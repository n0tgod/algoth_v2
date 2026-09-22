#!/usr/bin/env python3
"""Машина негативных контролей механики 374e2591: подделка — сюита падает.

Каждая подделка из `build.json` применяется к КОПИИ файла, прогоняется
`test_floor_sister.py`, файл восстанавливается и сверяется по sha256.
Требуется не просто падение, а падение ИМЕННО названной проверки:
контроль, роняющий что-то постороннее, ничего не доказывает о том
правиле, ради которого написан.

    .venv/bin/python research/mech_374e2591/controls_check.py \\
        research/factory/out/build.json

Сюиту прогоняет НЕ своя копия запускалки, а сама приёмка
(`runlog._run_tests`): приёмка смотрит ПОСЛЕДНИЕ 4000 символов вывода, и
своя копия, читающая весь вывод, была бы ПОДДАТЛИВЕЕ проверяемой машины.
Байткод она же кладёт в свой каталог на каждый прогон: подделки пишутся
в один файл подряд, и `.pyc` предыдущей врёт в обе стороны.
"""

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SUITE = "research/mech_374e2591/test_floor_sister.py"

sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import runlog as RL                                          # noqa: E402


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_suite():
    """(прошло, вывод) — ровно так, как это делает приёмка."""
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
    bad, t_all = 0, time.time()
    for i, c in enumerate(controls, 1):
        p = os.path.join(ROOT, c["file"])
        before = sha(p)
        with open(p, encoding="utf-8") as f:
            src = f.read()
        n = src.count(c["old"])
        if n != 1:
            print(f"{i:2d}. ПЛОХО: строка встречается {n} раз, нужна одна "
                  f"— {c['old'][:60]!r}")
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
            print(f"{i:2d}. УПАЛО НЕ ТО: обещано {want!r}, а упало другое "
                  f"({time.time() - t0:.1f} с)")
            print("    " + " | ".join(ln for ln in txt.splitlines()
                                      if ln.startswith("ПРОВАЛ"))[:300])
            bad += 1
        else:
            print(f"{i:2d}. кусается ({time.time() - t0:.1f} с): {want}")
    print(f"контролей {len(controls)}, не кусаются {bad}, "
          f"{time.time() - t_all:.0f} с")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
