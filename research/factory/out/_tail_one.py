#!/usr/bin/env python3
"""Показать ХВОСТ вывода сюиты под одной подделкой — ровно то, что видит
приёмка (`runlog._run_tests` отдаёт последние 4000 символов).

    .venv/bin/python research/factory/out/_tail_one.py 2
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))

import runlog as RL                                          # noqa: E402


def main():
    i = int(sys.argv[1])
    with open(os.path.join(ROOT, "research", "factory", "out", "build.json"),
              encoding="utf-8") as f:
        c = json.load(f)["controls"][i - 1]
    p = os.path.join(ROOT, c["file"])
    with open(p, encoding="utf-8") as f:
        src = f.read()
    assert src.count(c["old"]) == 1, "подделка неоднозначна"
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(src.replace(c["old"], c["new"], 1))
        ok, out = RL._run_tests(ROOT, "research/mech_d71203f0/"
                                      "test_unprovoked.py")
    finally:
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
    print(f"=== контроль {i}: сюита {'ПРОШЛА' if ok else 'упала'} ===")
    print(f"=== обещано: {c['expect']!r} — "
          f"{'есть' if c['expect'] in out else 'В ХВОСТЕ НЕТ'} ===")
    print(f"=== длина хвоста {len(out)} ===")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
