#!/usr/bin/env python3
"""Проверки отбора кандидатов A3.

Главное, что здесь проверяется, — отбор смотрит только в прошлое.
Ошибка такого рода не падает и не видна в числах: она просто делает
результат лучше, чем он есть.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pairs as P  # noqa: E402


def series(days, turnover=1e7, bars=1440, traded=1440, start="2023-01-01"):
    """Ряд подневной ликвидности: `days` дней подряд от `start`."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), turnover, bars, traded)
            for i in range(days)]


def uni(**kw):
    out = {}
    for a, listed in kw.items():
        out[a] = {"asset_class": "crypto", "listed": listed,
                  "binance_symbol": a + "USDT"}
    return out


META = {"duplicates": set(), "mechanical": [], "low": set(), "unlabeled": set()}


class PointInTime(unittest.TestCase):
    def test_future_days_are_not_used(self):
        """День самой даты отбора и всё после неё в оценку не входят."""
        t = "2023-04-01"
        rows = series(120, turnover=1e7)
        base = P.state_at({"A": rows}, uni(A="2021-01-01"), t)
        spike = rows + series(5, turnover=1e12, start=t)
        after = P.state_at({"A": spike}, uni(A="2021-01-01"), t)
        self.assertEqual(base["A"]["turnover"], after["A"]["turnover"])
        self.assertEqual(base["A"]["days"], after["A"]["days"])

    def test_window_is_exactly_form_days(self):
        t = "2023-05-01"
        rows = series(365, start="2022-06-01")
        st = P.state_at({"A": rows}, uni(A="2020-01-01"), t)
        self.assertEqual(st["A"]["days"], P.FORM_DAYS)

    def test_history_requirement(self):
        from datetime import date, timedelta
        t = "2024-01-01"
        just_short = (date.fromisoformat(t)
                      - timedelta(days=P.MIN_HISTORY - 1)).isoformat()
        just_long = (date.fromisoformat(t)
                     - timedelta(days=P.MIN_HISTORY + 1)).isoformat()
        rows = series(120, start="2023-08-01")
        self.assertNotIn("A", P.state_at({"A": rows}, uni(A=just_short), t))
        self.assertIn("A", P.state_at({"A": rows}, uni(A=just_long), t))


class Liquidity(unittest.TestCase):
    def test_days_without_trades_excluded_from_turnover(self):
        """Замороженный день не наблюдение: в оборот он не входит."""
        t = "2023-06-01"
        live = series(60, turnover=1e7, start="2023-03-04")
        dead = series(30, turnover=0.0, traded=0, start="2023-05-03")
        st = P.state_at({"A": live + dead}, uni(A="2020-01-01"), t)
        self.assertEqual(st["A"]["turnover"], 1e7)

    def test_days_without_trades_stay_in_share_denominator(self):
        """...но в знаменателе свежести цены остаются."""
        t = "2023-06-01"
        live = series(45, start="2023-03-04")
        dead = series(45, traded=0, start="2023-04-18")
        st = P.state_at({"A": live + dead}, uni(A="2020-01-01"), t)
        self.assertLess(st["A"]["share_traded"], 0.6)

    def test_short_series_rejected(self):
        t = "2023-06-01"
        rows = series(P.MIN_DAYS_IN_WINDOW - 1, start="2023-05-01")
        self.assertNotIn("A", P.state_at({"A": rows}, uni(A="2020-01-01"), t))

    def test_illiquid_asset_makes_no_pairs(self):
        st = {"A": {"turnover": 1e7, "share_traded": 1.0, "days": 90},
              "B": {"turnover": 1e7, "share_traded": 0.5, "days": 90}}
        got, live = P.candidates({"g": ["A", "B"]},
                                 {"A": "g", "B": "g"}, META, st)
        self.assertEqual(got, [])
        self.assertNotIn("B", live)


class SizeRule(unittest.TestCase):
    def state(self, ta, tb):
        return {"A": {"turnover": ta, "share_traded": 1.0, "days": 90},
                "B": {"turnover": tb, "share_traded": 1.0, "days": 90}}

    def pairs(self, ta, tb, **kw):
        got, _ = P.candidates({"g": ["A", "B"]}, {"A": "g", "B": "g"},
                              META, self.state(ta, tb), **kw)
        return got

    def test_ratio_boundary(self):
        r = P.MAX_TURNOVER_RATIO
        self.assertEqual(len(self.pairs(1e7, 1e7 * r)), 1)
        self.assertEqual(len(self.pairs(1e7, 1e7 * r * 1.001)), 0)

    def test_ratio_is_symmetric(self):
        self.assertEqual(len(self.pairs(1e9, 1e7)), len(self.pairs(1e7, 1e9)))

    def test_threshold_is_a_parameter_not_a_constant(self):
        self.assertEqual(len(self.pairs(1e7, 1e9, max_ratio=1e9)), 1)


class Membership(unittest.TestCase):
    def st(self, *names):
        return {n: {"turnover": 1e7, "share_traded": 1.0, "days": 90}
                for n in names}

    def test_pairs_only_inside_a_group(self):
        got, _ = P.candidates({"g": ["A"], "h": ["B"]},
                              {"A": "g", "B": "h"}, META, self.st("A", "B"))
        self.assertEqual(got, [])

    def test_unlabeled_makes_no_pairs(self):
        """Актив без метки сектора не порождает кандидатов вовсе."""
        got, _ = P.candidates({"g": ["A", "B"]}, {"A": "g"}, META,
                              self.st("A", "B"))
        self.assertEqual(got, [])

    def test_duplicate_listing_excluded(self):
        meta = dict(META, duplicates={frozenset(("A", "B"))})
        got, _ = P.candidates({"g": ["A", "B"]}, {"A": "g", "B": "g"},
                              meta, self.st("A", "B"))
        self.assertEqual(got, [])

    def test_mechanical_pair_ignores_size(self):
        """Газовый токен всегда меньше своей сети — размер здесь не судья."""
        meta = dict(META, mechanical=[("A", "B")])
        st = {"A": {"turnover": 1e10, "share_traded": 1.0, "days": 90},
              "B": {"turnover": 1e6, "share_traded": 1.0, "days": 90}}
        got, _ = P.candidates({"g": ["A", "B"]}, {"A": "g", "B": "g"},
                              meta, st)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][2], "mechanically_linked")

    def test_mechanical_pair_not_duplicated(self):
        meta = dict(META, mechanical=[("A", "B")])
        got, _ = P.candidates({"g": ["A", "B"]}, {"A": "g", "B": "g"},
                              meta, self.st("A", "B"))
        self.assertEqual(len(got), 1)

    def test_illiquid_leg_kills_mechanical_pair_too(self):
        meta = dict(META, mechanical=[("A", "B")])
        st = {"A": {"turnover": 1e7, "share_traded": 1.0, "days": 90},
              "B": {"turnover": 1e7, "share_traded": 0.1, "days": 90}}
        got, _ = P.candidates({"g": ["A", "B"]}, {"A": "g", "B": "g"},
                              meta, st)
        self.assertEqual(got, [])


class RealGroups(unittest.TestCase):
    def test_groups_file_parses_and_is_disjoint(self):
        groups, of_group, meta = P.load_groups()
        total = sum(len(v) for v in groups.values())
        self.assertEqual(total, len(of_group))
        self.assertTrue(meta["duplicates"])
        self.assertTrue(meta["mechanical"])

    def test_unlabeled_are_not_in_groups(self):
        groups, of_group, meta = P.load_groups()
        self.assertEqual(meta["unlabeled"] & set(of_group), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
