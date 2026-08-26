#!/usr/bin/env python3
"""
Тесты funding-замера месячной книги.

Столпы: ЗНАК закреплён числом (лонг с положительной ставкой платит,
шорт получает — перепутанный знак перевернул бы вердикт замера, ничем
себя не выдав); нога без ряда — не ноль (замороженный ряд в новом
костюме); встроенная сверка с артефактом зонда кусается.

    python3 research/probe_monthly/test_funding_cost.py
"""

import gzip
import io
import contextlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import funding_cost as FC                                 # noqa: E402
import probe as P                                         # noqa: E402
import test_probe as TP                                   # noqa: E402
import nulls as N                                         # noqa: E402
import run_d1 as R                                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def ms_of(iso):
    return int(datetime.fromisoformat(iso).replace(
        tzinfo=timezone.utc).timestamp() * 1000)


def series(day_from, n_accruals, rate, step_h=8):
    """Ряд funding: начисления каждые step_h часов от полуночи."""
    t0 = ms_of(day_from)
    t = np.array([t0 + i * step_h * 3600 * 1000
                  for i in range(n_accruals)], dtype=np.int64)
    r = np.full(n_accruals, rate, dtype=np.float64)
    return (t, r)


def test_sign_by_number():
    """Лонг с положительной ставкой ПЛАТИТ, шорт ПОЛУЧАЕТ — числом.

    A: +0.5 веса, ставка 1e-3 × 3 начисления → издержка +15 б.п.;
    B: −0.5 веса, ставка 2e-3 × 3 → −30. Книга: −15 (получает)."""
    funding = {"A": series("2024-02-01", 3, 1e-3),
               "B": series("2024-02-01", 3, 2e-3)}
    w = {"A": 0.5, "B": -0.5}
    tot, lc, sc, un = FC.funding_of_book(funding, w, "2024-02-01", 30)
    check("издержка лонга +15 б.п.", abs(lc - 15.0) < 1e-9, f"{lc}")
    check("шорт получает −30 б.п.", abs(sc + 30.0) < 1e-9, f"{sc}")
    check("итог книги −15 б.п.", abs(tot + 15.0) < 1e-9, f"{tot}")
    check("недоучёта нет", un == 0.0, f"{un}")


def test_missing_leg_is_not_zero():
    """Нога без ряда — недоучтённый гросс, а не нулевая издержка."""
    funding = {"A": series("2024-02-01", 3, 1e-3)}
    w = {"A": 0.5, "C": -0.5}
    tot, lc, sc, un = FC.funding_of_book(funding, w, "2024-02-01", 30)
    check("недоучтённый гросс равен весу ноги", un == 0.5, f"{un}")
    check("итог считан только по покрытым",
          abs(tot - 15.0) < 1e-9, f"{tot}")


def test_accrual_count_comes_from_the_series():
    """Та же ставка вдвое чаще — вдвое дороже (правило A1: число
    начислений по ряду, не по объявленному интервалу)."""
    f8 = {"A": series("2024-02-01", 90, 1e-4, step_h=8)}
    f4 = {"A": series("2024-02-01", 180, 1e-4, step_h=4)}
    w = {"A": 1.0}
    t8, *_ = FC.funding_of_book(f8, w, "2024-02-01", 30)
    t4, *_ = FC.funding_of_book(f4, w, "2024-02-01", 30)
    check("частота начислений удваивает издержку",
          abs(t4 - 2 * t8) < 1e-9, f"{t4} против 2×{t8}")


def test_window_bounds():
    """Начисление до окна и ровно на его правой границе не входит."""
    t = np.array([ms_of("2024-01-31"), ms_of("2024-02-01"),
                  ms_of("2024-03-02")], dtype=np.int64)
    funding = {"A": (t, np.array([1e-3, 1e-3, 1e-3]))}
    tot, *_ = FC.funding_of_book(funding, {"A": 1.0}, "2024-02-01", 30)
    check("окно [t, t+30): вошло одно начисление",
          abs(tot - 10.0) < 1e-9, f"{tot}")


def test_crosscheck_bites():
    cells = {"k14_h30": {"net0_median_bp": 10.0, "net0_mean_bp": 5.0}}
    ok_art = {"cells": {"k14_h30": {"net_median_bp": 10.0,
                                    "net_mean_bp": 5.0}}}
    bad_art = {"cells": {"k14_h30": {"net_median_bp": 10.0,
                                     "net_mean_bp": 7.0}}}
    check("совпадение проходит", FC.crosscheck(cells, ok_art) == [], "")
    check("расхождение ловится",
          len(FC.crosscheck(cells, bad_art)) == 1, "")


def test_verdict_phrase():
    alive = {"funding_mean_bp": 20.0, "net0_mean_bp": 90.0,
             "netf_mean_bp": 70.0, "netf_median_bp": 100.0}
    split = {"funding_mean_bp": 90.0, "net0_mean_bp": 90.0,
             "netf_mean_bp": -5.0, "netf_median_bp": 30.0}
    dead = {"funding_mean_bp": 120.0, "net0_mean_bp": 90.0,
            "netf_mean_bp": -30.0, "netf_median_bp": -10.0}
    check("обе меры в плюс — «не убивает»",
          "не убивает" in FC.verdict_phrase(alive),
          FC.verdict_phrase(alive))
    check("расхождение знака названо хвостом",
          "подпись хвоста" in FC.verdict_phrase(split),
          FC.verdict_phrase(split))
    check("обе в минус — «съедает»",
          "съедает" in FC.verdict_phrase(dead), FC.verdict_phrase(dead))
    check("нет ячейки — нет фразы",
          "не измерена" in FC.verdict_phrase(None), "")


def write_funding_dir(fdir, names, rate=1e-6, day_from="2024-01-01",
                      n=2000):
    os.makedirs(fdir, exist_ok=True)
    for a in names:
        t, r = series(day_from, n, rate)
        with gzip.open(os.path.join(fdir, f"{a}USDT.csv.gz"), "wt",
                       encoding="utf-8") as f:
            f.write("funding_time,funding_rate\n")
            for ti, ri in zip(t, r):
                f.write(f"{ti},{ri}\n")


def write_universe(path, names):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"assets": {a: {"bybit_symbol": f"{a}USDT"}
                              for a in names}}, f)


def run_funding_main(out, fdir, upath, vdir):
    argv, pub, vd = sys.argv, R.publish, N.VECTORS
    R.publish = lambda msg: None
    N.VECTORS = vdir
    sys.argv = ["funding_cost.py", "--interval", "1m", "--tag", "t",
                "--out", out, "--funding-dir", fdir,
                "--universe", upath, "--no-publish"]
    try:
        FC.main()
    finally:
        sys.argv, R.publish, N.VECTORS = argv, pub, vd
    return json.load(open(os.path.join(out, "MONTHLY-funding-t.json"),
                          encoding="utf-8"))


def test_end_to_end():
    """Сквозной: артефакт зонда настоящим probe.main, затем funding
    поверх него; сверка обязана пройти, фраза — следовать числам."""
    tmp = tempfile.mkdtemp()
    try:
        vec = TP.synth_vec(n_days=400)
        vdir = os.path.join(tmp, "v")
        TP.write_vectors(vec, vdir)
        out = os.path.join(tmp, "out")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            TP.run_main(vdir, out)
        names = sorted({n for v in vec.values() for n in v["names"]})
        fdir = os.path.join(tmp, "funding")
        write_funding_dir(fdir, names)
        upath = os.path.join(tmp, "universe.json")
        write_universe(upath, names)
        with contextlib.redirect_stdout(buf):
            art = run_funding_main(out, fdir, upath, vdir)
        c = art["cells"].get(P.MAIN_CELL)
        check("главная ячейка измерена", c is not None,
              f"{sorted(art['cells'])}")
        check("сверка с зондом чистая", art["crosscheck_bad"] == 0, "")
        check("нетто-с-funding = нетто − funding",
              c is not None and abs(
                  (c["net0_mean_bp"] - c["funding_mean_bp"])
                  - c["netf_mean_bp"]) < 0.11,
              c and f"{c['net0_mean_bp']} − {c['funding_mean_bp']} ≠ "
                    f"{c['netf_mean_bp']}")
        v = art["verdict"]
        ok = ("не убивает" in v) == (c["netf_mean_bp"] > 0
                                     and c["netf_median_bp"] > 0)
        check("фраза согласована с числами", ok, v)
        md = open(os.path.join(out, "MONTHLY-funding-t.md"),
                  encoding="utf-8").read()
        check("отчёт несёт разложение по ногам",
              "Лонги" in md or "лонги" in md, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tampered_probe_artifact_stops_the_run():
    """Подделанный артефакт зонда останавливает замер: funding,
    посчитанный другим книгам, недействителен."""
    tmp = tempfile.mkdtemp()
    try:
        vec = TP.synth_vec(n_days=400)
        vdir = os.path.join(tmp, "v")
        TP.write_vectors(vec, vdir)
        out = os.path.join(tmp, "out")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            TP.run_main(vdir, out)
        ap = os.path.join(out, "MONTHLY-t.json")
        art = json.load(open(ap, encoding="utf-8"))
        art["cells"][P.MAIN_CELL]["net_mean_bp"] += 5.0
        json.dump(art, open(ap, "w", encoding="utf-8"))
        names = sorted({n for v in vec.values() for n in v["names"]})
        fdir = os.path.join(tmp, "funding")
        write_funding_dir(fdir, names)
        upath = os.path.join(tmp, "universe.json")
        write_universe(upath, names)
        raised = False
        try:
            with contextlib.redirect_stdout(buf):
                run_funding_main(out, fdir, upath, vdir)
        except SystemExit as e:
            raised = "недействителен" in str(e)
        check("подделанный артефакт останавливает прогон", raised,
              "прошёл")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("знак и окно")
    test_sign_by_number()
    test_missing_leg_is_not_zero()
    test_accrual_count_comes_from_the_series()
    test_window_bounds()
    print("сверка и фразы")
    test_crosscheck_bites()
    test_verdict_phrase()
    print("сквозной прогон")
    test_end_to_end()
    test_tampered_probe_artifact_stops_the_run()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
