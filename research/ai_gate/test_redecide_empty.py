#!/usr/bin/env python3
"""Дорешение отказов книг ТВХ (10.11): в работу идут только отказы (k = -1)
с пустым значением хотя бы одного поля правила; входы, «не измерено» и
отказы на измеренных полях не трогаются."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import redecide_empty as RD                                   # noqa: E402


def main():
    b = {"rule": {"when": [{"field": "since_signal"}, {"field": "buy_share"}]}}
    assert RD.suspicious(b, {"k": -1, "vals": {"since_signal": None, "buy_share": None}})
    assert RD.suspicious(b, {"k": -1, "vals": {"since_signal": 0.01, "buy_share": None}}), "хватает одного пустого поля"
    assert not RD.suspicious(b, {"k": -1, "vals": {"since_signal": 0.01, "buy_share": 0.6}}), "измеренный отказ — решение"
    assert not RD.suspicious(b, {"k": 2, "vals": {"since_signal": None, "buy_share": 0.4}}), "вход не трогается"
    assert not RD.suspicious(b, {"k": -2, "vals": {"since_signal": None}}), "«не измерено» не трогается"
    assert not RD.suspicious(b, {"k": -1}), "решение без записанных значений (до 21.10) — не трогается"
    print("ok  дорешение: только отказы на пустых полях правила")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
