#!/usr/bin/env python3
"""Проверки замера «доливы в прибыльный шорт».

Кусаются: доля базовой ступени берётся из заполнений записи; pnl долива —
приращение отметок от часа долива, не ниже своей доли (ликвидация долива),
минус круг на свой нотионал; триггеры срабатывают строго до выхода
родителя (прибыль — первый час над порогом, повтор — час повторного выбора,
повтор в плюсе требует плюса, аномалия — плюс и имя слабее рынка); повторы
ищутся внутри окна родителя и не считают сам вход; контроль берёт позиции,
открытые в те же часы, без повторов; «одна на имя» снимается на время счёта
и возвращается даже при ошибке; сборка прогона с подставным рынком и кассой
отдаёт все ячейки; отчёт без None.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_adds as A                                        # noqa: E402
import test_path_screen as TP                                 # noqa: E402

AT = TP.AT
H = 3600.0


def _rec(sym="AAAUSDT", at=AT, deltas=(0.1, 0.2, -0.1, -0.3), lev=20.0, exit="срок", share=0.25):
    r = TP._rec(sym=sym, at=at, lev=lev, exit=exit,
                marks=[(at + i * H, d) for i, d in enumerate(deltas)])
    r["fills"] = [[at, r["entry_px"], share]]
    r["pnl_net"] = r["pnl"] - 0.01
    return r


class _Mkt:
    """Подставной рынок: имя падает на 1 % в час, волна стоит — имя слабее рынка."""
    wave_none = 0

    def __init__(self, own_step=-0.01, wave_step=0.0):
        self.own_step, self.wave_step = own_step, wave_step

    def move(self, sym, t0, t1):
        return self.own_step * round((t1 - t0) / H)

    def wave(self, t0, t1):
        return self.wave_step * round((t1 - t0) / H)


def test_add_outcome_is_the_whole_position_with_a_shared_floor():
    rec = _rec()                                   # cum: 0.1, 0.3, 0.2, −0.1; K = 4; итог −0.1
    v = A.view_lite(rec, _Mkt())
    assert A.share_of(rec) == 0.25 and A.share_of(dict(rec, fills=None)) == A.BASE_SHARE
    cost = 0.25 * 20.0 * A.D10.ROUND_COST_BP / 1e4
    a1 = A.add_outcome(v, 1, -0.9)                 # с долива на часе 1: итог 2·(−0.1) − 0.1 = −0.3 против −0.1
    assert abs(a1["delta"] + 0.2) < 1e-12 and abs(a1["net"] - (-0.2 - cost)) < 1e-12 and not a1["early_floor"]
    assert abs(a1["px_bp"] - (-0.2 / 5.0 * 1e4)) < 1e-9
    a2 = A.add_outcome(v, 2, -0.9)                 # с часа 2: 2·(−0.1) − 0.3 = −0.5 против −0.1 → −0.4, пола нет
    assert abs(a2["delta"] + 0.4) < 1e-12 and not a2["early_floor"]
    a2f = A.add_outcome(v, 2, -0.5)                # пол −0.5 достигнут на часе выхода — не «добито раньше»
    assert abs(a2f["delta"] + 0.4) < 1e-12 and not a2f["early_floor"]
    # родитель провалился и вернулся: без долива +0.4, с доливом общий пол −0.5 добивает на часе 3
    rec2 = _rec(deltas=(0.1, 0.2, -0.45, 0.35, 0.2))          # cum: .1 .3 −.15 .2 .4; K = 5
    v2 = A.view_lite(rec2, _Mkt())
    hit = A.add_outcome(v2, 2, -0.5)
    assert hit["early_floor"] and abs(hit["delta"] - (-0.6 - 0.4)) < 1e-12, hit
    assert abs(hit["px_bp"] - (-0.45 / 5.0 * 1e4)) < 1e-9
    safe = A.add_outcome(v2, 2, -0.9)              # пол −0.9 не достигнут: 2·0.4 − 0.3 = 0.5 против 0.4
    assert not safe["early_floor"] and abs(safe["delta"] - 0.1) < 1e-12
    assert A.floor_of_ruler("safe_s") < A.floor_of_ruler("optimal_s") < 0
    # запись для кассы: вторая ступень по цене отметки, отметки после k удвоены, выход по общему полу
    nr = A.record_with_add(rec2, 2, -0.5)
    assert nr["exit"] == "пол" and nr["add_floor"] and abs(nr["pnl"] + 0.6) < 1e-12
    assert nr["exit_ts"] == rec2["at"] + 3 * H - 1 and len(nr["marks"]) == 3
    assert [round(d, 6) for _h, d in nr["marks"]] == [0.1, 0.2, -0.9]          # третий час удвоен
    assert len(nr["fills"]) == 2 and abs(nr["fills"][1][2] - 0.25) < 1e-12
    assert abs(nr["fills"][1][1] - 100.0 * (1 - 0.3 / 5.0)) < 1e-9              # шорт в плюсе: цена ниже входа
    assert abs(nr["pnl_net"] - (rec2["pnl_net"] - rec2["pnl"] - 0.6 - cost)) < 1e-12
    ok = A.record_with_add(rec2, 2, -0.9)
    assert ok["exit"] == rec2["exit"] and not ok["add_floor"] and abs(ok["pnl"] - 0.5) < 1e-12 and len(ok["marks"]) == 5
    print(f"ok  долив: вся позиция с общим полом — добитая раньше выхода считается отдельно; запись для кассы согласована; круг {cost:.4f}")


def test_triggers_fire_strictly_before_exit_by_their_own_rule():
    rec = _rec(deltas=(0.05, 0.10, 0.20, -0.5, 0.1))        # cum: .05 .15 .35 −.15 −.05; K = 5
    v = A.view_lite(rec, _Mkt(own_step=-0.01))                 # excess −1 % в час
    assert A.trigger(v, "P", 0.10) == 2 and A.trigger(v, "P", 0.25) == 3 and A.trigger(v, "P", 0.50) is None
    assert A.trigger(v, "R", None, reps=[3]) == 3 and A.trigger(v, "R", None, reps=None) is None
    assert A.trigger(v, "R", None, reps=[5]) is None           # час выхода — не долив
    assert A.trigger(v, "R+", None, reps=[4]) is None          # в час 4 родитель в минусе
    assert A.trigger(v, "R+", None, reps=[2]) == 2
    assert A.trigger(v, "M", 0.01) == 1 and A.trigger(v, "M", 0.02) == 2 and A.trigger(v, "M", 0.10) is None
    flat = A.view_lite(rec, _Mkt(own_step=-0.01, wave_step=-0.01))   # имя идёт с рынком — аномалии нет
    assert A.trigger(flat, "M", 0.01) is None
    assert A.trigger({"path": None, "excess": {}}, "P", 0.1) is None
    print("ok  триггеры: прибыль — первый час над порогом, повтор — свой час, повтор в плюсе требует плюса, аномалия — слабее рынка")


def test_repeats_inside_the_parent_window_only():
    cache = {("safe_s", "AAAUSDT", AT): _rec(deltas=(0.1,) * 6)}      # выход AT + 6 ч
    legs_ = [{"sym": "AAAUSDT", "at": AT, "arm": "nn"},                 # сам вход — не повтор
             {"sym": "AAAUSDT", "at": AT + 2 * H, "arm": "nn"},
             {"sym": "AAAUSDT", "at": AT + 2 * H, "arm": "gbm"},         # та же нога другой рукой
             {"sym": "AAAUSDT", "at": AT + 6 * H, "arm": "nn"},         # в час выхода — нет
             {"sym": "BBBUSDT", "at": AT + H, "arm": "nn"}]
    reps = A.repeats_of(cache, legs_)
    assert reps == {("safe_s", "AAAUSDT", AT): [3]}, reps
    print("ok  повторы: внутри окна родителя, сам вход и час выхода не считаются, руки не удваивают")


def test_stats_control_and_beat():
    views, cache = {}, {}
    for i in range(20):
        rec = _rec(sym=f"S{i}USDT", deltas=(0.05, 0.05, (0.2 if i % 2 else -0.3), 0.0, 0.0))
        key = ("safe_s", rec["sym"], AT)
        cache[key] = rec
        views[key] = A.view_lite(rec, _Mkt())
    changed = {("safe_s", "S1USDT", AT): 2, ("safe_s", "S3USDT", AT): 2}   # оба продолжают в плюс
    st = A.stats([A.outcome(views, k, h) for k, h in changed.items()])
    assert st["n"] == 2 and st["pos"] == 1.0 and abs(st["mean"] - (0.2 - 0.25 * 20 * 11 / 1e4)) < 1e-12
    assert st["early_floor"] == 0.0
    idx = A.P.open_index(views)
    ctl = A.control(views, changed, idx, seeds=5, log=lambda *a: None)
    assert len(ctl["means"]) == 5 and ctl["median"] is not None
    ctp = A.control(views, changed, idx, seeds=5, log=lambda *a: None, in_profit=True)
    assert len(ctp["means"]) == 5 and ctp["median"] is not None
    assert abs(A.beat([0.1, 0.2, 0.3], 0.2) - 2 / 3) < 1e-3 and A.beat([], 0.1) is None
    bb = A.by_book(views, changed)
    assert bb["safe_h"]["n"] == 2 and bb["optimal_h"] is None
    print("ok  сводка: среднее и доля плюсовых; контроль — открытые в те же часы, доля зёрен не хуже")


def test_run_wiring_with_stub_market_and_cash():
    cache = {}
    for i in range(12):
        deltas = (0.05, 0.10, 0.20, -0.1, 0.05, 0.05) if i % 3 else (0.02, -0.1, -0.2, -0.4, 0.0, 0.0)
        for rk in ("safe_s", "optimal_s"):
            r = _rec(sym=f"S{i}USDT", at=AT + i * H, deltas=deltas, exit=("пол" if i % 3 == 0 else "срок"))
            cache[(rk, r["sym"], round(AT + i * H, 3))] = r
    legs_ = [{"sym": f"S{i}USDT", "at": AT + i * H, "arm": "nn"} for i in range(12)]
    legs_ += [{"sym": "S1USDT", "at": AT + 1 * H + 2 * H, "arm": "gbm"}]      # повтор на часе 3
    days = [{"d": f"2026-09-{i + 1:02d}", "usd": float((-1) ** i * (30 + i))} for i in range(6)]
    seen = []

    def _stats(packed, ctx, launch, keys, deps=None, now=None):
        seen.append(A.R.ONE_PER_NAME)
        return {f"{bk}:{int(deps[0])}": {"n": len(packed.get(bk) or []), "final": 0.02, "max_dd": -0.01,
                                         "usd": 200.0, "ratio": 2.0, "days": days,
                                         "exits": {"пол": {"n": 2, "usd": -9.0}}}
                for bk in keys}

    saved = (A.S.read_cache, A.S.legs, A.CO.context, A.IR.launches, A.AG.stats_of)
    A.S.read_cache = lambda log=print: (cache, None)
    A.S.legs = lambda log=print: legs_
    A.CO.context = lambda: {"error": "рядов нет"}
    A.IR.launches = lambda: {}
    A.AG.stats_of = _stats
    was = A.R.ONE_PER_NAME
    try:
        s = A.run(seeds=3, log=lambda *a: None, mem_limit=10 ** 6, mkt=_Mkt())
        try:
            A.with_repeats(lambda: 1 / 0)
        except ZeroDivisionError:
            pass
    finally:
        A.S.read_cache, A.S.legs, A.CO.context, A.IR.launches, A.AG.stats_of = saved
    assert A.R.ONE_PER_NAME == was and seen[:2] == [True, False] and all(seen[2:]), seen
    assert not s.get("error") and len(s["cells"]) == len(A.CELLS)
    cells = {c["title"]: c for c in s["cells"]}
    p10 = cells["прибыль ≥ +10 %"]
    assert p10["n"] == 16 and p10["beat"] is not None and p10["beat_plus"] is not None, p10["n"]   # 8 имён × 2 линейки
    assert cells["повторный выбор модели"]["n"] == 2 and cells["повтор при родителе в плюсе"]["n"] == 2
    assert cells["в плюсе и слабее рынка на ≥ 1 %"]["n"] == 24      # и «плохие» в плюсе на часе 1 при имени слабее рынка
    assert s["diag"]["repeats"] == 2 and s["diag"]["share_median"] == 0.25
    assert s["cash"]["safe_h"]["repeats"]["final"] == 0.02 and "days" not in s["cash"]["safe_h"]["base"]
    assert s["cash"]["safe_h"]["прибыль ≥ +10 %"]["n"] == 12 and "_changed" not in s["cells"][0]
    txt = A.report(s)
    assert "None" not in txt, [ln for ln in txt.splitlines() if "None" in ln]
    assert "| прибыль ≥ +10 % |" in txt and "повторы разрешены" in txt and "## По книгам" in txt
    assert "Не посчитано" in A.report({"error": "кэша нет"})
    print(f"ok  сборка: {len(s['cells'])} ячеек, повторы найдены ({s['diag']['repeats']}), «одна на имя» возвращена, отчёт без None")


if __name__ == "__main__":
    for t in (test_add_outcome_is_the_whole_position_with_a_shared_floor,
              test_triggers_fire_strictly_before_exit_by_their_own_rule,
              test_repeats_inside_the_parent_window_only,
              test_stats_control_and_beat,
              test_run_wiring_with_stub_market_and_cash):
        t()
    print("\nвсе 5 проверок прошли")
