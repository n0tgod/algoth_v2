#!/usr/bin/env python3
"""Машина негативных контролей механики a82dcf58: подделка — сюита падает.

Каждая подделка из `build.json` применяется к КОПИИ файла, прогоняется
`test_twin.py`, файл восстанавливается и сверяется по sha256. Требуется
не просто падение, а падение ИМЕННО названной проверки: контроль,
роняющий что-то постороннее, ничего не доказывает о том правиле, ради
которого написан.

    .venv/bin/python research/mech_a82dcf58/controls_check.py \\
        research/factory/out/build.json

Байткод складывается в СВОЙ каталог на каждый прогон, и это не гигиена, а
исправление дефекта: питон считает `.pyc` свежим по паре (mtime в целых
секундах, размер источника), а подделки пишутся в один файл подряд —
замена одной строки часто даёт файл ТОГО ЖЕ размера в ту же секунду, и
прогон исполняет байткод ПРЕДЫДУЩЕЙ подделки. Врёт это в обе стороны.

Сюиту прогоняет НЕ своя копия запускалки, а сама приёмка
(`runlog._run_tests`), и это не изящество, а починка по живому отказу.
Своя копия отличалась одной мелочью: приёмка смотрит ПОСЛЕДНИЕ 4000
символов вывода, а копия — весь. Сюита печатает 11 тысяч, и строка
«ПРОВАЛ имя», стоящая в середине, в это окно не попадала: копия говорила
«кусается», приёмка — «упало не то». Копия была ПОДДАТЛИВЕЕ проверяемой
машины, то есть врала в ту сторону, ради которой её и заводят. Второй
копии правила теперь нет: здесь только цикл по подделкам и
восстановление файла.
"""

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SUITE = "research/mech_a82dcf58/test_twin.py"

sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import runlog as RL                                          # noqa: E402


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_suite():
    """(прошло, вывод) — ровно так, как это делает приёмка.

    Включая усечение вывода: `expect`, не попадающий в окно приёмки, есть
    контроль, который здесь пройдёт, а там нет.
    """
    return RL._run_tests(ROOT, SUITE)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "research", "factory", "out", "build.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    controls = d.get("controls") or []
    ok, out = run_suite()
    print(f"сюита без подделок: {'прошла' if ok else 'УПАЛА'}")
    if not ok:
        print(out[-2000:])
        return 1
    bad = 0
    for i, c in enumerate(controls, 1):
        p = os.path.join(ROOT, c["file"])
        before = sha(p)
        with open(p, encoding="utf-8") as f:
            src = f.read()
        n = src.count(c["old"])
        if n != 1:
            print(f"{i:2d}. ПЛОХО: строка встречается {n} раз, нужна одна")
            bad += 1
            continue
        t0 = time.time()
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src.replace(c["old"], c["new"], 1))
            fell, txt = run_suite()
        finally:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src)
        assert sha(p) == before, "файл не восстановился — это хуже подделки"
        want = c.get("expect") or ""
        if fell:
            print(f"{i:2d}. НЕ КУСАЕТСЯ: подделка прошла мимо сюиты — "
                  f"{c['old'][:56]}")
            bad += 1
        elif want and want not in txt:
            print(f"{i:2d}. УПАЛО НЕ ТО: обещано {want!r}")
            bad += 1
        else:
            print(f"{i:2d}. кусается ({round(time.time() - t0, 1)} с): "
                  f"{want}")
    print(f"\nконтролей {len(controls)}, негодных {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
