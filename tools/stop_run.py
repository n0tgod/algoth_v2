#!/usr/bin/env python3
"""Остановить ИДУЩИЙ прогон очереди по пути скрипта — и ничего кроме него.

Зачем. У очереди заданий нет отмены: задание уходит отцепленно, и снять
его снаружи было нечем. 2026-09-06 это стоило часового цикла: прогон D10
(2.1 ГБ) рядом со сборщиком (1.5 ГБ) не оставил циклу его 3.3 ГБ на шаге
матрицы — машина 7.7 ГБ без свопа, — и ядро убивало `train.py` без
трассировки каждые 5 минут, при каждом подъёме сторожем.

Границы — именем, а не доверием к вызывающему: останавливается только
процесс вида `python research/<…>.py` или `python tools/<…>.py`, чей
путь РАВЕН аргументу; сборщик, цикл обучения, живой исполнитель, сторож
и сама очередь под запретом всегда. TERM, ожидание до 30 с, затем KILL.
Кого нашёл и чем кончилось — печатается; никого — говорится словами.

Запуск заданием очереди:
  run tools/stop_run.py research/dca_ladder/run_d10.py
  run tools/stop_run.py research/dca_ladder/run_d10.py --dry-run
"""
import os
import signal
import subprocess
import sys
import time

PROTECTED = ("b1_book/collect.py", "s8_loop/train.py", "bot live",
             "tools/jobs.sh", "tools/watchdog_book.sh", "tools/stop_run.py",
             "tools/run_live.sh", "tools/run_bot.sh")
WAIT_S = 30


def allowed(script):
    """Путь, который вообще можно останавливать: research/… или tools/…,
    оканчивается на .py, без «..», не из защищённого списка."""
    if not isinstance(script, str) or ".." in script or script.startswith("/"):
        return False
    if not (script.startswith("research/") or script.startswith("tools/")):
        return False
    if not script.endswith(".py"):
        return False
    return not any(p in script for p in PROTECTED)


def match(ps_lines, script):
    """Строки `ps -eo pid,args` → pid процессов `python <script> …`."""
    out = []
    for ln in ps_lines:
        parts = ln.split()
        if len(parts) < 3:
            continue
        pid, exe, arg = parts[0], parts[1], parts[2]
        if not pid.isdigit() or "python" not in os.path.basename(exe):
            continue
        if arg == script:
            out.append(int(pid))
    return out


def ps_lines():
    r = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True,
                       text=True)
    return r.stdout.splitlines()[1:]


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop(pids, log=print):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            log(f"TERM → {pid}")
        except ProcessLookupError:
            log(f"{pid}: уже нет")
    t0 = time.time()
    while time.time() - t0 < WAIT_S and any(alive(p) for p in pids):
        time.sleep(1)
    left = [p for p in pids if alive(p)]
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
            log(f"KILL → {pid} (не вышел за {WAIT_S} с)")
        except ProcessLookupError:
            pass
    time.sleep(1)
    return [p for p in pids if alive(p)]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    args = [a for a in argv if a != "--dry-run"]
    if len(args) != 1:
        print("нужен ровно один аргумент: путь скрипта research/… или tools/…")
        return 2
    script = args[0]
    if not allowed(script):
        print(f"ОТКАЗ: {script} останавливать нельзя (только research/…py "
              f"и tools/…py, не сборщик, не цикл, не исполнитель)")
        return 3
    pids = match(ps_lines(), script)
    if not pids:
        print(f"процесс `python {script}` не найден — останавливать нечего")
        return 0
    print(f"найдено {len(pids)}: {', '.join(map(str, pids))}")
    if dry:
        print("пробный запуск: ничего не остановлено")
        return 0
    left = stop(pids)
    if left:
        print(f"ОШИБКА: живы после KILL: {left}")
        return 1
    print(f"остановлено: {', '.join(map(str, pids))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
