#!/usr/bin/env python3
"""Проверки замера D9 — варианты выхода коротких DCA-книг.

Фикстуры записей берутся у проверок D7 (`_bars`, `_walk`, `_rec`): вариант
выхода есть пересчёт ТОЙ ЖЕ записи с контрольными точками, и вторая
сборка записи здесь разошлась бы с той, что судит D7.
"""

import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d7 as D7                                           # noqa: E402
import run_d9 as D9                                           # noqa: E402
import test_run_d7 as T7                                      # noqa: E402
import test_run_d8 as T8                                      # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import rules as R                                             # noqa: E402

H = 3600
T0 = T7.T0
N = 170 * 60                            # бары на 170 часов: все точки сетки
TAKE = 100.5


def _path_loser_recovers():
    """Минус к 24 ч, плоско до 48 ч, к 70 ч доходит до тейка."""
    def f(i):
        if i < 1440:
            return 100.0 - 5.0 * i / 1440.0
        if i < 2880:
            return 95.0
        if i < 4320:
            return 95.0 + 6.0 * (i - 2880) / 1440.0
        return 101.0
    return T7._walk(N, f)


def _path_winner_flat():
    """Плюс к 24 ч и плоско дальше: до тейка не доходит никогда."""
    return T7._walk(N, lambda i: 100.0 + 0.3 * min(i, 1440) / 1440.0)


def _path_level_early():
    """Тейк задет к пятому часу — раньше любого T сетки."""
    return T7._walk(N, lambda i: 100.0 + 1.0 * min(i, 600) / 600.0)


def _rec(path, sym):
    r, _rp, _w = T7._rec(T7._bars(path), D9.HOLDS, take=TAKE)
    r["sym"] = sym
    return r


def _same(a, b):
    return (a["exit"] == b["exit"] and int(a["exit_ts"]) == int(b["exit_ts"])
            and abs(float(a["pnl"]) - float(b["pnl"])) < 1e-12)


def test_grid_is_declared_before_the_run():
    g = D9.grid()
    assert len(g) == 20, len(g)
    assert sum(1 for c in g if c[0] == "A") == 5
    assert sum(1 for c in g if c[0] == "B") == 10
    assert sum(1 for c in g if c[0] == "C") == 5
    assert D9.REF_H in D9.HOLDS and D9.HOLDS == D7.HOLDS_H
    for (mode, t, h, th) in g:
        assert t in D9.HOLDS, (mode, t)
        if mode != "A":
            assert h in D9.HOLDS and t < h, (mode, t, h)
            assert D9.base_key((mode, t, h, th)) == f"A:{h}"
    assert len({D9.cell_key(c) for c in g}) == 20, "ключи ячеек не уникальны"
    print("ok  сетка объявлена: 5 таймеров, 10 «резать минус», 5 «наоборот»")


def test_timer_equals_d7_truncation():
    """Ячейка A — ровно усечение D7, бит в бит; своего счёта у неё нет."""
    r = _rec(_path_loser_recovers(), "AAAUSDT")
    for i, h in enumerate(D9.HOLDS):
        a = D9.decide(r, "A", h)
        b = D7.truncate(r, h, i)
        assert a is not None and b is not None, h
        assert _same(a, b), (h, a["exit"], b["exit"])
        assert a["d9"] == "timer"
    print("ok  таймер A равен усечению D7 на всех сроках")


def test_cut_losers_at_T_and_hold_the_rest_to_H():
    """B: минус глубже θ режется на T, остальное живёт до H.

    Позиция-неудачник: −5 % к 24 ч, к 70 ч доходит до тейка. При θ = 0 B
    закрывает её на 24 ч в минус — тейка она не увидит; при щедром θ
    она удержана и берёт тейк. Позиция-победитель на 24 ч в плюсе —
    B её не трогает и держит до H.
    """
    lo = _rec(_path_loser_recovers(), "AAAUSDT")
    wn = _rec(_path_winner_flat(), "BBBUSDT")
    cut = D9.decide(lo, "B", 24, 72, 0.0)
    assert cut["d9"] == "cut" and cut["exit"] == "срок", cut["exit"]
    assert float(cut["pnl"]) < 0, cut["pnl"]
    assert abs(float(cut["exit_ts"]) - (T0 + 24 * H)) <= 120, cut["exit_ts"]
    held = D9.decide(lo, "B", 24, 72, 0.5)
    assert held["d9"] == "held" and held["exit"] == "тейк", held["exit"]
    assert _same(held, D7.truncate(lo, 72, D9.HOLDS.index(72)))
    assert float(held["pnl"]) > 0
    w = D9.decide(wn, "B", 24, 72, 0.0)
    assert w["d9"] == "held" and w["exit"] == "срок", w
    assert abs(float(w["exit_ts"]) - (T0 + 72 * H)) <= 120, w["exit_ts"]
    assert float(w["pnl"]) > 0
    print("ok  B: минус срезан на T, щедрый θ и плюс удержаны до H")


def test_lock_winners_is_the_mirror():
    """C: плюс фиксируется на T, минус держится до H — зеркало B."""
    lo = _rec(_path_loser_recovers(), "AAAUSDT")
    wn = _rec(_path_winner_flat(), "BBBUSDT")
    held = D9.decide(lo, "C", 24, 72, 0.0)
    assert held["d9"] == "held" and held["exit"] == "тейк", held["exit"]
    assert float(held["pnl"]) > 0
    lock = D9.decide(wn, "C", 24, 72, 0.0)
    assert lock["d9"] == "cut" and lock["exit"] == "срок", lock
    assert abs(float(lock["exit_ts"]) - (T0 + 24 * H)) <= 120, lock["exit_ts"]
    assert float(lock["pnl"]) > 0
    print("ok  C: плюс зафиксирован на T, минус удержан до тейка")


def test_level_exit_before_T_is_untouched_by_every_variant():
    """Тейк к пятому часу: ни один вариант не вправе его переписать."""
    r = _rec(_path_level_early(), "CCCUSDT")
    assert r["exit"] == "тейк" and float(r["exit_ts"]) < T0 + 24 * H
    for c in D9.grid():
        mode, t, h, th = c
        got = D9.decide(r, mode, t, h, th or 0.0)
        assert got is not None, c
        assert _same(got, r), (c, got["exit"], got["exit_ts"])
        assert got["d9"] == ("timer" if mode == "A" else "level"), (c, got["d9"])
    print("ok  уровень раньше T не тронут ни одним из 20 вариантов")


def test_aggr_is_the_base_pass_under_its_leverage_gate():
    """`aggr_s` — записи `optimal_s` при плече не ниже гейта режима."""
    ml = R.min_lev_of("aggr_s")
    assert ml is not None and ml > 1.0, ml
    recs = {"optimal_s": [{"lev": 1.0, "sym": "A"}, {"lev": ml, "sym": "B"},
                          {"lev": ml * 2, "sym": "C"},
                          {"lev": ml - 0.01, "sym": "D"}]}
    got = D9.book_recs(recs, "aggr_s")
    assert [r["sym"] for r in got] == ["B", "C"], got
    assert D9.book_recs(recs, "optimal_s") == recs["optimal_s"]
    print(f"ok  aggr_s = optimal_s под гейтом плеча ≥ {ml:g}× (2 из 4)")


def test_cell_goes_through_the_book_cash():
    """Ячейка — касса и форма книги: взято обеих, раскладка d9 честная."""
    lo = _rec(_path_loser_recovers(), "AAAUSDT")
    wn = _rec(_path_winner_flat(), "BBBUSDT")
    c = D9.cell([lo, wn], ("B", 24, 72, 0.0), 1000.0, "optimal_s")
    assert c["taken"] == 2, c
    assert c["d9"] == {"cut": 1, "held": 1}, c["d9"]
    assert c["exits"] == {"срок": 2}, c["exits"]
    assert c["mode"] == "B" and c["t"] == 24 and c["h"] == 72
    print("ok  ячейка прошла через кассу: 2 взято, cut 1 / held 1")


def _rise_then_fall(t0=1_700_000_000, pre=1440, top=106.0, low=90.0,
                    post=10500, flat_h=24):
    """Путь ШОРТА-неудачника: рост к 24 ч (доливы вверх), плоско, потом
    падение до цели к ~65 ч и плато до 170 ч — все точки сетки есть."""
    bars = []
    for i in range(pre):
        px = 100.0 + 0.1 * ((i * 7919) % 11 - 5) / 5.0
        bars.append((t0 + i * 60, px, px + 0.05, px - 0.05, px, 1000.0))
    at = t0 + pre * 60
    n_up, n_flat, n_dn = 1440, flat_h * 60, 1440
    path = [100.0 + (top - 100.0) * j / (n_up - 1) for j in range(n_up)]
    path += [top] * n_flat
    path += [top - (top - low) * j / (n_dn - 1) for j in range(n_dn)]
    path += [low + 0.1 * ((j * 7919) % 11 - 5) / 5.0
             for j in range(max(0, post - len(path)))]
    for j, px in enumerate(path):
        bars.append((at + j * 60, px, px + 0.05, px - 0.05, px, 1000.0))
    return bars, at


def _drift_down(t0=1_700_000_000, pre=1440, post=10500):
    """Путь шорта-победителя: −0.5 % к 24 ч и плоско — цели не достигает."""
    bars = []
    for i in range(pre):
        px = 100.0 + 0.1 * ((i * 7919) % 11 - 5) / 5.0
        bars.append((t0 + i * 60, px, px + 0.05, px - 0.05, px, 1000.0))
    at = t0 + pre * 60
    for j in range(post):
        px = 100.0 - 0.5 * min(j, 1440) / 1440.0 \
            + 0.02 * ((j * 7919) % 11 - 5) / 5.0
        bars.append((at + j * 60, px, px + 0.05, px - 0.05, px, 1000.0))
    return bars, at


def _legs(at, side, sym, n=10):
    out = []
    for i in range(n):
        g = dict(T3._leg(at + (i % 5) * 3600))
        g["sym"], g["side"], g["fwd"] = sym, side, 40.0 + i
        if side == "short":
            g["fav"], g["adv_q"] = -500.0, 5000.0
        out.append(g)
    return out


def test_run_end_to_end_synthetic():
    """Сквозной прогон run → report на подставных барах обеих сторон.

    Дороги `collect_recs` → общая выборка → ячейки → половины → отчёт
    `py_compile` не видит, а прошлые замеры падали ровно на последнем
    шаге после часа счёта. Легенда: шорт-неудачник (в минусе на 24 ч,
    к 65 ч доходит до цели), шорт-победитель (плюс с первых суток, цели
    не достигает), длинный контроль на пути D8.
    """
    lo, at = _rise_then_fall()
    wn, _ = _drift_down()
    lg, _ = T8._dip_then_rise(post=10200)
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn, "AAAUSDT": lg})
    legs = (_legs(at, "short", "SSSUSDT") + _legs(at, "short", "TTTUSDT")
            + _legs(at, "long", "AAAUSDT"))
    orig_legs, orig_lv = D6.gated_legs, D2.build_levels
    D6.gated_legs = lambda **kw: legs
    D2.build_levels = lambda w, i: np.array([98.0, 95.0, 90.0,
                                             102.0, 105.0, 110.0])
    try:
        s = D9.run(src=src, log=lambda *a: None)
    finally:
        D6.gated_legs, D2.build_levels = orig_legs, orig_lv
    assert s["books"] == ["optimal_s", "safe_s", "aggr_s", "optimal"], s["books"]
    assert s["control_book"] == "optimal"
    assert s["sample"]["optimal_s"] == 20 and s["sample"]["optimal"] == 10, \
        s["sample"]
    dep = int(R.DEPOSITS[-1])
    for k in s["books"]:
        assert len(s["cells"][k]) == 20 * len(R.DEPOSITS), k
    cb = s["cells"]["optimal_s"]
    a72 = cb[f"A:72@{dep}"]
    assert a72["taken"] == 2, a72                # одно имя — одна позиция
    b = cb[f"B:24:72:0@{dep}"]
    assert b["d9"].get("cut", 0) >= 1 and b["d9"].get("held", 0) >= 1, b["d9"]
    c = cb[f"C:24:72:0@{dep}"]
    assert c["d9"].get("cut", 0) >= 1 and c["d9"].get("held", 0) >= 1, c["d9"]
    # неудачник: B срезал минус, C дал ему дойти до цели — значит по итогу
    # C выше B на тех же позициях, и парная разность это видит
    sm = D9.summarize(s)["optimal_s"]
    assert sm["paired"]["C:24:72:0"] > sm["paired"]["B:24:72:0"], sm["paired"]
    assert "optimal_s" in s["half"] and "optimal" not in s["half"]
    assert s["lev_split"]["optimal_s"]["lev_gt1"]["n"] >= 1, s["lev_split"]
    txt = D9.report(s)
    assert "(контроль, лонг)" in txt and "aggr_s" in txt, txt[:600]
    assert "ошибка R5" in txt and "Δ к A:H" in txt
    print(f"ok  сквозной прогон: книг {len(s['books'])}, ячеек "
          f"{sum(len(v) for v in s['cells'].values())}, "
          f"B:24→72 cut/held {b['d9']}, C {c['d9']}")


def _stub_summary(flip_c=False, neg=False):
    """Свод по образцу живого: одна короткая книга, депозит один."""
    dep = 100000.0
    grid = [D9.cell_key(c) for c in D9.grid()]
    fin = {"A:72": 0.010, "B:24:72:0": 0.030, "C:24:72:0": 0.020}
    if neg:
        # все ячейки в минусе: вопрос «в плюс?» получает «нет», а
        # уменьшение убытка остаётся отдельным числом
        fin = {k: v - 0.05 for k, v in fin.items()}
    def mk(ck, f):
        return {"taken": 3, "final": f, "max_dd": -0.01, "day_median": 0.0001,
                "day_green": 0.6, "bite": 2.0, "day_worst": -0.005,
                "worst_pos": -0.1, "exits": {"срок": 3}, "d9": {"held": 3},
                "open_mean": 1.0, "liq_share": 0.0, "mode": ck[0],
                "t": 24, "h": 72, "theta": 0.0}
    other = -0.07 if neg else -0.02
    cells = {f"{ck}@{int(dep)}": mk(ck, fin.get(ck, other)) for ck in grid}
    hc = {}
    for ck in grid:
        for side in ("A", "B"):
            f = fin.get(ck, other)
            if ck == "B:24:72:0" and side == "B":
                f = 0.0          # B хуже таймера во второй половине
            if ck == "C:24:72:0" and flip_c and side == "A":
                f = 0.0          # C хуже таймера в первой половине
            hc[f"{side}:{ck}"] = mk(ck, f)
    return {"holds_h": D9.HOLDS, "ref_h": D9.REF_H, "pairs": D9.PAIRS,
            "thetas": D9.THETAS, "grid": grid, "deposits": [dep],
            "books": ["optimal_s"], "short_books": ["optimal_s"],
            "control_book": None, "positions": {"optimal_s": 5},
            "sample": {"optimal_s": 4}, "lost_short_record": {"optimal_s": 1},
            "window": {"from": "2026-08-08", "to": "2026-09-05",
                       "span_d": 28, "dates": 28},
            "cells": {"optimal_s": cells},
            "half": {"optimal_s": {"mid_ts": 0, "n_a": 2, "n_b": 2,
                                   "deposit": dep, "cells": hc}},
            "lev_split": {"optimal_s": {
                "lev1": {"n": 3, "pnl_sum": 0.01, "pnl_median": 0.002,
                         "pnl_worst": -0.01, "lev_median": 1.0,
                         "exits": {"тейк": 2, "срок": 1}},
                "lev_gt1": {"n": 1, "pnl_sum": -0.5, "pnl_median": -0.5,
                            "pnl_worst": -0.5, "lev_median": 12.0,
                            "exits": {"пол": 1}}}},
            "min_lev": {"aggr_s": 4.0}, "secs": 1.0,
            "computed_at": "2026-09-06 00:00"}


def test_verdict_is_derived_from_paired_numbers_on_both_halves():
    """Вердикт — из парной разности и её знака на половинах, не из прозы.

    B:24:72 лучше таймера на целом (+2 п.п.), но во второй половине хуже
    — устойчивой она не считается; C:24:72 лучше в обеих половинах —
    устойчива. Перевернём C — устойчивых ноль, и фраза обязана смениться.
    """
    s = _stub_summary()
    sm = D9.summarize(s)["optimal_s"]
    assert abs(sm["paired"]["B:24:72:0"] - 0.02) < 1e-9, sm["paired"]
    assert abs(sm["paired"]["C:24:72:0"] - 0.01) < 1e-9, sm["paired"]
    assert set(sm["better"]) == {"B:24:72:0", "C:24:72:0"}, sm["better"]
    assert sm["stable"] == ["C:24:72:0"], sm["stable"]
    assert sm["n_cond"] == 15
    txt = D9.report(s)
    for need in ("ошибка R5", "Δ к A:H", "половинах окна",
                 "устойчивых по половинам 1", "направление есть",
                 "РАЗОШЁЛСЯ", "1× против лестницы"):
        assert need in txt, need
    # разность к НЫНЕШНЕМУ правилу (A:72) — своя колонка и свой счёт:
    # B:24:72 и C:24:72 выше A:72 на целом, устойчиво — только C
    assert abs(sm["vs_ref"]["B:24:72:0"] - 0.02) < 1e-9, sm["vs_ref"]
    assert sm["vs_ref"]["A:72"] is None
    assert set(sm["better_ref"]) == {"B:24:72:0", "C:24:72:0"}, sm["better_ref"]
    assert sm["stable_ref"] == ["C:24:72:0"], sm["stable_ref"]
    assert "Δ к 72 ч" in txt and "устойчиво лучше нынешних 72 ч" in txt
    assert "положительных по итогу и медиане дня **3**" in txt
    s2 = _stub_summary(flip_c=True)
    sm2 = D9.summarize(s2)["optimal_s"]
    assert sm2["stable"] == [] and sm2["stable_ref"] == [], sm2
    txt2 = D9.report(s2)
    assert "устойчивых по половинам 0" in txt2
    assert "**ни одной**" in txt2 and "**1**: C:24:72:0" not in txt2
    # все ячейки в минусе: главный ответ — «в плюс не выводит ни одна»
    s3 = _stub_summary(neg=True)
    txt3 = D9.report(s3)
    assert "положительных по итогу и медиане дня **0**" in txt3
    assert "не выводит ни одна ячейка сетки" in txt3, txt3[-3000:]
    assert "направление есть" not in txt3
    assert "не выводит ни одна ячейка сетки" not in txt, "фраза не из чисел"
    # механизм по плечу — из знаков раскладки: 1× в плюсе, лестница в минусе
    assert "весь убыток приносит лестница с плечом" in txt3
    print("ok  вердикт выведен из чисел: «в плюс?» по знаку ячеек, "
          "«лучше нынешних» по половинам, механизм по знакам плеча")


def test_main_publishes_by_default_and_not_with_the_flag():
    calls = []
    orig_run, orig_pub, orig_out = D9.run, D9.publish, D9.OUT
    D9.run = lambda **kw: _stub_summary()
    D9.publish = lambda name: calls.append(name)
    try:
        with tempfile.TemporaryDirectory() as td:
            D9.OUT = td
            D9.main(["--no-publish", "--tag", "t"])
            assert calls == [], calls
            assert os.path.exists(os.path.join(td, "D9-exit-t.md"))
            D9.main(["--tag", "t"])
            assert len(calls) == 1 and "D9" in calls[0], calls
            jp = os.path.join(td, "D9-exit-t.json")
            with open(jp, encoding="utf-8") as f:
                assert json.load(f)["grid"][0] == "A:24"
            # пересборка отчёта из артефакта: считать не зовёт вовсе
            D9.run = lambda **kw: (_ for _ in ()).throw(
                AssertionError("--from-json не должен считать"))
            os.remove(os.path.join(td, "D9-exit-t.md"))
            D9.main(["--from-json", jp, "--tag", "t", "--no-publish"])
            assert os.path.exists(os.path.join(td, "D9-exit-t.md"))
    finally:
        D9.run, D9.publish, D9.OUT = orig_run, orig_pub, orig_out
    print("ok  публикует по умолчанию, молчит по флагу")


# --- отрицательные контроли ---------------------------------------------
def _with_decide(bad, test):
    orig = D9.decide
    D9.decide = bad
    try:
        try:
            test()
        except AssertionError:
            return True
        return False
    finally:
        D9.decide = orig


def _control_theta_ignored():
    """B режет любой минус, порог θ не читается."""
    orig = D9.decide
    return _with_decide(lambda r, m, t, h=None, theta=0.0:
                        orig(r, m, t, h, 0.0),
                        test_cut_losers_at_T_and_hold_the_rest_to_H)


def _control_cut_regardless_of_mark():
    """B закрывает на T всё открытое, отметку не смотрит."""
    def bad(r, mode, t, h=None, theta=0.0):
        a = D7.truncate(r, t, D9.HOLDS.index(t))
        if a is None or mode == "A":
            return None if a is None else dict(a, d9="timer")
        return dict(a, d9="cut" if a["exit"] == "срок" else "level")
    return _with_decide(bad, test_cut_losers_at_T_and_hold_the_rest_to_H)


def _control_level_exit_overridden():
    """Вариант судит и позицию, вышедшую по уровню раньше T."""
    def bad(r, mode, t, h=None, theta=0.0):
        a = D7.truncate(r, t, D9.HOLDS.index(t))
        if a is None or mode == "A":
            return None if a is None else dict(a, d9="timer")
        mark = float(a["pnl"])
        cut = (mark < -theta) if mode == "B" else (mark > theta)
        if cut:
            return dict(a, d9="cut", exit="срок",
                        exit_ts=float(r["at"]) + t * H)
        b = D7.truncate(r, h, D9.HOLDS.index(h))
        return None if b is None else dict(b, d9="held")
    return _with_decide(bad,
                        test_level_exit_before_T_is_untouched_by_every_variant)


def _control_gate_not_applied():
    orig = D9.book_recs
    D9.book_recs = lambda recs, key: list(recs[D9.DERIVED.get(key, key)])
    try:
        try:
            test_aggr_is_the_base_pass_under_its_leverage_gate()
        except AssertionError:
            return True
        return False
    finally:
        D9.book_recs = orig


def _control_verdict_ignores_the_sign():
    """Фраза «в плюс не выводит» стоит литералом, а не выводится из чисел."""
    orig = D9.report

    def bad(s):
        # фраза стоит ЛИТЕРАЛОМ при любых числах
        return orig(s) + "\n\n**В плюс короткие книги не выводит ни одна " \
            "ячейка сетки**\n"
    D9.report = bad
    try:
        try:
            test_verdict_is_derived_from_paired_numbers_on_both_halves()
        except AssertionError:
            return True
        return False
    finally:
        D9.report = orig


def _control_stability_ignores_halves():
    """«Устойчива» = «лучше на целом», половины не спрашиваются."""
    orig = D9.summarize

    def bad(s):
        out = orig(s)
        for k in out:
            out[k]["stable"] = list(out[k]["better"])
        return out
    D9.summarize = bad
    try:
        try:
            test_verdict_is_derived_from_paired_numbers_on_both_halves()
        except AssertionError:
            return True
        return False
    finally:
        D9.summarize = orig


TESTS = [test_grid_is_declared_before_the_run,
         test_timer_equals_d7_truncation,
         test_cut_losers_at_T_and_hold_the_rest_to_H,
         test_lock_winners_is_the_mirror,
         test_level_exit_before_T_is_untouched_by_every_variant,
         test_aggr_is_the_base_pass_under_its_leverage_gate,
         test_cell_goes_through_the_book_cash,
         test_run_end_to_end_synthetic,
         test_verdict_is_derived_from_paired_numbers_on_both_halves,
         test_main_publishes_by_default_and_not_with_the_flag]

CONTROLS = [("θ не читается", _control_theta_ignored),
            ("B режет всё открытое", _control_cut_regardless_of_mark),
            ("уровень раньше T переписан", _control_level_exit_overridden),
            ("гейт плеча не применён", _control_gate_not_applied),
            ("устойчивость без половин", _control_stability_ignores_halves),
            ("вердикт не из знака", _control_verdict_ignores_the_sign)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
