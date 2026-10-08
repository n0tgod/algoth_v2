#!/usr/bin/env python3
"""Проверки замера отбора кассы: разметка «взято / причина» в порядке
кассы, «имя занято» по времени позиции, полосы возраста, массы и доли,
нуль внутри часа (калибровка: взятые хуже — находится; взятые случайные —
молчит), суд по порядку, отчёт без пустот."""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_select as SS                                     # noqa: E402
import short_weeks as SW                                      # noqa: E402
import run_short as S                                         # noqa: E402
import test_short_weeks as T                                  # noqa: E402

H = T.H
AT0 = T.AT0
DAY = 86400.0


def _dec(sym, at, edge):
    return {"sym": sym, "at": at, "edge": edge, "date": SW.date_of(at), "week": SW.week_of(at), "fwd": -10.0}


def _cache(entries):
    """entries: (book, sym, at, lev) → кэш реплея семейства по ключу линейки."""
    return {(S.BOOKS[bk], sym, round(at, 3)): {"lev": lev, "state": "closed"} for bk, sym, at, lev in entries}


def test_reason_follows_cash_order_and_held_name_by_time():
    launch = {"OLD": AT0 - 30 * DAY, "YOUNG": AT0 - 2 * DAY, "OLD2": AT0 - 90 * DAY}
    cache = _cache([("aggr_h", "OLD", AT0, 2.0), ("aggr_h", "OLD", AT0 + H, 8.0), ("aggr_h", "OLD", AT0 + 2 * H, 8.0),
                    ("aggr_h", "OLD", AT0 + 30 * H, 8.0)])
    rows_by_book = {"aggr_h": [{"sym": "OLD", "at": AT0 + H, "exit_ts": AT0 + 25 * H, "margin": 1, "lev": 8}]}
    decs = [_dec("OLD", AT0, 10), _dec("YOUNG", AT0, 10), _dec("NOFILE", AT0, 10), _dec("OLD2", AT0, 10),
            _dec("OLD", AT0 + H, 10), _dec("OLD", AT0 + 2 * H, 10), _dec("OLD", AT0 + 30 * H, 10)]
    lab = SS.label(decs, cache, rows_by_book, launch, books=("aggr_h",))
    got = [d["by"]["aggr_h"] for d in lab]
    # плечо 2 < 4; возраст 2 сут; возраст НЕИЗВЕСТЕН — тоже «возраст» (касса не входит); старое без записи — «нет записи»;
    # взято; имя занято (вход AT0+H, выход AT0+25H); очередь (после выхода)
    assert got == ["плечо", "возраст", "возраст", "нет записи", "взято", "имя занято", "очередь"], got
    assert [d["band"] for d in lab][:4] == ["30–60 сут", "<3 сут", SS.PA.UNKNOWN, "≥60 сут"]
    # у книги без гейта плеча «плечо» не возникает
    cache2 = _cache([("optimal_h", "OLD", AT0, 2.0)])
    lab2 = SS.label([_dec("OLD", AT0, 10)], cache2, {"optimal_h": []}, launch, books=("optimal_h",))
    assert lab2[0]["by"]["optimal_h"] == "очередь"


def _labeled(worse_taken, hours=40, per_hour=6, seed=1):
    """Решения: в каждом часе `per_hour`, взяты 2; при worse_taken взятые хуже на 150 б.п."""
    rng = random.Random(seed)
    out = []
    for h in range(hours):
        at = AT0 + h * H
        for i in range(per_hour):
            taken = i < 2
            e = rng.gauss(100, 200) - (150 if (taken and worse_taken) else 0)
            d = _dec(f"S{i}", at, e)
            d["band"] = "≥60 сут" if i % 2 else "<3 сут"
            d["by"] = {"optimal_h": SS.TAKEN if taken else "очередь", "aggr_h": SS.TAKEN if taken else "возраст"}
            out.append(d)
    return out


def test_null_within_hour_calibration_pair():
    bad = SS.null_within_hour(_labeled(True), lambda d: d["by"]["optimal_h"] == SS.TAKEN, seeds=200, worse=True)
    assert bad["n"] == 80 and bad["p"] <= 0.02, bad
    fair = SS.null_within_hour(_labeled(False, seed=7), lambda d: d["by"]["optimal_h"] == SS.TAKEN, seeds=200, worse=True)
    assert fair["p"] > 0.1, fair
    # всё помечено или ничего — нуля нет, а не ноль
    assert SS.null_within_hour(_labeled(False), lambda d: True, seeds=5)["p"] is None


def test_half_summary_masses_and_judge_order():
    lab = _labeled(True)
    hv = SS.half_summary(lab, seeds=100, books=("optimal_h", "aggr_h"))
    r = hv["books"]["optimal_h"]["reasons"]
    assert r[SS.TAKEN]["n"] == 80 and r["очередь"]["n"] == 160 and r["возраст"] is None
    assert abs(r["очередь"]["mass"] - sum(d["edge"] for d in lab if d["by"]["optimal_h"] == "очередь")) < 1e-6
    assert hv["bands"]["<3 сут"]["n"] == 120 and hv["bands"]["≥60 сут"]["n"] == 120
    assert set(hv["band_null"]) == {"<3 сут", "≥60 сут"}
    j = SS.judge([None, hv])
    assert j["kind"] == "systemic" and j["per"]["optimal_h"]["top"] == "очередь" and j["per"]["aggr_h"]["top"] == "возраст"
    assert not j["same_top"] and "причины у книг разные" in SS.verdict(j)
    fair = SS.half_summary(_labeled(False, seed=7), seeds=100, books=("optimal_h", "aggr_h"))
    assert SS.judge([None, fair])["kind"] == "noise"
    assert SS.judge([hv, {}])["kind"] == "unmeasured"


def test_end_to_end_report_on_synthetic_world():
    with tempfile.TemporaryDirectory() as tmp:
        T._world(tmp, hours=24 * 10, fall=lambda k: T.NAMES[8:10])
        mkt = T._mkt(tmp)
        legs = []
        for k in range(0, 24 * 10, 6):
            at = AT0 + k * H
            legs += [T._leg(T.NAMES[8], at), T._leg(T.NAMES[9], at), T._leg(T.NAMES[0], at), T._leg(T.NAMES[1], at)]
        launch = {s: AT0 - 40 * DAY for s in T.NAMES}
        launch[T.NAMES[9]] = AT0 + 5 * DAY                                 # листинг на границе половин: моложе 7 сут всё окно
        cache = {}
        for g in legs:
            for bk in SS.BOOKS:
                cache[(S.BOOKS[bk], g["sym"], round(g["at"], 3))] = {"lev": 6.0, "state": "closed"}
        # касса взяла стоячие имена N00 и N01 во всех книгах — отбор против листа
        rows = {bk: [{"sym": s, "at": g["at"], "exit_ts": g["at"] + 24 * H, "margin": 100, "lev": 6, "usd": 0.0}
                     for g in legs for s in (T.NAMES[0], T.NAMES[1]) if g["sym"] == s] for bk in SS.BOOKS}
        import short_levcap as LC
        orig = LC.cash_rows
        LC.cash_rows = lambda *a, **k: rows
        try:
            s = SS.run(log=lambda *a: None, legs_=legs, names=T.NAMES, mkt=mkt, cache=cache, ctx={}, launch=launch,
                       seeds=30, min_xs=5)
        finally:
            LC.cash_rows = orig
        assert not s.get("error") and s["n_measured"] == 160
        b = s["halves"][1]["books"]["optimal_h"]["reasons"]
        n2 = s["halves"][1]["n"]
        assert b[SS.TAKEN]["n"] == n2 // 2 and b["возраст"]["n"] == n2 // 4 and b["очередь"]["n"] == n2 // 4, \
            {k: (v or {}).get("n") for k, v in b.items()}
        assert b["возраст"]["edge"] > 150 and b[SS.TAKEN]["edge"] == 0.0
        assert s["judge"]["kind"] == "systemic", s["judge"]
        txt = SS.report(s)
        for must in ("1-я половина", "2-я половина", "полоса возраста", "Вердикт (из чисел)", "<3 сут", "возраст"):
            assert must in txt, must
        assert "None" not in txt


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    import traceback
    bad = 0
    for t in TESTS:
        try:
            t()
            print("ok", t.__name__)
        except Exception:                                      # noqa: BLE001
            bad += 1
            print("FAIL", t.__name__)
            traceback.print_exc()
    sys.exit(1 if bad else 0)
