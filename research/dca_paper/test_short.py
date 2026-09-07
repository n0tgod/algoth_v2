#!/usr/bin/env python3
"""Проверки коротких книг на сигнале h24 и общей статистики.

Кусаются: подпись кэша меняется вместе с ячейкой и сроком (иначе книга
считала бы чужие исходы своими); ноги берутся у ОБЕИХ рук и стоят по
времени; книга «агрессивная» отличается от «оптимальной» ровно гейтом
плеча; журнал и артефакт семейства СВОИ (в журнал длинных книг не
попадает ни строки). Общий счёт двух книг проверяет `test_pair.py`: он
считается своей книгой, а не блоком этого прогона.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_short as S                                         # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0
T0 = 1786320000.0


def _picks(path, hours, arms=("gbm", "nn")):
    """Журнал выборов книги со сроком: у каждой руки своё имя в час."""
    with open(path, "w", encoding="utf-8") as f:
        for h in hours:
            for arm in arms:
                sym = "SSSUSDT" if arm == "gbm" else "TTTUSDT"
                f.write(json.dumps({
                    "arm": arm, "hour": h, "long": [],
                    "short": [{"sym": sym, "fwd": -420.0, "px": 100.0,
                               "mae": 120.0, "mfe": -700.0}]}) + "\n")


def test_cache_signature_follows_the_cell_and_the_hold():
    was_hold, was_cell = R.H24_HOLD_H, S.CELL
    a = S.cache_sig()
    try:
        R.H24_HOLD_H = 72
        b = S.cache_sig()
        assert b != a and b["hold_h"] == 72, (a, b)
        R.H24_HOLD_H = was_hold
        S.CELL = ("c3:none:t2", "c3", "none", "t2")
        c = S.cache_sig()
        assert c != a and c["cell"] == "c3:none:t2", (a, c)
    finally:
        R.H24_HOLD_H, S.CELL = was_hold, was_cell
    assert S.cache_sig() == a
    print("ok  подпись кэша меняется вместе со сроком и ячейкой — чужие "
          "исходы своими не станут")


def test_legs_come_from_both_arms_in_time_order():
    tmp = tempfile.mkdtemp(prefix="short-")
    path = os.path.join(tmp, "picks.jsonl")
    try:
        _picks(path, ["2026-09-01-00", "2026-09-01-01"])
        got = S.legs(path=path, log=lambda *a: None)
        assert len(got) == 4, got
        assert {g["arm"] for g in got} == {"gbm", "nn"}
        assert [g["at"] for g in got] == sorted(g["at"] for g in got)
        # внутри часа порядок по руке: он же порядок кассы
        assert [g["arm"] for g in got[:2]] == ["gbm", "nn"], got[:2]
        assert all(g["side"] == "short" for g in got)
        print(f"ok  ноги обеих рук: {len(got)} решений, порядок по времени "
              "и руке")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_needs_replay_asks_for_new_and_open_positions():
    legs = [{"sym": "AAAUSDT", "at": T0}, {"sym": "BBBUSDT", "at": T0 + H}]
    cache = {}
    assert len(S.needs_replay(cache, legs)) == 2
    for rk in set(S.BOOKS.values()):
        cache[(rk, "AAAUSDT", round(T0, 3))] = {"state": "closed"}
        cache[(rk, "BBBUSDT", round(T0 + H, 3))] = {"state": "open"}
    need = S.needs_replay(cache, legs)
    assert [g["sym"] for g in need] == ["BBBUSDT"], need
    print("ok  заново считаются новые решения и открытые позиции, "
          "закрытые берутся из кэша")


def _end_to_end(tmp):
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = T10._legs(at, "SSSUSDT") + T10._legs(at, "TTTUSDT")
    for i, g in enumerate(legs):
        g["arm"] = "nn" if i % 2 else "gbm"
    jp = os.path.join(tmp, "short.jsonl")
    cp = os.path.join(tmp, "recs.jsonl")
    s = T10._with_levels(lambda: S.run(legs_=legs, src=src, journal=jp,
                                       cache_path=cp, log=lambda *a: None))
    return s, jp, cp, legs


def test_family_writes_its_own_journal_and_gates_the_aggressive_book():
    tmp = tempfile.mkdtemp(prefix="short-")
    try:
        s, jp, cp, legs = _end_to_end(tmp)
        assert s["family"] == "h24" and s["hedge"] is True
        assert s["signal"]["hold_h"] == R.H24_HOLD_H == 24
        assert s["rules"]["RULER_ORDER"] == list(R.H24_ORDER)
        assert set(s["rulers"]) == set(R.H24_ORDER), s["rulers"]
        # журнал семейства свой, и он не пуст
        rows, bad = R.read_journal(jp)
        assert rows and not bad
        assert {R.ruler_of(r) for r in rows} <= set(R.H24_ORDER), \
            sorted({R.ruler_of(r) for r in rows})
        assert all(r["side"] == "short" for r in rows)
        # «агрессивная» — та же линейка, но гейт плеча: правило читается,
        # а не подразумевается. Поднимаем порог до заведомо недостижимого
        # и требуем, чтобы книга опустела: гейт, которого нет, этого не
        # сделает.
        one = s["one_name"]
        assert one["aggr_h"]["min_lev"] == R.AGGR_MIN_LEV
        assert one["optimal_h"]["min_lev"] is None
        assert one["aggr_h"]["kept"] <= one["optimal_h"]["kept"], one
        was_gate = R.RULERS["aggr_h"].get("min_lev")
        try:
            R.RULERS["aggr_h"]["min_lev"] = 999.0
            s2 = T10._with_levels(lambda: S.run(
                legs_=legs, src=T3._Src({}), journal=os.path.join(tmp, "g.jsonl"),
                cache_path=cp, log=lambda *a: None))
            assert s2["one_name"]["aggr_h"]["kept"] == 0, s2["one_name"]["aggr_h"]
            assert s2["one_name"]["optimal_h"]["kept"] > 0
        finally:
            R.RULERS["aggr_h"]["min_lev"] = was_gate
        # билет книги — из объявленного пика режима
        b = s["books"][f"optimal_h:{int(R.DEPOSITS[1])}"]
        assert b["ticket"] == R.ticket(R.DEPOSITS[1], "optimal_h")
        assert (b.get("dups") or {}).get("overlaps") == 0, b.get("dups")
        # кэш пригоден для следующего прогона: второй прогон не считает заново
        cache, why = S.read_cache(cp, log=lambda *a: None)
        assert not why and cache, why
        assert not S.needs_replay(cache, [g for g in legs
                                          if g["sym"] == "SSSUSDT"][:1])
        txt = S.report(s)
        assert "хедж" in txt.lower() and "## Книги" in txt
        print(f"ok  семейство пишет свой журнал ({len(rows)} строк), "
              f"«агрессивная» под гейтом {one['aggr_h']['kept']} против "
              f"{one['optimal_h']['kept']} у «оптимальной», дублей нет")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_cache_signature_follows_the_cell_and_the_hold()
    test_legs_come_from_both_arms_in_time_order()
    test_needs_replay_asks_for_new_and_open_positions()
    test_family_writes_its_own_journal_and_gates_the_aggressive_book()
    print("\nвсе 4 проверки прошли")
