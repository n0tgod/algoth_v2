#!/usr/bin/env python3
"""
A4 — сравнение настоящего прогона с нулевой моделью §7.

Вопрос один: добавляет ли экономическая группировка §3.1 что-нибудь по
сравнению с тем же конвейером на перемешанных метках. Считает не свою
статистику, а `walkforward.summarize` — вторая копия арифметики решения
была бы ровно тем, чего проект избегает.

**Чем нельзя сравнивать напрямую.** Число пар после FDR у нуля и у
прогона получено при разном числе тестов: перемешанные метки сводят в
одну «группу» крупные и мелкие активы, фильтр по обороту ×10 режет
больше, и кандидатов у нуля меньше — местами на треть. Порог
Бенджамини–Хохберга равен k/m·alpha, то есть при меньшем m он мягче, и
нуль оказывается в выигрышном положении. Поэтому рядом всегда
докладывается доля сырых срабатываний p<0.05: она от m не зависит
вовсе и сравнивается честно.

    python3 compare.py                     # все 48 окон
    python3 compare.py --since 2025-01-01  # только окна с тысячей кандидатов
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)

import walkforward as W  # noqa: E402


def subset(rows, since=None, until=None):
    rows = sorted(rows, key=lambda r: r["date"])
    return [r for r in rows
            if (since is None or r["date"] >= since)
            and (until is None or r["date"] <= until)]


def rates(rows):
    """Доли, не зависящие от того, сколько было тестов."""
    tested = sum(r["tested"] for r in rows)
    return {
        "windows": len(rows),
        "candidates_mean": float(np.mean([r["candidates"] for r in rows])),
        "raw_pass_share": sum(r["raw_pass"] for r in rows) / tested if tested else float("nan"),
        "fdr_pass_share": sum(r["fdr_pass"] for r in rows) / tested if tested else float("nan"),
        "fdr_pass_mean": float(np.mean([r["fdr_pass"] for r in rows])),
        "fdr_pass_median": float(np.median([r["fdr_pass"] for r in rows])),
        "windows_zero": int(sum(1 for r in rows if r["fdr_pass"] == 0)),
    }


def block(rows, where=None):
    s = W.summarize(rows, where)
    return {**rates(rows),
            "adjacent": s["adjacent"], "three_steps": s["three_steps"]}


def show(name, real, null):
    print(f"\n=== {name} ===")
    print(f"{'':38} {'прогон':>12} {'нуль':>12}")
    rows = [
        ("окон", "windows", "{:.0f}"),
        ("кандидатов на окно", "candidates_mean", "{:.0f}"),
        ("доля p<0.05 (не зависит от m)", "raw_pass_share", "{:.1%}"),
        ("доля прошедших FDR", "fdr_pass_share", "{:.1%}"),
        ("пар после FDR на окно, среднее", "fdr_pass_mean", "{:.1f}"),
        ("пар после FDR на окно, медиана", "fdr_pass_median", "{:.0f}"),
        ("окон с нулём пар", "windows_zero", "{:.0f}"),
    ]
    for label, key, fmt in rows:
        print(f"{label:38} {fmt.format(real[key]):>12} "
              f"{fmt.format(null[key]):>12}")
    for lag, key in (("соседние окна", "adjacent"),
                     ("через три шага", "three_steps")):
        print(f"  -- выживаемость, {lag} --")
        for label, k, fmt in (
                ("  выживание среди проверенных", "survival", "{:.1%}"),
                ("  при отборе наугад", "survival_by_chance", "{:.1%}"),
                ("  превосходство над случайным", "survival_over_chance", "x{:.1f}"),
                ("  знаменатель, пар", "survival_denominator_total", "{:.0f}"),
                ("  кандидаты переходят целиком", "candidate_carryover", "{:.1%}")):
            print(f"{label:38} {fmt.format(real[key][k]):>12} "
                  f"{fmt.format(null[key][k]):>12}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-seed", type=int, default=1)
    ap.add_argument("--since", default="2025-01-01",
                    help="граница отдельного среза богатых окон")
    args = ap.parse_args()

    real = W.load_windows(W.windows_dir())
    null = W.load_windows(W.windows_dir(args.null_seed))
    if not real or not null:
        raise SystemExit("нет посчитанных окон: сначала walkforward.py "
                         "и walkforward.py --null")
    dates_real = {r["date"] for r in real}
    dates_null = {r["date"] for r in null}
    if dates_real != dates_null:
        # Сравнивать наборы по разным датам нельзя: разница в числах
        # оказалась бы разницей в периодах, а не в группировке.
        raise SystemExit(
            f"наборы окон не совпадают: только в прогоне "
            f"{sorted(dates_real - dates_null)}, только в нуле "
            f"{sorted(dates_null - dates_real)}")

    full = {"real": block(real, W.windows_dir()),
        "null": block(null, W.windows_dir(args.null_seed))}
    show(f"все {len(real)} окон", full["real"], full["null"])

    late_real, late_null = subset(real, args.since), subset(null, args.since)
    late = {"real": block(late_real, W.windows_dir()),
        "null": block(late_null, W.windows_dir(args.null_seed))}
    show(f"окна с {late_real[0]['date']} по {late_real[-1]['date']}"
         f" (кандидатов больше тысячи)", late["real"], late["null"])

    print("\nворонка по окнам")
    print("дата         кандидаты        p<0.05          после FDR")
    print("             прогон  нуль   прогон  нуль     прогон  нуль")
    by_date = {r["date"]: r for r in null}
    for r in sorted(real, key=lambda x: x["date"]):
        n = by_date[r["date"]]
        print(f"{r['date']}  {r['candidates']:>6} {n['candidates']:>5}   "
              f"{r['raw_pass']:>6} {n['raw_pass']:>5}     "
              f"{r['fdr_pass']:>6} {n['fdr_pass']:>5}")

    with open(os.path.join(OUT, "A4-null-comparison.json"), "w",
              encoding="utf-8") as f:
        json.dump({"null_seed": args.null_seed, "since": args.since,
                   "all_windows": full, "late_windows": late,
                   "funnel": [{"date": r["date"],
                               "candidates_real": r["candidates"],
                               "candidates_null": by_date[r["date"]]["candidates"],
                               "raw_real": r["raw_pass"],
                               "raw_null": by_date[r["date"]]["raw_pass"],
                               "fdr_real": r["fdr_pass"],
                               "fdr_null": by_date[r["date"]]["fdr_pass"]}
                              for r in sorted(real, key=lambda x: x["date"])]},
                  f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
