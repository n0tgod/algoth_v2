#!/usr/bin/env python3
"""Ветки судьи: «не судили» остаётся во всех ветках и считается числом;
жребий убирает ровно столько же входов в каждом часе; закрытие сторожа —
на отметке часа ПОСЛЕ решения через ядро (`wave.guard_record`), позиция,
вышедшая раньше, не трогается; случайные закрытия — того же числа и тех же
часов; делистинг закрывает только открытые в момент объявления."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate_books as GB                                      # noqa: E402
import gate_run as G                                         # noqa: E402

H = 3600
T0 = G.GATE_SINCE + 2 * H


def rec(sym, at, K=6, state="closed", step=0.01):
    marks = [[at + (k - 1) * H, step] for k in range(1, K + 1)]
    return {"sym": sym, "at": at, "marks": marks, "state": state, "pnl": step * K, "exit": "срок",
            "exit_ts": at + K * H - 1, "side": "long", "lev": 2.0, "fills": []}


def test_index_filter_rand():
    recs = [rec(f"S{i}USDT", T0 + (i % 2) * H) for i in range(6)]
    rows = [{"kind": "entry", "branch": "ai_news", "key": G.key_of("b", recs[0]), "decision": "skip"},
            {"kind": "entry", "branch": "ai_news", "key": G.key_of("b", recs[1]), "decision": "open"},
            {"kind": "entry", "branch": "ai_news", "key": G.key_of("b", recs[2]), "decision": "skip"},
            {"kind": "entry", "branch": "ai_news_repeat", "key": G.key_of("b", recs[3]), "decision": "skip"},
            {"kind": "hold", "branch": "ai_news_x", "key": "k1", "decision": "close", "t": 5, "no_verdict": "x"},
            {"kind": "hold", "branch": "ai_news_x", "key": "k1", "decision": "close", "t": 9},
            {"kind": "hold", "branch": "ai_news_x", "key": "k1", "decision": "close", "t": 7}]
    idx = GB.entry_index(rows)
    assert set(idx) == {"ai_news"} and len(idx["ai_news"]) == 3, "повтор — не ветка"
    assert GB.close_index(rows) == {"k1": 7.0}, "первое закрытие с вердиктом"
    kept, cut, unj = GB.filt(recs, "b", idx["ai_news"])
    assert cut == 2 and unj == 3 and len(kept) == 4, (cut, unj, len(kept))
    nbh = GB.cut_by_hour(recs, "b", idx["ai_news"])
    assert nbh == {int(T0): 2}, nbh                              # S0 и S2 — чётные, час T0
    for s in range(5):
        rr = GB.rand_cut(recs, nbh, random.Random(s))
        assert len(rr) == 4 and sum(1 for r in rr if r["at"] == T0) == 1, "в том же часе убрано столько же"
    # пул жребия — только входы, которые судья решал моделью: повтор вне
    # пула («held») жребий не трогает, и отказ жребия всегда что-то меняет
    keyed = [dict(r, _key=G.key_of("b", r)) for r in recs]
    pool = {G.key_of("b", recs[i]) for i in (0, 2, 4)}            # все три — час T0
    for s in range(5):
        rr = GB.rand_cut(keyed, nbh, random.Random(s), pool)
        gone = {r["sym"] for r in recs} - {r["sym"] for r in rr}
        assert len(rr) == 4 and gone <= {"S0USDT", "S2USDT", "S4USDT"}, gone
        assert all("_key" not in r for r in rr), "служебный ключ в кассу не едет"
    print("ok  индекс решений, фильтр (не судили — остаются), жребий той же формы по часам и только из пула судьи")


def test_closes_judge_rand_delist():
    a = rec("AAAUSDT", T0, K=6)
    b = rec("BBBUSDT", T0, K=2)
    c = rec("CCCUSDT", T0, K=8, state="open")
    recs = [a, b, c]
    closes = {G.key_of("x", a): T0 + 2.5 * H, G.key_of("x", b): T0 + 3 * H, G.key_of("x", c): T0 + 0.2 * H}
    out, n, ks = GB.apply_closes(recs, "x", closes, "судья")
    assert n == 2 and ks == [3, 1], (n, ks)                      # B вышла раньше решения — не трогается
    assert out[0]["exit"] == "судья" and abs(out[0]["pnl"] - 0.03) < 1e-12 and out[0]["state"] == "closed"
    assert out[1] is b and out[2]["exit"] == "судья" and abs(out[2]["pnl"] - 0.01) < 1e-12
    rr = GB.rand_closes(recs, ks, random.Random(1), "судья")
    closed = [r for r in rr if r.get("exit") == "судья"]
    assert len(closed) == 2, "столько же закрытий"
    assert sorted(len(r["marks"]) for r in closed) == [1, 3], "те же часы держания"
    ev = [{"venue": "bybit", "kind": "delistings", "title": "Delisting of AAAUSDT and ZZZUSDT", "t": (T0 + 1.5 * H) * 1000},
          {"venue": "binance", "kind": "Delisting", "title": "Delist CCCUSDT", "t": (T0 + H) * 1000},
          {"venue": "bybit", "kind": "delistings", "title": "Delisting of CCCUSDT", "t": (T0 - H) * 1000}]
    dl = GB.delist_closes(recs, "x", ev)
    assert dl == {G.key_of("x", a): T0 + 1.5 * H}, dl            # Binance — не наша площадка; объявление до входа — не закрытие
    print("ok  закрытия: после решения, вышедшая раньше — нетронута; жребий тех же часов; делистинг — открытые в момент объявления")


if __name__ == "__main__":
    test_index_filter_rand()
    test_closes_judge_rand_delist()
    print("\nвсе 2 проверки прошли")
