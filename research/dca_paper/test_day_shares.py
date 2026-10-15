#!/usr/bin/env python3
"""Дни и просадка — от счёта, доллары рядом (`run_paper._stats`, 15.10):
худший день — доля счёта на начало дня, а не стартового депозита; медиана
дня — медиана долей; просадка в $ — пик минус дно в точке худшей доли.

    .venv/bin/python research/dca_paper/test_day_shares.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_paper as RP                                        # noqa: E402

DAY = 86400


def row(day, usd, sym="AUSDT"):
    t = 1_790_000_000 - 1_790_000_000 % DAY + day * DAY
    return {"sym": sym, "usd": usd, "at": t - 3600, "exit_ts": t + 3600, "written_at": t - 3500}


def main():
    # депозит 100: +400 (счёт 500), −200 (счёт 300), +10
    rows = [row(0, 400.0), row(1, -200.0, "BUSDT"), row(2, 10.0, "CUSDT")]
    st = RP._stats(rows, 100.0)
    # худший день: −200 от счёта 500 на начало дня — −40 %, а не −200 %
    assert st["day_worst"] == -0.4 and st["day_worst_usd"] == -200.0, st
    assert st["day_worst_d"] == st["days_rows"][1]["d"], st
    # медиана долей: 400/100=4.0, −200/500=−0.4, 10/300=0.0333 → 0.03333
    assert abs(st["day_median"] - round(10.0 / 300.0, 5)) < 1e-9, st["day_median"]
    assert st["day_median_usd"] == 10.0
    # просадка: пик 500, дно 300 → −40 % и −200 $
    assert st["max_dd"] == -0.4 and st["max_dd_usd"] == -200.0, (st["max_dd"], st["max_dd_usd"])
    # контроль: прежняя формула (от депозита) дала бы −200 % — не она
    assert st["day_worst"] != round(-200.0 / 100.0, 4)
    # счёт съеден: день, начатый с нуля и ниже, — −100 %
    st2 = RP._stats([row(0, -100.0), row(1, -5.0, "BUSDT")], 100.0)
    assert st2["day_worst"] == -1.0, st2["day_worst"]
    print("ok  дни от счёта на начало дня (−200 $ при счёте 500 $ = −40 %), медиана долей, просадка в $")
    return 0


if __name__ == "__main__":
    sys.exit(main())
