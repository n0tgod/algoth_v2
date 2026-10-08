#!/usr/bin/env python3
"""Отбор кассы коротких книг: какие выборы листа касса НЕ берёт и что они стоят.

Повод (08.10, `short_weeks`): лист жив (+126 → +170 б.п. за 24 ч), а
взятые кассой позиции во второй половине окна дают −15…+32 — отбор
−137…−184 б.п. у всех трёх книг против −45…+49 в первой. Вопрос: какой
фильтр кассы выбрасывает эдж.

Единица — решение листа (имя × час, обе руки одной записью), мера — сырой
ход имени за `HOLD_H` ч в б.п. нотионала (та же, что у `short_weeks`;
обе половины окна — та же граница). Для каждой книги решение либо
ВЗЯТО кассой $10k, либо нет, и у невзятого — первая подошедшая причина
в порядке самой кассы:

  возраст      имя моложе `rules.MIN_AGE_DAYS` на момент решения или
               возраст неизвестен (фильтр возраста, правило 08.09);
  нет записи   реплей книги записи не дал (нет баров, фильтры универсума);
  плечо        у книги с гейтом плеча (агрессивная) плечо забора ниже;
  имя занято   книга уже держит это имя («одна на имя»);
  очередь      всё прошло, денег или мест не хватило — остаток.

Оси объявлены до прогона: (1) взятые против невзятых по книге и
половине; (2) невзятые по причине — число, средний сырой ход, доля
попаданий и «масса эджа» (сумма сырого хода, б.п.) — что именно
оставлено на столе; (3) лист по полосам возраста имени (`pair_age`:
<3, 3–7, 7–14, 14–30, 30–60, ≥60 сут, неизвестен) по половинам — живёт
ли эдж в молодых именах, которых касса не берёт с 08.09.

Нуль: метка «взято» переставляется ВНУТРИ часа (число взятых в час то же:
решения одного часа делят рынок), `SEEDS` зёрен; p — доля перестановок,
где средний ход взятых не выше наблюдаемого (взятые хуже случайных того
же часа). Для полос возраста — та же перестановка полосы внутри часа,
p — доля перестановок с ходом полосы не ниже наблюдаемого.

Вердикт из чисел по объявленному порядку: во второй половине у обеих
судимых книг причина с наибольшей массой эджа среди невзятых; если
взятые хуже невзятых с p ≤ `P_LIMIT` у обеих — «отбор системный, масса в
<причина>», иначе «отбор в шуме». Правил замер не меняет, ячеек не
выбирает — он называет, ГДЕ лежит потерянный эдж, не «что делать».

    run research/dca_paper/short_select.py
"""
import argparse
import collections
import os
import random
import subprocess
import sys
import time

import numpy as np

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
import short_grid as G                                        # noqa: E402
import short_levcap as LC                                     # noqa: E402
import short_weeks as SW                                      # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import pair_age as PA                                         # noqa: E402
import wave as W                                              # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-select"
H = SW.H
HOLD_H = SW.HOLD_H
SEEDS = 200
P_LIMIT = 0.05
MAIN_DEP = SW.MAIN_DEP
BOOKS = tuple(R.H24_ORDER)
JUDGE = ("optimal_h", "aggr_h")
REASONS = ("возраст", "нет записи", "плечо", "имя занято", "очередь")
TAKEN = "взято"


# ------------------------------------------------------------ разметка

def taken_index(rows_by_book):
    """Книга → {(имя, час): (at, exit_ts)} взятых позиций."""
    out = {}
    for bk, rows in rows_by_book.items():
        d = {}
        for r in rows or []:
            try:
                at = float(r["at"])
            except (TypeError, KeyError, ValueError):
                continue
            ex = r.get("exit_ts") or r.get("end_ts")
            d[(r.get("sym"), round(at, 3))] = (at, float(ex) if ex else None)
        out[bk] = d
    return out


def held_at(taken, sym, at):
    """Держит ли книга имя в момент `at` другой позицией (вход раньше, выход позже)."""
    for (s_, _k), (a0, ex) in taken.items():
        if s_ == sym and a0 < at and (ex is None or ex > at):
            return True
    return False


def reason_of(dec, bk, taken, cache, launch, min_age, min_lev):
    """Взято или первая причина отказа в порядке кассы."""
    key = (dec["sym"], round(float(dec["at"]), 3))
    if key in taken:
        return TAKEN
    if min_age:
        a = IR.age_days(launch, dec["sym"], dec["at"])
        if a is None or a < min_age:
            return "возраст"
    rec = cache.get((S.BOOKS[bk], dec["sym"], key[1]))
    if rec is None:
        return "нет записи"
    if min_lev is not None:
        lev = float(rec.get("lev") or 0.0)
        if lev < float(min_lev):
            return "плечо"
    if held_at(taken, dec["sym"], float(dec["at"])):
        return "имя занято"
    return "очередь"


def label(rows, cache, rows_by_book, launch, books=BOOKS):
    """Каждому измеренному решению листа — полоса возраста и исход по книге."""
    tk = taken_index(rows_by_book)
    out = []
    for r in rows:
        d = dict(r)
        d["band"] = PA.band_of(IR.age_days(launch, r["sym"], r["at"]))
        d["by"] = {bk: reason_of(r, bk, tk.get(bk) or {}, cache, launch,
                                 R.min_age_days(bk), R.min_lev_of(bk)) for bk in books}
        out.append(d)
    return out


# ------------------------------------------------------------ сводки

def _agg(xs):
    if not xs:
        return None
    e = [float(x["edge"]) for x in xs]
    return {"n": len(e), "edge": sum(e) / len(e), "mass": sum(e),
            "hit": sum(1 for v in e if v > 0) / len(e),
            "se": (float(np.std(e, ddof=1)) / len(e) ** 0.5) if len(e) > 1 else None}


def by_reason(labeled, bk):
    g = collections.defaultdict(list)
    for d in labeled:
        g[d["by"][bk]].append(d)
    return {k: _agg(g.get(k)) for k in (TAKEN,) + REASONS}


def by_band(labeled):
    g = collections.defaultdict(list)
    for d in labeled:
        g[d["band"]].append(d)
    return {k: _agg(g.get(k)) for k in PA.BAND_NAMES + (PA.UNKNOWN,)}


def null_within_hour(labeled, flag_fn, seeds=SEEDS, worse=True):
    """Перестановка метки внутри часа. `flag_fn(d)` → True у помеченных.
    worse=True: p — доля перестановок, где средний ход помеченных НЕ ВЫШЕ
    наблюдаемого (помеченные хуже случайных того же часа); иначе — не ниже."""
    by_hour = collections.defaultdict(list)
    for d in labeled:
        by_hour[float(d["at"])].append(d)
    obs_v, n_flag = [], 0
    for ds in by_hour.values():
        for d in ds:
            if flag_fn(d):
                obs_v.append(float(d["edge"]))
    if not obs_v or len(obs_v) == len(labeled):
        return {"obs": (sum(obs_v) / len(obs_v)) if obs_v else None, "p": None, "n": len(obs_v)}
    obs = sum(obs_v) / len(obs_v)
    hits = 0
    for s_ in range(int(seeds)):
        rng = random.Random(5000 + s_)
        tot, cnt = 0.0, 0
        for ds in by_hour.values():
            k = sum(1 for d in ds if flag_fn(d))
            if not k:
                continue
            pick = rng.sample(ds, k)
            tot += sum(float(d["edge"]) for d in pick)
            cnt += k
        m = tot / cnt
        if (worse and m <= obs) or (not worse and m >= obs):
            hits += 1
    return {"obs": obs, "p": hits / seeds, "n": len(obs_v)}


def half_summary(labeled, seeds=SEEDS, books=BOOKS, judge_books=JUDGE):
    out = {"n": len(labeled), "sheet": _agg(labeled), "books": {}, "bands": by_band(labeled), "band_null": {}}
    for bk in books:
        r = by_reason(labeled, bk)
        rest = [d for d in labeled if d["by"][bk] != TAKEN]
        nl = null_within_hour(labeled, lambda d, b=bk: d["by"][b] == TAKEN, seeds=seeds, worse=True)
        out["books"][bk] = {"reasons": r, "rest": _agg(rest), "taken_null": nl}
    for band in PA.BAND_NAMES + (PA.UNKNOWN,):
        if any(d["band"] == band for d in labeled):
            out["band_null"][band] = null_within_hour(
                labeled, lambda d, b=band: d["band"] == b, seeds=seeds, worse=False)
    return out


def judge(halves, judge_books=JUDGE, p_limit=P_LIMIT):
    b = halves[1]
    if not b or not b.get("books"):
        return {"kind": "unmeasured", "why": "вторая половина пуста"}
    per = {}
    for bk in judge_books:
        v = b["books"].get(bk) or {}
        rs = {k: a for k, a in (v.get("reasons") or {}).items() if k != TAKEN and a}
        top = max(rs.items(), key=lambda kv: kv[1]["mass"]) if rs else None
        per[bk] = {"top": (top[0] if top else None), "top_mass": (top[1]["mass"] if top else None),
                   "top_n": (top[1]["n"] if top else None), "top_edge": (top[1]["edge"] if top else None),
                   "taken": ((v.get("reasons") or {}).get(TAKEN) or {}).get("edge"),
                   "rest": (v.get("rest") or {}).get("edge"),
                   "p": (v.get("taken_null") or {}).get("p")}
    systemic = all(per[bk]["p"] is not None and per[bk]["p"] <= p_limit
                   and per[bk]["taken"] is not None and per[bk]["rest"] is not None
                   and per[bk]["taken"] < per[bk]["rest"] for bk in judge_books)
    tops = {per[bk]["top"] for bk in judge_books}
    return {"kind": ("systemic" if systemic else "noise"), "per": per,
            "same_top": (len(tops) == 1 and None not in tops), "top": (tops.pop() if len(tops) == 1 else None)}


def verdict(j):
    f = lambda x: "—" if x is None else f"{x:+.0f}"                           # noqa: E731
    p = lambda x: "—" if x is None else f"{x:.2f}"                            # noqa: E731
    if j.get("kind") == "unmeasured":
        return f"не измерено: {j.get('why')}"
    parts = "; ".join(f"{bk}: взятые {f(v['taken'])} против невзятых {f(v['rest'])} б.п. (p {p(v['p'])}), "
                      f"больше всего эджа оставлено в «{v['top']}» ({v['top_n']} решений, {f(v['top_edge'])} б.п. в среднем, масса {f(v['top_mass'])})"
                      for bk, v in j["per"].items())
    if j["kind"] == "systemic":
        head = ("отбор системный" + (f", масса эджа в «{j['top']}» у обеих судимых книг" if j.get("same_top") else ", причины у книг разные"))
    else:
        head = "отбор в шуме: взятые не хуже случайных того же часа хотя бы у одной судимой книги"
    return head + ": " + parts


# ------------------------------------------------------------ прогон

def run(log=print, legs_=None, names=None, mkt=None, cache=None, ctx=None, launch=None, now=None,
        seeds=SEEDS, mem_limit=None, hold_h=HOLD_H, min_xs=SW.MIN_XS, cut=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    legs_ = S.legs(log=log) if legs_ is None else legs_
    decs = SW.decisions(legs_)
    names = SW.universe() if names is None else list(names)
    mkt = W.Market() if mkt is None else mkt
    rows, _hours, miss = SW.measure(decs, mkt, names, hold_h=hold_h, seeds=0, min_xs=min_xs, log=log)
    if not rows:
        return {"error": "ни один выбор не измерен", "miss": miss, "computed_at": G.stamp()}
    if cache is None:
        cache, why = S.read_cache(log=log)
        if why:
            return {"error": f"кэш реплея непригоден: {why}", "computed_at": G.stamp()}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    rows_by_book = LC.cash_rows(AG.packed_short(cache), ctx, launch, now=now, dep=MAIN_DEP)
    log("касса: " + ", ".join(f"{bk} позиций {len(rows_by_book.get(bk) or [])}" for bk in BOOKS))
    labeled = label(rows, cache, rows_by_book, launch)
    cut = SW.cut_date(rows) if cut is None else cut
    a = [d for d in labeled if d["date"] < cut]
    b = [d for d in labeled if d["date"] >= cut]
    halves = [half_summary(a, seeds=seeds), half_summary(b, seeds=seeds)]
    log(f"половины: {len(a)} / {len(b)} решений, граница {cut}")
    j = judge(halves)
    log(f"вердикт: {verdict(j)}")
    return {"hold_h": hold_h, "seeds": seeds, "p_limit": P_LIMIT, "dep": MAIN_DEP, "books": list(BOOKS),
            "judge_books": list(JUDGE), "reasons": list(REASONS), "cut": cut, "miss": miss,
            "n_decisions": len(decs), "n_measured": len(rows), "halves": halves, "judge": j,
            "min_age": {bk: R.min_age_days(bk) for bk in BOOKS}, "min_lev": {bk: R.min_lev_of(bk) for bk in BOOKS},
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ------------------------------------------------------------ отчёт

def _b(x):
    return "—" if x is None else f"{x:+.0f}"


def _pc(x):
    return "—" if x is None else f"{100 * x:.0f} %"


def _p2(x):
    return "—" if x is None else f"{x:.2f}"


def _title(bk):
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная"}.get(bk, bk)


def report(s):
    if s.get("error"):
        return f"# Отбор кассы коротких книг\n\n**Не измерено:** {s['error']}.\n"
    L_ = ["# Отбор кассы коротких книг: какие выборы листа не взяты и что они стоят", "",
          f"- решений {s['n_decisions']}, измерено {s['n_measured']}; граница половин {s['cut']}; мера — сырой ход имени за {s['hold_h']} ч, "
          f"б.п. нотионала (шорт); касса ${int(s['dep']):,} нетто; нуль — перестановка метки внутри часа, {s['seeds']} зёрен; "
          f"посчитано {s['computed_at']} за {s['secs']:.0f} с.",
          "- причины отказа в порядке кассы: возраст (имя моложе порога или возраст неизвестен), нет записи (реплей книги записи не дал), "
          "плечо (гейт плеча книги), имя занято («одна на имя»), очередь (денег или мест не хватило). «Масса» — сумма сырого хода решений группы, б.п.: сколько эджа лежит в группе.", ""]
    for i, hv in enumerate(s["halves"]):
        sh = hv.get("sheet") or {}
        L_ += [f"## {i + 1}-я половина: решений {hv['n']}, лист {_b(sh.get('edge'))} б.п., попаданий {_pc(sh.get('hit'))}", "",
               "| книга | исход | решений | доля | сырой ход, б.п. | ± | попаданий | масса, б.п. |", "|---|---|--:|--:|--:|--:|--:|--:|"]
        for bk in s["books"]:
            v = hv["books"].get(bk) or {}
            for k in (TAKEN,) + tuple(s["reasons"]):
                a = (v.get("reasons") or {}).get(k)
                if not a:
                    continue
                nl = v.get("taken_null") or {}
                tag = f" (p {_p2(nl.get('p'))} против случайных того же часа)" if k == TAKEN else ""
                L_.append(f"| {_title(bk)} | {k}{tag} | {a['n']} | {_pc(a['n'] / hv['n'])} | {_b(a['edge'])} | {_b(a.get('se'))} | "
                          f"{_pc(a['hit'])} | {_b(a['mass'])} |")
        L_ += ["", "| полоса возраста | решений | доля | сырой ход, б.п. | ± | попаданий | масса | p (полоса не ниже случайных того же часа) |",
               "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for band, a in (hv.get("bands") or {}).items():
            if not a:
                continue
            nl = (hv.get("band_null") or {}).get(band) or {}
            L_.append(f"| {band} | {a['n']} | {_pc(a['n'] / hv['n'])} | {_b(a['edge'])} | {_b(a.get('se'))} | {_pc(a['hit'])} | "
                      f"{_b(a['mass'])} | {_p2(nl.get('p'))} |")
        L_.append("")
    L_ += ["## Вердикт (из чисел)", "", f"- {verdict(s['judge'])}", "",
           f"Порядок суда объявлен до прогона: во второй половине у обеих судимых книг взятые хуже невзятых с p ≤ {s['p_limit']:g} — отбор системный, "
           "и называется причина с наибольшей массой эджа; иначе — в шуме. Порог возраста книг "
           + ", ".join(f"{_title(bk)} {s['min_age'][bk]:g} сут" for bk in s["books"])
           + "; гейт плеча " + ", ".join(f"{_title(bk)} {s['min_lev'][bk]}" for bk in s["books"] if s["min_lev"][bk] is not None)
           + ". Правила не менялись, ячейки не выбирались; окно одно.", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    log = lambda *x: print(*x, flush=True)                                   # noqa: E731
    s = run(log=log, seeds=a.seeds)
    G.write(s, ART, report, log=log)
    if not a.no_publish:
        publish("отбор кассы коротких книг")


if __name__ == "__main__":
    main()
