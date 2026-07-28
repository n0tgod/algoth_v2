#!/usr/bin/env python3
"""
A3 — кандидаты в пары на момент окна.

Спека 02, раздел 3.1. Здесь группировка превращается из списка в функцию
от даты: `candidates(t)` возвращает пары, которые имеет смысл проверять
на коинтеграцию в окне, начинающемся в `t`.

Три условия, и каждое обосновано отдельно:

1. **Общий сектор** — `groups.yaml`. Активы без надёжной метки
   (`unlabeled`) пар не порождают: пустая метка хуже отсутствующей, она
   создаёт кандидатов, у которых нет причины быть парой.

2. **Сопоставимый размер.** Медианный дневной оборот двух ног не
   различается больше чем в `MAX_TURNOVER_RATIO` раз. Причина не
   эстетическая: позиция берётся равным нотионалом на обе ноги, поэтому
   при разнице в десять раз доля от оборота у меньшей ноги в десять раз
   хуже, и проскальзывание считается по ней. Плюс у активов разного
   размера разный состав держателей, то есть на одну новость они
   реагируют по-разному.

   Порог — правило на паре, а не разбиение на корзины: разбиение
   развело бы по разным корзинам активы с оборотом 9.9 и 10.1 млн,
   различающиеся ни на что.

3. **Ликвидность и история на момент окна.** Оборот и доля баров со
   сделками считаются по `FORM_DAYS` дням, ЗАКОНЧИВШИМСЯ до `t`.
   Ничего из окна `t` и позже в отбор не входит.

**Почему размер берётся на момент окна.** Актив, который сегодня в
первом дециле оборота, в 2022 году мог быть неликвиден. Деление групп по
сегодняшнему обороту протащило бы в отбор знание из будущего — тот же
дефект, что отбор универсума по сегодняшнему списку, который в A1
стоил бы 25–28 % инструментов.

    python3 pairs.py --interval 1m            # сетка окон по истории
    python3 pairs.py --at 2025-01-01 --dump   # состав на одну дату
"""

import argparse
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
UNIVERSE = os.path.join(HERE, "..", "a1_universe", "out", "universe.json")

sys.path.insert(0, HERE)
from check_coverage import GROUPS, MIN_HISTORY, parse_groups  # noqa: E402

FORM_DAYS = 90            # окно оценки ликвидности перед датой отбора
MIN_DAYS_IN_WINDOW = 30   # меньше — ряд слишком дыряв, чтобы судить
MIN_SHARE_TRADED = 0.90   # доля минут со сделками, мера свежести цены
MAX_TURNOVER_RATIO = 10.0

META_SECTIONS = ("duplicate_listings", "mechanically_linked",
                 "low_confidence", "unlabeled")


def load_groups():
    sec = parse_groups(GROUPS)
    meta = {k: sec.pop(k, []) for k in META_SECTIONS}
    sec.pop("excluded_special", None)
    of = {}
    for g, members in sec.items():
        for a in members:
            of[a] = g
    return sec, of, {
        "duplicates": {frozenset(p.split("/")) for p in meta["duplicate_listings"]},
        "mechanical": [tuple(p.split("/")) for p in meta["mechanically_linked"]],
        "low": set(meta["low_confidence"]),
        "unlabeled": set(meta["unlabeled"]),
    }


def load_liquidity(interval):
    """Подневный ряд ликвидности, ключ — базовый актив, не символ."""
    path = os.path.join(OUT, f"daily_liquidity_{interval}.csv.gz")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала liquidity.py --interval {interval}")
    u = json.load(open(UNIVERSE, encoding="utf-8"))["assets"]
    base = {v["binance_symbol"]: a for a, v in u.items() if v.get("binance_symbol")}
    d = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            a = base.get(r["symbol"])
            if a is None:
                continue
            d[a].append((r["day"], float(r["turnover"]),
                         int(r["bars"]), int(r["bars_traded"])))
    for v in d.values():
        v.sort()
    return d, u


def state_at(liq, universe, t):
    """Ликвидность каждого актива на дату `t`, только по прошлому.

    Оборот — медиана по дням, В КОТОРЫХ БЫЛИ СДЕЛКИ. Среднее здесь не
    годится: один день листинга с оборотом на порядок выше обычного
    сдвинул бы оценку размера на весь год. Дни без сделок не попадают
    в оборот, но остаются в знаменателе доли баров со сделками — иначе
    замороженный ряд выглядел бы идеально ликвидным.
    """
    t0 = (date.fromisoformat(t) - timedelta(days=FORM_DAYS)).isoformat()
    hist = (date.fromisoformat(t) - timedelta(days=MIN_HISTORY)).isoformat()
    out = {}
    for a, rows in liq.items():
        v = universe.get(a)
        if not v or v["asset_class"] != "crypto" or v["listed"] > hist:
            continue
        win = [x for x in rows if t0 <= x[0] < t]
        if len(win) < MIN_DAYS_IN_WINDOW:
            continue
        turn = sorted(x[1] for x in win if x[3] > 0)
        if not turn:
            continue
        bars = sum(x[2] for x in win)
        traded = sum(x[3] for x in win)
        out[a] = {"turnover": turn[len(turn) // 2],
                  "share_traded": traded / bars if bars else 0.0,
                  "days": len(win)}
    return out


def candidates(groups, of_group, meta, st,
               max_ratio=MAX_TURNOVER_RATIO,
               min_share=MIN_SHARE_TRADED):
    live = {a: s for a, s in st.items()
            if s["share_traded"] >= min_share and a in of_group}
    pairs = []
    for g, members in groups.items():
        ms = sorted(a for a in members if a in live)
        for i, a in enumerate(ms):
            for b in ms[i + 1:]:
                if frozenset((a, b)) in meta["duplicates"]:
                    continue
                ta, tb = live[a]["turnover"], live[b]["turnover"]
                if max(ta, tb) / min(ta, tb) > max_ratio:
                    continue
                pairs.append((a, b, g))
    # Механически связанные входят независимо от размера: связь задана
    # протоколом, и газовый токен по обороту всегда меньше своей сети.
    have = {frozenset(p[:2]) for p in pairs}
    for a, b in meta["mechanical"]:
        if a in live and b in live and frozenset((a, b)) not in have:
            pairs.append((a, b, "mechanically_linked"))
    return pairs, live


def grid(start, end, step_days):
    t = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while t <= last:
        yield t.isoformat()
        t += timedelta(days=step_days)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--at", help="одна дата вместо сетки")
    ap.add_argument("--dump", action="store_true", help="печатать состав")
    ap.add_argument("--start", default="2022-07-01")
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--step", type=int, default=90)
    args = ap.parse_args()

    groups, of_group, meta = load_groups()
    liq, universe = load_liquidity(args.interval)

    dates = [args.at] if args.at else list(grid(args.start, args.end, args.step))
    report = []
    for t in dates:
        st = state_at(liq, universe, t)
        pairs, live = candidates(groups, of_group, meta, st)
        n = len(live)
        alt = {}
        for r in (3.0, 10.0, 30.0, 1e9):
            p, _ = candidates(groups, of_group, meta, st, max_ratio=r)
            alt[r] = len(p)
        row = {"date": t, "assets": n, "pairs": len(pairs),
               "pairs_by_ratio": {str(k): v for k, v in alt.items()},
               "all_pairs": n * (n - 1) // 2}
        report.append(row)
        print(f"{t}  активов {n:>3}  кандидатов {len(pairs):>5}"
              f"  из {row['all_pairs']:>6} возможных"
              f"  ({100*(1-len(pairs)/max(1,row['all_pairs'])):.1f} % отсечено)")
        if args.dump:
            for a, b, g in sorted(pairs, key=lambda p: (p[2], p[0], p[1])):
                print(f"    {g:<22} {a}/{b}")

    if not args.at:
        with open(os.path.join(OUT, f"candidates_{args.interval}.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"form_days": FORM_DAYS,
                       "min_share_traded": MIN_SHARE_TRADED,
                       "max_turnover_ratio": MAX_TURNOVER_RATIO,
                       "min_history_days": MIN_HISTORY,
                       "windows": report}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
