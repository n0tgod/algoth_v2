#!/usr/bin/env python3
"""Тесты ядра F1 на известных ответах.

Проверяется главным образом знак и то, что разложение складывается в
сумму. Ошибка знака у funding не падает и не выглядит странно — она
просто превращает расход в доход, то есть даёт ровно тот вердикт, ради
которого этап существует.

Запуск: python3 -m unittest discover -s research/f1_carry
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry as CY  # noqa: E402

BP = 0.0001


class TestWeights(unittest.TestCase):

    def test_gross_is_one_and_legs_equal(self):
        s = np.arange(20.0)
        w, k = CY.weights(s, 0.10)
        self.assertEqual(k, 2)
        self.assertAlmostEqual(float(np.abs(w).sum()), 1.0, places=12)
        self.assertAlmostEqual(float(w[w > 0].sum()), 0.5, places=12)
        self.assertAlmostEqual(float(w[w < 0].sum()), -0.5, places=12)

    def test_top_score_goes_long(self):
        """Соглашение проекта: положительная оценка = «покупаем».

        Оценка есть МИНУС ставка, значит в лонг попадает актив с самой
        отрицательной ставкой — тот, кому платят шорты. Перепутанный
        знак здесь развернул бы книгу целиком.
        """
        s = np.array([-5.0, 0.0, 3.0, 9.0])
        w, _ = CY.weights(s, 0.25)
        self.assertGreater(w[3], 0)
        self.assertLess(w[0], 0)

    def test_nan_score_gets_no_weight(self):
        s = np.array([1.0, np.nan, 3.0, 4.0, np.nan, 6.0])
        w, k = CY.weights(s, 0.25)
        self.assertEqual(k, 1)
        self.assertEqual(float(w[1]), 0.0)
        self.assertEqual(float(w[4]), 0.0)

    def test_too_thin_section_gives_no_book(self):
        w, k = CY.weights(np.arange(5.0), 0.10)
        self.assertEqual(k, 0)
        self.assertEqual(float(np.abs(w).sum()), 0.0)


class TestDecompose(unittest.TestCase):

    def test_long_pays_positive_rate(self):
        """Положительная ставка: лонг ПЛАТИТ, шорт получает."""
        w = np.array([0.5, -0.5])
        price = np.array([0.0, 0.0])
        fund = np.array([0.01, 0.0])          # первый актив: лонги платят 1 %
        d = CY.decompose(w, price, fund)
        self.assertAlmostEqual(d["long"]["funding"], -0.005, places=12)
        self.assertAlmostEqual(d["short"]["funding"], 0.0, places=12)

    def test_short_earns_positive_rate(self):
        w = np.array([0.5, -0.5])
        price = np.array([0.0, 0.0])
        fund = np.array([0.0, 0.01])          # второй актив в шорте
        d = CY.decompose(w, price, fund)
        self.assertAlmostEqual(d["short"]["funding"], +0.005, places=12)

    def test_parts_sum_to_gross(self):
        rng = np.random.default_rng(3)
        s = rng.normal(size=40)
        w, _ = CY.weights(s, 0.20)
        price = rng.normal(0, 0.05, 40)
        fund = rng.normal(0, 0.002, 40)
        d = CY.decompose(w, price, fund)
        self.assertAlmostEqual(d["gross"], d["price"] + d["funding"],
                               places=12)
        self.assertAlmostEqual(d["gross"],
                               d["long"]["gross"] + d["short"]["gross"],
                               places=12)

    def test_missing_observation_is_dropped_not_zeroed(self):
        """Ноль означал бы «цена не двигалась» — наблюдение, которого не
        было. Вес такого актива обязан попасть в `dropped_weight`."""
        w = np.array([0.5, -0.5])
        price = np.array([0.10, np.nan])
        fund = np.array([0.0, 0.0])
        d = CY.decompose(w, price, fund)
        self.assertAlmostEqual(d["dropped_weight"], 0.5, places=12)
        # 0.5 · (e^0.10 − 1), а не 0.5 · 0.10: логарифмическое
        # приращение переводится в доходность позиции.
        self.assertAlmostEqual(d["price"], 0.5 * (np.expm1(0.10)), places=12)
        self.assertEqual(d["short"]["names"], 0)


class TestPositionReturn(unittest.TestCase):
    """Перевод накопленного логарифма в доходность позиции.

    Дефект, найденный после закрытия гипотезы: PnL считался суммой
    логарифмических приращений. На медиане разница в сотых долях, на
    хвосте — решающая, а гипотеза умерла именно на хвосте.
    """

    def test_long_cannot_lose_more_than_everything(self):
        for log_ret in (-1.0, -2.56, -10.0):
            r = float(CY.position_return(np.array([1.0]), np.array([log_ret]))[0])
            self.assertGreater(r, -1.0)
            self.assertLess(r, -0.6)

    def test_short_loss_is_unbounded(self):
        """У шорта убыток сверху не ограничен ничем: актив, выросший в
        13 раз, стоит позиции 1194 %, а не 256 %."""
        r = float(CY.position_return(np.array([-1.0]), np.array([2.56]))[0])
        self.assertLess(r, -11.0)
        self.assertAlmostEqual(r, -(np.expm1(2.56)), places=9)

    def test_small_moves_are_almost_unchanged(self):
        """На величинах, которыми живёт медиана книги, поправка
        пренебрежима — поэтому дефект и не был виден в средних."""
        r = float(CY.position_return(np.array([1.0]), np.array([0.0027]))[0])
        self.assertAlmostEqual(r, 0.0027, places=5)

    def test_short_side_sign(self):
        """Актив упал — шорт заработал."""
        r = float(CY.position_return(np.array([-1.0]), np.array([-0.20]))[0])
        self.assertGreater(r, 0)
        self.assertAlmostEqual(r, -np.expm1(-0.20), places=12)

    def test_book_tail_is_worse_than_the_log_approximation(self):
        """Проверка направления ошибки на книге из двух ног.

        Длинная нога потеряла (лог −1.0), короткая взорвалась (лог
        +1.0). Сумма логарифмов дала бы ноль — ноги «погасили» бы друг
        друга. На деле книга в глубоком минусе: шорт теряет больше, чем
        лонг может потерять в принципе.
        """
        w = np.array([0.5, -0.5])
        price = np.array([-1.0, 1.0])
        fund = np.array([0.0, 0.0])
        d = CY.decompose(w, price, fund)
        self.assertLess(d["price"], -0.4)

    def test_the_case_the_spec_predicts(self):
        """§5.1: нам платят за покупку падающего.

        Длинная нога получает 25 б.п. в сутки начислений и теряет 200 на
        цене. Книга обязана показать это отрицательным брутто длинной
        ноги, а не спрятать в агрегате.
        """
        w = np.array([0.5, -0.5])
        price = np.array([-0.02, 0.0])
        fund = np.array([-0.00125 * 5, 0.0])   # ставка отрицательная: платят шорты
        d = CY.decompose(w, price, fund)
        self.assertLess(d["long"]["price"], 0)
        self.assertGreater(d["long"]["funding"], 0)
        self.assertLess(d["long"]["gross"], 0)


class TestTailRatio(unittest.TestCase):

    def test_known_value(self):
        v = [0.01] * 19 + [-0.10]
        self.assertAlmostEqual(CY.tail_ratio(v), 10.0, places=9)

    def test_denominator_is_median_of_absolute(self):
        """У книги с медианой около нуля модуль медианы взорвал бы
        отношение в бесконечность, сообщив о хвосте то, чего в нём нет."""
        v = [0.01, -0.01] * 10 + [-0.10]
        r = CY.tail_ratio(v)
        self.assertAlmostEqual(r, 10.0, places=9)

    def test_short_series_gives_nothing(self):
        self.assertIsNone(CY.tail_ratio([0.01] * 9))



class TestFundingLoader(unittest.TestCase):
    """Разбор рядов. Колонки ищутся по имени, а не по номеру."""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        from research.common import funding_series as FS
        self.FS = FS

    def test_two_column_bybit_layout(self):
        i, j = self.FS.column_indices(["funding_time", "funding_rate"])
        self.assertEqual((i, j), (0, 1))

    def test_three_column_binance_layout(self):
        """Ровно тот случай, который смоук-прогон поймал разложением по
        ногам: `row[1]` у архива Binance есть число часов интервала, а
        не ставка. Позиция ставки — вторая, а не первая."""
        i, j = self.FS.column_indices(
            ["funding_time", "interval_hours", "funding_rate"])
        self.assertEqual((i, j), (0, 2))

    def test_unknown_header_raises(self):
        with self.assertRaises(ValueError):
            self.FS.column_indices(["time", "rate"])

    def test_empty_file_raises(self):
        with self.assertRaises(ValueError):
            self.FS.column_indices(None)


if __name__ == "__main__":
    unittest.main()
