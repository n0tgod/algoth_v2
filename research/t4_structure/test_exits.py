#!/usr/bin/env python3
"""
Тесты потолка геометрии.

Здесь два места, где ошибка была бы невидимой в результате, и оба уже
случились при написании замера:

* **ничья внутри бара.** Минутный бар не разрешает порядок касаний, и
  если решать её в свою пользу, потолок вырастет на ровном месте. Правило
  «против нас» то же, что в T3/T4, и закреплено числом;
* **просадка считается ДО цели, а не по всему окну.** Первая версия
  брала минимум по всем четырём часам, поэтому сделка, взявшая цель на
  пятой минуте, объявлялась не пережившей провал, случившийся через час.
  Потолок с ограничением выходил ниже фактического результата — то есть
  «идеальный стоп» проигрывал обычному, чего быть не может.

    python3 research/t4_structure/test_exits.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import exits as EX  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def bars(seq, t0=60):
    """Свечи из списка (high, low) на минутной сетке."""
    return {t0 + 60 * i: (lo, hi, lo, hi) for i, (hi, lo) in enumerate(seq)}


def row(pos=1, entry=100.0, stop=99.0, target=102.0):
    return {"sym": "X", "t": 0, "pos": pos, "entry": entry,
            "stop": stop, "target": target}


def test_tie_inside_bar_goes_against_us():
    # Бар, накрывающий и стоп, и цель. Порядок неизвестен — значит стоп.
    w = EX.walk(bars([(103.0, 98.0)]), row())
    check("ничья внутри бара — стоп", w["hit"] == "стоп", w["hit"])
    check("ничья засчитана по цене стопа", abs(w["gross"] + 100.0) < 1e-9,
          str(w["gross"]))


def test_target_and_stop_read_in_order():
    w = EX.walk(bars([(101.0, 99.5), (102.5, 101.0)]), row())
    check("цель взята вторым баром", w["hit"] == "цель", w["hit"])
    w = EX.walk(bars([(100.5, 98.5), (103.0, 102.0)]), row())
    check("стоп раньше цели", w["hit"] == "стоп", w["hit"])


def test_short_flips_the_sign():
    # В шорте прибыль — падение цены. Вход 100, цель 98, стоп 101.
    w = EX.walk(bars([(100.2, 97.5)]), row(pos=-1, stop=101.0, target=98.0))
    check("в шорте цель ниже входа", w["hit"] == "цель", w["hit"])
    check("ход в пользу положителен", w["best"] > 0, str(w["best"]))


def test_drawdown_measured_before_target_not_after():
    # Цель взята на первом баре; провал приходит на третьем и к сделке
    # отношения не имеет — она уже вышла.
    w = EX.walk(bars([(102.5, 99.9), (101.0, 99.0), (100.0, 50.0)]), row())
    check("цель достигнута", w["target_ever"], "не достигнута")
    check("просадка до цели мелкая",
          abs(w["worst_pre"] - (-10.0)) < 1e-6, str(w["worst_pre"]))
    check("просадка по всему окну — другая величина",
          w["worst"] < -4000, str(w["worst"]))


def test_wider_stop_lets_losers_run():
    # Ровно тот эффект, из-за которого расширение стопа ухудшает
    # результат в среднем: одна сделка спасается, две теряют больше.
    # Путь задаётся в БАЗИСНЫХ ПУНКТАХ от входа, парами (в пользу,
    # против) — первая версия теста писала сюда цены, и `bracket` не
    # находил ни стопа, ни цели вовсе.
    dip = (50.0, -150.0)                       # обе просели ниже узкого
    saved = {"path": [dip, (250.0, 0.0)]}      # потом дошла до цели
    lost = {"path": [dip, (-100.0, -450.0)]}   # потом провалилась дальше
    trades = [saved, lost, lost]
    tight = [EX.bracket(w["path"], -100.0, 200.0, 0.0)[1] for w in trades]
    wide = [EX.bracket(w["path"], -400.0, 200.0, 0.0)[1] for w in trades]
    check("узкий стоп выбивает все три", tight == [-100.0] * 3, str(tight))
    check("широкий спасает первую и топит остальные",
          wide == [200.0, -400.0, -400.0], str(wide))
    check("в сумме расширение хуже",
          sum(wide) < sum(tight), f"{sum(wide)} против {sum(tight)}")


def test_no_bars_is_not_a_zero_trade():
    # Пустое окно — пропуск, а не наблюдение с нулевым исходом. Урок A2.
    check("нет баров — нет замера", EX.walk({}, row()) is None, "вернулось")


def main():
    print("порядок касаний")
    test_tie_inside_bar_goes_against_us()
    test_target_and_stop_read_in_order()
    test_short_flips_the_sign()
    print("просадка")
    test_drawdown_measured_before_target_not_after()
    print("геометрия")
    test_wider_stop_lets_losers_run()
    test_no_bars_is_not_a_zero_trade()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
