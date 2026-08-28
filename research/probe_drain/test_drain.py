#!/usr/bin/env python3
"""Проверки разбора слива: каждая дорога исполняется, не только формулы.

У одноразового зонда дорог несколько — загрузка книг, срезы окна,
контекст рынка, IC, цикл, отчёт, публикация, — и «тесты зелёные»
значит ровно те, которые тесты ИСПОЛНЯЮТ (урок S11, трижды).
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop")):
    if p not in sys.path:
        sys.path.insert(0, p)

import drain as DR                                         # noqa: E402
import turn as PT                                          # noqa: E402

FAILED = []


def check(name, cond, note=""):
    print(("ok  " if cond else "ПРОВАЛ") + " " + name
          + ("" if cond else f" · {note}"))
    if not cond:
        FAILED.append(name)


def test_window_bounds_are_inclusive():
    """Границы окна включительны с обеих сторон.

    Сдвиг на день молча перекладывал бы деньги между базой и сливом, и
    обе таблицы выглядели бы исправными — сравнивать их стало бы не с
    чем.
    """
    check("первый день слива в окне",
          DR.in_win(DR.day_int("2026-08-24"), DR.DRAIN))
    check("последний день слива в окне",
          DR.in_win(DR.day_int("2026-08-27"), DR.DRAIN))
    check("канун слива — база, не слив",
          not DR.in_win(DR.day_int("2026-08-23"), DR.DRAIN)
          and DR.in_win(DR.day_int("2026-08-23"), DR.BASE))
    check("после окна — ничьё",
          not DR.in_win(DR.day_int("2026-08-28"), DR.DRAIN)
          and not DR.in_win(DR.day_int("2026-08-28"), DR.BASE))


def test_slice_stats_pins_numbers():
    """Срез считает стороны, причины и концентрацию числом."""
    d = DR.day_int("2026-08-25")
    tr = [
        {"day": d, "pnl": -10.0, "net": -300.0, "reason": "stop",
         "side": "long", "sym": "AAAUSDT", "arm": "gbm", "tid": "t1"},
        {"day": d, "pnl": -6.0, "net": -200.0, "reason": "stop",
         "side": "short", "sym": "BBBUSDT", "arm": "gbm", "tid": "t2"},
        {"day": d, "pnl": +2.0, "net": +50.0, "reason": "target",
         "side": "long", "sym": "CCCUSDT", "arm": "nn", "tid": "t3"},
    ]
    s = DR.slice_stats(tr)
    check("итог −14", abs(s["pnl"] + 14.0) < 1e-9, str(s["pnl"]))
    check("побед 0.333", s["win"] == 0.333, str(s["win"]))
    check("деньги лонгов −8", abs(s["long_pnl"] + 8.0) < 1e-9)
    check("деньги шортов −6", abs(s["short_pnl"] + 6.0) < 1e-9)
    check("стопы: 2 сделки на −16 $",
          s["reasons"]["stop"] == {"n": 2, "pnl": -16.0},
          str(s["reasons"]))
    check("худшее имя AAA −10, без него −4",
          s["worst_sym"] == "AAAUSDT" and abs(s["pnl_wo_worst"] + 4) < 1e-9,
          str((s["worst_sym"], s["pnl_wo_worst"])))
    # Причина-список (живое поле `why` однажды уже роняло зонд
    # перелома) обязана печататься строкой, а не падать.
    s2 = DR.slice_stats([dict(tr[0], reason=["x", 1])])
    check("причина-список не роняет срез", "n" in s2, str(s2))


def _fixture(root):
    """Книга с прибыльной базой и убыточным окном — как живая."""
    s8 = os.path.join(root, "s8_loop", "out")
    for name in ("model", "model_h24"):
        mdir = os.path.join(s8, name)
        os.makedirs(mdir)
        with open(os.path.join(mdir, "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": 2, "horizon_h": 4}, f)
        base_ts = DR.day_int("2026-08-14") * DR.DAY
        pk, rv = [], []
        for i in range(13 * 24):
            ts = base_ts + i * 3600
            hour = datetime.fromtimestamp(
                ts, timezone.utc).strftime("%Y-%m-%d-%H")
            pk.append({"arm": "gbm", "hour": hour, "at_ts": ts + 3900,
                       "long": [{"sym": "AAAUSDT", "fwd": 60.0,
                                 "mae": -30.0, "mfe": 90.0, "px": 100.0,
                                 "why": [["eat_bid", 12.0]]}],
                       "short": []})
            drain = DR.in_win((ts + 4 * 3600) // DR.DAY, DR.DRAIN)
            got = -90.0 if drain else 40.0
            rv.append({"arm": "gbm", "hour": hour, "cost_bp": 11.0,
                       "at_ts": ts + 4 * 3600 + 60,
                       "rows": [{"sym": "AAAUSDT", "side": "long",
                                 "expected": 60.0, "got": got,
                                 "net": got - 11.0}]})
        for fname, rows in (("picks.jsonl", pk), ("review.jsonl", rv)):
            with open(os.path.join(mdir, fname), "w",
                      encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # ic_history и train_log — у живого цикла, здесь пусто: ветка
    # «файла нет» обязана давать прочерк, а не ноль и не падение.
    return s8


def test_whole_run_writes_report():
    root = tempfile.mkdtemp()
    published = []
    keep = PT.publish
    PT.publish = lambda: published.append(1)
    out_was = DR.HERE
    try:
        s8 = _fixture(root)
        DR.HERE = os.path.join(root, "probe_drain")
        rc = DR.main(["--s8", s8, "--tag", "t", "--no-publish"])
        check("прогон дошёл до конца", rc == 0, str(rc))
        rep = os.path.join(DR.HERE, "out", "DRAIN-report-t.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("дни окна помечены", "08-24 ←" in txt and "08-27 ←" in txt,
              txt[:400])
        check("окно против базы есть",
              "| h4 | база |" in txt and "| h4 | слив |" in txt)
        check("худшие сделки поимённо", "AAAUSDT" in
              txt.split("Худшие сделки окна")[1], "нет имён в топе")
        check("день без контекста — прочерк, а не ноль",
              "| 08-24 ← | — |" in txt, "контекст выдуман")
        check("с флагом публикации нет", not published, str(published))
        art = json.load(open(os.path.join(DR.HERE, "out",
                                          "drain-t.json"),
                             encoding="utf-8"))
        check("в артефакте окно убыточно, база прибыльна",
              art["books"]["h4"]["drain"]["pnl"] < 0
              < art["books"]["h4"]["base"]["pnl"],
              str((art["books"]["h4"]["drain"].get("pnl"),
                   art["books"]["h4"]["base"].get("pnl"))))
        DR.main(["--s8", s8, "--tag", "p"])
        check("без флага публикация случилась", bool(published),
              "«публикует по умолчанию» однажды выключится молча")
    finally:
        PT.publish = keep
        DR.HERE = out_was
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_window_bounds_are_inclusive,
             test_slice_stats_pins_numbers,
             test_whole_run_writes_report)
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
