#!/usr/bin/env python3
"""D10 — чем вывести КОРОТКИЕ DCA-книги в плюс: плечо, доливы, цель, гейт.

Вопрос владельца 2026-09-06: «подумай, что мы можем затестить, чтобы
вывести DCA-шорт-стратегии в плюс — запускай всё в тест».

Откуда убыток, уже измерено (D9): у коротких книг позиции БЕЗ лестницы
(структурных уровней выше входа не нашлось, плечо 1×) в сумме
положительны, а весь минус приносит лестница с плечом — забор выдаёт
шорту 20× потому, что его лестница узкая, и пол капитуляции при таком
плече стоит в четырёх процентах хода против. Доливы ВВЕРХ при этом суть
усреднение в сквиз — ровно то, чем умерла F-серия. Значит рычаги три, и
все три объявлены ЗДЕСЬ, до прогона:

    плечо   fence (как сейчас) | потолок 3× | 2× | 1×
    доливы  struct (как сейчас) | none (без доливов) | sigma (σ-сетка §4)
    цель    обещание mfe ×2 (как сейчас) | ×1 | ×3

Это 36 ячеек на книгу. Отдельно ось ГЕЙТА входа: гейт `RR ≥ 2` (как
сейчас) оставляет шортам 3.4 % сырья, а у самого сигнала низкое
отношение трижды независимо оказалось прибыльной областью (наблюдательная
запись, lo-книга, S11). Гейты: `rr2` (как сейчас), `lo` (RR ≤ 1.5),
`any` (край ≥ 33 б.п., отношение любое). Ноги гейта — надмножество,
считаются ОДНИМ проходом (бары читаются по символу), ячейки — по
подмножеству.

**Как устроен потолок плеча.** Плечо каждого решения выводит ЗАБОР книги
на лестнице ЭТОГО решения (`D5.fence_leverage`, та же дорога, что у
бумажной книги); потолок берёт `min(забор, потолок)`. У руки без доливов
плечо берётся тем, что забор выдал СТРУКТУРНОЙ лестнице решения, а не
1×: так плечо и доливы разделяются, иначе «без доливов» совпадало бы с
«1×» по построению и вопрос «доливы или плечо» оставался бы без ответа.
У σ-сетки забор считается на ней же (её `d_max` = 3 · шаг).

**Что считается издержками.** В бумажных DCA-книгах комиссии нет вовсе —
все их числа брутто. Здесь рядом с брутто печатается нетто с кругом
`ROUND_COST_BP` (11 б.п. на заполненный нотионал: тейкер на каждом рунге
и на выходе); проскальзывание не моделируется, funding — отдельный замер
(`dca_paper/costs.py`). Знак книги обязан держаться и после круга, иначе
«в плюс» есть иллюзия брутто.

**Чего замер не делает.** Правил книг не меняет — решение владельца.
Выбрать лучшую ячейку из 36 и предъявить её — ошибка R5; таблица
печатается целиком, читать по форме (медиана дня, зелёные, укус,
просадка) и по парной разности к нынешнему правилу на ТЕХ ЖЕ решениях.
Веса модели видели эти часы (оценка сверху), окно записи одно и режим
рынка один. Касса и форма — те же, что у бумажных книг (`D6.ration`,
`run_paper._stats`), второй реализации нет.

Прогон: `run research/dca_ladder/run_d10.py`. Смоук: `--limit 400`.
Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
sys.path.insert(0, os.path.join(ROOT, "research", "s10_policy"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import run_d5 as D5                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as PP                                        # noqa: E402
import tournament as TNT                                      # noqa: E402
import trades as TR                                           # noqa: E402

OUT = os.path.join(HERE, "out")
HOUR = 3600

# --- сетка объявлена ДО прогона ----------------------------------------
LEVS = [("fence", "как забор"), ("c3", "потолок 3×"), ("c2", "потолок 2×"),
        ("c1", "1×")]
LEV_CAP = {"fence": None, "c3": 3.0, "c2": 2.0, "c1": 1.0}
ADDS = [("struct", "структурные уровни"), ("none", "без доливов"),
        ("sigma", "σ-сетка")]
TAKES = [("t2", "обещание ×2", 2.0), ("t1", "обещание ×1", 1.0),
         ("t3", "обещание ×3", 3.0)]
TAKE_MULT = {k: m for (k, _t, m) in TAKES}
SPACING_SIG = 2.0          # шаг σ-сетки: рунг каждые 2 суточные σ (как D1)
# Гейты входа: подмножества одного прохода. `rr2` — то, чем книга торгует.
GATES = [("rr2", "RR ≥ 2 (как сейчас)"), ("lo", "RR ≤ 1.5"),
         ("any", "отношение любое")]
REF = "fence:struct:t2"                     # нынешнее правило книги
REF_GATE = "rr2"
# Издержки: круг на заполненный нотионал — тейкер на рунге и на выходе.
ROUND_COST_BP = float(TR.ROUND_COST_BP)
# Книги: линейки забора коротких книг. «Агрессивная» — «оптимальная» плюс
# гейт плеча режима, из тех же позиций (как в D8/D9).
RULERS = {"safe_s": (R.RULERS["safe_s"]["rule"], R.RULERS["safe_s"]["param"]),
          "optimal_s": (R.RULERS["optimal_s"]["rule"],
                        R.RULERS["optimal_s"]["param"])}
BOOK_RULER = {"optimal_s": "optimal_s", "safe_s": "safe_s",
              "aggr_s": "optimal_s"}


def grid():
    """Все объявленные ячейки: ключ → (плечо, доливы, цель)."""
    out = []
    for lk, _l in LEVS:
        for ak, _a in ADDS:
            for tk, _t, _m in TAKES:
                out.append((f"{lk}:{ak}:{tk}", lk, ak, tk))
    return out


CELLS = grid()
KEYS = [c[0] for c in CELLS]
assert REF in KEYS, "точки отсчёта нет в сетке"


def book_cell():
    """Ключ ячейки, равной ДЕЙСТВУЮЩЕМУ правилу книги. None — её нет.

    Выводится из правила (`rules.TAKE_MULT`), не записан числом: сменится
    множитель — отчёт перестанет помечать «нынешним» то, чем книга не
    торгует (правило D8).
    """
    tk = {1.0: "t1", 2.0: "t2", 3.0: "t3"}.get(float(R.TAKE_MULT))
    key = f"fence:struct:{tk}" if tk else None
    return key if key in KEYS else None


def gate_of(g):
    """Какие гейты нога проходит. Край обязателен у всех (как в книге)."""
    if abs(float(g.get("fwd") or 0.0)) < D2.MIN_EDGE_BP:
        return set()
    rr = g.get("rr")
    out = {"any"}
    if rr is not None and float(rr) >= D2.MIN_RR:
        out.add("rr2")
    if rr is not None and float(rr) <= 1.5:
        out.add("lo")
    return out


def short_legs(limit=None, log=print):
    """Короткие ноги журнала листов под ОБЪЕДИНЕНИЕМ гейтов (край ≥ 33)."""
    legs = TNT.legs_from_sheets([D2.SHEETS], log=log)
    out = [g for g in legs if g.get("side") == "short" and gate_of(g)]
    return out[:limit] if limit else out


def leverage_for(lk, lev_fence):
    cap = LEV_CAP[lk]
    return float(lev_fence) if cap is None else float(min(lev_fence, cap))


def take_for(g, tk):
    """Цель ячейки — та же форма, что `rules.take_rule`, с множителем оси.

    Множитель книги — `rules.TAKE_MULT`; здесь он ось, и доля считается
    той же арифметикой: `|обещание| × множитель`, направление задаёт
    сторона в самой симуляции. Обещание не в сторону позиции — цели нет.
    """
    fav = float(g["fav"]) / 1e4
    if not fav < 0:                       # шорт: обещание в пользу — вниз
        return None
    return {"anchor": R.TAKE_ANCHOR, "frac": abs(fav) * TAKE_MULT[tk]}


def one_position(g, bars, ts, look, rule, param, lev_look=None):
    """Исход одного КОРОТКОГО решения во всех ячейках. None — нечем мерить.

    Геометрия считается один раз на решение; между ячейками различаются
    ровно плечо, рунги и цель. Пол капитуляции и срок — как у книги.
    """
    if (g.get("side") or "long") != "short":
        return None
    rs = D2.split_window(bars, ts, g["at"], D2.BACK_H, D2.HOLD_H)
    if rs is None:
        return None
    win, now_i = rs
    hold = win[now_i:]
    entry = float(hold[0][1])
    if entry <= 0:
        return None
    stop_px = entry * (1 + float(g["adv_q"]) / 1e4)
    if not stop_px > entry:               # стоп шорта обязан стоять выше
        return None
    if take_for(g, "t2") is None:
        return None
    lv = D2.build_levels(win, now_i)
    rungs_struct = D2.structural_rungs(entry, list(lv), D2.MIN_ADD_GAP,
                                       D2.N_RUNGS, side="short")
    sigma_bp, _r, _t = D3.window_stats(win, now_i)
    sig = D5.sigma_day(sigma_bp)
    # Забор на СТРУКТУРНОЙ лестнице — то, что выдаёт книга. Без него
    # руке «без доливов» не от чего брать плечо.
    lev_struct, rungs_s, _b = D5.fence_leverage(
        rule, param, entry, rungs_struct, look, sigma_bp, side="short",
        lev_look=lev_look)
    geo = {"struct": (lev_struct, rungs_s),
           "none": (lev_struct, [entry])}
    if sig is not None and sig > 0:
        try:
            rungs_sig, _dm = L.sigma_rungs(entry, sig, D2.N_RUNGS,
                                           SPACING_SIG, side="short")
        except ValueError:
            rungs_sig = None
        if rungs_sig:
            lev_sig, rungs_sg, _b2 = D5.fence_leverage(
                rule, param, entry, rungs_sig, look, sigma_bp, side="short",
                lev_look=lev_look)
            geo["sigma"] = (lev_sig, rungs_sg)
    out = {}
    for (key, lk, ak, tk) in CELLS:
        if ak not in geo:
            continue                      # σ не измерена — ячейки нет
        lev_f, rungs = geo[ak]
        lev = leverage_for(lk, lev_f)
        w = D2.WEIGHTS[:len(rungs)]
        tr = take_for(g, tk)
        r = L.simulate_dca(hold, rungs, w, 1.0, lev, look(1.0 * lev),
                           take_rule=tr, floor_frac=D2.FLOOR_FRAC,
                           side="short")
        filled = float(r["filled_notional"])
        out[key] = {
            "at": float(g["at"]), "exit_ts": float(r["exit_ts"]),
            "pnl": float(r["pnl_frac"]),
            # нетто: круг на заполненный нотионал (доля маржи)
            "pnl_net": float(r["pnl_frac"]) - filled * ROUND_COST_BP / 1e4,
            "lev": float(lev), "lev_fence": float(lev_f),
            "fwd": abs(float(g["fwd"])), "sym": g["sym"], "side": "short",
            "rr": g.get("rr"), "gates": sorted(gate_of(g)),
            "exit": r["exit"], "marks": [],
            "end_ts": float(hold[-1][0]),
            "sched_end": float(g["at"]) + D2.HOLD_H * HOUR,
            "depth": int(r["depth"]), "n_rungs": len(rungs),
            "avg": float(r["avg"]), "entry_px": entry,
            "exit_px": float(r["exit_px"]), "filled": filled}
    return out


def collect(limit=None, src=None, log=print, legs=None):
    """Дорогой проход: бары символа читаются ОДИН раз на все ячейки."""
    get = src.bars if src else (lambda s, a, b: D6.SW.read_bars(
        D6.ROOT_B1, s, a, b))
    tiers_all = D2.instruments_tiers()
    shorts = (list(legs)[:limit] if legs is not None
              else short_legs(limit=limit, log=log))
    by_sym = {}
    for g in shorts:
        by_sym.setdefault(g["sym"], []).append(g)
    win = D6.window(shorts)
    gc = {gk: sum(1 for g in shorts if gk in gate_of(g)) for gk, _ in GATES}
    log(f"коротких ног (край ≥ {D2.MIN_EDGE_BP:g}) {len(shorts)}: "
        + ", ".join(f"{gk} {gc[gk]}" for gk, _ in GATES)
        + f"; символов {len(by_sym)}")
    if win:
        log(f"окно решений {win['from']} … {win['to']} UTC "
            f"({win['span_d']:g} суток, дат {win['dates']})")
    recs = {rk: {k: [] for k in KEYS} for rk in RULERS}
    mem_guard("ноги загружены", log=log)
    n, skipped = 0, 0
    said, done = time.time(), 0
    for sym, glist in by_sym.items():
        done += 1
        if time.time() - said > 30:
            log(f"  символ {done}/{len(by_sym)}  решений {n}")
            said = time.time()
        if done % 10 == 0:
            mem_guard(f"символ {done}/{len(by_sym)}", log=log)
        a0 = min(gg["at"] for gg in glist) - D2.BACK_H * HOUR
        b1 = max(gg["at"] for gg in glist) + D2.HOLD_H * HOUR
        bars = get(sym, a0, b1)
        if not bars:
            skipped += len(glist)
            continue
        ts = [bb[0] for bb in bars]
        tiers = tiers_all.get(sym) or []
        look = lambda notl, t=tiers: L.mmr_for_notional(       # noqa: E731
            t, notl, flat=D2.FLAT_MMR)
        lev_look = lambda notl, t=tiers: L.lev_cap_for_notional(  # noqa: E731
            t, notl)
        for g in glist:
            got = 0
            for rk, (rule, param) in RULERS.items():
                o = one_position(g, bars, ts, look, rule, param,
                                 lev_look=lev_look)
                if not o:
                    continue
                got = 1
                for k, r in o.items():
                    recs[rk][k].append(r)
            n += got
            skipped += (1 - got)
    data_end = 0.0
    for rk in recs:
        for k in recs[rk]:
            for r in recs[rk][k]:
                data_end = max(data_end, float(r.get("end_ts") or 0.0))
    for rk in recs:
        for k in recs[rk]:
            for r in recs[rk][k]:
                r["state"] = D6.position_state(r, data_end)
    log(f"запись доходит до "
        f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(data_end))} UTC")
    return {"recs": recs, "positions": n, "skipped": skipped,
            "window": win, "data_end": data_end, "gate_counts": gc}


def common_sample(recs, log=print):
    """Решения, ЗАКРЫТЫЕ при каждой ячейке (правило D8). Потери — числом.

    Ячейка без σ-сетки у части решений (σ не измерена) не вправе сужать
    выборку остальным: сравнение идёт по решениям, у которых есть ВСЕ
    ячейки, и это печатается числом.
    """
    ok = None
    for k in KEYS:
        s = {(r["sym"], round(r["at"], 3)) for r in recs[k]
             if r.get("state") == "closed"}
        ok = s if ok is None else (ok & s)
    ok = ok or set()
    out, lost = {}, 0
    for k in KEYS:
        kept = [r for r in recs[k] if (r["sym"], round(r["at"], 3)) in ok]
        lost = max(lost, len(recs[k]) - len(kept))
        out[k] = kept
    log(f"общая выборка: {len(ok)} решений, выброшено до {lost}")
    return out, len(ok), lost


def _exits(rows):
    out = {}
    for (r, _m) in rows:
        out[r["exit"]] = out.get(r["exit"], 0) + 1
    return out


def cell(recs, book, dep, gate=REF_GATE, net=False):
    """Ячейка «правило × книга × депозит × гейт»: касса и форма книги.

    `net=True` считает деньги по `pnl_net` (с кругом издержек) — той же
    кассой; иначе брутто, как у бумажных книг.
    """
    ml = R.min_lev_of(book)
    sub = [r for r in recs if gate in (r.get("gates") or [])]
    gated = ([r for r in sub if float(r["lev"]) >= ml]
             if ml is not None else list(sub))
    keep, skipped = D6.one_per_name(gated)
    fld = "pnl_net" if net else "pnl"
    plan = [dict(r, pnl=float(r[fld])) for r in keep]
    rows = []
    c = D6.ration(plan, R.share(dep, book), deposit=dep,
                  min_notional=R.MIN_NOTIONAL, keep_rows=rows)
    st = PP._stats([{"exit_ts": r["exit_ts"], "at": r["at"], "sym": r["sym"],
                     "usd": float(r["pnl"]) * float(m)}
                    for (r, m) in rows], dep) or {}
    pnl = sorted(float(r["pnl"]) for (r, _m) in rows)
    levs = sorted(float(r["lev"]) for (r, _m) in rows)
    dep_v = sorted(int(r["depth"]) for (r, _m) in rows)
    ex = _exits(rows)
    n = len(rows) or 1
    return {"book": book, "deposit": dep, "gate": gate, "net": bool(net),
            "taken": c["taken"], "no_cash": c["no_cash"],
            "too_small": c["too_small"],
            "gate_dropped": len(sub) - len(gated),
            "skipped_repeats": skipped,
            "final": c["final"], "usd": st.get("usd"),
            "max_dd": st.get("max_dd"), "day_median": st.get("day_median"),
            "day_green": st.get("day_green"), "bite": st.get("bite"),
            "day_worst": st.get("day_worst"), "days": st.get("days"),
            "win": st.get("win"), "hold_med_h": st.get("hold_med_h"),
            "usd_wo_top3d": st.get("usd_wo_top3d"),
            "usd_wo_top": st.get("usd_wo_top"),
            "pnl_median": round(pnl[len(pnl) // 2], 5) if pnl else None,
            "pnl_mean": round(float(np.mean(pnl)), 5) if pnl else None,
            "worst_pos": round(pnl[0], 4) if pnl else None,
            "lev_median": round(levs[len(levs) // 2], 2) if levs else None,
            "depth_median": dep_v[len(dep_v) // 2] if dep_v else None,
            "exits": ex,
            "floor_share": round(ex.get("пол", 0) / n, 3),
            "liq_share": round(ex.get("ликвидация", 0) / n, 4),
            "take_share": round(ex.get("тейк", 0) / n, 3)}


def paired(rows_ref, rows_cell):
    """Парная разность исходов к точке отсчёта на ОБЩИХ решениях (доли маржи)."""
    a = {(r["sym"], round(r["at"], 3)): float(r["pnl"]) for r in rows_ref}
    d = [float(r["pnl"]) - a[(r["sym"], round(r["at"], 3))]
         for r in rows_cell if (r["sym"], round(r["at"], 3)) in a]
    if not d:
        return None
    d = np.array(d, dtype=float)
    return {"n": int(len(d)), "median": round(float(np.median(d)), 5),
            "mean": round(float(d.mean()), 5),
            "better": round(float(np.mean(d > 0)), 3)}


def halves(rows_by_cell):
    ts = sorted(float(r["at"]) for r in rows_by_cell[REF])
    if not ts:
        return None, {}, {}
    mid = ts[len(ts) // 2]
    a = {k: [r for r in v if float(r["at"]) < mid]
         for k, v in rows_by_cell.items()}
    b = {k: [r for r in v if float(r["at"]) >= mid]
         for k, v in rows_by_cell.items()}
    return mid, a, b


def lev_split(rows):
    """Диагностика D9 на этой выборке: без лестницы против лестницы."""
    out = {}
    for name, cond in (("no_ladder", lambda r: int(r["n_rungs"]) < 2),
                       ("ladder", lambda r: int(r["n_rungs"]) >= 2)):
        sub = [r for r in rows if cond(r)]
        pn = np.array([float(r["pnl"]) for r in sub], dtype=float)
        out[name] = {"n": len(sub),
                     "pnl_sum": round(float(pn.sum()), 4) if len(pn) else 0.0,
                     "lev_median": (round(float(np.median(
                         [float(r["lev"]) for r in sub])), 2) if sub else None)}
    return out


def _rss_mb():
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                     / 1024.0, 1)
    except Exception:
        return None


def _rss_now_mb():
    """Текущий RSS процесса в МБ (Linux); None — не прочитать."""
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    return round(int(ln.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


# Предел памяти прогона. Машина 7.7 ГБ без свопа: сборщик держит 1.5 ГБ,
# часовой цикл на шаге матрицы 3.3 ГБ; первый прогон D10 вырос до 2.1 ГБ,
# и ядро убивало ЦИКЛ (2026-09-06 18:07 и при каждом подъёме сторожем),
# а затем и сам прогон (код 137, 111 минут счёта потеряны). Прогон,
# перерастающий предел, останавливает себя сам, с числом и словами —
# это дешевле убитого цикла и неотличимой от тишины смерти.
MEM_LIMIT_MB = 1200


def mem_guard(where, log=print, limit=None):
    """Печатает RSS в точке `where`; выше предела — останавливает прогон."""
    lim = MEM_LIMIT_MB if limit is None else limit
    rss = _rss_now_mb()
    log(f"память: {rss} МБ ({where}; предел {lim})")
    if rss is not None and rss > lim:
        raise SystemExit(f"ОСТАНОВ: память {rss} МБ выше предела {lim} МБ "
                         f"({where}) — рядом сборщик и часовой цикл, "
                         "прогон снял себя сам, чтобы не убили цикл")
    return rss


# Ячейки, по которым читается ось гейта: правило книги и три ячейки 1×.
GATE_KEYS = [REF, "c1:struct:t2", "c1:none:t2", "c1:sigma:t2"]


def run(limit=None, src=None, log=print, legs=None):
    t0 = time.time()
    got = collect(limit=limit, src=src, log=log, legs=legs)
    log(f"пик памяти {_rss_mb()} МБ")
    sample, cells, pairs, half, split, gate_cells = {}, {}, {}, {}, {}, {}
    for rk in RULERS:
        rows, n_ok, lost = common_sample(got["recs"][rk], log=log)
        sample[rk] = {"n": n_ok, "lost": lost}
        got["recs"][rk] = rows
    dep = R.DEPOSITS[1]
    for book, rk in BOOK_RULER.items():
        rows = got["recs"][rk]
        for key in KEYS:
            for d in R.DEPOSITS:
                cells[f"{key}|{book}|{int(d)}"] = cell(rows[key], book, d)
            cells[f"{key}|{book}|{int(dep)}|net"] = cell(rows[key], book,
                                                        dep, net=True)
            pairs[f"{key}|{book}"] = paired(rows[REF], rows[key])
        for gk, _g in GATES:
            for key in GATE_KEYS:
                gate_cells[f"{gk}|{key}|{book}"] = cell(rows[key], book, dep,
                                                        gate=gk)
                gate_cells[f"{gk}|{key}|{book}|net"] = cell(
                    rows[key], book, dep, gate=gk, net=True)
        split[book] = lev_split([r for r in rows[REF]
                                 if REF_GATE in (r.get("gates") or [])])
        log(f"книга {book}: ячейки посчитаны")
    mid, ha, hb = halves(got["recs"]["optimal_s"])
    for key in KEYS:
        half[f"A:{key}"] = cell(ha[key], "optimal_s", dep)
        half[f"B:{key}"] = cell(hb[key], "optimal_s", dep)
    return {"cells": cells, "pairs": pairs, "half": half, "half_mid": mid,
            "gate_cells": gate_cells, "gate_keys": GATE_KEYS,
            "gates": [g for g, _ in GATES], "gate_counts": got["gate_counts"],
            "lev_split": split,
            "keys": KEYS, "ref": REF, "ref_gate": REF_GATE,
            "book_cell": book_cell(), "book_take": float(R.TAKE_MULT),
            "books": list(BOOK_RULER), "deposits": R.DEPOSITS,
            "round_cost_bp": ROUND_COST_BP, "spacing_sig": SPACING_SIG,
            "sample": sample, "positions": got["positions"],
            "skipped": got["skipped"], "window": got["window"],
            "hold_h": D2.HOLD_H, "weights": list(D2.WEIGHTS),
            "floor_frac": D2.FLOOR_FRAC,
            "rss_mb": _rss_mb(), "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


# --- чтение результата ---------------------------------------------------
def verdict(s):
    """Вердикт из ЧИСЕЛ: положительные ячейки (брутто и нетто), устойчивые
    к половинам, и лучше ли они нынешнего правила парно."""
    dep = int(s["deposits"][1])
    out = {"pos_gross": {}, "pos_net": {}, "stable_better": {}}
    for b in s["books"]:
        pg, pn, sb = [], [], []
        for k in s["keys"]:
            c = s["cells"].get(f"{k}|{b}|{dep}") or {}
            cn = s["cells"].get(f"{k}|{b}|{dep}|net") or {}
            ok_g = (c.get("final") or 0) > 0 and (c.get("day_median") or 0) >= 0
            ok_n = (cn.get("final") or 0) > 0 and (cn.get("day_median") or 0) >= 0
            if ok_g:
                pg.append(k)
            if ok_n:
                pn.append(k)
            if b == "optimal_s" and k != s["ref"]:
                p = s["pairs"].get(f"{k}|{b}") or {}
                a = s["half"].get(f"A:{k}") or {}
                bb = s["half"].get(f"B:{k}") or {}
                ra = s["half"].get(f"A:{s['ref']}") or {}
                rb = s["half"].get(f"B:{s['ref']}") or {}
                if ((p.get("median") or 0) > 0
                        and (a.get("final") or 0) > (ra.get("final") or 0)
                        and (bb.get("final") or 0) > (rb.get("final") or 0)):
                    sb.append(k)
        out["pos_gross"][b] = pg
        out["pos_net"][b] = pn
        if b == "optimal_s":
            out["stable_better"][b] = sb
    return out


def _p(x, d=2, sign=True):
    if x is None:
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{d}f} %"


def _u(x):
    return "—" if x is None else f"{x:+,.2f}"


def title_of(key):
    lk, ak, tk = key.split(":")
    return (f"{dict(LEVS)[lk]}, {dict(ADDS)[ak]}, "
            f"{ {k: t for (k, t, _m) in TAKES}[tk] }")


def _row(key, c, cn, p, mark):
    return (f"| `{key}`{mark} | {c.get('taken', '—')} | "
            f"{c.get('lev_median') if c.get('lev_median') is not None else '—'}× | "
            f"{_p(c.get('pnl_median'))} | {_p(c.get('pnl_mean'))} | "
            f"{_p(c.get('final'))} | {_p(cn.get('final'))} | "
            f"{_p(c.get('max_dd'))} | {_p(c.get('day_median'), 3)} | "
            f"{_p(c.get('day_green'), 0, sign=False)} | "
            f"{c.get('bite') if c.get('bite') is not None else '—'} | "
            f"{_p(c.get('take_share'), 0, sign=False)} / "
            f"{_p(c.get('floor_share'), 0, sign=False)} / "
            f"{_p(c.get('liq_share'), 1, sign=False)} | "
            f"{_p(c.get('worst_pos'), 1)} | "
            + (f"{_p(p.get('median'), 2)} ({_p(p.get('better'), 0, sign=False)})"
               if p else "—") + " |")


def report(s):
    w = s.get("window") or {}
    dep = int(s["deposits"][1])
    v = verdict(s)
    P = ["# D10 — короткие DCA-книги: плечо, доливы, цель, гейт", "",
         "Вопрос владельца 2026-09-06: «что мы можем затестить, чтобы "
         "вывести DCA-шорт-стратегии в плюс — запускай всё в тест». "
         "Механизм убытка измерен в D9: позиции без лестницы (1×) в сумме "
         "положительны, весь минус приносит лестница с плечом, которое "
         "забор выдаёт шорту из-за узкой лестницы вверх. Сетка объявлена "
         "ДО прогона и напечатана целиком: плечо {как забор, потолок 3×, "
         "2×, 1×} × доливы {структурные, без доливов, σ-сетка} × цель "
         "{×2 (сейчас), ×1, ×3} = 36 ячеек на книгу; отдельно ось гейта "
         "входа. Выбрать лучшую из 36 и предъявить её — ошибка R5: читать "
         "по форме и по парной разности к нынешнему правилу на тех же "
         "решениях.", "",
         f"Нынешнее правило книги — `{s['ref']}` "
         + (f"(ячейка правила книги `{s['book_cell']}`). "
            if s.get("book_cell") else
            "(действующий множитель цели вне сетки — ячейка книги не "
            "помечена). ")
         + "У руки без доливов плечо взято тем, что забор выдал "
         "СТРУКТУРНОЙ лестнице решения, — так плечо и доливы разделены; "
         "держит она ровно первый рунг (четверть нотионала: веса лестницы "
         "не нормируются, как у книги, — замер D8), то есть отвечает на "
         "«что было бы, не случись доливов» при том же размере входа; "
         "у σ-сетки забор считается на ней самой "
         f"(шаг {s['spacing_sig']:g} суточных σ, рунгов {len(s['weights'])}).",
         "",
         "**Издержки.** В бумажных DCA-книгах комиссии НЕТ — их числа "
         "брутто. Колонка «итог нетто» снимает круг "
         f"{s['round_cost_bp']:g} б.п. с заполненного нотионала (тейкер на "
         "каждом рунге и на выходе); проскальзывание не моделируется, "
         "funding — отдельный замер (`dca_paper/costs.py`). Знак книги "
         "обязан держаться ПОСЛЕ круга.", ""]
    if w:
        P += [f"Окно решений {w.get('from')} … {w.get('to')} UTC "
              f"({w.get('span_d')} суток, дат {w.get('dates')}); срок "
              f"удержания {s['hold_h']} ч, пол капитуляции "
              f"{s['floor_frac']:g}, веса лестницы {s['weights']}. "
              "Коротких ног по гейтам: "
              + ", ".join(f"{k} {n}" for k, n in s["gate_counts"].items())
              + ".", ""]
    sm = s.get("sample") or {}
    P += ["Выборка одна на все ячейки — решение годится, только если его "
          "позиция ЗАКРЫТА при КАЖДОЙ (и σ имени измерена): " +
          "; ".join(f"линейка {k} — {x['n']} решений, выброшено до {x['lost']}"
                    for k, x in sm.items()) + ".", ""]

    # раскладка D9 на этой выборке
    P += ["## Где убыток у нынешнего правила (гейт RR ≥ 2, доли маржи)", "",
          "| книга | без лестницы: n | Σ pnl | плечо | с лестницей: n | "
          "Σ pnl | плечо |", "|---|---:|---:|---:|---:|---:|---:|"]
    for b in s["books"]:
        sp = s["lev_split"].get(b) or {}
        a, l = sp.get("no_ladder") or {}, sp.get("ladder") or {}
        P.append(f"| {b} | {a.get('n', 0)} | {_p(a.get('pnl_sum'), 1)} | "
                 f"{a.get('lev_median') or '—'}× | {l.get('n', 0)} | "
                 f"{_p(l.get('pnl_sum'), 1)} | {l.get('lev_median') or '—'}× |")
    P.append("")

    for b in s["books"]:
        P += [f"## Книга «{R.ruler_title(b)}» ({b}), депозит ${dep:,}, "
              f"гейт {s['ref_gate']}", "",
              "| правило | взято | плечо | медиана позиции | среднее | "
              "итог брутто | итог нетто | просадка | медиана дня | зелёных | "
              "укус | тейк / пол / ликв | худшая позиция | "
              "Δ к правилу (доля лучше) |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
              "---:|---:|---:|"]
        for key in s["keys"]:
            c = s["cells"].get(f"{key}|{b}|{dep}") or {}
            cn = s["cells"].get(f"{key}|{b}|{dep}|net") or {}
            p = s["pairs"].get(f"{key}|{b}")
            mark = " ⟵ правило книги" if key == s["ref"] else ""
            P.append(_row(key, c, cn, p, mark))
        P += ["", f"Положительны по итогу и медиане дня: брутто "
              f"{len(v['pos_gross'][b])} ячеек из {len(s['keys'])}"
              + (" (" + ", ".join(f"`{k}`" for k in v["pos_gross"][b]) + ")"
                 if v["pos_gross"][b] else "")
              + f"; нетто {len(v['pos_net'][b])}"
              + (" (" + ", ".join(f"`{k}`" for k in v["pos_net"][b]) + ")"
                 if v["pos_net"][b] else "") + ".", ""]

    P += ["Расшифровка ключей: `плечо:доливы:цель`; "
          + "; ".join(f"`{k}` — {t}" for k, t in LEVS) + "; "
          + "; ".join(f"`{k}` — {t}" for k, t in ADDS) + "; "
          + "; ".join(f"`{k}` — {t}" for k, t, _m in TAKES) + ". "
          "«Δ к правилу» — парная медиана разности исходов (доли маржи) "
          "к нынешнему правилу на общих решениях и доля решений, где "
          "ячейка лучше.", ""]

    P += [f"## Ось гейта входа (депозит ${dep:,})", "",
          "Гейт меняет СОСТАВ решений, поэтому он не ячейка сетки, а "
          "отдельный разрез: по каждому гейту — нынешнее правило и три "
          "ячейки 1×. Ноги гейтов — подмножества одного прохода.", "",
          "| гейт | правило | книга | взято | итог брутто | итог нетто | "
          "просадка | медиана дня | зелёных | укус | тейк / пол / ликв | "
          "худшая позиция |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for gk in s["gates"]:
        for key in s["gate_keys"]:
            for b in s["books"]:
                c = s["gate_cells"].get(f"{gk}|{key}|{b}") or {}
                cn = s["gate_cells"].get(f"{gk}|{key}|{b}|net") or {}
                P.append(
                    f"| {gk} | `{key}` | {b} | {c.get('taken', '—')} | "
                    f"{_p(c.get('final'))} | {_p(cn.get('final'))} | "
                    f"{_p(c.get('max_dd'))} | {_p(c.get('day_median'), 3)} | "
                    f"{_p(c.get('day_green'), 0, sign=False)} | "
                    f"{c.get('bite') if c.get('bite') is not None else '—'} | "
                    f"{_p(c.get('take_share'), 0, sign=False)} / "
                    f"{_p(c.get('floor_share'), 0, sign=False)} / "
                    f"{_p(c.get('liq_share'), 1, sign=False)} | "
                    f"{_p(c.get('worst_pos'), 1)} |")
    P.append("")

    P += [f"## Половины окна (книга optimal_s, ${dep:,}, гейт {s['ref_gate']})",
          "", "| правило | A итог | A медиана дня | B итог | B медиана дня |",
          "|---|---:|---:|---:|---:|"]
    for key in s["keys"]:
        a = s["half"].get(f"A:{key}") or {}
        bb = s["half"].get(f"B:{key}") or {}
        P.append(f"| `{key}` | {_p(a.get('final'))} | "
                 f"{_p(a.get('day_median'), 3)} | {_p(bb.get('final'))} | "
                 f"{_p(bb.get('day_median'), 3)} |")
    sb = v["stable_better"].get("optimal_s") or []
    P += ["", "Устойчиво лучше нынешнего правила у `optimal_s` (парная "
          "медиана > 0 и итог выше правила в обеих половинах): "
          f"{len(sb)} ячеек из {len(s['keys']) - 1}"
          + (" — " + ", ".join(f"`{k}`" for k in sb) if sb else "") + ".", "",
          "## Чего этот замер НЕ говорит", "",
          "Правил книг он не меняет — это решение владельца. Веса модели "
          "видели эти часы (оценка сверху); окно записи одно, режим рынка "
          "один; коротких решений в разы меньше длинных, и часть ячеек "
          "стоит на десятках позиций. Проскальзывания и funding в числах "
          "нет; хвост шорта не ограничен сверху, и ячейка без единой "
          "ликвидации на этом окне не есть ячейка без ликвидаций. Ось "
          "гейта меняет состав решений — её ячейки не парны сетке.", ""]
    return "\n".join(P)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)          # каталог создаётся ДО счёта
    # Строки прогресса и памяти обязаны доходить до лога ДО смерти
    # процесса: буфер stdout при SIGKILL теряется целиком — первый прогон
    # умер через 111 минут, не оставив ни одной строки.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    s = run(limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    with open(os.path.join(OUT, f"D10-short-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"D10-short-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D10: короткие DCA-книги — плечо, доливы, цель, гейт ({tag})")


if __name__ == "__main__":
    main()
