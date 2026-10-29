#!/usr/bin/env python3
"""Ранний выход по смене состояния (§11.11): калибровочная пара — подсаженное
поле (после роста открытого интереса позиция дальше теряет: закрыть в тот час
выгодно) находится и держит обе половины, правило модели на нём проходит,
правило на шуме — нет; позиция, уже вышедшая, закрыться не может; таблица
строится из записей с отметками через то же закрытие, что у сторожа."""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import close_search as CS                                    # noqa: E402

H = 3600.0


def synth(n=500, seed=4):
    rng = np.random.default_rng(seed)
    names = ["oi_1h", "noise_a"]
    K = CS.HMAX + 1
    F = rng.uniform(-0.05, 0.05, size=(n, K, len(names)))
    final = np.zeros(n)
    M = np.full((n, K), np.nan)
    for i in range(n):
        path = 0.0
        hit = False
        for h in range(1, K):
            path += rng.normal(0, 0.01)
            if not hit and F[i, h, 0] >= 0.048:            # редкое событие: ~37 % позиций за 23 ч
                hit = True
                M[i, h] = path + 0.03          # закрыть В ЭТОТ час — плюс; раньше или позже — путь как есть
                continue
            M[i, h] = path
        final[i] = path
    M[:40, 6:] = np.nan                        # сорок позиций вышли на 6-м часе
    at = np.arange(n) * 3600.0 * 1.3
    return names, F, M, final, at


def main():
    names, F, M, final, at = synth()
    rng = np.random.default_rng(1)
    good = {"when": [{"field": "oi_1h", "op": ">=", "value": 0.048}], "H": 23}
    noise = {"when": [{"field": "noise_a", "op": ">=", "value": 0.03}], "H": 23}
    g = CS.score_rule(F, M, final, names, at, good, rng)
    z = CS.score_rule(F, M, final, names, at, noise, rng)
    assert g["matched"] > 120 and g["mean_close"] > g["mean_hold"] and g["gain"] > 0.008 and g["p_random_hour"] == 0.0, g
    assert all(h["gain"] > 0 for h in g["halves"])
    assert z["gain"] < g["gain"] and z["p_random_hour"] > 0.05, z      # шум: случайный час не хуже
    st = CS.close_by_state(F, M, final, names, at)
    # описание по терцилям: редкое событие (порог 0.048 внутри верхней трети) оно не выделяет —
    # верхняя треть oi_1h в списке есть, но с малым приростом; находит правило, а не описание
    up = next(x for x in st if x["field"] == "oi_1h" and x["tercile"] == 2)
    assert up["matched"] == 500 and up["gain"] < g["gain"], up
    # вышедшая позиция закрыться не может: час с NaN даёт исход книги
    hs = CS.first_hour(F, names, {"when": [{"field": "oi_1h", "op": ">=", "value": -1.0}], "H": 23})
    assert (hs == 1).all(), "условие выполнено сразу — первый час"
    res = CS.result_under(M, final, np.full(len(final), 10))
    assert np.allclose(res[:40], final[:40]) and not np.allclose(res[40:], final[40:])
    # таблица из записей с отметками: закрытие тем же путём, что у сторожа
    import gate_books as GB                                  # noqa: E402
    at0 = 1_793_000_000.0
    rec = {"sym": "AUSDT", "at": at0, "marks": [[at0 + (k - 1) * H, 0.01] for k in range(1, 7)], "state": "closed",
           "pnl": 0.06, "pnl_net": 0.05, "exit": "срок", "exit_ts": at0 + 6 * H - 1, "side": "short", "lev": 2.0, "fills": []}
    c2 = CS.close_pnl(rec, 2)
    k = GB.k_of(rec, at0 + 2 * H + CS.EDGE_S)
    assert k == 3 and abs(c2 - (0.03 - 0.01)) < 1e-9, (k, c2)       # 3 отметки по 0.01, издержки те же 0.01
    assert CS.close_pnl(rec, 6) is None, "позиция уже вышла"
    r = CS.run(log=lambda *a: None, table={"names": names, "F": F, "M": M, "final": final, "at": at, "n": len(at)})
    txt = CS.report(r)
    assert "## Закрытие по состоянию" in txt and "правил закрытия модели ещё нет" in txt
    with tempfile.TemporaryDirectory() as d:
        import json
        import entry_search as ES                            # noqa: E402
        rf = os.path.join(d, "r.json")
        json.dump({"close_rules": [dict(good, why="w"), {"when": [{"field": "нет", "op": ">=", "value": 1}], "H": 5}]}, open(rf, "w"))
        was = ES.RULES_FILE
        try:
            ES.RULES_FILE = rf
            r2 = CS.run(log=lambda *a: None, table={"names": names, "F": F, "M": M, "final": final, "at": at, "n": len(at)})
        finally:
            ES.RULES_FILE = was
        assert r2["close_model"][0]["p_random_hour"] == 0.0 and r2["close_model"][1]["why"] == "поле вне таблицы"
        assert "oi_1h >= 0.048, до 23 ч" in CS.report(r2)
    print("ok  ранний выход: подсаженное поле найдено и держит, правило проходит, шум — нет; вышедшая не закрывается; "
          "закрытие — как у сторожа")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
