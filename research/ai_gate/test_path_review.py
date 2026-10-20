#!/usr/bin/env python3
"""Прогон разбора путей (U0): разбираются только ЗАКРЫТЫЕ с дня рождения;
строка ложится в файл дня выхода и второй раз не считается; позиция без
баров записана как «не измерено», а не пропущена; уровни книги едут
числами. Источники — подставные."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import json
from types import SimpleNamespace as NS
import path_review as PR                                     # noqa: E402
import gate_run as G                                         # noqa: E402

H = 3600
T0 = G.GATE_SINCE + 5 * H


class Src:
    def __init__(self):
        self.calls = 0

    def bars(self, sym, t0, t1):
        self.calls += 1
        if sym == "DRYUSDT":
            return []
        out, t, px = [], t0, 1.0
        while t <= t1:
            px = 1.0 + 0.2 * ((t - t0) / (t1 - t0))          # ровно вверх на 20 % (пол шорта ≈ +18.6 %)
            out.append([t, px, px * 1.001, px * 0.999, px, 1.0])
            t += 60
        return out


class Mkt:
    def move(self, sym, t0, t1):
        return 0.1

    def wave(self, t0, t1):
        return 0.02


def rec(sym, at, state="closed", side="short"):
    return {"sym": sym, "at": at, "exit_ts": at + 2 * H, "state": state, "side": side, "lev": 10.0,
            "entry_px": 1.0, "pnl": -0.9, "exit": "пол", "fav_bp": -500,
            "fills": [[at, 1.0, 0.25]], "margin": 25.0}


class Client:
    """Подставная модель: отвечает разбором «wrong» с уроком."""
    def __init__(self):
        self.n = 0
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.n += 1
        body = json.dumps({"verdict": "wrong", "confidence": 0.7, "failed": "crowd_positioning", "saved": "",
                           "lesson": {"when": "L/S < 0.3", "do": "skip", "why": "squeeze"}, "notes": "n"})
        return NS(model="claude-opus-5-5", stop_reason="end_turn", content=[NS(type="text", text=body)],
                  usage=NS(input_tokens=4000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                  _request_id="r")


def test_reviews():
    """Разбор судьёй: только сделки с решением ai_news моделью; один раз на
    ключ; досье из записи, без досье — помечено; забор суток общий с входами."""
    with tempfile.TemporaryDirectory() as d:
        PR.REVIEWS, PR.LATEST = os.path.join(d, "reviews"), os.path.join(d, "latest.json")
        G.DECISIONS, G.RECORD = os.path.join(d, "dec"), os.path.join(d, "rec")
        books = {"optimal_h": [rec("AAAUSDT", T0), rec("BBBUSDT", T0), rec("HELDUSDT", T0), rec("NOVUSDT", T0)],
                 "optimal": []}
        k = {s: G.key_of("optimal_h", r) for s, r in ((r["sym"], r) for r in books["optimal_h"])}
        G.write_rows([{"t": T0 + 60, "kind": "entry", "branch": "ai_news", "key": k["AAAUSDT"], "decision": "open",
                       "confidence": 0.6, "reasons": ["calm"], "news_used": [], "cost_usd": 0.02},
                      {"t": T0 + 60, "kind": "entry", "branch": "ai_news", "key": k["BBBUSDT"], "decision": "skip",
                       "confidence": 0.6, "reasons": ["crowd"], "news_used": [], "cost_usd": 0.02},
                      {"t": T0 + 60, "kind": "entry", "branch": "ai_news", "key": k["HELDUSDT"], "decision": "held"},
                      {"t": T0 + 60, "kind": "entry", "branch": "ai_news", "key": k["NOVUSDT"], "decision": "open",
                       "no_verdict": "бюджет суток"}],
                     full=[{"branch": "ai_news", "key": k["AAAUSDT"], "dossier": {"symbol": "AAAUSDT", "crowd_positioning": {"x": 1}}}])
        c = Client()
        s = PR.run(log=lambda *a: None, now=T0 + 3 * 3600, src=Src(), mkt=Mkt(), books=books, client=c)
        rv = [r for r in G.read_decisions() if r.get("kind") == "review"]
        assert c.n == 2 and {r["sym"] for r in rv} == {"AAAUSDT", "BBBUSDT"}, (c.n, rv)
        a = next(r for r in rv if r["sym"] == "AAAUSDT")
        assert a["verdict"] == "wrong" and a["lesson"]["do"] == "skip" and a["dossier_found"] is True and a["decision"] == "open"
        b = next(r for r in rv if r["sym"] == "BBBUSDT")
        assert b["dossier_found"] is False and b["cost_usd"] > 0, "без досье в записи — разобрано и помечено"
        assert s["reviews"]["done"] == 2 and s["reviews"]["no_dossier"] == 1
        PR.run(log=lambda *a: None, now=T0 + 4 * 3600, src=Src(), mkt=Mkt(), books=books, client=c)
        assert c.n == 2, "второй раз не разбирается"
        # забор суток: потрачено ≥ предела — разбор пишется «неясно» с пометкой, модель не зовётся
        G.write_rows([{"t": T0 + 5 * 3600, "kind": "entry", "branch": "ai_news", "key": "optimal_h|ZZZUSDT|1",
                       "decision": "open", "cost_usd": 100.0}])
        books["optimal_h"].append(rec("CCCUSDT", T0 + 3600))
        G.write_rows([{"t": T0 + 3660, "kind": "entry", "branch": "ai_news", "key": G.key_of("optimal_h", books["optimal_h"][-1]),
                       "decision": "open", "confidence": 0.6, "reasons": [], "news_used": [], "cost_usd": 0.0}])
        s3 = PR.run(log=lambda *a: None, now=T0 + 6 * 3600, src=Src(), mkt=Mkt(), books=books, client=c)
        assert c.n == 2 and s3["reviews"]["budget_stop"] == 1
        cc = next(r for r in G.read_decisions() if r.get("kind") == "review" and r["sym"] == "CCCUSDT")
        assert cc["verdict"] == "unclear" and cc["no_verdict"] == "бюджет суток"
    print("ok  разбор судьёй: только решённые моделью, один раз, досье из записи или помечено, забор суток общий")


def main():
    with tempfile.TemporaryDirectory() as d:
        PR.REVIEWS, PR.LATEST = os.path.join(d, "reviews"), os.path.join(d, "latest.json")
        G.DECISIONS, G.RECORD = os.path.join(d, "dec"), os.path.join(d, "rec")
        books = {"optimal_h": [rec("AAAUSDT", T0), rec("DRYUSDT", T0 + H), rec("OPENUSDT", T0, state="open"),
                               rec("OLDUSDT", G.GATE_SINCE - 2 * H)],
                 "optimal": []}
        src, log = Src(), []
        s = PR.run(log=log.append, now=T0 + 3 * H, src=src, mkt=Mkt(), books=books, do_review=False)
        rows = PR.read_paths()
        assert {r["sym"] for r in rows} == {"AAAUSDT", "DRYUSDT"}, rows
        a = next(r for r in rows if r["sym"] == "AAAUSDT")
        assert a["path"]["shape"] == "straight_against" and abs(a["path"]["mae"] - 0.2 * 1.001) < 2e-3, a["path"]
        assert a["path"]["market_move"] == 0.02 and a["path"]["name_move"] == 0.1 and a["path"]["life_share"] == round(2 / 24, 3)
        assert a["floor_px"] is not None and a["take_px"] is not None, "уровни книги едут числами"
        assert a["path"]["first_touch"] == "floor", a["path"]
        dry = next(r for r in rows if r["sym"] == "DRYUSDT")
        assert dry["path"]["shape"] == "no_bars" and "не измерен" in dry["words"]
        assert s["last_pass"]["new"] == 2 and s["last_pass"]["no_bars"] == 1 and s["total"]["n"] == 2
        n = src.calls
        s2 = PR.run(log=log.append, now=T0 + 4 * H, src=src, mkt=Mkt(), books=books, do_review=False)
        assert src.calls == n and s2["last_pass"]["new"] == 0 and PR.read_paths().__len__() == 2, "второй раз не считается"
    print("ok  разбор путей: только закрытые с дня рождения, один раз, без баров — названо, уровни числами")
    test_reviews()
    print("\nвсе 2 проверки прошли")


if __name__ == "__main__":
    main()
