#!/usr/bin/env python3
"""Перепись журнала книг на сервере (только чтение): куски и их размер,
строки по семействам и версиям правил, у длинных книг — доля позиций с
доливом по повтору и маржа в билетах (спека 14 §18). Нужна потому, что
куски журнала больше 5 МБ в git не публикуются, а «правило работает»
обязано быть видно числом, а не утверждением.

    run research/dca_paper/journal_check.py
"""
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402

OUT = os.path.join(HERE, "out")


def main():
    files = sorted(glob.glob(os.path.join(OUT, "*journal*.jsonl")) + glob.glob(os.path.join(OUT, "short*.jsonl"))
                   + glob.glob(os.path.join(OUT, "pair*.jsonl")))
    big = [(os.path.basename(p), os.path.getsize(p)) for p in files]
    print(f"файлов журнала {len(big)}; > 5 МБ: " + ", ".join(f"{n} ({s / 1e6:.1f} МБ)" for n, s in big if s > 5e6) or "нет")
    print("последние куски: " + ", ".join(f"{n} ({s / 1e3:.0f} КБ)" for n, s in big[-6:]))
    rows = []
    for p in files:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    print(f"строк всего {len(rows)}")
    by = collections.Counter((R.family_of(r.get("ruler") or ""), r.get("rules"), r.get("book_rules")) for r in rows)
    for k, v in sorted(by.items(), key=lambda x: (str(x[0][0]), str(x[0][1]), str(x[0][2]))):
        print(f"  семейство {k[0]}: rules {k[1]}, book_rules {k[2]}: {v}")
    cur = [r for r in rows if R.is_current(r)]
    print(f"текущих строк {len(cur)}")
    for rk in ("safe", "optimal", "aggr"):
        xs = [r for r in cur if r.get("ruler") == rk and int(r.get("dep", 0)) == 10000 and not r.get("sizing")]
        adds = [r for r in xs if r.get("adds")]
        ct = collections.Counter(r.get("capital_t") for r in xs)
        wa = collections.Counter(str(r.get("written_at", 0))[:0] or __import__("time").strftime("%m-%d", __import__("time").gmtime(float(r.get("written_at") or 0))) for r in xs)
        print(f"{rk} $10k: позиций {len(xs)}, с доливом {len(adds)} ({(100 * len(adds) / len(xs)) if xs else 0:.0f} %), "
              f"capital_t {dict(ct)}, usd {sum(r.get('usd') or 0 for r in xs):.0f} (с доливом {sum(r.get('usd') or 0 for r in adds):.0f}); "
              f"дни записи {dict(sorted(wa.items()))}")
        if adds:
            r = max(adds, key=lambda r: float(r.get("at") or 0))
            print(f"   последняя с доливом: {r['sym']} вход {__import__('time').strftime('%m-%d %H:%M', __import__('time').gmtime(float(r['at'])))} "
                  f"заполнения {[(round(f[1], 5), f[2]) for f in r.get('fills') or []]} маржа {r.get('margin')} плечо {r.get('lev')} "
                  f"выход {r.get('exit')} usd {r.get('usd')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
