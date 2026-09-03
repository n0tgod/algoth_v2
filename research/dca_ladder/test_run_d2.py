#!/usr/bin/env python3
"""Тест чистой логики D2 — построение структурных рунгов.

Чтение журнала листов, баров и уровней проверяется смоуком на VPS (данные
только там). Здесь — рунги, где легко ошибиться молча. Запуск из
`.venv/bin/python` (импорт тянет numpy/tournament/levels).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d2 as D  # noqa: E402


def test_rungs_below_with_reserve():
    # Уровни: 98, 95, 90, 80 ниже входа 100; шаг ≥1.5 %. 98 годится (−2 %),
    # 95 от 98 это −3.06 % годится, 90 от 95 −5.3 % годится → база+3.
    r = D.structural_rungs(100.0, [98.0, 95.0, 90.0, 80.0, 105.0], 0.015, 4)
    assert r == [100.0, 98.0, 95.0, 90.0], r
    print(f"ok  структурные рунги с запасом: {r}")


def test_rungs_skip_too_close():
    # 99.5 слишком близко к входу (−0.5 % < 1.5 %) — пропуск; 97 годится.
    r = D.structural_rungs(100.0, [99.5, 97.0, 90.0], 0.015, 4)
    assert r == [100.0, 97.0, 90.0], r
    print(f"ok  слишком близкий уровень пропущен: {r}")


def test_rungs_ignore_above():
    # Уровни выше входа — не рунги DCA-вниз.
    r = D.structural_rungs(100.0, [105.0, 110.0], 0.015, 4)
    assert r == [100.0], r
    print("ok  уровни выше входа игнорируются (лестница вырождается)")


def test_rungs_cap_at_n():
    # Много уровней — не больше N рунгов.
    r = D.structural_rungs(100.0, [95.0, 90.0, 85.0, 80.0, 75.0], 0.015, 4)
    assert len(r) == 4 and r == [100.0, 95.0, 90.0, 85.0], r
    print(f"ok  не больше N рунгов: {r}")


def _control_no_gap_check():
    """Без проверки запаса слишком близкие уровни попали бы в рунги —
    тест «слишком близкий пропущен» обязан упасть."""
    orig = D.structural_rungs

    def no_gap(entry, level_prices, min_gap, n_rungs):
        below = sorted([p for p in level_prices if 0 < p < entry],
                       reverse=True)
        return ([entry] + below)[:n_rungs]
    D.structural_rungs = no_gap
    try:
        try:
            test_rungs_skip_too_close()
        except AssertionError:
            return True
        return False
    finally:
        D.structural_rungs = orig


TESTS = [
    test_rungs_below_with_reserve,
    test_rungs_skip_too_close,
    test_rungs_ignore_above,
    test_rungs_cap_at_n,
]


def main():
    for t in TESTS:
        t()
    assert _control_no_gap_check(), "контроль запаса не кусается"
    print(f"\nвсе {len(TESTS)} проверки прошли; контроль запаса кусается")


if __name__ == "__main__":
    main()
