#!/usr/bin/env python3
"""Установка пакетов в окружение сервера через очередь заданий.

Зачем. SSH к серверу нет (наружу открыты 80 и 443), а очередь заданий
запускает только питон-файлы из репозитория. Пакета, которого нет в
`.venv`, поставить было нечем — кроме рук владельца. Узкое место всплыло
25.09 на замере сжатия записи (нужен `zstandard`) и на выгрузке записи в
объектное хранилище (нужен `boto3`).

Что можно. Имена пакетов — буквы, цифры, `-`, `_`, `.`, необязательно
точная версия `==x.y`; никаких путей, ссылок и опций pip: строка задания
проверяется посимвольно и так, но pip принимает файлы и URL, и второй
забор здесь свой. Ставится в `.venv` репозитория тем же pip, что и
README (§установка). После установки печатается версия КАЖДОГО пакета —
признак результата содержимым, а не кодом выхода pip; пакет без версии
означает отказ прогона.

    run tools/venv_add.py zstandard boto3
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIP = os.path.join(ROOT, ".venv", "bin", "pip")
PY = os.path.join(ROOT, ".venv", "bin", "python")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(==[A-Za-z0-9.]+)?$")


def bad_names(names):
    return [n for n in names if not NAME.match(n)]


def version_of(py, name):
    """Версия установленного дистрибутива; None — не установлен."""
    dist = name.split("==")[0]
    r = subprocess.run(
        [py, "-c", "import importlib.metadata as m, sys; "
                   "print(m.version(sys.argv[1]))", dist],
        capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main(argv=None, pip=PIP, py=PY, log=print):
    names = list(sys.argv[1:] if argv is None else argv)
    if not names:
        log("пакеты не названы")
        return 2
    bad = bad_names(names)
    if bad:
        log(f"ОТКАЗ: недопустимое имя пакета: {bad}")
        return 2
    r = subprocess.run([pip, "install", "--disable-pip-version-check", "-q",
                        *names], capture_output=True, text=True)
    if r.stdout.strip():
        log(r.stdout.strip()[-2000:])
    if r.stderr.strip():
        log(r.stderr.strip()[-2000:])
    if r.returncode != 0:
        log(f"pip завершился с кодом {r.returncode}")
        return 1
    missing = 0
    for n in names:
        v = version_of(py, n)
        if v is None:
            missing += 1
            log(f"пакет {n}: НЕ установлен (pip промолчал)")
        else:
            log(f"пакет {n}: версия {v}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
