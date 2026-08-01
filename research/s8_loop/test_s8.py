#!/usr/bin/env python3
"""
Тесты S8.1. Главные — заглядывание (один тест на ВСЕ признаки, правило
M1) и правильность пути (MFE/MAE): на них стоит вся геометрия сделок,
и ошибка в них была бы невидима в результате.

    python3 research/s8_loop/test_s8.py
"""

import json
import os
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bookfeat as FB                                      # noqa: E402
import summary as SM                                       # noqa: E402
from book import BANDS                                     # noqa: E402

FAILED = []
rng = np.random.default_rng(20260801)


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


# ---------- сводка часа ----------

def _snap(mid, reach_bp, t, big=1000.0):
    r = {"t": t, "bid": mid - 0.5, "ask": mid + 0.5,
         "bid_sz": 10.0, "ask_sz": 12.0, "upd": 7,
         "reach_b": reach_bp, "reach_a": reach_bp,
         "b": [[mid - 0.5, big / mid]], "a": [[mid + 0.5, 8.0]]}
    for w in BANDS:
        r[f"bq{w}"] = 100.0 * (1 + w * 1000)
        r[f"aq{w}"] = 90.0 * (1 + w * 1000)
    return r


def test_summary_censors_bands_by_reach():
    # Охват ±4 б.п. — как у BTC: самая узкая полоса требует пяти.
    rows = [_snap(1000.0, 4.0, i) for i in range(10)]
    out = SM.summarize_hour(rows, [])
    check("узкая полоса цензурирована охватом",
          out["bq_b0.0005"] is None and out["cov_b0.0005"] == 0.0,
          str(out["bq_b0.0005"]))
    rows = [_snap(1000.0, 60.0, i) for i in range(10)]
    out = SM.summarize_hour(rows, [])
    check("при охвате 60 б.п. измеримы полосы до ±0.5 %",
          out["bq_b0.005"] is not None and out["cov_b0.005"] == 1.0,
          str(out))
    check("охват и спред посчитаны",
          abs(out["reach_bp"] - 60.0) < 1e-9 and out["spread_bp"] > 0)


def test_summary_tape():
    rows = [_snap(1000.0, 60.0, i) for i in range(5)]
    trades = [
        {"ts": 1_000_000, "side": 1, "p": 1000.0, "v": 2.0},
        {"ts": 1_001_400, "side": 1, "p": 1001.0, "v": 1.0},
        {"ts": 1_001_600, "side": -1, "p": 999.0, "v": 3.0},
    ]
    out = SM.summarize_hour(rows, trades)
    check("дельта ленты по сторонам",
          abs(out["buy"] - 3001.0) < 1e-6 and abs(out["sell"] - 2997.0)
          < 1e-6, f"{out['buy']} {out['sell']}")
    check("всплеск — максимум секунды, а не среднее",
          abs(out["vol_max_1s"] - (1001.0 + 2997.0)) < 1e-6,
          str(out["vol_max_1s"]))
    check("торгуемых секунд две", out["traded_secs"] == 2,
          str(out["traded_secs"]))
    check("максимум цены пришёл из ленты",
          abs(out["mid_high"] - 1001.0) < 1e-9, str(out["mid_high"]))


def test_summary_roundtrip_through_store():
    """Синтетическая запись через настоящий Writer и read_hour."""
    from store import Writer
    d = tempfile.mkdtemp()
    w = Writer(d, log=lambda m: None)
    t0 = time.time() - 7200
    hour = Writer.hour(t0)
    for i in range(20):
        s = _snap(500.0, 30.0, t0 + i)
        w.write("book", "TST", s, ts=t0 + i)
        w.write("trades", "TST",
                {"ts": int((t0 + i) * 1000), "side": 1 if i % 2 else -1,
                 "p": 500.0, "v": 1.0}, ts=t0 + i)
    w.close()
    from store import read_hour
    out = SM.summarize_hour(
        read_hour(os.path.join(d, "book", "TST"), hour),
        read_hour(os.path.join(d, "trades", "TST"), hour))
    check("сквозной прогон через хранилище",
          out is not None and out["n_snap"] == 20 and out["n_trades"] == 20,
          str(out))


def test_run_resumes_by_content():
    """Возобновление — по содержимому дневного файла (урок L2)."""
    from store import Writer
    d = tempfile.mkdtemp()
    w = Writer(d, log=lambda m: None)
    t0 = time.time() - 7200
    for i in range(5):
        w.write("book", "AAA", _snap(10.0, 30.0, t0 + i), ts=t0 + i)
    w.close()
    outd = os.path.join(d, "summary")
    n1 = SM.run(d, outd, None, lambda m: None)
    n2 = SM.run(d, outd, None, lambda m: None)
    check("час посчитан один раз", n1 == 1 and n2 == 0, f"{n1} {n2}")
    day = Writer.hour(t0)[:10]
    with open(os.path.join(outd, "AAA", day + ".jsonl")) as f:
        rows = [json.loads(x) for x in f]
    check("строка сводки одна и с часом", len(rows) == 1
          and rows[0]["hour"] == Writer.hour(t0), str(rows))


# ---------- признаки и цели ----------

def synth_summary(S=40, D=600, seed=3):
    r = np.random.default_rng(seed)
    f = r.normal(0, 0.004, D)
    rets = f[None, :] + r.normal(0, 0.006, (S, D))
    close = 100 * np.cumprod(1 + rets, axis=1)
    high = close * (1 + np.abs(r.normal(0, 0.002, (S, D))))
    low = close * (1 - np.abs(r.normal(0, 0.002, (S, D))))
    s = {"mid_close": close, "mid_high": high, "mid_low": low,
         "n_snap": np.full((S, D), 3600.0),
         "spread_bp": np.abs(r.normal(5, 1, (S, D))),
         "upd": np.abs(r.normal(100, 10, (S, D))),
         "best_b": np.abs(r.normal(1e4, 1e3, (S, D))),
         "best_a": np.abs(r.normal(1e4, 1e3, (S, D))),
         "big_med": np.abs(r.normal(1e5, 1e4, (S, D))),
         "big_max": np.abs(r.normal(2e5, 2e4, (S, D))),
         "buy": np.abs(r.normal(1e6, 1e5, (S, D))),
         "sell": np.abs(r.normal(1e6, 1e5, (S, D))),
         "vol_max_1s": np.abs(r.normal(1e4, 1e3, (S, D))),
         "traded_secs": np.full((S, D), 1800.0),
         "depth_eat_b": np.abs(r.normal(2e5, 1e4, (S, D))),
         "depth_eat_a": np.abs(r.normal(2e5, 1e4, (S, D)))}
    for w in BANDS:
        s[f"bq_b{w}"] = np.abs(r.normal(1e5, 1e4, (S, D)))
        s[f"bq_a{w}"] = np.abs(r.normal(1e5, 1e4, (S, D)))
    return s


def _mutate_after(s, t0, seed=9):
    r = np.random.default_rng(seed)
    out = {}
    for k, v in s.items():
        v2 = v.copy()
        v2[:, t0 + 1:] = np.abs(r.normal(50, 10, v2[:, t0 + 1:].shape))
        out[k] = v2
    return out


def test_no_lookahead_any_feature():
    s = synth_summary()
    t0 = 400
    a, _, _ = FB.feature_pack(s)
    b, _, _ = FB.feature_pack(_mutate_after(s, t0))
    for name in sorted(a):
        same = np.allclose(a[name][:, :t0 + 1], b[name][:, :t0 + 1],
                           equal_nan=True)
        check(f"будущее не трогает прошлое: {name}", same, name)
    s2 = {k: v.copy() for k, v in s.items()}
    s2["mid_close"][:, t0 - 5] *= 1.3
    c, _, _ = FB.feature_pack(s2)
    check("тест кусается",
          not np.allclose(a["ret_4h"][:, :t0 + 1], c["ret_4h"][:, :t0 + 1],
                          equal_nan=True))


def test_forward_path_exact():
    close = np.full((1, 10), 100.0)
    high = np.full((1, 10), 100.0)
    low = np.full((1, 10), 100.0)
    high[0, 4] = 103.0        # +300 б.п. в час 4
    low[0, 5] = 96.0          # −400 б.п. в час 5
    mfe, mae = FB.forward_path(close, high, low, h=4)
    # от часа 2 форвард накрывает часы 3..6: максимум 103, минимум 96
    check("MFE точен", abs(mfe[0, 2] - 300.0) < 1e-9, str(mfe[0, 2]))
    check("MAE точен от часа 2", abs(mae[0, 2] + 400.0) < 1e-9,
          str(mae[0, 2]))
    check("конец ряда — NaN, а не обрывок пути",
          np.isnan(mfe[0, -4:]).all(), str(mfe[0, -4:]))
    hole = high.copy()
    hole[0, 4] = np.nan
    mfe2, _ = FB.forward_path(close, hole, low, h=4)
    check("дыра внутри горизонта не рождает цели",
          np.isnan(mfe2[0, 2]), str(mfe2[0, 2]))


def test_eligibility_floor():
    s = synth_summary(S=35, D=300)
    s["n_snap"][3, :] = 100.0          # книга писалась три минуты в час
    _, r, elig = FB.feature_pack(s)
    check("недописанный час — не сечение", not elig[3].any())
    check("остальные в сечении", elig[0].sum() > 250)


def test_targets_shapes_and_direction():
    s = synth_summary(S=35, D=400)
    f, r, elig = FB.feature_pack(s)
    t = FB.target_pack(s, r, elig, f["beta"])
    check("цели всех горизонтов на месте",
          sorted(t) == sorted([f"{k}_{h}h" for k in ("fwd", "mfe", "mae")
                               for h in FB.HORIZONS]), str(sorted(t)))
    ok = np.isfinite(t["mfe_4h"]) & np.isfinite(t["mae_4h"])
    # MFE бывает отрицательным (цена ни разу не поднялась выше входа),
    # MAE — положительным; настоящий инвариант пути: максимум не ниже
    # минимума.
    check("MFE ≥ MAE там, где оба есть",
          (t["mfe_4h"][ok] >= t["mae_4h"][ok] - 1e-9).all())


def main():
    print("сводка часа")
    test_summary_censors_bands_by_reach()
    test_summary_tape()
    test_summary_roundtrip_through_store()
    test_run_resumes_by_content()
    print("заглядывание")
    test_no_lookahead_any_feature()
    print("путь")
    test_forward_path_exact()
    print("сечение и цели")
    test_eligibility_floor()
    test_targets_shapes_and_direction()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
