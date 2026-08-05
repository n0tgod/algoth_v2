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
import gzip
import json
import os
import sys
import time
import zlib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(RESEARCH))
# Спасение испорченных архивов живёт у сборщика, и второй копии ему не
# надо. Путь ставится ЗДЕСЬ, а не достаётся побочным эффектом чужого
# импорта: работавший так модуль падает, стоит поменять порядок строк.
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import store as ST                                         # noqa: E402
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
    """Книга на заданные моменты — потоком, без подъёма часа в память.

    Первая версия держала прочитанные часы в словаре, чтобы не читать
    один файл дважды. На сервере это убил OOM-killer, и правильно: в
    часе 3600 снимков, в снимке до двухсот уровней по каждой стороне,
    то есть один символо-час — это сотни мегабайт объектов Python.
    Десяток таких — и восьмигигабайтная машина кончилась. Тот же класс
    ошибки, что в A2, где замер согласованности ног держал ряды
    множествами.

    Поэтому здесь наоборот: сначала собираются ВСЕ нужные моменты, потом
    каждый символо-час читается ровно один раз потоком, и из него
    остаётся только сжатая лесенка на нужную секунду. Память не зависит
    от длины истории вовсе — она равна числу сделок.
    """

    def __init__(self, root, log=None):
        self.root = root
        self.log = log or (lambda m: None)
        self.reads = self.rows = 0

    def _stream(self, path):
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8") as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except (OSError, EOFError, zlib.error) as e:
            # Порченый архив — единственный случай, когда файл всё же
            # поднимается целиком: спасение по членам живёт в `store`, и
            # второй копии этой логики в проекте быть не должно.
            self.log(f"  {os.path.basename(path)}: {e}, спасаю по членам")
            for r in ST.read_jsonl(path, self.log):
                yield r

    @staticmethod
    def _hour(ts):
        return datetime.fromtimestamp(
            ts, timezone.utc).strftime("%Y-%m-%d-%H")

    def collect(self, want, tol=120.0):
        """`{(символ, час): [моменты]}` → `{(символ, момент): книга}`.

        Момент может прийтись на первые секунды часа, где своих снимков
        ещё нет, поэтому каждый ищется в своём часе и в предыдущем.
        Дальше допуска снимок описывает уже другой рынок, и вернуть его
        значило бы выдать соседний час за наш.
        """
        # План: у каждого файла — свои искомые моменты, включая те, чей
        # час следующий. Так файл читается один раз, а не дважды.
        plan = {}
        for (sym, hour), tss in want.items():
            for ts in tss:
                for h in (self._hour(ts), self._hour(ts - 3600)):
                    plan.setdefault((sym, h), set()).add(ts)
        out, best = {}, {}
        n = 0
        for (sym, h), tss in sorted(plan.items()):
            n += 1
            if n % 25 == 0 or n == 1:
                self.log(f"  чтение {n}/{len(plan)}: {sym} {h}")
            d = os.path.join(self.root, "book", sym)
            for suf in (".jsonl", ".jsonl.gz"):
                path = os.path.join(d, h + suf)
                if not os.path.exists(path):
                    continue
                self.reads += 1
                for r in self._stream(path):
                    self.rows += 1
                    t = r.get("t")
                    if t is None or not r.get("bid") or not r.get("ask"):
                        continue
                    for ts in tss:
                        if t > ts or ts - t > tol:
                            continue
                        k = (sym, ts)
                        if k not in best or t > best[k][0]:
                            # Лесенка сжимается СРАЗУ: держать снимок
                            # целиком ради одной секунды и есть та
                            # ошибка, которая убила первый прогон.
                            b = TR.cum_ladder(r.get("b"))
                            a = TR.cum_ladder(r.get("a"))
                            if b and a:
                                best[k] = (t, {
                                    "mid": (r["bid"] + r["ask"]) / 2.0,
                                    "b": b, "a": a, "t": round(t, 1)})
        for k, (_, v) in best.items():
            out[k] = v
        return out


def plan(picks, reviews, have, log, hold_h=TR.HOLD_H):
    """Что именно надо прочитать: `{(символ, час): {моменты}}` и заявки.

    Сначала план целиком, потом одно чтение — иначе тот же символо-час
    разбирался бы по два десятка раз, а держать его в памяти нельзя.
    """
    want, jobs = {}, []
    no_ts = skip = 0
    for pk in picks:
        arm, hour, ts = pk.get("arm") or "gbm", pk.get("hour"), pk.get("at_ts")
        if not ts:
            # Момент решения не записан — момент входа неизвестен. Взять
            # закрытие часа значило бы вернуть тот самый подарок, ради
            # снятия которого всё и делается.
            no_ts += 1
            continue
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                sym = p.get("sym")
                if p.get("cum") or "in" in have.get((arm, hour, sym), {}):
                    skip += 1
                    continue
                want.setdefault((sym, Books._hour(ts)), set()).add(ts)
                jobs.append((arm, hour, sym, ts, "in"))
    for rv in reviews:
        arm, hour = rv.get("arm") or "gbm", rv.get("hour")
        end = TR.hour_end(hour)
        if end is None:
            continue
        ts = end + hold_h * 3600
        for r in rv.get("rows") or []:
            sym = r.get("sym")
            if r.get("cum") or "out" in have.get((arm, hour, sym), {}):
                skip += 1
                continue
            want.setdefault((sym, Books._hour(ts)), set()).add(ts)
            jobs.append((arm, hour, sym, ts, "out"))
    log(f"к пересчёту: {len(jobs)} концов сделок в "
        f"{len(want)} символо-часах; уже было {skip}, "
        f"без момента решения {no_ts}")
    return want, jobs


def stamp(jobs, got, log):
    """Заявки + прочитанные книги → записи приписного файла."""
    out, miss = {}, 0
    for arm, hour, sym, ts, kind in jobs:
        b = got.get((sym, ts))
        if not b:
            miss += 1
            continue
        out.setdefault((arm, hour, sym),
                       {"arm": arm, "hour": hour, "sym": sym})[kind] = b
    log(f"дописано концов: {len(jobs) - miss}, нет снимка: {miss}")
    return out, miss


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

    books = Books(a.root, log)
    t0 = time.time()
    want, jobs = plan(picks, reviews, have, log)
    got = books.collect(want)
    new, miss = stamp(jobs, got, log)
    n1 = sum(1 for v in new.values() if "in" in v)
    n2 = sum(1 for v in new.values() if "out" in v)
    log(f"прочитано файлов записи: {books.reads}, снимков {books.rows}, "
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
    # Повторный прогон дописывать нечего, и затирать им отчёт настоящего
    # нельзя: отчёт обязан описывать тот прогон, который его породил, а
    # «дописано 0» на месте настоящих чисел выглядит как «пересчёт
    # ничего не дал».
    if new or not os.path.exists(rp):
        with open(rp, "w", encoding="utf-8") as f:
            f.write(report(before, after, n1, n2, books.reads, mdir))
        log(f"отчёт: {rp}")
    else:
        log(f"отчёт не тронут (дописывать было нечего): {rp}")

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
