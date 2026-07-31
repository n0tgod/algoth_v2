#!/usr/bin/env python3
"""
Потолок отсева: чего добьётся фильтр с идеальным знанием будущего.

Зачем именно так
----------------

Владелец поставил задачу: брать минусовые сделки и искать признак,
который их отсеет, постепенно выравнивая статистику. Задача правильная,
но у неё есть смертельная ловушка: признак, выбранный ПОСЛЕ того, как
исход известен, объясняет прошлое всегда и не переносится никуда. Цикл
«посмотрели на убытки — нашли признак — отсеяли — посмотрели снова» есть
способ подогнаться под шум, и каждый круг тратит бюджет доказательства.

Поэтому первым считается **потолок**, а не фильтр. Порог выбирается по
уже известным исходам — то есть заведомо нечестно, — и это даёт верхнюю
границу того, чего фильтр вообще способен достичь на этих признаках.
Если даже потолок не выводит ожидание в плюс, направление закрыто
дёшево. Так в S1 закрылись сразу три рычага против сквиза, а в T1 —
секундные горизонты.

Что считается признаком
-----------------------

Только то, что известно В МОМЕНТ ВХОДА. Ширина стопа, отношение к цели,
расстояние до уровня, час суток, сторона, что было на этом символе до
входа. Всё, что известно позже (сколько держали, куда вышли), признаком
не является — фильтр на нём был бы заглядыванием в будущее и дал бы
любые числа.

Как читать результат
--------------------

Три числа на признак: сколько сделок остаётся, ожидание оставшихся и
**насколько это лучше случайного отсева той же доли**. Последнее
обязательно: выбросив половину сделок наугад, ожидание тоже сдвинется,
и без сравнения «фильтр работает» неотличимо от «мы стали меньше
торговать» — то же условие, ради которого в спеке 05 заводился нуль 4.

    python3 research/t4_structure/ceiling.py
    python3 research/t4_structure/ceiling.py --file <другой прогон>
"""

import argparse
import json
import math
import os
import random
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
MIN_KEEP = 0.30           # фильтр, оставляющий меньше трети, — не фильтр
SEED = 20260731           # зерно числом: нуль обязан воспроизводиться


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    for t in d.get("trades") or []:
        entry, stop = float(t["entry"]), float(t["stop"])
        lvl = float(t.get("level") or entry)
        tgt = float(t.get("target") or entry)
        stop_bp = abs(entry - stop) / entry * 1e4
        ts = datetime.fromisoformat(t["t"])
        rows.append({
            "sym": t["sym"], "t": ts.timestamp(), "side": int(t["side"]),
            "net": float(t["net"]), "outcome": t["outcome"],
            "stop_bp": stop_bp,
            "r": float(t["net"]) / max(stop_bp, 1e-9),
            "rr": float(t.get("rr") or 0.0),
            "tgt_bp": abs(tgt - entry) / entry * 1e4,
            # Насколько цена ушла от уровня к моменту входа. Уровень —
            # повод сделки; вход далеко от него описывает другую сделку.
            "away_bp": abs(entry - lvl) / entry * 1e4,
            "hour": ts.astimezone(timezone.utc).hour,
        })
    rows.sort(key=lambda r: (r["sym"], r["t"]))
    hist = defaultdict(list)
    for r in rows:
        h = hist[r["sym"]]
        last = h[-1] if h else None
        r["gap_min"] = (r["t"] - last["t"]) / 60.0 if last else 1e9
        r["after_stop"] = 1.0 if (last and last["outcome"] == "стоп"
                                  and last["side"] == r["side"]
                                  and r["gap_min"] <= 30) else 0.0
        r["run"] = float(sum(1 for x in h if r["t"] - x["t"] <= 3600))
        h.append(r)
    return d.get("cell", {}), rows


def exp_se(rows, key="net"):
    n = len(rows)
    if not n:
        return 0.0, 0.0
    v = [r[key] for r in rows]
    m = sum(v) / n
    var = sum((x - m) ** 2 for x in v) / max(1, n - 1)
    return m, math.sqrt(var / n)


def best_cut(rows, feat, key="net"):
    """Лучший порог по признаку — выбранный ПО ИСХОДАМ, то есть нечестно.

    Перебираются квантили признака, обе стороны отсечения. Берётся то,
    что даёт наибольшее ожидание оставшихся при условии, что осталась
    хотя бы треть сделок. Это и есть потолок для фильтра «одно число».
    """
    vals = sorted({r[feat] for r in rows})
    if len(vals) < 2:
        return None
    if len(vals) == 2:
        # Двоичный признак: порогов нет, есть две стороны.
        best = None
        for v in vals:
            sel = [r for r in rows if r[feat] == v]
            if len(sel) < MIN_KEEP * len(rows):
                continue
            m, se = exp_se(sel, key)
            if best is None or m > best["exp"]:
                best = {"feat": feat, "thr": v, "low": True, "tries": 2,
                        "n": len(sel), "exp": m, "se": se,
                        "share": len(sel) / len(rows)}
        return best
    best, tries = None, 0
    for q in range(5, 96, 5):
        thr = vals[min(len(vals) - 1, int(len(vals) * q / 100))]
        for keep_low in (True, False):
            sel = [r for r in rows
                   if (r[feat] <= thr if keep_low else r[feat] >= thr)]
            if len(sel) < MIN_KEEP * len(rows):
                continue
            tries += 1
            m, se = exp_se(sel, key)
            if best is None or m > best["exp"]:
                best = {"feat": feat, "thr": thr, "low": keep_low,
                        "n": len(sel), "exp": m, "se": se,
                        "share": len(sel) / len(rows)}
    if best:
        best["tries"] = tries
    return best


def random_null(rows, share, tries=2000, key="net"):
    """Распределение ожидания при СЛУЧАЙНОМ отсеве той же доли.

    Возвращает среднее и 95-й процентиль. Сравнивать надо именно с
    процентилем, а не с максимумом: первая версия этого замера брала
    лучший из четырёхсот случайных отборов против лучшего из тридцати
    восьми порогов признака — максимум из большего числа попыток больше
    по построению, и случайности подсуживалось. Ошибка моя, найдена до
    выводов.

    Зачем нуль вообще: выбросив половину сделок наугад, ожидание тоже
    сдвинется. Без этого сравнения «фильтр работает» неотличимо от «мы
    стали меньше торговать» — то же условие, ради которого в спеке 05
    заводился нуль 4.
    """
    rnd = random.Random(SEED)
    k = max(1, int(round(share * len(rows))))
    vals = []
    for _ in range(tries):
        m, _se = exp_se(rnd.sample(rows, k), key)
        vals.append(m)
    vals.sort()
    return sum(vals) / len(vals), vals[int(0.95 * (len(vals) - 1))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(OUT, "backtest.json"))
    ap.add_argument("--unit", choices=("net", "r"), default="net")
    a = ap.parse_args()

    cell, rows = load(a.file)
    base, base_se = exp_se(rows, a.unit)
    unit = "б.п." if a.unit == "net" else "R"
    print(f"выгрузка: {a.file}")
    print(f"ячейка: {cell.get('start')}…{cell.get('end')}, окно "
          f"{cell.get('window_sec')} с, издержки {cell.get('cost_bp')} б.п.")
    print(f"сделок {len(rows)}, ожидание как есть "
          f"{base:+.2f} ± {base_se:.2f} {unit}\n")

    feats = ["stop_bp", "rr", "tgt_bp", "away_bp", "hour", "gap_min",
             "run", "after_stop", "side"]
    print(f"{'признак':10} {'порог':>10} {'оставили':>9} {'ожидание':>14} "
          f"{'нуль: среднее':>14} {'95-й':>8} {'выше?':>6}")
    got = []
    for f in feats:
        b = best_cut(rows, f, a.unit)
        if not b:
            continue
        mean, p95 = random_null(rows, b["share"], key=a.unit)
        b["rand"], b["p95"] = mean, p95
        b["over"] = b["exp"] > p95
        got.append(b)
        side = "≤" if b["low"] else "≥"
        print(f"{f:10} {side}{b['thr']:>9.2f} {b['share']:>8.0%} "
              f"{b['exp']:>+8.2f}±{b['se']:<4.2f} {mean:>+13.2f} "
              f"{p95:>+8.2f} {'да' if b['over'] else 'нет':>6}")

    got.sort(key=lambda b: -b["exp"])
    if got:
        top = got[0]
        print(f"\nПОТОЛОК одного признака: {top['feat']} "
              f"{'≤' if top['low'] else '≥'}{top['thr']:.2f} — "
              f"{top['exp']:+.2f} {unit} на {top['n']} сделках "
              f"({top['share']:.0%} выборки)")
        print(f"случайный отсев той же доли: среднее {top['rand']:+.2f}, "
              f"95-й процентиль {top['p95']:+.2f} {unit} "
              f"(порогов перебрано {top.get('tries', 0)})")
        above = [b for b in got if b["over"]]
        print(f"признаков выше 95-го процентиля нуля: {len(above)} из "
              f"{len(got)}" + (": " + ", ".join(b["feat"] for b in above)
                               if above else ""))
        print("\nПорог выбран ПО ИЗВЕСТНЫМ ИСХОДАМ — это верхняя граница, "
              "а не результат.\nЕсли она не выходит в плюс, фильтр на этих "
              "признаках не выведет тем более.")


if __name__ == "__main__":
    main()
