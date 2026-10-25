#!/usr/bin/env python3
"""Тормоз книги по рынку (владелец 25.10, пункт 3): доля отыгравшихся
вчерашних пампов по ВСЕЙ кросс-секции как датчик недели пампов.

Книга коротких ставит на то, что памп отыграется за сутки. Датчик меряет
ровно эту ставку на рынке в целом, без состава книги: на начало дня D
берутся имена, выросшие за позавчерашние сутки [D−48 ч, D−24 ч] не меньше
чем на PUMP (20 %); «отыгралось» — цена на D ниже цены на D−24 ч. Доля
отыгравшихся известна в 00:00 UTC дня D и судит день D. Меньше MIN_PUMPS
пампов — день «не измерен» (прочерк, не ноль).

Что считается (пороги объявлены до счёта): дни коротких книг по бакетам
доли (< 0.5 — «тормоз», ≥ 0.5, не измерен) → результат дня по входу, с
нулём перестановки меток дней (200); what-if кассой «без шортов в дни
тормоза» против случайных дней того же числа (20 зёрен); половины и вперёд.
Половина билета кассой здесь не считается (нужен прогон кассы с билетом по
дню) — названо, не подменено.

Отчёт `out/PUMP-brake.md`, `out/pump_brake.json`.
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
import wave as WV                                             # noqa: E402
import what_if_short as W                                     # noqa: E402
import regime_probe as P                                      # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "PUMP-brake.md")
LATEST = os.path.join(OUT, "pump_brake.json")
BOOKS = ["safe_h", "optimal_h", "aggr_h"]
DEP = 10000.0
PUMP = 0.20                     # рост за сутки, с которого имя — памп
MIN_PUMPS = 5                   # меньше — день не измерен
THRESH = 0.5                    # доля отыгравшихся ниже — тормоз
PERM = 200
SEEDS = 20
DAY = 86400.0


def universe(root):
    try:
        return sorted(d for d in os.listdir(root) if d.endswith("USDT") and os.path.isdir(os.path.join(root, d)))
    except OSError:
        return []


def reversal_share(mkt, syms, day_ts, pump=PUMP, min_pumps=MIN_PUMPS):
    """→ (доля отыгравшихся, число пампов, медиана хода пампов за вчера)."""
    pumps, moves = [], []
    for s in syms:
        p2, p1, p0 = mkt.px(s, day_ts - 2 * DAY), mkt.px(s, day_ts - DAY), mkt.px(s, day_ts)
        if not (p2 and p1 and p0):
            continue
        if p1 / p2 - 1.0 >= pump:
            pumps.append(p0 < p1)
            moves.append(p0 / p1 - 1.0)
    if len(pumps) < min_pumps:
        return None, len(pumps), None
    moves.sort()
    return sum(pumps) / len(pumps), len(pumps), moves[len(moves) // 2]


def series(root, d_from, d_to, log=print):
    """Доля по дням [d_from, d_to] (строки ГГГГ-ММ-ДД)."""
    mkt = WV.Market(hours=WV.Hours(root))
    syms = universe(root)
    log(f"кросс-секция: имён со сводками {len(syms)}")
    out = {}
    t = calendar.timegm(time.strptime(d_from, "%Y-%m-%d"))
    t_end = calendar.timegm(time.strptime(d_to, "%Y-%m-%d"))
    while t <= t_end:
        share, n, med = reversal_share(mkt, syms, t)
        out[time.strftime("%Y-%m-%d", time.gmtime(t))] = {"share": share, "pumps": n, "med_move": med}
        t += DAY
    return out


def bucket(v):
    if v is None:
        return "не измерен"
    return "тормоз (< 0.5)" if v < THRESH else "≥ 0.5"


def book_days(rows):
    per = {}
    for r in rows:
        d = P.day_of(r["at"])
        x = per.setdefault(d, {"usd": 0.0, "n": 0, "floors": 0})
        x["usd"] += float(r["usd"])
        x["n"] += 1
        x["floors"] += 1 if r.get("exit") in W.TRIGGER_EXITS else 0
    return per


def by_bucket(per_day, ser, scope_days):
    tab = {}
    for d in scope_days:
        x = per_day.get(d)
        if not x:
            continue
        b = tab.setdefault(bucket((ser.get(d) or {}).get("share")), {"days": 0, "usd": 0.0, "n": 0, "floors": 0})
        b["days"] += 1
        b["usd"] += x["usd"]
        b["n"] += x["n"]
        b["floors"] += x["floors"]
    for b in tab.values():
        b["usd"] = round(b["usd"], 2)
        b["usd_per_day"] = round(b["usd"] / b["days"], 2)
        b["floor_share"] = round(b["floors"] / b["n"], 3) if b["n"] else None
    # нуль: метки дней переставлены среди ИЗМЕРЕННЫХ дней
    meas = [d for d in scope_days if d in per_day and (ser.get(d) or {}).get("share") is not None]
    brake = [d for d in meas if (ser[d]["share"] < THRESH)]
    p = None
    if brake and len(meas) > len(brake):
        obs = sum(per_day[d]["usd"] for d in brake)
        rng = random.Random(11)
        le = 0
        for _ in range(PERM):
            pick = rng.sample(meas, len(brake))
            le += sum(per_day[d]["usd"] for d in pick) <= obs
        p = round(le / PERM, 3)
    return tab, p, len(brake), len(meas)


def whatif(recs, bk, ser, ctx, now, mid, fwd_ts):
    """Касса без шортов, вошедших в дни тормоза; нуль — без шортов в случайных
    днях того же числа (из измеренных дней записи)."""
    days_all = sorted({P.day_of(r["at"]) for r in recs if (r.get("side") or "long") == "short"})
    brake = [d for d in days_all if (ser.get(d) or {}).get("share") is not None and ser[d]["share"] < THRESH]
    meas = [d for d in days_all if (ser.get(d) or {}).get("share") is not None]

    def without(days):
        ds = set(days)
        cur = [r for r in recs if not ((r.get("side") or "long") == "short" and P.day_of(r["at"]) in ds)]
        rows = W.plain_rows(cur, bk, DEP, now)
        return {"all": W.stats(rows, bk, DEP, ctx), "first": W.stats(rows, bk, DEP, ctx, until=mid),
                "second": W.stats(rows, bk, DEP, ctx, since=mid),
                "forward": W.stats(rows, bk, DEP, ctx, since=fwd_ts) if fwd_ts else None}
    base = without([])
    rule = without(brake)
    nulls = []
    if brake and len(meas) > len(brake):
        for seed in range(SEEDS):
            pick = random.Random(seed).sample(meas, len(brake))
            z = without(pick)
            nulls.append((z["all"]["usd"], (z["forward"] or {}).get("usd")))
    return {"base": base, "rule": rule, "brake_days": len(brake), "measured_days": len(meas),
            "null": W.null_summary(nulls, rule["all"]["usd"], (rule["forward"] or {}).get("usd"))}


def run(books, root=None, log=print, now=None):
    now = now or time.time()
    R.SIZINGS = (R.SIZING_COMPOUND,)
    ctx = CO.context()
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш коротких: {why}"}
    launch = IR.launches()
    packed = W.h24_packed(cache, BOOKS, launch, now, lambda *a: None)
    ats = [float(r["at"]) for rs in packed.values() for r in rs]
    d_from = time.strftime("%Y-%m-%d", time.gmtime(min(ats)))
    d_to = time.strftime("%Y-%m-%d", time.gmtime(now))
    t0 = time.time()
    ser = series(root or WV.SUMMARY_DIR, d_from, d_to, log=log)
    meas = [d for d, v in ser.items() if v["share"] is not None]
    log(f"датчик: дней {len(ser)}, измерено {len(meas)}, тормоз {sum(1 for d in meas if ser[d]['share'] < THRESH)}, "
        f"{time.time() - t0:.0f} с")
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "pump": PUMP, "min_pumps": MIN_PUMPS,
           "thresh": THRESH, "perm": PERM, "seeds": SEEDS, "dep": DEP, "series": ser, "books": {}}
    for bk in books:
        rows = P.shorts_rows(bk, cache, launch, now, ctx)
        a = sorted(float(r["at"]) for r in rows)
        mid = a[len(a) // 2] if a else 0.0
        since = R.family_since(bk)
        fwd_ts = calendar.timegm(time.strptime(since, "%Y-%m-%d")) if since else None
        per = book_days(rows)
        days = sorted(per)
        scopes = {"all": days, "first": [d for d in days if calendar.timegm(time.strptime(d, "%Y-%m-%d")) < mid],
                  "second": [d for d in days if calendar.timegm(time.strptime(d, "%Y-%m-%d")) >= mid],
                  "forward": [d for d in days if fwd_ts and calendar.timegm(time.strptime(d, "%Y-%m-%d")) >= fwd_ts]}
        reg = {}
        for sc, ds in scopes.items():
            tab, p, nb, nm = by_bucket(per, ser, ds)
            reg[sc] = {"buckets": tab, "p_perm": p, "brake_days": nb, "measured_days": nm}
        res["books"][bk] = {"n": len(rows), "mid": P.day_of(mid) if mid else None, "forward_since": since,
                            "regime": reg, "whatif": whatif(packed[bk], bk, ser, ctx, now, mid, fwd_ts)}
        w = res["books"][bk]["whatif"]
        log(f"{bk}: дней тормоза {w['brake_days']} из {w['measured_days']}; касса {w['base']['all']['usd']} → "
            f"{w['rule']['all']['usd']} (вперёд {(w['base']['forward'] or {}).get('usd')} → {(w['rule']['forward'] or {}).get('usd')})"
            + (f"; нуль медиана {w['null']['usd_med']}, доля ≥ правила {w['null']['share_ge']}" if w["null"] else ""))
    return res


def usd(x):
    return "—" if x is None else f"{x:+.0f} $"


def report(r):
    if r.get("error"):
        return f"# Тормоз по рынку\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    ser = r["series"]
    meas = [d for d, v in ser.items() if v["share"] is not None]
    L = ["# Тормоз книги по рынку: доля отыгравшихся вчерашних пампов", "",
         f"Посчитано {r['computed_at']}. Памп — рост имени за сутки [D−48 ч, D−24 ч] ≥ {100 * r['pump']:.0f} %; "
         f"отыгралось — цена на 00:00 D ниже цены на 00:00 D−1; меньше {r['min_pumps']} пампов — день не измерен. "
         f"Тормоз — доля < {r['thresh']:g}. Дней {len(ser)}, измерено {len(meas)}, тормоз "
         f"{sum(1 for d in meas if ser[d]['share'] < r['thresh'])}. Пороги объявлены до счёта; описание, не правило. "
         "Половина билета кассой не считана (нужен прогон кассы с билетом по дню).", "",
         "## Датчик по дням (последние 21)", "", "| день | пампов | отыгралось | медиана хода пампа за вчера |", "|---|--:|--:|--:|"]
    for d in sorted(ser)[-21:]:
        v = ser[d]
        sh = "—" if v["share"] is None else f"{100 * v['share']:.0f} %"
        mv = "—" if v["med_move"] is None else f"{100 * v['med_move']:+.1f} %"
        L.append(f"| {d} | {v['pumps']} | {sh} | {mv} |")
    for bk, b in r["books"].items():
        L += ["", f"## {R.RULERS.get(bk, {}).get('title', bk)} (`{bk}`) — позиций {b['n']}, середина {b['mid']}, вперёд с {b['forward_since']}", "",
              "### Результат дня по датчику", "", "| окно | датчик | дней | итог $ | $ в день | полов | p перестановки |", "|---|---|--:|--:|--:|--:|--:|"]
        for sc, nm in (("all", "всё"), ("first", "1-я"), ("second", "2-я"), ("forward", "вперёд")):
            g = b["regime"][sc]
            for name in ("тормоз (< 0.5)", "≥ 0.5", "не измерен"):
                t = g["buckets"].get(name)
                if t:
                    fs = "—" if t["floor_share"] is None else f"{100 * t['floor_share']:.0f} %"
                    pp = g["p_perm"] if name.startswith("тормоз") and g["p_perm"] is not None else ""
                    L.append(f"| {nm} | {name} | {t['days']} | {usd(t['usd'])} | {usd(t['usd_per_day'])} | {fs} | {pp} |")
        w = b["whatif"]
        L += ["", f"### Касса без шортов в дни тормоза ({w['brake_days']} из {w['measured_days']} измеренных дней)", "",
              "| вариант | сделок | итог $ | итог % | просадка | 1-я | 2-я | вперёд |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for nm, c in (("как есть", w["base"]), ("без дней тормоза", w["rule"])):
            a = c["all"]
            L.append(f"| {nm} | {a['n']} | {usd(a['usd'])} | {W.pct(a['final'])} | {W.pct(a['max_dd'])} | {usd(c['first']['usd'])} | "
                     f"{usd(c['second']['usd'])} | {usd((c['forward'] or {}).get('usd'))} |")
        L.append(f"| нуль: случайные дни того же числа | | {W.null_text(w['null'])} | | | | | |")
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
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "тормоз по рынку: доля отыгравшихся пампов"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
