#!/usr/bin/env python3
"""Z3: катящийся склад лесенки — проход по сырью, свёртка к минуте.

Машинерия склада НЕ копируется: обход суток, состояние с диска,
параллельность, отчёт и публикация живут в `z2_book/fold.py`, а здесь
регистрируется свой сворачиватель — набор полей, функция суток символа и
свой каталог. Вторая копия этой машинерии — то, чем в проекте дважды
кончались `nulls.py` и загрузчик funding.

Почему склад обязан быть КАТЯЩИМСЯ. Лесенка живёт только в сырье:
минутный склад Z2 её не содержит вовсе (95 % строки снимка — это ровно
то, что свёртка выбрасывает). Само сырьё при этом не стареет и не
удаляется — чистки записи в проекте нет, это проверено. Срок задаёт
другое: через 11–13 суток диск заполнится, сбор остановится, и
освобождать место придётся удалением старой книги (75 ГБ, больше там
стирать нечего). Свернуть надо до этого момента.

Разбор снимка идёт `json.loads`, и это не лень, а замер: на живой строке
он стоит 20.0 мкс против 35.8 у собственной регулярки по лесенке
(`z2_book/out/store/Z2-ladder-bench.md`). Планировать проход надо как
0.7 ч на сутки записи с наблюдённым множителем накладных.

Запуск:

    cd ~/algoth_v2 && mkdir -p research/z3_ladder/out
    cd ~/algoth_v2 && setsid nohup nice -n 19 .venv/bin/python \\
        research/z3_ladder/fold_ladder.py > research/z3_ladder/out/run.log 2>&1 &
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(ROOT, "research", "z2_book"),
          os.path.join(ROOT, "research", "b1_book")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bookfeat2 as B                                     # noqa: E402
import fold as F                                          # noqa: E402
import ladder as LD                                       # noqa: E402
from store import read_hour                               # noqa: E402

STORE = os.path.join(HERE, "out", "store")
VERSION = 1


def log_(m):
    print(m, flush=True)


def snap_full(line):
    """Снимок целиком, вместе с лесенкой.

    Момент наблюдения — ПОЗДНЕЕ из двух времён, ровно как у лёгкого
    разбора Z2: метку `t` сборщик ставит один раз на весь проход по
    символам, а проход занимает до 2.5 с, поэтому у символов, до которых
    очередь дошла позже, содержимое снимка новее собственной метки.
    """
    d = json.loads(line)
    bid, ask = float(d["bid"]), float(d["ask"])
    if bid <= 0 or ask <= 0:
        raise ValueError("нулевая цена")
    return {"t": max(float(d["t"]), float(d["ts"]) / 1000.0),
            "bid": bid, "ask": ask, "b": d["b"], "a": d["a"]}


def symbol_day(sym, day, book=None, trades=None):
    """Минутные потоки по уровням одного символа за сутки.

    Пропуск — это `None`, и минута без достаточного числа пар снимков
    тоже пропуск, а не нулевое наблюдение.
    """
    hours, t0 = F.hours_of_day(day)
    snaps, trs = [], []
    for h in hours:
        try:
            snaps += read_hour(os.path.join(book or F.BOOK, sym), h,
                               parse=snap_full)
        except Exception:                                 # noqa: BLE001
            pass
        try:
            trs += read_hour(os.path.join(trades or F.TRADES, sym), h,
                             parse=B.trade_line_px)
        except Exception:                                 # noqa: BLE001
            pass
    if not snaps:
        return None
    snaps.sort(key=lambda r: r["t"])
    trs.sort(key=lambda r: r[0])
    return fold_symbol(snaps, trs, t0)


def trades_between(trs, j, lo, hi):
    """Принты интервала `(lo, hi]` и новое положение указателя.

    Граница строгая слева: принт ровно в момент предыдущего снимка уже
    учтён предыдущим интервалом, и засчитать его снова значило бы
    объяснить убыль сделкой из чужого времени. Вынесено отдельной
    функцией не для красоты: внутри цикла это правило было мёртвым —
    указатель монотонный, и до сравнения дело не доходило, то есть
    защита существовала только на вид.
    """
    out = []
    while j < len(trs) and trs[j][0] <= hi:
        if trs[j][0] > lo:
            out.append((trs[j][2], trs[j][1], trs[j][3]))
        j += 1
    return out, j


def fold_symbol(snaps, trs, t0, n_min=None):
    """Свернуть снимки и ленту одного символа к минутам.

    Сделки раскладываются по интервалам МЕЖДУ снимками: убыль уровня
    объясняется сделкой, случившейся в том же интервале, а не где-то в
    минуте. Иначе принт из начала минуты оправдывал бы снятие в её
    конце — то же самое, чем плоха полосовая мера.
    """
    n_min = n_min or F.MIN_PER_DAY
    out = {f: [None] * n_min for f in LD.FIELDS}
    acc = {}
    j, prev = 0, None
    for cur in snaps:
        if prev is not None:
            win, j = trades_between(trs, j, prev["t"], cur["t"])
            m = B.minute_of(cur["t"], t0)
            if 0 <= m < n_min:
                a = acc.get(m)
                if a is None:
                    a = acc[m] = LD.minute_accum()
                LD.add_pair(a, LD.pair_flows(prev, cur, win))
        else:
            while j < len(trs) and trs[j][0] <= cur["t"]:
                j += 1
        prev = cur
    for m, a in acc.items():
        got = LD.close_minute(a)
        if got is None:
            continue
        for f in LD.FIELDS:
            out[f][m] = got[f]
    return out


F.register_folder("ladder", "fold_ladder", "symbol_day", LD.FIELDS,
                  lambda: STORE, version=VERSION, mins_field="pairs")


def write_report(path=None, store=None, log=log_):
    """Состояние ладдерного склада — файлом, который уезжает в git."""
    store = store or STORE
    os.makedirs(store, exist_ok=True)
    path = path or os.path.join(store, "Z3-store.md")
    st = F.scan(store)
    days = sorted(st)
    L = ["# Z3 — состояние склада лесенки\n\n",
         f"Версия свёртки {VERSION} · полей {len(LD.FIELDS)} · "
         f"суток на складе {len(days)}\n\n",
         "Лесенка живёт только в сырье: минутный склад Z2 её не "
         "содержит вовсе. Свободного места на 11–13 суток записи, "
         "поэтому склад катящийся — сворачивать надо раньше, чем сырьё "
         "состарится.\n\n",
         "| сутки | имён с записью | символо-минут | МиБ |\n",
         "|---|--:|--:|--:|\n"]
    tot = 0
    for d in days:
        h = st[d]
        tot += h.get("minutes", 0)
        L.append(f"| {d} | {h.get('rows', 0)} | {h.get('minutes', 0):,} | "
                 f"{h.get('bytes', 0) / 2**20:.1f} |\n".replace(",", " "))
    L.append(f"| **итого** | | **{tot:,}** | |\n".replace(",", " "))
    raw = [d for d in F.days_with_records() if F.day_is_closed(d)]
    miss = [d for d in raw if d not in st]
    L.append(f"\n**Суток в сырье {len(raw)}, на складе {len(days)}, "
             f"не свёрнуто {len(miss)}.**\n")
    if miss:
        L.append("\nНе свёрнуты: " + ", ".join(miss) + ".\n")
        L.append("\nСырьё сегодня не удаляет ничто — проверено, чистки "
                 "записи в проекте нет. Но через 11–13 суток диск "
                 "заполнится, сбор остановится, и освобождать место "
                 "будут удалением старой книги: больше там стирать "
                 "нечего. Свернуть лесенку надо ДО этого момента — не "
                 "потому, что файлы исчезнут сами, а потому что их "
                 "придётся стереть, чтобы сбор продолжился.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    log(f"отчёт склада лесенки: {path}; не свёрнуто суток {len(miss)}")
    return {"path": path, "days": len(days), "missing": len(miss),
            "minutes": tot}


def publish(msg):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), msg],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z3: склад лесенки")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--jobs", type=int, default=1)
    # Ключ можно повторять: очередь заданий пропускает аргументы только
    # из [A-Za-z0-9._/=-], и запятая в список имён не проходит. Страж
    # прав, править надо здесь. Запятая при этом остаётся — руками с
    # шелла так удобнее.
    ap.add_argument("--symbols", action="append", default=None)
    ap.add_argument("--refold", action="store_true")
    ap.add_argument("--restat", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(STORE, exist_ok=True)
    syms = None
    if a.symbols:
        syms = [x for chunk in a.symbols for x in chunk.split(",") if x]
    if not a.restat:
        days = [d for d in F.days_with_records(syms=syms)
                if F.day_is_closed(d)]
        if a.start:
            days = [d for d in days if d >= a.start]
        if a.end:
            days = [d for d in days if d <= a.end]
        log_(f"свёртка лесенки: суток {len(days)}, потоков {a.jobs}")
        for d in days:
            F.fold_day(d, syms=syms, jobs=a.jobs, store=STORE,
                       refold=a.refold, log=log_, kind="ladder")
    write_report(store=STORE)
    if not a.no_publish:
        publish("Z3: состояние склада лесенки")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
