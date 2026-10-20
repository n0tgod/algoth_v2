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


def synth(n=200, seed=1, planted=True, second_half=True):
    rng = random.Random(seed)
    cs = []
    for i in range(n):
        x, y = rng.random(), rng.random()
        bad = planted and x < 0.3 and (second_half or i < n // 2)
        pnl = (-0.40 if bad else 0.05) + rng.gauss(0, 0.08)
        cs.append({"key": f"k{i}", "sym": f"S{i}USDT", "side": "short", "at": T0 + i * 3600, "decision": "open",
                   "pnl": pnl, "exit": "пол" if bad else "срок", "exit_ts": T0 + i * 3600 + 7200, "path_words": "p",
                   "f": {"crowd_positioning.bybit.now": x, "market.fng": y}, "review": {"verdict": "unclear"}})
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
    assert L.valid({"do": "open", "when": R_PLANT["when"]}, cat) == "проверяемы только правила skip"
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
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
