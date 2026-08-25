#!/usr/bin/env python3
"""
Z2 — минутный склад записи стакана.

Зачем
-----

Скрин читает сырьё: суточная запись — это 725 имён по 86 400 снимков,
каждый снимок 6.3 КБ, из которых 95 % занимает лесенка, скрину не
нужная вовсе. Прогон по семнадцати суткам стоит около пяти часов, и
цена растёт линейно с календарём: запись не кончается.

Свёртка по минутам делается ОДИН РАЗ на сутки. Сутки после свёртки
весят десятки мегабайт вместо десятков гигабайт, и любой следующий
скрин читает их за секунды. Это ровно устройство A2 (хранилище свечей)
на другом сырье, и по той же причине: разрешение ХРАНЕНИЯ и разрешение
ЗАМЕРА — разные вещи.

Три правила, заложенные с самого начала
---------------------------------------

1. **Свёртка обязана воспроизводить сырой счёт бит в бит.** Правка
   скорости, меняющая числа, есть другая мера, а не ускорение. Закреплено
   тестом: матрицы со склада и матрицы из сырья сравниваются точно,
   вместе с пропусками.

2. **Состояние читается с диска, а не из дельты прогона.** `scan()`
   обходит файлы склада и читает их заголовки; сводка выводится из
   обхода. Дефект `build.py` в A2 был ровно в обратном — сводка писала,
   что сделал прогон, и после прерывания докладывала 42 партиции из 78.

3. **Текущие сутки не сворачиваются, пока не закончились.** Свёрнутый
   наполовину день неотличим по имени файла от полного, и следующий
   прогон принял бы его за готовый. Сутки годны к свёртке, только когда
   их конец уже в прошлом.

Чего склад НЕ делает
--------------------

Он не применяет порог `MIN_SNAPS` (тонкая минута — не наблюдение). Это
порог ЗАМЕРА, объявляемый до прогона, и зашей мы его в склад — смена
порога требовала бы пересвёртки. На складе лежит `snaps`, маску кладёт
тот же код, что и раньше.

Он не хранит лесенку. Всё, что считается по уровням цен (восполнение
конкретного уровня, смерть уровня, цена хода в снесённом нотионале),
требует сырья и остаётся дорогим замером.

Запуск на VPS:
  cd ~/algoth_v2 && mkdir -p research/z2_book/out/store
  setsid nohup nice -n 19 .venv/bin/python research/z2_book/fold.py \
      --jobs 3 > research/z2_book/out/fold.log 2>&1 &
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import bookfeat2 as B                                     # noqa: E402
from store import read_hour                               # noqa: E402

BOOK = os.path.join(RESEARCH, "b1_book", "out", "book")
TRADES = os.path.join(RESEARCH, "b1_book", "out", "trades")
STORE = os.path.join(HERE, "out", "store")
MIN_PER_DAY = 1440

# Версия арифметики свёртки. Меняется вместе с `bookfeat2.fold`, с
# полосой глубины или с составом полей. Склад чужой версии читателем НЕ
# берётся: он падает обратно на сырьё и говорит об этом словами —
# молча посчитать старыми числами хуже, чем посчитать медленно.
FOLD_VERSION = 1


def log_(m):
    print(m, flush=True)


def symbols(root=None):
    try:
        return sorted(d for d in os.listdir(root or BOOK)
                      if os.path.isdir(os.path.join(root or BOOK, d)))
    except OSError:
        return []


def day_bounds(day):
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(d.timestamp()), int((d + timedelta(days=1)).timestamp())


def hours_of_day(day):
    t0, _ = day_bounds(day)
    return [(datetime.fromtimestamp(t0 + h * 3600, timezone.utc)
             .strftime("%Y-%m-%d-%H")) for h in range(24)], t0


def day_is_closed(day, now=None):
    """Сутки годны к свёртке, только когда их конец уже в прошлом."""
    _, t1 = day_bounds(day)
    return t1 <= (time.time() if now is None else now)


def symbol_day(sym, day, book=None, trades=None):
    """Минутные признаки одного символа за сутки. Пропуск — это None."""
    hours, t0 = hours_of_day(day)
    snaps, trs = [], []
    for h in hours:
        try:
            snaps += read_hour(os.path.join(book or BOOK, sym), h,
                               parse=B.snap_line)
        except Exception:                                 # noqa: BLE001
            pass
        try:
            trs += read_hour(os.path.join(trades or TRADES, sym), h,
                             parse=B.trade_line)
        except Exception:                                 # noqa: BLE001
            pass
    if not snaps:
        return None
    snaps.sort(key=lambda r: r[0])
    trs.sort(key=lambda r: r[0])
    return B.fold(snaps, trs, t0, MIN_PER_DAY)


def _row(got):
    """Словарь списков -> матрица (поле × минута) float32."""
    A = np.full((len(B.FOLD_FIELDS), MIN_PER_DAY), np.nan, dtype=np.float32)
    for i, f in enumerate(B.FOLD_FIELDS):
        v = got.get(f)
        if v is None:
            continue
        A[i] = [np.nan if x is None else x for x in v]
    return A


_JOB = {}


def _init(book, trades):
    _JOB["book"], _JOB["trades"] = book, trades


def _one(arg):
    sym, day = arg
    got = symbol_day(sym, day, book=_JOB.get("book"),
                     trades=_JOB.get("trades"))
    return sym, (None if got is None else _row(got))


def fold_day(day, syms=None, jobs=1, book=None, trades=None, store=None,
             refold=False, log=log_, now=None):
    """Свернуть сутки на склад. Возвращает 'ok' / 'есть' / причину отказа."""
    store = store or STORE
    if not day_is_closed(day, now):
        log(f"  {day}: сутки не кончились — не сворачиваю")
        return "не кончились"
    path = os.path.join(store, day + ".npz")
    if os.path.exists(path) and not refold:
        head = _head(path)
        if head and head["version"] == FOLD_VERSION:
            return "есть"
        log(f"  {day}: на складе версия {head and head['version']}, "
            f"пересворачиваю под {FOLD_VERSION}")
    syms = list(syms if syms is not None else symbols(book or BOOK))
    if not syms:
        log(f"  {day}: имён в записи нет")
        return "пусто"
    os.makedirs(store, exist_ok=True)
    n = len(syms)
    A = np.full((len(B.FOLD_FIELDS), n, MIN_PER_DAY), np.nan,
                dtype=np.float32)
    t_start = time.time()
    done = have = 0
    if jobs and jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs, initializer=_init,
                     initargs=(book or BOOK, trades or TRADES)) as pool:
            it = pool.imap_unordered(_one, [(s, day) for s in syms],
                                     chunksize=1)
            idx = {s: r for r, s in enumerate(syms)}
            for sym, row in it:
                done += 1
                if row is not None:
                    A[:, idx[sym], :] = row
                    have += 1
                _progress(day, done, n, have, t_start, log)
    else:
        _init(book or BOOK, trades or TRADES)
        for r, sym in enumerate(syms):
            _, row = _one((sym, day))
            done += 1
            if row is not None:
                A[:, r, :] = row
                have += 1
            _progress(day, done, n, have, t_start, log)
    mins = int(np.isfinite(A[B.FOLD_FIELDS.index("mid_open")]).sum())
    payload = {f: A[i] for i, f in enumerate(B.FOLD_FIELDS)}
    payload["symbols"] = np.array(syms)
    payload["version"] = np.array([FOLD_VERSION], dtype=np.int32)
    payload["rows"] = np.array([have], dtype=np.int32)
    payload["minutes"] = np.array([mins], dtype=np.int64)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **payload)
    os.replace(tmp, path)
    log(f"  {day}: свёрнуто, имён с записью {have} из {n}, "
        f"символо-минут {mins:,}, {os.path.getsize(path) / 2**20:.1f} МиБ, "
        f"{time.time() - t_start:.0f} с")
    return "ok"


def _progress(day, done, n, have, t_start, log, every=50):
    if done % every or done == n:
        return
    el = time.time() - t_start
    log(f"    {day}: свёрнуто имён {done}/{n} (с записью {have}), "
        f"{el:.0f} с, осталось ~{el / done * (n - done):.0f} с")


def _head(path):
    """Заголовок суток со СКЛАДА: версия, имена, объём — с диска."""
    try:
        with np.load(path) as z:
            return {"version": int(z["version"][0]),
                    "symbols": int(len(z["symbols"])),
                    "rows": int(z["rows"][0]),
                    "minutes": int(z["minutes"][0]),
                    "bytes": os.path.getsize(path)}
    except Exception:                                     # noqa: BLE001
        return None


def scan(store=None):
    """Состояние склада, прочитанное С ДИСКА, а не из дельты прогона."""
    store = store or STORE
    out = {}
    try:
        names = sorted(os.listdir(store))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".npz") or name.endswith(".tmp.npz"):
            continue
        day = name[:-4]
        head = _head(os.path.join(store, name))
        if head:
            out[day] = head
    return out


def read_day(day, syms, fields=None, store=None, log=log_):
    """Матрицы «символ × минута» со склада, или None — читайте сырьё.

    Порядок строк — запрошенный, а не складской: состав записи растёт
    по дням, и склад каждых суток знает СВОИ имена. Имя, которого в тех
    сутках не было, остаётся строкой пропусков — это и есть правда.
    """
    path = os.path.join(store or STORE, day + ".npz")
    if not os.path.exists(path):
        return None
    fields = tuple(fields or B.FOLD_FIELDS)
    try:
        with np.load(path) as z:
            ver = int(z["version"][0])
            if ver != FOLD_VERSION:
                log(f"  склад {day}: версия свёртки {ver} при нужной "
                    f"{FOLD_VERSION} — читаю сырьё")
                return None
            names = [str(s) for s in z["symbols"]]
            idx = {s: i for i, s in enumerate(names)}
            rows = np.array([idx.get(s, -1) for s in syms], dtype=np.int64)
            got = rows >= 0
            out = {}
            for f in fields:
                A = z[f]
                M = np.full((len(syms), MIN_PER_DAY), np.nan,
                            dtype=np.float32)
                if got.any():
                    M[got] = A[rows[got]]
                out[f] = M
    except Exception as e:                                # noqa: BLE001
        log(f"  склад {day}: не прочитался ({e}) — читаю сырьё")
        return None
    return out


def days_with_records(book=None, syms=None):
    """Какие сутки вообще есть в СЫРЬЕ — по именам часовых файлов."""
    book = book or BOOK
    days = set()
    for sym in (syms if syms is not None else symbols(book)):
        d = os.path.join(book, sym)
        try:
            for name in os.listdir(d):
                base = name.split(".")[0]
                if len(base) == 13 and base[4] == "-":
                    days.add(base[:10])
        except OSError:
            pass
    return sorted(days)


def write_manifest(store=None, log=log_):
    """Сводка склада ВЫВОДИТСЯ из обхода файлов, а не из прогона."""
    store = store or STORE
    st = scan(store)
    man = {
        "version": FOLD_VERSION,
        "fields": list(B.FOLD_FIELDS),
        "band": B.BAND,
        "days": st,
        "total_days": len(st),
        "total_minutes": sum(v["minutes"] for v in st.values()),
        "total_bytes": sum(v["bytes"] for v in st.values()),
    }
    os.makedirs(store, exist_ok=True)
    path = os.path.join(store, "manifest.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
    log(f"склад: суток {man['total_days']}, символо-минут "
        f"{man['total_minutes']:,}, {man['total_bytes'] / 2**30:.2f} ГиБ")
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z2: минутный склад стакана")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--refold", action="store_true")
    ap.add_argument("--restat", action="store_true",
                    help="только пересобрать сводку склада")
    a = ap.parse_args(argv)
    if a.restat:
        write_manifest()
        return 0
    syms = a.symbols.split(",") if a.symbols else None
    days = days_with_records(syms=syms)
    if a.start:
        days = [d for d in days if d >= a.start]
    if a.end:
        days = [d for d in days if d <= a.end]
    days = [d for d in days if day_is_closed(d)]
    if not days:
        log_("суток к свёртке нет")
        write_manifest()
        return 0
    log_(f"свёртка: суток {len(days)} ({days[0]}…{days[-1]}), "
         f"потоков {a.jobs}")
    for day in days:
        fold_day(day, syms=syms, jobs=a.jobs, refold=a.refold)
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
