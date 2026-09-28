#!/usr/bin/env python3
"""
Сверка дат запуска плечевых фондов по их собственным страницам.

Зачем отдельным прогоном
------------------------

Окно фонда — граница замера, и заявка назвала её ПО ПАМЯТИ (BITX с
2023-06-27, 2x на эфир с 2024-06-04), прямо сказав: строитель сверяет по
страницам фондов и печатает, сверенная дата побеждает названную. Память
модели датой не является, и подставить её молча было бы выдуманным
числом в границе окна.

Сверка живёт ОТДЕЛЬНО от замера намеренно. Замер обязан считаться на
архиве и без сети; сеть подводит, страница меняет разметку, и замер,
падающий от этого, не считается вовсе. Поэтому: этот прогон пишет
`out/fund_dates.json`, а замер его ЧИТАЕТ — нет файла или дата не
найдена, окно берётся объявленным и отчёт печатает «не сверено» с
названной причиной. Прочерк с причиной, а не тихая подмена.

    cd ~/algoth_v2 && .venv/bin/python research/mech_59653014/fund_dates.py

Только стандартная библиотека.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PATH = os.path.join(OUT, "fund_dates.json")

TIMEOUT = 25
UA = "algoth-mech-59653014/1.0 (fund inception date check)"

# Фонды и их страницы. Источники — записи разведчика
# (`research/factory/out/scout.jsonl`, at 1790475243.616). Символ перпа
# рядом: имя архива, к окну которого дата относится.
FUNDS = [
    {"ticker": "BITX", "symbol": "BTCUSDT", "lever": 2.0,
     "url": "https://www.volatilityshares.com/bitx",
     "what": "2x Bitcoin Strategy ETF, Volatility Shares"},
    {"ticker": "ETHU", "symbol": "ETHUSDT", "lever": 2.0,
     "url": "https://www.volatilityshares.com/ethu",
     "what": "2x Ether ETF, Volatility Shares"},
    {"ticker": "ETHT", "symbol": "ETHUSDT", "lever": 2.0,
     "url": "https://www.proshares.com/our-etfs/leveraged-and-inverse/etht",
     "what": "Ultra Ether ETF, ProShares"},
]

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}

# Ярлыки, рядом с которыми на странице фонда стоит дата запуска. Список
# закрытый: «любое число рядом со словом date» поймало бы дату отчёта.
DATE_LABELS = ("inception date", "fund inception", "inception",
               "first trade date", "commencement of operations")
AUM_LABELS = ("total net assets", "net assets", "fund assets",
              "assets under management")


def text_of(body):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def parse_date(s):
    """Дата из строки в виде ISO. Не разобралась — None, не «сегодня»."""
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", s)
    if m:
        mo, d, y = (int(x) for x in m.groups())
        y += 2000 if y < 100 else 0
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", s)
    if m:
        mo = None
        for name, i in MONTHS.items():
            if name.startswith(m.group(1).lower()[:3]):
                mo = i
                break
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}"
    return None


def find_value(t, labels, parser, take=120):
    """Ярлык, хвост за ним и разобранное значение. Ничего — (None, None, None).

    Ярлыки перебираются В ОБЪЯВЛЕННОМ ПОРЯДКЕ, от самого точного к
    самому общему, и находкой считается только та, чей хвост РАЗОБРАЛСЯ.
    Первая версия брала ярлык, встретившийся на странице раньше, и на
    странице ProShares общее слово «Inception» стояло в заголовке
    таблицы доходностей — то есть ярлык находился там, где даты не было.
    """
    low = t.lower()
    for lab in labels:
        i = low.find(lab)
        if i < 0:
            continue
        tail = t[i + len(lab): i + len(lab) + take].strip(" :–-")
        v = parser(tail)
        if v is not None:
            return lab, tail, v
    return None, None, None


# Активы фонда ниже этого — не активы фонда, а число, схваченное мимо
# ярлыка. Разобранное неправдоподобное значение хуже прочерка: прочерк
# видно, а «активы 9 $» уедет в отчёт числом.
AUM_MIN_USD = 1e6


def parse_money(s):
    """Сумма в долларах: `$1,320,640,709.94`, `$1.32 billion`. Нет — None.

    Знак доллара ОБЯЗАТЕЛЕН. Без него первое же число хвоста «as of
    09/25/2026 $1,320,640,709.94» разбиралось в 9 долларов — цифра
    месяца из даты, объявленная активами фонда.
    """
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*"
                  r"(billion|million|trillion|B\b|M\b|bn|mn)?", s or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"trillion": 1e12, "billion": 1e9, "b": 1e9, "bn": 1e9,
            "million": 1e6, "m": 1e6, "mn": 1e6}
    v *= mult.get((m.group(2) or "").lower(), 1.0)
    return v if v >= AUM_MIN_USD else None


def check(fund, log=print):
    rec = dict(fund)
    rec["at"] = round(time.time(), 3)
    try:
        req = urllib.request.Request(fund["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
        rec["http"] = getattr(r, "status", None)
    except (urllib.error.URLError, OSError, ValueError) as e:
        rec.update(status="страница недоступна", why=f"{type(e).__name__}: {e}",
                   inception=None, aum_usd=None, quote=None)
        log(f"  {fund['ticker']}: {rec['why']}")
        return rec
    t = text_of(body)
    lab, tail, d = find_value(t, DATE_LABELS, parse_date)
    alab, atail, aum = find_value(t, AUM_LABELS, parse_money)
    rec.update(
        inception=d,
        quote=(f"{lab}: {tail}" if lab else None),
        aum_usd=aum,
        aum_asof=(parse_date(atail) if atail else None),
        aum_quote=(f"{alab}: {atail}" if alab else None),
        status=("сверено" if d else
                "ярлыка с разобранной датой запуска на странице нет"),
        page_chars=len(t),
    )
    log(f"  {fund['ticker']}: {rec['status']}"
        + (f", дата {d}" if d else "")
        + (f", активы {rec['aum_usd']:,.0f} $" if rec.get("aum_usd") else ""))
    return rec


def read(path=PATH):
    """Сверенные даты: {символ: (ISO-дата, тикер, откуда)}. Нет файла — пусто.

    Берётся САМАЯ РАННЯЯ сверенная дата по символу: окно имени начинается
    с появления первого такого фонда на этот актив.
    """
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for r in d.get("funds", []):
        iso, sym = r.get("inception"), r.get("symbol")
        if not iso or not sym:
            continue
        if sym not in out or iso < out[sym][0]:
            out[sym] = (iso, r.get("ticker"), r.get("url"))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"сверка дат запуска по {len(FUNDS)} страницам фондов", flush=True)
    rows = [check(f) for f in FUNDS]
    doc = {"at": round(time.time(), 3), "funds": rows,
           "note": "сверенная дата побеждает объявленную; ненайденная — "
                   "прочерк с причиной, объявленная остаётся с пометкой"}
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps({r["ticker"]: r["status"] for r in rows},
                     ensure_ascii=False, indent=1))
    print(f"записано: {PATH}")
    return 0 if any(r.get("inception") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
