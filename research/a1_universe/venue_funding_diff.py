#!/usr/bin/env python3
"""
A1 — расхождение ставок funding между площадками, выровненное по периодам.

Раздел 5.2 спеки 02 требует измерить, насколько ставки Bybit и Binance
расходятся по одному активу. Требование не косметическое: спека запрещает
считать издержки удержания по ставкам площадки, отличной от площадки
исполнения, и это измерение показывает цену нарушения запрета.

**Почему сравнение по сводкам не годится.** Первая оценка бралась из
`funding_summary.json` и `funding_binance_summary.json`: у каждого актива
средняя ставка за всю его историю на этой площадке. Истории разные —
инструмент листится на площадках в разные дни, архив Binance отстаёт от
API Bybit на месяц, часть активов ушла с одной площадки раньше, чем с
другой. Разность двух средних за разные периоды измеряет в основном
разницу периодов. Хвост такой оценки нечитаем: GWEI давал -433.8 % против
+20.5 %, то есть даже разный знак.

**Что считается здесь.** По каждому активу берётся пересечение периодов —
от позднейшего начала до раннейшего конца, — и обе площадки считаются
строго внутри него, с одним и тем же знаменателем:

    годовая издержка = сумма начисленных ставок / длина окна × 365 × 100 %

Сумма, а не средняя: держатель позиции платит сумму. Она не требует знать
частоту начисления и сама учитывает, что за одно окно Bybit мог начислить
вдвое чаще Binance. Знаменатель — длина окна, одинаковая для обеих
площадок; расстояние между крайними начислениями внутри окна дало бы
площадкам разные знаменатели и снова разрушило бы выравнивание.

Окно короче `MIN_SPAN_DAYS` не берётся в статистику: на двух неделях
годовая издержка — экстраполяция шума в двадцать шесть раз.

Запуск (после `bybit_api.py` и `binance_funding.py`):

    python3 venue_funding_diff.py

Пишет `out/funding_venue_diff.json`; раздел отчёта рендерит
`data_report.py`. Только stdlib.
"""

import csv
import gzip
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
BYBIT_DIR = os.path.join(OUT, "funding")
BINANCE_DIR = os.path.join(OUT, "funding_binance")

sys.path.insert(0, RESEARCH)
from common.funding import annualized_from_sum  # noqa: E402

MIN_SPAN_DAYS = 90       # короче — годовая величина есть экстраполяция шума
MIN_ACCRUALS = 30        # и слишком мало начислений, чтобы усреднять


def read_series(path, rate_col):
    """(отметка времени UTC, ставка) из gzip-CSV с заголовком."""
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for row in list(csv.reader(f))[1:]:
            if not row:
                continue
            out.append((datetime.fromisoformat(row[0]), float(row[rate_col])))
    out.sort()
    return out


def window_stats(series, lo, hi):
    """Сумма ставок и число начислений строго внутри окна [lo, hi]."""
    inside = [r for t, r in series if lo <= t <= hi]
    return sum(inside), len(inside)


def quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    s = sorted(vals)
    if not s:
        return {}
    return {q: s[min(len(s) - 1, int(q * (len(s) - 1)))] for q in qs}


def main():
    universe = json.load(open(os.path.join(OUT, "universe.json"), encoding="utf-8"))
    by_sum = json.load(open(os.path.join(OUT, "funding_summary.json"), encoding="utf-8"))
    bn_sum = json.load(open(os.path.join(OUT, "funding_binance_summary.json"),
                            encoding="utf-8"))["assets"]

    assets, skipped = {}, {"нет ряда": 0, "нет пересечения": 0, "окно короче порога": 0}

    for asset, rec in universe["assets"].items():
        bys, bns = rec.get("bybit_symbol"), rec.get("binance_symbol")
        if not (bys and bns):
            continue
        p_by = os.path.join(BYBIT_DIR, f"{bys}.csv.gz")
        p_bn = os.path.join(BINANCE_DIR, f"{bns}.csv.gz")
        if not (os.path.exists(p_by) and os.path.exists(p_bn)):
            skipped["нет ряда"] += 1
            continue

        s_by = read_series(p_by, 1)          # funding_time, funding_rate
        s_bn = read_series(p_bn, 2)          # funding_time, interval_hours, funding_rate
        if not s_by or not s_bn:
            skipped["нет ряда"] += 1
            continue

        lo = max(s_by[0][0], s_bn[0][0])
        hi = min(s_by[-1][0], s_bn[-1][0])
        span_days = (hi - lo).total_seconds() / 86_400
        if span_days <= 0:
            skipped["нет пересечения"] += 1
            continue

        sum_by, n_by = window_stats(s_by, lo, hi)
        sum_bn, n_bn = window_stats(s_bn, lo, hi)
        ann_by = annualized_from_sum(sum_by, span_days)
        ann_bn = annualized_from_sum(sum_bn, span_days)

        # Сводочная («невыровненная») оценка — то, с чем сравниваем.
        naive_by = by_sum.get(bys, {}).get("annualized_mean_pct")
        naive_bn = bn_sum.get(asset, {}).get("annualized_mean_pct")

        assets[asset] = {
            "bybit_symbol": bys,
            "binance_symbol": bns,
            "window_start": lo.isoformat(),
            "window_end": hi.isoformat(),
            "span_days": span_days,
            "bybit_accruals": n_by,
            "binance_accruals": n_bn,
            "bybit_ann_pct": ann_by,
            "binance_ann_pct": ann_bn,
            "diff_pp": ann_by - ann_bn,
            "naive_bybit_ann_pct": naive_by,
            "naive_binance_ann_pct": naive_bn,
            "naive_diff_pp": (naive_by - naive_bn)
                             if (naive_by is not None and naive_bn is not None) else None,
            "usable": span_days >= MIN_SPAN_DAYS
                      and min(n_by, n_bn) >= MIN_ACCRUALS,
        }
        if not assets[asset]["usable"]:
            skipped["окно короче порога"] += 1

    usable = {a: v for a, v in assets.items() if v["usable"]}
    d_al = [abs(v["diff_pp"]) for v in usable.values()]
    # Сравнение обеих оценок строго на одном наборе активов: иначе разницу
    # между ними можно списать на разный состав выборки.
    d_na = [abs(v["naive_diff_pp"]) for v in usable.values()
            if v["naive_diff_pp"] is not None]

    meta = {
        "assets_compared": len(assets),
        "assets_usable": len(usable),
        "min_span_days": MIN_SPAN_DAYS,
        "min_accruals": MIN_ACCRUALS,
        "skipped": skipped,
        "median_span_days": sorted(v["span_days"] for v in usable.values())[len(usable) // 2]
                            if usable else 0,
        "aligned_abs_diff_pp": {str(k): v for k, v in quantiles(d_al).items()},
        "naive_abs_diff_pp": {str(k): v for k, v in quantiles(d_na).items()},
        "aligned_max_abs_pp": max(d_al) if d_al else 0,
        "naive_max_abs_pp": max(d_na) if d_na else 0,
        "sign_disagreement": sum(
            1 for v in usable.values()
            if v["bybit_ann_pct"] * v["binance_ann_pct"] < 0),
        "bybit_higher": sum(1 for v in usable.values() if v["diff_pp"] > 0),
    }

    path = os.path.join(OUT, "funding_venue_diff.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "assets": assets}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"записан {path}")


if __name__ == "__main__":
    main()
