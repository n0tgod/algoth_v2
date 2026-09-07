#!/usr/bin/env python3
"""
Проверки механики 49b535f8 — «где усреднять».

Проверяется то, где ошибка была бы НЕВИДИМОЙ в отчёте: прогон не падает,
таблица выглядит исправной, а число описывает другую книгу.

* **розыгрыш нуля обязан быть той же глубины и той же формы** — уплыви
  глубина, и мы сравнивали бы «глубже/мельче», а не «где»; исчезни
  зазор — розыгрыш ставил бы два долива на одном уровне, чего правило
  §R1 не разрешает ни одной руке;
* **при двух рунгах розыгрыш ТОЖДЕСТВЕН структурной лестнице** — и это
  обязано быть посчитано числом, а не разбавлять нуль нулями: такие
  пары тянут любую разность к нулю, то есть дарят ожидаемый вердикт;
* **заглядывания в будущее нет** — переписанное будущее не двигает ни
  уровней, ни рунгов, ни σ; узкое окно σ обязано совпасть с широким
  БИТ В БИТ, иначе пол сечения посчитан не той мерой, что сетка;
* **«не измерено» доезжает прочерком, а не нулём** — нет σ, сетка
  глубже 100 % цены: обе причины называются, и ни одна не ноль;
* **калибровочная пара** — подсаженное место долива обязано находиться,
  а на обмениваемых данных машинерия обязана молчать; без второй
  половины сломанное чтение уровней неотличимо от «уровни не важны»;
* **пустота не выдаёт себя за результат** — ноль позиций при непустом
  входе есть отказ с причиной;
* **вердикт выводится ИЗ чисел** — фраза, стоящая рядом с числом
  литералом, однажды противоречит своему же числу.

Запуск: `.venv/bin/python research/mech_49b535f8/test_place.py`.
"""

import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import place as P                                            # noqa: E402
import run_place as RP                                       # noqa: E402
import ladder as L                                           # noqa: E402
import run_d2 as D2                                          # noqa: E402
import run_d3 as D3                                          # noqa: E402

MIN = 60
HOUR = 3600
T0 = 1_786_000_000 // HOUR * HOUR          # ровный час


def look(notl):
    return 0.005


# ------------------------------------------------------------ сырьё

def bars_from(prices, t0=T0, vol=1000.0, wick=0.0008):
    out = []
    for i, p in enumerate(prices):
        p = float(p)
        out.append((t0 + i * MIN, p, p * (1 + wick), p * (1 - wick), p, vol))
    return out


def saw(n, base=100.0, amp=0.004, period=20, phase=0):
    """Пила: даёт структуре, из чего строить уровни.

    `phase` двигает фазу так, чтобы вход попадал куда надо: уровни
    строятся ниже входа только у входа НЕ на дне пилы, а на дне
    структурная лестница вырождается в один рунг — и проверка, ради
    которой ряд сделан, молча проверяла бы пустоту.
    """
    return [base * (1.0 + amp * (((i + phase) % period) - period / 2.0)
                    / (period / 2.0)) for i in range(n)]


def leg(at, sym="AAA", i=0, fav=300.0, adv=-400.0):
    return {"at": float(at), "sym": sym, "side": "long", "fwd": 40.0,
            "rr": 2.5, "beta": 0.5, "fav": fav, "adv_q": adv,
            "adv_m": adv, "arm": "gbm", "id": i, "hour": "h",
            "px": 100.0, "fz": 1.0}


class Src:
    """Подставной источник баров: ряд на символ, нарезается как живой.

    Подделка обязана выглядеть как живое: объём положителен (лимитка
    исполняется чужим принтом), фитили есть, минуты идут подряд, метки
    времени живые. Ряд, повторяющий себя числом в числе, прячет ошибки
    заполнения рунга.
    """

    def __init__(self, series):
        self.series = series
        self.calls = []

    def bars(self, sym, t0, t1):
        self.calls.append((sym, t0, t1))
        b = self.series.get(sym) or []
        return [x for x in b if t0 <= x[0] <= t1]


def make_series(sym_n=3, hours=200, seed=7):
    """Ряды нескольких имён: пила в прошлом, блуждание дальше."""
    rng = np.random.default_rng(seed)
    out = {}
    for j in range(sym_n):
        n = hours * 60
        px = list(np.asarray(saw(n // 2, base=100.0 + j))
                  * (1.0 + rng.normal(0, 0.0005, n // 2)))
        walk = px[-1] * np.exp(np.cumsum(rng.normal(0, 0.0009, n - len(px))))
        out[f"S{j}"] = bars_from(px + list(walk), t0=T0 - 24 * HOUR)
    return out


# ------------------------------------------------- геометрия розыгрыша

def test_draw_keeps_depth_and_form():
    rng = np.random.default_rng(3)
    for k in (2, 3, 4):
        for d in (0.05, 0.12, 0.31):
            for _ in range(50):
                r = P.draw_rungs(100.0, k, d, rng)
                assert r is not None, (k, d)
                assert len(r) == k, (k, len(r))
                assert abs(r[0] - 100.0) < 1e-12
                # глубина обязана СОВПАДАТЬ, а не «примерно»
                assert abs(P.depth_of(100.0, r) - d) < 1e-12, (k, d, r)
                assert all(a > b for a, b in zip(r, r[1:])), r


def test_draw_respects_min_gap():
    """Зазор §R1 у розыгрыша тот же, что у ядра, и предикат один."""
    # сперва калибруем сам предикат: выход ядра обязан его проходить
    lv = [99.0, 97.0, 96.9, 94.0, 93.9, 88.0]
    core = L.structural_rungs(100.0, lv, P.MIN_GAP, 4)
    assert len(core) >= 3, core
    assert P.gap_ok(core), core
    # и он обязан ЛОВИТЬ нарушение, иначе проверка ниже бессмысленна
    assert not P.gap_ok([100.0, 99.9, 90.0])
    rng = np.random.default_rng(11)
    for _ in range(300):
        d = float(rng.uniform(0.05, 0.4))
        r = P.draw_rungs(100.0, 4, d, rng)
        if r is None:
            continue
        assert P.gap_ok(r), (d, r)


def test_draw_impossible_form_is_none():
    """Лестницы такой формы не существует — None, а не короче и не тише."""
    rng = np.random.default_rng(5)
    # четыре рунга требуют трёх зазоров по 1.5 %: на 2 % их не разместить
    assert P.draw_rungs(100.0, 4, 0.02, rng) is None
    assert P.draw_rungs(100.0, 2, 0.0, rng) is None
    assert P.draw_rungs(0.0, 3, 0.1, rng) is None


def test_draws_assigned_by_seed_not_by_order():
    a = P.draws_for(100.0, 4, 0.2, 12, leg_id=7)
    b = P.draws_for(100.0, 4, 0.2, 12, leg_id=7)
    c = P.draws_for(100.0, 4, 0.2, 12, leg_id=8)
    assert a == b, "розыгрыш не воспроизводится тем же зерном"
    assert a != c, "разные ноги получили один розыгрыш"
    short = P.draws_for(100.0, 4, 0.2, 5, leg_id=7)
    assert short == a[:5], "прогон на пяти розыгрышах не префикс прогона на 12"


def test_two_rung_draw_is_identical_to_structure():
    """При двух рунгах розыгрыш совпадает с S — и это НЕ прячется."""
    rng = np.random.default_rng(2)
    r = P.draw_rungs(100.0, 2, 0.07, rng)
    assert r == [100.0, 93.0] or abs(r[1] - 93.0) < 1e-9, r
    hold = bars_from([100.0 * (1 - 0.0002 * i) for i in range(400)])
    arms = P.position_arms(hold, 100.0, [100.0, 93.0], 106.0, look, None,
                           n_draws=4, leg_id=1)
    assert arms["degenerate"] is True
    assert arms["r_identical"] is True
    # короткая дорога обязана давать ТЕ ЖЕ числа, что полный реплей
    full = P.sim(hold, [100.0, 93.0], arms["lev_s"], look, 106.0)
    for x in arms["R"]:
        assert x["pnl_frac"] == full["pnl_frac"], (x["pnl_frac"],
                                                   full["pnl_frac"])


def test_even_rungs_same_depth_and_count():
    r = P.even_rungs(100.0, 4, 0.12)
    assert len(r) == 4 and abs(P.depth_of(100.0, r) - 0.12) < 1e-12
    assert abs(r[1] - 96.0) < 1e-9 and abs(r[2] - 92.0) < 1e-9


# ------------------------------------------------------------ σ и пол

def test_sigma_floor_comes_from_section():
    sec = [0.02 + 0.001 * i for i in range(40)]        # 0.020 … 0.059
    f = P.sigma_floor(sec)
    want = float(np.quantile(np.asarray(sec), P.SIG_FLOOR_Q))
    assert abs(f - want) < 1e-12, (f, want)
    # сечение выше — пол выше: он ИЗ сечения, а не назначен
    f2 = P.sigma_floor([x * 3 for x in sec])
    assert f2 > f * 2.5, (f, f2)
    # тонкое сечение — абсолютный пол, и это не «пола нет»
    assert P.sigma_floor([0.9, 0.8]) == P.ABS_SIG_FLOOR
    # и пол не бывает ниже абсолютного
    assert P.sigma_floor([1e-6] * 40) == P.ABS_SIG_FLOOR


def test_no_sigma_is_dash_not_zero():
    assert P.sigma_grid(100.0, None) == (None, None)
    assert P.sigma_grid(100.0, 0.0) == (None, None)
    # сетка глубже 100 % цены — тоже прочерк, и причина НАЗЫВАЕТСЯ
    assert P.sigma_grid(100.0, 0.30) == (None, None)
    hold = bars_from(saw(400))
    a = P.position_arms(hold, 100.0, [100.0, 96.0, 92.0], 103.0, look, None,
                        n_draws=3, leg_id=1)
    assert a["G"] is None, "рука без σ обязана быть прочерком"
    assert a["g_why"] == "нет σ", a.get("g_why")
    b = P.position_arms(hold, 100.0, [100.0, 96.0, 92.0], 103.0, look, 0.30,
                        n_draws=3, leg_id=1)
    assert b["G"] is None, "глубокая сетка обязана быть прочерком"
    assert b["g_why"] == "сетка глубже 100 %", b.get("g_why")
    # и ноль в сводку не попадает: n руки G меньше, чем у S
    st = P.cell_stats([a["S"]["pnl_frac"], float("nan")])
    assert st["n"] == 1


def test_sigma_day_uses_d5_ruler():
    assert P.sigma_day_of(None) is None
    assert P.sigma_day_of(float("nan")) is None
    assert P.sigma_day_of(50.0) == D3.__dict__.get("_x", P.D5.sigma_day(50.0))


# --------------------------------------------------- заглядывание вперёд

def _leg_and_bars(fut_mult=1.0):
    """Нога и её бары; `fut_mult` переписывает БУДУЩЕЕ после решения.

    Переписывается всё СТРОГО ПОЗЖЕ бара решения: сам этот бар и есть
    вход (открытие первого бара после решения — `next_open`), и его
    подмена меняла бы вход законно, то есть проверка ловила бы
    собственную постановку, а не заглядывание.
    """
    at = T0 + 30 * HOUR
    # Размах пилы взят таким, чтобы структурная лестница СЛОЖИЛАСЬ:
    # зазор §R1 — 1.5 %, и на пиле в 0.4 % ни один уровень не проходит,
    # рунги вырождаются в один вход, а тогда сдвиг окна двигать нечего и
    # проверка на заглядывание молча проверяет пустоту.
    px = saw(48 * 60, base=100.0, amp=0.06, period=240, phase=239)
    b = bars_from(px, t0=at - 24 * HOUR)
    out = []
    for x in b:
        if x[0] > at and fut_mult != 1.0:
            out.append((x[0], x[1] * fut_mult, x[2] * fut_mult,
                        x[3] * fut_mult, x[4] * fut_mult, x[5]))
        else:
            out.append(x)
    return leg(at), out


def test_no_lookahead_in_setup():
    """Переписать будущее — прошлое не шелохнётся."""
    g, b1 = _leg_and_bars(1.0)
    _g, b2 = _leg_and_bars(3.7)                 # будущее втрое дороже
    s1 = RP.setup(g, b1, [x[0] for x in b1])
    s2 = RP.setup(g, b2, [x[0] for x in b2])
    assert s1 is not None and s2 is not None
    assert len(s1["rungs"]) >= 3, "лестница выродилась — двигать нечего"
    assert s1["entry"] == s2["entry"], "вход поехал за будущим"
    assert s1["take_px"] == s2["take_px"]
    assert s1["rungs"] == s2["rungs"], "рунги посчитаны по будущему"
    assert s1["n_levels"] == s2["n_levels"], "уровни увидели будущее"
    assert s1["sigma_bp"] == s2["sigma_bp"], "σ посчитана по будущему"


def test_sigma_narrow_window_equals_wide():
    """Узкое окно σ-прохода — ПРЕФИКС широкого, бит в бит.

    Иначе пол сечения посчитан не той мерой, которой считается сама
    сетка, и обе таблицы выглядят исправными.
    """
    g, b = _leg_and_bars(1.0)
    ts = [x[0] for x in b]
    wide = RP.setup(g, b, ts)["sigma_bp"]
    narrow_bars = [x for x in b if x[0] <= g["at"] + HOUR]
    rs = D2.split_window(narrow_bars, [x[0] for x in narrow_bars],
                         g["at"], D2.BACK_H, 1)
    assert rs is not None
    win, now_i = rs
    narrow = D3.window_stats(win, now_i)[0]
    assert narrow == wide, (narrow, wide)


# ------------------------------------------------------------ руки

def test_arms_hold_leverage_where_they_must():
    """R и G′ идут с плечом S, у G плечо своё: иначе место мешается
    с рычагом."""
    hold = bars_from(saw(600))
    rungs = [100.0, 96.0, 92.0, 88.0]           # глубина 12 %
    # σ подобрана так, чтобы сетка стояла НЕ на той же глубине:
    # 3 шага по 2 σ = 9 % против 12 % у структуры.
    a = P.position_arms(hold, 100.0, list(rungs), 103.0, look, 0.015,
                        n_draws=3, leg_id=4)
    assert a["lev_s"] > 0
    assert a["lev_g"] is not None and a["lev_g"] != a["lev_s"], \
        "у σ-сетки другая глубина, значит и плечо обязано быть другим"
    # плечо S проверяется прямым счётом ядром
    want = L.max_leverage(rungs, P.WEIGHTS, 1.0, 100.0, 0.12, look,
                          P.SURVIVE_MULT)
    assert abs(a["lev_s"] - want) < 1e-9, (a["lev_s"], want)
    assert a["lev_s"] > 1.0, "плечо забора выродилось — проверять нечего"
    # G′ и R обязаны идти С ПЛЕЧОМ S, иначе «где» смешано с «рычагом»
    gp = P.sim(hold, P.even_rungs(100.0, 4, 0.12), a["lev_s"], look, 103.0)
    assert a["GP"]["pnl_frac"] == gp["pnl_frac"], "у G′ чужое плечо"
    drawn = P.draws_for(100.0, 4, 0.12, 3, leg_id=4, seed=P.SEED)
    r0 = P.sim(hold, drawn[0], a["lev_s"], look, 103.0)
    assert a["R"][0]["pnl_frac"] == r0["pnl_frac"], "у розыгрыша чужое плечо"


def test_arm_S_is_core_replay():
    """Рука S — ровно `ladder.simulate_dca`, второй копии реплея нет."""
    hold = bars_from(saw(600))
    rungs = [100.0, 96.0, 92.0, 88.0]
    a = P.position_arms(hold, 100.0, list(rungs), 103.0, look, None,
                        n_draws=2, leg_id=9)
    want = L.simulate_dca(hold, rungs, P.WEIGHTS, 1.0, a["lev_s"],
                          look(a["lev_s"]), take_px=103.0,
                          floor_frac=P.FLOOR_FRAC)
    assert a["S"]["pnl_frac"] == want["pnl_frac"]
    assert a["S"]["exit"] == want["exit"]


def test_place_changes_money_when_it_should():
    """Дорога живая: у лестницы, чьи рунги стоят иначе, и деньги иные.

    Проверка против «все руки считают одно и то же»: там, где путь
    доходит до промежуточных мест, разные рунги обязаны давать разный
    исход, иначе сравнение рук ничего не сравнивает.
    """
    down = [100.0 - 8.0 * i / 300.0 for i in range(300)]
    up = [92.0 + 12.0 * i / 300.0 for i in range(300)]
    hold = bars_from(down + up)
    high = P.sim(hold, [100.0, 99.0, 98.0, 97.0], 3.0, look, 104.0)
    low = P.sim(hold, [100.0, 96.0, 94.0, 92.5], 3.0, look, 104.0)
    assert high["pnl_frac"] != low["pnl_frac"]


# ------------------------------------------------------ сводки и нуль

def test_cell_stats_keeps_median_and_mean_apart():
    v = [0.01] * 19 + [-1.0]          # медиана +, среднее −
    st = P.cell_stats(v)
    assert st["median"] > 0 > st["mean"], st
    assert st["bite"] == 100.0, st
    assert P.cell_stats([])["n"] == 0


def test_draw_pool_is_a_book_per_draw():
    """Розыгрыш — целая книга: сводка считается ВНУТРИ розыгрыша."""
    s = [0.10, 0.20, 0.30]
    r = [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]     # розыгрыш 0 плох, 1 хорош
    pool = P.draw_pool(s, r)
    assert pool["n"] == 3 and pool["draws"] == 2
    nm = pool["nulls"]["median"]
    assert nm["min"] == 0.0 and nm["max"] == 1.0, nm
    assert nm["real"] == 0.20
    # выравнивание проверяется, а не предполагается
    try:
        P.draw_pool(s, [[0.0], [0.0]])
        raise AssertionError("несовпадение длин прошло молча")
    except ValueError:
        pass


def test_null_place_bite_direction():
    """У меры ПЛОХОГО «выше» значит МЕНЬШЕ — и это проверяется знаком."""
    draws = [10.0, 12.0, 14.0, 16.0, 18.0]
    good = P.null_place(5.0, draws, lower_is_better=True)
    bad = P.null_place(30.0, draws, lower_is_better=True)
    assert good["beats"] is True and bad["beats"] is False
    # Между процентилями: укус слабее СРЕДНЕГО розыгрыша — этого мало,
    # правило §9 требует слабее 95 % из них. Сравнение с ВЕРХНИМ
    # процентилем эту разницу проглатывает молча.
    mid = P.null_place(11.0, draws, lower_is_better=True)
    assert mid["beats"] is False, mid
    assert mid["edge"] < 11.0 < P.np.percentile(draws, 95), mid
    up = P.null_place(30.0, draws)               # мера хорошего
    assert up["beats"] is True
    assert P.null_place(None, draws) is None
    assert P.null_place(1.0, []) is None


def test_verdict_null_needs_all_three():
    def nulls(m, mn, b):
        return {"median": P.null_place(m, [0.0, 0.01, 0.02]),
                "mean": P.null_place(mn, [0.0, 0.01, 0.02]),
                "bite": P.null_place(b, [10.0, 12.0, 14.0],
                                     lower_is_better=True)}
    alive = P.verdict_null(nulls(0.5, 0.5, 1.0))
    assert alive["killed"] is False, alive
    assert "выше 95-го процентиля" in alive["why"][0]
    for bad in (nulls(-0.5, 0.5, 1.0), nulls(0.5, -0.5, 1.0),
                nulls(0.5, 0.5, 99.0)):
        v = P.verdict_null(bad)
        assert v["killed"] is True, v
        assert "украшение" in v["why"][0]
    # не посчитано — это НЕ «не бьёт»
    v = P.verdict_null({"median": None, "mean": None, "bite": None})
    assert v["killed"] is None and "не измерено" in v["why"][0]


def test_verdict_null_reads_the_numbers():
    """Фраза выводится ИЗ величин: подвинь число — сменится вердикт."""
    def nulls(m):
        return {"median": P.null_place(m, [0.0, 0.01]),
                "mean": P.null_place(0.5, [0.0, 0.01]),
                "bite": P.null_place(1.0, [10.0, 12.0],
                                     lower_is_better=True)}
    a = P.verdict_null(nulls(0.9))
    b = P.verdict_null(nulls(-0.9))
    assert a["killed"] is False and b["killed"] is True
    assert a["why"][0] != b["why"][0]
    assert "0.9" in " ".join(a["parts"]) or "0.90000" in " ".join(a["parts"])


def test_verdict_grid_band():
    ind = P.verdict_grid(0.0004, 0.50, 100)
    assert ind["killed"] is True and "не различим" in ind["why"][0]
    for alive in (P.verdict_grid(0.02, 0.50, 100),
                  P.verdict_grid(0.0004, 0.80, 100)):
        assert alive["killed"] is False, alive
    assert P.verdict_grid(None, None, 0)["killed"] is None


def test_verdict_form_needs_better_than_both():
    s = {"med": 1.0, "green": 0.6, "bite": 3.0, "dd": -5.0}
    worse = {"med": 0.5, "green": 0.5, "bite": 9.0, "dd": -9.0}
    better = {"med": 2.0, "green": 0.7, "bite": 1.0, "dd": -1.0}
    v = P.verdict_form(s, {"G": worse, "R": worse})
    assert v["killed"] is False and set(v["wins"]) == {"med", "green",
                                                      "bite", "dd"}
    v2 = P.verdict_form(s, {"G": worse, "R": better})
    assert v2["killed"] is True, v2
    assert P.verdict_form(None, {"G": worse})["killed"] is None


def test_paired_day_boot_is_paired():
    a = {i: 1.0 for i in range(30)}
    b = {i: 0.0 for i in range(30)}
    r = P.paired_day_boot(a, b, n_boot=200)
    assert r["median"] == 1.0 and not r["covers_zero"], r
    same = P.paired_day_boot(a, dict(a), n_boot=200)
    assert same["covers_zero"], same
    assert P.paired_day_boot({1: 1.0}, {1: 1.0}) is None


# ------------------------------------------------------------ калибровка

def test_calibration_finds_planted_and_stays_quiet():
    """Пара обязательна: найти подсаженное место и промолчать на шуме."""
    c = P.calibrate(n_draws=40, planted_n=12, noise_n=40, hold_n=400)
    assert c["planted"] is not None and c["noise"] is not None
    assert c["found"] is True, c["planted"]["nulls"]
    assert c["quiet"] is True, c["noise"]["nulls"]
    pl = c["planted"]["nulls"]["median"]
    assert pl["sigmas"] > 2.0, pl
    assert c["geom"] is not None, "диагностика геометрии не посчиталась"


# ------------------------------------------------------------ прогон

def _fake_run(draws=6, hours=200, sym_n=3, per_sym=6, src=None):
    series = make_series(sym_n=sym_n, hours=hours)
    src = src or Src(series)
    legs, i = [], 0
    for j in range(sym_n):
        for q in range(per_sym):
            legs.append(leg(T0 + (30 + q * 5) * HOUR, sym=f"S{j}", i=i))
            i += 1
    return RP.run(draws=draws, src=src, legs=legs, log=lambda m: None,
                  tag="test"), legs


def test_end_to_end_gives_numbers_not_promises():
    s, legs = _fake_run()
    assert not s.get("refused"), s.get("refused")
    assert s["positions"] > 0 and s["positions"] <= len(legs)
    assert s["arms"]["S"]["n"] == s["positions"]
    assert set(s["k_hist"]), "население по числу рунгов не посчитано"
    assert s["null_bite_n"] + s["degenerate_2"] + s["no_ladder"] \
        == s["positions"], (s["null_bite_n"], s["degenerate_2"],
                            s["no_ladder"], s["positions"])
    assert s["sigma_mismatch"] == 0, "σ узкого и широкого окна разошлись"
    assert "verdict_null" in s and "verdict_grid" in s
    rep = RP.report(s)
    assert "Убийца 1" in rep and "Калибровочная пара" in rep


def test_run_refuses_on_empty_input():
    """Ноль позиций при непустом входе — отказ, а не отчёт с прочерками."""
    s, _ = _fake_run(src=Src({}))
    assert s.get("refused"), s
    rep = RP.report(s)
    assert "отказал" in rep.lower() or "отказ" in rep.lower()
    assert "Убийца 1" not in rep, "отказ выдал себя за отчёт"


def test_report_prints_the_numbers_it_judges_by():
    s, _ = _fake_run()
    rep = RP.report(s)
    for part in ((s.get("verdict_null") or {}).get("why") or []):
        assert part in rep, part
    for part in ((s.get("verdict_grid") or {}).get("why") or []):
        assert part in rep, part
    assert str(s["positions"]) in rep
    assert str(s["no_ladder"]) in rep


def test_day_form_uses_exit_day_and_book_ticket():
    d0 = T0 - T0 % 86400
    recs = [{"at": d0 + 3600, "sym": "AAA", "exit_ts": d0 + 2 * 86400 + 60,
             "fwd": 40.0, "pnl": 0.10},
            {"at": d0 + 7200, "sym": "BBB", "exit_ts": d0 + 2 * 86400 + 120,
             "fwd": 40.0, "pnl": -0.20},
            {"at": d0 + 5 * 86400, "sym": "CCC",
             "exit_ts": d0 + 6 * 86400, "fwd": 40.0, "pnl": 0.40}]
    st, daily = RP.day_form(recs)
    assert st["ticket"] == 25.0 and st["capital"] == RP.BOOK_CAP
    # сутки — день ВЫХОДА (деньги стали известны), а не день входа
    assert sorted(daily) == [int((d0 + 2 * 86400) // 86400),
                             int((d0 + 6 * 86400) // 86400)], sorted(daily)
    assert st["days"] == 2, daily
    assert abs(st["tot"] - (0.10 - 0.20 + 0.40) * 25.0) < 1e-9, st
    # медиана И среднее суток рядом: одной из них мало
    assert abs(st["mean_day"] - st["tot"] / st["days"]) < 0.01, st
    # правило одной позиции на имя — чужое и обязано применяться
    dup = recs + [{"at": d0 + 3600 + 60, "sym": "AAA",
                   "exit_ts": d0 + 2 * 86400 + 60, "fwd": 40.0,
                   "pnl": 5.0}]
    st2, _ = RP.day_form(dup)
    assert st2["skipped_same_name"] == 1 and st2["taken"] == 3, st2
    assert RP.day_form([]) == (None, None)


def test_concentration_columns_bite():
    d0 = T0 - T0 % 86400
    recs = ([{"at": d0, "sym": "AAA", "exit_ts": d0 + 86400, "fwd": 1.0,
              "pnl": 1.0}]
            + [{"at": d0, "sym": f"N{i}", "exit_ts": d0 + (5 + i) * 86400,
                "fwd": 1.0, "pnl": 0.01} for i in range(6)])
    c = RP.concentration(recs, 25.0)
    assert c["tot"] > c["no_top3_days"], c
    assert abs(c["no_best_name"] - (c["tot"] - 25.0)) < 1e-9, c
    assert c["best_name"] == "AAA"


def test_clusters_glue_reads():
    ats = [T0, T0 + 3600, T0 + 40 * HOUR, T0 + 41 * HOUR]
    gr = P and RP.clusters(ats)
    assert len(gr) == 2 and len(gr[0]) == 2 and len(gr[1]) == 2, gr
    assert RP.clusters([]) == []


def test_sigma_cache_roundtrip():
    sym = "__TEST__"
    RP.cache_write(sym, {"1": 12.5})
    assert RP.cache_read(sym) == {"1": 12.5}
    # мера сменилась — кэш не годится
    path = RP._cache_path(sym)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    d["back_h"] = -1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f)
    assert RP.cache_read(sym) == {}
    os.remove(path)


TESTS = [
    test_draw_keeps_depth_and_form,
    test_draw_respects_min_gap,
    test_draw_impossible_form_is_none,
    test_draws_assigned_by_seed_not_by_order,
    test_two_rung_draw_is_identical_to_structure,
    test_even_rungs_same_depth_and_count,
    test_sigma_floor_comes_from_section,
    test_no_sigma_is_dash_not_zero,
    test_sigma_day_uses_d5_ruler,
    test_no_lookahead_in_setup,
    test_sigma_narrow_window_equals_wide,
    test_arms_hold_leverage_where_they_must,
    test_arm_S_is_core_replay,
    test_place_changes_money_when_it_should,
    test_cell_stats_keeps_median_and_mean_apart,
    test_draw_pool_is_a_book_per_draw,
    test_null_place_bite_direction,
    test_verdict_null_needs_all_three,
    test_verdict_null_reads_the_numbers,
    test_verdict_grid_band,
    test_verdict_form_needs_better_than_both,
    test_paired_day_boot_is_paired,
    test_calibration_finds_planted_and_stays_quiet,
    test_end_to_end_gives_numbers_not_promises,
    test_run_refuses_on_empty_input,
    test_report_prints_the_numbers_it_judges_by,
    test_day_form_uses_exit_day_and_book_ticket,
    test_concentration_columns_bite,
    test_clusters_glue_reads,
    test_sigma_cache_roundtrip,
]


def main():
    bad = []
    t0 = time.time()
    for t in TESTS:
        try:
            t()
        except Exception as e:                            # noqa: BLE001
            bad.append(t.__name__)
            print(f"ПРОВАЛ {t.__name__}: {type(e).__name__}: {e}",
                  flush=True)
    if bad:
        print(f"провалов {len(bad)} из {len(TESTS)}: {bad}", flush=True)
        return 1
    print(f"все {len(TESTS)} проверки прошли за {time.time() - t0:.1f} с",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
