"""Тесты разбора и сведения записи стакана.

Проверяется не арифметика, а три места, где ошибка была бы невидимой:
момент наблюдения (метка `t` ставится один раз на весь проход), ключи
разбора (`"bid":` против `"bid_sz":`) и пустая минута, которая обязана
остаться пропуском, а не нулём.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bookfeat2 as B                                     # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name
          + ("" if cond else f"  · {extra}"))
    if not cond:
        FAILED.append(name)


def snap(t, ts_ms, bid, ask, bq=1000.0, aq=1200.0, upd=7, bsz=3.0,
         asz=4.0, rb=50.0, ra=60.0):
    """Строка снимка ровно того вида, что пишет сборщик."""
    d = {"s": "AAAUSDT", "ts": ts_ms, "u": 1, "bid": bid, "ask": ask,
         "bid_sz": bsz, "ask_sz": asz, "upd": upd,
         "b": [[bid, bsz], [bid - 1, 5.0]], "a": [[ask, asz]],
         "reach_b": rb, "reach_a": ra,
         "bq0.0005": 10.0, "aq0.0005": 11.0,
         "bq0.001": 20.0, "aq0.001": 21.0,
         "bq0.0025": bq, "aq0.0025": aq,
         "bq0.005": 2000.0, "aq0.005": 2100.0, "t": t}
    # Компактно, как пишет сборщик (`separators=(",", ":")`): пробел
    # после двоеточия сделал бы фикстуру непохожей на живую запись, а
    # разбор ищет ключи вместе с двоеточием.
    return json.dumps(d, separators=(",", ":"))


def test_light_parse_matches_json():
    """Быстрый разбор обязан совпасть с `json.loads` дословно."""
    line = snap(1700000000.5, 1700000002000, 100.0, 100.2)
    got = B.snap_line(line)
    d = json.loads(line)
    mid = (d["bid"] + d["ask"]) / 2.0
    want = (max(d["t"], d["ts"] / 1000.0), mid,
            (d["ask"] - d["bid"]) / mid * 1e4, d["bid_sz"], d["ask_sz"],
            d["upd"], min(d["reach_b"], d["reach_a"]),
            d["bq0.0025"], d["aq0.0025"])
    check("лёгкий разбор совпал с json.loads",
          all(abs(a - b) < 1e-9 for a, b in zip(got, want)),
          f"{got} против {want}")


def test_observation_moment_is_the_later_of_two_stamps():
    """Метка `t` ставится ОДИН РАЗ на весь проход по символам.

    Проход занимает от 0.18 до 2.5 секунды, значит у символов, до
    которых очередь дошла позже, содержимое снимка новее собственной
    метки — заглядывание ровно того размера, который решает на
    секундных горизонтах. Моментом наблюдения служит позднее из двух
    времён: биржевая метка не бывает в будущем относительно чтения.
    """
    late = B.snap_line(snap(1700000000.0, 1700000002400, 100.0, 100.2))
    check("момент наблюдения — биржевая метка, если она позже",
          abs(late[0] - 1700000002.4) < 1e-6, str(late[0]))
    stale = B.snap_line(snap(1700000010.0, 1700000002000, 100.0, 100.2))
    check("у неактивного символа момент — наша метка",
          abs(stale[0] - 1700000010.0) < 1e-6, str(stale[0]))


def test_empty_minute_is_a_gap_not_zeros():
    t0 = 1700000000
    snaps = [B.snap_line(snap(t0 + 5, (t0 + 5) * 1000, 100.0, 100.2))]
    got = B.fold(snaps, [], t0, 3)
    check("минута со снимком заполнена", got["snaps"][0] == 1,
          str(got["snaps"]))
    check("минуты без снимков — пропуск, а не нули",
          got["snaps"][1] is None and got["depth_b"][1] is None
          and got["path"][1] is None, str(got["snaps"]))


def test_quiet_path_counts_moves_without_trades():
    """Ход середины БЕЗ единой сделки — величина, которой нет в ленте."""
    t0 = 1700000000
    snaps = [B.snap_line(snap(t0 + 1, (t0 + 1) * 1000, 100.0, 100.2)),
             B.snap_line(snap(t0 + 2, (t0 + 2) * 1000, 100.5, 100.7)),
             B.snap_line(snap(t0 + 3, (t0 + 3) * 1000, 101.0, 101.2))]
    quiet = B.fold(snaps, [], t0, 1)
    check("без сделок весь путь тихий",
          abs(quiet["path"][0] - quiet["path_quiet"][0]) < 1e-9,
          f"{quiet['path'][0]} против {quiet['path_quiet'][0]}")
    loud = B.fold(snaps, [(t0 + 2.5, -1, 500.0)], t0, 1)
    check("сделка в интервале снимает тихую часть",
          loud["path_quiet"][0] < quiet["path_quiet"][0] - 1e-9,
          f"{loud['path_quiet'][0]} против {quiet['path_quiet'][0]}")
    check("сам путь от сделок не меняется",
          abs(loud["path"][0] - quiet["path"][0]) < 1e-9, "")


def test_pull_separates_cancels_from_trades():
    """Снятие заявок — то, что НЕ объяснено сделками.

    Это и есть недостающий знаменатель четырёх замеров ленты: они
    видели, сколько агрессии прошло через уровень, и не видели,
    подставляли ли уровень заново.
    """
    t0 = 1700000000
    # Глубина бида упала на 400, продажами объяснено 400 — снятия нет.
    eaten = [B.snap_line(snap(t0 + 1, (t0 + 1) * 1000, 100.0, 100.2,
                              bq=1000.0)),
             B.snap_line(snap(t0 + 2, (t0 + 2) * 1000, 100.0, 100.2,
                              bq=600.0))]
    got = B.fold(eaten, [(t0 + 1.5, -1, 400.0)], t0, 1)
    check("выеденная глубина снятием не считается",
          abs(got["pull_bid"][0]) < 1e-9, str(got["pull_bid"][0]))
    # Та же глубина упала БЕЗ единой сделки — это снятие.
    got2 = B.fold(eaten, [], t0, 1)
    check("падение глубины без сделок — снятие",
          abs(got2["pull_bid"][0] - 400.0) < 1e-9, str(got2["pull_bid"][0]))
    # Глубина выросла при тех же продажах — подставили больше, чем съели.
    refill = [B.snap_line(snap(t0 + 1, (t0 + 1) * 1000, 100.0, 100.2,
                               bq=1000.0)),
              B.snap_line(snap(t0 + 2, (t0 + 2) * 1000, 100.0, 100.2,
                               bq=1200.0))]
    got3 = B.fold(refill, [(t0 + 1.5, -1, 400.0)], t0, 1)
    check("восполнение сверх съеденного даёт отрицательное снятие",
          got3["pull_bid"][0] < -500.0, str(got3["pull_bid"][0]))


def test_path_is_not_stitched_across_minutes():
    """Путь минуты не сшивается с прошлой: это её собственная величина."""
    t0 = 1700000000
    snaps = [B.snap_line(snap(t0 + 59, (t0 + 59) * 1000, 100.0, 100.2)),
             B.snap_line(snap(t0 + 61, (t0 + 61) * 1000, 110.0, 110.2))]
    got = B.fold(snaps, [], t0, 2)
    check("скачок между минутами не попал в путь второй минуты",
          got["path"][1] == 0.0, str(got["path"][1]))


TESTS = [test_light_parse_matches_json,
         test_observation_moment_is_the_later_of_two_stamps,
         test_empty_minute_is_a_gap_not_zeros,
         test_quiet_path_counts_moves_without_trades,
         test_pull_separates_cancels_from_trades,
         test_path_is_not_stitched_across_minutes]


def main():
    for t in TESTS:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)} — " + ", ".join(FAILED))
        return 1
    print(f"все проверки прошли ({len(TESTS)} блоков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
