#!/usr/bin/env python3
"""
Опубликовать то, что построила роль строителя.

Дыра, найденная первой же постройкой: `tools/publish.sh` публикует
`research/*/out`, `docs` и `jobs` — то есть ОТЧЁТЫ. А строитель пишет
КОД, и он остался на сервере: прогон был, контракт выполнен, а в ветке
пусто. Тот же класс, что «прогон, чей отчёт остался на сервере,
неотличим от прогона, которого не было», только предметом стал не
отчёт.

Публикуется РОВНО ТО, ЧТО РОЛЬ ОБЪЯВИЛА: пути из её отчёта, а не
всё, что изменилось на диске. Расширять общий белый список публикации
нельзя — команда, сметающая в коммит любую правку на сервере, однажды
запишет туда то, чего никто не писал.

    .venv/bin/python research/factory/publish_build.py
    .venv/bin/python research/factory/publish_build.py --dry
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORT = os.path.join(HERE, "out", "build.json")

# Публиковать можно только СВОЙ каталог: путь наружу означает не
# опечатку, а попытку, и белый список публикации — не то место, где
# уместна доверчивость.
ALLOWED_PREFIX = "research/factory/"


def paths_of(report, log=print):
    """Пути, объявленные отчётом постройки. Чужое отсеивается."""
    try:
        with open(report, encoding="utf-8") as f:
            d = json.load(f)
    except OSError:
        log(f"отчёта постройки нет: {report}")
        return []
    except ValueError as e:
        log(f"отчёт постройки не читается: {e}")
        return []
    if not d.get("built"):
        log("постройка не состоялась — публиковать нечего")
        return []
    out = []
    for key in ("module", "tests"):
        rel = (d.get(key) or "").strip()
        if not rel:
            continue
        if not rel.startswith(ALLOWED_PREFIX) or ".." in rel:
            log(f"путь вне своего каталога, не публикую: {rel}")
            continue
        if not os.path.exists(os.path.join(ROOT, rel)):
            log(f"файла нет, не публикую: {rel}")
            continue
        out.append(rel)
    # Правки существующих файлов роль называет отдельно: они не её
    # собственность, и подхватывать их молча нельзя.
    for rel in d.get("touched") or []:
        if (isinstance(rel, str) and rel.startswith(ALLOWED_PREFIX)
                and ".." not in rel
                and os.path.exists(os.path.join(ROOT, rel))):
            out.append(rel)
    return sorted(set(out))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=REPORT)
    ap.add_argument("--dry", action="store_true")
    # Правка существующего файла, названная заданием, а не отчётом:
    # нужна для восстановления, когда роль писалась до появления поля
    # `touched`. Тот же запрет на путь наружу.
    ap.add_argument("--also", action="append", default=[])
    a = ap.parse_args(argv)

    rels = paths_of(a.report)
    for rel in a.also:
        if (rel.startswith(ALLOWED_PREFIX) and ".." not in rel
                and os.path.exists(os.path.join(ROOT, rel))):
            rels.append(rel)
        else:
            print(f"не публикую: {rel}")
    rels = sorted(set(rels))
    if not rels:
        print("публиковать нечего")
        return 0
    print("публикую:")
    for r in rels:
        print("  " + r)
    if a.dry:
        return 0
    subprocess.run(["git", "add", "--"] + rels, cwd=ROOT, check=False)
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                    "агенты: код, построенный ролью"],
                   cwd=ROOT, check=False, timeout=600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
