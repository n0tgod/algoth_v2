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
    G.MODEL_REGISTRY = os.path.join(tmp, "model_books.json")      # книг модели в подделке нет
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


def test_held_name_is_not_asked():
    """Повтор по имени, которое ветка держит, модели не показывается: книга
    выбросит его правилом «одно имя — одна позиция» (владелец 20.10: 89 из
    105 вызовов были такими). Держит ли — у КАЖДОЙ ветки по её решениям:
    отклонённый ранний вход освобождает имя в том же проходе."""
    with tempfile.TemporaryDirectory() as d:
        t0 = NOW - 4 * H

        def r(sym, at, fwd=-50.0):
            return {"sym": sym, "at": at, "exit_ts": at + 24 * H, "state": "open", "lev": 5.0, "fwd": fwd}
        recs = [r("CTUSDT", t0), r("CTUSDT", t0 + H), r("CTUSDT", t0 + 2 * H), r("XNYUSDT", t0 + H)]
        setup(d, {"optimal": [], "optimal_h": recs})
        seen = []

        def decide(kind, dd):
            seen.append((dd["sym"], dd["news"] is not None))
            # вход CT в t0: ветка с новостями отклоняет, без новостей открывает
            if dd["sym"] == "CTUSDT" and len([x for x in seen if x[0] == "CTUSDT" and x[1]]) == 1 and dd["news"] is not None:
                return "skip"
            return "open"
        c = Client(decide)
        st = G.run(log=lambda *a: None, client=c, now=NOW)
        rs = [x for x in rows_of() if x["kind"] == "entry"]
        by = {(x["branch"], x["key"]): x for x in rs}
        k = [G.key_of("optimal_h", x) for x in recs]
        assert by[("ai_news", k[0])]["decision"] == "skip" and by[("ai_plain", k[0])]["decision"] == "open"
        # CT t0+H: ветка с новостями имя НЕ держит (отклонила) — модель спрошена;
        # ветка без новостей держит (t0) — строка «held» без вызова
        assert by[("ai_news", k[1])]["decision"] == "open" and by[("ai_news", k[1])].get("held_by") is None
        assert by[("ai_plain", k[1])]["decision"] == "held" and by[("ai_plain", k[1])]["held_by"] == k[0]
        # CT t0+2H: держат обе ветки (news — с t0+H, plain — с t0)
        assert by[("ai_news", k[2])]["decision"] == "held" and by[("ai_news", k[2])]["held_by"] == k[1]
        assert by[("ai_plain", k[2])]["held_by"] == k[0]
        assert by[("ai_news", k[3])]["decision"] == "open", "другое имя судится"
        calls = c.n
        assert calls == 2 + 1 + 2 + sum(1 for x in rs if x["branch"] == "ai_news_repeat"), (calls, seen)
        assert all(x.get("cost_usd") == 0.0 for x in rs if x["decision"] == "held")
        assert st["today"]["entries"] == 3 and st["today"]["held"] == 1, st["today"]
        G.run(log=lambda *a: None, client=c, now=NOW + 60)
        assert c.n == calls, "второй проход ни решённых, ни «held» не судит"
    print("ok  повтор по держимому имени не судится: у каждой ветки своё «держит», отказ освобождает имя в том же проходе")


def test_learn_branch():
    """ai_learn — только с её дня рождения; в досье — похожие закрытые случаи
    ДО момента входа и принятые уроки; своё «держит имя»; прежние ветки
    решаются как прежде."""
    import lessons as LS
    with tempfile.TemporaryDirectory() as d:
        now = G.LEARN_SINCE + 3 * H
        recs = [{"sym": "OLDUSDT", "at": G.LEARN_SINCE - H, "state": "open", "exit_ts": G.LEARN_SINCE + 23 * H, "lev": 5.0},
                {"sym": "NEWUSDT", "at": G.LEARN_SINCE + H, "state": "open", "exit_ts": G.LEARN_SINCE + 25 * H, "lev": 5.0}]
        setup(d, {"optimal": [], "optimal_h": recs})
        G.CTX.build = lambda kind, r, book, side, now, recs, st, mr, ev, nw: (
            {"px": None, "crowd": {"bybit": {"now": 0.31}}}, [], {"px": False})
        seen = []
        G.J.ask_learn = lambda c, dd: (seen.append(dd), fake_ask(c, "entry", dd))[1]
        past = [{"key": "k1", "sym": "NEWUSDT", "side": "short", "at": G.LEARN_SINCE - 30 * H, "decision": "open",
                 "pnl": -0.44, "exit": "пол", "exit_ts": G.LEARN_SINCE - 28 * H, "path_words": "straight against",
                 "f": {"crowd_positioning.bybit.now": 0.3}, "review": {"verdict": "unclear", "failed": "", "saved": ""}},
                {"key": "k2", "sym": "FUTUSDT", "side": "short", "at": G.LEARN_SINCE, "decision": "open",
                 "pnl": 0.2, "exit": "тейк", "exit_ts": G.LEARN_SINCE + 2 * H + 1800, "path_words": "x",
                 "f": {"crowd_positioning.bybit.now": 0.31}, "review": None}]
        LS.cases = lambda decisions=None, dossiers=None, paths=None: past
        LS.LESSONS = os.path.join(d, "lessons.json")
        json.dump({"accepted": [{"text": "crowded short", "when": [{"field": "crowd_positioning.bybit.now", "op": "<", "value": 0.3}],
                                 "why": "w", "test": {"all": {"matched": 30, "mean_matched": -0.2, "mean_rest": 0.05}}}]},
                  open(LS.LESSONS, "w"))
        c = Client(lambda k, dd: "open")
        G.run(log=lambda *a: None, client=c, now=now)
        rs = [x for x in rows_of() if x["kind"] == "entry"]
        learn = [x for x in rs if x["branch"] == "ai_learn"]
        assert [x["sym"] for x in learn] == ["NEWUSDT"], "до дня рождения ai_learn не судит"
        assert len(seen) == 1 and seen[0]["accepted_lessons"][0]["rule"] == "crowded short"
        sim = seen[0]["similar_past_cases"]
        assert [x["symbol"] for x in sim] == ["NEWUSDT"], ("случай, вышедший ПОСЛЕ входа, не виден", sim)
        assert sim[0]["exit"] == "пол" and sim[0]["own_review"]["verdict"] == "unclear"
        om = seen[0]["own_mistakes"]
        assert om["rejected"]["n"] == 0 and om["accepted"]["n"] == 1 and om["rejected_wrongly"] == [], \
            ("свои ошибки: только вышедшие ДО входа, обе стороны счёта", om)
        assert {x["branch"] for x in rs if x["sym"] == "OLDUSDT"} == {"ai_news", "ai_plain"}
    print("ok  ai_learn: с дня рождения; похожие случаи только вышедшие до входа; уроки в досье; прежние ветки как прежде")


if __name__ == "__main__":
    test_entries_once_window_repeat_budget()
    test_watcher_events_heartbeat_stale_and_yield()
    test_held_name_is_not_asked()
    test_learn_branch()
    print("\nвсе 4 проверки прошли")
