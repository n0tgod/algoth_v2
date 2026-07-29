#!/usr/bin/env python3
"""
L3 — слой данных: цены, открытый интерес и фильтры на общей сетке.

Спека 06, этап L3. Всё приводится к одной сетке в 5 минут — шагу набора
`metrics`, — и после этого отбор событий, форварды и оба контроля
становятся арифметикой по индексам, а не поиском по времени.

Почему общая сетка, а не поиск по времени
-----------------------------------------

Зонд L1 искал точку по времени с допуском, потому что ряд интереса
дырявый: у части универсума нет 15–39 % суточных файлов, и смещение на
три точки через дыру означало бы не пятнадцать минут, а месяц. На общей
регулярной сетке этот дефект исчезает **по построению**: пропущенная
точка есть `NaN` в своей ячейке, и любое сравнение с ней даёт `NaN`, а
не чужое значение.

Три места, где ошибка была бы невидимой
---------------------------------------

**1. Падение интереса считается в контрактах, а не в долларах.** Набор
`metrics` даёт и то и другое. Долларовый интерес есть контракты,
умноженные на цену, — и при падении цены на 3 % он падает примерно на
те же 3 % сам собой, без единого закрытия позиции. Условие «интерес
упал И цена упала» на долларах было бы тавтологией, а контроль 2
(события без условия на интерес) прошёл бы блестяще и бессмысленно.
Порог §7.3 в 5 млн долларов, наоборот, считается по долларовому: он про
размер инструмента.

**2. Строка `metrics` с меткой `t` завершена только в `t+5`** — это
измерено (`l1_cascades/lag.py`), а не предположено. Поэтому ряд интереса
сдвигается на шаг вперёд: в ячейке `j` лежит значение, **известное** в
момент `j`, а не помеченное им.

**3. Бар без сделок — не наблюдение.** Требование A2: архив продолжает
публиковать бары с перенесённой ценой годами после смерти инструмента.
Такой бар даёт нулевую доходность и заниженную волатильность; здесь он
просто отсутствует.

    python3 -c "import data; data.build('1m')"
"""

import csv
import gzip
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
A1_OUT = os.path.join(RESEARCH, "a1_universe", "out")
A3_OUT = os.path.join(RESEARCH, "asset_groups", "out")
L2_OUT = os.path.join(RESEARCH, "l2_data", "out")
OI_SERIES = os.path.join(L2_OUT, "oi_binance")
OUT = os.path.join(HERE, "out")

sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))

START = "2024-01-01"
END = "2026-06-30"
STEP_SEC = 300                    # шаг сетки — шаг набора metrics
STEP_MIN = 5
LAG_STEPS = 1                     # строка с меткой t известна в t+5

# Разведочная часть §4 спеки: вердикт по ней не выносится никогда.
EXPLORATORY = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
               "AVAXUSDT", "LINKUSDT", "ARBUSDT", "APTUSDT", "SUIUSDT",
               "INJUSDT", "SEIUSDT")


def grid(start=START, end=END):
    """Сетка моментов времени в секундах эпохи UTC."""
    t0 = int(datetime.fromisoformat(start).replace(
        tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(end).replace(
        tzinfo=timezone.utc).timestamp()) + 86_400 - STEP_SEC
    return np.arange(t0, t1 + STEP_SEC, STEP_SEC, dtype=np.int64)


def months(start=START, end=END):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out, cur = [], date(a.year, a.month, 1)
    while cur <= b:
        out.append(f"{cur.year:04d}-{cur.month:02d}")
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return out


def universe():
    """Крипто-активы с историей Binance: тикер -> сведения."""
    with open(os.path.join(A1_OUT, "universe.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    out = {}
    for name, v in assets.items():
        if v.get("asset_class") != "crypto" or not v.get("binance_symbol"):
            continue
        out[v["binance_symbol"]] = {
            "asset": name,
            "last_trading_day": v.get("last_trading_day"),
            "delisted": bool(v.get("delisted")),
        }
    return out


def price_matrix(symbols, times, interval="1m", log=None,
                 columns=("open",)):
    """Первая доступная цена в каждый момент сетки: `(символы × моменты)`.

    Берётся **открытие** минутного бара, начинающегося в этот момент, —
    первая цена, по которой можно купить. Закрытие предыдущего бара
    известно, но сделка по нему уже невозможна: она в прошлом.

    Бары без сделок отбрасываются: `trades = 0` — не наблюдение.

    `columns` задаёт, какие цены бара нужны. Кроме открытия бывают
    нужны `low` и `high`: по ним считается, насколько далеко цена ушла
    **против** позиции, прежде чем вернуться. Это и есть вход для
    уровня ограничения убытка — иначе он назначается на глаз.
    """
    import duckdb
    import series as S                                    # noqa: E402

    con = S.connect()
    idx = {s: i for i, s in enumerate(symbols)}
    t0, t1 = int(times[0]), int(times[-1])
    M = {c: np.full((len(symbols), len(times)), np.nan, dtype=np.float32)
         for c in columns}
    want = "', '".join(symbols)
    for mon in months(
            datetime.fromtimestamp(int(times[0]), timezone.utc).date().isoformat(),
            datetime.fromtimestamp(int(times[-1]), timezone.utc).date().isoformat()):
        path = os.path.join(S.PARQUET, interval, f"{mon}.parquet")
        if not os.path.exists(path):
            continue
        cols = ", ".join(columns)
        q = f"""
            SELECT symbol, epoch(open_time)::BIGINT AS ts, {cols}
            FROM read_parquet('{path}')
            WHERE trades > 0
              AND symbol IN ('{want}')
              AND (epoch_ms(open_time) % {STEP_SEC * 1000}) = 0
        """
        try:
            tab = con.execute(q).fetch_arrow_table()
        except duckdb.Error as e:
            raise RuntimeError(f"{mon}: {e}") from None
        # Символы берутся словарным кодированием, а не списком строк:
        # месяц на 1m по универсуму даёт миллионы строк, и `to_pylist`
        # создал бы столько же объектов Python — сотни мегабайт и
        # минуты на ровном месте. Словарь содержит 618 значений.
        d = tab.column("symbol").combine_chunks().dictionary_encode()
        vocab = d.dictionary.to_pylist()
        row_of = np.array([idx.get(s, -1) for s in vocab], dtype=np.int64)
        rows = row_of[np.asarray(d.indices)]
        ts = np.asarray(tab.column("ts"))
        ok = (ts >= t0) & (ts <= t1)
        col = ((ts - t0) // STEP_SEC).astype(np.int64)
        keep = ok & (rows >= 0)
        for c in columns:
            v = np.asarray(tab.column(c), dtype=np.float32)
            M[c][rows[keep], col[keep]] = v[keep]
        if log:
            log(f"  цены {mon}: {int(keep.sum()):,} значений")
    con.close()
    return M[columns[0]] if len(columns) == 1 else M


def oi_series(symbol, times):
    """Открытый интерес символа на сетке: контракты и доллары.

    Возвращает величины, **известные** в момент своей ячейки: ряд
    сдвинут на шаг вперёд относительно меток, потому что строка с
    меткой `t` завершена только в `t+5` (`l1_cascades/lag.py`).
    """
    path = os.path.join(OI_SERIES, f"{symbol}.npz")
    if not os.path.exists(path):
        return None, None
    with np.load(path) as z:
        t, oi, usd = z["t"], z["oi"], z["oi_usd"]
    n = len(times)
    C = np.full(n, np.nan, dtype=np.float32)
    U = np.full(n, np.nan, dtype=np.float32)
    col = (t - int(times[0])) // STEP_SEC
    ok = (col >= 0) & (col < n) & (((t - int(times[0])) % STEP_SEC) == 0)
    C[col[ok]] = oi[ok]
    U[col[ok]] = usd[ok]
    if LAG_STEPS:
        C = np.concatenate([np.full(LAG_STEPS, np.nan, np.float32),
                            C[:-LAG_STEPS]])
        U = np.concatenate([np.full(LAG_STEPS, np.nan, np.float32),
                            U[:-LAG_STEPS]])
    return C, U


def liquid_days(interval="1m", min_share=0.90):
    """Дни, в которые актив достаточно ликвиден по мере A3.

    Мера — доля баров со сделками, а не оборот: оборот отвечает «много
    ли торгуют», доля баров — «свежая ли цена в момент решения».
    """
    path = os.path.join(A3_OUT, f"daily_liquidity_{interval}.csv.gz")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала asset_groups/liquidity.py")
    share = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            bars = float(r["bars"] or 0)
            if bars <= 0:
                continue
            share.setdefault(r["symbol"], {})[r["day"]] = (
                float(r["bars_traded"]) / bars)
    return share, min_share


def liquidity_mask(symbol, times, share, min_share, window_days=90):
    """Маска моментов, где актив прошёл фильтр ликвидности §7.3.

    Ликвидность меряется по 90 дням, закончившимся **до** дня события:
    иначе в отбор попадает знание о том самом дне, в который мы входим.
    """
    days = share.get(symbol)
    n = len(times)
    if not days:
        return np.zeros(n, dtype=bool)
    d0 = datetime.fromtimestamp(int(times[0]), timezone.utc).date()
    d1 = datetime.fromtimestamp(int(times[-1]), timezone.utc).date()
    span = (d1 - d0).days + 1
    # Скользящее среднее считается накопленной суммой, а не пересчётом
    # девяноста значений на каждый день: в лоб это 52 млн обращений к
    # словарю по универсуму.
    base = d0 - timedelta(days=window_days)
    full = span + window_days
    val = np.zeros(full)
    cnt = np.zeros(full)
    for k in range(full):
        v = days.get((base + timedelta(days=k)).isoformat())
        if v is not None:
            val[k], cnt[k] = v, 1.0
    cv = np.concatenate([[0.0], np.cumsum(val)])
    cc = np.concatenate([[0.0], np.cumsum(cnt)])
    lo = np.arange(span)                       # день k-1 … k-90 включительно
    hi = lo + window_days
    s = cv[hi] - cv[lo]
    c = cc[hi] - cc[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(c > 0, s / np.maximum(c, 1), np.nan)
    ok_day = np.isfinite(mean) & (mean >= min_share)
    day_of = ((times - int(times[0])) // 86_400).astype(np.int64)
    day_of = np.clip(day_of, 0, span - 1)
    return ok_day[day_of]


def delist_mask(symbol, times, uni, guard_days=30):
    """Маска моментов вне окна делистинга §7.1.

    При снятии инструмента с торгов позиции закрываются принудительно и
    открытый интерес падает до нуля — то есть наше условие входа,
    доведённое до предела. Крупнейшие «каскады» в данных оказались бы
    расчётными днями, где ни отскока, ни возможности торговать нет.
    """
    last = (uni.get(symbol) or {}).get("last_trading_day")
    if not last:
        return np.ones(len(times), dtype=bool)
    cutoff = int(datetime.fromisoformat(last).replace(
        tzinfo=timezone.utc).timestamp()) - guard_days * 86_400
    return times < cutoff
