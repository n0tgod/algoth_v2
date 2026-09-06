#!/usr/bin/env python3
"""Диски и куда на самом деле пишется запись стакана — одним заданием.

Повод (2026-09-06): `status` печатает `df` двух точек, и по нему том
150 ГБ (`HC_Volume_*`) занят на 94 %, а корень — на 48 %. Этого мало,
чтобы ответить на вопрос владельца «почему том не используется»: bind
mount после перезагрузки может отвалиться молча, и тогда запись идёт
на корень, а на томе лежит старая копия; второй докупленный том может
быть подключён, но не смонтирован. Здесь печатается: все блочные
устройства (`lsblk`), fstab, точки монтирования каталога записи и
`out/`, `df` ИМЕННО по этим путям, самые свежие файлы записи с их
файловой системой, размеры каталогов. Читает и печатает, ничего не
меняет.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATHS = ["research/b1_book/out", "out", "research/b1_book/out/book",
         "research/s8_loop/out", "research/dca_paper/out"]


def sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                           text=True, timeout=120)
        return (p.stdout + p.stderr).strip() or "(пусто)"
    except Exception as e:                                # noqa: BLE001
        return f"(не выполнено: {e})"


def main():
    print("=== блочные устройства ===")
    print(sh("lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID"))
    print("\n=== fstab ===")
    print(sh("grep -vE '^\\s*#|^\\s*$' /etc/fstab"))
    print("\n=== все монтирования томов и bind ===")
    print(sh("findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -iE "
             "'volume|sdb|sdc|sdd|bind|algoth' || echo '(нет)'"))
    print("\n=== df по всем ФС ===")
    print(sh("df -h -x tmpfs -x devtmpfs -x overlay"))
    for p in PATHS:
        ap = os.path.join(ROOT, p)
        print(f"\n=== {p} ===")
        if not os.path.isdir(ap):
            print("каталога нет")
            continue
        print("точка монтирования: " + sh(f"findmnt -T '{ap}' -rn -o TARGET,SOURCE,FSTYPE"))
        print("df: " + sh(f"df -h '{ap}' | tail -1"))
        print("размер: " + sh(f"du -sh '{ap}' 2>/dev/null | cut -f1"))
    print("\n=== свежайшие файлы записи (где лежат на самом деле) ===")
    bp = os.path.join(ROOT, "research", "b1_book", "out")
    print(sh(f"find '{bp}' -type f -mmin -30 -printf '%TY-%Tm-%Td %TH:%TM %s %p\\n' "
             "2>/dev/null | sort | tail -5 || echo '(нет)'"))
    print("\n=== самые большие каталоги в out записи ===")
    print(sh(f"du -sh '{bp}'/* 2>/dev/null | sort -h | tail -8"))
    print("\n=== занято корнем вне записи (крупнейшие) ===")
    print(sh(f"du -shx '{ROOT}'/* 2>/dev/null | sort -h | tail -8"))
    print(f"\nснято {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC")
    return 0


if __name__ == "__main__":
    sys.exit(main())
