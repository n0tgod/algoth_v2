#!/usr/bin/env python3
"""Долив по повторному выбору листа у длинных книг (владелец 03.11:
«давай затестим, если усредняться не просто глубже, а только по повторению
сигнала»).

После замера резервного рунга (спека 14 §16: покупка глубже по ЦЕНЕ ≈ 0)
триггер меняется: не уровень цены, а повторный выбор листом того же имени,
пока позиция открыта. Касса сегодня такие выборы ПРОПУСКАЕТ («одна на имя»,
`rules.ONE_PER_NAME`), и замер 06.10 показал, что повторы точнее первых
выборов по записям (`repeat_entry.py`), а у коротких книг повторный выбор был
единственным триггером долива, улучшавшим доход на просадку
(`short_adds.py`, по часовым отметкам). Здесь — длинные книги, ядро по
барам, общий пол.

**Ячейки (объявлены до прогона).** Единица денег — билет книги `T`; маржа
позиции во всех ячейках с резервом 1.25 T (резерв зарезервирован на входе,
§Р1), плечо — КНИЖНОЕ (забор четырёх плановых рунгов не пересчитывается:
долив идёт той же долей нотионала, что рунг, 0.25 T × плечо, и забор по
абсолютной цене ликвидации не ослабляется, когда долив ниже средней).

* `book` — книга как есть (записи того же ядра, кэш `cache/reserve/recs-book`).
* `idle` — контроль билета в резерве: все позиции на 1.25 T, резерв лежит.
* `rep_any` — ПЕРВЫЙ повторный выбор того же имени между входом и выходом
  книги → долив 0.25 T по рынку открытием бара часа решения, по любой цене.
* `rep_down` — то же, только если цена долива НЕ ВЫШЕ текущей средней (усреднение, не пирамида).
* `rep_deep` — то же, только если цена долива ниже глубочайшего ПЛАНОВОГО рунга (повтор И пролив лестницы).
* `ticket` — контроль: книга с билетом 1.25 T.
* **Нуль** на каждую ячейку `rep_*`: долив в СЛУЧАЙНЫЙ час жизни позиции при том же
  ценовом условии, у случайных позиций, столько же, сколько доливов у ячейки;
  `NULL_SEEDS` зёрен; у каждой позиции заранее считаются `RND_K` случайных часов
  (`rnd_<условие>:<k>`), зерно выбирает позиции и вариант. Триггер обязан
  выбирать момент лучше случайного — иначе он меряет лишь то, что лишняя
  четверть в позиции в среднем дотягивает (урок 05.10).

Пол капитуляции — правило книги (лестница плановых рунгов исчерпана и низ у
ликвидации); долив участвует в ликвидации и поле с минуты входа. Считается
ВСЯ позиция ядром по барам; касса, половины, вперёд — как у книг; события —
позиции с доливом против книги на тех же позициях, добитые, спасённые.
Кэш кусками по именам (`cache/repeat/`), прогон возобновляемый.

    run research/dca_paper/repeat_add.py [--deps 10000] [--limit N] [--no-publish]
"""
import argparse
import calendar
import hashlib
import json
import os
import random
import statistics as st
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import costs as CO                                            # noqa: E402
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import reserve_rung as RR                                     # noqa: E402

OUT = os.path.join(HERE, "out")
CACHE_DIR = os.path.join(HERE, "cache", "repeat")
REPORT = os.path.join(OUT, "DCA-repeat-add.md")
LATEST = os.path.join(OUT, "repeat_add.json")
BOOKS = ["safe", "optimal", "aggr"]
CONDS = ("any", "down", "deep")
ADD_W = 0.25                      # долив долей билета T
CAPITAL = 1.0 + ADD_W             # маржа позиции с резервом, в T
RND_K = 3                         # случайных часов на позицию (варианты нуля)
NULL_SEEDS = 20
CELLS = ["book", "idle"] + [f"rep_{c}" for c in CONDS] + [f"rnd_{c}:{k}" for c in CONDS for k in range(RND_K)]
MAIN_CELLS = ["book", "idle", "rep_any", "rep_down", "rep_deep", "ticket"]
CHUNK = 12
MEM_LIMIT_MB = 2400
HOUR = 3600
CELL_RU = {"book": "книга", "idle": "резерв лежит (1.25 T без долива)", "ticket": "билет ×1.25 (касса)",
           "rep_any": "долив по повтору, любая цена", "rep_down": "долив по повтору не выше средней",
           "rep_deep": "долив по повтору ниже лестницы"}


# ------------------------------------------------------------ геометрия долива

def idle_rec(base):
    """Запись книги на маржe 1.25 T с лежащим резервом: деньги те же, доля меньше."""
    f = 1.0 / CAPITAL
    return dict(base, pnl=float(base["pnl"]) * f, marks=[(h, v * f) for h, v in base.get("marks") or []],
                capital_t=CAPITAL, adds=0)


def bar_at(hold, t):
    """Первый бар с меткой ≥ t (так исполняет долив ядро) → (индекс, бар) или None."""
    for i, b in enumerate(hold):
        if b[0] >= t:
            return i, b
    return None


def avg_before(base, t_bar, entry_px):
    """Средняя цена входа по заполнениям книги ДО бара долива: до долива путь
    позиции тот же, что у книги, и её заполнения — её же."""
    cash = qty = 0.0
    for (t, px, w) in base.get("fills") or []:
        if t < t_bar and px > 0:
            cash += w
            qty += w / px
    return cash / qty if qty > 0 else entry_px


def condition_ok(cond, base, pl, hold, t_add):
    """Ценовое условие ячейки на баре долива. → (True/False, бар долива или None)."""
    hit = bar_at(hold, t_add)
    if hit is None:
        return False, None
    i, b = hit
    if i == 0 or b[0] >= float(base["exit_ts"]):
        return False, None                       # долив в бар входа или после выхода книги — не долив
    op = float(b[1])
    if op <= 0:
        return False, None
    if cond == "any":
        return True, b
    if cond == "down":
        return op <= avg_before(base, float(b[0]), pl["entry"]), b
    if cond == "deep":
        return op < float(pl["rungs"][-1]) if len(pl["rungs"]) >= 2 else op < float(pl["entry"]), b
    raise ValueError(cond)


def simulate_add(g, pl, look, t_add):
    rungs = pl["rungs"]
    w = [ADD_W / CAPITAL] * len(rungs)          # 0.2 от 1.25 T = 0.25 T на рунг, как у книги
    r = L.simulate_dca(pl["hold"], rungs, w, CAPITAL, pl["lev"], look(CAPITAL * pl["lev"]),
                       take_rule=pl["take"], floor_frac=D2.FLOOR_FRAC, track=True, side="long",
                       adds=[(float(t_add), ADD_W / CAPITAL)], adds_max=1)
    rec = RR.record(g, pl, r, pl["lev"], CAPITAL)
    rec["adds"] = int(r.get("adds") or 0)
    rec["add_t"] = float(t_add)
    return rec


def repeats_of(g, same_sym_legs, exit_ts):
    """Повторные выборы того же имени строго между входом и выходом книги, по времени."""
    at = float(g["at"])
    return sorted(float(x["at"]) for x in same_sym_legs if at < float(x["at"]) < exit_ts)


def random_hours(g, exit_ts, k=RND_K):
    """`k` случайных часов жизни позиции [вход + 1 ч, выход книги), зерно — от имени и входа."""
    life_h = int((exit_ts - float(g["at"])) // HOUR)
    if life_h < 2:
        return []
    rng = random.Random(int(hashlib.sha256(f"{g['sym']}|{float(g['at']):.0f}".encode()).hexdigest()[:12], 16))
    return [float(g["at"]) + rng.randint(1, life_h - 1) * HOUR for _ in range(k)]


def leg_cells(g, bars, ts, look, lev_look, rule, param, same_sym_legs, base=None):
    """Все ячейки одной ноги одной линейки → {ячейка: запись}; у `rnd_*` —
    только когда условие в случайный час выполнено. None — ядро не берёт ногу."""
    pl = D6.plan_position(g, bars, ts, look, rule, param, lev_look=lev_look)
    if pl is None:
        return None
    if base is None or base.get("state") != "closed":
        base = D6.one_position(g, bars, ts, look, rule, param, lev_look=lev_look)
        if base is None:
            return None
        base = dict(base, capital_t=1.0)
    out = {"book": base, "idle": idle_rec(base)}
    exit_ts = float(base["exit_ts"])
    reps = repeats_of(g, same_sym_legs, exit_ts)
    for cond in CONDS:
        # долив — на ПЕРВОМ повторе, где держит условие ячейки; один на позицию
        t_add = next((t for t in reps if condition_ok(cond, base, pl, pl["hold"], t)[0]), None)
        rec = simulate_add(g, pl, look, t_add) if t_add is not None else idle_rec(base)
        rec["repeat_t"] = reps[0] if reps else None
        out[f"rep_{cond}"] = rec
    for k, t_rnd in enumerate(random_hours(g, exit_ts)):
        for cond in CONDS:
            ok, _b = condition_ok(cond, base, pl, pl["hold"], t_rnd)
            if ok:
                out[f"rnd_{cond}:{k}"] = simulate_add(g, pl, look, t_rnd)
    return out


# ------------------------------------------------------------ кэш и проход

def cache_path(cell):
    return os.path.join(CACHE_DIR, f"recs-{cell.replace(':', '-')}.jsonl")


def cell_sig(cell):
    return dict(RP.cache_sig(), repeat_cell=cell, add_w=ADD_W, rnd_k=RND_K, v=1)


def read_caches(log=print):
    out = {}
    for c in CELLS:
        cache, why = RP.read_cache(cache_path(c), sig=cell_sig(c))
        if why and why != "кэша нет":
            log(f"кэш ячейки {c} не используется: {why}")
        out[c] = cache
    return out


def write_caches(caches):
    os.makedirs(CACHE_DIR, exist_ok=True)
    for c, cache in caches.items():
        RP.write_cache(cache, path=cache_path(c), sig=cell_sig(c))


def book_base(log=print):
    """Записи книги из кэша замера резервного рунга (то же ядро, закрытые —
    окончательны): ноги с готовой закрытой записью не считаются заново."""
    cache, why = RP.read_cache(RR.cache_path("book"), sig=RR.cell_sig("book"))
    if why:
        log(f"кэш книги замера резерва не используется: {why}")
    return cache


def replay(legs, pairs, caches, src, log=print, chunk=CHUNK, limit=None):
    by_sym = {}
    for g in legs:
        by_sym.setdefault(str(g["sym"]), []).append(g)
    done_cells = ["book", "idle"] + [f"rep_{c}" for c in CONDS]
    need = {}
    for sym, gl in by_sym.items():
        for g in gl:
            at = round(float(g["at"]), 3)
            for pr in pairs:
                k = (tuple(pr), sym, at)
                if not all(k in caches[c] and caches[c][k].get("state") == "closed" for c in done_cells):
                    need.setdefault(sym, []).append(g)
                    break
    syms = sorted(need)
    if limit:
        syms = syms[:limit]
    log(f"повтор: ног {sum(len(v) for v in by_sym.values())}, имён к досчёту {len(syms)} из {len(by_sym)}")
    tiers_all = D2.instruments_tiers()
    base_all = book_base(log)
    n = {"legs": 0, "from_cache": 0, "repeats": 0}
    said = time.time()
    for i0 in range(0, len(syms), chunk):
        part = syms[i0:i0 + chunk]
        for sym in part:
            glist = need[sym]
            a0 = min(g["at"] for g in glist) - D2.BACK_H * HOUR
            b1 = max(g["at"] for g in glist) + D2.HOLD_H * HOUR
            bars = src.bars(sym, a0, b1)
            if not bars:
                continue
            ts = [b[0] for b in bars]
            tiers = tiers_all.get(sym) or []
            look = lambda notl, t=tiers: L.mmr_for_notional(t, notl, flat=D2.FLAT_MMR)     # noqa: E731
            lev_look = lambda notl, t=tiers: L.lev_cap_for_notional(t, notl)              # noqa: E731
            for g in glist:
                at = round(float(g["at"]), 3)
                for pr in pairs:
                    k = (tuple(pr), sym, at)
                    base = base_all.get(k)
                    cells = leg_cells(g, bars, ts, look, lev_look, pr[0], pr[1], by_sym[sym], base=base)
                    if cells is None:
                        continue
                    n["legs"] += 1
                    n["from_cache"] += int(base is not None and base.get("state") == "closed")
                    n["repeats"] += int(cells["rep_any"].get("repeat_t") is not None)
                    for c, rec in cells.items():
                        caches[c][k] = rec
            if time.time() - said > 30:
                log(f"  имён {i0 + part.index(sym) + 1}/{len(syms)}, ног {n['legs']}, с повтором {n['repeats']}")
                said = time.time()
        RR._finish_states(caches, src)
        write_caches(caches)
        log(f"  кусок {i0 // chunk + 1}/{(len(syms) + chunk - 1) // chunk} записан")
    RR._finish_states(caches, src)
    return n


# ------------------------------------------------------------ касса, события, нуль

def events(caches, pr, cell):
    base = caches["book"]
    n = {"n": 0, "t_res": [], "t_book": [], "killed": 0, "saved": 0, "below_avg": 0}
    for k, r in caches[cell].items():
        if k[0] != tuple(pr) or r.get("state") != "closed" or not r.get("adds"):
            continue
        b = base.get(k)
        if b is None:
            continue
        n["n"] += 1
        n["t_res"].append(float(r["pnl"]) * CAPITAL)
        n["t_book"].append(float(b["pnl"]))
        bad_r, bad_b = r.get("exit") in ("пол", "ликвидация"), b.get("exit") in ("пол", "ликвидация")
        n["killed"] += int(bad_r and not bad_b)
        n["saved"] += int(bad_b and not bad_r)
    mean = lambda xs: round(st.mean(xs), 4) if xs else None               # noqa: E731
    return {"n": n["n"], "mean_t_res": mean(n["t_res"]), "mean_t_book": mean(n["t_book"]),
            "sum_t_res": round(sum(n["t_res"]), 3), "sum_t_book": round(sum(n["t_book"]), 3),
            "killed": n["killed"], "saved": n["saved"]}


def null_rows_stats(caches, pr, cond, bk, dep, ctx, now, n_adds, fwd_ts, seeds=NULL_SEEDS, log=print):
    """Нуль: столько же доливов в случайные часы у случайных позиций того же
    условия; касса на каждом зерне → распределение денег."""
    idle = {k: r for k, r in caches["idle"].items() if k[0] == tuple(pr)}
    cand = {kk: [c for c in range(RND_K) if (tuple(pr), kk[1], kk[2]) in caches[f"rnd_{cond}:{c}"]] for kk in idle}
    cand = {kk: v for kk, v in cand.items() if v}
    out = {"seeds": 0, "usd": [], "fwd": [], "candidates": len(cand), "n_adds": n_adds}
    if not cand or not n_adds:
        return out
    keys = sorted(cand)
    for s in range(seeds):
        rng = random.Random(1000 + s)
        pick = set(rng.sample(keys, min(n_adds, len(keys))))
        recs = []
        for kk, r in idle.items():
            if kk in pick:
                variant = rng.choice(cand[kk])
                recs.append(dict(caches[f"rnd_{cond}:{variant}"][kk]))
            else:
                recs.append(dict(r))
        rows = RR.rows_for(recs, bk, now)
        a = RR.stats(rows, bk, dep, ctx)
        f = RR.stats(rows, bk, dep, ctx, since=fwd_ts) if fwd_ts else {}
        out["usd"].append(a["usd"])
        out["fwd"].append(f.get("usd"))
        out["seeds"] += 1
    return out


def null_summary(z, usd, fwd_usd):
    xs = sorted(x for x in z["usd"] if x is not None)
    fs = sorted(x for x in z["fwd"] if x is not None)
    if not xs:
        return None
    q = lambda a, p: a[min(len(a) - 1, int(p * len(a)))]                  # noqa: E731
    return {"seeds": z["seeds"], "candidates": z["candidates"], "n_adds": z["n_adds"],
            "usd_med": q(xs, 0.5), "usd_lo": q(xs, 0.1), "usd_hi": q(xs, 0.9),
            "share_ge": round(sum(1 for x in xs if usd is not None and x >= usd) / len(xs), 3),
            "fwd_med": q(fs, 0.5) if fs else None,
            "fwd_share_ge": (round(sum(1 for x in fs if fwd_usd is not None and x >= fwd_usd) / len(fs), 3) if fs else None)}


def measure(caches, books, deps, log=print, now=None):
    now = now or time.time()
    ctx = CO.context()
    fwd = R.FAMILY_SINCE.get("sit")
    fwd_ts = calendar.timegm(time.strptime(fwd, "%Y-%m-%d")) if fwd else None
    res = {"books": {}, "events": {}, "null": {}, "halves": {}}
    for bk in books:
        pr = tuple(RP.RULERS[bk])
        res["books"][bk], res["events"][bk], res["null"][bk] = {}, {}, {}
        ats = sorted(float(k[2]) for k in caches["book"] if k[0] == pr)
        mid = ats[len(ats) // 2] if ats else None
        res["halves"][bk] = mid
        for cell in MAIN_CELLS:
            src_cell = "book" if cell == "ticket" else cell
            recs = [dict(r) for k, r in caches[src_cell].items() if k[0] == pr]
            if cell == "ticket":
                for r in recs:
                    r["capital_t"] = CAPITAL
            for dep in deps:
                t1 = time.time()
                rows = RR.rows_for(recs, bk, now)
                c = {"all": RR.stats(rows, bk, dep, ctx), "first": RR.stats(rows, bk, dep, ctx, until=mid),
                     "second": RR.stats(rows, bk, dep, ctx, since=mid),
                     "forward": RR.stats(rows, bk, dep, ctx, since=fwd_ts) if fwd_ts else None}
                # строки кассы поля `adds` не несут — доливы считаются по ЗАПИСЯМ взятых позиций
                taken = {(r.get("sym"), round(float(r["at"]), 3)) for r in rows
                         if r.get("ruler") == bk and int(r.get("dep", 0)) == int(dep) and r.get("usd") is not None}
                c["all"]["adds"] = sum(1 for r in recs if r.get("adds") and (r.get("sym"), round(float(r["at"]), 3)) in taken)
                c["secs"] = round(time.time() - t1, 1)
                res["books"][bk].setdefault(cell, {})[str(int(dep))] = c
                a = c["all"]
                log(f"{bk} ${int(dep)} {cell}: n {a['n']} полов {a['floors']} доливов {a['adds']} usd {a['usd']} "
                    f"итог {(a['final'] or 0) * 100:+.2f} % dd {(a['max_dd'] or 0) * 100:.1f} % "
                    f"(1-я {c['first']['usd']}, 2-я {c['second']['usd']}, вперёд {(c['forward'] or {}).get('usd')}); {c['secs']} с")
                if cell.startswith("rep_"):
                    cond = cell.split("_", 1)[1]
                    z = null_rows_stats(caches, pr, cond, bk, dep, ctx, now, a["adds"], fwd_ts, log=log)
                    zs = null_summary(z, a["usd"], (c["forward"] or {}).get("usd"))
                    res["null"][bk].setdefault(cell, {})[str(int(dep))] = zs
                    if zs:
                        log(f"   нуль {zs['seeds']} зёрен (кандидатов {zs['candidates']}): медиана {zs['usd_med']} "
                            f"[{zs['usd_lo']}…{zs['usd_hi']}], доля ≥ ячейки {zs['share_ge']}; вперёд медиана {zs['fwd_med']} "
                            f"доля ≥ {zs['fwd_share_ge']}")
            if cell.startswith("rep_"):
                res["events"][bk][cell] = events(caches, pr, cell)
    return res


# ------------------------------------------------------------ отчёт и прогон

def pct(x):
    return "—" if x is None else f"{100 * x:+.2f} %"


def report(r):
    L_ = ["# Долив по повторному выбору листа у длинных книг (владелец 03.11)", "",
          f"Посчитано {r['computed_at']}; ног {r['replay']['legs']} (книга из кэша замера резерва {r['replay']['from_cache']}), "
          f"с повторным выбором до выхода {r['replay']['repeats']}. Долив 0.25 T по рынку открытием бара часа повтора, маржа 1.25 T, "
          f"плечо книги; условия: любая цена / не выше средней / ниже плановой лестницы. Нуль — {NULL_SEEDS} зёрен: столько же доливов "
          f"в случайный час у случайных позиций того же условия. Деньги нетто; половины по времени входа; вперёд с {R.FAMILY_SINCE.get('sit')}.", "",
          "**Как читать.** `rep − idle` — цена самого долива при той же марже; `ticket − idle` — что даёт та же четверть в базовой лестнице; "
          "нуль говорит, выбирает ли повтор момент лучше случайного.", ""]
    for bk, cells in r["books"].items():
        L_ += [f"## {R.MODE_EN.get(bk, bk)} · `{bk}`", ""]
        for dep in r["deps"]:
            d = str(int(dep))
            L_ += [f"### депозит ${d}", "",
                   "| ячейка | позиций | полов | доливов | итог $ | итог % | просадка | зелёных | без 3 дней | 1-я | 2-я | вперёд | нуль: медиана [10–90 %] · доля ≥ ячейки · вперёд |",
                   "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
            for cell, by_dep in cells.items():
                c = by_dep.get(d)
                if not c:
                    continue
                a, f1, f2, fw = c["all"], c["first"], c["second"], c.get("forward") or {}
                z = ((r.get("null") or {}).get(bk) or {}).get(cell, {}).get(d)
                zt = (f"{z['usd_med']} [{z['usd_lo']}…{z['usd_hi']}] · {z['share_ge']} · {z['fwd_med']} ({z['fwd_share_ge']})"
                      if z else "—")
                L_.append(f"| {CELL_RU.get(cell, cell)} | {a['n']} | {a['floors']} | {a['adds']} | {a['usd']} | {pct(a['final'])} | "
                          f"{pct(a['max_dd'])} | {pct(a['win'])} | {a['usd_wo_top3d']} | {f1['usd']} | {f2['usd']} | {fw.get('usd')} | {zt} |")
            L_.append("")
        ev = r["events"].get(bk) or {}
        if ev:
            L_ += ["**События (долив состоялся), закрытые позиции всех ног линейки:**", "",
                   "| ячейка | позиций | на T: с доливом | на T: книга | Σ T: с доливом / книга | добито доливом | спасено |",
                   "|---|--:|--:|--:|--:|--:|--:|"]
            for cell, e in ev.items():
                L_.append(f"| {CELL_RU.get(cell, cell)} | {e['n']} | {pct(e['mean_t_res'])} | {pct(e['mean_t_book'])} | "
                          f"{e['sum_t_res']} / {e['sum_t_book']} | {e['killed']} | {e['saved']} |")
            L_.append("")
    return "\n".join(L_) + "\n"


def run(books, deps, log=print, limit=None, now=None, src=None, legs=None):
    t0 = time.time()
    now = now or time.time()
    R.SIZINGS = (R.SIZING_COMPOUND,)
    import tail as TL                                          # noqa: E402
    src = src or TL.TailBars(log=log, cache=TL.BARS_CACHE)
    legs = legs if legs is not None else D6.gated_legs(log=log, side="long")
    legs = [g for g in legs if (g.get("side") or "long") == "long"]
    pairs = RR.pairs_of(books)
    caches = read_caches(log)
    n = replay(legs, pairs, caches, src, log=log, limit=limit)
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "deps": deps, "cells": MAIN_CELLS,
           "replay": n, "add_w": ADD_W}
    res.update(measure(caches, books, deps, log=log, now=now))
    res["secs"] = round(time.time() - t0, 1)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default=",".join(BOOKS))
    ap.add_argument("--deps", default="10000")
    ap.add_argument("--limit", type=int, default=None, help="имён к досчёту за прогон (смоук)")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                      # noqa: E402
    log = AB.guarded(print, limit=MEM_LIMIT_MB)
    books = [b for b in a.books.split(",") if b]
    deps = [float(x) for x in a.deps.split(",") if x]
    r = run(books, deps, log=log, limit=a.limit)
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "долив по повтору: замер"], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
