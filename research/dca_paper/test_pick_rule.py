#!/usr/bin/env python3
"""Проверки замера «правило выбора при полной кассе»: подмена очереди ядра
меняет взятых и возвращается; случайный ключ воспроизводим; мера спора;
ключ funding (нет ряда — в конец); вердикт по порогу; отчёт без пустот."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pick_rule as PR                                        # noqa: E402
import run_d6 as D6                                           # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _rec(sym, at, lev, fwd, pnl=0.05, rr=1.0):
    r = TP._rec(sym=sym, at=at, lev=lev, pnl=pnl)
    r["fwd"], r["rr"] = fwd, rr
    r["exit_ts"] = at + 6 * H
    r["marks"] = [(at, pnl)]
    return r


def _taken(recs, key_fn=None, share=0.5):
    rows = []
    if key_fn is None:
        D6.ration(recs, share, deposit=1000.0, keep_rows=rows)
    else:
        with PR.with_queue(key_fn):
            D6.ration(recs, share, deposit=1000.0, keep_rows=rows)
    return [r["sym"] for r, _m in rows]


def test_queue_swap_changes_who_gets_the_money_and_restores():
    # три кандидата в одну секунду, денег на двоих (доля 0.5)
    recs = [_rec("A", AT, 20.0, 50.0), _rec("B", AT, 5.0, 40.0), _rec("C", AT, 2.0, 30.0)]
    was = D6.queue
    assert _taken(recs) == ["A", "B"], "опора: больший прогноз первым"
    assert _taken(recs, lambda r: PR.RULES["fwd_rev"](r, None)) == ["C", "B"]
    assert _taken(recs, lambda r: PR.RULES["lev_lo"](r, None)) == ["C", "B"]
    assert _taken(recs, lambda r: PR.RULES["lev_hi"](r, None)) == ["A", "B"]
    assert D6.queue is was, "очередь ядра обязана вернуться"
    # и возвращается даже при ошибке внутри
    try:
        with PR.with_queue(lambda r: 0):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert D6.queue is was


def test_random_key_is_reproducible_and_differs_by_seed():
    packed = {"optimal_h": [_rec("A", AT, 20.0, 50.0), _rec("B", AT, 5.0, 40.0),
                            _rec("C", AT, 2.0, 30.0)]}
    k1, k2, k3 = PR.random_key(packed, 1), PR.random_key(packed, 1), PR.random_key(packed, 2)
    recs = packed["optimal_h"]
    assert [k1(r) for r in recs] == [k2(r) for r in recs]
    assert [k1(r) for r in recs] != [k3(r) for r in recs]
    # за много зёрен каждый кандидат бывает первым — порядок правда случайный
    firsts = {min(recs, key=PR.random_key(packed, s))["sym"] for s in range(40)}
    assert firsts == {"A", "B", "C"}, firsts


def test_contested_measure():
    recs = [_rec("A", AT, 20.0, 50.0), _rec("B", AT, 5.0, 40.0), _rec("C", AT, 2.0, 30.0),
            _rec("D", AT + H, 10.0, 10.0), _rec("E", AT + 2 * H, 10.0, 10.0), _rec("F", AT + 2 * H, 10.0, 10.0)]
    rows = [{"at": AT, "margin": 1.0, "lev": 20.0, "usd": 0.0}, {"at": AT, "margin": 1.0, "lev": 5.0, "usd": 0.0},
            {"at": AT + H, "margin": 1.0, "lev": 10.0, "usd": 0.0},
            {"at": AT + 2 * H, "margin": 1.0, "lev": 10.0, "usd": 0.0}, {"at": AT + 2 * H, "margin": 1.0, "lev": 10.0, "usd": 0.0}]
    c = PR.contested(recs, rows, "safe_h")
    assert c["seconds_total"] == 3 and c["seconds_contested"] == 1, c
    assert c["candidates_in_contest"] == 3 and c["taken_in_contest"] == 2 and c["taken"] == 5
    assert abs(c["share_taken_in_contest"] - 0.4) < 1e-12
    # эдж взятых: нетто $ на нотионал
    rows2 = [{"margin": 100.0, "lev": 10.0, "usd": 1.0}, {"margin": 100.0, "lev": 10.0, "usd": -0.5}]
    assert abs(PR.taken_edge(rows2) - 2.5) < 1e-9   # (10 − 5) / 2 б.п.


def test_fund_key_prefers_rate_good_for_shorts_and_sends_unknown_last():
    t = np.array([(AT - 3600) * 1000, (AT - 60) * 1000], dtype=np.int64)
    ctx = {"to_asset": {"A": "a", "B": "b", "C": "c"},
           "funding": {"a": (t, np.array([0.0001, 0.0003])), "b": (t, np.array([-0.0002, -0.0001]))}}
    ka = PR.fund_key({"sym": "A", "at": AT}, ctx)
    kb = PR.fund_key({"sym": "B", "at": AT}, ctx)
    kc = PR.fund_key({"sym": "C", "at": AT}, ctx)
    assert ka < kb < kc, (ka, kb, kc)         # A получает +3 б.п. → первым; C без ряда — в конец
    assert PR.fund_key({"sym": "A", "at": AT}, {"error": "нет"}) == float("inf")


def test_verdict_threshold_and_report():
    beat_ok = {"optimal_h": {"final": 0.02, "ratio": 0.01}, "aggr_h": {"final": 0.05, "ratio": 0.0}}
    beat_no = {"optimal_h": {"final": 0.02, "ratio": 0.01}, "aggr_h": {"final": 0.30, "ratio": 0.0}}
    assert PR.verdict(beat_ok).startswith("РЫЧАГ")
    assert PR.verdict(beat_no).startswith("не рычаг") and "aggr_h: в шуме" in PR.verdict(beat_no)
    assert "не измерено" in PR.verdict({"optimal_h": {}, "aggr_h": {"final": 0.0, "ratio": 0.0}})
    cell = {"n": 100, "final": 0.12, "max_dd": -0.05, "usd": 1200.0, "wo3": 300.0, "sigma_day": 80.0}
    s = {"dep": 10000, "books": ["optimal_h"], "rules": ["fwd", "random"], "titles": PR.TITLES,
         "cells": {"fwd": {"optimal_h": cell}, "random": {"optimal_h": dict(cell, final=None, max_dd=None)}},
         "edge": {"fwd": {"optimal_h": 12.3}, "random": {"optimal_h": None}},
         "beat": {"fwd": {"optimal_h": {"final": 0.1, "ratio": 0.2, "ratio_value": 2.4}},
                  "random": {"optimal_h": {"final": None, "ratio": None, "ratio_value": None}}},
         "contest": {"optimal_h": {"seconds_total": 10, "seconds_contested": 3, "candidates_total": 30,
                                   "candidates_in_contest": 12, "taken": 20, "taken_in_contest": 6,
                                   "share_taken_in_contest": 0.3, "no_cash": 10, "take_share": 0.67}},
         "random": {"optimal_h": {"final_med": 0.1, "ratio_med": 2.0, "n": 200}}, "seeds": 200,
         "judge_books": ["optimal_h", "aggr_h"], "beat_max": 0.05,
         "verdict": {"fwd": "не рычаг: …", "random": "не рычаг: …"},
         "diag": {"records": 9000}, "computed_at": "2026-10-06 09:00", "secs": 100.0}
    md = PR.report(s)
    assert "None" not in md and "| оптимальная |" in md and "2.40" in md and "+12.3" in md, md[:400]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
