#!/usr/bin/env python3
"""
Опубликовать КОД механики, отчёт которой уже уехал в git.

Разовая дорога для механик, построенных ДО правила «каталог назначает
машина». `tools/publish.sh` публикует `research/*/out`, то есть отчёты;
код строителя оставался на сервере, и в ветке лежал отчёт потолка без
модуля, который его посчитал, — отчёт без своего кода невоспроизводим.

Публикуется РОВНО код названного каталога (`*.py`, `*.md` вне `out/`),
и только если механика с таким ключом стоит в очереди: каталог, ключа
не имеющий, здесь не публикуется вовсе.

    .venv/bin/python tools/publish_mech_code.py --id 5d30427d \\
        --dir research/probe_fshift --dry
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTORY = os.path.join(ROOT, "research", "factory")
KEEP = (".py", ".md", ".json", ".txt")


def code_files(rel_dir):
    """Код каталога: без `out/` (его публикует общая публикация)."""
    got = []
    base = os.path.join(ROOT, rel_dir)
    for dirpath, dirnames, names in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if d not in ("out", "__pycache__", ".git")]
        for n in sorted(names):
            if not n.endswith(KEEP):
                continue
            p = os.path.join(dirpath, n)
            got.append(os.path.relpath(p, ROOT))
    return sorted(got)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="ключ механики в очереди")
    ap.add_argument("--dir", required=True, help="каталог с кодом")
    ap.add_argument("--out", default=os.path.join(FACTORY, "out"))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    rel = a.dir.strip().rstrip("/")
    if not rel.startswith("research/") or ".." in rel:
        print("каталог вне research/, не публикую: %s" % rel)
        return 1
    if not os.path.isdir(os.path.join(ROOT, rel)):
        print("каталога нет: %s" % rel)
        return 1

    sys.path.insert(0, FACTORY)
    import mech_queue as MQ
    rows, _ = MQ.state(a.out)
    rec = {r["id"]: r for r in rows}.get(a.id)
    if not rec:
        print("механики %s в очереди нет — публиковать нечего" % a.id)
        return 1

    files = code_files(rel)
    if not files:
        print("кода в каталоге нет: %s" % rel)
        return 1
    print("механика %s — %s" % (a.id, rec["title"][:60]))
    print("публикую код:")
    for f in files:
        print("  " + f)
    if a.dry:
        return 0
    subprocess.run(["git", "add", "--"] + files, cwd=ROOT, check=False)
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                    "агенты: код механики %s" % a.id],
                   cwd=ROOT, check=False, timeout=600)
    # След в очереди: каталог механики, построенной до правила, иначе
    # связь «отчёт в git ↔ код в git» существует только в голове.
    MQ.mark(a.out, "code", a.id, "код опубликован: %s" % rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
