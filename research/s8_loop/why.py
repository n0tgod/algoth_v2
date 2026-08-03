#!/usr/bin/env python3
"""
Почему час не становится сечением — по числам, а не по догадке.

Цикл печатает «сечений с ≥30 именами: 0» и на этом останавливается:
что именно не так — мало снимков, рваное покрытие или дыры, — из этой
строки не видно. Скрипт читает готовые сводки и раскладывает отказ по
условиям пригодности, час за часом.

Зависимостей нет: только стандартная библиотека, чтобы диагностика
работала даже там, где окружение сломано.

    .venv/bin/python research/s8_loop/why.py            # последние 40 ч
    python3 research/s8_loop/why.py --hours 200
"""

import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SUM = os.path.join(HERE, "out", "summary")

# Пороги пригодности — берутся из bookfeat, чтобы диагностика не
# разошлась с правилом (вторая копия однажды соврала бы).
sys.path.insert(0, HERE)
try:
    import bookfeat as FB
    MIN_SPAN, MAX_GAP, MIN_SNAPS = FB.MIN_SPAN_SEC, FB.MAX_GAP_SEC, \
        FB.MIN_SNAPS
    MIN_SECTION = FB.MIN_SECTION
except Exception:                                          # noqa: BLE001
    # bookfeat тянет numpy; диагностика обязана работать и без него.
    MIN_SPAN, MAX_GAP, MIN_SNAPS, MIN_SECTION = 1800.0, 300.0, 1800, 30


def med(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sum-dir", default=SUM)
    ap.add_argument("--hours", type=int, default=40,
                    help="сколько последних часов расписать построчно")
    a = ap.parse_args()

    try:
        symbols = sorted(os.listdir(a.sum_dir))
    except OSError:
        raise SystemExit(f"нет сводок в {a.sum_dir}")

    # (час) -> список строк сводки. Поздняя строка часа побеждает —
    # тот же порядок, что при сборке матриц.
    by_hour = defaultdict(dict)
    n_rows = 0
    for sym in symbols:
        sdir = os.path.join(a.sum_dir, sym)
        if not os.path.isdir(sdir):
            continue
        for fn in sorted(os.listdir(sdir)):
            if not fn.endswith(".jsonl"):
                continue
            with open(os.path.join(sdir, fn), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        h = r["hour"]
                    except (ValueError, KeyError):
                        continue
                    by_hour[h][sym] = r
                    n_rows += 1

    if not by_hour:
        raise SystemExit("сводки пусты")

    hours = sorted(by_hour)
    print(f"сводок: {n_rows} строк, {len(symbols)} символов, "
          f"{len(hours)} часов: {hours[0]} … {hours[-1]}")
    print(f"пригодность: охват ≥ {MIN_SPAN:.0f} с, дыра ≤ {MAX_GAP:.0f} с; "
          f"запасное правило по числу ≥ {MIN_SNAPS}; "
          f"сечение — от {MIN_SECTION} имён\n")

    has_span = sum(1 for h in hours for r in by_hour[h].values()
                   if r.get("snap_span_sec") is not None)
    print(f"строк с охватом (новый формат): {has_span} из {n_rows}"
          + ("  — ОСТАЛЬНЫЕ судятся числом снимков" if has_span < n_rows
             else ""))

    print(f"\n{'час':<14}{'имён':>6}{'годн':>6}{'n_snap':>9}"
          f"{'охват':>8}{'дыра':>8}   почему отсеяны")
    good_hours = 0
    for h in hours[-a.hours:]:
        rows = by_hour[h]
        ns, sp, gp = [], [], []
        ok = 0
        why = defaultdict(int)
        for r in rows.values():
            n = r.get("n_snap") or 0
            s = r.get("snap_span_sec")
            g = r.get("snap_gap_max_sec")
            ns.append(n)
            if s is not None:
                sp.append(s)
            if g is not None:
                gp.append(g)
            if r.get("mid_close") is None:
                why["нет цены"] += 1
                continue
            if s is None or g is None:
                if n >= MIN_SNAPS:
                    ok += 1
                else:
                    why["мало снимков (старый формат)"] += 1
                continue
            if s < MIN_SPAN:
                why["охват мал"] += 1
            elif g > MAX_GAP:
                why["дыра велика"] += 1
            else:
                ok += 1
        if ok >= MIN_SECTION:
            good_hours += 1
        top = ", ".join(f"{k}: {v}" for k, v in
                        sorted(why.items(), key=lambda x: -x[1])[:2])
        print(f"{h:<14}{len(rows):>6}{ok:>6}{med(ns) or 0:>9.0f}"
              f"{(med(sp) if sp else 0):>8.0f}{(med(gp) if gp else 0):>8.0f}"
              f"   {top}")

    print(f"\nчасов-сечений среди показанных: {good_hours} из "
          f"{len(hours[-a.hours:])}")


if __name__ == "__main__":
    main()
