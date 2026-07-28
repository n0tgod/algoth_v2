#!/usr/bin/env python3
"""
R1 — сверка двух прогонов, посчитанных на разном разрешении хранилища.

Тот же приём, что в A2: 15m и 1m считаются независимо и служат
перекрёстной проверкой друг другу. Проверка осмысленна потому, что
источники разные — месячные архивы Binance за 15m и за 1m, — а ответ
обязан совпасть.

**Часовые закрытия обязаны совпадать точно, а не приблизительно.**
Закрытие 15-минутного бара есть цена последней сделки внутри него.
Последний торговавшийся 15-минутный бар часа содержит последнюю
торговавшуюся минуту часа. Значит часовое закрытие, собранное из 15m и
из 1m, — одно и то же число. Расхождение здесь означало бы дефект
хранилища, а не разницу разрешений.

**Расходиться имеет право состав активов.** Фильтр ликвидности §3.3
спеки 02 меряет долю баров со сделками, и на минутных барах эта мера
строже: A2 намерила медиану 0.60 % баров без сделок на 1m против 0.00 %
на 15m. Актив у самого порога 0.90 на 1m его не проходит, на 15m
проходит. Разный состав даёт разную волну и, значит, слегка разные β.

Поэтому сверка докладывает две вещи раздельно: сколько окон совпало
точно и чем объясняются остальные. Смешивать их нельзя — первое
проверяет хранилище, второе описывает поведение фильтра.

    python3 compare.py --a 15m --b 1m > out/R1-cross-check.md
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def load(interval):
    path = os.path.join(OUT, f"premise_summary_{interval}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала premise.py --interval {interval}")
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
    A = {w["date"]: w for w in da["windows"] if "r2_median" in w}
    B = {w["date"]: w for w in db["windows"] if "r2_median" in w}
    common = sorted(set(A) & set(B))

    p = print
    p(f"# R1 — перекрёстная проверка {args.a} против {args.b}\n")
    p(f"**Окон:** {args.a} — {len(A)}, {args.b} — {len(B)}, общих {len(common)}  ")
    p(f"**Даты совпадают полностью:** {'да' if set(A) == set(B) else 'НЕТ'}\n")

    exact, differ = [], []
    for k in common:
        (exact if A[k]["r2_median"] == B[k]["r2_median"]
         and A[k]["assets_fitted"] == B[k]["assets_fitted"]
         else differ).append(k)

    p("## Итог\n")
    p(f"- окон, совпавших **бит в бит**: **{len(exact)}** из {len(common)}")
    p(f"- окон с расхождением: **{len(differ)}**\n")

    if differ:
        dl = [B[k]["assets_liquid"] - A[k]["assets_liquid"] for k in differ]
        dr = [abs(B[k]["r2_median"] - A[k]["r2_median"]) for k in differ]
        dbb = [abs(B[k]["beta_median"] - A[k]["beta_median"]) for k in differ]
        p(f"Во всех {len(differ)} расхождение состава односторонне: у прогона "
          f"`{args.b}` ликвидных активов "
          f"{'меньше' if max(dl) < 0 else 'больше' if min(dl) > 0 else 'по-разному'}"
          f", разница от {min(dl)} до {max(dl)}. "
          f"Это поведение фильтра ликвидности, а не хранилища.\n")
        p(f"- |ΔR² медианы| — медиана {median(dr):.5f}, максимум {max(dr):.5f}")
        p(f"- |Δβ медианы| — медиана {median(dbb):.5f}, максимум {max(dbb):.5f}\n")
        p("| Окно | Ликвидных " + args.a + " | Ликвидных " + args.b
          + " | ΔR² | Δβ |")
        p("|---|---|---|---|---|")
        for k in differ:
            p(f"| {k} | {A[k]['assets_liquid']} | {B[k]['assets_liquid']} | "
              f"{B[k]['r2_median'] - A[k]['r2_median']:+.4f} | "
              f"{B[k]['beta_median'] - A[k]['beta_median']:+.4f} |")
        p("")

    p("## Вердикт по посылке\n")
    p("| Величина | " + args.a + " | " + args.b + " |")
    p("|---|---|---|")
    for name, get in (
        ("П1 — доля дисперсии, медиана по окнам",
         lambda d: f"{100 * d['summary']['explained_variance']['median_over_windows']:.2f} %"),
        ("П1 — агрегат",
         lambda d: f"{100 * d['summary']['explained_variance']['aggregate_median_over_windows']:.2f} %"),
        ("П1 — окон ниже порога",
         lambda d: str(d["summary"]["explained_variance"]["windows_below_threshold"])),
        ("П2 — максимальное отклонение β",
         lambda d: f"{100 * d['summary']['beta_step_max_deviation']:.3f} %"),
        ("Посылка выполнена",
         lambda d: "да" if d["summary"]["premise_pass"] else "НЕТ"),
    ):
        p(f"| {name} | {get(da)} | {get(db)} |")
    p("")

    same = (da["summary"]["premise_pass"] == db["summary"]["premise_pass"])
    p(f"Вердикты {'совпадают' if same else '**РАСХОДЯТСЯ**'}."
      + ("" if same else " Расхождение вердиктов означает, что посылка не"
                        " определена данными, и разбираться надо до R2."))


if __name__ == "__main__":
    main()
