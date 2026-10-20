#!/usr/bin/env python3
"""Паттерны пути (U4b): модель видит сводку путей и уже проверенное;
гипотеза вне словаря отвергается формой; повтор по параметрам не пишется;
файл гипотез дописывается, а не перезаписывается."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import patterns as P                                         # noqa: E402


class Client:
    def __init__(self, hyps):
        self.hyps, self.kw = hyps, None
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.kw = kw
        return NS(model="claude-opus-5-5", stop_reason="end_turn",
                  content=[NS(type="text", text=json.dumps({"hypotheses": self.hyps, "notes": "n"}))],
                  usage=NS(input_tokens=20000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                  _request_id="r")


def main():
    paths = [{"side": "short", "exit": "пол" if i % 3 == 0 else "срок", "pnl_frac": -0.4 if i % 3 == 0 else 0.1,
              "exit_ts": 1792000000 + i, "path": {"mae": 0.05 + 0.001 * i, "mae_h": 1.5, "mfe": 0.1, "mfe_h": 10,
                                                  "first_touch": "none", "shape": "against_then_for"}} for i in range(60)]
    good = {"kind": "pullback", "pct": 3.0, "within_h": 2.0, "after_h": 0, "why": "most trades go against ~3 % first"}
    dup = {"kind": "pullback", "pct": 2.0, "within_h": 3.0, "after_h": 0, "why": "same as grid"}
    bad = {"kind": "pullback", "pct": 40.0, "within_h": 2.0, "after_h": 0, "why": "too far"}
    with tempfile.TemporaryDirectory() as d:
        hf, sf = os.path.join(d, "h.json"), os.path.join(d, "s.json")
        c = Client([good, dup, bad])
        r = P.run(log=lambda *a: None, client=c, paths=paths, hyps_file=hf, shift_file=sf)
        assert [h["id"] for h in r["new"]] == ["pullback_3pct_2h"], r["new"]
        assert r["invalid"][0]["why"].startswith("порог")
        sent = json.loads(c.kw["messages"][0]["content"])
        assert sent["summary"]["by_exit"]["пол"]["n"] == 20 and any(t["id"] == "pullback_2pct_3h" for t in sent["already_tested"])
        r2 = P.run(log=lambda *a: None, client=Client([good]), paths=paths, hyps_file=hf, shift_file=sf)
        assert r2["new"] == [] and len(json.load(open(hf))["hypotheses"]) == 1, "повтор не пишется, файл дописывается"
        assert P.run(log=lambda *a: None, client=Client([good]), paths=paths[:10], hyps_file=hf, shift_file=sf)["error"].startswith("путей")
    print("ok  паттерны пути: сводка и проверенное — модели; форма и повтор отсекаются кодом; файл гипотез дописывается")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
