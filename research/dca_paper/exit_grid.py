#!/usr/bin/env python3
"""Сетка детерминированных выходов для КОРОТКИХ книг (владелец 2026-10-18:
«давай замерим сетку» — после потолка выхода, `exit_ceiling.py`).

Потолок показал: у коротких книг правило выхода (срок 24 ч, цель ×2, пол
0.5, охрана рынком 4 %) бьётся даже СЛУЧАЙНЫМ ранним выходом в 100 %
зёрен. Прежде чем звать судью-модель, меряется, что дают простые
объявленные правила выхода. Входы и размер — как у книги; меняется только
выход, и только РАНЬШЕ правила (забор: срок не продлевается, пол и стоп
не расширяются).

ОБЪЯВЛЕНО ДО ПРОГОНА (право на итерацию одно; ячейки не добавляются):

Решение — по закрытию часа, по отметке ядра (`marks`), будущее не видно:
выход в час k решается только по пути до k включительно.
* `T6`, `T12`, `T18` — ранний срок: закрыть по закрытию часа T;
* `TS4`, `TS8` — стоп по времени: в час N закрыть, если позиция в минусе;
* `TR05`, `TR10`, `TR20` — трейлинг от пика: как только пик pnl ≥ g доли
  маржи, закрыть, когда pnl упал от пика на g (g = 0.05 / 0.10 / 0.20);
* `LK10`, `LK25` — фиксация: закрыть, когда pnl ≥ X доли маржи (по
  закрытию часа, не лимиткой; X = 0.10 / 0.25).

Контроли: правило книги (как живёт); слепой выход — случайный час внутри
забора (`--seeds` зёрен); потолок — лучший час при знании будущего.

ПРАВИЛО ОТБОРА (объявлено до прогона, урок R5): победитель — ячейка с
наибольшим средним итогом кассы $10k по трём коротким книгам на ПЕРВОЙ
половине записи; судится он на ВТОРОЙ половине — против правила книги и
против слепого выхода (доля зёрен, где слепой не хуже). Ячейка, выигравшая
на всём окне, но не прошедшая этот суд, кандидатом не считается.

Деньги — касса тем же ядром (`run_paper.build_rows`), $1k и $10k, сложный
процент, БРУТТО (ранний выход рыночный: проскальзывание выхода и лишний
круг комиссии не вычтены — сказано в отчёте). Книги — три короткие h24 и
короткая сторона трёх общих счетов (базовые, без ветвей).

Ничего не меняет: книги, журналы и кэши не пишутся.

    run research/dca_paper/exit_grid.py --seeds=20
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
import long_guard as LG                                       # noqa: E402
import exit_ceiling as EC                                     # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-exit-grid.md")
OUT_JSON = os.path.join(R.OUT, "DCA-exit-grid.json")
DEPS = LG.DEPS
SINCE = LG.SINCE
MEM_LIMIT_MB = 3000
WHY = "выход сетки"

# Сетка — объявлена до прогона; порядок — порядок отчёта.
GRID = (
    ("T6", "срок 6 ч", ("term", 6)),
    ("T12", "срок 12 ч", ("term", 12)),
    ("T18", "срок 18 ч", ("term", 18)),
    ("TS4", "стоп по времени: в минусе к 4 ч", ("tstop", 4)),
    ("TS8", "стоп по времени: в минусе к 8 ч", ("tstop", 8)),
    ("TR05", "трейлинг от пика 5 п.п.", ("trail", 0.05)),
    ("TR10", "трейлинг от пика 10 п.п.", ("trail", 0.10)),
    ("TR20", "трейлинг от пика 20 п.п.", ("trail", 0.20)),
    ("LK10", "фиксация при +10 п.п.", ("lock", 0.10)),
    ("LK25", "фиксация при +25 п.п.", ("lock", 0.25)),
)


def exit_hour(p, last, spec):
    """Первый час k ≤ last, в который правило сетки закрывает позицию, —
    только по пути ДО k включительно. Нет такого часа — None (выход книги)."""
    kind, x = spec
    peak = float("-inf")
    for k in range(1, last + 1):
        c = p["cum"][k]
        peak = max(peak, c)
        if kind == "term" and k == int(x):
            return k
        if kind == "tstop" and k == int(x) and c < 0:
            return k
        if kind == "trail" and peak >= x and c <= peak - x:
            return k
        if kind == "lock" and c >= x:
            return k
    return None


def grid_recs(recs, book, spec):
    """Записи под правилом сетки и пары (было, стало, k, K) по позициям с забором."""
    out, hits = [], []
    for r in recs:
        p, last = EC.fence(r, book)
        if p is None or last < 1:
            out.append(r)
            continue
        k = exit_hour(p, last, spec)
        new = r if k is None else WV.guard_record(r, k, why=WHY)
        out.append(new)
        hits.append((r, new, k or p["K"], p["K"]))
    return out, hits


def run(seeds, log):
    t0 = time.time()
    R.DEPOSITS[:] = list(DEPS)
    R.SIZINGS = (R.SIZING_COMPOUND,)
    data, why = EC.load(log)
    if why:
        return {"error": why}
    now = data["now"]
    shorts = {k: v for k, v in data["books"].items() if R.side_of(k) == "short"}
    pairs = data["pairs"]
    longs = {k: v for k, v in data["books"].items() if R.side_of(k) == "long"}
    short_keys, pair_keys = list(shorts), list(pairs)
    ats = sorted(float(r["at"]) for v in shorts.values() for r in v)
    mid = ats[len(ats) // 2]
    since = time.mktime(time.strptime(SINCE, "%Y-%m-%d")) - time.timezone
    wins = {"all": (None, None), "half1": (None, mid), "half2": (mid, None), "since": (since, None)}
    res = {"seeds": seeds, "since": SINCE, "mid": mid, "deps": [int(d) for d in DEPS],
           "keys": {"short": short_keys, "pair": pair_keys}, "grid": [g[0] for g in GRID],
           "grid_title": {g[0]: g[1] for g in GRID}, "windows": {}}

    def cash_of(sh, psh, lw):
        c = LG.cash(sh, short_keys, now)
        c.update(LG.cash(EC.pack_pairs(pairs, lw, psh), pair_keys, now))
        return c

    for wname, (lo, hi) in wins.items():
        part = LG.window(shorts, lo, hi)
        pshort = LG.window({pk: v[2] for pk, v in pairs.items()}, lo, hi)
        lpart = LG.window(longs, lo, hi)
        cells = {"rule": {"cash": cash_of(part, pshort, lpart)}}
        # потолок — для масштаба
        sh_c = {k: EC.ceiling_recs(v, k)[0] for k, v in part.items()}
        ps_c = {k: EC.ceiling_recs(v, k)[0] for k, v in pshort.items()}
        cells["ceiling"] = {"cash": cash_of(sh_c, ps_c, lpart)}
        for name, _title, spec in GRID:
            sh_g, ps_g, pos = {}, {}, {}
            for k, v in part.items():
                sh_g[k], hits = grid_recs(v, k, spec)
                pos[k] = EC.pos_stats(hits)
            for k, v in pshort.items():
                ps_g[k], hits = grid_recs(v, k, spec)
                pos[k] = EC.pos_stats(hits)
            cells[name] = {"cash": cash_of(sh_g, ps_g, lpart), "pos": pos}
        log(f"окно {wname}: правило, потолок и {len(GRID)} ячеек ({time.time() - t0:.0f} с)")
        draws, pdelta = [], {}
        for sd in range(seeds):
            rng = random.Random(5000 + sd)
            sh_r, ps_r = {}, {}
            for k, v in part.items():
                sh_r[k], hits = EC.random_recs(v, k, rng)
                pdelta.setdefault(k, []).append(EC.pos_stats(hits).get("delta_mean"))
            for k, v in pshort.items():
                ps_r[k], hits = EC.random_recs(v, k, rng)
                pdelta.setdefault(k, []).append(EC.pos_stats(hits).get("delta_mean"))
            draws.append(cash_of(sh_r, ps_r, lpart))
        rnd = {}
        for k in short_keys + pair_keys:
            for d in DEPS:
                xs = [(x[k][int(d)] or {}).get("final") for x in draws]
                xs = [x for x in xs if x is not None]
                dd = [(x[k][int(d)] or {}).get("max_dd") for x in draws]
                dd = [x for x in dd if x is not None]
                rnd.setdefault(k, {})[int(d)] = {"final": (sum(xs) / len(xs)) if xs else None,
                                                 "max_dd": (sum(dd) / len(dd)) if dd else None,
                                                 "all": xs}
            ys = [y for y in pdelta.get(k, []) if y is not None]
            rnd[k]["pos_delta_mean"] = (sum(ys) / len(ys)) if ys else None
        cells["random"] = {"cash": rnd}
        log(f"окно {wname}: слепой выход {seeds} зёрен ({time.time() - t0:.0f} с)")
        res["windows"][wname] = cells
    res["selection"] = select(res)
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


def mean_final(cells, name, keys, dep=10000):
    xs = [((cells[name]["cash"].get(k) or {}).get(dep) or {}).get("final") for k in keys]
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if len(xs) == len(keys) else None


def select(res):
    """Правило отбора, объявленное до прогона: победитель по ПЕРВОЙ половине
    (средний итог $10k трёх коротких книг), суд — на ВТОРОЙ."""
    keys = res["keys"]["short"]
    h1, h2 = res["windows"]["half1"], res["windows"]["half2"]
    scores = {g: mean_final(h1, g, keys) for g in res["grid"]}
    scores = {g: s for g, s in scores.items() if s is not None}
    if not scores:
        return {"error": "ни одна ячейка не посчитана на первой половине"}
    win = max(scores, key=scores.get)
    judge = {}
    for k in keys + res["keys"]["pair"]:
        for d in (1000, 10000):
            g = ((h2[win]["cash"].get(k) or {}).get(d) or {}).get("final")
            r = ((h2["rule"]["cash"].get(k) or {}).get(d) or {}).get("final")
            xs = (h2["random"]["cash"].get(k) or {}).get(d, {}).get("all") or []
            judge[f"{k}:{d}"] = {"cell": g, "rule": r,
                                 "blind_mean": (sum(xs) / len(xs)) if xs else None,
                                 "blind_not_worse": (None if g is None or not xs
                                                     else sum(1 for x in xs if x >= g) / len(xs))}
    beats_rule = all(v["cell"] is not None and v["rule"] is not None and v["cell"] > v["rule"]
                     for kk, v in judge.items() if kk.split(":")[0] in keys and kk.endswith(":10000"))
    beats_blind = all(v["blind_not_worse"] is not None and v["blind_not_worse"] <= 0.10
                      for kk, v in judge.items() if kk.split(":")[0] in keys and kk.endswith(":10000"))
    return {"winner": win, "half1_scores": scores, "judge_half2": judge,
            "beats_rule_half2": beats_rule, "beats_blind_half2": beats_blind}


WIN_TITLE = {"all": "Вся запись", "half1": "Первая половина (по моменту решения) — здесь ВЫБИРАЕТСЯ",
             "half2": "Вторая половина — здесь СУДИТСЯ", "since": f"С {SINCE}"}


def _pp(x):
    return LG._pp(x)


def _pts(x):
    return EC._pts(x)


def report(res):
    if res.get("error"):
        return f"# Сетка выходов коротких книг\n\nНе посчитано: {res['error']}.\n"
    sel = res.get("selection") or {}
    keys = res["keys"]["short"]
    L = ["# Сетка детерминированных выходов: короткие книги", "",
         "Входы и размер — как у книги; меняется только выход, и только раньше правила. Решение — "
         "по закрытию часа по пути до этого часа (будущее не видно). Сетка, контроли и правило отбора "
         "объявлены ДО прогона (`exit_grid.py`). Касса тем же ядром, деньги БРУТТО.", "",
         "## Вердикт по объявленному правилу отбора", ""]
    if sel.get("error"):
        L += [f"Отбор не состоялся: {sel['error']}.", ""]
    else:
        w = sel["winner"]
        L += [f"Победитель первой половины: **{w}** — {res['grid_title'][w]} "
              f"(средний итог $10k трёх коротких книг {_pp(sel['half1_scores'][w])}).", "",
              "Суд на второй половине:", "",
              "| книга | депозит | ячейка | правило книги | слепой выход (среднее) | слепой не хуже ячейки |",
              "|---|--:|--:|--:|--:|--:|"]
        for kk, v in sel["judge_half2"].items():
            k, d = kk.rsplit(":", 1)
            L.append("| %s (`%s`) | $%s | %s | %s | %s | %s |" % (
                R.title_en(k), k, f"{int(d):,}", _pp(v["cell"]), _pp(v["rule"]), _pp(v["blind_mean"]),
                "—" if v["blind_not_worse"] is None else "%d %% зёрен" % round(100 * v["blind_not_worse"])))
        verdict = ("**кандидат**: бьёт правило книги на второй половине у всех трёх коротких книг $10k "
                   "и случайный выход не лучше него в ≥ 90 % зёрен"
                   if sel["beats_rule_half2"] and sel["beats_blind_half2"] else
                   "**не кандидат**: " + ("на второй половине не бьёт правило книги у всех трёх коротких книг $10k"
                                          if not sel["beats_rule_half2"] else
                                          "случайный ранний выход не хуже него чаще чем в 10 % зёрен — "
                                          "выигрыш от «закрыть раньше», не от правила"))
        L += ["", "Вердикт: " + verdict + ".", "",
              "Очки первой половины (средний итог $10k трёх коротких книг): " +
              ", ".join(f"{g} {_pp(s)}" for g, s in sorted(sel["half1_scores"].items(),
                                                            key=lambda kv: -kv[1])) + ".", ""]
    for wname in ("all", "half1", "half2", "since"):
        cells = res["windows"].get(wname)
        if not cells:
            continue
        L += [f"## {WIN_TITLE[wname]}", ""]
        for side, ks in (("короткие книги h24", res["keys"]["short"]),
                         ("общий счёт (выход меняется у короткой стороны)", res["keys"]["pair"])):
            L += [f"### {side}", "",
                  "| вариант | " + " | ".join(f"{R.title_en(k)} $1k | {R.title_en(k)} $10k" for k in ks) +
                  " | Δ на позицию (" + ", ".join(R.title_en(k) for k in ks) + ") |",
                  "|---|" + "--:|" * (2 * len(ks)) + "---|"]
            names = [("rule", "правило книги"), ("random", "слепой выход (среднее)")] + \
                [(g, f"{g} · {res['grid_title'][g]}") for g in res["grid"]] + [("ceiling", "потолок (знает будущее)")]
            for name, title in names:
                c = cells[name]["cash"]
                vals = []
                for k in ks:
                    for d in (1000, 10000):
                        vals.append(_pp(((c.get(k) or {}).get(d) or {}).get("final")))
                if name == "random":
                    dpos = ", ".join(_pts((c.get(k) or {}).get("pos_delta_mean")) for k in ks)
                elif name in res["grid"]:
                    dpos = ", ".join(_pts(((cells[name]["pos"].get(k) or {}).get("delta_mean"))) for k in ks)
                else:
                    dpos = "—"
                L.append(f"| {title} | " + " | ".join(vals) + f" | {dpos} |")
            L.append("")
    L += ["## Чего замер НЕ говорит", "",
          "- Деньги брутто: ранний выход рыночный — проскальзывание выхода (`costs.SLIP_BP`) и лишний круг "
          "комиссии от возросшего оборота не вычтены; ячейка с большим оборотом на издержках проигрывает "
          "больше остальных.",
          "- Решение раз в час по отметке ядра; лимитный тейк внутри часа и трейлинг по тикам не моделируются.",
          "- Половины делят запись по моменту решения; режим рынка в них разный — суд на второй половине "
          "проверяет, переносится ли выбор, а не доказывает эдж.",
          "- Доход книг пока рыночный (15.10): выход перераспределяет тот же ход, нового источника денег он "
          "не создаёт.", "",
          f"Прогон {res.get('secs')} с, {res.get('computed_at')} UTC, слепой выход — {res['seeds']} зёрен."]
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
    slim = json.loads(json.dumps(res))
    for w in (slim.get("windows") or {}).values():
        for k, v in ((w.get("random") or {}).get("cash") or {}).items():
            for d in list(v):
                if isinstance(v[d], dict):
                    v[d].pop("all", None)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)
    print(txt[:4000])
    if not a.no_publish and not res.get("error"):
        subprocess.run(["tools/publish.sh", "замер: сетка выходов коротких книг"], cwd=ROOT, check=False)
    return 0 if not res.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
