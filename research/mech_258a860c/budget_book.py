#!/usr/bin/env python3
"""Механика 258a860c — БЮДЖЕТ МАРЖИ короткой книги h24.

Заявка предлагающего 2026-09-14 (`research/factory/out/proposal.md`):
у короткой книги `h24` объявить бюджет маржи — долю депозита, больше
которой книга не держит в открытых шортах разом, — и выдавать каждой
новой позиции НЕ БОЛЬШЕ БИЛЕТА и НЕ БОЛЬШЕ ПОЛОВИНЫ ОСТАТКА бюджета:

    B       = b × депозит                    b ∈ {0.10, 0.20, 0.30}
    остаток = B − Σ маржи открытых коротких позиций книги (на момент
              решения)
    маржа   = min(билет, остаток / 2)

Ни одна сделка не отбирается: каждое решение листа открывается, меняется
только его маржа. Плечо, пол капитуляции, цель, срок, возраст имени и
охрана рынком — прежние, значит исход позиции В ДОЛЯХ МАРЖИ (`pnl_frac`)
тот же, и меняется только доллар. Единственное место, где в правило
просачивается отбор: позиция, которой бюджет оставляет меньше биржевого
пола билета (`rules.floor_of`), не открывается — число таких печатается
отдельной колонкой.

Ни одно число правила здесь не назначается заново: ось b, ячейка
вердикта (середина оси), доли-убийцы и названные дни объявлены
ЗАДАНИЕМ (`research/factory/out/build_task.md`) и перенесены сюда
именованными постоянными. Порог, назначенный тем же, кто его проверяет,
слабее назначенного независимо.

ГДЕ ЖИВЁТ ПРАВИЛО И ПОЧЕМУ ЗДЕСЬ, А НЕ В КАССЕ. Маржу назначает касса
`run_d6.ration` (её зовёт `run_paper.build_rows`), и бюджету место
именно там — параметром стороны. Дописать его в `run_paper.py` нельзя:
публикация постройки несёт ТОЛЬКО свой каталог (`publish_build.py`), и
правка чужого файла осталась бы на сервере — прогон был, а в ветке
пусто. Поэтому бюджет живёт ОБЁРТКОЙ кассы (`sized`): касса считает
всё сама, обёртка лишь подменяет функцию доли и читает её же список
взятых записей. Второй кассы нет, и это не обещание, а проверка:
`Sizer.finish` сверяет свой счёт эквити с итогом самой кассы и роняет
прогон при расхождении, а `book_form` сверяется с ячейкой семейства
(`short_grid.cell_stats`) на общих полях.

ЧЕГО МЕХАНИКА НЕ УТВЕРЖДАЕТ. Бюджет не меняет знака ни одной сделки и
не ловит хвост имени: шорт в разгоне своего имени остаётся при своём
поле капитуляции и своём билете, худшая ОДНА позиция стоит столько же,
сколько у базы. Он ограничивает, СКОЛЬКО таких сделок книга держит
разом на полном билете.

Порядок печати объявлен заданием и соблюдается прогоном:

    0) калибровочная пара — равномерно уменьшенная база (те же позиции,
       маржа × один множитель) обязана дать укус и доход/просадку базы
       бит в бит, а подсаженный тесный час обязан быть срезан бюджетом;
    1) загрузка базовой книги по дням — средняя, пиковая, распределение;
    2) ячейка вердикта против базы по колонкам убийц;
    3) сетка b и депозит $100k — диагностикой;
    4) контроль перестановкой множителей, SEEDS зёрен.

Запуск (VPS, очередь заданий):

    run research/mech_258a860c/budget_book.py

Смоук: `--seeds 4 --limit 300 --no-publish`.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
for _rel in ("research/dca_paper", "research", "research/a1_universe",
             "research/dca_ladder", "research/s8_loop", "research/s9_sweep",
             "research/factory"):
    _p = os.path.join(ROOT, _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_d6 as D6                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import pool as PL                                             # noqa: E402
import stability as ST                                        # noqa: E402

MECH = "258a860c"
ART = "BUDGET-book"

# --- объявлено ЗАДАНИЕМ, а не этим файлом --------------------------------
BOOK = "safe_h"                     # ячейка вердикта: безопасная короткая
RULER = S.BOOKS[BOOK]               # линейка, на которой считается позиция
DEP = 10000.0                       # депозит вердикта
GRID = (0.10, 0.20, 0.30)           # ось бюджета, объявлена до прогона
VERDICT_B = 0.20                    # середина оси; после просмотра не двигается
# Депозиты замера. $1k исключён заданием: там билет стоит на биржевом
# полу ($25 = `rules.floor_of`), и уменьшить его бюджет не может —
# книга просто перестала бы открывать позиции. Причина названа словами
# и печатается, а не оставлена пропуском.
DEPS = (10000.0, 100000.0)
DEP_SKIP = 1000.0
DEP_SKIP_WHY = ("билет стоит на биржевом полу — бюджет не уменьшает "
                "маржу, а вычёркивает сделки")
# Делитель остатка из формулы заявки: «не больше ПОЛОВИНЫ остатка».
HALF = 2.0
SEEDS = AG.SEEDS                    # 200 зёрен — одно число на весь проект
# Убийца 2: перемешанные множители не хуже бюджета в ≥ 10 % зёрен.
BEAT_MAX = 0.10
# Убийца 3: средняя загрузка базы ≥ 0.20 — ячейка режет каждый день.
LOAD_MAX = 0.20
# Доля «ниже пола билета» от взятых, выше которой правило читается как
# отбор по времени и требует другого контроля (задание, §«чем убивается»).
FLOOR_SHARE_MAX = 0.05
# Худшие дни базы — названы заданием, деньги за них идут отдельной строкой.
NAMED_DAYS = ("2026-09-12", "2026-09-13")
# Множитель равномерной калибровки: любой, лишь бы не единица.
CALIB_MULT = 0.5
# Подсаженный тесный час: сколько позиций и с каким исходом (задание).
PLANT_N = 25
PLANT_PNL = -0.9
HOUR = 3600.0

# Колонки спора. Порядок — порядок показа; `low` значит «меньше лучше».
COLS = (("usd", "$ всего", False),
        ("ratio", "доход/просадка", False),
        ("bite", "укус", True),
        ("usd_wo_top3d", "$ без 3 лучших дней", False),
        ("usd_wo_top", "$ без лучшего имени", False),
        ("max_dd_wo_worst", "просадка без худшего дня", False),
        ("n", "сделок в счёте", False),
        ("taken", "взято кассой", False),
        ("no_cash", "отказов кассы", False),
        ("below_floor", "ниже пола билета", True))


def _quiet(*_a):
    pass


def log_line(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


# --- бюджет: обёртка кассы, а не вторая касса -----------------------------

class Sizer:
    """Читатель решений кассы: сколько книга держит открытыми СЕЙЧАС.

    Список взятых записей — ТОТ ЖЕ объект, который заполняет касса
    (`keep_rows`), а предикат освобождения тот же, что у неё: деньги
    возвращаются в секунду выхода (`int(exit_ts) <= int(at)`), и до
    этой секунды позиция считается открытой. Значит «Σ маржи открытых»
    здесь — не пересчёт кассы, а чтение её собственного состояния.

    Своим остаётся ОДНО: счёт эквити (касса его наружу не отдаёт, а
    доля считается от текущего счёта). Он сверяется с итогом самой
    кассы в `finish`, и расхождение роняет прогон — вторая касса не
    заведётся молча.
    """

    def __init__(self, deposit, rows, base_share, floor):
        self.deposit = float(deposit)
        self.rows = rows                  # тот же список, что у кассы
        self.base_share = base_share
        self.floor = float(floor)
        self.seen = 0
        self.open = []                    # [(exit_ts, маржа, исход)]
        self.equity = float(deposit)
        self.entries = []                 # (at, exit_ts, маржа) всех взятых
        self.mults = []                   # множитель на КАЖДЫЙ вызов доли
        self.calls = 0
        self.below_floor = 0
        self.capped = 0
        self.no_equity = 0
        self.peak_open_usd = 0.0
        self.cap_days = set()
        self.mult_of = {}
        self.taken_usd = 0.0              # Σ маржи взятых, для контроля суммы

    # -- состояние кассы на момент решения --------------------------------

    def sync(self, now):
        """Вобрать новые взятые записи и вернуть деньги вышедших.

        Порядок тот же, что у кассы: сперва освобождение, потом размер.
        Освобождение ленивое — результат от этого не зависит, потому что
        предикат один и тот же и применяется ко всем позициям сразу.
        """
        while self.seen < len(self.rows):
            r, m = self.rows[self.seen]
            self.seen += 1
            self.open.append((float(r["exit_ts"]), float(m), float(r["pnl"])))
            self.entries.append((float(r["at"]), float(r["exit_ts"]),
                                 float(m)))
            self.taken_usd += float(m)
        still = []
        for ts, m, pnl in self.open:
            if int(ts) <= now:
                self.equity += m * pnl
            else:
                still.append((ts, m, pnl))
        self.open = still
        held = sum(m for _t, m, _p in self.open)
        self.peak_open_usd = max(self.peak_open_usd, held)
        return held

    def desk_margin(self, r):
        """Маржа, которую касса назначила бы БЕЗ правила."""
        return self.equity * float(self.base_share(r))

    def record(self, r, mult):
        """Множитель этого решения — и списком (порядок очереди), и картой.

        Список нужен контролю перестановкой: он раздаёт то же
        мультимножество по тому же порядку вызовов. Карта нужна показу и
        проверкам: «какой множитель достался ЭТОМУ решению» из списка не
        вычитать, а вторая копия порядка очереди разошлась бы с первой.
        """
        self.mults.append(float(mult))
        self.mult_of[key_of(r)] = float(mult)
        return mult

    # -- доля счёта: правило подкласса ------------------------------------

    def share(self, r):
        self.calls += 1
        now = int(r["at"])
        held = self.sync(now)
        if self.equity <= 0.0:
            # Счёта нет — размера не существует. Ноль здесь означает
            # «касса откажет как мельче минимума», и это считается
            # числом, а не молчаливым пропуском.
            self.no_equity += 1
            self.record(r, 0.0)
            return 0.0
        return self.decide(r, held)

    def decide(self, r, _held):
        self.record(r, 1.0)
        return float(self.base_share(r))

    def emit(self, r, want):
        """Перевести желаемую маржу в долю счёта, соблюдая пол билета.

        Пол — биржевой (`rules.floor_of`), и он ЕДИНСТВЕННОЕ место, где
        в правило просачивается отбор: позиция, которой остаётся меньше
        пола, не открывается вовсе. Число таких печатается колонкой.
        """
        base = float(self.base_share(r))
        m0 = self.desk_margin(r)
        if want >= m0 - 1e-12:
            self.record(r, 1.0)
            return base
        if want < self.floor:
            self.below_floor += 1
            self.record(r, 0.0)
            return 0.0
        self.capped += 1
        self.cap_days.add(time.strftime("%Y-%m-%d",
                                        time.gmtime(float(r["at"]))))
        self.record(r, want / m0 if m0 > 0 else 0.0)
        return want / self.equity

    # -- сверка с самой кассой --------------------------------------------

    def finish(self, c):
        """Свой счёт эквити против итога кассы. Расхождение — отказ.

        Касса считает итог по ВСЕМ взятым позициям (хвост закрывается в
        конце), и тот же итог обязан получиться из её же списка взятых.
        Разница больше единицы последнего знака означает, что счёт здесь
        и счёт кассы разошлись, — и считать дальше нельзя: числа были бы
        не про ту книгу.
        """
        self.sync(2 ** 62)
        mine = round(self.equity / self.deposit - 1.0, 4)
        theirs = c.get("final")
        self.final_mine, self.final_desk = mine, theirs
        if theirs is not None and abs(mine - float(theirs)) > 1e-4:
            raise AssertionError(
                f"счёт обёртки разошёлся с кассой: {mine} против {theirs} "
                f"на депозите {self.deposit:g} — вторая касса заведена")
        return c


class Budget(Sizer):
    """Правило заявки: маржа = min(билет, остаток / 2)."""

    def __init__(self, b, deposit, rows, base_share, floor, half=HALF):
        super().__init__(deposit, rows, base_share, floor)
        self.b = float(b)
        self.B = float(b) * float(deposit)
        self.half = float(half)

    def decide(self, r, held):
        rest = self.B - held
        return self.emit(r, rest / self.half)


class Uniform(Sizer):
    """Калибровка: ТЕ ЖЕ позиции с маржой, умноженной на один множитель.

    Множитель ровно один на всю книгу, поэтому все деньги книги
    масштабируются им же, а укус — отношение денег к деньгам — обязан
    остаться тем же. Позиция, которой касса базы не дала денег, не
    открывается и здесь — иначе состав книги изменился бы, и калибровка
    сравнивала бы разные книги (см. `calib_uniform` о том, почему
    доход на просадку безразмерен НЕ вполне).

    Именно здесь и проверяется счёт эквити обёртки: маржа задаётся в
    ДОЛЛАРАХ и переводится в долю делением на него. Ошибись он — маржа
    перестала бы быть ровно `mult` × базовой, и равенство упало бы.
    """

    def __init__(self, mult, base_margin, deposit, rows, base_share, floor):
        super().__init__(deposit, rows, base_share, floor)
        self.mult = float(mult)
        self.base_margin = base_margin

    def decide(self, r, _held):
        m = self.base_margin.get(key_of(r))
        if m is None:
            self.record(r, 0.0)
            return 0.0
        want = self.mult * float(m)
        self.record(r, self.mult)
        return want / self.equity


class Shuffle(Sizer):
    """Контроль: те же множители, розданные позициям случайно.

    Множители берутся у бюджета КАК ЕСТЬ (их мультимножество, включая
    нули отказов по полу) и переставляются между всеми вызовами доли.
    Порядок вызовов задаёт очередь кассы (`run_d6.queue`) и от размеров
    не зависит, поэтому i-й вызов здесь и i-й вызов у бюджета — одно и
    то же решение.
    """

    def __init__(self, mults, deposit, rows, base_share, floor):
        super().__init__(deposit, rows, base_share, floor)
        self.plan = list(mults)

    def decide(self, r, _held):
        i = self.calls - 1
        m = self.plan[i] if i < len(self.plan) else 1.0
        if m >= 1.0:
            self.record(r, 1.0)
            return float(self.base_share(r))
        return self.emit(r, m * self.equity * float(self.base_share(r)))


def key_of(r):
    """Ключ решения: имя и секунда. Тот же, что у кэша реплея."""
    return (str(r["sym"]), round(float(r["at"]), 3))


class sized:
    """Касса с размером от правила — на время одного вызова, и обратно.

    Подменяется ОДНА функция (`run_d6.ration`), и подменённая зовёт
    настоящую: считает по-прежнему касса, обёртка лишь даёт ей другую
    функцию доли и читает её же список взятых. Оставленная глобально
    подмена сделала бы соседний расчёт другим расчётом молча — поэтому
    восстановление стоит в `finally`, как у `run_d11.configure`.
    """

    def __init__(self, make):
        self.make = make
        self.sizers = {}
        self._real = None

    def __enter__(self):
        self._real = D6.ration
        real = self._real

        def wrapped(recs, share, deposit=D6.DEPOSIT,
                    min_notional=D6.MIN_NOTIONAL, keep_rows=False):
            rows = [] if keep_rows is False else keep_rows
            sz = self.make(float(deposit), rows, share)
            if sz is None:
                return real(recs, share, deposit=deposit,
                            min_notional=min_notional, keep_rows=keep_rows)
            self.sizers[float(deposit)] = sz
            c = real(recs, sz.share, deposit=deposit,
                     min_notional=min_notional, keep_rows=rows)
            sz.finish(c)
            c = dict(c, below_floor=sz.below_floor, capped=sz.capped,
                     no_equity=sz.no_equity,
                     margin_usd=round(sz.taken_usd, 2),
                     peak_open_usd=round(sz.peak_open_usd, 2))
            return c

        D6.ration = wrapped
        return self

    def __exit__(self, *_a):
        D6.ration = self._real
        return False


def budget_maker(b, book=BOOK, half=HALF):
    """Бюджет как свойство СТОРОНЫ: пол билета берётся у книги."""
    def make(deposit, rows, share):
        return Budget(b, deposit, rows, share, R.floor_of(book), half=half)
    return make


def plain_maker(book=BOOK):
    """Обёртка без правила: та же книга, только с измерением загрузки."""
    def make(deposit, rows, share):
        return Sizer(deposit, rows, share, R.floor_of(book))
    return make


# --- книга: те же функции и тот же порядок, что у семейства ---------------

def book_form(cache, ctx, launch, dep=DEP, book=BOOK, maker=None, now=None,
              log=_quiet, mkt=None, deps=None):
    """Форма книги на этих записях — ТЕМИ ЖЕ функциями, что касса.

    Порядок правил тот же, что у `short_grid.cell_stats`: возраст имени
    → охрана рынком → касса → издержки → статистика. Зачем не сама
    `cell_stats`: её ячейка не отдаёт колонок концентрации («без трёх
    лучших дней», «без лучшего имени», «просадка без худшего дня»), а
    спор заявки идёт ровно о них; дописать поля в `short_grid.py`
    нельзя — правка чужого файла не публикуется. Равенство ячейке
    семейства на ОБЩИХ полях проверяется отдельно (`agrees_with_cell`).

    Возвращает (статистика, ячейка кассы, размерщик) либо None.
    """
    packed = AG.packed_short(cache)
    recs, _ages = RP.age_shorts(packed.get(book) or [], book, launch=launch,
                                log=log, now=now)
    recs, _g = RP.guard_shorts(recs, book, log=log, now=now, mkt=mkt)
    with sized(maker or (lambda *_a: None)) as sz:
        rows, cells, _one, _live = RP.build_rows({book: recs}, now=now,
                                                 keys=[book], log=log)
    mine = [r for r in rows if R.ruler_of(r) == book
            and int(r.get("dep", 0)) == int(dep)]
    if ctx is not None and not ctx.get("error"):
        mine, _c = CO.apply_to_rows(mine, ctx)
    st = RP._stats(mine, dep)
    c = cells.get(RP._cell(book, dep)) or {}
    return st, c, sz.sizers.get(float(dep))


def agrees_with_cell(cache, ctx, launch, dep=DEP, book=BOOK, now=None,
                     log=_quiet):
    """Сверка с ячейкой семейства: те же деньги теми же правилами.

    Числом, а не утверждением: расхождение означает, что здесь заведена
    вторая касса, и оно едет в отчёт.
    """
    st, c, _sz = book_form(cache, ctx, launch, dep=dep, book=book, now=now,
                           log=log)
    cell = G.cell_stats(AG.packed_short(cache), ctx, launch, now=now, log=log,
                        keys=[book], deps=[dep]).get(f"{book}:{int(dep)}") or {}
    got = {}
    for f in ("n", "usd", "final", "max_dd", "day_median", "win"):
        a, b = (st or {}).get(f), cell.get(f)
        got[f] = {"форма": a, "ячейка": b,
                  "равно": (a is None and b is None)
                           or (a is not None and b is not None
                               and abs(float(a) - float(b)) <= 1e-9)}
    got["taken"] = {"форма": c.get("taken"), "ячейка": cell.get("taken"),
                    "равно": c.get("taken") == cell.get("taken")}
    got["все_равны"] = all(v["равно"] for v in got.values()
                           if isinstance(v, dict))
    return got


def load_of(sizer, deposit, hour=HOUR):
    """Загрузка книги: доля депозита в марже открытых позиций по ЧАСАМ.

    Считается по взятым записям самой кассы (момент решения, момент
    выхода, маржа) — этого числа у коротких книг не напечатано нигде,
    и заявка требует его первым. Часы без единой открытой позиции в
    ряд ВХОДЯТ нулём: книга в такой час действительно держала ноль, и
    выбросив их, мы завысили бы среднюю загрузку.
    """
    if sizer is None or not sizer.entries:
        return None
    a0 = min(int(a // hour) for a, _b, _m in sizer.entries)
    a1 = max(int(b // hour) for _a, b, _m in sizer.entries)
    n = int(a1 - a0) + 1
    if n <= 0:
        return None
    held = np.zeros(n, dtype=float)
    cnt = np.zeros(n, dtype=float)
    for at, out_ts, m in sizer.entries:
        i = int(at // hour) - a0
        j = int(out_ts // hour) - a0
        held[i:j + 1] += float(m)
        cnt[i:j + 1] += 1.0
    return {"hours": n,
            "mean": round(float(held.mean()) / float(deposit), 4),
            "median": round(float(np.median(held)) / float(deposit), 4),
            "peak": round(float(held.max()) / float(deposit), 4),
            "peak_usd": round(float(held.max()), 2),
            "open_mean": round(float(cnt.mean()), 1),
            "open_peak": int(cnt.max()),
            "positions": len(sizer.entries),
            "margin_usd": round(sizer.taken_usd, 2)}


def columns(st, cell=None, sizer=None, named=NAMED_DAYS):
    """Колонки спора. Чего нет — прочерк, а не ноль.

    Все величины считает `run_paper._stats` (там же, где деньги книги),
    а укус и медиану дня — `stability.stats` по её же суточной разбивке:
    своей копии дней здесь нет, и правило вылета пула судит тем же
    укусом, каким печатает отчёт.
    """
    if not st:
        return None
    days = {str(r["d"]): float(r.get("usd") or 0.0)
            for r in (st.get("days_rows") or [])}
    ns = {str(r["d"]): int(r.get("n") or 0)
          for r in (st.get("days_rows") or [])}
    shape = ST.stats(days) or {}
    fin, dd = st.get("final"), st.get("max_dd")
    out = {k: st.get(k) for k in ("usd", "final", "max_dd", "n", "days",
                                  "day_median", "win", "usd_wo_top",
                                  "usd_wo_top3d", "max_dd_wo_worst",
                                  "top_sym", "top_day", "worst_day")}
    out["ratio"] = (None if not fin or not dd
                    else round(float(fin) / abs(float(dd)), 2))
    # Укус — у `stability`, а не у `_stats`: мера одна на проект, и
    # правило вылета пула судит именно ею.
    out["bite"] = shape.get("bite")
    out["shape"] = shape or None
    out["taken"] = (cell or {}).get("taken")
    out["no_cash"] = (cell or {}).get("no_cash")
    out["too_small"] = (cell or {}).get("too_small")
    out["below_floor"] = None if sizer is None else int(sizer.below_floor)
    out["capped"] = None if sizer is None else int(sizer.capped)
    out["cap_days"] = None if sizer is None else len(sizer.cap_days)
    out["margin_usd"] = None if sizer is None else round(sizer.taken_usd, 2)
    # Доля «ниже пола» от взятых: выше неё правило читается как отбор.
    tk = out.get("taken")
    out["floor_share"] = (None if not tk or out["below_floor"] is None
                          else round(out["below_floor"] / float(tk), 4))
    # Деньги названных дней: дня в своде нет — прочерк с причиной.
    out["named"] = {d: {"usd": days.get(d), "n": ns.get(d),
                        "why": (None if d in days
                                else "дня нет в суточном своде книги")}
                    for d in named}
    out["daily_no"] = {PL.day_no(_ts_of(d)): round(v, 4)
                       for d, v in days.items()}
    # Укус меры и укус кассы обязаны совпадать: две формулы одного числа
    # в этом проекте уже расходились, и это проверяется, а не обещается.
    out["bite_stats"] = st.get("bite")
    return out


def _ts_of(day):
    import calendar
    return float(calendar.timegm(time.strptime(str(day), "%Y-%m-%d")))


# --- калибровочная пара ---------------------------------------------------

def base_margins(sizer):
    """Маржа базы по решениям: {(имя, момент): маржа}."""
    return {} if sizer is None else {
        (str(r["sym"]), round(float(r["at"]), 3)): float(m)
        for r, m in sizer.rows}


def calib_uniform(cache, ctx, launch, base_cols, base_sizer, mult=CALIB_MULT,
                  dep=DEP, book=BOOK, now=None, mkt=None, log=_quiet):
    """Нога «молчать на шуме»: равномерное уменьшение не меняет формы.

    Утверждение заявки: укус и доход на просадку БЕЗРАЗМЕРНЫ, и
    равномерное уменьшение всех позиций их не двигает; значит любая
    разница у книги с бюджетом — от НЕРАВНОМЕРНОСТИ, а не от того, что
    денег стало меньше.

    ИЗМЕРЕНО, что это верно НЕ ДЛЯ ОБЕИХ величин, и молчать об этом
    нельзя. Укус безразмерен точно: деньги дня делятся на деньги дня.
    Доход на просадку — НЕТ: просадка считается к пиковому СЧЁТУ
    (`run_paper._dd`: `min(eq / cummax(eq) − 1)`, eq = депозит +
    накопленное), а депозит при уменьшении маржи остаётся прежним —
    книга с меньшей прибылью имеет меньший пик, и та же по деньгам
    просадка выходит ГЛУБЖЕ долей. Поэтому равномерное уменьшение
    занижает доход на просадку, и величина смещения печатается числом
    (`ratio_bias`). Знак смещения работает ПРОТИВ заявки: книга с
    бюджетом мельче базы, и её доход на просадку занижен тем же
    механизмом — убийца 1 от этого строже, а не мягче.

    Пропуском считается совпадение состава, равенство укуса на литерал и
    уменьшение денег ровно во столько раз, во сколько уменьшена маржа
    (с точностью до округления строк журнала до сотой цента).
    """
    marg = base_margins(base_sizer)

    def make(deposit, rows, share):
        return Uniform(mult, marg, deposit, rows, share, R.floor_of(book))

    st, c, sz = book_form(cache, ctx, launch, dep=dep, book=book, maker=make,
                          now=now, mkt=mkt, log=log)
    cols = columns(st, c, sz)
    if not cols:
        return {"why": "равномерная сестра не дала ни одной сделки"}
    same_n = (cols.get("n") == base_cols.get("n")
              and cols.get("taken") == base_cols.get("taken"))
    scale = (None if not base_cols.get("usd")
             else round(float(cols["usd"]) / float(base_cols["usd"]), 6))
    ok_bite = cols.get("bite") == base_cols.get("bite")
    ok_scale = scale is not None and abs(scale - mult) < 1e-4
    ok = bool(same_n and ok_bite and ok_scale)
    br, cr = base_cols.get("ratio"), cols.get("ratio")
    bias = (None if br is None or cr is None
            else round(float(cr) - float(br), 3))
    return {"mult": float(mult), "same_n": bool(same_n), "scale": scale,
            "bite": cols.get("bite"), "base_bite": base_cols.get("bite"),
            "ratio": cr, "base_ratio": br, "ratio_bias": bias,
            "n": cols.get("n"), "base_n": base_cols.get("n"),
            "taken": cols.get("taken"), "base_taken": base_cols.get("taken"),
            "usd": cols.get("usd"), "base_usd": base_cols.get("usd"),
            "pass": ok,
            "why": (f"укус не шелохнулся ({cols.get('bite')}), деньги "
                    f"уменьшились ровно в {1.0 / mult:g} раза (масштаб "
                    f"{scale}); доход на просадку сместился на {bias} "
                    f"({br} → {cr}) — просадка считается к пиковому счёту, "
                    "и это смещение работает против заявки"
                    if ok else
                    "равномерное уменьшение изменило то, что обязано было "
                    f"остаться: состав тот же — {same_n}, укус "
                    f"{cols.get('bite')} против {base_cols.get('bite')}, "
                    f"масштаб денег {scale} против {mult}")}


class NoMarket:
    """Рынок, которого в калибровке нет: охрана не срабатывает ни разу.

    Подставной рынок назван, а не подразумевается: калибровка мерит
    КАССУ, и правило выхода, сработавшее посреди подсаженного часа,
    сделало бы литеральное равенство недостижимым по чужой причине.
    """

    def __init__(self):
        self.wave_none = 0

    def k_star(self, _at, _pct, _last):
        self.wave_none += 1
        return None, 1


def planted(cache, b=VERDICT_B, dep=DEP, n=PLANT_N, pnl=PLANT_PNL,
            ruler=RULER):
    """Копия данных с подсаженным ТЕСНЫМ ЧАСОМ: n позиций разом.

    Записи не выдуманы: берутся живые записи кэша (их поля, плечо,
    отметки, входы), у них меняются момент решения (общий час), исход
    (`pnl`) и время выхода. Имена РАЗНЫЕ — иначе правило «одна позиция
    на имя» оставило бы от подсадки одну.

    Отметки пересчитываются так, чтобы их сумма равнялась исходу, а
    число их равнялось числу ЧАСОВ ЖИЗНИ позиции: запись, у которой
    отметки не сходятся с исходом или торчат за срок, живой не бывает —
    касса на такой падает с `KeyError`, а правило охраны читает её
    иначе. Дрожание оставлено живое (первые часы взяты у самой записи),
    выравнивается последний час.
    """
    src = sorted((k for k in cache if k[0] == ruler
                  and (cache[k].get("state") or "closed") == "closed"),
                 key=lambda k: (k[1], k[2]))
    seen, pick = set(), []
    for k in src:
        if k[1] in seen:
            continue
        seen.add(k[1])
        pick.append(k)
        if len(pick) >= n:
            break
    if len(pick) < n:
        return None, {"why": f"имён в кэше {len(pick)} при нужных {n}"}
    at = float(max(cache[k]["at"] for k in pick))
    at = float(int(at // HOUR) * HOUR) + HOUR
    out_ts = at + R.H24_HOLD_H * HOUR - 1.0
    n_h = int((out_ts - at) // HOUR) + 1
    out = {}
    for k in pick:
        r = dict(cache[k])
        mk = [float(x[1]) for x in (r.get("marks") or [])][:n_h]
        mk += [0.0] * (n_h - len(mk))
        mk[-1] = float(pnl) - sum(mk[:-1])
        r["marks"] = [[at + i * HOUR, float(x)] for i, x in enumerate(mk)]
        r["at"] = at
        r["pnl"] = float(pnl)
        r["pnl_net"] = float(pnl)
        r["exit_ts"] = at + R.H24_HOLD_H * HOUR - 1.0
        r["sched_end"] = at + R.H24_HOLD_H * HOUR
        r["end_ts"] = r["exit_ts"]
        r["state"] = "closed"
        r["exit"] = "срок"
        out[(ruler, k[1], round(at, 3))] = r
    return out, {"at": at, "n": len(out), "B": float(b) * float(dep)}


def calib_planted(cache, dep=DEP, b=VERDICT_B, book=BOOK, now=None,
                  log=_quiet):
    """Нога «найти подсаженное»: тесный час обязан быть срезан бюджетом.

    Подсаженный час — `PLANT_N` позиций одной секунды с исходом
    `PLANT_PNL`. База открывает их все полным билетом и теряет
    `PLANT_N × |PLANT_PNL| × билет`; книга с бюджетом держит в них не
    больше `B`, значит теряет не больше `|PLANT_PNL| × B`. Обе величины
    печатаются, и граница проверяется литералом.

    Считается БРУТТО (издержки выключены названо): калибровка мерит
    КАССУ, а издержки добавляются поверх исхода и сделали бы литеральное
    равенство «деньги = исход × маржа» недостижимым по чужой причине.
    Издержки проверяет вторая нога пары, она идёт нетто.

    Возраст имени подставной: имена настоящие, а момент решения
    сдвинут — справочник запусков здесь мерит не то, о чём калибровка.
    """
    ctx = {"error": "калибровка кассы идёт брутто: издержки выключены"}
    cut, meta = planted(cache, b=b, dep=dep)
    if cut is None:
        return dict(meta, **{"pass": None})
    lau = {k[1]: float(meta["at"]) - 400.0 * 86400.0 for k in cut}
    at = float(meta["at"])
    ticket = R.ticket(dep, book)
    mkt = NoMarket()
    st0, c0, sz0 = book_form(cut, ctx, lau, dep=dep, book=book,
                             maker=plain_maker(book), now=now, mkt=mkt,
                             log=log)
    st1, c1, sz1 = book_form(cut, ctx, lau, dep=dep, book=book,
                             maker=budget_maker(b, book), now=now, mkt=mkt,
                             log=log)
    B = float(b) * float(dep)
    lim = abs(float(PLANT_PNL)) * B
    base_usd = (st0 or {}).get("usd")
    got_usd = (st1 or {}).get("usd")
    held0 = None if sz0 is None else round(sz0.taken_usd, 2)
    held1 = None if sz1 is None else round(sz1.taken_usd, 2)
    # Брутто деньги позиции есть исход × маржа, поэтому у подсаженного
    # часа они обязаны РАВНЯТЬСЯ `PLANT_PNL × Σ маржи` — это и проверяется
    # литералом, а не «примерно столько».
    exact = (None if got_usd is None or held1 is None
             else round(float(got_usd) - float(PLANT_PNL) * float(held1), 2))
    ok = (got_usd is not None and held1 is not None
          and held1 <= B + 1e-6 and abs(float(got_usd)) <= lim + 1e-6
          and exact is not None and abs(exact) <= 0.01
          and base_usd is not None and abs(float(base_usd)) > lim)
    return {"at": at, "n": meta["n"], "B": B, "limit": round(lim, 2),
            "ticket": ticket, "base_usd": base_usd, "usd": got_usd,
            "base_margin_usd": held0, "margin_usd": held1, "exact": exact,
            "below_floor": None if sz1 is None else sz1.below_floor,
            "taken": c1.get("taken"), "base_taken": c0.get("taken"),
            "pass": bool(ok),
            "why": (f"тесный час: база держит {held0} $ маржи и теряет "
                    f"{base_usd} $, бюджет держит {held1} $ (предел {B:g}) "
                    f"и теряет {got_usd} $ (предел {lim:g}); деньги равны "
                    f"исходу × маржу с точностью {exact} $"
                    if ok else
                    f"подсадка не срезана: маржа {held1} при пределе {B:g}, "
                    f"деньги {got_usd} при пределе {lim:g} (исход × маржа "
                    f"расходится на {exact} $), база {base_usd}")}


# --- контроль перестановкой ----------------------------------------------

def shuffle_cell(cache, ctx, launch, mults, seed, dep=DEP, book=BOOK,
                 now=None, mkt=None, log=_quiet):
    """Одно зерно контроля: те же множители, розданные случайно."""
    rnd = random.Random(1000 + int(seed))
    plan = list(mults)
    rnd.shuffle(plan)

    def make(deposit, rows, share):
        return Shuffle(plan, deposit, rows, share, R.floor_of(book))

    st, c, sz = book_form(cache, ctx, launch, dep=dep, book=book, maker=make,
                          now=now, mkt=mkt, log=log)
    return columns(st, c, sz)


def sample_cell(cache, ctx, launch, pool, n_keep, seed, dep=DEP, book=BOOK,
                now=None, mkt=None, log=_quiet):
    """Одно зерно контроля выборкой: `n_keep` решений базы наугад.

    Выбирается РЕШЕНИЕ, а не запись, и правило выборки — то же, что у
    `agree_book.control` (то же зерно, тот же `random.sample`, тот же
    срез кэша `agree_book.keep`): второй копии розыгрыша быть не
    должно, иначе контроль мерил бы не тот случай, о котором спор.

    Книга считается ПОЛНЫМ билетом: спор идёт о том, лучше ли бюджет
    случайного сокращения ЧИСЛА сделок того же размера.
    """
    rnd = random.Random(1000 + int(seed))
    want = set(rnd.sample(sorted(pool), int(n_keep)))
    st, c, sz = book_form(AG.keep(cache, want), ctx, launch, dep=dep,
                          book=book, maker=plain_maker(book), now=now,
                          mkt=mkt, log=log)
    return columns(st, c, sz)


def control_kind(floor_share, limit=FLOOR_SHARE_MAX):
    """Какой контроль обязан считаться — решает ЧИСЛО, а не автор.

    Заданием объявлено: доля решений, вычеркнутых полом билета, выше
    `limit` от взятых — правило читается как ОТБОР по времени, и
    контролем ему служит случайная выборка того же размера, а не
    перестановка множителей. Ниже предела вычеркнутых почти нет,
    правило есть чистое уменьшение размера, и спор идёт о раскладке.
    """
    if floor_share is None:
        return "perm", ("доля «ниже пола билета» не измерена — контролем "
                        "берётся перестановка множителей")
    if float(floor_share) > float(limit):
        return "sample", (f"полом билета вычеркнуто {100 * float(floor_share):.1f} % "
                          f"взятых при пределе {100 * float(limit):.0f} % — "
                          "правило читается как отбор, и контролем служит "
                          "случайная выборка того же размера")
    return "perm", (f"полом билета вычеркнуто {100 * float(floor_share):.1f} % "
                    f"взятых при пределе {100 * float(limit):.0f} % — отбора "
                    "нет, контролем служит перестановка множителей")


def control(cache, ctx, launch, mults, seeds=SEEDS, dep=DEP, book=BOOK,
            now=None, mkt=None, log=_quiet, say=_quiet, kind="perm",
            pool=None, n_keep=None):
    """Контроль на `seeds` зёрнах — тем розыгрышем, который выбрало число.

    Спор идёт о безразмерных колонках, поэтому доля зёрен считается по
    ним же. Укус — колонка, где МЕНЬШЕ лучше, и одна мера доли на весь
    проект (`agree_book.beat_share`) считает «не хуже» как «не меньше»;
    поэтому укус едет в неё со знаком минус, а не своей копией правила.
    """
    draws, t0 = [], time.time()
    for i in range(int(seeds)):
        if kind == "sample":
            d = sample_cell(cache, ctx, launch, pool, n_keep, i, dep=dep,
                            book=book, now=now, mkt=mkt, log=log)
        else:
            d = shuffle_cell(cache, ctx, launch, mults, i, dep=dep, book=book,
                             now=now, mkt=mkt, log=log)
        if d is not None:
            d["bite_neg"] = (None if d.get("bite") is None
                             else -float(d["bite"]))
        draws.append(d)
        if i and i % 25 == 0:
            say(f"    контроль: {i} зёрен из {seeds}, "
                f"{time.time() - t0:.0f} с")
    return {"draws": draws, "n": len(draws), "seeds": int(seeds),
            "kind": kind, "n_keep": (None if n_keep is None else int(n_keep)),
            "pool": (None if pool is None else len(pool)),
            "secs": round(time.time() - t0, 1)}


def taken_keys(sizer):
    """Решения, которые касса ВЗЯЛА: (имя, момент, сторона).

    Ключ тот же, каким режет кэш `agree_book.keep`, — иначе выборка
    отдавала бы пустую книгу, ничем себя не выдав.
    """
    if sizer is None:
        return set()
    return {(str(r["sym"]), round(float(r["at"]), 3),
             r.get("side") or "short") for r, _m in sizer.rows}


def beat(draws, value, field):
    """Доля зёрен, где случайная раскладка НЕ ХУЖЕ — мерой проекта."""
    return AG.beat_share([d for d in (draws or []) if d], value, field)


def _med(xs):
    xs = [float(x) for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


# --- убийцы: фраза выводится из числа ------------------------------------

def killer_one(base, cell):
    """Потолок на записи: ячейка вердикта против базы на тех же сутках.

    Мертво, если выполнено хотя бы одно: доход на просадку не выше
    базового; укус не ниже базового; «$ без трёх лучших дней» ≤ 0.
    """
    if not cell:
        return None, "не измерено: ячейки вердикта нет", {}
    got = {f: {"база": base.get(f), "бюджет": cell.get(f)}
           for f in ("ratio", "bite", "usd_wo_top3d", "usd")}
    br, cr = base.get("ratio"), cell.get("ratio")
    bb, cb = base.get("bite"), cell.get("bite")
    w3 = cell.get("usd_wo_top3d")
    if br is None or cr is None:
        return None, ("не измерено: доход на просадку есть не у обеих книг "
                      f"(база {br}, бюджет {cr})"), got
    if float(cr) <= float(br):
        return False, (f"доход на просадку {cr:.2f} не выше базового "
                       f"{br:.2f}"), got
    if bb is None or cb is None:
        return None, (f"не измерено: укус есть не у обеих книг (база {bb}, "
                      f"бюджет {cb})"), got
    if float(cb) >= float(bb):
        return False, (f"укус {cb:g} не ниже базового {bb:g} — худший день "
                       "съедает столько же обычных"), got
    if w3 is None:
        return None, ("не измерено: «без трёх лучших дней» не считается — "
                      "суток меньше четырёх"), got
    if float(w3) <= 0:
        return False, (f"без трёх лучших дней остаётся {w3:+.2f} $ — деньги "
                       "книги суть те же эпизоды"), got
    return True, (f"доход на просадку {br:.2f} → {cr:.2f}, укус {bb:g} → "
                  f"{cb:g}, без трёх лучших дней {w3:+.2f} $"), got


def killer_two(cell, ctl, beat_max=BEAT_MAX):
    """Контроль: выигрыш от ЗАНЯТОСТИ книги или от случайности.

    Розыгрыш выбирает число (`control_kind`), а порог один: не хуже в
    `beat_max` зёрен — правило мертво. Название розыгрыша едет во фразу,
    чтобы вердикт нельзя было прочитать не про тот контроль.
    """
    if not ctl or not ctl.get("draws"):
        return None, "не измерено: контроль не считался (зёрен нет)", {}
    draws = ctl["draws"]
    ttl = ("случайная выборка того же размера"
           if ctl.get("kind") == "sample" else "перемешанные множители")
    sh_b, n_b = beat(draws, (None if cell.get("bite") is None
                             else -float(cell["bite"])), "bite_neg")
    sh_r, n_r = beat(draws, cell.get("ratio"), "ratio")
    got = {"bite": {"share": sh_b, "n": n_b,
                    "med": _med([(d or {}).get("bite") for d in draws])},
           "ratio": {"share": sh_r, "n": n_r,
                     "med": _med([(d or {}).get("ratio") for d in draws])}}
    if sh_b is None:
        return None, "не измерено: укус не посчитан ни у одного зерна", got
    if float(sh_b) >= beat_max:
        return False, (f"{ttl}: не хуже по укусу в "
                       f"{100 * float(sh_b):.0f} % зёрен при пределе "
                       f"{100 * beat_max:.0f} % — выигрыш даёт случайность, "
                       "а не занятость книги"), got
    return True, (f"{ttl}: не хуже по укусу в "
                  f"{100 * float(sh_b):.0f} % зёрен (предел "
                  f"{100 * beat_max:.0f} %), по доходу на просадку в "
                  + ("—" if sh_r is None else f"{100 * float(sh_r):.0f}")
                  + " %"), got


def killer_three(load, cell, load_max=LOAD_MAX, b=VERDICT_B):
    """Загрузка: режет ли ячейка каждый день.

    Если средняя доля депозита в марже у БАЗЫ не ниже бюджета, правило
    связывает всегда, и это уже не «размер от занятости», а простое
    уменьшение плеча книги: тогда читаются только безразмерные колонки.
    """
    if not load:
        return None, "не измерено: загрузка базы не посчитана", {}
    m, p = load.get("mean"), load.get("peak")
    got = {"mean": m, "peak": p, "b": float(b),
           "cap_days": (cell or {}).get("cap_days"),
           "capped": (cell or {}).get("capped")}
    if m is None:
        return None, "не измерено: средней загрузки нет", got
    if float(m) >= min(float(load_max), float(b)):
        return False, (f"средняя загрузка базы {100 * float(m):.1f} % не ниже "
                       f"бюджета {100 * float(b):.0f} % — ячейка режет "
                       "каждый день, и это уменьшение плеча книги, а не "
                       "размер от занятости"), got
    return True, (f"средняя загрузка базы {100 * float(m):.1f} % при пике "
                  f"{100 * float(p or 0):.1f} % и бюджете "
                  f"{100 * float(b):.0f} %: правило связывает "
                  + (f"{got['cap_days']} суток" if got.get("cap_days")
                     is not None else "не каждый день")), got


def killer_four(cell, declared_at=None):
    """Форвард: правило вылета пула по ряду суток — с пометкой, чем судится.

    Форвардных суток у необъявленной сестры НОЛЬ, поэтому здесь судится
    ПЕРЕСЧЁТ, и вердиктом это не является. Дорога вперёд — решение
    владельца (та же просьба, что открыта 13.09).
    """
    daily = {int(k): float(v) for k, v in (cell or {}).get("daily_no",
                                                           {}).items()}
    if not daily:
        return None, "не измерено: суточного ряда нет", {}
    s = ST.stats(daily) or {}
    fwd, _pre = PL.split_forward(daily, declared_at)
    got = {"days": s.get("days"), "med": s.get("med"), "bite": s.get("bite"),
           "green": s.get("green"), "thin": s.get("thin"),
           "shape_why": PL.shape_why(daily, declared_at),
           "forward_days": (len(fwd) if declared_at else 0)}
    # Молчание правила вылета значит РАЗНОЕ, и разница лечится разным:
    # суток меньше порога — вердикта нет вовсе; суток хватает — форма
    # правилу не противоречит. Печатать в обоих случаях «None» значило
    # бы выдать «не измерено» за «прошло».
    said = (got["shape_why"] or
            (f"суток {got['days']} при пороге {ST.MIN_DAYS} — вердикта нет"
             if s.get("thin") else "по форме не отставлен"))
    return None, ("судится ПЕРЕСЧЁТ, а не форвард: форвардных суток "
                  f"{got['forward_days']}; правило вылета пула на ряду "
                  f"говорит «{said}»"), got


# --- прогон ---------------------------------------------------------------

def bite_table(packed, ctx, launch, dep=DEP, now=None, log=_quiet):
    """Укус коротких книг — число, которого нет нигде, и печатается оно ПЕРВЫМ.

    Правило вылета кандидатов судит именно укусом, а у семейства `h24`
    он не напечатан ни в одном отчёте. Считается мерой проекта
    (`stability.stats`) по суточной разбивке ячейки семейства.
    """
    cells = G.cell_stats(packed, ctx, launch, now=now, log=log,
                         keys=list(R.H24_ORDER), deps=[dep])
    out = []
    for bk in R.H24_ORDER:
        c = cells.get(f"{bk}:{int(dep)}") or {}
        days = {str(r["d"]): float(r.get("usd") or 0.0)
                for r in (c.get("days") or [])}
        s = ST.stats(days)
        fin, dd = c.get("final"), c.get("max_dd")
        out.append({"book": bk, "n": c.get("n"), "usd": c.get("usd"),
                    "final": fin, "max_dd": dd,
                    "ratio": (None if not fin or not dd
                              else round(float(fin) / abs(float(dd)), 2)),
                    "bite": (s or {}).get("bite"),
                    "med": (s or {}).get("med"),
                    "green": (s or {}).get("green"),
                    "days": (s or {}).get("days"),
                    "thin": (s or {}).get("thin")})
    return out


def run(seeds=SEEDS, limit=None, grid=GRID, b_verdict=VERDICT_B, dep=DEP,
        book=BOOK, now=None, launch=None, ctx=None, cache=None,
        log=log_line, mem_limit=None, deps=DEPS):
    t0 = time.time()
    say = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    if cache is None:
        cache, why = S.read_cache(log=say)
        if why:
            say(f"механика не считается: {why}")
            return {"error": f"кэш реплея непригоден: {why}", "mech": MECH}
    closed = {k: r for k, r in cache.items()
              if k[0] == RULER and (r.get("state") or "closed") == "closed"}
    if limit:
        keep = sorted(closed, key=lambda k: k[2])[:int(limit)]
        closed = {k: closed[k] for k in keep}
        cache = {k: v for k, v in cache.items()
                 if k[0] != RULER or k in closed}
    # Ноль наблюдений при непустом входе — отказ, а не отчёт с
    # прочерками: пустота не вправе выдавать себя за результат.
    if not closed:
        return {"error": f"закрытых позиций линейки {RULER} в кэше нет: "
                         "считать нечего", "mech": MECH}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    say(f"кэш: записей {len(cache)}, закрытых у линейки {RULER} {len(closed)}")

    # (0) калибровка — ДО всяких ячеек: сломанная загрузка иначе выглядит
    # ровно как «правило ничего не меняет».
    base_st, base_c, base_sz = book_form(cache, ctx, launch, dep=dep,
                                         book=book, maker=plain_maker(book),
                                         now=now, log=_quiet)
    base = columns(base_st, base_c, base_sz)
    if not base:
        return {"error": "база не дала ни одной закрытой сделки при непустом "
                         "кэше: считать не с чем", "mech": MECH}
    cal_u = calib_uniform(cache, ctx, launch, base, base_sz, dep=dep,
                          book=book, now=now, log=_quiet)
    say(f"калибровка, равномерное уменьшение ×{CALIB_MULT:g}: "
        f"{cal_u.get('why')}")
    cal_p = calib_planted(cache, dep=dep, b=b_verdict, book=book, now=now,
                          log=_quiet)
    say(f"калибровка, подсаженный тесный час: {cal_p.get('why')}")

    # (1) загрузка базы — первое число заявки
    load = load_of(base_sz, dep)
    say(f"загрузка базы {book} ${int(dep)}: средняя "
        f"{100 * (load or {}).get('mean', 0):.1f} %, медиана "
        f"{100 * (load or {}).get('median', 0):.1f} %, пик "
        f"{100 * (load or {}).get('peak', 0):.1f} % "
        f"({(load or {}).get('peak_usd')} $), открытых в среднем "
        f"{(load or {}).get('open_mean')}, пик {(load or {}).get('open_peak')}")
    agree = agrees_with_cell(cache, ctx, launch, dep=dep, book=book, now=now,
                             log=_quiet)
    say("сверка с ячейкой семейства: "
        + ("равны" if agree.get("все_равны") else f"РАСХОЖДЕНИЕ {agree}"))
    bites = bite_table(AG.packed_short(cache), ctx, launch, dep=dep, now=now,
                       log=_quiet)
    for r in bites:
        say(f"  укус {R.ruler_title(r['book'])}: {r['bite']} "
            f"(медиана дня {r['med']}, доход/просадка {r['ratio']}, "
            f"суток {r['days']})")

    # (2–3) ось бюджета: ячейка вердикта и диагностика сетки
    cells, verdict = [], None
    for b in grid:
        got = {"b": float(b), "verdict_cell": abs(b - b_verdict) < 1e-12,
               "by_dep": {}}
        for d in deps:
            st, c, sz = book_form(cache, ctx, launch, dep=d, book=book,
                                  maker=budget_maker(b, book), now=now,
                                  log=_quiet)
            cols = columns(st, c, sz)
            if cols is not None:
                cols["load"] = load_of(sz, d)
                cols["mults"] = None if sz is None else list(sz.mults)
            got["by_dep"][str(int(d))] = cols
            say(f"бюджет b={b:g}, ${int(d):,}: $ {(cols or {}).get('usd')}, "
                f"доход/просадка {(cols or {}).get('ratio')}, укус "
                f"{(cols or {}).get('bite')}, взято {(cols or {}).get('taken')}"
                f", ниже пола {(cols or {}).get('below_floor')}, связывал "
                f"{(cols or {}).get('capped')} раз")
        cells.append(got)
        if got["verdict_cell"]:
            verdict = got
    vcell = ((verdict or {}).get("by_dep") or {}).get(str(int(dep)))

    # (4) контроль перестановкой — только у ячейки вердикта
    ctl, kind, kind_why = None, None, None
    if vcell:
        kind, kind_why = control_kind(vcell.get("floor_share"))
        say(f"контроль: {kind_why}")
    if vcell and seeds:
        ctl = control(cache, ctx, launch, vcell.get("mults") or [],
                      seeds=seeds, dep=dep, book=book, now=now, log=_quiet,
                      say=say, kind=kind, pool=taken_keys(base_sz),
                      n_keep=vcell.get("taken"))
        ctl["why"] = kind_why
        ctl["margin_med"] = _med([(d or {}).get("margin_usd")
                                  for d in ctl["draws"]])
        ctl["n_med"] = _med([(d or {}).get("n") for d in ctl["draws"]])
    k1, w1, n1 = killer_one(base, vcell)
    say(f"убийца 1 ({_verd(k1)}): {w1}")
    k2, w2, n2 = killer_two(vcell or {}, ctl)
    say(f"убийца 2 ({_verd(k2)}): {w2}")
    k3, w3, n3 = killer_three(load, vcell)
    say(f"убийца 3 ({_verd(k3)}): {w3}")
    k4, w4, n4 = killer_four(vcell)
    say(f"убийца 4 ({_verd(k4)}): {w4}")
    if vcell:
        vcell.pop("mults", None)
    for c in cells:
        for v in (c.get("by_dep") or {}).values():
            if v:
                v.pop("mults", None)
    return {"mech": MECH, "book": book, "ruler": RULER, "dep": float(dep),
            "deps": [float(x) for x in deps], "dep_skip": float(DEP_SKIP),
            "dep_skip_why": DEP_SKIP_WHY,
            "grid": [float(x) for x in grid], "b": float(b_verdict),
            "half": float(HALF), "floor": R.floor_of(book),
            "ticket": {str(int(d)): R.ticket(d, book) for d in deps},
            "seeds": int(seeds), "beat_max": BEAT_MAX, "load_max": LOAD_MAX,
            "floor_share_max": FLOOR_SHARE_MAX,
            "base": base, "load": load, "bites": bites, "agree": agree,
            "calib": {"uniform": cal_u, "planted": cal_p},
            "cells": cells, "control": ctl, "control_kind": kind,
            "control_why": kind_why,
            "killers": {"1": {"pass": k1, "why": w1, "nums": n1},
                        "2": {"pass": k2, "why": w2, "nums": n2},
                        "3": {"pass": k3, "why": w3, "nums": n3},
                        "4": {"pass": k4, "why": w4, "nums": n4}},
            "costs_error": (ctx or {}).get("error"),
            "closed": len(closed), "records": len(cache),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _verd(x):
    return "прошёл" if x else ("НЕ прошёл" if x is False else "не измерен")


# --- показ ---------------------------------------------------------------

def _u(x):
    return "—" if x is None else f"{float(x):+,.2f} $"


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _n(x):
    return "—" if x is None else f"{int(x)}"


def _r(x):
    return "—" if x is None else f"{float(x):g}"


def _col(f, v):
    if v is None:
        return "—"
    if f == "max_dd_wo_worst":
        return _pp(v)
    if f in ("n", "taken", "no_cash", "below_floor"):
        return _n(v)
    if f in ("ratio", "bite"):
        return _r(v)
    return _u(v)


def _cols_table(rows):
    L = ["| книга | " + " | ".join(t for _f, t, _lo in COLS) + " |",
         "|---|" + "--:|" * len(COLS)]
    for name, c in rows:
        if not c:
            L.append(f"| {name} | " + " | ".join("—" for _ in COLS) + " |")
            continue
        L.append(f"| {name} | "
                 + " | ".join(_col(f, c.get(f)) for f, _t, _lo in COLS) + " |")
    return L


def _taken_line(base, cell, limit):
    """Число взятых обязано СОЙТИСЬ или разница названа — числом, не прозой.

    Заявка обещает, что не отбирается ни одна сделка: денег у книги с
    бюджетом больше, значит отказов кассы у неё нет, а взятых не меньше.
    Единственная законная убыль — пол билета, и она печатается тут же.
    Фраза собирается из чисел: разойдись обещание с фактом, она скажет
    об этом сама.
    """
    bt, ct = base.get("taken"), cell.get("taken")
    bf = cell.get("below_floor")
    if bt is None or ct is None:
        return ("Число взятых не измерено ни у одной из книг — сравнивать "
                "нечего.")
    d = int(ct) - int(bt)
    sh = cell.get("floor_share")
    say = [f"Взято кассой: база {int(bt)}, бюджет {int(ct)} "
           f"({d:+d}); отказов кассы {base.get('no_cash')} против "
           f"{cell.get('no_cash')}."]
    if bf is None:
        say.append("Сколько решений вычеркнул пол билета — не измерено.")
    else:
        say.append(f"Полом билета вычеркнуто {int(bf)} решений"
                   + ("" if sh is None
                      else f" ({100 * float(sh):.1f} % от взятых при пределе "
                           f"{100 * float(limit or 0):.0f} %)")
                   + ".")
        rest = d + int(bf)
        if rest:
            say.append(f"Разница взятых объясняется полом не полностью: "
                       f"остаётся {rest:+d} — их даёт касса, у которой при "
                       "меньших размерах освобождаются деньги под новые "
                       "решения.")
        else:
            say.append("Иных потерь нет: разница взятых равна вычеркнутым "
                       "полом.")
    return " ".join(say)


def _named_table(rows):
    L = ["| книга | " + " | ".join(f"{d}" for d in NAMED_DAYS) + " |",
         "|---|" + "--:|" * len(NAMED_DAYS)]
    for name, c in rows:
        cells = []
        for d in NAMED_DAYS:
            v = ((c or {}).get("named") or {}).get(d) or {}
            cells.append("—" if v.get("usd") is None
                         else f"{_u(v['usd'])} ({_n(v.get('n'))})")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    return L + ["", "Прочерк значит «дня нет в суточном своде книги», а не "
                "«книга вышла в ноль»: в скобках сделок дня.", ""]


def _load_table(rows):
    L = ["| книга | часов | средняя | медиана | пик | пик, $ | открытых "
         "в среднем | пик открытых |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for name, ld in rows:
        if not ld:
            L.append(f"| {name} | " + " | ".join("—" for _ in range(7)) + " |")
            continue
        L.append(f"| {name} | {ld['hours']} | {_p(ld['mean'])} | "
                 f"{_p(ld['median'])} | {_p(ld['peak'])} | "
                 f"{ld['peak_usd']:,.0f} $ | {ld['open_mean']} | "
                 f"{ld['open_peak']} |")
    return L


def report(s):
    L = [f"# Бюджет маржи короткой книги `{s.get('book')}` "
         f"(механика {s.get('mech')})", "",
         "Заявка предлагающего 2026-09-14: книга держит в открытых шортах "
         "не больше объявленной доли депозита, и каждая новая позиция "
         "получает **не больше билета и не больше половины остатка "
         "бюджета**. Ни одна сделка не отбирается: каждое решение листа "
         "открывается, меняется только его маржа. Плечо, пол капитуляции, "
         "цель, срок, возраст имени и охрана рынком — прежние, поэтому "
         "исход позиции в долях маржи тот же, и меняется только доллар.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    b = s.get("b")
    L += [f"Формула: `B = b × депозит`, `остаток = B − Σ маржи открытых`, "
          f"`маржа = min(билет, остаток / {s.get('half'):g})`. Ось "
          "объявлена заданием: b = "
          + " / ".join(f"{x:g}" for x in s.get("grid") or [])
          + f"; **ячейка вердикта — середина оси, b = {b:g}**, книга "
          f"`{s.get('book')}`, депозит ${int(s.get('dep')):,}. Билет книги "
          + ", ".join(f"${int(float(k)):,} → {v:g} $"
                      for k, v in (s.get("ticket") or {}).items())
          + f"; биржевой пол билета {s.get('floor'):g} $.", "",
          f"Депозит ${int(s.get('dep_skip')):,} из замера исключён заданием: "
          f"{s.get('dep_skip_why')}.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}. Числа ниже "
              "брутто, и сравнивать их с нетто-числами страницы нельзя.", ""]
    ag = s.get("agree") or {}
    L += ["## Касса здесь не вторая", "",
          ("Форма книги считается теми же функциями и в том же порядке, что "
           "ячейка семейства (`short_grid.cell_stats`), и на общих полях "
           "они "
           + ("**равны**" if ag.get("все_равны") else "**РАЗОШЛИСЬ**")
           + ": "
           + ", ".join(f"{k} {v.get('форма')}/{v.get('ячейка')}"
                       for k, v in ag.items() if isinstance(v, dict))
           + ". Счёт эквити обёртки сверяется с итогом самой кассы на "
             "каждом прогоне — расхождение роняет замер, а не считается "
             "дальше молча."), ""]
    cal = s.get("calib") or {}
    u, p = cal.get("uniform") or {}, cal.get("planted") or {}
    L += ["## 0. Калибровочная пара", "",
          "Пара отвечает на два разных вопроса: «молчит ли мера на том, что "
          "не должно её двигать» и «находит ли она подсаженное». Без первой "
          "ноги разница чисел объяснялась бы тем, что денег стало меньше; "
          "без второй сломанная загрузка выглядела бы как «правило ничего "
          "не меняет».", "",
          f"**Равномерное уменьшение ×{u.get('mult')}** "
          f"({'сошлось' if u.get('pass') else 'НЕ сошлось'}): {u.get('why')}.",
          "",
          f"| | сделок | взято | $ | доход/просадка | укус |",
          "|---|--:|--:|--:|--:|--:|",
          f"| база | {_n(u.get('base_n'))} | {_n(u.get('base_taken'))} | "
          f"{_u(u.get('base_usd'))} | {_r(u.get('base_ratio'))} | "
          f"{_r(u.get('base_bite'))} |",
          f"| ×{u.get('mult')} | {_n(u.get('n'))} | {_n(u.get('taken'))} | "
          f"{_u(u.get('usd'))} | {_r(u.get('ratio'))} | {_r(u.get('bite'))} |",
          "",
          "Укус безразмерен ТОЧНО и не шелохнулся. Доход на просадку "
          f"безразмерен НЕ вполне: он сместился на {_r(u.get('ratio_bias'))} "
          "при уменьшении маржи вдвое — просадка считается к пиковому "
          "счёту (`run_paper._dd`), а депозит остаётся прежним, поэтому у "
          "книги с меньшей прибылью та же по деньгам просадка выходит "
          "глубже долей. Смещение работает ПРОТИВ заявки: книга с "
          "бюджетом мельче базы, значит её доход на просадку занижен тем "
          "же механизмом, и убийца 1 от этого строже, а не мягче.", "",
          f"**Подсаженный тесный час** ({PLANT_N} позиций одной секунды с "
          f"исходом {PLANT_PNL:g} доли маржи, "
          f"{'найден' if p.get('pass') else 'НЕ найден'}): {p.get('why')}. "
          f"Предел по построению — `|исход| × B` = {p.get('limit')} $, и он "
          "рыхлый: он говорит только, что тесный час физически не может "
          "стоить больше бюджета.", ""]
    L += ["## 1. Загрузка книги — число, которого не было", "",
          "Доля депозита в марже открытых позиций по часам. Часы без "
          "позиций входят в ряд нулём: книга в такой час держала ноль. "
          "Именно это число решает, связывает ли бюджет хоть один день, — "
          "и до сих пор оно у коротких книг не печаталось нигде.", "",
          "Знаменатель — НАЧАЛЬНЫЙ депозит, тот же, от которого объявлен "
          "бюджет: иначе две доли мерились бы разными линейками. Отсюда и "
          "загрузка выше 100 %: билет считается от ТЕКУЩЕГО счёта, и "
          "заработавшая книга держит в марже больше, чем внесено.", ""]
    rows = [(f"база {R.ruler_title(s.get('book'))}", s.get("load"))]
    vc = _verdict_cell(s)
    if vc:
        rows.append((f"бюджет b={b:g}", vc.get("load")))
    L += _load_table(rows) + [""]
    L += ["## Укус коротких книг", "",
          "Укус («сколько обычных прибыльных дней съедает худший») судит "
          "правило вылета кандидатов, а у семейства `h24` он не напечатан "
          "нигде. Считается мерой проекта (`stability.stats`) по суточной "
          "разбивке ячейки семейства.", "",
          "| книга | сделок | $ | доход/просадка | укус | медиана дня | "
          "зелёных | суток |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for r in s.get("bites") or []:
        L.append(f"| {R.ruler_title(r['book'])} | {_n(r.get('n'))} | "
                 f"{_u(r.get('usd'))} | {_r(r.get('ratio'))} | "
                 f"{_r(r.get('bite'))} | {_u(r.get('med'))} | "
                 + ("—" if r.get("green") is None else f"{r['green']:.2f}")
                 + f" | {_n(r.get('days'))} |")
    L += ["", "## 2. Ячейка вердикта против базы", ""]
    L += _cols_table([(f"база {R.ruler_title(s.get('book'))}", s.get("base")),
                      (f"бюджет b={b:g}", vc)]) + [""]
    L += [_taken_line(s.get("base") or {}, vc or {},
                      s.get("floor_share_max")), ""]
    L += _named_table([(f"база {R.ruler_title(s.get('book'))}", s.get("base")),
                       (f"бюджет b={b:g}", vc)])
    L += ["## 3. Сетка бюджета и масштаб депозита — диагностика", "",
          "Вердикт выносится по ОДНОЙ объявленной ячейке; соседние значения "
          "оси и депозит $100k печатаются, чтобы было видно форму, а не "
          "чтобы выбрать лучшую.", "",
          "| b | депозит | $ | доход/просадка | укус | без 3 лучших дней | "
          "взято | ниже пола | связывал | средняя загрузка |",
          "|---:|---:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for c in s.get("cells") or []:
        for d, v in sorted((c.get("by_dep") or {}).items(),
                           key=lambda kv: float(kv[0])):
            mark = " ⟵" if c.get("verdict_cell") and int(d) == int(s["dep"]) \
                else ""
            ld = (v or {}).get("load") or {}
            L.append(f"| {c['b']:g}{mark} | ${int(d):,} | "
                     f"{_u((v or {}).get('usd'))} | "
                     f"{_r((v or {}).get('ratio'))} | "
                     f"{_r((v or {}).get('bite'))} | "
                     f"{_u((v or {}).get('usd_wo_top3d'))} | "
                     f"{_n((v or {}).get('taken'))} | "
                     f"{_n((v or {}).get('below_floor'))} | "
                     f"{_n((v or {}).get('capped'))} | "
                     f"{_p(ld.get('mean')) if ld else '—'} |")
    L += ["", "⟵ — объявленная ячейка вердикта.", ""]
    ctl = s.get("control")
    L += ["## 4. Контроль", "",
          "Какой розыгрыш считается, решает ЧИСЛО, а не автор: доля "
          "решений, вычеркнутых полом билета, выше "
          f"{100 * s.get('floor_share_max', 0):.0f} % от взятых — правило "
          "читается как отбор и сравнивается со **случайной выборкой того "
          "же размера** (те же решения базы, полный билет); ниже предела "
          "отбора нет, и спор идёт о раскладке — тогда **множители "
          "переставляются** между всеми решениями книги: то же "
          "мультимножество размеров, другое место.", ""]
    if not ctl:
        L += ["Контроль не считался: зёрен нет."
              + ((" " + (s.get("control_why") or "")) if s.get("control_why")
                 else ""), ""]
    else:
        n2 = (s.get("killers") or {}).get("2", {}).get("nums") or {}
        ttl = ("случайная выборка" if ctl.get("kind") == "sample"
               else "перемешанные")
        L += [f"Выбран розыгрыш: {ctl.get('why')}.", "",
              f"Зёрен {ctl.get('n')} ({ctl.get('secs')} с). Σ маржи у "
              f"бюджета {_u((vc or {}).get('margin_usd'))}, у контроля "
              f"(медиана) {_u(ctl.get('margin_med'))}; сделок у бюджета "
              f"{_n((vc or {}).get('n'))}, у контроля (медиана) "
              f"{_n(ctl.get('n_med'))}"
              + (f", выбиралось {ctl.get('n_keep')} решений из "
                 f"{ctl.get('pool')}" if ctl.get("kind") == "sample" else "")
              + ".", "",
              f"| колонка | бюджет | {ttl} (медиана) | зёрен, где контроль "
              "не хуже |", "|---|--:|--:|--:|"]
        for f, t in (("bite", "укус"), ("ratio", "доход/просадка")):
            g = n2.get(f) or {}
            L.append(f"| {t} | {_r((vc or {}).get(f))} | "
                     + ("—" if g.get("med") is None
                        else f"{float(g['med']):.2f}") + " | "
                     + ("—" if g.get("share") is None
                        else f"{100 * g['share']:.0f} % из {g.get('n')}")
                     + " |")
        L += [""]
    L += ["## Убийцы", "",
          "| # | о чём | вердикт | почему |", "|---|---|---|---|"]
    # Название убийцы 2 — по тому розыгрышу, который ДЕЙСТВИТЕЛЬНО
    # считался: подпись «перестановка» над выборкой стареет молча и
    # однажды прочтётся не про тот контроль.
    titles = {"1": "потолок на записи",
              "2": ("контроль выборкой того же размера"
                    if (ctl or {}).get("kind") == "sample"
                    else "контроль перестановкой"),
              "3": "загрузка", "4": "форвард"}
    for k in ("1", "2", "3", "4"):
        g = (s.get("killers") or {}).get(k) or {}
        L.append(f"| {k} | {titles[k]} | {_verd(g.get('pass'))} | "
                 f"{g.get('why')} |")
    L += ["", "Убийца 4 форвардом не является и им не назван: форвардных "
          "суток у необъявленной сестры ноль, судится пересчёт по уже "
          "виденному прошлому. Дорога вперёд — решение владельца.", "",
          f"Записей в кэше {s.get('records')}, закрытых у линейки "
          f"`{s.get('ruler')}` {s.get('closed')}; прогон "
          f"{s.get('computed_at')} UTC, {s.get('secs')} с.", ""]
    return "\n".join(L)


def _verdict_cell(s):
    for c in s.get("cells") or []:
        if c.get("verdict_cell"):
            return (c.get("by_dep") or {}).get(str(int(s.get("dep"))))
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--mem-limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    s = run(seeds=a.seeds, limit=a.limit, mem_limit=a.mem_limit)
    with open(os.path.join(OUT, f"{ART}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    path = os.path.join(OUT, f"{ART}.md")
    txt = report(s)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        # Публикация — часть прогона: шаг, который можно забыть, рано или
        # поздно забывают.
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), path,
                        "механика 258a860c: бюджет маржи короткой книги"],
                       check=False)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
