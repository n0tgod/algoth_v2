#!/usr/bin/env python3
"""Добавить допустимую аудиторию токена Apple (Bundle ID приложения) в
`out/apple_audiences.txt` на сервере. Сервер читает файл при каждой
проверке — перезапуск не нужен. Значение — только буквы, цифры, точка,
дефис, подчёркивание.

    run tools/app_api/add_audience.py algoth
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "out", "apple_audiences.txt")
OK = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def main(argv):
    if len(argv) != 1 or not OK.match(argv[0]):
        print("ОТКАЗ: ровно одно значение из букв, цифр, точки, дефиса и подчёркивания")
        return 2
    aud = argv[0]
    have = []
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as f:
            have = [ln.strip() for ln in f if ln.strip()]
    if aud in have:
        print(f"аудитория {aud!r} уже в списке")
    else:
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(aud + "\n")
        print(f"аудитория {aud!r} добавлена")
    with open(PATH, encoding="utf-8") as f:
        print("список:", [ln.strip() for ln in f if ln.strip()])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
