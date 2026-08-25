#!/usr/bin/env python3
"""Проверки ядра потоков по ценовым уровням.

Каждое из трёх правил меры проверяется отдельно и с подделкой: правило,
которое нельзя уронить, ничего не защищает.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ladder as LD                                       # noqa: E402

FAILED = []


def check(name, ok, extra=""):
    print(("ok   " if ok else "ПРОВАЛ ") + name + ("" if ok else "  · "
                                                   + str(extra)))
    if not ok:
        FAILED.append(name)


def snap(t, bid, ask, b, a):
    return {"t": t, "bid": bid, "ask": ask, "b": b, "a": a}


def test_price_leaving_the_visible_ladder_is_not_a_cancel():
    """Цена, ушедшая за край лесенки, снятием НЕ является.

    Лесенка обрезана (50 уровней у альтов, 200 у BTC и ETH), и при ходе
    цены дальние уровни выпадают из видимости, не будучи отменёнными.
    Ровно этим загрязнена полосовая мера Z2, и здесь это чинится.
    """
    prev = [[100.0, 5.0], [99.0, 5.0], [98.0, 5.0]]
    cur = [[100.0, 5.0], [99.0, 5.0], [97.0, 5.0]]   # 98 ушла, 97 пришла
    f = LD.side_flows(prev, cur, {})
    check("выпавшая за край цена не снята", f["cancel"] == 0.0, str(f))
    check("пришедшая из-за края цена не добавлена", f["add"] == 0.0,
          str(f))
    check("знаменатель — только пересечение",
          f["vis"] == 100.0 * 5 + 99.0 * 5, str(f))


def test_decrease_explained_by_a_trade_is_not_a_cancel():
    """Убыль, объяснённая сделкой на этой же цене, — не снятие.

    Иначе «снятие» окажется переодетой агрессией, и знаменатель T1–T4
    снова не построится.
    """
    prev = [[100.0, 10.0]]
    cur = [[100.0, 4.0]]
    f = LD.side_flows(prev, cur, {100.0: 6.0})
    check("съедено ровно объёмом сделки", f["eat"] == 100.0 * 6.0, str(f))
    check("снятого нет", f["cancel"] == 0.0, str(f))
    part = LD.side_flows(prev, cur, {100.0: 2.0})
    check("часть без сделки идёт в снятое",
          part["eat"] == 200.0 and part["cancel"] == 400.0, str(part))


def test_level_death_without_a_print():
    """Уровень, ушедший в ноль без единой сделки, — смерть без принта.

    Величина, невыразимая ни на свечах, ни на ленте: заявку убрали, и
    следа не осталось нигде, кроме записанной книги.
    """
    f = LD.side_flows([[100.0, 7.0]], [[100.0, 0.0]], {})
    check("смерть без принта посчитана", f["dead"] == 700.0, str(f))
    alive = LD.side_flows([[100.0, 7.0]], [[100.0, 0.0]], {100.0: 7.0})
    check("уровень, который выели, мёртвым не считается",
          alive["dead"] == 0.0, str(alive))


def test_refill_is_counted_where_a_trade_happened():
    """Подставленное на цене, где была сделка, — это восполнение."""
    f = LD.side_flows([[100.0, 2.0]], [[100.0, 9.0]], {100.0: 3.0})
    check("восполнение посчитано", f["refill"] == 700.0, str(f))
    plain = LD.side_flows([[100.0, 2.0]], [[100.0, 9.0]], {})
    check("добавление без сделки восполнением не считается",
          plain["add"] == 700.0 and plain["refill"] == 0.0, str(plain))


def test_gap_gives_no_observation():
    """Разрыв в записи не даёт наблюдения, а не даёт ноль.

    Пятиминутная дыра иначе стала бы гигантским «снятием» — тот же
    класс дефекта, что окно по номеру точки в L2.
    """
    p = snap(100.0, 99.0, 101.0, [[99.0, 5.0]], [[101.0, 5.0]])
    near = snap(101.0, 99.0, 101.0, [[99.0, 1.0]], [[101.0, 5.0]])
    far = snap(400.0, 99.0, 101.0, [[99.0, 1.0]], [[101.0, 5.0]])
    check("соседние снимки дают наблюдение",
          LD.pair_flows(p, near, []) is not None)
    check("разрыв даёт пропуск, а не ноль",
          LD.pair_flows(p, far, []) is None)
    check("обратный порядок времени наблюдением не является",
          LD.pair_flows(near, p, []) is None)


def test_aggressor_side_eats_the_right_book():
    """Покупающий агрессор ест АСКИ, продающий — биды.

    Перепутать стороны значит получить осмысленные на вид числа с
    перевёрнутым знаком — то же, что проверялось на ленте Bybit.
    """
    p = snap(1.0, 99.0, 101.0, [[99.0, 5.0]], [[101.0, 5.0]])
    c = snap(2.0, 99.0, 101.0, [[99.0, 5.0]], [[101.0, 1.0]])
    fl = LD.pair_flows(p, c, [(101.0, 1, 4.0)])
    check("покупка съела аск",
          fl["a"]["eat"] == 404.0 and fl["a"]["cancel"] == 0.0, str(fl))
    wrong = LD.pair_flows(p, c, [(101.0, -1, 4.0)])
    check("та же сделка с другой стороной аск не объясняет",
          wrong["a"]["eat"] == 0.0 and wrong["a"]["cancel"] == 404.0,
          str(wrong))


def test_minute_is_a_gap_when_pairs_are_few():
    """Минута из трёх снимков — пропуск, а не наблюдение.

    Она описывает не ту же величину, и засчитать её значило бы
    разбавить выборку. Порог тонкой минуты — порог ЗАМЕРА.
    """
    acc = LD.minute_accum()
    p = snap(1.0, 99.0, 101.0, [[99.0, 5.0]], [[101.0, 5.0]])
    for i in range(3):
        c = snap(2.0 + i, 99.0, 101.0, [[99.0, 4.0]], [[101.0, 5.0]])
        LD.add_pair(acc, LD.pair_flows(p, c, []))
        p = c
    check("тонкая минута — пропуск", LD.close_minute(acc) is None,
          str(acc["pairs"]))
    for i in range(LD.MIN_PAIRS):
        c = snap(10.0 + i, 99.0, 101.0, [[99.0, 4.0]], [[101.0, 5.0]])
        LD.add_pair(acc, LD.pair_flows(p, c, []))
        p = c
    out = LD.close_minute(acc)
    check("полная минута даёт все объявленные поля",
          out is not None and set(out) == set(LD.FIELDS), str(out))


def test_sweep_is_notional_per_basis_point():
    """`sweep` — съеденный нотионал на базисный пункт хода середины.

    Без хода делить не на что, и величина обязана быть пропуском, а не
    нулём: ноль читался бы как «двигать цену бесплатно».
    """
    acc = LD.minute_accum()
    p = snap(1.0, 100.0, 100.0, [[100.0, 10.0]], [[100.0, 10.0]])
    for i in range(LD.MIN_PAIRS):
        c = snap(2.0 + i, 100.0, 100.0, [[100.0, 10.0]],
                 [[100.0, 10.0]])
        LD.add_pair(acc, LD.pair_flows(p, c, []))
        p = c
    out = LD.close_minute(acc)
    check("без хода середины sweep — пропуск", out["sweep"] != out["sweep"],
          str(out["sweep"]))

    acc = LD.minute_accum()
    p = snap(1.0, 100.0, 100.0, [[100.0, 10.0]], [[100.0, 10.0]])
    for i in range(LD.MIN_PAIRS):
        c = snap(2.0 + i, 101.0, 101.0, [[100.0, 9.0]], [[100.0, 10.0]])
        LD.add_pair(acc, LD.pair_flows(p, c, [(100.0, -1, 1.0)]))
        p = snap(2.0 + i, 100.0, 100.0, [[100.0, 10.0]], [[100.0, 10.0]])
    out = LD.close_minute(acc)
    check("с ходом sweep — число", out["sweep"] == out["sweep"]
          and out["sweep"] > 0, str(out["sweep"]))


def test_fast_merge_equals_the_reference_bit_for_bit():
    """Быстрый путь обязан совпасть с образцовым БИТ В БИТ.

    Ускорение, меняющее числа, есть другая мера — правило, которым
    закреплены и лёгкий разбор Z2, и пачки матрицы запретов в D1.
    Проверяется на случайных лесенках с дырами, нулями и сделками, на
    обеих сторонах книги.
    """
    import random
    rng = random.Random(7)
    bad = 0
    for _ in range(400):
        n = rng.randint(1, 30)
        base = round(rng.uniform(0.5, 200.0), 2)
        tick = round(base * 1e-4, 6) or 1e-6
        desc = rng.random() < 0.5
        prices = [round(base + tick * k, 6) for k in range(n)]
        if desc:
            prices.reverse()
        prev, cur, traded = [], [], {}
        for p in prices:
            if rng.random() < 0.85:
                prev.append([p, round(rng.uniform(0, 5), 3)])
            if rng.random() < 0.85:
                cur.append([p, round(rng.choice((0.0, rng.uniform(0, 5))),
                                     3)])
            if rng.random() < 0.3:
                traded[p] = round(rng.uniform(0, 3), 3)
        f = LD.side_flows(prev, cur, traded)
        g = LD.side_flows_slow(prev, cur, traded)
        if f != g:
            bad += 1
            if bad == 1:
                print(f"     расхождение: {f} против {g}")
    check("быстрый путь совпал с образцовым на 400 лесенках", bad == 0,
          f"расхождений {bad}")


def test_unsorted_ladder_falls_back_instead_of_zeroing():
    """Перемешанная лесенка считается ОБРАЗЦОВЫМ путём, а не обнуляется.

    Слияние на неотсортированном списке не сломалось бы — оно просто не
    нашло бы пересечения, и мера обнулилась бы молча. Это худший исход
    из возможных: ноль читался бы как «уровни ушли за край».
    """
    prev = [[100.0, 5.0], [99.0, 4.0], [98.0, 3.0], [97.0, 2.0]]
    cur = [[100.0, 1.0], [99.0, 4.0], [98.0, 3.0], [97.0, 2.0]]
    good = LD.side_flows(prev, cur, {})
    mixed_prev = [prev[2], prev[0], prev[3], prev[1]]
    mixed_cur = [cur[1], cur[3], cur[0], cur[2]]
    got = LD.side_flows(mixed_prev, mixed_cur, {})
    ref = LD.side_flows_slow(mixed_prev, mixed_cur, {})
    check("перемешанная лесенка не дала молчаливого нуля",
          got["vis"] > 0, str(got))
    check("перемешанная посчитана образцовым путём", got == ref,
          f"{got} против {ref}")
    check("и совпала с той же лесенкой в порядке", got == good,
          f"{got} против {good}")


def main():
    tests = (
        test_price_leaving_the_visible_ladder_is_not_a_cancel,
        test_decrease_explained_by_a_trade_is_not_a_cancel,
        test_level_death_without_a_print,
        test_refill_is_counted_where_a_trade_happened,
        test_gap_gives_no_observation,
        test_aggressor_side_eats_the_right_book,
        test_minute_is_a_gap_when_pairs_are_few,
        test_sweep_is_notional_per_basis_point,
        test_fast_merge_equals_the_reference_bit_for_bit,
        test_unsorted_ladder_falls_back_instead_of_zeroing,
    )
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
