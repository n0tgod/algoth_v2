#!/usr/bin/env python3
"""Формирует отчёт A0 в markdown из summary.json."""

import datetime as dt
import json
import os
import statistics as st
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def load(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    s = load("summary.json")
    c = s["counts"]
    inter = s["intersection"]

    by_year = Counter(e["bybit_first"][:4] for e in inter)
    hl_count = sum(1 for e in inter if e["on_hyperliquid"])

    def cohort(min_year):
        return [e for e in inter if e["bybit_first"] < f"{min_year}-01-01"]

    lines = []
    add = lines.append

    add("# Отчёт A0 — инвентаризация площадок\n")
    add("Сгенерирован `research/a0_venue_inventory/report.py` из `out/summary.json`.")
    add("Источники: публичные архивы Bybit и Binance, публичный API Hyperliquid.\n")
    add("---\n")

    add("## 1. Размер универсумов\n")
    add("| Площадка | Инструментов | Комментарий |")
    add("|---|---:|---|")
    add(f"| Bybit — все директории архива | {c['bybit_archive_dirs']} | включая инверсные, USDC и делистнутые |")
    add(f"| **Bybit — базовых активов в USDT-перпах** | **{c['bybit_usdt_bases']}** | торговый универсум площадки исполнения |")
    add(f"| Binance USD-M — символов | {c['binance_um_symbols']} | источник длинной истории |")
    add(f"| Binance — базовых активов в USDT | {c['binance_usdt_bases']} | |")
    add(f"| Hyperliquid — всего | {c['hyperliquid_total']} | из них делистнутых: {c['hyperliquid_delisted']} |")
    add(f"| Hyperliquid — активных | {c['hyperliquid_live']} | |")
    add("")
    add(f"**Пересечение Bybit × Binance: {c['bybit_x_binance_bases']} базовых активов.**")
    add("Это и есть рабочий универсум: торгуем на Bybit, длинную историю берём с Binance.")
    add("")
    add(f"Пересечение всех трёх площадок: {c['bybit_x_binance_x_hl_bases']} активов.")
    add("")

    add("## 2. Глубина истории\n")
    add("Распределение по году появления инструмента на Bybit (внутри пересечения):\n")
    add("| Год | Инструментов | Накопительно |")
    add("|---|---:|---:|")
    run = 0
    for y in sorted(by_year):
        run += by_year[y]
        add(f"| {y} | {by_year[y]} | {run} |")
    add("")

    add("Когорты, пригодные для walk-forward:\n")
    add("| Инструмент торгуется с | Активов | Лет истории (прибл.) |")
    add("|---|---:|---:|")
    for y, yrs in ((2021, "5+"), (2022, "4+"), (2023, "3+"), (2024, "2+")):
        add(f"| до {y} | {len(cohort(y))} | {yrs} |")
    add("")

    # --- смертность инструментов ---------------------------------------
    bybit = load("bybit.json")
    usdt = [v for v in bybit.values() if v["quote"] == "USDT"]
    archive_end = max(v["last_date"] for v in usdt)
    cutoff = (dt.date.fromisoformat(archive_end) - dt.timedelta(days=7)).isoformat()
    dead = [v for v in usdt if v["last_date"] < cutoff]
    live = [v for v in usdt if v["last_date"] >= cutoff]
    lives = sorted(v["days_available"] for v in dead)
    dead_by_year = Counter(v["last_date"][:4] for v in dead)

    add("## 3. Смертность инструментов — ключевая находка\n")
    add(f"Архив Bybit по состоянию на {archive_end}. Инструмент считается прекратившим "
        f"торговаться, если последний день архива старше {cutoff}.\n")
    add("| | Инструментов | Доля |")
    add("|---|---:|---:|")
    add(f"| USDT-перпов за всю историю | {len(usdt)} | 100 % |")
    add(f"| Торгуются сейчас | {len(live)} | {len(live) / len(usdt) * 100:.1f} % |")
    add(f"| **Прекратили торговаться** | **{len(dead)}** | **{len(dead) / len(usdt) * 100:.1f} %** |")
    add("")
    if lives:
        add(f"Срок жизни делистнутого инструмента: медиана **{st.median(lives):.0f} дней**, "
            f"квартили {lives[len(lives) // 4]} и {lives[3 * len(lives) // 4]}, максимум {max(lives)}.\n")
    add("Делистинги по годам (последний день торгов):\n")
    add("| Год | Инструментов |")
    add("|---|---:|")
    for y in sorted(dead_by_year):
        add(f"| {y} | {dead_by_year[y]} |")
    add("")
    add("### Следствия\n")
    add("**1. Опасность отбора универсума «по сегодняшнему списку».** Треть инструментов "
        "уже мертва. Если брать активы, у которых на сегодня есть N лет истории, отбираются "
        "именно выжившие — то есть survivorship bias возвращается через конструкцию универсума, "
        "даже когда делистнутые данные физически лежат в архиве.\n")
    add("**Требование:** универсум определяется **на момент времени**. В каждом окне отбора "
        "участвуют инструменты, торговавшиеся тогда и имевшие достаточно истории на тот момент, "
        "независимо от того, существуют ли они сегодня.\n")
    add("**2. Делистинг — материальный риск позиции, а не редкий случай.** При таком темпе "
        "книга из 30 пар (60 ног) за год почти наверняка столкнётся с несколькими событиями. "
        "Это подтверждает необходимость выхода по делистингу в модели позиции и требует "
        "фильтра зрелости и ликвидности при отборе: короткая история и низкий оборот — "
        "признаки кандидата на делистинг.\n")

    add("## 4. Доступность данных\n")
    add("| Данные | Площадка | Доступ из окружения разработки | Назначение |")
    add("|---|---|---|---|")
    add("| Свечи 1m, с 2020 | Binance, S3-архив | **да** | оценка отношений, β, полураспад |")
    add("| Ставки funding, с 2020 | Binance, S3-архив | **да** | только для сверки, не для издержек |")
    add("| bookTicker (лучший бид/аск) | Binance, S3-архив | **да** | моделирование исполнения |")
    add("| aggTrades | Binance, S3-архив | **да** | вероятность исполнения лимиток |")
    add("| Тики с агрессором, с 2020-03 | Bybit, `public.bybit.com/trading` | **да** | лучший источник для модели исполнения |")
    add("| Свечи 1m | Bybit, API v5 | **нет — геоблок (403 CloudFront)** | торговое окно |")
    add("| **Ставки funding** | **Bybit, API v5** | **нет — геоблок** | **издержки, обязательны** |")
    add("| Справочник инструментов | Bybit, API v5 | **нет — геоблок** | шаг цены/объёма, мин. нотионал |")
    add("| Универсум, делистинги, funding | Hyperliquid, API | **да** | |")
    add("")
    add(f"Инструментов из пересечения, представленных также на Hyperliquid: {hl_count}.")
    add("")

    add("### Пробелы, требующие решения\n")
    add("1. **Ставки funding Bybit недоступны из этого окружения.** Спецификация 02, раздел 2.0 "
        "требует брать funding строго с площадки исполнения. Обходные источники в публичном "
        "архиве Bybit не подходят: `premium_index` покрывает только инверсные контракты "
        "(11 символов), `kline_for_metatrader4` — 23 символа.")
    add("2. **Свечи Bybit в масштабе** доступны только через API либо агрегацией тиков. "
        "Агрегация возможна из открытого архива, но объём большой.")
    add("")

    add("## 5. Самые старые инструменты пересечения\n")
    add("| Базовый актив | Bybit | С даты | Binance | Hyperliquid |")
    add("|---|---|---|---|---|")
    for e in inter[:25]:
        hl = "да" if e["on_hyperliquid"] else "—"
        if e["hyperliquid_delisted"]:
            hl = "делистнут"
        add(f"| {e['base']} | {e['bybit_symbol']} | {e['bybit_first']} | {e['binance_symbol']} | {hl} |")
    add("")
    add(f"Полный список — `out/summary.json`, поле `intersection` ({len(inter)} записей).")
    add("")

    add("## 6. Наборы данных в архиве Binance USD-M\n")
    add(", ".join(f"`{d}`" for d in s["binance_datasets"]))
    add("")

    path = os.path.join(OUT, "A0-report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"записано: {path} ({len(lines)} строк)")


if __name__ == "__main__":
    main()
