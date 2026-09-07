#!/usr/bin/env python3
"""Проверки `side_wave.py`: волна из закрытий на границах часов, сырой
исход = нетто кассы + s·β·волна, без волны — пропуск со счётом."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import side_wave as W                                         # noqa: E402
import trades as TR                                           # noqa: E402

H0 = "2026-08-10-00"
T0 = TR.hour_end(H0)


def _bars(drift_bp_per_h, start, hours, px0=100.0):
    """Минутные бары с постоянным дрейфом: закрытие часа k = px0·(1+d)^k."""
    out = []
    for k in range(hours * 60):
        t = start + k * 60
        px = px0 * (1 + drift_bp_per_h / 1e4) ** (k / 60.0)
        out.append([t, px, px, px, px, 1.0])
    return out


def test_wave_and_raw_outcome():
    hours = [H0, "2026-08-10-01", "2026-08-10-02"]
    bounds = [TR.hour_end(h) for h in hours]
    # рынок падает: −10 б.п. в час у всех прокси (4 имени) → за 4 ч ≈ −40
    src = {p: _bars(-10.0, bounds[0] - 3600, 12) for p in W.PROXY[:5]}
    read = lambda s, a, b: [r for r in src.get(s, []) if a <= r[0] <= b]  # noqa: E731
    wt, meta = W.wave_table(bounds, [4], read=read, proxies=W.PROXY[:6],
                            log=lambda *a: None)
    assert meta["proxies"] == 5 and meta["cover"][4] == 3, meta
    w4 = wt[4]
    assert np.all(np.isfinite(w4)) and abs(w4[0] - (-40.0)) < 0.5, w4
    # мало прокси с ценой — волны нет, не ноль
    wt2, meta2 = W.wave_table(bounds, [4], read=read, proxies=W.PROXY[:3],
                              log=lambda *a: None)
    assert not np.isfinite(wt2[4]).any() and meta2["cover"][4] == 0
    # сделки: шорт с нулевым остатком в падающем рынке — сырой плюс;
    # лонг с +40 остатка — сырой ноль
    trades = [
        {"arm": "gbm", "hour": H0, "sym": "AAA", "side": "short",
         "state": "закрыта", "net_bp": 0.0, "pnl": 0.0},
        {"arm": "gbm", "hour": H0, "sym": "BBB", "side": "long",
         "state": "закрыта", "net_bp": 40.0, "pnl": 4.0},
        {"arm": "gbm", "hour": "2026-08-10-09", "sym": "CCC", "side": "short",
         "state": "закрыта", "net_bp": 100.0, "pnl": 10.0},   # часа нет в волне
        {"arm": "gbm", "hour": H0, "sym": "DDD", "side": "short",
         "state": "открыта", "net_bp": 999.0, "pnl": 99.0},
    ]
    wave = {h: float(w4[i]) for i, h in enumerate(hours)}
    betas = {("gbm", H0, "AAA", "short"): 0.5}
    rows, nw, nb = W.side_rows(trades, betas, wave, 4, "gbm", "short")
    assert len(rows) == 1 and nw == 1 and nb == 0, (rows, nw, nb)
    assert abs(rows[0]["raw"] - (0.0 - 0.5 * w4[0])) < 1e-9 and rows[0]["raw"] > 0
    rows_l, nw_l, nb_l = W.side_rows(trades, betas, wave, 4, "gbm", "long")
    assert len(rows_l) == 1 and nb_l == 1, (rows_l, nb_l)     # β нет → 1.0
    assert abs(rows_l[0]["raw"] - (40.0 + w4[0])) < 1e-9
    assert abs(rows_l[0]["pnl_raw"] - 4.0 * rows_l[0]["raw"] / 40.0) < 1e-9
    st = W._stat(rows_l)
    assert st["n"] == 1 and st["wave_neg_share"] == 1.0 and st["beta_mean"] == 1.0
    print(f"ok  волна −40 б.п. за 4 ч из закрытий; шорт β 0.5: сырой "
          f"{rows[0]['raw']:+.1f} при остатке 0; лонг: сырой {rows_l[0]['raw']:+.1f} "
          "при остатке +40; час без волны и открытая — пропуск со счётом")


def test_run_end_to_end_with_fake_books():
    hours = [f"2026-08-10-{h:02d}" for h in range(6)]
    bounds = [TR.hour_end(h) for h in hours]
    src = {p: _bars(+5.0, bounds[0] - 3600, 40) for p in W.PROXY[:8]}
    read = lambda s, a, b: [r for r in src.get(s, []) if a <= r[0] <= b]  # noqa: E731
    trades = []
    for i, h in enumerate(hours):
        trades.append({"arm": "nn", "hour": h, "sym": f"S{i}", "side": "short",
                       "state": "закрыта", "net_bp": 200.0, "pnl": 2.0})
        trades.append({"arm": "nn", "hour": h, "sym": f"L{i}", "side": "long",
                       "state": "закрыта", "net_bp": -50.0, "pnl": -0.5})
    fake = lambda k: (trades, {"horizon_h": 24})                # noqa: E731
    s = W.run(read=read, log=lambda *a: None, books=("h24",), trades_of=fake)
    assert s["present"] and s["hours"] == 6 and "h24" in s["books"], s.keys()
    st = s["books"]["h24"]["arms"]["nn"]["short"]
    m = s["market"]["24"]
    assert m["hours_with_wave"] == 6 and m["median_bp"] > 100 and m["neg_share"] == 0.0, m
    # растущий рынок: шорт в кассе +200, сырым меньше на волну
    assert st["n"] == 6 and st["net_mean"] == 200.0 and st["raw_mean"] < 200.0, st
    assert abs(st["raw_mean"] - (200.0 - st["wave_mean"])) < 0.2, st
    lg = s["books"]["h24"]["arms"]["nn"]["long"]
    assert abs(lg["raw_mean"] - (-50.0 + lg["wave_mean"])) < 0.2, lg
    txt = W.report(s)
    assert "| `h24` | 24 | nn | short | 6 |" in txt and "Рынок окна" in txt
    print(f"ok  сквозной: растущий рынок (волна {st['wave_mean']:+.1f}), шорт "
          f"+200 в кассе → {st['raw_mean']:+.1f} сырым; лонг −50 → {lg['raw_mean']:+.1f}")


if __name__ == "__main__":
    test_wave_and_raw_outcome()
    test_run_end_to_end_with_fake_books()
    print("\nвсе 2 проверки прошли")
