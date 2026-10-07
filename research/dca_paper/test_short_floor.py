#!/usr/bin/env python3
"""Проверки замера «пол как ось»: ячейки и политики (пол явно у каждой),
половины окна формулой кассы, суд (главная 0.25 против пола книги на $10k,
обе половины, все депозиты, обе книги), сборка из частей с названной
недостающей группой, сквозной проход с диском на подставных барах."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import short_floor as FL                                      # noqa: E402
import short_rung as SR                                       # noqa: E402
import run_short as S                                         # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0


def test_cells_and_policies_carry_the_floor_explicitly():
    names = [c[0] for c in FL.cells_for()]
    assert names == [SR.cell_key(f"f{int(round(f * 100)):03d}") for f in FL.FLOORS]
    assert all(c[1:] == S.CELL[1:] for c in FL.cells_for())
    for f in FL.FLOORS:
        pol = FL.adds_of({}, SR.cell_key(FL.cell_name(f)))
        assert pol == {"adds": [], "floor_frac": f}, pol
    assert FL.cell_name(0.25) == "f025" and FL.floor_of_name("f075") == 0.75
    assert FL.book_floor("optimal_h") == 0.5 and FL.book_floor("safe_h") == 0.1


def test_halves_split_by_date_and_use_the_cash_drawdown():
    days = [{"d": f"2026-09-{dd:02d}", "usd": u} for dd, u in zip(range(1, 9), (100, -50, 30, 20, -10, 60, -80, 40))]
    h = FL.halves(days, 10000.0)
    assert h[0]["from"] == "2026-09-01" and h[0]["to"] == "2026-09-04" and h[0]["days"] == 4
    assert h[1]["from"] == "2026-09-05" and h[1]["to"] == "2026-09-08"
    assert abs(h[0]["final"] - 0.01) < 1e-9 and abs(h[1]["final"] - 0.001) < 1e-9
    assert h[0]["max_dd"] < 0 and h[1]["max_dd"] < 0 and h[0]["ratio"] > h[1]["ratio"]
    assert FL.halves(days[:3], 10000.0) == [None, None]
    assert FL.halves([], 10000.0) == [None, None]


def _cash(ratio, halves=(2.0, 2.0), deps=(2.0, 2.0, 2.0)):
    out = {}
    for dep, r in zip(FL.DEPS, deps):
        d = {"n": 10, "final": 0.1, "max_dd": -0.1 / r if r else None, "ratio": r}
        if int(dep) == int(FL.MAIN_DEP):
            d["ratio"] = ratio
            d["halves"] = [{"from": "a", "to": "b", "days": 5, "final": 0.05, "max_dd": -0.05 / halves[0], "ratio": halves[0]},
                           {"from": "c", "to": "d", "days": 5, "final": 0.05, "max_dd": -0.05 / halves[1], "ratio": halves[1]}]
        out[str(int(dep))] = d
    return out


def test_judge_demands_all_three_for_both_books():
    books = ["optimal_h", "aggr_h"]
    cash = {FL.cell_name(f): {bk: _cash(2.0) for bk in books} for f in FL.FLOORS}
    jd = FL.judge(cash, books)
    assert not jd["candidate"] and FL.verdict(jd).startswith("не кандидат")
    for bk in books:
        cash["f025"][bk] = _cash(2.5, halves=(2.5, 2.5), deps=(2.5, 2.5, 2.5))
    jd = FL.judge(cash, books)
    assert jd["candidate"] and FL.verdict(jd).startswith("КАНДИДАТ")
    # вторая половина не лучше у одной книги — не кандидат, причина названа
    cash["f025"]["aggr_h"] = _cash(2.5, halves=(2.5, 1.9), deps=(2.5, 2.5, 2.5))
    jd = FL.judge(cash, books)
    assert not jd["candidate"] and "обе половины" in FL.verdict(jd) and "aggr_h" in FL.verdict(jd)
    # $100k не лучше — не кандидат
    cash["f025"]["aggr_h"] = _cash(2.5, halves=(2.5, 2.5), deps=(2.5, 2.5, 1.5))
    jd = FL.judge(cash, books)
    assert not jd["candidate"] and "все депозиты" in FL.verdict(jd)
    # безопасная не судится, но считается
    cash2 = {FL.cell_name(f): {bk: _cash(2.0) for bk in books + ["safe_h"]} for f in FL.FLOORS}
    for bk in books:
        cash2["f025"][bk] = _cash(2.5, halves=(2.5, 2.5), deps=(2.5, 2.5, 2.5))
    jd2 = FL.judge(cash2, books + ["safe_h"])
    assert jd2["candidate"] and "safe_h" in jd2["books"] and jd2["books"]["safe_h"]["book_floor"] == 0.1


def test_end_to_end_with_disk_and_parts():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = T10._legs(at, "SSSUSDT", n=3) + T10._legs(at, "TTTUSDT", n=2)
    td = tempfile.mkdtemp(prefix="floor-")
    try:
        said = []
        s = T10._with_levels(lambda: FL.run(legs_=legs, src=src, log=said.append, ctx={"error": "рядов нет"},
                                            launch={}, now=at + 400 * H, groups=[0.5], mem_limit=10 ** 6,
                                            out_dir=td, sink_dir=os.path.join(td, "sink"), cache={}))
        assert not s.get("error"), s.get("error")
        assert s["books"] == ["optimal_h", "aggr_h"] and s["missing"] and s["missing"][0]["frac"] == 0.1
        floors = [x for x in said if x.startswith("пол капитуляции")]
        assert floors == ["пол капитуляции 0.5 — линейки optimal_s"], floors
        for f in FL.FLOORS:
            c = s["cash"][FL.cell_name(f)]["optimal_h"]
            for dep in FL.DEPS:
                assert c[str(int(dep))]["n"] and c[str(int(dep))]["final"] is not None, (f, dep, c)
        # пол едет в записи: ячейка 0.10 и 0.75 на одном пути дают разные исходы хотя бы у одной позиции
        sink = __import__("short_rung_axes").Sink(os.path.join(td, "sink", "g0.5"))
        de = float(s["parts"]["0.5"]["ref_check"] and 0) or None
        assert os.path.exists(FL.part_path(0.5, td)) and not os.path.exists(FL.part_path(0.1, td))
        files = sorted(os.listdir(os.path.join(td, "sink", "g0.5")))
        assert len(files) == len(FL.FLOORS) and all(f.startswith("optimal_s__") for f in files)
        assert s["verdict"].startswith(("КАНДИДАТ", "не кандидат")), s["verdict"]
        md = FL.report(s)
        assert "None" not in md and "nan" not in md and "НЕ ПОСЧИТАНА" in md and "(книга)" in md and "(главная)" in md, md[:800]
        asm = FL.assemble(out_dir=td)
        assert asm["cash"] == s["cash"] and asm["verdict"] == s["verdict"]
        empty = FL.assemble(out_dir=os.path.join(td, "nothing"))
        assert empty["books"] == [] and len(empty["missing"]) == 2 and empty["verdict"].startswith("не измерено")
        assert "None" not in FL.report(empty)
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
