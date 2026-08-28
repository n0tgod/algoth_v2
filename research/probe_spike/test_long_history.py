#!/usr/bin/env python3
"""Проверки прогона на годах: каждая дорога исполняется, не только формула.

Дорог у одноразового зонда несколько — примитив, отбор событий, маска
своего месяца, издержки, реплей, отчёт, публикация, — и «тесты
зелёные» значит ровно те, которые тесты ИСПОЛНЯЮТ. Урок S11, где два
падения нашлись только живым прогоном.
"""
import json
import os
import re
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
Z1 = os.path.join(os.path.dirname(HERE), "z1_screen")
Z2 = os.path.join(os.path.dirname(HERE), "z2_book")
L3 = os.path.join(os.path.dirname(HERE), "l3_events")
for p in (HERE, Z1, Z2, L3):
    if p not in sys.path:
        sys.path.insert(0, p)

import data as D                                           # noqa: E402
import long_history as LH                                  # noqa: E402
import screen as Z                                         # noqa: E402
import spike as S                                          # noqa: E402
from test_probe import check, FAILED                       # noqa: E402

SYMS = [f"S{i:02d}USDT" for i in range(12)]


def synth_matrix(syms, times, interval="1m", log=None, columns=("open",)):
    """Подставной загрузчик цен: спокойный ряд плюс всплески на 3 %.

    Всплески расставлены со сдвигом по имени, чтобы фон существовал:
    синхронный сигнал не оставляет кросс-секции, которой меряется
    превышение (урок T1 — при четырёх символах фон 0–2 имени).
    """
    rng = np.random.default_rng(7)
    n, m = len(syms), len(times)
    P = np.empty((n, m), dtype=np.float32)
    for r in range(n):
        px = 100.0
        row = np.empty(m, dtype=np.float64)
        for j in range(m):
            px *= float(np.exp(rng.normal(0, 0.0004)))
            row[j] = px
        for k, j in enumerate(range(200 + r * 37, m - 600, 900)):
            row[j:] *= 1.03                      # всплеск вверх
            row[j + 1:j + 121] /= np.linspace(1.0, 1.012, 120)   # откат
        P[r] = row
    return P


def _setup():
    root = tempfile.mkdtemp()
    old = (LH.OUT, D.price_matrix, D.universe, Z.MIN_CROSS, Z.MIN_BUCKETS)
    LH.OUT = os.path.join(root, "out")
    D.price_matrix = synth_matrix
    D.universe = lambda: {s: {} for s in SYMS}
    Z.MIN_CROSS, Z.MIN_BUCKETS = 3, 1
    return root, old


def _restore(old):
    (LH.OUT, D.price_matrix, D.universe, Z.MIN_CROSS, Z.MIN_BUCKETS) = old


def test_trips_reuse_probe_formula():
    """Издержки считает формула ЗОНДА, а не своя арифметика.

    Числа закреплены прямо: книга 22 + (8.5+6.5)/2 + (5.7+5.7)/2 = 35.2,
    голая нога 11 + (8.5+6.5)/2 = 18.5. Вторая формула издержек в этом
    проекте уже расходилась с первой дважды.
    """
    book, solo = LH.trips()
    check("круг книги = 35.2", abs(book - 35.2) < 1e-6, f"{book}")
    check("круг голой ноги = 18.5", abs(solo - 18.5) < 1e-6, f"{solo}")
    a = {"spread_in": [8.5], "spread_out": [6.5],
         "hedge_in": [5.7], "hedge_out": [5.7]}
    check("это ровно round_trip зонда",
          abs(book - S.round_trip(a)[0]) < 1e-9, "формулы разошлись")
    check("это ровно solo_trip зонда",
          abs(solo - S.solo_trip(a)) < 1e-9, "формулы разошлись")


def test_gap_gives_no_event():
    """Дыра в сетке не рождает всплеск.

    Пропущенный бар даёт NaN, и ход через него обязан быть NaN, а не
    накопленным за пропуск движением: ровно этим отличается «нет
    наблюдения» от «наблюдение равно нулю» (класс дефекта L2).
    """
    P = np.full((1, 6), 100.0, dtype=np.float32)
    P[0, 2] = np.nan
    P[0, 3] = 110.0                      # +10 % относительно бара до дыры
    r = LH.primitives(P)["ret_1m"]
    check("ход через дыру не считается", not np.isfinite(r[0, 2]), str(r))
    check("и следующий за дырой тоже", not np.isfinite(r[0, 3]), str(r))
    P2 = np.array([[100.0, 103.0]], dtype=np.float32)
    check("а соседние бары считаются",
          abs(float(LH.primitives(P2)["ret_1m"][0, 1]) - 0.03) < 1e-5,
          str(LH.primitives(P2)["ret_1m"]))


def test_own_mask_keeps_events_in_their_month():
    """Хвост следующего месяца событий не даёт.

    Хвост нужен для форвардов конца месяца; засчитав его событием, мы
    посчитали бы одно и то же дважды — своим месяцем и чужим, и число
    наблюдений оказалось бы подделанным.
    """
    # Окно длиннее шага всплесков фикстуры: на коротком их не было бы
    # вовсе, и проверка «хвост режется» прошла бы на нуле против нуля.
    times = np.arange(0, 3000 * 60, 60, dtype=np.int64)
    P = synth_matrix(SYMS, times)
    prim = LH.primitives(P)
    all_own = np.ones(len(times), dtype=bool)
    half = all_own.copy()
    half[len(times) // 2:] = False
    n_all = sum(len(v[1]) for v in
                LH.collect_events(P, prim, all_own, log=lambda _m: None)
                .values())
    n_half = sum(len(v[1]) for v in
                 LH.collect_events(P, prim, half, log=lambda _m: None)
                 .values())
    check("события есть вообще", n_all > 0, f"{n_all}")
    check("маска своего месяца режет хвост", n_half < n_all,
          f"{n_half} против {n_all}")


def test_run_writes_report_and_year_profile():
    """Сквозной прогон: отчёт, профиль по годам, публикация по флагу."""
    root, old = _setup()
    published = []
    keep_pub = Z.publish
    Z.publish = lambda msg: published.append(msg)
    try:
        rc = LH.main(["--no-publish", "--tag", "t",
                      "--start", "2024-01-01", "--end", "2024-03-01"])
        check("прогон дошёл до конца", rc == 0, f"код {rc}")
        rep = os.path.join(LH.OUT, "SPIKE-long-t.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("профиль по годам есть", "Профиль по годам" in txt, txt[-600:])
        check("издержки названы перенесёнными",
              "перенесены, а не измерены здесь" in txt, txt[:1500])
        check("с флагом публикации нет", not published, str(published))
        got = json.load(open(os.path.join(LH.OUT, "spike-long-t.json"),
                             encoding="utf-8"))
        key = "|".join(str(x) for x in LH.KEY)
        check("ячейка вердикта посчитана", key in got["cells"],
              str(list(got["cells"])[:4]))
        # Проверять надо не наличие КЛЮЧА года, а посчитанные в нём
        # числа: `setdefault` заводит год и при выключенном замере, и
        # тогда «годы есть» проходит на пустых словарях (контроль со
        # снятым помесячным `measure` не кусался ровно поэтому).
        with_cell = [y for y, d in got["years"].items() if key in d]
        check("ячейка вердикта посчитана по годам", bool(with_cell),
              str({y: len(d) for y, d in got["years"].items()}))
        ev = [got["years"][y][key].get("events", 0) for y in with_cell]
        check("у года есть события", all(e > 0 for e in ev), str(ev))
        # И дорога до показа: строка года в таблице обязана нести число,
        # а не прочерк — формула, не доехавшая до отчёта, уже стоила
        # колонки прочерков в турнире.
        tbl = txt.split("Профиль по годам")[1]
        rows = [ln for ln in tbl.splitlines()
                if re.match(r"\|\s*20\d\d\s*\|", ln)]
        filled = [ln for ln in rows if "| —" not in ln]
        check("год в отчёте не прочерк", bool(filled),
              "\n".join(rows) or "строк года нет")
        LH.main(["--tag", "p", "--start", "2024-01-01", "--end", "2024-02-01"])
        check("без флага публикация случилась", bool(published),
              "публикация не вызвана — «публикует по умолчанию» "
              "однажды окажется выключенным молча")
    finally:
        Z.publish = keep_pub
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_trips_reuse_probe_formula,
             test_gap_gives_no_event,
             test_own_mask_keeps_events_in_their_month,
             test_run_writes_report_and_year_profile)
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
