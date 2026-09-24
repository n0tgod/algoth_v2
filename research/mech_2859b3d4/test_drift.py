#!/usr/bin/env python3
"""
Проверки механики «дрейф после экстремального начисления funding».

Хранилища здесь нет: `drift.py` работает на списках снимков, и тест
собирает такой список руками за миллисекунды. Поэтому и калибровочная
пара, и проверка на заглядывание в будущее гоняются на НАСТОЯЩИХ
функциях замера (`measure_event`, `percentile_among`), а не на их
пересказе — иначе проверялся бы тест, а не механика.

Что здесь обязано быть и есть:

* **заглядывание в будущее** — переписать запись ПОСЛЕ выхода, и ни
  одно число сделки не шелохнётся; одновременно проверено, что тест не
  холостой: правка ВНУТРИ позиции числа меняет;
* **калибровочная пара** — подсаженный дрейф −50 б.п. за полчаса обязан
  поднять перцентиль события среди контролей к 1 (assert на литерал), а
  чистый шум обязан оставить его у 0.5;
* **отказ вместо пустоты** — ноль наблюдений при непустом входе есть
  исключение, а не отчёт с прочерками;
* **прочерк вместо нуля** — лесенка, не покрывшая билет, и пустая лента
  дают None, а не 0.0;
* **вердиктовая фраза из числа** — фраза каждого убийцы выведена из его
  же числа, и подделка числа меняет фразу.

    cd ~/algoth_v2 && .venv/bin/python research/mech_2859b3d4/test_drift.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import drift as DR                                           # noqa: E402

MS = DR.MS_S
T0 = 1_789_876_800_000                # ровная граница часа UTC
DAY0 = (T0 // DR.MS_D) * DR.MS_D


def eq(a, b, tol=1e-6, what=""):
    assert a is not None and abs(a - b) <= tol, f"{what}: {a} != {b}"


# --- сборка синтетической записи --------------------------------------

def snap(ts, px, spread_bp=2.0, levels=12, usd=300.0, step_bp=5.0,
         depth_b=3602.0, depth_a=3222.0):
    """Снимок стакана той же формы, что пишет сборщик.

    Поля глубины подставляются ЧИСЛОМ, не считаются по уровням: в записи
    их считает сборщик на полном стакане, и тест обязан проверять, что
    модуль берёт поле записи, а не пересчитывает срез.
    """
    half = px * spread_bp / 2.0 / 1e4
    bid, ask = px - half, px + half
    b = [[bid * (1 - i * step_bp / 1e4),
          usd / (bid * (1 - i * step_bp / 1e4))] for i in range(levels)]
    a = [[ask * (1 + i * step_bp / 1e4),
          usd / (ask * (1 + i * step_bp / 1e4))] for i in range(levels)]
    return {"ts": int(ts), "bid": bid, "ask": ask, "b": b, "a": a,
            "bq0.0025": depth_b, "aq0.0025": depth_a}


def tape(t_ms, mids, step_ms=2000, **kw):
    """Список снимков по ряду середин с шагом `step_ms` от `t_ms`."""
    return [snap(t_ms + i * step_ms, m, **kw) for i, m in enumerate(mids)]


def flat_tape(t_ms, px=100.0, lo_s=-60, hi_s=1900, step_ms=2000, **kw):
    n = int((hi_s - lo_s) * MS / step_ms) + 1
    return tape(t_ms + lo_s * MS, [px] * n, step_ms, **kw)


# --- полосы, сторона, ноги --------------------------------------------

def test_bands_by_number():
    """Границы полос — числами, включая саму границу.

    Полоса замкнута снизу: ставка ровно в −1 % обязана попасть в
    соседнюю полосу, а не выпасть из замера молча.
    """
    assert DR.band_of(-0.02) == "lt1", "−2 % — ячейка вердикта"
    assert DR.band_of(-0.0100001) == "lt1"
    assert DR.band_of(-0.01) == "m1_m05", "ровно −1 % — уже не событие"
    assert DR.band_of(-0.006) == "m1_m05"
    assert DR.band_of(-0.005) == "m05_m02"
    assert DR.band_of(-0.0021) == "m05_m02"
    assert DR.band_of(0.003) == "pos"
    assert DR.band_of(0.0) == "quiet"
    assert DR.band_of(0.0004) == "quiet"
    assert DR.band_of(-0.001) is None, "между полосами — не тишина"
    assert DR.band_of(None) is None and DR.band_of(np.nan) is None
    assert DR.VERDICT_BAND == "lt1"


def test_side_by_number():
    """Сторона ячейки — ШОРТ, и это закреплено числом.

    Рефлекс carry при отрицательной ставке — длинная позиция (ставку
    платят шорты). Здесь утверждается противоположное: позиция
    открывается ПОСЛЕ расчёта, когда выплата уже произошла. Знак,
    перевёрнутый молча, описывал бы другую сделку целиком.
    """
    assert DR.side_of_band("lt1") == -1, "после −1 % встаём в ШОРТ"
    assert DR.side_of_band("m1_m05") == -1
    assert DR.side_of_band("pos") == +1, "после плюса — длинная"
    assert DR.side_of_band("quiet") == -1, "тишина меряется той же стороной"
    assert DR.side_of_band("нет такой") is None


def test_legs_by_side():
    """Шорт продаёт в биды и выкупает с асков, лонг наоборот."""
    assert DR.legs_of(-1) == ("b", "a")
    assert DR.legs_of(+1) == ("a", "b")


# --- окна входа и выхода ----------------------------------------------

def test_entry_not_before_third_second():
    """Вход — первый снимок НЕ РАНЬШЕ третьей секунды.

    Ожидание стоит ЛИТЕРАЛОМ, а не через саму константу: проверка,
    построенная на проверяемом числе, тавтологична и проходит при любом
    его значении. Ровно это и показала машина контролей — первая версия
    была холостой.
    """
    assert DR.ENTRY_LAG_S == 3, DR.ENTRY_LAG_S
    sn = tape(T0, [100.0] * 2000, step_ms=1000)
    i_in, i_out, why = DR.entry_exit([s["ts"] for s in sn], T0)
    assert why is None, why
    eq(sn[i_in]["ts"] - T0, 3 * MS, what="метка входа")
    assert sn[i_in]["ts"] > T0, "вход не вправе стоять в секунду расчёта"


def test_entry_window_upper_bound_bites():
    """Дыра записи на входе — событие НЕПОКРЫТО, а не вход попозже.

    Без верхней границы «первый снимок не раньше T+3 с» на дыре молча
    берёт снимок через сорок секунд, и сделка оказывается другой — той,
    которую никто не объявлял.

    Дыра построена ЛИТЕРАЛОМ в сорок секунд, а не от самой границы:
    фикстура, растущая вместе с проверяемым числом, проходит при любом
    его значении. Первая версия была именно такой и не укусила.
    """
    assert DR.ENTRY_MAX_LAG_S == 10, DR.ENTRY_MAX_LAG_S
    ts = ([T0 - 2000, T0 - 1000]
          + [T0 + 40 * MS + i * 1000 for i in range(2000)])
    i_in, i_out, why = DR.entry_exit(ts, T0)
    assert i_in is None and why and "снимка входа" in why, why


def test_exit_horizon_is_half_an_hour():
    """Выход — первый снимок не раньше T+1800 с."""
    sn = tape(T0, [100.0] * 1000, step_ms=2000)
    i_in, i_out, why = DR.entry_exit([s["ts"] for s in sn], T0)
    assert why is None, why
    lag = sn[i_out]["ts"] - T0 - DR.EXIT_S * MS
    assert 0 <= lag <= DR.EXIT_MAX_LAG_S * MS, lag
    assert DR.EXIT_S == 1800, DR.EXIT_S


def test_exit_window_upper_bound_bites():
    """Дыра записи на выходе — событие НЕПОКРЫТО, а не цена из другого часа."""
    ts = [T0 + i * 1000 for i in range(600)]
    ts += [T0 + (DR.EXIT_S + 600) * MS]          # снимок сильно позже
    _i, _j, why = DR.entry_exit(ts, T0)
    assert why and "снимка выхода" in why, why


# --- заглядывание в будущее -------------------------------------------

def test_no_lookahead_past_exit():
    """Переписать будущее — прошлое не шелохнётся.

    И тут же проверено, что тест не холостой: правка ВНУТРИ позиции
    числа менять обязана. Проверка без этой половины однажды прошла бы
    на коде, который вообще не смотрит на цену.
    """
    mids = [100.0 - 0.001 * i for i in range(1000)]
    sn = tape(T0 - 60 * MS, mids, step_ms=2000)
    base = DR.measure_event(sn, T0, -1)
    assert base["used"], base["why"]
    edge = T0 + (DR.EXIT_S + DR.PROFILE_TOL_S) * MS
    after = []
    for s in sn:
        if s["ts"] <= edge:
            after.append(s)
            continue
        m = DR.mid(s) * 3.0                       # будущее переписано втрое
        after.append(snap(s["ts"], m))
    got = DR.measure_event(after, T0, -1)
    for k in ("entry_ts", "exit_ts", "flat_bp", "walk_bp", "mid_out"):
        assert base[k] == got[k], f"{k}: будущее просочилось в прошлое"
    p0 = DR.profile_bp(sn, T0)
    p1 = DR.profile_bp(after, T0)
    assert p0 == p1, "профиль изменился от переписанного будущего"
    inside = [snap(s["ts"], DR.mid(s) * (0.5 if s["ts"] >= base["exit_ts"]
                                         and s["ts"] <= edge else 1.0))
              for s in sn]
    other = DR.measure_event(inside, T0, -1)
    assert other["flat_bp"] != base["flat_bp"], \
        "правка ВНУТРИ позиции ничего не изменила — проверка холостая"


def test_snapshots_must_be_sorted():
    """Снимки не по возрастанию — громкий отказ, а не тихая чепуха."""
    sn = tape(T0, [100.0] * 100, step_ms=2000)
    sn[5], sn[6] = sn[6], sn[5]
    try:
        DR.measure_event(sn, T0, -1)
    except ValueError:
        return
    raise AssertionError("перепутанный порядок снимков прошёл молча")


# --- позиция и расчёт --------------------------------------------------

def test_position_never_spans_accrual():
    """Позиция, которая прошла бы через расчёт, сделкой не становится.

    Это свойство ячейки, а не случайность расписания: удержание через
    начисление — другая сделка, с выплатой внутри.
    """
    sn = flat_tape(T0)
    ok = DR.measure_event(sn, T0, -1, next_accrual_ms=T0 + 4 * DR.MS_H)
    assert ok["used"] and ok["flat_bp"] is not None
    bad = DR.measure_event(sn, T0, -1, next_accrual_ms=T0 + 1200 * MS)
    assert bad["cover"] is True, "запись-то есть — K0 судит запись"
    assert bad["used"] is False and bad["flat_bp"] is None
    assert "начисление внутри позиции" in (bad["why"] or ""), bad["why"]


# --- арифметика --------------------------------------------------------

def test_take_bp_numbers():
    """Взятие — числами, обе стороны, с кругом и без."""
    eq(DR.take_bp(100.0, 99.0, -1, 0.0), 100.0, what="шорт на падении")
    eq(DR.take_bp(100.0, 101.0, -1, 0.0), -100.0, what="шорт на росте")
    eq(DR.take_bp(100.0, 101.0, +1, 0.0), 100.0, what="лонг на росте")
    eq(DR.take_bp(100.0, 99.0, -1, 19.8), 80.2, what="шорт минус круг")
    assert DR.take_bp(None, 99.0, -1, 0.0) is None
    assert DR.take_bp(0.0, 99.0, -1, 0.0) is None


def test_cost_model_numbers():
    """Круг 19.8 б.п. = комиссия 11 + проскальзывание X3 4.4 × 2 ноги.

    Оба числа ввезены из своих модулей, а не повторены здесь: копия
    комиссии однажды разошлась бы с кассой. У прохода по лесенке
    проскальзывание уже в цене — второй раз константой оно не платится.
    """
    eq(DR.COMMISSION_BP, 11.0, what="комиссия тейкера на круг")
    eq(DR.SLIP_BP, 4.4, what="проскальзывание X3 на ногу")
    eq(DR.FLAT_COST_BP, 19.8, what="плоский круг")
    eq(DR.WALK_COST_BP, DR.COMMISSION_BP, what="круг прохода по лесенке")
    assert DR.WALK_COST_BP < DR.FLAT_COST_BP, \
        "проход по лесенке заплатил бы проскальзывание дважды"


def test_flow_sign_by_number():
    """Перевес продаж — величина ПОЛОЖИТЕЛЬНАЯ, и это число.

    Сторона принта — сторона агрессора (+1 «купили по аску»).
    Перевёрнутый знак превратил бы принудительный поток продаж в поток
    покупок, не уронив ничего.
    """
    pr = [(T0 + 1000, -1, 100.0, 3.0), (T0 + 2000, +1, 100.0, 1.0)]
    f, n = DR.flow_usd(pr, T0, T0 + 60 * MS)
    eq(f, 200.0, what="продано минус куплено")
    assert n == 2
    f2, n2 = DR.flow_usd(pr, T0 + 10 * MS, T0 + 60 * MS)
    assert f2 is None and n2 == 0, "пустая лента — прочерк, а не ноль"


def test_empty_tape_is_dash_not_zero():
    """Ленты нет — прочерк. Ноль означал бы «мерили и вышло поровну»."""
    assert DR.flow_usd([], T0, T0 + 1000) == (None, 0)
    assert DR.flow_usd(None, T0, T0 + 1000) == (None, 0)


# --- лесенка -----------------------------------------------------------

def test_walk_numbers():
    """Проход по лесенке — числами, и он ХУЖЕ лучшей цены.

    Билет 100 $ на уровнях 100 $ × 1 и 99 $ × 1 съедает первый уровень
    целиком, поэтому средняя цена продажи равна 100. Билет 199 $ съедает
    оба и даёт ровно 99.5.
    """
    lv = [(100.0, 1.0), (99.0, 1.0), (98.0, 1.0)]
    p, coins = DR.walk_open(lv, 100.0)
    eq(p, 100.0, what="билет в один уровень")
    eq(coins, 1.0, what="монет")
    p2, c2 = DR.walk_open(lv, 199.0)
    eq(p2, 99.5, what="билет в два уровня")
    eq(c2, 2.0, what="монет на двух уровнях")
    assert p2 < lv[0][0], "проход обязан быть хуже лучшей цены"
    eq(DR.walk_close([(100.0, 1.0), (101.0, 1.0)], 2.0), 100.5,
       what="выкуп двух уровней")


def test_walk_ignores_input_order():
    """Порядок уровней наводится модулем, а не предполагается.

    Проход, начатый не с лучшей цены, даёт исполнение лучше возможного —
    ошибку, которая выглядит как эдж.
    """
    s = snap(T0, 100.0)
    good = DR.ladder(s, "b")
    s2 = dict(s)
    s2["b"] = list(reversed(s["b"]))
    assert DR.ladder(s2, "b") == good, "перемешанная лесенка легла иначе"
    a = DR.ladder(s, "a")
    assert a[0][0] < a[-1][0], "аски обязаны идти от лучшей цены вверх"
    assert good[0][0] > good[-1][0], "биды обязаны идти от лучшей вниз"


def test_thin_ladder_is_a_dash_not_zero():
    """Лесенки не хватило на билет — прочерк, а не частичное исполнение.

    Цена за пределами записи неизвестна. Частичное исполнение, выданное
    за полное, польстило бы входу; ноль означал бы «проскальзывания
    нет».
    """
    assert DR.walk_open([(100.0, 1.0)], 1000.0) is None
    assert DR.walk_close([(100.0, 1.0)], 5.0) is None
    thin = flat_tape(T0, usd=5.0)                 # уровни по 5 $
    row = DR.measure_event(thin, T0, -1, ticket_usd=1000.0)
    assert row["used"] is True, row["why"]
    assert row["flat_bp"] is not None, "плоская модель считается всегда"
    assert row["walk_bp"] is None, "тонкая лесенка обязана дать прочерк"
    fat = flat_tape(T0, usd=300.0)
    assert DR.measure_event(fat, T0, -1)["walk_bp"] is not None


def test_depth_is_field_of_record():
    """Глубина в 25 б.п. — ПОЛЕ записи, а не наш пересчёт среза."""
    s = snap(T0, 100.0, depth_b=1234.0, depth_a=4321.0)
    eq(DR.depth_usd(s, "b"), 1234.0, what="глубина бидов")
    eq(DR.depth_usd(s, "a"), 4321.0, what="глубина асков")
    assert DR.depth_usd({"ts": 1}, "b") is None, "поля нет — прочерк"


# --- отказ вместо пустоты ---------------------------------------------

def test_empty_is_refusal_not_zero():
    """Ноль наблюдений при непустом входе — отказ, а не нули."""
    for bad in ([], [None, None], [np.nan]):
        try:
            DR.stat_block(bad)
        except DR.Empty:
            continue
        raise AssertionError(f"пустота притворилась результатом: {bad!r}")
    try:
        DR.form([{"ts": T0, "flat_bp": None, "ticket": 1000.0}])
    except DR.Empty:
        pass
    else:
        raise AssertionError("форма без единых суток притворилась отчётом")


def test_zeroed_rates_give_no_event_not_zero():
    """Обнулённая ставка даёт ПУСТОЕ множество событий, а не нулевое.

    Сломанная загрузка рядов обязана выглядеть как «событий нет», а не
    как «эффект равен нулю»: второе неотличимо от измеренного нуля.
    """
    zeroed = [0.0] * 500
    assert not [r for r in zeroed if DR.band_of(r) == DR.VERDICT_BAND]
    assert all(DR.band_of(r) == "quiet" for r in zeroed)
    try:
        DR.stat_block([])
    except DR.Empty:
        return
    raise AssertionError("пустое множество событий дало отчёт")


# --- K0 ----------------------------------------------------------------

def _row(ts, cover=True, used=True, bp=10.0, sym="AAAUSDT", why=None,
         in_record=True, entry_ok=None):
    return {"ts": ts, "sym": sym, "in_record": in_record, "cover": cover,
            "entry_ok": cover if entry_ok is None else entry_ok,
            "used": used, "why": why,
            "flat_bp": bp if used else None, "walk_bp": bp if used else None,
            "ticket": 1000.0}


def test_k0_phrase_follows_number():
    """Вердиктовая фраза выведена ИЗ ЧИСЛА, а не стоит рядом с ним.

    Фраза, поставленная рядом, стареет молча и однажды противоречит
    своему же числу.
    """
    full = [_row(T0 + i * DR.MS_D) for i in range(10)]
    r = DR.k0(full)
    assert r["ok"] is True and "судим рынок" in r["say"], r["say"]
    assert f"{1.0:.1%}" in r["say"], r["say"]
    half = full[:3] + [_row(T0 + i * DR.MS_D, cover=False, used=False,
                            why="нет снимка входа в окне T+3…10 с")
                       for i in range(7)]
    r2 = DR.k0(half)
    assert r2["ok"] is False and "БЛОК" in r2["say"], r2["say"]
    assert "30.0%" in r2["say"], r2["say"]
    assert r2["why"] and sum(r2["why"].values()) == 7, r2["why"]
    assert DR.k0([])["ok"] is None, "событий нет — не измерено, а не провал"


def test_k0_denominator_is_what_the_record_covers():
    """Начисление имени, которого запись не вела, — НЕ брак сборщика.

    Состав записи рос ступенями 25 → 518 → 559 → 725 имён. Считать
    такое событие непокрытым значило бы судить сборщик за то, что
    инструмент тогда не собирали, — и блокировать замер по величине,
    которая о качестве записи не говорит ничего. Оба числа обязаны
    стоять в фразе.
    """
    rows = [_row(T0 + i) for i in range(9)]
    rows += [_row(T0 + 100, cover=False, used=False, in_record=False,
                  why="снимков имени вокруг расчёта нет: запись его не вела")
             for _ in range(40)]
    rows += [_row(T0 + 200, cover=False, used=False, entry_ok=False,
                  why="нет снимка входа в окне T+3…10 с")]
    r = DR.k0(rows)
    assert r["in_record"] == 10 and r["cover"] == 9, r
    eq(r["share"], 0.9, what="покрытие среди покрытых записью")
    assert r["ok"] is True, r["say"]
    assert "40 начислений запись не вела" in r["say"], r["say"]
    blind = [_row(T0 + i, cover=False, used=False, in_record=False,
                  why="запись его не вела") for i in range(5)]
    rb = DR.k0(blind)
    assert rb["ok"] is None and "не измерено, а не равно нулю" in rb["say"], \
        rb["say"]


# --- K1 ----------------------------------------------------------------

def test_k1_control_share_rule():
    """Мертва, если случайная не хуже в ≥ 5 % зёрен хотя бы по одной
    величине. Порог — тот, что объявлен заявкой, и он сравнивается
    НЕСТРОГО: ровно 5 % это уже смерть."""
    ev = [10.0] * 20
    sh = DR.seed_shares(ev, [[-100.0]] * 20, seeds=50)
    assert DR.k1(sh)["ok"] is True, sh
    eq(sh["share_sum"], 0.0, what="случайная хуже во всех зёрнах")
    sh2 = DR.seed_shares(ev, [[1000.0]] * 20, seeds=50)
    assert DR.k1(sh2)["ok"] is False and "МЕРТВА" in DR.k1(sh2)["say"]
    eq(DR.K1_MAX_SHARE, 0.05, what="порог заявки")
    assert DR.k1({"share_sum": 0.05, "share_med": 0.0})["ok"] is False, \
        "ровно порог обязан убивать"
    assert DR.k1({"share_sum": 0.049, "share_med": 0.0})["ok"] is True
    assert DR.k1(None)["ok"] is None


def test_k1_compares_same_size_sample():
    """Выборка контроля ТОГО ЖЕ размера: событие без пула выбывает.

    Сравнение выборок разного размера отвечало бы на другой вопрос —
    про число наблюдений, а не про величину.
    """
    sh = DR.seed_shares([1.0, 2.0, 3.0], [[0.0], [], [0.0]], seeds=10)
    assert sh["n"] == 2, sh
    eq(sh["ev_sum"], 4.0, what="сумма событий с непустым пулом")
    try:
        DR.seed_shares([1.0], [[]], seeds=10)
    except DR.Empty:
        return
    raise AssertionError("пустые пулы дали отчёт вместо отказа")


def test_percentile_zero_is_half():
    """Нуль перцентиля — 0.5, и это проверено числом."""
    eq(DR.percentile_among(5.0, [1.0, 2.0, 8.0, 9.0]), 0.5, what="нуль")
    eq(DR.percentile_among(99.0, [1.0, 2.0]), 1.0, what="лучше всех")
    eq(DR.percentile_among(-99.0, [1.0, 2.0]), 0.0, what="хуже всех")
    assert DR.percentile_among(1.0, []) is None
    assert DR.percentile_among(None, [1.0]) is None


# --- калибровочная пара -----------------------------------------------

def _name_day(seed, planted_bp=0.0, hours=24, ev_hour=12, step_ms=4000,
              sigma_bp=0.2):
    """Сутки одного имени: 24 границы часа, у одной подсажен дрейф.

    Возвращает (строка события, строки контролей). Считается НАСТОЯЩИМ
    `measure_event` — иначе калибровалась бы фикстура, а не замер.
    """
    rng = np.random.default_rng(seed)
    ev_row, ctl = None, []
    n = int((DR.EXIT_S + 120) * MS / step_ms)
    for k in range(hours):
        t = DAY0 + k * DR.MS_H
        steps = rng.normal(0.0, sigma_bp, size=n)
        mids, px = [], 100.0
        for i, d in enumerate(steps):
            px *= (1.0 + d / 1e4)
            if k == ev_hour and planted_bp:
                # Подсаженный дрейф: ровно `planted_bp` за окно позиции.
                px_planted = px * (1.0 + planted_bp / 1e4 * (i / len(steps)))
                mids.append(px_planted)
            else:
                mids.append(px)
        sn = tape(t - 60 * MS, mids, step_ms=step_ms)
        row = DR.measure_event(sn, t, -1)
        row["sym"] = "CALUSDT"
        if k == ev_hour:
            ev_row = row
        elif abs(k - ev_hour) >= DR.CONTROL_GAP_H:
            ctl.append(row)
    return ev_row, ctl


def test_calibration_finds_planted_drift():
    """Подсаженный дрейф −50 б.п. за полчаса — перцентиль РОВНО 1.

    Литерал в assert намеренно: без такой половины пары сломанная
    загрузка выглядит ровно как «эффекта нет», и в этом проекте так уже
    бывало дважды.
    """
    ev, ctl = _name_day(7, planted_bp=-50.0)
    assert ev["used"], ev["why"]
    p = DR.percentile_among(DR.usd_of(ev),
                            [DR.usd_of(c) for c in ctl])
    assert p == 1.0, f"подсаженный дрейф не найден: перцентиль {p}"
    assert DR.usd_of(ev) > 0, "дрейф в −50 б.п. обязан перебить круг 19.8"
    c = DR.calib_percentile([ev], {("CALUSDT", DR.day_no(ev["ts"])): ctl},
                            lambda r: (r["sym"], DR.day_no(r["ts"])))
    eq(c["mean"], 1.0, what="средний перцентиль подсаженного")


def test_calibration_silent_on_noise():
    """Чистый шум — перцентиль у 0.5, и замер молчит.

    Вторая половина пары: измеритель, который «находит» эффект в
    случайном блуждании, не измеритель.
    """
    ps = []
    for seed in range(24):
        ev, ctl = _name_day(100 + seed, planted_bp=0.0)
        p = DR.percentile_among(DR.usd_of(ev), [DR.usd_of(c) for c in ctl])
        assert p is not None
        ps.append(p)
    m = float(np.mean(ps))
    assert abs(m - 0.5) <= 0.15, \
        f"на шуме перцентиль ушёл от нуля 0.5: {m:.3f} по {len(ps)} суткам"


# --- K2 ----------------------------------------------------------------

def test_k2_rule_and_thin_ladder():
    """Мертва при медиане взятия ≤ 0 либо медиане дня < 0; событие без
    прохода считается ОТДЕЛЬНО, а не нулём."""
    good = [_row(T0 + i * DR.MS_D, bp=50.0) for i in range(12)]
    r = DR.k2(good)
    assert r["ok"] is True and r["thin"] == 0, r
    bad = [_row(T0 + i * DR.MS_D, bp=-5.0) for i in range(12)]
    assert DR.k2(bad)["ok"] is False and "МЕРТВА" in DR.k2(bad)["say"]
    thin = [dict(x, walk_bp=None) for x in good]
    r3 = DR.k2(thin)
    assert r3["ok"] is None and r3["n"] == 0, r3
    assert "не посчитан" in r3["say"], r3["say"]
    mixed = good + [dict(_row(T0, bp=50.0), walk_bp=None)]
    assert DR.k2(mixed)["thin"] == 1, "событие без прохода обязано считаться"


# --- K3 ----------------------------------------------------------------

def test_k3_placebo_rule():
    """Мертва, если медиана события НЕ ВЫШЕ p95 плацебо-медиан."""
    pool = list(np.linspace(-10.0, 10.0, 400))
    sh = DR.placebo_shares(100.0, pool, 30, seeds=50)
    assert DR.k3(sh)["ok"] is True, sh
    sh2 = DR.placebo_shares(-100.0, pool, 30, seeds=50)
    assert DR.k3(sh2)["ok"] is False and "МЕРТВА" in DR.k3(sh2)["say"]
    assert DR.k3(None)["ok"] is None
    try:
        DR.placebo_shares(1.0, [1.0, 2.0], 30, seeds=10)
    except DR.Empty:
        return
    raise AssertionError("пул меньше числа событий дал отчёт")


# --- K4 ----------------------------------------------------------------

def test_k4_waits_for_calendar():
    """До календаря вердикта НЕТ ВОВСЕ: не измерено не есть провал."""
    d0 = DR.forward_day()
    few = [_row((d0 + i) * DR.MS_D, bp=50.0) for i in range(5)]
    r = DR.k4(few, from_day=d0)
    assert r["ok"] is None and "вердикта нет" in r["say"], r["say"]
    assert str(DR.K4_MIN_EVENTS) in r["say"], r["say"]


def test_k4_judges_by_pool_rule():
    """Форму судит ПРАВИЛО ПУЛА, а не своя копия укуса."""
    d0 = DR.forward_day()
    rows = []
    for i in range(12):
        for j in range(3):
            rows.append(_row((d0 + i) * DR.MS_D + j, bp=40.0))
    r = DR.k4(rows, from_day=d0)
    assert r["ok"] is True, r
    # Медиана дня отрицательна — правило пула обязано отставить.
    bad = [_row((d0 + i) * DR.MS_D + j, bp=-40.0)
           for i in range(12) for j in range(3)]
    rb = DR.k4(bad, from_day=d0)
    assert rb["ok"] is False and "МЕРТВА" in rb["say"], rb["say"]


def test_k4_without_top_days_rule():
    """Третья граница заявки: без трёх лучших дней сумма обязана
    остаться положительной — иначе ожидание живёт в эпизоде."""
    d0 = DR.forward_day()
    rows = []
    for i in range(12):
        # Обычный день чуть в плюсе, четыре дня чуть в минусе, три дня —
        # весь доход. Медиана дня положительна и укус мал: правило пула
        # такую книгу пропускает, и режет её только третья граница.
        bp = 2000.0 if i < 3 else (0.5 if i < 8 else -1.0)
        for j in range(3):
            rows.append(_row((d0 + i) * DR.MS_D + j, bp=bp))
    r = DR.k4(rows, from_day=d0)
    assert r["without_top"] is not None
    assert r["ok"] is False and "лучших дней" in (r["why"] or ""), r


def test_without_top_days_and_halves():
    """Колонки концентрации — числами."""
    daily = {1: 10.0, 2: 100.0, 3: 1.0, 4: -5.0, 5: 50.0}
    eq(DR.without_top_days(daily, 3), -4.0, what="без трёх лучших")
    eq(DR.without_top_days(daily, 0), 156.0, what="без нуля лучших")
    assert DR.TOP_DAYS == 3
    rows = [_row(T0, bp=10.0, sym="AAA"),
            _row(T0 + 40 * DR.MS_D, bp=30.0, sym="BBB")]
    h1, h2 = DR.halves(rows)
    eq(h1, 1.0, what="первая половина окна, доллары")
    eq(h2, 3.0, what="вторая половина окна, доллары")


def test_form_uses_project_bite():
    """Форма считается мерой проекта, а не своей копией укуса."""
    import stability as SB
    rows = [_row((1000 + i) * DR.MS_D, bp=(100.0 if i % 3 else -50.0))
            for i in range(12)]
    f = DR.form(rows)
    assert f["st"] == SB.stats(DR.daily_usd(rows)), \
        "форма разошлась с мерой проекта"
    assert f["st"]["bite"] is not None and f["days"] == 12


def test_daily_skips_uncovered():
    """Непокрытое событие не есть убыточный день: сделки не было вовсе."""
    rows = [_row(T0, bp=10.0),
            _row(T0 + 1, cover=False, used=False, why="нет снимка входа")]
    d = DR.daily_usd(rows)
    assert len(d) == 1 and abs(sum(d.values()) - 1.0) < 1e-9, d


# --- порядок убийц -----------------------------------------------------

def test_verdict_order_and_unmeasured():
    """Порядок обязателен; «не измерено» — отдельный исход.

    Убийца, которого нечем посчитать, не есть пройденный убийца: иначе
    механика объявлялась бы живой по календарю, которого ещё нет.
    """
    res = {"K0": {"ok": True, "say": "a"}, "K1": {"ok": False, "say": "b"},
           "K2": {"ok": False, "say": "c"}, "K3": {"ok": True, "say": "d"},
           "K4": {"ok": None, "say": "e"}}
    v = DR.verdict(res)
    assert v["alive"] is False and v["at"] == "K1", v
    res["K1"]["ok"] = True
    res["K2"]["ok"] = True
    v2 = DR.verdict(res)
    assert v2["alive"] is None and v2["at"] == "K4", v2
    assert "не измерен" in v2["say"], v2["say"]
    res["K4"]["ok"] = True
    v3 = DR.verdict(res)
    assert v3["alive"] is True and v3["at"] is None, v3


def test_measure_event_end_to_end_numbers():
    """Сделка целиком — числами, на записи с известным ходом.

    Цена падает ровно на 100 б.п. от входа к выходу; шорт обязан взять
    100 б.п. минус спред минус круг.
    """
    step, lo = 2000, T0 - 60 * MS
    ts = [lo + i * step for i in range(int((60 + 1900) * MS / step) + 1)]
    # До расчёта цена стоит, после — ровно −100 б.п. за тридцать минут.
    mids = [100.0 if t <= T0 else
            100.0 * (1 - 0.01 * min((t - T0) / (DR.EXIT_S * MS), 1.0))
            for t in ts]
    sn = [snap(t, m, spread_bp=2.0) for t, m in zip(ts, mids)]
    row = DR.measure_event(sn, T0, -1, prints=[(T0 + 1, -1, 100.0, 10.0)])
    assert row["cover"] and row["used"], row["why"]
    gross = (row["mid_in"] - row["mid_out"]) / row["mid_in"] * 1e4
    assert 95 < gross < 101, gross
    # Плоская модель: спред 2 б.п. (вход по биду, выход по аску) и круг.
    eq(row["flat_bp"], gross - 2.0 - DR.FLAT_COST_BP, tol=0.6,
       what="взятие нетто")
    assert row["walk_bp"] < row["flat_bp"] + DR.SLIP_BP * 2, \
        "проход по лесенке обязан быть не лучше плоской модели без слипа"
    # Спред печатается отдельно, хотя он уже внутри взятия: без него
    # разница «по серединам» и «по лучшим ценам» выглядит необъяснимой.
    eq(row["spread_in_bp"], 2.0, tol=0.01, what="спред на входе")
    eq(row["mid_bp"] - row["flat_bp"], 2.0, tol=0.02,
       what="взятие по серединам минус взятие по лучшим ценам = спред")
    eq(DR.usd_of(row), row["flat_bp"] / 1e4 * 1000.0, what="деньги билета")
    eq(row["flow_usd"], 1000.0, what="лента за минуту")
    eq(row["depth_bp25"], 3602.0, what="глубина бидов на входе")


def test_first_after_measures_the_hole_not_the_count():
    """«Событие непокрыто» обязано быть ВЕЛИЧИНОЙ, а не счётом.

    Верхней границы у этой меры нет намеренно: она диагностирует
    сборщик, а не выбирает цену. Без неё K0 говорит «запись плоха» и не
    говорит НАСКОЛЬКО — а лечить придётся именно величину.
    """
    ts = [T0 - 5000, T0 + 40 * MS, T0 + 42 * MS]
    eq(DR.first_after_s(ts, T0), 40.0, what="дыра в сорок секунд")
    eq(DR.first_after_s([T0 + 3000], T0), 3.0, what="снимок ровно в окне")
    assert DR.first_after_s([T0 - 1], T0) is None, "после точки пусто"
    # Дыра длиннее сплошного окна диагностики — ПРОЧЕРК: дальше идёт уже
    # снимок выхода, и назвать его задержкой значило бы выдумать полчаса.
    assert DR.DIAG_CAP_S == 180, DR.DIAG_CAP_S
    assert DR.first_after_s([T0 + DR.EXIT_S * MS], T0) is None, \
        "снимок выхода выдал себя за задержку сборщика"
    eq(DR.first_after_s([T0 + 179 * MS], T0), 179.0, what="у потолка")
    # Событие непокрыто, а величина дыры измерена и лежит в строке.
    sn = ([snap(T0 - 5000, 100.0)]
          + [snap(T0 + 40 * MS + i * 2000, 100.0) for i in range(1000)])
    row = DR.measure_event(sn, T0, -1)
    assert row["in_record"] is True and row["cover"] is False
    eq(row["first_after_s"], 40.0, what="задержка первого снимка")
    r = DR.k0([row])
    assert r["lag"] and r["lag"]["med"] == 40.0, r
    assert "с задержкой 40.0 с" in r["say"], r["say"]
    assert r["entry"] == 0 and r["in_record"] == 1, r


def test_k0_judges_the_entry_snapshot_it_was_declared_on():
    """K0 судит ВХОД, а не сделку: это две разные беды.

    Объявлено: «доля событий, у которых в записи есть снимок входа не
    позже T+10 с». Дыра на ВЫХОДЕ покрытие входа не портит, и подменить
    одно другим значило бы судить сборщик за другую величину.
    """
    sn = ([snap(T0 + 4 * MS, 100.0)]
          + [snap(T0 + 5 * MS + i * 2000, 100.0) for i in range(100)])
    row = DR.measure_event(sn, T0, -1)          # выхода в записи нет
    assert row["entry_ok"] is True and row["cover"] is False, row
    assert "снимка выхода" in (row["why"] or ""), row["why"]
    r = DR.k0([row])
    eq(r["share"], 1.0, what="вход покрыт, хотя сделки не вышло")
    assert r["entry"] == 1 and r["cover"] == 0, r
    assert r["ok"] is True, r["say"]


def test_profile_to_next_is_a_dash_without_next():
    """Профиль до следующего начисления: доли пути, а не «через 4 часа».

    Шаг начисления у площадки бывает 1, 2, 4 и 8 ч; фиксированные часы
    для часового имени означали бы четыре пропущенных расчёта. Нет
    следующего начисления в ряду — прочерк, а не ноль.
    """
    step, lo = 4000, T0 - 60 * MS
    n = int((60 + 4 * 3600) * MS / step) + 1
    ts = [lo + i * step for i in range(n)]
    mids = [100.0 * (1 - 0.02 * max(0.0, (t - T0)) / (4 * DR.MS_H))
            for t in ts]
    sn = [snap(t, m) for t, m in zip(ts, mids)]
    p = DR.profile_to_next(sn, T0, T0 + 4 * DR.MS_H)
    assert set(p) == set(DR.NEXT_FRACTIONS), p
    eq(p[1.0], -200.0, tol=1.0, what="весь путь до следующего расчёта")
    eq(p[0.5], -100.0, tol=1.0, what="половина пути")
    assert DR.profile_to_next(sn, T0, None) is None, "нет расчёта — прочерк"
    assert DR.profile_to_next(sn, T0, T0) is None


def test_lag_stats_measure_the_collector():
    """Дыра записи у границы часа считается по покрытым событиям."""
    rows = [dict(_row(T0 + i), entry_lag_s=float(i), exit_lag_s=0.5)
            for i in range(1, 21)]
    rows.append(_row(T0 + 99, cover=False, used=False, why="нет снимка"))
    st = DR.lag_stats(rows)
    assert st["entry_lag_s"]["n"] == 20, st
    eq(st["entry_lag_s"]["med"], 10.5, what="медиана задержки входа")
    eq(st["entry_lag_s"]["max"], 20.0, what="худшая задержка")
    assert DR.lag_stats([])["entry_lag_s"] is None, "пусто — прочерк"


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
            # контролей фабрики: она узнаёт ИМЕННУЮ проверку по нему, а
            # контроль, роняющий что-то постороннее, ничего не
            # доказывает о своём правиле.
            print(f"  ПРОВАЛ {fn.__name__} — {e}")
        except Exception as e:                              # noqa: BLE001
            bad += 1
            print(f"  ПРОВАЛ {fn.__name__} — {type(e).__name__}: {e}")
    print(f"\nпроверок {len(ALL)}, провалов {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
