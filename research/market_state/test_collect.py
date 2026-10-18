#!/usr/bin/env python3
"""Сборщик состояния рынка: разборы ответов площадок в форме зонда nb43,
продление ряда по часам (а не по файлу), покрытие числом, имя каталога
Binance берётся из ответа, события не дублируются, прогон с подставной
сетью пишет строки по суткам ИХ времени, отказ источника — причина в
`errors`, не тишина. Подделка доказывается до проверки."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import collect as C                                          # noqa: E402

BB_RATIO = {"retCode": 0, "result": {"list": [
    {"symbol": "BTCUSDT", "buyRatio": "0.6329", "sellRatio": "0.3671", "timestamp": "1792317600000"},
    {"symbol": "BTCUSDT", "buyRatio": "0.6302", "sellRatio": "0.3698", "timestamp": "1792314000000"}]}}
BN_RATIO = [{"symbol": "BTCUSDT", "longAccount": "0.6274", "longShortRatio": "1.6838",
             "shortAccount": "0.3726", "timestamp": 1792314000000},
            {"symbol": "BTCUSDT", "longAccount": "0.6251", "longShortRatio": "1.6674",
             "shortAccount": "0.3749", "timestamp": 1792310400000}]
OKX_RATIO = {"code": "0", "data": [["1792317600000", "1.71"], ["1792314000000", "1.73"]]}


def test_parsers_match_probe_shapes():
    r = C.parse_bybit_ratio(BB_RATIO)
    assert [x["t"] for x in r] == [1792314000000, 1792317600000], "по возрастанию времени"
    assert r[-1]["long"] == 0.6329 and r[-1]["short"] == 0.3671
    b = C.parse_binance_ratio(BN_RATIO)
    assert b[-1] == {"t": 1792314000000, "long": 0.6274}
    o = C.parse_okx_ratio(OKX_RATIO)
    assert o[-1] == {"t": 1792317600000, "ls": 1.71}
    names = C.parse_bybit_names({"result": {"list": [
        {"symbol": "BTCUSDT", "baseCoin": "BTC", "status": "Trading"},
        {"symbol": "BTCPERP", "baseCoin": "BTC", "status": "Trading"},
        {"symbol": "OLDUSDT", "baseCoin": "OLD", "status": "Closed"}]}})
    assert names == {"BTCUSDT": "BTC"}, names
    bn = C.parse_binance_names({"symbols": [
        {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDT"},
        {"symbol": "BTCUSDT_261226", "contractType": "CURRENT_QUARTER", "status": "TRADING", "quoteAsset": "USDT"},
        {"symbol": "BTCUSDC", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDC"}]})
    assert bn == {"BTCUSDT"}
    ok = C.parse_okx_ccys({"data": [{"instId": "BTC-USDT-SWAP", "state": "live"},
                                    {"instId": "BTC-USD-SWAP", "state": "live"},
                                    {"instId": "X-USDT-SWAP", "state": "suspend"}]})
    assert ok == {"BTC"}
    assert C.parse_bybit_ratio({"retCode": 10001}) == [] and C.parse_okx_ratio({}) == []
    assert C.skew(0.6329) == 13.3 and C.skew(None) is None
    print("ok  разборы: Bybit/Binance/OKX в форме зонда nb43, по времени, мусор — пусто")


def test_market_and_events_take_names_from_the_answer():
    m = C.parse_market(
        fng={"data": [{"value": "53", "value_classification": "Neutral"}]},
        cg={"data": {"market_cap_percentage": {"btc": 57.123}, "total_market_cap": {"usd": 2.5e12},
                     "market_cap_change_percentage_24h_usd": -1.234}},
        ins={"result": {"list": [{"coin": "USDT", "balance": "2663688.33"}, {"coin": "USDC", "balance": "5"}]}},
        stables={"peggedAssets": [{"symbol": "USDT", "price": 1.0003, "circulating": {"peggedUSD": 1.8e11}},
                                  {"symbol": "USDC", "price": 0.9998, "circulating": {"peggedUSD": 6e10}}]})
    assert m["fng"] == 53 and m["btc_dom"] == 57.12 and m["mcap_24h_pct"] == -1.23
    assert m["insurance_usdt"] == 2663688 and m["stables_usd"] == 240000000000
    assert m["stable_px"] == {"USDT": 1.0003, "USDC": 0.9998}
    assert C.parse_market() == {}, "ничего не пришло — ничего не выдумано"
    ev = C.parse_binance_events({"data": {"catalogs": [
        {"catalogId": 161, "catalogName": "Delisting",
         "articles": [{"code": "abc", "title": "Binance Will Delist X", "releaseDate": 1792300000000}]}]}})
    assert ev == [{"id": "binance:abc", "src": "binance", "t": 1792300000000,
                   "title": "Binance Will Delist X", "kind": "Delisting"}], ev
    bb = C.parse_bybit_events({"result": {"list": [
        {"title": "New Listing: FOO", "url": "https://announcements.bybit.com/x", "dateTimestamp": 1792300000000,
         "type": {"key": "new_crypto", "title": "New Listings"}, "tags": ["Spot", "Derivatives"]}]}})
    assert bb[0]["kind"] == "new_crypto" and bb[0]["id"].startswith("bybit:https")
    hk = C.parse_hacks([{"date": 1792200000, "name": "P", "classification": "Bridge", "amount": 1e6},
                        {"date": 1600000000, "name": "Old"}], since_s=1792000000)
    assert len(hk) == 1 and hk[0]["kind"] == "hack"
    print("ok  рынок и события: имя каталога — из ответа, нет данных — нет поля, старые взломы отсечены")


def test_rows_extend_by_time_and_coverage_is_a_number():
    rows = C.parse_bybit_ratio(BB_RATIO)
    assert [r["t"] for r in C.new_rows(rows, 1792314000000)] == [1792317600000]
    assert C.new_rows(rows, None) == rows and C.new_rows(rows, 1792317600000) == []
    assert C.day_of(1792317600000) == "2026-10-18"
    assert C.coverage(3, 4) == {"got": 3, "of": 4, "pct": 75.0}
    assert C.coverage(0, 0)["pct"] is None, "нет имён — не 0 %, а прочерк"
    print("ok  ряд продлевается по часам, сутки — по времени точки, покрытие — число или прочерк")


def _fake_get(urls_seen):
    def get(url):
        urls_seen.append(url)
        p = url.split("?")[0]
        if p.endswith("instruments-info"):
            return {"result": {"list": [{"symbol": "BTCUSDT", "baseCoin": "BTC", "status": "Trading"},
                                        {"symbol": "ETHUSDT", "baseCoin": "ETH", "status": "Trading"},
                                        {"symbol": "ONLYBBUSDT", "baseCoin": "ONLYBB", "status": "Trading"}]}}
        if p.endswith("/v5/market/account-ratio"):
            if "ONLYBB" in url:
                raise RuntimeError("HTTP 500: ratio")
            return BB_RATIO
        if p.endswith("exchangeInfo"):
            return {"symbols": [{"symbol": "BTCUSDT", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDT"},
                                {"symbol": "ETHUSDT", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDT"}]}
        if "LongShort" in p:
            return BN_RATIO
        if p.endswith("public/instruments"):
            return {"data": [{"instId": "BTC-USDT-SWAP", "state": "live"}]}
        if p.endswith("long-short-account-ratio"):
            return OKX_RATIO
        if "fng" in p:
            return {"data": [{"value": "53", "value_classification": "Neutral"}]}
        if p.endswith("/global"):
            raise RuntimeError("HTTP 429: cg")
        if p.endswith("insurance"):
            return {"result": {"list": [{"coin": "USDT", "balance": "100"}]}}
        if "stablecoins" in p:
            return {"peggedAssets": []}
        if p.endswith("trending"):
            return {"coins": [{"item": {"symbol": "minter"}}]}
        if p.endswith("announcements/index"):
            return {"result": {"list": [{"title": "A", "url": "u1", "dateTimestamp": 1792317600000, "type": {"key": "k"}}]}}
        if "cms" in p:
            return {"data": {"catalogs": []}}
        if p.endswith("/hacks"):
            return []
        raise RuntimeError("неизвестный адрес " + p)
    return get


def test_run_with_fake_network_writes_by_day_and_names_failures():
    C.PACE = {k: (1, 0.0) for k in C.PACE}
    with tempfile.TemporaryDirectory() as d:
        rec = os.path.join(d, "record")
        seen = []
        logs = []
        C.LATEST, C.REPORT = os.path.join(d, "latest.json"), os.path.join(d, "r.md")
        s = C.run(get=_fake_get(seen), log=logs.append, hist_path=os.path.join(rec, "hist.json"),
                  seen_path=os.path.join(rec, "seen.json"), record_dir=rec)
        assert s["coverage"]["bybit"] == {"got": 2, "of": 3, "pct": 66.7}, s["coverage"]
        assert s["coverage"]["binance"]["got"] == 2 and s["coverage"]["binance"]["absent"] == 1
        assert s["coverage"]["okx"]["got"] == 1 and s["coverage"]["okx"]["absent"] == 2
        assert any("ONLYBBUSDT" in e for e in s["errors"]) and any(e.startswith("cg:") for e in s["errors"])
        assert s["market"]["fng"] == 53 and "btc_dom" not in s["market"] and s["market"]["trending"] == ["MINTER"]
        assert s["names"]["BTCUSDT"]["bb_long"] == 0.6329 and s["names"]["BTCUSDT"]["okx_ls"] == 1.71
        assert s["names"]["ETHUSDT"]["bn_top"] == 0.6274 and "okx_ls" not in s["names"]["ETHUSDT"]
        assert s["most_long"] and s["most_short"]
        assert any("limit=500" in u and "account-ratio" in u for u in seen), "первый запуск докачивает историю"
        files = sorted(os.listdir(rec))
        assert "state-2026-10-18.jsonl" in files and "hist.json" in files, files
        rows = [json.loads(x) for f in files if f.startswith("state-")
                for x in open(os.path.join(rec, f), encoding="utf-8")]
        assert s["rows"] == len(rows) and len(rows) > 0
        kinds = {r["src"] for r in rows}
        assert {"bybit", "bn_global", "bn_top", "okx", "market", "event"} <= kinds, kinds
        bb_rows = [r for r in rows if r["src"] == "bybit"]
        assert len(bb_rows) == 4                                   # по 2 точки на 2 имени
        assert s["backfill"] == 6, "докачка: по 1 лишней точке у 2 имён Bybit и 2×2 рядов Binance"
        hist = json.load(open(os.path.join(rec, "hist.json"), encoding="utf-8"))
        assert hist["BTCUSDT"]["bybit"] == 1792317600000
        assert os.path.exists(C.LATEST)
        rep = open(C.REPORT, encoding="utf-8").read()
        assert "| bybit | 2 | 3 | 66.7 |" in rep and "Отказы:" in rep, rep
        # второй запуск: тот же ответ площадки — новых точек нет, лимит уже 1, событие не дублируется
        seen.clear()
        s2 = C.run(get=_fake_get(seen), log=logs.append, hist_path=os.path.join(rec, "hist.json"),
                   seen_path=os.path.join(rec, "seen.json"), record_dir=rec)
        assert any("account-ratio" in u and "limit=1" in u for u in seen) and \
            not any("account-ratio" in u and "limit=500" in u and "ONLYBB" not in u for u in seen)
        assert s2["coverage"]["bybit"]["got"] == 2, "покрытие — ответила ли площадка, не новизна точки"
        rows2 = [json.loads(x) for f in sorted(os.listdir(rec)) if f.startswith("state-")
                 for x in open(os.path.join(rec, f), encoding="utf-8")]
        assert sum(1 for r in rows2 if r["src"] == "event") == 1, "событие записано однажды"
        assert sum(1 for r in rows2 if r["src"] == "bybit") == 4, "старые точки не переписаны"
        assert s2["backfill"] == 0
    print("ok  прогон: строки по суткам точки, докачка один раз, событие однажды, отказы по именам и источникам названы")


if __name__ == "__main__":
    test_parsers_match_probe_shapes()
    test_market_and_events_take_names_from_the_answer()
    test_rows_extend_by_time_and_coverage_is_a_number()
    test_run_with_fake_network_writes_by_day_and_names_failures()
    print("\nвсе 4 проверки прошли")
