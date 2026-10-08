#!/usr/bin/env python3
"""Эдж коротких выборов h24 по неделям: сигнал ослаб, рынок режет или касса?

Повод (08.10). Все замеры недели — доливы, повтор, срок, пол — показали
одно и то же: вторая половина окна (с 07.09) слаба у всех трёх коротких
книг при ЛЮБОЙ настройке (доход/просадка 0.04…1.04 против 1.42…5.72 в
первой). Пока это не понято, любая ось меряется наполовину на мёртвом
сигнале. Вопрос владельца: что случилось во второй половине.

Три ответа, объявленные ДО прогона, и чем они различаются:

* **сигнал ослаб сам** — эдж выборов НАД одновременной кросс-секцией
  (все имена с ценой в тот же час) упал во второй половине, и нуль по
  часовым блокам это подтверждает (p ≤ 0.05);
* **сигнал жив, шорты режет рынок** — эдж над кросс-секцией держится,
  а сырой эдж (минус ход имени за 24 ч) упал: рынок рос, и шорт платил
  за бету, не за выбор;
* **сигнал жив, убивает касса** — и сырой, и над кросс-секцией держатся,
  а разрыв между ценой ВЗЯТЫХ кассой позиций и листом (отбор «одна на
  имя» и очередь) расширился на ≥ `CASH_GAP_BP` у обеих судимых книг.

Ничего из этого не подтвердилось — «второй половины как режима стенд
не видит»: разница в шуме, и слабость кассы есть шум кассы.

Единица — выбор (имя × час), обе руки одним решением (та же склейка,
что у кассы: `repeat_entry.label`). Мера эджа — в ЦЕНЕ, б.п. нотионала:
минус ход середины стакана за `HOLD_H` часов по часовым сводкам S8
(`wave.Market`, те же цены, что у охраны рынком). Контроли: одновременная
кросс-секция (средний ход всех имён с ценой в тот же час) и случайные
выборы ТОГО ЖЕ размера в тот же час, `SEEDS` зёрен. Нуль половин —
перестановка метки половины по ЧАСОВЫМ блокам (выборы одного часа идут
вместе: они делят рынок, порознь их переставлять значило бы считать
один час двадцатью наблюдениями). Половины — по дате, граница та же,
что у замера пола (медианный день выборов). Неделя — ISO, таблица.

Касса — $10k нетто тем же ядром, что прогон книг (`short_levcap.cash_rows`):
взятые позиции по неделе входа, их цена в б.п. нотионала, и разрыв с
листом той же половины.

Чего замер не делает: правил не меняет, ячеек не выбирает, окно одно, и
веса модели эти часы видели — он отвечает, ЕСТЬ ЛИ разница между
половинами и какой она природы, не «что делать».

    run research/dca_paper/short_weeks.py
"""
import argparse
import collections
import datetime as dt
import os
import random
import statistics
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
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import wave as W                                              # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-weeks"
H = 3600.0
HOLD_H = int(R.H24_HOLD_H)          # срок коротких книг — та же мера хода
SEEDS = 200
P_LIMIT = 0.05                      # порог нуля половин, объявлен до прогона
CASH_GAP_BP = 5.0                   # расширение разрыва касса−лист, б.п.
MIN_XS = 50                         # меньше имён с ценой в час — кросс-секции нет
MAIN_DEP = 10000.0
BOOKS = tuple(R.H24_ORDER)
JUDGE = ("optimal_h", "aggr_h")


# ------------------------------------------------------------ выборы

def week_of(ts):
    y, w, _d = dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def date_of(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))


def decisions(legs_):
    """Одно решение на (имя, час): обе руки в одну секунду — одна запись,
    остаётся больший |прогноз| (та же склейка, что у кассы)."""
    best = {}
    for g in legs_:
        k = (g["sym"], round(float(g["at"]), 3))
        cur = best.get(k)
        if cur is None or abs(float(g.get("fwd") or 0)) > abs(float(cur.get("fwd") or 0)):
            best[k] = dict(g, arms=sorted(set((cur or {}).get("arms", []) + [g.get("arm") or ""])))
        else:
            cur["arms"] = sorted(set(cur.get("arms", []) + [g.get("arm") or ""]))
    out = list(best.values())
    out.sort(key=lambda g: (g["at"], g["sym"]))
    return out


def universe(root=W.SUMMARY_DIR):
    try:
        return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    except OSError:
        return []


def measure(decs, mkt, names, hold_h=HOLD_H, seeds=SEEDS, min_xs=MIN_XS, log=print):
    """Цена каждого выбора и контроли того же часа.

    На выбор: `move` — ход имени за hold_h ч (доля), `edge` — минус ход в
    б.п. (шорт), `xs` — средний минус-ход всех имён с ценой в тот час,
    `edge_xs` = edge − xs, `wave` — волна прокси-имён за те же часы (б.п.).
    На час: `rand[s]` — средний эдж случайных n имён того часа, зерно s.
    Час без цены имени — выбор «не измерен» (считается), час с < min_xs
    именами — кросс-секции нет (считается отдельно).
    """
    by_hour = collections.defaultdict(list)
    for g in decs:
        by_hour[float(g["at"])].append(g)
    rows, hours = [], {}
    miss = {"no_price": 0, "no_xs": 0, "no_wave": 0}
    t0 = time.time()
    for i, at in enumerate(sorted(by_hour)):
        t1 = at + hold_h * H
        mv = {}
        for s_ in names:
            m = mkt.move(s_, at, t1)
            if m is not None:
                mv[s_] = m
        xs = (float(np.mean([-m for m in mv.values()])) * 1e4) if len(mv) >= min_xs else None
        if xs is None:
            miss["no_xs"] += 1
        wv = mkt.wave(at, t1)
        if wv is None:
            miss["no_wave"] += 1
        picks = by_hour[at]
        n_meas = 0
        for g in picks:
            m = mv.get(g["sym"])
            if m is None:
                m = mkt.move(g["sym"], at, t1)
            if m is None:
                miss["no_price"] += 1
                continue
            n_meas += 1
            e = -float(m) * 1e4
            rows.append({"sym": g["sym"], "at": at, "week": week_of(at), "date": date_of(at),
                         "fwd": float(g.get("fwd") or 0.0), "arms": g.get("arms") or [g.get("arm")],
                         "edge": e, "xs": xs, "edge_xs": (None if xs is None else e - xs),
                         "wave": (None if wv is None else float(wv) * 1e4)})
        rand = None
        if xs is not None and n_meas > 0 and seeds:
            pool = np.array([-m for m in mv.values()]) * 1e4
            rand = []
            for s_ in range(int(seeds)):
                rng = np.random.default_rng((int(at) & 0x7fffffff) * 1000 + s_)
                idx = rng.choice(len(pool), size=min(n_meas, len(pool)), replace=False)
                rand.append(float(pool[idx].mean()))
        hours[at] = {"n": n_meas, "n_xs": len(mv), "xs": xs, "wave": (None if wv is None else float(wv) * 1e4),
                     "rand": rand}
        if (i + 1) % 100 == 0:
            log(f"  час {i + 1}/{len(by_hour)}  выборов {len(rows)}  ({time.time() - t0:.0f} с)")
    log(f"выборов измерено {len(rows)} из {len(decs)}; часов {len(hours)}; "
        f"без цены имени {miss['no_price']}, без кросс-секции {miss['no_xs']}, без волны {miss['no_wave']}")
    return rows, hours, miss


# ------------------------------------------------------------ сводки

def _mean(xs):
    xs = [float(x) for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _median(xs):
    xs = [float(x) for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def summarize(rows, hours, ats=None):
    """Сводка подмножества выборов (и их часов): эдж, попадания, над
    кросс-секцией, волна, случайные того же размера."""
    if not rows:
        return None
    ats = sorted(set(float(r["at"]) for r in rows)) if ats is None else ats
    e = [r["edge"] for r in rows]
    rand_means = None
    rs = [hours[a]["rand"] for a in ats if hours.get(a) and hours[a].get("rand")]
    ws = [hours[a]["n"] for a in ats if hours.get(a) and hours[a].get("rand")]
    if rs:
        arr = np.array(rs)                                  # часы × зёрна
        wgt = np.array(ws, dtype=float)
        rand_means = list((arr * wgt[:, None]).sum(axis=0) / wgt.sum())
    mean_e = _mean(e)
    return {"n": len(rows), "hours": len(ats),
            "days": len(set(r["date"] for r in rows)),
            "edge": mean_e, "edge_med": _median(e),
            "hit": sum(1 for x in e if x > 0) / len(e),
            "edge_xs": _mean([r["edge_xs"] for r in rows]),
            "xs": _mean([r["xs"] for r in rows]),
            "wave": _mean([r["wave"] for r in rows]),
            "rand_med": (_median(rand_means) if rand_means else None),
            "rand_ge": (None if not rand_means or mean_e is None
                        else sum(1 for x in rand_means if x >= mean_e) / len(rand_means)),
            "from": min(r["date"] for r in rows), "to": max(r["date"] for r in rows)}


def weekly(rows, hours):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["week"]].append(r)
    return {wk: summarize(by[wk], hours) for wk in sorted(by)}


def cut_date(rows):
    days = sorted(set(r["date"] for r in rows))
    return days[len(days) // 2] if len(days) >= 4 else None


def halves(rows, hours, cut=None):
    cut = cut_date(rows) if cut is None else cut
    if cut is None:
        return [None, None], None
    a = [r for r in rows if r["date"] < cut]
    b = [r for r in rows if r["date"] >= cut]
    return [summarize(a, hours), summarize(b, hours)], cut


def null_halves(rows, cut, seeds=SEEDS, fields=("edge", "edge_xs")):
    """Нуль: метка половины переставляется по ЧАСОВЫМ блокам, число часов в
    половинах то же. Возвращает на поле: наблюдаемую разность (1-я − 2-я)
    и долю перестановок с разностью ≥ наблюдаемой."""
    by_hour = collections.defaultdict(list)
    for r in rows:
        by_hour[float(r["at"])].append(r)
    ats = sorted(by_hour)
    first = [a for a in ats if date_of(a) < cut]
    n1 = len(first)
    out = {}
    for f in fields:
        v1 = [r[f] for a in first for r in by_hour[a] if r.get(f) is not None]
        v2 = [r[f] for a in ats if date_of(a) >= cut for r in by_hour[a] if r.get(f) is not None]
        if not v1 or not v2:
            out[f] = {"diff": None, "p": None, "n": 0}
            continue
        obs = _mean(v1) - _mean(v2)
        ge = 0
        for s_ in range(int(seeds)):
            rng = random.Random(1000 + s_)
            perm = list(ats)
            rng.shuffle(perm)
            p1 = set(perm[:n1])
            a_ = [r[f] for a in ats if a in p1 for r in by_hour[a] if r.get(f) is not None]
            b_ = [r[f] for a in ats if a not in p1 for r in by_hour[a] if r.get(f) is not None]
            if a_ and b_ and (_mean(a_) - _mean(b_)) >= obs:
                ge += 1
        out[f] = {"diff": obs, "p": ge / seeds, "n": seeds}
    return out


# ------------------------------------------------------------ касса

def cash_weeks(cache, ctx, launch, now=None, dep=MAIN_DEP, cut=None):
    """Взятые кассой позиции по книгам: неделя входа → число, $ нетто,
    цена в б.п. нотионала; то же по половинам."""
    packed = AG.packed_short(cache)
    rows = LC.cash_rows(packed, ctx, launch, now=now, dep=dep)
    out = {}
    for bk in BOOKS:
        wk, hv = collections.defaultdict(list), [[], []]
        for r in rows.get(bk) or []:
            try:
                m, lev, usd, at = float(r["margin"]), float(r["lev"]), float(r["usd"]), float(r["at"])
            except (TypeError, KeyError, ValueError):
                continue
            if not (m > 0 and lev > 0):
                continue
            item = {"usd": usd, "px_bp": usd / (m * lev) * 1e4, "date": date_of(at)}
            wk[week_of(at)].append(item)
            if cut:
                hv[0 if item["date"] < cut else 1].append(item)
        agg = lambda xs: (None if not xs else {"n": len(xs), "usd": sum(x["usd"] for x in xs),   # noqa: E731
                                               "px_bp": _mean([x["px_bp"] for x in xs])})
        out[bk] = {"weeks": {k: agg(v) for k, v in sorted(wk.items())},
                   "halves": [agg(hv[0]), agg(hv[1])]}
    return out


# ------------------------------------------------------------ суд

def judge(hv, null, cash, judge_books=JUDGE, p_limit=P_LIMIT, gap_bp=CASH_GAP_BP):
    """Вердикт из чисел по объявленному порядку."""
    a, b = hv
    if not a or not b:
        return {"kind": "unmeasured", "why": "половины окна не набираются"}
    if a.get("edge_xs") is None or b.get("edge_xs") is None:
        return {"kind": "unmeasured", "why": "кросс-секция не измерена хотя бы в одной половине "
                                             f"(часов с < {MIN_XS} именами слишком много)"}
    d_xs, d_e = null.get("edge_xs") or {}, null.get("edge") or {}
    fell_xs = (a.get("edge_xs") is not None and b.get("edge_xs") is not None
               and b["edge_xs"] < a["edge_xs"] and d_xs.get("p") is not None and d_xs["p"] <= p_limit)
    fell_e = (b["edge"] < a["edge"] and d_e.get("p") is not None and d_e["p"] <= p_limit)
    gaps = {}
    for bk in judge_books:
        ch = (cash.get(bk) or {}).get("halves") or [None, None]
        if ch[0] and ch[1] and ch[0].get("px_bp") is not None and ch[1].get("px_bp") is not None:
            gaps[bk] = [ch[0]["px_bp"] - a["edge"], ch[1]["px_bp"] - b["edge"]]
    widened = bool(gaps) and len(gaps) == len(judge_books) and all(
        g[1] < g[0] - gap_bp for g in gaps.values())
    if fell_xs:
        kind = "signal"
    elif fell_e:
        kind = "market"
    elif widened:
        kind = "cash"
    else:
        kind = "noise"
    return {"kind": kind, "fell_xs": fell_xs, "fell_raw": fell_e, "gaps": gaps,
            "widened": widened, "p_xs": d_xs.get("p"), "p_raw": d_e.get("p"),
            "edge": [a["edge"], b["edge"]], "edge_xs": [a.get("edge_xs"), b.get("edge_xs")],
            "wave": [a.get("wave"), b.get("wave")]}


def verdict(j):
    k = j.get("kind")
    f = lambda x: "—" if x is None else f"{x:+.0f}"                           # noqa: E731
    p = lambda x: "—" if x is None else f"{x:.2f}"                            # noqa: E731
    if k == "unmeasured":
        return f"не измерено: {j.get('why')}"
    e, x, w = j["edge"], j["edge_xs"], j["wave"]
    base = (f"сырой эдж {f(e[0])} → {f(e[1])} б.п. (p {p(j['p_raw'])}), над кросс-секцией "
            f"{f(x[0])} → {f(x[1])} б.п. (p {p(j['p_xs'])}), волна за 24 ч при входах {f(w[0])} → {f(w[1])} б.п.")
    if k == "signal":
        return "сигнал ослаб сам: " + base
    if k == "market":
        return "сигнал жив, шорты режет рынок: " + base
    if k == "cash":
        gs = "; ".join(f"{bk} разрыв {f(g[0])} → {f(g[1])}" for bk, g in j["gaps"].items())
        return "сигнал жив, убивает касса: " + base + f"; разрыв взятых против листа расширился ({gs})"
    return "второй половины как режима стенд не видит, разница в шуме: " + base


# ------------------------------------------------------------ прогон

def run(log=print, legs_=None, names=None, mkt=None, cache=None, ctx=None, launch=None,
        now=None, seeds=SEEDS, mem_limit=None, hold_h=HOLD_H, with_cash=True, min_xs=MIN_XS):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    legs_ = S.legs(log=log) if legs_ is None else legs_
    decs = decisions(legs_)
    log(f"решений (имя × час) {len(decs)} из {len(legs_)} ног")
    names = universe() if names is None else list(names)
    log(f"имён со сводками {len(names)}")
    mkt = W.Market() if mkt is None else mkt
    rows, hours, miss = measure(decs, mkt, names, hold_h=hold_h, seeds=seeds, min_xs=min_xs, log=log)
    if not rows:
        return {"error": "ни один выбор не измерен: нет цен в сводках", "miss": miss,
                "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}
    wk = weekly(rows, hours)
    hv, cut = halves(rows, hours)
    null = null_halves(rows, cut, seeds=seeds) if cut else {}
    total = summarize(rows, hours)
    cash = {}
    if with_cash:
        if cache is None:
            cache, why = S.read_cache(log=log)
            if why:
                log(f"касса не посчитана: {why}")
                cache = None
        if cache:
            ctx = ctx if ctx is not None else CO.context()
            launch = IR.launches() if launch is None else launch
            cash = cash_weeks(cache, ctx, launch, now=now, cut=cut)
            log("касса посчитана: " + ", ".join(
                f"{bk} позиций {sum((v or {}).get('n', 0) for v in cash[bk]['weeks'].values())}" for bk in BOOKS))
    j = judge(hv, null, cash)
    log(f"вердикт: {verdict(j)}")
    return {"hold_h": hold_h, "seeds": seeds, "p_limit": P_LIMIT, "cash_gap_bp": CASH_GAP_BP,
            "min_xs": min_xs, "dep": MAIN_DEP, "books": list(BOOKS), "judge_books": list(JUDGE),
            "n_legs": len(legs_), "n_decisions": len(decs), "n_names": len(names), "miss": miss,
            "total": total, "weeks": wk, "halves": hv, "cut": cut, "null": null,
            "cash": cash, "judge": j, "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ------------------------------------------------------------ отчёт

def _b(x):
    return "—" if x is None else f"{x:+.0f}"


def _pc(x):
    return "—" if x is None else f"{100 * x:.0f} %"


def _p2(x):
    return "—" if x is None else f"{x:.2f}"


def _usd(x):
    return "—" if x is None else f"{x:+,.0f}"


def _title(bk):
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная"}.get(bk, bk)


def _cash_week(s, bk, wk):
    v = ((s.get("cash") or {}).get(bk) or {}).get("weeks") or {}
    return (v.get(wk) or {}).get("usd") if wk in v else None


def _cash_total(s, bk):
    v = ((s.get("cash") or {}).get(bk) or {}).get("weeks")
    if not v:
        return None
    return sum((x or {}).get("usd", 0.0) for x in v.values())


def report(s):
    if s.get("error"):
        return f"# Эдж коротких выборов по неделям\n\n**Не измерено:** {s['error']}.\n"
    t = s["total"] or {}
    L_ = [f"# Эдж коротких выборов h24 по неделям: сигнал, рынок или касса", "",
          f"- решений {s['n_decisions']} из {s['n_legs']} ног обеих рук; имён в кросс-секции {s['n_names']}; "
          f"измерено {t.get('n')} выборов за {t.get('hours')} часов, {t.get('from')} … {t.get('to')}; "
          f"не измерено: без цены имени {s['miss']['no_price']}, часов без кросс-секции {s['miss']['no_xs']}, "
          f"без волны {s['miss']['no_wave']}; посчитано {s['computed_at']} за {s['secs']:.0f} с.",
          f"- мера — минус ход середины стакана за {s['hold_h']} ч, б.п. нотионала (шорт); «над кросс-секцией» — минус "
          f"средний ход всех имён с ценой в тот же час; «случайные» — выборы того же размера в тот же час, "
          f"{s['seeds']} зёрен (медиана и доля зёрен не хуже листа); волна — средний ход 20 прокси-имён за те же часы.",
          "", "| неделя | дней | часов | выборов | эдж, б.п. | медиана | попаданий | над кросс-секцией | случайные, медиана | зёрен ≥ листа | волна 24 ч, б.п. |"
          + "".join(f" {_title(bk)}, $ |" for bk in s["books"]),
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|" + "--:|" * len(s["books"])]
    for wk, v in s["weeks"].items():
        if not v:
            continue
        cells = "".join(f" {_usd(_cash_week(s, bk, wk))} |" for bk in s["books"])
        L_.append(f"| {wk} | {v['days']} | {v['hours']} | {v['n']} | {_b(v['edge'])} | {_b(v['edge_med'])} | {_pc(v['hit'])} | "
                  f"{_b(v['edge_xs'])} | {_b(v['rand_med'])} | {_pc(v['rand_ge'])} | {_b(v['wave'])} |" + cells)
    L_.append(f"| **всё окно** | {t['days']} | {t['hours']} | {t['n']} | {_b(t['edge'])} | {_b(t['edge_med'])} | {_pc(t['hit'])} | "
              f"{_b(t['edge_xs'])} | {_b(t['rand_med'])} | {_pc(t['rand_ge'])} | {_b(t['wave'])} |"
              + "".join(f" {_usd(_cash_total(s, bk))} |" for bk in s["books"]))
    a, b = s["halves"]
    L_ += ["", f"## Половины окна (граница {s['cut']}, нуль — перестановка метки половины по часовым блокам, {s['seeds']} перестановок)", "",
           "| половина | выборов | эдж, б.п. | попаданий | над кросс-секцией | случайные, медиана | волна 24 ч |"
           + "".join(f" {_title(bk)}: цена взятых, б.п. | $ |" for bk in s["books"]),
           "|---|--:|--:|--:|--:|--:|--:|" + "--:|--:|" * len(s["books"])]
    for i, h in enumerate((a, b)):
        if not h:
            L_.append(f"| {i + 1}-я | — | — | — | — | — | — |" + " — | — |" * len(s["books"]))
            continue
        cells = ""
        for bk in s["books"]:
            ch = ((s["cash"].get(bk) or {}).get("halves") or [None, None])[i] or {}
            cells += f" {_b(ch.get('px_bp'))} | {_usd(ch.get('usd'))} |"
        L_.append(f"| {i + 1}-я ({h['from']} … {h['to']}) | {h['n']} | {_b(h['edge'])} | {_pc(h['hit'])} | {_b(h['edge_xs'])} | "
                  f"{_b(h['rand_med'])} | {_b(h['wave'])} |" + cells)
    nl = s.get("null") or {}
    L_ += ["", "Нуль половин: " + "; ".join(
        f"{'сырой эдж' if f == 'edge' else 'над кросс-секцией'} — разность 1-я − 2-я {_b((nl.get(f) or {}).get('diff'))} б.п., "
        f"доля перестановок с разностью не меньше {_p2((nl.get(f) or {}).get('p'))}" for f in ("edge", "edge_xs")) + "."]
    L_ += ["", "## Вердикт (из чисел)", "", f"- {verdict(s['judge'])}", "",
           f"Порядок суда объявлен до прогона: над кросс-секцией упало с p ≤ {s['p_limit']:g} — сигнал; иначе сырой упал с p ≤ {s['p_limit']:g} — рынок; "
           f"иначе разрыв взятых кассой против листа расширился на ≥ {s['cash_gap_bp']:g} б.п. у обеих судимых книг — касса; иначе шум. "
           "Окно одно, веса модели эти часы видели; замер правил не меняет и ячеек не выбирает.", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--no-cash", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    log = lambda *x: print(*x, flush=True)                                   # noqa: E731
    s = run(log=log, seeds=a.seeds, with_cash=not a.no_cash)
    G.write(s, ART, report, log=log)
    if not a.no_publish:
        publish("эдж коротких выборов по неделям")


if __name__ == "__main__":
    main()
