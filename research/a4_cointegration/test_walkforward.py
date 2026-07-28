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


def window(date, pairs_fdr, pairs_sel=None, candidates=None):
    """Окно с заданными наборами прошедших пар.

    `candidates` — весь список проверенного в этом окне. По умолчанию
    совпадает с прошедшими: тесту, которому кандидаты безразличны,
    незачем их перечислять.
    """
    sel = set(pairs_sel if pairs_sel is not None else pairs_fdr)
    tested = set(candidates) if candidates is not None else set(pairs_fdr)
    tested |= set(pairs_fdr)
    pairs = [{"pair": p, "p": 0.001 if p in pairs_fdr else 0.5, "n": 2160,
              "half_life_days": 1.0 if p in sel else 40.0,
              "fdr": p in pairs_fdr, "selected": p in sel} for p in sorted(tested)]
    return {"date": date, "candidates": len(tested), "tested": len(pairs),
            "raw_pass": len(pairs_fdr), "fdr_pass": len(pairs_fdr),
            "selected": len(sel), "pairs": pairs}


def grid(sets, start="2023-01-01", candidates=None):
    """Окна, расставленные ровно по шагу сетки."""
    from datetime import date, timedelta
    t = date.fromisoformat(start)
    out = []
    for i, s in enumerate(sets):
        c = candidates[i] if candidates is not None else None
        out.append(window(t.isoformat(), s, candidates=c))
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


class ConditionalSurvival(unittest.TestCase):
    """Пара, выпавшая из кандидатов, — не распавшаяся связь.

    Знаменатель — только те отобранные пары, которые во втором окне
    вообще проверялись. Иначе ужесточение фильтров A3 (ликвидность,
    разброс оборота) выглядело бы как деградация отношений между
    активами.
    """

    def test_dropped_candidate_does_not_count_as_broken(self):
        s = W.survival({"A/B", "C/D"}, {"A/B"}, tested_b={"A/B"})
        # C/D во втором окне не проверялась — из знаменателя вон.
        self.assertEqual(s, (1.0, 1))

    def test_tested_and_failed_counts_as_broken(self):
        s = W.survival({"A/B", "C/D"}, {"A/B"}, tested_b={"A/B", "C/D"})
        self.assertEqual(s, (0.5, 2))

    def test_nothing_carried_over_is_not_zero(self):
        import math
        v, n = W.survival({"A/B"}, {"X/Y"}, tested_b={"X/Y"})
        self.assertTrue(math.isnan(v))
        self.assertEqual(n, 0)

    def test_summary_separates_survival_from_candidate_churn(self):
        # Окно 1 отбирает A/B и C/D; в окне 2 C/D вообще не кандидат,
        # A/B проверена и не прошла.
        rows = [window("2023-01-01", {"A/B", "C/D"}),
                window("2023-01-31", set(), candidates={"A/B", "E/F"})]
        s = W.summarize(rows)
        self.assertAlmostEqual(s["adjacent"]["survival"], 0.0)
        self.assertEqual(s["adjacent"]["survival_denominator_total"], 1)
        # Из двух отобранных кандидатом осталась одна.
        self.assertAlmostEqual(s["adjacent"]["selected_still_candidate"], 0.5)
        # Безусловная доля не отличила бы этих двух причин.
        self.assertAlmostEqual(s["adjacent"]["survival_unconditional"], 0.0)

    def test_candidate_carryover_measured_on_full_list(self):
        rows = [window("2023-01-01", set(), candidates={"A/B", "C/D"}),
                window("2023-01-31", set(), candidates={"A/B", "E/F", "G/H"})]
        s = W.summarize(rows)
        self.assertAlmostEqual(s["adjacent"]["candidate_carryover"], 0.5)

    def test_criterion_2_reads_conditional_not_unconditional(self):
        """Порог §8 сравнивается с условной долей.

        Набор из двух пар, где одна выпала из кандидатов, а вторая
        подтвердилась: по существу удержалось всё, что можно было
        удержать, и безусловные 50 % занижают ответ.
        """
        rows = [window("2023-01-01", {"A/B", "C/D"}),
                window("2023-01-31", {"A/B"}, candidates={"A/B", "E/F"})]
        s = W.summarize(rows)
        self.assertAlmostEqual(s["adjacent"]["survival"], 1.0)
        self.assertAlmostEqual(s["adjacent"]["survival_unconditional"], 0.5)
        self.assertTrue(s["criterion_2_survival_ge_30pct"])


class Summary(unittest.TestCase):
    def test_survival_pairs_consecutive_windows(self):
        rows = grid([{"A/B", "C/D"}, {"A/B", "E/F"}, {"E/F", "G/H"}],
                    candidates=[None, {"A/B", "C/D", "E/F"},
                                {"A/B", "C/D", "E/F", "G/H"}])
        s = W.summarize(rows)
        # 1→2: A/B и C/D проверены обе, дожила одна. 2→3: то же.
        self.assertAlmostEqual(s["adjacent"]["survival"], 0.5)

    def test_three_step_survival_skips_overlapping_windows(self):
        every = {"A/B", "X/Y", "Z/W"}
        rows = grid([{"A/B"}, {"X/Y"}, {"X/Y"}, {"A/B"}, {"Z/W"}],
                    candidates=[every] * 5)
        s = W.summarize(rows)
        # 1→4: A/B дожила (1.0), 2→5: X/Y не дожила (0.0).
        self.assertAlmostEqual(s["three_steps"]["survival"], 0.5)

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
