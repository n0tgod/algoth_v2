#!/usr/bin/env python3
"""Замер перед постройкой живой DCA-книги: почём лестница и бывает ли она.

Живая книга обязана знать цены рунгов В МОМЕНТ ВХОДА, а строятся они из
структурных уровней T4 по 24-часовому окну минутных баров — то есть их
считает часовой цикл и кладёт в лист сечения, а пятисекундный сканер
только сравнивает с ними живую цену. Два вопроса решаются ДО кода:

1. **Сколько это стоит.** Цикл идёт каждый час; шаг, который стоит
   минуты, туда вписать можно, шаг на десятки минут — нет.
2. **Бывает ли лестница вообще.** `structural_rungs` возвращает `[вход]`,
   когда ни один уровень не годится: тогда позиция вырождается в
   одиночный вход при плече 1×, то есть книга носила бы имя DCA, не
   усредняя. Если так у большинства имён, строить надо не это.

Прогон: `run research/dca_live/probe_levels.py --top 80`.
Отчёта файлом не пишет намеренно: это замер на один раз, и его место —
лог задания, который публикуется сам.
"""

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))
sys.path.insert(0, os.path.join(RESEARCH, "s9_sweep"))
sys.path.insert(0, os.path.join(RESEARCH, "t4_structure"))
sys.path.insert(0, os.path.join(RESEARCH, "dca_ladder"))
sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))
import levels as LV                                          # noqa: E402
import sweep as SW                                           # noqa: E402
import books as BK                                           # noqa: E402

ROOT = os.path.join(RESEARCH, "b1_book", "out")
# Каталог книги берётся из РЕЕСТРА, а не собирается соглашением:
# «model_<ключ>» уже однажды увело сводку в чужую книгу.
SHEET = os.path.join(RESEARCH, "s8_loop", "out",
                     "model" + BK.suffix("sit"), "scan_sheet.json")
BACK_H = 24                       # то же окно, что у реплея (run_d2.BACK_H)
N_RUNGS = 4
MIN_ADD_GAP = 0.015


def rungs(entry, level_prices, min_gap=MIN_ADD_GAP, n=N_RUNGS):
    """Копия правила реплея (`run_d2.structural_rungs`) на время замера.

    В общий модуль правило переедет вместе с постройкой; здесь копия
    намеренно, чтобы замер не зависел от незавершённой правки.
    """
    if entry <= 0:
        return [entry]
    below = sorted([p for p in level_prices if 0 < p < entry], reverse=True)
    out = [entry]
    for p in below:
        if len(out) >= n:
            break
        if (out[-1] - p) / out[-1] >= min_gap:
            out.append(p)
    return out


def build_levels(bars):
    """Уровни по последнему бару окна; мало истории — уровней нет."""
    if len(bars) < LV.MIN_HISTORY_MIN:
        return np.array([]), len(bars)
    t = np.array([b[0] for b in bars], dtype="int64")
    H = np.array([b[2] for b in bars], dtype="float64")
    Lo = np.array([b[3] for b in bars], dtype="float64")
    P = np.array([b[4] for b in bars], dtype="float64")
    V = np.array([b[5] for b in bars], dtype="float64")
    prices, _k, _n, _s = LV.build(t, H, Lo, P, V, len(bars) - 1)
    return prices, len(bars)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=80)
    a = ap.parse_args()
    if not os.path.exists(SHEET):
        print(f"листа нет: {SHEET} — цикл ещё не писал сечение")
        return 1
    with open(SHEET, encoding="utf-8") as f:
        sh = json.load(f)
    seen, rows = set(), []
    for arm, rr in (sh.get("arms") or {}).items():
        for r in rr:
            s = r.get("sym")
            if s and s not in seen:
                seen.add(s)
                rows.append(r)
    rows.sort(key=lambda q: -abs(float(q.get("fwd_z") or 0.0)))
    rows = rows[:a.top]
    print(f"лист {sh.get('hour')}, написан {sh.get('written_at')}; "
          f"имён в сечении {len(seen)}, беру верхние {len(rows)}")
    now = time.time()
    t0 = time.time()
    per, depth, thin, nolv = [], [], 0, 0
    for r in rows:
        s, px = r["sym"], float(r.get("px") or 0.0)
        t1 = time.time()
        bars = SW.read_bars(ROOT, s, now - BACK_H * 3600, now)
        lv, n = build_levels(bars)
        per.append(time.time() - t1)
        if n < LV.MIN_HISTORY_MIN:
            thin += 1
            continue
        if not len(lv):
            nolv += 1
            continue
        d = len(rungs(px, list(lv)))
        depth.append(d)
    dt = time.time() - t0
    med = sorted(per)[len(per) // 2] if per else 0.0
    print(f"\nцена: {dt:.1f} с на {len(rows)} имён, медиана "
          f"{med:.3f} с/имя; на всё сечение ({len(seen)}) вышло бы "
          f"~{med * len(seen):.0f} с")
    print(f"мало истории (<{LV.MIN_HISTORY_MIN} мин записи): {thin}; "
          f"уровней не построилось: {nolv}")
    if depth:
        c = {k: depth.count(k) for k in sorted(set(depth))}
        real = sum(v for k, v in c.items() if k > 1)
        print(f"глубина лестницы у {len(depth)} имён: "
              + ", ".join(f"{k} ступеней — {v}" for k, v in c.items()))
        print(f"НАСТОЯЩАЯ лестница (есть хоть один долив): {real} "
              f"из {len(depth)} ({real / len(depth):.0%})")
    else:
        print("лестниц не построено ни одной — считать нечего")
    return 0


if __name__ == "__main__":
    sys.exit(main())
