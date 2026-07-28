#!/usr/bin/env python3
"""Тесты ядра F2 на известных ответах.

Запуск: python3 -m unittest discover -s research/f2_traps
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traps as T  # noqa: E402


class TestBeta(unittest.TestCase):

    def test_exact_slope(self):
        x = np.linspace(-0.1, 0.1, 40)
        y = 0.35 * x + 0.001
        b, r2, n = T.beta(y, x)
        self.assertAlmostEqual(b, 0.35, places=9)
        self.assertAlmostEqual(r2, 1.0, places=9)
        self.assertEqual(n, 40)

    def test_market_neutral_book_gives_zero(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 0.05, 300)
        y = rng.normal(0, 0.01, 300)
        b, _, _ = T.beta(y, x)
        self.assertLess(abs(b), 0.1)

    def test_short_market_bet_is_detected(self):
        """Ловушка §5.2: книга, оказавшаяся ставкой против рынка.

        Именно её F1 сделал решающей — обе ноги ехали вниз, и надо
        показать, что книга не является переодетым шортом беты.
        """
        rng = np.random.default_rng(2)
        x = rng.normal(0, 0.05, 200)
        y = -0.6 * x + rng.normal(0, 0.005, 200)
        b, _, _ = T.beta(y, x)
        self.assertLess(b, -0.4)

    def test_flat_market_gives_nothing(self):
        self.assertIsNone(T.beta(np.arange(20.0), np.zeros(20)))

    def test_short_series_gives_nothing(self):
        self.assertIsNone(T.beta(np.arange(9.0), np.arange(9.0)))

    def test_rolling_beta_sees_regime_change(self):
        """Одно число скрывает смену знака: β +0.5 полгода и −0.5 полгода
        в среднем даст ноль, и книга покажется нейтральной."""
        rng = np.random.default_rng(4)
        x = rng.normal(0, 0.05, 200)
        y = np.concatenate([+0.5 * x[:100], -0.5 * x[100:]])
        overall, _, _ = T.beta(y, x)
        roll = T.rolling_beta(y, x, 40)
        self.assertLess(abs(overall), 0.2)
        self.assertGreater(max(roll), 0.3)
        self.assertLess(min(roll), -0.3)


class TestMarketReturn(unittest.TestCase):

    def test_equal_weighted_mean(self):
        self.assertAlmostEqual(T.market_return([0.01, 0.03, -0.02]),
                               0.0066666666, places=9)

    def test_missing_is_excluded_not_zeroed(self):
        """Ноль означал бы «актив не двигался» — наблюдение, которого
        не было; он занизил бы волну и завысил β книги."""
        self.assertAlmostEqual(T.market_return([0.02, np.nan, 0.04]),
                               0.03, places=12)

    def test_all_missing(self):
        self.assertTrue(np.isnan(T.market_return([np.nan, np.nan])))


class TestDelisting(unittest.TestCase):

    def test_counts_only_weighted_names_inside_horizon(self):
        names = ["A", "B", "C", "D"]
        w = np.array([0.5, 0.0, -0.5, 0.0])
        last = {"A": "2024-01-20", "B": "2024-01-20", "D": "2024-01-05"}
        share, hit = T.near_delisting(names, w, last, "2024-01-01", 30)
        self.assertAlmostEqual(share, 0.5, places=12)
        self.assertEqual(hit, ["A"])

    def test_already_delisted_does_not_count(self):
        """Отрицательный зазор — актив снят в прошлом; в книге его быть
        не должно вовсе, и записывать это в ловушку будущего нельзя."""
        names = ["A"]
        share, hit = T.near_delisting(names, np.array([0.5]),
                                      {"A": "2023-12-01"}, "2024-01-01", 30)
        self.assertEqual(share, 0.0)
        self.assertEqual(hit, [])


class TestRegimeChange(unittest.TestCase):

    def test_same_rate_per_day_is_not_a_change(self):
        """Окна разной длины дают разное ЧИСЛО начислений при неизменном
        режиме — сравнивать надо начисления в сутки."""
        flags = T.regime_change([21], [15], days_form=7, days_hold=5)
        self.assertFalse(bool(flags[0]))

    def test_four_hourly_to_hourly_is_a_change(self):
        flags = T.regime_change([42], [120], days_form=7, days_hold=5)
        self.assertTrue(bool(flags[0]))

    def test_missing_counts_as_no_change(self):
        flags = T.regime_change([None], [10], 7, 5)
        self.assertFalse(bool(flags[0]))

    def test_weighted_share(self):
        w = np.array([0.25, -0.25, 0.25, -0.25])
        self.assertAlmostEqual(
            T.weighted_share(w, [True, False, False, False]), 0.25, places=12)


class TestCapacity(unittest.TestCase):

    def test_known_limit(self):
        """Позиция 0.5 · $20 000 = $10 000 против оборота $1 млн есть
        1 % оборота; предел при 5 % — $100 000."""
        w = np.array([0.5, -0.5])
        turn = {"A": 1_000_000.0, "B": 1_000_000.0}
        c = T.capacity(w, turn, ["A", "B"], 20_000, 0.05)
        self.assertAlmostEqual(c["worst_share"], 0.01, places=12)
        self.assertAlmostEqual(c["capital_limit"], 100_000.0, places=6)

    def test_asset_without_turnover_is_skipped(self):
        c = T.capacity(np.array([0.5, -0.5]), {"A": 1e6}, ["A", "B"], 20_000)
        self.assertEqual(c["names"], 1)


if __name__ == "__main__":
    unittest.main()
