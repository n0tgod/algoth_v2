#!/usr/bin/env python3
"""Проверки замера «вторая ступень по повторному выбору» (ядро, общий пол):
повторы в срок позиции и склейка рук, нуль-перестановка хранит множество
задержек, политики ячеек, проскальзывание доливов, статистика позиций с
гейтом плеча книги, вердикт и отчёт без дыр, сквозной проход обеих дорог
(реплей ядра и касса) на подставных барах формы записи."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import short_rung as SR                                       # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0
AT = 1_700_000_000.0 + 1440 * 60


def _leg(sym, at, fwd=40.0, arm="nn"):
    g = T10._short_leg(at, sym=sym, fwd=fwd)
    g["arm"] = arm
    return g


def test_repeats_are_same_name_picks_within_the_term_and_arms_collapse():
    legs = [_leg("A", AT), _leg("A", AT, arm="gbm"), _leg("A", AT + H), _leg("A", AT + 2 * H),
            _leg("A", AT + 30 * H), _leg("B", AT + H)]
    reps = SR.repeats_of(legs)
    assert reps[SR.pkey("A", AT)] == [AT + H, AT + 2 * H], reps[SR.pkey("A", AT)]
    assert reps[SR.pkey("A", AT + H)] == [AT + 2 * H]
    assert reps[SR.pkey("A", AT + 30 * H)] == [] and reps[SR.pkey("B", AT + H)] == []
    assert len(reps) == 5                                     # две руки в секунду — одна позиция


def test_null_permutes_first_repeat_offsets_between_positions():
    legs = [_leg("A", AT), _leg("A", AT + H),                 # задержка 1 ч
            _leg("B", AT), _leg("B", AT + 3 * H),             # 3 ч
            _leg("C", AT), _leg("C", AT + 5 * H),             # 5 ч
            _leg("D", AT + 40 * H)]                           # без повтора
    reps = SR.repeats_of(legs)
    offs = sorted(v[0] - k[1] for k, v in reps.items() if v)
    assert offs == [H, 3 * H, 5 * H], offs
    seen = set()
    for seed in range(1, 7):
        nz = SR.null_offsets(reps, seed)
        assert set(nz) == {k for k, v in reps.items() if v}, nz
        assert sorted(t - k[1] for k, t in nz.items()) == offs, "множество задержек не сохранено"
        seen.add(tuple(sorted((k, t) for k, t in nz.items())))
    assert len(seen) > 1, "перестановка не меняет назначений"
    # политика нуля берёт чужую задержку, ячейки — свои повторы
    nulls = {"n01": SR.null_offsets(reps, 1)}
    pol = SR.policy("n01", SR.pkey("A", AT), reps, nulls)
    assert pol and pol["max"] == 1 and len(pol["adds"]) == 1 and pol["adds"][0][1] == SR.ADD_W
    assert SR.policy("n01", SR.pkey("D", AT + 40 * H), reps, nulls) is None


def test_cell_policies_follow_the_declared_axes():
    legs = [_leg("A", AT)] + [_leg("A", AT + i * H) for i in (1, 2, 3, 4, 5)]
    reps = SR.repeats_of(legs)
    key = SR.pkey("A", AT)
    assert SR.policy("ref", key, reps, {}) is None
    r2 = SR.policy("r2", key, reps, {})
    assert r2 == {"adds": [(AT + H, SR.ADD_W)], "max": 1}, r2
    r2p = SR.policy("r2p", key, reps, {})
    assert r2p["if_profit"] is True and r2p["max"] == 1 and len(r2p["adds"]) == 5
    r4 = SR.policy("r4", key, reps, {})
    assert r4["max"] == SR.MAX_ADDS == 3 and [t for t, _w in r4["adds"]] == [AT + H, AT + 2 * H, AT + 3 * H]
    assert SR.policy("r2", SR.pkey("A", AT + 5 * H), reps, {}) is None    # повторов нет — долива нет
    adds_of = SR.make_adds_of(reps, {})
    assert adds_of({"sym": "A", "at": AT}, SR.cell_key("r2")) == r2
    assert adds_of({"sym": "A", "at": AT}, SR.cell_key("ref")) is None
    keys = [c[0] for c in SR.cells_for(3)]
    assert keys[:4] == [SR.cell_key(n) for n in ("ref", "r2", "r2p", "r4")] and keys[4:] == [SR.cell_key(f"n0{i}") for i in (1, 2, 3)]
    assert all(c[1:] == S.CELL[1:] for c in SR.cells_for(3)), "геометрия ячеек — геометрия книги"


def test_slippage_of_adds_is_market_on_each_add_share():
    row = {"margin": 100.0, "lev": 4.0, "adds": 1,
           "fills": [[AT, 100.0, 0.25], [AT + H, 99.0, 0.25]]}
    assert abs(SR.slip_adds_usd(row) - 0.25 * 400.0 * CO.SLIP_BP / 1e4) < 1e-12
    assert SR.slip_adds_usd(dict(row, adds=0)) == 0.0
    assert SR.slip_adds_usd(dict(row, margin=None)) == 0.0
    two = dict(row, adds=2, fills=row["fills"] + [[AT + 2 * H, 98.0, 0.25]])
    assert abs(SR.slip_adds_usd(two) - 0.5 * 400.0 * CO.SLIP_BP / 1e4) < 1e-12
    # крюк кассы вычитает ровно это
    packed = {"optimal_h": [dict(T10._short_leg(AT), **{
        "at": AT, "exit_ts": AT + 6 * H, "pnl": 0.10, "pnl_net": 0.09, "lev": 6.0, "fwd": 40.0,
        "sym": "AAAUSDT", "side": "short", "exit": "срок", "state": "closed", "adds": 1,
        "marks": [(AT - AT % H + H, 0.10)], "end_ts": AT + 6 * H, "sched_end": AT + 24 * H,
        "entry_px": 100.0, "exit_px": 99.0, "fills": [[AT, 100.0, 0.25], [AT + H, 99.5, 0.25]]})]}
    a = G.cell_stats(packed, {"error": "рядов нет"}, {}, now=AT + 100 * H, keys=["optimal_h"], deps=[10000])
    b = G.cell_stats(packed, {"error": "рядов нет"}, {}, now=AT + 100 * H, keys=["optimal_h"], deps=[10000],
                     extra_usd=lambda r: 1.5)
    ua, ub = a["optimal_h:10000"]["usd"], b["optimal_h:10000"]["usd"]
    assert a["optimal_h:10000"]["n"] == 1 and abs((ua - ub) - 1.5) < 1e-6, (ua, ub)


def test_position_stats_use_the_book_gate_and_count_kills():
    rk = S.BOOKS["aggr_h"]
    ref = {(rk, "A", 1.0): {"pnl_net": 0.02, "exit": "срок", "lev": 6.0, "state": "closed"},
           (rk, "B", 2.0): {"pnl_net": -0.01, "exit": "срок", "lev": 6.0, "state": "closed"},
           (rk, "C", 3.0): {"pnl_net": 0.05, "exit": "тейк", "lev": 3.0, "state": "closed"}}   # плечо < 4 — вне агрессивной
    cell = {(rk, "A", 1.0): dict(ref[(rk, "A", 1.0)], pnl_net=0.05, adds=1),
            (rk, "B", 2.0): dict(ref[(rk, "B", 2.0)], pnl_net=-0.50, exit="пол", adds=1),
            (rk, "C", 3.0): dict(ref[(rk, "C", 3.0)], pnl_net=0.09, adds=1)}
    p = SR.position_stats(cell, ref, "aggr_h")
    assert p["positions"] == 2 and p["adds"] == 2 and p["killed"] == 1, p
    assert abs(p["mean"] - ((0.03 - 0.49) / 2)) < 1e-12 and p["pos_share"] == 0.5
    q = SR.position_stats(cell, ref, "optimal_h")
    assert q["positions"] == 3 and q["adds"] == 3 and q["killed"] == 1, q
    empty = SR.position_stats({k: dict(v, adds=0) for k, v in cell.items()}, ref, "optimal_h")
    assert empty["adds"] == 0 and empty["mean"] is None


def test_verdict_needs_better_than_book_and_every_null_seed():
    def cash(ref_r, main_r):
        return {"ref": {bk: {"final": 0.10, "max_dd": -0.10 / ref_r} for bk in SR.BOOK_KEYS},
                "r2": {bk: {"final": 0.12, "max_dd": -0.12 / main_r} for bk in SR.BOOK_KEYS}}
    nz_ok = {bk: {"ratio_med": 2.0, "beat_ratio": 0.0} for bk in SR.BOOK_KEYS}
    nz_no = {bk: {"ratio_med": 2.0, "beat_ratio": (0.1 if bk == "aggr_h" else 0.0)} for bk in SR.BOOK_KEYS}
    assert SR.verdict(cash(2.0, 3.0), nz_ok).startswith("РЫЧАГ")
    assert SR.verdict(cash(2.0, 3.0), nz_no).startswith("не рычаг"), "одно зерно не хуже — не рычаг"
    assert SR.verdict(cash(3.0, 2.5), nz_ok).startswith("не рычаг"), "хуже книги — не рычаг"
    worse_income = cash(2.0, 3.0)
    worse_income["r2"] = {bk: {"final": 0.08, "max_dd": -0.08 / 3.0} for bk in SR.BOOK_KEYS}
    assert SR.verdict(worse_income, nz_ok).startswith("не рычаг"), "отношение лучше, итог хуже — не рычаг"


def test_end_to_end_on_core_shaped_bars():
    """Обе дороги — реплей ядра с политиками и касса — на подставных барах:
    шорт-неудачник (рост к 24 ч) и шорт-победитель (дрейф вниз); у каждого
    повтор через час. Долив в неудачника вредит, в победителя помогает."""
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = [_leg("SSSUSDT", at), _leg("SSSUSDT", at + H), _leg("SSSUSDT", at + 2 * H),
            _leg("TTTUSDT", at), _leg("TTTUSDT", at + H)]
    reps = SR.repeats_of(legs)
    assert reps[SR.pkey("SSSUSDT", at)] == [at + H, at + 2 * H] and reps[SR.pkey("TTTUSDT", at)] == [at + H]
    nulls = {"n01": SR.null_offsets(reps, 1)}
    cells = SR.cells_for(1)
    got, _tail = T10._with_levels(lambda: S.replay_cells(
        legs, cells, src=src, log=lambda *a: None, adds_of=SR.make_adds_of(reps, nulls)))
    assert set(got) == {c[0] for c in cells}, sorted(got)
    ref, r2, r4 = got[SR.cell_key("ref")], got[SR.cell_key("r2")], got[SR.cell_key("r4")]
    assert ref and set(ref) == set(r2) == set(r4), (len(ref), len(r2), len(r4))
    rk = S.BOOKS["optimal_h"]
    assert all(int(r.get("adds") or 0) == 0 for r in ref.values())
    k_lose, k_win = (rk, "SSSUSDT", round(at, 3)), (rk, "TTTUSDT", round(at, 3))
    assert r2[k_lose]["adds"] == 1 and r2[k_win]["adds"] == 1, (r2[k_lose]["adds"], r2[k_win]["adds"])
    assert r4[k_lose]["adds"] == 2, r4[k_lose]["adds"]                    # два повтора — две ступени
    assert len(r2[k_lose]["fills"]) == 2 and r2[k_lose]["fills"][1][0] >= at + H
    assert r2[k_lose]["pnl_net"] < ref[k_lose]["pnl_net"], "долив в растущий шорт обязан вредить"
    assert r2[k_win]["pnl_net"] > ref[k_win]["pnl_net"], "долив в падающий шорт обязан помогать"
    # позиция без повтора — без долива во всех ячейках
    k_last = (rk, "SSSUSDT", round(at + 2 * H, 3))
    assert r2[k_last]["adds"] == 0 and r4[k_last]["adds"] == 0
    # сквозной прогон: касса, нуль, сверка, отчёт
    s = T10._with_levels(lambda: SR.run(legs_=legs, src=src, log=lambda *a: None, ctx={"error": "рядов нет"},
                                        launch={}, now=at + 400 * H, seeds=2, cache={}, mem_limit=10 ** 6))
    assert not s.get("error"), s.get("error")
    assert s["with_repeat"] == 3 and s["positions"] == 5 and s["ref_check"]["compared"] == 0
    for nm in ("ref", "r2", "r2p", "r4", "n01", "n02"):
        c = s["cash"][nm]["optimal_h"]
        assert c.get("n") and c.get("final") is not None, (nm, c)
    assert s["positions_stats"]["r2"]["optimal_h"]["adds"] >= 2
    assert s["verdict"].startswith(("РЫЧАГ", "не рычаг")), s["verdict"]
    md = SR.report(s)
    assert "None" not in md and "nan" not in md and "## Вердикт" in md, md[:600]
    # сверка с «кэшем»: подставим кэш из самой ячейки ref — расхождений ноль; подделка pnl — ловится
    fake = {k: dict(v) for k, v in ref.items()}
    assert SR.ref_check(ref, fake)["mismatch"] == 0
    bad_key = next(iter(fake))
    fake[bad_key]["pnl"] = float(fake[bad_key]["pnl"]) + 0.01
    chk = SR.ref_check(ref, fake)
    assert chk["mismatch"] == 1 and chk["sample"], chk


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
