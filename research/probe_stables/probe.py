"""Стейбл-против-стейбла: у инструмента цены нет, а издержки есть.

Владелец увидел USDEUSDT на графике DCA-книги: свечи стоят на 0.9994,
размах суток около шести базисных пунктов при круге издержек в 11 —
торговать такую пару нельзя ни при каком сигнале, это арифметика, а не
вкус. Пара исполняется, комиссия платится, а хода, из которого её можно
отбить, не существует.

Отсюда предмет замера: **есть ли у распределения размаха ПРОВАЛ**,
которым стейблы отделяются от обычных имён, и сколько имён он забирает.
Порог назначать по результату нельзя (ошибка R5), поэтому он объявлен
арифметикой ДО прогона и проверяется на попадание в провал:

    круг издержек 11 б.п. на ногу → двойной круг 22 → назначаем
    порог 50 б.п. медианного СУТОЧНОГО размаха.

Пятьдесят — не подобранное число, а верхняя граница «инструмента, у
которого суточного хода не хватает и на два круга с запасом»: обычный
альт ходит за сутки 200–500 б.п., стейбл — единицы. Если провала в
данных нет, порог не вводится вовсе: правило, режущее по краю плотного
распределения, однажды выбросит живое имя.

Источник — наши же почасовые сводки (`s8_loop/out/summary`), те самые,
на которых учится модель: `(mid_high − mid_low) / mid_close`. Размах, а
не доходность, по той же причине, что на странице волатильности — час,
в котором цена сходила и вернулась, доходность считает спокойным.
Суточный размах собирается по часам суток одним max/min, а не суммой
часовых: сумма мерила бы путь, а нас интересует ход.

Прогон: .venv/bin/python research/probe_stables/probe.py --days 14
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = os.path.join(os.path.dirname(HERE), "s8_loop", "out", "summary")
OUT = os.path.join(HERE, "out")

# Порог объявлен ДО прогона и выведен из круга издержек, а не из вида
# распределения: 11 б.п. круг на ногу, двойной круг 22, порог 50.
ROUND_COST_BP = 11.0
STABLE_MAX_BP = 50.0


def day_ranges(path):
    """Суточный размах по часам одного дня, б.п. Нет данных — None."""
    hi = lo = None
    close = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                h, l, c = r.get("mid_high"), r.get("mid_low"), r.get("mid_close")
                if h is None or l is None or not c:
                    continue
                hi = h if hi is None else max(hi, h)
                lo = l if lo is None else min(lo, l)
                close = c
    except OSError:
        return None
    if hi is None or not close:
        return None
    return (hi - lo) / close * 1e4


def scan(days, log=print):
    """Медианный суточный размах по каждому имени, б.п."""
    try:
        syms = sorted(os.listdir(SUMMARY))
    except OSError:
        raise SystemExit(f"нет сводок в {SUMMARY} — прогон не на той машине")
    cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    out, said = {}, time.time()
    for i, sym in enumerate(syms):
        d = os.path.join(SUMMARY, sym)
        if not os.path.isdir(d):
            continue
        if time.time() - said > 30:
            log(f"  {i}/{len(syms)} имён")
            said = time.time()
        vals = []
        for f in sorted(os.listdir(d)):
            if not f.endswith(".jsonl") or f[:10] < cut:
                continue
            v = day_ranges(os.path.join(d, f))
            if v is not None:
                vals.append(v)
        # Меньше трёх суток — величина не измерена, а не мала: молодой
        # листинг и стейбл различаются только числом суток под ней.
        if len(vals) >= 3:
            out[sym] = (round(statistics.median(vals), 2), len(vals))
    return out


def report(res, days, path):
    rows = sorted(res.items(), key=lambda kv: kv[1][0])
    vals = [v for _, (v, _) in rows]
    q = lambda p: (round(vals[int(p * (len(vals) - 1))], 2) if vals else None)
    below = [(s, v, n) for s, (v, n) in rows if v < STABLE_MAX_BP]
    # Провал ищется как отношение соседних значений на границе: если
    # порог стоит в плотной области, отношение около единицы, и правило
    # режет живое имя.
    gap = None
    for i in range(1, len(vals)):
        if vals[i - 1] < STABLE_MAX_BP <= vals[i]:
            gap = (round(vals[i - 1], 2), round(vals[i], 2),
                   round(vals[i] / max(vals[i - 1], 1e-9), 1))
            break
    md = [f"# Стейблы: у инструмента цены нет, а издержки есть",
          "",
          f"Окно {days} суток, имён с измеримым размахом {len(rows)}.",
          f"Порог объявлен до прогона: **{STABLE_MAX_BP:g} б.п.** "
          f"медианного суточного размаха (круг издержек "
          f"{ROUND_COST_BP:g} б.п. на ногу, двойной круг "
          f"{2 * ROUND_COST_BP:g}).",
          "",
          "## Распределение медианного суточного размаха, б.п.",
          "",
          "| 1 % | 5 % | 25 % | медиана | 75 % | 95 % |",
          "|---|---|---|---|---|---|",
          f"| {q(0.01)} | {q(0.05)} | {q(0.25)} | {q(0.5)} | {q(0.75)} "
          f"| {q(0.95)} |",
          ""]
    if gap:
        md += [f"Соседи у порога: {gap[0]} и {gap[1]} б.п., "
               f"то есть скачок в {gap[2]} раза — порог стоит "
               f"{'в ПРОВАЛЕ' if gap[2] >= 3 else 'в ПЛОТНОЙ области'} "
               f"распределения.", ""]
    else:
        md += ["Ни одно имя не ниже порога — правило вводить не на чем.",
               ""]
    md += [f"## Ниже порога — {len(below)} имён", "",
           "| символ | медианный суточный размах, б.п. | суток |",
           "|---|---|---|"]
    for s, v, n in below:
        md += [f"| {s} | {v} | {n} |"]
    md += ["", "## Двадцать самых спокойных СВЕРХ порога (для сравнения)",
           "", "| символ | размах, б.п. | суток |", "|---|---|---|"]
    for s, (v, n) in rows[len(below):len(below) + 20]:
        md += [f"| {s} | {v} | {n} |"]
    os.makedirs(OUT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(path.replace(".md", ".json"), "w", encoding="utf-8") as f:
        json.dump({"days": days, "threshold_bp": STABLE_MAX_BP,
                   "n": len(rows), "gap": gap,
                   "below": [{"sym": s, "bp": v, "days": n}
                             for s, v, n in below],
                   "ranges": {s: v for s, (v, _) in rows}}, f,
                  ensure_ascii=False, indent=1)
    return len(below), gap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    res = scan(a.days)
    path = os.path.join(OUT, f"STABLES-{a.tag}.md")
    n, gap = report(res, a.days, path)
    print(f"имён {len(res)}, ниже порога {n}, провал {gap}, "
          f"{round(time.time() - t0, 1)} с")
    if not a.no_publish:
        subprocess.run([os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                     "tools", "publish.sh"),
                        f"стейблы: замер размаха ({a.tag})"], check=False)


if __name__ == "__main__":
    main()
