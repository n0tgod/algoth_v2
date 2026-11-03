#!/usr/bin/env python3
"""Резервный рунг ниже плановой лестницы у длинных книг (спека 14 §Р1).

Владелец 02.11, по позиции NIL в Sigma (четыре рунга за 2.5 часа внутри
6.5 % от входа, цена ушла втрое глубже, до пола и ликвидации ещё 50 %):
«давай сделаем замер, и в идеале такие позиции усреднять глубже». Спека
§Р1 так и писана: «каждый плановый долив оставляет неиспользованным
капитал минимум на `RESERVE_RUNGS` рунгов ниже — деньги на дальнейший
пролив зарезервированы до входа, а не ищутся в просадке». В бумажные
книги резерв не попал: лестница везде четыре рунга (`run_d2.N_RUNGS`).

**Что измеряется.** Бывает ли случай и что он стоит: по журналу книг
версии 7 на $10k позиций полной глубины (4 рунга) у Sigma 56 из 1613
(полов 0, ниже глубочайшего рунга более чем на 5 % вышли 2 %), у Depth
76 из 1632 (полов 14, ликвидаций 5, глубже 5 % — 24 %), у Gated 101 из 657
(полов 24, ликвидаций 8, глубже 5 % — 25 %). Случай редкий, и выборка на
вердикт у Sigma заведомо мала; это сказано ДО прогона, а числа ниже лишь
покажут цену, а не докажут правило.

**Ячейки (объявлены до прогона, не меняются после).** Единица денег — билет
книги `T`. Резерв применяется ТОЛЬКО к позициям, чья плановая лестница
полная (`len(rungs_full) == N_RUNGS`): у усечённых лестниц резервный
рунг менял бы забор (одиночный вход 1× стал бы лестницей с плечом), и
вопрос «усреднять глубже» подменился бы вопросом о плече; их записи во
всех ячейках — записи книги.

* `book` — книга как есть: 4 рунга по 0.25 T, забор на плановой лестнице;
  считается тем же ядром и сверяется с кэшем книги бит в бит.
* `res:<глубина>` — пятый, резервный рунг на 0.25 T ниже глубочайшего
  планового; маржа позиции 1.25 T зарезервирована на входе (§Р1); забор §5
  считается на ПОЛНОЙ пятирунговой лестнице (веса 0.2 от 1.25 T) — плечо
  всех рунгов от него. Глубина резерва:
  `s1`/`s2`/`s3` — 1/2/3 суточных σ имени (σ окна входа, `run_d5.sigma_day`)
  ниже глубочайшего планового рунга; `x2` — удвоенная глубина лестницы,
  `вход · (1 − 2·d_max)` (там, где у правила `depth` сегодня стоит
  ликвидация).
* `fence:<глубина>` — контроль плеча: тот же забор пятирунговой лестницы и та
  же маржа 1.25 T, но резервный рунг НЕ покупается (0.25 T лежит). Разность
  `res − fence` и есть цена самой покупки глубже; разность `fence − ticket`
  — цена пониженного плеча.
* `ticket` — контроль билета: записи книги с билетом 1.25 T (только касса).

Пол капитуляции — правило книги (`FLOOR_FRAC`): лестница исчерпана И низ
бара у ликвидации; с резервом «исчерпана» означает заполненный резерв.
Срок, тейк, хвост ленты — как у книги. Считается ВСЯ позиция с общим полом
ядром по барам (урок 05.10: долив с ограниченным убытком и неограниченной
прибылью делает победителем любой триггер — по отметкам судить нельзя).

**Меры.** Касса книги на депозите (умолчание $10k, другие флагом):
результат нетто издержек, итог, просадка, доля зелёных, полов, без трёх
лучших дней; половины по времени входа; запись вперёд семейства (с
`rules.FAMILY_SINCE`). Отдельно — события: позиции, где резерв заполнился,
их результат на T против книги на тех же позициях, добитые резервом раньше
своего выхода. Пересчёт идёт кусками по именам с кэшем на диске
(`cache/reserve/`): снятый прогон продолжает с места.

    run research/dca_paper/reserve_rung.py [--deps 10000] [--limit N] [--no-publish]
"""
import argparse
import calendar
import json
import os
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
import run_d5 as D5                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402

OUT = os.path.join(HERE, "out")
CACHE_DIR = os.path.join(HERE, "cache", "reserve")
REPORT = os.path.join(OUT, "DCA-reserve-rung.md")
LATEST = os.path.join(OUT, "reserve_rung.json")
BOOKS = ["safe", "optimal", "aggr"]
DEPTHS = {"s1": ("sigma", 1.0), "s2": ("sigma", 2.0), "s3": ("sigma", 3.0), "x2": ("ladder", 2.0)}
RESERVE_W = 0.25                 # резерв долей билета книги T
CAPITAL_RES = 1.0 + RESERVE_W    # маржа позиции с резервом, в T
CELLS = ["book"] + [f"{v}:{d}" for d in DEPTHS for v in ("res", "fence")]
CHUNK = 12                       # имён на кусок: кэш пишется после каждого
MEM_LIMIT_MB = 2400
HOUR = 3600
CELL_RU = {"book": "книга", "ticket": "билет ×1.25 (касса)"}
for _d, (_k, _p) in DEPTHS.items():
    _how = f"{_p:g}σ ниже глубочайшего рунга" if _k == "sigma" else "на удвоенной глубине лестницы"
    CELL_RU[f"res:{_d}"] = f"резерв {_how}"
    CELL_RU[f"fence:{_d}"] = f"только забор ({_how}, без покупки)"


# ------------------------------------------------------------ геометрия ячейки

def reserve_px(pl, depth):
    """Цена резервного рунга; None — меры нет (σ) или рунг ушёл в ноль."""
    kind, p = DEPTHS[depth]
    deepest = float(pl["rungs_full"][-1])
    entry = float(pl["entry"])
    if kind == "sigma":
        sd = D5.sigma_day(pl.get("sigma_bp"))
        if sd is None:
            return None
        px = deepest * (1.0 - p * sd)
    else:
        d_max = (entry - deepest) / entry
        px = entry * (1.0 - p * d_max)
    return px if 0 < px < deepest else None


def cell_geometry(pl, depth, rule, param, look, lev_look):
    """Лестница с резервом и забор на ней. None — ячейка не применима
    (нет σ, рунг в нуле, забор отказал пятирунговой лестнице)."""
    px = reserve_px(pl, depth)
    if px is None:
        return None
    rungs5 = [float(x) for x in pl["rungs_full"]] + [float(px)]
    w5 = [1.0 / len(rungs5)] * len(rungs5)              # 0.2 от 1.25 T = 0.25 T на рунг
    lev, rungs, binder = D5.fence_leverage(rule, param, pl["entry"], rungs5, look, pl.get("sigma_bp"),
                                           weights=w5, side="long", lev_look=lev_look)
    if len(rungs) < 2:
        return None
    return {"rungs5": rungs5, "w5": w5, "lev": float(lev), "binder": binder, "reserve_px": float(px)}


def record(g, pl, r, lev, capital):
    """Запись позиции в формате `run_d6.one_position` (та же раздача кассы
    читает её), плюс маржа в билетах и цена резерва."""
    hold = pl["hold"]
    marks, prev = [], 0.0
    for (hr, _cash, pnl) in r["track"]:
        marks.append((hr, pnl - prev))
        prev = pnl
    return {"at": float(g["at"]), "exit_ts": float(r["exit_ts"]), "side": "long",
            "pnl": float(r["pnl_frac"]), "lev": float(lev), "fwd": abs(float(g["fwd"])), "sym": g["sym"],
            "fav_bp": float(g["fav"]), "exit": r["exit"], "marks": marks,
            "end_ts": float(hold[-1][0]), "sched_end": float(g["at"]) + pl["hold_h"] * HOUR,
            "entry_px": float(r.get("entry_px") or pl["entry"]), "exit_px": float(r["exit_px"]),
            "avg": float(r["avg"]), "depth": int(r["depth"]),
            "fills": [[float(a), float(b), float(c)] for (a, b, c) in (r.get("fills") or [])],
            "capital_t": float(capital)}


def leg_cells(g, bars, ts, look, lev_look, rule, param, cells=CELLS):
    """Все ячейки одной ноги одной линейки → {ячейка: запись} или None.
    `why` в записи `book` — почему резерв не применён (усечённая лестница,
    нет σ, забор отказал): печатается счётом."""
    pl = D6.plan_position(g, bars, ts, look, rule, param, lev_look=lev_look)
    if pl is None:
        return None
    hold = pl["hold"]
    out = {}
    base = D6.one_position(g, bars, ts, look, rule, param, lev_look=lev_look)
    if base is None:
        return None
    base = dict(base, capital_t=1.0)
    out["book"] = base
    full = len(pl["rungs_full"]) >= D2.N_RUNGS
    for c in cells:
        if c == "book":
            continue
        kind, depth = c.split(":")
        if not full:
            out[c] = dict(base, why="усечённая лестница")
            continue
        geo = cell_geometry(pl, depth, rule, param, look, lev_look)
        if geo is None:
            out[c] = dict(base, why="нет σ или забор отказал")
            continue
        if kind == "res":
            rungs, w = geo["rungs5"], geo["w5"]
        else:
            rungs, w = geo["rungs5"][:-1], geo["w5"][:-1]        # резерв лежит: 0.25 T без покупки
        r = L.simulate_dca(hold, rungs, w, CAPITAL_RES, geo["lev"], look(CAPITAL_RES * geo["lev"]),
                           take_rule=pl["take"], floor_frac=D2.FLOOR_FRAC, track=True, side="long")
        rec = record(g, pl, r, geo["lev"], CAPITAL_RES)
        rec["reserve_px"] = geo["reserve_px"]
        rec["binder"] = geo["binder"]
        # плечо КНИГИ едет в запись: гейт плеча Gated судит решение входа по
        # геометрии книги, иначе пониженное забором пяти рунгов плечо меняло
        # бы состав книги, и вопрос «усреднять глубже» подменился бы составом
        rec["lev_book"] = float(base["lev"])
        out[c] = rec
    return out


# ------------------------------------------------------------ кэш и проход

def cache_path(cell):
    return os.path.join(CACHE_DIR, f"recs-{cell.replace(':', '-')}.jsonl")


def cell_sig(cell):
    return dict(RP.cache_sig(), reserve_cell=cell, reserve_w=RESERVE_W, depths=DEPTHS.get(cell.split(":")[-1]), v=2)


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


def pairs_of(books):
    out = []
    for k in books:
        pr = RP.RULERS[k]
        if pr not in out:
            out.append(pr)
    return out


def replay(legs, pairs, caches, src, log=print, chunk=CHUNK, limit=None, data_end=None):
    """Досчёт всех ячеек по именам, кэш на диск после каждого куска.
    Пересчитываются решения, которых нет или которые ещё открыты в ЛЮБОЙ
    ячейке. Возвращает счётчики."""
    by_leg = {}
    for g in legs:
        by_leg[(str(g["sym"]), round(float(g["at"]), 3))] = g
    need = {}
    for (sym, at), g in by_leg.items():
        for pr in pairs:
            done = all(((tuple(pr), sym, at) in caches[c] and caches[c][(tuple(pr), sym, at)].get("state") == "closed")
                       for c in CELLS)
            if not done:
                need.setdefault(sym, []).append(g)
                break
    syms = sorted(need)
    if limit:
        syms = syms[:limit]
    log(f"резерв: ног {len(by_leg)}, имён к досчёту {len(syms)} из {len({s for s, _ in by_leg})}")
    tiers_all = D2.instruments_tiers()
    n = {"legs": 0, "mismatch": 0, "checked": 0, "truncated": 0, "no_geo": 0, "events": 0,
         "mismatch_lev": 0, "mismatch_exit": 0, "mismatch_pnl": 0}
    said = time.time()
    book_cache, _why = RP.read_cache()
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
                key_at = round(float(g["at"]), 3)
                for pr in pairs:
                    cells = leg_cells(g, bars, ts, look, lev_look, pr[0], pr[1])
                    if cells is None:
                        continue
                    n["legs"] += 1
                    k = (tuple(pr), str(g["sym"]), key_at)
                    # сверка с кэшем книги: закрытая запись обязана совпасть
                    old = book_cache.get(k)
                    if old is not None and old.get("state") == "closed":
                        n["checked"] += 1
                        b = cells["book"]
                        d_lev = abs(float(old["lev"]) - b["lev"]) > 1e-9
                        d_exit = old.get("exit") != b["exit"]
                        d_pnl = abs(float(old["pnl"]) - b["pnl"]) > 1e-9
                        if d_lev or d_exit or d_pnl:
                            # расхождение с кэшем книги — диагностика, не вердикт: тиры площадки
                            # читаются по текущему состоянию (плечо), хвост ленты дописан позже (исход)
                            n["mismatch"] += 1
                            n["mismatch_lev"] += int(d_lev)
                            n["mismatch_exit"] += int(d_exit)
                            n["mismatch_pnl"] += int(d_pnl and not d_lev)
                    c1 = cells[f"res:{next(iter(DEPTHS))}"]
                    if c1.get("why") == "усечённая лестница":
                        n["truncated"] += 1
                    elif c1.get("why"):
                        n["no_geo"] += 1
                    for c, rec in cells.items():
                        caches[c][k] = rec
            if time.time() - said > 30:
                log(f"  имён {i0 + part.index(sym) + 1}/{len(syms)}, ног {n['legs']}, расхождений с книгой {n['mismatch']}")
                said = time.time()
        _finish_states(caches, src, data_end)
        write_caches(caches)
        log(f"  кусок {i0 // chunk + 1}/{(len(syms) + chunk - 1) // chunk} записан")
    _finish_states(caches, src, data_end)
    return n


def _finish_states(caches, src, data_end=None):
    end = data_end or D6.record_end_of(src)
    for cache in caches.values():
        for r in cache.values():
            if r.get("end_ts"):
                end = max(end, float(r["end_ts"]))
    for cache in caches.values():
        for r in cache.values():
            r["state"] = D6.position_state(r, end)


# ------------------------------------------------------------ касса и меры

def stats(rows, bk, dep, ctx, since=None, until=None):
    rows, _cs = CO.apply_to_rows(rows, ctx)
    sub = [r for r in rows if r.get("ruler") == bk and int(r.get("dep", 0)) == int(dep)
           and not r.get("sizing") and r.get("usd") is not None
           and (since is None or float(r.get("at") or 0) >= since)
           and (until is None or float(r.get("at") or 0) < until)]
    s = RP._stats(sub, dep) or {}
    return {"n": s.get("n"), "usd": None if s.get("usd") is None else round(s["usd"], 2),
            "final": s.get("final"), "max_dd": s.get("max_dd"), "win": s.get("win"),
            "floors": sum(1 for r in sub if r.get("exit") in ("пол", "ликвидация")),
            "depth5": sum(1 for r in sub if int(r.get("depth") or 0) >= 5),
            "usd_wo_top3d": s.get("usd_wo_top3d")}


def events(caches, pr, cell):
    """Позиции, где резерв заполнился: результат на T против книги (те же
    позиции), добитые резервом раньше своего выхода."""
    base = caches["book"]
    out = {"n": 0, "pnl_t_res": [], "pnl_t_book": [], "killed": 0, "saved": 0, "fence_lev_ratio": []}
    for k, r in caches[cell].items():
        if k[0] != tuple(pr) or r.get("state") != "closed":
            continue
        b = base.get(k)
        if b is None or b.get("why"):
            continue
        if float(r.get("lev") or 0) > 0 and float(b.get("lev") or 0) > 0 and not r.get("why"):
            out["fence_lev_ratio"].append(float(r["lev"]) / float(b["lev"]))
        if int(r.get("depth") or 0) < 5:
            continue
        out["n"] += 1
        out["pnl_t_res"].append(float(r["pnl"]) * float(r.get("capital_t") or 1.0))
        out["pnl_t_book"].append(float(b["pnl"]) * 1.0)
        if r.get("exit") in ("пол", "ликвидация") and b.get("exit") not in ("пол", "ликвидация"):
            out["killed"] += 1
        if b.get("exit") in ("пол", "ликвидация") and r.get("exit") not in ("пол", "ликвидация"):
            out["saved"] += 1
    mean = lambda xs: round(st.mean(xs), 4) if xs else None                     # noqa: E731
    return {"n": out["n"], "mean_t_res": mean(out["pnl_t_res"]), "mean_t_book": mean(out["pnl_t_book"]),
            "sum_t_res": round(sum(out["pnl_t_res"]), 3), "sum_t_book": round(sum(out["pnl_t_book"]), 3),
            "killed": out["killed"], "saved": out["saved"],
            "lev_ratio_med": round(st.median(out["fence_lev_ratio"]), 3) if out["fence_lev_ratio"] else None,
            "positions_with_fence": len(out["fence_lev_ratio"])}


def measure(caches, books, deps, log=print, now=None):
    now = now or time.time()
    ctx = CO.context()
    fwd = R.FAMILY_SINCE.get("sit")
    fwd_ts = calendar.timegm(time.strptime(fwd, "%Y-%m-%d")) if fwd else None
    res = {"books": {}, "events": {}, "halves": {}}
    for bk in books:
        pr = tuple(RP.RULERS[bk])
        res["books"][bk] = {}
        res["events"][bk] = {}
        ats = sorted(float(k[2]) for k in caches["book"] if k[0] == pr)
        mid = ats[len(ats) // 2] if ats else None
        res["halves"][bk] = mid
        for cell in CELLS + ["ticket"]:
            src_cell = "book" if cell == "ticket" else cell
            recs = [dict(r) for k, r in caches[src_cell].items() if k[0] == pr]
            if cell == "ticket":
                for r in recs:
                    r["capital_t"] = CAPITAL_RES          # записи книги, билет 1.25 T
            for dep in deps:
                t1 = time.time()
                rows = rows_for(recs, bk, now)
                cell_out = {"all": stats(rows, bk, dep, ctx), "first": stats(rows, bk, dep, ctx, until=mid),
                            "second": stats(rows, bk, dep, ctx, since=mid),
                            "forward": stats(rows, bk, dep, ctx, since=fwd_ts) if fwd_ts else None,
                            "secs": round(time.time() - t1, 1)}
                res["books"][bk].setdefault(cell, {})[str(int(dep))] = cell_out
                a = cell_out["all"]
                log(f"{bk} ${int(dep)} {cell}: n {a['n']} полов {a['floors']} резерв заполнен {a['depth5']} usd {a['usd']} "
                    f"итог {(a['final'] or 0) * 100:+.2f} % dd {(a['max_dd'] or 0) * 100:.1f} % "
                    f"(1-я {cell_out['first']['usd']}, 2-я {cell_out['second']['usd']}, вперёд "
                    f"{(cell_out['forward'] or {}).get('usd')}); {cell_out['secs']} с")
            if cell.startswith("res:"):
                res["events"][bk][cell] = events(caches, pr, cell)
    return res


def rows_for(recs, bk, now):
    """Раздача кассы книги, где маржа записи = билет × `capital_t` (1 T у
    книги и усечённых лестниц, 1.25 T у позиций с резервом и у контроля
    билета) — это считает сама касса книги. Подмена одна: гейт плеча
    применяется ЗДЕСЬ по плечу книги (`lev_book`, у записей книги — её
    собственное), чтобы состав у всех ячеек был один; сама раздача,
    порядок и отказы — те же, что у книги."""
    ml = R.min_lev_of(bk)
    if ml is not None:
        recs = [r for r in recs if float(r.get("lev_book", r["lev"])) >= ml]
    orig_ml = R.min_lev_of
    # маржу × `capital_t` касса книги считает сама (`build_rows`, правило с
    # 04.11); здесь подменяется только гейт плеча
    R.min_lev_of = lambda _k: None
    try:
        rows, _c, _o, _l = RP.build_rows({bk: recs}, now=now, keys=[bk], log=lambda *a: None)
    finally:
        R.min_lev_of = orig_ml
    return rows


# ------------------------------------------------------------ отчёт

def pct(x):
    return "—" if x is None else f"{100 * x:+.2f} %"


def report(r):
    L_ = ["# Резервный рунг ниже плановой лестницы (спека 14 §Р1; владелец 02.11)", "",
          f"Посчитано {r['computed_at']}; ног {r['replay']['legs']}, сверено с кэшем книги {r['replay']['checked']}, "
          f"расхождений {r['replay']['mismatch']} (плечо {r['replay'].get('mismatch_lev')}, выход {r['replay'].get('mismatch_exit')}, "
          f"только деньги {r['replay'].get('mismatch_pnl')}; тиры площадки читаются по сегодняшнему состоянию, хвост ленты "
          f"дописан позже — диагностика, не вердикт; все ячейки считаны одним проходом на одних данных); усечённых лестниц (резерв не применяется) {r['replay']['truncated']}, "
          f"без σ / забор отказал {r['replay']['no_geo']}. Резерв 0.25 T, маржа позиции 1.25 T, забор на пяти рунгах; "
          f"глубины: 1σ, 2σ, 3σ ниже глубочайшего планового рунга и удвоенная глубина лестницы. "
          f"Деньги нетто; половины по времени входа; вперёд с {R.FAMILY_SINCE.get('sit')}.", "",
          "**Как читать.** `res − fence` — цена самой покупки глубже; `fence − ticket` — цена пониженного плеча; "
          "`ticket − book` — цена большего билета. Случай редкий (см. шапку модуля): малое число заполненных "
          "резервов — не вердикт, а счёт.", ""]
    for bk, cells in r["books"].items():
        L_ += [f"## {R.MODE_EN.get(bk, bk)} · `{bk}`", ""]
        for dep in r["deps"]:
            d = str(int(dep))
            L_ += [f"### депозит ${d}", "",
                   "| ячейка | позиций | полов | резерв заполнен | итог $ | итог % | просадка | зелёных | без 3 дней | 1-я | 2-я | вперёд |",
                   "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
            for cell, by_dep in cells.items():
                c = by_dep.get(d)
                if not c:
                    continue
                a, f1, f2, fw = c["all"], c["first"], c["second"], c.get("forward") or {}
                L_.append(f"| {CELL_RU.get(cell, cell)} | {a['n']} | {a['floors']} | {a['depth5']} | {a['usd']} | {pct(a['final'])} | "
                          f"{pct(a['max_dd'])} | {pct(a['win'])} | {a['usd_wo_top3d']} | {f1['usd']} | {f2['usd']} | {fw.get('usd')} |")
            L_.append("")
        ev = r["events"].get(bk) or {}
        if ev:
            L_ += ["**События (резерв заполнился), закрытые позиции:**", "",
                   "| глубина | позиций | плечо к книге (медиана) | на T: с резервом | на T: книга | Σ T: с резервом / книга | добито резервом | спасено |",
                   "|---|--:|--:|--:|--:|--:|--:|--:|"]
            for cell, e in ev.items():
                L_.append(f"| {CELL_RU.get(cell, cell)} | {e['n']} | {e['lev_ratio_med']} | {pct(e['mean_t_res'])} | {pct(e['mean_t_book'])} | "
                          f"{e['sum_t_res']} / {e['sum_t_book']} | {e['killed']} | {e['saved']} |")
            L_.append("")
    return "\n".join(L_) + "\n"


# ------------------------------------------------------------ прогон

def run(books, deps, log=print, limit=None, now=None, src=None, legs=None):
    t0 = time.time()
    now = now or time.time()
    R.SIZINGS = (R.SIZING_COMPOUND,)
    import tail as TL                                          # noqa: E402
    src = src or TL.TailBars(log=log, cache=TL.BARS_CACHE)
    legs = legs if legs is not None else D6.gated_legs(log=log, side="long")
    legs = [g for g in legs if (g.get("side") or "long") == "long"]
    pairs = pairs_of(books)
    caches = read_caches(log)
    n = replay(legs, pairs, caches, src, log=log, limit=limit)
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "deps": deps, "cells": CELLS,
           "replay": n, "reserve_w": RESERVE_W}
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
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "резервный рунг: замер"], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
