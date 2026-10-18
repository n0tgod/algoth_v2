#!/usr/bin/env python3
"""Сборщик новостей: разбор RSS в форме живых лент (пространства имён,
CDATA с разметкой, рубрики), привязка к монетам тремя способами со
стоп-словами и множителями Bybit, календарь в UTC по правилу летнего
времени США и правилу Deribit, прогон с подставной сетью — запись по суткам
новости, повтор не пишется, отказ ленты назван. Подделка — литерал."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import collect as N                                          # noqa: E402
import macro_cal as CAL                                      # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<title>Feed</title>
<item><title><![CDATA[Pepe and $WIF rally as SEC delays ETF; ONE more thing]]></title>
<link>https://example.com/a1</link><guid isPermaLink="false">a1</guid>
<pubDate>Sun, 18 Oct 2026 13:54:00 +0000</pubDate>
<description><![CDATA[<p>Short &amp; sweet</p>]]></description>
<content:encoded><![CDATA[<p>Traders bought <b>PEPE</b> while Solana &amp; the AI sector cooled.</p>]]></content:encoded>
<dc:creator>X</dc:creator><category>Markets</category><category>Memecoins</category></item>
<item><title>Bitcoin hashrate record</title><link>https://example.com/a2</link>
<pubDate>Sat, 17 Oct 2026 23:59:59 -0100</pubDate><description>Miners &lt;b&gt;grow&lt;/b&gt;</description></item>
<item><title>no date</title><link>https://example.com/a3</link></item>
</channel></rss>"""

INSTR = {"1000PEPEUSDT": {"base_coin": "1000PEPE", "status": "Trading"},
         "WIFUSDT": {"base_coin": "WIF", "status": "Trading"},
         "SOLUSDT": {"base_coin": "SOL", "status": "Trading"},
         "BTCUSDT": {"base_coin": "BTC", "status": "Trading"},
         "ONEUSDT": {"base_coin": "ONE", "status": "Trading"},
         "OLDUSDT": {"base_coin": "OLD", "status": "Closed"},
         "BTCPERP": {"base_coin": "BTC", "status": "Trading"}}
CG = [{"symbol": "btc", "name": "Bitcoin"}, {"symbol": "sol", "name": "Solana"},
      {"symbol": "pepe", "name": "Pepe"}, {"symbol": "xyz", "name": "Not On Bybit"},
      {"symbol": "one", "name": "Harmony"}]


def test_parse_rss_like_live_feeds():
    items = N.parse_rss(RSS, "cd")
    assert len(items) == 2, "запись без даты пропущена"
    a = items[0]
    assert a["id"] == "cd:https://example.com/a1" and a["t"] == 1792331640000
    assert a["title"] == "Pepe and $WIF rally as SEC delays ETF; ONE more thing"
    assert a["text"] == "Traders bought PEPE while Solana & the AI sector cooled.", a["text"]
    assert a["cats"] == ["Markets", "Memecoins"]
    b = items[1]
    assert b["t"] == int(datetime(2026, 10, 18, 0, 59, 59, tzinfo=timezone.utc).timestamp() * 1000), "пояс −0100"
    assert b["text"] == "Miners grow"
    print("ok  RSS: пространства имён, CDATA и разметка сняты, пояс даты учтён, без даты — пропуск")


def test_tagging_three_ways_with_stopwords_and_multipliers():
    tk = N.bybit_tickers(INSTR)
    assert tk["PEPE"] == ["1000PEPEUSDT"] and "OLD" not in tk and tk["BTC"] == ["BTCUSDT"]
    nm = N.names_map(CG, tk)
    assert nm == {"bitcoin": "BTC", "solana": "SOL", "harmony": "ONE"}, nm   # Pepe = тикер, имя не нужно
    a = N.parse_rss(RSS, "cd")[0]
    t = N.tag(a, tk, nm)
    assert t == {"WIFUSDT": "cash", "1000PEPEUSDT": "word", "SOLUSDT": "name"}, t
    assert "ONEUSDT" not in t, "ONE — стоп-слово, Harmony в тексте нет"
    b = N.parse_rss(RSS, "cd")[1]
    assert N.tag(b, tk, nm) == {"BTCUSDT": "name"}
    assert N.tag({"title": "bitcoinx and solanaland", "text": ""}, tk, nm) == {}, "имя — целым словом"
    tk2 = dict(tk, GENIUS=["GENIUSUSDT"])
    assert N.tag({"title": "adviser helped pass the GENIUS Act", "text": ""}, tk2, nm) == {}, "закон — не монета"
    assert N.tag({"title": "$GENIUS lists", "text": ""}, tk2, nm) == {"GENIUSUSDT": "cash"}, "кэштег сильнее стоп-слова"
    print("ok  привязка: $тикер, ТИКЕР словом без стоп-слов, имя проекта целым словом; 1000PEPE → PEPE")


def test_calendar_utc_by_us_dst_rule_and_deribit():
    assert CAL.ny_to_utc("2026-10-28", 14, 0).strftime("%H:%M") == "18:00", "28.10 — ещё летнее время"
    assert CAL.ny_to_utc("2026-12-09", 14, 0).strftime("%H:%M") == "19:00"
    assert CAL.ny_to_utc("2026-11-10", 8, 30).strftime("%H:%M") == "13:30"
    assert str(CAL.last_friday(2026, 10)) == "2026-10-30" and str(CAL.last_friday(2026, 12)) == "2026-12-25"
    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    up = CAL.upcoming(now, 48)
    assert [e["kind"] for e in up] == ["fomc"] and up[0]["t"] == "2026-10-28T18:00Z", up
    up = CAL.upcoming(datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc), 48)
    assert up and up[0]["kind"] == "expiry" and up[0]["t"] == "2026-10-30T08:00Z" and "monthly" in up[0]["title"]
    assert "quarterly" in CAL.events(datetime(2026, 12, 1, tzinfo=timezone.utc),
                                     datetime(2026, 12, 31, tzinfo=timezone.utc))[-1]["title"]
    print("ok  календарь: ФРС и CPI в UTC по правилу летнего времени США, экспирации — последняя пятница 08:00")


def test_run_with_fake_network():
    with tempfile.TemporaryDirectory() as d:
        ip = os.path.join(d, "instr.json")
        json.dump(INSTR, open(ip, "w"))
        rec = os.path.join(d, "record")
        N.LATEST, N.REPORT = os.path.join(d, "latest.json"), os.path.join(d, "r.md")
        calls = []

        def get(url):
            calls.append(url)
            if "coingecko" in url:
                return json.dumps(CG if "page=1" in url else [])
            if "coindesk" in url:
                return RSS
            if "cointelegraph" in url:
                raise RuntimeError("HTTP 403")
            return "<rss><channel></channel></rss>"
        now = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
        s = N.run(get=get, log=lambda *_: None, record=rec, instruments_path=ip, now=now)
        assert s["new"] == 2 and s["feeds"]["coindesk"] == {"got": 2, "new": 2}
        assert s["feeds"]["cointelegraph"]["error"] == "HTTP 403"
        assert any(e.startswith("cointelegraph: HTTP 403") for e in s["errors"])
        assert any(e.startswith("theblock: ответ без статей") for e in s["errors"]), "живой ответ без статей — назван"
        assert s["day_items"] == 2 and s["day_tagged"] == 2
        assert s["headlines"][0]["tags"]["WIFUSDT"] == "cash"
        files = sorted(f for f in os.listdir(rec) if f.startswith("news-"))
        assert files == ["news-2026-10-18.jsonl"], files
        rep = open(N.REPORT, encoding="utf-8").read()
        assert "| coindesk | 2 | 2 |  |" in rep and "| cointelegraph | — | — | HTTP 403 |" in rep, rep
        s2 = N.run(get=get, log=lambda *_: None, record=rec, instruments_path=ip, now=now)
        assert s2["new"] == 0 and s2["day_items"] == 2, "повтор не пишется, сутки читаются из записи"
        assert sum(1 for _ in open(os.path.join(rec, files[0]), encoding="utf-8")) == 2
        assert sum(1 for u in calls if "coingecko" in u) == 2, "имена CoinGecko — раз в сутки, не каждый прогон"
    print("ok  прогон: запись по суткам новости, повтор не пишется, отказ и пустая лента названы, имена кэшируются")


if __name__ == "__main__":
    test_parse_rss_like_live_feeds()
    test_tagging_three_ways_with_stopwords_and_multipliers()
    test_calendar_utc_by_us_dst_rule_and_deribit()
    test_run_with_fake_network()
    print("\nвсе 4 проверки прошли")
