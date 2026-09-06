#!/usr/bin/env python3
"""Проверки замера издержек DCA-книг (`costs.py`).

Строки журнала строятся ЗДЕСЬ теми же полями, что пишет `run_paper`
(`fills` = [момент, цена, доля], `margin`, `lev`, `exit_px`, `side`):
подставной артефакт обязан выглядеть как живой, иначе тест исполняет
другую дорогу. Ряды funding — в форме `funding_series.load_funding`
(времена в МИЛЛИСЕКУНДАХ, ставки долями).
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import costs as C                                             # noqa: E402
import rules as R                                             # noqa: E402

H = 3600
T0 = 1_790_000_000.0            # позже RULES_SINCE: строки «живые»
FILLS4 = [(T0 + 60, 100.0, 0.25), (T0 + 5 * H, 102.0, 0.25),
          (T0 + 9 * H, 105.0, 0.25), (T0 + 13 * H, 110.0, 0.25)]


def _row(sym="SSSUSDT", side="short", at=T0, fills=None, exit_ts=None,
         exit_px=95.0, usd=5.0, dep=10000, ruler=None, margin=100.0,
         lev=2.0, pnl_frac=0.05):
    ruler = ruler or ("optimal_s" if side == "short" else "optimal")
    fills = fills if fills is not None else FILLS4
    exit_ts = exit_ts if exit_ts is not None else at + 40 * H
    return {"dep": dep, "ruler": ruler, "at": float(at),
            "exit_ts": float(exit_ts), "sym": sym, "lev": lev,
            "margin": margin, "pnl_frac": pnl_frac, "usd": usd,
            "exit": "тейк", "tail": None, "entry_px": fills[0][1],
            "exit_px": exit_px, "avg": fills[0][1], "depth": len(fills),
            "fills": [list(f) for f in fills], "fav_bp": -500.0,
            "written_at": at + 60, "rules": R.RULES, "side": side}


def _series(start, hours, rate_fn):
    """Ряд начислений раз в час: (времена мс, ставки), как у загрузчика."""
    t = np.array([int((start + i * H) * 1000) for i in range(hours)],
                 dtype=np.int64)
    r = np.array([rate_fn(i) for i in range(hours)], dtype=np.float64)
    return t, r


def test_commission_charges_every_rung_and_the_exit():
    r = _row()                                   # нотионал 200, 4 рунга
    fee = C.commission_usd(r, 5.5)
    qty = sum(0.25 * 200.0 / px for (_t, px, _s) in FILLS4)
    want = 4 * 0.25 * 200.0 * 5.5e-4 + qty * 95.0 * 5.5e-4
    assert abs(fee - want) < 1e-12, (fee, want)
    one = C.commission_usd(_row(fills=[FILLS4[0]]), 5.5)
    assert one < fee, (one, fee)                 # лестница платит больше
    assert abs(one - (0.25 * 200.0 * 5.5e-4
                      + 0.25 * 200.0 / 100.0 * 95.0 * 5.5e-4)) < 1e-12
    assert C.commission_usd(dict(_row(), fills=[]), 5.5) is None
    assert C.commission_usd(dict(_row(), margin=None), 5.5) is None
    assert C.commission_usd(dict(_row(), exit_px=None), 5.5) is None
    print(f"ok  комиссия: лестница {fee:.4f} $ (4 рунга + выход), одиночный "
          f"{one:.4f} $, без нотионала/рунгов/выхода — не измерено")


def test_funding_sign_follows_the_side():
    t, r = _series(T0 - H, 60, lambda i: 0.001)     # плюс: лонги платят
    lo = _row(side="long", ruler="optimal")
    sh = _row(side="short", ruler="optimal_s")
    fl, fs = C.funding_usd(lo, (t, r), "long"), C.funding_usd(sh, (t, r), "short")
    assert fl is not None and fs is not None
    assert fl < 0 < fs and abs(fl + fs) < 1e-12, (fl, fs)
    print(f"ok  знак funding: лонг {fl:+.4f} $ платит, шорт {fs:+.4f} $ получает")


def test_funding_follows_the_open_notional_over_time():
    """До долива платит четверть, после — половина: нотионал по времени."""
    fills = [(T0 + 60, 100.0, 0.25), (T0 + 3 * H, 104.0, 0.25)]
    r = _row(side="long", ruler="optimal", fills=fills, exit_ts=T0 + 6 * H)
    # начисления в T0+1h и T0+4h (и раньше/позже — вне окна)
    t = np.array([int(x * 1000) for x in (T0 - 5 * H, T0 + H, T0 + 4 * H,
                                          T0 + 9 * H)], dtype=np.int64)
    rates = np.array([0.5, 0.001, 0.001, 0.5])
    got = C.funding_usd(r, (t, rates), "long")
    want = -(0.001 * 0.25 * 200.0 + 0.001 * 0.5 * 200.0)
    assert abs(got - want) < 1e-12, (got, want)
    print(f"ok  funding по открытому нотионалу: {got:+.4f} $ = "
          f"четверть на первом начислении, половина на втором")


def test_funding_uncovered_is_not_measured():
    r = _row(side="short", ruler="optimal_s", exit_ts=T0 + 40 * H)
    short_t, short_r = _series(T0 - H, 20, lambda i: 0.001)   # кончается рано
    assert C.funding_usd(r, (short_t, short_r), "short") is None
    late_t, late_r = _series(T0 + 2 * H, 60, lambda i: 0.001)  # начинается поздно
    assert C.funding_usd(r, (late_t, late_r), "short") is None
    assert C.funding_usd(r, None, "short") is None
    full_t, full_r = _series(T0 - H, 60, lambda i: 0.001)
    assert C.funding_usd(r, (full_t, full_r), "short") is not None
    print("ok  ряд, не покрывающий позицию, — «не измерено», не ноль")


def test_rate_at_entry_is_the_last_known_and_the_gate_is_by_side():
    t = np.array([int(x * 1000) for x in (T0 - 2 * H, T0 + H)], dtype=np.int64)
    rates = np.array([0.002, -0.005])
    assert C.rate_at_entry((t, rates), T0) == 0.002
    assert C.rate_at_entry((t, rates), T0 - 3 * H) is None
    assert C.rate_at_entry(None, T0) is None
    # ставка старше суток — не «известная», а конец ряда или дыра:
    # первый живой прогон брал июльскую точку для августовских входов
    one = (t[:1], rates[:1])                     # единственная точка T0−2h
    assert C.rate_at_entry(one, T0 - 2 * H + C.RATE_MAX_AGE_S - 60) == 0.002
    assert C.rate_at_entry(one, T0 - 2 * H + C.RATE_MAX_AGE_S + 60) is None
    assert C.RATE_MAX_AGE_S == 24 * 3600, C.RATE_MAX_AGE_S
    assert C.favourable("long", 0.002) is False
    assert C.favourable("short", 0.002) is True
    assert C.favourable("long", -0.001) is True
    assert C.favourable("short", -0.001) is False
    assert C.favourable("long", 0.0) is True and C.favourable("short", 0.0) is True
    assert C.favourable("long", None) is None
    print("ok  ставка на входе — последняя известная; гейт зеркален стороне")


def _fixture():
    assets = {"SSS": {"bybit_symbol": "SSSUSDT", "taker_fee_bp": 5.5},
              "LLL": {"bybit_symbol": "LLLUSDT", "taker_fee_bp": 2.75},
              "NNN": {"bybit_symbol": "NNNUSDT", "taker_fee_bp": None},
              "UUU": {"bybit_symbol": "UUUUSDT", "taker_fee_bp": 5.5}}
    # ставка по часам: восьмичасовые блоки знака — часть входов при плюсе,
    # часть при минусе, у обеих сторон
    fn = lambda i: 0.001 if (i // 8) % 2 == 0 else -0.001      # noqa: E731
    funding = {"SSS": _series(T0 - 24 * H, 400, fn),
               "LLL": _series(T0 - 24 * H, 400, fn),
               "NNN": _series(T0 - 24 * H, 400, fn)}   # UUU — ряда нет
    rows = []
    for i in range(12):
        at = T0 + i * 6 * H
        rows.append(_row("SSSUSDT", "short", at=at, ruler="optimal_s",
                         usd=3.0 - (i % 3), exit_ts=at + 30 * H,
                         fills=[(at + 60, 100.0, 0.25), (at + 2 * H, 102.0, 0.25)]))
        rows.append(_row("LLLUSDT", "long", at=at, ruler="optimal",
                         usd=2.0 - (i % 4), exit_ts=at + 30 * H,
                         fills=[(at + 60, 100.0, 0.25)]))
    rows.append(_row("NNNUSDT", "long", at=T0, ruler="optimal", usd=1.0))
    rows.append(_row("UUUUSDT", "long", at=T0, ruler="optimal", usd=1.0))
    rows.append(_row("LLLUSDT", "long", at=T0, ruler="safe", usd=1.0,
                     dep=1000))
    # строка без записи рунгов: издержки неизмеримы, брутто — считается
    rows.append(dict(_row("LLLUSDT", "long", at=T0 + H, ruler="safe",
                          usd=1.0, dep=1000), fills=None))
    # строка ПРЕЖНЕЙ версии правил: другая книга, в счёт не входит
    rows.append(dict(_row("LLLUSDT", "long", at=T0 + 2 * H, ruler="safe",
                          usd=50.0, dep=1000), rules=R.RULES - 1))
    return assets, funding, rows


def test_slippage_on_base_entry_and_market_exits_only():
    """Проскальзывание X3 берётся с базового входа (первый рунг — рыночный)
    и с рыночного выхода (пол/срок/трейл/стоп); лимитные рунги и тейк —
    ноль по построению; ликвидация — не проскальзывание."""
    slip = 4.4
    # маржа 100, плечо 2 → нотионал 200; первый рунг 0.25 → 50 $ × 4.4 б.п.
    base = 0.25 * 200 * slip / 1e4
    take = C.slippage_usd(dict(_row(), exit="тейк"), slip)
    assert abs(take - base) < 1e-9, (take, base)
    qty = sum(0.25 * 200 / px for (_t, px, _s) in FILLS4)
    for ex in ("пол", "срок", "трейл", "стоп"):
        got = C.slippage_usd(dict(_row(), exit=ex), slip)
        want = base + qty * 95.0 * slip / 1e4
        assert abs(got - want) < 1e-9, (ex, got, want)
    liq = C.slippage_usd(dict(_row(), exit="ликвидация"), slip)
    assert abs(liq - base) < 1e-9, liq
    one = C.slippage_usd(dict(_row(fills=[FILLS4[0]]), exit="тейк"), slip)
    assert abs(one - base) < 1e-9, one       # один рунг = тот же базовый вход
    assert C.slippage_usd(dict(_row(), fills=[]), slip) is None
    assert C.slippage_usd(dict(_row(), exit_px=None), slip) is None
    assert C.slippage_usd(dict(_row(), exit="пол"), 0.0) == 0.0
    assert set(C.MARKET_EXITS) == {"пол", "срок", "трейл", "стоп"}
    print(f"ok  проскальзывание: тейк {take:.4f} $ (только базовый вход), "
          f"пол {C.slippage_usd(dict(_row(), exit='пол'), slip):.4f} $ (плюс рыночный выход), "
          "ликвидация как тейк, лимитные рунги — ноль")


def test_run_end_to_end_synthetic():
    assets, funding, rows = _fixture()
    s = C.run(rows=rows, funding=funding, assets=assets, log=lambda *a: None)
    assert s["rows"] == 28 and s["funding_present"], (s["rows"], s["funding_present"])
    assert s["rows_all"] == 29 and s["rows_with_fills"] == 27, s["rows_all"]
    assert s["miss"]["taker_fallback"] == 1, s["miss"]
    assert s["miss"]["no_funding_series"] == 1, s["miss"]
    assert s["miss"]["funding_uncovered"] == 0, s["miss"]
    assert s["miss"]["no_fills"] == 1, s["miss"]
    d = time.strftime("%Y-%m-%d", time.gmtime(T0 + H + 60))
    assert s["miss"]["no_fills_written"] == [d, d], s["miss"]["no_fills_written"]
    sf = s["cells"]["safe:1000"]
    # без рунгов — в брутто есть, в измеренных нет; прежняя версия — нигде
    assert sf["n"] == 2 and sf["measured"] == 1, sf
    assert sf["gross_usd"] == 2.0, sf["gross_usd"]
    assert set(s["cells"]) == {"optimal_s:10000", "optimal:10000", "safe:1000"}, \
        set(s["cells"])
    c = s["cells"]["optimal_s:10000"]
    assert c["side"] == "short" and c["n"] == 12 and c["measured"] == 12, c
    assert c["fee_usd"] > 0 and c["fund_usd"] is not None
    assert c["slip_usd"] > 0 and c["n_slip"] == 12, c
    assert abs(c["net_usd"] - round(c["gross_measured_usd"] - c["fee_usd"]
                                    + c["fund_usd"] - c["slip_usd"], 2)) < 0.011, c
    assert s["slip_bp"] == C.SLIP_BP == 4.4 and "X3" in s["slip_source"], s["slip_bp"]
    assert "проскальз. $" in C.report(s) and "нижняя граница" in C.report(s).lower()
    assert c["fee_bp_median"] > 0 and c["gross_bp_median"] is not None
    assert c["form_net"]["day_median"] is not None
    lo = s["cells"]["optimal:10000"]
    assert lo["n"] == 14 and lo["measured"] == 13, lo    # UUU без ряда
    assert lo["fund_cover"] == round(13 / 14, 3), lo["fund_cover"]
    assert s["sides"]["short"]["n"] == 12 and s["sides"]["long"]["n"] == 14
    a = s["arms"]["optimal_s:10000"]
    assert a["n_known"] == 12 and 0 < a["n_fav"] < 12, a
    assert a["median_fav"] is not None and a["median_rest"] is not None
    # медианы руки — в б.п. МАРЖИ: usd 3/2/1 $ при марже 100 → 300/200/100
    assert a["median_all"] == 200.0, a["median_all"]
    assert "б.п. маржи" in C.report(s)
    # покрытие — от строк с рунгами; от всех строк печатается рядом
    assert s["funding_cover"] == round(26 / 27, 3), s["funding_cover"]
    assert s["funding_cover_all"] == round(26 / 28, 3), s["funding_cover_all"]
    assert s["taker_rates_bp"] == [2.75, 5.5], s["taker_rates_bp"]
    v = C.verdict(s)
    assert v["measurable"] is True
    txt = C.report(s)
    for need in ("По книгам", "По сторонам", "Гейт по знаку ставки",
                 "Чего замер НЕ говорит", "`optimal_s:10000`", "short",
                 "без записи рунгов 1", "в журнале всего 29",
                 "брутто измеренных $ | нетто $ (измеренные) | funding б.п."):
        assert need in txt, need
    assert "funding НЕ измерен" not in txt
    assert "nan" not in txt.lower()
    # без рядов funding: колонки нетто объявлены нечитаемыми, а не нулями
    s0 = C.run(rows=rows, funding={}, assets=assets, log=lambda *a: None)
    assert s0["funding_present"] is False and s0["funding_cover"] == 0.0
    assert s0["cells"]["optimal_s:10000"]["fund_usd"] is None
    assert s0["cells"]["optimal_s:10000"]["net_usd"] is None
    assert C.verdict(s0)["measurable"] is False
    assert "funding НЕ измерен" in C.report(s0)
    print(f"ok  сквозной прогон: {s['rows']} строк, книг {len(s['cells'])}, "
          f"покрытие funding {s['funding_cover']}, отчёт {len(txt)} знаков; "
          f"без рядов — «не измерен»")


def test_gate_is_judged_only_with_both_arms_of_size():
    """Медиана девяти отсечённых — шум: рука судится при ≥ MIN_ARM_N
    позиций в ОБЕИХ руках, иначе книга не попадает ни в «помогает», ни
    во «вредит»."""
    n = C.MIN_ARM_N
    arm = lambda nf, nr: {"n_known": nf + nr, "n_fav": nf, "n_rest": nr,  # noqa: E731
                          "median_fav": 10.0, "median_rest": 20.0}
    s = {"funding_present": True, "funding_cover": 1.0, "min_cover": 0.5,
         "cells": {}, "arms": {"thin_rest": arm(n + 10, n - 1),
                               "thin_fav": arm(n - 1, n + 10),
                               "both": arm(n, n)}}
    v = C.verdict(s)
    assert v["gate_hurts"] == ["both"], v
    assert v["gate_helps"] == [], v
    assert n == 30, n
    print(f"ok  гейт судится при обеих руках ≥ {n}: тонкая рука — не судится")


def test_main_writes_the_artifact_and_publishes_by_default():
    assets, funding, rows = _fixture()
    tmp = tempfile.mkdtemp(prefix="dca-costs-")
    calls = []
    o_out, o_pub, o_run = C.OUT, C.publish, C.run
    C.OUT = os.path.join(tmp, "out")
    C.publish = lambda name: calls.append(name)
    seen = []
    C.run = lambda **kw: (seen.append(kw), o_run(
        rows=rows, funding=funding, assets=assets, log=lambda *a: None,
        slip_bp=kw.get("slip_bp")))[1]
    try:
        C.main(["--tag", "test", "--no-publish"])
        assert not calls
        j = json.load(open(os.path.join(C.OUT, "DCA-costs-test.json")))
        assert j["rows"] == 28
        assert os.path.exists(os.path.join(C.OUT, "DCA-costs-test.md"))
        C.main(["--tag", "test"])
        assert len(calls) == 1 and "test" in calls[0], calls
        # --slip-bp доезжает до счёта: стресс p90 X3 считается другим числом
        C.main(["--tag", "stress", "--no-publish", "--slip-bp", "17.4"])
        assert seen[-1].get("slip_bp") == 17.4, seen[-1]
        js = json.load(open(os.path.join(C.OUT, "DCA-costs-stress.json")))
        assert js["slip_bp"] == 17.4 and js["cells"]["optimal_s:10000"]["slip_usd"] > \
            j["cells"]["optimal_s:10000"]["slip_usd"] * 3, (js["slip_bp"], js["cells"]["optimal_s:10000"]["slip_usd"])
    finally:
        C.OUT, C.publish, C.run = o_out, o_pub, o_run
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok  main: артефакт пишется, публикует по умолчанию, --no-publish молчит")


# --- отрицательные контроли ------------------------------------------------
def _poison(path, lit, sub, fn, mod):
    src = open(path, encoding="utf-8").read()
    assert src.count(lit) == 1, f"подделка НЕ легла: литерал не один — {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="costs-"),
                        os.path.basename(path))
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, sub, 1))
        cache = os.path.join(os.path.dirname(path), "__pycache__")
        base = os.path.basename(path).split(".")[0]
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith(base + "."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(mod)
        try:
            fn()
        except Exception:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(mod)


P = os.path.join(HERE, "costs.py")


def _control_exit_fee_dropped():
    return _poison(P, "fee += qty * exit_px * rate", "fee += 0.0",
                   test_commission_charges_every_rung_and_the_exit, C)


def _control_funding_sign_flipped():
    return _poison(P, 'sign = 1.0 if side == "long" else -1.0',
                   'sign = -1.0 if side == "long" else 1.0',
                   test_funding_sign_follows_the_side, C)


def _control_open_notional_ignores_time():
    return _poison(P, "for (ts, _px, share) in fills if ts <= tm)",
                   "for (ts, _px, share) in fills if True)",
                   test_funding_follows_the_open_notional_over_time, C)


def _control_uncovered_counted_as_zero():
    return _poison(P, "if len(t) == 0 or t[-1] < exit_ts * 1000 or t[0] > fills[0][0] * 1000:",
                   "if len(t) == 0:",
                   test_funding_uncovered_is_not_measured, C)


def _control_gate_ignores_side():
    return _poison(P, 'return rate <= 0 if side == "long" else rate >= 0',
                   "return rate >= 0",
                   test_rate_at_entry_is_the_last_known_and_the_gate_is_by_side, C)


def _control_rate_at_entry_looks_ahead():
    return _poison(P, '"right")) - 1', '"right"))',
                   test_rate_at_entry_is_the_last_known_and_the_gate_is_by_side, C)


def _control_stale_rate_counts_as_known():
    return _poison(P, "if i < 0 or at_ms - int(t[i]) > max_age_s * 1000:",
                   "if i < 0:",
                   test_rate_at_entry_is_the_last_known_and_the_gate_is_by_side, C)


def _control_gate_medians_in_dollars():
    return _poison(P, '"median_all": _bp_median(known, "usd")}',
                   '"median_all": round(float(np.median([float(r["usd"]) for r in known])), 4)}',
                   test_run_end_to_end_synthetic, C)


def _control_missing_series_reads_as_present():
    return _poison(P, '"funding_present": funding is not None and len(funding) > 0,',
                   '"funding_present": funding is not None,',
                   test_run_end_to_end_synthetic, C)


def _control_old_rules_rows_counted():
    return _poison(P, "rows = [r for r in rows if R.is_current(r)]",
                   "rows = list(rows)", test_run_end_to_end_synthetic, C)


def _control_no_fills_in_cover_denominator():
    return _poison(P, 'n_fills = n_rows - miss["no_fills"]', "n_fills = n_rows",
                   test_run_end_to_end_synthetic, C)


def _control_thin_rest_arm_judged():
    return _poison(P, 'a.get("n_rest", 0) < MIN_ARM_N', "False",
                   test_gate_is_judged_only_with_both_arms_of_size, C)


def _control_slip_on_take_exit():
    return _poison(P, 'if row.get("exit") in MARKET_EXITS:', "if True:",
                   test_slippage_on_base_entry_and_market_exits_only, C)


def _control_slip_on_every_rung():
    return _poison(P, "base_share = float(fills[0][2])",
                   "base_share = sum(float(f[2]) for f in fills)",
                   test_slippage_on_base_entry_and_market_exits_only, C)


def _control_net_ignores_slippage():
    return _poison(P, "net = (round(gross_m - fee_m + fund_m - slip_m, 2)",
                   "net = (round(gross_m - fee_m + fund_m, 2)",
                   test_run_end_to_end_synthetic, C)


TESTS = [
    test_commission_charges_every_rung_and_the_exit,
    test_slippage_on_base_entry_and_market_exits_only,
    test_funding_sign_follows_the_side,
    test_funding_follows_the_open_notional_over_time,
    test_funding_uncovered_is_not_measured,
    test_rate_at_entry_is_the_last_known_and_the_gate_is_by_side,
    test_run_end_to_end_synthetic,
    test_gate_is_judged_only_with_both_arms_of_size,
    test_main_writes_the_artifact_and_publishes_by_default,
]

CONTROLS = [
    ("комиссия выхода снята", _control_exit_fee_dropped),
    ("знак funding перевёрнут", _control_funding_sign_flipped),
    ("нотионал не следит за временем долива", _control_open_notional_ignores_time),
    ("непокрытый ряд считается нулём", _control_uncovered_counted_as_zero),
    ("гейт не смотрит на сторону", _control_gate_ignores_side),
    ("ставка на входе берётся из будущего", _control_rate_at_entry_looks_ahead),
    ("пустой словарь рядов выдан за funding", _control_missing_series_reads_as_present),
    ("устаревшая ставка считается известной", _control_stale_rate_counts_as_known),
    ("медианы руки гейта в долларах", _control_gate_medians_in_dollars),
    ("строки прежних версий правил в счёте", _control_old_rules_rows_counted),
    ("строки без рунгов в знаменателе покрытия", _control_no_fills_in_cover_denominator),
    ("тонкая рука отсечённых судится", _control_thin_rest_arm_judged),
    ("проскальзывание снимается и с тейка", _control_slip_on_take_exit),
    ("проскальзывание со всех рунгов", _control_slip_on_every_rung),
    ("нетто без проскальзывания", _control_net_ignores_slippage),
]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
