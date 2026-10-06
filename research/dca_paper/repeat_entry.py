#!/usr/bin/env python3
"""Пропустить первый вход: насколько «ювелирны» второй, третий, четвёртый
выбор имени моделью — и что это даёт кассе. ОТДЕЛЬНО по коротким и
длинным сделкам.

Вопрос владельца (06.10): если модель, выбирающая то же имя второй и
третий час подряд, права чаще и сильнее, чем в первый раз (замеры
`cost_gap` и `pick_rule`: повторные выборы в цене +43…54 б.п. против
первых +19…31), что будет, если входить ТОЛЬКО по повторам. Второй
вопрос (06.10): посмотреть то же отдельно на шорт- и лонг-сделках —
первый прогон считал только короткие книги `h24`.

Стороны — это РАЗНЫЕ семейства книг с разными листами, и смешивать их
нельзя: короткие сделки — книги `safe_h`/`optimal_h`/`aggr_h` (лист —
короткие выборы `h24`, срок 24 ч, без доливов); длинные — DCA-книги
`safe`/`optimal`/`aggr` (лист — длинные выборы ситуационной книги, срок
72 ч, лестница доливов). Каждая сторона считается своим кэшем реплея,
своей кассой и своими случайными подмножествами; вердикт — по стороне.

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

Нетто записи. Короткое ядро (`run_d10`) пишет `pnl_net` = pnl − круг на
заполненный нотионал (доля маржи); длинное (`run_d6`) хранит только
заполнения `fills` (момент, цена, доля). Для длинных записей нетто
считается ТОЙ ЖЕ формулой из заполнений — плечо × Σ долей × 11 б.п. — и
формула сверяется с ядром на коротких записях, у которых есть и
`filled`, и `fills`: расхождение печатается числом, а не молчит.

Рычаг — «пропустить первый» лучше книги «как сейчас» по доходу/просадке
и не хуже ≥ 95 % случайных подмножеств по итогу и доходу/просадке у
оптимальной и агрессивной СВОЕЙ стороны. Право на итерацию одно. Правила
книг не меняются; замер читает кэши реплея.

    run research/dca_paper/repeat_entry.py            # обе стороны
    run research/dca_paper/repeat_entry.py --side long
"""
import argparse
import gc
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
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_d10 as D10                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_levers as L                                      # noqa: E402
import short_levcap as V                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-repeat-entry"
MAIN_DEP = 10000
SEEDS = 200
BEAT_MAX = 0.05
K_BANDS = ("1", "2", "3", "4", "5+")
CELLS = (("k1", "как сейчас: первый выбор имени", lambda k: k == 1),
         ("k2plus", "пропустить первый: входит второй выбор", lambda k: k >= 2),
         ("k3plus", "пропустить два: входит третий выбор", lambda k: k >= 3))
# Стороны — семейства книг. Ключи книг, судимые книги, кэш и упаковка —
# из реестров прогонов, не своей копией.
SIDES = {
    "short": {"title": "короткие сделки — книги h24 (`safe_h`/`optimal_h`/`aggr_h`), срок 24 ч, без доливов",
              "keys": list(S.BOOKS), "judge": ("optimal_h", "aggr_h"),
              "read": lambda log: S.read_cache(log=log),
              "pack": lambda cache: AG.packed_short(cache)},
    "long": {"title": "длинные сделки — DCA-книги лонгов (`safe`/`optimal`/`aggr`), срок 72 ч, лестница доливов",
             "keys": list(R.RULER_ORDER), "judge": ("optimal", "aggr"),
             "read": lambda log: RP.read_cache(),
             "pack": lambda cache: AG.packed_long(cache, R.RULER_ORDER)},
}
SIDE_ORDER = ("short", "long")
# Прежние имена — для совместимости с проверками первой версии.
BOOK_KEYS = SIDES["short"]["keys"]
JUDGE_BOOKS = SIDES["short"]["judge"]


def band_of(k):
    return "5+" if k >= 5 else str(int(k))


def filled_of(r):
    """Заполненный нотионал долей маржи — из заполнений, как у ядра:
    `filled_notional` = Σ долей × плечо (капитал 1)."""
    fills = r.get("fills")
    lev = float(r.get("lev") or 0.0)
    if not fills or not lev > 0:
        return None
    return lev * sum(float(f[2]) for f in fills)


def net_of(r):
    """Нетто записи долей маржи: записанное ядром `pnl_net`, а без него —
    та же формула ядра из заполнений (`run_d10`: pnl − filled × круг)."""
    if r.get("pnl_net") is not None:
        return float(r["pnl_net"])
    if r.get("pnl") is None:
        return None
    filled = filled_of(r)
    if filled is None:
        return None
    return float(r["pnl"]) - filled * D10.ROUND_COST_BP / 1e4


def net_check(recs, tol=1e-6):
    """Сверка формулы нетто с ядром: у записей с `filled` И `fills`
    заполненный нотионал из заполнений обязан совпасть с записанным."""
    n, bad, worst = 0, 0, 0.0
    for r in recs:
        if r.get("filled") is None:
            continue
        f = filled_of(r)
        if f is None:
            continue
        n += 1
        d = abs(f - float(r["filled"]))
        worst = max(worst, d)
        if d > tol:
            bad += 1
    return {"checked": n, "mismatch": bad, "worst": worst}


def label(recs):
    """Записи книги с номером входа `k` по имени (см. модуль).

    Закрытые записи с нетто; две записи одного имени в одну секунду —
    одна (с большим прогнозом). Возвращает список копий записей с полями
    `k` и `pnl_net`.
    """
    closed = []
    for r in recs:
        if (r.get("state") or "closed") != "closed" or not float(r.get("lev") or 0) > 0:
            continue
        net = net_of(r)
        if net is None:
            continue
        closed.append(dict(r, pnl_net=net))
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
        r["k"] = k
        out.append(r)
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


def random_subsets(packed, sizes, ctx, launch, keys, seeds=SEEDS, dep=MAIN_DEP,
                   now=None, log=print, tag=""):
    """Случайные подмножества записей ТОГО ЖЕ размера на книгу — нуль фильтра."""
    draws = {bk: [] for bk in keys}
    base = {bk: label(packed.get(bk) or []) for bk in keys}
    t0 = time.time()
    for i in range(int(seeds)):
        rnd = random.Random(9000 + i)
        sub = {}
        for bk in keys:
            n = int(sizes.get(bk) or 0)
            pool = base[bk]
            sub[bk] = list(pool) if n >= len(pool) else rnd.sample(pool, n)
        st = AG.stats_of(sub, ctx, launch, keys, deps=[dep], now=now)
        for bk in keys:
            c = st.get(f"{bk}:{int(dep)}") or {}
            draws[bk].append({"final": c.get("final"), "ratio": c.get("ratio"), "n": c.get("n")})
        if i and i % 50 == 0:
            log(f"{tag}случайные подмножества: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    return draws


def cash_cell(sub, ctx, launch, keys, dep=MAIN_DEP, now=None):
    st = AG.stats_of(sub, ctx, launch, keys, deps=[dep], now=now)
    return {bk: L.summ(st.get(f"{bk}:{int(dep)}") or {}) for bk in keys}


def ratio_of(c):
    return (None if not c or not c.get("final") or not c.get("max_dd")
            else round(float(c["final"]) / abs(float(c["max_dd"])), 2))


def verdict(cells, beat, judge=JUDGE_BOOKS):
    """Из чисел: «пропустить первый» против книги как сейчас и против случайных."""
    parts, ok = [], True
    for bk in judge:
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


def run_side(side, log=print, now=None, launch=None, ctx=None, dep=MAIN_DEP, seeds=SEEDS):
    """Одна сторона: записи по k, касса по ячейкам, случайные того же размера, вердикт."""
    t0 = time.time()
    sd = SIDES[side]
    keys, judge = sd["keys"], sd["judge"]
    tag = f"[{side}] "
    cache, why = sd["read"](log)
    if why:
        return {"title": sd["title"], "books": keys, "judge_books": list(judge),
                "error": f"кэш реплея непригоден: {why}"}
    packed = sd["pack"](cache)
    check = net_check([r for recs in packed.values() for r in recs])
    n_cache = len(cache)
    del cache
    gc.collect()
    records = {}
    for bk in keys:
        lab = label(packed.get(bk) or [])
        records[bk] = {"n": len(lab), "by_k": by_k(lab, bk),
                       "share_k": {name: sum(1 for r in lab if band_of(r["k"]) == name) / len(lab)
                                   for name in K_BANDS} if lab else {}}
    cells, sizes = {}, {}
    for key, _title, pred in CELLS:
        sub = subset(packed, pred)
        sizes[key] = {bk: len(sub[bk]) for bk in keys}
        cells[key] = cash_cell(sub, ctx, launch, keys, dep=dep, now=now)
        log(f"{tag}{key}: записей " + ", ".join(f"{bk} {sizes[key][bk]}" for bk in keys)
            + "; доход/просадка " + ", ".join(f"{bk} {ratio_of(cells[key][bk])}" for bk in keys)
            + f" ({time.time() - t0:.0f} с)")
    beat = {}
    for key, _title, _pred in CELLS[1:]:
        draws = random_subsets(packed, sizes[key], ctx, launch, keys, seeds=seeds, dep=dep,
                               now=now, log=log, tag=tag)
        beat[key] = {}
        for bk in keys:
            c = cells[key][bk]
            beat[key][bk] = {"final": AG.beat_share(draws[bk], c.get("final"), "final")[0],
                             "ratio": AG.beat_share(draws[bk], ratio_of(c), "ratio")[0],
                             "random_final_med": _median([d["final"] for d in draws[bk] if d["final"] is not None]),
                             "random_ratio_med": _median([d["ratio"] for d in draws[bk] if d["ratio"] is not None])}
    return {"title": sd["title"], "books": keys, "judge_books": list(judge),
            "records": records, "cash": cells, "sizes": sizes, "beat": beat,
            "verdict": verdict(cells, beat, judge),
            "diag": {"records": n_cache, "net_check": check},
            "secs": round(time.time() - t0, 1)}


def run(log=print, now=None, launch=None, ctx=None, mem_limit=None, dep=MAIN_DEP, seeds=SEEDS,
        sides=SIDE_ORDER):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    out_sides = {}
    for side in sides:
        out_sides[side] = run_side(side, log=log, now=now, launch=launch, ctx=ctx, dep=dep, seeds=seeds)
        if out_sides[side].get("error"):
            log(f"[{side}] {out_sides[side]['error']}")
        gc.collect()
    words = {"short": "короткие", "long": "длинные"}
    verdict_all = "; ".join(f"{words.get(sd, sd)}: {out_sides[sd].get('verdict') or out_sides[sd].get('error')}"
                            for sd in sides)
    return {"dep": dep, "seeds": int(seeds), "beat_max": BEAT_MAX,
            "cells": [(k, t) for k, t, _p in CELLS], "k_bands": list(K_BANDS),
            "side_order": list(sides), "sides": out_sides, "verdict": verdict_all,
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


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
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная",
            "safe": "безопасная", "optimal": "оптимальная", "aggr": "агрессивная"}.get(bk, bk)


def _side_name(side):
    return {"short": "Короткие сделки", "long": "Длинные сделки"}.get(side, side)


def report_side(side, sd, s):
    L_ = [f"# {_side_name(side)}: {sd.get('title', '')}", ""]
    if sd.get("error"):
        L_ += [f"ОШИБКА: {sd['error']}", ""]
        return L_
    chk = (sd.get("diag") or {}).get("net_check") or {}
    L_.append(f"Записей реплея {sd['diag']['records']}, посчитано за {sd.get('secs')} с. ")
    if chk.get("checked"):
        L_.append(f"Сверка формулы нетто с ядром: записей с `filled` и `fills` {chk['checked']}, "
                  f"расхождений {chk['mismatch']}, худшее {chk['worst']:.2e}"
                  + (" — ФОРМУЛА РАСХОДИТСЯ С ЯДРОМ, нетто записей этой стороны под вопросом." if chk["mismatch"] else "."))
    else:
        L_.append("Сверка формулы нетто с ядром здесь невозможна: записей с `filled` нет "
                  "(у длинных записей нетто считается из заполнений, формула сверена на коротких).")
    L_.append("")
    for bk in sd["books"]:
        rec = sd["records"][bk]
        L_ += [f"## {_side_name(side).lower()}, {_title(bk)} — по записям ({rec['n']} записей)", "",
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
    L_ += [f"## {_side_name(side).lower()} — по кассе ${s['dep']:,} нетто", "",
           "| книга | ячейка | записей | сделок | итог | просадка | доход/просадка | без 3 дней, $ | σ дня, $ | случайные того же размера: итог (медиана) | доход/просадка (медиана) | зёрен не хуже: итог | доход/просадка |",
           "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in sd["books"]:
        for key, title in s["cells"]:
            c = sd["cash"][key][bk]
            b = (sd["beat"].get(key) or {}).get(bk) or {}
            L_.append(f"| {_title(bk)} | {title} | {_n(sd['sizes'][key][bk])} | {_n(c.get('n'))} | {_p(c.get('final'))} | "
                      f"{_p(c.get('max_dd'))} | {_f(ratio_of(c))} | {_n(c.get('wo3'))} | {_n(c.get('sigma_day'))} | "
                      f"{_p(b.get('random_final_med'))} | {_f(b.get('random_ratio_med'))} | {_pp(b.get('final'))} | {_pp(b.get('ratio'))} |")
    by = {"short": "по коротким сделкам", "long": "по длинным сделкам"}.get(side, side)
    L_ += ["", f"**Вердикт {by} (из чисел):** {sd['verdict']}", ""]
    return L_


def report(s):
    if s.get("error"):
        return f"# Пропустить первый вход\n\nОШИБКА: {s['error']}\n"
    L_ = ["# Пропустить первый вход: второй, третий и четвёртый выбор имени — отдельно по коротким и длинным сделкам",
          "",
          f"Касса ${s['dep']:,} нетто; случайные подмножества того же размера — {s['seeds']} зёрен; "
          f"посчитано {s['computed_at']} за {s['secs']} с.",
          "",
          "Номер входа k по имени — как у правила «одна на имя»: k = 1 первый выбор, k = 2, 3, 4… выборы того же имени, "
          "пока позиция первого ещё открыта. По записям — издержки реплея (плоские, 11 б.п. на заполненный нотионал); "
          "по кассе — настоящие. Стороны — разные семейства книг с разными листами и считаются порознь.",
          ""]
    for side in s["side_order"]:
        L_ += report_side(side, s["sides"][side], s)
    L_ += ["## Вердикт (из чисел)", "", f"- {s['verdict']}", "",
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
    ap.add_argument("--side", choices=list(SIDE_ORDER) + ["both"], default="both")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    sides = SIDE_ORDER if a.side == "both" else (a.side,)
    s = run(log=print, seeds=a.seeds, sides=sides)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("пропустить первый вход: второй-четвёртый выбор имени, отдельно шорт и лонг")


if __name__ == "__main__":
    main()
