#!/usr/bin/env python3
"""
Тесты механики bb7c3581 — буря выкупа шортов по рынку.

Пять мест, где легче всего соврать себе в свою пользу, и каждое закрыто
синтетикой с известным заранее ответом.

**Заглядывание в будущее.** Правило решает, закрывать ли книгу в часе k,
и если оно заглянет хоть в один час ПОСЛЕ фактического выхода позиции,
находка будет неотличима от находки. Проверяется прямо: будущее
переписывается бурями целиком, прошлое обязано не шелохнуться. Час
самого выхода — тоже будущее: в нём позицию уже закрыли ядро или
охрана.

**Сама мера.** Сломанное чтение сводок и перевёрнутая сторона выглядят
ровно как «бури не было» — в этом проекте так дважды печатался нулевой
отчёт. Поэтому калибровочная пара: подсаженный бурный час мера обязана
найти и закрыть им каждый открытый шорт, а на потоке без бурь —
промолчать и отдать базу БИТ В БИТ.

**База.** Механика считается ПОВЕРХ охраны рынком, то есть база — книги
как сейчас, а не кэш реплея. Кэш хранит исход БЕЗ охраны; забудь её
применить — и правило «спасало» бы то, что охрана уже закрыла. Отдельная
проверка сажает волну мажоров выше порога и смотрит, что часы жизни
укоротились.

**Контроль.** Для правила ВСЕЙ книги контроль случайными позициями
вырождается, поэтому случайными становятся часы — с ТЕМ ЖЕ часом суток
и ТОГО ЖЕ числа. Проверяется и согласование по часу суток, и отказ, когда
часов суток не хватает: выборка меньшего размера сделала бы контроль
слабее правила молча.

**Пустота и вердикт.** Час с малым числом имён — ПРОЧЕРК, а не ноль
ширины; ноль строк при непустом каталоге — отказ, а не отчёт; фраза
итога выводится из числа, а не стоит рядом с ним.

Деньги считаются НАСТОЯЩЕЙ кассой семейства (`agree_book.stats_of`) на
подставном журнале: подделка обязана выглядеть живой — поля живого
писателя, дрожание, живые даты, живой масштаб. Рынок при этом уводится в
пустой каталог везде, кроме проверки самой охраны: тест, зависящий от
того, что сегодня записал сборщик, менял бы ответ сам собой.

    python3 research/mech_bb7c3581/test_storm.py
"""
import json
import os
import random
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (HERE, os.path.join(RESEARCH, "dca_paper"),
           os.path.join(RESEARCH, "a1_universe"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "mech_d71203f0"),
           os.path.join(RESEARCH, "mech_357a7c60")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agree_book as AG                                        # noqa: E402
import rules as R                                              # noqa: E402
import run_paper as RP                                         # noqa: E402
import squeeze_fuel as SQ                                      # noqa: E402
import wave as WV                                              # noqa: E402
import storm as STM                                            # noqa: E402
import run_storm as RUN                                        # noqa: E402

FAILED = []
CHECKS = [0]
HOUR = 3600.0
# Живые даты, но ДО начала записи сводок (01.08.2026): журнал подставной,
# и рынок ему взять неоткуда — см. `empty_market`.
BASE_TS = 1778000000.0 - 1778000000.0 % HOUR
BASE_HK = int((BASE_TS - 1.0) // HOUR)      # календарный час ПЕРЕД входом


def check(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def run_test(fn):
    """Прогнать проверку так, чтобы её ПАДЕНИЕ было сосчитано, а не
    оборвало сюиту.

    Тест, умерший исключением, уносит с собой все проверки после себя, и
    сводки падений не печатается вовсе — снаружи это неотличимо от «их не
    было». Приёмка фабрики (`runlog._run_tests`) читает ПОСЛЕДНИЕ 4000
    символов и по сводке судит, какой контроль укусил; оборванная сюита
    оставляет в хвосте трассировку вместо имени, и кусающийся контроль
    объявляется холостым (урок постройки d71203f0 12.09).
    """
    try:
        fn()
    except BaseException as e:                                # noqa: BLE001
        import traceback
        name = getattr(fn, "__name__", "?")
        check(name, False, f"{type(e).__name__}: {e} | "
              + traceback.format_exc()[-400:].replace("\n", " ⏎ "))


# ======================================================================
# Подделки, которые обязаны выглядеть живыми
# ======================================================================

def summary_row(idx, mid, buy, sell, liq_buy, liq_sell, rnd, liq=True):
    """Строка часовой сводки — теми же полями, что пишет живой писатель.

    Живой писатель кладёт `liq_short` (доллары метки `Buy`) и `liq_long`
    (метки `Sell`) ТОЛЬКО при живом опросе метрик того же часа. Час без
    опроса идёт без этих полей ВОВСЕ — поэтому `liq=False` их не
    обнуляет, а убирает: подделка, кладущая ноль, проверяла бы не тот
    случай, который бывает в жизни.
    """
    j = lambda a, b: rnd.uniform(a, b)                        # noqa: E731
    row = {"n_snap": 3400 + rnd.randrange(-300, 200),
           "snap_span_sec": round(j(3590, 3600), 1),
           "snap_gap_max_sec": round(j(1.0, 200.0), 1),
           "mid_close": round(mid, 8),
           "mid_high": round(mid * j(1.001, 1.02), 8),
           "mid_low": round(mid * j(0.98, 0.999), 8),
           "spread_bp": round(j(0.5, 9.0), 4),
           "upd": rnd.randrange(5, 20),
           "reach_bp": round(j(1.0, 40.0), 1),
           "best_b": round(j(1e4, 3e5), 2), "best_a": round(j(1e4, 3e5), 2),
           "big_med": round(j(1e4, 6e5), 2), "big_max": round(j(1e5, 2e6), 2),
           "n_trades": rnd.randrange(200, 30000),
           "buy": round(buy, 2), "sell": round(sell, 2),
           "vol_max_1s": round(j(1e3, 2e6), 2),
           "traded_secs": rnd.randrange(300, 3500),
           "depth_eat_b": None, "depth_eat_a": None,
           "fr": round(j(-0.0006, 0.0006), 6),
           "oi_usd": round(j(1e6, 5e9), 1),
           "basis_bp": round(j(-40, 40), 4),
           "mins_fund": round(j(0, 480), 1),
           "hour": time.strftime("%Y-%m-%d-%H", time.gmtime(int(idx) * 3600))}
    if liq:
        row["liq_short"] = round(liq_buy, 2)                  # доллары метки Buy
        row["liq_long"] = round(liq_sell, 2)                  # доллары метки Sell
    for b in ("b0.0005", "b0.001", "a0.0005", "a0.001"):
        row[f"bq_{b}"] = None
        row[f"cov_{b}"] = 0.0
    return row


def record(sym, at, marks, exit_="срок", rnd=None, ruler="safe_s"):
    """Запись кэша реплея — поля ровно те, что пишет живой прогон."""
    rnd = rnd or random.Random(7)
    lev = round(rnd.uniform(2.0, 20.0), 6)
    px = round(rnd.uniform(0.01, 3.0), 6)
    cum = 0.0
    ms = []
    for k, d in enumerate(marks, start=1):
        cum += float(d)
        ms.append([at + (k - 1) * HOUR, float(d)])
    K = len(marks)
    return {"at": at, "exit_ts": at + K * HOUR - 1.0, "pnl": cum,
            "pnl_net": round(cum - rnd.uniform(0.001, 0.02), 6),
            "lev": lev, "lev_fence": lev,
            "fwd": round(rnd.uniform(-80, 80), 4), "sym": sym, "side": "short",
            "rr": round(rnd.uniform(0.4, 2.5), 4), "gates": ["any", "lo"],
            "exit": exit_, "marks": ms, "end_ts": at + 24 * HOUR,
            "sched_end": at + 24 * HOUR, "depth": 1, "n_rungs": 1,
            "avg": px, "entry_px": px,
            "exit_px": round(px * (1.0 - cum / lev), 8),
            "filled": round(rnd.uniform(0.5, 4.0), 6),
            "fills": [[at + rnd.uniform(30, 900), px, 0.25]],
            "state": "closed", "pair": [ruler]}


def journal(n_tail=12, n_rest=28, seed=11, stagger=True,
            rulers=("safe_s", "optimal_s"), hold=None):
    """Подставной журнал: хвост (пол) и обычные сделки, с дрожанием."""
    rnd = random.Random(seed)
    cache, launch = {}, {}
    i = 0
    for ruler in rulers:
        for tail in (True, False):
            for j in range(n_tail if tail else n_rest):
                sym = f"STM{i:03d}USDT"
                i += 1
                launch[sym] = BASE_TS - rnd.uniform(30, 400) * 86400
                at = BASE_TS + ((j % 12) * 6 * HOUR if stagger else 0.0)
                K = hold or rnd.choice([8, 12, 18, 24])
                marks = [round(rnd.uniform(-0.06, 0.05), 6) for _ in range(K)]
                if tail:
                    marks[-1] = round(-0.55 - rnd.uniform(0.0, 0.2)
                                      - sum(marks[:-1]), 6)
                cache[(ruler, sym, at)] = record(
                    sym, at, marks, exit_=("пол" if tail else "срок"),
                    rnd=rnd, ruler=ruler)
    return cache, launch


_EMPTY = {}


def empty_market():
    """Увести рынок книг в ПУСТОЙ каталог сводок.

    Охрана рынком (`run_paper.guard_shorts`) берёт волну из глобального
    `_MARKET`. Оставь его на настоящем каталоге — и деньги подставного
    журнала зависели бы от того, что сегодня записал сборщик. Тест обязан
    отвечать одно и то же; поэтому рынок пуст, а отсутствие выходов
    «рынок» проверяется отдельным утверждением.
    """
    if "dir" not in _EMPTY:
        _EMPTY["dir"] = tempfile.mkdtemp(prefix="stm-empty-")
    RP.market(root=_EMPTY["dir"])
    return _EMPTY["dir"]


def books_of(cache, launch, now=None):
    """База механики: книги С охраной рынком, ключ несёт КНИГУ."""
    empty_market()
    packed, guards = STM.guarded_books(cache, launch, now=now)
    gcache = STM.keyed(packed)
    return gcache, SQ.views_of(gcache, rulers=STM.BOOK_KEYS), guards


def money(gcache, launch, dep=None):
    """Деньги книг настоящей кассой; издержки не применяются намеренно.

    `ctx=None` — круг издержек у кассы свой и проверен своими тестами
    (`dca_paper/test_costs.py`); здесь проверяется ДОРОГА: кто вышел, в
    каком часу и по какой отметке. Смешав две проверки, мы получили бы
    тест, чьё имя обещает больше, чем он исполняет.
    """
    empty_market()
    return AG.stats_of(STM.repack(gcache), None, launch, STM.BOOK_KEYS,
                       deps=[dep or STM.MAIN_DEP])


def width_of(hours_marked, names=200, s_flow=5e4, turn=1e6, field="liq_long",
             liq=True):
    """Счётчики ширины на выдуманном рынке: {час: сколько имён помечено}.

    Имён в часе — `names` (выше порога измеримости), из них помечено
    столько, сколько сказано. Поток кладётся в названную колонку, вторая
    остаётся тихой: это и есть «сторона несёт смысл, а не имя колонки».
    """
    rnd = random.Random(5)
    acc = STM.new_width()
    for hk, marked in sorted(hours_marked.items()):
        for i in range(names):
            hot = i < marked
            lb = (s_flow if (hot and field == "liq_short") else 10.0)
            ls = (s_flow if (hot and field == "liq_long") else 10.0)
            acc = STM.fold_width([summary_row(hk, 1.0, turn / 2, turn / 2,
                                              lb, ls, rnd, liq=liq)], acc)
    return acc


def storm_at(views, hours):
    """Календарные часы бури из часов ЖИЗНИ (для подсадки в тестах)."""
    out = set()
    for _key, v in views.items():
        at = float(v["rec"]["at"])
        for k in hours:
            out.add(SQ.hour_key(at, k))
    return out


# ======================================================================
# 1. Ширина по календарному часу
# ======================================================================

def test_mark_is_the_parent_judged_cell():
    """Метка имени — константы РОДИТЕЛЯ, а не переписанное число.

    Разойдись родитель со своей судимой ячейкой — механика обязана
    сказать это вслух, а не унести чужой порог молча.
    """
    check("метка: доля равна судимой ячейке родителя",
          STM.MARK_S == SQ.middle(SQ.AXIS_S) == 0.010,
          f"{STM.MARK_S} против {SQ.middle(SQ.AXIS_S)}")
    check("метка: пол в долларах — родительский",
          STM.MIN_USD == SQ.MIN_USD == 1000.0, f"{STM.MIN_USD}")
    check("метка: считается правилом родителя, а не своим",
          STM.SQ.is_marked(2e4, 1e6, STM.MARK_S)
          and not STM.SQ.is_marked(2e3, 1e6, STM.MARK_S),
          "правило метит не то")


def test_width_is_a_dash_below_min_names():
    """Час с малым числом имён — ПРОЧЕРК, а не ноль ширины.

    Доля по десятку имён скачет от одного всплеска: «бури не было» там
    неотличимо от «мерить было не на чем», и печатать ноль значило бы
    выдать второе за первое.
    """
    thin = width_of({100: 5}, names=STM.MIN_NAMES - 1)
    fat = width_of({200: 5}, names=STM.MIN_NAMES)
    s_thin = STM.width_series(thin, "liq_long")
    s_fat = STM.width_series(fat, "liq_long")
    check("измеримость: час с малым числом имён — прочерк",
          s_thin[100] is None, f"{s_thin[100]}")
    check("измеримость: час с достаточным числом имён — число",
          s_fat[200] is not None
          and abs(s_fat[200] - 5.0 / STM.MIN_NAMES) < 1e-12, f"{s_fat[200]}")
    st = STM.width_stats(s_thin)
    check("измеримость: прочерк сосчитан отдельным числом",
          st["measurable"] == 0 and st["unmeasurable"] == 1, f"{st}")
    check("измеримость: распределения без часов нет, а не нули",
          st["median"] is None and st["p99"] is None and st["max"] is None,
          f"{st}")
    check("измеримость: порог объявлен числом", STM.MIN_NAMES == 100,
          f"{STM.MIN_NAMES}")


def test_width_counts_only_marked_names():
    """Считается имя, ПОМЕЧЕННОЕ правилом родителя, а не любое живое.

    Пол в долларах и доля в обороте — оба: доля без пола метит тонкий
    час, пол без доли метит крупное имя в обычный день.
    """
    rnd = random.Random(3)
    acc = STM.new_width()
    # 120 имён: 10 с настоящим всплеском, 40 с долей без пола, 70 тихих
    for i in range(120):
        if i < 10:
            ls, turn = 5e4, 1e6                  # доля 5 %, $50 000 — метка
        elif i < 50:
            ls, turn = 500.0, 1e4                # доля 5 %, но $500 — нет
        else:
            ls, turn = 5e4, 1e9                  # $50 000, но доля 0.005 % — нет
        acc = STM.fold_width([summary_row(500, 1.0, turn / 2, turn / 2,
                                          10.0, ls, rnd)], acc)
    s = STM.width_series(acc, "liq_long")
    check("метка: помечены только настоящие всплески",
          abs(s[500] - 10.0 / 120.0) < 1e-12,
          f"{s[500]} при ожидаемых {10 / 120:.5f}")
    check("метка: имён в знаменателе все измеренные",
          acc["hours"][500]["measured"] == 120,
          f"{acc['hours'][500]['measured']}")


def test_unmeasured_hour_is_never_a_storm():
    """Прочерк бурей НЕ БЫВАЕТ, даже если помеченных имён много.

    Час, в котором сводки есть у трёх имён и все три помечены, даёт долю
    1.0 — и ровно так выглядит обрыв записи. Ширины у такого часа нет.
    """
    acc = width_of({10: 3}, names=3)             # 3 имени из 3 помечены
    s = STM.width_series(acc, "liq_long")
    check("прочерк: ширина не посчитана", s[10] is None, f"{s[10]}")
    check("прочерк: бурей не стал", STM.storm_hours(s, 0.02) == [],
          f"{STM.storm_hours(s, 0.02)}")
    mixed = width_of({10: 3}, names=3)
    for hk, m in ((11, 2), (12, 30)):
        mixed = width_of({hk: m}, names=200, )
        s2 = STM.width_series(mixed, "liq_long")
        want = [11] if hk == 11 else [12]
        got = STM.storm_hours(s2, 0.01)
        check(f"прочерк: измеримый час {hk} судится по своей ширине",
              (got == want) == (m / 200.0 >= 0.01), f"{got}")


def test_storm_hours_need_the_declared_width():
    """Бурный час — тот, чья ширина ≥ q объявленной оси.

    Ось объявлена ДО прогона и судит СЕРЕДИНА; лучшая ячейка после
    просмотра — ошибка R5, и она здесь невозможна по построению.
    """
    acc = width_of({1: 1, 2: 2, 3: 4, 4: 6, 5: 0}, names=200)
    s = STM.width_series(acc, "liq_long")        # ширина 0.5 / 1 / 2 / 3 / 0 %
    check("ось: объявлена до прогона", STM.AXIS_Q == (0.01, 0.02, 0.03),
          f"{STM.AXIS_Q}")
    check("ось: судится середина", STM.middle() == 0.02, f"{STM.middle()}")
    check("порог 1 %: часы 2, 3, 4", STM.storm_hours(s, 0.01) == [2, 3, 4],
          f"{STM.storm_hours(s, 0.01)}")
    check("порог 2 %: часы 3, 4", STM.storm_hours(s, 0.02) == [3, 4],
          f"{STM.storm_hours(s, 0.02)}")
    check("порог 3 %: час 4", STM.storm_hours(s, 0.03) == [4],
          f"{STM.storm_hours(s, 0.03)}")
    check("порог: час с нулевой шириной бурей не бывает",
          5 not in STM.storm_hours(s, 0.01), "ноль стал бурей")
    check("сутки: считаются по номеру часа",
          STM.days_of([0, 23, 24, 47, 48]) == [0, 1, 2],
          f"{STM.days_of([0, 23, 24, 47, 48])}")
    check("час суток: номер часа записи и есть час UTC",
          STM.hod_hist([3, 27, 51, 4]) == {3: 3, 4: 1},
          f"{STM.hod_hist([3, 27, 51, 4])}")


def test_swapped_columns_change_the_storm_hours():
    """Сторону решают ДАННЫЕ: другая колонка — другое множество бурь.

    Механика обязана быть верна при любом ИМЕНИ колонки (колонки сводки
    названы, судя по записи, наоборот). Модуль, считающий обе колонки
    одинаково, на этом тесте падает — а вместе с ним и вся калибровка
    стороны, которая от различия колонок и живёт.
    """
    rnd = random.Random(9)
    acc = STM.new_width()
    for i in range(200):
        # час 7: всплеск в колонке `liq_long`; час 8 — в `liq_short`
        acc = STM.fold_width([summary_row(7, 1.0, 5e5, 5e5, 10.0,
                                          5e4 if i < 10 else 10.0, rnd)], acc)
        acc = STM.fold_width([summary_row(8, 1.0, 5e5, 5e5,
                                          5e4 if i < 10 else 10.0, 10.0,
                                          rnd)], acc)
    a = STM.storm_hours(STM.width_series(acc, "liq_long"), 0.02)
    b = STM.storm_hours(STM.width_series(acc, "liq_short"), 0.02)
    check("сторона: колонка `liq_long` даёт час 7", a == [7], f"{a}")
    check("сторона: колонка `liq_short` даёт час 8", b == [8], f"{b}")
    check("сторона: множества бурь РАЗНЫЕ", set(a) != set(b), f"{a} и {b}")


def test_rows_without_liquidations_are_a_dash_not_zero():
    """Час без полей ликвидаций или с нулевым оборотом — не измерен."""
    no_liq = width_of({20: 0}, names=150, liq=False)
    check("прочерк: час без полей ликвидаций в меру не идёт",
          20 not in no_liq["hours"] and no_liq["unmeasured"] == 150,
          f"{no_liq['unmeasured']}, часов {list(no_liq['hours'])}")
    rnd = random.Random(1)
    zero_turn = STM.fold_width([summary_row(21, 1.0, 0.0, 0.0, 5e4, 5e4, rnd)])
    check("прочерк: нулевой оборот в меру не идёт",
          21 not in zero_turn["hours"] and zero_turn["unmeasured"] == 1,
          f"{zero_turn}")


def test_width_does_not_double_count_a_name():
    """Две строки одного имени на один час — одно имя, а не два.

    В живой записи таких строк без малого десять тысяч; посчитав их
    дважды, мы раздули бы знаменатель ширины у одних часов и не у
    других.
    """
    rnd = random.Random(4)
    rows = [summary_row(30, 1.0, 5e5, 5e5, 10.0, 5e4, rnd),
            summary_row(30, 1.0, 5e5, 5e5, 10.0, 5e4, rnd)]
    acc = STM.fold_width(rows)
    check("дубль: имя сосчитано один раз",
          acc["hours"][30]["measured"] == 1, f"{acc['hours'][30]}")
    check("дубль: сосчитан отдельным числом", acc["dup"] == 1, f"{acc}")


# ======================================================================
# 2. Правило ВСЕЙ книги
# ======================================================================

def test_rule_closes_every_open_short_in_the_storm_hour():
    """В бурный час закрывается ВСЁ, что открыто, — и только оно.

    Единица правила — час книги, а не позиция: укус делает
    одновременность, и отбор позиций здесь был бы другим правилом.
    """
    cache, launch = journal(n_tail=4, n_rest=4, seed=61, stagger=True)
    gcache, views, _g = books_of(cache, launch)
    hk = SQ.hour_key(BASE_TS, 3)                 # календарный час
    changed = STM.apply_storm(views, {hk})
    want = {key: hk - SQ.hour_key(float(v["rec"]["at"]), 0)
            for key, v in views.items()}
    want = {key: k for key, k in want.items()
            if 1 <= k < int(views[key]["path"]["K"])}
    check("книга целиком: закрыты ровно открытые в этот час",
          set(changed) == set(want) and changed == want,
          f"правило {len(changed)}, ожидалось {len(want)}")
    check("книга целиком: открытых в этот час и правда несколько",
          len(changed) >= 4, f"{len(changed)}")
    same = {SQ.hour_key(float(views[key]["rec"]["at"]), k)
            for key, k in changed.items()}
    check("книга целиком: календарный час выхода у всех ОДИН",
          same == {hk}, f"{same}")


def test_first_storm_hour_wins():
    """Помечается ПЕРВЫЙ бурный час жизни, а не лучший и не последний."""
    cache, launch = journal(n_tail=1, n_rest=1, seed=62, stagger=False,
                            rulers=("safe_s",), hold=12)
    _gc, views, _g = books_of(cache, launch)
    key = sorted(views)[0]
    at = float(views[key]["rec"]["at"])
    storms = {SQ.hour_key(at, 2), SQ.hour_key(at, 7)}
    ch = STM.apply_storm(views, storms)
    check("первый бурный час", ch.get(key) == 2, f"{ch.get(key)}")
    check("первый бурный час: он же у storm_exit",
          STM.storm_exit(views[key], storms) == 2,
          f"{STM.storm_exit(views[key], storms)}")


def test_rule_never_touches_the_exit_hour():
    """Час K — тот, в котором позицию закрыли ядро или охрана.

    Закрыть в него «по буре» значило бы решать выход по тому, чем сделка
    кончилась: час выхода правилу не принадлежит.
    """
    cache, launch = journal(n_tail=1, n_rest=1, seed=63, stagger=False,
                            rulers=("safe_s",), hold=10)
    _gc, views, _g = books_of(cache, launch)
    key = sorted(views)[0]
    v = views[key]
    at, K = float(v["rec"]["at"]), int(v["path"]["K"])
    hs = STM.hours_of(v)
    check("час выхода: в часы правила не входит",
          SQ.hour_key(at, K) not in hs and SQ.hour_key(at, K - 1) in hs,
          f"K={K}, часов {len(hs)}")
    ch = STM.apply_storm(views, {SQ.hour_key(at, K)})
    check("час выхода: буря в нём ничего не меняет", ch == {}, f"{ch}")
    ch2 = STM.apply_storm(views, {SQ.hour_key(at, K - 1)})
    check("час перед выходом: буря в нём меняет", ch2.get(key) == K - 1,
          f"{ch2}")


def test_future_does_not_move_the_past():
    """Переписать будущее — прошлое обязано не шелохнуться.

    Журнал здесь БЕЗ разбега и с одним сроком намеренно: правило
    книжное, позиции стоят внахлёст, и «будущее одной» у разбега легко
    оказывается настоящим другой. Тогда тест ловил бы свою подделку, а
    не модуль; при общем входе и общем K множество «после выхода»
    одинаково для всех и с жизнью не пересекается вовсе.
    """
    cache, launch = journal(n_tail=3, n_rest=3, seed=64, stagger=False,
                            hold=10)
    _gc, views, _g = books_of(cache, launch)
    quiet = STM.apply_storm(views, set())
    check("будущее: без бурь выходов нет", quiet == {}, f"{len(quiet)}")

    at = BASE_TS
    K = 10
    after = {SQ.hour_key(at, k) for k in range(K, K + 12)}
    live = set()
    for _key, v in views.items():
        live |= set(STM.hours_of(v))
    check("будущее: часы после выхода с жизнью не пересекаются",
          len(after) == 12 and not (after & live),
          f"общих {len(after & live)}")
    ch_after = STM.apply_storm(views, after)
    check("будущее: бури ПОСЛЕ выхода не метят ничего", ch_after == {},
          f"{len(ch_after)} изменённых")

    only2 = STM.apply_storm(views, {SQ.hour_key(at, 2)})
    ch_mixed = STM.apply_storm(views, after | {SQ.hour_key(at, 2)})
    check("будущее: час выхода взят из прошлого", ch_mixed == only2,
          f"{len(ch_mixed)} против {len(only2)}")
    check("будущее: правило и правда что-то нашло",
          len(only2) == len(views) and set(only2.values()) == {2},
          f"{len(only2)} из {len(views)}")


def test_no_storm_reproduces_the_base_bit_for_bit():
    """Бурь нет — касса книг БИТ В БИТ по семи полям.

    Правило, которое трогает деньги там, где бури не было, — не правило
    выхода, а сдвиг книги. Это же вторая половина калибровочной пары:
    мера обязана молчать на тишине.
    """
    cache, launch = journal(n_tail=6, n_rest=14, seed=65)
    gcache, views, guards = books_of(cache, launch)
    acc = width_of({h: 1 for h in range(BASE_HK, BASE_HK + 48)}, names=200)
    series = STM.width_series(acc, "liq_long")   # ширина 0.5 % — ниже оси
    storms = STM.storm_hours(series, STM.middle())
    check("тишина: бурных часов нет", storms == [], f"{storms}")
    ch = STM.apply_storm(views, storms)
    check("тишина: не изменено ни одной позиции", ch == {}, f"{len(ch)}")
    base = money(gcache, launch)
    mod = money(STM.close_storm(gcache, ch), launch)
    fields = ("n", "usd", "final", "max_dd", "day_median", "win", "taken")
    diff = [(bk, f, (base.get(bk) or {}).get(f), (mod.get(bk) or {}).get(f))
            for bk in base for f in fields
            if (base.get(bk) or {}).get(f) != (mod.get(bk) or {}).get(f)]
    check("тишина: касса бит в бит", not diff, f"{diff[:3]}")
    got = {bk: (v.get("exits") or {}) for bk, v in base.items()}
    check("тишина: охрана рынком в тесте молчит",
          all("рынок" not in e for e in got.values())
          and all(not g["guard"]["closed_by_market"] for g in guards.values()),
          f"{got}")


def test_planted_storm_closes_the_book_by_the_core_mark():
    """Подсаженный бурный час — выход ПО ОТМЕТКЕ ЯДРА в этот час.

    Первая половина калибровочной пары: подсаженное мера обязана найти.
    Без неё сломанное чтение сводок выглядит ровно как «бури не было».
    """
    cache, launch = journal(n_tail=10, n_rest=10, seed=66, stagger=False)
    gcache, views, _g = books_of(cache, launch)
    storms = storm_at(views, [1])
    ch = STM.apply_storm(views, storms)
    check("подсаженная буря: помечены все позиции", len(ch) == len(views),
          f"{len(ch)} из {len(views)}")
    mod = STM.close_storm(gcache, ch)
    bad = []
    for key, k in ch.items():
        r, old = mod[key], gcache[key]
        want = views[key]["path"]["cum"][1]
        if (k != 1 or abs(float(r["pnl"]) - float(want)) > 1e-12
                or r["exit"] != STM.EXIT_LABEL or len(r["marks"]) != 1
                or float(r["exit_ts"]) != float(old["at"]) + HOUR - 1.0
                or r["state"] != "closed"):
            bad.append((key[1], k, r["pnl"], want, r["exit"]))
    check("подсаженная буря: каждая вышла в час 1 по отметке часа 1",
          not bad, f"{bad[:2]}")
    tails = [key for key in ch if views[key]["tail"]]
    check("подсаженная буря: хвост спасён",
          tails and all(float(mod[key]["pnl"]) > float(gcache[key]["pnl"])
                        for key in tails), f"хвостовых {len(tails)}")
    base, rule = money(gcache, launch), money(mod, launch)
    moved = [bk for bk in base
             if (base[bk] or {}).get("usd") != (rule.get(bk) or {}).get("usd")]
    check("подсаженная буря: деньги книг сдвинулись",
          len(moved) == len(base), f"сдвинулось {len(moved)} из {len(base)}")


def test_closing_is_the_library_record():
    """Закрытие записи — библиотечное (`wave.guard_record`), не своё."""
    cache, launch = journal(n_tail=2, n_rest=2, seed=67)
    gcache, views, _g = books_of(cache, launch)
    key = sorted(views)[0]
    mine = STM.close_storm(gcache, {key: 2})[key]
    theirs = WV.guard_record(gcache[key], 2, why=STM.EXIT_LABEL)
    check("закрытие: запись совпадает с библиотечной", mine == theirs,
          str({k: (mine.get(k), theirs.get(k))
               for k in set(mine) | set(theirs)
               if mine.get(k) != theirs.get(k)})[:200])


# ======================================================================
# 3. База — книги С охраной рынком
# ======================================================================

def guard_market(views, pct=3.0):
    """Каталог сводок, в котором волна двадцати прокси-имён РАСТЁТ.

    Охрана рынком закрывает шорт, когда средний ход прокси-имён с входа
    ≥ порога книги. Здесь он растёт на `pct` % за час — значит охрана
    обязана сработать в первом же часе жизни каждой позиции.
    """
    root = tempfile.mkdtemp(prefix="stm-guard-")
    lo = min(SQ.hour_key(float(v["rec"]["at"]), 0) for v in views.values())
    hi = max(SQ.hour_key(float(v["rec"]["at"]), int(v["path"]["K"]) + 1)
             for v in views.values())
    rnd = random.Random(12)
    for sym in WV.PROXY:
        rows, mid = [], 100.0
        for hk in range(lo, hi + 1):
            mid *= (1.0 + pct / 100.0)
            rows.append(summary_row(hk, mid, 5e6, 5e6, 10.0, 10.0, rnd))
        d = os.path.join(root, sym)
        os.makedirs(d, exist_ok=True)
        by_day = {}
        for r in rows:
            by_day.setdefault(str(r["hour"])[:10], []).append(r)
        for day, rs in sorted(by_day.items()):
            with open(os.path.join(d, day + ".jsonl"), "w",
                      encoding="utf-8") as f:
                for r in rs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return root


def test_base_is_the_book_with_the_market_guard():
    """База — книги КАК СЕЙЧАС, то есть С охраной рынком.

    Кэш реплея хранит исход БЕЗ охраны (правило книг с 13.09). Забудь её
    применить — и буря «спасала» бы то, что охрана уже закрыла, а
    изменённых позиций насчиталось бы больше, чем их есть.
    """
    cache, launch = journal(n_tail=4, n_rest=4, seed=68, stagger=False,
                            hold=12)
    _gc0, views0, _g0 = books_of(cache, launch)          # рынок пустой
    root = guard_market(views0, pct=3.0)
    RP.market(root=root)
    packed, guards = STM.guarded_books(cache, launch)
    gcache = STM.keyed(packed)
    views = SQ.views_of(gcache, rulers=STM.BOOK_KEYS)
    closed = sum(int((g["guard"] or {}).get("closed_by_market") or 0)
                 for g in guards.values())
    check("охрана: применена и закрыла позиции", closed >= len(views0) // 2,
          f"закрыто {closed} из {len(views0)}")
    check("охрана: порог книги взят из правил",
          all(abs(float(g["guard"]["pct"]) - float(R.wave_guard_of(bk))) < 1e-9
              for bk, g in guards.items()), f"{[g['guard'].get('pct') for g in guards.values()]}")
    shorter = sum(1 for key in views
                  if int(views[key]["path"]["K"]) < int(views0[key]["path"]["K"]))
    check("охрана: часы жизни укоротились", shorter >= 1,
          f"укоротилось {shorter} из {len(views)}")
    check("охрана: исход помечен рынком",
          any((v["rec"].get("exit") or "") == R.GUARD_EXIT
              for v in views.values()),
          f"{sorted({v['rec'].get('exit') for v in views.values()})}")
    # буря после выхода охраны ничего не трогает — это и есть «поверх»
    late = set()
    for _key, v in views.items():
        at, K = float(v["rec"]["at"]), int(v["path"]["K"])
        late.add(SQ.hour_key(at, K))
    check("охрана: буря после её выхода позиций не трогает",
          STM.apply_storm(views, late) == {},
          f"{len(STM.apply_storm(views, late))}")
    empty_market()


def test_key_carries_the_book_not_the_ruler():
    """Ключ несёт КНИГУ: две книги на одной линейке — две записи.

    `optimal_h` и `aggr_h` считаются на линейке `optimal_s` и
    различаются гейтом плеча; склей их ключом линейки — и правило всей
    книги закрывало бы чужие позиции, а изменённых насчиталось бы вдвое
    меньше.
    """
    cache, launch = journal(n_tail=2, n_rest=2, seed=69, stagger=False)
    gcache, views, _g = books_of(cache, launch)
    books = sorted({key[0] for key in gcache})
    check("ключ: все три книги семейства на месте",
          books == sorted(STM.BOOK_KEYS), f"{books}")
    check("ключ: `optimal_h` и `aggr_h` не склеены",
          len([k for k in gcache if k[0] == "optimal_h"])
          == len([k for k in gcache if k[0] == "aggr_h"]) > 0,
          f"{ {b: len([k for k in gcache if k[0] == b]) for b in books} }")
    back = STM.repack(gcache)
    check("ключ: обратная укладка отдаёт те же книги",
          sorted(back) == sorted(STM.BOOK_KEYS)
          and sum(len(v) for v in back.values()) == len(gcache), f"{list(back)}")
    bb = STM.by_book(views, STM.apply_storm(views, storm_at(views, [1])))
    check("ключ: изменённые считаются по книгам",
          sorted(bb) == sorted(STM.BOOK_KEYS)
          and all(v["n"] > 0 for v in bb.values()), f"{bb}")


# ======================================================================
# 4. Контроль случайными ЧАСАМИ
# ======================================================================

def test_control_keeps_the_hour_of_day():
    """Случайные часы — с ТЕМ ЖЕ мультимножеством часа суток.

    Бурные часы кучкуются по часу суток (21:00, 03:00, 07–08:00 UTC в
    верхних строках записи). Не согласуй контроль по часу суток — и он
    отвечал бы на вопрос «бывает ли такой час суток», а не «бывает ли
    буря».
    """
    pool = {h: [h + 24 * d for d in range(20)] for h in range(24)}
    real = [3, 27, 51, 10]                       # 03:00 трижды, 10:00 раз
    import collections
    want = collections.Counter(hk % 24 for hk in real)
    bad = []
    for seed in range(20):
        hrs, why = STM.control_hours(real, pool, random.Random(seed))
        if hrs is None:
            bad.append(why)
            continue
        got = collections.Counter(hk % 24 for hk in hrs)
        if got != want or len(hrs) != len(real):
            bad.append((seed, dict(got)))
    check("контроль: час суток сохранён на всех зёрнах", not bad,
          f"{bad[:2]}")
    check("контроль: часов столько же, сколько бурь",
          len(STM.control_hours(real, pool, random.Random(1))[0]) == len(real),
          "число часов другое")
    moved = set()
    for seed in range(10):
        hrs, _w = STM.control_hours(real, pool, random.Random(seed))
        moved |= (set(hrs) - set(real))
    check("контроль: часы и правда другие", len(moved) > 3, f"{sorted(moved)[:5]}")


def test_control_refuses_when_the_pool_is_too_small():
    """Часов суток не хватило — ОТКАЗ С ПРИЧИНОЙ, а не выборка поменьше.

    Тихая замена размера сделала бы контроль слабее правила: фильтр,
    режущий число событий, сравнивается с выборкой ТОГО ЖЕ размера.
    """
    pool = {3: [3, 27]}
    hrs, why = STM.control_hours([3, 27, 51], pool, random.Random(0))
    check("контроль: выборка не выдана", hrs is None, f"{hrs}")
    check("контроль: причина названа числом",
          why and "измеримо 2" in why and "нужных 3" in why, f"{why}")
    ok, why2 = STM.control_hours([3, 27], pool, random.Random(0))
    check("контроль: ровно по размеру — выборка есть",
          ok is not None and why2 is None and len(ok) == 2, f"{ok} {why2}")


def test_hour_pool_respects_the_journal_window():
    """Пул часов ограничен сроком журнала и не берёт прочерки."""
    acc = width_of({h: 1 for h in (100, 101, 200, 201)}, names=200)
    thin = width_of({102: 1}, names=3)
    acc["hours"].update(thin["hours"])
    series = STM.width_series(acc, "liq_long")
    pool = STM.hour_pool(series, lo=100, hi=201)
    flat = sorted(x for v in pool.values() for x in v)
    check("пул: прочерк в кандидаты не идёт", 102 not in flat, f"{flat}")
    check("пул: окно журнала соблюдено",
          flat == [100, 101, 200, 201], f"{flat}")
    narrow = STM.hour_pool(series, lo=150, hi=250)
    flat2 = sorted(x for v in narrow.values() for x in v)
    check("пул: часы вне окна отброшены", flat2 == [200, 201], f"{flat2}")


def test_control_storm_runs_the_same_road_as_the_rule():
    """Контроль считается ТОЙ ЖЕ дорогой: закрытие книги, та же касса."""
    cache, launch = journal(n_tail=3, n_rest=5, seed=70, stagger=True)
    gcache, views, _g = books_of(cache, launch)
    real = sorted(storm_at(views, [2]))
    pool = {h: sorted({hk for hk in range(min(real) - 48, max(real) + 48)
                       if hk % 24 == h}) for h in range(24)}
    empty_market()
    ctl = STM.control_storm(gcache, views, real, pool, None, launch, seeds=4,
                            log=lambda *a: None)
    check("контроль: зёрен посчитано столько, сколько просили",
          ctl["seeds"] == 4 and ctl["no_draw"] == 0, f"{ctl['seeds']}")
    check("контроль: у каждой книги свой ряд",
          sorted(ctl["books"]) == sorted(STM.BOOK_KEYS)
          and all(len(v) == 4 for v in ctl["books"].values()),
          f"{ {k: len(v) for k, v in ctl['books'].items()} }")
    check("контроль: Σ долей маржи посчитана на каждом зерне",
          len(ctl["sum"]) == 4 and len(ctl["n"]) == 4, f"{ctl['sum']}")
    check("контроль: зёрна дают РАЗНЫЕ выборки",
          len(set(ctl["n"])) > 1 or len(set(round(x, 6) for x in ctl["sum"])) > 1,
          f"{ctl['n']} {ctl['sum']}")


# ======================================================================
# 5. Диагностика
# ======================================================================

def test_shifted_series_moves_the_positions():
    """Ряд ширины, сдвинутый на сутки, даёт ДРУГОЕ множество позиций.

    Совпадение означало бы, что правило метит состав журнала, а не
    событие: диагностика, которая обязана кусаться сама.
    """
    cache, launch = journal(n_tail=4, n_rest=4, seed=71, stagger=False,
                            hold=24)
    _gc, views, _g = books_of(cache, launch)
    hk = SQ.hour_key(BASE_TS, 2)
    acc = width_of({hk: 6}, names=200)           # ширина 3 %
    series = STM.width_series(acc, "liq_long")
    storms = STM.storm_hours(series, 0.02)
    ch = STM.apply_storm(views, storms)
    sh = STM.shifted(series, STM.SHIFT_H)
    check("сдвиг: часы сдвинулись ровно на сутки",
          sorted(sh) == [h + 24 for h in sorted(series)], "сдвиг не тот")
    ch_sh = STM.apply_storm(views, STM.storm_hours(sh, 0.02))
    check("сдвиг: множество изменённых позиций другое",
          ch and ch != ch_sh,
          f"правило {len(ch)}, сдвиг {len(ch_sh)}, общих "
          f"{len(set(ch) & set(ch_sh))}")


def test_quiet_share_is_a_dash_without_a_wave():
    """Волна не измерена — ПРОЧЕРК, а не «рынок стоял»."""
    q = STM.quiet_share([None, None])
    check("слепота охраны: без волны — прочерк",
          q["share"] is None and q["missing"] == 2 and q["n"] == 0, f"{q}")
    q2 = STM.quiet_share([0.001, -0.004, 0.03, None])
    check("слепота охраны: доля считается по измеренным",
          abs(q2["share"] - 2.0 / 3.0) < 1e-12 and q2["missing"] == 1, f"{q2}")


def test_cover_separates_none_from_partial():
    """Покрытие различает «ни одного часа», «часть» и «все»."""
    cache, launch = journal(n_tail=2, n_rest=2, seed=72, stagger=True)
    _gc, views, _g = books_of(cache, launch)
    all_hours = set()
    for v in views.values():
        all_hours |= set(STM.hours_of(v))
    full = STM.cover_of(views, {hk: 0.001 for hk in all_hours})
    check("покрытие: полное — доля 1.0", full["share"] == 1.0, f"{full}")
    key = sorted(views)[0]
    hs = sorted(STM.hours_of(views[key]))
    cut = {hk: 0.001 for hk in all_hours}
    for hk in hs:
        cut[hk] = None
    c = STM.cover_of(views, cut)
    check("покрытие: позиции без единого часа сосчитаны",
          c["none"] >= 1 and c["share"] < 1.0, f"{c}")
    check("покрытие: часы считаются отдельно от позиций",
          c["hours_measured"] < c["hours"] and c["hours_share"] is not None,
          f"{c}")


def test_before_worst_is_the_parent_diagnostic():
    """«Раньше худшей отметки» — диагностика РОДИТЕЛЯ, не своя копия."""
    at = BASE_TS
    rec = record("STM900USDT", at, [-0.05, -0.30, 0.10, 0.05], exit_="пол")
    v = {"rec": rec, "path": WV.path_of(rec), "tail": True}
    views = {("safe_h", "STM900USDT", at): v}
    check("диагностика: час худшей отметки найден",
          SQ.worst_hour(v["path"]) == 2, f"{SQ.worst_hour(v['path'])}")
    early = SQ.before_worst(views, {("safe_h", "STM900USDT", at): 1})
    same = SQ.before_worst(views, {("safe_h", "STM900USDT", at): 2})
    check("диагностика: час раньше — начало хода",
          early["share"] == 1.0 and early["early"] == 1, f"{early}")
    check("диагностика: тот же час — кульминация, а не начало",
          same["share"] == 0.0 and same["same"] == 1, f"{same}")
    none = SQ.before_worst({("safe_h", "x", 1.0): {"rec": rec, "path": None,
                                                   "tail": False}},
                           {("safe_h", "x", 1.0): 1})
    check("диагностика: без хвоста — прочерк, а не ноль",
          none["share"] is None, f"{none}")


# ======================================================================
# 6. Вердикт и показ
# ======================================================================

def _art(**over):
    """Артефакт, у которого пройдены ВСЕ убийцы, — основа для подмен."""
    books = list(STM.BOOK_KEYS)
    cell = {"q": 0.02, "storms": 27, "storm_days": 13,
            "by_book": {bk: {"n": 120, "tails": 30, "positions": 900}
                        for bk in books},
            "beat": {bk: {"final": 0.02, "ratio": 0.03} for bk in books},
            "tails": {bk: {"base": 100, "rule": 70} for bk in books},
            "wo3": {bk: {"base": 100.0, "rule": 400.0} for bk in books},
            "days": {bk: {"better": 8, "worse": 5} for bk in books},
            "diag": {"n": 30, "early": 21, "same": 5, "late": 4, "share": 0.7},
            "control": {"seeds": 200, "sum": [1.0], "why": None},
            "quiet": {"n": 27, "quiet": 14, "share": 0.52, "missing": 0},
            "delta": {"n": 360, "tails": 90, "sum": 3.5, "cut_worse": 40}}
    art = {"axis": [0.01, 0.02, 0.03], "judged": 0.02, "books": books,
           "dep": 10000, "seeds": 200, "n": 2000, "open_skipped": 3,
           "side": {"ok": True, "why": "доля долларов Buy в падениях 0.804",
                    "mark_short": "Sell", "field_short": "liq_long",
                    "share_down": {"Buy": 0.804, "Sell": 0.144},
                    "usd_down": {"Buy": 3.0e8, "Sell": 7.2e7},
                    "usd_up": {"Buy": 7.3e7, "Sell": 4.3e8}},
           "width": {"hours": 1149, "measurable": 1148, "unmeasurable": 1,
                     "median": 0.00279, "p90": 0.00918, "p95": 0.01238,
                     "p99": 0.03067, "max": 0.21674},
           "cover": {"n": 2000, "full": 1900, "share": 0.95, "hours": 40000,
                     "hours_measured": 39000, "hours_share": 0.975,
                     "no_hours": 10, "part": 80, "none": 20},
           "cells": [cell], "base": {}, "computed_at": "2026-09-20 00:00"}
    for k, v in over.items():
        art[k] = v
    return art


def _state(art, key):
    for r in STM.verdict(art):
        if r["key"] == key:
            return r["state"]
    return None


def test_verdict_is_derived_from_the_numbers():
    """Каждая строка вердикта следует из своего числа, а не из мнения."""
    ok = _art()
    check("вердикт: всё пройдено",
          all(r["state"] == "пройдено" for r in STM.verdict(ok)),
          f"{[(r['key'], r['state']) for r in STM.verdict(ok)]}")
    check("вердикт: фраза итога говорит о пройденном",
          "убийцы пройдены" in STM.reading(ok), STM.reading(ok)[:120])

    a = _art()
    a["side"] = {"ok": False, "why": "доля 0.51 внутри полосы"}
    check("вердикт: сторона не измерена — блок", _state(a, "сторона") == "блок",
          f"{_state(a, 'сторона')}")
    check("вердикт: после блока стороны ничего не судится",
          len(STM.verdict(a)) == 1, f"{len(STM.verdict(a))}")

    m = _art()
    m["width"] = dict(m["width"], measurable=0, unmeasurable=1149)
    check("вердикт: измеримых часов нет — блок",
          _state(m, "измеримость") == "блок", f"{_state(m, 'измеримость')}")
    check("вердикт: сказано об отсутствии МЕРЫ, а не бури",
          "отсутствие меры" in STM.reading(m), STM.reading(m)[:200])

    b = _art()
    b["cover"] = dict(b["cover"], share=0.4)
    check("вердикт: покрытие ниже половины — блок",
          _state(b, "покрытие") == "блок", f"{_state(b, 'покрытие')}")
    b2 = _art()
    b2["cover"] = dict(b2["cover"], share=0.7)
    check("вердикт: покрытие 50–90 % — оговорка",
          _state(b2, "покрытие") == "оговорка", f"{_state(b2, 'покрытие')}")

    c = _art()
    c["cells"][0]["beat"] = {"safe_h": {"final": 0.5},
                             "optimal_h": {"final": 0.4},
                             "aggr_h": {"final": 0.01}}
    check("вердикт: контроль не пройден — убивает",
          _state(c, "контроль") == "убивает", f"{_state(c, 'контроль')}")

    s3 = _art()
    s3["cells"][0]["control"] = {"seeds": 3, "why": None}
    check("вердикт: контроль на трёх зёрнах не судит",
          _state(s3, "контроль") == "нечем судить", f"{_state(s3, 'контроль')}")
    check("вердикт: смоук назван смоуком",
          "смоук ДОРОГИ" in STM.reading(s3), STM.reading(s3)[:200])

    e = _art()
    e["cells"][0]["wo3"] = {bk: {"base": 400.0, "rule": 100.0}
                            for bk in e["books"]}
    check("вердикт: без трёх лучших дней не выросло — убивает",
          _state(e, "концентрация") == "убивает",
          f"{_state(e, 'концентрация')}")

    f = _art()
    f["cells"][0]["diag"] = {"n": 30, "early": 9, "same": 10, "late": 11,
                             "share": 0.3}
    check("вердикт: буря есть кульминация — убивает",
          _state(f, "механизм") == "убивает", f"{_state(f, 'механизм')}")
    check("вердикт: кульминация названа в итоге",
          "КУЛЬМИНАЦИЯ" in STM.reading(f), STM.reading(f)[:200])

    g = _art()
    g["cells"][0]["diag"] = {"n": 0, "early": 0, "same": 0, "late": 0,
                             "share": None}
    check("вердикт: доля не измерена — не измерено, а не ноль",
          _state(g, "механизм") == "не измерено", f"{_state(g, 'механизм')}")


def test_thin_change_is_the_guard_already_covering():
    """Меньше 30 изменённых на книгу — «охрана уже покрывает».

    Это РЕЗУЛЬТАТ, а не сбой: судить нечем, и правило «не работает»
    отсюда не следует.
    """
    a = _art()
    a["cells"][0]["by_book"] = {bk: {"n": 7, "tails": 2, "positions": 900}
                                for bk in a["books"]}
    check("объём: состояние «нечем судить»",
          _state(a, "объём") == "нечем судить", f"{_state(a, 'объём')}")
    check("объём: сказано, что охрана уже покрывает",
          "охрана рынком уже покрывает" in STM.reading(a),
          STM.reading(a)[:200])
    check("объём: деньги дальше не судятся",
          all(r["key"] not in ("контроль", "концентрация")
              for r in STM.verdict(a)),
          f"{[r['key'] for r in STM.verdict(a)]}")
    check("объём: порог объявлен числом", STM.MIN_CHANGED == 30,
          f"{STM.MIN_CHANGED}")


def test_report_prints_a_dash_and_the_derived_phrase():
    """Величины, которой нет, — прочерк; фраза итога — из числа."""
    a = _art()
    a["cells"][0]["beat"] = {bk: {"final": None, "ratio": None}
                             for bk in a["books"]}
    a["cells"][0]["control"] = {"seeds": 200, "sum": [], "why": None}
    a["verdict"] = STM.verdict(a)
    txt = STM.report(a)
    check("показ: прочерк вместо ноля", "—" in txt, "прочерков нет")
    check("показ: фраза итога совпадает с выведенной",
          STM.reading(a) in txt, STM.reading(a)[:80])
    check("показ: судимая ячейка помечена жирным",
          "| **2.0 %** |" in txt, "судимая ячейка не выделена")
    f = _art()
    f["cells"][0]["diag"] = {"n": 30, "early": 9, "same": 10, "late": 11,
                             "share": 0.3}
    f["verdict"] = STM.verdict(f)
    check("показ: вердикт в отчёте тот же, что в числах",
          "убивает" in STM.report(f), "вердикт не напечатан")
    err = STM.report({"error": "кэш реплея непригоден"})
    check("показ: не посчитано — сказано прямо",
          "Не посчитано" in err, err[:120])


def test_empty_read_is_a_refusal_not_a_report():
    """Ноль строк при непустом каталоге — ОТКАЗ, а не отчёт с прочерками."""
    raised = None
    try:
        SQ.refuse_if_empty(778, {"rows": 0}, root="/нет/такого")
    except SystemExit as e:
        raised = str(e)
    check("пустота: отказ поднят", raised is not None, "отказа нет")
    check("пустота: причина названа сломанным чтением",
          raised and "сломанное чтение" in raised, str(raised)[:160])
    quiet_ok = True
    try:
        SQ.refuse_if_empty(778, {"rows": 811990}, root="x")
        SQ.refuse_if_empty(0, {"rows": 0}, root="x")
    except SystemExit:
        quiet_ok = False
    check("пустота: на живой записи отказа нет", quiet_ok, "лишний отказ")


def test_modules_come_from_where_they_should():
    """Чужой модуль под знакомым именем — отказ, а не работа."""
    check("ядра: волна из dca_paper",
          STM.U.module_origin(STM.WV) == "dca_paper",
          STM.U.module_origin(STM.WV))
    check("ядра: касса из dca_paper",
          STM.U.module_origin(STM.AG) == "dca_paper",
          STM.U.module_origin(STM.AG))
    check("ядра: родитель из mech_357a7c60",
          STM.U.module_origin(STM.SQ) == "mech_357a7c60",
          STM.U.module_origin(STM.SQ))
    check("прогон: своего ядра денег не завёл",
          RUN.STM is STM and RUN.AG is STM.AG, "прогон считает своим")


def main():
    print("механика bb7c3581 — буря выкупа шортов по рынку\n")
    for title, tests in (
            ("ширина по календарному часу",
             (test_mark_is_the_parent_judged_cell,
              test_width_is_a_dash_below_min_names,
              test_width_counts_only_marked_names,
              test_unmeasured_hour_is_never_a_storm,
              test_storm_hours_need_the_declared_width,
              test_swapped_columns_change_the_storm_hours,
              test_rows_without_liquidations_are_a_dash_not_zero,
              test_width_does_not_double_count_a_name)),
            ("правило всей книги",
             (test_rule_closes_every_open_short_in_the_storm_hour,
              test_first_storm_hour_wins,
              test_rule_never_touches_the_exit_hour,
              test_future_does_not_move_the_past,
              test_no_storm_reproduces_the_base_bit_for_bit,
              test_planted_storm_closes_the_book_by_the_core_mark,
              test_closing_is_the_library_record)),
            ("база — книги с охраной рынком",
             (test_base_is_the_book_with_the_market_guard,
              test_key_carries_the_book_not_the_ruler)),
            ("контроль случайными часами",
             (test_control_keeps_the_hour_of_day,
              test_control_refuses_when_the_pool_is_too_small,
              test_hour_pool_respects_the_journal_window,
              test_control_storm_runs_the_same_road_as_the_rule)),
            ("диагностика",
             (test_shifted_series_moves_the_positions,
              test_quiet_share_is_a_dash_without_a_wave,
              test_cover_separates_none_from_partial,
              test_before_worst_is_the_parent_diagnostic)),
            ("вердикт и показ",
             (test_verdict_is_derived_from_the_numbers,
              test_thin_change_is_the_guard_already_covering,
              test_report_prints_a_dash_and_the_derived_phrase,
              test_empty_read_is_a_refusal_not_a_report,
              test_modules_come_from_where_they_should))):
        print(title)
        for fn in tests:
            run_test(fn)
    print()
    if FAILED:
        # Каждое падение — СВОЕЙ строкой со словом ПАДЕНИЕ, и сводка стоит
        # в самом конце. Приёмка (`runlog.check_build`) читает последние
        # 4000 символов и ищет в них обещанную строку: имя проверки без
        # этого слова нашлось бы и в строке «ok», то есть холостой
        # контроль объявлялся бы кусающимся.
        print(f"ПАДЕНИЙ: {len(FAILED)}")
        for name in FAILED:
            print(f"ПАДЕНИЕ {name}")
        raise SystemExit(1)
    print(f"все проверки прошли ({CHECKS[0]})")


if __name__ == "__main__":
    main()
