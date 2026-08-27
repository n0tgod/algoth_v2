#!/usr/bin/env python3
"""
Тесты зонда первых дней жизни инструмента.

Калибровочная пара обязательна: на синтетике с ПОДСАЖЕННЫМ дрейфом
новичков зонд обязан его найти, без дрейфа — дать ноль, и нуль
псевдо-событий обязан быть около ноля. Без неё отрицательный результат
неотличим от сломанной загрузки (проект дважды печатал нулевой отчёт
именно так).

    python3 research/probe_listings/test_probe.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "d1_seconds"))

import probe as P                                         # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def iso(day_idx):
    return (date.fromisoformat(P.T_START)
            + timedelta(days=day_idx)).isoformat()


def synth(n_days=900, n_old=40, n_new=20, drift_bp_day=0.0,
          list_days=(740, 761), pump_day0=0.0, seed=3):
    """Матрица дневных закрытий: зрелые с дня 0, новички листингами в
    `list_days`, дрейф новичка — первые 30 дней сверх рынка,
    `pump_day0` задирает цену ДНЯ листинга (проверка задержки d)."""
    rng = np.random.default_rng(seed)
    market = np.cumsum(rng.normal(0.0, 0.005, n_days))
    syms, listed, cols = [], {}, []
    for i in range(n_old):
        eps = np.cumsum(rng.normal(0.0, 0.01, n_days))
        cols.append(np.exp(market + eps))
        s = f"OLD{i:03d}USDT"
        syms.append(s)
        listed[s] = iso(0)
    lo, hi = list_days
    for i in range(n_new):
        L = int(lo + (hi - lo) * i / max(1, n_new - 1))
        eps = np.cumsum(rng.normal(0.0, 0.01, n_days))
        px = np.exp(market + eps)
        drift = np.zeros(n_days)
        d_end = min(n_days, L + 30)
        drift[L:d_end] = drift_bp_day * 1e-4
        px = px * np.exp(np.cumsum(drift))
        px[:L] = np.nan
        if pump_day0:
            px[L] *= (1.0 + pump_day0)
        cols.append(px)
        s = f"NEW{i:03d}USDT"
        syms.append(s)
        listed[s] = iso(L)
    M = np.column_stack(cols)
    universe = {s.replace("USDT", ""): {"binance_symbol": s,
                                        "listed": listed[s]}
                for s in syms}
    events = [(s.replace("USDT", ""), s, listed[s])
              for s in syms if s.startswith("NEW")]
    return M, syms, universe, events


def counters():
    return {k: 0 for k in (
        "нет ряда в хранилище", "нет цены входа",
        "форвард упирается в край данных",
        "ряд оборван сразу после входа",
        "контрольная база тоньше пола")}


def test_planted_drift_is_found():
    """Подсаженный дрейф −30 б.п./день найден; нуль около ноля."""
    M, syms, uni, ev = synth(drift_bp_day=-30.0)
    cells, years, null, _x = P.run(M, syms, uni, ev, counters())
    c = cells.get(P.MAIN_CELL)
    check("дрейф найден (медиана когорт < −400)",
          c is not None and c["coh_median_bp"] < -400,
          f"{c and c['coh_median_bp']}")
    check("нуль псевдо-событий около ноля",
          null is not None and abs(null["coh_median_mean"]) < 250,
          f"{null}")


def test_no_drift_is_zero():
    M, syms, uni, ev = synth(drift_bp_day=0.0)
    cells, _, _, _x = P.run(M, syms, uni, ev, counters())
    c = cells.get(P.MAIN_CELL)
    check("без дрейфа ноль (|медиана| < 250)",
          c is not None and abs(c["coh_median_bp"]) < 250,
          f"{c and c['coh_median_bp']}")


def test_delay_skips_the_listing_day():
    """Цена дня листинга задрана в полтора раза — вход по закрытию
    следующего дня её не видит, и «распад пампа» не выдумывается."""
    M, syms, uni, ev = synth(pump_day0=0.5)
    cells, _, _, _x = P.run(M, syms, uni, ev, counters())
    c = cells.get(P.MAIN_CELL)
    check("памп дня листинга не попадает в меру",
          c is not None and abs(c["coh_median_bp"]) < 250,
          f"{c and c['coh_median_bp']}")


def test_base_is_mature_and_computed_by_hand():
    """База события — среднее зрелых, сверено с ручным счётом числом."""
    M, syms, uni, ev = synth(n_new=1, drift_bp_day=0.0)
    col_of = {s: j for j, s in enumerate(syms)}
    ages = np.arange(len(M))[:, None] - P.born_index(M)[None, :]
    rec = P.measure_events(M, col_of, ages, ev, 1, 30, counters(),
                           len(M))
    check("событие измерено", len(rec) == 1, f"{len(rec)}")
    if rec:
        i0 = P.day_index(P.T_START, rec[0]["listed"]) + 1
        i1 = i0 + 30
        old = [j for j, s in enumerate(syms) if s.startswith("OLD")]
        want = float(np.mean(M[i1, old] / M[i0, old] - 1.0)) * 1e4
        check("база сходится с ручным счётом зрелых",
              abs(rec[0]["base_bp"] - want) < 1e-6,
              f"{rec[0]['base_bp']} против {want}")


def test_young_dirty_neighbor_stays_out_of_base():
    """Молодой сосед с диким дрейфом НЕ входит в контрольную базу.

    NEW000 листнут за 20 дней до события NEW001 и дрейфует −300
    б.п./день прямо в окне события; будь он в базе, она сдвинулась бы
    на ~66 б.п. — ручной счёт по зрелым это ловит. Первая версия
    контроля (снятый порог зрелости) не кусалась именно потому, что ни
    одна фикстура не держала живого грязного соседа в окне."""
    M, syms, uni, ev = synth(n_new=2, drift_bp_day=-300.0,
                             list_days=(720, 740))
    col_of = {s: j for j, s in enumerate(syms)}
    ages = np.arange(len(M))[:, None] - P.born_index(M)[None, :]
    late = [e for e in ev if e[0] == "NEW001"]
    rec = P.measure_events(M, col_of, ages, late, 1, 30, counters(),
                           len(M))
    check("позднее событие измерено", len(rec) == 1, f"{len(rec)}")
    if rec:
        i0 = P.day_index(P.T_START, rec[0]["listed"]) + 1
        i1 = i0 + 30
        old = [j for j, s in enumerate(syms) if s.startswith("OLD")]
        want = float(np.mean(M[i1, old] / M[i0, old] - 1.0)) * 1e4
        check("грязный молодой сосед не в базе",
              abs(rec[0]["base_bp"] - want) < 1e-6,
              f"{rec[0]['base_bp']} против {want}")


def test_delisted_counts_to_last_bar():
    """Делистинг внутри горизонта: считается до последнего бара с
    пометкой, а не выбрасывается (вырезать его — вырезать худшие
    исходы)."""
    M, syms, uni, ev = synth(n_new=1)
    j = syms.index("NEW000USDT")
    L = P.day_index(P.T_START, uni["NEW000"]["listed"])
    M[L + 12:, j] = np.nan
    cells, _, _, _x = P.run(M, syms, uni, ev, counters())
    c = cells.get(P.MAIN_CELL)
    check("оборванное событие измерено",
          c is not None and c["events"] == 1 and
          c["truncated_share"] == 1.0, f"{c}")


def test_edge_of_data_is_a_skip():
    """Форвард за краем данных — пропуск, а не укороченное окно."""
    M, syms, uni, ev = synth(n_new=1, list_days=(880, 881))
    cnt = counters()
    cells, _, _, _x = P.run(M, syms, uni, ev, cnt)
    check("край данных — пропуск",
          P.MAIN_CELL not in cells
          and cnt["форвард упирается в край данных"] > 0,
          f"{cells.keys()} {cnt}")


def test_hole_at_entry_is_a_skip():
    """Дыра в день входа — пропуск, а не сдвиг на следующий день."""
    M, syms, uni, ev = synth(n_new=1)
    j = syms.index("NEW000USDT")
    L = P.day_index(P.T_START, uni["NEW000"]["listed"])
    M[L + 1, j] = np.nan          # закрытие дня входа d=1
    col_of = {s: i for i, s in enumerate(syms)}
    ages = np.arange(len(M))[:, None] - P.born_index(M)[None, :]
    cnt = counters()
    rec = P.measure_events(M, col_of, ages, ev, 1, 30, cnt, len(M))
    check("дыра входа — пропуск события",
          not rec and cnt["нет цены входа"] == 1, f"{len(rec)} {cnt}")


def test_thin_base_is_a_skip():
    M, syms, uni, ev = synth(n_old=5, n_new=1)
    cnt = counters()
    cells, _, _, _x = P.run(M, syms, uni, ev, cnt)
    check("тонкая база — пропуск",
          P.MAIN_CELL not in cells
          and cnt["контрольная база тоньше пола"] > 0, f"{cnt}")


def test_event_comes_from_data_not_listed_field():
    """Событие A — рождение ряда ПО ДАННЫМ, а не поле `listed`.

    Живой дефект первого прогона: `listed` справочника — дата листинга
    Bybit, у 135 имён Binance-ряд начинается позже неё. Фикстура врёт
    полем на 10 дней раньше рождения — дрейф всё равно обязан быть
    найден (событие от первого дня ряда); возьми код дату из поля,
    входа не существовало бы и ячейка вышла бы пустой."""
    M, syms, uni, ev = synth(drift_bp_day=-30.0)
    ev_lied = [(a, s, iso(P.day_index(P.T_START, li) - 10))
               for a, s, li in ev]
    for a, s, li in ev_lied:
        uni[a]["listed"] = li
    cells, _, _, x = P.run(M, syms, uni, ev_lied, counters())
    c = cells.get(P.MAIN_CELL)
    check("событие от данных: дрейф найден при врущем поле",
          c is not None and c["coh_median_bp"] < -400,
          f"{c and c['coh_median_bp']}")
    check("расхождение поля с данными посчитано",
          x["born_vs_listed_month_mismatch"] > 0,
          f"{x['born_vs_listed_month_mismatch']}")


def test_short_history_name_stays_out_of_base():
    """Имя с давним `listed`, но коротким РЯДОМ — не зрелое.

    Второй зуб того же дефекта: возраст от поля пускал в контрольную
    базу имена, чей ряд живёт меньше года. OLD000 объявлен листнутым в
    день 0, а ряд начинается с дня 500 — на событие дня ~741 его
    возраст по данным 241 день, и в базе его быть не должно."""
    M, syms, uni, ev = synth(n_new=1)
    j0 = syms.index("OLD000USDT")
    M[:500, j0] = np.nan
    col_of = {s: i for i, s in enumerate(syms)}
    ages = np.arange(len(M))[:, None] - P.born_index(M)[None, :]
    rec = P.measure_events(M, col_of, ages, ev, 1, 30, counters(),
                           len(M))
    check("событие измерено", len(rec) == 1, f"{len(rec)}")
    if rec:
        i0 = P.day_index(P.T_START, rec[0]["listed"]) + 1
        i1 = i0 + 30
        old = [j for j, s in enumerate(syms)
               if s.startswith("OLD") and j != j0]
        want = float(np.mean(M[i1, old] / M[i0, old] - 1.0)) * 1e4
        check("короткий ряд не в базе, база сходится с ручным счётом",
              abs(rec[0]["base_bp"] - want) < 1e-6,
              f"{rec[0]['base_bp']} против {want}")


def test_short_history_out_of_base_through_run():
    """Тот же зуб, но через ДОРОГУ run(): прямой тест строил ages сам
    и подделку внутри run не исполнял — контроль не кусался.

    Короткому ряду (born 500 при listed «день 0») дан рост ×90 за месяц
    событий: пусти его возраст от поля в зрелую базу — база задралась
    бы и медиана excess ушла бы на тысячи б.п. вниз; честный код держит
    её около ноля."""
    M, syms, uni, ev = synth(n_new=3, drift_bp_day=0.0)
    j0 = syms.index("OLD000USDT")
    M[:500, j0] = np.nan
    t = np.arange(len(M), dtype=float)
    M[:, j0] = M[:, j0] * np.exp(np.where(t >= 500,
                                          0.15 * (t - 500), 0.0))
    cells, _, _, _x = P.run(M, syms, uni, ev, counters())
    c = cells.get(P.MAIN_CELL)
    check("короткий ряд не загрязняет базу через run",
          c is not None and abs(c["coh_median_bp"]) < 300,
          f"{c and c['coh_median_bp']}")


def test_bybit_listing_is_a_separate_event():
    """Листинг Bybit у зрелого на Binance имени — событие B, отдельной
    секцией; свежерождённое имя в B не входит (возраст < 30)."""
    M, syms, uni, ev = synth(n_new=2, list_days=(500, 740))
    ev2 = []
    for a, s, li in ev:
        if a == "NEW000":                 # ряд с дня 500, Bybit в 780
            uni[a]["listed"] = iso(780)   # 2022-02-19 — внутри MAIN_FROM
            ev2.append((a, s, iso(780)))
        else:                             # рождение = listed, молодой
            ev2.append((a, s, li))
    cells, _, _, x = P.run(M, syms, uni, ev2, counters())
    check("зрелое на Binance имя вошло в событие B",
          x["events_bybit"] == 1, f"{x['events_bybit']}")
    check("ячейка события B посчитана",
          x["bybit_cell"] is not None and x["bybit_cell"]["events"] == 1,
          f"{x['bybit_cell']}")


def test_cohort_is_one_vote():
    """Месяц листинга — один голос: толпа событий одного месяца не
    переголосует одиночек других."""
    recs = ([{"month": "2024-01", "year": "2024", "excess_bp": 500.0,
              "truncated": False}] * 20
            + [{"month": "2024-02", "year": "2024", "excess_bp": -100.0,
                "truncated": False},
               {"month": "2024-03", "year": "2024", "excess_bp": -100.0,
                "truncated": False}])
    s = P.summarise(recs)
    check("когорт три и медиана отрицательная",
          s["cohorts"] == 3 and s["coh_median_bp"] == -100.0,
          f"{s['cohorts']} {s['coh_median_bp']}")
    check("по событиям при этом плюс", s["ev_median_bp"] == 500.0,
          f"{s['ev_median_bp']}")


def test_funding_newborns():
    day = 86_400_000
    t = np.array([10 * day + i * 8 * 3_600_000 for i in range(120)],
                 dtype=np.int64)
    r = np.full(120, -1e-4)
    funding = {"AAA": (t, r)}
    ev = [("AAA", "AAAUSDT", "2020-01-11"), ("BBB", "BBBUSDT",
                                             "2020-01-11")]
    f = P.funding_newborns(funding, ev)
    check("покрытие считается", f["covered"] == 1, f"{f['covered']}")
    w = f.get("d0_7")
    check("суточная ставка первой недели −3 б.п./сутки",
          w is not None and abs(w["median_bp_day"] + 3.0) < 1e-9,
          f"{w}")
    check("доля отрицательных единица",
          w is not None and w["neg_share"] == 1.0, f"{w}")


def test_verdict_phrase():
    lag = {"coh_median_bp": -300.0, "coh_mean_bp": -150.0}
    lead = {"coh_median_bp": 200.0, "coh_mean_bp": 90.0}
    split = {"coh_median_bp": -50.0, "coh_mean_bp": 120.0}
    check("минус обеими мерами — ОТСТАЁТ",
          "ОТСТАЁТ" in P.verdict_phrase(lag), P.verdict_phrase(lag))
    check("плюс обеими — ОБГОНЯЕТ",
          "ОБГОНЯЕТ" in P.verdict_phrase(lead), P.verdict_phrase(lead))
    check("разные знаки — подпись хвоста",
          "подпись хвоста" in P.verdict_phrase(split),
          P.verdict_phrase(split))
    check("нет ячейки — нет фразы",
          "не измерена" in P.verdict_phrase(None), "")


def test_report_writes():
    """Дорога до показа исполняется: отчёт из настоящего run()."""
    tmp = tempfile.mkdtemp()
    try:
        M, syms, uni, ev = synth(drift_bp_day=-30.0)
        cnt = counters()
        cells, years, null, _x = P.run(M, syms, uni, ev, cnt)
        art = {"run_at": "t", "main_from": P.MAIN_FROM,
               "cells": cells, "years": years, "null": null,
               "funding": None, "skipped": cnt,
               "verdict": P.verdict_phrase(cells.get(P.MAIN_CELL))}
        path = os.path.join(tmp, "r.md")
        P.report(art, path)
        md = open(path, encoding="utf-8").read()
        check("отчёт несёт вердикт и сетку",
              "ОТСТАЁТ" in md and "| 1 | 30 |" in md, md[:200])
        check("отчёт несёт нуль числом",
              null is not None and "зёрнам" in md, "")
        check("отчёт несёт оговорку про Bybit-листинг",
              "листинг Bybit" in md, "")
        check("вердикт согласован с числами",
              ("ОТСТАЁТ" in art["verdict"]) == (
                  cells[P.MAIN_CELL]["coh_median_bp"] < 0
                  and cells[P.MAIN_CELL]["coh_mean_bp"] < 0), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("калибровка")
    test_planted_drift_is_found()
    test_no_drift_is_zero()
    test_delay_skips_the_listing_day()
    print("правила меры")
    test_base_is_mature_and_computed_by_hand()
    test_young_dirty_neighbor_stays_out_of_base()
    test_delisted_counts_to_last_bar()
    test_edge_of_data_is_a_skip()
    test_hole_at_entry_is_a_skip()
    test_thin_base_is_a_skip()
    test_event_comes_from_data_not_listed_field()
    test_short_history_name_stays_out_of_base()
    test_short_history_out_of_base_through_run()
    test_bybit_listing_is_a_separate_event()
    test_cohort_is_one_vote()
    print("funding и показ")
    test_funding_newborns()
    test_verdict_phrase()
    test_report_writes()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
