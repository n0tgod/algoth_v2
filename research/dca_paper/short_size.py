#!/usr/bin/env python3
"""Стабильность безопасной короткой книги: размер билета и плечо забора — кассой.

Решение владельца 2026-10-03 («давай все сразу по очереди») по разбору
«почему шорты нестабильнее лонгов»: у `safe_h` дисперсию дня и деньги
делают одни и те же позиции на плече ≥ 15×, а 77 % сделок на плече < 5×
(забор не даёт размера волатильному имени) дают −154 $ и четверть
дисперсии. Два рычага объявлены здесь, до прогона:

- **билет 0.5** (`rules.SHORT_SHARE["safe_h"]` 1.0 → 0.5): линейно режет
  σ дня и деньги, отношение день/σ не трогает — считается кассой, чтобы
  видеть, что сделают слоты и очередь денег при меньшем билете;
- **плечо забора ≥ 5×**: решение без размера в книгу не входит. Это
  правило конструкции (книга торгует там, где может размер), не отбор по
  модели, но судится как отбор — против случайной выборки ТОГО ЖЕ числа
  убранных сделок (200 зёрен): правило обязано удержать деньги, которые
  случайная уносит, и срезать дисперсию.

Исходы позиций не меняются (размер и гейт — свойства кассы), поэтому
считается на записях кэша без реплея; оба рычага — на `safe_h`, остальные
книги не трогаются. Цифры — $10k, нетто.
"""
import argparse
import math
import os
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
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import entry_gate as E                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import wave_guard as W                                        # noqa: E402

ART = "DCA-short-size"
BOOK = "safe_h"
SEEDS = 200                       # объявлено до прогона
MAIN_DEP = 10000
SHARE = 0.5                       # билет безопасной: половина
MIN_LEV = 5.0                     # плечо забора, ниже которого книга не входит
CELLS = (("as_is", "как сейчас"), ("ticket", f"билет {SHARE:g}"),
         ("lev", f"плечо ≥ {MIN_LEV:g}×"), ("both", f"билет {SHARE:g} и плечо ≥ {MIN_LEV:g}×"))


def lev_gate(recs, min_lev=MIN_LEV):
    """Записи с плечом забора ≥ порога; плечо неизвестно — остаётся и считается."""
    keep, unknown = [], 0
    for r in recs:
        lv = r.get("lev")
        if lv is None:
            unknown += 1
            keep.append(r)
            continue
        if float(lv) >= float(min_lev):
            keep.append(r)
    return keep, unknown


def with_share(book, share, fn):
    """Доля билета книги на время счёта — и назад, что бы ни случилось."""
    was = R.SHORT_SHARE.get(book)
    R.SHORT_SHARE[book] = float(share)
    try:
        return fn()
    finally:
        if was is None:
            R.SHORT_SHARE.pop(book, None)
        else:
            R.SHORT_SHARE[book] = was


def day_sigma(days):
    """σ дня и отношение средний день / σ — по дням кассы."""
    u = [float(d.get("usd") or 0.0) for d in (days or [])]
    if len(u) < 2:
        return None, None
    sd = statistics.pstdev(u)
    return sd, ((sum(u) / len(u)) / sd if sd > 0 else None)


def run(seeds=SEEDS, log=print, now=None, launch=None, ctx=None, mem_limit=None,
        dep=MAIN_DEP):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    packed = {BOOK: AG.packed_short(cache).get(BOOK) or []}
    kept, unknown = lev_gate(packed[BOOK])
    log(f"{BOOK}: записей {len(packed[BOOK])}, с плечом ≥ {MIN_LEV:g}× {len(kept)} "
        f"(плечо неизвестно у {unknown})")
    gated = {BOOK: kept}
    stats = lambda p: AG.stats_of(p, ctx, launch, [BOOK], deps=[dep], now=now)   # noqa: E731
    cells = {
        "as_is": stats(packed),
        "ticket": with_share(BOOK, SHARE, lambda: stats(packed)),
        "lev": stats(gated),
        "both": with_share(BOOK, SHARE, lambda: stats(gated)),
    }
    out = {}
    for key, _title in CELLS:
        c = cells[key].get(f"{BOOK}:{dep}") or {}
        sd, ratio = day_sigma(c.get("days"))
        _tot, wo, _top = W.wo3(c.get("days"))
        out[key] = {"n": c.get("n"), "final": c.get("final"), "max_dd": c.get("max_dd"),
                    "usd": c.get("usd"), "wo3": wo, "sigma_day": sd, "ratio_day": ratio,
                    "tails": W.tails_of(c), "days": c.get("days")}
        log(f"{key}: сделок {c.get('n')}, итог {c.get('final')}, просадка {c.get('max_dd')}, "
            f"σ дня {None if sd is None else round(sd)}")
    ctl = E.control_rows(packed, {BOOK: len(kept)}, ctx, launch, [BOOK], seeds=seeds,
                         dep=dep, now=now, log=log)
    g = cells["lev"].get(f"{BOOK}:{dep}") or {}
    beat = {f: AG.beat_share(ctl.get(BOOK), g.get(f), f)[0] for f in ("final", "ratio")}
    return {"book": BOOK, "dep": dep, "share": SHARE, "min_lev": MIN_LEV, "seeds": int(seeds),
            "removed": len(packed[BOOK]) - len(kept), "offered": len(packed[BOOK]),
            "unknown_lev": unknown, "cells": out, "beat": beat,
            "days_diff": W.day_diff(out["as_is"]["days"], out["lev"]["days"]),
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _sd(x):
    return "—" if x is None else f"{float(x):.0f} $"


def report(s):
    L = ["# Стабильность безопасной короткой книги: билет и плечо забора", "",
         "Решение владельца 2026-10-03. Два рычага объявлены до прогона: билет "
         f"{s.get('share', SHARE):g} вместо целого и вход только при плече забора ≥ "
         f"{s.get('min_lev', MIN_LEV):g}×. Исходы позиций те же (размер и гейт — "
         "свойства кассы), деньги — касса семейства на записях кэша, "
         f"${int(s.get('dep') or MAIN_DEP):,}, нетто. Гейт по плечу судится против "
         f"случайной выборки того же числа убранных сделок ({s.get('seeds') or SEEDS} "
         "зёрен): он обязан удержать деньги, которые случайная уносит.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой части.", ""]
    L += [f"Записей {s.get('offered')}, гейт убирает {s.get('removed')} "
          f"(плечо неизвестно у {s.get('unknown_lev')} — они остаются).", "",
          "| ячейка | сделок | итог | просадка | $ всего | $ без 3 лучших дней | σ дня | "
          "день/σ | хвостовых выходов |", "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for key, title in CELLS:
        c = (s.get("cells") or {}).get(key) or {}
        L.append(f"| {title} | {c.get('n', '—')} | {_pp(c.get('final'))} | {_pp(c.get('max_dd'))} "
                 f"| {_usd(c.get('usd'))} | {_usd(c.get('wo3'))} | "
                 f"{_sd(c.get('sigma_day'))} | {_f(c.get('ratio_day'))} | {c.get('tails', '—')} |")
    b = s.get("beat") or {}
    L += ["", f"**Гейт по плечу против случайного удаления того же числа сделок:** случайная "
          f"не хуже по итогу в {_pp(b.get('final'), 0)} зёрен, по доходу/просадке в "
          f"{_pp(b.get('ratio'), 0)}.", ""]
    dd = s.get("days_diff") or {}
    L += ["## Гейт по плечу — по дням", "",
          f"Дней {dd.get('n_days')}, с гейтом лучше в {dd.get('better')}, хуже в "
          f"{dd.get('worse')}, разница всего {_usd(dd.get('sum_diff'))}.", ""]
    rows = dd.get("rows") or []
    if rows:
        L += ["| день | как сейчас | с гейтом | разница |", "|---|--:|--:|--:|"]
        L += [f"| {x['d']} | {_usd(x['base'])} | {_usd(x['rule'])} | {_usd(x['diff'])} |"
              for x in rows]
        L.append("")
    L += ["## Как читать", "",
          "- Билет линеен: итог и σ дня делятся на два, день/σ стоит на месте; "
          "расхождение с линейностью — работа слотов и очереди денег.",
          "- Гейт по плечу — правило, если σ дня падает, а деньги остаются; если "
          "случайная выборка того же размера держит деньги не хуже — он ничего не знает.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


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
        publish("стабильность безопасной короткой книги: билет и плечо забора")


if __name__ == "__main__":
    main()
