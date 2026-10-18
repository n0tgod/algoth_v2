#!/usr/bin/env python3
"""Зонд внешних источников для спеки 19 — доступны ли они С СЕРВЕРА.

Из сессии ассистента Bybit и Binance закрыты по географии (CloudFront 403,
Binance 451), и судить о доступности источников оттуда нельзя. Этот зонд
ходит по объявленному списку публичных адресов (без ключей) с сервера и
печатает код ответа, время и первые знаки тела — чтобы каталог критериев
спеки 19 опирался на факт, а не на предположение. Только чтение, ничего
не пишет.

    run tools/source_probe.py
"""
import json
import sys
import time
import urllib.error
import urllib.request

SOURCES = [
    ("bybit account-ratio (лонг/шорт по аккаунтам, монета)",
     "https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=BTCUSDT&period=1h&limit=2"),
    ("bybit open-interest (OI, монета, час)",
     "https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1h&limit=2"),
    ("bybit tickers (OI value, funding, 24h, все имена одним ответом)",
     "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"),
    ("bybit funding history", "https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT&limit=2"),
    ("bybit insurance (страховой фонд)", "https://api.bybit.com/v5/market/insurance?coin=USDT"),
    ("bybit announcements (листинги/делистинги)",
     "https://api.bybit.com/v5/announcements/index?locale=en-US&limit=2"),
    ("binance global long/short accounts",
     "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=2"),
    ("binance top traders long/short positions",
     "https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=1h&limit=2"),
    ("binance taker buy/sell ratio",
     "https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=2"),
    ("binance open interest hist",
     "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=2"),
    ("binance announcements (CMS)",
     "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=2&catalogId=48"),
    ("okx long/short ratio", "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H"),
    ("okx taker volume", "https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1H"),
    ("fear & greed", "https://api.alternative.me/fng/?limit=1"),
    ("coingecko trending", "https://api.coingecko.com/api/v3/search/trending"),
    ("coingecko global (доминация BTC)", "https://api.coingecko.com/api/v3/global"),
    ("defillama hacks", "https://api.llama.fi/hacks"),
    ("defillama stablecoins", "https://stablecoins.llama.fi/stablecoins?includePrices=false"),
    ("coindesk rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph rss", "https://cointelegraph.com/rss"),
    ("theblock rss", "https://www.theblock.co/rss.xml"),
    ("cryptopanic (нужен ключ — ждём 4xx)", "https://cryptopanic.com/api/v1/posts/?public=true"),
    ("anthropic api (без ключа — ждём 401, значит достижим)", "https://api.anthropic.com/v1/models"),
]


def probe(url):
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "algoth-probe/1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read(400)
            return r.status, round(time.time() - t0, 2), body
    except urllib.error.HTTPError as e:
        return e.code, round(time.time() - t0, 2), e.read(300)
    except Exception as e:                                   # noqa: BLE001
        return None, round(time.time() - t0, 2), f"{type(e).__name__}: {e}".encode()


def main():
    out = []
    for name, url in SOURCES:
        code, sec, body = probe(url)
        txt = body.decode("utf-8", "replace").replace("\n", " ").strip()[:200]
        print(f"{name}\n  {url.split('?')[0]}\n  код {code}, {sec} с: {txt}\n")
        out.append({"name": name, "url": url, "code": code, "sec": sec, "head": txt})
    ok = sum(1 for o in out if o["code"] and 200 <= o["code"] < 300)
    print(f"итого отвечают 2xx: {ok} из {len(out)}")
    print(json.dumps(out, ensure_ascii=False)[:100])
    return 0


if __name__ == "__main__":
    sys.exit(main())
