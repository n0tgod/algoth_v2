#!/usr/bin/env python3
"""Выдержка логов сервера за окно времени — через очередь заданий.

Повод (28.09). IP сервера был заблокирован хостером с ≈ 10:20 до
≈ 17:05 UTC: страниц нет, SSH висит, публикаций нет. Снаружи видно
только «сервер не отвечает», а что делали процессы в эти часы — лежит в
логах на сервере, которые никто не читает. Задание печатает выдержки за
окно: журнал сторожа, системный журнал (ошибки и предупреждения) и
сообщения ядра. Только чтение; пути — фиксированный список.

    run tools/logtail.py --since 2026-09-28-10 --until 2026-09-28-12
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = ("research/b1_book/out/watchdog.log", "research/b1_book/out/ship.log",
        "research/b1_book/out/collect.log", "research/dca_paper/out/short.log")
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})")


def hour(s):
    return datetime.strptime(s, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)


def in_window(line, a, b):
    m = STAMP.search(line)
    if not m:
        return False
    try:
        t = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}",
                              "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return a <= t <= b


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ГГГГ-ММ-ДД-ЧЧ UTC")
    ap.add_argument("--until", required=True, help="ГГГГ-ММ-ДД-ЧЧ UTC")
    ap.add_argument("--max", type=int, default=120, help="строк на источник")
    a = ap.parse_args(argv)
    t0, t1 = hour(a.since), hour(a.until)
    for rel in LOGS:
        p = os.path.join(ROOT, rel)
        print(f"\n== {rel} ==")
        if not os.path.exists(p):
            print("  (файла нет)")
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                got = [ln.rstrip() for ln in f if in_window(ln, t0, t1)]
        except OSError as e:
            print(f"  не читается: {e}")
            continue
        print(f"  строк в окне {len(got)}")
        for ln in got[-a.max:]:
            print("  " + ln[:220])
    since = t0.strftime("%Y-%m-%d %H:%M:%S")
    until = t1.strftime("%Y-%m-%d %H:%M:%S")
    for title, cmd in (("journalctl (warning и выше)",
                        ["journalctl", "--utc", "--since", since, "--until", until,
                         "-p", "warning", "--no-pager", "-o", "short-iso"]),
                       ("journalctl sshd/cron",
                        ["journalctl", "--utc", "--since", since, "--until", until,
                         "-u", "ssh", "-u", "cron", "--no-pager", "-o", "short-iso"]),
                       ("dmesg -T (память, диск, сеть)",
                        ["sh", "-c", "dmesg -T 2>/dev/null | grep -iE 'out of memory|killed process|"
                                     "i/o error|remount|link is down|link becomes ready|nf_conntrack' | tail -40"])):
        print(f"\n== {title} ==")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            lines = (r.stdout or "").splitlines()
            print(f"  строк {len(lines)}" + (f"; stderr: {r.stderr.strip()[:200]}" if r.stderr.strip() else ""))
            for ln in lines[-a.max:]:
                print("  " + ln[:220])
        except Exception as e:                                # noqa: BLE001
            print(f"  не выполнилось: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
