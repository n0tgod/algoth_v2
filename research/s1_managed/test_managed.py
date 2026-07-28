#!/usr/bin/env python3
"""Тесты ядра S1. Запуск: python3 -m unittest discover -s research/s1_managed"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import managed as M  # noqa: E402


class TestInverseVolWeights(unittest.TestCase):

    def test_gross_is_one_and_legs_equal_in_money(self):
        score = np.arange(20.0)
        vol = np.full(20, 0.05)
        w, k = M.inverse_vol_weights(score, vol, 0.10)
        self.assertEqual(k, 2)
        self.assertAlmostEqual(float(np.abs(w).sum()), 1.0, places=12)
        self.assertAlmostEqual(float(w[w > 0].sum()), 0.5, places=12)
        self.assertAlmostEqual(float(w[w < 0].sum()), -0.5, places=12)

    def test_volatile_name_gets_smaller_share(self):
        """Суть правила 1: актив, который ходит в разы, получает меньшую
        долю ноги ещё до того, как что-либо произошло."""
        score = np.array([10.0, 9.0, 1.0, 0.0])
        # Волатильности подобраны так, чтобы пол сечения не связывал:
        # иначе тест мерил бы не правило, а защиту от него.
        vol = np.array([0.020, 0.005, 0.005, 0.005])
        w, _ = M.inverse_vol_weights(score, vol, 0.50)
        self.assertLess(abs(w[0]), abs(w[1]))
        self.assertAlmostEqual(abs(w[0]) / abs(w[1]), 0.005 / 0.020,
                               places=12)

    def test_floor_binds_when_a_name_is_far_below_the_section(self):
        """Тот же расчёт, но одно имя вдесятеро спокойнее сечения: пол
        обязан связать, и отношение весов выходит мягче голого 1/σ."""
        score = np.array([10.0, 9.0, 1.0, 0.0])
        vol = np.array([0.10, 0.02, 0.05, 0.05])
        w, _ = M.inverse_vol_weights(score, vol, 0.50)
        naked = 0.02 / 0.10
        self.assertGreater(abs(w[0]) / abs(w[1]), naked)

    def test_equal_vol_reproduces_equal_weights(self):
        """Проверка на вырождение: при одинаковой волатильности правило
        обязано совпасть с равными весами до последнего знака."""
        rng = np.random.default_rng(1)
        score = rng.normal(size=60)
        vol = np.full(60, 0.037)
        a, _ = M.inverse_vol_weights(score, vol, 0.20)
        b, _ = M.equal_weights(score, vol, 0.20)
        self.assertTrue(np.allclose(a, b, atol=1e-15))

    def test_frozen_series_is_excluded(self):
        """У замороженного ряда (A2) волатильность равна нулю, и
        обратная величина дала бы ему бесконечный вес — дефект данных
        стал бы всей книгой."""
        score = np.array([5.0, 4.0, 3.0, 2.0])
        vol = np.array([0.0, 0.05, 0.05, 0.05])
        w, k = M.inverse_vol_weights(score, vol, 0.50)
        self.assertEqual(float(w[0]), 0.0)
        self.assertTrue(np.isfinite(w).all())
        self.assertEqual(k, 1)

    def test_same_universe_as_control_arm(self):
        score = np.array([5.0, 4.0, np.nan, 2.0, 1.0, 0.0])
        vol = np.array([0.05, 0.0, 0.05, 0.05, 0.05, 0.05])
        a, ka = M.inverse_vol_weights(score, vol, 0.25)
        b, kb = M.equal_weights(score, vol, 0.25)
        self.assertEqual(ka, kb)
        self.assertTrue(np.array_equal(a != 0, b != 0))


class TestExits(unittest.TestCase):

    def test_untouched_leg_keeps_full_period(self):
        w = np.array([0.5, -0.5])
        pos = np.array([0.03, -0.02])
        ex = np.array([np.nan, np.nan])
        fr = np.array([np.nan, np.nan])
        fund = np.array([0.0, 0.0])
        ret, hit = M.apply_exits(w, pos, ex, fr, fund)
        self.assertFalse(hit.any())
        self.assertTrue(np.allclose(ret, pos))

    def test_exit_replaces_period_return(self):
        w = np.array([0.5])
        ret, hit = M.apply_exits(w, np.array([-0.80]), np.array([-0.45]),
                                 np.array([0.4]), np.array([0.0]))
        self.assertTrue(bool(hit[0]))
        self.assertAlmostEqual(float(ret[0]), -0.45, places=12)

    def test_funding_is_prorated_not_kept_whole(self):
        """Выбитая нога перестаёт получать начисления. Оставить их
        целиком значило бы дарить книге доход, которого не было."""
        w = np.array([-0.5])                      # шорт
        fund = np.array([0.02])                   # лонги платят 2 %
        ret, _ = M.apply_exits(w, np.array([-0.5]), np.array([-0.45]),
                               np.array([0.25]), fund)
        # шорт получает +2 % за полный период, здесь — четверть
        self.assertAlmostEqual(float(ret[0]), -0.45 + 0.02 * 0.25, places=12)

    def test_long_pays_funding_with_correct_sign(self):
        w = np.array([0.5])
        ret, _ = M.apply_exits(w, np.array([0.0]), np.array([np.nan]),
                               np.array([np.nan]), np.array([0.01]))
        self.assertAlmostEqual(float(ret[0]), -0.01, places=12)


class TestBookStats(unittest.TestCase):

    def test_pnl_splits_by_leg(self):
        w = np.array([0.25, 0.25, -0.25, -0.25])
        r = np.array([0.10, 0.00, 0.20, -0.40])
        b = M.book_pnl(w, r)
        self.assertAlmostEqual(b["long"], 0.025, places=12)
        self.assertAlmostEqual(b["short"], -0.05, places=12)
        self.assertAlmostEqual(b["gross"], b["long"] + b["short"], places=12)
        self.assertAlmostEqual(b["worst_leg"], -0.40, places=12)

    def test_unpaired_share_zero_when_nothing_fires(self):
        w = np.array([0.25, 0.25, -0.25, -0.25])
        hit = np.zeros(4, dtype=bool)
        self.assertAlmostEqual(M.unpaired_share(w, hit), 0.0, places=12)

    def test_unpaired_share_after_one_side_exits(self):
        """Выбило одну короткую ногу из двух: осталось 0.5 лонга против
        0.25 шорта, перекос — треть оставшегося гросса."""
        w = np.array([0.25, 0.25, -0.25, -0.25])
        hit = np.array([False, False, True, False])
        self.assertAlmostEqual(M.unpaired_share(w, hit), 0.25 / 0.75,
                               places=12)

    def test_turnover_counts_only_fired_legs(self):
        w = np.array([0.25, 0.25, -0.25, -0.25])
        hit = np.array([True, False, True, False])
        self.assertAlmostEqual(M.turnover_from_exits(w, hit), 0.5, places=12)



class TestVolFloor(unittest.TestCase):
    """Пол волатильности. Без него правило 1 — ловушка замороженных рядов."""

    def test_near_frozen_name_cannot_take_the_leg(self):
        """Замер, поймавший дефект: σ медианы 0.008 против 0.000057 у
        0.1-го процентиля, и такой актив забирал до 92.7 % своей
        половины книги."""
        n = 40
        score = np.arange(float(n))
        vol = np.full(n, 0.008)
        vol[n - 1] = 0.000057          # почти замороженный, попадёт в лонг
        w, k = M.inverse_vol_weights(score, vol, 0.25)
        share = abs(w[n - 1]) / 0.5
        self.assertLess(share, 0.30)

    def test_floor_is_taken_from_the_section_not_a_constant(self):
        """Волатильность универсума меняется с режимом рынка: пол,
        заданный числом, связывал бы то слишком сильно, то никак."""
        ok = np.ones(20, dtype=bool)
        quiet = M.floored_vol(np.full(20, 0.002), ok)
        loud = M.floored_vol(np.full(20, 0.020), ok)
        self.assertAlmostEqual(float(quiet.min()), 0.002, places=12)
        self.assertAlmostEqual(float(loud.min()), 0.020, places=12)

    def test_high_vol_tail_is_not_trimmed(self):
        """Подавлять волатильные имена и есть смысл правила — верхний
        хвост подрезать нельзя."""
        ok = np.ones(11, dtype=bool)
        vol = np.array([0.005] * 10 + [0.10])
        out = M.floored_vol(vol, ok)
        self.assertAlmostEqual(float(out[-1]), 0.10, places=12)

    def test_still_downweights_the_volatile_name(self):
        vol = np.array([0.030, 0.006, 0.006, 0.006])
        score = np.array([10.0, 9.0, 1.0, 0.0])
        w, _ = M.inverse_vol_weights(score, vol, 0.50)
        self.assertLess(abs(w[0]), abs(w[1]))


if __name__ == "__main__":
    unittest.main()
