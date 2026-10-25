#!/usr/bin/env python3
"""Зонд режима у коротких книг (вопрос владельца 25.10): как ловить трендовые
падения и мало терять на неделях пампов.

Два замера по кэшу коротких, без правок правил и без реплея:

1. **Повторный вход после своего пола — где цена?** Пауза режет ВСЕ повторные
   входы; здесь они делятся по месту входа относительно ПРЕДЫДУЩЕЙ позиции
   книги в том же имени: вход НИЖЕ цены пола (имя после отскока вернулось вниз —
   продолжение падения) и вход ВЫШЕ цены пола (имя ушло ещё выше — памп
   продолжается). Если минус живёт только в одной группе, правило уже есть —
   и оно не «пауза», а «не входить выше пола».

2. **Доля полов за прошлые 48 ч как датчик режима.** У книги за день до
   18.10 полов 0–14 %, в неделю пампов 28–50 %. Дни делятся по доле полов
   среди выходов книги за предыдущие двое суток; смотрится результат ДНЯ
   (по дню входа). Нуль — перестановка меток дней на 20 зёрнах.

Числа — $10k, нетто, половины по времени входа, вперёд с дня записи семейства.
Отчёт `out/REGIME-probe.md`, `out/regime_probe.json`.
"""
import argparse
import calendar
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "mech_193cbb87"))

import rules as R                                             # noqa: E402
import run_short as S                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import costs as CO                                            # noqa: E402
import what_if_short as W                                     # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "REGIME-probe.md")
LATEST = os.path.join(OUT, "regime_probe.json")
BOOKS = ["safe_h", "optimal_h", "aggr_h"]
DEP = 10000.0
GAP_H = 48.0                     # повторный вход считается таким, если прошлая позиция имени закрылась не раньше
LOOK_H = 48.0                    # окно датчика: выходы за прошлые 48 ч
MIN_EXITS = 5                    # меньше выходов — режим «не измерен»
BUCKETS = [("<10 %", 0.0, 0.10), ("10–25 %", 0.10, 0.25), ("≥ 25 %", 0.25, 1.01)]
SEEDS = 20
TRIG = W.TRIGGER_EXITS


def day_of(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))


def shorts_rows(bk, cache, launch, now, ctx):
    packed = W.h24_packed(cache, BOOKS, launch, now, lambda *a: None)
    rows = W.plain_rows(packed[bk], bk, DEP, now)
    rows, _cs = CO.apply_to_rows(rows, ctx)
    mine = [r for r in rows if r.get("ruler") == bk and int(r.get("dep", 0)) == int(DEP)
            and not r.get("sizing") and r.get("usd") is not None and (r.get("side") or "long") == "short"]
    mine.sort(key=lambda r: (float(r["at"]), str(r["sym"])))
    return mine


def agg(rows):
    if not rows:
        return {"n": 0, "usd": 0.0, "floors": 0, "floor_share": None, "median_usd": None}
    us = sorted(float(r["usd"]) for r in rows)
    fl = sum(1 for r in rows if r.get("exit") in TRIG)
    return {"n": len(rows), "usd": round(sum(us), 2), "floors": fl, "floor_share": round(fl / len(rows), 3),
            "median_usd": round(us[len(us) // 2], 2)}


def split_windows(rows, mid, fwd_ts):
    return {"all": agg(rows), "first": agg([r for r in rows if float(r["at"]) < mid]),
            "second": agg([r for r in rows if float(r["at"]) >= mid]),
            "forward": agg([r for r in rows if fwd_ts and float(r["at"]) >= fwd_ts])}


def reentries(rows, mid, fwd_ts):
    """Повторные входы после СВОЕГО пола в имени, по месту входа относительно
    цены пола и цены входа прежней позиции."""
    prev = {}
    groups = {"ниже пола": [], "выше пола": [], "выше входа прежней": [], "ниже входа прежней": [], "первый или не после пола": []}
    for r in rows:
        p = prev.get(r["sym"])
        if p and p.get("exit") in TRIG and 0 <= float(r["at"]) - float(p["exit_ts"]) <= GAP_H * 3600:
            px, fpx, epx = float(r["entry_px"]), float(p["exit_px"]), float(p["entry_px"])
            groups["ниже пола" if px <= fpx else "выше пола"].append(r)
            groups["ниже входа прежней" if px <= epx else "выше входа прежней"].append(r)
        else:
            groups["первый или не после пола"].append(r)
        prev[r["sym"]] = r
    return {g: split_windows(rs, mid, fwd_ts) for g, rs in groups.items()}


def regime(rows, mid, fwd_ts):
    """Дни по доле полов среди выходов за прошлые 48 ч → результат дня."""
    exits = sorted((float(r["exit_ts"]), r.get("exit") in TRIG) for r in rows if r.get("exit_ts") is not None)
    days = sorted({day_of(r["at"]) for r in rows})
    per_day = {}
    for d in days:
        t0 = calendar.timegm(time.strptime(d, "%Y-%m-%d"))
        win = [f for (t, f) in exits if t0 - LOOK_H * 3600 <= t < t0]
        share = (sum(win) / len(win)) if len(win) >= MIN_EXITS else None
        mine = [r for r in rows if day_of(r["at"]) == d]
        per_day[d] = {"share_prev": share, "n_prev": len(win), "usd": sum(float(r["usd"]) for r in mine),
                      "n": len(mine), "floors": sum(1 for r in mine if r.get("exit") in TRIG),
                      "half": "first" if t0 < mid else "second", "fwd": bool(fwd_ts and t0 >= fwd_ts)}

    def bucket_of(share):
        if share is None:
            return "не измерен"
        for name, lo, hi in BUCKETS:
            if lo <= share < hi:
                return name
        return "≥ 25 %"
    out = {}
    for scope in ("all", "first", "second", "forward"):
        sel = {d: v for d, v in per_day.items()
               if scope == "all" or (scope == "forward" and v["fwd"]) or v["half"] == scope}
        tab = {}
        for d, v in sel.items():
            b = tab.setdefault(bucket_of(v["share_prev"]), {"days": 0, "usd": 0.0, "n": 0, "floors": 0})
            b["days"] += 1
            b["usd"] += v["usd"]
            b["n"] += v["n"]
            b["floors"] += v["floors"]
        for b in tab.values():
            b["usd"] = round(b["usd"], 2)
            b["usd_per_day"] = round(b["usd"] / b["days"], 2) if b["days"] else None
            b["floor_share"] = round(b["floors"] / b["n"], 3) if b["n"] else None
        # нуль: бакет «≥ 25 %» против случайного набора дней того же числа (из измеренных дней)
        hot = [d for d, v in sel.items() if bucket_of(v["share_prev"]) == "≥ 25 %"]
        meas = [d for d, v in sel.items() if v["share_prev"] is not None]
        null = None
        if hot and len(meas) > len(hot):
            hot_usd = sum(sel[d]["usd"] for d in hot)
            draws = []
            for seed in range(SEEDS):
                pick = random.Random(seed).sample(meas, len(hot))
                draws.append(sum(sel[d]["usd"] for d in pick))
            draws.sort()
            null = {"hot_usd": round(hot_usd, 2), "null_med": round(draws[len(draws) // 2], 2),
                    "share_le": round(sum(1 for x in draws if x <= hot_usd) / len(draws), 2), "seeds": SEEDS}
        out[scope] = {"buckets": tab, "null": null}
    return out, per_day


def run(books, log=print, now=None):
    now = now or time.time()
    R.SIZINGS = (R.SIZING_COMPOUND,)
    ctx = CO.context()
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш коротких: {why}"}
    launch = IR.launches()
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "dep": DEP, "gap_h": GAP_H,
           "look_h": LOOK_H, "min_exits": MIN_EXITS, "books": {}}
    for bk in books:
        rows = shorts_rows(bk, cache, launch, now, ctx)
        ats = [float(r["at"]) for r in rows]
        mid = ats[len(ats) // 2] if ats else 0.0
        since = R.family_since(bk)
        fwd_ts = calendar.timegm(time.strptime(since, "%Y-%m-%d")) if since else None
        reg, per_day = regime(rows, mid, fwd_ts)
        res["books"][bk] = {"n": len(rows), "usd": round(sum(float(r["usd"]) for r in rows), 2),
                            "mid": day_of(mid) if mid else None, "forward_since": since,
                            "reentries": reentries(rows, mid, fwd_ts), "regime": reg,
                            "days": {d: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in x.items()}
                                     for d, x in per_day.items()}}
        log(f"{bk}: позиций {len(rows)}, дней {len(per_day)}, середина {day_of(mid) if mid else '—'}")
    return res


def usd(x):
    return "—" if x is None else f"{x:+.0f} $"


def share(x):
    return "—" if x is None else f"{100 * x:.0f} %"


def report(r):
    if r.get("error"):
        return f"# Зонд режима коротких\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    L = ["# Зонд режима у коротких книг: повторные входы и доля полов", "",
         f"Посчитано {r['computed_at']}; ${r['dep']:.0f}, нетто, только короткие позиции книги. Повторный вход — "
         f"позиция в имени, чья предыдущая позиция книги в этом имени закрылась полом или ликвидацией не раньше "
         f"{r['gap_h']:.0f} ч до входа. Датчик режима — доля полов среди выходов книги за прошлые {r['look_h']:.0f} ч "
         f"(меньше {r['min_exits']} выходов — «не измерен»); результат дня — по дню ВХОДА. Описание, не правило: "
         "пороги бакетов заданы до счёта, нуль — случайные дни того же числа.", ""]
    for bk, b in r["books"].items():
        L += [f"## {R.RULERS.get(bk, {}).get('title', bk)} (`{bk}`) — позиций {b['n']}, итог {usd(b['usd'])}, "
              f"середина {b['mid']}, вперёд с {b['forward_since']}", "",
              "### Повторные входы после своего пола: где цена входа", "",
              "| группа | окно | сделок | итог $ | полов | доля полов | медиана $ |", "|---|---|--:|--:|--:|--:|--:|"]
        for g, w in b["reentries"].items():
            for scope, nm in (("all", "всё"), ("first", "1-я половина"), ("second", "2-я половина"), ("forward", "вперёд")):
                a = w[scope]
                L.append(f"| {g} | {nm} | {a['n']} | {usd(a['usd'])} | {a['floors']} | {share(a['floor_share'])} | {usd(a['median_usd'])} |")
        L += ["", "### Доля полов за прошлые 48 ч → результат дня", "",
              "| окно | доля полов вчера-позавчера | дней | итог $ | $ в день | полов сегодня |", "|---|---|--:|--:|--:|--:|"]
        for scope, nm in (("all", "всё"), ("first", "1-я половина"), ("second", "2-я половина"), ("forward", "вперёд")):
            tab = b["regime"][scope]["buckets"]
            for name in [x[0] for x in BUCKETS] + ["не измерен"]:
                t = tab.get(name)
                if t:
                    L.append(f"| {nm} | {name} | {t['days']} | {usd(t['usd'])} | {usd(t['usd_per_day'])} | {share(t['floor_share'])} |")
            z = b["regime"][scope]["null"]
            if z:
                L.append(f"| {nm} | нуль «≥ 25 %»: случайные дни того же числа | | медиана {usd(z['null_med'])} | "
                         f"доля ≤ факта {z['share_le']:.2f} | |")
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default=",".join(BOOKS))
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                      # noqa: E402
    log = AB.guarded(print, limit=W.MEM_LIMIT_MB)
    r = run([b for b in a.books.split(",") if b], log=log)
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "зонд режима коротких: повторные входы и доля полов"],
                       cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
