#!/usr/bin/env python3
"""Механика 193cbb87 — ПАУЗА ПО ИМЕНИ после хвостового выхода.

Заявка предлагающего 2026-09-17 (`research/factory/out/proposal.md`,
задание `research/factory/out/build_task.md`): короткая книга `h24` не
открывает шорт в имени X, если её СОБСТВЕННАЯ предыдущая позиция в X
закрылась исходом «пол» или «ликвидация» меньше P часов назад.

    ось P            6 / 12 / 24 ч   (объявлена брифом и скрином хвоста)
    ячейка вердикта  P = 12 ч — СЕРЕДИНА оси, как у охраны рынком
    книга вердикта   safe_h, депозит $10 000, деньги НЕТТО
    исходы-триггеры  `tail_screen.TAIL_EXITS` — не своя копия

Ни одно число правила здесь не назначается заново: ось, ячейка вердикта,
пороги-убийцы, число зёрен и названный день перенесены из задания
именованными постоянными. Порог, назначенный тем же, кто его проверяет,
слабее назначенного независимо.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Правило не меняет ИСХОДА ни одной позиции: у
семейства `h24` доливов нет, срок 24 ч фиксирован, цель, пол и охрана
считаются на самой позиции, и исход в кэше реплея не зависит от того,
какие ещё позиции держит книга. Меняется СОСТАВ книги — ровно так же
считал гейт входа (`dca_paper/entry_gate.py`). Поэтому реплея по барам
здесь нет вовсе, кэш читается и не переписывается (`cache_locked`), а
подпись кэша не трогается: пауза — правило состава, как возраст имени, а
не правило исхода, как охрана рынком.

ПОЧЕМУ ПОСЛЕДОВАТЕЛЬНО. Триггер — СОБСТВЕННАЯ ВЗЯТАЯ позиция книги, а
кто взят, знает только касса: решение, которому не хватило денег,
позицией не стало и паузы не даёт. Значит состав считается шагами: на
каждом шаге касса пересчитывается, снимается САМАЯ РАННЯЯ запрещённая
запись, и так до неподвижности. Это точно, а не приблизительно: касса
причинна (решение зависит только от того, что было раньше), поэтому
снятие записи в момент t не меняет ни одного решения ДО t — а значит
самая ранняя запрещённая запись запрещена окончательно.

ГДЕ ЖИВЁТ ПРАВИЛО И ПОЧЕМУ ЗДЕСЬ. Его место — слот между охраной рынком
и кассой (`run_short.run`: возраст → охрана → касса). Дописать его в
`run_paper.py` нельзя: публикация постройки несёт ТОЛЬКО свой каталог
(`research/factory/publish_build.py`), и правка чужого файла осталась бы
на сервере — прогон был, а в ветке пусто. Поэтому здесь стоит тот же
порядок теми же функциями (`prepare` → `sister` → `form_of`), а
равенство ячейке семейства (`short_grid.cell_stats`) проверяется числом
(`agrees_with_cell`) и едет в отчёт: вторая касса — не обещание, а
измеримое обвинение.

Порядок печати объявлен заданием и соблюдается прогоном:

    0) повторы после своего хвостового выхода — ПЕРВОЙ таблицей, по
       книгам и по всей оси P; она же скорее всего и закрывает заявку;
    1) калибровочная пара: пауза 0 ч равна базе бит в бит; перемешанные
       метки исходов эффекта не дают; подсаженные повторы находятся;
    2) шаг 1а — потолок с идеальным знанием будущего;
       шаг 1б — правило против случайного урезания того же числа сделок;
       шаг 1в — плацебо: та же пауза после ПРИБЫЛЬНОГО выхода;
       шаг 1г — переодетое плечо: перестановка меток в полосе ≥ 15×;
    3) шаг 2 — форма на записи с обязательными колонками;
    4) шаг 3 — вперёд: правило вылета пула и то, чего пока не измерить.

Запуск (VPS, очередь заданий):

    run research/mech_193cbb87/name_pause.py

Смоук: `--seeds 4 --no-publish`. Проверки:
`.venv/bin/python research/mech_193cbb87/test_name_pause.py`.
"""
import argparse
import collections
import contextlib
import json
import os
import random

import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
for _rel in ("research/dca_paper", "research", "research/a1_universe",
             "research/dca_ladder", "research/s8_loop", "research/factory"):
    _p = os.path.join(ROOT, _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import tail_screen as TS                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import stability as ST                                        # noqa: E402
import pool as PL                                             # noqa: E402

MECH = "193cbb87"
ART = "PAUSE-name"
HOUR = 3600.0

# --- объявлено ЗАДАНИЕМ, а не этим файлом --------------------------------
BOOK = "safe_h"                    # книга вердикта: безопасная короткая
DEP = 10000.0                      # депозит вердикта; на нём идёт контроль
BOOKS = tuple(R.H24_ORDER)         # три книги семейства; две — диагностика
DEPS = tuple(float(d) for d in R.DEPOSITS)      # $1k и $100k — диагностика
PAUSE_GRID_H = (6.0, 12.0, 24.0)   # ось паузы, объявлена до прогона
# Ячейка вердикта — СЕРЕДИНА оси, как у охраны рынком (1/2/3 % → 2 %).
# Выводится из оси, а не стоит числом: литерал рядом с осью стареет молча.
VERDICT_P_H = PAUSE_GRID_H[len(PAUSE_GRID_H) // 2]
# Исходы-триггеры берутся у скрина хвоста, где объявлены ДО просмотра.
TRIGGER_EXITS = tuple(TS.TAIL_EXITS)
# Плацебо: та же пауза после ПРИБЫЛЬНОГО выхода. Метка исхода — та,
# которой её пишет ядро лестницы (`dca_ladder/ladder.py`, ветка цели);
# своей константы у ядра нет, поэтому она названа здесь и ПРОВЕРЯЕТСЯ на
# данных: исхода, которого в журнале нет вовсе, плацебо не бывает.
TAKE_EXIT = "тейк"
PLACEBO_EXITS = (TAKE_EXIT,)
# Вариант триггера с добавленным исходом охраны — диагностика.
MARKET_EXIT = R.GUARD_EXIT
SEEDS = AG.SEEDS                   # 200 зёрен — одно число на весь проект
PERMS = TS.PERMS                   # 200 перестановок — тем же числом
HIGH_LEV = TS.HIGH_LEV             # полоса плеча, где живёт хвост
# Убийца шага 0: правило инертно — судить нечего. Задание объявило его
# на САМОЙ ШИРОКОЙ ячейке оси («вход не позже 24 ч после собственного
# хвостового выхода») и на трактовке «после последнего хвостового
# выхода», а не на ячейке вердикта: порог, перенесённый на другую
# ячейку, был бы порогом, назначенным здесь.
MIN_REPEATS = 20
MIN_SHARE = 0.03
KILL_P_H = max(PAUSE_GRID_H)
KILL_MODE = "tail"
# Убийца шагов 1а–1в: случайное урезание не хуже правила в ≥ 5 % зёрен.
BEAT_MAX = 0.05
# Убийца шага 1г: перестановки дают такой же разрыв в ≥ 5 % случаев.
PERM_MAX = 0.05
# Худший день базы — назван заданием, деньги за него идут отдельной строкой.
NAMED_DAY = "2026-09-12"
# Калибровка: подсаженным повторам переписывается исход.
PLANT_PNL = -0.9
# Предел шагов состава: больше — это не пауза, а другая книга.
MAX_STEPS = 2000

# Величины спора — порядок показа; первая и есть та, по которой судят.
CTL_FIELDS = ("usd_wo_top3d", "ratio", "day_worst")
MAIN_FIELD = "usd_wo_top3d"
FIELD_TITLE = {"usd_wo_top3d": "$ без 3 лучших дней",
               "ratio": "доход/просадка",
               "day_worst": "худший день, доля депозита"}


def _quiet(*_a):
    pass


# --- состав книги --------------------------------------------------------

def closed_of(recs):
    """Закрытые записи: у открытой позиции исхода нет вовсе.

    Открытая позиция триггером быть не может ни при какой трактовке: её
    исход лежит в будущем решения, а не в его прошлом.
    """
    return [r for r in recs if (r.get("state") or "closed") == "closed"
            and r.get("exit") is not None and r.get("exit_ts") is not None]


def taken_of(rows, book, dep):
    """Позиции, которые книга ВЗЯЛА на этом депозите — строками кассы.

    Касса (`run_paper.build_rows`) отдаёт только ЗАКРЫТЫЕ взятые
    позиции, и это ровно то, что нужно триггеру: решение, которому не
    хватило денег или которое сняло правило «одна на имя», позицией не
    стало, и живой исполнитель о нём ничего не знает.
    """
    mine = [r for r in rows if R.ruler_of(r) == book
            and int(r.get("dep", 0)) == int(dep)]
    mine.sort(key=lambda r: (float(r["at"]), str(r["sym"])))
    return mine


def blocked_of(recs, taken, pause_h, exits=TRIGGER_EXITS, mode="prev"):
    """Записи, которых книга НЕ берёт: пауза после своего хвостового выхода.

    `mode="prev"` — само правило заявки: смотрится ПРЕДЫДУЩАЯ позиция
    книги в имени, и если она закрылась исходом из `exits` меньше
    `pause_h` часов назад, вход запрещён.

    `mode="tail"` — величина шага 0 задания: вход не позже P часов после
    ПОСЛЕДНЕГО хвостового выхода книги в имени, даже если между ними
    успела встать позиция с обычным исходом. Две величины различаются
    ровно этим случаем, и обе печатаются — трактовка, выбранная молча,
    есть решение, принятое там, где его никто не увидит.

    Записи отдаются ПО ВРЕМЕНИ ВХОДА: состав снимается по одной, и
    порядок здесь — часть правила, а не удобство показа.
    """
    by_sym = {}
    for t in sorted(taken, key=lambda r: float(r["at"])):
        by_sym.setdefault(str(t["sym"]), []).append(t)
    out = []
    for r in sorted(recs, key=lambda x: (float(x["at"]), str(x["sym"]))):
        at = float(r["at"])
        prev = None
        for t in by_sym.get(str(r["sym"])) or []:
            if float(t["at"]) >= at:
                break
            if mode == "tail" and (t.get("exit") or "") not in exits:
                continue
            prev = t
        if prev is None:
            continue
        ex, ts = prev.get("exit"), prev.get("exit_ts")
        # Позиция, не закрытая К МОМЕНТУ РЕШЕНИЯ, триггером не бывает: её
        # исход есть будущее этого решения. Это ЕДИНСТВЕННАЯ защита от
        # заглядывания вперёд, и второй, дублирующей, здесь нет
        # намеренно: проверка, которую нечем уронить, не проверяет
        # ничего — нижняя граница окна прикрывала её и делала
        # негативный контроль непроверяемым.
        if ts is None or float(ts) > at:
            continue
        if (ex or "") not in exits:
            continue
        gap = at - float(ts)
        # Пауза кончается РОВНО через P часов: вход ровно на границе
        # разрешён. Граница объявлена до прогона, и двигать её нельзя.
        if not (gap < float(pause_h) * HOUR):
            continue
        out.append({"key": RP._key(r), "sym": str(r["sym"]), "at": at,
                    "trigger_at": float(prev["at"]), "trigger_exit": ex,
                    "trigger_exit_ts": float(ts),
                    "gap_h": round(gap / HOUR, 3)})
    return out


def prepare(packed, launch, books=BOOKS, now=None, mkt=None, log=_quiet):
    """Правила счёта ДО кассы: возраст имени, затем охрана рынком.

    Порядок тот же, что у прогона (`run_short.run`) и у ячейки семейства
    (`short_grid.cell_stats`), и обе функции — те же самые, а не их
    копии. Пауза стоит СЛЕДУЮЩИМ слотом, после них и до кассы: она
    вычёркивает вход, а исход входа уже посчитан охраной.

    Обе — правила ПОЗАПИСНЫЕ, поэтому снятие записи с ними коммутирует:
    состав можно резать после них, и книга остаётся той же. Это не
    рассуждение, а проверка — `agrees_with_cell` сверяет числом.
    """
    out, ages, guards = {}, {}, {}
    for bk in books:
        recs = list(packed.get(bk) or [])
        recs, ages[bk] = RP.age_shorts(recs, bk, launch=launch, log=log,
                                       now=now)
        recs, guards[bk] = RP.guard_shorts(recs, bk, log=log, now=now,
                                           mkt=mkt)
        out[bk] = recs
    return out, ages, guards


@contextlib.contextmanager
def only(dep):
    """Касса считается на ОДНОМ депозите — ради скорости, не ради чисел.

    Состав с паузой считается шагами, а `run_paper.build_rows` на каждом
    шаге перебирает все три депозита семейства: два из них на этом шаге
    никому не нужны. Депозиты в кассе независимы (маржа считается от
    своего счёта), поэтому сужение списка не меняет ни одного числа —
    и это не рассуждение, а проверка: `ускорение_сверяется_бит_в_бит`
    сверяет узкий проход с полным. Список возвращается на место всегда.
    """
    was = list(R.DEPOSITS)
    R.DEPOSITS = [float(dep)]
    try:
        yield
    finally:
        R.DEPOSITS = was


def sister(packed, dep, pause_h, books=BOOKS, exits=TRIGGER_EXITS,
           trigger="taken", mode="prev", now=None, log=_quiet,
           max_steps=MAX_STEPS):
    """Состав книги с паузой: записи снимаются ПО ОДНОЙ, в порядке времени.

    Почему не одним проходом: снятая запись освобождает деньги и имя, и
    касса берёт на них другие позиции — а значит и триггеры у книги
    становятся другими. Считать это «в один проход» означало бы судить
    правило по чужому составу.

    Почему одна запись за шаг — правильно и конечно: касса причинна,
    поэтому снятие записи в момент t не меняет ни одного решения ДО t.
    Самая ранняя запрещённая запись запрещена окончательно; каждый шаг
    снимает ровно её, и шагов не больше, чем записей.

    `trigger="cache"` — вариант диагностики: триггером считается ЛЮБОЕ
    закрытое решение имени, взяла его касса или нет.
    """
    cur = {bk: list(packed.get(bk) or []) for bk in books}
    cut = {bk: [] for bk in books}
    steps = {bk: 0 for bk in books}
    rows, cells = [], {}
    # Книги семейства в кассе НЕЗАВИСИМЫ (у каждой свой счёт), поэтому
    # состав каждой считается своим циклом: снятая запись безопасной
    # книги не меняет ни одного решения агрессивной.
    with only(dep):
        for bk in books:
            while True:
                r_, c_, _one, _live = RP.build_rows({bk: cur[bk]}, now=now,
                                                    keys=[bk], log=log)
                src = (closed_of(cur[bk]) if trigger == "cache"
                       else taken_of(r_, bk, dep))
                b = blocked_of(cur[bk], src, pause_h, exits=exits, mode=mode)
                if not b:
                    rows += r_
                    cells.update(c_)
                    break
                # `blocked_of` отдаёт записи по времени входа: снимается
                # САМАЯ РАННЯЯ. Снять позднюю значило бы судить её по
                # составу, которого у книги с паузой не будет.
                first = b[0]
                cur[bk] = [r for r in cur[bk] if RP._key(r) != first["key"]]
                cut[bk].append(first)
                steps[bk] += 1
                if steps[bk] > max_steps:
                    raise RuntimeError(
                        f"пауза {pause_h:g} ч сняла у книги {bk} больше "
                        f"{max_steps} записей — это не пауза, а другая "
                        "книга; прогон отказывается считать дальше молча")
    return {"packed": cur, "cut": cut, "steps": steps, "rows": rows,
            "cells": cells}


# --- деньги и форма ------------------------------------------------------

def form_of(rows, dep, ctx, book, cells=None):
    """Форма книги на строках кассы: деньги НЕТТО, концентрация, дни.

    Теми же функциями, что считает семейство (`short_grid.cell_stats`):
    издержки в КАЖДУЮ сделку (`costs.apply_to_rows`), статистика книги
    (`run_paper._stats`), устойчивость (`stability.stats`). Зачем не
    сама `cell_stats`: её ячейка не отдаёт колонок концентрации («без
    трёх лучших дней», «без лучшего имени», «просадка без худшего дня»),
    а спор заявки идёт ровно о них; дописать поля в `short_grid.py`
    нельзя — правка чужого файла не публикуется. Равенство ячейке на
    ОБЩИХ полях проверяет `agrees_with_cell`, и оно едет в отчёт.
    """
    mine = [r for r in rows if R.ruler_of(r) == book
            and int(r.get("dep", 0)) == int(dep)]
    cst = {"error": (ctx or {}).get("error") or "контекста издержек нет"}
    if ctx is not None and not ctx.get("error"):
        mine, cst = CO.apply_to_rows(mine, ctx)
    st = RP._stats(mine, dep) or {}
    if not st:
        return {"n": 0, "why": "строк книги нет"}
    daily = {}
    for d in st.get("days_rows") or []:
        daily[str(d["d"])] = float(d["usd"])
    sh = ST.stats(daily) or {}
    cell = (cells or {}).get(RP._cell(book, dep)) or {}
    by = collections.Counter(r.get("exit") or "—" for r in mine)
    usd = collections.defaultdict(float)
    for r in mine:
        usd[r.get("exit") or "—"] += float(r.get("usd") or 0.0)
    fin, dd = st.get("final"), st.get("max_dd")
    return {
        "book": book, "dep": int(dep), "n": st.get("n"),
        "usd": st.get("usd"), "final": fin, "max_dd": dd,
        "ratio": (None if not fin or not dd
                  else round(float(fin) / abs(float(dd)), 2)),
        "win": st.get("win"), "day_median": st.get("day_median"),
        "day_worst": st.get("day_worst"), "day_green": st.get("day_green"),
        "usd_wo_top": st.get("usd_wo_top"),
        "usd_wo_top3d": st.get("usd_wo_top3d"),
        "max_dd_wo_worst": st.get("max_dd_wo_worst"),
        "worst_day": st.get("worst_day"), "top_sym": st.get("top_sym"),
        "names": st.get("names"), "days": st.get("days"),
        # Форма — мерой проекта, а не своей: медиана суток, доля зелёных,
        # укус. Среднее стоит РЯДОМ с медианой: расхождение знака есть
        # подпись короткой волатильности, и прятать его нельзя.
        "med": sh.get("med"), "med_green": sh.get("med_green"),
        "green": sh.get("green"), "bite": sh.get("bite"),
        "mean": (None if not sh.get("days")
                 else round(float(sh["tot"]) / float(sh["days"]), 2)),
        "under": sh.get("under"), "red": sh.get("red"),
        "thin": sh.get("thin"),
        "named_day": daily.get(NAMED_DAY),
        "exits": {k: {"n": v, "usd": round(usd[k], 2)} for k, v in by.items()},
        "taken": cell.get("taken"), "no_cash": cell.get("no_cash"),
        "costs": {k: cst.get(k) for k in ("applied", "error", "cost_usd",
                                          "no_funding")} if cst else None,
        "daily": daily}


def agrees_with_cell(packed, ctx, launch, dep=DEP, book=BOOK, now=None,
                     log=_quiet, mkt=None):
    """Сверка с ячейкой семейства: те же деньги теми же правилами.

    Числом, а не утверждением: расхождение означает, что здесь заведена
    вторая касса, и оно едет в отчёт. Сверяются ОБЩИЕ поля — те, что
    ячейка отдаёт.
    """
    prep, _a, _g = prepare(packed, launch, books=(book,), now=now, mkt=mkt,
                           log=log)
    rows, cells, _o, _l = RP.build_rows(prep, now=now, keys=[book], log=log)
    mine = form_of(rows, dep, ctx, book, cells)
    cell = G.cell_stats(packed, ctx, launch, now=now, log=log, keys=[book],
                        deps=[dep]).get(f"{book}:{int(dep)}") or {}
    got = {}
    for f in ("n", "usd", "final", "max_dd", "day_median", "win", "taken"):
        a, b = mine.get(f), cell.get(f)
        got[f] = {"здесь": a, "ячейка": b,
                  "равно": (a is None and b is None)
                  or (a is not None and b is not None
                      and abs(float(a) - float(b)) <= 1e-9)}
    got["все_равны"] = all(v["равно"] for v in got.values()
                           if isinstance(v, dict))
    return got


# --- контроль: случайное урезание того же размера ------------------------

def cut_draws(packed, pool, sizes, dep, ctx, books=BOOKS, seeds=SEEDS,
              now=None, log=_quiet, seed0=7000, tag=""):
    """Случайные урезания ТОГО ЖЕ размера — по каждой книге своё.

    Правило РЕЖЕТ число сделок, а книга на меньшем числе сделок меняется
    сама по себе: пятый замер подряд закрывался ровно этим. Пул —
    ВЗЯТЫЕ позиции базы: спорить с правилом обязана выборка из того же,
    что оно вычёркивает. Зёрна номерами, доля разрешается 1/зёрна.
    """
    out = {bk: [] for bk in books}
    t0 = time.time()
    with only(dep):
        for i in range(int(seeds)):
            rnd = random.Random(int(seed0) + i)
            sub = {}
            for bk in books:
                p = list(pool.get(bk) or [])
                n = min(int(sizes.get(bk) or 0), len(p))
                gone = set(rnd.sample(p, n)) if n else set()
                sub[bk] = [r for r in (packed.get(bk) or [])
                           if RP._key(r) not in gone]
            rows, cells, _o, _l = RP.build_rows(sub, now=now,
                                                keys=list(books), log=_quiet)
            for bk in books:
                out[bk].append(form_of(rows, dep, ctx, bk, cells))
            if i and i % 50 == 0:
                log(f"контроль{tag}: {i} зёрен из {seeds}, "
                    f"{time.time() - t0:.0f} с")
    return out


def _median_of(draws, field):
    vals = sorted(float(d[field]) for d in (draws or [])
                  if d.get(field) is not None)
    return None if not vals else round(vals[len(vals) // 2], 4)


def beats(draws, form, fields=CTL_FIELDS):
    """Доля зёрен, где СЛУЧАЙНОЕ урезание не хуже правила — по каждой
    величине спора. Считается общей мерой (`agree_book.beat_share`)."""
    out = {}
    for f in fields:
        sh, n = AG.beat_share(draws, (form or {}).get(f), f)
        out[f] = {"share": sh, "n": n, "value": (form or {}).get(f),
                  "median": _median_of(draws, f)}
    return out


def verdict_of(share, beat_max=BEAT_MAX):
    """Фраза вердикта ВЫВОДИТСЯ из доли зёрен, а не стоит рядом с ней.

    Фраза, стоящая литералом рядом с числом, стареет молча и однажды
    противоречит своему же числу.
    """
    if share is None:
        return "не измерено: контроля нет"
    return ("правило бьёт случайное урезание того же размера"
            if float(share) < float(beat_max)
            else "правило неотличимо от случайного урезания того же размера")


# --- шаг 0: повторы после своего хвостового выхода -----------------------

def repeats_of(taken, grid=PAUSE_GRID_H, exits=TRIGGER_EXITS):
    """Шаг 0: сколько повторов у книги, чего они стоят и где лежат.

    Считается по ВЗЯТЫМ позициям базы: повтор — позиция, которую книга
    открыла, хотя правило паузы её бы запретило. Печатаются обе
    трактовки триггера (`mode`) — правило говорит о предыдущей позиции,
    шаг 0 задания о последнем хвостовом выходе.
    """
    n = len(taken)
    tail = [r for r in taken if (r.get("exit") or "") in exits]
    tail_usd = round(sum(float(r.get("usd") or 0.0) for r in tail), 2)
    cells = {}
    for p in grid:
        got = {}
        for mode in ("prev", "tail"):
            b = blocked_of(taken, taken, p, exits=exits, mode=mode)
            keys = set(x["key"] for x in b)
            rep = [r for r in taken if RP._key(r) in keys]
            rep_tail = [r for r in rep if (r.get("exit") or "") in exits]
            gaps = sorted(x["gap_h"] for x in b)
            by_day = collections.defaultdict(float)
            for r in rep:
                d = time.strftime("%Y-%m-%d", time.gmtime(float(r["exit_ts"])))
                by_day[d] += float(r.get("usd") or 0.0)
            got[mode] = {
                "n": len(rep),
                # «Не измерено» ≠ ноль: доли без знаменателя не бывает.
                "share": (None if not n else round(len(rep) / n, 4)),
                "usd": round(sum(float(r.get("usd") or 0.0) for r in rep), 2),
                "tail_n": len(rep_tail),
                "tail_share": (None if not tail
                               else round(len(rep_tail) / len(tail), 4)),
                "usd_tail": round(sum(float(r.get("usd") or 0.0)
                                      for r in rep_tail), 2),
                "pause_median_h": (None if not gaps
                                   else round(gaps[len(gaps) // 2], 2)),
                "named_day": (round(by_day[NAMED_DAY], 2)
                              if NAMED_DAY in by_day else None),
                "worst_day": (None if not by_day
                              else min(by_day.items(), key=lambda kv: kv[1])),
                # Деньги повторов ПО СУТКАМ: заявка ждёт мельче худший
                # день, а из чего он сложен, итог не говорит.
                "by_day": {k: round(v, 2) for k, v in sorted(by_day.items())},
                "keys": sorted(keys)}
        cells[p] = got
    return {"n": n, "tail_n": len(tail), "tail_usd": tail_usd, "cells": cells}


def step0_killer(rep, p=KILL_P_H, mode=KILL_MODE, min_n=MIN_REPEATS,
                 min_share=MIN_SHARE):
    """Убийца шага 0: правило инертно — судить нечего, заявка закрыта.

    Ячейка убийцы объявлена ЗАДАНИЕМ и не равна ячейке вердикта: считается
    вход не позже 24 ч после собственного хвостового выхода. Вердикт
    выводится из ДВУХ чисел сразу, и оба названы заданием: меньше `min_n`
    позиций ИЛИ меньше `min_share` сделок.
    """
    c = ((rep or {}).get("cells") or {}).get(p, {}).get(mode) or {}
    n, share = c.get("n"), c.get("share")
    if n is None or share is None:
        return {"fired": None, "why": "повторы не посчитаны: нет базы"}
    inert = (int(n) < int(min_n) or float(share) < float(min_share))
    return {"fired": bool(inert), "n": n, "share": share,
            "p_h": float(p), "mode": mode,
            "why": (f"повторов за {float(p):g} ч {n} при пороге {min_n} и "
                    f"доля сделок {100.0 * float(share):.1f} % при пороге "
                    f"{100.0 * float(min_share):.0f} % — "
                    + ("правило инертно, судить нечего" if inert
                       else "правилу есть что резать"))}


# --- шаг 1г: переодетое плечо -------------------------------------------

def lev_perm(taken, rep_keys, perms=PERMS, high=HIGH_LEV,
             exits=TRIGGER_EXITS, seed=11):
    """Доля хвостовых исходов у повторов против остальных В ПОЛОСЕ ПЛЕЧА.

    Хвост живёт на большом плече по построению (пол капитуляции ближе), и
    признак, связанный с плечом, «найдётся» из-за него. Приём тот же, что
    у скрина хвоста: метки перемешиваются `perms` раз, печатается доля
    перестановок, давших разрыв не меньше наблюдаемого.
    """
    band = [r for r in taken if float(r.get("lev") or 0.0) >= float(high)]
    x = np.array([1.0 if RP._key(r) in rep_keys else 0.0 for r in band])
    y = np.array([1.0 if (r.get("exit") or "") in exits else 0.0
                  for r in band])
    if x.sum() < 1 or (1.0 - x).sum() < 1:
        # Величины нет — прочерк с названной причиной, а не ноль: ноль
        # здесь читался бы как «разрыва нет».
        return {"n_band": len(band), "n_rep": int(x.sum()), "gap": None,
                "perm": None, "why": "в полосе плеча нет обеих групп"}
    gap = float(y[x == 1].mean() - y[x == 0].mean())
    rng = np.random.default_rng(int(seed))
    hits = 0
    for _ in range(int(perms)):
        p = rng.permutation(x)
        g = float(y[p == 1].mean() - y[p == 0].mean())
        if g >= gap:
            hits += 1
    return {"n_band": len(band), "n_rep": int(x.sum()),
            "tail_rep": round(float(y[x == 1].mean()), 4),
            "tail_rest": round(float(y[x == 0].mean()), 4),
            "gap": round(gap, 4), "perm": round(hits / max(1, int(perms)), 4),
            "perms": int(perms), "high_lev": float(high)}


# --- калибровка ----------------------------------------------------------

def shuffled(packed, books=BOOKS, seed=101, exits=TRIGGER_EXITS):
    """Копия записей с ПЕРЕМЕШАННЫМИ метками исходов.

    Перемешиваются только метки (`exit`) закрытых записей: деньги,
    плечо, отметки и сроки остаются своими. Значит триггер становится
    случайным относительно денег — и правило обязано оказаться В
    ПРЕДЕЛАХ случайного урезания. Нуль честной формы: без него сломанная
    загрузка выглядела бы ровно как «эффекта нет».
    """
    out = {}
    for bk in books:
        recs = list(packed.get(bk) or [])
        idx = [i for i, r in enumerate(recs)
               if (r.get("state") or "closed") == "closed"
               and r.get("exit") is not None]
        labels = [recs[i].get("exit") for i in idx]
        random.Random(int(seed)).shuffle(labels)
        got = list(recs)
        for i, lab in zip(idx, labels):
            got[i] = dict(recs[i], exit=lab)
        out[bk] = got
    return out


def planted(packed, keys, pnl=PLANT_PNL, books=BOOKS):
    """Копия записей, где ПОВТОРАМ переписан исход на `pnl` долей маржи.

    Записи не выдуманы: берутся живые (их поля, плечо, входы, сроки), и
    меняется исход — сам он и отметки, чтобы сумма отметок равнялась
    исходу. Запись, у которой отметки не сходятся с исходом, живой не
    бывает, и касса с правилом охраны читают её иначе.
    """
    out = {}
    for bk in books:
        got = []
        for r in packed.get(bk) or []:
            if RP._key(r) not in (keys.get(bk) or set()):
                got.append(r)
                continue
            marks = [list(m) for m in (r.get("marks") or [])]
            if marks:
                head = sum(float(m[1]) for m in marks[:-1])
                marks[-1][1] = round(float(pnl) - head, 6)
            new = dict(r, pnl=float(pnl), marks=marks)
            if r.get("pnl_net") is not None:
                new["pnl_net"] = float(pnl) - (float(r["pnl"])
                                               - float(r["pnl_net"]))
            got.append(new)
        out[bk] = got
    return out


@contextlib.contextmanager
def cache_locked():
    """Кэш реплея только ЧИТАЕТСЯ: писатель подменяется отказом.

    Пауза меняет состав книги, а не исход позиции, поэтому подпись кэша
    не трогается вовсе. «Не переписываем» здесь не обещание в
    комментарии, а механизм: попытка записи роняет прогон с названной
    причиной.
    """
    real = S.write_cache

    def refuse(*_a, **_k):
        raise RuntimeError("механика не вправе переписывать кэш реплея: "
                           "пауза меняет состав книги, а не исход позиции")

    S.write_cache = refuse
    try:
        yield refuse
    finally:
        S.write_cache = real


# --- прогон --------------------------------------------------------------

def base_of(packed, dep, ctx, books=BOOKS, now=None, log=_quiet):
    """База: касса на подготовленных записях и форма каждой книги."""
    with only(dep):
        rows, cells, _o, _l = RP.build_rows(packed, now=now,
                                            keys=list(books), log=log)
    taken = {bk: taken_of(rows, bk, dep) for bk in books}
    form = {bk: form_of(rows, dep, ctx, bk, cells) for bk in books}
    return {"rows": rows, "cells": cells, "taken": taken, "form": form}


def branch(packed, base, dep, ctx, pause_h, books=BOOKS, exits=TRIGGER_EXITS,
           trigger="taken", now=None, log=_quiet, seeds=SEEDS, seed0=7000,
           tag="", draws=True):
    """Одна ветка: состав с паузой, его форма и контроль того же размера."""
    sis = sister(packed, dep, pause_h, books=books, exits=exits,
                 trigger=trigger, now=now, log=log)
    form = {bk: form_of(sis["rows"], dep, ctx, bk, sis["cells"])
            for bk in books}
    cut_keys = {bk: [x["key"] for x in sis["cut"][bk]] for bk in books}
    base_keys = {bk: set(RP._key(r) for r in base["taken"][bk])
                 for bk in books}
    # Размер спора — сколько ВЗЯТЫХ базой позиций сняло правило: снятое
    # решение, которого касса и так не брала, денег книги не меняет.
    cut_taken = {bk: [k for k in cut_keys[bk] if k in base_keys[bk]]
                 for bk in books}
    sizes = {bk: len(cut_taken[bk]) for bk in books}
    got = {"pause_h": float(pause_h), "trigger": trigger,
           "exits": list(exits), "steps": sis["steps"], "form": form,
           "cut_n": {bk: len(cut_keys[bk]) for bk in books},
           "cut_taken_n": dict(sizes),
           "cut_taken": {bk: list(cut_taken[bk]) for bk in books},
           "cut": {bk: sis["cut"][bk][:200] for bk in books}}
    if not draws or not seeds or not any(sizes.values()):
        got["control"] = ({"why": "вычеркнутых взятых позиций нет — "
                                  "урезать нечего и спорить не о чем"}
                          if not any(sizes.values()) else None)
        return got, sis
    pool = {bk: sorted(base_keys[bk]) for bk in books}
    d = cut_draws(packed, pool, sizes, dep, ctx, books=books, seeds=seeds,
                  now=now, log=log, seed0=seed0, tag=tag)
    got["control"] = {bk: beats(d[bk], form[bk]) for bk in books}
    got["seeds"] = int(seeds)
    return got, sis


def run(seeds=SEEDS, perms=PERMS, dep=DEP, deps=DEPS, books=BOOKS,
        grid=PAUSE_GRID_H, log=print, now=None, launch=None, ctx=None,
        cache=None, mkt=None, mem_limit=None, full=True):
    """Механика целиком, в объявленном заданием порядке."""
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    with cache_locked():
        ctx = CO.context() if ctx is None else ctx
        launch = IR.launches() if launch is None else launch
        if cache is None:
            cache, why = S.read_cache(log=log)
            if why:
                return {"error": f"кэш реплея непригоден: {why}"}
        packed0 = AG.packed_short(cache)
        if not any(packed0.get(bk) for bk in books):
            return {"error": "в кэше реплея нет записей коротких книг — "
                             "считать нечего, и это отказ, а не отчёт"}
        prep, ages, guards = prepare(packed0, launch, books=books, now=now,
                                     mkt=mkt, log=log)
        log("записей после возраста и охраны: "
            + ", ".join(f"{bk} {len(prep[bk])}" for bk in books))
        base = base_of(prep, dep, ctx, books=books, now=now, log=log)
        if not base["taken"].get(BOOK):
            return {"error": "книга вердикта не взяла ни одной позиции при "
                             "непустом входе — отказ, а не отчёт с "
                             "прочерками"}
        # Метка плацебо ПРОВЕРЯЕТСЯ на данных: исхода, которого в журнале
        # нет вовсе, плацебо не бывает — молчаливый ноль выглядел бы как
        # «плацебо эффекта не дало».
        seen = set(r.get("exit") for bk in books for r in base["taken"][bk])
        placebo_why = (None if TAKE_EXIT in seen
                       else f"исхода «{TAKE_EXIT}» в книге нет вовсе")
        s = {"mech": MECH, "book": BOOK, "dep": int(dep),
             "books": list(books), "deps": [int(d) for d in deps],
             "grid": list(grid), "verdict_p_h": float(VERDICT_P_H),
             "trigger_exits": list(TRIGGER_EXITS), "seeds": int(seeds),
             "perms": int(perms), "named_day": NAMED_DAY,
             "ages": ages, "guards": guards,
             "costs_error": (ctx or {}).get("error"),
             "placebo_why": placebo_why,
             "base": {bk: base["form"][bk] for bk in books},
             "agree": agrees_with_cell(packed0, ctx, launch, dep=dep,
                                       book=BOOK, now=now, log=_quiet,
                                       mkt=mkt)}
        # --- шаг 0 -----------------------------------------------------
        s["step0"] = {bk: repeats_of(base["taken"][bk], grid=grid)
                      for bk in books}
        s["killers"] = {"0": step0_killer(s["step0"][BOOK])}
        log(f"шаг 0: {s['killers']['0']['why']}")
        # --- калибровка ------------------------------------------------
        s["calib"] = calibrate(prep, base, dep, ctx, books=books,
                               seeds=seeds, now=now, log=log)
        if not s["calib"].get("ok"):
            s["error"] = ("калибровочная пара не сошлась: "
                          + "; ".join(s["calib"].get("why") or []))
            s["secs"] = round(time.time() - t0, 1)
            return s
        # --- шаг 1а: потолок с идеальным знанием будущего ---------------
        s["ceiling"] = ceiling(prep, base, dep, ctx, books=books, seeds=seeds,
                               p=VERDICT_P_H, now=now, log=log)
        s["killers"]["1а"] = killer_of(s["ceiling"].get("control"), BOOK,
                                       "потолок с идеальным знанием "
                                       "будущего")
        log(f"шаг 1а: {s['killers']['1а']['why']}")
        # --- шаг 1б: правило против случайного урезания -----------------
        s["rule"] = {}
        for p in grid:
            got, _sis = branch(prep, base, dep, ctx, p, books=books,
                               now=now, log=log,
                               seeds=(seeds if p == VERDICT_P_H else 0),
                               seed0=7000 + int(p), tag=f" P={p:g}")
            s["rule"][p] = got
            log(f"шаг 1б: P={p:g} ч, снято "
                + ", ".join(f"{bk} {got['cut_taken_n'][bk]} взятых "
                            f"({got['steps'][bk]} шагов)" for bk in books))
        s["killers"]["1б"] = killer_of(
            (s["rule"].get(VERDICT_P_H) or {}).get("control"), BOOK,
            f"правило P={VERDICT_P_H:g} ч")
        log(f"шаг 1б: {s['killers']['1б']['why']}")
        # --- шаг 1в: плацебо -------------------------------------------
        if placebo_why:
            s["placebo"] = {"why": placebo_why}
            s["killers"]["1в"] = {"fired": None, "why": placebo_why}
        else:
            pl, _ps = branch(prep, base, dep, ctx, VERDICT_P_H, books=books,
                             exits=PLACEBO_EXITS, now=now, log=log,
                             seeds=seeds, seed0=9000, tag=" плацебо")
            s["placebo"] = pl
            # Число вычеркнутых УРАВНЕНО: из снятого плацебо берётся
            # случайное подмножество размером с правило, и спор идёт на
            # одинаковом числе сделок.
            rule_sizes = {bk: (s["rule"].get(VERDICT_P_H) or {})
                          .get("cut_taken_n", {}).get(bk, 0) for bk in books}
            if seeds and any(rule_sizes.values()):
                eq = cut_draws(prep, {bk: pl["cut_taken"][bk] for bk in books},
                               rule_sizes, dep, ctx, books=books, seeds=seeds,
                               now=now, log=log, seed0=9500,
                               tag=" плацебо (уравнено)")
                rule_form = (s["rule"].get(VERDICT_P_H) or {}).get("form") \
                    or {}
                s["placebo_eq"] = {"sizes": rule_sizes}
                for bk in books:
                    s["placebo_eq"][bk] = beats(eq[bk], rule_form.get(bk))
            s["killers"]["1в"] = placebo_killer(s, BOOK)
            log(f"шаг 1в: {s['killers']['1в']['why']}")
        # --- шаг 1г: переодетое плечо ----------------------------------
        rep_keys = set(((s["step0"][BOOK].get("cells") or {})
                        .get(VERDICT_P_H, {}).get("prev") or {}).get("keys")
                       or [])
        s["lev"] = lev_perm(base["taken"][BOOK], rep_keys, perms=perms)
        s["killers"]["1г"] = lev_killer(s["lev"])
        log(f"шаг 1г: {s['killers']['1г']['why']}")
        # --- шаг 2: форма по книгам и депозитам ------------------------
        s["form"] = {}
        if full:
            for d in deps:
                if int(d) == int(dep):
                    s["form"][int(d)] = {
                        "base": {bk: base["form"][bk] for bk in books},
                        "sister": (s["rule"].get(VERDICT_P_H) or {})
                        .get("form")}
                    continue
                b2 = base_of(prep, d, ctx, books=books, now=now, log=_quiet)
                got, _x = branch(prep, b2, d, ctx, VERDICT_P_H, books=books,
                                 now=now, log=log, seeds=0)
                s["form"][int(d)] = {
                    "base": {bk: b2["form"][bk] for bk in books},
                    "sister": got.get("form"),
                    "cut_taken_n": got.get("cut_taken_n")}
                log(f"шаг 2: депозит ${int(d)} посчитан")
        # --- диагностика вариантов триггера ----------------------------
        s["variants"] = {}
        if full:
            for name, kw in (("любое решение имени (кэш реплея)",
                              {"trigger": "cache"}),
                             ("исходы с добавленным «рынок»",
                              {"exits": TRIGGER_EXITS + (MARKET_EXIT,)})):
                got, _x = branch(prep, base, dep, ctx, VERDICT_P_H,
                                 books=books, now=now, log=log, seeds=0, **kw)
                s["variants"][name] = {
                    "cut_taken_n": got["cut_taken_n"], "steps": got["steps"],
                    "form": got["form"]}
                log(f"вариант триггера «{name}»: снято "
                    + ", ".join(f"{bk} {got['cut_taken_n'][bk]}"
                                for bk in books))
        # --- шаг 3: вперёд ---------------------------------------------
        s["forward"] = forward_of(s, now=now)
        s["verdict"] = overall(s)
        s["computed_at"] = G.stamp()
        s["secs"] = round(time.time() - t0, 1)
        return s


def killer_of(control, book, title, beat_max=BEAT_MAX, field=MAIN_FIELD):
    """Убийца шагов 1а–1б: случайное урезание не хуже правила.

    Спор идёт по ОДНОЙ объявленной величине — «$ без 3 лучших дней»;
    остальные печатаются рядом и вердикта не выносят.
    """
    if not control or (control or {}).get("why"):
        return {"fired": None,
                "why": f"{title}: контроля нет — "
                       + ((control or {}).get("why") or "не считался")}
    c = ((control or {}).get(book) or {}).get(field) or {}
    sh = c.get("share")
    if sh is None:
        return {"fired": None, "why": f"{title}: доля зёрен не измерена"}
    fired = float(sh) >= float(beat_max)
    return {"fired": bool(fired), "share": sh, "field": field,
            "why": (f"{title}: случайное урезание не хуже в "
                    f"{100.0 * float(sh):.0f} % зёрен из {c.get('n')} "
                    f"по величине «{FIELD_TITLE[field]}» — "
                    + verdict_of(sh, beat_max))}


def placebo_killer(s, book, beat_max=BEAT_MAX, field=MAIN_FIELD):
    """Убийца 1в: плацебо (пауза после ТЕЙКА) даёт то же или лучше.

    Сравниваются две величины: доля зёрен у плацебо против его
    собственного случайного урезания и уравненное по числу сделок
    сравнение с правилом.
    """
    pl = (s.get("placebo") or {})
    c = ((pl.get("control") or {}).get(book) or {}).get(field) or {}
    rule = ((s.get("rule") or {}).get(VERDICT_P_H) or {})
    rv = (rule.get("form") or {}).get(book, {}).get(field)
    pv = (pl.get("form") or {}).get(book, {}).get(field)
    eq = ((s.get("placebo_eq") or {}).get(book) or {}).get(field) or {}
    parts = []
    if c.get("share") is not None:
        parts.append(f"плацебо против своей выборки: не хуже в "
                     f"{100.0 * float(c['share']):.0f} % зёрен")
    if eq.get("share") is not None:
        parts.append(f"уравненное по числу сделок плацебо не хуже правила "
                     f"в {100.0 * float(eq['share']):.0f} % зёрен")
    if rv is not None and pv is not None:
        parts.append(f"«{FIELD_TITLE[field]}»: правило {float(rv):+.0f}, "
                     f"плацебо {float(pv):+.0f}")
    fired = None
    if eq.get("share") is not None:
        fired = float(eq["share"]) >= float(beat_max)
    elif c.get("share") is not None and rv is not None and pv is not None:
        fired = float(pv) >= float(rv)
    return {"fired": (None if fired is None else bool(fired)),
            "why": ("шаг 1в: " + "; ".join(parts) if parts
                    else "шаг 1в: плацебо не посчитано")
            + ("" if fired is None else
               (" — утверждение «после ПРОИГРЫША» мертво, остаток есть "
                "«меньше входов»" if fired
                else " — плацебо эффекта не даёт, дело не в числе входов"))}


def lev_killer(lev, perm_max=PERM_MAX):
    """Убийца 1г: разрыв принадлежит оси плеча."""
    if not lev or lev.get("perm") is None:
        return {"fired": None,
                "why": "шаг 1г: " + ((lev or {}).get("why")
                                     or "перестановки не считались")}
    fired = float(lev["perm"]) >= float(perm_max)
    return {"fired": bool(fired), "perm": lev["perm"],
            "why": (f"шаг 1г: в полосе плеча ≥ {lev['high_lev']:g}× хвост у "
                    f"повторов {100.0 * float(lev['tail_rep']):.0f} % "
                    f"против {100.0 * float(lev['tail_rest']):.0f} % у "
                    f"остальных, перестановки дают такой же разрыв в "
                    f"{100.0 * float(lev['perm']):.0f} % случаев — "
                    + ("разрыв принадлежит оси плеча" if fired
                       else "разрыв не объясняется плечом"))}


def ceiling(packed, base, dep, ctx, books=BOOKS, seeds=SEEDS, p=VERDICT_P_H,
            now=None, log=_quiet):
    """Шаг 1а: потолок с ИДЕАЛЬНЫМ ЗНАНИЕМ БУДУЩЕГО.

    Вычёркиваются только те повторы, что кончились хвостом, — верхняя
    граница любого правила на этом признаке. Потолок считается ПЕРВЫМ из
    денежных шагов: он закрывает направление за минуты, если даже
    всезнающее правило не бьёт случайное урезание.
    """
    cut, pool, sizes = {}, {}, {}
    for bk in books:
        taken = base["taken"][bk]
        b = blocked_of(taken, taken, p, mode="prev")
        keys = set(x["key"] for x in b)
        cut[bk] = [RP._key(r) for r in taken if RP._key(r) in keys
                   and (r.get("exit") or "") in TRIGGER_EXITS]
        pool[bk] = sorted(RP._key(r) for r in taken)
        sizes[bk] = len(cut[bk])
    gone = {bk: set(cut[bk]) for bk in books}
    sub = {bk: [r for r in (packed.get(bk) or [])
                if RP._key(r) not in gone[bk]] for bk in books}
    with only(dep):
        rows, cells, _o, _l = RP.build_rows(sub, now=now, keys=list(books),
                                            log=_quiet)
    form = {bk: form_of(rows, dep, ctx, bk, cells) for bk in books}
    got = {"pause_h": float(p), "cut_n": dict(sizes), "form": form}
    if not seeds or not any(sizes.values()):
        got["control"] = {"why": "повторов, кончившихся хвостом, нет — "
                                 "потолок пуст"} if not any(sizes.values()) \
            else None
        return got
    d = cut_draws(packed, pool, sizes, dep, ctx, books=books, seeds=seeds,
                  now=now, log=log, seed0=6000, tag=" потолок")
    got["control"] = {bk: beats(d[bk], form[bk]) for bk in books}
    got["seeds"] = int(seeds)
    return got


def calibrate(packed, base, dep, ctx, books=BOOKS, seeds=SEEDS, now=None,
              log=_quiet, book=BOOK, p=VERDICT_P_H):
    """Калибровочная пара: найти подсаженное и промолчать на шуме.

    Три ноги, и каждая объявлена заданием:

    (i)   пауза 0 ч — сестра равна базе БИТ В БИТ по числу сделок,
          деньгам, итогу, просадке и медиане дня;
    (ii)  перемешанные метки исходов — правило обязано остаться В
          ПРЕДЕЛАХ случайного урезания и эффекта не объявить;
    (iii) подсаженные повторы (исход −0.9 доли маржи) — правило обязано
          бить случайное урезание того же размера.

    Без неё сломанная загрузка выглядит ровно как «эффекта нет», и это
    уже дважды случалось.
    """
    why, got = [], {}
    # (i) пауза 0 ч
    zero, _z = branch(packed, base, dep, ctx, 0.0, books=books, now=now,
                      log=_quiet, seeds=0)
    same = {}
    for f in ("n", "usd", "final", "max_dd", "day_median"):
        a = (zero["form"].get(book) or {}).get(f)
        b = (base["form"].get(book) or {}).get(f)
        same[f] = {"пауза 0": a, "база": b,
                   "равно": (a is None and b is None)
                   or (a is not None and b is not None
                       and abs(float(a) - float(b)) <= 1e-12)}
    cut0 = sum(zero["cut_taken_n"].values())
    same["снято"] = {"пауза 0": cut0, "база": 0, "равно": cut0 == 0}
    got["zero"] = same
    if not all(v["равно"] for v in same.values()):
        why.append("пауза 0 ч не равна базе — сестра считает другую книгу")
    # (ii) перемешанные метки исходов
    sh_packed = shuffled(packed, books=books)
    sh_base = base_of(sh_packed, dep, ctx, books=books, now=now, log=_quiet)
    sh_branch, _s = branch(sh_packed, sh_base, dep, ctx, p, books=books,
                           now=now, log=log, seeds=seeds, seed0=3000,
                           tag=" калибровка (шум)")
    sh_share = (((sh_branch.get("control") or {}).get(book) or {})
                .get(MAIN_FIELD) or {}).get("share")
    got["shuffle"] = {"cut_taken_n": sh_branch.get("cut_taken_n"),
                      "share": sh_share,
                      "verdict": verdict_of(sh_share)}
    if sh_share is not None and float(sh_share) < BEAT_MAX:
        why.append("на перемешанных метках правило «работает» — нуль не "
                   "честной формы, числа читать нельзя")
    # (iii) подсадка
    rep = {}
    for bk in books:
        taken = base["taken"][bk]
        rep[bk] = set(x["key"] for x in blocked_of(taken, taken, p,
                                                   mode="prev"))
    pl_packed = planted(packed, rep, books=books)
    pl_base = base_of(pl_packed, dep, ctx, books=books, now=now, log=_quiet)
    pl_branch, _p = branch(pl_packed, pl_base, dep, ctx, p, books=books,
                           now=now, log=log, seeds=seeds, seed0=4000,
                           tag=" калибровка (подсадка)")
    pl_share = (((pl_branch.get("control") or {}).get(book) or {})
                .get(MAIN_FIELD) or {}).get("share")
    got["plant"] = {"n": {bk: len(rep[bk]) for bk in books},
                    "pnl": PLANT_PNL, "share": pl_share,
                    "verdict": verdict_of(pl_share)}
    if pl_share is None:
        why.append("подсадку судить нечем: контроля нет")
    elif float(pl_share) >= BEAT_MAX:
        why.append("подсаженные повторы НЕ находятся: правило не бьёт "
                   "случайное урезание даже там, где эффект посажен руками")
    got["ok"] = not why
    got["why"] = why
    return got


def forward_of(s, now=None):
    """Шаг 3: правило вылета пула и то, чего пока не измерить.

    Сестра не объявлена, форвардных суток у неё ноль — вердикта по форме
    не бывает, и это прочерк с названной причиной, а не «правило
    прошло». Пороги берутся у самого правила (`factory/pool.py`), а не
    повторяются числами.
    """
    rule = ((s.get("rule") or {}).get(VERDICT_P_H) or {})
    form = (rule.get("form") or {}).get(BOOK) or {}
    base = (s.get("base") or {}).get(BOOK) or {}
    daily = form.get("daily") or {}
    days = len(daily)
    med, bite = form.get("med"), form.get("bite")
    # Форма СЕСТРЫ по мерам правила вылета печатается, но вердиктом не
    # становится: правило вылета судит ФОРВАРД, а форвардных суток у
    # необъявленной сестры ноль. Фраза выводится из этого числа.
    would = None
    if med is not None:
        would = (f"по пересчёту медиана дня {float(med):+.2f} при пороге "
                 f"{PL.MIN_MED_DAY:g}, укус "
                 + ("—" if bite is None else f"{float(bite):.1f}")
                 + f" при пределе {PL.MAX_BITE:g}")
    return {"min_med": PL.MIN_MED_DAY, "max_bite": PL.MAX_BITE,
            "min_days": ST.MIN_DAYS, "days_backtest": days,
            "days_forward": 0,
            "why": (f"форвардных суток 0 при {days} сутках пересчёта — "
                    "вердикта по правилу вылета здесь нет и быть не может; "
                    + (would or "форма сестры не посчитана")),
            "med": med, "bite": bite,
            "base_med": base.get("med"), "base_bite": base.get("bite")}


def overall(s):
    """Итог механики — из того, какой убийца сработал ПЕРВЫМ."""
    order = ("0", "1а", "1б", "1в", "1г")
    for k in order:
        kil = (s.get("killers") or {}).get(k) or {}
        if kil.get("fired"):
            return {"closed_at": k, "why": kil.get("why")}
    unknown = [k for k in order
               if ((s.get("killers") or {}).get(k) or {}).get("fired") is None]
    return {"closed_at": None,
            "why": ("ни один убийца не сработал"
                    + (f"; не измерены шаги: {', '.join(unknown)}"
                       if unknown else "")),
            "unknown": unknown}


# --- показ ---------------------------------------------------------------

def _u(x, d=2):
    return "—" if x is None else f"{float(x):+.{d}f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _s(x, d=1):
    """Доля без знака: доли, где знак бессмыслен (зелёные, доля зёрен)."""
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _r(x):
    return "—" if x is None else f"{float(x):.2f}"


def _n(x):
    return "—" if x is None else str(x)


def _share_cell(c):
    c = c or {}
    return ("—" if c.get("share") is None
            else f"{_s(c['share'], 0)} из {c.get('n')}")


FORM_HEAD = ("| ветка | сделок | взято кассой | Σ $ | итог | просадка | "
             "доход/просадка | медиана дня | среднее дня | зелёных | укус | "
             "худший день | $ без 3 лучших дней | $ без лучшего имени | "
             "просадка без худшего дня | " + NAMED_DAY + " |")
FORM_SEP = ("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"
            "--:|")


def form_row(title, f):
    """Строка формы — обязательные колонки заявки, все в одном месте."""
    f = f or {}
    # Худший день печатается деньгами и датой сразу: доля депозита без
    # даты не отвечает на вопрос «тот же это день, что у базы, или
    # другой», а ради него колонка и стоит.
    worst = (None if f.get("day_worst") is None or not f.get("dep")
             else float(f["day_worst"]) * float(f["dep"]))
    return (f"| {title} | {_n(f.get('n'))} | {_n(f.get('taken'))} | "
            f"{_u(f.get('usd'))} | {_p(f.get('final'))} | "
            f"{_p(f.get('max_dd'))} | {_r(f.get('ratio'))} | "
            f"{_u(f.get('med'))} | {_u(f.get('mean'))} | "
            f"{_s(f.get('green'))} | {_r(f.get('bite'))} | "
            + (f"{_u(worst, 0)}"
               + (f" ({f.get('worst_day')})" if f.get("worst_day") else ""))
            + f" | {_u(f.get('usd_wo_top3d'))} | {_u(f.get('usd_wo_top'))} | "
            f"{_p(f.get('max_dd_wo_worst'))} | {_u(f.get('named_day'))} |")


def report(s):
    L = [f"# Механика {MECH} — пауза по имени после хвостового выхода", "",
         "Правило заявки одной строкой: **короткая книга `h24` не "
         "открывает шорт в имени X, если её СОБСТВЕННАЯ предыдущая "
         "позиция в X закрылась исходом «"
         + "» или «".join(TRIGGER_EXITS) + "» меньше P часов назад**. Ось "
         "P — " + " / ".join(f"{p:g}" for p in PAUSE_GRID_H)
         + f" ч, объявлена брифом и скрином хвоста; ячейка вердикта — "
         f"СЕРЕДИНА оси, P = {VERDICT_P_H:g} ч, как у охраны рынком. Книга "
         f"вердикта — `{BOOK}` на ${int(DEP)}, деньги нетто; остальные "
         "книги и депозиты — диагностика без вердикта.", "",
         "Заявка НЕ утверждает, что пауза снимает хвост как класс (первая "
         "ставка против разгона остаётся полной), что она поднимает доход "
         "(она вычёркивает сделки, и вычеркнутые могут оказаться деньгами "
         "книги) и что она даёт пулу новую полосу.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", "",
                              "Числа ниже не печатаются намеренно: отказ, "
                              "неотличимый от исправности, — главный "
                              "дефект этого проекта.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}. Числа "
              "брутто.", ""]
    v = s.get("verdict") or {}
    L += ["## Итог", "",
          (f"**Заявка закрыта на шаге {v['closed_at']}.** {v.get('why')}"
           if v.get("closed_at")
           else f"**Ни один убийца не сработал.** {v.get('why')}"), "",
          "Сработавший убийца закрывает заявку; шаги ниже печатаются без "
          "вердикта — они остаются описанием, а не доводом.", ""]
    ag = s.get("agree") or {}
    L += ["| поле | здесь | ячейка семейства | равно |", "|---|--:|--:|:-:|"]
    for f in ("n", "usd", "final", "max_dd", "day_median", "win", "taken"):
        c = ag.get(f) or {}
        L.append(f"| {f} | {_n(c.get('здесь'))} | {_n(c.get('ячейка'))} | "
                 + ("да" if c.get("равно") else "**НЕТ**") + " |")
    L += ["", "Сверка с ячейкой семейства (`short_grid.cell_stats`): здесь "
          "не заведена вторая касса, и это число, а не обещание. "
          + ("Все поля сошлись." if ag.get("все_равны")
             else "**Поля разошлись — числа ниже читать нельзя.**"), ""]
    # --- шаг 0 ---
    L += ["## Шаг 0. Повторы после своего хвостового выхода", "",
          "Повтор — позиция, которую книга открыла в имени, где сама "
          "только что вышла хвостом. Считается по ВЗЯТЫМ позициям базы. "
          "Две трактовки триггера стоят рядом: правило говорит о "
          "ПРЕДЫДУЩЕЙ позиции, шаг 0 задания — о последнем хвостовом "
          "выходе; различаются они, когда между ними успела встать "
          "позиция с обычным исходом.", "",
          "| книга | сделок | хвост | P, ч | повторов | доля сделок | "
          "из них хвостовых | доля хвоста | Σ $ повторов | Σ $ хвоста "
          "повторов | медиана паузы, ч | " + NAMED_DAY + " |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in s.get("books") or []:
        st = (s.get("step0") or {}).get(bk) or {}
        for p in s.get("grid") or []:
            c = ((st.get("cells") or {}).get(p) or {}).get("prev") or {}
            L.append(f"| {R.ruler_title(bk)} | {_n(st.get('n'))} | "
                     f"{_n(st.get('tail_n'))} | {float(p):g} | "
                     f"{_n(c.get('n'))} | {_s(c.get('share'))} | "
                     f"{_n(c.get('tail_n'))} | {_s(c.get('tail_share'))} | "
                     f"{_u(c.get('usd'))} | {_u(c.get('usd_tail'))} | "
                     f"{_r(c.get('pause_median_h'))} | "
                     f"{_u(c.get('named_day'))} |")
    L += ["", "Та же таблица по трактовке «после последнего хвостового "
          "выхода» (диагностика):", "",
          "| книга | P, ч | повторов | доля сделок | Σ $ повторов |",
          "|---|--:|--:|--:|--:|"]
    for bk in s.get("books") or []:
        st = (s.get("step0") or {}).get(bk) or {}
        for p in s.get("grid") or []:
            c = ((st.get("cells") or {}).get(p) or {}).get("tail") or {}
            L.append(f"| {R.ruler_title(bk)} | {float(p):g} | "
                     f"{_n(c.get('n'))} | {_s(c.get('share'))} | "
                     f"{_u(c.get('usd'))} |")
    # Деньги повторов ПО СУТКАМ у книги вердикта: заявка ждёт мельче
    # худший день, и из чего он сложен, итог не говорит.
    cell = (((s.get("step0") or {}).get(BOOK) or {}).get("cells")
            or {}).get(s.get("verdict_p_h") or VERDICT_P_H) or {}
    by_day = ((cell.get("prev") or {}).get("by_day") or {})
    if by_day:
        worst = sorted(by_day.items(), key=lambda kv: kv[1])[:5]
        L += ["", f"Деньги повторов по суткам у книги "
              f"`{BOOK}` при P = {float(s.get('verdict_p_h') or 0):g} ч "
              f"(пять худших суток из {len(by_day)}); сутки {NAMED_DAY} "
              "стоят отдельной строкой в форме:", "",
              "| сутки | $ повторов |", "|---|--:|"]
        L += [f"| {d} | {_u(v)} |" for d, v in worst]
        L += [""]
    k0 = (s.get("killers") or {}).get("0") or {}
    L += ["", f"**Убийца шага 0:** {k0.get('why')} (ячейка убийцы "
          f"объявлена заданием: {float(k0.get('p_h') or 0):g} ч, трактовка "
          f"«{k0.get('mode')}»).", ""]
    # --- калибровка ---
    cal = s.get("calib") or {}
    L += ["## Калибровочная пара", "",
          "Нуль честной формы и подсадка, найденная руками: без них "
          "сломанная загрузка выглядит ровно как «эффекта нет».", "",
          "| нога | что сделано | чего ждали | что вышло |",
          "|---|---|---|---|"]
    z = cal.get("zero") or {}
    L.append("| пауза 0 ч | ни одна запись не снимается | сестра равна базе "
             "бит в бит | "
             + ("равна по всем полям" if all(x.get("равно") for x in z.values()
                                             if isinstance(x, dict))
                else "**РАЗОШЛАСЬ**") + " |")
    sh = cal.get("shuffle") or {}
    L.append("| перемешанные метки исходов | триггер случаен относительно "
             "денег | правило В ПРЕДЕЛАХ случайного урезания | случайное не "
             f"хуже в {_s(sh.get('share'), 0)} зёрен — {sh.get('verdict')} |")
    pl = cal.get("plant") or {}
    L.append(f"| подсадка: повторам исход {PLANT_PNL:+g} доли маржи | "
             "эффект посажен руками | правило бьёт случайное урезание | "
             f"случайное не хуже в {_s(pl.get('share'), 0)} зёрен — "
             f"{pl.get('verdict')} |")
    L += [""]
    # --- шаг 1а ---
    ce = s.get("ceiling") or {}
    L += ["## Шаг 1а. Потолок с идеальным знанием будущего", "",
          "Вычёркиваются ТОЛЬКО те повторы, что кончились хвостом, — "
          "верхняя граница любого правила на этом признаке. Не бьёт "
          "случайное урезание даже она — направление закрыто до постройки "
          "правила.", "",
          "| книга | вычеркнуто | " + " | ".join(FIELD_TITLE[f]
                                                 for f in CTL_FIELDS)
          + " | доля зёрен не хуже (первая величина) |",
          "|---|--:|" + "--:|" * (len(CTL_FIELDS) + 1)]
    for bk in s.get("books") or []:
        f = (ce.get("form") or {}).get(bk) or {}
        c = ((ce.get("control") or {}).get(bk) or {})
        L.append(f"| {R.ruler_title(bk)} | "
                 f"{_n((ce.get('cut_n') or {}).get(bk))} | "
                 + " | ".join(_u(f.get(x)) for x in CTL_FIELDS) + " | "
                 + _share_cell(c.get(MAIN_FIELD) if isinstance(c, dict)
                               else None) + " |")
    L += ["", f"**Убийца шага 1а:** "
          f"{((s.get('killers') or {}).get('1а') or {}).get('why')}.", ""]
    # --- шаг 1б ---
    L += ["## Шаг 1б. Правило против случайного урезания того же размера",
          "",
          "Контроль берётся из ВЗЯТЫХ позиций базы и того же размера, что "
          "сняло правило: книга на меньшем числе сделок меняется сама по "
          "себе, и пятый замер подряд закрывался ровно этим.", "",
          "| книга | P, ч | снято записей | из них взятых базой | шагов | "
          + " | ".join(FIELD_TITLE[f] for f in CTL_FIELDS)
          + " | доля зёрен не хуже (первая величина) |",
          "|---|--:|--:|--:|--:|" + "--:|" * (len(CTL_FIELDS) + 1)]
    for bk in s.get("books") or []:
        for p in s.get("grid") or []:
            b = (s.get("rule") or {}).get(p) or {}
            f = (b.get("form") or {}).get(bk) or {}
            c = ((b.get("control") or {}).get(bk)
                 if isinstance(b.get("control"), dict) else None)
            L.append(f"| {R.ruler_title(bk)} | {float(p):g} | "
                     f"{_n((b.get('cut_n') or {}).get(bk))} | "
                     f"{_n((b.get('cut_taken_n') or {}).get(bk))} | "
                     f"{_n((b.get('steps') or {}).get(bk))} | "
                     + " | ".join(_u(f.get(x)) for x in CTL_FIELDS) + " | "
                     + _share_cell((c or {}).get(MAIN_FIELD)) + " |")
    L += ["", f"**Убийца шага 1б:** "
          f"{((s.get('killers') or {}).get('1б') or {}).get('why')}.", ""]
    # --- шаг 1в ---
    L += ["## Шаг 1в. Плацебо: та же пауза после ПРИБЫЛЬНОГО выхода", ""]
    pl = s.get("placebo") or {}
    if pl.get("why"):
        L += [f"Не посчитано: {pl['why']}.", ""]
    else:
        L += ["| книга | снято записей | из них взятых базой | "
              + " | ".join(FIELD_TITLE[f] for f in CTL_FIELDS)
              + " | доля зёрен не хуже | уравненное плацебо против правила |",
              "|---|--:|--:|" + "--:|" * (len(CTL_FIELDS) + 2)]
        for bk in s.get("books") or []:
            f = (pl.get("form") or {}).get(bk) or {}
            c = ((pl.get("control") or {}).get(bk)
                 if isinstance(pl.get("control"), dict) else None)
            eq = ((s.get("placebo_eq") or {}).get(bk) or {})
            L.append(f"| {R.ruler_title(bk)} | "
                     f"{_n((pl.get('cut_n') or {}).get(bk))} | "
                     f"{_n((pl.get('cut_taken_n') or {}).get(bk))} | "
                     + " | ".join(_u(f.get(x)) for x in CTL_FIELDS) + " | "
                     + _share_cell((c or {}).get(MAIN_FIELD)) + " | "
                     + _share_cell(eq.get(MAIN_FIELD)) + " |")
        L += [""]
    L += [f"**Убийца шага 1в:** "
          f"{((s.get('killers') or {}).get('1в') or {}).get('why')}.", ""]
    # --- шаг 1г ---
    lv = s.get("lev") or {}
    L += ["## Шаг 1г. Переодетое плечо", "",
          f"Хвост живёт на большом плече по построению, поэтому разрыв "
          f"меряется ВНУТРИ полосы ≥ {HIGH_LEV:g}×, а нулём стоит "
          f"перестановка меток ({s.get('perms')} раз).", "",
          "| позиций в полосе | из них повторов | хвост у повторов | "
          "хвост у остальных | разрыв | доля перестановок не меньше |",
          "|--:|--:|--:|--:|--:|--:|",
          f"| {_n(lv.get('n_band'))} | {_n(lv.get('n_rep'))} | "
          f"{_s(lv.get('tail_rep'))} | {_s(lv.get('tail_rest'))} | "
          f"{_u(lv.get('gap'), 3)} | {_s(lv.get('perm'), 0)} |", "",
          f"**Убийца шага 1г:** "
          f"{((s.get('killers') or {}).get('1г') or {}).get('why')}.", ""]
    # --- шаг 2 ---
    L += ["## Шаг 2. Форма на записи", "",
          "Колонки обязательны и объявлены заявкой. «Взято кассой» стоит "
          "рядом со сделками не для полноты: касса берёт другие позиции на "
          "освобождённые деньги, и без этого числа прибавка неотличима от "
          "оборота капитала. Медиана и среднее суток стоят рядом — "
          "расхождение знака есть подпись короткой волатильности.", ""]
    for d in s.get("deps") or []:
        got = (s.get("form") or {}).get(d) or (s.get("form")
                                               or {}).get(str(d)) or {}
        if not got:
            continue
        L += [f"### Депозит ${int(d)}"
              + (" — ячейка вердикта" if int(d) == int(s.get("dep") or 0)
                 else " (диагностика)"), "", FORM_HEAD, FORM_SEP]
        for bk in s.get("books") or []:
            L.append(form_row(f"{R.ruler_title(bk)}: база",
                              (got.get("base") or {}).get(bk)))
            L.append(form_row(f"{R.ruler_title(bk)}: пауза "
                              f"{VERDICT_P_H:g} ч",
                              (got.get("sister") or {}).get(bk)))
        L += [""]
    # --- варианты триггера ---
    var = s.get("variants") or {}
    if var:
        L += ["### Варианты триггера (диагностика, вердикта нет)", "",
              "| вариант | снято взятых базой | "
              + " | ".join(FIELD_TITLE[f] for f in CTL_FIELDS) + " |",
              "|---|--:|" + "--:|" * len(CTL_FIELDS)]
        for name, got in var.items():
            f = (got.get("form") or {}).get(BOOK) or {}
            L.append(f"| {name} | "
                     f"{_n((got.get('cut_taken_n') or {}).get(BOOK))} | "
                     + " | ".join(_u(f.get(x)) for x in CTL_FIELDS) + " |")
        L += [""]
    # --- шаг 3 ---
    fw = s.get("forward") or {}
    L += ["## Шаг 3. Вперёд", "",
          f"Правило вылета пула: медиана дня ≥ {fw.get('min_med')}, укус ≤ "
          f"{fw.get('max_bite')} при ≥ {fw.get('min_days')} сутках со "
          f"сделками (`research/factory/pool.py`). У сестры суток "
          f"пересчёта {fw.get('days_backtest')}, форварда "
          f"{fw.get('days_forward')}.", "",
          f"**{fw.get('why')}.**", ""]
    # --- как читать ---
    L += ["## Как читать и чего механика НЕ говорит", "",
          "- Реплея по барам здесь нет вовсе: пауза меняет СОСТАВ книги, "
          "а не исход позиции. Кэш реплея читается и не переписывается — "
          "это механизм (`cache_locked`), а не обещание.",
          "- Веса модели видели эти часы: всё, что выше, есть ПЕРЕСЧЁТ и "
          "читается как оценка сверху. Форму судит форвард, которого у "
          "необъявленной сестры нет.",
          "- Правило вычёркивает сделки, поэтому рядом с каждой веткой "
          "стоит доля зёрен, где случайное урезание ТОГО ЖЕ размера не "
          "хуже. Велика доля — работает размер, а не правило.",
          "- Ячейка вердикта одна и объявлена до прогона; лучшая ячейка "
          "оси после просмотра правилом не объявляется (ошибка R5).",
          "- Пауза не снимает хвост как класс: первая ставка против "
          "разгона имени остаётся полной. Она ограничивает ПОВТОРЕНИЕ "
          "одной потери, а не её размер.", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=f"механика {MECH}: пауза по "
                                             "имени после хвостового выхода")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--perms", type=int, default=PERMS)
    ap.add_argument("--mem-limit", type=int, default=None)
    ap.add_argument("--short", action="store_true",
                    help="только ячейка вердикта: без чужих депозитов и "
                         "вариантов триггера")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    # Каталог артефактов создаётся ДО счёта: прогон, которому некуда
    # писать, узнаёт об этом в конце.
    os.makedirs(OUT, exist_ok=True)
    s = run(seeds=a.seeds, perms=a.perms, mem_limit=a.mem_limit,
            full=not a.short)
    art = os.path.join(OUT, f"{ART}.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, default=str)
    os.replace(art + ".tmp", art)
    path = os.path.join(OUT, f"{ART}.md")
    txt = report(s)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        # Публикация — часть прогона: шаг, который можно забыть, рано или
        # поздно забывают.
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        f"механика {MECH}: пауза по имени после хвостового "
                        "выхода"], cwd=ROOT, check=False)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
