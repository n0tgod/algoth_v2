#!/usr/bin/env python3
"""Кто держит память на сервере — через очередь заданий.

Повод (28.09). После блокировки IP хостером часовой цикл S8 убивало
ядро по памяти при КАЖДОМ подъёме сторожем: 28 убийств с 14:37 по
17:10, по 4.1–4.2 ГБ каждое. `status` печатает список процессов без
памяти и без возраста, `logtail` — логи по окну времени; ни один не
отвечает на вопрос «кто держит остальные 3.5 ГБ». Этот печатает
`free`, процессы по убыванию RSS с возрастом, все убийства ядра за день
и хвосты логов прогонов БЕЗ фильтра по метке времени (прогон печатает
строки без метки, и окно их не видит). Только чтение.

    run tools/memtop.py --day 2026-09-28 --tail 40
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = ("research/s8_loop/out/train.log",
        "research/dca_paper/out/short.log",
        "research/dca_paper/out/daily.log",
        "research/dca_paper/out/pair.log",
        "research/b1_book/out/collect.log",
        "research/b1_book/out/watchdog.log",
        "research/b1_book/out/ship.log",
        "research/a1_universe/out/refresh.log",
        "research/a1_universe/out/instruments.log",
        "research/s8_loop/out/model/train_log.jsonl")
PS_TOP = 18
ARGS_W = 150


def sh(cmd, timeout=60):
    """stdout команды строками; ошибка — одной строкой с причиной."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:                                    # noqa: BLE001
        return [f"не выполнилось: {e}"]
    out = (r.stdout or "").splitlines()
    if r.returncode and not out:
        out = [f"код {r.returncode}: {(r.stderr or '').strip()[:200]}"]
    return out


def ps_rows(lines, top=PS_TOP, width=ARGS_W):
    """Строки `ps -eo pid,ppid,rss,etimes,args` → (pid, ppid, МБ, возраст, args).

    RSS в килобайтах переводится в мегабайты, возраст — в «чч:мм»;
    заголовок и строки не по форме пропускаются, аргументы режутся.
    """
    rows = []
    for ln in lines:
        parts = ln.split(None, 4)
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            rss_mb = int(parts[2]) // 1024
            secs = int(parts[3])
        except ValueError:
            continue
        rows.append((int(parts[0]), int(parts[1]), rss_mb,
                     f"{secs // 3600:02d}:{secs % 3600 // 60:02d}",
                     parts[4][:width]))
    rows.sort(key=lambda r: -r[2])
    return rows[:top]


def tail_lines(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            got = f.readlines()
    except OSError as e:
        return None, f"не читается: {e}"
    return [ln.rstrip() for ln in got[-n:]], f"строк всего {len(got)}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="ГГГГ-ММ-ДД UTC — убийства ядра с начала этого дня")
    ap.add_argument("--tail", type=int, default=40, help="строк хвоста на лог")
    a = ap.parse_args(argv)
    print(f"== free -m ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC) ==")
    for ln in sh(["free", "-m"]):
        print("  " + ln)
    print(f"\n== процессы по памяти (RSS, МБ; возраст чч:мм; первые {PS_TOP}) ==")
    rows = ps_rows(sh(["ps", "-eo", "pid,ppid,rss,etimes,args", "--no-headers"]))
    print(f"  всего памяти у первых {PS_TOP}: {sum(r[2] for r in rows)} МБ")
    for pid, ppid, mb, age, args in rows:
        print(f"  {pid:>8} {ppid:>8} {mb:>6} {age:>7}  {args}")
    print(f"\n== убийства ядра с {a.day} 00:00 UTC ==")
    got = [ln for ln in sh(["journalctl", "-k", "--utc", "--since", f"{a.day} 00:00:00",
                            "--no-pager", "-o", "short-iso"], timeout=120)
           if "Out of memory" in ln or "oom_reaper" in ln]
    kills = [ln for ln in got if "Out of memory: Killed" in ln]
    print(f"  строк {len(got)}, убийств {len(kills)}")
    # Первое и последнее убийство — всегда, даже когда список обрезан:
    # по ним видно, КОГДА началась петля, а не только что она есть.
    if kills:
        print("  первое: " + kills[0][:220])
        print("  последнее: " + kills[-1][:220])
    for ln in got[-30:]:
        print("  " + ln[:220])
    for rel in LOGS:
        p = os.path.join(ROOT, rel)
        print(f"\n== {rel} (хвост {a.tail}) ==")
        if not os.path.exists(p):
            print("  (файла нет)")
            continue
        lines, note = tail_lines(p, a.tail)
        print(f"  {note}")
        for ln in lines or ():
            print("  " + ln[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
