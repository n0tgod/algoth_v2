#!/usr/bin/env python3
"""Ядро судьи: разбор ответа (вне словаря и не JSON — отказ, не мнение),
цена по модели, которая ответила; досье без новостей НЕ содержит блоков
новостей (ветка ai_plain); ход цены по часам; новости — только до момента
решения и только по имени; вызов через подставной клиент — успех, отказ
модели, ответ вне схемы, обрыв связи; ключ в строку журнала не попадает."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import judge as J                                            # noqa: E402


def test_parse_and_cost():
    v, why = J.parse_verdict("end_turn", json.dumps({"decision": "skip", "confidence": 0.7,
                                                     "reasons": ["a", "b", "c", "d"], "news_used": ["n1"]}),
                             ("open", "skip"))
    assert why is None and v["decision"] == "skip" and v["reasons"] == ["a", "b", "c"]
    assert J.parse_verdict("refusal", "", ("open", "skip"))[1].startswith("отказ модели")
    assert J.parse_verdict("max_tokens", "{", ("open", "skip"))[1] == "ответ оборван по длине"
    assert J.parse_verdict("end_turn", "нет", ("open", "skip"))[1] == "ответ не JSON"
    assert J.parse_verdict("end_turn", '{"decision": "close"}', ("open", "skip"))[1] == "решение вне словаря"
    c = J.cost_usd({"input_tokens": 3000, "output_tokens": 500}, "claude-opus-5-5")
    assert abs(c - (3000 * 4 + 500 * 20) / 1e6) < 1e-9, c
    assert J.cost_usd({"input_tokens": 1}, "unknown-model") is None, "неизвестная модель — не ноль"
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "k.txt")
        assert J.read_key(p) is None
        open(p, "w").write("garbage\n"); assert J.read_key(p) is None
        open(p, "w").write("sk-ant-abc\n"); assert J.read_key(p) == "sk-ant-abc"
    print("ok  ответ вне схемы — отказ; цена по ответившей модели; ключ только нужной формы")


def test_dossier_moves_news():
    H = 3600
    at = 1_790_000_000 // H * H + 600
    closes = {at // H * H - n * H: 100.0 * (1 + 0.01 * n) for n in range(0, 200)}
    m = J.moves(closes, at)
    assert m["1h_pct"] == round(100 * (100 / 101 - 1), 2) and m["168h_pct"] is not None
    assert J.moves({}, at) is None
    items = [{"id": "a", "t": (at - 10) * 1000, "src": "cd", "title": "A", "text": "x", "tags": {"ABCUSDT": "cash"}},
             {"id": "b", "t": (at + 10) * 1000, "src": "cd", "title": "B", "tags": {"ABCUSDT": "cash"}},
             {"id": "c", "t": (at - 10) * 1000, "src": "cd", "title": "C", "tags": {"XYZUSDT": "word"}}]
    nw = J.news_for(items, "ABCUSDT", at * 1000)
    assert [x["id"] for x in nw] == ["a"], "будущее и чужие имена не попадают"
    rec = {"sym": "ABCUSDT", "lev": 3.0, "fav_bp": 50, "exit": "пол", "state": "closed", "secret": 1}
    d_news = J.dossier("entry", rec, "optimal", "long", at, news=nw, mkt_news=[])
    d_plain = J.dossier("entry", rec, "optimal", "long", at, news=None)
    assert "news_on_this_coin_72h" in d_news and "news_on_this_coin_72h" not in d_plain
    assert "market_headlines_24h" not in d_plain, "ветка без новостей не видит и рыночных заголовков"
    assert d_plain["book_rules"] == {"lev": 3.0, "fav_bp": 50}, "исход позиции и посторонние поля в досье не идут"
    print("ok  досье: без новостей — без блоков новостей; исход позиции скрыт; новости до решения и по имени")


class FakeClient:
    def __init__(self, resp=None, exc=None):
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))
        self.resp, self.exc = resp, exc

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.resp


def _resp(text, stop="end_turn", model="claude-opus-5-5"):
    return NS(model=model, stop_reason=stop, content=[NS(type="thinking", thinking=""), NS(type="text", text=text)],
              usage=NS(input_tokens=2000, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0),
              _request_id="req_x")


def test_ask_paths():
    import anthropic
    fc = FakeClient(_resp(json.dumps({"decision": "skip", "confidence": 0.8, "reasons": ["delisting"], "news_used": []})))
    row = J.ask(fc, "entry", {"symbol": "X"})
    kw = fc.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"] == [J.FALLBACK_BETA]
    assert kw["output_config"]["effort"] == "medium" and kw["output_config"]["format"]["schema"]["properties"]["decision"]["enum"] == ["open", "skip"]
    assert "temperature" not in kw, "у модели выборка отклоняется — параметра нет"
    assert row["decision"] == "skip" and row["no_verdict"] is None and row["cost_usd"] == round((2000 * 4 + 300 * 20) / 1e6, 6)
    assert "sk-ant" not in json.dumps(row) and "api_key" not in row
    r2 = J.ask(FakeClient(_resp("", stop="refusal")), "entry", {})
    assert r2["decision"] == "open" and r2["no_verdict"].startswith("отказ модели"), "отказ — открыть с пометкой"
    r3 = J.ask(FakeClient(_resp('{"decision":"close","confidence":1,"reasons":[],"news_used":[]}')), "entry", {})
    assert r3["decision"] == "open" and r3["no_verdict"] == "решение вне словаря"
    r4 = J.ask(FakeClient(_resp('{"decision":"close","confidence":0.6,"reasons":["hack"],"news_used":["n"]}')), "hold", {})
    assert r4["decision"] == "close" and r4["no_verdict"] is None
    try:
        exc = anthropic.APIConnectionError(request=None)
    except TypeError:
        exc = None
    if exc is not None:
        r5 = J.ask(FakeClient(exc=exc), "hold", {})
        assert r5["decision"] == "hold" and r5["no_verdict"] == "нет связи с площадкой", r5
    print("ok  вызов: модель, усилие, схема и запасная модель заданы; отказ и ответ вне схемы — по умолчанию с пометкой")


def test_review():
    good = {"verdict": "wrong", "confidence": 0.7, "failed": "crowd_positioning", "saved": "",
            "lesson": {"when": "bybit L/S < 0.3 and 7d > +300 %", "do": "skip", "why": "squeeze running"},
            "notes": "x" * 500}
    v, why = J.parse_review("end_turn", json.dumps(good))
    assert why is None and v["verdict"] == "wrong" and v["lesson"]["do"] == "skip" and len(v["notes"]) == 400
    v2, _ = J.parse_review("end_turn", json.dumps(dict(good, lesson={"when": "", "do": "", "why": ""})))
    assert v2["lesson"] is None, "пустой урок — None, не пустые строки"
    assert J.parse_review("end_turn", '{"verdict": "maybe"}')[1] == "вердикт вне словаря"
    assert J.parse_review("refusal", "")[1].startswith("отказ модели")
    d = J.review_dossier({"symbol": "X", "crowd_positioning": {"bybit": 0.3}}, {"decision": "open", "confidence": 0.6,
                         "reasons": ["calm"], "news_used": [], "cost_usd": 0.02, "request_id": "r"},
                         {"exit": "пол", "pnl_on_margin": -0.44}, {"mae": 0.1})
    assert d["kind"] == "review" and d["my_decision"] == {"decision": "open", "confidence": 0.6, "reasons": ["calm"], "news_used": []}
    assert "cost_usd" not in json.dumps(d["my_decision"]) and d["dossier_at_decision"]["crowd_positioning"] == {"bybit": 0.3}
    fc = FakeClient(_resp(json.dumps(good)))
    row = J.ask_review(fc, d)
    kw = fc.calls[0]
    assert kw["system"] == J.SYSTEM_REVIEW and kw["output_config"]["format"]["schema"]["properties"]["verdict"]["enum"] == ["right", "wrong", "unclear"]
    assert row["kind"] == "review" and row["verdict"] == "wrong" and row["no_verdict"] is None and row["cost_usd"] > 0
    r2 = J.ask_review(FakeClient(_resp("", stop="refusal")), d)
    assert r2["verdict"] == "unclear" and r2["no_verdict"].startswith("отказ модели"), "отказ — «неясно» с пометкой"
    # прежняя дорога входа не изменилась
    r3 = J.ask(FakeClient(_resp('{"decision":"skip","confidence":0.8,"reasons":[],"news_used":[]}')), "entry", {})
    assert r3["decision"] == "skip" and r3["no_verdict"] is None
    print("ok  разбор: вердикт по словарю, урок пустой — None, досье разбора без цены и служебного; отказ — «неясно»")


if __name__ == "__main__":
    test_parse_and_cost()
    test_dossier_moves_news()
    test_ask_paths()
    test_review()
    print("\nвсе 4 проверки прошли")
