#!/usr/bin/env python3
"""
Z1 — скрин закономерностей: машина, которая сама перебирает УСЛОВИЯ по
записанным данным и меряет, предсказывает ли условие ход цены СВЕРХ
одновременной кросс-секции.

Это не модель и не гипотеза. Модель усредняет, а закономерность живёт в
углу распределения: замер крайности прогноза уже показал, что в верхнем
квинтиле +11.2 б.п. против +2.0 в середине. Скрин ищет такие углы
прямым перебором объявленных правил — и судит их той же дисциплиной,
которой проект судит гипотезы.

Почему перебор здесь законен
----------------------------

Перебор сотен ячеек — ровно та ошибка, что убила R5: при 96 испытаниях
лучшая ПУСТЫШКА давала Sharpe 1.19. Разница в трёх вещах:

1. **Пространство объявлено целиком до прогона** и лежит в этом файле
   таблицей `CONDITIONS`. Отчёт печатает ВСЕ ячейки, а не лучшую.
2. **Планка семейственная**: 95-й процентиль МАКСИМУМА превышения по
   всем ячейкам под нулём. Не «эта ячейка хороша», а «лучшая из наших
   ячеек лучше, чем лучшая из случайных».
3. **Мера — превышение над одновременной кросс-секцией**, а не над
   нулём. Проект трижды находил, что «эффект» принадлежал рынку:
   отскок после каскада (L3: рынку 88–90 %), рост после падения,
   асимметрия хода в замерах ленты.

Что известно и переоткрывать незачем
------------------------------------

- падение 3 % за 15 минут даёт +26 б.п. сверх кросс-секции на 30 мин
  (D1), и это НЕ окупает круг в 17.4 б.п. с двойным запасом;
- каскад с падением открытого интереса не лучше простого падения
  (L3, отношение 0.51×);
- поглощение по принтам даёт ноль на всех горизонтах (T1–T4);
- кросс-секционный возврат на сутках имеет IC 0.047 и не окупает круг.

Скрин не ищет эти четыре вещи заново. Он ищет УГЛЫ: сочетания
состояний, в которых ход сверх рынка велик настолько, что перекрывает
круг издержек с запасом.

Данные
------

Хранилище A2 (минутные бары, 2020–2026, 725 символов) через слой L3.
В баре лежат `open/high/low/close`, `quote_volume`, `trades` и
`taker_buy_quote_volume` — последняя колонка даёт долю агрессивных
ПОКУПОК на всей истории, и в проекте она не использовалась ни разу:
агрессор мерился только по ленте Bybit, на 16 символах за неделю.

Единицы и защиты
----------------

* Вход — по открытию СЛЕДУЮЩЕГО бара после срабатывания. Вход по бару
  решения есть подарок себе (урок зонда возврата).
* Собственная единица символа — медианный минутный размах за ПРОШЛЫЕ
  сутки (`(high−low)/open`). Та же мера шума, которой живой сканер
  меряет запас до стопа (правила v11/v12); константы между символами
  несравнимы (T1, T4, B1).
* Бар без сделок не наблюдение, а пропуск (A2, замороженные ряды).
* Порог ликвидности и охранное окно делистинга — масками L3.
* Все окна считаются ПО ВРЕМЕНИ на регулярной сетке: смещение по
  номеру точки через дыру уже превращало месяц в пятнадцать минут (L2).

Запуск на VPS:
  cd ~/algoth_v2 && nice -n 19 .venv/bin/python research/z1_screen/screen.py
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))

import data as D                                          # noqa: E402
import events as E                                        # noqa: E402

STEP_MIN = 1
STEP_SEC = 60
HORIZONS = (5, 15, 60, 240)       # минуты форварда
GUARD_MIN = 60                    # соседи в событии вне кросс-секции
MIN_CROSS = 50                    # меньше символов — кросс-секции нет
DEDUP_MIN = 60                    # серия срабатываний одного символа
# Единица наблюдения — временнáя КОРЗИНА длиной в горизонт, а не
# событие и не «эпизод по разрыву». Причина арифметическая: форвардные
# окна событий, отстоящих меньше чем на горизонт, перекрываются, и
# считать их независимыми значит подделать бюджет доказательства.
# Слипание по разрыву здесь не годится вовсе: на частом сигнале оно
# вырождается — первый же тест схлопнул двести событий в ДВА эпизода,
# и медиана «по эпизодам» стала медианой двух чисел. Тот же дефект
# зонд возврата уже ловил на непрерывном сигнале.
PERMS = 100                       # перестановок для семейственной планки
SEED = 20260824                   # зерно ЧИСЛОМ, а не от часов запуска
ROUND_COST_BP = 11.0              # круг тейкера в долях гросса
WARM_DAYS = 2                     # дней разогрева собственных единиц
MIN_EVENTS = 30                   # ячейка тоньше — НЕ измерена
CHUNK = 200                       # символов за раз в памяти


def log_(msg):
    print(msg, flush=True)


def month_span(mon):
    y, m = int(mon[:4]), int(mon[5:7])
    a = datetime(y, m, 1, tzinfo=timezone.utc)
    b = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=timezone.utc)
    return a, b


def grid(a, b):
    return np.arange(int(a.timestamp()), int(b.timestamp()), STEP_SEC,
                     dtype=np.int64)


def daily_units(symbols, mon, log=log_):
    """Собственные единицы символа по КАЖДЫМ суткам: шум и медианы.

    Считается агрегатом на стороне хранилища — одним проходом по
    партиции месяца. Используются значения ПРОШЛЫХ суток, поэтому в
    момент решения они известны целиком.

    `noise` — медианный минутный размах `(high−low)/open`. Ровно эта
    мера служит шумом в живом сканере, и второй меры шума в проекте
    заводить нельзя.
    """
    import series as S
    con = S.connect()
    path = os.path.join(S.PARQUET, "1m", f"{mon}.parquet")
    if not os.path.exists(path):
        con.close()
        return {}
    want = "', '".join(symbols)
    q = f"""
        SELECT symbol,
               date_trunc('day', open_time) AS d,
               median((high - low) / open)  AS noise,
               median(quote_volume)         AS med_qv,
               median(trades)               AS med_tr,
               median(quote_volume / NULLIF(trades, 0)) AS med_ts
        FROM read_parquet('{path}')
        WHERE trades > 0 AND open > 0 AND symbol IN ('{want}')
        GROUP BY 1, 2
    """
    tab = con.execute(q).fetch_arrow_table()
    con.close()
    out = {}
    syms = tab.column("symbol").to_pylist()
    days = [int(x.timestamp()) // 86400 for x in tab.column("d").to_pylist()]
    for i, s in enumerate(syms):
        out[(s, days[i])] = (
            float(tab.column("noise")[i].as_py() or np.nan),
            float(tab.column("med_qv")[i].as_py() or np.nan),
            float(tab.column("med_tr")[i].as_py() or np.nan),
            float(tab.column("med_ts")[i].as_py() or np.nan))
    log(f"  единицы: {len(out):,} символо-суток")
    return out


def unit_rows(symbols, times, units):
    """Единицы ПРОШЛЫХ суток, разложенные по минутам сетки.

    День берётся предыдущий: единица, посчитанная по тем же суткам,
    знала бы будущее внутри дня. Первые `WARM_DAYS` суток символа
    остаются пустыми — это пропуск, а не «единица равна нулю»: нулевая
    единица делает любой ход бесконечным в её единицах, и замороженный
    ряд стал бы сильнейшим сигналом (урок S1 про обратную σ без пола).
    """
    day = (times // 86400).astype(np.int64)
    n = (len(symbols), len(times))
    noise = np.full(n, np.nan, dtype=np.float32)
    qv = np.full(n, np.nan, dtype=np.float32)
    tr = np.full(n, np.nan, dtype=np.float32)
    ts = np.full(n, np.nan, dtype=np.float32)
    uniq = np.unique(day)
    for r, s in enumerate(symbols):
        for d in uniq:
            u = units.get((s, int(d) - 1))
            if not u:
                continue
            sel = day == d
            noise[r, sel], qv[r, sel] = u[0], u[1]
            tr[r, sel], ts[r, sel] = u[2], u[3]
    noise[~np.isfinite(noise) | (noise <= 0)] = np.nan
    return {"noise": noise, "med_qv": qv, "med_tr": tr, "med_ts": ts}


def back_ret(P, w):
    """Доходность за `w` минут НАЗАД: известна в момент `t`."""
    out = np.full(P.shape, np.nan, dtype=np.float32)
    if w < P.shape[1]:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, w:] = P[:, w:] / P[:, :-w] - 1.0
    return out


def fwd_ret(P, h):
    """Ход ВПЕРЁД от входа: вход по открытию следующего бара.

    Сигнал сработал на баре `j`; купить можно не раньше открытия
    `j+1`, и держать до открытия `j+1+h`. Вход по открытию самого `j`
    означал бы торговлю по цене, которая сигнал и определила.
    """
    n = P.shape[1]
    out = np.full(P.shape, np.nan, dtype=np.float32)
    e, x = 1, 1 + h
    if x < n:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, :n - x] = P[:, x:] / P[:, e:n - h] - 1.0
    return out


def cross_median(F, cols, rows):
    """Медиана одновременной кросс-секции с исключением своих событий.

    Считается только для минут, где события есть: у скрина сотни
    условий, и полная матрица масок была бы дороже самого замера.
    Возвращает медиану на каждую пару (событие) и ширину сечения.
    """
    med = np.full(len(cols), np.nan, dtype=np.float64)
    wide = np.zeros(len(cols), dtype=np.int64)
    order = np.argsort(cols, kind="stable")
    cs, cr = cols[order], rows[order]
    start = 0
    while start < len(cs):
        end = start
        while end < len(cs) and cs[end] == cs[start]:
            end += 1
        j = int(cs[start])
        col = F[:, j].astype(np.float64)
        mask = np.isfinite(col)
        mask[cr[start:end]] = False        # свои события вне сечения
        k = int(mask.sum())
        if k >= MIN_CROSS:
            m = float(np.median(col[mask]))
            med[order[start:end]] = m
            wide[order[start:end]] = k
        start = end
    return med, wide


# --- Примитивы -------------------------------------------------------
#
# Все смотрят строго назад и выражены в СОБСТВЕННЫХ единицах символа:
# абсолютные величины между инструментами несравнимы, и проект измерял
# это трижды (порог объёма T1, шум T4, гейт B1).

def roll_sum(X, w):
    """Сумма за `w` минут назад, включая текущую."""
    c = np.nancumsum(np.nan_to_num(X, nan=0.0), axis=1, dtype=np.float64)
    out = np.full(X.shape, np.nan, dtype=np.float32)
    out[:, w - 1:] = (c[:, w - 1:] - np.concatenate(
        [np.zeros((X.shape[0], 1)), c[:, :-w]], axis=1)).astype(np.float32)
    return out


def since_shock(z, thr=2.0, cap=1440):
    """Минут с последнего собственного шока |z_15| >= thr, с потолком."""
    hit = np.isfinite(z) & (np.abs(z) >= thr)
    n = z.shape[1]
    idx = np.where(hit, np.arange(n, dtype=np.float32)[None, :], np.nan)
    last = np.fmax.accumulate(np.nan_to_num(idx, nan=-1.0), axis=1)
    out = np.arange(n, dtype=np.float32)[None, :] - last
    out[last < 0] = cap
    return np.minimum(out, cap)


def primitives(P, QV, TR, TB, U, hi_prev, lo_prev, btc_row):
    """Все примитивы разом. Возвращает словарь матриц символ × минута."""
    p = {}
    for w in (5, 15, 60, 240):
        r = back_ret(P, w)
        with np.errstate(invalid="ignore", divide="ignore"):
            p[f"z{w}"] = (r / (U["noise"] * np.sqrt(w))).astype(np.float32)
        p[f"r{w}"] = r
    for w in (15, 60):
        sq = roll_sum(QV, w)
        st = roll_sum(TR, w)
        sb = roll_sum(TB, w)
        with np.errstate(invalid="ignore", divide="ignore"):
            p[f"burst{w}"] = (sq / (U["med_qv"] * w)).astype(np.float32)
            p[f"tsz{w}"] = ((sq / st) / U["med_ts"]).astype(np.float32)
            p[f"buy{w}"] = (sb / sq).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        p["rpos"] = ((P - lo_prev) / (hi_prev - lo_prev)).astype(np.float32)
    p["dwell"] = since_shock(p["z15"])
    # Состояние рынка, известное в ту же минуту: сколько имён в шоке и
    # что делает ведущий инструмент. Это НЕ признак символа, а фон, и
    # разложен он одинаково по всем строкам.
    sh = (np.abs(p["z15"]) >= 2.0)
    fin = np.isfinite(p["z15"])
    with np.errstate(invalid="ignore", divide="ignore"):
        br = sh.sum(axis=0) / np.maximum(fin.sum(axis=0), 1)
    p["breadth"] = np.repeat(br[None, :].astype(np.float32), P.shape[0], 0)
    lead = (p["z15"][btc_row] if btc_row is not None
            else np.full(P.shape[1], np.nan, dtype=np.float32))
    p["lead"] = np.repeat(lead[None, :], P.shape[0], 0)
    return p


# --- Пространство условий (объявлено ЦЕЛИКОМ до прогона) -------------
#
# Ячейка = условие × горизонт. Сторона входит в условие, а не
# выбирается после результата. Отчёт печатает все ячейки.

def build_conditions():
    C = []

    def add(name, side, fn, group):
        C.append({"name": name, "side": side, "fn": fn, "group": group})

    # A. Ход в собственных единицах: реверсия против продолжения.
    for w in (5, 15, 60):
        for thr in (2.0, 4.0):
            add(f"вниз z{w}<=-{thr:g}", +1,
                (lambda p, w=w, t=thr: p[f"z{w}"] <= -t), "ход")
            add(f"вниз z{w}<=-{thr:g}", -1,
                (lambda p, w=w, t=thr: p[f"z{w}"] <= -t), "ход")
            add(f"вверх z{w}>=+{thr:g}", -1,
                (lambda p, w=w, t=thr: p[f"z{w}"] >= t), "ход")
            add(f"вверх z{w}>=+{thr:g}", +1,
                (lambda p, w=w, t=thr: p[f"z{w}"] >= t), "ход")

    # B. Объём, размер сделки и агрессия (доля тейкерских покупок).
    for s in (+1, -1):
        add("всплеск объёма x10 при падении", s,
            lambda p: (p["burst15"] >= 10) & (p["z15"] <= -2), "объём")
        add("всплеск объёма x10 при росте", s,
            lambda p: (p["burst15"] >= 10) & (p["z15"] >= 2), "объём")
        add("агрессивные покупки >=0.70", s,
            lambda p: (p["buy15"] >= 0.70) & (p["burst15"] >= 3), "агрессия")
        add("агрессивные продажи <=0.30", s,
            lambda p: (p["buy15"] <= 0.30) & (p["burst15"] >= 3), "агрессия")
        add("крупные сделки x3 при ходе", s,
            lambda p: (p["tsz15"] >= 3) & (np.abs(p["z15"]) >= 2), "агрессия")

    # C. Ход СВОЙ против хода общего: одиночное движение против
    #    рыночного. Кросс-секция вычитает общее, но условие на breadth
    #    отбирает РАЗНЫЕ состояния рынка, и это другой вопрос.
    for s in (+1, -1):
        add("падение вместе с рынком", s,
            lambda p: (p["z15"] <= -2) & (p["breadth"] >= 0.20), "фон")
        add("падение в одиночку", s,
            lambda p: (p["z15"] <= -2) & (p["breadth"] <= 0.05), "фон")
        add("одиночный ход при спокойном BTC", s,
            lambda p: (np.abs(p["z15"]) >= 3) & (np.abs(p["lead"]) <= 1),
            "фон")

    # D. Диапазон прошлых суток и покой перед всплеском.
    for s in (+1, -1):
        add("пробой вчерашнего максимума", s,
            lambda p: (p["rpos"] >= 1.0) & (p["z60"] >= 2), "диапазон")
        add("пробой вчерашнего минимума", s,
            lambda p: (p["rpos"] <= 0.0) & (p["z60"] <= -2), "диапазон")
        add("всплеск после четырёх часов покоя", s,
            lambda p: (p["dwell"] >= 240) & (np.abs(p["z5"]) >= 3),
            "диапазон")

    # E. Четыре квадранта «цена × интерес». L3 проверил РОВНО ОДИН из
    #    них — падение при падающем интересе, — и получил 0.51× против
    #    простого падения. Остальные три не проверялись ни разу, а
    #    именно квадрант «цена вниз при РАСТУЩЕМ интересе» (новые шорты
    #    входят в падение) и есть состояние, из которого рождались
    #    сквизы, убившие гипотезы 3 и 4.
    for s in (+1, -1):
        add("падение, интерес ПАДАЕТ (ликвидации лонгов)", s,
            lambda p: (p["oi15"] <= -0.01) & (p["z15"] <= -2), "интерес")
        add("падение, интерес РАСТЁТ (входят шорты)", s,
            lambda p: (p["oi15"] >= 0.01) & (p["z15"] <= -2), "интерес")
        add("рост, интерес ПАДАЕТ (закрывают шорты)", s,
            lambda p: (p["oi15"] <= -0.01) & (p["z15"] >= 2), "интерес")
        add("рост, интерес РАСТЁТ (входят лонги)", s,
            lambda p: (p["oi15"] >= 0.01) & (p["z15"] >= 2), "интерес")
        add("набор интереса без хода цены", s,
            lambda p: (p["oi60"] >= 0.02) & (np.abs(p["z60"]) <= 0.5),
            "интерес")

    # G. Тишина инструмента и возобновление торгов. Бар без сделок в
    #    хранилище отсутствует, поэтому перерыв виден прямо в матрице.
    #    Это действие площадки или уход маркет-мейкера, а не движение
    #    цены, и в проекте оно не смотрелось ни разу.
    for s in (+1, -1):
        add("торги возобновились после получаса тишины", s,
            lambda p: (p["resume"] <= 3) & (p["silence"] >= 30), "тишина")

    # H. Угасание инструмента, измеренное СВОИМ прошлым. Честный
    #    двойник делистинга: дату снятия мы знаем только задним числом,
    #    а падение собственного оборота видно в момент решения.
    for s in (+1, -1):
        add("оборот в нижнем дециле своей истории, падение", s,
            lambda p: (p["decay"] <= 0.1) & (p["z15"] <= -2), "угасание")

    # F. Молодой листинг: универсум исследования требует 365 дней
    #    истории, поэтому первые недели жизни инструмента проектом не
    #    смотрелись ни разу.
    for s in (+1, -1):
        add("молодой листинг, падение", s,
            lambda p: (p["age"] <= 30) & (p["z15"] <= -2), "листинг")
    return C


CONDITIONS = build_conditions()


def dedup_rows(hit, dedup_min=DEDUP_MIN):
    """Одно срабатывание на серию: обвал длится десятки минут.

    Без этого одно движение даёт сотни «событий» и раздувает бюджет
    доказательства — ровно то, чем зонд L1 чуть не обманул сам себя.
    """
    rows, cols = np.nonzero(hit)
    if not len(rows):
        return rows, cols
    order = np.lexsort((cols, rows))
    rows, cols = rows[order], cols[order]
    keep = np.ones(len(rows), dtype=bool)
    last_r, last_c = -1, -10**9
    for i in range(len(rows)):
        if rows[i] == last_r and cols[i] - last_c < dedup_min:
            keep[i] = False
            continue
        last_r, last_c = rows[i], cols[i]
    return rows[keep], cols[keep]


def cell_stats(exc, ep, wide, share):
    """Сводка ячейки. Медиана — по эпизодам, а не по событиям.

    Событий у одного рыночного окна бывают сотни, и считать их
    независимыми наблюдениями значит подделать бюджет доказательства.
    """
    ok = np.isfinite(exc)
    if int(ok.sum()) < MIN_EVENTS:
        return None
    e, p = exc[ok], ep[ok]
    per = {}
    for v, k in zip(e, p):
        per.setdefault(int(k), []).append(float(v))
    med_ep = np.array([np.median(v) for v in per.values()])
    return {"events": int(ok.sum()), "episodes": len(per),
            "med_bp": float(np.median(e) * 1e4),
            "med_ep_bp": float(np.median(med_ep) * 1e4),
            "mean_bp": float(np.mean(e) * 1e4),
            "win": float(np.mean(med_ep > 0)),
            "cross": float(np.median(wide[ok])),
            "share": float(np.median(share[ok]))}


NULL_CAP = 3000                   # событий на ячейку в нулевой выборке


def month_units(symbols, mon, times, log=log_):
    """Матрицы собственных единиц символа плюс вчерашний диапазон."""
    import series as S
    con = S.connect()
    path = os.path.join(S.PARQUET, "1m", f"{mon}.parquet")
    prev = (datetime.strptime(mon, "%Y-%m") - timedelta(days=1)).strftime("%Y-%m")
    paths = [p for p in (os.path.join(S.PARQUET, "1m", f"{prev}.parquet"),
                         path) if os.path.exists(p)]
    if not paths:
        con.close()
        return None
    want = "', '".join(symbols)
    files = "', '".join(paths)
    q = f"""
        SELECT symbol, date_trunc('day', open_time) AS d,
               median((high - low) / open) AS noise,
               median(quote_volume) AS med_qv,
               median(trades) AS med_tr,
               median(quote_volume / NULLIF(trades, 0)) AS med_ts,
               max(high) AS hi, min(low) AS lo
        FROM read_parquet(['{files}'])
        WHERE trades > 0 AND open > 0 AND symbol IN ('{want}')
        GROUP BY 1, 2
    """
    tab = con.execute(q).fetch_arrow_table()
    con.close()
    idx = {s: i for i, s in enumerate(symbols)}
    day = (times // 86400).astype(np.int64)
    uniq = np.unique(day)
    keys = ("noise", "med_qv", "med_tr", "med_ts", "hi", "lo")
    per = {}
    syms = tab.column("symbol").to_pylist()
    ds = [int(x.timestamp()) // 86400 for x in tab.column("d").to_pylist()]
    cols = {k: np.asarray(tab.column(k), dtype=np.float64) for k in keys}
    for i, s in enumerate(syms):
        r = idx.get(s)
        if r is None:
            continue
        per[(r, ds[i])] = [cols[k][i] for k in keys]
    shape = (len(symbols), len(times))
    U = {k: np.full(shape, np.nan, dtype=np.float32) for k in keys}
    for d in uniq:
        sel = day == d
        for (r, dd), vals in per.items():
            if dd != int(d) - 1:            # ВЧЕРАШНИЕ единицы
                continue
            for k, v in zip(keys, vals):
                U[k][r, sel] = v
    U["noise"][~np.isfinite(U["noise"]) | (U["noise"] <= 0)] = np.nan
    # Ранг вчерашнего оборота в СОБСТВЕННОЙ истории загруженного окна
    # (около двух месяцев суток). Это честный, известный в момент
    # решения двойник делистинга: дату снятия мы знаем только задним
    # числом, а падение своего оборота видно сразу.
    R = np.full(U["med_qv"].shape, np.nan, dtype=np.float32)
    for r in range(U["med_qv"].shape[0]):
        vals = np.array([per[(r, d)][1] for d in
                         sorted({dd for (rr, dd) in per if rr == r})],
                        dtype=np.float64) if any(
                            rr == r for (rr, dd) in per) else None
        if vals is None or len(vals) < 10:
            continue
        row = U["med_qv"][r]
        ok = np.isfinite(row)
        if not ok.any():
            continue
        R[r, ok] = (np.searchsorted(np.sort(vals), row[ok], side="left")
                    / len(vals)).astype(np.float32)
    U["qv_rank"] = R
    log(f"  единицы: {len(per):,} символо-суток")
    return U


def age_matrix(symbols, times, uni):
    """Возраст листинга в сутках — из справочника универсума."""
    day = (times // 86400).astype(np.int64)
    A = np.full((len(symbols), len(times)), np.nan, dtype=np.float32)
    for r, s in enumerate(symbols):
        v = (uni.get(s) or {}).get("listed")
        if not v:
            continue
        d0 = int(datetime.strptime(v, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp()) // 86400
        A[r] = (day - d0).astype(np.float32)
    return A


def oi_matrices(symbols, times):
    """Изменение открытого интереса за 15 и 60 минут (ряд с 2024)."""
    shape = (len(symbols), len(times))
    o15 = np.full(shape, np.nan, dtype=np.float32)
    o60 = np.full(shape, np.nan, dtype=np.float32)
    have = 0
    for r, s in enumerate(symbols):
        C, _ = D.oi_series(s, times)
        if C is None:
            continue
        have += 1
        c = C.astype(np.float64)
        for w, dst in ((15, o15), (60, o60)):
            with np.errstate(invalid="ignore", divide="ignore"):
                dst[r, w:] = (c[w:] / c[:-w] - 1.0).astype(np.float32)
    return o15, o60, have


def run_length_gap(fin):
    """Сколько минут подряд не было сделок ПЕРЕД текущей минутой.

    Бар без сделок в хранилище отсутствует вовсе (правило A2: это
    пропуск, а не наблюдение с нулевой доходностью), поэтому перерыв
    торгов виден прямо дырой в матрице.
    """
    n = fin.shape[1]
    out = np.zeros(fin.shape, dtype=np.float32)
    run = np.zeros(fin.shape[0], dtype=np.float32)
    for j in range(n):
        out[:, j] = run
        run = np.where(fin[:, j], 0.0, run + 1.0)
    return out


def since_resume(fin):
    """Минут с возобновления торгов после перерыва (потолок — сутки)."""
    n = fin.shape[1]
    out = np.full(fin.shape, 1440.0, dtype=np.float32)
    since = np.full(fin.shape[0], 1440.0, dtype=np.float32)
    prev = fin[:, 0].copy()
    for j in range(n):
        started = fin[:, j] & ~prev
        since = np.where(started, 0.0, np.minimum(since + 1.0, 1440.0))
        out[:, j] = since
        prev = fin[:, j]
    return out


def base_prims(P, U, uni, symbols, times):
    """Примитивы, нужные почти всем группам, — держатся в памяти.

    Фон (`breadth`, `lead`) хранится ОДНОМЕРНЫМ: это состояние рынка,
    одинаковое для всех строк, и материализовать его матрицей значит
    занять четверть гигабайта ради повторения одного числа.
    """
    p = {}
    for w in (5, 15, 60):
        with np.errstate(invalid="ignore", divide="ignore"):
            p[f"z{w}"] = (back_ret(P, w)
                          / (U["noise"] * np.sqrt(w))).astype(np.float32)
    sh = np.abs(p["z15"]) >= 2.0
    fin = np.isfinite(p["z15"])
    with np.errstate(invalid="ignore", divide="ignore"):
        p["breadth"] = (sh.sum(axis=0)
                        / np.maximum(fin.sum(axis=0), 1)).astype(np.float32)
    btc = symbols.index("BTCUSDT") if "BTCUSDT" in symbols else None
    p["lead"] = (p["z15"][btc] if btc is not None
                 else np.full(P.shape[1], np.nan, dtype=np.float32))
    return p


def group_prims(group, P, U, prim, symbols, times, uni, log=log_):
    """Примитивы конкретной группы: материализуются и освобождаются."""
    p = dict(prim)
    if group == "диапазон":
        with np.errstate(invalid="ignore", divide="ignore"):
            p["rpos"] = ((P - U["lo"]) / (U["hi"] - U["lo"])).astype(np.float32)
        p["dwell"] = since_shock(prim["z15"])
    elif group == "листинг":
        p["age"] = age_matrix(symbols, times, uni)
    elif group == "тишина":
        fin = np.isfinite(P)
        p["silence"] = run_length_gap(fin)
        p["resume"] = since_resume(fin)
    elif group == "угасание":
        p["decay"] = U["qv_rank"]
    elif group == "интерес":
        o15, o60, have = oi_matrices(symbols, times)
        if not have:
            return None
        p["oi15"], p["oi60"] = o15, o60
        log(f"  интерес: рядов {have}")
    return p


def volume_prims(P, U, prim, rows_slice, symbols, times, log=log_):
    """Объём, размер сделки и доля агрессивных покупок — по куску имён.

    `taker_buy_quote_volume` лежит в хранилище с 2020 года и в проекте
    не использовалась НИ РАЗУ: агрессор мерился только по ленте Bybit,
    на 16 символах за неделю (T1, T2). Здесь он есть на всей истории.
    """
    syms = symbols[rows_slice]
    M = D.price_matrix(syms, times, "1m", None,
                       columns=("quote_volume", "trades",
                                "taker_buy_quote_volume"))
    QV, TR, TB = (M["quote_volume"], M["trades"],
                  M["taker_buy_quote_volume"])
    p = {"z15": prim["z15"][rows_slice], "z5": prim["z5"][rows_slice],
         "z60": prim["z60"][rows_slice],
         "breadth": prim["breadth"], "lead": prim["lead"]}
    for w in (15,):
        sq, st, sb = roll_sum(QV, w), roll_sum(TR, w), roll_sum(TB, w)
        u = {k: U[k][rows_slice] for k in ("med_qv", "med_ts")}
        with np.errstate(invalid="ignore", divide="ignore"):
            p[f"burst{w}"] = (sq / (u["med_qv"] * w)).astype(np.float32)
            p[f"tsz{w}"] = ((sq / st) / u["med_ts"]).astype(np.float32)
            p[f"buy{w}"] = (sb / sq).astype(np.float32)
    return p


def collect_events(P, U, prim, symbols, times, uni, own, log=log_):
    """События по всем условиям: словарь имя-условия → (строки, колонки).

    Группы считаются по очереди и освобождают свои матрицы: держать всё
    разом значит занять гигабайты рядом с живым сбором, а запись
    стакана — единственное необратимое в проекте.
    """
    ev = {}
    fin = np.isfinite(P)
    by_group = {}
    for c in CONDITIONS:
        by_group.setdefault(c["group"], []).append(c)
    for group, conds in by_group.items():
        if group in ("объём", "агрессия"):
            continue
        gp = group_prims(group, P, U, prim, symbols, times, uni, log)
        if gp is None:
            log(f"  группа «{group}» пропущена: нет данных")
            continue
        for c in conds:
            hit = c["fn"](gp) & fin
            hit[:, ~own] = False
            r, cc = dedup_rows(hit)
            if len(r):
                ev.setdefault(c["name"], (c, [], []))
                ev[c["name"]][1].append(r)
                ev[c["name"]][2].append(cc)
        del gp
    vol_conds = [c for c in CONDITIONS if c["group"] in ("объём", "агрессия")]
    if vol_conds:
        for a in range(0, len(symbols), CHUNK):
            sl = slice(a, min(a + CHUNK, len(symbols)))
            vp = volume_prims(P, U, prim, sl, symbols, times, log)
            fin_c = fin[sl]
            for c in vol_conds:
                hit = c["fn"](vp) & fin_c
                hit[:, ~own] = False
                r, cc = dedup_rows(hit)
                if len(r):
                    ev.setdefault(c["name"], (c, [], []))
                    ev[c["name"]][1].append(r + a)
                    ev[c["name"]][2].append(cc)
            del vp
    return {k: (v[0], np.concatenate(v[1]), np.concatenate(v[2]))
            for k, v in ev.items()}


CONDS_BY_NAME = {}
for _c in CONDITIONS:
    CONDS_BY_NAME.setdefault(_c["name"], []).append(_c)


def measure(events, P, times, acc, rng, log=log_):
    """Превышение по каждой ячейке плюс нулевые розыгрыши.

    Нуль переставляет, КАКОЙ символ сработал, оставляя минуту на месте:
    так сохраняются и календарь событий, и состояние рынка в эти
    минуты, а рвётся ровно связь «этот символ ↔ этот исход». Розыгрыши
    копятся вместе с событиями, потому что семейственная планка берётся
    по ВСЕМУ прогону, а не по месяцу.
    """
    for h in HORIZONS:
        F = fwd_ret(P, h)
        colmed = np.full(P.shape[1], np.nan, dtype=np.float64)
        fin_any = np.isfinite(F)
        need = np.unique(np.concatenate([c for _, _, c in events.values()])) \
            if events else np.array([], dtype=np.int64)
        for j in need:
            col = F[:, j]
            m = np.isfinite(col)
            if int(m.sum()) >= MIN_CROSS:
                colmed[j] = float(np.median(col[m].astype(np.float64)))
        for name, (_, rows, cols) in events.items():
            f = F[rows, cols].astype(np.float64)
            med, wide = cross_median(F, cols, rows)
            ep = times[cols] // (h * 60)     # корзина длиной в горизонт
            cnt = np.bincount(cols, minlength=P.shape[1]).astype(np.float64)
            fin_n = np.maximum(fin_any.sum(axis=0), 1)
            share = cnt[cols] / fin_n[cols]
            n = len(rows)
            take = min(n, NULL_CAP)
            sub = rng.choice(n, size=take, replace=False) if take < n \
                else np.arange(n)
            draws = np.empty((take, PERMS), dtype=np.float32)
            for pi in range(PERMS):
                pick = rng.integers(0, P.shape[0], size=take)
                for _try in range(4):
                    bad = ~np.isfinite(F[pick, cols[sub]])
                    if not bad.any():
                        break
                    pick[bad] = rng.integers(0, P.shape[0],
                                             size=int(bad.sum()))
                draws[:, pi] = (F[pick, cols[sub]]
                                - colmed[cols[sub]]).astype(np.float32)
            for cond in CONDS_BY_NAME[name]:
                key = (name, cond["side"], h)
                a = acc.setdefault(key, {"exc": [], "ep": [], "wide": [],
                                         "share": [], "null": [],
                                         "sub_exc": [], "sub_ep": [],
                                         "group": cond["group"]})
                a["exc"].append(cond["side"] * (f - med))
                a["ep"].append(ep)
                a["wide"].append(wide)
                a["share"].append(share)
                a["null"].append(cond["side"] * draws)
                a["sub_exc"].append(cond["side"]
                                    * (f[sub] - colmed[cols[sub]]))
                a["sub_ep"].append(ep[sub])
        del F
    return acc


def med_by_episode(v, ep):
    ok = np.isfinite(v)
    if not ok.any():
        return np.nan
    per = {}
    for x, k in zip(v[ok], ep[ok]):
        per.setdefault(int(k), []).append(float(x))
    return float(np.median([np.median(u) for u in per.values()]))


def summarize(acc):
    """Сводка по ячейкам и семейственная планка нуля."""
    cells, nulls = {}, []
    for key, a in acc.items():
        exc = np.concatenate(a["exc"])
        ep = np.concatenate(a["ep"])
        ok = np.isfinite(exc)
        if int(ok.sum()) < MIN_EVENTS:
            continue
        wide = np.concatenate(a["wide"])
        share = np.concatenate(a["share"])
        cells[key] = {
            "group": a["group"], "events": int(ok.sum()),
            "buckets": len({int(x) for x in ep[ok]}),
            "med_bp": med_by_episode(exc, ep) * 1e4,
            "mean_bp": float(np.mean(exc[ok])) * 1e4,
            "win": float(np.mean([np.median(v) > 0 for v in
                                  _by_ep(exc[ok], ep[ok]).values()])),
            "cross": float(np.median(wide[ok])),
            "share": float(np.median(share[ok])),
        }
    # Планка считается на ПОДВЫБОРКЕ (до NULL_CAP событий на ячейку), и
    # наблюдаемый максимум на той же подвыборке печатается рядом:
    # сравнивать планку с полной выборкой было бы сравнением разных
    # величин.
    sub_obs = {}
    for key, a in acc.items():
        if key not in cells:
            continue
        se = np.concatenate(a["sub_exc"])
        sp = np.concatenate(a["sub_ep"])
        sub_obs[key] = med_by_episode(se, sp) * 1e4
    for pi in range(PERMS):
        best = -np.inf
        for key, a in acc.items():
            if key not in cells:
                continue
            v = np.concatenate([d[:, pi] for d in a["null"]])
            sp = np.concatenate(a["sub_ep"])
            m = med_by_episode(v.astype(np.float64), sp)
            if np.isfinite(m):
                best = max(best, m * 1e4)
        if np.isfinite(best):
            nulls.append(best)
    nulls.sort()
    bar = nulls[int(0.95 * (len(nulls) - 1))] if nulls else float("nan")
    return cells, {"bar": bar,
                   "mean": float(np.mean(nulls)) if nulls else float("nan"),
                   "perms": len(nulls), "sub_obs": sub_obs}


def _by_ep(v, ep):
    per = {}
    for x, k in zip(v, ep):
        per.setdefault(int(k), []).append(float(x))
    return per


def write_report(path, cells, null, meta):
    L = []
    L.append("# Z1 — скрин закономерностей по записанным данным\n")
    L.append(f"Прогон {meta['when']} · {meta['start']}…{meta['end']} · "
             f"символов {meta['symbols']} · условий {meta['conds']} · "
             f"ячеек {len(cells)} · перестановок {null['perms']}\n")
    L.append("\n**Что меряется.** Для каждого объявленного УСЛОВИЯ — ход "
             "цены за горизонт МИНУС медиана одновременной кросс-секции "
             "(тех, у кого условие в эту минуту не сработало). Вход по "
             "открытию СЛЕДУЮЩЕГО бара. Единица символа — медианный "
             "минутный размах за прошлые сутки, та же мера шума, что у "
             "живого сканера.\n")
    L.append("\n**Как читать планку.** Ячеек сотни, поэтому «эта ячейка "
             "хороша» не значит ничего: планка берётся по МАКСИМУМУ "
             "среди всех ячеек под нулём, который переставляет, какой "
             "символ сработал, оставляя минуту на месте. Это защита от "
             "ошибки R5, где при 96 испытаниях лучшая пустышка давала "
             f"Sharpe 1.19.\n")
    L.append(f"\n- планка (95-й процентиль максимума): **{null['bar']:+.1f} "
             f"б.п.**, средний максимум {null['mean']:+.1f};\n")
    L.append(f"- круг издержек тейкера {ROUND_COST_BP:.0f} б.п.; в стрессе "
             "со спредом до 17.4;\n")
    L.append(f"- ячейка тоньше {MIN_EVENTS} событий не измерена, а не "
             "равна нулю.\n")
    best = sorted(cells.items(), key=lambda kv: -kv[1]["med_bp"])
    L.append("\n## Все ячейки, по величине превышения\n")
    L.append("| условие | стор | гор | событий | корзин | превышение, б.п. |"
             " нетто | побед | сечение | доля | выше планки |\n")
    L.append("|---|:--|--:|--:|--:|--:|--:|--:|--:|--:|:--|\n")
    for (name, side, h), c in best:
        net = c["med_bp"] - ROUND_COST_BP
        mark = "**да**" if (c["med_bp"] > null["bar"]
                            and net > 0) else ""
        L.append(f"| {name} | {'L' if side > 0 else 'S'} | {h} | "
                 f"{c['events']} | {c['buckets']} | {c['med_bp']:+.1f} | "
                 f"{net:+.1f} | {c['win']:.2f} | {c['cross']:.0f} | "
                 f"{c['share']:.3f} | {mark} |\n")
    L.append("\n«сечение» — сколько символов было в контроле, «доля» — "
             "какая часть универсума срабатывала в ту же минуту. Доля "
             "близкая к единице означает, что условие ловит состояние "
             "РЫНКА, и кросс-секция у такой ячейки вырождается: сравнивать "
             "почти не с чем (так умерла ячейка 2 % в зонде возврата).\n")
    L.append("\n## Чего этот скрин НЕ говорит\n")
    L.append("- Он не проверяет стратегию: у ячейки нет ни стопа, ни "
             "цели, ни размера, ни конкуренции за слоты.\n")
    L.append("- Превышение над кросс-секцией не есть прибыль: издержки "
             "вычтены только круговой ставкой тейкера, без проскальзывания "
             "и без спреда, а в стрессе спред растёт (D1: 6.8 б.п. на "
             "входе).\n")
    L.append("- Ячейка выше планки — повод построить гипотезу с "
             "объявленными порогами и своим нулём, а не торговать её.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))


def publish(msg):
    sh = os.path.join(os.path.dirname(RESEARCH), "tools", "publish.sh")
    try:
        subprocess.run(["bash", sh, msg], check=False, timeout=300)
    except Exception as e:                                # noqa: BLE001
        log_(f"публикация не прошла: {e}")


def months_between(start, end):
    a = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    b = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out, cur = [], a.replace(day=1)
    while cur < b:
        out.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + timedelta(days=8)).replace(day=1)
    return out


def run(start, end, symbols=None, log=log_):
    uni = D.universe()
    share, min_share = D.liquid_days("1m")
    syms = symbols or sorted(uni)
    rng = np.random.default_rng(SEED)
    acc = {}
    for mon in months_between(start, end):
        a, b = month_span(mon)
        nb = month_span((b - timedelta(days=1)).strftime("%Y-%m"))[1]
        times = grid(a, nb)
        own = (times >= int(a.timestamp())) & (times < int(b.timestamp()))
        t0 = datetime.now(timezone.utc)
        P = D.price_matrix(syms, times, "1m", None, columns=("open",))
        fill = float(np.isfinite(P).mean())
        if fill < 0.01:
            raise SystemExit(f"{mon}: матрица цен заполнена на {fill:.2%} — "
                             "пустая загрузка, а не «событий нет»")
        U = month_units(syms, mon, times, log)
        if U is None:
            log(f"  {mon}: нет партиции — пропуск")
            continue
        # Разогрев: первые сутки месяца остаются без вчерашних единиц.
        own = own & (np.isfinite(U["noise"]).any(axis=0))
        prim = base_prims(P, U, uni, syms, times)
        ev = collect_events(P, U, prim, syms, times, uni, own, log)
        n_ev = sum(len(v[1]) for v in ev.values())
        measure(ev, P, times, acc, rng, log)
        log(f"  {mon}: заполнено {fill:.1%}, условий сработало "
            f"{len(ev)}, событий {n_ev:,}, "
            f"{(datetime.now(timezone.utc) - t0).total_seconds():.0f} с")
        del P, U, prim, ev
    return acc


def main(argv=None):
    ap = argparse.ArgumentParser(description="скрин закономерностей Z1")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)      # каталог ДО счёта, не после
    syms = [s for s in args.symbols.split(",") if s] or None
    acc = run(args.start, args.end, syms)
    if not acc:
        log_("ни одного события — считать нечего")
        return 1
    cells, null = summarize(acc)
    path = os.path.join(OUT, f"Z1-screen-{args.tag}.md")
    write_report(path, cells, null,
                 {"when": datetime.now(timezone.utc)
                  .strftime("%Y-%m-%d %H:%M UTC"),
                  "start": args.start, "end": args.end,
                  "symbols": len(syms) if syms else "универсум",
                  "conds": len(CONDITIONS)})
    with open(os.path.join(OUT, f"z1-{args.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": {f"{k[0]}|{k[1]}|{k[2]}": v
                             for k, v in cells.items()},
                   "null": {k: v for k, v in null.items()
                            if k != "sub_obs"},
                   "conds": len(CONDITIONS), "perms": PERMS,
                   "start": args.start, "end": args.end}, f,
                  ensure_ascii=False)
    over = [k for k, c in cells.items()
            if c["med_bp"] > null["bar"] and c["med_bp"] > ROUND_COST_BP]
    log_(f"отчёт: {path}")
    log_(f"ячеек измерено: {len(cells)}; планка {null['bar']:+.1f} б.п.; "
         f"выше планки и круга: {len(over)}")
    for k in sorted(over, key=lambda x: -cells[x]["med_bp"])[:10]:
        c = cells[k]
        log_(f"  {k[0]} [{'L' if k[1] > 0 else 'S'}] {k[2]}м: "
             f"{c['med_bp']:+.1f} б.п., корзин {c['buckets']}")
    if not args.no_publish:
        publish("Z1: скрин закономерностей по записанным данным")
    return 0


if __name__ == "__main__":
    sys.exit(main())
