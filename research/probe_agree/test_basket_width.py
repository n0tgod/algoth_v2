#!/usr/bin/env python3
"""Проверки замера «ширина согласной корзины».

Дороги настоящие: фикстура пишет `preds.jsonl` и `picks.jsonl` живого
образца, читают их те же `load_sections` и `BB.load_picks`, что и
прогон. Отбор ног обязан воспроизводить правило книги (топ-k с КАЖДОГО
конца, пол по модулю), нога — масштабироваться с шириной, а мост —
отказывать замеру, когда состав из сечения описывает другую книгу.

    cd /home/user/algoth_v2 && .venv/bin/python \
        research/probe_agree/test_basket_width.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import basket_width as BW                                  # noqa: E402

BB = BW.BB
FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


T0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
H = 3600
SYMS = [f"S{i:02d}USDT" for i in range(10)]


def hour_key(ts):
    return datetime.fromtimestamp(ts, timezone.utc) \
        .strftime("%Y-%m-%d-%H")


def section(shift):
    """Сечение часа: прогнозы от −45 до +45 б.п., сдвиг меняет порядок."""
    return [(SYMS[i], round(-45.0 + 10.0 * ((i + shift) % 10), 4))
            for i in range(10)]


def write_fixture(s8, hours=100, arms=("gbm", "nn")):
    """Живой образец: `preds.jsonl` в каталоге МОДЕЛИ, `picks.jsonl` в
    каталоге книги; выборы согласованы с сечением — топ-3 с каждого
    конца, как их делает train.py."""
    mdl = os.path.join(s8, "model")
    bdir = os.path.join(s8, "model_h24")
    os.makedirs(mdl, exist_ok=True)
    os.makedirs(bdir, exist_ok=True)
    pr, pk = [], []
    for j in range(hours):
        ts = T0 + j * H
        for a_i, arm in enumerate(arms):
            row = section(j + 3 * a_i)
            pr.append({"arm": arm, "hour": hour_key(ts),
                       "target": "fwd_24h",
                       "syms": [s for s, _ in row],
                       "pred": [v for _, v in row]})
            legs = BW.pick_n(row, 6, 0.0)
            px = {s: 100.0 + 0.5 * ((j + k) % 7)
                  for k, s in enumerate(SYMS)}
            rec = {"arm": arm, "hour": hour_key(ts), "floor_bp": 0.0,
                   "long": [], "short": []}
            for g in legs:
                rec[g["side"]].append(
                    {"sym": g["sym"], "px": px[g["sym"]], "fwd": 1.0})
            pk.append(rec)
    with open(os.path.join(mdl, "preds.jsonl"), "w",
              encoding="utf-8") as f:
        for r in pr:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(bdir, "picks.jsonl"), "w",
              encoding="utf-8") as f:
        for r in pk:
            f.write(json.dumps(r) + "\n")
    return s8


def mids_fixture(hours=140):
    """Середины дрожат, как живые: ровный ряд вырождает любую меру."""
    out = {}
    for i, s in enumerate(SYMS):
        base = 100.0 + i
        out[s] = {T0 + j * H: base * (1 + 0.0009 * j
                                      * (1 if j % 3 else -1))
                  for j in range(hours)}
    return out


def test_pick_rule():
    row = section(0)
    legs = BW.pick_n(row, 6, 0.0)
    longs = [g["sym"] for g in legs if g["side"] == "long"]
    shorts = [g["sym"] for g in legs if g["side"] == "short"]
    top = [s for s, _ in sorted(row, key=lambda r: -r[1])][:3]
    bot = [s for s, _ in sorted(row, key=lambda r: r[1])][:3]
    check("лонг — крайние сверху сечения", longs == top, str(longs))
    check("шорт — крайние снизу сечения", shorts == bot, str(shorts))
    check("ширина 6 даёт 3+3", len(longs) == 3 and len(shorts) == 3,
          str(legs))
    # Ширина 12 законна только на сечении шире двенадцати: живое
    # сечение — сотни имён, фикстурное из десяти ограничило бы её
    # собой (это отдельная проверка ниже).
    big = [(f"B{i:02d}USDT", float(i) - 20.0) for i in range(40)]
    wide = BW.pick_n(big, 12, 0.0)
    check("ширина 12 даёт 6+6",
          sum(1 for g in wide if g["side"] == "long") == 6
          and sum(1 for g in wide if g["side"] == "short") == 6,
          str(len(wide)))
    # Пол применяется к МОДУЛЮ сырого прогноза: из ±45…±5 при поле 30
    # остаются только |v| ≥ 30, то есть по два конца.
    lim = BW.pick_n(row, 12, 30.0)
    check("пол режет по модулю, а не по знаку",
          all(abs(dict(row)[g["sym"]]) >= 30.0 for g in lim),
          str([(g["sym"], dict(row)[g["sym"]]) for g in lim]))
    # Концы не вправе пересечься: имя в лонге И шорте одной корзины
    # означало бы встречные ноги, а правило реплея такую вторую ногу
    # молча пропускает — ширина вышла бы меньше объявленной, и
    # заметить это было бы нечем.
    huge = BW.pick_n(row, 40, 0.0)
    names = [g["sym"] for g in huge]
    check("сечение уже ширины — имя не берётся дважды",
          len(names) == len(set(names)), str(sorted(names)))
    check("ширина ограничена самим сечением",
          len(huge) == len(row) - len(row) % 2, str(len(huge)))
    narrow = BW.pick_n(row[:5], 12, 0.0)
    nn = [g["sym"] for g in narrow]
    check("нечётное сечение делится без пересечения концов",
          len(nn) == len(set(nn)) and len(nn) == 4, str(nn))


def test_leg_scales():
    check("нога 6 — сайзинг живой книги",
          abs(BW.leg_usd(6) - BB.CAPITAL / 144.0) < 1e-9,
          str(BW.leg_usd(6)))
    check("нога 12 вдвое мельче ноги 6",
          abs(BW.leg_usd(12) * 2 - BW.leg_usd(6)) < 1e-9,
          str(BW.leg_usd(12)))
    check("гросс полной корзины не растёт с шириной",
          abs(BW.leg_usd(30) * 30 * BW.HOLD_H - BB.CAPITAL) < 1e-9,
          str(BW.leg_usd(30) * 30 * BW.HOLD_H))


def test_bridge():
    d = tempfile.mkdtemp()
    try:
        s8 = write_fixture(os.path.join(d, "s8"))
        recorded = BB.load_picks(os.path.join(s8, "model_h24"))
        sections = BW.load_sections(os.path.join(s8, "model"), "fwd_24h")
        check("сечения прочитаны обеими руками",
              set(sections) == {"gbm", "nn"}, str(sorted(sections)))
        built = BW.build(sections, 6, 0.0, mids_fixture())
        share, n = BW.bridge(built, recorded)
        check("мост при N=6 совпадает с записанным выбором",
              share == 1.0 and n > 0, f"{share} на {n}")
        # Состав ДРУГОЙ ширины обязан расходиться с записанным: иначе
        # мост не различал бы книги вовсе.
        wide = BW.build(sections, 12, 0.0, mids_fixture())
        share_w, _ = BW.bridge(wide, recorded)
        check("мост ловит другую ширину", share_w == 0.0, str(share_w))
        check("цель, которой книга не ранжирует, сечений не даёт",
              not BW.load_sections(os.path.join(s8, "model"), "fwd_4h"),
              "")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_e2e_report():
    d = tempfile.mkdtemp()
    was_out, was_mids, was_pub = BW.OUT, BB.BK.load_mids, BW.PT.publish
    calls = []
    try:
        s8 = write_fixture(os.path.join(d, "s8"))
        BW.OUT = os.path.join(d, "out")
        BB.BK.load_mids = lambda syms, log=None: mids_fixture()
        BW.PT.publish = lambda *a, **k: calls.append(1)
        rc = BW.main(["--s8", s8, "--tag", "t", "--no-publish"])
        check("прогон завершился нулём", rc == 0, str(rc))
        path = os.path.join(BW.OUT, "AGREE-width-t.md")
        check("отчёт написан", os.path.exists(path), path)
        md = open(path, encoding="utf-8").read()
        check("мост назван числом в отчёте",
              "Мост: состав из полного сечения при N = 6" in md
              and "1.000 часов" in md, md[:400])
        check("все объявленные ширины в таблице",
              all(f"N={n} · gbm · base" in md for n in BW.WIDTHS),
              str(BW.WIDTHS))
        check("нуль назван по каждой ширине",
              md.count(f"null×{len(BW.SEEDS)}") >= len(BW.WIDTHS),
              str(md.count("null×")))
        check("таблица согласия по ширине есть",
              "## Согласие по ширине" in md, "")
        check("вердикт выведен из чисел",
              "(выведен из чисел)" in md, "")
        check("артефакт json написан",
              os.path.exists(os.path.join(BW.OUT, "agree-width-t.json")),
              "")
        check("с флагом --no-publish публикации нет", not calls,
              str(calls))
        rc = BW.main(["--s8", s8, "--tag", "t"])
        check("без флага публикация обязана случиться",
              rc == 0 and len(calls) == 1, str(calls))
        # Мост ниже порога обязан ОСТАНАВЛИВАТЬ замер, а не считать:
        # цель, которой книга не ранжирует, сечений не даёт вовсе.
        rc = BW.main(["--s8", s8, "--tag", "t2", "--target", "fwd_4h",
                      "--no-publish"])
        check("чужая цель — отказ, а не таблица", rc == 1, str(rc))
        check("отчёта чужой цели нет",
              not os.path.exists(os.path.join(BW.OUT,
                                              "AGREE-width-t2.md")), "")
    finally:
        BW.OUT, BB.BK.load_mids, BW.PT.publish = (was_out, was_mids,
                                                  was_pub)
        shutil.rmtree(d, ignore_errors=True)


def test_bridge_refuses():
    """Плохой мост обязан остановить прогон — с настоящим main()."""
    d = tempfile.mkdtemp()
    was_out, was_mids, was_pub = BW.OUT, BB.BK.load_mids, BW.PT.publish
    try:
        s8 = write_fixture(os.path.join(d, "s8"))
        # Записанные выборы подменены чужими именами: состав из
        # сечения совпасть с ними не может.
        bdir = os.path.join(s8, "model_h24")
        rows = list(BW.PT.read_jsonl(os.path.join(bdir, "picks.jsonl")))
        for r in rows:
            for side in ("long", "short"):
                for g in r.get(side) or []:
                    g["sym"] = "ZZZUSDT"
        with open(os.path.join(bdir, "picks.jsonl"), "w",
                  encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        BW.OUT = os.path.join(d, "out")
        BB.BK.load_mids = lambda syms, log=None: mids_fixture()
        BW.PT.publish = lambda *a, **k: None
        rc = BW.main(["--s8", s8, "--tag", "bad", "--no-publish"])
        check("разошедшийся мост роняет прогон", rc == 1, str(rc))
        check("отчёта при разошедшемся мосте нет",
              not os.path.exists(os.path.join(BW.OUT,
                                              "AGREE-width-bad.md")), "")
    finally:
        BW.OUT, BB.BK.load_mids, BW.PT.publish = (was_out, was_mids,
                                                  was_pub)
        shutil.rmtree(d, ignore_errors=True)


def test_short_history_refuses():
    """Короткая история — диагноз отчётом, а не таблица нулей.

    Живой прогон дал ровно это: `preds.jsonl` — очередь на оценку, в
    ней лежат часы с незакрытым форвардом, и на такой истории не
    закрывается ни одна корзина. Таблица вышла бы из `+0.00`, а ноль
    читается как «денег нет» вместо «не измерено».
    """
    d = tempfile.mkdtemp()
    was_out, was_mids, was_pub = BW.OUT, BB.BK.load_mids, BW.PT.publish
    try:
        s8 = write_fixture(os.path.join(d, "s8"), hours=10)
        BW.OUT = os.path.join(d, "out")
        BB.BK.load_mids = lambda syms, log=None: mids_fixture()
        BW.PT.publish = lambda *a, **k: None
        rc = BW.main(["--s8", s8, "--tag", "sh", "--no-publish"])
        check("короткая история роняет прогон", rc == 1, str(rc))
        path = os.path.join(BW.OUT, "AGREE-width-sh.md")
        check("диагноз написан отчётом", os.path.exists(path), path)
        md = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        check("отчёт называет ОЧЕРЕДЬ причиной",
              "ОЧЕРЕДЬ на оценку" in md, md[:200])
        check("отчёт говорит, чего отказ НЕ означает",
              "не измерена вовсе" in md, "")
        check("таблицы ширин в диагнозе нет",
              "N=12 · gbm · base" not in md, "")
    finally:
        BW.OUT, BB.BK.load_mids, BW.PT.publish = (was_out, was_mids,
                                                  was_pub)
        shutil.rmtree(d, ignore_errors=True)


def test_unclosed_is_mark_not_zero():
    """Корзина без единого закрытия — отметка, а не реализованный ноль."""
    c = {"realized": 0.0, "baskets": 0, "n_take": 0, "n_floor": 0,
         "n_age": 0, "worst_basket": None, "max_dd": 0.0,
         "open_mark": -12.5}
    row = BW.cell_row("N=6 · gbm · agreed", c)
    check("не закрывшаяся корзина названа словом",
          "не закрылась ни разу" in row, row)
    check("реализованного нуля в строке нет",
          "+0.00" not in row, row)
    check("отметка хвоста названа числом", "-12.50" in row, row)
    closed = dict(c, baskets=3, n_age=3, realized=7.25,
                  worst_basket=-2.0)
    check("закрывшаяся корзина печатает реализованное",
          "+7.25" in BW.cell_row("x", closed), BW.cell_row("x", closed))


def main():
    tests = (test_pick_rule, test_leg_scales, test_bridge,
             test_e2e_report, test_bridge_refuses,
             test_short_history_refuses, test_unclosed_is_mark_not_zero)
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
