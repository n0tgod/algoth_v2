#!/usr/bin/env python3
"""Проверки охраны рынком.

Кусаются: контрольные точки ядра доезжают сквозь `collect` → `replay` до
записи и равны почасовым отметкам ТОЙ ЖЕ симуляции до выхода (после —
пусты); сверка ловит расхождение (яд в отметке); «без 3 лучших дней» и
разбор по дням считаются из дней кассы; порог сестры — середина оси, а не
лучшая ячейка; отчёт называет вердикт равенства и не печатает None.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import wave_guard as W                                        # noqa: E402
import path_screen as P                                       # noqa: E402
import run_short as S                                         # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0


def test_checkpoints_reach_the_record_and_equal_the_hourly_marks():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    # у книг h24 вход стоит на границе часа; фикстура выравнивается сдвигом
    # всех меток времени, чтобы отметки календарных часов и точки от входа
    # говорили об одном
    shift = at % H
    lo = [(b[0] - shift,) + tuple(b[1:]) for b in lo]
    wn = [(b[0] - shift,) + tuple(b[1:]) for b in wn]
    at -= shift
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = T10._legs(at, "SSSUSDT")
    out, _tail = T10._with_levels(
        lambda: S.replay(legs, src=src, log=lambda *a: None,
                         ckpt_hours=W.CKPT_OFFS))
    assert out, "реплей не отдал записей"
    checked = 0
    for key, r in out.items():
        assert r.get("ckpt") is not None and len(r["ckpt"]) == len(W.CKPT_OFFS), key
        got = W.compare_ckpt({key: r}, {key: r})
        assert got["outcome_diff"] == 0 and got["point_diff"] == 0, got
        assert got["none_where_open"] == 0 and got["value_where_closed"] == 0, got
        checked += got["points"]
        lag = W.lag_stats(got["lag"])
        assert lag["n"] == got["points"] and lag["nonzero"] > 0, lag
    assert checked > 0, "ни одной точки до выхода — фикстура не проверяет ничего"
    # без ручки — точек в записи нет, как раньше
    out2, _ = T10._with_levels(lambda: S.replay(legs, src=src, log=lambda *a: None))
    assert all(r.get("ckpt") is None for r in out2.values())
    print(f"ok  контрольные точки ядра доехали до записи и равны отметкам "
          f"({checked} точек до выхода, после выхода пусты); без ручки их нет")


def test_comparison_bites_on_a_poisoned_mark_and_a_changed_outcome():
    at = 1_789_002_000.0                     # граница часа: 496945 × 3600
    marks = [(at + i * H, d) for i, d in enumerate((0.1, -0.2, -0.3, -0.1))]
    rec = {"sym": "X", "at": at, "pnl": -0.5, "exit": "срок", "marks": marks,
           "state": "closed"}
    # точки: по две на час (за секунду до границы и на ней); до выхода (K = 4) — часы 1, 2, 3
    cum = [0.1, -0.1, -0.4]
    ck = []
    for k in W.KS:
        if k < 4:
            ck += [(at + k * H - 1, at + k * H - 60, cum[k - 1]),
                   (at + k * H, at + k * H, cum[k - 1] - 0.01)]     # граница на 1 п.п. хуже
        else:
            ck += [None, None]
    fresh = dict(rec, ckpt=ck)
    key = ("safe_s", "X", at)
    ok = W.compare_ckpt({key: fresh}, {key: rec})
    assert ok["points"] == 3 and ok["point_diff"] == 0 and ok["outcome_diff"] == 0, ok
    lag = W.lag_stats(ok["lag"])
    assert lag["n"] == 3 and abs(lag["median"] + 0.01) < 1e-12, lag
    poisoned = list(ck)
    poisoned[2] = (ck[2][0], ck[2][1], -0.11)            # точка часа 2 «до границы»
    bad = W.compare_ckpt({key: dict(fresh, ckpt=poisoned)}, {key: rec})
    assert bad["point_diff"] == 1 and bad["max_diff"] > 0.009, bad
    bad2 = W.compare_ckpt({key: dict(fresh, pnl=-0.4)}, {key: rec})
    assert bad2["outcome_diff"] == 1, bad2
    late = W.compare_ckpt({key: dict(fresh, ckpt=[c if c else (0, 0, 0.0) for c in ck])},
                          {key: rec})
    assert late["value_where_closed"] == len(W.KS) - 3, late
    print("ok  сверка кусается: подменённая точка, другой исход и точка после "
          f"выхода считаются каждая своим числом; задержка на бар {100 * lag['median']:+.1f} п.п.")


def test_concentration_and_day_diff_come_from_the_cash_days():
    days = [{"d": f"2026-09-0{i}", "usd": u} for i, u in
            enumerate((100.0, -50.0, 400.0, 20.0, 300.0, -10.0), start=1)]
    total, wo, top = W.wo3(days)
    assert abs(total - 760.0) < 1e-9 and abs(wo - (760.0 - 800.0)) < 1e-9, (total, wo)
    assert set(top) == {"2026-09-03", "2026-09-05", "2026-09-01"}, top
    assert W.wo3([]) == (None, None, [])
    # вход не на границе часа — запись в сверку не идёт и посчитана отдельно
    off = W.compare_ckpt({("safe_s", "Y", 1_789_000_000.0 + 7.0): {"pnl": 0.0, "exit": "срок", "ckpt": [None]}},
                         {("safe_s", "Y", 1_789_000_000.0 + 7.0): {"at": 1_789_000_000.0 + 7.0, "pnl": 0.0, "exit": "срок", "marks": []}})
    assert off["misaligned"] == 1 and off["records"] == 0, off
    rule = [dict(d) for d in days]
    rule[1]["usd"] = 200.0            # правило спасло день −50 → +200
    rule[4]["usd"] = 240.0            # и отняло 60 $ у лучшего
    dd = W.day_diff(days, rule)
    assert dd["better"] == 1 and dd["worse"] == 1 and abs(dd["sum_diff"] - 190.0) < 1e-9
    assert [x["d"] for x in dd["rows"]] == ["2026-09-02", "2026-09-05"], dd["rows"]
    assert W.middle(W.wave_axis()) == 2.0 and W.wave_axis() == (1.0, 2.0, 3.0)
    print("ok  «без 3 лучших дней» и разбор по дням — из дней кассы; порог "
          f"сестры — середина оси ({W.middle(W.wave_axis()):g} %)")


def test_report_names_the_verdict_and_prints_no_none():
    dep = W.MAIN_DEP
    days_b = [{"d": "2026-09-01", "usd": 100.0}, {"d": "2026-09-02", "usd": -300.0}]
    days_c = [{"d": "2026-09-01", "usd": 100.0}, {"d": "2026-09-02", "usd": 50.0}]
    def st(fin, dd, days, tails):
        return {"final": fin, "max_dd": dd, "days": days,
                "exits": {"ликвидация": {"n": tails, "usd": -1.0},
                          "срок": {"n": 10, "usd": 5.0}}}
    base = {f"{bk}:{d}": st(0.1, -0.15, days_b, 4) for bk in W.BOOK_KEYS
            for d in (1000, dep, 100000)}
    cell_st = {f"{bk}:{d}": st(0.3, -0.06, days_c, 1) for bk in W.BOOK_KEYS
               for d in (1000, dep, 100000)}
    cell = {"val": 2.0, "delta": {"n": 40, "tails": 30, "cut_worse": 5, "sum": 8.8},
            "stats": cell_st, "control": {"books": {}, "no_cand": 0, "sum_med": -12.4},
            "beat": {**{bk: {"final": 0.0, "ratio": 0.0} for bk in W.BOOK_KEYS}, "sum": 0.01},
            "days": {bk: W.day_diff(days_b, days_c) for bk in W.BOOK_KEYS}}
    empty = {"val": 3.0, "delta": {"n": 0, "tails": 0, "cut_worse": 0, "sum": 0.0},
             "stats": None, "control": None, "beat": {}, "days": {}}
    s = {"base": base, "cells": [cell, empty], "axis": [1.0, 2.0, 3.0], "middle": 2.0,
         "seeds": 2, "dep": dep, "deps": [1000, dep, 100000], "books": W.BOOK_KEYS,
         "faith": {"records": 300, "outcome_diff": 0, "points": 4000, "point_diff": 0,
                   "max_diff": 0.0, "none_where_open": 0, "value_where_closed": 0,
                   "no_ckpt": 0, "misaligned": 0, "sample": 150, "legs": 300, "secs": 120.0,
                   "lag": {"n": 4000, "median": -0.0004, "mean": -0.0006,
                           "p05": -0.02, "p95": 0.015, "nonzero": 0.9}},
         "n": 6593, "wave_none": 1, "proxies": 20, "computed_at": "2026-09-13 02:00",
         "secs": 400.0}
    txt = W.report(s)
    assert "**равенство держится**" in txt and "середина ОБЪЯВЛЕННОЙ оси" in txt, txt[:800]
    assert "Задержка исполнения на один бар" in txt and "-0.040 % маржи" in txt, txt
    # «$ всего» −200 → +150; «без 3 лучших дней» при двух днях — 0 у обеих
    assert "| -200 $ → +150 $ | +0 $ → **+0 $** |" in txt, [l for l in txt.splitlines() if " $ | " in l][:3]
    assert "Не сработало ни разу" in txt and "None" not in txt, [l for l in txt.splitlines() if "None" in l]
    bad = W.report(dict(s, faith=dict(s["faith"], point_diff=3)))
    assert "РАСХОЖДЕНИЕ" in bad
    assert "Не посчитано" in W.report({"error": "кэша нет"})
    print("ok  отчёт: вердикт равенства выводится из чисел, порог сестры назван "
          "серединой оси, прочерк вместо None")


if __name__ == "__main__":
    for t in (test_checkpoints_reach_the_record_and_equal_the_hourly_marks,
              test_comparison_bites_on_a_poisoned_mark_and_a_changed_outcome,
              test_concentration_and_day_diff_come_from_the_cash_days,
              test_report_names_the_verdict_and_prints_no_none):
        t()
    print("\nвсе 4 проверки прошли")
