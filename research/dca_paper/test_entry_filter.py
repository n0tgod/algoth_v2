#!/usr/bin/env python3
"""Фильтр входа (`entry_filter.py`): порог — верхние q по первой половине;
неизмеренный признак решение не отсекает; случайное отсечение — ровно n;
критерий требует вторую половину у ВСЕХ книг, нуль ≤ 10 % и тот же знак на
первой. Подделка доказывается до проверки."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import entry_filter as EF                                     # noqa: E402


def test_threshold_filter_and_random_cut():
    vals = list(range(100))
    thr = EF.threshold(vals, 0.10)
    assert thr == 90, thr                                       # убираются > 90: 91..99 — 9 штук
    recs = [{"i": i} for i in range(100)] + [{"i": "x"}, {"i": "y"}]
    fts = [{"lev": float(i)} for i in range(100)] + [{"lev": None}, {}]
    keep, cut, unm = EF.apply_filter(recs, fts, "lev", thr)
    assert cut == 9 and unm == 2 and len(keep) == 93
    assert {"i": "x"} in keep and {"i": "y"} in keep, "неизмеренное не отсекается"
    assert EF.threshold([1.0] * 5, 0.1) is None, "мало значений — порога нет"
    keep2, cut2, _ = EF.apply_filter(recs, fts, "lev", None)
    assert cut2 == 0 and len(keep2) == len(recs)
    rc = EF.random_cut(recs, 10, random.Random(1))
    assert len(rc) == len(recs) - 10 and all(r in recs for r in rc)
    assert EF.random_cut(recs, 0, random.Random(1)) == recs
    print("ok  порог — верхние q, неизмеренное остаётся, случайное отсечение — ровно n")


def test_verdict_needs_all_books_null_and_same_sign():
    keys = ["a", "b", "c"]

    def cash(v):
        return {k: {1000: {"final": v[k]}, 10000: {"final": v[k]}} for k in keys}
    out = {"keys": keys,
           "base": {"half1": cash({"a": 0.1, "b": 0.1, "c": 0.1}), "half2": cash({"a": 0.1, "b": 0.1, "c": 0.1})},
           "cells": {"lev:10": {"windows": {"half1": {"cash": cash({"a": 0.2, "b": 0.2, "c": 0.2})},
                                            "half2": {"cash": cash({"a": 0.2, "b": 0.2, "c": 0.2})}}}},
           "null": {"10:half2": {k: {10000: [0.05] * 19 + [0.25]} for k in keys}}}
    v = EF.verdict(out)["lev:10"]
    assert v["candidate"] and abs(v["null_not_worse"]["a"] - 0.05) < 1e-12
    out["null"]["10:half2"]["c"] = {10000: [0.25] * 3 + [0.05] * 17}          # 15 % не хуже
    assert not EF.verdict(out)["lev:10"]["candidate"], "нуль > 10 % у одной книги — не кандидат"
    out["null"]["10:half2"]["c"] = {10000: [0.05] * 20}
    out["cells"]["lev:10"]["windows"]["half2"]["cash"]["b"][10000]["final"] = 0.09
    assert not EF.verdict(out)["lev:10"]["candidate"], "у одной книги хуже без фильтра — не кандидат"
    out["cells"]["lev:10"]["windows"]["half2"]["cash"]["b"][10000]["final"] = 0.2
    out["cells"]["lev:10"]["windows"]["half1"]["cash"]["a"][10000]["final"] = 0.05
    vv = EF.verdict(out)["lev:10"]
    assert vv["half2_ok"] and not vv["half1_same_sign"] and not vv["candidate"]
    print("ok  критерий: вторая половина у всех книг, нуль ≤ 10 % у каждой, тот же знак на первой")


if __name__ == "__main__":
    test_threshold_filter_and_random_cut()
    test_verdict_needs_all_books_null_and_same_sign()
    print("\nвсе 2 проверки прошли")
