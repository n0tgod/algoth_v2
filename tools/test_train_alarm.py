#!/usr/bin/env python3
"""Проверка `tools/train_alarm.py`: тревога по возрасту весов, просьба один
раз на эпизод, тишина ниже порога, `--print` всегда, контроль порога."""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_alarm as D  # noqa: E402
import stall as ST  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name + ("" if cond else f": {detail}"))
    if not cond:
        FAILED.append(name)


def write_state(mdir, age_h, now, why=None):
    os.makedirs(mdir, exist_ok=True)
    json.dump({"trained_at": datetime.fromtimestamp(now - age_h * 3600, timezone.utc)
               .isoformat(timespec="seconds"), "version": 7},
              open(os.path.join(mdir, "manifest.json"), "w"))
    if why:
        json.dump({"at": "2026-10-04T13:05:10+00:00", "reason": "часовой цикл без обучения",
                   "train_why": why}, open(os.path.join(mdir, "last_run.json"), "w"))


def main():
    now = 1791240000.0
    d = tempfile.mkdtemp(prefix="talarm-")
    try:
        mdir, asks = os.path.join(d, "model"), os.path.join(d, "asks")
        why = "память: доступно 2762 МБ при пороге 3072 — рядом другие прогоны, обучение отложено на час"
        write_state(mdir, 50.0, now, why)
        said = []
        st = D.check(mdir, asks, now=now, log=said.append)
        rows = [json.loads(x) for x in open(os.path.join(asks, "asks.jsonl"))]
        check("50 ч — тревога напечатана с возрастом и причиной цикла",
              st["stalled"] and len(said) == 1 and said[0].startswith("ТРЕВОГА")
              and "50.0 ч" in said[0] and "2762" in said[0], str(said))
        check("просьба владельцу записана одна, с возрастом и временем весов",
              len(rows) == 1 and "50.0 ч" in rows[0]["why"]
              and "Обучение S8 стоит: веса от" in rows[0]["what"]
              and rows[0]["from"] == "сторож обучения", str(rows))
        D.check(mdir, asks, now=now + 3600, log=said.append)
        rows = [json.loads(x) for x in open(os.path.join(asks, "asks.jsonl"))]
        check("час спустя — строка снова, просьба всё та же одна",
              len(said) == 2 and "уже стоит" in said[1] and len(rows) == 1, str(said))
        # свежие веса: сторожу — тишина, `status` — строка состояния
        write_state(mdir, 2.0, now, "обучение пропущено по каденции: весам 2.0 ч при каденции 24")
        said = []
        st = D.check(mdir, asks, now=now, log=said.append)
        check("2 ч — тишина для сторожа", not st["stalled"] and said == [], str(said))
        D.check(mdir, asks, now=now, log=said.append, always=True)
        check("--print: строка состояния и без тревоги, с причиной последнего цикла",
              len(said) == 1 and said[0].startswith("обучение S8: веса от")
              and "2.0 ч назад" in said[0] and "пропущено по каденции" in said[0], str(said))
        # не измерено — строка с причиной, не тишина и не тревога
        shutil.rmtree(mdir)
        said = []
        st = D.check(mdir, asks, now=now, log=said.append)
        check("манифеста нет — «не измерено» с причиной, без тревоги",
              not st["stalled"] and len(said) == 1 and "не измерено" in said[0], str(said))
        # код выхода дороги main: стоит — 1, нет — 0
        write_state(mdir, 1.0, time.time(), why)   # свежие веса к настоящему «сейчас»
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc_fresh = D.main(["--print"], mdir=mdir, asks_out=asks)
        check("--print печатает всегда, код 0 на свежих",
              rc_fresh == 0 and "обучение S8" in buf.getvalue(), buf.getvalue())
        write_state(mdir, 100.0, time.time(), why)
        with redirect_stdout(io.StringIO()):
            rc = D.main([], mdir=mdir, asks_out=asks)
        write_state(mdir, 1.0, time.time(), why)
        with redirect_stdout(io.StringIO()):
            rc_ok = D.main([], mdir=mdir, asks_out=asks)
        check("код выхода: стоит 1, свежие 0", rc == 1 and rc_ok == 0, f"{rc} {rc_ok}")
        # Отрицательный контроль: порог 1000 ч обязан погасить тревогу
        # при 50 ч — сперва доказываем, что подделка легла.
        write_state(mdir, 50.0, now, why)
        was = ST.STALL_H
        ST.STALL_H = 1000
        assert ST.STALL_H == 1000
        try:
            said = []
            st = D.check(mdir, asks, now=now, log=said.append)
            check("подставной порог кусается (контроль): 50 ч без тревоги",
                  not st["stalled"] and said == [], str(said))
        finally:
            ST.STALL_H = was
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
