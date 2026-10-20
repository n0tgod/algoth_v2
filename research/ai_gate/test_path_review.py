#!/usr/bin/env python3
"""Прогон разбора путей (U0): разбираются только ЗАКРЫТЫЕ с дня рождения;
строка ложится в файл дня выхода и второй раз не считается; позиция без
баров записана как «не измерено», а не пропущена; уровни книги едут
числами. Источники — подставные."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import path_review as PR                                     # noqa: E402
import gate_run as G                                         # noqa: E402

H = 3600
T0 = G.GATE_SINCE + 5 * H


class Src:
    def __init__(self):
        self.calls = 0

    def bars(self, sym, t0, t1):
        self.calls += 1
        if sym == "DRYUSDT":
            return []
        out, t, px = [], t0, 1.0
        while t <= t1:
            px = 1.0 + 0.2 * ((t - t0) / (t1 - t0))          # ровно вверх на 20 % (пол шорта ≈ +18.6 %)
            out.append([t, px, px * 1.001, px * 0.999, px, 1.0])
            t += 60
        return out


class Mkt:
    def move(self, sym, t0, t1):
        return 0.1

    def wave(self, t0, t1):
        return 0.02


def rec(sym, at, state="closed", side="short"):
    return {"sym": sym, "at": at, "exit_ts": at + 2 * H, "state": state, "side": side, "lev": 10.0,
            "entry_px": 1.0, "pnl": -0.9, "exit": "пол", "fav_bp": -500,
            "fills": [[at, 1.0, 0.25]], "margin": 25.0}


def main():
    with tempfile.TemporaryDirectory() as d:
        PR.REVIEWS, PR.LATEST = os.path.join(d, "reviews"), os.path.join(d, "latest.json")
        books = {"optimal_h": [rec("AAAUSDT", T0), rec("DRYUSDT", T0 + H), rec("OPENUSDT", T0, state="open"),
                               rec("OLDUSDT", G.GATE_SINCE - 2 * H)],
                 "optimal": []}
        src, log = Src(), []
        s = PR.run(log=log.append, now=T0 + 3 * H, src=src, mkt=Mkt(), books=books)
        rows = PR.read_paths()
        assert {r["sym"] for r in rows} == {"AAAUSDT", "DRYUSDT"}, rows
        a = next(r for r in rows if r["sym"] == "AAAUSDT")
        assert a["path"]["shape"] == "straight_against" and abs(a["path"]["mae"] - 0.2 * 1.001) < 2e-3, a["path"]
        assert a["path"]["market_move"] == 0.02 and a["path"]["name_move"] == 0.1 and a["path"]["life_share"] == round(2 / 24, 3)
        assert a["floor_px"] is not None and a["take_px"] is not None, "уровни книги едут числами"
        assert a["path"]["first_touch"] == "floor", a["path"]
        dry = next(r for r in rows if r["sym"] == "DRYUSDT")
        assert dry["path"]["shape"] == "no_bars" and "не измерен" in dry["words"]
        assert s["last_pass"]["new"] == 2 and s["last_pass"]["no_bars"] == 1 and s["total"]["n"] == 2
        n = src.calls
        s2 = PR.run(log=log.append, now=T0 + 4 * H, src=src, mkt=Mkt(), books=books)
        assert src.calls == n and s2["last_pass"]["new"] == 0 and PR.read_paths().__len__() == 2, "второй раз не считается"
    print("ok  разбор путей: только закрытые с дня рождения, один раз, без баров — названо, уровни числами")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
