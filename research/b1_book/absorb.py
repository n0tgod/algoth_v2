#!/usr/bin/env python3
"""
Поглощение в стакане: крупный стоит, его выедают, он подставляет снова.

Чем это отличается от всего, что стенд мерил раньше
---------------------------------------------------

Четыре замера направления ленты (T1–T4) считались по **принтам** — по
состоявшимся сделкам. По ним «крупного выкупают» и «продавцы кончились
сами» выглядят одинаково: в обоих случаях виден объём и стоящая цена.
Различает их только очередь заявок, а её в архивах нет ни у Bybit, ни у
Binance. Поэтому стакан пишется живьём, и поэтому здесь появляется
условие, которое на ленте не выражается в принципе.

Ключевая величина — **выедено против показанного**. Если через уровень
прошло агрессии больше, чем он когда-либо показывал размером, значит
его подставляли заново. Лента даёт числитель и не даёт знаменателя.

Правило входа, пять условий сразу
---------------------------------

Каждую секунду по каждому символу берётся самый крупный по нотионалу
уровень своей стороны в пределах `NEAR` шумов от лучшей цены.

1. **Крупный** — его нотионал не меньше `BIG` медиан по видимым уровням
   той же стороны. Мера относительная намеренно: у BTC и ARBUSDT
   абсолютные размеры несравнимы, и константа означала бы разное.
2. **Стоит** — та же цена держится крупной `HOLD` секунд подряд.
   Сменилась цена или уровень измельчал — отсчёт с нуля.
3. **Выедают** — накопленная агрессия противоположной стороны с момента
   появления уровня не меньше `EAT` его размера.
4. **Не пробит** — сделок ниже уровня (для бида) не проходило.
   Пробой виден по ленте, а не по книге: у бида лучшая цена по
   построению не бывает ниже уровня, лежащего в этом же биде.
5. **Восполнен** — текущий размер не меньше `REFILL` от максимума,
   который уровень показывал.

Все пять — поглощение на стороне бида даёт лонг, на стороне аска шорт.

Чем это НЕ является
-------------------

Это наблюдение, а не гипотеза: порогов, объявленных заранее и
неизменных, здесь нет, и вердикта по этим сделкам не выносится. Пороги
подбираются глядя на диагностику — законно ровно потому, что никакого
вывода на них не строится. Вывод потребует спеки с объявленной сеткой,
нулевой моделью и замером на накопленных файлах, а не на памяти
процесса.

Оговорка, которую нельзя терять: агрессия считается **посекундно**, а
не по каждому принту, и приписывается уровню, когда цена секунды до
него дотянулась. На снимке раз в секунду точнее нельзя. Значит `EAT`
считается с точностью до секунды, и очень быстрые серии «удар —
восполнение» внутри секунды видны только в сыром потоке.

Только стандартная библиотека.
"""

from statistics import median

NEAR = 2.0                        # уровень ищем в стольких шумах от цены
BIG = 5.0                         # во столько раз крупнее медианы уровней
HOLD = 10                         # столько секунд подряд держится крупным
EAT = 1.0                         # выедено не меньше стольких его размеров
REFILL = 0.5                      # текущий размер к максимальному
MIN_LEVELS = 5                    # меньше уровней — медиана бессмысленна


class Side:
    """Отслеживание одного кандидата на одной стороне."""

    def __init__(self):
        self.price = None
        self.since = 0.0
        self.peak = 0.0
        self.eaten = 0.0
        self.size = 0.0
        self.held = 0
        self.pierced = False

    def reset(self, price, size, now):
        self.price, self.since = price, now
        self.peak = self.size = size
        self.eaten = 0.0
        self.held = 0
        self.pierced = False

    def state(self):
        return {"price": self.price, "held": self.held,
                "size": round(self.size, 2), "peak": round(self.peak, 2),
                "eaten": round(self.eaten, 2),
                "eaten_x": (round(self.eaten / self.peak, 2)
                            if self.peak > 0 else None),
                "refill": (round(self.size / self.peak, 2)
                           if self.peak > 0 else None)}


def biggest(levels, best, noise, long):
    """Самый крупный по нотионалу уровень рядом с ценой.

    Возвращает `(цена, нотионал, медиана нотионала, сколько уровней)`.
    Медиана считается по всем видимым уровням стороны, а не по окну:
    окно узкое, и медиана по нему мерила бы сама себя.
    """
    if not levels or not noise or noise <= 0:
        return None
    vals = [(p, p * q) for p, q in levels.items() if q > 0]
    if len(vals) < MIN_LEVELS:
        return None
    med = median([v for _, v in vals])
    lo, hi = best - NEAR * noise, best + NEAR * noise
    near = [(p, v) for p, v in vals if lo <= p <= hi]
    if not near:
        return None
    p, v = max(near, key=lambda x: x[1])
    return p, v, med, len(vals)


class Tracker:
    """Поглощение по обеим сторонам одного инструмента."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.by = {True: Side(), False: Side()}   # True — бид (лонг)
        self.diag = {True: {}, False: {}}

    def step(self, bids, asks, noise, sec, now):
        """Шаг на новом снимке книги.

        `sec` — только что закрытая секунда ленты
        `(t, buy_qv, sell_qv, high, low, close)`; из неё берётся
        агрессия, которую уровень принял на себя. Без неё условие
        «выедают» посчитать нечем, и шаг проходит вхолостую.
        """
        if not bids or not asks:
            return
        best_b, best_a = max(bids), min(asks)
        for long in (True, False):
            side = self.by[long]
            found = biggest(bids if long else asks,
                            best_b if long else best_a, noise, long)
            if found is None:
                side.reset(None, 0.0, now)
                self.diag[long] = {"why": "уровней мало или шум неизвестен"}
                continue
            price, notional, med, n = found
            big = notional >= BIG * med if med > 0 else False
            if not big or side.price != price:
                if big:
                    side.reset(price, notional, now)
                else:
                    side.reset(None, 0.0, now)
            else:
                side.held += 1
                side.size = notional
                side.peak = max(side.peak, notional)
                if sec is not None:
                    # Агрессия приписывается уровню, когда цена секунды
                    # до него дотянулась: иначе засчитывались бы сделки,
                    # прошедшие в другом конце стакана.
                    reach = (sec[4] <= price) if long else (sec[3] >= price)
                    if reach:
                        side.eaten += sec[2] if long else sec[1]
                    # Пробой виден по ленте, а не по книге: у бида лучшая
                    # цена по построению не бывает ниже уровня, который в
                    # этом биде и лежит, — проверка по книге была бы
                    # недостижимой. Сделка НИЖЕ уровня означает, что его
                    # выели, а не выдержали.
                    if (sec[4] < price) if long else (sec[3] > price):
                        side.pierced = True
            self.diag[long] = self._verdict(long, price, notional, med, n)

    def _verdict(self, long, price, notional, med, n):
        s = self.by[long]
        d = {"price": price, "big_x": round(notional / med, 2) if med else None,
             "levels": n, "held": s.held,
             "eaten_x": (round(s.eaten / s.peak, 2) if s.peak > 0 else None),
             "refill": (round(s.size / s.peak, 2) if s.peak > 0 else None),
             "ok": False, "why": ""}
        if s.price is None:
            d["why"] = f"не крупный ({d['big_x']}× при нужных {BIG})"
            return d
        if s.held < HOLD:
            d["why"] = f"стоит {s.held} с при нужных {HOLD}"
            return d
        if s.peak <= 0 or s.eaten < EAT * s.peak:
            d["why"] = (f"выедено {d['eaten_x']}× при нужных {EAT}")
            return d
        if s.pierced:
            d["why"] = "цена прошла сквозь уровень"
            return d
        if s.size < REFILL * s.peak:
            d["why"] = f"не восполнен ({d['refill']} при нужных {REFILL})"
            return d
        d["ok"] = True
        d["why"] = "поглощение"
        return d

    def signal(self):
        """Сторона, на которой поглощение подтверждено, или `None`."""
        for long in (True, False):
            d = self.diag.get(long) or {}
            if d.get("ok"):
                return long, d["price"], d
        return None
