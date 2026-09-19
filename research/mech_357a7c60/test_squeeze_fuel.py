#!/usr/bin/env python3
"""
Тесты механики 357a7c60 — топливо сквиза по ходу позиции.

Четыре места, где легче всего соврать себе в свою пользу, и каждое
закрыто синтетикой с известным заранее ответом.

**Заглядывание в будущее.** Правило решает, выходить ли из позиции в
часе k, и если оно заглянет хоть в один час ПОСЛЕ фактического выхода,
находка будет неотличима от находки. Проверяется прямо: будущее
переписывается всплесками целиком, прошлое обязано не шелохнуться.

**Сама мера.** Сломанное чтение потока и перевёрнутая сторона выглядят
ровно как «эффекта нет» — в этом проекте так дважды печатался нулевой
отчёт. Поэтому калибровочная пара: подсаженный в хвост поток мера
обязана найти, а на потоке без связи с именем — промолчать, и сказать
это тем же контролем (перемешиванием между именами), которым будет
судить живые числа.

**Сторона.** Колонки сводки названы, судя по записи, наоборот. Механика
обязана быть верна при ЛЮБОМ имени колонки: переставь колонки местами —
калибровка назовёт другую метку и придёт к тому же физическому потоку,
а множество помеченных позиций не сдвинется. Модуль, читающий колонку
по имени, на этом тесте падает.

**Пустота и вердикт.** Ноль строк при непустом каталоге — отказ, а не
отчёт с прочерками; величина, которой нет, — прочерк, а не ноль; фраза
итога выводится из числа, а не стоит рядом с ним.

Деньги считаются НАСТОЯЩЕЙ кассой семейства (`agree_book.stats_of`) на
подставном журнале: подделка обязана выглядеть живой — поля живого
писателя, дрожание, живые даты, живой масштаб. Рынок при этом уводится
в пустой каталог: охрана рынком — чужое правило, и тест, зависящий от
сегодняшней записи стакана, менял бы ответ сам собой.

    python3 research/mech_357a7c60/test_squeeze_fuel.py
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
           os.path.join(RESEARCH, "mech_d71203f0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agree_book as AG                                      # noqa: E402
import path_screen as P                                      # noqa: E402
import run_paper as RP                                       # noqa: E402
import squeeze_fuel as SQ                                    # noqa: E402
import run_squeeze as RUN                                    # noqa: E402

FAILED = []
CHECKS = [0]
HOUR = 3600.0
# Живые даты, но ДО начала записи сводок (01.08.2026): журнал подставной,
# и рынок ему взять неоткуда — см. `empty_market`.
BASE_TS = 1778000000.0 - 1778000000.0 % HOUR


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
    сводки падений не печатается вовсе — снаружи это неотличимо от «их
    не было». Приёмка фабрики (`runlog._run_tests`) читает ПОСЛЕДНИЕ
    4000 символов и по сводке судит, какой контроль укусил; оборванная
    сюита оставляет в хвосте трассировку вместо имени, и кусающийся
    контроль объявляется холостым (урок постройки d71203f0 12.09).
    """
    try:
        fn()
    except BaseException as e:                               # noqa: BLE001
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
    j = lambda a, b: rnd.uniform(a, b)                       # noqa: E731
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
        row["liq_short"] = round(liq_buy, 2)                 # доллары метки Buy
        row["liq_long"] = round(liq_sell, 2)                 # доллары метки Sell
    for b in ("b0.0005", "b0.001", "a0.0005", "a0.001"):
        row[f"bq_{b}"] = None
        row[f"cov_{b}"] = 0.0
    return row


class FakeHours:
    """`wave.Hours` на словаре: {(имя, номер часа): строка сводки}."""

    def __init__(self, rows):
        self.rows = dict(rows)
        self.hit = self.miss = 0

    def row(self, sym, ts):
        r = self.rows.get((sym, int(float(ts) // HOUR)))
        if r is None:
            self.miss += 1
        else:
            self.hit += 1
        return r


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


def journal(n_tail=12, n_rest=28, seed=11, stagger=True, rulers=("safe_s",)):
    """Подставной журнал: хвост (пол) и обычные сделки, с дрожанием."""
    rnd = random.Random(seed)
    cache, launch = {}, {}
    i = 0
    for ruler in rulers:
        for tail in (True, False):
            for j in range(n_tail if tail else n_rest):
                sym = f"SQZ{i:03d}USDT"
                i += 1
                launch[sym] = BASE_TS - rnd.uniform(30, 400) * 86400
                at = BASE_TS + ((j % 12) * 6 * HOUR if stagger else 0.0)
                K = rnd.choice([8, 12, 18, 24])
                marks = []
                for k in range(K):
                    marks.append(round(rnd.uniform(-0.06, 0.05), 6))
                if tail:
                    marks[-1] = round(-0.55 - rnd.uniform(0.0, 0.2)
                                      - sum(marks[:-1]), 6)
                cache[(ruler, sym, at)] = record(
                    sym, at, marks, exit_=("пол" if tail else "срок"),
                    rnd=rnd, ruler=ruler)
    return cache, launch


def quiet_cells(views, usd=100.0, turn=1e6):
    """Поток, которого почти нет: доля 0.01 % — ниже любой ячейки оси."""
    cells = {}
    for _key, v in views.items():
        rec = v["rec"]
        for k in SQ.live_hours(v):
            cells[(rec["sym"], SQ.hour_key(float(rec["at"]), k))] = (usd, turn)
    return cells


def plant(cells, views, hour=1, usd=50000.0, turn=1e6, only_tails=True):
    """Подсадить всплеск в час `hour` у хвостовых позиций."""
    out = dict(cells)
    hit = []
    for key, v in views.items():
        if only_tails and not v["tail"]:
            continue
        if hour not in SQ.live_hours(v):
            continue
        rec = v["rec"]
        out[(rec["sym"], SQ.hour_key(float(rec["at"]), hour))] = (usd, turn)
        hit.append(key)
    return out, hit


_EMPTY = {}


def empty_market():
    """Увести рынок книг в ПУСТОЙ каталог сводок.

    `run_paper.guard_shorts` (охрана рынком — чужое правило, живущее
    внутри кассы) берёт волну из глобального `_MARKET`. Оставь его на
    настоящем каталоге — и деньги подставного журнала зависели бы от
    того, что сегодня записал сборщик. Тест обязан отвечать одно и то
    же; поэтому рынок пуст, а отсутствие выходов «рынок» проверяется
    отдельным утверждением.
    """
    if "dir" not in _EMPTY:
        _EMPTY["dir"] = tempfile.mkdtemp(prefix="sqz-empty-")
    RP.market(root=_EMPTY["dir"])
    return _EMPTY["dir"]


def money(cache, launch, dep=None):
    """Деньги книг настоящей кассой; издержки не применяются намеренно.

    `ctx=None` — круг издержек у кассы свой и проверен своими тестами
    (`dca_paper/test_costs.py`); здесь проверяется ДОРОГА: кто вышел, в
    каком часу и по какой отметке. Смешав две проверки, мы получили бы
    тест, чьё имя обещает больше, чем он исполняет.
    """
    empty_market()
    return AG.stats_of(AG.packed_short(cache), None, launch, RUN.BOOK_KEYS,
                       deps=[dep or RUN.MAIN_DEP])


def calib_stream(days=8, names=6, seed=5, swap=False, half_swap=False,
                 flip_at=None, scale=1.0, liq=True, blur=0.0):
    """Поток сводок, в котором ШОРТОВ выбивает рост, а лонгов — падение.

    Метка `Buy` кладётся живым писателем в колонку `liq_short`. В этой
    подделке `Buy` горит в часах ПАДЕНИЯ (то есть маркирует лонга —
    ровно как на нынешней записи площадки), `Sell` — в часах роста.
    `swap` меняет содержимое колонок местами, `half_swap` — у половины
    строк, `flip_at` переворачивает сутки с номера, `blur` подмешивает
    `Buy` и в часы РОСТА (доля метки в падениях ползёт к половине, а
    кросс-сравнение меток остаётся уверенным — случай, который ловит
    только объявленная полоса).
    """
    rnd = random.Random(seed)
    start = int(BASE_TS // HOUR)
    out = []
    for n in range(names):
        sym = f"CAL{n:02d}USDT"
        rows, mid = [], 1.0 + n
        for d in range(days):
            for h in range(24):
                idx = start + d * 24 + h
                up = ((h + n) % 2 == 0)
                mid = mid * (1.02 if up else 0.98)
                lb = ((rnd.uniform(3e4, 9e4) * blur if up
                       else rnd.uniform(3e4, 9e4))) * scale
                ls = (rnd.uniform(3e4, 9e4) if up else 0.0) * scale
                if flip_at is not None and d >= flip_at:
                    lb, ls = ls, lb
                if swap or (half_swap and (idx % 2 == 0)):
                    lb, ls = ls, lb
                rows.append(summary_row(idx, mid, rnd.uniform(1e6, 9e6),
                                        rnd.uniform(1e6, 9e6), lb, ls, rnd,
                                        liq=liq))
        out.append((sym, rows))
    return out


# ======================================================================
# 1. Сторона решается данными
# ======================================================================

def test_side_is_decided_by_data():
    """Метка, чьи доллары лежат в падениях, — ЛОНГ; вторая — наш шорт."""
    s = SQ.calibrate(calib_stream())
    check("сторона: решение принято", s["ok"], s.get("why"))
    check("сторона: лонга маркирует Buy", s["mark_long"] == "Buy",
          f"{s['mark_long']}")
    check("сторона: выкуп шортов маркирует Sell", s["mark_short"] == "Sell",
          f"{s['mark_short']}")
    check("сторона: поток лежит в колонке liq_long",
          s["field_short"] == "liq_long", f"{s['field_short']}")
    check("сторона: доля Buy в падениях больше 0.6",
          s["share_down"]["Buy"] > 0.6, f"{s['share_down']}")


def test_side_survives_swapped_columns():
    """Колонки переставлены — метка ДРУГАЯ, поток ТОТ ЖЕ.

    Это и есть «механика верна при любом имени колонки». Модуль,
    читающий колонку по имени, назовёт ту же метку и уедет на чужой
    поток; модуль, читающий данными, назовёт другую метку и придёт к
    тому же физическому потоку — а значит к тем же помеченным позициям.
    """
    a = SQ.calibrate(calib_stream())
    b = SQ.calibrate(calib_stream(swap=True))
    check("переставленные колонки: обе калибровки состоялись",
          a["ok"] and b["ok"], f"{a.get('why')} | {b.get('why')}")
    check("переставленные колонки: метка перевернулась",
          a["mark_short"] != b["mark_short"],
          f"{a['mark_short']} и {b['mark_short']}")
    check("переставленные колонки: колонка потока другая",
          a["field_short"] != b["field_short"],
          f"{a['field_short']} и {b['field_short']}")

    # тот же физический поток — значит те же помеченные часы
    rnd = random.Random(3)
    idx = int(BASE_TS // HOUR)
    rows = [summary_row(idx + h, 1.0, 5e6, 5e6,
                        (4e4 if h in (2, 5) else 10.0),
                        (7e4 if h in (3, 9) else 10.0), rnd)
            for h in range(12)]
    swapped = []
    for r in rows:
        r2 = dict(r)
        r2["liq_short"], r2["liq_long"] = r["liq_long"], r["liq_short"]
        swapped.append(r2)
    hit_a = [h for h, r in enumerate(rows)
             if SQ.flow_of(r, a["field_short"])[0] >= 1000.0]
    hit_b = [h for h, r in enumerate(swapped)
             if SQ.flow_of(r, b["field_short"])[0] >= 1000.0]
    check("переставленные колонки: помеченные часы те же",
          hit_a == hit_b == [3, 9], f"{hit_a} и {hit_b}")


def test_side_refuses_inside_the_band():
    """Доля внутри полосы 0.4–0.6 — ОТКАЗ, а не выбор наугад.

    Две записи, и вторая важнее. В первой стороны перемешаны пополам, и
    отказ даёт уже ядро. Во второй `Buy` горит и в падениях, и в росте
    (доля в падениях ≈ 0.56), а `Sell` — только в росте: КРОСС-сравнение
    меток здесь уверенное, и ядро назвало бы сторону. Ловит такую запись
    только объявленная полоса — то есть именно она, а не ядро, стоит
    между нами и угаданным знаком.
    """
    s = SQ.calibrate(calib_stream(half_swap=True))
    check("полоса: сторона не выбрана", not s["ok"], f"{s.get('mark_short')}")
    b = SQ.calibrate(calib_stream(blur=0.8))
    check("полоса: размытая метка не принята", not b["ok"],
          f"{b.get('mark_short')} при долях {b.get('share_down')}")
    check("полоса: причина названа полосой",
          "полос" in str(b.get("why")), str(b.get("why"))[:160])


def test_side_refuses_when_halves_disagree():
    """Сторона, разная на половинах записи, — уже не кодировка площадки.

    Запись подделана так, что ПО ВСЕЙ ей сторона решается уверенно
    (доля 0.75), а на второй половине разъезжается: без проверки половин
    такая запись прошла бы как измеренная.
    """
    s = SQ.calibrate(calib_stream(days=8, flip_at=6))
    whole = SQ.decide_side({m: {"down": s["usd_down"][m], "up": s["usd_up"][m]}
                            for m in SQ.MARK_COLUMN})
    check("половины: по всей записи сторона решалась бы", whole["ok"],
          str(whole.get("why"))[:120])
    check("половины: сторона не принята", not s["ok"], f"{s.get('mark_short')}")
    check("половины: причина названа половинами",
          "полов" in str(s.get("why")) or "половин" in str(s.get("why")),
          str(s.get("why"))[:160])


def test_side_needs_dollars_to_be_measured():
    """Долларов меньше пола — НЕ ИЗМЕРЕНО, а не «поровну».

    Запись подделана уверенной по форме (весь `Buy` в падениях), но
    тощей по деньгам: полторы тысячи долларов за двое суток. Без пола
    такая запись прошла бы как измеренная.
    """
    s = SQ.calibrate(calib_stream(days=2, names=1, scale=0.001))
    check("пол калибровки: сторона не принята", not s["ok"],
          f"{s.get('mark_short')}")
    check("пол калибровки: сказано «НЕ ИЗМЕРЕНА»",
          "НЕ ИЗМЕРЕН" in str(s.get("why")), str(s.get("why"))[:160])


def test_unmeasured_hours_are_not_a_move():
    """Час без полей ликвидаций не даёт ни хода, ни долларов."""
    s = SQ.calibrate(calib_stream(days=2, names=2, liq=False))
    check("час без опроса метрик: сторона не измерена", not s["ok"],
          f"{s.get('mark_short')}")
    check("час без опроса метрик: сосчитан отдельным числом",
          s["unmeasured"] == s["rows"] and s["rows"] > 0,
          f"{s.get('unmeasured')} из {s.get('rows')}")


def test_gap_hours_do_not_make_a_move():
    """Сосед берётся во ВРЕМЕНИ: через дыру хода не бывает."""
    rnd = random.Random(2)
    idx = int(BASE_TS // HOUR)
    rows = [summary_row(idx, 1.0, 5e6, 5e6, 1e4, 1e4, rnd),
            summary_row(idx + 5, 2.0, 5e6, 5e6, 9e9, 10.0, rnd)]
    acc = SQ.fold_calib(rows)
    check("дыра: ход через пропуск не считается",
          acc["gap"] == 1 and acc["hours"]["up"] == 0,
          f"дыр {acc['gap']}, ростов {acc['hours']['up']}")
    check("дыра: доллары через пропуск не копятся",
          acc["usd"]["Buy"]["up"] == 0.0, f"{acc['usd']}")


# ======================================================================
# 2. Метка часа
# ======================================================================

def _one_view(K=10, exit_="пол"):
    at = BASE_TS
    rec = record("SQZ000USDT", at, [-0.02] * (K - 1) + [-0.5], exit_=exit_)
    return {"rec": rec, "path": SQ.WV.path_of(rec), "tail": exit_ == "пол"}


def test_rule_needs_both_share_and_floor():
    """Доля И пол в долларах — оба, иначе правило метит тишину."""
    v = _one_view()
    at = float(v["rec"]["at"])
    sym = v["rec"]["sym"]
    base = {(sym, SQ.hour_key(at, k)): (100.0, 1e6) for k in SQ.live_hours(v)}
    only_share = dict(base)
    only_share[(sym, SQ.hour_key(at, 3))] = (500.0, 1e4)      # доля 5 %, $500
    k, _st = SQ.marked_hour(v, only_share, 0.01)
    check("правило: доля без пола в долларах не метит", k is None, f"{k}")
    only_usd = dict(base)
    only_usd[(sym, SQ.hour_key(at, 3))] = (5000.0, 1e9)       # $5000, доля 0.0005 %
    k, _st = SQ.marked_hour(v, only_usd, 0.01)
    check("правило: пол без доли не метит", k is None, f"{k}")
    both = dict(base)
    both[(sym, SQ.hour_key(at, 4))] = (30000.0, 1e6)          # доля 3 %, $30 000
    k, _st = SQ.marked_hour(v, both, 0.01)
    check("правило: доля и пол вместе метят час 4", k == 4, f"{k}")

    # час выхода и доля помеченных часов обязаны спрашивать ОДНО правило
    views = {("safe_s", sym, at): v}
    ms = SQ.marked_share(views, both, 0.01)
    check("правило: доля помеченных часов считает тем же правилом",
          ms["hours_marked"] == 1
          and ms["hours_measured"] == len(SQ.live_hours(v)), f"{ms}")
    check("правило: на тишине помеченных часов ноль",
          SQ.marked_share(views, base, 0.01)["hours_marked"] == 0,
          f"{SQ.marked_share(views, base, 0.01)}")


def test_first_marked_hour_wins():
    """Помечается ПЕРВЫЙ подходящий час, а не лучший."""
    v = _one_view()
    at, sym = float(v["rec"]["at"]), v["rec"]["sym"]
    cells = {(sym, SQ.hour_key(at, k)): (100.0, 1e6) for k in SQ.live_hours(v)}
    cells[(sym, SQ.hour_key(at, 2))] = (20000.0, 1e6)
    cells[(sym, SQ.hour_key(at, 7))] = (90000.0, 1e6)
    k, _st = SQ.marked_hour(v, cells, 0.01)
    check("первый помеченный час", k == 2, f"{k}")


def test_missing_hour_is_a_dash_not_zero():
    """Час без сводки не метится, не обнуляется и СЧИТАЕТСЯ прочерком."""
    v = _one_view()
    at, sym = float(v["rec"]["at"]), v["rec"]["sym"]
    cells = {(sym, SQ.hour_key(at, k)): (100.0, 1e6)
             for k in SQ.live_hours(v) if k != 3}
    k, st = SQ.marked_hour(v, cells, 0.01)
    check("прочерк: час без сводки не метит", k is None, f"{k}")
    check("прочерк: сосчитан отдельно",
          st["missing"] == 1 and st["measured"] == len(SQ.live_hours(v)) - 1,
          f"{st}")
    row_none = SQ.flow_of(None, "liq_long")
    rnd = random.Random(1)
    row_noliq = summary_row(1, 1.0, 5e6, 5e6, 0, 0, rnd, liq=False)
    check("прочерк: сводки нет — (None, None)", row_none == (None, None),
          f"{row_none}")
    check("прочерк: полей ликвидаций нет — (None, None)",
          SQ.flow_of(row_noliq, "liq_long") == (None, None),
          f"{SQ.flow_of(row_noliq, 'liq_long')}")


def test_coverage_separates_none_from_partial():
    """Покрытие различает «ни одного часа», «часть» и «все»."""
    cache, _launch = journal(n_tail=2, n_rest=2, seed=4)
    views = SQ.views_of(cache)
    cells = quiet_cells(views)
    full = SQ.coverage(views, cells)
    check("покрытие: полное — доля 1.0", full["share"] == 1.0, f"{full}")
    keys = sorted(views)
    v0 = views[keys[0]]
    cut = dict(cells)
    for k in SQ.live_hours(v0):
        cut.pop((v0["rec"]["sym"], SQ.hour_key(float(v0["rec"]["at"]), k)), None)
    v1 = views[keys[1]]
    cut.pop((v1["rec"]["sym"], SQ.hour_key(float(v1["rec"]["at"]), 2)), None)
    c = SQ.coverage(views, cut)
    check("покрытие: одна позиция без единого часа", c["none"] == 1, f"{c}")
    check("покрытие: одна позиция с частью часов", c["part"] == 1, f"{c}")
    check("покрытие: доля полных упала",
          c["share"] < full["share"], f"{c['share']}")


# ======================================================================
# 3. Заглядывание в будущее
# ======================================================================

def test_future_does_not_move_the_past():
    """Переписать будущее — прошлое обязано не шелохнуться.

    Правило смотрит часы СТРОГО до фактического выхода. Всплеск в часе,
    когда позиция уже закрыта ядром, не вправе ни пометить её, ни
    сдвинуть час выхода: иначе замер знал бы, чем кончилась сделка, и
    выглядел бы находкой.
    """
    v = _one_view(K=10)
    at, sym = float(v["rec"]["at"]), v["rec"]["sym"]
    quiet = {(sym, SQ.hour_key(at, k)): (100.0, 1e6) for k in range(1, 30)}
    k0, _ = SQ.marked_hour(v, quiet, 0.01)
    check("будущее: на тишине выхода нет", k0 is None, f"{k0}")

    future = dict(quiet)
    for k in range(int(v["path"]["K"]), 30):                  # k = K и дальше
        future[(sym, SQ.hour_key(at, k))] = (9e6, 1e6)        # доля 900 %
    k1, _ = SQ.marked_hour(v, future, 0.01)
    check("будущее: всплеск после выхода не метит", k1 is None, f"{k1}")

    mixed = dict(future)
    mixed[(sym, SQ.hour_key(at, 3))] = (30000.0, 1e6)
    k2, _ = SQ.marked_hour(v, mixed, 0.01)
    check("будущее: час выхода взят из прошлого", k2 == 3, f"{k2}")

    # и то же самое на всей выборке, а не на одной записи
    cache, _launch = journal(n_tail=3, n_rest=3, seed=6)
    views = SQ.views_of(cache)
    cells = quiet_cells(views)
    a, _ = SQ.mark_all(views, cells, 0.01)
    after = dict(cells)
    for key, vv in views.items():
        rec = vv["rec"]
        for k in range(int(vv["path"]["K"]), int(vv["path"]["K"]) + 12):
            after[(rec["sym"], SQ.hour_key(float(rec["at"]), k))] = (9e6, 1e6)
    b, _ = SQ.mark_all(views, after, 0.01)
    check("будущее: выборка не шелохнулась", a == b, f"{len(a)} и {len(b)}")


def test_live_hours_stop_before_the_exit():
    """Часы жизни кончаются на K−1: час K — тот, в котором закрыло ядро."""
    v = _one_view(K=10)
    ks = SQ.live_hours(v)
    check("часы жизни: последний — K−1",
          ks == list(range(1, 10)), f"{ks[:3]}…{ks[-3:] if ks else ''}")
    check("часы жизни: пустого пути нет",
          SQ.live_hours({"path": None}) == [], "не пусто")


# ======================================================================
# 4. Калибровочная пара и перемешанный поток
# ======================================================================

def test_calibration_pair_finds_planted_and_is_quiet_on_noise():
    """Подсаженное — найти, на шуме — промолчать.

    Без этой пары сломанное чтение потока неотличимо от «эффекта нет»:
    оба печатают ноль помеченных позиций.
    """
    cache, _launch = journal(n_tail=12, n_rest=28, seed=21, stagger=False)
    views = SQ.views_of(cache)
    quiet = quiet_cells(views)
    planted, hit = plant(quiet, views, hour=2)
    ch, _st = SQ.mark_all(views, planted, 0.01)
    tails = sum(1 for key in ch if views[key]["tail"])
    check("калибровочная пара: подсаженное найдено",
          set(ch) == set(hit) and tails == 12,
          f"помечено {len(ch)}, хвостовых {tails}, подсажено {len(hit)}")
    check("калибровочная пара: все вышли в час 2",
          all(k == 2 for k in ch.values()), f"{sorted(set(ch.values()))}")

    draws = SQ.permuted_marks(views, planted, 0.01, seeds=60)
    ps = SQ.perm_stats({"n": len(ch), "tails": tails}, draws)
    check("калибровочная пара: перемешанный поток хвост не находит",
          ps["beat_tails"] <= 0.02,
          f"зёрен не хуже {ps['beat_tails']}, медиана {ps['med_tails']}")

    rnd = random.Random(33)
    noise = {}
    for ck in quiet:
        noise[ck] = ((50000.0 if rnd.random() < 0.3 else 100.0), 1e6)
    ch_n, _ = SQ.mark_all(views, noise, 0.01)
    tails_n = sum(1 for key in ch_n if views[key]["tail"])
    dn = SQ.permuted_marks(views, noise, 0.01, seeds=60)
    pn = SQ.perm_stats({"n": len(ch_n), "tails": tails_n}, dn)
    check("калибровочная пара: на шуме мера молчит",
          pn["beat_tails"] >= 0.05,
          f"зёрен не хуже {pn['beat_tails']}, настоящий {tails_n}, "
          f"медиана {pn['med_tails']}")


def test_permutation_keeps_the_hour_and_moves_the_name():
    """Перемешивается ИМЯ, а не час: набор пар внутри часа тот же."""
    cache, _launch = journal(n_tail=6, n_rest=6, seed=8, stagger=False)
    views = SQ.views_of(cache)
    cells, _hit = plant(quiet_cells(views), views, hour=2)
    draws = SQ.permuted_marks(views, cells, 0.01, seeds=5)
    check("перемешивание: число помеченных позиций держится",
          all(abs(d["n"] - 6) <= 6 for d in draws), f"{[d['n'] for d in draws]}")
    check("перемешивание: имена и правда сдвинулись",
          any(d["tails"] != 6 for d in draws), f"{[d['tails'] for d in draws]}")

    # инвариант: час тот же, набор пар внутри часа тот же, имя другое
    sh = SQ.shuffle_cells(cells, random.Random(2))
    before, after = {}, {}
    for (sym, hk), c in cells.items():
        before.setdefault(hk, []).append(c)
    for (sym, hk), c in sh.items():
        after.setdefault(hk, []).append(c)
    same_hours = sorted(before) == sorted(after)
    same_bags = all(sorted(before[h]) == sorted(after.get(h) or [])
                    for h in before)
    moved = sum(1 for ck in cells if sh.get(ck) != cells[ck])
    check("перемешивание: часы не тронуты", same_hours,
          f"{len(before)} и {len(after)}")
    check("перемешивание: набор пар внутри часа тот же", same_bags, "набор иной")
    check("перемешивание: имена переставлены", moved > 0, f"{moved}")


# ======================================================================
# 5. Дорога денег
# ======================================================================

def test_zero_flow_reproduces_the_base_bit_for_bit():
    """Обнулённый поток — база БИТ В БИТ по семи полям кассы.

    Правило, которое трогает деньги там, где потока нет, — не правило
    выхода, а сдвиг книги.
    """
    cache, launch = journal(n_tail=6, n_rest=14, seed=31,
                            rulers=("safe_s", "optimal_s"))
    views = SQ.views_of(cache)
    zero = {ck: (0.0, 1e6) for ck in quiet_cells(views)}
    ch, _st = SQ.mark_all(views, zero, 0.01)
    check("нулевой поток: не помечено ни одной позиции", not ch, f"{len(ch)}")
    base = money(cache, launch)
    mod = money(SQ.apply_flow(cache, ch), launch)
    fields = ("n", "usd", "final", "max_dd", "day_median", "win", "taken")
    diff = [(bk, f, (base.get(bk) or {}).get(f), (mod.get(bk) or {}).get(f))
            for bk in base for f in fields
            if (base.get(bk) or {}).get(f) != (mod.get(bk) or {}).get(f)]
    check("нулевой поток: касса бит в бит", not diff, f"{diff[:3]}")
    got = {bk: (v.get("exits") or {}) for bk, v in base.items()}
    check("нулевой поток: охрана рынком в тесте молчит",
          all("рынок" not in e for e in got.values()),
          f"{got}")


def test_planted_spike_exits_at_hour_one_by_the_core_mark():
    """Подсаженный всплеск в час 1 — выход в час 1 ПО ОТМЕТКЕ ЯДРА.

    Двадцать пять позиций с записанным исходом «пол»; после правила у
    каждой pnl равен отметке первого часа, выход помечен потоком, а
    отметки срезаны по час выхода — второго реплея здесь нет и не
    должно быть.
    """
    cache, launch = journal(n_tail=25, n_rest=10, seed=41,
                            rulers=("safe_s", "optimal_s"))
    views = SQ.views_of(cache)
    cells, hit = plant(quiet_cells(views), views, hour=1)
    ch, _st = SQ.mark_all(views, cells, 0.01)
    check("подсаженный всплеск: помечены все 25 хвостовых каждой линейки",
          len(ch) == 50 and set(ch) == set(hit), f"{len(ch)} из {len(hit)}")
    mod = SQ.apply_flow(cache, ch)
    bad = []
    for key, k in ch.items():
        r, old = mod[key], cache[key]
        want = views[key]["path"]["cum"][1]
        if (k != 1 or abs(float(r["pnl"]) - float(want)) > 1e-12
                or r["exit"] != SQ.EXIT_LABEL or len(r["marks"]) != 1
                or float(r["exit_ts"]) != float(old["at"]) + HOUR - 1.0
                or r["state"] != "closed"):
            bad.append((key[1], k, r["pnl"], want, r["exit"], len(r["marks"])))
    check("подсаженный всплеск: каждая вышла в час 1 по отметке часа 1",
          not bad, f"{bad[:2]}")
    check("подсаженный всплеск: исход стал лучше пола",
          all(float(mod[key]["pnl"]) > float(cache[key]["pnl"]) for key in ch),
          "хвост не спасён")
    base, rule = money(cache, launch), money(mod, launch)
    moved = [bk for bk in base
             if (base[bk] or {}).get("usd") != (rule.get(bk) or {}).get("usd")]
    check("подсаженный всплеск: деньги книг сдвинулись",
          len(moved) == len(base), f"сдвинулось {len(moved)} из {len(base)}")


def test_exit_record_is_the_library_one():
    """Закрытие записи — библиотечное (`wave.guard_record`), не своё."""
    cache, _launch = journal(n_tail=2, n_rest=2, seed=51)
    views = SQ.views_of(cache)
    key = sorted(views)[0]
    mine = SQ.apply_flow(cache, {key: 2})[key]
    theirs = SQ.WV.guard_record(cache[key], 2, why=SQ.EXIT_LABEL)
    check("закрытие: запись совпадает с библиотечной", mine == theirs,
          f"{ {k: (mine.get(k), theirs.get(k)) for k in set(mine) | set(theirs) if mine.get(k) != theirs.get(k)} }")


# ======================================================================
# 6. Диагностика механизма
# ======================================================================

def test_before_worst_needs_a_whole_hour_earlier():
    """Всплеск в час худшей отметки — НЕ раньше её: это кульминация."""
    at = BASE_TS
    rec = record("SQZ900USDT", at, [-0.05, -0.30, 0.10, 0.05], exit_="пол")
    v = {"rec": rec, "path": SQ.WV.path_of(rec), "tail": True}
    views = {("safe_s", "SQZ900USDT", at): v}
    w = SQ.worst_hour(v["path"])
    check("худшая отметка: час найден", w == 2, f"{w}")
    d_same = SQ.before_worst(views, {("safe_s", "SQZ900USDT", at): 2})
    check("диагностика: тот же час не считается ранним",
          d_same["share"] == 0.0 and d_same["same"] == 1, f"{d_same}")
    d_early = SQ.before_worst(views, {("safe_s", "SQZ900USDT", at): 1})
    check("диагностика: час раньше считается ранним",
          d_early["share"] == 1.0 and d_early["early"] == 1, f"{d_early}")
    d_late = SQ.before_worst(views, {("safe_s", "SQZ900USDT", at): 3})
    check("диагностика: час позже — поздний", d_late["late"] == 1, f"{d_late}")


def test_before_worst_is_a_dash_when_no_tail_is_marked():
    """Ни одной хвостовой позиции с всплеском — доля НЕ ИЗМЕРЕНА."""
    at = BASE_TS
    rec = record("SQZ901USDT", at, [0.01, 0.02, 0.03], exit_="срок")
    views = {("safe_s", "SQZ901USDT", at): {"rec": rec,
                                            "path": SQ.WV.path_of(rec),
                                            "tail": False}}
    d = SQ.before_worst(views, {("safe_s", "SQZ901USDT", at): 1})
    check("диагностика: прочерк, а не ноль",
          d["share"] is None and d["n"] == 0, f"{d}")


# ======================================================================
# 7. Порядок убийц в самом прогоне
# ======================================================================

def write_summaries(root, streams):
    """Разложить сводки по диску так, как их пишет живой писатель:
    `<корень>/<имя>/<сутки>.jsonl`, одна строка — один час.

    Прогон читает сводки ФАЙЛАМИ (`summary_names`, `read_name`,
    `wave.Hours`), а не объектом, и порядок убийц живёт именно в нём.
    Тест, подающий сводки в память, проверял бы другую дорогу.
    """
    for sym, rows in streams:
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


def journal_streams(views, spike_hour=2, usd=50000.0, quiet=100.0, turn=1e5):
    """Сводки на часы жизни подставного журнала: тишина плюс один всплеск.

    Доллары кладутся в колонку метки `Sell` (`liq_long`) — ту, которую
    калибровка на этой подделке назовёт выкупом шортов, — и попадают в
    часы РОСТА: середина стакана здесь растёт каждый час, то есть
    подделка не спорит с физикой, из которой сторона и выводится.
    """
    out = []
    for _key, v in sorted(views.items(), key=lambda kv: kv[1]["rec"]["sym"]):
        rec = v["rec"]
        rnd = random.Random(hash(rec["sym"]) % 10_000)
        at, rows, mid = float(rec["at"]), [], 1.0
        for k in range(0, int(v["path"]["K"]) + 1):
            mid *= 1.01
            rows.append(summary_row(SQ.hour_key(at, k), mid, turn / 2.0,
                                    turn / 2.0, 0.0,
                                    usd if k == spike_hour else quiet, rnd))
        out.append((rec["sym"], rows))
    return out


def run_with_spy(summary_dir, cache, launch, **kw):
    """Прогнать `run_squeeze.run` на подделке, считая вызовы ДЕНЕГ.

    Деньги подменяются пустышкой-счётчиком: проверяется не их число, а
    то, СЧИТАЛИСЬ ли они вообще — порядок убийц заявки требует, чтобы до
    измеренной стороны и покрытия касса не трогалась. Подменяется и
    чтение кэша (журнал подставной) и круг издержек (у кассы он свой и
    проверен своими тестами).
    """
    calls = []

    def spy(*a, **k):
        calls.append(a[2])                                    # changed
        return {"delta": {"n": 0, "tails": 0, "sum": 0.0, "cut_worse": 0},
                "stats": {}, "control": None, "beat": {}, "tails": {},
                "wo3": {}, "days": {}, "shape": {}}

    empty_market()
    out = tempfile.mkdtemp(prefix="sqz-run-")
    было = (RUN.money_cell, RUN.S.read_cache, RUN.CO.context)
    RUN.money_cell = spy
    RUN.S.read_cache = lambda log=print: (cache, None)
    RUN.CO.context = lambda *a, **k: None
    art, err = {}, None
    try:
        art = RUN.run(seeds=1, perm_seeds=0, axis=(0.01,),
                      summary_dir=summary_dir, launch=launch, ctx=None,
                      log=lambda *a: None, out=out, tag="test", **kw)
    except BaseException as e:                               # noqa: BLE001
        # Прогон, умерший ВНУТРИ шага, — тоже нарушение порядка, и
        # отвечать за него обязана названная проверка. Иначе падение
        # прилетает трассировкой из недр чтения потока, и снаружи не
        # видно, какое правило исчезло: подделка объявляется холостой
        # ровно потому, что её укус неразборчив (поймано `_bite.py`).
        err = f"{type(e).__name__}: {e}"
    finally:
        RUN.money_cell, RUN.S.read_cache, RUN.CO.context = было
    return art, calls, err


def test_run_counts_money_only_after_side_and_coverage():
    """Порядок убийц: пока сторона и покрытие не измерены, кассы нет.

    Убийца 0 объявлен заявкой стоящим ДО денег, и это свойство самого
    ПРОГОНА, а не меры: вердикт мерой считается верно и в том случае,
    если деньги посчитаны зря, — а посчитанные зря числа попадают в
    артефакт и однажды будут оттуда прочитаны как результат.
    """
    cache, launch = journal(n_tail=4, n_rest=4, seed=71)
    views = SQ.views_of(cache)

    # 1. Сторона не измерена (`Buy` горит и в росте, и в падении), а
    #    журнал сводками ПОКРЫТ: иначе блок дало бы покрытие, и проверка
    #    обещала бы больше, чем исполняет, — поймано подделкой 1
    #    (`_bite.py`), которая на покрытом журнале как раз и кусается.
    root = write_summaries(tempfile.mkdtemp(prefix="sqz-side-"),
                           calib_stream(blur=0.8) + journal_streams(views))
    art, calls, err = run_with_spy(root, cache, launch)
    check("порядок: сторона не измерена — денег не считали",
          not calls and err is None and "base" not in art
          and not art.get("cells"),
          f"вызовов кассы {len(calls)}, ячеек "
          f"{len(art.get('cells') or [])}, отказ {err}")
    check("порядок: блок назван стороной",
          [(r["key"], r["state"]) for r in (art.get("verdict") or [])]
          == [("сторона", "блок")], f"{art.get('verdict')}")
    check("порядок: покрытие даже не считалось",
          art.get("cover") == {}, f"{art.get('cover')}")

    # 2. Сторона измерена, а журнала сводки не покрывают вовсе.
    root = write_summaries(tempfile.mkdtemp(prefix="sqz-cover-"),
                           calib_stream())
    art, calls, err = run_with_spy(root, cache, launch)
    check("порядок: покрытие ниже половины — денег не считали",
          not calls and err is None and "base" not in art
          and not art.get("cells"),
          f"вызовов кассы {len(calls)}, покрытие "
          f"{(art.get('cover') or {}).get('share')}, отказ {err}")
    check("порядок: блок назван покрытием",
          [r["key"] for r in (art.get("verdict") or [])]
          == ["сторона", "покрытие"]
          and art["verdict"][-1]["state"] == "блок"
          and (art.get("cover") or {}).get("share") == 0.0,
          f"{(art.get('verdict') or [{}])[-1]}")

    # 3. Сторона измерена и журнал покрыт — вот теперь считается касса.
    root = write_summaries(tempfile.mkdtemp(prefix="sqz-full-"),
                           calib_stream() + journal_streams(views))
    art, calls, err = run_with_spy(root, cache, launch)
    check("порядок: сторона и покрытие измерены — касса посчитана",
          len(calls) >= 1 and err is None and "base" in art
          and len(art.get("cells") or []) == 1,
          f"вызовов кассы {len(calls)}, ячеек {len(art.get('cells') or [])}, "
          f"покрытие {(art.get('cover') or {}).get('share')}, отказ {err}")
    check("порядок: покрытие журнала полное",
          (art.get("cover") or {}).get("share") == 1.0
          and (art.get("cover") or {}).get("hours_share") == 1.0,
          f"{(art.get('cover') or {}).get('share')} и "
          f"{(art.get('cover') or {}).get('hours_share')}")
    check("порядок: всплеск в часе 2 помечен",
          calls and all(k == 2 for k in calls[0].values()) and calls[0],
          f"{sorted(set(calls[0].values())) if calls else 'вызовов нет'}")


# ======================================================================
# 8. Вердикт и показ
# ======================================================================

def _art(**over):
    """Артефакт, у которого пройдены ВСЕ убийцы, — основа для подмен."""
    books = ["safe_h", "optimal_h", "aggr_h"]
    cell = {"s": 0.01,
            "by_book": {bk: {"n": 40, "tails": 12, "positions": 800,
                             "ruler": "safe_s"} for bk in books},
            "beat": {bk: {"final": 0.01, "ratio": 0.02} for bk in books},
            "tails": {bk: {"base": 100, "rule": 60} for bk in books},
            "wo3": {bk: {"base": 100.0, "rule": 400.0} for bk in books},
            "days": {bk: {"better": 20, "worse": 10} for bk in books},
            "diag": {"n": 30, "early": 21, "same": 5, "late": 4, "share": 0.7},
            "delta": {"n": 40, "tails": 12, "sum": 3.5, "cut_worse": 4}}
    art = {"axis": [0.005, 0.01, 0.02], "judged": 0.01, "books": books,
           "dep": 10000, "seeds": 200, "n": 2000,
           "side": {"ok": True, "why": "доля долларов Buy в падениях 0.805",
                    "mark_short": "Sell", "field_short": "liq_long",
                    "share_down": {"Buy": 0.805, "Sell": 0.143},
                    "usd_down": {"Buy": 3.0e8, "Sell": 7.2e7},
                    "usd_up": {"Buy": 7.3e7, "Sell": 4.3e8}},
           "cover": {"n": 2000, "full": 1900, "share": 0.95, "hours": 40000,
                     "hours_measured": 39000, "hours_share": 0.975,
                     "n_uncovered": 100, "no_hours": 10, "part": 80,
                     "none": 20},
           "cells": [cell], "base": {}, "computed_at": "2026-09-19 00:00"}
    for k, v in over.items():
        art[k] = v
    return art


def _state(art, key):
    for r in SQ.verdict(art):
        if r["key"] == key:
            return r["state"]
    return None


def test_verdict_is_derived_from_the_numbers():
    """Каждая строка вердикта следует из своего числа, а не из мнения."""
    ok = _art()
    check("вердикт: всё пройдено", all(r["state"] == "пройдено"
                                       for r in SQ.verdict(ok)),
          f"{[(r['key'], r['state']) for r in SQ.verdict(ok)]}")
    check("вердикт: фраза итога говорит о пройденном",
          "убийцы пройдены" in SQ.reading(ok), SQ.reading(ok)[:120])

    a = _art()
    a["side"] = {"ok": False, "why": "доля 0.51 внутри полосы"}
    check("вердикт: сторона не измерена — блок", _state(a, "сторона") == "блок",
          f"{_state(a, 'сторона')}")
    check("вердикт: после блока стороны ничего не судится",
          len(SQ.verdict(a)) == 1, f"{len(SQ.verdict(a))}")

    b = _art()
    b["cover"] = dict(b["cover"], share=0.4)
    check("вердикт: покрытие ниже половины — блок",
          _state(b, "покрытие") == "блок", f"{_state(b, 'покрытие')}")
    b2 = _art()
    b2["cover"] = dict(b2["cover"], share=0.7)
    check("вердикт: покрытие 50–90 % — оговорка",
          _state(b2, "покрытие") == "оговорка", f"{_state(b2, 'покрытие')}")

    c = _art()
    c["cells"][0]["beat"] = {"safe_h": {"final": 0.5}, "optimal_h": {"final": 0.4},
                             "aggr_h": {"final": 0.01}}
    check("вердикт: контроль не пройден — убивает",
          _state(c, "контроль") == "убивает", f"{_state(c, 'контроль')}")

    # Смоук на трёх зёрнах вердиктом не является: разрешение доли есть
    # 1/зёрна, и планка в 10 % на трёх зёрнах не измерима вовсе.
    s3 = _art()
    s3["seeds"] = 3
    check("вердикт: контроль на трёх зёрнах не судит",
          _state(s3, "контроль") == "нечем судить", f"{_state(s3, 'контроль')}")
    check("вердикт: смоук назван смоуком",
          "смоук ДОРОГИ" in SQ.reading(s3), SQ.reading(s3)[:160])

    d = _art()
    d["cells"][0]["tails"] = {bk: {"base": 100, "rule": 90} for bk in d["books"]}
    check("вердикт: хвост срезан меньше четверти — убивает",
          _state(d, "хвост") == "убивает", f"{_state(d, 'хвост')}")

    e = _art()
    e["cells"][0]["wo3"] = {bk: {"base": 400.0, "rule": 100.0}
                            for bk in e["books"]}
    check("вердикт: без трёх лучших дней не выросло — убивает",
          _state(e, "концентрация") == "убивает",
          f"{_state(e, 'концентрация')}")

    f = _art()
    f["cells"][0]["diag"] = {"n": 30, "early": 9, "same": 10, "late": 11,
                             "share": 0.3}
    check("вердикт: всплеск есть кульминация — убивает",
          _state(f, "механизм") == "убивает", f"{_state(f, 'механизм')}")
    check("вердикт: кульминация названа в итоге",
          "КУЛЬМИНАЦИЯ" in SQ.reading(f), SQ.reading(f)[:160])

    g = _art()
    g["cells"][0]["diag"] = {"n": 0, "early": 0, "same": 0, "late": 0,
                             "share": None}
    check("вердикт: доля не измерена — не измерено, а не ноль",
          _state(g, "механизм") == "не измерено", f"{_state(g, 'механизм')}")


def test_thin_event_is_not_a_dead_rule():
    """Меньше 30 помеченных на книгу — «нечем судить», а не «не работает»."""
    a = _art()
    a["cells"][0]["by_book"] = {bk: {"n": 7, "tails": 2, "positions": 800,
                                     "ruler": "safe_s"} for bk in a["books"]}
    check("объём: состояние «нечем судить»",
          _state(a, "объём") == "нечем судить", f"{_state(a, 'объём')}")
    check("объём: сказано «событие реже, чем думали»",
          "реже, чем думали" in SQ.reading(a), SQ.reading(a)[:160])
    check("объём: деньги дальше не судятся",
          all(r["key"] not in ("контроль", "хвост") for r in SQ.verdict(a)),
          f"{[r['key'] for r in SQ.verdict(a)]}")


def test_report_prints_a_dash_and_the_derived_phrase():
    """Величины, которой нет, — прочерк; фраза итога — из числа."""
    a = _art()
    a["cells"][0]["beat"] = {bk: {"final": None, "ratio": None}
                             for bk in a["books"]}
    a["cells"][0]["control"] = {"sum_med": None}
    a["verdict"] = SQ.verdict(a)
    txt = SQ.report(a)
    check("показ: прочерк вместо ноля", "—" in txt, "прочерков нет")
    check("показ: нолей вместо прочерка не появилось",
          "0.0 % |" not in txt.split("## 1.")[-1].split("###")[0],
          "ноль там, где нечего мерить")
    check("показ: фраза итога совпадает с выведенной",
          SQ.reading(a) in txt, SQ.reading(a)[:80])
    f = _art()
    f["cells"][0]["diag"] = {"n": 30, "early": 9, "same": 10, "late": 11,
                             "share": 0.3}
    f["verdict"] = SQ.verdict(f)
    check("показ: вердикт в отчёте тот же, что в числах",
          "убивает" in SQ.report(f), "вердикт не напечатан")


def test_empty_read_is_a_refusal_not_a_report():
    """Ноль строк при непустом каталоге — ОТКАЗ, а не отчёт с прочерками."""
    raised = None
    try:
        SQ.refuse_if_empty(772, {"rows": 0}, root="/нет/такого")
    except SystemExit as e:
        raised = str(e)
    check("пустота: отказ поднят", raised is not None, "отказа нет")
    check("пустота: причина названа сломанным чтением",
          raised and "сломанное чтение" in raised, str(raised)[:160])
    quiet_ok = True
    try:
        SQ.refuse_if_empty(772, {"rows": 791920}, root="x")
        SQ.refuse_if_empty(0, {"rows": 0}, root="x")
    except SystemExit:
        quiet_ok = False
    check("пустота: на живой записи отказа нет", quiet_ok, "лишний отказ")


def test_middle_of_the_axis_is_judged():
    """Судит середина объявленной оси, а не лучшая ячейка."""
    check("ось: судится середина", SQ.middle() == 0.010, f"{SQ.middle()}")
    check("ось: объявлена до прогона",
          SQ.AXIS_S == (0.005, 0.010, 0.020), f"{SQ.AXIS_S}")


def test_modules_come_from_where_they_should():
    """Чужой модуль под знакомым именем — отказ, а не работа."""
    check("ядра: волна из dca_paper",
          SQ.U.module_origin(SQ.WV) == "dca_paper", SQ.U.module_origin(SQ.WV))
    check("ядра: форма из factory",
          SQ.U.module_origin(SQ.SB) == "factory", SQ.U.module_origin(SQ.SB))
    check("ядра: сторона из mech_d71203f0",
          SQ.U.module_origin(SQ.U) == "mech_d71203f0", SQ.U.module_origin(SQ.U))


def main():
    print("механика 357a7c60 — топливо сквиза по ходу позиции\n")
    for title, tests in (
            ("сторона решается данными",
             (test_side_is_decided_by_data,
              test_side_survives_swapped_columns,
              test_side_refuses_inside_the_band,
              test_side_refuses_when_halves_disagree,
              test_side_needs_dollars_to_be_measured,
              test_unmeasured_hours_are_not_a_move,
              test_gap_hours_do_not_make_a_move)),
            ("метка часа",
             (test_rule_needs_both_share_and_floor,
              test_first_marked_hour_wins,
              test_missing_hour_is_a_dash_not_zero,
              test_coverage_separates_none_from_partial)),
            ("заглядывание в будущее",
             (test_future_does_not_move_the_past,
              test_live_hours_stop_before_the_exit)),
            ("калибровочная пара",
             (test_calibration_pair_finds_planted_and_is_quiet_on_noise,
              test_permutation_keeps_the_hour_and_moves_the_name)),
            ("дорога денег",
             (test_zero_flow_reproduces_the_base_bit_for_bit,
              test_planted_spike_exits_at_hour_one_by_the_core_mark,
              test_exit_record_is_the_library_one)),
            ("диагностика механизма",
             (test_before_worst_needs_a_whole_hour_earlier,
              test_before_worst_is_a_dash_when_no_tail_is_marked)),
            ("порядок убийц в прогоне",
             (test_run_counts_money_only_after_side_and_coverage,)),
            ("вердикт и показ",
             (test_verdict_is_derived_from_the_numbers,
              test_thin_event_is_not_a_dead_rule,
              test_report_prints_a_dash_and_the_derived_phrase,
              test_empty_read_is_a_refusal_not_a_report,
              test_middle_of_the_axis_is_judged,
              test_modules_come_from_where_they_should))):
        print(title)
        for fn in tests:
            run_test(fn)
    print()
    if FAILED:
        # Каждое падение — СВОЕЙ строкой со словом ПАДЕНИЕ, и сводка
        # стоит в самом конце. Приёмка (`runlog.check_build`) читает
        # последние 4000 символов и ищет в них обещанную строку: имя
        # проверки без этого слова нашлось бы и в строке «ok», то есть
        # холостой контроль объявлялся бы кусающимся. Поймано на своей
        # же машине контролей 19.09.
        print(f"ПАДЕНИЙ: {len(FAILED)}")
        for name in FAILED:
            print(f"ПАДЕНИЕ {name}")
        raise SystemExit(1)
    print(f"все проверки прошли ({CHECKS[0]})")


if __name__ == "__main__":
    main()
