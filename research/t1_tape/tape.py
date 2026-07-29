#!/usr/bin/env python3
"""
T1 — лента принтов площадки исполнения: загрузка, кластеры, поглощение.

Первое направление проекта, работающее не с барами, а с потоком. Пять
закрытых гипотез очертили, где эджа нет — в медленной статистической
торговле по барам; последний зонд намерил, что живой эдж сидит в первых
секундах после движения. Бар этого не видит, лента видит.

Что даёт лента Bybit
--------------------

Колонки: `timestamp, symbol, side, size, price, tickDirection,
trdMatchID, grossValue, homeNotional, foreignNotional`. Метка — epoch с
четырьмя знаками, то есть разрешение 0.1 мс.

**Сторона — агрессора, и это проверено данными, а не взято из
документации.** Из принтов `Buy`, сдвинувших цену, 96 % сдвинули её
вверх, а `Buy` с падающим тиком почти не встречается (0.4 %). Значит
`Buy` = покупатель ударил по предложению. Если бы `side` означала
мейкера, знак дельты пришлось бы переворачивать — и мы бы этого не
заметили, потому что все производные величины поменяли бы знак
согласованно. Проверка вынесена в тесты и гоняется на живом файле.

Что считается
-------------

**Кластер** (footprint) — объём по каждой цене, отдельно по сторонам.
**Дельта** — агрессивные покупки минус продажи, в котируемой валюте.
**Поглощение** — много агрессивного объёма в одну сторону, а цена не
идёт: значит с другой стороны стоит крупный лимитник и набирает. Это и
есть то, что читают глазами; здесь оно превращается в число.

Объёмы: ARBUSDT — 8.6 МБ и 212 тыс. принтов в сутки, SOLUSDT — 58 МБ и
1.6 млн. Срез «три символа на месяц» порядка 2 ГБ, то есть работать
можно сразу, не дожидаясь большой выгрузки.

Только стандартная библиотека и numpy.
"""

import gzip
import io
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")

sys.path.insert(0, RESEARCH)
from common.venue import fetch_binary                       # noqa: E402

ARCHIVE = "https://public.bybit.com/trading/"
UA = "t1-tape/1.0"

# Колонки ленты Bybit. Ищутся по имени: разбор по номеру уже однажды
# стоил проекту тихого нуля в загрузчике funding.
COL_TIME = "timestamp"
COL_SIDE = "side"
COL_SIZE = "size"
COL_PRICE = "price"
COL_TICK = "tickDirection"


def day_url(symbol, day):
    return f"{ARCHIVE}{symbol}/{symbol}{day}.csv.gz"


def days_between(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += timedelta(days=1)
    return out


def load_day(symbol, day, cache=True):
    """Лента за сутки: `(время, знак, размер, цена)`.

    Знак: `+1` — агрессивная покупка, `−1` — агрессивная продажа. Размер
    в базовом активе, цена в котируемом; произведение даёт нотионал.
    Возвращает `None`, если файла нет.
    """
    try:
        raw = fetch_binary(day_url(symbol, day), CACHE,
                           cache_key=f"{symbol}_{day}", user_agent=UA,
                           cache=cache)
    except FileNotFoundError:
        return None
    except Exception:                                     # noqa: BLE001
        return None
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
        head = f.readline().strip().split(",")
        cols = [c.strip().lower() for c in head]
        try:
            it = cols.index(COL_TIME)
            isd = cols.index(COL_SIDE)
            isz = cols.index(COL_SIZE)
            ip = cols.index(COL_PRICE)
        except ValueError as e:
            raise ValueError(f"{symbol} {day}: нет колонки {e}; "
                             f"заголовок {head}") from None
        need = max(it, isd, isz, ip)
        ts, sg, sz, px = [], [], [], []
        for line in f:
            p = line.rstrip("\n").split(",")
            if len(p) <= need:
                continue
            try:
                ts.append(float(p[it]))
                sz.append(float(p[isz]))
                px.append(float(p[ip]))
            except ValueError:
                continue
            sg.append(1 if p[isd] == "Buy" else -1)
    if not ts:
        return None
    return (np.asarray(ts, dtype=np.float64),
            np.asarray(sg, dtype=np.int8),
            np.asarray(sz, dtype=np.float64),
            np.asarray(px, dtype=np.float64))


def to_grid(tape, step_sec, t0=None, t1=None):
    """Лента на регулярную сетку шагом `step_sec`.

    Возвращает словарь массивов по ячейкам сетки:

    - `t` — начало ячейки, секунды эпохи;
    - `buy_qv`, `sell_qv` — агрессивный нотионал по сторонам;
    - `delta` — `buy_qv − sell_qv`;
    - `prints` — число сделок;
    - `open`, `close`, `high`, `low` — цены по ячейке;
    - `vwap` — средняя по объёму.

    Пустая ячейка — не ноль, а отсутствие наблюдения: цены в ней `NaN`,
    объёмы нули. Урок A2: бар без сделок это пропуск, а не наблюдение с
    нулевой доходностью.
    """
    ts, sg, sz, px = tape
    t0 = float(np.floor((t0 if t0 is not None else ts[0]) / step_sec)
               * step_sec)
    t1 = float(np.ceil((t1 if t1 is not None else ts[-1]) / step_sec)
               * step_sec)
    n = int(round((t1 - t0) / step_sec))
    if n <= 0:
        n = 1
    idx = np.clip(((ts - t0) // step_sec).astype(np.int64), 0, n - 1)
    qv = sz * px

    buy_qv = np.zeros(n)
    sell_qv = np.zeros(n)
    np.add.at(buy_qv, idx[sg > 0], qv[sg > 0])
    np.add.at(sell_qv, idx[sg < 0], qv[sg < 0])
    prints = np.bincount(idx, minlength=n).astype(np.int64)
    sum_qv = np.zeros(n)
    np.add.at(sum_qv, idx, qv)
    sum_pq = np.zeros(n)
    np.add.at(sum_pq, idx, px * qv)

    op = np.full(n, np.nan)
    cl = np.full(n, np.nan)
    # Накопители максимума и минимума начинаются с бесконечностей, а не с
    # NaN: `np.maximum.at` по NaN даёт NaN, и вся колонка выходила пустой.
    hi = np.full(n, -np.inf)
    lo = np.full(n, np.inf)
    # Первый и последний принт ячейки: индексы уже упорядочены по времени.
    first = np.full(n, -1, dtype=np.int64)
    last = np.full(n, -1, dtype=np.int64)
    first[idx[::-1]] = np.arange(len(idx))[::-1]
    last[idx] = np.arange(len(idx))
    has = prints > 0
    op[has] = px[first[has]]
    cl[has] = px[last[has]]
    np.maximum.at(hi, idx, px)
    np.minimum.at(lo, idx, px)
    hi[~has] = np.nan
    lo[~has] = np.nan

    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.where(sum_qv > 0, sum_pq / np.maximum(sum_qv, 1e-12),
                        np.nan)
    return {"t": t0 + np.arange(n) * step_sec,
            "buy_qv": buy_qv, "sell_qv": sell_qv,
            "delta": buy_qv - sell_qv, "prints": prints,
            "open": op, "close": cl, "high": hi, "low": lo,
            "vwap": vwap, "step_sec": step_sec}


def footprint(tape, t_from, t_to, tick):
    """Кластер: объём по ценовым уровням и сторонам за окно.

    `tick` — шаг цены, по которому уровни группируются. Возвращает
    `(уровни, покупки, продажи)`, уровни по возрастанию цены.
    """
    ts, sg, sz, px = tape
    a = int(np.searchsorted(ts, t_from, "left"))
    b = int(np.searchsorted(ts, t_to, "left"))
    if b <= a:
        return np.empty(0), np.empty(0), np.empty(0)
    lvl = np.round(px[a:b] / tick).astype(np.int64)
    qv = (sz[a:b] * px[a:b])
    side = sg[a:b]
    uniq, inv = np.unique(lvl, return_inverse=True)
    buy = np.zeros(len(uniq))
    sell = np.zeros(len(uniq))
    np.add.at(buy, inv[side > 0], qv[side > 0])
    np.add.at(sell, inv[side < 0], qv[side < 0])
    return uniq * tick, buy, sell


def rolling_sum(v, w):
    """Сумма по `w` ячейкам, выровненная по правому краю окна."""
    if w <= 1:
        return v.astype(np.float64)
    c = np.concatenate([[0.0], np.cumsum(v, dtype=np.float64)])
    out = np.full(len(v), np.nan)
    out[w - 1:] = c[w:] - c[:-w]
    return out


def absorption(grid, window_sec, vol_mult, max_move, side):
    """Моменты поглощения: много агрессии в одну сторону, цена не идёт.

    `side = -1` — поглощение **продаж**: льют в стакан, а цена стоит,
    значит кто-то откупает, и ожидание — рост. `side = +1` зеркально.

    `vol_mult` — во сколько раз агрессивный объём окна должен превышать
    обычный для этого символа (медиана по всем окнам суток). Порог в
    разах, а не в долларах: у ARBUSDT и SOLUSDT обычные объёмы
    различаются в шесть раз, и абсолютный порог сравнивал бы разное.

    `max_move` — насколько цене позволено уйти против поглощающего.
    Именно это и делает событие поглощением, а не обычным проливом.
    """
    step = grid["step_sec"]
    w = max(1, int(round(window_sec / step)))
    press = grid["sell_qv"] if side < 0 else grid["buy_qv"]
    vol = rolling_sum(press, w)
    med = np.nanmedian(vol[np.isfinite(vol) & (vol > 0)]) if np.any(
        np.isfinite(vol) & (vol > 0)) else np.nan
    if not np.isfinite(med) or med <= 0:
        return np.empty(0, dtype=np.int64), {}

    # Цена на краях окна: конец окна против его начала.
    cl = grid["close"]
    start = np.full(len(cl), np.nan)
    start[w - 1:] = cl[:len(cl) - w + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        move = cl / start - 1.0

    # Поглощение продаж: цена НЕ упала ниже допуска (side<0 -> move >= -max_move)
    held = move >= -max_move if side < 0 else move <= max_move
    hit = np.isfinite(vol) & np.isfinite(move) & held & (vol >= vol_mult * med)
    idx = np.flatnonzero(hit)
    if len(idx) == 0:
        return idx, {"median_window_qv": float(med)}
    # Соседние ячейки одного события — одно событие.
    gap = w
    keep, last = [], -10**9
    for i in idx:
        if i - last >= gap:
            keep.append(i)
            last = i
    return np.array(keep, dtype=np.int64), {
        "median_window_qv": float(med),
        "windows": int(np.isfinite(vol).sum()),
        "raw_hits": int(len(idx)),
    }


def stamp(sec):
    return datetime.fromtimestamp(float(sec), timezone.utc).isoformat()
