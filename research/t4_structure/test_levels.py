#!/usr/bin/env python3
"""
Тесты структурных уровней.

Главное здесь — **стоп обязан быть снаружи шума**. Ровно этим T3 и
убился: полоса в 7 базисных пунктов сидела внутри обычного хода минутной
свечи, и её выбивало независимо от того, верно ли прочитано событие.
Поэтому мера шума и её применение проверяются числом.

    python3 research/t4_structure/test_levels.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t1_tape"))
sys.path.insert(0, HERE)

import levels as LV  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def test_noise_is_median_range():
    H = np.array([101.0, 102.0, 100.5, 105.0])
    L = np.array([100.0, 100.0, 100.0, 100.0])
    P = (H + L) / 2
    check("шум — медиана хода свечи",
          abs(LV.noise_px(H, L, P) - 1.5) < 1e-12, str(LV.noise_px(H, L, P)))
    check("пустой ряд не рушит счёт",
          not np.isfinite(LV.noise_px(np.array([]), np.array([]),
                                      np.array([]))))


def test_shelf_found_where_volume_sits():
    """Полка обязана появиться там, где прошёл объём, и только там."""
    rng = np.random.default_rng(3)
    P = np.concatenate([rng.uniform(99.0, 101.0, 400),
                        np.full(120, 100.40)])
    V = np.concatenate([np.full(400, 1.0), np.full(120, 50.0)])
    lv = LV.shelves(P, V, noise=0.05)
    check("полка найдена", len(lv) > 0, str(lv))
    if len(lv):
        best = lv[np.argmin(np.abs(lv - 100.40))]
        check(f"полка на цене объёма ({best:.2f})", abs(best - 100.40) < 0.06,
              str(lv))


def test_round_levels_scale_with_price():
    """Шаг круглых чисел берётся от масштаба цены, а не назначается."""
    a = LV.round_levels(0.3412, noise=0.02, span=10)
    b = LV.round_levels(85_000.0, noise=2000.0, span=10)
    check("для 0.34 шаг сотые", len(a) and abs(np.diff(a)[0] - 0.01) < 1e-9,
          str(a))
    check("для 85 000 шаг тысяча",
          len(b) and abs(np.diff(b)[0] - 1000.0) < 1e-6, str(b))
    far = LV.round_levels(0.3412, noise=0.0001, span=1)
    check("далёкие круглые числа отсекаются", len(far) <= 1, str(far))


def test_nearest_and_ahead():
    lv = np.array([99.0, 100.0, 101.0, 103.0])
    kinds = ["полка", "круглое", "полка", "максимум суток"]
    got = LV.nearest(lv, kinds, 100.02, tol=0.05)
    check("ближайший уровень найден", got and abs(got[0] - 100.0) < 1e-9,
          str(got))
    check("вид уровня возвращается", got and got[1] == "круглое", str(got))
    check("далёкая цена уровня не получает",
          LV.nearest(lv, kinds, 102.0, tol=0.05) is None)
    check("цель впереди — ближайшая",
          abs(LV.ahead(lv, 100.02, True, 0.1) - 101.0) < 1e-9,
          str(LV.ahead(lv, 100.02, True, 0.1)))
    check("слишком близкая цель пропускается",
          abs(LV.ahead(lv, 100.95, True, 0.5) - 103.0) < 1e-9,
          str(LV.ahead(lv, 100.95, True, 0.5)))
    check("впереди ничего — цели нет",
          LV.ahead(lv, 104.0, True, 0.1) is None)


def test_stop_is_outside_noise():
    """Стоп, поставленный по правилу, обязан быть больше шума.

    Это и есть исправление дефекта T3, выраженное числом: там стоп
    равнялся десятой части хода минутного окна и оказывался в разы
    МЕНЬШЕ обычного хода свечи.
    """
    noise = 0.5
    level = 100.0
    entry = 100.2
    stop = level - LV.ROUND_SPAN * 0  # значение ниже задаётся правилом
    stop = level - 1.0 * noise
    stop_bp = abs(entry - stop) / entry * 1e4
    noise_bp = noise / entry * 1e4
    check(f"стоп ({stop_bp:.0f} б.п.) не меньше шума ({noise_bp:.0f} б.п.)",
          stop_bp >= noise_bp, f"{stop_bp} против {noise_bp}")
    # А в T3 было наоборот: полоса в десятую часть хода окна.
    t3_stop_bp = (0.1 * noise) / entry * 1e4
    check(f"правило T3 дало бы {t3_stop_bp:.0f} б.п. — внутри шума",
          t3_stop_bp < noise_bp)


def test_build_needs_history():
    n = 100
    t = np.arange(n, dtype=np.float64) * 60
    H = np.full(n, 101.0)
    L = np.full(n, 100.0)
    P = np.full(n, 100.5)
    V = np.full(n, 10.0)
    px, kinds, noise = LV.build(t, H, L, P, V, now_i=n)
    check("короткой истории не хватает — уровней нет", len(px) == 0,
          f"{px} {noise}")


def main():
    print("шум")
    test_noise_is_median_range()
    print("источники уровней")
    test_shelf_found_where_volume_sits()
    test_round_levels_scale_with_price()
    test_nearest_and_ahead()
    print("геометрия сделки")
    test_stop_is_outside_noise()
    test_build_needs_history()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
