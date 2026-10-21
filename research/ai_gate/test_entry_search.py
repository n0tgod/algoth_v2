#!/usr/bin/env python3
"""Поиск ТВХ по состоянию (U4c): калибровочная пара — подсаженный параметр
(вход, когда доля лонгов упала ниже порога, даёт плюс, остальные часы —
минус) находится и держит на проверочной половине в обе стороны, а на
перемешанных параметрах отбор молчит; первый час по условиям и окно;
таблица исходов — подставная."""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import entry_search as ES                                    # noqa: E402


def synth(n=600, seed=3, planted=True):
    rng = np.random.default_rng(seed)
    K = ES.KMAX + 1
    names = ["crowd_bybit", "noise_a", "noise_b"]
    F = rng.uniform(0, 1, size=(n, K, len(names)))
    O = rng.normal(-0.01, 0.05, size=(n, K))
    if planted:
        good = F[:, :, 0] <= 0.25                      # толпа ушла в шорт — вход выгоден
        O = np.where(good, O + 0.12, O)
    at = np.arange(n) * 3600.0
    return names, F, O, at


def main():
    names, F, O, at = synth()
    rule = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.25}], "W": 3}
    ks = ES.first_k(F, names, rule)
    i = int(np.where(ks > 0)[0][0])
    assert F[i, ks[i], 0] <= 0.25 and all(F[i, k, 0] > 0.25 for k in range(ks[i])), "первый час по условию"
    assert all(k <= 3 for k in ks), "окно W"
    f1, f2 = ES.search(F, O, names, at, seed=1)
    assert f1["held"] and f2["held"], (f1.get("rule"), f1.get("test_mean"), f1.get("p_random_hour"), f2.get("rule"))
    assert f1["rule"]["when"][0]["field"] == "crowd_bybit" and f2["rule"]["when"][0]["field"] == "crowd_bybit"
    c1, c2 = ES.search(ES.shuffled(F, 9), O, names, at, seed=2)
    assert not (c1.get("held") and c2.get("held")), "на перемешанных параметрах отбор молчит"
    n2, F2, O2, at2 = synth(planted=False, seed=5)
    g1, g2 = ES.search(F2, O2, n2, at2, seed=3)
    assert not (g1.get("held") and g2.get("held")), "на шуме отбор молчит"
    r = ES.run(log=lambda *a: None, table={"names": names, "F": F, "O": O, "at": at, "n": len(at)})
    assert r["procedure_holds"] and r["candidate"]["rule"]["when"][0]["field"] == "crowd_bybit", r.get("candidate")
    assert "держит" in ES.report(r) or "**да**" in ES.report(r)
    print("ok  поиск ТВХ: подсаженный параметр найден и держит на проверке в обе стороны; перемешанные и шум — молчат")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
