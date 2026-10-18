#!/usr/bin/env python3
"""Сборщик новостей (спека 19 §4, этап N1): RSS с привязкой к монетам.

Раз в 15 мин из сторожа: ленты CoinDesk, CoinTelegraph, The Block —
заголовок, время, текст (до 2 000 знаков, без разметки), ссылка, рубрики
и список НАШИХ имён, о которых новость. Объявления площадок и взломы сюда
не дублируются: их пишет сборщик состояния рынка (`market_state`, E1–E3),
судья читает обе записи — одна запись на источник.

Привязка к монетам (`tags`), три способа, каждый помечен — судья и сетка
видят, насколько привязка надёжна:
* `cash` — `$TIKER` в тексте;
* `word` — тикер ЗАГЛАВНЫМИ отдельным словом, от трёх букв, не из
  стоп-списка обычных слов («ONE», «ETF», «SEC» …);
* `name` — имя проекта по справочнику CoinGecko (первые 500 по
  капитализации), от четырёх букв, без учёта регистра.
Тикер переводится в символы Bybit (`PEPE` → `1000PEPEUSDT`) по
справочнику инструментов; тикер не на Bybit не пишется.

Запись `out/record/news-ГГГГ-ММ-ДД.jsonl` по суткам времени новости — вне
git (тексты чужих изданий в репозиторий не кладём); в git — сводка
`latest.json` (заголовки суток, счёт по лентам, отказы, календарь на 48 ч)
и отчёт. Отказ ленты — строка в `errors`, не тишина; лента, отдавшая ноль
новостей при живом ответе, — тоже строка.

    collect.py [--no-publish] [--dry]
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import macro_cal as CAL                                       # noqa: E402  (не calendar.py: перекрыл бы модуль Python)

OUT = os.path.join(HERE, "out")
RECORD = os.path.join(OUT, "record")
SEEN = os.path.join(RECORD, "seen.json")
NAMES = os.path.join(RECORD, "names.json")
LATEST = os.path.join(OUT, "latest.json")
REPORT = os.path.join(OUT, "NEWS-state.md")
INSTRUMENTS = os.path.join(ROOT, "research", "a1_universe", "out", "instruments.json")

FEEDS = [("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
         ("cointelegraph", "https://cointelegraph.com/rss"),
         ("theblock", "https://www.theblock.co/rss.xml")]
CG_MARKETS = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
              "&order=market_cap_desc&per_page=250&page={p}")
TEXT_MAX = 2000
NAMES_TTL_S = 86400
STALE_S = 45 * 60
NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
WORD_STOP = {
    "THE", "AND", "FOR", "ONE", "NEW", "CEO", "CFO", "CTO", "ETF", "ETFS", "SEC", "USD", "API", "NFT",
    "DAO", "GAS", "TOP", "WIN", "BIG", "KEY", "ACT", "MAX", "ALL", "NOT", "OUT", "NOW", "WHO", "WHY",
    "HOW", "ITS", "ARE", "WAS", "HAS", "BUT", "CAN", "GET", "SET", "RUN", "OPEN", "HIGH", "LOW", "FED",
    "CPI", "GDP", "IPO", "ATH", "TVL", "DEX", "CEX", "OTC", "ETH2", "USA", "UK", "EU", "FBI", "DOJ",
    "IRS", "CFTC", "FOMC", "AI", "L1", "L2", "DEFI", "MEME", "BULL", "BEAR", "HOLD", "MOVE", "SAFE",
    "REAL", "TRUE", "BAND", "LINK", "BOND", "GOLD", "SAND", "BLUR", "PEOPLE", "DOGS", "HYPE", "TRUMP",
    "LIVE", "PUMP", "TURBO", "BANK", "PRIME", "ZERO", "FREE", "FUN", "PLAY", "GAME", "TIME", "BOOK",
    "CAT", "DOG", "ALT", "ALTS", "WAVE", "STORY", "SIGN", "ME", "IP", "TAO", "OM", "S", "W", "G",
    "GENIUS", "CLARITY", "STABLE", "ACT",  # названия законов США о крипте (18.10: GENIUS Act лёг на монету)
}
NAME_STOP = {"story", "movement", "official", "sign", "wave", "safe", "people", "zero", "prime",
             "book", "pump", "hype", "turbo", "live", "game", "real", "play"}
MULT_RE = re.compile(r"^(?:1000000|100000|10000|1000|100)(?=[A-Z])")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def utc_now():
    return datetime.now(timezone.utc)


def http_text(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "algoth-news/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None
    except Exception as e:                                   # noqa: BLE001
        raise RuntimeError(type(e).__name__) from None


# ------------------------------------------------------------ разборы (чистые)

def clean(s):
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def parse_rss(text, src):
    """RSS 2.0 → [{id, src, t (мс UTC), title, text, link, cats}]; битая запись пропускается."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or "").strip()
        title = clean(it.findtext("title"))
        try:
            t = int(parsedate_to_datetime(it.findtext("pubDate") or "").timestamp() * 1000)
        except (TypeError, ValueError, IndexError):
            continue
        if not (link or guid) or not title:
            continue
        body = it.findtext("content:encoded", namespaces=NS) or it.findtext("description") or ""
        out.append({"id": f"{src}:{link or guid}", "src": src, "t": t, "title": title[:300],
                    "text": clean(body)[:TEXT_MAX], "link": link or guid,
                    "cats": [clean(c.text) for c in it.findall("category") if c.text][:8]})
    return out


def ticker_of(base):
    """База Bybit → тикер в тексте: 1000PEPE → PEPE."""
    return MULT_RE.sub("", base or "")


def bybit_tickers(instruments):
    """{тикер: [символы Bybit]} по торгуемым перпам USDT справочника."""
    m = {}
    for sym, it in (instruments or {}).items():
        if not sym.endswith("USDT") or it.get("status") != "Trading":
            continue
        t = ticker_of(it.get("base_coin") or sym[:-4])
        if t:
            m.setdefault(t, []).append(sym)
    return {k: sorted(v) for k, v in m.items()}


def names_map(cg_rows, tickers):
    """CoinGecko markets → {имя в нижнем регистре: тикер}, только тикеры с Bybit."""
    out = {}
    for c in cg_rows or []:
        sym = str(c.get("symbol") or "").upper()
        name = str(c.get("name") or "").strip()
        if sym in tickers and len(name) >= 4 and name.lower() not in NAME_STOP and name.upper() != sym:
            out.setdefault(name.lower(), sym)
    return out


def tag(item, tickers, names):
    """→ {символ Bybit: способ} — cash сильнее word сильнее name."""
    blob = item["title"] + " \n " + item["text"]
    found = {}
    rank = {"cash": 3, "word": 2, "name": 1}

    def put(t, how):
        for s in tickers.get(t, ()):
            if rank[how] > rank.get(found.get(s), 0):
                found[s] = how
    for m in re.finditer(r"\$([A-Za-z][A-Za-z0-9]{1,14})\b", blob):
        put(m.group(1).upper(), "cash")
    for m in re.finditer(r"(?<![A-Za-z0-9$])([A-Z][A-Z0-9]{2,14})(?![A-Za-z0-9])", blob):
        w = m.group(1)
        if w not in WORD_STOP:
            put(w, "word")
    low = blob.lower()
    for name, t in names.items():
        if name in low and re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low):
            put(t, "name")
    return found


def summarize(items_day, per_feed, errors, upcoming, t0, n_new, now_ms):
    day = [x for x in items_day if x["t"] >= now_ms - 86400 * 1000]
    day.sort(key=lambda x: -x["t"])
    cnt = Counter(s for x in day for s in x.get("tags", {}))
    return {"computed_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "secs": round(time.time() - t0, 1),
            "feeds": per_feed, "errors": errors, "new": n_new,
            "day_items": len(day), "day_tagged": sum(1 for x in day if x.get("tags")),
            "top_names": cnt.most_common(15),
            "headlines": [{"t": x["t"], "src": x["src"], "title": x["title"], "link": x["link"],
                           "tags": x.get("tags", {})} for x in day[:40]],
            "calendar_48h": upcoming}


def report_md(s):
    L = ["# Новостной фон (спека 19 §4)", "", f"Срез {s['computed_at']}, новых {s['new']}, "
         f"за сутки {s['day_items']} (с привязкой к нашим именам {s['day_tagged']}).", "",
         "| лента | статей в ответе | новых | отказ |", "|---|---|---|---|"]
    for k, v in s["feeds"].items():
        L.append(f"| {k} | {v.get('got', '—')} | {v.get('new', '—')} | {v.get('error') or ''} |")
    if s["top_names"]:
        L += ["", "Чаще всего за сутки: " + ", ".join(f"{n} {c}" for n, c in s["top_names"])]
    if s["calendar_48h"]:
        L += ["", "Календарь на 48 ч: " + "; ".join(f"{e['t']} {e['title']}" for e in s["calendar_48h"])]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------ прогон

def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_names(get, tickers, path=NAMES, log=print):
    old = _load(path, {})
    if old.get("at", 0) > time.time() - NAMES_TTL_S and old.get("names"):
        return old["names"], None
    rows = []
    try:
        for p in (1, 2):
            rows += json.loads(get(CG_MARKETS.format(p=p)))
    except Exception as e:                                   # noqa: BLE001
        if old.get("names"):
            return old["names"], f"имена CoinGecko не обновлены ({e}), взяты от {old.get('at')}"
        return {}, f"имена CoinGecko не получены ({e}) — привязка только по тикерам"
    nm = names_map(rows, tickers)
    _save(path, {"at": time.time(), "names": nm})
    log(f"имена проектов: из {len(rows)} монет CoinGecko на Bybit {len(nm)}")
    return nm, None


def run(get=http_text, dry=False, log=print, record=RECORD, instruments_path=INSTRUMENTS, now=None):
    t0 = time.time()
    now = now or utc_now()
    errors = []
    tickers = bybit_tickers(_load(instruments_path, {}))
    if not tickers:
        errors.append("справочник инструментов пуст — привязки к монетам нет")
    names, err = load_names(get, tickers, os.path.join(record, "names.json"), log)
    if err:
        errors.append(err)
    seen_path = os.path.join(record, "seen.json")
    seen = set(_load(seen_path, []))
    per_feed, fresh = {}, []
    for src, url in FEEDS:
        try:
            items = parse_rss(get(url), src)
        except ET.ParseError as e:
            per_feed[src] = {"error": f"не разбирается: {e}"[:120]}; errors.append(f"{src}: не разбирается"); continue
        except Exception as e:                               # noqa: BLE001
            per_feed[src] = {"error": str(e)[:120]}; errors.append(f"{src}: {e}"); continue
        new = [x for x in items if x["id"] not in seen]
        per_feed[src] = {"got": len(items), "new": len(new)}
        if not items:
            errors.append(f"{src}: ответ без статей")
        fresh += new
    for x in fresh:
        x["tags"] = tag(x, tickers, names)
        seen.add(x["id"])
    if not dry:
        os.makedirs(record, exist_ok=True)
        by_day = {}
        for x in fresh:
            by_day.setdefault(datetime.fromtimestamp(x["t"] / 1000, tz=timezone.utc).date().isoformat(), []).append(x)
        for d, xs in by_day.items():
            with open(os.path.join(record, f"news-{d}.jsonl"), "a", encoding="utf-8") as f:
                for x in sorted(xs, key=lambda x: x["t"]):
                    f.write(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n")
        _save(seen_path, sorted(seen)[-20000:])
    now_ms = int(now.timestamp() * 1000)
    day = []
    for d in {(now - timedelta(days=1)).date().isoformat(), now.date().isoformat()}:
        p = os.path.join(record, f"news-{d}.jsonl")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        day.append(json.loads(line))
                    except ValueError:
                        continue
    if dry:
        day += fresh
    s = summarize(day, per_feed, errors, CAL.upcoming(now, 48), t0, len(fresh), now_ms)
    if not dry:
        _save(LATEST, s)
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write(report_md(s))
    log(f"ленты: " + ", ".join(f"{k} {v.get('got', 'отказ')}/{v.get('new', '—')}" for k, v in per_feed.items())
        + f"; новых {len(fresh)}, с привязкой {sum(1 for x in fresh if x['tags'])}; за сутки {s['day_items']}; "
        f"отказов {len(errors)}; {s['secs']} с")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="новостной фон: RSS с привязкой к монетам")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(dry=a.dry)
    if not a.dry and not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "news " + s["computed_at"][:16]],
                       cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
