#!/usr/bin/env python3
"""
L2 — открытый интерес площадки исполнения и проверка её соглашения о метке.

Спека 06, §7.6 и §9.1. Вся подпись каскада измерена на Binance, а
торговать придётся на Bybit. Два вопроса, и оба обязаны быть закрыты до
дорогой части:

1. **Какое у Bybit соглашение о метке.** Для Binance это выяснено
   замером, а не документацией: строка `metrics` с меткой `t` описывает
   интервал `[t, t+5)` и завершена только в `t+5` (`l1_cascades/lag.py`).
   У Bybit собственный эндпоинт, и соглашение может быть другим. Ошибка
   здесь стоит ровно того же — заглядывания в будущее, невидимого в
   результате.
2. **Насколько глубока история.** Эндпоинт открытого интереса Bybit
   ограничен по глубине, и величина ограничения — предмет замера, а не
   предположения. От неё зависит, на каком периоде вообще возможно
   сравнение площадок.

Что проверяется и чем
---------------------

Соглашение о метке — тем же способом, что сработал на Binance:
**изменение интереса обязано идти вместе с объёмом того интервала, в
котором произошло.** Профиль связи считается по сдвигам −2…+2, и
положение пика отвечает на вопрос. Пик на 0 означает снимок на начале
интервала (известен на метке), пик на +1 — на конце (известен на метке
плюс шаг).

Сравнение площадок (§9.1) делается на **выборке символов, а не на всём
универсуме**: критерий требует доли общих событий, и для доли выборка
достаточна. Полный обход Bybit оправдан только если площадка станет
основным источником, а этого спека не предполагает.

    .venv/bin/python research/l2_data/oi_bybit.py --probe
    .venv/bin/python research/l2_data/oi_bybit.py --collect --sample 40
"""

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
A1 = os.path.join(RESEARCH, "a1_universe")
OUT = os.path.join(HERE, "out")
SERIES = os.path.join(OUT, "oi_bybit")

sys.path.insert(0, RESEARCH)
sys.path.insert(0, A1)
from bybit_api import CATEGORY, api_get                     # noqa: E402

INTERVAL = "5min"             # шаг сетки Binance `metrics` — сравнивать так
LIMIT = 200                   # максимум записей на ответ
PAUSE_S = 0.05
PROBE_SYMBOLS = ("BTCUSDT", "SOLUSDT", "ARBUSDT")
PROBE_DAYS = 20               # сколько суток берётся на проверку метки
STEP_SEC = 300


def oi_page(symbol, end_ms, interval=INTERVAL):
    """Страница интереса, назад во времени от `end_ms`."""
    params = {"category": CATEGORY, "symbol": symbol,
              "intervalTime": interval, "limit": LIMIT}
    if end_ms:
        params["endTime"] = end_ms
    res = api_get("/v5/market/open-interest", params,
                  f"oi_{symbol}_{interval}_{end_ms or 0}")
    rows = []
    for r in res.get("list", []):
        try:
            rows.append((int(r["timestamp"]), float(r["openInterest"])))
        except (KeyError, ValueError):
            continue
    return rows


def oi_history(symbol, pages_max, interval=INTERVAL):
    """История назад во времени, пока эндпоинт отдаёт. Глубина — замер."""
    rows, end_ms, seen = [], None, 0
    for _ in range(pages_max):
        batch = oi_page(symbol, end_ms, interval)
        if not batch:
            break
        rows += batch
        oldest = min(t for t, _ in batch)
        if end_ms is not None and oldest >= end_ms:
            break
        end_ms = oldest - 1
        if len(batch) < LIMIT:
            break
        seen += 1
        time.sleep(PAUSE_S)
    rows = sorted(set(rows))
    return rows


def klines(symbol, start_ms, end_ms):
    """Пятиминутные бары Bybit: `(время_начала_мс, объём)`."""
    out, cursor = [], end_ms
    for _ in range(60):
        res = api_get("/v5/market/kline",
                      {"category": CATEGORY, "symbol": symbol,
                       "interval": "5", "start": start_ms, "end": cursor,
                       "limit": 1000},
                      f"kl_{symbol}_{cursor}")
        rows = res.get("list", [])
        if not rows:
            break
        for r in rows:
            try:
                out.append((int(r[0]), float(r[5])))
            except (IndexError, ValueError):
                continue
        oldest = min(int(r[0]) for r in rows)
        if oldest <= start_ms or len(rows) < 1000:
            break
        cursor = oldest - 1
        time.sleep(PAUSE_S)
    return sorted(set(out))


def spearman(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 100:
        return None
    ra = np.empty(ok.sum())
    rb = np.empty(ok.sum())
    ra[np.argsort(a[ok])] = np.arange(ok.sum())
    rb[np.argsort(b[ok])] = np.arange(ok.sum())
    ra -= ra.mean()
    rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else None


def label_profile(symbol, oi_rows):
    """Профиль связи изменения интереса с объёмом по сдвигам −2…+2."""
    if len(oi_rows) < 500:
        return None
    t = np.array([r[0] for r in oi_rows], dtype=np.int64)
    v = np.array([r[1] for r in oi_rows], dtype=np.float64)
    kl = klines(symbol, int(t[0]) - 2 * STEP_SEC * 1000,
                int(t[-1]) + 2 * STEP_SEC * 1000)
    if len(kl) < 500:
        return None
    kt = np.array([r[0] for r in kl], dtype=np.int64)
    kv = np.array([r[1] for r in kl], dtype=np.float64)

    step_ok = np.diff(t) == STEP_SEC * 1000
    d_oi = np.abs(np.diff(v) / np.maximum(v[:-1], 1e-12))
    d_oi = np.where(step_ok, d_oi, np.nan)

    prof = {}
    for off in (-2, -1, 0, 1, 2):
        want = t[:-1] + off * STEP_SEC * 1000
        idx = np.searchsorted(kt, want, "left")
        ok = (idx < len(kt)) & (kt[np.clip(idx, 0, len(kt) - 1)] == want)
        vol = np.where(ok, kv[np.clip(idx, 0, len(kt) - 1)], np.nan)
        prof[off] = spearman(d_oi, vol)
    return {"symbol": symbol, "points": int(np.isfinite(d_oi).sum()),
            "profile": prof}


def probe(args):
    print("1. ГЛУБИНА ИСТОРИИ ОТКРЫТОГО ИНТЕРЕСА BYBIT\n")
    print(f"{'символ':<10}{'шаг':>8}{'точек':>9}{'самая ранняя метка':>24}"
          f"{'суток':>8}")
    depth = {}
    for sym in PROBE_SYMBOLS:
        for interval in (INTERVAL, "1h"):
            rows = oi_history(sym, args.pages, interval)
            if not rows:
                print(f"{sym:<10}{interval:>8}{'—':>9}")
                continue
            first = rows[0][0] / 1000
            days = (rows[-1][0] - rows[0][0]) / 86_400_000
            depth[f"{sym}_{interval}"] = {"points": len(rows),
                                          "first_ms": rows[0][0],
                                          "last_ms": rows[-1][0],
                                          "days": round(days, 1)}
            import datetime as dt
            stamp = dt.datetime.fromtimestamp(
                first, dt.timezone.utc).isoformat()
            print(f"{sym:<10}{interval:>8}{len(rows):>9}{stamp:>24}"
                  f"{days:>8.1f}")
    print("\n  глубина — предел эндпоинта, а не наш выбор; она задаёт "
          "период,\n  на котором вообще возможно сравнение площадок\n")

    print("\n2. СОГЛАШЕНИЕ О МЕТКЕ: связь изменения интереса с объёмом\n")
    print(f"{'символ':<10}{'точек':>8}"
          + "".join(f"{'сдвиг ' + str(o):>12}" for o in (-2, -1, 0, 1, 2)))
    profs = []
    for sym in PROBE_SYMBOLS:
        rows = oi_history(sym, max(2, PROBE_DAYS * 288 // LIMIT))
        p = label_profile(sym, rows)
        if not p:
            print(f"{sym:<10}{'—':>8}")
            continue
        profs.append(p)
        cells = "".join(f"{p['profile'][o]:>12.3f}"
                        if p["profile"][o] is not None else f"{'—':>12}"
                        for o in (-2, -1, 0, 1, 2))
        print(f"{sym:<10}{p['points']:>8}{cells}")
    if profs:
        peak = {}
        for o in (-2, -1, 0, 1, 2):
            vals = [p["profile"][o] for p in profs
                    if p["profile"][o] is not None]
            peak[o] = float(np.mean(vals)) if vals else -1.0
        best = max(peak, key=peak.get)
        print(f"\n  пик на сдвиге {best:+d} ({peak[best]:.3f})")
        print("  сдвиг 0 — снимок на начале интервала, метка известна в t")
        print("  сдвиг +1 — на конце, метка известна в t + шаг")
        print(f"\n  для сравнения, Binance: пик на +1 (0.557), "
              f"то есть строка известна в t+5")

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bybit_probe.json"), "w",
              encoding="utf-8") as f:
        json.dump({"depth": depth, "profiles": profs}, f,
                  ensure_ascii=False, indent=1,
                  default=lambda o: None)
    print(f"\nзаписано {os.path.join(OUT, 'bybit_probe.json')}")


def sample_symbols(n):
    """Выборка по размеру инструмента, а не первые по алфавиту.

    Берётся из манифеста сбора Binance: символы сортируются по
    медианному открытому интересу и прореживаются равномерно, чтобы
    выборка накрывала весь диапазон размеров. Сравнение площадок на
    одних мажорах ничего не сказало бы о хвосте универсума.
    """
    path = os.path.join(OUT, "oi_binance_manifest.json")
    if not os.path.exists(path):
        raise SystemExit("сначала oi_binance.py — выборка строится по его "
                         "манифесту")
    with open(path, encoding="utf-8") as f:
        man = json.load(f)["symbols"]
    have = [(v["median_oi_usd"], s) for s, v in man.items()
            if v.get("rows") and v.get("median_oi_usd")]
    have.sort()
    if len(have) <= n:
        return [s for _, s in have]
    step = len(have) / n
    return [have[int(i * step)][1] for i in range(n)]


def collect(args):
    os.makedirs(SERIES, exist_ok=True)
    syms = ([s.strip() for s in args.symbols.split(",") if s.strip()]
            if args.symbols else sample_symbols(args.sample))
    print(f"символов {len(syms)}", file=sys.stderr, flush=True)
    man_path = os.path.join(OUT, "oi_bybit_manifest.json")
    man = {}
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f).get("symbols", {})
    for i, sym in enumerate(syms, 1):
        dst = os.path.join(SERIES, f"{sym}.npz")
        if os.path.exists(dst) and sym in man:
            continue
        t0 = time.time()
        try:
            rows = oi_history(sym, args.pages)
        except Exception as e:                            # noqa: BLE001
            man[sym] = {"rows": 0, "error": str(e)[:120]}
            print(f"[{i}/{len(syms)}] {sym}: {str(e)[:80]}",
                  file=sys.stderr, flush=True)
            continue
        if rows:
            np.savez_compressed(
                dst + ".tmp.npz",
                t=np.array([r[0] for r in rows], dtype=np.int64),
                oi=np.array([r[1] for r in rows], dtype=np.float32))
            os.replace(dst + ".tmp.npz", dst)
        man[sym] = {"rows": len(rows),
                    "first_ms": rows[0][0] if rows else None,
                    "last_ms": rows[-1][0] if rows else None,
                    "seconds": round(time.time() - t0, 1)}
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump({"symbols": man}, f, ensure_ascii=False)
        print(f"[{i}/{len(syms)}] {sym}: точек {len(rows)}, "
              f"{man[sym]['seconds']} с", file=sys.stderr, flush=True)
    ok = [v for v in man.values() if v.get("rows")]
    print(f"\nсимволов с рядом {len(ok)} из {len(man)}, "
          f"точек {sum(v['rows'] for v in ok):,}")
    print(f"манифест {man_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--pages", type=int, default=4000,
                    help="предел страниц на символ — страховка от петли")
    a = ap.parse_args()
    if a.probe:
        probe(a)
    elif a.collect:
        collect(a)
    else:
        ap.error("нужен --probe или --collect")


if __name__ == "__main__":
    main()
