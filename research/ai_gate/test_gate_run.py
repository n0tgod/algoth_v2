#!/usr/bin/env python3
"""Запись вперёд судьи: вход судится один раз и только с дня рождения и не
старше LATE_H; повтор — 5 % ключей по отпечатку; забор суточной цены
останавливает вызовы с пометкой; сторож зовёт модель только по событию
(новость, событие площадки, сдвиг толпы ≥ 10 п.п.), без события — heartbeat
раз в 6 ч без модели; несвежий фон — «фон не свеж», не «ничего не
случилось»; ожидание обучения — проход уступает. Подделки — литералы."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate_run as G                                         # noqa: E402

H = 3600
NOW = G.GATE_SINCE + 10 * H + 300


class Client:
    def __init__(self, decide):
        self.decide, self.n = decide, 0


def fake_ask(client, kind, d):
    client.n += 1
    return {"decision": client.decide(kind, d), "confidence": 0.7, "reasons": ["r"], "news_used": [],
            "no_verdict": None, "served_model": "claude-opus-5-5", "cost_usd": 0.01,
            "usage": {"input_tokens": 2000, "output_tokens": 100}, "model": "claude-opus-5-5"}


def setup(tmp, books, news=(), events=(), state=None):
    G.DECISIONS = os.path.join(tmp, "decisions"); G.RECORD = os.path.join(tmp, "record")
    G.WATCH = os.path.join(G.RECORD, "watch.json"); G.LATEST = os.path.join(tmp, "latest.json")
    G.TRAIN_WAIT = os.path.join(tmp, "train_wait.flag")
    G.NEWS_LATEST = os.path.join(tmp, "news.json"); G.MS_LATEST = os.path.join(tmp, "ms.json")
    for p in (G.NEWS_LATEST, G.MS_LATEST):
        open(p, "w").write("{}"); os.utime(p, (NOW - 60, NOW - 60))
    G.candidates = lambda log: (books, None)
    G.CTX.load_state = lambda days: (state or {}, [], list(events))
    G.CTX.load_news = lambda: list(news)
    G.CTX.build = lambda kind, r, book, side, now, recs, st, mr, ev, nw: (
        {"px": None}, [x for x in nw if r["sym"] in x.get("tags", {})], {"px": False})
    G.J.ask = fake_ask
    G.J.dossier = lambda kind, r, book, side, t, news=None, **kw: {"kind": kind, "sym": r["sym"], "news": news}


def rows_of():
    return G.read_decisions()


def test_entries_once_window_repeat_budget():
    with tempfile.TemporaryDirectory() as d:
        recs = [{"sym": f"S{i}USDT", "at": NOW - 2 * H, "state": "closed"} for i in range(40)]
        recs += [{"sym": "OLDUSDT", "at": G.GATE_SINCE - H}, {"sym": "LATEUSDT", "at": NOW - (G.LATE_H + 1) * H}]
        setup(d, {"optimal": recs, "optimal_h": []})
        c = Client(lambda k, dd: "skip" if dd["sym"] == "S1USDT" else "open")
        s = G.run(log=lambda *a: None, client=c, now=NOW)
        rs = rows_of()
        keys = {r["key"] for r in rs if r["branch"] == "ai_news"}
        assert len(keys) == 40 and not any("OLD" in k or "LATE" in k for k in keys), "до дня рождения и поздние — не судятся"
        reps = [r for r in rs if r["branch"] == "ai_news_repeat"]
        assert reps and all(G.is_repeat(r["key"]) for r in reps) and len(reps) == sum(G.is_repeat(k) for k in keys)
        assert all(r["late_min"] == 120.0 for r in rs if r["kind"] == "entry")
        assert s["today"]["skips"] == 1 and s["today"]["entries"] == 40
        n1 = c.n
        G.run(log=lambda *a: None, client=c, now=NOW + 60)
        assert c.n == n1, "второй проход не судит тех же"
    with tempfile.TemporaryDirectory() as d:
        recs = [{"sym": f"B{i}USDT", "at": NOW - H} for i in range(5)]
        setup(d, {"optimal": recs, "optimal_h": []})
        G.BUDGET_DAY_USD, old = 0.025, G.BUDGET_DAY_USD
        try:
            c = Client(lambda k, dd: "open")
            G.run(log=lambda *a: None, client=c, now=NOW)
        finally:
            G.BUDGET_DAY_USD = old
        rs = rows_of()
        assert c.n == 3, c.n                                      # 0.01 × 3 ≥ 0.025 → стоп
        assert sum(1 for r in rs if r.get("no_verdict") == "бюджет суток") == len(rs) - 3
        assert all(r["decision"] == "open" for r in rs if r.get("no_verdict"))
    print("ok  вход: один раз, окно дня рождения и LATE_H, повтор 5 % по ключу, забор суток с пометкой")


def test_watcher_events_heartbeat_stale_and_yield():
    with tempfile.TemporaryDirectory() as d:
        at = NOW - 8 * H
        recs = [{"sym": "AUSDT", "at": at, "state": "open"}, {"sym": "BUSDT", "at": at, "state": "open"},
                {"sym": "CUSDT", "at": at, "state": "open"}]
        state = {"CUSDT": {"bybit": [{"t": int(at * 1000), "long": 0.50}, {"t": int((NOW - 60) * 1000), "long": 0.63}]}}
        news = [{"id": "n1", "t": int((NOW - H) * 1000), "src": "cd", "title": "A hacked", "tags": {"AUSDT": "cash"}}]
        setup(d, {"optimal": recs, "optimal_h": []}, news=news, state=state)
        G.write_rows([{"t": at + 60, "kind": "entry", "branch": "ai_news", "key": G.key_of("optimal", r),
                       "decision": "open"} for r in recs])
        G.CTX.crowd_of = lambda st, sym, t_ms: ({"bybit": {"now": [x for x in st[sym]["bybit"] if x["t"] <= t_ms][-1]["long"]}}
                                                if sym in st else None)
        c = Client(lambda k, dd: "close" if dd["sym"] == "AUSDT" else "hold")
        s = G.run(log=lambda *a: None, client=c, now=NOW)
        rs = rows_of()
        holds = {r["sym"]: r for r in rs if r["kind"] == "hold"}
        assert set(holds) == {"AUSDT", "CUSDT"}, holds.keys()
        assert holds["AUSDT"]["decision"] == "close" and holds["AUSDT"]["trigger"] == ["news:1"]
        assert holds["CUSDT"]["trigger"][0].startswith("crowd:0.500->0.630")
        hb = [r for r in rs if r["kind"] == "heartbeat"]
        assert [r["sym"] for r in hb] == ["BUSDT"] and hb[0]["no_verdict"] is None, "без события — heartbeat без модели"
        assert s["today"]["closes"] == 1
        n1 = c.n
        G.run(log=lambda *a: None, client=c, now=NOW + 900)
        assert c.n == n1, "закрытая не спрашивается, событие не повторяется, сдвиг толпы — от новой опоры"
        os.utime(G.NEWS_LATEST, (NOW - 3 * H, NOW - 3 * H))
        G.run(log=lambda *a: None, client=c, now=NOW + 7 * H)
        hb2 = [r for r in rows_of() if r["kind"] == "heartbeat" and r["t"] == NOW + 7 * H]
        assert hb2 and all(r["no_verdict"] == "фон не свеж" for r in hb2), "несвежий фон — не «ничего не случилось»"
        open(G.TRAIN_WAIT, "w").write("1"); os.utime(G.TRAIN_WAIT, (NOW + 8 * H - 60,) * 2)
        assert G.run(log=lambda *a: None, client=c, now=NOW + 8 * H).get("skipped")
        os.utime(G.TRAIN_WAIT, (NOW + 8 * H - 2 * H,) * 2)
        assert not G.run(log=lambda *a: None, client=c, now=NOW + 8 * H).get("skipped"), "застрявший флаг — не уступать"
    print("ok  сторож: модель — по новости и сдвигу толпы; без события heartbeat; несвежий фон назван; обучение — уступает")


if __name__ == "__main__":
    test_entries_once_window_repeat_budget()
    test_watcher_events_heartbeat_stale_and_yield()
    print("\nвсе 2 проверки прошли")
