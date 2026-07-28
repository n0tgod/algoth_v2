#!/usr/bin/env python3
"""
Общие примитивы работы с площадками: HTTP с дисковым кэшем и нормализация тикеров.

Вынесено из `research/a0_venue_inventory/inventory.py`, когда те же функции
понадобились этапу A1. Копировать `normalize()` было нельзя: в ней уже дважды
находили ошибки (множитель-суффикс `SHIB1000USDT` и множители до 10 000 000),
и разошедшиеся копии дали бы разный универсум на разных этапах.

Только stdlib.
"""

import gzip
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from hashlib import sha256

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


def fetch(url, cache_dir, method="GET", body=None, cache_key=None, user_agent="algoth-v2/1.0"):
    """HTTP с дисковым кэшем и повторами. Возвращает текст ответа."""
    key = cache_key or sha256(f"{method}{url}{body}".encode()).hexdigest()
    path = os.path.join(cache_dir, key + ".gz")

    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()

    data = body.encode() if body else None
    headers = {"User-Agent": user_agent}
    if body:
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
                text = r.read().decode("utf-8", errors="replace")
            os.makedirs(cache_dir, exist_ok=True)
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(text)
            return text
        except Exception as e:  # noqa: BLE001 — сеть, нужен любой сбой
            last = e
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch failed {url}: {last}")


def fetch_binary(url, cache_dir, cache_key=None,
                 user_agent="algoth-v2/1.0"):
    """То же, что `fetch`, но возвращает байты и кэширует их как есть.

    Отдельной функцией, а не флагом: `fetch` декодирует ответ в текст с
    заменой битых байт, и для zip-архива это молча портит данные —
    файл распакуется с ошибкой уже потом, далеко от места причины.
    """
    key = cache_key or sha256(url.encode()).hexdigest()
    path = os.path.join(cache_dir, key + ".bin")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(req, timeout=TIMEOUT,
                                        context=SSL_CTX) as r:
                data = r.read()
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            return data
        except Exception as e:  # noqa: BLE001 — сеть, нужен любой сбой
            last = e
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch_binary failed {url}: {last}")


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
