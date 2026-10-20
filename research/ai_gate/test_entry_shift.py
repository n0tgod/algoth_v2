#!/usr/bin/env python3
"""Сдвиг точки входа (U4): срабатывание по свече после опоры (против шорта —
рост, в пользу — падение), конец минуты срабатывания — новый момент; не
сработало в окне — сделки нет; случайный момент — в том же окне и только
для сработавших; на сигнал не сработавший считается нулём; кандидат — только
когда держат обе половины, случайный момент и касса. Реплей, касса и
правила книги — подставные."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import entry_shift as E                                      # noqa: E402

T0 = 1_792_000_800.0
H = 3600.0


def bars(prices, t0=T0):
    out = []
    for i, (o, h, l, c) in enumerate(prices):
        out.append([t0 + 60 * i, o, h, l, c, 1.0])
    return out


def main():
    b = bars([(100, 100, 100, 100), (100, 101, 99.5, 100.5), (100.5, 102.5, 100, 102), (102, 102, 97, 97.5)])
    pb = {"id": "p", "kind": "pullback", "pct": 2.0, "within_h": 1}
    cf = {"id": "c", "kind": "confirm", "pct": 2.0, "within_h": 1}
    assert E.trigger(pb, b, T0) == T0 + 2 * 60 + 60, "против шорта — рост до 102 на третьей минуте"
    assert E.trigger(cf, b, T0) == T0 + 3 * 60 + 60, "в пользу — падение до 98 на четвёртой"
    assert E.trigger(dict(pb, pct=5.0), b, T0) is None, "не сработало — сделки нет"
    assert E.trigger({"kind": "delay", "after_h": 1}, b, T0) is None, "баров на час позже нет — сделки нет"
    assert E.trigger(dict(pb, within_h=1 / 60), b, T0) is None, "срабатывание за окном не считается"
    assert E.valid({"kind": "pullback", "pct": 30, "within_h": 2}).startswith("порог")
    assert E.valid({"kind": "jump"}) == "вид вне словаря"
    legs = []
    for i in range(140):
        legs.append({"sym": f"S{i % 7}USDT", "at": T0 + i * H, "side": "short", "fwd": -50, "fav": -500, "adv_q": 300})

    def bars_of(sym, a, z):
        i = int(sym[1])
        up = 2.5 if i % 2 == 0 else 0.5          # чётные имена откатываются против шорта на 2.5 %
        return bars([(100, 100, 100, 100), (100, 100 + up, 99.8, 100 + up / 2), (100, 100, 99, 99)], t0=a)
    pairs = E.shifted(legs, pb, bars_of)
    trig = [ng for _g, ng in pairs if ng is not None]
    assert trig and all(int(ng["sym"][1]) % 2 == 0 for ng in trig) and all(ng["at"] == ng["at_signal"] + 120 for ng in trig)
    npairs = E.shifted(legs, pb, bars_of, rng=random.Random(1))
    assert [g["sym"] for g, ng in npairs if ng] == [ng["sym"] for ng in trig], "нуль — те же сработавшие"
    assert all(ng["at_signal"] < ng["at"] <= ng["at_signal"] + 3600 for _g, ng in npairs if ng)

    # прогон целиком: вход после отката даёт +0.10 на сработавший, книга и случайный момент — 0.0 / −0.02
    def replay(need):
        out = {}
        for g in need:
            shifted_ = g.get("at_signal") is not None
            exact = shifted_ and (g["at"] - g["at_signal"]) == 120
            v = 0.10 if exact else (-0.02 if shifted_ else 0.0)
            out[(E.RULER, g["sym"], round(float(g["at"]), 3))] = {"sym": g["sym"], "at": g["at"], "pnl": v,
                                                                  "pnl_net": v, "state": "closed"}
        return out

    import run_short as S
    S.read_cache = lambda log=None: ({(E.RULER, g["sym"], round(g["at"], 3)): {"pnl": 0.0, "state": "closed"} for g in legs}, None)
    E.book_chain = lambda recs, log, now: list(recs)
    E.GRID = [pb]
    E.HYPS_FILE = "/nonexistent"
    cash = lambda recs: {10000: {"final": sum(r["pnl"] for r in recs) / 100}, 1000: {"final": 0}}   # noqa: E731
    r = E.run(log=lambda *a: None, since=T0, now=T0 + 260 * H, legs=legs, replay=replay, cash=cash,
              src=type("Src", (), {"bars": lambda self, s, a, z: bars_of(s, a, z)})())
    assert r["reproduce"]["share"] == 1.0, r["reproduce"]
    h = r["hypotheses"][0]
    assert h["per_signal"]["all"]["triggered"] == len(trig) and abs(h["per_signal"]["all"]["mean_triggered"] - 0.10) < 1e-9
    assert h["null_median_triggered"]["all"] == -0.02 and h["candidate"] is True, (h["why"], h["per_signal"])
    # тот же вариант без выигрыша над случайным моментом — не кандидат
    def replay2(need):
        out = replay(need)
        for k, v in out.items():
            if v["pnl"] != 0.0:
                v["pnl"] = v["pnl_net"] = 0.10
        return out
    r2 = E.run(log=lambda *a: None, since=T0, now=T0 + 260 * H, legs=legs, replay=replay2, cash=cash,
               src=type("Src", (), {"bars": lambda self, s, a, z: bars_of(s, a, z)})())
    assert r2["hypotheses"][0]["candidate"] is False, "выигрыш, который даёт любой момент того же окна, — отбор, не ТВХ"
    assert "кандидат" in E.report(r) and "Проверка проверки" in E.report(r)
    print("ok  сдвиг входа: срабатывание по свече, конец минуты — новый момент; нуль — случайная минута тех же сигналов; "
          "кандидат только при обеих половинах, нуле и кассе")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
