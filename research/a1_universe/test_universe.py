#!/usr/bin/env python3
"""
Тесты интервальной логики универсума.

Проверяется именно то, что определяет, какие инструменты попадут в отбор
и в каком окне. Ошибка здесь не падает, а тихо смещает результат: универсум
получится чуть другим, воронка отбора — чуть другой, и заметить это по
итоговым числам невозможно. В v1 такие ошибки жили годами.

    python3 test_universe.py
"""

import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from common.venue import normalize  # noqa: E402
from universe import (  # noqa: E402
    KEEP_AS_CRYPTO,
    NON_CRYPTO_TAKER_BP,
    binance_history_days_by,
    classify_asset_class,
    estimation_history_days_by,
    history_days_by,
    split_settlement,
    to_intervals,
    tradable_on,
    universe_at,
)

D = date.fromisoformat


class ToIntervals(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(to_intervals([]), [])

    def test_single_day(self):
        self.assertEqual(to_intervals([D("2024-01-05")]),
                         [(D("2024-01-05"), D("2024-01-05"))])

    def test_contiguous_run_collapses(self):
        days = [D("2024-01-01"), D("2024-01-02"), D("2024-01-03")]
        self.assertEqual(to_intervals(days), [(D("2024-01-01"), D("2024-01-03"))])

    def test_gap_splits(self):
        days = [D("2024-01-01"), D("2024-01-02"), D("2024-01-05"), D("2024-01-06")]
        self.assertEqual(
            to_intervals(days),
            [(D("2024-01-01"), D("2024-01-02")), (D("2024-01-05"), D("2024-01-06"))],
        )

    def test_one_day_gap_is_a_gap(self):
        # Крипта торгуется без выходных, поэтому пропущенный день —
        # настоящий перерыв, а не календарь. Случай SAND.
        days = [D("2024-11-03"), D("2024-11-05")]
        self.assertEqual(len(to_intervals(days)), 2)


class SplitSettlement(unittest.TestCase):
    def test_no_settlement_when_single_interval(self):
        iv = [(D("2024-01-01"), D("2024-06-01"))]
        self.assertEqual(split_settlement(iv), (iv, []))

    def test_isolated_trailing_day_is_settlement(self):
        # Случай BTT: торговля кончилась 2021-12-28, последний файл архива —
        # 2022-12-12, почти год спустя. Это расчёт по делистингу, не торги.
        iv = [(D("2021-06-01"), D("2021-12-28")), (D("2022-12-12"), D("2022-12-12"))]
        trading, settlement = split_settlement(iv)
        self.assertEqual(trading, [(D("2021-06-01"), D("2021-12-28"))])
        self.assertEqual(settlement, [D("2022-12-12")])

    def test_real_resumption_is_kept(self):
        # Случай FHE: пауза 77 дней, затем 201 день настоящей торговли.
        iv = [(D("2025-04-16"), D("2025-10-21")), (D("2026-01-07"), D("2026-07-26"))]
        trading, settlement = split_settlement(iv)
        self.assertEqual(trading, iv)
        self.assertEqual(settlement, [])

    def test_short_gap_single_day_is_not_settlement(self):
        # Один день после разрыва в один день — сбой выкладки архива,
        # а не расчёт по делистингу: порог по разрыву не пройден.
        iv = [(D("2024-01-01"), D("2024-03-01")), (D("2024-03-03"), D("2024-03-03"))]
        trading, settlement = split_settlement(iv)
        self.assertEqual(settlement, [])
        self.assertEqual(trading, iv)


REC = {
    "base": "TEST",
    "bybit_symbol": "TESTUSDT",
    "listed": "2023-01-01",
    "last_trading_day": "2024-06-30",
    "settlement_days": [],
    "intervals": [["2023-01-01", "2023-06-30"], ["2023-08-01", "2024-06-30"]],
    "binance_symbol": "TESTUSDT",
    "binance_first_month": "2022-01",
    "delisted": True,
}


class PointInTime(unittest.TestCase):
    def test_tradable_inside_interval(self):
        self.assertTrue(tradable_on(REC, D("2023-03-01")))

    def test_not_tradable_in_gap(self):
        self.assertFalse(tradable_on(REC, D("2023-07-15")))

    def test_not_tradable_after_delisting(self):
        self.assertFalse(tradable_on(REC, D("2024-08-01")))

    def test_history_counts_only_traded_days(self):
        # К 2023-08-01 накоплен первый интервал (181 день) плюс один день.
        self.assertEqual(history_days_by(REC, D("2023-08-01")), 182)

    def test_history_excludes_the_gap(self):
        span = (D("2023-08-01") - D("2023-01-01")).days + 1
        self.assertLess(history_days_by(REC, D("2023-08-01")), span)

    def test_binance_history_is_longer_here(self):
        d = D("2023-03-01")
        self.assertGreater(binance_history_days_by(REC, d), history_days_by(REC, d))
        self.assertEqual(
            estimation_history_days_by(REC, d), binance_history_days_by(REC, d)
        )

    def test_estimation_takes_the_longer_series(self):
        # Обратный случай: Bybit листинговал раньше Binance.
        rec = dict(REC, binance_first_month="2024-01")
        d = D("2024-03-01")
        self.assertEqual(estimation_history_days_by(rec, d), history_days_by(rec, d))


class UniverseAt(unittest.TestCase):
    def setUp(self):
        self.m = {"assets": {"TEST": REC, "NOBNC": dict(REC, binance_symbol=None)}}

    def test_delisted_asset_is_included_in_past_window(self):
        # Суть требования 2.1.1: смерть инструмента сегодня не влияет
        # на то, что он торговался тогда.
        self.assertIn("TEST", universe_at(self.m, D("2023-03-01")))

    def test_asset_excluded_after_its_death(self):
        self.assertNotIn("TEST", universe_at(self.m, D("2025-01-01")))

    def test_excluded_during_suspension(self):
        self.assertNotIn("TEST", universe_at(self.m, D("2023-07-15")))

    def test_history_filter_applies(self):
        self.assertEqual(universe_at(self.m, D("2023-03-01"), min_history_days=10_000), [])

    def test_requires_binance_series_by_default(self):
        self.assertNotIn("NOBNC", universe_at(self.m, D("2023-03-01")))


class AssetClass(unittest.TestCase):
    """Разметка классов активов и исключение некрипты из универсума."""

    def _manifest(self):
        return {"assets": {
            "BTC": dict(REC, bybit_symbol="BTCUSDT"),
            "AAPL": dict(REC, bybit_symbol="AAPLUSDT"),
            "PURR": dict(REC, bybit_symbol="PURRUSDT"),
            "DEAD": dict(REC, bybit_symbol="DEADUSDT"),
        }}

    def _fees(self):
        # Делистнутого DEADUSDT в ответе нет: эндпоинт отвечает по текущему
        # состоянию счёта и закрытые контракты не возвращает.
        return [
            {"symbol": "BTCUSDT", "takerFeeRate": "0.00055"},
            {"symbol": "AAPLUSDT", "takerFeeRate": "0.000275"},
            {"symbol": "PURRUSDT", "takerFeeRate": "0.000275"},
        ]

    def test_cheap_tier_marks_non_crypto(self):
        m = self._manifest()
        n = classify_asset_class(m, self._fees())
        self.assertEqual(m["assets"]["AAPL"]["asset_class"], "non_crypto")
        self.assertEqual(m["assets"]["BTC"]["asset_class"], "crypto")
        self.assertEqual(n, 1)

    def test_exception_list_wins_over_tier(self):
        # PURR сидит на дешёвом тарифе, но это криптотокен: признак не
        # является определением, и исключения ведутся явным списком.
        self.assertIn("PURR", KEEP_AS_CRYPTO)
        m = self._manifest()
        classify_asset_class(m, self._fees())
        self.assertEqual(m["assets"]["PURR"]["asset_class"], "crypto")

    def test_missing_rate_stays_crypto(self):
        # Ставки нет только у делистнутых. Исключать их по умолчанию нельзя:
        # иначе из универсума молча выпадет ровно та часть, ради которой он
        # строится на момент времени.
        m = self._manifest()
        classify_asset_class(m, self._fees())
        self.assertEqual(m["assets"]["DEAD"]["asset_class"], "crypto")
        self.assertIsNone(m["assets"]["DEAD"]["taker_fee_bp"])

    def test_universe_excludes_non_crypto_by_default(self):
        m = self._manifest()
        classify_asset_class(m, self._fees())
        d = D("2023-03-01")
        self.assertNotIn("AAPL", universe_at(m, d))
        self.assertIn("AAPL", universe_at(m, d, include_non_crypto=True))

    def test_tier_threshold_is_exact(self):
        m = self._manifest()
        classify_asset_class(m, [
            {"symbol": "AAPLUSDT", "takerFeeRate": str(NON_CRYPTO_TAKER_BP / 1e4)},
            {"symbol": "BTCUSDT", "takerFeeRate": "0.0003"},
        ])
        self.assertEqual(m["assets"]["AAPL"]["asset_class"], "non_crypto")
        self.assertEqual(m["assets"]["BTC"]["asset_class"], "crypto")


class Normalize(unittest.TestCase):
    """Регрессии на две ошибки, найденные проверкой покрытия групп."""

    def test_prefix_multiplier(self):
        self.assertEqual(normalize("1000PEPEUSDT"), ("PEPE", "USDT", 1000))

    def test_suffix_multiplier(self):
        # Bybit торгует SHIB1000USDT, Binance — 1000SHIBUSDT.
        # Без обработки суффикса SHIB выпадал из пересечения.
        self.assertEqual(normalize("SHIB1000USDT"), ("SHIB", "USDT", 1000))
        self.assertEqual(normalize("1000SHIBUSDT"), ("SHIB", "USDT", 1000))

    def test_largest_multiplier_wins(self):
        # Порядок чередования от длинного к короткому: иначе в базовом
        # активе остались бы лишние нули.
        self.assertEqual(normalize("10000000AIDOGEUSDT"), ("AIDOGE", "USDT", 10_000_000))

    def test_plain_symbol(self):
        self.assertEqual(normalize("BTCUSDT"), ("BTC", "USDT", 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
