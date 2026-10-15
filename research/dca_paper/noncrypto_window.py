#!/usr/bin/env python3
"""Замер: не-крипто в Ladder — входить только в торговое окно биржи
(предложение владельца 2026-10-15: «если не торгуются — не открывать»).

Правило объявлено ДО прогона, таблицей окна по бирже (UTC, пн–пт,
праздники не учтены — это названо в отчёте):

* США (умолчание; август–октябрь — летнее время): 13:30–20:00;
* Гонконг/Китай (`HK`): 01:30–08:00;  Корея (`KR`): 00:00–06:30;
* золото (`XAU`): 00:00–21:00.

Варианты:
* A — вход по не-крипто только в часы окна своей биржи;
* B — A и срок 72 ч кончается до закрытия пятничного окна той же недели
  (позиция не переживает выходные; выход по сроку — тоже в окне).

Касса (`run_paper.build_rows`) на кэше реплея, рядом «как есть» и
«отсечь всё не-крипто»; нуль — тот же ЧИСЛОМ срез случайных решений
(`--seeds`); половины окна записи. Книги не меняет.

    run research/dca_paper/noncrypto_window.py --seeds=30
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import arm_book as AB                                          # noqa: E402
import rules as R                                              # noqa: E402
import run_paper as RP                                         # noqa: E402
from common import universe_filter as UF                       # noqa: E402
from noncrypto_cut import cash, fmt, pctl                      # noqa: E402

OUT_MD = os.path.join(R.OUT, "NONCRYPTO-window.md")
OUT_JSON = os.path.join(R.OUT, "NONCRYPTO-window.json")
HOLD_H = 72
HK = {"MEITUAN", "XIAOMI", "TENCENT", "POPMART", "SMIC", "MINIMAX", "ZHIPU", "KUAISHOU",
      "CSOPSKHYNIX2L", "CSOPSAMSUNG2L", "GIGADEVICE", "CXMT"}
KR = {"SAMSUNG", "SKHY", "HYUNDAI"}
SESS = {"US": (13 * 60 + 30, 20 * 60), "HK": (90, 8 * 60), "KR": (0, 6 * 60 + 30), "XAU": (0, 21 * 60)}


def market(sym):
    b = sym[:-4] if sym.endswith("USDT") else sym
    if b in HK:
        return "HK"
    if b in KR:
        return "KR"
    if b == "XAU":
        return "XAU"
    return "US"


def in_session(ts, mk):
    g = time.gmtime(ts)
    if g.tm_wday >= 5:
        return False
    m = g.tm_hour * 60 + g.tm_min
    lo, hi = SESS[mk]
    return lo <= m < hi


def fits_week(ts, mk):
    """Срок кончается до закрытия пятничного окна той же недели."""
    end = ts + HOLD_H * 3600
    g = time.gmtime(ts)
    day0 = ts - (g.tm_hour * 3600 + g.tm_min * 60 + g.tm_sec)
    fri_close = day0 + (4 - g.tm_wday) * 86400 + SESS[mk][1] * 60
    return end <= fri_close


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    a = ap.parse_args()
    log = AB.guarded(print, limit=2400)
    t0 = time.time()
    cache, why = RP.read_cache()
    if why or not cache:
        print(f"кэш реплея не читается: {why or 'пуст'} — замера нет")
        return 2
    keys = list(R.order_of("sit"))
    ref = UF.non_crypto_set()
    dec = sorted({(k[1], round(float(k[2]), 3)) for k in cache})
    nc = [x for x in dec if UF.is_non_crypto(x[0], ref)]
    drop_a = {x for x in nc if not in_session(x[1], market(x[0]))}
    drop_b = {x for x in nc if not (in_session(x[1], market(x[0])) and fits_week(x[1], market(x[0])))}
    mk = Counter(market(s) for s, _ in nc)
    log(f"решений {len(dec)}, не-крипто {len(nc)} (по биржам {dict(mk)}); "
        f"A отсекает {len(drop_a)}, B отсекает {len(drop_b)}")
    key = lambda r: (r["sym"], round(float(r["at"]), 3))         # noqa: E731
    ncs = set(nc)
    var = {"как есть": cash(cache, keys),
           "A: только в окне": cash(cache, keys, keep=lambda r: key(r) not in drop_a),
           "B: окно и без выходных": cash(cache, keys, keep=lambda r: key(r) not in drop_b),
           "отсечь всё": cash(cache, keys, keep=lambda r: key(r) not in ncs)}
    rng = random.Random(20261015)
    nulls = {"A": [], "B": []}
    for s in range(a.seeds):
        for nm, dr in (("A", drop_a), ("B", drop_b)):
            d = set(rng.sample(dec, len(dr)))
            nulls[nm].append(cash(cache, keys, keep=lambda r, d=d: key(r) not in d))
        if (s + 1) % 10 == 0:
            log(f"  нуль: {s + 1}/{a.seeds} зёрен ({time.time() - t0:.0f} с)")
    ats = sorted(x[1] for x in dec)
    mid = ats[len(ats) // 2]
    halves = {}
    for hn, inside in (("1-я", lambda r: float(r["at"]) < mid), ("2-я", lambda r: float(r["at"]) >= mid)):
        halves[hn] = {"base": cash(cache, keys, keep=inside),
                      "B": cash(cache, keys, keep=lambda r, f=inside: f(r) and key(r) not in drop_b)}
    L = ["# Ladder: не-крипто только в торговом окне биржи — замер кассой", "",
         f"Решений {len(dec)}, не-крипто {len(nc)} (по биржам: {dict(mk)}). Окна UTC пн–пт: США 13:30–20:00, "
         "Гонконг/Китай 01:30–08:00, Корея 00:00–06:30, золото 00:00–21:00; праздники не учтены.",
         f"A — вход только в окне: отсекает {len(drop_a)} решений. B — в окне и срок 72 ч кончается до "
         f"закрытия пятницы: отсекает {len(drop_b)}. Нуль — случайный срез того же числа, {a.seeds} зёрен; "
         "«доля нуля ниже» — сколько случайных срезов дали итог ниже правила (около 0.5 — неотличимо).", "",
         "| книга | как есть | A: в окне | доля нуля ниже A | B: окно, без выходных | доля нуля ниже B | отсечь всё | просадка: как есть → B |",
         "|---|--:|--:|--:|--:|--:|--:|--:|"]
    out = {"decisions": len(dec), "noncrypto": len(nc), "drop_a": len(drop_a), "drop_b": len(drop_b),
           "by_market": dict(mk), "cells": {}}
    for k in var["как есть"]:
        b = var["как есть"][k]
        A, B, C = var["A: только в окне"][k], var["B: окно и без выходных"][k], var["отсечь всё"][k]
        pa = pctl(A["final"], [n[k]["final"] for n in nulls["A"]])
        pb = pctl(B["final"], [n[k]["final"] for n in nulls["B"]])
        out["cells"][k] = {"base": b, "A": A, "B": B, "cut": C, "null_below_A": pa, "null_below_B": pb,
                           "halves": {h: {"base": halves[h]["base"][k], "B": halves[h]["B"][k]} for h in halves}}
        L.append(f"| {k} | {fmt(b['final'])} | {fmt(A['final'])} | {fmt(pa, False)} | {fmt(B['final'])} | "
                 f"{fmt(pb, False)} | {fmt(C['final'])} | {fmt(b['max_dd'])} → {fmt(B['max_dd'])} |")
    L += ["", "## Вариант B по половинам окна", "", "| книга | 1-я: как есть → B | 2-я: как есть → B |", "|---|--:|--:|"]
    for k in var["как есть"]:
        L.append(f"| {k} | {fmt(halves['1-я']['base'][k]['final'])} → {fmt(halves['1-я']['B'][k]['final'])} | "
                 f"{fmt(halves['2-я']['base'][k]['final'])} → {fmt(halves['2-я']['B'][k]['final'])} |")
    L += ["", f"Граница половин {time.strftime('%Y-%m-%d', time.gmtime(mid))}. Прогон {time.time() - t0:.0f} с, "
          f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC."]
    txt = "\n".join(L) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(txt)
    RP.publish("Ladder: не-крипто только в торговом окне — замер кассой")
    return 0


if __name__ == "__main__":
    sys.exit(main())
