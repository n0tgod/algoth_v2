#!/usr/bin/env python3
"""Проверка размораживателя публикации на ПОДСТАВНОМ репозитории.

Инструмент делает `git checkout` по записи книги, поэтому проверять его
надо там, где ошибка ничего не стоит: настоящий журнал — единственное
здесь невосстановимое. Проверяются обе стороны: пока хоть одно решение
живёт только в цельном файле, инструмент обязан ОТКАЗАТЬ; после
разрезки — вернуть файл к версии git, не потеряв ни одного решения.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))

import rules as R  # noqa: E402
import split_journal as S  # noqa: E402


def main():
    td = tempfile.mkdtemp()
    repo = os.path.join(td, "repo")
    dst = os.path.join(repo, "research", "dca_paper")
    os.makedirs(os.path.join(dst, "out"))
    os.makedirs(os.path.join(repo, "tools"))
    for f in ("rules.py", "split_journal.py"):
        shutil.copy2(os.path.join(ROOT, "research", "dca_paper", f),
                     os.path.join(dst, f))
    shutil.copy2(os.path.join(ROOT, "tools", "unstick_publish.py"),
                 os.path.join(repo, "tools", "unstick_publish.py"))
    run = lambda *a: subprocess.run(a, cwd=repo, capture_output=True,
                                    text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    p = os.path.join(dst, "out", "journal.jsonl")
    t0 = 1_788_000_000

    def row(at, sym):
        return {"dep": 1000, "ruler": "safe", "rules": R.RULES, "at": at,
                "sym": sym, "usd": 1.0, "written_at": at + 60}

    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(row(t0, "AAAUSDT")) + "\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")
    # дозапись, которой в git нет: ровно то, что осталось на сервере
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row(t0 + 86400, "BBBUSDT")) + "\n")

    tool = os.path.join(repo, "tools", "unstick_publish.py")
    r1 = subprocess.run([sys.executable, tool], capture_output=True,
                        text=True)
    assert r1.returncode == 1, r1.stdout + r1.stderr
    assert "ОТКАЗ" in r1.stdout, r1.stdout
    print("ok  размораживатель: без разрезки отказывает и называет причину")

    S.split(p, log=lambda *_: None)
    r2 = subprocess.run([sys.executable, tool], capture_output=True,
                        text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    rows, _bad = R.read_journal(p)
    whole = S.read_one(p)[0]
    assert len(rows) == 2, rows          # читатель видит оба решения
    assert len(whole) == 1, whole        # цельный файл вернулся к версии git
    print("ok  размораживатель: файл вернулся к версии git, "
          f"решений по-прежнему {len(rows)}")
    print("\nвсе 2 проверки прошли")


if __name__ == "__main__":
    main()
