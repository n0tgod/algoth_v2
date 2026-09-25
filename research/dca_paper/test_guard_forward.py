#!/usr/bin/env python3
"""Проверки замера «охрана рынком вперёд».

Кусаются: отбор записей — с 00:00 UTC названного дня; карта охраны на
время ветки «без» пуста и после счёта ВОССТАНОВЛЕНА (иначе следующий
прогон книг жил бы без правила); отчёт без None и с обеими ветками.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard_forward as GF                                    # noqa: E402
import rules as R                                             # noqa: E402


def test_forward_cache_starts_at_midnight_of_the_day():
    t0 = GF.since_ts("2026-09-13")
    assert t0 == 1789257600.0, t0
    cache = {("safe_s", "A", t0 - 1): {"at": t0 - 1}, ("safe_s", "B", t0): {"at": t0},
             ("safe_s", "C", t0 + 5): {"at": t0 + 5}}
    got = GF.forward_cache(cache, "2026-09-13")
    assert sorted(k[1] for k in got) == ["B", "C"], got
    print("ok  вперёд — с 00:00 UTC дня смены правил, граница включительно")


def test_off_branch_clears_the_guard_and_restores_it():
    seen = []
    was = dict(R.WAVE_GUARD_PCT)

    def _stats(packed, ctx, launch, keys, deps=None, now=None):
        seen.append(dict(R.WAVE_GUARD_PCT))
        return {}

    saved = GF.AG.stats_of
    GF.AG.stats_of = _stats
    try:
        GF.stats_both({}, None, {})
    finally:
        GF.AG.stats_of = saved
    assert seen[0] == {} and seen[1] == was, seen
    assert R.WAVE_GUARD_PCT == was, R.WAVE_GUARD_PCT
    print("ok  ветка «без охраны» считается с пустой картой, карта восстановлена")


def test_report_has_both_branches_and_no_none():
    days_a = [{"d": "2026-09-14", "usd": -300.0}, {"d": "2026-09-15", "usd": 100.0}]
    days_b = [{"d": "2026-09-14", "usd": -100.0}, {"d": "2026-09-15", "usd": 90.0}]
    st = lambda fin, dd, days, t: {"n": 100, "final": fin, "max_dd": dd, "days": days,   # noqa: E731
                                  "exits": {"пол": {"n": t, "usd": -1.0}}}
    s = {"since": "2026-09-13", "n": 400, "dep": 10000,
         "books": {bk: {"off": st(-0.02, -0.09, days_a, 4), "on": st(0.01, -0.05, days_b, 2),
                        "days": GF.W.day_diff(days_a, days_b)} for bk in GF.BOOK_KEYS},
         "guard": {"safe_h": 2.0}, "computed_at": "2026-09-25 10:00", "secs": 30.0}
    txt = GF.report(s)
    assert "-2.0 % → **+1.0 %**" in txt and "4 → 2" in txt, txt[:900]
    assert "None" not in txt and "| 2026-09-14 | -300 $ | -100 $ | +200 $ |" in txt, txt
    assert "Не посчитано" in GF.report({"error": "кэша нет"})
    print("ok  отчёт: обе ветки, дни, прочерк вместо None")


if __name__ == "__main__":
    for t in (test_forward_cache_starts_at_midnight_of_the_day,
              test_off_branch_clears_the_guard_and_restores_it,
              test_report_has_both_branches_and_no_none):
        t()
    print("\nвсе 3 проверки прошли")
