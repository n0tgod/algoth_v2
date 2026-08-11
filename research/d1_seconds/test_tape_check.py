#!/usr/bin/env python3
"""
Тесты проверки события по ленте.

Проверка призвана отличить настоящее падение цены от снятой котировки, и
ошибиться она может ровно в обе стороны: объявить артефактом настоящее
движение либо не заметить пустую книгу. Здесь закрыто и то, и другое —
синтетикой, где ответ известен заранее.

    python3 research/d1_seconds/test_tape_check.py
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

import detect as D                                        # noqa: E402
import run_d1 as R                                        # noqa: E402
import tape_check as T                                    # noqa: E402
from store import Writer                                  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def snap(sym, t, bid, ask):
    return {"s": sym, "ts": int(t * 1000), "u": 1, "bid": bid, "ask": ask,
            "bid_sz": 1.0, "ask_sz": 1.0, "upd": 1,
            "b": [[bid, 1.0]], "a": [[ask, 1.0]], "t": round(float(t), 3)}


def test_both_parsers_agree():
    """Разбор проверки и разбор прогона обязаны дать одну середину.

    Разойдясь, они дали бы проверку на ДРУГИХ событиях, чем сам прогон, —
    и оба отчёта выглядели бы исправными.
    """
    bad = 0
    for sym, t, bid, ask in (("BTCUSDT", 1786000000.5, 90000.5, 90000.7),
                             ("XUSDT", 1786000001.0, 1.234e-05, 1.24e-05)):
        line = json.dumps(snap(sym, t, bid, ask), separators=(",", ":"))
        t1, m1 = R.mid_line(line)
        t2, b2, a2 = T.book_line(line)
        if (t1, m1) != (t2, (b2 + a2) / 2.0):
            bad += 1
    check("разборы прогона и проверки совпадают", bad == 0, f"{bad}")


def test_trade_line_reads_milliseconds():
    """Сборщик пишет метку сделки в миллисекундах, а сетка — в секундах.

    Перепутать порядок здесь значит уехать на полвека и получить пустую
    ленту, то есть «сделок не было» на каждом событии.
    """
    line = json.dumps({"ts": 1786000000123, "s": "X", "side": 1,
                       "p": 12.5, "v": 3.0}, separators=(",", ":"))
    t, p = T.trade_line(line)
    check("метка переведена в секунды", abs(t - 1786000000.123) < 1e-6,
          f"{t}")
    check("цена прочитана", p == 12.5, f"{p}")


def build(root, kind_rows):
    w = Writer(root)
    for kind, sym, obj, ts in kind_rows:
        w.write(kind, sym, obj, ts=ts)
    w.flush()
    w.close()


def scenario(with_trades):
    """Сутки из 60 имён; у одного падение на 4 % и отскок.

    `with_trades=True` — падение видно и в ленте (настоящее движение);
    `False` — сделки идут по прежней цене, а падает только котировка.
    Ответ известен заранее, и проверка обязана его назвать.
    """
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store")
    t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
    j_ev, rows = 3600, 60
    recs = []
    for r in range(rows):
        sym = f"S{r:03d}USDT"
        px = 100.0
        for j in range(0, 7200, 5):
            if r == 0 and j >= j_ev:
                px = 96.0 if j < j_ev + 60 else 96.0 * 1.02
            t = t0 + j
            recs.append(("book", sym, snap(sym, t, px * 0.9999,
                                           px * 1.0001), t))
            if r == 0 and j % 10 == 0:
                # У «котировочного» варианта сделки идут по СТАРОЙ цене:
                # книга упала, а по рынку никто не торговал.
                tp = px if with_trades else 100.0
                recs.append(("trades", sym,
                             {"ts": int(t * 1000), "s": sym, "side": -1,
                              "p": tp, "v": 1.0}, t))
    build(root, recs)
    return tmp, root


def run_scenario(with_trades):
    tmp, root = scenario(with_trades)
    try:
        out = os.path.join(tmp, "out")
        argv, pub = sys.argv, R.publish
        R.publish = lambda msg: None
        sys.argv = ["tape_check.py", "--root", root, "--out", out,
                    "--tag", "t", "--no-publish"]
        try:
            T.main()
        finally:
            sys.argv, R.publish = argv, pub
        return json.load(open(os.path.join(out, "D1-tape-check-t.json"),
                              encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_real_move_is_confirmed():
    a = run_scenario(True)
    g = a["groups"]
    conf = g["подтверждено лентой"]
    check("настоящее движение попало в подтверждённые",
          conf["events"] == 1, f"{conf['events']}")
    check("падение по сделкам сошлось с серединой",
          conf["events"] and abs(conf["trade_fall_pct"]
                                 - conf["mid_fall_pct"]) < 0.5,
          f"{conf.get('trade_fall_pct')} против {conf.get('mid_fall_pct')}")
    check("вывод не объявляет артефакт",
          "артефакт" not in a["reading"] or "не подтвердилась"
          in a["reading"], a["reading"])
    check("сверка загрузки чистая", a["mismatch"] == 0, f"{a['mismatch']}")


def test_quote_only_move_is_caught():
    """Главная проверка: пустая книга обязана быть названа пустой."""
    a = run_scenario(False)
    g = a["groups"]
    check("событие ушло в «только котировка»",
          g["только котировка"]["events"] == 1,
          f"{g['только котировка']['events']}")
    check("в подтверждённых пусто",
          g["подтверждено лентой"]["events"] == 0,
          f"{g['подтверждено лентой']['events']}")
    check("вывод называет артефакт",
          "артефакт" in a["reading"] or "закрыто" in a["reading"],
          a["reading"])


def test_no_trades_is_a_third_group():
    """Отсутствие сделок — не опровержение, а отсутствие свидетельства.

    Смешав «нечем проверять» с «опровергнуто», мы объявили бы дефектом
    то, чего не измеряли, — и закрыли бы направление по тонким именам.
    """
    e = {"n_trades": 0, "trade_fall": float("nan"), "mid_fall": -0.04}
    check("без сделок — своя группа",
          T.group_of(e) == "нечем проверять", T.group_of(e))
    e2 = {"n_trades": T.MIN_TRADES - 1, "trade_fall": -0.04,
          "mid_fall": -0.04}
    check("мало сделок — тоже своя группа",
          T.group_of(e2) == "нечем проверять", T.group_of(e2))
    e3 = {"n_trades": 50, "trade_fall": -0.001, "mid_fall": -0.04}
    check("сделки есть, падения в них нет — котировка",
          T.group_of(e3) == "только котировка", T.group_of(e3))


def test_no_evidence_is_not_a_refutation():
    """Все события в третьей группе — судить нечем, а не «закрыто».

    Сделок в записи может не быть по НАШЕЙ вине: лента не писалась,
    имя тонкое. Объявить это опровержением значит закрыть направление по
    дефекту сбора — тот же класс, что «не измеряется ≠ ноль».
    """
    g = {"подтверждено лентой": {"events": 0},
         "только котировка": {"events": 0},
         "нечем проверять": {"events": 340}}
    r = T.reading(g)
    check("пустая лента не закрывает направление",
          "Судить нечем" in r and "закрыто" not in r, r)
    g2 = {"подтверждено лентой": {"events": 0},
          "только котировка": {"events": 120, "excess_bp": 30.0,
                               "episodes": 20},
          "нечем проверять": {"events": 10}}
    check("опровержение при живой ленте закрывает",
          "закрыто" in T.reading(g2), T.reading(g2))


def test_reading_is_written_from_numbers():
    """Вывод собирается из чисел, а не из надежды."""
    g = {"подтверждено лентой": {"events": 10, "excess_bp": -2.0,
                                 "episodes": 5},
         "только котировка": {"events": 10, "excess_bp": 30.0,
                              "episodes": 5}}
    check("превышение только у котировки названо артефактом",
          "артефакт" in T.reading(g), T.reading(g))
    g2 = {"подтверждено лентой": {"events": 10, "excess_bp": 30.0,
                                  "episodes": 5},
          "только котировка": {"events": 10, "excess_bp": -2.0,
                               "episodes": 5}}
    check("превышение у подтверждённых артефактом не называется",
          "не подтвердилась" in T.reading(g2), T.reading(g2))


def main():
    print("разбор")
    test_both_parsers_agree()
    test_trade_line_reads_milliseconds()
    print("группы")
    test_no_trades_is_a_third_group()
    test_no_evidence_is_not_a_refutation()
    test_reading_is_written_from_numbers()
    print("сквозные сценарии")
    test_real_move_is_confirmed()
    test_quote_only_move_is_caught()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
