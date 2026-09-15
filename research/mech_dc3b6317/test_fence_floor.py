#!/usr/bin/env python3
"""Проверки механики dc3b6317 — пол забора из размаха суток.

Что здесь обязано кусаться (и кусается — каждая проверка названа):

* **единицы**: размах приходит в б.п., забор считает долей цены, и
  перевод закреплён литералом (1000 б.п. = 0.10 цены). Ошибка единиц
  ловилась в проекте пять раз;
* **тождество с ядром**: пол, выставленный ровно в `param · d_max`,
  обязан дать линейке `depth` ТО ЖЕ плечо бит в бит — это пришивает и
  глубину лестницы, и перевод единиц, и то, что плечо выводит одна
  `ladder.max_leverage`, а не вторая копия;
* **калибровочная пара**: замороженный ряд (σ близка к нулю, размах
  велик) обязан быть НАЙДЕН — пол связывает плечо; случайное блуждание
  с известной σ обязано пройти МОЛЧА — отношение размах/σ около 1.6 и
  пол не связывает под 6σ. Без пары сломанное чтение баров выглядит как
  «σ честна»;
* **заглядывание в будущее**: переписанное будущее не двигает ни σ, ни
  размах, ни долю замороженных минут, ни плечо под полом — и двигает
  потолок с идеальным знанием, потому что он в будущее смотрит
  намеренно;
* **возврат подмен**: перехват ядра снимается в любом исходе, иначе
  соседний прогон молча станет другим замером;
* **отказ вместо пустоты**: ноль позиций при непустом листе — отказ
  словами, а не отчёт с прочерками;
* **вердикт из числа**: фраза шага выводится из величины, а не стоит
  рядом с ней литералом.
"""
import copy
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import fence_floor as F                                       # noqa: E402
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import run_d5 as D5                                           # noqa: E402
import run_d10 as D10                                         # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import wave as WV                                             # noqa: E402

H = 3600.0
T0 = 1_786_320_000.0
FLAT_MMR = 0.005
# Уровни ВЫШЕ входа: у шорта лестница идёт вверх. Шаг 1.6 % — чуть
# больше `MIN_ADD_GAP`, чтобы рунги приняло ядро, и лестница вышла
# УЗКОЙ (d_max ≈ 5 %) — ровно такая, какой забор выдаёт потолок плеча.
LEVELS = [101.6, 103.3, 105.0]
RULE, PARAM = D10.RULERS["safe_s"]


def _look(notl):
    return L.mmr_for_notional([], notl, flat=FLAT_MMR)


def _with_levels(fn, levels=None):
    orig = D2.build_levels
    D2.build_levels = lambda w, i, _lv=(levels or LEVELS): list(_lv)
    try:
        return fn()
    finally:
        D2.build_levels = orig


def _leg(at, sym="SSSUSDT", fwd=60.0, rr=2.0, fav=-500.0):
    return {"sym": sym, "at": float(at), "side": "short", "fwd": fwd,
            "rr": rr, "beta": 0.8, "fav": fav, "adv_q": 5000.0}


def _bars_from(prices, t0=T0 - 1440 * 60, spread=0.0, vol=1000.0):
    """Минутные бары из ряда цен: верх и низ на `spread` вокруг цены."""
    out = []
    for i, px in enumerate(prices):
        out.append((t0 + i * 60.0, px, px + spread, px - spread, px, vol))
    return out


def _frozen(n_pre=1440, n_post=1440, px=100.0, step_bp=1.0, spike=0.15):
    """ЗАМОРОЖЕННЫЙ ряд: котировка стоит, один тик и один всплеск верхом.

    σ близка к нулю (два ненулевых приращения на сутки), а размах велик —
    ровно тот случай, ради которого заявка: обратная волатильность без
    пола есть замороженный ряд в новом костюме (урок S1).
    """
    pre = [px] * n_pre
    pre[700:] = [px * (1 + step_bp / 1e4)] * (n_pre - 700)
    bars = _bars_from(pre)
    hi = list(bars[300])
    hi[2] = px * (1 + spike)             # всплеск ВЕРХОМ: размах есть
    bars[300] = tuple(hi)
    at = bars[0][0] + n_pre * 60.0       # момент решения — по СЕТКЕ времени
    post = [bars[-1][4]] * n_post
    bars += _bars_from(post, t0=bars[-1][0] + 60.0)
    return bars, at


def _walk(seed=1, n_pre=1440, n_post=1440, px=100.0, sigma_day=0.03):
    """Случайное блуждание с ИЗВЕСТНОЙ σ: у него размах ≈ 1.6 σ_сут."""
    s = sigma_day / math.sqrt(D5.MIN_PER_DAY)
    rnd = random.Random(seed)
    v, out = px, []
    for _ in range(n_pre + n_post):
        v *= math.exp(rnd.gauss(0.0, s))
        out.append(v)
    bars = _bars_from(out)
    return bars, bars[0][0] + n_pre * 60.0


# --- единицы, тождество с ядром, само правило -------------------------

def test_units_of_the_range_floor():
    """Размах в б.п. → доля цены. Литералом, а не «как-нибудь»."""
    assert F.range_frac(1000.0) == 0.10, F.range_frac(1000.0)
    assert F.range_frac(1972.0) == 0.1972, F.range_frac(1972.0)
    assert abs(F.range_frac(1000.0, 0.5) - 0.05) < 1e-15
    assert abs(F.range_frac(1000.0, 2.0) - 0.20) < 1e-15
    # «не измерено» ≠ ноль: у размаха, которого нет, пола не бывает
    for bad in (None, float("nan"), 0.0, -3.0):
        assert F.range_frac(bad) is None, bad
    print("ok  единицы: 1000 б.п. = 0.10 цены; размаха нет — прочерк, "
          "а не ноль")


def test_floor_equals_the_depth_ruler():
    """Пол в `param · d_max` обязан дать линейке `depth` ТО ЖЕ плечо.

    Кусается за всё сразу: за глубину лестницы, за перевод единиц и за
    то, что плечо выводит одна `ladder.max_leverage`.
    """
    entry, rungs = 100.0, [100.0, 103.0, 106.0, 110.0]
    d = F.depth_frac(entry, rungs)
    assert abs(d - 0.10) < 1e-12, d
    for p in (1.0, 2.0, 3.0, 6.0):
        want, _r, _b = D5.fence_leverage("depth", p, entry, rungs, _look,
                                         50.0, side="short")
        got, why = F.floor_leverage(entry, rungs, _look, p * d * 1e4,
                                    mult=1.0, side="short")
        assert got is not None and got == want, (p, got, want, why)
    print("ok  пол в «param · d_max» равен линейке depth бит в бит на "
          "четырёх параметрах — второй копии вывода плеча нет")


def test_floor_binds_only_below_the_ruler():
    """`min` двух плеч и есть «запас = max(запас линейки, размах)»."""
    assert F.under_floor(25.0, 7.0) == (7.0, "пол")
    assert F.under_floor(3.0, 7.0) == (3.0, "линейка")
    assert F.under_floor(3.0, None) == (3.0, "линейка")
    entry, rungs = 100.0, [100.0, 101.6, 103.3, 105.0]
    # запас забора и запас пола — одна величина, и большая из них
    # обязана дать то же плечо, что минимум из двух
    for rng_bp in (200.0, 500.0, 1500.0, 4000.0):
        lev_f, _w = F.floor_leverage(entry, rungs, _look, rng_bp,
                                     side="short")
        lev_r, _r, _b = D5.fence_leverage("sigma", 6.0, entry, rungs, _look,
                                          12.0, side="short")
        lev, who = F.under_floor(lev_r, lev_f)
        both = max(F.range_frac(rng_bp), 6.0 * D5.sigma_day(12.0))
        want = L.max_leverage(rungs, D2.WEIGHTS[:len(rungs)], 1.0, entry,
                              F.depth_frac(entry, rungs), _look,
                              max(both, F.depth_frac(entry, rungs))
                              / F.depth_frac(entry, rungs), side="short")
        assert abs(lev - want) < 1e-9, (rng_bp, lev, want, who)
        # тождество самой заявки: запас до ликвидации не меньше размаха
        gap = F.liq_gap(entry, rungs, lev, _look, "short")
        assert gap >= F.range_frac(rng_bp) - 1e-9 or lev <= 1.0 + 1e-9, \
            (rng_bp, gap, F.range_frac(rng_bp), lev)
    print("ok  плечо под полом равно плечу по БОЛЬШЕМУ из двух запасов, "
          "и расстояние до ликвидации после него не меньше размаха")


def test_two_readings_of_the_claim_are_both_counted():
    """Пол на лестнице забора и пол на позиции, которой книга торгует.

    Кусается за существо находки: у НЕПОЛНОЙ лестницы (рунгов меньше
    четырёх) сумма весов меньше единицы, забор считает среднюю цену
    набранной лестницы во столько же раз выше входа — и запас, который
    он себе выводит, в разы больше того, что у позиции есть без
    доливов. Трактовка меняет вывод, поэтому выбирать её молча нельзя.
    """
    entry = 100.0
    thin = [100.0, 102.19]                     # два рунга: Σ весов 0.5
    full = [100.0, 102.0, 104.0, 106.0]        # четыре: Σ весов 1.0
    gap_thin = F.liq_gap(entry, thin, 25.0, _look, "short",
                         weights=D2.WEIGHTS[:2])
    gap_full = F.liq_gap(entry, full, 25.0, _look, "short")
    gap_flat = F.liq_gap(entry, [entry], 25.0, _look, "short",
                         weights=[1.0])
    # у позиции без доливов на 25× запас около 1/плеча, у неполной
    # лестницы забор насчитывает себе больше цены целиком
    assert gap_thin > 1.0 and gap_full < 0.10 and gap_flat < 1.5 / 25.0, \
        (gap_thin, gap_full, gap_flat)
    rng_bp = 1500.0                            # размах суток 15 %
    lev_fence, _w = F.floor_leverage(entry, thin, _look, rng_bp,
                                     side="short")
    lev_flat, _w2 = F.flat_floor_leverage(entry, _look, rng_bp,
                                          side="short")
    assert lev_fence == F.LEV_CAP, ("на неполной лестнице пол забора не "
                                    "связывает вовсе", lev_fence)
    assert 1.0 < lev_flat < 8.0, lev_flat
    # тождество второй трактовки: запас позиции БЕЗ доливов не меньше размаха
    assert F.liq_gap(entry, [entry], lev_flat, _look, "short",
                     weights=[1.0]) >= F.range_frac(rng_bp) - 1e-9
    assert F.flat_floor_leverage(entry, _look, float("nan")) == \
        (None, "размах не измерен")
    assert F.flat_floor_leverage(entry, _look, 1_000_000.0,
                                 side="short")[1] == "пол недостижим"
    print(f"ok  две трактовки считаются обе: на неполной лестнице забор "
          f"видит запас {100 * gap_thin:.0f} % и пола не замечает "
          f"({lev_fence:.0f}×), а у позиции без доливов запас "
          f"{100 * gap_flat:.1f} % и пол даёт {lev_flat:.2f}×")


def test_partial_note_is_derived_from_the_numbers():
    rows = [dict(r, band="25x", lev=25.0, n_rungs=2, w_sum=0.5,
                 avg_ratio=2.02, gap=1.06, gap_flat=0.0196, rng=0.23)
            for r in _rows(n=6)]
    part, why = F.partial_note(rows)
    assert part is True and "НЕПОЛНАЯ" in why and "2.02" in why, why
    assert "106.0 %" in why and "2.0 %" in why and "23.0 %" in why, why
    full = [dict(r, band="25x", n_rungs=4, w_sum=1.0, avg_ratio=1.03,
                 gap=0.05, gap_flat=0.0196, rng=0.23) for r in _rows(n=6)]
    part, why = F.partial_note(full)
    assert part is False and "полная" in why, why
    part, why = F.partial_note([], band="25x")
    assert part is None and "нет" in why, why
    print("ok  третье объяснение полосы 25× выводится из чисел: рунгов, "
          "суммы весов, средней цены лестницы и двух запасов")


def test_declared_reading_decides_what_is_judged():
    rows = [dict(r, lev=25.0, lev_after=25.0, moved=False,
                 lev_after_flat=3.0, moved_flat=True, band="25x")
            for r in _rows(n=20)]
    assert F.after_of(rows[0], "fence") == 25.0
    assert F.after_of(rows[0], "flat") == 3.0
    dead_a, why_a, _n = F.inert_verdict(rows, F.bands_table(rows, "fence"),
                                        "fence")
    dead_b, why_b, _n = F.inert_verdict(rows, F.bands_table(rows, "flat"),
                                        "flat")
    assert dead_a is True and "0.0 %" in why_a, why_a
    assert dead_b is False, why_b
    picks_a, st_a = F.seed_picks(rows, n_seeds=3, variant="fence")
    picks_b, st_b = F.seed_picks(rows, n_seeds=3, variant="flat")
    assert st_a["touched"] == 0 and not picks_a
    assert st_b["touched"] == len(rows) and len(picks_b) == 3
    print("ok  что судится — решает ОБЪЯВЛЕННАЯ трактовка: на одних и тех "
          "же позициях вердикт инертности у них разный, и контроль зёрен "
          "строится под ту, которую объявили")


def test_floor_refuses_instead_of_guessing():
    """Нечем считать — причина словами, а не молчаливое плечо."""
    assert F.floor_leverage(100.0, [100.0], _look, 500.0) == \
        (None, "нет лестницы")
    assert F.floor_leverage(100.0, [100.0, 105.0], _look, float("nan")) == \
        (None, "размах не измерен")
    # размах, которого не переживает даже 1×, — не «плечо поменьше», а
    # названная причина: такой позиции не существует
    lev, why = F.floor_leverage(100.0, [100.0, 105.0], _look, 100000.0,
                                side="short")
    assert lev is None and why == "пол недостижим", (lev, why)
    print("ok  пол отказывает с причиной: нет лестницы / размах не "
          "измерен / пол недостижим")


# --- калибровочная пара ------------------------------------------------

def _window(bars, at):
    ts = [b[0] for b in bars]
    return D2.split_window(bars, ts, at, D2.BACK_H, D2.HOLD_H)


def test_calibration_pair_finds_the_frozen_row_and_stays_silent_on_noise():
    """Подсаженное — найти, на шуме — молчать. Обе половины с литералами."""
    bars, at = _frozen()
    win, now_i = _window(bars, at)
    sigma_bp, rng_bp, _t = D3.window_stats(win, now_i)
    sd = D5.sigma_day(sigma_bp)
    ratio = F.range_frac(rng_bp) / sd
    flat = F.flat_share(win, now_i)
    assert ratio >= F.DEFECT_RATIO, ("замороженный ряд не найден", ratio)
    assert flat is not None and flat > 0.99, flat
    entry = float(win[now_i][1])
    rungs = L.structural_rungs(entry, LEVELS, D2.MIN_ADD_GAP, D2.N_RUNGS,
                               side="short")
    lev_ice, _r, _b = D5.fence_leverage("sigma", 6.0, entry, rungs, _look,
                                        sigma_bp, side="short")
    lev_icef, _w = F.floor_leverage(entry, rungs, _look, rng_bp, side="short")
    lev_frozen, who = F.under_floor(lev_ice, lev_icef)
    assert lev_ice >= 20.0, ("забор обязан выдать замороженному ряду "
                             "потолок", lev_ice)
    assert who == "пол" and lev_frozen < lev_ice / 2.0, (lev_frozen, lev_ice)
    # само тождество заявки на подсаженном случае: после пола расстояние
    # «вход → ликвидация» не меньше размаха, который имя УЖЕ прошло
    gap = F.liq_gap(entry, rungs, lev_frozen, _look, "short")
    assert gap >= F.range_frac(rng_bp) - 1e-9, (gap, F.range_frac(rng_bp))

    ratios, bound = [], []
    for seed in range(5):
        bars, at = _walk(seed=seed)
        win, now_i = _window(bars, at)
        sigma_bp, rng_bp, _t = D3.window_stats(win, now_i)
        sd = D5.sigma_day(sigma_bp)
        ratios.append(F.range_frac(rng_bp) / sd)
        entry = float(win[now_i][1])
        rg = L.structural_rungs(entry, [entry * 1.016, entry * 1.033,
                                        entry * 1.05], D2.MIN_ADD_GAP,
                                D2.N_RUNGS, side="short")
        lev_w, _r, _b = D5.fence_leverage("sigma", 6.0, entry, rg, _look,
                                          sigma_bp, side="short")
        lev_wf, _w = F.floor_leverage(entry, rg, _look, rng_bp, side="short")
        bound.append(F.under_floor(lev_w, lev_wf)[1])
    med = sorted(ratios)[len(ratios) // 2]
    assert med <= F.HONEST_RATIO, ("на шуме пол обязан молчать", ratios)
    assert bound.count("пол") == 0, (bound, ratios)
    print(f"ok  калибровка: замороженный ряд найден (размах/σ = "
          f"{ratio:.0f}, минут без движения {100 * flat:.0f} %, плечо "
          f"{lev_ice:.1f}× → {lev_frozen:.1f}×); на случайном блуждании "
          f"отношение {med:.2f} при {F.BROWN_RATIO:g} у теории и пол НЕ "
          "связывает")


def test_segment_is_the_same_one_window_stats_uses():
    """Доля минут без движения считается на ТОМ ЖЕ отрезке, что σ."""
    for make in (_frozen, _walk):
        bars, at = make()
        win, now_i = _window(bars, at)
        cl = F.seg_closes(win, now_i)
        assert cl is not None and len(cl) >= 10
        import numpy as np
        mine = float(np.std(np.diff(np.log(cl)))) * 1e4
        theirs = D3.window_stats(win, now_i)[0]
        assert abs(mine - theirs) < 1e-9, (mine, theirs)
    print("ok  отрезок окна тот же, что у window_stats: σ по нему равна "
          "её σ — доля замороженных минут описывает то же окно")


# --- заглядывание в будущее -------------------------------------------

def _one(bench, g, bars, cells=None, rich=True):
    ts = [b[0] for b in bars]
    with F.bound(bench):
        return _with_levels(lambda: D10.one_position(
            g, bars, ts, _look, RULE, PARAM, cells=cells, rich=rich))


def test_future_does_not_touch_the_floor_but_does_touch_the_ceiling():
    """Переписать будущее — прошлое не шелохнётся; потолок обязан дрогнуть.

    Прошлое у обеих дорог одно: случайное блуждание. Будущее разное:
    у одной оно стоит на месте, у другой уходит ПРОТИВ шорта. Всё, что
    известно в момент решения (σ, размах, доля замороженных минут, плечо
    линейки и плечо под полом), обязано совпасть бит в бит; потолок с
    идеальным знанием — измениться, он в будущее смотрит намеренно.
    """
    bars, at = _walk(seed=7, n_post=0)
    px = bars[-1][4]
    quiet = _bars_from([px] * 1440, t0=bars[-1][0] + 60.0)
    rise = _bars_from([px * (1 + 0.20 * i / 1440.0) for i in range(1440)],
                      t0=bars[-1][0] + 60.0)
    g = _leg(at)
    rows = []
    for post in (quiet, rise):
        b = F.Bench(oracle=True, mults=(F.RANGE_MULT,))
        _one(b, g, bars + post, cells=[F.CELL])
        rows.append(list(b.rows.values())[0])
    a, z = rows
    for k in ("sigma_bp", "sigma_day", "rng", "ratio", "n_bars", "flat",
              "lev", "lev_after", "bound", "binder"):
        assert a[k] == z[k], (k, a[k], z[k])
    assert a["adv"] != z["adv"], (a["adv"], z["adv"])
    assert z["adv"] > a["adv"], (a["adv"], z["adv"])
    print(f"ok  будущее прошлого не двигает: σ, размах, плечо и пол "
          f"совпадают бит в бит; потолок видит ход против позиции "
          f"{100 * a['adv']:.1f} % против {100 * z['adv']:.1f} %")


def test_the_ceiling_reaches_neither_the_floor_nor_liquidation():
    """Запас потолка выводится из реализованного хода и пола капитуляции."""
    assert F.oracle_frac(0.10, 0.0) == 0.10 + F.ORACLE_EPS_BP / 1e4
    assert abs(F.oracle_frac(0.09, 0.50) - 2 * (0.09 + 1e-4)) < 1e-12
    bars, at = _walk(seed=3, n_post=0)
    px = bars[-1][4]
    g = _leg(at)
    key = ("safe_s", g["sym"], round(at, 3))
    got = {}
    for name, rise in (("тихое", 0.08), ("буйное", 0.60)):
        post = _bars_from([px * (1 + rise * i / 1440.0)
                           for i in range(1440)], t0=bars[-1][0] + 60.0)
        plan = {key: [("base", {"kind": "base"}),
                      ("oracle", {"kind": "oracle"})]}
        b = F.Bench(plan=plan, oracle=True)
        assert _one(b, g, bars + post, cells=[F.CELL])
        got[name] = (b.recs["oracle"]["safe_s"][key],
                     b.recs["base"]["safe_s"][key])
    for name, (rec, base) in got.items():
        assert rec["exit"] not in F.TAIL_EXITS, (name, rec["exit"])
        assert 1.0 <= rec["lev"] <= F.LEV_CAP + 1e-9, (name, rec["lev"])
    # знание будущего работает В ОБЕ СТОРОНЫ: где ход против позиции был
    # велик, потолок даёт меньше плеча, чем там, где его не было
    assert got["буйное"][0]["lev"] < got["тихое"][0]["lev"], got
    assert got["буйное"][0]["lev"] < got["буйное"][1]["lev"], got["буйное"]
    print(f"ok  потолок не доходит ни до пола, ни до ликвидации и следует "
          f"будущему: {got['тихое'][0]['lev']:.2f}× на тихом ходе против "
          f"{got['буйное'][0]['lev']:.2f}× на буйном (у базы "
          f"{got['буйное'][1]['lev']:.2f}×)")


# --- перехват: возврат, отказ, счёт вариантов -------------------------

def test_patch_is_put_back_in_any_outcome():
    ws, fl, op = D3.window_stats, D5.fence_leverage, D10.one_position
    with F.bound(F.Bench()):
        assert D3.window_stats is not ws
        assert D5.fence_leverage is not fl
        assert D10.one_position is not op
    assert (D3.window_stats, D5.fence_leverage, D10.one_position) == \
        (ws, fl, op)
    try:
        with F.bound(F.Bench()):
            raise ValueError("нарочно")
    except ValueError:
        pass
    assert (D3.window_stats, D5.fence_leverage, D10.one_position) == \
        (ws, fl, op), "подмена осталась после исключения"
    print("ok  перехват ядра снимается и после исключения — соседний "
          "прогон другим замером не станет")


def test_foreign_window_is_a_refusal_not_a_stale_floor():
    """Забор о ЧУЖОМ окне — отказ вслух, а не пол от прошлой позиции."""
    b = F.Bench()
    fell = None
    with F.bound(b):
        b.cur = {"calls": 0, "spec": {"kind": "floor", "mult": 1.0},
                 "entry": 100.0, "sigma_bp": 50.0, "rng_bp": 900.0}
        try:
            D5.fence_leverage("sigma", 6.0, 777.0, [777.0, 800.0], _look,
                              50.0, side="short")
        except F.Stale as e:
            fell = str(e)
        finally:
            b.cur = None
    assert fell and "чужом окне" in fell, fell
    print("ok  чужое окно — отказ словами: " + fell[:60] + "…")


def test_plan_gives_each_variant_its_own_leverage():
    bars, at = _walk(seed=11)
    g = _leg(at)
    key = ("safe_s", g["sym"], round(at, 3))
    plan = {key: [("base", {"kind": "base"}),
                  ("floor", {"kind": "floor", "mult": F.RANGE_MULT}),
                  ("scale", {"kind": "scale", "v": 0.5}),
                  ("cap", {"kind": "cap", "v": 2.0}),
                  ("seed", {"kind": "scale", "v": 0.25})]}
    b = F.Bench(plan=plan, oracle=False)
    _one(b, g, bars, cells=[F.CELL])
    base = b.recs["base"]["safe_s"][key]["lev"]
    assert abs(b.recs["scale"]["safe_s"][key]["lev"]
               - max(1.0, base * 0.5)) < 1e-9
    assert abs(b.recs["cap"]["safe_s"][key]["lev"]
               - max(1.0, min(base, 2.0))) < 1e-9
    assert abs(b.seeds[key][0.25]["lev"] - max(1.0, base * 0.25)) < 1e-9
    assert b.no_plan == 0
    print(f"ok  каждый вариант получил своё плечо: база {base:.2f}×, "
          f"равномерный {b.recs['scale']['safe_s'][key]['lev']:.2f}×, "
          f"потолок {b.recs['cap']['safe_s'][key]['lev']:.2f}×")


def test_uniform_control_may_only_reduce_leverage():
    b = F.Bench()
    fell = None
    try:
        b._resolve({"kind": "scale", "v": 1.5},
                   {"lev_base": 4.0}, 100.0, [100.0, 105.0], _look,
                   "short", None)
    except ValueError as e:
        fell = str(e)
    assert fell and "больше единицы" in fell, fell
    print("ok  равномерный контроль УМЕНЬШАЕТ плечо: множитель больше "
          "единицы — отказ, а не тихое усиление книги")


# --- контроли: размер, множители, пороги ------------------------------

def _rows(n=40, seed=5):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        lev = 1.0 if i % 4 == 0 else rnd.choice([2.0, 8.0, 18.0, 25.0])
        aft = lev if i % 3 else max(1.0, lev * rnd.uniform(0.1, 0.8))
        out.append({"ruler": "safe_s", "sym": f"S{i}USDT", "at": T0 + i * H,
                    "lev": lev, "lev_after": aft, "moved": aft < lev - 1e-9,
                    "lev_after_flat": aft, "moved_flat": aft < lev - 1e-9,
                    "band": F.band_of(lev), "ratio": 2.0 + i,
                    "sigma_day": 0.01, "rng": 0.02, "n_bars": 1440,
                    "flat": 0.0, "binder": "σ", "n_rungs": 4, "w_sum": 1.0,
                    "avg_ratio": 1.03, "gap": 0.05, "gap_flat": 0.04})
    return out


def test_seed_control_keeps_the_size_and_the_multiset():
    rows = _rows()
    picks, st = F.seed_picks(rows, n_seeds=F.SEEDS)
    touched = [r for r in rows if r["moved"]]
    assert st["seeds"] == F.SEEDS == 200, st
    assert st["touched"] == len(touched) and st["mults"] == len(touched)
    want = sorted(round(r["lev_after"] / r["lev"], 9) for r in touched)
    for s in (0, 7, 199):
        got = sorted(round(m, 9) for m in picks[s].values())
        assert len(picks[s]) == len(touched), (s, len(picks[s]))
        assert got == want, (s, got[:3], want[:3])
        for key in picks[s]:
            r = next(x for x in rows if (x["ruler"], x["sym"], x["at"]) == key)
            assert r["lev"] > 1.0 + 1e-9, ("в жеребьёвку попала позиция на "
                                           "1×, где уменьшать нечего", key)
    assert picks[0] != picks[1], "зёрна дают одну и ту же выборку"
    print(f"ok  зёрна: {st['seeds']} штук, выборка того же размера "
          f"({st['touched']}) с тем же мультимножеством, и только из "
          f"{st['pool']} позиций с плечом больше 1×")


def test_uniform_controls_hit_the_target_mean_leverage():
    rows = _rows()
    want = F.mean_lev(rows, "lev_after")
    k = F.solve_scale(rows, want)
    c = F.solve_cap(rows, want)
    got_k = sum(max(1.0, r["lev"] * k) for r in rows) / len(rows)
    got_c = sum(max(1.0, min(r["lev"], c)) for r in rows) / len(rows)
    assert abs(got_k - want) < 1e-6, (got_k, want)
    assert abs(got_c - want) < 1e-6, (got_c, want)
    assert 0.0 < k <= 1.0 and 1.0 <= c <= 25.0, (k, c)
    print(f"ok  равномерные контроли выведены на то же среднее плечо "
          f"{want:.3f}×: множитель {k:.4f}, плоский потолок {c:.2f}×")


def test_better_needs_both_numbers_and_both_directions():
    good = {"bite": 2.0, "ratio": 3.0}
    assert F.better({"bite": 1.0, "ratio": 4.0}, good) is True
    assert F.better({"bite": 3.0, "ratio": 4.0}, good) is False
    assert F.better({"bite": 1.0, "ratio": 2.0}, good) is False
    assert F.better({"bite": None, "ratio": 4.0}, good) is None
    print("ok  «лучше» требует ОБЕ величины и ОБА направления; "
          "не измерено — прочерк, а не победа")


# --- вердикты выводятся из чисел --------------------------------------

def _table(ratio, flat=0.9, n=100, lev_after=3.0):
    return {"25x": {"n": n,
                    "ratio": {"n": n, "med": ratio, "mean": ratio},
                    "flat": {"n": n, "med": flat, "mean": flat},
                    "lev_after": {"n": n, "med": lev_after,
                                  "mean": lev_after},
                    "sigma_day": {"n": n, "med": 0.006, "mean": 0.006},
                    "rng": {"n": n, "med": 0.15, "mean": 0.15},
                    "n_bars": {"n": n, "med": 1440, "mean": 1440},
                    "binders": {"σ": n}, "moved": n, "moved_share": 1.0,
                    "lev": {"n": n, "med": 25.0, "mean": 25.0},
                    "no_measure": 0}}


def test_sigma_verdict_is_derived_from_the_number():
    kind, why = F.sigma_verdict(_table(24.0))
    assert kind == "дефект" and "24.0" in why and "дефект меры" in why, why
    kind, why = F.sigma_verdict(_table(1.7))
    assert kind == "честна" and "1.7" in why and "σ честна" in why, why
    kind, why = F.sigma_verdict(_table(5.0))
    assert kind == "между" and "5.0" in why, why
    kind, why = F.sigma_verdict(_table(None))
    assert kind is None and "не измерено" in why, why
    print("ok  вердикт шага 0 выводится из отношения: 24 → дефект, "
          "1.7 → σ честна, 5 → между порогами, прочерк → «не измерено»")


def test_inertness_verdict_is_derived_from_the_numbers():
    rows = [dict(r, moved=False) for r in _rows()]
    dead, why, num = F.inert_verdict(rows, _table(20.0))
    assert dead and "0.0 %" in why, why
    rows = [dict(r, moved=True) for r in _rows()]
    dead, why, _n = F.inert_verdict(rows, _table(20.0, lev_after=18.0))
    assert dead and "18.0×" in why, why
    dead, why, _n = F.inert_verdict(rows, _table(20.0, lev_after=3.0))
    assert not dead and "судить есть что" in why, why
    print("ok  вердикт инертности выводится из доли тронутых и плеча "
          "полосы 25× после пола")


def test_shape_verdict_is_derived_from_the_numbers():
    dead, why = F.shape_verdict({"usd_wo_top3d": -12.0, "wo3d_share": -0.1,
                                 "med": 5.0, "usd": 120.0})
    assert dead and "-12.00" in why, why
    dead, why = F.shape_verdict({"usd_wo_top3d": 100.0, "wo3d_share": 0.30,
                                 "med": 5.0, "usd": 330.0})
    assert dead and "30 %" in why, why
    dead, why = F.shape_verdict({"usd_wo_top3d": 100.0, "wo3d_share": 0.60,
                                 "med": 5.0, "usd": 166.0})
    assert not dead and "форма держится" in why, why
    dead, why = F.shape_verdict({"usd_wo_top3d": None, "med": None})
    assert dead is None and "не измерена" in why, why
    print("ok  вердикт формы выводится из «без 3 лучших дней», доли "
          "итога и медианы дня")


def test_seed_verdict_counts_the_share_of_seeds():
    floor = {"bite": 2.0, "ratio": 3.0}
    seeds = [{"bite": 1.0, "ratio": 4.0}] * 30 + \
            [{"bite": 3.0, "ratio": 2.0}] * 70
    dead, st, why = F.seed_verdict(floor, seeds)
    assert dead and st["wins"] == 30 and "30.0 %" in why, (st, why)
    dead, st, why = F.seed_verdict(floor, [{"bite": 3.0, "ratio": 2.0}] * 100)
    assert not dead and st["wins"] == 0, st
    dead, st, why = F.seed_verdict(floor, [])
    assert dead is None and "не проведён" in why, why
    # «не измерено» ≠ «случайная не выиграла»: доля считается от
    # ИЗМЕРЕННЫХ зёрен, а нечего мерить — контроль не проведён
    dead, st, why = F.seed_verdict(floor, [{"bite": None, "ratio": None}] * 7)
    assert dead is None and st["share"] is None and "не проведён" in why, st
    dead, st, why = F.seed_verdict(
        floor, [{"bite": 1.0, "ratio": 4.0}] * 2
        + [{"bite": None, "ratio": None}] * 98)
    assert dead is True and st["measured"] == 2 and st["share"] == 1.0, st
    # то же требование к равномерному контролю
    dead, _o = F.uniform_verdict({"floor": {"bite": None, "ratio": None},
                                  "scale": {"bite": None, "ratio": None}})
    assert dead is None, dead
    print("ok  контроль зёрен считает ДОЛЮ ИЗМЕРЕННЫХ зёрен; неизмеренное "
          "не выдаётся ни за победу правила, ни за победу случайной")


# --- касса: та же дорога, что у соседних замеров -----------------------

def _fake_market(tmp):
    RP.reset_market()
    RP.market(root=os.path.join(tmp, "нет-сводок"))


def _recs(n=12, seed=2):
    """Записи позиций в форме ядра — достаточные для кассы и формы."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        at = T0 + i * 6 * H
        lev = rnd.choice([1.0, 4.0, 12.0, 25.0])
        pnl = rnd.uniform(-0.6, 0.4)
        out.append({"at": at, "exit_ts": at + 12 * H, "pnl": pnl,
                    "pnl_net": pnl - 0.01, "lev": lev, "lev_fence": lev,
                    "fwd": 60.0, "sym": f"S{i % 5}USDT", "side": "short",
                    "rr": 2.0, "gates": ["any", "rr2"],
                    "exit": ("пол" if pnl < -0.4 else "тейк"),
                    "marks": [(at + k * H, 0.0) for k in range(12)],
                    "end_ts": at + 12 * H, "sched_end": at + 24 * H,
                    "depth": 1, "n_rungs": 1, "avg": 100.0,
                    "entry_px": 100.0, "exit_px": 99.0, "filled": lev,
                    "fav_bp": -500.0, "state": "closed", "fills": None})
    return out


def test_book_stats_walks_the_same_road_as_the_axis_measures():
    """Та же касса и те же правила, что у `short_grid.cell_stats`.

    Отличие одно и объявлено: наружу отдаётся весь `_stats` ради колонок
    концентрации. Разойдись дороги — замер судил бы другую книгу под тем
    же именем, и это молчаливо.
    """
    import tempfile
    tmp = tempfile.mkdtemp(prefix="floor-")
    _fake_market(tmp)
    try:
        recs = _recs()
        launch = {f"S{i}USDT": T0 - 90 * 86400.0 for i in range(5)}
        ctx = {"error": "рядов издержек нет"}
        mine = F.book_stats({"safe_s": copy.deepcopy(recs)}, ctx, launch,
                            now=T0 + 40 * 24 * H, keys=["safe_h"],
                            log=lambda *a: None)
        theirs = G.cell_stats({"safe_h": copy.deepcopy(recs)}, ctx, launch,
                              now=T0 + 40 * 24 * H, keys=["safe_h"],
                              log=lambda *a: None)
        assert set(mine) == set(theirs), (sorted(mine), sorted(theirs))
        checked = 0
        for k in mine:
            a, z = mine[k], theirs[k]
            for f in ("n", "usd", "final", "max_dd", "win", "day_median",
                      "taken", "no_cash"):
                assert a.get(f) == z.get(f), (k, f, a.get(f), z.get(f))
                checked += 1
            assert a.get("days") == z.get("days_rows") or \
                a.get("days_rows") == z.get("days"), k
        assert checked >= 8 * 3, checked
        print(f"ok  касса замера и касса соседних замеров дают одни числа "
              f"({checked} сверок по {len(mine)} клеткам); наружу идёт "
              "весь `_stats` ради колонок концентрации")
    finally:
        RP.reset_market()


def test_tail_share_by_band_counts_the_tail_outcomes():
    rows = [{"lev": 25.0, "exit": "пол", "usd": -50.0},
            {"lev": 25.0, "exit": "тейк", "usd": 10.0},
            {"lev": 25.0, "exit": "ликвидация", "usd": -80.0},
            {"lev": 1.0, "exit": "тейк", "usd": 3.0}]
    by = F._by_band(rows)
    assert by["25x"]["n"] == 3 and by["25x"]["tail"] == 2
    assert by["25x"]["tail_share"] == round(2 / 3, 4), by["25x"]
    assert by["1x"]["tail"] == 0 and by["1x"]["tail_share"] == 0.0
    print("ok  доля хвостовых исходов по полосам считает пол И ликвидацию")


# --- сквозной прогон ---------------------------------------------------

class _Src:
    """Подставной источник баров: тот же контракт, что у `sweep.read_bars`."""

    def __init__(self, by_sym):
        self.by_sym = by_sym

    def bars(self, sym, a, b):
        return [r for r in self.by_sym.get(sym, []) if a <= r[0] <= b]


def _world():
    """Три имени: замороженное (пол связывает), шумное и растущее."""
    frozen, at_f = _frozen()
    walk, at_w = _walk(seed=21)
    bars3, at_r = _walk(seed=22, n_post=0)
    px = bars3[-1][4]
    bars3 = bars3 + _bars_from(
        [px * (1 + 0.12 * i / 1440.0) for i in range(1440)],
        t0=bars3[-1][0] + 60.0)
    at = max(at_f, at_w, at_r)
    # решения кладём в ОДИН момент времени у всех имён: окно у каждого
    # своё, а касса сравнивает книги на одних сутках
    return _Src({"AAAUSDT": frozen, "BBBUSDT": walk, "CCCUSDT": bars3}), \
        (at_f, at_w, at_r)


def test_run_end_to_end_on_synthetic_bars():
    """Сквозь всё: проход A → план → проход B → касса → шаги → отчёт.

    Дороги отчёта и вердиктов `py_compile` не видит, а прошлые прогоны
    падали ровно на последнем шаге после часа счёта.
    """
    import tempfile
    tmp = tempfile.mkdtemp(prefix="floor-e2e-")
    _fake_market(tmp)
    src, ats = _world()
    legs = []
    for sym, at in zip(("AAAUSDT", "BBBUSDT", "CCCUSDT"), ats):
        for i in range(4):
            legs.append(_leg(at + i * H, sym=sym, fwd=60.0 + i))
    launch = {s: T0 - 200 * 86400.0
              for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT")}
    try:
        s = _with_levels(lambda: F.run(
            legs_=legs, src=src, log=lambda *a: None,
            ctx={"error": "рядов издержек нет"}, launch=launch,
            now=max(ats) + 40 * 24 * H, n_seeds=5))
    finally:
        RP.reset_market()
    assert not s.get("error"), s.get("error")
    assert s["positions"] > 0 and s["no_plan"] == 0, s
    assert set(s["cells"]) >= {"base", "floor", "floor_flat", "scale",
                               "cap"}, s["cells"]
    assert s["variant"] == F.VERDICT_VARIANT == "fence", s["variant"]
    assert s["variant_key"] == "floor", s["variant_key"]
    assert [x["n"] for x in s["steps"]] == [0, 1, 2, 3, 4, 5, 6]
    base, floor = s["cells"]["base"], s["cells"]["floor"]
    assert base["lev_mean"] is not None and floor["lev_mean"] is not None
    assert floor["lev_mean"] <= base["lev_mean"] + 1e-9, (base, floor)
    txt = F.report(s)
    assert "Шаг 0" in txt and "размах/σ" in txt, txt[:400]
    assert "Механика закрыта на шаге" in txt or "Ни один убийца" in txt
    for band in ("ровно 1×", "ровно 25×"):
        assert band in txt, band
    # обе трактовки в отчёте, и ровно одна помечена вердиктом
    assert txt.count("— ВЕРДИКТ") == 1, txt.count("— ВЕРДИКТ")
    assert "на лестнице забора — ВЕРДИКТ" in txt
    assert "на позиции без доливов (диагностика)" in txt
    # объявленная трактовка меняет то, ЧТО судится
    _fake_market(tmp)
    try:
        s2 = _with_levels(lambda: F.run(
            legs_=legs, src=src, log=lambda *a: None,
            ctx={"error": "рядов издержек нет"}, launch=launch,
            now=max(ats) + 40 * 24 * H, n_seeds=5, variant="flat"))
    finally:
        RP.reset_market()
    assert s2["variant_key"] == "floor_flat", s2["variant_key"]
    assert "на позиции без доливов — ВЕРДИКТ" in F.report(s2)
    bad = F.run(legs_=legs, src=src, log=lambda *a: None, variant="нетакая")
    assert "не объявлена" in (bad.get("error") or ""), bad
    print(f"ok  сквозной прогон: позиций {s['positions']}, среднее плечо "
          f"{base['lev_mean']:.2f}× → {floor['lev_mean']:.2f}×, шагов "
          f"{len(s['steps'])}, отчёт {len(txt)} символов; вторая трактовка "
          "судится только по объявлению")


def test_empty_result_is_a_refusal_not_a_report_with_dashes():
    """Ноль позиций при непустом листе — отказ словами."""
    src = _Src({})
    legs = [_leg(T0 + i * H, sym="ZZZUSDT") for i in range(3)]
    s = F.run(legs_=legs, src=src, log=lambda *a: None,
              ctx={"error": "нет"}, launch={}, n_seeds=2)
    assert s.get("error") and "мерить нечем" in s["error"], s
    txt = F.report(s)
    assert "Не посчитано" in txt, txt[:300]
    s2 = F.run(legs_=[], src=src, log=lambda *a: None, ctx={"error": "нет"},
               launch={}, n_seeds=2)
    assert s2.get("error") and "считать нечего" in s2["error"], s2
    print("ok  пустота не выдаёт себя за результат: и пустой лист, и лист "
          "без единой посчитанной позиции — отказ с причиной")


def test_report_prints_dashes_for_what_is_not_measured():
    s = {"verdict_cell": "safe_h:10000", "legs": 10, "positions": 0,
         "hold_h": 24, "rules": R.RULES, "secs": 1.0,
         "computed_at": "2026-09-15 10:00",
         "table": {k: {"n": 0} for k, _t in F.BANDS},
         "steps": [{"n": 0, "name": "шаг", "dead": None, "why": "нечего"}],
         "claims": {}, "cells": {}, "picks": {}, "seeds": {},
         "forward": {"days": 0, "verdict": "нечем"}, "stopped_at": None}
    txt = F.report(s)
    assert "| ровно 25× | 0 | — | — |" in txt, \
        [ln for ln in txt.splitlines() if "ровно 25×" in ln]
    assert " 0.00 " not in txt.split("## Шаг 0")[1].split("##")[0], \
        "непосчитанная величина напечатана нулём"
    print("ok  величина, которой нет, печатается прочерком, а не нулём")


TESTS = (test_units_of_the_range_floor,
         test_floor_equals_the_depth_ruler,
         test_floor_binds_only_below_the_ruler,
         test_two_readings_of_the_claim_are_both_counted,
         test_partial_note_is_derived_from_the_numbers,
         test_declared_reading_decides_what_is_judged,
         test_floor_refuses_instead_of_guessing,
         test_calibration_pair_finds_the_frozen_row_and_stays_silent_on_noise,
         test_segment_is_the_same_one_window_stats_uses,
         test_future_does_not_touch_the_floor_but_does_touch_the_ceiling,
         test_the_ceiling_reaches_neither_the_floor_nor_liquidation,
         test_patch_is_put_back_in_any_outcome,
         test_foreign_window_is_a_refusal_not_a_stale_floor,
         test_plan_gives_each_variant_its_own_leverage,
         test_uniform_control_may_only_reduce_leverage,
         test_seed_control_keeps_the_size_and_the_multiset,
         test_uniform_controls_hit_the_target_mean_leverage,
         test_better_needs_both_numbers_and_both_directions,
         test_sigma_verdict_is_derived_from_the_number,
         test_inertness_verdict_is_derived_from_the_numbers,
         test_shape_verdict_is_derived_from_the_numbers,
         test_seed_verdict_counts_the_share_of_seeds,
         test_book_stats_walks_the_same_road_as_the_axis_measures,
         test_tail_share_by_band_counts_the_tail_outcomes,
         test_run_end_to_end_on_synthetic_bars,
         test_empty_result_is_a_refusal_not_a_report_with_dashes,
         test_report_prints_dashes_for_what_is_not_measured)


if __name__ == "__main__":
    for t in TESTS:
        t()
    print(f"\nвсе {len(TESTS)} проверок прошли")
