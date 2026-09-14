#!/usr/bin/env python3
"""Проверки механики 258a860c — бюджет маржи короткой книги h24.

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть.
Проверка, которая не кусается, не проверяет ничего.

Что проверяется: обёртка без правила не меняет книгу ни на цент; бюджет
режет тесный час РОВНО до объявленной границы (литералы 1972 $ и
−1774.8 $ посчитаны руками из билета 222 $, бюджета 2000 $ и пола 25 $);
остаток считается от ОТКРЫТЫХ позиций, а не от книги целиком; половина
остатка есть половина, а не весь; ниже пола билета позиция не
открывается и считается числом; счёт эквити обёртки равен счёту кассы, и
сверка кусается; заглядывание в будущее (переписать будущее — прошлое не
шелохнулось); калибровочная пара обеими ногами (равномерное уменьшение
не двигает укус, подсадка находится); форма книги равна ячейке
семейства; укус берётся у меры проекта; дня, которого нет, — прочерк, а
не ноль; розыгрыш контроля выбирает ЧИСЛО; перестановка меняет
раскладку; вердиктовые фразы выведены из чисел; пустота не выдаёт себя
за результат; загрузка считает все часы жизни позиции; ось и ячейка
вердикта объявлены заданием.

Вывод скуп намеренно: приёмка смотрит ПОСЛЕДНИЕ 4000 символов, и строка
«ПРОВАЛ имя», утонувшая в середине, есть контроль, который здесь
пройдёт, а там нет.

    .venv/bin/python research/mech_258a860c/test_budget_book.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import budget_book as BB                                      # noqa: E402
from budget_book import R, RP, ST, AG                         # noqa: E402

TESTS = []
H = BB.HOUR
DAY = 86400.0
T0 = 1786147200.0                      # ровная граница часа И суток
NOW = T0 + 40 * DAY
CTX = {"error": "издержки в проверке не считаются"}
TICKET = 222.0                         # билет `safe_h` на $10k — руками
FLOOR = 25.0                           # биржевой пол билета режима
B20 = 2000.0                           # бюджет b = 0.20 на $10k


def test(fn):
    TESTS.append(fn)
    return fn


def quiet(*_a):
    pass


# ---------------------------------------------------------------- фикстуры

def rec(sym, at, pnl, hold_h=24, lev=3.0, fwd=100.0, state="closed"):
    """Запись реплея в ЖИВОЙ форме: поля те же, что пишет прогон.

    Отметки дрожат и суммируются ровно в исход: запись с ровными
    приращениями прятала бы разницу между «где позиция к часу k» и её
    итогом, а запись, где сумма отметок не равна исходу, живой не бывает.
    """
    out_ts = float(at) + hold_h * H - 1.0
    n = int((out_ts - at) // H) + 1
    d = [((i * 37 % 11) - 5) / 100.0 for i in range(n - 1)]
    d.append(float(pnl) - sum(d))
    return {"at": float(at), "exit_ts": out_ts, "pnl": float(pnl),
            "pnl_net": float(pnl) - 0.002, "lev": float(lev),
            "lev_fence": float(lev), "fwd": float(fwd), "sym": sym,
            "side": "short", "rr": 0.5, "gates": ["any"], "exit": "срок",
            "marks": [[float(at) + i * H, round(float(x), 6)]
                      for i, x in enumerate(d)],
            "end_ts": out_ts, "sched_end": float(at) + hold_h * H,
            "depth": 1, "avg": 100.0, "entry_px": 100.0, "exit_px": 100.7,
            "fills": [[float(at), 100.0, 0.25]], "state": state,
            "fav_bp": 300.0}


def cache_of(rows, ruler=None):
    ruler = ruler or BB.RULER
    return {(ruler, r["sym"], round(float(r["at"]), 3)): r for r in rows}


def tight(n=25, pnl=BB.PLANT_PNL, at=None):
    """Тесный час: n позиций одной секунды, имена РАЗНЫЕ.

    Разные имена обязательны: правило «одна позиция на имя» оставило бы
    от подсадки одну, и бюджету нечего было бы резать. `pnl` — число
    либо функция от номера: раскладка множителей видна в деньгах только
    тогда, когда исходы у позиций разные.
    """
    at = T0 + 10 * DAY if at is None else at
    f = pnl if callable(pnl) else (lambda _i: pnl)
    return cache_of([rec(f"T{i:02d}USDT", at, f(i), fwd=200.0 - i)
                     for i in range(n)])


def spread(days=12, per_day=3, pnl=None):
    """Книга на несколько суток: колонок концентрации без четырёх суток нет."""
    pnl = pnl or (lambda i: 0.25 if i % 4 else -0.6)
    rows = []
    for d in range(days):
        for j in range(per_day):
            i = d * per_day + j
            rows.append(rec(f"S{i:03d}USDT", T0 + d * DAY + j * 3 * H,
                            pnl(i), fwd=150.0 - j))
    return cache_of(rows)


def launch_of(cache, days=400.0):
    return {k[1]: T0 - days * DAY for k in cache}


class NoMkt(BB.NoMarket):
    pass


class HotMkt:
    """Рынок, который ИНОГДА срабатывает: без него охрана непроверяема.

    Проверка «форма равна ячейке семейства» на молчащем рынке прошла бы
    и у книги, которая правило выхода вовсе не применяет: обе дороги
    ничего не меняли бы. Поэтому здесь рынок трогает каждую третью
    позицию — и разница дорог становится видна деньгами.
    """

    def __init__(self, k=3, every=3):
        self.k, self.every = int(k), int(every)
        self.wave_none = 0

    def k_star(self, at, _pct, last):
        if int(float(at) // H) % self.every:
            self.wave_none += 1
            return None, 1
        return (min(self.k, int(last)) or None), 0


def form(cache, maker=None, dep=BB.DEP, now=NOW, ctx=CTX):
    return BB.book_form(cache, ctx, launch_of(cache), dep=dep, maker=maker,
                        now=now, log=quiet, mkt=NoMkt())


def margins(sz):
    return {(r["sym"], round(float(r["at"]), 3)): round(float(m), 6)
            for r, m in sz.rows}


# ------------------------------------------------------------------ правило

@test
def обёртка_без_правила_не_меняет_книгу():
    """Обёртка, ничего не решающая, обязана дать ТУ ЖЕ книгу.

    Иначе всякая разница ниже объяснялась бы самой обёрткой, а не
    правилом, и замер отвечал бы не на свой вопрос.
    """
    cache = spread()
    st0, c0, _z = BB.book_form(cache, CTX, launch_of(cache), log=quiet,
                               mkt=NoMkt(), now=NOW)
    st1, c1, sz = form(cache, maker=BB.plain_maker())
    assert st0 and st1, "книга пуста"
    assert st0["usd"] == st1["usd"], (st0["usd"], st1["usd"])
    assert st0["n"] == st1["n"] and c0["fp"] == c1["fp"], "состав разошёлся"
    assert sz.capped == 0 and sz.below_floor == 0, "обёртка что-то отрезала"


@test
def бюджет_режет_тесный_час():
    """Тесный час стоит книге не больше бюджета — с точностью до цента.

    Числа посчитаны руками и стоят литералами: билет 222 $, бюджет
    2000 $, пол 25 $. Восемь позиций берут полный билет (1776 $), затем
    половины остатка 112, 56 и 28 $, а девятая доля (14 $) ниже пола —
    и позиция не открывается. Итого 1972 $ маржи, 11 позиций, 14
    отказов полом; деньги часа при исходе −0.9 суть −1774.8 $.
    """
    cache = tight()
    st, c, sz = form(cache, maker=BB.budget_maker(BB.VERDICT_B))
    assert round(sz.taken_usd, 2) == 1972.0, sz.taken_usd
    assert c["taken"] == 11, c["taken"]
    assert sz.below_floor == 14, sz.below_floor
    assert round(st["usd"], 2) == -1774.8, st["usd"]
    assert sz.taken_usd <= B20 + 1e-9, "бюджет превышен"


@test
def половина_остатка_а_не_весь():
    """Половина остатка — половина: правило целого остатка даёт другой счёт.

    При целом остатке книга взяла бы девять полных билетов (1998 $) и
    встала; половина даёт 1972 $ и одиннадцать позиций. Числа разные, и
    именно этим правило отличимо от «брать, пока хватает денег».
    """
    cache = tight()
    _st, c2, sz2 = form(cache, maker=BB.budget_maker(BB.VERDICT_B, half=2.0))
    _s1, c1, sz1 = form(cache, maker=BB.budget_maker(BB.VERDICT_B, half=1.0))
    assert round(sz1.taken_usd, 2) == 1998.0, sz1.taken_usd
    assert c1["taken"] == 9 and c2["taken"] == 11, (c1["taken"], c2["taken"])
    assert round(sz2.taken_usd, 2) == 1972.0, sz2.taken_usd


@test
def остаток_считается_от_открытых():
    """Деньги возвращаются в бюджет в секунду выхода, не раньше и не позже.

    Позиция, открытая ПОСЛЕ выхода тесного часа, обязана получить полный
    билет: бюджет к этому моменту свободен. Пока час жив — билет
    урезан. Разница между этими двумя позициями и есть правило.
    """
    at = T0 + 10 * DAY
    cache = dict(tight(at=at))
    late = rec("LATEUSDT", at + 25 * H, 0.2)
    early = rec("EARLYUSDT", at + 2 * H, 0.2)
    cache[(BB.RULER, "LATEUSDT", round(late["at"], 3))] = late
    cache[(BB.RULER, "EARLYUSDT", round(early["at"], 3))] = early
    _st, _c, sz = form(cache, maker=BB.budget_maker(BB.VERDICT_B))
    got = margins(sz)
    late_k = BB.key_of(late)
    assert sz.mult_of[late_k] == 1.0, sz.mult_of[late_k]
    assert late_k in got, "позиция после выхода часа денег не получила"
    assert sz.mult_of[BB.key_of(early)] == 0.0, sz.mult_of
    assert BB.key_of(early) not in got, \
        "позиция внутри занятого часа получила деньги"


@test
def ниже_пола_не_открывается():
    """Позиция, которой остаётся меньше пола билета, не открывается.

    Пол биржевой (`rules.floor_of`), и это единственное место, где в
    правило просачивается отбор, — поэтому число вычеркнутых считается
    и печатается. При широком бюджете вычеркнутых нет вовсе.
    """
    cache = tight()
    _s, c1, sz1 = form(cache, maker=BB.budget_maker(BB.VERDICT_B))
    _s2, c2, sz2 = form(cache, maker=BB.budget_maker(1.0))
    assert R.floor_of(BB.BOOK) == FLOOR, R.floor_of(BB.BOOK)
    assert sz1.below_floor == 14 and c1["taken"] == 11, sz1.below_floor
    assert sz2.below_floor == 0 and c2["taken"] == 25, (sz2.below_floor,
                                                        c2["taken"])
    cols = BB.columns(*form(cache, maker=BB.budget_maker(BB.VERDICT_B)))
    assert cols["below_floor"] == 14 and cols["floor_share"] > 0.05, cols


@test
def счёт_обёртки_равен_кассе():
    """Свой счёт эквити обязан совпасть с итогом самой кассы.

    Это и есть запрет на вторую кассу: обёртка читает решения кассы, а
    не пересчитывает их, и равенство проверяется каждым прогоном.
    """
    cache = spread()
    for maker in (BB.plain_maker(), BB.budget_maker(BB.VERDICT_B)):
        _st, _c, sz = form(cache, maker=maker)
        assert abs(sz.final_mine - float(sz.final_desk)) <= 1e-4, \
            (sz.final_mine, sz.final_desk)


@test
def сверка_счёта_кусается():
    """Сама сверка обязана падать на расхождении, а не молчать."""
    sz = BB.Sizer(10000.0, [], lambda _r: 0.02, FLOOR)
    sz.finish({"final": 0.0})
    try:
        sz.finish({"final": 0.5})
    except AssertionError:
        return
    raise AssertionError("сверка счёта не заметила расхождения")


@test
def будущее_не_меняет_прошлого():
    """Переписать будущее — маржа прошлых решений не шелохнётся.

    Будущее переписывается ЦЕЛИКОМ: и решения после границы, и исходы
    позиций, которые на границе ещё открыты. Второе важно: деньги
    возвращаются в бюджет в секунду выхода, и касса, освобождающая их
    раньше, знала бы исход до его наступления.

    Книга взята НАБИТАЯ (восемь решений в сутки): на редкой книге
    бюджет не связывает ни разу, маржа у всех равна билету, и проверка
    прошла бы, ничего не проверив. Это условие стоит первым `assert`.
    """
    cache = spread(days=12, per_day=8)
    T = T0 + 6 * DAY
    _s, _c, sz0 = form(cache, maker=BB.budget_maker(BB.VERDICT_B))
    assert sz0.capped > 5, f"бюджет не связывал — проверять нечего: {sz0.capped}"
    fut = {}
    for k, r in cache.items():
        if float(r["at"]) > T:
            fut[k] = rec(r["sym"], r["at"], -0.95, hold_h=48,
                         fwd=float(r["fwd"]) / 2.0)
        elif float(r["exit_ts"]) > T:
            fut[k] = dict(rec(r["sym"], r["at"], -0.95), fwd=r["fwd"])
        else:
            fut[k] = r
    assert sum(1 for k in fut if fut[k] is not cache[k]) > 3, "будущее не тронуто"
    _s2, _c2, sz1 = form(fut, maker=BB.budget_maker(BB.VERDICT_B))
    a = {k: v for k, v in margins(sz0).items() if k[1] <= T}
    b = {k: v for k, v in margins(sz1).items() if k[1] <= T}
    assert a and a == b, ("прошлое шелохнулось",
                          [k for k in a if b.get(k) != a[k]][:3])


# ------------------------------------------------------- калибровочная пара

@test
def равномерное_уменьшение_не_двигает_укус():
    """Нога «молчать»: те же позиции с маржой ×0.5 — тот же укус.

    Заодно это и проверка счёта эквити: маржа задаётся в долларах и
    делится на него, значит ошибка счёта сделала бы масштаб денег не
    ровно вдвое.
    """
    cache = spread()
    st, c, sz = form(cache, maker=BB.plain_maker())
    base = BB.columns(st, c, sz)
    u = BB.calib_uniform(cache, CTX, launch_of(cache), base, sz, log=quiet,
                         mkt=NoMkt(), now=NOW)
    assert u["pass"] is True, u["why"]
    assert u["bite"] == base["bite"], (u["bite"], base["bite"])
    assert abs(u["scale"] - BB.CALIB_MULT) < 1e-4, u["scale"]
    assert u["n"] == base["n"], (u["n"], base["n"])


@test
def калибровка_находит_подсадку():
    """Нога «найти»: подсаженный тесный час обязан быть срезан бюджетом.

    Деньги брутто равны исходу × маржу, поэтому граница проверяется
    литералом, а не «примерно».
    """
    cache = spread(days=8, per_day=4)
    p = BB.calib_planted(cache, now=NOW, log=quiet)
    assert p["pass"] is True, p["why"]
    assert p["margin_usd"] <= p["B"] + 1e-9, p
    assert abs(p["exact"]) <= 0.01, p["exact"]
    assert abs(p["base_usd"]) > p["limit"], (p["base_usd"], p["limit"])


@test
def форма_равна_кассе():
    """Форма книги обязана совпасть с ячейкой семейства на общих полях.

    Рынок здесь СРАБАТЫВАЮЩИЙ намеренно: на молчащем правило выхода
    ничего не меняет, и проверка прошла бы у книги, которая его вовсе
    не применяет. Сначала числом доказывается, что охрана действительно
    тронула часть позиций, — и только потом сверяются дороги.
    """
    cache = spread()
    was = RP._MARKET
    RP._MARKET = HotMkt()
    try:
        hot, _s = RP.guard_shorts(AG.packed_short(cache)[BB.BOOK], BB.BOOK,
                                  log=quiet, now=NOW)
        moved = sum(1 for r in hot if r.get("exit") == R.GUARD_EXIT)
        assert moved > 3, f"охрана не сработала ни разу: {moved}"
        g = BB.agrees_with_cell(cache, CTX, launch_of(cache), now=NOW,
                                log=quiet)
    finally:
        RP._MARKET = was
    assert g["все_равны"] is True, g


# -------------------------------------------------------------- показ и меры

@test
def укус_берётся_у_меры_проекта():
    """Укус — `stability.stats`, и он сходится с укусом кассы."""
    st, c, sz = form(spread(), maker=BB.plain_maker())
    cols = BB.columns(st, c, sz)
    days = {str(r["d"]): float(r["usd"]) for r in st["days_rows"]}
    assert cols["bite"] == (ST.stats(days) or {})["bite"], cols["bite"]
    assert cols["bite"] == cols["bite_stats"], (cols["bite"],
                                                cols["bite_stats"])


@test
def дня_нет_прочерк_а_не_ноль():
    """Дня нет в своде книги — прочерк с причиной, а не нулевые деньги."""
    st, c, sz = form(spread(), maker=BB.plain_maker())
    cols = BB.columns(st, c, sz, named=("2000-01-01",))
    got = cols["named"]["2000-01-01"]
    assert got["usd"] is None, got
    assert got["why"], "причина прочерка не названа"


@test
def загрузка_считает_часы_жизни():
    """Загрузка считается по всем часам жизни позиции, а не по часу входа.

    Часы без позиций входят в ряд нулём, поэтому средняя ниже пика, а
    пик равен марже самого занятого часа.
    """
    cache = tight(n=4)
    _s, _c, sz = form(cache, maker=BB.plain_maker())
    ld = BB.load_of(sz, BB.DEP)
    assert ld["hours"] == 24, ld["hours"]
    assert ld["peak_usd"] == round(4 * TICKET, 2), ld["peak_usd"]
    assert ld["open_peak"] == 4 and ld["positions"] == 4, ld
    # Четыре позиции одного часа живут ВСЕ 24 часа ряда, значит средняя
    # загрузка равна пиковой ровно. Считай загрузка один час входа,
    # средняя вышла бы в 24 раза ниже — и это то, что проверяется.
    assert ld["mean"] == ld["peak"] == round(4 * TICKET / BB.DEP, 4), ld
    _s2, _c2, sz2 = form(spread(), maker=BB.plain_maker())
    ld2 = BB.load_of(sz2, BB.DEP)
    assert 0 < ld2["mean"] < ld2["peak"], ld2


@test
def розыгрыш_контроля_выбирает_число():
    """Какой контроль считать, решает доля вычеркнутых полом, а не автор."""
    k1, w1 = BB.control_kind(0.33)
    k2, w2 = BB.control_kind(0.01)
    k3, w3 = BB.control_kind(None)
    assert k1 == "sample" and "33.0 %" in w1, (k1, w1)
    assert k2 == "perm" and "1.0 %" in w2, (k2, w2)
    assert k3 == "perm" and "не измерена" in w3, (k3, w3)


@test
def перестановка_меняет_раскладку():
    """Контроль перестановкой обязан РАЗДАВАТЬ те же множители иначе.

    Тождественная перестановка дала бы ту же книгу под другим именем, и
    контроль ничего бы не проверял.
    """
    cache = tight(pnl=lambda i: -0.9 if i % 2 else 0.6)
    st, c, sz = form(cache, maker=BB.budget_maker(BB.VERDICT_B))
    base = BB.columns(st, c, sz)
    mults = list(sz.mults)
    a = BB.shuffle_cell(cache, CTX, launch_of(cache), mults, 7, now=NOW,
                        mkt=NoMkt(), log=quiet)
    b = BB.shuffle_cell(cache, CTX, launch_of(cache), mults, 8, now=NOW,
                        mkt=NoMkt(), log=quiet)
    assert a and b and a["taken"] and b["taken"], (a, b)
    assert a["usd"] != base["usd"], "перемешанная книга равна бюджету"
    assert a["usd"] != b["usd"], "два зерна дали одну и ту же раскладку"
    assert sorted(round(x, 6) for x in mults) == sorted(
        round(x, 6) for x in sz.mults), "мультимножество испорчено"


@test
def число_взятых_сходится_или_названо():
    """Разница взятых объясняется полом билета — или называется числом.

    Заявка обещает, что не отбирается ни одна сделка. Проверить это
    можно только сведением: взятых у бюджета минус у базы плюс
    вычеркнутых полом. Остаток, который не объясняется полом, обязан
    быть назван, а не спрятан в прозе.
    """
    base = {"taken": 729, "no_cash": 4}
    line = BB._taken_line(base, {"taken": 551, "below_floor": 182,
                                 "floor_share": 0.33, "no_cash": 0}, 0.05)
    assert "база 729, бюджет 551 (-178)" in line, line
    assert "182 решений" in line and "33.0 %" in line, line
    assert "остаётся +4" in line, line
    exact = BB._taken_line(base, {"taken": 551, "below_floor": 178,
                                  "floor_share": 0.32, "no_cash": 0}, 0.05)
    assert "Иных потерь нет" in exact, exact
    none = BB._taken_line(base, {"taken": 551}, 0.05)
    assert "не измерено" in none, none


@test
def доля_зёрен_считается_мерой_проекта():
    """Доля «не хуже» — одна мера на проект; укус едет в неё со знаком."""
    draws = [{"bite": 1.0, "bite_neg": -1.0}, {"bite": 9.0, "bite_neg": -9.0}]
    sh, n = BB.beat(draws, -5.0, "bite_neg")
    assert n == 2 and sh == 0.5, (sh, n)


@test
def вердикт_выведен_из_числа():
    """Фразы убийц собираются из чисел и переворачиваются вместе с ними."""
    base = {"ratio": 2.0, "bite": 3.0, "usd_wo_top3d": 100.0}
    good = {"ratio": 3.0, "bite": 1.0, "usd_wo_top3d": 50.0}
    bad = dict(good, ratio=1.0)
    ok, why, _n = BB.killer_one(base, good)
    assert ok is True and "3.00" in why and "1" in why, why
    ok2, why2, _n2 = BB.killer_one(base, bad)
    assert ok2 is False and "1.00" in why2, why2
    ok3, why3, _n3 = BB.killer_one(base, dict(good, bite=5.0))
    assert ok3 is False and "5" in why3, why3
    ok4, why4, _n4 = BB.killer_one(base, dict(good, usd_wo_top3d=-1.0))
    assert ok4 is False and "-1.00" in why4, why4
    ctl = {"kind": "perm",
           "draws": [{"bite": 0.5, "bite_neg": -0.5, "ratio": 9.0}] * 4}
    k2, w2, _ = BB.killer_two(good, ctl)
    assert k2 is False and "100 %" in w2, w2
    k3, w3, _ = BB.killer_three({"mean": 0.42, "peak": 0.9}, good)
    assert k3 is False and "42.0 %" in w3, w3
    k3b, w3b, _ = BB.killer_three({"mean": 0.03, "peak": 0.2}, good)
    assert k3b is True and "3.0 %" in w3b, w3b


@test
def пустота_не_выдаёт_себя_за_результат():
    """Ноль наблюдений при непустом входе — отказ, и ПРИЧИНА своя.

    Пустот две, и лечатся они разным: закрытых записей нет вовсе
    (считать нечего) и записи есть, но книга не взяла ни одной
    (правила отсеяли всё). Один отказ на обе причины читался бы как
    «данных нет» там, где на деле сработало правило.
    """
    cache = cache_of([rec("OPENUSDT", T0, 0.0, state="open")])
    s = BB.run(seeds=0, cache=cache, ctx=CTX, launch=launch_of(cache),
               now=NOW, log=quiet)
    assert "закрытых позиций линейки" in (s.get("error") or ""), s.get("error")
    assert "Не посчитано" in BB.report(s), BB.report(s)[:200]
    # Записи есть, но справочник запусков их не знает — фильтр возраста
    # снимает всё: это ДРУГАЯ пустота и другая причина.
    s2 = BB.run(seeds=0, cache=spread(), ctx=CTX,
                launch={"ZZZUSDT": T0 - 400 * DAY}, now=NOW, log=quiet)
    assert "ни одной закрытой сделки" in (s2.get("error") or ""), \
        s2.get("error")


@test
def прогон_и_отчёт_целиком():
    """Прогон проходит все шаги, а показ выдерживает все их состояния."""
    cache = spread(days=14, per_day=3)
    was = RP._MARKET
    RP._MARKET = NoMkt()
    try:
        s = BB.run(seeds=2, cache=cache, ctx=CTX, launch=launch_of(cache),
                   now=NOW, log=quiet)
    finally:
        RP._MARKET = was
    assert not s.get("error"), s.get("error")
    assert s["load"]["mean"] > 0 and s["base"]["bite"] is not None, s["load"]
    assert len(s["cells"]) == len(BB.GRID), s["cells"]
    assert s["control"]["n"] == 2 and s["control"]["kind"], s["control"]
    txt = BB.report(s)
    for want in ("Калибровочная пара", "Загрузка книги", "Ячейка вердикта",
                 "Контроль", "Укус коротких книг", s["killers"]["1"]["why"]):
        assert want in txt, want
    # Название контроля в таблице убийц выводится из того, что считалось,
    # а не стоит литералом: подпись не про тот розыгрыш стареет молча.
    assert ("контроль выборкой того же размера" in txt) is \
        (s["control"]["kind"] == "sample"), s["control"]["kind"]
    assert BB.report(dict(s, control=None, cells=[])), "показ без ячеек упал"


@test
def ось_и_ячейка_объявлены_заданием():
    """Ось, ячейка вердикта и пороги — из задания, а не выбраны здесь."""
    assert BB.GRID == (0.10, 0.20, 0.30), BB.GRID
    assert BB.VERDICT_B == BB.GRID[len(BB.GRID) // 2], BB.VERDICT_B
    assert float(BB.DEP_SKIP) not in BB.DEPS and BB.DEP_SKIP_WHY, BB.DEPS
    assert BB.SEEDS == AG.SEEDS and BB.BEAT_MAX == 0.10, BB.SEEDS
    assert BB.BOOK == "safe_h" and BB.RULER == "safe_s", BB.RULER


def main():
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as e:                                # noqa: BLE001
            failed.append((fn.__name__, f"{type(e).__name__}: {e}"[:110]))
    print(f"проверок {len(TESTS)}, прошло {len(TESTS) - len(failed)}, "
          f"провалов {len(failed)}")
    for name, err in failed:
        print(f"ПРОВАЛ {name}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
