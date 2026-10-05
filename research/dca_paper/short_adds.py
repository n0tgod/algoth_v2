#!/usr/bin/env python3
"""Доливы в прибыльный шорт: заполнить зарезервированные ступени по триггеру.

Решение владельца 2026-10-05 («давай затестим»): докидывать в плюсовые
шорты, уменьшив начальный билет так, чтобы позиция состояла из нескольких
входов, и докидывать не по лесенке, а по аномалии. Структурный факт, с
которого начинается замер: короткая книга `h24` УЖЕ резервирует маржу на
четыре ступени (`run_d2.N_RUNGS`, веса по 0.25) и заполняет только первую
— три четверти маржи лежат без дела всю позицию. «Долив» здесь есть
заполнение второй ступени в сторону прибыли; касса и слоты не трогаются,
лишней маржи не нужно.

Первый взгляд — по записям кэша (отметки pnl по часам у каждой позиции),
без реплея ядра; оси объявлены до прогона:

- **P — прибыль**: вторая ступень в первый час, когда pnl родителя ≥
  +10 / +25 / +50 % зарезервированной маржи.
- **R — повторный выбор модели**: лист `h24` выбрал то же имя снова,
  пока позиция открыта (сейчас касса такие входы пропускает, правило
  «одна на имя»); `R+` — то же, но только если родитель в плюсе.
- **M — аномалия «имя слабее рынка»**: родитель в плюсе И ход имени с
  входа ниже волны рынка (средний ход 20 прокси-имён S8) на ≥ 1 / 2 %.

Долив — та же доля нотионала, что у базовой ступени (четверть × плечо).
Считается ВСЯ позиция: после долива pnl идёт вдвое быстрее, и общий пол
капитуляции (−90 % маржи у безопасной линейки, −50 % у оптимальной)
достигается при вдвое меньшем ходе против — по часовым отметкам, с
оговоркой часа. Величина ячейки — приращение денег позиции от долива
(с доливом минус без), нетто круга издержек на нотионал долива; позиции,
добитые доливом раньше своего выхода, считаются отдельно.

Судьи два: случайные позиции, ОТКРЫТЫЕ в те же часы, столько же, с тем же
доливом (200 зёрен), и то же среди открытых В ПЛЮСЕ — триггер обязан
выбирать продолжение лучше случайного открытого, иначе он измерял бы не
аномалию, а то, что любая живая позиция в среднем дотягивает в плюс. Для `R` рядом — касса: повторы
разрешены как СВОИ позиции (`rules.ONE_PER_NAME` снят на время счёта), с
деньгами, просадкой и σ дня на $10k.
"""
import argparse
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
import run_d10 as D10                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import path_screen as P                                       # noqa: E402
import short_levers as L                                      # noqa: E402
import tail_screen as T                                       # noqa: E402
import wave as WV                                             # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-adds"
SEEDS = 200                       # объявлено до прогона
MAIN_DEP = 10000
HOUR = 3600.0
BOOK_KEYS = list(S.BOOKS)
TAIL_EXITS = T.TAIL_EXITS
PROFIT = (0.10, 0.25, 0.50)       # доля зарезервированной маржи
WEAK = (0.01, 0.02)               # имя слабее рынка на ≥ r (доля цены)
BASE_SHARE = 0.25                 # доля нотионала базовой ступени, если запись её не несёт
CELLS = ([("P", f"прибыль ≥ +{int(100 * x)} %", x) for x in PROFIT]
         + [("R", "повторный выбор модели", None), ("R+", "повтор при родителе в плюсе", None)]
         + [("M", f"в плюсе и слабее рынка на ≥ {int(100 * r)} %", r) for r in WEAK])


def share_of(rec):
    """Доля нотионала базовой ступени — из заполнений записи."""
    f = rec.get("fills") or []
    try:
        s = float(f[0][2])
        return s if s > 0 else BASE_SHARE
    except (TypeError, ValueError, IndexError):
        return BASE_SHARE


def view_lite(rec, mkt):
    """Путь по отметкам и ход имени против волны рынка по часам — без β."""
    p = WV.path_of(rec)
    at, sym = float(rec["at"]), rec["sym"]
    t_in = at - 1.0
    excess = {}
    if p:
        for k in range(1, p["K"] + 1):
            t = t_in + k * HOUR
            own, wave = mkt.move(sym, t_in, t), mkt.wave(t_in, t)
            excess[k] = (own - wave) if (own is not None and wave is not None) else None
    return {"rec": rec, "path": p, "tail": T.is_tail(rec), "excess": excess,
            "wave": {}, "resid": {}}


def repeats_of(cache, legs_):
    """{ключ родителя: [часы повторных выборов]} — лист выбрал то же имя при открытой позиции.

    Час повтора — первая отметка родителя, час которой не раньше момента
    повтора; повтор в час выхода и позже не считается (долива уже не во что).
    """
    by_sym = {}
    for g in legs_:
        by_sym.setdefault(g["sym"], set()).add(round(float(g["at"]), 3))
    out = {}
    for key, r in cache.items():
        at, end = float(r["at"]), float(r.get("exit_ts") or 0)
        ks = []
        for t in by_sym.get(r["sym"], ()):
            if at < t < end:
                ks.append(int((t - at) // HOUR) + 1)
        if ks:
            out[key] = sorted(set(ks))
    return out


def trigger(v, kind, val, reps=None):
    """Первый час долива СТРОГО до выхода родителя, иначе None."""
    p = v["path"]
    if not p:
        return None
    cum = p["cum"]
    for k in range(1, p["K"]):
        c = cum.get(k)
        if c is None:
            continue
        if kind == "P":
            if c >= val:
                return k
        elif kind == "R":
            if reps and k in reps:
                return k
        elif kind == "R+":
            if reps and k in reps and c > 0:
                return k
        elif kind == "M":
            e = v["excess"].get(k)
            if c > 0 and e is not None and e <= -float(val):
                return k
    return None


def floor_of_ruler(rk):
    """Пол капитуляции линейки долями маржи: −(1 − доля пола), как у ядра в терминах съеденной маржи."""
    for frac, rulers in S.floor_groups().items():
        if rk in rulers:
            return -(1.0 - float(frac))
    return -(1.0 - float(D2.FLOOR_FRAC))


def add_outcome(v, k, floor_pnl):
    """Позиция с доливом второй ступени на часе k против позиции без него.

    После долива pnl позиции идёт вдвое быстрее: на часе j он равен
    2·cum_j − cum_k. Общий пол (`floor_pnl`, доля маржи) достигнут —
    позиция закрыта на этом часе, раньше своего выхода. `delta` —
    приращение денег позиции от долива долями зарезервированной маржи,
    `net` — за вычетом круга издержек на нотионал долива; `early_floor` —
    позиция добита доливом раньше своего выхода.
    """
    rec, p = v["rec"], v["path"]
    cum, K = p["cum"], p["K"]
    share = share_of(rec)
    lev = float(rec.get("lev") or 0.0)
    ck = float(cum[k])
    j_exit, floored = K, False
    for j in range(k + 1, K + 1):
        c = cum.get(j)
        if c is None:
            continue
        if 2.0 * float(c) - ck <= float(floor_pnl):
            j_exit, floored = j, True
            break
    cj = float(cum[j_exit])
    total_with = 2.0 * cj - ck
    delta = total_with - float(p["final"])
    cost = share * lev * D10.ROUND_COST_BP / 1e4
    return {"delta": delta, "net": delta - cost, "cost": cost, "add_pnl": cj - ck,
            "early_floor": bool(floored and j_exit < K),
            "px_bp": ((cj - ck) / (share * lev) * 1e4) if (share > 0 and lev > 0) else None}


def record_with_add(rec, k, floor_pnl):
    """Запись кэша, как если бы на часе k заполнилась вторая ступень.

    Отметки после k удваиваются (две ступени), позиция закрывается на
    часе общего пола, если он достигнут раньше своего выхода (исход
    «пол»); заполнение добавляется по цене отметки часа k (из pnl и
    заполнений — `wave.exit_px_of`), чтобы касса сняла комиссию,
    проскальзывание и funding с ОБЕИХ ступеней своим кодом.
    """
    p = WV.path_of(rec)
    cum, K = p["cum"], p["K"]
    at = float(rec["at"])
    share = share_of(rec)
    ck = float(cum[k])
    j_exit, floored = K, False
    for j in range(k + 1, K + 1):
        c = cum.get(j)
        if c is not None and 2.0 * float(c) - ck <= float(floor_pnl):
            j_exit, floored = j, True
            break
    marks, prev = [], 0.0
    for hr, d in rec["marks"]:
        kk = int(round((float(hr) - at) / HOUR)) + 1
        if kk > j_exit:
            break
        marks.append((hr, float(d) * (2.0 if kk > k else 1.0)))
        prev += float(d)
    total = 2.0 * float(cum[j_exit]) - ck
    t_k = at + k * HOUR - 1.0
    px_k = WV.exit_px_of(rec, ck, t_k)
    new = dict(rec, pnl=total, marks=marks, state="closed", add_hour=k, add_floor=bool(floored and j_exit < K))
    if rec.get("pnl_net") is not None:
        lev = float(rec.get("lev") or 0.0)
        new["pnl_net"] = float(rec["pnl_net"]) - float(rec["pnl"]) + total - share * lev * D10.ROUND_COST_BP / 1e4
    if floored and j_exit < K:
        new["exit_ts"] = at + j_exit * HOUR - 1.0
        new["exit"] = "пол"
    if px_k is not None:
        new["fills"] = [list(f) for f in (rec.get("fills") or [])] + [[t_k, float(px_k), share]]
    new["exit_px"] = WV.exit_px_of(new, total, float(new["exit_ts"]))
    return new


def cache_with_adds(cache, views, changed):
    """Кэш, где у изменённых записей заполнена вторая ступень."""
    mod = dict(cache)
    for key, k in changed.items():
        mod[key] = record_with_add(views[key]["rec"], k, floor_of_ruler(key[0]))
    return mod


def outcome(views, key, k):
    return add_outcome(views[key], k, floor_of_ruler(key[0]))


def stats(adds):
    """Сводка доливов: среднее и медиана приращения, доля плюсовых, худшие 5 %, добитые, в цене."""
    if not adds:
        return None
    net = sorted(a["net"] for a in adds)
    px = [a["px_bp"] for a in adds if a["px_bp"] is not None]
    n = len(net)
    return {"n": n, "mean": sum(net) / n, "median": statistics.median(net),
            "pos": sum(1 for x in net if x > 0) / n,
            "worst5": net[max(0, int(0.05 * (n - 1)))],
            "early_floor": sum(1 for a in adds if a["early_floor"]) / n,
            "px_mean": (sum(px) / len(px)) if px else None,
            "px_median": (statistics.median(px) if px else None),
            "sum": sum(net)}


def control(views, changed, idx, seeds=SEEDS, log=print, in_profit=False):
    """Случайные позиции, открытые в те же часы (при `in_profit` — и в плюсе на этом часе),
    с тем же доливом — средний net по зёрнам."""
    hours = [(key[0], k) for key, k in changed.items()]
    means, t0 = [], time.time()
    for i in range(int(seeds)):
        rnd = random.Random((7000 if in_profit else 2000) + i)
        got, used = [], set()
        for rk, k in hours:
            pool = (idx.get(rk) or {}).get(k) or []
            pick = None
            for _try in range(30):
                if not pool:
                    break
                c = rnd.choice(pool)
                if c in used:
                    continue
                if in_profit and not (float(views[c]["path"]["cum"].get(k) or 0.0) > 0):
                    continue
                pick = c
                break
            if pick is None:
                continue
            used.add(pick)
            got.append(outcome(views, pick, k)["net"])
        means.append((sum(got) / len(got)) if got else None)
        if i and i % 50 == 0:
            log(f"    контроль{' в плюсе' if in_profit else ''}: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    vals = [m for m in means if m is not None]
    return {"means": vals, "median": (statistics.median(vals) if vals else None)}


def beat(ctl_means, value):
    vals = [m for m in ctl_means if m is not None]
    if not vals or value is None:
        return None
    return round(sum(1 for m in vals if m >= value) / len(vals), 3)


def by_book(views, changed):
    """Доливы по книгам (линейка → книги семейства)."""
    out = {bk: [] for bk in BOOK_KEYS}
    for key, k in changed.items():
        a = outcome(views, key, k)
        for bk, rk in S.BOOKS.items():
            if rk == key[0]:
                out[bk].append(a)
    return {bk: stats(v) for bk, v in out.items()}


def with_repeats(fn):
    """Правило «одна на имя» снято на время счёта — и возвращено, что бы ни случилось."""
    was = R.ONE_PER_NAME
    R.ONE_PER_NAME = False
    try:
        return fn()
    finally:
        R.ONE_PER_NAME = was


def run(seeds=SEEDS, log=print, now=None, launch=None, ctx=None, mem_limit=None,
        dep=MAIN_DEP, legs_=None, summary_dir=None, mkt=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(log=log) if legs_ is None else legs_
    if mkt is None:
        mkt = WV.Market(WV.Hours(root=summary_dir or WV.SUMMARY_DIR))
    closed = {key: r for key, r in cache.items()
              if key[0] in T.RULERS and (r.get("state") or "closed") == "closed"}
    views, no_marks = {}, 0
    for i, (key, r) in enumerate(sorted(closed.items(), key=lambda kv: kv[0][2])):
        v = view_lite(r, mkt)
        if v["path"] is None:
            no_marks += 1
        views[key] = v
        if i and i % 2000 == 0:
            log(f"виды: {i} из {len(closed)}, {time.time() - t0:.0f} с")
    reps = repeats_of(closed, legs_)
    shares = [share_of(v["rec"]) for v in views.values()]
    log(f"закрытых {len(views)}, без отметок {no_marks}, с повторным выбором {len(reps)}; "
        f"доля базовой ступени: медиана {statistics.median(shares) if shares else None}; "
        f"волна не собралась {mkt.wave_none} раз")
    idx = P.open_index(views)
    # опора: деньги родителей (доли маржи, нетто записи)
    base_sum = {bk: sum(float(v["rec"].get("pnl_net") or 0.0) for key, v in views.items()
                       if key[0] == rk) for bk, rk in S.BOOKS.items()}
    base_n = {bk: sum(1 for key in views if key[0] == rk) for bk, rk in S.BOOKS.items()}
    cells = []
    for kind, title, val in CELLS:
        changed = {}
        for key, v in views.items():
            k = trigger(v, kind, val, reps=reps.get(key))
            if k is not None:
                changed[key] = k
        adds = {key: outcome(views, key, k) for key, k in changed.items()}
        st = stats(list(adds.values()))
        cell = {"kind": kind, "title": title, "val": val, "n": len(changed), "stats": st,
                "books": by_book(views, changed), "control": None, "beat": None,
                "control_plus": None, "beat_plus": None, "_changed": changed,
                "tails_after": sum(1 for key in changed if views[key]["tail"])}
        if changed:
            ctl = control(views, changed, idx, seeds=seeds, log=log)
            cell["control"] = {"median": ctl["median"], "n": len(ctl["means"])}
            cell["beat"] = beat(ctl["means"], st["mean"])
            ctp = control(views, changed, idx, seeds=seeds, log=log, in_profit=True)
            cell["control_plus"] = {"median": ctp["median"], "n": len(ctp["means"])}
            cell["beat_plus"] = beat(ctp["means"], st["mean"])
        log(f"{kind} {title}: доливов {len(changed)}, среднее {None if not st else round(st['mean'], 4)}, "
            f"добито {None if not st else round(st['early_floor'], 3)}; случайные не хуже в {cell['beat']}, "
            f"в плюсе — {cell['beat_plus']}")
        cells.append(cell)
    # касса: повторы как свои позиции (правило «одна на имя» снято)
    packed = AG.packed_short(cache)
    stats_fn = lambda: AG.stats_of(packed, ctx, launch, BOOK_KEYS, deps=[dep], now=now)   # noqa: E731
    cash_base = stats_fn()
    cash_rep = with_repeats(stats_fn)
    cash = {bk: {"base": L.summ(cash_base.get(f"{bk}:{int(dep)}") or {}),
                 "repeats": L.summ(cash_rep.get(f"{bk}:{int(dep)}") or {})} for bk in BOOK_KEYS}
    # касса: вторая ступень заполнена по триггеру — те же записи, деньги и издержки обеих ступеней
    for c in cells:
        ch = c.pop("_changed", {})
        if not ch:
            continue
        st = AG.stats_of(AG.packed_short(cache_with_adds(cache, views, ch)), ctx, launch,
                         BOOK_KEYS, deps=[dep], now=now)
        for bk in BOOK_KEYS:
            cash[bk][c["title"]] = L.summ(st.get(f"{bk}:{int(dep)}") or {})
        log(f"касса со ступенью «{c['title']}»: " + ", ".join(
            f"{bk} {_pp(cash[bk][c['title']].get('final'))}" for bk in BOOK_KEYS))
    for bk in BOOK_KEYS:
        for k in list(cash[bk]):
            cash[bk][k].pop("days", None)
    return {"dep": dep, "seeds": int(seeds), "books": BOOK_KEYS, "cells": cells,
            "base": {"sum": base_sum, "n": base_n}, "cash": cash,
            "diag": {"closed": len(views), "no_marks": no_marks, "repeats": len(reps),
                     "legs": len(legs_), "share_median": (statistics.median(shares) if shares else None),
                     "wave_none": mkt.wave_none},
            "axes": {"profit": list(PROFIT), "weak": list(WEAK)},
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- отчёт

def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _pu(x, d=0):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _bp(x):
    return "—" if x is None else f"{float(x):+.0f} б.п."


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def _sd(x):
    return "—" if x is None else f"{float(x):.0f} $"


def _i(x):
    return "—" if x is None else str(x)


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def verdict(cell):
    """Фраза из чисел: среднее нетто и доля зёрен, где случайный открытый В ПЛЮСЕ не хуже."""
    b = cell.get("beat_plus")
    st = cell.get("stats") or {}
    if b is None or st.get("mean") is None:
        return "не измерено"
    if st["mean"] <= 0:
        return "долив в минусе"
    if b <= 0.05:
        return "лучше случайного в плюсе"
    if b >= 0.95:
        return "хуже случайного в плюсе"
    return "в шуме случайного в плюсе"


def report(s):
    L_ = ["# Доливы в прибыльный шорт: заполнить зарезервированные ступени по триггеру", "",
          "Решение владельца 2026-10-05. Короткая книга резервирует маржу на четыре ступени и "
          "заполняет одну; долив здесь — вторая ступень той же доли нотионала в сторону прибыли. "
          "Считается ВСЯ позиция: после долива pnl идёт вдвое быстрее, общий пол капитуляции "
          "(−90 % маржи у безопасной линейки, −50 % у оптимальной) достигается при вдвое меньшем "
          "ходе против — по часовым отметкам кэша, с оговоркой часа. Величина — приращение денег "
          "позиции от долива, нетто круга издержек на его нотионал, долями зарезервированной маржи. "
          f"Судьи — случайные позиции, открытые в те же часы, и такие же в плюсе ({s.get('seeds') or SEEDS} зёрен). "
          "«В цене» — ход цены за жизнь долива в б.п. (мера хода, не показ денег).", ""]
    if s.get("error"):
        return "\n".join(L_ + [f"**Не посчитано:** {s['error']}.", ""])
    dg = s.get("diag") or {}
    L_ += [f"Закрытых позиций {_i(dg.get('closed'))}, без отметок {_i(dg.get('no_marks'))}, с повторным "
           f"выбором модели {_i(dg.get('repeats'))} (ног листа {_i(dg.get('legs'))}); доля базовой ступени "
           f"(медиана) {_f(dg.get('share_median'))}; волна не собралась {_i(dg.get('wave_none'))} раз.", ""]
    L_ += ["## Доливы по триггерам (все линейки вместе)", "",
           "| триггер | доливов | хвостовых родителей | приращение, % маржи: среднее | медиана | плюсовых | "
           "худшие 5 % | добито доливом | в цене, среднее | случайные открытые: медиана / не хуже | "
           "случайные в плюсе: медиана / не хуже | вывод |",
           "|---|--:|--:|--:|--:|--:|--:|--:|--:|---|---|---|"]
    for c in s.get("cells") or []:
        st = c.get("stats") or {}
        ctl = c.get("control") or {}
        ctp = c.get("control_plus") or {}
        L_.append(f"| {c['title']} | {_i(c.get('n'))} | {_i(c.get('tails_after'))} | {_pp(st.get('mean'), 2)} | "
                  f"{_pp(st.get('median'), 2)} | {_pu(st.get('pos'))} | {_pp(st.get('worst5'))} | "
                  f"{_pu(st.get('early_floor'), 1)} | {_bp(st.get('px_mean'))} | "
                  f"{_pp(ctl.get('median'), 2)} / {_pu(c.get('beat'))} | "
                  f"{_pp(ctp.get('median'), 2)} / {_pu(c.get('beat_plus'))} | {verdict(c)} |")
    L_.append("")
    L_ += ["## По книгам: сумма доливов против денег родителей (доли маржи, нетто записей)", "",
           "| книга | родителей | Σ родителей | " + " | ".join(c["title"] for c in s.get("cells") or []) + " |",
           "|---|--:|--:|" + "--:|" * len(s.get("cells") or [])]
    base = s.get("base") or {}
    for bk in s.get("books") or BOOK_KEYS:
        row = [f"| {R.ruler_title(bk)} | {_i((base.get('n') or {}).get(bk))} | "
               f"{_f((base.get('sum') or {}).get(bk), 1)} |"]
        for c in s.get("cells") or []:
            b = (c.get("books") or {}).get(bk) or {}
            row.append(f" {_f(b.get('sum'), 1)} ({_i(b.get('n'))}) |")
        L_.append("".join(row))
    L_ += ["", "## Касса $10 000: повторы как свои позиции (правило «одна на имя» снято)", "",
           "Повторный выбор модели сейчас кассой пропускается. Здесь он входит СВОЕЙ позицией со своей "
           "маржой — это долив с лишней маржой, не заполнение ступени; деньги нетто со всеми издержками.", "",
           "| книга | ячейка | сделок | итог | просадка | σ дня | $ без 3 лучших дней | хвостовых |",
           "|---|---|--:|--:|--:|--:|--:|--:|"]
    for bk in s.get("books") or BOOK_KEYS:
        for key, title in (("base", "как сейчас"), ("repeats", "повторы разрешены")):
            c = ((s.get("cash") or {}).get(bk) or {}).get(key) or {}
            L_.append(f"| {R.ruler_title(bk)} | {title} | {_i(c.get('n'))} | {_pp(c.get('final'))} | "
                      f"{_pp(c.get('max_dd'))} | {_sd(c.get('sigma_day'))} | {_usd(c.get('wo3'))} | {_i(c.get('tails'))} |")
    L_ += ["", "## Касса $10 000: вторая ступень заполнена по триггеру", "",
           "То, о чём спрашивал владелец: позиция из двух входов на той же зарезервированной марже. "
           "Записи те же, после долива отметки идут вдвое быстрее, общий пол — по отметкам; касса снимает "
           "комиссию, проскальзывание и funding с обеих ступеней своим кодом. Доход/просадка — главная колонка.", "",
           "| книга | ячейка | сделок | итог | просадка | доход/просадка | σ дня | $ без 3 лучших дней | хвостовых |",
           "|---|---|--:|--:|--:|--:|--:|--:|--:|"]
    titles = ["base"] + [c["title"] for c in s.get("cells") or []]
    for bk in s.get("books") or BOOK_KEYS:
        for key in titles:
            c = ((s.get("cash") or {}).get(bk) or {}).get(key)
            if c is None:
                continue
            ratio = (None if not c.get("final") or not c.get("max_dd")
                     else float(c["final"]) / abs(float(c["max_dd"])))
            L_.append(f"| {R.ruler_title(bk)} | {'как сейчас' if key == 'base' else key} | {_i(c.get('n'))} | "
                      f"{_pp(c.get('final'))} | {_pp(c.get('max_dd'))} | {_f(ratio)} | {_sd(c.get('sigma_day'))} | "
                      f"{_usd(c.get('wo3'))} | {_i(c.get('tails'))} |")
    L_ += ["", "## Как читать", "",
           "- Долив имеет смысл, если приращение денег позиции в плюсе ПОСЛЕ издержек, случайный открытый "
           "В ПЛЮСЕ в те же часы не хуже редко (≤ 5 % зёрен), а добитых доливом и худших 5 % книга переживёт.",
           "- «Добито доливом» — позиция дошла до общего пола раньше своего выхода только из-за второй "
           "ступени: без долива она дожила бы до своего исхода. «Хвостовых родителей» — родители, "
           "кончившиеся полом или ликвидацией и без долива.",
           "- Триггер по прибыли судится против случайного открытого, потому что любая живая позиция в "
           "среднем дотягивает в плюс: вопрос — выбирает ли триггер продолжение ЛУЧШЕ среднего.",
           "- Правилом ничего не назначается: это первый взгляд по отметкам; второй шаг — ядро с общим "
           "полом и касса на заполнении ступеней.",
           f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
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
    s = run(seeds=a.seeds, log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("доливы в прибыльный шорт: прибыль, повтор модели, слабее рынка")


if __name__ == "__main__":
    main()
