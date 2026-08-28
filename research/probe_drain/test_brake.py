#!/usr/bin/env python3
"""Проверки реплея: хронология тормоза, отсутствие заглядывания у хода.

Обе механики легко соврать в свою пользу: тормоз, видящий деньги ещё
не выброшенной сделки, тормозил бы задним числом, а ход, взятый с часа
самого входа, заглядывал бы в будущее. Обе дороги закреплены числами.
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

import brake as BK                                         # noqa: E402
import drain as DR                                         # noqa: E402
import turn as PT                                          # noqa: E402

FAILED = []


def check(name, cond, note=""):
    print(("ok  " if cond else "ПРОВАЛ") + " " + name
          + ("" if cond else f" · {note}"))
    if not cond:
        FAILED.append(name)


def _t(h, pnl, dh=4, sym="AAAUSDT", side="long", book="h4", arm="gbm"):
    t_in = DR.day_int("2026-08-25") * 86400 + h * 3600
    t_money = t_in + dh * 3600
    return {"t_in": t_in, "t_money": t_money,
            "day": int(t_money // 86400), "pnl": pnl, "net": pnl * 10,
            "sym": sym, "side": side, "book": book, "arm": arm}


def test_brake_chronology():
    """Тормоз видит только деньги, известные ДО входа, и только от
    принятых сделок."""
    g = lambda t: (t["book"], t["arm"])                   # noqa: E731
    # −40 стало известно в 04+4=08:00; вход в 09:00 при X=30 заперт,
    # вход в 07:00 — ещё нет (деньги не известны)
    tr = [_t(4, -40.0), _t(7, -40.0), _t(9, -10.0)]
    dropped = BK.replay_brake(tr, 30.0, g)
    check("вход после известного −40 заперт",
          len(dropped) == 1 and dropped[0]["t_in"] == tr[2]["t_in"],
          str([d["t_in"] % 86400 // 3600 for d in dropped]))
    # накопление: −40 и −40 приняты, вход 15:00 видит −80 ≤ −60
    tr2 = [_t(4, -40.0), _t(9, -40.0, dh=2), _t(15, -10.0)]
    d3 = BK.replay_brake(tr2, 60.0, g)
    check("накопленный минус двух принятых запирает третий",
          len(d3) == 1 and d3[0]["t_in"] == tr2[2]["t_in"],
          str([x["t_in"] % 86400 // 3600 for x in d3]))
    # деньги ВЫБРОШЕННОЙ сделки не существуют: −60 запирает вход
    # 09:00 с pnl +100; если бы его плюс засчитался, реализованное
    # стало бы +40 и вход 11:00 остался бы — а он обязан быть заперт
    tr4 = [_t(4, -60.0), _t(9, +100.0, dh=1), _t(11, -10.0)]
    d4 = BK.replay_brake(tr4, 50.0, g)
    check("деньги выброшенной сделки не существуют",
          len(d4) == 2 and d4[0]["t_in"] == tr4[1]["t_in"]
          and d4[1]["t_in"] == tr4[2]["t_in"],
          str([x["t_in"] % 86400 // 3600 for x in d4]))
    # группы независимы: минус чужой руки не запирает нашу
    tr3 = [_t(4, -100.0, arm="gbm"), _t(9, -10.0, arm="nn")]
    check("чужая рука не тормозит",
          BK.replay_brake(tr3, 30.0, lambda t: (t["book"], t["arm"]))
          == [], "заперло чужим минусом")
    check("одной группой — тормозит",
          len(BK.replay_brake(tr3, 30.0, lambda t: "all")) == 1)


def test_runup_uses_closed_hour():
    """Ход берётся с последнего ЗАКРЫТОГО часа перед входом."""
    day0 = DR.day_int("2026-08-25") * 86400
    mids = {"AAAUSDT": {day0 - 2 * 86400 + 9 * 3600: 100.0,
                        day0 + 9 * 3600: 150.0,      # закрытие 09:00
                        day0 + 10 * 3600: 300.0}}    # час входа — нельзя
    t_in = day0 + 10 * 3600 + 600                    # вход 10:10
    v = BK.runup(mids, "AAAUSDT", t_in, 2)
    check("ход +50 % по закрытому часу, не +200 % по часу входа",
          v is not None and abs(v - 0.5) < 1e-9, str(v))
    check("нет ряда — ход не измерен",
          BK.runup(mids, "BBBUSDT", t_in, 2) is None)
    check("нет опорной точки — не измерен",
          BK.runup(mids, "AAAUSDT", t_in, 5) is None)


def test_runup_table_counts():
    day_d = DR.day_int("2026-08-25") * 86400
    day_b = DR.day_int("2026-08-15") * 86400
    mids = {"PUMPUSDT": {}, "FLATUSDT": {}}
    for base, m in ((day_d, mids), (day_b, mids)):
        for h in range(-3 * 24, 24):
            ts = base + h * 3600
            m["PUMPUSDT"][ts] = 100.0 * (1.6 if h >= -1 else 1.0)
            m["FLATUSDT"][ts] = 100.0
    tr = [
        {**_t(10, -50.0, sym="PUMPUSDT", side="short"), },
        {**_t(10, -20.0, sym="FLATUSDT", side="short"), },
        {**_t(10, +30.0, sym="PUMPUSDT", side="long"), },
    ]
    # имя без сводок: шорт остаётся и считается неизмеренным
    tr.append({**_t(10, -70.0, sym="NOMIDUSDT", side="short")})
    rows = BK.runup_table(tr, mids)
    r = next(x for x in rows if x["r"] == 2 and x["t"] == 0.5)
    check("срезан только разогнанный шорт: +50 $ в сливе",
          r["drain"]["n_cut"] == 1 and abs(r["drain"]["cut"] - 50) < 1e-9,
          str(r["drain"]))
    check("шортов в окне три: плоский и неизмеренный остались",
          r["drain"]["n"] == 3, str(r["drain"]))
    check("имя без сводок — неизмеренное, не срезанное",
          r["unmeasured"] == 1, str(r["unmeasured"]))
    r2 = next(x for x in rows if x["r"] == 2 and abs(x["t"] - 1.0) < 1e-9)
    check("порог +100 % не срезает ход +60 %",
          r2["drain"]["n_cut"] == 0, str(r2["drain"]))


def test_whole_run_writes_report():
    root = tempfile.mkdtemp()
    published = []
    keep_pub, keep_sum = PT.publish, BK.SUMMARY
    out_was = BK.HERE
    try:
        PT.publish = lambda: published.append(1)
        # книга-фикстура: та же, что у теста разбора
        import test_drain as TD
        s8 = TD._fixture(root)
        BK.SUMMARY = os.path.join(root, "summary")   # пусто: не измерено
        BK.HERE = os.path.join(root, "probe_drain")
        rc = BK.main(["--s8", s8, "--tag", "t", "--no-publish"])
        check("прогон дошёл до конца", rc == 0, str(rc))
        rep = os.path.join(BK.HERE, "out", "DRAIN-brake-t.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("обе таблицы на месте",
              "тормоз дня" in txt and "потолок шорта" in txt, txt[:200])
        check("оговорка про кассу и один эпизод",
              "Касса не пересчитывается" in txt
              and "ошибка R5" in txt, "оговорки нет")
        art = json.load(open(os.path.join(
            BK.HERE, "out", "brake-t.json"), encoding="utf-8"))
        # На фикстуре сделки мелкие и до порогов день не доезжает —
        # срезание закреплено юнит-сценариями с числами; сквозной
        # прогон держит ДОРОГУ: обе таблицы посчитаны, окно убыточно.
        check("тормоз посчитан по всем X",
              len(art["brake"]) == len(BK.BRAKE_X)
              and len(art["brake_global"]) == len(BK.BRAKE_X_GLOBAL),
              str(len(art["brake"])))
        check("окно фикстуры убыточно без правила",
              art["brake"][0]["drain"]["pnl0"] < 0,
              str(art["brake"][0]["drain"]))
        check("ход посчитан по всей сетке",
              len(art["runup"]) == len(BK.RUNUP_R) * len(BK.RUNUP_T),
              str(len(art["runup"])))
        check("с флагом публикации нет", not published, str(published))
        BK.main(["--s8", s8, "--tag", "p"])
        check("без флага публикация случилась", bool(published))
    finally:
        PT.publish, BK.SUMMARY, BK.HERE = keep_pub, keep_sum, out_was
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_brake_chronology, test_runup_uses_closed_hour,
             test_runup_table_counts, test_whole_run_writes_report)
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
