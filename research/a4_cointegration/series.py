#!/usr/bin/env python3
"""
A4 — чтение рядов из хранилища A2 с приведением к нужному шагу.

Шаг бара — не техническая деталь, а параметр, от которого зависит ответ
теста на коинтеграцию. Окно отбора в 90 дней на 1m даёт 130 тысяч
наблюдений, и тест с такой выборкой отвергает единичный корень при
сколь угодно слабом возврате к среднему: статистическая значимость и
торговая пригодность здесь расходятся. Поэтому шаг задаётся явно и
проверяется на чувствительность.

Два требования этапа A2 выполняются буквально:

- **бар с `trades = 0` — не наблюдение.** Архив Binance публикует бары
  с перенесённой ценой годами после смерти инструмента. Такой бар не
  участвует ни в оценке β, ни в тесте: доходность по нему ноль, и он
  занижает σ спреда;
- ряд обрывается на **последнем баре со сделкой**, а не на последнем
  опубликованном.

Приведение к шагу делается в DuckDB по границе времени, а не
пересчётом номера бара: месяцы неполны по краям, и нумерация разъехалась
бы на границе партиций.
"""

import os

import duckdb
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
PARQUET = os.path.join(RESEARCH, "a2_storage", "out", "parquet")
OUT = os.path.join(HERE, "out")

MEMORY_SHARE = 0.55

# Шаг бара -> выражение усечения времени в DuckDB.
STEPS = {
    "1m": None,
    "5m": "time_bucket(INTERVAL '5 minutes', open_time)",
    "15m": "time_bucket(INTERVAL '15 minutes', open_time)",
    "1h": "time_bucket(INTERVAL '1 hour', open_time)",
    "4h": "time_bucket(INTERVAL '4 hours', open_time)",
    "1d": "time_bucket(INTERVAL '1 day', open_time)",
}


def memory_limit_mb():
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return int(total / 1024**2 * MEMORY_SHARE)


def connect():
    con = duckdb.connect()
    tmp = os.path.join(OUT, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{tmp}'")
    con.execute(f"PRAGMA memory_limit='{memory_limit_mb()}MB'")
    con.execute("SET TimeZone='UTC'")
    return con


def partition_files(interval, t0, t1):
    """Партиции, пересекающиеся с окном. Читать всё хранилище незачем."""
    d = os.path.join(PARQUET, interval)
    want = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".parquet"):
            continue
        ym = f[:-len(".parquet")]
        if ym[:7] >= t0[:7] and ym[:7] <= t1[:7]:
            want.append(os.path.join(d, f))
    return want


def load(con, symbols, t0, t1, step="1h", interval="1m"):
    """Цены закрытия по шагу `step` за `[t0, t1)`.

    Возвращает `{symbol: (times, closes)}`, времена — numpy int64 в
    миллисекундах, цены — float64. Закрытием интервала считается цена
    последнего бара СО СДЕЛКАМИ внутри него: иначе замороженная минута
    в конце часа подменила бы часовое закрытие ценой, которой на рынке
    не было.
    """
    files = partition_files(interval, t0, t1)
    if not files:
        return {}
    bucket = STEPS[step] or "open_time"
    # Список файлов и список символов подставляются литералами, а не
    # параметрами запроса: с параметром DuckDB не отсекает row group по
    # статистикам, и вместо одной группы на символ читается партиция
    # целиком — на замере это двадцатикратная разница.
    flist = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    slist = ", ".join("'" + s.replace("'", "''") + "'" for s in symbols)
    q = f"""
        WITH src AS (
            SELECT symbol, open_time, close
            FROM read_parquet([{flist}])
            WHERE symbol IN ({slist})
              AND open_time >= TIMESTAMPTZ '{t0}'
              AND open_time <  TIMESTAMPTZ '{t1}'
              AND trades > 0
        )
        SELECT symbol,
               {bucket} AS t,
               arg_max(close, open_time) AS close
        FROM src
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    # Забираем через Arrow одним куском: миллионы строк по одной через
    # fetchall стоят больше, чем сам запрос.
    tbl = con.execute(q).fetch_arrow_table()
    syms = tbl.column("symbol").to_numpy(zero_copy_only=False)
    times = tbl.column("t").to_numpy(zero_copy_only=False)
    closes = tbl.column("close").to_numpy(zero_copy_only=False)
    times = times.astype("datetime64[ms]").astype("int64")
    closes = closes.astype(np.float64)

    # Ряды идут подряд по символу (ORDER BY в запросе), поэтому границы
    # находятся одним проходом, без словаря списков на каждую строку.
    out = {}
    if len(syms) == 0:
        return out
    edges = np.flatnonzero(syms[1:] != syms[:-1]) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(syms)]))
    for i, j in zip(starts, ends):
        out[syms[i]] = (times[i:j], closes[i:j])
    return out


STEP_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
           "4h": 14_400_000, "1d": 86_400_000}


def resample(t, c, step):
    """Приведение уже загруженного ряда 1m к более крупному шагу.

    Читать хранилище отдельно под каждый шаг незачем: перечитывание тех
    же трёх месяцев по всему универсуму стоит минуту на шаг. Метка
    интервала — его начало, как у `time_bucket`, значение — последняя
    цена внутри интервала. Пустые интервалы не появляются: их просто нет
    в ряду, и это правильно — бара со сделками там не было.
    """
    ms = STEP_MS[step]
    if ms == STEP_MS["1m"]:
        return t, c
    b = t // ms
    # Последний элемент каждой корзины: там, где номер корзины меняется,
    # плюс самый последний.
    idx = np.flatnonzero(np.diff(b))
    idx = np.concatenate((idx, [len(b) - 1])) if len(b) else idx
    return b[idx] * ms, c[idx]


def align(a, b):
    """Общие моменты времени двух рядов.

    Пересечение по метке времени, а не «склеить по индексу»: у ног
    разные пропуски, и склейка по порядку сдвинула бы одну ногу
    относительно другой на неизвестное число баров.
    """
    ta, ca = a
    tb, cb = b
    common, ia, ib = np.intersect1d(ta, tb, assume_unique=True,
                                    return_indices=True)
    return common, ca[ia], cb[ib]
