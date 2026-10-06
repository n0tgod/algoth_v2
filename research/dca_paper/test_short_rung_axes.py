#!/usr/bin/env python3
"""Проверки замера трёх осей долива: ячейки объявлены из реестра, политики
по осям (доля, порог, пол, пол без долива), нуль с ВСЕМИ задержками донора,
суд по вариантам и вердикт, отчёт без дыр, сквозной проход с диском
(записи не живут в памяти) на подставных барах формы записи."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import short_rung_axes as AX                                  # noqa: E402
import short_rung as SR                                       # noqa: E402
import run_short as S                                         # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0
AT = 1_700_000_000.0 + 1440 * 60


def _leg(sym, at, fwd=40.0):
    g = T10._short_leg(at, sym=sym, fwd=fwd)
    g["arm"] = "nn"
    return g


def test_cells_declared_and_policies_follow_axes():
    names = AX.all_names(3)
    assert names[:3] == ["ref", "f25_ref", "f10_ref"] and names[3:11] == [v[0] for v in AX.VARIANTS]
    assert len(names) == 3 + 8 + 8 * 3 and AX.null_name("p25", 2) in names
    assert AX.BOOKS == ["optimal_h", "aggr_h"]
    assert all(c[1:] == S.CELL[1:] for c in AX.cells_for(3)), "геометрия — книги"
    legs = [_leg("A", AT)] + [_leg("A", AT + i * H) for i in (1, 2, 3)]
    reps = SR.repeats_of(legs)
    key = SR.pkey("A", AT)
    assert AX.policy("ref", key, reps, {}) is None
    assert AX.policy("f25_ref", key, reps, {}) == {"adds": [], "floor_frac": 0.25}
    assert AX.policy("r2", key, reps, {}) == {"adds": [(AT + H, 0.25)], "max": 1}
    assert AX.policy("w05", key, reps, {}) == {"adds": [(AT + H, 0.05)], "max": 1}
    assert AX.policy("w10", key, reps, {})["adds"][0][1] == 0.10
    p25 = AX.policy("p25", key, reps, {})
    assert p25["min_profit"] == 0.25 and p25["max"] == 1 and len(p25["adds"]) == 3, "порог — все повторы кандидаты"
    f10 = AX.policy("f10", key, reps, {})
    assert f10 == {"adds": [(AT + H, 0.25)], "max": 1, "floor_frac": 0.10}
    # позиция без повтора: долива нет, но пол ячейки остаётся
    k2 = SR.pkey("A", AT + 3 * H)
    assert AX.policy("r2", k2, reps, {}) is None and AX.policy("f25", k2, reps, {}) == {"adds": [], "floor_frac": 0.25}


def test_null_uses_all_offsets_of_the_donor():
    legs = [_leg("A", AT), _leg("A", AT + H), _leg("A", AT + 2 * H),
            _leg("B", AT), _leg("B", AT + 5 * H),
            _leg("C", AT + 10 * H), _leg("C", AT + 13 * H), _leg("C", AT + 14 * H), _leg("C", AT + 15 * H)]
    reps = SR.repeats_of(legs)
    seen = set()
    for seed in range(1, 8):
        nz = AX.null_offsets_all(reps, seed)
        assert set(nz) == {k for k, v in reps.items() if v}
        got = sorted(tuple(round((t - k[1]) / H) for t in v) for k, v in nz.items())
        # позиций с повтором шесть (вложенные тоже позиции): множества задержек те же, доноры переставлены
        assert got == [(1,), (1,), (1, 2), (1, 2), (3, 4, 5), (5,)], got
        seen.add(tuple(sorted((k, tuple(v)) for k, v in nz.items())))
    assert len(seen) > 1
    nulls = {1: AX.null_offsets_all(reps, 1)}
    pol = AX.policy(AX.null_name("p10", 1), SR.pkey("A", AT), reps, nulls)
    assert pol and pol["min_profit"] == 0.10 and len(pol["adds"]) == len(nulls[1][SR.pkey("A", AT)])
    pol2 = AX.policy(AX.null_name("w05", 1), SR.pkey("A", AT), reps, nulls)
    assert pol2 and len(pol2["adds"]) == 1 and pol2["adds"][0][1] == 0.05


def test_judge_and_verdict():
    def c(final, dd):
        return {"final": final, "max_dd": dd, "n": 10}
    names = AX.all_names(3)
    cash = {nm: {bk: c(0.10, -0.05) for bk in AX.BOOKS} for nm in names}       # всё как книга: 2.0
    pos = {nm: {bk: {} for bk in AX.BOOKS} for nm in names}
    jd = AX.judge(cash, pos, 3)
    assert not any(j["candidate"] for j in jd.values())
    assert AX.verdict(jd).startswith("нет кандидатов")
    # w10 лучше книги у обеих и выше всех зёрен — кандидат
    for bk in AX.BOOKS:
        cash["w10"][bk] = c(0.12, -0.04)
        for i in (1, 2, 3):
            cash[AX.null_name("w10", i)][bk] = c(0.11, -0.05)
    jd = AX.judge(cash, pos, 3)
    assert jd["w10"]["candidate"] and AX.verdict(jd).startswith("КАНДИДАТ") and "w10" in AX.verdict(jd)
    # одно зерно не хуже — не кандидат
    cash[AX.null_name("w10", 2)]["aggr_h"] = c(0.12, -0.04)
    jd = AX.judge(cash, pos, 3)
    assert not jd["w10"]["candidate"] and jd["w10"]["books"]["aggr_h"]["null_beat"] > 0
    # ячейка пола обязана быть лучше и своего пола без долива
    for bk in AX.BOOKS:
        cash["f25"][bk] = c(0.12, -0.04)
        cash["f25_ref"][bk] = c(0.13, -0.04)
        for i in (1, 2, 3):
            cash[AX.null_name("f25", i)][bk] = c(0.05, -0.05)
    jd = AX.judge(cash, pos, 3)
    assert jd["f25"]["books"]["optimal_h"]["better_than_book"] and not jd["f25"]["books"]["optimal_h"]["better_than_floor_ref"]
    assert not jd["f25"]["candidate"]


def test_end_to_end_with_disk_sink():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = [_leg("SSSUSDT", at), _leg("SSSUSDT", at + H), _leg("SSSUSDT", at + 2 * H),
            _leg("TTTUSDT", at), _leg("TTTUSDT", at + H)]
    td = tempfile.mkdtemp(prefix="rung-axes-")
    try:
        said = []
        s = T10._with_levels(lambda: AX.run(legs_=legs, src=src, log=said.append, ctx={"error": "рядов нет"},
                                            launch={}, now=at + 400 * H, seeds=1, mem_limit=10 ** 6, sink_dir=td))
        assert not s.get("error"), s.get("error")
        files = sorted(os.listdir(td))
        assert len(files) == len(AX.all_names(1)) and all(f.startswith("optimal_s__") for f in files), files[:5]
        for nm in AX.all_names(1):
            for bk in AX.BOOKS:
                c = s["cash"][nm][bk]
                assert c.get("n") and c.get("final") is not None, (nm, bk, c)
        # доля 0.05 добавляет меньше нотионала, чем 0.25: приращение по модулю меньше
        p25, p05 = s["positions_stats"]["r2"]["optimal_h"], s["positions_stats"]["w05"]["optimal_h"]
        assert p25["adds"] == p05["adds"] >= 2 and abs(p05["mean"]) < abs(p25["mean"]), (p25, p05)
        # пол без долива меняет исход хотя бы у одной позиции ИЛИ совпадает — но записи несут свой пол
        recs = AX.Sink(td).read("optimal_s", SR.cell_key("f10_ref"), float(s["tail"]["data_end"]))
        assert recs and all(r["floor_frac"] == 0.10 and r["adds"] == 0 and r["state"] for r in recs.values())
        assert s["verdict"].startswith(("нет кандидатов", "КАНДИДАТ")), s["verdict"]
        md = AX.report(s)
        assert "None" not in md and "nan" not in md and "## Суд по вариантам" in md and "ось A" in md, md[:600]
        assert any(x.startswith("пол капитуляции 0.5") for x in said) and not any(x.startswith("пол капитуляции 0.1") for x in said)
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
