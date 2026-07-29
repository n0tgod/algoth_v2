#!/usr/bin/env python3
"""
T0 — инвентаризация данных потока заявок: лента, кластеры, стакан.

Не гипотеза и не спека: ответ на вопрос, **из чего можно строить**. Тот
же жанр, что A0 для площадок и L0 для ликвидаций, и по той же причине —
дешевле выяснить, что данных нет, чем обнаружить это на середине.

Откуда взялось направление
--------------------------

Пять закрытых гипотез очертили, где эджа нет: в медленной статистической
торговле по барам и кросс-секциям. Последний зонд сказал другое —
краткосрочный возврат реален, не микроструктурен, при идеальном
исполнении покрывает издержки вдвое, и **упирается в скорость**: минута
задержки съедает две трети. То есть эдж в первых секундах после
движения, и достаётся он тому, кто читает поток, а не график.

Это ровно та ниша, где работают команды на ленте и кластерах. Наш стенд
их метод **никогда не проверял** — он построен на барах и в принципе не
видит поглощения. Отсутствие проверки не есть опровержение.

Четыре вопроса
--------------

1. **Что лежит в ленте площадки исполнения.** Нужна не просто сделка, а
   **сторона агрессора**: без неё нет ни дельты, ни кластеров, ни
   поглощения. A0 признак агрессора у Bybit подтвердила, здесь — состав
   колонок целиком и разрешение метки времени.
2. **Есть ли архив стакана.** Кластеры и дельта считаются из ленты;
   поглощение видно и по ней, но «плотность в стакане» — нет. Если
   снимков уровней нет ни у одной площадки, часть методики придётся
   выводить косвенно, и знать это надо сразу.
3. **Сколько это весит.** L0 намерила: лента Binance по BTCUSDT — 43.6 ГБ
   сжатыми за историю, против 0.07–0.15 ГБ у минутных свечей. Здесь
   считается вес **узкого среза**, с которого имеет смысл начинать:
   несколько символов, несколько месяцев.
4. **Совпадают ли ленты площадок.** Мы уже дважды обжигались на том, что
   данные одной площадки не переносятся на другую: ставки funding
   расходятся, соглашение о метке `metrics` у Binance и Bybit разное.
   Лента — тем более: исполняем на Bybit, и мерить надо на ней.

Только стандартная библиотека, сетевые ответы кэшируются.

    python3 research/t0_orderflow_inventory/inventory.py
"""

import gzip
import io
import json
import os
import re
import sys
import zipfile
from hashlib import sha256

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")

sys.path.insert(0, os.path.dirname(HERE))
from common.venue import fetch as _fetch, fetch_binary as _fetchb  # noqa: E402

BYBIT = "https://public.bybit.com/"
BINANCE_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
UA = "t0-orderflow-inventory/1.0"

# Крупный, средний и мелкий: вес ленты зависит от активности, и средним
# по одному символу судить обо всех нельзя.
SAMPLE = ("BTCUSDT", "SOLUSDT", "ARBUSDT")
SAMPLE_DAY = "2025-03-10"


def fetch(url, cache_key=None, binary=False):
    if binary:
        return _fetchb(url, CACHE, cache_key=cache_key, user_agent=UA)
    return _fetch(url, CACHE, cache_key=cache_key, user_agent=UA)


def listing(url, key):
    try:
        return fetch(url, cache_key=key)
    except Exception as e:                                # noqa: BLE001
        return f"ОШИБКА {str(e)[:120]}"


def bybit_sections():
    """Какие разделы вообще есть в публичном архиве Bybit."""
    html = listing(BYBIT, "bybit_root")
    if html.startswith("ОШИБКА"):
        return {"error": html}
    dirs = sorted(set(re.findall(r'href="([^"?/][^"]*/)"', html)))
    return {"sections": dirs}


def bybit_trade_format():
    """Состав ленты Bybit: колонки, агрессор, разрешение метки."""
    out = {}
    html = listing(BYBIT + "trading/BTCUSDT/", "bybit_btc_list")
    if html.startswith("ОШИБКА"):
        return {"error": html}
    files = sorted(re.findall(r'href="(BTCUSDT[^"]+\.csv\.gz)"', html))
    out["files"] = len(files)
    out["first"] = files[0] if files else None
    out["last"] = files[-1] if files else None
    if not files:
        return out
    name = files[-1]
    raw = fetch(BYBIT + f"trading/BTCUSDT/{name}", cache_key=f"bb_{name}",
                binary=True)
    out["day_mb"] = round(len(raw) / 1e6, 2)
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
        head = f.readline().strip()
        rows = [f.readline().strip() for _ in range(3)]
        n = 4
        for _ in f:
            n += 1
    cols = [c.strip() for c in head.split(",")]
    out["columns"] = cols
    out["sample"] = rows
    out["rows_per_day"] = n
    out["has_side"] = any(c.lower() in ("side", "tickdirection")
                          for c in cols)
    out["has_price"] = any(c.lower() == "price" for c in cols)
    out["has_size"] = any(c.lower() in ("size", "qty", "amount", "volume")
                          for c in cols)
    # Разрешение метки: миллисекунды или микросекунды видно по числу
    # знаков после точки в первой строке.
    ti = next((i for i, c in enumerate(cols)
               if c.lower() in ("timestamp", "time")), None)
    if ti is not None and rows and rows[0]:
        val = rows[0].split(",")[ti]
        out["timestamp_sample"] = val
        out["timestamp_decimals"] = len(val.split(".")[1]) if "." in val else 0
    return out


def bybit_symbol_days(symbol):
    """Сколько суточных файлов и какого веса у символа."""
    html = listing(BYBIT + f"trading/{symbol}/", f"bb_list_{symbol}")
    if html.startswith("ОШИБКА"):
        return {"error": html}
    files = sorted(re.findall(rf'href="({symbol}[^"]+\.csv\.gz)"', html))
    return {"files": len(files),
            "first": files[0] if files else None,
            "last": files[-1] if files else None}


def bybit_day_weight(symbol, day):
    """Вес одного дня ленты и число принтов в нём."""
    name = f"{symbol}{day}.csv.gz"
    try:
        raw = fetch(BYBIT + f"trading/{symbol}/{name}",
                    cache_key=f"bbw_{symbol}_{day}", binary=True)
    except Exception as e:                                # noqa: BLE001
        return {"error": str(e)[:100]}
    n = 0
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
        f.readline()
        for _ in f:
            n += 1
    return {"mb": round(len(raw) / 1e6, 2), "prints": n}


def binance_book_sets():
    """Есть ли у Binance наборы про стакан и какого разрешения."""
    out = {}
    for freq in ("daily", "monthly"):
        url = (f"{BINANCE_S3}?delimiter=/&prefix=data/futures/um/{freq}/")
        xml = listing(url, f"bin_{freq}")
        if xml.startswith("ОШИБКА"):
            out[freq] = xml
            continue
        names = [p.rstrip("/").split("/")[-1]
                 for p in re.findall(r"<Prefix>([^<]+)</Prefix>", xml)]
        out[freq] = sorted(n for n in names if n)
    return out


def binance_agg_day(symbol, day):
    """Вес суточной ленты Binance и состав колонок."""
    key = (f"data/futures/um/daily/aggTrades/{symbol}/"
           f"{symbol}-aggTrades-{day}.zip")
    try:
        raw = fetch(f"{BINANCE_S3}/{key}", cache_key=f"agg_{symbol}_{day}",
                    binary=True)
    except Exception as e:                                # noqa: BLE001
        return {"error": str(e)[:100]}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            head = f.readline().decode().strip()
            row = f.readline().decode().strip()
            n = 2
            for _ in f:
                n += 1
    cols = [c.strip() for c in head.split(",")]
    return {"mb": round(len(raw) / 1e6, 2), "prints": n,
            "columns": cols, "sample": row,
            # У Binance сторона агрессора — флаг «покупатель был мейкером»
            "has_side": any("maker" in c.lower() for c in cols)}


def main():
    os.makedirs(OUT, exist_ok=True)
    res = {}

    print("разделы архива Bybit…", file=sys.stderr, flush=True)
    res["bybit_sections"] = bybit_sections()

    print("формат ленты Bybit…", file=sys.stderr, flush=True)
    res["bybit_trade"] = bybit_trade_format()

    print("вес суток по символам…", file=sys.stderr, flush=True)
    res["bybit_days"] = {s: bybit_symbol_days(s) for s in SAMPLE}
    res["bybit_weight"] = {s: bybit_day_weight(s, SAMPLE_DAY)
                           for s in SAMPLE}

    print("наборы Binance про стакан…", file=sys.stderr, flush=True)
    res["binance_sets"] = binance_book_sets()
    res["binance_agg"] = {s: binance_agg_day(s, SAMPLE_DAY) for s in SAMPLE}

    with open(os.path.join(OUT, "t0_inventory.json"), "w",
              encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    md = ["# T0 — инвентаризация данных потока заявок\n",
          "Что есть для ленты, кластеров и стакана на площадке "
          "исполнения и в архиве длинной истории.\n"]

    md.append("## 1. Лента площадки исполнения (Bybit)\n")
    b = res["bybit_trade"]
    if "error" in b:
        md.append(f"Недоступна: {b['error']}\n")
    else:
        md.append(f"Колонки: `{'`, `'.join(b.get('columns', []))}`\n")
        md.append("| Мера | Значение |")
        md.append("|---|---|")
        md.append(f"| Сторона агрессора | "
                  f"{'**есть**' if b.get('has_side') else 'НЕТ'} |")
        md.append(f"| Цена и объём | "
                  f"{'есть' if b.get('has_price') and b.get('has_size') else 'НЕТ'} |")
        md.append(f"| Знаков после точки в метке | "
                  f"{b.get('timestamp_decimals')} |")
        md.append(f"| Суточных файлов по BTCUSDT | {b.get('files')} |")
        md.append(f"| Период | {b.get('first')} … {b.get('last')} |")
        md.append(f"| Вес суток BTCUSDT | {b.get('day_mb')} МБ |")
        md.append(f"| Принтов в сутках | {b.get('rows_per_day'):,} |"
                  if b.get("rows_per_day") else "")
        md.append("")
        md.append("Сторона агрессора — то, без чего нет ни дельты, ни "
                  "кластеров, ни поглощения. Всё остальное из ленты "
                  "выводится.\n")

    md.append("## 2. Вес узкого среза\n")
    md.append("| Символ | Суток в архиве | Вес суток, МБ | Принтов в сутках |")
    md.append("|---|---|---|---|")
    for s in SAMPLE:
        d = res["bybit_days"].get(s, {})
        w = res["bybit_weight"].get(s, {})
        md.append(f"| {s} | {d.get('files', '—')} | {w.get('mb', '—')} | "
                  f"{w.get('prints', '—'):,} |"
                  if isinstance(w.get("prints"), int) else
                  f"| {s} | {d.get('files', '—')} | {w.get('mb', '—')} | — |")
    md.append("")
    tot = sum(res["bybit_weight"].get(s, {}).get("mb", 0) or 0
              for s in SAMPLE)
    if tot:
        md.append(f"Три символа за сутки — {tot:.1f} МБ. Срез «три "
                  f"символа × 90 суток» — около {tot * 90 / 1000:.1f} ГБ. "
                  f"Это подъёмно; лента по универсуму за историю — нет "
                  f"(L0: 43.6 ГБ на один BTCUSDT у Binance).\n")

    md.append("## 3. Стакан\n")
    for freq, names in res["binance_sets"].items():
        if isinstance(names, str):
            md.append(f"- Binance {freq}: {names}")
            continue
        book = [n for n in names if "book" in n.lower() or "depth" in n.lower()]
        md.append(f"- Binance {freq}: {', '.join(names)}")
        md.append(f"  - про стакан: **{', '.join(book) if book else 'нет'}**")
    md.append("")
    sec = res["bybit_sections"].get("sections")
    if sec:
        md.append(f"- Разделы Bybit: {', '.join(sec)}")
    md.append("")

    md.append("## 4. Лента Binance для сравнения\n")
    md.append("| Символ | Вес суток, МБ | Принтов | Сторона агрессора |")
    md.append("|---|---|---|---|")
    for s in SAMPLE:
        a = res["binance_agg"].get(s, {})
        if "error" in a:
            md.append(f"| {s} | ошибка | — | — |")
            continue
        md.append(f"| {s} | {a.get('mb')} | {a.get('prints', 0):,} | "
                  f"{'есть' if a.get('has_side') else 'НЕТ'} |")
    md.append("")
    md.append("Мерить надо на **площадке исполнения**: ставки funding "
              "площадок расходятся, соглашение о метке `metrics` у них "
              "разное, и лента — тем более. Binance здесь только для "
              "сверки объёмов.\n")

    text = "\n".join(x for x in md if x is not None)
    dst = os.path.join(OUT, "T0-inventory.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\nзаписано {dst}")


if __name__ == "__main__":
    main()
