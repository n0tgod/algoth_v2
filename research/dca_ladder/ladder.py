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


def liq_price(p_avg, qty, capital, mmr, side="long"):
    """Цена ликвидации позиции при кросс-марже; сторона параметром.

    Вывод (лонг, кросс, выделенный капитал `capital` = маржа позиции):
        эквити при цене P:   capital + qty·(P − p_avg)
        поддерживающая маржа: mmr · P · qty
        ликвидация:          эквити = поддерживающая маржа
        ⇒ P_liq = (qty·p_avg − capital) / (qty·(1 − mmr))

    Для ШОРТА знаки хода и маржи зеркальны: эквити = capital + qty·(p_avg − P),
    ликвидация ВЫШЕ средней ⇒ P_liq = (qty·p_avg + capital)/(qty·(1 + mmr)).
    Одна формула на обе стороны через `d` (+1 лонг, −1 шорт):
        P_liq = (qty·p_avg − d·capital) / (qty·(1 − d·mmr)).

    При лонге 1× (capital = qty·p_avg) числитель = 0 → P_liq = 0: лонг без
    плеча не ликвидируется. Шорт 1× ликвидируется при росте цены вдвое
    (P_liq ≈ 2·p_avg). Умолчание `long` — прежнее поведение бит-в-бит,
    таблица §5 не тронута.
    """
    d = 1.0 if side == "long" else -1.0
    denom = qty * (1.0 - d * mmr)
    if denom <= 0:
        return 0.0
    p = (qty * p_avg - d * capital) / denom
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
                 mmr_lookup, survive_mult, lev_cap=25.0, side="long"):
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

    У короткой стороны забор зеркален: ликвидация стоит ВЫШЕ входа, и
    требование — чтобы она была не ближе `survive_mult · d_max` сверху.
    Правило одно, знак разный; ветка лонга не тронута.
    """
    d = 1.0 if side == "long" else -1.0
    target_liq = base_px * (1.0 - d * survive_mult * d_max)

    def ok(L):
        qty, p_avg, notional = fully_loaded(rung_prices, weights, capital, L)
        mmr = mmr_lookup(notional)
        p = liq_price(p_avg, qty, capital, mmr, side)
        return p <= target_liq if side == "long" else p >= target_liq

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

def sigma_rungs(base_px, sigma_frac, n_rungs, spacing_sig, side="long"):
    """Цены рунгов по σ-сетке: база плюс равные шаги в единицах σ.

    `sigma_frac` — волатильность имени долей цены (σ доходности за бар,
    накопленная на окне оценки). Рунг `i` стоит на `i · spacing_sig · σ`
    ниже базы. Рунг 0 — сама база. σ-сетка есть объявленный спекой §4
    запасной каркас уровней и БАЗА, против которой структурные уровни T4
    судятся нулём §8.6: сначала дешёвое, потом структура.

    Возвращает список цен от базы ПРОЧЬ от неё (рунг 0 = база) и `d_max`
    — глубину самого дальнего рунга долей базы. У короткой стороны сетка
    зеркальна: рунги стоят ВЫШЕ базы, `d_max` считается тем же модулем.
    """
    if n_rungs < 1:
        raise ValueError("рунгов меньше одного")
    step = spacing_sig * sigma_frac
    d = 1.0 if side == "long" else -1.0
    prices = [base_px * (1.0 - d * i * step) for i in range(n_rungs)]
    if prices[-1] <= 0:
        raise ValueError("дальний рунг ушёл в ноль или ниже — сетка глубже 100 %")
    d_max = abs(base_px - prices[-1]) / base_px
    return prices, d_max


def structural_rungs(entry, level_prices, min_gap, n_rungs, side="long"):
    """Цены рунгов DCA: вход плюс СТРУКТУРНЫЕ уровни против позиции.

    Берём уровни против позиции (лонгу — ниже входа, шорту — выше;
    у шорта это зеркало, а не другое правило), ближайший первым,
    каждый обязан стоять не
    ближе `min_gap` (доля цены) от предыдущего рунга — это «запас на
    дальнейший пролив» §R1 и «не дважды на одном уровне». Возвращает
    список по УБЫВАНИЮ (`rungs[0]` = вход), длиной ≤ `n_rungs`; если ни
    один уровень не годится, вернёт `[entry]` — лестница вырождается в
    одиночный вход без доливов, и плечо тогда 1× (нет резерва — нет
    рычага). Чистая функция.

    Живёт здесь, а не в реплее, по той же причине, по которой рядом
    живёт `sigma_rungs`: цены рунгов понадобились ЖИВОЙ книге (сканер
    сравнивает с ними цену каждые пять секунд), а сканер стандартную
    библиотеку не покидает. Вторая копия правила означала бы, что живая
    книга усредняется не на тех уровнях, на которых её судит реплей.
    """
    if entry <= 0:
        return [entry]
    if side == "long":
        away = sorted([p for p in level_prices if 0 < p < entry], reverse=True)
    else:
        away = sorted([p for p in level_prices if p > entry > 0])
    rungs = [entry]
    for p in away:
        if len(rungs) >= n_rungs:
            break
        gap = ((rungs[-1] - p) if side == "long" else (p - rungs[-1]))
        if gap / rungs[-1] >= min_gap:   # ≥min_gap дальше прошлого рунга
            rungs.append(p)
    return rungs


def open_mark(px, avg, capital, leverage, weights_filled, side="long"):
    """Отметка ОТКРЫТОЙ лестницы: доля капитала позиции при цене `px`.

    Ровно та величина, которую симуляция зовёт `pnl_frac`, только на
    живой цене вместо закрытия последнего бара:

        qty = cash / avg,  cash = capital · leverage · Σw
        pnl = qty · (px − avg) / capital = cash/capital · (px/avg − 1)

    Живёт в ядре и проверена ТОЖДЕСТВОМ с `simulate_dca` не ради
    красоты: отметка открытой позиции считается в двух местах — часовым
    прогоном (по бару) и страницей (по живой середине), — и две формулы
    под одним именем однажды разошлись бы. Тогда владелец видел бы одно
    число, а книга держала бы другое.

    `avg` или капитал не положительны — меры нет (`None`), а не ноль:
    ноль объявил бы позицию ровной там, где переоценить нечем.

    У шорта знак хода зеркален (`side="short"`) — то же тождество с
    зеркальной симуляцией; умолчание не тронуто.
    """
    if not avg or avg <= 0 or not capital or capital <= 0:
        return None
    d = 1.0 if side == "long" else -1.0
    cash = float(capital) * float(leverage) * sum(weights_filled)
    return d * cash / float(capital) * (float(px) / float(avg) - 1.0)


def _fill_rungs(filled, cash, qty, lo, rung_prices, weights, notional,
                log=None, bt=None, side="long"):
    """Заполнить рунги долива, до которых дошёл крайний ход бара `lo`.

    Одна копия логики долива на весь модуль: её зовут и потолок D1
    (`simulate_ladder`), и стратегия D2 (`simulate_dca`). Рунг `j` (цена
    ниже базы) заполняется по СВОЕЙ цене `rung_prices[j]` — структурный
    уровень или узел σ-сетки, — когда низ бара до неё дошёл. Возвращает
    обновлённые (filled, cash, qty).

    `log` — список, куда дописывается КАЖДЫЙ долив `(время бара, цена,
    доля нотионала)`. Он нужен показу: позиция сворачивается в одну
    строку, а разворачивается в свои входы, и средняя цена входа
    («плавающая ТВХ») выводится из этого же списка. Счёт от журнала не
    зависит ни на бит: список только записывает уже случившееся.

    `side="short"` — зеркало: рунги стоят ВЫШЕ базы, и заполняет их верх
    бара (аргумент `lo` тогда несёт максимум). Ветка лонга оставлена
    дословно прежней, а не выражена через знак: правка стороны, меняющая
    числа длинных книг, была бы другой мерой, а не зеркалом.
    """
    for j in range(1, len(rung_prices)):
        hit = (rung_prices[j] >= lo > 0) if side == "long" else (
            0 < rung_prices[j] <= lo)
        if not filled[j] and hit:
            filled[j] = True
            cash += weights[j] * notional
            qty += weights[j] * notional / rung_prices[j]
            if log is not None:
                log.append((bt, float(rung_prices[j]), float(weights[j])))
    return filled, cash, qty


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
        filled, cash, qty = _fill_rungs(filled, cash, qty, lo,
                                        rung_prices, weights, notional)
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


# ------------------------------------------------------ D2: стратегия на барах
# Вход = выбор модели (первый рунг), доливы вниз на уровнях, выход тейк + пол
# капитуляции (§6). Первый срез — ЛОНГИ (естественный DCA-вниз); шорты зеркало,
# следом. Бары — OHLC минуты записи сборщика: (t, open, high, low, close, qv).

def simulate_single(bars, capital, leverage, mmr, take_px=None, stop_px=None,
                    side="long"):
    """Одиночный вход тем же капиталом и плечом, стоп/тейк; сторона параметром.

    Тот же вход (открытие ПЕРВОГО бара после решения, next_open), весь
    нотионал разом — так книга торгует сейчас. Для ЛОНГА стоп/ликвидация по
    НИЗУ бара (адверс — падение), тейк по ВЕРХУ; для ШОРТА зеркально —
    адверс это РОСТ (по верху), тейк по низу. Стоп раньше тейка (ничья
    против нас). Знак хода `d` (+1 лонг, −1 шорт): pnl = qty·d·(уровень −
    вход). Умолчание `long` — прежнее поведение бит-в-бит.

    Возвращает: exit ("ликвидация"/"стоп"/"тейк"/"срок"), pnl_frac, exit_ts,
    exit_px.
    """
    if not bars:
        raise ValueError("пустой путь")
    entry = float(bars[0][1])
    if entry <= 0:
        raise ValueError("цена входа ≤ 0")
    d = 1.0 if side == "long" else -1.0
    notional = capital * leverage
    qty = notional / entry
    p_liq = liq_price(entry, qty, capital, mmr, side)  # средняя не меняется
    for (bt, _o, hi, lo, cl, _v) in bars:
        adverse = lo if side == "long" else hi         # ход ПРОТИВ позиции
        fav = hi if side == "long" else lo             # ход В ПОЛЬЗУ
        if d * (adverse - p_liq) <= 0:                 # адверс дошёл до ликв.
            return {"exit": "ликвидация", "pnl_frac": -1.0, "exit_ts": bt,
                    "exit_px": p_liq}
        if stop_px is not None and d * (adverse - stop_px) <= 0:
            return {"exit": "стоп", "exit_ts": bt, "exit_px": stop_px,
                    "pnl_frac": qty * d * (stop_px - entry) / capital}
        if take_px is not None and d * (fav - take_px) >= 0:
            return {"exit": "тейк", "exit_ts": bt, "exit_px": take_px,
                    "pnl_frac": qty * d * (take_px - entry) / capital}
    lb = bars[-1]
    return {"exit": "срок", "exit_ts": lb[0], "exit_px": float(lb[4]),
            "pnl_frac": qty * d * (float(lb[4]) - entry) / capital}


def simulate_dca(bars, rung_prices, weights, capital, leverage, mmr,
                 take_px=None, floor_frac=None, track=False,
                 checkpoints=None, take_rule=None, side="long"):
    """DCA на РЕАЛЬНЫХ барах: доливы против хода, тейк по ходу, пол.

    Вход в `bars[0][1]` (открытие первого бара после решения, next_open) —
    это база; `rung_prices[1:]` — цены доливов ВНИЗ (структурные уровни или
    узлы σ-сетки, по убыванию), рунг `j` заполняется, когда НИЗ бара до неё
    дошёл (`_fill_rungs`, одна копия долива на модуль). `rung_prices[0]` не
    используется — база покупается по фактической цене входа.

    Выход:
    - **тейк** `take_px` (выше входа) — лимитка на уровне (правило v13):
      когда ВЕРХ бара доходит до уровня, исполнение по уровню;
    - **пол капитуляции** (§6, фенс): когда лестница ВЫЧЕРПАНА (все рунги
      заполнены) И низ бара подошёл к цене ликвидации ближе `floor_frac` её
      расстояния до входа — закрытие по ЗАКРЫТИЮ бара, в минус (разрыв не
      держит на уровне, урок S1: закрываем по доступной цене);
    - **ликвидация** — низ пробил цену ликвидации текущего состояния;
    - **срок** — бары кончились.

    Порядок в баре: заполнить рунги → ликвидация → пол → тейк
    (неблагоприятное раньше благоприятного, ничья против нас). Рунг и
    тейк — ЛИМИТКИ, поэтому на баре с нулевым объёмом (минута без единой
    сделки) они не заполняются вовсе; ликвидация, пол и срок считаются и
    там — это рыночные выходы против котировки. Ранняя
    капитуляция (рулевой §6) здесь НЕ считается — она мерится против пола
    отдельной рукой (пересчёт), вердикт по «только пол».

    `checkpoints` — возрастающий список АБСОЛЮТНЫХ меток времени; на
    каждой возвращается переоценка позиции по закрытию последнего бара с
    `t ≤ метка` (`ckpt`: список `(метка, время бара, pnl)` либо `None`,
    если к этой метке сделка уже закрылась или ряд кончился раньше). Это
    ровно то, чем кончилась бы симуляция со сроком до этой метки, —
    отсюда замер срока удержания считается ОДНИМ проходом, а не проходом
    на каждый срок. Равенство усечения прямой симуляции закреплено
    тестом: пересчёт, дающий другие числа, есть другая мера.

    `track=True` добавляет почасовую отметку позиции: список
    `(час, занятый нотионал, pnl долей капитала)`, по одной записи на
    календарный час, значение — по ПОСЛЕДНЕМУ бару часа, последняя запись
    равна итогу сделки. Она нужна книжным замерам (экспозиция и переоценка
    книги во времени); сами возвращаемые числа от неё не меняются ни на
    бит — умолчание `False` даёт прежний счёт, и это закреплено тестом.

    `take_rule` — ДИНАМИЧЕСКИЙ тейк вместо неподвижного `take_px`
    (передавать оба нельзя — уровень стал бы неоднозначен). Словарь:
    `anchor` (`"entry"` — от цены входа, как у `take_px`; `"avg"` — от
    плавающей ТВХ, то есть цель едет вниз вместе со средней), `frac` —
    доля цены (0.05 = 5 %), `trail` — доля трейла или None.

    Уровень считается по ТВХ на НАЧАЛО бара: долив этой же минуты ТВХ
    опускает, но заявку мы переставляем только следующим баром. Иначе
    тейк, ставший достижимым ТОЛЬКО из-за долива в этом же баре,
    засчитывался бы нам внутрибарным путём, которого мы не видим
    (конвенция проекта: ничью решаем не в свою пользу).

    Трейлинг: `hi ≥ уровень` не закрывает позицию, а ВЗВОДИТ её (`peak`);
    дальше выход, когда низ бара опустился на `trail` от достигнутого
    максимума. Взвод и выход в одном баре невозможны по построению
    (выход проверяется раньше взвода), максимум растёт только на барах
    со сделками, а сам выход — РЫНОЧНЫЙ (`min(закрытие, уровень трейла)`:
    стоп не получает цену уровня, урок правила v13) и потому считается
    и на баре без принтов, как пол и ликвидация. Исход помечается
    отдельным `"трейл"`, чтобы его нельзя было спутать с тейком.

    `side="short"` — ЗЕРКАЛО той же конструкции, а не другая: доливы
    вверх, тейк вниз, ликвидация и пол сверху, трейл от достигнутого
    минимума. Ветки лонга оставлены дословно прежними и выбираются
    сравнением стороны, а не выражены через знак: правка, меняющая числа
    длинных книг, была бы другой мерой. Умолчание даёт прежний счёт
    бит в бит, и это закреплено тестом.

    Асимметрия сторон при этом НЕ является дефектом зеркала и её нельзя
    терять при чтении: у лонга убыток ограничен нулём цены, у шорта
    сверху не ограничен ничем — шорт 1× ликвидируется удвоением цены
    (`liq_price`), а F-серия намерила ноги, терявшие 475–590 % позиции.
    Значит одинаковые правила дают РАЗНЫЙ хвост, и сравнивать книги надо
    по форме, а не только по итогу.

    Возвращает: exit ("тейк"/"трейл"/"пол"/"ликвидация"/"срок"), pnl_frac
    (доля капитала позиции; ликвидация = −1.0), depth, avg,
    filled_notional.
    """
    d = 1.0 if side == "long" else -1.0
    n = len(rung_prices)
    if len(weights) != n:
        raise ValueError("рунгов и весов разное число")
    if not bars:
        raise ValueError("пустой путь")
    entry = float(bars[0][1])
    if entry <= 0:
        raise ValueError("цена входа ≤ 0")
    notional = capital * leverage
    filled = [False] * n
    filled[0] = True                    # база заполнена входом
    cash = weights[0] * notional
    qty = cash / entry                  # по ФАКТИЧЕСКОЙ цене входа
    # Входы позиции: база плюс каждый долив. Позиция на показе одна, а
    # входов у неё несколько — без этого списка развернуть её не во что,
    # и «плавающую ТВХ» (среднюю цену, ступенькой уходящую вниз) неоткуда
    # взять. Числа сделки от списка не зависят.
    fills = [(float(bars[0][0]), entry, float(weights[0]))]
    if take_rule is not None:
        if take_px is not None:
            raise ValueError("take_px и take_rule вместе неоднозначны")
        if take_rule.get("anchor") not in ("entry", "avg"):
            raise ValueError(f"неизвестный якорь тейка: {take_rule.get('anchor')}")
        if not float(take_rule.get("frac") or 0.0) > 0:
            raise ValueError("доля тейка обязана быть > 0")
    avg_prev = entry          # ТВХ на начало бара: заявка стоит с прошлого
    peak = None               # максимум после взвода трейлинга
    tr = [] if track else None
    cps = [float(x) for x in (checkpoints or [])]
    ck = [None] * len(cps)
    ck_i = 0
    last = None                          # (время бара, pnl переоценки)

    def _mark(bt, pnl):
        """Отметка часа: последняя запись часа побеждает (переоценка по
        концу часа), а на выходе кладётся сам исход сделки."""
        hr = bt - (bt % 3600)
        rec = (hr, cash, pnl)
        if tr and tr[-1][0] == hr:
            tr[-1] = rec
        else:
            tr.append(rec)

    def _ret(res, bt):
        res["fills"] = fills
        res["entry_px"] = entry
        if tr is not None:
            _mark(bt, res["pnl_frac"])
            res["track"] = tr
        if cps:
            res["ckpt"] = ck
        return res

    for (bt, _o, hi, lo, cl, vol) in bars:
        # Границы срока закрываются ДО обработки бара: бар с `t > метка` в
        # окно этого срока не входит, и переоценка на границе есть
        # закрытие ПОСЛЕДНЕГО бара, который в окно вошёл. Считать после
        # значило бы подарить сроку бар из будущего.
        while ck_i < len(cps) and cps[ck_i] < bt:
            ck[ck_i] = (cps[ck_i], last[0], last[1]) if last else None
            ck_i += 1
        # ЛИМИТКУ ИСПОЛНЯЕТ ЧУЖОЙ ПРИНТ. Бар с нулевым объёмом означает
        # минуту без единой сделки: рунг и тейк на ней не заполняются —
        # цену КОТИРОВАЛИ, но никто по ней не торговал, и засчитать себе
        # исполнение значило бы вернуть ошибку движка v1 («касание есть
        # заполнение»). Пол капитуляции, ликвидация и срок ниже считаются
        # и на такой минуте: это наш собственный (и биржи) РЫНОЧНЫЙ выход
        # против котировки, а не ожидание встречной заявки.
        # У баров ленты объём положителен всегда (они рождаются из
        # принтов), поэтому на прежних данных правило не меняет НИ ОДНОГО
        # числа — закреплено тестом. Нулевой объём приносит только хвост,
        # дописанный серединой стакана (`dca_paper/tail.py`).
        traded = float(vol) > 0
        adverse = lo if side == "long" else hi     # ход ПРОТИВ позиции
        fav = hi if side == "long" else lo         # ход В ПОЛЬЗУ
        if traded:
            filled, cash, qty = _fill_rungs(filled, cash, qty, adverse,
                                            rung_prices, weights, notional,
                                            log=fills, bt=float(bt),
                                            side=side)
        avg = cash / qty
        # Уровень тейка — по ТВХ на НАЧАЛО бара (`avg_prev`), а не по той,
        # что сложилась доливом ЭТОЙ минуты (см. докстроку).
        lvl = (take_px if take_rule is None else
               (entry if take_rule["anchor"] == "entry" else avg_prev)
               * (1.0 + d * float(take_rule["frac"])))
        mark = d * (qty * cl - cash) / capital
        if tr is not None:
            _mark(bt, mark)
        p_liq = liq_price(avg, qty, capital, mmr, side)
        if (adverse <= p_liq) if side == "long" else (adverse >= p_liq):
            return _ret({"exit": "ликвидация", "pnl_frac": -1.0,
                         "exit_ts": bt, "exit_px": p_liq,
                         "depth": sum(filled), "avg": avg,
                         "filled_notional": cash}, bt)
        if floor_frac is not None and all(filled):
            # Формула пола одна на обе стороны: у лонга ликвидация ниже
            # входа и пол оказывается между ними, у шорта выше — и пол
            # снова между. Разный тут только знак срабатывания.
            floor_px = p_liq + floor_frac * (entry - p_liq)
            hit = ((adverse <= floor_px) if side == "long"
                   else (adverse >= floor_px))
            if hit:                            # подошли к ликвидации — режем
                return _ret({"exit": "пол",
                             "pnl_frac": d * qty * (cl - avg) / capital,
                             "exit_ts": bt, "exit_px": cl,
                             "depth": sum(filled), "avg": avg,
                             "filled_notional": cash}, bt)
        trail = (float(take_rule.get("trail") or 0.0)
                 if take_rule is not None else 0.0)
        if trail > 0:
            if peak is not None:
                stop = peak * (1.0 - d * trail)
                hit = (adverse <= stop) if side == "long" else (adverse >= stop)
                if hit:                      # трейл — РЫНОЧНЫЙ выход
                    px = min(cl, stop) if side == "long" else max(cl, stop)
                    return _ret({"exit": "трейл",
                                 "pnl_frac": d * qty * (px - avg) / capital,
                                 "exit_ts": bt, "exit_px": px,
                                 "depth": sum(filled), "avg": avg,
                                 "filled_notional": cash}, bt)
                if traded:
                    peak = max(peak, fav) if side == "long" else min(peak, fav)
            elif traded and ((fav >= lvl) if side == "long" else (fav <= lvl)):
                peak = fav                   # взвели; выход со следующего бара
        elif traded and lvl is not None and (
                (fav >= lvl) if side == "long" else (fav <= lvl)):
            return _ret({"exit": "тейк",
                         "pnl_frac": d * qty * (lvl - avg) / capital,
                         "exit_ts": bt, "exit_px": lvl,
                         "depth": sum(filled), "avg": avg,
                         "filled_notional": cash}, bt)
        avg_prev = avg
        last = (bt, mark)
    lb = bars[-1]
    avg = cash / qty
    return _ret({"exit": "срок",
                 "pnl_frac": d * qty * (float(lb[4]) - avg) / capital,
                 "exit_ts": lb[0], "exit_px": float(lb[4]),
                 "depth": sum(filled), "avg": avg,
                 "filled_notional": cash}, lb[0])


def same_coin_short(bars, trigger_px, exit_ts, exit_px, short_notional):
    """Короткий на ТОЙ ЖЕ монете, включаемый в просадке (вариант а).

    Идея владельца: пока лонг в просадке, параллельный короткий на той же
    монете поддерживает деп; когда просадка кончилась — короткий закрыт, и
    лонг забирает отскок (свой эдж). Реализация как маленький автомат по
    барам удержания (до выхода лонга `exit_ts`):

    - **вход** короткого — когда низ бара впервые доходит до `trigger_px`
      (уровень просадки, напр. первый долив): продажа НА ПРОБОЙ уровня вниз,
      исполнение по уровню (та же модель, что тейк-лимитка v13);
    - **выход по восстановлению** — когда верх бара впервые доходит до
      `trigger_px` ПОСЛЕ входа: покупка на пробой вверх по уровню, pnl ровно
      0 (вошли и вышли по одному уровню) — просадка кончилась, лонг едет
      дальше сам, короткий median НЕ ест;
    - **выход с лонгом** — если восстановления не было до `exit_ts`, короткий
      закрывается там же, где лонг, по `exit_px` (ликвидация → p_liq, срок →
      закрытие): при продолжении падения даёт плюс — гасит хвост.

    Короткий ОДИН на позицию (после восстановления не переоткрывается —
    второй провал не хеджируется; это занижает пользу, консервативно).
    `short_notional` — нотионал короткого долей капитала (β_s·нотионал
    лонга). Возвращает pnl короткого долей капитала, либо None, если
    просадка до триггера не дошла (короткого не было вовсе). Чистая функция.
    """
    if trigger_px <= 0:
        return None
    opened = False
    for (bt, _o, hi, lo, _cl, _v) in bars:
        if bt > exit_ts:
            break
        if not opened:
            if lo <= trigger_px:               # просадка пробила триггер вниз
                opened = True                  # вход; восстановление — со след. бара
            continue                            # на баре входа выхода не ищем
        if hi >= trigger_px:                    # восстановление сквозь уровень
            return 0.0                          # вошли и вышли по триггеру — pnl 0
    if not opened:
        return None                             # просадки до триггера не было
    # восстановления не случилось — закрываем с лонгом по его цене выхода
    return short_notional * (trigger_px - exit_px) / trigger_px
