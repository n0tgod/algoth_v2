#!/usr/bin/env python3
"""Диагностика API приложения на сервере, только чтение: слушает ли
порт, хвост журнала запросов (адрес, метод, путь, код — без токенов и
тел), счётчики базы без секретов, последние события. Нужна, когда с
телефона «ничего не происходит»: отличить «запрос не дошёл» от «дошёл
и отвергнут».

    run tools/app_api/diag.py
"""
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def main():
    try:
        ss = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=10).stdout
        print("порт 443:", "слушает" if ":443 " in ss else "НЕ слушает")
    except Exception as e:                                   # noqa: BLE001
        print("ss не выполнился:", e)
    try:
        with open(os.path.join(OUT, "status.json"), encoding="utf-8") as f:
            print("status.json:", f.read().strip())
    except OSError:
        print("status.json нет")
    log = os.path.join(OUT, "server.log")
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        print(f"журнал запросов: строк {len(lines)}, последние 40:")
        for ln in lines[-40:]:
            print("  " + ln.rstrip())
    except OSError:
        print("журнала запросов нет")
    db = os.path.join(OUT, "app.sqlite")
    if os.path.exists(db):
        c = sqlite3.connect(db)
        for t in ("accounts", "sessions", "exchange_keys", "subscriptions", "events"):
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t}: {n}")
        print("аккаунты (без секретов):")
        for r in c.execute("SELECT id, role, apple_sub IS NOT NULL, status, datetime(created,'unixepoch') FROM accounts"):
            print("  ", r)
        print("последние события:")
        for r in c.execute("SELECT datetime(ts,'unixepoch'), account_id, kind, text FROM events ORDER BY id DESC LIMIT 15"):
            print("  ", r)
    else:
        print("базы нет")
    print("LIVE_ENABLED:", os.path.exists(os.path.join(OUT, "LIVE_ENABLED")))


if __name__ == "__main__":
    main()
