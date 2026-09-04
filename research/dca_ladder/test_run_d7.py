#!/usr/bin/env python3
"""Проверки замера срока D7. Главная — усечение равно прямой симуляции."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import ladder as L                                            # noqa: E402
import run_d6 as D6                                           # noqa: E402
import run_d7 as D7                                           # noqa: E402

M = 60
H = 3600
T0 = 1_700_000_000                      # ровно на границе часа


def _bars(path, t0=T0):
    """Минутные бары из ряда цен: (t, o, h, l, c, v)."""
    out = []
    for i, p in enumerate(path):
        prev = path[i - 1] if i else p
        out.append((t0 + i * M, prev, max(prev, p), min(prev, p), p, 1.0))
    return out


def _walk(n, f):
    return [f(i) for i in range(n)]


def _rec(bars, holds, at=T0, take=None, rungs=None, lev=3.0):
    """Запись, как её строит `one_position`: исход, трек и контрольные
    точки. Фикстура повторяет сборку записи, а не расчёт."""
    rp = rungs or [bars[0][4], bars[0][4] * 0.97, bars[0][4] * 0.94]
    w = [1.0 / len(rp)] * len(rp)
    r = L.simulate_dca(bars, rp, w, 1.0, lev, 0.02, take_px=take,
                       floor_frac=0.10, track=True,
                       checkpoints=[at + h * H for h in holds])
    marks, prev = [], 0.0
    for (hr, _c, pnl) in r["track"]:
        marks.append((hr, pnl - prev))
        prev = pnl
    return {"at": float(at), "exit_ts": float(r["exit_ts"]),
            "pnl": float(r["pnl_frac"]), "lev": lev, "fwd": 100.0,
            "sym": "AAAUSDT", "exit": r["exit"], "marks": marks,
            "ckpt": r["ckpt"], "end_ts": float(bars[-1][0])}, rp, w


def test_truncation_equals_direct_simulation():
    """Усечение обязано дать ТО ЖЕ, что прямая симуляция с этим сроком.

    Это и есть право считать все сроки одним проходом: пересчёт, дающий
    другие числа, был бы другой мерой, а не экономией. Путь построен так,
    чтобы сроки различались по существу: цена сперва проваливается (идут
    доливы), потом растёт и берёт тейк далеко за первыми сутками.
    """
    holds = [24, 48, 72]
    n = 80 * 60                          # 80 часов минутных баров
    path = _walk(n, lambda i: (100.0 * (1 - 0.06 * min(i, 600) / 600.0)
                               + 0.02 * max(0, i - 600) / 60.0))
    bars = _bars(path)
    take = 100.5
    rec, rp, w = _rec(bars, holds, take=take)
    for i, h in enumerate(holds):
        cut = [b for b in bars if b[0] <= T0 + h * H]
        direct = L.simulate_dca(cut, rp, w, 1.0, 3.0, 0.02, take_px=take,
                                floor_frac=0.10)
        got = D7.truncate(rec, h, i)
        assert got is not None, h
        assert got["exit"] == direct["exit"], (h, got["exit"],
                                               direct["exit"])
        assert abs(got["pnl"] - direct["pnl_frac"]) < 1e-12, (
            h, got["pnl"], direct["pnl_frac"])
        assert int(got["exit_ts"]) == int(direct["exit_ts"]), (
            h, got["exit_ts"], direct["exit_ts"])
    print("ok  усечение = прямая симуляция на всех сроках сетки "
          f"({', '.join(str(h) + ' ч' for h in holds)})")


def test_marks_sum_to_the_truncated_outcome():
    """Сумма почасовых приращений обязана равняться исходу сделки.

    Касса складывает именно их: разойдись сумма с pnl, кривая книги
    считала бы движение ПОСЛЕ выхода, и просадка срока была бы чужой.
    """
    holds = [24, 48]
    n = 60 * 60
    path = _walk(n, lambda i: 100.0 - 3.0 * i / n)
    rec, _rp, _w = _rec(_bars(path), holds)
    for i, h in enumerate(holds):
        got = D7.truncate(rec, h, i)
        s = sum(d for (_hr, d) in got["marks"])
        assert abs(s - got["pnl"]) < 1e-12, (h, s, got["pnl"])
        assert all(hr <= got["exit_ts"] for (hr, _d) in got["marks"]), h
    print("ok  приращения обрезаны и сходятся с исходом сделки")


def test_sample_is_common_to_all_holds():
    """Запись, не дожившая до самого длинного срока, выбрасывается ЦЕЛИКОМ.

    Иначе длинные сроки судились бы по обрезанным сделкам, а короткие по
    полным, и таблица сравнивала бы разные выборки.
    """
    holds = [24, 48, 72]
    long_path = _walk(80 * 60, lambda i: 100.0 - 2.0 * i / (80 * 60))
    short_path = _walk(30 * 60, lambda i: 100.0 - 2.0 * i / (30 * 60))
    full, _rp, _w = _rec(_bars(long_path), holds)
    part, _rp2, _w2 = _rec(_bars(short_path), holds)
    keep, lost = D7.common_sample([full, part], holds, log=lambda *_: None)
    assert lost == 1 and len(keep) == 1, (lost, len(keep))
    assert keep[0] is full
    # у короткой записи ранние сроки МЕРЯЮТСЯ, и всё равно она выброшена
    assert D7.truncate(part, 24, 0) is not None
    assert D7.truncate(part, 72, 2) is None
    print("ok  выборка общая: короткая запись выброшена, хотя первые "
          "сроки у неё измеримы")


def test_shorter_hold_frees_the_name_and_the_slot():
    """Срок меняет не только исход, но и ОБОРОТ: имя и место освобождаются.

    Правило одной на имя пересобирается на каждом сроке — иначе замер
    сравнивал бы сроки при обороте одного из них.
    """
    holds = [24, 72]
    n = 80 * 60
    path = _walk(n, lambda i: 100.0 - 1.0 * i / n)
    r1, _a, _b = _rec(_bars(path), holds, at=T0)
    r2, _c, _d = _rec(_bars(path, t0=T0 + 30 * H), holds, at=T0 + 30 * H)
    recs = [r1, r2]
    short = [D7.truncate(r, 24, 0) for r in recs]
    long_ = [D7.truncate(r, 72, 1) for r in recs]
    ks, _ = D6.one_per_name(short)
    kl, _ = D6.one_per_name(long_)
    assert len(ks) == 2, ks               # первая закрылась за сутки
    assert len(kl) == 1, kl               # держит имя третьи сутки
    print("ok  короткий срок освобождает имя: 2 сделки против 1")


def test_grid_is_declared_and_holds_the_reference():
    """Сетка объявлена до прогона и содержит нынешнее правило книги."""
    assert D7.HOLDS_H == [24, 48, 72, 120, 168], D7.HOLDS_H
    assert D7.REF_H in D7.HOLDS_H, D7.REF_H
    assert D7.REF_H == 72, D7.REF_H
    txt = D7.report({"holds_h": D7.HOLDS_H, "ref_h": D7.REF_H,
                     "deposits": [1000.0], "sample": 10,
                     "lost_short_record": 2, "cells": {}})
    assert "ошибка R5" in txt and "по ФОРМЕ" in txt, txt[:400]
    assert "←" in txt or "не победителя" in txt, txt[:400]
    print("ok  сетка объявлена, точка отсчёта помечена, вердикт по форме")


def _control_truncate_ignores_checkpoint():
    """Усечение берёт исход полной сделки вместо переоценки на границе."""
    orig = D7.truncate
    D7.truncate = lambda r, h, i: dict(r)
    try:
        try:
            test_truncation_equals_direct_simulation()
        except AssertionError:
            return True
        return False
    finally:
        D7.truncate = orig


def _control_marks_not_fixed():
    """Приращения обрезаны, но не поправлены: сумма разойдётся с исходом."""
    orig = D7.truncate

    def bad(r, h, i):
        lim = float(r["at"]) + float(h) * H
        if float(r["exit_ts"]) <= lim:
            return dict(r)
        ck = (r.get("ckpt") or [None] * (i + 1))[i]
        if not ck:
            return None
        _t, t_bar, pnl = ck
        hr = int(t_bar) - int(t_bar) % H
        return dict(r, exit="срок", exit_ts=float(t_bar), pnl=float(pnl),
                    marks=[(h2, d) for (h2, d) in r["marks"] if h2 <= hr])

    D7.truncate = bad
    try:
        try:
            test_marks_sum_to_the_truncated_outcome()
        except AssertionError:
            return True
        return False
    finally:
        D7.truncate = orig


def _control_sample_not_common():
    """Выборка не общая: короткая запись остаётся на коротких сроках."""
    orig = D7.common_sample
    D7.common_sample = lambda recs, holds, log=print: (list(recs), 0)
    try:
        try:
            test_sample_is_common_to_all_holds()
        except AssertionError:
            return True
        return False
    finally:
        D7.common_sample = orig


TESTS = [test_truncation_equals_direct_simulation,
         test_marks_sum_to_the_truncated_outcome,
         test_sample_is_common_to_all_holds,
         test_shorter_hold_frees_the_name_and_the_slot,
         test_grid_is_declared_and_holds_the_reference]

CONTROLS = [("усечение игнорирует контрольную точку",
             _control_truncate_ignores_checkpoint),
            ("приращения не поправлены", _control_marks_not_fixed),
            ("выборка не общая", _control_sample_not_common)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
