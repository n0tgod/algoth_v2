#!/usr/bin/env python3
"""Охрана рынком для коротких книг h24: концентрация, состав выходов, депозиты, равенство ядру.

Решение владельца 2026-09-13 («давай») по итогам `path_screen`: ось
«выйти из шорта, когда волна рынка с момента входа выросла на ≥ y %»
(y ∈ `path_screen.AXES`, 1 / 2 / 3 %) — единственная за шесть замеров,
что бьёт случайный контроль того же размера. Здесь она дорабатывается до
того, чего ей не хватало, чтобы стать кандидатом на бумажную книгу-сестру:

1. **Концентрация**: итог «без 3 лучших дней» у правила и у книги как
   есть, разбор по дням — какие дни сделали разницу (правило, которое
   живёт одним днём, правилом не является).
2. **Состав выходов** и все три депозита (1k / 10k / 100k): касса та же.
3. **Контроль** — случайные выходы того же числа сделок в те же часы
   среди открытых, 200 зёрен (как в `path_screen`).
4. **Равенство ядру.** Охрана — выход по ВРЕМЕНИ, а отметка ядра на
   границе часа есть усечение симуляции в эту секунду (`simulate_dca`,
   `checkpoints`). Это не постулируется, а проверяется на выборке
   реальных решений: реплей с контрольными точками на каждом часе,
   сверка бит в бит с отметками записей кэша и с их исходом. Полный
   реплей охране не нужен — он нужен стопу по цене, который срабатывает
   внутри часа, и это отдельный замер.

Правилом ось и здесь не становится: следующий шаг — книга-сестра вперёд,
решение владельца.
"""
import argparse
import collections
import os
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
import instruments_refresh as IR                              # noqa: E402
import tail_screen as T                                       # noqa: E402
import path_screen as P                                       # noqa: E402

ART = "DCA-wave-guard"
SEEDS = P.SEEDS
MAIN_DEP = P.MAIN_DEP
SAMPLE = 150                                  # решений на проверку равенства ядру
HOUR = 3600.0
EPS = 1.0 / HOUR                              # одна секунда в часах
# Контрольные точки — ДВЕ на каждый час: за секунду до границы (последний
# бар часа — тот же, что у почасовой отметки: равенство проверяется на
# нём) и на самой границе (бар с t = граница — первый бар СЛЕДУЮЩЕГО часа:
# это выход с задержкой в один бар, цена которого честнее для исполнения).
KS = tuple(range(1, R.H24_HOLD_H))
CKPT_OFFS = tuple(x for k in KS for x in (k - EPS, float(k)))
EXIT_LABEL = "рынок"
DAY_MIN_USD = 50.0                            # день в разборе, если разница ≥ этого
TAIL_EXITS = T.TAIL_EXITS
BOOK_KEYS = P.BOOK_KEYS


def wave_axis():
    """Значения оси волны — ТЕ ЖЕ, что объявлены в `path_screen.AXES`."""
    for key, _title, vals in P.AXES:
        if key == "wave":
            return tuple(vals)
    raise KeyError("ось волны не объявлена в path_screen.AXES")


def middle(vals):
    """Середина объявленной оси — порог книги-сестры, не лучшая ячейка."""
    vals = list(vals)
    return vals[len(vals) // 2]


def wo3(days):
    """Сумма дней и сумма без трёх лучших: (всего $, без 3 $, [лучшие дни])."""
    rows = [(float(d.get("usd") or 0.0), d.get("d")) for d in (days or [])]
    if not rows:
        return None, None, []
    total = sum(u for u, _d in rows)
    top = sorted(rows, reverse=True)[:3]
    return total, total - sum(u for u, _d in top), [d for _u, d in top]


def day_diff(base_days, rule_days, min_usd=DAY_MIN_USD):
    """Разница по дням: где правило добавило и где отняло."""
    b = {d["d"]: float(d.get("usd") or 0.0) for d in (base_days or [])}
    r = {d["d"]: float(d.get("usd") or 0.0) for d in (rule_days or [])}
    rows = []
    for d in sorted(set(b) | set(r)):
        diff = r.get(d, 0.0) - b.get(d, 0.0)
        rows.append({"d": d, "base": b.get(d, 0.0), "rule": r.get(d, 0.0),
                     "diff": diff})
    big = [x for x in rows if abs(x["diff"]) >= min_usd]
    return {"rows": big, "n_days": len(rows),
            "better": sum(1 for x in rows if x["diff"] > 0),
            "worse": sum(1 for x in rows if x["diff"] < 0),
            "sum_diff": sum(x["diff"] for x in rows)}


def tails_of(stats_cell):
    ex = (stats_cell or {}).get("exits") or {}
    return sum(int(v.get("n") or 0) for k, v in ex.items() if k in TAIL_EXITS)


def evaluate(cache, views, ctx, launch, seeds=SEEDS, now=None, log=print,
             axis=None):
    axis = tuple(axis if axis is not None else wave_axis())
    base = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                       deps=R.DEPOSITS, now=now)
    idx = P.open_index(views)
    cells = []
    for y in axis:
        mod, changed = P.apply_axis(cache, views, "wave", y)
        for key in changed:
            mod[key] = dict(mod[key], exit=EXIT_LABEL)
        d = P.deltas(cache, views, changed)
        log(f"волна ≥ {y:g} %: изменено {d['n']} сделок (хвостовых {d['tails']}), "
            f"Σ долей маржи {d['sum']:+.2f}")
        cell = {"val": y, "delta": d, "stats": None, "control": None, "beat": {}}
        if changed:
            cell["stats"] = AG.stats_of(AG.packed_short(mod), ctx, launch,
                                        BOOK_KEYS, deps=R.DEPOSITS, now=now)
            ctl = P.control_exits(cache, views, changed, ctx, launch,
                                  seeds=seeds, dep=MAIN_DEP, now=now, log=log,
                                  idx=idx)
            cell["control"] = {"books": ctl["books"], "no_cand": ctl["no_cand"],
                               "sum_med": P._med(ctl["sum"])}
            for bk in BOOK_KEYS:
                st = cell["stats"].get(f"{bk}:{MAIN_DEP}") or {}
                cell["beat"][bk] = {
                    f: AG.beat_share(ctl["books"].get(bk), st.get(f), f)[0]
                    for f in ("final", "ratio")}
            cell["beat"]["sum"] = AG.beat_share(
                [{"sum": x} for x in ctl["sum"]], d["sum"], "sum")[0]
        # разбор по дням — на главном депозите
        cell["days"] = {}
        for bk in BOOK_KEYS:
            b = base.get(f"{bk}:{MAIN_DEP}") or {}
            c = (cell["stats"] or {}).get(f"{bk}:{MAIN_DEP}") or {}
            cell["days"][bk] = day_diff(b.get("days"), c.get("days"))
        cells.append(cell)
    return base, cells


def sample_keys(cache, n):
    """Ровно n решений, равномерно по времени, из закрытых с отметками."""
    keys = sorted({(sym, at) for (rk, sym, at), r in cache.items()
                   if rk in T.RULERS and r.get("state", "closed") == "closed"
                   and r.get("marks")}, key=lambda k: (k[1], k[0]))
    if n <= 0 or not keys:
        return []
    if n >= len(keys):
        return keys
    step = len(keys) / float(n)
    return [keys[int(i * step)] for i in range(n)]


def compare_ckpt(fresh, cache, ks=KS, tol=1e-9):
    """Сверка реплея с контрольными точками против записей кэша.

    Три вещи: (1) исход реплея равен исходу записи — прошлое не изменилось;
    (2) точка «за секунду до границы часа k» равна отметке часа k у ВСЕХ k
    до выхода, а после выхода точек нет — это и есть равенство «отметка =
    усечение ядра», на которое опирается охрана рынком; (3) точка на самой
    границе (первый бар следующего часа) минус отметка — цена задержки
    исполнения на один бар, её распределение печатается, а не
    подразумевается нулём.
    """
    out = {"records": 0, "outcome_diff": 0, "points": 0, "max_diff": 0.0,
           "point_diff": 0, "none_where_open": 0, "value_where_closed": 0,
           "no_ckpt": 0, "misaligned": 0, "lag": [], "diffs": []}
    for key, f in fresh.items():
        r = cache.get(key)
        if r is None:
            continue
        # отметки ядра идут по КАЛЕНДАРНЫМ часам, контрольные точки — от
        # момента входа: сравнимы только когда вход стоит на границе часа
        # (у книг h24 — всегда: `at` есть конец часа решения)
        if abs(float(r["at"]) % HOUR) > 1e-6:
            out["misaligned"] += 1
            continue
        out["records"] += 1
        if abs(float(f["pnl"]) - float(r["pnl"])) > tol or f.get("exit") != r.get("exit"):
            out["outcome_diff"] += 1
            # расхождение исхода — не равенство точек, а воспроизводимость
            # кэша; называется поимённо, с признаком исхода по котировке
            out["diffs"].append({
                "key": list(key), "cache": {"pnl": float(r["pnl"]), "exit": r.get("exit"),
                                            "tail": r.get("tail"),
                                            "exit_ts": r.get("exit_ts")},
                "fresh": {"pnl": float(f["pnl"]), "exit": f.get("exit"),
                          "tail": f.get("tail"), "exit_ts": f.get("exit_ts")}})
        ck = f.get("ckpt")
        if not ck:
            out["no_ckpt"] += 1
            continue
        path = P.path_of(r)
        K = path["K"] if path else 0
        for i, k in enumerate(ks):
            c_eq = ck[2 * i] if 2 * i < len(ck) else None
            c_bd = ck[2 * i + 1] if 2 * i + 1 < len(ck) else None
            if k < K:
                if c_eq is None:
                    out["none_where_open"] += 1
                    continue
                out["points"] += 1
                diff = abs(float(c_eq[2]) - float(path["cum"][k]))
                out["max_diff"] = max(out["max_diff"], diff)
                if diff > tol:
                    out["point_diff"] += 1
                if c_bd is not None:
                    out["lag"].append(float(c_bd[2]) - float(c_eq[2]))
            elif c_eq is not None:
                out["value_where_closed"] += 1
    return out


def lag_stats(lag):
    """Цена задержки на один бар: медиана, среднее, края, доля ненулевых."""
    xs = [float(x) for x in (lag or [])]
    if not xs:
        return {"n": 0}
    import numpy as np
    a = np.array(xs)
    return {"n": len(xs), "median": float(np.median(a)), "mean": float(a.mean()),
            "p05": float(np.percentile(a, 5)), "p95": float(np.percentile(a, 95)),
            "nonzero": float((np.abs(a) > 1e-12).mean())}


def faithfulness(cache, legs_, sample=SAMPLE, log=print):
    """Реплей выборки решений с контрольными точками и сверка с кэшем."""
    want = set(sample_keys(cache, sample))
    if not want:
        return {"why": "выборка пуста"}
    need = [g for g in legs_ if (g["sym"], round(float(g["at"]), 3)) in want]
    t0 = time.time()
    fresh, _tail = S.replay(need, log=log, ckpt_hours=CKPT_OFFS)
    got = compare_ckpt(fresh, cache)
    got["lag"] = lag_stats(got.pop("lag"))
    got.update({"sample": len(want), "legs": len(need),
                "secs": round(time.time() - t0, 1)})
    return got


def run(seeds=SEEDS, sample=SAMPLE, log=print, summary_dir=None,
        mem_limit=None, now=None, launch=None, ctx=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        log(f"охрана рынком не считается: {why}")
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    hours = T.Hours(root=summary_dir or T.SUMMARY_DIR)
    mkt = P.Market(hours)
    closed = {key: r for key, r in cache.items()
              if key[0] in T.RULERS and r.get("state", "closed") == "closed"}
    views = {key: P.view_of(r, mkt) for key, r in closed.items()}
    log(f"сделок {len(views)}; волна не собралась {mkt.wave_none} раз; "
        f"сводок есть/нет {hours.hit}/{hours.miss}; {time.time() - t0:.0f} с")
    base, cells = evaluate(cache, views, ctx, launch, seeds=seeds, now=now,
                           log=log)
    faith = None
    if sample:
        legs_ = S.legs(log=log)
        faith = faithfulness(cache, legs_, sample=sample, log=log)
        log(f"равенство ядру: записей {faith.get('records')}, исход разошёлся у "
            f"{faith.get('outcome_diff')}, точек {faith.get('points')}, "
            f"расхождений {faith.get('point_diff')}, max |Δ| {faith.get('max_diff', 0):.2e}")
    return {"base": base, "cells": cells, "axis": list(wave_axis()),
            "middle": middle(wave_axis()), "seeds": int(seeds), "dep": MAIN_DEP,
            "deps": [int(d) for d in R.DEPOSITS], "books": BOOK_KEYS,
            "faith": faith, "n": len(views),
            "wave_none": mkt.wave_none, "proxies": len(P.PROXY),
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _p(x, d=0):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def _cell_table(s, y, cell):
    dep = int(s["dep"])
    base = s.get("base") or {}
    L = [f"### волна с входа ≥ {y:g} %", ""]
    d = cell["delta"]
    if not d["n"]:
        return L + ["Не сработало ни разу.", ""]
    ctl = cell.get("control") or {}
    L += [f"Изменено сделок {d['n']} (из них хвостовых {d['tails']}, срезано в "
          f"минус {d['cut_worse']}); Σ долей маржи {d['sum']:+.2f} против "
          f"{P._f(ctl.get('sum_med'))} у случайных выходов (не хуже в "
          f"{_p(cell['beat'].get('sum'))} зёрен).", "",
          "| книга | итог: как сейчас → правило | просадка | $ всего | $ без 3 лучших дней | "
          "хвостовых выходов (пол + ликвидация) | зёрен, где случайные не хуже по итогу |",
          "|---|--:|--:|--:|--:|--:|--:|"]
    for bk in s["books"]:
        b = base.get(f"{bk}:{dep}") or {}
        c = (cell["stats"] or {}).get(f"{bk}:{dep}") or {}
        bt, bw, _bd = wo3(b.get("days"))
        ct, cw, _cd = wo3(c.get("days"))
        bt_ = (cell.get("beat") or {}).get(bk) or {}
        L.append(f"| {R.ruler_title(bk)} | {_pp(b.get('final'))} → **{_pp(c.get('final'))}** "
                 f"| {_pp(b.get('max_dd'))} → {_pp(c.get('max_dd'))} "
                 f"| {_usd(bt)} → {_usd(ct)} | {_usd(bw)} → **{_usd(cw)}** "
                 f"| {tails_of(b)} → {tails_of(c)} | {_p(bt_.get('final'))} |")
    L.append("")
    return L


def _deposits_table(s, cell):
    base = s.get("base") or {}
    L = ["| книга | " + " | ".join(f"${int(dp):,}: итог, просадка" for dp in s["deps"]) + " |",
         "|---|" + "--:|" * len(s["deps"])]
    for bk in s["books"]:
        row = []
        for dp in s["deps"]:
            b = base.get(f"{bk}:{int(dp)}") or {}
            c = (cell["stats"] or {}).get(f"{bk}:{int(dp)}") or {}
            row.append(f"{_pp(b.get('final'))} → {_pp(c.get('final'))}, "
                       f"{_pp(b.get('max_dd'))} → {_pp(c.get('max_dd'))}")
        L.append(f"| {R.ruler_title(bk)} | " + " | ".join(row) + " |")
    return L


def _days_table(cell, books):
    L = []
    for bk in books:
        dd = (cell.get("days") or {}).get(bk) or {}
        L += [f"**{R.ruler_title(bk)}**: дней {dd.get('n_days')}, правило лучше в "
              f"{dd.get('better')}, хуже в {dd.get('worse')}, разница всего "
              f"{_usd(dd.get('sum_diff'))}. Дни с разницей ≥ {DAY_MIN_USD:.0f} $:", ""]
        rows = dd.get("rows") or []
        if not rows:
            L += ["нет таких дней.", ""]
            continue
        L += ["| день | как сейчас | правило | разница |", "|---|--:|--:|--:|"]
        for x in rows:
            L.append(f"| {x['d']} | {_usd(x['base'])} | {_usd(x['rule'])} | {_usd(x['diff'])} |")
        L.append("")
    return L


def _faith_text(f):
    if not f:
        return ["Проверка равенства ядру не запускалась (`--sample 0`)."]
    if f.get("why"):
        return [f"Проверка равенства ядру: {f['why']}."]
    # равенство «отметка = усечение» судится по точкам; исход реплея против
    # кэша — отдельный вопрос воспроизводимости, и он печатается отдельно
    ok = (f.get("point_diff") == 0 and f.get("none_where_open") == 0
          and f.get("value_where_closed") == 0 and (f.get("points") or 0) > 0)
    verdict = ("**равенство держится**" if ok
               else "**РАСХОЖДЕНИЕ — охрану по отметкам читать нельзя**")
    return [f"Реплей ядром {f.get('legs')} ног ({f.get('sample')} решений, "
            f"{f.get('secs')} с) с контрольными точками на конце каждого часа: "
            f"записей сверено {f.get('records')}, исход реплея разошёлся с кэшем у "
            f"{f.get('outcome_diff')}; точек до выхода {f.get('points')}, "
            f"расхождений с отметкой {f.get('point_diff')} (max |Δ| "
            f"{float(f.get('max_diff') or 0):.1e} доли маржи); точка пустая при "
            f"открытой позиции {f.get('none_where_open')} раз, непустая после выхода "
            f"{f.get('value_where_closed')} раз; записей без точек {f.get('no_ckpt')}, "
            f"с входом не на границе часа {f.get('misaligned')}. "
            f"{verdict}.", "",
            _diffs_text(f), "",
            _lag_text(f.get("lag") or {})]


def _diffs_text(f):
    ds = f.get("diffs") or []
    if not ds:
        return ("Исход сегодняшнего реплея равен исходу в кэше у всех сверенных "
                "записей — кэш воспроизводим.")
    L = [f"**Исход реплея разошёлся с кэшем у {len(ds)} записей** — это "
         "воспроизводимость кэша, а не равенство точек; поимённо (исход в "
         "кэше → в реплее; «котировка» — исход был посчитан по котировке "
         "хвоста ленты, а не по принтам):", "",
         "| запись | вход | в кэше | в реплее |", "|---|---|---|---|"]
    for d in ds:
        k = d["key"]
        c, fr = d["cache"], d["fresh"]
        at = time.strftime("%m-%d %H:%M", time.gmtime(float(k[2])))
        L.append(f"| {k[0]} {k[1]} | {at} | {100 * c['pnl']:+.1f} % {c['exit']}"
                 f"{' (котировка)' if c.get('tail') else ''} | "
                 f"{100 * fr['pnl']:+.1f} % {fr['exit']}"
                 f"{' (котировка)' if fr.get('tail') else ''} |")
    return "\n".join(L)


def _lag_text(lg):
    if not lg.get("n"):
        return "Цена задержки на один бар не измерена: точек на границе нет."
    return (f"**Задержка исполнения на один бар** (выход первым баром следующего "
            f"часа вместо последнего бара своего): по {lg['n']} точкам медиана "
            f"{100 * lg['median']:+.3f} % маржи, среднее {100 * lg['mean']:+.3f} %, "
            f"5–95 % {100 * lg['p05']:+.2f}…{100 * lg['p95']:+.2f} %; бар на границе "
            f"отличался от последнего у {100 * lg['nonzero']:.0f} % точек. Знак минус "
            "значит, что минута задержки стоит денег шорту; в числах оси выше "
            "задержка не учтена.")


def report(s):
    L = ["# Охрана рынком для коротких книг: концентрация, депозиты, равенство ядру",
         "",
         "Решение владельца 2026-09-13 по итогам `path_screen`: довести ось «выйти "
         "из шорта, когда волна рынка с входа выросла на ≥ y %» до кандидата на "
         "книгу-сестру. Волна — средний ход "
         f"{s.get('proxies') or len(P.PROXY)} прокси-имён (`side_wave.PROXY`). "
         "Выход — по отметке ядра на границе часа; это не приближение, а "
         "усечение симуляции в эту секунду — и это ПРОВЕРЕНО ниже на выборке "
         "реальных решений, а не постулировано. Деньги — касса семейства, нетто; "
         "контроль — случайные выходы того же числа сделок в те же часы среди "
         f"открытых ({s.get('seeds') or SEEDS} зёрен). Правилом ось не "
         "становится: следующий шаг — книга-сестра вперёд.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой части.", ""]
    L += ["## Равенство ядру", ""] + _faith_text(s.get("faith")) + [""]
    L += ["## Ось по порогам", "",
          f"Сделок {s.get('n')}; волна не собралась {s.get('wave_none')} раз. "
          f"Депозит ${int(s['dep']):,}; «$ без 3 лучших дней» — сумма дней книги "
          "без трёх лучших: правило, живущее одним днём, здесь и проваливается.", ""]
    cells = s.get("cells") or []
    for c in cells:
        L += _cell_table(s, c["val"], c)
    mid = s.get("middle")
    for c in cells:
        if c["val"] == mid and c["delta"]["n"]:
            L += [f"## Порог книги-сестры: середина оси, {mid:g} %", "",
                  "Выбран как середина ОБЪЯВЛЕННОЙ оси, а не как лучшая ячейка.", "",
                  "### Три депозита", ""] + _deposits_table(s, c) + ["",
                  "### Разбор по дням (главный депозит)", ""] + _days_table(c, s["books"])
    L += ["## Как читать", "",
          "- Если «$ без 3 лучших дней» у правила не выше, чем у книги как есть, "
          "прибавка пришла эпизодом — правило не подтверждено.",
          "- Если правило лучше в большинстве дней и разница размазана — "
          "механизм работает каждый день, а не одним сквизом.",
          "- Равенство ядру: расхождение хотя бы в одной точке значит, что выход "
          "по отметке не есть выход ядра, и все числа выше — приближение.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--sample", type=int, default=SAMPLE)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--art", default=ART,
                    help="имя артефакта (диагностический прогон не затирает основной)")
    a = ap.parse_args(argv)
    s = run(seeds=a.seeds, sample=a.sample, log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, a.art, report, log=print)
    if not a.no_publish:
        publish("охрана рынком коротких книг: концентрация, депозиты, равенство ядру")


if __name__ == "__main__":
    main()
