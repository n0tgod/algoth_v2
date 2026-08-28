#!/usr/bin/env python3
"""То же условие всплеска — на годах истории, а не на трёх неделях.

Зачем. Зонд по записи стакана (`spike.py`, 21 сутки) намерил у ячейки
«цена выросла на 2 % за минуту», шорт, 60 минут превышение +38.4 б.п.
над одновременной кросс-секцией. Скрин Z1 мерил похожее семейство на
2.5 годах минутных баров Binance и оставил от него **+2 б.п. сверх
сноса**. Расхождение в двадцать раз — повод не верить короткому окну, а
не радоваться ему. Здесь то же условие считается на хранилище A2, где
истории годы: 2022-01 … 2026-08 против трёх недель.

**Пространство объявлено до прогона и не растёт: два условия (всплеск
вверх и вниз на 2 % за минуту) × две стороны × три горизонта = 12
ячеек.** Ячейка вердикта одна и та же, что в зонде по стакану: вверх,
шорт, 60 минут. Остальное — диагностика распада; предъявлять лучшую
ячейку из двенадцати запрещено (ошибка R5).

**Профиль по годам — главная диагностика, а не украшение.** Вопрос
прогона в том, свойство ли это рынка или свойство трёх недель августа
2026; ответ даёт не общее число, а согласие лет. Годы считаются тем же
судьёй, а не второй мерой: `measure` зовётся ещё раз в накопитель
своего года.

**Три различия с зондом по стакану, названные до чтения чисел.**
Цена здесь — открытие минутного бара Binance, там — середина стакана
Bybit в начале минуты: близко, но не тождественно, и базис площадок в
разность не входит только потому, что событие, форвард и фон берутся
из ОДНОГО источника (урок T2). Бар без сделок отбрасывается загрузчиком
(`trades = 0` — не наблюдение, урок A2), то есть замороженный ряд
событий не создаёт. И спреда в архиве нет вовсе: он переносится
числом из нашей записи стакана и подписан как перенесённый.

Запуск:
    cd ~/algoth_v2 && mkdir -p research/probe_spike/out
    cd ~/algoth_v2 && .venv/bin/python research/probe_spike/long_history.py \\
        --tag 1m
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "z1_screen"), os.path.join(ROOT, "l3_events"),
          HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import data as D                                           # noqa: E402
import screen as Z                                         # noqa: E402
import spike as S                                          # noqa: E402

OUT = os.path.join(HERE, "out")
HORIZONS = S.HORIZONS               # 15 / 60 / 240 минут — как у зонда
JUMP = S.JUMP                       # 2 % за минуту — как у зонда
DEDUP_MIN = 5                       # окно склейки серии, как у зонда

# Спред взят из СОБСТВЕННОЙ записи стакана (21 сутки, 725 имён, зонд
# `spike.py`): в архиве Binance спреда нет вовсе. Числа перенесены, а
# не измерены здесь, и отчёт обязан это говорить. Наша нога дороже
# хеджа, потому что в момент всплеска книга шире обычного.
SPREAD_OWN = (8.5, 6.5)             # вход / выход, б.п.
SPREAD_HEDGE = (5.7, 5.7)


def log_(m):
    print(m, flush=True)


def primitives(P):
    """Единственный примитив: ход за минуту по открытиям соседних баров.

    Сетка регулярная, и дыра в ней даёт NaN, а не «ход через дыру»:
    отсутствующий бар в матрице — пропуск, и `P[:, t] / P[:, t-1]`
    через него возвращает NaN сам. Тот же класс дефекта, что окно по
    номеру точки в L2, только здесь он закрыт формой матрицы.
    """
    out = np.full(P.shape, np.nan, dtype=np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:, 1:] = P[:, 1:] / P[:, :-1] - 1.0
    return {"ret_1m": out}


def build_conditions():
    C = []
    for side in (+1, -1):
        for lbl, sign in (("вверх", +1), ("вниз", -1)):
            fn = ((lambda p: p["ret_1m"] >= JUMP) if sign > 0
                  else (lambda p: p["ret_1m"] <= -JUMP))
            C.append({"name": f"всплеск {lbl} 2 % за минуту", "side": side,
                      "fn": fn, "group": f"всплеск {lbl}"})
    return C


CONDITIONS = build_conditions()
CONDS_BY_NAME = {}
for _c in CONDITIONS:
    CONDS_BY_NAME.setdefault(_c["name"], []).append(_c)


def collect_events(P, prim, own, log=log_):
    """События месяца. `own` отсекает хвост следующего месяца.

    Хвост нужен для форвардов конца месяца и событием быть не должен —
    иначе то же событие посчиталось бы дважды, своим месяцем и чужим.
    """
    ev = {}
    fin = np.isfinite(P) & own[None, :]
    for c in CONDITIONS:
        if c["name"] in ev:
            continue
        hit = c["fn"](prim) & fin
        r, cc = Z.dedup_rows(hit, dedup_min=DEDUP_MIN)
        if len(r):
            ev[c["name"]] = (c, r, cc)
    log(f"  условий сработало {len(ev)}, событий "
        f"{sum(len(v[1]) for v in ev.values()):,}".replace(",", " "))
    return ev


def trips():
    """Оба круга ОДНОЙ формулой зонда — второй копии издержек нет.

    Списки спредов подставные (по одному числу): `round_trip` берёт из
    них медиану, и одно число само себе медиана. Считать издержки
    здесь своей арифметикой значило бы завести вторую формулу, а они
    уже расходились в этом проекте дважды.
    """
    a = {"spread_in": [SPREAD_OWN[0]], "spread_out": [SPREAD_OWN[1]],
         "hedge_in": [SPREAD_HEDGE[0]], "hedge_out": [SPREAD_HEDGE[1]]}
    return S.round_trip(a)[0], S.solo_trip(a)


def run(start, end, symbols=None, log=log_):
    uni = D.universe()
    syms = symbols or sorted(uni)
    rng = np.random.default_rng(Z.SEED)
    acc, by_year = {}, {}
    for mon in Z.months_between(start, end):
        a, b = Z.month_span(mon)
        nb = Z.month_span((b - timedelta(days=1)).strftime("%Y-%m"))[1]
        times = Z.grid(a, nb)
        own = (times >= int(a.timestamp())) & (times < int(b.timestamp()))
        t0 = datetime.now(timezone.utc)
        P = D.price_matrix(syms, times, "1m", None, columns=("open",))
        fill = float(np.isfinite(P).mean())
        if fill < 0.001:
            log(f"  {mon}: матрица пуста ({fill:.3%}) — партиции нет, пропуск")
            del P
            continue
        prim = primitives(P)
        ev = collect_events(P, prim, own, log)
        if ev:
            Z.measure(ev, P, times, acc, rng, log=log,
                      conds_by_name=CONDS_BY_NAME, control="mean",
                      horizons=HORIZONS)
            year = mon[:4]
            ya = by_year.setdefault(year, {})
            # Зерно года выведено ЧИСЛОМ из года, а не взято от часов
            # запуска: нуль, который нельзя повторить, проверяемым не
            # является (урок R3).
            Z.measure(ev, P, times, ya, np.random.default_rng(
                Z.SEED + int(year)), log=lambda _m: None,
                conds_by_name=CONDS_BY_NAME, control="mean",
                horizons=HORIZONS)
        n_ev = sum(len(v[1]) for v in ev.values())
        log(f"  {mon}: заполнено {fill:.1%}, событий {n_ev:,}, "
            f"{(datetime.now(timezone.utc) - t0).total_seconds():.0f} с"
            .replace(",", " "))
        del P, prim, ev
    return acc, by_year


KEY = ("всплеск вверх 2 % за минуту", -1, 60)      # ячейка вердикта


def write_report(path, cells, null, years, meta):
    book, solo = trips()
    L = ["# То же условие всплеска на годах истории\n"]
    L.append(f"\nПрогон {meta['when']} · окно {meta['start']}…{meta['end']} "
             f"· месяцев {meta['months']} · символов {meta['symbols']} · "
             f"ячеек {len(cells)}\n")
    L.append("\n**Зачем прогон.** Зонд по записи стакана намерил у "
             "ячейки «вверх 2 % за минуту, шорт, 60 минут» превышение "
             "+38.4 б.п. на 21 сутках. Скрин Z1 мерил похожее семейство "
             "на 2.5 годах и оставил от него +2 б.п. сверх сноса. "
             "Расхождение в двадцать раз — повод проверить то же "
             "условие там, где истории годы.\n")
    L.append("\n**Пространство объявлено до прогона:** два условия × две "
             "стороны × три горизонта = 12 ячеек, ячейка вердикта одна "
             "и та же (вверх, шорт, 60 минут). Предъявлять лучшую из "
             "двенадцати запрещено — это ошибка R5.\n")
    L.append("\n**Издержки перенесены, а не измерены здесь.** В архиве "
             "спреда нет вовсе; взяты числа собственной записи стакана "
             f"(наша нога {SPREAD_OWN[0]}/{SPREAD_OWN[1]} б.п., "
             f"хедж {SPREAD_HEDGE[0]}/{SPREAD_HEDGE[1]}). Круг "
             f"хеджированной книги **{book:.1f}** б.п., круг голой "
             f"ноги **{solo:.1f}**. Спред в 2022–2024 годах почти "
             "наверняка был шире нынешнего, то есть перенос работает "
             "В НАШУ пользу и читается как нижняя граница издержек.\n")
    L.append("\n| условие | стор. | гор. | событий | корзин | медиана | "
             "среднее | доля+ | z | нетто книги | нетто ноги | вердикт |\n")
    L.append("|---|:--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|\n")
    for (name, side, h), c in sorted(cells.items(),
                                     key=lambda kv: -(kv[1].get("z") or -9e9)):
        raw = c.get("raw_mean_bp", float("nan"))
        L.append(f"| {name} | {'L' if side > 0 else 'S'} | {h}м | "
                 f"{c['events']:,} | {c['buckets']:,} | "
                 f"{c['med_bp']:+.1f} | {c['mean_bp']:+.1f} | "
                 f"{c.get('win', float('nan')):.2f} | "
                 f"{c.get('z', float('nan')):+.1f} | "
                 f"{c['mean_bp'] - book:+.1f} | {raw - solo:+.1f} | "
                 f"{Z.verdict_of(c, null)} |\n".replace(",", " "))
    L.append("\n«Нетто книги» — среднее превышение минус круг двух ног; "
             "«нетто ноги» — сырой ход минус круг одной. Вердикт судья "
             f"ставит против круга {Z.NEUTRAL_COST_BP:.0f} б.п., то есть "
             "комиссии БЕЗ спреда: колонки нетто и ярлык расходятся "
             "ровно на спред.\n")

    L.append("\n### Профиль по годам — ячейка вердикта\n\n")
    L.append("| год | событий | корзин | медиана | среднее | доля+ | z |\n")
    L.append("|---|--:|--:|--:|--:|--:|--:|\n")
    signs = []
    for y in sorted(years):
        c = years[y]["cells"].get(KEY)
        if not c:
            L.append(f"| {y} | — | — | — | — | — | — |\n")
            continue
        signs.append(c["mean_bp"])
        L.append(f"| {y} | {c['events']:,} | {c['buckets']:,} | "
                 f"{c['med_bp']:+.1f} | {c['mean_bp']:+.1f} | "
                 f"{c.get('win', float('nan')):.2f} | "
                 f"{c.get('z', float('nan')):+.1f} |\n".replace(",", " "))
    pos = sum(1 for v in signs if v > 0)
    if signs:
        L.append(f"\nПоложительных лет {pos} из {len(signs)}, разброс "
                 f"среднего {min(signs):+.1f}…{max(signs):+.1f} б.п. "
                 "Согласие лет и есть проверка, свойство ли это рынка "
                 "или свойство одного окна: общее число её не заменяет, "
                 "потому что одно сильное окно вытягивает среднее по "
                 "всей истории.\n")

    cell = cells.get(KEY)
    if cell:
        L.append("\n### Ячейка вердикта против замера по стакану\n\n")
        L.append("| мера | запись стакана, 21 сутки | архив, годы |\n")
        L.append("|---|--:|--:|\n")
        L.append(f"| превышение, среднее | +38.5 | {cell['mean_bp']:+.1f} |\n")
        L.append(f"| превышение, медиана | +72.2 | {cell['med_bp']:+.1f} |\n")
        L.append(f"| доля прибыльных корзин | 0.61 | "
                 f"{cell.get('win', float('nan')):.2f} |\n")
        L.append(f"| корзин | 468 | {cell['buckets']:,} |\n"
                 .replace(",", " "))
        L.append(f"| нетто хеджированной книги | +3.2 | "
                 f"{cell['mean_bp'] - book:+.1f} |\n")
        L.append("\nЧисла левой колонки — `SPIKE-report-1m.md`. Совпадение "
                 "по порядку означало бы, что три недели не соврали; "
                 "расхождение — что величина принадлежала окну.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="то же условие на годах истории")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2026-08-26")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    syms = [s for s in a.symbols.split(",") if s] or None
    mons = Z.months_between(a.start, a.end)
    log_(f"условие всплеска на архиве: {a.start}…{a.end}, "
         f"месяцев {len(mons)}")
    acc, by_year = run(a.start, a.end, symbols=syms, log=log_)
    if not acc:
        log_("ни одного события — считать нечего")
        return 1
    cells, null = Z.summarize(acc)
    years = {}
    for y, ya in by_year.items():
        yc, yn = Z.summarize(ya)
        years[y] = {"cells": yc, "null": yn}
    path = os.path.join(OUT, f"SPIKE-long-{a.tag}.md")
    write_report(path, cells, null, years,
                 {"when": datetime.now(timezone.utc)
                  .strftime("%Y-%m-%d %H:%M UTC"),
                  "start": a.start, "end": a.end, "months": len(mons),
                  "symbols": len(syms) if syms else len(D.universe())})
    with open(os.path.join(OUT, f"spike-long-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": {f"{k[0]}|{k[1]}|{k[2]}": v
                             for k, v in cells.items()},
                   "null": null,
                   "years": {y: {f"{k[0]}|{k[1]}|{k[2]}": v
                                 for k, v in d["cells"].items()}
                             for y, d in years.items()}},
                  f, ensure_ascii=False)
    log_(f"отчёт: {path}")
    c = cells.get(KEY)
    if c:
        book, solo = trips()
        log_(f"  ячейка вердикта: событий {c['events']:,}, корзин "
             f"{c['buckets']:,}, медиана {c['med_bp']:+.1f}, среднее "
             f"{c['mean_bp']:+.1f}, доля+ {c.get('win', float('nan')):.2f}, "
             f"нетто книги {c['mean_bp'] - book:+.1f} б.п."
             .replace(",", " "))
    if not a.no_publish:
        Z.publish("то же условие всплеска на годах истории")
    return 0


if __name__ == "__main__":
    sys.exit(main())
