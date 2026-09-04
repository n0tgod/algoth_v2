#!/usr/bin/env python3
"""
tick/σ — шаг цены в единицах волатильности, метка на имя-месяц.

Механика `fcbd3542`. Утверждение заявки: отскок первых секунд (спека 11,
ячейка вердикта D1) сосредоточен в половине универсума с МЕЛКИМ шагом
цены относительно её собственной волатильности и слаб либо обратен в
половине с крупным. Здесь считается только МЕТКА; замер — в
`run_halves.py`.

    tick_rel = шаг цены / цена            (безразмерная, доля)
    ticksig  = tick_rel / σ_суточная      (безразмерная)

Обе величины безразмерны, поэтому имена сравнимы между собой — а это и
есть весь смысл: у BTC двести уровней книги стоят в четырёх базисных
пунктах, у альта полсотни уровней размазаны на шестьдесят три (аудит
B1). Мера, относительная к соседям по стакану, не инвариантна к нарезке;
мера, относительная к собственной волатильности, инвариантна — тем же
приёмом T1 чинил порог объёма, а B1 порог «крупного уровня».

Три правила, которые модуль держит сам
--------------------------------------

**Метка считается строго ДО месяца события.** Окно — тридцать суток,
кончающихся в полночь первого дня месяца. Иначе цена входила бы в метку
задним числом: имя, обвалившееся внутри месяца, имеет более низкую
среднюю цену, значит более крупный `tick_rel`, — и попадало бы в
«крупную» половину ровно потому, что падало. А падавшие имена и есть
источник событий. Это загрязнение не видно в результате, поэтому оно
запрещено конструкцией, а не аккуратностью: `window()` не знает о
событиях вовсе, и её свойство закреплено тестом.

**Замороженный ряд даёт пропуск, а не бесконечность.** Архив Binance
публикует бары с перенесённой ценой годами после смерти инструмента
(A2). У такого имени σ равна нулю, а `tick_rel / 0` — плюс
бесконечность, то есть «самый крупный шаг в универсуме» у инструмента,
которого нет. Тот же класс ловушки, что обратная волатильность без пола
в S1. Поэтому σ считается ТОЛЬКО по барам со сделками (это делает
`series.load`, и второй такой загрузки не заводится), а нулевая σ
означает «меры нет».

**Масштаб цены берётся у той площадки, которой принадлежит шаг.** Шаг
цены — свойство контракта Bybit, а σ и цена читаются из архива Binance,
и у семи имён универсума множители контрактов различаются: `10000SATS`
на Bybit против `1000SATS` на Binance — это десятикратная разница в
цене и, значит, в `tick_rel`. Множитель выводится из САМИХ ИМЁН
(ведущее или замыкающее число), то есть из статических метаданных, а не
подгонкой отношения цен: подогнанное отношение зависело бы от периода и
молча вобрало бы в себя падение инструмента.

Чего здесь нет
--------------

Ни событий, ни доходностей, ни вердикта. Модуль отвечает на один
вопрос: «какой у этого имени шаг цены в единицах его волатильности на
момент начала месяца» — и честно молчит там, где ответа нет.
"""

import datetime as dt
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (os.path.join(RESEARCH, "a4_cointegration"),
           os.path.join(RESEARCH, "asset_groups")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

UNIVERSE = os.path.join(RESEARCH, "a1_universe", "out", "universe.json")
INSTRUMENTS = os.path.join(RESEARCH, "a1_universe", "out", "instruments.json")
PARQUET = os.path.join(RESEARCH, "a2_storage", "out", "parquet")

# --- объявлено ДО прогона --------------------------------------------
LOOKBACK_D = 30        # окно метки, суток; задано заявкой
MIN_OBS = 20           # суток с ценой в окне, ниже — меры нет
#   Две трети окна. Ниже этого σ по горсти дней описывает не имя, а
#   несколько его дней; выше — окно теряло бы свежие листинги целиком.
#   Порог назначен здесь и до чтения чисел.
DDOF = 1               # σ выборочная

# Доля физической памяти под DuckDB. У соседей 0.55; здесь меньше
# намеренно и заметно: рядом идёт запись стакана И часовой цикл
# обучения, а отобранная у сборщика память стоит суток записи, которую
# неоткуда докачать. Замерено на машине прогона: свободно около 3.3 ГБ
# из 7.7, то есть 0.55 от полной памяти — это больше, чем свободно
# вообще.
MEMORY_SHARE = 0.15

_LEAD = re.compile(r"^(\d+)")
_TRAIL = re.compile(r"(\d+)(?:USDT|USD|USDC|PERP)$")


def name_multiplier(symbol):
    """Множитель контракта, вытащенный из ИМЕНИ.

    `1000SATSUSDT` → 1000, `SHIB1000USDT` → 1000, `TAGUSDT` → 1.
    Ведущее число сильнее замыкающего: имена вида `1000000CHEEMSUSDT`
    несут его спереди, а `SHIB1000USDT` — единственная форма с
    замыкающим, и спереди у неё цифр нет.
    """
    s = str(symbol)
    m = _LEAD.match(s)
    if m:
        return float(m.group(1))
    m = _TRAIL.search(s)
    if m:
        return float(m.group(1))
    return 1.0


def price_scale(bybit_symbol, binance_symbol):
    """Во сколько раз цена на Bybit больше цены на Binance.

    Отношение множителей из имён. Статическая величина: она не зависит
    ни от периода, ни от того, что делала цена, — поэтому подставить в
    неё будущее нечем.
    """
    b = name_multiplier(bybit_symbol)
    n = name_multiplier(binance_symbol)
    if not n:
        return None
    return b / n


def load_universe(path=UNIVERSE):
    """Отображение символов Bybit в символы Binance."""
    import json
    d = json.load(open(path, encoding="utf-8"))["assets"]
    out = {}
    for rec in d.values():
        b, n = rec.get("bybit_symbol"), rec.get("binance_symbol")
        if b and n:
            out[b] = n
    return out


def load_ticks(path=INSTRUMENTS):
    """Шаг цены по справочнику площадки исполнения."""
    import json
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for sym, rec in d.items():
        try:
            t = float(rec.get("tick_size"))
        except (TypeError, ValueError):
            continue
        if t > 0:
            out[sym] = t
    return out


def window(month, days=LOOKBACK_D):
    """Окно метки для месяца `YYYY-MM`: `[начало − days, начало)`.

    Правый край — полночь первого дня месяца, и он ИСКЛЮЧЁН. Ни один бар
    самого месяца в метку не входит; это и есть защита от заглядывания,
    и она здесь, а не в вызывающем коде, чтобы её нельзя было забыть.
    """
    y, m = (int(x) for x in str(month).split("-")[:2])
    end = dt.date(y, m, 1)
    return (end - dt.timedelta(days=int(days))).isoformat(), end.isoformat()


def connect(share=MEMORY_SHARE, tmp=None):
    """Своё подключение к DuckDB со своим временным каталогом.

    Чужое (`series.connect`) создало бы временный каталог в чужом
    `out/`, а строителю писать вне своего каталога нельзя. Расчётная
    суть — запросы — при этом остаётся чужой: их считает `series.load` и
    `liquidity.scan`, которым сюда передаётся именно это подключение.
    """
    import duckdb
    con = duckdb.connect()
    # Временный каталог — СИБЛИНГ `out/`, а не внутри него: публикация
    # кладёт в git `research/*/out` целиком, и временные файлы DuckDB
    # уехали бы туда вместе с отчётом.
    tmp = tmp or os.path.join(HERE, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    con.execute(f"PRAGMA temp_directory='{tmp}'")
    con.execute(f"PRAGMA memory_limit='{int(total / 1024**2 * share)}MB'")
    con.execute("SET TimeZone='UTC'")
    return con


def closes_loader(con, interval="1m"):
    """Загрузчик суточных закрытий из хранилища A2.

    Оборачивает `series.load` — ту же функцию, которой ряды читают A4 и
    R1. Она уже держит требование A2 «бар с `trades = 0` не есть
    наблюдение», и переписывать это правило здесь значило бы завести
    вторую его копию: разойдясь, они дали бы замороженному имени
    ненулевую σ ровно там, где вся ловушка.
    """
    import series as SR

    def load(symbols, t0, t1):
        if not symbols:
            return {}
        got = SR.load(con, list(symbols), t0, t1, step="1d",
                      interval=interval)
        return {s: list(v[1]) for s, v in got.items()}
    return load


def turnover_loader(con, interval="1m"):
    """Загрузчик подневного оборота из хранилища A2.

    Оборот считает `liquidity.scan` — определение оборота в проекте одно
    (`sum(quote_volume) FILTER (trades > 0)`), и повторять формулу здесь
    нельзя: разъехавшись, контроль оборота делил бы имена не тем, чем
    их делит остальной проект. Оборот в котируемой валюте, поэтому
    множитель контракта на него не влияет.
    """
    import liquidity as LQ

    def load(symbols, t0, t1):
        want = set(symbols)
        out = {}
        d = os.path.join(PARQUET, interval)
        for f in sorted(os.listdir(d)):
            if not f.endswith(".parquet"):
                continue
            ym = f[:-len(".parquet")]
            if ym[:7] < t0[:7] or ym[:7] > t1[:7]:
                continue
            for sym, day, turn, _b, _bt, _tr in LQ.scan(
                    con, os.path.join(d, f)):
                if sym not in want:
                    continue
                iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
                if t0 <= iso < t1:
                    out.setdefault(sym, []).append(float(turn or 0.0))
        return out
    return load


def sigma_of(closes, ddof=DDOF):
    """σ суточных доходностей ряда закрытий. `None` — меры нет.

    Ноль возвращается только тогда, когда ряд ДЕЙСТВИТЕЛЬНО постоянен:
    это замороженный ряд A2, и вызывающий обязан прочесть его как
    пропуск, а не как «самая спокойная монета в универсуме».
    """
    v = [float(c) for c in closes if c is not None and float(c) > 0]
    if len(v) < 3:
        return None
    r = [v[i + 1] / v[i] - 1.0 for i in range(len(v) - 1)]
    if len(r) < 2:
        return None
    return st.stdev(r) if ddof == 1 else st.pstdev(r)


def label_one(tick, closes, scale, turnover=None, min_obs=MIN_OBS):
    """Метка одного имени. Всегда возвращает словарь с полем `why`.

    `ticksig = None` означает «не измерено», и причина названа словом.
    Молчаливого нуля здесь нет ни в одной ветке: ноль у `ticksig`
    читался бы как «шаг бесконечно мелкий», то есть как принадлежность
    к проверяемой половине.
    """
    rec = {"ticksig": None, "tick_rel": None, "sigma": None, "price": None,
           "turnover": None, "obs": len(closes or []), "why": None}
    if not tick or tick <= 0:
        rec["why"] = "нет шага цены в справочнике"
        return rec
    if scale is None or scale <= 0:
        rec["why"] = "имя не сопоставлено с архивом"
        return rec
    v = [float(c) for c in (closes or []) if c is not None and float(c) > 0]
    if len(v) < int(min_obs):
        rec["why"] = f"суток с ценой {len(v)} при минимуме {int(min_obs)}"
        return rec
    sig = sigma_of(v)
    if sig is None:
        rec["why"] = "σ не считается: ряд короче трёх наблюдений"
        return rec
    price = st.median(v) * float(scale)
    rec["price"] = price
    rec["sigma"] = sig
    if sig <= 0:
        # Замороженный ряд A2: цена перенесена, сделок нет, σ = 0.
        # Делить на неё нельзя — получилось бы «самый крупный шаг в
        # универсуме» у инструмента, который не торгуется.
        rec["why"] = "σ равна нулю: ряд замороженный, меры нет"
        return rec
    if price <= 0:
        rec["why"] = "цена не положительна"
        return rec
    rec["tick_rel"] = float(tick) / price
    rec["ticksig"] = rec["tick_rel"] / sig
    if turnover:
        t = [float(x) for x in turnover if x is not None]
        if t:
            rec["turnover"] = st.median(t)
    return rec


def build(month, symbols, load_closes, load_turnover=None, ticks=None,
          bymap=None, min_obs=MIN_OBS, days=LOOKBACK_D):
    """Метки всех имён на месяц. Возвращает `(метки, окно)`.

    Загрузчики передаются аргументами, а не берутся из модуля: так
    свойство «метка не видит месяца события» проверяется тестом на
    подставном универсуме, а не принимается на слово.
    """
    ticks = load_ticks() if ticks is None else ticks
    bymap = load_universe() if bymap is None else bymap
    t0, t1 = window(month, days)
    pairs = [(s, bymap[s]) for s in symbols if s in bymap]
    closes = load_closes([n for _s, n in pairs], t0, t1) or {}
    turns = {}
    if load_turnover is not None:
        turns = load_turnover([n for _s, n in pairs], t0, t1) or {}
    out = {}
    for sym in symbols:
        n = bymap.get(sym)
        if n is None:
            out[sym] = {"ticksig": None, "tick_rel": None, "sigma": None,
                        "price": None, "turnover": None, "obs": 0,
                        "why": "имени нет в универсуме A1"}
            continue
        out[sym] = label_one(ticks.get(sym), closes.get(n),
                             price_scale(sym, n), turns.get(n), min_obs)
    return out, (t0, t1)


def halves(labels, key="ticksig"):
    """Деление имён пополам по медиане `key`. Только размеченные.

    Возвращает `(тонкая, крупная, медиана)`. Тонкая — МЕЛКИЙ шаг в
    единицах волатильности, то есть та половина, где заявка ждёт
    отскока. Имя ровно на медиане уходит в крупную: правило должно быть
    однозначным, а при чётном числе имён такого имени не бывает вовсе.
    """
    vals = {s: r[key] for s, r in labels.items()
            if r.get(key) is not None}
    if len(vals) < 2:
        return set(), set(), None
    med = st.median(vals.values())
    thin = {s for s, v in vals.items() if v < med}
    coarse = {s for s, v in vals.items() if v >= med}
    return thin, coarse, med
