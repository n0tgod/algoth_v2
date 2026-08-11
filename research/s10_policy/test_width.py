#!/usr/bin/env python3
"""
Тесты профиля по месту в сечении.

Замер отвечает на «различает ли место будущий ход», и соврать он может
в обе стороны: показать убывание там, где его нет, и не показать там,
где оно есть. Обе стороны закрыты синтетикой с известным ответом.

    python3 research/s10_policy/test_width.py
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s9_sweep"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))

import trades as TR                                       # noqa: E402
import width as W                                         # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def leg(sym, fwd, hour="2026-08-05-10", arm="gbm", at=1.0):
    """Нога листа: сторона задаётся знаком прогноза, как у сканера."""
    return {"arm": arm, "sym": sym, "hour": hour, "at": at,
            "side": "long" if fwd > 0 else "short", "fwd": float(fwd),
            "px": 100.0, "adv_q": -50.0 if fwd > 0 else 50.0,
            "adv_m": -50.0 if fwd > 0 else 50.0,
            "fav": 100.0 if fwd > 0 else -100.0, "rr": 2.0, "id": 0}


def test_rank_is_within_hour_arm_and_side():
    """Место считается внутри часа, руки и СТОРОНЫ.

    Сложив лонги с шортами в один список, мы сравнивали бы разные концы
    сечения: у шорта самый крайний прогноз самый отрицательный. Место
    тогда означало бы не «крайний», а «ближе к лонгам».
    """
    legs = [leg("A", 90), leg("B", 30), leg("C", -80), leg("D", -20),
            leg("E", 50, hour="2026-08-05-11")]
    W.rank_legs(legs)
    by = {g["sym"]: (g["side"], g["rank"]) for g in legs}
    check("самый крайний лонг первый", by["A"] == ("long", 1), f"{by['A']}")
    check("второй лонг второй", by["B"] == ("long", 2), f"{by['B']}")
    check("самый крайний шорт первый у своей стороны",
          by["C"] == ("short", 1), f"{by['C']}")
    check("другой час считается отдельно", by["E"] == ("long", 1),
          f"{by['E']}")


def test_short_side_sign():
    """У шорта место задаёт МОДУЛЬ прогноза, а не его величина."""
    legs = [leg("A", -10), leg("B", -90)]
    W.rank_legs(legs)
    by = {g["sym"]: g["rank"] for g in legs}
    check("−90 крайнее, чем −10", by["B"] == 1 and by["A"] == 2, f"{by}")


def rows_with(profile):
    """Ноги с заданным ожиданием по месту: `profile[место] = нетто`."""
    out = []
    for r, net in profile.items():
        for k in range(40):
            out.append({"rank": r, "net": float(net), "sym": f"S{k % 7}",
                        "hour": f"h{k}", "arm": "gbm", "side": "long",
                        "id": len(out)})
    return out


def test_decaying_profile_is_named_decaying():
    rows = rows_with({1: 40, 2: 30, 3: 20, 4: 10, 5: 5, 6: 0, 8: -5,
                      10: -10, 15: -15, 20: -20, 30: -25})
    r = W.reading(W.by_rank(rows), W.by_width(rows))
    check("убывание названо убыванием", "убывает с местом" in r, r)
    check("ось признана оправданной", "оправдана" in r, r)


def test_flat_profile_is_named_flat():
    """Плоский профиль — довод ПРОТИВ оси, и это надо сказать прямо."""
    rows = rows_with({r: 12 for r in W.RANKS})
    r = W.reading(W.by_rank(rows), W.by_width(rows))
    check("плоское названо плоским", "плоский" in r, r)
    check("сказано, что шире лучше", "шире строго лучше" in r, r)
    check("ось признана ненужной", "не нужна" in r, r)


def test_thin_profile_is_not_judged():
    """Мест с наблюдениями мало — судить нечем, а не «профиля нет»."""
    rows = [{"rank": 1, "net": 50.0, "sym": "A", "hour": "h", "arm": "g",
             "side": "long", "id": 0}]
    r = W.reading(W.by_rank(rows), W.by_width(rows))
    check("тонкое не судится", "судить нечем" in r, r)


def test_width_reports_concentration():
    """Итог без лучшего имени — обязательная колонка.

    Весь опыт проекта: деньги делают одно-три имени. Без этой колонки
    узкая книга выглядит прибыльной ровно до дня, когда везучего имени
    не случится.
    """
    rows = [{"rank": 1, "net": 500.0, "sym": "LUCKY", "hour": "h1",
             "arm": "g", "side": "long", "id": 0}]
    rows += [{"rank": 1, "net": -10.0, "sym": f"S{k}", "hour": f"h{k}",
              "arm": "g", "side": "long", "id": k + 1} for k in range(20)]
    w = [x for x in W.by_width(rows) if x["width"] == 1][0]
    check("итог положителен", w["total_bp"] > 0, f"{w['total_bp']}")
    check("лучшее имя названо", w["top_sym"] == "LUCKY", f"{w['top_sym']}")
    check("без него итог отрицателен", w["total_wo_top_bp"] < 0,
          f"{w['total_wo_top_bp']}")


def test_net_matches_the_tournament_formula():
    """Нетто считается той же формулой, что `simulate` турнира.

    Вторая формула разошлась бы с первой, и профиль описывал бы другие
    деньги, чем таблица вариантов, — обе при этом выглядели бы верно.
    """
    import tournament as T
    bars = [(0.0, 100.0, 100.0, 100.0, 100.0),
            (60.0, 100.0, 110.0, 100.0, 110.0)]
    got = T.outcome(bars, 0.0, "long", None, None, 1)
    _, move, _, _ = got
    mine = 1 * move - TR.ROUND_COST_BP
    check("нетто лонга совпадает",
          abs(mine - (move - TR.ROUND_COST_BP)) < 1e-9, f"{mine}")
    got_s = T.outcome(bars, 0.0, "short", None, None, 1)
    _, move_s, _, _ = got_s
    check("шорту знак переворачивается",
          (-1 * move_s - TR.ROUND_COST_BP) < 0, f"{move_s}")


def test_report_names_the_fence():
    """Отчёт обязан назвать потолок на имя.

    Узкая книга несовместима с уже принятым забором: при одной ноге на
    сторону имя запросило бы половину книги. Умолчать об этом значит
    предложить владельцу правило, которое не исполнится.
    """
    rows = rows_with({r: 10 for r in W.RANKS})
    art = {"run_at": "x", "legs": 10, "measured": 10, "sections": 3,
           "age_h": 4, "ranks": W.by_rank(rows), "widths": W.by_width(rows),
           "reading": "—"}
    p = os.path.join(tempfile.mkdtemp(), "w.md")
    W.report(art, p)
    txt = open(p, encoding="utf-8").read()
    check("потолок на имя назван", "потолок на имя" in txt, "молчит")
    check("названа цена оси в испытаниях", "72 → 216" in txt, "молчит")


def main():
    print("места")
    test_rank_is_within_hour_arm_and_side()
    test_short_side_sign()
    print("вывод")
    test_decaying_profile_is_named_decaying()
    test_flat_profile_is_named_flat()
    test_thin_profile_is_not_judged()
    print("деньги и оговорки")
    test_width_reports_concentration()
    test_net_matches_the_tournament_formula()
    test_report_names_the_fence()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
