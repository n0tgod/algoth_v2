#!/usr/bin/env python3
"""
R2 — сверка прогонов: между разрешениями хранилища или с нулевой моделью.

Две разные проверки одним инструментом, потому что вопрос у них общий:
насколько два прогона, отличающиеся ровно одним, расходятся в числах.

    python3 compare.py --a 15m --b 1m            > out/R2-cross-check.md
    python3 compare.py --a 1m  --b 1m_null1      > out/R2-null-check.md

Сверка разрешений отвечает на вопрос «не ошибка ли это конвейера».
Часовое закрытие, собранное из 15m и из 1m, — одно и то же число (см.
`r1_factor/compare.py`), поэтому расходиться имеет право только состав
универсума: фильтр ликвидности на минутных барах строже.

Сверка с нулём отвечает на другой вопрос — «не создан ли сигнал самим
стендом». Разрушена связь «кто какой сигнал получил», остальное на
месте. Порог решения задаёт §8.2, полная нулевая модель — R3.
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def load(name):
    path = os.path.join(OUT, f"crosssection_{name}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def median(v):
    v = sorted(v)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2
                               else (v[n // 2 - 1] + v[n // 2]) / 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="15m")
    ap.add_argument("--b", default="1m")
    args = ap.parse_args()
    da, db = load(args.a), load(args.b)
    A, B = da["summary"], db["summary"]
    p = print

    p(f"# R2 — сверка `{args.a}` против `{args.b}`\n")
    p("| Величина | " + args.a + " | " + args.b + " |")
    p("|---|---|---|")
    p(f"| Сечений | {A['sections_total']} | {B['sections_total']} |")
    p(f"| Период | {A['date_first']} … {A['date_last']} "
      f"| {B['date_first']} … {B['date_last']} |")
    p(f"| Активов в сечении, медиана | {A['assets']['median']:.0f} "
      f"| {B['assets']['median']:.0f} |")
    p(f"| Активов, максимум | {A['assets']['max']} | {B['assets']['max']} |")
    p(f"| Медианный IC по сетке | {A['grid']['ic_median']:.4f} "
      f"| {B['grid']['ic_median']:.4f} |")
    p(f"| Лучшая ячейка | {A['grid']['ic_best']:.4f} "
      f"| {B['grid']['ic_best']:.4f} |")
    p(f"| Худшая ячейка | {A['grid']['ic_worst']:.4f} "
      f"| {B['grid']['ic_worst']:.4f} |")
    p(f"| Ячеек с положительным IC | {A['grid']['positive_cells']} из 16 "
      f"| {B['grid']['positive_cells']} из 16 |\n")

    keys = [k for k in A["cells"] if k in B["cells"]]
    d = []
    p("## По ячейкам\n")
    p(f"| Ячейка | IC {args.a} | IC {args.b} | Δ | "
      f"медиана спреда {args.a}, б.п. | медиана спреда {args.b}, б.п. |")
    p("|---|---|---|---|---|---|")
    for k in keys:
        x = A["cells"][k]["ic_independent"]["mean"]
        y = B["cells"][k]["ic_independent"]["mean"]
        m1 = A["cells"][k]["decile"]["spread_median"]
        m2 = B["cells"][k]["decile"]["spread_median"]
        d.append(y - x)
        p(f"| {k} | {x:.4f} | {y:.4f} | {y - x:+.4f} "
          f"| {m1 * 1e4:.1f} | {m2 * 1e4:.1f} |")
    p("")
    p(f"**ΔIC:** медиана {median(d):+.4f}, максимум по модулю "
      f"{max(d, key=abs):+.4f}\n")

    ca, cb = A.get("composition"), B.get("composition")
    if ca and cb:
        p("## Состав дециля\n")
        p(f"| Величина | нога | {args.a} | {args.b} |")
        p("|---|---|---|---|")
        for label, field, f in (
            ("Оборот, $/день", "turnover", lambda x: f"{x:,.0f}"),
            ("Доля баров со сделками", "share_traded", lambda x: f"{x:.4f}"),
            ("Возраст листинга, дней", "age_days", lambda x: f"{x:,.0f}"),
        ):
            for leg in ("long", "short", "universe"):
                p(f"| {label} | {leg} | {f(ca[leg][field])} "
                  f"| {f(cb[leg][field])} |")
        p("")


if __name__ == "__main__":
    main()
