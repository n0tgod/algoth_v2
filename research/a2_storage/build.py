#!/usr/bin/env python3
"""
A2 — хранилище: месячные архивы Binance в колоночный формат.

Спецификация 02, раздел 2.3. Схема v1 «таблица на инструмент в Postgres»
для исследования не годится: кросс-секционный запрос по 250 инструментам
превращается в 250-табличный джойн. Нужен один длинный ряд
`(symbol, time, o, h, l, c, v, trades)` с партиционированием по времени.

Устройство и почему так:

**Партиция — календарный месяц, все символы вместе.** Отбор пар в разделе 3
кросс-секционный: на дату берётся весь универсум сразу. Партиция по символу
вернула бы ту же проблему, что убила схему v1.

**Внутри партиции символы идут по порядку, каждый отдельной row group.**
Parquet хранит по группам минимум и максимум каждой колонки, поэтому запрос
по одному символу читает одну группу вместо всей партиции. Это же даёт
постоянный расход памяти: в оперативной памяти одновременно живёт один
символо-месяц, а не месяц целиком. На 1m месяц по универсуму — порядка
31 млн строк, и собирать его в памяти нельзя.

**Дедупликация по `(symbol, open_time)` обязательна.** Дыры месячного архива
Binance дозакрыты суточными файлами, а суточный файл приносит день целиком,
включая бары, которые в месячном уже были. На этапе A1 пересечение составило
491 бар. Без дедупликации они войдут в ряд дважды, и оценка σ спреда
окажется заниженной — то есть z-оценка будет систематически завышена, а
позиции открываться раньше, чем следует.

Запуск:

    python3 build.py --interval 15m            # весь универсум
    python3 build.py --interval 1m --limit 5   # пилот

Требует `pyarrow`. Прогон идемпотентный: готовые партиции пропускаются.
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
A1_OUT = os.path.join(RESEARCH, "a1_universe", "out")
OUT = os.path.join(HERE, "out")
PARQUET = os.path.join(OUT, "parquet")

# Колонки месячного файла Binance. Заголовка в файлах до 2025 года нет,
# в поздних есть — читается и то и другое.
COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]

# Хранится не всё. `close_time` выводится из `open_time` и шага, `ignore`
# всегда ноль. `quote_volume` сверх схемы раздела 2.3 нужен для фильтра
# ликвидности: сравнивать активы можно только в долларах, а не в единицах
# базового актива.
KEEP = ["open_time", "open", "high", "low", "close",
        "volume", "quote_volume", "trades", "taker_buy_quote_volume"]

SCHEMA = pa.schema([
    ("symbol", pa.string()),
    ("open_time", pa.timestamp("ms", tz="UTC")),
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.float64()),
    ("quote_volume", pa.float64()),
    ("trades", pa.int64()),
    ("taker_buy_quote_volume", pa.float64()),
])

READ_OPTS = pacsv.ReadOptions(column_names=COLUMNS)
CONVERT_OPTS = pacsv.ConvertOptions(
    column_types={c: pa.float64() for c in COLUMNS if c != "trades"}
    | {"open_time": pa.int64(), "close_time": pa.int64(), "trades": pa.int64()},
)
PARSE_OPTS = pacsv.ParseOptions(delimiter=",")

MONTH_RE = re.compile(r"-(\d{4}-\d{2})(?:-\d{2})?\.zip$")


def files_by_month(symbol_dir, symbol, interval):
    """Файлы символа, сгруппированные по месяцу. Суточные идут туда же."""
    out = defaultdict(list)
    for fn in sorted(os.listdir(symbol_dir)):
        m = MONTH_RE.search(fn)
        if m:
            out[m.group(1)].append(os.path.join(symbol_dir, fn))
    return out


def read_zip(path):
    """Одна таблица из zip-архива. Заголовок, если он есть, отбрасывается."""
    with zipfile.ZipFile(path) as z:
        blob = z.read(z.namelist()[0])
    if blob[:9] == b"open_time":
        blob = blob[blob.index(b"\n") + 1:]
    if not blob.strip():
        return None
    return pacsv.read_csv(io.BytesIO(blob), READ_OPTS, PARSE_OPTS, CONVERT_OPTS)


def symbol_month_table(symbol, paths):
    """Все файлы символо-месяца в одну таблицу, без дублей, по времени.

    Дедупликация здесь, а не позже: суточные файлы дозакрытия пересекаются
    с месячным по уже имеющимся барам.
    """
    tables = [t for t in (read_zip(p) for p in paths) if t is not None]
    if not tables:
        return None
    t = pa.concat_tables(tables).select(KEEP)
    t = t.sort_by("open_time")

    ts = t.column("open_time").to_pylist()
    keep = [i for i in range(len(ts)) if i == 0 or ts[i] != ts[i - 1]]
    dups = len(ts) - len(keep)
    if dups:
        t = t.take(keep)

    t = t.set_column(
        t.schema.get_field_index("open_time"), "open_time",
        t.column("open_time").cast(pa.timestamp("ms", tz="UTC")),
    )
    t = t.add_column(0, "symbol", pa.array([symbol] * t.num_rows, pa.string()))
    return t.cast(SCHEMA), dups


def read_manifest(path):
    """Манифест партиции: состав и её собственные числа.

    Ранний образец — голый список символов, без чисел. Такой манифест
    читается как «состав известен, дублей не знаем»: подставлять вместо
    неизвестного нуль нельзя, иначе сводка молча занизит итог.
    """
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    if isinstance(m, list):
        return {"symbols": m, "rows": None, "duplicates": None,
                "files": None}
    return {"symbols": m["symbols"], "rows": m.get("rows"),
            "duplicates": m.get("duplicates"), "files": m.get("files")}


def write_manifest(path, symbols, rows, dups, files=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"symbols": symbols, "rows": rows, "duplicates": dups,
                   "files": files}, f)


def scan_store(dest):
    """Сводка по тому, что лежит на диске, а не по тому, что сделал прогон.

    Прогон возобновляем, и при обрыве — перезагрузка сервера, OOM — вторая
    попытка пропускает готовые партиции. Если сводку писать по дельте
    прогона, она опишет остаток работы и будет выглядеть как состояние
    хранилища: после перезагрузки в отчёт ушли 42 партиции из 78 и 6075
    дублей вместо 7365. Та же ошибка уже случалась в загрузчике funding
    (правка ae9b279), поэтому здесь состояние читается только с диска.

    Число строк берётся из футера Parquet — он содержит его точно, а
    читать сами данные не нужно. Число дублей из данных не выводится
    вовсе: снятый дубль в хранилище не оставляет следа, поэтому его
    помнит манифест партиции.
    """
    stats = {"months": 0, "rows": 0, "duplicates": 0,
             "duplicates_unknown_months": 0, "bytes": 0}
    for name in sorted(os.listdir(dest)):
        if not name.endswith(".parquet"):
            continue
        path = os.path.join(dest, name)
        stats["months"] += 1
        stats["bytes"] += os.path.getsize(path)
        stats["rows"] += pq.ParquetFile(path).metadata.num_rows
        m = read_manifest(path + ".symbols.json")
        if m is None or m["duplicates"] is None:
            stats["duplicates_unknown_months"] += 1
        else:
            stats["duplicates"] += m["duplicates"]
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--raw", default=os.path.join(A1_OUT, "klines"),
                    help="каталог сырых архивов этапа A1")
    ap.add_argument("--rebuild", action="store_true",
                    help="перезаписать готовые партиции")
    ap.add_argument("--dest", default="",
                    help="куда писать партиции (по умолчанию out/parquet)")
    ap.add_argument("--months", default="",
                    help="только эти месяцы, через запятую (докачка)")
    ap.add_argument("--restat", action="store_true",
                    help="дочитать числа партиций, собранных ранним кодом; "
                         "сами партиции не переписываются")
    args = ap.parse_args()

    root = os.path.join(args.raw, args.interval)
    if not os.path.isdir(root):
        raise SystemExit(f"нет каталога {root} — сначала A1")

    symbols = sorted(os.listdir(root))
    if args.limit:
        symbols = symbols[: args.limit]

    # Раскладка «месяц -> символы» строится заранее: партиция пишется одним
    # проходом, чтобы не открывать один и тот же файл Parquet многократно.
    by_month = defaultdict(dict)
    for sym in symbols:
        d = os.path.join(root, sym)
        if not os.path.isdir(d):
            continue
        for ym, paths in files_by_month(d, sym, args.interval).items():
            by_month[ym][sym] = paths

    if args.months:
        want_months = {m.strip() for m in args.months.split(",") if m.strip()}
        by_month = {k: v for k, v in by_month.items() if k in want_months}
        if not by_month:
            raise SystemExit(f"нет сырья за месяцы: {sorted(want_months)}")

    dest = os.path.join(args.dest or PARQUET, args.interval)
    os.makedirs(dest, exist_ok=True)

    skipped = 0
    for i, ym in enumerate(sorted(by_month), 1):
        path = os.path.join(dest, f"{ym}.parquet")
        manifest = path + ".symbols.json"
        want = sorted(by_month[ym])

        # Готовность партиции определяется её составом, а не наличием файла.
        # Пилотный прогон на трёх символах создаёт файл за тот же месяц, и
        # проверка «файл есть» пропустила бы его как готовый — в партиции
        # навсегда осталось бы три символа вместо семисот. Ошибка того же
        # рода уже дважды встречалась в загрузчиках: признаком состояния
        # служило то, что сделал текущий прогон, а не то, что лежит на диске.
        done = read_manifest(manifest)
        # Число файлов сырья — часть признака готовности, а не украшение.
        # Состав символов при ДОЗАКАЧКЕ не меняется (те же имена, новые
        # суточные файлы), и партиция молча считалась бы готовой: месяц
        # остался бы без свежих дней навсегда. Тот же класс ошибки, что
        # «готовность символа по существованию файла» в L2 — признаком
        # результата служило неполное свойство.
        n_files = sum(len(v) for v in by_month[ym].values())
        fresh = (done is not None and done.get("files") is not None
                 and done["files"] != n_files)
        if os.path.exists(path) and done and done["symbols"] == want \
                and not fresh and not args.rebuild:
            if done["duplicates"] is not None or not args.restat:
                skipped += 1
                continue
            # Манифест старого образца: состав известен, а числа нет.
            # Пересчитываем их тем же кодом, не трогая саму партицию —
            # иначе они разошлись бы со сборкой.
            restat = True
        else:
            restat = False

        # В режиме пересчёта ничего не пишется на диск, в том числе когда
        # состав партиции разошёлся с раскладкой: иначе `--restat --limit`
        # пересобрал бы месяц по горстке символов и потерял остальные.
        if args.restat and not restat:
            skipped += 1
            continue

        tmp = path + ".tmp"
        writer = None
        rows = dups = 0
        for sym in want:
            res = symbol_month_table(sym, by_month[ym][sym])
            if res is None:
                continue
            table, d = res
            dups += d
            rows += table.num_rows
            if restat:
                continue
            if writer is None:
                writer = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
            writer.write_table(table)          # один символ — одна row group
        if not restat:
            if writer is None:
                continue
            writer.close()
            os.replace(tmp, path)              # партиция появляется целиком
        write_manifest(manifest, want, rows, dups, n_files)
        print(f"  {i}/{len(by_month)} {ym}: {rows} строк, дублей {dups}"
              + (" (пересчёт)" if restat else ""),
              file=sys.stderr, flush=True)

    stats = scan_store(dest)
    stats["symbols"] = len(symbols)
    stats["skipped_existing"] = skipped
    stats["interval"] = args.interval
    with open(os.path.join(OUT, f"build_{args.interval}.json"), "w",
              encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
