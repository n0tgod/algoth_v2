#!/usr/bin/env python3
"""Насколько важна охрана рынком: без неё и с другими порогами.

Вопрос владельца 2026-10-16 после ложного срабатывания охраны. Замер
один в один повторяет метод `wave_guard.py` (13.09), но на ВСЕЙ записи
до сегодня и отдельно на окне ВПЕРЁД с 13.09 — дня, когда порог 2 %
был выбран: на этом окне правило не подбиралось, и только оно судит.

* ось: без охраны; волна с входа ≥ 1 / 1.5 / 2 / 3 / 4 / 6 %;
* книги: три короткие `h24` на $1k и $10k (деньги НЕТТО, `cell_stats`),
  общий счёт (Both) трёх режимов — брутто (`run_paper.build_rows`);
* нуль: случайные выходы ТОГО ЖЕ числа сделок в ТЕ ЖЕ часы среди
  открытых, `--seeds` зёрен, на $10k (`path_screen.control_exits`);
* концентрация: «$ без 3 лучших дней» (`wave_guard.wo3`).

Карта порогов `rules.WAVE_GUARD_PCT` на время прогона очищается: ось
ставит выходы сама (`apply_axis`), иначе охрана применилась бы дважды.
Ничего не меняет в книгах.

    run research/dca_paper/guard_sweep.py --seeds=30
"""
import argparse
import json
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
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_short as S                                         # noqa: E402
import run_paper as RP                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import tail_screen as T                                       # noqa: E402
import path_screen as P                                       # noqa: E402
import wave_guard as W                                        # noqa: E402
import guard_forward as GF                                    # noqa: E402
import noncrypto_pair as NP                                   # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-guard-sweep.md")
OUT_JSON = os.path.join(R.OUT, "DCA-guard-sweep.json")
AXIS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
SINCE = "2026-09-13"
DEPS = (1000, 10000)


def short_sweep(cache, views, ctx, launch, seeds, log):
    """Короткие книги: база без охраны и ось порогов с контролем."""
    saved = dict(R.WAVE_GUARD_PCT)
    try:
        R.WAVE_GUARD_PCT.clear()
        base, cells = W.evaluate(cache, views, ctx, launch, seeds=seeds,
                                 log=log, axis=AXIS)
    finally:
        R.WAVE_GUARD_PCT.clear()
        R.WAVE_GUARD_PCT.update(saved)
    return base, cells


def pair_sweep(lcache, scache, ctx, launch, since_ts, log):
    """Общий счёт: касса по порогам (брутто), короткая сторона под охраной."""
    now = time.time()
    longs = NP.long_all(lcache)
    if since_ts:
        longs = {k: [r for r in v if float(r["at"]) >= since_ts] for k, v in longs.items()}
        scache = {k: r for k, r in scache.items() if float(r["at"]) >= since_ts}
    import run_pair as RPair
    shorts, _ = RPair.short_recs(scache, log=lambda *a: None)
    keys = list(R.PAIR_ORDER)
    saved = dict(R.WAVE_GUARD_PCT)
    out = {}
    try:
        for pct in (None,) + AXIS:
            R.WAVE_GUARD_PCT.clear()
            if pct is not None:
                R.WAVE_GUARD_PCT.update({k: float(pct) for k in saved})
            sready = NP.shorts_ready(shorts, ctx, launch, keys, now)
            out["off" if pct is None else f"{pct:g}"] = NP.pair_cash(
                longs, sready, keys, lambda r: True, now)
            log(f"  общий счёт, порог {pct}: посчитан")
    finally:
        R.WAVE_GUARD_PCT.clear()
        R.WAVE_GUARD_PCT.update(saved)
    return out


def run(seeds, log):
    t0 = time.time()
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш коротких непригоден: {why}"}
    lcache, why_l = RP.read_cache()
    ctx = CO.context()
    launch = IR.launches()
    hours = T.Hours(root=T.SUMMARY_DIR)
    mkt = P.Market(hours)
    closed = {key: r for key, r in cache.items()
              if key[0] in T.RULERS and r.get("state", "closed") == "closed"}
    views = {key: P.view_of(r, mkt) for key, r in closed.items()}
    log(f"коротких записей {len(cache)}, закрытых сделок {len(views)}; "
        f"волна не собралась {mkt.wave_none} раз ({time.time() - t0:.0f} с)")
    res = {"axis": list(AXIS), "seeds": seeds, "since": SINCE, "windows": {},
           "guard_now": dict(R.WAVE_GUARD_PCT), "costs_error": (ctx or {}).get("error")}
    for name, since in (("all", None), ("forward", SINCE)):
        c = cache if since is None else GF.forward_cache(cache, since)
        v = views if since is None else {k: x for k, x in views.items() if k in c}
        log(f"окно «{name}»: записей {len(c)}, сделок {len(v)}")
        base, cells = short_sweep(c, v, ctx, launch, seeds, log)
        pair = None
        if not why_l and lcache:
            pair = pair_sweep(lcache, cache, ctx, launch,
                              GF.since_ts(since) if since else None, log)
        res["windows"][name] = {"n": len(c), "base": base, "cells": cells, "pair": pair}
        log(f"окно «{name}» посчитано ({time.time() - t0:.0f} с)")
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def report(res):
    L = ["# Охрана рынком: без неё и с другими порогами", "",
         "Ось — волна 20 крупных имён с момента входа, при которой шорт закрывается по "
         "закрытию часа: без охраны и пороги " + ", ".join(f"{a:g} %" for a in AXIS) +
         ". Действующее правило — 2 %. Короткие книги — деньги НЕТТО; общий счёт (Both) — "
         "брутто. Нуль — случайные выходы того же числа сделок в те же часы среди открытых, "
         f"{res['seeds']} зёрен, на $10k: «нуль не хуже» — доля зёрен, где случайные выходы "
         "дали итог не ниже правила (около 0 — правило лучше случайного, около 1 — хуже). "
         "«$ без 3» — сумма дней без трёх лучших: правило, живущее одним днём, здесь "
         "проваливается.", ""]
    if res.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {res['error']}.", ""])
    if res.get("costs_error"):
        L += [f"**Издержки:** {res['costs_error']}.", ""]
    for name, title in (("all", "Вся запись (с 04.08)"),
                        ("forward", f"Вперёд с {res['since']} — окно, на котором порог не подбирался")):
        w = res["windows"].get(name)
        if not w:
            continue
        L += [f"## {title} · записей {w['n']}", ""]
        for bk in W.BOOK_KEYS:
            L += [f"### {R.ruler_title(bk)}", "",
                  "| порог | $1k итог | $1k просадка | $10k итог | $10k просадка | $10k без 3 | "
                  "хвостовых | сделок изменено | нуль не хуже ($10k) |",
                  "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
            b1 = (w["base"] or {}).get(f"{bk}:1000") or {}
            b10 = (w["base"] or {}).get(f"{bk}:10000") or {}
            _t, w3, _d = W.wo3(b10.get("days"))
            L.append(f"| без охраны | {_pp(b1.get('final'))} | {_pp(b1.get('max_dd'))} | "
                     f"{_pp(b10.get('final'))} | {_pp(b10.get('max_dd'))} | {_usd(w3)} | "
                     f"{W.tails_of(b10)} | 0 | — |")
            for c in w["cells"]:
                st = c.get("stats") or {}
                s1, s10 = st.get(f"{bk}:1000") or {}, st.get(f"{bk}:10000") or {}
                _t, w3, _d = W.wo3(s10.get("days"))
                beat = (c.get("beat") or {}).get(bk, {}).get("final")
                mark = " ← действует" if abs(float(c["val"]) - 2.0) < 1e-9 else ""
                L.append(f"| ≥ {c['val']:g} %{mark} | {_pp(s1.get('final'))} | {_pp(s1.get('max_dd'))} | "
                         f"{_pp(s10.get('final'))} | {_pp(s10.get('max_dd'))} | {_usd(w3)} | "
                         f"{W.tails_of(s10) if s10 else '—'} | {(c.get('delta') or {}).get('n', 0)} | "
                         f"{('—' if beat is None else f'{beat:.2f}')} |")
            L.append("")
        if w.get("pair"):
            L += ["### Общий счёт (Both), брутто", "",
                  "| порог | " + " | ".join(f"{R.MODE_EN[R.parts_of(pk)[0]]} $1k / $10k" for pk in R.PAIR_ORDER) + " |",
                  "|---|" + "--:|" * len(R.PAIR_ORDER)]
            for key in ["off"] + [f"{a:g}" for a in AXIS]:
                cells = w["pair"].get(key) or {}
                row = []
                for pk in R.PAIR_ORDER:
                    a, b = cells.get(f"{pk}:1000") or {}, cells.get(f"{pk}:10000") or {}
                    row.append(f"{_pp(a.get('final'))} ({_pp(a.get('max_dd'), 0)}) / "
                               f"{_pp(b.get('final'))} ({_pp(b.get('max_dd'), 0)})")
                label = "без охраны" if key == "off" else f"≥ {key} %" + (" ← действует" if key == "2" else "")
                L.append(f"| {label} | " + " | ".join(row) + " |")
            L.append("")
    L.append(f"Прогон {res['secs']} с, {res['computed_at']} UTC.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = AB.guarded(print, limit=2400)
    res = run(a.seeds, log)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "замер: охрана рынком — без неё и с другими порогами"],
                       cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
