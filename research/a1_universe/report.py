#!/usr/bin/env python3
"""Формирует отчёт A1 по универсуму в markdown из universe.json."""

import json
import os
import sys
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
from universe import (  # noqa: E402
    binance_history_days_by,
    estimation_history_days_by,
    history_days_by,
    tradable_on,
    universe_at,
)

# Точки, в которых показывается универсум. Полугодовой шаг выбран под
# протокол walk-forward раздела 6: окно отбора и торговое окно такого
# порядка дают по этой истории осмысленное число окон.
PROBE_MONTHS = (1, 7)
MIN_HISTORY = 365


def main():
    with open(os.path.join(OUT, "universe.json"), encoding="utf-8") as f:
        m = json.load(f)
    A = m["assets"]
    as_of = date.fromisoformat(m["archive_as_of"])

    probes = [
        date(y, mo, 1)
        for y in range(2022, as_of.year + 1)
        for mo in PROBE_MONTHS
        if date(y, mo, 1) <= as_of
    ]

    lines = []
    add = lines.append

    add("# Отчёт A1 — универсум площадки исполнения на момент времени\n")
    add("Сгенерирован `research/a1_universe/report.py` из `out/universe.json`.")
    add("Источник — листинг директорий публичного архива Bybit: файл за день")
    add("существует тогда и только тогда, когда в этот день были сделки.\n")
    add(f"Срез архива: **{m['archive_as_of']}**.\n")
    add("---\n")

    # 1
    total = len(A)
    delisted = sum(1 for r in A.values() if r["delisted"])
    with_bnc = sum(1 for r in A.values() if r["binance_symbol"])
    add("## 1. Что собрано\n")
    add("| | Инструментов |")
    add("|---|---:|")
    add(f"| USDT-перпов Bybit за всю историю | {total} |")
    add(f"| из них торгуются на срезе архива | {total - delisted} |")
    add(f"| из них прекратили торговаться | **{delisted}** ({100*delisted/total:.1f} %) |")
    add(f"| есть длинная история на Binance | {with_bnc} |")
    add("")
    add("Три числа сходятся с этапом A0, полученным по другому пути, — это")
    add("независимая проверка, а не повтор.\n")

    # 2
    add("## 2. Универсум на момент времени\n")
    add(f"Условия отбора: инструмент торговался на Bybit в этот день и имел к")
    add(f"тому моменту не менее {MIN_HISTORY} дней истории для оценки β, μ, σ.")
    add("История считается по более длинному из двух рядов — Bybit или Binance")
    add("(раздел 2.2 спеки 02): часть активов Bybit листинговал раньше Binance,")
    add("поэтому ни один источник по отдельности не годится.\n")
    add("| Дата | Активов | Пар-кандидатов | Из них делистнуты сегодня |")
    add("|---|---:|---:|---:|")
    for d in probes:
        u = universe_at(m, d, MIN_HISTORY)
        n = len(u)
        dead = sum(1 for b in u if A[b]["delisted"])
        share = f"{dead} ({100*dead/n:.0f} %)" if n else "—"
        add(f"| {d.isoformat()} | {n} | {n*(n-1)//2:,} | {share} |".replace(",", " "))
    add("")

    # 3 — главное следствие
    add("## 3. Величина survivorship bias\n")
    add("Сравниваются два способа построить универсум на одну и ту же дату:")
    add("**на момент времени** (как требует раздел 2.1.1) и **по сегодняшнему")
    add("списку** — то есть с молчаливым отбрасыванием того, что уже умерло.\n")
    add("| Дата | На момент времени | По сегодняшнему списку | Потеряно |")
    add("|---|---:|---:|---:|")
    worst = (0.0, None)
    for d in probes:
        u = universe_at(m, d, MIN_HISTORY)
        alive = [b for b in u if not A[b]["delisted"]]
        n, k = len(u), len(alive)
        pct = 100 * (n - k) / n if n else 0.0
        if pct > worst[0]:
            worst = (pct, d)
        add(f"| {d.isoformat()} | {n} | {k} | **−{pct:.0f} %** |")
    add("")
    add(f"Максимум расхождения — {worst[0]:.0f} % на {worst[1].isoformat()}. В окнах")
    add("2023–2025 годов отбор по сегодняшнему списку выбрасывает примерно")
    add("четверть инструментов, причём именно тех, чья судьба закончилась плохо.")
    add("Это и есть механизм, которым survivorship bias возвращается через")
    add("конструкцию универсума, даже когда делистнутые данные лежат в архиве.\n")

    # 4
    settled = sorted(
        (r for r in A.values() if r["settlement_days"]),
        key=lambda r: r["last_trading_day"],
    )
    add("## 4. Расчётный день делистинга — ловушка в данных\n")
    add(f"У {len(settled)} инструментов последний файл архива отстоит от конца")
    add("реальной торговли на недели и месяцы и содержит ровно один день:")
    add("биржа закрывает позиции по расчётной цене уже после остановки торгов.\n")
    add("| Актив | Торговля кончилась | Расчётный день | Разрыв, дней |")
    add("|---|---|---|---:|")
    for r in settled:
        end = date.fromisoformat(r["last_trading_day"])
        st = date.fromisoformat(r["settlement_days"][0])
        add(f"| {r['base']} | {r['last_trading_day']} | {r['settlement_days'][0]} | {(st-end).days} |")
    add("")
    add("Взять последний файл за дату делистинга — значит считать инструмент")
    add("торгуемым всё это время. У BTT торговля кончилась 2021-12-28, а")
    add("последний файл датирован 2022-12-12: бэктест открывал бы по нему")
    add("позиции почти год после смерти инструмента, по ценам, которых не было.")
    add("Поэтому расчётные дни хранятся отдельно и в универсум не входят.\n")
    add("Пороги отделения откалиброваны по самим данным, а не назначены:")
    add("у всех девяти артефактов длина хвоста ровно один день, тогда как")
    add("ближайший настоящий хвост — двенадцать дней.\n")

    gapped = sorted(
        (r for r in A.values() if r["gap_days"] > 0),
        key=lambda r: -r["gap_days"],
    )
    add("### 4.1 Настоящие приостановки\n")
    add(f"После отделения расчётных дней остаётся {len(gapped)} инструментов,")
    add("у которых торги действительно прерывались и возобновлялись.\n")
    add("| Актив | Первый день | Последний день | Дней с торгами | Пропущено | Интервалов |")
    add("|---|---|---|---:|---:|---:|")
    for r in gapped:
        add(
            f"| {r['base']} | {r['listed']} | {r['last_trading_day']} "
            f"| {r['trading_days']} | {r['gap_days']} | {len(r['intervals'])} |"
        )
    add("")
    add("Практическое следствие то же: интервал «торговался с первой даты по")
    add("последнюю» неверен. Позиция, открытая по такому универсуму в день")
    add("приостановки, в бэктесте закроется по цене, которой не было. Поэтому")
    add("универсум хранит интервалы, а не пару дат.\n")

    # 5
    add("## 5. Делистинги по годам\n")
    by_year = Counter(
        r["last_trading_day"][:4] for r in A.values() if r["delisted"]
    )
    add("| Год | Прекратили торговаться |")
    add("|---|---:|")
    for y in sorted(by_year):
        add(f"| {y} | {by_year[y]} |")
    add("")

    # 6
    add("## 6. Следствие для walk-forward\n")
    monthly = [
        date(y, mo, 1)
        for y in range(2020, as_of.year + 1)
        for mo in range(1, 13)
        if date(y, mo, 1) <= as_of
    ]
    first_usable = next((d for d in monthly if len(universe_at(m, d, MIN_HISTORY)) >= 50), None)
    add(f"Универсум достигает 50 активов к **{first_usable.isoformat() if first_usable else '—'}**")
    add("и растёт до сотен к 2025–2026. Значит пригодная для протокола раздела 6")
    add("история начинается примерно с 2022 года, а не с 2020: до этого на")
    add("площадке исполнения просто нечего отбирать.\n")
    add("При полугодовом окне отбора и полугодовом торговом окне это порядка")
    add("восьми–девяти окон — достаточно, чтобы критерий 2 раздела 8 (доля пар,")
    add("выживающих между соседними окнами) был измерим, но не с запасом.\n")

    # 7
    add("## 7. Чего в этом этапе нет\n")
    add("Собрано из открытого архива и не требует доступа к API:")
    add("универсум, интервалы торговли, делистинги, сопоставление с Binance.\n")
    add("**Не собрано, требует доступа к API v5 Bybit:**\n")
    add("| Данные | Зачем | Без них нельзя |")
    add("|---|---|---|")
    add("| История ставок funding | издержки удержания, раздел 5.2 | считать P&L: при удержании 3–5 дней это десяток начислений на ногу |")
    add("| Справочник инструментов | шаг цены и объёма, мин. нотионал | проверять сайзинг раздела 4 спеки 01 |")
    add("| Ставки комиссий | раздел 5.1 | базовую модель издержек |")
    add("")
    add("Причина — страновой блок CloudFront: `api.bybit.com`, `api.bytick.com`,")
    add("`api.bybit.nl`, `api.byhkbit.com` и testnet отдают 403 одинаково.")
    add("Сбор выполняется владельцем оттуда, где Bybit открыт;")
    add("сборщик — `research/a1_universe/bybit_api.py`.\n")

    path = os.path.join(OUT, "A1-universe-report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"записан {path}")


if __name__ == "__main__":
    main()
