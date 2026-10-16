"""Зонд: свод книг НА ДИСКЕ сервера (не в git) — версии, охрана, время."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "research", "dca_paper", "out")
for f in ("DCA-short.json", "DCA-pair.json", "DCA-paper.json"):
    p = os.path.join(OUT, f)
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError) as e:
        print(f, "не читается:", e)
        continue
    r = d.get("rules") or {}
    g = {k: (v or {}).get("guard") for k, v in (d.get("guards") or {}).items()}
    print(f, d.get("computed_at"), "FAMILY_RULES", r.get("FAMILY_RULES"), "FAMILY_SINCE", r.get("FAMILY_SINCE"), "охрана", g)
    for k, b in sorted((d.get("books") or {}).items()):
        if ":fixed" in k or not k.endswith((":1000", ":10000")):
            continue
        a = b.get("all") or {}
        fw = b.get("forward") or {}
        ex = a.get("exits") or {}
        print(f"  {k}: итог {a.get('final')}, n {a.get('n')}, рынок {(ex.get('рынок') or {}).get('n') if isinstance(ex.get('рынок'), dict) else ex.get('рынок')}, вперёд n {fw.get('n')}")
