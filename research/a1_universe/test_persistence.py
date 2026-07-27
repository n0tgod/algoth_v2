#!/usr/bin/env python3
"""
Тесты статистики персистентности funding.

Проверяется то, на чём стоит вывод по вопросу 12.4 спеки 01. Ошибка здесь
не падает: доля согласованных пар получится 0.52 вместо 0.50, и это будет
прочитано как «слабая, но связь есть». Поэтому каждая быстрая формула
сверяется с медленной, но очевидной — перебором всех пар.

    python3 test_persistence.py
"""

import itertools
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from funding_persistence import (  # noqa: E402
    MS_DAY, _count_inversions, decile_spread, pair_sign_agreement,
    spearman, window_rate,
)


def brute_agreement(f, g):
    """То же, что `pair_sign_agreement`, но перебором.

    Пара без знака (равенство на любом из концов) в знаменатель не идёт.
    """
    n = len(f)
    ok = ties = ranked = 0
    for i, j in itertools.combinations(range(n), 2):
        df, dg = f[i] - f[j], g[i] - g[j]
        if df == 0 or dg == 0:
            ties += 1
            continue
        ranked += 1
        if df * dg > 0:
            ok += 1
    total = n * (n - 1) // 2
    return (ok / ranked if ranked else None), ties / total


class Inversions(unittest.TestCase):
    def test_sorted(self):
        self.assertEqual(_count_inversions([1, 2, 3, 4, 5]), 0)

    def test_reversed(self):
        self.assertEqual(_count_inversions([5, 4, 3, 2, 1]), 10)

    def test_ties_are_not_inversions(self):
        self.assertEqual(_count_inversions([2, 2, 2]), 0)

    def test_matches_brute_force(self):
        seqs = [
            [3, 1, 2], [1, 3, 2, 4], [9, 7, 8, 1, 2, 3],
            [1, 1, 2, 0, 5, 5, 3], list(range(20, 0, -1)),
            [i % 7 for i in range(31)],
        ]
        for s in seqs:
            brute = sum(1 for i, j in itertools.combinations(range(len(s)), 2)
                        if s[i] > s[j])
            self.assertEqual(_count_inversions(s), brute, s)


class PairSignAgreement(unittest.TestCase):
    def test_identical_order_is_one(self):
        f = [1.0, 2.0, 3.0, 4.0]
        share, ties, n = pair_sign_agreement(f, [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(share, 1.0)
        self.assertEqual(ties, 0.0)
        self.assertEqual(n, 6)

    def test_reversed_order_is_zero(self):
        share, _, _ = pair_sign_agreement([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
        self.assertEqual(share, 0.0)

    def test_matches_brute_force(self):
        cases = [
            ([1, 5, 3, 2, 4], [2, 1, 5, 3, 4]),
            ([0.1, -0.2, 0.3, 0.0, -0.5, 0.7], [0.2, 0.1, -0.3, 0.4, -0.1, 0.0]),
            ([i * 0.37 % 1 for i in range(40)], [i * 0.61 % 1 for i in range(40)]),
        ]
        for f, g in cases:
            f = [float(x) for x in f]
            g = [float(x) for x in g]
            share, ties, _ = pair_sign_agreement(f, g)
            b_share, b_ties = brute_agreement(f, g)
            self.assertAlmostEqual(share, b_share, places=12)
            self.assertAlmostEqual(ties, b_ties, places=12)

    def test_ties_excluded_matches_brute_force(self):
        """Ряд с обилием точных совпадений — как настоящие ставки funding."""
        cases = [
            ([1.0, 1.0, 1.0, 2.0, 2.0, 3.0], [5.0, 5.0, 4.0, 4.0, 9.0, 9.0]),
            ([float(i % 3) for i in range(30)], [float(i % 4) for i in range(30)]),
            ([float(i % 2) for i in range(24)], [float((i // 2) % 2) for i in range(24)]),
        ]
        for f, g in cases:
            share, ties, _ = pair_sign_agreement(f, g)
            b_share, b_ties = brute_agreement(f, g)
            self.assertAlmostEqual(ties, b_ties, places=12, msg=f)
            if b_share is None:
                self.assertIsNone(share)
            else:
                self.assertAlmostEqual(share, b_share, places=12, msg=f)

    def test_all_tied_has_no_sign(self):
        share, ties, _ = pair_sign_agreement([1.0] * 5, [2.0] * 5)
        self.assertIsNone(share)
        self.assertEqual(ties, 1.0)

    def test_independent_series_is_near_half(self):
        """Отсутствие связи должно давать 50 %, а не смещённую величину."""
        f = [((i * 7919) % 1013) / 1013 for i in range(200)]
        g = [((i * 104729) % 1009) / 1009 for i in range(200)]
        share, _, _ = pair_sign_agreement(f, g)
        self.assertAlmostEqual(share, 0.5, delta=0.05)


class Spearman(unittest.TestCase):
    def test_monotone(self):
        self.assertAlmostEqual(spearman([1.0, 2.0, 3.0], [5.0, 6.0, 9.0]), 1.0)

    def test_antitone(self):
        self.assertAlmostEqual(spearman([1.0, 2.0, 3.0], [9.0, 6.0, 5.0]), -1.0)

    def test_known_value(self):
        # Ранги f: 1..5; ранги g: 2,1,4,3,5 → сумма d² = 4, rho = 1 − 6·4/120.
        rho = spearman([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 1.0, 4.0, 3.0, 5.0])
        self.assertAlmostEqual(rho, 0.8)


class DecileSpread(unittest.TestCase):
    def test_selection_is_by_past_only(self):
        """Отбор по `f`; `g` считается по тем же активам, а не пересортировкой.

        Это главное свойство измерения. Если бы `g` сортировался заново,
        полученный спред всегда был бы положительным и измерение отвечало
        бы «да» на любых данных.
        """
        f = [10.0, 5.0, 0.0, -5.0, -10.0, 1.0, 2.0, 3.0, 4.0, 6.0]
        g = [-10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        prom, real, k, lowk, highk = decile_spread(f, g)
        self.assertEqual(k, 1)
        self.assertEqual(prom, 20.0)        # 10 − (−10)
        self.assertEqual(real, -20.0)       # те же активы дали обратное

    def test_promised_is_nonnegative(self):
        f = [3.0, 1.0, 2.0, 8.0, -4.0, 0.5, 7.0, -2.0, 6.0, 0.0]
        prom, _, _, _, _ = decile_spread(f, f)
        self.assertGreater(prom, 0)


def _series(step_h, n, rate, start_ms=0):
    """Ряд из `n` начислений с постоянным шагом и постоянной ставкой."""
    from array import array
    ts = array("q", [start_ms + i * step_h * 3_600_000 for i in range(n)])
    rates = array("d", [rate] * n)
    pre = array("d", [0.0])
    s = 0.0
    for r in rates:
        s += r
        pre.append(s)
    return ts, rates, pre


class WindowRate(unittest.TestCase):
    def test_constant_rate_annualizes(self):
        """8 ч × 0.0001 = 3 начисления в сутки → 0.0003 в сутки → 10.95 % годовых."""
        s = _series(8, 400, 0.0001)
        t0 = 50 * MS_DAY
        r = window_rate(s, t0, t0 + 10 * MS_DAY)
        self.assertAlmostEqual(r, 0.0001 * 3 * 365 * 100, places=6)

    def test_hourly_regime_gives_eight_times_more(self):
        """Тот же размер ставки при часовом режиме стоит в восемь раз дороже."""
        s = _series(1, 3000, 0.0001)
        t0 = 50 * MS_DAY
        r = window_rate(s, t0, t0 + 10 * MS_DAY)
        self.assertAlmostEqual(r, 0.0001 * 24 * 365 * 100, places=6)

    def test_window_outside_series_rejected(self):
        s = _series(8, 100, 0.0001)          # ~33 суток истории
        self.assertIsNone(window_rate(s, 40 * MS_DAY, 45 * MS_DAY))

    def test_window_before_series_rejected(self):
        s = _series(8, 100, 0.0001, start_ms=10 * MS_DAY)
        self.assertIsNone(window_rate(s, 5 * MS_DAY, 12 * MS_DAY))

    def test_hole_at_window_edge_rejected(self):
        """Дыра у края окна занижает сумму — такое окно брать нельзя."""
        from array import array
        base = _series(8, 200, 0.0001)
        ts = [t for t in base[0]]
        # выбрасываем начисления, попадающие в первые двое суток окна
        t0 = 50 * MS_DAY
        keep = [t for t in ts if not (t0 <= t < t0 + 2 * MS_DAY)]
        pre = array("d", [0.0])
        s = 0.0
        for _ in keep:
            s += 0.0001
            pre.append(s)
        series = (array("q", keep), array("d", [0.0001] * len(keep)), pre)
        self.assertIsNone(window_rate(series, t0, t0 + 10 * MS_DAY))

    def test_short_window_rejected(self):
        s = _series(8, 400, 0.0001)
        t0 = 50 * MS_DAY
        self.assertIsNone(window_rate(s, t0, t0 + 3_600_000))   # один час


if __name__ == "__main__":
    unittest.main(verbosity=2)
