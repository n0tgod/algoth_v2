#!/usr/bin/env python3
"""
L2 — отчёт о сборе: что собралось и годится ли это для L3.

Отчёт описывает **тот прогон, который породил манифест**, а не текущее
состояние исходников: настройки читаются из артефакта. Урок R1, где
`report.py` импортировал пороги из кода прогона и отчёт нельзя было
собрать даже из готового JSON.

Три вопроса, на которые он отвечает
-----------------------------------

1. **Сколько собралось и с какими дырами.** Архив Binance публикует
   `metrics` не для всех символо-дней: у BSWUSDT в прогоне не нашлось
   248 суточных файлов из 640. Дыра опаснее пропуска — окно в 15 минут
   через неё означает месяц, — и хотя отбор событий это уже
   отбрасывает (`l1_cascades/probe.py`, поиск по времени), знать долю
   потерянных наблюдений надо до L3.
2. **Сколько символов переживает порог §7.3 спеки** — минимальный
   открытый интерес $5 млн. У актива с интересом в $200 тыс. падение на
   3 % есть закрытие одной позиции, а не каскад.
3. **Какова подтверждающая часть** после исключения двенадцати активов
   зонда. Вердикт §9 выносится только на ней, и её размер — это и есть
   бюджет доказательства гипотезы.

    .venv/bin/python research/l2_data/report.py
"""

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
SERIES = os.path.join(OUT, "oi_binance")

sys.path.insert(0, os.path.join(RESEARCH, "l1_cascades"))

# Разведочная часть §4 спеки 06. Вердикт по ней не выносится никогда.
EXPLORATORY = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
               "AVAXUSDT", "LINKUSDT", "ARBUSDT", "APTUSDT", "SUIUSDT",
               "INJUSDT", "SEIUSDT")
MIN_OI_USD = 5_000_000        # §7.3 спеки
STEP_MIN = 5


def stamp(sec):
    return datetime.fromtimestamp(sec, timezone.utc).date().isoformat()


def load():
    path = os.path.join(OUT, "oi_binance_manifest.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет манифеста {path} — сначала oi_binance.py")
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc.get("config", {}), doc.get("symbols", {})


def pct(v, q):
    return float(np.percentile(v, q)) if len(v) else float("nan")


def main():
    cfg, man = load()
    ok = {s: v for s, v in man.items() if v.get("rows")}
    counted = {s: v for s, v in ok.items()
               if not v.get("recovered") and v.get("days")}

    rows = sum(v["rows"] for v in ok.values())
    days = sum(v["days"] for v in counted.values())
    miss = sum(v.get("days_missing", 0) for v in counted.values())
    dups = sum(v.get("dups", 0) for v in ok.values())

    share = np.array([v["days_missing"] / v["days"]
                      for v in counted.values() if v["days"]])
    worst = sorted(((v["days_missing"] / v["days"], s, v)
                    for s, v in counted.items() if v["days"]),
                   reverse=True)[:15]

    oi = {s: v.get("median_oi_usd") for s, v in ok.items()
          if v.get("median_oi_usd")}
    big = {s for s, x in oi.items() if x >= MIN_OI_USD}
    confirm = sorted(set(ok) - set(EXPLORATORY))
    confirm_big = sorted(big - set(EXPLORATORY))

    # Полнота ряда: сколько точек есть против сетки в 5 минут на
    # промежутке жизни. Отдельно от «дней без файла»: файл может быть
    # неполным, и это видно только так.
    dense = []
    for s, v in ok.items():
        if not v.get("first") or not v.get("last"):
            continue
        span = (v["last"] - v["first"]) / 60 / STEP_MIN + 1
        if span > 0:
            dense.append(v["rows"] / span)
    dense = np.array(dense)

    lines = []
    w = lines.append
    w("# L2 — сбор открытого интереса, отчёт\n")
    w(f"Окно сбора: **{cfg.get('start')} … {cfg.get('end')}**. "
      f"Источник — набор `metrics` архива Binance, шаг 5 минут.\n")
    w("## 1. Что собралось\n")
    w("| Мера | Значение |")
    w("|---|---|")
    w(f"| Символов с рядом | **{len(ok)}** из {len(man)} |")
    w(f"| Точек интереса | **{rows:,}** |")
    w(f"| Символо-дней запрошено | {days:,} |")
    w(f"| Дней без файла | {miss:,} ({miss / max(days, 1):.2%}) |")
    w(f"| Дублей по метке | {dups:,} |")
    if len(man) - len(ok):
        w(f"| Символов без единой строки | {len(man) - len(ok)} |")
    w("")
    w("## 2. Дыры в рядах\n")
    w("Дыра опаснее пропуска: окно в 15 минут, взятое через неё, "
      "означает не пятнадцать минут, а месяц. Отбор событий такие "
      "величины отбрасывает (поиск точки по времени), но доля "
      "потерянных наблюдений — это доля потерянной статистики.\n")
    w("| Доля дней без файла | Символов |")
    w("|---|---|")
    for lo, hi in ((0.0, 0.001), (0.001, 0.01), (0.01, 0.05),
                   (0.05, 0.15), (0.15, 1.01)):
        n = int(((share >= lo) & (share < hi)).sum())
        w(f"| {lo:.1%} … {hi:.1%} | {n} |")
    w("")
    w(f"Процентили доли пропусков: 50-й {pct(share, 50):.2%}, "
      f"90-й {pct(share, 90):.2%}, 99-й {pct(share, 99):.2%}, "
      f"максимум {share.max():.2%}." if len(share) else "")
    w("")
    if len(dense):
        w(f"Плотность ряда против сетки в 5 минут: медиана "
          f"{np.median(dense):.3f}, 10-й процентиль {pct(dense, 10):.3f}, "
          f"минимум {dense.min():.3f}. Величина ниже единицы означает "
          f"неполные файлы, а не отсутствующие.\n")
    w("Худшие по доле пропусков:\n")
    w("| Символ | Дней | Без файла | Доля |")
    w("|---|---|---|---|")
    for sh, s, v in worst:
        w(f"| {s} | {v['days']} | {v['days_missing']} | {sh:.1%} |")
    w("")
    w("## 3. Порог по размеру инструмента\n")
    w(f"Спека 06 §7.3 требует открытого интереса не ниже "
      f"**${MIN_OI_USD:,}** на момент события: у актива с интересом в "
      f"$200 тыс. падение на 3 % есть закрытие одной позиции, а не "
      f"каскад. Здесь порог применён к медиане по всей истории — это "
      f"оценка сверху для L3, где он проверяется на каждую дату.\n")
    w("| Мера | Значение |")
    w("|---|---|")
    w(f"| Символов с измеримым интересом | {len(oi)} |")
    w(f"| Из них выше ${MIN_OI_USD:,} | **{len(big)}** "
      f"({len(big) / max(len(oi), 1):.0%}) |")
    if oi:
        v = np.array(sorted(oi.values()))
        w(f"| Медиана медианного интереса | ${np.median(v):,.0f} |")
        w(f"| 10-й процентиль | ${pct(v, 10):,.0f} |")
    w("")
    w("## 4. Подтверждающая часть\n")
    w("Вердикт раздела 9 спеки выносится только на ней; двенадцать "
      "активов зонда L1 в неё не входят никогда.\n")
    w("| Часть | Символов |")
    w("|---|---|")
    w(f"| Разведочная (зонд L1) | {len(EXPLORATORY)} |")
    w(f"| Подтверждающая, всего | **{len(confirm)}** |")
    w(f"| Подтверждающая, выше порога размера | **{len(confirm_big)}** |")
    w("")
    w(f"Разведочная часть дала 168 эпизодов на двенадцати активах. "
      f"Подтверждающая шире по числу инструментов в "
      f"{len(confirm_big) / len(EXPLORATORY):.1f} раза — это и есть "
      f"рычаг измеримости, ради которого гипотеза 5 меняет знаменатель "
      f"доказательства (§2 спеки). Во сколько раз вырастет число "
      f"эпизодов, отсюда не следует: события рынка одновременны, и "
      f"слипание в эпизоды (§7.5) съест часть прироста. Величину даст "
      f"L3, предполагать её здесь нельзя.\n")
    w("## 5. Чего в этом отчёте нет\n")
    w("Ни одного числа о доходности. L2 — только данные; отбор "
      "событий, контроли и нули идут в L3, вердикт — в L5.\n")

    text = "\n".join(lines)
    dst = os.path.join(OUT, "L2-data-report.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\nзаписано {dst}")


if __name__ == "__main__":
    main()
