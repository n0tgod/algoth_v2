#!/usr/bin/env python3
"""Z2: цена разбора ЛЕСЕНКИ — замер на живых строках записи.

Зачем отдельный замер. Минутный склад лесенки не содержит вовсе: 95 %
строки снимка — это ровно то, что свёртка выбрасывает, и любая мера по
ценовым уровням (восполнение выеденного уровня, смерть крупного уровня
без единого принта, снесённый нотионал на единицу хода) требует
возвращения к сырью. Планировать такой проход можно только по числу, и
числа у нас разошлись в двадцать раз: замер проекта на живой строке дал
`json.loads` 792 мкс, синтетика в песочнице — 34, при том что ЛЁГКИЙ
разбор стоит на обеих машинах одинаково (4.5 против 4.6 мкс). Значит
дело в самой строке, а не в процессоре, и переносить туда-сюда нельзя
ни то, ни другое.

Поэтому здесь меряется одно: сколько стоит разобрать НАСТОЯЩУЮ строку
на той машине, где проход и пойдёт. Рядом печатается отношение к
лёгкому разбору — оно переносимо, в отличие от абсолютных величин.

Сырьё читается ТЕМ ЖЕ `store.read_hour`, что и весь проект (с разбором
порчи архива), а не вторым читателем: разойдись они, замер описывал бы
другие строки. Разбор передаётся параметром `parse=lambda s: s` —
строки нужны сырыми.

Запуск:

    cd ~/algoth_v2 && mkdir -p research/z2_book/out/store
    cd ~/algoth_v2 && .venv/bin/python research/z2_book/bench_ladder.py
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(ROOT, "research", "b1_book")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bookfeat2 as B                                     # noqa: E402
import fold as F                                          # noqa: E402
from store import read_hour                               # noqa: E402

N_SYM = 12          # символов в выборке
N_LINES = 4000      # строк с символа
WINDOW_S = 60       # окно точечного прохода вокруг события, секунд
# Наблюдённое отставание живого прохода от чистой арифметики разбора.
# Взято не с потолка: D1 прочитал 12 суток за 90 минут (559 имён), то
# есть 7.5 мин на сутки при 3.0 расчётных по лёгкому разбору. Разницу
# делают чтение файлов, распаковка и посимвольные накладные, и она
# обязана стоять в оценке: иначе «13 часов» читается как обещание.
OVERHEAD = 2.5

_LAD = re.compile(r'"b":\[(.*?)\],"a":\[(.*?)\],"reach_b"')


def log_(m):
    print(m, flush=True)


def ladder(line):
    """Разбор ЛЕСЕНКИ: обе стороны как массивы «цена, размер».

    Отдельная функция, а не `json.loads`, потому что сравнивать надо
    именно то, что будет считать будущий проход: ему нужны уровни, а не
    весь словарь. Промах регулярки — исключение, а не пустой ответ:
    молчаливая пустота на месте лесенки читалась бы как «уровней нет».
    """
    m = _LAD.search(line)
    if not m:
        raise ValueError("лесенка не найдена в строке")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bb = np.fromstring(m.group(1).replace("[", "").replace("]", ""),
                           sep=",")
        aa = np.fromstring(m.group(2).replace("[", "").replace("]", ""),
                           sep=",")
    return bb.reshape(-1, 2), aa.reshape(-1, 2)


def sample_lines(day, book=None, n_sym=N_SYM, n_lines=N_LINES, log=log_):
    """Сырые строки живой записи: по одному часу у нескольких символов."""
    book = book or F.BOOK
    syms = sorted(d for d in os.listdir(book)
                  if os.path.isdir(os.path.join(book, d)))
    if not syms:
        return {}
    step = max(1, len(syms) // n_sym)
    take = syms[::step][:n_sym]
    # BTC и ETH пишутся темой в 200 уровней вместо 50, то есть строка у
    # них вчетверо тяжелее. Ровный шаг по алфавиту их пропустил, и
    # первый отчёт мерил цену без самых дорогих строк — добавляем явно.
    for heavy in ("BTCUSDT", "ETHUSDT"):
        if heavy in syms and heavy not in take:
            take.append(heavy)
    out = {}
    for s in take:
        d = os.path.join(book, s)
        hours = sorted(h.split(".")[0] for h in os.listdir(d)
                       if h.startswith(day))
        if not hours:
            continue
        h = hours[len(hours) // 2]
        rows = read_hour(d, h, log=lambda m: None, parse=lambda x: x)
        if rows:
            out[s] = rows[:n_lines]
    log(f"выборка: символов {len(out)}, строк "
        f"{sum(len(v) for v in out.values())}")
    return out


def bench(fn, lines, cap=2000):
    """Микросекунды на строку. Возвращает None, если разбор не прошёл."""
    use = lines[:cap]
    if not use:
        return None
    try:
        for l in use[:5]:
            fn(l)
    except Exception:                                     # noqa: BLE001
        return None
    t0 = time.perf_counter()
    for l in use:
        fn(l)
    return (time.perf_counter() - t0) / len(use) * 1e6


def snaps_of_day(day, store=None):
    """Снимки за сутки: сколько всего и сколько в минуте НА ИМЯ.

    Делить надо на символо-минуты склада, а не на число выбранных для
    замера имён: первая версия делила на одиннадцать и завышала
    плотность в 66 раз, отчего точечный проход выходил 192 часа вместо
    трёх минут. Знаменатель берётся оттуда же, откуда числитель.
    """
    p = os.path.join(store or F.STORE, day + ".npz")
    if not os.path.exists(p):
        return None
    with np.load(p) as z:
        a = z["snaps"]
    v = a[np.isfinite(a)]
    if not v.size:
        return None
    return {"total": float(v.sum()), "per_min": float(v.sum()) / v.size}


def measure(day, book=None, store=None, n_sym=N_SYM, n_lines=N_LINES,
            log=log_):
    got = sample_lines(day, book=book, n_sym=n_sym, n_lines=n_lines, log=log)
    if not got:
        return None
    rows = []
    for s, lines in sorted(got.items()):
        try:
            bb, _aa = ladder(lines[0])
            lev = int(len(bb))
        except Exception:                                 # noqa: BLE001
            lev = 0
        rows.append({
            "sym": s, "lines": len(lines), "levels": lev,
            "bytes": float(np.mean([len(l) for l in lines[:200]])),
            "light": bench(B.snap_line, lines),
            "json": bench(json.loads, lines),
            "ladder": bench(ladder, lines),
        })
    return {"day": day, "rows": rows, "snaps": snaps_of_day(day, store)}


def _med(v):
    return F._med([x for x in v if x is not None])


def write_report(res, path=None, log=log_):
    store = os.path.join(F.STORE)
    os.makedirs(store, exist_ok=True)
    path = path or os.path.join(store, "Z2-ladder-bench.md")
    rows = res["rows"]
    L = ["# Z2 — цена разбора лесенки\n\n",
         f"Живые строки записи за {res['day']}, символов {len(rows)}, "
         f"строк {sum(r['lines'] for r in rows)}.\n\n",
         "Минутный склад лесенки НЕ содержит: 95 % строки снимка — это "
         "ровно то, что свёртка выбрасывает. Любая мера по ценовым "
         "уровням требует возвращения к сырью, поэтому её цена и "
         "меряется здесь — на той машине, где проход и пойдёт.\n\n",
         "| символ | уровней | байт | лёгкий, мкс | json, мкс | "
         "лесенка, мкс | лесенка/лёгкий |\n",
         "|---|--:|--:|--:|--:|--:|--:|\n"]

    def _f(x, k=1):
        return "—" if x is None else f"{x:.{k}f}"

    for r in rows:
        rel = (r["ladder"] / r["light"]
               if r["ladder"] and r["light"] else None)
        L.append(f"| {r['sym']} | {r['levels']} | {r['bytes']:.0f} | "
                 f"{_f(r['light'])} | {_f(r['json'])} | {_f(r['ladder'])} | "
                 f"{_f(rel)}× |\n")

    lg = _med([r["light"] for r in rows])
    js = _med([r["json"] for r in rows])
    ld = _med([r["ladder"] for r in rows])
    L.append(f"\nМедианы: лёгкий **{_f(lg)}**, json **{_f(js)}**, лесенка "
             f"**{_f(ld)}** мкс на строку. Отношение лесенка/лёгкий = "
             f"**{_f(ld / lg if lg else None)}×** — переносимая величина, "
             "в отличие от абсолютных.\n")

    sn = res.get("snaps")
    if sn and ld:
        h = sn["total"] * ld * 1e-6 / 3600
        L.append(f"\n### Сколько стоит проход\n\n"
                 f"Снимков за сутки записи — {sn['total'] / 1e6:.1f} млн, "
                 f"в минуте на имя {sn['per_min']:.1f} (из склада, не из "
                 "допущения: делится на символо-минуты склада, а не на "
                 "число выбранных для замера имён).\n\n")
        full = h * 25
        real = full * OVERHEAD
        L.append(f"**Сплошной проход по лесенке: {h:.2f} ч на КАЖДЫЕ "
                 f"сутки записи, {full:.0f} ч на двадцать пять — но это "
                 "ЧИСТЫЙ разбор, нижняя граница.** Наблюдённые проходы "
                 "проекта шли примерно втрое медленнее арифметики "
                 "разбора (D1: 7.5 мин на сутки при 3.0 расчётных — "
                 "разницу делают чтение файлов, распаковка и "
                 f"посимвольные накладные), поэтому планировать надо "
                 f"**около {real / 24:.1f} суток счёта**, а не {full:.0f} "
                 "часов.\n\n")
        L.append("Меры лесенки при этом событийные: нужны секунды ВОКРУГ "
                 "события, а события дёшево находит скрин по складу. "
                 f"Точечный проход при окне {WINDOW_S} с на событие "
                 f"(одно имя, обе стороны; часы с тем же множителем "
                 f"{OVERHEAD}):\n\n"
                 "| событий | строк | часов |\n|--:|--:|--:|\n")
        for e in (1000, 10000, 100000):
            n = e * WINDOW_S * sn["per_min"] / 60.0
            L.append(f"| {e} | {n / 1e6:.2f} млн | "
                     f"{n * ld * 1e-6 / 3600 * OVERHEAD:.3f} |\n")
        L.append("\nПорядок работ от этого не меняется: скрин по складу "
                 "сначала не из-за цены, а потому что он же составляет "
                 "список мест, куда лесенке стоит заглядывать.\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    log(f"отчёт замера: {path}")
    return path


def publish(msg):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), msg],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z2: цена разбора лесенки")
    ap.add_argument("--day", default=None)
    ap.add_argument("--symbols", type=int, default=N_SYM)
    ap.add_argument("--lines", type=int, default=N_LINES)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(F.STORE, exist_ok=True)
    day = a.day
    if not day:
        days = [d for d in F.days_with_records() if F.day_is_closed(d)]
        if not days:
            log_("суток записи нет")
            return 1
        day = days[-1]
    res = measure(day, n_sym=a.symbols, n_lines=a.lines)
    if not res:
        log_(f"строк за {day} не нашлось")
        return 1
    write_report(res)
    if not a.no_publish:
        publish("Z2: цена разбора лесенки")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
