#!/usr/bin/env python3
"""
A1 — отчёт о загруженных данных.

Раздел 10 спеки 02, артефакт 1: покрытие, пропуски, инструменты в карантине.
Полноценный отчёт о гигиене — этап A2, здесь фиксируется то, что видно уже
на загрузке: сошлись ли контрольные суммы, где не хватает месяцев, где
пропущены бары внутри наблюдаемого диапазона.

Отдельно считается **дифференциал funding между активами**. Причина в том,
что парная позиция держит одну ногу в лонг, вторую в шорт, и funding по ним
сокращается не полностью. Разница ставок — измеримый денежный поток того же
порядка, что ожидаемая прибыль от возврата спреда, и открытый вопрос 12.4
спеки 01 спрашивает ровно про это: остаётся ли funding только издержкой или
обязан входить в критерий отбора пар.

    python3 data_report.py
"""

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def load(name):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pct(x, n):
    return f"{100 * x / n:.1f} %" if n else "—"


def quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    s = sorted(vals)
    if not s:
        return {}
    out = {}
    for q in qs:
        i = min(len(s) - 1, int(q * (len(s) - 1)))
        out[q] = s[i]
    return out


def main():
    universe = load("universe.json")
    klines = load("klines_inventory_15m.json")
    funding = load("funding_binance_summary.json")

    if universe is None:
        raise SystemExit("нет universe.json — сначала universe.py")

    lines = []
    add = lines.append

    add("# Отчёт A1 — загруженные данные\n")
    add("Сгенерирован `research/a1_universe/data_report.py`.")
    add("Раздел 10 спеки 02, артефакт 1. Полная гигиена — этап A2;")
    add("здесь фиксируется то, что видно на загрузке.\n")
    add(f"Универсум на срезе **{universe['archive_as_of']}**.\n")
    add("---\n")

    # ---------------------------------------------------------------- свечи
    add("## 1. Свечи Binance\n")
    if not klines:
        add("Прогон не завершён — `klines_inventory_15m.json` отсутствует.\n")
    else:
        meta, A = klines["meta"], klines["assets"]
        months_ok = sum(v["months_ok"] for v in A.values())
        absent = sum(len(v["months_absent"]) for v in A.values())
        bad = sum(len(v["months_bad"]) for v in A.values())
        bars = sum(v["bars"] for v in A.values())
        exp = sum(v["bars_expected"] for v in A.values())
        gb = sum(v["bytes"] for v in A.values()) / 1024**3

        add(f"Таймфрейм **{meta['interval']}**, активов "
            f"{meta['assets_loaded']} из {meta['assets_in_universe']}"
            f"{'' if meta['complete'] else ' (пилот)'}.\n")
        add("| | |")
        add("|---|---:|")
        add(f"| Символо-месяцев загружено | {months_ok:,} |".replace(",", " "))
        add(f"| Месяцев отсутствует в архиве | {absent} |")
        add(f"| Месяцев с битой контрольной суммой | {bad} |")
        add(f"| Баров | {bars:,} |".replace(",", " "))
        add(f"| Пропущено баров внутри диапазона | {exp - bars:,} ({pct(exp-bars, exp)}) |".replace(",", " "))
        add(f"| Объём сжатого архива | {gb:.2f} ГБ |")
        add("")
        add("Контрольная сумма сверяется по каждому месячному файлу. Пропуски")
        add("считаются **внутри наблюдаемого диапазона**: месяц листинга и месяц")
        add("делистинга неполны по построению, и записывать их в недобор —")
        add("значит завести себе ложную проблему гигиены.\n")

        worst = sorted(
            (v for v in A.values() if v["bars_expected"]),
            key=lambda v: -v["missing_bars"] / v["bars_expected"],
        )[:15]
        holed = [v for v in worst if v["missing_bars"] > 0]
        if holed:
            add("### 1.1 Где пропуски\n")
            add("| Актив | Баров | Пропущено | Доля |")
            add("|---|---:|---:|---:|")
            for v in holed:
                add(f"| {v['binance_symbol']} | {v['bars']:,} | {v['missing_bars']:,} "
                    f"| {pct(v['missing_bars'], v['bars_expected'])} |".replace(",", " "))
            add("")
            add("Пропуск баров — остановка торгов или сбой площадки. Раздел 2.4")
            add("запрещает заполнять их интерполяцией: для нас это реальные")
            add("события, на которых срабатывают стопы.\n")
        else:
            add("Пропусков баров внутри наблюдаемых диапазонов нет ни у одного")
            add("актива. Архив Binance по универсуму сплошной.\n")

        missing_months = [(v["binance_symbol"], v["months_absent"])
                          for v in A.values() if v["months_absent"]]
        if missing_months:
            add("### 1.2 Отсутствующие месяцы\n")
            add(f"У {len(missing_months)} активов часть месяцев в архиве отсутствует.\n")
            add("| Актив | Месяцев нет | Какие |")
            add("|---|---:|---|")
            for sym, ms in sorted(missing_months, key=lambda x: -len(x[1]))[:15]:
                shown = ", ".join(ms[:6]) + (" …" if len(ms) > 6 else "")
                add(f"| {sym} | {len(ms)} | {shown} |")
            add("")

        add("### 1.3 Схема файлов — вход для A2\n")
        add("Месячный CSV, 12 колонок. В файлах до 2025 года заголовка нет,")
        add("в поздних есть — загрузчик обрабатывает оба варианта.\n")
        add("| # | Колонка | Примечание |")
        add("|---:|---|---|")
        for i, (col, note) in enumerate([
            ("open_time", "мс, UTC — ключ времени"),
            ("open", ""),
            ("high", "нужен для консервативной проверки стопа внутри бара"),
            ("low", "то же"),
            ("close", "цена сигнала: z считается на закрытии бара"),
            ("volume", "в базовом активе"),
            ("close_time", "мс"),
            ("quote_volume", "в USDT — основа фильтра ликвидности"),
            ("count", "число сделок — поле `trades` схемы раздела 2.3"),
            ("taker_buy_volume", "агрессивные покупки"),
            ("taker_buy_quote_volume", ""),
            ("ignore", "служебное, всегда 0"),
        ]):
            add(f"| {i} | `{col}` | {note} |")
        add("")
        add("Целевая схема хранилища раздела 2.3 — `(symbol, time, o, h, l, c,")
        add("v, trades)` — покрывается полностью. `quote_volume` берётся сверх")
        add("неё: фильтр ликвидности раздела 2.1.1 нужно считать в долларах,")
        add("а не в единицах базового актива, иначе активы несравнимы.\n")

    # -------------------------------------------------------------- funding
    add("## 2. Ставки funding Binance\n")
    add("> Это **не издержки**. Раздел 5.2 требует считать их по ставкам")
    add("> площадки исполнения; ставки Bybit живут только в API и собираются")
    add("> на VPS. Ряд Binance нужен как мера расхождения между площадками")
    add("> и как перекрёстная проверка раздела 7.\n")

    if not funding:
        add("Прогон не завершён — `funding_binance_summary.json` отсутствует.\n")
    else:
        A = funding["assets"]
        withdata = {b: v for b, v in A.items() if v.get("records")}
        add(f"Активов с данными: {len(withdata)} из {len(A)}. "
            f"Записей: {sum(v['records'] for v in withdata.values()):,}".replace(",", " ") + "\n")

        ann = {b: v["annualized_mean_pct"] for b, v in withdata.items()}
        q = quantiles(list(ann.values()))
        add("### 2.1 Средняя ставка в пересчёте на год\n")
        add("| Квантиль | Годовых |")
        add("|---|---:|")
        for k, v in q.items():
            add(f"| {int(k*100)} % | {v:+.1f} % |")
        add("")
        hi = sorted(ann.items(), key=lambda x: -x[1])[:8]
        lo = sorted(ann.items(), key=lambda x: x[1])[:8]
        add("| Самые дорогие для лонга | Годовых | | Самые дорогие для шорта | Годовых |")
        add("|---|---:|---|---|---:|")
        for (b1, v1), (b2, v2) in zip(hi, lo):
            add(f"| {b1} | {v1:+.1f} % | | {b2} | {v2:+.1f} % |")
        add("")

        # Дифференциал по всем парам универсума — считается точно,
        # 700 активов дают порядка 245 000 пар.
        vals = sorted(ann.values())
        diffs = [abs(vals[i] - vals[j])
                 for i in range(len(vals)) for j in range(i + 1, len(vals))]
        spread_q = quantiles(diffs)
        add("### 2.2 Дифференциал между ногами\n")
        add("Парная позиция держит одну ногу в лонг, вторую в шорт, поэтому")
        add("платит не ставку, а **разницу ставок**. Распределение модуля")
        add(f"разницы по всем {len(diffs):,} парам универсума:\n".replace(",", " "))
        add("| Квантиль | Годовых |")
        add("|---|---:|")
        for k, v in spread_q.items():
            add(f"| {int(k*100)} % | {v:.1f} % |")
        add("")
        add("**Как это читать.** Дифференциал не является издержкой сам по себе:")
        add("знак зависит от того, какая нога в лонге, а направление задаёт")
        add("z-оценка, а не funding. При симметричном чередовании направлений")
        add("вклад в среднем гасится.")
        add("")
        add("Существенно другое — величина и устойчивость. Разница такого")
        add("порядка сравнима с целевой доходностью раздела 8, а ставки")
        add("персистентны: актив с дорогим фондированием остаётся дорогим")
        add("месяцами. Значит у пары с устойчиво разным funding по ногам")
        add("возникает систематический денежный поток, знак которого задаётся")
        add("тем, в какую сторону эта пара обычно торгуется. Это измеримо и")
        add("не является шумом.")
        add("")
        add("Отсюда открытый вопрос 12.4 спеки 01 — оставить funding только")
        add("издержкой или включить в критерий отбора пар — переходит из")
        add("теоретических в требующие проверки на данных. Окончательные числа")
        add("считаются по ставкам Bybit; эти показывают порядок величины.\n")

        # Покрытие: ряд funding обязан накрывать торговое окно на Bybit.
        U = universe["assets"]
        late, early = [], []
        for b, v in withdata.items():
            rec = U.get(b)
            if not rec:
                continue
            f_first, f_last = v["first"][:10], v["last"][:10]
            if f_first > rec["listed"]:
                late.append((b, rec["listed"], f_first,
                             (datetime.fromisoformat(f_first)
                              - datetime.fromisoformat(rec["listed"])).days))
            if f_last < rec["last_trading_day"]:
                early.append((b, f_last, rec["last_trading_day"],
                              (datetime.fromisoformat(rec["last_trading_day"])
                               - datetime.fromisoformat(f_last)).days))

        add("### 2.3 Покрытие торгового окна\n")
        add("Ряд funding обязан накрывать период, когда инструмент торговался")
        add("на площадке исполнения. Там, где не накрывает, издержки удержания")
        add("за этот отрезок посчитать нечем.\n")
        add(f"- ряд начинается **позже** листинга на Bybit: {len(late)} активов")
        add(f"- ряд кончается **раньше** делистинга на Bybit: {len(early)} активов\n")

        if early:
            add("Второй случай — обратный тому, что предусматривает раздел 2.2:")
            add("не история площадки исполнения короче, а история Binance.")
            add("Инструмент ушёл с Binance, продолжая торговаться на Bybit.\n")
            add("| Актив | Funding до | Торговался на Bybit до | Не покрыто, дней |")
            add("|---|---|---|---:|")
            for b, f_last, b_last, days in sorted(early, key=lambda x: -x[3])[:12]:
                add(f"| {b} | {f_last} | {b_last} | {days} |")
            add("")

        if late:
            add("| Актив | Листинг на Bybit | Funding с | Не покрыто, дней |")
            add("|---|---|---|---:|")
            for b, listed, f_first, days in sorted(late, key=lambda x: -x[3])[:12]:
                add(f"| {b} | {listed} | {f_first} | {days} |")
            add("")

        add("Для издержек это некритично — там авторитетны ставки Bybit, а не")
        add("Binance. Но перекрёстную проверку раздела 7 на этих отрезках")
        add("провести не удастся, и при расхождении результатов по ним нельзя")
        add("будет отличить артефакт площадки от дефекта данных.\n")

    path = os.path.join(OUT, "A1-data-report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"записан {path}")


if __name__ == "__main__":
    main()
