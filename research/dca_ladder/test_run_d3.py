#!/usr/bin/env python3
"""Тесты D3 — граница забора, портрет хвоста, покрытие опционами.

Проверяется то, где ошибка была бы НЕВИДИМОЙ в отчёте: строка «1×» обязана
не ликвидироваться по построению (иначе весь смысл строки исчезает, а
таблица выглядит исправной); ранги обязаны усреднять ничьи (иначе
признак-константа получает AUC ≠ 0.5 и «разделяет»); планка обязана иметь
нуль (без него любой шум проходит); правило избегания обязано оставлять
позиции с неизмеримым признаком (иначе ему приписывается чужая польза).

Запуск из `.venv/bin/python` (тянет numpy).
"""
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d3 as D3                                           # noqa: E402
import run_d2 as D2                                           # noqa: E402
import ladder as L                                            # noqa: E402

LEVELS = np.array([98.0, 95.0, 90.0])       # уровни ниже входа 100
FLAT_MMR = 0.02


def _bars(t0=1_700_000_000, pre=1440, drop_to=40.0, steps=120):
    """1440 минут ровного рынка у 100, затем плавный сход до `drop_to`.

    Сход ПЛАВНЫЙ намеренно: одним баром цена пробила бы и рунги, и пол, и
    ликвидацию разом, и колонка пола ничего бы не показала — порядок
    проверок внутри бара «долив → ликвидация → пол → тейк».
    """
    bars = [(t0 + i * 60, 100.0, 100.2, 99.8, 100.0, 1000.0)
            for i in range(pre)]
    at = t0 + pre * 60
    for j in range(steps):
        px = 100.0 - (100.0 - drop_to) * j / (steps - 1)
        bars.append((at + j * 60, px, px + 0.1, px - 0.1, px, 1000.0))
    return bars, at


def _leg(at):
    return {"sym": "AAAUSDT", "at": float(at), "side": "long",
            "fwd": 100.0, "rr": 2.0, "beta": 0.8,
            "fav": 500.0,        # тейк +5 % — в этом пути не достигается
            "adv_q": -5000.0}    # стоп −50 %: у simulate_dca стопа нет,
                                 # число нужно только гейту геометрии


def _cells(bars=None, at=None):
    orig = D2.build_levels
    D2.build_levels = lambda w, i: LEVELS
    try:
        if bars is None:
            bars, at = _bars()
        ts = [b[0] for b in bars]
        look = (lambda notl: L.mmr_for_notional([], notl, flat=FLAT_MMR))
        return D3.leg_cells(_leg(at), bars, ts, look, {})
    finally:
        D2.build_levels = orig


def test_hard_1x_cannot_liquidate():
    # Строка «1×» отвечает на требование владельца «нет ликвидаций»
    # ГАРАНТИЕЙ, а не статистикой: у лонга при плече 1 цена ликвидации
    # равна нулю. Та же лестница при выведенном плече §5 — ликвидируется.
    rs = _cells()
    assert rs is not None
    cells, feat, extra, lev_by = rs
    fenced = cells[(2.0, None)]
    hard = cells[(None, None)]
    assert lev_by[2.0] > 1.5, lev_by            # забор выдал рычаг
    assert lev_by[None] == 1.0, lev_by
    assert fenced["exit"] == "ликвидация", fenced
    assert fenced["pnl_frac"] == -1.0, fenced
    assert hard["exit"] != "ликвидация", hard
    assert hard["pnl_frac"] > -1.0, hard
    # лестница у «1×» НЕ вырождается — глубина та же, что у забора
    assert hard["depth"] == len(LEVELS) + 1, hard
    print(f"ok  1× не ликвидируется: забор {lev_by[2.0]:.2f}× → "
          f"{fenced['exit']} {fenced['pnl_frac']:+.2f}; "
          f"1× → {hard['exit']} {hard['pnl_frac']:+.2f}")


def test_floor_cuts_before_liquidation():
    # Пол капитуляции §6 — вторая ось границы: та же лестница и то же
    # плечо, но выход раньше ликвидации. Без этого колонка пола была бы
    # украшением.
    cells = _cells()[0]
    none = cells[(2.0, None)]
    tight = cells[(2.0, 0.50)]
    assert none["exit"] == "ликвидация", none
    assert tight["exit"] == "пол", tight
    assert tight["pnl_frac"] > none["pnl_frac"], (tight, none)
    print(f"ok  пол режет раньше ликвидации: без пола {none['pnl_frac']:+.2f}, "
          f"пол 0.5 → {tight['exit']} {tight['pnl_frac']:+.2f}")


def test_features_are_ex_ante():
    # Признаки обязаны быть известны В МОМЕНТ ВХОДА: возраст листинга без
    # справочника — NaN, а не ноль; час входа — час метки решения.
    cells, feat, extra, _lev = _cells()
    assert feat["age_d"] != feat["age_d"], feat          # NaN
    assert feat["n_rungs"] == len(LEVELS) + 1, feat
    assert abs(feat["gap1_bp"] - 200.0) < 1e-6, feat     # 100 → 98 это 2 %
    assert feat["fwd_bp"] == 100.0 and feat["rr"] == 2.0
    assert 0 <= feat["hour"] <= 23
    assert extra["sym"] == "AAAUSDT"
    print(f"ok  признаки ex ante: рунгов {feat['n_rungs']}, до долива "
          f"{feat['gap1_bp']:.0f} б.п., возраст без справочника NaN")


def test_auc_ties_and_separation():
    # Полное разделение → 1.0; константа → ровно 0.5 (ничьи по половине).
    v = np.array([1.0, 2.0, 3.0, 10.0, 11.0, 12.0])
    m = np.array([False, False, False, True, True, True])
    a, nt, nr = D3.auc(v, m)
    assert abs(a - 1.0) < 1e-9, a
    c = np.ones(6)
    a2, _, _ = D3.auc(c, m)
    assert abs(a2 - 0.5) < 1e-9, a2
    # NaN не считается наблюдением
    v3 = np.array([1.0, np.nan, 3.0, 10.0, np.nan, 12.0])
    a3, nt3, nr3 = D3.auc(v3, m)
    assert nt3 == 2 and nr3 == 2, (nt3, nr3)
    print(f"ok  AUC: разделение {a:.2f}, константа {a2:.2f}, "
          f"NaN не наблюдение ({nt3}+{nr3})")


def _calib(n=500, k=50, noise_feats=20, seed=7):
    rng = np.random.default_rng(seed)
    mask = np.zeros(n, dtype=bool)
    mask[:k] = True
    feats = {"planted": np.where(mask, rng.normal(3, 1, n),
                                 rng.normal(0, 1, n))}
    for i in range(noise_feats):
        feats[f"noise{i}"] = rng.normal(0, 1, n)
    return feats, mask, ["planted"] + [f"noise{i}" for i in range(noise_feats)]


def test_family_bar_calibration():
    # Калибровочная ПАРА: планка обязана пропускать подсаженный признак и
    # молчать на шуме. Без неё «признаков не нашлось» неотличимо от
    # сломанной меры — проект дважды печатал нулевой отчёт именно так.
    feats, mask, names = _calib()
    bar = D3.family_bar(feats, mask, names, perms=100)
    seps = {}
    for nm in names:
        a, _, _ = D3.auc(feats[nm], mask)
        seps[nm] = abs(a - 0.5)
    assert bar["bar95"] > 0.02, bar
    assert seps["planted"] > bar["bar95"], (seps["planted"], bar)
    clearing = [nm for nm in names if nm != "planted"
                and seps[nm] > bar["bar95"]]
    assert len(clearing) <= 1, clearing        # семейственная планка держит
    print(f"ok  планка {bar['bar95']:.3f}: подсаженный "
          f"{seps['planted']:.3f} проходит, из {len(names)-1} шумовых "
          f"прошло {len(clearing)}")


def test_avoid_keeps_unmeasured():
    # Позиция с НЕизмеримым признаком остаётся в книге: правило не может
    # сработать без измерения, и выбросив её, мы приписали бы правилу
    # чужую пользу.
    rng = np.random.default_rng(11)
    n = 200
    feat = rng.normal(0, 1, n)
    feat[:30] = np.nan
    pnl = rng.normal(0.01, 0.05, n)
    pnl[np.argsort(np.nan_to_num(feat, nan=-9))[-10:]] = -1.0
    r = D3.avoid_check(pnl, feat, hi_side=True)
    assert r is not None
    assert r["unmeasured_kept"] == 30, r
    assert r["after"]["n"] == n - r["dropped"], r
    assert r["before"]["n"] == n, r
    print(f"ok  избегание: срезано {r['dropped']}, неизмеримых оставлено "
          f"{r['unmeasured_kept']}, ликвид. {r['before']['liq_freq']:.3f} → "
          f"{r['after']['liq_freq']:.3f}")


def test_crosscheck_reports_mismatch():
    # Прогон, не воспроизводящий D2 на общей ячейке, описывает другую
    # книгу — и обе таблицы при этом выглядят исправными.
    orig = D3.OUT
    with tempfile.TemporaryDirectory() as td:
        D3.OUT = td
        try:
            assert D3.d2_crosscheck({"median": 0.01})["have"] is False
            base = {"median": 0.0191, "mean": 0.0288, "liq_freq": 0.0006,
                    "worst": -1.0, "green": 0.906, "n": 8670}
            with open(os.path.join(td, "D2-dca-1m.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"positions": 8670, "arms": {"S": dict(base)}}, f)
            same = D3.d2_crosscheck(base)
            assert same["have"] and same["mismatch"] == 0, same
            moved = dict(base, median=0.05)
            bad = D3.d2_crosscheck(moved)
            assert bad["mismatch"] == 1 and bad["fields"][0]["field"] == \
                "median", bad
        finally:
            D3.OUT = orig
    print("ok  сверка с D2: совпадение 0 расхождений, сдвиг медианы пойман")


def test_options_cover_aliases():
    # Опционы котируются на сам актив, а перп несёт множитель лота:
    # 1000PEPEUSDT обязан находиться по базовому PEPE.
    orig = D3.OPTIONS_INV
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "opts.json")
        D3.OPTIONS_INV = p
        try:
            cov = D3.options_cover({"AAAUSDT": 3}, {})
            assert cov["have"] is False, cov          # нет инвентаря — не ноль
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"base_coins": ["BTC", "ETH", "PEPE"],
                           "asof": "x"}, f)
            inst = {"1000PEPEUSDT": {"base_coin": "1000PEPE"},
                    "ZZZUSDT": {"base_coin": "ZZZ"}}
            cov = D3.options_cover({"1000PEPEUSDT": 4, "ZZZUSDT": 6}, inst)
            assert cov["covered"] == 4 and cov["total"] == 10, cov
            assert cov["names"] == ["1000PEPEUSDT"], cov
        finally:
            D3.OPTIONS_INV = orig
    print("ok  покрытие опционами: 1000PEPE → PEPE найден, ZZZ нет, "
          "отсутствие инвентаря не выдаётся за ноль")


class _Src:
    """Подставной источник баров: тот же контракт, что `sweep.read_bars`."""

    def __init__(self, by_sym):
        self.by_sym = by_sym

    def bars(self, sym, a, b):
        return [r for r in self.by_sym.get(sym, []) if a <= r[0] <= b]


def test_run_end_to_end_synthetic():
    # Сквозной прогон: run → finish → report. Дороги отчёта и сводки
    # `py_compile` не проверяет, и S11 потерял два прогона именно так
    # (`UnboundLocalError` после правки памяти; чужая форма аргумента в
    # статистике — падение на ПОСЛЕДНЕМ шаге после часа счёта).
    import tournament as TNT
    bars, at0 = _bars(pre=1440, drop_to=60.0, steps=400)
    up, _ = _bars(pre=1440, drop_to=130.0, steps=400)     # рост → тейк
    src = _Src({"AAAUSDT": bars, "BBBUSDT": up, "CCCUSDT": bars})
    legs = []
    for i in range(60):
        sym = ("AAAUSDT", "BBBUSDT", "CCCUSDT")[i % 3]
        g = _leg(at0 + (i % 5) * 3600)                    # разные сутки/часы
        g["sym"] = sym
        g["fwd"] = 40.0 + i
        g["rr"] = 2.0 + (i % 3)
        g["beta"] = 0.5 + 0.01 * i
        legs.append(g)
    o_legs, o_lv = TNT.legs_from_sheets, D2.build_levels
    TNT.legs_from_sheets = lambda paths, log=None: legs
    D2.build_levels = lambda w, i: LEVELS
    try:
        s = D3.run(src=src, log=lambda *a: None)
    finally:
        TNT.legs_from_sheets, D2.build_levels = o_legs, o_lv
    assert s["positions"] == 60, s["positions"]
    want = len(D3.GRID_SURVIVE) * len(D3.GRID_FLOOR)
    assert len(s["cells"]) == want, (len(s["cells"]), want)
    for key, c in s["cells"].items():
        assert c["n"] == 60, (key, c["n"])
        assert c["median_lev"] == c["median_lev"], key     # не NaN
        assert 0.0 <= c["frac_1x"] <= 1.0, key
    hard = s["cells"][f"1x|нет"]
    assert hard["liq_freq"] == 0.0, hard                   # гарантия строки 1×
    assert hard["median_lev"] == 1.0, hard
    t = s["tail"]
    assert t["n"] >= 5 and len(t["features"]) == len(D3.FEATURES), t["n"]
    assert t["bar"]["bar95"] > 0, t["bar"]
    rep = D3.report(s)
    assert "Граница забора" in rep and "Портрет хвоста" in rep, rep[:300]
    assert "Опционы" in rep, rep[-800:]
    assert "nan" not in rep.lower(), [ln for ln in rep.splitlines()
                                      if "nan" in ln.lower()][:3]
    print(f"ok  сквозной прогон: позиций {s['positions']}, ячеек "
          f"{len(s['cells'])}, хвост {t['n']}, отчёт {len(rep)} знаков")


def test_window_stats_needs_history():
    # Короткое окно — «не измерено», а не «спокойно»: замороженный ряд не
    # есть ряд с нулевой волатильностью (урок S1).
    short = [(0, 1, 1, 1, 1.0, 5.0)] * 5
    s, r, t = D3.window_stats(short, 4)
    assert s != s and r != r and t != t, (s, r, t)
    bars, at = _bars()
    s2, r2, t2 = D3.window_stats(bars, 1440)
    assert s2 == s2 and t2 == 1000.0, (s2, t2)
    print(f"ok  окно: короткое → NaN, полное → σ {s2:.2f} б.п., "
          f"оборот {t2:.0f}")


# ------------------------------------------------------ отрицательные контроли

def _control_hard_1x_from_fence():
    """Если строка «1×» начнёт брать плечо у забора, гарантии не станет —
    проверка «1× не ликвидируется» обязана упасть."""
    orig = D3.GRID_SURVIVE
    D3.GRID_SURVIVE = [2.0, 2.0]              # None ушёл: «жёсткого 1×» нет
    try:
        try:
            test_hard_1x_cannot_liquidate()
        except (AssertionError, KeyError):
            return True
        return False
    finally:
        D3.GRID_SURVIVE = orig


def _control_ranks_without_ties():
    """Ранги без усреднения ничьих: признак-константа получит AUC ≠ 0.5 и
    «разделит» — проверка AUC обязана упасть."""
    orig = D3._avg_ranks
    D3._avg_ranks = lambda x: np.argsort(np.argsort(np.asarray(x, float),
                                                    kind="mergesort")) + 1.0
    try:
        try:
            test_auc_ties_and_separation()
        except AssertionError:
            return True
        return False
    finally:
        D3._avg_ranks = orig


def _control_bar_without_null():
    """Планка без нуля (ноль вместо процентиля перестановок): шум пройдёт —
    калибровочная пара обязана упасть."""
    orig = D3.family_bar
    D3.family_bar = lambda f, m, n, perms=0, seed=0: {
        "bar95": 0.0, "bar_mean": 0.0, "perms": 0, "seed": 0}
    try:
        try:
            test_family_bar_calibration()
        except AssertionError:
            return True
        return False
    finally:
        D3.family_bar = orig


def _control_avoid_drops_unmeasured():
    """Если правило выбрасывает позиции с неизмеримым признаком, ему
    приписывается чужая польза — проверка обязана упасть."""
    orig = D3.avoid_check

    def drops(pnl, feat, hi_side, q=D3.AVOID_Q):
        p = np.array(pnl, float)
        v = np.array(feat, float)
        ok = ~np.isnan(v)
        thr = float(np.quantile(v[ok], 1.0 - q if hi_side else q))
        keep = ok & ((v < thr) if hi_side else (v > thr))
        return {"dropped": int((~keep).sum()), "unmeasured_kept": 0,
                "threshold": thr, "hi_side": hi_side,
                "before": {"n": len(p), "median": 0.0, "mean": 0.0,
                           "worst": 0.0, "liq_freq": 0.0, "green": 0.0},
                "after": {"n": int(keep.sum()), "median": 0.0, "mean": 0.0,
                          "worst": 0.0, "liq_freq": 0.0, "green": 0.0}}
    D3.avoid_check = drops
    try:
        try:
            test_avoid_keeps_unmeasured()
        except AssertionError:
            return True
        return False
    finally:
        D3.avoid_check = orig


def _control_floor_ignored():
    """Пол, не доезжающий до симулятора, оставил бы колонку украшением —
    проверка пола обязана упасть."""
    orig = D3.GRID_FLOOR
    D3.GRID_FLOOR = [None, None, None, None]
    try:
        try:
            test_floor_cuts_before_liquidation()
        except (AssertionError, KeyError):
            return True
        return False
    finally:
        D3.GRID_FLOOR = orig


TESTS = [
    test_hard_1x_cannot_liquidate,
    test_floor_cuts_before_liquidation,
    test_features_are_ex_ante,
    test_auc_ties_and_separation,
    test_family_bar_calibration,
    test_avoid_keeps_unmeasured,
    test_crosscheck_reports_mismatch,
    test_options_cover_aliases,
    test_window_stats_needs_history,
    test_run_end_to_end_synthetic,
]

CONTROLS = [
    ("жёсткий 1× берёт плечо у забора", _control_hard_1x_from_fence),
    ("ранги без усреднения ничьих", _control_ranks_without_ties),
    ("планка без нуля", _control_bar_without_null),
    ("избегание выбрасывает неизмеримых", _control_avoid_drops_unmeasured),
    ("пол не доезжает до симулятора", _control_floor_ignored),
]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
