#!/usr/bin/env python3
"""
L0 — инвентаризация данных о ликвидациях.

Не гипотеза и не спека: ответ на вопрос, **из чего вообще можно
строить**. Тот же жанр, что A0 для площадок, и по той же причине —
дешевле выяснить, что данных нет, чем обнаружить это на середине.

Три вопроса
-----------

1. **Есть ли прямая выкладка принудительных закрытий.** Если событие
   помечено в архиве, его не надо выводить из подписи — а вывод из
   подписи есть отдельная модель со своими ошибками.
2. **Что лежит в тиковом архиве Bybit.** Ленту с признаком агрессора A0
   подтвердила; есть ли там признак ликвидации — не проверялось.
3. **Сколько это весит.** Свечи 1m по универсуму заняли 23 ГБ. Лента
   сделок — другой порядок, и впервые за проект инфраструктура может
   стать настоящим ограничением. Знать это надо до оплаты диска, а не
   после.

Почему лента, а не стакан — и поправка к этому
----------------------------------------------

Каскад — это серия агрессивных односторонних принтов: сметается
ближайшая ликвидность, цена проваливается, это добивает следующих.
Стакан показывает **последствие** (выеденную глубину), само событие
живёт в ленте.

Утверждение «исторической глубины стакана публично нет» оказалось
неверным, и инвентаризация это и вскрыла: у Binance в **суточном**
разделе лежат `bookDepth` (глубина по уровням ±1…5 % от цены, снимки
раз в минуту, с 2023-01) и `metrics` (открытый интерес и соотношения
лонг/шорт, шаг 5 минут, с 2020-09). Оба набора крошечные — 0.6 ГБ и
0.02 ГБ на символ за всю историю против 43.6 ГБ ленты.

Для гипотезы о ликвидациях это меняет план: открытый интерес есть
прямой измеритель того, сколько позиций стоит под ударом, а падение
открытого интереса при движении цены — подпись массового принудительного
закрытия. И то и другое стоит копейки по объёму.

Только стандартная библиотека, сетевые ответы кэшируются.

    python3 inventory.py
"""

import gzip
import io
import json
import os
import re
import sys
import urllib.parse
import zipfile
from hashlib import sha256

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")

sys.path.insert(0, os.path.dirname(HERE))
from common.venue import fetch as _fetch, fetch_binary as _fetchb  # noqa: E402

BINANCE_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BYBIT_ARCHIVE = "https://public.bybit.com/trading/"

# Представители: крупный, средний и мелкий по обороту — объём ленты
# зависит от активности, и средним по одному символу считать нельзя.
SAMPLE = ("BTCUSDT", "SOLUSDT", "ARBUSDT")
SAMPLE_MONTH = "2025-03"


UA = "l0-liquidation-inventory/1.0"


def fetch(url, cache_key=None, binary=False):
    if binary:
        return _fetchb(url, CACHE, cache_key=cache_key, user_agent=UA)
    return _fetch(url, CACHE, cache_key=cache_key, user_agent=UA)


def s3_list(prefix, delimiter="/"):
    keys, prefixes, marker = [], [], ""
    while True:
        url = f"{BINANCE_S3}?delimiter={delimiter}&prefix={prefix}"
        if marker:
            url += f"&marker={urllib.parse.quote(marker, safe='')}"
        xml = fetch(url, cache_key="s3_" + sha256(url.encode()).hexdigest())
        keys += re.findall(r"<Key>([^<]+)</Key>", xml)
        prefixes += re.findall(r"<Prefix>([^<]+)</Prefix>", xml)
        sizes = re.findall(r"<Size>(\d+)</Size>", xml)
        if "<IsTruncated>true</IsTruncated>" not in xml:
            break
        nm = re.findall(r"<NextMarker>([^<]+)</NextMarker>", xml)
        marker = nm[0] if nm else (keys[-1] if keys else "")
        if not marker:
            break
    return keys, prefixes


def s3_sizes(prefix):
    """Ключи с размерами — нужно для оценки объёма."""
    out, marker = {}, ""
    while True:
        url = f"{BINANCE_S3}?prefix={prefix}"
        if marker:
            url += f"&marker={urllib.parse.quote(marker, safe='')}"
        xml = fetch(url, cache_key="sz_" + sha256(url.encode()).hexdigest())
        for m in re.finditer(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", xml,
                             re.S):
            out[m.group(1)] = int(m.group(2))
        if "<IsTruncated>true</IsTruncated>" not in xml:
            break
        nm = re.findall(r"<NextMarker>([^<]+)</NextMarker>", xml)
        marker = nm[0] if nm else (list(out)[-1] if out else "")
        if not marker:
            break
    return out


def binance_datasets():
    """Какие типы данных лежат в архиве USD-M, помесячно и посуточно."""
    out = {}
    for freq in ("monthly", "daily"):
        _, prefixes = s3_list(f"data/futures/um/{freq}/")
        out[freq] = sorted(p.rstrip("/").split("/")[-1] for p in prefixes
                           if p.rstrip("/").split("/")[-1])
    return out


def binance_tape_volume():
    """Вес ленты сделок против свечей — на представителях."""
    rows = {}
    for sym in SAMPLE:
        row = {}
        for kind, sub in (("aggTrades", f"aggTrades/{sym}/"),
                          ("trades", f"trades/{sym}/"),
                          ("bookTicker", f"bookTicker/{sym}/"),
                          ("klines_1m", f"klines/{sym}/1m/")):
            pref = f"data/futures/um/monthly/{kind.split('_')[0]}/{sym}/"
            if kind == "klines_1m":
                pref = f"data/futures/um/monthly/klines/{sym}/1m/"
            try:
                sizes = s3_sizes(pref)
            except Exception as e:
                row[kind] = {"error": str(e)[:80]}
                continue
            months = {k: v for k, v in sizes.items()
                      if k.endswith(".zip") and SAMPLE_MONTH in k}
            allz = [v for k, v in sizes.items() if k.endswith(".zip")]
            row[kind] = {
                "months": len(allz),
                "sample_month_mb": round(sum(months.values()) / 1e6, 1)
                if months else None,
                "total_gb": round(sum(allz) / 1e9, 2) if allz else 0.0,
            }
        rows[sym] = row
    return rows


def bybit_tick_format():
    """Есть ли в тиковом архиве Bybit признак ликвидации."""
    html = fetch(BYBIT_ARCHIVE + "BTCUSDT/", cache_key="bybit_btc_list")
    files = re.findall(r'href="(BTCUSDT[^"]+\.csv\.gz)"', html)
    if not files:
        return {"error": "список файлов пуст"}
    name = sorted(files)[-1]
    raw = fetch(BYBIT_ARCHIVE + f"BTCUSDT/{name}", cache_key=f"bybit_{name}",
                binary=True)
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
        header = f.readline().strip()
        sample = [f.readline().strip() for _ in range(3)]
    cols = [c.strip() for c in header.split(",")]
    return {"file": name, "columns": cols, "sample": sample,
            "has_liquidation_flag": any("liq" in c.lower() for c in cols),
            "has_aggressor": any(c.lower() in ("side", "tickdirection")
                                 for c in cols),
            "first_files": sorted(files)[:2], "files": len(files)}


def binance_agg_format():
    """Колонки ленты Binance: есть ли признак принудительного закрытия."""
    sym = "BTCUSDT"
    key = (f"data/futures/um/monthly/aggTrades/{sym}/"
           f"{sym}-aggTrades-{SAMPLE_MONTH}.zip")
    try:
        raw = fetch(f"{BINANCE_S3}/{key}", cache_key=f"agg_{sym}", binary=True)
    except Exception as e:
        return {"error": str(e)[:120]}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            head = f.readline().decode().strip()
            rows = [f.readline().decode().strip() for _ in range(2)]
    cols = [c.strip() for c in head.split(",")]
    return {"file": key.split("/")[-1], "columns": cols, "sample": rows,
            "has_liquidation_flag": any("liq" in c.lower() for c in cols),
            "zip_mb": round(len(raw) / 1e6, 1)}


def main():
    os.makedirs(OUT, exist_ok=True)
    res = {}

    print("типы данных в архиве Binance USD-M…", file=sys.stderr, flush=True)
    res["binance_datasets"] = binance_datasets()

    print("формат ленты Binance…", file=sys.stderr, flush=True)
    res["binance_agg_format"] = binance_agg_format()

    print("формат тикового архива Bybit…", file=sys.stderr, flush=True)
    try:
        res["bybit_tick_format"] = bybit_tick_format()
    except Exception as e:
        res["bybit_tick_format"] = {"error": str(e)[:200]}

    print("объёмы…", file=sys.stderr, flush=True)
    res["volume"] = binance_tape_volume()

    with open(os.path.join(OUT, "l0_inventory.json"), "w",
              encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    d = res["binance_datasets"]
    print("\n1. ТИПЫ ДАННЫХ В АРХИВЕ BINANCE USD-M\n")
    for freq, names in d.items():
        liq = [n for n in names if "liq" in n.lower()]
        print(f"  {freq}: {', '.join(names)}")
        print(f"     выкладка ликвидаций: "
              f"{'ЕСТЬ — ' + ', '.join(liq) if liq else 'НЕТ'}")

    print("\n2. ПРИЗНАК ЛИКВИДАЦИИ В ЛЕНТЕ\n")
    a = res["binance_agg_format"]
    if "error" in a:
        print(f"  Binance: ошибка — {a['error']}")
    else:
        print(f"  Binance aggTrades: колонки {a['columns']}")
        print(f"     признак ликвидации: "
              f"{'есть' if a['has_liquidation_flag'] else 'НЕТ'}")
    b = res["bybit_tick_format"]
    if "error" in b:
        print(f"  Bybit: ошибка — {b['error']}")
    else:
        print(f"  Bybit тики: колонки {b['columns']}")
        print(f"     признак ликвидации: "
              f"{'есть' if b['has_liquidation_flag'] else 'НЕТ'}, "
              f"агрессор: {'есть' if b['has_aggressor'] else 'нет'}")
        print(f"     файлов по BTCUSDT: {b['files']}, "
              f"первые: {b['first_files']}")

    print("\n3. ОБЪЁМЫ, архив Binance (сжатые zip)\n")
    print(f"{'символ':<10}{'набор':<12}{'месяцев':>9}"
          f"{'месяц ' + SAMPLE_MONTH + ', МБ':>18}{'всего, ГБ':>12}")
    for sym, row in res["volume"].items():
        for kind, v in row.items():
            if "error" in v:
                print(f"{sym:<10}{kind:<12}{'ошибка':>9}")
                continue
            print(f"{sym:<10}{kind:<12}{v['months']:>9}"
                  f"{str(v['sample_month_mb']):>18}{v['total_gb']:>12}")
    print(f"\nзаписано {os.path.join(OUT, 'l0_inventory.json')}")


if __name__ == "__main__":
    main()
