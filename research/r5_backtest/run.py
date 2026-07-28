#!/usr/bin/env python3
"""
R5 — статистическая валидация по рядам доходностей из R4.

Спека 03 §8.3, критерии 6–8. Отдельного бэктест-движка здесь нет и не
нужно: R4 уже прошёл по датам ребаланса с переносом книги и посчитал
нетто каждого периода. Строить рядом второй счётчик значило бы завести
вторую копию расчётного ядра — прямой запрет CLAUDE.md, и именно эта
ошибка стоила первой версии двойной починки одного бага.

Число испытаний
---------------

Поправка считается по **96** — числу ячеек, объявленному в §2 спеки, а
не по 32 фактически посчитанным. Мы объявили сетку из 96 и обязаны
платить за неё, даже если три модели фактора свелись к одной: выбор
«считать по факту» удешевил бы поправку задним числом.

Разброс Sharpe по испытаниям берётся по тем ячейкам, что есть. Это
единственная доступная оценка, и она занижает разброс (у 96 ячеек он был
бы не меньше), то есть занижает и поправку — направление известно и
докладывается.

    python3 run.py --interval 1m
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
R4 = os.path.join(RESEARCH, "r4_costs", "out")

sys.path.insert(0, HERE)
import stats as S  # noqa: E402

DECLARED_TRIALS = 96          # §2 спеки: k × h × модель фактора × корзина
SHARPE_MIN = 0.8              # §8.3 п. 6
WORST_SUBPERIOD_MIN = 0.3     # §8.3 п. 7
MAX_DRAWDOWN = 0.20           # §8.3 п. 8, умеренный профиль спеки 01


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    args = ap.parse_args()
    path = os.path.join(R4, f"costs_{args.interval}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала r4_costs/run.py")
    with open(path, encoding="utf-8") as f:
        r4 = json.load(f)
    cfg = r4["config"]
    dates_by_h = r4.get("dates_by_h")
    if not dates_by_h:
        raise SystemExit(
            "в артефакте R4 нет рядов по периодам — он собран кодом раннего\n"
            "образца. Перезапустите r4_costs/run.py.")

    out = {}
    for rule, cells in r4["rules"].items():
        # Разброс Sharpe по испытаниям — вход поправки. Считается один раз
        # на правило по всем его ячейкам.
        srs = {}
        for name, c in cells.items():
            h = int(name.split("_h")[1].split("_")[0])
            s = S.sharpe(c["series"], 365.0 / h)
            if s is not None:
                srs[name] = s
        sr_std = S.moments(list(srs.values()))["sd"] if len(srs) > 1 else 0.0
        sr0 = S.expected_max_sharpe(DECLARED_TRIALS, sr_std)

        res = {}
        for name, c in cells.items():
            h = int(name.split("_h")[1].split("_")[0])
            ppy = 365.0 / h
            v = c["series"]
            d = S.deflated_sharpe(v, ppy, DECLARED_TRIALS, sr_std)
            if d is None:
                continue
            dd = S.max_drawdown(v)
            dates = dates_by_h[str(h)][:len(v)]
            years = {y: S.sharpe(x, ppy)
                     for y, x in S.split_by_year(dates, v).items()
                     if len(x) >= 5}
            thirds = {k: S.sharpe(x, ppy)
                      for k, x in S.split_equal(v, 3).items()}
            worst_y = min((s for s in years.values() if s is not None),
                          default=None)
            worst_t = min((s for s in thirds.values() if s is not None),
                          default=None)
            res[name] = {
                **d,
                "max_drawdown": dd["max_drawdown"],
                "final_equity": dd["final_equity"],
                "by_year": years, "by_third": thirds,
                "worst_year_sharpe": worst_y,
                "worst_third_sharpe": worst_t,
                "positive_years": sum(1 for s in years.values()
                                      if s is not None and s > 0),
                "years": len(years),
            }
        # Формула ожидаемого максимума предполагает НЕЗАВИСИМЫЕ испытания,
        # а наши 96 ячеек сильно скоррелированы: те же данные, соседние
        # горизонты, пересекающиеся сигналы. Эффективное число независимых
        # направлений заведомо меньше 96, значит поправка по 96 избыточно
        # строга. Поэтому вердикт проверяется на устойчивость: если он не
        # меняется даже при пяти эффективных испытаниях, спорить об этом
        # числе незачем.
        best_sr = max((r["sharpe_annual"] for r in res.values()), default=0.0)
        sens = {}
        for n in (5, 10, 32, DECLARED_TRIALS):
            s0 = S.expected_max_sharpe(n, sr_std)
            sens[str(n)] = {"sr0_annual": s0, "best_deflated": best_sr - s0,
                            "passes": (best_sr - s0) >= SHARPE_MIN}
        out[rule] = {"sr_std_over_cells": sr_std, "sr0_annual": sr0,
                     "best_sharpe_raw": best_sr,
                     "trials_sensitivity": sens, "cells": res}
        best = max(res.items(), key=lambda kv: kv[1]["sharpe_deflated"],
                   default=(None, None))
        if best[0]:
            print(f"{rule}: SR0 = {sr0:.2f}; лучшая {best[0]} — "
                  f"Sharpe {best[1]['sharpe_annual']:.2f}, "
                  f"с поправкой {best[1]['sharpe_deflated']:.2f}",
                  file=sys.stderr, flush=True)

    doc = {"config": {"interval": cfg["interval"],
                      "declared_trials": DECLARED_TRIALS,
                      "cells_measured": len(r4["rules"]["expected"]),
                      "funding_included": cfg["funding_included"],
                      "sharpe_min": SHARPE_MIN,
                      "worst_subperiod_min": WORST_SUBPERIOD_MIN,
                      "max_drawdown": MAX_DRAWDOWN},
           "rules": out}
    os.makedirs(OUT, exist_ok=True)
    name = f"validation_{cfg['interval']}.json"
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"записано {os.path.join(OUT, name)}")


if __name__ == "__main__":
    main()
