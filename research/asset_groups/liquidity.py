#!/usr/bin/env python3
"""
A3 — подневная ликвидность каждого актива по хранилищу A2.

Зачем отдельный слой. Спека 02, раздел 3.1 требует сокращать пространство
поиска по внешним признакам, и сектор — только один из них. Второй —
размер: L1 с оборотом в миллиард и L1 с оборотом в миллион не пара, даже
если сектор один. Но размер нельзя брать сегодняшний. Актив, который
сегодня в первом дециле, в окне 2022 года мог быть неликвидным, и деление
групп «по сегодняшнему обороту» протащило бы в отбор знание из будущего —
ровно тот дефект, который в A1 стоил универсума по текущему списку.

Поэтому здесь считается ряд, а не число: оборот и торговая активность по
дням. Слой tiers берёт из него срез на дату окна.

Два требования этапа A2 выполняются здесь буквально:

- **бар с `trades = 0` — не наблюдение.** Архив Binance продолжает
  публиковать бары после смерти инструмента на площадке, с перенесённой
  ценой и нулевым оборотом. Такие бары не входят ни в оборот, ни в
  знаменатель торговой активности как «торговался»;
- **мера ликвидности — доля баров со сделками**, а не оборот. Оборот
  отвечает «много ли торгуют», доля баров — «свежая ли цена в момент,
  когда мы считаем спред». Для парной торговли важен второй, поэтому
  считаются оба и хранятся раздельно.

Прогон идёт по одной партиции за раз: партиция месяца на 1m — до 31 млн
строк, и агрегат по (символ, день) укладывается в память, а вот запрос по
всему хранилищу сразу не уложился бы. Тот же урок, что в hygiene.py.

    python3 liquidity.py --interval 1m
"""

import argparse
import csv
import gzip
import json
import os
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
PARQUET = os.path.join(RESEARCH, "a2_storage", "out", "parquet")

MEMORY_SHARE = 0.55


def memory_limit_mb():
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return int(total / 1024**2 * MEMORY_SHARE)


def connect():
    con = duckdb.connect()
    tmp = os.path.join(OUT, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{tmp}'")
    con.execute(f"PRAGMA memory_limit='{memory_limit_mb()}MB'")
    # Без явной зоны граница суток зависела бы от настройки машины, и
    # подневный оборот на VPS и в песочнице разошёлся бы на сдвиг.
    con.execute("SET TimeZone='UTC'")
    return con


def partitions(interval):
    d = os.path.join(PARQUET, interval)
    if not os.path.isdir(d):
        raise SystemExit(f"нет хранилища {d} — сначала A2")
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.endswith(".parquet")]


def scan(con, path):
    """Подневный агрегат одной партиции.

    `quote_volume` суммируется только по барам со сделками. На
    замороженном хвосте он и так нулевой, но полагаться на это нельзя:
    бар без сделок с ненулевым объёмом — признак битой строки, и он
    должен выпасть из оборота, а не попасть в него.
    """
    return con.execute("""
        SELECT symbol,
               CAST(open_time AS DATE)                        AS day,
               sum(quote_volume) FILTER (trades > 0)          AS turnover,
               count(*)                                       AS bars,
               count(*) FILTER (trades > 0)                   AS bars_traded,
               sum(trades)                                    AS trades
        FROM read_parquet(?)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, [path]).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    con = connect()
    paths = partitions(args.interval)
    dest = os.path.join(OUT, f"daily_liquidity_{args.interval}.csv.gz")

    rows = 0
    with gzip.open(dest, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "day", "turnover", "bars", "bars_traded",
                    "trades"])
        for i, path in enumerate(paths, 1):
            got = scan(con, path)
            for sym, day, turn, bars, traded, trades in got:
                w.writerow([sym, day.isoformat(),
                            f"{turn or 0:.2f}", bars, traded, trades or 0])
            rows += len(got)
            print(f"  {i}/{len(paths)} {os.path.basename(path)}: "
                  f"{len(got)} символо-дней", file=sys.stderr, flush=True)

    meta = {"interval": args.interval, "partitions": len(paths),
            "symbol_days": rows, "path": os.path.basename(dest)}
    with open(os.path.join(OUT, f"liquidity_{args.interval}.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
