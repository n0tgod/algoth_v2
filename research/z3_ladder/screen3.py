#!/usr/bin/env python3
"""Z3 — скрин по лесенке: снятие, смерть и восполнение КОНКРЕТНЫХ цен.

Чем это отличается от Z2, и почему ноль Z2 лесенку не закрывает
--------------------------------------------------------------

Z2 меряет снятие по ПОЛОСЕ ±0.25 %, привязанной к середине, а середина
движется: часть «снятия» на резком ходе есть смещение полосы, а не уход
заявок. Отчёт Z2 сам это называет, и потому его ноль — свойство
загрязнённой меры, а не лесенки. Здесь величины считаются по каждой
цене между соседними снимками:

* `cancel` — убыль уровня, НЕ объяснённая сделкой на этой же цене;
* `dead` — уровень ушёл в ноль, не увидев ни одного принта;
* `refill` — на цене, где была сделка, объём подставили заново; это тот
  самый ЗНАМЕНАТЕЛЬ, которого не было у четырёх замеров ленты T1–T4:
  они видели, сколько агрессии прошло, и не видели, подставляли ли
  уровень обратно;
* `sweep` — съеденный нотионал на базисный пункт хода середины.

Что откуда берётся
------------------

Событие — со склада ЛЕСЕНКИ (`z3_ladder/out/store`). Цена форварда и
одновременная кросс-секция — с минутного склада Z2 по тем же суткам и
тем же минутам. Оба склада — свёртка ОДНОЙ записи одного сборщика, то
есть площадка, часы и универсум общие: подмены источника, из-за которой
базис площадок вошёл бы в разность как эдж (урок T2), здесь нет.

Судит ядро Z1 — то же, что у Z1 и Z2: корзины длиной в горизонт,
перестановочный нуль, семейственная планка по Z, согласие МЕДИАНЫ и
СРЕДНЕГО и круг издержек нейтральной книги 22 б.п. Второй копии судьи
нет: разойдись они, две таблицы спорили бы об одном рынке.

Контроль — СРЕДНЕЕ сечения, а не медиана: медиана есть статистика, а не
портфель, и превышение над ней несёт снос, не зависящий от условия
(Z1 намерил +10.7 б.п. на любой лонг за четыре часа).

Запуск:

    cd ~/algoth_v2 && mkdir -p research/z3_ladder/out
    cd ~/algoth_v2 && setsid nohup nice -n 19 .venv/bin/python \\
        research/z3_ladder/screen3.py --tag 1m \\
        > research/z3_ladder/out/screen.log 2>&1 &
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(ROOT, "research", "z2_book"),
          os.path.join(ROOT, "research", "z1_screen"),
          os.path.join(ROOT, "research", "b1_book")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fold as F                                          # noqa: E402
import fold_ladder as FL                                  # noqa: E402
import ladder as LD                                       # noqa: E402
import probe as P2                                        # noqa: E402
import screen as Z                                        # noqa: E402

OUT = os.path.join(HERE, "out")
STORE = os.path.join(HERE, "out", "store")

# Горизонты те же, что у Z2: лесенка обязана быть ЧИСТОЙ версией той же
# меры, и сравнивать их можно только на одной сетке горизонтов.
HORIZONS = P2.HORIZONS

# Порог ЗАМЕРА, а не склада: минута с малым числом пар снимков —
# пропуск, а не наблюдение. Склад хранит `pairs` и маску не кладёт,
# чтобы смена порога не требовала пересвёртки (правило Z2).
MIN_PAIRS = 30

# Норма символа считается по ВЧЕРАШНИМ суткам и только там, где вчера
# было хотя бы столько минут: норма по тем же суткам знала бы будущее
# внутри дня, а норма по трём минутам — не норма.
NORM_MIN_MIN = 120


def log_(m):
    print(m, flush=True)


def day_ladder(syms, day, log=log_):
    """Матрицы лесенки за сутки со своего склада. Нет склада — None."""
    got = F.read_day(day, syms, fields=LD.FIELDS, store=STORE, log=log,
                     version=FL.VERSION)
    if got is None:
        return None
    # Порог замера: тонкая минута становится пропуском ВЕЗДЕ, а не
    # только там, где мы вспомнили о нём.
    thin = ~(got["pairs"] >= MIN_PAIRS)
    for f in LD.FIELDS:
        got[f] = np.where(thin, np.nan, got[f])
    return got


def norms(prev):
    """Собственные нормы символа по вчерашней лесенке.

    Нормируется только `sweep`: остальные величины уже безразмерны —
    они считаются в долях ПОКАЗАННОГО нотионала той же минуты, и делить
    их на вчерашний уровень значило бы мерить две вещи разом.
    """
    if prev is None:
        return None
    out = {}
    for f in ("sweep", "vis_b", "vis_a", "eat_b", "eat_a"):
        with np.errstate(invalid="ignore"):
            med = np.nanmedian(prev[f], axis=1)
        cnt = np.isfinite(prev[f]).sum(axis=1)
        med[cnt < NORM_MIN_MIN] = np.nan
        med[~np.isfinite(med) | (med <= 0)] = np.nan
        out[f] = med[:, None]
    return out


def primitives(L, N):
    """Признаки лесенки в долях показанного — и в разах от своей нормы."""
    p = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        vb, va = L["vis_b"], L["vis_a"]
        both = vb + va
        p["cancel_b"] = L["cancel_b"] / vb
        p["cancel_a"] = L["cancel_a"] / va
        p["dead_b"] = L["dead_b"] / vb
        p["dead_a"] = L["dead_a"] / va
        p["eat_b"] = L["eat_b"] / vb
        p["eat_a"] = L["eat_a"] / va
        p["add_b"] = L["add_b"] / vb
        p["add_a"] = L["add_a"] / va
        # Восполнение против СЪЕДЕННОГО: единица означает, что уровень
        # подставили ровно столько, сколько с него сняли сделками.
        p["refill_b"] = L["refill_b"] / L["eat_b"]
        p["refill_a"] = L["refill_a"] / L["eat_a"]
        # Съеденный нотионал на базисный пункт хода — в разах от своей
        # нормы: «дорого ли двигают эту монету» несравнимо между BTC и
        # мелким альтом в абсолюте.
        p["sweep_rel"] = L["sweep"] / N["sweep"]
        # Съеденное — в РАЗАХ от обычного для этого символа, а не в
        # долях показанного: показанное считается по всей лесенке и по
        # всем парам минуты, поэтому `eat/vis` имеет медиану ноль и
        # 99-й процентиль 0.002 (замер по 780 тыс. символо-минут).
        # Порог в долях показанного не сработал бы никогда — и в
        # отчёте это выглядело бы как «эффекта нет».
        p["eat_b_rel"] = L["eat_b"] / N["eat_b"]
        p["eat_a_rel"] = L["eat_a"] / N["eat_a"]
        # Асимметрии считаются от ОБЩЕГО показанного, а не от своей
        # стороны: иначе тонкая сторона даёт огромную долю на пустом
        # месте.
        p["cancel_skew"] = (L["cancel_b"] - L["cancel_a"]) / both
        p["eat_skew"] = (L["eat_a"] - L["eat_b"]) / both
        p["vis_b_rel"] = vb / N["vis_b"]
        p["vis_a_rel"] = va / N["vis_a"]
    return p


def build_conditions():
    """Пространство объявляется ЦЕЛИКОМ здесь и после прогона не растёт.

    Пороги ОТКАЛИБРОВАНЫ по распределению самих признаков на сутках
    2026-08-04…06 (780 тыс. символо-минут в сутки, 546 имён), режимом
    `--stats`, то есть без единого взгляда на исходы. Это законная
    калибровка: подгонкой было бы двигать их, увидев доходности.
    Дальше они не двигаются.

    Что калибровка изменила против первого черновика, и почему это не
    косметика:

    * условия по `dead` СНЯТЫ — величина равна нулю во всех 2.3 млн
      минут. Уровень, ушедший в ноль, площадка убирает из лесенки, а не
      публикует нулевым размером: это структурный ноль МЕРЫ, а не
      рынка, и в отчёте он выглядел бы как «эффекта нет»;
    * пороги по съеденному переведены в РАЗЫ от нормы символа: доля
      `eat/vis` имеет медиану 0 и 99-й процентиль 0.002, так что любой
      порог «съедена половина показанного» не сработал бы никогда, а
      парный ему «их почти не ели» выполнялся бы всегда;
    * порог снятия опущен 0.5 → 0.15 и 0.30: это 99-й и 99.9-й
      процентили доли, то есть событие редкое, но существующее.
    """
    C = []

    def add(name, side, fn, group):
        C.append({"name": name, "side": side, "fn": fn, "group": group})

    for s in (+1, -1):
        # Снятие: ушло, не будучи тронутым. 0.15 — 99-й процентиль
        # доли, 0.30 — 99.9-й.
        add("сняли 15 % показанных бидов", s,
            lambda p: p["cancel_b"] >= 0.15, "снятие")
        add("сняли 15 % показанных асков", s,
            lambda p: p["cancel_a"] >= 0.15, "снятие")
        add("сняли 30 % показанных бидов", s,
            lambda p: p["cancel_b"] >= 0.30, "снятие")
        add("сняли 30 % показанных асков", s,
            lambda p: p["cancel_a"] >= 0.30, "снятие")
        # Самый чистый случай: сняли, хотя ели МЕНЬШЕ обычного.
        add("биды растворились, ели меньше обычного", s,
            lambda p: (p["cancel_b"] >= 0.15) & (p["eat_b_rel"] <= 0.5),
            "снятие")
        add("аски растворились, ели меньше обычного", s,
            lambda p: (p["cancel_a"] >= 0.15) & (p["eat_a_rel"] <= 0.5),
            "снятие")
        # Восполнение: тот знаменатель, которого не было у ленты.
        # Гейт по съеденному — в разах от нормы, иначе отношение
        # считается на пустом месте.
        add("выеденные биды подставляют заново", s,
            lambda p: (p["refill_b"] >= 1.0) & (p["eat_b_rel"] >= 1.0),
            "восполнение")
        add("выеденные аски подставляют заново", s,
            lambda p: (p["refill_a"] >= 1.0) & (p["eat_a_rel"] >= 1.0),
            "восполнение")
        add("биды едят и НЕ подставляют", s,
            lambda p: (p["refill_b"] <= 0.1) & (p["eat_b_rel"] >= 1.0),
            "восполнение")
        add("аски едят и НЕ подставляют", s,
            lambda p: (p["refill_a"] <= 0.1) & (p["eat_a_rel"] >= 1.0),
            "восполнение")
        # Выедание против обычного для этого символа.
        add("биды едят втрое сильнее обычного", s,
            lambda p: p["eat_b_rel"] >= 3.0, "выедание")
        add("аски едят втрое сильнее обычного", s,
            lambda p: p["eat_a_rel"] >= 3.0, "выедание")
        add("биды едят вдесятеро сильнее обычного", s,
            lambda p: p["eat_b_rel"] >= 10.0, "выедание")
        add("аски едят вдесятеро сильнее обычного", s,
            lambda p: p["eat_a_rel"] >= 10.0, "выедание")
        # Цена хода в снесённом нотионале.
        add("двигают дорого: втрое больше нотионала на б.п.", s,
            lambda p: p["sweep_rel"] >= 3, "цена хода")
        add("двигают дёшево: втрое меньше нотионала на б.п.", s,
            lambda p: (p["sweep_rel"] <= 0.33) & (p["sweep_rel"] > 0),
            "цена хода")
        # Асимметрии сторон.
        add("снимают биды, а не аски", s,
            lambda p: p["cancel_skew"] >= 0.3, "перекос")
        add("снимают аски, а не биды", s,
            lambda p: p["cancel_skew"] <= -0.3, "перекос")
        add("едят аски, а не биды", s,
            lambda p: p["eat_skew"] >= 0.3, "перекос")
        add("едят биды, а не аски", s,
            lambda p: p["eat_skew"] <= -0.3, "перекос")
        # Показанное против своей нормы — контрольная группа: то же
        # есть в Z2, и совпадение подтверждает, что склады описывают
        # один рынок.
        add("показанные биды вдвое тоньше нормы", s,
            lambda p: p["vis_b_rel"] <= 0.5, "показанное")
        add("показанные аски вдвое тоньше нормы", s,
            lambda p: p["vis_a_rel"] <= 0.5, "показанное")
    return C


def twin_of(name):
    """Имя условия для ДРУГОЙ стороны книги, или None.

    Нужно для главной диагностики отчёта: если условие и его близнец
    дают один и тот же знак, триггер выбирает не направление, а
    СОСТОЯНИЕ — и таблица описывает поведение рынка в такие минуты, а
    не сведение из лесенки. Тот же класс, что асимметрия хода в T1,
    которую я едва не прочёл как эдж.
    """
    pairs = (("бидов", "асков"), ("биды", "аски"), ("Биды", "Аски"))
    for a, b in pairs:
        if a in name:
            return name.replace(a, b)
        if b in name:
            return name.replace(b, a)
    return None


CONDITIONS = build_conditions()
CONDS_BY_NAME = {}
for _c in CONDITIONS:
    CONDS_BY_NAME.setdefault(_c["name"], []).append(_c)


def collect_events(P, prim, log=log_):
    """События по всем условиям: имя триггера → (условие, строки, колонки)."""
    ev = {}
    fin = np.isfinite(P)
    for c in CONDITIONS:
        if c["name"] in ev:
            continue                       # стороны делят один триггер
        try:
            hit = c["fn"](prim) & fin
        except KeyError:
            continue
        r, cc = Z.dedup_rows(hit, dedup_min=5)
        if len(r):
            ev[c["name"]] = (c, r, cc)
    log(f"  условий сработало {len(ev)}, событий "
        f"{sum(len(v[1]) for v in ev.values()):,}")
    return ev


def store_days(store=None):
    """Сутки, которые ЕСТЬ на складе лесенки, по диску."""
    return sorted(F.scan(store or STORE))


def stats(syms, days, log=log_):
    """Распределение самих величин — БЕЗ единого взгляда на исходы.

    Зачем это отдельный режим. Условие, которое не срабатывает никогда,
    и условие, у которого нет эффекта, в отчёте выглядят одинаково —
    пустой строкой. А `dead` (уровень ушёл в ноль, не увидев принта)
    может оказаться структурным нулём: площадка снимает уровень из
    лесенки, а не публикует его с нулевым размером, и тогда мера мертва
    по построению, а не по рынку.

    Пороги, поставленные ПО РАСПРЕДЕЛЕНИЮ ПРИЗНАКА, — это калибровка, и
    она законна: подгонкой было бы двигать их, увидев доходности. Здесь
    исходы не читаются вовсе — ни цены, ни форварда в этом режиме нет.
    """
    qs = (50, 90, 99, 99.9)
    rows = []
    for day in days:
        L = day_ladder(syms, day, log=log)
        if L is None:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            share = {
                "cancel_b/vis": L["cancel_b"] / L["vis_b"],
                "cancel_a/vis": L["cancel_a"] / L["vis_a"],
                "dead_b/vis": L["dead_b"] / L["vis_b"],
                "dead_a/vis": L["dead_a"] / L["vis_a"],
                "eat_b/vis": L["eat_b"] / L["vis_b"],
                "eat_a/vis": L["eat_a"] / L["vis_a"],
                "add_b/vis": L["add_b"] / L["vis_b"],
                "refill_b/eat": L["refill_b"] / L["eat_b"],
                "refill_a/eat": L["refill_a"] / L["eat_a"],
            }
        for name, M in list(share.items()) + [(f, L[f]) for f in LD.FIELDS]:
            v = M[np.isfinite(M)]
            if not v.size:
                rows.append((day, name, 0, [float("nan")] * len(qs), 0.0))
                continue
            rows.append((day, name, int(v.size),
                         [float(x) for x in np.percentile(v, qs)],
                         float((v > 0).mean())))
    log(f"{'сутки':11} {'величина':16} {'минут':>9} {'>0':>6} "
        + " ".join(f"p{q:g}".rjust(10) for q in qs))
    for day, name, n, q, pos in rows:
        log(f"{day:11} {name:16} {n:9,} {pos:6.2f} "
            .replace(",", " ")
            + " ".join(f"{x:10.4g}" for x in q))
    dead = [r for r in rows if r[1].startswith("dead") and r[2]]
    if dead and all(r[4] == 0.0 for r in dead):
        log("ВНИМАНИЕ: `dead` равен нулю во всех минутах — уровень, "
            "ушедший в ноль, площадка, видимо, просто убирает из "
            "лесенки. Тогда это структурный ноль меры, а не рынка, и "
            "условия по нему из пространства надо снимать ДО прогона.")
    return rows


def write_report(path, cells, null, drift, meta):
    L = []
    L.append("# Z3 — скрин по лесенке ценовых уровней\n")
    L.append(f"Прогон {meta['when']} · суток {meta['days']} "
             f"({meta['first']}…{meta['last']}) · условий "
             f"{len(CONDITIONS)} · ячеек {len(cells)} · перестановок "
             f"{null['perms']}\n")
    if meta["days"] < 7:
        L.append(f"\n**Это диагностика, а не вердикт: суток {meta['days']}.** "
                 "Склад лесенки катящийся и наполняется по суткам, "
                 "скрин считает по тому, что уже свёрнуто. Один режим "
                 "рынка на нескольких сутках — это не выборка: смоук "
                 "варианта C в гипотезе 4 давал Sharpe 1.12 на годе и "
                 "0.55 на четырёх, а градиент горизонта в S11 рассыпался "
                 "между двумя разрезами одной записи.\n")
    L.append("\n**Что здесь меряется и чего нет в Z2.** Z2 считает "
             "снятие по полосе ±0.25 %, привязанной к СЕРЕДИНЕ, а "
             "середина движется: часть «снятия» на резком ходе есть "
             "смещение полосы, а не уход заявок. Здесь всё считается по "
             "каждой цене между соседними снимками: `cancel` — убыль, не "
             "объяснённая сделкой на этой же цене; `dead` — уровень ушёл "
             "в ноль, не увидев ни одного принта; `refill` — на цене со "
             "сделкой объём подставили заново (тот самый знаменатель, "
             "которого не было у четырёх замеров ленты T1–T4); `sweep` — "
             "съеденный нотионал на базисный пункт хода.\n")
    L.append("\n**Как судится.** Ядро Z1: корзины длиной в горизонт, "
             "перестановочный нуль, планка по Z, согласие МЕДИАНЫ и "
             "СРЕДНЕГО и круг нейтральной книги "
             f"{Z.NEUTRAL_COST_BP:.0f} б.п. (наша нога плюс хедж об "
             "сечение — две ноги, а не одна). Контроль — СРЕДНЕЕ "
             "сечения: медиана есть статистика, а не портфель.\n")
    if drift:
        L.append("\n**Снос по стороне** (встроенная проверка меры: при "
                 "контроле средним обязан быть около нуля): "
                 + ", ".join(f"{k} {v:+.2f}" for k, v in sorted(drift.items()))
                 + ". Если эти числа заметно отличны от нуля, читать "
                 "таблицу нельзя — контроль считается не тем, чем "
                 "задумано.\n")
    # Главная диагностика отчёта, и она стоит ДО таблицы: если условие
    # и его близнец с другой стороны книги дают один и тот же знак,
    # триггер выбирает не направление, а СОСТОЯНИЕ. Тогда таблица
    # описывает, что рынок делает в такие минуты, а не сведение из
    # лесенки — и крупные числа читать как сигнал нельзя.
    same, seen = [], set()
    for (name, side, h), c in cells.items():
        tw = twin_of(name)
        if side != 1 or tw is None or (name, h) in seen:
            continue
        other = cells.get((tw, side, h))
        if not other:
            continue
        seen.add((tw, h))
        a1, a2 = c["mean_bp"] - drift.get(f"{h}|{side}", 0.0), \
            other["mean_bp"] - drift.get(f"{h}|{side}", 0.0)
        if a1 * a2 > 0 and min(abs(a1), abs(a2)) > 1.0:
            same.append((name, tw, h, a1, a2))
    if same:
        L.append("\n**Зеркало сторон книги: у "
                 f"{len(same)} пар условий обе стороны дают ОДИН знак.** "
                 "Снятие бидов и снятие асков — противоположные события; "
                 "если после обоих цена идёт в одну сторону, условие "
                 "выбрало не направление, а состояние (обычно резкую "
                 "минуту), и таблица описывает поведение рынка в такие "
                 "минуты, а не сведение из лесенки. Так же выглядела "
                 "асимметрия хода в T1, которую кросс-секция обнулила.\n\n")
        L.append("| условие | близнец | гор. | сверх сноса | у близнеца |\n")
        L.append("|---|---|--:|--:|--:|\n")
        for name, tw, h, a1, a2 in sorted(same, key=lambda x: -abs(x[3])):
            L.append(f"| {name} | {tw} | {h}м | {a1:+.1f} | {a2:+.1f} |\n")
    L.append(f"\nПланка семейственная: **{null['bar_z']:+.2f} σ** "
             f"(95-й процентиль максимума по семействам под нулём).\n")
    L.append("\n| условие | стор. | гор. | событий | корзин | медиана | "
             "среднее | сверх сноса | доля+ | z | вердикт |\n")
    L.append("|---|:--:|--:|--:|--:|--:|--:|--:|--:|--:|---|\n")
    rows = sorted(cells.items(),
                  key=lambda kv: -(kv[1].get("z") or -9e9))
    for (name, side, h), c in rows:
        d = drift.get(f"{h}|{side}", 0.0)
        L.append(
            f"| {name} | {'L' if side > 0 else 'S'} | {h}м | "
            f"{c['events']:,} | {c['buckets']:,} | {c['med_bp']:+.1f} | "
            f"{c['mean_bp']:+.1f} | {c['mean_bp'] - d:+.1f} | "
            f"{c.get('win', float('nan')):.2f} | "
            f"{c.get('z', float('nan')):+.1f} | "
            f"{Z.verdict_of(c, null)} |\n".replace(",", " "))
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z3: скрин по лесенке")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--stats", action="store_true",
                    help="распределение величин, без единого взгляда "
                         "на исходы")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    if HORIZONS != P2.HORIZONS:
        log_("горизонты скрина и Z2 разошлись — сравнивать таблицы "
             "нельзя; правьте в одном месте")
        return 1
    have = store_days()
    # Узкие сутки (свёрнутые по нескольким именам — так остаётся смоук)
    # в замер не идут вовсе: кросс-секции там нет, а нормы соседних
    # суток они всё равно не дают. Первый прогон включил такие сутки —
    # три имени против семисот, и нормы им достались от суток
    # восемнадцатидневной давности.
    narrow = F.partial_days(F.scan(STORE), store=STORE)
    if narrow:
        log_("узкие сутки в замер не идут: "
             + ", ".join(f"{d} (не хватает {n})"
                         for d, n in sorted(narrow.items())))
        have = [d for d in have if d not in narrow]
    if a.start:
        have = [d for d in have if d >= a.start]
    if a.end:
        have = [d for d in have if d <= a.end]
    if a.stats:
        syms = [s for s in a.symbols.split(",") if s] or P2.symbols()
        if not have:
            log_("на складе лесенки нет суток — считать нечего")
            return 1
        log_(f"распределение величин: суток {len(have)}, "
             f"символов {len(syms)}")
        stats(syms, have)
        return 0
    if len(have) < 2:
        log_(f"на складе лесенки суток {len(have)} — норма берётся с "
             "ВЧЕРАШНИХ суток, значит считать нечего: нужны хотя бы "
             "двое подряд")
        return 1
    syms = [s for s in a.symbols.split(",") if s] or P2.symbols()
    log_(f"скрин лесенки: суток {len(have)} ({have[0]}…{have[-1]}), "
         f"символов {len(syms)}, условий {len(CONDITIONS)}")
    acc, rng = {}, np.random.default_rng(Z.SEED)
    prev, prev_key, width = None, None, []
    for day in have:
        Lm = day_ladder(syms, day)
        if Lm is None:
            log_(f"  {day}: склада лесенки нет — пропускаю")
            prev, prev_key = None, None
            continue
        M, _ = P2.day_matrices(syms, day, log=log_, use_store=True)
        pairs = int(np.isfinite(Lm["pairs"]).sum())
        price = int(np.isfinite(M["mid_open"]).sum())
        width.append((day, pairs, price))
        # Норма берётся только с КАЛЕНДАРНО вчерашних суток. Склад
        # катящийся и наполняется по порядку, но пропуск в нём (сутки
        # не свернулись, сутки узкие) означал бы норму трёхнедельной
        # давности, выданную за вчерашнюю.
        prev_day = (datetime.strptime(day, "%Y-%m-%d")
                    - timedelta(days=1)).strftime("%Y-%m-%d")
        N = norms(prev) if prev_key == prev_day else None
        if N is None:
            log_(f"  {day}: нет КАЛЕНДАРНО вчерашних норм — сутки идут "
                 f"только в историю (минут лесенки {pairs:,}, цены "
                 f"{price:,})".replace(",", " "))
            prev, prev_key = Lm, day
            continue
        prim = primitives(Lm, N)
        times = np.arange(M["mid_open"].shape[1], dtype=np.int64) * 60 \
            + int(datetime.strptime(day, "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp())
        log_(f"  {day}: минут лесенки {pairs:,}, цены {price:,}"
             .replace(",", " "))
        ev = collect_events(M["mid_open"], prim)
        Z.measure(ev, M["mid_open"], times, acc, rng,
                  conds_by_name=CONDS_BY_NAME, control="mean",
                  horizons=HORIZONS)
        prev, prev_key = Lm, day
    if not acc:
        log_("ни одного события — считать нечего")
        return 1
    log_("считаю сводку и семейственную планку…")
    cells, null = Z.summarize(acc)
    drift = P2.side_drift(cells)
    path = os.path.join(OUT, f"Z3-ladder-{a.tag}.md")
    write_report(path, cells, null, drift,
                 {"when": datetime.now(timezone.utc)
                  .strftime("%Y-%m-%d %H:%M UTC"),
                  "days": len(width), "first": (width[0][0] if width else "—"),
                  "last": (width[-1][0] if width else "—"),
                  "width": width})
    with open(os.path.join(OUT, f"z3-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": {f"{k[0]}|{k[1]}|{k[2]}": v
                             for k, v in cells.items()},
                   "null": null, "drift": drift, "width": width,
                   "conds": len(CONDITIONS)}, f, ensure_ascii=False)
    over = [k for k, c in cells.items()
            if Z.verdict_of(c, null) == "**кандидат**"]
    log_(f"отчёт: {path}")
    log_(f"ячеек измерено: {len(cells)}; планка {null['bar_z']:+.2f} σ; "
         f"кандидатов: {len(over)}")
    for k in sorted(over, key=lambda x: -cells[x]["z"])[:10]:
        c = cells[k]
        log_(f"  {k[0]} [{'L' if k[1] > 0 else 'S'}] {k[2]}м: "
             f"медиана {c['med_bp']:+.1f}, среднее {c['mean_bp']:+.1f} "
             f"б.п., z {c['z']:+.1f}, корзин {c['buckets']}")
    log_("снос по стороне (обязан быть около нуля): "
         + ", ".join(f"{k}: {v:+.2f}" for k, v in sorted(drift.items())))
    if not a.no_publish:
        Z.publish("Z3: скрин по лесенке ценовых уровней")
    return 0


if __name__ == "__main__":
    sys.exit(main())
