#!/usr/bin/env python3
"""Проверки механики 9dd65163 — funding внутри пути позиции (шаг 1, потолок).

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть.
Проверка, которая не кусается, не проверяет ничего.

Что проверяется: знак и набор начислений (те же, что у `costs`); строгая
граница часа (начисление на границе принадлежит следующему часу — иначе
это заглядывание в будущее на шаг); сдвиг строго ДО записанного выхода;
пол книги из реестра, а не константой; крышка −100 % маржи у ликвидации;
круг издержек, переживающий поправку; прочерк вместо нуля у непокрытого
ряда; отказ вместо пустоты; калибровочная пара обеими ногами (молчит на
нуле, находит подсаженное); вердикт и его блок по покрытию, выведенные
из чисел; форма книги — чужой мерой, а не своей копией.

Вывод намеренно скуп: приёмка смотрит ПОСЛЕДНИЕ 4000 символов, и строка
«ПРОВАЛ имя», утонувшая в середине, есть контроль, который здесь
пройдёт, а там нет.

    .venv/bin/python research/mech_9dd65163/test_funding_margin.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import funding_margin as FM                                   # noqa: E402
from funding_margin import CO, S, ST, WV                      # noqa: E402

TESTS = []
HOUR = 3600.0
# Начало часа в живом окне журнала коротких книг (08.08–18.09).
T0 = 1786183200.0          # 2026-08-19 06:00 UTC, ровно граница часа
RULERS = {"safe_s": 0.10, "optimal_s": 0.50}


def test(fn):
    TESTS.append(fn)
    return fn


def quiet(*_a):
    pass


# ------------------------------------------------------------ фикстуры

def rec(cum, sym="BLUAIUSDT", at=T0, lev=8.0, exit="срок", entry=0.019603,
        state="closed", ruler="optimal_s", cost_bp=11.0):
    """Запись кэша реплея в ЖИВОЙ форме: те же поля, что пишет `run_d10`.

    `cum` — путь позиции по часам (доли маржи), как его видит
    `wave.path_of`; отметки складываются из приращений, последняя равна
    исходу сделки — иначе фикстура описывала бы позицию, которой ядро не
    считало. Момент выхода лежит ВНУТРИ последнего часа (не на его
    границе), первый рунг — через 18 минут после решения: и то и другое
    так и стоит в живом кэше.
    """
    K = len(cum)
    marks, prev = [], 0.0
    for k, c in enumerate(cum, 1):
        marks.append([at + (k - 1) * HOUR, float(c) - prev])
        prev = float(c)
    filled = 0.25 * lev
    pnl = float(cum[-1])
    return {"at": float(at), "exit_ts": at + (K - 1) * HOUR + 1234.0,
            "pnl": pnl, "pnl_net": pnl - filled * cost_bp / 1e4,
            "lev": float(lev), "lev_fence": float(lev),
            "fwd": 57.35, "sym": sym, "side": "short", "rr": 0.5457,
            "gates": ["any", "lo"], "exit": exit, "marks": marks,
            "ckpt": None, "end_ts": at + K * HOUR,
            "sched_end": at + 24 * HOUR, "depth": 1, "n_rungs": 1,
            "avg": entry, "entry_px": entry,
            "exit_px": entry * (1.0 - pnl / lev), "filled": filled,
            "fills": [[at + 1080.0, entry, 0.25]], "state": state,
            "fav_bp": -120.0, "ruler": ruler}


def series(rate, at=T0, every_h=4, n=12, start_h=-6, jitter=True):
    """Ряд funding площадки: моменты через `every_h` часов, ставка `rate`.

    Ставка дрожит на процент от самой себя: ровная константа в ряду
    площадки не встречается, а подделка, непохожая на жизнь, уже
    пропускала дефекты (восемь холостых проверок из-за фикстур).
    """
    ts = np.array([int((at + (start_h + i * every_h) * HOUR) * 1000)
                   for i in range(n)], dtype=np.int64)
    r = np.full(n, float(rate), dtype=np.float64)
    if jitter:
        r = r * (1.0 + 0.01 * np.sin(np.arange(n, dtype=np.float64)))
    return ts, r


def series_at(times, rate):
    """Ряд с НАЗВАННЫМИ моментами начислений (число событий — свойство имени)."""
    return (np.array([int(t * 1000) for t in times], dtype=np.int64),
            np.full(len(times), float(rate), dtype=np.float64))


def ctx_of(ser, sym="BLUAIUSDT", asset="BLUAI"):
    return {"funding": {asset: ser}, "to_asset": {sym: asset},
            "taker": {sym: 5.5}}


def cache_of(*recs):
    return {(r.get("ruler") or "optimal_s", r["sym"],
             round(float(r["at"]) + i * 1e-3, 3)): r
            for i, r in enumerate(recs)}


# ------------------------------------------------ начисления: знак и набор

@test
def funding_считается_знаком_costs():
    """Знак и набор событий — из `costs.funding_usd`, не из своей копии.

    Шорту положительная ставка — ДОХОД. Своего обхода ряда здесь нет, и
    проверяется это тождеством с самой `costs.funding_usd` на той же
    записи.
    """
    r = rec([0.0, -0.1, -0.2])
    ser = series(+0.001)
    total, ev = FM.accruals(r, ser)
    assert total > 0, f"шорту положительная ставка обязана быть доходом: {total}"
    ref = CO.funding_usd(dict(r, margin=1.0), ser, "short")
    assert abs(total - ref) < 2e-4, (total, ref)
    neg, _ev = FM.accruals(r, series(-0.001))
    assert neg < 0, f"отрицательная ставка шорту — расход: {neg}"


@test
def начисления_не_теряют_точность_на_округлении():
    """Событие округляется до 4 знаков — масштаб маржи обязан это снимать.

    При марже 1 накопленный funding терял бы до 1e-4 доли маржи на
    событие; на медиане в 0.007 % это четверть величины.
    """
    r = rec([0.0, -0.05, -0.1])
    ser = series(3e-6, n=10)
    total, ev = FM.accruals(r, ser)
    want = sum(float(ser[1][i]) * r["filled"] for i in range(len(ser[0]))
               if r["fills"][0][0] * 1000 <= ser[0][i] < r["exit_ts"] * 1000)
    assert abs(total - want) < 1e-9, (total, want)
    assert abs(sum(d for _t, d in ev) - total) < 1e-9, "события ≠ итогу"


@test
def начисление_на_границе_часа_не_в_прошлое():
    """Начисление ровно на границе часа принадлежит СЛЕДУЮЩЕМУ часу.

    Иначе час судится деньгами, которых на нём ещё не было, — заглядывание
    в будущее на один шаг.
    """
    ev = [(T0 + 2 * HOUR, -0.3)]
    assert FM.accrued_to(ev, T0 + 2 * HOUR) == 0.0, "граница строгая"
    assert FM.accrued_to(ev, T0 + 2 * HOUR + 1) == -0.3


@test
def будущее_не_меняет_прошлого():
    """Переписать будущее — прошлое не шелохнётся.

    Начисления ПОСЛЕ найденного часа и путь позиции после него на решение
    этого часа влиять не вправе.
    """
    cum = [0.0, -0.2, -0.45, -0.60, -0.62]
    r = rec(cum)
    ser = series(-0.05, every_h=1, n=30)
    _t, ev = FM.accruals(r, ser)
    sh = FM.shift_of(r, ev, 0.50)
    assert sh is not None, "нечего проверять: сдвига нет"
    k = sh["k"]
    later = [(t, d) for (t, d) in ev if t < T0 + k * HOUR]
    later += [(T0 + (k + 0.5) * HOUR, -9.0), (T0 + (k + 1) * HOUR, -9.0)]
    r2 = rec(cum[:k] + [-0.95] * (len(cum) - k))
    sh2 = FM.shift_of(r2, later, 0.50)
    assert sh2 is not None and sh2["k"] == k, (sh, sh2)
    assert abs(sh2["F"] - sh["F"]) < 1e-12, (sh["F"], sh2["F"])


# --------------------------------------------------- условие пола и знака

@test
def знак_ставки_читается():
    """Расход двигает пол к входу, доход — от входа.

    Одна и та же позиция: при уплаченном funding пол срабатывает раньше
    записанного выхода, при полученном той же величины — нет.
    """
    cum = [0.0, -0.20, -0.36, -0.44, -0.45]
    r = rec(cum)
    _t, pay = FM.accruals(r, series(-0.03, every_h=1, n=30))
    _t, got = FM.accruals(r, series(+0.03, every_h=1, n=30))
    a, b = FM.shift_of(r, pay, 0.50), FM.shift_of(r, got, 0.50)
    assert a is not None, "расход обязан подвинуть пол к входу"
    assert b is None, f"полученный funding не вправе резать позицию: {b}"


@test
def пол_книги_берётся_из_реестра():
    """Пол у книг РАЗНЫЙ, и он читается реестром, а не константой."""
    floors = FM.floor_by_ruler()
    assert floors.get("safe_s") == S.R.floor_frac_of("safe_h", 0.10), floors
    assert floors.get("optimal_s") == S.R.floor_frac_of("optimal_h", 0.10), floors
    assert floors["safe_s"] != floors["optimal_s"], floors
    cum = [0.0, -0.30, -0.55, -0.60]
    r = rec(cum)
    _t, ev = FM.accruals(r, series(-0.02, every_h=1, n=30))
    lo = FM.shift_of(r, ev, floors["optimal_s"])
    hi = FM.shift_of(r, ev, floors["safe_s"])
    assert lo is not None, "пол 0.5 обязан сработать на этом пути"
    assert hi is None or hi["k"] > lo["k"], (lo, hi)


@test
def сдвиг_строго_до_записанного_выхода():
    """Сработавшее на самом часе выхода сдвигом не является."""
    r = rec([0.0, -0.05, -0.95])
    _t, ev = FM.accruals(r, series(0.0))
    assert FM.shift_of(r, ev, 0.50) is None, "последний час — не находка"
    r2 = rec([0.0, -0.95, -0.05, -0.05])
    assert FM.shift_of(r2, ev, 0.50)["k"] == 2


@test
def съеденная_маржа_даёт_ликвидацию_с_крышкой():
    """Начисление, съевшее маржу, ликвидирует позицию независимо от цены.

    Исход такой позиции — вся оставшаяся маржа и не больше: ценовой pnl
    равен −(1 + F), а вместе с начислениями ровно −1.
    """
    r = rec([0.0, 0.05, 0.07, 0.06])
    _t, ev = FM.accruals(r, series(-1.0, every_h=1, n=30))
    sh = FM.shift_of(r, ev, 0.50)
    assert sh is not None and sh["why"] == "ликвидация", sh
    assert abs(sh["pnl"] - (-(1.0 + sh["F"]))) < 1e-12, sh
    assert sh["pnl"] + sh["F"] >= -1.0 - 1e-12, "глубже маржи уйти нельзя"


# ------------------------------------------------------- крышка и издержки

@test
def ликвидация_не_глубже_маржи():
    """Учёт после факта приписывал ликвидации убыток глубже всей маржи."""
    r = rec([0.0, -0.4, -1.0], exit="ликвидация")
    ser = series(-0.01)
    total, _ev = FM.accruals(r, ser)
    assert float(r["pnl"]) + total < -1.0, "фикстура не воспроизводит дефект"
    cap = FM.capped_liq_pnl(r, total)
    assert cap is not None and abs(cap - (-(1.0 + total))) < 1e-12, cap
    assert abs(cap + total - (-1.0)) < 1e-12, "вместе с funding ровно −1"
    assert FM.capped_liq_pnl(rec([0.0, -0.3], exit="пол"), total) is None


@test
def нетто_сохраняет_круг_издержек():
    """Поправка меняет ЦЕНОВОЙ pnl; круг издержек сделки остаётся её."""
    r = rec([0.0, -0.4, -1.0], exit="ликвидация")
    cost = float(r["pnl"]) - float(r["pnl_net"])
    assert cost > 0, "фикстура без круга издержек ничего не проверяет"
    new = FM.repnl(r, -1.08)
    assert abs((new["pnl"] - new["pnl_net"]) - cost) < 1e-12, new
    two = FM.close_at(r, 2, "пол", pnl=-0.42)
    assert abs((two["pnl"] - two["pnl_net"]) - cost) < 1e-12, two


@test
def close_at_тождествен_охране_рынком():
    """Без подмены исхода закрытие на часе — ровно `wave.guard_record`."""
    r = rec([0.0, -0.2, -0.3, -0.4])
    assert FM.close_at(r, 2, "пол") == WV.guard_record(r, 2, why="пол")
    got = FM.close_at(r, 2, "пол", pnl=-0.55)
    assert abs(got["pnl"] - (-0.55)) < 1e-12, got
    assert got["exit_px"] > r["entry_px"], "шорту убыток есть РОСТ цены"


# --------------------------------------------- прочерк, отказ, следствие «б»

@test
def непокрытый_ряд_прочерк_а_не_ноль():
    """Ряд, не покрывающий жизнь позиции, даёт «не измерено», а не нуль."""
    r = rec([0.0, -0.2, -0.3])
    short = series(-0.01, start_h=-6, every_h=1, n=3)      # кончается рано
    assert FM.accruals(r, short) is None, "обрезанный ряд обязан дать None"
    assert FM.accruals(r, None) is None
    cache = cache_of(r)
    out, s = FM.screen(cache, ctx_of(short), floors=RULERS, log=quiet)
    d = s["rulers"]["optimal_s"]
    assert d["uncovered"] == 1 and d["covered"] == 0, d
    assert out[list(cache)[0]] is r, "непокрытую запись поправлять нечем"


@test
def пустой_вход_отказ_а_не_отчёт():
    """Ноль наблюдений при непустом входе — отказ, а не отчёт с прочерками."""
    r = rec([0.0, -0.2])
    for bad, what in ((({}, ctx_of(series(-0.01)))), "пустой кэш"), \
                     ((cache_of(r), {"funding": {}, "to_asset": {}}), "нет рядов"), \
                     ((cache_of(rec([0.0, -0.2], state="open")),
                       ctx_of(series(-0.01))), "нет закрытых"):
        try:
            FM.screen(bad[0], bad[1], floors=RULERS, log=quiet)
        except ValueError:
            continue
        raise AssertionError(f"{what}: пустота выдала себя за результат")


@test
def отодвинутый_пол_только_при_полученном_funding():
    """Следствие «б» считает записи с ПОЛУЧЕННЫМ funding; у полосы свой нуль."""
    r = rec([0.0, -0.3, -0.5], exit="пол")
    up, band, move = FM._postponed(r, +0.02, 0.50)
    assert up and move > 0, (up, move)
    assert FM._postponed(r, -0.02, 0.50)[0] is False, "расход пол не отодвигает"
    assert FM._postponed(r, 0.0, 0.50)[1] is False, "при нуле полоса пуста"
    assert FM._postponed(rec([0.0, -0.3], exit="тейк"), +0.02, 0.5)[0] is False


@test
def остаток_ниже_минус_100_считается_числом():
    """«По построению не остаётся» — утверждение, и оно считается числом.

    Ликвидацию крышка чинит всегда. А позиция, у которой весь funding лёг
    в ПОСЛЕДНИЙ час жизни, потолку не видна: к концу каждого часа до
    выхода начислено ноль, условие не срабатывает, и запись остаётся
    глубже −100 % маржи. Это не дефект счёта, а граница потолка, и она
    печатается числом, а не умалчивается.
    """
    r = rec([0.0, -0.4, -1.0], exit="ликвидация")
    _o, s = FM.screen(cache_of(r), ctx_of(series(-0.01)), floors=RULERS,
                      log=quiet)
    assert s["diag"]["over_after"] == 0, s["diag"]
    assert s["rulers"]["optimal_s"]["over_100"] == 1, s["rulers"]
    assert "over_after" in s["diag"], "величина обязана печататься"
    # Пол 0.10 у безопасной книги режет около −90 % маржи; одно стрессовое
    # начисление (−2.5 % на нотионал 6.25 маржи) добавляет ещё −15.6 п.п.
    late = rec([0.0, -0.3, -0.6, -0.92], exit="пол", lev=25.0,
               ruler="safe_s", sym="COTIUSDT")
    ser = series_at([T0 - 8 * HOUR, T0 + 3 * HOUR + 600.0, T0 + 12 * HOUR],
                    -0.025)
    _o2, s2 = FM.screen(cache_of(late), ctx_of(ser, sym="COTIUSDT",
                                              asset="COTI"),
                        floors=RULERS, log=quiet)
    d = s2["rulers"]["safe_s"]
    assert d["shift"] == 0 and d["covered"] == 1, d
    assert d["over_100"] == 1 and d["over_after"] == 1, d
    assert s2["diag"]["over_after"] == 1, s2["diag"]


# ------------------------------------------------------ калибровочная пара

@test
def калибровочная_пара_кусается():
    """Молчать на нуле и находить подсаженное — обе ноги числами."""
    cache = cache_of(rec([0.0, -0.2, -0.36, -0.40, -0.42]),
                     rec([0.0, 0.05, 0.10, 0.02], exit="тейк"),
                     rec([0.0, -0.4, -1.0], exit="ликвидация"))
    ctx = ctx_of(series(-0.004, every_h=1, n=40))
    c = FM.calibrate(log=quiet, cache=cache, ctx=ctx)
    assert c.get("ok") is True, c
    assert c["zero_shifts"] == 0 and c["zero_cache_same"], c
    assert c["planted_shifts"] == c["planted_must"] > 0, c
    assert c["planted_liq"] == c["planted_shifts"], c


@test
def контроли_смысла_кусаются():
    """Знак наоборот обязан дать ДРУГОЕ число сдвинутых; иначе тревога."""
    cache = cache_of(rec([0.0, -0.20, -0.36, -0.44, -0.45]),
                     rec([0.0, 0.05, 0.10, 0.02], exit="тейк"))
    ctx = ctx_of(series(-0.03, every_h=1, n=40))
    c = FM.sense_controls(cache, ctx, floors=RULERS, seeds=3, log=quiet)
    assert c["real"] > 0 and c["flip"] != c["real"], c
    assert c["sign_read"] is True and "знак читается" in c["why"], c
    flat = FM.sense_controls(cache, ctx_of(series(0.0)), floors=RULERS,
                             seeds=0, log=quiet)
    assert flat["real"] == flat["flip"] == 0, flat
    assert flat["sign_read"] is False, "совпадение обязано быть тревогой"
    assert "НЕ ЧИТАЕТСЯ" in flat["why"], flat["why"]
    assert flat["shuffle_ge_real"] is None, "нуль зёрен — прочерк, не ноль"


@test
def нулевые_ставки_ничего_не_двигают():
    """Нулевой funding — кэш тождествен исходному запись в запись.

    Наше условие строго строже движкового (ставка поддерживающей маржи
    опущена), поэтому при нулевых ставках оно не вправе сработать ни разу.
    """
    cache = cache_of(rec([0.0, -0.2, -0.45, -0.49]),
                     rec([0.0, -0.4, -1.0], exit="ликвидация"),
                     rec([0.0, 0.1, 0.3], exit="тейк"))
    out, s = FM.screen(cache, ctx_of(series(0.0)), floors=RULERS, log=quiet)
    d = s["rulers"]["optimal_s"]
    assert d["shift"] == 0 and d["capped"] == 0, d
    assert all(out[k] == cache[k] for k in cache), "кэш обязан совпасть"


# --------------------------------------------------------- форма и вердикт

def _cell(days, exits=None):
    return {"days": [{"d": f"2026-09-{i + 1:02d}", "usd": float(u)}
                     for i, u in enumerate(days)],
            "exits": exits or {}}


@test
def форма_книги_чужой_мерой():
    """Укус и медиана хорошего дня — `factory/stability`, не своя копия."""
    days = [120.0, -300.0, 40.0, 80.0, -20.0, 200.0]
    f = FM.form_of(_cell(days))
    ref = ST.stats({f"2026-09-{i + 1:02d}": v for i, v in enumerate(days)})
    assert f["bite"] == ref["bite"], (f, ref)
    assert f["worst"] == ref["worst"] and f["med_green"] == ref["med_green"]
    none = FM.form_of(_cell([-10.0, -20.0, -30.0, -40.0]))
    assert none["bite"] is None, "без прибыльных суток укуса не существует"


@test
def без_трёх_лучших_дней_прочерк_на_коротком_ряде():
    """Трёх дней из трёх вычитать нечего — прочерк, а не ноль."""
    assert FM._wo3d(_cell([10.0, 20.0, 30.0])["days"]) is None
    assert FM._wo3d(_cell([10.0, 20.0, 30.0, 5.0])["days"]) == 5.0


def _s_for(shift_share, postponed_share, d_usd, d_bite, cover=1.0):
    n = 1000
    rulers = {}
    for rk in set(S.BOOKS.values()):
        rulers[rk] = {"covered": n, "shift": int(shift_share * n),
                      "shift_share": shift_share,
                      "postponed": int(postponed_share * n),
                      "postponed_band": int(postponed_share * n),
                      "postponed_share": postponed_share}
    books = {bk: {"d_usd": d_usd, "d_bite": d_bite, "med_green": 100.0}
             for bk in S.BOOKS}
    return {"screen": {"rulers": rulers, "diag": {"cover": cover}},
            "books": books}


@test
def вердикт_выводится_из_числа():
    """Фраза собирается из чисел; смена числа обязана менять фразу."""
    dead = FM.verdict(_s_for(0.0, 0.0, 1.0, 0.0))
    alive = FM.verdict(_s_for(0.05, 0.0, 1.0, 0.0))
    assert dead["state"].startswith("мертво"), dead
    assert alive["state"] == "есть что править", alive
    assert alive["n_fail"] == 3 and dead["n_fail"] == 0, (alive, dead)
    big = FM.verdict(_s_for(0.0, 0.0, 500.0, 0.0))
    assert big["state"] == "есть что править", big
    bite = FM.verdict(_s_for(0.0, 0.0, 1.0, 0.9))
    assert bite["state"] == "есть что править", bite


@test
def покрытие_ниже_порога_блокирует():
    """Ряды не покрывают журнал — блок с причиной, а не вердикт по книгам."""
    v = FM.verdict(_s_for(0.0, 0.0, 1.0, 0.0, cover=0.3))
    assert v["state"] == "заблокировано", v
    assert "не покрывают" in v["why"], v
    assert not v["checks"], "по непокрытому журналу книги не судятся"
    ok = FM.verdict(_s_for(0.0, 0.0, 1.0, 0.0, cover=0.95))
    assert ok["state"] != "заблокировано", ok


@test
def обе_трактовки_следствия_б_печатаются():
    """Трактовка не выбирается молча: судит строгая, вторая — рядом."""
    s = _s_for(0.0, 0.0, 1.0, 0.0)
    for rk in s["screen"]["rulers"].values():
        rk["postponed"], rk["postponed_band"] = 100, 0
    v = FM.verdict(s)
    assert v["state"] == "есть что править", v
    assert (v.get("alt") or {}).get("state", "").startswith("мертво"), v.get("alt")


@test
def отчёт_печатает_вердикт_и_покрытие():
    """Отчёт без чисел покрытия и вердикта читать нельзя."""
    s = _s_for(0.0, 0.0, 1.0, 0.0)
    s.update({"dep": 10000, "books_order": FM.BOOK_KEYS, "computed_at": "x",
              "secs": 1.0, "thresholds": {}})
    for rk, d in s["screen"]["rulers"].items():
        d.update({"ruler": rk, "floor": 0.5, "books": FM.books_of(rk), "n": 10,
                  "cover": 1.0, "no_series": 0, "uncovered": 0, "no_marks": 0,
                  "F_median": 0.0, "F_mean": 0.0, "F_min": 0.0, "F_max": 0.0,
                  "over_100": 0, "over_sum": 0.0, "shift_floor": 0,
                  "shift_liq": 0, "shift_pnl": 0.0, "capped": 0,
                  "cap_pnl": 0.0, "exits_floor": 0, "move_median": None,
                  "move_max": None})
    s["screen"]["diag"].update({"closed": 20, "open": 0, "over_after": 0,
                                "event_sum_mismatch": 0,
                                "worst_over_100": None})
    side = {"n": 120, "usd": 900.0, "final": 0.09, "max_dd": -0.03,
            "form": FM.form_of(_cell([10.0, -5.0, 30.0, 12.0]))}
    s["books"] = {bk: {"base": dict(side), "corr": dict(side),
                       "d_usd": 1.0, "d_bite": 0.0, "d_worst": 0.0,
                       "d_liq": 0, "med_green": 100.0}
                  for bk in FM.BOOK_KEYS}
    s["verdict"] = FM.verdict(s)
    txt = FM.report(s)
    assert s["verdict"]["state"] in txt, "вердикта в отчёте нет"
    assert "покрыто" in txt and "## Вердикт" in txt
    assert "Чего этот замер НЕ говорит" in txt


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
