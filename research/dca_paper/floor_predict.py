#!/usr/bin/env python3
"""Предсказуем ли пол коротких позиций (владелец 2026-10-18: «давай замер»).

Потолок выхода (`exit_ceiling.py`) и сетка простых выходов (`exit_grid.py`)
показали: деньги коротких книг лежат в позициях, которые доходят до пола
(15 % позиций, в среднем −53 п.п. маржи); фиксированный час, трейлинг и
фиксация их не ловят, а случайный выход иногда ловит. Вопрос: отличаются
ли такие позиции от остальных ДО пола — по тому, что видно при входе и в
первые часы жизни. Нет признаков — судья в моменте (модель ли, правило ли)
пол не предскажет, и вопрос об ИИ-выходе закрывается.

ОБЪЯВЛЕНО ДО ПРОГОНА (направление каждого признака — тоже; признаки не
добавляются после просмотра):

Позиции — закрытые шорты книг `safe_h` (Sigma) и `optimal_h` (Depth) как
они живут (возраст, охрана рынком). У `aggr_h` те же записи, что у
`optimal_h` (книга отличается гейтом кассы) — не дублируется. Метка —
выход «пол» или «ликвидация».

Признаки при входе (h = 0), «больше — подозрительнее»:
* `lev` — плечо позиции;
* `-fav` — обещание модели со знаком минус (слабее обещание — хуже);
* `beta` — β имени к волне рынка по 72 часам до входа;
* `pre24` — ход имени за 24 ч до входа (разогнанное имя продолжает расти);
* `wave_pre24` — ход рынка за 24 ч до входа.
Признаки в час h ∈ {1, 2, 4, 8} у позиций, живых к концу часа h:
* `-cum` — pnl позиции к концу часа h со знаком минус;
* `-min` — худший pnl до часа h со знаком минус;
* `wave` — ход рынка с входа до конца часа h (против шорта — плюс);
* `excess` — ход имени сверх рынка с входа (своё движение против шорта).

Мера — AUC в объявленном направлении (0.5 — не различает; выше — признак
указывает на пол; ниже — указывает наоборот). Нуль — перестановка меток
среди тех же позиций, `--perms` раз: полоса 2.5…97.5 %.

Деньги — правило «в час h закрыть 10 % самых подозрительных из живых» в
долях маржи (pnl на час h против исхода позиции) против случайных 10 %
живых в тот же час, `--seeds` зёрен; плюс доля пола среди закрытых
против доли пола среди живых.

КРИТЕРИЙ (объявлен до прогона): признак-кандидат — AUC вне полосы нуля
В ОБЕИХ половинах записи с одним знаком И «закрыть 10 %» лучше случайных
10 % в ≥ 95 % зёрен в ОБЕИХ половинах. Только позиции, без кассы: вопрос
— различимость; деньги кассы — следующий шаг, если кандидат есть.

Ничего не меняет: книги, журналы и кэши не пишутся.

    run research/dca_paper/floor_predict.py --perms=500 --seeds=500
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
import wave as WV                                             # noqa: E402
import arm_book as AB                                         # noqa: E402
import exit_ceiling as EC                                     # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-floor-predict.md")
OUT_JSON = os.path.join(R.OUT, "DCA-floor-predict.json")
HOUR = 3600.0
BOOKS = ("safe_h", "optimal_h")
HOURS = (1, 2, 4, 8)
BAD = ("пол", "ликвидация")
CUT_SHARE = 0.10
MEM_LIMIT_MB = 3000
ENTRY_FEATS = ("lev", "-fav", "beta", "pre24", "wave_pre24")
PATH_FEATS = ("-cum", "-min", "wave", "excess")
FEAT_TITLE = {"lev": "плечо", "-fav": "обещание модели (слабее — хуже)",
              "beta": "β к рынку за 72 ч до входа", "pre24": "ход имени за 24 ч до входа",
              "wave_pre24": "ход рынка за 24 ч до входа", "-cum": "pnl к часу h (ниже — хуже)",
              "-min": "худший pnl до часа h (ниже — хуже)", "wave": "ход рынка с входа",
              "excess": "ход имени сверх рынка с входа"}


def auc(scores, labels):
    """P(score у пола > score у остальных), ничьи — пополам. Ранговая формула."""
    pairs = sorted(zip(scores, labels), key=lambda x: x[0])
    n1 = sum(1 for _s, y in pairs if y)
    n0 = len(pairs) - n1
    if not n1 or not n0:
        return None
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        rank_sum += r * sum(1 for k in range(i, j + 1) if pairs[k][1])
        i = j + 1
    return (rank_sum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def null_band(scores, labels, perms, rng):
    lab = list(labels)
    xs = []
    for _ in range(perms):
        rng.shuffle(lab)
        a = auc(scores, lab)
        if a is not None:
            xs.append(a)
    xs.sort()
    if not xs:
        return None, None
    return xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))]


def features(recs, mkt, log, book):
    """Таблица позиций: метка, исход, путь и признаки. Без пути — мимо."""
    rows = []
    t0 = time.time()
    for i, r in enumerate(recs):
        p = WV.path_of(r)
        if not p or (r.get("state") or "closed") != "closed":
            continue
        at = float(r["at"])
        t_in = at - 1.0
        sym = r.get("sym")
        b, _rho, _n = mkt.beta_pre(sym, at)
        pre = mkt.move(sym, t_in - 24 * HOUR, t_in)
        wpre = mkt.wave(t_in - 24 * HOUR, t_in)
        fav = r.get("fav_bp")
        row = {"bad": (r.get("exit") in BAD), "final": p["final"], "K": p["K"],
               "exit": r.get("exit"), "at": at,
               "f": {"lev": float(r.get("lev") or 0) or None,
                     "-fav": (-float(fav) if fav is not None else None),
                     "beta": b, "pre24": pre, "wave_pre24": wpre},
               "h": {}}
        for h in HOURS:
            if h > p["K"] - 1:
                continue                                       # к концу часа h позиции уже нет
            cum = [p["cum"][k] for k in range(1, h + 1)]
            w = mkt.wave(t_in, t_in + h * HOUR)
            m = mkt.move(sym, t_in, t_in + h * HOUR)
            row["h"][h] = {"cum": cum[-1],
                           "f": {"-cum": -cum[-1], "-min": -min(cum), "wave": w,
                                 "excess": (m - w) if (m is not None and w is not None) else None}}
        rows.append(row)
        if (i + 1) % 1000 == 0:
            log(f"  {book}: признаки {i + 1}/{len(recs)} ({time.time() - t0:.0f} с)")
    return rows


def judge(rows, perms, seeds, rng):
    """AUC с полосой нуля и правило «закрыть 10 %» против случайных 10 %."""
    out = {"n": len(rows), "bad": sum(1 for r in rows if r["bad"]), "feat": {}}
    plans = [(0, f) for f in ENTRY_FEATS] + [(h, f) for h in HOURS for f in PATH_FEATS]
    for h, f in plans:
        if h == 0:
            pool = [(r["f"][f], r["bad"]) for r in rows if r["f"].get(f) is not None]
        else:
            pool = [(r["h"][h]["f"][f], r["bad"]) for r in rows
                    if h in r["h"] and r["h"][h]["f"].get(f) is not None]
        key = f"{h}:{f}"
        if len(pool) < 50 or not any(y for _s, y in pool) or all(y for _s, y in pool):
            out["feat"][key] = {"n": len(pool), "why": "мало позиций или одна метка"}
            continue
        sc, lb = [s for s, _y in pool], [y for _s, y in pool]
        a = auc(sc, lb)
        lo, hi = null_band(sc, lb, perms, rng)
        cell = {"n": len(pool), "bad": sum(lb), "auc": a, "null_lo": lo, "null_hi": hi,
                "outside": (a is not None and lo is not None and (a < lo or a > hi))}
        if h > 0:
            alive = [r for r in rows if h in r["h"] and r["h"][h]["f"].get(f) is not None]
            alive.sort(key=lambda r: -r["h"][h]["f"][f])
            n_cut = max(1, int(round(CUT_SHARE * len(alive))))
            cut = alive[:n_cut]
            d_rule = sum(r["h"][h]["cum"] - r["final"] for r in cut)
            ds = []
            for _ in range(seeds):
                pick = rng.sample(alive, n_cut)
                ds.append(sum(r["h"][h]["cum"] - r["final"] for r in pick))
            cell.update({"alive": len(alive), "cut": n_cut,
                         "delta_mean": d_rule / n_cut,
                         "rand_delta_mean": (sum(ds) / len(ds)) / n_cut,
                         "rand_not_worse": sum(1 for x in ds if x >= d_rule) / len(ds),
                         "bad_in_cut": sum(1 for r in cut if r["bad"]) / n_cut,
                         "bad_in_alive": sum(1 for r in alive if r["bad"]) / len(alive)})
        out["feat"][key] = cell
    return out


def run(perms, seeds, log):
    t0 = time.time()
    data, why = EC.load(log)
    if why:
        return {"error": why}
    mkt = WV.Market(WV.Hours())
    res = {"perms": perms, "seeds": seeds, "books": {}, "hours": list(HOURS),
           "cut_share": CUT_SHARE}
    for book in BOOKS:
        recs = data["books"].get(book) or []
        rows = features(recs, mkt, log, book)
        ats = sorted(r["at"] for r in rows)
        mid = ats[len(ats) // 2] if ats else 0
        wins = {"all": rows, "half1": [r for r in rows if r["at"] < mid],
                "half2": [r for r in rows if r["at"] >= mid]}
        bres = {"mid": mid, "windows": {}}
        for wname, part in wins.items():
            bres["windows"][wname] = judge(part, perms, seeds, random.Random(hash((book, wname)) & 0xffff))
            log(f"{book}, окно {wname}: {len(part)} позиций, посчитано ({time.time() - t0:.0f} с)")
        # критерий
        cand = []
        h1, h2 = bres["windows"]["half1"]["feat"], bres["windows"]["half2"]["feat"]
        for key in h1:
            a, b = h1.get(key) or {}, h2.get(key) or {}
            if not (a.get("outside") and b.get("outside")):
                continue
            if (a["auc"] - 0.5) * (b["auc"] - 0.5) <= 0:
                continue
            econ = ("rand_not_worse" not in a) or (a["rand_not_worse"] <= 0.05 and b["rand_not_worse"] <= 0.05)
            if key.startswith("0:"):
                econ = None                                     # у признака входа «закрыть» нет
            cand.append({"key": key, "auc_h1": a["auc"], "auc_h2": b["auc"], "econ": econ})
        bres["candidates"] = cand
        res["books"][book] = bres
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


def _a(x):
    return "—" if x is None else f"{x:.3f}"


def _pts(x):
    return EC._pts(x)


def report(res):
    if res.get("error"):
        return f"# Предсказуем ли пол коротких позиций\n\nНе посчитано: {res['error']}.\n"
    L = ["# Предсказуем ли пол коротких позиций", "",
         "Позиции — закрытые шорты как живут; метка — выход «пол» или «ликвидация». Признаки, их "
         "направление («больше — подозрительнее»), нуль и критерий объявлены ДО прогона (`floor_predict.py`). "
         f"AUC: 0.5 — не различает; полоса нуля — {res['perms']} перестановок меток, 2.5…97.5 %. "
         f"«Закрыть 10 %» — в час h закрыть 10 % самых подозрительных из живых; против случайных 10 % живых, "
         f"{res['seeds']} зёрен. Δ — pnl на час h минус исход позиции, доли маржи (+ — закрытие помогло).", "",
         "**Критерий кандидата:** AUC вне полосы нуля в ОБЕИХ половинах с одним знаком И «закрыть 10 %» лучше "
         "случайных в ≥ 95 % зёрен в обеих половинах.", ""]
    for book, b in res["books"].items():
        L += [f"## {R.title_en(book)} · Short (`{book}`)", ""]
        cand = b.get("candidates") or []
        full = [c for c in cand if c["econ"]]
        L += ["**Кандидаты по критерию:** " + (", ".join(
            f"`{c['key']}` (AUC {_a(c['auc_h1'])} / {_a(c['auc_h2'])})" for c in full) if full else "нет") + ".",
              "Различают пол в обеих половинах, но без денег (или признак входа): " + (", ".join(
                  f"`{c['key']}` ({_a(c['auc_h1'])} / {_a(c['auc_h2'])})" for c in cand if not c["econ"]) or "нет") + ".", ""]
        for wname, wt in (("all", "Вся запись"), ("half1", "Первая половина"), ("half2", "Вторая половина")):
            w = b["windows"][wname]
            L += [f"### {wt}: позиций {w['n']}, у пола {w['bad']} ({100.0 * w['bad'] / max(1, w['n']):.1f} %)", "",
                  "| час | признак | позиций | AUC | полоса нуля | вне полосы | закрыто | пол среди закрытых / живых | "
                  "Δ закрытых | Δ случайных | случайные не хуже |",
                  "|--:|---|--:|--:|---|---|--:|---|--:|--:|--:|"]
            for key, c in w["feat"].items():
                h, f = key.split(":", 1)
                if c.get("why"):
                    L.append(f"| {h} | {FEAT_TITLE[f]} | {c['n']} | — | {c['why']} | | | | | | |")
                    continue
                econ = ("| %d | %.0f %% / %.0f %% | %s | %s | %d %% |" % (
                    c["cut"], 100 * c["bad_in_cut"], 100 * c["bad_in_alive"], _pts(c["delta_mean"]),
                    _pts(c["rand_delta_mean"]), round(100 * c["rand_not_worse"]))
                    if "cut" in c else "| — | — | — | — | — |")
                L.append(f"| {h} | {FEAT_TITLE[f]} | {c['n']} | {_a(c['auc'])} | {_a(c['null_lo'])}…{_a(c['null_hi'])} | "
                         f"{'да' if c['outside'] else 'нет'} " + econ)
            L.append("")
    L += ["## Чего замер НЕ говорит", "",
          "- Только позиции, без кассы: «закрыть 10 %» меряется исходом позиций, а касса заполнила бы освободившиеся "
          "слоты (урок 07.10) — деньги кассы считаются следующим шагом, если кандидат есть.",
          "- Признаки — объявленный короткий список; «признаков нет» значит «нет среди этих», а не «нет вообще». "
          "Модель в моменте видела бы то же самое, что здесь: путь позиции, рынок, имя.",
          "- Час решения — закрытие часа по отметке ядра; внутричасовой ход не виден.",
          "- Выход по полу — исход ПРАВИЛА книги (пол 0.10 у Sigma, 0.50 у Depth); при другом поле метка другая.", "",
          f"Прогон {res.get('secs')} с, {res.get('computed_at')} UTC."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--perms", type=int, default=500)
    ap.add_argument("--seeds", type=int, default=500)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = AB.guarded(print, limit=MEM_LIMIT_MB)
    res = run(a.perms, a.seeds, log)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print(txt[:5000])
    if not a.no_publish and not res.get("error"):
        subprocess.run(["tools/publish.sh", "замер: предсказуем ли пол коротких позиций"], cwd=ROOT, check=False)
    return 0 if not res.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
