#!/usr/bin/env python3
"""
A2 — отчёт о гигиене данных.

Спецификация 02, раздел 2.4. Отчёт обязателен: без него последующие числа
не подлежат интерпретации. Пять проверок, и каждая сделана измеримой, а не
декларативной — параметр, который спека оставляет открытым, здесь считается
по данным, а не назначается.

1. **Пропуски баров.** Фиксируются явно, интерполяцией не заполняются:
   остановка торгов — реальное событие, на котором срабатывает стоп.
2. **Выбросы.** Помечаются, но не удаляются, по той же причине. Порог берётся
   от медианного отклонения самого символа: у альта дневное движение в 20 %
   норма, у BTC — событие, и общий порог осмысленным быть не может.
3. **Начало жизни.** Спека говорит «отсекается карантин в N дней», но не
   говорит, чему равно N. Считается профиль: во сколько раз движение в
   k-й день после листинга больше обычного для этого же инструмента.
4. **Конец жизни.** То же с другого края: за сколько дней до делистинга
   данные перестают быть репрезентативными.
5. **Согласованность по времени.** Обе ноги пары обязаны иметь бар в одну
   и ту же минуту, иначе спред считается по разновременным ценам. Отдельно
   считаются бары без сделок: такой бар существует, но цена в нём
   несвежая — для спреда это то же самое, что пропуск.

    python3 hygiene.py --interval 15m
"""

import argparse
import bisect
import json
import os
import sys
from array import array

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
PARQUET = os.path.join(OUT, "parquet")
A1_OUT = os.path.join(RESEARCH, "a1_universe", "out")

STEP_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

# Выброс — движение, во столько раз превышающее медианное абсолютное
# отклонение доходностей самого символа. Порог робастный: медиана не
# сдвигается от самих выбросов, в отличие от стандартного отклонения,
# которое они же и раздувают.
OUTLIER_MAD = 10.0

QUARANTINE_DAYS = 30      # горизонт профиля начала жизни
ENDLIFE_DAYS = 30         # горизонт профиля конца жизни
PAIR_SYMBOLS = 45         # символов для попарного замера согласованности
                          # (даёт ~990 пар)
PAIR_WINDOW_DAYS = 365    # хвост истории каждого символа для этого замера

# Доля оперативной памяти, отдаваемая движку. Остаток нужен самому Python:
# замер согласованности ног держит массивы меток времени, и если отдать
# движку всё, эти два потребителя столкнутся.
MEMORY_SHARE = 0.55
TMP = os.path.join(OUT, ".tmp")


def memory_limit_mb():
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return max(512, int(total * MEMORY_SHARE / 1024 / 1024))


def connect(interval):
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    # Промежуточные результаты обязаны выливаться на диск, а не в OOM.
    # На 1m покрытие считается по 759 млн строк, и `median(abs(ret))` —
    # агрегат точный, а не приближённый: чтобы взять медиану, движок держит
    # все значения группы. База in-memory по умолчанию сливать некуда, и
    # ядро убивает прогон на первом же шаге, через полминуты после старта.
    # На 15m это не проявлялось: там строк в пятнадцать раз меньше и всё
    # помещалось в память.
    #
    # Приближённая медиана убрала бы симптом и испортила измерение: MAD
    # служит порогом выброса, и порог не должен зависеть от того, сколько
    # памяти оказалось на машине.
    os.makedirs(TMP, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{TMP}'")
    con.execute(f"PRAGMA memory_limit='{memory_limit_mb()}MB'")
    glob = os.path.join(PARQUET, interval, "*.parquet")
    con.execute(f"CREATE VIEW bars AS SELECT * FROM read_parquet('{glob}')")
    return con


def per_symbol(con, step_min):
    """Покрытие, пропуски, мёртвые бары и выбросы по каждому символу.

    Обход идёт **по одному символу за запрос**, а не одним запросом по всей
    таблице. Причина не в стиле, а в том, что одним запросом на 1m это не
    считается вовсе. Оконная функция `lag` с разбиением по символу требует
    упорядочить все 759 млн строк, а `median` — агрегат точный, и чтобы
    взять медиану, движок держит все значения группы. На восьми гигабайтах
    прогон умирал от OOM через полминуты, а с выливанием на диск съедал
    27 ГБ временных файлов за минуту и продолжал расти. На 15m этого не
    было видно: строк в пятнадцать раз меньше, всё помещалось в память.

    Посимвольный обход дёшев именно благодаря раскладке хранилища: символ
    внутри партиции лежит отдельной row group, и Parquet хранит по группам
    минимум и максимум колонок, поэтому `WHERE symbol = ?` читает свою
    группу, а не партицию целиком. Ради этого раскладка и делалась.

    Считаемые величины не меняются: медиана остаётся точной, порог выброса
    не должен зависеть от того, сколько памяти оказалось на машине.
    """
    symbols = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()]

    out = []
    for sym in symbols:
        row = con.execute(f"""
            WITH r AS (
                SELECT open_time, close, volume, trades,
                       ln(close / lag(close) OVER (ORDER BY open_time)) AS ret
                FROM bars WHERE symbol = ?
            ),
            m AS (
                SELECT median(abs(ret)) AS mad
                FROM r WHERE ret IS NOT NULL AND ret <> 0
            )
            SELECT count(*)                                     AS bars,
                   -- Метки приводятся к строке в запросе: иначе duckdb
                   -- тянет pytz ради timezone-aware значений, а лишняя
                   -- зависимость на сервере не нужна.
                   CAST(min(r.open_time) AS VARCHAR)            AS first_bar,
                   CAST(max(r.open_time) AS VARCHAR)            AS last_bar,
                   CAST(date_diff('minute', min(r.open_time),
                                  max(r.open_time))
                        / {step_min} + 1 AS BIGINT)             AS expected,
                   sum(CASE WHEN r.trades = 0 THEN 1 ELSE 0 END)  AS no_trade,
                   sum(CASE WHEN r.volume = 0 THEN 1 ELSE 0 END)  AS zero_vol,
                   any_value(m.mad)                             AS mad,
                   sum(CASE WHEN abs(r.ret) > {OUTLIER_MAD} * m.mad
                            THEN 1 ELSE 0 END)                  AS outliers
            FROM r, m
        """, [sym]).fetchone()
        if row and row[0]:
            out.append((sym,) + tuple(row))
    return out


def life_profile(con, side, days):
    """Во сколько раз движение у края жизни отличается от обычного.

    `side='start'` — дни от листинга, `side='end'` — дни до последнего бара.
    Нормируется на медиану самого символа, иначе профиль будет описывать
    состав выборки, а не поведение инструментов: у молодых альтов движение
    больше в любой день их жизни.

    Считается в два прохода по той же причине, что и покрытие: одним
    запросом на 1m это не считается. Здесь окно ещё дороже — рамка
    `UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` по каждому символу поверх
    759 млн строк, — да ещё точная медиана на символ поверх всей истории.

    Проход первый: по одному символу за запрос считается `typical` и сразу
    же, тем же сканированием, откладываются отношения только для края
    жизни. Край — это `days` суток, то есть порядка тридцати миллионов
    строк на всю выборку вместо семисот шестидесяти миллионов.

    Проход второй: финальная свёртка по дню поверх отложенного. Медиана
    остаётся точной и пулится по всем символам сразу — ровно как раньше,
    иначе профиль описывал бы состав выборки.
    """
    idx = ("date_diff('day', first_value(open_time) OVER w, open_time)"
           if side == "start" else
           "date_diff('day', open_time, last_value(open_time) OVER w)")

    symbols = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()]

    con.execute("CREATE OR REPLACE TEMP TABLE edge (day BIGINT, ratio DOUBLE)")
    for sym in symbols:
        con.execute(f"""
            INSERT INTO edge
            WITH r AS (
                SELECT open_time,
                       abs(ln(close / lag(close) OVER w)) AS ar,
                       {idx} AS d
                FROM bars WHERE symbol = ?
                WINDOW w AS (ORDER BY open_time
                             ROWS BETWEEN UNBOUNDED PRECEDING
                                      AND UNBOUNDED FOLLOWING)
            ),
            base AS (
                SELECT median(ar) AS typical FROM r
                WHERE ar IS NOT NULL AND ar > 0 AND d > {days}
            )
            -- Символ без «обычного» движения выпадает целиком: у него вся
            -- история короче горизонта, нормировать не на что. В прежней
            -- формулировке это делал внутренний JOIN, здесь — проверка на
            -- NULL, потому что median по пустому множеству возвращает
            -- строку, а группировка не возвращала ничего.
            SELECT r.d, r.ar / base.typical
            FROM r, base
            WHERE r.ar IS NOT NULL AND r.ar > 0 AND r.d <= {days}
              AND base.typical IS NOT NULL
        """, [sym])

    return con.execute(
        "SELECT day, median(ratio) AS ratio, count(*) AS n"
        " FROM edge GROUP BY day ORDER BY day").fetchall()


def frozen_tails(con, min_days=7):
    """Хвост ряда, где бары публикуются, но сделок нет ни одной.

    Самая тихая ловушка из найденных. Архив Binance не прекращает выдавать
    бар после того, как инструмент там перестал торговаться: бар выходит
    каждые 15 минут с перенесённой ценой, годами. У SCUSDT последняя сделка
    2022-06-17, а бары идут до 2026-06-30 — четыре года константы.

    Почему это опаснее пропуска:

    - проверка «есть ли бар» проходит на 100 %, то есть штатная гигиена
      раздела 2.4 такой ряд не ловит;
    - доходности равны нулю, поэтому волатильность выглядит крошечной,
      а σ спреда — заниженной;
    - на площадке исполнения инструмент в это время торговался. То есть
      ряд для оценки отношения (Binance, раздел 2.2) фиктивен ровно там,
      где торговое окно настоящее.

    **Следствие для A3 и далее:** концом ряда Binance считается последний
    бар со сделкой, а не последний опубликованный. Бар с `trades = 0` —
    пропуск, а не наблюдение.
    """
    # Обычная группировка, а не оконная функция. `max(...) OVER (PARTITION
    # BY symbol)` вычисляет ровно то же самое, но заставляет движок держать
    # партицию целиком, чтобы приписать результат каждой строке — а строк
    # на 1m семьсот шестьдесят миллионов. Группировка идёт потоком: на
    # каждый из 720 символов живёт по два значения.
    rows = con.execute(f"""
        SELECT symbol,
               CAST(date_diff('day',
                              max(CASE WHEN trades > 0 THEN open_time END),
                              max(open_time)) AS BIGINT)       AS frozen_days,
               CAST(max(CASE WHEN trades > 0 THEN open_time END)
                    AS VARCHAR)                                AS last_traded,
               CAST(max(open_time) AS VARCHAR)                 AS last_bar
        FROM bars
        GROUP BY symbol
        HAVING frozen_days >= {min_days}
        ORDER BY frozen_days DESC
    """).fetchall()
    return [{"symbol": s, "frozen_days": d, "last_traded": lt, "last_bar": lb}
            for s, d, lt, lb in rows]


def pair_alignment(con, universe, n_symbols, window_days=PAIR_WINDOW_DAYS):
    """Согласованность двух ног по времени на пересечении их сроков жизни.

    Считаются две разные величины, и различие между ними и есть суть
    проверки:

    - **общий бар** — метка времени есть у обеих ног. Отсутствие означает,
      что спред в этот момент посчитать нечем;
    - **общий бар со сделками у обеих** — в баре у каждой ноги была хотя бы
      одна сделка. Бар без сделок существует, но цена в нём перенесена с
      предыдущего: формально данные есть, фактически спред считается по
      несвежей цене. Для оценки отношения это то же самое, что пропуск,
      только молчаливый.

    Ряды вытягиваются в память по символу и пересекаются попарно: запрос на
    каждую пару отдельно читал бы одни и те же партиции по многу раз, и на
    сотнях пар это дороже всего остального вместе взятого.
    """
    syms = sorted(
        r["binance_symbol"] for r in universe["assets"].values()
        if r.get("binance_symbol") and r.get("asset_class") != "non_crypto"
    )
    # Равномерная выборка по алфавиту: он не связан ни с ликвидностью, ни с
    # возрастом, поэтому не смещает результат в сторону мажоров.
    step = max(1, len(syms) // n_symbols)
    picked = syms[::step][:n_symbols]

    # Окно ограничено сверху, и ряды держатся отсортированными массивами,
    # а не множествами. На 15m множества занимали десятки мегабайт, но на
    # 1m баров в пятнадцать раз больше: сорок пять символов за всю историю
    # дали бы порядка ста тридцати миллионов меток, а множество целых в
    # Python стоит под сотню байт на элемент — машина с восемью гигабайтами
    # такого не переживёт. Свойство, которое здесь измеряется, от длины
    # окна не зависит, поэтому ограничение ничего не портит.
    horizon_ms = window_days * 86_400_000
    series = {}
    for s in picked:
        rows = con.execute(
            "SELECT epoch_ms(open_time), trades FROM bars WHERE symbol = ?"
            " AND open_time >= (SELECT max(open_time) FROM bars WHERE symbol = ?)"
            f"     - INTERVAL {window_days} DAY"
            " ORDER BY open_time", [s, s]).fetchall()
        if not rows:
            continue
        ts = array("q", (t for t, _ in rows))
        tr = array("q", (t for t, n in rows if n and n > 0))
        series[s] = (ts, tr)

    def intersect(x, y):
        """Число общих элементов двух отсортированных массивов."""
        i = j = n = 0
        while i < len(x) and j < len(y):
            if x[i] == y[j]:
                n, i, j = n + 1, i + 1, j + 1
            elif x[i] < y[j]:
                i += 1
            else:
                j += 1
        return n

    def window(arr, lo, hi):
        return arr[bisect.bisect_left(arr, lo):bisect.bisect_right(arr, hi)]

    out = []
    names = sorted(series)
    for i, a in enumerate(names):
        ta, tra = series[a]
        for b in names[i + 1:]:
            tb, trb = series[b]
            lo, hi = max(ta[0], tb[0]), min(ta[-1], tb[-1])
            if hi <= lo:
                continue
            wa, wb = window(ta, lo, hi), window(tb, lo, hi)
            if not wa or not wb:
                continue
            both = intersect(wa, wb)
            if not both:
                continue
            traded_both = intersect(window(tra, lo, hi), window(trb, lo, hi))
            out.append({
                "a": a, "b": b,
                "overlap_days": round((hi - lo) / 86_400_000, 1),
                "bars_in_window": max(len(wa), len(wb)),
                "share_common": both / max(len(wa), len(wb)),
                "share_both_traded": traded_both / both,
            })
    return out


def quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    s = sorted(v for v in vals if v is not None)
    if not s:
        return {}
    return {q: s[min(len(s) - 1, int(q * (len(s) - 1)))] for q in qs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--pair-symbols", type=int, default=PAIR_SYMBOLS)
    ap.add_argument("--pair-days", type=int, default=PAIR_WINDOW_DAYS)
    args = ap.parse_args()

    step = STEP_MINUTES[args.interval]
    con = connect(args.interval)
    with open(os.path.join(A1_OUT, "universe.json"), encoding="utf-8") as f:
        universe = json.load(f)

    print("покрытие и выбросы...", file=sys.stderr, flush=True)
    rows = per_symbol(con, step)
    symbols = {}
    for (sym, bars, first, last, expected, no_trade, zero_vol, mad, out) in rows:
        symbols[sym] = {
            "bars": bars,
            "first_bar": first,
            "last_bar": last,
            "expected": expected,
            "missing": expected - bars,
            "missing_pct": 100 * (expected - bars) / expected if expected else 0,
            "no_trade_bars": no_trade,
            "no_trade_pct": 100 * no_trade / bars if bars else 0,
            "zero_volume_bars": zero_vol,
            "mad": mad,
            "outliers": out,
            "outlier_pct": 100 * out / bars if bars else 0,
        }

    print("профиль начала жизни...", file=sys.stderr, flush=True)
    start = life_profile(con, "start", QUARANTINE_DAYS)
    print("профиль конца жизни...", file=sys.stderr, flush=True)
    end = life_profile(con, "end", ENDLIFE_DAYS)

    print("замороженные хвосты...", file=sys.stderr, flush=True)
    frozen = frozen_tails(con)

    print(f"согласованность по времени, {args.pair_symbols} символов...",
          file=sys.stderr, flush=True)
    pairs = pair_alignment(con, universe, args.pair_symbols, args.pair_days)

    doc = {
        "meta": {
            "interval": args.interval,
            "symbols": len(symbols),
            "bars": sum(v["bars"] for v in symbols.values()),
            "outlier_mad_threshold": OUTLIER_MAD,
            "universe_as_of": universe["archive_as_of"],
        },
        "symbols": symbols,
        "life_start": [{"day": d, "ratio": r, "n": n} for d, r, n in start],
        "life_end": [{"day": d, "ratio": r, "n": n} for d, r, n in end],
        "pair_alignment": pairs,
        "frozen_tails": frozen,
    }
    path = os.path.join(OUT, f"hygiene_{args.interval}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)

    miss = sum(v["missing"] for v in symbols.values())
    tot = sum(v["expected"] for v in symbols.values())
    print(json.dumps({
        "symbols": len(symbols),
        "bars": doc["meta"]["bars"],
        "missing_bars": miss,
        "missing_pct": round(100 * miss / tot, 4) if tot else 0,
        "no_trade_pct_median": round(
            quantiles([v["no_trade_pct"] for v in symbols.values()]).get(0.5, 0), 2),
        "outlier_pct_median": round(
            quantiles([v["outlier_pct"] for v in symbols.values()]).get(0.5, 0), 3),
        "pairs_measured": len(pairs),
        "frozen_tail_symbols": len(frozen),
        "frozen_days_total": sum(f["frozen_days"] for f in frozen),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
