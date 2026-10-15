#!/usr/bin/env python3
"""Дневной ряд просадки открытых в своде (`run_paper.attach_open_dd`, 15.10):
худший час по дням UTC, момент худшего часа; день без отметок под водой в
ряд не попадает; ячейка без `open_hours` — пустой ряд и момент None.

    .venv/bin/python research/dca_paper/test_open_days.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_paper as RP                                        # noqa: E402

DAY = 86400


def main():
    t0 = 1_790_000_000 - 1_790_000_000 % DAY                  # полночь UTC
    s = {"cells": {"safe:1000": {"open_dd": -40.0, "open_dd_share": -0.04,
                                 "open_hours": [[t0 + 3600, -5.0], [t0 + 7200, -40.0],
                                                [t0 + 2 * DAY + 3600, -12.0]]},
                   "aggr:1000": {"open_dd": 0.0, "open_dd_share": 0.0, "open_hours": []}},
         "books": {"safe:1000": {"all": {"n": 3}, "deposit": 1000},
                   "aggr:1000": {"all": {"n": 1}, "deposit": 1000}}}
    RP.attach_open_dd(s)
    a = s["books"]["safe:1000"]["all"]
    import time
    d0 = time.strftime("%Y-%m-%d", time.gmtime(t0))
    d2 = time.strftime("%Y-%m-%d", time.gmtime(t0 + 2 * DAY))
    assert a["open_days"] == [[d0, -40.0], [d2, -12.0]], a["open_days"]
    assert a["open_dd_at"] == t0 + 7200 and a["open_dd"] == -40.0
    b = s["books"]["aggr:1000"]["all"]
    assert b["open_days"] == [] and b["open_dd_at"] is None
    print("ok  просадка открытых по дням: худший час дня, момент худшего часа, день без отметок пропущен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
