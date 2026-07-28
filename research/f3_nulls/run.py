#!/usr/bin/env python3
"""
F3 — нулевые модели раздела 7 спеки 04. Прогон.

Считается пересчётом векторов F1, как R3 и F2. Законно потому, что все
три нуля отличаются от прогона ровно тем, КАК сопоставлены сохранённые
векторы: перестановкой оценок внутри сечения, сдвигом сечения во
времени либо случайным отбором. Гонять конвейер тридцать раз незачем.

Побочная выгода важнее экономии: реальный результат, пересчитанный из
тех же векторов, обязан совпасть с артефактом F1. Сверка встроена и
прерывает прогон при расхождении.

Критерий немедленной остановки §8.2 проверяется здесь по двум условиям
из четырёх — остальные два измерены на F1 и не сработали.

    python3 run.py --interval 1m
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
F1 = os.path.join(RESEARCH, "f1_carry", "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "f1_carry"))
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "r5_backtest"))

import carry_nulls as NL           # noqa: E402
import carry as CY           # noqa: E402
import residual as RS        # noqa: E402
import stats as ST           # noqa: E402

KS = (7, 14)
HS = (5, 10)
WIDTHS = {"decile": 0.10, "quintile": 0.20}

SEEDS = 10                       # §7: не менее десяти зёрен
SHIFTS = (180, 270, 365, 450, 545, 640, 730, 200, 300, 400)
TOLERANCE = 1e-9


def load_vectors(tag):
    d = os.path.join(F1, "vectors")
    if not os.path.isdir(d):
        raise SystemExit(f"нет {d} — сначала f1_carry/run.py")
    out = {}
    for fn in sorted(os.listdir(d)):
        if fn.startswith(tag + "_") and fn.endswith(".json"):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                out.update(json.load(f))
    if not out:
        raise SystemExit(f"в {d} нет векторов для {tag}")
    return out


def arr(d, key):
    return np.asarray(d[str(key)] if str(key) in d else d[key],
                      dtype=np.float64)


def book_series(vec, days, k, h, width, mode=None, seed=None, shift=None):
    """Ряд брутто книги по непересекающимся датам.

    `mode`: `None` — прогон, `perm` — нуль 1, `random` — нуль 3,
    `shift` — нуль 2 (форвард берётся с даты `t + сдвиг`).
    """
    out = []
    have = set(days) if shift is None else set(vec)
    for day in days:
        v = vec[day]
        names = v["names"]
        score = arr(v["score"], k)

        if mode in ("perm", "random"):
            rng = np.random.default_rng(RS.seed_for(seed, day))
            score = (NL.permuted(score, rng) if mode == "perm"
                     else NL.random_scores(score, rng))

        if shift is None:
            price, fund = arr(v["price"], h), arr(v["funding"], h)
        else:
            far = (date.fromisoformat(day)
                   + timedelta(days=shift)).isoformat()
            if far not in have:
                continue
            w = vec[far]
            price = NL.align_by_name(names, w["names"], arr(w["price"], h))
            fund = NL.align_by_name(names, w["names"], arr(w["funding"], h))

        ww, per_leg = CY.weights(score, width)
        if per_leg < 1:
            continue
        out.append(CY.decompose(ww, price, fund)["gross"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--funding-venue", default="bybit")
    a = ap.parse_args()
    tag = f"{a.interval}_{a.funding_venue}"

    vec = load_vectors(tag)
    dates = sorted(vec)
    with open(os.path.join(F1, f"f1_{tag}.json"), encoding="utf-8") as f:
        f1 = json.load(f)

    cells, mismatches = {}, 0
    for k in KS:
        for h in HS:
            for wname, width in WIDTHS.items():
                name = f"k{k}_h{h}_{wname}"
                days = dates[::h]

                real = book_series(vec, days, k, h, width)
                got = CY.robust(real)
                want = f1["cells"].get(name, {}).get("gross")
                if want is not None and got is not None \
                        and abs(want - got) > TOLERANCE:
                    mismatches += 1
                    print(f"РАСХОЖДЕНИЕ {name}: F1 {want:.9f} против "
                          f"{got:.9f}", file=sys.stderr)

                n1 = [CY.robust(book_series(vec, days, k, h, width,
                                            mode="perm", seed=s))
                      for s in range(SEEDS)]
                n3_series = [book_series(vec, days, k, h, width,
                                         mode="random", seed=100 + s)
                             for s in range(SEEDS)]
                n3 = [CY.robust(x) for x in n3_series]
                n2 = [CY.robust(book_series(vec, days, k, h, width,
                                            shift=sh)) for sh in SHIFTS]

                # `max_drawdown` возвращает словарь с кривой эквити;
                # берётся только сама просадка. Первая редакция клала
                # словарь в статистику — падение поймал смоук.
                dd_real = ST.max_drawdown(real)["max_drawdown"]
                dd_n3 = [ST.max_drawdown(x)["max_drawdown"]
                         for x in n3_series if len(x) >= 10]

                p95_1 = NL.percentile(n1, 95)
                p95_3 = NL.percentile(n3, 95)
                cells[name] = {
                    "periods": len(real),
                    "real": got,
                    "null1_mean": CY.robust(n1, "mean"),
                    "null1_p95": p95_1,
                    "null1_sigmas": NL.sigmas_from(got, n1),
                    "null2_mean": CY.robust(n2, "mean"),
                    "null2_max": max(x for x in n2 if x is not None),
                    "null2_sigmas": NL.sigmas_from(got, n2),
                    "null3_mean": CY.robust(n3, "mean"),
                    "null3_p95": p95_3,
                    "above_null1_p95": (got is not None and p95_1 is not None
                                        and got > p95_1),
                    "above_null2_max": (got is not None
                                        and got > max(x for x in n2
                                                      if x is not None)),
                    "drawdown": dd_real,
                    "drawdown_null3_median": (CY.robust(dd_n3)
                                              if dd_n3 else None),
                    # Просадка отрицательна. «Хуже» означает глубже, то
                    # есть МЕНЬШЕ по величине со знаком.
                    "drawdown_worse_than_null3": (
                        dd_real is not None and dd_n3
                        and dd_real < CY.robust(dd_n3)),
                }

    if mismatches:
        raise SystemExit(f"сверка с F1 не сошлась в {mismatches} ячейках — "
                         f"нули считались бы для другой книги")

    n_cells = len(cells)
    above1 = sum(1 for c in cells.values() if c["above_null1_p95"])
    worse_dd = sum(1 for c in cells.values()
                   if c["drawdown_worse_than_null3"])
    stop = {
        # §8.2, условие 3: медианный результат обязан быть выше 95-го
        # процентиля нуля 1 — во всех ячейках, а не в среднем.
        "not_above_null1": above1 < n_cells,
        # §8.2, условие 4: просадка хуже, чем у случайной книги, в пяти
        # ячейках и более.
        "drawdown_worse_in_5plus": worse_dd >= 5,
    }
    doc = {"config": {"interval": a.interval, "funding_venue": a.funding_venue,
                      "seeds": SEEDS, "shifts": list(SHIFTS),
                      "sections": len(dates)},
           "cells": cells,
           "grid": {"cells": n_cells, "above_null1_p95": above1,
                    "above_null2_max": sum(1 for c in cells.values()
                                           if c["above_null2_max"]),
                    "drawdown_worse_than_null3": worse_dd,
                    "sigmas_null1_median": CY.robust(
                        [c["null1_sigmas"] for c in cells.values()]),
                    "sigmas_null2_median": CY.robust(
                        [c["null2_sigmas"] for c in cells.values()])},
           "stop_criterion": stop}
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"f3_{tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    g = doc["grid"]
    print(f"сверка брутто с F1: расхождений 0 из {n_cells} ячеек")
    print(f"выше 95-го процентиля нуля 1: {above1} из {n_cells}; "
          f"выше максимума нуля 2: {g['above_null2_max']} из {n_cells}")
    print(f"расстояние от нуля 1 — медиана {g['sigmas_null1_median']:.1f} σ, "
          f"от нуля 2 — {g['sigmas_null2_median']:.1f} σ")
    print(f"просадка хуже случайной книги: {worse_dd} из {n_cells}")
    print(f"критерий остановки §8.2: "
          f"{'СРАБОТАЛ' if any(stop.values()) else 'не сработал'}")
    print(f"записано {dst}")


if __name__ == "__main__":
    main()
