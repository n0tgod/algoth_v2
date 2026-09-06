#!/usr/bin/env python3
"""Проверки `slip_x3.py`: решение ↔ открытие по ключу позиции, знак по
стороне, отсутствие цены сигнала — пропуск со счётом, а не ноль."""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import slip_x3 as X                                           # noqa: E402


def _journal(rows):
    d = tempfile.mkdtemp(prefix="x3-")
    with open(os.path.join(d, "journal-2026-09-06.jsonl"), "w",
              encoding="utf-8") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps(dict(r, seq=i + 1)) + "\n")
    return d


def _dec(arm, hour, sym, side, px):
    return {"ev": "decision", "arm": arm, "hour": hour, "sym": sym,
            "side": side, "px": px}


def _open(arm, hour, sym, side, entry_px, notl=100.0):
    return {"ev": "open", "pos": f"{arm}:{hour}:{sym}:{side}",
            "entry_px": entry_px, "notional_usd": notl, "ts": 1.0}


def test_pairs_and_signs_by_side():
    rows = [
        _dec("gbm", "2026-09-06-01", "AAAUSDT", "long", 100.0),
        _open("gbm", "2026-09-06-01", "AAAUSDT", "long", 100.1),   # +10 б.п.
        _dec("gbm", "2026-09-06-01", "BBBUSDT", "short", 100.0),
        _open("gbm", "2026-09-06-01", "BBBUSDT", "short", 100.1),  # −10: шорту выше — лучше
        _dec("nn", "2026-09-06-02", "CCCUSDT", "long", 50.0),
        _open("nn", "2026-09-06-02", "CCCUSDT", "long", 49.9),     # −20
        _open("nn", "2026-09-06-03", "DDDUSDT", "long", 10.0),     # без решения
        {"ev": "close", "pos": "gbm:2026-09-06-01:AAAUSDT:long", "exit_px": 101.0},
    ]
    d = _journal(rows)
    try:
        s = X.run(jdir=d, log=lambda *a: None)
        assert s["present"] and s["miss"] == {"opens": 4, "no_signal_px": 1,
                                              "no_entry_px": 0}, s["miss"]
        got = {r["sym"]: r["slip_bp"] for r in s["rows"]}
        assert abs(got["AAAUSDT"] - 10.0) < 0.01 and abs(got["BBBUSDT"] + 10.0) < 0.01
        assert abs(got["CCCUSDT"] + 20.0) < 0.01, got
        a = s["all"]
        assert a["n"] == 3 and abs(a["median"] + 10.0) < 0.01, a
        assert s["by_side"]["short"]["n"] == 1 and s["by_side"]["long"]["n"] == 2
        assert a["share_worse"] == round(1 / 3, 3) and a["share_over_cap"] == 0.0
        txt = X.report(s)
        assert "| все | 3 |" in txt and "| short | 1 |" in txt, txt
        assert "без цены сигнала 1" in txt
        print("ok  решение ↔ открытие по ключу позиции, знак по стороне, "
              "без цены сигнала — пропуск со счётом")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_missing_journal_is_named():
    s = X.run(jdir="/nonexistent/x3", log=lambda *a: None)
    assert s["present"] is False
    assert "Журнала нет" in X.report(s)
    print("ok  нет журнала — сказано словами, распределения нет")


if __name__ == "__main__":
    test_pairs_and_signs_by_side()
    test_missing_journal_is_named()
    print("\nвсе 2 проверки прошли")
