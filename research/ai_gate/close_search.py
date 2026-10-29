#!/usr/bin/env python3
"""Ранний выход по смене состояния (спека 19 §11.11; владелец 29.10: «модель
должна сама анализировать, когда лучше закрывать сделку раньше времени, если
на рынке что-то сменилось»).

Таблица: у каждой закрытой позиции книги Depth · Short (записи кэша коротких
с отметками часов) — параметры состояния рынка на каждом часе h = 1…HMAX после
входа (те же формулы `entry_search.features`) и результат, если закрыть по
рынку на отметке часа после решения (`wave.guard_record`, как сторож судьи и
охрана рынком). Правило закрытия: условия на полях состояния в час h → первый
такой час закрывает; не наступило — позиция живёт до своего выхода.

Что печатается: «закрытие по состоянию» (описание, не отбор) — по терцилям
каждого поля: средний прирост к исходу книги, если закрывать в первый час,
когда поле в терциле, и половины; правила закрытия модели — на подходящих
позициях средний при закрытии против их же исхода, прирост на позицию, нуль
(случайный час закрытия у тех же позиций, 400) и половины.

Отчёт `out/CLOSE-SEARCH.md`, `out/close_search.json`; таблица
`out/record/close_table.npz` (не в git).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
for _p in (os.path.join(ROOT, "research", "dca_paper"), os.path.join(ROOT, "research", "dca_ladder")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import entry_search as ES                                       # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "CLOSE-SEARCH.md")
LATEST = os.path.join(OUT, "close_search.json")
TABLE = os.path.join(OUT, "record", "close_table.npz")
H = 3600.0
HMAX = 23                     # часов после входа, в которые судится закрытие (срок книги 24 ч)
EDGE_S = 300                  # решение по часу — когда сводка часа легла
DAYS = 45
MIN_COVER = 0.90
MIN_N = 30
NULL_DRAWS = 400
RULER = "optimal_s"           # линейка кэша книги Depth · Short


def pct(v):
    return "—" if v is None else f"{100 * v:+.2f} %"


def close_pnl(rec, h):
    """Нетто позиции, закрытой по решению в час h (отметка часа после решения); None — уже вышла."""
    import gate_books as GB                                     # noqa: E402
    import wave as WV                                           # noqa: E402
    k = GB.k_of(rec, float(rec["at"]) + h * H + EDGE_S)
    if k is None:
        return None
    new = WV.guard_record(rec, k, why="смена")
    return float(new.get("pnl_net", new["pnl"]))


def make_table(log, now, cache=None):
    """F[позиция, h, поле], M[позиция, h] (нетто при закрытии в час h; NaN — уже вышла), final, at."""
    import run_short as S                                       # noqa: E402
    if cache is None:
        cache, why = S.read_cache(log=lambda *a: None)
        if why and not cache:
            return {"error": f"кэш коротких: {why}"}
    lo, hi = now - DAYS * 86400, now - (HMAX + 2) * H
    recs = sorted((r for (rk, _s, _a), r in cache.items()
                   if rk == RULER and r.get("state", "closed") == "closed" and r.get("marks")
                   and lo <= float(r["at"]) <= hi), key=lambda r: float(r["at"]))
    if len(recs) < 4 * MIN_N:
        return {"error": f"позиций с отметками {len(recs)} < {4 * MIN_N}"}
    legs = [{"sym": r["sym"], "at": float(r["at"]), "fav": r.get("fav_bp") or 0.0} for r in recs]
    log(f"позиций {len(recs)}; состояние на часах 1…{HMAX} после входа")
    feat = ES.feature_env(legs, days=DAYS)
    rows = [[feat(g, h) for h in range(1, HMAX + 1)] for g in legs]
    names = sorted({x for r in rows for d in r for x in d})
    n = len(recs)
    F = np.full((n, HMAX + 1, len(names)), np.nan)
    M = np.full((n, HMAX + 1), np.nan)
    final = np.full(n, np.nan)
    for i, (r, row) in enumerate(zip(recs, rows)):
        final[i] = float(r.get("pnl_net", r["pnl"]))
        for h, d in enumerate(row, start=1):
            for j, nm in enumerate(names):
                v = d.get(nm)
                if v is not None:
                    F[i, h, j] = v
            c = close_pnl(r, h)
            if c is not None:
                M[i, h] = c
    at = np.array([float(r["at"]) for r in recs])
    os.makedirs(os.path.dirname(TABLE), exist_ok=True)
    np.savez_compressed(TABLE, F=F, M=M, final=final, at=at, names=np.array(names))
    return {"names": names, "F": F, "M": M, "final": final, "at": at, "n": n}


def load_table(path=None):
    try:
        z = np.load(path or TABLE, allow_pickle=False)
    except OSError as e:
        return {"error": f"таблицы нет ({type(e).__name__}) — нужен полный прогон"}
    return {"names": [str(x) for x in z["names"]], "F": z["F"], "M": z["M"], "final": z["final"], "at": z["at"],
            "n": len(z["at"])}


def first_hour(F, names, rule, hmax=HMAX):
    """Первый час 1…H, где все условия выполнены; −1 — не наступил."""
    Hh = min(int(rule.get("H") or hmax), hmax)
    ok = np.ones(F.shape[:2], dtype=bool)
    for c in rule["when"]:
        x = F[:, :, names.index(c["field"])]
        with np.errstate(invalid="ignore"):
            ok &= (x <= c["value"]) if c["op"] == "<=" else (x >= c["value"])
    ok[:, 0] = False
    ok[:, Hh + 1:] = False
    any_ = ok.any(axis=1)
    return np.where(any_, ok.argmax(axis=1), -1)


def result_under(M, final, hs):
    """Результат на позицию при закрытии в час hs[i] (−1 или уже вышла — исход книги)."""
    out = final.copy()
    for i, h in enumerate(hs):
        if h > 0 and not np.isnan(M[i, h]):
            out[i] = M[i, h]
    return out


def score_rule(F, M, final, names, at, rule, rng):
    hs = first_hour(F, names, rule)
    hit = (hs > 0) & np.array([not np.isnan(M[i, h]) if h > 0 else False for i, h in enumerate(hs)])
    res = result_under(M, final, hs)
    n_all = len(final)
    gain = float(np.nansum(res - final) / n_all)
    row = {"rule": {"when": rule["when"], "H": int(rule.get("H") or HMAX)}, "matched": int(hit.sum()),
           "mean_close": round(float(res[hit].mean()), 5) if hit.any() else None,
           "mean_hold": round(float(final[hit].mean()), 5) if hit.any() else None,
           "gain": round(gain, 5), "p_random_hour": None, "halves": []}
    if hit.any():
        idx = np.where(hit)[0]
        ge = 0
        for _ in range(NULL_DRAWS):
            s = 0.0
            for i in idx:
                valid = np.where(~np.isnan(M[i, 1:]))[0] + 1
                if len(valid):
                    s += float(M[i, rng.choice(valid)] - final[i])
            ge += (s / n_all) >= gain
        row["p_random_hour"] = round(ge / NULL_DRAWS, 4)
    order = np.argsort(at)
    half = len(order) // 2
    for hv in (order[:half], order[half:]):
        hh = hit[hv]
        row["halves"].append({"matched": int(hh.sum()), "gain": round(float(np.nansum((res - final)[hv]) / max(1, len(hv))), 5)})
    return row


def close_by_state(F, M, final, names, at, min_n=MIN_N):
    """Описание: закрытие в первый час, когда поле в терциле — прирост к исходу, половины."""
    order = np.argsort(at)
    half = len(order) // 2
    halves = (set(order[:half].tolist()), set(order[half:].tolist()))
    out = []
    for j, nm in enumerate(names):
        x = F[:, 1:, j]
        cover = float(np.mean(~np.isnan(x)))
        if cover < MIN_COVER:
            continue
        v = x[~np.isnan(x)]
        if len(v) < 3 * min_n:
            continue
        cuts = np.quantile(v, [1 / 3, 2 / 3])
        for ti, (lo, hi) in enumerate(((-np.inf, cuts[0]), (cuts[0], cuts[1]), (cuts[1], np.inf))):
            rule = {"when": [{"field": nm, "op": ">=", "value": float(lo)}] if np.isinf(hi) else
                    [{"field": nm, "op": "<=", "value": float(hi)}] if np.isinf(lo) else
                    [{"field": nm, "op": ">=", "value": float(lo)}, {"field": nm, "op": "<=", "value": float(hi)}],
                    "H": HMAX}
            hs = first_hour(F, names, rule)
            res = result_under(M, final, hs)
            d = res - final
            hit = hs > 0
            if hit.sum() < min_n:
                continue
            g1 = [d[i] for i in range(len(d)) if i in halves[0]]
            g2 = [d[i] for i in range(len(d)) if i in halves[1]]
            row = {"field": nm, "tercile": ti, "range": [None if np.isinf(lo) else round(float(lo), 6),
                                                          None if np.isinf(hi) else round(float(hi), 6)],
                   "matched": int(hit.sum()), "gain": round(float(np.mean(d)), 5),
                   "gain_first": round(float(np.mean(g1)), 5) if g1 else None,
                   "gain_second": round(float(np.mean(g2)), 5) if g2 else None,
                   "median_hour": int(np.median(hs[hit])) if hit.any() else None}
            row["held"] = bool(g1 and g2 and np.mean(g1) > 0 and np.mean(g2) > 0)
            out.append(row)
    out.sort(key=lambda r: -r["gain"])
    return out


def run(log=print, now=None, table=None, seed=0):
    t0 = time.time()
    now = now or time.time()
    if table is None:
        table = make_table(log, now)
    if table.get("error"):
        return table
    names, F, M, final, at = table["names"], table["F"], table["M"], table["final"], table["at"]
    rules = []
    try:
        with open(ES.RULES_FILE, encoding="utf-8") as f:
            rules = list(json.load(f).get("close_rules") or [])
    except (OSError, ValueError):
        pass
    rng = np.random.default_rng(seed + 5)
    model = []
    for r in rules:
        if not all(c["field"] in names for c in r.get("when") or []):
            model.append({"rule": r, "why": "поле вне таблицы"})
            continue
        model.append(score_rule(F, M, final, names, at, r, rng))
    state = close_by_state(F, M, final, names, at)
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "positions": int(len(final)),
           "hmax": HMAX, "fields": names, "book_mean": round(float(np.nanmean(final)), 5),
           "exited_by_hour": [int(np.sum(np.isnan(M[:, h]))) for h in range(1, HMAX + 1)],
           "close_state": state, "close_model": model, "secs": round(time.time() - t0, 1)}
    log(f"закрытие по состоянию: позиций {len(final)}, полей {len(names)}, правил модели {len(model)}, "
        f"держат {sum(1 for x in state if x['held'])} из {len(state)}")
    return res


def rule_words(rule):
    return " и ".join(f"{c['field']} {c['op']} {float(c['value']):g}" for c in rule.get("when") or []) + \
        f", до {int(rule.get('H') or HMAX)} ч"


def report(r):
    if r.get("error"):
        return f"# Ранний выход по смене состояния\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    L = ["# Ранний выход по смене состояния (спека 19 §11.11)", "",
         f"Посчитано {r['computed_at']}; Depth · Short, позиций {r['positions']}, состояние на часах 1…{r['hmax']} после входа; "
         f"исход книги в среднем {pct(r['book_mean'])} на позицию. Закрытие — по рынку на отметке часа после решения, "
         f"нетто. Описание, не правило: лучший терциль на всём окне — не правило (R5).", "",
         "## Закрытие по состоянию (описание для модели)", "",
         "«Закрыть в первый час, когда поле в терциле»: прирост к исходу книги на позицию, половины, медианный час.", "",
         "| поле | терциль | диапазон | подходящих | прирост | 1-я | 2-я | час | держит |", "|---|--:|---|--:|--:|--:|--:|--:|---|"]
    for x in (r.get("close_state") or [])[:15]:
        rg = f"{'' if x['range'][0] is None else x['range'][0]}…{'' if x['range'][1] is None else x['range'][1]}"
        L.append(f"| `{x['field']}` | {x['tercile']} | {rg} | {x['matched']} | {pct(x['gain'])} | {pct(x['gain_first'])} | "
                 f"{pct(x['gain_second'])} | {x['median_hour']} | {'да' if x['held'] else 'нет'} |")
    L.append(f"| … | | | держат всего {sum(1 for x in r.get('close_state') or [] if x['held'])} из {len(r.get('close_state') or [])} | | | | | |")
    L += ["", "## Правила закрытия модели", "",
          "| правило | подходящих | закрыть: средний | держать: средний | прирост на позицию | случайный час не хуже | половины |",
          "|---|--:|--:|--:|--:|--:|---|"]
    for x in r.get("close_model") or []:
        if x.get("why"):
            L.append(f"| {rule_words(x['rule'])} | {x['why']} | | | | | |")
            continue
        hv = "; ".join(f"{h['matched']}: {pct(h['gain'])}" for h in x["halves"])
        L.append(f"| {rule_words(x['rule'])} | {x['matched']} | {pct(x['mean_close'])} | {pct(x['mean_hold'])} | {pct(x['gain'])} | "
                 f"{x['p_random_hour'] if x['p_random_hour'] is not None else '—'} | {hv} |")
    if not r.get("close_model"):
        L.append("| правил закрытия модели ещё нет | | | | | | |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-table", action="store_true", help="без пересчёта состояния: таблица прошлого прогона")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                      # noqa: E402
    log = AB.guarded(print, limit=2500)
    r = run(log=log, table=load_table() if a.from_table else None)
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "ранний выход по смене состояния"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
