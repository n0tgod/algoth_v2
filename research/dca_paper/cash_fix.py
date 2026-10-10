#!/usr/bin/env python3
"""Отчёт о правке кассы бумаги (2026-10-10): насколько меняются книги.

Правка (`run_d6.ration`, `profit_to_cash`): закрытая позиция возвращает в
свободные деньги маржу ВМЕСТЕ с результатом. Прежде возвращалась только
маржа, и книга со сложным процентом теряла места по мере роста счёта
(`pair_aggr` 100 $: счёт 665 $, свободно 15.96 $ — две позиции из 16).

Обе версии считаются СЕЙЧАС, на одном кэше реплея и теми же функциями, что
часовые прогоны трёх семейств (длинные, короткие `h24`, общий счёт), с
издержками (`costs.apply_to_rows`), — разница между колонками есть только
правило кассы. Журналы не пишутся. Рядом печатается то, что стоит на
странице сейчас (запись вперёд прежней версии), — сверка, а не довод.

    run research/dca_paper/cash_fix.py
"""
import argparse
import functools
import gc
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as RS                                        # noqa: E402
import run_pair as PR                                         # noqa: E402
import run_d6 as D6                                           # noqa: E402
import arm_book as AB                                         # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-cash-fix.md")
OUT_JSON = os.path.join(R.OUT, "DCA-cash-fix.json")
MEM_LIMIT_MB = 2200
REAL_RATION = D6.ration

T = lambda t: time.strftime("%Y-%m-%d", time.gmtime(float(t))) if t else "—"   # noqa: E731


def packed_long(log):
    cache, why = RP.read_cache()
    if why:
        raise SystemExit(f"кэш длинных книг не годен: {why}")
    keys = R.order_of("sit")
    by_pair = {}
    for (pr, _s, _a), r in cache.items():
        by_pair.setdefault(tuple(pr), []).append(r)
    return {k: by_pair.get(tuple(RP.RULERS[k]), []) for k in keys}, keys


def packed_short(log, now, launch):
    cache, why = RS.read_cache(log=log)
    if why:
        raise SystemExit(f"кэш коротких книг не годен: {why}")
    by_ruler = {}
    for (rk, _s, _a), r in cache.items():
        by_ruler.setdefault(rk, []).append(r)
    packed = {bk: list(by_ruler.get(rk) or []) for bk, rk in RS.BOOKS.items()}
    for bk in list(packed):
        packed[bk], _ = RP.age_shorts(packed[bk], bk, launch=launch, log=log, now=now)
        packed[bk], _ = RP.guard_shorts(packed[bk], bk, log=log, now=now)
    return packed, list(R.H24_ORDER)


def packed_pair(log, now, launch, ctx):
    keys = list(R.PAIR_ORDER)
    longs, why_l = PR.long_recs(log=log)
    shorts, why_s = PR.short_recs(log=log)
    if why_l or why_s:
        raise SystemExit(f"кэш общего счёта не годен: {why_l or why_s}")
    packed = PR.pack(longs, shorts, keys)
    for pk in keys:
        lk, sk = R.parts_of(pk)
        mine = [r for r in packed[pk] if (r.get("book") or pk) == sk]
        kept, _ = PR.gate_shorts(mine, pk, ctx, log=log)
        kept, _ = RP.age_shorts(kept, pk, launch=launch, log=log, now=now)
        kept, _ = RP.guard_shorts(kept, pk, log=log, now=now)
        packed[pk] = [r for r in packed[pk] if (r.get("book") or pk) == lk] + kept
    return packed, keys


def both(packed, keys, now, ctx, log):
    """Строки книг прежним и новым правилом кассы, с издержками."""
    import costs as CO
    out = {}
    for name, ptc in (("old", False), ("new", True)):
        D6.ration = functools.partial(REAL_RATION, profit_to_cash=ptc)
        try:
            rows, cells, _one, live = RP.build_rows(packed, now=now, keys=keys, log=lambda *a: None)
        finally:
            D6.ration = REAL_RATION
        rows, _ = CO.apply_to_rows(rows, ctx)
        out[name] = (rows, cells, live)
        log(f"  {name}: строк {len(rows)}")
    return out


def cell_stats(rows, rk, dep, sizing, since):
    mine = [r for r in rows if R.ruler_of(r) == rk and int(r.get("dep", 0)) == int(dep)
            and R.sizing_of(r) == sizing]
    win = [r for r in mine if since is not None and float(r["at"]) >= float(since)]
    return RP._stats(mine, dep), RP._stats(win, dep)


def g(st, k):
    return None if not st else st.get(k)


def pct(v):
    return "—" if v is None else f"{v * 100:+.1f} %"


def num(v):
    return "—" if v is None else f"{v:g}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = AB.guarded(print, limit=MEM_LIMIT_MB)
    t0 = time.time()
    now = time.time()
    import costs as CO
    ctx = CO.context()
    launch = RS.IR.launches()
    fams = [("Длинные книги", R.ARTIFACT, lambda: packed_long(log)),
            ("Короткие книги h24", R.H24_ARTIFACT, lambda: packed_short(log, now, launch)),
            ("Общий счёт", R.PAIR_ARTIFACT, lambda: packed_pair(log, now, launch, ctx))]
    res = []
    for title, art, build in fams:
        log(f"{title}: сборка решений")
        try:
            with open(art, encoding="utf-8") as f:
                before = (json.load(f).get("books") or {})
        except (OSError, ValueError) as e:
            log(f"  свод {art} не читается: {e}")
            before = {}
        packed, keys = build()
        got = both(packed, keys, now, ctx, log)
        del packed
        for rk in keys:
            for dep in R.DEPOSITS:
                for sizing in R.SIZINGS:
                    key = RP._cell(rk, dep, sizing)
                    b = before.get(key) or {}
                    since = b.get("forward_since")
                    o_all, o_win = cell_stats(got["old"][0], rk, dep, sizing, since)
                    n_all, n_win = cell_stats(got["new"][0], rk, dep, sizing, since)
                    co, cn = got["old"][1].get(key) or {}, got["new"][1].get(key) or {}
                    res.append({
                        "family": title, "book": rk, "title": R.ruler_title(rk), "dep": dep,
                        "sizing": sizing, "since": since,
                        "page_forward_final": g(b.get("forward"), "final"),
                        "old_all": {k: g(o_all, k) for k in ("n", "usd", "final", "max_dd")},
                        "new_all": {k: g(n_all, k) for k in ("n", "usd", "final", "max_dd")},
                        "old_win": {k: g(o_win, k) for k in ("n", "usd", "final", "max_dd")},
                        "new_win": {k: g(n_win, k) for k in ("n", "usd", "final", "max_dd")},
                        "old_no_cash": co.get("no_cash"), "new_no_cash": cn.get("no_cash"),
                        "old_open": len((got["old"][2].get(key) or {}).get("positions") or []),
                        "new_open": len((got["new"][2].get(key) or {}).get("positions") or []),
                    })
        del got
        gc.collect()
        log(f"{title}: готово, {time.time() - t0:.0f} с")
    os.makedirs(R.OUT, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)),
                   "rows": res}, f, ensure_ascii=False, indent=1)
    txt = report(res, now)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "DCA-cash-fix"], cwd=ROOT, check=False)
    return 0


def report(res, now):
    L = [f"# Правка кассы бумаги: до и после ({time.strftime('%Y-%m-%d %H:%M', time.gmtime(now))} UTC)", "",
         "Правка: закрытая позиция возвращает в свободные деньги маржу ВМЕСТЕ с результатом "
         "(прежде — только маржу). Обе колонки посчитаны сейчас на одном кэше, с издержками; "
         "разница — только правило кассы. «Окно вперёд» — с первого решения записи вперёд "
         "этой книги на странице (дата в строке); «на странице» — число, стоящее там сейчас "
         "(прежнее правило, запись вперёд).", ""]
    for fam in dict.fromkeys(r["family"] for r in res):
        L += [f"## {fam}", "",
              "| книга | депозит | формат | весь период: итог до → после | просадка до → после | сделок до → после "
              "| окно вперёд с | итог окна до → после | на странице | отказов кассы до → после |",
              "|---|---:|---|---|---|---|---|---|---:|---|"]
        for r in res:
            if r["family"] != fam:
                continue
            L.append(
                f"| {r['title']} | {r['dep']:g} | {'слож.' if r['sizing'] == R.DEFAULT_SIZING else 'фикс.'} "
                f"| {pct(r['old_all']['final'])} → {pct(r['new_all']['final'])} "
                f"| {pct(r['old_all']['max_dd'])} → {pct(r['new_all']['max_dd'])} "
                f"| {num(r['old_all']['n'])} → {num(r['new_all']['n'])} "
                f"| {T(r['since'])} | {pct(r['old_win']['final'])} → {pct(r['new_win']['final'])} "
                f"| {pct(r['page_forward_final'])} | {num(r['old_no_cash'])} → {num(r['new_no_cash'])} |")
        L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
