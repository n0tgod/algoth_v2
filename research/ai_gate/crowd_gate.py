#!/usr/bin/env python3
"""Толпа как гейт короткого входа (владелец 25.10, пункт 2) — замер с нулём.

Разрез 25.10 (`REGIME-split.md`) показал: когда толпа Bybit уже в шорте
(доля длинных `crowd_bybit` в нижней трети, ≤ 0.474 по терцилям окна
25.09–20.10), у короткого входа глубокий минус 23 % против 13 % и вперёд
−2 % против +5 %. Порог объявлен ДО этого счёта тем значением терциля.

Правило A «гейт»: сигнал с `crowd_bybit` ≤ порога не берётся. Правило B
«половина билета»: берётся половиной. Поле не измерено — вход как у книги
(и это считается отдельно). Мера — средний нетто на сигнал (доля маржи,
невзятый — 0) при входе в час сигнала с выходом книги; нуль — столько же
СЛУЧАЙНЫХ сигналов снято/ополовинено (400 жребиев): p = доля жребиев не
хуже правила. Окна: всё, половины по времени сигнала, вперёд с 16.10,
неделя пампов с 20.10. Соседние пороги 0.45 и 0.50 печатаются как
описание — выбирать по ним нельзя.

Источник — таблица поиска ТВХ (`entry_search.make_table`), Depth · Short.
Отчёт `out/CROWD-gate.md`, `out/crowd_gate.json`.
"""
import argparse
import calendar
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import entry_search as ES                                       # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "CROWD-gate.md")
LATEST = os.path.join(OUT, "crowd_gate.json")
FIELD = "crowd_bybit"
THRESH = 0.474                   # нижний терциль окна 25.09–20.10 — объявлен до счёта
NEIGHBOURS = (0.45, 0.50)        # описание, не отбор
DRAWS = 400
DEEP = -0.30
FORWARD = "2026-10-16"
PUMP_WEEK = "2026-10-20"


def pct(v):
    return "—" if v is None else f"{100 * v:+.2f} %"


def rule_scores(o, x, thresh, rng, draws=DRAWS):
    """→ гейт и половина билета на подмножестве: средний на сигнал, снято, нуль."""
    ok = ~np.isnan(o)
    o = np.where(ok, o, 0.0)
    n = int(ok.sum())
    if n == 0:
        return None
    hit = ok & ~np.isnan(x) & (x <= thresh)
    unmeasured = int((ok & np.isnan(x)).sum())
    book = float(o.sum() / n)
    out = {"n": n, "book_mean": round(book, 5), "unmeasured": unmeasured, "hit": int(hit.sum()),
           "hit_mean": round(float(o[hit].mean()), 5) if hit.any() else None,
           "hit_deep": round(float((o[hit] <= DEEP).mean()), 3) if hit.any() else None,
           "kept_deep": round(float((o[ok & ~hit] <= DEEP).mean()), 3) if (ok & ~hit).any() else None}
    for name, w in (("gate", 0.0), ("half", 0.5)):
        rule = float((np.where(hit, w * o, o)).sum() / n)
        idx = np.where(ok)[0]
        k = int(hit.sum())
        ge = 0
        for _ in range(draws):
            pick = rng.choice(idx, size=k, replace=False) if k else np.array([], dtype=int)
            m = np.ones(len(o), dtype=bool)
            m[pick] = False
            ge += float(np.where(m, o, w * o).sum() / n) >= rule
        out[name] = {"mean": round(rule, 5), "gain": round(rule - book, 5), "p_random": round(ge / draws, 4) if k else None}
    return out


def run(log=print, now=None):
    now = now or time.time()
    T = ES.load_table()
    if T.get("error"):
        return {"error": T["error"]}
    names, F, O, at = T["names"], T["F"], ES.as3(T["O"]), np.asarray(T["at"], dtype=float)
    if FIELD not in names:
        return {"error": f"поля {FIELD} нет в таблице"}
    if ES.BOOK_EXIT not in T["exits"]:
        return {"error": f"в таблице нет ячейки книги {ES.BOOK_EXIT}"}
    o = O[:, 0, T["exits"].index(ES.BOOK_EXIT)]
    x = F[:, 0, names.index(FIELD)]
    order = np.argsort(at)
    half = len(order) // 2
    fwd = calendar.timegm(time.strptime(FORWARD, "%Y-%m-%d"))
    pw = calendar.timegm(time.strptime(PUMP_WEEK, "%Y-%m-%d"))
    scopes = {"all": order, "first": order[:half], "second": order[half:],
              "forward": np.where(at >= fwd)[0], "pump_week": np.where(at >= pw)[0]}
    rng = np.random.default_rng(3)
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "signals": int(len(at)),
           "window": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(at.min())), time.strftime("%Y-%m-%d %H:%M", time.gmtime(at.max()))],
           "mid": time.strftime("%Y-%m-%d", time.gmtime(at[order[half]])), "field": FIELD, "thresh": THRESH,
           "draws": DRAWS, "deep": DEEP, "forward": FORWARD, "pump_week": PUMP_WEEK, "scopes": {}, "neighbours": {}}
    for sc, idx in scopes.items():
        res["scopes"][sc] = rule_scores(o[idx], x[idx], THRESH, rng)
    for th in NEIGHBOURS:
        res["neighbours"][str(th)] = {sc: rule_scores(o[idx], x[idx], th, rng, draws=100) for sc, idx in scopes.items()}
    a = res["scopes"]["all"]
    log(f"сигналов {len(at)}; порог {THRESH}: снято {a['hit']} из {a['n']}; книга {pct(a['book_mean'])}, "
        f"гейт {pct(a['gate']['mean'])} (p {a['gate']['p_random']}), половина {pct(a['half']['mean'])} (p {a['half']['p_random']})")
    return res


def report(r):
    if r.get("error"):
        return f"# Толпа как гейт\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    sc_names = (("all", "всё"), ("first", "1-я половина"), ("second", "2-я половина"), ("forward", "вперёд"), ("pump_week", "неделя пампов"))
    L = ["# Толпа как гейт короткого входа: замер с нулём", "",
         f"Посчитано {r['computed_at']}; таблица ТВХ Depth · Short, сигналов {r['signals']}, окно {r['window'][0]} … {r['window'][1]} UTC, "
         f"середина {r['mid']}, вперёд с {r['forward']}, неделя пампов с {r['pump_week']}. Поле `{r['field']}` (доля длинных в толпе Bybit) "
         f"в час сигнала; порог ≤ {r['thresh']} объявлен до счёта (нижний терциль окна 25.09–20.10). Мера — средний нетто на сигнал "
         f"в доле маржи (невзятый — 0), вход в час сигнала с выходом книги; «глубокий минус» — доля исходов ≤ {100 * r['deep']:.0f} % маржи. "
         f"Нуль — столько же случайных сигналов снято или ополовинено, {r['draws']} жребиев: p = доля жребиев не хуже правила. "
         "Описание, не отбор: решение о правиле — за владельцем.", "",
         "| окно | сигналов | не изм. | снято | книга | снятые: средний / глубокий | оставленные: глубокий | гейт | прирост | p | половина билета | прирост | p |",
         "|---|--:|--:|--:|--:|---|--:|--:|--:|--:|--:|--:|--:|"]
    for sc, nm in sc_names:
        a = r["scopes"].get(sc)
        if not a:
            L.append(f"| {nm} | 0 | | | | | | | | | | | |")
            continue
        L.append(f"| {nm} | {a['n']} | {a['unmeasured']} | {a['hit']} | {pct(a['book_mean'])} | {pct(a['hit_mean'])} / "
                 f"{'—' if a['hit_deep'] is None else a['hit_deep']} | {'—' if a['kept_deep'] is None else a['kept_deep']} | "
                 f"{pct(a['gate']['mean'])} | {pct(a['gate']['gain'])} | {a['gate']['p_random']} | "
                 f"{pct(a['half']['mean'])} | {pct(a['half']['gain'])} | {a['half']['p_random']} |")
    L += ["", "## Соседние пороги (описание, 100 жребиев)", "", "| порог | окно | снято | гейт прирост | p | половина прирост | p |", "|---|---|--:|--:|--:|--:|--:|"]
    for th, by in r["neighbours"].items():
        for sc, nm in sc_names:
            a = by.get(sc)
            if a:
                L.append(f"| {th} | {nm} | {a['hit']} | {pct(a['gate']['gain'])} | {a['gate']['p_random']} | {pct(a['half']['gain'])} | {a['half']['p_random']} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    r = run()
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "толпа как гейт короткого входа"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
