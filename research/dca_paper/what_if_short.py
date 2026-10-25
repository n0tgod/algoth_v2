#!/usr/bin/env python3
"""Что было бы с короткими и общими книгами при двух правилах (владелец 25.10:
«если поменять эти правила, как поменяется общая статистика») — описание,
не отбор: правила заданы владельцем, а не подобраны по результату.

Правила:
* **пауза имени после пола** — книга не открывает шорт в имени, если её
  СОБСТВЕННАЯ предыдущая позиция в нём закрылась полом или ликвидацией
  меньше `PAUSE_H` часов назад (правило механики 193cbb87, `name_pause`:
  записи снимаются по одной, касса пересчитывается — снятая позиция
  освобождает деньги и имя, и состав дальше другой);
* **потолок плеча** — плечо короткой позиции не выше `LEV_CAP`; позиции с
  плечом выше считаются ЗАНОВО тем же ядром (`run_short.replay_cells`,
  политика ячейки `lev_cap`), не масштабируются — пол и ликвидация у
  меньшего плеча стоят дальше, и исход другой.

Варианты: книга как есть, пауза, потолок, оба. Книги: короткие `h24`
(`safe_h`, `optimal_h`, `aggr_h`) и общие счета режимов; депозит $10 000
(и другие по флагу); окно целиком, две половины по времени входа и запись
вперёд семейства (`rules.FAMILY_SINCE`). Деньги — нетто тем же путём, что
у книг (`build_rows` → `costs.apply_to_rows` → `_stats`).

    run research/dca_paper/what_if_short.py [--books optimal_h,aggr_h] [--deps 10000] [--no-pair]
"""
import argparse
import calendar
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "mech_193cbb87"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_pair as RPair                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import costs as CO                                            # noqa: E402
import name_pause as NP                                       # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "WHATIF-short.md")
LATEST = os.path.join(OUT, "whatif_short.json")
PAUSE_H = 24.0
LEV_CAP = 10.0
TRIGGER_EXITS = NP.TRIGGER_EXITS          # «пол», «ликвидация» — как у механики
MAX_STEPS = 400
MEM_LIMIT_MB = 3000
H24_BOOKS = ["safe_h", "optimal_h", "aggr_h"]
PAIR_BOOKS = ["pair_safe", "pair_optimal", "pair_aggr"]
VARIANTS = ("book", "pause", "cap", "both")
VARIANT_RU = {"book": "как есть", "pause": f"пауза {PAUSE_H:g} ч после пола", "cap": f"плечо ≤ {LEV_CAP:g}×",
              "both": "пауза и потолок"}


def capped_cache(cache, log):
    """Кэш коротких, где позиции с плечом > LEV_CAP пересчитаны ядром с потолком."""
    legs = S.legs(log=lambda *a: None)
    by_leg = {(g["sym"], round(float(g["at"]), 3)): g for g in legs}
    need = {}
    for (rk, sym, at), r in cache.items():
        if float(r.get("lev") or 0) > LEV_CAP and (sym, at) in by_leg:
            need[(sym, at)] = by_leg[(sym, at)]
    log(f"потолок {LEV_CAP:g}×: позиций с плечом выше — {sum(1 for r in cache.values() if float(r.get('lev') or 0) > LEV_CAP)}, "
        f"решений к пересчёту {len(need)}")
    if not need:
        return dict(cache), 0
    t0 = time.time()
    out, _tail = S.replay_cells(list(need.values()), [S.CELL], log=log, rulers=sorted(set(cache_rulers(cache))),
                                adds_of=lambda g, key: {"adds": [], "lev_cap": LEV_CAP})
    fresh = out.get(S.CELL[0]) or {}
    new = dict(cache)
    n = 0
    for k, r in fresh.items():
        if k in new and float(new[k].get("lev") or 0) > LEV_CAP:
            new[k] = dict(r, state=new[k].get("state", r.get("state")))
            n += 1
    log(f"пересчитано с потолком: {n} записей за {time.time() - t0:.0f} с")
    return new, n


def cache_rulers(cache):
    return {rk for (rk, _s, _a) in cache}


def h24_packed(cache, books, launch, now, log):
    """Записи коротких книг после возраста и охраны — как в прогоне."""
    packed = {}
    for bk in books:
        rk = S.BOOKS[bk]
        packed[bk] = [r for (k, _s, _a), r in cache.items() if k == rk]
    out, _ages, _guards = NP.prepare(packed, launch, books=books, now=now, log=log)
    return out


def pair_packed(short_cache, books, launch, now, ctx, log):
    """Записи общих счетов после гейта, возраста и охраны — как в `run_pair.run`."""
    longs, why_l = RPair.long_recs(log=lambda *a: None)
    shorts, why_s = RPair.short_recs(short_cache, log=lambda *a: None)
    if why_l or why_s:
        raise RuntimeError(why_l or why_s)
    packed = RPair.pack(longs, shorts, books)
    out = {}
    for pk in books:
        lk, sk = R.parts_of(pk)
        mine = [r for r in packed[pk] if (r.get("book") or pk) == sk]
        kept, _why = RPair.gate_shorts(mine, pk, ctx, log=lambda *a: None)
        kept, _a = RP.age_shorts(kept, pk, launch=launch, log=lambda *a: None, now=now)
        kept, _g = RP.guard_shorts(kept, pk, log=lambda *a: None, now=now)
        longs_part = [r for r in packed[pk] if (r.get("book") or pk) == lk]
        out[pk] = longs_part + kept
    return out


def pause_rows(recs, bk, dep, now, log):
    """Касса книги с паузой: записи снимаются по одной (как `name_pause.sister`),
    триггер и запрет — только у КОРОТКИХ позиций (у общего счёта длинные не трогаются)."""
    cur = list(recs)
    steps = 0
    with NP.only(dep):
        while True:
            rows, _c, _o, _l = RP.build_rows({bk: cur}, now=now, keys=[bk], log=lambda *a: None)
            taken = [t for t in NP.taken_of(rows, bk, dep) if (t.get("side") or "long") == "short"]
            shorts = [r for r in cur if (r.get("side") or "long") == "short"]
            blocked = NP.blocked_of(shorts, taken, PAUSE_H, exits=TRIGGER_EXITS, mode="prev")
            if not blocked:
                return rows, steps
            first = blocked[0]
            cur = [r for r in cur if RP._key(r) != first["key"]]
            steps += 1
            if steps > MAX_STEPS:
                raise RuntimeError(f"{bk}: пауза сняла больше {MAX_STEPS} записей — не пауза, а другая книга")


def plain_rows(recs, bk, dep, now):
    with NP.only(dep):
        rows, _c, _o, _l = RP.build_rows({bk: recs}, now=now, keys=[bk], log=lambda *a: None)
    return rows


def stats(rows, bk, dep, ctx, since=None, until=None):
    rows, _cs = CO.apply_to_rows(rows, ctx)
    sub = [r for r in rows if r.get("ruler") == bk and int(r.get("dep", 0)) == int(dep)
           and not r.get("sizing") and r.get("usd") is not None
           and (since is None or float(r.get("at") or 0) >= since)
           and (until is None or float(r.get("at") or 0) < until)]
    st = RP._stats(sub, dep) or {}
    return {"n": st.get("n"), "usd": None if st.get("usd") is None else round(st["usd"], 2),
            "final": st.get("final"), "max_dd": st.get("max_dd"), "win": st.get("win"),
            "floors": sum(1 for r in sub if r.get("exit") in TRIGGER_EXITS),
            "usd_wo_top3d": st.get("usd_wo_top3d")}


def run(books_h24, books_pair, deps, log=print, now=None, do_pair=True):
    t0 = time.time()
    now = now or time.time()
    R.SIZINGS = (R.SIZING_COMPOUND,)
    ctx = CO.context()
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш коротких: {why}"}
    launch = IR.launches()
    capped, n_cap = capped_cache(cache, log)
    sources = {"book": cache, "pause": cache, "cap": capped, "both": capped}
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "pause_h": PAUSE_H,
           "lev_cap": LEV_CAP, "recapped": n_cap, "deps": deps, "books": {}, "halves": {}}
    plan = [(bk, "h24") for bk in books_h24] + ([(pk, "pair") for pk in books_pair] if do_pair else [])
    packed_cache = {}
    for bk, fam in plan:
        res["books"][bk] = {}
        for v in VARIANTS:
            src = sources[v]
            pk = (fam, id(src))
            if pk not in packed_cache:
                packed_cache[pk] = (h24_packed(src, books_h24, launch, now, lambda *a: None) if fam == "h24"
                                    else pair_packed(src, books_pair, launch, now, ctx, log))
            recs = packed_cache[pk][bk]
            ats = sorted(float(r["at"]) for r in recs if (r.get("side") or "long") == "short")
            mid = ats[len(ats) // 2] if ats else None
            res["halves"][bk] = mid
            since_fwd = R.family_since(bk)
            fwd_ts = calendar.timegm(time.strptime(since_fwd, "%Y-%m-%d")) if since_fwd else None
            for dep in deps:
                t1 = time.time()
                if v in ("pause", "both"):
                    rows, steps = pause_rows(recs, bk, dep, now, log)
                else:
                    rows, steps = plain_rows(recs, bk, dep, now), 0
                cell = {"all": stats(rows, bk, dep, ctx), "first": stats(rows, bk, dep, ctx, until=mid),
                        "second": stats(rows, bk, dep, ctx, since=mid),
                        "forward": stats(rows, bk, dep, ctx, since=fwd_ts) if fwd_ts else None,
                        "steps": steps, "secs": round(time.time() - t1, 1)}
                res["books"][bk].setdefault(v, {})[str(int(dep))] = cell
                a = cell["all"]
                log(f"{bk} ${int(dep)} {v}: n {a['n']} полов {a['floors']} usd {a['usd']} итог "
                    f"{(a['final'] or 0) * 100:+.2f} % dd {(a['max_dd'] or 0) * 100:.1f} % "
                    f"(1-я {cell['first']['usd']}, 2-я {cell['second']['usd']}, вперёд "
                    f"{(cell['forward'] or {}).get('usd')}); снято {steps}; {cell['secs']} с")
    res["secs"] = round(time.time() - t0, 1)
    return res


def pct(x):
    return "—" if x is None else f"{100 * x:+.2f} %"


def usd(x):
    return "—" if x is None else f"{x:+.0f} $"


def report(r):
    if r.get("error"):
        return f"# Что если: короткие книги\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    L = ["# Что если: пауза имени после пола и потолок плеча у коротких книг", "",
         f"Посчитано {r['computed_at']}; правила заданы владельцем 25.10 до счёта: пауза {r['pause_h']:g} ч после пола "
         f"или ликвидации в том же имени (у книги — её собственная позиция; записи снимаются по одной, касса "
         f"пересчитывается), потолок плеча {r['lev_cap']:g}× (позиции с плечом выше пересчитаны ядром: {r['recapped']}). "
         f"Деньги нетто; «вперёд» — с дня записи семейства; половины — по времени входа. За {r['secs']} с.", "",
         "Это описание: что дали бы правила на той же записи. Правило, снимающее сделки, сравнивать надо и со "
         "случайным снятием того же числа (здесь не считано) — цифры ниже говорят, где стоит минус, а не доказывают эдж.", ""]
    for bk, by in r["books"].items():
        L += [f"## {R.RULERS.get(bk, {}).get('title', bk)} (`{bk}`)", "",
              "| депозит | вариант | сделок | полов | итог $ | итог % | просадка | без 3 лучших дней | 1-я половина | 2-я половина | вперёд | снято |",
              "|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for v in VARIANTS:
            for dep, c in (by.get(v) or {}).items():
                a = c["all"]
                L.append(f"| ${dep} | {VARIANT_RU[v]} | {a['n']} | {a['floors']} | {usd(a['usd'])} | {pct(a['final'])} | "
                         f"{pct(a['max_dd'])} | {usd(a['usd_wo_top3d'])} | {usd(c['first']['usd'])} | {usd(c['second']['usd'])} | "
                         f"{usd((c['forward'] or {}).get('usd'))} | {c['steps']} |")
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default=",".join(H24_BOOKS))
    ap.add_argument("--pair-books", default=",".join(PAIR_BOOKS))
    ap.add_argument("--deps", default="10000")
    ap.add_argument("--no-pair", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                      # noqa: E402
    log = AB.guarded(print, limit=MEM_LIMIT_MB)
    books = [b for b in a.books.split(",") if b]
    pairs = [b for b in a.pair_books.split(",") if b]
    deps = [float(x) for x in a.deps.split(",") if x]
    r = run(books, pairs, deps, log=log, do_pair=not a.no_pair)
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "что если: пауза и потолок плеча у коротких"],
                       cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
