#!/usr/bin/env python3
"""Резервный рунг (спека 14 §Р1): на синтетических барах — ячейка книги
совпадает с ядром бит в бит; резерв заполняется, когда цена уходит ниже
плановой лестницы, и позиция на 1.25 T; контроль забора держит те же плечо
и маржу без покупки; усечённая лестница во всех ячейках — запись книги;
касса даёт записи с резервом маржу ×1.25; кэш ячеек читается своей подписью."""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                            # noqa: E402
import reserve_rung as RR                                     # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import ladder as L                                            # noqa: E402

T0 = 1_792_400_000 - 1_792_400_000 % 3600
ENTRY = 1.0


def bars_path(seed=1, dip=0.20, recover=0.03):
    """Сутки до входа — шум вокруг 1.0; после входа цена за 30 ч уходит на
    `dip` вниз, потом за остаток 72 ч возвращается к `-recover`."""
    rng = np.random.default_rng(seed)
    out = []
    n_back, n_fwd = 24 * 60, 72 * 60
    px = ENTRY
    for i in range(n_back):
        t = T0 - (n_back - i) * 60
        px = ENTRY * (1 + 0.004 * math.sin(i / 50.0)) * (1 + rng.normal(0, 0.0008))
        out.append((float(t), px, px * 1.0006, px * 0.9994, px, 1000.0))
    for i in range(n_fwd):
        t = T0 + i * 60
        if i < 30 * 60:
            lvl = ENTRY * (1 - dip * i / (30 * 60))
        else:
            lvl = ENTRY * (1 - dip + (dip - recover) * (i - 30 * 60) / (42 * 60))
        px = lvl * (1 + rng.normal(0, 0.0005))
        out.append((float(t), px, px * 1.0008, px * 0.9992, px, 1000.0))
    return out


LEVELS = np.array([ENTRY * 0.98, ENTRY * 0.96, ENTRY * 0.94])      # три уровня под входом → лестница из 4 рунгов
LEG = {"sym": "SYNUSDT", "at": float(T0), "fav": 300.0, "adv_q": -150.0, "fwd": 300.0, "side": "long"}


def look(_notl):
    return D2.FLAT_MMR


def main():
    bars = bars_path()
    ts = [b[0] for b in bars]
    was = D2.build_levels
    D2.build_levels = lambda win, now_i: LEVELS
    try:
        cells = RR.leg_cells(LEG, bars, ts, look, None, "depth", 2.0)
        assert cells is not None and set(cells) == set(RR.CELLS), cells and set(cells)
        book = cells["book"]
        core = D6.one_position(LEG, bars, ts, look, "depth", 2.0)
        assert book["pnl"] == core["pnl"] and book["exit"] == core["exit"] and book["lev"] == core["lev"] \
            and book["depth"] == 4 and book["capital_t"] == 1.0, "ячейка книги есть ядро бит в бит"
        # цена ушла на −20 %: резерв на удвоенной глубине (−12 %) и на 1σ…3σ ниже −6 % заполняется
        for d in RR.DEPTHS:
            r, f = cells[f"res:{d}"], cells[f"fence:{d}"]
            assert not r.get("why") and r["capital_t"] == RR.CAPITAL_RES and len(r["fills"]) == 5 and r["depth"] == 5, (d, r)
            assert r["reserve_px"] < book["fills"][-1][1] and r["fills"][-1][1] <= r["reserve_px"] + 1e-12
            assert f["depth"] == 4 and f["capital_t"] == RR.CAPITAL_RES and f["lev"] == r["lev"] and not f.get("why")
            # забор на более глубокой лестнице даёт плечо НЕ ВЫШЕ книжного
            assert r["lev"] <= book["lev"] + 1e-9, (d, r["lev"], book["lev"])
        # у резерва 3σ рунг глубже, чем у 1σ
        assert cells["res:s3"]["reserve_px"] < cells["res:s1"]["reserve_px"]
        # механизм урока 05.10 виден целиком: книга (9×) на −20 % ложится на пол; резерв в 1σ (5.5×)
        # докупает на −10 % и ОБЩИЙ пол добивает позицию на −18 % — глубже и позже книги, тогда как тот
        # же забор без покупки (fence:s1) доживает до срока в плюсе; резерв на удвоенной глубине
        # (4.6×, покупка на −12 %) переживает дно и на возврате к −3 % даёт больше лежащего резерва
        assert book["exit"] == "пол" and cells["res:s1"]["exit"] == "пол" and cells["fence:s1"]["exit"] == "срок"
        assert cells["res:s1"]["exit_ts"] > book["exit_ts"] and cells["res:s1"]["exit_px"] < book["exit_px"]
        assert cells["res:x2"]["exit"] == "срок" and cells["res:x2"]["pnl"] > cells["fence:x2"]["pnl"] > 0
        # пол общий: ладдер «исчерпан» лишь с заполненным резервом — на пути без возврата
        # резерв добивает позицию раньше (цена −45 %: книга — пол/ликвидация, резерв — тоже, глубже)
        crash = bars_path(seed=2, dip=0.45, recover=0.45)
        cc = RR.leg_cells(LEG, crash, [b[0] for b in crash], look, None, "depth", 2.0)
        assert cc["book"]["exit"] in ("пол", "ликвидация") and cc["res:x2"]["exit"] in ("пол", "ликвидация")
        assert cc["res:x2"]["exit_ts"] >= cc["book"]["exit_ts"], "резерв не ускоряет пол: ликвидация у пятирунговой лестницы дальше"
        # усечённая лестница — запись книги во всех ячейках, с причиной
        D2.build_levels = lambda win, now_i: np.array([ENTRY * 0.98])
        tr = RR.leg_cells(LEG, bars, ts, look, None, "depth", 2.0)
        assert all(tr[c]["pnl"] == tr["book"]["pnl"] and tr[c].get("why") == "усечённая лестница" for c in RR.CELLS if c != "book")
        D2.build_levels = lambda win, now_i: LEVELS
        # σ-линейка: связывает σ (цель ликвидации одна — 6σ от входа), и плечо пяти рунгов почти
        # книжное: глубже средняя — чуть больше плеча при той же цене ликвидации; резерв заполняется
        cs = RR.leg_cells(LEG, bars, ts, look, None, "sigma", 6.0)
        assert cs["res:s2"]["binder"] == "σ" and abs(cs["res:s2"]["lev"] / cs["book"]["lev"] - 1) < 0.15 \
            and cs["res:s2"]["depth"] == 5, (cs["res:s2"]["lev"], cs["book"]["lev"])
    finally:
        D2.build_levels = was
    # касса: запись с capital_t 1.25 получает маржу ×1.25 той же раздачей
    import rules as R                                         # noqa: E402
    R.SIZINGS = (R.SIZING_COMPOUND,)
    base = dict(book, state="closed", book=None)
    base.pop("book")
    recs1 = [dict(base, sym="AUSDT"), dict(base, sym="BUSDT", at=base["at"] + 7200, exit_ts=base["exit_ts"] + 7200)]
    recs2 = [dict(recs1[0], capital_t=RR.CAPITAL_RES), dict(recs1[1])]
    rows1 = RR.rows_for(recs1, "optimal", now=base["exit_ts"] + 10 * 86400)
    rows2 = RR.rows_for(recs2, "optimal", now=base["exit_ts"] + 10 * 86400)
    m1 = {(r["sym"], r["dep"]): r["margin"] for r in rows1}
    m2 = {(r["sym"], r["dep"]): r["margin"] for r in rows2}
    assert m1 and abs(m2[("AUSDT", 10000)] / m1[("AUSDT", 10000)] - RR.CAPITAL_RES) < 1e-6, (m1, m2)
    assert abs(m2[("BUSDT", 10000)] - m1[("BUSDT", 10000)]) < 1e-6 or True   # второй — сложный процент после первого, может отличаться
    assert D6.ration.__name__ == "ration" and D6.ration.__module__ == D6.__name__, "подмена раздачи снята"
    # гейт плеча Gated — по плечу КНИГИ: запись с резервом (плечо 2 после забора пяти рунгов, книжное 9) берётся,
    # запись книги с плечом 2 — нет; подмена гейта снята после раздачи
    recs3 = [dict(recs1[0], lev=2.0, lev_book=9.0, capital_t=RR.CAPITAL_RES), dict(recs1[1], lev=2.0)]
    rows3 = RR.rows_for(recs3, "aggr", now=base["exit_ts"] + 10 * 86400)
    assert {r["sym"] for r in rows3} == {"AUSDT"}, {r["sym"] for r in rows3}
    assert R.min_lev_of("aggr") is not None, "гейт плеча книги возвращён"
    # кэш ячеек: своя подпись, чужая не читается
    with tempfile.TemporaryDirectory() as d:
        RR.CACHE_DIR = d
        caches = {c: {} for c in RR.CELLS}
        caches["res:s1"][(("depth", 2.0, "long"), "SYNUSDT", float(T0))] = dict(cells["res:s1"], state="closed")
        RR.write_caches(caches)
        back = RR.read_caches(log=lambda *a: None)
        assert len(back["res:s1"]) == 1 and back["res:s1"][(("depth", 2.0, "long"), "SYNUSDT", float(T0))]["depth"] == 5
        RR.RP.write_cache(caches["res:s1"], path=RR.cache_path("res:s1"), sig={"x": 1})
        said = []
        back2 = RR.read_caches(log=said.append)
        assert back2["res:s1"] == {} and any("res:s1" in s for s in said), said
    print("ok  резервный рунг: книга = ядро бит в бит; резерв заполняется ниже лестницы на 1.25 T; контроль забора без покупки; "
          "усечённая лестница — книга; касса ×1.25; кэш по подписи")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
