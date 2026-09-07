#!/usr/bin/env python3
"""Проверки замера «почему у короткой книги просадка».

Кусаются: полоса плеча выбирается по объявленной сетке (сдвинь плечо —
сделка обязана переехать); концентрация видит подсаженный хвост и без
него книга становится другой; ликвидация считается своей строкой с
долей убытка; сетка билета при доле 1 воспроизводит саму пару, а при
меньшей доле уводит просадку туда, где её делает шорт.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import short_why as SW                                        # noqa: E402

H = 3600.0
T0 = 1786320000.0


def _row(sym, at, usd, lev=5.0, exit_="тейк", margin=222.0, hold_h=24.0,
         fund=None):
    r = {"dep": 10000, "ruler": "safe_h", "at": float(at),
         "exit_ts": float(at) + hold_h * H, "sym": sym, "side": "short",
         "lev": float(lev), "margin": float(margin),
         "pnl_frac": round(usd / margin, 6), "usd": float(usd),
         "exit": exit_, "written_at": float(at) + H, "rules": R.RULES}
    if fund is not None:
        r["fund_usd"] = float(fund)
    return r


def test_leverage_bands_are_the_declared_ones():
    rows = [_row("A", T0, 1.0, lev=2.0), _row("B", T0 + H, 1.0, lev=4.0),
            _row("C", T0 + 2 * H, -50.0, lev=25.0)]
    got = SW.by_lev(rows)
    assert got["<3×"]["n"] == 1 and got["3–5×"]["n"] == 1
    assert got["≥20×"]["n"] == 1 and got["≥20×"]["usd"] == -50.0, got
    assert got["5–10×"]["n"] == 0 and got["10–20×"]["n"] == 0
    # контроль: сдвинутое плечо обязано переехать в другую полосу
    rows[2]["lev"] = 6.0
    got2 = SW.by_lev(rows)
    assert got2["≥20×"]["n"] == 0 and got2["5–10×"]["n"] == 1, got2
    assert got2["5–10×"]["usd"] == -50.0
    print("ok  полоса плеча — по объявленной сетке, сдвиг плеча переносит "
          "сделку и её деньги")


def test_concentration_sees_the_planted_tail():
    rows = [_row(f"S{i}", T0 + i * 24 * H, 10.0) for i in range(20)]
    plain = SW.concentration(rows)
    assert plain["worst1"] == 10.0 and plain["usd"] == 200.0, plain
    # подсаженный хвост: одна сделка тянет книгу в минус
    rows.append(_row("BOOM", T0 + 21 * 24 * H, -900.0, lev=25.0,
                     exit_="ликвидация"))
    got = SW.concentration(rows)
    assert got["worst1"] == -900.0, got
    assert got["usd"] == -700.0 and got["usd_wo_worst5"] > 0, got
    assert got["dd"] is not None and got["dd_wo_worst5"] is not None
    assert got["dd_wo_worst5"] > got["dd"], (got["dd"], got["dd_wo_worst5"])
    assert got["worst_day"] == -900.0 and got["usd_wo_worst_day"] == 200.0, got
    print(f"ok  концентрация видит хвост: худшая {got['worst1']:+.0f} $, "
          f"без худших пяти {got['usd_wo_worst5']:+.0f} $, просадка "
          f"{100 * got['dd']:.1f} % против {100 * got['dd_wo_worst5']:.1f} %")


def test_liquidation_is_its_own_line_with_a_share_of_the_loss():
    rows = ([_row(f"S{i}", T0 + i * H, 10.0) for i in range(5)]
            + [_row("L1", T0 + 9 * H, -300.0, exit_="ликвидация"),
               _row("L2", T0 + 10 * H, -100.0, exit_="срок")])
    got = SW.by_exit(rows)
    assert set(got) == {"тейк", "ликвидация", "срок"}, got
    assert got["ликвидация"]["usd"] == -300.0
    assert abs(got["ликвидация"]["share_of_loss"] - 0.75) < 1e-9, got
    assert got["тейк"]["share_of_loss"] is None, got["тейк"]
    print(f"ok  ликвидация — своя строка: {got['ликвидация']['usd']:+.0f} $, "
          f"{100 * got['ликвидация']['share_of_loss']:.0f} % убытка книги")


def test_funding_top_names_the_payers():
    rows = [_row("A", T0, 5.0, fund=-0.5, margin=100.0),
            _row("B", T0 + H, -80.0, fund=-90.0, margin=100.0, lev=20.0),
            _row("C", T0 + 2 * H, 1.0, fund=None)]
    got = SW.funding_top(rows, k=2)
    assert [x["sym"] for x in got] == ["B", "A"], got
    assert got[0]["fund_bp"] == -9000.0, got[0]
    assert all(x["sym"] != "C" for x in got), "строка без funding не считается"
    print(f"ok  самые дорогие по funding названы: {got[0]['sym']} "
          f"{got[0]['fund_usd']:+.0f} $ ({got[0]['fund_bp']:+.0f} б.п. маржи)")


def test_grid_reproduces_the_pair_and_flattens_when_the_short_is_the_tail():
    longs = [_row(f"L{i}", T0 + i * 24 * H, 20.0) for i in range(10)]
    for r in longs:
        r["side"] = "long"
    shorts = ([_row(f"S{i}", T0 + i * 24 * H, 20.0) for i in range(10)]
              + [_row("BOOM", T0 + 11 * 24 * H, -1500.0, lev=25.0,
                      exit_="ликвидация")])
    g = SW.pair_grid(longs, shorts, shares=(1.0, 0.5, 0.0))
    rows = {r["share"]: r for r in g["rows"]}
    # доля 1 — это сама пара, доля 0 — одна длинная книга
    assert abs(rows[1.0]["usd"] - (200.0 + (200.0 - 1500.0))) < 1e-6, rows
    assert abs(rows[0.0]["usd"] - 200.0) < 1e-6, rows
    # хвост делает шорт: уменьшив его билет, просадка пары мельчает
    assert rows[0.5]["dd"] > rows[1.0]["dd"], rows
    assert rows[0.0]["dd"] >= rows[0.5]["dd"], rows
    print(f"ok  сетка билета: доля 1 даёт {rows[1.0]['usd']:+.0f} $ при "
          f"просадке {100 * rows[1.0]['dd']:.1f} %, доля 0.5 — "
          f"{rows[0.5]['usd']:+.0f} $ при {100 * rows[0.5]['dd']:.1f} %")


def test_end_to_end_reads_the_journal_and_says_its_silence():
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "short.jsonl")
        lp = os.path.join(td, "journal.jsonl")
        with open(sp, "w", encoding="utf-8") as f:
            for i in range(40):
                f.write(json.dumps(_row(f"S{i}", T0 + i * 6 * H,
                                        10.0 if i % 4 else -70.0)) + "\n")
        with open(lp, "w", encoding="utf-8") as f:
            for i in range(20):
                r = _row(f"L{i}", T0 + i * 12 * H, 5.0, margin=25.0)
                r.update({"ruler": "safe", "side": "long"})
                f.write(json.dumps(r) + "\n")
        s = SW.run(short_path=sp, long_path=lp, log=lambda *a: None,
                   ctx={"error": "рядов нет"})
        b = s["books"]["safe_h"]
        assert b["n"] == 40 and b["stats"]["n"] == 40, b["n"]
        assert b["by_exit"]["тейк"]["n"] == 40, b["by_exit"]
        assert b["long_key"] == "safe", b["long_key"]
        assert b["grid"]["rows"][0]["share"] == 1.0
        # книг без строк в журнале — причина словами, а не нули
        assert s["books"]["aggr_h"].get("why"), s["books"]["aggr_h"]
        txt = report_text = SW.report(s)
        assert "Издержки посчитать не удалось" in txt
        assert "по плечу" in txt and "Выровнять кривую" in txt
        assert "задним числом не меняются" in report_text
        print(f"ok  прогон целиком: {b['n']} сделок, нетто {b['net']:+.2f} $; "
              "книга без строк названа причиной, отчёт говорит про издержки")


if __name__ == "__main__":
    for t in (test_leverage_bands_are_the_declared_ones,
              test_concentration_sees_the_planted_tail,
              test_liquidation_is_its_own_line_with_a_share_of_the_loss,
              test_funding_top_names_the_payers,
              test_grid_reproduces_the_pair_and_flattens_when_the_short_is_the_tail,
              test_end_to_end_reads_the_journal_and_says_its_silence):
        t()
    print("\nвсе 6 проверок прошли")
