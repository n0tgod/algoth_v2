#!/usr/bin/env python3
"""Проверки замера «гейты входа книг DCA».

Кусаются: запас до пола считается ядром лестницы и падает с ростом
плеча (на том же имени 25× ближе к полу, чем 3×); доля пола берётся у
КНИГИ, а не одна на всех; теснота меряется той стороной стакана, об
которую бьёт вход; решение без записи часа гейт ПРОПУСКАЕТ и считает
отдельно — «не измерено» фильтром быть не должно; контроль берёт
выборки того же размера ПО КАЖДОЙ книге.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import run_d2 as D2                                           # noqa: E402
import entry_gate as E                                        # noqa: E402

T0 = 1_789_000_000.0


def _rec(sym="AAAUSDT", lev=10.0, px=100.0, side="short", margin=100.0):
    return {"sym": sym, "at": T0, "exit_ts": T0 + 3600, "side": side,
            "lev": float(lev), "margin": float(margin), "entry_px": px,
            "exit_px": px, "avg": px, "depth": 1, "usd": 0.0,
            "fills": [[T0, px, 1.0]]}


def test_floor_gap_falls_with_leverage_and_follows_the_book():
    """Запас до пола — ядром лестницы, доля пола — правилом КНИГИ."""
    look = lambda _n: 0.005                       # ставка тира, фикстура
    g3 = E.floor_gap(_rec(lev=3.0), "safe_h", look=look)
    g25 = E.floor_gap(_rec(lev=25.0), "safe_h", look=look)
    assert g3 and g25 and g3 > 3 * g25, (g3, g25)
    # у безопасной пол 0.10, у оптимальной 0.50 — при том же плече
    # оптимальная режется ВДВОЕ ближе к входу
    s_h = E.floor_gap(_rec(lev=25.0), "safe_h", look=look)
    o_h = E.floor_gap(_rec(lev=25.0), "optimal_h", look=look)
    assert R.floor_frac_of("optimal_h", D2.FLOOR_FRAC) == 0.50
    assert o_h < s_h * 0.75, (s_h, o_h)
    # нет плеча — величина НЕ измерена, а не ноль
    assert E.floor_gap(dict(_rec(), lev=None), "safe_h", look=look) is None
    print(f"ok  запас до пола: 3× даёт {100 * g3:.1f} %, 25× — "
          f"{100 * g25:.1f} %; у оптимальной с полом 0.5 — {100 * o_h:.1f} %")


def test_tightness_reads_the_side_the_entry_hits():
    """Шорт бьёт в БИД, лонг в аск: теснота меряется своей стороной."""
    td = tempfile.mkdtemp()
    sym, hour = "AAAUSDT", time.strftime("%Y-%m-%d-%H",
                                         time.gmtime(T0 - 1))
    os.makedirs(os.path.join(td, sym), exist_ok=True)
    with open(os.path.join(td, sym, hour[:10] + ".jsonl"), "w",
              encoding="utf-8") as f:
        f.write(json.dumps({"hour": hour, "best_b": 1000.0,
                            "best_a": 4000.0, "spread_bp": 5.0}) + "\n")
    d = E.Depth(root=td, log=lambda *a: None)
    # нотионал = БИЛЕТ книги × плечо: маржи у записи кэша нет вовсе
    tick = float(R.ticket_in("safe_h", "safe_h", E.MAIN_DEP))
    sh = d.tightness(_rec(side="short", lev=10.0), "safe_h")
    lo = d.tightness(_rec(side="long", lev=10.0), "safe_h")
    assert abs(sh - tick * 10.0 / 1000.0) < 1e-9, (sh, tick)
    assert abs(lo - tick * 10.0 / 4000.0) < 1e-9, (lo, tick)
    assert abs(sh / lo - 4.0) < 1e-9, (sh, lo)
    # часа нет в записи — НЕ измерено
    assert d.tightness(dict(_rec(), at=T0 + 86400 * 5), "safe_h") is None
    assert d.why()["измерено"] == 2 and d.why()["нет файла записи"] == 1
    print(f"ok  теснота от билета книги ${tick:g}: шорт меряется бидом "
          f"({sh:.2f}), лонг аском ({lo:.2f}); часа нет — прочерк, и он "
          "посчитан")


def test_unknown_is_not_a_filter():
    """Решение без величины гейт пропускает и считает отдельно."""
    recs = [_rec(sym="AAAUSDT"), _rec(sym="BBBUSDT"), _rec(sym="CCCUSDT")]
    seen = {"AAAUSDT": True, "BBBUSDT": False, "CCCUSDT": None}
    kept, unknown = E.gate_records(recs, "safe_h",
                                   lambda r, bk: seen[r["sym"]])
    assert [r["sym"] for r in kept] == ["AAAUSDT", "CCCUSDT"], kept
    assert unknown == 1, unknown
    print("ok  «не измерено» не фильтр: решение без величины остаётся в "
          "книге и стоит отдельным числом")


def test_control_samples_each_book_to_its_own_size():
    """Выборка того же размера — ПО КАЖДОЙ книге своя."""
    packed = {"safe_h": [_rec(sym=f"S{i}USDT") for i in range(20)],
              "optimal_h": [_rec(sym=f"O{i}USDT") for i in range(10)]}
    sizes = {"safe_h": 7, "optimal_h": 3}
    seen = []

    def _stats(sub, ctx, launch, keys, deps=None, now=None):
        seen.append({k: len(v) for k, v in sub.items()})
        return {}

    was = E.AG.stats_of
    E.AG.stats_of = _stats
    try:
        E.control_rows(packed, sizes, None, {}, ["safe_h", "optimal_h"],
                       seeds=4, log=lambda *a: None)
    finally:
        E.AG.stats_of = was
    assert seen == [{"safe_h": 7, "optimal_h": 3}] * 4, seen
    print("ok  контроль: каждой книге своя выборка того же размера "
          f"({seen[0]})")


def test_report_names_axes_thresholds_and_the_control():
    dep = int(R.DEPOSITS[1])
    ax = {"name": "запас до пола", "keys": ["safe_h"],
          "axis": [{"key": "g05", "value": 0.05}],
          "base": {f"safe_h:{dep}": {"n": 600, "usd": 1000.0,
                                     "final": 0.1, "max_dd": -0.15,
                                     "ratio": 0.67}},
          "cells": {"g05": {"value": 0.05, "unknown": 0,
                            "stats": {f"safe_h:{dep}": {
                                "n": 300, "usd": 1400.0, "final": 0.14,
                                "max_dd": -0.05, "ratio": 2.8}}}},
          "control": {"g05": {"safe_h": [{"final": 0.05, "ratio": 0.5},
                                         {"final": 0.2, "ratio": 3.0}]}}}
    s = {"families": [{"name": "короткие книги h24", "keys": ["safe_h"],
                       "axes": [ax], "live": {}}],
         "seeds": 2, "main_dep": dep, "computed_at": "2026-09-12 23:00",
         "depth": {"измерено": 10, "нет файла записи": 1,
                   "нет часа в записи": 2}}
    txt = E.report(s)
    assert "запас до пола" in txt and "как сейчас" in txt, txt[:400]
    assert "+14.0 %" in txt and "+10.0 %" in txt, txt[:800]
    assert "итог 50 % из 2" in txt, [x for x in txt.splitlines()
                                     if "%" in x][:8]
    assert "не измерено" in txt.lower(), txt[:800]
    bad = E.report({"error": "кэш реплея непригоден: подпись чужая"})
    assert "Не посчитано" in bad and "подпись чужая" in bad, bad[:200]
    print("ok  отчёт: обе ветки порога, доля зёрен числом, запись "
          "стакана под теснотой названа")


if __name__ == "__main__":
    for t in (test_floor_gap_falls_with_leverage_and_follows_the_book,
              test_tightness_reads_the_side_the_entry_hits,
              test_unknown_is_not_a_filter,
              test_control_samples_each_book_to_its_own_size,
              test_report_names_axes_thresholds_and_the_control):
        t()
    print("\nвсе 5 проверок прошли")
