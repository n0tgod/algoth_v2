#!/usr/bin/env python3
"""Проверки механики a82dcf58 — двойник по ИМЕНИ.

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть. Проверка,
которая не кусается, не проверяет ничего.

Что проверяется: пересадка геометрии в долях цены входа (и тейка, и
плеча, и ставки тира), пул часа и его два запрета, подбор дециля σ,
заранее назначенные розыгрыши, прочерк вместо нуля у ненайденного
двойника, отказ вместо пустоты, порог измеримости, вердиктовые фразы,
выведенные из чисел, заглядывание в будущее (σ и своя геометрия
двойника) и калибровочная пара.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import twin as T                                             # noqa: E402
import run_twin as RT                                        # noqa: E402
from twin import L                                           # noqa: E402

H = 3600


def quiet(_m):
    pass


# ------------------------------------------------------------ фикстуры

def _bars(prices, t0=1_786_000_000):
    return T.bars_of(prices, t0)


def _flat_then(n_pre, tail, start=100.0, jitter=0.0007, seed=3, dip=None):
    """Живой на вид ряд: дрожание до решения, заданный путь после.

    Подставной артефакт обязан выглядеть как живой — ровная полка до
    входа прячет ошибку построения уровней (восемь таких случаев).
    `dip` — провал и возврат внутри окна до решения: он оставляет
    структурные полки НИЖЕ входа, без которых лестница вырождается в
    одиночный вход и проверка геометрии ничего не проверяет.
    """
    rng = np.random.default_rng(seed)
    if dip is None:
        pre = list(start * np.exp(np.cumsum(rng.normal(0.0, jitter, n_pre))))
    else:
        half = n_pre // 2
        shape = (list(np.linspace(start, float(dip), half))
                 + list(np.linspace(float(dip), start, n_pre - half)))
        pre = [p * float(x) for p, x in
               zip(shape, np.exp(np.cumsum(rng.normal(0.0, jitter, n_pre))))]
    return pre + list(tail)


def _setup(entry, offs, take_frac, lev, mmr=0.005, k=None, pnl=0.0,
           exit_ts=0.0, sigma=50.0):
    return {"geo": {"off": list(offs), "take": float(take_frac),
                    "lev": float(lev), "k": len(offs)},
            "mmr": float(mmr), "lev": float(lev),
            "k": int(k if k is not None else len(offs)),
            "entry": float(entry), "sigma": float(sigma), "pnl": float(pnl),
            "exit": "срок", "exit_ts": float(exit_ts)}


class _Src:
    def __init__(self, series, tiers=None):
        self.series = series
        self.tiers = tiers or {}

    def bars(self, sym, t0, t1):
        return [b for b in (self.series.get(sym) or []) if t0 <= b[0] <= t1]


# --------------------------------------------------------- геометрия

def test_geometry_is_in_fractions_of_entry():
    entry, rungs = 250.0, [250.0, 242.5, 230.0, 215.0]
    geo = T.geometry(entry, rungs, 262.5, 3.0)
    assert abs(geo["off"][0]) < 1e-15, geo["off"]
    assert abs(geo["off"][2] - (230.0 / 250.0 - 1.0)) < 1e-15
    back, _tk = T.transplant(geo, entry)
    for a, b in zip(back, rungs):                # пересадка на себя — тождество
        assert abs(a - b) < 1e-9, (a, b)
    moved, _ = T.transplant(geo, 25.0)           # имя вдесятеро дешевле
    for a, b in zip(moved, rungs):
        assert abs(a - b / 10.0) < 1e-9, (a, b)
    print(f"ok  геометрия в долях входа: рунги {[round(o, 4) for o in geo['off']]}, "
          f"пересадка на себя тождественна, на цену/10 — та же форма")


def test_take_travels_as_a_fraction():
    geo = T.geometry(100.0, [100.0, 96.0], 104.0, 2.0)
    assert abs(geo["take"] - 0.04) < 1e-12, geo["take"]
    _r, tk = T.transplant(geo, 7.0)
    assert abs(tk - 7.28) < 1e-9, tk               # 7 × 1.04
    _r, tk2 = T.transplant(geo, 100.0)
    assert abs(tk2 - 104.0) < 1e-9, tk2
    print(f"ok  тейк едет долей: +4 % от входа → {tk:.4f} при входе 7.0")


# ------------------------------------------------------------ пул часа

def test_pool_excludes_gated_picks():
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    m = T.pool_mask(syms, {"AAAUSDT"}, set())
    assert list(m) == [False, True, True], list(m)
    # выбор часа лежит в `gated` по построению — значит двойником быть
    # не может, иначе контроль сравнивал бы книгу с собой
    assert not m[0]
    print("ok  пул часа не берёт гейтованных выборов (в них и сам выбор)")


def test_pool_excludes_non_crypto():
    syms = ["AAAUSDT", "TSMUSDT"]
    m = T.pool_mask(syms, set(), {"TSMUSDT"})
    assert list(m) == [True, False], list(m)
    assert "TSMUSDT" in T.UF.non_crypto_set()      # справочник, а не наш список
    print("ok  пул часа не берёт перпов не на криптоактив (universe_filter)")


# ------------------------------------------------------------ децили σ

def test_decile_of_sigma_inside_the_hour():
    vals = [float(x) for x in range(10, 110, 5)]          # 20 значений
    e = T.decile_edges(vals)
    assert e is not None and len(e) == T.N_DEC - 1
    assert T.decile_of(vals[0], e) == 0
    assert T.decile_of(vals[-1], e) == T.N_DEC - 1
    assert T.decile_of(float("nan"), e) is None            # не измерено ≠ ноль
    assert T.decile_edges([1.0, 2.0]) is None              # мало сечения
    print(f"ok  децили σ внутри часа: {len(e)} границ, край сечения "
          f"{T.decile_of(vals[-1], e)}, NaN даёт прочерк")


def test_twins_come_from_the_pick_decile():
    pool = list(range(20))
    dec = [i // 2 for i in range(20)]              # по два имени на дециль
    m, p = T.assign_twins(pool, dec, 3, 40, leg_id=7)
    assert all(x in (6, 7) for x in m), m          # дециль 3 = индексы 6 и 7
    assert set(p) - {6, 7}, p                      # без подбора — всё сечение
    empty, _ = T.assign_twins(pool, dec, 99, 5, leg_id=7)
    assert all(x is None for x in empty), empty    # пустой дециль — прочерк
    print(f"ok  двойник из дециля выбора: {sorted(set(m))}, без подбора "
          f"{len(set(p))} разных имён, пустой дециль даёт прочерк")


def test_draws_are_assigned_in_advance_by_seed():
    pool, dec = list(range(30)), [0] * 30
    a, _ = T.assign_twins(pool, dec, 0, 12, leg_id=5, seed=T.SEED)
    b, _ = T.assign_twins(pool, dec, 0, 12, leg_id=5, seed=T.SEED)
    c, _ = T.assign_twins(pool, dec, 0, 12, leg_id=6, seed=T.SEED)
    d, _ = T.assign_twins(pool, dec, 0, 12, leg_id=5, seed=T.SEED + 1)
    assert a == b, (a, b)                    # порядок обхода ни при чём
    assert a != c and a != d, (a, c, d)      # ключ — (зерно, розыгрыш, нога)
    print(f"ok  розыгрыши назначены заранее: тот же ключ даёт тот же список "
          f"{a[:4]}, другая нога — другой")


# ---------------------------------------------------- будущее не видно

def test_sigma_does_not_look_into_the_future():
    at = 1_786_000_000 + 600 * 60
    px = _flat_then(600, list(np.linspace(100.0, 100.0, 400)))
    b1 = _bars(px)
    s1 = T.sigma_at(b1, [x[0] for x in b1], at)
    px2 = list(px[:600]) + [p * (1.0 + 0.05 * i) for i, p in
                            enumerate(px[600:])]      # будущее переписано
    b2 = _bars(px2)
    s2 = T.sigma_at(b2, [x[0] for x in b2], at)
    assert s1 == s1 and s1 > 0, s1
    assert s1 == s2, (s1, s2)
    print(f"ok  σ смотрит только прошлое: {s1:.3f} б.п. до и после "
          f"переписывания будущего")


def test_own_geometry_does_not_look_into_the_future():
    at = 1_786_000_000 + 700 * 60
    px = _flat_then(700, list(np.linspace(100.0, 92.0, 500)), seed=11,
                    dip=88.0)
    b1 = _bars(px)
    ts = [x[0] for x in b1]
    r1 = T.twin_window(b1, ts, at)
    assert r1 is not None
    g1, _ = T.own_geometry(r1[0], r1[1], 300.0, lambda n: 0.005)
    px2 = list(px[:700]) + [p * (1.0 + 0.4 * i / 500.0)
                            for i, p in enumerate(px[700:])]
    b2 = _bars(px2)
    r2 = T.twin_window(b2, [x[0] for x in b2], at)
    g2, _ = T.own_geometry(r2[0], r2[1], 300.0, lambda n: 0.005)
    assert g1 is not None and g2 is not None
    assert g1["rungs"] == g2["rungs"], (g1["rungs"], g2["rungs"])
    assert g1["lev"] == g2["lev"], (g1["lev"], g2["lev"])
    print(f"ok  своя геометрия двойника (T2) строится на прошлом: рунгов "
          f"{len(g1['rungs'])}, плечо {g1['lev']:.2f}× — будущее не меняет")


def test_own_geometry_says_why_it_is_absent():
    at = 1_786_000_000 + 700 * 60
    b = _bars(_flat_then(700, [100.0] * 300, seed=5))
    ts = [x[0] for x in b]
    win, now_i = T.twin_window(b, ts, at)
    g, why = T.own_geometry(win, now_i, -120.0, lambda n: 0.005)
    assert g is None and "mfe" in why, why       # прочерк С ПРИЧИНОЙ
    print(f"ok  T2 у имени без длинного обещания — прочерк с причиной: {why}")


# ------------------------------------------------------- проход двойников

def _twin_case(tail, lev=3.0, mmr=0.005, offs=(0.0, -0.03, -0.07, -0.12),
               take=0.05, mmr_from="pick"):
    """Один выбор, один двойник, один розыгрыш — на подставных барах."""
    at = float(1_786_000_000 + 700 * 60)
    px = _flat_then(700, tail, seed=17)
    src = _Src({"TWNUSDT": _bars(px)}, tiers={})
    setups = [_setup(400.0, offs, take, lev, mmr=mmr)]
    names = [("TWNUSDT", 250.0, at)]
    MT = np.array([[0]], dtype=np.int32)
    PT = np.array([[-1]], dtype=np.int32)
    res = RT.pass_two(setups, MT, PT, names, src.bars, {}, log=quiet,
                      tag="test", mmr_from=mmr_from)
    win, now_i = T.twin_window(src.series["TWNUSDT"],
                               [x[0] for x in src.series["TWNUSDT"]], at)
    hold = win[now_i:]
    return res, hold, setups[0]


def test_twin_gets_the_pick_leverage_and_tier():
    """Плечо и ставка тира ПЕРЕСАЖИВАЮТСЯ, а не считаются заново."""
    tail = list(np.linspace(100.0, 66.0, 300)) + [66.0] * 200
    res, hold, st = _twin_case(tail)
    e = float(hold[0][1])
    rungs = [e * (1.0 + o) for o in st["geo"]["off"]]
    ref = L.simulate_dca(hold, rungs, T.WEIGHTS, 1.0, st["lev"], st["mmr"],
                         take_px=e * (1.0 + st["geo"]["take"]),
                         floor_frac=T.FLOOR_FRAC)
    got = float(res["R_M"][0, 0])
    assert ref["exit"] in ("пол", "ликвидация"), ref["exit"]
    assert got == ref["pnl_frac"], (got, ref["pnl_frac"])
    other = L.simulate_dca(hold, rungs, T.WEIGHTS, 1.0, 1.0, st["mmr"],
                           take_px=e * (1.0 + st["geo"]["take"]),
                           floor_frac=T.FLOOR_FRAC)
    assert abs(other["pnl_frac"] - ref["pnl_frac"]) > 1e-6   # плечо решает
    print(f"ok  двойник взял плечо выбора {st['lev']}× и его ставку тира: "
          f"исход {ref['exit']} {got:+.4f} (при 1× было бы "
          f"{other['pnl_frac']:+.4f})")


def test_twin_mmr_comes_from_the_pick_not_from_its_own_tier():
    tail = list(np.linspace(100.0, 66.0, 300)) + [66.0] * 200
    a, hold, st = _twin_case(tail, mmr=0.005)
    e = float(hold[0][1])
    rungs = [e * (1.0 + o) for o in st["geo"]["off"]]
    tk = e * (1.0 + st["geo"]["take"])
    with_own = L.simulate_dca(hold, rungs, T.WEIGHTS, 1.0, st["lev"],
                              T.FLAT_MMR, take_px=tk,
                              floor_frac=T.FLOOR_FRAC)
    with_pick = L.simulate_dca(hold, rungs, T.WEIGHTS, 1.0, st["lev"],
                               st["mmr"], take_px=tk,
                               floor_frac=T.FLOOR_FRAC)
    assert abs(with_own["pnl_frac"] - with_pick["pnl_frac"]) > 1e-6
    assert float(a["R_M"][0, 0]) == with_pick["pnl_frac"]
    b, _h, _s = _twin_case(tail, mmr=0.005, mmr_from="own")
    assert float(b["R_M"][0, 0]) == with_own["pnl_frac"]
    print(f"ok  ставка тира пересажена от выбора: {with_pick['pnl_frac']:+.4f}; "
          f"ключ --mmr own считает по тиру двойника "
          f"({with_own['pnl_frac']:+.4f})")


def test_missing_twin_bars_are_a_dash_not_zero():
    at = float(1_786_000_000 + 700 * 60)
    src = _Src({})                                   # баров нет вовсе
    setups = [_setup(400.0, (0.0, -0.05), 0.04, 2.0)]
    names = [("GONEUSDT", 200.0, at)]
    res = RT.pass_two(setups, np.array([[0]], dtype=np.int32),
                      np.array([[-1]], dtype=np.int32), names, src.bars, {},
                      log=quiet, tag="test")
    assert np.isnan(res["R_M"][0, 0]), res["R_M"]
    assert res["no_bars"] == 1, res["no_bars"]
    print("ok  двойник без баров — прочерк (NaN) и счётчик причины, не ноль")


# --------------------------------------------------------- сквозной путь

def _run_synth(planted=False, draws=20, **kw):
    picks, pools, src, pmax = RT.synth(planted=planted, **kw)
    s = RT.core(picks, pools, src.bars, src.tiers, draws=draws, log=quiet,
                tag="test", use_cache=False)
    return s, picks, pools, src, pmax


def test_end_to_end_names_hours_and_books():
    s, picks, pools, _src, _p = _run_synth()
    assert s["positions"] == len(picks), s.get("refused")
    assert s["cover"] == 1.0, s["cover"]
    # двойник обязан быть из сечения СВОЕГО часа и не быть самим выбором
    pool_syms = set(next(iter(pools.values()))["syms"])
    pick_syms = {g["sym"] for g in picks}
    assert not (pool_syms & pick_syms), pool_syms & pick_syms
    b = s["book_S"]
    assert b["capital"] == 10000.0 and b["ticket"] == 25.0, b
    assert s["book_draws"] >= 1
    assert s["null_t1s"]["draws"] == 20, s["null_t1s"]["draws"]
    assert s["null_t1"] and s["null_t2"] is not None
    assert "no_top3_days" in s["conc_S"], s["conc_S"]
    print(f"ok  сквозной прогон: позиций {s['positions']}, покрытие "
          f"{s['cover'] * 100:.0f} %, книг-двойников {s['book_draws']}, "
          f"касса ${b['capital']:.0f}/билет ${b['ticket']:.0f}, "
          f"вердикт «{s['verdict']['head'][:24]}…»")


def test_no_ladder_positions_are_counted_apart():
    s, _p, _q, _s, _m = _run_synth()
    assert s.get("n_ladder") is not None and s.get("n_no_ladder") is not None
    assert s["n_ladder"] + s["n_no_ladder"] == s["positions"]
    print(f"ok  выборы без структурной лестницы считаются отдельно: "
          f"{s['n_no_ladder']} из {s['positions']} (у них плечо 1× и один "
          f"рунг, двойник получает то же)")


def test_refuses_instead_of_reporting_emptiness():
    picks, pools, _src, _p = RT.synth()
    empty = _Src({})
    s = RT.core(picks, pools, empty.bars, {}, draws=20, log=quiet,
                tag="test", use_cache=False)
    assert s.get("refused") and "позиций ноль" in s["refused"], s
    assert "verdict" not in s, s.keys()
    txt = RT.report(s)
    assert "ОТКАЗ" in txt, txt[:200]
    print(f"ok  ноль позиций при непустом входе — отказ: «{s['refused'][:52]}…»")


def test_refuses_when_draws_are_too_few():
    picks, pools, src, _p = RT.synth()
    s = RT.core(picks, pools, src.bars, src.tiers, draws=3, log=quiet,
                tag="test", use_cache=False)
    assert s.get("refused") and "розыгрыш" in s["refused"], s
    print(f"ok  розыгрышей меньше {T.MIN_DRAWS} — отказ, а не полоса из "
          f"горстки книг")


# ------------------------------------------------------------- вердикты

def _nulls(real_med, real_mean, edge):
    draws = [[edge - 0.01 + 0.0002 * i] * 1 for i in range(40)]
    med = [d[0] for d in draws]
    return {"median": T.P.null_place(real_med, med),
            "mean": T.P.null_place(real_mean, med)}


def test_verdict_choice_is_derived_from_numbers():
    lo = T.verdict_choice(_nulls(-0.01, -0.01, 0.02))
    assert lo["killed"] is True and "НЕ бьёт" in lo["why"][0], lo
    hi = T.verdict_choice(_nulls(0.5, 0.5, 0.02))
    assert hi["killed"] is False, hi
    assert any("против" in p for p in hi["parts"]), hi["parts"]
    none = T.verdict_choice({"median": None, "mean": None})
    assert none["killed"] is None and "не измерено" in none["why"][0]
    print(f"ok  фраза убийцы 1 выведена из чисел: «{lo['why'][0][:46]}…» / "
          f"«{hi['why'][0][:34]}…»; непосчитанное — третий ответ")


def test_pair_killer_needs_both_median_and_mean():
    good_pos = {"n": 9, "median": 0.02, "mean": 0.03, "s_beats_t": 0.7,
                "same_sign": True}
    good_day = dict(good_pos)
    boot = {"days": 9, "median": 0.02, "mean": 0.03, "lo": 0.01, "hi": 0.05,
            "covers_zero": False}
    assert T.verdict_pair(good_pos, good_day, boot)["killed"] is False
    split = dict(good_pos, mean=-0.04, same_sign=False)
    v = T.verdict_pair(split, good_day, boot)
    assert v["killed"] is True and "знаком" in v["why"][0], v
    v0 = T.verdict_pair(good_pos, good_day,
                        dict(boot, lo=-0.01, covers_zero=True))
    assert v0["killed"] is True and "накрывает ноль" in v0["why"][0]
    print("ok  убийца 2 требует и медианы, и среднего, и интервала мимо нуля")


def test_form_killer_reads_bite_the_right_way():
    st_s = {"med": 5.0, "worst": -3.0, "bite": 2.0}
    draws = [{"med": 1.0, "worst": -9.0, "bite": 9.0} for _ in range(30)]
    nl = T.form_nulls(st_s, draws)
    assert nl["bite"]["lower_is_better"] and nl["bite"]["beats"], nl["bite"]
    v = T.verdict_form(nl)
    assert v["killed"] is False, v
    bad = T.form_nulls({"med": -1.0, "worst": -30.0, "bite": 40.0}, draws)
    assert T.verdict_form(bad)["killed"] is True
    print(f"ok  убийца 3: укус судится «меньше — лучше» "
          f"({st_s['bite']} против края {nl['bite']['edge']})")


def test_concentration_killer_uses_no_top3_days():
    good = {"no_top3_days": T.P.null_place(90.0, [10.0 + i for i in range(30)]),
            "no_best_name": T.P.null_place(90.0,
                                           [10.0 + i for i in range(30)])}
    assert T.verdict_conc(good)["killed"] is False
    bad = dict(good, no_top3_days=T.P.null_place(
        1.0, [10.0 + i for i in range(30)]))
    v = T.verdict_conc(bad)
    assert v["killed"] is True and "одного эпизода" in v["why"][0], v
    print("ok  убийца 4 судит колонку «без 3 лучших суток», не итог")


def test_coverage_gates_the_verdict_with_a_number():
    ok = T.verdict_cover(0.95, 1000)
    assert ok["ok"] and "95.0 %" in ok["why"][0], ok
    low = T.verdict_cover(0.5, 1000)
    assert not low["ok"] and "ТОЛЬКО по измеренным" in low["why"][0], low
    v = T.verdict(low, [{"killed": False, "why": ["x"]}] * 4)
    assert v["why"][0] is low["why"][0], v["why"][:1]
    print(f"ok  измеримость раньше убийц: {T.COVER_MIN * 100:.0f} % — порог, "
          f"ниже вердикт только по измеренным")


# ------------------------------------------------------- калибровочная пара

def test_calibration_finds_the_planted_move_and_is_quiet_on_noise():
    c = RT.calibrate(draws=20, log=quiet)
    assert c["planted_laid"] is True, c.get("planted_move")
    assert c["planted_move"] > 0.1, c["planted_move"]
    assert c["found"] is True, ("подсаженное не найдено",
                                c["planted"]["null_t1s"]["nulls"])
    assert c["quiet"] is True, ("на шуме не промолчала",
                                c["noise"]["null_t1s"]["nulls"])
    assert c["ok"] is True
    txt = RT.cal_report(c)
    assert "подделка легла" in txt and "Итог калибровки" in txt
    md = c["planted"]["null_t1s"]["nulls"]["median"]
    print(f"ok  калибровка: подделка легла на {c['planted_move'] * 100:.0f} %, "
          f"подсаженное найдено (S {md['real']:+.4f} против края "
          f"{md['edge']:+.4f}), на шуме молчит")


def test_concentration_columns_stand_at_every_arm():
    """Колонки концентрации обязаны стоять у КАЖДОЙ руки, не у одной."""
    s, _p, _q, _sr, _m = _run_synth()
    for key in ("conc_nulls", "conc_nulls_t1", "conc_nulls_t2"):
        nl = (s.get(key) or {}).get("no_top3_days")
        assert nl and "edge" in nl, (key, s.get(key))
    txt = RT.report(s)
    for ttl in ("концентрация против книг T1σ (вердикт)",
                "концентрация против книг T1",
                "концентрация против книг T2"):
        assert ttl in txt, ttl
    print(f"ok  колонки концентрации у всех рук: T1σ, T1, T2 — книг с формой "
          f"{s['book_draws']}/{s['book_draws_t1']}/{s['book_draws_t2']}")


def test_memory_self_stop_names_the_number():
    """Выше предела прогон снимает СЕБЯ, и говорит число, а не молчит."""
    assert RT.mem_stop(None, "нет предела") is None      # предела нет — идём
    rss = RT.mem_stop(10 ** 9, "предел заведомо велик")
    assert rss and rss > 0, rss
    try:
        RT.mem_stop(1, "предел заведомо мал")
    except SystemExit as e:
        assert "ОСТАНОВ" in str(e) and "предела 1 МБ" in str(e), str(e)
    else:
        raise AssertionError("прогон не снял себя выше предела памяти")
    lim = RT.mem_limit_mb(share=0.6, log=quiet)
    have = RT.mem_available_mb()
    # Доступная память живая и между двумя чтениями гуляет — сверяется
    # ДОЛЯ, а не равенство: точное сравнение падало бы от соседа по машине.
    assert lim is None or 0 < lim < have, (lim, have)
    assert lim is None or abs(lim / float(have) - 0.6) < 0.1, (lim, have)
    assert RT.MEM_SHARE == 0.6, RT.MEM_SHARE
    print(f"ok  самоостанов по памяти: RSS {rss} МБ, предел прогона {lim} МБ "
          f"({RT.MEM_SHARE:.0%} доступной)")


def test_report_prints_both_median_and_mean_and_the_verdict():
    s, _p, _q, _s, _m = _run_synth()
    txt = RT.report(s)
    for need in ("медиана позиции", "среднее позиции", "без 3 лучших суток",
                 "Измеримость", "T1 — двойник БЕЗ подбора σ",
                 "T2 — тот же двойник со СВОЕЙ геометрией",
                 s["verdict"]["head"][:20]):
        assert need in txt, need
    print(f"ok  отчёт печатает обе величины, диагностику и вердикт "
          f"({len(txt)} символов)")


CHECKS = [
    test_geometry_is_in_fractions_of_entry,
    test_take_travels_as_a_fraction,
    test_pool_excludes_gated_picks,
    test_pool_excludes_non_crypto,
    test_decile_of_sigma_inside_the_hour,
    test_twins_come_from_the_pick_decile,
    test_draws_are_assigned_in_advance_by_seed,
    test_sigma_does_not_look_into_the_future,
    test_own_geometry_does_not_look_into_the_future,
    test_own_geometry_says_why_it_is_absent,
    test_twin_gets_the_pick_leverage_and_tier,
    test_twin_mmr_comes_from_the_pick_not_from_its_own_tier,
    test_missing_twin_bars_are_a_dash_not_zero,
    test_end_to_end_names_hours_and_books,
    test_no_ladder_positions_are_counted_apart,
    test_refuses_instead_of_reporting_emptiness,
    test_refuses_when_draws_are_too_few,
    test_verdict_choice_is_derived_from_numbers,
    test_pair_killer_needs_both_median_and_mean,
    test_form_killer_reads_bite_the_right_way,
    test_concentration_killer_uses_no_top3_days,
    test_coverage_gates_the_verdict_with_a_number,
    test_calibration_finds_the_planted_move_and_is_quiet_on_noise,
    test_concentration_columns_stand_at_every_arm,
    test_memory_self_stop_names_the_number,
    test_report_prints_both_median_and_mean_and_the_verdict,
]


if __name__ == "__main__":
    # Каждая проверка идёт до конца, а её провал печатается ИМЕНЕМ:
    # приёмка требует падения ИМЕННО названной проверки, и первое
    # исключение, обрывающее прогон, скрыло бы остальные — тогда контроль,
    # роняющий что-то постороннее, выглядел бы кусающимся.
    bad = []
    for c in CHECKS:
        try:
            c()
        except Exception as e:                              # noqa: BLE001
            bad.append(c.__name__)
            print(f"ПРОВАЛ {c.__name__}: {type(e).__name__}: {e}")
    if bad:
        print(f"\nпровалено {len(bad)} из {len(CHECKS)}: " + ", ".join(bad))
        sys.exit(1)
    print(f"\nвсе {len(CHECKS)} проверки прошли")
