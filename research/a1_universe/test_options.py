#!/usr/bin/env python3
"""Тесты инвентаря опционов площадки.

Три места, где ошибка была бы невидимой в отчёте: снятый контракт,
посчитанный живым (объявили бы хедж возможным там, где инструмента нет);
базовый актив без снятия множителя лота (`1000PEPE` не нашёл бы `PEPE`, и
покрытие вышло бы заниженным); отказ эндпоинта, поднятый исключением
вместо данных (второй способ обхода не сработал бы никогда — прогон просто
падал бы). Только stdlib.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bybit_options as B                                     # noqa: E402


def test_summarize_only_trading():
    rows = [
        {"baseCoin": "BTC", "status": "Trading", "deliveryTime": "1767139200000"},
        {"baseCoin": "BTC", "status": "Trading", "deliveryTime": "1769731200000"},
        {"baseCoin": "ETH", "status": "Closed", "deliveryTime": "1700000000000"},
    ]
    by = B.summarize(rows)
    assert set(by) == {"BTC"}, by
    assert by["BTC"]["contracts"] == 2, by
    assert by["BTC"]["first"] < by["BTC"]["last"], by
    print(f"ok  свод: снятый контракт не считается инструментом "
          f"(BTC {by['BTC']['contracts']}, ETH нет)")


def test_alias_set():
    assert B.alias_set("1000PEPE") == {"1000PEPE", "PEPE"}
    assert B.alias_set("BTC") == {"BTC"}
    assert "BABYDOGE" in B.alias_set("1000000BABYDOGE")
    assert B.alias_set("1000") == {"1000"}          # не срезать всё имя
    print("ok  алиасы базового актива: множитель лота снимается, "
          "имя целиком не съедается")


def test_api_get_refusal_is_data():
    orig = B._fetch
    try:
        B._fetch = lambda *a, **k: '{"retCode":10001,"retMsg":"baseCoin"}'
        ok, res, msg = B.api_get("/x", {"a": 1})
        assert ok is False and "10001" in msg, (ok, msg)

        def boom(*a, **k):
            raise RuntimeError("нет сети")
        B._fetch = boom
        ok2, _r2, msg2 = B.api_get("/x", {"a": 1})
        assert ok2 is False and "сеть" in msg2, msg2
    finally:
        B._fetch = orig
    print("ok  отказ эндпоинта и сети — данные, а не исключение")


def test_run_falls_back_to_probe():
    """Общий список не отдан → поимённый опрос, и метод назван в артефакте."""
    orig = B.list_options
    calls = []

    def stub(base_coin=None, pages=20):
        calls.append(base_coin)
        if base_coin is None:
            return False, [], "retCode=10001 baseCoin is required"
        if base_coin == "BTC":
            return True, [{"baseCoin": "BTC", "status": "Trading",
                           "deliveryTime": "1767139200000"}], ""
        return True, [], ""
    B.list_options = stub
    try:
        s = B.run(smoke=True, log=lambda *a: None)
    finally:
        B.list_options = orig
    assert s["method"] == "probe", s["method"]
    assert calls[0] is None and len(calls) > 1, calls
    assert s["base_coins"] == ["BTC"], s["base_coins"]
    assert s["universe_crypto"] > 0, s["universe_crypto"]
    print(f"ok  запасной обход: опрошено {s['probed']}, найден "
          f"{s['base_coins']}, крипто-универсум {s['universe_crypto']}")


def test_report_names_absence():
    s = {"asof": "x", "method": "probe", "probed": 5, "rows": 0, "secs": 1.0,
         "base_coins": [], "by_coin": {}, "universe_crypto": 600,
         "universe_covered": [], "probe_errors": []}
    r = B.report(s)
    assert "не найдено" in r, r[:400]
    assert "пут под нашу книгу купить не на что" in r, r[-600:]
    s2 = dict(s, base_coins=["BTC"], by_coin={"BTC": {"contracts": 2,
                                                      "first": "2026-01-01",
                                                      "last": "2026-06-01"}},
              universe_covered=["BTCUSDT"])
    r2 = B.report(s2)
    assert "| BTC | 2 |" in r2, r2
    assert "0.2 %" in r2, r2            # 1 из 600
    print("ok  отчёт различает «не нашли» и «нечего покрывать»")


# ------------------------------------------------------ отрицательные контроли

def _control_count_closed():
    """Считая снятые контракты, мы объявили бы хедж возможным там, где
    инструмента нет — проверка свода обязана упасть."""
    orig = B.summarize

    def loose(rows):
        by = {}
        for r in rows:
            b = str(r.get("baseCoin") or "").upper()
            d = by.setdefault(b, {"contracts": 0, "first": None, "last": None})
            d["contracts"] += 1
        return by
    B.summarize = loose
    try:
        try:
            test_summarize_only_trading()
        except AssertionError:
            return True
        return False
    finally:
        B.summarize = orig


def _control_alias_no_strip():
    """Без снятия множителя лота покрытие вышло бы заниженным."""
    orig = B.alias_set
    B.alias_set = lambda b: {str(b).upper()}
    try:
        try:
            test_alias_set()
        except AssertionError:
            return True
        return False
    finally:
        B.alias_set = orig


def _control_api_raises():
    """Отказ, поднятый исключением, не даёт перейти ко второму обходу."""
    orig = B.api_get

    def raiser(path, params, day=None):
        raise RuntimeError("retCode=10001")
    B.api_get = raiser
    try:
        try:
            test_api_get_refusal_is_data()
        except (AssertionError, RuntimeError):
            return True
        return False
    finally:
        B.api_get = orig


TESTS = [test_summarize_only_trading, test_alias_set,
         test_api_get_refusal_is_data, test_run_falls_back_to_probe,
         test_report_names_absence]

CONTROLS = [("снятые контракты считаются живыми", _control_count_closed),
            ("алиас без снятия множителя", _control_alias_no_strip),
            ("отказ эндпоинта исключением", _control_api_raises)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
