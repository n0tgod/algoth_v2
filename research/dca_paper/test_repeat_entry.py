#!/usr/bin/env python3
"""Проверки замера «пропустить первый вход»: разметка номера входа по имени
(как «одна на имя»), склейка двух рук в секунду, сброс после выхода,
нетто длинной записи из заполнений той же формулой, что у короткого ядра,
подмножества для кассы, статистика по k и гейт плеча книги, вердикт по
стороне, отчёт на две стороны без пустот."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repeat_entry as RE                                     # noqa: E402
import run_d10 as D10                                         # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _rec(sym, at, pnl=0.05, fwd=10.0, hold_h=6, lev=10.0):
    r = TP._rec(sym=sym, at=at, lev=lev, pnl=pnl)
    r["fwd"] = fwd
    r["exit_ts"] = at + hold_h * H
    return r


def _long(sym, at, pnl=0.05, fwd=10.0, hold_h=30, lev=5.0, weights=(0.25, 0.25, 0.5)):
    """Длинная запись ядра `run_d6`: нетто не записано, есть заполнения (момент, цена, доля)."""
    r = _rec(sym, at, pnl=pnl, fwd=fwd, hold_h=hold_h, lev=lev)
    del r["pnl_net"]
    r["side"] = "long"
    r["fills"] = [[at + i * H, 100.0 - i, w] for i, w in enumerate(weights)]
    return r


def test_label_counts_repeats_while_first_is_open_and_resets_after_exit():
    recs = [_rec("A", AT), _rec("A", AT + H), _rec("A", AT + 2 * H),       # k 1, 2, 3
            _rec("A", AT + 7 * H),                                            # первый вышел в +6 ч → снова 1
            _rec("A", AT + 8 * H),                                            # 2
            _rec("B", AT + H), _rec("B", AT + 9 * H)]                         # своё имя: 1, 1
    lab = RE.label(recs)
    got = [(r["sym"], int((r["at"] - AT) / H), r["k"]) for r in lab]
    assert got == [("A", 0, 1), ("A", 1, 2), ("B", 1, 1), ("A", 2, 3), ("A", 7, 1), ("A", 8, 2), ("B", 9, 1)], got


def test_two_arms_same_second_are_one_record_with_bigger_forecast():
    recs = [_rec("A", AT, fwd=5.0, pnl=0.01), _rec("A", AT, fwd=9.0, pnl=0.02), _rec("A", AT + H)]
    lab = RE.label(recs)
    assert len(lab) == 2 and lab[0]["fwd"] == 9.0 and lab[0]["k"] == 1 and lab[1]["k"] == 2
    # открытые и без нетто не входят
    bad = dict(_rec("C", AT), state="open")
    assert all(r["sym"] != "C" for r in RE.label([bad]))
    nonet = dict(_rec("D", AT))
    del nonet["pnl_net"]
    del nonet["fills"]
    assert RE.label([nonet]) == []


def test_long_record_net_is_core_formula_from_fills_and_check_catches_mismatch():
    r = _long("A", AT, pnl=0.10, lev=5.0, weights=(0.25, 0.25, 0.5))
    # ядро: filled_notional = Σ долей × плечо; нетто = pnl − filled × круг
    assert abs(RE.filled_of(r) - 5.0) < 1e-12
    want = 0.10 - 5.0 * D10.ROUND_COST_BP / 1e4
    assert abs(RE.net_of(r) - want) < 1e-12
    lab = RE.label([r])
    assert len(lab) == 1 and abs(lab[0]["pnl_net"] - want) < 1e-12 and lab[0]["k"] == 1
    # частичное заполнение — меньше нотионала, меньше издержек
    half = _long("B", AT, pnl=0.10, lev=5.0, weights=(0.25,))
    assert RE.net_of(half) > RE.net_of(r)
    # записанное ядром нетто главнее формулы
    s = _rec("C", AT, pnl=0.10)
    assert RE.net_of(s) == s["pnl_net"]
    # сверка с ядром: короткая запись несёт и filled, и fills
    ok = dict(_long("D", AT, lev=5.0, weights=(0.25, 0.25, 0.5)), filled=5.0)
    bad = dict(_long("E", AT, lev=5.0, weights=(0.25, 0.25, 0.5)), filled=4.0)
    chk = RE.net_check([ok, r])
    assert chk == {"checked": 1, "mismatch": 0, "worst": 0.0}, chk
    chk2 = RE.net_check([ok, bad])
    assert chk2["checked"] == 2 and chk2["mismatch"] == 1 and abs(chk2["worst"] - 1.0) < 1e-12, chk2


def test_bands_subsets_and_stats():
    recs = [_rec("A", AT + i * H, pnl=(0.10 if i else -0.05)) for i in range(6)]   # k 1..6, первый в минусе
    lab = RE.label(recs)
    assert [r["k"] for r in lab] == [1, 2, 3, 4, 5, 6]
    assert [RE.band_of(r["k"]) for r in lab] == ["1", "2", "3", "4", "5+", "5+"]
    sub = RE.subset({"optimal_h": recs}, lambda k: k >= 2)
    assert [r["k"] for r in sub["optimal_h"]] == [2, 3, 4, 5, 6]
    st = RE.by_k(lab, "optimal_h")
    assert st["1"]["n"] == 1 and st["1"]["hit"] == 0.0
    assert st["2+"]["n"] == 5 and st["2+"]["hit"] == 1.0 and st["all"]["n"] == 6
    assert st["5+"]["n"] == 2 and abs(st["2+"]["exp_q"] - (0.10 - 0.01) / 10.0) < 1e-12
    # длинные книги: у агрессивной гейт плеча ≥ 4 режет статистику записей, у оптимальной — нет
    longs = [_long("A", AT + i * H, lev=(3.0 if i % 2 else 6.0)) for i in range(4)]
    lab_l = RE.label(longs)
    assert [r["k"] for r in lab_l] == [1, 2, 3, 4]
    assert RE.by_k(lab_l, "optimal")["all"]["n"] == 4
    assert RE.by_k(lab_l, "aggr")["all"]["n"] == 2


def test_sides_are_declared_from_registries():
    assert RE.SIDES["short"]["keys"] == ["safe_h", "optimal_h", "aggr_h"]
    assert RE.SIDES["long"]["keys"] == ["safe", "optimal", "aggr"]
    assert RE.SIDES["short"]["judge"] == ("optimal_h", "aggr_h") and RE.SIDES["long"]["judge"] == ("optimal", "aggr")
    assert RE.SIDE_ORDER == ("short", "long")


def test_verdict_and_report_have_no_holes():
    cells = {"k1": {"optimal_h": {"final": 0.11, "max_dd": -0.042}, "aggr_h": {"final": 0.14, "max_dd": -0.065}},
             "k2plus": {"optimal_h": {"final": 0.20, "max_dd": -0.04}, "aggr_h": {"final": 0.25, "max_dd": -0.06}},
             "k3plus": {"optimal_h": {}, "aggr_h": {}}}
    beat_ok = {"k2plus": {"optimal_h": {"final": 0.0, "ratio": 0.01}, "aggr_h": {"final": 0.02, "ratio": 0.0}}}
    assert RE.verdict(cells, beat_ok).startswith("РЫЧАГ")
    beat_no = {"k2plus": {"optimal_h": {"final": 0.0, "ratio": 0.01}, "aggr_h": {"final": 0.40, "ratio": 0.0}}}
    assert RE.verdict(cells, beat_no).startswith("не рычаг")
    worse = dict(cells, k2plus={"optimal_h": {"final": 0.05, "max_dd": -0.04}, "aggr_h": {"final": 0.25, "max_dd": -0.06}})
    assert RE.verdict(worse, beat_ok).startswith("не рычаг"), "лучше случайных, но хуже книги — не рычаг"
    # судимые книги — параметр стороны: те же числа под длинными ключами
    cells_l = {k: {bk.replace("_h", ""): v for bk, v in d.items()} for k, d in cells.items()}
    beat_l = {"k2plus": {bk.replace("_h", ""): v for bk, v in beat_ok["k2plus"].items()}}
    assert RE.verdict(cells_l, beat_l, judge=("optimal", "aggr")).startswith("РЫЧАГ")

    def side_fixture(keys, judge, with_check):
        recs = [_rec("A", AT + i * H, pnl=(0.10 if i else -0.05)) for i in range(6)]
        lab = RE.label(recs)
        bk = keys[0]
        return {"title": "т", "books": [bk], "judge_books": list(judge),
                "records": {bk: {"n": 6, "by_k": RE.by_k(lab, bk), "share_k": {n: 1 / 6 for n in RE.K_BANDS}}},
                "cash": {k: {bk: {"n": 3, "final": 0.1, "max_dd": -0.05, "wo3": 100.0, "sigma_day": 20.0}}
                         for k, _t, _p in RE.CELLS},
                "sizes": {k: {bk: 5} for k, _t, _p in RE.CELLS},
                "beat": {"k2plus": {bk: {"final": 0.1, "ratio": 0.2, "random_final_med": 0.05, "random_ratio_med": 1.5}},
                         "k3plus": {bk: {"final": None, "ratio": None, "random_final_med": None, "random_ratio_med": None}}},
                "verdict": "не рычаг: …",
                "diag": {"records": 6, "net_check": ({"checked": 6, "mismatch": 0, "worst": 0.0} if with_check
                                                     else {"checked": 0, "mismatch": 0, "worst": 0.0})},
                "secs": 10.0}
    s = {"dep": 10000, "seeds": 200, "beat_max": 0.05, "cells": [(k, t) for k, t, _p in RE.CELLS],
         "k_bands": list(RE.K_BANDS), "side_order": ["short", "long"],
         "sides": {"short": side_fixture(["optimal_h"], ("optimal_h", "aggr_h"), True),
                   "long": side_fixture(["optimal"], ("optimal", "aggr"), False)},
         "verdict": "короткие: не рычаг: …; длинные: не рычаг: …",
         "computed_at": "2026-10-06 09:30", "secs": 10.0}
    md = RE.report(s)
    assert "None" not in md and "nan" not in md, md[:500]
    assert "# Короткие сделки" in md and "# Длинные сделки" in md
    assert "| k = 1 |" in md and "| k ≥ 2 (все повторы) |" in md
    assert "расхождений 0" in md and "Сверка формулы нетто с ядром здесь невозможна" in md
    # сторона без кэша — ошибка словами, остальное печатается
    s2 = dict(s, sides=dict(s["sides"], long={"title": "т", "books": ["optimal"], "judge_books": ["optimal", "aggr"],
                                               "error": "кэш реплея непригоден: кэша нет"}))
    md2 = RE.report(s2)
    assert "ОШИБКА: кэш реплея непригоден" in md2 and "# Короткие сделки" in md2
    # расхождение формулы с ядром кричит
    s3 = dict(s, sides=dict(s["sides"]))
    s3["sides"]["short"] = dict(s["sides"]["short"], diag={"records": 6, "net_check": {"checked": 6, "mismatch": 2, "worst": 0.5}})
    assert "ФОРМУЛА РАСХОДИТСЯ С ЯДРОМ" in RE.report(s3)


def test_run_both_sides_offline_smoke_on_core_shaped_records():
    """Обе стороны проходят свою дорогу кассы целиком на подставных кэшах:
    короткие — записи ядра `run_d10` (с `pnl_net`), длинные — записи ядра
    `run_d6` (без `pnl_net`, с заполнениями). Зёрен два — проверяется дорога,
    не числа."""
    import test_paper as TPP
    import run_paper as RP
    import run_short as S
    T0, HH = TPP.T0, 3600.0
    names = ("AAAUSDT", "BBBUSDT", "CCCUSDT")

    def short_cache():
        c = {}
        for ni, sym in enumerate(names):
            for blk in range(2):
                for j in range(6):                      # k 1..6 внутри блока, срок 6 ч; первые два выбора в минусе — у кассы есть просадка
                    at = T0 + blk * 48 * HH + j * HH + ni * 7
                    r = TPP._rec(at, hold_h=6.0, pnl=(-0.05 if j < 2 else 0.08), lev=6.0, fwd=30.0 + j, sym=sym)
                    r["side"] = "short"
                    # как пишет короткое ядро: заполненный нотионал и нетто записаны
                    r["filled"] = 6.0 * 0.25
                    r["pnl_net"] = r["pnl"] - r["filled"] * D10.ROUND_COST_BP / 1e4
                    for rk in set(S.BOOKS.values()):
                        c[(rk, sym, round(at, 3))] = dict(r)
        return c, None

    def long_cache():
        c = {}
        for ni, sym in enumerate(names):
            for blk in range(2):
                for j in range(6):
                    at = T0 + blk * 96 * HH + j * HH + ni * 7
                    r = TPP._rec(at, hold_h=30.0, pnl=(-0.04 if j < 2 else 0.06), lev=6.0, fwd=30.0 + j, sym=sym)
                    for k in RE.SIDES["long"]["keys"]:
                        c[(tuple(RP.RULERS[k]), sym, round(at, 3))] = dict(r)
        return c, None

    saved = {sd: RE.SIDES[sd]["read"] for sd in RE.SIDE_ORDER}
    try:
        RE.SIDES["short"]["read"] = lambda log: short_cache()
        RE.SIDES["long"]["read"] = lambda log: long_cache()
        s = RE.run(log=lambda *a: None, now=T0 + 400 * HH, launch={}, ctx={"error": "рядов нет"},
                   mem_limit=10 ** 6, seeds=2)
    finally:
        for sd, fn in saved.items():
            RE.SIDES[sd]["read"] = fn
    assert s["side_order"] == ["short", "long"], s["side_order"]
    for side in RE.SIDE_ORDER:
        sd = s["sides"][side]
        assert not sd.get("error"), sd.get("error")
        for bk in sd["books"]:
            rec = sd["records"][bk]
            assert rec["n"] == 36 and rec["by_k"]["1"]["n"] == 6 and rec["by_k"]["2+"]["n"] == 30, (side, bk, rec["n"])
            assert sd["sizes"]["k1"][bk] == 6 and sd["sizes"]["k2plus"][bk] == 30 and sd["sizes"]["k3plus"][bk] == 24
            for key in ("k1", "k2plus", "k3plus"):
                c = sd["cash"][key][bk]
                assert c.get("n") and c.get("final") is not None, (side, bk, key, c)
            # касса под «одна на имя» берёт по одной позиции на блок имени: 3 имени × 2 блока
            assert sd["cash"]["k1"][bk]["n"] == 6 and sd["cash"]["k2plus"][bk]["n"] == 6, (side, bk, sd["cash"]["k2plus"][bk]["n"])
            b = sd["beat"]["k2plus"][bk]
            assert b["final"] is not None and b["ratio"] is not None, (side, bk, b)
        assert sd["verdict"].startswith(("РЫЧАГ", "не рычаг")), sd["verdict"]
    # длинная запись без нетто получила нетто из заполнений; короткая сверена с ядром
    assert s["sides"]["long"]["diag"]["net_check"]["checked"] == 0
    chk = s["sides"]["short"]["diag"]["net_check"]
    assert chk["checked"] > 0 and chk["mismatch"] == 0, chk
    md = RE.report(s)
    assert "None" not in md and "nan" not in md and "# Длинные сделки" in md, md[:400]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
