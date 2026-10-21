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
    def __init__(self, rules):
        self.rules, self.kw = rules, None
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.kw = kw
        return NS(model="claude-opus-5-5", stop_reason="end_turn",
                  content=[NS(type="text", text=json.dumps({"rules": self.rules, "notes": "n"}))],
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
        c = Client([good, bad_field, bad_w])
        r = P.run(log=lambda *a: None, client=c, paths=paths, rules_file=rf, catalog=cat, last_search={"fold_1to2": {}})
        assert len(r["new"]) == 1 and r["new"][0]["W"] == 4, r
        assert sorted(x["why"] for x in r["invalid"]) == ["окно вне 1–6 ч", "поля 'moon_phase' нет в каталоге"], r["invalid"]
        sent = json.loads(c.kw["messages"][0]["content"])
        assert sent["field_catalog"] == cat and "path_summary" in sent and "last_search" in sent
        r2 = P.run(log=lambda *a: None, client=Client([good]), paths=paths, rules_file=rf, catalog=cat, last_search={})
        assert r2["new"] == [] and len(json.load(open(rf))["rules"]) == 1, "повтор не пишется, файл дописывается"
    print("ok  правила модели: каталог, пути и поиск — модели; форма и повтор — кодом; файл правил дописывается")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
