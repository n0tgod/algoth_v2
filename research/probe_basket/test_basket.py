#!/usr/bin/env python3
"""Проверки реплея корзины: правило «только все разом» закреплено
числами, оба порога живые, хвост не выдаётся за реализованное."""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(os.path.dirname(HERE), "probe_drain"),
          os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop")):
    if p not in sys.path:
        sys.path.insert(0, p)

import basket as BS                                        # noqa: E402
import brake as BK                                         # noqa: E402
import turn as PT                                          # noqa: E402

FAILED = []
H = 3600
T0 = BS.hour_ts("2026-08-20-00")


def check(name, cond, note=""):
    print(("ok  " if cond else "ПРОВАЛ") + " " + name
          + ("" if cond else f" · {note}"))
    if not cond:
        FAILED.append(name)


def flat_mids(path):
    """{sym: {ts: mid}} по заданным траекториям (часовые точки)."""
    out = {}
    for sym, pts in path.items():
        out[sym] = {T0 + i * H: v for i, v in enumerate(pts)}
    return out


def test_take_closes_all_at_once():
    """Цель корзины закрывает ВСЕ ноги одним часом, и реализованное
    сходится числом: ход минус круг на каждую ногу."""
    # Две ноги входят в час 0; к часу 2 суммарный нереализованный
    # проходит +2.5 % капитала (75 $): каждая нога 20.83 $, лонг A
    # +200 %, лонг B +200 % → unreal ≈ 2 × 20.83 × (2.0 − 0.0011)
    picks = {T0: [{"sym": "AAA", "side": "long", "px": 100.0},
                  {"sym": "BBB", "side": "long", "px": 100.0}]}
    mids = flat_mids({"AAA": [100, 150, 300, 300],
                      "BBB": [100, 150, 300, 300]})
    c = BS.replay(picks, mids, take=0.025, floor=0.025)
    check("корзина закрылась целью один раз",
          c["baskets"] == 1 and c["n_take"] == 1, str(c))
    # Число закреплено ЛИТЕРАЛОМ, а не формулой от констант модуля:
    # ожидание, считающее себя тем же кодом, не ловит снятый круг
    # (контроль «COST = 0» проходил мимо, пока здесь стояла формула).
    # 2 × (3000/144) × (2.0 − 0.0011) = 83.29 $.
    check("реализованное сходится числом (с кругом издержек)",
          abs(c["realized"] - 83.29) < 0.01,
          f"{c['realized']} против 83.29")
    check("хвоста нет: все ноги закрыты разом",
          c["open_legs"] == 0 and c["open_mark"] is None, str(c))


def test_floor_and_no_individual_exits():
    """Предел закрывает всё; нога с чудовищным собственным минусом НЕ
    закрывается, пока корзина в допуске, — отдельных выходов нет."""
    # AAA −60 %, BBB +55 %: чистый минус мал, корзина живёт, хотя
    # одиночный стоп давно снял бы AAA. К часу 3 обе валятся — предел.
    picks = {T0: [{"sym": "AAA", "side": "long", "px": 100.0},
                  {"sym": "BBB", "side": "long", "px": 100.0}]}
    mids = flat_mids({"AAA": [100, 40, 40, 5, 5],
                      "BBB": [100, 155, 150, 10, 10]})
    c = BS.replay(picks, mids, take=0.20, floor=0.01)
    check("предел сработал один раз",
          c["baskets"] == 1 and c["n_floor"] == 1, str(c))
    check("до предела ни одна нога не закрылась сама",
          c["baskets"] == 1 and c["age_med_h"] >= 3,
          f"возраст {c['age_med_h']}")
    c2 = BS.replay(picks, mids, take=9.0, floor=None)
    check("без предела корзина не закрывается вовсе",
          c2["baskets"] == 0 and c2["open_legs"] == 2, str(c2))
    check("открытый хвост — отметкой, не реализованным",
          c2["realized"] == 0.0 and c2["open_mark"] is not None
          and c2["open_mark"] < 0, str(c2))


def test_cash_and_name_caps_count():
    """Касса и потолок имени: сверх — размер 0, посчитан числом."""
    # 145-я нога не влезает в гросс 3000 (144 × 20.83).
    picks = {}
    for i in range(29):
        picks[T0 + i * H] = [{"sym": f"S{i}_{j}", "side": "long",
                              "px": 100.0} for j in range(5)]
    mids = flat_mids({f"S{i}_{j}": [100.0] * 40
                      for i in range(29) for j in range(5)})
    c = BS.replay(picks, mids, take=9.0, floor=None)
    check("гросс упёрся в капитал: пропуски кассы посчитаны",
          c["skipped"]["no_cash"] == 145 - 144
          and c["open_legs"] == 144,
          str((c["skipped"], c["open_legs"])))
    # Потолок имени: 15-я нога одного имени превышает 10 % (300 $).
    picks2 = {T0 + i * H: [{"sym": "ONE", "side": "long", "px": 100.0}]
              for i in range(20)}
    mids2 = flat_mids({"ONE": [100.0] * 40})
    c2 = BS.replay(picks2, mids2, take=9.0, floor=None)
    check("потолок имени связал сверх 14 ног",
          c2["open_legs"] == 14 and c2["skipped"]["name_cap"] == 6,
          str((c2["open_legs"], c2["skipped"])))
    # Встречная нога в удерживаемое имя не открывается.
    picks3 = {T0: [{"sym": "ONE", "side": "long", "px": 100.0}],
              T0 + H: [{"sym": "ONE", "side": "short", "px": 100.0}]}
    c3 = BS.replay(picks3, mids2, take=9.0, floor=None)
    check("встречная нога пропущена и посчитана",
          c3["open_legs"] == 1 and c3["skipped"]["opposite"] == 1,
          str(c3["skipped"]))


def test_age_limit_closes_basket():
    """Лимит возраста закрывает корзину целиком по отметке; пороги
    старше возраста — задетая цель называется целью, не возрастом."""
    picks = {T0: [{"sym": "AAA", "side": "long", "px": 100.0}]}
    mids = flat_mids({"AAA": [100.0] * 10})
    c = BS.replay(picks, mids, take=9.0, floor=None, age_h=3)
    check("возраст закрыл корзину один раз",
          c["baskets"] == 1 and c["n_age"] == 1
          and c["age_med_h"] == 3, str(c))
    # Плоская цена: итог = −круг на ногу. 20.83 × 0.0011 = 0.02 $.
    check("итог возрастного закрытия — ровно круг издержек",
          abs(c["realized"] + 0.02) < 0.005,
          f"{c['realized']} против −0.02")
    check("хвост пуст: корзина закрыта, не отметка",
          c["open_legs"] == 0 and c["open_mark"] is None, str(c))
    # Цель, задетая РАНЬШЕ лимита, остаётся целью. Одна нога ×3 даёт
    # +41.6 $, цель 1 % капитала (30 $) задета в час 1 — до возраста.
    mids2 = flat_mids({"AAA": [100, 300, 300, 300, 300]})
    c2 = BS.replay(picks, mids2, take=0.01, floor=None, age_h=3)
    check("цель раньше возраста — закрытие целью",
          c2["n_take"] == 1 and c2["n_age"] == 0, str(c2))
    # Умолчание age_h=None — прежнее поведение: корзина живёт.
    c3 = BS.replay(picks, mids, take=9.0, floor=None)
    check("без лимита возраст не закрывает",
          c3["baskets"] == 0 and c3["open_legs"] == 1, str(c3))


def test_one_loss_day_blocks_entries():
    """После минусового закрытия новые входы того же дня UTC не
    берутся и считаются числом; следующий день входит."""
    picks = {T0: [{"sym": "AAA", "side": "long", "px": 100.0}],
             T0 + 2 * H: [{"sym": "BBB", "side": "long", "px": 100.0}],
             T0 + 26 * H: [{"sym": "CCC", "side": "long",
                            "px": 100.0}]}
    mids = flat_mids({"AAA": [100.0] + [10.0] * 29,
                      "BBB": [100.0] * 30, "CCC": [100.0] * 30})
    # AAA −90 % пробивает предел 0.5 % капитала в час T0+1 (минус).
    c = BS.replay(picks, mids, take=9.0, floor=0.005,
                  one_loss_day=True)
    check("минусовое закрытие случилось",
          c["baskets"] == 1 and c["n_floor"] == 1, str(c))
    check("вход того же дня пропущен и посчитан",
          c["skipped"]["loss_day"] == 1, str(c["skipped"]))
    check("вход следующего дня взят",
          c["open_legs"] == 1, str(c))
    # Без правила тот же день входит: к концу открыты BBB и CCC.
    c2 = BS.replay(picks, mids, take=9.0, floor=0.005)
    check("без правила оба поздних входа взяты",
          c2["open_legs"] == 2
          and c2["skipped"]["loss_day"] == 0, str(c2))


def test_unpriced_leg_blocks_decision():
    """Нога без единой цены блокирует решение корзины (правило живой
    книги), и часы блокировки считаются."""
    picks = {T0: [{"sym": "AAA", "side": "long", "px": 100.0},
                  {"sym": "GHOST", "side": "long", "px": 100.0}]}
    mids = flat_mids({"AAA": [100, 300, 300], "GHOST": []})
    # GHOST есть в mids (пустой ряд) — вход прошёл, цены нет ни разу.
    mids["GHOST"] = {}
    c = BS.replay(picks, mids, take=0.01, floor=0.01)
    check("решение заблокировано: закрытий нет при явном ходе",
          c["baskets"] == 0 and c["blocked_hours"] > 0, str(c))


def test_whole_run_writes_report():
    root = tempfile.mkdtemp()
    here_was, sum_was = BS.HERE, BK.SUMMARY
    published = []
    keep_pub = PT.publish
    try:
        s8 = os.path.join(root, "s8", "out")
        mdir = os.path.join(s8, "model_h24")
        os.makedirs(mdir)
        with open(os.path.join(mdir, "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": 2, "horizon_h": 24}, f)
        pk = []
        for i in range(72):
            hour = datetime.fromtimestamp(
                T0 + i * H, timezone.utc).strftime("%Y-%m-%d-%H")
            pk.append({"arm": "gbm", "hour": hour,
                       "long": [{"sym": "AAA", "px": 100.0,
                                 "fwd": 50.0}],
                       "short": []})
        with open(os.path.join(mdir, "picks.jsonl"), "w",
                  encoding="utf-8") as f:
            for r in pk:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        # сводки для load_mids: AAA плавно растёт — цели достижимы
        sdir = os.path.join(root, "summary", "AAA")
        os.makedirs(sdir)
        by_day = {}
        for i in range(100):
            ts = T0 + i * H
            d = datetime.fromtimestamp(ts, timezone.utc)
            by_day.setdefault(d.strftime("%Y-%m-%d"), []).append(
                {"hour": d.strftime("%Y-%m-%d-%H"),
                 "mid_close": 100.0 * (1 + 0.004 * i)})
        for day, rows in by_day.items():
            with open(os.path.join(sdir, day + ".jsonl"), "w",
                      encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        BK.SUMMARY = os.path.join(root, "summary")
        BS.HERE = os.path.join(root, "probe_basket")
        PT.publish = lambda: published.append(1)
        rc = BS.main(["--s8", s8, "--tag", "t", "--no-publish"])
        check("прогон дошёл до конца", rc == 0, str(rc))
        rep = os.path.join(BS.HERE, "out", "BASKET-report-t.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("вся сетка в таблице: 20 строк ячеек",
              txt.count("| +2.5% |") + txt.count("| +5.0% |")
              + txt.count("| +10.0% |") + txt.count("| +20.0% |")
              == 20, str(txt.count("| +")))
        check("оговорка R5 у лучшей ячейки",
              "ошибка R5" in txt, "оговорки нет")
        check("свойство кассы названо",
              "размер 0" in txt, "нет оговорки про наполнение")
        art = json.load(open(os.path.join(
            BS.HERE, "out", "basket-t.json"), encoding="utf-8"))
        g = art["cells"]["gbm"]
        check("на растущем ряде мягкая цель закрывается чаще жёсткой",
              next(c for c in g if c["take"] == 0.025
                   and c["floor"] is None)["baskets"]
              >= next(c for c in g if c["take"] == 0.20
                      and c["floor"] is None)["baskets"], str(
                  [(c["take"], c["baskets"]) for c in g
                   if c["floor"] is None]))
        check("с флагом публикации нет", not published, str(published))
        BS.main(["--s8", s8, "--tag", "p"])
        check("без флага публикация случилась", bool(published))
        # Вторая серия: свой отчёт, база не затирается.
        rc2 = BS.main(["--s8", s8, "--tag", "t", "--rules",
                       "--no-publish"])
        check("прогон правил дошёл до конца", rc2 == 0, str(rc2))
        rep2 = os.path.join(BS.HERE, "out", "BASKET-rules-t.md")
        check("отчёт правил написан отдельным файлом",
              os.path.exists(rep2), rep2)
        t2 = open(rep2, encoding="utf-8").read()
        # Каждый ярлык стоит дважды: строкой свода и колонкой
        # поячеечной таблицы — присутствие проверяется по всем шести.
        labels6 = [BS.vlabel(*v) for v in BS.VARIANTS]
        check("все шесть вариантов в отчёте (свод + колонки)",
              len(labels6) == 6
              and all(t2.count(f"| {lb} |") >= 2 for lb in labels6),
              str([(lb, t2.count(f"| {lb} |")) for lb in labels6]))
        check("поячеечная таблица правил: 20 строк",
              t2.count("| +2.5% |") + t2.count("| +5.0% |")
              + t2.count("| +10.0% |") + t2.count("| +20.0% |")
              == 20, "строк не 20")
        check("оговорка R5 в отчёте правил", "ошибка R5" in t2)
        check("базовый отчёт не затёрт прогоном правил",
              os.path.exists(rep), rep)
        art2 = json.load(open(os.path.join(
            BS.HERE, "out", "basket-rules-t.json"), encoding="utf-8"))
        gv = art2["variants"]["gbm"]
        base_tot = {(c["take"], c["floor"]): c["realized"]
                    for c in gv["без лимита"]}
        same = {(c["take"], c["floor"]): c["realized"]
                for c in art["cells"]["gbm"]}
        check("база второй серии = первая серия бит в бит",
              base_tot == same, str((base_tot, same))[:200])
        aged = gv["возраст ≤ 24 ч"]
        check("лимит возраста держит возраст закрытий в пределе",
              all((c["age_max_h"] or 0) <= 24 for c in aged),
              str([c["age_max_h"] for c in aged]))
    finally:
        BS.HERE, BK.SUMMARY = here_was, sum_was
        PT.publish = keep_pub
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_take_closes_all_at_once,
             test_floor_and_no_individual_exits,
             test_cash_and_name_caps_count,
             test_age_limit_closes_basket,
             test_one_loss_day_blocks_entries,
             test_unpriced_leg_blocks_decision,
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
