#!/usr/bin/env python3
"""Предсказуемость пола (`floor_predict.py`): AUC считается правильно (ничьи
пополам, известные значения), калибровочная пара — подсаженный признак
находится, шумовой нет; «закрыть 10 %» на подсаженном признаке бьёт
случайные 10 %, на шуме — нет; признак часа h берётся только у позиций,
живых к концу h, и только по пути до h."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import floor_predict as FP                                    # noqa: E402


def test_auc_is_exact_with_ties():
    assert FP.auc([1, 2, 3, 4], [0, 0, 1, 1]) == 1.0
    assert FP.auc([1, 2, 3, 4], [1, 1, 0, 0]) == 0.0
    assert FP.auc([1, 1, 1, 1], [0, 1, 0, 1]) == 0.5
    assert abs(FP.auc([1, 2, 2, 3], [0, 1, 0, 1]) - 0.875) < 1e-12   # (2;1)=1 (2;2)=½ (3;1)=1 (3;2)=1
    assert FP.auc([1, 2], [1, 1]) is None
    print("ok  AUC: точные значения, ничьи пополам, одна метка — None")


def _rows(n, rng, planted):
    rows = []
    for i in range(n):
        bad = rng.random() < 0.15
        final = -0.5 if bad else rng.uniform(-0.05, 0.25)
        sig = (1.0 if bad else 0.0) + rng.gauss(0, 0.6) if planted else rng.gauss(0, 1)
        cum = (-0.10 if bad else 0.05) if planted else rng.uniform(-0.05, 0.05)
        rows.append({"bad": bad, "final": final, "K": 24, "exit": "пол" if bad else "срок", "at": float(i),
                     "f": {"lev": sig, "-fav": None, "beta": rng.gauss(0, 1), "pre24": None, "wave_pre24": None},
                     "h": {h: {"cum": cum, "f": {"-cum": -cum + (rng.gauss(0, 0.02) if planted else 0.0),
                                                 "-min": rng.gauss(0, 1), "wave": rng.gauss(0, 1),
                                                 "excess": None}} for h in FP.HOURS}})
    return rows


def test_calibration_pair_finds_planted_and_stays_silent_on_noise():
    rng = random.Random(1)
    planted = FP.judge(_rows(1500, rng, True), perms=200, seeds=200, rng=random.Random(2))
    noise = FP.judge(_rows(1500, random.Random(3), False), perms=200, seeds=200, rng=random.Random(4))
    p = planted["feat"]
    assert p["0:lev"]["outside"] and p["0:lev"]["auc"] > 0.8, p["0:lev"]
    c = p["4:-cum"]
    assert c["outside"] and c["rand_not_worse"] <= 0.05 and c["delta_mean"] > c["rand_delta_mean"], c
    assert c["bad_in_cut"] > c["bad_in_alive"]
    nz = noise["feat"]
    silent = [k for k, v in nz.items() if v.get("outside")]
    assert len(silent) <= 2, ("шум не должен различать пол", silent)
    assert nz["0:-fav"].get("why") and nz["4:excess"].get("why"), "неизмеренный признак — причина, а не AUC"
    print("ok  калибровка: подсаженный признак найден (AUC > 0.8, закрытие бьёт случайное), шум молчит")


if __name__ == "__main__":
    test_auc_is_exact_with_ties()
    test_calibration_pair_finds_planted_and_stays_silent_on_noise()
    print("\nвсе 2 проверки прошли")
