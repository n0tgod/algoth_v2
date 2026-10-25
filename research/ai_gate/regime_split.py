#!/usr/bin/env python3
"""Разрез исходов короткого входа по состоянию имени и рынка (вопрос владельца
25.10: как ловить трендовые падения и мало терять на неделях пампов).

Источник — таблица поиска ТВХ (`entry_search.make_table`): для каждого сигнала
Depth · Short параметры состояния на час k после сигнала (F) и нетто-исход
входа в этот час с выходом книги (O, доля маржи на сигнал). Правил не ищем —
описание: как исход делится по терцилям каждого поля в час сигнала, и
«подтверждение»: вход через k часов, когда имя уже упало с сигнала (≤ −2 %),
стоит около него (±2 %) или ушло выше (≥ +2 %). Нуль — перестановка поля между
сигналами (200 раз): доля перестановок с разбегом бакетов не меньше факта.
Половины по времени сигнала; «вперёд» — с 16.10. Пороги объявлены до счёта.

Отчёт `out/REGIME-split.md`, `out/regime_split.json`.
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
REPORT = os.path.join(OUT, "REGIME-split.md")
LATEST = os.path.join(OUT, "regime_split.json")
FIELDS = ["px_4h", "px_24h", "px_168h", "btc_24h", "mcap_24h", "crowd_bybit", "crowd_bybit_shift", "funding",
          "oi_24h", "oi_1h", "trades_ratio", "burst_ratio", "fng", "btc_dom", "basis_bp", "signal_fav_bp"]
CONFIRM = [("упало ≤ −2 %", -np.inf, -0.02), ("±2 %", -0.02, 0.02), ("выросло ≥ +2 %", 0.02, np.inf)]
DEEP = -0.30                     # «глубокий минус» на сигнал — доля маржи; у Depth пол ≈ половина маржи
DRAWS = 200
FORWARD = "2026-10-16"


def pct(v):
    return "—" if v is None else f"{100 * v:+.2f} %"


def cell(o):
    o = o[~np.isnan(o)]
    if len(o) == 0:
        return {"n": 0, "mean": None, "deep": None}
    return {"n": int(len(o)), "mean": round(float(o.mean()), 5), "deep": round(float((o <= DEEP).mean()), 3)}


def terciles(x):
    v = x[~np.isnan(x)]
    if len(v) < 30:
        return None
    return float(np.quantile(v, 1 / 3)), float(np.quantile(v, 2 / 3))


def bucket_ids(x, cuts):
    """0/1/2 — терцили, 3 — не измерено."""
    b = np.full(len(x), 3, dtype=int)
    ok = ~np.isnan(x)
    b[ok & (x <= cuts[0])] = 0
    b[ok & (x > cuts[0]) & (x <= cuts[1])] = 1
    b[ok & (x > cuts[1])] = 2
    return b


def spread(o, b, nb=3):
    means = [o[(b == i) & ~np.isnan(o)].mean() if ((b == i) & ~np.isnan(o)).sum() >= 10 else np.nan for i in range(nb)]
    means = [m for m in means if not np.isnan(m)]
    return (max(means) - min(means)) if len(means) >= 2 else np.nan


def null_p(o, b, rng, nb=3):
    obs = spread(o, b, nb)
    if np.isnan(obs):
        return None
    ge = 0
    for _ in range(DRAWS):
        ge += spread(o, rng.permutation(b), nb) >= obs
    return round(ge / DRAWS, 3)


def by_field(F, names, Ob, at, scopes, rng):
    out = {}
    for f in FIELDS:
        if f not in names:
            continue
        x = F[:, 0, names.index(f)]
        cuts = terciles(x)
        if not cuts:
            out[f] = {"why": "меньше 30 измерений"}
            continue
        b = bucket_ids(x, cuts)
        o = Ob[:, 0]
        row = {"cuts": [round(c, 5) for c in cuts], "scopes": {}}
        for sc, idx in scopes.items():
            row["scopes"][sc] = {"buckets": [cell(o[idx][b[idx] == i]) for i in range(4)],
                                 "p_perm": null_p(o[idx], b[idx], rng)}
        # держит: порядок терцилей по среднему одинаков в обеих половинах
        m = [[c["mean"] for c in row["scopes"][h]["buckets"][:3]] for h in ("first", "second")]
        holds = all(v is not None for v in m[0] + m[1]) and (np.argsort(m[0]).tolist() == np.argsort(m[1]).tolist())
        row["holds"] = bool(holds)
        out[f] = row
    return out


def confirmation(F, names, Ob, scopes, rng):
    if "since_signal" not in names:
        return {"why": "поля since_signal нет"}
    j = names.index("since_signal")
    out = {}
    for k in range(1, Ob.shape[1]):
        x = F[:, k, j]
        b = np.full(len(x), 3, dtype=int)
        for i, (_nm, lo, hi) in enumerate(CONFIRM):
            b[~np.isnan(x) & (x > lo) & (x <= hi)] = i
        row = {}
        for sc, idx in scopes.items():
            cells = []
            for i in range(4):
                m = idx[b[idx] == i]
                c = cell(Ob[m, k])
                c["book_same"] = cell(Ob[m, 0])["mean"]       # вход книги в час сигнала у ТЕХ ЖЕ сигналов
                cells.append(c)
            row[sc] = {"buckets": cells, "p_perm": null_p(Ob[idx, k], b[idx], rng)}
        out[f"k{k}"] = row
    return out


def run(log=print, now=None):
    now = now or time.time()
    T = ES.load_table()
    if T.get("error"):
        return {"error": T["error"]}
    names, F, O, at = T["names"], T["F"], ES.as3(T["O"]), np.asarray(T["at"], dtype=float)
    if ES.BOOK_EXIT not in T["exits"]:
        return {"error": f"в таблице нет ячейки книги {ES.BOOK_EXIT}"}
    Ob = O[:, :, T["exits"].index(ES.BOOK_EXIT)]
    order = np.argsort(at)
    half = len(order) // 2
    fwd = calendar.timegm(time.strptime(FORWARD, "%Y-%m-%d"))
    scopes = {"all": order, "first": order[:half], "second": order[half:], "forward": np.where(at >= fwd)[0]}
    rng = np.random.default_rng(7)
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "signals": int(len(at)),
           "window": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(at.min())), time.strftime("%Y-%m-%d %H:%M", time.gmtime(at.max()))],
           "mid": time.strftime("%Y-%m-%d", time.gmtime(at[order[half]])), "forward": FORWARD, "deep": DEEP, "draws": DRAWS,
           "book": {sc: cell(Ob[idx, 0]) for sc, idx in scopes.items()},
           "fields": by_field(F, names, Ob, at, scopes, rng), "confirmation": confirmation(F, names, Ob, scopes, rng)}
    log(f"сигналов {len(at)}, окно {res['window']}, книга на сигнал {pct(res['book']['all']['mean'])}")
    return res


def report(r):
    if r.get("error"):
        return f"# Разрез коротких по состоянию\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    sc_names = (("all", "всё"), ("first", "1-я"), ("second", "2-я"), ("forward", "вперёд"))
    L = ["# Разрез исходов короткого входа по состоянию имени и рынка", "",
         f"Посчитано {r['computed_at']}; таблица поиска ТВХ: Depth · Short, сигналов {r['signals']}, окно {r['window'][0]} … "
         f"{r['window'][1]} UTC, середина {r['mid']}, вперёд с {r['forward']}. Число — средний нетто на сигнал в доле маржи "
         f"при входе в час сигнала с выходом книги; «глубокий минус» — доля исходов ≤ {100 * r['deep']:.0f} % маржи. "
         f"Терцили поля считаны по всем сигналам; «не изм.» — поле не измерено (отдельный бакет). Нуль — перестановка поля между "
         f"сигналами {r['draws']} раз: p = доля перестановок с разбегом средних не меньше факта. «Держит» — порядок терцилей "
         "одинаков в обеих половинах. Описание, не правило.", "",
         "Книга (вход в час сигнала): " + "; ".join(f"{nm} {pct(r['book'][sc]['mean'])} (n {r['book'][sc]['n']}, глубокий минус "
                                                   f"{r['book'][sc]['deep']})" for sc, nm in sc_names), "",
         "## Поля в час сигнала: терцили", "",
         "| поле | границы | окно | нижняя треть | средняя | верхняя | не изм. | p перест. | держит |", "|---|---|---|---|---|---|---|--:|---|"]
    for f, row in r["fields"].items():
        if row.get("why"):
            L.append(f"| `{f}` | — | | {row['why']} | | | | | |")
            continue
        for sc, nm in sc_names:
            s = row["scopes"][sc]
            cells = " | ".join(f"{pct(c['mean'])} (n {c['n']}, гл. {c['deep'] if c['deep'] is not None else '—'})" for c in s["buckets"])
            L.append(f"| `{f}` | {row['cuts'][0]:.4g} / {row['cuts'][1]:.4g} | {nm} | {cells} | "
                     f"{s['p_perm'] if s['p_perm'] is not None else '—'} | {'да' if row['holds'] else 'нет'} |")
    L += ["", "## Подтверждение: вход через k часов по ходу имени с сигнала", "",
          "Каждая клетка: средний исход входа в час k в этой группе / средний исход ВХОДА КНИГИ (час сигнала) у тех же сигналов.", "",
          "| k | окно | " + " | ".join(n for n, _l, _h in CONFIRM) + " | не изм. | p перест. |", "|---|---|---|---|---|---|--:|"]
    conf = r["confirmation"]
    if conf.get("why"):
        L.append(f"| — | | {conf['why']} | | | | |")
    else:
        for k, row in conf.items():
            for sc, nm in sc_names:
                s = row[sc]
                cells = " | ".join(f"{pct(c['mean'])} / {pct(c['book_same'])} (n {c['n']})" for c in s["buckets"])
                L.append(f"| {k} | {nm} | {cells} | {s['p_perm'] if s['p_perm'] is not None else '—'} |")
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
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "разрез коротких по состоянию имени и рынка"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
