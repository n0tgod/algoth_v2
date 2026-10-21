#!/usr/bin/env python3
"""Контекст для досье судьи (спека 19): запись состояния рынка, новости,
ход цены с площадки, история имени в книге — до момента решения.

Одно место на сборку фона: сухой час (`dry_hour.py`) и запись вперёд
(`gate_run.py`) зовут эти функции, чтобы досье у них не разошлось.
Всё строго «до момента решения»: свечи с `end` = момент, толпа и события —
последняя строка не позже момента, новости — опубликованные не позже.
"""
import glob
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MS_RECORD = os.path.join(ROOT, "research", "market_state", "out", "record")
NEWS_RECORD = os.path.join(ROOT, "research", "news", "out", "record")
for _p in (os.path.join(ROOT, "research", "dca_paper"), os.path.join(ROOT, "research", "news"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
KLINE = "https://api.bybit.com/v5/market/kline?category=linear&symbol={s}&interval=60&end={e}&limit=170"
H = 3600


def klines(sym, at_s):
    """{начало часа с: close} за 7 суток до решения; отказ — None."""
    try:
        req = urllib.request.Request(KLINE.format(s=sym, e=int(at_s * 1000)), headers={"User-Agent": "algoth-ai/1"})
        doc = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return {int(r[0]) // 1000: float(r[4]) for r in (doc.get("result") or {}).get("list") or []}
    except Exception:                                        # noqa: BLE001
        return None


def load_state(days, syms=None):
    """Запись состояния рынка → {sym: {src: [(t, row)]}}, рынок и события.
    `syms` — только эти имена (поиск ТВХ, 21.10: 40 суток всех имён — гигабайты)."""
    want = set(syms) if syms is not None else None
    by, market, events = {}, [], []
    for p in sorted(glob.glob(os.path.join(MS_RECORD, "state-*.jsonl")))[-days:]:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("src") == "market":
                    market.append(r)
                elif r.get("src") == "event":
                    events.append(r)
                elif want is None or r.get("sym") in want:
                    by.setdefault(r.get("sym"), {}).setdefault(r["src"], []).append(r)
    for d in by.values():
        for v in d.values():
            v.sort(key=lambda r: r["t"])
    market.sort(key=lambda r: r["t"])
    return by, market, events


def at_or_before(rows, t_ms):
    best = None
    for r in rows:
        if r["t"] <= t_ms:
            best = r
        else:
            break
    return best


def crowd_of(state, sym, t_ms):
    d = state.get(sym) or {}
    out = {}
    for src, key in (("bybit", "long"), ("bn_global", "long"), ("bn_top", "long"), ("okx", "ls")):
        now = at_or_before(d.get(src, []), t_ms)
        ago = at_or_before(d.get(src, []), t_ms - 24 * H * 1000)
        if now:
            out[src] = {"now": now.get(key), "24h_ago": ago.get(key) if ago else None,
                        "as_of": time.strftime("%m-%d %H:%M", time.gmtime(now["t"] / 1000))}
    return out or None


def events_for(events, sym, t_ms, since_ms=None):
    """События площадок и взломы с именем — в (since, t]; по умолчанию 72 ч до t."""
    base = sym[:-4] if sym.endswith("USDT") else sym
    lo = t_ms - 72 * H * 1000 if since_ms is None else since_ms + 1
    out = []
    for e in events:
        title = str(e.get("title") or "")
        if lo <= e["t"] <= t_ms and (sym in title or f" {base} " in f" {title} " or f"({base})" in title):
            out.append({"t": time.strftime("%Y-%m-%d %H:%M", time.gmtime(e["t"] / 1000)),
                        "venue": e.get("venue"), "kind": e.get("kind"), "title": title})
    return out


def load_news():
    items = []
    for p in sorted(glob.glob(os.path.join(NEWS_RECORD, "news-*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue
    return items


def history_of(recs, sym, at_s):
    prev = [r for r in recs if r.get("sym") == sym and float(r.get("at", 0)) < at_s]
    if not prev:
        return {"positions_before": 0}
    return {"positions_before": len(prev), "hit_floor": sum(1 for r in prev if r.get("exit") == "пол"),
            "last_entry_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(max(float(r["at"]) for r in prev)))}




def build(kind, r, book, side, now, recs, state, market_rows, events, news):
    """Досье и счёт покрытия: вход — на момент решения `at`, держание — на `now`.

    Возвращает (kwargs для judge.dossier без news, news, покрытие). Ветка без
    новостей получает те же kwargs с news=None — одна сборка на обе ветки.
    """
    import judge as J                                          # noqa: E402
    import macro_cal as CAL                                    # noqa: E402
    import wave as WV                                          # noqa: E402
    from datetime import datetime, timezone
    at_s = float(r["at"])
    ask_s = now if kind == "hold" else at_s
    t_ms = int(ask_s * 1000)
    px = J.moves(klines(r["sym"], ask_s) or {}, ask_s)
    btc = J.moves(klines("BTCUSDT", ask_s) or {}, ask_s)
    crowd = crowd_of(state, r["sym"], t_ms)
    mk = at_or_before(market_rows, t_ms)
    market = {"btc_moves": btc, **({k: mk[k] for k in ("fng", "btc_dom", "mcap_24h_pct", "insurance_usdt")
                                    if k in mk} if mk else {"note": "market slice not recorded at this time"})}
    ev = events_for(events, r["sym"], t_ms)
    hours = 72 if kind == "entry" else max(1, int((now - at_s) / H) + 1)
    nw = J.news_for(news, r["sym"], t_ms, hours=hours)
    since = None
    if kind == "hold":
        pth = WV.path_of(r) or {}
        cum = pth.get("cum") or {}
        since = {"hours_held": round((now - at_s) / H, 1),
                 "pnl_pct_of_margin": round(100 * cum[max(cum)], 2) if cum else None,
                 "entry_crowd": crowd_of(state, r["sym"], int(at_s * 1000))}
    kw = dict(px=px, crowd=crowd, market=market, history=history_of(recs, r["sym"], at_s),
              mkt_news=J.market_news(news, t_ms),
              calendar=CAL.upcoming(datetime.fromtimestamp(ask_s, tz=timezone.utc), 48),
              events=ev, since_entry=since)
    cov = {"px": bool(px), "crowd_bybit": bool(crowd and "bybit" in crowd),
           "crowd_binance": bool(crowd and "bn_global" in crowd), "news": bool(nw), "market": bool(mk)}
    return kw, nw, cov
