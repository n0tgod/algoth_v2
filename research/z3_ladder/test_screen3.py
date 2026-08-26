#!/usr/bin/env python3
"""Проверки скрина по лесенке: каждая дорога ИСПОЛНЯЕТСЯ.

У одноразового зонда дорог несколько — чтение двух складов, нормы,
признаки, отбор событий, судья, отчёт, публикация, — и «тесты зелёные»
значит ровно те дороги, которые тест исполняет. Зонд S11 падал трижды
подряд на шагах, которых не касался ни один тест: печать после `del`,
чужая форма аргумента, каталог артефактов.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
Z2 = os.path.join(os.path.dirname(HERE), "z2_book")
for p in (HERE, Z2):
    if p not in sys.path:
        sys.path.insert(0, p)

import fold as F                                          # noqa: E402
import probe as P2                                        # noqa: E402
import screen as Z                                        # noqa: E402
import screen3 as S                                       # noqa: E402
from test_fold_ladder import write_ladder_rec             # noqa: E402
from test_probe import check, FAILED                      # noqa: E402

DAYS = ["2026-08-18", "2026-08-19", "2026-08-20"]
# Имён шесть, а не четыре: фон обязан существовать после
# запрета соседей, иначе контроль не строится ни для одного
# события и ячеек не будет вовсе.
SYMS = [f"S{i:02d}USDT" for i in range(6)]


def _thin_judge():
    """Понизить пороги СУДЬИ на время проверки дороги.

    Кросс-секции судья требует 50 имён, корзин — 50: на живых данных
    так и надо (при четырёх символах фон 0–2 имени, урок T1), но
    фикстура такого размера считалась бы минуты. Проверяется ДОРОГА —
    что два склада читаются, признаки считаются, события отбираются,
    судья зовётся и отчёт пишется, — а не осмысленность чисел.
    """
    keep = (Z.MIN_CROSS, Z.MIN_BUCKETS, Z.DEDUP_MIN)
    Z.MIN_CROSS, Z.MIN_BUCKETS, Z.DEDUP_MIN = 3, 1, 5
    return keep


def _fat_judge(keep):
    Z.MIN_CROSS, Z.MIN_BUCKETS, Z.DEDUP_MIN = keep


def _setup(sparse_last=True):
    """Три дня записи, у последнего минуты нарочно тонкие."""
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE, S.STORE, S.OUT,
           P2.BOOK, P2.TRADES, P2.STORE)
    F.BOOK = P2.BOOK = os.path.join(root, "book")
    F.TRADES = P2.TRADES = os.path.join(root, "trades")
    F.STORE = P2.STORE = os.path.join(root, "store2")
    S.STORE = os.path.join(root, "store3")
    S.OUT = os.path.join(root, "out")
    for i, d in enumerate(DAYS):
        thin = sparse_last and d == DAYS[-1]
        write_ladder_rec(root, SYMS, [d], hours=(10, 11, 12),
                         # 25 пар в минуте — между полом СКЛАДА (20)
                         # и полом ЗАМЕРА (30): при пяти парах склад
                         # и так кладёт пропуск, и снятие маски
                         # ничего бы не изменило — проверка не
                         # проверяла бы свой предмет.
                         per_min=(25 if thin else 40), seed=11 + i,
                         pull=0.05)
    later = time.time() + 10 * 86400
    for d in DAYS:
        F.fold_day(d, syms=SYMS, jobs=1, store=S.STORE, log=lambda m: None,
                   now=later, kind="ladder")
        F.fold_day(d, syms=SYMS, jobs=1, store=P2.STORE,
                   log=lambda m: None, now=later)
    return root, old


def _restore(old):
    (F.BOOK, F.TRADES, F.STORE, S.STORE, S.OUT,
     P2.BOOK, P2.TRADES, P2.STORE) = old


def test_screen_runs_the_whole_road_and_says_it_is_diagnostics():
    """Прогон целиком: два склада, судья, отчёт, числа в JSON."""
    root, old = _setup()
    keep = _thin_judge()
    try:
        rc = S.main(["--no-publish", "--tag", "test",
                     "--symbols", ",".join(SYMS)])
        check("прогон дошёл до конца", rc == 0, f"код {rc}")
        rep = os.path.join(S.OUT, "Z3-ladder-test.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("отчёт называет себя диагностикой",
              "диагностика, а не вердикт" in txt, txt[:400])
        check("в отчёте есть таблица ячеек", txt.count("| L |")
              + txt.count("| S |") > 0, "ни одной строки ячейки")
        check("отчёт называет круг нейтральной книги",
              "22 б.п." in txt, "круга издержек в отчёте нет")
        got = json.load(open(os.path.join(S.OUT, "z3-test.json"),
                             encoding="utf-8"))
        check("ячейки посчитаны", len(got["cells"]) > 0, "ячеек нет")
        check("снос по стороне посчитан", len(got["drift"]) > 0,
              "сноса нет")
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_thin_minutes_are_a_gap_not_an_observation():
    """Минута с малым числом пар не доезжает до замера вовсе.

    Порог живёт в ЗАМЕРЕ, а не на складе: склад хранит `pairs`, чтобы
    смена порога не требовала пересвёртки. Проверяется по числам самого
    прогона: у нарочно тонких суток минут лесенки обязано быть ноль,
    а у плотных — не ноль.

    Цена за те же тонкие сутки тоже обнуляется, и это правильно: запись
    ОДНА, а порог книжного склада (снимков в минуте) того же размера,
    что наш порог пар. Требовать здесь «цена на месте» значило бы
    требовать от фикстуры того, чего в природе записи нет.
    """
    root, old = _setup()
    keep = _thin_judge()
    try:
        S.main(["--no-publish", "--tag", "thin", "--symbols",
                ",".join(SYMS)])
        got = json.load(open(os.path.join(S.OUT, "z3-thin.json"),
                             encoding="utf-8"))
        width = {w[0]: (w[1], w[2]) for w in got["width"]}
        check("тонкие сутки дали ноль минут лесенки",
              width.get(DAYS[-1], (None, None))[0] == 0, str(width))
        check("и цена за те же сутки тоже пропуск",
              (width.get(DAYS[-1], (1, 1))[1] or 0) == 0, str(width))
        check("плотные сутки минуты дали",
              (width.get(DAYS[1], (0, 0))[0] or 0) > 0, str(width))
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_one_day_is_refused_because_norms_come_from_yesterday():
    """Одни сутки — отказ словами, а не пустая таблица.

    Норма символа берётся с ВЧЕРАШНИХ суток; на одних сутках считать
    нечего, и молчаливый пустой отчёт читался бы как «эффекта нет».
    """
    root, old = _setup()
    try:
        rc = S.main(["--no-publish", "--tag", "one",
                     "--symbols", ",".join(SYMS),
                     "--start", DAYS[0], "--end", DAYS[0]])
        check("одни сутки не считаются", rc == 1, f"код {rc}")
        check("и отчёт не написан",
              not os.path.exists(os.path.join(S.OUT, "Z3-ladder-one.md")),
              "отчёт есть, хотя считать было нечего")
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_horizons_must_match_the_book_screen():
    """Разошлись горизонты с Z2 — прогон отказывается, а не считает.

    Лесенка задумана ЧИСТОЙ версией той же меры, и сравнивать её с Z2
    можно только на одной сетке горизонтов. Ядро Z1 уже ловило этот
    класс: пилот объявил 1/5/15/60, а измерены были 5/15/60/240.
    """
    root, old = _setup()
    keep = P2.HORIZONS
    try:
        P2.HORIZONS = (7, 13)
        rc = S.main(["--no-publish", "--tag", "hz",
                     "--symbols", ",".join(SYMS)])
        check("расхождение горизонтов останавливает прогон",
              rc == 1, f"код {rc}")
    finally:
        P2.HORIZONS = keep
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_stats_mode_looks_at_features_and_never_at_outcomes():
    """Режим распределения не читает ни цен, ни форвардов.

    Порог, поставленный по распределению ПРИЗНАКА, — калибровка, и она
    законна; подгонкой было бы двигать его, увидев доходности. Проверка
    держит именно это: подмени `day_matrices` (цены) на взрыв — режим
    обязан пройти, потому что он туда не ходит.
    """
    root, old = _setup()
    boom = P2.day_matrices

    def explode(*a, **kw):
        raise AssertionError("режим распределения полез за ценами")

    try:
        P2.day_matrices = explode
        rc = S.main(["--stats", "--symbols", ",".join(SYMS)])
        check("режим распределения прошёл", rc == 0, f"код {rc}")
    finally:
        P2.day_matrices = boom
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_narrow_days_and_stale_norms_are_kept_out():
    """Узкие сутки не считаются, а норма — только с КАЛЕНДАРНО вчера.

    Первый живой прогон включил сутки смоука: три имени против семисот,
    и нормы им достались от суток восемнадцатидневной давности. Обе
    дыры невидимы в отчёте — таблица выглядит исправной.
    """
    root, old = _setup()
    keep = _thin_judge()
    try:
        # Узкие сутки — это сутки, у которых сырьё ЕСТЬ по всем
        # именам, а свёрнуто одно: ровно то, что оставляет смоук.
        # Сутки без сырья вовсе узкими не считаются и не должны — там
        # сворачивать нечего (правило `day_gap`).
        later = time.time() + 10 * 86400
        write_ladder_rec(root, SYMS, ["2026-08-22"], hours=(10, 11, 12),
                         per_min=40, seed=77, pull=0.05)
        F.fold_day("2026-08-22", syms=SYMS[:1], jobs=1, store=S.STORE,
                   log=lambda m: None, now=later, kind="ladder")
        said = []
        S.log_, keep_log = said.append, S.log_
        try:
            S.main(["--no-publish", "--tag", "narrow",
                    "--symbols", ",".join(SYMS)])
        finally:
            S.log_ = keep_log
        txt = " ".join(said)
        check("узкие сутки названы и выброшены",
              "узкие сутки в замер не идут" in txt and "2026-08-22" in txt,
              txt[:300])
        got = json.load(open(os.path.join(S.OUT, "z3-narrow.json"),
                             encoding="utf-8"))
        days = [w[0] for w in got["width"]]
        check("узких суток в замере нет", "2026-08-22" not in days,
              str(days))
        # Сутки ПОСЛЕ ПРОПУСКА: сырьё есть, свёрнуто широко, но
        # календарного вчера на складе нет. Норму им дать неоткуда, и
        # проверка требует, чтобы это было сказано про КОНКРЕТНЫЙ день:
        # слово «КАЛЕНДАРНО» само по себе печатается и для первых суток,
        # то есть проверка на одно слово прошла бы на молчащем правиле.
        write_ladder_rec(root, SYMS, ["2026-08-25"], hours=(10, 11, 12),
                         per_min=40, seed=99, pull=0.05)
        F.fold_day("2026-08-25", syms=SYMS, jobs=1, store=S.STORE,
                   log=lambda m: None, now=later, kind="ladder")
        F.fold_day("2026-08-25", syms=SYMS, jobs=1, store=P2.STORE,
                   log=lambda m: None, now=later)
        said2 = []
        S.log_, keep_log = said2.append, S.log_
        try:
            S.main(["--no-publish", "--tag", "gap",
                    "--symbols", ",".join(SYMS)])
        finally:
            S.log_ = keep_log
        gap = [m for m in said2 if "2026-08-25" in m and "КАЛЕНДАРНО" in m]
        check("сутки после пропуска нормы не получают", bool(gap),
              " | ".join(m for m in said2 if "2026-08-25" in m)[:300])
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (
        test_screen_runs_the_whole_road_and_says_it_is_diagnostics,
        test_thin_minutes_are_a_gap_not_an_observation,
        test_one_day_is_refused_because_norms_come_from_yesterday,
        test_horizons_must_match_the_book_screen,
        test_stats_mode_looks_at_features_and_never_at_outcomes,
        test_narrow_days_and_stale_norms_are_kept_out,
    )
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
