"""Тесты зонда горизонта сигнала.

Три места, где ошибка была бы невидимой: умолчание целей обязано не
шелохнуться от нового параметра (иначе правка зонда молча сдвинула бы
живое обучение); граница разбивки обязана держать правило M2
`s + h < T` с точностью до часа (утечка на один час выглядит как
улучшение всех горизонтов разом); потолок отношения книги lo обязан
резать по той же семантике, что живой гейт (неизмеримое не проходит).
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
sys.path.insert(0, HERE)

import bookfeat as FB              # noqa: E402
import horizon_probe as HP         # noqa: E402

OK = []


def check(name, cond, note=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name
          + (f": {note}" if note and not cond else ""))
    OK.append(bool(cond))


def _synth(S=40, H=80, seed=7):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(
        rng.normal(0, 0.004, size=(S, H)), axis=1))
    s = {"mid_close": close,
         "mid_high": close * (1 + np.abs(rng.normal(0, 0.002, (S, H)))),
         "mid_low": close * (1 - np.abs(rng.normal(0, 0.002, (S, H))))}
    r = np.diff(np.log(close), axis=1, prepend=np.log(close[:, :1]))
    elig = np.ones((S, H), dtype=bool)
    beta = np.ones((S, H))
    return s, r, elig, beta


def test_default_targets_unchanged():
    s, r, elig, beta = _synth()
    a = FB.target_pack(s, r, elig, beta)
    b = FB.target_pack(s, r, elig, beta, horizons=FB.HORIZONS)
    check("умолчание и явная ось дают один состав целей",
          sorted(a) == sorted(b))
    same = all(np.array_equal(a[k], b[k], equal_nan=True) for k in a)
    check("умолчание не шелохнулось ни в одном значении", same)
    c = FB.target_pack(s, r, elig, beta, horizons=(4, 5))
    check("новый горизонт приносит свои цели",
          "fwd_5h" in c and "mae_5h" in c and "mfe_5h" in c)
    m = np.isfinite(c["fwd_5h"]) & np.isfinite(c["fwd_4h"])
    check("цель 5h — не копия 4h",
          m.any() and not np.allclose(c["fwd_5h"][m], c["fwd_4h"][m]))


def test_split_boundary_is_m2_rule():
    # Разрез на 10: при h=4 последний годный час обучения — 5
    # (5+4=9<10), час 6 уже смотрит В хвост (6+4=10). Ошибка ровно в
    # один час — ровно то, что ловил тест M2.
    cols = HP.train_cols(20, 10, 4)
    check("последний годный час — split−h−1",
          max(cols) == 5 and 6 not in cols, str(cols))
    check("часы дальше разреза не входят тем более",
          all(j < 10 for j in cols))
    cols24 = HP.train_cols(20, 10, 24)
    check("горизонт длиннее обучения — обучать не на чем",
          cols24 == [])


def test_gate_pool_rr_ceiling():
    legs = [{"rr": 1.2, "sym": "A"}, {"rr": 1.5, "sym": "B"},
            {"rr": 2.4, "sym": "C"}, {"rr": None, "sym": "D"}]
    lo = HP.gate_pool(legs, 1.5)
    check("потолок 1.5 берёт другой конец распределения",
          [g["sym"] for g in lo] == ["A", "B"])
    check("нога без измеримого отношения не проходит порог",
          all(g["rr"] is not None for g in lo))
    check("без потолка — все ноги", HP.gate_pool(legs, None) is legs)


def main():
    test_default_targets_unchanged()
    test_split_boundary_is_m2_rule()
    test_gate_pool_rr_ceiling()
    if not all(OK):
        print("ЕСТЬ ПАДЕНИЯ")
        return 1
    print("все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
