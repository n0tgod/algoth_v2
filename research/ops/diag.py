"""Снимок состояния сервера: почему что-то не работает.

Только ЧТЕНИЕ: хвосты журналов, наличие процессов, расписание cron,
свежесть артефактов. Ничего не запускает и не чинит — задача одна:
ответить «что случилось», когда сессия видит остановку, а сервера под
рукой нет.

Зовётся очередью заданий (`jobs/`), поэтому лежит в репозитории и не
принимает произвольных путей: список того, что смотреть, объявлен
здесь.

    .venv/bin/python research/ops/diag.py [--lines 40]
"""

import argparse
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# Что смотреть. Список объявлен, а не собирается по маске: иначе
# однажды сюда попадёт файл с ключами.
LOGS = (
    ("цикл обучения", "research/s8_loop/out/train.log"),
    ("сборщик", "research/b1_book/out/collect.log"),
    ("живой исполнитель", "bot/out/live.log"),
    ("сторож", "research/b1_book/out/watchdog.log"),
    ("очередь заданий", "jobs/poke.log"),
)
PROCS = ("b1_book/collect.py", "s8_loop/train.py", "bot live",
         "s10_policy/tournament.py")
STAMPS = (
    ("манифест модели", "research/s8_loop/out/model/manifest.json"),
    ("лист сечения", "research/s8_loop/out/model/scan_sheet.json"),
    ("статус сбора", "research/b1_book/out/status.json"),
    ("статус исполнителя", "bot/out/live/live_status.json"),
)


def tail(path, n):
    p = os.path.join(ROOT, path)
    try:
        with open(p, "rb") as f:
            data = f.read()[-200000:]
    except OSError as e:
        return f"(нет: {e.__class__.__name__})"
    rows = data.decode("utf-8", "replace").splitlines()
    return "\n".join(rows[-n:]) or "(пусто)"


def age(path):
    p = os.path.join(ROOT, path)
    try:
        return round(time.time() - os.path.getmtime(p), 1)
    except OSError:
        return None


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=20, cwd=ROOT)
        return (out.stdout + out.stderr).strip() or "(пусто)"
    except (OSError, subprocess.SubprocessError) as e:
        return f"(не вышло: {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=40)
    args = ap.parse_args()
    n = max(5, min(args.lines, 200))

    print("=== процессы ===", flush=True)
    for pat in PROCS:
        got = run(["pgrep", "-af", pat])
        print(f"{pat}: {'НЕТ' if got == '(пусто)' else got}")

    print("\n=== расписание cron ===", flush=True)
    print(run(["crontab", "-l"]))

    print("\n=== свежесть артефактов (секунд назад) ===", flush=True)
    for name, path in STAMPS:
        a = age(path)
        print(f"{name}: {'нет файла' if a is None else a}")

    for name, path in LOGS:
        print(f"\n=== {name}: {path} ===", flush=True)
        print(tail(path, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
