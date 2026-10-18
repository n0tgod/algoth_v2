#!/usr/bin/env python3
"""Хвост лога сборщика новостей и строки сторожа о нём (только чтение).

Лог `research/news/out/collect.log` в git не идёт; это задание выносит его
хвост в лог очереди, чтобы «почему не лёг срез» решалось фактом.

    run research/news/peek_log.py
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in ("research/news/out/collect.log", "research/b1_book/out/watchdog.log"):
    full = os.path.join(ROOT, p)
    print(f"== {p}: {'есть' if os.path.exists(full) else 'НЕТ'}")
    if os.path.exists(full):
        with open(full, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        keep = lines[-40:] if "news" in p else [x for x in lines[-3000:] if "новост" in x or "состояние рынка" in x][-15:]
        print("".join(keep).rstrip())
print("== процессы")
print(subprocess.run(["pgrep", "-af", "news/collect.py"], capture_output=True, text=True).stdout.strip() or "нет")
print("== сторож в cron")
print(subprocess.run(["bash", "-c", "crontab -l 2>/dev/null | grep -n watchdog"], capture_output=True, text=True).stdout.strip() or "не найден")
