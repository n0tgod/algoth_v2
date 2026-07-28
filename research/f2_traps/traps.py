#!/usr/bin/env python3
"""
F2 — ловушки раздела 5 спеки 04. Ядро расчёта.

Здесь только арифметика мер. Ни диска, ни базы — чтобы проверялось
тестами с известным ответом.

Почему бета считается по ряду книги, а не по бетам активов
----------------------------------------------------------

Соблазн: посчитать β каждого актива к волне, потом взвесить весами
книги. Так пришлось бы заново грузить цены и оценивать β на окне
формирования — то есть повторить половину R1.

Но β книги есть свойство её доходности, а не её состава, и меряется
она прямо: регрессией ценового борта книги на доходность волны за те
же периоды. Обе величины уже сохранены прогоном F1 — форвардные
доходности всех активов сечения лежат в векторах, и волна есть их
равновзвешенное среднее.

Это не экономия, а точность. Взвешенная сумма оценённых β несёт в себе
ошибки оценки каждой из них и молчаливо предполагает, что β постоянна
на окне удержания. Регрессия ряда книги не предполагает ничего.
"""

import numpy as np


def market_return(price_fwd):
    """Доходность равновзвешенной волны за период: среднее по сечению.

    Та же конструкция, что в R1 §3.1: равные веса, а не по размеру.
    Универсум идёт от 134 активов в 2022 до 448 в 2026, и взвешивание
    по капитализации превратило бы волну в «BTC плюс шум».

    Актив без наблюдения в волну не входит — ни нулём, ни средним.
    """
    v = np.asarray(price_fwd, dtype=np.float64)
    m = np.isfinite(v)
    return float(v[m].mean()) if m.any() else np.nan


def beta(book, market):
    """МНК-наклон доходности книги на доходность волны.

    Возвращает `(β, R², n)`; `None`, если наблюдений мало либо волна
    не двигалась вовсе.
    """
    y = np.asarray(book, dtype=np.float64)
    x = np.asarray(market, dtype=np.float64)
    m = np.isfinite(y) & np.isfinite(x)
    n = int(m.sum())
    if n < 10:
        return None
    yy, xx = y[m], x[m]
    dx, dy = xx - xx.mean(), yy - yy.mean()
    sxx, syy = float(dx @ dx), float(dy @ dy)
    if sxx <= 0:
        return None
    b = float(dx @ dy) / sxx
    resid = dy - b * dx
    r2 = 1.0 - float(resid @ resid) / syy if syy > 0 else 0.0
    return b, r2, n


def rolling_beta(book, market, window):
    """β на скользящих окнах: одно число скрывает смену режима.

    Книга может иметь β около нуля в среднем и заметную β в каждом
    отдельном году, если знак менялся. Критерий 10 §8.3 проверяется по
    медиане, но распределение обязано быть видно.
    """
    out = []
    for i in range(0, len(book) - window + 1):
        r = beta(book[i:i + window], market[i:i + window])
        if r is not None:
            out.append(r[0])
    return out


def near_delisting(names, weights, last_day, at, days=30):
    """Доля гросса книги в активах, снимаемых с торгов в ближайшие `days`.

    Ловушка §5.3: у инструмента перед делистингом базис разъезжается и
    ставка становится экстремальной, то есть в дециль он попадает почти
    наверняка, а выйти придётся по цене расчёта.

    Исключать такие активы из универсума нельзя — это был бы отбор «по
    сегодняшнему списку», запрещённый проектом. Их можно только
    измерить.
    """
    from datetime import date as _d
    t = _d.fromisoformat(at)
    share, hit = 0.0, []
    for i, a in enumerate(names):
        if weights[i] == 0:
            continue
        ld = last_day.get(a)
        if not ld:
            continue
        gap = (_d.fromisoformat(ld) - t).days
        if 0 <= gap <= days:
            share += abs(float(weights[i]))
            hit.append(a)
    return share, hit


def regime_change(counts_form, counts_hold, days_form, days_hold,
                  tolerance=0.25):
    """Доля веса, у которой частота начислений сменилась между окнами.

    Ловушка §5.6: Bybit переводит инструмент на часовые начисления в
    периоды высокого базиса и возвращает обратно. Ставка, оценённая на
    четырёхчасовом режиме и полученная на часовом, стоит вчетверо
    дороже. Оценка §3.2 считает суточную величину именно поэтому, но
    проверка обязана быть явной.

    Сравниваются начисления **в сутки**, а не их число: окна разной
    длины дают разное число начислений при неизменном режиме.
    """
    out = []
    for cf, ch in zip(counts_form, counts_hold):
        if cf is None or ch is None or days_form <= 0 or days_hold <= 0:
            out.append(False)
            continue
        a, b = cf / days_form, ch / days_hold
        if a <= 0:
            out.append(b > 0)
            continue
        out.append(abs(b - a) / a > tolerance)
    return np.asarray(out, dtype=bool)


def weighted_share(weights, flags):
    """Доля гросса книги, приходящаяся на помеченные активы."""
    w = np.abs(np.asarray(weights, dtype=np.float64))
    tot = float(w.sum())
    if tot <= 0:
        return None
    return float(w[np.asarray(flags, dtype=bool)].sum()) / tot


def leg_stat(names, weights, values, side):
    """Медиана величины по одной ноге книги. `side`: +1 лонг, −1 шорт."""
    w = np.asarray(weights, dtype=np.float64)
    m = (w > 0) if side > 0 else (w < 0)
    v = np.asarray([values.get(a, np.nan) for a in names], dtype=np.float64)
    v = v[m & np.isfinite(v)]
    return float(np.median(v)) if len(v) else None


def capacity(weights, turnover, names, capital, max_share=0.05):
    """Капитал, при котором нога упирается в оборот актива.

    Позиция размером `capital · |w|` относится к суточному обороту
    актива. Возвращает медианную и худшую долю оборота, а также
    предельный капитал, при котором худшая позиция ещё укладывается в
    `max_share` оборота.

    Порогом при капитале фаз C–D это не является (§5.5 спеки), но число
    нужно знать заранее: в фазе E оно станет ограничением.
    """
    w = np.abs(np.asarray(weights, dtype=np.float64))
    shares = []
    for i, a in enumerate(names):
        if w[i] <= 0:
            continue
        t = turnover.get(a)
        if not t or t <= 0:
            continue
        shares.append(capital * w[i] / t)
    if not shares:
        return None
    shares = np.asarray(shares)
    worst = float(shares.max())
    return {"median_share": float(np.median(shares)),
            "worst_share": worst,
            "capital_limit": float(capital * max_share / worst)
            if worst > 0 else None,
            "names": len(shares)}
