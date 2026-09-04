#!/usr/bin/env python3
"""Тесты D4 — книжный хедж.

Два места, где ошибка была бы НЕВИДИМОЙ в отчёте и сделала бы хедж
чудесным: заглядывание вперёд при выборе размера (хедж «уже включён» в
час обвала, потому что просадку посчитали с учётом этого же обвала) и
неучтённые издержки переключения (условный хедж, мигающий каждый час,
выглядел бы бесплатным). Плюс сверка свода с исходами позиций и
одинаковая доля включённых часов у нуля.

Запуск из `.venv/bin/python`.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d4 as D4                                           # noqa: E402
import run_d2 as D2                                           # noqa: E402
import test_run_d3 as T3                                      # noqa: E402

H = D4.HOUR


def _flat_book(n=6, crash_at=3, hit=-0.10):
    """Книга из постоянной экспозиции: обвал ровно в один час, рынок с ней."""
    hrs = [1_699_999_200 + i * H for i in range(n)]
    dP = {h: 0.0 for h in hrs}
    X = {h: 1.0 for h in hrs}
    BW = {h: 1.0 for h in hrs}
    BC = {h: 1.0 for h in hrs}
    rmkt = {h: 0.0 for h in hrs}
    if 0 <= crash_at < n:                       # crash_at вне ряда = без обвала
        dP[hrs[crash_at]] = hit
        rmkt[hrs[crash_at]] = hit
    return hrs, dP, X, BW, BC, rmkt


def test_hedge_cannot_see_the_crash():
    """Хедж не может быть включён в час, просадкой которого он и вызван.

    Порог 5 %: к концу часа перед обвалом просадки нет, значит в самом
    обвале хедж выключен, и книга обязана получить удар целиком. Реализация
    с заглядыванием посчитала бы просадку С УЧЁТОМ этого часа, включила бы
    хедж задним числом и обнулила бы удар — «хедж спас обвал» на данных,
    которых в тот момент не существовало.
    """
    hrs, dP, X, BW, BC, rmkt = _flat_book()
    base = D4.simulate_hedge(hrs, dP, X, BW, BC, rmkt, 1e9, 0.0)
    hedged = D4.simulate_hedge(hrs, dP, X, BW, BC, rmkt, 0.05, 1.0)
    i = 3
    assert abs(base["curve"][i] - hedged["curve"][i]) < 1e-9, \
        (base["curve"][i], hedged["curve"][i])
    assert base["curve"][i] < base["curve"][i - 1] * 0.95, base["curve"]
    # после обвала просадка уже видна — хедж обязан включиться
    assert hedged["duty"] > 0, hedged["duty"]
    print(f"ok  хедж не видит собственный обвал: база {base['curve'][i]:.4f} "
          f"= хедж {hedged['curve'][i]:.4f}, дальше включился "
          f"({hedged['duty']*100:.0f} % часов)")


def test_switching_costs_are_charged():
    """Издержки берутся с ИЗМЕНЕНИЯ нотионала: включил и выключил — круг."""
    hrs, dP, X, BW, BC, rmkt = _flat_book(n=4, crash_at=99)
    always = D4.simulate_hedge(hrs, dP, X, BW, BC, rmkt, 0.0, 1.0)
    # экспозиция и бета единичны, значит нотионал 1.0 с первого же часа,
    # где известен прошлый час; включение стоит половину круга ровно раз
    # ожидание ЛИТЕРАЛОМ, а не от константы модуля: посчитанное формулой
    # от неё, оно не поймало бы её обнуление (круг 11 б.п. → половина 0.00055)
    assert abs(always["cost"] - 0.00055) < 1e-12, always["cost"]
    off = D4.simulate_hedge(hrs, dP, X, BW, BC, rmkt, 1e9, 1.0)
    assert off["cost"] == 0.0 and off["duty"] == 0.0, off
    print(f"ok  издержки переключения: включение {always['cost']:.5f} "
          f"(половина круга), выключенный хедж {off['cost']:.5f}")


def test_null_uses_same_duty():
    """Нуль включает хедж на столько же часов — иначе сравнивают разное."""
    hrs, dP, X, BW, BC, rmkt = _flat_book(n=20, crash_at=5)
    cell = D4.simulate_hedge(hrs, dP, X, BW, BC, rmkt, 0.02, 1.0)
    k = max(1, int(round(cell["duty"] * len(hrs))))
    rng = np.random.default_rng(D4.NULL_SEED0)
    pick = set(np.array(hrs)[rng.choice(len(hrs), size=k,
                                        replace=False)].tolist())
    null = D4.simulate_hedge(hrs, dP, X, BW, BC, rmkt, 0.0, 1.0,
                             on_hours=pick)
    assert abs(null["duty"] - cell["duty"]) <= 1.5 / len(hrs), \
        (null["duty"], cell["duty"])
    print(f"ok  нуль той же доли часов: хедж {cell['duty']:.2f}, нуль "
          f"{null['duty']:.2f}")


def test_end_to_end_and_crosscheck():
    """Сквозной прогон: свод обязан сойтись с суммой исходов позиций."""
    import tournament as TNT
    bars, at0 = T3._bars(pre=1440, drop_to=70.0, steps=400)
    up, _ = T3._bars(pre=1440, drop_to=130.0, steps=400)
    btc, _ = T3._bars(pre=1440, drop_to=90.0, steps=400)
    src = T3._Src({"AAAUSDT": bars, "BBBUSDT": up, "CCCUSDT": bars,
                   D4.MARKET: btc})
    legs = []
    for i in range(40):
        g = T3._leg(at0 + (i % 6) * H)
        g["sym"] = ("AAAUSDT", "BBBUSDT", "CCCUSDT")[i % 3]
        g["beta"] = 0.8 + 0.01 * i
        legs.append(g)
    o_legs, o_lv = TNT.legs_from_sheets, D2.build_levels
    TNT.legs_from_sheets = lambda paths, log=None: legs
    D2.build_levels = lambda w, i: T3.LEVELS
    try:
        s = D4.run(src=src, log=lambda *a: None)
    finally:
        TNT.legs_from_sheets, D2.build_levels = o_legs, o_lv
    assert s["positions"] == 40, s["positions"]
    cc = s["crosscheck"]
    assert abs(cc["residual"]) < 1e-6, cc
    want = len(D4.GRID_DD) * len(D4.GRID_MULT)
    assert len(s["cells"]) == want and len(s["nulls"]) == want, len(s["cells"])
    seen_null = 0
    for k, z in s["nulls"].items():
        if z.get("never_on"):                  # хедж не включался — нуля нет
            assert z["cell_duty"] == 0.0, (k, z)
            continue
        seen_null += 1
        assert abs(z["duty_mean"] - z["cell_duty"]) <= 0.02, (k, z)
    assert seen_null > 0, "ни одной ячейки с нулём — сравнивать нечего"
    assert s["base"]["hours"] == s["hours"], (s["base"], s["hours"])
    rep = D4.report(s)
    assert "сходится" in rep and "Нуль случайного момента" in rep, rep[:400]
    assert "nan" not in rep.lower(), [ln for ln in rep.splitlines()
                                      if "nan" in ln.lower()][:3]
    print(f"ok  сквозной прогон: позиций {s['positions']}, часов "
          f"{s['hours']}, сверка {cc['residual']:+.2e}, ячеек "
          f"{len(s['cells'])}, отчёт {len(rep)} знаков")


def test_beats_null_needs_both():
    """«Бьёт нуль» — это И итог выше 95-го процентиля, И просадка мельче.

    Одного мало: хедж просто сокращает экспозицию, и просадка улучшается у
    ЛЮБОГО момента включения — тот же довод, по которому в S1 был обязателен
    нуль случайных выходов.
    """
    base = {"grid": {"dd": [0.0], "mult": [1.0]}, "hours": 10,
            "positions": 5, "skipped": 0, "beta_coverage": 1.0, "secs": 1.0,
            "market_hours": 10,
            "crosscheck": {"sum_positions": 0.0, "sum_hourly": 0.0,
                           "residual": 0.0},
            "base": {"hours": 10, "final": 0.1, "max_dd": -0.2,
                     "day_median": 0.01, "day_worst": -0.05,
                     "day_green": 0.6, "days": 3, "duty": 0.0, "cost": 0.0}}
    cell = {"hours": 10, "final": 0.2, "max_dd": -0.30, "day_median": 0.01,
            "day_worst": -0.04, "day_green": 0.6, "days": 3, "duty": 0.5,
            "cost": 0.01, "vs_base_day_median": 0.001,
            "vs_base_day_better": 0.6}
    null = {"final_mean": 0.0, "final_p95": 0.1, "dd_mean": -0.4,
            "dd_best": -0.25, "duty_mean": 0.5, "cell_duty": 0.5, "seeds": 10}
    s = dict(base, cells={"0.0|1.0": cell}, nulls={"0.0|1.0": null})
    r = D4.report(s)
    row = [ln for ln in r.splitlines() if ln.startswith("| 0 % | 1.0 |")][-1]
    assert row.rstrip().endswith("| — |"), row      # итог выше, просадка хуже
    s2 = dict(s, cells={"0.0|1.0": dict(cell, max_dd=-0.10)})
    r2 = D4.report(s2)
    row2 = [ln for ln in r2.splitlines()
            if ln.startswith("| 0 % | 1.0 |")][-1]
    assert row2.rstrip().endswith("| ✓ |"), row2
    print("ok  «бьёт нуль» требует обоих условий: лучший итог при худшей "
          "просадке отметки не получает")


def _control_hedge_sees_current_hour():
    """Размер по ТЕКУЩЕМУ часу (заглядывание) — проверка обязана упасть."""
    orig = D4.simulate_hedge

    def peeking(hrs, dP, X, BW, BC, rmkt, dd_on, mult, on_hours=None):
        eq, peak = 1.0, 1.0
        curve, day, prev, cost_tot, on_n = [], {}, 0.0, 0.0, 0
        for i, h in enumerate(hrs):
            den = X.get(h, 0.0)
            nxt = eq * (1.0 + (dP.get(h, 0.0) / den if den > 0 else 0.0))
            dd = (1.0 - nxt / peak) if peak > 0 else 0.0     # знает свой час
            on = (h in on_hours) if on_hours is not None else dd >= dd_on
            bp = (BW.get(h, 0.0) / BC[h]) if BC.get(h, 0.0) > 0 else 0.0
            notl = mult * bp * X.get(h, 0.0) if on else 0.0
            r = rmkt.get(h, float("nan"))
            hedge = 0.0 if (notl == 0.0 or r != r) else -notl * r
            cost = abs(notl - prev) * D4.HALF_ROUND
            cost_tot += cost
            on_n += int(notl > 0)
            prev = notl
            ret = ((dP.get(h, 0.0) + hedge - cost) / den) if den > 0 else 0.0
            eq *= (1.0 + ret)
            peak = max(peak, eq)
            curve.append(eq)
            d = "d"
            day[d] = day.get(d, 0.0) + ret
        return {"curve": curve, "day": day, "cost": cost_tot,
                "duty": on_n / len(hrs) if hrs else 0.0}
    D4.simulate_hedge = peeking
    try:
        try:
            test_hedge_cannot_see_the_crash()
        except AssertionError:
            return True
        return False
    finally:
        D4.simulate_hedge = orig


def _control_costs_ignored():
    """Бесплатное переключение — проверка издержек обязана упасть."""
    orig = D4.HALF_ROUND
    D4.HALF_ROUND = 0.0
    try:
        try:
            test_switching_costs_are_charged()
        except AssertionError:
            return True
        return False
    finally:
        D4.HALF_ROUND = orig


def _control_crosscheck_blind():
    """Свод без сверки (остаток объявлен нулём) — сквозной тест обязан упасть,
    потому что расхождение перестало бы быть заметным."""
    orig = D4.run

    def blind(limit=None, src=None, log=print):
        s = orig(limit=limit, src=src, log=log)
        if s.get("crosscheck"):
            s["crosscheck"]["residual"] = 1.0      # свод разошёлся, но молчит
        return s
    D4.run = blind
    try:
        try:
            test_end_to_end_and_crosscheck()
        except AssertionError:
            return True
        return False
    finally:
        D4.run = orig


TESTS = [test_hedge_cannot_see_the_crash, test_switching_costs_are_charged,
         test_null_uses_same_duty, test_end_to_end_and_crosscheck,
         test_beats_null_needs_both]

CONTROLS = [("хедж видит текущий час", _control_hedge_sees_current_hour),
            ("издержки переключения не берутся", _control_costs_ignored),
            ("сверка свода слепа", _control_crosscheck_blind)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
