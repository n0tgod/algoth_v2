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


def test_venue_leverage_cap_binds():
    """Предел плеча ТИРА площадки связывает раньше неравенства безопасности.

    Узкая лестница (10 % глубиной) при дорогом тире (`mmr` 0.1) проходит
    забор до ~10×, но площадка у такого символа даёт 5×. Плечо, которого
    биржа не даёт, консервативной оценкой не является — позиция просто не
    открывается, и её исход описывал бы сделку, которой не было.
    """
    rungs = [100.0, 95.0, 90.0]
    w = [1 / 3] * 3
    look = lambda n: 0.1                        # noqa: E731  дорогой тир
    free = L.max_leverage(rungs, w, 1.0, 100.0, 0.10, look, 0.5)
    capped = L.max_leverage(rungs, w, 1.0, 100.0, 0.10, look, 0.5,
                            lev_lookup=lambda n: 5.0)
    assert free > 5.0 + 1e-6, free      # без предела забор пускает больше
    assert abs(capped - 5.0) < 1e-6, capped
    # Предел, которого нет (нет справочника), прежнего счёта не двигает.
    same = L.max_leverage(rungs, w, 1.0, 100.0, 0.10, look, 0.5,
                          lev_lookup=lambda n: None)
    assert abs(same - free) < 1e-12, (same, free)
    # Зеркально у короткой стороны — правило одно, знак разный.
    srun = [100.0, 105.0, 110.0]
    s_free = L.max_leverage(srun, w, 1.0, 100.0, 0.10, look, 0.5,
                            side="short")
    s_cap = L.max_leverage(srun, w, 1.0, 100.0, 0.10, look, 0.5,
                           side="short", lev_lookup=lambda n: 5.0)
    assert s_free > 5.0 + 1e-6 and abs(s_cap - 5.0) < 1e-6, (s_free, s_cap)
    print(f"ok  предел тира связывает: лонг {free:.2f}→{capped:.2f}, "
          f"шорт {s_free:.2f}→{s_cap:.2f}")


def test_fence_refuses_leverage_dead_at_open():
    """Ликвидация обязана стоять ПРОТИВ позиции, иначе она мертва на входе.

    Поддерживающая маржа съедает капитал уже при открытии, когда
    `плечо · mmr ≥ 1`: у лонга цена ликвидации выходит НЕ НИЖЕ средней, у
    шорта не выше. Это не «рискованно» — такой позиции не существует, и
    забор такое плечо не выдаёт ни на одной стороне.

    Замер 2026-09-05 по журналу книг: у коротких решений 71 из 1021 несли
    ровно это, и 47 из 80 их ликвидаций — эти же; у длинных таких нет.
    """
    w = [1 / 3] * 3
    look = lambda n: 0.1                        # noqa: E731  1/mmr = 10×
    for side, rungs, base in (("long", [100.0, 95.0, 90.0], 100.0),
                              ("short", [100.0, 105.0, 110.0], 100.0)):
        # Запас велик намеренно: неравенство безопасности не связывает, и
        # ограничителем остаётся ровно проверка стороны ликвидации.
        lev = L.max_leverage(rungs, w, 1.0, base, 0.10, look, 0.01,
                             side=side)
        assert lev <= 10.0 + 1e-6, (side, lev)
        qty, p_avg, notl = L.fully_loaded(rungs, w, 1.0, lev)
        p = L.liq_price(p_avg, qty, 1.0, look(notl), side)
        if side == "long":
            assert p < p_avg, (side, p, p_avg)
        else:
            assert p > p_avg, (side, p, p_avg)
    print("ok  плечо, мёртвое на входе, забор не выдаёт ни одной стороне")


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


def _patch_ladder_source(lit, repl, test):
    """Подделка ИСХОДНИКА ядра: правило живёт строкой, подменить функцию
    нечем. Копия кладётся в scratchpad и возвращается копированием —
    `git checkout` для этого не инструмент (он однажды снёс всю
    несохранённую работу файла). Кэш байткода удаляется руками: питон
    считает `.pyc` свежим по паре «mtime в целых секундах, размер», и
    подделка успевала исполниться ПРЕЖНИМ кодом, то есть контроль врал в
    обе стороны. Возвращает True, если контроль кусается.
    """
    import importlib
    import shutil
    import tempfile
    path = os.path.join(HERE, "ladder.py")
    src = open(path, encoding="utf-8").read()
    assert lit in src, "подделка НЕ легла: литерала нет"
    keep = os.path.join(tempfile.mkdtemp(prefix="ladder-"), "ladder.py")
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, repl, 1))
        cache = os.path.join(HERE, "__pycache__")
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith("ladder."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(L)
        try:
            test()
        except AssertionError:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(L)


def _control_venue_cap_ignored():
    """Забор, не читающий предел тира — проверка обязана упасть."""
    orig = L.max_leverage

    def loose(*a, **k):
        k.pop("lev_lookup", None)
        return orig(*a, **k)

    L.max_leverage = loose
    try:
        try:
            test_venue_leverage_cap_binds()
        except AssertionError:
            return True
        return False
    finally:
        L.max_leverage = orig


def _control_dead_at_open_allowed():
    """Снять проверку стороны ликвидации — плечо уедет за 1/mmr, и
    позиция окажется ликвидированной в момент открытия."""
    return _patch_ladder_source(
        '        if (p >= p_avg) if side == "long" else (p <= p_avg):\n'
        '            return False\n', "",
        test_fence_refuses_leverage_dead_at_open)


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

def _bars(closes, lows, highs=None, entry=None, vols=None):
    """Собрать OHLC-бары из closes/lows для тестов D2; open первого = entry.

    Объём по умолчанию ПОЛОЖИТЕЛЕН, потому что таковы живые бары ленты:
    они рождаются из принтов, и минуты без сделок среди них не бывает
    вовсе. Прежняя фикстура ставила ноль — то есть не выглядела как
    живые данные, и правило «лимитка требует принта» на ней читалось бы
    как поломка (правило проекта: подставные данные обязаны выглядеть
    живыми). `vols` позволяет собрать бар-КОТИРОВКУ (объём 0) намеренно —
    ровно такие приносит хвост, дописанный серединой стакана.
    """
    highs = highs or list(closes)
    bars = []
    for i, (cl, lo, hi) in enumerate(zip(closes, lows, highs)):
        op = entry if (i == 0 and entry is not None) else cl
        v = 1000.0 if vols is None else float(vols[i])
        bars.append((i, op, hi, lo, cl, v))
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


def test_same_coin_short_no_trigger():
    # Цена не доходит до триггера 95 (просадки нет) — короткого не было → None.
    bars = [(t, 100, 101, 99.0, 100, 0) for t in range(4)]
    assert L.same_coin_short(bars, 95.0, 3, 90.0, 1.0) is None
    print("ok  шорт той же монеты: нет просадки до триггера → None")


def test_same_coin_short_recovers_to_zero():
    # Ныряет к триггеру (низ 94 ≤ 95) на баре входа, СЛЕДУЮЩИЙ бар
    # восстанавливает (верх 97 ≥ 95) — короткий вышел ~в ноль по уровню.
    bars = [
        (0, 100, 100.0, 100.0, 100, 0),
        (1, 96, 96.0, 94.0, 95, 0),      # вход короткого (низ ≤ 95)
        (2, 96, 97.0, 95.5, 96, 0),      # восстановление (верх ≥ 95)
        (3, 98, 99.0, 97.0, 98, 0),
    ]
    r = L.same_coin_short(bars, 95.0, 5, 98.0, 1.0)
    assert r == 0.0, r
    print("ok  шорт: восстановление сквозь триггер → 0 (лонг едет сам)")


def test_same_coin_short_crash_gains():
    # Ныряет к триггеру и продолжает падать без восстановления; лонг вышел
    # по 82 (напр. ликвидация) — короткий держится до выхода, гасит хвост.
    bars = [
        (0, 100, 100.0, 100.0, 100, 0),
        (1, 96, 96.0, 94.0, 95, 0),      # вход короткого
        (2, 90, 90.0, 88.0, 89, 0),      # верх 90 < 95 — держим
        (3, 85, 85.0, 82.0, 83, 0),      # верх 85 < 95 — держим до выхода
    ]
    r = L.same_coin_short(bars, 95.0, 3, 82.0, 1.0)
    exp = 1.0 * (95.0 - 82.0) / 95.0     # (триггер − цена выхода)/триггер
    assert abs(r - exp) < 1e-12, (r, exp)
    assert r > 0, r
    print(f"ok  шорт: крах без восстановления → +{r*100:.1f}% (гасит хвост)")


def test_liq_price_short_is_above():
    # Шорт 1× ликвидируется при росте цены ~вдвое: capital = qty·entry,
    # P_liq = (qty·entry + capital)/(qty·(1+mmr)) = 2·entry/(1+mmr).
    entry, qty, cap = 100.0, 1.0, 100.0            # нотионал = qty·entry = cap
    p = L.liq_price(entry, qty, cap, MMR, side="short")
    assert abs(p - 2 * entry / (1 + MMR)) < 1e-9, p
    assert p > entry                               # ликвидация ВЫШЕ входа
    # тот же вызов лонгом — прежнее (ликвидация в нуле у 1×)
    assert L.liq_price(entry, qty, cap, MMR, side="long") == 0.0
    print(f"ok  ликвидация шорта выше входа: {p:.1f} (лонг 1× — 0)")


def test_single_short_take_stop_liq():
    # Плечо 2, шорт: ликвидация ≈149, тейк НИЖЕ входа, стоп ВЫШЕ.
    tk = L.simulate_single(_bars([100.0, 88.0], [100.0, 89.0], [100.0, 95.0],
                                 entry=100.0),
                           capital=1.0, leverage=2.0, mmr=MMR,
                           take_px=90.0, stop_px=112.0, side="short")
    assert tk["exit"] == "тейк", tk
    assert abs(tk["pnl_frac"] - 0.02 * (100.0 - 90.0)) < 1e-9, tk   # +
    st = L.simulate_single(_bars([100.0, 108.0], [100.0, 100.0], [100.0, 112.0],
                                 entry=100.0),
                           capital=1.0, leverage=2.0, mmr=MMR,
                           take_px=90.0, stop_px=110.0, side="short")
    assert st["exit"] == "стоп", st
    assert abs(st["pnl_frac"] - 0.02 * (100.0 - 110.0)) < 1e-9, st   # −
    lq = L.simulate_single(_bars([100.0, 160.0], [100.0, 130.0], [100.0, 160.0],
                                 entry=100.0),
                           capital=1.0, leverage=2.0, mmr=MMR,
                           take_px=90.0, stop_px=200.0, side="short")
    assert lq["exit"] == "ликвидация" and lq["pnl_frac"] == -1.0, lq
    print("ok  шорт: тейк ниже входа (плюс), стоп выше (минус), ликвид. вверху")


# --- отрицательные контроли -----------------------------------------------

def _control_short_side_ignored():
    """Если сторону игнорировать (считать лонгом), шорт-геометрия ломается —
    тест тейка/стопа/ликвидации шорта обязан упасть."""
    orig = L.simulate_single

    def as_long(bars, capital, leverage, mmr, take_px=None, stop_px=None,
                side="long"):
        return orig(bars, capital, leverage, mmr, take_px=take_px,
                    stop_px=stop_px, side="long")   # игнорируем side
    L.simulate_single = as_long
    try:
        try:
            test_single_short_take_stop_liq()
        except AssertionError:
            return True
        return False
    finally:
        L.simulate_single = orig


# --- отрицательные контроли -----------------------------------------------

def _control_short_recovers_on_entry_bar():
    """Если восстановление проверять НА баре входа (у него верх ≥ триггера
    почти всегда), крах закрылся бы в ноль — тест краха обязан упасть."""
    orig = L.same_coin_short

    def buggy(bars, trigger_px, exit_ts, exit_px, short_notional):
        if trigger_px <= 0:
            return None
        opened = False
        for (bt, _o, hi, lo, _cl, _v) in bars:
            if bt > exit_ts:
                break
            if not opened and lo <= trigger_px:
                opened = True
            if opened and hi >= trigger_px:      # БАГ: и на баре входа
                return 0.0
        if not opened:
            return None
        return short_notional * (trigger_px - exit_px) / trigger_px
    L.same_coin_short = buggy
    try:
        try:
            test_same_coin_short_crash_gains()
        except AssertionError:
            return True
        return False
    finally:
        L.same_coin_short = orig


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



# ------------------------------------------- почасовая отметка позиции (D4)

def _track_bars(t0=1_699_999_200, hours=5):   # ровно на границе часа
    """Бары трёх часов: ровно, затем провал до рунга, затем возврат."""
    bars, px = [], 100.0
    for i in range(hours * 60):
        if i < 60:
            px = 100.0
        elif i < 120:
            px = 100.0 - 6.0 * (i - 60) / 59.0      # к концу 2-го часа 94
        else:
            px = 94.0 + 4.0 * (i - 120) / (hours * 60 - 121)
        bars.append((t0 + i * 60, px, px + 0.05, px - 0.05, px, 100.0))
    return bars


def test_track_does_not_change_numbers():
    """Отметка — наблюдение, а не правило: числа обязаны совпасть бит в бит."""
    bars = _track_bars()
    rungs, w = [100.0, 96.0], [0.5, 0.5]
    a = L.simulate_dca(bars, rungs, w, 1.0, 2.0, 0.01, take_px=140.0)
    b = L.simulate_dca(bars, rungs, w, 1.0, 2.0, 0.01, take_px=140.0,
                       track=True)
    for k in ("exit", "pnl_frac", "depth", "avg", "filled_notional",
              "exit_ts", "exit_px"):
        assert a[k] == b[k], (k, a[k], b[k])
    assert "track" not in a and b["track"], "отметка появилась не там"
    print(f"ok  отметка не меняет счёт: {a['exit']} {a['pnl_frac']:+.4f} "
          f"у обоих, записей {len(b['track'])}")


def test_track_last_equals_outcome():
    """Последняя запись отметки — сам исход сделки, а не переоценка."""
    bars = _track_bars()
    r = L.simulate_dca(bars, [100.0, 96.0], [0.5, 0.5], 1.0, 2.0, 0.01,
                       take_px=140.0, track=True)
    tr = r["track"]
    hrs = [x[0] for x in tr]
    assert hrs == sorted(set(hrs)), hrs               # по записи на час
    assert abs(tr[-1][2] - r["pnl_frac"]) < 1e-12, (tr[-1], r["pnl_frac"])
    assert tr[-1][1] == r["filled_notional"], (tr[-1][1],
                                               r["filled_notional"])
    # занятый нотионал только растёт: доливы добавляют, обратно не отдают
    assert all(x[1] <= y[1] + 1e-12 for x, y in zip(tr, tr[1:])), tr
    print(f"ok  отметка: {len(tr)} часов, нотионал {tr[0][1]:.2f} → "
          f"{tr[-1][1]:.2f}, итог {tr[-1][2]:+.4f}")


def test_track_marks_hour_close():
    """Переоценка часа — по ПОСЛЕДНЕМУ бару часа, а не по первому.

    Первый бар часа — цена, с которой час начался; отметив её, книга видела
    бы свою экспозицию на час устаревшей, и просадка книги считалась бы по
    вчерашним ценам.
    """
    bars = _track_bars()
    r = L.simulate_dca(bars, [100.0], [1.0], 1.0, 1.0, 0.01, track=True)
    tr = r["track"]
    # второй час кончается на 94 → pnl первого часа ≈ 0, второго ≈ −6 %
    assert abs(tr[0][2]) < 1e-9, tr[0]
    assert tr[1][2] < -0.055, tr[1]
    print(f"ok  переоценка по концу часа: час 1 {tr[0][2]:+.4f}, час 2 "
          f"{tr[1][2]:+.4f}")


def _control_track_marks_hour_open():
    """Отметка по ПЕРВОМУ бару часа (запись не перезаписывается) —
    экспозиция и переоценка книги отставали бы на час."""
    orig = L.simulate_dca

    def first_bar(bars, rung_prices, weights, capital, leverage, mmr,
                  take_px=None, floor_frac=None, track=False):
        r = orig(bars, rung_prices, weights, capital, leverage, mmr,
                 take_px=take_px, floor_frac=floor_frac, track=track)
        if track and r.get("track"):
            seen, out = set(), []
            for (hr, cash, pnl) in r["track"]:
                if hr in seen:
                    continue
                seen.add(hr)
                out.append((hr, cash, 0.0))       # «цена начала часа»
            r["track"] = out
        return r
    L.simulate_dca = first_bar
    try:
        try:
            test_track_marks_hour_close()
        except AssertionError:
            return True
        return False
    finally:
        L.simulate_dca = orig


def test_fills_describe_the_position_and_its_floating_entry():
    """Входы позиции записаны, и средняя из них равна средней симуляции.

    Позиция на показе одна, а входов у неё несколько: база плюс доливы.
    Средняя цена входа («плавающая ТВХ») обязана выводиться ИЗ ЭТОГО
    списка — вторая её реализация на странице однажды разошлась бы с той,
    по которой считаются деньги. Проверяется тождеством: средняя,
    собранная из записанных входов, совпадает с `avg` симуляции.
    """
    # цена уходит вниз, задевает два рунга, потом стоит
    bars = [(0, 100.0, 100.0, 100.0, 100.0, 1),
            (60, 100.0, 100.0, 94.0, 95.0, 1),
            (120, 95.0, 95.0, 89.0, 90.0, 1),
            (180, 90.0, 90.0, 90.0, 90.0, 1)]
    rungs = [100.0, 95.0, 90.0, 85.0]
    w = [0.25, 0.25, 0.25, 0.25]
    r = L.simulate_dca(bars, rungs, w, 1.0, 2.0, 0.02)
    fills = r["fills"]
    assert [round(f[1], 2) for f in fills] == [100.0, 95.0, 90.0], fills
    assert fills[0][0] == 0 and fills[1][0] == 60 and fills[2][0] == 120, fills
    # Средняя из записанных входов = средняя симуляции (тождество), и
    # считает её ТА ЖЕ функция, которой пользуются страница и график:
    # `rules.avg_walk`. Своя арифметика в проверке означала бы, что
    # тождество держится с формулой ТЕСТА, а не с той, что на экране, —
    # первая версия этой функции считала среднее цен и расходилась.
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dca_paper"))
    import rules as PR
    walk = PR.avg_walk(fills)
    assert len(walk) == len(fills), walk
    assert abs(walk[-1]["avg"] - r["avg"]) < 1e-9, (walk[-1], r["avg"])
    # ТВХ ПЛЫВЁТ: каждый долив ниже опускает её, и первый шаг равен
    # цене входа
    assert abs(walk[0]["avg"] - 100.0) < 1e-9, walk[0]
    assert walk[0]["avg"] > walk[1]["avg"] > walk[2]["avg"], walk
    assert abs(r["entry_px"] - 100.0) < 1e-9
    print(f"ok  входы позиции: {[round(f[1], 1) for f in fills]}, "
          f"ТВХ {[round(x['avg'], 2) for x in walk]} совпала с симуляцией")


def _control_fills_not_logged():
    """Доливы не записываются: позиция не разворачивается во входы."""
    orig = L._fill_rungs
    L._fill_rungs = lambda *a, **k: orig(*a[:7])
    try:
        try:
            test_fills_describe_the_position_and_its_floating_entry()
        except AssertionError:
            return True
        return False
    finally:
        L._fill_rungs = orig


def test_open_mark_equals_the_simulation_pnl():
    """Живая отметка открытой позиции — та же величина, что pnl симуляции.

    Отметку считают ДВА места: часовой прогон книги (по закрытию бара) и
    страница (по живой середине, каждые десять секунд). Формул при этом
    обязана быть одна: разойдись они, владелец видел бы одно число, а
    книга держала бы другое. Проверяется тождеством, а не сравнением с
    арифметикой теста.
    """
    bars = [(0, 100.0, 100.0, 100.0, 100.0, 1),
            (60, 100.0, 100.0, 94.0, 95.0, 1),
            (120, 95.0, 95.0, 89.0, 90.0, 1),
            (180, 90.0, 92.0, 90.0, 91.5, 1)]
    rungs = [100.0, 95.0, 90.0, 85.0]
    w = [0.25, 0.25, 0.25, 0.25]
    cap, lev = 26.65, 2.0
    r = L.simulate_dca(bars, rungs, w, cap, lev, 0.02)
    # Симуляция дошла до конца пути: её pnl и есть отметка на цене
    # последнего закрытия — на ней тождество и проверяется.
    px = bars[-1][4]
    got = L.open_mark(px, r["avg"], cap, lev,
                      [f[2] for f in r["fills"]])
    assert got is not None
    assert abs(got - r["pnl_frac"]) < 1e-12, (got, r["pnl_frac"])
    # Цена ушла вверх — отметка растёт; вниз — падает (знак, а не модуль)
    up = L.open_mark(px * 1.01, r["avg"], cap, lev,
                     [f[2] for f in r["fills"]])
    dn = L.open_mark(px * 0.99, r["avg"], cap, lev,
                     [f[2] for f in r["fills"]])
    assert up > got > dn, (up, got, dn)
    # Меры нет — None, а не ноль: ноль объявил бы позицию ровной
    assert L.open_mark(px, 0.0, cap, lev, [0.25]) is None
    assert L.open_mark(px, r["avg"], 0.0, lev, [0.25]) is None
    print(f"ok  живая отметка = pnl симуляции ({got:+.6f}), "
          f"и меры нет — прочерк, а не ноль")


def _control_open_mark_forgets_leverage():
    """Отметка считается без плеча: страница показала бы не те деньги."""
    orig = L.open_mark
    L.open_mark = lambda px, avg, cap, lev, wf: orig(px, avg, cap, 1.0, wf)
    try:
        try:
            test_open_mark_equals_the_simulation_pnl()
        except AssertionError:
            return True
        return False
    finally:
        L.open_mark = orig


def test_limit_needs_a_print_market_exit_does_not():
    """Лимитка на баре БЕЗ принтов не заполняется, рыночный выход — да.

    Хвост, дописанный серединой стакана (`dca_paper/tail.py`), приносит
    бары с нулевым объёмом: цену КОТИРОВАЛИ, но по ней никто не торговал.
    Засчитать себе заполнение рунга или тейка значило бы вернуть ошибку
    движка v1 («касание есть заполнение»). Пол капитуляции, ликвидация и
    срок — наши собственные (и биржи) рыночные выходы против котировки, и
    на такой минуте они считаются.

    Бары ленты объём несут всегда, поэтому на прежних данных правило не
    меняет ни одного числа: этим и служит остальная сюита, где все бары
    положительны и результаты не изменились.
    """
    rungs = [100.0, 90.0]
    w = [0.5, 0.5]
    # цена ныряет к рунгу и возвращается выше тейка — но обе минуты без
    # единого принта
    closes = [100.0, 90.0, 106.0]
    lows = [100.0, 89.0, 100.0]
    highs = [100.0, 100.0, 106.0]
    quote = _bars(closes, lows, highs, entry=100.0, vols=[1000.0, 0.0, 0.0])
    q = L.simulate_dca(quote, rungs, w, capital=1.0, leverage=2.0, mmr=MMR,
                       take_px=105.0)
    assert q["exit"] == "срок", q
    assert q["depth"] == 1, q            # рунг на котировке не заполнен
    # те же бары с принтами: и рунг, и тейк исполняются
    traded = _bars(closes, lows, highs, entry=100.0)
    t = L.simulate_dca(traded, rungs, w, capital=1.0, leverage=2.0, mmr=MMR,
                       take_px=105.0)
    assert t["exit"] == "тейк" and t["depth"] == 2, t
    # рыночный выход на котировке считается: разрыв вниз сквозь забор
    deep = _bars([100.0, 40.0], [100.0, 40.0], entry=100.0,
                 vols=[1000.0, 0.0])
    d = L.simulate_dca(deep, [100.0], [1.0], capital=1.0, leverage=10.0,
                       mmr=MMR)
    assert d["exit"] == "ликвидация" and d["pnl_frac"] == -1.0, d
    print(f"ok  лимитка требует принта: котировка → {q['exit']} "
          f"(глубина {q['depth']}), принты → {t['exit']} "
          f"(глубина {t['depth']}); ликвидация на котировке считается")


def _control_limit_fills_without_a_print():
    """Правило снято: лимитка заполняется и на минуте без единой сделки."""
    return _patch_ladder_source("traded = float(vol) > 0", "traded = True",
                                test_limit_needs_a_print_market_exit_does_not)


# --- динамический тейк: якорь по ТВХ и трейлинг (D8) -------------------

TAKE_RUNGS = [100.0, 90.0]
TAKE_W = [0.5, 0.5]


def _dca_take(bars, rule=None, take_px=None, rungs=None, w=None, lev=2.0):
    return L.simulate_dca(bars, rungs or TAKE_RUNGS, w or TAKE_W,
                          capital=1.0, leverage=lev, mmr=MMR,
                          take_px=take_px, take_rule=rule)


def test_entry_anchored_rule_equals_take_px():
    """Якорь `entry` обязан совпасть со старым `take_px` БИТ В БИТ.

    Иначе у одного правила две реализации: неподвижная цена и якорь,
    который её изображает, — и однажды они разойдутся молча.
    """
    bars = _bars([100.0, 95.0, 106.0], [100.0, 89.0, 100.0],
                 [100.0, 100.0, 106.0], entry=100.0)
    a = _dca_take(bars, take_px=105.0)
    b = _dca_take(bars, rule={"anchor": "entry", "frac": 0.05})
    same = all(a[k] == b[k] for k in
               ("exit", "pnl_frac", "exit_ts", "exit_px", "depth", "avg"))
    assert same, (a, b)
    assert a["exit"] == "тейк", a
    print(f"ok  якорь entry == take_px бит в бит: {a['exit']} "
          f"{a['pnl_frac']*100:+.2f}% по {a['exit_px']:.2f}")


def test_avg_anchor_follows_the_ladder_and_pays_filled_leverage():
    """Тейк от ТВХ едет вниз вместе со средней, и его pnl — тождество.

    `pnl = qty·(ТВХ·(1+f) − ТВХ)/capital = заполненный нотионал · f`.
    То есть тейк по ТВХ платит РОВНО «заполненное плечо × доля», и это
    главное его свойство: он не зависит от того, где стоял вход.
    """
    bars = _bars([100.0, 95.0, 100.0], [100.0, 89.0, 95.0],
                 [100.0, 100.0, 100.0], entry=100.0)
    e = _dca_take(bars, rule={"anchor": "entry", "frac": 0.05})
    a = _dca_take(bars, rule={"anchor": "avg", "frac": 0.05})
    assert e["exit"] == "срок", e          # 105 недостижимы
    assert a["exit"] == "тейк", a          # уровень уехал к 99.47
    assert a["exit_px"] < 100.0, a
    want = a["filled_notional"] / 1.0 * 0.05
    assert abs(a["pnl_frac"] - want) < 1e-12, (a["pnl_frac"], want)
    print(f"ok  тейк от ТВХ: уровень {a['exit_px']:.2f} при входе 100, "
          f"pnl {a['pnl_frac']*100:+.2f}% = нотионал {a['filled_notional']:.2f} × 5%; "
          f"якорь входа при том же пути даёт {e['exit']}")


def test_take_level_uses_the_average_at_the_bar_start():
    """Долив ЭТОЙ минуты уровень опускает, но заявку переставит следующая.

    Иначе тейк, ставший достижимым только из-за долива в этом же баре,
    засчитался бы нам внутрибарным путём, которого мы не видим.
    """
    bars = _bars([100.0, 95.0, 99.6], [100.0, 89.0, 95.0],
                 [100.0, 99.6, 99.6], entry=100.0)
    a = _dca_take(bars, rule={"anchor": "avg", "frac": 0.05})
    assert a["exit"] == "тейк", a
    assert a["exit_ts"] == 2, a            # не 1 — бар долива тейка не даёт
    print(f"ok  уровень по ТВХ на начало бара: долив в баре 1, "
          f"тейк в баре {int(a['exit_ts'])}")


def test_trailing_arms_then_exits_below_the_peak():
    """Трейл: взвод не закрывает, выход не получает цену уровня.

    Взвод и выход в одном баре невозможны (выход проверяется раньше),
    а исполнение — рыночное: `min(закрытие, уровень трейла)`.
    """
    bars = _bars([100.0, 105.0, 108.0, 107.5],
                 [100.0, 100.0, 104.0, 107.0],
                 [100.0, 106.0, 110.0, 110.0], entry=100.0)
    rr = {"anchor": "avg", "frac": 0.05, "trail": 0.02}
    t = _dca_take(bars, rule=rr, rungs=[100.0], w=[1.0], lev=1.0)
    p = _dca_take(bars, rule={"anchor": "avg", "frac": 0.05},
                  rungs=[100.0], w=[1.0], lev=1.0)
    assert p["exit"] == "тейк" and p["exit_ts"] == 1, p     # взвод = выход
    assert t["exit"] == "трейл" and t["exit_ts"] == 3, t    # взвод ≠ выход
    assert abs(t["exit_px"] - 107.5) < 1e-9, t              # закрытие, не 107.8
    assert t["pnl_frac"] > p["pnl_frac"], (t, p)
    # Максимум растёт только на барах СО СДЕЛКАМИ: у минуты-котировки
    # (хвост, дописанный серединой стакана) верх — рисованный, и подняв
    # по нему трейл, мы вышли бы по цене, которой никто не торговал.
    q = _bars([100.0, 105.0, 108.0, 108.0, 108.5, 107.5],
              [100.0, 100.0, 104.0, 108.0, 108.0, 107.0],
              [100.0, 106.0, 110.0, 200.0, 109.0, 109.0], entry=100.0,
              vols=[1e3, 1e3, 1e3, 0.0, 1e3, 1e3])
    qt = _dca_take(q, rule=rr, rungs=[100.0], w=[1.0], lev=1.0)
    # Верх 200 у минуты-котировки максимум не двигает: трейл остаётся на
    # 110·0.98, и выход случается только там, где низ до него дошёл.
    assert qt["exit"] == "трейл" and qt["exit_ts"] == 5, qt
    assert abs(qt["exit_px"] - t["exit_px"]) < 1e-9, (qt, t)
    print(f"ok  трейл: взвод в баре 1, выход в баре {int(t['exit_ts'])} "
          f"по {t['exit_px']:.2f} ({t['pnl_frac']*100:+.2f}% против "
          f"{p['pnl_frac']*100:+.2f}% у обычного тейка); "
          f"верх минуты-котировки максимум не двигает")


def test_take_px_and_take_rule_together_are_refused():
    """Два уровня разом неоднозначны — отказ, а не молчаливый выбор."""
    bars = _bars([100.0, 106.0], [100.0, 100.0], entry=100.0)
    try:
        _dca_take(bars, take_px=105.0, rule={"anchor": "avg", "frac": 0.05})
    except ValueError:
        print("ok  take_px вместе с take_rule отвергнуты")
        return
    raise AssertionError("два уровня разом приняты молча")


# ------------------------------------------------- зеркало короткой стороны
# Правка стороны опасна ровно тем, что может незаметно сдвинуть числа
# ДЛИННЫХ книг: у них уже есть записанная история, и «другая мера» под тем
# же именем — худшее, что может случиться. Поэтому проверок две породы:
# зеркало считает то, что должно, И лонг не шелохнулся.


def test_short_take_fills_below_entry():
    """Тейк шорта стоит НИЖЕ входа и исполняется низом бара по уровню."""
    rungs = [100.0, 110.0, 120.0]          # доливы ВВЕРХ
    w = [1/3, 1/3, 1/3]
    # Низ второго бара стоит ВЫШЕ обоих доливов (115): по правилу лонга
    # («рунг не ниже низа бара») лестница не набралась бы вовсе, и только
    # верх (125) её набирает. Фикстура нарочно такая — иначе проверка
    # прошла бы и на неверном правиле заполнения.
    closes = [100.0, 120.0, 94.0]
    lows = [100.0, 115.0, 94.0]
    highs = [100.0, 125.0, 120.0]
    r = L.simulate_dca(_bars(closes, lows, highs, entry=100.0), rungs, w,
                       capital=1.0, leverage=2.0, mmr=MMR, take_px=96.0,
                       side="short")
    assert r["exit"] == "тейк", r["exit"]
    assert r["depth"] == 3, r["depth"]
    # средняя ШОРТА = потрачено/куплено, та же формула; выигрыш зеркален
    exp = (r["filled_notional"] / r["avg"]) * (r["avg"] - 96.0)
    assert abs(r["pnl_frac"] - exp) < 1e-9, (r["pnl_frac"], exp)
    assert r["pnl_frac"] > 0, r["pnl_frac"]
    print(f"ok  шорт: доливы вверх (глубина {r['depth']}), тейк ниже входа "
          f"по 96.00, +{r['pnl_frac']*100:.1f}%")


def test_short_rungs_need_the_price_to_rise():
    """Лестница шорта не набирается, пока цена НЕ ВЫРОСЛА до рунгов.

    Проверка отдельной фикстурой, а не внутри тейка: заполнение по
    неверному (длинному) правилу дало бы ту же глубину и ту же среднюю,
    только раньше по времени — то есть на пути, где цена ДО рунгов
    доходит, дефект неразличим вовсе. Здесь цена до них не доходит, и
    правило заполнения становится наблюдаемым.
    """
    rungs = [100.0, 110.0, 120.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 104.0, 94.0]
    lows = [100.0, 99.0, 94.0]
    highs = [100.0, 105.0, 104.0]          # ни один долив не достигнут
    r = L.simulate_dca(_bars(closes, lows, highs, entry=100.0), rungs, w,
                       capital=1.0, leverage=2.0, mmr=MMR, take_px=96.0,
                       side="short")
    assert r["exit"] == "тейк", r["exit"]
    assert r["depth"] == 1, r["depth"]
    assert abs(r["avg"] - 100.0) < 1e-9, r["avg"]
    print(f"ok  шорт: рост до рунгов не дошёл → глубина {r['depth']}, "
          f"ТВХ {r['avg']:.2f}")


def test_short_liquidation_is_above_entry():
    """Шорт ликвидируется ростом цены; у лонга тот же путь безобиден."""
    rungs = [100.0, 110.0, 120.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 200.0]
    lows = [100.0, 100.0]
    highs = [100.0, 240.0]                 # взлёт вдвое с лишним
    bars = _bars(closes, lows, highs, entry=100.0)
    sh = L.simulate_dca(bars, rungs, w, capital=1.0, leverage=2.0, mmr=MMR,
                        take_px=90.0, side="short")
    assert sh["exit"] == "ликвидация" and sh["pnl_frac"] == -1.0, sh
    lo_r = L.simulate_dca(bars, [100.0, 90.0, 80.0], w, capital=1.0,
                          leverage=2.0, mmr=MMR, take_px=110.0)
    assert lo_r["exit"] == "тейк", lo_r["exit"]
    print("ok  шорт ликвидируется ростом; лонг на том же пути берёт тейк")


def test_short_floor_cuts_above_entry():
    """Пол капитуляции у шорта срабатывает СВЕРХУ и режет не в −100 %."""
    rungs = [100.0, 110.0, 120.0]
    w = [1/3, 1/3, 1/3]
    closes = [100.0, 120.0, 150.0]
    lows = [100.0, 100.0, 130.0]
    highs = [100.0, 121.0, 158.0]
    r = L.simulate_dca(_bars(closes, lows, highs, entry=100.0), rungs, w,
                       capital=1.0, leverage=2.0, mmr=MMR, take_px=50.0,
                       floor_frac=0.10, side="short")
    assert r["exit"] == "пол", r["exit"]
    assert -1.0 < r["pnl_frac"] < 0.0, r["pnl_frac"]
    print(f"ok  шорт: пол сверху режет в минус, не −100 %: "
          f"{r['pnl_frac']*100:.1f}%")


def test_short_take_rule_walks_with_the_average():
    """Динамический тейк шорта едет ВВЕРХ вместе с ТВХ и стоит ниже неё."""
    rungs = [100.0, 110.0]
    w = [0.5, 0.5]
    # Бар 1 набирает второй рунг (ТВХ уходит вверх), бар 2 берёт цель:
    # от входа цель была бы 95, от ТВХ (≈104.76) — ≈99.5.
    closes = [100.0, 110.0, 99.0]
    lows = [100.0, 100.0, 99.0]
    highs = [100.0, 111.0, 110.0]
    tr = {"anchor": "avg", "frac": 0.05}
    r = L.simulate_dca(_bars(closes, lows, highs, entry=100.0), rungs, w,
                       capital=1.0, leverage=2.0, mmr=MMR, take_rule=tr,
                       side="short")
    assert r["exit"] == "тейк", r["exit"]
    assert r["depth"] == 2, r["depth"]
    lvl = r["exit_px"]
    assert 99.0 <= lvl <= 100.0, lvl          # от ТВХ, а не от входа
    assert abs(lvl - r["avg"] * 0.95) < 1e-9, (lvl, r["avg"])
    print(f"ok  шорт: цель от ТВХ {r['avg']:.2f} → {lvl:.2f} "
          f"(от входа было бы 95.00), +{r['pnl_frac']*100:.1f}%")


def test_short_rungs_and_fence_mirror():
    """Уровни, σ-сетка и забор зеркальны; лонг тем же вызовом не тронут."""
    up, d_up = L.sigma_rungs(100.0, sigma_frac=0.05, n_rungs=3,
                             spacing_sig=2.0, side="short")
    # Сравнение с допуском намеренно: у лонга `100·(1−0.1)` даёт ровно
    # 90.0, у шорта `100·(1+0.1)` — 110.00000000000001. Бит в бит обязан
    # совпадать только ЛОНГ (у него есть записанная история), зеркало
    # обязано совпадать по величине.
    assert all(abs(a - b) < 1e-9 for a, b in
               zip(up, [100.0, 110.0, 120.0])), up
    assert abs(d_up - 0.20) < 1e-9, d_up
    dn, d_dn = L.sigma_rungs(100.0, sigma_frac=0.05, n_rungs=3,
                             spacing_sig=2.0)
    assert dn == [100.0, 90.0, 80.0] and abs(d_dn - 0.20) < 1e-9, (dn, d_dn)
    lv = [80.0, 90.0, 96.0, 104.0, 112.0, 130.0]
    rs = L.structural_rungs(100.0, lv, min_gap=0.05, n_rungs=3,
                            side="short")
    assert rs == [100.0, 112.0, 130.0], rs      # 104 ближе 5 % — пропущен
    assert L.structural_rungs(100.0, lv, 0.05, 3) == [100.0, 90.0, 80.0]
    look = lambda notl: 0.02
    lev_s = L.max_leverage(rs, [1/3, 1/3, 1/3], 1.0, 100.0, 0.30, look,
                           survive_mult=1.0, side="short")
    assert lev_s > 0, lev_s
    qty, p_avg, notl = L.fully_loaded(rs, [1/3, 1/3, 1/3], 1.0, lev_s)
    p_liq = L.liq_price(p_avg, qty, 1.0, look(notl), "short")
    assert p_liq >= 100.0 * (1.0 + 1.0 * 0.30) - 1e-6, (p_liq, lev_s)
    print(f"ok  зеркало уровней и забора: σ-сетка вверх, уровни {rs}, "
          f"плечо {lev_s:.2f}× при ликвидации {p_liq:.1f}")


def test_short_open_mark_mirrors_the_sign():
    """Отметка открытого шорта тождественна симуляции и зеркальна знаком."""
    cap, lev = 25.0, 2.0
    mk = L.open_mark(90.0, 100.0, cap, lev, [0.5], side="short")
    assert mk is not None and mk > 0, mk
    assert abs(mk - L.open_mark(90.0, 100.0, cap, lev, [0.5])) > 1e-9
    assert abs(mk + L.open_mark(90.0, 100.0, cap, lev, [0.5])) < 1e-12
    print(f"ok  отметка шорта зеркальна: падение до 90 даёт "
          f"{mk*100:+.1f}% против {L.open_mark(90.0,100.0,cap,lev,[0.5])*100:+.1f}%")

def _poison_ladder(lit, sub, fn):
    """Подделка строки ядра и прогон проверки. True — контроль кусается."""
    import importlib
    import shutil
    import tempfile
    path = os.path.join(HERE, "ladder.py")
    src = open(path, encoding="utf-8").read()
    assert lit in src, f"подделка НЕ легла: литерала нет — {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="ladder-"), "ladder.py")
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, sub, 1))
        cache = os.path.join(HERE, "__pycache__")
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith("ladder."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(L)
        try:
            fn()
        except Exception:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(L)


def _control_take_anchor_ignored():
    """Якорь не читается — тейк всегда от входа."""
    return _poison_ladder(
        '(entry if take_rule["anchor"] == "entry" else avg_prev)',
        "entry",
        test_avg_anchor_follows_the_ladder_and_pays_filled_leverage)


def _control_take_level_uses_this_bar_average():
    """Уровень считается по ТВХ ПОСЛЕ долива этого же бара."""
    return _poison_ladder(
        '(entry if take_rule["anchor"] == "entry" else avg_prev)',
        '(entry if take_rule["anchor"] == "entry" else avg)',
        test_take_level_uses_the_average_at_the_bar_start)


def _control_trail_gets_the_level_price():
    """Трейл исполняется по уровню, а не по доступной цене."""
    return _poison_ladder("px = min(cl, stop)", "px = stop",
                          test_trailing_arms_then_exits_below_the_peak)


def _control_trail_arms_and_exits_in_one_bar():
    """Взвод переставлен ПЕРЕД выходом — трейл срабатывает в баре взвода."""
    return _poison_ladder(
        "            if peak is not None:\n"
        "                stop = peak * (1.0 - d * trail)",
        "            if peak is None and traded and fav >= lvl:\n"
        "                peak = fav\n"
        "            if peak is not None:\n"
        "                stop = peak * (1.0 - d * trail)",
        test_trailing_arms_then_exits_below_the_peak)


def _control_trail_peak_grows_on_a_quote_bar():
    """Максимум трейла растёт и на минуте без единого принта."""
    return _poison_ladder(
        "                if traded:\n"
        "                    peak = max(peak, fav) if side == \"long\" "
        "else min(peak, fav)",
        "                if True:\n"
        "                    peak = max(peak, fav) if side == \"long\" "
        "else min(peak, fav)",
        test_trailing_arms_then_exits_below_the_peak)


def _control_short_rungs_fill_by_long_rule():
    """Доливы шорта ищут НИЗ бара — лестница вверх не набирается."""
    return _poison_ladder(
        '        hit = (rung_prices[j] >= lo > 0) if side == "long" else (\n'
        '            0 < rung_prices[j] <= lo)',
        "        hit = (rung_prices[j] >= lo > 0)",
        test_short_rungs_need_the_price_to_rise)


def _control_short_take_level_not_mirrored():
    """Уровень цели считается вверх у обеих сторон."""
    return _poison_ladder(
        '               * (1.0 + d * float(take_rule["frac"])))',
        '               * (1.0 + float(take_rule["frac"])))',
        test_short_take_rule_walks_with_the_average)


def _control_short_pnl_sign_not_mirrored():
    """Знак исхода не зеркалится — падение цены у шорта в минус."""
    return _poison_ladder(
        '                         "pnl_frac": d * qty * (lvl - avg) / capital,',
        '                         "pnl_frac": qty * (lvl - avg) / capital,',
        test_short_take_fills_below_entry)


def _control_short_fence_compares_downwards():
    """Забор шорта требует ликвидации СНИЗУ — плечо выходит любым."""
    return _poison_ladder(
        '        return p <= target_liq if side == "long" else p >= target_liq',
        "        return p <= target_liq",
        test_short_rungs_and_fence_mirror)


TESTS = [
    test_open_mark_equals_the_simulation_pnl,
    test_liq_price_matches_spec5_table,
    test_one_x_long_cannot_liquidate,
    test_mmr_tier_lookup,
    test_fully_loaded_avg_and_notional,
    test_max_leverage_derived_from_fence,
    test_max_leverage_refuses_impossible_depth,
    test_venue_leverage_cap_binds,
    test_fence_refuses_leverage_dead_at_open,
    test_sigma_rungs_descend,
    test_short_take_fills_below_entry,
    test_short_rungs_need_the_price_to_rise,
    test_short_liquidation_is_above_entry,
    test_short_floor_cuts_above_entry,
    test_short_take_rule_walks_with_the_average,
    test_short_rungs_and_fence_mirror,
    test_short_open_mark_mirrors_the_sign,
    test_ladder_beats_hold_on_recovery,
    test_ladder_partial_fill,
    test_liquidation_on_gap,
    test_dca_matches_ladder_bit_for_bit,
    test_dca_take_on_recovery,
    test_dca_capit_floor_in_the_red,
    test_dca_liquidation_gap,
    test_single_stop_and_take,
    test_same_coin_short_no_trigger,
    test_same_coin_short_recovers_to_zero,
    test_same_coin_short_crash_gains,
    test_liq_price_short_is_above,
    test_single_short_take_stop_liq,
    test_track_does_not_change_numbers,
    test_track_last_equals_outcome,
    test_track_marks_hour_close,
    test_fills_describe_the_position_and_its_floating_entry,
    test_limit_needs_a_print_market_exit_does_not,
    test_entry_anchored_rule_equals_take_px,
    test_avg_anchor_follows_the_ladder_and_pays_filled_leverage,
    test_take_level_uses_the_average_at_the_bar_start,
    test_trailing_arms_then_exits_below_the_peak,
    test_take_px_and_take_rule_together_are_refused,
]


CONTROLS = [
    ("доливы шорта по правилу лонга", _control_short_rungs_fill_by_long_rule),
    ("цель шорта не зеркалится", _control_short_take_level_not_mirrored),
    ("знак исхода шорта не зеркалится", _control_short_pnl_sign_not_mirrored),
    ("забор шорта сравнивает вниз", _control_short_fence_compares_downwards),
    ("(1−mmr) в цене ликвидации", _control_no_mmr_term),
    ("плечо не ограничено забором", _control_leverage_unbounded),
    ("предел тира площадки не читается", _control_venue_cap_ignored),
    ("ликвидация на входе разрешена", _control_dead_at_open_allowed),
    ("ликвидация не проверяется", _control_no_liquidation_check),
    ("рунги не заполняются", _control_rungs_never_fill),
    ("пола капитуляции нет", _control_dca_no_floor),
    ("тейк игнорируется", _control_dca_take_ignored),
    ("короткий восстанавливается на баре входа",
     _control_short_recovers_on_entry_bar),
    ("сторона шорта игнорируется", _control_short_side_ignored),
    ("отметка по началу часа", _control_track_marks_hour_open),
    ("доливы не записываются", _control_fills_not_logged),
    ("плечо забыто в живой отметке", _control_open_mark_forgets_leverage),
    ("лимитка заполняется без принта", _control_limit_fills_without_a_print),
    ("якорь тейка не читается", _control_take_anchor_ignored),
    ("уровень по ТВХ этого же бара", _control_take_level_uses_this_bar_average),
    ("трейл получает цену уровня", _control_trail_gets_the_level_price),
    ("трейл взводится и выходит одним баром",
     _control_trail_arms_and_exits_in_one_bar),
    ("максимум трейла растёт по котировке",
     _control_trail_peak_grows_on_a_quote_bar),
]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
