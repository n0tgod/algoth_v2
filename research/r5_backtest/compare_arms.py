#!/usr/bin/env python3
"""
Сравнение рук прогона: чистый остаток против комбинации с funding.

Зачем отдельный шаг
-------------------

R5 докладывает Sharpe каждой ячейки по отдельности. Из таблицы видно,
что лучшая комбинированная ячейка даёт 1.43 против 1.08 у чистой, и это
читается как «рычаг 2 поднял Sharpe на 0.35». Прочтение неверно по двум
причинам, и обе проверяются здесь числом.

**Первая: разность двух Sharpe имеет собственную ошибку.** Стандартная
ошибка годового Sharpe равна `1/√(лет истории)` — на 3.6 годах это
±0.53, и от частоты ребаланса не зависит (замер `r2_residual/
path_norm.py`). Но ряды двух рук посчитаны на ОДНИХ И ТЕХ ЖЕ периодах и
сильно скоррелированы, поэтому ошибка их разности меньше ±0.53 и по
отдельным ошибкам не восстанавливается. Она меряется парным бутстрапом:
периоды пересэмплируются целыми парами, так что корреляция рук
сохраняется.

**Вторая: улучшение могло прийти не оттуда, откуда кажется.** §6 спеки
запрещал смешивать сигналы до измерения чистого остатка ровно потому,
что смешанный результат нельзя разложить обратно. Разложить его можно
только по составляющим PnL, и это здесь делается: если брутто остатка
падает, а funding из расхода превращается в доход, то комбинация не
улучшила предсказание остатка — она заменила его на carry, уже
открытый в A1.

    python3 compare_arms.py --interval 1m
"""

import argparse
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
R4 = os.path.join(os.path.dirname(HERE), "r4_costs", "out")
BOOTSTRAP = 4000
SEED = 20260728          # закреплено числом: нуль, который нельзя
                         # повторить, не является проверяемым (дефект R3)


def sharpe(v, ppy):
    v = np.asarray(v, dtype=np.float64)
    sd = v.std(ddof=1)
    return float(v.mean() / sd * np.sqrt(ppy)) if sd > 0 else None


def paired_bootstrap(a, b, ppy, rng, n_boot=BOOTSTRAP):
    """Распределение разности Sharpe при пересэмплировании ПАР периодов.

    Пары, а не два независимых ресэмпла: руки торгуют одни и те же дни,
    и независимый ресэмпл разорвал бы эту связь, завысив разброс
    разности — то есть сделал бы вывод «различие не значимо» слишком
    лёгким.
    """
    n = len(a)
    idx = rng.integers(0, n, size=(n_boot, n))
    d = np.array([sharpe(b[i], ppy) - sharpe(a[i], ppy) for i in idx])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--rule", default="expected")
    a = ap.parse_args()

    path = os.path.join(R4, f"costs_{a.interval}_blend.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала r4_costs/run.py --blend-funding")
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    cells = doc["rules"][a.rule]
    rng = np.random.default_rng(SEED)

    base = sorted(k for k in cells
                  if not k.endswith(("_blend", "_resid_r"))
                  and k + "_blend" in cells)

    print("## Разложение PnL: откуда взялось изменение\n")
    print(f"{'ячейка':<22}{'рука':<12}{'брутто':>9}{'комис.':>8}"
          f"{'funding':>9}{'нетто':>8}{'IC':>9}{'доля+':>8}")
    for k in base:
        h = int(k.split("_h")[1].split("_")[0])
        for nm, key in (("остаток", k), ("комбинация", k + "_blend")):
            c = cells[key]
            print(f"{k if nm == 'остаток' else '':<22}{nm:<12}"
                  f"{c['gross']['mean'] * 1e4:>9.2f}"
                  f"{c['commission']['mean'] * 1e4:>8.2f}"
                  f"{c['funding']['mean'] * 1e4:>9.2f}"
                  f"{c['net']['mean'] * 1e4:>8.2f}"
                  f"{c['ic_median']:>9.4f}{c['net_positive_share']:>8.3f}")

    print("\n## Разность Sharpe с парным бутстрапом\n")
    print(f"{'ячейка':<22}{'SR ост.':>9}{'SR комб.':>10}{'Δ':>8}"
          f"{'95 % интервал Δ':>22}{'P(Δ>0)':>9}{'корр':>7}{'n':>6}")
    rows = []
    for k in base:
        h = int(k.split("_h")[1].split("_")[0])
        ppy = 365.0 / h
        x = np.asarray(cells[k]["series"], dtype=np.float64)
        y = np.asarray(cells[k + "_blend"]["series"], dtype=np.float64)
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
        if n < 20:
            continue
        sa, sb = sharpe(x, ppy), sharpe(y, ppy)
        d = paired_bootstrap(x, y, ppy, rng)
        lo, hi = float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))
        pos = float((d > 0).mean())
        corr = float(np.corrcoef(x, y)[0, 1])
        print(f"{k:<22}{sa:>9.2f}{sb:>10.2f}{sb - sa:>8.2f}"
              f"{f'[{lo:+.2f}, {hi:+.2f}]':>22}{pos:>9.2f}{corr:>7.2f}{n:>6}")
        rows.append({"cell": k, "sharpe_resid": sa, "sharpe_blend": sb,
                     "delta": sb - sa, "ci_low": lo, "ci_high": hi,
                     "p_positive": pos, "corr": corr, "periods": n})

    better = [r for r in rows if r["delta"] > 0]
    signif = [r for r in rows if r["ci_low"] > 0]
    print(f"\nЯчеек с ростом Sharpe: {len(better)} из {len(rows)}. "
          f"Ячеек, где интервал разности не накрывает ноль: {len(signif)}.")

    dst = os.path.join(HERE, "out", f"arms_{a.interval}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"rule": a.rule, "bootstrap": BOOTSTRAP, "seed": SEED,
                   "cells": rows}, f, ensure_ascii=False, indent=2)
    print(f"\n→ {dst}")


if __name__ == "__main__":
    main()
