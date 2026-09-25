#!/usr/bin/env python3
"""Проверка установщика пакетов очереди: забор имён, отказ pip, версия."""
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import venv_add as V                                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name
          + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def fake_pip(d, rc=0):
    p = os.path.join(d, "pip")
    with open(p, "w") as f:
        f.write(f'#!/bin/sh\necho "$@" >> "{d}/pip.log"\nexit {rc}\n')
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


def main():
    d = tempfile.mkdtemp(prefix="venv-add-")
    said = []
    pip = fake_pip(d)
    # имена: чужие формы не доходят до pip вовсе
    for bad in ("../x", "http://a/b.whl", "pkg;rm", "-r", "a b", "/tmp/x"):
        rc = V.main([bad], pip=pip, py=sys.executable, log=said.append)
        check(f"отказ до pip: {bad!r}", rc == 2
              and not os.path.exists(os.path.join(d, "pip.log")))
    # установленный пакет: pip вызван, версия напечатана
    said.clear()
    rc = V.main(["pip"], pip=pip, py=sys.executable, log=said.append)
    log = open(os.path.join(d, "pip.log")).read()
    check("pip вызван с именем", "install" in log and " pip" in log, log)
    check("версия напечатана", rc == 0 and any("версия" in x for x in said), said)
    # pip промолчал, а пакета нет — отказ прогона, не тишина
    said.clear()
    rc = V.main(["no-such-dist-xyz-123"], pip=pip, py=sys.executable,
                log=said.append)
    check("пакет без версии — отказ", rc == 1
          and any("НЕ установлен" in x for x in said), said)
    # отказ pip — код 1 и слова
    said.clear()
    rc = V.main(["pip"], pip=fake_pip(d, rc=3), py=sys.executable,
                log=said.append)
    check("отказ pip — код 1", rc == 1 and any("кодом 3" in x for x in said), said)
    check("без имён — код 2", V.main([], pip=pip, log=said.append) == 2)
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
