#!/usr/bin/env python3
"""
Календарь торговых дней NYSE 2021–2026 — кодом, а не списком.

Зачем он механике
-----------------

Фонд с дневным целевым плечом считает стоимость пая к ЗАКРЫТИЮ
американского рынка. Значит «последний час» существует ровно в те дни,
когда рынок закрывается в 16:00 Нью-Йорка, и не существует в выходные, в
праздники и — отдельная категория — в дни ранней сессии, когда пай
считают к 13:00, а не к 16:00. Смешать ранний день с обычным значит
мерить час, в котором фонд уже не торгует.

Четыре категории, и ни одна не сваливается в другую:

    TRADE    полная сессия, закрытие 16:00 ET
    EARLY    ранняя сессия, закрытие 13:00 ET (13:00 — не 16:00)
    HOLIDAY  рынок закрыт, будний день
    WEEKEND  суббота и воскресенье

Правила, а не таблица — намеренно. Таблица на шесть лет, набранная
руками, есть шестьдесят строк, каждую из которых нельзя проверить
иначе как глазами; правило проверяется тем, что даёт ИЗВЕСТНУЮ дату
(`test_etf_rebal.py` держит литералы на каждый год). Исключение одно и
правилом не выводится — день национального траура; такие дни
объявляются биржей и живут списком с названной причиной.

Источник правил — регламент NYSE:

* Новый год — 1 января; попал на воскресенье, наблюдается 2 января;
  попал на субботу — НЕ наблюдается (биржа не переносит его на
  31 декабря прошлого года).
* День Мартина Лютера Кинга — третий понедельник января.
* День рождения Вашингтона — третий понедельник февраля.
* Страстная пятница — пятница перед католической Пасхой.
* День памяти — последний понедельник мая.
* Джунтинс — 19 июня, с 2022 года; суббота → пятница, воскресенье →
  понедельник.
* День независимости — 4 июля; суббота → 3 июля, воскресенье → 5 июля.
* День труда — первый понедельник сентября.
* День благодарения — четвёртый четверг ноября.
* Рождество — 25 декабря; суббота → 24 декабря, воскресенье →
  26 декабря.

Ранняя сессия (13:00 ET):

* 3 июля, когда 4 июля — вторник, среда, четверг или пятница (иначе
  либо выходной рядом, либо сам 3 июля уже праздник);
* пятница после Дня благодарения — всегда;
* 24 декабря, когда оно приходится на понедельник–четверг (в пятницу
  оно либо само праздник, либо выходной).

Только стандартная библиотека.
"""

import datetime as dt

TRADE = "trade"
EARLY = "early"
HOLIDAY = "holiday"
WEEKEND = "weekend"

# Закрытие полной сессии и ранней, часы Нью-Йорка.
CLOSE_H = 16
EARLY_CLOSE_H = 13

# Годы, на которые календарь объявлен. Дата вне этого диапазона —
# ОТКАЗ, а не «наверное, торговый день»: молчаливая экстраполяция
# календаря на год, чьи правила не сверены, есть выдуманный день.
FIRST_YEAR = 2020
LAST_YEAR = 2026

# Внеплановые закрытия: объявляются биржей, правилом не выводятся.
# Каждая строка — дата и причина; причина нужна, чтобы день нельзя
# было добавить «на всякий случай».
SPECIAL_CLOSED = {
    dt.date(2025, 1, 9): "национальный траур по Дж. Картеру",
}


def easter(year):
    """Католическая Пасха (анонимный григорианский алгоритм)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def nth_weekday(year, month, weekday, n):
    """n-й `weekday` (0 = понедельник) месяца; n < 0 — считая с конца."""
    if n > 0:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(days=7 * (n - 1))
    if month == 12:
        last = dt.date(year, 12, 31)
    else:
        last = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    last -= dt.timedelta(days=(last.weekday() - weekday) % 7)
    return last - dt.timedelta(days=7 * (-n - 1))


def _observed(d):
    """Перенос праздника с выходного: суббота → пятница, воскресенье →
    понедельник. Новый год пользуется своим правилом и сюда не идёт."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def holidays(year):
    """Полные закрытия NYSE в году: {дата: имя}."""
    out = {}
    jan1 = dt.date(year, 1, 1)
    # Суббота — биржа НЕ переносит Новый год на 31 декабря; такой год
    # начинается обычным торговым понедельником 3 января.
    if jan1.weekday() != 5:
        out[jan1 + dt.timedelta(days=1) if jan1.weekday() == 6 else jan1] = \
            "Новый год"
    out[nth_weekday(year, 1, 0, 3)] = "День Мартина Лютера Кинга"
    out[nth_weekday(year, 2, 0, 3)] = "День рождения Вашингтона"
    out[easter(year) - dt.timedelta(days=2)] = "Страстная пятница"
    out[nth_weekday(year, 5, 0, -1)] = "День памяти"
    if year >= 2022:
        out[_observed(dt.date(year, 6, 19))] = "Джунтинс"
    out[_observed(dt.date(year, 7, 4))] = "День независимости"
    out[nth_weekday(year, 9, 0, 1)] = "День труда"
    out[nth_weekday(year, 11, 3, 4)] = "День благодарения"
    out[_observed(dt.date(year, 12, 25))] = "Рождество"
    for d, why in SPECIAL_CLOSED.items():
        if d.year == year:
            out[d] = why
    return out


def early_closes(year):
    """Дни ранней сессии (13:00 ET) в году: {дата: имя}."""
    out = {}
    hol = holidays(year)
    jul4 = dt.date(year, 7, 4)
    if jul4.weekday() in (1, 2, 3, 4):        # вторник–пятница
        out[dt.date(year, 7, 3)] = "канун Дня независимости"
    out[nth_weekday(year, 11, 3, 4) + dt.timedelta(days=1)] = \
        "пятница после Дня благодарения"
    dec24 = dt.date(year, 12, 24)
    if dec24.weekday() <= 3:                 # понедельник–четверг
        out[dec24] = "канун Рождества"
    # Праздник сильнее ранней сессии: 3 июля 2026 — наблюдаемый День
    # независимости, и рано закрываться в него уже нечему.
    return {d: n for d, n in out.items()
            if d not in hol and d.weekday() < 5}


class Calendar:
    """Категория каждого дня в объявленном диапазоне лет.

    Категория спрашивается методом, а не полем словаря по умолчанию:
    вопрос о дне вне объявленных лет обязан быть ОТКАЗОМ. Словарь с
    `get(d, TRADE)` молча объявил бы 2027 год торговым целиком.
    """

    def __init__(self, first_year=FIRST_YEAR, last_year=LAST_YEAR):
        self.first_year, self.last_year = first_year, last_year
        self.hol, self.early = {}, {}
        for y in range(first_year, last_year + 1):
            self.hol.update(holidays(y))
            self.early.update(early_closes(y))
        self._sessions = None

    def kind(self, d):
        if not (self.first_year <= d.year <= self.last_year):
            raise ValueError(
                f"календарь объявлен на {self.first_year}–{self.last_year}, "
                f"а спрошен {d}: правила года не сверены")
        if d.weekday() >= 5:
            return WEEKEND
        if d in self.hol:
            return HOLIDAY
        if d in self.early:
            return EARLY
        return TRADE

    def close_hour(self, d):
        """Час закрытия сессии по Нью-Йорку; у неторгового дня — прочерк."""
        k = self.kind(d)
        if k == EARLY:
            return EARLY_CLOSE_H
        if k == TRADE:
            return CLOSE_H
        return None

    def why(self, d):
        """Почему день неторговый: имя праздника или имя ранней сессии."""
        return self.hol.get(d) or self.early.get(d)

    def sessions(self):
        """Все дни с сессией (TRADE и EARLY) по порядку."""
        if self._sessions is None:
            out, d = [], dt.date(self.first_year, 1, 1)
            end = dt.date(self.last_year, 12, 31)
            while d <= end:
                if self.kind(d) in (TRADE, EARLY):
                    out.append(d)
                d += dt.timedelta(days=1)
            self._sessions = out
        return self._sessions

    def prev_session(self, d):
        """Предыдущий день с сессией; до начала диапазона — прочерк."""
        s = self.sessions()
        import bisect
        i = bisect.bisect_left(s, d)
        return s[i - 1] if i > 0 else None

    def days(self, lo, hi, kinds):
        """Дни диапазона [lo, hi] названных категорий, по порядку."""
        out, d = [], lo
        while d <= hi:
            if self.kind(d) in kinds:
                out.append(d)
            d += dt.timedelta(days=1)
        return out


def main():
    """Печать календаря — чтобы правило можно было прочитать глазами."""
    cal = Calendar()
    for y in range(cal.first_year, cal.last_year + 1):
        hol = sorted(holidays(y).items())
        ear = sorted(early_closes(y).items())
        n = len([d for d in cal.days(dt.date(y, 1, 1), dt.date(y, 12, 31),
                                     (TRADE,))])
        print(f"{y}: полных сессий {n}, праздников {len(hol)}, "
              f"ранних {len(ear)}")
        for d, name in hol:
            print(f"    праздник  {d} {d.strftime('%a')}  {name}")
        for d, name in ear:
            print(f"    ранняя    {d} {d.strftime('%a')}  {name}")


if __name__ == "__main__":
    main()
