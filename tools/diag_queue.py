#!/usr/bin/env python3
"""Состояние канала заданий и идущих прогонов — одним заданием.

Зачем отдельный файл. Очередь умеет три действия, и ни одно из них не
рассказывает о САМОЙ очереди: `status` снимает сборщика и исполнителя,
а почему очередь молчала — не говорит никто. Один раз это стоило суток
слепоты: публикация оставила коммит локально, дерево разошлось с
`origin/main`, и `jobs.sh` перестал трогать задания — молча, потому что
его вывод уезжает в git той же публикацией, которая и сломалась.

Читает и печатает, ничего не меняет: ни git, ни файлов.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*cmd):
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=60)
        return (p.stdout + p.stderr).strip()
    except Exception as e:                                # noqa: BLE001
        return f"не выполнилось: {e}"


def tail(path, n=12):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return f"{path}: файла нет"
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            rows = f.read().splitlines()
        return "\n".join(rows[-n:]) or f"{path}: пусто"
    except OSError as e:
        return f"{path}: {e}"


def main():
    print("=== ветка и расхождение ===")
    print(run("git", "status", "-sb"))
    print("\n=== последние коммиты ===")
    print(run("git", "log", "--oneline", "-5"))
    print("\n=== впереди / позади origin/main ===")
    print("впереди:", run("git", "rev-list", "--count", "origin/main..HEAD"))
    print("позади: ", run("git", "rev-list", "--count", "HEAD..origin/main"))
    print("\n=== git fetch (проверка доступа) ===")
    print(run("git", "fetch", "--dry-run", "origin", "main") or "молча, то есть успешно")
    print("\n=== состояние очереди ===")
    print(tail("jobs/queue-state.md"))
    print("\n=== хвост журнала сигнала ===")
    print(tail("jobs/poke.log", 20))
    print("\n=== идущие прогоны ===")
    print(run("pgrep", "-af", "python") or "питона не запущено")
    # Хвост лога КАЖДОГО идущего задания: лог публикуется в git только
    # по концу задания, а на диске пишется построчно — без этого ход
    # пятичасового прогона снаружи неотличим от зависшего (2026-09-06).
    print("\n=== хвосты логов идущих заданий ===")
    ps = run("pgrep", "-af", "jobs/done/")
    names = sorted({m for ln in ps.splitlines()
                    for m in re.findall(r"jobs/done/([A-Za-z0-9._-]+)\.log", ln)})
    if not names:
        print("идущих заданий нет")
    for nm in names:
        print(f"--- {nm} ---")
        print(tail(f"jobs/done/{nm}.log", 8))
    print("\n=== склад лесенки ===")
    print(run("ls", "-la", "research/z3_ladder/out/store"))
    print("\n=== хвост лога свёртки ===")
    print(tail("jobs/done/z3-fold-1.log", 15))
    return 0


if __name__ == "__main__":
    sys.exit(main())
