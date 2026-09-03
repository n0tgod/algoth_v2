#!/usr/bin/env python3
"""
Проверки механики «смена интервала начисления funding».

Хранилища и духдб здесь нет: `shift.py` работает на рядах, а замер
(`run_ceiling.measure`) — на `PriceBook`, который тест собирает руками.
Поэтому калибровочная пара гоняется на НАСТОЯЩИХ функциях замера, а не
на их пересказе.

    cd ~/algoth_v2 && .venv/bin/python research/probe_fshift/test_fshift.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import shift as SH                                          # noqa: E402
import run_ceiling as RC                                    # noqa: E402

H = SH.MS_H
T0 = 1_700_000_000_000 // H * H          # ровный час


def eq(a, b, tol=1e-9, what=""):
    assert abs(a - b) <= tol, f"{what}: {a} != {b}"


# --- знак и сторона ---------------------------------------------------

def test_side_sign_by_number():
    """Знак закреплён ЧИСЛОМ, а не словом.

    Соглашение загрузчика: положительная ставка — лонги платят шортам.
    Значит выталкивает она лонгов, и вставать надо в шорт; отрицательная
    выталкивает шортов, и позиция длинная. Перевёрнутый знак развернул
    бы сторону ячейки вердикта молча, и весь замер описывал бы другую
    сделку — ровно так уже ловилось у probe_monthly.
    """
    assert SH.side_of_rate(-0.01) == +1, "ставка < 0 — платят шорты, мы лонг"
    assert SH.side_of_rate(+0.01) == -1, "ставка > 0 — платят лонги, мы шорт"
    assert SH.side_of_rate(0.0) is None, "нулевая ставка стороны не задаёт"
    assert SH.VERDICT_SIGN == -1


def test_funding_and_excess_signs():
    """Начисления и превышение — числами, обе стороны."""
    # Лонг при ставке −1 % за удержание получает +100 б.п.
    eq(SH.funding_bp(-0.01, +1), 100.0, what="лонг получает")
    eq(SH.funding_bp(-0.01, -1), -100.0, what="шорт платит")
    eq(SH.excess_bp(0.02, 0.01, +1), 100.0, what="лонг обогнал корзину")
    eq(SH.excess_bp(0.02, 0.01, -1), -100.0, what="шорт против корзины")
    assert not np.isfinite(SH.excess_bp(np.nan, 0.01, +1))
    assert not np.isfinite(SH.funding_bp(None, +1))


# --- события ----------------------------------------------------------

def series_8h_then_1h(n_long=40, n_short=12, rate=-0.01):
    """8 часов, затем переход на 1 час. Метка события — первый час."""
    t = [T0 + k * 8 * H for k in range(n_long)]
    t += [t[-1] + (k + 1) * H for k in range(n_short)]
    return np.array(t, dtype=np.int64), np.full(len(t), rate)


def test_shift_events_finds_shortening():
    t, r = series_8h_then_1h()
    ev = SH.shift_events(t, r)
    assert len(ev) == 1, f"ожидалось одно событие, вышло {len(ev)}"
    e = ev[0]
    eq(e["step_h"], 1.0, what="шаг события")
    eq(e["before_h"], 8.0, what="прежний режим")
    assert e["ts"] == int(t[40]), "метка — первое начисление по часу"
    assert e["side"] == +1, "ставка отрицательная — позиция длинная"


def test_no_lookahead_in_events():
    """Переписать будущее — прошлое не должно шелохнуться.

    Детектор обязан опознавать событие по режиму ДО и по шагу, который
    к событию привёл. Определение «режим до длинный, режим после
    короткий» было бы заглядыванием: режим после метки в момент метки
    неизвестен.

    Ряд подобран так, чтобы проверка КУСАЛАСЬ. Первая редакция брала
    сорок восьмичасовых начислений перед переходом, и окно режима,
    расширенное в будущее, всё равно оставалось восьмичасовым — то есть
    заглядывающий детектор давал те же события, и негативный контроль
    выходил холостым. Здесь прошлого ровно семь шагов, а будущего
    тридцать: у детектора, заглянувшего вперёд, режим переворачивается
    на часовой, и событие исчезает вовсе.
    """
    n_long = 8
    t = [T0 + k * 8 * H for k in range(n_long)]
    t += [t[-1] + (k + 1) * H for k in range(30)]
    t = np.array(t, dtype=np.int64)
    r = np.full(len(t), -0.01)
    cut = int(t[n_long])                  # метка первого часового начисления
    base = [e for e in SH.shift_events(t, r) if e["ts"] <= cut]
    assert len(base) == 1 and base[0]["ts"] == cut, (
        f"на исходном ряде обязано быть ровно одно событие: {base}")

    # Будущее переписано целиком: шаги, ставки, длина ряда.
    t2 = list(t[:n_long + 2]) + [int(t[n_long + 1]) + (k + 1) * 8 * H
                                 for k in range(30)]
    r2 = list(r[:n_long + 2]) + [0.02] * 30
    after = [e for e in SH.shift_events(np.array(t2, dtype=np.int64),
                                        np.array(r2)) if e["ts"] <= cut]
    assert base == after, ("события до границы изменились от переписи "
                           f"будущего: {base} против {after}")


def test_lookahead_probe_bites():
    """Негативный контроль самой проверки: она обязана кусаться.

    Тест на заглядывание бесполезен, если сломанный детектор его
    проходит. Здесь заведомо заглядывающий детектор строится прямо в
    тесте, и проверка обязана его отвергнуть.
    """
    def peeking(t_ms, rates, window=SH.WINDOW):
        out = []
        for i in range(1, len(t_ms)):
            step = (int(t_ms[i]) - int(t_ms[i - 1])) / H
            after = SH.FU.modal_step_hours(list(t_ms[i:i + window + 1]))
            if after is not None and step <= after * 1.001 and i > 5:
                before = SH.regime_before(t_ms, i, window)
                if before and before >= after * SH.RATIO:
                    out.append({"ts": int(t_ms[i]), "step_h": step})
        return out

    t, r = series_8h_then_1h(n_long=40, n_short=12)
    cut = int(t[41])
    a = [e for e in peeking(t, r) if e["ts"] <= cut]
    t2 = list(t[:42]) + [int(t[41]) + (k + 1) * 8 * H for k in range(30)]
    b = [e for e in peeking(np.array(t2, dtype=np.int64),
                            np.array(list(r[:42]) + [0.0] * 30))
         if e["ts"] <= cut]
    assert a != b, ("заглядывающий детектор дал те же события — "
                    "значит проверка на заглядывание ничего не проверяет")


def test_min_before_steps():
    """Режим, оценённый по паре шагов, режимом не является."""
    t = np.array([T0, T0 + 8 * H, T0 + 16 * H, T0 + 17 * H], dtype=np.int64)
    r = np.full(4, -0.01)
    assert SH.shift_events(t, r) == [], "три метки — режима ещё нет"
    t2, r2 = series_8h_then_1h(n_long=6, n_short=3)
    assert len(SH.shift_events(t2, r2)) == 1, "шести шагов уже хватает"


def test_only_first_short_accrual_is_event():
    """Событие — ПЕРВОЕ начисление по короткому интервалу.

    Без условия на предыдущий шаг переход 8ч→1ч дал бы событие на
    каждом из первых двадцати пяти часовых начислений: окно режима ещё
    состоит из восьмичасовых шагов. Так `gap_report` получала 112
    ложных пропусков у BLURUSDT.
    """
    t, r = series_8h_then_1h(n_long=40, n_short=30)
    ev = SH.shift_events(t, r)
    assert len(ev) == 1, f"переход один, событий {len(ev)}"
    # Ступенька 8ч → 4ч → 1ч есть ДВА перехода, и оба обязаны найтись.
    t2 = [T0 + k * 8 * H for k in range(40)]
    t2 += [t2[-1] + (k + 1) * 4 * H for k in range(30)]
    t2 += [t2[-1] + (k + 1) * H for k in range(30)]
    ev2 = SH.shift_events(np.array(t2, dtype=np.int64),
                          np.full(len(t2), -0.01))
    assert len(ev2) == 2, f"два перехода, событий {len(ev2)}"
    assert [e["step_h"] for e in ev2] == [4.0, 1.0]


def test_ratio_ignores_jitter():
    """Дрожание метки на минуты сменой интервала не является."""
    t = np.array([T0 + k * 8 * H + (k % 3) * 60_000 for k in range(40)],
                 dtype=np.int64)
    assert SH.shift_events(t, np.full(40, -0.01)) == []


def test_reverse_and_holding():
    t, r = series_8h_then_1h(n_long=40, n_short=5)
    # После пяти часовых начислений ряд возвращается к восьми часам.
    t = np.concatenate([t, [int(t[-1]) + 8 * H]])
    r = np.concatenate([r, [-0.01]])
    e = SH.shift_events(t, r)[0]
    entry, exit_, why = SH.holding(t, e)
    assert why == "интервал вернулся"
    eq((exit_ - entry) / H, 12.0, what="удержание до возврата")

    # Без возврата удержание упирается в предел 24 ч.
    t2, r2 = series_8h_then_1h(n_long=40, n_short=40)
    e2 = SH.shift_events(t2, r2)[0]
    entry2, exit2, why2 = SH.holding(t2, e2)
    assert why2 == "предел удержания"
    eq((exit2 - entry2) / H, 24.0, what="предел удержания")


def test_dedup_by_name():
    evs = [{"ts": T0}, {"ts": T0 + 2 * H}, {"ts": T0 + 30 * H}]
    kept = SH.dedup_by_name(evs)
    assert [e["ts"] for e in kept] == [T0, T0 + 30 * H], (
        "внутри чужого удержания вторая позиция по имени не открывается")


def test_rate_extremity():
    r = list(np.linspace(0.0001, 0.001, 40)) + [0.01]
    t = np.arange(41, dtype=np.int64) * H + T0
    rank, top = SH.rate_extremity(t, np.array(r), 40)
    eq(rank, 1.0, what="ставка выше всей своей истории")
    assert top > 9.0, "и вдесятеро выше прежнего максимума"
    assert SH.rate_extremity(t, np.array(r), 5) == (None, None), (
        "короткая история — «не измерено», а не ноль")


# --- плотность --------------------------------------------------------

def test_active_share_arithmetic():
    d0 = SH.day_of(T0)
    ts = [(d0 + k) * SH.MS_D for k in (0, 1, 5, 9)]
    d = SH.active_share(ts, d0, d0 + 9, window_d=10)
    eq(d["share"], 0.4, what="доля суток с событием")
    assert d["days"] == 10 and d["active_days"] == 4
    eq(d["med"], 0.4, what="единственное окно")


def test_active_share_empty_is_none():
    d = SH.active_share([])
    assert d["share"] is None, "доли, которой нет, ноль не заменяет"
    assert d["med"] is None and d["windows"] == 0


# --- цены: PriceBook и заполнение ------------------------------------

def test_needed_minutes_never_before_anchor():
    """Окно допуска смотрит только ВПЕРЁД от якоря.

    Минута до якоря — цена, которой в момент решения уже нет: сделка по
    ней в прошлом. Это то же правило, по которому вход берётся по
    открытию бара, а не по закрытию предыдущего.
    """
    need = RC.needed_minutes([1000 * 60, 2000 * 60], tol_min=3)
    assert need.min() == 1000 * 60, "минуты раньше якоря брать нельзя"
    assert set(need.tolist()) == {60000, 60060, 60120,
                                  120000, 120060, 120120}


def test_fill_book_takes_first_price():
    """У якоря побеждает ПЕРВАЯ доступная цена окна допуска."""
    book = RC.PriceBook(["A", "B"], [600])
    by_min = {600: (np.array([1]), np.array([50.0], dtype=np.float32)),
              660: (np.array([0, 1]), np.array([10.0, 99.0],
                                               dtype=np.float32)),
              720: (np.array([0]), np.array([77.0], dtype=np.float32))}
    # Заполнено ровно два значения, а не три: минута 720 у имени A
    # приходит позже занятой 660 и не пишется вовсе.
    n = RC.fill_book(book, by_min, tol_min=5)
    assert n == 2, f"ожидалось два заполнения, вышло {n}"
    eq(book.price(600, "A"), 10.0, what="A: ближайшая минута 660")
    eq(book.price(600, "B"), 50.0, what="B: своя минута 600, не 660")


def test_fill_book_is_order_independent():
    """Порядок, в котором хранилище вернуло строки, чисел не меняет."""
    a = RC.PriceBook(["A"], [600])
    b = RC.PriceBook(["A"], [600])
    d1 = {600: (np.array([0]), np.array([10.0], dtype=np.float32)),
          660: (np.array([0]), np.array([20.0], dtype=np.float32))}
    RC.fill_book(a, d1, tol_min=5)
    RC.fill_book(b, dict(reversed(list(d1.items()))), tol_min=5)
    eq(a.price(600, "A"), b.price(600, "A"), what="порядок словаря")
    eq(a.price(600, "A"), 10.0)


# --- кросс-секция -----------------------------------------------------

def make_book(n=120, ret=None, seed=7):
    """Сечение из `n` имён на трёх якорях: метка, метка+1, выход."""
    rng = np.random.default_rng(seed)
    syms = [f"S{i:03d}USDT" for i in range(n)]
    a0, a1, a2 = 600, 660, 600 + 6 * 3600
    book = RC.PriceBook(syms, [a0, a1, a2])
    r = rng.normal(0, 0.01, n) if ret is None else np.asarray(ret,
                                                              dtype=float)
    book.A[book.pos[a0], :] = 100.0
    book.A[book.pos[a1], :] = 100.0
    book.A[book.pos[a2], :] = 100.0 * (1.0 + r)
    return book, syms, (a0, a1, a2), r


def test_cross_mean_needs_min_cross():
    book, _, (a0, _, a2), _ = make_book(n=RC.MIN_CROSS - 1)
    v, k = RC.cross_mean(book, a0, a2, np.array([], dtype=np.int64))
    assert not np.isfinite(v), "уже сечения — контроля нет вовсе"
    assert k == RC.MIN_CROSS - 1, "но ширина обязана быть посчитана"


def test_cross_mean_excludes_banned():
    book, _, (a0, _, a2), r = make_book(n=120, ret=[0.5] + [0.0] * 119)
    ban = np.array([0], dtype=np.int64)
    v, k = RC.cross_mean(book, a0, a2, ban)
    eq(v, 0.0, tol=1e-9, what="сосед со своим событием вне фона")
    assert k == 119
    v2, _ = RC.cross_mean(book, a0, a2, np.array([], dtype=np.int64))
    assert v2 > 0.004, "без исключения фон уезжает — значит проверка живая"


def test_decile_peers_same_sign():
    rates = {f"S{i}": (0.001 * (i + 1)) for i in range(20)}
    rates.update({f"N{i}": (-0.001 * (i + 1)) for i in range(20)})
    peers = RC.decile_peers(rates, "N5", same_sign=True)
    assert peers, "дециль обязан быть непустым"
    assert all(p.startswith("N") for p in peers), (
        "контроль обязан быть той же стороны")
    any_peers = RC.decile_peers(rates, "N5", same_sign=False)
    assert any(p.startswith("S") for p in any_peers), (
        "диагностическая прочитка знак не смотрит")


# --- калибровочная пара ----------------------------------------------

def synth_case(plant, n=120, seed=11, rate=-0.01):
    """Сечение с подсаженным ходом у имени события (или без него)."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, 0.01, n)
    r[0] += plant
    book, syms, (a0, a1, a2), _ = make_book(n=n, ret=r, seed=seed)
    entry = a0 * 1000
    exit_ = a2 * 1000
    asset = "S000"
    fund = {asset: (np.array([entry - H, entry, entry + H],
                             dtype=np.int64),
                    np.array([rate, rate, rate]))}
    sym_of = {asset: syms[0]}
    for i, s in enumerate(syms[1:], start=1):
        a = f"S{i:03d}"
        fund[a] = (np.array([entry - H, entry, entry + H], dtype=np.int64),
                   np.array([rate * (1 + 0.01 * i)] * 3))
        sym_of[a] = s
    ev = [{"i": 1, "ts": entry, "rate": rate, "step_h": 1.0,
           "before_h": 8.0, "side": +1, "symbol": syms[0], "asset": asset,
           "entry_ms": entry, "exit_ms": exit_, "exit_why": "предел удержания",
           "rank": 1.0, "top": 1.0}]
    all_ts = {syms[0]: np.array([entry], dtype=np.int64)}
    return ev, book, all_ts, fund, sym_of


def test_calibration_finds_planted_move():
    """Подсаженное событие обязано находиться.

    Без этой половины пары отрицательный результат не значит ничего:
    сломанная загрузка выглядит ровно как «эффекта нет», и проект уже
    дважды печатал нулевой отчёт именно так.
    """
    ev, book, all_ts, fund, sym_of = synth_case(plant=0.05)
    rows = RC.measure(ev, book, all_ts, fund, sym_of,
                      np.random.default_rng(1), log=lambda _m: None)
    assert len(rows) == 1
    exc = rows[0]["ideal_exc_bp"]
    assert 400.0 < exc < 600.0, f"подсаженные +5 % не нашлись: {exc}"
    assert abs(rows[0]["null_bp"]) < 100.0, "нуль не обязан ловить подсадку"
    # Начисления: лонг при ставке −1 % на трёх начислениях в окне.
    assert rows[0]["fund_bp"] > 0, "лонг у нижнего предела ПОЛУЧАЕТ funding"


def test_calibration_silent_on_random_walk():
    """На случайном блуждании превышение обязано быть около нуля."""
    vals = []
    for seed in range(40):
        ev, book, all_ts, fund, sym_of = synth_case(plant=0.0, seed=seed)
        rows = RC.measure(ev, book, all_ts, fund, sym_of,
                          np.random.default_rng(seed), log=lambda _m: None)
        vals.append(rows[0]["ideal_exc_bp"])
    m = float(np.mean(vals))
    assert abs(m) < 60.0, f"на шуме превышение уехало: {m:+.1f} б.п."


def test_funding_excludes_entry_accrual():
    """Начисление в момент метки — не наше, и это закреплено ЧИСЛОМ.

    Оно достаётся тем, кто держал позицию ДО него, а мы в эту секунду
    только входим. В фикстуре начислений три (метка−1ч, метка, метка+1ч)
    при удержании в шесть часов, значит нашим является ровно одно: при
    ставке −1 % это +100 б.п., а не +200.
    """
    ev, book, all_ts, fund, sym_of = synth_case(plant=0.0)
    rows = RC.measure(ev, book, all_ts, fund, sym_of,
                      np.random.default_rng(3), log=lambda _m: None)
    eq(rows[0]["fund_bp"], 100.0, tol=1e-6,
       what="одно начисление строго внутри удержания")


def test_peer_funding_is_measured_from_peer_series():
    """Начисления соседа считаются по ЕГО ряду и тем же окном.

    Без этого числа отношение (в) сравнивало бы ценовую ногу события с
    ценовой ногой контроля и молчало бы о том, что обе стороны получают
    одну и ту же ставку: «carry в новом костюме» осталось бы догадкой
    вместо проверяемой колонки.
    """
    ev, book, all_ts, fund, sym_of = synth_case(plant=0.0)
    rows = RC.measure(ev, book, all_ts, fund, sym_of,
                      np.random.default_rng(9), log=lambda _m: None)
    r = rows[0]
    assert np.isfinite(r["c2_fund_bp"]), "у соседей ставка есть — величина тоже"
    # У соседа ставка своя (rate·(1+0.01·i)), значит и начисления другие.
    assert abs(r["c2_fund_bp"] - r["fund_bp"]) > 1e-6, (
        "начисления соседа посчитаны по чужому ряду")
    # Знак тот же: обе стороны в лонге при отрицательной ставке ПОЛУЧАЮТ.
    assert r["c2_fund_bp"] > 0


def test_anchors_pre_window_mirrors_holding():
    """Окно ДО метки — зеркало удержания, и оно строго перед меткой."""
    e = {"entry_ms": 3_600_000_000, "exit_ms": 3_600_000_000 + 6 * H}
    A = RC.anchors_of(e)
    assert A["pre"] < A["mark"] < A["real"] < A["out"]
    eq(A["mark"] - A["pre"], A["out"] - A["mark"],
       what="длина окна до равна длине удержания")
    assert A["real"] - A["mark"] == 60


def test_pre_window_is_measured():
    """Четвёртое условие смерти обязано опираться на посчитанное число."""
    ev, book, all_ts, fund, sym_of = synth_case(plant=0.05)
    # У окна ДО метки свои якоря: без цены на них величины не будет.
    A = RC.anchors_of(ev[0])
    assert A["pre"] not in book.pos, "фикстура цен до метки не держит"
    rows = RC.measure(ev, book, all_ts, fund, sym_of,
                      np.random.default_rng(5), log=lambda _m: None)
    assert "pre_exc_bp" in rows[0], "величина обязана считаться всегда"
    assert not np.isfinite(rows[0]["pre_exc_bp"]), (
        "цен до метки нет — прочерк, а не ноль")


def test_measure_reports_missing_price_as_gap():
    """Цены нет — величины нет; ноль тут читался бы как «не двигалась»."""
    ev, book, all_ts, fund, sym_of = synth_case(plant=0.05)
    book.A[:, 0] = np.nan                       # у имени события цен нет
    rows = RC.measure(ev, book, all_ts, fund, sym_of,
                      np.random.default_rng(1), log=lambda _m: None)
    assert not np.isfinite(rows[0]["ideal_exc_bp"])
    assert "c2_bp" not in rows[0], (
        "контроль 2 считается только там, где событие измерено")


# --- вердикт ----------------------------------------------------------

DENS = {"share": 0.9}
GOOD = {"n": 100, "mean": 80.0, "med": 60.0}
C2 = {"n": 100, "mean": 10.0, "med": 8.0}
NUL = {"n": 100, "mean": 0.2, "med": 0.1}
PRE = {"n": 100, "mean": 3.0, "med": 2.0}
BIG = 100                    # событий заведомо больше порога измеримости


def vd(dens=None, ex=None, c2=None, rank=0.8, null=None, pre=None,
       n=BIG):
    return RC.verdict(dens or DENS, ex or GOOD, c2 or C2, rank,
                      null or NUL, pre or PRE, n)


def test_verdict_derived_from_numbers():
    """Фраза вердикта выводится из числа, а не стоит рядом литералом."""
    _lines, dead, doubt = vd()
    assert dead == [], f"здоровые числа не обязаны никого убивать: {dead}"
    assert doubt == [], doubt

    _l, dead2, _ = vd(ex={"n": 100, "mean": 5.0, "med": 4.0})
    assert any("круг" in d for d in dead2), dead2

    _l, dead3, _ = vd(dens={"share": 0.1})
    assert any("плотность" in d for d in dead3), dead3

    _l, dead4, _ = vd(ex={"n": 100, "mean": -30.0, "med": 60.0})
    assert any("расходятся знаком" in d for d in dead4), dead4

    _l, dead5, _ = vd(c2={"n": 100, "mean": 70.0, "med": 60.0})
    assert any("контролю 2" in d for d in dead5), dead5

    _l, dead6, _ = vd(rank=0.1)
    assert any("предела" in d for d in dead6), dead6

    # Четвёртое объявленное условие: превышение живёт ДО метки.
    _l, dead7, _ = vd(pre={"n": 100, "mean": 120.0, "med": 90.0})
    assert any("до метки" in d for d in dead7), dead7


def test_verdict_threshold_comes_from_factory():
    """Порог измеримости формы взят у потолка фабрики, а не назначен."""
    assert RC.FCE.MIN_ACTIVE_SHARE == RC.FCE.SB.MIN_DAYS / float(
        RC.FCE.PL.IDLE_D)
    lines, _d, _q = vd(dens={"share": RC.FCE.MIN_ACTIVE_SHARE})
    row = [r for r in lines if r[0] == "плотность"][0]
    assert f"{RC.FCE.MIN_ACTIVE_SHARE:.2f}" in row[1], row
    assert row[2] == "", "ровно на пороге форма ещё измерима"


def test_verdict_says_not_measured_not_dead():
    """«Не измерено» — не то же, что «условие сработало»."""
    empty = {"n": 0, "mean": None, "med": None}
    lines, dead, _q = RC.verdict({"share": None}, empty, empty, None,
                                 empty, empty, BIG)
    assert dead == [], dead
    assert all(("не измерен" in r[2] or r[2] == "") for r in lines), lines


def test_verdict_withholds_on_thin_sample():
    """На горстке событий вердикт не выносится вовсе.

    Смоук даёт единицы событий, и без этого правила он читался бы как
    закрытие механики: таблица та же, слова те же, а под ними восемь
    наблюдений.
    """
    _l, dead, doubt = vd(dens={"share": 0.1}, n=RC.MIN_MEASURED - 1)
    assert dead == [], f"на тонкой выборке закрывать нечем: {dead}"
    assert any("меньше" in d for d in doubt), doubt
    _l2, dead2, _ = vd(dens={"share": 0.1}, n=RC.MIN_MEASURED)
    assert dead2, "ровно на пороге вердикт уже выносится"


def test_null_is_calibration_not_a_kill():
    """Нуль калибрует меру, а не судит механику.

    Своего порога заявка нулю не объявляла, и добавлять его в
    «сработало» значило бы назначить пятое условие смерти после
    результата.
    """
    _l, dead, doubt = vd(null={"n": 100, "mean": -12.4, "med": -7.7})
    assert dead == [], f"нуль не вправе закрывать механику: {dead}"
    assert any("нуль" in d for d in doubt), doubt


def test_daily_net_matches_exit_rule_shape():
    """Ряд суток отдаётся в той форме, в какой его судит правило вылета."""
    sys.path.insert(0, os.path.join(RC.RESEARCH, "factory"))
    import stability as SB                                   # noqa: E402
    rows = [{"ts": T0 + k * SH.MS_D, "ideal_exc_bp": 40.0 + k,
             "fund_bp": 5.0} for k in range(12)]
    daily = RC.daily_net(rows)
    assert len(daily) == 12 and all(isinstance(k, str) for k in daily)
    st = SB.stats(daily)
    assert st and st["days"] == 12 and st["thin"] is False
    eq(daily[sorted(daily)[0]], 40.0 + 5.0 - RC.NEUTRAL_COST_BP,
       what="нетто суток = превышение + начисления − круг")


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    bad = 0
    for fn in ALL:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            bad += 1
            # Формат строки провала — тот же, что у машины негативных
            # контролей фабрики (`ПРОВАЛ имя — сообщение`): она узнаёт
            # ИМЕННУЮ проверку по нему, а контроль, роняющий что-то
            # постороннее, ничего не доказывает о своём правиле.
            print(f"  ПРОВАЛ {fn.__name__} — {e}")
        except Exception as e:                              # noqa: BLE001
            bad += 1
            print(f"  ПРОВАЛ {fn.__name__} — {type(e).__name__}: {e}")
    print(f"\nпроверок {len(ALL)}, провалов {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
