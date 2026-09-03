#!/usr/bin/env python3
"""Тесты ядра забора — цена ликвидации закреплена таблицей §5 спеки 01."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ladder as L  # noqa: E402

MMR = 0.005          # базовый тир мажоров; на нём таблица §5 и считалась


def _single_liq_frac(leverage, mmr=MMR, base=100.0):
    """Ликвидация одиночной (без лестницы) длинной позиции, долей от входа."""
    capital = 1.0
    notional = capital * leverage
    qty = notional / base
    p_liq = L.liq_price(base, qty, capital, mmr)
    return L.liq_frac(base, p_liq)


def test_liq_price_matches_spec5_table():
    # §5 спеки 01: «Ликвидация примерно при» — 3× −33 %, 10× −9.6 %,
    # 25× −3.6 %, 50× −1.6 %. Чистые случаи (3×, 10×) совпадают почти
    # точно; крупные плечи спека округляла — допуск 0.3 п.п.
    got = {L_: _single_liq_frac(L_) for L_ in (3, 10, 25, 50)}
    assert abs(got[3] - 0.33) < 0.003, got[3]
    assert abs(got[10] - 0.096) < 0.003, got[10]
    assert abs(got[25] - 0.036) < 0.003, got[25]
    assert abs(got[50] - 0.016) < 0.003, got[50]
    print(f"ok  ликвидация по таблице §5: "
          f"3×={got[3]*100:.1f}% 10×={got[10]*100:.1f}% "
          f"25×={got[25]*100:.1f}% 50×={got[50]*100:.1f}%")


def test_one_x_long_cannot_liquidate():
    # Плечо 1×: capital = нотионал, числитель нулевой, ликвидация в нуле.
    assert L.liq_price(100.0, 1.0, 100.0, MMR) == 0.0
    assert _single_liq_frac(1.0) == 1.0     # «на 100 % ниже» = цена 0
    print("ok  лонг 1× не ликвидируется (цена ликвидации 0)")


def test_mmr_tier_lookup():
    tiers = [{"cap": 100000, "mmr": 0.005, "max_leverage": 50},
             {"cap": 500000, "mmr": 0.01, "max_leverage": 25},
             {"cap": 1000000, "mmr": 0.025, "max_leverage": 10}]
    assert L.mmr_for_notional(tiers, 50000) == 0.005     # базовый
    assert L.mmr_for_notional(tiers, 100000) == 0.005    # ровно граница
    assert L.mmr_for_notional(tiers, 250000) == 0.01     # средний тир
    assert L.mmr_for_notional(tiers, 9e9) == 0.025       # за верхом — верхний
    # снятый контракт: тиров нет — плоский по правилу
    assert L.mmr_for_notional([], 50000, flat=0.02) == 0.02
    # ни тиров, ни плоского — ошибка, не молчаливый ноль
    try:
        L.mmr_for_notional([], 50000)
        assert False, "должно было бросить"
    except ValueError:
        pass
    print("ok  тир MMR по нотионалу; снятый — плоский; нечем — ошибка")


def test_fully_loaded_avg_and_notional():
    # Нотионал полностью набранной лестницы = capital·leverage ТОЧНО,
    # средняя цена — между рунгами.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    qty, p_avg, notional = L.fully_loaded(rungs, w, capital=1.0, leverage=3.0)
    assert abs(notional - 3.0) < 1e-12, notional
    assert 80.0 < p_avg < 100.0, p_avg
    assert abs(p_avg - 3.0 / qty) < 1e-9        # p_avg = деньги/количество
    print(f"ok  полная лестница: нотионал=capital·плечо, ср.цена={p_avg:.2f}")


def test_max_leverage_derived_from_fence():
    # Лестница 20 % глубиной, множитель выживания 2 → плечо ~3× (сходится
    # с потолком «≤ 3×» §5). Множитель 3 → плечо ~1.8×. Монотонно.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    look = lambda n: MMR                        # noqa: E731
    lev2 = L.max_leverage(rungs, w, capital=1.0, base_px=100.0, d_max=0.20,
                          mmr_lookup=look, survive_mult=2.0)
    lev3 = L.max_leverage(rungs, w, capital=1.0, base_px=100.0, d_max=0.20,
                          mmr_lookup=look, survive_mult=3.0)
    assert abs(lev2 - 3.02) < 0.05, lev2
    assert abs(lev3 - 1.81) < 0.05, lev3
    assert lev3 < lev2, "больше запаса — меньше плеча"
    # глубже лестница при том же множителе — меньше плеча
    deep = L.max_leverage([100.0, 80.0, 60.0], w, capital=1.0, base_px=100.0,
                          d_max=0.40, mmr_lookup=look, survive_mult=2.0)
    assert deep < lev2, (deep, lev2)
    print(f"ok  плечо выведено: 20%×2={lev2:.2f}, ×3={lev3:.2f}, "
          f"40%×2={deep:.2f}")


def test_max_leverage_refuses_impossible_depth():
    # Если даже 1× нарушает забор — 0.0 (глубину обрезать). Множитель 6 на
    # 20 % лестнице требует ликвидацию на 120 % ниже базы — недостижимо.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    lev = L.max_leverage(rungs, w, capital=1.0, base_px=100.0, d_max=0.20,
                         mmr_lookup=lambda n: MMR, survive_mult=6.0)
    assert lev == 0.0, lev
    print("ok  недопустимая глубина забора → плечо 0")


# --- отрицательные контроли -----------------------------------------------

def _control_no_mmr_term():
    """Убрать (1−mmr) из знаменателя — таблица §5 обязана разойтись."""
    orig = L.liq_price
    L.liq_price = lambda p_avg, qty, cap, mmr: max(
        0.0, (qty * p_avg - cap) / qty)          # без (1−mmr)
    try:
        try:
            test_liq_price_matches_spec5_table()
        except AssertionError:
            return True
        return False
    finally:
        L.liq_price = orig


def _control_leverage_unbounded():
    """Плечо, не считающее забор (всегда потолок) — тест вывода обязан
    упасть (не будет ни 3.02, ни монотонности)."""
    orig = L.max_leverage
    L.max_leverage = lambda *a, **k: 25.0
    try:
        try:
            test_max_leverage_derived_from_fence()
        except AssertionError:
            return True
        return False
    finally:
        L.max_leverage = orig


TESTS = [
    test_liq_price_matches_spec5_table,
    test_one_x_long_cannot_liquidate,
    test_mmr_tier_lookup,
    test_fully_loaded_avg_and_notional,
    test_max_leverage_derived_from_fence,
    test_max_leverage_refuses_impossible_depth,
]


def main():
    for t in TESTS:
        t()
    assert _control_no_mmr_term(), "контроль (1−mmr) не кусается"
    assert _control_leverage_unbounded(), "контроль плеча не кусается"
    print(f"\nвсе {len(TESTS)} проверки прошли; 2 отрицательных контроля "
          f"кусаются")


if __name__ == "__main__":
    main()
