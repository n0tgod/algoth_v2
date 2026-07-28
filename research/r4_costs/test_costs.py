#!/usr/bin/env python3
"""Тесты ядра R4 на известных ответах.

Здесь проверяется главным образом арифметика единиц. Ошибка в множителе
или в определении оборота не падает и не выглядит подозрительно — она
просто даёт другой вердикт.

Запуск: python3 -m unittest discover -s research/r4_costs
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import costs as C  # noqa: E402

# Базисный пункт равен 0.0001. Тейкер 5.5 б.п. — это 0.00055, а не
# 0.000055: первая редакция этих тестов ошиблась на порядок ровно здесь,
# и поймали её сами тесты. Ставки в fees.json лежат в этих же долях
# (2.75 б.п. записаны как 0.000275).
BP = 0.0001
CHEAP, MODAL, EXPENSIVE = 2.75 * BP, 5.5 * BP, 11.0 * BP


class Weights(unittest.TestCase):
    def test_gross_is_one_and_book_is_neutral(self):
        score = np.arange(100.0)
        w, k = C.weights(score, np.zeros(100), 0.10)
        self.assertEqual(k, 10)
        self.assertAlmostEqual(np.abs(w).sum(), 1.0, places=12)
        self.assertAlmostEqual(w.sum(), 0.0, places=12)   # нейтральность

    def test_long_is_top_of_score(self):
        score = np.array([1.0, 5.0, 3.0, 9.0, 7.0, 2.0, 8.0, 4.0, 6.0, 0.0])
        w, _ = C.weights(score, np.zeros(10), 0.20)
        self.assertGreater(w[3], 0)      # 9.0 — максимум
        self.assertGreater(w[6], 0)      # 8.0
        self.assertLess(w[9], 0)         # 0.0 — минимум
        self.assertLess(w[0], 0)         # 1.0

    def test_assets_without_forward_get_no_weight(self):
        score = np.arange(10.0)
        fwd = np.array([np.nan] * 5 + [0.0] * 5)
        w, k = C.weights(score, fwd, 0.20)
        self.assertEqual(k, 1)
        self.assertTrue((w[:5] == 0).all())


class Turnover(unittest.TestCase):
    def test_unchanged_book_trades_nothing(self):
        n = ["A", "B", "C", "D"]
        w = np.array([0.5, -0.5, 0.0, 0.0])
        _, _, tot = C.turnover(n, w, n, w)
        self.assertAlmostEqual(tot, 0.0, places=12)

    def test_full_replacement_trades_two(self):
        """Полная замена книги — оборот 2, а не 1: старое закрывается,
        новое открывается."""
        _, _, tot = C.turnover(["A", "B"], np.array([0.5, -0.5]),
                               ["C", "D"], np.array([0.5, -0.5]))
        self.assertAlmostEqual(tot, 2.0, places=12)

    def test_flip_trades_double(self):
        """Имя, перевернувшееся из лонга в шорт, торгуется двойным
        объёмом — именно поэтому оборот считается по разности весов."""
        _, _, tot = C.turnover(["A"], np.array([0.5]), ["A"], np.array([-0.5]))
        self.assertAlmostEqual(tot, 1.0, places=12)

    def test_persisting_leg_is_free(self):
        """Смысл замера: допущение «шестьдесят ног каждый ребаланс»
        завышало бы издержки тем сильнее, чем длиннее окно сигнала."""
        n = ["A", "B", "C", "D"]
        prev = np.array([0.25, 0.25, -0.25, -0.25])
        now = np.array([0.25, 0.25, -0.25, -0.25])
        _, d, tot = C.turnover(n, prev, n, now)
        self.assertAlmostEqual(tot, 0.0)
        self.assertTrue((d == 0).all())


class Commission(unittest.TestCase):
    def test_full_replacement_at_modal_rate(self):
        """Полная замена при тейкере 5.5 б.п. стоит 11 б.п. гросса."""
        names, d, tot = C.turnover(["A", "B"], np.array([0.5, -0.5]),
                                   ["C", "D"], np.array([0.5, -0.5]))
        c = C.commission(names, d, lambda s: 0.00055)
        self.assertAlmostEqual(tot, 2.0)
        self.assertAlmostEqual(c * 10000, 11.0, places=9)

    def test_per_symbol_rate_is_used(self):
        """Разброс ставок вчетверо — средняя по универсуму запрещена."""
        rates = {"A": 0.000275, "B": 0.0011}      # 2.75 и 11.0 б.п.
        names, d, _ = C.turnover([], np.array([]), ["A", "B"],
                                 np.array([0.5, -0.5]))
        c = C.commission(names, d, rates.__getitem__)
        self.assertAlmostEqual(c, 0.5 * 0.000275 + 0.5 * 0.0011, places=15)


class Funding(unittest.TestCase):
    def test_long_pays_short_receives(self):
        """Положительная ставка: лонг платит, шорт получает."""
        f = C.funding_cost(["A", "B"], np.array([0.5, -0.5]),
                           lambda s: 0.001)
        self.assertAlmostEqual(f, 0.0, places=15)   # ноги гасят друг друга

    def test_book_funding_is_the_differential(self):
        """У книги, равной по деньгам, funding есть ДИФФЕРЕНЦИАЛ ног, а
        не сумма. Знак заранее неизвестен и подлежит замеру."""
        acc = {"A": 0.002, "B": 0.001}
        f = C.funding_cost(["A", "B"], np.array([0.5, -0.5]),
                           acc.__getitem__)
        self.assertAlmostEqual(f, 0.5 * (0.002 - 0.001), places=15)

    def test_missing_series_is_skipped_not_zeroed(self):
        f = C.funding_cost(["A", "B"], np.array([0.5, -0.5]),
                           lambda s: 0.001 if s == "A" else None)
        self.assertAlmostEqual(f, 0.0005, places=15)


class DelistedRate(unittest.TestCase):
    TABLE = [0.432, 0.326, 0.137, 0.147, 0.052]

    def test_thin_asset_gets_expensive_rate(self):
        t = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        r = C.quintile_expected_rate(t, self.TABLE, 0.00055, 0.0011,
                                     0.0011)
        self.assertGreater(r[0], r[-1])          # тонкий дороже ликвидного

    # Доли безставочных активов по квинтилям оборота, замер A1.
    SHARES = [0.250, 0.164, 0.191, 0.230, 0.164]

    def test_uniform_population_gives_670(self):
        """При равномерном распределении по квинтилям — 6.70 б.п."""
        t = list(range(1, 1001))
        r = C.quintile_expected_rate(t, self.TABLE, 0.00055, 0.0011, 0.0011)
        self.assertAlmostEqual(float(np.mean(r)) * 10000, 6.70, places=2)

    def test_measured_population_gives_676(self):
        """Число 6.76 б.п. из раздела 6 спеки — это средневзвешенное по
        ФАКТИЧЕСКОМУ распределению безставочных активов по квинтилям, а
        не по равномерному. Разница мелкая (6.70 против 6.76), но тест,
        проверяющий не ту популяцию, закрепил бы неверный вывод числа.
        """
        t = list(range(1, 1001))
        r = C.quintile_expected_rate(t, self.TABLE, 0.00055, 0.0011, 0.0011)
        per_q = [float(np.mean(r[i * 200:(i + 1) * 200])) for i in range(5)]
        weighted = sum(s * q for s, q in zip(self.SHARES, per_q))
        self.assertAlmostEqual(weighted * 10000, 6.76, places=2)

    def test_flat_expensive_would_overcharge(self):
        """Замер, опровергнувший черновик: плоские 11.0 б.п. завышают
        издержку почти вдвое против правила."""
        t = list(range(1, 1001))
        r = C.quintile_expected_rate(t, self.TABLE, 0.00055, 0.0011,
                                     0.0011)
        self.assertGreater(0.0011 / float(np.mean(r)), 1.6)

    def test_no_turnover_gets_fallback(self):
        r = C.quintile_expected_rate([None, 5.0, 7.0], self.TABLE,
                                     0.00055, 0.0011, 0.0011)
        self.assertAlmostEqual(r[0], 0.0011)


class NetSpread(unittest.TestCase):
    def test_half_factor(self):
        """Спред дециля — величина «на ногу», книга держит две ноги."""
        self.assertAlmostEqual(C.net_spread(0.0100, 0.0), 0.0050, places=12)

    def test_costs_subtract_directly(self):
        self.assertAlmostEqual(C.net_spread(0.0100, 0.0011), 0.0039, places=12)

    def test_known_case_end_to_end(self):
        """Сквозной пример в числах, которые можно проверить руками.

        Спред дециля 100 б.п. за период, книга обновляется целиком,
        тейкер 5.5 б.п. Доход книги 50 б.п., комиссия 11 б.п., нетто 39.
        """
        names, d, tot = C.turnover(["A", "B"], np.array([0.5, -0.5]),
                                   ["C", "D"], np.array([0.5, -0.5]))
        c = C.commission(names, d, lambda s: 0.00055)
        self.assertAlmostEqual(C.net_spread(0.0100, c) * 10000, 39.0,
                               places=6)


if __name__ == "__main__":
    unittest.main()


class ParseTime(unittest.TestCase):
    """Формат метки времени угадывался дважды и дважды неверно.

    Первый раз файлы сочли json-ом, второй — время миллисекундами, тогда
    как сборщик A1 пишет ISO. Оба вида теперь разбираются, а незнакомый
    обязан падать: молчаливый пропуск уже выдавал пустой результат за
    посчитанный ноль.
    """

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "r4run", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "run.py"))
        self.run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.run)

    def test_iso_with_timezone(self):
        got = self.run.parse_time_ms("2025-09-18T04:00:00+00:00")
        self.assertEqual(got, 1758168000000)

    def test_milliseconds_as_string(self):
        self.assertEqual(self.run.parse_time_ms("1758168000000"),
                         1758168000000)

    def test_both_forms_agree(self):
        a = self.run.parse_time_ms("2024-11-25T08:00:00+00:00")
        b = self.run.parse_time_ms(str(a))
        self.assertEqual(a, b)

    def test_unknown_form_raises(self):
        with self.assertRaises(ValueError):
            self.run.parse_time_ms("позавчера")
