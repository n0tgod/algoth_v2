#!/usr/bin/env python3
"""Проверки скрина рычагов коротких книг.

Кусаются: срок закрывает только живую на этом часе позицию и СТРОГО до её
выхода; трейлинг взводится от порога и выходит на откате от пика, молчит без
взвода и на последнем часе; пауза по имени считает окно [выход, выход + h)
от СВОИХ выходов книги и различает пол и любой выход; рука берётся из ног
листа, запись без ноги не измерена; вол-таргет берёт σ прошлых дней без
заглядывания и обрезается; сборка прогона с подставными кассой и листом
отдаёт все пять осей; отчёт без None и с причиной отказа.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_levers as L                                      # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _view(marks, exit="срок"):
    rec = TP._rec(marks=marks, exit=exit)
    return rec, {"rec": rec, "path": L.WV.path_of(rec), "tail": L.T.is_tail(rec),
                 "wave": {}, "resid": {}}


def test_hold_closes_only_positions_alive_at_that_hour():
    rec, v = _view([(AT + i * H, -0.02) for i in range(24)])       # K = 24
    assert L.hold_trigger(v, 12) == 12 and L.hold_trigger(v, 18) == 18
    _r10, v10 = _view([(AT + i * H, -0.02) for i in range(10)])    # вышла на 10-м часе
    assert L.hold_trigger(v10, 12) is None
    _r12, v12 = _view([(AT + i * H, -0.02) for i in range(12)])    # вышла ровно на 12-м
    assert L.hold_trigger(v12, 12) is None                         # не строго до выхода
    assert L.hold_trigger({"path": None}, 12) is None
    key = ("safe_s", rec["sym"], AT)
    mod, changed = L.apply_rule({key: rec}, {key: v}, lambda x: L.hold_trigger(x, 12), why="срок 12 ч")
    assert changed == {key: 12}
    new = mod[key]
    assert abs(new["pnl"] - v["path"]["cum"][12]) < 1e-12 and new["exit"] == "срок 12 ч"
    assert len(new["marks"]) == 12 and new["exit_ts"] == AT + 12 * H - 1
    print(f"ok  срок: живая на 12-м часе закрыта на отметке ({new['pnl']:+.2f}), вышедшая раньше или ровно — нет")


def test_trail_arms_at_threshold_and_exits_on_giveback_from_peak():
    #           cum: 0.10 0.30 0.40 0.20 0.30 -0.50 -0.60
    rec, v = _view([(AT, 0.10), (AT + H, 0.20), (AT + 2 * H, 0.10), (AT + 3 * H, -0.20),
                    (AT + 4 * H, 0.10), (AT + 5 * H, -0.80), (AT + 6 * H, -0.10)])
    cum = v["path"]["cum"]
    assert abs(cum[3] - 0.40) < 1e-12 and abs(cum[4] - 0.20) < 1e-12, cum
    assert L.trail_trigger(v, 0.25, 0.15) == 4          # взвод на часе 2 (0.30), пик 0.40, откат до 0.20
    assert L.trail_trigger(v, 0.25, 0.25) == 6          # откат на 0.25 — только на часе 6 (−0.50 ≤ 0.15)
    assert L.trail_trigger(v, 0.50, 0.25) is None       # взвода не было (пик 0.40 < 0.50)
    # срабатывание лишь на последнем часе (сам выход) не считается
    _r, v2 = _view([(AT, 0.30), (AT + H, 0.10), (AT + 2 * H, -0.60)])
    assert L.trail_trigger(v2, 0.25, 0.15) is None
    assert L.trail_trigger({"path": None}, 0.25, 0.15) is None
    print("ok  трейлинг: взвод при +0.25, выход на откате 0.15 от пика — час 4; без взвода и на последнем часе молчит")


def test_cooldown_counts_the_window_from_own_exits_and_tells_floor_from_any():
    taken = [{"sym": "AAAUSDT", "exit": "пол", "exit_ts": AT},
             {"sym": "BBBUSDT", "exit": "срок", "exit_ts": AT},
             {"sym": "CCCUSDT", "exit": "ликвидация", "exit_ts": AT + 100 * H}]
    recs = [{"sym": "AAAUSDT", "at": AT - 1}, {"sym": "AAAUSDT", "at": AT},
            {"sym": "AAAUSDT", "at": AT + 6 * H - 1}, {"sym": "AAAUSDT", "at": AT + 6 * H},
            {"sym": "BBBUSDT", "at": AT + H}, {"sym": "CCCUSDT", "at": AT + H},
            {"sym": "DDDUSDT", "at": AT + H}]
    keep, dropped = L.cooldown(recs, taken, 6, "tail")
    assert dropped == 2 and [(r["sym"], r["at"]) for r in keep] == [
        ("AAAUSDT", AT - 1), ("AAAUSDT", AT + 6 * H), ("BBBUSDT", AT + H),
        ("CCCUSDT", AT + H), ("DDDUSDT", AT + H)], keep
    keep_any, dropped_any = L.cooldown(recs, taken, 6, "any")
    assert dropped_any == 3 and all(not (r["sym"] == "BBBUSDT") for r in keep_any)
    keep24, d24 = L.cooldown(recs, taken, 24, "tail")
    assert d24 == 3                                     # и AT + 6 ч попадает в сутки
    print("ok  пауза: окно [выход, выход + 6 ч) по своим выходам; «после пола» убирает 2, «после любого» 3; будущий выход не считается")


def test_arm_map_from_legs_and_unknown_is_not_measured():
    legs_ = [{"sym": "AAAUSDT", "at": AT, "arm": "nn"}, {"sym": "AAAUSDT", "at": AT, "arm": "gbm"},
             {"sym": "BBBUSDT", "at": AT, "arm": "nn"}, {"sym": "CCCUSDT", "at": AT + H}]
    m = L.arm_map(legs_)
    assert m[("AAAUSDT", round(AT, 3))] == {"nn", "gbm"} and m[("CCCUSDT", round(AT + H, 3))] == {"gbm"}
    recs = [{"sym": "AAAUSDT", "at": AT}, {"sym": "BBBUSDT", "at": AT},
            {"sym": "CCCUSDT", "at": AT + H}, {"sym": "ZZZUSDT", "at": AT}]
    nn, unk = L.arm_select(recs, m, "nn")
    assert [r["sym"] for r in nn] == ["AAAUSDT", "BBBUSDT"] and unk == 1
    gbm, _u = L.arm_select(recs, m, "gbm")
    assert [r["sym"] for r in gbm] == ["AAAUSDT", "CCCUSDT"]
    print("ok  рука: обе руки входят в обе ячейки, без руки в ноге — gbm, без ноги — не измерено (1)")


def test_vol_target_uses_past_sigma_only_and_clips():
    days = [{"d": f"2026-08-{i + 1:02d}", "usd": (100.0 if i % 2 else -100.0)} for i in range(20)]
    days += [{"d": f"2026-09-{i + 1:02d}", "usd": (400.0 if i % 2 else -400.0)} for i in range(20)]
    out, facs = L.vol_target(days, ref_days=20, clip=(0.5, 1.5))
    assert facs[:21] == [1.0] * 21, facs[:21]             # первые 20 и первый день после — σ прошлого та же
    assert abs(facs[-1] - 0.5) < 1e-12 and min(facs) == 0.5    # σ выросла вчетверо → 0.25, обрезано до 0.5
    assert abs(out[-1]["usd"] - days[-1]["usd"] * 0.5) < 1e-9 and out[20]["usd"] == days[20]["usd"]
    assert any(0.5 < f < 1.0 for f in facs[21:-1])        # переходное окно — промежуточные множители
    assert L.vol_target(days[:20]) == (None, None)
    low = [{"d": f"2026-08-{i + 1:02d}", "usd": (100.0 if i % 2 else -100.0)} for i in range(20)]
    low += [{"d": f"2026-09-{i + 1:02d}", "usd": (10.0 if i % 2 else -10.0)} for i in range(25)]
    _o, f2 = L.vol_target(low)
    assert max(f2) == 1.5                                 # тишина — множитель не выше 1.5
    print("ok  вол-таргет: множитель из σ прошлых 20 дней без заглядывания, обрезка 0.5…1.5")


def test_run_wiring_with_stub_cash_and_report_without_none():
    rec_keys = []
    cache = {}
    for i in range(12):
        marks = [(AT + i * H + j * H, (0.05 if j % 3 else -0.1)) for j in range(24 if i % 2 else 8)]
        for rk in ("safe_s", "optimal_s"):
            r = TP._rec(sym=f"S{i}USDT", at=AT + i * H, marks=marks, exit=("пол" if i % 5 == 0 else "срок"))
            cache[(rk, r["sym"], r["at"])] = r
            rec_keys.append((rk, r["sym"], r["at"]))
    days = [{"d": f"2026-09-{i + 1:02d}", "usd": float((-1) ** i * (50 + i))} for i in range(25)]

    def _stats(packed, ctx, launch, keys, deps=None, now=None):
        out = {}
        for bk in keys:
            n = len(packed.get(bk) or [])
            out[f"{bk}:{int(deps[0])}"] = {"n": n, "final": 0.01 * n, "max_dd": -0.02, "usd": 10.0 * n,
                                           "ratio": 0.5 * n, "days": days,
                                           "exits": {"пол": {"n": 1, "usd": -5.0}}}
        return out

    def _rows(packed, now=None, keys=None, log=None):
        rows = []
        for bk in keys:
            for r in (packed.get(bk) or [])[:3]:
                rows.append(dict(r, ruler=bk, dep=10000, usd=1.0))
        return rows, {}, {}, {}

    legs_ = [{"sym": f"S{i}USDT", "at": AT + i * H, "arm": ("nn" if i % 2 else "gbm")} for i in range(12)]
    saved = (L.S.read_cache, L.CO.context, L.IR.launches, L.AG.stats_of, L.RP.build_rows,
             L.RP.age_shorts, L.RP.guard_shorts)
    L.S.read_cache = lambda log=print: (cache, None)
    L.CO.context = lambda: {}
    L.IR.launches = lambda: {}
    L.AG.stats_of = _stats
    L.RP.build_rows = _rows
    L.RP.age_shorts = lambda recs, bk, launch=None, log=None, now=None: (list(recs), {})
    L.RP.guard_shorts = lambda recs, bk, log=None, now=None: (list(recs), {})
    try:
        s = L.run(seeds=2, log=lambda *a: None, legs_=legs_, mem_limit=10 ** 6)
    finally:
        (L.S.read_cache, L.CO.context, L.IR.launches, L.AG.stats_of, L.RP.build_rows,
         L.RP.age_shorts, L.RP.guard_shorts) = saved
    assert not s.get("error"), s
    assert [h["hours"] for h in s["hold"]] == [12, 18] and s["hold"][0]["delta"]["n"] == 12   # 6 имён × 2 линейки живы на 12-м
    assert len(s["trail"]) == 2 and len(s["cool"]) == 6 and len(s["arms"]) == 2
    assert s["diag"]["closed"] == 24 and s["diag"]["legs"] == 12
    for a in s["arms"]:
        for bk in L.BOOK_KEYS:
            assert a["books"][bk]["kept"] == 6 and a["books"][bk]["unknown"] == 0, a["books"][bk]
    c = s["cool"][0]["books"]["safe_h"]
    assert c["verdict"] in ("лучше случайной", "хуже случайной", "в шуме случайной", "не измерено")
    for bk in L.BOOK_KEYS:
        assert s["vol"][bk]["factors"]["n_scaled"] >= 1 and s["vol"][bk]["max_dd"] is not None
    txt = L.report(s)
    assert "None" not in txt, [ln for ln in txt.splitlines() if "None" in ln]
    for head in ("## A. Срок", "## B. Трейлинг", "## C. Пауза", "## D. Одна рука", "## E. Вол-таргет"):
        assert head in txt, head
    assert "Не посчитано" in L.report({"error": "кэша нет"})
    assert L.verdict_sel({"final": 0.0, "ratio": 0.05}) == "лучше случайной"
    assert L.verdict_sel({"final": 1.0, "ratio": 0.96}) == "хуже случайной"
    assert L.verdict_sel({"final": 0.3, "ratio": 0.0}) == "в шуме случайной"
    assert L.verdict_sel({}) == "не измерено"
    print(f"ok  сборка: пять осей на подставной кассе, срок 12 ч изменил {s['hold'][0]['delta']['n']} записей, отчёт без None")


if __name__ == "__main__":
    for t in (test_hold_closes_only_positions_alive_at_that_hour,
              test_trail_arms_at_threshold_and_exits_on_giveback_from_peak,
              test_cooldown_counts_the_window_from_own_exits_and_tells_floor_from_any,
              test_arm_map_from_legs_and_unknown_is_not_measured,
              test_vol_target_uses_past_sigma_only_and_clips,
              test_run_wiring_with_stub_cash_and_report_without_none):
        t()
    print("\nвсе 6 проверок прошли")
