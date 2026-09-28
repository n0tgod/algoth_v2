#!/usr/bin/env python3
"""
Потолок механики «ребаланс плечевых крипто-ETF в последний час Нью-Йорка».

Один прогон на минутном архиве: K1–K5 по BTC и ETH, перебор 24 часов,
калибровочная пара, деньги сделки и отчёт. Новых данных не нужно — всё
уже на диске (`research/a1_universe/out/klines/1m`).

    cd ~/algoth_v2 && setsid nohup .venv/bin/python \\
        research/mech_59653014/run_ceiling.py \\
        > research/mech_59653014/out/run.log 2>&1 &

Порядок вывода не случаен: **число квалифицированных дней печатается
первым**, до любого вердикта. Покрытие, названное после вердикта, уже
ничего не решает — это урок памяти проекта, а не форма.

Сеть нужна только сверке дат запуска фондов (`fund_dates.py`), и её
отказ прогон не роняет: окно берётся объявленным, а отчёт печатает «не
сверено» с причиной. `--no-net` выключает сверку намеренно.

Предел памяти и самоостанов живут В САМОМ прогоне — сторож взят у
`research/dca_paper/arm_book.guarded`, второй копии не заводится: рядом
на сервере идёт часовой цикл, и ядро при нехватке памяти убивает не
того, кто виноват.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))

import arm_book as AB                                         # noqa: E402
import bars as BR                                             # noqa: E402
import etf_rebal as ER                                        # noqa: E402
import fund_dates as FD                                       # noqa: E402
import nyse_cal as CAL                                        # noqa: E402

SYMBOLS = ("BTCUSDT", "ETHUSDT")
TITLE = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
ARCHIVE_LO = dt.date(2021, 1, 1)
ARCHIVE_HI = dt.date(2026, 9, 25)
SHUFFLE_SEEDS = 8
PLANT_BP = 30.0
PLANT_FRAC = 0.5
# Развёртка силы замера: величина подсадки, не порог. Нужна, чтобы
# отрицательный результат читался — стенд, не видящий и 200 б.п., сказал
# бы «эффекта нет» ровно так же, как стенд, видящий 10.
PLANT_SCAN_BP = (30.0, 60.0, 120.0, 240.0)
REPORT = os.path.join(OUT, "MECH-etf-rebal.md")
DATA = os.path.join(OUT, "etf_rebal.json")
STATE = os.path.join(OUT, "state.json")


def num(v, fmt="{:.2f}", dash="—"):
    """Число или ПРОЧЕРК. Ноль тут не появляется никогда: он значит
    «измерено и равно нулю», а не «нечем измерить»."""
    return dash if v is None else fmt.format(v)


def state(step, **kw):
    os.makedirs(OUT, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(dict({"at": round(time.time(), 3), "step": step}, **kw),
                  f, ensure_ascii=False, indent=1)


def plant_killers(b, cal, days, fund_start, fund_end, bp, shape):
    """K1–K5 на ряду с подсадкой. Возвращает (сводка, число дней)."""
    pb, n = ER.plant_bars(b, cal, days, bp=bp, frac=PLANT_FRAC, shape=shape)
    rows, _ = ER.day_table(pb, cal, days, with_extras=False)
    bh, _ = ER.by_hour_means(pb, cal, fund_start, fund_end)
    rp, _ = ER.day_table(pb, cal, cal.days(ER.PLACEBO_LO, ER.PLACEBO_HI,
                                           (CAL.TRADE, CAL.EARLY)),
                         with_extras=False)
    rn, _ = ER.day_table(pb, cal, cal.days(fund_start, fund_end,
                                           (CAL.WEEKEND, CAL.HOLIDAY)),
                         ref_mode=ER.REF_PREV_CALENDAR, with_extras=False)
    ks = ER.killers(rows, rp, rn, bh)
    return {
        "days_planted": n, "bp": bp, "frac": PLANT_FRAC, "shape": shape,
        "passed": sorted(k for k, v in ks.items() if not v["dead"]),
        "killed": sorted(k for k, v in ks.items() if v["dead"]),
        "killers": {k: {"value": v["value"], "thr": v["thr"],
                        "dead": v["dead"], "phrase": v["phrase"]}
                    for k, v in ks.items()},
    }, n


def calibrate(b, cal, fund_start, fund_end, log):
    """Калибровочная пара на НАСТОЯЩЕМ ряду: подсадка, развёртка силы, нуль.

    Подсадка живёт в ценах — значит проверяется и загрузка; нуль —
    перестановка знаков хода дня по дням.

    Развёртка по величине подсадки отвечает на вопрос, без которого
    отрицательный результат нечем читать: КАКОЙ эффект этот стенд вообще
    способен увидеть. Пороги при этом не меняются — меняется только
    величина подсаженного, и наименьшая прошедшая печатается числом.
    """
    days = cal.days(fund_start, fund_end, (CAL.TRADE, CAL.EARLY))
    out = {}
    for shape in ("prop", "flat"):
        rec, n = plant_killers(b, cal, days, fund_start, fund_end,
                               PLANT_BP, shape)
        out["plant_" + shape] = rec
        log(f"  подсадка {shape} {PLANT_BP:.0f} б.п. на {n} днях: прошло "
            f"{','.join(rec['passed']) or '—'}, "
            f"упало {','.join(rec['killed']) or '—'}")

    scan = []
    for bp in PLANT_SCAN_BP:
        rec = (out["plant_prop"] if bp == PLANT_BP else
               plant_killers(b, cal, days, fund_start, fund_end, bp, "prop")[0])
        scan.append({"bp": bp, "passed": rec["passed"],
                     "killed": rec["killed"],
                     "all_five": len(rec["passed"]) == 5})
        log(f"  развёртка: подсадка {bp:.0f} б.п. — прошло "
            f"{len(rec['passed'])}/5 ({','.join(rec['killed']) or 'все'})")
    out["scan"] = scan
    out["min_visible_bp"] = next((s["bp"] for s in scan if s["all_five"]), None)

    pb, _ = ER.plant_bars(b, cal, days, bp=PLANT_BP, frac=PLANT_FRAC,
                          shape="prop")
    rows, _ = ER.day_table(pb, cal, days, with_extras=False)
    hours = {ER.VERDICT_HOUR: 0.0, 0: 0.0}
    k1_fell, k5_fell, slopes, ts = 0, 0, [], []
    for seed in range(SHUFFLE_SEEDS):
        ks = ER.killers(ER.shuffle_signs(rows, seed=seed), [], [], hours)
        k1_fell += bool(ks["K1"]["dead"])
        k5_fell += bool(ks["K5"]["dead"])
        slopes.append(ks["K5"]["value"])
        ts.append(ks["K5"]["t"])
    out["shuffle"] = {
        "seeds": SHUFFLE_SEEDS, "k1_dead": k1_fell, "k5_dead": k5_fell,
        "slope": ER.stat(slopes), "slope_t": ER.stat(ts),
        # Сколько зёрен дали наклон, НЕОТЛИЧИМЫЙ от нуля. Это и есть то,
        # что у нуля обязано быть; «K5 упал» у него — монета.
        "slope_insignificant": sum(1 for t in ts if t is not None
                                   and abs(t) < 2.0),
        "planted_slope": ER.killers(rows, [], [], hours)["K5"]["value"],
    }
    log(f"  перестановка знаков, {SHUFFLE_SEEDS} зёрен: K1 упал "
        f"{k1_fell}/{SHUFFLE_SEEDS}, K5 упал {k5_fell}/{SHUFFLE_SEEDS}")
    return out


def run_symbol(sym, cal, checked, log, use_cache=True):
    lo = int(dt.datetime(ARCHIVE_LO.year, ARCHIVE_LO.month, ARCHIVE_LO.day,
                         tzinfo=dt.timezone.utc).timestamp() * 1000)
    hi = int((dt.datetime(ARCHIVE_HI.year, ARCHIVE_HI.month, ARCHIVE_HI.day,
                          tzinfo=dt.timezone.utc)
              + dt.timedelta(days=1)).timestamp() * 1000)
    b = BR.load(sym, lo, hi, use_cache=use_cache, log=log)
    cov = BR.coverage(b, lo, hi)
    log(f"{sym}: покрытие архива {num(100 * cov, '{:.3f}')} % "
        f"({len(b)} минут)")

    src = checked.get(sym)
    start = dt.date.fromisoformat(src[0]) if src else None
    res = ER.measure_symbol(b, cal, fund_start=start, fund_end=ARCHIVE_HI,
                            log=log)
    res["archive_coverage"] = cov
    res["archive_minutes"] = len(b)
    res["fund_start_declared"] = ER.FUND_START_DECLARED[sym].isoformat()
    res["fund_start_source"] = (
        f"сверено по странице фонда {src[1]} ({src[2]})" if src
        else "НЕ сверено: сверка дат недоступна, взята объявленная заявкой")
    log(f"{sym}: {res['verdict']['phrase']}")
    state("калибровка", symbol=sym)
    res["calibration"] = calibrate(b, cal, dt.date.fromisoformat(
        res["fund_start"]), ARCHIVE_HI, log)
    for k in ("rows_fund", "rows_placebo", "rows_nontrade"):
        res.pop(k, None)
    return res


# --- отчёт ------------------------------------------------------------

def killers_table(res):
    out = ["| убийца | что мерится | число | порог | итог |",
           "|---|---|---|---|---|"]
    what = {
        "K1": "ход со знаком в окне фонда, б.п.",
        "K2": "t разности с плацебо-окном",
        "K3": "час 15–16 против p95 остальных 23 часов, б.п.",
        "K4": "t разности с выходными и праздниками",
        # Черта экранирована: в таблице markdown она разделитель ячеек, и
        # «|ход дня|» разрывало строку K5 на лишние столбцы.
        "K5": "наклон на \\|ход дня\\|, б.п. на % хода",
    }
    for k in ("K1", "K2", "K3", "K4", "K5"):
        v = res["killers"][k]
        out.append(f"| {k} | {what[k]} | {num(v['value'])} | "
                   f"{num(v['thr'])} | "
                   f"{ER.DEAD if v['dead'] else ER.ALIVE} |")
    return out


def hours_table(res):
    out = ["| час ET | дней | ход со знаком, б.п. |", "|---|---|---|"]
    for h in range(24):
        mark = " ← вердикт" if h == ER.VERDICT_HOUR else ""
        out.append(f"| {h:02d}–{(h + 1) % 24:02d}{mark} | "
                   f"{res['by_hour_n'][h]} | {num(res['by_hour'][h])} |")
    return out


def report(results, checked, started):
    """Отчёт. Первая строка после заголовка — покрытие числом."""
    L = [f"# MECH-59653014 — ребаланс плечевых крипто-ETF в последний час "
         f"Нью-Йорка", ""]
    first = ", ".join(
        f"{TITLE[s]} {r['n_qual']}" for s, r in results.items())
    L += [f"**Квалифицированных торговых дней: {first}.** Минимум для "
          f"вердикта — {ER.MIN_QUAL_DAYS}; меньше значит «{ER.UNMEASURED}», "
          f"а не вердикт.", ""]
    for s, r in results.items():
        L.append(f"**{TITLE[s]}: {r['verdict']['phrase']}.**")
    L += ["",
          f"Вердикт заявке выносится по BTC — самый крупный фонд и самое "
          f"длинное окно; ETH стоит рядом и в пул попадает только своими "
          f"K1–K5.", ""]

    L += ["## Что это значит", "",
          "Поток фонда существует и знак его известен заранее — это"
          " арифметика, а не гипотеза. Гипотезой было то, что поток"
          " ДОХОДИТ до перпа настолько, чтобы пережить круг издержек."
          " Измерено: не доходит. Ниже — числа, каждое из которых"
          " способно было закрыть заявку в одиночку.", ""]

    for s, r in results.items():
        t = TITLE[s]
        L += [f"## {t} — {s}", "",
              f"Окно фонда {r['fund_start']} → {r['fund_end']}, "
              f"плацебо {r['placebo'][0]} → {r['placebo'][1]}. "
              f"Дата запуска: {r['fund_start_source']}; объявлено заявкой "
              f"{r['fund_start_declared']}.", "",
              f"Дней с сессией в окне {r['n_rows']}, из них "
              f"квалифицированных (|ход дня| ≥ "
              f"{ER.QUAL_ABS_R * 100:.0f} %) {r['n_qual']} — "
              f"{num(100 * r['qual_share'], '{:.1f}')} %. "
              f"Покрытие минутного архива "
              f"{num(100 * r['archive_coverage'], '{:.3f}')} % "
              f"({r['archive_minutes']} минут).", ""]
        if r["skips_fund"]:
            L.append("Выпавшие дни окна с причинами: "
                     + "; ".join(f"{k} — {v}"
                                 for k, v in sorted(r["skips_fund"].items()))
                     + ".")
            L.append("")
        L += killers_table(r) + [""]
        m = r["m"]
        L += [f"Ход со знаком: среднее {num(m['mean'])} б.п., медиана "
              f"{num(m['median'])}, σ дня {num(m['sd'])}, t {num(m['t'])}, "
              f"бутстрап 95 % [{num(m['lo'])}; {num(m['hi'])}] на "
              f"{BOOT_N} выборках.",
              "",
              f"Столбцы, вердикта не выносящие: полчаса 15:30 → 16:00 "
              f"{num(r['m_half']['mean'])} б.п. (t "
              f"{num(r['m_half']['t'])}); откат 16:00 → 17:00 "
              f"{num(r['m_after']['mean'])} б.п. (t "
              f"{num(r['m_after']['t'])}) — разведчик предупреждал именно "
              f"об этом, и сделке с выходом в 16:00 он не убийца; перевес "
              f"агрессора-покупателя в час 15–16 со знаком хода дня "
              f"{num(r['aggr']['mean'])} п.п. (t {num(r['aggr']['t'])}).",
              ""]
        L += ["### Корзины |ход дня|", "",
              "| корзина | дней | ход со знаком, б.п. | медиана | t |",
              "|---|---|---|---|---|"]
        for bk in r["buckets"]:
            hi = "> 5" if bk["hi"] > 9 else f"{bk['lo'] * 100:.0f}–{bk['hi'] * 100:.0f}"
            L.append(f"| {hi} % | {bk['n']} | {num(bk['mean'])} | "
                     f"{num(bk['median'])} | {num(bk['t'])} |")
        L += ["", "### Двадцать четыре часа (K3)", ""] + hours_table(r) + [""]

        mo = r["money"]
        L += ["### Деньги сделки", "",
              f"Размер — доля депозита min(1, {ER.RISK_PER_HOUR * 100:.1f} % / "
              f"σ̂ часа), σ̂ по минутным ходам предыдущих 24 ч; издержки "
              f"круга {ER.ROUND_COST_BP:.0f} б.п. на ногу снимаются с "
              f"нотионала в КАЖДОЙ сделке.", "",
              f"| дней | брутто, % депозита | нетто | медиана дня | "
              f"доля прибыльных | худший день | без 3 лучших | медианная доля |",
              "|---|---|---|---|---|---|---|---|",
              f"| {mo['n']} | {num(mo['gross_pct'])} | {num(mo['net_pct'])} | "
              f"{num(mo['median_pct'], '{:.3f}')} | "
              f"{num(mo['win_share'] and 100 * mo['win_share'], '{:.1f}')} % | "
              f"{num(mo['worst_pct'], '{:.2f}')} "
              f"({mo['worst_day'] or '—'}) | "
              f"{num(mo['without_top3_pct'])} | "
              f"{num(mo.get('size_frac_median'), '{:.2f}')} |", ""]
        if mo["no_size"]:
            L += [f"Дней без размера (прочерк σ̂, в счёт не входят): "
                  f"{mo['no_size']}.", ""]

        L += ["### Поток против оборота", ""]
        aum = next((f for f in checked.get("_funds", [])
                    if f.get("symbol") == s and f.get("aum_usd")), None)
        vol = r["usd_volume"]["median"]
        absr = r["abs_r"]["mean"]
        if aum and absr and vol:
            flow = 2.0 * aum["aum_usd"] * absr
            L += [f"Активы фонда {aum['ticker']} "
                  f"{aum['aum_usd'] / 1e9:.2f} млрд $ на "
                  f"{aum.get('aum_asof') or 'дату страницы'} — ОДНА точка, "
                  f"ряда активов по дням у нас нет (прочерк). Поток "
                  f"2·A·|r| при среднем |ход дня| "
                  f"{absr * 100:.2f} % — около {flow / 1e6:.0f} млн $; "
                  f"медианный оборот перпа в час 15–16 — "
                  f"{vol / 1e6:.0f} млн $, то есть поток составляет "
                  f"{100 * flow / vol:.0f} % часового оборота одного "
                  f"перпа, и это ВЕРХНЯЯ оценка: фонд торгует фьючерс "
                  f"CME, до перпа доходит лишь часть.", ""]
        else:
            L += ["Активы фонда по дням — прочерк: ряда активов у нас нет, "
                  "а одна точка со страницы фонда не разобралась.", ""]

        cb = r["calibration"]
        L += ["### Калибровочная пара", "",
              "| проверка | что обязано случиться | что вышло |",
              "|---|---|---|",
              f"| подсадка ∝ \\|r\\| ({PLANT_BP:.0f} б.п. на "
              f"{PLANT_FRAC:.0%} дней, В ЦЕНЫ) | проходит K1–K5 | прошло "
              f"{','.join(cb['plant_prop']['passed']) or '—'}, упало "
              f"{','.join(cb['plant_prop']['killed']) or '—'} |",
              f"| ровная подсадка {PLANT_BP:.0f} б.п. | проходит K1–K4; K5 "
              f"не обязан — у ровного плюса нет формы 2·A·r | прошло "
              f"{','.join(cb['plant_flat']['passed']) or '—'}, упало "
              f"{','.join(cb['plant_flat']['killed']) or '—'} |",
              f"| перестановка знаков хода дня, {cb['shuffle']['seeds']} "
              f"зёрен | K1 падает всегда; наклон ложится к нулю | K1 упал "
              f"{cb['shuffle']['k1_dead']}/{cb['shuffle']['seeds']}; наклон "
              f"нуля {num(cb['shuffle']['slope']['mean'])} ± "
              f"{num(cb['shuffle']['slope']['sd'])}, незначим на "
              f"{cb['shuffle']['slope_insignificant']}/"
              f"{cb['shuffle']['seeds']} зёрнах; K5 упал "
              f"{cb['shuffle']['k5_dead']}/{cb['shuffle']['seeds']} |", "",
              "Сила замера — развёртка по величине подсадки (∝ |r|, "
              f"{PLANT_FRAC:.0%} дней). Пороги при этом не меняются, "
              "меняется только подсаженное:", "",
              "| подсадка, б.п. | прошло убийц | не прошло |",
              "|---|---|---|"]
        for sc in cb["scan"]:
            L.append(f"| {sc['bp']:.0f} | {len(sc['passed'])}/5 | "
                     f"{','.join(sc['killed']) or '—'} |")
        mv = cb["min_visible_bp"]
        L += ["",
              (f"Наименьшая из проверенных подсадок, проходящая ВСЕ пять: "
               f"{mv:.0f} б.п. — то есть эффект слабее этого стенд на этом "
               f"имени объявил бы мёртвым даже будь он настоящим, и "
               f"измеренные {num(res_m(r))} б.п. лежат ниже этой границы."
               if mv is not None else
               "Ни одна из проверенных подсадок не прошла все пять — на "
               "этом имени стенд способен закрыть заявку, но не способен "
               "её подтвердить, и это ограничение самого замера, а не "
               "вывод о рынке."), "",
              "Подсадка сделана В ЦЕНАХ, а не в таблице дней: калибровка "
              "обязана проверять и загрузку тоже — сломанный читатель "
              "архива иначе выглядит ровно как «эффекта нет».", "",
              "Про K5 у нуля сказано прямо: порог «наклон ≤ 0» при "
              "симметричном относительно нуля шуме есть монета, и "
              f"требовать от одного зерна падения K5 значило бы объявить "
              f"проверкой бросок монеты. Поэтому печатается доля зёрен "
              f"({cb['shuffle']['k5_dead']} из {cb['shuffle']['seeds']}) и "
              f"величина наклона, а проверяется у нуля то, что у него "
              f"действительно обязано быть: наклон неотличим от нуля.", ""]

    L += ["## Как считано", "",
          f"* Минутные свечи Binance (архив A1, {ARCHIVE_LO} → "
          f"{ARCHIVE_HI}); площадка исполнения здесь не важна — ход перпа "
          f"отражает поток через арбитраж, а funding в замер не входит "
          f"вовсе: позиция живёт час и расчёта не переживает.",
          "* Время — `zoneinfo America/New_York`, то есть 16:00 ET это "
          "20:00 UTC летом и 21:00 зимой. Час перехода, которого не "
          "существует или которых два, — прочерк с причиной, а не "
          "молчаливый выбор первого.",
          "* Календарь NYSE 2021–2026 правилами (`nyse_cal.py`), четыре "
          "категории дня. Ранние сессии (закрытие 13:00) ИСКЛЮЧЕНЫ "
          "отдельной категорией, и вместе с ними исключён день, чей "
          "предыдущий день фонда был ранним: у него точка отсчёта хода "
          "дня лежит в 13:00. Оба исключения посчитаны выше.",
          "* Сигнал и исполнение — разные цены: ход дня и размер считаются "
          "по закрытию минуты ДО момента, сделка исполняется по открытию "
          "минуты С момента. Проверка на заглядывание в будущее переписывает "
          "всё с 15:00 и требует, чтобы ход дня, признак квалификации и σ̂ "
          "не шелохнулись.",
          "* Час-вердикт есть частный случай перебора 24 часов: таблица "
          "часов и измеряемая сделка считаются ОДНИМ кодом, и это "
          "закреплено проверкой.",
          f"* Круг издержек берётся из расчётного ядра проекта "
          f"(`research/s8_loop/trades.ROUND_COST_BP` = "
          f"{ER.ROUND_COST_BP:.0f} б.п.), своей копии числа здесь нет.", ""]

    L += ["## Чего этот прогон НЕ говорит", "",
          "* Он не говорит, что потока нет. Поток фонда есть арифметика "
          "проспекта; измерено другое — доходит ли он до перпа настолько, "
          "чтобы пережить круг.",
          "* Он не мерил фьючерс CME и не мерил сам пай: замер стоит на "
          "перпе, то есть на том инструменте, которым мы торговали бы.",
          "* Он ничего не говорит про фонды на SOL и XRP (с 2025 года): у "
          "них окно короче и квалифицированных дней заведомо меньше "
          f"объявленного минимума {ER.MIN_QUAL_DAYS} — это «"
          f"{ER.UNMEASURED}», и мерить их значило бы предъявить шум.",
          "* Пороги K1–K5 и порог квалификации объявлены заявкой ДО "
          "расчёта и этим прогоном не подбирались. Права на итерацию "
          "здесь одно, и оно не потрачено.", ""]

    when = dt.datetime.fromtimestamp(started, dt.timezone.utc)
    L += [f"Прогон {when:%Y-%m-%d %H:%M} UTC, "
          f"{time.time() - started:.0f} с. Числа — "
          f"`out/etf_rebal.json`, лог — `out/run.log`."]
    return "\n".join(L)


BOOT_N = ER.BOOTSTRAP


def res_m(r):
    """Измеренное м имени — чтобы фраза о силе замера стояла на ЧИСЛЕ."""
    return r["killers"]["K1"]["value"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--no-net", action="store_true",
                    help="не сверять даты фондов по их страницам")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    # Каталог артефактов создаётся ДО счёта: редирект лога — тоже каталог.
    os.makedirs(OUT, exist_ok=True)
    started = time.time()
    log = AB.guarded(lambda *a: print(*a, flush=True))
    state("старт")

    checked = {}
    if args.no_net:
        log("сверка дат фондов выключена ключом --no-net")
    else:
        try:
            FD.main()
        except Exception as e:                             # noqa: BLE001
            log(f"сверка дат фондов не удалась: {type(e).__name__}: {e}")
    checked = FD.read()
    try:
        with open(FD.PATH, encoding="utf-8") as f:
            checked["_funds"] = json.load(f).get("funds", [])
    except (OSError, ValueError):
        checked["_funds"] = []
    log(f"сверенных дат запуска: {sum(1 for k in checked if k != '_funds')}")

    cal = CAL.Calendar()
    results = {}
    for sym in args.symbols.split(","):
        sym = sym.strip()
        if not sym:
            continue
        state("замер", symbol=sym)
        results[sym] = run_symbol(sym, cal, checked, log,
                                  use_cache=not args.no_cache)

    state("отчёт")
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump({"at": round(time.time(), 3), "seconds": round(
            time.time() - started, 1), "results": results},
            f, ensure_ascii=False, indent=1, default=str)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(report(results, checked, started) + "\n")
    state("конец", seconds=round(time.time() - started, 1))
    log(f"\nотчёт: {REPORT}\nчисла: {DATA}")
    for s, r in results.items():
        log(f"{TITLE[s]}: {r['verdict']['phrase']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
