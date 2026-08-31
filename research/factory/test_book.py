"""Проверки реплея кандидата.

Ноги и исходы здесь синтетические, но ПОЛЯ у них те же, что кладёт
`tournament._leg`: подставной артефакт обязан выглядеть как живой,
иначе проверка исполняет другую дорогу. Ровно на этом уже ловились
лига (деньги штампует касса, а не разбор) и зонд `probe_turn`.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import book as B    # noqa: E402
import space as S   # noqa: E402

FAILED = []
H = 3600.0


def check(name, ok, got=""):
    print(("  ok   " if ok else "  ПРОВАЛ ") + name
          + ("" if ok else f" — {got}"))
    if not ok:
        FAILED.append(name)


def leg(i, sym, side, fwd, at, arm="gbm", fz=None, adv=30.0, rr=3.0,
        hour="2026-08-31-10"):
    sign = 1 if side == "long" else -1
    return {"id": i, "arm": arm, "sym": sym, "hour": hour, "at": at,
            "side": side, "fwd": fwd, "px": 100.0,
            "fz": fz, "adv_q": -sign * adv, "adv_m": -sign * adv,
            "fav": sign * adv * rr, "rr": rr}


def rule(**kw):
    r = {"target": "fwd_4h", "rank": "raw", "floor_bp": 0, "width": 3,
         "geom": "timer", "rr_band": "none", "sizing": "equal",
         "basket": "no", "agree": "no"}
    r.update(kw)
    return B.with_geometry(r)


def outs_for(legs, move=100.0, exit_at=None):
    """Исход у всех ног одинаковый — тогда разница между книгами
    принадлежит ПРАВИЛУ, а не исходам."""
    r = rule()
    return {(lg["id"], r["_stop"], r["_take"], r["_age"]):
            ("срок", move, exit_at or (lg["at"] + 4 * H), 100.0)
            for lg in legs}


def test_width_is_per_side():
    legs = ([leg(i, f"L{i}", "long", 50.0, 1000.0) for i in range(10)]
            + [leg(10 + i, f"S{i}", "short", -50.0, 1000.0)
               for i in range(10)])
    tr = B.simulate(legs, outs_for(legs), rule(width=3))
    longs = sum(1 for t in tr if t["side"] == "long")
    shorts = sum(1 for t in tr if t["side"] == "short")
    # «3+3» есть три лонга И три шорта. Считай места на всех — в
    # растущем рынке книга набралась бы одними лонгами и мерила бы
    # бету, а не отбор.
    check("ширина 3 даёт 3 лонга и 3 шорта",
          (longs, shorts) == (3, 3), f"{longs}/{shorts}")


def test_one_position_per_name_per_arm():
    legs = [leg(0, "AAA", "long", 50.0, 1000.0),
            leg(1, "AAA", "long", 50.0, 1000.0 + H),
            leg(2, "AAA", "long", 50.0, 1000.0 + 9 * H)]
    outs = outs_for(legs)
    tr = B.simulate(legs, outs, rule(width=3))
    check("занятое имя не берётся второй раз",
          len(tr) == 2, f"{len(tr)} сделок: {[t['at'] for t in tr]}")


def test_order_decides_who_gets_the_slot():
    # У A прогноз крупнее в сырых б.п., у B — в единицах σ. Одно место.
    legs = [leg(0, "AAA", "long", 90.0, 1000.0, fz=1.0),
            leg(1, "BBB", "long", 30.0, 1000.0, fz=9.0)]
    outs = outs_for(legs)
    # Вход НЕ сортируется тестом: очередь обязана задаваться правилом,
    # иначе ось порядка не решает ничего, а проверка этого не видит.
    raw = B.simulate(legs, outs, rule(width=1, rank="raw"))
    sig = B.simulate(legs, outs, rule(width=1, rank="sigma"))
    check("сырой порядок берёт крупный прогноз",
          [t["sym"] for t in raw] == ["AAA"], str([t["sym"] for t in raw]))
    check("порядок в σ берёт крупный в единицах σ",
          [t["sym"] for t in sig] == ["BBB"], str([t["sym"] for t in sig]))
    # Нога без `fwd_z` в книге, упорядоченной по σ, не участвует:
    # неизмеримое место не есть последнее место.
    no_z = [leg(0, "AAA", "long", 90.0, 1000.0, fz=None)]
    check("без величины в σ нога не берётся",
          B.simulate(no_z, outs_for(no_z), rule(rank="sigma")) == [])


def test_agreement_is_read_from_the_sheet():
    legs = [leg(0, "AAA", "long", 50.0, 1000.0, arm="gbm"),
            leg(1, "AAA", "long", 50.0, 1000.0, arm="nn"),
            leg(2, "BBB", "long", 50.0, 1000.0, arm="gbm")]
    outs = outs_for(legs)
    tr = B.simulate(legs, outs, rule(agree="yes"))
    syms = {t["sym"] for t in tr}
    check("берётся только имя, выбранное обеими руками",
          syms == {"AAA"}, str(syms))
    check("без требования согласия берутся оба",
          {t["sym"] for t in B.simulate(legs, outs, rule())} == {"AAA", "BBB"})


def test_sizing_changes_weight_not_the_trade():
    legs = [leg(0, "AAA", "long", 50.0, 1000.0, fz=2.0, adv=20.0),
            leg(1, "BBB", "long", 50.0, 1000.0, fz=1.0, adv=40.0)]
    outs = outs_for(legs)
    eq = B.simulate(legs, outs, rule(sizing="equal"))
    rk = B.simulate(legs, outs, rule(sizing="risk"))
    check("сделки те же, меняется вес",
          [t["sym"] for t in eq] == [t["sym"] for t in rk], "")
    wr = {t["sym"]: t["w"] for t in rk}
    check("равный риск: тесный стоп весит вдвое больше",
          abs(wr["AAA"] / wr["BBB"] - 2.0) < 1e-6, str(wr))
    # Книга с равным риском обязана вообще давать сделки: первая версия
    # читала несуществующее поле `adv` и молча не давала ни одной.
    check("равный риск даёт сделки", len(rk) == 2, str(len(rk)))
    iv = {t["sym"]: t["w"] for t in B.simulate(legs, outs,
                                               rule(sizing="inv_sigma"))}
    check("обратно σ: у монеты с крупной σ вес меньше",
          iv["AAA"] > iv["BBB"], str(iv))


def test_unmeasurable_weight_skips_the_leg():
    legs = [leg(0, "AAA", "long", 50.0, 1000.0, fz=None)]
    outs = outs_for(legs)
    tr = B.simulate(legs, outs, rule(sizing="inv_sigma"))
    # Вес 1.0 вместо пропуска смешал бы два правила размера в одной
    # книге, и разница между ними перестала бы принадлежать правилу.
    check("нога без измеримого веса пропущена", tr == [], str(tr))


def test_gates_are_the_books_gates():
    legs = [leg(0, "AAA", "long", 25.0, 1000.0, rr=1.2),
            leg(1, "BBB", "long", 50.0, 1000.0, rr=3.0)]
    outs = outs_for(legs)
    check("пол входа режет мелкий прогноз",
          [t["sym"] for t in B.simulate(legs, outs, rule(floor_bp=30))]
          == ["BBB"])
    check("полоса «низкое отношение» берёт своё",
          [t["sym"] for t in B.simulate(legs, outs, rule(rr_band="lo"))]
          == ["AAA"])
    check("полоса «высокое отношение» берёт своё",
          [t["sym"] for t in B.simulate(legs, outs, rule(rr_band="hi"))]
          == ["BBB"])
    no_rr = [dict(legs[0], rr=None)]
    check("неизмеримое отношение не проходит ни одну полосу",
          B.simulate(no_rr, outs_for(no_rr), rule(rr_band="lo")) == []
          and B.simulate(no_rr, outs_for(no_rr), rule(rr_band="hi")) == [])


def test_daily_net_is_weighted():
    legs = [leg(0, "AAA", "long", 50.0, 1000.0, fz=2.0, adv=20.0),
            leg(1, "BBB", "long", 50.0, 1000.0, fz=1.0, adv=40.0)]
    r = rule(sizing="risk")
    outs = {(0, r["_stop"], r["_take"], r["_age"]):
            ("срок", 300.0, 1000.0 + 4 * H, 100.0),
            (1, r["_stop"], r["_take"], r["_age"]):
            ("срок", 0.0, 1000.0 + 4 * H, 100.0)}
    tr = B.simulate(legs, outs, r)
    d = B.daily_net(tr)
    day = list(d)[0]
    # Веса 1/20 и 1/40: взвешенное среднее ближе к ноге с тесным стопом.
    exp = ((300.0 - 11.0) * (1 / 20.0) + (0.0 - 11.0) * (1 / 40.0)) / (
        1 / 20.0 + 1 / 40.0)
    check("дневной итог взвешен размером",
          abs(d[day] - exp) < 1e-6, f"{d[day]:.3f} против {exp:.3f}")


def main():
    tests = (test_width_is_per_side,
             test_one_position_per_name_per_arm,
             test_order_decides_who_gets_the_slot,
             test_agreement_is_read_from_the_sheet,
             test_sizing_changes_weight_not_the_trade,
             test_unmeasurable_weight_skips_the_leg,
             test_gates_are_the_books_gates,
             test_daily_net_is_weighted)
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
