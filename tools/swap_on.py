#!/usr/bin/env python3
"""Файл подкачки на корневом диске — одной строкой очереди, по решению владельца.

Повод (02.10). Машина 7.7 ГБ без свопа: обучение S8 (2.5–3.7 ГБ пиком),
сборщик (1.5–2.4 ГБ), часовые прогоны книг и суточные турнир и фабрика
вместе не помещаются, ядро убивало обучение 10–13 раз в сутки. Своп
на корне (72 ГБ свободно) отдаёт холодные страницы матриц диску и
снимает убийства; горячие страницы сборщика ядро держит в памяти.

Запуск БЕЗ `--apply` ничего не меняет и печатает состояние и план:

    run tools/swap_on.py --size-gb 4
    run tools/swap_on.py --size-gb 4 --apply --persist

`--persist` дописывает строку в /etc/fstab (одну, если её ещё нет), чтобы
своп переживал перезагрузку. Повторный запуск с существующим файлом
ничего не портит: сообщает и выходит.
"""
import argparse
import os
import shutil
import subprocess
import sys

SWAPFILE = "/swapfile"
FSTAB = "/etc/fstab"
FSTAB_LINE = f"{SWAPFILE} none swap sw 0 0"
MIN_FREE_GB_AFTER = 20          # на корне после создания файла


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def state():
    """Что есть сейчас: активные свопы, файл, строка fstab, место на корне."""
    _, swaps, _ = sh(["swapon", "--show", "--noheadings", "--bytes"])
    exists = os.path.exists(SWAPFILE)
    size = os.path.getsize(SWAPFILE) if exists else 0
    try:
        with open(FSTAB, encoding="utf-8") as f:
            in_fstab = any(ln.split() and ln.split()[0] == SWAPFILE
                           for ln in f if not ln.lstrip().startswith("#"))
    except OSError:
        in_fstab = False
    free_gb = shutil.disk_usage("/").free / 2**30
    return {"active": swaps, "file": exists, "size_gb": round(size / 2**30, 2),
            "fstab": in_fstab, "root_free_gb": round(free_gb, 1)}


def plan(st, size_gb, persist):
    """Шаги, которые нужны; пустой список — делать нечего."""
    steps = []
    if SWAPFILE in st["active"]:
        return steps, "своп уже активен"
    if st["file"] and abs(st["size_gb"] - size_gb) > 0.05:
        return steps, (f"файл {SWAPFILE} уже есть размером {st['size_gb']} ГБ, "
                       f"а просили {size_gb}: решать руками, ничего не делаю")
    if st["root_free_gb"] - (0 if st["file"] else size_gb) < MIN_FREE_GB_AFTER:
        return steps, (f"на корне останется меньше {MIN_FREE_GB_AFTER} ГБ "
                       f"(свободно {st['root_free_gb']}), не делаю")
    if not st["file"]:
        steps += [["fallocate", "-l", f"{size_gb}G", SWAPFILE],
                  ["chmod", "600", SWAPFILE], ["mkswap", SWAPFILE]]
    steps.append(["swapon", SWAPFILE])
    if persist and not st["fstab"]:
        steps.append(["fstab-append"])
    return steps, "ok"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--size-gb", type=int, required=True, choices=(2, 3, 4, 6, 8))
    ap.add_argument("--apply", action="store_true", help="выполнить, а не только показать")
    ap.add_argument("--persist", action="store_true", help="дописать в fstab")
    a = ap.parse_args(argv)
    st = state()
    print(f"состояние: {st}")
    steps, why = plan(st, a.size_gb, a.persist)
    print(f"план: {why}; шагов {len(steps)}")
    for s in steps:
        print("  " + " ".join(s))
    if not a.apply or not steps:
        print("ничего не менял" if not a.apply else "делать нечего")
        return 0
    for s in steps:
        if s == ["fstab-append"]:
            with open(FSTAB, "a", encoding="utf-8") as f:
                f.write(FSTAB_LINE + "\n")
            print(f"  fstab: дописано «{FSTAB_LINE}»")
            continue
        rc, out, err = sh(s)
        print(f"  {' '.join(s)} → код {rc}" + (f": {err[:200]}" if rc else ""))
        if rc:
            return 1
    print(f"после: {state()}")
    _, free, _ = sh(["free", "-m"])
    print(free)
    return 0


if __name__ == "__main__":
    sys.exit(main())
