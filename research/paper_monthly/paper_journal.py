#!/usr/bin/env python3
"""Журнал бумажной месячной книги: чтение и правила — на стандартной
библиотеке, без numpy и duckdb.

Зачем отдельный модуль. Журнал читают ДВОЕ: сама книга (`book.py`,
тянет numpy, duckdb и половину исследовательского кода) и веб-сервер
страницы наблюдения (`b1_book/collect.py`, живёт на стандартной
библиотеке и работает рядом со сбором стакана). Тянуть в сборщик
numpy ради правила «записано ли решение вперёд» нельзя, а завести
второе такое правило — тем более: два места, решающих одно, однажды
разойдутся, и страница станет называть настоящим наблюдением то, что
книга считает бэктестом. Ровно поэтому карта семейств признаков в своё
время переехала в `s8_loop/families.py`.

Здесь живёт то, что нужно обоим: константы конструкции, календарь и
правило `ahead`. Всё, что требует numpy (β, сигнал, исход), остаётся в
`book.py`.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

# --- конструкция (объявлена до первого прогона книги) ------------------
RULES = 1
K_DAYS = 14              # формация сигнала
H_DAYS = 30              # удержание транша
FORM_DAYS = 90           # окно оценки β
WIDTH = 0.10             # дециль
TAKER_BP = 5.5
TURNOVER = 2.0           # транш открывается и закрывается целиком
COST_BP = TURNOVER * TAKER_BP

# Решение считается записанным ВПЕРЁД, если попало в журнал не позже чем
# через двое суток после даты сечения. Двое, а не одни: задержка
# структурная, а не случайная — суточный архив Binance за день `D`
# публикуется ПОСЛЕ конца суток `D`, а решению на дату `D` нужен бар с
# меткой `D`. Раньше `D + 1` его посчитать нечем ни при каком
# расписании; запас во вторые сутки — на сам прогон и на задержку
# публикации архива.
AHEAD_TOL_SEC = 2 * 86400


def ms(day):
    """Полночь UTC даты в миллисекундах.

    Считается datetime, а не numpy: модуль обязан подниматься в
    сборщике. Совпадение с прежним счётом книги закреплено тестом.
    """
    d = date.fromisoformat(day)
    return int(datetime(d.year, d.month, d.day,
                        tzinfo=timezone.utc).timestamp() * 1000)


def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def today():
    return datetime.now(timezone.utc).date().isoformat()


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def ahead(rec):
    """Записано ли решение ВПЕРЁД, до начала форвардного окна.

    Решение без `written_at` настоящим наблюдением не считается: время
    записи неизвестно, а неизмеримое не есть удовлетворяющее.
    """
    w = rec.get("written_at")
    if w is None:
        return False
    return w <= ms(rec["at"]) / 1000.0 + AHEAD_TOL_SEC


def tranches(decisions, resolutions, now=None, h_days=H_DAYS):
    """Сопоставить решения с разборами — по одной строке на транш.

    Ничего не считает сверх календаря: числа исхода берутся из разбора
    как есть. Транш без разбора — ОТКРЫТЫЙ, у него нет ни нетто, ни
    исхода; ставить туда ноль значило бы выдать незрелое за нулевое.
    """
    by_at = {r["at"]: r for r in resolutions}
    now = now or datetime.now(timezone.utc).timestamp()
    rows = []
    for dec in sorted(decisions, key=lambda r: r["at"]):
        at = dec["at"]
        res = by_at.get(at)
        legs = dec.get("legs") or []
        matures = shift(at, h_days)
        left = (ms(matures) / 1000.0 - now) / 86400.0
        row = {
            "at": at,
            "ahead": ahead(dec),
            "written_at": dec.get("written_at"),
            "elapsed": dec.get("elapsed"),
            "rules": dec.get("rules"),
            "assets": dec.get("assets"),
            "legs_n": len(legs),
            "long_n": sum(1 for l in legs if (l.get("w") or 0) > 0),
            "short_n": sum(1 for l in legs if (l.get("w") or 0) < 0),
            "matures_at": matures,
            "state": "closed" if res else "open",
            "days_left": (None if res else round(max(0.0, left), 1)),
        }
        if res:
            row.update({
                "gross_bp": res.get("gross_bp"),
                "cost_bp": res.get("cost_bp"),
                "funding_bp": res.get("funding_bp"),
                "net_bp": res.get("net_bp"),
                "missing_weight": res.get("missing_weight"),
                "truncated_legs": res.get("truncated_legs"),
                "coverage_median": res.get("coverage_median"),
                "resolved_at": res.get("resolved_at"),
            })
        rows.append(row)
    return rows


def leg_rows(dec, res=None):
    """Ноги транша: состав решения плюс исход, когда он есть.

    Исход НЕ выдумывается: у открытого транша и у ноги, чей ряд
    хранилище не отдало, `resid_bp` остаётся пустым — прочерк на
    странице, а не ноль.
    """
    out_by = {}
    for lg in (res or {}).get("legs") or []:
        out_by[lg.get("sym")] = lg
    rows = []
    for lg in dec.get("legs") or []:
        got = out_by.get(lg.get("sym")) or {}
        rows.append({
            "sym": lg.get("sym"),
            "w": lg.get("w"),
            "side": "long" if (lg.get("w") or 0) > 0 else "short",
            "sig": lg.get("sig"),
            "beta": lg.get("beta"),
            "resid_bp": got.get("resid_bp"),
            "bars": got.get("bars"),
            "coverage": got.get("coverage"),
            "truncated": got.get("truncated"),
        })
    # Порядок показа: сперва длинная нога, внутри — по сигналу. Состав
    # решения и есть ответ на вопрос «что книга купила», и читать его
    # удобнее сторонами, а не порядком записи.
    rows.sort(key=lambda r: (r["side"] != "long",
                             -(r["sig"] if r["sig"] is not None else 0.0)))
    return rows
