#!/usr/bin/env python3
"""Отставить запись книги, набранной СВЕРХ объявленной ширины.

Зачем нужен. Книга кандидата есть ИСПЫТАНИЕ объявленного правила, и
её живая запись имеет смысл ровно постольку, поскольку описывает то
правило, которое объявлено. Позиции, открытые при дефекте сверх
объявленных мест, описывают книгу другой ширины — то есть другого
кандидата под тем же именем. Оставить их значило бы измерять не то,
что заявлено, и никакая пометка этого не чинит: кривая складывается
из сделок, а не из пометок.

Что делает. Считает открытые позиции книги ТЕМ ЖЕ кодом, которым их
считает сканер (`collect.sit_open_levels`), сравнивает с объявленными
местами из манифеста и, если мест превышено, отставляет запись в
архив `<каталог>.overfilled-<метка>` — той же функцией `archive_book`,
которой книгу отставляет смена правил. Второй реализации «отставить
книгу» в проекте нет и не заводится.

Чего НЕ делает. Не удаляет ничего (архив остаётся записью), не
трогает книги, у которых превышения нет, и не решает, какая книга
кандидат: каталог называет вызывающий. Идемпотентен — повторный
прогон на вычищенной книге говорит «превышения нет» и уходит.
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
sys.path.insert(0, os.path.join(ROOT, "research", "b1_book"))
sys.path.insert(0, os.path.join(ROOT, "research"))


def held_by_arm(mdir):
    """Занятые ИМЕНА по рукам — счётом сканера, а не своим."""
    import collect as CO
    import train as T
    pk = T._read_jsonl(os.path.join(mdir, "picks.jsonl"))
    rv = T._read_jsonl(os.path.join(mdir, "review.jsonl"))
    en = T._read_jsonl(os.path.join(mdir, "entries_live.jsonl"))
    out = {}
    for p in CO.sit_open_levels(pk, rv, en):
        out.setdefault(p["arm"], set()).add(p["sym"])
    return out


def main(argv):
    if not argv:
        print("нужен каталог книги")
        return 2
    import json
    import train as T
    mdir = argv[0]
    if not os.path.isabs(mdir):
        mdir = os.path.join(ROOT, "research", "s8_loop", "out", mdir)
    if not os.path.isdir(mdir):
        print(f"каталога нет: {mdir}")
        return 2
    try:
        with open(os.path.join(mdir, "manifest.json"),
                  encoding="utf-8") as f:
            man = json.load(f) or {}
    except (OSError, ValueError) as e:
        print(f"манифест не читается: {e} — не трогаю")
        return 2
    slots = int(man.get("slots") or 0)
    if not slots:
        print("в манифесте нет числа мест — не трогаю")
        return 2
    held = held_by_arm(mdir)
    over = {a: len(s) for a, s in held.items() if len(s) > slots}
    for a, s in sorted(held.items()):
        print(f"  {a}: занято имён {len(s)} при {slots} местах")
    if not over:
        print("превышения нет — книга не трогается")
        return 0
    dst = f"{mdir}.overfilled-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    print(f"превышено: {over} — отставляю запись в "
          f"{os.path.basename(dst)}")
    T.archive_book(mdir, dst, print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
