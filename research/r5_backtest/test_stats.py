#!/usr/bin/env python3
"""Тесты ядра R5 на известных ответах.

Главное здесь — что поправка на число испытаний действительно
обесценивает результат перебора. Тест на это устроен как эксперимент:
берём заведомо пустой ряд, перебираем сетку, находим лучшую ячейку — и
требуем, чтобы поправка её убила.

Запуск: python3 -m unittest discover -s research/r5_backtest
"""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats as S  # noqa: E402


class NormPpf(unittest.TestCase):
    def test_known_quantiles(self):
        self.assertAlmostEqual(S.norm_ppf(0.5), 0.0, places=12)
        self.assertAlmostEqual(S.norm_ppf(0.975), 1.959963985, places=8)
        self.assertAlmostEqual(S.norm_ppf(0.99), 2.326347874, places=8)
        self.assertAlmostEqual(S.norm_ppf(0.001), -3.090232306, places=8)

    def test_round_trip(self):
        for p in (0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.999):
            self.assertAlmostEqual(S.norm_cdf(S.norm_ppf(p)), p, places=12)


class Sharpe(unittest.TestCase):
    def test_known_value(self):
        """Ряд со средним 0.001 и разбросом 0.01 при 252 периодах в год.

        Разброс считается ПО ВЫБОРКЕ (ddof=1), а не по генеральной
        совокупности: у нас конечный ряд наблюдений, а не популяция.
        Разница на 1000 точках — четвёртый знак, но тест, написанный под
        ddof=0, закрепил бы неверную формулу.
        """
        n = 1000
        v = [0.001 + 0.01 * x for x in (-1, 1) * (n // 2)]
        sd = 0.01 * math.sqrt(n / (n - 1))
        self.assertAlmostEqual(S.sharpe(v, 252), 0.001 / sd * math.sqrt(252),
                               places=9)

    def test_constant_series_has_no_sharpe(self):
        self.assertIsNone(S.sharpe([0.01] * 50, 252))


class ExpectedMaxSharpe(unittest.TestCase):
    def test_grows_with_number_of_trials(self):
        a = S.expected_max_sharpe(10, 1.0)
        b = S.expected_max_sharpe(96, 1.0)
        c = S.expected_max_sharpe(1000, 1.0)
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_scales_with_spread_of_trials(self):
        self.assertAlmostEqual(S.expected_max_sharpe(96, 2.0),
                               2.0 * S.expected_max_sharpe(96, 1.0),
                               places=12)

    def test_no_correction_for_single_trial(self):
        self.assertEqual(S.expected_max_sharpe(1, 1.0), 0.0)


class CorrectionKillsPureSearch(unittest.TestCase):
    """Проверка смысла поправки, а не её формулы.

    Строим 96 рядов чистого шума, берём лучший по Sharpe — он выйдет
    заметно положительным просто потому, что мы перебирали. Поправка
    обязана его обнулить.
    """

    def test_best_of_pure_noise_does_not_survive(self):
        rnd = random.Random(0)
        n_obs, n_trials, ppy = 133, 96, 36.5
        trials = [[rnd.gauss(0.0, 0.01) for _ in range(n_obs)]
                  for _ in range(n_trials)]
        srs = [S.sharpe(t, ppy) for t in trials]
        sr_std = S.moments(srs)["sd"]
        best_i = max(range(n_trials), key=lambda i: srs[i])

        self.assertGreater(srs[best_i], 0.8)      # без поправки «проходит»
        d = S.deflated_sharpe(trials[best_i], ppy, n_trials, sr_std)
        self.assertLess(d["sharpe_deflated"], 0.8)   # с поправкой — нет
        self.assertLess(d["dsr_probability"], 0.95)

    def test_real_edge_survives_the_same_correction(self):
        """Обратная проверка: поправка не должна убивать всё подряд."""
        rnd = random.Random(1)
        n_obs, n_trials, ppy = 133, 96, 36.5
        trials = [[rnd.gauss(0.0, 0.01) for _ in range(n_obs)]
                  for _ in range(n_trials)]
        srs = [S.sharpe(t, ppy) for t in trials]
        sr_std = S.moments(srs)["sd"]
        strong = [rnd.gauss(0.006, 0.01) for _ in range(n_obs)]
        d = S.deflated_sharpe(strong, ppy, n_trials, sr_std)
        self.assertGreater(d["sharpe_annual"], 2.5)
        self.assertGreater(d["sharpe_deflated"], 0.8)


class HeavyTails(unittest.TestCase):
    def test_dsr_falls_on_fat_tails_when_sharpe_does_not(self):
        """Смысл второй версии поправки: у ряда с тяжёлыми хвостами
        обычный Sharpe этого не показывает, а DSR показывает."""
        rnd = random.Random(2)
        n, ppy = 200, 36.5
        thin = [rnd.gauss(0.002, 0.01) for _ in range(n)]
        fat = list(thin)
        for i in range(0, n, 20):                 # редкие крупные выбросы
            fat[i] -= 0.06
            fat[i + 1] += 0.06
        a = S.deflated_sharpe(thin, ppy, 96, 0.5)
        b = S.deflated_sharpe(fat, ppy, 96, 0.5)
        self.assertGreater(b["kurtosis"], a["kurtosis"])
        self.assertLess(b["dsr_probability"], a["dsr_probability"])


class Drawdown(unittest.TestCase):
    def test_known_case(self):
        """+10 %, затем −50 % даёт просадку ровно 50 %."""
        r = S.max_drawdown([0.10, -0.50])
        self.assertAlmostEqual(r["max_drawdown"], -0.50, places=12)
        self.assertAlmostEqual(r["final_equity"], 1.10 * 0.50, places=12)

    def test_monotone_growth_has_no_drawdown(self):
        r = S.max_drawdown([0.01] * 20)
        self.assertAlmostEqual(r["max_drawdown"], 0.0, places=12)

    def test_compounding_not_summing(self):
        """Просадка считается сложением, а не суммой: счёт считает так."""
        r = S.max_drawdown([-0.5, -0.5])
        self.assertAlmostEqual(r["final_equity"], 0.25, places=12)
        self.assertAlmostEqual(r["max_drawdown"], -0.75, places=12)


class Splits(unittest.TestCase):
    def test_by_year(self):
        d = ["2022-01-01", "2022-06-01", "2023-01-01"]
        out = S.split_by_year(d, [1.0, 2.0, 3.0])
        self.assertEqual(out["2022"], [1.0, 2.0])
        self.assertEqual(out["2023"], [3.0])

    def test_equal_parts_cover_everything(self):
        out = S.split_equal(list(range(10)), 3)
        self.assertEqual(sum(len(v) for v in out.values()), 10)


if __name__ == "__main__":
    unittest.main()
