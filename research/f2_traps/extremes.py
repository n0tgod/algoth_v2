#!/usr/bin/env python3
"""
Проверка крайних ног: настоящее движение рынка или дефект архива?

Исправление арифметики хвоста вскрыло ноги, теряющие 475–590 % позиции
за один период удержания. Это короткие позиции в активах, выросших за
десять дней в шесть-семь раз. Для разогнанной монеты такое возможно, для
битого бара архива — тоже.

Разница решающая. Если движение настоящее — оно и есть тот хвост,
ради которого гипотеза провалила критерий просадки, и строить рм надо
против него. Если это дефект данных — мы чиним не ту проблему, а
настоящая просадка меньше.

Проверка обязана быть отдельной ещё и потому, что A2 уже находила
именно такой класс дефекта: замороженные ряды, где архив продолжает
публиковать бар с перенесённой ценой. Мера «есть ли бар» их не ловила.

Печатает крайние ноги с активом, датой и величиной — дальше их надо
смотреть глазами по хранилищу, а не верить сводке.

    python3 extremes.py --interval 1m
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
F1 = os.path.join(RESEARCH, "f1_carry", "out")

sys.path.insert(0, os.path.join(RESEARCH, "f1_carry"))
import carry as CY           # noqa: E402

KS = (7, 14)
HS = (5, 10)
WIDTHS = {"decile": 0.10, "quintile": 0.20}
TOP = 25                     # сколько крайних ног показать


def load_vectors(tag):
    d = os.path.join(F1, "vectors")
    if not os.path.isdir(d):
        raise SystemExit(f"нет {d} — сначала f1_carry/run.py")
    out = {}
    for fn in sorted(os.listdir(d)):
        if fn.startswith(tag + "_") and fn.endswith(".json"):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                out.update(json.load(f))
    if not out:
        raise SystemExit(f"в {d} нет векторов для {tag}")
    return out


def arr(d, key):
    return np.asarray(d[str(key)] if str(key) in d else d[key],
                      dtype=np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--funding-venue", default="bybit")
    a = ap.parse_args()
    tag = f"{a.interval}_{a.funding_venue}"

    vec = load_vectors(tag)
    dates = sorted(vec)
    seen, rows = set(), []

    for k in KS:
        for h in HS:
            for wname, width in WIDTHS.items():
                for day in dates[::h]:
                    v = vec[day]
                    names = v["names"]
                    score = arr(v["score"], k)
                    price = arr(v["price"], h)
                    fund = arr(v["funding"], h)
                    w, per_leg = CY.weights(score, width)
                    if per_leg < 1:
                        continue
                    pos = CY.position_return(w, np.where(np.isfinite(price),
                                                         price, 0.0))
                    m = (w != 0) & np.isfinite(price)
                    for i in np.flatnonzero(m):
                        if pos[i] > -1.0:
                            continue          # интересен только хвост
                        key = (names[i], day, h)
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append({
                            "asset": names[i], "date": day, "hold_days": h,
                            "side": "лонг" if w[i] > 0 else "шорт",
                            "log_return": float(price[i]),
                            "price_move": float(np.expm1(price[i])),
                            "position_return": float(pos[i]),
                            "funding": float(fund[i]),
                            "k": k, "width": wname,
                        })

    rows.sort(key=lambda r: r["position_return"])
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"extremes_{tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"config": {"interval": a.interval,
                              "funding_venue": a.funding_venue},
                   "count": len(rows), "legs": rows}, f,
                  ensure_ascii=False, indent=1)

    print(f"ног с убытком больше 100 % позиции: {len(rows)}\n")
    print(f"{'актив':<14}{'дата':<12}{'h':>3}{'сторона':>9}"
          f"{'ход цены':>12}{'убыток поз.':>14}{'ставка за период':>18}")
    for r in rows[:TOP]:
        print(f"{r['asset']:<14}{r['date']:<12}{r['hold_days']:>3}"
              f"{r['side']:>9}{r['price_move']:>11.0%}"
              f"{r['position_return']:>14.0%}{r['funding']:>17.2%}")
    if rows:
        by_asset = {}
        for r in rows:
            by_asset[r["asset"]] = by_asset.get(r["asset"], 0) + 1
        top = sorted(by_asset.items(), key=lambda x: -x[1])[:10]
        print("\nчаще всего в хвосте: " +
              ", ".join(f"{a} ({n})" for a, n in top))
        print(f"\nразных активов {len(by_asset)}, разных дат "
              f"{len({r['date'] for r in rows})}")
    print(f"\nзаписано {dst}")
    print("\nДальше эти ноги надо посмотреть по хранилищу глазами: "
          "шестикратный рост за десять дней бывает у разогнанной монеты "
          "и бывает у битого бара, и различить это сводка не может.")


if __name__ == "__main__":
    main()
