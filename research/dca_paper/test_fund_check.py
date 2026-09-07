#!/usr/bin/env python3
"""Проверки проверки funding.

Кусаются: шаг ряда меряется по самому ряду (подмени час на восемь — и
сводка обязана измениться); повтор во времени виден числом и меняет итог
книги ровно на удвоенное начисление; разбор позиции печатает КАЖДОЕ
начисление, и их сумма равна числу, которое считает ядро издержек.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import fund_check as F                                        # noqa: E402

H = 3600.0
T0 = 1786320000.0


def _series(step_h, n, rate, start=T0 - 3600.0, dup=0):
    t = [int((start + i * step_h * H) * 1000) for i in range(n)]
    r = [rate] * n
    for i in range(dup):                 # повтор ТОЙ ЖЕ точки
        t.append(t[i])
        r.append(rate)
    o = np.argsort(np.asarray(t))
    return (np.asarray(t, dtype=np.int64)[o],
            np.asarray(r, dtype=float)[o])


def _row(sym="AAAUSDT", hold_h=24.0, margin=400.0, lev=20.0, side="short"):
    return {"dep": 10000, "ruler": "safe_h", "at": T0,
            "exit_ts": T0 + hold_h * H, "sym": sym, "side": side,
            "lev": lev, "margin": margin, "pnl_frac": 0.0, "usd": 0.0,
            "exit": "срок", "entry_px": 1.0, "exit_px": 1.0,
            "fills": [[T0, 1.0, 1.0]], "written_at": T0 + H,
            "rules": R.RULES}


def test_step_of_the_series_is_measured_not_assumed():
    got = F.series_health({"A": _series(8.0, 10, 0.0001),
                           "B": _series(1.0, 40, 0.0001)})
    assert got["A"]["step_h"] == 8.0 and got["B"]["step_h"] == 1.0, got
    ov = F.steps_overview(got)
    assert ov == {"8 ч": 1, "1 ч": 1}, ov
    print(f"ok  шаг ряда измерен по самому ряду: {ov}")


def test_duplicates_are_counted_and_double_the_charge():
    row = _row()
    clean = _series(8.0, 10, 0.001)
    dirty = _series(8.0, 10, 0.001, dup=3)     # три первых точки дважды
    h = F.series_health({"A": dirty})["A"]
    assert h["dups"] == 3 and h["n"] - h["uniq"] == 3, h
    to_asset = {"AAAUSDT": "A"}
    a = F.book_funding([row], {"A": clean}, to_asset)
    b = F.book_funding([row], {"A": dirty}, to_asset)
    # шорт при положительной ставке ПОЛУЧАЕТ; повтор удваивает начисление
    assert a["usd"] > 0 and b["usd"] > a["usd"], (a, b)
    back = F.book_funding([row], F.dedup({"A": dirty}), to_asset)
    assert abs(back["usd"] - a["usd"]) < 1e-9, (back, a)
    print(f"ok  повторы видны числом ({h['dups']}) и меняют итог: "
          f"{a['usd']:+.2f} → {b['usd']:+.2f}, а без них снова "
          f"{back['usd']:+.2f}")


def test_events_add_up_to_what_the_core_counts():
    row = _row(hold_h=24.0, margin=400.0, lev=20.0)
    s = _series(1.0, 48, 0.0002)               # часовой интервал площадки
    got = F.explain_top([row], {"A": s}, {"AAAUSDT": "A"}, k=1)[0]
    assert got["n_events"] == 24, got["n_events"]
    assert abs(got["per_hour"] - 1.0) < 1e-9, got
    total = round(sum(e["usd"] for e in got["events"]), 4)
    core = CO.funding_usd(row, s, "short")
    assert abs(total - round(core, 4)) < 1e-6, (total, core)
    # шорт при плюсовой ставке получает: знак положительный
    assert got["funding_usd"] > 0, got
    # тот же ряд с восьмичасовым шагом даёт втрое меньше начислений
    s8 = _series(8.0, 10, 0.0002)
    got8 = F.explain_top([row], {"A": s8}, {"AAAUSDT": "A"}, k=1)[0]
    assert got8["n_events"] == 3, got8["n_events"]
    print(f"ok  начисления складываются в число ядра: {got['n_events']} "
          f"штук на {got['funding_usd']:+.2f} $ при часовом шаге и "
          f"{got8['n_events']} при восьмичасовом")


def test_no_series_is_a_reason_not_a_zero():
    row = _row()
    got = F.book_funding([row], {}, {"AAAUSDT": "A"})
    assert got["usd"] == 0.0 and got["n"] == 0 and got["missing"] == 1, got
    s = F.run(ctx={"error": "каталога нет", "funding": None},
              log=lambda *a: None)
    assert s.get("error"), s
    assert "Не проверено" in F.report(s)
    print("ok  без ряда позиция не считается посчитанной: она в "
          "«не измерено», а не в нуле")


if __name__ == "__main__":
    for t in (test_step_of_the_series_is_measured_not_assumed,
              test_duplicates_are_counted_and_double_the_charge,
              test_events_add_up_to_what_the_core_counts,
              test_no_series_is_a_reason_not_a_zero):
        t()
    print("\nвсе 4 проверки прошли")
