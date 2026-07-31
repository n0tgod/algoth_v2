#!/usr/bin/env python3
"""
Замер: отличается ли исход входа, случившегося сразу после стопа?

Откуда вопрос
-------------

Владелец увидел на HYPEUSDT две сделки подряд: лонг 07:47:21 выбило
стопом за 119 секунд, и через 73 секунды детектор снова открыл лонг — на
уровень ниже, и снова стоп. Вопрос: есть ли у таких входов общий
признак, по которому их можно было бы не брать.

Почему нельзя отвечать по этим двум
-----------------------------------

Две сделки имеют десятки общих признаков случайно: обе лонги, обе на
одной монете, обе в один час, обе по правилу ленты. Признак, выбранный
после того, как известен исход, объясняет эти два случая всегда — и не
переносится ни на что. Поэтому гипотеза формулируется словами ДО
подсчёта, а проверяется на всей выборке архивного прогона T4: 1403
сделки, 16 символов, неделя.

Гипотеза, записанная до счёта
-----------------------------

Если цена валится сквозь уровни, детектор видит поглощение на каждом
следующем и открывается снова и снова, а выбивает его тоже каждый раз.
Тогда **вход вскоре после стопа на том же символе в ту же сторону**
должен быть систематически хуже одиночного.

Что считается
-------------

Три корзины по обстоятельствам входа, известным В МОМЕНТ ВХОДА:

* «одиночный» — на этом символе не было сделок час до входа;
* «после стопа» — предыдущая сделка того же символа закрылась стопом
  не раньше чем за `--within` минут, и сторона та же;
* «прочее» — всё остальное (была сделка, но давно, либо другой исход,
  либо другая сторона).

Порог существенности — не «на глаз»: у доли побед считается интервал по
Уилсону, у ожидания — стандартная ошибка среднего. Если корзины
расходятся меньше чем на две ошибки, разницы не предъявлено.

    python3 research/t4_structure/reentry.py
"""

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    for t in d.get("trades") or []:
        entry, stop = float(t["entry"]), float(t["stop"])
        stop_bp = abs(entry - stop) / entry * 1e4
        rows.append({"sym": t["sym"],
                     "t": datetime.fromisoformat(t["t"]).timestamp(),
                     "side": int(t["side"]), "net": float(t["net"]),
                     "outcome": t["outcome"], "rr": float(t.get("rr") or 0),
                     "stop_bp": stop_bp,
                     # Кратность риска. Решающая мера, а не украшение:
                     # после стопа цена уже ушла, значит и экстремум
                     # дальше, и стоп шире — а более широкий стоп даёт
                     # больший убыток В ПУНКТАХ при том же качестве
                     # входа. В R размер сделки поделён обратно, и если
                     # разница держится только в пунктах, дело в
                     # геометрии, а не в отборе. Ровно этот подвох T4
                     # уже находила у «прогон минус нуль».
                     "r": float(t["net"]) / max(stop_bp, 1e-9)})
    rows.sort(key=lambda r: (r["sym"], r["t"]))
    return d.get("cell", {}), rows


def label(rows, within_min, quiet_min=60):
    """Пометить каждую сделку обстоятельствами ЕЁ ВХОДА.

    Смотрим только назад: всё, что известно позже, знанием в момент
    входа не является. Это то же требование, из-за которого в L1
    пришлось сдвигать момент решения на задержку публикации.
    """
    prev = defaultdict(list)
    for r in rows:
        hist = prev[r["sym"]]
        last = hist[-1] if hist else None
        gap = (r["t"] - last["t"]) / 60.0 if last else float("inf")
        if gap >= quiet_min:
            r["bucket"] = "одиночный"
        elif (last and last["outcome"] == "стоп" and gap <= within_min
              and last["side"] == r["side"]):
            r["bucket"] = "после стопа"
        else:
            r["bucket"] = "прочее"
        r["gap_min"] = gap
        # Сколько сделок было на этом символе за прошедший час — мера
        # «сколько уровней подряд уже сложилось».
        r["run"] = sum(1 for h in hist if r["t"] - h["t"] <= 3600)
        hist.append(r)
    return rows


def wilson(k, n, z=1.96):
    """Интервал доли: на малых корзинах обычная ошибка врёт."""
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - half), min(1.0, c + half)


def summarize(rows, name):
    n = len(rows)
    if not n:
        return {"bucket": name, "n": 0}
    wins = sum(1 for r in rows if r["outcome"] == "цель")
    nets = [r["net"] for r in rows]
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / max(1, n - 1)
    se = math.sqrt(var / n)
    lo, hi = wilson(wins, n)
    rs = [r["r"] for r in rows]
    rmean = sum(rs) / n
    rvar = sum((x - rmean) ** 2 for x in rs) / max(1, n - 1)
    stops = sorted(r["stop_bp"] for r in rows)
    return {"bucket": name, "n": n, "win": wins / n, "win_lo": lo,
            "win_hi": hi, "exp": mean, "se": se,
            "median": sorted(nets)[n // 2], "r": rmean,
            "r_se": math.sqrt(rvar / n), "stop": stops[n // 2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(OUT, "backtest.json"))
    ap.add_argument("--within", type=float, default=30.0,
                    help="сколько минут после стопа считать «сразу»")
    a = ap.parse_args()

    cell, rows = load(a.file)
    rows = label(rows, a.within)
    print(f"выгрузка: {a.file}")
    print(f"ячейка: окно {cell.get('window_sec')} с, объём "
          f"×{cell.get('vol_mult')}, издержки {cell.get('cost_bp')} б.п., "
          f"{cell.get('start')}…{cell.get('end')}")
    print(f"сделок {len(rows)}, символов "
          f"{len({r['sym'] for r in rows})}\n")

    all_ = summarize(rows, "вся выборка")
    parts = [summarize([r for r in rows if r["bucket"] == b], b)
             for b in ("одиночный", "после стопа", "прочее")]
    print(f"{'корзина':14} {'сделок':>7} {'побед':>7} "
          f"{'ожидание':>12} {'в риске':>13} {'стоп':>8}")
    for s in [all_] + parts:
        if not s["n"]:
            print(f"{s['bucket']:14} {'—':>7}  пусто")
            continue
        print(f"{s['bucket']:14} {s['n']:>7} {s['win']:>6.1%} "
              f"{s['exp']:>+8.1f}±{s['se']:<4.1f} "
              f"{s['r']:>+7.2f}±{s['r_se']:<5.2f} {s['stop']:>7.1f}")

    # Прямое сравнение двух корзин: расходятся ли они больше чем на две
    # ошибки разности. Без этого «хуже» — это про знак, а не про размер.
    one = next(s for s in parts if s["bucket"] == "одиночный")
    after = next(s for s in parts if s["bucket"] == "после стопа")
    if one["n"] and after["n"]:
        for unit, key, sek in (("б.п.", "exp", "se"), ("R", "r", "r_se")):
            diff = after[key] - one[key]
            sed = math.hypot(one[sek], after[sek])
            print(f"\nразность «после стопа» − «одиночный» в {unit}: "
                  f"{diff:+.2f} ± {sed:.2f} "
                  f"({abs(diff) / max(sed, 1e-9):.1f} σ)")
        print(f"медианный стоп: одиночный {one['stop']:.1f} б.п., "
              f"после стопа {after['stop']:.1f} б.п.")
        print("если разница держится в пунктах и пропадает в R — "
              "это разный РАЗМЕР сделки, а не разное качество входа")

    # Устойчивость. Одно число в 4.5 сигмы получено на выборке, которую
    # мы уже смотрели, и гипотеза родилась из двух сделок, у которых
    # исход был известен. Значит агрегат ничего не доказывает сам по
    # себе: смотреть надо, повторяется ли знак на НЕЗАВИСИМЫХ кусках.
    # Совпадение знака в большинстве дней и монет — свидетельство,
    # величина агрегата — нет.
    def split(key, title):
        keys = sorted({key(r) for r in rows})
        same, both, lines = 0, 0, []
        for k in keys:
            sel = [r for r in rows if key(r) == k]
            o = summarize([r for r in sel if r["bucket"] == "одиночный"], "o")
            f = summarize([r for r in sel if r["bucket"] == "после стопа"], "f")
            if o["n"] < 10 or f["n"] < 10:
                continue
            both += 1
            worse = f["exp"] < o["exp"]
            same += worse
            lines.append(f"    {str(k):12} одиночный {o['exp']:>+7.1f} "
                         f"({o['n']:>3}) · после стопа {f['exp']:>+7.1f} "
                         f"({f['n']:>3}) {'хуже' if worse else 'ЛУЧШЕ'}")
        print(f"\n{title}: знак совпал в {same} из {both}")
        print("\n".join(lines))
        return same, both

    split(lambda r: datetime.utcfromtimestamp(r["t"]).strftime("%m-%d"),
          "по дням (кусков с 10+ сделками в обеих корзинах)")
    split(lambda r: r["sym"].replace("USDT", ""),
          "по монетам (кусков с 10+ сделками в обеих корзинах)")

    # Что осталось бы, если такие входы просто не брать. Отдельный
    # вопрос от «есть ли разница»: фильтр может быть настоящим и при
    # этом не спасать — остаток тоже надо назвать числом.
    keep = [r for r in rows if r["bucket"] != "после стопа"]
    s = summarize(keep, "без них")
    print(f"\nесли такие входы не брать: {s['n']} сделок из {len(rows)}, "
          f"побед {s['win']:.1%}, ожидание {s['exp']:+.1f} ± {s['se']:.1f} б.п.")

    # Вторая мера того же наблюдения: сколько сделок уже случилось на
    # символе за час. Если уровни сыплются подряд, исход должен падать с
    # номером сделки в серии.
    print("\nпо длине серии на символе за прошедший час:")
    for k in (0, 1, 2, 3):
        sel = [r for r in rows if (r["run"] == k if k < 3 else r["run"] >= 3)]
        s = summarize(sel, f"было {k}" + ("+" if k == 3 else ""))
        if s["n"]:
            print(f"  {s['bucket']:10} {s['n']:>6} сд., побед {s['win']:>5.1%}"
                  f", ожидание {s['exp']:>+7.1f} ± {s['se']:.1f} б.п.")


if __name__ == "__main__":
    main()
