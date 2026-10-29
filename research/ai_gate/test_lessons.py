#!/usr/bin/env python3
"""Уроки (U2): калибровочная пара — подсаженное правило принимается, правило
на шуме — нет; половина, где эффекта нет, роняет приём; поле вне каталога и
не-skip отвергаются формой; модель — подставная; принятый урок, переставший
работать, отзывается; уроки словами для учащейся ветки."""
import json
import os
import random
import sys
import tempfile
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lessons as L                                          # noqa: E402

T0 = 1_792_400_000.0


def synth(n=200, seed=1, planted=True, second_half=True, good=False, rejected_good=True):
    """`good`: подсаженное ХОРОШЕЕ подмножество (x > 0.8 → +0.40), которое
    судья отклонял (`rejected_good`) — материал для правила take."""
    rng = random.Random(seed)
    cs = []
    for i in range(n):
        x, y = rng.random(), rng.random()
        bad = planted and x < 0.3 and (second_half or i < n // 2)
        nice = good and x > 0.8
        pnl = (-0.40 if bad else 0.40 if nice else 0.05) + rng.gauss(0, 0.08)
        dec = "skip" if (nice and rejected_good) else "open"
        cs.append({"key": f"k{i}", "sym": f"S{i}USDT", "side": "short", "at": T0 + i * 3600, "decision": dec,
                   "reasons": ["crowd long-heavy"] if dec == "skip" else [], "confidence": 0.6,
                   "pnl": pnl, "exit": "пол" if bad else "тейк" if nice else "срок", "exit_ts": T0 + i * 3600 + 7200,
                   "path_words": "p", "f": {"crowd_positioning.bybit.now": x, "market.fng": y},
                   "review": {"verdict": "wrong" if (nice and rejected_good and i % 2) else "unclear"}})
    return cs


class Client:
    def __init__(self, rules):
        self.rules, self.n = rules, 0
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.n += 1
        self.kw = kw
        body = json.dumps({"rules": self.rules, "notes": "n"})
        return NS(model="claude-opus-5-5", stop_reason="end_turn", content=[NS(type="text", text=body)],
                  usage=NS(input_tokens=9000, output_tokens=800, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                  _request_id="r")


R_PLANT = {"text": "crowded short", "when": [{"field": "crowd_positioning.bybit.now", "op": "<", "value": 0.3}],
           "do": "skip", "why": "squeeze"}
R_NOISE = {"text": "fear", "when": [{"field": "market.fng", "op": "<", "value": 0.3}], "do": "skip", "why": "noise"}
R_TAKE = {"text": "take crowded long", "when": [{"field": "crowd_positioning.bybit.now", "op": ">", "value": 0.8}],
          "do": "take", "why": "longs get squeezed"}
R_TAKE_NOISE = {"text": "take greed", "when": [{"field": "market.fng", "op": ">", "value": 0.7}], "do": "take", "why": "noise"}


def test_take():
    """Правило take: подсаженное хорошее подмножество, которое судья отклонял,
    принимается; шум — нет; то же подмножество, которое судья и так брал, не
    принимается (правило ничего не меняет); эффект, пропавший на второй
    половине, роняет приём; отзыв — когда подходящие перестали быть лучше."""
    cs = synth(good=True)
    t = L.test_rule(R_TAKE, cs)
    assert t["passed"] and t["all"]["rejected_matched"] >= L.MIN_TAKE_REJECTED \
        and t["first"]["mean_matched"] > t["first"]["mean_rest"] and t["first"]["p_random"] <= L.P_MAX, t
    assert not L.test_rule(R_TAKE_NOISE, cs)["passed"], "шум не принимается"
    t2 = L.test_rule(R_TAKE, synth(good=True, rejected_good=False))
    assert not t2["passed"] and t2["why"].startswith("отклонённых среди подходящих"), t2
    half = synth(good=True)
    for c in half[len(half) // 2:]:
        if c["f"]["crowd_positioning.bybit.now"] > 0.8:
            c["pnl"] -= 0.6
    t3 = L.test_rule(R_TAKE, half)
    assert not t3["passed"] and t3["why"] == "вторая половина не держит", t3
    # skip-правило с тем же условием — другой урок (id различаются), и оно не принимается
    assert L.rule_id(R_TAKE) != L.rule_id(dict(R_TAKE, do="skip"))
    assert not L.test_rule(dict(R_TAKE, do="skip"), cs)["passed"]
    cat = L.catalog(cs)
    assert L.valid(R_TAKE, cat) is None and L.valid(dict(R_TAKE, do="open"), cat).startswith("проверяемы")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "lessons.json")
        c = Client([R_TAKE, R_TAKE_NOISE])
        out = L.run(log=lambda *a: None, now=T0 + 300 * 3600, client=c, cs=cs, path=path)
        stt = json.load(open(path))
        assert [(r["text"], r["do"]) for r in stt["accepted"]] == [("take crowded long", "take")], stt["accepted"]
        assert [r["text"] for r in stt["proposed"]] == ["take greed"]
        sent = json.loads(c.kw["messages"][0]["content"])
        rw = sent["rejected_went_well"]
        assert rw and all(x["result_on_margin_if_taken"] > 0 and x["reasons_given_then"] for x in rw), "модель видит зря отклонённые с доводами"
        assert L.lessons_text(stt)[0]["do"] == "take"
        rep = out["report"]
        assert "брать | take crowded long" in rep and "## Отклонено зря" in rep and "crowd long-heavy" in rep, rep
        assert out["rejected"]["n"] == sum(1 for x in cs if x["decision"] == "skip") and out["rejected"]["went_well"] > 0
        # мера обучения: ветка ai_learn судила подходящие входы после приёма — сколько всё же отклонила
        dec = [{"kind": "entry", "branch": "ai_learn", "key": x["key"], "decision": "skip" if i % 3 else "open"}
               for i, x in enumerate(cs) if x["decision"] == "skip"]
        stt["accepted"][0]["accepted_at"] = "2000-01-01T00:00:00Z"
        tv = L.learn_still_rejects(stt, cs, dec)
        assert tv[0]["learn_judged"] == len(dec) and tv[0]["learn_rejected"] == sum(1 for x in dec if x["decision"] == "skip"), tv
        # подходящие перестали быть лучше — отзыв
        flip = synth(good=True, seed=5)
        for x in flip:
            if x["f"]["crowd_positioning.bybit.now"] > 0.8:
                x["pnl"] -= 0.8
        out3 = L.run(log=lambda *a: None, now=T0 + 302 * 3600, client=Client([]), cs=flip, path=path)
        assert out3["revoked_now"] == ["take crowded long"], out3["revoked_now"]
    print("ok  правило take: подсаженное принято, шум и «и так брали» — нет, половина роняет; зря отклонённые в промпте и отчёте; отзыв")


def test_mistakes():
    """Свои ошибки до момента решения: только вышедшие раньше `at_s` и не
    старше окна; зря отклонённые — в плюсе или «wrong» в разборе; с доводами
    тогда; счёт отклонённых и принятых за окно."""
    cs = synth(n=60, good=True)
    at = cs[40]["at"]
    m = L.mistakes(cs, at, days=1)
    win = [c for c in cs if at - 86400 <= c["exit_ts"] < at]
    assert m["rejected"]["n"] == sum(1 for c in win if c["decision"] == "skip") \
        and m["accepted"]["n"] == sum(1 for c in win if c["decision"] == "open") and m["rejected"]["n"] + m["accepted"]["n"] == len(win)
    assert m["rejected_wrongly"] and len(m["rejected_wrongly"]) <= L.MISTAKE_K
    for x in m["rejected_wrongly"]:
        assert x["reasons_given_then"] == ["crowd long-heavy"] and x["result_on_margin_if_taken"] > 0
    seen = {x["entered_utc"] for x in m["rejected_wrongly"]}
    future = {L._utc(c["at"]) for c in cs if c["exit_ts"] >= at}
    assert not (seen & future), "будущее в своих ошибках не видно"
    assert L.mistakes(cs, cs[0]["at"])["rejected"]["n"] == 0 and L.mistakes(cs, cs[0]["at"])["rejected_wrongly"] == []
    # отклонённый в минусе, но признанный в разборе ошибкой — тоже своя ошибка
    one = [{"key": "z", "sym": "ZUSDT", "side": "short", "at": T0, "decision": "skip", "reasons": ["r"], "pnl": -0.1,
            "exit": "срок", "exit_ts": T0 + 3600, "path_words": "p", "f": {}, "review": {"verdict": "wrong", "failed": "f"}}]
    mm = L.mistakes(one, T0 + 7200)
    assert mm["rejected_wrongly"][0]["own_review"]["verdict"] == "wrong" and mm["rejected"]["went_well"] == 0
    print("ok  свои ошибки: без будущего, в окне, с тогдашними доводами; счёт обеих сторон")


def main():
    cs = synth()
    t = L.test_rule(R_PLANT, cs)
    assert t["passed"] and t["first"]["matched"] >= L.MIN_HALF and t["first"]["p_random"] <= L.P_MAX, t
    tn = L.test_rule(R_NOISE, cs)
    assert not tn["passed"], ("шум не принимается", tn)
    t2 = L.test_rule(R_PLANT, synth(second_half=False))
    assert not t2["passed"] and t2["why"] == "вторая половина не держит", t2
    cat = L.catalog(cs)
    assert L.valid({"do": "skip", "when": [{"field": "nope", "op": "<", "value": 1}]}, cat).startswith("поля")
    assert L.valid({"do": "open", "when": R_PLANT["when"]}, cat) == "проверяемы только правила skip и take"
    assert L.valid({"do": "skip", "when": [{"field": "market.fng", "op": "==", "value": 1}]}, cat).startswith("знак")
    f = L.fields_of({"crowd_positioning": {"bybit": {"now": 0.3, "24h_ago": 0.4}},
                     "name_history_in_book": {"positions_before": 10, "hit_floor": 3},
                     "news_on_this_coin_72h": [{"x": 1}], "symbol": "X"})
    assert abs(f["derived.crowd_bybit_shift_24h"] + 0.1) < 1e-9 and f["derived.name_floor_share"] == 0.3
    assert not any(k.startswith("news") for k in f), "новости в поля уроков не идут"
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "lessons.json")
        bad = {"text": "x", "when": [{"field": "nope", "op": "<", "value": 1}], "do": "skip", "why": ""}
        c = Client([R_PLANT, R_NOISE, bad])
        out = L.run(log=lambda *a: None, now=T0 + 300 * 3600, client=c, cs=cs, path=path)
        stt = json.load(open(path))
        assert c.n == 1 and out["new_rules"] == 2 and out["invalid"][0]["why"].startswith("поля")
        assert [r["text"] for r in stt["accepted"]] == ["crowded short"] and [r["text"] for r in stt["proposed"]] == ["fear"]
        assert stt["version"] == 1 and "crowded short" in out["report"]
        sent = json.loads(c.kw["messages"][0]["content"])
        assert sent["field_catalog"] and "reviews_last_week" in sent, "модель видит каталог и разборы недели"
        lt = L.lessons_text(stt)
        assert lt[0]["rule"] == "crowded short" and "crowd_positioning.bybit.now < 0.3" in lt[0]["when"]
        # повтор того же правила не плодится
        out2 = L.run(log=lambda *a: None, now=T0 + 301 * 3600, client=Client([R_PLANT]), cs=cs, path=path)
        assert out2["new_rules"] == 0
        # эффект перевернулся на всей выборке (подходящие ЛУЧШЕ остальных) — урок отзывается
        flip = synth(planted=False, seed=3)
        for c in flip:
            if c["f"]["crowd_positioning.bybit.now"] < 0.3:
                c["pnl"] += 0.3
        out3 = L.run(log=lambda *a: None, now=T0 + 302 * 3600, client=Client([]), cs=flip, path=path)
        st3 = json.load(open(path))
        assert out3["revoked_now"] == ["crowded short"] and st3["accepted"] == [] \
            and st3["revoked"][0]["text"] == "crowded short" and st3["version"] == 2, (out3["revoked_now"], st3["version"])
        # мало случаев — ошибка словами, без модели
        c4 = Client([R_PLANT])
        out4 = L.run(log=lambda *a: None, now=T0, client=c4, cs=cs[:10], path=path)
        assert out4.get("error", "").startswith("случаев") and c4.n == 0
    print("ok  уроки: подсаженное принято, шум — нет, половина без эффекта роняет приём; форма проверяется; отзыв; уроки словами")
    test_take()
    test_mistakes()
    print("\nвсе 3 проверки прошли")


if __name__ == "__main__":
    main()
