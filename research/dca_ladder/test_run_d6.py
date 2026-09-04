#!/usr/bin/env python3
"""Тесты D6 — нормировка кассы.

Проверяется то, где ошибка была бы НЕВИДИМОЙ в отчёте и при этом решала
бы спор «мало крупных против много мелких» в чью-то пользу:

* **Бюджет не превышается.** Раздача, забывшая вычесть маржу, открыла бы
  все сигналы при любой доле — и «много мелких» победило бы арифметикой,
  а не рынком.
* **Деньги возвращаются раньше, чем тратятся.** Позиция, закрывшаяся в ту
  же секунду, обязана освободить кассу до нового входа: иначе узкая книга
  теряет входы, которых на бирже не потеряла бы (живое правило кассы
  проекта).
* **Мелкий ордер — отказ, а не округление.** Округлив до минимума биржи,
  мы дали бы позиции больше денег, чем позволяет доля.
* **Причины отказа считаются врозь.** «Нет кассы» лечится числом мест,
  «мельче $5» — только депозитом; одна колонка вместо двух лечила бы не
  то.
* **Внутри секунды деньги достаются лучшим по |прогноз|.** Раздача по
  порядку прихода сравнивала бы удачу, а не ширину.

Запуск из `.venv/bin/python` (тянет numpy).
"""
import calendar
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d6 as D6                                           # noqa: E402
import run_d2 as D2                                           # noqa: E402
import trades as TR                                           # noqa: E402

H = D6.HOUR


def _rec(at, hold_h=1.0, pnl=0.10, lev=4.0, fwd=100.0, sym="AAAUSDT"):
    """Позиция с готовым исходом: раздаче больше ничего не нужно."""
    ex = at + hold_h * H
    return {"at": float(at), "exit_ts": float(ex), "pnl": float(pnl),
            "lev": float(lev), "fwd": float(fwd), "sym": sym,
            "exit": "тейк", "marks": [(int(at) - int(at) % H, float(pnl))]}


def test_budget_is_respected():
    """Шесть мест — не больше шести позиций разом, сколько ни предлагай."""
    recs = [_rec(1_700_000_000 + i, hold_h=10.0, pnl=0.0) for i in range(50)]
    r = D6.ration(recs, 1.0 / 6, deposit=3000.0)
    assert r["taken"] == 6, r
    assert r["no_cash"] == 44, r
    assert r["open_max"] <= 6, r
    # шире доля — больше входов, и это монотонно
    wide = D6.ration(recs, 1.0 / 20, deposit=3000.0)
    assert wide["taken"] == 20 and wide["taken"] > r["taken"], (wide, r)
    print(f"ok  бюджет: 6 мест → взято {r['taken']}, отказов по кассе "
          f"{r['no_cash']}; 20 мест → {wide['taken']}")


def test_money_returns_before_it_is_spent():
    """Закрытие в ту же секунду освобождает кассу до нового входа.

    Одно место: вторая позиция входит ровно в секунду выхода первой. Если
    порядок перевернуть, она получит отказ по кассе — вход, которого на
    бирже не потерялось бы.
    """
    a = _rec(1_700_000_000, hold_h=1.0, pnl=0.0)
    b = _rec(int(a["exit_ts"]), hold_h=1.0, pnl=0.0)
    r = D6.ration([a, b], 1.0, deposit=3000.0)
    assert r["taken"] == 2 and r["no_cash"] == 0, r
    # а если вторая приходит РАНЬШЕ выхода первой — касса занята
    c = _rec(int(a["exit_ts"]) - 60, hold_h=1.0, pnl=0.0)
    r2 = D6.ration([a, c], 1.0, deposit=3000.0)
    assert r2["taken"] == 1 and r2["no_cash"] == 1, r2
    print("ok  касса: выход в ту же секунду освобождает деньги, вход "
          "минутой раньше — нет")


def test_min_notional_rejects_not_rounds():
    """Мелкий ордер отвергается, и причина считается отдельной колонкой."""
    # доля 1/600 при депозите 3000 → маржа $5, плечо 4 → нотионал $20,
    # рунг $5 — ровно на границе, проходит
    ok = D6.ration([_rec(1_700_000_000, lev=4.0)], 1.0 / 600, deposit=3000.0)
    assert ok["taken"] == 1 and ok["too_small"] == 0, ok
    # то же место при плече 1× → нотионал $5, рунг $1.25 — отказ
    bad = D6.ration([_rec(1_700_000_000, lev=1.0)], 1.0 / 600, deposit=3000.0)
    assert bad["taken"] == 0 and bad["too_small"] == 1, bad
    assert bad["no_cash"] == 0, bad          # причина именно размера
    print(f"ok  минимум биржи: при плече 4 рунг ${3000 / 600 * 4 * 0.25:.2f} "
          f"проходит, при 1× — отказ, и он не путается с «нет кассы»")


def test_leverage_sets_the_ticket():
    """Меньше плечо — крупнее минимальный кусок депозита, у́же книга.

    Это и есть найденное взаимодействие двух рычагов: σ-линейка снижает
    плечо и тем самым уменьшает число мест, которые влезают в депозит.
    """
    recs = [_rec(1_700_000_000 + i, hold_h=10.0, pnl=0.0, lev=3.0)
            for i in range(300)]
    hi = D6.ration(recs, 1.0 / 200, deposit=3000.0)
    low = D6.ration([dict(r, lev=1.0) for r in recs], 1.0 / 200,
                    deposit=3000.0)
    assert hi["taken"] > 0 and low["taken"] == 0, (hi, low)
    assert low["too_small"] == 300, low
    print(f"ok  плечо задаёт билет: при 3× взято {hi['taken']}, при 1× — "
          f"{low['taken']} (все {low['too_small']} мельче минимума)")


def test_best_first_within_a_second():
    """Внутри секунды деньги достаются лучшим по |прогноз|, не первым."""
    at = 1_700_000_000
    weak = _rec(at, hold_h=10.0, pnl=-0.5, fwd=40.0, sym="WEAK")
    strong = _rec(at, hold_h=10.0, pnl=+0.5, fwd=900.0, sym="STRONG")
    r = D6.ration([weak, strong], 1.0, deposit=3000.0)   # одно место
    assert r["taken"] == 1, r
    assert r["final"] > 0, r          # взят сильный, а не пришедший первым
    print(f"ok  очередь: при одном месте взят сильный сигнал, "
          f"итог {r['final']:+.4f}")


def test_deposit_units_and_curve():
    """Доход и просадка считаются в долях ДЕПОЗИТА, а не позиции."""
    r = D6.ration([_rec(1_700_000_000, hold_h=1.0, pnl=0.20)], 1.0 / 6,
                  deposit=3000.0)
    # одна позиция на 1/6 депозита с исходом +20 % даёт +3.33 % счёта
    # сводка округляется до четвёртого знака — ожидание берётся тем же
    # округлением, а не «по памяти о правиле» (урок формата процентов)
    assert abs(r["final"] - round(0.2 / 6, 4)) < 1e-12, r
    assert r["ticket"] == 500.0 and r["slots"] == 6, r
    print(f"ok  единица: +20 % позиции на 1/6 депозита = "
          f"{r['final'] * 100:+.2f} % счёта")


def test_report_names_both_refusals():
    st = {"positions": 10, "skipped": 0, "secs": 1.0,
          "params": {"DEPOSIT": 3000.0}, "unlimited": {},
          "cells": {f"depth|2.0|{D6.GRID_SHARE[0]:.6f}":
                    D6.ration([_rec(1_700_000_000)], D6.GRID_SHARE[0])}}
    rep = D6.report(st)
    assert "нет кассы" in rep and "мельче $5" in rep, rep[:900]
    assert "проценты ДЕПОЗИТА" in rep, rep[:900]
    assert "nan" not in rep.lower(), rep
    print("ok  отчёт: обе причины отказа названы и лечатся разным")


# ------------------------------------------------------ отрицательные контроли

def test_concentration_names_one_coin():
    """Итог, принадлежащий одному имени, обязан быть виден числом.

    Урок лиги и one_name.py: колонка «без лучшего имени» переворачивала
    знак у целых групп. Здесь всё зарабатывает TUT, остальные в нуле —
    итог без него обязан сойтись к нулю, а имя быть названо.
    """
    t0 = 1_700_000_000
    recs = [_rec(t0 + i, hold_h=1.0, pnl=0.0, sym=f"C{i}USDT")
            for i in range(5)]
    recs.append(_rec(t0 + 5, hold_h=1.0, pnl=0.50, sym="TUTUSDT"))
    r = D6.ration(recs, 1.0 / 6, deposit=3000.0)
    assert r["taken"] == 6, r
    assert r["names"] == 6, r
    assert r["top_sym"] == "TUTUSDT", r
    # 0.50 на позицию в 500 $ = 250 $ = 8.33 % депозита
    assert abs(r["final"] - round(250.0 / 3000.0, 4)) < 1e-9, r
    assert abs(r["final_wo_top"]) < 1e-9, r
    assert abs(r["top_pnl"] - 250.0) < 1e-6, r
    assert abs(r["top_trade"] - 250.0) < 1e-6, r
    print(f"ok  концентрация: итог {_pc(r['final'])}, без "
          f"{r['top_sym']} {_pc(r['final_wo_top'])}")


def _pc(x):
    return f"{100.0 * x:+.2f} %"


def test_report_carries_concentration():
    """Число, не доехавшее до отчёта, владельцу не существует."""
    t0 = 1_700_000_000
    recs = [_rec(t0 + i, hold_h=1.0, pnl=0.0, sym=f"C{i}USDT")
            for i in range(5)]
    recs.append(_rec(t0 + 5, hold_h=1.0, pnl=0.50, sym="TUTUSDT"))
    cells = {}
    for rule, param in D6.GRID_RULER:
        for sh in D6.GRID_SHARE:
            cells[f"{rule}|{param}|{sh:.6f}"] = D6.ration(
                recs, sh, deposit=3000.0)
    txt = D6.report({"positions": 6, "skipped": 0, "secs": 1.0,
                     "grid": {}, "params": {"DEPOSIT": 3000.0},
                     "cells": cells, "unlimited": {}})
    assert "Концентрация" in txt, txt[:400]
    assert "TUTUSDT" in txt, txt[-1500:]
    assert "ВЫЧИТАНИЕ, а не пересчёт" in txt, txt[-1500:]
    assert "Ячейки не парны" in txt, txt[-2500:]
    print("ok  отчёт: концентрация названа именем и оговорена вычитанием")


def _control_no_concentration():
    """Итог без лучшего имени, равный итогу, — колонка ничего не считает."""
    orig = D6.ration

    def flat(recs, share, deposit=D6.DEPOSIT, min_notional=D6.MIN_NOTIONAL):
        r = orig(recs, share, deposit, min_notional)
        r["final_wo_top"] = r["final"]
        return r
    D6.ration = flat
    try:
        try:
            test_concentration_names_one_coin()
        except AssertionError:
            return True
        return False
    finally:
        D6.ration = orig


def test_window_is_measured_and_reported():
    """Доход в процентах без окна не читается — окно обязано быть в отчёте."""
    t0 = calendar.timegm((2026, 8, 8, 0, 0, 0))   # не магическое число
    longs = [{"at": t0 + 3 * H}, {"at": t0 + 27 * 24 * H + 5 * H}]
    w = D6.window(longs)
    assert w["from"].startswith("2026-08-08"), w
    assert w["to"].startswith("2026-09-04"), w
    assert abs(w["span_d"] - 27.1) < 0.15, w
    assert D6.window([]) is None
    txt = D6.report({"positions": 2, "skipped": 0, "secs": 1.0, "grid": {},
                     "params": {"DEPOSIT": 3000.0}, "cells": {},
                     "unlimited": {}, "window": w})
    assert "Окно замера: 2026-08-08" in txt, txt[:900]
    assert "27.1 суток" in txt, txt[:900]
    # отчёт прежнего образца обязан СКАЗАТЬ, что окна нет, а не молчать
    old = D6.report({"positions": 2, "skipped": 0, "secs": 1.0, "grid": {},
                     "params": {"DEPOSIT": 3000.0}, "cells": {},
                     "unlimited": {}})
    assert "Окно замера не записано" in old, old[:900]
    print(f"ok  окно: {w['from']} … {w['to']} UTC, {w['span_d']:g} суток")


def test_restat_says_the_journal_grew():
    """Окно, дописанное позже прогона, обязано назвать хвост числом."""
    t0 = calendar.timegm((2026, 8, 8, 0, 0, 0))
    w = D6.window([{"at": t0}, {"at": t0 + 27 * 24 * H}])
    w["grown"] = 42
    txt = D6.report({"positions": 8676, "skipped": 0, "secs": 1.0, "grid": {},
                     "params": {"DEPOSIT": 3000.0}, "cells": {},
                     "unlimited": {}, "window": w})
    assert "вырос на 42 выборов" in txt, txt[:1200]
    w.pop("grown")
    clean = D6.report({"positions": 8676, "skipped": 0, "secs": 1.0,
                       "grid": {}, "params": {"DEPOSIT": 3000.0},
                       "cells": {}, "unlimited": {}, "window": w})
    assert "вырос на" not in clean, clean[:1200]
    print("ok  restat: рост журнала назван числом, у ровного окна молчит")


def test_percent_of_deposit_is_invariant_to_deposit():
    """Пока пол биржи не связывает, процент к депозиту от депозита не зависит.

    Это не удобство, а свойство конструкции: маржа пропорциональна счёту,
    исход позиции есть доля её капитала. Значит «пересчитать таблицу на
    другой депозит» меняет ровно то, что упирается в абсолютные $5.
    """
    recs = [_rec(1_700_000_000 + i, hold_h=2.0, pnl=0.10, lev=4.0,
                 sym=f"C{i}USDT") for i in range(40)]
    a = D6.ration(recs, 1.0 / 20, deposit=3000.0, min_notional=0.0)
    b = D6.ration(recs, 1.0 / 20, deposit=10000.0, min_notional=0.0)
    assert a["taken"] == b["taken"], (a, b)
    assert abs(a["final"] - b["final"]) < 1e-12, (a["final"], b["final"])
    assert abs(a["max_dd"] - b["max_dd"]) < 1e-12, (a, b)
    # а с полом биржи мелкий депозит теряет входы, крупный — нет:
    # при плече 3 билет $5 даёт рунг $3.75 (мельче минимума), билет
    # $16.67 — рунг $12.5 (проходит)
    thin = [_rec(1_700_000_000 + i, hold_h=2.0, pnl=0.10, lev=3.0,
                 sym=f"C{i}USDT") for i in range(40)]
    c = D6.ration(thin, 1.0 / 600, deposit=3000.0)
    d = D6.ration(thin, 1.0 / 600, deposit=10000.0)
    assert c["too_small"] > 0 and d["too_small"] == 0, (c, d)
    assert d["taken"] > c["taken"], (c, d)
    print(f"ok  инвариант: {_pc(a['final'])} на $3000 и $10000 без пола; "
          f"с полом взято {c['taken']} против {d['taken']}")


def test_scale_invariance_holds_on_the_cash_boundary():
    """Тот же набор сделок — тот же процент, на любом депозите.

    Пограничный случай нарочно: шесть мест наполняют счёт ровно, и
    абсолютный допуск кассы решал такой вход по-разному на разных
    депозитах — «тот же замер на другом депозите» переставал быть тем же.
    """
    recs = [_rec(1_700_000_000 + i, hold_h=3.0, pnl=0.10 + 0.01 * (i % 5),
                 lev=4.0, sym=f"C{i}USDT") for i in range(30)]
    a = D6.ration(recs, 1.0 / 6, deposit=3000.0)
    b = D6.ration(recs, 1.0 / 6, deposit=10000.0)
    assert a["fp"] == b["fp"], (a["fp"], b["fp"])
    assert abs(a["final"] - b["final"]) < 1e-9, (a["final"], b["final"])
    assert abs(a["pnl_taken"] - b["pnl_taken"]) < 1e-9, (a, b)
    # отпечаток обязан РАЗЛИЧАТЬ наборы, иначе он ничего не стережёт
    # берём ДРУГИЕ первые шесть: обрезка хвоста набор не меняет — при
    # шести местах входят первые шесть очереди
    c = D6.ration(recs[5:], 1.0 / 6, deposit=3000.0)
    assert c["fp"] != a["fp"], (c["fp"], a["fp"])
    print(f"ok  масштаб: набор {a['fp']} и {_pc(a['final'])} на обоих "
          "депозитах")


def test_deposit_anchor_catches_a_broken_measure():
    """Расхождение при СОВПАВШЕМ наборе — сломанная мера, не находка."""
    ok = {"params": {"DEPOSIT": 10000.0}, "anchor_dep": 3000.0,
          "cells": {"a": {"final": 0.10, "too_small": 0, "fp": "x"},
                    "b": {"final": 0.25, "too_small": 0, "fp": "p"}},
          "anchor_cells": {"a": {"final": 0.10, "too_small": 0, "fp": "x"},
                           "b": {"final": 0.20, "too_small": 3000,
                                 "fp": "q"}}}
    a = D6.anchor_deposit(ok)
    assert a and not a["bad"], a
    assert a["n_same"] == 1, a
    bad = {"params": {"DEPOSIT": 10000.0}, "anchor_dep": 3000.0,
           "cells": {"a": {"final": 0.17, "too_small": 0, "fp": "x"}},
           "anchor_cells": {"a": {"final": 0.10, "too_small": 0,
                                  "fp": "x"}}}
    a2 = D6.anchor_deposit(bad)
    assert a2["bad"] == ["a"], a2
    txt = D6.report({"positions": 1, "skipped": 0, "secs": 1.0, "grid": {},
                     "params": {"DEPOSIT": 10000.0}, "cells": {},
                     "unlimited": {}, "anchor_deposit": a2})
    assert "Мера сломана" in txt, txt[-1200:]
    assert "тот же набор, а процент другой" in txt, txt[-1200:]
    # другой набор БЕЗ пола — тоже сломанная мера, и названа отдельно
    drift = {"params": {"DEPOSIT": 10000.0}, "anchor_dep": 3000.0,
             "cells": {"a": {"final": 0.17, "too_small": 0, "fp": "x"}},
             "anchor_cells": {"a": {"final": 0.10, "too_small": 0,
                                    "fp": "y"}}}
    a3 = D6.anchor_deposit(drift)
    assert a3["bad"] == ["a"], a3
    # опоры нет вовсе, если сравнивать не с чем
    assert D6.anchor_deposit({"params": {"DEPOSIT": 3000.0},
                              "cells": {}}) is None
    print("ok  опора депозита: расхождение при совпавшем наборе — сломано")


def test_peak_open_counts_simultaneous_positions():
    """Пик — максимум одновременно открытых, и стык не задваивается."""
    t0 = 1_700_000_000
    # три позиции внахлёст: пик 3
    recs = [_rec(t0, hold_h=3.0), _rec(t0 + 60, hold_h=3.0),
            _rec(t0 + 120, hold_h=3.0)]
    assert D6.peak_open(recs) == 3, D6.peak_open(recs)
    # встык: закрытие в ту же секунду, что открытие — пик 1, не 2
    a = _rec(t0, hold_h=1.0)
    b = _rec(int(a["exit_ts"]), hold_h=1.0)
    assert D6.peak_open([a, b]) == 1, D6.peak_open([a, b])
    print("ok  пик: внахлёст 3, встык 1 — стык не задваивается")


def test_full_cover_takes_every_signal():
    """Депозит полного охвата берёт ВСЕ и выводится из слабейшего плеча."""
    t0 = 1_700_000_000
    # десять позиций внахлёст; у одной плечо 1 — она и назначает билет
    recs = [_rec(t0 + i, hold_h=5.0, pnl=0.10, lev=4.0, sym=f"C{i}USDT")
            for i in range(10)]
    recs[3]["lev"] = 1.0
    f = D6.full_cover(recs, log=lambda *_: None)
    assert f["peak"] == 10, f
    assert f["lev_min"] == 1.0, f
    # билет = 5 / 0.25 / 1 = 20 $, пол депозита = 10 × 20 = 200 $
    assert abs(f["ticket"] - 20.0) < 1e-9, f
    assert abs(f["floor_dep"] - 200.0) < 1e-9, f
    assert f["deposit"] is not None and f["cell"]["taken"] == 10, f
    assert f["cell"]["no_cash"] == 0 and f["cell"]["too_small"] == 0, f
    # тождество: доход = сумма исходов / пик (депозит не входит вовсе)
    exp = round(sum(r["pnl"] for r in recs) / f["peak"], 4)
    assert abs(f["cell"]["final"] - exp) < 5e-4, (f["cell"]["final"], exp)
    # депозит МЕНЬШЕ пола обязан терять сигналы
    thin = D6.ration(recs, 1.0 / f["peak"], deposit=f["floor_dep"] * 0.5)
    assert thin["taken"] < 10, thin
    print(f"ok  полный охват: пик {f['peak']}, билет ${f['ticket']:g}, "
          f"депозит ${f['deposit']:.0f}, доход {_pc(f['cell']['final'])}")


def test_report_carries_full_cover():
    """Число, не доехавшее до отчёта, владельцу не существует."""
    t0 = 1_700_000_000
    recs = [_rec(t0 + i, hold_h=5.0, pnl=0.10, lev=4.0, sym=f"C{i}USDT")
            for i in range(10)]
    recs[3]["lev"] = 1.0
    f = D6.full_cover(recs, log=lambda *_: None)
    f["curve"] = D6.coverage_curve(recs, f["peak"],
                                   [f["deposit"] * 0.5, f["deposit"]])
    txt = D6.report({"positions": 10, "skipped": 0, "secs": 1.0, "grid": {},
                     "params": {"DEPOSIT": 3000.0}, "cells": {},
                     "unlimited": {}, "full": {"depth|2.0": f}})
    assert "Полный охват" in txt, txt[:600]
    assert "$200" in txt or "$201" in txt or "$2" in txt, txt[-2000:]
    assert "САМАЯ СЛАБАЯ по плечу" in txt, txt[-2000:]
    assert "Чем платит депозит меньше полного" in txt, txt[-2000:]
    print("ok  отчёт: полный охват назван вместе с правилом билета")


def _control_no_full_cover():
    """Билет от МЕДИАННОГО плеча вместо слабейшего — охват неполон."""
    orig = D6.full_cover

    def loose(recs, min_notional=D6.MIN_NOTIONAL, rung=D6.RUNG_SHARE,
              log=print):
        f = orig(recs, min_notional, rung, log)
        if f:
            f["ticket"] = round(f["ticket"] / 4.0, 2)
            f["floor_dep"] = round(f["peak"] * f["ticket"], 2)
        return f
    D6.full_cover = loose
    try:
        try:
            test_full_cover_takes_every_signal()
        except AssertionError:
            return True
        return False
    finally:
        D6.full_cover = orig


def _control_no_window():
    """Отчёт без окна — доход в процентах непонятно за что."""
    orig = D6._window_line
    D6._window_line = lambda w: ""
    try:
        try:
            test_window_is_measured_and_reported()
        except AssertionError:
            return True
        return False
    finally:
        D6._window_line = orig


def _control_blind_anchor():
    """Опора, объявляющая совпадением всё подряд, не проверяет ничего."""
    orig = D6.anchor_deposit

    def blind(s):
        a = orig(s)
        if a:
            a["bad"] = []
        return a
    D6.anchor_deposit = blind
    try:
        try:
            test_deposit_anchor_catches_a_broken_measure()
        except AssertionError:
            return True
        return False
    finally:
        D6.anchor_deposit = orig


def _control_no_budget():
    """Без вычета маржи любая доля берёт всё — ширина побеждает даром."""
    orig = D6.ration

    def loose(recs, share, deposit=D6.DEPOSIT, min_notional=D6.MIN_NOTIONAL):
        r = orig(recs, share, deposit, min_notional=0.0)
        r["taken"] += r["no_cash"]
        r["no_cash"] = 0
        return r
    D6.ration = loose
    try:
        try:
            test_budget_is_respected()
        except AssertionError:
            return True
        return False
    finally:
        D6.ration = orig


def _control_no_min_notional():
    """Без минимума биржи мелкий ордер проходит, и книга шире, чем можно."""
    orig = D6.ration
    D6.ration = (lambda recs, share, deposit=D6.DEPOSIT,
                 min_notional=D6.MIN_NOTIONAL:
                 orig(recs, share, deposit, min_notional=0.0))
    try:
        try:
            test_min_notional_rejects_not_rounds()
        except AssertionError:
            return True
        return False
    finally:
        D6.ration = orig


def _control_arrival_order():
    """Раздача по порядку прихода: узкая книга берёт случайные сигналы."""
    orig = D6.queue
    D6.queue = lambda recs: list(recs)
    try:
        try:
            # порядок списка — слабый первым; правило обязано его обойти
            test_best_first_within_a_second()
        except AssertionError:
            return True
        return False
    finally:
        D6.queue = orig


TESTS = [test_budget_is_respected, test_money_returns_before_it_is_spent,
         test_min_notional_rejects_not_rounds, test_leverage_sets_the_ticket,
         test_best_first_within_a_second, test_deposit_units_and_curve,
         test_report_names_both_refusals, test_concentration_names_one_coin,
         test_report_carries_concentration,
         test_window_is_measured_and_reported,
         test_restat_says_the_journal_grew,
         test_percent_of_deposit_is_invariant_to_deposit,
         test_deposit_anchor_catches_a_broken_measure,
         test_scale_invariance_holds_on_the_cash_boundary,
         test_peak_open_counts_simultaneous_positions,
         test_full_cover_takes_every_signal,
         test_report_carries_full_cover]

CONTROLS = [("бюджет не вычитается", _control_no_budget),
            ("минимум биржи снят", _control_no_min_notional),
            ("раздача по порядку прихода", _control_arrival_order),
            ("колонка без лучшего имени не считает",
             _control_no_concentration),
            ("окно замера не названо", _control_no_window),
            ("опора депозита не сверяет", _control_blind_anchor),
            ("билет не от слабейшего плеча", _control_no_full_cover)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
