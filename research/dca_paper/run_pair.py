#!/usr/bin/env python3
"""Общий счёт: длинная книга и короткая на ОДНОМ депозите.

Требование владельца 2026-09-07: «общая должна выводиться в таком же
формате, как и по отдельности шорт и лонг, а также для общей должен быть
один общий счёт, а не по отдельности».

Что изменилось против прежней «общей статистики». Та складывала два
РАЗДЕЛЬНЫХ счёта: у длинной книги свои $10k, у короткой свои, и пара
была суммой двух кривых. Здесь счёт ОДИН: решения обеих книг встают в
одну очередь за деньгами, занятая одной стороной маржа недоступна
другой, и часть сделок поэтому не случается вовсе. Числа общей книги НЕ
равны сумме двух — это не расхождение, а суть режима, и разница
печатается отдельной таблицей.

Что осталось свойством СТОРОНЫ, а не общего счёта:

* **билет** — он выведен из пика одновременных позиций своей книги (у
  длинной их до 457, у короткой 30), и общий билет означал бы другую
  книгу с обеих сторон;
* **гейт плеча** и **одна позиция на имя** — правила своей книги; шорт
  по имени, которое держит длинная, законен в ХЕДЖ-РЕЖИМЕ и считается
  отдельной строкой («совпадений имён»);
* **издержки** — комиссия, проскальзывание и funding учтены в КАЖДОЙ
  сделке (`costs.apply_to_rows`), как и в отдельных книгах.

Прогон НИЧЕГО не пересчитывает по барам: исходы позиций берутся из кэшей
реплея длинных книг (`run_paper`) и коротких (`run_short`) — прошлое не
меняется, и второй копии симуляции здесь нет. Нет кэша или он от других
правил — это причина словами и отказ считать, а не пустые книги.

Формат — тот же, что у отдельных книг: то же ядро (`run_paper.build_rows`,
`summarize`, `_stats`), тот же журнал суточными кусками, тот же артефакт,
те же вкладки страницы.

Запуск: `run research/dca_paper/run_pair.py`.
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_d13 as D13                                         # noqa: E402
import arm_book as AB                                         # noqa: E402

# Предел памяти прогона. На VPS 7.7 ГБ без свопа, и тяжёлый прогон рядом
# с часовым циклом убивает НЕ СЕБЯ (OOM выбирает по-своему): предел и
# самоостанов живут в самом прогоне, вслух и с числом. Сторож памяти —
# тот же, что у разреза по рукам, второй копии нет.
MEM_LIMIT_MB = 1200


def long_recs(cache=None, log=print):
    """Позиции длинных книг из кэша реплея `run_paper`, по книгам.

    Ключ кэша — (пара линейки, имя, момент); пара книги берётся из того
    же реестра, которым её считает длинный прогон, а не из копии списка.
    """
    why = None
    if cache is None:
        cache, why = RP.read_cache()
    if why:
        log(f"кэш длинных книг не используется: {why}")
        return {}, why
    # Одна пара линейки кормит НЕСКОЛЬКО книг: «оптимальная» и
    # «агрессивная» считаются на одной геометрии и различаются гейтом
    # плеча. Словарь «пара → книга» терял вторую из них молча, и общая
    # книга режима оставалась вовсе без длинной стороны — ноль, который
    # выглядел как книга.
    want = {}
    for k in R.order_of("sit"):
        want.setdefault(tuple(RP.RULERS[k]), []).append(k)
    out = {}
    for (pr, _sym, _at), r in cache.items():
        for k in want.get(tuple(pr), ()):
            out.setdefault(k, []).append(r)
    log("длинные книги: " + ", ".join(f"{k} {len(v)}"
                                      for k, v in sorted(out.items())))
    return out, None


def short_recs(cache=None, log=print):
    """Позиции коротких книг `h24` из их кэша, по книгам семейства."""
    why = None
    if cache is None:
        cache, why = S.read_cache(log=log)
    if why:
        log(f"кэш коротких книг не используется: {why}")
        return {}, why
    out = {}
    for (rk, _sym, _at), r in cache.items():
        for bk, base in S.BOOKS.items():
            if base == rk:
                out.setdefault(bk, []).append(r)
    log("короткие книги: " + ", ".join(f"{k} {len(v)}"
                                       for k, v in sorted(out.items())))
    return out, None


def pack(longs, shorts, keys=None):
    """Решения общей книги: обе стороны в одном списке, с меткой источника.

    Метка (`book`) едет С ЗАПИСЬЮ, потому что билет, гейт плеча и правило
    одной на имя выбираются по ней, а из ключа общей книги их вывести
    нечем.
    """
    out = {}
    for pk in (keys or R.PAIR_ORDER):
        lk, sk = R.parts_of(pk)
        recs = ([dict(r, book=lk) for r in (longs.get(lk) or [])]
                + [dict(r, book=sk) for r in (shorts.get(sk) or [])])
        out[pk] = recs
    return out


def collisions(rows, ruler):
    """Имена, которые общий счёт держит РАЗОМ длинной и короткой.

    В хедж-режиме это законно и считается отдельно; в одностороннем
    режиме биржи такой шорт срезал бы длинную позицию, и тогда число
    ниже есть цена режима, а не мелочь показа.
    """
    longs = [r for r in rows if R.row_side(r, ruler) == "long"]
    shorts = [r for r in rows if R.row_side(r, ruler) == "short"]
    if not longs or not shorts:
        return {"n": 0, "names": 0, "share": None,
                "why": "одна из сторон в книге пуста"}
    got = D13.collisions(shorts, longs)
    got["share"] = (round(got["n"] / len(shorts), 3) if shorts else None)
    return got


def _side_series(rows, ruler, side):
    return D13.series([r for r in rows if R.row_side(r, ruler) == side])


def link(rows, ruler):
    """Связь дневных денег сторон ВНУТРИ общего счёта.

    Около нуля или ниже — стороны ходят врозь, и общий счёт мельче суммы
    двух; заметно выше нуля — вторая книга просто удваивает ту же ставку.
    """
    a = _side_series(rows, ruler, "long")
    b = _side_series(rows, ruler, "short")
    days, xa, xb = D13.align(a, b)
    if len(days) < 3 or np.std(xa) == 0 or np.std(xb) == 0:
        return {"corr": None, "days": len(days),
                "why": "общих суток меньше трёх или сторона стоит"}
    return {"corr": round(float(np.corrcoef(xa, xb)[0, 1]), 3),
            "days": len(days), "window": [days[0], days[-1]]}


def separate(rows_by_book, dep):
    """Те же книги на РАЗДЕЛЬНЫХ счетах — для сравнения с общим.

    Считается по журналам самих книг тем же `_stats`: это ровно то, что
    показывают их вкладки. Сумма двух счетов есть счёт $2·dep, и итог в
    процентах у неё оттого считается от удвоенного депозита — иначе
    сравнивались бы разные капиталы.
    """
    out = {}
    for bk, rows in rows_by_book.items():
        out[bk] = RP._stats([r for r in rows
                             if int(r.get("dep", 0)) == int(dep)], dep)
    return out


def one_sided(book, lk, sk):
    """Какой стороны в общем счёте НЕТ. Пусто — обе на месте.

    Односторонняя «общая» книга выглядит как обычная и врёт молча:
    первый живой прогон показал «общую (оптимальную)» без единой длинной
    сделки — и она читалась как книга, а не как дефект. Отсюда поле,
    из которого выводится фраза отчёта и строка страницы.
    """
    pr = book.get("parts") or {}
    out = [p for p in (lk, sk)
           if not (((pr.get(p) or {}).get("stats") or {}).get("n") or 0)]
    return out or None


def run(log=print, now=None, journal=None, long_cache=None, short_cache=None,
        long_journal=None, short_journal=None, keys=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    keys = list(keys or R.PAIR_ORDER)
    longs, why_l = long_recs(long_cache, log=log)
    shorts, why_s = short_recs(short_cache, log=log)
    if why_l or why_s or not longs or not shorts:
        why = (why_l or why_s
               or ("позиций длинных книг нет" if not longs
                   else "позиций коротких книг нет"))
        log(f"общий счёт не считается: {why}")
        return {"family": "pair", "error": why, "books": {},
                "rulers": keys, "deposits": list(R.DEPOSITS),
                "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    packed = pack(longs, shorts, keys)
    rows, cells, one, live = RP.build_rows(packed, now=now, keys=keys, log=log)
    RP.append_journal(rows, path=journal or R.PAIR_JOURNAL, log=log)
    s = RP.summarize(path=journal or R.PAIR_JOURNAL, live=live, keys=keys)
    jrows, _bad = R.read_journal(journal or R.PAIR_JOURNAL)
    jrows = [r for r in jrows if R.is_current(r)]
    # Раздельные счета — из журналов самих книг, тем же ядром: это ровно
    # то, что показывают их вкладки, и сравнение общего счёта с ними есть
    # ответ на вопрос владельца «что даёт один счёт вместо двух».
    lrows, _ = R.read_journal(long_journal or R.JOURNAL)
    srows, _ = R.read_journal(short_journal or R.H24_JOURNAL)
    lrows = [r for r in lrows if R.is_current(r)]
    srows = [r for r in srows if R.is_current(r)]
    for pk in keys:
        lk, sk = R.parts_of(pk)
        mine = [r for r in jrows if R.ruler_of(r) == pk]
        for dep in R.DEPOSITS:
            key = RP._cell(pk, dep)
            b = s["books"].get(key)
            if not b:
                continue
            sub = [r for r in mine if int(r.get("dep", 0)) == int(dep)]
            b["one_sided"] = one_sided(b, lk, sk)
            b["collisions"] = collisions(sub, pk)
            b["link"] = link(sub, pk)
            b["separate"] = separate(
                {lk: [r for r in lrows if R.ruler_of(r) == lk],
                 sk: [r for r in srows if R.ruler_of(r) == sk]}, dep)
    s.update({"family": "pair", "hedge": True, "cells": cells,
              "one_name": one, "parts": {k: R.parts_of(k) for k in keys},
              "secs": round(time.time() - t0, 1),
              "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
              "rules": RP.rules_snapshot(keys=keys)})
    return s


def _p(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def report(s):
    L = ["# Общий счёт: длинная книга и короткая на одном депозите", "",
         "Требование владельца 2026-09-07: «для общей должен быть один "
         "общий счёт, а не по отдельности». Решения обеих книг стоят в "
         "ОДНОЙ очереди за деньгами: занятая одной стороной маржа "
         "недоступна другой, и часть сделок поэтому не случается вовсе. "
         "Числа общей книги не равны сумме двух отдельных — это и есть "
         "разница режимов, а не расхождение счёта.", "",
         "Билет у каждой стороны СВОЙ (он выведен из пика её "
         "одновременных позиций), гейт плеча и правило «одна позиция на "
         "имя» — тоже правила стороны. Издержки учтены в каждой сделке, "
         "как и в отдельных книгах.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитан:** {s['error']}. Это причина, "
                              "а не пустая книга: без кэшей реплея обеих "
                              "сторон общий счёт неоткуда взять.", ""])
    L += ["## Книги", "",
          "| книга | депозит | сделок | длинных | коротких | Σ $ | итог | "
          "просадка | медиана дня | плюсов | связь сторон | совпадений имён |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for pk in (s.get("rulers") or R.PAIR_ORDER):
        for dep in R.DEPOSITS:
            b = (s.get("books") or {}).get(RP._cell(pk, dep)) or {}
            st = b.get("all") or {}
            pr = b.get("parts") or {}
            lk, sk = R.parts_of(pk)
            ln = ((pr.get(lk) or {}).get("stats") or {}).get("n", 0)
            sn = ((pr.get(sk) or {}).get("stats") or {}).get("n", 0)
            col = b.get("collisions") or {}
            lk_ = b.get("link") or {}
            L.append(
                f"| {R.ruler_title(pk)} | ${int(dep)} | {st.get('n', 0)} | "
                f"{ln} | {sn} | {_u(st.get('usd'))} | {_p(st.get('final'))} | "
                f"{_p(st.get('max_dd'))} | {_u(st.get('day_median'))} | "
                f"{st.get('win', '—')} % | "
                f"{'—' if lk_.get('corr') is None else lk_['corr']} | "
                f"{col.get('n', 0)}"
                + (f" ({100 * col['share']:.1f} %)" if col.get("share")
                   else "") + " |")
    bad = []
    for pk in (s.get("rulers") or R.PAIR_ORDER):
        for dep in R.DEPOSITS:
            b = (s.get("books") or {}).get(RP._cell(pk, dep)) or {}
            if b.get("one_sided"):
                bad.append(f"{R.ruler_title(pk)} ${int(dep)}: нет стороны "
                           + ", ".join(R.ruler_title(x)
                                       for x in b["one_sided"]))
    if bad:
        L += ["", "**ВНИМАНИЕ: общий счёт не собран из двух сторон** — "
              + "; ".join(bad) + ". Односторонняя книга выглядит как "
              "обычная и молчит о том, что половины решений в ней нет; "
              "числа выше по этим книгам читать нельзя.", ""]
    L += ["", "## Один счёт против двух раздельных", "",
          "Слева общий счёт: депозит один на обе стороны. Справа те же "
          "книги, как их показывают собственные вкладки: у каждой свой "
          "депозит, то есть капитала вдвое больше. Поэтому сравниваются "
          "ДЕНЬГИ и просадка, а проценты у них от разных капиталов.", "",
          "| книга | депозит | Σ $ общий счёт | просадка общего | "
          "Σ $ длинная отдельно | Σ $ короткая отдельно | Σ $ двух счетов | "
          "сделок общий / врозь |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for pk in (s.get("rulers") or R.PAIR_ORDER):
        lk, sk = R.parts_of(pk)
        for dep in R.DEPOSITS:
            b = (s.get("books") or {}).get(RP._cell(pk, dep)) or {}
            st = b.get("all") or {}
            sep = b.get("separate") or {}
            ls, ss = sep.get(lk) or {}, sep.get(sk) or {}
            both = (None if not ls and not ss
                    else round((ls.get("usd") or 0.0) + (ss.get("usd") or 0.0), 2))
            L.append(
                f"| {R.ruler_title(pk)} | ${int(dep)} | {_u(st.get('usd'))} | "
                f"{_p(st.get('max_dd'))} | {_u(ls.get('usd'))} | "
                f"{_u(ss.get('usd'))} | {_u(both)} | "
                f"{st.get('n', 0)} / {(ls.get('n') or 0) + (ss.get('n') or 0)} |")
    L += [""]
    # Издержки — тем же разделом, что у отдельных книг: одно ядро, один
    # текст, и разойтись им негде.
    L += RP.costs_block(s)
    L += ["## Чего эти числа НЕ говорят", "",
          "- Живого исполнения здесь нет: исходы позиций взяты из кэшей "
          "реплея обеих книг, посчитанных по барам записи. Очередь в "
          "стакане и задержка входа не моделируются.",
          "- Внутри одной секунды деньги достаются лучшему по |прогнозу| "
          "решению — правило очереди объявлено до прогона и одно на обе "
          "стороны. Другое правило дало бы другой состав, и это ось для "
          "отдельного замера, а не свойство рынка.",
          "- Общий счёт — ХЕДЖ-режим: шорт по имени, которое держит "
          "длинная сторона, разрешён. В одностороннем режиме биржи он "
          "срезал бы длинную позицию, и число совпадений выше есть цена "
          "режима.",
          "- Веса модели видели эти часы: пересчёт истории читается как "
          "оценка СВЕРХУ. Судит форвард.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="общий счёт длинной и короткой")
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run()
    with open(R.PAIR_ARTIFACT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(R.PAIR_ARTIFACT + ".tmp", R.PAIR_ARTIFACT)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-pair.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"общий счёт длинной и короткой книги{a.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
