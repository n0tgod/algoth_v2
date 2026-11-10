#!/usr/bin/env python3
"""Сколько решений книг ТВХ помечено «нет ячейки равного риска» (10.11),
когда был последний тик и его хвост лога — только чтение."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model_books as MB                                      # noqa: E402

st = json.load(open(MB.ENTRY_STATE, encoding="utf-8"))
for bid in ("m01", "m02", "m03", "m05", "m06"):
    m = st.get(bid) or {}
    nc = [k for k, d in m.items() if d.get("no_cell")]
    print(f"{bid}: решений {len(m)}, входов {sum(1 for d in m.values() if d.get('k', -1) >= 0)}, без ячейки {len(nc)}")
try:
    print("тик:", open(MB.TICK, encoding="utf-8").read())
except OSError as e:
    print("тик:", e)
lg = os.path.join(HERE, "out", "model_books.log")
print("\n".join(l for l in open(lg, encoding="utf-8").read().splitlines()[-400:] if "ячейк" in l or "к реплею" in l or "no_cell" in l)[-1500:])
print("сейчас", time.strftime("%H:%M", time.gmtime()))
