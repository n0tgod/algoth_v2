#!/usr/bin/env python3
"""Машина негативных контролей этой механики: подделка → сюита падает.

Каждая подделка из `research/factory/out/build.json` применяется к
КОПИИ файла, прогоняется `test_fshift.py`, файл восстанавливается и
сверяется по sha256. Требуется не просто падение, а падение ИМЕННО
названной проверки: контроль, роняющий что-то другое, ничего не
доказывает о том правиле, ради которого написан.

Байткод НЕ кешируется, и это не гигиена. Питон считает `.pyc` свежим по
паре (mtime источника в целых секундах, размер), а подделки пишутся в
один файл подряд и сплошь и рядом дают файл ТОГО ЖЕ размера в ту же
секунду — тогда прогон исполняет байткод ПРЕДЫДУЩЕЙ подделки, и
результат врёт в обе стороны. Дефект найден на машине контролей
фабрики; повторять его здесь незачем.

Восстановление — КОПИЕЙ исходного текста, а не `git checkout`: тот
сносит все незакоммиченные правки файла, и это уже стоило проекту
потерянного шага.

    cd ~/algoth_v2 && .venv/bin/python \\
        research/probe_fshift/controls_check.py
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SUITE = "research/probe_fshift/test_fshift.py"
REPORT = "research/factory/out/build.json"


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run():
    """Код возврата и ИМЕНА провалившихся проверок, а не только код."""
    shutil.rmtree(os.path.join(ROOT, "research", "probe_fshift",
                               "__pycache__"), ignore_errors=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-B", os.path.join(ROOT, SUITE)],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    fails = [ln.split("ПРОВАЛ", 1)[1].split(" — ")[0].strip()
             for ln in r.stdout.splitlines() if "ПРОВАЛ " in ln]
    return r.returncode, fails


def main(report=None):
    path = os.path.join(ROOT, report or REPORT)
    with open(path, encoding="utf-8") as f:
        controls = json.load(f)["controls"]
    rc, fails = run()
    print(f"=== база: rc={rc}, провалов={len(fails)} "
          f"{'зелёная' if rc == 0 and not fails else 'КРАСНАЯ'}")
    bad = []
    for i, c in enumerate(controls, 1):
        p = os.path.join(ROOT, c["file"])
        before = sha(p)
        with open(p, encoding="utf-8") as f:
            orig = f.read()
        # Подделка обязана быть ОДНОЗНАЧНОЙ: строка, встречающаяся
        # дважды, подменила бы заодно и то место, о котором контроль
        # ничего не утверждает.
        if orig.count(c["old"]) != 1:
            print(f"  #{i} НЕПРИМЕНИМ: строка встречается "
                  f"{orig.count(c['old'])} раз")
            bad.append(i)
            continue
        with open(p, "w", encoding="utf-8") as f:
            f.write(orig.replace(c["old"], c["new"]))
        try:
            code, got = run()
        finally:
            with open(p, "w", encoding="utf-8") as f:
                f.write(orig)
        assert sha(p) == before, f"#{i}: файл не восстановлен"
        hit = [x for x in got if c["expect"] in x]
        ok = code != 0 and hit
        print(f"  #{i} {'кусается' if ok else 'ХОЛОСТОЙ'}: rc={code}, "
              f"провалов={len(got)}, названная={'да' if hit else 'НЕТ'}"
              f"  [{c['expect'][:48]}]")
        if not ok:
            print(f"      провалились: {got}")
            bad.append(i)
    print(f"\nитог: {len(controls) - len(bad)} из {len(controls)} кусаются"
          + ("" if not bad else f"; ХОЛОСТЫЕ: {bad}"))
    return 1 if bad or rc or fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
