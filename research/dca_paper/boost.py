#!/usr/bin/env python3
"""Разгонный профиль на маленьком депозите: $100, крупный билет — кассой.

Вопрос владельца 2026-10-04: «что можем смастерить высокорисковое для
разгона депозита под $100». Ответ стенда — не плечо (замер потолка
2026-10-03: эдж живёт в цене, плечо лишь делает деньги из эджа размером
с издержки и есть измеренный механизм хвоста), а КРУПНЫЙ БИЛЕТ на
конструкции с положительной записью вперёд — длинных DCA-книгах.

Оси объявлены здесь, до прогона, и не меняются:

- книги: `safe` и `optimal` (длинные; шорты закрыты D9/D10 — механизма
  дохода нет, aggr намеренно садится в хвостовую зону);
- депозит: $100; доля билета от ТЕКУЩЕГО счёта: 0.25 / 0.5 / 1.0.
  Доля, а не доллар: касса семейства и так считает маржу от текущего
  счёта, то есть билет растёт и проседает вместе с ним — это и есть
  геометрия разгона;
- якорь: та же книга на $1000 со ШТАТНЫМ билетом — сверка с
  опубликованной книгой и встроенный контроль подмены (отпечаток
  кассы обязан совпасть с расчётом без подмены бит в бит);
- окна: вся запись кэша и отдельно хвост с `rules.RULES_SINCE`
  (граница записи вперёд у самих книг);
- перестановки дней: 2000, зерно числом. Итог к порядку дней
  НЕЧУВСТВИТЕЛЕН (произведение множителей), перестановки отвечают
  только про ПУТЬ: P(просадка ≥ 50 %) и P(счёт ниже пола билета $25 —
  книга больше не может войти, разгон кончился);
- деньги ячейки — нетто (`costs.apply_to_rows`, как у страницы);
  кривая и просадка — брутто-касса семейства (издержки на лонгах
  5–9 б.п. маржи, клин печатается рядом).

Чего замер НЕ говорит: это пересчёт по записанному журналу одного
окна (сентябрь—октябрь, один режим рынка); 2000 перестановок меряют
чувствительность пути к порядку ТЕХ ЖЕ дней, а не будущее.

Вторая копия ядра не заводится: состав и касса — `run_paper.build_rows`
(гейт плеча, одна позиция на имя, очередь денег, минимальный ордер
биржи $5 на рунг), издержки — `costs.py`.

Запуск: run research/dca_paper/boost.py
"""
import argparse
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_grid as G                                        # noqa: E402

ART = "DCA-boost-100"
BOOKS = ("safe", "optimal")
DEP = 100.0
SHARES = (0.25, 0.5, 1.0)
ANCHOR_DEP = 1000.0
SEEDS = 2000
SEED0 = 20261004
DD_LIM = 0.5                     # «глубокая просадка» разгона
FLOOR_USD = R.TICKET_MIN         # счёт ниже пола билета — входить нечем


def with_overrides(deposits, share, fn):
    """Депозиты и доля билета на время счёта — и назад, что бы ни было.

    `share=None` оставляет ШТАТНОЕ правило билета — так считается якорь
    и так проверяется сама подмена (её отсутствие обязано быть
    тождественно штатному пути).
    """
    was_dep, was_share = R.DEPOSITS, R.share_in
    R.DEPOSITS = list(deposits)
    if share is not None:
        R.share_in = lambda _pk, _bk, _dep, _s=float(share): _s
    try:
        return fn()
    finally:
        R.DEPOSITS, R.share_in = was_dep, was_share


def day_series(rows):
    """Деньги по дням выхода: (день, брутто $, нетто $), дни по UTC."""
    by = {}
    for r in rows:
        d = time.strftime("%Y-%m-%d", time.gmtime(float(r["exit_ts"])))
        g, n = by.setdefault(d, [0.0, 0.0])
        by[d][0] = g + float(r.get("usd_gross", r.get("usd") or 0.0))
        by[d][1] = n + float(r.get("usd") or 0.0)
    return [(d, by[d][0], by[d][1]) for d in sorted(by)]


def geo_days(gross_by_day, deposit):
    """Дневные ДОЛИ текущего счёта и меры пути по дневной кривой.

    Касса меняет счёт ровно на деньги закрывшихся позиций, поэтому
    дневная кривая — точная (по дням) реконструкция кассы; внутридневная
    просадка тут не видна, и это названо в отчёте.
    """
    eq, peak, dd, min_eq, fracs = float(deposit), float(deposit), 0.0, float(deposit), []
    for _d, g, _n in gross_by_day:
        fracs.append(g / eq if eq > 0 else 0.0)
        eq += g
        min_eq = min(min_eq, eq)
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, 1.0 - eq / peak)
    return {"fracs": fracs, "final": eq / float(deposit) - 1.0,
            "max_dd_day": dd, "min_eq": min_eq}


def perm_probs(fracs, deposit, seeds=SEEDS, seed0=SEED0,
               dd_lim=DD_LIM, floor_usd=FLOOR_USD):
    """Путь на перестановках ТЕХ ЖЕ дней: просадка и пол билета.

    Итог у всех перестановок один (произведение), поэтому он не
    считается заново; меряется только чувствительность пути к порядку.
    """
    if not fracs:
        return None
    hit_dd = hit_floor = 0
    for i in range(int(seeds)):
        xs = list(fracs)
        random.Random(seed0 + i).shuffle(xs)
        eq, peak, dd, mn = float(deposit), float(deposit), 0.0, float(deposit)
        for f in xs:
            eq *= (1.0 + f)
            mn = min(mn, eq)
            peak = max(peak, eq)
            if peak > 0:
                dd = max(dd, 1.0 - eq / peak)
        hit_dd += bool(dd >= dd_lim)
        hit_floor += bool(mn < floor_usd)
    return {"p_dd": hit_dd / float(seeds), "p_floor": hit_floor / float(seeds)}


def cell(packed, rk, dep, share, ctx, since=None, log=print):
    """Одна ячейка: состав и касса — build_rows, деньги — нетто."""
    sub = {rk: ([r for r in packed[rk] if float(r["at"]) >= float(since)]
                if since else list(packed[rk]))}
    rows, cells, one, _live = with_overrides(
        [dep], share, lambda: RP.build_rows(sub, log=lambda *_: None,
                                            keys=[rk]))
    c = dict(cells.get(f"{rk}:{int(dep)}") or {})
    rs = [r for r in rows if r.get("ruler") == rk]
    rs, cost_sum = CO.apply_to_rows(rs, ctx)
    days = day_series(rs)
    geo = geo_days(days, dep)
    bysym = {}
    for r in rs:
        bysym[r["sym"]] = bysym.get(r["sym"], 0.0) + float(r.get("usd") or 0.0)
    net = sum(bysym.values())
    gross = sum(float(r.get("usd_gross", r.get("usd") or 0.0)) for r in rs)
    top = max(bysym, key=bysym.get) if bysym else None
    day_net = sorted(x[2] for x in days)
    return {
        "book": rk, "dep": dep, "share": share,
        "ticket": (round(dep * share, 2) if share else c.get("ticket")),
        "n": len(rs), "taken": c.get("taken"), "no_cash": c.get("no_cash"),
        "too_small": c.get("too_small"), "fp": c.get("fp"),
        "final": c.get("final"), "max_dd": c.get("max_dd"),
        "final_day": round(geo["final"], 4),
        "max_dd_day": round(geo["max_dd_day"], 4),
        "min_eq": round(geo["min_eq"], 2),
        "net_usd": round(net, 2), "gross_usd": round(gross, 2),
        "cost_usd": round(gross - net, 2),
        "costs_applied": cost_sum.get("applied"),
        "days": len(days),
        "day_median_net": (round(day_net[len(day_net) // 2], 2)
                           if day_net else None),
        "day_worst_net": (round(day_net[0], 2) if day_net else None),
        "top_sym": top,
        "net_wo_top": (round(net - bysym[top], 2) if top else None),
        "perm": perm_probs(geo["fracs"], dep),
    }


def run(log=print, cache=None, ctx=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    if cache is None:
        cache, why = RP.read_cache()
        if why:
            return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    by_pair = {}
    for (pair, _sym, _at), r in cache.items():
        by_pair.setdefault(pair, []).append(r)
    packed = {rk: list(by_pair.get(tuple(RP.RULERS[rk])) or [])
              for rk in BOOKS}
    for rk in BOOKS:
        log(f"{rk}: записей в кэше {len(packed[rk])}")
        if not packed[rk]:
            return {"error": f"в кэше нет записей книги {rk} — не та машина?"}

    # Контроль подмены: доля None (штатный путь) обязана дать ТОТ ЖЕ
    # отпечаток кассы, что расчёт вовсе без подмены, — бит в бит.
    rk0 = BOOKS[0]
    a_sub = cell(packed, rk0, ANCHOR_DEP, None, ctx, log=log)
    rows0, cells0, _one0, _l0 = RP.build_rows(
        {rk0: packed[rk0]}, log=lambda *_: None, keys=[rk0])
    fp0 = (cells0.get(f"{rk0}:{int(ANCHOR_DEP)}") or {}).get("fp")
    if a_sub.get("fp") != fp0:
        return {"error": f"подмена нетождественна штатному пути: "
                         f"{a_sub.get('fp')} против {fp0}"}

    out = {"anchors": {}, "cells": [], "fwd": []}
    for rk in BOOKS:
        out["anchors"][rk] = cell(packed, rk, ANCHOR_DEP, None, ctx, log=log)
        for sh in SHARES:
            log(f"ячейка {rk} доля {sh:g}")
            out["cells"].append(cell(packed, rk, DEP, sh, ctx, log=log))
            out["fwd"].append(cell(packed, rk, DEP, sh, ctx,
                                   since=R.RULES_SINCE, log=log))
    out.update({
        "dep": DEP, "shares": list(SHARES), "books": list(BOOKS),
        "seeds": SEEDS, "seed0": SEED0, "dd_lim": DD_LIM,
        "floor_usd": float(FLOOR_USD),
        "since": float(R.RULES_SINCE),
        "since_h": time.strftime("%Y-%m-%d %H:%M UTC",
                                 time.gmtime(R.RULES_SINCE)),
        "costs_error": (ctx or {}).get("error"),
        "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)})
    return out


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _p0(x):
    return "—" if x is None else f"{100.0 * float(x):.1f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.2f} $"


def _row(c):
    pm = c.get("perm") or {}
    t = "штатный" if c.get("share") is None else f"{c.get('ticket')} $"
    return (f"| {c['book']} | {t} | {c.get('n', '—')} "
            f"| {c.get('no_cash', '—')} / {c.get('too_small', '—')} "
            f"| {_pp(c.get('final'))} | {_pp(c.get('max_dd'))} "
            f"| {_usd(c.get('net_usd'))} | {_usd(c.get('cost_usd'))} "
            f"| {_usd(c.get('net_wo_top'))} "
            f"| {_usd(c.get('day_worst_net'))} "
            f"| {_p0(pm.get('p_dd'))} | {_p0(pm.get('p_floor'))} |")


HEAD = ("| книга | билет | сделок | отказов кассы / мельче $5 | итог "
        "(брутто-касса) | просадка | $ нетто | издержки | без топ-имени "
        "| худший день | P(просадка ≥ 50 %) | P(счёт < 25 $) |")
SEP = "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"


def report(s):
    L = ["# Разгонный профиль: $100 и крупный билет — кассой", "",
         "Вопрос владельца 2026-10-04. Оси объявлены до прогона: книги "
         "safe и optimal, депозит $100, доля билета от текущего счёта "
         "0.25 / 0.5 / 1.0; состав и касса — `run_paper.build_rows` "
         "(гейт плеча, одна позиция на имя, очередь денег, минимальный "
         "ордер $5 на рунг), деньги нетто (`costs.apply_to_rows`). "
         f"Перестановки {s.get('seeds')} дней отвечают только про ПУТЬ: "
         "итог от порядка дней не зависит. Просадка перестановок — по "
         "ДНЯМ: внутридневная глубина в ней не видна, честная часовая "
         "просадка стоит в колонке кассы.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой "
              "части.", ""]
    L += ["## Якорь: той же сборкой на $1000 со штатным билетом", "",
          "Сверка с опубликованной книгой (/dca-page) — расхождение здесь "
          "означает, что реплей описывает не ту книгу.", "", HEAD, SEP]
    for rk in s.get("books") or []:
        a = (s.get("anchors") or {}).get(rk)
        if a:
            L.append(_row(a))
    L += ["", "## $100: вся запись кэша", "", HEAD, SEP]
    L += [_row(c) for c in s.get("cells") or []]
    L += ["", f"## $100: хвост с {s.get('since_h')} — окно записи "
          "вперёд самих книг", "", HEAD, SEP]
    L += [_row(c) for c in s.get("fwd") or []]
    if any(c.get("share") == 1.0 for c in (s.get("cells") or [])):
        L += ["", "**Ячейки с долей 1.0 не измерены, и это свойство КАССЫ "
              "семейства, а не стратегии.** Касса возвращает в свободные "
              "деньги МАРЖУ, а прибыль зачисляет только в счёт: после "
              "первой же прибыльной сделки билет размером в целый счёт "
              "всегда больше свободных денег, и вход блокируется навсегда "
              "(видно числом: одна сделка при тысячах отказов кассы). У "
              "штатных билетов (2.5 % счёта) расхождение свободных денег "
              "со счётом микроскопично, но оно систематическое — решение "
              "о правке ядра кассы за владельцем: это смена версии правил "
              "всех книг семейства.", ""]
    L += ["", "## Как читать", "",
          "- «Отказов кассы» у крупного билета — это и есть цена "
          "концентрации: решения, на которые не хватило счёта; «мельче "
          "$5» — рунги, которые биржа не примет.",
          f"- P(счёт < {int(s.get('floor_usd') or FLOOR_USD)} $) — доля "
          "перестановок, где счёт падал ниже пола билета: входить дальше "
          "нечем, разгон закончился сам.",
          "- Один режим рынка, одно окно записи; перестановки меряют "
          "порядок тех же дней, а не будущее.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("разгонный профиль: 100 долларов и крупный билет")


if __name__ == "__main__":
    main()
