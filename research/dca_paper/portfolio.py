#!/usr/bin/env python3
"""Общая статистика: длинная книга и короткая на одной кривой (хедж-режим).

Решение владельца 2026-09-07: «три варианта шорт-стратегий рядом, а также
режим общей статистики, под хедж-режим». Пара считается ПО РЕЖИМАМ:
«безопасная» с «безопасной (шорт h24)», и так все три — режимы суть
разные уровни риска, и смешивать их в одну кучу значило бы судить не то,
чем торгуют.

Что здесь считается и зачем каждое число:

- **корреляция дневных денег** — книга, ходящая с длинной в такт,
  удваивает риск, а не хеджирует его; около нуля или ниже — другая
  ставка, а не вторая такая же;
- **просадка ПАРЫ по общей кривой** — не сумма просадок: если стороны
  ходят врозь, пара мельче каждой;
- **совпадения имён** — сколько шортов открыто по монете, которую
  длинная книга держит в тот же момент. В ХЕДЖ-РЕЖИМЕ это законно и
  считается отдельной строкой; в одностороннем такой шорт срезал бы
  длинную позицию, и тогда число выше есть цена режима, а не мелочь.

Счета РАЗДЕЛЬНЫЕ: у каждой книги свой депозит, итог пары считается от
суммы. Общий счёт — другое правило кассы (свободные деньги одной книги
кормят другую), и выдавать одно за другое нельзя.

Ряды, выравнивание, просадка и совпадения считаются функциями замера
D13 (`dca_ladder/run_d13`) — второй копии этих правил не заводится.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_d13 as D13                                         # noqa: E402

# Пары «режим → (длинная книга, короткая книга)» — по именам режимов,
# один раз и одним местом.
PAIRS = [("safe", "safe", "safe_h"), ("optimal", "optimal", "optimal_h"),
         ("aggr", "aggr", "aggr_h")]
MAIN_DEP = 10000.0


def rows_of(path, ruler, dep):
    """Строки книги ТЕКУЩЕЙ версии правил из её журнала."""
    rows, _bad = R.read_journal(path)
    return [r for r in rows if R.is_current(r)
            and int(float(r.get("dep") or 0)) == int(dep)
            and R.ruler_of(r) == ruler]


def pair_stats(long_rows, short_rows, dep=MAIN_DEP):
    """Одна пара: деньги врозь, деньги вместе, связь и совпадения имён."""
    ls, ss = D13.series(long_rows), D13.series(short_rows)
    days, xl, xs = D13.align(ls, ss)
    both = [a + b for a, b in zip(xl, xs)]
    corr = None
    if len(days) > 2 and np.std(xl) > 0 and np.std(xs) > 0:
        corr = round(float(np.corrcoef(xl, xs)[0, 1]), 3)
    green = (round(float(np.mean(np.array(both) > 0)), 3) if both else None)
    return {"days": len(days),
            "window": [days[0], days[-1]] if days else None,
            "n_long": len(long_rows), "n_short": len(short_rows),
            "long_usd": round(sum(xl), 2), "short_usd": round(sum(xs), 2),
            "both_usd": round(sum(both), 2),
            "long_dd": D13.curve_dd(xl, dep), "short_dd": D13.curve_dd(xs, dep),
            "both_dd": D13.curve_dd(both, 2 * dep),
            "both_final": (round(sum(both) / (2.0 * dep), 4) if days else None),
            "long_final": (round(sum(xl) / dep, 4) if days else None),
            "short_final": (round(sum(xs) / dep, 4) if days else None),
            "corr": corr, "day_green": green,
            "collisions": D13.collisions(short_rows, long_rows)}


def build(long_path=None, short_path=None, deps=None, log=print):
    """Общая статистика по всем режимам и депозитам.

    Журнала короткой книги ещё нет (первый прогон) — это причина, а не
    ноль: пары не считаются, и отчёт говорит словами.
    """
    long_path = long_path or R.JOURNAL
    short_path = short_path or R.H24_JOURNAL
    if not R.journal_parts(short_path):
        log("журнала коротких книг нет — общая статистика не считается")
        return {"error": "журнала коротких книг ещё нет",
                "hedge": True, "main_dep": MAIN_DEP}
    if not R.journal_parts(long_path):
        log("журнала длинных книг нет — общая статистика не считается")
        return {"error": "журнала длинных книг нет",
                "hedge": True, "main_dep": MAIN_DEP}
    deps = list(deps or R.DEPOSITS)
    out = {"hedge": True, "main_dep": MAIN_DEP, "deposits": deps, "pairs": {}}
    for (mode, lk, sk) in PAIRS:
        for dep in deps:
            lr = rows_of(long_path, lk, dep)
            sr = rows_of(short_path, sk, dep)
            out["pairs"][f"{mode}:{int(dep)}"] = dict(
                pair_stats(lr, sr, dep), mode=mode, long=lk, short=sk,
                dep=int(dep))
    n = sum(1 for p in out["pairs"].values() if p["days"])
    log(f"общая статистика: пар с общим окном {n} из {len(out['pairs'])}")
    return out


def verdict(p):
    """Пара против длинной книги ОДНОЙ: деньги и просадка."""
    if not p or not p.get("days"):
        return {"why": "общего окна нет"}
    adds = (p["both_usd"] or 0) > (p["long_usd"] or 0)
    dd_ok = (p["both_dd"] is not None and p["long_dd"] is not None
             and p["both_dd"] >= p["long_dd"])
    return {"adds_money": adds, "dd_not_worse": dd_ok,
            "verdict": ("рядом имеет смысл" if adds and dd_ok
                        else ("деньги добавляет, просадку тоже" if adds
                              else "не добавляет"))}


def _p(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def report_block(s):
    """Раздел отчёта. Нет чисел — сказано причиной, а не пустой таблицей."""
    L = ["## Общая статистика: длинная книга и короткая рядом", ""]
    if not s:
        return L + ["Не считалась: блока нет в своде.", ""]
    if s.get("error"):
        return L + [f"Не считалась: {s['error']}.", ""]
    dep = int(s.get("main_dep") or MAIN_DEP)
    L += [f"Счета РАЗДЕЛЬНЫЕ: каждой книге ${dep}, итог пары — от "
          f"${2 * dep}. Хедж-режим: короткая книга не смотрит на длинные "
          "позиции, и совпадения имён считаются отдельной колонкой — в "
          "одностороннем режиме биржи такой шорт резал бы длинную "
          "позицию.", "",
          "| режим | суток | Σ $ длинная | Σ $ короткая | Σ $ пара | "
          "итог пары | просадка длинной | просадка пары | связь дней | "
          "совпадений имён |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for (mode, _lk, _sk) in PAIRS:
        p = (s.get("pairs") or {}).get(f"{mode}:{dep}")
        if not p:
            continue
        col = p.get("collisions") or {}
        share = col.get("share")
        L.append(
            f"| {R.ruler_title(mode)} | {p['days']} | {_u(p['long_usd'])} | "
            f"{_u(p['short_usd'])} | {_u(p['both_usd'])} | "
            f"{_p(p['both_final'])} | {_p(p['long_dd'])} | "
            f"{_p(p['both_dd'])} | "
            f"{'—' if p['corr'] is None else p['corr']} | "
            f"{col.get('n', 0)}"
            + (f" ({100 * share:.1f} %)" if share else "") + " |")
    L += ["", "| режим | добавляет деньги | просадка пары не хуже длинной | вывод |",
          "|---|---|---|---|"]
    for (mode, _lk, _sk) in PAIRS:
        v = verdict((s.get("pairs") or {}).get(f"{mode}:{dep}"))
        if v.get("why"):
            L.append(f"| {R.ruler_title(mode)} | — | — | вердикта нет: {v['why']} |")
        else:
            L.append(f"| {R.ruler_title(mode)} | "
                     f"{'да' if v['adds_money'] else 'нет'} | "
                     f"{'да' if v['dd_not_worse'] else 'нет'} | "
                     f"{v['verdict']} |")
    L += ["", "Связь дней около нуля или ниже означает, что стороны ходят "
          "ВРОЗЬ: тогда пара — другая ставка, а не вторая такая же, и "
          "просадка пары мельче суммы. Связь заметно выше нуля означает "
          "обратное, и вторая книга тогда просто удваивает риск.", ""]
    return L
