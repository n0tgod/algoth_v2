#!/usr/bin/env python3
"""Почему молчит цикл обучения: хвост журнала и состояние манифеста.

Заводится потому, что молчащий цикл снаружи неотличим от здорового:
страницы отдают ПРОШЛЫЙ манифест, сборщик пишет книгу как ни в чём не
бывало, а живой исполнитель встаёт по правилу «цикл молчит три часа» —
и первым признаком отказа оказывается остановка живых денег. Спросить
об этом было нечем: очередь заданий пускает только `research/*.py` и
`tools/*.py`, а хвост журнала лежит на сервере.

Печатает: жив ли процесс, возраст манифеста и последнего обучения,
хвост `train.log` — и НЕ печатает ничего, чего нет: отсутствие файла
называется словами, а не пустотой.
"""

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "research", "s8_loop", "out")


def age(p):
    try:
        return time.time() - os.path.getmtime(p)
    except OSError:
        return None


def main(argv=None):
    n = 60
    if argv:
        for a in argv:
            if a.startswith("--tail="):
                n = int(a.split("=", 1)[1])
    r = subprocess.run(["pgrep", "-af", "s8_loop/train.py"],
                       capture_output=True, text=True)
    live = [x for x in r.stdout.splitlines() if x.strip()]
    print("=== процесс цикла ===")
    print("\n".join(live) if live else "НЕ НАЙДЕН — цикл не работает")
    print("\n=== манифест модели ===")
    mp = os.path.join(OUT, "model", "manifest.json")
    a = age(mp)
    if a is None:
        print(f"манифеста нет: {mp}")
    else:
        try:
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError) as e:
            m = {"ошибка чтения": str(e)}
        print(f"возраст {a / 3600:.1f} ч")
        for k in ("trained_at", "train_seq", "cycle_sec",
                  "woke_after_hour_sec", "steps_sec", "canary_ic"):
            if k in m:
                print(f"  {k}: {m[k]}")
    print("\n=== хвост train.log ===")
    lp = os.path.join(OUT, "train.log")
    if not os.path.exists(lp):
        print(f"журнала нет: {lp}")
        return 0
    print(f"возраст {age(lp) / 60:.1f} мин, размер "
          f"{os.path.getsize(lp)} Б")
    with open(lp, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for x in lines[-n:]:
        print(x.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
