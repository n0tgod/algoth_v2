#!/usr/bin/env python3
"""Проверка правила «обучение стоит»: порог, мера, причина, каденция."""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stall as S  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name + ("" if cond else f": {detail}"))
    if not cond:
        FAILED.append(name)


def man(now, age_h):
    return {"trained_at": datetime.fromtimestamp(now - age_h * 3600, timezone.utc)
            .isoformat(timespec="seconds")}


def main():
    now = time.time()
    lr = {"at": "2026-10-04T13:05:10+00:00", "reason": "часовой цикл без обучения",
          "train_why": "память: доступно 2762 МБ при пороге 3072 — рядом другие прогоны, обучение отложено на час"}
    st = S.stall_of(man(now, 25.0), lr, now)
    check("25 ч при каденции 24 — не тревога (один пропуск законен)",
          st["measured"] and not st["stalled"] and abs(st["age_h"] - 25.0) < 0.1, str(st))
    st = S.stall_of(man(now, 109.1), lr, now)
    check("109 ч (случай 30.09 → 04.10) — тревога с возрастом и причиной",
          st["stalled"] and st["age_h"] == 109.1 and "2762" in st["last_why"], str(st))
    ln = S.line(st)
    check("строка начинается с ТРЕВОГА и несёт возраст, порог и причину цикла",
          ln.startswith("ТРЕВОГА обучение S8") and "109.1 ч" in ln and "36 ч" in ln
          and "13:05 UTC: память: доступно 2762" in ln, ln)
    st = S.stall_of(man(now, 36.0), None, now)
    check("ровно порог — тревога (не меньше)", st["stalled"])
    st = S.stall_of(man(now, 35.9), None, now)
    check("чуть ниже порога — нет", not st["stalled"])
    check("порог читается из модуля в момент вызова",
          S.stall_of(man(now, 40), None, now, threshold_h=48)["stalled"] is False)
    st = S.stall_of(None, lr, now)
    check("манифеста нет — не измерено, не тревога, причина названа",
          not st["measured"] and not st["stalled"] and "манифеста" in st["note"], str(st))
    check("строка «не измерено» называет причину",
          S.line(st).startswith("обучение S8: не измерено — манифеста"), S.line(st))
    st = S.stall_of({"trained_at": "вчера"}, None, now)
    check("время не разобрано — не измерено", not st["measured"] and "не разобрано" in st["note"])
    ln = S.line(S.stall_of(man(now, 2.0), lr, now))
    check("свежие веса — строка без ТРЕВОГИ, но с причиной последнего цикла",
          not ln.startswith("ТРЕВОГА") and "2.0 ч назад" in ln and "последний цикл" in ln, ln)
    # чтение с диска — той же дорогой, что у сторожа и страницы
    d = tempfile.mkdtemp()
    json.dump(man(now, 50), open(os.path.join(d, "manifest.json"), "w"))
    m, r = S.read_state(d)
    check("с диска: манифест прочитан, исхода нет — None", m is not None and r is None)
    json.dump(lr, open(os.path.join(d, "last_run.json"), "w"))
    m, r = S.read_state(d)
    check("с диска: исход прочитан", r == lr)
    # каденция — та же, что у цикла: дубль числа держится проверкой
    import train as T
    check("каденция совпадает с train.TRAIN_EVERY_H", S.CADENCE_H == T.TRAIN_EVERY_H,
          f"{S.CADENCE_H} vs {T.TRAIN_EVERY_H}")
    check("порог тревоги — полторы каденции", S.STALL_H == 1.5 * S.CADENCE_H)
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
