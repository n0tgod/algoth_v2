#!/usr/bin/env python3
"""
Обёртка механического шага круга: прогон и ТЕРМИНАЛЬНАЯ строка журнала.

У роли начало и конец пишет `tools/agents_run.sh`. У механического шага
писателя конца не было ВОВСЕ: круг писал только начало, и законно
кончившийся шаг навсегда оставался в журнале начатым — а страница
честно читала это как «прогон оборван». То есть нормальное завершение
было неотличимо от убитого процесса, ровно тот класс отказа, против
которого построена вся система.

Строка конца пишется по ФАКТУ — с кодом возврата, а не выводится из
свежести артефакта: артефакт мог остаться от вчерашнего прогона, а
сегодняшний упасть.

    mech_run.py <ключ> <момент старта> -- <команда...>
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runlog as RL                                       # noqa: E402


def out_dir():
    """Каталог журнала. Подменяется переменной среды — как у роли."""
    return os.environ.get("AGENTS_OUT") or os.path.join(HERE, "out")


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 3 or "--" not in a:
        print("нужно: mech_run.py <ключ> <момент старта> -- <команда>",
              file=sys.stderr)
        return 2
    key, started = a[0], a[1]
    cmd = a[a.index("--") + 1:]
    try:
        started = float(started)
    except ValueError:
        started = time.time()

    runs = os.path.join(out_dir(), RL.RUNS)
    note, rc = None, 1
    # Свой каталог байткода на прогон. Тот же дефект, что в машине
    # контролей: питон считает `.pyc` свежим по паре «mtime в целых
    # секундах, размер», и правка модуля, попавшая в ту же секунду при
    # неизменной длине, оставляет ПРЕЖНИЙ байткод. Здесь цена выше:
    # суточный шаг считал бы старым кодом, ничем себя не выдавая, — а
    # деплой у нас как раз «git pull и следующий такт».
    cache = tempfile.mkdtemp(prefix="pyc-")
    env = dict(os.environ, PYTHONPYCACHEPREFIX=cache)
    try:
        rc = subprocess.call(cmd, cwd=os.path.dirname(
            os.path.dirname(HERE)), env=env)
        note = f"код возврата {rc}"
    except OSError as e:                                  # noqa: BLE001
        # Шаг не запустился вовсе — это тоже конец прогона, и молчать
        # о нём нельзя: иначе несостоявшийся запуск выглядел бы
        # оборванным на полпути.
        note = f"шаг не запустился: {e}"
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    RL.append(runs, key, "ok" if rc == 0 else "fail", started,
              note=note)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
