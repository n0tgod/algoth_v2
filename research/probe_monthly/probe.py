#!/usr/bin/env python3
"""Зонд месячного горизонта кросс-секции.

Выбор владельца из карты направлений (№2). Сетка R-серии кончалась на
10 днях удержания; IC возврата на 30-дневном форварде уже измерен и
положителен (+0.0324 при k=7, +0.0467 при k=14 — сцепленные форварды,
запись в IDEAS.md), но КНИГА на месячном удержании не строилась ни
разу: спред в деньгах, оборот, издержки, доля прибыльных сечений и
хвост не мерились. Арифметика, ради которой зонд существует: месячное
удержание платит круг издержек ОДИН раз за 30 дней — если спред дециля
и правда ~100 б.п. за месяц, покрытие втрое-впятеро, чего не было ни у
одной из закрытых конструкций.

Это зонд, не гипотеза: порогов и вердикта нет, пространство объявлено
до прогона, решение за владельцем.

Устройство: пересчёт СОХРАНЁННЫХ векторов R2, без прохода по хранилищу
--------------------------------------------------------------------
`crosssection.py` сохранил на каждую дату ребаланса вектор сигналов
(k ∈ {1,3,7,14}) и форвардов (h ∈ {1,3,5,10}) вместе с именами. Из них
собираются и длинные формации, и месячный форвард — СЦЕПЛЕНИЕМ
10-дневных кирпичей по календарю:

    сигнал k=30 даты t  = −( fwd10(t−30) + fwd10(t−20) + fwd10(t−10) )
    форвард h=30 даты t =    fwd10(t) + fwd10(t+10) + fwd10(t+20)

Знак сигнала — конвенция R2: положительный сигнал означает «отстал от
волны», ставка на возврат. Выравнивание кирпичей — ПО ИМЕНИ, не по
индексу: состав сечения меняется от даты к дате, и позиционное
сцепление молча сложило бы остатки разных активов (класс дефекта
`basket_spread` §5.2). Имя, отсутствующее хотя бы в одном кирпиче или
несущее NaN, получает NaN — пропуск, а не ноль.

Ловушки, названные до прогона:
- кирпичи форварда считаны каждый по СВОЕЙ β (β переоценивается на
  каждую дату). `path_norm` мерил цену этого на k ≤ 14: ранговое
  согласие 0.9996–1.0000, расхождение величины 0.5–2.9 %; на 90 днях
  оно больше и здесь не измеряется — оговорка, не поправка;
- смещение выживших: имя обязано жить все k+30 дней; доля доживших
  печатается. Делистинг ВНУТРИ форварда выбрасывает имя из меры, а в
  живой книге нога закрылась бы по последней цене — не моделируется;
- издержки — модальный тейкер 5.5 б.п. на ногу (посимвольная ставка —
  дело спеки, не зонда); единицы — конвенция R4: Σ|w| = 1, прибыль
  книги = ½ спреда дециля, комиссия = Σ|Δw| × тейкер, полная замена
  книги = 11 б.п.;
- медиана И среднее спреда печатаются обе (Z1: расходятся в знаке у
  целых семейств).

Запуск (на VPS, где лежат векторы прогона R2 1m):

    python3 research/probe_monthly/probe.py --interval 1m --tag 30d
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta, datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import residual as RS                                     # noqa: E402
import nulls as N                                         # noqa: E402
import run_d1 as R                                        # noqa: E402

# --- объявлено до прогона ---------------------------------------------
BRICK = 10                   # кирпич сцепления — самый длинный форвард R2
KS = (14, 30, 60, 90)        # формация сигнала, дни
HS = (10, 30)                # удержание: 10 — мост к сетке R2, 30 — предмет
WIDTH = 0.10                 # дециль, главная ширина R2
TAKER_BP = 5.5               # модальный тейкер A1; круг ноги 11
SEEDS = (1, 2, 3, 4, 5)      # нуль 1, зонд; у гипотезы будет 10
MAIN_CELL = "k14_h30"        # главная ячейка: единственная с внешним
#                              измерением (IC +0.0467 сцепленных
#                              форвардов, IDEAS.md) — зонд добавляет к
#                              ней книгу и издержки


def shift(day, days):
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def name_index(vec, day, cache):
    if day not in cache:
        cache[day] = {n: i for i, n in enumerate(vec[day]["names"])}
    return cache[day]


def aligned(vec, cache, base_names, day, kind, key):
    """Вектор `kind[key]` даты `day`, выровненный по `base_names`.

    По ИМЕНИ: состав сечения меняется от даты к дате, позиционное
    выравнивание сложило бы остатки разных активов. Отсутствующее имя —
    NaN, пропуск.
    """
    idx = name_index(vec, day, cache)
    arr = vec[day][kind][key]
    out = np.full(len(base_names), np.nan)
    for j, n in enumerate(base_names):
        i = idx.get(n)
        if i is not None:
            out[j] = arr[i]
    return out


def chain(vec, cache, base_names, days):
    """Сумма fwd10 по датам `days`, выровненная по `base_names`.

    Любая дата вне сетки → None (сцеплять через дыру нельзя — класс
    дефекта L2/W2: окно по номеру точки через дыру означает месяц).
    """
    total = np.zeros(len(base_names))
    for d in days:
        if d not in vec:
            return None
        total = total + aligned(vec, cache, base_names, d, "fwd", BRICK)
    return total


def build_signal(vec, cache, t, k):
    """Сигнал формации k на дату t, в нумерации names(t).

    k=14 берётся из сохранённого сигнала R2 напрямую; длинные —
    сцеплением ПРОШЛЫХ кирпичей со знаком минус (конвенция R2:
    положительный сигнал = отстал от волны)."""
    base = vec[t]["names"]
    if k in vec[t]["sig"]:
        return np.asarray(vec[t]["sig"][k], dtype=np.float64)
    days = [shift(t, -k + BRICK * i) for i in range(k // BRICK)]
    got = chain(vec, cache, base, days)
    return None if got is None else -got


def build_forward(vec, cache, t, h):
    """Форвард h дней на дату t, в нумерации names(t)."""
    if h in vec[t]["fwd"]:
        return np.asarray(vec[t]["fwd"][h], dtype=np.float64)
    days = [shift(t, BRICK * i) for i in range(h // BRICK)]
    return chain(vec, cache, vec[t]["names"], days)


def book_weights(sig, fwd, width=WIDTH):
    """Веса книги даты: Σ|w| = 1, дециль равновзвешенный внутри ноги.

    Возвращает dict имя → вес либо None (сечение тоньше дециля)."""
    b = RS.basket_spread(sig, fwd, width)
    return b


def turnover(prev_w, cur_w):
    """Σ|Δw| двух книг (имя → вес); полная замена = 2."""
    names = set(prev_w) | set(cur_w)
    return float(sum(abs(cur_w.get(n, 0.0) - prev_w.get(n, 0.0))
                     for n in names))


def build_pairs(vec, cache, dates, k, h, counters):
    """Пары (дата, сигнал, форвард) ячейки. Строятся ОДИН раз: нуль
    отличается от прогона ровно тем, как сопоставлены два вектора, и
    ничем больше (принцип R3) — пересборка под каждое зерно была бы и
    расточительной, и лишней степенью свободы."""
    pairs = []
    for t in dates:
        sig = build_signal(vec, cache, t, k)
        if sig is None:
            counters["нет прошлого для сигнала"] += 1
            continue
        fwd = build_forward(vec, cache, t, h)
        if fwd is None:
            counters["нет будущего для форварда"] += 1
            continue
        pairs.append((t, sig, fwd))
    return pairs


def measure_pairs(vec, pairs, counters, seed=None):
    """Мера ячейки по готовым парам. `seed` — нуль 1: перестановка
    сигнала внутри сечения, зерно на ДАТУ (`RS.seed_for` — урок R3:
    невоспроизводимый нуль не является проверяемым)."""
    ics, spreads, nets, turns, coverage = [], [], [], [], []
    prev_w = None
    for t, sig, fwd in pairs:
        if seed is not None:
            rng = np.random.default_rng(RS.seed_for(seed, t))
            sig = rng.permutation(sig)
        ic, n = RS.spearman(sig, fwd)
        if ic is None:
            counters["сечение вырождено"] += 1
            continue
        b = RS.basket_spread(sig, fwd, WIDTH)
        if b is None:
            counters["дециль вырождается"] += 1
            continue
        ics.append(ic)
        spreads.append(b["spread"])
        coverage.append(n / len(vec[t]["names"]))
        names = vec[t]["names"]
        w = {}
        for i in b["long_idx"]:
            w[names[i]] = 0.5 / len(b["long_idx"])
        for i in b["short_idx"]:
            w[names[i]] = -0.5 / len(b["short_idx"])
        tr = turnover(prev_w, w) if prev_w is not None else 1.0
        prev_w = w
        turns.append(tr)
        nets.append(b["spread"] * 1e4 / 2.0 - tr * TAKER_BP)
    if not ics:
        return None
    sp_bp = [s * 1e4 for s in spreads]
    mean_ic, t_ic, n_ic = RS.tstat(ics)
    mean_net, t_net, _ = RS.tstat(nets)
    return {
        "sections": n_ic, "ic_mean": round(mean_ic, 4),
        "ic_t": round(t_ic, 2) if t_ic is not None else None,
        "ic_pos_share": round(float(np.mean(np.array(ics) > 0)), 3),
        "spread_median_bp": round(float(np.median(sp_bp)), 1),
        "spread_mean_bp": round(float(np.mean(sp_bp)), 1),
        "turnover_mean": round(float(np.mean(turns)), 3),
        "cost_mean_bp": round(float(np.mean(turns)) * TAKER_BP, 1),
        "net_median_bp": round(float(np.median(nets)), 1),
        "net_mean_bp": round(mean_net, 1),
        "net_t": round(t_net, 2) if t_net is not None else None,
        "net_pos_share": round(float(np.mean(np.array(nets) > 0)), 3),
        "net_worst_bp": round(float(np.min(nets)), 1),
        "coverage_median": round(float(np.median(coverage)), 3),
    }


def run_grid(vec, dates_all, counters):
    """Все ячейки k×h по непересекающимся сечениям (шаг h по списку дат
    — конвенция R3: перекрытие окон обесценило A4). Возвращает и пары —
    нули считаются по ним же."""
    cache = {}
    cells, all_pairs = {}, {}
    for k in KS:
        for h in HS:
            pairs = build_pairs(vec, cache, dates_all[::h], k, h,
                                counters)
            got = measure_pairs(vec, pairs, counters)
            if got:
                cells[f"k{k}_h{h}"] = got
                all_pairs[f"k{k}_h{h}"] = pairs
    return cells, all_pairs


def run_nulls(vec, all_pairs, counters):
    """Нуль 1 для каждой ячейки по ТЕМ ЖЕ парам, что прогон."""
    out = {}
    for key, pairs in all_pairs.items():
        per_seed = []
        for s in SEEDS:
            got = measure_pairs(vec, pairs, counters, seed=s)
            if got:
                per_seed.append(got["ic_mean"])
        if per_seed:
            out[key] = {
                "ic_mean_seeds": round(float(np.mean(per_seed)), 4),
                "ic_max_seeds": round(float(np.max(per_seed)), 4),
                "seeds": len(per_seed)}
    return out


def verdict_phrase(cell):
    """Фраза выводится ИЗ чисел главной ячейки (урок Z2)."""
    if cell is None:
        return "главная ячейка не измерена — фразы нет"
    net, cost = cell["net_mean_bp"], cell["cost_mean_bp"]
    gross = cell["spread_mean_bp"] / 2.0
    if net > 0 and cell["net_median_bp"] > 0:
        return (f"месячная книга живёт по обеим мерам: нетто в среднем "
                f"{net:+.1f} б.п. за 30 дней (медиана "
                f"{cell['net_median_bp']:+.1f}) при издержках "
                f"{cost:.1f} — брутто {gross:+.1f} покрывает круг в "
                f"{gross / cost:.1f} раза")
    if net > 0 or cell["net_median_bp"] > 0:
        return (f"месячная книга живёт ТОЛЬКО одной мерой: среднее "
                f"{net:+.1f}, медиана {cell['net_median_bp']:+.1f} б.п. "
                f"— расхождение знака есть подпись хвоста, вердикта нет")
    return (f"месячная книга не окупается: нетто в среднем {net:+.1f} "
            f"б.п. за 30 дней (медиана {cell['net_median_bp']:+.1f}) "
            f"при издержках {cost:.1f}")


def report(art, path):
    a = art
    L = ["# Зонд: месячный горизонт кросс-секции\n",
         f"Прогон: {a['run_at']}, векторы R2 `{a['interval']}` "
         f"({a['dates']} дат {a['date_first']} … {a['date_last']}). "
         "Зонд, не гипотеза: порогов нет, решение за владельцем.\n",
         "Пересчёт сохранённых векторов R2: длинные формации и месячный "
         "форвард собраны сцеплением 10-дневных кирпичей по календарю, "
         "выравнивание по имени. Единицы — конвенция R4: Σ|w| = 1, "
         "прибыль книги = ½ спреда дециля, комиссия = оборот × "
         f"{TAKER_BP} б.п., полная замена книги = 11 б.п.\n",
         f"**{a['verdict']}**\n",
         "## Сетка (по непересекающимся сечениям)\n",
         "| k, дн | h, дн | сечений | IC | t | IC>0 | спред мед. | "
         "спред ср. | оборот | издержки | нетто мед. | нетто ср. | t | "
         "нетто>0 | худшее | дожило |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
         "---|---|"]
    for k in KS:
        for h in HS:
            c = a["cells"].get(f"k{k}_h{h}")
            if c is None:
                L.append(f"| {k} | {h} | — | — | — | — | — | — | — | — "
                         f"| — | — | — | — | — | — |")
                continue
            mark = " **⟵**" if f"k{k}_h{h}" == MAIN_CELL else ""
            L.append(
                f"| {k} | {h} | {c['sections']} | {c['ic_mean']:+.4f} | "
                f"{c['ic_t']} | {c['ic_pos_share']:.2f} | "
                f"{c['spread_median_bp']:+.1f} | {c['spread_mean_bp']:+.1f} | "
                f"{c['turnover_mean']:.2f} | {c['cost_mean_bp']:.1f} | "
                f"{c['net_median_bp']:+.1f} | {c['net_mean_bp']:+.1f} | "
                f"{c['net_t']} | {c['net_pos_share']:.2f} | "
                f"{c['net_worst_bp']:+.1f} | {c['coverage_median']:.2f}"
                f"{mark} |")
    L += ["",
          "Спред и нетто — б.п. за период удержания; «дожило» — медиана "
          "доли имён сечения, у которых существуют и полный сигнал, и "
          "полный форвард (смещение выживших).\n",
          "## Нуль 1: перестановка сигнала внутри сечения "
          f"({len(SEEDS)} зёрен)\n",
          "| ячейка | IC прогона | IC нуля (ср.) | IC нуля (макс) |",
          "|---|---|---|---|"]
    for key, nv in sorted(a["nulls"].items()):
        c = a["cells"].get(key)
        L.append(f"| {key} | "
                 f"{c['ic_mean']:+.4f} | {nv['ic_mean_seeds']:+.4f} | "
                 f"{nv['ic_max_seeds']:+.4f} |" if c else
                 f"| {key} | — | {nv['ic_mean_seeds']:+.4f} | "
                 f"{nv['ic_max_seeds']:+.4f} |")
    L += ["", "## Пропуски\n"]
    for kk, v in sorted(a["skipped"].items()):
        L.append(f"- {kk}: {v}")
    L += ["", "## Оговорки, не снимаемые замером\n",
          "- кирпичи форварда считаны каждый по СВОЕЙ β; на k ≤ 14 "
          "path_norm мерил цену — ранговое согласие 0.9996–1.0000, "
          "расхождение 0.5–2.9 %; на 90 днях оно больше и здесь не "
          "измеряется;",
          "- смещение выживших: имя обязано жить k+h дней; делистинг "
          "внутри форварда выбрасывает имя из меры, живая книга закрыла "
          "бы ногу по последней цене;",
          "- издержки модальным тейкером 5.5, не посимвольно; funding "
          "удержания в 30 дней в числах НЕТ вовсе — на месячном "
          "удержании он значим (A1: медиана дифференциала 19.7 % "
          "годовых) и обязан войти в спеку, если она будет;",
          "- сцепление даёт сигнал только на датах, где все кирпичи "
          "существуют: ранние даты сетки выпадают у длинных формаций."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="30d")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    t0 = time.time()
    vec = N.load_vectors(a.interval)
    dates_all = sorted(vec)
    print(f"векторов {len(dates_all)} дат "
          f"({dates_all[0]} … {dates_all[-1]})")

    counters = {k: 0 for k in (
        "нет прошлого для сигнала", "нет будущего для форварда",
        "сечение вырождено", "дециль вырождается")}
    cells, all_pairs = run_grid(vec, dates_all, counters)
    if not cells:
        for k, v in sorted(counters.items()):
            print(f"  пропуск — {k}: {v}")
        raise SystemExit("ни одной измеренной ячейки — причины выше")
    null_counters = {k: 0 for k in counters}
    nulls = run_nulls(vec, all_pairs, null_counters)

    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "interval": a.interval, "dates": len(dates_all),
        "date_first": dates_all[0], "date_last": dates_all[-1],
        "ks": list(KS), "hs": list(HS), "width": WIDTH,
        "taker_bp": TAKER_BP, "seeds": list(SEEDS),
        "main_cell": MAIN_CELL,
        "cells": cells, "nulls": nulls, "skipped": counters,
        "verdict": verdict_phrase(cells.get(MAIN_CELL)),
        "took_min": round((time.time() - t0) / 60, 1),
    }
    p = os.path.join(a.out, f"MONTHLY-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"MONTHLY-{a.tag}.md"))
    print(f"готово: {p} ({art['took_min']} мин)")
    print(f"  {art['verdict']}")
    if not a.no_publish:
        R.publish(f"зонд месячного горизонта кросс-секции ({a.tag})")


if __name__ == "__main__":
    main()
