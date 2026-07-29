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


def oi_page(symbol, end_ms, interval=INTERVAL, start_ms=None):
    """Страница интереса, назад во времени от `end_ms`."""
    params = {"category": CATEGORY, "symbol": symbol,
              "intervalTime": interval, "limit": LIMIT}
    if end_ms:
        params["endTime"] = end_ms
    if start_ms:
        params["startTime"] = start_ms
    res = api_get("/v5/market/open-interest", params,
                  f"oi_{symbol}_{interval}_{start_ms or 0}_{end_ms or 0}")
    rows = []
    for r in res.get("list", []):
        try:
            rows.append((int(r["timestamp"]), float(r["openInterest"])))
        except (KeyError, ValueError):
            continue
    return rows


def has_data_at(symbol, days_ago, interval=INTERVAL, now_ms=None):
    """Есть ли данные примерно `days_ago` суток назад. Один запрос."""
    now_ms = now_ms or int(time.time() * 1000)
    end = now_ms - days_ago * 86_400_000
    return bool(oi_page(symbol, end, interval, start_ms=end - 86_400_000))


def retention_days(symbol, interval=INTERVAL, now_ms=None):
    """Глубина истории — лестницей и уточнением, а не обходом назад.

    Первая версия шла страницами по 200 точек: на два с половиной года
    пятиминутных данных это больше тысячи запросов на символ, и
    выглядело как зависание. Глубину незачем обходить — её надо
    **нащупать**: десяток пробных запросов вместо тысячи.
    """
    now_ms = now_ms or int(time.time() * 1000)
    ladder = (1, 7, 30, 90, 180, 365, 545, 730, 1095, 1460, 1825)
    ok, bad = 0, None
    for d in ladder:
        if has_data_at(symbol, d, interval, now_ms):
            ok = d
        else:
            bad = d
            break
        time.sleep(PAUSE_S)
    if bad is None:
        return ok, None          # глубже лестницы не проверяли
    lo, hi = ok, bad
    while hi - lo > max(3, lo // 20):      # уточнение до нескольких суток
        mid = (lo + hi) // 2
        if has_data_at(symbol, mid, interval, now_ms):
            lo = mid
        else:
            hi = mid
        time.sleep(PAUSE_S)
    return lo, hi


def oi_history(symbol, pages_max, interval=INTERVAL, since_days=None,
               log_every=0):
    """История назад во времени. `since_days` ограничивает глубину."""
    now_ms = int(time.time() * 1000)
    floor_ms = (now_ms - since_days * 86_400_000) if since_days else None
    rows, end_ms = [], None
    for page in range(pages_max):
        batch = oi_page(symbol, end_ms, interval)
        if not batch:
            break
        rows += batch
        oldest = min(t for t, _ in batch)
        if floor_ms and oldest <= floor_ms:
            break
        if end_ms is not None and oldest >= end_ms:
            break
        end_ms = oldest - 1
        if len(batch) < LIMIT:
            break
        if log_every and (page + 1) % log_every == 0:
            print(f"    {symbol}: страниц {page + 1}, точек {len(rows)}",
                  file=sys.stderr, flush=True)
        time.sleep(PAUSE_S)
    return sorted(set(rows))


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
    """Обе проверки площадки. Пишет отчёт в `out/`, а не только в консоль.

    Отчёт файлом, а не выводом на экран, — правило проекта: прогон
    идёт на сервере, а обсуждается в другом месте, и пересказывать
    консоль руками значит терять числа.
    """
    import datetime as dt

    now_ms = int(time.time() * 1000)
    md = []
    w = md.append
    w("# L2 — площадка исполнения, проверка\n")
    w("## 1. Глубина истории открытого интереса Bybit\n")
    w("Нащупывается пробными запросами, а не обходом назад: глубина — "
      "предел эндпоинта, а не наш выбор, и она задаёт период, на "
      "котором вообще возможно сравнение площадок.\n")
    w("| Символ | Шаг | Данные есть до | Суток назад | Дальше пусто с |")
    w("|---|---|---|---|---|")
    depth = {}
    for sym in PROBE_SYMBOLS:
        for interval in (INTERVAL, "1h"):
            print(f"  … {sym} {interval}", file=sys.stderr, flush=True)
            lo, hi = retention_days(sym, interval, now_ms)
            edge = dt.datetime.fromtimestamp(
                (now_ms - lo * 86_400_000) / 1000,
                dt.timezone.utc).date().isoformat()
            depth[f"{sym}_{interval}"] = {"deep_days": lo,
                                          "empty_from_days": hi}
            w(f"| {sym} | {interval} | {edge} | {lo} | "
              f"{hi if hi else 'не найдено'} |")
    w("")
    w("## 2. Соглашение о метке\n")
    w("Изменение интереса обязано идти вместе с объёмом того интервала, "
      "в котором произошло. Положение пика отвечает на вопрос: сдвиг 0 — "
      "снимок на начале интервала, метка известна в `t`; сдвиг +1 — на "
      "конце, метка известна в `t` плюс шаг.\n")
    w("| Символ | Точек | " + " | ".join(f"сдвиг {o:+d}"
                                         for o in (-2, -1, 0, 1, 2)) + " |")
    w("|---|---|---|---|---|---|---|")
    profs = []
    for sym in PROBE_SYMBOLS:
        print(f"  … {sym} профиль", file=sys.stderr, flush=True)
        rows = oi_history(sym, max(2, PROBE_DAYS * 288 // LIMIT + 2),
                          since_days=PROBE_DAYS)
        p = label_profile(sym, rows)
        if not p:
            w(f"| {sym} | — | | | | | |")
            continue
        profs.append(p)
        cells = " | ".join(f"{p['profile'][o]:.3f}"
                           if p["profile"][o] is not None else "—"
                           for o in (-2, -1, 0, 1, 2))
        w(f"| {sym} | {p['points']} | {cells} |")
    w("")
    if profs:
        peak = {}
        for o in (-2, -1, 0, 1, 2):
            vals = [p["profile"][o] for p in profs
                    if p["profile"][o] is not None]
            peak[o] = float(np.mean(vals)) if vals else -1.0
        best = max(peak, key=peak.get)
        w(f"**Пик на сдвиге {best:+d}** ({peak[best]:.3f}).\n")
        w("Для сравнения, Binance: пик на **+1** (0.557), то есть строка "
          "`metrics` с меткой `t` завершена только в `t+5`, и момент "
          "решения сдвинут туда (`l1_cascades/lag.py`). Если у Bybit "
          "пик на 0 — правило момента решения там своё, и это надо "
          "учесть в L3, а не считать мелочью.\n")
    else:
        w("Профиль не построен — данных не хватило.\n")

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bybit_probe.json"), "w",
              encoding="utf-8") as f:
        json.dump({"depth": depth, "profiles": profs}, f,
                  ensure_ascii=False, indent=1, default=lambda o: None)
    text = "\n".join(md)
    dst = os.path.join(OUT, "L2-bybit-probe.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\nзаписано {dst}")


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
            rows = oi_history(sym, args.pages, since_days=args.since_days,
                              log_every=100)
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
        tmp = man_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"symbols": man}, f, ensure_ascii=False)
        os.replace(tmp, man_path)     # обрыв не оставляет обрезанный JSON
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
    ap.add_argument("--since-days", type=int, default=0,
                    help="глубина сбора в сутках; 0 — сколько отдаёт")
    a = ap.parse_args()
    if a.probe:
        probe(a)
    elif a.collect:
        collect(a)
    else:
        ap.error("нужен --probe или --collect")


if __name__ == "__main__":
    main()
