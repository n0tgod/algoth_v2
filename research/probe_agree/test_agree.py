#!/usr/bin/env python3
"""Проверки зонда согласия: флаг из выборов, нуль внутри дня,
находит подсаженное и молчит на ровном."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agree as AG                                        # noqa: E402

FAILED = []


def check(name, cond, note=""):
    print(("ok  " if cond else "ПРОВАЛ") + " " + name
          + ("" if cond else f" · {note}"))
    if not cond:
        FAILED.append(name)


def test_flag_from_picks_not_rows():
    """Флаг — из выборов ДРУГОЙ руки, даже когда её сделка не дожила
    до закрытия (схлопнулась, без исхода): фильтр обязан быть знанием
    момента входа, а не выживания."""
    keys = {"gbm": {("h1", "AAA", "long"), ("h1", "BBB", "long")},
            "nn": {("h1", "AAA", "long")}}
    rows = [{"arm": "gbm", "hour": "h1", "sym": "AAA", "side": "long"},
            {"arm": "gbm", "hour": "h1", "sym": "BBB", "side": "long"},
            {"arm": "nn", "hour": "h1", "sym": "AAA", "side": "long"}]
    AG.flag_rows(rows, keys)
    check("обе руки выбрали — согласие",
          rows[0]["agree"] and rows[2]["agree"], str(rows))
    check("одна рука — одиночная", not rows[1]["agree"], str(rows))
    # У nn НЕТ закрытой строки по BBB, но и выбора нет — а по AAA
    # выбор есть: закрытые строки в флаге не участвуют вовсе.
    keys2 = {"gbm": {("h1", "CCC", "short")},
             "nn": {("h1", "CCC", "short")}}
    r2 = [{"arm": "gbm", "hour": "h1", "sym": "CCC", "side": "short"}]
    AG.flag_rows(r2, keys2)
    check("согласие без закрытой строки другой руки",
          r2[0]["agree"], str(r2))


def test_pick_keys_reads_both_sides(tmp=None):
    import json
    import tempfile
    import shutil
    root = tempfile.mkdtemp()
    try:
        with open(os.path.join(root, "picks.jsonl"), "w",
                  encoding="utf-8") as f:
            f.write(json.dumps({
                "arm": "gbm", "hour": "2026-08-30-10",
                "long": [{"sym": "AAAUSDT", "px": 1.0, "size": 0.0}],
                "short": [{"sym": "BBBUSDT", "px": 2.0}]}) + "\n")
            f.write(json.dumps({
                "arm": "nn", "hour": "2026-08-30-10",
                "long": [{"sym": "AAAUSDT", "px": 1.0}],
                "short": []}) + "\n")
        k = AG.pick_keys(root)
        check("ключи выбора: обе стороны и нулевой размер",
              ("2026-08-30-10", "AAAUSDT", "long") in k["gbm"]
              and ("2026-08-30-10", "BBBUSDT", "short") in k["gbm"]
              and ("2026-08-30-10", "AAAUSDT", "long") in k["nn"],
              str(k))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def synth_trades(n_days=40, per_day=20, planted=0.0, seed=9):
    """Сделки одной ячейки: половина согласных; `planted` — сдвиг
    нетто согласных в б.п."""
    rng = np.random.default_rng(seed)
    t0 = 1_756_000_000
    out = []
    for d in range(n_days):
        for i in range(per_day):
            agree = i % 2 == 0
            net = float(rng.normal(scale=60.0))
            if agree:
                net += planted
            out.append({"ts": t0 + d * 86400 + i * 600,
                        "sym": f"S{i % 7}", "agree": agree,
                        "net": net})
    return out


def test_null_finds_planted_and_stays_silent():
    tr = synth_trades(planted=40.0)
    c = AG.cell_stats(tr)
    check("подсаженный сдвиг найден",
          c["measured"] and c["delta_mean"] > 20
          and c["p_perm"] < 0.05, str(c))
    check("знак держится в обеих половинах",
          c["halves"][0] > 0 and c["halves"][1] > 0, str(c["halves"]))
    flat = AG.cell_stats(synth_trades(planted=0.0))
    check("на ровном — не значимо", flat["p_perm"] > 0.1,
          str(flat["p_perm"]))
    thin = AG.cell_stats(synth_trades(n_days=2, per_day=10))
    check("тонкая ячейка не измерена, а не нулевая",
          not thin["measured"], str(thin))


def test_null_preserves_day_counts():
    """Нуль тасует флаги ВНУТРИ дня: перестановка не смешивает дни —
    иначе эффект дня (слив) выдал бы себя за эффект согласия. Проверка
    прямая: сдвиг, живущий ЦЕЛЫМИ днями (в чётные дни всё лучше и
    доля согласных выше), внутри дня не создаёт разницы — p обязан
    быть большим."""
    rng = np.random.default_rng(4)
    t0 = 1_756_000_000
    tr = []
    for d in range(40):
        good_day = d % 2 == 0
        n_agr = 14 if good_day else 6
        for i in range(20):
            tr.append({"ts": t0 + d * 86400 + i * 600,
                       "sym": f"S{i % 7}",
                       "agree": i < n_agr,
                       "net": float(rng.normal(
                           loc=40.0 if good_day else -40.0,
                           scale=20.0))})
    c = AG.cell_stats(tr)
    check("эффект дня не выдаёт себя за согласие (p большой)",
          c["p_perm"] > 0.1, str((c["delta_mean"], c["p_perm"])))


def test_report_and_reading():
    import tempfile
    import shutil
    root = tempfile.mkdtemp()
    try:
        good = AG.cell_stats(synth_trades(planted=40.0))
        flat = AG.cell_stats(synth_trades(planted=0.0, seed=10))
        p = AG.write_report(
            os.path.join(root, "r.md"),
            {"h4 · gbm": good, "h4 · nn": flat},
            {"sit_obs · gbm": flat},
            {"when": "тест"})
        txt = open(p, encoding="utf-8").read()
        check("оговорка R5 на странице", "ошибка R5" in txt)
        check("обе группы в таблице числом",
              "/" in txt and "не измерена" not in txt.split("##")[1],
              txt[:200])
        r_neg = AG.reading({"a": flat})
        check("вывод на ровном — «реже, а не лучше»",
              "реже, а не лучше" in r_neg, r_neg)
        r_pos = AG.reading({"a": good})
        check("вывод на живом — повод считать спеку",
              "повод" in r_pos, r_pos)
    finally:
        shutil.rmtree(root, ignore_errors=True)




def test_drain_split_boundaries():
    """Разрез окна слива: границы ВКЛЮЧИТЕЛЬНО, день — UTC по моменту
    денег, худшее имя — по сумме $ группы."""
    import drain as DR
    from datetime import datetime, timezone

    def at(day, h=12):
        return datetime.fromisoformat(day + "T00:00:00+00:00") \
            .timestamp() + h * 3600
    rows = [
        {"ts": at("2026-08-23"), "sym": "A", "net": 10, "pnl": 1.0,
         "agree": True},
        {"ts": at("2026-08-24", 0), "sym": "B", "net": -100,
         "pnl": -5.0, "agree": True},
        {"ts": at("2026-08-27", 23), "sym": "C", "net": -300,
         "pnl": -9.0, "agree": False},
        {"ts": at("2026-08-28", 0), "sym": "D", "net": 20, "pnl": 2.0,
         "agree": False},
    ]
    out = DR.split_cell(rows)
    check("границы окна включительно (24-е 00ч и 27-е 23ч внутри)",
          out["слив"]["agree"]["n"] == 1
          and out["слив"]["solo"]["n"] == 1, str(out["слив"]))
    check("соседние дни — вне окна",
          out["вне"]["agree"]["n"] == 1
          and out["вне"]["solo"]["n"] == 1, str(out["вне"]))
    check("худшее имя одиночных в сливе — C",
          out["слив"]["solo"]["worst_sym"] == "C",
          str(out["слив"]["solo"]))
    check("тонкая часть помечена, p не считается",
          out["слив"]["thin"] and out["слив"]["p"] is None, "")
    days = DR.by_day_table(rows, ["2026-08-24", "2026-08-25"])
    check("дневная таблица: 24-е несёт согласную, 25-е пусто",
          days[0][1]["n"] == 1 and days[1][1]["n"] == 0
          and days[1][2]["n"] == 0, str(days))


def main():
    tests = (test_flag_from_picks_not_rows,
             test_drain_split_boundaries,
             test_pick_keys_reads_both_sides,
             test_null_finds_planted_and_stays_silent,
             test_null_preserves_day_counts,
             test_report_and_reading)
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
