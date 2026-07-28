#!/usr/bin/env python3
"""Тесты ядра F3. Запуск: python3 -m unittest discover -s research/f3_nulls"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "f1_carry"))
import carry_nulls as NL  # noqa: E402
import carry as CY  # noqa: E402


class TestPermutation(unittest.TestCase):

    def test_multiset_is_preserved(self):
        s = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        out = NL.permuted(s, np.random.default_rng(0))
        self.assertEqual(sorted(x for x in out if x == x),
                         [1.0, 2.0, 4.0, 5.0])
        self.assertEqual(int(np.isnan(out).sum()), 1)

    def test_nan_travels_with_values(self):
        """Если бы NaN оставались на месте, число участников сечения
        менялось бы, и нуль отличался бы от прогона не только разрывом
        связи оценки с активом."""
        s = np.array([np.nan] * 5 + [1.0] * 5)
        seen = set()
        for seed in range(20):
            out = NL.permuted(s, np.random.default_rng(seed))
            seen.add(tuple(np.isnan(out)))
            self.assertEqual(int(np.isnan(out).sum()), 5)
        self.assertGreater(len(seen), 1)

    def test_deterministic_for_same_seed(self):
        s = np.arange(50.0)
        a = NL.permuted(s, np.random.default_rng(7))
        b = NL.permuted(s, np.random.default_rng(7))
        self.assertTrue(np.array_equal(a, b))


class TestRandomBook(unittest.TestCase):

    def test_eligibility_is_preserved(self):
        s = np.array([1.0, np.nan, 3.0, np.nan, 5.0])
        out = NL.random_scores(s, np.random.default_rng(1))
        self.assertTrue(np.array_equal(np.isnan(out), np.isnan(s)))

    def test_null1_and_null3_pick_the_same_kind_of_book(self):
        """Ключевая проверка: объявленные нуль 1 и нуль 3 совпадают по
        построению.

        Отбор ранговый, поэтому и перестановка оценок, и свежие
        случайные оценки дают равномерно случайное подмножество нужного
        размера. Совпадать обязаны РАСПРЕДЕЛЕНИЯ книг, а не отдельные
        реализации; сравнивается частота попадания активов в лонг.
        """
        n, width, trials = 40, 0.25, 4000
        s = np.arange(float(n))
        c1 = np.zeros(n)
        c3 = np.zeros(n)
        for seed in range(trials):
            w1, _ = CY.weights(NL.permuted(s, np.random.default_rng(seed)),
                               width)
            w3, _ = CY.weights(
                NL.random_scores(s, np.random.default_rng(10_000 + seed)),
                width)
            c1 += w1 > 0
            c3 += w3 > 0
        f1, f3 = c1 / trials, c3 / trials
        # Каждый актив обязан попадать в лонг с вероятностью width в
        # обоих нулях; допуск — три стандартные ошибки доли.
        se = (width * (1 - width) / trials) ** 0.5
        self.assertLess(float(np.abs(f1 - width).max()), 4 * se)
        self.assertLess(float(np.abs(f3 - width).max()), 4 * se)
        self.assertLess(float(np.abs(f1 - f3).max()), 6 * se)


class TestAlignByName(unittest.TestCase):

    def test_matches_by_name_not_position(self):
        out = NL.align_by_name(["A", "B", "C"], ["C", "A"],
                               np.array([9.0, 7.0]))
        self.assertEqual(list(out[[0, 2]]), [7.0, 9.0])
        self.assertTrue(np.isnan(out[1]))

    def test_same_length_does_not_imply_same_assets(self):
        """Сечения даты t и t+сдвиг бывают одной длины и разного
        состава — сопоставление по позиции молча дало бы чужие данные."""
        out = NL.align_by_name(["A", "B"], ["C", "D"], np.array([1.0, 2.0]))
        self.assertTrue(np.isnan(out).all())


class TestStats(unittest.TestCase):

    def test_percentile_known_values(self):
        v = list(range(11))
        self.assertAlmostEqual(NL.percentile(v, 95), 9.5, places=9)
        self.assertAlmostEqual(NL.percentile(v, 50), 5.0, places=9)

    def test_percentile_of_ten_is_near_max(self):
        """При десяти зёрнах 95-й процентиль почти совпадает с
        максимумом — поэтому вердикт по нему шумен, и рядом считается
        расстояние в сигмах."""
        v = list(range(10))
        self.assertGreater(NL.percentile(v, 95), 8.5)

    def test_sigmas(self):
        self.assertAlmostEqual(NL.sigmas_from(10.0, [0.0, 2.0, 4.0]), 4.0,
                               places=9)

    def test_sigmas_need_spread(self):
        self.assertIsNone(NL.sigmas_from(1.0, [2.0, 2.0, 2.0]))


if __name__ == "__main__":
    unittest.main()
