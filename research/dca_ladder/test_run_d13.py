#!/usr/bin/env python3
"""Проверки D13 (короткая книга рядом с длинной).

Кусаются: ряды выравниваются по КАЛЕНДАРЮ, а не по номеру элемента
(сдвиг на сутки меняет корреляцию); совпадением имён считается только
пересечение во времени, касание встык — нет; просадка пары считается по
общей кривой, а не как сумма просадок; ячейка D10 отдаёт ровно те строки,
из которых сложен её итог.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d13 as D13                                        # noqa: E402
import run_d10 as D10                                        # noqa: E402
import test_run_d3 as T3                                     # noqa: E402
import test_run_d9 as T9                                     # noqa: E402
import test_run_d10 as T10                                   # noqa: E402

DAY = 86400.0
T0 = 1786320000.0                     # 2026-08-10 00:00 UTC


def _row(sym, at, hold_h, usd):
    return {"sym": sym, "at": at, "exit_ts": at + hold_h * 3600.0,
            "usd": usd}


def test_series_and_align_follow_the_calendar_not_the_index():
    a = D13.series([_row("A", T0, 1, 5.0), _row("A", T0 + 3600, 2, -2.0),
                    _row("B", T0 + 2 * DAY, 1, 7.0)])
    assert set(a) == {D13._day(T0), D13._day(T0 + 2 * DAY)}, a
    assert abs(a[D13._day(T0)] - 3.0) < 1e-9, a
    b = D13.series([_row("C", T0 + DAY, 1, 4.0)])
    days, xa, xb = D13.align(a, b)
    # пересечение окон: у ряда b одни сутки, и общая ось — они же
    assert days == [D13._day(T0 + DAY)] and xa == [0.0] and xb == [4.0], (days, xa, xb)
    # выравнивание по календарю: сдвиг второго ряда на сутки меняет пару
    b2 = D13.series([_row("C", T0, 1, 4.0), _row("C", T0 + DAY, 1, 1.0)])
    d2, x2a, x2b = D13.align(a, b2)
    assert d2 == [D13._day(T0), D13._day(T0 + DAY)], d2
    assert x2a == [3.0, 0.0] and x2b == [4.0, 1.0], (x2a, x2b)
    assert D13.align({}, b) == ([], [], [])
    print(f"ok  ряды по суткам выхода и общая ось по календарю: {d2}, "
          f"длинная {x2a}, короткая {x2b}")


def test_pair_drawdown_is_taken_from_the_joint_curve():
    # длинная теряет в первый день и отыгрывает во второй, короткая —
    # наоборот: по отдельности просадка есть у обеих, у пары её нет
    l = [-100.0, +150.0]
    s = [+120.0, -80.0]
    dl = D13.curve_dd(l, 10000)
    ds = D13.curve_dd(s, 10000)
    dp = D13.curve_dd([a + b for a, b in zip(l, s)], 20000)
    assert dl < 0 and ds < 0, (dl, ds)
    assert dp == 0.0, dp                     # пара под водой не была
    assert D13.curve_dd([], 10000) is None
    print(f"ok  просадка пары из общей кривой: длинная {100 * dl:.2f} %, "
          f"короткая {100 * ds:.2f} %, пара {100 * dp:.2f} %")


def test_collision_is_time_overlap_not_a_shared_name():
    longs = [_row("AAAUSDT", T0, 10, 1.0), _row("BBBUSDT", T0, 1, 1.0)]
    shorts = [{"sym": "AAAUSDT", "at": T0 + 3600, "exit_ts": T0 + 2 * 3600,
               "usd": -3.0},                                   # внахлёст
              {"sym": "BBBUSDT", "at": T0 + 3600, "exit_ts": T0 + 2 * 3600,
               "usd": 5.0},                                    # встык
              {"sym": "CCCUSDT", "at": T0, "exit_ts": T0 + 3600, "usd": 2.0}]
    c = D13.collisions(shorts, longs)
    assert c["n"] == 1 and c["names"] == 1 and c["top"] == [("AAAUSDT", 1)], c
    assert abs(c["usd"] + 3.0) < 1e-9 and abs(c["share"] - 1 / 3) < 1e-4, c
    assert D13.collisions([], longs)["share"] is None
    print("ok  совпадение — пересечение во времени: нахлёст найден, "
          "касание встык и чужое имя не считаются")


def test_cell_returns_the_rows_its_result_is_made_of():
    lo, at = T9._rise_then_fall()
    src = T3._Src({"SSSUSDT": lo})
    legs = T10._legs(at, "SSSUSDT")
    got = T10._with_levels(lambda: D10.collect(src=src, legs=legs,
                                               log=lambda *a: None))
    rk = D10.BOOK_RULER["optimal_s"]
    stores, _n, _lost = D10.common_sample(got["recs"][rk], log=lambda *a: None)
    st = stores[D10.REF]
    recs = [st.row(i) for i in range(len(st))]
    rows = []
    c = D10.cell(recs, "optimal_s", 10000, rows_out=rows)
    assert len(rows) == c["taken"], (len(rows), c["taken"])
    assert all(set(r) >= {"sym", "at", "exit_ts", "usd", "margin"} for r in rows)
    got_usd = round(sum(r["usd"] for r in rows), 2)
    assert abs(got_usd - (c["usd"] or 0)) < 0.02, (got_usd, c["usd"])
    print(f"ok  ячейка отдаёт свои строки: {len(rows)} позиций на "
          f"{got_usd:+.2f} $ — ровно её итог")


if __name__ == "__main__":
    test_series_and_align_follow_the_calendar_not_the_index()
    test_pair_drawdown_is_taken_from_the_joint_curve()
    test_collision_is_time_overlap_not_a_shared_name()
    test_cell_returns_the_rows_its_result_is_made_of()
    print("\nвсе 4 проверки прошли")
