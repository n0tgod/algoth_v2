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
import json
import os
import sys

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
PAIR_SAMPLE = 400         # пар для замера согласованности по времени


def connect(interval):
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    glob = os.path.join(PARQUET, interval, "*.parquet")
    con.execute(f"CREATE VIEW bars AS SELECT * FROM read_parquet('{glob}')")
    return con


def per_symbol(con, step_min):
    """Покрытие, пропуски, мёртвые бары и выбросы по каждому символу."""
    return con.execute(f"""
        WITH r AS (
            SELECT symbol, open_time, close, volume, trades,
                   ln(close / lag(close) OVER w) AS ret
            FROM bars
            WINDOW w AS (PARTITION BY symbol ORDER BY open_time)
        ),
        m AS (
            SELECT symbol, median(abs(ret)) AS mad
            FROM r WHERE ret IS NOT NULL AND ret <> 0
            GROUP BY symbol
        )
        SELECT r.symbol,
               count(*)                                        AS bars,
               min(r.open_time)                                AS first_bar,
               max(r.open_time)                                AS last_bar,
               CAST(date_diff('minute', min(r.open_time), max(r.open_time))
                    / {step_min} + 1 AS BIGINT)                AS expected,
               sum(CASE WHEN r.trades = 0 THEN 1 ELSE 0 END)   AS no_trade_bars,
               sum(CASE WHEN r.volume = 0 THEN 1 ELSE 0 END)   AS zero_volume_bars,
               any_value(m.mad)                                AS mad,
               sum(CASE WHEN abs(r.ret) > {OUTLIER_MAD} * m.mad
                        THEN 1 ELSE 0 END)                     AS outliers
        FROM r JOIN m USING (symbol)
        GROUP BY r.symbol
        ORDER BY r.symbol
    """).fetchall()


def life_profile(con, side, days):
    """Во сколько раз движение у края жизни отличается от обычного.

    `side='start'` — дни от листинга, `side='end'` — дни до последнего бара.
    Нормируется на медиану самого символа, иначе профиль будет описывать
    состав выборки, а не поведение инструментов: у молодых альтов движение
    больше в любой день их жизни.
    """
    idx = ("date_diff('day', first_value(open_time) OVER w, open_time)"
           if side == "start" else
           "date_diff('day', open_time, last_value(open_time) OVER w)")
    return con.execute(f"""
        WITH r AS (
            SELECT symbol, open_time,
                   abs(ln(close / lag(close) OVER w)) AS ar,
                   {idx} AS d
            FROM bars
            WINDOW w AS (PARTITION BY symbol ORDER BY open_time
                         ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
        ),
        base AS (
            SELECT symbol, median(ar) AS typical FROM r
            WHERE ar IS NOT NULL AND ar > 0 AND d > {days}
            GROUP BY symbol
        )
        SELECT r.d AS day, median(r.ar / base.typical) AS ratio, count(*) AS n
        FROM r JOIN base USING (symbol)
        WHERE r.ar IS NOT NULL AND r.ar > 0 AND r.d <= {days}
        GROUP BY r.d ORDER BY r.d
    """).fetchall()


def pair_alignment(con, universe, sample):
    """Доля общих меток времени у двух ног — по случайным парам универсума.

    Считается на пересечении сроков жизни: вне его несовпадение тривиально
    и о качестве данных ничего не говорит.
    """
    syms = sorted(
        r["bybit_symbol"] and r["binance_symbol"]
        for r in universe["assets"].values()
        if r.get("binance_symbol") and r.get("asset_class") != "non_crypto"
    )
    syms = [s for s in syms if s]
    pairs = []
    step = max(1, len(syms) // int(sample ** 0.5 + 1))
    for i in range(0, len(syms), step):
        for j in range(i + step, len(syms), step):
            pairs.append((syms[i], syms[j]))
            if len(pairs) >= sample:
                break
        if len(pairs) >= sample:
            break

    rows = []
    for a, b in pairs:
        r = con.execute("""
            WITH x AS (SELECT open_time, trades FROM bars WHERE symbol = ?),
                 y AS (SELECT open_time, trades FROM bars WHERE symbol = ?),
                 lo AS (SELECT greatest((SELECT min(open_time) FROM x),
                                        (SELECT min(open_time) FROM y)) AS t),
                 hi AS (SELECT least((SELECT max(open_time) FROM x),
                                     (SELECT max(open_time) FROM y)) AS t)
            SELECT
              (SELECT count(*) FROM x, lo, hi
                WHERE x.open_time BETWEEN lo.t AND hi.t)          AS nx,
              (SELECT count(*) FROM y, lo, hi
                WHERE y.open_time BETWEEN lo.t AND hi.t)          AS ny,
              (SELECT count(*) FROM x JOIN y USING (open_time), lo, hi
                WHERE x.open_time BETWEEN lo.t AND hi.t)          AS both,
              (SELECT count(*) FROM x JOIN y USING (open_time), lo, hi
                WHERE x.open_time BETWEEN lo.t AND hi.t
                  AND x.trades > 0 AND y.trades > 0)              AS both_traded
        """, [a, b]).fetchone()
        nx, ny, both, traded = r
        if not both:
            continue
        rows.append({
            "a": a, "b": b, "overlap_bars": both,
            "share_of_max": both / max(nx, ny) if max(nx, ny) else None,
            "share_traded": traded / both if both else None,
        })
    return rows


def quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    s = sorted(v for v in vals if v is not None)
    if not s:
        return {}
    return {q: s[min(len(s) - 1, int(q * (len(s) - 1)))] for q in qs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--pairs", type=int, default=PAIR_SAMPLE)
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
            "first_bar": str(first),
            "last_bar": str(last),
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

    print(f"согласованность по времени, {args.pairs} пар...",
          file=sys.stderr, flush=True)
    pairs = pair_alignment(con, universe, args.pairs)

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
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
