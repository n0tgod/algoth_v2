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


def test_sigma_rungs_descend():
    px, d_max = L.sigma_rungs(100.0, sigma_frac=0.05, n_rungs=3,
                              spacing_sig=2.0)
    # шаг 2·0.05 = 0.10 → рунги 100, 90, 80
    assert px == [100.0, 90.0, 80.0], px
    assert abs(d_max - 0.20) < 1e-9, d_max
    print(f"ok  σ-сетка вниз: {px}, глубина {d_max:.2f}")


def test_ladder_beats_hold_on_recovery():
    # 20%-лестница, плечо 2 (глубоко внутри забора). Цена ныряет на 80,
    # заполняя все рунги, и возвращается на 100. Лестница купила дно —
    # средняя 89.26, итог +24.1 % капитала; удержание вошло всё на 100 и
    # к возврату даёт ровно ноль.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 90.0, 80.0, 90.0, 100.0]
    lows = [100.0, 89.0, 79.0, 90.0, 100.0]
    lad = L.simulate_ladder(closes, lows, rungs, w, capital=1.0,
                            leverage=2.0, mmr=MMR)
    hold = L.simulate_hold(closes, lows, 100.0, capital=1.0,
                           leverage=2.0, mmr=MMR)
    assert not lad["liquidated"] and not hold["liquidated"]
    assert lad["depth"] == 3, lad["depth"]
    assert abs(lad["avg"] - 89.26) < 0.1, lad["avg"]
    assert abs(lad["pnl_frac"] - 0.241) < 0.01, lad["pnl_frac"]
    assert abs(hold["pnl_frac"]) < 1e-9, hold["pnl_frac"]
    assert lad["pnl_frac"] > hold["pnl_frac"]
    print(f"ok  лестница бьёт удержание на возврате: "
          f"+{lad['pnl_frac']*100:.1f}% против {hold['pnl_frac']*100:.1f}%")


def test_ladder_partial_fill():
    # Цена ныряет на 90, но не на 80 — заполнены база и первый рунг.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 92.0, 95.0, 100.0]
    lows = [100.0, 89.0, 95.0, 100.0]
    lad = L.simulate_ladder(closes, lows, rungs, w, capital=1.0,
                            leverage=3.0, mmr=MMR)
    assert lad["depth"] == 2, lad["depth"]
    assert abs(lad["filled_notional"] - 2.0) < 1e-9, lad["filled_notional"]
    print(f"ok  частичная загрузка: глубина {lad['depth']}, "
          f"нотионал {lad['filled_notional']:.2f}")


def test_liquidation_on_gap():
    # Удержание с плечом 10 (ликвидация ≈ −9.6 %): нырок на 85 пробивает
    # забор и теряет капитал позиции целиком.
    closes = [100.0, 88.0, 95.0]
    lows = [100.0, 85.0, 95.0]
    hold = L.simulate_hold(closes, lows, 100.0, capital=1.0,
                           leverage=10.0, mmr=MMR)
    assert hold["liquidated"] and hold["pnl_frac"] == -1.0, hold
    # тот же путь без разрыва к ликвидации — цел
    ok = L.simulate_hold([100.0, 95.0, 100.0], [100.0, 92.0, 100.0],
                         100.0, capital=1.0, leverage=10.0, mmr=MMR)
    assert not ok["liquidated"], ok
    print("ok  разрыв сквозь забор ликвидирует, мелкий нырок — нет")


# --- D2: стратегия на барах -----------------------------------------------

def _bars(closes, lows, highs=None, entry=None):
    """Собрать OHLC-бары из closes/lows для тестов D2; open первого = entry."""
    highs = highs or list(closes)
    bars = []
    for i, (cl, lo, hi) in enumerate(zip(closes, lows, highs)):
        op = entry if (i == 0 and entry is not None) else cl
        bars.append((i, op, hi, lo, cl, 0.0))
    return bars


def test_dca_matches_ladder_bit_for_bit():
    # Без тейка и пола, вход == база: simulate_dca обязан воспроизвести
    # simulate_ladder ДОСЛОВНО — общий _fill_rungs, одна копия долива.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 90.0, 80.0, 90.0, 100.0]
    lows = [100.0, 89.0, 79.0, 90.0, 100.0]
    lad = L.simulate_ladder(closes, lows, rungs, w, capital=1.0,
                            leverage=2.0, mmr=MMR)
    dca = L.simulate_dca(_bars(closes, lows, entry=100.0), rungs, w,
                         capital=1.0, leverage=2.0, mmr=MMR)
    assert dca["exit"] == "срок", dca["exit"]
    assert abs(dca["pnl_frac"] - lad["pnl_frac"]) < 1e-12, (dca, lad)
    assert dca["depth"] == lad["depth"]
    assert abs(dca["avg"] - lad["avg"]) < 1e-12
    print(f"ok  simulate_dca == simulate_ladder бит-в-бит: "
          f"+{dca['pnl_frac']*100:.1f}%")


def test_dca_take_on_recovery():
    # Цена ныряет на 80 (все рунги), возвращается с перелётом — верх бара
    # доходит до 106, тейк на 104 (ВЫШЕ входа, это mfe модели) исполняется
    # по уровню. Средняя 89.26, итог qty·(104−ср). Тейк лонга обязан быть
    # выше входа, иначе он сработал бы в первом же баре у самого входа.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 80.0, 106.0]
    lows = [100.0, 79.0, 90.0]
    highs = [100.0, 80.0, 106.0]        # третий бар доходит верхом до 106
    dca = L.simulate_dca(_bars(closes, lows, highs, entry=100.0), rungs, w,
                         capital=1.0, leverage=2.0, mmr=MMR, take_px=104.0)
    assert dca["exit"] == "тейк", dca["exit"]
    assert dca["depth"] == 3, dca["depth"]
    exp = 0.022407 * (104.0 - 89.26)        # qty·(тейк − средняя)
    assert abs(dca["pnl_frac"] - exp) < 0.005, (dca["pnl_frac"], exp)
    print(f"ok  DCA тейк по уровню на возврате: +{dca['pnl_frac']*100:.1f}%")


def test_dca_capit_floor_in_the_red():
    # Все рунги заполнены (ныряет на 80), затем низ подходит к ликвидации
    # (≈44.85 при плече 2): пол капитуляции режет по ЗАКРЫТИЮ в минус, но
    # НЕ −100 % (это не ликвидация).
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 80.0, 55.0]
    lows = [100.0, 79.0, 48.0]          # 48 < пол(≈50.4), > ликв(44.85)
    dca = L.simulate_dca(_bars(closes, lows, entry=100.0), rungs, w,
                         capital=1.0, leverage=2.0, mmr=MMR,
                         take_px=200.0, floor_frac=0.10)
    assert dca["exit"] == "пол", dca["exit"]
    assert -1.0 < dca["pnl_frac"] < 0.0, dca["pnl_frac"]
    print(f"ok  пол капитуляции режет в минус, не −100 %: "
          f"{dca['pnl_frac']*100:.1f}%")


def test_dca_liquidation_gap():
    # Разрыв сквозь цену ликвидации — −100 %, раньше пола.
    rungs = [100.0, 90.0, 80.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 80.0, 40.0]
    lows = [100.0, 79.0, 40.0]          # 40 < ликв 44.85
    dca = L.simulate_dca(_bars(closes, lows, entry=100.0), rungs, w,
                         capital=1.0, leverage=2.0, mmr=MMR,
                         take_px=200.0, floor_frac=0.10)
    assert dca["exit"] == "ликвидация" and dca["pnl_frac"] == -1.0, dca
    print("ok  разрыв сквозь ликвидацию → −100 %")


def test_single_stop_and_take():
    # Контроль: одиночный вход, стоп ниже входа и тейк выше.
    stop = L.simulate_single(_bars([100.0, 88.0], [100.0, 89.0], entry=100.0),
                             capital=1.0, leverage=2.0, mmr=MMR,
                             take_px=110.0, stop_px=90.0)
    assert stop["exit"] == "стоп", stop
    assert abs(stop["pnl_frac"] - 0.02 * (90.0 - 100.0)) < 1e-9, stop
    take = L.simulate_single(_bars([100.0, 112.0], [100.0, 100.0],
                                   [100.0, 112.0], entry=100.0),
                             capital=1.0, leverage=2.0, mmr=MMR,
                             take_px=110.0, stop_px=90.0)
    assert take["exit"] == "тейк", take
    assert abs(take["pnl_frac"] - 0.02 * (110.0 - 100.0)) < 1e-9, take
    print("ok  контроль: одиночный вход стоп/тейк по уровням")


# --- отрицательные контроли -----------------------------------------------

def _control_dca_no_floor():
    """Пол игнорируется — сделка идёт до ликвидации/срока, не 'пол'."""
    orig = L.simulate_dca

    def no_floor(bars, rung_prices, weights, capital, leverage, mmr,
                 take_px=None, floor_frac=None):
        return orig(bars, rung_prices, weights, capital, leverage, mmr,
                    take_px=take_px, floor_frac=None)
    L.simulate_dca = no_floor
    try:
        try:
            test_dca_capit_floor_in_the_red()
        except AssertionError:
            return True
        return False
    finally:
        L.simulate_dca = orig


def _control_dca_take_ignored():
    """Тейк игнорируется — возврат не закрывается по уровню, не 'тейк'."""
    orig = L.simulate_dca

    def no_take(bars, rung_prices, weights, capital, leverage, mmr,
                take_px=None, floor_frac=None):
        return orig(bars, rung_prices, weights, capital, leverage, mmr,
                    take_px=None, floor_frac=floor_frac)
    L.simulate_dca = no_take
    try:
        try:
            test_dca_take_on_recovery()
        except AssertionError:
            return True
        return False
    finally:
        L.simulate_dca = orig


# --- отрицательные контроли -----------------------------------------------

def _control_no_liquidation_check():
    """Убрать проверку ликвидации в simulate_hold — разрыв обязан
    перестать ловиться, тест разрыва падает."""
    orig = L.simulate_hold

    def no_liq(closes, lows, base_px, capital, leverage, mmr):
        notional = capital * leverage
        qty = notional / base_px
        final = closes[-1]
        return {"liquidated": False,
                "pnl_frac": qty * (final - base_px) / capital}
    L.simulate_hold = no_liq
    try:
        try:
            test_liquidation_on_gap()
        except AssertionError:
            return True
        return False
    finally:
        L.simulate_hold = orig


def _control_rungs_never_fill():
    """Если рунги ниже базы не заполняются, лестница вырождается в базу
    и на возврате не бьёт удержание — тест возврата падает."""
    orig = L.simulate_ladder

    def base_only(closes, lows, rung_prices, weights, capital, leverage, mmr):
        base = rung_prices[0]
        notional = capital * leverage
        cash = weights[0] * notional
        qty = cash / base
        avg = cash / qty
        final = closes[-1]
        return {"liquidated": False, "pnl_frac": qty * (final - avg) / capital,
                "depth": 1, "avg": avg, "filled_notional": cash}
    L.simulate_ladder = base_only
    try:
        try:
            test_ladder_beats_hold_on_recovery()
        except AssertionError:
            return True
        return False
    finally:
        L.simulate_ladder = orig


TESTS = [
    test_liq_price_matches_spec5_table,
    test_one_x_long_cannot_liquidate,
    test_mmr_tier_lookup,
    test_fully_loaded_avg_and_notional,
    test_max_leverage_derived_from_fence,
    test_max_leverage_refuses_impossible_depth,
    test_sigma_rungs_descend,
    test_ladder_beats_hold_on_recovery,
    test_ladder_partial_fill,
    test_liquidation_on_gap,
    test_dca_matches_ladder_bit_for_bit,
    test_dca_take_on_recovery,
    test_dca_capit_floor_in_the_red,
    test_dca_liquidation_gap,
    test_single_stop_and_take,
]


def main():
    for t in TESTS:
        t()
    assert _control_no_mmr_term(), "контроль (1−mmr) не кусается"
    assert _control_leverage_unbounded(), "контроль плеча не кусается"
    assert _control_no_liquidation_check(), "контроль ликвидации не кусается"
    assert _control_rungs_never_fill(), "контроль заполнения рунгов не кусается"
    assert _control_dca_no_floor(), "контроль пола капитуляции не кусается"
    assert _control_dca_take_ignored(), "контроль тейка не кусается"
    print(f"\nвсе {len(TESTS)} проверки прошли; 6 отрицательных контролей "
          f"кусаются")


if __name__ == "__main__":
    main()
