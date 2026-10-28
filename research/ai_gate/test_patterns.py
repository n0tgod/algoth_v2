#!/usr/bin/env python3
"""Правила модели (U4b, словарь поиска §11.8): модель видит каталог полей,
сводку путей и итог поиска; поле вне каталога, окно вне 1–6 и знак вне
словаря отвергаются формой; повтор по сигнатуре не пишется; файл правил
дописывается."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import patterns as P                                         # noqa: E402


class Client:
    def __init__(self, rules, exit_rules=()):
        self.rules, self.kw, self.exit_rules = rules, None, list(exit_rules)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.kw = kw
        return NS(model="claude-opus-5-5", stop_reason="end_turn",
                  content=[NS(type="text", text=json.dumps({"rules": self.rules, "exit_rules": self.exit_rules, "notes": "n"}))],
                  usage=NS(input_tokens=20000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                  _request_id="r")


def main():
    paths = [{"side": "short", "exit": "пол" if i % 3 == 0 else "срок", "pnl_frac": -0.4 if i % 3 == 0 else 0.1,
              "exit_ts": 1792000000 + i, "path": {"mae": 0.05, "mae_h": 1.5, "mfe": 0.1, "mfe_h": 10,
                                                  "first_touch": "none", "shape": "against_then_for"}} for i in range(60)]
    cat = {"crowd_bybit": {"cover": 1.0, "q10": 0.3, "q50": 0.5, "q90": 0.7},
           "funding": {"cover": 0.98, "q10": -0.0005, "q50": 0.0001, "q90": 0.0008}}
    good = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.35}, {"field": "funding", "op": "<=", "value": 0.0}],
            "W": 4, "why": "squeeze fuel already burnt"}
    bad_field = {"when": [{"field": "moon_phase", "op": "<=", "value": 1}], "W": 3, "why": ""}
    bad_w = {"when": [{"field": "funding", "op": ">=", "value": 0.0}], "W": 9, "why": ""}
    with tempfile.TemporaryDirectory() as d:
        rf = os.path.join(d, "r.json")
        xgood = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.35}], "exit": "s3:t2:book", "why": "small excursion"}
        xbook = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.35}], "exit": "s0:t2:book", "why": ""}
        xcell = {"when": [{"field": "funding", "op": ">=", "value": 0.0}], "exit": "s4:t2:book", "why": ""}
        c = Client([good, bad_field, bad_w], [xgood, xbook, xcell])
        r = P.run(log=lambda *a: None, client=c, paths=paths, rules_file=rf, catalog=cat, last_search={"fold_1to2": {}},
                  exit_state={"by_state": [{"field": "crowd_bybit", "tercile": 0, "exit": "s3:t2:book", "gain": 0.05, "held": True}]})
        assert len(r["new"]) == 1 and r["new"][0]["W"] == 4, r
        assert len(r["new_exit"]) == 1 and r["new_exit"][0]["exit"] == "s3:t2:book", r["new_exit"]
        assert sorted(x["why"] for x in r["invalid_exit"]) == ["выход книги — не правило", "выхода 's4:t2:book' нет в сетке"], r["invalid_exit"]
        assert c.kw["messages"][0]["content"] and json.loads(c.kw["messages"][0]["content"])["exit_by_state"]["by_state"][0]["exit"] == "s3:t2:book"
        assert "exit_rules" in c.kw["tools"][0]["input_schema"]["properties"] if c.kw.get("tools") else True
        assert sorted(x["why"] for x in r["invalid"]) == ["окно вне 1–6 ч", "поля 'moon_phase' нет в каталоге"], r["invalid"]
        sent = json.loads(c.kw["messages"][0]["content"])
        assert sent["field_catalog"] == cat and "path_summary" in sent and "last_search" in sent
        r2 = P.run(log=lambda *a: None, client=Client([good], [xgood]), paths=paths, rules_file=rf, catalog=cat, last_search={},
                   exit_state=None)
        assert r2["new"] == [] and r2["new_exit"] == [] and len(json.load(open(rf))["rules"]) == 1, "повтор не пишется"
        assert len(json.load(open(rf))["exit_rules"]) == 1, "правила выхода — своим списком"
    print("ok  правила модели: каталог, пути, поиск и выход по состоянию — модели; форма и повтор — кодом; правила выхода своим списком")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
