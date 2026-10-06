#!/usr/bin/env python3
"""Проверки разложения разрыва издержек: полосы, стыковка строк с записями,
тождество цепочки, вес долларами против равного, издержки как Σ/Σ нотионала,
отчёт без пустот; контроль — подделка веса кусается."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cost_gap as CG                                         # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _rec(sym, at, lev, pnl, flat=0.0011, hours=12):
    r = TP._rec(sym=sym, at=at, lev=lev, pnl=pnl)
    r["pnl_net"] = pnl - flat * lev      # плоские 11 б.п. нотионала × плечо
    r["exit_ts"] = at + hours * H
    return r


def _row(rec, margin, fee_bp=5.5, slip_bp=4.4, fund_bp=None, ruler="optimal_h"):
    notl = margin * rec["lev"]
    return {"dep": 10000, "ruler": ruler, "at": rec["at"], "sym": rec["sym"],
            "lev": rec["lev"], "margin": margin,
            "usd_gross": rec["pnl"] * margin, "usd": None,
            "fee_usd": notl * fee_bp / 1e4, "slip_usd": notl * slip_bp / 1e4,
            "fund_usd": (None if fund_bp is None else notl * fund_bp / 1e4),
            "exit": "срок", "exit_ts": rec["exit_ts"]}


def test_bands():
    assert [CG.band_of(x) for x in (1, 3, 3.01, 6, 8, 10, 12, 15, 24.9)] == \
        ["≤3×", "≤3×", "3–6×", "3–6×", "6–10×", "6–10×", "10–15×", "10–15×", "15–25×"]


def test_join_matches_by_name_and_moment():
    a = _rec("AAAUSDT", AT, 10.0, 0.05)
    b = _rec("BBBUSDT", AT + H, 20.0, -0.02)
    rows = [_row(a, 100.0), _row(b, 50.0), dict(_row(a, 1.0), at=AT + 7)]
    pairs, lost = CG.join(rows, [a, b])
    assert len(pairs) == 2 and lost == 1
    assert pairs[0][1] is a and pairs[1][1] is b


def test_chain_identity_and_axes():
    # четыре записи, касса берёт две; плечи и билеты разные
    recs = [_rec("A", AT, 10.0, 0.10), _rec("B", AT + H, 20.0, -0.10),
            _rec("C", AT + 2 * H, 5.0, 0.03), _rec("D", AT + 3 * H, 20.0, 0.30)]
    rows = [_row(recs[0], 100.0, fund_bp=-2.0), _row(recs[3], 400.0, fund_bp=1.0)]
    c = CG.chain(recs, rows, "optimal_h")
    assert c["n_records"] == 4 and c["n_taken"] == 2 and c["lost"] == 0
    # S0: равный вес по всем четырём, в цене
    s0 = sum(r["pnl_net"] / r["lev"] for r in recs) / 4 * 1e4
    assert abs(c["S0"] - s0) < 1e-9, (c["S0"], s0)
    # S1: только взятые, равный вес
    s1 = sum(recs[i]["pnl_net"] / recs[i]["lev"] for i in (0, 3)) / 2 * 1e4
    assert abs(c["S1"] - s1) < 1e-9
    # S2: доллары: Σ pnl_net·margin / Σ margin·lev
    notl = 100.0 * 10 + 400.0 * 20
    s2 = (recs[0]["pnl_net"] * 100 + recs[3]["pnl_net"] * 400) / notl * 1e4
    assert abs(c["S2"] - s2) < 1e-9
    # S3: брутто − комиссия − проскальзывание + funding, долларами
    gross = recs[0]["pnl"] * 100 + recs[3]["pnl"] * 400
    fee = notl * 5.5 / 1e4
    slip = notl * 4.4 / 1e4
    fund = (1000 * -2.0 + 8000 * 1.0) / 1e4
    s3 = (gross - fee - slip + fund) / notl * 1e4
    assert abs(c["S3"] - s3) < 1e-9
    # тождество цепочки
    assert abs((c["d_select"] + c["d_weight"] + c["d_costs"]) - (c["S3"] - c["S0"])) < 1e-9
    # издержки — ровно Σ/Σ нотионала
    assert abs(c["fee_bp"] - 5.5) < 1e-9 and abs(c["slip_bp"] - 4.4) < 1e-9
    assert abs(c["fund_bp"] - fund / notl * 1e4) < 1e-9 and abs(c["flat_bp"] - 11.0) < 1e-9
    # Δ издержки = плоские − (комиссия + проскальзывание − funding)
    assert abs(c["d_costs"] - (c["flat_bp"] - (c["fee_bp"] + c["slip_bp"] - c["fund_bp"]))) < 1e-9
    # полосы: записи по всей сетке, взятые — только там, где они есть
    assert c["bands"]["6–10×"]["n_records"] == 1 and c["bands"]["6–10×"]["n_taken"] == 1
    assert c["bands"]["15–25×"]["n_records"] == 2 and c["bands"]["15–25×"]["n_taken"] == 1
    assert c["bands"]["3–6×"]["n_taken"] == 0 and "S3" not in c["bands"]["3–6×"]
    assert abs(sum(b.get("share_notional", 0) for b in c["bands"].values()) - 1.0) < 1e-9


def test_weighting_axis_is_real():
    # равные нотионалы: S2 == S1 (вес ничего не меняет)
    recs = [_rec("A", AT, 10.0, 0.10), _rec("B", AT + H, 10.0, -0.06)]
    rows = [_row(recs[0], 100.0), _row(recs[1], 100.0)]
    c = CG.chain(recs, rows, "optimal_h")
    assert abs(c["d_weight"]) < 1e-9, c["d_weight"]
    # большая позиция у минусовой записи тянет S2 вниз
    rows2 = [_row(recs[0], 100.0), _row(recs[1], 300.0)]
    c2 = CG.chain(recs, rows2, "optimal_h")
    assert c2["d_weight"] < -1e-6, c2["d_weight"]
    # Контроль: подделка, считающая S2 равным весом, обязана скрыть ось.
    was = CG.chain

    def poisoned(recs_, rows_, book):
        out = was(recs_, rows_, book)
        out["S2"] = out["S1"]
        out["d_weight"] = 0.0
        return out
    assert abs(poisoned(recs, rows2, "optimal_h")["d_weight"]) < 1e-9     # подделка легла
    assert poisoned(recs, rows2, "optimal_h")["d_weight"] != c2["d_weight"]  # и кусается


def test_rows_without_costs_are_not_mixed_in():
    recs = [_rec("A", AT, 10.0, 0.10), _rec("B", AT + H, 10.0, 0.10)]
    r_ok = _row(recs[0], 100.0)
    r_raw = dict(_row(recs[1], 100.0), fee_usd=None, slip_usd=None)   # издержки не измерены
    c = CG.chain(recs, [r_ok, r_raw], "optimal_h")
    assert c["n_taken"] == 1 and c["n_rows_all"] == 2 and abs(c["cover"] - 0.5) < 1e-9


def test_verdict_names_largest_axis_and_report_has_no_holes():
    recs = [_rec("A", AT, 10.0, 0.10), _rec("B", AT + H, 20.0, -0.10),
            _rec("C", AT + 2 * H, 5.0, 0.03), _rec("D", AT + 3 * H, 20.0, 0.30)]
    rows = [_row(recs[0], 100.0, fund_bp=-2.0), _row(recs[3], 400.0, fund_bp=1.0)]
    c = CG.chain(recs, rows, "optimal_h")
    c["verdict"] = CG.verdict(c)
    axes = {"отбор кассой": c["d_select"], "вес долларами (плечо × билет)": c["d_weight"],
            "издержки против плоских 11 б.п.": c["d_costs"]}
    top = max(axes, key=lambda k: abs(axes[k]))
    assert top in c["verdict"], c["verdict"]
    s = {"dep": 10000, "books": ["optimal_h"], "chain": {"optimal_h": c},
         "bands": [b[2] for b in CG.BANDS], "steps": CG.STEPS,
         "diag": {"records": 4, "rows": 2}, "computed_at": "2026-10-06 08:00", "secs": 1.0}
    md = CG.report(s)
    assert "None" not in md and "nan" not in md and "| оптимальная |" in md
    assert "Δ отбор" in md and "15–25×" in md
    empty = CG.chain([], [], "optimal_h")
    assert CG.verdict(empty).startswith("касса не взяла")
    assert "None" not in CG.report(dict(s, chain={"optimal_h": dict(empty, verdict=CG.verdict(empty))}))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
