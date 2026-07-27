#!/usr/bin/env python3
"""
A0 — инвентаризация площадок.

Собирает фактические данные о том, что доступно на Bybit, Hyperliquid и Binance:
перечень инструментов (включая делистнутые), глубина публичной истории,
пересечение универсумов между площадками.

Спецификация: docs/v2/02-research-harness-spec.md, этап A0.

Только stdlib. Все сетевые ответы кэшируются на диск — повторный запуск дешёвый.
"""

import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "out", "cache")
OUT = os.path.join(HERE, "out")

BYBIT_ARCHIVE = "https://public.bybit.com/trading/"
BINANCE_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"

WORKERS = 8
TIMEOUT = 45
RETRIES = 3

# Множители в тикерах: 1000PEPEUSDT, 10000LADYSUSDT, 1000000MOGUSDT.
# В логарифмическом спреде постоянный множитель уходит в среднее,
# поэтому на коинтеграцию он не влияет — но для сопоставления
# инструментов между площадками его надо снимать.
#
# Две ловушки, обе обнаружены проверкой покрытия групп:
#   1. Множитель бывает и суффиксом: Bybit торгует SHIB1000USDT,
#      тогда как Binance — 1000SHIBUSDT. Без обработки суффикса SHIB
#      получал разные базовые активы на разных площадках и молча
#      выпадал из пересечения.
#   2. Множители доходят до 10 000 000 (10000000AIDOGEUSDT).
# Порядок в чередовании — от длинного к короткому, иначе сработает
# короткий вариант и в базовом активе останутся лишние нули.
_MULT = r"(10000000|1000000|100000|10000|1000)"
MULTIPLIER_PREFIX_RE = re.compile(r"^" + _MULT + r"(?=[A-Z])")
MULTIPLIER_SUFFIX_RE = re.compile(r"(?<=[A-Z])" + _MULT + r"$")
QUOTE_SUFFIXES = ("USDT", "USDC", "PERP", "USD")


def _ctx():
    c = ssl.create_default_context()
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle and os.path.exists(bundle):
        c.load_verify_locations(bundle)
    return c


SSL_CTX = _ctx()


def fetch(url, method="GET", body=None, cache_key=None):
    """HTTP с дисковым кэшем и повторами."""
    key = cache_key or sha256(f"{method}{url}{body}".encode()).hexdigest()
    path = os.path.join(CACHE, key + ".gz")

    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()

    data = body.encode() if body else None
    headers = {"User-Agent": "a0-venue-inventory/1.0"}
    if body:
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
                text = r.read().decode("utf-8", errors="replace")
            os.makedirs(CACHE, exist_ok=True)
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(text)
            return text
        except Exception as e:  # noqa: BLE001 — сеть, нужен любой сбой
            last = e
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch failed {url}: {last}")


def normalize(symbol):
    """Тикер площадки -> (базовый актив, котируемый актив, множитель)."""
    s = symbol.upper()
    quote = None
    for suf in QUOTE_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            quote = "USDC" if suf == "PERP" else suf
            s = s[: -len(suf)]
            break
    mult = 1
    m = MULTIPLIER_PREFIX_RE.match(s)
    if m:
        mult = int(m.group(1))
        s = s[m.end():]
    else:
        m = MULTIPLIER_SUFFIX_RE.search(s)
        if m:
            mult = int(m.group(1))
            s = s[: m.start()]
    return s, quote, mult


# ---------------------------------------------------------------- Hyperliquid

def collect_hyperliquid():
    meta = json.loads(fetch(HYPERLIQUID_API, "POST", '{"type":"meta"}', "hl_meta"))
    ctxs = json.loads(
        fetch(HYPERLIQUID_API, "POST", '{"type":"metaAndAssetCtxs"}', "hl_ctxs")
    )
    asset_ctxs = ctxs[1] if isinstance(ctxs, list) and len(ctxs) > 1 else []

    out = {}
    for i, a in enumerate(meta.get("universe", [])):
        name = a["name"]
        base, _, mult = normalize(name)
        ctx = asset_ctxs[i] if i < len(asset_ctxs) else {}
        out[name] = {
            "symbol": name,
            "base": base or name,
            "quote": "USD",
            "multiplier": mult,
            "delisted": bool(a.get("isDelisted", False)),
            "max_leverage": a.get("maxLeverage"),
            "sz_decimals": a.get("szDecimals"),
            "funding_now": ctx.get("funding"),
            "open_interest": ctx.get("openInterest"),
            "day_volume_usd": ctx.get("dayNtlVlm"),
        }
    return out


# ---------------------------------------------------------------------- Bybit

def _bybit_symbols():
    html = fetch(BYBIT_ARCHIVE, cache_key="bybit_root")
    return sorted(set(re.findall(r'href="([A-Z0-9_-]+)/"', html)))


def _bybit_symbol_range(symbol):
    """Первый и последний день, за который есть архив тиков."""
    try:
        html = fetch(BYBIT_ARCHIVE + symbol + "/", cache_key="bybit_sym_" + symbol)
    except Exception:
        return None
    dates = re.findall(r"(\d{4}-\d{2}-\d{2})\.csv\.gz", html)
    if not dates:
        return None
    dates.sort()
    return {"first": dates[0], "last": dates[-1], "days": len(set(dates))}


def collect_bybit(symbols):
    out = {}
    done = [0]

    def work(sym):
        rng = _bybit_symbol_range(sym)
        done[0] += 1
        if done[0] % 200 == 0:
            print(f"  bybit {done[0]}/{len(symbols)}", file=sys.stderr, flush=True)
        return sym, rng

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for sym, rng in ex.map(work, symbols):
            if not rng:
                continue
            base, quote, mult = normalize(sym)
            out[sym] = {
                "symbol": sym,
                "base": base,
                "quote": quote,
                "multiplier": mult,
                "first_date": rng["first"],
                "last_date": rng["last"],
                "days_available": rng["days"],
            }
    return out


# -------------------------------------------------------------------- Binance

def _s3_list(prefix, delimiter="/"):
    """Постраничный листинг S3-бакета архива Binance."""
    keys, prefixes, marker = [], [], ""
    while True:
        url = f"{BINANCE_S3}?delimiter={delimiter}&prefix={prefix}"
        if marker:
            url += f"&marker={urllib.parse.quote(marker, safe='')}"
        xml = fetch(url, cache_key="bnc_" + sha256(url.encode()).hexdigest())
        keys += re.findall(r"<Key>([^<]+)</Key>", xml)
        prefixes += re.findall(r"<Prefix>([^<]+)</Prefix>", xml)
        if "<IsTruncated>true</IsTruncated>" not in xml:
            break
        nm = re.findall(r"<NextMarker>([^<]+)</NextMarker>", xml)
        marker = nm[0] if nm else (keys[-1] if keys else "")
        if not marker:
            break
    return keys, prefixes


def collect_binance():
    base_prefix = "data/futures/um/monthly/klines/"
    _, prefixes = _s3_list(base_prefix)
    symbols = [p[len(base_prefix):].strip("/") for p in prefixes if p != base_prefix]
    symbols = sorted({s for s in symbols if s})

    out = {}
    done = [0]

    def work(sym):
        try:
            keys, _ = _s3_list(f"{base_prefix}{sym}/1m/")
        except Exception:
            keys = []
        done[0] += 1
        if done[0] % 200 == 0:
            print(f"  binance {done[0]}/{len(symbols)}", file=sys.stderr, flush=True)
        months = sorted(set(re.findall(r"-1m-(\d{4}-\d{2})\.zip", " ".join(keys))))
        return sym, months

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for sym, months in ex.map(work, symbols):
            if not months:
                continue
            b, q, mult = normalize(sym)
            out[sym] = {
                "symbol": sym,
                "base": b,
                "quote": q,
                "multiplier": mult,
                "first_month": months[0],
                "last_month": months[-1],
                "months_available": len(months),
            }
    return out


def binance_datasets():
    """Какие типы данных вообще лежат в архиве Binance USD-M."""
    _, prefixes = _s3_list("data/futures/um/monthly/")
    return sorted(
        p.rstrip("/").split("/")[-1]
        for p in prefixes
        if p != "data/futures/um/monthly/"
    )


# ------------------------------------------------------------------ сведение

def build_summary(hl, bybit, binance, bnc_datasets):
    def by_base(d, pred=None):
        m = {}
        for v in d.values():
            if pred and not pred(v):
                continue
            m.setdefault(v["base"], []).append(v)
        return m

    # Торговый универсум = линейные USDT-перпы Bybit (площадка исполнения)
    bybit_usdt = by_base(bybit, lambda v: v["quote"] == "USDT")
    binance_usdt = by_base(binance, lambda v: v["quote"] == "USDT")
    hl_live = by_base(hl, lambda v: not v["delisted"])
    hl_all = by_base(hl)

    both = sorted(set(bybit_usdt) & set(binance_usdt))
    tri = sorted(set(both) & set(hl_all))

    def depth(entries, first_key):
        return min(e[first_key] for e in entries)

    intersection = []
    for b in both:
        bb = bybit_usdt[b]
        bn = binance_usdt[b]
        intersection.append({
            "base": b,
            "bybit_symbol": bb[0]["symbol"],
            "bybit_first": depth(bb, "first_date"),
            "bybit_last": max(e["last_date"] for e in bb),
            "bybit_days": max(e["days_available"] for e in bb),
            "binance_symbol": bn[0]["symbol"],
            "binance_first": depth(bn, "first_month"),
            "on_hyperliquid": b in hl_all,
            "hyperliquid_delisted": b in hl_all and b not in hl_live,
        })
    intersection.sort(key=lambda e: e["bybit_first"])

    return {
        "counts": {
            "bybit_archive_dirs": len(bybit),
            "bybit_usdt_bases": len(bybit_usdt),
            "binance_um_symbols": len(binance),
            "binance_usdt_bases": len(binance_usdt),
            "hyperliquid_total": len(hl),
            "hyperliquid_live": len(hl_live),
            "hyperliquid_delisted": len(hl) - len(hl_live),
            "bybit_x_binance_bases": len(both),
            "bybit_x_binance_x_hl_bases": len(tri),
        },
        "binance_datasets": bnc_datasets,
        "intersection": intersection,
    }


def load_datasets_from_summary():
    """Список наборов данных архива Binance из предыдущего прогона."""
    path = os.path.join(OUT, "summary.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("binance_datasets", [])
    return []


def renormalize_stored():
    """Пересчитать производные поля из уже собранных JSON, без сети.

    Нужно после правки normalize(): базовый актив и множитель вычисляются
    на этапе сбора, поэтому исправление нормализации требует пересчёта —
    но не повторной загрузки.
    """
    loaded = {}
    for name in ("hyperliquid.json", "bybit.json", "binance.json"):
        path = os.path.join(OUT, name)
        if not os.path.exists(path):
            raise SystemExit(f"нет {path} — сначала обычный прогон")
        with open(path, encoding="utf-8") as f:
            loaded[name] = json.load(f)

    changed = 0
    for name, data in loaded.items():
        for rec in data.values():
            base, quote, mult = normalize(rec["symbol"])
            if name == "hyperliquid.json":
                base, quote = base or rec["symbol"], "USD"
            if rec["base"] != base or rec["multiplier"] != mult:
                changed += 1
            rec["base"], rec["multiplier"] = base, mult
            if name != "hyperliquid.json":
                rec["quote"] = quote

    print(f"пересчитано записей с изменениями: {changed}", file=sys.stderr)
    return (
        loaded["hyperliquid.json"],
        loaded["bybit.json"],
        loaded["binance.json"],
    )


def write_all(hl, bybit, binance, summary):
    for name, obj in (
        ("hyperliquid.json", hl),
        ("bybit.json", bybit),
        ("binance.json", binance),
        ("summary.json", summary),
    ):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    if "--renormalize" in sys.argv:
        hl, bybit, binance = renormalize_stored()
        summary = build_summary(hl, bybit, binance, load_datasets_from_summary())
        write_all(hl, bybit, binance, summary)
        print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
        return

    print("Hyperliquid...", file=sys.stderr, flush=True)
    hl = collect_hyperliquid()
    print(f"  {len(hl)} инструментов", file=sys.stderr, flush=True)

    print("Bybit: список символов...", file=sys.stderr, flush=True)
    syms = _bybit_symbols()
    print(f"  {len(syms)} директорий, собираю глубину истории...", file=sys.stderr, flush=True)
    bybit = collect_bybit(syms)

    print("Binance: список символов...", file=sys.stderr, flush=True)
    binance = collect_binance()
    datasets = binance_datasets()

    summary = build_summary(hl, bybit, binance, datasets)
    write_all(hl, bybit, binance, summary)

    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import urllib.parse  # noqa: E402 — нужен внутри _s3_list
    main()
