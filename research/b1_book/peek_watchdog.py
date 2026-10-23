#!/usr/bin/env python3
"""Заглянуть в сторож и цикл S8 за окно часов (только чтение): почему книги
не считались (строки «отложен», память, обучение), когда шло обучение, когда
стоял флаг ожидания. 23.10: книги стояли с 01:05 до 08:50 UTC.

    run research/b1_book/peek_watchdog.py 2026-10-23T00 2026-10-23T09
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WD = os.path.join(HERE, "out", "watchdog.log")
TRAIN = os.path.join(ROOT, "research", "s8_loop", "out", "train.log")
FLAG = os.path.join(ROOT, "research", "s8_loop", "out", "train_wait.flag")
WORDS = ("отложен", "обучен", "книги", "память", "уступ", "MemAvailable", "короткие", "общий", "бумажные", "прогон")


def window(path, lo, hi, words, limit=160):
    print(f"== {os.path.relpath(path, ROOT)}: {'есть' if os.path.exists(path) else 'НЕТ'}")
    if not os.path.exists(path):
        return
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", line)
            if not m:
                continue
            key = m.group(1) + "T" + m.group(2)
            if lo <= key <= hi and any(w in line for w in words):
                out.append(line.rstrip())
    if len(out) > limit:
        out = out[:limit // 2] + [f"… ещё {len(out) - limit} строк …"] + out[-limit // 2:]
    print("\n".join(out))


def main():
    lo = sys.argv[1] if len(sys.argv) > 1 else "2026-10-23T00"
    hi = sys.argv[2] if len(sys.argv) > 2 else "2026-10-23T09"
    try:
        st = os.stat(FLAG)
        print(f"train_wait.flag: есть, изменён {time.strftime('%FT%TZ', time.gmtime(st.st_mtime))}")
    except OSError:
        print("train_wait.flag: нет")
    window(WD, lo, hi, WORDS)
    window(TRAIN, lo, hi, ("обуч", "жд", "памят", "сводк", "час", "конец", "начал", "книг", "RSS", "МБ"), limit=80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
