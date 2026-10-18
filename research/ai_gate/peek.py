#!/usr/bin/env python3
"""Заглянуть в судью на сервере (только чтение): хвост лога прохода, свежесть
кандидатов книг Depth (последний час входа) и листа S8 — чтобы «судья молчит»
решалось фактом: нет кандидатов или проход не идёт.

    run research/ai_gate/peek.py
"""
import glob
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t)) if t else "—"


def main():
    log = os.path.join(HERE, "out", "gate.log")
    print(f"== gate.log: {'есть' if os.path.exists(log) else 'НЕТ'}")
    if os.path.exists(log):
        print("".join(open(log, encoding="utf-8", errors="replace").readlines()[-15:]).rstrip())
    import gate_run as G
    books, why = G.candidates(lambda *a: None)
    if why:
        print("книги не загружены:", why)
        return 1
    for b, _ in G.BOOKS:
        recs = books.get(b) or []
        last = max((float(r["at"]) for r in recs), default=0)
        after = sum(1 for r in recs if float(r["at"]) >= G.GATE_SINCE)
        print(f"{b}: записей {len(recs)}, последний вход {ts(last)} UTC, входов с дня рождения {after}")
    for p in sorted(glob.glob(os.path.join(ROOT, "research", "s8_loop", "out", "sheets*.jsonl")))[-3:]:
        print(f"лист {os.path.basename(p)}: изменён {ts(os.path.getmtime(p))} UTC")
    flag = os.path.join(ROOT, "research", "s8_loop", "out", "train_wait.flag")
    print("train_wait.flag:", ts(os.path.getmtime(flag)) if os.path.exists(flag) else "нет")
    print("сейчас:", ts(time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
