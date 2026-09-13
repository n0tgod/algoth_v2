#!/usr/bin/env python3
"""Проверки замера «дорога сделки» коротких книг.

Кусаются: путь строится из отметок ядра (час без бара наследует прошлую
отметку, последняя равна исходу); волна — средний ход прокси-имён, β до
входа восстанавливает подсаженную связь и молчит при нехватке часов; ось
срабатывает СТРОГО до фактического выхода, стоп по времени — только «не
в плюсе», запись после выхода согласована (pnl = отметка, срез отметок,
издержки те же); контроль выбирает сделки, ОТКРЫТЫЕ в назначенный час,
столько же, без повторов, воспроизводимо; калибровка анатомии —
подсаженное отделение хвоста видно, шум даёт базовую долю; отчёт
называет оговорку часа и не печатает None.
"""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import path_screen as P                                       # noqa: E402
import test_tail_screen as TT                                 # noqa: E402

AT = TT.AT
H = 3600.0


def _rec(sym="AAAUSDT", at=AT, marks=None, pnl=None, lev=20.0, exit="срок",
         entry_px=100.0):
    marks = marks if marks is not None else [(at + i * H, d)
                                             for i, d in enumerate((0.1, -0.2, -0.3))]
    final = sum(d for _h, d in marks)
    return {"sym": sym, "at": at, "exit_ts": at + len(marks) * H, "side": "short",
            "lev": lev, "pnl": final if pnl is None else pnl,
            "pnl_net": (final if pnl is None else pnl) - 0.01,
            "exit": exit, "marks": marks, "entry_px": entry_px, "state": "closed",
            "fwd": 40.0, "rr": 1.0}


def test_path_from_core_marks_with_gaps():
    # часы 1, 2, 4 (третьего бара не было): третий наследует второй
    marks = [(AT, 0.10), (AT + H, -0.30), (AT + 3 * H, -0.50)]
    p = P.path_of(_rec(marks=marks))
    assert p["K"] == 4 and p["cum"][1] == 0.10, p
    assert abs(p["cum"][2] + 0.20) < 1e-12 and p["cum"][3] == p["cum"][2], p
    assert abs(p["cum"][4] + 0.70) < 1e-12 and abs(p["final"] + 0.70) < 1e-12
    assert p["peak"] == 0.10
    assert P.path_of(_rec(marks=[])) is None
    print("ok  путь: отметки ядра → pnl по часам, дыра наследует прошлую "
          f"отметку, пик {p['peak']:+.2f}, исход {p['final']:+.2f}")


def test_wave_and_beta_recover_the_planted_link():
    td = tempfile.mkdtemp()
    rnd = np.random.default_rng(5)
    n = 80                                   # часов записи до входа
    start = AT - n * H
    wave_ret = rnd.normal(0, 0.01, n)        # доходность волны за час
    proxies = list(P.PROXY[:6])
    for j, sym in enumerate(proxies):
        px = 100.0 * np.cumprod(1 + wave_ret + rnd.normal(0, 1e-4, n))
        TT._write_hours(td, sym, start, n, lambda i, px=px: {"mid_close": float(px[i])})
    own = 50.0 * np.cumprod(1 + 2.0 * wave_ret + rnd.normal(0, 1e-4, n))
    TT._write_hours(td, "OWNUSDT", start, n, lambda i: {"mid_close": float(own[i])})
    mkt = P.Market(P.__dict__["T"].Hours(root=td), proxies=proxies, min_proxy=5)
    # волна за последний час — средний ход прокси
    w = mkt.wave(AT - 1 - H, AT - 1)
    want = float(np.mean([mkt.move(p, AT - 1 - H, AT - 1) for p in proxies]))
    assert w is not None and abs(w - want) < 1e-12, (w, want)
    b, rho, k = mkt.beta_pre("OWNUSDT", AT)
    assert k >= P.BETA_MIN and abs(b - 2.0) < 0.1 and rho > 0.95, (b, rho, k)
    # мало часов — β не измерена, число часов названо
    b2, rho2, k2 = mkt.beta_pre("OWNUSDT", AT, n=30, min_n=P.BETA_MIN)
    assert b2 is None and rho2 is None and k2 == 30, (b2, k2)
    # меньше MIN_PROXY цен — волны нет, и это посчитано
    assert mkt.wave(AT + 400 * H, AT + 401 * H) is None and mkt.wave_none == 1
    print(f"ok  рынок: волна = средний ход {len(proxies)} прокси, β до входа "
          f"{b:.2f} при подсаженной 2.0 (ρ {rho:.2f}, часов {k}); мало часов — "
          "не измерена")


def test_axes_fire_strictly_before_the_real_exit_and_records_stay_consistent():
    marks = [(AT + i * H, d) for i, d in enumerate((0.05, -0.20, -0.15, 0.10, -0.30, -0.6))]
    rec = _rec(marks=marks, exit="пол", lev=20.0)
    v = {"path": P.path_of(rec), "wave": {1: 0.002, 2: 0.011, 3: 0.03},
         "resid": {1: None, 2: 0.04, 3: 0.06}, "tail": True, "rec": rec}
    cum = v["path"]["cum"]           # 0.05, −0.15, −0.30, −0.20, −0.50, −1.10
    assert P.trigger(v, "loss", 0.25) == 3, cum
    assert P.trigger(v, "loss", 0.50) == 5
    assert P.trigger(v, "loss", 1.0) is None          # только на последнем часе — не считается
    assert P.trigger(v, "take", 0.04) == 1 and P.trigger(v, "take", 0.5) is None
    assert P.trigger(v, "time", 4) == 4               # к часу 4 не в плюсе
    v_plus = dict(v, path=P.path_of(_rec(marks=[(AT + i * H, d) for i, d in
                                                 enumerate((0.2, 0.1, 0.1, 0.1, -1.0))])))
    assert P.trigger(v_plus, "time", 4) is None       # в плюсе — стоп по времени молчит
    assert P.trigger(v, "wave", 1.0) == 2 and P.trigger(v, "wave", 5.0) is None
    assert P.trigger(v, "resid", 5.0) == 3
    new = P.exit_at(rec, 3)
    assert abs(new["pnl"] - cum[3]) < 1e-12 and new["exit"] == "правило выхода"
    assert abs(sum(d for _h, d in new["marks"]) - new["pnl"]) < 1e-12
    assert len(new["marks"]) == 3 and new["exit_ts"] == AT + 3 * H - 1
    assert abs((rec["pnl"] - rec["pnl_net"]) - (new["pnl"] - new["pnl_net"])) < 1e-12
    assert abs(new["exit_px"] - 100.0 * (1 + 0.30 / 20.0)) < 1e-9   # шорт в минусе: цена выше
    cache = {("safe_s", "AAAUSDT", AT): rec}
    mod, changed = P.apply_axis(cache, {("safe_s", "AAAUSDT", AT): v}, "loss", 0.25)
    assert changed == {("safe_s", "AAAUSDT", AT): 3} and mod[("safe_s", "AAAUSDT", AT)]["pnl"] == new["pnl"]
    d = P.deltas(cache, {("safe_s", "AAAUSDT", AT): v}, changed)
    assert abs(d["sum"] - (cum[3] - rec["pnl"])) < 1e-12 and d["tails"] == 1 and d["cut_worse"] == 0
    print(f"ok  оси: стоп −25 % сработал на часе 3 (pnl {cum[3]:+.2f}), стоп по "
          "времени молчит в плюсе, срабатывание на последнем часе не считается; "
          f"запись согласована (срез отметок, Σ маржи {d['sum']:+.2f})")


def test_control_picks_trades_open_at_the_assigned_hour_without_repeats():
    views, cache = {}, {}
    for i in range(30):
        K = 3 + (i % 6)                      # сроки 3…8 часов
        marks = [(AT + j * H, -0.05) for j in range(K)]
        rec = _rec(sym=f"S{i}USDT", marks=marks)
        key = ("safe_s", rec["sym"], AT)
        cache[key] = rec
        views[key] = {"path": P.path_of(rec), "tail": False, "rec": rec,
                      "wave": {}, "resid": {}}
    changed = {("safe_s", "S0USDT", AT): 2, ("safe_s", "S1USDT", AT): 5,
               ("safe_s", "S2USDT", AT): 7}
    seen = []

    def _stats(packed, ctx, launch, keys, deps=None, now=None):
        seen.append(packed)
        return {}

    was = P.AG.stats_of
    P.AG.stats_of = _stats
    try:
        out = P.control_exits(cache, views, changed, None, {}, seeds=3,
                              log=lambda *a: None)
        out2 = P.control_exits(cache, views, changed, None, {}, seeds=3,
                               log=lambda *a: None)
    finally:
        P.AG.stats_of = was
    assert len(seen) == 6 and out["no_cand"] == 0
    for packed in seen[:3]:
        recs = [r for rs in packed.values() for r in rs]
        picked = [r for r in recs if r["exit"] == "случайный выход"]
        # столько же, без повторов, и каждая была ОТКРЫТА после назначенного часа
        names = [r["sym"] for r in picked]
        assert len(set(names)) >= 3, names
        for r in picked:
            k = len(r["marks"])
            orig = cache[("safe_s", r["sym"], AT)]
            assert len(orig["marks"]) > k, (r["sym"], k, len(orig["marks"]))
            assert k in (2, 5, 7)
    assert out["sum"] == out2["sum"]         # зёрна воспроизводимы
    print("ok  контроль: случайные выходы — столько же, в те же часы, только "
          "среди открытых в тот час, без повторов, воспроизводимо")


def test_anatomy_calibration_planted_separation_found_noise_silent():
    rnd = np.random.default_rng(9)

    def _views(planted):
        vs = []
        for i in range(400):
            tail = i < 60
            if planted:
                step = -0.12 if tail else 0.02
            else:
                step = float(rnd.choice([-0.12, 0.02]))
            marks = [(AT + j * H, step) for j in range(8)]
            marks[-1] = (marks[-1][0], -2.0 if tail else 0.1)
            rec = _rec(sym=f"S{i}USDT", marks=marks, exit="пол" if tail else "срок")
            vs.append({"path": P.path_of(rec), "tail": tail, "rec": rec,
                       "wave": {}, "resid": {}})
        return vs
    a = {r["k"]: r for r in P.anatomy(_views(True))}[4]
    assert a["tail_under"] == 1.0 and a["tail_above"] == 0.0, a
    assert a["deep_tail"] == 1.0 and a["deep_rest"] == 0.0, a
    b = {r["k"]: r for r in P.anatomy(_views(False))}[4]
    assert abs(b["tail_under"] - 0.15) < 0.08 and abs(b["tail_above"] - 0.15) < 0.08, b
    pk = P.peaks(_views(True))
    assert pk["peak_tail"][0] == 0.0 and pk["peak_rest"][0] == 1.0, pk
    print(f"ok  калибровка анатомии: подсаженное отделение видно (хвост среди "
          f"глубоких {a['tail_under']:.0%}, выше — {a['tail_above']:.0%}), шум даёт "
          f"базовую долю ({b['tail_under']:.0%} / {b['tail_above']:.0%})")


def test_report_names_the_hour_caveat_the_control_and_prints_no_none():
    rul = {"ruler": "safe_s", "title": "безопасная", "n": 100, "n_tail": 10,
           "n_high": 40,
           "anatomy": [{"k": 4, "n": 80, "n_tail": 9, "tail_share": 0.1125,
                        "med_tail": -0.31, "med_rest": 0.02, "deep_tail": 0.6,
                        "deep_rest": 0.05, "n_under": 9, "tail_under": 0.66,
                        "tail_above": 0.04, "wave_tail": 0.012, "wave_rest": 0.001,
                        "resid_tail": 0.05, "resid_rest": None},
                       {"k": 18, "n": 0}],
           "peaks": {"n_tail": 10, "n_rest": 90, "peak_tail": [0.3, 0.1, 0.0],
                     "peak_rest": [0.8, 0.5, 0.2], "med_peak_tail": 0.04,
                     "med_peak_rest": 0.2,
                     "exit_k": {"q25": 6.0, "q50": 9.0, "q75": 14.0}},
           "market": [{"key": "beta", "title": "β к волне за 72 ч до входа",
                       "src": "рынок", "n": 100, "missing": 0, "distinct": 100,
                       "tail_share": 0.1, "med_tail": 1.5, "med_rest": 1.0,
                       "spread": 0.12, "shares": [0.05, 0.1, 0.1, 0.1, 0.17],
                       "perm": 0.0}],
           "market_high": [{"key": "rho", "title": "корреляция", "src": "рынок",
                            "n": 3, "missing": 37, "why": "сделок с признаком мало"}]}
    dep = P.MAIN_DEP
    s = {"rulers": [rul], "dep": dep, "books": ["safe_h"], "seeds": 2, "perms": 2,
         "base": {f"safe_h:{dep}": {"final": 0.107, "max_dd": -0.155, "n": 634}},
         "axes": [{"axis": "loss", "title": "стоп по убытку", "cells": [
             {"val": 0.25, "delta": {"sum": 12.3, "n": 40, "tails": 30, "cut_worse": 5},
              "stats": {f"safe_h:{dep}": {"final": 0.12, "max_dd": -0.10}},
              "control": {"sum": [1.0, 2.0], "books": {}, "tails": [1, 2], "no_cand": 0},
              "beat": {"safe_h": {"final": 0.5, "ratio": None}, "sum": 0.0}},
             {"val": 0.5, "delta": {"sum": 0.0, "n": 0, "tails": 0, "cut_worse": 0}}]}],
         "k_list": [4, 18], "peaks": [0.1, 0.25, 0.5], "deep": 0.25, "beta_h": 72,
         "proxies": 20, "diag": {"n": 100, "no_marks": 0, "mismatch": 0, "beta": 95,
                                 "wave_none": 3, "hours": {"есть сводка": 1, "нет сводки": 0}},
         "computed_at": "2026-09-13 01:00", "secs": 12.0}
    txt = P.report(s)
    assert "на границе часа" in txt and "случайные выходы" in txt, txt[:600]
    assert "+12.30 / +1.50" in txt and "66.0 % (9)" in txt, txt
    assert "не сработало ни разу" in txt and "медиана 9 (четверти 6–14)" in txt, txt
    assert "None" not in txt, [x for x in txt.splitlines() if "None" in x]
    bad = P.report({"error": "кэш реплея непригоден"})
    assert "Не посчитано" in bad
    print("ok  отчёт: оговорка границы часа, контроль случайными выходами, "
          "обе ветки ячейки, прочерк вместо None")


if __name__ == "__main__":
    for t in (test_path_from_core_marks_with_gaps,
              test_wave_and_beta_recover_the_planted_link,
              test_axes_fire_strictly_before_the_real_exit_and_records_stay_consistent,
              test_control_picks_trades_open_at_the_assigned_hour_without_repeats,
              test_anatomy_calibration_planted_separation_found_noise_silent,
              test_report_names_the_hour_caveat_the_control_and_prints_no_none):
        t()
    print("\nвсе 6 проверок прошли")
