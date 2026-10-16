#!/usr/bin/env python3
"""Лучшие сделки для главной сайта (`rules.best_trades`/`merge_best`).

Кусаются: берутся только нынешние правила, сложный процент, закрытые и
книги из списка; одна позиция (имя, сторона, момент решения) — одна
строка, лучшая копия; знаменатель — все сделки, убыточные — числом;
сведение семейств суммирует объём и не дублирует позицию; первые N по
долларам нетто; бэктест и запись вперёд помечены.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402

H = 3600.0
T = float(R.RULES_SINCE) + 5 * 86400.0


def _row(ruler, sym, usd, at=T, dep=1000, side="short", fam="h24", **kw):
    r = {"ruler": ruler, "sym": sym, "usd": usd, "usd_gross": usd + 1.0, "at": at,
         "exit_ts": at + 5 * H, "dep": dep, "side": side, "margin": 50.0, "lev": 3.0,
         "exit": "тейк", "written_at": at + 6 * H, "rules": R.RULES,
         "book_rules": R.FAMILY_RULES[fam]}
    r.update(kw)
    return r


def test_best_trades_one_position_once_with_denominator():
    rows = [_row("safe_h", "AUSDT", 10.0),
            _row("safe_h_g0", "AUSDT", 12.0),                  # та же позиция у сестры — лучшая копия
            _row("optimal_h", "BUSDT", 30.0, at=T + H),
            _row("aggr_h", "CUSDT", -8.0, at=T + 2 * H),
            _row("aggr_h", "DUSDT", 50.0, at=T + 3 * H, book_rules=1),        # прежние правила — мимо
            _row("aggr_h", "EUSDT", 60.0, at=T + 4 * H, sizing="fixed"),      # фиксированный билет — мимо
            _row("aggr_h", "FUSDT", 70.0, at=T + 5 * H, exit_ts=None),        # не закрыта — мимо
            _row("aggr_h", "GUSDT", 80.0, at=T + 6 * H, dep=10000),
            _row("other", "HUSDT", 90.0, at=T + 7 * H)]                       # не книга семейства
    assert R.is_current(rows[0]) and not R.is_current(rows[4]), "подделка версии легла"
    b = R.best_trades(rows, keys=R.order_of("h24"))
    assert set(b) == {"1000", "10000"}, b.keys()
    d = b["1000"]
    assert d["n"] == 4 and d["n_loss"] == 1, d                       # знаменатель — все сделки книг
    assert [(x["sym"], x["book"], x["usd"]) for x in d["top"]] == [
        ("BUSDT", "optimal_h", 30.0), ("AUSDT", "safe_h_g0", 12.0), ("CUSDT", "aggr_h", -8.0)], d["top"]
    x = d["top"][0]
    assert x["ret"] == round(30.0 / 50.0, 4) and x["usd_gross"] == 31.0 and x["bt"] is False and x["side"] == "short"
    late = R.best_trades([_row("safe_h", "AUSDT", 5.0, written_at=T + 30 * 86400)])["1000"]["top"][0]
    assert late["bt"] is True, "записанное после исхода — бэктест"
    print("ok  лучшие сделки семейства: нынешние правила, сложный процент, закрытые; позиция один раз "
          "лучшей копией; знаменатель и убыточные числом; бэктест помечен")


def test_merge_best_sums_denominator_and_keeps_position_once():
    a = {"1000": {"n": 10, "n_loss": 4, "top": [
        {"sym": "AUSDT", "side": "short", "at": T, "usd": 12.0, "book": "safe_h"},
        {"sym": "BUSDT", "side": "long", "at": T, "usd": 5.0, "book": "safe"}]}}
    p = {"1000": {"n": 7, "n_loss": 2, "top": [
        {"sym": "AUSDT", "side": "short", "at": T, "usd": 20.0, "book": "pair_safe"},
        {"sym": "CUSDT", "side": "short", "at": T, "usd": 1.0, "book": "pair_safe"}]},
         "100": {"n": 1, "n_loss": 0, "top": []}}
    m = R.merge_best([a, None, p], n=2)
    assert m["1000"]["n"] == 17 and m["1000"]["n_loss"] == 6
    assert [(x["sym"], x["book"]) for x in m["1000"]["top"]] == [("AUSDT", "pair_safe"), ("BUSDT", "safe")]
    assert m["100"] == {"n": 1, "n_loss": 0, "top": []}
    assert R.BEST_N == 100 and R.BEST_KEEP >= R.BEST_N
    print("ok  сведение семейств: объём и убыточные суммой, позиция один раз, первые N")


if __name__ == "__main__":
    test_best_trades_one_position_once_with_denominator()
    test_merge_best_sums_denominator_and_keeps_position_once()
    print("\nвсе 2 проверки прошли")
