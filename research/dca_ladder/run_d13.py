#!/usr/bin/env python3
"""D13 — короткая книга РЯДОМ с длинной: что даёт пара, а не половина.

Вопрос владельца 2026-09-07: «что по шорт-сделкам лучше всего запускать
параллельно к DCA-лонгу». D12 намерил одиночный шорт на сигнале `h24`
(рука сети, срок 24 ч, билет от собственного пика): от +7 % до +41 %
нетто за окно в зависимости от плеча и цели. Но «сколько даёт книга
одна» и «что она даёт рядом с длинной» — разные вопросы, и второй
решается тремя числами, которых у D12 нет:

1. **корреляция дней** — короткая книга, ходящая с длинной в такт,
   удваивает риск, а не хеджирует его;
2. **общая просадка** — просадка пары может быть меньше суммы (тогда
   пара имеет смысл) или равна ей (тогда это просто вторая ставка);
3. **совпадения имён** — шорт по монете, которую длинная книга держит,
   на одностороннем режиме биржи НЕ открывает позицию, а закрывает
   чужую. Это не «хедж», это порча длинной книги, и мерить её надо
   числом до, а не после запуска.

Короткая сторона считается тем же реплеем, что D12 (ноги `h24`, сетка
D10, билет от своего пика), длинная берётся ИЗ ЖУРНАЛА бумажных книг —
той записи, которая ведётся вперёд, а не из второго реплея.

Счета РАЗДЕЛЬНЫЕ: каждой книге свой депозит, итог пары считается от
суммы. Общий счёт — другое правило кассы (свободные деньги одной книги
кормят другую), и выдавать одно за другое нельзя.

Запуск: run research/dca_ladder/run_d13.py --arm nn --hold 24
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "dca_paper"))
sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))
import rules as R                                             # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d11 as D11                                         # noqa: E402
import run_d12 as D12                                         # noqa: E402

OUT = os.path.join(HERE, "out")
DEP = 10000                          # депозит каждой книги
SHORT_BOOK = "optimal_s"             # короткое зеркало, как у D12
LONG_BOOKS = ("optimal", "safe")     # длинные книги журнала
# Ячейки объявлены ДО прогона: три из D12 (лучшая по итогу, цель ×1 и
# потолок плеча 3×) плюс структурные доливы — чтобы пара судилась не
# по одной удачной ячейке.
SHORT_KEYS = ["fence:none:t2", "fence:none:t1", "c3:none:t2", "c3:struct:t2"]
DAY = 86400.0


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))


def series(rows, key="exit_ts"):
    """Дневной ряд денег: сутки UTC по моменту ВЫХОДА.

    День закрытия, а не входа: деньги появляются на счёте тогда, и
    кривая счёта строится по ним. Пустой день в ряд не попадает — его
    добавляет выравнивание, и там он честный ноль, а не пропуск.
    """
    out = {}
    for r in rows:
        try:
            out[_day(r[key])] = out.get(_day(r[key]), 0.0) + float(r["usd"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def align(a, b):
    """Два ряда на ОБЩЕЙ оси суток: пересечение окон, дырки — нули.

    Ось — календарь, а не номер элемента: ряды разной длины, и сдвиг на
    сутки при выравнивании по индексу дал бы корреляцию чужой пары.
    Берётся ПЕРЕСЕЧЕНИЕ окон: сутки, когда одной книги ещё не было, о
    паре не говорят ничего.
    """
    if not a or not b:
        return [], [], []
    lo = max(min(a), min(b))
    hi = min(max(a), max(b))
    if lo > hi:
        return [], [], []
    days, xa, xb = [], [], []
    t = time.mktime(time.strptime(lo, "%Y-%m-%d"))
    t -= time.timezone
    end = time.mktime(time.strptime(hi, "%Y-%m-%d")) - time.timezone
    while t <= end + 1:
        d = _day(t)
        days.append(d)
        xa.append(float(a.get(d, 0.0)))
        xb.append(float(b.get(d, 0.0)))
        t += DAY
    return days, xa, xb


def curve_dd(vals, dep):
    """Просадка по дневной кривой счёта, долей депозита.

    Первой точкой кривой стоит САМ ДЕПОЗИТ: иначе убыток первого дня
    просадкой не считается вовсе (пика перед ним нет), и книга, ушедшая
    вниз со старта, показывала бы ноль. Это отличается от `_stats`
    бумажных книг, которые начинают ряд с первого дня, поэтому число
    D13 сравнивается с числом D13, а расхождение названо в отчёте.
    """
    if not vals:
        return None
    eq = float(dep) + np.cumsum(np.array([0.0] + list(vals), dtype=float))
    return round(float(np.min(eq / np.maximum.accumulate(eq) - 1.0)), 4)


def collisions(short_rows, long_rows):
    """Шорт по имени, которое длинная книга держит В ТО ЖЕ ВРЕМЯ.

    Касание встык совпадением не считается — позиция закрыта, монета
    свободна (то же правило, что у дублей внутри книги).
    """
    per = {}
    for r in long_rows:
        try:
            per.setdefault(r["sym"], []).append((float(r["at"]),
                                                 float(r["exit_ts"])))
        except (KeyError, TypeError, ValueError):
            continue
    hits, usd, names = 0, 0.0, {}
    for r in short_rows:
        for (a, b) in per.get(r["sym"], ()):
            if float(r["at"]) < b and a < float(r["exit_ts"]):
                hits += 1
                usd += float(r.get("usd") or 0)
                names[r["sym"]] = names.get(r["sym"], 0) + 1
                break
    top = sorted(names.items(), key=lambda kv: -kv[1])[:5]
    return {"n": hits, "share": (round(hits / len(short_rows), 4)
                                 if short_rows else None),
            "usd": round(usd, 2), "names": len(names), "top": top}


def long_rows(dep=DEP, books=LONG_BOOKS, path=None, log=print):
    """Строки длинных книг ИЗ ЖУРНАЛА — той записи, что ведётся вперёд."""
    rows, bad = R.read_journal(path or R.JOURNAL)
    out = {}
    for rk in books:
        mine = [r for r in rows if R.is_current(r)
                and int(float(r.get("dep") or 0)) == int(dep)
                and R.ruler_of(r) == rk]
        out[rk] = mine
        log(f"журнал книги {rk} ${dep}: строк {len(mine)}")
    if bad:
        log(f"битых строк журнала {bad}")
    return out


def short_cells(arm="nn", hold_h=24, limit=None, src=None, log=print,
                legs=None, keys=None):
    """Короткие книги-кандидаты: те же ноги и та же касса, что у D12."""
    keys = list(keys or SHORT_KEYS)
    was = D11.configure(hold_h)
    try:
        legs = legs if legs is not None else D11.h24_legs(arm, limit=limit,
                                                          log=log)
        got = D10.collect(src=src, log=log, legs=legs)
        rk = D10.BOOK_RULER[SHORT_BOOK]
        stores, n_ok, lost = D10.common_sample(got["recs"][rk], log=log)
        out = {}
        for key in keys:
            st = stores.get(key)
            if st is None:
                log(f"ячейка {key}: записей нет — пропуск")
                continue
            recs = [st.row(i) for i in range(len(st))]
            sub = [r for r in recs if D10.REF_GATE in (r.get("gates") or [])]
            keep, _sk = D10.D6.one_per_name(sub)
            # `D12.peak_open` возвращает ЧИСЛО (пик одновременных), а не
            # словарь `D6.peak_open`: две функции одного имени в соседних
            # модулях, и путать их нельзя — первый прогон упал ровно тут.
            pk = D12.peak_open(keep)
            sh = D12.own_share(DEP, pk, SHORT_BOOK)
            rows = []
            c = D10.cell(recs, SHORT_BOOK, DEP, net=True, share=sh, rows_out=rows)
            out[key] = {"cell": c, "rows": rows, "share": sh,
                        "peak": pk,
                        "ticket": round(DEP * sh, 2) if sh else None}
            log(f"ячейка {key}: взято {c['taken']}, итог {100 * (c['final'] or 0):+.2f} %, "
                f"билет ${out[key]['ticket']}")
        return out, {"legs": len(legs), "sample": n_ok, "lost": lost,
                     "hold_h": D10.D2.HOLD_H, "arm": arm}
    finally:
        D11.restore(was)


def run(arm="nn", hold_h=24, limit=None, src=None, log=print, legs=None,
        journal=None, keys=None):
    t0 = time.time()
    shorts, sig = short_cells(arm=arm, hold_h=hold_h, limit=limit, src=src,
                              log=log, legs=legs, keys=keys)
    longs = long_rows(path=journal, log=log)
    pairs, marks = {}, {}
    for rk, lrows in longs.items():
        ls = series(lrows)
        marks[rk] = {"n": len(lrows), "usd": round(sum(float(r.get("usd") or 0)
                                                       for r in lrows), 2),
                     "days": len(ls),
                     "max_dd": curve_dd([ls[d] for d in sorted(ls)], DEP)}
        for key, sh in shorts.items():
            ss = series(sh["rows"])
            days, xl, xs = align(ls, ss)
            both = [a + b for a, b in zip(xl, xs)]
            corr = None
            if len(days) > 2 and np.std(xl) > 0 and np.std(xs) > 0:
                corr = round(float(np.corrcoef(xl, xs)[0, 1]), 3)
            pairs[f"{rk}|{key}"] = {
                "long": rk, "short": key, "days": len(days),
                "window": [days[0], days[-1]] if days else None,
                "corr": corr,
                "long_usd": round(sum(xl), 2), "short_usd": round(sum(xs), 2),
                "long_dd": curve_dd(xl, DEP), "short_dd": curve_dd(xs, DEP),
                "both_usd": round(sum(both), 2),
                "both_dd": curve_dd(both, 2 * DEP),
                "both_final": round(sum(both) / (2.0 * DEP), 4),
                "collisions": collisions(sh["rows"], lrows)}
    return {"at": time.time(), "secs": round(time.time() - t0, 1),
            "signal": sig, "dep": DEP, "short_book": SHORT_BOOK,
            "keys": list(shorts), "shorts": {k: {kk: vv for kk, vv in v.items()
                                                 if kk != "rows"}
                                             for k, v in shorts.items()},
            "longs": marks, "pairs": pairs, "rules": R.RULES}


def verdict(s):
    """Что стоит рядом с длинной книгой: пара обязана быть лучше длинной
    ОДНОЙ по деньгам и не хуже по просадке, а совпадения имён — редкими."""
    v = {}
    for k, p in s["pairs"].items():
        better = (p["both_usd"] or 0) > (p["long_usd"] or 0)
        dd_ok = (p["both_dd"] is not None and p["long_dd"] is not None
                 and p["both_dd"] >= p["long_dd"])
        v[k] = {"adds_money": better, "dd_not_worse": dd_ok,
                "corr": p["corr"],
                "collisions": (p["collisions"] or {}).get("share"),
                "verdict": ("рядом имеет смысл" if better and dd_ok
                            else ("деньги добавляет, просадку тоже"
                                  if better else "не добавляет"))}
    return v


def _p(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def report(s):
    sig = s.get("signal") or {}
    L = ["# D13 — короткая книга рядом с длинной", "",
         "Вопрос владельца 2026-09-07: «что по шорт-сделкам лучше всего "
         "запускать параллельно к DCA-лонгу». D12 мерил короткую книгу "
         "ОДНУ; здесь она считается В ПАРЕ с длинной, потому что рядом "
         "решают три другие величины: корреляция дней (книга в такт "
         "удваивает риск), общая просадка и совпадения имён — шорт по "
         "монете, которую длинная книга держит, на одностороннем режиме "
         "биржи не открывает позицию, а закрывает чужую.", "",
         f"Короткая сторона: ноги `h24` руки {sig.get('arm')}, срок "
         f"{sig.get('hold_h')} ч, книга `{s['short_book']}`, билет от "
         f"собственного пика, деньги НЕТТО круга издержек; {sig.get('legs')} "
         f"ног, общая выборка {sig.get('sample')}. Длинная сторона — "
         "журнал бумажных книг (запись, которая ведётся вперёд), депозит "
         f"${s['dep']}. Счета РАЗДЕЛЬНЫЕ: итог пары считается от суммы "
         f"${2 * s['dep']}.", "",
         "## Книги по отдельности", "",
         "| книга | сделок | Σ $ | итог | просадка | билет |",
         "|---|--:|--:|--:|--:|--:|"]
    for rk, m in sorted(s["longs"].items()):
        L.append(f"| `{rk}` (длинная) | {m['n']} | {_u(m['usd'])} | "
                 f"{_p((m['usd'] or 0) / s['dep'])} | {_p(m['max_dd'])} | "
                 f"${R.ticket(s['dep'], rk)} |")
    for key, c in sorted(s["shorts"].items()):
        cc = c["cell"]
        L.append(f"| `{key}` (короткая) | {cc['taken']} | {_u(cc['usd'])} | "
                 f"{_p(cc['final'])} | {_p(cc['max_dd'])} | ${c['ticket']} |")
    L += ["", "## Пара: длинная книга + короткая", "",
          "| пара | суток | корреляция дней | Σ $ длинная | Σ $ короткая | "
          "Σ $ пара | просадка длинной | просадка пары | итог пары | "
          "совпадений имён |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for k, p in sorted(s["pairs"].items()):
        col = p["collisions"] or {}
        L.append(f"| {k} | {p['days']} | "
                 f"{'—' if p['corr'] is None else p['corr']} | "
                 f"{_u(p['long_usd'])} | {_u(p['short_usd'])} | "
                 f"{_u(p['both_usd'])} | {_p(p['long_dd'])} | "
                 f"{_p(p['both_dd'])} | {_p(p['both_final'])} | "
                 f"{col.get('n', 0)}"
                 + (f" ({100 * col['share']:.1f} %)" if col.get("share") else "")
                 + " |")
    L += ["", "## Вердикт", "",
          "| пара | добавляет деньги | просадка не хуже | корреляция | "
          "совпадений | итог |", "|---|---|---|--:|--:|---|"]
    for k, v in sorted(verdict(s).items()):
        col = v["collisions"]
        col_s = "—" if col is None else f"{100.0 * col:.1f} %"
        corr_s = "—" if v["corr"] is None else str(v["corr"])
        money = "да" if v["adds_money"] else "нет"
        dd_s = "да" if v["dd_not_worse"] else "нет"
        L.append(f"| {k} | {money} | {dd_s} | {corr_s} | {col_s} | "
                 f"{v['verdict']} |")
    L += ["", "## Чего замер НЕ говорит", "",
          "- Он не обещает будущего: короткая сторона считана реплеем на "
          "том же окне, где две трети денег длинных книг сделаны за три "
          "дня всплеска 20–22.08. Половины окна у короткой книги D12 "
          "разошлись (+44.6 / −3.2 %), и это ограничение никуда не делось.",
          "- Счета раздельные. Общий счёт — другое правило кассы, и "
          "числа пары к нему не относятся.",
          "- Совпадение имён посчитано как ПЕРЕСЕЧЕНИЕ во времени. Что "
          "именно сделает биржа, зависит от режима позиции: в "
          "одностороннем шорт закроет часть длинной, в хедж-режиме обе "
          "живут. Замер говорит, как ЧАСТО это случилось бы, а не чем "
          "кончится.",
          "- Длинная сторона взята из журнала (правила v6 живут с 05.09), "
          "то есть это пересчёт истории, а не проверенный вперёд результат.",
          "- Просадка здесь считается по дневной кривой, где первой "
          "точкой стоит сам депозит (убыток первого дня — тоже "
          "просадка). У бумажных книг ряд начинается с первого дня, "
          "поэтому их число и число D13 могут не совпасть: сравнивать "
          "надо однородные.",
          ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="D13: короткая книга рядом с длинной")
    ap.add_argument("--arm", default="nn", choices=("nn", "gbm"))
    ap.add_argument("--hold", type=int, default=24)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    s = run(arm=a.arm, hold_h=a.hold, limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    name = f"D13-pair-{a.arm}-h{a.hold}-{tag}"
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D13: короткая книга рядом с длинной ({a.arm}, {a.hold} ч, {tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
