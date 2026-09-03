#!/usr/bin/env python3
"""Тест чистой логики D2 — построение структурных рунгов.

Чтение журнала листов, баров и уровней проверяется смоуком на VPS (данные
только там). Здесь — рунги, где легко ошибиться молча. Запуск из
`.venv/bin/python` (импорт тянет numpy/tournament/levels).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d2 as D  # noqa: E402


def test_rungs_below_with_reserve():
    # Уровни: 98, 95, 90, 80 ниже входа 100; шаг ≥1.5 %. 98 годится (−2 %),
    # 95 от 98 это −3.06 % годится, 90 от 95 −5.3 % годится → база+3.
    r = D.structural_rungs(100.0, [98.0, 95.0, 90.0, 80.0, 105.0], 0.015, 4)
    assert r == [100.0, 98.0, 95.0, 90.0], r
    print(f"ok  структурные рунги с запасом: {r}")


def test_rungs_skip_too_close():
    # 99.5 слишком близко к входу (−0.5 % < 1.5 %) — пропуск; 97 годится.
    r = D.structural_rungs(100.0, [99.5, 97.0, 90.0], 0.015, 4)
    assert r == [100.0, 97.0, 90.0], r
    print(f"ok  слишком близкий уровень пропущен: {r}")


def test_rungs_ignore_above():
    # Уровни выше входа — не рунги DCA-вниз.
    r = D.structural_rungs(100.0, [105.0, 110.0], 0.015, 4)
    assert r == [100.0], r
    print("ok  уровни выше входа игнорируются (лестница вырождается)")


def test_rungs_cap_at_n():
    # Много уровней — не больше N рунгов.
    r = D.structural_rungs(100.0, [95.0, 90.0, 85.0, 80.0, 75.0], 0.015, 4)
    assert len(r) == 4 and r == [100.0, 95.0, 90.0, 85.0], r
    print(f"ok  не больше N рунгов: {r}")


def test_split_window():
    # Часовые бары 0..19ч; окно вокруг 5ч, назад 2ч вперёд 3ч → бары 3..8ч,
    # now_i указывает на 5ч.
    bars = [(t, 1.0, 1.0, 1.0, 1.0, 0.0) for t in range(0, 20 * 3600, 3600)]
    ts = [b[0] for b in bars]
    win, now_i = D.split_window(bars, ts, 5 * 3600, 2, 3)
    assert [b[0] for b in win] == [3 * 3600, 4 * 3600, 5 * 3600, 6 * 3600,
                                   7 * 3600, 8 * 3600], [b[0] for b in win]
    assert win[now_i][0] == 5 * 3600, win[now_i][0]
    print(f"ok  окно среза: {len(win)} баров, вход на {win[now_i][0]//3600}ч")


def test_split_window_no_future():
    # Вход за последним баром — нет баров после входа → None.
    bars = [(t, 1.0, 1.0, 1.0, 1.0, 0.0) for t in range(0, 5 * 3600, 3600)]
    ts = [b[0] for b in bars]
    assert D.split_window(bars, ts, 10 * 3600, 2, 3) is None
    print("ok  вход за концом ряда → None")


def test_px_at():
    # close = метка бара; минутные бары 0..9 мин.
    bars = [(t, 0, 0, 0, float(t), 0) for t in range(0, 10 * 60, 60)]
    ts = [b[0] for b in bars]
    assert D.px_at(bars, ts, 5 * 60) == 5 * 60          # ровно на баре
    assert D.px_at(bars, ts, 5 * 60 + 30) == 5 * 60     # между → предыдущий
    assert D.px_at(bars, ts, -1) is None                # до первого бара
    assert D.px_at([], [], 100) is None                 # нет баров
    print("ok  px_at: последний бар ≤ t, None до начала ряда")


def _hedge_case():
    """Синтетика для бета-хеджа: build_levels пусто → один рунг, плечо 1×;
    BTC ПАДАЕТ за окно → короткий BTC даёт плюс. Возвращает всё для сверки."""
    entry = 100.0
    at = 1000 * 3600
    hours = list(range(998, 1006))                      # 998..1005ч
    bars = []
    for hh in hours:
        px = 100.0 if hh < 1000 else 100.0 - (hh - 1000)   # 100,100,100,99,…95
        bars.append((hh * 3600, px, px + 0.5, px - 0.5, px, 1000.0))
    ts = [b[0] for b in bars]
    # BTC падает 60000 → ниже, шаг 100 в час, шире окна выборки
    btc = [(hh * 3600, 60000.0 - (hh - 998) * 100.0, 0.0, 0.0,
            60000.0 - (hh - 998) * 100.0, 0.0) for hh in range(996, 1008)]
    btc_ts = [b[0] for b in btc]
    g = {"sym": "AAA", "at": float(at), "beta": 0.8, "fwd": 100.0,
         "rr": 1.0, "side": "long", "fav": 5000.0, "adv_q": -5000.0}
    return g, bars, ts, btc, btc_ts, entry


def test_hedge_arm_arithmetic():
    # build_levels пусто → рунг один, плечо §5 = 1×; SH = S + хедж, знак
    # хеджа закреплён формулой −β·нотионал·(bx/be−1).
    orig = D.build_levels
    D.build_levels = lambda bars, now_i: D.np.array([])
    try:
        g, bars, ts, btc, btc_ts, entry = _hedge_case()
        look = (lambda notl: D.L.mmr_for_notional([], notl, flat=D.FLAT_MMR))
        arms = {a: {"pnl": [], "liq": 0, "ruin": 0, "day": {}, "ok": 0}
                for a in ("B", "H", "S", "SH", "SS")}
        st = D._process_leg(g, bars, ts, look, arms, [], [], btc, btc_ts)
        assert st == "no_add", st
        # независимо пересчитать S и хедж
        win, now_i = D.split_window(bars, ts, g["at"], D.BACK_H, D.HOLD_H)
        hold = win[now_i:]
        take_px = entry * (1 + g["fav"] / 1e4)
        s = D.L.simulate_dca(hold, [entry], D.WEIGHTS[:1], 1.0, 1.0, look(1.0),
                             take_px=take_px, floor_frac=D.FLOOR_FRAC)
        be = D.px_at(btc, btc_ts, hold[0][0])
        bx = D.px_at(btc, btc_ts, s["exit_ts"])
        hedge = -g["beta"] * s["filled_notional"] * (bx / be - 1.0)
        exp = s["pnl_frac"] + hedge
        got = arms["SH"]["pnl"][-1]
        assert abs(got - exp) < 1e-12, (got, exp)
        assert arms["SH"]["ok"] == 1, arms["SH"]["ok"]
        # BTC упал → короткий BTC в плюс → SH ВЫШЕ голого S
        assert got > arms["S"]["pnl"][-1], (got, arms["S"]["pnl"][-1])
        print(f"ok  бета-хедж: SH={got:+.4f} = S{arms['S']['pnl'][-1]:+.4f} "
              f"+ хедж{hedge:+.4f}")
    finally:
        D.build_levels = orig


def test_short_stats_diversify_measure():
    # Мера диверсификации (§в) обязана РАЗЛИЧАТЬ анти- и со-движущийся шорт.
    days = ["2026-01-%02d" % i for i in range(1, 11)]
    ldn = [10, -10, 5, -5, 8, -8, 3, -3, 6, -6]           # дни лонг-книги
    long_day = dict(zip(days, ldn))
    # анти-коррелированный шорт → corr<0, в худший день лонга шорт в ПЛЮСЕ
    anti = [-3, 8, -1, 4, -2, 6, -1, 2, -2, 5]
    a = D._short_stats(list(anti), dict(zip(days, anti)), 0, 10, long_day)
    assert a["corr_daily"] < 0, a
    assert a["long_worst_days"] == 1 and abs(a["long_worst_mean"] + 10) < 1e-9, a
    assert a["short_on_long_worst_mean"] > 0, a
    # со-движущийся шорт (= знак лонга) → corr>0, в худший день лонга МИНУС
    co = ldn[:]
    c = D._short_stats(list(co), dict(zip(days, co)), 0, 10, long_day)
    assert c["corr_daily"] > 0 and c["short_on_long_worst_mean"] < 0, c
    print(f"ok  шорт-контур различает: анти corr {a['corr_daily']:+.2f} / "
          f"со-хвост {a['short_on_long_worst_mean']:+.1f}; "
          f"со corr {c['corr_daily']:+.2f} / {c['short_on_long_worst_mean']:+.1f}")


def _control_flat_btc():
    """Если BTC не движется (be == bx), хедж = 0 и SH == S — проверка
    «SH выше S при падении BTC» обязана упасть. Доказывает, что тест
    ДЕЙСТВИТЕЛЬНО меряет хедж, а не проходит на любых числах."""
    orig_px = D.px_at
    D.px_at = lambda bars, ts, t: 60000.0
    try:
        try:
            test_hedge_arm_arithmetic()
        except AssertionError:
            return True
        return False
    finally:
        D.px_at = orig_px


def _control_no_gap_check():
    """Без проверки запаса слишком близкие уровни попали бы в рунги —
    тест «слишком близкий пропущен» обязан упасть."""
    orig = D.structural_rungs

    def no_gap(entry, level_prices, min_gap, n_rungs):
        below = sorted([p for p in level_prices if 0 < p < entry],
                       reverse=True)
        return ([entry] + below)[:n_rungs]
    D.structural_rungs = no_gap
    try:
        try:
            test_rungs_skip_too_close()
        except AssertionError:
            return True
        return False
    finally:
        D.structural_rungs = orig


TESTS = [
    test_rungs_below_with_reserve,
    test_rungs_skip_too_close,
    test_rungs_ignore_above,
    test_rungs_cap_at_n,
    test_split_window,
    test_split_window_no_future,
    test_px_at,
    test_hedge_arm_arithmetic,
    test_short_stats_diversify_measure,
]


def main():
    for t in TESTS:
        t()
    assert _control_no_gap_check(), "контроль запаса не кусается"
    assert _control_flat_btc(), "контроль плоского BTC не кусается"
    print(f"\nвсе {len(TESTS)} проверки прошли; контроли запаса и хеджа кусаются")


if __name__ == "__main__":
    main()
