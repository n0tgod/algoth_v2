#!/usr/bin/env python3
"""Проверки замера «потолок плеча у коротких книг».

Кусаются: масштаб записи линеен по плечу и трогает pnl, нетто, отметки и
контрольные точки, но не исход и не плечо забора; разметка отдаёт в реплей
только хвост с плечом выше потолка, открытые и низкоплечевые не трогает;
выборка на сверку воспроизводима; ноги — по одной на решение, без ноги
посчитано; сверка ловит расхождение масштаба с ядром; потолок ядра
ставится на время счёта и возвращается даже при ошибке; статистика сделки
считает долю плюсовых, RR и ожидание в двух единицах; гейт плеча книги
применяется к записям; сборка прогона с подставным ядром и кассой отдаёт
опору и обе ячейки; отчёт без None.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_levcap as V                                      # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _rec(sym, lev, exit, marks=None, at=AT, state="closed", pnl_net_gap=0.01):
    r = TP._rec(sym=sym, at=at, lev=lev, exit=exit,
                marks=marks if marks is not None else [(at, 0.1), (at + H, -0.3)])
    r["pnl_net"] = r["pnl"] - pnl_net_gap * lev
    r["state"] = state
    r["ckpt"] = [("c12", at + 12 * H, 0.05), ("c18", at + 18 * H, None)]
    return r


def test_scale_is_linear_and_keeps_outcome():
    r = _rec("AAAUSDT", 20.0, "срок")
    s = V.scale_record(r, 2.0)
    assert s["lev"] == 2.0 and s["lev_scaled_from"] == 20.0 and s["exit"] == "срок"
    assert abs(s["pnl"] - r["pnl"] / 10) < 1e-12 and abs(s["pnl_net"] - r["pnl_net"] / 10) < 1e-12
    assert [d for _h, d in s["marks"]] == [0.01, -0.03] or all(
        abs(a - b / 10) < 1e-12 for (_h, a), (_g, b) in zip(s["marks"], r["marks"]))
    assert abs(s["ckpt"][0][2] - 0.005) < 1e-12 and s["ckpt"][1][2] is None
    assert s["exit_ts"] == r["exit_ts"] and s["entry_px"] == r["entry_px"]
    print("ok  масштаб: pnl, нетто, отметки и точки ÷10 при 20× → 2×; исход, время и цена входа те же")


def test_plan_sends_only_high_leverage_tails_to_the_core():
    cache = {("safe_s", "A", AT): _rec("A", 20.0, "пол"),
             ("safe_s", "B", AT): _rec("B", 20.0, "срок"),
             ("safe_s", "C", AT): _rec("C", 1.5, "ликвидация"),         # плечо ниже потолка
             ("safe_s", "D", AT): _rec("D", 25.0, "ликвидация", state="open"),
             ("safe_s", "E", AT): _rec("E", 6.0, "тейк")}
    un, sc, rp = V.plan(cache, 2.0)
    assert set(k[1] for k in un) == {"C", "D"} and set(k[1] for k in sc) == {"B", "E"}
    assert set(k[1] for k in rp) == {"A"}
    un6, sc6, rp6 = V.plan(cache, 6.0)
    assert set(k[1] for k in un6) == {"C", "D", "E"} and set(k[1] for k in rp6) == {"A"}
    keys = list(sc)
    assert V.verify_keys(keys, n=1) == V.verify_keys(keys, n=1) and len(V.verify_keys(keys, n=5)) == 2
    legs_ = [{"sym": "A", "at": AT, "arm": "nn"}, {"sym": "A", "at": AT, "arm": "gbm"},
             {"sym": "B", "at": AT, "arm": "nn"}]
    need, missing = V.legs_for(list(rp) + list(sc), legs_)
    assert [g["sym"] for g in need] == ["A", "B"] and missing == 1          # E без ноги
    print("ok  разметка: в реплей только хвост с плечом выше потолка, открытые и низкоплечевые не трогаются; ноги по одной на решение")


def test_compare_flags_divergence_and_cap_is_restored():
    s = {("safe_s", "A", AT): _rec("A", 2.0, "срок")}
    same = {("safe_s", "A", AT): dict(s[("safe_s", "A", AT)])}
    assert V.compare(s, same) == {"n": 1, "bad": 0, "worst": 0.0}
    diff = {("safe_s", "A", AT): dict(s[("safe_s", "A", AT)], pnl=s[("safe_s", "A", AT)]["pnl"] + 1e-6)}
    got = V.compare(s, diff)
    assert got["bad"] == 1 and abs(got["worst"] - 1e-6) < 1e-12
    other = {("safe_s", "A", AT): dict(s[("safe_s", "A", AT)], exit="пол")}
    assert V.compare(s, other)["bad"] == 1
    was = V.D10.LEV_CAP.get("fence")
    seen = V.with_cap(6.0, lambda: V.D10.LEV_CAP["fence"])
    assert seen == 6.0 and V.D10.LEV_CAP.get("fence") == was
    try:
        V.with_cap(2.0, lambda: 1 / 0)
    except ZeroDivisionError:
        pass
    assert V.D10.LEV_CAP.get("fence") == was
    assert V.D10.leverage_for("fence", 25.0) == 25.0
    assert V.with_cap(2.0, lambda: V.D10.leverage_for("fence", 25.0)) == 2.0
    print("ok  сверка ловит расхождение 1e-6 и смену исхода; потолок ядра ставится на время счёта и возвращается")


def test_trade_stats_in_two_units_and_book_gate():
    pairs = [(0.10, 0.01), (0.30, 0.03), (-0.20, -0.02), (0.0, 0.0)]
    ts = V.trade_stats(pairs)
    assert ts["n"] == 4 and abs(ts["hit"] - 0.5) < 1e-12
    assert abs(ts["win_m"] - 0.2) < 1e-12 and abs(ts["loss_m"] + 0.1) < 1e-12 and abs(ts["rr"] - 2.0) < 1e-12
    assert abs(ts["exp_m"] - 0.05) < 1e-12 and abs(ts["exp_q"] - 0.005) < 1e-12
    assert V.trade_stats([]) is None
    recs = [_rec("A", 20.0, "срок"), _rec("B", 2.0, "срок"), _rec("C", 20.0, "срок", state="open")]
    pa = V.record_pairs(recs, "safe_h")
    assert len(pa) == 2 and abs(pa[0][1] - pa[0][0] / 20.0) < 1e-12
    assert len(V.record_pairs(recs, "aggr_h")) == 1                       # гейт ≥ 4× режет B
    rows = [{"margin": 100.0, "lev": 10.0, "usd": 5.0}, {"margin": 0.0, "lev": 10.0, "usd": 1.0}]
    rp = V.row_pairs(rows)
    assert rp == [(0.05, 0.005)]
    assert V.verdict({"exp_q": 0.01}, {"exp_q": 0.0095}) == "ожидание в цене держится"
    assert V.verdict({"exp_q": 0.01}, {"exp_q": -0.001}) == "ожидание в цене исчезло"
    assert V.verdict({"exp_q": 0.01}, {"exp_q": 0.005}) == "ожидание в цене -50 %"
    assert V.verdict({}, {"exp_q": 0.005}) == "не измерено"
    print("ok  статистика сделки: доля плюсовых 50 %, RR 2.0, ожидание в марже и в цене; гейт книги режет записи")


def test_run_wiring_with_stub_core_and_report_without_none():
    cache = {}
    for i in range(10):
        lev = 20.0 if i % 2 else 1.5
        exit = "пол" if i in (1, 3) else "срок"
        marks = [(AT + i * H + j * H, (0.05 if j % 3 else -0.1)) for j in range(6)]
        for rk in ("safe_s", "optimal_s"):
            cache[(rk, f"S{i}USDT", round(AT + i * H, 3))] = _rec(f"S{i}USDT", lev, exit, marks=marks,
                                                                  at=AT + i * H)
    legs_ = [{"sym": f"S{i}USDT", "at": AT + i * H, "arm": "nn", "fwd": -40.0, "fav": -40.0}
             for i in range(10)]
    days = [{"d": f"2026-09-{i + 1:02d}", "usd": float((-1) ** i * (40 + i))} for i in range(8)]
    replayed = []

    def _replay(need, src=None, log=print, ckpt_hours=None):
        replayed.append((V.D10.LEV_CAP.get("fence"), [g["sym"] for g in need]))
        out = {}
        for g in need:
            for rk in ("safe_s", "optimal_s"):
                old = cache[(rk, g["sym"], round(float(g["at"]), 3))]
                cap = V.D10.LEV_CAP["fence"]
                if old["exit"] == "пол":
                    out[(rk, g["sym"], round(float(g["at"]), 3))] = dict(old, lev=cap, exit="срок", pnl=0.02,
                                                                        pnl_net=0.015)
                else:
                    out[(rk, g["sym"], round(float(g["at"]), 3))] = V.scale_record(old, cap)
        return out, {}

    def _stats(packed, ctx, launch, keys, deps=None, now=None):
        return {f"{bk}:{int(deps[0])}": {"n": len(packed.get(bk) or []), "final": 0.05, "max_dd": -0.02,
                                         "usd": 500.0, "ratio": 2.5, "days": days, "exits": {}}
                for bk in keys}

    def _rows(packed, now=None, keys=None, log=None):
        rows = []
        for bk in keys:
            for r in (packed.get(bk) or []):
                rows.append(dict(r, ruler=bk, dep=10000, margin=100.0, usd=100.0 * float(r["pnl"])))
        return rows, {}, {}, {}

    saved = (V.S.read_cache, V.S.legs, V.S.replay, V.CO.context, V.IR.launches, V.AG.stats_of,
             V.RP.build_rows, V.RP.age_shorts, V.RP.guard_shorts)
    V.S.read_cache = lambda log=print: (cache, None)
    V.S.legs = lambda log=print: legs_
    V.S.replay = _replay
    V.CO.context = lambda: {"error": "рядов нет"}
    V.IR.launches = lambda: {}
    V.AG.stats_of = _stats
    V.RP.build_rows = _rows
    V.RP.age_shorts = lambda recs, bk, launch=None, log=None, now=None: (list(recs), {})
    V.RP.guard_shorts = lambda recs, bk, log=None, now=None: (list(recs), {})
    try:
        s = V.run(caps=(2.0, 6.0), log=lambda *a: None, mem_limit=10 ** 6, verify_n=1)
    finally:
        (V.S.read_cache, V.S.legs, V.S.replay, V.CO.context, V.IR.launches, V.AG.stats_of,
         V.RP.build_rows, V.RP.age_shorts, V.RP.guard_shorts) = saved
    assert not s.get("error") and set(s["cells"]) == {"base", "2", "6"}, s.get("error")
    assert V.D10.LEV_CAP.get("fence") is None
    assert [c for c, _n in replayed] == [2.0, 6.0]
    p2 = s["plans"]["2"]
    # 5 решений с плечом 20× на две линейки: 2 хвоста → реплей (4 записи), 3 срока → масштаб (6)
    assert p2["replayed"] == 4 and p2["scaled"] == 6 and p2["unchanged"] == 10 and p2["dropped"] == 0, p2
    assert p2["verify"]["n"] == 1 and p2["verify"]["bad"] == 0
    assert p2["was_exits"] == {"пол": 4} and p2["now_exits"] == {"срок": 4}
    b = s["cells"]["2"]["safe_h"]
    assert b["records"]["n"] == 10 and b["records_tails"] == 0 and b["records_tail_share"] == 0.0
    assert s["cells"]["base"]["safe_h"]["records_tails"] == 2
    assert s["cells"]["2"]["aggr_h"]["records"] is None                   # гейт ≥ 4× пуст при потолке 2×
    assert s["cells"]["6"]["aggr_h"]["records"]["n"] == 5
    txt = V.report(s)
    assert "None" not in txt, [ln for ln in txt.splitlines() if "None" in ln]
    assert "| потолок 2× |" in txt and "## Как собраны ячейки" in txt and "вывод |" in txt
    assert "Не посчитано" in V.report({"error": "кэша нет"})
    print("ok  сборка: опора и два потолка, хвост пересчитан ядром с потолком, остальное масштабом; отчёт без None")


if __name__ == "__main__":
    for t in (test_scale_is_linear_and_keeps_outcome,
              test_plan_sends_only_high_leverage_tails_to_the_core,
              test_compare_flags_divergence_and_cap_is_restored,
              test_trade_stats_in_two_units_and_book_gate,
              test_run_wiring_with_stub_core_and_report_without_none):
        t()
    print("\nвсе 5 проверок прошли")
