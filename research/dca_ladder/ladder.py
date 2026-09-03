#!/usr/bin/env python3
"""
DCA-лестница с забором по §5 — ЯДРО (спека 14).

Единственная копия расчёта забора: её зовут и дешёвый потолок D1, и
позже живая книга D5. Второй копии не заводить — так дважды расходились
`nulls.py` (F3) и загрузчик funding.

Здесь только арифметика забора, без чтения хранилища и без выбора
уровней (уровни — структура T4, живёт в `run_d1`). Что считается:

1. **Цена ликвидации** длинной позиции при кросс-марже — точная формула,
   закреплённая таблицей §5 спеки 01 (плечо 3× → ликвидация ≈ −33 %,
   10× → −9.6 %, 25× → −3.6 %, 50× → −1.6 %). Это единственное место, где
   ошибка ловится точным числом, поэтому оно проверяется первым.
2. **Ставка maintenance margin по тиру** нотионала (D0). Нет тиров
   (снятый контракт) — плоский MMR по правилу, а не ноль.
3. **Максимальное плечо ВЫВОДИТСЯ** из неравенства безопасности: цена
   ликвидации полностью набранной лестницы обязана стоять не ближе
   `survive_mult · D_max` к базовому входу — то есть после самого
   глубокого долива цена может пройти ещё столько же (или больше) вниз,
   прежде чем биржа закроет. `survive_mult` — объединённый §5-множитель
   (SAFETY·k), объявленная ось; при `D_max = 20 %` и множителе 2 плечо
   выходит ~3× (сходится с потолком «≤ 3×» спеки 01 §5).

Только stdlib. Все цены — в абсолютной цене инструмента, доли — доли.
"""


def liq_price(p_avg, qty, capital, mmr):
    """Цена ликвидации длинной позиции при кросс-марже.

    Вывод (лонг, кросс, выделенный капитал `capital` = маржа позиции):
        эквити при цене P:   capital + qty·(P − p_avg)
        поддерживающая маржа: mmr · P · qty
        ликвидация:          эквити = поддерживающая маржа
        ⇒ P_liq = (qty·p_avg − capital) / (qty·(1 − mmr))

    При плече 1× (capital = qty·p_avg) числитель = 0 → P_liq = 0: лонг
    без плеча не ликвидируется вовсе. Проверено таблицей §5.
    """
    denom = qty * (1.0 - mmr)
    if denom <= 0:
        return 0.0
    p = (qty * p_avg - capital) / denom
    return p if p > 0 else 0.0


def liq_frac(p_ref, p_liq):
    """Насколько ниже опорной цены стоит ликвидация, долей (0..1)."""
    if p_ref <= 0:
        return 0.0
    d = (p_ref - p_liq) / p_ref
    return d if d > 0 else 0.0


def mmr_for_notional(tiers, notional, flat=None):
    """Ставка maintenance margin тира, чей верх нотионала ≥ позиции.

    `tiers` — лестница D0 (по возрастанию нотионала). Позиция крупнее
    самого верхнего тира берёт ставку верхнего (за пределом таблицы
    плечо и так минимально). Тиров нет — плоский `flat` по правилу; если
    и его нет, это ошибка вызова, а не молчаливый ноль.
    """
    if tiers:
        for t in tiers:
            if notional <= t["cap"]:
                return t["mmr"]
        return tiers[-1]["mmr"]
    if flat is None:
        raise ValueError("нет тиров и нет плоского MMR — нечем считать забор")
    return flat


def fully_loaded(rung_prices, weights, capital, leverage):
    """Состояние ПОЛНОСТЬЮ набранной лестницы при данном плече.

    `capital` — маржа позиции, `leverage` — множитель нотионала, так что
    суммарный нотионал = capital·leverage. Вес `weights[i]` — доля
    нотионала на рунге `i`; на каждом рунге куплено `w·capital·leverage`
    в деньгах, то есть `w·capital·leverage / price` в количестве.
    Возвращает (qty_total, p_avg, notional).
    """
    if len(rung_prices) != len(weights):
        raise ValueError("рунгов и весов разное число")
    notional = capital * leverage
    qty = 0.0
    for p, w in zip(rung_prices, weights):
        if p <= 0:
            raise ValueError("цена рунга ≤ 0")
        qty += (w * notional) / p
    if qty <= 0:
        raise ValueError("нулевое количество")
    # p_avg = потраченные деньги / количество; потрачено ровно notional
    p_avg = notional / qty
    return qty, p_avg, notional


def max_leverage(rung_prices, weights, capital, base_px, d_max,
                 mmr_lookup, survive_mult, lev_cap=25.0):
    """Максимальное плечо, при котором забор §5 выполняется.

    Забор: цена ликвидации полностью набранной лестницы ≤ базового входа,
    сдвинутого вниз на `survive_mult · d_max`. То есть после самого
    глубокого планового долива цена может пройти ещё `survive_mult · d_max`
    (доля от базовой цены) вниз, прежде чем биржа закроет.

    `mmr_lookup(notional) -> mmr` — ставка тира (или плоская). MMR зависит
    от нотионала, а нотионал — от плеча, поэтому считаем на каждом шаге
    поиска, а не один раз. Возвращает плечо (float); если даже 1× не
    проходит — 0.0 (лестница такой глубины недопустима: обрезать `d_max`).

    Плечо ВЫВОДИТСЯ, а не назначается: двоичный поиск по [1, lev_cap].
    """
    target_liq = base_px * (1.0 - survive_mult * d_max)

    def ok(L):
        qty, p_avg, notional = fully_loaded(rung_prices, weights, capital, L)
        mmr = mmr_lookup(notional)
        return liq_price(p_avg, qty, capital, mmr) <= target_liq

    if not ok(1.0):
        return 0.0                      # даже без плеча забор нарушен
    lo, hi = 1.0, lev_cap
    if ok(hi):
        return hi                       # весь диапазон проходит
    for _ in range(40):                 # ~1e-8 по плечу
        mid = (lo + hi) / 2.0
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


# ---------------------------------------------------------- реплей позиции

def sigma_rungs(base_px, sigma_frac, n_rungs, spacing_sig):
    """Цены рунгов ВНИЗ по σ-сетке: база плюс равные шаги в единицах σ.

    `sigma_frac` — волатильность имени долей цены (σ доходности за бар,
    накопленная на окне оценки). Рунг `i` стоит на `i · spacing_sig · σ`
    ниже базы. Рунг 0 — сама база. σ-сетка есть объявленный спекой §4
    запасной каркас уровней и БАЗА, против которой структурные уровни T4
    судятся нулём §8.6: сначала дешёвое, потом структура.

    Возвращает список цен по УБЫВАНИЮ (рунг 0 = база сверху) и `d_max` —
    глубину самого нижнего рунга долей базы.
    """
    if n_rungs < 1:
        raise ValueError("рунгов меньше одного")
    step = spacing_sig * sigma_frac
    prices = [base_px * (1.0 - i * step) for i in range(n_rungs)]
    if prices[-1] <= 0:
        raise ValueError("нижний рунг ушёл в ноль или ниже — сетка глубже 100 %")
    d_max = (base_px - prices[-1]) / base_px
    return prices, d_max


def simulate_ladder(closes, lows, rung_prices, weights, capital, leverage, mmr):
    """Пройти путь цены лестницей доливов вниз. Чистая функция.

    `closes`, `lows` — путь удержания на сетке, база в индексе 0.
    `rung_prices` — цены рунгов по убыванию, `rung_prices[0]` = база; рунг
    заполняется, когда бегущий минимум бара опускается до его цены. Плечо
    выведено §5 в предположении ПОЛНОЙ загрузки; частичная даёт меньший
    нотионал, выше среднюю, ниже плечо — цена ликвидации считается по
    ТЕКУЩЕМУ набранному состоянию каждый бар.

    Возвращает: `liquidated` (пробита ли цена ликвидации), `pnl_frac`
    (итог долей капитала позиции; ликвидация = −1.0), `depth` (сколько
    рунгов заполнилось), `avg` (итоговая средняя), `filled_notional`.
    """
    n = len(rung_prices)
    if len(weights) != n:
        raise ValueError("рунгов и весов разное число")
    if not closes:
        raise ValueError("пустой путь")
    base = rung_prices[0]
    notional = capital * leverage
    # база (рунг 0) заполнена входом
    filled = [False] * n
    filled[0] = True
    cash = weights[0] * notional
    qty = cash / base
    for lo, cl in zip(lows, closes):
        # заполнить рунги, до которых опустился минимум бара
        for j in range(1, n):
            if not filled[j] and rung_prices[j] >= lo > 0:
                filled[j] = True
                cash += weights[j] * notional
                qty += weights[j] * notional / rung_prices[j]
        avg = cash / qty
        p_liq = liq_price(avg, qty, capital, mmr)
        if lo <= p_liq:                         # разрыв пробил забор
            return {"liquidated": True, "pnl_frac": -1.0,
                    "depth": sum(filled), "avg": avg,
                    "filled_notional": cash}
    final = closes[-1]
    avg = cash / qty
    pnl_frac = qty * (final - avg) / capital     # доля капитала позиции
    return {"liquidated": False, "pnl_frac": pnl_frac,
            "depth": sum(filled), "avg": avg, "filled_notional": cash}


def simulate_hold(closes, lows, base_px, capital, leverage, mmr):
    """Контроль: весь нотионал куплен в базе разом, без лестницы.

    Тот же капитал, то же предельное плечо, то же окно — но вход один.
    Разница с лестницей и есть замен «усреднять вниз против держать».
    """
    if not closes:
        raise ValueError("пустой путь")
    notional = capital * leverage
    qty = notional / base_px
    for lo in lows:
        p_liq = liq_price(base_px, qty, capital, mmr)
        if lo <= p_liq:
            return {"liquidated": True, "pnl_frac": -1.0}
    final = closes[-1]
    pnl_frac = qty * (final - base_px) / capital
    return {"liquidated": False, "pnl_frac": pnl_frac}
