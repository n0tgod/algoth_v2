#!/usr/bin/env python3
"""Пропустить первый вход: насколько «ювелирны» второй, третий, четвёртый
выбор имени моделью — и что это даёт кассе.

Вопрос владельца (06.10): если модель, выбирающая то же имя второй и
третий час подряд, права чаще и сильнее, чем в первый раз (замеры
`cost_gap` и `pick_rule`: повторные выборы в цене +43…54 б.п. против
первых +19…31), что будет, если входить ТОЛЬКО по повторам.

Оси объявлены до прогона. Номер входа k по имени — как у правила «одна
на имя»: k = 1 первый выбор имени; k = 2, 3, 4… — выборы того же имени,
пока позиция первого выбора ещё открыта (ровно те записи, которые касса
сейчас пропускает); после выхода счёт начинается заново. Два выбора
одного имени в одну секунду (обе руки) — одна запись, с большим
прогнозом, как в ядре.

  по записям (равный вес, издержки реплея): n, доля плюсовых, средний
      выигрыш и проигрыш, RR, ожидание в марже и в цене — по k = 1, 2,
      3, 4, 5+ и по k ≥ 2 целиком;
  по кассе $10k нетто (тем же ядром, что прогон книг): книга «как
      сейчас» (k = 1), «пропустить первый» (k ≥ 2: входит второй выбор,
      дальнейшие отсекает «одна на имя»), «пропустить два» (k ≥ 3);
  нуль — случайные подмножества записей ТОГО ЖЕ размера, 200 зёрен:
      фильтр, режущий число сделок, сравнивается только так.

Рычаг — «пропустить первый» лучше книги «как сейчас» по доходу/просадке
и не хуже ≥ 95 % случайных подмножеств по итогу и доходу/просадке у
оптимальной и агрессивной. Право на итерацию одно. Правила книг не
меняются; замер читает кэш реплея.

    run research/dca_paper/repeat_entry.py
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
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_levers as L                                      # noqa: E402
import short_levcap as V                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-repeat-entry"
MAIN_DEP = 10000
BOOK_KEYS = list(S.BOOKS)
SEEDS = 200
JUDGE_BOOKS = ("optimal_h", "aggr_h")
BEAT_MAX = 0.05
K_BANDS = ("1", "2", "3", "4", "5+")
CELLS = (("k1", "как сейчас: первый выбор имени", lambda k: k == 1),
         ("k2plus", "пропустить первый: входит второй выбор", lambda k: k >= 2),
         ("k3plus", "пропустить два: входит третий выбор", lambda k: k >= 3))


def band_of(k):
    return "5+" if k >= 5 else str(int(k))


def label(recs):
    """Записи книги с номером входа `k` по имени (см. модуль).

    Закрытые записи; две записи одного имени в одну секунду — одна (с
    большим прогнозом). Возвращает список копий записей с полем `k`.
    """
    closed = [r for r in recs if (r.get("state") or "closed") == "closed"
              and r.get("pnl_net") is not None and float(r.get("lev") or 0) > 0]
    closed.sort(key=lambda r: (int(float(r["at"])), -float(r.get("fwd") or 0.0)))
    seen, uniq = set(), []
    for r in closed:
        key = (r.get("sym"), int(float(r["at"])))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    open_until, k_of, out = {}, {}, []
    for r in uniq:
        sym, at = r.get("sym"), int(float(r["at"]))
        until = open_until.get(sym)
        if until is not None and at < until:
            k = k_of[sym] + 1
        else:
            k = 1
            open_until[sym] = int(float(r["exit_ts"]))
        k_of[sym] = k
        out.append(dict(r, k=k))
    return out


def by_k(labeled, book):
    """Статистика записей по номеру входа — тем же `trade_stats`, что у потолка плеча."""
    out = {}
    for name in K_BANDS:
        sub = [r for r in labeled if band_of(r["k"]) == name]
        out[name] = V.trade_stats(V.record_pairs(sub, book))
    out["2+"] = V.trade_stats(V.record_pairs([r for r in labeled if r["k"] >= 2], book))
    out["all"] = V.trade_stats(V.record_pairs(labeled, book))
    return out


def subset(packed, pred):
    """Записи книг, чей номер входа проходит `pred` — состав для кассы."""
    out = {}
    for bk, recs in packed.items():
        out[bk] = [r for r in label(recs) if pred(r["k"])]
    return out


def random_subsets(packed, sizes, ctx, launch, seeds=SEEDS, dep=MAIN_DEP, now=None, log=print):
    """Случайные подмножества записей ТОГО ЖЕ размера на книгу — нуль фильтра."""
    draws = {bk: [] for bk in BOOK_KEYS}
    base = {bk: label(packed.get(bk) or []) for bk in BOOK_KEYS}
    t0 = time.time()
    for i in range(int(seeds)):
        rnd = random.Random(9000 + i)
        sub = {}
        for bk in BOOK_KEYS:
            n = int(sizes.get(bk) or 0)
            pool = base[bk]
            sub[bk] = list(pool) if n >= len(pool) else rnd.sample(pool, n)
        st = AG.stats_of(sub, ctx, launch, BOOK_KEYS, deps=[dep], now=now)
        for bk in BOOK_KEYS:
            c = st.get(f"{bk}:{int(dep)}") or {}
            draws[bk].append({"final": c.get("final"), "ratio": c.get("ratio"), "n": c.get("n")})
        if i and i % 50 == 0:
            log(f"случайные подмножества: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    return draws


def cash_cell(sub, ctx, launch, dep=MAIN_DEP, now=None):
    st = AG.stats_of(sub, ctx, launch, BOOK_KEYS, deps=[dep], now=now)
    return {bk: L.summ(st.get(f"{bk}:{int(dep)}") or {}) for bk in BOOK_KEYS}


def ratio_of(c):
    return (None if not c or not c.get("final") or not c.get("max_dd")
            else round(float(c["final"]) / abs(float(c["max_dd"])), 2))


def verdict(cells, beat):
    """Из чисел: «пропустить первый» против книги как сейчас и против случайных."""
    parts, ok = [], True
    for bk in JUDGE_BOOKS:
        now_, skip = cells["k1"][bk], cells["k2plus"][bk]
        r_now, r_skip = ratio_of(now_), ratio_of(skip)
        b = (beat.get("k2plus") or {}).get(bk) or {}
        bf, br = b.get("final"), b.get("ratio")
        if r_now is None or r_skip is None or bf is None or br is None:
            parts.append(f"{bk}: не измерено")
            ok = False
            continue
        better = r_skip > r_now
        word = L.verdict_sel({"final": bf, "ratio": br})
        parts.append(f"{bk}: доход/просадка {r_skip:.2f} против {r_now:.2f} как сейчас, "
                     f"{word} (итог {bf:.0%}, доход/просадка {br:.0%} зёрен не хуже)")
        if not (better and bf <= BEAT_MAX and br <= BEAT_MAX):
            ok = False
    return ("РЫЧАГ: " if ok else "не рычаг: ") + "; ".join(parts)


def run(log=print, now=None, launch=None, ctx=None, mem_limit=None, dep=MAIN_DEP, seeds=SEEDS):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    packed = AG.packed_short(cache)
    records = {}
    for bk in BOOK_KEYS:
        lab = label(packed.get(bk) or [])
        records[bk] = {"n": len(lab), "by_k": by_k(lab, bk),
                       "share_k": {name: sum(1 for r in lab if band_of(r["k"]) == name) / len(lab)
                                   for name in K_BANDS} if lab else {}}
    cells, sizes = {}, {}
    for key, _title, pred in CELLS:
        sub = subset(packed, pred)
        sizes[key] = {bk: len(sub[bk]) for bk in BOOK_KEYS}
        cells[key] = cash_cell(sub, ctx, launch, dep=dep, now=now)
        log(f"{key}: записей " + ", ".join(f"{bk} {sizes[key][bk]}" for bk in BOOK_KEYS)
            + "; доход/просадка " + ", ".join(f"{bk} {ratio_of(cells[key][bk])}" for bk in BOOK_KEYS)
            + f" ({time.time() - t0:.0f} с)")
    beat = {}
    for key, _title, _pred in CELLS[1:]:
        draws = random_subsets(packed, sizes[key], ctx, launch, seeds=seeds, dep=dep, now=now, log=log)
        beat[key] = {}
        for bk in BOOK_KEYS:
            c = cells[key][bk]
            beat[key][bk] = {"final": AG.beat_share(draws[bk], c.get("final"), "final")[0],
                             "ratio": AG.beat_share(draws[bk], ratio_of(c), "ratio")[0],
                             "random_final_med": _median([d["final"] for d in draws[bk] if d["final"] is not None]),
                             "random_ratio_med": _median([d["ratio"] for d in draws[bk] if d["ratio"] is not None])}
    return {"dep": dep, "books": BOOK_KEYS, "cells": [(k, t) for k, t, _p in CELLS],
            "records": records, "cash": cells, "sizes": sizes, "beat": beat,
            "seeds": int(seeds), "judge_books": list(JUDGE_BOOKS), "beat_max": BEAT_MAX,
            "verdict": verdict(cells, beat), "k_bands": list(K_BANDS),
            "diag": {"records": len(cache)}, "computed_at": G.stamp(),
            "secs": round(time.time() - t0, 1)}


def _median(xs):
    xs = sorted(xs)
    return None if not xs else xs[len(xs) // 2]


# ---------------------------------------------------------------- отчёт
def _p(x, d=1):
    return "—" if x is None else f"{100 * float(x):+.{d}f} %"


def _pp(x):
    return "—" if x is None else f"{100 * float(x):.0f} %"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _bp(x):
    return "—" if x is None else f"{1e4 * float(x):+.1f} б.п."


def _n(x):
    return "—" if x is None else f"{int(x)}"


def _title(bk):
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная"}.get(bk, bk)


def report(s):
    if s.get("error"):
        return f"# Пропустить первый вход\n\nОШИБКА: {s['error']}\n"
    L_ = ["# Пропустить первый вход: насколько ювелирны второй, третий и четвёртый выбор имени",
          "",
          f"Касса ${s['dep']:,} нетто, записей реплея {s['diag']['records']}; случайные подмножества того же размера — "
          f"{s['seeds']} зёрен; посчитано {s['computed_at']} за {s['secs']} с.",
          "",
          "Номер входа k по имени — как у правила «одна на имя»: k = 1 первый выбор, k = 2, 3, 4… выборы того же имени, "
          "пока позиция первого ещё открыта. По записям — издержки реплея (плоские); по кассе — настоящие.",
          ""]
    for bk in s["books"]:
        rec = s["records"][bk]
        L_ += [f"## {_title(bk)} — по записям ({rec['n']} записей)", "",
               "| номер входа | записей | доля записей | плюсовых | ср. выигрыш, % маржи | ср. проигрыш, % маржи | RR | ожидание, % маржи | ожидание в цене |",
               "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for name in s["k_bands"] + ["2+", "all"]:
            t = (rec["by_k"] or {}).get(name)
            share = rec["share_k"].get(name) if name in s["k_bands"] else None
            row_name = {"2+": "k ≥ 2 (все повторы)", "all": "все"}.get(name, f"k = {name}")
            if not t:
                L_.append(f"| {row_name} | 0 | {_pp(share)} | — | — | — | — | — | — |")
                continue
            L_.append(f"| {row_name} | {t['n']} | {_pp(share)} | {_pp(t['hit'])} | {_p(t['win_m'])} | {_p(t['loss_m'])} | "
                      f"{_f(t['rr'])} | {_p(t['exp_m'], 2)} | {_bp(t['exp_q'])} |")
        L_.append("")
    L_ += ["## По кассе", "",
           "| книга | ячейка | записей | сделок | итог | просадка | доход/просадка | без 3 дней, $ | σ дня, $ | случайные того же размера: итог (медиана) | доход/просадка (медиана) | зёрен не хуже: итог | доход/просадка |",
           "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in s["books"]:
        for key, title in s["cells"]:
            c = s["cash"][key][bk]
            b = (s["beat"].get(key) or {}).get(bk) or {}
            L_.append(f"| {_title(bk)} | {title} | {_n(s['sizes'][key][bk])} | {_n(c.get('n'))} | {_p(c.get('final'))} | "
                      f"{_p(c.get('max_dd'))} | {_f(ratio_of(c))} | {_n(c.get('wo3'))} | {_n(c.get('sigma_day'))} | "
                      f"{_p(b.get('random_final_med'))} | {_f(b.get('random_ratio_med'))} | {_pp(b.get('final'))} | {_pp(b.get('ratio'))} |")
    L_ += ["", "## Вердикт (из чисел)", "", f"- {s['verdict']}", "",
           "Чего замер не делает: не меняет правила книг и не судит направление; «ювелирность» здесь — доля плюсовых и RR "
           "по записям и деньги кассы, а не слово.", ""]
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
        publish("пропустить первый вход: второй-четвёртый выбор имени по записям и по кассе")


if __name__ == "__main__":
    main()
