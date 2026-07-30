#!/usr/bin/env python3
"""
Уровни из структуры: полки объёма, экстремумы суток, круглые числа.

Почему это отдельный модуль
---------------------------

В T3 уровень выдумывала сама лента: полоса определялась как десятая
часть хода минутного окна. Замер это убил — медианный стоп вышел **7
базисных пунктов при круге издержек 11**, то есть «уровень» оказался
тоньше комиссии и сидел внутри обычного шума минутной свечи. Половина
событий отсеивалась даже не по этому, а как «стоп неисполним».
Владелец подтвердил это, посмотрев на график.

Ошибка была не в порогах, а в постановке: **лента не создаёт уровень,
она говорит, защищают ли уровень, который существует сам по себе.**
Здесь уровни строятся из структуры на масштабе суток, а лента остаётся
источником момента.

Три источника, и каждый — то, на что смотрит трейдер
----------------------------------------------------

**Полки объёма** — цены, где за сутки прошло заметно больше оборота,
чем вокруг. Там стояли заявки, там их помнят.

**Экстремумы прошедших суток** — максимум и минимум предыдущего дня.

**Круглые числа** — шаг выбирается от масштаба цены, а не назначается:
десятая часть ближайшей степени десятки. Для цены 0.34 это 0.01, для
85 000 — 1000, и в обоих случаях уровни отстоят примерно на процент.

Толщина уровня измеряется, а не выбирается
------------------------------------------

Стоп обязан стоять **за пределами обычного шума**, иначе его выбьет
независимо от того, верно ли прочитано событие. Мерой шума служит
медианный ход минутной свечи за то же окно наблюдения: стоп ставится за
уровень на одну такую величину. Это и есть исправление главного дефекта
T3, выраженное числом, а не намерением.

Только стандартная библиотека и numpy.
"""

import numpy as np

LOOKBACK_MIN = 24 * 60            # окно, из которого строятся уровни
MIN_HISTORY_MIN = 6 * 60          # меньше — уровней не строим
# Шум меряется по НЕДАВНЕМУ окну, а не по суткам. Волатильность внутри
# суток не постоянна: у ARBUSDT 4 марта медианный ход минутной свечи за
# сутки 21 б.п., а в час разгона 44 при размахе часа 455. Стоп,
# посчитанный по суточной медиане, оказывался ВНУТРИ одной свечи того
# часа — владелец увидел это на графике раньше, чем я в числах. Тот же
# класс ошибки, что константа вместо частоты начисления funding: величина
# переменная, а зафиксирована средним.
RECENT_MIN = 30
MIN_RECENT_MIN = 10               # меньше — берём медленную оценку
SHELF_Q = 0.85                    # полка: полоса выше этого квантиля
ROUND_SPAN = 3.0                  # круглые числа в пределах стольких шумов


def minute_series(g):
    """Секундная сетка суток -> минутные `(t, high, low, vwap, объём)`.

    Минута без сделок отсутствует: бар без сделок — пропуск, а не
    наблюдение с нулевым объёмом (урок A2).
    """
    n = 1440
    cut = 1440 * 60
    hi = g["high"][:cut].reshape(n, 60)
    lo = g["low"][:cut].reshape(n, 60)
    qv = (g["buy_qv"][:cut] + g["sell_qv"][:cut]).reshape(n, 60)
    vw = g["vwap"][:cut].reshape(n, 60)
    has = np.isfinite(hi)
    keep = has.any(axis=1)
    with np.errstate(invalid="ignore"):
        H = np.nanmax(np.where(has, hi, np.nan), axis=1)[keep]
        L = np.nanmin(np.where(has, lo, np.nan), axis=1)[keep]
        V = qv.sum(axis=1)[keep]
        num = np.nansum(np.where(has, vw * qv, 0.0), axis=1)[keep]
    P = np.where(V > 0, num / np.maximum(V, 1e-12), (H + L) / 2)
    t = (g["t"][:cut].reshape(n, 60)[:, 0])[keep]
    return t, H, L, P, V


def noise_px(H, L, P):
    """Обычный ход минутной свечи в ценах — мера шума.

    Медиана `high − low` по окну. Стоп короче этой величины сидит внутри
    шума и будет выбит независимо от верности сигнала — ровно это и
    случилось в T3.
    """
    r = H - L
    r = r[np.isfinite(r) & (r > 0)]
    if len(r) == 0:
        return float("nan")
    return float(np.median(r))


def shelves(P, V, noise, q=SHELF_Q):
    """Полки объёма: цены, где оборот заметно выше окрестного.

    Ширина полосы профиля равна шуму: делить тоньше бессмысленно —
    внутри одной минутной свечи цена и так побывает во всех таких
    полосах.
    """
    ok = np.isfinite(P) & (V > 0)
    if not ok.any() or not np.isfinite(noise) or noise <= 0:
        return np.empty(0)
    p, v = P[ok], V[ok]
    lo = float(p.min())
    k = ((p - lo) / noise).astype(np.int64)
    nb = int(k.max()) + 1
    if nb < 5:
        return np.empty(0)
    vol = np.bincount(k, weights=v, minlength=nb)
    thr = np.quantile(vol[vol > 0], q)
    peak = np.zeros(nb, dtype=bool)
    peak[1:-1] = (vol[1:-1] >= vol[:-2]) & (vol[1:-1] >= vol[2:])
    idx = np.flatnonzero(peak & (vol >= thr))
    return lo + (idx + 0.5) * noise


def round_levels(price, noise, span=ROUND_SPAN):
    """Круглые числа вокруг цены; шаг — от масштаба самой цены.

    Шаг не назначается: берётся десятая часть ближайшей степени десятки,
    поэтому 0.34 даёт шаг 0.01, а 85 000 — 1000, и уровни в обоих
    случаях отстоят примерно на процент.
    """
    if not np.isfinite(price) or price <= 0:
        return np.empty(0)
    step = 10.0 ** (np.floor(np.log10(price)) - 1)
    lo = (np.floor(price / step) - 2) * step
    out = lo + step * np.arange(5)
    return out[np.abs(out - price) <= span * max(noise, step * 1e-6)]


def build(t, H, L, P, V, now_i, prev_day_hl=None, recent_min=RECENT_MIN,
          min_history=MIN_HISTORY_MIN):
    """Уровни на момент `now_i`: полки, экстремумы суток, круглые числа.

    Возвращает `(цены уровней, вид уровня, шум текущий, шум суточный)`.

    **Уровни берутся из суток, а геометрия — из текущего режима.**
    Структура медленная: полка объёма, где торговали вчера, никуда не
    делась. А ширина полос профиля, стоп и зазор до цели обязаны
    следовать тому, как рынок движется СЕЙЧАС, иначе в разгон сделка
    целиком помещается внутрь одной свечи.

    Вид уровня нужен диагностике: если работает только один источник,
    это надо видеть, а не усреднять.

    `min_history` — сколько минут требуется, чтобы вообще строить уровни.
    Для суточного профиля разумны шесть часов, но на живом потоке их нет
    первые полдня, и с ними страница наблюдения показывала бы пустоту.
    """
    a = max(0, now_i - LOOKBACK_MIN)
    if now_i - a < min_history:
        return np.empty(0), [], float("nan"), float("nan")
    hh, ll, pp, vv = H[a:now_i], L[a:now_i], P[a:now_i], V[a:now_i]
    slow = noise_px(hh, ll, pp)
    r0 = max(a, now_i - recent_min)
    noise = (noise_px(H[r0:now_i], L[r0:now_i], P[r0:now_i])
             if now_i - r0 >= MIN_RECENT_MIN else slow)
    if not np.isfinite(noise) or noise <= 0:
        noise = slow
    if not np.isfinite(noise) or noise <= 0:
        return np.empty(0), [], float("nan"), float("nan")
    px, kind = [], []
    for v in shelves(pp, vv, noise):
        px.append(float(v))
        kind.append("полка")
    if prev_day_hl:
        for v, k in ((prev_day_hl[0], "максимум суток"),
                     (prev_day_hl[1], "минимум суток")):
            if np.isfinite(v):
                px.append(float(v))
                kind.append(k)
    last = pp[-1] if len(pp) else np.nan
    for v in round_levels(last, noise):
        px.append(float(v))
        kind.append("круглое")
    if not px:
        return np.empty(0), [], noise, slow
    order = np.argsort(px)
    return (np.asarray(px)[order], [kind[i] for i in order], noise, slow)


def nearest(levels, kinds, price, tol):
    """Ближайший уровень к цене, если он в пределах `tol`."""
    if len(levels) == 0:
        return None
    i = int(np.argmin(np.abs(levels - price)))
    if abs(levels[i] - price) > tol:
        return None
    return float(levels[i]), kinds[i]


def ahead(levels, price, long, min_gap):
    """Ближайший уровень впереди — цель. Слишком близкие пропускаются."""
    if len(levels) == 0:
        return None
    f = levels[levels > price + min_gap] if long \
        else levels[levels < price - min_gap]
    if len(f) == 0:
        return None
    return float(f.min() if long else f.max())
