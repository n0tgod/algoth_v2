#!/usr/bin/env python3
"""Тесты D5 — линейка забора (глубины лестницы против движений монеты).

Проверяется то, где ошибка была бы НЕВИДИМОЙ в отчёте и при этом сделала
бы новую линейку чудесной:

* **σ = 0 у замороженной котировки.** Правило «запас в N·σ» выдало бы ей
  потолок плеча — ловушка S1 в новом костюме. Неизмеримое и нулевое не
  есть безопасное: и то и другое обязано давать 1×.
* **Запас мельче лестницы.** У спокойной монеты `N·σ` бывает меньше
  глубины плановых доливов, и тогда ликвидация встала бы ВЫШЕ последнего
  рунга: позицию закрыли бы раньше, чем лестница набралась. Запас обязан
  не быть мельче `d_max`.
* **Сама линейка.** У σ-правила бешеная монета обязана получать МЕНЬШЕ
  плеча, чем спокойная с той же лестницей; у нынешнего правила плечо от
  волатильности не зависит вовсе — иначе замер сравнивал бы линейку сам с
  собой.
* **Якорь.** Ячейка ("depth", 2.0) обязана давать ровно то плечо, что
  считает живой путь D2/D4, иначе таблица описывает другую книгу.

Запуск из `.venv/bin/python` (тянет numpy).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d5 as D5                                           # noqa: E402
import run_d4 as D4                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import run_d2 as D2                                           # noqa: E402
import ladder as L                                            # noqa: E402
import test_run_d3 as T3                                      # noqa: E402

LOOK = (lambda notl: L.mmr_for_notional([], notl, flat=0.02))
ENTRY = 100.0
RUNGS = [100.0, 98.0, 95.0, 90.0]          # d_max = 10 %


def test_sigma_ruler_gives_wild_less_leverage():
    """Главное утверждение: та же лестница, разная монета — разное плечо.

    Спокойная (σ суток ≈ 1.9 %) и бешеная (≈ 11.4 %) с ОДИНАКОВОЙ
    лестницей. По нынешней линейке обе получают одно плечо: глубина
    лестницы у них общая, а как быстро монета её проходит, забор не
    спрашивает. По σ-линейке бешеная обязана получить заметно меньше.
    """
    calm_bp, wild_bp = 5.0, 30.0            # σ минуты, б.п.
    d_calm, d_wild = [D5.fence_leverage("depth", 2.0, ENTRY, RUNGS, LOOK, s)[0]
                      for s in (calm_bp, wild_bp)]
    s_calm, s_wild = [D5.fence_leverage("sigma", 6.0, ENTRY, RUNGS, LOOK, s)[0]
                      for s in (calm_bp, wild_bp)]
    assert abs(d_calm - d_wild) < 1e-9, (d_calm, d_wild)
    assert s_wild < s_calm * 0.6, (s_calm, s_wild)
    assert s_calm > 1.0 and s_wild > 1.0, (s_calm, s_wild)
    print(f"ok  линейка: нынешняя даёт обеим {d_calm:.2f}×; σ-линейка — "
          f"спокойной {s_calm:.2f}×, бешеной {s_wild:.2f}×")


def test_no_sigma_no_leverage():
    """Нет меры и ноль — оба 1×, а не потолок.

    Замороженная котировка даёт ровно σ = 0, и запас `N·0` обратил бы
    неравенство в тождество: плечо ушло бы в потолок именно на том ряде,
    где риск не измерен вовсе.
    """
    for bad in (float("nan"), 0.0, -1.0, None):
        lev, rungs, binder = D5.fence_leverage("sigma", 6.0, ENTRY, RUNGS,
                                               LOOK, bad)
        assert lev == 1.0, (bad, lev)
        assert binder == "нет σ", (bad, binder)
        assert rungs == [ENTRY], (bad, rungs)
    assert D5.sigma_day(0.0) is None and D5.sigma_day(float("nan")) is None
    print("ok  σ отсутствует или равна нулю → плеча нет (1×), не потолок")


def test_buffer_never_shallower_than_ladder():
    """Ликвидация не встаёт выше последнего планового долива.

    У очень спокойной монеты `N·σ` мельче глубины лестницы; если взять
    запас как есть, ликвидация окажется внутри лестницы — позиция умрёт,
    не успев набраться, а таблица покажет «мало ликвидаций» просто потому,
    что до нижнего рунга дело не дошло.
    """
    tiny = 1.0                              # σ суток ≈ 0.38 % при d_max 10 %
    lev, rungs, binder = D5.fence_leverage("sigma", 3.0, ENTRY, RUNGS, LOOK,
                                           tiny)
    assert binder == "лестница", binder
    qty, p_avg, _n = L.fully_loaded(rungs, D2.WEIGHTS[:len(rungs)], 1.0, lev)
    liq = L.liq_price(p_avg, qty, 1.0, LOOK(1.0 * lev))
    assert liq <= RUNGS[-1] + 1e-9, (liq, RUNGS[-1])
    # а у бешеной связывает уже σ, и запас глубже лестницы
    lev2, _r2, b2 = D5.fence_leverage("sigma", 3.0, ENTRY, RUNGS, LOOK, 30.0)
    assert b2 == "σ", b2
    qty2, pa2, _ = L.fully_loaded(RUNGS, D2.WEIGHTS, 1.0, lev2)
    liq2 = L.liq_price(pa2, qty2, 1.0, LOOK(1.0 * lev2))
    assert liq2 < RUNGS[-1] - 1e-9, (liq2, RUNGS[-1])
    print(f"ok  запас: у спокойной связала лестница (ликвидация {liq:.2f} ≤ "
          f"рунга {RUNGS[-1]:.2f}), у бешеной связала σ ({liq2:.2f})")


def test_anchor_matches_live_path():
    """Ячейка ("depth", 2.0) обязана дать плечо живого пути D2/D4.

    Живой путь считает его сам (`run_d4._one`), и если линейка расходится
    с ним, якорь сверки перестаёт быть якорем — обе таблицы при этом
    выглядят исправными.
    """
    d_max = (ENTRY - RUNGS[-1]) / ENTRY
    want = L.max_leverage(RUNGS, D2.WEIGHTS, 1.0, ENTRY, d_max, LOOK,
                          D2.SURVIVE_MULT)
    got, rungs, binder = D5.fence_leverage("depth", D2.SURVIVE_MULT, ENTRY,
                                           RUNGS, LOOK, 12.0)
    assert abs(got - want) < 1e-12, (got, want)
    assert binder == "лестница" and rungs is RUNGS
    # лестницы нет — 1×, как в D2
    lev1, r1, b1 = D5.fence_leverage("depth", 2.0, ENTRY, [ENTRY], LOOK, 12.0)
    assert lev1 == 1.0 and r1 == [ENTRY] and b1 == "нет лестницы"
    print(f"ok  якорь: линейка воспроизвела живой путь D2 — {got:.4f}×")


def test_run_end_to_end_synthetic():
    """Сквозной прогон: run → report, обе единицы и сверка якоря.

    Дороги отчёта и книги `py_compile` не проверяет, и S11 потерял два
    прогона ровно так. Здесь же проверяется, что книга D4 строится по
    каждой ячейке и её числа доезжают до таблицы.
    """
    import tournament as TNT
    bars, at0 = T3._bars(pre=1440, drop_to=60.0, steps=400)
    up, _ = T3._bars(pre=1440, drop_to=130.0, steps=400)
    src = T3._Src({"AAAUSDT": bars, "BBBUSDT": up, "CCCUSDT": bars})
    legs = []
    for i in range(60):
        g = T3._leg(at0 + (i % 5) * 3600)
        g["sym"] = ("AAAUSDT", "BBBUSDT", "CCCUSDT")[i % 3]
        g["fwd"] = 40.0 + i
        g["rr"] = 2.0 + (i % 3)
        legs.append(g)
    o_legs, o_lv, o_anchor = (TNT.legs_from_sheets, D2.build_levels,
                              dict(D5.ANCHOR_D3))
    TNT.legs_from_sheets = lambda paths, log=None: legs
    D2.build_levels = lambda w, i: T3.LEVELS
    try:
        s = D5.run(src=src, log=lambda *a: None)
    finally:
        TNT.legs_from_sheets, D2.build_levels = o_legs, o_lv
    assert s["positions"] == 60, s["positions"]
    assert len(s["cells"]) == len(D5.GRID_RULE), len(s["cells"])
    for key, c in s["cells"].items():
        assert c["n"] == 60, (key, c["n"])
        b = c["book"]
        assert b["hours"] > 0 and b["final"] == b["final"], (key, b)
        assert sum(c["binder"].values()) > 0.99, (key, c["binder"])
    # синтетика не обязана совпасть с живым якорем — сверка обязана это
    # СКАЗАТЬ, а не промолчать
    assert s["anchor"]["mismatch"] > 0, s["anchor"]
    rep = D5.report(s)
    assert "ЛИНЕЙКА" in rep and "Кто связал запас" in rep, rep[:400]
    assert "Сверка якоря НЕ сошлась" in rep, rep[:1200]
    assert "nan" not in rep.lower(), [ln for ln in rep.splitlines()
                                      if "nan" in ln.lower()][:3]
    print(f"ok  сквозной прогон: позиций {s['positions']}, ячеек "
          f"{len(s['cells'])}, книга по каждой, отчёт {len(rep)} знаков")


# ------------------------------------------------------ отрицательные контроли

def _control_sigma_zero_allowed():
    """Без защиты от нулевой σ замороженный ряд получает потолок плеча."""
    orig = D5.sigma_day
    D5.sigma_day = lambda bp: (None if (bp is None or bp != bp)
                               else bp / 1e4 * 37.9473)
    try:
        try:
            test_no_sigma_no_leverage()
        except AssertionError:
            return True
        return False
    finally:
        D5.sigma_day = orig


def _control_buffer_may_be_shallower():
    """Без `max(N·σ, d_max)` ликвидация встаёт внутрь лестницы."""
    orig = D5.fence_leverage

    def loose(rule, param, entry, rungs_full, look, sigma_bp):
        if rule != "sigma" or len(rungs_full) < 2:
            return orig(rule, param, entry, rungs_full, look, sigma_bp)
        d_max = (entry - rungs_full[-1]) / entry
        sd = D5.sigma_day(sigma_bp)
        if sd is None:
            return 1.0, [entry], "нет σ"
        mult = (float(param) * sd) / d_max          # без пола по лестнице
        lev = L.max_leverage(rungs_full, D2.WEIGHTS[:len(rungs_full)], 1.0,
                             entry, d_max, look, mult)
        return (lev if lev > 0 else 1.0), rungs_full, "σ"
    D5.fence_leverage = loose
    try:
        try:
            test_buffer_never_shallower_than_ladder()
        except AssertionError:
            return True
        return False
    finally:
        D5.fence_leverage = orig


def _control_sigma_ruler_is_depth():
    """Если σ-линейка втайне считает запас по лестнице, различия нет."""
    orig = D5.fence_leverage

    def fake(rule, param, entry, rungs_full, look, sigma_bp):
        return orig("depth", 2.0, entry, rungs_full, look, sigma_bp)
    D5.fence_leverage = fake
    try:
        try:
            test_sigma_ruler_gives_wild_less_leverage()
        except AssertionError:
            return True
        return False
    finally:
        D5.fence_leverage = orig


def _control_anchor_never_complains():
    """Молчаливая сверка якоря: расхождение обязано попадать в отчёт."""
    orig = dict(D5.ANCHOR_D3), dict(D5.ANCHOR_D4)
    D5.ANCHOR_D3, D5.ANCHOR_D4 = {}, {}
    try:
        try:
            test_run_end_to_end_synthetic()
        except AssertionError:
            return True
        return False
    finally:
        D5.ANCHOR_D3, D5.ANCHOR_D4 = orig


TESTS = [test_sigma_ruler_gives_wild_less_leverage,
         test_no_sigma_no_leverage,
         test_buffer_never_shallower_than_ladder,
         test_anchor_matches_live_path,
         test_run_end_to_end_synthetic]

CONTROLS = [("нулевая σ пропускается", _control_sigma_zero_allowed),
            ("запас мельче лестницы", _control_buffer_may_be_shallower),
            ("σ-линейка это лестница", _control_sigma_ruler_is_depth),
            ("сверка якоря молчит", _control_anchor_never_complains)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
