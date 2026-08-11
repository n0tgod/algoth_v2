#!/usr/bin/env python3
"""
Тесты модели очереди и замера пассивного входа.

Модель очереди — единственное место всей гипотезы, где легко соврать
себе в свою пользу: «цену коснулись, значит исполнено» была ошибкой
движка v1. Здесь она закрыта синтетикой, где ответ известен заранее, и
проверяется в обе стороны — что заявка НЕ исполняется раньше срока и что
исполняется, когда очередь съедена.

    python3 research/d1_seconds/test_passive.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))

import passive as PS                                      # noqa: E402
import run_d1 as R                                        # noqa: E402
from store import Writer                                  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def tape(rows):
    """`(время, цена, объём, сторона)` массивами."""
    a = np.array(rows, dtype=np.float64)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def test_touching_the_price_is_not_a_fill():
    """Главная проверка модуля.

    Сквозь уровень прошло меньше объёма, чем стояло в очереди впереди, —
    значит нашей заявки не коснулись вовсе. Правило «цену задели, значит
    исполнено» и есть ошибка, погубившая движок v1.
    """
    tt, tp, tv, ts = tape([[1.0, 100.0, 3.0, -1],
                           [2.0, 100.0, 3.0, -1],
                           [3.0, 100.0, 3.0, -1]])
    got = PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, queue=50.0, size=1.0)
    check("очередь не съедена — исполнения нет", got is None, f"{got}")


def test_fill_when_the_queue_is_eaten():
    tt, tp, tv, ts = tape([[1.0, 100.0, 4.0, -1],
                           [2.0, 100.0, 4.0, -1],
                           [3.0, 100.0, 4.0, -1]])
    got = PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, queue=9.0, size=1.0)
    check("исполнение после съедания очереди", got == 3.0, f"{got}")


def test_only_selling_aggression_fills_a_buy():
    """Покупателя-агрессора наша покупка не исполняет.

    Сторона в записи — агрессора (проверено на архиве ленты). Спутав
    знак, мы получили бы исполнение на росте, то есть ровно там, где
    пассивная заявка исполниться не может.
    """
    tt, tp, tv, ts = tape([[1.0, 100.0, 100.0, +1],
                           [2.0, 100.0, 100.0, +1]])
    got = PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, queue=1.0, size=1.0)
    check("покупки агрессора не исполняют покупку", got is None, f"{got}")


def test_price_above_our_limit_does_not_fill():
    tt, tp, tv, ts = tape([[1.0, 100.5, 100.0, -1]])
    got = PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, queue=0.0, size=1.0)
    check("сделка выше нашей цены не исполняет", got is None, f"{got}")
    tt2, tp2, tv2, ts2 = tape([[1.0, 99.5, 100.0, -1]])
    got2 = PS.fill_at(tt2, tp2, tv2, ts2, 0.0, 100.0, queue=0.0, size=1.0)
    check("сделка ниже нашей цены исполняет", got2 == 1.0, f"{got2}")


def test_wait_window_is_respected():
    """Заявка снимается: сделка после окна ожидания нас не исполняет."""
    tt, tp, tv, ts = tape([[120.0, 100.0, 100.0, -1]])
    got = PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, queue=0.0, size=1.0,
                     wait=60)
    check("после окна не исполняет", got is None, f"{got}")
    got2 = PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, queue=0.0, size=1.0,
                      wait=180)
    check("внутри окна исполняет", got2 == 120.0, f"{got2}")


def test_trades_before_placement_do_not_count():
    """Объём, прошедший ДО постановки, очередь нам не съедает."""
    tt, tp, tv, ts = tape([[1.0, 100.0, 1000.0, -1],
                           [20.0, 100.0, 1.0, -1]])
    got = PS.fill_at(tt, tp, tv, ts, 10.0, 100.0, queue=100.0, size=1.0)
    check("прошлое не исполняет", got is None, f"{got}")


def test_own_size_must_also_pass():
    """Нужно съесть очередь И наш объём: иначе заявка задета частично.

    Частичное исполнение мы намеренно не моделируем, а требуем полного —
    это работает против нас, что здесь и нужно.
    """
    tt, tp, tv, ts = tape([[1.0, 100.0, 10.0, -1]])
    check("очереди хватило, а на нас нет",
          PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, 9.5, 1.0) is None,
          "исполнилось")
    check("хватило и на нас",
          PS.fill_at(tt, tp, tv, ts, 0.0, 100.0, 8.0, 1.0) == 1.0,
          "не исполнилось")


def build_day(root, *, fill_side):
    """Сутки из 60 имён; у одного падение 4 % и отскок.

    `fill_side=True` — после падения идут ПРОДАЖИ агрессором, то есть
    пассивная покупка исполняется; `False` — идут покупки, и заявка
    остаётся стоять.
    """
    w = Writer(root)
    t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
    j_ev = 3600
    for r in range(60):
        sym = f"S{r:03d}USDT"
        px = 100.0
        for j in range(0, 7200, 5):
            if r == 0 and j >= j_ev:
                px = 96.0 if j < j_ev + 60 else 96.0 * 1.02
            t = t0 + j
            w.write("book", sym, {
                "s": sym, "ts": int(t * 1000), "u": 1,
                "bid": px * 0.999, "ask": px * 1.001,
                "bid_sz": 10.0, "ask_sz": 10.0, "upd": 1,
                "b": [[px * 0.999, 10.0]], "a": [[px * 1.001, 10.0]],
                "t": round(float(t), 3)}, ts=t)
            if r == 0:
                w.write("trades", sym, {
                    "ts": int(t * 1000), "s": sym,
                    "side": -1 if fill_side else 1,
                    "p": px * 0.998, "v": 200.0}, ts=t)
    w.flush()
    w.close()
    return t0


def run_day(fill_side):
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "store")
        build_day(root, fill_side=fill_side)
        out = os.path.join(tmp, "out")
        argv, pub = sys.argv, R.publish
        R.publish = lambda msg: None
        sys.argv = ["passive.py", "--root", root, "--out", out,
                    "--tag", "t", "--no-publish"]
        try:
            PS.main()
        finally:
            sys.argv, R.publish = argv, pub
        return json.load(open(os.path.join(out, "D1-passive-t.json"),
                              encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_end_to_end_fills_and_misses():
    a = run_day(True)
    s = a["summary"]
    check("тейкер исполняется всегда", s["тейкер"]["fill_rate"] == 1.0,
          f"{s['тейкер']['fill_rate']}")
    check("мейкер на биде исполнился при продажах",
          s["мейкер на биде"]["fill_rate"] == 1.0,
          f"{s['мейкер на биде']['fill_rate']}")
    check("нетто мейкера выше тейкера при равном исходе",
          s["мейкер на биде"]["excess_net_bp"]
          > s["тейкер"]["excess_net_bp"],
          f"{s['мейкер на биде']['excess_net_bp']} против "
          f"{s['тейкер']['excess_net_bp']}")

    b = run_day(False)
    sb = b["summary"]
    check("без продающей агрессии мейкер не исполняется",
          sb["мейкер на биде"]["fill_rate"] == 0.0,
          f"{sb['мейкер на биде']['fill_rate']}")
    check("неисполненная рука не даёт нетто",
          sb["мейкер на биде"]["excess_net_bp"] is None,
          f"{sb['мейкер на биде']['excess_net_bp']}")
    check("тейкер при этом торгует", sb["тейкер"]["fill_rate"] == 1.0,
          f"{sb['тейкер']['fill_rate']}")


def main():
    print("модель очереди")
    test_touching_the_price_is_not_a_fill()
    test_fill_when_the_queue_is_eaten()
    test_only_selling_aggression_fills_a_buy()
    test_price_above_our_limit_does_not_fill()
    test_wait_window_is_respected()
    test_trades_before_placement_do_not_count()
    test_own_size_must_also_pass()
    print("сквозной прогон")
    test_end_to_end_fills_and_misses()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
