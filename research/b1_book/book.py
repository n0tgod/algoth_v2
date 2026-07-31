#!/usr/bin/env python3
"""
Стакан: состояние, применение обновлений, снимок.

Почему это отдельный модуль без сети
------------------------------------

Здесь живёт единственная часть сборщика, где ошибка портит **все**
данные и ничем себя не выдаёт: поддержание книги по потоку изменений.
Пропущенное удаление уровня оставляет в стакане призрак, который потом
выглядит как «крупный стоит и не уходит» — то есть ровно как то
событие, ради которого всё затевается. Поэтому логика вынесена в чистые
функции и закрыта тестами, а сеть, файлы и переподключения — в
`collect.py`.

Что важно знать про поток Bybit
-------------------------------

Первое сообщение темы — **снимок** (`type: snapshot`), дальше идут
**изменения** (`type: delta`). В изменении цена с размером `0` означает
**снятие уровня**, а не нулевой объём. У каждого сообщения есть номер
`u`; если номер пришёл не следующим по порядку, часть потока потеряна —
книгу надо выбросить и переподписаться. Молчаливо продолжать нельзя:
книга разъедется с биржей, а по виду останется правдоподобной.

Что снимается
-------------

Раз в секунду: лучшие цены, ближние уровни лесенкой и накопленный объём
в полосах вокруг середины. Полосы — в долях цены, а не в шагах: у BTC
шаг 0.1 доллара на девяносто тысяч, у мелкого альта — единица
последнего знака, и в шагах полосы сравнивали бы разное.

Только стандартная библиотека.
"""

BANDS = (0.0005, 0.001, 0.0025, 0.005)   # ±0.05 %, 0.1 %, 0.25 %, 0.5 %
LADDER = 10                               # уровней лесенки для показа
# В ФАЙЛ пишется книга целиком, а не лесенка для глаз. Причина найдена
# вопросом владельца «можно ли прогнать прошлые сделки по новой
# логике»: правило по стакану считает «крупный» относительно ВСЕХ
# видимых уровней, и по обрезку в десять штук оно дало бы
# правдоподобные, но неверные числа. Запись, по которой нельзя
# воспроизвести решение, не является записью решения.
STORE_LADDER = 0                          # 0 — все уровни


class Book:
    """Одна сторона рынка по одному инструменту.

    Хранит цены как строки в исходном виде и как числа для арифметики:
    строка — то, что прислала биржа, и по ней уровни сходятся точно, без
    накопления ошибки округления при сравнении цен.
    """

    def __init__(self, symbol):
        self.symbol = symbol
        self.bids = {}                    # цена (float) -> размер (float)
        self.asks = {}
        self.u = None                     # номер последнего обновления
        self.ts = None                    # метка биржи, мс
        self.updates = 0                  # обновлений с прошлого снимка
        self.resets = 0                   # сколько раз книгу выбрасывали

    def clear(self):
        self.bids.clear()
        self.asks.clear()
        self.u = None

    @property
    def ready(self):
        return bool(self.bids) and bool(self.asks)

    def apply(self, msg):
        """Применить сообщение темы `orderbook`.

        Возвращает `True`, если сообщение применено, и `False`, если
        обнаружен разрыв нумерации — в этом случае книга очищена и
        вызывающему следует переподписаться.
        """
        kind = msg.get("type")
        data = msg.get("data") or {}
        u = data.get("u")
        if kind == "snapshot":
            self.clear()
            self._side(self.bids, data.get("b") or [])
            self._side(self.asks, data.get("a") or [])
            self.u = u
            self.ts = msg.get("ts")
            self.updates += 1
            return True
        if kind != "delta":
            return True
        if self.u is None:
            return True                   # снимка ещё не было — ждём
        if u is not None and self.u is not None and u != self.u + 1:
            # Разрыв: часть потока потеряна. Молчать нельзя — книга
            # разойдётся с биржей, оставаясь правдоподобной на вид.
            self.clear()
            self.resets += 1
            return False
        self._side(self.bids, data.get("b") or [])
        self._side(self.asks, data.get("a") or [])
        self.u = u
        self.ts = msg.get("ts")
        self.updates += 1
        return True

    @staticmethod
    def _side(book, rows):
        for row in rows:
            if len(row) < 2:
                continue
            price = float(row[0])
            size = float(row[1])
            if size == 0.0:
                # Ноль — СНЯТИЕ уровня, а не нулевой объём. Оставить его
                # в книге значит получить призрак, который потом читается
                # как «крупный стоит и не уходит».
                book.pop(price, None)
            else:
                book[price] = size

    def best(self):
        if not self.ready:
            return None, None
        return max(self.bids), min(self.asks)

    def sample_view(self, ladder=LADDER, bands=BANDS):
        """То же, что `sample`, но БЕЗ обнуления счётчика обновлений.

        Страница наблюдения смотрит в ту же книгу, что и запись. Если бы
        показ пользовался `sample`, он сбрасывал бы счётчик, и в файлы
        уходило бы заниженное число обновлений — показ портил бы данные.
        """
        keep = self.updates
        out = self.sample(ladder, bands)
        self.updates = keep
        return out

    def sample(self, ladder=LADDER, bands=BANDS):
        """Снимок для записи: лучшие, лесенка и объём в полосах.

        Объём в полосах — в котируемой валюте (цена × размер), потому что
        сравнивать надо деньги, а не единицы базового актива.
        """
        if not self.ready:
            return None
        bid, ask = self.best()
        mid = (bid + ask) / 2.0
        bids = sorted(self.bids.items(), key=lambda x: -x[0])
        asks = sorted(self.asks.items(), key=lambda x: x[0])
        out = {
            "s": self.symbol, "ts": self.ts, "u": self.u,
            "bid": bid, "ask": ask,
            "bid_sz": self.bids[bid], "ask_sz": self.asks[ask],
            "upd": self.updates,
            "b": [[p, q] for p, q in (bids[:ladder] if ladder
                                        else bids)],
            "a": [[p, q] for p, q in (asks[:ladder] if ladder
                                        else asks)],
        }
        # Докуда книга вообще достаёт. Тема `orderbook.50` отдаёт полсотни
        # уровней, а не глубину в процентах, и у плотных инструментов все
        # они помещаются внутрь самой узкой полосы: у BTCUSDT полосы
        # ±0.05 и ±0.5 % давали одно и то же число, то есть четыре
        # колонки несли одну величину и выглядели измерением. Охват
        # докладывается числом, чтобы полосу шире него было видно.
        out["reach_b"] = round((mid - bids[-1][0]) / mid * 1e4, 1)
        out["reach_a"] = round((asks[-1][0] - mid) / mid * 1e4, 1)
        for w in bands:
            lo, hi = mid * (1 - w), mid * (1 + w)
            out[f"bq{w}"] = round(sum(p * q for p, q in bids if p >= lo), 2)
            out[f"aq{w}"] = round(sum(p * q for p, q in asks if p <= hi), 2)
        self.updates = 0
        return out


def parse_trades(msg):
    """Сделки темы `publicTrade` в компактный вид.

    Сторона — агрессора: это проверено на архиве ленты (96 % принтов
    `Buy` двигали цену вверх) и здесь берётся тем же соглашением.
    """
    out = []
    for t in msg.get("data") or []:
        try:
            out.append({"ts": int(t["T"]), "s": t["s"],
                        "side": 1 if t["S"] == "Buy" else -1,
                        "p": float(t["p"]), "v": float(t["v"])})
        except (KeyError, ValueError, TypeError):
            continue
    return out
