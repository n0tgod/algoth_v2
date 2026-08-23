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


def test_edge_prefilter_matches_simulate_gate():
    # Предфильтр появился как правка памяти (первый прогон убит OOM
    # на хранении всех ног); правка памяти, меняющая состав сделок,
    # была бы другой мерой — тождество с гейтом ядра держит этот тест.
    import tournament as TN
    legs = []
    for i, (f, sym) in enumerate([(32.99, "A"), (33.0, "B"),
                                  (-33.0, "C"), (-32.99, "D"),
                                  (40.0, "E")]):
        legs.append({"id": i, "sym": sym, "arm": "gbm",
                     "side": "long" if f > 0 else "short",
                     "fwd": f, "rr": 9.9, "at": 1000 + i})
    outs = {(lg["id"], "m", True, HP.AGE_H):
            ("age", 0.0, lg["at"] + 60, 1.0) for lg in legs}
    var = {"edge": HP.EDGE_BP, "rr": 0.0, "stop": "m", "take": True,
           "age": HP.AGE_H}
    entered = {t["sym"] for t in TN.simulate(legs, outs, var)}
    kept = {lg["sym"] for lg in legs if HP.edge_pass(lg["fwd"])}
    check("предфильтр по краю тождествен гейту симуляции",
          entered == kept == {"B", "C", "E"},
          f"simulate {sorted(entered)} против фильтра {sorted(kept)}")
    check("нога без прогноза не проходит предфильтр",
          not HP.edge_pass(None))


def test_fit_predict_executes_end_to_end():
    # Дефект «del ys раньше печати» жил только на дороге исполнения:
    # py_compile молчал, живой прогон падал UnboundLocalError на первом
    # обучении. Смоук исполняет настоящий fit_predict на синтетике
    # test_s8 — той же, на которой гоняется цикл.
    import numpy as np
    import train as T
    from test_s8 import synth_summary
    # D=300, а не меньше: хеджированной цели нужна бета (BETA_MIN=96
    # часов), и на коротком окне обучение честно пустое — «строк 0».
    s = synth_summary(S=40, D=300)
    x, names, targets, elig = T.assemble(s, horizons=(4,))
    n = s["mid_close"].shape[1]
    cols = HP.train_cols(n, int(n * 0.6), 4)
    el_tr = elig.copy()
    keep = np.zeros(n, dtype=bool)
    keep[cols] = True
    el_tr[:, ~keep] = False
    arm, fit_fn = T.ARMS[0]
    preds = HP.fit_predict(4, arm, fit_fn, x, targets, elig, el_tr)
    check("обучение горизонта исполняется от начала до конца",
          preds is not None and set(preds) == {"fwd", "mae", "mfe"})
    check("предсказание покрывает всю сетку",
          preds is not None
          and all(p.shape == elig.shape for p in preds.values()))


def main():
    test_default_targets_unchanged()
    test_split_boundary_is_m2_rule()
    test_gate_pool_rr_ceiling()
    test_edge_prefilter_matches_simulate_gate()
    test_fit_predict_executes_end_to_end()
    if not all(OK):
        print("ЕСТЬ ПАДЕНИЯ")
        return 1
    print("все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
