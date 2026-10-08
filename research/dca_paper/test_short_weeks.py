#!/usr/bin/env python3
"""Проверки замера «эдж коротких выборов по неделям»: склейка рук в одно
решение, мера в цене и кросс-секция того же часа, случайные того же размера,
непосчитанное считается, калибровочная пара нуля половин (спад находится,
ровный ряд молчит), порядок суда, отчёт без пустот."""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_weeks as SW                                      # noqa: E402
import wave as W                                              # noqa: E402

H = 3600.0
AT0 = 1786000000.0 - (1786000000.0 % 3600)          # 2026-08-06 ~ ровный час
NAMES = [f"N{i:02d}USDT" for i in range(12)]
PROXIES = NAMES[:4]


def _summary(root, prices):
    """prices: {sym: {hour_ts: mid_close}} → сводки s8 по дням."""
    for sym, series in prices.items():
        by_day = {}
        for ts, px in series.items():
            hour = time.strftime("%Y-%m-%d-%H", time.gmtime(ts))
            by_day.setdefault(hour[:10], []).append({"hour": hour, "mid_close": px})
        os.makedirs(os.path.join(root, sym), exist_ok=True)
        for day, rows in by_day.items():
            with open(os.path.join(root, sym, day + ".jsonl"), "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")


def _world(root, hours, fall=None, drift=0.0):
    """Цены всем именам на `hours` часов + 24: имена из `fall(h)` падают
    на 2 % за 24 ч, остальные стоят (плюс общий дрейф за 24 ч)."""
    prices = {s: {} for s in NAMES}
    for k in range(hours + 25):
        ts = AT0 + k * H
        for s in NAMES:
            prices[s][ts] = 100.0 * (1 + drift) ** (k / 24.0)
    if fall:
        for k in range(hours):
            at = AT0 + k * H
            for s in fall(k):
                base = prices[s][at]
                prices[s][at + 24 * H] = base * 0.98 * (1 + drift) ** (24 / 24.0) / (1 + drift) ** (24 / 24.0) * (1 + drift)
    _summary(root, prices)
    return prices


def _mkt(root):
    return W.Market(hours=W.Hours(root=root), proxies=PROXIES, min_proxy=2)


def _leg(sym, at, fwd=-20.0, arm="nn"):
    return {"sym": sym, "at": at, "fwd": fwd, "arm": arm, "side": "short"}


def test_decisions_merge_two_arms_into_one_with_bigger_forecast():
    legs = [_leg("A", AT0, -5.0, "gbm"), _leg("A", AT0, -9.0, "nn"), _leg("B", AT0, -3.0, "gbm"),
            _leg("A", AT0 + H, -4.0, "nn")]
    d = SW.decisions(legs)
    assert [(x["sym"], x["at"]) for x in d] == [("A", AT0), ("B", AT0), ("A", AT0 + H)], d
    assert d[0]["fwd"] == -9.0 and d[0]["arms"] == ["gbm", "nn"] and d[1]["arms"] == ["gbm"]


def test_measure_prices_edge_against_same_hour_cross_section_and_counts_missing():
    with tempfile.TemporaryDirectory() as tmp:
        _world(tmp, hours=2, fall=lambda k: NAMES[8:10])          # два имени падают каждый час
        mkt = _mkt(tmp)
        legs = [_leg(NAMES[8], AT0), _leg(NAMES[9], AT0), _leg("GHOSTUSDT", AT0),  # без цены
                _leg(NAMES[0], AT0 + H)]                                           # стоит на месте
        rows, hours, miss = SW.measure(SW.decisions(legs), mkt, NAMES, seeds=50, min_xs=5, log=lambda *a: None)
        assert miss["no_price"] == 1 and miss["no_xs"] == 0 and miss["no_wave"] == 0, miss
        assert len(rows) == 3
        r8 = next(r for r in rows if r["sym"] == NAMES[8])
        assert abs(r8["edge"] - 200.0) < 1e-6, r8["edge"]                 # −2 % хода = +200 б.п. шорту
        # кросс-секция часа: 2 из 12 имён упали на 2 % → средний минус-ход 33.3 б.п.
        assert abs(r8["xs"] - 200.0 * 2 / 12) < 1e-6 and abs(r8["edge_xs"] - (200.0 - 200.0 * 2 / 12)) < 1e-6
        assert r8["wave"] == 0.0                                            # прокси стоят
        h0 = hours[AT0]
        assert h0["n"] == 2 and h0["n_xs"] == 12 and len(h0["rand"]) == 50
        # случайные два имени из 12: среднее 0, 100 или 200 б.п.; лист (200) не хуже всех
        assert all(x in (0.0, 100.0, 200.0) for x in map(lambda v: round(v, 6), h0["rand"]))
        r0 = next(r for r in rows if r["sym"] == NAMES[0])
        assert r0["edge"] == 0.0 and r0["xs"] > 0 and r0["edge_xs"] < 0
        # час с кросс-секцией меньше min_xs — кросс-секции нет, считается
        rows2, hours2, miss2 = SW.measure(SW.decisions(legs[:2]), mkt, NAMES[:3], seeds=5, min_xs=5, log=lambda *a: None)
        assert miss2["no_xs"] == 1 and rows2[0]["xs"] is None and hours2[AT0]["rand"] is None


def test_summary_weekly_and_rand_share():
    with tempfile.TemporaryDirectory() as tmp:
        _world(tmp, hours=2, fall=lambda k: NAMES[8:10])
        mkt = _mkt(tmp)
        legs = [_leg(NAMES[8], AT0), _leg(NAMES[9], AT0), _leg(NAMES[0], AT0 + H)]
        rows, hours, _m = SW.measure(SW.decisions(legs), mkt, NAMES, seeds=40, min_xs=5, log=lambda *a: None)
        t = SW.summarize(rows, hours)
        assert t["n"] == 3 and t["hours"] == 2 and abs(t["edge"] - 400.0 / 3) < 1e-6
        assert abs(t["hit"] - 2 / 3) < 1e-9 and t["rand_ge"] is not None and 0 <= t["rand_ge"] <= 1
        wk = SW.weekly(rows, hours)
        assert list(wk) == [SW.week_of(AT0)] and wk[SW.week_of(AT0)]["n"] == 3


def _rows_for_null(decline, days=16, per_day=3, seed=0):
    """Синтетические строки: первая половина эдж +50, вторая +50 − decline, шум по часам."""
    import random
    rng = random.Random(seed)
    rows = []
    for d in range(days):
        for hh in range(per_day):
            at = AT0 + (d * 24 + hh * 6) * H
            base = 50.0 - (decline if d >= days // 2 else 0.0) + rng.gauss(0, 10)
            for i in range(3):
                e = base + rng.gauss(0, 15)
                rows.append({"sym": f"S{i}", "at": at, "week": SW.week_of(at), "date": SW.date_of(at),
                             "edge": e, "xs": 0.0, "edge_xs": e, "wave": 0.0, "fwd": -10.0, "arms": ["nn"]})
    return rows


def test_null_halves_calibration_pair_finds_planted_decline_and_is_quiet_on_flat():
    rows = _rows_for_null(decline=80.0)
    hv, cut = SW.halves(rows, {})
    assert hv[0]["edge"] > hv[1]["edge"] and hv[0]["from"] < cut <= hv[1]["from"]
    nl = SW.null_halves(rows, cut, seeds=200)
    assert nl["edge"]["p"] <= 0.02 and nl["edge_xs"]["p"] <= 0.02, nl
    flat = _rows_for_null(decline=0.0, seed=3)
    _hv, cut2 = SW.halves(flat, {})
    nl2 = SW.null_halves(flat, cut2, seeds=200)
    assert nl2["edge"]["p"] > 0.1, nl2


def _half(edge, edge_xs, wave=0.0):
    return {"n": 10, "edge": edge, "edge_xs": edge_xs, "wave": wave, "from": "a", "to": "b"}


def _cash(gaps):
    # цена взятых = эдж листа + разрыв по половинам
    return {bk: {"halves": [{"n": 5, "usd": 1.0, "px_bp": px0}, {"n": 5, "usd": 1.0, "px_bp": px1}]}
            for bk, (px0, px1) in gaps.items()}


def test_cash_summary_splits_gap_into_selection_and_exits():
    with tempfile.TemporaryDirectory() as tmp:
        _world(tmp, hours=2, fall=lambda k: NAMES[8:10])
        mkt = _mkt(tmp)
        rows = {"optimal_h": [
            # взята упавшая на 2 % (сырой +200), позиция вышла по тейку с +100 б.п. нотионала: маржа 100, плечо 10 → $ +10
            {"sym": NAMES[8], "at": AT0, "margin": 100.0, "lev": 10.0, "usd": 10.0},
            # взята стоявшая (сырой 0), позиция −50 б.п.: маржа 200, плечо 5 → $ −5
            {"sym": NAMES[0], "at": AT0 + H, "margin": 200.0, "lev": 5.0, "usd": -5.0},
            {"sym": "GHOSTUSDT", "at": AT0 + H, "margin": 100.0, "lev": 1.0, "usd": 1.0},    # без цены: сырой не измерен
            {"sym": NAMES[1], "at": AT0, "margin": 0.0, "lev": 5.0, "usd": 1.0}]}             # без маржи — мимо
        cut = SW.date_of(AT0 + H)                        # первая половина — только AT0 (день тот же, граница по дате)
        c = SW.cash_summary(rows, cut=SW.date_of(AT0 + 48 * H), mkt=mkt)
        h = c["optimal_h"]["halves"][0]
        assert h["n"] == 3 and abs(h["usd"] - 6.0) < 1e-9 and abs(h["notl"] - 2100.0) < 1e-9
        assert abs(h["px_bp"] - (100.0 - 50.0 + 100.0) / 3) < 1e-9          # средняя по позициям
        assert abs(h["px_w"] - 6.0 / 2100.0 * 1e4) < 1e-9                   # взвешенная нотионалом
        assert h["raw_n"] == 2 and abs(h["raw_bp"] - 100.0) < 1e-9          # (+200 + 0) / 2, призрак не измерен
        assert c["optimal_h"]["halves"][1] is None and c["safe_h"]["halves"] == [None, None]
        assert list(c["optimal_h"]["weeks"]) == [SW.week_of(AT0)]
        del cut
    # разложение в суде: отбор и выходы считаются из тех же полей
    hv = [_half(60, 40), _half(10, 0)]
    nl = {"edge": {"p": 0.30}, "edge_xs": {"p": 0.40}}
    cash = {bk: {"halves": [{"n": 5, "usd": 1.0, "px_bp": 50.0, "raw_bp": 55.0, "px_w": 48.0},
                            {"n": 4, "usd": 1.0, "px_bp": -20.0, "raw_bp": 5.0, "px_w": -25.0}]}
            for bk in ("optimal_h", "aggr_h")}
    j = SW.judge(hv, nl, cash)
    assert j["kind"] == "cash" and j["parts"]["optimal_h"]["select"] == [55.0 - 60, 5.0 - 10]
    assert j["parts"]["optimal_h"]["exits"] == [50.0 - 55.0, -20.0 - 5.0]
    assert "отбор" in SW.verdict(j) and "выходы и издержки" in SW.verdict(j)


def test_judge_follows_declared_order():
    hv = [_half(60, 40), _half(10, 0)]
    nl = {"edge": {"p": 0.01}, "edge_xs": {"p": 0.01}}
    assert SW.judge(hv, nl, {})["kind"] == "signal"
    nl = {"edge": {"p": 0.01}, "edge_xs": {"p": 0.40}}
    assert SW.judge(hv, nl, {})["kind"] == "market"
    nl = {"edge": {"p": 0.30}, "edge_xs": {"p": 0.40}}
    cash = _cash({"optimal_h": (60 - 10, 10 - 30), "aggr_h": (60 - 5, 10 - 20)})   # разрыв −10 → −20, −5 → −10
    j = SW.judge(hv, nl, cash)
    assert j["kind"] == "cash" and j["widened"], j
    cash2 = _cash({"optimal_h": (50, 0), "aggr_h": (60, 12)})                      # у агрессивной разрыв не расширился
    assert SW.judge(hv, nl, cash2)["kind"] == "noise"
    assert SW.judge([None, _half(1, 1)], nl, {})["kind"] == "unmeasured"
    for k in ("signal", "market", "cash", "noise"):
        assert SW.verdict(dict(SW.judge(hv, {"edge": {"p": 0.5}, "edge_xs": {"p": 0.5}}, {}), kind=k, gaps={"optimal_h": [1, 2]}))


def test_end_to_end_report_without_cash_has_every_surface():
    with tempfile.TemporaryDirectory() as tmp:
        _world(tmp, hours=24 * 10, fall=lambda k: NAMES[8:10] if k < 24 * 5 else [])
        mkt = _mkt(tmp)
        legs = []
        for k in range(0, 24 * 10, 8):
            legs += [_leg(NAMES[8], AT0 + k * H, -20.0, "nn"), _leg(NAMES[9], AT0 + k * H, -15.0, "gbm")]
        s = SW.run(log=lambda *a: None, legs_=legs, names=NAMES, mkt=mkt, seeds=20, with_cash=False, min_xs=5)
        assert not s.get("error") and s["n_decisions"] == 60 and s["total"]["n"] == 60
        assert len(s["weeks"]) >= 2 and s["halves"][0]["edge"] > s["halves"][1]["edge"]
        assert s["judge"]["kind"] in ("signal", "market"), s["judge"]      # спад подсажен
        # кросс-секции нет (имён меньше порога) — вердикт «не измерено», а не «рынок»
        s2 = SW.run(log=lambda *a: None, legs_=legs, names=NAMES, mkt=mkt, seeds=5, with_cash=False, min_xs=50)
        assert s2["judge"]["kind"] == "unmeasured" and "кросс-секция" in SW.verdict(s2["judge"]), s2["judge"]
        txt = SW.report(s)
        for must in ("| неделя |", "всё окно", "Половины окна", "Нуль половин", "Вердикт (из чисел)", s["cut"]):
            assert must in txt, must
        assert "None" not in txt


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    import traceback
    bad = 0
    for t in TESTS:
        try:
            t()
            print("ok", t.__name__)
        except Exception:                                      # noqa: BLE001
            bad += 1
            print("FAIL", t.__name__)
            traceback.print_exc()
    sys.exit(1 if bad else 0)
