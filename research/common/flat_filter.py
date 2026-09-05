"""Плоский инструмент: цены нет, а издержки есть.

Владелец увидел USDEUSDT на графике DCA-книги — свечи стоят на 0.9994,
размах суток около шести базисных пунктов при круге издержек 11, — и
попросил убрать торговлю такими парами. Пара исполняется, комиссия
платится, а хода, из которого её можно отбить, не существует.

**Правило МЕРИТСЯ, а не ведётся списком.** Поимённый список отставал от
каждой волны листингов трижды (CSOP, биржевые акции августа 2026,
ISRG), и стейблов это касается ровно так же: сегодня их четыре, завтра
площадка листингует пятый. Мера снимается с наших же почасовых сводок
(`s8_loop/out/summary`) — тех самых, на которых учится модель, — и имя,
которое начало ходить, перестаёт быть плоским само.

Порог объявлен ДО замера и выведен из арифметики, а не из вида
распределения: круг издержек 11 б.п. на ногу, двойной круг 22, порог
50 б.п. медианного СУТОЧНОГО размаха. Замер `probe_stables` показал,
что он попадает в ПРОВАЛ распределения — соседи у границы 7.0 и 65.05
б.п., скачок в 9.3 раза, ниже порога ровно четыре имени (USD1, USDE,
USDC, RLUSD) и ни одного живого. В плотной области такое правило
однажды выбросило бы живое имя, и вводить его было бы нельзя.

**Меньше `MIN_DAYS` суток под именем — величина НЕ измерена, а не мала.**
Свежий листинг и стейбл различаются только числом суток под мерой, и
молчаливое отсечение по «мало данных» запретило бы каждое новое имя на
первые дни его жизни.

Запись при этом НЕ прекращается: сборщик пишет всё торгуемое, иначе
мерить стало бы нечем. Правило стоит на ВЫБОРЕ — как и отсечение
не-крипто, — и из обучения имена не выдёргиваются: менять выборку
задним числом значило бы судить прошлое по сегодняшнему правилу.
"""

import json
import os
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = os.path.join(os.path.dirname(HERE), "s8_loop", "out", "summary")

# Порог и окно объявлены до замера (см. шапку). Менять их после
# результата запрещено правилом проекта.
FLAT_MAX_BP = 50.0
WINDOW_D = 14
MIN_DAYS = 3


def day_range_bp(path):
    """Суточный размах середины по часам одного дня, б.п. Нет — None.

    Размах, а не доходность: час, в котором цена сходила и вернулась,
    доходность считает спокойным, а пережить его позиции пришлось
    целиком (тот же довод, что на странице волатильности). Сутки
    сводятся одним max/min по часам, а не суммой часовых размахов:
    сумма мерила бы ПУТЬ, а нас интересует ХОД.
    """
    hi = lo = close = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                h, l, c = r.get("mid_high"), r.get("mid_low"), r.get("mid_close")
                if h is None or l is None or not c:
                    continue
                hi = h if hi is None else max(hi, h)
                lo = l if lo is None else min(lo, l)
                close = c
    except OSError:
        return None
    if hi is None or not close:
        return None
    return (hi - lo) / close * 1e4


def scan(summary=None, days=WINDOW_D, now=None, log=None):
    """Медианный суточный размах по каждому имени, б.п.

    Возвращает `{символ: (медиана б.п., суток под мерой)}`; имена, у
    которых суток меньше `MIN_DAYS`, в ответ не попадают вовсе —
    неизмеримое не есть плоское.
    """
    root = summary or SUMMARY
    try:
        syms = sorted(os.listdir(root))
    except OSError:
        return {}
    day_of = {}
    for sym in syms:
        d = os.path.join(root, sym)
        if not os.path.isdir(d):
            continue
        try:
            day_of[sym] = [f for f in sorted(os.listdir(d))
                           if f.endswith(".jsonl")]
        except OSError:
            continue
    # Окно отсчитывается от САМОГО СВЕЖЕГО дня записи, а не от
    # настенных часов: остановленный сбор иначе молча опустошал бы
    # правило (мера перестала бы связывать кого бы то ни было, и
    # отличить это от «плоских имён нет» было бы нечем). Судим по
    # тому, что записано; явный `now` перекрывает — им пользуется
    # проверка.
    newest = max((f[:10] for fs in day_of.values() for f in fs),
                 default=None)
    if now is not None:
        newest = time.strftime("%Y-%m-%d", time.gmtime(float(now)))
    if not newest:
        return {}
    t = time.mktime(time.strptime(newest, "%Y-%m-%d"))
    cut = time.strftime("%Y-%m-%d", time.localtime(t - days * 86400))
    out, said = {}, time.time()
    for i, sym in enumerate(sorted(day_of)):
        d = os.path.join(root, sym)
        if log and time.time() - said > 30:
            log(f"  {i}/{len(day_of)} имён")
            said = time.time()
        vals = []
        for f in day_of[sym]:
            if f[:10] < cut:
                continue
            v = day_range_bp(os.path.join(d, f))
            if v is not None:
                vals.append(v)
        if len(vals) >= MIN_DAYS:
            out[sym] = (statistics.median(vals), len(vals))
    return out


def flat_names(summary=None, days=WINDOW_D, now=None, ranges=None):
    """Имена, которыми торговать нечем: ход мельче порога.

    `ranges` — готовый ответ `scan`, если он уже посчитан (замер и цикл
    считают одну и ту же величину, и второго прохода по сводкам ради
    неё быть не должно).
    """
    r = scan(summary, days, now) if ranges is None else ranges
    return {s for s, (v, _) in r.items() if v < FLAT_MAX_BP}


def is_flat(sym, flat):
    """Плоское ли имя. Пустое множество — правило не связывает никого."""
    return str(sym).upper() in (flat or set())
