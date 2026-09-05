#!/usr/bin/env python3
"""Сколько ШОРТОВ вообще есть в журнале листов под теми же гейтами.

Вопрос владельца: завести зеркальные короткие DCA-книги, чтобы они
СГЛАЖИВАЛИ длинные. Прежде чем строить девять книг, надо знать, из чего
их набирать: D2 (вариант «в») намерил, что под гейтом `край ≥ 33 б.п.,
RR ≥ 2` шортов было 258 из 8670 (3 %). Если так и осталось, зеркальные
книги окажутся почти пустыми и сглаживать им нечем — а узнать это стоит
минуты и не требует ни одного бара.

Считаем ровно то, что решает вопрос:
  - ноги журнала по сторонам, до гейта и после;
  - календарь: в скольких сутках у шортов есть хоть одна нога (книга,
    торгующая треть суток, не может сглаживать книгу, торгующую все);
  - пересечение суток с лонгами — сглаживание требует ОБЩИХ дней, а не
    просто числа сделок.

Ни одного вывода про деньги здесь нет и быть не может: исход ноги — это
бары, а бар тут не читается. Это замер СЫРЬЯ.
"""

import argparse
import collections
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "s10_policy"), os.path.join(ROOT, "dca_ladder")):
    if p not in sys.path:
        sys.path.insert(0, p)

import tournament as TNT              # noqa: E402
import run_d2 as D2                   # noqa: E402
import rules as R                     # noqa: E402

OUT = os.path.join(HERE, "out")


def day(ts):
    return dt.datetime.utcfromtimestamp(float(ts)).strftime("%Y-%m-%d")


def collect(log=print):
    legs = TNT.legs_from_sheets([D2.SHEETS], log=log)
    by = {"long": [], "short": []}
    gated = {"long": [], "short": []}
    for g in legs:
        s = g.get("side")
        if s not in by:
            continue
        by[s].append(g)
        if abs(g["fwd"]) >= D2.MIN_EDGE_BP and (g["rr"] or 0) >= D2.MIN_RR:
            gated[s].append(g)
    return by, gated


def stats(by, gated):
    days = {s: collections.Counter(day(g["at"]) for g in gated[s])
            for s in gated}
    both = set(days["long"]) & set(days["short"])
    out = {
        "legs": {s: len(by[s]) for s in by},
        "gated": {s: len(gated[s]) for s in gated},
        "days": {s: len(days[s]) for s in days},
        "days_both": len(both),
        "names": {s: len({g["sym"] for g in gated[s]}) for s in gated},
        "per_day": {s: dict(sorted(days[s].items())) for s in days},
    }
    tot = out["gated"]["long"] + out["gated"]["short"]
    out["short_share"] = (out["gated"]["short"] / tot) if tot else None
    return out


def report(s):
    g, l = s["gated"], s["legs"]
    sh = s["short_share"]
    L = []
    L.append("# Сырьё зеркальной короткой DCA-книги\n")
    L.append("Замер СЫРЬЯ, не денег: бары здесь не читаются вовсе. Он "
             "отвечает на один вопрос — из чего набирать короткие книги "
             "под теми же гейтами, что длинные "
             f"(край ≥ {D2.MIN_EDGE_BP:g} б.п., RR ≥ {D2.MIN_RR:g}).\n")
    L.append("| величина | лонг | шорт |")
    L.append("|---|---:|---:|")
    L.append(f"| ног в журнале | {l['long']} | {l['short']} |")
    L.append(f"| под гейтом | {g['long']} | {g['short']} |")
    L.append(f"| имён под гейтом | {s['names']['long']} | {s['names']['short']} |")
    L.append(f"| суток со сделками | {s['days']['long']} | {s['days']['short']} |")
    L.append("")
    L.append(f"Доля шортов под гейтом — "
             f"**{'—' if sh is None else format(sh, '.3f')}**; общих суток "
             f"у сторон {s['days_both']}.\n")
    L.append("Как это читать. Сглаживание требует ОБЩИХ суток, а не просто "
             "числа сделок: книга, торгующая треть календаря, не может "
             "выравнивать книгу, торгующую весь. Поэтому строка «суток со "
             "сделками» здесь важнее строки «под гейтом».\n")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="1m")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    by, gated = collect()
    s = stats(by, gated)
    print(f"ног: лонг {s['legs']['long']}, шорт {s['legs']['short']}; "
          f"под гейтом: лонг {s['gated']['long']}, шорт {s['gated']['short']}")
    print(f"суток: лонг {s['days']['long']}, шорт {s['days']['short']}, "
          f"общих {s['days_both']}")
    path = os.path.join(OUT, f"DCA-short-supply-{a.tag}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report(s))
    print("отчёт:", path)
    sys.path.insert(0, os.path.join(ROOT, "..", "tools"))
    os.system(f"bash {os.path.join(ROOT, '..', 'tools', 'publish.sh')} "
              f"'DCA: сырьё зеркальной короткой книги'")


if __name__ == "__main__":
    main()
