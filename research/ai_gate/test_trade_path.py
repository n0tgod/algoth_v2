#!/usr/bin/env python3
"""Меры пути сделки (§11.2): крайности против и за — стороной позиции;
первое касание цели или пола — по порядку во времени; форма — по
объявленным порогам; дыры записи — числом, не гладкостью."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trade_path as TP                                      # noqa: E402

T0 = 1_792_400_000.0


def bar(i, o, h, l, c):
    return [T0 + 60 * i, o, h, l, c, 1.0]


def main():
    # шорт от 100: сначала вверх до 108 (против) на 5-й минуте, потом вниз до 90 на 30-й
    bars = [bar(i, 100, 100, 100, 100) for i in range(0, 5)]
    bars += [bar(5, 100, 108, 100, 107)]
    bars += [bar(i, 107, 107, 107 - (i - 5), 107 - (i - 5)) for i in range(6, 23)]
    bars += [bar(i, 90, 90, 90, 90) for i in range(23, 31)]
    m = TP.metrics(bars, "short", 100.0, T0, T0 + 30 * 60, take_px=92.0, floor_px=110.0, lev=10.0, hold_h=24)
    assert abs(m["mae"] - 0.08) < 1e-9 and abs(m["mae_h"] - round(5 / 60, 2)) < 1e-6, m
    assert abs(m["mfe"] - 0.10) < 1e-9 and abs(m["mfe_margin"] - 1.0) < 1e-9, m
    assert m["first_touch"] == "take" and m["shape"] == "against_then_for", m
    assert m["bars"] == 31 and m["gap_min"] == 0 and m["life_h"] == 0.5 and m["life_share"] == round(0.5 / 24, 3), m
    # лонг: пол раньше цели — first_touch=floor, даже если потом цель и была
    bars2 = [bar(0, 100, 100, 100, 100), bar(1, 100, 100, 94, 94), bar(2, 94, 112, 94, 112)]
    m2 = TP.metrics(bars2, "long", 100.0, T0, T0 + 2 * 60, take_px=110.0, floor_px=95.0)
    assert m2["first_touch"] == "floor" and abs(m2["mae"] - 0.06) < 1e-9 and abs(m2["mfe"] - 0.12) < 1e-9, m2
    # спайк: против на 2-й минуте на 6 %, итог почти ноль
    bars3 = [bar(0, 100, 100, 100, 100), bar(2, 100, 106, 100, 100.2), bar(9, 100.2, 100.3, 100, 100.1)]
    m3 = TP.metrics(bars3, "short", 100.0, T0, T0 + 9 * 60)
    assert m3["shape"] == "spike_against" and m3["gap_min"] == 7, m3
    # сразу за: против ≤ трети хода за
    bars4 = [bar(0, 100, 101, 100, 100), bar(1, 100, 100, 94, 94), bar(2, 94, 94, 90, 90)]
    m4 = TP.metrics(bars4, "short", 100.0, T0, T0 + 2 * 60)
    assert m4["shape"] == "straight_for" and m4["first_touch"] == "none", m4
    # без баров — не ноль, а «не измерено»
    m5 = TP.metrics([], "short", 100.0, T0, T0 + 600)
    assert m5["shape"] == "no_bars" and m5["mae"] is None and "не измерен" in TP.words(m5)
    w = TP.words(dict(m, market_move=-0.012))
    assert "сначала против, потом за" in w and "против до 8.0 %" in w and "цели" in w and "рынок за это время -1.2 %" in w, w
    assert "against, then in favour" in TP.words(m, "en")
    print("ok  путь сделки: крайности стороной позиции, первое касание по времени, форма по порогам, дыры числом, слова из чисел")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
