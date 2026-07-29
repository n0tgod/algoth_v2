#!/usr/bin/env python3
"""
L3 — отбор событий, эпизоды, нули и контроли. Чистые функции.

Спека 06, §5, §7.5, §8. Всё считается по индексам общей сетки: момент
`j` есть момент, в который решение принимается и по которому уже
известны обе величины (см. `data.py`).

Что здесь главное
-----------------

Не отбор событий — он прост, — а **два контроля**, каждый из которых
способен закрыть гипотезу сам по себе:

- **контроль 1, одновременная кросс-секция.** Отскакивает ли каскадный
  актив сильнее тех, кто в ту же минуту не каскадил. Если нет, мы
  открыли, что рынок отскакивает после падения;
- **контроль 2, события без условия на интерес.** Если превышение то же
  самое, механизм принудительного закрытия — украшение, а гипотеза
  сводится к «покупай падение». Прямой аналог перемешанных меток A4,
  убивших первую гипотезу проекта.

Нули проверяют другое и слабее: что мера не смещена (нуль 1) и что
эффект принадлежит событию, а не активу (нуль 2).
"""

import numpy as np

STEP_MIN = 5
WINDOW_MIN = 15                   # окно, за которое меряется падение
DEDUP_MIN = 60                    # серия баров одного обвала — одно событие
EPISODE_SEC = 4 * 3600            # слипание событий разных активов
CROSS_GUARD_MIN = 60              # каскадящие соседи вне кросс-секции
SHIFT_DAYS = 365                  # нуль 2


def steps(minutes):
    return int(minutes // STEP_MIN)


def detect(oi_c, price, ok, oi_drop, move, require_oi=True):
    """Индексы моментов, где сработало условие §5.1.

    `ok` — маска допустимых моментов (ликвидность, делистинг, размер).
    `require_oi=False` даёт контроль 2: то же самое без условия на
    падение интереса. Наличие самой величины при этом сохраняется —
    иначе сравнивались бы разные множества моментов, и разница
    объяснялась бы составом, а не условием.
    """
    w = steps(WINDOW_MIN)
    n = len(price)
    if n <= w:
        return np.empty(0, dtype=np.int64)
    d_px = np.full(n, np.nan)
    d_oi = np.full(n, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        d_px[w:] = price[w:] / price[:-w] - 1.0
        d_oi[w:] = oi_c[w:] / oi_c[:-w] - 1.0
    hit = np.isfinite(d_px) & np.isfinite(d_oi) & ok & (d_px <= -move)
    if require_oi:
        hit &= d_oi <= -oi_drop
    idx = np.flatnonzero(hit)
    if len(idx) == 0:
        return idx
    # Серия соседних баров одного обвала — одно событие, а не десять.
    gap = steps(DEDUP_MIN)
    keep, last = [], -10**9
    for i in idx:
        if i - last >= gap:
            keep.append(i)
            last = i
    return np.array(keep, dtype=np.int64)


def forward(price, j, horizon_min):
    """Доходность от входа в `j` до выхода через `horizon_min` минут."""
    h = steps(horizon_min)
    k = j + h
    ok = (k < len(price))
    out = np.full(len(j), np.nan)
    kk = np.clip(k, 0, len(price) - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = price[kk] / price[j] - 1.0
    out[ok] = v[ok]
    return out


def episodes(times, gap_sec=EPISODE_SEC):
    """Номер эпизода для каждого события. События идут по времени.

    Каскады не независимы: обвал накрывает весь рынок, и сотня событий
    на сотне активов в один час — это одно наблюдение, а не сто. Бюджет
    доказательства этой гипотезы считается в эпизодах.
    """
    if len(times) == 0:
        return np.empty(0, dtype=np.int64)
    order = np.argsort(times, kind="stable")
    ep = np.empty(len(times), dtype=np.int64)
    cur, prev = 0, None
    for pos in order:
        t = times[pos]
        if prev is not None and t - prev > gap_sec:
            cur += 1
        ep[pos] = cur
        prev = t
    return ep


def by_episode(values, ep):
    """Медиана внутри эпизода, потом по эпизодам: одно окно — один голос."""
    out = []
    for e in np.unique(ep):
        v = values[(ep == e) & np.isfinite(values)]
        if len(v):
            out.append(float(np.median(v)))
    return np.array(out)


def cross_section(P, j_list, rows, horizon_min, guard_min=CROSS_GUARD_MIN):
    """Контроль 1: медианный форвард тех, кто в этот момент не каскадил.

    Из кросс-секции исключаются активы, у которых событие случилось
    рядом по времени: иначе «фон» частично состоит из тех же каскадов,
    и контроль сравнивал бы событие с самим собой.
    """
    h = steps(horizon_min)
    g = steps(guard_min)
    near = {}
    for r, j in zip(rows, j_list):
        for c in range(j - g, j + g + 1):
            near.setdefault(c, set()).add(r)
    out = np.full(len(j_list), np.nan)
    for k, j in enumerate(j_list):
        if j + h >= P.shape[1]:
            continue
        a, b = P[:, j], P[:, j + h]
        with np.errstate(invalid="ignore", divide="ignore"):
            r = b / a - 1.0
        drop = near.get(j)
        if drop:
            r = r.copy()
            r[list(drop)] = np.nan
        v = r[np.isfinite(r)]
        if len(v) >= 20:
            out[k] = float(np.median(v))
    return out


def null_matched_times(valid, j_list, hours, seed, guard_steps):
    """Нуль 1: случайные моменты того же актива и того же часа суток.

    Согласование по часу обязательно: каскады не равномерны по времени,
    и несогласованный нуль сравнивал бы разные режимы ликвидности.
    """
    rng = np.random.default_rng(seed)
    pool = np.flatnonzero(valid)
    if len(pool) == 0:
        return np.full(len(j_list), -1, dtype=np.int64)
    ph = hours[pool]
    out = np.full(len(j_list), -1, dtype=np.int64)
    for k, j in enumerate(j_list):
        cand = pool[(ph == hours[j]) & (np.abs(pool - j) > guard_steps)]
        if len(cand):
            out[k] = cand[rng.integers(len(cand))]
    return out


def null_shift(j_list, n, shift_days=SHIFT_DAYS):
    """Нуль 2: тот же актив, момент сдвинут на год.

    Отвечает на вопрос, не является ли эффект свойством актива, а не
    события.
    """
    d = shift_days * 24 * 60 // STEP_MIN
    out = np.where(j_list + d < n, j_list + d, j_list - d)
    out[out < 0] = -1
    return out
