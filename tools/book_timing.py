#!/usr/bin/env python3
"""Сколько длится прогон книг на тёплом кэше — из логов прогонов (спека 17,
путь 1: каденция 5 минут возможна, только если прогон укладывается).
Печатает последние 8 строк с временем из daily.log, short.log, pair.log
и пики RSS, если прогон их писал. Ничего не меняет.

    run tools/book_timing.py
"""
import os
import re
import sys

LOGS = ("research/dca_paper/out/daily.log", "research/dca_paper/out/short.log", "research/dca_paper/out/pair.log")
RX = re.compile(r"(готово|за \d+(\.\d+)? с|\d+(\.\d+)? с\b|RSS|МБ|строк|решений|позиций)")


def main():
    for p in LOGS:
        print(f"== {p} ==")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-4000:]
        except OSError as e:
            print("нет:", e)
            continue
        hits = [ln.rstrip() for ln in lines if RX.search(ln)]
        for ln in hits[-14:]:
            print(" ", ln[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
