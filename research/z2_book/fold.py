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


# Полные сутки и годный состав. Числа объявлены здесь, а не в тексте
# отчёта: порог, живущий словом в прозе, однажды разойдётся с тем, по
# которому считали.
FULL_DAY = 0.95
THIN_ROWS = 100


def coverage(head):
    """Доля заполненных символо-минут: полные ли это сутки.

    Знаменатель — имена С ЗАПИСЬЮ, а не весь список сборщика: имя,
    которого в те сутки не было, не есть пропуск наблюдения.
    """
    if not head or not head.get("rows"):
        return None
    return head["minutes"] / (head["rows"] * MIN_PER_DAY)


def calendar_gaps(days):
    """Календарные сутки внутри окна записи, которых в СЫРЬЕ нет вовсе."""
    if len(days) < 2:
        return []
    a = datetime.strptime(days[0], "%Y-%m-%d")
    b = datetime.strptime(days[-1], "%Y-%m-%d")
    have = set(days)
    out, cur = [], a
    while cur <= b:
        d = cur.strftime("%Y-%m-%d")
        if d not in have:
            out.append(d)
        cur += timedelta(days=1)
    return out


def density(path, log=log_):
    """Медиана снимков в минуте за сутки — ПРЯМАЯ мера прорежения записи.

    Покрытие на неё слепо по построению: минута с одним снимком и
    минута с шестьюдесятью дают одну и ту же заполненную ячейку, и
    сутки, записанные вдвое реже, показывают те же 100 %. Плотность —
    единственное, что различает «запись есть» и «запись густа», а на
    ней стоит вся ось задержек гипотезы 7.

    Читается ОДНО поле склада (`snaps`), а не все восемнадцать.
    """
    try:
        with np.load(path) as z:
            a = z["snaps"]
    except Exception as e:                                # noqa: BLE001
        log(f"плотность {path}: не прочиталась ({e})")
        return None
    v = a[np.isfinite(a)]
    if not v.size:
        return None
    return {"med": float(np.median(v)), "p10": float(np.percentile(v, 10))}


HOURS_BACK = 7          # сколько последних суток показывать по часам
HOUR_DEV = 0.20         # отклонение часа от соседних суток, ниже которого молчим


def _med(v):
    """Медиана без дефекта `sorted(x)[n // 2]`.

    На ЧЁТНОЙ длине тот индекс даёт верхнее из двух средних, то есть
    завышенную базу. На живой сетке из шести суток это подняло планку и
    объявило прорежением пять часов вместо двух. Ровно этот дефект уже
    ловился однажды на живой странице (`Collector._median`) — и
    повторился в свежем коде: записанный урок не защищает новый модуль
    сам собой.
    """
    s = sorted(x for x in v if x is not None)
    n = len(s)
    if not n:
        return None
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def hour_series(path, field="snaps", log=log_):
    """Медиана поля ПО ЧАСАМ суток — по символам и минутам часа.

    Это и есть контроль, которого не даёт сравнение разных часов одного
    дня: проход сборщика зависит от потока обновлений книги, а тот
    растёт с активностью рынка, поэтому утро и середина дня несравнимы
    по построению. Сравнивать надо ОДИН И ТОТ ЖЕ час по разным суткам.
    """
    try:
        with np.load(path) as z:
            a = z[field]
    except Exception as e:                                # noqa: BLE001
        log(f"{field} по часам {path}: не прочиталась ({e})")
        return None
    out = []
    for h in range(24):
        v = a[:, h * 60:(h + 1) * 60]
        v = v[np.isfinite(v)]
        out.append(float(np.median(v)) if v.size else None)
    return out


def hour_density(path, log=log_):
    """Снимков в минуте по часам — частный случай `hour_series`."""
    return hour_series(path, "snaps", log=log)


def hour_spread(rows):
    """Размах ОДНОГО И ТОГО ЖЕ часа по суткам, в долях его медианы.

    Калибровка самой меры: пока размах не измерен, порог `HOUR_DEV`
    остаётся догадкой, и по сработавшему флагу нельзя сказать, что он
    означает. Первая живая сетка дала 0.40 — то есть вдвое больше
    порога, и список часов непуст даже в сутки без единого тяжёлого
    прогона.
    """
    out = []
    for h in range(24):
        v = [r[h] for r in rows.values() if r[h] is not None]
        m = _med(v)
        if v and m:
            out.append((max(v) - min(v)) / m)
    return _med(out)


def hour_table(store, days, back=HOURS_BACK, log=log_):
    """Сетка «сутки × час» за последние `back` суток плюс отклонения.

    Последние сутки сравниваются с МЕДИАНОЙ тех же часов у предыдущих —
    так тяжёлый счёт рядом со сбором отделяется от активности рынка.
    Рядом с каждым отклонением едут диапазон тех же часов у соседей и
    поток ленты: выросшая лента при упавших снимках означает рынок.
    """
    take = sorted(days)[-back:]
    rows, flow = {}, {}
    for d in take:
        p = os.path.join(store, d + ".npz")
        got = hour_series(p, "snaps", log=log)
        if got:
            rows[d] = got
            fl = hour_series(p, "trades", log=log)
            if fl:
                flow[d] = fl
    if len(rows) < 2:
        return rows, []
    last = sorted(rows)[-1]
    prev = sorted(rows)[:-1]
    off = []
    for h in range(24):
        base = [rows[d][h] for d in prev if rows[d][h] is not None]
        cur = rows[last][h]
        if not base or cur is None:
            continue
        med = _med(base)
        if not med or cur >= med * (1 - HOUR_DEV):
            continue
        fb = [flow[d][h] for d in prev
              if d in flow and flow[d][h] is not None]
        off.append({"h": h, "cur": cur, "med": med,
                    "lo": min(base), "hi": max(base),
                    "flow": flow.get(last, [None] * 24)[h],
                    "flow_med": _med(fb)})
    return rows, off


def full_days(st):
    """Сутки, годные к замеру: полные по времени И широкие по составу.

    Два условия, а не одно: сутки могут быть полными по времени и
    узкими по составу (ранние 25–30 имён), и тогда кросс-секции нет
    вовсе — урок T1, где при четырёх символах медианный фон был 0–2
    имени, а величины печатались и выглядели как результат.
    """
    return [d for d in sorted(st)
            if (coverage(st[d]) or 0) >= FULL_DAY
            and st[d].get("rows", 0) >= THIN_ROWS]


def write_report(path=None, store=None, book=None, syms=None, log=log_):
    """Отчёт о состоянии склада — ФАЙЛОМ, который уезжает в git.

    Сам склад в git не идёт (двоичные сутки), и без этого отчёта прогон
    свёртки не оставляет снаружи ни следа: снаружи он неотличим от «не
    запускали». Тот же урок, что дважды стоил потерянных прогонов
    (`width.py`, первый D1) — публикация есть ЧАСТЬ прогона.

    Главное число отчёта — не объём, а **сутки записи, которых на
    складе нет**: по нему видно, догнал склад запись или отстал.
    """
    store = store or STORE
    st = scan(store)
    have = days_with_records(book=book, syms=syms)
    missing = [d for d in have if d not in st]
    path = path or os.path.join(store, "Z2-store.md")
    L = ["# Z2 — состояние минутного склада\n"]
    L.append(f"\nВерсия свёртки {FOLD_VERSION} · полоса глубины ±{B.BAND} · "
             f"полей {len(B.FOLD_FIELDS)} · суток на складе {len(st)}\n")
    L.append("\nСклад — свёртка сырья по минутам, а не другая мера: "
             "равенство сырому счёту бит в бит закреплено тестом. Порог "
             "тонкой минуты здесь НЕ применён — он объявляется замером.\n")
    L.append("\n### Сутки склада\n\n")
    L.append("| сутки | символов | с записью | символо-минут | покрытие | "
             "снимков/мин | МиБ |\n")
    L.append("|---|--:|--:|--:|--:|--:|--:|\n")
    dens = {}
    for day in sorted(st):
        v = st[day]
        cov = coverage(v)
        d = density(os.path.join(store, day + ".npz"), log=lambda m: None)
        dens[day] = d
        L.append(f"| {day} | {v['symbols']} | {v['rows']} | "
                 f"{v['minutes']:,} | "
                 + ("—" if cov is None else f"{cov * 100:.0f} %")
                 + " | " + ("—" if d is None else f"{d['med']:.1f}")
                 + f" | {v['bytes'] / 2**20:.1f} |\n")
    tot_min = sum(v["minutes"] for v in st.values())
    tot_b = sum(v["bytes"] for v in st.values())
    L.append(f"| **итого** | | | **{tot_min:,}** | | "
             f"**{tot_b / 2**20:.0f}** |\n")
    L.append("\nПокрытие — символо-минуты против «имён с записью × 1440», "
             "то есть ПОЛНЫЕ ли это сутки. Без него 491 тыс. минут выглядят "
             "как много, а это две трети дня; замер, посчитанный по огрызку "
             "суток вперемешку с полными, описывает не то, что подписано.\n")
    L.append("\n**Снимков в минуте — плотность, и покрытие на неё слепо.** "
             "Минута с одним снимком и минута с шестьюдесятью дают одну и ту "
             "же заполненную ячейку, поэтому сутки, записанные вдвое реже, "
             "показывают те же 100 % покрытия. На плотности стоит вся ось "
             "задержек гипотезы 7: раз в секунду — это ~60 снимков в минуте, "
             "и просевшая колонка означает, что секундные задержки в те "
             "сутки записью НЕ разрешаются. Сравнивать сутки с соседними "
             "сутками, а не с ожиданием: это и есть контроль, которого не "
             "даёт сравнение разных часов одного дня.\n")
    live = [d for d in sorted(dens) if dens[d]]
    if len(live) >= 3:
        med = sorted(dens[d]["med"] for d in live)[len(live) // 2]
        low = [d for d in live if dens[d]["med"] < 0.8 * med]
        L.append(f"\nМедиана плотности по суткам склада — {med:.1f} "
                 "снимка в минуте. "
                 + (f"Заметно реже (ниже 80 % от неё): "
                    + ", ".join(f"{d} ({dens[d]['med']:.1f})" for d in low)
                    + ".\n" if low
                    else "Суток, записанных заметно реже, нет.\n"))
    part = [d for d in sorted(st) if (coverage(st[d]) or 0) < FULL_DAY]
    thin = [d for d in sorted(st) if st[d]["rows"] < THIN_ROWS]
    if part or thin:
        L.append(f"\nНеполные сутки (покрытие ниже {FULL_DAY:.0%}): "
                 + (", ".join(part) if part else "нет") + ". ")
        L.append(f"Узкие по составу (имён с записью меньше {THIN_ROWS}): "
                 + (", ".join(thin) if thin else "нет")
                 + " — на таком составе кросс-секции нет вовсе (урок T1: "
                 "при четырёх символах медианный фон 0–2 имени), и "
                 "замер по этим суткам ничего не измеряет.\n")
    ok_days = full_days(st)
    if ok_days:
        L.append(f"\n**Полных и широких суток {len(ok_days)}**, первые — "
                 f"{ok_days[0]}.\n")
    rows, off = hour_table(store, list(st), log=lambda m: None)
    if len(rows) >= 2:
        last = sorted(rows)[-1]
        L.append(f"\n### Плотность по часам, последние {len(rows)} суток\n\n")
        L.append("Один и тот же час по разным суткам — единственный честный "
                 "контроль: у сборщика проход зависит от потока обновлений "
                 "книги, а тот растёт с активностью рынка, поэтому утро и "
                 "середина дня несравнимы по построению. Тяжёлый счёт рядом "
                 "со сбором отделяется от рынка только так.\n\n")
        L.append("| сутки | " + " | ".join(f"{h:02d}" for h in range(24))
                 + " |\n")
        L.append("|---" * 25 + "|\n")
        for d in sorted(rows):
            L.append(f"| {d} | " + " | ".join(
                "—" if x is None else f"{x:.0f}" for x in rows[d]) + " |\n")
        sp = hour_spread(rows)
        if sp:
            L.append(f"\nРазмах ОДНОГО И ТОГО ЖЕ часа по разным суткам — "
                     f"**{sp:.0%} его медианы**, то есть больше порога "
                     f"{HOUR_DEV:.0%}, по которому ниже назван список часов. "
                     "Значит список — диагностика, а не тревога: рынок "
                     "двигает плотность сильнее порога сам, и на сутках без "
                     "единого тяжёлого прогона список тоже непуст. Порог не "
                     "трогаю (он объявлен до прогона) — рядом печатается "
                     "измеренное, чтобы флаг читался тем, чем является.\n")

        if off:
            def _one(o):
                t = (f"{o['h']:02d} ({o['cur']:.0f} против {o['med']:.0f}, "
                     f"у соседей {o['lo']:.0f}–{o['hi']:.0f}")
                if o["flow"] is not None and o["flow_med"]:
                    t += (f"; лента {o['flow']:.0f} против "
                          f"{o['flow_med']:.0f}")
                return t + ")"
            L.append(f"\n**Последние сутки ({last}) реже медианы тех же "
                     f"часов больше чем на {HOUR_DEV:.0%} в часах:** "
                     + ", ".join(_one(o) for o in off) + ".\n")
            L.append("\nЛента в скобках разделяет две причины, но только в "
                     "одну сторону: **выросшая лента при упавших снимках "
                     "означает рынок** — книга обновляется чаще, проход "
                     "сборщика длиннее. Обратное доводом НЕ является: под "
                     "нашей нагрузкой замедляется и запись ленты, поэтому "
                     "обычная лента при упавших снимках нашей нагрузки не "
                     "исключает. Если прорежение всё же наше — оно "
                     "невосполнимо: архива стакана нет нигде.\n")
        else:
            L.append(f"\nПо часам последние сутки ({last}) от соседних не "
                     "отличаются: прорежения нет.\n")

    L.append("\n### Догнал ли склад запись\n\n")
    L.append(f"Суток в сырье {len(have)}"
             + (f" ({have[0]}…{have[-1]})" if have else "")
             + f", на складе {len(st)}, **не свёрнуто {len(missing)}**.\n")
    if missing:
        L.append("\nНе свёрнуты: " + ", ".join(missing) + ".\n")
        L.append("\nСегодняшние сутки в этом списке стоят ПО ДЕЛУ — "
                 "незакончившийся день не сворачивается: свёрнутый "
                 "наполовину он неотличим по имени файла от полного. "
                 "Всё остальное означает, что свёртку надо догнать: "
                 "`fold.py --jobs 2`.\n")
    else:
        L.append("\nСклад покрывает запись целиком.\n")
    gaps = calendar_gaps(have)
    if gaps:
        L.append(f"\n**Дыры САМОЙ записи: {len(gaps)}** — "
                 + ", ".join(gaps) + ". Этих суток нет в сырье вовсе "
                 "(сборщик стоял), склад тут ни при чём и докачать их "
                 "неоткуда: архива стакана не существует нигде.\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    log(f"отчёт склада: {path}; не свёрнуто суток {len(missing)}")
    return {"path": path, "days": len(st), "missing": missing,
            "minutes": tot_min, "bytes": tot_b, "gaps": gaps,
            "full": ok_days}


def publish(msg):
    """Публикация — ЧАСТЬ прогона, а не отдельный шаг (урок `width.py`)."""
    import subprocess
    sh = os.path.abspath(os.path.join(RESEARCH, os.pardir, "tools",
                                      "publish.sh"))
    if not os.path.exists(sh):
        log_(f"публиковать нечем: нет {sh}")
        return
    log_("публикую состояние склада")
    try:
        r = subprocess.run(["bash", sh, msg],
                           cwd=os.path.dirname(os.path.dirname(sh)),
                           timeout=600)
        if r.returncode != 0:
            log_(f"публикация не прошла (код {r.returncode}); отчёт на "
                 f"диске, повторить: tools/publish.sh '{msg}'")
    except Exception as e:                                # noqa: BLE001
        log_(f"публикация не прошла ({e}); отчёт на диске")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z2: минутный склад стакана")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--refold", action="store_true")
    ap.add_argument("--restat", action="store_true",
                    help="только пересобрать сводку склада")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    syms0 = a.symbols.split(",") if a.symbols else None
    if a.restat:
        write_manifest()
        write_report(syms=syms0)
        if not a.no_publish:
            publish("Z2: состояние минутного склада")
        return 0
    syms = syms0
    days = days_with_records(syms=syms)
    if a.start:
        days = [d for d in days if d >= a.start]
    if a.end:
        days = [d for d in days if d <= a.end]
    days = [d for d in days if day_is_closed(d)]
    if not days:
        log_("суток к свёртке нет")
        write_manifest()
        write_report(syms=syms)
        if not a.no_publish:
            publish("Z2: состояние минутного склада")
        return 0
    log_(f"свёртка: суток {len(days)} ({days[0]}…{days[-1]}), "
         f"потоков {a.jobs}")
    for day in days:
        fold_day(day, syms=syms, jobs=a.jobs, refold=a.refold)
    write_manifest()
    rep = write_report(syms=syms)
    if not a.no_publish:
        publish(f"Z2: склад свёрнут, суток {rep['days']}, "
                f"символо-минут {rep['minutes']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
