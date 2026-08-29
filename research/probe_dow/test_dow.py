#!/usr/bin/env python3
"""Проверки зонда дней недели.

Главная — калибровочная ПАРА (урок W1): зонд обязан НАЙТИ подсаженный
день и промолчать на чистом шуме. Без пары отрицательный результат не
значит ничего: сломанная метка дня выглядит ровно как «эффекта нет».
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(os.path.dirname(HERE), "r2_residual"),
          os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dow as DW                                           # noqa: E402
import nulls as N                                          # noqa: E402
import turn as PT                                          # noqa: E402

FAILED = []


def check(name, cond, note=""):
    print(("ok  " if cond else "ПРОВАЛ") + " " + name
          + ("" if cond else f" · {note}"))
    if not cond:
        FAILED.append(name)


def test_dow_labels_pinned():
    """Метка дня закреплена ЧИСЛОМ по известным датам."""
    check("2026-08-24 — понедельник", DW.dow_of("2026-08-24") == 0)
    check("2026-08-29 — суббота", DW.dow_of("2026-08-29") == 5)
    check("2026-08-30 — воскресенье", DW.dow_of("2026-08-30") == 6)


def _rows(days=700, sat_bump=0.0, seed=3):
    """Синтетика: сечение в день, спред — шум, суббота +sat_bump б.п."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(days):
        dow = i % 7                       # 0…6 равномерно
        sp = float(rng.normal(5.0, 40.0))
        if dow == 5:
            sp += sat_bump
        rows.append({"date": f"d{i}", "dow": dow, "ic": sp / 1e3,
                     "spread_bp": sp})
    return rows


def test_planted_day_is_found_and_noise_is_quiet():
    """Калибровочная пара: подсаженная суббота переживает планку,
    чистый шум — нет."""
    hot = DW.family_null(_rows(sat_bump=40.0), "spread_bp", perms=400)
    check("подсаженная суббота переживает планку",
          hot["max_dev"] > hot["bar95"]
          and abs(hot["dev"][5]) == hot["max_dev"],
          f"dev {hot['max_dev']:.1f} при планке {hot['bar95']:.1f}")
    check("выходные − будни видят подсадку и p мал",
          hot["weekend_diff"] > 10 and hot["weekend_p"] < 0.01,
          str((hot["weekend_diff"], hot["weekend_p"])))
    cold = DW.family_null(_rows(sat_bump=0.0), "spread_bp", perms=400)
    check("чистый шум планку не переживает",
          cold["max_dev"] <= cold["bar95"],
          f"dev {cold['max_dev']:.1f} при планке {cold['bar95']:.1f}")
    check("на шуме p выходных не мал", cold["weekend_p"] > 0.05,
          str(cold["weekend_p"]))


def test_null_is_reproducible():
    """Зерно числом: два прогона нуля дают ОДНИ числа (урок R3)."""
    a = DW.family_null(_rows(), "spread_bp", perms=200)
    b = DW.family_null(_rows(), "spread_bp", perms=200)
    check("нуль воспроизводим", a["bar95"] == b["bar95"]
          and a["weekend_p"] == b["weekend_p"],
          f"{a['bar95']} против {b['bar95']}")


def test_whole_run_writes_report():
    """Сквозной прогон на подставных векторах: отчёт, обе ячейки,
    публикация по флагу. Подставной артефакт выглядит как живой —
    даты настоящие, недели идут подряд."""
    from datetime import datetime, timedelta, timezone
    root = tempfile.mkdtemp()
    vec_was, here_was = N.VECTORS, DW.HERE
    published = []
    keep_pub = PT.publish
    try:
        N.VECTORS = os.path.join(root, "vectors")
        os.makedirs(N.VECTORS)
        rng = np.random.default_rng(11)
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        dump = {}
        for i in range(210):                     # 30 недель
            d = (t0 + timedelta(days=i)).date().isoformat()
            n = 60
            sig = rng.normal(0, 1, n)
            # Подсадка выходных — в СИЛЕ связи сигнала с форвардом, а
            # не сдвигом уровня: длинно-короткая корзина к константе
            # слепа по построению (спред — разность средних, и общий
            # сдвиг дня сокращается). Первая версия фикстуры добавляла
            # константу — и «подсаженный» эффект не существовал.
            beta = (0.15 if DW.dow_of(d) in DW.WEEKEND else 0.04)
            fwd = beta * sig + rng.normal(0, 1, n)
            dump[d] = {"names": [f"S{j}" for j in range(n)],
                       "sig": {"7": sig.tolist(), "14": sig.tolist()},
                       "fwd": {"1": (fwd / 1e2).tolist()}}
        with open(os.path.join(N.VECTORS, "1m_all.json"), "w",
                  encoding="utf-8") as f:
            json.dump(dump, f)
        DW.HERE = os.path.join(root, "probe_dow")
        PT.publish = lambda: published.append(1)
        s8 = os.path.join(root, "s8", "out")     # пусто: книг нет
        os.makedirs(s8)
        rc = DW.main(["--tag", "t", "--no-publish", "--s8", s8])
        check("прогон дошёл до конца", rc == 0, str(rc))
        rep = os.path.join(DW.HERE, "out", "DOW-report-t.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("обе ячейки в отчёте",
              "k=7, h=1" in txt and "k=14, h=1" in txt, txt[:300])
        check("именованные варианты владельца названы",
              "Только\nвыходные" in txt.replace("«", "\n«")
              .replace("\n", " ") or "только выходные" in txt.lower(),
              "нет вариантов")
        check("живой разрез назван анекдотом",
              "анекдот, не замер" in txt, "оговорки нет")
        art = json.load(open(os.path.join(
            DW.HERE, "out", "dow-t.json"), encoding="utf-8"))
        wd = art["cells"]["k7_h1"]["fam_spread"]["weekend_diff"]
        check("подсадка выходных видна в артефакте числом",
              wd is not None and wd > 5, str(wd))
        check("с флагом публикации нет", not published, str(published))
        DW.main(["--tag", "p", "--s8", s8])
        check("без флага публикация случилась", bool(published))
    finally:
        N.VECTORS, DW.HERE = vec_was, here_was
        PT.publish = keep_pub
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_dow_labels_pinned,
             test_planted_day_is_found_and_noise_is_quiet,
             test_null_is_reproducible,
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
