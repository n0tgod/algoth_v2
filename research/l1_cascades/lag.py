#!/usr/bin/env python3
"""
L1 — известно ли в момент `t` то, что мы взяли на метке `t`.

Проверка перед спекой, а не после. Замер L1 показал превышение над
безусловным сносом на пятиминутном горизонте; если хоть одна из двух
величин, входящих в решение, на самом деле становится известна позже
метки, весь замер есть заглядывание в будущее, и превышение объясняется
им целиком.

Два места, и оба невидимы в результате
--------------------------------------

**1. Соглашение о метке набора `metrics`.** Строка со временем `t`
может описывать интервал, который на `t` уже закончился (тогда она
известна в `t`), а может — интервал, который с `t` только начинается
(тогда она известна в `t + 5 мин`). Различить можно, потому что в той
же строке лежит `sum_taker_long_short_vol_ratio` — отношение объёмов
агрессивных покупок к продажам, а это величина **за интервал**, и её
можно пересчитать из минутных свечей: `taker_buy_volume` и `volume`
лежат в архиве. Считаем отношение по интервалу ДО метки и по интервалу
ПОСЛЕ метки и смотрим, какое совпадает.

Открытый интерес — мгновенный снимок, а не интервальная величина, и
отношением объёмов он не проверяется. Он проверяется отдельно, третьим
замером: **изменение интереса обязано идти вместе с объёмом того
интервала, в котором оно произошло.** Если снимок сделан на начале
интервала строки, то `OI(t+5) − OI(t)` есть изменение за `[t, t+5)` и
связано с объёмом этого интервала; если на конце — за `[t+5, t+10)` и
связано с объёмом следующего. Связь сильная и односторонняя: позиции не
появляются и не исчезают без сделок.

**2. Правило сопоставления цены.** В зонде цена бралась как
`searchsorted(pt, mt, "right") - 1`, то есть последний бар, открытый не
позже метки. При точном совпадении меток (а они совпадают: сетка
`metrics` — ровно 00:00, 00:05, …) это бар, который в момент `t` ещё
**не закрылся**, и его закрытие наступает на минуту позже. Минута в
каскаде — не мелочь: именно в ней происходит основное движение, и
вход по цене на минуту позже завышает измеренный отскок.

    python3 lag.py
"""

import csv
import io
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")

sys.path.insert(0, RESEARCH)
from common.venue import fetch_binary                      # noqa: E402

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
UA = "l1-cascade-probe/1.0"
WORKERS = 8
STEP = 300.0                       # шаг сетки metrics, секунды

# Символы разного размера: соглашение о метке от инструмента зависеть не
# должно, и если зависит — это само по себе находка.
SAMPLE = ("BTCUSDT", "SOLUSDT", "ARBUSDT")
MONTHS = ("2024-07", "2025-03")

# Колонки минутного файла Binance.
K_OPEN, K_VOL, K_TAKER_BUY = 0, 5, 9


def days_of(mon):
    y, m = (int(x) for x in mon.split("-"))
    d, out = date(y, m, 1), []
    while d.month == m:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def read_zip_csv(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with z.open(z.namelist()[0]) as f:
            return list(csv.reader(io.TextIOWrapper(f, "utf-8")))


def load_metrics(sym, mon):
    """`(время, интерес, отношение объёмов)` по суточным файлам месяца."""
    def one(day):
        key = (f"data/futures/um/daily/metrics/{sym}/"
               f"{sym}-metrics-{day}.zip")
        try:
            raw = fetch_binary(f"{S3}/{key}", CACHE,
                               cache_key=f"m_{sym}_{day}", user_agent=UA)
        except Exception:
            return []
        rows = read_zip_csv(raw)
        if not rows:
            return []
        head = [c.strip() for c in rows[0]]
        try:
            it = head.index("create_time")
            ioi = head.index("sum_open_interest")
            ir = head.index("sum_taker_long_short_vol_ratio")
        except ValueError:
            return []
        out = []
        for r in rows[1:]:
            if len(r) <= max(it, ioi, ir):
                continue
            try:
                # Метка — UTC. Без явной зоны `fromisoformat` берёт
                # локальную, и на машине не в UTC вся сетка молча
                # съезжает на часы.
                t = datetime.fromisoformat(r[it].strip()).replace(
                    tzinfo=timezone.utc).timestamp()
                out.append((t, float(r[ioi]), float(r[ir])))
            except ValueError:
                continue
        return out

    got = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for part in ex.map(one, days_of(mon)):
            got += part
    got.sort()
    return got


def load_klines(sym, mon):
    """`(время открытия, объём, объём агрессивных покупок)`, минутные."""
    key = f"data/futures/um/monthly/klines/{sym}/1m/{sym}-1m-{mon}.zip"
    raw = fetch_binary(f"{S3}/{key}", CACHE, cache_key=f"k_{sym}_{mon}",
                       user_agent=UA)
    t, vol, buy = [], [], []
    for r in read_zip_csv(raw):
        if not r or not r[K_OPEN].strip().lstrip("-").isdigit():
            continue                     # заголовок появился в 2025 году
        try:
            t.append(int(r[K_OPEN]) / 1000.0)
            vol.append(float(r[K_VOL]))
            buy.append(float(r[K_TAKER_BUY]))
        except (ValueError, IndexError):
            continue
    o = np.argsort(t)
    return (np.array(t)[o], np.array(vol)[o], np.array(buy)[o])


def ratio_over(kt, vol, buy, t0, t1):
    """Отношение агрессивных покупок к продажам за `[t0, t1)`."""
    a, b = np.searchsorted(kt, t0, "left"), np.searchsorted(kt, t1, "left")
    if b <= a:
        return None
    v, bu = vol[a:b].sum(), buy[a:b].sum()
    sell = v - bu
    if sell <= 0 or bu <= 0:
        return None
    return bu / sell


def compare(sym, mon):
    met = load_metrics(sym, mon)
    if not met:
        return None
    kt, vol, buy = load_klines(sym, mon)
    dev_prev, dev_next, n = [], [], 0
    for t, _oi, r in met:
        if not np.isfinite(r) or r <= 0:
            continue
        rp = ratio_over(kt, vol, buy, t - STEP, t)
        rn = ratio_over(kt, vol, buy, t, t + STEP)
        if rp is None or rn is None:
            continue
        n += 1
        dev_prev.append(abs(np.log(r / rp)))
        dev_next.append(abs(np.log(r / rn)))
    if n < 100:
        return None
    dp, dn = np.array(dev_prev), np.array(dev_next)
    return {
        "symbol": sym, "month": mon, "rows": n,
        "dev_prev": float(np.median(dp)),
        "dev_next": float(np.median(dn)),
        "share_prev_closer": float((dp < dn).mean()),
        "exact_prev": float((dp < 1e-6).mean()),
        "exact_next": float((dn < 1e-6).mean()),
    }


def spearman(a, b):
    """Ранговая корреляция без scipy — связь заведомо не линейна."""
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


def oi_snapshot_side(sym, mon):
    """Снимок интереса — на начале интервала строки или на конце.

    Меряется связью |изменение интереса| с объёмом того интервала, в
    котором изменение по каждой из гипотез произошло.
    """
    met = load_metrics(sym, mon)
    if len(met) < 500:
        return None
    kt, vol, buy = load_klines(sym, mon)
    t = np.array([x[0] for x in met])
    oi = np.array([x[1] for x in met])
    step_ok = np.isclose(np.diff(t), STEP)          # только соседние метки
    d_oi = np.abs(np.diff(oi) / np.maximum(oi[:-1], 1e-12))
    d_oi = np.where(step_ok, d_oi, np.nan)

    def vol_over(t0, t1):
        a = np.searchsorted(kt, t0, "left")
        b = np.searchsorted(kt, t1, "left")
        return vol[a:b].sum() if b > a else np.nan

    # Профиль по сдвигам, а не два числа: объём автокоррелирован, и
    # положительная связь будет у любого соседнего интервала. Отвечает
    # на вопрос **положение пика**, а не сам факт связи.
    prof = {}
    for off in (-2, -1, 0, 1, 2):
        v = np.array([vol_over(x + off * STEP, x + (off + 1) * STEP)
                      for x in t[:-1]])
        prof[off] = spearman(d_oi, v)
    return {"symbol": sym, "month": mon, "points": int(np.isfinite(d_oi).sum()),
            "profile": prof,
            "corr_start": prof[0], "corr_end": prof[1]}


def price_shift(sym, mon):
    """Насколько цена «последнего открытого бара» отличается от закрытого.

    Мера того, что стоило старое правило сопоставления: доля меток, где
    два правила дают разную цену, и величина расхождения.
    """
    key = f"data/futures/um/monthly/klines/{sym}/1m/{sym}-1m-{mon}.zip"
    raw = fetch_binary(f"{S3}/{key}", CACHE, cache_key=f"k_{sym}_{mon}",
                       user_agent=UA)
    t, close = [], []
    for r in read_zip_csv(raw):
        if not r or not r[K_OPEN].strip().lstrip("-").isdigit():
            continue
        try:
            t.append(int(r[K_OPEN]) / 1000.0)
            close.append(float(r[4]))
        except (ValueError, IndexError):
            continue
    o = np.argsort(t)
    kt, kc = np.array(t)[o], np.array(close)[o]
    if len(kt) < 100:
        return None
    grid = np.arange(kt[0] - kt[0] % STEP + STEP, kt[-1], STEP)
    old = np.searchsorted(kt, grid, "right") - 1     # бар ещё не закрыт
    new = np.searchsorted(kt, grid, "left") - 1      # бар уже закрыт
    ok = (old >= 0) & (new >= 0)
    old, new = old[ok], new[ok]
    diff = np.abs(kc[old] / kc[new] - 1.0)
    return {"symbol": sym, "month": mon, "points": int(ok.sum()),
            "share_different": float((old != new).mean()),
            "median_bp": float(np.median(diff) * 1e4),
            "p95_bp": float(np.percentile(diff, 95) * 1e4)}


def main():
    print("1. СОГЛАШЕНИЕ О МЕТКЕ metrics")
    print("   отношение объёмов из строки против пересчёта по свечам")
    print("   'до' = интервал закончился на метке (известно в t)")
    print("   'после' = интервал с метки начинается (известно в t+5 мин)\n")
    print(f"{'символ':<10}{'месяц':<10}{'строк':>7}"
          f"{'откл. до':>11}{'откл. после':>13}"
          f"{'совпало до':>12}{'точно до':>10}{'точно после':>13}")
    verdict = []
    for sym in SAMPLE:
        for mon in MONTHS:
            r = compare(sym, mon)
            if not r:
                print(f"{sym:<10}{mon:<10}{'—':>7}")
                continue
            verdict.append(r)
            print(f"{r['symbol']:<10}{r['month']:<10}{r['rows']:>7}"
                  f"{r['dev_prev']:>11.4f}{r['dev_next']:>13.4f}"
                  f"{r['share_prev_closer']:>11.1%}"
                  f"{r['exact_prev']:>10.1%}{r['exact_next']:>13.1%}")

    if verdict:
        prev = float(np.mean([v["share_prev_closer"] for v in verdict]))
        print(f"\n   интервал ДО метки ближе в {prev:.1%} строк — "
              + ("метка закрывает интервал, заглядывания нет"
                 if prev > 0.9 else
                 "МЕТКА ОТКРЫВАЕТ ИНТЕРВАЛ, строка известна позже метки"
                 if prev < 0.1 else "НЕОДНОЗНАЧНО, разбираться"))

    print("\n\n2. СНИМОК ИНТЕРЕСА — НА НАЧАЛЕ ИЛИ НА КОНЦЕ ИНТЕРВАЛА СТРОКИ")
    print("   связь |изменения интереса| с объёмом интервала\n")
    print(f"{'символ':<10}{'месяц':<10}{'точек':>8}"
          + "".join(f"{'сдвиг ' + str(o):>12}" for o in (-2, -1, 0, 1, 2)))
    sides = []
    for sym in SAMPLE:
        for mon in MONTHS:
            r = oi_snapshot_side(sym, mon)
            if not r or r["corr_start"] is None or r["corr_end"] is None:
                continue
            sides.append(r)
            cells = "".join(
                f"{r['profile'][o]:>12.3f}" if r["profile"][o] is not None
                else f"{'—':>12}" for o in (-2, -1, 0, 1, 2))
            print(f"{r['symbol']:<10}{r['month']:<10}{r['points']:>8}{cells}")
    if sides:
        peak = {}
        for o in (-2, -1, 0, 1, 2):
            vals = [s["profile"][o] for s in sides
                    if s["profile"][o] is not None]
            peak[o] = float(np.mean(vals)) if vals else -1.0
        best = max(peak, key=peak.get)
        print(f"\n   пик на сдвиге {best:+d} "
              f"({peak[best]:.3f}); сдвиг 0 = снимок на начале интервала, "
              f"сдвиг +1 = на конце")
        st = float(np.mean([s["corr_start"] for s in sides]))
        en = float(np.mean([s["corr_end"] for s in sides]))
        print(f"\n   в среднем {st:.3f} против {en:.3f} — "
              + ("снимок на НАЧАЛЕ интервала, интерес на метке t известен в t"
                 if st > en else
                 "снимок на КОНЦЕ интервала, интерес на метке t известен "
                 "только в t+5 мин"))

    print("\n\n3. ПРАВИЛО СОПОСТАВЛЕНИЯ ЦЕНЫ")
    print("   старое правило берёт бар, который на метке ещё не закрылся\n")
    print(f"{'символ':<10}{'месяц':<10}{'меток':>9}"
          f"{'разошлось':>12}{'медиана, б.п.':>16}{'95-й, б.п.':>13}")
    for sym in SAMPLE:
        for mon in MONTHS:
            r = price_shift(sym, mon)
            if not r:
                continue
            print(f"{r['symbol']:<10}{r['month']:<10}{r['points']:>9}"
                  f"{r['share_different']:>11.1%}{r['median_bp']:>16.2f}"
                  f"{r['p95_bp']:>13.2f}")


if __name__ == "__main__":
    main()
