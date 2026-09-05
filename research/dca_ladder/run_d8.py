#!/usr/bin/env python3
"""D8 — замер ТЕЙКА DCA-книги (вопрос владельца 2026-09-05).

Вопрос: «тейки слишком короткие получаются, по две копейки; желательно
чтобы тейк был динамическим, так как ТВХ у нас тоже динамическая».

Нынешнее правило: `take_px = вход · (1 + mfe)`, то есть НЕПОДВИЖНАЯ цена,
привязанная к цене БАЗЫ. ТВХ при этом едет вниз с каждым доливом, и цель
за ней не идёт. Сетка объявлена ДО прогона и печатается ЦЕЛИКОМ:

    якорь  entry (нынешний) | avg (от плавающей ТВХ)
    цель   обещание mfe ×1 / ×1.5 / ×2 / ×3;  σ_сут имени ×1 / ×2
    трейл  взвод на обещании, шаг трейла 0.5 и 1.0 обещания (якорь avg)
    норм.  диагностическая рука: веса лестницы нормированы на единицу

Выбрать лучшую ячейку из семнадцати и предъявить её было бы ошибкой R5
(при 96 ячейках лучшая ПУСТЫШКА давала Sharpe 1.19). Поэтому это ЗОНД:
порогов и вердикта нет, решение о правиле — за владельцем, и читать
таблицу надо по форме (медиана дня, зелёные, укус, просадка), а не по
максимуму итога.

**Почему «две копейки» может быть НЕ про тейк.** Веса лестницы —
`[0.25]×4` и НЕ нормируются: позиция, у которой структурных уровней
нашлось меньше четырёх, вкладывает `сумма весов × нотионал`, а при
одном рунге — ровно четверть. Тейк по ТВХ платит тождественно
`заполненный нотионал × доля` (закреплено тестом ядра), значит при
глубине 1 он даёт четверть того, на что лестница сайзилась. Поэтому
рядом с сеткой тейков идёт диагностическая рука `norm`: те же правила
при весах, нормированных на единицу. Если «копейки» делает она, а не
цель, то двигать надо размер, а не тейк.

**Одна выборка на все ячейки.** Решение годится, только если его позиция
ЗАКРЫТА при КАЖДОЙ ячейке: под длинным тейком часть позиций упирается в
конец записи, и судить их «по сроку» значило бы мерить длину записи, а
не правило. Сколько выброшено — печатается числом.

**Касса та же, что у бумажных книг.** Тейк меняет оборот: позиция,
вышедшая позже, держит слот и отказывает новым сигналам, — поэтому
каждая ячейка идёт через `D6.ration` с билетом режима, а форма считается
тем же `run_paper._stats`, что печатает страница наблюдения. Второй
реализации ни кассы, ни формы здесь нет.

Оговорка про просадку: почасовая переоценка (`marks`) здесь НЕ копится —
на семнадцати ячейках это сотни мегабайт рядом с живым сбором, — поэтому
просадка считается по РЕАЛИЗОВАННЫМ суткам (та же, что в таблице дней на
странице книги). С почасовой просадкой артефакта бумажной книги её
сравнивать нельзя; между ячейками она сравнима, а это и есть предмет.

Прогон: `run research/dca_ladder/run_d8.py`. Смоук: `--limit 400`.
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
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import run_d5 as D5                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as PP                                        # noqa: E402

OUT = os.path.join(HERE, "out")
HOUR = 3600

# --- сетка объявлена ДО прогона ----------------------------------------
# Цель задаётся ДОЛЕЙ цены; откуда доля берётся — вторая ось. Обещание
# модели (`mfe`) считано на горизонте СИГНАЛА (4 ч), а позиция живёт до
# 72 ч, поэтому множители обещания и мера в собственных σ имени стоят
# рядом: первая проверяет «цель просто коротка», вторая — «цель
# откалибрована не на тот горизонт».
TARGETS = [
    ("fav", "обещание mfe", lambda fav, sig: fav),
    ("fav1.5", "обещание ×1.5", lambda fav, sig: 1.5 * fav),
    ("fav2", "обещание ×2", lambda fav, sig: 2.0 * fav),
    ("fav3", "обещание ×3", lambda fav, sig: 3.0 * fav),
    ("sig1", "1 суточная σ", lambda fav, sig: sig),
    ("sig2", "2 суточных σ", lambda fav, sig: 2.0 * sig),
]
ANCHORS = [("e", "entry"), ("a", "avg")]
# Трейлинг: взвод на обещании, дальше шаг трейла долей ОБЕЩАНИЯ. Якорь
# только `avg` — у трейла цель не уровень выхода, а порог взвода, и
# привязывать её к неподвижному входу незачем.
TRAILS = [0.5, 1.0]
# Диагностическая рука: нормированные веса. Ячейки объявлены, а не
# выбраны по результату; `fav2` взят затем, чтобы видеть, складываются
# ли размер и цель или подменяют друг друга.
NORM_CELLS = [("e", "fav"), ("a", "fav"), ("a", "fav2")]
REF = "e:fav"                              # правило книги ДО правки 2026-09-05


def book_cell():
    """Ключ ячейки, равной ДЕЙСТВУЮЩЕМУ правилу книги. None — её нет в сетке.

    Выводится из самого правила (`rules.TAKE_ANCHOR`/`TAKE_MULT`), а не
    записывается числом: правило меняется, и вторая запись о том, какая
    ячейка ему равна, однажды разошлась бы — отчёт помечал бы «нынешним»
    то, чем книга не торгует. Правило вне объявленной сетки ячейки не
    имеет вовсе, и это честнее, чем помечать ближайшую.
    """
    ak = {"entry": "e", "avg": "a"}.get(R.TAKE_ANCHOR)
    tk = {1.0: "fav", 1.5: "fav1.5", 2.0: "fav2", 3.0: "fav3"}.get(
        float(R.TAKE_MULT))
    key = f"{ak}:{tk}" if (ak and tk) else None
    return key if key in {c[0] for c in CELLS} else None


def grid():
    """Все объявленные ячейки: ключ → (якорь, цель, трейл, нормировка)."""
    out = []
    for ak, anchor in ANCHORS:
        for tk, _t, _fn in TARGETS:
            out.append((f"{ak}:{tk}", anchor, tk, None, False))
    for tr in TRAILS:
        out.append((f"a:fav/tr{tr:g}", "avg", "fav", tr, False))
    for ak, tk in NORM_CELLS:
        anchor = dict(ANCHORS)[ak]
        out.append((f"n|{ak}:{tk}", anchor, tk, None, True))
    return out


CELLS = grid()
TARGET_FN = {k: fn for (k, _t, fn) in TARGETS}
TARGET_TITLE = {k: t for (k, t, _fn) in TARGETS}
assert REF in {c[0] for c in CELLS}, "точки отсчёта нет в сетке"
# Линейки забора: считаются обе, что ведут книги. «Агрессивная» своей
# линейки не имеет — она есть «оптимальная» плюс гейт плеча, и потому
# выводится из тех же позиций, а не считается третьим проходом.
RULERS = {"safe": (R.RULERS["safe"]["rule"], R.RULERS["safe"]["param"]),
          "optimal": (R.RULERS["optimal"]["rule"],
                      R.RULERS["optimal"]["param"])}
BOOK_RULER = {"safe": "safe", "optimal": "optimal", "aggr": "optimal"}


def norm_weights(n):
    """Веса лестницы, нормированные на единицу: вкладывается ВЕСЬ нотионал."""
    w = list(D2.WEIGHTS[:n])
    s = sum(w)
    return [x / s for x in w] if s > 0 else w


def one_position(g, bars, ts, look, rule, param):
    """Исход одного решения во ВСЕХ ячейках сетки. None — измерить нечем.

    Геометрия (окно, уровни, рунги, σ, плечо) считается ОДИН раз на
    решение: между ячейками различается ровно правило тейка, и пересчёт
    геометрии на каждую означал бы, что ячейки могут разойтись не по той
    причине, ради которой их сравнивают.
    """
    rs = D2.split_window(bars, ts, g["at"], D2.BACK_H, D2.HOLD_H)
    if rs is None:
        return None
    win, now_i = rs
    hold = win[now_i:]
    entry = float(hold[0][1])
    if entry <= 0:
        return None
    fav = float(g["fav"]) / 1e4
    stop_px = entry * (1 + g["adv_q"] / 1e4)
    if not (fav > 0 and 0 < stop_px < entry):
        return None
    lv = D2.build_levels(win, now_i)
    rungs_full = D2.structural_rungs(entry, list(lv), D2.MIN_ADD_GAP,
                                     D2.N_RUNGS)
    sigma_bp, _r, _t = D3.window_stats(win, now_i)
    sig = D5.sigma_day(sigma_bp)
    if sig is None or not sig > 0:
        # σ не измерена — половина сетки не считается вовсе. «Не
        # измерено» не есть ноль: подставив нулевую σ, мы дали бы такому
        # имени тейк в ноль процентов, то есть мгновенный выход.
        return None
    geo = {}
    for norm in (False, True):
        w_full = (norm_weights(len(rungs_full)) if norm
                  else D2.WEIGHTS[:len(rungs_full)])
        lev, rungs, _b = D5.fence_leverage(rule, param, entry, rungs_full,
                                           look, sigma_bp,
                                           weights=w_full if norm else None)
        w = (norm_weights(len(rungs)) if norm else D2.WEIGHTS[:len(rungs)])
        geo[norm] = (lev, rungs, w)
    out = {}
    for (key, anchor, tk, trail, norm) in CELLS:
        lev, rungs, w = geo[norm]
        frac = TARGET_FN[tk](fav, sig)
        if not frac > 0:
            continue
        tr = {"anchor": anchor, "frac": frac}
        if trail:
            tr["trail"] = trail * frac
        r = L.simulate_dca(hold, rungs, w, 1.0, lev, look(1.0 * lev),
                           take_rule=tr, floor_frac=D2.FLOOR_FRAC)
        out[key] = {
            "at": float(g["at"]), "exit_ts": float(r["exit_ts"]),
            "pnl": float(r["pnl_frac"]), "lev": float(lev),
            "fwd": abs(float(g["fwd"])), "sym": g["sym"],
            "exit": r["exit"], "marks": [],
            "end_ts": float(hold[-1][0]),
            "sched_end": float(g["at"]) + D2.HOLD_H * HOUR,
            "depth": int(r["depth"]), "avg": float(r["avg"]),
            "entry_px": entry, "exit_px": float(r["exit_px"]),
            "filled": float(r["filled_notional"]),
            "frac": frac, "fav": fav, "sig": sig}
    return out


def collect(limit=None, src=None, log=print, legs=None):
    """Дорогой проход: бары символа читаются ОДИН раз на все ячейки."""
    get = src.bars if src else (lambda s, a, b: D6.SW.read_bars(
        D6.ROOT_B1, s, a, b))
    tiers_all = D2.instruments_tiers()
    longs = (list(legs)[:limit] if legs is not None
             else D6.gated_legs(limit=limit, log=log))
    by_sym = {}
    for g in longs:
        by_sym.setdefault(g["sym"], []).append(g)
    win = D6.window(longs)
    log(f"лонгов под гейтом {len(longs)}, символов {len(by_sym)}")
    if win:
        log(f"окно решений {win['from']} … {win['to']} UTC "
            f"({win['span_d']:g} суток, дат {win['dates']})")
    recs = {rk: {c[0]: [] for c in CELLS} for rk in RULERS}
    n, skipped = 0, 0
    said, done = time.time(), 0
    for sym, glist in by_sym.items():
        done += 1
        if time.time() - said > 30:
            log(f"  символ {done}/{len(by_sym)}  решений {n}")
            said = time.time()
        a0 = min(gg["at"] for gg in glist) - D2.BACK_H * HOUR
        b1 = max(gg["at"] for gg in glist) + D2.HOLD_H * HOUR
        bars = get(sym, a0, b1)
        if not bars:
            skipped += len(glist)
            continue
        ts = [bb[0] for bb in bars]
        tiers = tiers_all.get(sym) or []
        look = lambda notl: L.mmr_for_notional(tiers, notl, flat=D2.FLAT_MMR)
        for g in glist:
            got = 0
            for rk, (rule, param) in RULERS.items():
                o = one_position(g, bars, ts, look, rule, param)
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
            "window": win, "data_end": data_end}


def common_sample(recs, log=print):
    """Решения, ЗАКРЫТЫЕ при каждой ячейке. Остальные — числом.

    Под длинным тейком часть позиций упирается в конец записи, и выдать
    это за исход «по сроку» значило бы измерить длину записи, а не
    правило. Выборка обязана быть одна, иначе ячейки судятся по разным
    сделкам.
    """
    keys = [c[0] for c in CELLS]
    ok = None
    for k in keys:
        s = {(r["sym"], round(r["at"], 3)) for r in recs[k]
             if r.get("state") == "closed"}
        ok = s if ok is None else (ok & s)
    ok = ok or set()
    out, lost = {}, 0
    for k in keys:
        kept = [r for r in recs[k]
                if (r["sym"], round(r["at"], 3)) in ok]
        lost = max(lost, len(recs[k]) - len(kept))
        out[k] = kept
    log(f"общая выборка: {len(ok)} решений, выброшено до {lost} "
        f"(не закрыты при какой-то ячейке)")
    return out, len(ok), lost


def _exits(rows):
    out = {}
    for (r, _m) in rows:
        out[r["exit"]] = out.get(r["exit"], 0) + 1
    return out


def cell(recs, book, dep):
    """Одна ячейка «правило тейка × книга × депозит»: касса книги."""
    rk = BOOK_RULER[book]
    ml = R.min_lev_of(book)
    gated = ([r for r in recs if float(r["lev"]) >= ml]
             if ml is not None else list(recs))
    keep, skipped = D6.one_per_name(gated)
    rows = []
    c = D6.ration(keep, R.share(dep, book), deposit=dep,
                  min_notional=R.MIN_NOTIONAL, keep_rows=rows)
    st = PP._stats([{"exit_ts": r["exit_ts"], "at": r["at"], "sym": r["sym"],
                     "usd": float(r["pnl"]) * float(m)}
                    for (r, m) in rows], dep) or {}
    pnl = sorted(float(r["pnl"]) for (r, _m) in rows)
    dep_v = sorted(int(r["depth"]) for (r, _m) in rows)
    fil = sorted(float(r["filled"]) for (r, _m) in rows)
    frac = sorted(float(r["frac"]) for (r, _m) in rows)
    ex = _exits(rows)
    n = len(rows) or 1
    return {"book": book, "deposit": dep, "taken": c["taken"],
            "no_cash": c["no_cash"], "too_small": c["too_small"],
            "gate_dropped": len(recs) - len(gated),
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
            "depth_median": dep_v[len(dep_v) // 2] if dep_v else None,
            "filled_median": (round(fil[len(fil) // 2], 3) if fil else None),
            "frac_median": (round(frac[len(frac) // 2] * 100, 2)
                            if frac else None),
            "exits": ex,
            "take_share": round((ex.get("тейк", 0) + ex.get("трейл", 0)) / n,
                                3),
            "liq_share": round(ex.get("ликвидация", 0) / n, 4),
            "usd_per_take": (round(sum(float(r["pnl"]) * float(m)
                                       for (r, m) in rows
                                       if r["exit"] in ("тейк", "трейл"))
                                   / max(1, ex.get("тейк", 0)
                                         + ex.get("трейл", 0)), 4))}


def diagnosis(recs, book, dep):
    """Разложение «двух копеек» у нынешнего правила — не ось, а объяснение.

    Тейк по ТВХ платит тождественно `заполненный нотионал × доля`. У
    якоря входа тождества нет (цель стоит выше ТВХ), но порядок величины
    задают те же два множителя, и здесь видно, какой из них короток.
    """
    rk = BOOK_RULER[book]
    ml = R.min_lev_of(book)
    gated = ([r for r in recs if float(r["lev"]) >= ml]
             if ml is not None else list(recs))
    keep, _s = D6.one_per_name(gated)
    rows = []
    D6.ration(keep, R.share(dep, book), deposit=dep,
              min_notional=R.MIN_NOTIONAL, keep_rows=rows)
    tk = [r for (r, _m) in rows if r["exit"] == "тейк"]
    if not tk:
        return None
    med = lambda xs: float(np.median(np.array(xs, dtype=float)))
    dpt = [r["depth"] for r in tk]
    return {"book": book, "takes": len(tk),
            "depth_median": med(dpt),
            "depth1_share": round(sum(1 for d in dpt if d == 1) / len(dpt), 3),
            "lev_median": round(med([r["lev"] for r in tk]), 2),
            "filled_median": round(med([r["filled"] for r in tk]), 3),
            "fav_median_pct": round(med([r["fav"] for r in tk]) * 100, 2),
            "sig_median_pct": round(med([r["sig"] for r in tk]) * 100, 2),
            "pnl_median_pct": round(med([r["pnl"] for r in tk]) * 100, 3),
            # то, что тейк по ТВХ дал бы РОВНО: заполненный нотионал × доля
            "identity_pct": round(med([r["filled"] * r["fav"] for r in tk])
                                  * 100, 3)}


def halves(rows_by_cell):
    """Разрез выборки надвое по времени решения — проверка на шум окна."""
    ts = sorted(float(r["at"]) for r in rows_by_cell[REF])
    if not ts:
        return None, {}, {}
    mid = ts[len(ts) // 2]
    a = {k: [r for r in v if float(r["at"]) < mid]
         for k, v in rows_by_cell.items()}
    b = {k: [r for r in v if float(r["at"]) >= mid]
         for k, v in rows_by_cell.items()}
    return mid, a, b


def _rss_mb():
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                     / 1024.0, 1)
    except Exception:
        return None


def run(limit=None, src=None, log=print, legs=None):
    t0 = time.time()
    got = collect(limit=limit, src=src, log=log, legs=legs)
    log(f"пик памяти {_rss_mb()} МБ")
    cells, diag, half = {}, {}, {}
    sample = {}
    for rk in RULERS:
        rows, n_ok, lost = common_sample(got["recs"][rk], log=log)
        sample[rk] = {"n": n_ok, "lost": lost}
        got["recs"][rk] = rows
    for book, rk in BOOK_RULER.items():
        rows = got["recs"][rk]
        for key in (c[0] for c in CELLS):
            for dep in R.DEPOSITS:
                cells[f"{key}|{book}|{int(dep)}"] = cell(rows[key], book, dep)
        d = diagnosis(rows[REF], book, R.DEPOSITS[1])
        if d:
            diag[book] = d
        log(f"книга {book}: ячейки посчитаны")
    mid, ha, hb = halves(got["recs"]["optimal"])
    for key in (c[0] for c in CELLS):
        half[f"A:{key}"] = cell(ha[key], "optimal", R.DEPOSITS[1])
        half[f"B:{key}"] = cell(hb[key], "optimal", R.DEPOSITS[1])
    return {"cells": cells, "diag": diag, "half": half, "half_mid": mid,
            "keys": [c[0] for c in CELLS], "ref": REF,
            "book_cell": book_cell(),
            "book_take": [R.TAKE_ANCHOR, R.TAKE_MULT],
            "books": list(BOOK_RULER), "deposits": R.DEPOSITS,
            "sample": sample, "positions": got["positions"],
            "skipped": got["skipped"], "window": got["window"],
            "hold_h": D2.HOLD_H, "weights": list(D2.WEIGHTS),
            "rss_mb": _rss_mb(),
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def _p(x, d=2, sign=True):
    if x is None:
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{d}f} %"


def _u(x):
    return "—" if x is None else f"{x:+,.2f}"


def title_of(key):
    if key.startswith("n|"):
        rest = key[2:]
        a, t = rest.split(":")
        return (f"нормированные веса, якорь "
                f"{'входа' if a == 'e' else 'ТВХ'}, {TARGET_TITLE[t]}")
    if "/tr" in key:
        tr = key.split("/tr")[1]
        return f"трейл от ТВХ: взвод на обещании, шаг {tr} обещания"
    a, t = key.split(":")
    return (f"якорь {'входа' if a == 'e' else 'ТВХ'}, {TARGET_TITLE[t]}")


def report(s):
    w = s.get("window") or {}
    ref = s["ref"]
    P = ["# D8 — тейк DCA-книги: сетка правил", "",
         "Вопрос владельца: «тейки слишком короткие получаются, по две "
         "копейки; желательно чтобы тейк был динамическим, так как ТВХ у "
         "нас тоже динамическая».", "",
         f"Правило, с которого начинали (`{ref}`), — цена "
         "`вход · (1 + mfe)`, **неподвижная** и привязанная к цене базы: "
         "ТВХ едет вниз с каждым доливом, цель за ней не идёт. "
         + (f"Книга сейчас торгует `{s['book_cell']}` "
            f"(якорь {s['book_take'][0]}, обещание ×{s['book_take'][1]:g}). "
            if s.get("book_cell") else
            "Действующее правило книги в объявленной сетке отсутствует, "
            "поэтому «правило книги» здесь не помечено ничем. ")
         + "Сетка объявлена ДО "
         "прогона и напечатана целиком; выбрать лучшую ячейку из "
         f"{len(s['keys'])} и предъявить её было бы ошибкой R5, поэтому "
         "это ЗОНД — порогов и вердикта здесь нет, решение о правиле за "
         "владельцем.", "",
         "**Что меряется.** Тейк меняет ОБОРОТ книги: позиция, вышедшая "
         "позже, держит слот и отказывает новым сигналам по кассе. "
         "Поэтому каждая ячейка идёт через ту же кассу, что ведёт "
         "бумажные книги, с билетом своего режима, а форма считается тем "
         "же кодом, что печатает страница наблюдения.", ""]
    if w:
        P += [f"Окно решений {w.get('from')} … {w.get('to')} UTC "
              f"({w.get('span_d')} суток, дат {w.get('dates')}); "
              f"срок удержания {s.get('hold_h')} ч, веса лестницы "
              f"{s.get('weights')}.", ""]
    sm = s.get("sample") or {}
    P += ["Выборка одна на все ячейки — решение годится, только если его "
          "позиция ЗАКРЫТА при КАЖДОЙ: " +
          "; ".join(f"линейка {k} — {v['n']} решений, выброшено до "
                    f"{v['lost']}" for k, v in sm.items()) + ".", "",
          "Просадка здесь считается по РЕАЛИЗОВАННЫМ суткам (та же, что в "
          "таблице дней на странице книги), а не почасовой переоценкой: "
          "на семнадцати ячейках почасовые отметки весят сотни мегабайт "
          "рядом с живым сбором. С почасовой просадкой артефакта "
          "бумажной книги её сравнивать нельзя; между ячейками она "
          "сравнима, а это и есть предмет.", ""]

    d = s.get("diag") or {}
    if d:
        P += ["## Откуда «две копейки» (диагностика нынешнего правила)", "",
              "Тейк по ТВХ платит тождественно `заполненный нотионал × "
              "доля цели` — это закреплено тестом ядра. У якоря входа "
              "тождества нет, но порядок величины задают те же два "
              "множителя, и таблица показывает, который из них короток. "
              "Веса лестницы `[0.25]×4` НЕ нормируются: у позиции, "
              "которой структурных уровней нашлось меньше четырёх, "
              "простаивает соответствующая доля объявленного нотионала.",
              "",
              "| книга | тейков | медиана глубины | доля глубины 1 | "
              "медиана плеча | заполнено нотионала | обещание mfe | "
              "σ суточная | медиана тейка | «нотионал × обещание» |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for b in s["books"]:
            v = d.get(b)
            if not v:
                continue
            P.append(f"| {b} | {v['takes']} | {v['depth_median']:g} | "
                     f"{v['depth1_share']*100:.0f} % | {v['lev_median']}× | "
                     f"{v['filled_median']}× | {v['fav_median_pct']:.2f} % | "
                     f"{v['sig_median_pct']:.2f} % | "
                     f"{v['pnl_median_pct']:+.3f} % | "
                     f"{v['identity_pct']:+.3f} % |")
        P += ["", "«Заполнено нотионала» — доля капитала позиции, которая "
              "реально работает (плечо × сумма весов заполненных рунгов). "
              "Если она заметно меньше плеча, копейки делает не цель, а "
              "простаивающий капитал, и двигать надо размер, а не тейк — "
              "ровно это и проверяет диагностическая рука `n|…` в сетке "
              "ниже.", ""]

    dep = s["deposits"][1]
    for b in s["books"]:
        P += [f"## Книга «{R.ruler_title(b)}» ({b}), депозит ${dep:,.0f}", "",
              "| правило | взято | доля выходов по цели | медиана позиции | "
              "среднее | итог | просадка | медиана дня | зелёных | укус | "
              "побед | медиана удержания | \\$ на тейк | \\$ без 3 лучших дней "
              "| худшая позиция | ликвидаций |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
              "---:|---:|---:|---:|---:|"]
        for key in s["keys"]:
            c = s["cells"].get(f"{key}|{b}|{int(dep)}") or {}
            mark = ""
            if key == s.get("book_cell"):
                mark = " ⟵ правило книги"
            elif key == ref:
                mark = " ⟵ правило до 2026-09-05"
            P.append(
                f"| `{key}`{mark} | {c.get('taken', '—')} | "
                f"{_p(c.get('take_share'), 0, sign=False)} | "
                f"{_p(c.get('pnl_median'))} | {_p(c.get('pnl_mean'))} | "
                f"{_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                f"{_p(c.get('day_median'), 3)} | "
                f"{_p(c.get('day_green'), 0, sign=False)} | "
                f"{c.get('bite') if c.get('bite') is not None else '—'} | "
                f"{_p(c.get('win'), 0, sign=False)} | "
                f"{c.get('hold_med_h') if c.get('hold_med_h') is not None else '—'} ч | "
                f"{_u(c.get('usd_per_take'))} | {_u(c.get('usd_wo_top3d'))} | "
                f"{_p(c.get('worst_pos'), 1)} | "
                f"{_p(c.get('liq_share'), 2, sign=False)} |")
        P.append("")
    P += ["Расшифровка ключей: "
          + "; ".join(f"`{k}` — {title_of(k)}" for k in s["keys"]), ""]

    P += [f"## Тот же разрез по депозитам (книга «оптимальная»)", "",
          "| правило | " + " | ".join(f"${int(x):,} итог"
                                      for x in s["deposits"]) + " |",
          "|---|" + "---:|" * len(s["deposits"])]
    for key in s["keys"]:
        row = [f"| `{key}` "]
        for x in s["deposits"]:
            c = s["cells"].get(f"{key}|optimal|{int(x)}") or {}
            row.append(f"| {_p(c.get('final'))} ")
        P.append("".join(row) + "|")
    P.append("")

    P += ["## Половины окна (книга «оптимальная», $%s)" % f"{int(dep):,}", "",
          "Купол на одном окне может быть свойством правила, а может — "
          "свойством этих суток. Половины не складываются в целое: у "
          "каждой своя касса с полного депозита, то есть это две "
          "независимые книги по половине календаря.", "",
          "| правило | A итог | A медиана дня | B итог | B медиана дня |",
          "|---|---:|---:|---:|---:|"]
    for key in s["keys"]:
        a = s["half"].get(f"A:{key}") or {}
        b = s["half"].get(f"B:{key}") or {}
        P.append(f"| `{key}` | {_p(a.get('final'))} | "
                 f"{_p(a.get('day_median'), 3)} | {_p(b.get('final'))} | "
                 f"{_p(b.get('day_median'), 3)} |")
    P += ["", "## Чего этот замер НЕ говорит", "",
          "Правил книги он не меняет — это решение владельца. Веса модели "
          "видели эти часы, значит оценка читается СВЕРХУ. Окно записи "
          "одно и режим рынка один. Живого исполнения нет: сделки "
          "считаются реплеем по барам записи, а трейл исполняется "
          "рыночно, по `min(закрытие бара, уровень трейла)` — на "
          "минутных барах это приближение, и в разрыве настоящий выход "
          "был бы хуже. Гейт кассы «мельче биржевого пола» считается по "
          f"доле рунга `{R.RUNG_SHARE:g}` и у нормированной руки поэтому "
          "строже, чем нужно, — то есть её числа занижены, а не "
          "завышены.", ""]
    return "\n".join(P)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)          # каталог создаётся ДО счёта
    s = run(limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    with open(os.path.join(OUT, f"D8-take-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"D8-take-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D8: замер тейка DCA ({tag})")


if __name__ == "__main__":
    main()
