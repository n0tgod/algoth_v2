#!/usr/bin/env python3
"""
Тесты замера сделки. Закрывают места, где ошибка была бы невидимой.

Главное здесь — **порядок касаний**. Если стоп и цель задеты в одну
секунду, засчитываться обязан стоп: порядок внутри секунды нам
неизвестен, и решать неоднозначность в свою пользу значит рисовать
доходность, которой не было. Ровно этот род ошибки убил движок v1
(«цену коснулись — значит исполнено»).

    python3 research/t3_brackets/test_brackets.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# Порядок путей важен: `probe.py` в проекте несколько, и вставка чужого
# каталога ПОСЛЕ своего однажды уже дала подмену модуля (дефект F3).
# Здесь модуль назван своим именем, но порядок всё равно явный.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t1_tape"))
sys.path.insert(0, HERE)

import brackets as P  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def grid_from(prices, step=1.0):
    """Сетка из последовательности `(open, high, low, close)` по секундам."""
    n = len(prices)
    g = {"t": np.arange(n, dtype=np.float64) * step, "step_sec": step,
         "open": np.array([p[0] for p in prices], dtype=np.float64),
         "high": np.array([p[1] for p in prices], dtype=np.float64),
         "low": np.array([p[2] for p in prices], dtype=np.float64),
         "close": np.array([p[3] for p in prices], dtype=np.float64)}
    return g


def flat(v):
    return (v, v, v, v)


def test_target_hit():
    g = grid_from([flat(100.0)] * 3 + [(100.0, 101.0, 100.0, 101.0)]
                  + [flat(101.0)] * 3)
    r = P.bracket(g, 0, side=-1, stop_px=99.0, target_px=100.5,
                  max_hold_sec=10)
    check("цель засчитана", r["outcome"] == "цель", str(r))
    check("вход по следующей секунде", abs(r["entry"] - 100.0) < 1e-9, str(r))


def test_stop_hit():
    g = grid_from([flat(100.0)] * 3 + [(100.0, 100.0, 98.5, 98.5)]
                  + [flat(98.5)] * 3)
    r = P.bracket(g, 0, side=-1, stop_px=99.0, target_px=101.0,
                  max_hold_sec=10)
    check("стоп засчитан", r["outcome"] == "стоп", str(r))


def test_tie_goes_against_us():
    """В одну секунду задеты оба уровня — считается стоп."""
    g = grid_from([flat(100.0)] * 2 + [(100.0, 102.0, 98.0, 100.0)]
                  + [flat(100.0)] * 2)
    r = P.bracket(g, 0, side=-1, stop_px=99.0, target_px=101.0,
                  max_hold_sec=10)
    check("ничья решается против нас", r["outcome"] == "стоп", str(r))
    r2 = P.bracket(g, 0, side=1, stop_px=101.0, target_px=99.0,
                   max_hold_sec=10)
    check("и в шорте тоже", r2["outcome"] == "стоп", str(r2))


def test_timeout():
    g = grid_from([flat(100.0)] * 10)
    r = P.bracket(g, 0, side=-1, stop_px=99.0, target_px=101.0,
                  max_hold_sec=5)
    check("вышли по времени", r["outcome"] == "время", str(r))
    check("выход по последней цене", abs(r["exit"] - 100.0) < 1e-9, str(r))


def test_entry_skips_empty_seconds():
    """Секунда без сделок — не наблюдение, вход берётся со следующей."""
    g = grid_from([flat(100.0), (np.nan,) * 4, (101.0, 101.0, 101.0, 101.0)]
                  + [flat(101.0)] * 3)
    r = P.bracket(g, 0, side=-1, stop_px=99.0, target_px=200.0,
                  max_hold_sec=10)
    check("вход не по пустой секунде", abs(r["entry"] - 101.0) < 1e-9, str(r))


def test_shelf_is_nearest_ahead():
    """Цель — ближайшая полка впереди, а не самая крупная."""
    centers = np.array([99.0, 100.0, 101.0, 102.0, 103.0])
    vol = np.array([10.0, 10.0, 50.0, 10.0, 900.0])
    t = P.shelf_ahead(centers, vol, entry=100.2, long=True, q=0.5)
    check("взята ближняя полка, а не крупнейшая", abs(t - 101.0) < 1e-9,
          str(t))
    t2 = P.shelf_ahead(centers, vol, entry=100.2, long=False, q=0.5)
    check("для шорта — ближайшая снизу", t2 is None or t2 < 100.2, str(t2))


def test_shelf_none_when_nothing_ahead():
    centers = np.array([99.0, 100.0, 101.0])
    vol = np.array([100.0, 10.0, 10.0])
    t = P.shelf_ahead(centers, vol, entry=101.5, long=True, q=0.9)
    check("впереди структуры нет — цели нет", t is None, str(t))


def test_break_even_arithmetic():
    """Безубыточная доля побед: при 1 к 3 и издержках она около трети."""
    trades = [{"net_bp": 0.0, "rr": 3.0, "stop_bp": 10.0, "outcome": "цель",
               "held": 1} for _ in range(10)]
    st = P.stats(trades, cost_bp=11.0)
    want = (10.0 + 11.0) / (10.0 * 4.0)
    check(f"безубыточная доля {st['break_even']:.3f}",
          abs(st["break_even"] - want) < 1e-9, f"{st['break_even']} {want}")


def test_seed_is_reproducible_by_number():
    a = P.rng_for(3, 5, 1).integers(10**6)
    b = P.rng_for(3, 5, 1).integers(10**6)
    c = P.rng_for(3, 6, 1).integers(10**6)
    check("зерно воспроизводимо", a == b, f"{a} {b}")
    check("и различается по ячейке", a != c, f"{a} {c}")


def main():
    print("бракет")
    test_target_hit()
    test_stop_hit()
    test_tie_goes_against_us()
    test_timeout()
    test_entry_skips_empty_seconds()
    print("цель по структуре")
    test_shelf_is_nearest_ahead()
    test_shelf_none_when_nothing_ahead()
    print("арифметика и зерно")
    test_break_even_arithmetic()
    test_seed_is_reproducible_by_number()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
