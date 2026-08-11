#!/usr/bin/env python3
"""
D1 — общее ядро решения: событие, вход, форвард, одновременный фон.

Спека 11. Чистые функции над **секундной сеткой**; ни файлов, ни сети,
ни состояния.

Почему ядро одно
----------------

Гипотезу проверяют две половины, и они смотрят на одни и те же данные с
разных сторон: реплей идёт по записи сборщика и выносит вердикт, живой
сканер идёт по потоку и калибрует исполнение. Если у каждой будет своё
определение события, разойдутся они молча — и обе будут выглядеть
правдоподобно. Так уже умер движок v1 (копия ядра бэктеста разъехалась
с оригиналом), и так же чуть не разошлись нули F3 (`nulls.py` в двух
местах). Поэтому: **и реплей, и сканер зовут эти функции**, а не свои.

Секунда — единица, и это не мелочь
----------------------------------

Зонд возврата упёрся ровно в то, что минутная свеча не разрешает первые
шестьдесят секунд. Здесь единица — секунда, а все окна задаются **во
времени**, а не в номерах точек. Разница видна на дыре: сборщик снимает
книгу проходом по всем именам, проход бывает дольше секунды, и снимков у
символа в часе бывает меньше 3600. Пятнадцать точек назад через дыру —
это не пятнадцать минут. Тот же класс дефекта дважды ловился в проекте
(окно по номеру точки в L2; зашитый шаг в загрузчике цен), и оба раза
проверка «точка есть» его проходила.

Отсюда правила, которые ядро держит само:

- **нет цены — нет измерения, а не ноль.** Ни события, ни входа, ни
  форварда, ни фона: `nan` и отдельный счётчик;
- **опорная точка ищется по времени** с допуском, и берётся ближайшая —
  односторонний поиск назад систематически удлинял бы окно, то есть
  находил бы события чаще;
- **входа в секунду решения не существует.** Решение завершено концом
  секунды `T`, купить можно не раньше `T + 1`; задержка меньше секунды
  отвергается исключением, а не молча приравнивается к единице.

Что здесь НЕ живёт
------------------

Издержки, проскальзывание обходом лесенки, нули и вердикт — это D2 и D3.
Ядро отвечает только на «было ли событие, по какой цене мы бы вошли и
вышли, и что в тот же момент делали остальные».
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))

import events as E                                        # noqa: E402

# --- объявлено спекой 11 §4, после результата не меняется -------------
W_SEC = 15 * 60                   # окно обнаружения падения
DROPS = (0.03, 0.05)              # X — насколько упала середина
DELAYS = (1, 5, 15, 30, 60)       # δ — ось задержки входа, секунды
HORIZONS_SEC = (5 * 60, 15 * 60, 30 * 60)   # h — удержание
VERDICT_CELL = {"drop": 0.03, "delay_sec": 5, "horizon_sec": 30 * 60}
MIN_CROSS = 50                    # пол ширины фона, §5
EPISODE_SEC = 5 * 60              # слипание событий в эпизоды, §7 п.5

# --- служебные допуски: свойства записи, а не гипотезы ----------------
REF_TOL_SEC = 5                   # допуск на поиск опорной точки
FILL_WAIT_SEC = 5                 # дальше цена считается несвежей
DEDUP_SEC = W_SEC                 # два события не делят окно измерения
MIN_DELAY_SEC = 1                 # «мгновенного входа» не существует


def place(times, mids, t0, n):
    """Сырой ряд `(время, середина)` на секундную сетку длиной `n`.

    Ячейка `j` — секунда `t0 + j`, значение — **последняя** цена этой
    секунды: решение принимается концом секунды, и знать мы можем ровно
    её. Секунда без наблюдений остаётся `nan` — пропуском, а не нулём и
    не перенесённой ценой (урок замороженных рядов A2).

    Последнее наблюдение выбирается **по времени**, а не по порядку
    строк во входе: файлы часа читаются по кускам, живая очередь может
    прийти чем угодно, и «последняя строка» — не то же самое, что
    «поздняя цена». Полагаться на то, в каком порядке numpy разрешает
    повторяющиеся индексы при присваивании, тоже нельзя.
    """
    row = np.full(int(n), np.nan)
    t = np.asarray(times, dtype=np.float64)
    m = np.asarray(mids, dtype=np.float64)
    if len(t) == 0:
        return row
    j = np.floor(t - float(t0)).astype(np.int64)
    keep = (j >= 0) & (j < int(n)) & np.isfinite(m)
    j, m, t = j[keep], m[keep], t[keep]
    if len(j) == 0:
        return row
    order = np.argsort(t, kind="stable")
    j, m = j[order], m[order]
    last = np.ones(len(j), dtype=bool)
    last[:-1] = j[1:] != j[:-1]
    row[j[last]] = m[last]
    return row


def fill_index(row):
    """Индексы ближайшего наблюдения слева и справа от каждой секунды.

    `prev[j] = -1` и `nxt[j] = n` означают «с этой стороны наблюдений
    нет». Строится за один проход и переиспользуется всеми задержками и
    горизонтами: иначе каждый поиск был бы прогулкой по ряду.
    """
    row = np.asarray(row, dtype=np.float64)
    n = len(row)
    fin = np.isfinite(row)
    idx = np.arange(n, dtype=np.int64)
    prev = np.maximum.accumulate(np.where(fin, idx, -1))
    nxt = np.minimum.accumulate(np.where(fin, idx, n)[::-1])[::-1]
    return prev, nxt


def nearest(prev, nxt, k, tol=REF_TOL_SEC):
    """Ближайшее к секунде `k` наблюдение в пределах `±tol`, иначе −1.

    Ближайшее, а не «последнее до»: односторонний поиск назад делает
    измеряемое окно длиннее объявленного, то есть находит падения чаще —
    смещение в пользу гипотезы, которого в результате не видно. При
    равном расстоянии берётся более раннее, чтобы правило было
    однозначным.
    """
    n = len(prev)
    k = np.asarray(k, dtype=np.int64)
    kk = np.clip(k, 0, n - 1)
    p, q = prev[kk], nxt[kk]
    big = np.int64(1 << 40)
    dp = np.where(p >= 0, np.abs(k - p), big)
    dq = np.where(q < n, np.abs(q - k), big)
    out = np.where(dp <= dq, p, q)
    bad = (np.minimum(dp, dq) > tol) | (k < 0) | (k >= n)
    return np.where(bad, -1, out).astype(np.int64)


def falls(row, prev=None, nxt=None, window_sec=W_SEC, tol=REF_TOL_SEC):
    """Падение середины за `window_sec` к каждой секунде ряда.

    `nan` там, где цены нет сейчас или нет опорной точки: **отсутствие
    измерения не есть отсутствие падения**. Смешав их, мы получили бы
    ряд, в котором дыра выглядит спокойным рынком.
    """
    row = np.asarray(row, dtype=np.float64)
    if prev is None or nxt is None:
        prev, nxt = fill_index(row)
    n = len(row)
    ref = nearest(prev, nxt, np.arange(n, dtype=np.int64) - int(window_sec),
                  tol)
    out = np.full(n, np.nan)
    ok = (ref >= 0) & np.isfinite(row)
    if ok.any():
        out[ok] = row[ok] / row[ref[ok]] - 1.0
    return out


def detect(row, drop, prev=None, nxt=None, window_sec=W_SEC,
           dedup_sec=DEDUP_SEC, tol=REF_TOL_SEC, ok=None):
    """Секунды, в которые условие §4 впервые выполнено.

    Падение на `drop` за пятнадцать минут остаётся верным ещё много
    секунд подряд — это одно событие, а не девятьсот. Пропуск равен
    самому окну измерения: два события, отстоящие дальше, меряют
    непересекающиеся куски цены.
    """
    f = falls(row, prev, nxt, window_sec, tol)
    hit = np.isfinite(f) & (f <= -float(drop))
    if ok is not None:
        hit &= np.asarray(ok, dtype=bool)
    idx = np.flatnonzero(hit)
    if len(idx) == 0:
        return idx.astype(np.int64)
    keep, last = [], -(1 << 40)
    for j in idx:
        if j - last >= int(dedup_sec):
            keep.append(int(j))
            last = j
    return np.array(keep, dtype=np.int64)


def first_at_or_after(nxt, k, wait=FILL_WAIT_SEC):
    """Первая доступная цена начиная с секунды `k`, иначе −1.

    «Первая доступная», а не «последняя известная»: закрытие бара,
    кончившегося в момент решения, — цена ДО решения, купить по ней уже
    нельзя (правка `next_open` в зонде каскадов). Ожидание ограничено:
    цена, найденная через минуту после намеченного момента, описывает
    другую сделку, и подставить её значило бы выдумать исполнение.
    """
    n = len(nxt)
    k = np.asarray(k, dtype=np.int64)
    kk = np.clip(k, 0, n - 1)
    q = nxt[kk]
    bad = (k < 0) | (k >= n) | (q >= n) | ((q - k) > int(wait))
    return np.where(bad, -1, q).astype(np.int64)


def trade(row, nxt, j, delay_sec, horizon_sec, wait=FILL_WAIT_SEC):
    """Сделка от решения в секунду `j`: вход, выход, доходность.

    Горизонт отсчитывается от **фактического входа**, а не от решения:
    если заполнение задержалось, удержание не должно от этого
    укорачиваться — иначе задержка входа молча меняла бы и вторую
    сторону сделки.

    Возвращает `(доходность, i_вход, i_выход)`; ненаступившее —
    `(nan, -1, -1)`.
    """
    if int(delay_sec) < MIN_DELAY_SEC:
        raise ValueError(
            f"задержка входа {delay_sec} с: решение завершено концом "
            f"секунды T, вход возможен не раньше T+{MIN_DELAY_SEC}. "
            "«Мгновенного входа» не существует — спека 11 §4")
    row = np.asarray(row, dtype=np.float64)
    i_in = int(first_at_or_after(nxt, np.int64(int(j) + int(delay_sec)),
                                 wait))
    if i_in < 0:
        return float("nan"), -1, -1
    i_out = int(first_at_or_after(nxt, np.int64(i_in + int(horizon_sec)),
                                  wait))
    if i_out < 0:
        return float("nan"), i_in, -1
    return float(row[i_out] / row[i_in] - 1.0), i_in, i_out


def returns_matrix(P, NXT, j, delay_sec, horizon_sec, wait=FILL_WAIT_SEC):
    """Та же сделка от секунды `j`, но по ВСЕМ строкам матрицы разом.

    Ею считается и своя нога, и фон: правило исполнения у события и у
    кросс-секции обязано быть одним, иначе в разность войдёт правило, а
    не рынок. Здесь это гарантировано не договорённостью, а тем, что
    считает их одна функция.
    """
    if int(delay_sec) < MIN_DELAY_SEC:
        raise ValueError("задержка входа меньше секунды — см. `trade`")
    P = np.asarray(P, dtype=np.float64)
    R, n = P.shape
    rows = np.arange(R, dtype=np.int64)
    out = np.full(R, np.nan)
    k = int(j) + int(delay_sec)
    if k < 0 or k >= n:
        return out
    e = NXT[:, k]
    good = (e < n) & ((e - k) <= int(wait))
    if not good.any():
        return out
    ko = np.clip(e + int(horizon_sec), 0, n - 1)
    o = NXT[rows, ko]
    good &= (o < n) & ((o - (e + int(horizon_sec))) <= int(wait)) \
        & (e + int(horizon_sec) < n)
    if not good.any():
        return out
    g = np.flatnonzero(good)
    out[g] = P[g, o[g]] / P[g, e[g]] - 1.0
    return out


def guard_sec(delay_sec, horizon_sec, window_sec=W_SEC):
    """Ширина защитного окна фона: `max(окно обнаружения, δ + h)`.

    Загрязняет фон ровно тот сосед, чьё собственное движение накрывает
    наш замер, а не сосед часом раньше. Плоское широкое окно на частом
    сигнале запрещает почти всё сечение — в T1 оно оставляло контроль у
    0.1 % событий, и величины при этом печатались как результат.
    """
    return int(max(int(window_sec), int(delay_sec) + int(horizon_sec)))


GUARD_CHUNK = 128                 # строк за раз при построении запретов


def guard_matrix(shape, rows, j_list, guard, chunk=GUARD_CHUNK):
    """Кто в какой момент не годится в фон. Обёртка над L3.

    Считает `E.ban_matrix` — она работает в единицах сетки, и у нас эта
    единица секунда. Второй реализации не полагается: в проекте уже был
    случай, когда одинаково названные нули считались разным кодом.

    Строки идут пачками. На сутках это 518 × 93 600, и разностный массив
    внутри L3 берёт вчетверо больше готового результата — почти 400 МБ
    разом. Строки независимы, поэтому пачка даёт **тот же результат**
    (закреплено тестом), а пик памяти падает вчетверо. Считать это
    оптимизацией «на всякий случай» нельзя: реплей работает рядом со
    сбором, и память, отобранная у сборщика, стоит суток записи, которую
    неоткуда докачать.
    """
    rows = np.asarray(rows, dtype=np.int64)
    j_list = np.asarray(j_list, dtype=np.int64)
    out = np.zeros(shape, dtype=bool)
    for lo in range(0, shape[0], int(chunk)):
        hi = min(lo + int(chunk), shape[0])
        m = (rows >= lo) & (rows < hi)
        out[lo:hi] = E.ban_matrix((hi - lo, shape[1]), rows[m] - lo,
                                  j_list[m], guard_min=int(guard),
                                  step_min=1)
    return out


def excess(P, NXT, row, j, delay_sec, horizon_sec, banned,
           min_cross=MIN_CROSS, wait=FILL_WAIT_SEC):
    """Контроль 1: своя доходность против одновременной кросс-секции.

    Главная величина всей спеки. Возвращает
    `(своя, фон, превышение, ширина фона)`.

    Фон тоньше пола — **не измеряется, а не ноль**: в зонде возврата
    ячейка порога 2 % была пуста не из-за отсутствия эффекта, а потому
    что падали почти все и сравнивать становилось не с чем. Ширина
    возвращается всегда, даже когда измерения нет: только по ней видно,
    отчего ячейка молчит.
    """
    r = returns_matrix(P, NXT, j, delay_sec, horizon_sec, wait)
    own = float(r[int(row)])
    bg = np.array(r, copy=True)
    bg[int(row)] = np.nan                 # своя нога в фон не входит
    if banned is not None:
        bg[np.asarray(banned, dtype=bool)] = np.nan
    v = bg[np.isfinite(bg)]
    width = int(len(v))
    if width < int(min_cross):
        return own, float("nan"), float("nan"), width
    med = float(np.median(v))
    exc = own - med if np.isfinite(own) else float("nan")
    return own, med, exc, width


def episodes(times, gap_sec=EPISODE_SEC):
    """Номер эпизода: события всех имён, слипшиеся окном `gap_sec`.

    Обвал накрывает рынок целиком, и сотня событий в одну минуту — это
    одно наблюдение. Бюджет доказательства считается в эпизодах (§7 п.5).
    Считает та же функция L3.
    """
    return E.episodes(np.asarray(times, dtype=np.float64), gap_sec=gap_sec)


def by_episode(values, ep):
    """Медиана внутри эпизода: одно рыночное окно — один голос.

    Та же функция L3. Без неё месяц из сорока тысяч событий считался бы
    сорока тысячами наблюдений, а это один рынок, а не сорок тысяч.
    """
    return E.by_episode(np.asarray(values, dtype=np.float64),
                        np.asarray(ep, dtype=np.int64))


def live_fall(times, mids, t_now, window_sec=W_SEC, tol=REF_TOL_SEC):
    """Падение к моменту `t_now` по сырому ряду живого сборщика.

    Половина, которую зовёт сканер. Считает НЕ своей арифметикой, а той
    же `falls` на той же сетке — ради этого ядро и заведено: живой
    вход и вход в реплее обязаны решаться одним кодом, иначе калибровка
    исполнения описывала бы другую сделку.
    """
    j_now = int(np.floor(float(t_now)))
    t0 = j_now - int(window_sec)
    row = place(times, mids, t0, int(window_sec) + 1)
    return float(falls(row, window_sec=window_sec, tol=tol)[-1])
