#!/usr/bin/env python3
"""
A1 — загрузка свечей Binance по универсуму на момент времени.

Binance используется **только как источник исторических данных** (раздел 2.0
спеки 02). Торговля на нём недоступна, и экономика сделки — комиссии, funding,
листинги — берётся строго с площадки исполнения.

Что делает этап: скачивает месячные архивы, **сверяет контрольные суммы** и
считает, сколько баров фактически пришло против того, сколько должно быть.
Пропуски фиксируются явно и не заполняются интерполяцией (раздел 2.4).

Чего этап не делает: не строит хранилище. Parquet и DuckDB — предмет A2,
и для них нужны библиотеки, которых здесь нет. Разделение соответствует
плану работ раздела 11: A1 — загрузка, A2 — хранилище и отчёт о гигиене.

Таймфрейм задаётся аргументом. Объём по всему универсуму (20 198
символо-месяцев) на срезе 2026-07:

    1m  ~31 ГБ     5m  ~6.5 ГБ     15m  ~2.3 ГБ     1h  ~0.7 ГБ

Довод против 1m не только объёмный. На минутных барах β и корреляция
систематически занижаются из-за несинхронной торговли (эффект Эппса), а
хвост альтов торгуется редко — в таких рядах много минут вообще без сделок.
При целевом удержании 1–5 дней (раздел 11 спеки 01) более грубый бар для
оценки отношения точнее, а не грубее. Спека сама задаёт двухэтапность в
разделе 5.5: грубо по универсуму, точно — по горстке выживших пар.

Запуск:

    python3 binance_klines.py --interval 15m --limit 8   # пилот
    python3 binance_klines.py --interval 15m             # весь универсум

Прогон возобновляемый: файл с сошедшейся контрольной суммой не
перекачивается. Только stdlib.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
RAW = os.path.join(OUT, "klines")

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
WORKERS = 6
TIMEOUT = 120
RETRIES = 3

INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}


def http_bytes(url):
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "a1-klines/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None          # месяца просто нет в архиве
            last = e
        except Exception as e:  # noqa: BLE001 — сеть, нужен любой сбой
            last = e
    raise RuntimeError(f"не скачалось {url}: {last}")


def months_between(first_ym, last_ym):
    y, mo = int(first_ym[:4]), int(first_ym[5:7])
    ly, lmo = int(last_ym[:4]), int(last_ym[5:7])
    out = []
    while (y, mo) <= (ly, lmo):
        out.append(f"{y:04d}-{mo:02d}")
        mo += 1
        if mo == 13:
            y, mo = y + 1, 1
    return out


def verify_and_count(blob, checksum):
    """Сверить контрольную сумму, посчитать бары и границы ряда.

    Возвращает (число баров, первый open_time, последний open_time, статус).
    Границы нужны для честного учёта пропусков: месяц листинга и месяц
    делистинга неполны по построению, и считать их недобором — значит
    объявлять дефектом нормальные данные.
    """
    got = hashlib.sha256(blob).hexdigest()
    if checksum and got != checksum:
        return None, None, None, "checksum_mismatch"
    try:
        rows, first_ts, last_ts = 0, None, None
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                for r in csv.reader(io.TextIOWrapper(f, encoding="utf-8")):
                    if not r or r[0].startswith("open_time"):
                        continue
                    ts = int(r[0])
                    rows += 1
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
    except (zipfile.BadZipFile, ValueError, IndexError):
        return None, None, None, "bad_zip"
    return rows, first_ts, last_ts, "ok"


def fetch_month(symbol, interval, ym, keep):
    """Скачать, проверить, при необходимости сохранить один символо-месяц."""
    stem = f"{symbol}-{interval}-{ym}"
    url = f"{BASE}/{symbol}/{interval}/{stem}.zip"
    path = os.path.join(RAW, interval, symbol, f"{stem}.zip")

    if os.path.exists(path):
        with open(path, "rb") as f:
            blob = f.read()
        rows, first_ts, last_ts, status = verify_and_count(blob, None)
        return {"month": ym, "rows": rows or 0, "first_ts": first_ts,
                "last_ts": last_ts, "status": status, "bytes": len(blob),
                "cached": True}

    blob = http_bytes(url)
    if blob is None:
        return {"month": ym, "rows": 0, "first_ts": None, "last_ts": None,
                "status": "absent", "cached": False}

    chk_raw = http_bytes(url + ".CHECKSUM")
    checksum = chk_raw.decode().split()[0] if chk_raw else None

    rows, first_ts, last_ts, status = verify_and_count(blob, checksum)
    if status == "ok" and keep:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(blob)
    return {
        "month": ym,
        "rows": rows or 0,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "status": status,
        "bytes": len(blob),
        "checksum_verified": checksum is not None,
        "cached": False,
    }


def plan(manifest, interval):
    """Какие символо-месяцы нужны: от начала истории Binance до смерти на Bybit.

    Верхняя граница — последний торговый день на площадке исполнения:
    после делистинга на Bybit актив выходит из универсума, и месяцы Binance
    за пределами этого срока в исследовании не участвуют.
    """
    jobs = []
    for base, rec in sorted(manifest["assets"].items()):
        sym, first = rec.get("binance_symbol"), rec.get("binance_first_month")
        if not sym or not first:
            continue
        last_bybit = rec["last_trading_day"][:7]
        last = min(last_bybit, rec["binance_last_month"] or last_bybit)
        if last < first:
            continue
        jobs.append((base, sym, months_between(first, last)))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="15m", choices=sorted(INTERVAL_MINUTES))
    ap.add_argument("--limit", type=int, default=0,
                    help="взять только N активов с самой длинной историей (пилот)")
    ap.add_argument("--no-keep", action="store_true",
                    help="проверять, но не сохранять файлы на диск")
    args = ap.parse_args()

    with open(os.path.join(OUT, "universe.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    jobs = plan(manifest, args.interval)
    if args.limit:
        jobs = sorted(jobs, key=lambda j: -len(j[2]))[: args.limit]

    total_months = sum(len(m) for m in (j[2] for j in jobs))
    print(f"активов: {len(jobs)}, символо-месяцев: {total_months}, "
          f"таймфрейм: {args.interval}", file=sys.stderr, flush=True)

    inventory, done = {}, [0]

    def work(job):
        base, sym, months = job
        res = []
        for ym in months:
            res.append(fetch_month(sym, args.interval, ym, keep=not args.no_keep))
        done[0] += 1
        print(f"  {done[0]}/{len(jobs)} {base}", file=sys.stderr, flush=True)
        return base, sym, res

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        step_ms = INTERVAL_MINUTES[args.interval] * 60_000
        for base, sym, res in ex.map(work, jobs):
            got = sum(r["rows"] for r in res)
            stamps = [r for r in res if r["first_ts"] is not None]
            first_ts = min(r["first_ts"] for r in stamps) if stamps else None
            last_ts = max(r["last_ts"] for r in stamps) if stamps else None
            # Ожидание считается по наблюдаемому диапазону, а не по календарю:
            # неполные месяцы листинга и делистинга — не пропуск данных.
            exp = ((last_ts - first_ts) // step_ms + 1) if stamps else 0
            inventory[base] = {
                "binance_symbol": sym,
                "interval": args.interval,
                "months_requested": len(res),
                "months_ok": sum(1 for r in res if r["status"] == "ok"),
                "months_absent": [r["month"] for r in res if r["status"] == "absent"],
                "months_bad": [r["month"] for r in res if r["status"] in
                               ("checksum_mismatch", "bad_zip")],
                "first_bar": first_ts,
                "last_bar": last_ts,
                "bars": got,
                "bars_expected": exp,
                "missing_bars": exp - got,
                "bytes": sum(r.get("bytes", 0) for r in res),
            }

    bars = sum(v["bars"] for v in inventory.values())
    exp = sum(v["bars_expected"] for v in inventory.values())

    # Артефакт описывает сам себя: пилотный прогон на горстке активов
    # не должен выглядеть как полный универсум.
    doc = {
        "meta": {
            "interval": args.interval,
            "universe_as_of": manifest["archive_as_of"],
            "assets_in_universe": len(plan(manifest, args.interval)),
            "assets_loaded": len(inventory),
            "pilot_limit": args.limit or None,
            "complete": not args.limit,
        },
        "assets": inventory,
    }
    suffix = f"_pilot{args.limit}" if args.limit else ""
    path = os.path.join(OUT, f"klines_inventory_{args.interval}{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(json.dumps({
        "interval": args.interval,
        "assets": len(inventory),
        "months_ok": sum(v["months_ok"] for v in inventory.values()),
        "months_absent": sum(len(v["months_absent"]) for v in inventory.values()),
        "months_bad": sum(len(v["months_bad"]) for v in inventory.values()),
        "bars": bars,
        "bars_expected": exp,
        "missing_bars_pct": round(100 * (exp - bars) / exp, 3) if exp else 0,
        "bytes": sum(v["bytes"] for v in inventory.values()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
