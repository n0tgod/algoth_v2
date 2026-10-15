#!/usr/bin/env python3
"""Замер: что сделало отсечение не-крипто с ОБЩИМ счётом (Both) и с
длинными книгами — по полному набору не-крипто (разметка площадки, 15.10).

Вопрос владельца 2026-10-15 вечером: после отсечения Both Depth $100
показал +2549 % (было +545 %), $1k +141 % (было +119 %) — так и должно
быть? Прежний замер (`noncrypto_cut.py`) считал только длинные книги и
по отставшему списку (833 решения); общий счёт не мерился вовсе.

Считается КАССОЙ тем же путём, что прогон общего счёта
(`run_pair.run`: гейт по ставке, возраст имени, охрана рынком, затем
`run_paper.build_rows`), на тех же кэшах реплея. Режется только ДЛИННАЯ
сторона — так устроено правило; короткая одинакова во всех вариантах.

* «как есть» — все длинные решения;
* «без не-крипто» — длинные решения по именам из `non_crypto_set`;
* НУЛЬ — выброшено СЛУЧАЙНОЕ подмножество длинных решений ТОГО ЖЕ
  размера, `--seeds` зёрен (урок 08.09);
* половины окна — по моменту решения (урок 08.10).

Ничего не меняет в книгах и журналах: `build_rows` журнал не пишет.

    run research/dca_paper/noncrypto_pair.py --seeds=20
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import run_pair as RPair                                       # noqa: E402  (пути и модули общего счёта)
import arm_book as AB                                          # noqa: E402
import rules as R                                              # noqa: E402
import run_paper as RP                                         # noqa: E402
import instruments_refresh as IR                               # noqa: E402
from common import universe_filter as UF                       # noqa: E402

OUT_MD = os.path.join(R.OUT, "NONCRYPTO-pair.md")
OUT_JSON = os.path.join(R.OUT, "NONCRYPTO-pair.json")
METRICS = ("final", "max_dd", "taken")


def key(r):
    return (r["sym"], round(float(r["at"]), 3))


def long_all(cache):
    """Длинные решения по книгам — БЕЗ отсечения (`run_pair.long_recs` режет)."""
    want = {}
    for k in R.order_of("sit"):
        want.setdefault(tuple(RP.RULERS[k]), []).append(k)
    out = {}
    for (pr, _sym, _at), r in cache.items():
        for k in want.get(tuple(pr), ()):
            out.setdefault(k, []).append(r)
    return out


def shorts_ready(shorts, ctx, launch, keys, now):
    """Короткая сторона под правилами входа — один раз на все варианты."""
    quiet = lambda *a: None                                    # noqa: E731
    packed = RPair.pack({}, shorts, keys)
    out = {}
    for pk in keys:
        kept, _ = RPair.gate_shorts(packed[pk], pk, ctx, log=quiet)
        kept, _ = RP.age_shorts(kept, pk, launch=launch, log=quiet, now=now)
        kept, _ = RP.guard_shorts(kept, pk, log=quiet, now=now)
        out[pk] = kept
    return out


def pair_cash(longs, sready, keys, keep, now):
    packed = RPair.pack({k: [r for r in v if keep(r)] for k, v in longs.items()},
                        {}, keys)
    for pk in keys:
        packed[pk] = packed[pk] + sready[pk]
    _rows, cells, _one, _live = RP.build_rows(packed, now=now, keys=keys,
                                              log=lambda *a: None)
    return {f"{pk}:{int(d)}": {m: (cells.get(RP._cell(pk, d)) or {}).get(m)
                               for m in METRICS}
            for pk in keys for d in R.DEPOSITS}


def long_cash(longs, keep, now):
    keys = list(R.order_of("sit"))
    by = {k: [r for r in longs.get(k, []) if keep(r)] for k in keys}
    _rows, cells, _one, _live = RP.build_rows(by, now=now, keys=keys,
                                              log=lambda *a: None)
    return {f"{k}:{int(d)}": {m: (cells.get(RP._cell(k, d)) or {}).get(m)
                              for m in METRICS}
            for k in keys for d in R.DEPOSITS}


def pctl(x, xs):
    xs = sorted(v for v in xs if v is not None)
    if x is None or not xs:
        return None
    return round(sum(1 for v in xs if v < x) / len(xs), 3)


def med(xs):
    xs = sorted(v for v in xs if v is not None)
    return xs[len(xs) // 2] if xs else None


def fmt(v):
    return "—" if v is None else f"{v * 100:+.1f} %"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    log = AB.guarded(print, limit=2400)
    t0 = time.time()
    now = time.time()
    lcache, why_l = RP.read_cache()
    scache, why_s = RPair.S.read_cache(log=lambda *x: None)
    if why_l or why_s or not lcache or not scache:
        print(f"кэши реплея не читаются: {why_l or why_s or 'пусты'} — замера нет")
        return 2
    longs = long_all(lcache)
    shorts, _ = RPair.short_recs(scache, log=lambda *x: None)
    import costs as CO
    ctx = CO.context()
    launch = IR.launches()
    keys = list(R.PAIR_ORDER)
    sready = shorts_ready(shorts, ctx, launch, keys, now)
    ref = UF.non_crypto_set()
    dec = sorted({key(r) for v in longs.values() for r in v})
    nc = {x for x in dec if UF.is_non_crypto(x[0], ref)}
    old_ref = UF.reference_non_crypto() | set(UF.NON_CRYPTO_NEW)
    nc_old = {x for x in dec if UF.is_non_crypto(x[0], old_ref)}
    names = sorted({s for s, _ in nc})
    log(f"длинных решений {len(dec)}, не-крипто {len(nc)} (по старому списку "
        f"{len(nc_old)}), имён {len(names)}; набор {len(ref)}")
    every = lambda r: True                                     # noqa: E731
    no_nc = lambda r: key(r) not in nc                         # noqa: E731
    res = {"pair": {}, "long": {}}
    for fam, fn in (("pair", lambda k: pair_cash(longs, sready, keys, k, now)),
                    ("long", lambda k: long_cash(longs, k, now))):
        base, cut = fn(every), fn(no_nc)
        log(f"{fam}: как есть и без не-крипто ({time.time() - t0:.0f} с)")
        rng = random.Random(20261015)
        nulls = []
        for s in range(a.seeds):
            drop = set(rng.sample(dec, len(nc)))
            nulls.append(fn(lambda r, d=drop: key(r) not in d))
            if (s + 1) % 5 == 0:
                log(f"  {fam} нуль: {s + 1}/{a.seeds} ({time.time() - t0:.0f} с)")
        ats = sorted(x[1] for x in dec)
        mid = ats[len(ats) // 2]
        halves = {}
        for h, inside in (("1", lambda r: float(r["at"]) < mid),
                          ("2", lambda r: float(r["at"]) >= mid)):
            halves[h] = (fn(inside), fn(lambda r, f=inside: f(r) and no_nc(r)))
        res[fam] = {"base": base, "cut": cut, "nulls": nulls, "halves": halves,
                    "mid": mid}
    L = ["# Не-крипто по разметке площадки: общий счёт и длинные книги — замер кассой", "",
         f"Длинных решений {len(dec)}, не-крипто по полному набору {len(nc)} "
         f"(по старому списку было {len(nc_old)}), имён {len(names)}. Короткая сторона "
         f"общего счёта одинакова во всех вариантах. Нуль — {a.seeds} случайных срезов "
         "длинных решений того же размера; «доля нуля ниже» — сколько случайных срезов "
         "дали итог НИЖЕ отсечения (0.5 — неотличимо от случайного). Сложный процент, "
         "со всем бэктестом.", ""]
    out = {"decisions": len(dec), "noncrypto": len(nc), "noncrypto_old_list": len(nc_old),
           "names": names, "seeds": a.seeds, "cells": {}}
    for fam, title in (("pair", "Общий счёт (Both)"), ("long", "Длинные книги (Long)")):
        r = res[fam]
        L += [f"## {title}", "",
              "| книга | как есть | без не-крипто | нуль: медиана | нуль: 10–90 % | доля нуля ниже | просадка как есть → без | 1-я половина как есть → без | 2-я половина как есть → без |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for k in r["base"]:
            b, c = r["base"][k], r["cut"][k]
            nf = sorted(v for v in (n[k]["final"] for n in r["nulls"]) if v is not None)
            lo = nf[int(len(nf) * 0.1)] if nf else None
            hi = nf[min(len(nf) - 1, int(len(nf) * 0.9))] if nf else None
            h1, h2 = r["halves"]["1"], r["halves"]["2"]
            out["cells"][f"{fam}/{k}"] = {"base": b, "cut": c, "null_median": med(nf),
                                          "null_p10": lo, "null_p90": hi,
                                          "null_below": pctl(c["final"], nf),
                                          "half1": [h1[0][k]["final"], h1[1][k]["final"]],
                                          "half2": [h2[0][k]["final"], h2[1][k]["final"]]}
            L.append(f"| {k} | {fmt(b['final'])} | {fmt(c['final'])} | {fmt(med(nf))} | "
                     f"{fmt(lo)} … {fmt(hi)} | {pctl(c['final'], nf)} | "
                     f"{fmt(b['max_dd'])} → {fmt(c['max_dd'])} | "
                     f"{fmt(h1[0][k]['final'])} → {fmt(h1[1][k]['final'])} | "
                     f"{fmt(h2[0][k]['final'])} → {fmt(h2[1][k]['final'])} |")
        L.append("")
    L.append(f"Прогон {time.time() - t0:.0f} с, {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC.")
    txt = "\n".join(L)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "замер: не-крипто, общий счёт и длинные книги"],
                       cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
