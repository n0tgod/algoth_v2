#!/usr/bin/env python3
"""Ветвь судьи над записями: skip убирает вход, close сторожа закрывает по
рынку на часе после решения (причина «судья»); вход без решения остаётся и
считается числом только с дня рождения; журнала нет — записи как у книги,
причина словами; не-ветвь проходит насквозь."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ai_branch as AIB                                      # noqa: E402
import rules as R                                            # noqa: E402

H = 3600


def rec(sym, at, K=6, state="closed"):
    return {"sym": sym, "at": at, "marks": [[at + (k - 1) * H, 0.01] for k in range(1, K + 1)], "state": state,
            "pnl": 0.01 * K, "exit": "срок", "exit_ts": at + K * H - 1, "side": "short", "lev": 2.0, "fills": []}


def test_apply():
    import gate_run as G
    old = G.DECISIONS
    with tempfile.TemporaryDirectory() as d:
        G.DECISIONS = d
        AIB._CACHE.update(sig=None, rows=None)
        try:
            T = R.AI_START_TS + 3 * H
            a, b, c, old_rec = rec("AAAUSDT", T), rec("BBBUSDT", T), rec("CCCUSDT", T, K=8, state="open"), rec("DDDUSDT", R.AI_START_TS - 5 * H)
            recs = [a, b, c, old_rec]
            out, st = AIB.apply(recs, "optimal_h_ai", log=lambda *x: None)
            assert [r["sym"] for r in out] == ["AAAUSDT", "BBBUSDT", "CCCUSDT"] and st["why"] == "решений судьи ещё нет", \
                "журнала нет — как книга с момента старта, причина словами"
            rows = [{"t": T, "kind": "entry", "branch": "ai_news", "key": G.key_of("optimal_h", a), "decision": "skip"},
                    {"t": T, "kind": "entry", "branch": "ai_plain", "key": G.key_of("optimal_h", b), "decision": "skip"},
                    {"t": T, "kind": "entry", "branch": "ai_news", "key": G.key_of("optimal_h", c), "decision": "open"},
                    {"t": T + 2.5 * H, "kind": "hold", "branch": "ai_news_x", "key": G.key_of("optimal_h", c), "decision": "close"}]
            with open(os.path.join(d, "decisions-2026-10-18.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(r) for r in rows) + "\n")
            out, st = AIB.apply(recs, "optimal_h_ai", log=lambda *x: None)
            syms = [r["sym"] for r in out]
            assert syms == ["BBBUSDT", "CCCUSDT"], "skip ветки без новостей ветвь не трогает; до старта — не её позиции"
            cc = out[1]
            assert cc["exit"] == R.JUDGE_EXIT and cc["state"] == "closed" and abs(cc["pnl"] - 0.03) < 1e-12
            assert st == {"why": None, "cut": 1, "unjudged": 1, "closes": 1, "start": R.AI_START_TS}, st   # B без решения ai_news
            same, none = AIB.apply(recs, "optimal_h", log=lambda *x: None)
            assert same is recs and none is None, "основная книга проходит насквозь"
        finally:
            G.DECISIONS = old
    assert not R.is_current({"rules": R.RULES, "book_rules": R.FAMILY_RULES.get("h24"), "ruler": "optimal_h_ai",
                             "at": R.AI_START_TS - 1}), "строка ветви до старта — не её"
    assert R.is_current({"rules": R.RULES, "book_rules": R.FAMILY_RULES.get("h24"), "ruler": "optimal_h_ai",
                         "at": R.AI_START_TS}), "со старта — её"
    assert R.is_current({"rules": R.RULES, "book_rules": R.FAMILY_RULES.get("h24"), "ruler": "optimal_h",
                         "at": R.AI_START_TS - 86400}), "основная книга — прежним правилом"
    print("ok  ветвь судьи: старт с нуля (до старта — не её позиции и не её строки); skip убирает вход, close — выход «судья» на часе после решения, без решения — числом, нет журнала — словами")


if __name__ == "__main__":
    test_apply()
    print("\nвсе 1 проверки прошли")
