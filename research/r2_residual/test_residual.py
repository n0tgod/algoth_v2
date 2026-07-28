#!/usr/bin/env python3
"""Тесты ядра R2 на известных ответах.

Главное, что здесь проверяется, — что стенд способен увидеть возврат,
когда он есть, и НЕ увидеть, когда его нет. Второе важнее: R2 существует,
чтобы гипотезу убить, если она ложна.

Запуск: python3 -m unittest discover -s research/r2_residual
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import residual as RS  # noqa: E402


class Accumulate(unittest.TestCase):
    def test_sums_residual_over_bars(self):
        R = np.array([[0.01, 0.02], [0.03, 0.04]])
        F = np.array([[0.01, 0.01], [0.02, 0.02]])
        beta = np.array([1.0, 2.0])
        e, n = RS.accumulate(R, F, beta, 0, 2)
        # актив 0: (0.01−0.01) + (0.03−0.02) = 0.01
        # актив 1: (0.02−0.02) + (0.04−0.04) = 0.00
        self.assertAlmostEqual(e[0], 0.01, places=12)
        self.assertAlmostEqual(e[1], 0.00, places=12)
        self.assertEqual(list(n), [2, 2])

    def test_missing_bars_are_skipped_not_zeroed(self):
        """Актив, торговавшийся половину окна, не должен получать волну
        за ту половину, которой не было."""
        R = np.array([[0.05, np.nan], [0.05, np.nan]])
        F = np.array([[0.01, 0.01], [0.01, 0.01]])
        e, n = RS.accumulate(R, F, np.array([1.0, 1.0]), 0, 2)
        self.assertAlmostEqual(e[0], 0.08, places=12)
        self.assertTrue(np.isnan(e[1]))
        self.assertEqual(list(n), [2, 0])

    def test_asset_with_no_bars_is_nan_not_zero(self):
        R = np.full((3, 1), np.nan)
        F = np.zeros((3, 1))
        e, n = RS.accumulate(R, F, np.array([1.0]), 0, 3)
        self.assertTrue(np.isnan(e[0]))
        self.assertEqual(int(n[0]), 0)


class Ranks(unittest.TestCase):
    def test_average_rank_for_ties(self):
        r = RS.ranks(np.array([5.0, 1.0, 5.0, 3.0]))
        self.assertAlmostEqual(r[1], 0.0)
        self.assertAlmostEqual(r[3], 1.0)
        self.assertAlmostEqual(r[0], 2.5)
        self.assertAlmostEqual(r[2], 2.5)

    def test_all_ties_give_no_correlation(self):
        """Урок A1: связки нельзя засчитывать как согласие."""
        ic, _ = RS.spearman(np.ones(50), np.arange(50.0))
        self.assertIsNone(ic)


class Spearman(unittest.TestCase):
    def test_perfect_monotone(self):
        x = np.arange(20.0)
        ic, n = RS.spearman(x, x ** 3)
        self.assertAlmostEqual(ic, 1.0, places=12)
        self.assertEqual(n, 20)

    def test_perfect_inverse(self):
        x = np.arange(20.0)
        ic, _ = RS.spearman(x, -x)
        self.assertAlmostEqual(ic, -1.0, places=12)

    def test_independent_is_near_zero(self):
        rng = np.random.default_rng(0)
        ics = [RS.spearman(rng.normal(size=200), rng.normal(size=200))[0]
               for _ in range(200)]
        self.assertLess(abs(float(np.mean(ics))), 0.02)


class BasketSpread(unittest.TestCase):
    def test_picks_extremes_and_signs_correctly(self):
        score = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        fwd = score.copy()
        r = RS.basket_spread(score, fwd, 0.2)     # по 2 в ноге
        self.assertEqual(r["per_leg"], 2)
        self.assertAlmostEqual(r["long"], 9.5)
        self.assertAlmostEqual(r["short"], 1.5)
        self.assertAlmostEqual(r["spread"], 8.0)

    def test_no_signal_gives_zero_spread_on_average(self):
        """Порог задан стандартной ошибкой, а не выбран на глаз.

        Первая версия требовала |среднее| < 0.02, но при 300 активах в
        дециле 30 имён на ногу, и стандартная ошибка среднего по 300
        испытаниям равна 0.015 — порог стоял в 1.3 сигмы и падал бы
        примерно в каждом пятом запуске. Тест на отсутствие смещения
        обязан выражаться в сигмах, иначе он проверяет зерно генератора.
        """
        rng = np.random.default_rng(1)
        sp = [RS.basket_spread(rng.normal(size=300), rng.normal(size=300),
                               0.1)["spread"] for _ in range(2000)]
        _, t, n = RS.tstat(sp)
        self.assertEqual(n, 2000)
        self.assertLess(abs(t), 4.0)


class DetectsRealReversal(unittest.TestCase):
    """Стенд обязан увидеть возврат, если он в данных есть."""

    def test_finds_planted_mean_reversion(self):
        rng = np.random.default_rng(2)
        ics = []
        for _ in range(200):
            shock = rng.normal(0, 1.0, 300)          # отклонение от волны
            fwd = -0.3 * shock + rng.normal(0, 1.0, 300)  # частичный возврат
            ic, _ = RS.spearman(-shock, fwd)         # сигнал = минус отклонение
            ics.append(ic)
        mean, t, n = RS.tstat(ics)
        self.assertGreater(mean, 0.2)
        self.assertGreater(t, 10)
        self.assertEqual(n, 200)

    def test_finds_nothing_when_nothing_planted(self):
        """И, что важнее, НЕ находит, когда возврата нет."""
        rng = np.random.default_rng(3)
        ics = [RS.spearman(-rng.normal(size=300), rng.normal(size=300))[0]
               for _ in range(200)]
        mean, t, _ = RS.tstat(ics)
        self.assertLess(abs(mean), 0.02)
        self.assertLess(abs(t), 3.0)

    def test_momentum_gives_negative_ic(self):
        """Продолжение движения вместо возврата обязано дать минус, а не
        ноль: знак должен быть содержательным, а не абсолютной величиной."""
        rng = np.random.default_rng(4)
        ics = []
        for _ in range(100):
            shock = rng.normal(0, 1.0, 300)
            fwd = +0.3 * shock + rng.normal(0, 1.0, 300)
            ics.append(RS.spearman(-shock, fwd)[0])
        self.assertLess(float(np.mean(ics)), -0.2)


class TStat(unittest.TestCase):
    def test_known_value(self):
        mean, t, n = RS.tstat([1.0, 1.0, 1.0, 1.0, 1.0])
        self.assertAlmostEqual(mean, 1.0)
        self.assertIsNone(t)          # нулевая дисперсия — t не определена
        self.assertEqual(n, 5)

    def test_scales_with_sample_size(self):
        rng = np.random.default_rng(5)
        small = RS.tstat(rng.normal(0.1, 1.0, 25))[1]
        large = RS.tstat(rng.normal(0.1, 1.0, 2500))[1]
        self.assertGreater(abs(large), abs(small))

    def test_ignores_missing_sections(self):
        mean, _, n = RS.tstat([1.0, None, 3.0, float("nan")])
        self.assertAlmostEqual(mean, 2.0)
        self.assertEqual(n, 2)



class WindowBounds(unittest.TestCase):
    """Ошибка на один бар здесь невидима — поэтому тест явный."""

    def setUp(self):
        self.form, self.sig, self.fwd = RS.window_bounds(
            i_form=0, i_t=2160, n_returns=5000, k=7, h=5, bars_per_day=24)

    def test_forward_starts_exactly_at_rebalance(self):
        """Бар i_t−1 закончился В МОМЕНТ ребаланса и уже известен.

        Если форвард начнётся с него, стенд заработает на прошлом:
        отскок после падения в окне сигнала придёт в результат как эдж.
        """
        self.assertEqual(self.fwd[0], 2160)

    def test_signal_ends_exactly_at_rebalance(self):
        self.assertEqual(self.sig[1], 2160)

    def test_signal_and_forward_share_no_bar(self):
        self.assertLessEqual(self.sig[1], self.fwd[0])

    def test_lengths(self):
        self.assertEqual(self.sig[1] - self.sig[0], 7 * 24)
        self.assertEqual(self.fwd[1] - self.fwd[0], 5 * 24)
        self.assertEqual(self.form, (0, 2160))

    def test_signal_clipped_by_formation_start(self):
        _, sig, _ = RS.window_bounds(100, 200, 5000, 14, 1, 24)
        self.assertEqual(sig[0], 100)

    def test_forward_clipped_by_end_of_series(self):
        _, _, fwd = RS.window_bounds(0, 4990, 5000, 1, 10, 24)
        self.assertEqual(fwd[1], 5000)

if __name__ == "__main__":
    unittest.main()
