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


def test_split_window():
    # Часовые бары 0..19ч; окно вокруг 5ч, назад 2ч вперёд 3ч → бары 3..8ч,
    # now_i указывает на 5ч.
    bars = [(t, 1.0, 1.0, 1.0, 1.0, 0.0) for t in range(0, 20 * 3600, 3600)]
    ts = [b[0] for b in bars]
    win, now_i = D.split_window(bars, ts, 5 * 3600, 2, 3)
    assert [b[0] for b in win] == [3 * 3600, 4 * 3600, 5 * 3600, 6 * 3600,
                                   7 * 3600, 8 * 3600], [b[0] for b in win]
    assert win[now_i][0] == 5 * 3600, win[now_i][0]
    print(f"ok  окно среза: {len(win)} баров, вход на {win[now_i][0]//3600}ч")


def test_split_window_no_future():
    # Вход за последним баром — нет баров после входа → None.
    bars = [(t, 1.0, 1.0, 1.0, 1.0, 0.0) for t in range(0, 5 * 3600, 3600)]
    ts = [b[0] for b in bars]
    assert D.split_window(bars, ts, 10 * 3600, 2, 3) is None
    print("ok  вход за концом ряда → None")


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
    test_split_window,
    test_split_window_no_future,
]


def main():
    for t in TESTS:
        t()
    assert _control_no_gap_check(), "контроль запаса не кусается"
    print(f"\nвсе {len(TESTS)} проверки прошли; контроль запаса кусается")


if __name__ == "__main__":
    main()
