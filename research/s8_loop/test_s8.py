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


# ---------- цикл переобучения ----------

def _write_summaries(d, S=36, D=260, seed=5, start="2026-08-01-00"):
    """Синтетические сводки на диск: дельта ленты предсказывает
    следующий час — сигнал, который цикл обязан найти."""
    r = np.random.default_rng(seed)
    t0 = time.mktime(time.strptime(start, "%Y-%m-%d-%H"))
    sig = r.normal(0, 1, (S, D))
    close = np.empty((S, D))
    close[:, 0] = 100.0
    # Сила сигнала выбрана правдоподобной (IC ~0.2, не 0.5): шум
    # проекции канарейки растёт вместе с настоящим сигналом (механизм
    # M2), и на перегретой синтетике канарейка кричала бы без течи.
    for t in range(1, D):
        close[:, t] = close[:, t - 1] * (
            1 + 0.004 * sig[:, t - 1] * 0.22
            + r.normal(0, 0.004, S))
    from datetime import datetime as DT, timezone as TZ
    for si in range(S):
        sym = f"S{si:02d}USDT"
        os.makedirs(os.path.join(d, sym), exist_ok=True)
        fh = {}
        for t in range(D):
            hour = DT.fromtimestamp(t0 + t * 3600, TZ.utc)\
                .strftime("%Y-%m-%d-%H")
            day = hour[:10]
            buy = 1e6 * (1 + 0.4 * np.tanh(sig[si, t]))
            sell = 2e6 - buy
            row = {"hour": hour, "n_snap": 3600,
                   "mid_close": round(close[si, t], 6),
                   "mid_high": round(close[si, t] * 1.002, 6),
                   "mid_low": round(close[si, t] * 0.998, 6),
                   "spread_bp": 5.0, "upd": 100.0, "reach_bp": 60.0,
                   "best_b": 1e4, "best_a": 1e4,
                   "big_med": 1e5, "big_max": 2e5,
                   "n_trades": 500, "buy": round(buy, 2),
                   "sell": round(sell, 2),
                   "vol_max_1s": 1e4, "traded_secs": 1800,
                   "depth_eat_b": 2e5, "depth_eat_a": 2e5}
            for w in BANDS:
                row[f"bq_b{w}"] = 1e5
                row[f"bq_a{w}"] = 1e5
                row[f"cov_b{w}"] = 1.0
                row[f"cov_a{w}"] = 1.0
            f = fh.get(day)
            if f is None:
                f = fh[day] = open(os.path.join(d, sym, day + ".jsonl"),
                                   "a", encoding="utf-8")
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        for f in fh.values():
            f.close()


def test_train_cycle_end_to_end():
    import train as T

    orig_fit = T.gbm.fit
    T.gbm.fit = lambda x, y, seed: orig_fit(x, y, seed, n_trees=25)
    try:
        d = tempfile.mkdtemp()
        sd = os.path.join(d, "summary")
        _write_summaries(sd, D=260)
        T.MODEL_DIR = os.path.join(d, "model")
        ok = T.cycle(sd, lambda m: None, book_root=None)
        check("цикл прошёл", ok)
        man = json.load(open(os.path.join(T.MODEL_DIR, "manifest.json")))
        check("манифест с версией и границей обучения",
              man["version"] == T.MODEL_VERSION
              and man["trained_upto"].startswith("2026-08-1"),
              str(man.get("trained_upto")))
        check("веса всех целей на месте",
              all(os.path.exists(os.path.join(
                  T.MODEL_DIR, f"weights_{t}.pkl")) for t in T.TARGETS))
        check("канарейка не кричит",
              man["canary_ic"] is not None
              and abs(man["canary_ic"]) < T.CANARY_STOP,
              str(man["canary_ic"]))

        # Второй цикл: дописываем сутки и ждём живой вневыборочный IC —
        # прежняя модель обязана поймать заложенный сигнал на часах,
        # которых не видела.
        _write_summaries(sd, D=300)   # те же зерно и старт: +40 час.
        ok2 = T.cycle(sd, lambda m: None, book_root=None)
        check("второй цикл прошёл", ok2)
        hist = [json.loads(x) for x in
                open(os.path.join(T.MODEL_DIR, "ic_history.jsonl"))]
        f1 = [h for h in hist if h["target"] == "fwd_1h"]
        check("живой IC записан", len(f1) == 1, str(hist))
        check(f"заложенный сигнал пойман вне выборки "
              f"(IC {f1[0]['median_ic']:+.3f})",
              f1[0]["median_ic"] > 0.1, str(f1))
    finally:
        T.gbm.fit = orig_fit


def test_load_matrices_grid_is_continuous():
    import train as T

    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "AAA"))
    rows = [{"hour": "2026-08-01-00", "mid_close": 1.0, "n_snap": 3600},
            {"hour": "2026-08-01-05", "mid_close": 2.0, "n_snap": 3600}]
    with open(os.path.join(d, "AAA", "2026-08-01.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    mats, syms, grid = T.load_matrices(d)
    check("сетка часов непрерывна (дыра — колонка NaN)",
          len(grid) == 6 and np.isnan(mats["mid_close"][0, 2]),
          str(grid))
    check("края на месте", mats["mid_close"][0, 0] == 1.0
          and mats["mid_close"][0, 5] == 2.0)


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
    print("цикл переобучения")
    test_load_matrices_grid_is_continuous()
    test_train_cycle_end_to_end()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
