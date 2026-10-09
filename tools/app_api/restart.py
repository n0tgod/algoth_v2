#!/usr/bin/env python3
"""Перезапуск процесса API приложения со свежим кодом (через очередь).
Останавливает процесс и сразу поднимает новый; сторож поднял бы и сам,
но через 5 минут. Состояние (`out/`) не трогается.

    run tools/app_api/restart.py
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")


def main():
    subprocess.run(["pkill", "-f", "app_api/server.py"], check=False)
    time.sleep(2)
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, "server.log"), "ab")
    subprocess.Popen([os.path.join(ROOT, ".venv", "bin", "python"), os.path.join(HERE, "server.py")],
                     cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(3)
    ss = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True).stdout
    print("порт 443:", "слушает" if ":443 " in ss else "НЕ слушает — смотреть out/server.log")


if __name__ == "__main__":
    main()
