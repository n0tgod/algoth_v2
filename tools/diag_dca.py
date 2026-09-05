#!/usr/bin/env python3
"""Идёт ли прогон бумажных DCA-книг и докуда дошёл.

Длинный прогон снаружи неотличим от повисшего: очередь отдаёт лог
задания только по завершении, а `status` перечисляет постоянные
процессы. Здесь печатается ровно то, что различает эти случаи, — живой
процесс, возраст артефакта и ХВОСТ собственного лога прогона.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "research/dca_paper/out/daily.log")
ART = os.path.join(ROOT, "research/dca_paper/out/DCA-paper.json")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    try:
        ps = subprocess.run(["pgrep", "-af", "dca_paper/run_paper.py"],
                            capture_output=True, text=True).stdout.strip()
    except OSError as e:
        ps = f"pgrep недоступен: {e}"
    print("--- процесс ---")
    print(ps or "не запущен")
    print("--- артефакт ---")
    if os.path.exists(ART):
        age = time.time() - os.path.getmtime(ART)
        print(f"{ART}: обновлён {age / 60:.1f} мин назад, "
              f"{os.path.getsize(ART)} байт")
    else:
        print("артефакта нет")
    print(f"--- хвост {LOG} ---")
    if not os.path.exists(LOG):
        print("лога нет — прогон ещё не писал")
        return
    age = time.time() - os.path.getmtime(LOG)
    print(f"(последняя запись {age / 60:.1f} мин назад)")
    with open(LOG, encoding="utf-8", errors="replace") as fh:
        tail = fh.readlines()[-n:]
    for ln in tail:
        print(ln.rstrip())


if __name__ == "__main__":
    main()
