#!/usr/bin/env python3
"""Замер: не-крипто в Ladder со сроком ДОЛЬШЕ 72 ч (вопрос владельца
2026-10-15: «дать им отработать, а не срезать в мёртвые часы»).

Объявлено до прогона: сетка срока для решений по не-крипто — 72 (как
сейчас), 120 и 168 ч; деньги — касса (`run_paper.build_rows`), сложный
процент, все режимы и депозиты. Остальные решения не трогаются.

* КАЛИБРОВКА: решения по не-крипто перепроигрываются с 72 ч и
  подставляются в кэш — касса обязана совпасть с «как есть». Иначе
  подстановка нечестна, и замер не печатается.
* НУЛЬ: тот же длинный срок (168 ч) выдаётся СЛУЧАЙНЫМ крипто-решениям
  того же числа (`--seeds` зёрен) — отличает «длинный срок помогает
  акциям» от «длинный срок помогает кому угодно».
* Рядом — вариант «отсечь» из прошлого замера и разбор выходов по сроку:
  сколько позиций не-крипто закрыто по сроку и в какие часы UTC.

    run research/dca_paper/noncrypto_hold.py --seeds=3
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
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import arm_book as AB                                          # noqa: E402
import rules as R                                              # noqa: E402
import run_paper as RP                                         # noqa: E402
import run_d6 as D6                                            # noqa: E402
import tail as TL                                              # noqa: E402
from common import universe_filter as UF                       # noqa: E402
from noncrypto_cut import cash, fmt                            # noqa: E402

OUT_MD = os.path.join(R.OUT, "NONCRYPTO-hold.md")
OUT_JSON = os.path.join(R.OUT, "NONCRYPTO-hold.json")
GRID = (72, 120, 168)


def kd(sym, at):
    return (str(sym), round(float(at), 3))


def replay(cache, legs, pairs, subset, hold, log):
    """Перепроиграть решения `subset` со сроком `hold` и подставить в копию кэша."""
    src = TL.TailBars(log=lambda *a: None, cache=TL.BARS_CACHE)
    got = D6.collect_recs(rulers=pairs, legs=legs, src=src, log=log, hold_h=hold,
                          only=sorted(subset))
    TL.apply(got["recs"], src.last_tape, src.last_book)
    new = {k: v for k, v in cache.items() if kd(k[1], k[2]) not in subset}
    fresh = []
    for pr, lst in got["recs"].items():
        for r in lst:
            new[(tuple(pr), r["sym"], round(float(r["at"]), 3))] = r
            fresh.append(r)
    RP.attach_fav(fresh, legs, log=lambda *a: None)
    return new, fresh


def exits(recs):
    by = Counter(r.get("exit") for r in recs)
    term = [r for r in recs if r.get("exit") == "срок" and r.get("exit_ts")]
    hours = Counter(time.gmtime(float(r["exit_ts"])).tm_hour for r in term)
    wd = Counter(time.strftime("%a", time.gmtime(float(r["exit_ts"]))) for r in term)
    return {"by_exit": dict(by), "term_hours_utc": dict(sorted(hours.items())), "term_weekdays": dict(wd)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    log = AB.guarded(print, limit=3000)
    t0 = time.time()
    cache, why = RP.read_cache()
    if why or not cache:
        print(f"кэш реплея не читается: {why or 'пуст'} — замера нет")
        return 2
    keys = list(R.order_of("sit"))
    pairs = []
    for k in keys:
        if RP.RULERS[k] not in pairs:
            pairs.append(RP.RULERS[k])
    sides = {R.side_of(k) for k in keys}
    legs = D6.gated_legs(side=(None if len(sides) > 1 else next(iter(sides), "long")), log=lambda *a: None)
    ref = UF.non_crypto_set()
    dec = sorted({kd(k[1], k[2]) for k in cache})
    nc = {x for x in dec if UF.is_non_crypto(x[0], ref)}
    cr = [x for x in dec if x not in nc]
    log(f"решений {len(dec)}, не-крипто {len(nc)}; сетка срока {GRID} ч, нуль {a.seeds} зёрен по 168 ч")
    base = cash(cache, keys)
    cut = cash(cache, keys, keep=lambda r: kd(r["sym"], r["at"]) not in nc)
    res, diag = {}, {}
    for h in GRID:
        c2, fresh = replay(cache, legs, pairs, nc, h, log)
        res[h] = cash(c2, keys)
        diag[h] = exits(fresh)
        log(f"не-крипто со сроком {h} ч: перепроиграно {len(fresh)} записей ({time.time() - t0:.0f} с)")
    # калибровка: 72 ч обязаны дать «как есть»
    off = [k for k in base if base[k]["final"] != res[72][k]["final"]]
    if off:
        worst = max(off, key=lambda k: abs((base[k]["final"] or 0) - (res[72][k]["final"] or 0)))
        log(f"КАЛИБРОВКА НЕ СОШЛАСЬ у {len(off)} книг из {len(base)} (худшая {worst}: "
            f"{base[worst]['final']} против {res[72][worst]['final']}) — подстановка нечестна, вывода нет")
    nulls = []
    rng = random.Random(20261015)
    for s in range(a.seeds):
        sub = set(rng.sample(cr, len(nc)))
        c2, _ = replay(cache, legs, pairs, sub, 168, log)
        nulls.append(cash(c2, keys))
        log(f"  нуль: зерно {s + 1}/{a.seeds} ({time.time() - t0:.0f} с)")
    L = ["# Ladder: не-крипто со сроком дольше 72 ч — замер кассой", "",
         f"Решений {len(dec)}, не-крипто {len(nc)}. Калибровка (72 ч перепроиграно = как есть): "
         + ("сошлась бит в бит." if not off else f"**НЕ сошлась у {len(off)} книг** — числа ниже не судить."), "",
         f"Нуль: срок 168 ч у {len(nc)} СЛУЧАЙНЫХ крипто-решений, {a.seeds} зёрен — прирост против «как есть».", "",
         "| книга | как есть (72) | не-крипто 120 ч | не-крипто 168 ч | отсечь | нуль 168 ч: приросты по зёрнам | просадка: как есть → 168 ч |",
         "|---|--:|--:|--:|--:|--:|--:|"]
    out = {"decisions": len(dec), "noncrypto": len(nc), "grid": GRID, "calibration_off": off, "cells": {}, "exits": diag}
    for k in base:
        b = base[k]["final"]
        dn = [(n[k]["final"] - b) if (n[k]["final"] is not None and b is not None) else None for n in nulls]
        out["cells"][k] = {"base": base[k], "cut": cut[k], **{f"h{h}": res[h][k] for h in GRID}, "null_delta": dn}
        L.append(f"| {k} | {fmt(b)} | {fmt(res[120][k]['final'])} | {fmt(res[168][k]['final'])} | {fmt(cut[k]['final'])} | "
                 + " / ".join(fmt(x) for x in dn) + f" | {fmt(base[k]['max_dd'])} → {fmt(res[168][k]['max_dd'])} |")
    L += ["", "## Как выходят позиции по не-крипто", "",
          "| срок | по причине выхода | выходы по сроку: часы UTC | дни недели |", "|---|---|---|---|"]
    for h in GRID:
        d = diag[h]
        L.append(f"| {h} ч | {d['by_exit']} | {d['term_hours_utc']} | {d['term_weekdays']} |")
    L += ["", f"Прогон {time.time() - t0:.0f} с, {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC. "
          "Позиции, чей срок ещё не истёк к концу записи, стоят открытыми — у 168 ч их больше, это видно в итоге."]
    txt = "\n".join(L) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(txt)
    RP.publish("Ladder: не-крипто с долгим сроком — замер кассой")
    return 0


if __name__ == "__main__":
    sys.exit(main())
