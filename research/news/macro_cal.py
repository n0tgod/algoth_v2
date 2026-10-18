#!/usr/bin/env python3
"""Календарь событий для судьи (спека 19 §4, E5); имя не calendar.py — перекрыло бы модуль Python: даты, которые владелец может проверить.

Источник каждой даты назван рядом с ней; даты взяты с официальных страниц
18.10.2026, не по памяти. Время — UTC: решение ФРС в 14:00 по Нью-Йорку,
CPI в 08:30 по Нью-Йорку; смещение Нью-Йорка от UTC считается по правилу
США (летнее время со второго воскресенья марта до первого воскресенья
ноября), а не вписывается руками.

Экспирации опционов Deribit — не список, а правило площадки: последняя
пятница месяца, 08:00 UTC; квартальные — март, июнь, сентябрь, декабрь.

Ряд дополняется руками: новая дата — строка в FOMC или CPI с источником.
"""
from datetime import date, datetime, timedelta, timezone

FOMC_SRC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
CPI_SRC = "https://www.bls.gov/schedule/news_release/cpi.htm"

# день решения (второй день заседания); «*» на странице ФРС — с прогнозами (SEP)
FOMC = [("2026-10-28", False), ("2026-12-09", True),
        ("2027-01-27", False), ("2027-03-17", True), ("2027-04-28", False),
        ("2027-06-09", True), ("2027-07-28", False), ("2027-09-15", True),
        ("2027-10-27", False), ("2027-12-08", True)]
# день выхода CPI и месяц, за который
CPI = [("2026-11-10", "2026-10"), ("2026-12-10", "2026-11"), ("2027-01-13", "2026-12"),
       ("2027-02-11", "2027-01"), ("2027-03-10", "2027-02")]


def _nth_sunday(y, m, n):
    d = date(y, m, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def ny_offset_h(d):
    """Смещение Нью-Йорка от UTC в часах на дату d: −4 летом, −5 зимой."""
    return -4 if _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1) else -5


def ny_to_utc(day, hh, mm):
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc) - timedelta(hours=ny_offset_h(d))


def last_friday(y, m):
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - 4) % 7)


def events(start, end):
    """События в [start, end) — список словарей по возрастанию времени."""
    out = []
    for day, sep in FOMC:
        t = ny_to_utc(day, 14, 0)
        out.append({"t": t, "kind": "fomc", "title": "FOMC rate decision" + (" + projections" if sep else ""),
                    "src": FOMC_SRC})
    for day, ref in CPI:
        out.append({"t": ny_to_utc(day, 8, 30), "kind": "cpi", "title": f"US CPI for {ref}", "src": CPI_SRC})
    y, m = start.year, start.month
    while date(y, m, 1) <= end.date():
        d = last_friday(y, m)
        q = m in (3, 6, 9, 12)
        out.append({"t": datetime(d.year, d.month, d.day, 8, 0, tzinfo=timezone.utc), "kind": "expiry",
                    "title": ("quarterly" if q else "monthly") + " Deribit options expiry",
                    "src": "Deribit rule: last Friday of the month, 08:00 UTC"})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted((e for e in out if start <= e["t"] < end), key=lambda e: e["t"])


def upcoming(now, hours=48):
    return [dict(e, t=e["t"].strftime("%Y-%m-%dT%H:%MZ"))
            for e in events(now, now + timedelta(hours=hours))]
