#!/usr/bin/env python3
"""Строки лога по образцу, счётом по дням — через очередь заданий.

Повод (28.09). Ядро убивало часовой цикл 1 862 раза с 20.09, а книги
DCA при этом получали решения — значит, часть часов цикл всё же
проходил. Сколько именно и в какие дни, знает только `train.log`:
строка «матрица: …» печатается после сборки матрицы, «переобучаю» —
перед обучением. Печатает число строк по образцу за каждый день и
последние N совпадений. Только чтение; файлы — из списка.

    run tools/loggrep.py --file train --pattern матрица: --days 10 --last 5
"""
import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {"train": "research/s8_loop/out/train.log",
         "watchdog": "research/b1_book/out/watchdog.log",
         "collect": "research/b1_book/out/collect.log",
         "short": "research/dca_paper/out/short.log",
         "daily": "research/dca_paper/out/daily.log",
         "pair": "research/dca_paper/out/pair.log",
         "ship": "research/b1_book/out/ship.log"}
# Именованные образцы: аргументы задания — только латиница, а слова в
# логах русские. `cycle` — вехи часового цикла: матрица собрана, книги
# посчитаны без обучения (по каденции), обучение начато, цикл закончен.
PRESETS = {"cycle": r"матрица:|обучение пропущено по каденции|обучение отложено по памяти|переобучаю:|цикл закончен",
           "oom": r"Killed|убит|память",
           # строки памяти шагов цикла (`train.mem_line`)
           "mem": r"память \d+ МБ, пик",
           "raise": r"не найден — поднимаю|перезапускаю"}
# Метка дня в строке: «[09-28 17:20:28]» у прогонов, «2026-09-28T…» у сторожа.
STAMP = re.compile(r"\[(\d{2})-(\d{2}) \d{2}:\d{2}:\d{2}\]|(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:")


def day_of(line, year):
    m = STAMP.search(line)
    if not m:
        return None
    if m.group(1):
        return f"{year}-{m.group(1)}-{m.group(2)}"
    return f"{m.group(3)}-{m.group(4)}-{m.group(5)}"


def scan(lines, pattern, days, today=None):
    """(счёт по дням за `days` суток до `today` включительно, совпадения)."""
    today = today or datetime.now(timezone.utc).date()
    keep = {(today - timedelta(days=k)).isoformat() for k in range(days)}
    rx = re.compile(pattern)
    by_day = Counter()
    hits = []
    for ln in lines:
        if not rx.search(ln):
            continue
        d = day_of(ln, today.year)
        if d in keep:
            by_day[d] += 1
            hits.append(ln.rstrip())
    return by_day, hits


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, choices=sorted(FILES))
    ap.add_argument("--pattern", default=None, help="регулярное выражение")
    ap.add_argument("--preset", default=None, choices=sorted(PRESETS),
                    help="именованный образец вместо --pattern")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--last", type=int, default=10, help="последних совпадений")
    a = ap.parse_args(argv)
    pattern = PRESETS[a.preset] if a.preset else a.pattern
    if not pattern:
        ap.error("нужен --pattern или --preset")
    p = os.path.join(ROOT, FILES[a.file])
    print(f"== {FILES[a.file]} по образцу /{pattern}/ за {a.days} сут ==")
    if not os.path.exists(p):
        print("  (файла нет)")
        return 0
    with open(p, encoding="utf-8", errors="replace") as f:
        by_day, hits = scan(f, pattern, a.days)
    print(f"  совпадений {len(hits)}")
    for d in sorted(by_day):
        print(f"  {d}: {by_day[d]}")
    for ln in hits[-a.last:]:
        print("  " + ln[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
