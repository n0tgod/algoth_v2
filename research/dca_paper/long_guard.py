"""Замер: охрана рынком на ДЛИННЫХ книгах (вопрос владельца 2026-10-16).

Зеркало правила коротких книг: длинная позиция закрывается по закрытию
часа, когда средний ход крупных имён рынка (`wave.PROXY`) с момента
входа упал на ≥ порога. Ядро то же (`wave.apply_guard(..., down=True)`):
отметка ядра за час триггера, срез отметок, цена выхода из заполнений.

Объявлено ДО прогона:
* ось порогов — та же, что у коротких (`guard_sweep.AXIS`): без охраны,
  1 / 1.5 / 2 / 3 / 4 / 6 %;
* окна: вся запись; половины по моменту решения (медиана) — до слова
  «лучше» (урок 08.10); с 13.09 — для сравнения с короткими;
* нуль: те же ЧАСЫ закрытия, что дал порог, но позиция в каждом часе —
  случайная из открытых в этот час (урок: фильтр, режущий выходы,
  сравнивается со случайной выборкой того же размера), `--seeds` зёрен,
  на всей записи, для порогов 2 и 4 % (действующий у шортов и прежний);
* деньги — КАССА длинных книг тем же ядром (`run_paper.build_rows`),
  депозиты $1k и $10k, сложный процент; БРУТТО (издержки не вычтены:
  короче удержание — меньше funding, число заполнений то же — сказано
  в отчёте).

Ничего не меняет: книги, журналы и кэши не пишутся.

    run research/dca_paper/long_guard.py --seeds=20
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_pair as RPair                                      # noqa: E402
import wave as WV                                             # noqa: E402
import arm_book as AB                                         # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-long-guard.md")
OUT_JSON = os.path.join(R.OUT, "DCA-long-guard.json")
AXIS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
NULL_AT = (2.0, 4.0)
DEPS = (1000.0, 10000.0)
SINCE = "2026-09-13"
HOUR = 3600.0
WHY = "рынок"
MEM_LIMIT_MB = 3000


def kmax_of(book):
    return R.hold_of(book) - 1


def guard_book(recs, pct, mkt, book):
    """Записи книги под охраной порога pct (вниз) и сводка срабатываний."""
    if pct is None:
        return list(recs), [], {"closed_by_market": 0}
    out, st = WV.apply_guard(recs, pct, mkt, kmax_of(book), why=WHY, down=True)
    hits = []
    for a, b in zip(recs, out):
        if b is not a and b.get("exit") == WHY:
            hits.append((a, b))
    return out, hits, st


def cash(by, keys, now):
    """Касса длинных книг: {книга: {депозит: stats}} по строкам `build_rows`."""
    rows, _c, _o, _l = RP.build_rows(by, now=now, keys=keys, log=lambda *a: None)
    out = {}
    for k in keys:
        for d in DEPS:
            sub = [r for r in rows if r.get("ruler") == k and int(r.get("dep", 0)) == int(d)
                   and not r.get("sizing") and r.get("usd") is not None]
            st = RP._stats(sub, d) or {}
            out.setdefault(k, {})[int(d)] = {m: st.get(m) for m in
                                              ("final", "max_dd", "n", "win", "usd_wo_top3d", "usd")}
    return out


def open_index(recs, book):
    """Часы, в которые позиция открыта и может быть закрыта: {час: [(i, k)]}."""
    idx = {}
    for i, r in enumerate(recs):
        p = WV.path_of(r)
        if not p:
            continue
        closed = (r.get("state") or "closed") == "closed"
        last = min(kmax_of(book), p["K"] - 1 if closed else p["K"])
        at = float(r["at"])
        for k in range(1, last + 1):
            idx.setdefault(int((at + k * HOUR) // HOUR), []).append((i, k))
    return idx


def null_book(recs, hits, idx, rng):
    """Те же часы закрытия, случайные позиции из открытых в этот час."""
    out = list(recs)
    used, miss = set(), 0
    for a, b in hits:
        h = int((float(b["exit_ts"]) + 1.0) // HOUR)
        cand = [(i, k) for (i, k) in idx.get(h, ()) if i not in used]
        if not cand:
            miss += 1
            continue
        i, k = rng.choice(cand)
        used.add(i)
        out[i] = WV.guard_record(recs[i], k, why="случайный")
    return out, miss


def pos_stats(hits):
    """Что охрана сделала с ПОЗИЦИЯМИ (в долях маржи, без кассы)."""
    if not hits:
        return {"n": 0}
    d = [float(b["pnl"]) - float(a["pnl"]) for a, b in hits]
    win_cut = sum(1 for a, b in hits if float(a["pnl"]) > float(b["pnl"]))
    tails = sum(1 for a, _b in hits if float(a["pnl"]) <= -0.5)
    return {"n": len(hits), "delta_mean": sum(d) / len(d),
            "delta_sum": sum(d), "worse": win_cut,
            "tails_saved": tails}


def window(by, lo=None, hi=None):
    return {k: [r for r in v if (lo is None or float(r["at"]) >= lo)
                and (hi is None or float(r["at"]) < hi)] for k, v in by.items()}


def run(seeds, log):
    t0 = time.time()
    # касса только нужных депозитов и одного формата — вчетверо быстрее;
    # подмена живёт в процессе замера и никуда не пишется
    R.DEPOSITS[:] = list(DEPS)
    R.SIZINGS = (R.SIZING_COMPOUND,)
    now = time.time()
    longs, why = RPair.long_recs(log=log)
    if why or not longs:
        return {"error": why or "длинных позиций нет"}
    keys = [k for k in R.order_of("sit") if k in longs]
    mkt = WV.Market(WV.Hours())
    ats = sorted(float(r["at"]) for v in longs.values() for r in v)
    mid = ats[len(ats) // 2]
    since = time.mktime(time.strptime(SINCE, "%Y-%m-%d")) - time.timezone
    wins = {"all": (None, None), "half1": (None, mid), "half2": (mid, None),
            "since": (since, None)}
    res = {"axis": [None] + list(AXIS), "seeds": seeds, "keys": keys,
           "mid": mid, "since": SINCE, "windows": {}, "null": {}}
    for wname, (lo, hi) in wins.items():
        part = window(longs, lo, hi)
        cells = {}
        for pct in (None,) + AXIS:
            by, hits_all, stats = {}, {}, {}
            for k in keys:
                g, hits, st = guard_book(part.get(k, []), pct, mkt, k)
                by[k], hits_all[k], stats[k] = g, hits, st
            c = cash(by, keys, now)
            cells["off" if pct is None else f"{pct:g}"] = {
                "cash": c, "pos": {k: pos_stats(hits_all[k]) for k in keys},
                "hours_no_wave": sum(s.get("hours_no_wave", 0) for s in stats.values())}
            log(f"окно {wname}, порог {pct}: посчитано ({time.time() - t0:.0f} с)")
            if wname == "all" and pct in NULL_AT:
                rule = c
                draws = []
                idx = {k: open_index(part.get(k, []), k) for k in keys}
                for sd in range(seeds):
                    rng = random.Random(1000 + sd)
                    nb, misses = {}, 0
                    for k in keys:
                        nb[k], m = null_book(part.get(k, []), hits_all[k], idx[k], rng)
                        misses += m
                    draws.append({"cash": cash(nb, keys, now), "miss": misses})
                    log(f"  нуль {pct:g} %: зерно {sd + 1}/{seeds}")
                share = {}
                for k in keys:
                    for d in DEPS:
                        rv = (rule[k][int(d)] or {}).get("final")
                        xs = [(x["cash"][k][int(d)] or {}).get("final") for x in draws]
                        xs = [x for x in xs if x is not None]
                        share[f"{k}:{int(d)}"] = (None if rv is None or not xs
                                                  else sum(1 for x in xs if x >= rv) / len(xs))
                res["null"][f"{pct:g}"] = {"share_not_worse": share,
                                           "misses": [x["miss"] for x in draws]}
        res["windows"][wname] = cells
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


def _pp(x):
    return "—" if x is None else f"{100.0 * float(x):+.1f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


TITLE = {"off": "без охраны"}
WIN_TITLE = {"all": "Вся запись", "half1": "Первая половина (по моменту решения)",
             "half2": "Вторая половина", "since": "С 2026-09-13 (окно сравнения с короткими)"}


def report(res):
    if res.get("error"):
        return f"# Охрана рынком на длинных книгах\n\nНе посчитано: {res['error']}.\n"
    L = ["# Охрана рынком на длинных книгах", "",
         "Зеркало правила коротких: длинная позиция закрывается по закрытию часа, когда средний ход "
         "крупных имён рынка с момента входа упал на ≥ порога. Ось объявлена до прогона — та же, что "
         "у коротких. Касса длинных книг тем же ядром, деньги БРУТТО (короче удержание — меньше "
         "funding; число заполнений то же). «Позиций закрыто» — сколько позиций охрана закрыла "
         "раньше их выхода; «Δ на позицию» — средняя разница исхода позиции в долях её маржи "
         "(+ — охрана помогла); «хвостов снято» — закрытые охраной позиции, которые без неё кончили "
         "хуже −50 % маржи; «срезано победителей» — закрытые, которые без неё кончили лучше.", ""]
    for wname in ("all", "half1", "half2", "since"):
        cells = res["windows"].get(wname) or {}
        if not cells:
            continue
        L += [f"## {WIN_TITLE[wname]}", ""]
        for k in res["keys"]:
            L += [f"### {R.title_en(k)} (длинная, `{k}`)", "",
                  "| порог | $1k итог | $1k просадка | $10k итог | $10k просадка | $10k без 3 дней | "
                  "позиций закрыто | Δ на позицию | хвостов снято | срезано победителей |",
                  "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
            for key in ["off"] + [f"{a:g}" for a in AXIS]:
                c = cells.get(key)
                if not c:
                    continue
                a = c["cash"][k][1000]
                b = c["cash"][k][10000]
                p = c["pos"][k]
                n = p.get("n", 0)
                dm = "—" if not n else "%+.1f п.п." % (100 * p["delta_mean"])
                ts = "—" if not n else str(p["tails_saved"])
                wc = "—" if not n else str(p["worse"])
                name = TITLE.get(key, "≥ " + key + " %")
                L.append("| %s | %s | %s | %s | %s | %s | %d | %s | %s | %s |" % (
                    name, _pp(a.get("final")), _pp(a.get("max_dd")), _pp(b.get("final")),
                    _pp(b.get("max_dd")), _usd(b.get("usd_wo_top3d")), n, dm, ts, wc))
            L.append("")
    if res.get("null"):
        L += ["## Нуль: те же часы закрытия, случайные открытые позиции", "",
              f"{res['seeds']} зёрен на всей записи. Число — доля зёрен, где случайные закрытия дали итог "
              "НЕ ХУЖЕ правила (около 0 — правило лучше случайного, около 1 — хуже). Разрешение — "
              f"1/{res['seeds']}.", "",
              "| порог | " + " | ".join(f"{R.title_en(k)} $1k | {R.title_en(k)} $10k" for k in res["keys"]) + " |",
              "|---|" + "--:|" * (2 * len(res["keys"]))]
        for pk, v in res["null"].items():
            sh = v["share_not_worse"]
            def _sh(x):
                return "—" if x is None else "%.2f" % x
            L.append("| ≥ %s %% | " % pk + " | ".join(
                _sh(sh.get(k + ":1000")) + " | " + _sh(sh.get(k + ":10000"))
                for k in res["keys"]) + " |")
        L.append("")
    L.append(f"Прогон {res.get('secs')} с, {res.get('computed_at')} UTC.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = AB.guarded(print, limit=MEM_LIMIT_MB)
    res = run(a.seeds, log)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "замер: охрана рынком на длинных книгах"], cwd=ROOT, check=False)


if __name__ == "__main__":
    main()
