#!/usr/bin/env python3
"""
Что нужно запускалке ролей, и чего на этой машине нет.

Первый боевой прогон роли зависит от вещей вне репозитория: команды
`claude`, ключа API, замка. Каждая отсутствует по-своему и лечится
по-своему, и узнать это надо ДО того, как крон начнёт молча падать
раз в сутки.

Ключ НЕ печатается ни при каких условиях — ни целиком, ни началом, ни
длиной. Докладываются только существование и права: этого достаточно,
чтобы отличить «ключа нет» от «ключ лежит открытым для всех».

    .venv/bin/python research/factory/probe_env.py
"""

import os
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def line(name, ok, note=""):
    print(f"  {'да ' if ok else 'НЕТ'}  {name}" + (f" — {note}" if note else ""))
    return ok


def main():
    print("Что нужно запускалке ролей\n")
    ready = True

    p = shutil.which("claude")
    if p:
        try:
            v = subprocess.run([p, "--version"], capture_output=True,
                               text=True, timeout=30).stdout.strip()
        except Exception as e:                            # noqa: BLE001
            v = f"версию спросить не вышло: {type(e).__name__}"
        ready &= line("команда claude", True, f"{p}, {v}")
    else:
        ready &= line("команда claude", False,
                      "роль позвать нечем; ставится отдельно от репозитория")

    # Путей авторизации ДВА: ключ API и вход CLI по подписке. Роль
    # можно звать любым, и требовать первый было бы лишним расходом.
    kf = os.environ.get("ANTHROPIC_KEY_FILE") or os.path.join(
        os.path.expanduser("~"), ".anthropic", "key")
    auth = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        auth = "ключ API взят из окружения"
    elif os.path.exists(kf):
        mode = stat.S_IMODE(os.stat(kf).st_mode)
        # Права важнее наличия: ключ, открытый всем, — это ключ,
        # который уже утёк. Значение не печатается никогда.
        if mode & 0o077:
            ready &= line("авторизация", False,
                          f"ключ {kf} открыт лишним (права {oct(mode)}), "
                          "нужно 600")
        else:
            auth = f"ключ API из {kf}, права {oct(mode)}"
    elif p:
        # Спрашиваем сам CLI: где он держит состояние входа, знает
        # только он.
        try:
            out = subprocess.run([p, "auth", "status"], timeout=30,
                                 capture_output=True, text=True).stdout
            if '"loggedIn": true' in out.replace('"loggedIn":true',
                                                 '"loggedIn": true'):
                auth = "вход CLI по подписке (claude auth login)"
        except Exception:                                 # noqa: BLE001
            pass
    if auth:
        ready &= line("авторизация", True, auth)
    else:
        ready &= line("авторизация", False,
                      "нужен ЛИБО вход по подписке (claude auth login), "
                      f"ЛИБО ключ API в {kf} с правами 600")

    ready &= line("замок flock", bool(shutil.which("flock")),
                  "нужен, чтобы роли не писали в репозиторий разом")
    ready &= line("запускалка", os.path.exists(
        os.path.join(ROOT, "tools", "agents_run.sh")))
    prompts = os.path.join(ROOT, "research", "factory", "agents")
    have = sorted(f[:-3] for f in os.listdir(prompts)
                  if f.endswith(".md")) if os.path.isdir(prompts) else []
    ready &= line("промпты ролей", bool(have),
                  ", ".join(have) if have else "каталог пуст")

    print()
    if ready:
        print("Всё на месте: боевой прогон роли возможен.")
        print("  tools/agents_run.sh brief")
    else:
        print("Боевой прогон невозможен — недостающее названо выше.")
        print("Сухой прогон работает всегда и модель не зовёт:")
        print("  tools/agents_run.sh brief --dry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
