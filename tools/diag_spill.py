#!/usr/bin/env python3
"""Проверка перелива записи: читаются ли перелитые часы ПО ПРЕЖНЕМУ пути.

После `spill_book.py` старые сжатые часы лежат на корне, а на томе —
ссылки. Ссылка, ведущая в пустоту, снаружи неотличима от файла, пока её
не откроют; читатели записи (`store.read_hour`) открывают по прежнему
пути. Здесь несколько перелитых часов открываются именно так, и
печатается число строк, а не «файл есть». Плюс `df` обеих сторон,
число ссылок и хвост `spill.log`. Читает и печатает, ничего не меняет.
"""
import os
import random
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "b1_book"))
import store as ST                                            # noqa: E402

OUT = os.path.join(ROOT, "research", "b1_book", "out")
SPILL = os.path.join(os.path.dirname(ROOT), "b1_spill")


def sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                           text=True, timeout=600)
        return (p.stdout + p.stderr).strip() or "(пусто)"
    except Exception as e:                                # noqa: BLE001
        return f"(не выполнено: {e})"


def main():
    print("=== df ===")
    print(sh(f"df -h '{OUT}' / | tail -2"))
    print("\n=== ссылок в book/ и trades/ (find -type l) ===")
    for sub in ("book", "trades"):
        print(f"{sub}: " + sh(f"find '{OUT}/{sub}' -type l | wc -l"))
    print("\n=== чтение перелитых часов по прежнему пути ===")
    random.seed(int(time.time()))
    links = sh(f"find '{OUT}/book' -type l | shuf -n 5 2>/dev/null").splitlines()
    ok = 0
    for p in links:
        if not p or not os.path.islink(p):
            continue
        d, fn = os.path.dirname(p), os.path.basename(p)
        hour = fn.replace(".jsonl.gz", "")
        try:
            rows = ST.read_hour(d, hour)
            n = len(rows) if rows is not None else -1
        except Exception as e:                            # noqa: BLE001
            n = f"ОШИБКА {e}"
        tgt = os.readlink(p)
        print(f"  {os.path.basename(d)}/{fn}: строк {n}; → {tgt} "
              f"({'есть' if os.path.isfile(tgt) else 'НЕТ ФАЙЛА'})")
        if isinstance(n, int) and n > 0:
            ok += 1
    print(f"прочитано с данными {ok} из {len([x for x in links if x])}")
    print("\n=== spill.log (хвост) ===")
    print(sh(f"tail -5 '{SPILL}/spill.log'"))
    print(f"\nснято {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC")
    return 0


if __name__ == "__main__":
    sys.exit(main())
