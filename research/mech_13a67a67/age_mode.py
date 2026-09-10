#!/usr/bin/env python3
"""Механика 13a67a67 — возраст имени как РЕЖИМ ПРОГНОЗА.

Ядро механики: чистые функции. Диск, журналы, книги и отчёт — в
`run_age_mode.py`.

Что спрашивается. Правило «не входить в шорт по имени моложе 7 суток»
объявлено 08.09 и измерено ДЕНЬГАМИ одной книги (`dca_paper/rules.py`,
`MIN_AGE_DAYS`). Здесь меряется не книга, а сам ПРОГНОЗ: доля выборов,
у которых цена пошла в сторону сделки, — по полосам возраста имени, на
обеих сторонах и на трёх листах (`h4`, `h24`, `sit`). Утверждение
предлагающего: на именах моложе 7 суток прогноз информации не несёт, а
на именах старше 60 — несёт.

**Ход в сторону сделки считается со знаком стороны.** Заявка называет
мерой «долю выборов с ходом в сторону прогноза, P(got > 0)», но поле
`got` журнала разбора — СЫРОЙ ход цены, а не ход в пользу позиции:
цикл кладёт туда `y[i, j]` матрицы форвардных доходностей, и знак
стороны появляется только в соседнем поле (`s8_loop/train.py`:
`net = (1 if side == "long" else -1) * got - ROUND_COST_BP`). Буквальное
`P(got > 0)` мерило бы у шортов долю ПРОМАХОВ. Слова заявки и задания
(«ход в сторону прогноза», «б.п. цены в сторону сделки») говорят
обратное её же формуле, и здесь взяты слова: мера — `P(fav > 0)`, где
`fav` есть `+got` лонгу и `−got` шорту. Проверка не на веру: у `h24`
сырое `P(got > 0)` даёт шортам 33.6 %, а по стороне — 66.4 %, и в плюсе
шорты `h24` у проекта уже измерены кассой (`side_split`, +771 $).
Буквальная доля печатается рядом ОТДЕЛЬНОЙ колонкой, чтобы расхождение
было видно, а не спрятано.

**Момент решения — это `hour`, а не `at_ts`.** Поле `at_ts` строки
разбора есть момент, когда разбор ЗАПИСАН (`s8_loop/train.py`: «Момент
записи разбора»), то есть уже ПОСЛЕ горизонта книги; у ситуационного
листа строки живого сторожа пишут туда вовсе `time.time()` момента
выхода (`s8_loop/sit_absorb.py`). Возраст, взятый по `at_ts`, — это
возраст в будущем относительно решения. На нашей записи это не мелочь:
191 выбор меняет полосу, и в полосе, о которой идёт спор, у коротких
`h24` 226 превращаются в 128. Поэтому возраст здесь считается на
`trades.hour_end(hour)` — момент закрытия часа сигнала, он же момент
входа, — и проверка «переписать будущее, прошлое не шелохнётся» стоит
именно на этом.

Чужое зовётся у хозяев, второй копии не заводится:

* полосы возраста и их границы, фильтр и контроль размера —
  `dca_paper/pair_age` (`BAND_EDGES`, `BAND_NAMES`, `band_of`, `pick`,
  `SEED`, `SEEDS`);
* дата листинга и возраст — `a1_universe/instruments_refresh`
  (`launches`, `age_days`) — единственное место чтения справочника;
* момент входа из метки часа — `s8_loop/trades.hour_end`;
* чтение строк журнала разбора — `s8_loop/side_split.jlines`;
* деньги, просадка и дневная форма книги — `dca_paper/run_paper`
  (`build_rows`, `_stats`), издержки — `dca_paper/costs.apply_to_rows`.

Своё здесь: разбор журнала в выборы, доля попаданий, бутстрап разности
ДВУМЯ единицами (выбор и час), пороги измеримости и вердикта, взятые у
заявки, калибровочная пара и вердиктовые фразы, выведенные из чисел.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in ("dca_paper", "s8_loop", "a1_universe", "dca_ladder", "common",
           "factory"):
    _d = os.path.join(RESEARCH, _p)
    if _d not in sys.path:
        sys.path.insert(0, _d)

import pair_age as PA                                        # noqa: E402
import instruments_refresh as IR                             # noqa: E402
import trades as TR                                          # noqa: E402

# --- чужие величины: берутся У ХОЗЯЕВ, здесь не назначаются -------------
BAND_NAMES = PA.BAND_NAMES
BAND_EDGES = PA.BAND_EDGES
UNKNOWN = PA.UNKNOWN
# Объявленные полосы вердикта. Оба числа — ГРАНИЦЫ `pair_age`, а не
# новые пороги: заявка сравнивает «моложе 7» с «старше 60», и предъявить
# лучшую полосу запрещено. Читаются из сетки хозяина, чтобы сдвиг сетки
# не оставил здесь осиротевший литерал.
YOUNG_MAX_D = BAND_EDGES[2]                       # 7 суток
OLD_MIN_D = BAND_EDGES[5]                         # 60 суток
YOUNG = f"моложе {YOUNG_MAX_D:g} сут"
OLD = f"старше {OLD_MIN_D:g} сут"
SEED_PICK = PA.SEED                               # зерно контроля размера
SEEDS = PA.SEEDS                                  # 200 зёрен переноса

# --- своё, объявлено ДО прогона ----------------------------------------
# Убийца (0): полоса тоньше этого — «не измерено», прочерк с числом.
MIN_CHOICES = 100
# Убийца (1): разность долей попаданий (старые − молодые), п.п.
MIN_DIFF_PP = 5.0
# Убийца (3): доля зёрен, где случайная выборка того же размера бьёт
# фильтр возраста. Порог не новый — им принято короткое правило.
MAX_BEAT = 0.10
BOOT = 2000                                       # повторов бутстрапа
CI = 0.95
SEED = 20260910                                   # зерно ЧИСЛОМ (урок R3)
# Калибровка: подсаженный сдвиг к `got` молодой полосы обязан перевернуть
# разность в пользу молодых.
SPIKE_BP = 200.0
# Бутстрап, у которого годных повторов меньше этой доли, интервала НЕ
# даёт: он печатается прочерком с числом, а не нулём. Пустая полоса в
# повторе — не «разность ноль», а «разности нет».
#
# Доля высокая намеренно. Повтор теряет полосу только тогда, когда вся
# полоса живёт в считаных часах: при пересэмплировании часов с возвратом
# полоса из ОДНОГО часа выпадает примерно в 37 % повторов, и никакая
# полоса шире этого столько не теряет. То есть порог отделяет «полоса
# держится на одном-двух часах» от «полоса есть», а не режет здоровый
# счёт: на нашей записи молодые выборы стоят в 161 часе (лонги) и 264
# (шорты), и годных повторов там все 2000 из 2000.
BOOT_MIN_USED = 0.9

SHEETS = (("h4", "model"), ("h24", "model_h24"), ("sit", "model_sit"))
SIDES = ("long", "short")
UNION = "объединение"


# --- разбор журнала разбора в выборы -----------------------------------

def decision_ts(line):
    """Момент РЕШЕНИЯ строки журнала разбора, секунды. None — метки нет.

    Берётся из `hour` — метки часа сигнала — через `trades.hour_end`:
    решение принимается на закрытии часа, оно же цена входа книги.

    `at_ts` здесь НЕ годится ни на одном листе: цикл пишет туда момент
    ЗАПИСИ разбора (то есть после горизонта), а живой сторож
    ситуационной книги — момент выхода. Возраст по `at_ts` есть возраст
    из будущего, и на нашей записи он переносит 191 выбор в другую
    полосу.
    """
    return TR.hour_end((line or {}).get("hour"))


def favour(got, side):
    """Ход В СТОРОНУ СДЕЛКИ, б.п. Лонгу `+got`, шорту `−got`.

    Знак стороны живёт ЗДЕСЬ и только здесь: `got` журнала разбора —
    сырой ход цены (`train.py`: `got = y[i, j]`), и та же формула знака
    стоит у самого цикла, когда он считает `net`. Вторая копия правила
    знака однажды разошлась бы с первой, поэтому его читают отсюда все
    меры механики.
    """
    return float(got) if side == "long" else -float(got)


def choices(lines, sheet, log=None):
    """Выборы листа из строк журнала разбора.

    Возвращает `(список, счётчики)`. Выбор — словарь с листом, рукой,
    часом решения, моментом решения, именем, стороной и ходом `got`
    (б.п. цены в сторону сделки) и `net`.

    Строка без метки часа или выбор без `got` — НЕ ноль: они считаются
    отдельными числами и в выборы не попадают. Ноль означает «измерено и
    равно нулю», а здесь величины нет вовсе.
    """
    out = []
    why = {"строк": 0, "без часа": 0, "без хода": 0, "без стороны": 0,
           "повторов": 0}
    seen = set()
    for ln in lines or []:
        why["строк"] += 1
        at = decision_ts(ln)
        if at is None:
            why["без часа"] += 1
            continue
        arm = ln.get("arm")
        for r in ln.get("rows") or []:
            side = r.get("side")
            if side not in SIDES:
                why["без стороны"] += 1
                continue
            if r.get("got") is None:
                why["без хода"] += 1
                continue
            k = (arm, ln.get("hour"), r.get("sym"), side)
            if k in seen:
                # Один и тот же выбор дважды удвоил бы вес часа в
                # бутстрапе. Повтор считается числом, а не чинится молча.
                why["повторов"] += 1
                continue
            seen.add(k)
            out.append({"sheet": sheet, "arm": arm, "hour": ln.get("hour"),
                        "at": float(at), "sym": r.get("sym"), "side": side,
                        "got": float(r["got"]),
                        "fav": favour(r["got"], side),
                        "net": (None if r.get("net") is None
                                else float(r["net"]))})
    if why["строк"] and not out:
        # Отказ вместо пустоты: непустой вход, давший ноль наблюдений, —
        # это сломанная дорога, а не «эффекта нет».
        raise ValueError(
            f"лист {sheet}: строк {why['строк']}, выборов ноль "
            f"(без часа {why['без часа']}, без хода {why['без хода']}, "
            f"без стороны {why['без стороны']})")
    if log:
        log(f"лист {sheet}: строк {why['строк']}, выборов {len(out)}"
            + (f", повторов {why['повторов']}" if why["повторов"] else "")
            + (f", без часа {why['без часа']}" if why["без часа"] else "")
            + (f", без хода {why['без хода']}" if why["без хода"] else ""))
    return out, why


def with_age(chs, launch):
    """Дописать выборам возраст на момент решения и полосу.

    Возраст — `instruments_refresh.age_days`, полоса — `pair_age.band_of`:
    имя без даты листинга получает СВОЮ полосу, а не приписывается к
    старым. Ровно на этом сгорел гейт по ставке funding.
    """
    out = []
    for c in chs:
        a = IR.age_days(launch, c.get("sym"), c["at"])
        out.append(dict(c, age=a, band=PA.band_of(a)))
    return out


def band_key(age):
    """Полоса вердикта: молодая, старая или ни та ни другая.

    Возраст неизвестен — ни та ни другая, и это отдельная строка отчёта.
    """
    if age is None:
        return None
    a = float(age)
    if a < YOUNG_MAX_D:
        return YOUNG
    if a >= OLD_MIN_D:
        return OLD
    return None


# --- меры --------------------------------------------------------------

def hit_share(fav):
    """Доля выборов с ходом В СТОРОНУ сделки, P(fav > 0).

    Ничья (ровно ноль) попаданием НЕ считается: конвенция проекта
    разрешает ничью не в свою пользу.
    """
    v = np.asarray(list(fav), dtype=float)
    return None if v.size == 0 else float(np.mean(v > 0))


def cell_stats(chs):
    """Ячейка: число выборов, доля попаданий, медиана и среднее.

    Величины считаются по ходу В СТОРОНУ СДЕЛКИ (`fav`); рядом стоит
    `hit_raw` — буквальная доля `P(got > 0)` заявки, чтобы расхождение
    двух мер было видно колонкой, а не жило в объяснении. Сырые медиана
    и среднее `got` тоже печатаются: у шортов они зеркальны, и читатель
    вправе увидеть обе.

    Пустая ячейка — ПРОЧЕРК во всех величинах, а не ноль: нуль значит
    «измерено и равно нулю», а измерять здесь нечего.
    """
    fav = np.array([c["fav"] for c in chs], dtype=float)
    got = np.array([c["got"] for c in chs], dtype=float)
    net = np.array([c["net"] for c in chs if c.get("net") is not None],
                   dtype=float)
    if fav.size == 0:
        return {"n": 0, "hit": None, "hit_raw": None, "fav_med": None,
                "fav_mean": None, "got_med": None, "got_mean": None,
                "net_n": 0, "net_med": None, "net_mean": None}
    return {"n": int(fav.size),
            "hit": round(float(hit_share(fav)), 4),
            "hit_raw": round(float(np.mean(got > 0)), 4),
            "fav_med": round(float(np.median(fav)), 1),
            "fav_mean": round(float(np.mean(fav)), 1),
            "got_med": round(float(np.median(got)), 1),
            "got_mean": round(float(np.mean(got)), 1),
            "net_n": int(net.size),
            "net_med": (round(float(np.median(net)), 1)
                        if net.size else None),
            "net_mean": (round(float(np.mean(net)), 1)
                         if net.size else None)}


def cells(chs, sheets=None):
    """Все ячейки: лист × сторона × полоса, плюс объединение листов.

    Ключ — `лист|сторона|полоса`. Объединение считается ОТДЕЛЬНЫМ листом
    `объединение`: ячейка вердикта — оно, а разрез по листам объявлен
    диагностикой.
    """
    names = [s[0] for s in (sheets or SHEETS)] + [UNION]
    by = {}
    for c in chs:
        for sh in (c["sheet"], UNION):
            by.setdefault(f"{sh}|{c['side']}|{c['band']}", []).append(c)
    out = {}
    for sh in names:
        for side in SIDES:
            for band in list(BAND_NAMES) + [UNKNOWN]:
                k = f"{sh}|{side}|{band}"
                out[k] = cell_stats(by.get(k) or [])
    return out


def split_bands(chs, side):
    """Молодые и старые выборы одной стороны — только объявленные полосы."""
    young = [c for c in chs
             if c["side"] == side and band_key(c.get("age")) == YOUNG]
    old = [c for c in chs
           if c["side"] == side and band_key(c.get("age")) == OLD]
    return old, young


# --- бутстрап разности долей: две единицы ------------------------------

def _diff_pp(old_fav, young_fav):
    """Разность долей попаданий (старые − молодые), процентные пункты."""
    a, b = hit_share(old_fav), hit_share(young_fav)
    return None if a is None or b is None else 100.0 * (a - b)


def boot_diff(old, young, unit="выборы", reps=BOOT, seed=SEED):
    """Интервал разности долей попаданий одним из двух пересчётов.

    `unit="выборы"` — каждая полоса пересэмплируется своими выборами.
    `unit="часы"` — единицей берётся ЧАС: выборы одного часа делят один
    рынок, и час пересэмплируется ЦЕЛИКОМ, вместе с обеими полосами.
    Час — та единица, на которой проект считает независимость.

    Повтор, в котором одна из полос пуста, разности не даёт и считается
    негодным: пустая полоса — не «разность ноль». Годных меньше
    `BOOT_MIN_USED` — интервал ПРОЧЕРК с числом, а не пара нулей.
    """
    base = _diff_pp([c["fav"] for c in old], [c["fav"] for c in young])
    out = {"unit": unit, "reps": int(reps), "diff_pp": base,
           "used": 0, "lo": None, "hi": None, "median": None,
           "covers_zero": None, "weak": False,
           "n_old": len(old), "n_young": len(young)}
    if not old or not young:
        out["weak"] = True
        return out
    rng = np.random.default_rng(seed)
    go = np.array([c["fav"] for c in old], dtype=float)
    gy = np.array([c["fav"] for c in young], dtype=float)
    vals = []
    if unit == "выборы":
        for _ in range(int(reps)):
            a = go[rng.integers(0, go.size, go.size)]
            b = gy[rng.integers(0, gy.size, gy.size)]
            vals.append(_diff_pp(a, b))
    elif unit == "часы":
        by = {}
        for i, c in enumerate(old):
            by.setdefault(c["hour"], ([], []))[0].append(i)
        for i, c in enumerate(young):
            by.setdefault(c["hour"], ([], []))[1].append(i)
        hours = list(by)
        pack = [by[h] for h in hours]
        n = len(hours)
        for _ in range(int(reps)):
            idx = rng.integers(0, n, n)
            oi, yi = [], []
            for j in idx:
                p = pack[j]
                oi += p[0]
                yi += p[1]
            if not oi or not yi:
                continue
            vals.append(_diff_pp(go[oi], gy[yi]))
    else:
        raise ValueError(f"единица бутстрапа не объявлена: {unit!r}")
    vals = [v for v in vals if v is not None]
    out["used"] = len(vals)
    if len(vals) < BOOT_MIN_USED * int(reps):
        out["weak"] = True
        return out
    v = np.sort(np.array(vals, dtype=float))
    lo = float(np.quantile(v, (1.0 - CI) / 2.0))
    hi = float(np.quantile(v, 1.0 - (1.0 - CI) / 2.0))
    out["lo"] = round(lo, 2)
    out["hi"] = round(hi, 2)
    out["median"] = round(float(np.median(v)), 2)
    out["covers_zero"] = bool(lo <= 0.0 <= hi)
    return out


# --- вердикт: выводится ИЗ ЧИСЕЛ ---------------------------------------

def verdict(old_cell, young_cell, boots):
    """Вердикт по одной стороне. Ни одна фраза не стоит рядом с числом.

    Порядок убийц — тот, что объявлен заявкой:

    0. молодая полоса тоньше `MIN_CHOICES` — сторона НЕ ИЗМЕРЕНА;
    1. разность долей меньше `MIN_DIFF_PP` либо интервал накрывает ноль
       хотя бы при одном пересчёте (или интервала нет вовсе) — мёртво;
    2. медиана и среднее молодой полосы расходятся знаком относительно
       старой — подпись лотереи, вердикт «нет информации» НЕ выносится.
    """
    ny = int((young_cell or {}).get("n") or 0)
    no = int((old_cell or {}).get("n") or 0)
    res = {"n_young": ny, "n_old": no, "measured": ny >= MIN_CHOICES
           and no >= MIN_CHOICES, "alive": False, "killer": None,
           "diff_pp": None, "min_diff_pp": MIN_DIFF_PP,
           "min_choices": MIN_CHOICES}
    if not res["measured"]:
        thin = YOUNG if ny < MIN_CHOICES else OLD
        res["killer"] = 0
        res["phrase"] = (
            f"не измерено: в полосе «{thin}» "
            f"{ny if thin == YOUNG else no} выборов при нужных "
            f"{MIN_CHOICES} — вердикта нет, прочерк с числом")
        return res
    diff = 100.0 * (float(old_cell["hit"]) - float(young_cell["hit"]))
    res["diff_pp"] = round(diff, 2)
    covers = [b for b in boots if b.get("covers_zero") is not False]
    if diff < MIN_DIFF_PP:
        res["killer"] = 1
        res["phrase"] = (
            f"утверждение мертво: разность долей {diff:+.1f} п.п. меньше "
            f"объявленных {MIN_DIFF_PP:g} п.п. — прогноз на именах "
            f"«{YOUNG}» информативен не хуже, чем на «{OLD}»")
        return res
    if covers:
        bad = ", ".join(
            (f"{b['unit']}: интервала нет, годных повторов {b['used']} "
             f"из {b['reps']}") if b.get("lo") is None
            else f"{b['unit']}: {b['lo']:+.1f}…{b['hi']:+.1f} п.п."
            for b in covers)
        res["killer"] = 1
        res["phrase"] = (
            f"утверждение мертво: разность {diff:+.1f} п.п., но интервал "
            f"95 % накрывает ноль ({bad}) — разность не отличима от нуля "
            "хотя бы одним пересчётом")
        return res
    dm = float(young_cell["fav_med"]) - float(old_cell["fav_med"])
    da = float(young_cell["fav_mean"]) - float(old_cell["fav_mean"])
    if dm < 0.0 < da:
        res["killer"] = 2
        res["phrase"] = (
            f"вердикт «нет информации» НЕ выносится: у полосы «{YOUNG}» "
            f"медиана хуже на {abs(dm):.0f} б.п., а среднее ЛУЧШЕ на "
            f"{da:.0f} б.п. — подпись лотереи, разность объявляется "
            "хвостовой")
        return res
    res["alive"] = True
    res["phrase"] = (
        f"утверждение выжило: доля попаданий у «{OLD}» "
        f"{100 * old_cell['hit']:.1f} % против {100 * young_cell['hit']:.1f} % "
        f"у «{YOUNG}», разность {diff:+.1f} п.п. при пороге "
        f"{MIN_DIFF_PP:g}; интервал 95 % ноль не накрывает ни выборами, "
        f"ни часами; медиана {young_cell['fav_med']:+.0f} против "
        f"{old_cell['fav_med']:+.0f} б.п. и среднее "
        f"{young_cell['fav_mean']:+.0f} против {old_cell['fav_mean']:+.0f} "
        "б.п. у молодых хуже оба")
    return res


# --- калибровочная пара -------------------------------------------------

def spike(chs, bp=SPIKE_BP):
    """Подсадить сдвиг `bp` к ходу молодых выборов В ИХ ПОЛЬЗУ.

    Сдвиг кладётся на `fav`, а `got` двигается со знаком стороны — иначе
    у шортов подсадка шла бы против них, и «калибровка не прошла»
    означало бы ошибку самой калибровки.

    Возвращает `(выборы, сколько тронуто)`; вызывающий ОБЯЗАН убедиться,
    что подделка легла (`assert`), — иначе «калибровка прошла» значит
    только, что её не было. Урок `probe_dow`.
    """
    out, n = [], 0
    for c in chs:
        if band_key(c.get("age")) == YOUNG:
            d = dict(c, fav=float(c["fav"]) + float(bp),
                     got=float(c["got"])
                     + (float(bp) if c["side"] == "long" else -float(bp)))
            if c.get("net") is not None:
                d["net"] = float(c["net"]) + float(bp)
            out.append(d)
            n += 1
        else:
            out.append(dict(c))
    return out, n


def shuffle_ages(chs, seed=SEED):
    """Перемешать ВОЗРАСТА выборов ВНУТРИ ЧАСА, ход оставить на месте.

    Это второй нуль калибровочной пары: связь «возраст имени → качество
    выбора» рвётся, а всё остальное — состав часа, распределение ходов,
    число выборов в часе — сохраняется. Полосы обязаны сравняться в
    пределах интервала.

    Перемешивание идёт ВНУТРИ часа, а не по всей записи: сдвиг состава
    во времени (в августе имена моложе, чем в сентябре) сам по себе
    создал бы разность, и глобальная перестановка мерила бы календарь.
    """
    rng = np.random.default_rng(seed)
    by = {}
    for i, c in enumerate(chs):
        by.setdefault(c["hour"], []).append(i)
    out = [dict(c) for c in chs]
    moved = 0
    for hour in sorted(by):
        idx = by[hour]
        ages = [chs[i].get("age") for i in idx]
        perm = rng.permutation(len(idx))
        for j, i in enumerate(idx):
            a = ages[perm[j]]
            out[i]["age"] = a
            out[i]["band"] = PA.band_of(a)
            if band_key(a) != band_key(chs[i].get("age")):
                moved += 1
    return out, moved


# --- шаг 2: перенос правила возраста на длинную сторону -----------------

def pick_side(recs, launch, min_days, side=None, seed=SEED_PICK,
              n_random=None):
    """`pair_age.pick` со СТОРОНОЙ: фильтр видит только свою сторону.

    Объявленное правило возраста стоит на КОРОТКОЙ стороне
    (`rules.MIN_AGE_DAYS`), и `pair_age.pick` фильтрует весь переданный
    список. Чтобы то же правило можно было применить к длинной стороне —
    и к смеси сторон общего счёта — сюда добавлена сторона: записи
    ДРУГОЙ стороны проходят нетронутыми и считаются своим числом.

    Сам фильтр возраста и контроль размера не переписаны: они остаются в
    `pair_age.pick`, и вторая копия однажды разошлась бы с первой.
    Контроль размера берёт столько же записей, сколько оставил фильтр, и
    берёт их ИЗ СВОЕЙ СТОРОНЫ — иначе «столько же» считалось бы по
    чужому списку.

    `side=None` — как у хозяина: фильтруется всё.
    """
    if side is None:
        keep, why = PA.pick(recs, launch, min_days, seed=seed,
                            n_random=n_random)
        return keep, dict(why, сторона="все")
    mine = [r for r in recs if r.get("side") == side]
    other = [r for r in recs if r.get("side") != side]
    keep, why = PA.pick(mine, launch, min_days, seed=seed,
                        n_random=n_random)
    why = dict(why, сторона=side, **{"другая сторона": len(other)})
    return other + keep, why


def ratio_of(st):
    """Доход на просадку книги. Просадки нет — отношения НЕ существует."""
    if not st:
        return None
    fin, dd = st.get("final"), st.get("max_dd")
    if not fin or not dd:
        return None
    return round(float(fin) / abs(float(dd)), 2)


def beat_share(base, vals):
    """Доля значений контроля, которые ДОСТАЮТ до фильтра или бьют его.

    Знак `>=`, а не `>`: равный результат случайной выборки означает, что
    фильтр не дал ничего, и засчитывать ничью фильтру нельзя. Та же
    конвенция, что у `pair_age` и `pair_gate`.
    """
    v = [x for x in vals if x is not None]
    if base is None or not v:
        return None
    return round(float(np.mean(np.array(v, dtype=float) >= float(base))), 3)


def transfer_verdict(rows, max_beat=MAX_BEAT, seeds=SEEDS):
    """Вердикт переноса из чисел: убийца (3) заявки.

    `rows` — по режиму: `{"key", "ratio", "ratio_random", "beat_ratio"}`.
    Перенос живёт, только если во ВСЕХ режимах случайное исключение того
    же размера бьёт возраст реже `max_beat`. Хотя бы один режим выше —
    прибавка есть размер, а не возраст.

    Число зёрен приходит ПАРАМЕТРОМ, а не берётся из умолчания модуля:
    фраза, называющая 200 там, где прогон считал 3, стареет молча — а
    разрешение доли и есть 1/зёрна.
    """
    known = [r for r in rows if r.get("beat_ratio") is not None]
    if not known or len(known) != len(rows):
        miss = [r["key"] for r in rows if r.get("beat_ratio") is None]
        return {"alive": False, "measured": False, "seeds": int(seeds),
                "phrase": ("перенос не судится: доля «бьют фильтр» не "
                           f"посчитана у режимов {', '.join(miss) or '—'} — "
                           "прочерк, а не ноль")}
    worst = max(known, key=lambda r: r["beat_ratio"])
    ok = worst["beat_ratio"] < max_beat
    thin = ("" if seeds >= SEEDS else
            f" (зёрен {seeds} при объявленных {SEEDS} — разрешение доли "
            f"{1.0 / max(seeds, 1):.3f}, вердикт предварителен)")
    return {"alive": bool(ok), "measured": True, "seeds": int(seeds),
            "worst_key": worst["key"], "worst_beat": worst["beat_ratio"],
            "max_beat": max_beat,
            "phrase": (
                f"перенос выжил: худший режим «{worst['key']}» — случайное "
                f"исключение того же размера достаёт до возраста в "
                f"{100 * worst['beat_ratio']:.1f} % из "
                f"{seeds} зёрен при пороге {100 * max_beat:.0f} %" + thin
                if ok else
                f"перенос мёртв: в режиме «{worst['key']}» случайное "
                f"исключение того же размера достаёт до возраста в "
                f"{100 * worst['beat_ratio']:.1f} % из {seeds} зёрен при "
                f"пороге {100 * max_beat:.0f} % — прибавка есть размер, а "
                "не возраст" + thin)}
