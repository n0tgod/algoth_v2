#!/usr/bin/env python3
"""Вторая ступень по повторному выбору модели — в ЯДРЕ лестницы, реплей по барам.

Второй шаг после `short_adds` (05.10): там долив по повторному выбору был
единственным триггером с плюсом (оптимальная 2.34 → 4.31, агрессивная
2.40 → 2.64), но считался ПО ЧАСОВЫМ ОТМЕТКАМ кэша с оговоркой часа, а не
ядром. Здесь то же правило считается ядром `ladder.simulate_dca` на
барах записи: долив по времени (`adds`) рыночно по открытию бара, из той
же зарезервированной маржи (книга резервирует четыре ступени по 0.25 и
заполняет одну), с ОБЩИМ полом капитуляции и плавающей ТВХ — позиция
одна, убыток долива ничем не ограничен (урок 05.10). Решение владельца
06.10: «давай тогда дальше мерить доливание в сделку».

Оси объявлены до прогона. Повтор — выбор листа `h24` (обе руки) того же
имени в срок позиции (24 ч) после входа; исполняется, пока позиция
открыта. Ячейки на одной геометрии книги (`fence:none:t2`):

  ref — как книга, без доливов (обязана совпасть с кэшем книги бит в бит
        у закрытых записей; расхождение печатается числом);
  r2  — вторая ступень на ПЕРВОМ повторе (главная ячейка — та, что
        выиграла 05.10; по ней вердикт);
  r2p — вторая ступень на первом повторе, при котором позиция в плюсе
        по открытию бара (повтор в минусе пропускается, ход к следующему);
  r4  — ступень на каждом повторе, пока не заполнены все четыре;
  n01…n10 — НУЛЬ: та же вторая ступень, но момент повтора взят у ЧУЖОЙ
        позиции (перестановка смещений «первый повтор − вход» между
        позициями с повтором, 10 зёрен): столько же доливов, то же
        распределение задержек, случайные позиции. Судит ВЫБОР модели,
        а не сам факт долива в открытый шорт.

Деньги: по записям — нетто круга издержек на заполненный нотионал
(`pnl_net` ядра, долив включён); по кассе $10k — тем же ядром, что
прогон книг (`cell_stats`), с настоящими издержками каждой сделки, плюс
проскальзывание ДОЛИВОВ (рыночный ордер) по ставке входа — модель
издержек считает рунги лимитными и его не берёт. Правило книги про
возраст имени, гейт плеча агрессивной, «одна на имя» — те же.

Рычаг (объявлено): у оптимальной И агрессивной `r2` лучше `ref` по итогу
и по доходу/просадке, и доход/просадка `r2` выше, чем у КАЖДОГО из
десяти нулевых зёрен (разрешение доли — 1/10). Безопасная печатается,
не судится (05.10: её пол далеко, ступень там добавляет размер без
защиты). Правила книг не меняются. Право на итерацию одно.

    run research/dca_paper/short_rung.py              # вся ось, ~1–1.5 ч
    run research/dca_paper/short_rung.py --limit 200  # смоук
"""
import argparse
import bisect
import gc
import os
import random
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_short as S                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_levers as L                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-rung"
MAIN_DEP = 10000
NULL_SEEDS = 10
JUDGE = ("optimal_h", "aggr_h")
BOOK_KEYS = list(S.BOOKS)
BASE = S.CELL                       # геометрия книги: ("fence:none:t2", "fence", "none", "t2")
ADD_W = float(D2.WEIGHTS[1])        # доля ступени — вторая по счёту, 0.25
MAX_ADDS = int(D2.N_RUNGS) - 1      # три долива поверх базы
HOUR = 3600.0
KILL_EXITS = ("пол", "ликвидация")
CELLS = (("ref", "как книга: без доливов"),
         ("r2", "вторая ступень на первом повторе"),
         ("r2p", "вторая ступень на первом повторе при плюсе"),
         ("r4", "ступень на каждом повторе, до четырёх"))
MAIN_CELL = "r2"


def null_name(i):
    return f"n{int(i):02d}"


def cell_key(name):
    return f"{BASE[0]}#{name}"


def name_of(key):
    return key.split("#", 1)[1] if "#" in key else key


def cells_for(seeds=NULL_SEEDS):
    """Ячейки прохода ядра: одна геометрия, разные политики долива."""
    names = [c[0] for c in CELLS] + [null_name(i) for i in range(1, int(seeds) + 1)]
    return [(cell_key(n), BASE[1], BASE[2], BASE[3]) for n in names]


def pkey(sym, at):
    return (str(sym), round(float(at), 3))


def repeats_of(legs, hold_h=None):
    """{(имя, момент): [моменты повторов]} — выборы того же имени в срок позиции."""
    hold = float(R.H24_HOLD_H if hold_h is None else hold_h) * HOUR
    by_sym = {}
    for g in legs:
        by_sym.setdefault(str(g["sym"]), set()).add(round(float(g["at"]), 3))
    sorted_ats = {s: sorted(v) for s, v in by_sym.items()}
    out = {}
    for g in legs:
        sym, at = str(g["sym"]), round(float(g["at"]), 3)
        ats = sorted_ats[sym]
        i = bisect.bisect_right(ats, at)
        j = bisect.bisect_right(ats, at + hold)
        out[pkey(sym, at)] = [float(t) for t in ats[i:j]]
    return out


def null_offsets(reps, seed):
    """Нуль: смещение первого повтора каждой позиции отдаётся ЧУЖОЙ позиции
    (перестановка среди позиций с повтором) — счёт и задержки те же."""
    parents = sorted(k for k, v in reps.items() if v)
    offs = [reps[k][0] - k[1] for k in parents]
    rnd = random.Random(7000 + int(seed))
    rnd.shuffle(offs)
    return {k: k[1] + o for k, o in zip(parents, offs)}


def policy(name, key, reps, nulls):
    """Политика долива ячейки для позиции `key` — словарь для ядра или None."""
    if name == "ref":
        return None
    rp = reps.get(key) or []
    if name == "r2":
        return {"adds": [(t, ADD_W) for t in rp[:1]], "max": 1} if rp else None
    if name == "r2p":
        return {"adds": [(t, ADD_W) for t in rp], "max": 1, "if_profit": True} if rp else None
    if name == "r4":
        return {"adds": [(t, ADD_W) for t in rp[:MAX_ADDS]], "max": MAX_ADDS} if rp else None
    if name.startswith("n"):
        t = (nulls.get(name) or {}).get(key)
        return {"adds": [(t, ADD_W)], "max": 1} if t is not None else None
    raise ValueError(f"неизвестная ячейка {name}")


def make_adds_of(reps, nulls):
    def adds_of(g, key):
        return policy(name_of(key), pkey(g["sym"], g["at"]), reps, nulls)
    return adds_of


def slip_adds_usd(row, slip_bp=None):
    """Проскальзывание доливов: рыночный ордер по ставке входа на долю
    нотионала каждого долива (последние `adds` заполнений записи)."""
    n = int(row.get("adds") or 0)
    if n <= 0:
        return 0.0
    notl = R.notional_of(row)
    fills = row.get("fills") or []
    if notl is None or len(fills) < n + 1:
        return 0.0
    rate = float(CO.SLIP_BP if slip_bp is None else slip_bp) / 1e4
    return sum(float(f[2]) * notl * rate for f in fills[-n:])


def packed_of(cell_recs):
    """{(линейка, имя, момент): запись} → {книга: [записи]} картой прогона."""
    by_rk = {}
    for (rk, _s, _a), r in cell_recs.items():
        by_rk.setdefault(rk, []).append(r)
    return {bk: list(by_rk.get(rk) or []) for bk, rk in S.BOOKS.items()}


def ref_check(ref_recs, cache, tol=1e-9):
    """Сверка ячейки `ref` с кэшем книги по закрытым записям обоих."""
    n, bad, sample = 0, 0, []
    for key, r in ref_recs.items():
        c = cache.get(key)
        if c is None or c.get("state") != "closed" or r.get("state") != "closed":
            continue
        n += 1
        same = (c.get("exit") == r.get("exit")
                and abs(float(c.get("pnl") or 0) - float(r.get("pnl") or 0)) <= tol
                and abs(float(c.get("exit_ts") or 0) - float(r.get("exit_ts") or 0)) <= 1.0)
        if not same:
            bad += 1
            if len(sample) < 5:
                sample.append({"key": list(key), "cache": [c.get("exit"), c.get("pnl")],
                               "ref": [r.get("exit"), r.get("pnl")]})
    return {"compared": n, "mismatch": bad, "sample": sample}


def _p5(xs):
    xs = sorted(xs)
    return xs[max(0, int(0.05 * len(xs)) - 1)] if xs else None


def position_stats(cell_recs, ref_recs, book):
    """Приращение денег позиции от долива (нетто круга) — у позиций книги,
    где долив исполнился; гейт плеча книги — как у статистики записей."""
    ml = R.min_lev_of(book)
    rk = S.BOOKS[book]
    inc, killed, n_pos = [], 0, 0
    for key, r in cell_recs.items():
        if key[0] != rk or (r.get("state") or "closed") != "closed":
            continue
        ref = ref_recs.get(key)
        if ref is None or (ref.get("state") or "closed") != "closed":
            continue
        lev = float(r.get("lev") or 0.0)
        if not lev > 0 or (ml is not None and lev < float(ml)):
            continue
        n_pos += 1
        if int(r.get("adds") or 0) <= 0:
            continue
        inc.append(float(r["pnl_net"]) - float(ref["pnl_net"]))
        if r.get("exit") in KILL_EXITS and ref.get("exit") not in KILL_EXITS:
            killed += 1
    if not inc:
        return {"positions": n_pos, "adds": 0, "mean": None, "median": None,
                "pos_share": None, "p5": None, "killed": 0}
    return {"positions": n_pos, "adds": len(inc), "mean": statistics.fmean(inc),
            "median": statistics.median(inc), "pos_share": sum(1 for x in inc if x > 0) / len(inc),
            "p5": _p5(inc), "killed": killed}


def cash_of(cell_recs, ctx, launch, dep=MAIN_DEP, now=None):
    packed = packed_of(cell_recs)
    keys = [bk for bk in BOOK_KEYS if packed.get(bk)]
    st = G.cell_stats({bk: packed[bk] for bk in keys}, ctx, launch, now=now, keys=keys,
                      deps=[dep], extra_usd=slip_adds_usd)
    out = {}
    for bk in keys:
        c = st.get(f"{bk}:{int(dep)}") or {}
        d = L.summ(c)
        ex = c.get("exits") or {}
        d["kill_n"] = sum(int((ex.get(k) or {}).get("n") or 0) for k in KILL_EXITS)
        d["exits"] = {k: int((v or {}).get("n") or 0) for k, v in ex.items()}
        out[bk] = d
    return out


def ratio_of(c):
    return (None if not c or not c.get("final") or not c.get("max_dd")
            else round(float(c["final"]) / abs(float(c["max_dd"])), 2))


def null_summary(cash, seeds, bk, main):
    """Нуль по кассе книги: медиана/мин/макс итога и отношения по зёрнам,
    доля зёрен не хуже главной ячейки."""
    fins = [cash[null_name(i)][bk].get("final") for i in range(1, seeds + 1)]
    rats = [ratio_of(cash[null_name(i)][bk]) for i in range(1, seeds + 1)]
    fins = [float(x) for x in fins if x is not None]
    rats = [float(x) for x in rats if x is not None]
    mf, mr = main.get("final"), ratio_of(main)
    return {"n": len(rats), "final_med": (statistics.median(fins) if fins else None),
            "final_min": (min(fins) if fins else None), "final_max": (max(fins) if fins else None),
            "ratio_med": (statistics.median(rats) if rats else None),
            "ratio_min": (min(rats) if rats else None), "ratio_max": (max(rats) if rats else None),
            "beat_final": (sum(1 for x in fins if mf is not None and x >= float(mf)) / len(fins) if fins and mf is not None else None),
            "beat_ratio": (sum(1 for x in rats if mr is not None and x >= float(mr)) / len(rats) if rats and mr is not None else None)}


def verdict(cash, nulls_summ, judge=JUDGE):
    parts, ok = [], True
    for bk in judge:
        ref, main = cash["ref"][bk], cash[MAIN_CELL][bk]
        nz = nulls_summ[bk]
        r_ref, r_main = ratio_of(ref), ratio_of(main)
        if r_ref is None or r_main is None or nz.get("beat_ratio") is None or main.get("final") is None:
            parts.append(f"{bk}: не измерено")
            ok = False
            continue
        better = r_main > r_ref and float(main["final"]) > float(ref["final"] or 0)
        beats_null = float(nz["beat_ratio"]) == 0.0
        parts.append(f"{bk}: доход/просадка {r_main:.2f} против {r_ref:.2f} как книга, "
                     f"нуль (чужой повтор) медиана {nz['ratio_med']:.2f}, зёрен не хуже {nz['beat_ratio']:.0%}")
        if not (better and beats_null):
            ok = False
    return ("РЫЧАГ: " if ok else "не рычаг: ") + "; ".join(parts)


def run(limit=None, src=None, log=print, legs_=None, ctx=None, launch=None, now=None,
        seeds=NULL_SEEDS, cache=None, mem_limit=None, dep=MAIN_DEP):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        return {"error": "коротких решений на листе нет"}
    reps = repeats_of(legs_)
    nulls = {null_name(i): null_offsets(reps, i) for i in range(1, int(seeds) + 1)}
    with_rep = sum(1 for v in reps.values() if v)
    offs_h = sorted((v[0] - k[1]) / HOUR for k, v in reps.items() if v)
    log(f"решений {len(legs_)}, уникальных позиций {len(reps)}, с повтором в срок {with_rep} "
        f"({with_rep / max(1, len(reps)):.0%}); медиана задержки первого повтора "
        f"{(offs_h[len(offs_h) // 2] if offs_h else float('nan')):.1f} ч")
    cells = cells_for(seeds)
    names = [c[0] for c in CELLS] + [null_name(i) for i in range(1, int(seeds) + 1)]
    if cache is None:
        cache, _why = S.read_cache(log=log)
    cache = cache or {}
    adds_of = make_adds_of(reps, nulls)
    # По группам пола: проход считает только линейки своей группы, касса и
    # статистика позиций её книг считаются СРАЗУ, записи освобождаются —
    # первый прогон (06.10) держал 14 ячеек × 2 линейки разом и снял себя
    # по памяти на второй группе. Память считается составом до счёта.
    cash = {nm: {} for nm in names}
    pos = {nm: {} for nm in names}
    check = {"compared": 0, "mismatch": 0, "sample": []}
    tail = None
    for frac, group in sorted(S.floor_groups().items()):
        books = [bk for bk in BOOK_KEYS if S.BOOKS[bk] in group]
        got, t = S.replay_cells(legs_, cells, src=src, log=log, adds_of=adds_of, rulers=group)
        tail = tail if tail is not None else t
        ref_recs = got.get(cell_key("ref")) or {}
        c = ref_check(ref_recs, cache)
        check["compared"] += c["compared"]
        check["mismatch"] += c["mismatch"]
        check["sample"] = (check["sample"] + c["sample"])[:5]
        log(f"пол {frac:g}: сверка ref с кэшем книги — закрытых у обоих {c['compared']}, "
            f"расхождений {c['mismatch']}")
        for nm in names:
            recs = got.get(cell_key(nm)) or {}
            st = cash_of(recs, ctx, launch, dep=dep, now=now)
            for bk in books:
                cash[nm][bk] = st[bk]
                pos[nm][bk] = position_stats(recs, ref_recs, bk)
            if not nm.startswith("n"):
                log(f"пол {frac:g} {nm}: " + ", ".join(f"{bk} {ratio_of(cash[nm][bk])} (сделок {cash[nm][bk].get('n')})"
                                                     for bk in books) + f" ({time.time() - t0:.0f} с)")
        del got, ref_recs
        gc.collect()
    nulls_summ = {bk: null_summary(cash, int(seeds), bk, cash[MAIN_CELL][bk]) for bk in BOOK_KEYS}
    # нуль по позициям: доля зёрен, у которых среднее приращение не хуже главной ячейки
    pos_null = {}
    for bk in BOOK_KEYS:
        means = [pos[null_name(i)][bk].get("mean") for i in range(1, int(seeds) + 1)]
        means = [float(x) for x in means if x is not None]
        m = pos[MAIN_CELL][bk].get("mean")
        pos_null[bk] = {"mean_med": (statistics.median(means) if means else None),
                        "beat": (sum(1 for x in means if m is not None and x >= float(m)) / len(means)
                                 if means and m is not None else None),
                        "adds_med": statistics.median([pos[null_name(i)][bk]["adds"] for i in range(1, int(seeds) + 1)])}
    return {"dep": dep, "seeds": int(seeds), "legs": len(legs_), "positions": len(reps),
            "with_repeat": with_rep, "offset_med_h": (offs_h[len(offs_h) // 2] if offs_h else None),
            "cells": [list(c) for c in CELLS], "main_cell": MAIN_CELL, "judge": list(JUDGE),
            "books": BOOK_KEYS, "cash": cash, "positions_stats": pos, "null": nulls_summ,
            "pos_null": pos_null, "ref_check": check, "tail": tail,
            "slip_bp": CO.SLIP_BP, "verdict": verdict(cash, nulls_summ),
            "window": None, "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- отчёт
def _p(x, d=1):
    return "—" if x is None else f"{100 * float(x):+.{d}f} %"


def _pp(x):
    return "—" if x is None else f"{100 * float(x):.0f} %"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _n(x):
    return "—" if x is None else f"{int(x)}"


def _title(bk):
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная"}.get(bk, bk)


def report(s):
    if s.get("error"):
        return f"# Вторая ступень по повторному выбору\n\nОШИБКА: {s['error']}\n"
    chk = s["ref_check"]
    L_ = ["# Вторая ступень по повторному выбору модели: ядро лестницы, реплей по барам, общий пол",
          "",
          f"Решений {s['legs']}, позиций {s['positions']}, с повтором в срок {s['with_repeat']} "
          f"({s['with_repeat'] / max(1, s['positions']):.0%}); медиана задержки первого повтора "
          f"{_f(s['offset_med_h'], 1)} ч. Касса ${s['dep']:,} нетто; нулевых зёрен {s['seeds']}; "
          f"проскальзывание доливов {s['slip_bp']} б.п.; посчитано {s['computed_at']} за {s['secs']} с.",
          "",
          f"Сверка ячейки «как книга» с кэшем книги: закрытых у обоих {chk['compared']}, расхождений {chk['mismatch']}"
          + (" — РЕПЛЕЙ РАСХОДИТСЯ С КНИГОЙ, числа ниже под вопросом." if chk["mismatch"] else "."),
          "",
          "Долив — рыночно по открытию бара повтора, 0.25 нотионала из зарезервированной маржи; позиция одна: "
          "общий пол, плавающая ТВХ, цель от неё. Нуль — тот же долив по задержке ЧУЖОЙ позиции (перестановка).",
          ""]
    for bk in s["books"]:
        L_ += [f"## {_title(bk)} — по кассе", "",
               "| ячейка | сделок | итог | просадка | доход/просадка | без 3 дней, $ | σ дня, $ | выходов полом/ликвидацией |",
               "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for key, title in s["cells"]:
            c = s["cash"][key][bk]
            L_.append(f"| {title} | {_n(c.get('n'))} | {_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                      f"{_f(ratio_of(c))} | {_n(c.get('wo3'))} | {_n(c.get('sigma_day'))} | {_n(c.get('kill_n'))} |")
        nz = s["null"][bk]
        L_.append(f"| нуль: чужой повтор, {nz['n']} зёрен (медиана; мин…макс) | — | {_p(nz['final_med'])} "
                  f"({_p(nz['final_min'])} … {_p(nz['final_max'])}) | — | {_f(nz['ratio_med'])} "
                  f"({_f(nz['ratio_min'])} … {_f(nz['ratio_max'])}) | — | — | — |")
        L_ += ["", f"Зёрен нуля не хуже «{dict(s['cells'])[s['main_cell']]}»: по итогу {_pp(nz['beat_final'])}, "
                   f"по доходу/просадке {_pp(nz['beat_ratio'])}.", ""]
        L_ += [f"### {_title(bk)} — по позициям (приращение денег позиции от долива, доли маржи, нетто круга)", "",
               "| ячейка | позиций | с доливом | среднее | медиана | плюсовых | худшие 5 % | добито доливом |",
               "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for key, title in s["cells"][1:]:
            p = s["positions_stats"][key][bk]
            L_.append(f"| {title} | {_n(p['positions'])} | {_n(p['adds'])} | {_p(p['mean'], 2)} | {_p(p['median'], 2)} | "
                      f"{_pp(p['pos_share'])} | {_p(p['p5'], 1)} | {_n(p['killed'])} |")
        pn = s["pos_null"][bk]
        L_.append(f"| нуль: чужой повтор (медиана по зёрнам) | — | {_n(pn['adds_med'])} | {_p(pn['mean_med'], 2)} | — | — | — | — |")
        L_ += ["", f"Зёрен нуля со средним приращением не хуже главной ячейки: {_pp(pn['beat'])}.", ""]
    L_ += ["## Вердикт (из чисел)", "", f"- {s['verdict']}", "",
           "Чего замер не делает: правил книг не меняет; окно одно, веса модели эти часы видели (оценка сверху); "
           "третья и четвёртая ступени судятся только как ячейка `r4`, не по отдельности; безопасная печатается, "
           "не судится. Разрешение доли нуля — одно зерно из десяти.", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seeds", type=int, default=NULL_SEEDS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(limit=a.limit, log=print, seeds=a.seeds)
    if s.get("error"):
        print(s["error"])
    name = ART if a.limit is None else f"{ART}-smoke"
    G.write(s, name, report, log=print)
    if not a.no_publish:
        publish("вторая ступень по повторному выбору: ядро лестницы, общий пол, нуль-перестановка")


if __name__ == "__main__":
    main()
