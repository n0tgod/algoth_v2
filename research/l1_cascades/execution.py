#!/usr/bin/env python3
"""
L1 — сколько стоит войти в момент каскада.

Третий и последний вопрос перед спекой. Первые два закрыты: строка
`metrics` известна только в `t+5` и вход сдвинут туда (`lag.py`),
наблюдения независимы (60 эпизодов на 128 событий строгого порога).
Остался тот, который в этом проекте уже один раз всё решил: **в момент
события ликвидность выедена**. Ровно это сделало стоп бесполезным в
сквизах S1 — цена проходила уровень разрывом, и заявка исполнялась не
там, где стоял уровень.

Разница между «каскад» и «обычная минута» в том и состоит, что
ближайшая глубина сметена: она и есть механизм события. Значит платить
за вход придётся больше обычного — вопрос только, насколько.

Чем меряем
----------

Набор `bookDepth` архива Binance: снимок раз в 30 секунд, нотионал,
стоящий в полосах ±1…5 % от середины, накопленный. Покупаем — едим
**сторону предложения** (`percentage = +1`), продаём — сторону спроса
(`-1`). Нужны только дни событий, это сотни мегабайт, а не терабайты.

Модель проскальзывания и её честная слабость
--------------------------------------------

Стакан внутри полосы 1 % считается равномерным по цене. Тогда заявка
на `S` долларов при глубине `N` в полосе проходит `1 % · S/N`, а
средняя цена исполнения хуже середины на **половину** этого:
`slip = 0.5 % · S/N`.

Приближение грубое и заведомо оптимистичное — настоящий стакан в
каскаде разрежен неравномерно, и ближние уровни выедены сильнее
дальних. Поэтому число читается как **нижняя граница издержки**, и
если гипотеза не выживает даже на нижней границе, направление закрыто
без тиковой симуляции. Тот же приём, что потолок рычагов в S1: сначала
самая дешёвая оценка, способная убить.

События строятся вызовом функций `probe.py`, а не копией правил
обнаружения: вторая копия расчёта в этом проекте запрещена.

    python3 execution.py
    python3 execution.py --cells 3x3 --sizes 10000,50000
"""

import argparse
import csv
import io
import json
import os
import sys
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")

sys.path.insert(0, HERE)
sys.path.insert(0, RESEARCH)
import probe as PR                                          # noqa: E402
from common.venue import fetch_binary                       # noqa: E402

S3 = PR.S3
UA = "l1-execution/1.0"
WORKERS = 8

# Ячейки, между которыми идёт выбор: мягкая мертва по величине, строгая
# бедна наблюдениями, середина — единственная, где сходится и то и другое.
CELLS = {"1x3": (0.01, 0.03), "2x3": (0.02, 0.03), "3x3": (0.03, 0.03)}
SIZES = (10_000, 50_000, 200_000)
EXIT_MIN = 15                     # горизонт, на котором величина максимальна
TOL_SEC = 60                      # допуск подбора снимка стакана
BAND = 0.01                       # полоса 1 % — та, которую съедает заявка


def day_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def load_depth(sym, day):
    """Снимки глубины за сутки: `(время, нотионал спроса, предложения)`."""
    key = (f"data/futures/um/daily/bookDepth/{sym}/"
           f"{sym}-bookDepth-{day}.zip")
    try:
        raw = fetch_binary(f"{S3}/{key}", CACHE, cache_key=f"bd_{sym}_{day}",
                           user_agent=UA)
    except Exception:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            rows = list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]),
                                                    "utf-8")))
    except (zipfile.BadZipFile, OSError):
        return None
    if len(rows) < 2:
        return None
    head = [c.strip() for c in rows[0]]
    try:
        it, ip = head.index("timestamp"), head.index("percentage")
        inn = head.index("notional")
    except ValueError:
        return None
    bid, ask = {}, {}
    for r in rows[1:]:
        if len(r) <= max(it, ip, inn):
            continue
        try:
            pct = int(float(r[ip]))
            if abs(pct) != 1:                 # нужна только полоса 1 %
                continue
            t = datetime.fromisoformat(r[it].strip()).replace(
                tzinfo=timezone.utc).timestamp()
            (bid if pct < 0 else ask)[t] = float(r[inn])
        except ValueError:
            continue
    keys = sorted(set(bid) & set(ask))
    if len(keys) < 100:
        return None
    t = np.array(keys, dtype=np.float64)
    return t, np.array([bid[k] for k in keys]), np.array([ask[k] for k in keys])


def at_moment(depth, when):
    """Последний снимок, сделанный не позже момента. Иначе — пусто."""
    t, bid, ask = depth
    i = int(np.searchsorted(t, when, "right")) - 1
    if i < 0 or when - t[i] > TOL_SEC:
        return None
    return float(bid[i]), float(ask[i])


def slip_bp(size, notional):
    """Проскальзывание в б.п. при равномерном стакане внутри полосы.

    При `size = notional` заявка съедает полосу целиком и величина
    равна 50 б.п. (половина от 1 %). Дальше формула — экстраполяция за
    пределы измеренного, и такие случаи считаются отдельно, а не
    подрезаются потолком: подрезка спрятала бы ровно тот случай, когда
    входить нельзя.
    """
    if not notional or notional <= 0:
        return None
    return 0.5 * BAND * 1e4 * size / notional


def collect_events(cells, start, end, symbols):
    """События по правилам `probe.py`, без второй копии обнаружения."""
    ev = defaultdict(list)
    for sym in symbols:
        m = PR.load_metrics(sym, start, end)
        p = PR.load_price(sym, start, end)
        if not m or not p:
            continue
        price, _ = PR.align(m[0], p[0], p[1], p[2], PR.LAG_MIN, "next_open")
        for name, (oi_drop, move) in cells.items():
            for e in PR.scan(sym, m[0], m[1], price, oi_drop, move):
                if e["down"]:
                    ev[name].append(e)
        print(f"{sym}: события собраны", file=sys.stderr, flush=True)
    return ev


def measure(events, sizes):
    """Глубина в момент входа и выхода против обычной для того же дня."""
    need = sorted({(e["symbol"], day_of(e["t"] + PR.LAG_MIN * 60))
                   for e in events})
    print(f"  символо-дней к загрузке: {len(need)} "
          f"(~{len(need) * 0.46:.0f} МБ)", file=sys.stderr, flush=True)
    depth = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for key, d in zip(need, ex.map(lambda k: load_depth(*k), need)):
            if d is not None:
                depth[key] = d

    rows = []
    for e in events:
        enter = e["t"] + PR.LAG_MIN * 60
        d = depth.get((e["symbol"], day_of(enter)))
        if d is None:
            continue
        now = at_moment(d, enter)
        if now is None:
            continue
        # Обычный уровень — медиана того же дня. Сравнение с другим днём
        # смешало бы выеденность стакана с изменением интереса к активу.
        norm_ask = float(np.median(d[2]))
        norm_bid = float(np.median(d[1]))
        out = at_moment(d, enter + EXIT_MIN * 60)
        rows.append({
            "symbol": e["symbol"], "t": e["t"],
            "ask_in": now[1], "bid_out": out[0] if out else None,
            "ask_ratio": now[1] / norm_ask if norm_ask > 0 else None,
            "bid_ratio": (out[0] / norm_bid
                          if out and norm_bid > 0 else None),
        })
    if not rows:
        return None

    def med(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return float(np.median(v)) if v else None

    res = {"events_matched": len(rows), "events_total": len(events),
           "ask_in": med("ask_in"), "bid_out": med("bid_out"),
           "ask_ratio": med("ask_ratio"), "bid_ratio": med("bid_ratio"),
           "cost": {}}
    for s in sizes:
        si = [slip_bp(s, r["ask_in"]) for r in rows if r["ask_in"]]
        so = [slip_bp(s, r["bid_out"]) for r in rows if r["bid_out"]]
        res["cost"][s] = {
            "slip_in_bp": float(np.median(si)) if si else None,
            "slip_out_bp": float(np.median(so)) if so else None,
            "slip_in_p90_bp": float(np.percentile(si, 90)) if si else None,
        }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PR.START)
    ap.add_argument("--end", default=PR.END)
    ap.add_argument("--symbols", default=",".join(PR.SAMPLE))
    ap.add_argument("--cells", default=",".join(CELLS))
    ap.add_argument("--sizes", default=",".join(str(s) for s in SIZES))
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    cells = {k: CELLS[k] for k in a.cells.split(",") if k in CELLS}
    sizes = [int(x) for x in a.sizes.split(",")]
    os.makedirs(OUT, exist_ok=True)

    ev = collect_events(cells, a.start, a.end, syms)
    res = {}
    for name in cells:
        print(f"\nячейка {name}: событий вниз {len(ev[name])}",
              file=sys.stderr, flush=True)
        r = measure(ev[name], sizes)
        if r:
            res[name] = r

    dst = os.path.join(OUT, "l1_execution.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"config": {"symbols": syms, "cells": cells,
                              "sizes": sizes, "exit_min": EXIT_MIN,
                              "band": BAND}, "cells": res},
                  f, ensure_ascii=False, indent=1)

    print("\nГЛУБИНА В МОМЕНТ ВХОДА, полоса 1 % от середины")
    print("доля от обычной — медиана того же дня; < 1 значит выедено\n")
    print(f"{'ячейка':<9}{'событий':>9}{'сопоставлено':>14}"
          f"{'предложение, $':>17}{'доля от обычной':>18}"
          f"{'спрос на выходе':>18}")
    for name, r in res.items():
        print(f"{name:<9}{r['events_total']:>9}{r['events_matched']:>14}"
              f"{r['ask_in']:>17,.0f}{r['ask_ratio']:>17.2f}"
              f"{r['bid_ratio']:>18.2f}")

    print("\nЦЕНА КРУГА: комиссия 11 б.п. плюс проскальзывание")
    print("проскальзывание по нижней границе — стакан считается ровным\n")
    print(f"{'ячейка':<9}{'размер, $':>11}{'вход, б.п.':>13}"
          f"{'выход, б.п.':>13}{'вход 90-й':>12}{'круг, б.п.':>12}")
    for name, r in res.items():
        for s in sizes:
            c = r["cost"][s]
            if c["slip_in_bp"] is None or c["slip_out_bp"] is None:
                continue
            total = 11.0 + c["slip_in_bp"] + c["slip_out_bp"]
            print(f"{name:<9}{s:>11,}{c['slip_in_bp']:>13.2f}"
                  f"{c['slip_out_bp']:>13.2f}{c['slip_in_p90_bp']:>12.2f}"
                  f"{total:>12.2f}")
    print(f"\nзаписано {dst}")


if __name__ == "__main__":
    main()
