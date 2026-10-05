#!/usr/bin/env python3
"""Проверки замера «билет и плечо забора» безопасной короткой книги.

Кусаются: гейт оставляет плечо ≥ порога, неизвестное плечо остаётся и
посчитано; доля билета на время счёта меняет билет кассы и ВОЗВРАЩАЕТСЯ
(иначе следующий прогон книг жил бы с половинным билетом); σ дня и
отношение — из дней кассы; отчёт без None.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_size as Z                                        # noqa: E402
import rules as R                                             # noqa: E402


def test_lev_gate_keeps_sized_positions_and_counts_the_unknown():
    recs = [{"lev": 1.0}, {"lev": 4.99}, {"lev": 5.0}, {"lev": 25.0}, {"lev": None}, {}]
    keep, unknown = Z.lev_gate(recs)
    assert [r.get("lev") for r in keep] == [5.0, 25.0, None, None], keep
    assert unknown == 2
    print("ok  гейт: остаются плечо ≥ 5× и неизвестное (посчитано отдельно)")


def test_share_is_applied_for_the_count_and_restored():
    was = R.SHORT_SHARE.get("safe_h")
    t_full = R.ticket_in("safe_h", "safe_h", 10000)
    own = R.ticket(10000, "safe_h")
    seen = Z.with_share("safe_h", 0.25, lambda: (R.SHORT_SHARE["safe_h"],
                                                 R.ticket_in("safe_h", "safe_h", 10000)))
    assert seen[0] == 0.25 and abs(seen[1] - max(R.floor_of("safe_h"), own * 0.25)) < 1e-9, (seen, own)
    assert R.SHORT_SHARE.get("safe_h") == was and R.ticket_in("safe_h", "safe_h", 10000) == t_full
    try:
        Z.with_share("safe_h", 0.25, lambda: 1 / 0)
    except ZeroDivisionError:
        pass
    assert R.SHORT_SHARE.get("safe_h") == was
    print(f"ok  билет: на время счёта {t_full:g} → {seen[1]:g}, после — как было, и при ошибке тоже")


def test_day_sigma_and_report():
    days = [{"d": "2026-09-01", "usd": 100.0}, {"d": "2026-09-02", "usd": -100.0},
            {"d": "2026-09-03", "usd": 300.0}]
    sd, ratio = Z.day_sigma(days)
    assert abs(sd - 163.299) < 0.01 and abs(ratio - 100.0 / sd) < 1e-9, (sd, ratio)
    assert Z.day_sigma([{"d": "x", "usd": 1.0}]) == (None, None)
    cell = {"n": 100, "final": 0.1, "max_dd": -0.05, "usd": 1000.0, "wo3": 200.0,
            "sigma_day": 163.3, "ratio_day": 0.61, "tails": 4, "days": days}
    s = {"book": "safe_h", "dep": 10000, "share": 0.5, "min_lev": 5.0, "seeds": 2,
         "removed": 70, "offered": 100, "unknown_lev": 0,
         "cells": {k: dict(cell) for k, _t in Z.CELLS}, "beat": {"final": 0.0, "ratio": 0.01},
         "days_diff": Z.W.day_diff(days, days), "computed_at": "2026-10-03 06:00", "secs": 9.0}
    txt = Z.report(s)
    assert "| плечо ≥ 5× | 100 | +10.0 % | -5.0 % | +1,000 $ | +200 $ | 163 $ | 0.61 | 4 |" in txt, txt
    assert "не хуже по итогу в +0 % зёрен" in txt and "None" not in txt, txt
    assert "Не посчитано" in Z.report({"error": "кэша нет"})
    print("ok  σ дня и отношение — из дней кассы; отчёт без None")


if __name__ == "__main__":
    for t in (test_lev_gate_keeps_sized_positions_and_counts_the_unknown,
              test_share_is_applied_for_the_count_and_restored,
              test_day_sigma_and_report):
        t()
    print("\nвсе 3 проверки прошли")
