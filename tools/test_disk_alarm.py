#!/usr/bin/env python3
"""Проверка тревоги по диску: над порогом — просьба один раз, ниже — тишина."""
import json
import os
import shutil
import sys
import tempfile
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import disk_alarm as D                                        # noqa: E402

FAILED = []
ST = namedtuple("st", "f_blocks f_frsize f_bavail")


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name
          + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def main():
    d = tempfile.mkdtemp(prefix="alarm-")
    try:
        fill = {"/vol": 94.0, "/": 60.0}

        def fake(path):
            pct = fill[path]
            return ST(1000, 2**20, int(1000 * (1 - pct / 100)))
        said = []
        over = D.check([("том", "/vol"), ("корень", "/")], pct=90, asks_out=d,
                       statvfs=fake, log=said.append, now=1790000000)
        rows = [json.loads(x) for x in open(os.path.join(d, "asks.jsonl"))]
        check("над порогом — тревога и просьба", [o[0] for o in over] == ["том"]
              and len(rows) == 1 and "94 %" in rows[0]["why"], rows)
        check("ниже порога — молчит", not any("корень" in x for x in said))
        over = D.check([("том", "/vol"), ("корень", "/")], pct=90, asks_out=d,
                       statvfs=fake, log=said.append, now=1790000000)
        rows = [json.loads(x) for x in open(os.path.join(d, "asks.jsonl"))]
        check("повтор — просьба одна", len(rows) == 1 and any("уже стоит" in x for x in said))
        fill["/vol"] = 50.0
        over = D.check([("том", "/vol")], pct=90, asks_out=d, statvfs=fake,
                       log=said.append, now=1790000000)
        check("спало — тревоги нет", over == [])
        # дорога до вызова: main пишет в НАЗВАННЫЙ каталог, а не в боевой
        d2 = tempfile.mkdtemp(prefix="alarm2-")
        rc = D.main(["--pct", "0"], asks_out=d2)
        rc_ok = D.main(["--pct", "100.5"], asks_out=d2)
        check("код выхода: над порогом 1, ниже 0", rc == 1 and rc_ok == 0
              and os.path.exists(os.path.join(d2, "asks.jsonl")))
        shutil.rmtree(d2, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
