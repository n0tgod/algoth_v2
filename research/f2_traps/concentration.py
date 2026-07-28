#!/usr/bin/env python3
"""
Замер к вопросу владельца: спасает ли стоп книгу carry?

Гипотеза F1–F3 провалилась не по доходности, а по хвосту: 11 % годовых
медианой при 30 % просадки. Ожидание положительное, распределение —
негодное. Ровно эту болезнь стоп и лечит, и вопрос «а если добавить
риск-менеджмент» законен.

Полная проверка стопа требует путей цен внутри периода удержания —
отдельный проход по хранилищу, часы на сервере. Здесь считается то, что
решает, стоит ли этот проход затевать, и считается из уже сохранённых
векторов F1.

Две меры, и вторая важнее
-------------------------

**1. Концентрация.** Просадка приходит от нескольких ног, рухнувших
глубоко, или от всех тридцати, поехавших вниз вместе? В первом случае
стоп её срежет, во втором — лишь зафиксирует те же убытки раньше.

**2. Потолок пользы от стопа.** Доходность каждой ноги за период
обрезается снизу на уровне `X`, и книга пересчитывается. Это
**оптимистичная** оценка, то есть верхняя граница пользы, и вот почему:

- нога, закрывшаяся ниже `X`, в реальности была бы выбита по цене не
  лучше `X` — здесь ей ставится ровно `X`;
- нога, чья цена **проваливалась** ниже `X` и успела вернуться, в
  реальности была бы выбита с убытком, а обрезание оставляет ей
  итоговый, лучший результат.

Второй эффект сильнее первого, поэтому настоящий стоп сработает **чаще**
и обойдётся **дороже**, чем это обрезание. Начисления при этом
сохраняются целиком, хотя выбитая нога перестала бы их получать, — ещё
одна поблажка в пользу стопа.

Если даже такой потолок не приводит просадку под 20 %, направление
закрыто без дорогого прогона. Это тот же приём, что закрыл вопрос о
мейкерском исполнении в §12.2 спеки 03: сначала недостижимо хорошая
оценка, потом недели работы — а не наоборот.

    python3 concentration.py --interval 1m
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
F1 = os.path.join(RESEARCH, "f1_carry", "out")

sys.path.insert(0, os.path.join(RESEARCH, "f1_carry"))
sys.path.insert(0, os.path.join(RESEARCH, "r5_backtest"))

import carry as CY           # noqa: E402
import stats as ST           # noqa: E402

KS = (7, 14)
HS = (5, 10)
WIDTHS = {"decile": 0.10, "quintile": 0.20}

WORST_N = 10                             # сколько худших периодов разбирать
STOPS = (0.50, 0.30, 0.20, 0.10)         # уровни обрезания, доля позиции
DD_LIMIT = 0.20                          # критерий §8.3 п. 7


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


def leg_pnl(w, price, fund, stop=None):
    """Вклад каждой ноги в результат книги, с обрезанием или без.

    Доходность выражается **в единицах позиции**: для шорта рост цены
    есть убыток, поэтому берётся `sign(w) · доходность`. Стоп в 20 %
    означает «позиция потеряла 20 %», а не «цена упала на 20 %», — так
    его и понимает трейдер.
    """
    ok = np.isfinite(price) & np.isfinite(fund)
    ww = np.where(ok, w, 0.0)
    s = np.sign(ww)
    ret = np.where(ok, s * price, 0.0)
    if stop is not None:
        ret = np.maximum(ret, -stop)
    # Начисления сохраняются целиком даже у обрезанной ноги — поблажка
    # в пользу стопа, названная в шапке.
    return np.abs(ww) * ret - ww * np.where(ok, fund, 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--funding-venue", default="bybit")
    a = ap.parse_args()
    tag = f"{a.interval}_{a.funding_venue}"

    vec = load_vectors(tag)
    dates = sorted(vec)
    out = {}

    for k in KS:
        for h in HS:
            for wname, width in WIDTHS.items():
                name = f"k{k}_h{h}_{wname}"
                days = dates[::h]
                per_period, legs_all, base = [], [], []
                stopped = {s: [] for s in STOPS}

                for day in days:
                    v = vec[day]
                    score = arr(v["score"], k)
                    price, fund = arr(v["price"], h), arr(v["funding"], h)
                    w, per_leg = CY.weights(score, width)
                    if per_leg < 1:
                        continue
                    p = leg_pnl(w, price, fund)
                    base.append(float(p.sum()))
                    per_period.append((day, p, w, price))
                    m = w != 0
                    legs_all.append(np.sign(w[m]) * price[m])
                    for s in STOPS:
                        stopped[s].append(
                            float(leg_pnl(w, price, fund, s).sum()))

                if len(base) < 10:
                    continue

                # --- концентрация худших периодов ---
                order = np.argsort(base)[:WORST_N]
                conc1, conc3, losers = [], [], []
                for i in order:
                    _, p, w, _ = per_period[i]
                    tot = float(p.sum())
                    if tot >= 0:
                        continue
                    srt = np.sort(p)                      # самые убыточные
                    conc1.append(float(srt[0]) / tot)
                    conc3.append(float(srt[:3].sum()) / tot)
                    losers.append(int((p < 0).sum()) / int((w != 0).sum()))

                flat = (np.concatenate(legs_all) if legs_all
                        else np.array([]))
                # Нога может получить вес и не иметь цены (актив
                # перестал торговаться внутри окна). В разложении она
                # выбывает; в статистике доходностей ног её тоже не
                # должно быть, иначе перцентили выходят NaN — поймал
                # смоук.
                flat = flat[np.isfinite(flat)]
                dd_base = ST.max_drawdown(base)["max_drawdown"]
                ppy = 365.0 / h

                row = {
                    "periods": len(base),
                    "worst_periods_used": len(conc1),
                    "share_of_loss_worst_leg": CY.robust(conc1),
                    # Доля может превысить 100 %: если три худшие ноги
                    # потеряли больше, чем весь убыток книги, значит
                    # остальные в том же периоде заработали. Это не
                    # ошибка, а признак сильной концентрации.
                    "share_of_loss_worst3_legs": CY.robust(conc3),
                    "share_of_legs_losing": CY.robust(losers),
                    "leg_return_p01": float(np.percentile(flat, 1)),
                    "leg_return_p05": float(np.percentile(flat, 5)),
                    "leg_return_median": float(np.median(flat)),
                    "leg_worst": float(flat.min()),
                    "leg_share_below_20pct": float((flat < -0.20).mean()),
                    "leg_share_below_50pct": float((flat < -0.50).mean()),
                    "base": {"drawdown": dd_base,
                             "annual": float(np.mean(base)) * ppy,
                             "sharpe": ST.sharpe(base, ppy)},
                    "stops": {},
                }
                for s in STOPS:
                    v2 = stopped[s]
                    row["stops"][str(s)] = {
                        "drawdown": ST.max_drawdown(v2)["max_drawdown"],
                        "annual": float(np.mean(v2)) * ppy,
                        "sharpe": ST.sharpe(v2, ppy),
                        "passes_dd": (ST.max_drawdown(v2)["max_drawdown"]
                                      >= -DD_LIMIT),
                    }
                out[name] = row

    doc = {"config": {"interval": a.interval, "funding_venue": a.funding_venue,
                      "worst_n": WORST_N, "stops": list(STOPS),
                      "dd_limit": DD_LIMIT},
           "cells": out}
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"concentration_{tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print("КОНЦЕНТРАЦИЯ УБЫТКА в худших периодах\n")
    print(f"{'ячейка':<20}{'худшая нога':>13}{'три худшие':>12}"
          f"{'ног в минусе':>14}{'1-й проц. ноги':>16}{'ног хуже −20 %':>16}")
    for n in sorted(out):
        c = out[n]
        print(f"{n:<20}{c['share_of_loss_worst_leg']:>12.0%}"
              f"{c['share_of_loss_worst3_legs']:>12.0%}"
              f"{c['share_of_legs_losing']:>14.0%}"
              f"{c['leg_return_p01']:>15.1%}"
              f"{c['leg_share_below_20pct']:>16.2%}")

    def cell_text(stat, mark=" "):
        return mark + "{:.1%} ({:.0%})".format(stat["drawdown"],
                                               stat["annual"])

    print("\n\nПОТОЛОК ПОЛЬЗЫ ОТ СТОПА — просадка (годовая доходность)\n")
    head = "".join("{:>18}".format("стоп {:.0%}".format(s)) for s in STOPS)
    print("{:<20}{:>18}{}".format("ячейка", "без стопа", head))
    for n in sorted(out):
        c = out[n]
        line = "{:<20}{:>18}".format(n, cell_text(c["base"]))
        for s in STOPS:
            x = c["stops"][str(s)]
            line += "{:>18}".format(cell_text(x, "*" if x["passes_dd"]
                                              else " "))
        print(line)
    print("\n* — просадка укладывается в критерий §8.3 п. 7 (≤ 20 %).")
    print("Обрезание оптимистично: настоящий стоп срабатывает чаще и "
          "обходится дороже.")
    print(f"\nзаписано {dst}")


if __name__ == "__main__":
    main()
