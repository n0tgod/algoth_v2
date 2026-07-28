#!/usr/bin/env python3
"""Проверки сводки walk-forward.

Числа этой сводки решают судьбу фазы A: критерий 1 (пар после FDR на
окно), критерий 2 (выживание между окнами) и правило немедленной
остановки. Ошибка в знаменателе или в шаге сетки не выглядит как ошибка
— она выглядит как результат. Поэтому здесь проверяется именно
арифметика решения, а не то, что код запускается.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walkforward as W  # noqa: E402


def window(date, pairs_fdr, pairs_sel=None, candidates=100):
    """Окно с заданными наборами прошедших пар."""
    sel = set(pairs_sel if pairs_sel is not None else pairs_fdr)
    pairs = [{"pair": p, "p": 0.001, "n": 2160,
              "half_life_days": 1.0 if p in sel else 40.0,
              "fdr": True, "selected": p in sel} for p in pairs_fdr]
    return {"date": date, "candidates": candidates, "tested": len(pairs),
            "raw_pass": len(pairs), "fdr_pass": len(pairs_fdr),
            "selected": len(sel), "pairs": pairs}


def grid(sets, start="2023-01-01"):
    """Окна, расставленные ровно по шагу сетки."""
    from datetime import date, timedelta
    t = date.fromisoformat(start)
    out = []
    for s in sets:
        out.append(window(t.isoformat(), s))
        t += timedelta(days=W.TRADE_DAYS)
    return out


class Overlap(unittest.TestCase):
    def test_denominator_is_the_earlier_window(self):
        """Вопрос §8 — сколько из отобранного удержалось.

        Знаменатель — размер раннего набора, не позднего и не
        объединения: иначе окно, отобравшее вдвое больше пар, само по
        себе улучшало бы или ухудшало метрику.
        """
        a, b = {"X/Y", "P/Q"}, {"X/Y", "M/N", "K/L", "R/S"}
        self.assertAlmostEqual(W.overlap(a, b), 0.5)
        self.assertAlmostEqual(W.overlap(b, a), 0.25)

    def test_empty_earlier_window_is_not_zero(self):
        """Окно, не отобравшее ничего, не имеет выживаемости.

        Ноль здесь означал бы «всё потеряно» и тянул бы среднее вниз,
        тогда как терять было нечего.
        """
        import math
        self.assertTrue(math.isnan(W.overlap(set(), {"X/Y"})))

    def test_identical_sets(self):
        self.assertAlmostEqual(W.overlap({"A/B"}, {"A/B"}), 1.0)


class Summary(unittest.TestCase):
    def test_survival_pairs_consecutive_windows(self):
        rows = grid([{"A/B", "C/D"}, {"A/B", "E/F"}, {"E/F", "G/H"}])
        s = W.summarize(rows)
        # 1→2: 1 из 2, 2→3: 1 из 2.
        self.assertAlmostEqual(s["survival_adjacent_fdr"], 0.5)

    def test_three_step_survival_skips_overlapping_windows(self):
        rows = grid([{"A/B"}, {"X/Y"}, {"X/Y"}, {"A/B"}, {"Z/W"}])
        s = W.summarize(rows)
        # 1→4: A/B дожила (1.0), 2→5: X/Y не дожила (0.0).
        self.assertAlmostEqual(s["survival_three_steps_fdr"], 0.5)

    def test_criteria_read_from_the_thresholds_in_spec(self):
        rows = grid([set(f"P{i}/Q{i}" for i in range(60))] * 4)
        s = W.summarize(rows)
        self.assertTrue(s["criterion_1_fdr_ge_50"])
        self.assertTrue(s["criterion_2_survival_ge_30pct"])
        self.assertFalse(s["stop_rule_triggered"])

    def test_stop_rule_needs_most_windows_not_some(self):
        """Правило остановки — «в большинстве окон», а не «хотя бы в одном»."""
        few, many = {"A/B"}, set(f"P{i}/Q{i}" for i in range(20))
        s = W.summarize(grid([few, many, many, many]))
        self.assertFalse(s["stop_rule_triggered"])
        s = W.summarize(grid([few, few, few, many]))
        self.assertTrue(s["stop_rule_triggered"])

    def test_half_life_filter_narrows_selection(self):
        rows = grid([{"A/B", "C/D"}])
        rows[0] = window(rows[0]["date"], {"A/B", "C/D"}, pairs_sel={"A/B"})
        s = W.summarize(rows)
        self.assertEqual(s["fdr_pass_mean"], 2.0)
        self.assertEqual(s["selected_mean"], 1.0)

    def test_off_grid_window_is_refused_not_averaged(self):
        """Окно не по сетке ломает смысл «соседнего» — и должно падать.

        Молча посчитанная сводка по разношаговой сетке выглядела бы
        нормально: критерий 2 просто оказался бы выше или ниже.
        """
        rows = grid([{"A/B"}, {"A/B"}])
        rows.append(window("2023-03-05", {"A/B"}))
        with self.assertRaises(SystemExit):
            W.summarize(rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
