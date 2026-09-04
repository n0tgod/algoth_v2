#!/usr/bin/env python3
"""Проверки замера соответствия имён режимов."""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import name_check as N                                        # noqa: E402

H = 3600
T0 = 1_700_000_000


def _row(at, hold_h, margin, dep=10000, ruler="optimal", pnl=0.01,
         sym="AAAUSDT", lev=3.0, exit_="тейк"):
    return {"dep": dep, "ruler": ruler, "at": float(at),
            "exit_ts": float(at + hold_h * H), "sym": sym, "lev": lev,
            "margin": float(margin), "pnl_frac": pnl,
            "usd": pnl * margin, "exit": exit_, "rules": R.RULES}


def test_load_is_money_weighted_by_time():
    """Загрузка — деньги, взвешенные ВРЕМЕНЕМ, а не доля сделок.

    Иначе книга из редких, но полных вложений выглядела бы такой же, как
    книга из постоянных мелких, — а именно этим и различаются режимы.
    """
    dep = 10000.0
    full = [_row(T0, 10, dep)]                       # весь депозит на всё окно
    load, peak = N.load_share(full, dep)
    assert abs(load - 1.0) < 1e-9 and abs(peak - 1.0) < 1e-9, (load, peak)
    half_money = [_row(T0, 10, dep / 2)]
    load2, _ = N.load_share(half_money, dep)
    assert abs(load2 - 0.5) < 1e-9, load2
    # половина ВРЕМЕНИ при полном депозите даёт ту же половину загрузки
    half_time = [_row(T0, 5, dep), _row(T0 + 10 * H, 0.001, 1.0)]
    load3, _ = N.load_share(half_time, dep)
    assert abs(load3 - 0.5) < 0.01, load3
    # две позиции по половине, идущие рядом, — та же полная загрузка
    two = [_row(T0, 10, dep / 2, sym="A"), _row(T0, 10, dep / 2, sym="B")]
    load4, peak4 = N.load_share(two, dep)
    assert abs(load4 - 1.0) < 1e-9 and abs(peak4 - 1.0) < 1e-9, (load4, peak4)
    print("ok  загрузка: деньги × время, а не доля сделок")


def test_verdict_follows_the_numbers_both_ways():
    """Вердикт выводится ИЗ загрузки, а не стоит рядом с ней.

    Недогруженный режим обязан быть назван недогруженным, а сопоставимый
    — не обязан: фраза, которая печатается всегда, ничего не сообщает.
    """
    dep = int(R.DEPOSITS[-1])
    rk = R.RULER_ORDER
    win = (float(T0), float(T0 + 10 * H))       # окно ОДНО на оба режима
    thin = {"deposits": [float(dep)], "rulers": list(rk), "book": {},
            "cells": {f"{rk[0]}:{dep}": dict(N.mode_stats(
                [_row(T0, 10, dep * 1.0, dep=dep, ruler=rk[0])], dep,
                window=win)),
                f"{rk[-1]}:{dep}": dict(N.mode_stats(
                    [_row(T0, 1, dep * 1.0, dep=dep, ruler=rk[-1])], dep,
                    window=win))}}
    txt = N.report(thin)
    assert "НЕДОГРУЗ" in txt, txt[-900:]
    assert R.ruler_title(rk[-1]).capitalize() in txt, txt[-900:]
    same = {"deposits": [float(dep)], "rulers": list(rk), "book": {},
            "cells": {f"{k}:{dep}": dict(N.mode_stats(
                [_row(T0, 10, dep * 1.0, dep=dep, ruler=k)], dep,
                window=win)) for k in rk}}
    txt2 = N.report(same)
    assert "НЕДОГРУЗ" not in txt2, txt2[-900:]
    assert "сопоставима" in txt2, txt2[-900:]
    print("ok  вердикт следует за загрузкой в обе стороны")


def test_window_is_common_to_all_modes():
    """Окно загрузки — ОДНО на все режимы депозита.

    У режима с гейтом сделок втрое меньше; мерься он своим окном, вышел
    бы полностью вложенным, и «недогруз» стал бы невидим ровно там, где
    его надо увидеть.
    """
    dep = 10000
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        rows = [_row(T0, 240, dep * 1.0, dep=dep, ruler=R.RULER_ORDER[0]),
                _row(T0, 1, dep * 1.0, dep=dep, ruler=R.RULER_ORDER[-1])]
        with open(jp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        s = N.collect(path=jp, art=os.path.join(td, "нет.json"))
        a = s["cells"][f"{R.RULER_ORDER[0]}:{dep}"]["load"]
        b = s["cells"][f"{R.RULER_ORDER[-1]}:{dep}"]["load"]
        assert abs(a - 1.0) < 1e-6, a
        assert abs(b - 1.0 / 240) < 1e-3, b        # своим окном вышло бы 1.0
    print("ok  окно загрузки общее: редкий режим не выглядит вложенным")


def test_book_numbers_come_from_the_artifact():
    """Свод книги берётся ИЗ АРТЕФАКТА и здесь не пересчитывается."""
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        ap = os.path.join(td, "a.json")
        rows = [_row(T0, 5, 100.0, ruler="optimal"),
                _row(T0 + 6 * H, 5, 100.0, ruler="optimal", sym="BBBUSDT")]
        with open(jp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(ap, "w", encoding="utf-8") as f:
            json.dump({"books": {"optimal:10000": {
                "restored": {"max_dd": -0.1234, "day_green": 0.42,
                             "bite": 7.7}}}}, f)
        s = N.collect(path=jp, art=ap)
        b = s["book"]["optimal:10000"]
        assert b["max_dd"] == -0.1234 and b["bite"] == 7.7, b
        assert "-12.34 %" in N.report(s), N.report(s)[:1500]
    print("ok  просадка и укус пришли из артефакта прогона")


def _control_load_by_trade_share():
    """Загрузка считается долей сделок, а не деньгами во времени."""
    orig = N.load_share
    N.load_share = lambda rows, dep: (min(1.0, len(rows) / 10.0), 1.0)
    try:
        try:
            test_load_is_money_weighted_by_time()
        except AssertionError:
            return True
        return False
    finally:
        N.load_share = orig


def _control_verdict_always_printed():
    """Фраза про недогруз печатается всегда — то есть не сообщает ничего."""
    orig = N.report

    def loud(s):
        return orig(s) + "\n**НЕДОГРУЗ** у всех режимов."

    N.report = loud
    try:
        try:
            test_verdict_follows_the_numbers_both_ways()
        except AssertionError:
            return True
        return False
    finally:
        N.report = orig


def _control_book_recomputed_here():
    """Свод книги считается на месте вместо чтения артефакта."""
    orig = N.collect

    def blind(path=R.JOURNAL, art=R.ARTIFACT):
        s = orig(path, art)
        for k in s["book"]:
            s["book"][k] = {"max_dd": -0.5, "day_green": 0.5, "bite": 1.0}
        return s

    N.collect = blind
    try:
        try:
            test_book_numbers_come_from_the_artifact()
        except AssertionError:
            return True
        return False
    finally:
        N.collect = orig


def _control_window_per_mode():
    """Каждый режим мерится СВОИМ окном — недогруз становится невидим."""
    orig = N.collect

    def per_mode(path=R.JOURNAL, art=R.ARTIFACT):
        rows, _bad = R.read_journal(path)
        rows = [r for r in rows if int(r.get("rules", 0)) == R.RULES]
        out = {"deposits": list(R.DEPOSITS), "rulers": list(R.RULER_ORDER),
               "cells": {}, "book": {}}
        for dep in R.DEPOSITS:
            for rk in R.RULER_ORDER:
                mine = [r for r in rows if int(r.get("dep", 0)) == int(dep)
                        and R.ruler_of(r) == rk]
                out["cells"][f"{rk}:{int(dep)}"] = N.mode_stats(mine, dep)
                out["book"][f"{rk}:{int(dep)}"] = {}
        return out

    N.collect = per_mode
    try:
        try:
            test_window_is_common_to_all_modes()
        except AssertionError:
            return True
        return False
    finally:
        N.collect = orig


TESTS = [test_load_is_money_weighted_by_time,
         test_window_is_common_to_all_modes,
         test_verdict_follows_the_numbers_both_ways,
         test_book_numbers_come_from_the_artifact]

CONTROLS = [("загрузка по доле сделок", _control_load_by_trade_share),
            ("окно у каждого режима своё", _control_window_per_mode),
            ("вердикт печатается всегда", _control_verdict_always_printed),
            ("свод книги пересчитан на месте", _control_book_recomputed_here)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
