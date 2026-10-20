#!/usr/bin/env python3
"""Почасовой ряд открытых у ячейки (20.10): из чего сложена «просадка
открытых». Владелец: у «AI judge · both» $100 она 0.000 %. Печатает ряд
`open_hours` кассы ([час, сумма отметок открытых $, доля счёта]) из
артефакта семейства и открытые позиции ячейки с их последними отметками.
Аргументы: ячейка двумя словами — ключ книги и депозит (белый список
очереди двоеточие не пропускает). Только читает."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                            # noqa: E402


def main(argv):
    rk, dep = argv[0], argv[1]
    cell = f"{rk}:{dep}"
    path = R.artifact_of(rk)
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    print(f"артефакт {os.path.basename(path)}, посчитан {s.get('computed_at')}")
    c = (s.get("cells") or {}).get(cell)
    b = (s.get("books") or {}).get(cell) or {}
    if c is None:
        print(f"ячейки {cell} в cells нет; ключи: {sorted(s.get('cells') or {})[:12]}")
    else:
        print({k: c.get(k) for k in ("open_dd", "open_dd_share", "open_dd_at")})
        hrs = c.get("open_hours")
        print(f"open_hours: {None if hrs is None else len(hrs)} строк")
        for row in (hrs or [])[-48:]:
            print("  ", time.strftime("%m-%d %H:%M", time.gmtime(int(row[0]))), row[1:])
    for p in ((b.get("open") or {}).get("positions") or []):
        print("открыта", p.get("sym"), time.strftime("%m-%d %H:%M", time.gmtime(float(p["at"]))),
              "mark_usd", p.get("mark_usd"), "marks", (p.get("marks") or [])[-3:])
    print("all", {k: (b.get("all") or {}).get(k) for k in ("n", "usd", "open_dd", "open_dd_share")})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
