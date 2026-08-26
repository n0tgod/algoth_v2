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


def peak_rss_mb():
    """Пик собственной памяти, МБ — по факту, а не по оценке."""
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def mem_line():
    """Сколько памяти доступно машине прямо сейчас, словами.

    Рядом живут сборщик, цикл обучения и чужие зонды: свободного окна
    у этой машины нет вовсе, и «влезет ли» решается не нашим пиком, а
    остатком.
    """
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return f"доступно {int(line.split()[1]) / 1024:.0f} МБ"
    except OSError:
        pass
    return "доступной памяти не видно"


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


def _read(dirpath, hour, parse):
    try:
        return read_hour(dirpath, hour, parse=parse)
    except Exception:                                     # noqa: BLE001
        return []


def symbol_day(sym, day, book=None, trades=None):
    """Минутные потоки по уровням одного символа за сутки.

    Считается ПО ЧАСАМ, а не суткам целиком, и это не оптимизация, а
    условие исполнимости. Первый полный проход убило ядро (код 137) на
    сто первом имени: снимок BTC и ETH несёт 200 уровней на сторону —
    около 45 КБ питоновских объектов, — и сутки такого имени это
    примерно 3.9 ГБ в списке. Рядом живут сборщик и цикл обучения, и
    восьми гигабайт не хватает. Час держит около 160 МБ в худшем случае.

    Порядок остаётся ДНЕВНЫМ: снимок, заехавший за границу часа,
    переносится в следующий шаг и сортируется вместе с ним, а
    несъеденные принты и последний снимок переходят туда же. Поэтому
    результат равен посуточному счёту бит в бит — это закреплено тестом,
    а не заявлено: правка памяти, меняющая числа, была бы другой мерой.

    Пропуск — это `None`, и минута без достаточного числа пар снимков
    тоже пропуск, а не нулевое наблюдение.
    """
    hours, t0 = F.hours_of_day(day)
    bd = os.path.join(book or F.BOOK, sym)
    td = os.path.join(trades or F.TRADES, sym)
    acc, prev, seen = {}, None, 0
    carry_s, carry_t = [], []
    for i, h in enumerate(hours):
        snaps = carry_s + _read(bd, h, snap_full)
        trs = carry_t + _read(td, h, B.trade_line_px)
        if not snaps:
            carry_s, carry_t = [], trs
            continue
        snaps.sort(key=lambda r: r["t"])
        trs.sort(key=lambda r: r[0])
        edge = t0 + (i + 1) * 3600
        cut = len(snaps)
        while cut and snaps[cut - 1]["t"] >= edge:
            cut -= 1
        carry_s, part = snaps[cut:], snaps[:cut]
        seen += len(part)
        prev, j = fold_chunk(acc, part, trs, t0, prev)
        carry_t = trs[j:]
    if carry_s:
        carry_s.sort(key=lambda r: r["t"])
        seen += len(carry_s)
        prev, _ = fold_chunk(acc, carry_s, carry_t, t0, prev)
    if not seen:
        return None
    return close_day(acc)


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


def fold_chunk(acc, snaps, trs, t0, prev=None, n_min=None):
    """Досчитать пары снимков в накопители минут; вернуть хвост.

    Вынесено из `fold_symbol` ради посуточного порядка при почасовом
    чтении: накопители и последний снимок переживают границу часа, и
    поток по уровням не знает, что его считают кусками.
    """
    n_min = n_min or F.MIN_PER_DAY
    j = 0
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
    return prev, j


def close_day(acc, n_min=None):
    """Накопители минут -> словарь списков по полям."""
    n_min = n_min or F.MIN_PER_DAY
    out = {f: [None] * n_min for f in LD.FIELDS}
    for m, a in acc.items():
        got = LD.close_minute(a)
        if got is None:
            continue
        for f in LD.FIELDS:
            out[f][m] = got[f]
    return out


def fold_symbol(snaps, trs, t0, n_min=None):
    """Свернуть снимки и ленту одного символа к минутам — сутки целиком.

    Остаётся ОБРАЗЦОМ: посуточный счёт, с которым почасовой обязан
    совпасть бит в бит. Сделки раскладываются по интервалам МЕЖДУ
    снимками: убыль уровня объясняется сделкой, случившейся в том же
    интервале, а не где-то в минуте. Иначе принт из начала минуты
    оправдывал бы снятие в её конце — то же самое, чем плоха полосовая
    мера.
    """
    acc = {}
    fold_chunk(acc, snaps, trs, t0, None, n_min)
    return close_day(acc, n_min)


F.register_folder("ladder", "fold_ladder", "symbol_day", LD.FIELDS,
                  lambda: STORE, version=VERSION, mins_field="pairs")


def write_report(path=None, store=None, log=log_):
    """Состояние ладдерного склада — файлом, который уезжает в git."""
    store = store or STORE
    os.makedirs(store, exist_ok=True)
    path = path or os.path.join(store, "Z3-store.md")
    st = F.scan(store)
    raw_days = [d for d in F.days_with_records() if F.day_is_closed(d)]
    if not st and not raw_days:
        # НЕ пишем вовсе: файл на диске подхватит любая следующая
        # публикация — так серверный отчёт и был затёрт пустым из
        # песочницы. Отсутствие склада и сырья означает не «склад
        # пуст», а «мы не на той машине».
        log(f"ни склада, ни сырья по пути {store} — отчёт не трогаю "
            "(это песочница, а не сервер)")
        return {"path": path, "days": 0, "missing": 0, "partial": 0,
                "minutes": 0}
    # Файл суток на складе — ещё не «сутки свёрнуты»: смоук по трём
    # именам оставляет файл, неотличимый по имени от полного. Такие
    # сутки считаются НЕсвёрнутыми и здесь, и при возобновлении —
    # обе дороги зовут одну `day_gap`.
    narrow = F.partial_days(st, store=store)
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
        mark = " ⚠ узкие" if d in narrow else ""
        L.append(f"| {d}{mark} | {h.get('rows', 0)} | "
                 f"{h.get('minutes', 0):,} | "
                 f"{h.get('bytes', 0) / 2**20:.1f} |\n".replace(",", " "))
    L.append(f"| **итого** | | **{tot:,}** | |\n".replace(",", " "))
    raw = raw_days
    miss = [d for d in raw if d not in st or d in narrow]
    full = len(days) - len(narrow)
    L.append(f"\n**Суток в сырье {len(raw)}, свёрнуто полностью {full}, "
             f"не свёрнуто {len(miss)}.**\n")
    if narrow:
        L.append("\nСвёрнуты по УЗКОМУ списку имён (файл есть, имён в нём "
                 "меньше "
                 "запрошенного — так остаётся смоук): "
                 + ", ".join(f"{d} (не хватает {n})"
                             for d, n in sorted(narrow.items()))
                 + ". Такие сутки считаются несвёрнутыми, и полный "
                 "проход сворачивает их заново.\n")
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
    log(f"отчёт склада лесенки: {path}; не свёрнуто суток {len(miss)}"
        + (f" (из них по узкому списку имён {len(narrow)})"
           if narrow else ""))
    return {"path": path, "days": len(days), "missing": len(miss),
            "partial": len(narrow), "minutes": tot}


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
        log_(f"свёртка лесенки: суток {len(days)}, потоков {a.jobs}, "
             f"{mem_line()}")
        for d in days:
            F.fold_day(d, syms=syms, jobs=a.jobs, store=STORE,
                       refold=a.refold, log=log_, kind="ladder")
            # Пик памяти печатается ПОСЛЕ КАЖДЫХ суток и по факту, а не
            # по оценке: первый полный проход убило ядро (код 137), и
            # снаружи это выглядело обычной тишиной. Числа нужны, чтобы
            # решать про `--jobs` замером, а не ощущением.
            log_(f"  память: пик {peak_rss_mb():.0f} МБ, {mem_line()}")
            # Отчёт публикуется ПОСЛЕ КАЖДЫХ суток, а не в конце:
            # проход по всей записи идёт десятки часов, а очередь
            # отдаёт лог задания только по завершении — то есть прогон
            # всё это время неотличим от повисшего. Урок D1, где
            # молчание часового прогона стоило круга переписки.
            if not a.no_publish:
                write_report(store=STORE)
                publish(f"Z3: склад лесенки, свёрнуты сутки {d}")
    got = write_report(store=STORE)
    # Публикуется отчёт, который что-то ОПИСЫВАЕТ. Прогон из песочницы
    # (ни склада, ни сырья) один раз уже затёр серверный отчёт пустым —
    # «суток на складе 0»: тот же класс, что два прогона на один
    # артефакт в S9, только там спасло имя с источником.
    if not a.no_publish:
        if got["days"] or got["missing"]:
            publish("Z3: состояние склада лесенки")
        else:
            log_("ни склада, ни сырья — публиковать нечего: "
                 "это песочница, а не сервер")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
