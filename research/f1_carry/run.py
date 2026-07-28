#!/usr/bin/env python3
"""
F1 — книга carry и разложение её PnL. Прогон.

Спека 04, этап F1. Отвечает на посылки §8.1 и **не доходит ни до
издержек, ни до бэктеста**: если ход цены съедает начисления, дальше
идти незачем, и узнать это надо первым прогоном.

Протокол одной даты ребаланса `t`
---------------------------------

    │── окно оценки ставки k ──│── удержание h ──│
                               ↑ t

- оценка — минус средняя суточная ставка за `[t−k, t)`, §3.2 спеки;
- книга — верхняя доля `w` в лонг, нижняя в шорт, деньги поровну;
- форвард цены — сумма побарных доходностей за `[t, t+h)`;
- форвард начислений — сумма ставок, начисленных за `[t, t+h)`.

Граница проходит ровно по `t` с обеих сторон. Ставка, начисленная **в**
момент `t`, принадлежит удержанию, а не окну оценки: она объявляется
заранее и известна на входе, но получает её тот, кто держит позицию
после `t`. Ошибка на одно начисление здесь ничем себя не выдаёт — она
просто добавляет книге доход, которого та не получала.

Цена и начисления считаются по РАЗНЫМ источникам
------------------------------------------------

Ставки — только площадка исполнения (Bybit): подменять их запрещено
прямо. Цены — архив Binance через хранилище A2, потому что длинная
история есть только там, а отношение цен между площадками расходится
несопоставимо меньше, чем ставки (замер A1, раздел 4).

Расхождение цен между площадками в результат всё же входит, и это
**известная неточность, а не недосмотр**: реальная позиция на Bybit
получит свой ход цены, слегка отличный от нашего. Величина ограничена
арбитражем между площадками и мала против измеряемых десятков базисных
пунктов; при переходе к фазе B её придётся снять заново.

    python3 run.py --interval 1m
    python3 run.py --interval 15m --funding-venue binance   # только смоук
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r1_factor"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))
sys.path.insert(0, os.path.dirname(RESEARCH))

import carry as CY           # noqa: E402
import factor as FA          # noqa: E402
import series as S           # noqa: E402
import pairs as P            # noqa: E402
from research.common import funding_series as FS   # noqa: E402

STEP = "1h"                  # тот же шаг, что в A4/R1/R2
BARS_PER_DAY = 24

# Сетка §4 спеки 04. Объявлена до прогона и НЕ РАСШИРЯЕТСЯ.
KS = (7, 14)                 # окно оценки ставки, дни
HS = (5, 10)                 # удержание, дни
WIDTHS = {"decile": 0.10, "quintile": 0.20}

GRID_START = "2022-07-01"    # раньше сечение вырождается: §3.1 спеки
GRID_END = "2026-06-01"
REBALANCE_STEP_DAYS = 1
CHUNK_DAYS = 90

MIN_ASSETS = 30              # сечение тоньше — дециль вырождается в 3 имени
MIN_FORWARD_BARS = 1
MAX_DROPPED_WEIGHT = 0.05    # выше — разложение описывает не ту книгу


def rebalance_dates(start, end, step_days):
    t, last = date.fromisoformat(start), date.fromisoformat(end)
    while t <= last:
        yield t.isoformat()
        t += timedelta(days=step_days)


def forward_price(R, i_t, i_end):
    """Сумма побарных доходностей за `[i_t, i_end)` по каждому активу.

    Побарная сумма, а не разность цен «конец минус начало». Разница
    существенна для актива, переставшего торговаться внутри окна:
    разность цен приписала бы ему движение за всё окно, хотя половину
    этого времени его цены не существовало. Возвращается и число баров
    — актив без единого бара наблюдения не имеет и получает NaN, а не
    ноль.
    """
    e = R[i_t:i_end]
    m = ~np.isnan(e)
    n = m.sum(axis=0)
    s = np.where(m, e, 0.0).sum(axis=0)
    return np.where(n >= MIN_FORWARD_BARS, s, np.nan), n


def run_date(at, grid, PX, cols, live, funding):
    """Одно сечение: оценки по всем k, форварды по всем h, книга по сетке."""
    t_ms = FS.ms(at)
    i_t = int(np.searchsorted(grid, t_ms))
    keep = [i for i, c in enumerate(cols) if c in live]
    if len(keep) < MIN_ASSETS:
        return None
    names = [cols[i] for i in keep]
    R = FA.log_returns(PX[:, keep])
    if i_t - 1 >= len(R) or i_t < 1:
        return None

    scores, readings = {}, {}
    for k in KS:
        per_day, per_accrual = FS.funding_score(funding, names, at, k)
        scores[k] = per_day
        readings[k] = per_accrual

    fwd_price, fwd_fund, bars = {}, {}, {}
    for h in HS:
        end = (date.fromisoformat(at) + timedelta(days=h)).isoformat()
        i_end = min(len(R), int(np.searchsorted(grid, FS.ms(end))))
        p, nb = forward_price(R, i_t, i_end)
        fwd_price[h] = p
        bars[h] = nb
        fwd_fund[h] = np.array(
            [FS.accrued(funding, a, t_ms, FS.ms(end)) for a in names],
            dtype=np.float64)

    row = {"date": at, "assets": len(names), "cells": {}}
    for k in KS:
        for h in HS:
            for wname, width in WIDTHS.items():
                w, per_leg = CY.weights(scores[k], width)
                if per_leg < 1:
                    continue
                d = CY.decompose(w, fwd_price[h], fwd_fund[h])
                d["per_leg"] = per_leg
                row["cells"][f"k{k}_h{h}_{wname}"] = d

    # Диагностика прочтения «средней ставки»: суточная против ставки на
    # начисление. В отбор идёт первая; вторая нужна, чтобы разница между
    # прочтениями была видна числом, а не предполагалась малой.
    agree = {}
    for k in KS:
        a, b = scores[k], readings[k]
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() >= 3:
            ra = np.argsort(np.argsort(a[m]))
            rb = np.argsort(np.argsort(b[m]))
            agree[k] = float(np.corrcoef(ra, rb)[0, 1])
    row["reading_agreement"] = agree
    row["score_coverage"] = {k: float(np.isfinite(v).mean())
                             for k, v in scores.items()}
    row["_vectors"] = {
        "names": names,
        "score": {k: v.tolist() for k, v in scores.items()},
        "price": {h: v.tolist() for h, v in fwd_price.items()},
        "funding": {h: v.tolist() for h, v in fwd_fund.items()}}
    return row


def process_chunk(con, dates, liq, universe, funding, interval):
    t0 = (date.fromisoformat(dates[0]) - timedelta(days=max(KS))).isoformat()
    t1 = (date.fromisoformat(dates[-1])
          + timedelta(days=max(HS) + 1)).isoformat()

    live_by_date, wanted = {}, set()
    for at in dates:
        st = P.state_at(liq, universe, at)
        live = {a for a, s in st.items()
                if s["share_traded"] >= P.MIN_SHARE_TRADED}
        live_by_date[at] = live
        wanted |= live
    if not wanted:
        return []

    sym_of = {a: universe[a]["binance_symbol"] for a in wanted
              if universe[a].get("binance_symbol")}
    raw = S.load(con, sorted(sym_of.values()), t0, t1, step=STEP,
                 interval=interval)
    if not raw:
        return []
    by_asset = {a: raw[s] for a, s in sym_of.items() if s in raw}
    grid, cols, PX = FA.price_grid(by_asset, STEP, FS.ms(t0), FS.ms(t1))

    out = []
    for at in dates:
        r = run_date(at, grid, PX, cols, live_by_date[at], funding)
        if r:
            out.append(r)
    return out


def summarize(rows, hs):
    """Сводка по сетке: медианы слагаемых, доли, посылки §8.1.

    Всё считается по **непересекающимся** периодам: сечения идут
    ежедневно, а удержание длится `h` дней, поэтому соседние сечения
    делят данные. Урок A4 стоил месяца — превосходство ×4.7 целиком
    создавалось перекрытием окон.
    """
    dates = sorted(r["date"] for r in rows)
    by_date = {r["date"]: r for r in rows}
    cells = {}
    for name in sorted({c for r in rows for c in r["cells"]}):
        h = int(name.split("_h")[1].split("_")[0])
        keep = [by_date[d]["cells"][name] for d in dates[::h]
                if name in by_date[d]["cells"]]
        if not keep:
            continue
        g = [x["gross"] for x in keep]
        cells[name] = {
            "periods": len(keep),
            "funding": CY.robust([x["funding"] for x in keep]),
            "price": CY.robust([x["price"] for x in keep]),
            "gross": CY.robust(g),
            "gross_mean": CY.robust(g, "mean"),
            "positive_share": CY.share_positive(g),
            "tail_ratio": CY.tail_ratio(g),
            "dropped_weight": CY.robust([x["dropped_weight"] for x in keep]),
            "long": {f: CY.robust([x["long"][f] for x in keep])
                     for f in ("price", "funding", "gross")},
            "short": {f: CY.robust([x["short"][f] for x in keep])
                      for f in ("price", "funding", "gross")},
            "series": [round(float(x), 12) for x in g],
        }
    med_f = CY.robust([c["funding"] for c in cells.values()])
    med_g = CY.robust([c["gross"] for c in cells.values()])
    price_eats = sum(1 for c in cells.values()
                     if c["price"] is not None and c["funding"] is not None
                     and c["price"] + c["funding"] <= 0)
    return {
        "cells": cells,
        "grid": {
            "n_cells": len(cells),
            "funding_median": med_f,
            "gross_median": med_g,
            "cells_price_eats_carry": price_eats,
            "sections": len(rows),
            "assets_median": CY.robust([r["assets"] for r in rows]),
        },
        "premises": {
            "P1_funding_ge_30bp": (med_f is not None and med_f >= 30e-4),
            "P2_gross_positive": (med_g is not None and med_g > 0),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--start", default=GRID_START)
    ap.add_argument("--end", default=GRID_END)
    ap.add_argument("--funding-venue", default="bybit",
                    choices=("bybit", "binance"),
                    help="binance — только смоук-тест конвейера, деньги "
                         "считаются исключительно по площадке исполнения")
    ap.add_argument("--rerun", action="store_true")
    args = ap.parse_args()

    chunks = os.path.join(OUT, "chunks")
    vectors = os.path.join(OUT, "vectors")
    os.makedirs(chunks, exist_ok=True)
    os.makedirs(vectors, exist_ok=True)

    liq, universe = P.load_liquidity(args.interval)
    bybit = args.funding_venue == "bybit"
    directory = os.path.join(A1, "funding" if bybit else "funding_binance")
    funding = FS.load_funding(
        directory, universe, set(universe),
        symbol_field="bybit_symbol" if bybit else "binance_symbol")
    if funding is None:
        raise SystemExit(f"нет каталога {directory}")
    if len(funding) < FS.MIN_FUNDING_SYMBOLS:
        raise SystemExit(f"рядов funding нашлось {len(funding)} — это не "
                         f"покрытие, а его отсутствие")
    if args.funding_venue != "bybit":
        print("ВНИМАНИЕ: ставки взяты НЕ с площадки исполнения. Результат "
              "непригоден для вердикта, только для проверки конвейера.",
              file=sys.stderr, flush=True)
    print(f"funding: ряды у {len(funding)} активов", file=sys.stderr,
          flush=True)

    tag = f"{args.interval}_{args.funding_venue}"
    con = S.connect()
    dates = list(rebalance_dates(args.start, args.end, REBALANCE_STEP_DAYS))
    groups = [dates[i:i + CHUNK_DAYS]
              for i in range(0, len(dates), CHUNK_DAYS)]
    for g in groups:
        path = os.path.join(chunks, f"{tag}_{g[0]}.json")
        if os.path.exists(path) and not args.rerun:
            continue
        t = time.time()
        rows = process_chunk(con, g, liq, universe, funding, args.interval)
        vecs = {r["date"]: r.pop("_vectors") for r in rows if "_vectors" in r}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        if vecs:
            with open(os.path.join(vectors, f"{tag}_{g[0]}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(vecs, f)
        print(f"{g[0]}…{g[-1]}: сечений {len(rows)}, "
              f"{time.time() - t:.1f} с", file=sys.stderr, flush=True)

    rows = []
    for fn in sorted(os.listdir(chunks)):
        if fn.startswith(tag + "_") and fn.endswith(".json"):
            with open(os.path.join(chunks, fn), encoding="utf-8") as f:
                rows.extend(json.load(f))
    if not rows:
        raise SystemExit("сечений не получилось")

    s = summarize(rows, HS)
    s["config"] = {"interval": args.interval, "ks": list(KS), "hs": list(HS),
                   "widths": WIDTHS, "start": args.start, "end": args.end,
                   "funding_venue": args.funding_venue,
                   "funding_symbols": len(funding),
                   "declared_trials": len(KS) * len(HS) * len(WIDTHS)}
    s["reading_agreement"] = {
        str(k): CY.robust([r["reading_agreement"].get(str(k),
                                                      r["reading_agreement"]
                                                      .get(k))
                           for r in rows])
        for k in KS}
    dst = os.path.join(OUT, f"f1_{tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

    g = s["grid"]
    print(f"\nячеек {g['n_cells']}, сечений {g['sections']}, "
          f"активов в сечении {g['assets_median']:.0f}")
    print(f"медиана начислений {g['funding_median'] * 1e4:+.1f} б.п., "
          f"медиана брутто {g['gross_median'] * 1e4:+.1f} б.п.")
    print(f"посылки §8.1: П1 {'✓' if s['premises']['P1_funding_ge_30bp'] else '✗'}, "
          f"П2 {'✓' if s['premises']['P2_gross_positive'] else '✗'}")
    print(f"записано {dst}")


if __name__ == "__main__":
    main()
