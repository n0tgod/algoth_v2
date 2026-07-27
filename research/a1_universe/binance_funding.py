#!/usr/bin/env python3
"""
A1 — история ставок funding с Binance.

**Это не издержки.** Раздел 5.2 спеки 02 требует считать издержки удержания
строго по ставкам площадки исполнения: ставки по одному активу между
площадками расходятся, а при удержании 3–5 дней funding — значимая часть
P&L. Ставки Bybit живут только в API и собираются на VPS (`bybit_api.py`).

Тогда зачем эти данные:

1. **Мера расхождения между площадками.** Раздел 5.2 прямо просит измерить
   её в ходе A1 и завести межплощадочный funding-спред отдельной гипотезой
   в `IDEAS.md`. Без ряда Binance измерять нечего.
2. **Перекрёстная проверка.** Раздел 7: величина, видимая на одной площадке
   и не видимая на другой за тот же период, — признак артефакта, а не
   свойства актива.
3. **Заполнение до появления VPS.** Порядок величины funding по универсуму
   виден уже сейчас, и от него зависит, насколько жёстким получится фильтр
   по периоду полураспада (раздел 3.4).

Архив отдаёт месячные файлы с полями `calc_time, funding_interval_hours,
last_funding_rate`. Объём по универсуму порядка десятка мегабайт.

Запуск:

    python3 binance_funding.py            # весь универсум
    python3 binance_funding.py --limit 10 # пилот

Возобновляемый, только stdlib.
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
RAW = os.path.join(OUT, "funding_binance")

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
WORKERS = 6
TIMEOUT = 120
RETRIES = 3

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from binance_klines import months_between  # noqa: E402
from common.funding import accruals_per_day, annualized_mean_pct  # noqa: E402


def http_bytes(url):
    last = None
    for _ in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "a1-funding/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # noqa: BLE001 — сеть, нужен любой сбой
            last = e
    raise RuntimeError(f"не скачалось {url}: {last}")


def read_month(blob, checksum):
    """Проверить контрольную сумму и разобрать месячный файл."""
    if checksum and hashlib.sha256(blob).hexdigest() != checksum:
        return None, "checksum_mismatch"
    rows = []
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            with z.open(z.namelist()[0]) as f:
                for r in csv.reader(io.TextIOWrapper(f, encoding="utf-8")):
                    if not r or r[0].startswith("calc_time"):
                        continue
                    rows.append((int(r[0]), int(float(r[1])), float(r[2])))
    except (zipfile.BadZipFile, ValueError, IndexError):
        return None, "bad_zip"
    return rows, "ok"


def collect_symbol(symbol, months):
    rows, absent, bad = [], [], []
    for ym in months:
        url = f"{BASE}/{symbol}/{symbol}-fundingRate-{ym}.zip"
        blob = http_bytes(url)
        if blob is None:
            absent.append(ym)
            continue
        chk = http_bytes(url + ".CHECKSUM")
        parsed, status = read_month(blob, chk.decode().split()[0] if chk else None)
        if status != "ok":
            bad.append(ym)
            continue
        rows += parsed
    return sorted(set(rows)), absent, bad


def write_symbol(symbol, rows):
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, f"{symbol}.csv.gz")
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["funding_time", "interval_hours", "funding_rate"])
        for ts, hours, rate in rows:
            w.writerow([
                datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(),
                hours, f"{rate:.10f}",
            ])
    return path


def summarize(rows):
    if not rows:
        return {"records": 0}
    vals = [r for _, _, r in rows]
    mean = sum(vals) / len(vals)
    intervals = sorted({h for _, h, _ in rows})

    # Число начислений в сутки измеряется по самому ряду, а не берётся из
    # объявленного интервала: интервал меняется по ходу истории. Обоснование
    # и числа — в `common/funding.py`. Та же функция считает сводку Bybit,
    # чтобы расхождение между площадками нельзя было списать на разный
    # способ подсчёта.
    per_day = accruals_per_day(rows[0][0], rows[-1][0], len(vals), intervals)
    return {
        "records": len(vals),
        "first": datetime.fromtimestamp(rows[0][0] / 1000, timezone.utc).isoformat(),
        "last": datetime.fromtimestamp(rows[-1][0] / 1000, timezone.utc).isoformat(),
        "interval_hours": intervals,
        "mean": mean,
        "min": min(vals),
        "max": max(vals),
        "annualized_mean_pct": annualized_mean_pct(mean, per_day),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(OUT, "universe.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    jobs = []
    for rec in manifest["assets"].values():
        sym, first = rec.get("binance_symbol"), rec.get("binance_first_month")
        if not sym or not first:
            continue
        last_bybit = rec["last_trading_day"][:7]
        last = min(last_bybit, rec["binance_last_month"] or last_bybit)
        if last < first:
            continue
        jobs.append((rec["base"], sym, months_between(first, last)))
    jobs.sort()
    if args.limit:
        jobs = sorted(jobs, key=lambda j: -len(j[2]))[: args.limit]

    print(f"активов: {len(jobs)}", file=sys.stderr, flush=True)
    summary, done = {}, [0]

    def work(job):
        base, sym, months = job
        path = os.path.join(RAW, f"{sym}.csv.gz")
        if os.path.exists(path):                      # возобновляемость
            with gzip.open(path, "rt", encoding="utf-8") as f:
                rows = [
                    (int(datetime.fromisoformat(r[0]).timestamp() * 1000),
                     int(r[1]), float(r[2]))
                    for r in list(csv.reader(f))[1:]
                ]
            absent, bad = [], []
        else:
            rows, absent, bad = collect_symbol(sym, months)
            write_symbol(sym, rows)
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"  {done[0]}/{len(jobs)}", file=sys.stderr, flush=True)
        return base, sym, rows, absent, bad

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for base, sym, rows, absent, bad in ex.map(work, jobs):
            s = summarize(rows)
            s.update({"binance_symbol": sym, "months_absent": absent, "months_bad": bad})
            summary[base] = s

    doc = {
        "meta": {
            "source": "binance public archive (fundingRate, monthly)",
            "purpose": "мера расхождения между площадками и перекрёстная проверка; "
                       "издержки считаются по ставкам площадки исполнения",
            "universe_as_of": manifest["archive_as_of"],
            "assets_loaded": len(summary),
            "pilot_limit": args.limit or None,
            "complete": not args.limit,
        },
        "assets": summary,
    }
    suffix = f"_pilot{args.limit}" if args.limit else ""
    with open(os.path.join(OUT, f"funding_binance_summary{suffix}.json"), "w",
              encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)

    recs = sum(v["records"] for v in summary.values())
    nonzero = [v for v in summary.values() if v["records"]]
    print(json.dumps({
        "assets": len(summary),
        "records": recs,
        "assets_without_data": len(summary) - len(nonzero),
        "months_absent": sum(len(v["months_absent"]) for v in summary.values()),
        "months_bad": sum(len(v["months_bad"]) for v in summary.values()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
