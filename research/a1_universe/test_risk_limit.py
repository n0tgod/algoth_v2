#!/usr/bin/env python3
"""Тесты разбора тиров D0 — без обращения к площадке.

Пагинация и сеть проверяются смоуком на VPS (`--symbol BTCUSDT`); здесь
проверяется только разбор ответа, потому что из песочницы API закрыт, а
разбор — единственное место, где легко ошибиться молча.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bybit_risk_limit as RL  # noqa: E402


# Ответ намеренно НЕ отсортирован по нотионалу: площадка порядок не
# гарантирует, а D1 ищет тир по размеру позиции слева направо и обязан
# получить лестницу по возрастанию нотионала.
FIXTURE = {"list": [
    {"id": 2, "symbol": "X", "riskLimitValue": "500000",
     "maintenanceMargin": "0.01", "initialMargin": "0.02", "maxLeverage": "25"},
    {"id": 1, "symbol": "X", "riskLimitValue": "100000",
     "maintenanceMargin": "0.005", "initialMargin": "0.01",
     "maxLeverage": "50", "isLowestRisk": 1},
    {"id": 3, "symbol": "X", "riskLimitValue": "1000000",
     "maintenanceMargin": "0.025", "initialMargin": "0.05", "maxLeverage": "10"},
]}


def test_tiers_parsed_and_sorted_by_notional():
    tiers = RL.parse_tiers(FIXTURE)
    assert len(tiers) == 3, len(tiers)
    caps = [t["cap"] for t in tiers]
    assert caps == sorted(caps), f"тиры не по возрастанию нотионала: {caps}"
    base = tiers[0]
    assert base["cap"] == 100000.0 and base["mmr"] == 0.005, base
    # ставка растёт с нотионалом — базовый тир самый дешёвый
    assert tiers[0]["mmr"] < tiers[-1]["mmr"], "MMR не растёт с тиром"
    # числа стали float, а не строки — иначе D1 считал бы MMR как текст
    assert all(isinstance(t["mmr"], float) for t in tiers)
    assert all(isinstance(t["max_leverage"], float) for t in tiers)
    print("ok  тиры разобраны и отсортированы по нотионалу")


def test_empty_list_is_empty_not_none():
    # Снятый контракт: `list` пуст. Это законный ответ «тиров нет», и он
    # обязан отличаться от «не собрано» (символа нет в хранилище вовсе).
    tiers = RL.parse_tiers({"list": []})
    assert tiers == [], tiers
    tiers = RL.parse_tiers({})            # и без ключа list
    assert tiers == [], tiers
    print("ok  пустой ответ — [] , а не None")


def test_report_counts_three_states_by_number():
    # Покрытие: с тирами / пустой ответ / не собрано — три РАЗНЫХ состояния,
    # и отчёт обязан считать их числом, а не смешивать.
    syms = ["A", "B", "C"]
    store = {"A": RL.parse_tiers(FIXTURE), "B": []}   # C не собрано вовсе
    rep = RL.report(store, syms)
    assert "С тирами: 1" in rep, rep
    assert "пустой ответ (снят с торгов?): 1" in rep, rep
    assert "не собрано: 1" in rep, rep
    print("ok  отчёт считает три состояния покрытия числом")


# --- отрицательные контроли: должны КУСАТЬСЯ ------------------------------

def _control_sort_removed():
    """Если убрать сортировку по нотионалу, тест порядка обязан упасть."""
    orig = RL.parse_tiers

    def unsorted(result):
        rows = result.get("list") or []
        return [{"id": int(r["id"]), "cap": float(r["riskLimitValue"]),
                 "mmr": float(r["maintenanceMargin"]),
                 "imr": float(r.get("initialMargin", 0)),
                 "max_leverage": float(r["maxLeverage"])} for r in rows]
    RL.parse_tiers = unsorted
    try:
        try:
            test_tiers_parsed_and_sorted_by_notional()
        except AssertionError:
            return True          # укусил — хорошо
        return False
    finally:
        RL.parse_tiers = orig


def _control_empty_becomes_none():
    """Если пустой ответ вернуть как None, различие «нет тиров» / «не
    собрано» исчезнет, и тест обязан упасть."""
    orig = RL.parse_tiers

    def as_none(result):
        rows = result.get("list") or []
        return orig(result) if rows else None
    RL.parse_tiers = as_none
    try:
        try:
            test_empty_list_is_empty_not_none()
        except (AssertionError, TypeError):
            return True
        return False
    finally:
        RL.parse_tiers = orig


TESTS = [
    test_tiers_parsed_and_sorted_by_notional,
    test_empty_list_is_empty_not_none,
    test_report_counts_three_states_by_number,
]


def main():
    for t in TESTS:
        t()
    assert _control_sort_removed(), "контроль сортировки не кусается"
    assert _control_empty_becomes_none(), "контроль пустого ответа не кусается"
    print(f"\nвсе {len(TESTS)} проверки прошли; 2 отрицательных контроля "
          f"кусаются")


if __name__ == "__main__":
    main()
