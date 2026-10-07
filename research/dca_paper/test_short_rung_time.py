#!/usr/bin/env python3
"""Проверки замера «повтор как время»: ячейки из реестра, первый повтор в
первые 24 ч, обещание повтора при двух руках, политики (срок, перенос цели,
контроль, нуль донора), суд и вердикт, отчёт без дыр, сквозной проход с
диском на подставных барах формы записи (окно 48 ч, книга 24 ч бит в бит)."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import short_rung_time as TM                                  # noqa: E402
import short_rung as SR                                       # noqa: E402
import run_short as S                                         # noqa: E402
import rules as R                                             # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0
AT = 1_700_000_000.0 + 1440 * 60


def _leg(sym, at, fwd=40.0, fav=-500.0, arm="nn"):
    g = T10._short_leg(at, sym=sym, fwd=fwd, fav=fav)
    g["arm"] = arm
    return g


def test_cells_first_repeat_and_favs():
    names = TM.all_names(3)
    assert names[:2] == ["ref", "all48"] and names[2:6] == ["t36", "t48", "tgt", "tgt48"] and len(names) == 6 + 12
    assert all(c[1:] == S.CELL[1:] for c in TM.cells_for(3))
    legs = [_leg("A", AT), _leg("A", AT + H, fav=-300.0, fwd=10.0), _leg("A", AT + H, fav=-800.0, fwd=50.0, arm="gbm"),
            _leg("A", AT + 30 * H), _leg("B", AT), _leg("B", AT + 23 * H), _leg("C", AT), _leg("C", AT + 25 * H)]
    reps = SR.repeats_of(legs)
    favs = TM.repeat_favs(legs)
    assert favs[SR.pkey("A", AT + H)] == -800.0, "при двух руках в секунду — выбор с большим |прогнозом|"
    assert TM.first_repeat(reps, SR.pkey("A", AT)) == AT + H
    assert TM.first_repeat(reps, SR.pkey("B", AT)) == AT + 23 * H
    assert TM.first_repeat(reps, SR.pkey("C", AT)) is None, "повтор на 25-м часу — не в первые 24"


def test_policies_follow_axes_and_null_takes_the_donor():
    legs = [_leg("A", AT), _leg("A", AT + H, fav=-800.0),
            _leg("B", AT), _leg("B", AT + 5 * H, fav=-200.0),
            _leg("C", AT)]
    reps = SR.repeats_of(legs)
    favs = TM.repeat_favs(legs)
    kA, kB, kC = SR.pkey("A", AT), SR.pkey("B", AT), SR.pkey("C", AT)
    assert TM.policy("ref", kA, reps, favs, {}) == {"adds": [], "hold_h": 24.0}, "срок книги — явно, окно прохода шире"
    assert TM.policy("all48", kC, reps, favs, {}) == {"adds": [], "hold_h": 48.0}
    assert TM.policy("t36", kA, reps, favs, {}) == {"adds": [], "hold_h": 36.0}
    assert TM.policy("t48", kA, reps, favs, {}) == {"adds": [], "hold_h": 48.0}
    assert TM.policy("t48", kC, reps, favs, {}) == {"adds": [], "hold_h": 24.0}, "без повтора — как книга"
    tg = TM.policy("tgt", kA, reps, favs, {})
    assert tg["hold_h"] == 24.0 and tg["take_events"] == [(AT + H, R.take_rule(-800.0, "short")["frac"])], tg
    tg48 = TM.policy("tgt48", kB, reps, favs, {})
    assert tg48["hold_h"] == 48.0 and tg48["take_events"] == [(AT + 5 * H, R.take_rule(-200.0, "short")["frac"])]
    nulls = {1: TM.null_donors(reps, 1)}
    assert set(nulls[1]) == {kA, kB} and set(nulls[1].values()) == {kA, kB}
    pn = TM.policy(TM.null_name("tgt48", 1), kA, reps, favs, nulls)
    donor = nulls[1][kA]
    t_d = TM.first_repeat(reps, donor)
    assert pn["hold_h"] == 48.0 and pn["take_events"] == [(AT + (t_d - donor[1]), R.take_rule(favs[(donor[0], round(t_d, 3))], "short")["frac"])]
    assert TM.policy(TM.null_name("t48", 1), kC, reps, favs, nulls) == {"adds": [], "hold_h": 24.0}
    seen = {tuple(sorted(TM.null_donors(reps, s_).items())) for s_ in range(1, 9)}
    assert len(seen) > 1


def test_judge_requires_book_null_and_blanket():
    def c(final, dd):
        return {"final": final, "max_dd": dd, "n": 10}
    names = TM.all_names(3)
    cash = {nm: {bk: c(0.10, -0.05) for bk in TM.BOOKS} for nm in names}            # всё 2.0
    jd = TM.judge(cash, 3)
    assert not any(j["candidate"] for j in jd.values()) and TM.verdict(jd).startswith("нет кандидатов")
    for bk in TM.BOOKS:
        cash["t48"][bk] = c(0.14, -0.05)                                              # 2.8
        for i in (1, 2, 3):
            cash[TM.null_name("t48", i)][bk] = c(0.11, -0.05)
    jd = TM.judge(cash, 3)
    assert jd["t48"]["candidate"] and "t48" in TM.verdict(jd)
    # слепое продление не хуже — не кандидат
    for bk in TM.BOOKS:
        cash["all48"][bk] = c(0.15, -0.05)
    jd = TM.judge(cash, 3)
    assert not jd["t48"]["candidate"] and not jd["t48"]["books"]["optimal_h"]["above_all48"]
    # перенос цели со слепым продлением не сравнивается
    for bk in TM.BOOKS:
        cash["tgt"][bk] = c(0.14, -0.05)
        for i in (1, 2, 3):
            cash[TM.null_name("tgt", i)][bk] = c(0.11, -0.05)
    jd = TM.judge(cash, 3)
    assert jd["tgt"]["candidate"]


def test_end_to_end_with_disk_sink_window_48():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = [_leg("SSSUSDT", at), _leg("SSSUSDT", at + H, fav=-900.0), _leg("SSSUSDT", at + 2 * H),
            _leg("TTTUSDT", at), _leg("TTTUSDT", at + H, fav=-300.0)]
    td = tempfile.mkdtemp(prefix="rung-time-")
    try:
        said = []
        s = T10._with_levels(lambda: TM.run(legs_=legs, src=src, log=said.append, ctx={"error": "рядов нет"},
                                            launch={}, now=at + 400 * H, seeds=1, mem_limit=10 ** 6, sink_dir=td))
        assert not s.get("error"), s.get("error")
        assert s["with_repeat"] == 3 and s["pass_hold_h"] == 48.0
        for nm in TM.all_names(1):
            for bk in TM.BOOKS:
                c = s["cash"][nm][bk]
                assert c.get("n") and c.get("final") is not None, (nm, bk, c)
        de = float(s["tail"]["data_end"])
        sink = __import__("short_rung_axes").Sink(td)
        ref = sink.read("optimal_s", SR.cell_key("ref"), de)
        t48 = sink.read("optimal_s", SR.cell_key("t48"), de)
        a48 = sink.read("optimal_s", SR.cell_key("all48"), de)
        tgt = sink.read("optimal_s", SR.cell_key("tgt"), de)
        assert ref and set(ref) == set(t48) == set(a48) == set(tgt)
        assert all(r["hold_h"] == 24.0 and r["sched_end"] == r["at"] + 24 * H for r in ref.values())
        k_rep = ("optimal_s", "SSSUSDT", round(at, 3))
        k_last = ("optimal_s", "SSSUSDT", round(at + 2 * H, 3))
        assert t48[k_rep]["hold_h"] == 48.0 and t48[k_last]["hold_h"] == 24.0 and a48[k_last]["hold_h"] == 48.0
        assert tgt[k_rep]["take_moves"] == 1 and tgt[k_last]["take_moves"] == 0
        p = s["positions_stats"]["t48"]["optimal_h"]
        assert p["changed"] >= 1 and p["extra_h_med"] is not None
        assert s["verdict"].startswith(("нет кандидатов", "КАНДИДАТ")), s["verdict"]
        md = TM.report(s)
        assert "None" not in md and "nan" not in md and "## Суд по вариантам" in md and "слепого продления" in md, md[:600]
        assert any(x.startswith("пол капитуляции 0.5") for x in said)
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
