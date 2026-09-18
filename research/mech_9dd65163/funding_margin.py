#!/usr/bin/env python3
"""Механика 9dd65163, шаг 1: funding ВНУТРИ пути позиции — потолок на кэше.

Утверждение заявки. Сегодня реплей коротких книг `h24` считает путь
позиции маржой, которая за 24 часа жизни не меняется ни разу, а funding
вычитается ПОТОМ, из уже записанного исхода (`dca_paper/costs.py`: «в
ядре комиссии, проскальзывания и funding нет вовсе»). В жизни начисления
списываются с маржи каждые 1–8 часов, и от остатка маржи зависит, где
стоят ликвидация и пол капитуляции. Значит момент учёта может менять
ИСХОД части позиций, а с ним — худший день, укус и число ликвидаций, то
есть числа, по которым книги судятся вперёд до 04.10.

Что считает ЭТОТ модуль (шаг 1, «потолок»). Реплея по барам здесь нет
вовсе, и в этом весь смысл: у семейства `h24` доливов нет, пол активен с
первого часа, а у каждой закрытой записи кэша реплея уже лежат почасовые
отметки ядра (`ladder.simulate_dca(track=True)` → `wave.path_of`). К часу
k берётся накопленный funding `F_k` (долей маржи, знак и события — те же,
что у `costs.funding_usd`) и проверяется скорректированное условие

    ликвидация:  cum[k] ≤ −(1 + F_k)
    пол:         cum[k] ≤ −(1 − f)·(1 + F_k)

на каждом часе СТРОГО ДО записанного выхода; `f` — пол капитуляции
книги из реестра правил (`rules.FLOOR_FRAC_BY_BOOK` через
`run_short.floor_groups`). Вывод на листке: у шорта при марже M и
нотионале N ликвидация стоит там, где цена ушла против на M/N, то есть
pnl = −1 доля маржи, пол — на −(1 − f) доли; если начисления съели долю
|F| маржи, остаток M·(1 − |F|), и оба уровня сжимаются в (1 + F) раз.
Ставка поддерживающей маржи здесь опущена намеренно — она делает
настоящую ликвидацию БЛИЖЕ к входу, чем −1 (`ladder.liq_price`:
pnl = (L·mmr − 1)/(1 + mmr)), поэтому наше условие строго СТРОЖЕ
движкового, и на нулевых ставках оно не срабатывает ни разу. Это и есть
калибровочная нога «нулевые ставки → база бит в бит», а не пожелание.

Вторая, ТОЧНАЯ поправка — крышка −100 %. Ликвидированной позиции учёт
после факта приписывает `pnl + funding` меньше −1 доли маржи, чего на
изолированной марже не бывает: биржа забирает маржу и не больше.
Правильное число известно без реплея и без отметок — цена в момент
ликвидации стоит ровно там, где съедена ВСЯ оставшаяся маржа, то есть
ценовой pnl = −(1 + F), а вместе с начислениями ровно −1. Число записей
ниже −100 % ДО поправки есть прямая мера дефекта (следствие «в» заявки).

Чего этот шаг НЕ умеет и не притворяется, что умеет:

* потолок недооценивает ПО ПОСТРОЕНИЮ. Отметки почасовые, а пол и
  ликвидация в жизни бьют внутри часа: позиция, у которой закрытие
  прошлого часа было далеко от уровня, за минуту доходит до него и
  умирает. Поэтому сработавший потолок ДОКАЗЫВАЕТ сдвиг, а молчащий
  потолок не доказывает его отсутствия — вердикт «мертво» здесь всегда
  предварительный и подтверждается шагом 2 (реплей по барам с
  начислениями в марже, `ladder.simulate_dca` одним необязательным
  аргументом). Шаг 2 есть правка ЯДРА вне каталога механики и здесь не
  построен: см. RUNBOOK и `notes` отчёта постройки;
* судьба позиции, которой ПОЛУЧЕННЫЙ funding отодвинул пол (следствие
  «б»), на кэше не измерима вовсе: пол сработал бы позже или не сработал,
  а что было бы дальше, знают только бары. Здесь она считается ЧИСЛОМ —
  верхней оценкой и полосой, — а не деньгами.

Второй копии расчётного ядра здесь нет: события и знак начислений —
`costs.funding_usd`, путь позиции — `wave.path_of`, закрытие записи на
часе — `wave.guard_record` (тот же, которым закрывает охрана рынком),
деньги — `agree_book.stats_of` → `short_grid.cell_stats` → `run_paper`,
форма — `factory/stability.stats`, пол — реестр правил.

Артефакт и отчёт — в `out/` СВОЕГО каталога (публикуемый `research/*/out`),
живой кэш реплея и журналы книг не переписываются ни при каком исходе.
"""

import argparse
import json
import os
import statistics as _st
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in ("dca_paper", "dca_ladder", "s8_loop", "a1_universe", "factory", ""):
    _q = os.path.join(ROOT, "research", _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_short as S                                         # noqa: E402
import wave as WV                                             # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import stability as ST                                        # noqa: E402

OUT = os.path.join(HERE, "out")
ART = "FUND-margin"
HOUR = WV.HOUR
MAIN_DEP = 10000                      # депозит, на котором судится книга
BOOK_KEYS = list(S.BOOKS)             # safe_h / optimal_h / aggr_h

# Маржа подставной строки, на которой считаются начисления. Единица не
# годится: `costs.funding_usd(detail=True)` округляет КАЖДОЕ событие до
# четырёх знаков (`round(got, 4)`), и при марже 1 накопленный funding
# терял бы до 1e-4 доли маржи на событие — четверть медианы. Масштаб
# делает округление 1e-10 доли и не трогает ни одной формулы: доллары
# события линейны по марже, и сумма событий сверяется с итогом самой
# `funding_usd` числом (`diag.event_sum_mismatch`).
SCALE = 1e6

# Порог, ниже которого вердикт НЕ выносится: ряд, не покрывающий журнал,
# даёт заниженный funding и выдаёт его за полный. Число не своё — оно
# взято у замера издержек (`costs.MIN_FUNDING_COVER`), где тем же
# порогом судится колонка нетто. Второго порога у одной величины быть
# не должно.
MIN_COVER = CO.MIN_FUNDING_COVER
# Между этим покрытием и полным вердикт выносится С ОГОВОРКОЙ, и
# непокрытые позиции печатаются отдельной строкой (заявка, шаг 0).
FULL_COVER = 0.90

# Пороги «мертво» объявлены ЗАЯВКОЙ до прогона (`kills_it`, шаг 1) и
# здесь только прочитаны. Назначать их тому, кто их проверяет, нельзя.
DEAD_SHIFT_SHARE = 0.01          # доля сдвинутых позиций книги
DEAD_BITE = 0.5                  # |сдвиг укуса|
DEAD_POSTPONED_SHARE = 0.01      # доля записей с отодвинутым полом
# Пороги «живо» шага 2 (реплей по барам). Здесь они НЕ выносят вердикт —
# потолок недооценивает, — но печатаются рядом, чтобы читатель видел, на
# сколько потолок не дотягивает до объявленной границы.
ALIVE_SHIFT_SHARE = 0.01
ALIVE_WORST_FRAC = 0.10          # |Δ худшего дня| ≥ 10 % его величины
ALIVE_BITE = 0.5
ALIVE_LIQ = 3                    # число ликвидаций меняется на ≥ 3


def floor_by_ruler():
    """Линейка кэша → пол капитуляции её книг, из реестра правил.

    Карта строится `run_short.floor_groups()`, а не своим чтением
    `FLOOR_FRAC_BY_BOOK`: там же проверяется, что линейка не кормит две
    книги с РАЗНЫМ полом (иначе исход позиции неразрешим), и вторая
    копия этой проверки однажды разошлась бы с прогоном.
    """
    out = {}
    for frac, rulers in S.floor_groups().items():
        for rk in rulers:
            out[rk] = float(frac)
    return out


def books_of(ruler):
    """Книги семейства, которые кормит эта линейка."""
    return [bk for bk, rk in S.BOOKS.items() if rk == ruler]


def accruals(rec, series):
    """Начисления позиции: `(F, [(момент, dF)])` долей МАРЖИ; None — нет меры.

    Один вызов `costs.funding_usd` — события, их знак и их набор берутся
    оттуда целиком (шорту положительная ставка — доход). Своего обхода
    ряда здесь нет: два места, считающие «сколько начислено», однажды
    разойдутся, и отчёт назовёт дефектом собственное расхождение.

    `None` означает ровно одно из трёх: ряда у имени нет, ряд не
    покрывает жизнь позиции целиком, у записи нет рунгов или плеча.
    Ноль тут был бы наблюдением «ставка была нулевой», которого не было.
    """
    if series is None:
        return None
    got = CO.funding_usd(dict(rec, margin=SCALE), series, "short", detail=True)
    if got is None:
        return None
    total, events = got
    ev = sorted((float(e["ts"]), float(e["usd"]) / SCALE) for e in events)
    return float(total) / SCALE, ev


def accrued_to(events, t):
    """Накопленный funding к моменту `t`, долей маржи — СТРОГО до него.

    Граница строгая, и это не мелочь: начисление ровно на границе часа
    относится к СЛЕДУЮЩЕМУ часу (бар с меткой `t` лежит уже в нём), а
    включить его в отметку часа `k` значило бы судить час деньгами,
    которых на нём ещё не было, — заглядывание в будущее на один шаг.
    """
    s = 0.0
    for (ts, d) in events:
        if ts < t:
            s += d
    return s


def shift_of(rec, events, floor, path=None):
    """Первый час, на котором пол или ликвидация СРАБОТАЛИ БЫ раньше записи.

    Возвращает `{"k", "why", "pnl", "F"}` либо None. `pnl` — ценовой pnl
    позиции в долях ИСХОДНОЙ маржи: у пола это отметка часа (тот же
    исход, что берёт охрана рынком), у ликвидации — ровно −(1 + F), то
    есть вся оставшаяся маржа и не больше.

    Часы перебираются СТРОГО до записанного выхода (`range(1, K)`):
    сработавшее на самом часе выхода не есть сдвиг — позиция и так
    закрылась в этом часе, и засчитать его значило бы выдать за находку
    собственную границу.
    """
    p = path if path is not None else WV.path_of(rec)
    if not p:
        return None
    at = float(rec["at"])
    for k in range(1, p["K"]):
        f_k = accrued_to(events, at + k * HOUR)
        c = float(p["cum"][k])
        left = 1.0 + f_k                      # что осталось от маржи
        if left <= 0 or c <= -left:
            return {"k": k, "why": "ликвидация", "pnl": -left, "F": f_k}
        if c <= -(1.0 - floor) * left:
            return {"k": k, "why": "пол", "pnl": c, "F": f_k}
    return None


def capped_liq_pnl(rec, total):
    """Ценовой pnl ликвидированной позиции с крышкой −100 % маржи.

    None — записи это не касается (исход не ликвидация) или поправки
    нет. Смысл: ликвидация случается ровно тогда, когда съедена вся
    оставшаяся маржа, поэтому ценовой pnl равен −(1 + F), а вместе с
    начислениями — ровно −1. Реплей же записывает −1 ЦЕНОЙ и сверх того
    вычитает начисления после факта, получая суммарный убыток глубже
    маржи, которого на изолированном счёте не бывает.
    """
    if rec.get("exit") != "ликвидация" or total is None:
        return None
    want = -(1.0 + float(total))
    return None if abs(want - float(rec["pnl"])) < 1e-12 else want


def close_at(rec, k, why, pnl=None):
    """Запись, закрытая на часе k, — библиотекой волны; `pnl` заменяет исход.

    Само закрытие делает `wave.guard_record` (тот же, которым закрывает
    охрана рынком): срез отметок, момент выхода, цена выхода, нетто.
    Замена нужна одной ликвидации — её исход не отметка часа, а «вся
    оставшаяся маржа», — и тождество `close_at(...)` без `pnl` с
    `guard_record` закреплено проверкой, чтобы подмена цены выхода не
    разошлась с исходной формулой.
    """
    new = WV.guard_record(rec, k, why=why)
    if pnl is None:
        return new
    pnl = float(pnl)
    round_cost = float(rec["pnl"]) - float(rec.get("pnl_net", rec["pnl"]))
    new["pnl"] = pnl
    if rec.get("pnl_net") is not None:
        new["pnl_net"] = pnl - round_cost
    lev, e = float(rec.get("lev") or 0), rec.get("entry_px")
    if e and lev:
        new["exit_px"] = float(e) * (1.0 - pnl / lev)          # шорт
    return new


def repnl(rec, pnl):
    """Та же запись с другим ЦЕНОВЫМ pnl (крышка −100 %), тот же выход."""
    pnl = float(pnl)
    round_cost = float(rec["pnl"]) - float(rec.get("pnl_net", rec["pnl"]))
    new = dict(rec, pnl=pnl)
    if rec.get("pnl_net") is not None:
        new["pnl_net"] = pnl - round_cost
    lev, e = float(rec.get("lev") or 0), rec.get("entry_px")
    if e and lev:
        new["exit_px"] = float(e) * (1.0 - pnl / lev)
    return new


def _postponed(rec, total, floor):
    """Следствие «б»: отодвинул ли ПОЛУЧЕННЫЙ funding пол этой записи.

    Возвращает `(верхняя_оценка, полоса, сдвиг_уровня)`.

    * верхняя оценка — запись закрыта полом либо ликвидацией, и funding
      ПОЛУЧЕН (F > 0). Тогда уровень стоит глубже на (1 − f)·F, и в жизни
      позиция в этом баре не резалась бы; что было бы дальше, знают
      только бары. Это верхняя оценка, а не мера: движок бьёт по
      ЭКСТРЕМУМУ бара, а в записи лежит цена закрытия, и насколько
      экстремум был глубже уровня, из кэша не видно;
    * полоса — отметка выхода лежит МЕЖДУ прежним и новым уровнем. Это
      наблюдаемое ядро того же вопроса: при F = 0 полоса пуста по
      построению, поэтому у величины есть свой честный нуль.
    """
    if rec.get("exit") not in ("пол", "ликвидация") or total is None:
        return False, False, None
    if not total > 0:
        return False, False, None
    f = 0.0 if rec["exit"] == "ликвидация" else float(floor)
    old = -(1.0 - f)
    new = -(1.0 - f) * (1.0 + float(total))
    return True, bool(new < float(rec["pnl"]) <= old), old - new


def screen(cache, ctx, floors=None, log=print):
    """Потолок по всему кэшу: покрытие, сдвиги, крышка, следствие «б».

    Возвращает `(правленый кэш, свод)`. Свод считается ПО ЛИНЕЙКАМ (ключ
    кэша) — книгу из линейки собирает уже касса, и у двух книг одной
    линейки записи те же.
    """
    floors = floors if floors is not None else floor_by_ruler()
    funding = (ctx or {}).get("funding") or {}
    to_asset = (ctx or {}).get("to_asset") or {}
    closed = [(key, r) for key, r in cache.items()
              if (r.get("state") or "closed") == "closed"]
    if not cache:
        raise ValueError("кэш реплея пуст — считать нечего")
    if not closed:
        raise ValueError(f"в кэше {len(cache)} записей и ни одной закрытой: "
                         "потолок считается по закрытым позициям")
    if not funding:
        raise ValueError("рядов funding нет ни одного — отказ, а не нули: "
                         "пустой ряд неотличим от нулевой ставки")
    out = dict(cache)
    by = {}
    diag = {"event_sum_mismatch": 0, "no_marks": 0, "open": len(cache) - len(closed),
            "over_after": 0}
    worst_over = None
    for key, rec in sorted(closed, key=lambda kv: (kv[0][0], kv[0][2])):
        rk = key[0]
        floor = floors.get(rk)
        if floor is None:
            raise ValueError(f"у линейки {rk} нет пола капитуляции в реестре "
                             "правил — книга неизвестна, считать нельзя")
        d = by.setdefault(rk, {
            "ruler": rk, "floor": floor, "books": books_of(rk), "n": 0,
            "covered": 0, "no_series": 0, "uncovered": 0, "no_marks": 0,
            "shift": 0, "shift_liq": 0, "shift_floor": 0, "shift_pnl": 0.0,
            "over_100": 0, "over_sum": 0.0, "capped": 0, "cap_pnl": 0.0,
            "postponed": 0, "postponed_band": 0, "move": [], "F": [],
            "exits_floor": 0, "over_after": 0,
            "shift_keys": [], "cap_keys": []})
        d["n"] += 1
        asset = to_asset.get(rec.get("sym"))
        series = funding.get(asset) if asset else None
        if series is None:
            d["no_series"] += 1
            continue
        got = accruals(rec, series)
        if got is None:
            d["uncovered"] += 1
            continue
        total, events = got
        if abs(sum(x for _t, x in events) - total) > 1e-9:
            diag["event_sum_mismatch"] += 1
        d["covered"] += 1
        d["F"].append(total)
        if rec.get("exit") in ("пол", "ликвидация"):
            d["exits_floor"] += 1
        up, band, move = _postponed(rec, total, floor)
        d["postponed"] += 1 if up else 0
        d["postponed_band"] += 1 if band else 0
        if move is not None:
            d["move"].append(move)
        tot = float(rec["pnl"]) + total
        if tot < -1.0:
            d["over_100"] += 1
            d["over_sum"] += tot + 1.0
            worst_over = tot if worst_over is None else min(worst_over, tot)
        path = WV.path_of(rec)
        if path is None:
            d["no_marks"] += 1
            diag["no_marks"] += 1
            continue
        sh = shift_of(rec, events, floor, path=path)
        if sh is not None:
            d["shift"] += 1
            d["shift_keys"].append([rk, key[1], key[2], sh["k"], sh["why"],
                                    round(sh["pnl"], 4), round(sh["F"], 5),
                                    round(float(rec["pnl"]), 4),
                                    rec.get("exit")])
            d["shift_pnl"] += sh["pnl"] - float(rec["pnl"])
            if sh["why"] == "ликвидация":
                d["shift_liq"] += 1
            else:
                d["shift_floor"] += 1
            out[key] = close_at(rec, sh["k"], sh["why"], pnl=sh["pnl"])
            # Funding у сдвинутой записи считается кассой по НОВОМУ, более
            # короткому окну — то есть ровно `F_k` часа сдвига.
            after = sh["pnl"] + sh["F"]
        else:
            cap = capped_liq_pnl(rec, total)
            if cap is not None:
                d["capped"] += 1
                d["cap_pnl"] += cap - float(rec["pnl"])
                d["cap_keys"].append([rk, key[1], key[2], round(cap, 4),
                                      round(float(rec["pnl"]), 4),
                                      round(total, 5)])
                out[key] = repnl(rec, cap)
            after = float(out[key]["pnl"]) + total
        # Следствие «в» заявки: записей глубже −100 % маржи после поправки
        # остаться не должно ПО ПОСТРОЕНИЮ. «Не должно» — это утверждение,
        # а не свойство кода, поэтому оно считается ЧИСЛОМ: funding, легший
        # целиком в последний час жизни позиции, потолок не ловит, и такая
        # запись останется — её разрешит только реплей по барам.
        if after < -1.0 - 1e-9:
            d["over_after"] += 1
            diag["over_after"] += 1
    for rk, d in by.items():
        d["cover"] = round(d["covered"] / d["n"], 4) if d["n"] else None
        d["shift_share"] = round(d["shift"] / d["covered"], 5) if d["covered"] else None
        d["postponed_share"] = (round(d["postponed"] / d["covered"], 5)
                                if d["covered"] else None)
        d["F_median"] = round(_st.median(d["F"]), 6) if d["F"] else None
        d["F_mean"] = round(sum(d["F"]) / len(d["F"]), 6) if d["F"] else None
        d["F_min"] = round(min(d["F"]), 5) if d["F"] else None
        d["F_max"] = round(max(d["F"]), 5) if d["F"] else None
        d["move_median"] = round(_st.median(d["move"]), 6) if d["move"] else None
        d["move_max"] = round(max(d["move"]), 5) if d["move"] else None
        d["shift_pnl"] = round(d["shift_pnl"], 4)
        d["cap_pnl"] = round(d["cap_pnl"], 4)
        d["over_sum"] = round(d["over_sum"], 4)
        del d["F"], d["move"]
        log(f"{rk}: закрытых {d['n']}, покрыто {d['covered']} "
            f"({_s(d['cover'])}), сдвинуто {d['shift']}, крышка −100 % у "
            f"{d['capped']}, ниже −100 % было {d['over_100']}")
    cover_n = sum(d["covered"] for d in by.values())
    cover_all = sum(d["n"] for d in by.values())
    diag.update({"closed": cover_all, "covered": cover_n,
                 "cover": round(cover_n / cover_all, 4) if cover_all else None,
                 "worst_over_100": (None if worst_over is None
                                    else round(worst_over, 4))})
    return out, {"rulers": by, "diag": diag}


def _wo3d(days):
    """Деньги книги без ТРЁХ лучших суток; меньше четырёх суток — прочерк.

    Колонка обязательна в обеих версиях счёта: у коротких книг без трёх
    лучших дней остаётся 28–48 % денег, и концентрация переворачивает
    знак. Считается по тем же суткам, которые вернула касса книги
    (`run_paper._stats` → `days_rows`), своего деления по дням здесь нет.
    """
    v = sorted((float(d["usd"]) for d in (days or [])), reverse=True)
    if len(v) <= 3:
        return None
    return round(sum(v) - sum(v[:3]), 2)


def form_of(cell):
    """Форма книги: устойчивость по суткам + деньги без трёх лучших дней.

    Укус, медиана прибыльных суток и худший день считаются
    `factory/stability.stats` — той же мерой, которой судится пул; своей
    копии отношения «худший день / медиана хорошего» здесь нет.
    """
    days = (cell or {}).get("days") or []
    daily = {d["d"]: float(d["usd"]) for d in days}
    st = ST.stats(daily) if daily else None
    return {"bite": (st or {}).get("bite"), "worst": (st or {}).get("worst"),
            "med_green": (st or {}).get("med_green"),
            "med": (st or {}).get("med"), "green": (st or {}).get("green"),
            "days": len(days), "wo3d": _wo3d(days),
            "liq": ((cell or {}).get("exits") or {}).get("ликвидация", {}).get("n", 0),
            "floor": ((cell or {}).get("exits") or {}).get("пол", {}).get("n", 0)}


def _d(a, b):
    return None if (a is None or b is None) else round(float(b) - float(a), 6)


def compare(base, corr, dep=MAIN_DEP, keys=None):
    """Книга до и после поправки: деньги, форма, число ликвидаций."""
    out = {}
    for bk in (keys or BOOK_KEYS):
        k = f"{bk}:{int(dep)}"
        b, c = base.get(k) or {}, corr.get(k) or {}
        fb, fc = form_of(b), form_of(c)
        out[bk] = {
            "base": {"n": b.get("n"), "usd": b.get("usd"),
                     "final": b.get("final"), "max_dd": b.get("max_dd"),
                     "win": b.get("win"), "day_median": b.get("day_median"),
                     "taken": b.get("taken"), "form": fb},
            "corr": {"n": c.get("n"), "usd": c.get("usd"),
                     "final": c.get("final"), "max_dd": c.get("max_dd"),
                     "win": c.get("win"), "day_median": c.get("day_median"),
                     "taken": c.get("taken"), "form": fc},
            "d_usd": _d(b.get("usd"), c.get("usd")),
            "d_final": _d(b.get("final"), c.get("final")),
            "d_max_dd": _d(b.get("max_dd"), c.get("max_dd")),
            "d_bite": _d(fb["bite"], fc["bite"]),
            "d_worst": _d(fb["worst"], fc["worst"]),
            "d_wo3d": _d(fb["wo3d"], fc["wo3d"]),
            "d_liq": _d(fb["liq"], fc["liq"]),
            "med_green": fb["med_green"]}
    return out


def checks(s, postponed="upper"):
    """Четыре порога «мертво» по каждой книге — числом и со своим итогом.

    `postponed` выбирает, какой из двух счётов следствия «б» судит:
    `upper` — верхняя оценка (каждая запись с полученным funding),
    `band` — полоса (отметка выхода между прежним и новым уровнем).
    Считаются ОБА и печатаются оба: молча выбранная трактовка — решение,
    принятое там, где его никто не увидит.
    """
    rulers = (s.get("screen") or {}).get("rulers") or {}
    out = []
    for bk, c in sorted((s.get("books") or {}).items()):
        d = rulers.get(S.BOOKS.get(bk)) or {}
        n_cov = d.get("covered") or 0
        share = d.get("shift_share")
        pn = (d.get("postponed") if postponed == "upper"
              else d.get("postponed_band"))
        psh = (round(pn / n_cov, 5) if (n_cov and pn is not None) else None)
        med_green, du, db = c.get("med_green"), c.get("d_usd"), c.get("d_bite")
        out += [
            {"book": bk, "name": "доля сдвинутых позиций", "value": share,
             "limit": DEAD_SHIFT_SHARE, "unit": "share",
             "ok": (share is not None and share < DEAD_SHIFT_SHARE)},
            {"book": bk, "name": "сдвиг итога против медианы прибыльного дня",
             "value": du, "limit": (None if med_green is None
                                    else abs(float(med_green))), "unit": "usd",
             "ok": (du is not None and med_green is not None
                    and abs(du) < abs(float(med_green)))},
            {"book": bk, "name": "сдвиг укуса", "value": db,
             "limit": DEAD_BITE, "unit": "abs",
             "ok": (db is not None and abs(db) < DEAD_BITE)},
            {"book": bk,
             "name": ("доля записей с отодвинутым полом ("
                      + ("верхняя оценка" if postponed == "upper" else "полоса")
                      + ")"),
             "value": psh, "limit": DEAD_POSTPONED_SHARE, "unit": "share",
             "ok": (psh is not None and psh < DEAD_POSTPONED_SHARE)}]
    return out


def _state(chk):
    bad = [c for c in chk if not c["ok"]]
    return ("мертво (предварительно)" if not bad else "есть что править"), bad


def verdict(s):
    """Вердикт ИЗ ЧИСЕЛ: блок по покрытию, «мертво», «есть что править».

    Фраза не стоит рядом с числами литералом — она собирается здесь из
    тех же полей, которые печатает таблица. Иначе она стареет молча и
    однажды противоречит своему же числу.

    Судит СТРОГАЯ трактовка следствия «б» (верхняя оценка): ошибиться в
    сторону «есть что править» дешевле, чем объявить реплей честным.
    Вердикт по второй трактовке (полоса) считается тут же и печатается
    рядом под своим именем.
    """
    diag = (s.get("screen") or {}).get("diag") or {}
    cover = diag.get("cover")
    if cover is None:
        return {"state": "заблокировано", "cover": None, "checks": [],
                "why": "покрытие рядами funding не измерено — считать нечего"}
    if cover < MIN_COVER:
        return {"state": "заблокировано", "cover": cover, "checks": [],
                "why": (f"ряды funding не покрывают журнал: покрыто "
                        f"{100 * cover:.1f} % закрытых записей при пороге "
                        f"{100 * MIN_COVER:.0f} % — первым заданием идёт "
                        "догон рядов, а не вердикт")}
    chk = checks(s, postponed="upper")
    state, bad = _state(chk)
    alt_state, alt_bad = _state(checks(s, postponed="band"))
    note = ("" if cover >= FULL_COVER else
            f" Оговорка: покрыто {100 * cover:.1f} % записей при полном "
            f"{100 * FULL_COVER:.0f} % — непокрытые в счёт поправки не идут.")
    if not bad:
        why = ("на этом журнале ни один из четырёх порогов заявки не "
               "перейдён: реплей честен в пределах почасовых отметок. "
               "Предварительно — потолок недооценивает по построению (пол и "
               "ликвидация бьют внутри часа), и «мертво» подтверждает "
               "только шаг 2, реплей по барам." + note)
    else:
        names = "; ".join(f"{c['book']}: {c['name']}" for c in bad)
        why = ("потолок перешёл пороги — " + names
               + f" (всего {len(bad)} из {len(chk)} проверок). Потолок "
                 "недооценивает по построению, значит это НИЖНЯЯ граница "
                 "правки; на сколько именно — отвечает шаг 2 (реплей по "
                 "барам)." + note)
    return {"state": state, "cover": cover, "checks": chk, "why": why,
            "n_fail": len(bad), "n_checks": len(chk),
            "alt": {"reading": "полоса", "state": alt_state,
                    "n_fail": len(alt_bad),
                    "why": ("по второй трактовке следствия «б» (полоса: "
                            "отметка выхода легла между прежним и новым "
                            "уровнем) вердикт был бы «" + alt_state + "» — "
                            + (f"перейдено порогов {len(alt_bad)}"
                               if alt_bad else "пороги не перейдены"))}}


def run(log=print, cache_path=None, ctx=None, launch=None, now=None,
        mem_limit=None, dep=MAIN_DEP, seeds=200):
    """Шаг 1 целиком: покрытие → потолок → деньги двух счётов → вердикт."""
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    cache, why = S.read_cache(cache_path, log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    if not cache:
        return {"error": "кэш реплея пуст: считать потолок не по чему"}
    ctx = CO.context() if ctx is None else ctx
    if ctx.get("error") and not ctx.get("funding"):
        return {"error": f"контекст издержек не собран: {ctx['error']}"}
    launch = IR.launches() if launch is None else launch
    log(f"кэш: записей {len(cache)}, рядов funding "
        f"{len(ctx.get('funding') or {})}, справочник листингов "
        f"{len(launch or {})}")
    corr, scr = screen(cache, ctx, log=log)
    sense = sense_controls(cache, ctx, seeds=seeds, log=log)
    log(f"потолок посчитан, {time.time() - t0:.0f} с — считаю деньги")
    base = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                       deps=[dep], now=now)
    after = AG.stats_of(AG.packed_short(corr), ctx, launch, BOOK_KEYS,
                        deps=[dep], now=now)
    s = {"screen": scr, "books": compare(base, after, dep=dep),
         "sense": sense,
         "dep": int(dep), "min_cover": MIN_COVER, "full_cover": FULL_COVER,
         "thresholds": {"dead_shift": DEAD_SHIFT_SHARE, "dead_bite": DEAD_BITE,
                        "dead_postponed": DEAD_POSTPONED_SHARE,
                        "alive_shift": ALIVE_SHIFT_SHARE,
                        "alive_worst": ALIVE_WORST_FRAC,
                        "alive_bite": ALIVE_BITE, "alive_liq": ALIVE_LIQ},
         "books_order": BOOK_KEYS, "scale": SCALE,
         "costs_error": ctx.get("error"),
         "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}
    s["verdict"] = verdict(s)
    log(f"вердикт: {s['verdict']['state']} — {s['verdict']['why']}")
    return s


# --------------------------------------------------------- контроли смысла

def _flip_series(ctx):
    """Те же ряды с ЗНАКОМ НАОБОРОТ: расход становится доходом."""
    return {a: (t, -r) for a, (t, r) in (ctx.get("funding") or {}).items()}


def _shuffle_series(ctx, seed):
    """Ряды, ПЕРЕМЕШАННЫЕ между именами: у имени чужая история ставок."""
    import random
    keys = sorted(ctx.get("funding") or {})
    vals = [ctx["funding"][k] for k in keys]
    random.Random(seed).shuffle(vals)
    return dict(zip(keys, vals))


def sense_controls(cache, ctx, floors=None, seeds=200, log=print):
    """Два контроля смысла, объявленные заявкой, — числами.

    **Знак наоборот.** Ряд с перевёрнутым знаком обязан дать ДРУГОЕ число
    сдвинутых позиций. Совпадение означало бы, что знак ставки в счёт не
    входит вовсе, то есть сдвигает не funding, а что-то другое.

    **Перемешанный ряд** (`seeds` зёрен). Если чужая история ставок
    сдвигает столько же позиций, сколько своя, начисления бьют не
    «дорогие имена», а любую тонкую маржу — и лекарство тогда плечо, а не
    модель funding. Это ДИАГНОСТИКА, а не убийца: доля печатается, вердикт
    по ней не выносится. Перемешивание меняет и покрытие (чужой ряд может
    не накрыть жизнь позиции), поэтому рядом печатается медиана покрытых.
    """
    floors = floors if floors is not None else floor_by_ruler()

    def _n(fund):
        _o, s = screen(cache, dict(ctx, funding=fund), floors=floors,
                       log=lambda *a: None)
        return (sum(d["shift"] for d in s["rulers"].values()),
                sum(d["covered"] for d in s["rulers"].values()))
    real, real_cov = _n(ctx.get("funding") or {})
    flip, flip_cov = _n(_flip_series(ctx))
    draws, covs = [], []
    t0 = time.time()
    for i in range(int(seeds)):
        n, cov = _n(_shuffle_series(ctx, 1000 + i))
        draws.append(n)
        covs.append(cov)
        if i and i % 50 == 0:
            log(f"    перемешивание: {i} зёрен из {seeds}, "
                f"{time.time() - t0:.0f} с")
    ge = (round(sum(1 for x in draws if x >= real) / len(draws), 3)
          if draws else None)
    out = {"real": real, "real_covered": real_cov, "flip": flip,
           "flip_covered": flip_cov, "seeds": int(seeds),
           "shuffle_median": (round(_st.median(draws), 1) if draws else None),
           "shuffle_max": (max(draws) if draws else None),
           "shuffle_ge_real": ge,
           "shuffle_cover_median": (round(_st.median(covs), 1) if covs else None)}
    out["sign_read"] = bool(flip != real)
    out["why"] = (
        (f"знак читается: перевёрнутый ряд сдвигает {flip} позиций против "
         f"{real} у настоящего" if out["sign_read"] else
         f"ЗНАК НЕ ЧИТАЕТСЯ: перевёрнутый ряд сдвигает те же {flip} позиций "
         "— сдвигает не funding")
        + ("; перемешивание не считалось (зёрен 0)" if not draws else
           f"; перемешанный между именами ряд даёт медиану {out['shuffle_median']} "
           f"и не хуже настоящего у {100 * ge:.1f} % из {len(draws)} зёрен"))
    log(out["why"])
    return out


# ------------------------------------------------------- калибровочная пара

def _flat_series(ctx, rate):
    """Ряды тех же имён и тех же МОМЕНТОВ с подставленной ставкой.

    Моменты берутся у настоящего ряда: число начислений есть свойство
    имени (318 символов из 722 меняли режим), и ровный интервал сделал бы
    подделку непохожей на жизнь.
    """
    out = {}
    for a, (t, r) in (ctx.get("funding") or {}).items():
        out[a] = (t, r * 0.0 + float(rate))
    return out


def calibrate(log=print, cache_path=None, ctx=None, limit=None, cache=None):
    """Найти подсаженное и промолчать на нуле — обе ноги числами.

    Нога «нуль»: ставки всех имён обнулены. Потолок обязан не сдвинуть
    НИ ОДНОЙ позиции, а правленый кэш — совпасть с исходным запись в
    запись. Это не пожелание: наше условие строго строже движкового
    (ставка поддерживающей маржи опущена), поэтому при нулевом funding
    сработать оно не может, и любое срабатывание есть дефект формулы.

    Нога «подсадка»: ставка настолько отрицательная, что ПЕРВОЕ же
    начисление съедает всю маржу. Каждая покрытая позиция, у которой
    начисление успевает лечь строго до записанного выхода, обязана
    сдвинуться, и именно ликвидацией.
    """
    if cache is None:
        cache, why = S.read_cache(cache_path, log=log)
        if why:
            return {"error": f"кэш реплея непригоден: {why}"}
    ctx = CO.context() if ctx is None else ctx
    if not (ctx.get("funding") or {}):
        return {"error": "рядов funding нет — калибровать нечем"}
    if limit:
        keys = sorted(cache)[:int(limit)]
        cache = {k: cache[k] for k in keys}
    floors = floor_by_ruler()
    zero_ctx = dict(ctx, funding=_flat_series(ctx, 0.0))
    z_cache, z = screen(cache, zero_ctx, floors=floors, log=lambda *a: None)
    n_zero = sum(d["shift"] for d in z["rulers"].values())
    same = all(z_cache[k] is cache[k] or z_cache[k] == cache[k] for k in cache)
    # Подсадка: |ставка| × открытый нотионал ≥ 1.2 маржи у самого
    # мелкого нотионала выборки — тогда первое начисление съедает маржу
    # у КАЖДОЙ позиции, а не у везучих.
    filled = [float(r.get("filled") or 0) for r in cache.values()
              if float(r.get("filled") or 0) > 0]
    rate = -1.2 / min(filled) if filled else -1.0
    big_ctx = dict(ctx, funding=_flat_series(ctx, rate))
    _b_cache, b = screen(cache, big_ctx, floors=floors, log=lambda *a: None)
    n_big = sum(d["shift"] for d in b["rulers"].values())
    n_big_liq = sum(d["shift_liq"] for d in b["rulers"].values())
    covered = sum(d["covered"] for d in b["rulers"].values())
    # Сколько позиций подсадка ОБЯЗАНА сдвинуть: у которых начисление
    # ложится строго до записанного выхода и есть отметки.
    must = 0
    funding = big_ctx["funding"]
    for key, rec in cache.items():
        if (rec.get("state") or "closed") != "closed":
            continue
        ser = funding.get((ctx.get("to_asset") or {}).get(rec.get("sym")))
        got = accruals(rec, ser) if ser is not None else None
        p = WV.path_of(rec)
        if got is None or p is None:
            continue
        if any(ts < float(rec["at"]) + (p["K"] - 1) * HOUR for ts, _d in got[1]):
            must += 1
    ok = (n_zero == 0 and same and n_big >= must and must > 0
          and n_big_liq == n_big)
    out = {"ok": bool(ok), "n": len(cache), "covered": covered,
           "zero_shifts": n_zero, "zero_cache_same": bool(same),
           "planted_rate": rate, "planted_shifts": n_big,
           "planted_liq": n_big_liq, "planted_must": must,
           "computed_at": G.stamp()}
    out["why"] = (
        "пара годна: на нулевых ставках потолок молчит и кэш тождествен "
        f"исходному, подсадка {rate:.3g} за начисление сдвинула {n_big} "
        f"позиций из {must} обязанных, все ликвидацией"
        if ok else
        "пара НЕ годна: " + "; ".join(x for x in [
            (f"на нулевых ставках сдвинуто {n_zero} позиций — формула "
             "срабатывает без funding") if n_zero else "",
            ("правленый кэш на нулевых ставках не совпал с исходным"
             if not same else ""),
            (f"подсадка сдвинула {n_big} при {must} обязанных"
             if n_big < must else ""),
            ("подсадке нечего было двигать: ни одного начисления внутри "
             "жизни позиций" if not must else ""),
            (f"сдвиг не ликвидацией у {n_big - n_big_liq} позиций"
             if n_big_liq != n_big else "")] if x))
    log(out["why"])
    return out


# ------------------------------------------------------------------ отчёт

def _u(x, d=2):
    return "—" if x is None else f"{float(x):+,.{d}f}"


def _p(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _s(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _n(x):
    return "—" if x is None else f"{x}"


def report(s):
    L = ["# Механика 9dd65163, шаг 1: funding внутри пути позиции — потолок на кэше",
         "",
         "Вопрос: меняет ли МОМЕНТ учёта funding исход позиций коротких "
         "книг `h24`. Сегодня реплей ведёт позицию маржой, которая за 24 "
         "часа жизни не меняется ни разу, а начисления вычитаются после "
         "факта из уже записанного исхода; в жизни они списываются с маржи "
         "каждые 1–8 часов, и от остатка маржи зависит, где стоят "
         "ликвидация и пол капитуляции. Здесь это проверено САМЫМ ДЕШЁВЫМ "
         "способом — без реплея по барам: по почасовым отметкам ядра из "
         "кэша реплея и накопленному к часу funding.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    v = s.get("verdict") or {}
    scr = s.get("screen") or {}
    diag = scr.get("diag") or {}
    rulers = scr.get("rulers") or {}
    L += ["## Покрытие рядами и записи ниже −100 % маржи (до денег)", "",
          "Ряд, скачанный однажды, стареет молча, поэтому покрытие печатается "
          "ПЕРВЫМ и числом. Покрыта позиция, чью жизнь от первого рунга до "
          "выхода ряд площадки исполнения закрывает целиком (условие то же, "
          "что у замера издержек: начисление позже последней точки ряда — не "
          "нулевая ставка, а отсутствие данных). «Ниже −100 %» — записи, у "
          "которых ЦЕНА плюс funding после факта дают убыток глубже всей "
          "маржи позиции: на изолированном счёте такого не бывает, и это "
          "прямая мера дефекта.", "",
          "| линейка | пол | книги | закрытых | покрыто | нет ряда | "
          "ряд не покрывает | без отметок | F на позицию: медиана / среднее | "
          "F: минимум / максимум | ниже −100 % | сумма перебора, маржи |",
          "|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for rk, d in sorted(rulers.items()):
        L.append(f"| `{rk}` | {d['floor']:g} | "
                 + ", ".join(f"`{b}`" for b in d["books"])
                 + f" | {d['n']} | {_s(d['cover'])} | {d['no_series']} | "
                 f"{d['uncovered']} | {d['no_marks']} | "
                 f"{_p(d['F_median'], 3)} / {_p(d['F_mean'], 2)} | "
                 f"{_p(d['F_min'], 1)} / {_p(d['F_max'], 1)} | "
                 f"{d['over_100']} | {_u(d['over_sum'], 3)} |")
    L += ["", f"Всего закрытых записей {diag.get('closed')}, покрыто "
          f"{_s(diag.get('cover'))} при пороге вердикта "
          f"{100 * s.get('min_cover', MIN_COVER):.0f} % и полном "
          f"{100 * s.get('full_cover', FULL_COVER):.0f} %; открытых позиций "
          f"{diag.get('open')} (у них выхода нет, и поправлять нечего). "
          f"Худшая суммарная потеря до поправки "
          f"{_p(diag.get('worst_over_100'), 1)} маржи; ПОСЛЕ поправки записей "
          f"глубже −100 % маржи осталось {diag.get('over_after')} (заявка "
          "обещала ноль «по построению» — потолок ловит только то, что "
          "успело перейти уровень к КОНЦУ часа, и начисление, легшее в "
          "последний час жизни, остаётся за ним). Сумма событий расходится с "
          f"итогом `costs.funding_usd` у {diag.get('event_sum_mismatch')} "
          "записей (обязано быть 0).", ""]
    L += ["## Что потолок нашёл", "",
          "**Сдвиг** — час, на котором пол или ликвидация по СКОРРЕКТИРОВАННОЙ "
          "марже сработали бы строго раньше записанного выхода. **Крышка "
          "−100 %** — ликвидированная позиция, которой учёт после факта "
          "приписывал убыток глубже маржи: её ценовой исход равен −(1 + F), а "
          "вместе с начислениями ровно −1. **Отодвинутый пол** — запись, "
          "закрытая полом или ликвидацией, у которой funding ПОЛУЧЕН: уровень "
          "стоит глубже, в этом баре позиция не резалась бы, а что было бы "
          "дальше, знают только бары — деньгами это не измеряется здесь "
          "вовсе.", "",
          "| линейка | сдвинуто | доля | из них полом / ликвидацией | "
          "Σ Δ ценового pnl, маржи | крышка −100 % | Σ Δ, маржи | "
          "пол/ликвидация в записи | отодвинутый пол (верхняя оценка) | доля | "
          "в полосе сдвига | сдвиг уровня: медиана / максимум |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for rk, d in sorted(rulers.items()):
        L.append(f"| `{rk}` | {d['shift']} | {_s(d['shift_share'], 3)} | "
                 f"{d['shift_floor']} / {d['shift_liq']} | "
                 f"{_u(d['shift_pnl'], 3)} | {d['capped']} | "
                 f"{_u(d['cap_pnl'], 3)} | {d['exits_floor']} | "
                 f"{d['postponed']} | {_s(d['postponed_share'], 2)} | "
                 f"{d['postponed_band']} | "
                 f"{_p(d['move_median'], 3)} / {_p(d['move_max'], 2)} |")
    L += ["", "«Верхняя оценка» и «полоса» — две честные границы одного "
          "вопроса, и путать их нельзя. Верхняя считает КАЖДУЮ запись с "
          "полученным funding: арифметически любой полученный funding "
          "отодвигает уровень, и в том самом баре позиция не резалась бы. "
          "Полоса считает только те, у которых отметка выхода легла МЕЖДУ "
          "прежним и новым уровнем, — у неё есть честный нуль (при нулевых "
          "ставках полоса пуста по построению), и она говорит, насколько "
          "сдвиг материален. Вердикт ниже берёт СТРОГУЮ из двух (верхнюю): "
          "ошибиться в сторону «есть что править» дешевле, чем объявить "
          "реплей честным.", ""]
    sn = s.get("sense") or {}
    if sn:
        L += ["## Контроли смысла: знак наоборот и перемешанный ряд", "",
              f"**Знак наоборот.** Настоящий ряд сдвигает {sn.get('real')} "
              f"позиций (покрыто {sn.get('real_covered')}), ряд с "
              f"перевёрнутым знаком — {sn.get('flip')} (покрыто "
              f"{sn.get('flip_covered')}). "
              + ("Знак читается." if sn.get("sign_read") else
                 "**Знак НЕ читается** — числа совпали, значит сдвигает не "
                 "funding, и читать таблицы выше нельзя.") + "", "",
              f"**Перемешанный между именами ряд** ({sn.get('seeds')} зёрен) "
              "— диагностика, не убийца: если чужая история ставок сдвигает "
              "столько же позиций, начисления бьют не «дорогие имена», а "
              "любую тонкую маржу, и лекарство тогда плечо, а не модель "
              f"funding. Медиана {sn.get('shuffle_median')}, максимум "
              f"{sn.get('shuffle_max')}, не хуже настоящего у "
              f"{_s(sn.get('shuffle_ge_real'), 1)} зёрен; медиана покрытых "
              f"записей при перемешивании {sn.get('shuffle_cover_median')} "
              f"против {sn.get('real_covered')} — чужой ряд накрывает жизнь "
              "позиции не всегда, и это часть диагностики, а не её дефект.",
              ""]
    L += ["## Деньги книг: базовый счёт и счёт с начислениями в марже", "",
          f"Депозит ${s.get('dep')}, деньги НЕТТО (те же издержки в каждой "
          "сделке), касса и правила книги — те же (`run_paper`: возраст "
          "имени, охрана рынком, «одна на имя», билет стороны). Колонка «без "
          "3 лучших дней» обязательна в обеих версиях: у коротких книг деньги "
          "эпизодичны, и концентрация переворачивает знак.", "",
          "| книга | сделок | итог, $ | итог, % | просадка | худший день, $ | "
          "укус | без 3 лучших дней, $ | ликвидаций | полом | "
          "Δ итога, $ | Δ укуса | Δ худшего дня, $ | Δ ликвидаций |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in s.get("books_order") or BOOK_KEYS:
        c = (s.get("books") or {}).get(bk)
        if not c:
            L.append(f"| `{bk}` | — | — | — | — | — | — | — | — | — | — | — | — | — |")
            continue
        for tag, side in (("база", c["base"]), ("с начислениями", c["corr"])):
            f = side["form"]
            extra = ("" if tag == "база" else
                     f" {_u(c['d_usd'])} | {_u(c['d_bite'])} | "
                     f"{_u(c['d_worst'])} | {_n(c['d_liq'])} |")
            L.append(f"| `{bk}`, {tag} | {_n(side['n'])} | {_u(side['usd'])} | "
                     f"{_p(side['final'])} | {_p(side['max_dd'])} | "
                     f"{_u(f['worst'])} | {_n(f['bite'])} | {_u(f['wo3d'])} | "
                     f"{_n(f['liq'])} | {_n(f['floor'])} |"
                     + (extra if extra else " — | — | — | — |"))
    L += ["", "## Вердикт", "",
          f"**{v.get('state')}.** {v.get('why')}", "",
          f"{(v.get('alt') or {}).get('why', '')}", ""]
    if v.get("checks"):
        L += ["| книга | проверка | величина | порог | сошлось |",
              "|---|---|--:|--:|:-:|"]
        for c in v["checks"]:
            fmt = (_s if c["unit"] == "share"
                   else (_u if c["unit"] == "usd" else _u))
            L.append(f"| `{c['book']}` | {c['name']} | {fmt(c['value'])} | "
                     f"{fmt(c['limit'])} | {'да' if c['ok'] else '**НЕТ**'} |")
        L.append("")
    th = s.get("thresholds") or {}
    L += ["Пороги объявлены ЗАЯВКОЙ до прогона и здесь только прочитаны. "
          f"«Мертво»: во всех трёх книгах доля сдвинутых < {100 * th.get('dead_shift', 0):g} %, "
          "|сдвиг итога| меньше медианы прибыльного дня, |сдвиг укуса| < "
          f"{th.get('dead_bite')}, доля записей с отодвинутым полом < "
          f"{100 * th.get('dead_postponed', 0):g} %. «Живо» (границы шага 2, "
          "реплея по барам): доля сдвинутых ≥ "
          f"{100 * th.get('alive_shift', 0):g} %, либо |Δ худшего дня| ≥ "
          f"{100 * th.get('alive_worst', 0):g} % его величины, либо |Δ укуса| ≥ "
          f"{th.get('alive_bite')}, либо число ликвидаций меняется на ≥ "
          f"{th.get('alive_liq')}.", "",
          "## Чего этот замер НЕ говорит", "",
          "1. **Потолок недооценивает по построению.** Отметки почасовые, а "
          "пол и ликвидация в жизни бьют внутри часа: позиция, у которой "
          "закрытие прошлого часа стояло далеко от уровня, за минуту доходит "
          "до него и умирает. Сработавший потолок сдвиг ДОКАЗЫВАЕТ, молчащий "
          "отсутствия сдвига не доказывает.",
          "2. **Шаг 2 здесь не построен.** Реплей по барам с начислениями в "
          "марже есть правка ядра (`dca_ladder/ladder.py`, один "
          "необязательный аргумент), а она лежит вне каталога механики: "
          "публикация роли выпускает только `research/factory/` и каталог "
          "механики, и правка ядра осталась бы на сервере — прогон был бы, а "
          "в ветке пусто. Это работа роли `fix`.",
          "3. **Час выхода у сдвинутой позиции — граница часа.** Исход берётся "
          "отметкой ядра на закрытии часа (тем же способом, что у охраны "
          "рынком, где равенство отметки усечению доказано на 6100 точках); "
          "в жизни пол срабатывает внутри часа и по другой цене.",
          "4. **Это правка МЕРЫ, а не правила.** Ни одной сделки не "
          "вычёркивается и ни одного размера не меняется. Если хвост после "
          "поправки стал мельче — это не «книга стала лучше», а «мера стала "
          "честной»; если глубже — книги, судимые вперёд до 04.10, судились "
          "на завышенной кривой.",
          "5. **Счёт изолированный.** Книги считают маржу на позицию (пол и "
          "цена ликвидации от собственной `capital`), и механика следует "
          "модели книги. Кросс-маржа дала бы другие числа — это другая "
          "механика, и она не предлагается.",
          "", f"Расчёт: {s.get('computed_at')}, {s.get('secs')} с."
          + (f" Издержки: {s['costs_error']}." if s.get("costs_error") else ""),
          ""]
    return "\n".join(L)


def write(s, name=ART, report_fn=report, log=print):
    """Артефакт и отчёт — в СВОЙ каталог out/, который публикуется.

    Своя запись, а не `short_grid.write`: тот кладёт файлы в
    `dca_paper/out`, то есть вне каталога механики, и опубликованы они бы
    не были.
    """
    os.makedirs(OUT, exist_ok=True)
    art = os.path.join(OUT, f"{name}.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report_fn(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    log(txt)
    return txt


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--calibrate", action="store_true",
                    help="только калибровочная пара: молчит на нуле, находит "
                         "подсаженное; код возврата 2 — пара негодна")
    ap.add_argument("--limit", type=int, default=None,
                    help="смоук: столько записей кэша")
    ap.add_argument("--seeds", type=int, default=200,
                    help="зёрен перемешанного ряда (контроль смысла); "
                         "меньше объявленных 200 — разрешение доли грубее")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    if a.calibrate:
        c = calibrate(log=print, limit=a.limit)
        with open(os.path.join(OUT, f"{ART}-calib.json"), "w",
                  encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        return 0 if c.get("ok") else 2
    s = run(log=print, seeds=a.seeds)
    if s.get("error"):
        print(s["error"])
    write(s, log=print)
    if not a.no_publish:
        publish("механика 9dd65163: funding внутри пути позиции — потолок на кэше")
    return 0


if __name__ == "__main__":
    sys.exit(main())
