#!/usr/bin/env python3
"""Проверить СВОИ негативные контроли той же машиной, что приёмка.

Роль судит себя ДО отчёта: `runlog.check_build` применяет каждую
подделку к копии файла, гоняет тесты и требует падения. Журналов машина
отсюда не пишет (`check_build`, а не `check_role`): суд и запись —
разные дела.

    .venv/bin/python research/mech_dc3b6317/controls_check.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import runlog as RL                                           # noqa: E402

OUT = os.path.join(ROOT, "research", "factory", "out")


def main():
    with open(os.path.join(OUT, "build.json"), encoding="utf-8") as f:
        text = f.read()
    ok, bad = RL.check_build(text, ROOT, out_dir=OUT)
    d = json.loads(text)
    print(f"контролей {len(d.get('controls') or [])}, "
          + ("все кусаются" if ok else "БЕДЫ:"))
    for b in bad:
        print("  " + b)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
