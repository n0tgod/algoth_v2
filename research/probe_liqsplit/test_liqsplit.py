#!/usr/bin/env python3
"""Проверки зонда деления падений по принтам ликвидаций.

Синтетика с известным ответом (правило tape_check): два падения в
сутках, у одного принты ликвидаций В ОКНЕ обнаружения, у другого —
только ВНЕ окна. Сломанная привязка окна или метка в миллисекундах,
прочитанная секундами, разложили бы события не по тем группам — и
таблица выглядела бы осмысленно.

    cd /home/user/algoth_v2 && .venv/bin/python \
        research/probe_liqsplit/test_liqsplit.py
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
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "d1_seconds"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))

import liqsplit as LS                                     # noqa: E402
from store import Writer                                  # noqa: E402

R = LS.R
FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def snap(sym, t, bid, ask):
    return {"s": sym, "ts": int(t * 1000), "u": 1, "bid": bid,
            "ask": ask, "bid_sz": 1.0, "ask_sz": 1.0, "upd": 1,
            "b": [[bid, 1.0]], "a": [[ask, 1.0]],
            "t": round(float(t), 3)}


def liq(sym, t, side="Sell", p=96.0, v=10.0):
    return {"ts": int(t * 1000), "side": side, "p": p, "v": v}


def scenario():
    """Сутки из 60 имён. S000 падает в 3600 с ликвидациями в окне;
    S001 падает в 7000 — принты только ВНЕ окна (до и после)."""
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store")
    t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
    recs = []
    ev = {0: 3600, 1: 7000}
    for r in range(60):
        sym = f"S{r:03d}USDT"
        for j in range(0, 10800, 5):
            px = 100.0
            if r in ev and j >= ev[r]:
                px = 96.0 if j < ev[r] + 60 else 96.0 * 1.02
            t = t0 + j
            recs.append(("book", sym,
                         snap(sym, t, px * 0.9999, px * 1.0001), t))
    for dt in (-600, -300, -30):     # внутри окна [ev−900, ev]
        t = t0 + 3600 + dt
        recs.append(("liq", "S000USDT", liq("S000USDT", t), t))
    for dt in (-1200, 120):          # строго вне окна
        t = t0 + 7000 + dt
        recs.append(("liq", "S001USDT", liq("S001USDT", t), t))
    w = Writer(root)
    for kind, sym, obj, ts in recs:
        w.write(kind, sym, obj, ts=ts)
    w.flush()
    w.close()
    return tmp, root


def run_scenario():
    tmp, root = scenario()
    try:
        out = os.path.join(tmp, "out")
        argv, pub = sys.argv, R.publish
        R.publish = lambda msg: None
        sys.argv = ["liqsplit.py", "--root", root, "--out", out,
                    "--tag", "t", "--no-publish"]
        try:
            LS.main()
        finally:
            sys.argv, R.publish = argv, pub
        return json.load(open(os.path.join(out, "LIQSPLIT-t.json"),
                              encoding="utf-8")), \
            open(os.path.join(out, "LIQSPLIT-t.md"),
                 encoding="utf-8").read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_liq_line_reads_milliseconds():
    t, usd, buy = LS.liq_line(json.dumps(
        {"ts": 1788100000123, "side": "Buy", "p": 2.5, "v": 40.0}))
    check("метка в секундах, не миллисекундах",
          abs(t - 1788100000.123) < 1e-6, str(t))
    check("нотионал = p×v", abs(usd - 100.0) < 1e-9, str(usd))
    check("сторона Buy = 1", buy == 1, str(buy))


def test_split_and_window():
    art, md = run_scenario()
    g = art["groups"]
    a, b = g[LS.GROUPS[0]], g[LS.GROUPS[1]]
    check("событий два, по одному в группе",
          a["events"] == 1 and b["events"] == 1,
          f"{a['events']}/{b['events']}")
    check("принты вне окна НЕ пометили событие",
          b.get("n_liq_med") == 0, str(b))
    # Личность события, а не только состав групп: помеченным обязан
    # быть S000 с ТРЕМЯ принтами окна — окно, съехавшее ЗА событие,
    # пометило бы S001 с одним принтом, и группы поменялись бы местами,
    # оставив прежние проверки зелёными (первый контроль был холостым
    # ровно из-за этой симметрии).
    check("помечено само событие: три принта в окне",
          a.get("n_liq_med") == 3, str(a.get("n_liq_med")))
    check("медианный нотионал помеченной группы посчитан",
          a["liq_usd_med"] and a["liq_usd_med"] > 0, str(a))
    check("превышение помеченной группы измерено",
          a["excess_bp"] is not None and a["excess_bp"] > 0, str(a))
    check("доля Sell = 1.0 (падение сносит лонгов)",
          g["_sell_share"] == 1.0, str(g["_sell_share"]))
    check("градиент при <30 событиях пуст, а не выдуман",
          g["_gradient"] == [], str(g["_gradient"]))
    check("молчащих суток ноль", art["dead_days"] == 0, "")
    check("рамка смертей в отчёте",
          "условие украшение" in md and "покупай" in md, md[:400])
    check("порог экономики числом в отчёте", "35 б.п." in md, "")


def test_dead_day_detection():
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "store")
        t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
        w = Writer(root)
        w.write("book", "S000USDT",
                snap("S000USDT", t0, 99.99, 100.01), t0)
        w.flush()
        w.close()
        check("сутки без единого liq-файла — молчание",
              not LS.liq_day_alive(root, "2026-08-05"), "")
        os.makedirs(os.path.join(root, "liq", "S000USDT"),
                    exist_ok=True)
        with open(os.path.join(root, "liq", "S000USDT",
                               "2026-08-05-03.jsonl"), "w") as f:
            f.write(json.dumps(liq("S000USDT", t0 + 3600 * 3)) + "\n")
        check("один файл за сутки — лента жива",
              LS.liq_day_alive(root, "2026-08-05"), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reading_branches():
    def grp(a_bp, b_bp):
        base = {"events": 5, "episodes": 5, "share_pos": 0.6,
                "own_bp": 0.0, "bg_bp": 0.0, "liq_usd_med": 1.0,
                "n_liq_med": 1.0}
        return {LS.GROUPS[0]: dict(base, excess_bp=a_bp),
                LS.GROUPS[1]: dict(base, excess_bp=b_bp)}
    check("не добавляет — смерть L3 названа",
          "украшение" in LS.reading(grp(10.0, 12.0)), "")
    check("добавляет, но ниже порога — экономика остаётся",
          "не" in LS.reading(grp(20.0, 10.0))
          and "35" in LS.reading(grp(20.0, 10.0)),
          LS.reading(grp(20.0, 10.0)))
    check("выше валового порога — повод считать спеку",
          "повод считать спеку" in LS.reading(grp(40.0, 10.0)), "")
    empty = {LS.GROUPS[0]: {"events": 0, "episodes": 0,
                            "excess_bp": None},
             LS.GROUPS[1]: {"events": 3, "episodes": 3,
                            "excess_bp": 5.0}}
    check("пустая группа — «не измерено», не вердикт",
          "не измерено" in LS.reading(empty), LS.reading(empty))


def main():
    tests = (test_liq_line_reads_milliseconds,
             test_dead_day_detection,
             test_reading_branches,
             test_split_and_window)
    for t in tests:
        print(t.__name__)
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
