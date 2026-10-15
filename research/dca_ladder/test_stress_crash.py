"""Стресс-прогон Ladder без сигнала: калибровочная пара на подставном ряде.

Кусается в обе стороны (урок «калибровочная пара»): на ряду, который
падает на 60 % за окно, книги обязаны уйти в минус и показать полы
(либо срок в минус); на ряду, который растёт, — в плюс без полов. Иначе
сломанная загрузка неотличима от «обвал не страшен». Хранилище
подменяется синтетикой целиком — духа duckdb здесь нет.
"""
import math
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stress_crash as SC                                     # noqa: E402


def _series(t0, t1, drift_total, seed, px0=10.0):
    """Минутный ряд: дрейф на `drift_total` за окно плюс шум 20 б.п./мин."""
    rng = random.Random(seed)
    n = int((t1 - t0) // 60)
    ts = np.arange(n, dtype=np.float64) * 60 + t0
    lp = math.log(px0)
    o, h, l, c = [], [], [], []
    step = drift_total / n
    for i in range(n):
        a = math.exp(lp)
        lp += step + rng.gauss(0, 0.002)
        b = math.exp(lp)
        o.append(a); c.append(b)
        h.append(max(a, b) * (1 + abs(rng.gauss(0, 0.001))))
        l.append(min(a, b) * (1 - abs(rng.gauss(0, 0.001))))
    qv = np.full(n, 1000.0)
    return (ts, np.array(o), np.array(h), np.array(l), np.array(c), qv)


def _run(drift, log):
    t0, t1 = SC.ts_of("2024-01-05"), SC.ts_of("2024-01-25")
    syms = [f"S{i}USDT" for i in range(6)]
    data = {s: _series(t0 - 2 * 86400, t1 + 4 * 86400, drift, i) for i, s in enumerate(syms)}
    data["BTCUSDT"] = data[syms[0]]
    rng = random.Random(1)
    legs = SC.random_legs(syms, t0, t1, 12, [(50.0, 50.0), (80.0, 80.0)], rng)
    out = {}
    for bk in SC.BOOKS:
        recs, miss = SC.positions(legs, data, bk, log)
        assert recs, (bk, miss)
        out[bk] = SC.book_cells(recs, bk)
    return out


def test_calibration_pair():
    quiet = lambda *a: None                                   # noqa: E731
    down = _run(math.log(0.4), quiet)        # −60 % за окно
    up = _run(math.log(1.6), quiet)          # +60 %
    for bk in ("safe", "optimal"):
        d, u = down[bk][1000], up[bk][1000]
        assert d["final"] < 0 < u["final"], (bk, d["final"], u["final"])
        assert d["max_dd"] < -0.01, (bk, d["max_dd"])
        assert (d["floor_share"] or 0) > 0 or d["exits"].get("срок", 0) > 0, d["exits"]
        assert not (u["floor_share"] or 0), (bk, u["exits"])
    # у шести имён и билета $25 на $1k открыто не больше 6 × $25 — просадка
    # счёта мала даже в −60 %: это свойство билета, и оно печатается
    print("    $1k в −60 %: " + ", ".join(f"{bk} {down[bk][1000]['final'] * 100:+.1f} % "
          f"dd {down[bk][1000]['max_dd'] * 100:+.1f} % {down[bk][1000]['exits']}"
          for bk in SC.BOOKS))
    print("ok  калибровка: −60 % за окно → минус с полами/сроком, +60 % → плюс без полов; "
          f"Depth $1k {down['optimal'][1000]['final'] * 100:+.0f} % / "
          f"{up['optimal'][1000]['final'] * 100:+.0f} %")


def test_report_renders():
    quiet = lambda *a: None                                   # noqa: E731
    cells = _run(math.log(0.7), quiet)
    for bk in SC.BOOKS:
        cells[bk]["positions"] = 1
        cells[bk]["missing"] = 0
    res = {"per_day": 12, "seeds": 1, "symbols": 6, "secs": 1.0, "computed_at": "x",
           "windows": [{"name": "t", "from": "a", "to": "b", "kind": "crash", "btc": -0.3,
                        "median_move": -0.3, "symbols": 6, "seeds": [cells]},
                       {"name": "e", "from": "a", "to": "b", "kind": "crash", "error": "нет"}]}
    txt = SC.report(res)
    assert "| Depth" in txt or "| optimal" in txt, txt[:400]
    assert "нет" in txt
    print("ok  отчёт собирается, окно без хранилища названо словами")


if __name__ == "__main__":
    test_calibration_pair()
    test_report_renders()
