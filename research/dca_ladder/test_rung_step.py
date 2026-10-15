"""Вход, которого биржа не примет по шагу объёма, касса не берёт.

Живой отказ 2026-10-15 22:08 (Вена): AKEUSDT, Both Depth $100. Рунг был
$5…6.46 — проверка «≥ $5» его пропустила; у AKE шаг объёма 100 монет,
при цене 0.0323 после округления вниз остаётся 100 × 0.0323 = $3.23, и
исполнитель отказал («Not executed»). Правило одно: бумага (`ration`) и
намерения (`intents`) спрашивают `run_d6.rung_refusal`.

Кусается: (1) случай AKE отказан с причиной про шаг; (2) тот же рунг у
имени с мелким шагом принят; (3) неизвестное имя судится только долларом;
(4) касса `ration` не берёт AKE и берёт крипту того же размера — без
этого правка проверки не дошла бы до бумаги.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d6 as D6                                           # noqa: E402


def _fake_instruments():
    td = tempfile.mkdtemp()
    p = os.path.join(td, "instruments.json")
    with open(p, "w") as f:
        json.dump({"AKEUSDT": {"qty_step": "100", "min_order_qty": "100",
                               "min_notional_value": "5"},
                   "BTCUSDT": {"qty_step": "0.001", "min_order_qty": "0.001",
                               "min_notional_value": "5"},
                   "DOGEUSDT": {"qty_step": "1", "min_order_qty": "1",
                                "min_notional_value": "5"}}, f)
    return p


def _with(path, fn):
    saved = (D6.INSTRUMENTS_JSON, D6._INSTR, D6._INSTR_AT)
    try:
        D6.INSTRUMENTS_JSON, D6._INSTR, D6._INSTR_AT = path, None, 0.0
        return fn()
    finally:
        D6.INSTRUMENTS_JSON, D6._INSTR, D6._INSTR_AT = saved


def test_refusal_reasons():
    def run():
        why = D6.rung_refusal("AKEUSDT", 6.0, 0.0323215)
        assert why and "шага объёма 100" in why and "3.23" in why, why
        assert D6.rung_refusal("AKEUSDT", 6.5, 0.0323215) is None  # 200 монет = 6.46
        assert D6.rung_refusal("DOGEUSDT", 6.0, 0.2) is None       # шаг мелкий
        # мин. лот BTC 0.001 при 65 000 — $65: рунг $6 биржа не примет
        assert "лот 0.001" in (D6.rung_refusal("BTCUSDT", 6.0, 65000.0) or "")
        assert D6.rung_refusal("ZZZUSDT", 6.0, 0.03) is None       # шаг неизвестен
        assert D6.rung_refusal("ZZZUSDT", 4.0, 0.03)               # доллар судится всегда
        assert D6.rung_refusal("AKEUSDT", 6.0, None) is None       # цены нет — только доллар
    _with(_fake_instruments(), run)
    print("ok  AKE: рунг $6 после шага 100 монет = $3.23 — отказ с причиной; "
          "$6.5 → 200 монет = $6.46 — принят; мелкий шаг принят, мин. лот BTC отказан, неизвестное имя — по доллару")


def test_ration_skips_what_exchange_refuses():
    def rec(sym, at, px):
        # маржа 10 $ × плечо 2.4 × 0.25 = рунг 6 $
        return {"sym": sym, "at": at, "exit_ts": at + 3600, "lev": 2.4,
                "pnl": 0.01, "marks": [(at - at % 3600, 0.01)],
                "entry_px": px, "fwd": 50.0}

    def run():
        recs = [rec("AKEUSDT", 1_790_000_000, 0.0323215),
                rec("DOGEUSDT", 1_790_000_100, 0.2)]
        got = D6.ration(recs, 0.1, deposit=100.0)
        return got

    got = _with(_fake_instruments(), run)
    assert got["taken"] == 1 and got["too_small"] == 1, \
        {k: got.get(k) for k in ("taken", "too_small", "no_cash")}
    # отрицательный контроль: без справочника AKE прошёл бы (старое правило)
    td = tempfile.mkdtemp()
    empty = os.path.join(td, "instruments.json")
    with open(empty, "w") as f:
        f.write("{}")
    got0 = _with(empty, run)
    assert got0["taken"] == 2 and got0["too_small"] == 0, got0.get("too_small")
    print("ok  касса не берёт AKE (рунг $6 → $3.23 по шагу) и берёт DOGE того же "
          "размера; без справочника взяла бы оба")


if __name__ == "__main__":
    test_refusal_reasons()
    test_ration_skips_what_exchange_refuses()
