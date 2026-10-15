#!/usr/bin/env python3
"""Размеры кэшей прогонов книг на диске (15.10): ноги листа, куски журнала,
бары, контекст издержек, кэши реплея. Ничего не меняет.

    run tools/cache_sizes.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PATHS = ["research/dca_ladder/out/legs_cache.pkl", "research/dca_paper/out/journal_cache",
         "research/dca_paper/out/bars_cache", "research/dca_paper/out/costs_context.pkl",
         "research/dca_paper/out/replay_cache.pkl", "research/dca_paper/out",
         "research/s8_loop/out/model_sit/sheets.jsonl"]


def du(p):
    if os.path.isfile(p):
        return os.path.getsize(p), 1
    tot, n = 0, 0
    for dp, _d, fs in os.walk(p):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
                n += 1
            except OSError:
                pass
    return tot, n


def main():
    for rel in PATHS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print(f"{rel}: нет")
            continue
        b, n = du(p)
        print(f"{rel}: {b / 1048576:.1f} МБ, файлов {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
