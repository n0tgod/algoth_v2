#!/usr/bin/env python3
"""Замер: что станет с длинными книгами Ladder, если отсечь не-крипто
(вопрос владельца 2026-10-15, перп на фонд SK Hynix в книге со сроком 72 ч).

Считается КАССОЙ (`run_paper.build_rows`), а не вычитанием сделок из
журнала: касса раздаёт освободившиеся места другим решениям, и вычитание
врёт про итог и дисперсию (урок 03.10). Три прогона на одном кэше реплея:

* «как есть» — все решения;
* «без не-крипто» — решения по именам из `universe_filter.non_crypto_set`;
* НУЛЬ — выброшено СЛУЧАЙНОЕ подмножество решений ТОГО ЖЕ размера,
  `--seeds` зёрен: фильтр, режущий сделки, сравнивается с таким же
  срезом наугад (урок 08.09), иначе «стало лучше» может быть просто «стало
  меньше сделок».

Плюс половины окна (по моменту решения): правило, выигравшее на всём
окне, проверяется половинами ДО слова «лучше» (урок 08.10). Порог и
сетка объявлены здесь до прогона: деньги — сложный процент, депозиты
книги, все три режима. Ничего не меняет в книгах.

    run research/dca_paper/noncrypto_cut.py --seeds=30
"""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import arm_book as AB                                          # noqa: E402
import rules as R                                              # noqa: E402
import run_paper as RP                                         # noqa: E402
from common import universe_filter as UF                       # noqa: E402

OUT_MD = os.path.join(R.OUT, "NONCRYPTO-cut.md")
OUT_JSON = os.path.join(R.OUT, "NONCRYPTO-cut.json")
METRICS = ("final", "max_dd", "open_dd_share", "taken")


def by_ruler_of(cache, keys, keep=None):
    pairs = {k: tuple(RP.RULERS[k]) for k in keys}
    out = {k: [] for k in keys}
    for (pr, _sym, _at), r in cache.items():
        for k in keys:
            if tuple(pr) == pairs[k] and (keep is None or keep(r)):
                out[k].append(r)
    return out


def cash(cache, keys, keep=None):
    rows, cells, one, live = RP.build_rows(by_ruler_of(cache, keys, keep), keys=keys,
                                           log=lambda *a: None)
    res = {}
    for k in keys:
        for d in R.DEPOSITS:
            c = cells.get(RP._cell(k, d)) or {}
            res[f"{k}:{int(d)}"] = {m: c.get(m) for m in METRICS}
    return res


def pctl(x, xs):
    xs = sorted(v for v in xs if v is not None)
    if x is None or not xs:
        return None
    return round(sum(1 for v in xs if v < x) / len(xs), 3)


def fmt(v, pct=True):
    if v is None:
        return "—"
    return f"{v * 100:+.1f} %" if pct else str(v)


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
    dec = sorted({(r["sym"], round(float(r["at"]), 3)) for r in cache.values()})
    nc = {x for x in dec if UF.is_non_crypto(x[0], ref)}
    names = sorted({s for s, _ in nc})
    log(f"решений в кэше {len(dec)}, из них не-крипто {len(nc)} ({len(nc) / max(1, len(dec)) * 100:.1f} %), "
        f"имён {len(names)}: {', '.join(names)}")
    key = lambda r: (r["sym"], round(float(r["at"]), 3))         # noqa: E731
    base = cash(cache, keys)
    cut = cash(cache, keys, keep=lambda r: key(r) not in nc)
    log(f"как есть и без не-крипто посчитаны ({time.time() - t0:.0f} с)")
    nulls = []
    rng = random.Random(20261015)
    for s in range(a.seeds):
        drop = set(rng.sample(dec, len(nc)))
        nulls.append(cash(cache, keys, keep=lambda r, drop=drop: key(r) not in drop))
        if (s + 1) % 5 == 0:
            log(f"  нуль: {s + 1}/{a.seeds} зёрен ({time.time() - t0:.0f} с)")
    ats = sorted(x[1] for x in dec)
    mid = ats[len(ats) // 2]
    halves = {}
    for name, inside in (("первая", lambda r: float(r["at"]) < mid), ("вторая", lambda r: float(r["at"]) >= mid)):
        halves[name] = {
            "base": cash(cache, keys, keep=inside),
            "cut": cash(cache, keys, keep=lambda r, f=inside: f(r) and key(r) not in nc)}
    log(f"половины посчитаны ({time.time() - t0:.0f} с); граница {time.strftime('%Y-%m-%d', time.gmtime(mid))}")

    L = ["# Ladder без не-крипто: замер кассой", "",
         f"Решений в кэше {len(dec)}, не-крипто {len(nc)} ({len(nc) / max(1, len(dec)) * 100:.1f} %), "
         f"имена: {', '.join(names)}. Нуль — {a.seeds} случайных срезов того же размера. "
         "Сложный процент; доля «под нулём» — сколько случайных срезов дали итог НИЖЕ, чем отсечение "
         "не-крипто (0.5 — неотличимо от случайного; около 1 — отсечение лучше случайного).", "",
         "| книга | итог как есть | итог без не-крипто | нуль: медиана | доля нуля ниже | просадка как есть → без | открытые как есть → без | сделок как есть → без |",
         "|---|--:|--:|--:|--:|--:|--:|--:|"]
    out = {"decisions": len(dec), "noncrypto": len(nc), "names": names, "seeds": a.seeds, "cells": {}}
    for k in base:
        b, c = base[k], cut[k]
        nf = [n[k]["final"] for n in nulls]
        med = sorted(v for v in nf if v is not None)
        med = med[len(med) // 2] if med else None
        out["cells"][k] = {"base": b, "cut": c, "null_median_final": med, "null_below": pctl(c["final"], nf),
                           "halves": {h: {"base": halves[h]["base"][k], "cut": halves[h]["cut"][k]} for h in halves}}
        L.append(f"| {k} | {fmt(b['final'])} | {fmt(c['final'])} | {fmt(med)} | {fmt(pctl(c['final'], nf), False)} | "
                 f"{fmt(b['max_dd'])} → {fmt(c['max_dd'])} | {fmt(b['open_dd_share'])} → {fmt(c['open_dd_share'])} | "
                 f"{fmt(b['taken'], False)} → {fmt(c['taken'], False)} |")
    L += ["", "## По половинам окна", "", "| книга | 1-я: как есть → без | 2-я: как есть → без |", "|---|--:|--:|"]
    for k in base:
        h1, h2 = halves["первая"], halves["вторая"]
        L.append(f"| {k} | {fmt(h1['base'][k]['final'])} → {fmt(h1['cut'][k]['final'])} | "
                 f"{fmt(h2['base'][k]['final'])} → {fmt(h2['cut'][k]['final'])} |")
    L += ["", f"Прогон {time.time() - t0:.0f} с, {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC."]
    txt = "\n".join(L) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(txt)
    RP.publish("Ladder без не-крипто: замер кассой")
    return 0


if __name__ == "__main__":
    sys.exit(main())
