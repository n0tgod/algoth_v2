#!/usr/bin/env python3
"""Какие модели принимает CLI НА ЭТОЙ машине.

Повод: роли `scout` и `propose` не отработали ни разу с 2026-09-01 —
журнал прогонов (`research/factory/out/agents-runs.jsonl`) показывает у
обеих один и тот же отказ:

    API Error: 400 Claude Code 2.1.220 does not support this model;
    version 2.1.251 or newer is required.

То есть дело не в промпте и не в правах, а в том, что CLI на сервере
старше объявленного идентификатора модели (решение владельца
2026-09-01: `claude-fable-5-1`, запасная `claude-opus-5`). Прежде чем
чинить — измерить: какой идентификатор эта версия принимает, а какой
нет. Гадать нельзя, ошибка стоит суток простоя круга.

Запрос каждой модели — одно слово, чтобы замер не стоил ничего. Ключей
и переменных окружения не печатается: только идентификатор, код
возврата и первая строка ответа.
"""

import os
import subprocess
import sys

IDS = ["claude-fable-5-1", "claude-opus-5", "opus", "sonnet"]
ASK = "Ответь ровно одним словом: ок"


def run(argv, stdin=None, timeout=180):
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except FileNotFoundError:
        return 127, "команды claude нет в PATH"
    except subprocess.TimeoutExpired:
        return 124, f"молчит дольше {timeout} с"


def main():
    rc, out = run(["claude", "--version"])
    print(f"версия CLI: код {rc}, {out.splitlines()[0] if out else '—'}")
    rc, out = run(["claude", "auth", "status"])
    first = out.splitlines()[0] if out else "—"
    print(f"вход: код {rc}, {first}")
    print()
    for mid in IDS:
        rc, out = run(["claude", "-p", "--model", mid], stdin=ASK)
        line = " ".join(out.split())[:200] if out else "—"
        print(f"{mid:20s} код {rc}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
