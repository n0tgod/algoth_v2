#!/usr/bin/env python3
"""Проверки скрина хвоста коротких книг.

Кусаются: признаки момента входа берутся из сводки ТОГО часа, чьё
закрытие есть момент входа, а «до входа» — из предыдущих часов через
границу суток; перекос и ход цены считаются той формулой, что напечатана
в отчёте; КАЛИБРОВОЧНАЯ ПАРА — подсаженный признак скрин находит (ноль
перестановок), шум молчит (доля перестановок около половины); «не
измерено» не участвует и посчитано; портрет худших ранжирует по всем
сделкам.
"""
import json
import os
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import tail_screen as T                                       # noqa: E402

# ровный час UTC, чтобы граница суток была в 24 часах позади
AT = 1_789_084_800.0 + 3600.0     # 2026-09-11 01:00 UTC — конец часа 00


def _hour(ts):
    return time.strftime("%Y-%m-%d-%H", time.gmtime(ts))


def _write_hours(root, sym, start_ts, n, fn):
    """n часов сводок подряд, каждый — из `fn(i)`; файлы по дням."""
    by_day = {}
    for i in range(n):
        ts = start_ts + i * 3600.0
        h = _hour(ts)
        by_day.setdefault(h[:10], []).append(dict(fn(i), hour=h))
    os.makedirs(os.path.join(root, sym), exist_ok=True)
    for day, rows in by_day.items():
        with open(os.path.join(root, sym, day + ".jsonl"), "w",
                  encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")


def test_features_come_from_the_entry_hour_and_the_day_before():
    td = tempfile.mkdtemp()
    sym = "AAAUSDT"
    # 30 часов: с −29 до 0 включительно (0 — час решения, конец = AT)
    start = AT - 3600.0 - 29 * 3600.0

    def row(i):
        px = 100.0 + i                       # растёт на 1 $ в час
        return {"mid_close": px, "mid_high": px + 0.5, "mid_low": px - 0.5,
                "spread_bp": 10.0 if i < 29 else 30.0,
                "best_b": 1000.0, "best_a": 2000.0, "depth_eat_b": 300.0,
                "depth_eat_a": 600.0, "big_med": 50.0,
                "n_trades": 100 if i < 29 else 400, "buy": 30.0, "sell": 10.0,
                "vol_max_1s": 5.0, "reach_bp": 20.0, "upd": 3.0, "fr": 0.0001,
                "oi_usd": 1e6 if i < 29 else 1.5e6, "basis_bp": 2.0,
                "liq_short": 7.0, "liq_long": 1.0}
    _write_hours(td, sym, start, 30, row)
    hours = T.Hours(root=td)
    rec = {"sym": sym, "at": AT, "side": "short", "lev": 20.0, "exit": "пол",
           "pnl": -0.8}
    leg = {"fwd": -45.0, "rr": 2.5, "adv_q": 60.0, "odd": 0.7, "beta": 1.1,
           "fwd_z": -1.8}
    f = T.features_of(rec, leg, hours)
    # момент входа — сводка часа 0 (i = 29)
    assert f["spread_bp"] == 30.0 and f["n_trades"] == 400, f
    assert f["touch_usd"] == 1000.0 and f["depth_eat"] == 300.0, f  # шорт: бид
    assert abs(f["imb"] - 0.5) < 1e-9, f["imb"]                      # (30−10)/40
    assert abs(f["range_bp"] - 1.0 / 129.0 * 1e4) < 1e-6, f["range_bp"]
    # до входа: цена росла на 1 $/ч — ход за 1/6/24 ч положителен и растёт
    assert f["ret_1h"] and f["ret_6h"] and f["ret_24h"], f
    assert f["ret_1h"] < f["ret_6h"] < f["ret_24h"], f
    assert abs(f["ret_24h"] - (129.0 / 105.0 - 1.0) * 1e4) < 1e-6, f["ret_24h"]
    # объём 400 против суточной медианы 100, спред 30 против 10, ОИ +50 %
    assert abs(f["vol_ratio"] - 4.0) < 1e-9 and abs(f["spread_ratio"] - 3.0) < 1e-9
    assert abs(f["oi_chg_24h"] - 0.5) < 1e-9, f["oi_chg_24h"]
    assert abs(f["liq_short_24h"] - 24 * 7.0) < 1e-9, f["liq_short_24h"]
    # модель и позиция
    assert f["fwd"] == 45.0 and f["rr"] == 2.5 and f["odd"] == 0.7, f
    assert f["lev"] == 20.0 and f["hour_utc"] == 0.0, (f["lev"], f["hour_utc"])
    # признак без записи — прочерк, а не ноль
    f2 = T.features_of(dict(rec, sym="NOPEUSDT"), None, hours)
    assert f2.get("spread_bp") is None and f2.get("fwd") is None, f2
    assert hours.miss >= 1
    print("ok  признаки: момент входа из часа решения, «до входа» через "
          f"границу суток (ход 24 ч {f['ret_24h']:+.0f} б.п., объём "
          f"×{f['vol_ratio']:g}); без записи — прочерк")


def test_calibration_pair_finds_the_planted_signal_and_stays_silent_on_noise():
    """Подсаженное обязано найтись, шум обязан молчать — иначе сломанная
    загрузка неотличима от «эффекта нет»."""
    rnd = np.random.default_rng(3)
    n = 1200
    tail = rnd.random(n) < 0.15
    planted = np.where(tail, rnd.normal(3.0, 1.0, n), rnd.normal(0.0, 1.0, n))
    noise = rnd.normal(0.0, 1.0, n)
    rows = [{"rec": {"pnl": -1.0 if t else 0.1, "at": AT, "sym": "X"},
             "tail": bool(t),
             "f": {"spread_bp": float(planted[i]), "imb": float(noise[i])}}
            for i, t in enumerate(tail)]
    got = {d["key"]: d for d in T.screen(rows, perms=100)}
    p, q = got["spread_bp"], got["imb"]
    assert p["spread"] is not None and p["spread"] > 0.4, p["spread"]
    assert p["perm"] == 0.0, p["perm"]
    assert q["spread"] is not None and abs(q["spread"]) < 0.08, q["spread"]
    assert q["perm"] > 0.2, q["perm"]
    # поле, которого нет ни у одной сделки, — «лист не несёт», а не ноль
    assert got["odd"].get("why") == "лист этих полей не несёт", got["odd"]
    assert got["spread_bp"]["distinct"] == n, got["spread_bp"]["distinct"]
    print(f"ok  калибровочная пара: подсаженный признак найден (разрыв "
          f"{100 * p['spread']:+.0f} п.п., перестановок не меньше 0 %), шум "
          f"молчит (разрыв {100 * q['spread']:+.0f} п.п., перестановок "
          f"{100 * q['perm']:.0f} %)")


def test_ties_are_broken_at_random_not_by_record_order():
    """Плечо в полосе ≥ 15× почти у всех 25×: устойчивая сортировка
    раскладывала бы равные по порядку записи (по времени), и квинтиль
    мерил бы дату. Хвост, собранный в НАЧАЛЕ записи, при равном признаке
    разрыва давать не должен; признак помечается в отчёте."""
    n = 500
    rows = [{"rec": {"pnl": -1.0 if i < 100 else 0.1, "at": AT, "sym": "X"},
             "tail": i < 100, "f": {"lev": 25.0}} for i in range(n)]
    d = {x["key"]: x for x in T.screen(rows, perms=20)}["lev"]
    assert d["distinct"] == 1, d["distinct"]
    assert d["spread"] is not None and abs(d["spread"]) < 0.15, d["spread"]
    txt = "\n".join(T._table([d], 20))
    assert "плечо †" in txt and "квинтили условны" in txt, txt
    print(f"ok  связи: при равном плече хвост в начале записи даёт разрыв "
          f"{100 * d['spread']:+.0f} п.п. (не −100), признак помечен †")


def test_portrait_ranks_the_worst_against_everyone():
    rows = []
    for i in range(50):
        pnl = -0.9 if i < 5 else 0.05
        rows.append({"rec": {"pnl": pnl, "at": AT, "sym": f"S{i}",
                             "exit": "пол" if i < 5 else "срок"},
                     "tail": i < 5,
                     # у пяти худших плечо самое большое, спред самый малый
                     "f": {"lev": 25.0 if i < 5 else float(i) / 10.0,
                           "spread_bp": 1.0 if i < 5 else float(10 + i)}})
    pt = T.portrait(rows, k=5)
    assert len(pt["worst"]) == 5
    assert pt["median_rank"]["lev"] > 0.9, pt["median_rank"]
    assert pt["median_rank"]["spread_bp"] < 0.15, pt["median_rank"]
    print(f"ok  портрет худших: плечо у края ({pt['median_rank']['lev']:.2f}), "
          f"спред у другого края ({pt['median_rank']['spread_bp']:.2f})")


def test_report_names_the_screen_the_null_and_the_false_positive_budget():
    s = {"rulers": [{"ruler": "safe_s", "title": "безопасная", "n": 100,
                     "n_tail": 15, "n_high": 40, "n_tail_high": 12,
                     "all": [{"key": "spread_bp", "title": "спред, б.п.",
                              "src": "стакан", "n": 100, "missing": 0,
                              "tail_share": 0.15, "med_tail": 30.0,
                              "med_rest": 10.0, "spread": 0.3,
                              "shares": [0.05, 0.1, 0.15, 0.2, 0.35],
                              "perm": 0.0},
                             {"key": "odd", "title": "новизна",
                              "src": "модель", "n": 3, "missing": 97,
                              "why": "сделок с признаком мало"}],
                     "high": [], "portrait": {"worst": [], "median_rank": {}}}],
         "perms": 200, "high_lev": 15.0, "features": len(T.FEATURES),
         "tail_exits": list(T.TAIL_EXITS),
         "hours": {"есть сводка": 100, "нет сводки": 0},
         "computed_at": "2026-09-13 00:00"}
    txt = T.report(s)
    assert "скрин, а не замер правила" in txt, txt[:300]
    assert "ложных находок" in txt and "**спред, б.п.**" in txt, txt[:1500]
    assert "+30.0 п.п." in txt and "5.0 %" in txt and "35.0 %" in txt, txt
    assert "сделок с признаком мало" in txt
    bad = T.report({"error": "кэш реплея непригоден"})
    assert "Не посчитано" in bad
    # отказ печатает константы скрина, а не слово None
    assert "None" not in bad and f"признаков {len(T.FEATURES)}" in bad, bad
    print("ok  отчёт: назван скрин, нуль, бюджет ложных находок; признак "
          "без сделок — причина словами")


if __name__ == "__main__":
    for t in (test_features_come_from_the_entry_hour_and_the_day_before,
              test_calibration_pair_finds_the_planted_signal_and_stays_silent_on_noise,
              test_ties_are_broken_at_random_not_by_record_order,
              test_portrait_ranks_the_worst_against_everyone,
              test_report_names_the_screen_the_null_and_the_false_positive_budget):
        t()
    print("\nвсе 5 проверок прошли")
