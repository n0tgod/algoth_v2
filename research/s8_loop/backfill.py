#!/usr/bin/env python3
"""Дописать старым сделкам книгу входа и выхода из записи стакана.

Зачем
-----

Издержки стали считаться проходом по стакану (`trades.exec_cost`), но
лесенка стамповывается в выбор и разбор только с этой правки. Сделки,
проведённые раньше, остались на плоском круге в 11 б.п. — а он занижает
стоимость торговли, потому что содержит одну комиссию и не содержит
спреда.

Пересчитывать их не надо ВЫДУМЫВАЯ: сборщик пишет снимок книги раз в
секунду по каждому символу, и моменты входа и выхода лежат в этой
записи целиком. Значит старым сделкам можно дописать ровно те же
данные, какие новые получают на лету, — не оценку, а тот же снимок.

Чего скрипт НЕ делает
---------------------

Не досчитывает то, чего в записи нет. Если снимка на нужный момент не
оказалось — запись началась позже, символ выпадал, час потерян — сделка
остаётся на плоском круге и помечается числом в сводке. Подставить
соседний час значило бы выдать другой рынок за наш; подставить
умолчание — сделать пропуск неотличимым от измерения.

Не меняет ни исход сделки, ни выбор: `got` — движение цены — остаётся
тем же. Меняется только цена исполнения, то есть издержка.

Порядок запуска
---------------

    .venv/bin/python research/s8_loop/backfill.py --pretest

Останавливать цикл НЕ надо, и это не удобство, а требование
безопасности: `picks.jsonl` и `review.jsonl` — приписные журналы,
которые ведёт цикл, а сторож поднимает его обратно через минуту после
любого `pkill`. Переписать такой файл целиком значит однажды потерять
час выборов, причём молча — файл останется исправным на вид.

Поэтому пересчёт не трогает историю вовсе: он пишет СВОЙ приписной файл
`books.jsonl`, а `trades.build` подмешивает его тем сделкам, у которых
своей книги нет. Отменяется пересчёт удалением одного файла.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import summary as SM                                       # noqa: E402
import trades as TR                                        # noqa: E402

# Каталоги те же, что у цикла, но `train` не импортируется: он тянет
# numpy, а пересчёту нужны только стандартная библиотека и чтение
# записи. Совпадение путей закреплено тестом, а не надеждой.
OUT = os.path.join(HERE, "out")
MODEL_DIRS = {False: os.path.join(OUT, "model"),
              True: os.path.join(OUT, "model_pretest")}


BOOKS = "books.jsonl"


def read_rows(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    # Битую строку сохраняем как есть: выбросить её
                    # значило бы потерять сделку молча.
                    out.append(line.rstrip("\n"))
    except OSError:
        pass
    return out


class Books:
    """Книга на момент, с памятью прочитанных часов.

    Час читается целиком (`store.read_hour` умеет спасать испорченные
    архивы, и второй копии этой логики в проекте быть не должно), но
    читается ОДИН раз: у трёхсот сделок моменты входа и выхода
    ложатся на несколько десятков часов, и без памяти один и тот же
    файл разбирался бы по два десятка раз.
    """

    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.reads = 0

    def rows(self, sym, hour):
        key = (sym, hour)
        if key not in self.cache:
            try:
                self.cache[key] = SM.read_hour(
                    os.path.join(self.root, "book", sym), hour)
            except OSError:
                self.cache[key] = []
            self.reads += 1
        return self.cache[key]

    def at(self, sym, ts, tol=120.0):
        if ts is None:
            return None
        best = None
        for back in (0, 3600):
            h = datetime.fromtimestamp(
                ts - back, timezone.utc).strftime("%Y-%m-%d-%H")
            for r in self.rows(sym, h):
                t = r.get("t")
                if t is None or t > ts or ts - t > tol:
                    continue
                if not r.get("bid") or not r.get("ask"):
                    continue
                if best is None or t > best.get("t", 0):
                    best = r
            if best is not None:
                break
        if best is None:
            return None
        b = TR.cum_ladder(best.get("b"))
        a = TR.cum_ladder(best.get("a"))
        if not b or not a:
            return None
        return {"mid": (best["bid"] + best["ask"]) / 2.0,
                "b": b, "a": a, "t": round(best.get("t") or ts, 1)}


def stamp_picks(rows, books, log, have=None, out=None):
    """Книга в момент РЕШЕНИЯ, а не в момент закрытия часа сигнала.

    У записи есть `at_ts` — когда цикл на самом деле выбрал. Это и есть
    первый момент, когда войти было можно; закрытие часа сигнала на
    6–15 минут раньше и входом быть не могло.
    """
    have, out = have if have is not None else {}, out if out is not None else {}
    done = miss = skip = no_ts = 0
    for pk in rows:
        if isinstance(pk, str):
            continue
        arm, hour, ts = pk.get("arm") or "gbm", pk.get("hour"), pk.get("at_ts")
        if not ts:
            # Момент решения не записан — момент входа неизвестен.
            # Взять закрытие часа значило бы вернуть тот самый подарок,
            # ради снятия которого всё и делается.
            no_ts += 1
            continue
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                k = (arm, hour, p.get("sym"))
                if p.get("cum") or "in" in have.get(k, out.get(k, {})):
                    skip += 1
                    continue
                got = books.at(p.get("sym"), ts)
                if got:
                    out.setdefault(k, {"arm": arm, "hour": hour,
                                       "sym": p.get("sym")})["in"] = got
                    done += 1
                else:
                    miss += 1
    log(f"выборы: дописано {done}, уже было {skip}, "
        f"нет снимка {miss}, без момента решения {no_ts}")
    return done, out


def stamp_reviews(rows, books, log, have=None, out=None, hold_h=TR.HOLD_H):
    have, out = have if have is not None else {}, out if out is not None else {}
    done = miss = skip = 0
    for rv in rows:
        if isinstance(rv, str):
            continue
        arm, hour = rv.get("arm") or "gbm", rv.get("hour")
        end = TR.hour_end(hour)
        if end is None:
            continue
        ts = end + hold_h * 3600
        for r in rv.get("rows") or []:
            k = (arm, hour, r.get("sym"))
            if r.get("cum") or "out" in have.get(k, out.get(k, {})):
                skip += 1
                continue
            got = books.at(r.get("sym"), ts)
            if got:
                out.setdefault(k, {"arm": arm, "hour": hour,
                                   "sym": r.get("sym")})["out"] = got
                done += 1
            else:
                miss += 1
    log(f"разборы: дописано {done}, уже было {skip}, нет снимка {miss}")
    return done, out


def compare(picks, reviews, log, books=None):
    """Счёт до и после — по каждой руке, деньгами.

    Это и есть ответ на вопрос «насколько плоский круг льстил»: одни и
    те же сделки, одни и те же движения цены, разная цена исполнения.
    """
    out = {}
    for arm in ("gbm", "nn"):
        tr = TR.build(picks, reviews, now=time.time(), books=books)
        _, bal = TR.account(tr, arm)
        s = TR.summary(tr, arm)
        out[arm] = {"balance": bal, "closed": s.get("closed"),
                    "exec_n": s.get("exec_n"), "flat": s.get("cost_flat"),
                    "exec_med_bp": s.get("exec_med_bp"),
                    "fee_med_bp": s.get("fee_med_bp"),
                    "slip_med_bp": s.get("slip_med_bp"),
                    "fee_known": s.get("fee_known"),
                    "partial": s.get("exec_partial"),
                    "net_bp_avg": s.get("net_bp_avg")}
        log(f"  {arm}: счёт {bal} $, закрытых {s.get('closed')}, "
            f"по книге {s.get('exec_n')}, плоских {s.get('cost_flat')}")
    return out


def report(before, after, n1, n2, reads, mdir):
    """Отчёт о пересчёте: что было, что стало, чего не хватило."""
    L = [f"# Пересчёт издержек по записанной книге — {mdir}", "",
         f"Дописано книг: вход {n1}, выход {n2}. "
         f"Прочитано символо-часов записи: {reads}.", "",
         "Движение цены (`got`) не менялось — менялась только цена",
         "исполнения. Сделки, которым записи не хватило, остались на",
         "плоском круге в 11 б.п. и сосчитаны отдельной строкой.", "",
         "| рука | счёт до | счёт после | закрытых | по книге | плоских |",
         "|---|---|---|---|---|---|"]
    for arm in ("gbm", "nn"):
        b, af = before.get(arm, {}), after.get(arm, {})
        L.append(f"| {arm} | {b.get('balance')} $ | {af.get('balance')} $ "
                 f"| {af.get('closed')} | {af.get('exec_n') or 0} "
                 f"| {af.get('flat') or 0} |")
    L += ["", "| рука | круг, медиана | комиссия | спред | "
          "ставка настоящая | книга тонка |", "|---|---|---|---|---|---|"]
    for arm in ("gbm", "nn"):
        af = after.get(arm, {})
        L.append(f"| {arm} | {af.get('exec_med_bp')} б.п. "
                 f"| {af.get('fee_med_bp')} | {af.get('slip_med_bp')} "
                 f"| {af.get('fee_known')}/{af.get('exec_n') or 0} "
                 f"| {af.get('partial')} |")
    L += ["", "Плоский круг в 11 б.п. содержал одну комиссию и не содержал",
          "спреда. Разница между двумя столбцами счёта — цена этой",
          "условности на данной выборке.", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pretest", action="store_true",
                    help="каталог предпросмотра, а не боевой")
    ap.add_argument("--root", default=SM.BOOK_ROOT)
    ap.add_argument("--dry", action="store_true",
                    help="посчитать и НЕ дописывать файл")
    a = ap.parse_args()

    def log(m):
        print(m, flush=True)

    mdir = MODEL_DIRS[bool(a.pretest)]
    ppath = os.path.join(mdir, "picks.jsonl")
    rpath = os.path.join(mdir, "review.jsonl")
    bpath = os.path.join(mdir, BOOKS)
    if not os.path.exists(ppath):
        raise SystemExit(f"нет файла выборов: {ppath}")
    picks = [r for r in read_rows(ppath) if not isinstance(r, str)]
    reviews = [r for r in read_rows(rpath) if not isinstance(r, str)]
    have = TR.load_books(bpath)
    log(f"каталог {mdir}: выборов {len(picks)}, разборов {len(reviews)}, "
        f"уже дописано {len(have)}")

    log("до пересчёта:")
    before = compare(picks, reviews, log, books=have)

    books = Books(a.root)
    t0 = time.time()
    n1, new = stamp_picks(picks, books, log, have)
    n2, new = stamp_reviews(reviews, books, log, have, new)
    log(f"прочитано символо-часов записи: {books.reads}, "
        f"{time.time() - t0:.0f} с")

    merged = dict(have)
    for k, v in new.items():
        merged.setdefault(k, dict(v)).update(v)
    log("после пересчёта:")
    after = compare(picks, reviews, log, books=merged)

    if a.dry:
        log("--dry: файл не дописан")
    elif new:
        # Приписью, а не переписью: историю пересчёт не трогает вовсе.
        with open(bpath, "a", encoding="utf-8") as f:
            for v in new.values():
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
        log(f"дописано {len(new)} записей в {bpath}")
    else:
        log("дописывать нечего")

    # Отчёт файлом и в отслеживаемый каталог: прогон идёт на сервере, а
    # читается в другом месте, и пересказ консоли теряет числа.
    tag = "pretest" if a.pretest else "live"
    rp = os.path.join(OUT, f"S8-backfill-{tag}.md")
    with open(rp, "w", encoding="utf-8") as f:
        f.write(report(before, after, n1, n2, books.reads, mdir))
    log(f"отчёт: {rp}")

    sp = os.path.join(mdir, "backfill.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"at": time.time(), "dir": mdir,
                   "stamped_picks": n1, "stamped_reviews": n2,
                   "book_hours_read": books.reads,
                   "before": before, "after": after}, f,
                  ensure_ascii=False, indent=1)
    log(f"сводка: {sp}")


if __name__ == "__main__":
    main()
