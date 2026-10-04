#!/usr/bin/env python3
"""Тесты разгонного профиля ($100, крупный билет): касса, путь, подмена.

Главные двое: подмена доли билета обязана доехать до настоящей кассы
(`run_paper.build_rows` → `ration`), а штатный путь (`share=None`)
обязан быть тождествен расчёту вовсе без подмены — по отпечатку кассы,
бит в бит. Перестановки проверяются числом на ряде, где просадка
зависит от порядка дней, а итог — нет.

    python3 research/dca_paper/test_boost.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))

import boost as B                                             # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def rec(sym, at, exit_ts, pnl, lev=2.0, book=None):
    """Запись кэша, как её пишет реплей книги: поля живого образца."""
    return {"sym": sym, "at": float(at), "exit_ts": float(exit_ts),
            "pnl": float(pnl), "lev": float(lev), "marks": [],
            "state": "closed", "exit": "take", "side": "long",
            "fwd": 80.0, "entry_px": 1.0, "exit_px": 1.0 + pnl, "avg": 1.0,
            "depth": 1, "fills": [[float(at), 1.0, 25.0]],
            "fav_bp": 100.0, **({"book": book} if book else {})}


DAY = 86400.0
T0 = 1757000000.0                 # произвольная секунда, живой масштаб
CTX = {"error": "тестовый контекст: издержки не считаются"}


def test_day_series_and_geo():
    rows = [{"exit_ts": T0, "usd": 9.0, "usd_gross": 10.0},
            {"exit_ts": T0 + 3600, "usd": -2.0, "usd_gross": -2.0},
            {"exit_ts": T0 + DAY, "usd": -9.5, "usd_gross": -10.0}]
    days = B.day_series(rows)
    check("дни по выходу: два дня, суммы брутто и нетто",
          len(days) == 2 and days[0][1] == 8.0 and days[0][2] == 7.0
          and days[1][1] == -10.0, f"{days}")
    g = B.geo_days(days, 100.0)
    # 100 → 108 → 98: итог −2 %, просадка 10/108, доли 0.08 и −10/108
    check("геометрия дней числом",
          abs(g["final"] + 0.02) < 1e-9
          and abs(g["max_dd_day"] - 10.0 / 108.0) < 1e-9
          and abs(g["fracs"][1] + 10.0 / 108.0) < 1e-9, f"{g}")


def test_perm_path_depends_order_not_total():
    # Дни −30 %, −30 %, +200 %: итог всегда ×1.47, а просадка ≥ 50 %
    # только когда оба минуса идут подряд либо после плюса — ровно в
    # 2 порядках из 3 различимых. P(dd) обязана быть долей, не 0 и не 1.
    fracs = [-0.3, -0.3, 2.0]
    p = B.perm_probs(fracs, 100.0, seeds=900, seed0=7)
    check("просадка зависит от порядка: P строго между 0 и 1",
          p is not None and 0.0 < p["p_dd"] < 1.0, f"{p}")
    check("P(dd) около 2/3 — доля порядков, а не монетка",
          abs(p["p_dd"] - 2.0 / 3.0) < 0.06, f"{p}")
    check("пол $25 не задет: худший путь 49 $", p["p_floor"] == 0.0,
          f"{p}")
    p2 = B.perm_probs([-0.8], 100.0, seeds=50, seed0=7)
    check("день −80 % кладёт счёт ниже пола всегда",
          p2["p_floor"] == 1.0 and p2["p_dd"] == 1.0, f"{p2}")


def test_with_overrides_restores_even_on_error():
    was_dep, was_share = R.DEPOSITS, R.share_in
    try:
        B.with_overrides([100.0], 0.5, lambda: 1 / 0)
    except ZeroDivisionError:
        pass
    check("депозиты и доля возвращены после исключения",
          R.DEPOSITS is was_dep and R.share_in is was_share, "")


def test_share_reaches_the_real_cash():
    """Дорога: доля билета доезжает до ration через build_rows.

    Две позиции пересекаются во времени. Доля 1.0 — весь счёт у первой,
    второй отказ «нет кассы»; доля 0.25 — входят обе. Контроль подмены:
    при штатном билете ($25 на $100 — доля 0.25) отказа тоже нет, то
    есть различает ячейки именно подменённая доля.
    """
    packed = {"safe": [rec("AAA", T0, T0 + 2 * DAY, 0.10),
                       rec("BBB", T0 + DAY, T0 + 3 * DAY, -0.05)]}
    c_full = B.cell(packed, "safe", 100.0, 1.0, CTX, log=lambda *_: None)
    check("доля 1.0: одна лестница за раз, второй — отказ кассы",
          c_full["taken"] == 1 and c_full["no_cash"] == 1, f"{c_full}")
    c_q = B.cell(packed, "safe", 100.0, 0.25, CTX, log=lambda *_: None)
    check("доля 0.25: входят обе", c_q["taken"] == 2
          and c_q["no_cash"] == 0, f"{c_q}")
    # Рунг мельче биржевых $5: доля 0.15 на $100 при плече 1 даёт
    # нотионал 15 и рунг 3.75 — касса обязана отказать «мельче минимума».
    tiny = {"safe": [rec("AAA", T0, T0 + DAY, 0.10, lev=1.0)]}
    c_t = B.cell(tiny, "safe", 100.0, 0.15, CTX, log=lambda *_: None)
    check("рунг мельче $5 — отказ биржи, не сделка",
          c_t["taken"] == 0 and c_t["too_small"] == 1, f"{c_t}")


def test_none_share_is_bitwise_standard():
    packed = {"safe": [rec("AAA", T0, T0 + 2 * DAY, 0.10),
                       rec("BBB", T0 + DAY, T0 + 3 * DAY, -0.05)]}
    a = B.cell(packed, "safe", 1000.0, None, CTX, log=lambda *_: None)
    _rows, cells, _one, _l = RP.build_rows(
        {"safe": list(packed["safe"])}, log=lambda *_: None, keys=["safe"])
    fp0 = (cells.get("safe:1000") or {}).get("fp")
    check("штатная доля тождественна пути без подмены (отпечаток кассы)",
          a.get("fp") is not None and a.get("fp") == fp0,
          f"{a.get('fp')} против {fp0}")


def test_fwd_slice_filters_by_decision_time():
    packed = {"safe": [rec("AAA", T0, T0 + DAY, 0.10),
                       rec("BBB", T0 + 10 * DAY, T0 + 11 * DAY, 0.02)]}
    c = B.cell(packed, "safe", 100.0, 0.25, CTX,
               since=T0 + 5 * DAY, log=lambda *_: None)
    check("хвост окна берёт только решения после границы",
          c["taken"] == 1 and c["n"] == 1, f"{c}")


def main():
    test_day_series_and_geo()
    test_perm_path_depends_order_not_total()
    test_with_overrides_restores_even_on_error()
    test_share_reaches_the_real_cash()
    test_none_share_is_bitwise_standard()
    test_fwd_slice_filters_by_decision_time()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        sys.exit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
