#!/usr/bin/env python3
"""Правило выбора позиций при полной кассе: кто получает место, когда
кандидатов больше, чем денег.

Повод (06.10, `cost_gap`): отбор кассой стоит коротким книгам −15…−19 б.п.
в цене — записи, которые касса реально берёт, вдвое хуже листа. Правило
сейчас (`run_d6.queue`): внутри секунды решения первым к деньгам идёт
больший |прогноз| модели. Вопрос владельца: есть ли правило лучше.

Оси объявлены до прогона — ключ порядка внутри секунды:
  fwd      как сейчас: больший прогноз первым (опора);
  fwd_rev  меньший прогноз первым — контроль информативности прогноза:
           если он не хуже опоры, порядок по прогнозу ничего не знает;
  rr       больший обещанный RR первым;
  lev_lo   меньшее плечо забора первым;   lev_hi  большее первым;
  fund     ставка funding на входе выгоднее шорту первым (шорт получает
           положительную ставку) — издержка, которую cost_gap назвал
           главной (8–10 б.п.);
  random   случайный порядок внутри секунды, 200 зёрен — нуль.

Судится касса $10k нетто (тем же ядром, что прогон книг): доход/просадка
и итог против случайного порядка; правило — рычаг, если случайный порядок
не хуже его не более чем у 5 % зёрен по обеим величинам у оптимальной и
агрессивной книг. Право на итерацию одно. Рядом — мера спора: сколько
решений приходится на секунды, где кандидатов больше, чем мест: порядок
может двигать только их.

Правила книг не меняются; меняется только ключ очереди за деньгами,
объявленный в ядре отдельной функцией ровно затем, чтобы его можно было
подменить и измерить.

    run research/dca_paper/pick_rule.py
"""
import argparse
import contextlib
import os
import random
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
import run_paper as RP                                        # noqa: E402
import run_d6 as D6                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_levers as L                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-pick-rule"
MAIN_DEP = 10000
BOOK_KEYS = list(S.BOOKS)
SEEDS = 200
JUDGE_BOOKS = ("optimal_h", "aggr_h")
BEAT_MAX = 0.05


def fund_key(r, ctx):
    """Ставка funding на входе: выгоднее шорту (больше) — первым; нет
    ряда — в конец очереди, а не в начало."""
    if not ctx or ctx.get("error"):
        return float("inf")
    asset = (ctx.get("to_asset") or {}).get(r.get("sym"))
    series = (ctx.get("funding") or {}).get(asset) if asset else None
    rate = CO.rate_at_entry(series, r.get("at"))
    return float("inf") if rate is None else -float(rate)


RULES = {
    "fwd": lambda r, ctx: -float(r.get("fwd") or 0.0),
    "fwd_rev": lambda r, ctx: float(r.get("fwd") or 0.0),
    "rr": lambda r, ctx: -float(r.get("rr") or 0.0),
    "lev_lo": lambda r, ctx: float(r.get("lev") or 0.0),
    "lev_hi": lambda r, ctx: -float(r.get("lev") or 0.0),
    "fund": fund_key,
}
TITLES = {"fwd": "как сейчас: больший прогноз первым",
          "fwd_rev": "меньший прогноз первым (контроль)",
          "rr": "больший RR первым", "lev_lo": "меньшее плечо первым",
          "lev_hi": "большее плечо первым",
          "fund": "ставка funding выгоднее шорту первым",
          "random": "случайный порядок (нуль, 200 зёрен)"}


def rec_key(r):
    return (r.get("sym"), round(float(r["at"]), 3))


@contextlib.contextmanager
def with_queue(key_fn):
    """Подменить ключ очереди ядра на время счёта и вернуть обратно."""
    was = D6.queue

    def q(recs):
        return sorted(recs, key=lambda r: (int(r["at"]), key_fn(r)))
    D6.queue = q
    try:
        yield
    finally:
        D6.queue = was


def random_key(packed, seed):
    """Случайный, но воспроизводимый ключ на запись: одно зерно — один порядок."""
    rnd = random.Random(seed)
    keys = sorted({rec_key(r) for recs in packed.values() for r in recs})
    salt = {k: rnd.random() for k in keys}
    return lambda r: salt.get(rec_key(r), 0.5)


def candidates_by_second(recs, book):
    """Кандидаты книги по секундам решения — после гейта плеча."""
    ml = R.min_lev_of(book)
    out = {}
    for r in recs:
        if (r.get("state") or "closed") != "closed":
            continue
        if ml is not None and float(r.get("lev") or 0) < float(ml):
            continue
        out.setdefault(int(float(r["at"])), []).append(r)
    return out


def contested(recs, rows, book):
    """Мера спора: секунды, где кандидатов больше взятых; доля взятых в них."""
    cand = candidates_by_second(recs, book)
    taken = {}
    for row in rows:
        taken.setdefault(int(float(row["at"])), []).append(row)
    secs = [s for s, c in cand.items() if len(c) >= 2 and len(taken.get(s, ())) < len(c)]
    n_taken = sum(len(v) for v in taken.values())
    in_contest = sum(len(taken.get(s, ())) for s in secs)
    return {"seconds_total": len(cand), "seconds_contested": len(secs),
            "candidates_total": sum(len(c) for c in cand.values()),
            "candidates_in_contest": sum(len(cand[s]) for s in secs),
            "taken": n_taken, "taken_in_contest": in_contest,
            "share_taken_in_contest": (in_contest / n_taken) if n_taken else None}


def taken_edge(rows):
    """Эдж взятых в цене, равный вес: нетто $ на нотионал, б.п."""
    vals = []
    for r in rows:
        try:
            m, lev, usd = float(r["margin"]), float(r["lev"]), float(r["usd"])
        except (TypeError, KeyError, ValueError):
            continue
        if m > 0 and lev > 0:
            vals.append(usd / (m * lev) * 1e4)
    return (sum(vals) / len(vals)) if vals else None


def cell_rows(packed, ctx, launch, now=None, dep=MAIN_DEP):
    """Строки кассы по книгам (нетто) — тем же порядком, что `cell_stats`."""
    ruled = L.ruled(packed, launch, now=now)
    rows, cells_, _o, _l = RP.build_rows(ruled, now=now, keys=BOOK_KEYS, log=lambda *a: None)
    out = {}
    for bk in BOOK_KEYS:
        mine = [r for r in rows if R.ruler_of(r) == bk and int(r.get("dep", 0)) == int(dep)]
        if ctx is not None and not ctx.get("error"):
            mine, _n = CO.apply_to_rows(mine, ctx)
        out[bk] = (mine, cells_.get(RP._cell(bk, dep)) or {})
    return out


def run(log=print, now=None, launch=None, ctx=None, mem_limit=None, dep=MAIN_DEP,
        seeds=SEEDS, rules=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    packed = AG.packed_short(cache)
    rules = dict(RULES if rules is None else rules)
    cells, edge, contest = {}, {}, {}
    for name, key in rules.items():
        with with_queue(lambda r, _k=key: _k(r, ctx)):
            st = AG.stats_of(packed, ctx, launch, BOOK_KEYS, deps=[dep], now=now)
            rows = cell_rows(packed, ctx, launch, now=now, dep=dep)
        cells[name] = {bk: L.summ(st.get(f"{bk}:{int(dep)}") or {}) for bk in BOOK_KEYS}
        edge[name] = {bk: taken_edge(rows[bk][0]) for bk in BOOK_KEYS}
        if name == "fwd":
            contest = {bk: dict(contested(packed.get(bk) or [], rows[bk][0], bk),
                                no_cash=rows[bk][1].get("no_cash"),
                                take_share=rows[bk][1].get("take_share"))
                       for bk in BOOK_KEYS}
        log(f"правило {name}: " + ", ".join(
            f"{bk} {cells[name][bk].get('ratio_day') or cells[name][bk].get('final')}"
            for bk in BOOK_KEYS) + f" ({time.time() - t0:.0f} с)")
    draws = {bk: [] for bk in BOOK_KEYS}
    for i in range(int(seeds)):
        with with_queue(random_key(packed, 7000 + i)):
            st = AG.stats_of(packed, ctx, launch, BOOK_KEYS, deps=[dep], now=now)
        for bk in BOOK_KEYS:
            c = st.get(f"{bk}:{int(dep)}") or {}
            draws[bk].append({"final": c.get("final"), "ratio": c.get("ratio"), "n": c.get("n")})
        if i and i % 25 == 0:
            log(f"случайный порядок: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    beat = {}
    for name in rules:
        beat[name] = {}
        for bk in BOOK_KEYS:
            c = cells[name][bk]
            ratio = (None if not c.get("final") or not c.get("max_dd")
                     else round(float(c["final"]) / abs(float(c["max_dd"])), 2))
            beat[name][bk] = {"final": AG.beat_share(draws[bk], c.get("final"), "final")[0],
                              "ratio": AG.beat_share(draws[bk], ratio, "ratio")[0],
                              "ratio_value": ratio}
    rnd_summary = {bk: {"final_med": _median([d["final"] for d in draws[bk] if d["final"] is not None]),
                        "ratio_med": _median([d["ratio"] for d in draws[bk] if d["ratio"] is not None]),
                        "n": len(draws[bk])} for bk in BOOK_KEYS}
    return {"dep": dep, "books": BOOK_KEYS, "rules": list(rules), "titles": TITLES,
            "cells": cells, "edge": edge, "beat": beat, "contest": contest,
            "random": rnd_summary, "seeds": int(seeds), "judge_books": list(JUDGE_BOOKS),
            "beat_max": BEAT_MAX,
            "verdict": {name: verdict(beat[name]) for name in rules},
            "diag": {"records": len(cache)},
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _median(xs):
    xs = sorted(xs)
    return None if not xs else xs[len(xs) // 2]


def verdict(beat_rule):
    """Рычаг — случайный порядок не хуже правила ≤ 5 % зёрен по обеим
    величинам у ОБЕИХ судимых книг; иначе — словами, что именно не так."""
    parts = []
    ok = True
    for bk in JUDGE_BOOKS:
        b = (beat_rule or {}).get(bk) or {}
        bf, br = b.get("final"), b.get("ratio")
        if bf is None or br is None:
            parts.append(f"{bk}: не измерено")
            ok = False
            continue
        word = L.verdict_sel({"final": bf, "ratio": br})
        parts.append(f"{bk}: {word} (итог {bf:.0%}, доход/просадка {br:.0%} зёрен не хуже)")
        if not (bf <= BEAT_MAX and br <= BEAT_MAX):
            ok = False
    return ("РЫЧАГ: " if ok else "не рычаг: ") + "; ".join(parts)


# ---------------------------------------------------------------- отчёт
def _p(x, d=1):
    return "—" if x is None else f"{100 * float(x):+.{d}f} %"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _b(x, d=1):
    return "—" if x is None else f"{float(x):+.{d}f}"


def _n(x):
    return "—" if x is None else f"{int(x)}"


def _share(x):
    return "—" if x is None else f"{100 * float(x):.0f} %"


def _title(bk):
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная"}.get(bk, bk)


def report(s):
    if s.get("error"):
        return f"# Правило выбора позиций при полной кассе\n\nОШИБКА: {s['error']}\n"
    L_ = ["# Правило выбора позиций при полной кассе: кто получает место, когда кандидатов больше, чем денег",
          "",
          f"Касса ${s['dep']:,} нетто, записей реплея {s['diag']['records']}; случайный порядок — {s['seeds']} зёрен; "
          f"посчитано {s['computed_at']} за {s['secs']} с. Судимые книги: оптимальная и агрессивная; "
          f"рычаг — случайный порядок не хуже правила не более чем у {s['beat_max']:.0%} зёрен по итогу и по доходу/просадке.",
          "", "## Мера спора (при правиле как сейчас)", "",
          "| книга | секунд решения | из них спорных | кандидатов | в спорных | взято | взято в спорных | доля | отказов «нет кассы» |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in s["books"]:
        c = (s.get("contest") or {}).get(bk) or {}
        L_.append(f"| {_title(bk)} | {_n(c.get('seconds_total'))} | {_n(c.get('seconds_contested'))} | "
                  f"{_n(c.get('candidates_total'))} | {_n(c.get('candidates_in_contest'))} | {_n(c.get('taken'))} | "
                  f"{_n(c.get('taken_in_contest'))} | {_share(c.get('share_taken_in_contest'))} | {_n(c.get('no_cash'))} |")
    L_ += ["", "Порядок внутри секунды решает только судьбу позиций в спорных секундах; остальные касса берёт при любом правиле.", ""]
    for bk in s["books"]:
        rs = s["random"][bk]
        L_ += [f"## {_title(bk)}", "",
               f"Случайный порядок: медиана итога {_p(rs['final_med'])}, доход/просадка {_f(rs['ratio_med'])} ({rs['n']} зёрен).", "",
               "| правило | сделок | итог | просадка | доход/просадка | без 3 дней, $ | σ дня, $ | эдж взятых в цене, б.п. | зёрен не хуже: итог | доход/просадка |",
               "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for name in s["rules"]:
            c = s["cells"][name][bk]
            b = s["beat"][name][bk]
            L_.append(f"| {s['titles'].get(name, name)} | {_n(c.get('n'))} | {_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                      f"{_f(b.get('ratio_value'))} | {_n(c.get('wo3'))} | {_n(c.get('sigma_day'))} | "
                      f"{_b(s['edge'][name][bk])} | {_share(b.get('final'))} | {_share(b.get('ratio'))} |")
        L_.append("")
    L_ += ["## Вердикт (из чисел)", ""]
    for name in s["rules"]:
        L_.append(f"- {s['titles'].get(name, name)}: {s['verdict'][name]}")
    L_ += ["", "Чего замер не делает: не меняет правила книг; не судит направление; правило-рычаг, если найдётся, "
           "входит в ядро только решением владельца и с записью вперёд.", ""]
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
    s = run(log=print, seeds=a.seeds)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("правило выбора позиций при полной кассе: порядок внутри секунды против случайного")


if __name__ == "__main__":
    main()
