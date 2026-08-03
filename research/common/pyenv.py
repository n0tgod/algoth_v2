#!/usr/bin/env python3
"""
Запуск не тем интерпретатором — отказ, который повторяется вечно.

Системный `python3` на сервере зависимостей не имеет, они лежат в
`.venv`. Факт этот записан в README, и всё равно стоил уже двух
падений: сперва прогон R1 упал на `ModuleNotFoundError: numpy`, потом я
сам продиктовал владельцу команду с `python3` и получил то же самое.

Записать в документ оказалось недостаточно: команды приходят из
переписки, а не из README. Поэтому проверка живёт в коде и чинит себя
сама — если numpy нет, а рядом есть `.venv`, скрипт перезапускается им
и говорит об этом строкой. Молчать нельзя: подмена интерпретатора,
которую не видно, однажды объяснит непонятное поведение.

Перезапуск делается ровно один раз (метка в окружении), только когда
нужного модуля нет и только когда `.venv` существует. Если venv нет —
печатается команда, которой чинится, а не голый traceback.

Только стандартная библиотека: модуль обязан работать ДО того, как
станет ясно, что зависимостей нет.
"""

import os
import sys

MARK = "ALGOTH_REEXEC"


def repo_root(start=None):
    """Корень репозитория — по каталогу `research` рядом с `.venv`."""
    d = os.path.abspath(start or os.path.dirname(
        os.path.abspath(sys.argv[0] or __file__)))
    while True:
        if os.path.isdir(os.path.join(d, "research")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def venv_python(root=None):
    root = root or repo_root()
    if not root:
        return None
    p = os.path.join(root, ".venv", "bin", "python")
    return p if os.path.exists(p) else None


def need(*modules):
    """Убедиться, что модули доступны; иначе перезапуститься из .venv.

    Возвращает управление, если всё на месте. Иначе либо заменяет
    процесс интерпретатором из `.venv`, либо выходит с внятной
    командой — но не с голым `ModuleNotFoundError`.
    """
    import importlib.util
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if not missing:
        return
    py = venv_python()
    if py and os.path.realpath(py) != os.path.realpath(sys.executable) \
            and not os.environ.get(MARK):
        # Говорим о подмене вслух: тихий перезапуск другим
        # интерпретатором однажды объяснял бы непонятное поведение.
        print(f"нет модулей: {', '.join(missing)} — перезапускаюсь из "
              f"{py}", flush=True)
        os.environ[MARK] = "1"
        os.execv(py, [py] + sys.argv)
    root = repo_root() or "."
    raise SystemExit(
        f"нет модулей: {', '.join(missing)}.\n"
        f"Зависимости живут в .venv, системный python3 их не имеет.\n"
        f"Запускать так:\n"
        f"    cd {root} && .venv/bin/python {sys.argv[0]} "
        + " ".join(sys.argv[1:]))
