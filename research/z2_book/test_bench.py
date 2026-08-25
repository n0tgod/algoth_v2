#!/usr/bin/env python3
"""Проверки замера цены разбора лесенки.

Дорог у одноразового замера несколько (выборка строк, разбор лесенки,
сборка отчёта, публикация), и «тесты зелёные» значит ровно те дороги,
которые тесты ИСПОЛНЯЮТ — урок трёх падений зонда S11.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bench_ladder as BL                                 # noqa: E402
import fold as F                                          # noqa: E402
from test_probe import check, write_rec, FAILED           # noqa: E402


def _setup(days, syms):
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE, BL.F.BOOK, BL.F.STORE)
    F.BOOK = os.path.join(root, "book")
    F.TRADES = os.path.join(root, "trades")
    F.STORE = os.path.join(root, "store")
    write_rec(root, syms, days, hours=(10,), per_min=4, seed=7)
    for d in days:
        F.fold_day(d, syms=syms, log=lambda m: None,
                   now=time.time() + 10 * 86400)
    return root, old


def test_ladder_parse_matches_json_and_is_measured_on_live_lines():
    """Разбор лесенки обязан совпасть с `json.loads` дословно.

    Быстрый разбор, расходящийся с медленным, есть другая мера — тот же
    урок, что закреплён на лёгком разборе заголовка.
    """
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms)
    try:
        got = BL.sample_lines(days[0], log=lambda m: None)
        check("живые строки набрались", len(got) == 2
              and all(v for v in got.values()), str(list(got)))
        line = next(iter(got.values()))[0]
        import json
        bb, aa = BL.ladder(line)
        rec = json.loads(line)
        check("лесенка совпала с json дословно",
              bb.tolist() == rec["b"] and aa.tolist() == rec["a"],
              f"{bb.tolist()} против {rec['b']}")
        res = BL.measure(days[0], log=lambda m: None)
        r = res["rows"][0]
        check("три разбора измерены числами",
              all(r[k] and r[k] > 0 for k in ("light", "json", "ladder")),
              str(r))
        check("число снимков взято из склада, а не из допущения",
              res["snaps"] == 2 * 4 * 60, str(res["snaps"]))
    finally:
        (F.BOOK, F.TRADES, F.STORE, BL.F.BOOK, BL.F.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_report_names_the_price_of_both_passes():
    """Отчёт обязан назвать и сплошной проход, и точечный.

    Сплошной без точечного читался бы как «лесенка недоступна», хотя
    меры её событийные и стоят на два порядка меньше.
    """
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms)
    try:
        res = BL.measure(days[0], log=lambda m: None)
        p = BL.write_report(res, log=lambda m: None)
        txt = open(p, encoding="utf-8").read()
        check("сплошной проход назван",
              "Сплошной проход по лесенке" in txt and "ч на КАЖДЫЕ сутки"
              in txt, txt[:600])
        # Строки таблицы считаются ЧИСЛОМ: заголовок стоит и у пустой
        # таблицы, и первый отрицательный контроль прошёл мимо ровно
        # поэтому — «блок есть» проходит на пустом блоке.
        body = txt[txt.find("| событий | строк | часов |"):]
        n = len([l for l in body.splitlines()
                 if l.startswith("| ") and "млн" in l])
        check("точечный проход назван таблицей из строк",
              "Точечный проход" in txt and n == 3, f"строк {n}")
        check("отношение к лёгкому разбору напечатано",
              "лесенка/лёгкий" in txt, txt[:600])
        check("прочерк вместо нуля у неизмеренного",
              "0.0×" not in txt, txt[:600])
    finally:
        (F.BOOK, F.TRADES, F.STORE, BL.F.BOOK, BL.F.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_publish_is_part_of_the_run():
    """С ключом публикации нет, без ключа она ОБЯЗАНА случиться."""
    days = ["2026-08-20"]
    syms = ["AAAUSDT"]
    root, old = _setup(days, syms)
    said = []
    orig, BL.publish = BL.publish, said.append
    try:
        BL.main(["--day", days[0], "--lines", "50", "--no-publish"])
        check("с ключом публикации нет", not said, str(said))
        BL.main(["--day", days[0], "--lines", "50"])
        check("без ключа публикация случилась", len(said) == 1, str(said))
    finally:
        BL.publish = orig
        (F.BOOK, F.TRADES, F.STORE, BL.F.BOOK, BL.F.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (
        test_ladder_parse_matches_json_and_is_measured_on_live_lines,
        test_report_names_the_price_of_both_passes,
        test_publish_is_part_of_the_run,
    )
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
