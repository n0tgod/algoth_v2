#!/usr/bin/env python3
"""Проверки замера «пропустить первый вход»: разметка номера входа по имени
(как «одна на имя»), склейка двух рук в секунду, сброс после выхода,
подмножества для кассы, статистика по k, вердикт, отчёт без пустот."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repeat_entry as RE                                     # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _rec(sym, at, pnl=0.05, fwd=10.0, hold_h=6, lev=10.0):
    r = TP._rec(sym=sym, at=at, lev=lev, pnl=pnl)
    r["fwd"] = fwd
    r["exit_ts"] = at + hold_h * H
    return r


def test_label_counts_repeats_while_first_is_open_and_resets_after_exit():
    recs = [_rec("A", AT), _rec("A", AT + H), _rec("A", AT + 2 * H),       # k 1, 2, 3
            _rec("A", AT + 7 * H),                                            # первый вышел в +6 ч → снова 1
            _rec("A", AT + 8 * H),                                            # 2
            _rec("B", AT + H), _rec("B", AT + 9 * H)]                         # своё имя: 1, 1
    lab = RE.label(recs)
    got = [(r["sym"], int((r["at"] - AT) / H), r["k"]) for r in lab]
    assert got == [("A", 0, 1), ("A", 1, 2), ("B", 1, 1), ("A", 2, 3), ("A", 7, 1), ("A", 8, 2), ("B", 9, 1)], got


def test_two_arms_same_second_are_one_record_with_bigger_forecast():
    recs = [_rec("A", AT, fwd=5.0, pnl=0.01), _rec("A", AT, fwd=9.0, pnl=0.02), _rec("A", AT + H)]
    lab = RE.label(recs)
    assert len(lab) == 2 and lab[0]["fwd"] == 9.0 and lab[0]["k"] == 1 and lab[1]["k"] == 2
    # открытые и без нетто не входят
    bad = dict(_rec("C", AT), state="open")
    assert all(r["sym"] != "C" for r in RE.label([bad]))


def test_bands_subsets_and_stats():
    recs = [_rec("A", AT + i * H, pnl=(0.10 if i else -0.05)) for i in range(6)]   # k 1..6, первый в минусе
    lab = RE.label(recs)
    assert [r["k"] for r in lab] == [1, 2, 3, 4, 5, 6]
    assert [RE.band_of(r["k"]) for r in lab] == ["1", "2", "3", "4", "5+", "5+"]
    sub = RE.subset({"optimal_h": recs}, lambda k: k >= 2)
    assert [r["k"] for r in sub["optimal_h"]] == [2, 3, 4, 5, 6]
    st = RE.by_k(lab, "optimal_h")
    assert st["1"]["n"] == 1 and st["1"]["hit"] == 0.0
    assert st["2+"]["n"] == 5 and st["2+"]["hit"] == 1.0 and st["all"]["n"] == 6
    assert st["5+"]["n"] == 2 and abs(st["2+"]["exp_q"] - (0.10 - 0.01) / 10.0) < 1e-12


def test_verdict_and_report_have_no_holes():
    cells = {"k1": {"optimal_h": {"final": 0.11, "max_dd": -0.042}, "aggr_h": {"final": 0.14, "max_dd": -0.065}},
             "k2plus": {"optimal_h": {"final": 0.20, "max_dd": -0.04}, "aggr_h": {"final": 0.25, "max_dd": -0.06}},
             "k3plus": {"optimal_h": {}, "aggr_h": {}}}
    beat_ok = {"k2plus": {"optimal_h": {"final": 0.0, "ratio": 0.01}, "aggr_h": {"final": 0.02, "ratio": 0.0}}}
    assert RE.verdict(cells, beat_ok).startswith("РЫЧАГ")
    beat_no = {"k2plus": {"optimal_h": {"final": 0.0, "ratio": 0.01}, "aggr_h": {"final": 0.40, "ratio": 0.0}}}
    assert RE.verdict(cells, beat_no).startswith("не рычаг")
    worse = dict(cells, k2plus={"optimal_h": {"final": 0.05, "max_dd": -0.04}, "aggr_h": {"final": 0.25, "max_dd": -0.06}})
    assert RE.verdict(worse, beat_ok).startswith("не рычаг"), "лучше случайных, но хуже книги — не рычаг"
    recs = [_rec("A", AT + i * H, pnl=(0.10 if i else -0.05)) for i in range(6)]
    lab = RE.label(recs)
    s = {"dep": 10000, "books": ["optimal_h"], "cells": [(k, t) for k, t, _p in RE.CELLS],
         "records": {"optimal_h": {"n": 6, "by_k": RE.by_k(lab, "optimal_h"),
                                   "share_k": {n: 1 / 6 for n in RE.K_BANDS}}},
         "cash": {k: {"optimal_h": {"n": 3, "final": 0.1, "max_dd": -0.05, "wo3": 100.0, "sigma_day": 20.0}}
                  for k, _t, _p in RE.CELLS},
         "sizes": {k: {"optimal_h": 5} for k, _t, _p in RE.CELLS},
         "beat": {"k2plus": {"optimal_h": {"final": 0.1, "ratio": 0.2, "random_final_med": 0.05, "random_ratio_med": 1.5}},
                  "k3plus": {"optimal_h": {"final": None, "ratio": None, "random_final_med": None, "random_ratio_med": None}}},
         "seeds": 200, "judge_books": ["optimal_h", "aggr_h"], "beat_max": 0.05, "verdict": "не рычаг: …",
         "k_bands": list(RE.K_BANDS), "diag": {"records": 6}, "computed_at": "2026-10-06 09:30", "secs": 10.0}
    md = RE.report(s)
    assert "None" not in md and "nan" not in md and "| k = 1 |" in md and "| k ≥ 2 (все повторы) |" in md, md[:500]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
