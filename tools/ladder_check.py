#!/usr/bin/env python3
"""Исполнители Ladder — только чтение (11.11): режим и статус подписок
(без ключей и аккаунтов), процессы `bot ladder`, возраст статусов и хвост
журнала супервизора по каждой подписке. Ничего не меняет и не запускает."""
import glob
import os
import sqlite3
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "app_api", "out")


def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(float(t))) if t else "-"


con = sqlite3.connect(f"file:{os.path.join(OUT, 'app.sqlite')}?mode=ro", uri=True)
print("подписки (id, книга, депозит, режим, статус, создана, взведена):")
for sid, book, dep, mode, status, created, armed in con.execute(
        "SELECT id, book, deposit, mode, status, created, armed_at FROM subscriptions ORDER BY created"):
    print(f"  {sid}: {book} ${dep:g}, {mode}, {status}, создана {ts(created)}, взведена {ts(armed)}")
print("\nсобытия подписок за 5 суток (вид, время, текст):")
for t, kind, text in con.execute(
        "SELECT ts, kind, text FROM events WHERE ts > ? AND (kind LIKE '%sub%' OR kind LIKE '%mode%' OR kind LIKE '%live%' "
        "OR text LIKE '%sub_%') ORDER BY ts", (time.time() - 5 * 86400,)):
    print(f"  {ts(t)} {kind}: {str(text)[:160]}")
ps = subprocess.run(["pgrep", "-af", "bot ladder"], capture_output=True, text=True).stdout
print("\nпроцессы bot ladder:", "\n  " + "\n  ".join(l[:160] for l in ps.splitlines() if "pgrep" not in l) if ps.strip() else "нет")
for f in sorted(glob.glob(os.path.join(ROOT, "bot", "out", "dca", "*", "ladder_status.json"))):
    print(f"статус {os.path.basename(os.path.dirname(f))}: изменён {ts(os.path.getmtime(f))}")
lg = os.path.join(OUT, "ladder_run.log")
try:
    lines = open(lg, encoding="utf-8").read().splitlines()
    want = [l for l in lines if "sub_13a2" in l or "упал" in l or "ошиб" in l.lower() or "error" in l.lower()]
    print(f"\nжурнал супервизора: строк {len(lines)}, последняя: {lines[-1][:200] if lines else '-'}")
    print("по подписке sub_13a2 и ошибки (последние 25):\n  " + "\n  ".join(l[:220] for l in want[-25:]))
except OSError as e:
    print(f"журнал супервизора: {e}")
