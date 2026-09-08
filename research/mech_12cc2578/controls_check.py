#!/usr/bin/env python3
"""
Своя машинка проверки негативных контролей — до сдачи отчёта.

Делает ровно то же, что приёмка (`factory/runlog.check_build`): каждая
подделка применяется к КОПИИ файла, сюита прогоняется заново и ОБЯЗАНА
упасть именно на названной проверке. Нужна затем, что контроль, который
не кусается, валит весь прогон приёмки целиком, а узнать это до сдачи
дешевле, чем после.

Байткод складывается в СВОЙ каталог на каждый прогон: питон считает
`.pyc` свежим по паре «mtime в целых секундах, размер», а подделки
пишутся в один файл подряд — замена строки часто даёт файл ТОГО ЖЕ
размера в ту же секунду, и прогон исполняет байткод предыдущей
подделки. Врёт это в обе стороны.

    .venv/bin/python research/mech_12cc2578/controls_check.py
    .venv/bin/python research/mech_12cc2578/controls_check.py --only 3
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORT = os.path.join(ROOT, "research", "factory", "out", "build.json")


def run_tests(tests):
    py = os.path.join(ROOT, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable
    cache = tempfile.mkdtemp(prefix="pyc-")
    env = dict(os.environ, PYTHONPYCACHEPREFIX=cache)
    try:
        r = subprocess.run([py, tests], cwd=ROOT, capture_output=True,
                           text=True, timeout=900, env=env)
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    return r.returncode == 0, (r.stdout + r.stderr)[-6000:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=REPORT)
    ap.add_argument("--only", type=int, default=None)
    a = ap.parse_args()
    with open(a.report, encoding="utf-8") as f:
        d = json.load(f)
    tests = d["tests"]
    ok, out = run_tests(tests)
    print("чистая сюита: " + ("зелена" if ok else "КРАСНА\n" + out))
    if not ok:
        return 1
    bad = []
    for i, c in enumerate(d.get("controls") or [], 1):
        if a.only and i != a.only:
            continue
        p = os.path.join(ROOT, c["file"])
        with open(p, encoding="utf-8") as f:
            src = f.read()
        n = src.count(c["old"])
        if n != 1:
            print(f"контроль {i}: строка встречается {n} раз, а нужна одна")
            bad.append(i)
            continue
        t0 = time.time()
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src.replace(c["old"], c["new"], 1))
            fell, out = run_tests(tests)
        finally:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src)
        want = (c.get("expect") or "").strip()
        if fell:
            print(f"контроль {i} НЕ КУСАЕТСЯ ({time.time() - t0:.0f} с)")
            bad.append(i)
        elif want and want not in out:
            print(f"контроль {i}: упало не то — нет {want!r}")
            print(out[-800:])
            bad.append(i)
        else:
            print(f"контроль {i}: кусается ({time.time() - t0:.0f} с) — "
                  f"{want}")
    print("плохих контролей: " + (", ".join(map(str, bad)) if bad else "нет"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
