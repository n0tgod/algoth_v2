#!/usr/bin/env python3
"""Правила 03.10 у безопасной короткой книги: билет 0.5.

Кусаются: доля билета 0.5 у `safe_h` И у короткой стороны `pair_safe`
(одно правило, два места показа), билет кассы ровно вдвое, но не ниже
биржевого пола; пол безопасной остаётся 0.10 (0.75 отвергнут реплеем) и
подпись кэша билета не несёт; версии h24 4 / pair 8 с 2026-10-03, строка
прежней версии в счёт не идёт; текст на вкладке называет долю и её день.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_short as S                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402


def test_ticket_half_for_safe_and_its_pair_side_not_below_exchange_floor():
    assert R.SHORT_SHARE["safe_h"] == 0.5 and R.SHORT_SHARE["pair_safe"] == 0.5
    assert R.SHORT_SHARE["optimal_h"] == 0.25 and R.SHORT_SHARE["aggr_h"] == 0.25
    full = R.ticket(10000, "safe_h")
    assert abs(R.ticket_in("safe_h", "safe_h", 10000) - max(R.floor_of("safe_h"), full * 0.5)) < 1e-9
    assert abs(R.ticket_in("pair_safe", "safe_h", 10000) - max(R.floor_of("safe_h"), full * 0.5)) < 1e-9
    # на $1k билет стоит на биржевом полу — доля не кусается, и это не ошибка
    assert R.ticket_in("safe_h", "safe_h", 1000) >= R.floor_of("safe_h")
    print(f"ok  билет безопасной {full:g} → {R.ticket_in('safe_h', 'safe_h', 10000):g} у книги и у стороны общего счёта")


def test_floor_of_safe_stays_and_the_cache_signature_is_untouched_by_the_ticket():
    """Пол 0.75 у безопасной ОТВЕРГНУТ реплеем 03.10 (+9.9 % против +31.0 %,
    просадка −14.9 против −11.3): пол остаётся 0.10, подпись кэша прежняя —
    билет исходов не меняет, реплея не будет."""
    assert R.floor_frac_of("safe_h", D2.FLOOR_FRAC) == 0.10, R.FLOOR_FRAC_BY_BOOK
    assert R.floor_frac_of("optimal_h", D2.FLOOR_FRAC) == 0.50 and R.floor_frac_of("aggr_h", D2.FLOOR_FRAC) == 0.50
    sig = S.cache_sig()
    assert sig["floor"] == {"aggr_h": 0.50, "optimal_h": 0.50, "safe_h": 0.10}, sig["floor"]
    assert "share" not in sig and "ticket" not in sig, sig
    print("ok  пол безопасной 0.10 на месте; подпись кэша билета не несёт — реплея от смены билета нет")


def test_versions_day_and_page_text():
    assert R.FAMILY_RULES == {"pair": 8, "h24": 4}, R.FAMILY_RULES
    assert R.FAMILY_SINCE == {"pair": "2026-10-03", "h24": "2026-10-03"}, R.FAMILY_SINCE
    assert not R.is_current({"rules": R.RULES, "book_rules": 3, "ruler": "safe_h"})
    assert R.is_current({"rules": R.RULES, "book_rules": 4, "ruler": "safe_h"})
    assert not R.is_current({"rules": R.RULES, "book_rules": 7, "ruler": "pair_safe"})
    plain = R.RULERS["safe_h"]["plain"]
    assert "берёт 0.5 своего билета (правило 2026-10-03)" in plain, plain[-400:]
    assert "берёт 0.5 своего билета (правило 2026-10-03)" in R.RULERS["pair_safe"]["plain"]
    assert "берёт 0.25 своего билета (правило 2026-09-07)" in R.RULERS["pair_optimal"]["plain"]
    print("ok  версии h24 4 / pair 8 с 2026-10-03; прежние строки не в счёт; вкладка называет билет и дату пола")


if __name__ == "__main__":
    for t in (test_ticket_half_for_safe_and_its_pair_side_not_below_exchange_floor,
              test_floor_of_safe_stays_and_the_cache_signature_is_untouched_by_the_ticket,
              test_versions_day_and_page_text):
        t()
    print("\nвсе 3 проверки прошли")
