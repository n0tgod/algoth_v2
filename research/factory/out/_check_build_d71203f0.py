#!/usr/bin/env python3
"""Приёмка постройки ТОЙ ЖЕ машиной, что судит фабрику.

Своя копия проверки была бы поддатливее проверяемой: `runlog.check_build`
смотрит ПОСЛЕДНИЕ 4000 символов вывода сюиты, а копия, читающая весь
вывод, объявила бы кусающимся контроль, чьё падение до хвоста не дошло.
Поэтому здесь зовётся сама приёмка, а не её пересказ.

    .venv/bin/python research/factory/out/_check_build_d71203f0.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))

import runlog as RL                                          # noqa: E402

OUT = os.path.join(ROOT, "research", "factory", "out")


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    p = os.path.join(OUT, "build.json")
    with open(p, encoding="utf-8") as f:
        text = f.read()
    t0 = time.time()
    ok, bad = RL.check_build(text, ROOT, out_dir=OUT)
    print(f"приёмка: {'ГОДНА' if ok else 'НЕГОДНА'} за "
          f"{round(time.time() - t0, 1)} с")
    for b in bad:
        print(f"  - {b}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
