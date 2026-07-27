#!/usr/bin/env python3
"""
A1 — сбор того, что доступно только через API v5 Bybit.

**Запускается владельцем оттуда, где Bybit открыт.** Из окружения разработки
`api.bybit.com`, `api.bytick.com`, `api.bybit.nl`, `api.byhkbit.com` и testnet
отдают 403 CloudFront со страновым блоком; смена домена не помогает.

Собирает три вещи, без которых нельзя считать экономику сделки:

1. **История ставок funding** — раздел 5.2 спеки 02. Строго с площадки
   исполнения: ставки между площадками по одному активу расходятся, а при
   удержании 3–5 дней funding составляет значимую часть P&L. Брать их с
   Binance — самый вероятный способ получить красивый и недостоверный
   результат.
2. **Справочник инструментов** — шаг цены и объёма, минимальный нотионал.
   Без них нельзя проверить сайзинг раздела 4 спеки 01: после округления
   количеств β проверяется повторно, и на мелких размерах округление
   заметно искажает хедж.
3. **Ставки комиссий** — раздел 5.1, базовый тир. Требует ключа API;
   без ключа шаг пропускается, а не подменяется числом из памяти.

Что кладётся в git, а что нет: справочник и сводка по funding маленькие
и коммитятся, сами ряды funding — нет (см. `.gitignore`). Хранилище
исследования — предмет этапа A2, а не git.

Запуск:

    python3 bybit_api.py --symbol BTCUSDT   # смоук-тест на одном символе
    python3 bybit_api.py                    # funding + справочник
    python3 bybit_api.py --with-fees        # ещё и комиссии, нужен ключ
                                            # BYBIT_API_KEY / BYBIT_API_SECRET

Начинать стоит со смоук-теста: пагинация funding написана вслепую, из
песочницы разработки API недоступен. По BTCUSDT за полный срок жизни
должно прийти порядка 6–7 тысяч записей с шагом 8 часов без разрывов.

Прогон возобновляемый: готовые символы пропускаются, сеть кэшируется.
Только stdlib.
"""

import csv
import gzip
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache_api")
FUNDING_DIR = os.path.join(OUT, "funding")

sys.path.insert(0, RESEARCH)
from common.venue import fetch as _fetch  # noqa: E402

API = "https://api.bybit.com"
CATEGORY = "linear"
FUNDING_LIMIT = 200          # максимум записей на ответ у эндпоинта
WORKERS = 4                  # вежливо к лимитам площадки
PAUSE_S = 0.05


def api_get(path, params, cache_key):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    raw = _fetch(url, CACHE, cache_key=cache_key, user_agent="a1-bybit/1.0")
    doc = json.loads(raw)
    if doc.get("retCode") != 0:
        raise RuntimeError(f"{path}: retCode={doc.get('retCode')} {doc.get('retMsg')}")
    return doc["result"]


# ------------------------------------------------------------ справочник

def collect_instruments():
    """Полный справочник линейных контрактов, включая неторгуемые сейчас."""
    out, cursor, page = {}, "", 0
    while True:
        params = {"category": CATEGORY, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        res = api_get("/v5/market/instruments-info", params, f"instr_{page}")
        for it in res.get("list", []):
            pf = it.get("priceFilter", {})
            lf = it.get("lotSizeFilter", {})
            out[it["symbol"]] = {
                "symbol": it["symbol"],
                "base_coin": it.get("baseCoin"),
                "quote_coin": it.get("quoteCoin"),
                "status": it.get("status"),
                "launch_time": it.get("launchTime"),
                "delivery_time": it.get("deliveryTime"),
                "tick_size": pf.get("tickSize"),
                "qty_step": lf.get("qtyStep"),
                "min_order_qty": lf.get("minOrderQty"),
                "max_order_qty": lf.get("maxOrderQty"),
                "min_notional_value": lf.get("minNotionalValue"),
                "funding_interval_min": it.get("fundingInterval"),
                "settle_coin": it.get("settleCoin"),
            }
        cursor = res.get("nextPageCursor") or ""
        page += 1
        if not cursor:
            break
    return out


# --------------------------------------------------------------- funding

def _ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def collect_funding_symbol(symbol, start_day, end_day):
    """Вся история funding по символу. Эндпоинт отдаёт назад во времени."""
    rows, cursor_end, guard = [], _ms(end_day) + 86_400_000, 0
    start_ms = _ms(start_day)

    while cursor_end > start_ms and guard < 500:
        guard += 1
        res = api_get(
            "/v5/market/funding/history",
            {
                "category": CATEGORY,
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": cursor_end,
                "limit": FUNDING_LIMIT,
            },
            f"fund_{symbol}_{cursor_end}",
        )
        batch = res.get("list", [])
        if not batch:
            break
        for r in batch:
            rows.append((int(r["fundingRateTimestamp"]), r["fundingRate"]))
        oldest = min(int(r["fundingRateTimestamp"]) for r in batch)
        if oldest >= cursor_end:
            break
        cursor_end = oldest - 1
        if len(batch) < FUNDING_LIMIT:
            break
        time.sleep(PAUSE_S)

    dedup = sorted(set(rows))
    return [(datetime.fromtimestamp(t / 1000, timezone.utc).isoformat(), r) for t, r in dedup]


def write_funding(symbol, rows):
    os.makedirs(FUNDING_DIR, exist_ok=True)
    path = os.path.join(FUNDING_DIR, f"{symbol}.csv.gz")
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["funding_time", "funding_rate"])
        w.writerows(rows)
    return path


def summarize(symbol, rows):
    vals = [float(r) for _, r in rows]
    if not vals:
        return {"symbol": symbol, "records": 0}
    return {
        "symbol": symbol,
        "records": len(vals),
        "first": rows[0][0],
        "last": rows[-1][0],
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
        # Годовая доля при трёх начислениях в сутки — грубый ориентир
        # порядка величины, а не оценка доходности.
        "annualized_mean_pct": sum(vals) / len(vals) * 3 * 365 * 100,
    }


# ------------------------------------------------------------- комиссии

def collect_fees():
    """Ставки комиссий по ключу API. Раздел 5.1: из живого API, не по памяти."""
    key = os.environ.get("BYBIT_API_KEY")
    secret = os.environ.get("BYBIT_API_SECRET")
    if not (key and secret):
        print("BYBIT_API_KEY / BYBIT_API_SECRET не заданы — комиссии пропущены",
              file=sys.stderr)
        return None

    ts = str(int(time.time() * 1000))
    recv, query = "5000", f"category={CATEGORY}"
    sign = hmac.new(
        secret.encode(), f"{ts}{key}{recv}{query}".encode(), hashlib.sha256
    ).hexdigest()

    req = urllib.request.Request(
        f"{API}/v5/account/fee-rate?{query}",
        headers={
            "X-BAPI-API-KEY": key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": recv,
            "X-BAPI-SIGN": sign,
        },
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        doc = json.loads(r.read().decode())
    if doc.get("retCode") != 0:
        raise RuntimeError(f"fee-rate: {doc.get('retMsg')}")
    return doc["result"].get("list", [])


def preflight():
    """Проверить доступ до начала сбора и объяснить отказ по-человечески."""
    try:
        api_get("/v5/market/time", {}, "preflight_time")
    except Exception as e:
        msg = str(e)
        if "403" in msg:
            print(
                "\nBybit не отвечает: 403 — страновой блок CloudFront.\n"
                "Это не ошибка ключа и не опечатка: площадка закрывает доступ\n"
                "по местоположению. Скрипт нужно запустить оттуда, где Bybit\n"
                "открыт. Смена домена не помогает — api.bytick.com, api.bybit.nl\n"
                "и api.byhkbit.com отвечают тем же 403.\n",
                file=sys.stderr,
            )
        else:
            print(f"\nBybit недоступен: {msg}\n", file=sys.stderr)
        raise SystemExit(1)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    preflight()

    with open(os.path.join(OUT, "universe.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    print("справочник инструментов...", file=sys.stderr, flush=True)
    instruments = collect_instruments()
    with open(os.path.join(OUT, "instruments.json"), "w", encoding="utf-8") as f:
        json.dump(instruments, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"  {len(instruments)} контрактов", file=sys.stderr, flush=True)

    # Только символы универсума и только за их срок жизни: тянуть funding
    # за периоды, когда инструмент не торговался, незачем.
    targets = []
    for rec in manifest["assets"].values():
        if not rec["binance_symbol"]:
            continue
        targets.append((
            rec["bybit_symbol"],
            date.fromisoformat(rec["listed"]),
            date.fromisoformat(rec["last_trading_day"]),
        ))
    targets.sort()

    # Дешёвая проверка перед многочасовым прогоном: пагинация funding
    # написана вслепую — из песочницы API недоступен, — поэтому убедиться,
    # что по одному символу приходит связная история, стоит заранее.
    only = None
    for i, a in enumerate(sys.argv):
        if a == "--symbol" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1].upper()
    if only:
        targets = [t for t in targets if t[0] == only]
        if not targets:
            raise SystemExit(f"{only} нет в универсуме")
    elif "--limit" in sys.argv:
        n = int(sys.argv[sys.argv.index("--limit") + 1])
        targets = targets[:n]

    print(f"funding по {len(targets)} символам...", file=sys.stderr, flush=True)

    summary, done = {}, [0]

    def work(item):
        sym, a, b = item
        path = os.path.join(FUNDING_DIR, f"{sym}.csv.gz")
        if os.path.exists(path):                      # возобновляемость
            with gzip.open(path, "rt", encoding="utf-8") as f:
                rows = [tuple(r) for r in csv.reader(f)][1:]
        else:
            rows = collect_funding_symbol(sym, a, b)
            write_funding(sym, rows)
        done[0] += 1
        if done[0] % 25 == 0:
            print(f"  funding {done[0]}/{len(targets)}", file=sys.stderr, flush=True)
        return sym, rows

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for sym, rows in ex.map(work, targets):
            summary[sym] = summarize(sym, rows)

    with open(os.path.join(OUT, "funding_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, sort_keys=True)

    if "--with-fees" in sys.argv:
        fees = collect_fees()
        if fees is not None:
            with open(os.path.join(OUT, "fees.json"), "w", encoding="utf-8") as f:
                json.dump(fees, f, ensure_ascii=False, indent=1, sort_keys=True)

    empty = [s for s, v in summary.items() if not v["records"]]
    print(json.dumps({
        "instruments": len(instruments),
        "funding_symbols": len(summary),
        "funding_records": sum(v["records"] for v in summary.values()),
        "symbols_without_funding": len(empty),
    }, ensure_ascii=False, indent=2))
    if empty:
        print("без данных funding: " + ", ".join(sorted(empty)[:20]), file=sys.stderr)


if __name__ == "__main__":
    main()
