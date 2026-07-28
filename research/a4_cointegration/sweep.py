#!/usr/bin/env python3
"""
A4 — выбор шага бара для теста на коинтеграцию, измерением.

Спека 02 §2.2 задаёт 1m как разрешение хранения. Разрешение хранения и
разрешение теста — разные вещи, и спека второго не задаёт. Здесь оно
выбирается по данным, на одних и тех же парах и одном и том же окне.

Что должно быть видно:

- **доля пар, проходящих тест, растёт с числом наблюдений.** Это
  свойство теста, а не рынка: мощность против сколь угодно слабого
  возврата к среднему растёт с выборкой. Если на 1m проходит половина
  кандидатов, а на 1d — единицы, значит на 1m тест отвечает на вопрос
  «есть ли возврат вообще», а нам нужен «есть ли возврат быстрее
  издержек»;
- **полураспад** тех же пар. Он измеряется в барах и переводится в
  часы: если у прошедших тест пар полураспад в неделях, при удержании
  1–5 дней они бесполезны, каким бы ни было p-значение;
- **β на разных шагах.** На минутных барах β занижается несинхронной
  торговлей — эффект Эппса. Это открытый пункт из A2, здесь он
  закрывается числом.

    python3 sweep.py --at 2025-06-15 --limit 200
"""

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import coint as C          # noqa: E402
import series as S         # noqa: E402
import pairs as P          # noqa: E402

STEPS = ("1d", "4h", "1h", "15m", "1m")
BARS_PER_DAY = {"1d": 1, "4h": 6, "1h": 24, "15m": 96, "1m": 1440}
FORM_DAYS = 90
ALPHA = 0.10


def window(at):
    from datetime import date, timedelta
    t1 = date.fromisoformat(at)
    t0 = t1 - timedelta(days=FORM_DAYS)
    return t0.isoformat(), t1.isoformat()


def q(vals, p):
    v = sorted(x for x in vals if np.isfinite(x))
    return v[min(len(v) - 1, int(p * (len(v) - 1)))] if v else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="2025-06-15")
    ap.add_argument("--limit", type=int, default=200,
                    help="сколько кандидатов брать (0 — все)")
    ap.add_argument("--interval", default="1m")
    args = ap.parse_args()

    groups, of_group, meta = P.load_groups()
    liq, universe = P.load_liquidity(args.interval)
    st = P.state_at(liq, universe, args.at)
    cand, live = P.candidates(groups, of_group, meta, st)
    if args.limit:
        # Берём не первые попавшиеся, а равномерно по списку: первые
        # отсортированы по группе, и выборка «сверху» описала бы одну
        # группу вместо универсума.
        idx = np.linspace(0, len(cand) - 1, min(args.limit, len(cand)))
        cand = [cand[int(i)] for i in dict.fromkeys(idx.astype(int))]

    t0, t1 = window(args.at)
    sym = {a: universe[a]["binance_symbol"] for a, _, _ in cand}
    sym.update({b: universe[b]["binance_symbol"] for _, b, _ in cand})
    con = S.connect()

    report = {"at": args.at, "form_days": FORM_DAYS, "pairs": len(cand),
              "alpha": ALPHA, "steps": {}}
    per_pair = {}

    # Хранилище читается один раз, на 1m. Приведение к крупному шагу
    # делается в памяти: перечитывание тех же трёх месяцев по всему
    # универсуму стоило минуту на каждый шаг.
    t = time.time()
    base = S.load(con, sorted(set(sym.values())), t0, t1, step="1m",
                  interval=args.interval)
    print(f"загружено {len(base)} рядов 1m за {time.time()-t:.0f} с",
          flush=True)

    for step in STEPS:
        t = time.time()
        data = {s: S.resample(*v, step) for s, v in base.items()}
        res = []
        for a, b, g in cand:
            sa, sb = sym[a], sym[b]
            if sa not in data or sb not in data:
                continue
            _, ca, cb = S.align(data[sa], data[sb])
            # Первой ногой — более оборотистая: направление регрессии не
            # должно зависеть от порядка, в котором пара пришла из A3.
            if st[a]["turnover"] < st[b]["turnover"]:
                ca, cb = cb, ca
            r = C.test_pair(ca, cb)
            if r is None:
                continue
            r["pair"] = f"{a}/{b}"
            r["group"] = g
            res.append(r)
            per_pair.setdefault(r["pair"], {})[step] = r

        if not res:
            # Молча пропустить нельзя: шаг, на котором не набирается
            # наблюдений, — это ответ, а не отсутствие ответа.
            need = C.MIN_OBS / BARS_PER_DAY[step]
            report["steps"][step] = {
                "tested": 0,
                "skipped": f"наблюдений меньше {C.MIN_OBS}: окно в "
                           f"{FORM_DAYS} дней даёт "
                           f"{FORM_DAYS * BARS_PER_DAY[step]}, "
                           f"для теста нужно окно от {need:.0f} дней",
            }
            print(f"{step:>4}: пропущен — {report['steps'][step]['skipped']}",
                  flush=True)
            continue
        p = np.array([r["p"] for r in res])
        keep = C.benjamini_hochberg(p, ALPHA)
        hl_days = [r["half_life"] / BARS_PER_DAY[step] for r in res]
        hl_kept = [res[i]["half_life"] / BARS_PER_DAY[step] for i in keep]
        report["steps"][step] = {
            "tested": len(res),
            "obs_median": int(np.median([r["n"] for r in res])),
            "raw_pass": int((p < 0.05).sum()),
            "fdr_pass": int(len(keep)),
            "half_life_days_p25": q(hl_days, 0.25),
            "half_life_days_p50": q(hl_days, 0.50),
            "half_life_days_p75": q(hl_days, 0.75),
            "half_life_days_kept_p50": q(hl_kept, 0.50),
            "kept_within_5d": int(sum(1 for h in hl_kept if h <= 5)),
            "beta_median": float(np.median([r["beta"] for r in res])),
            "seconds": round(time.time() - t, 1),
        }
        s = report["steps"][step]
        print(f"{step:>4}: наблюдений {s['obs_median']:>6}  "
              f"p<0.05 {s['raw_pass']:>4}/{s['tested']:<4} "
              f"после FDR {s['fdr_pass']:>4}  "
              f"полураспад медиана {s['half_life_days_p50']:>6.1f} дн  "
              f"у прошедших {s['half_life_days_kept_p50']:>6.1f} дн  "
              f"из них ≤5 дн: {s['kept_within_5d']:>3}  "
              f"β медиана {s['beta_median']:.3f}  ({s['seconds']} с)",
              flush=True)

    # Эффект Эппса: β одной и той же пары на разных шагах.
    ratios = []
    for pair, by in per_pair.items():
        if "1m" in by and "1h" in by and abs(by["1h"]["beta"]) > 1e-9:
            ratios.append(by["1m"]["beta"] / by["1h"]["beta"])
    if ratios:
        report["epps"] = {"pairs": len(ratios),
                          "beta_1m_over_1h_p25": q(ratios, 0.25),
                          "beta_1m_over_1h_p50": q(ratios, 0.50),
                          "beta_1m_over_1h_p75": q(ratios, 0.75)}
        e = report["epps"]
        print(f"\nэффект Эппса: β(1m)/β(1h) по {e['pairs']} парам — "
              f"25/50/75 %: {e['beta_1m_over_1h_p25']:.3f} / "
              f"{e['beta_1m_over_1h_p50']:.3f} / "
              f"{e['beta_1m_over_1h_p75']:.3f}")

    # Полураспад в единицах ВРЕМЕНИ не должен зависеть от шага бара: это
    # свойство спреда, а не сетки наблюдений. Если он укорачивается с
    # измельчением бара, значит измеряется не возврат к среднему, а
    # микроструктурный шум — отскок между сторонами стакана даёт
    # отрицательную автокорреляцию, которая на минутах видна, а на часах
    # усредняется. Сравнение делается по одним и тем же парам.
    inv = {}
    for step in STEPS:
        if step == "4h":
            continue
        rel = []
        for pair, by in per_pair.items():
            if "4h" not in by or step not in by:
                continue
            base = by["4h"]["half_life"] / BARS_PER_DAY["4h"]
            here = by[step]["half_life"] / BARS_PER_DAY[step]
            if np.isfinite(base) and np.isfinite(here) and base > 0:
                rel.append(here / base)
        if rel:
            inv[step] = {"pairs": len(rel), "p25": q(rel, 0.25),
                         "p50": q(rel, 0.50), "p75": q(rel, 0.75)}
    if inv:
        report["half_life_invariance"] = inv
        print("\nполураспад относительно замера на 4h (по одним парам):")
        for step, v in inv.items():
            print(f"  {step:>4}: 25/50/75 % — {v['p25']:.2f} / "
                  f"{v['p50']:.2f} / {v['p75']:.2f}  ({v['pairs']} пар)")

    report["per_pair"] = {
        pair: {step: {"p": r["p"], "beta": r["beta"],
                      "half_life_days": r["half_life"] / BARS_PER_DAY[step]}
               for step, r in by.items()}
        for pair, by in per_pair.items()}

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"sweep_{args.at}.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
