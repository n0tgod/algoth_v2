#!/usr/bin/env python3
"""Потолок плеча у коротких книг: держится ли эдж НА СДЕЛКУ без мотора.

Тезис владельца 2026-10-03: «плечо — последнее, о чём думать; эдж в
соотношении риск/прибыль и точности попаданий». Стенд меряет ровно это —
исход позиции долями маржи и долями НОТИОНАЛА (цены), нетто, — и здесь
проверяет тезис на наших же сделках: те же решения, тот же срок 24 ч, та
же цель ×2, тот же пол капитуляции, но плечо забора не выше потолка.

Ось объявлена до прогона: потолок 2× и 6× (розничная фонда через ночь
и портфельная маржа), опора — как книги живут (забор до 25×).

Как считается. Исход позиции линеен по плечу, пока плечо не решает её
судьбу: цель стоит в ЦЕНЕ (обещание ×2), срок — во времени, круг
издержек — на заполненный нотионал. Поэтому у записи, вышедшей по цели
или сроку, исход при меньшем плече есть тот же исход × (потолок / плечо),
и он масштабируется без реплея. У записи, вышедшей по ПОЛУ или
ЛИКВИДАЦИИ, при меньшем плече пол стоит дальше, и путь после прежнего
выхода нам неизвестен — такие записи пересчитываются ядром лестницы
(`run_short.replay` с потолком `run_d10.LEV_CAP["fence"]` на время
счёта). Линейность не берётся на веру: случайная выборка записей,
вышедших по цели/сроку, тоже пересчитывается ядром и сверяется с
масштабом (ускорение сверяется с точным счётом — урок памяти); число
расхождений печатается.

Что печатается на книгу и ячейку: сделок, доля плюсовых, средний выигрыш
и проигрыш долями маржи, их отношение (RR), ожидание на сделку долями
маржи и долями нотионала (последнее от плеча не зависит и есть мера
эджа в цене), доля полов и ликвидаций, — по ЗАПИСЯМ (все решения
линейки, круг издержек без funding) и по КАССЕ $10k (как книга живёт,
нетто со всеми издержками). Контроля случайной выборкой нет: потолок
сделок не режет, он меняет, чем они кончаются.
"""
import argparse
import collections
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
import run_paper as RP                                        # noqa: E402
import run_d10 as D10                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_levers as L                                      # noqa: E402
import short_size as Z                                        # noqa: E402
import tail_screen as T                                       # noqa: E402
import wave_guard as W                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-levcap"
CAPS = (2.0, 6.0)                 # объявлено до прогона
VERIFY_N = 120                    # записей цели/срока на сверку масштаба с ядром
VERIFY_SEED = 7
TOL = 1e-9
MAIN_DEP = 10000
BOOK_KEYS = list(S.BOOKS)
TAIL_EXITS = T.TAIL_EXITS
CELL_KEYS = ("base",) + tuple(f"{c:g}" for c in CAPS)


def scale_record(r, cap):
    """Запись при плече `cap`, когда исход от плеча не зависел: pnl линеен."""
    lev = float(r["lev"])
    k = float(cap) / lev
    new = dict(r, lev=float(cap), pnl=float(r["pnl"]) * k, lev_scaled_from=lev)
    if r.get("pnl_net") is not None:
        new["pnl_net"] = float(r["pnl_net"]) * k
    if r.get("marks"):
        new["marks"] = [(h, float(d) * k) for h, d in r["marks"]]
    if r.get("ckpt"):
        new["ckpt"] = [((c[0], c[1], (None if c[2] is None else float(c[2]) * k))
                        if isinstance(c, (list, tuple)) and len(c) == 3 else c)
                       for c in r["ckpt"]]
    return new


def plan(cache, cap):
    """Разметка записей под потолок: без изменений / масштаб / реплей ядром."""
    unchanged, scale, replay = {}, {}, {}
    for key, r in cache.items():
        lev = float(r.get("lev") or 0.0)
        closed = (r.get("state") or "closed") == "closed"
        if lev <= float(cap) or not closed:
            unchanged[key] = r
        elif (r.get("exit") or "") in TAIL_EXITS:
            replay[key] = r
        else:
            scale[key] = r
    return unchanged, scale, replay


def verify_keys(keys, n=VERIFY_N, seed=VERIFY_SEED):
    """Воспроизводимая выборка записей цели/срока на сверку с ядром."""
    ks = sorted(keys)
    rnd = random.Random(seed)
    return set(rnd.sample(ks, min(int(n), len(ks))))


def legs_for(keys, legs_):
    """Ноги листа для (имя, момент) — одна на решение; без ноги — посчитано."""
    by = {}
    for g in legs_:
        by.setdefault((g["sym"], round(float(g["at"]), 3)), g)
    need, missing, seen = [], 0, set()
    for (_rk, sym, at) in keys:
        k = (sym, round(float(at), 3))
        if k in seen:
            continue
        seen.add(k)
        g = by.get(k)
        if g is None:
            missing += 1
        else:
            need.append(g)
    need.sort(key=lambda g: (g["at"], g["sym"]))
    return need, missing


def with_cap(cap, fn):
    """Потолок плеча забора на время счёта — и назад, что бы ни случилось."""
    was = D10.LEV_CAP.get("fence")
    D10.LEV_CAP["fence"] = float(cap)
    try:
        return fn()
    finally:
        D10.LEV_CAP["fence"] = was


def compare(scaled, replayed, tol=TOL):
    """Масштаб против ядра на тех же записях: число расхождений и худшее."""
    n, bad, worst = 0, 0, 0.0
    for key, s in scaled.items():
        f = replayed.get(key)
        if f is None:
            continue
        n += 1
        d = abs(float(s["pnl"]) - float(f["pnl"]))
        if s.get("pnl_net") is not None and f.get("pnl_net") is not None:
            d = max(d, abs(float(s["pnl_net"]) - float(f["pnl_net"])))
        same = (s.get("exit") == f.get("exit")
                and abs(float(s["exit_ts"]) - float(f["exit_ts"])) < 0.5)
        worst = max(worst, d)
        if d > tol or not same:
            bad += 1
    return {"n": n, "bad": bad, "worst": worst}


def build_cap(cache, cap, legs_, log=print, src=None, verify_n=VERIFY_N):
    """Кэш при потолке плеча: масштаб + реплей хвоста + сверка на выборке."""
    unchanged, scale, replay = plan(cache, cap)
    vkeys = verify_keys(scale, n=verify_n)
    need, missing = legs_for(list(replay) + sorted(vkeys), legs_)
    log(f"потолок {cap:g}×: без изменений {len(unchanged)}, масштаб {len(scale)}, "
        f"реплей хвоста {len(replay)} (+{len(vkeys)} на сверку); ног {len(need)}, "
        f"без ноги {missing}")
    fresh = {}
    if need:
        fresh, _tail = with_cap(cap, lambda: S.replay(need, src=src, log=log))
    out = dict(unchanged)
    scaled = {k: scale_record(r, cap) for k, r in scale.items()}
    out.update(scaled)
    n_rep, n_miss = 0, 0
    was_ex, now_ex = collections.Counter(), collections.Counter()
    for key, r in replay.items():
        f = fresh.get(key)
        if f is None:
            n_miss += 1                 # записи нет в ячейке: не выдумывается
            continue
        out[key] = dict(r, **f)
        n_rep += 1
        was_ex[r.get("exit") or "—"] += 1
        now_ex[f.get("exit") or "—"] += 1
    ver = compare({k: scaled[k] for k in vkeys}, fresh)
    log(f"потолок {cap:g}×: пересчитано {n_rep}, выпало {n_miss}; сверка масштаба "
        f"с ядром: {ver['n']} записей, расхождений {ver['bad']}, худшее {ver['worst']:.2e}")
    return out, {"cap": float(cap), "unchanged": len(unchanged), "scaled": len(scale),
                 "replayed": n_rep, "dropped": n_miss, "legs_missing": missing,
                 "verify": ver, "was_exits": dict(was_ex), "now_exits": dict(now_ex)}


def trade_stats(pairs):
    """Доля плюсовых, средний выигрыш/проигрыш, RR, ожидание — долями маржи и нотионала."""
    if not pairs:
        return None
    n = len(pairs)
    m = [a for a, _b in pairs]
    q = [b for _a, b in pairs]
    win_m = [x for x in m if x > 0]
    loss_m = [x for x in m if x <= 0]
    win_q = [b for a, b in pairs if a > 0]
    loss_q = [b for a, b in pairs if a <= 0]
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None          # noqa: E731
    mw, ml = mean(win_m), mean(loss_m)
    return {"n": n, "hit": len(win_m) / n,
            "win_m": mw, "loss_m": ml,
            "rr": (None if not mw or not ml else mw / abs(ml)),
            "exp_m": mean(m), "exp_q": mean(q),
            "win_q": mean(win_q), "loss_q": mean(loss_q),
            "med_m": statistics.median(m)}


def record_pairs(recs, book):
    """Пары (pnl_net маржи, pnl_net нотионала) по закрытым записям книги с её гейтом плеча."""
    ml = R.min_lev_of(book)
    out = []
    for r in recs:
        if (r.get("state") or "closed") != "closed" or r.get("pnl_net") is None:
            continue
        lev = float(r.get("lev") or 0.0)
        if not lev > 0 or (ml is not None and lev < float(ml)):
            continue
        p = float(r["pnl_net"])
        out.append((p, p / lev))
    return out


def cash_rows(packed, ctx, launch, now=None, dep=MAIN_DEP):
    """Строки кассы на $dep по книгам, нетто — тем же порядком, что `cell_stats`."""
    ruled = L.ruled(packed, launch, now=now)
    rows, _c, _o, _l = RP.build_rows(ruled, now=now, keys=BOOK_KEYS, log=lambda *a: None)
    out = {bk: [] for bk in BOOK_KEYS}
    for bk in BOOK_KEYS:
        mine = [r for r in rows if R.ruler_of(r) == bk and int(r.get("dep", 0)) == int(dep)]
        if ctx is not None and not ctx.get("error"):
            mine, _n = CO.apply_to_rows(mine, ctx)
        out[bk] = mine
    return out


def row_pairs(rows):
    out = []
    for r in rows:
        try:
            m, lev, usd = float(r["margin"]), float(r["lev"]), float(r["usd"])
        except (TypeError, KeyError, ValueError):
            continue
        if m > 0 and lev > 0:
            out.append((usd / m, usd / (m * lev)))
    return out


def tails_share(recs_or_rows):
    n = len(recs_or_rows)
    t = sum(1 for r in recs_or_rows if (r.get("exit") or "") in TAIL_EXITS)
    return (t / n) if n else None, t


def cell_of(cache, ctx, launch, now=None, dep=MAIN_DEP):
    """Сводка ячейки: по записям и по кассе, на книгу."""
    packed = AG.packed_short(cache)
    st = AG.stats_of(packed, ctx, launch, BOOK_KEYS, deps=[dep], now=now)
    rows = cash_rows(packed, ctx, launch, now=now, dep=dep)
    books = {}
    for bk in BOOK_KEYS:
        recs = packed.get(bk) or []
        kept = [r for r in recs if (r.get("state") or "closed") == "closed"
                and (R.min_lev_of(bk) is None or float(r.get("lev") or 0) >= float(R.min_lev_of(bk)))]
        rs, rt = tails_share(kept)
        cs, ct = tails_share(rows[bk])
        c = L.summ(st.get(f"{bk}:{int(dep)}") or {})
        books[bk] = {"records": trade_stats(record_pairs(recs, bk)),
                     "records_tail_share": rs, "records_tails": rt,
                     "cash": trade_stats(row_pairs(rows[bk])),
                     "cash_tail_share": cs, "cash_tails": ct,
                     "cash_cell": c}
    return books


def run(caps=CAPS, log=print, now=None, launch=None, ctx=None, mem_limit=None,
        dep=MAIN_DEP, legs_=None, src=None, verify_n=VERIFY_N):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(log=log) if legs_ is None else legs_
    cells, plans = {}, {}
    cells["base"] = cell_of(cache, ctx, launch, now=now, dep=dep)
    log("опора посчитана: " + ", ".join(
        f"{bk} сделок {((cells['base'][bk].get('cash') or {}).get('n'))}" for bk in BOOK_KEYS))
    for cap in caps:
        capped, meta = build_cap(cache, cap, legs_, log=log, src=src, verify_n=verify_n)
        key = f"{float(cap):g}"
        plans[key] = meta
        cells[key] = cell_of(capped, ctx, launch, now=now, dep=dep)
        log(f"потолок {cap:g}× посчитан за {time.time() - t0:.0f} с")
    return {"caps": [float(c) for c in caps], "dep": dep, "books": BOOK_KEYS,
            "cells": cells, "plans": plans, "verify_n": int(verify_n), "tol": TOL,
            "diag": {"records": len(cache), "legs": len(legs_)},
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- отчёт

def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _pu(x, d=0):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _bp(x):
    return "—" if x is None else f"{1e4 * float(x):+.1f} б.п."


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def _sd(x):
    return "—" if x is None else f"{float(x):.0f} $"


def _i(x):
    return "—" if x is None else str(x)


def _title(key):
    return "как сейчас (забор до 25×)" if key == "base" else f"потолок {key}×"


def _trade_row(label, ts, tail_share, tails):
    if not ts:
        return f"| {label} | — | — | — | — | — | — | — | — |"
    return (f"| {label} | {ts['n']} | {_pu(ts['hit'])} | {_pp(ts['win_m'])} | {_pp(ts['loss_m'])} | "
            f"{_f(ts['rr'])} | {_pp(ts['exp_m'], 2)} | {_bp(ts['exp_q'])} | "
            f"{_pu(tail_share, 1)} ({_i(tails)}) |")


TRADE_HEAD = ("| ячейка | сделок | плюсовых | ср. выигрыш, % маржи | ср. проигрыш, % маржи | "
              "RR | ожидание, % маржи | ожидание в цене | полов и ликвидаций |")
TRADE_SEP = "|---|--:|--:|--:|--:|--:|--:|--:|--:|"


def verdict(base, cell):
    """Фраза из числа: ожидание на сделку В ЦЕНЕ при потолке против опоры."""
    b = (base or {}).get("exp_q")
    c = (cell or {}).get("exp_q")
    if b is None or c is None:
        return "не измерено"
    if b <= 0:
        return "опора без эджа в цене" if c <= 0 else "эдж в цене появился"
    rel = c / b - 1.0
    if rel >= -0.1:
        return "ожидание в цене держится"
    if c <= 0:
        return "ожидание в цене исчезло"
    return f"ожидание в цене {100 * rel:+.0f} %"


def report(s):
    L_ = ["# Потолок плеча у коротких книг: держится ли эдж на сделку без мотора", "",
          "Тезис владельца 2026-10-03: эдж — в соотношении риск/прибыль и точности "
          "попаданий, а не в плече. Проверка на наших же решениях: те же входы, срок 24 ч, "
          f"цель ×2, пол капитуляции книги, но плечо забора не выше потолка {', '.join(f'{c:g}×' for c in (s.get('caps') or CAPS))}. "
          "Записи, вышедшие по цели или сроку, масштабированы (исход линеен по плечу), "
          "вышедшие по полу или ликвидации пересчитаны ядром лестницы; линейность "
          "сверена с ядром на случайной выборке. «Ожидание в цене» — pnl на нотионал, от "
          "плеча не зависит и есть мера эджа решения. По записям — все решения линейки с "
          "кругом издержек без funding; по кассе — как книга живёт на "
          f"${int(s.get('dep') or MAIN_DEP):,}, нетто со всеми издержками. Контроля "
          "случайной выборкой нет: потолок сделок не режет, он меняет, чем они кончаются.", ""]
    if s.get("error"):
        return "\n".join(L_ + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L_ += [f"**Издержки:** {s['costs_error']} — касса без этой части.", ""]
    plans = s.get("plans") or {}
    L_ += ["## Как собраны ячейки", "",
           "| потолок | без изменений (плечо ≤ потолка) | масштаб (цель/срок) | реплей хвоста | "
           "выпало | сверка с ядром: записей / расхождений / худшее Δ | хвост был → стал |",
           "|---|--:|--:|--:|--:|---|---|"]
    for key in CELL_KEYS[1:]:
        p = plans.get(key) or {}
        v = p.get("verify") or {}
        was = ", ".join(f"{k} {n}" for k, n in sorted((p.get("was_exits") or {}).items()))
        now = ", ".join(f"{k} {n}" for k, n in sorted((p.get("now_exits") or {}).items()))
        L_.append(f"| {key}× | {_i(p.get('unchanged'))} | {_i(p.get('scaled'))} | {_i(p.get('replayed'))} | "
                  f"{_i(p.get('dropped'))} | {_i(v.get('n'))} / {_i(v.get('bad'))} / "
                  f"{'—' if v.get('worst') is None else format(float(v['worst']), '.1e')} | "
                  f"{was or '—'} → {now or '—'} |")
    L_.append("")
    cells = s.get("cells") or {}
    for bk in s.get("books") or BOOK_KEYS:
        base_b = (cells.get("base") or {}).get(bk) or {}
        L_ += [f"## {R.ruler_title(bk)}", "", "**По записям** (все решения линейки под гейтом книги):", "",
               TRADE_HEAD, TRADE_SEP]
        for key in CELL_KEYS:
            b = (cells.get(key) or {}).get(bk) or {}
            L_.append(_trade_row(_title(key), b.get("records"), b.get("records_tail_share"),
                                 b.get("records_tails")))
        L_ += ["", f"**По кассе ${int(s.get('dep') or MAIN_DEP):,}, нетто:**", "",
               TRADE_HEAD[:-1] + " итог | просадка | σ дня | $ без 3 лучших дней | вывод |",
               TRADE_SEP + "--:|--:|--:|--:|---|"]
        for key in CELL_KEYS:
            b = (cells.get(key) or {}).get(bk) or {}
            c = b.get("cash_cell") or {}
            row = _trade_row(_title(key), b.get("cash"), b.get("cash_tail_share"), b.get("cash_tails"))
            L_.append(f"{row} {_pp(c.get('final'))} | {_pp(c.get('max_dd'))} | {_sd(c.get('sigma_day'))} | "
                      f"{_usd(c.get('wo3'))} | "
                      f"{'опора' if key == 'base' else verdict(base_b.get('cash'), b.get('cash'))} |")
        L_.append("")
    L_ += ["## Как читать", "",
           "- Если при потолке доля плюсовых растёт, полы исчезают, а ожидание в цене "
           "держится — эдж решения жил отдельно от плеча, и стабильность лежит в потолке.",
           "- Если ожидание в цене тает вместе с полами — цель и срок книги работают только "
           "на том плече, на котором она живёт; у решения без мотора эджа нет.",
           "- Ожидание в долях маржи при меньшем плече меньше арифметически — это не "
           "вердикт, вердикт читается в цене и в доле плюсовых.",
           "- Пустая книга при потолке — гейт её плеча выше потолка (агрессивная ≥ 4×), "
           "и это названо прочерком, а не нулём.",
           f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--caps", default=",".join(f"{c:g}" for c in CAPS),
                    help="потолки плеча через запятую (объявлены в коде)")
    ap.add_argument("--verify", type=int, default=VERIFY_N)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    caps = tuple(float(x) for x in a.caps.split(",") if x.strip())
    s = run(caps=caps, log=print, verify_n=a.verify)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("потолок плеча у коротких книг: эдж на сделку без мотора")


if __name__ == "__main__":
    main()
