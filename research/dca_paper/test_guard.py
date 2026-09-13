#!/usr/bin/env python3
"""Проверки охраны рынком — правила выхода коротких книг (спека 14 §13).

Кусаются: закрытая запись закрывается «рынком» на часе триггера СТРОГО
до своего выхода и не трогается, если вышла раньше; открытая закрывается
только в прожитом часе; час без волны триггером не бывает и посчитан;
запись без отметок не трогается; порог — у трёх коротких книг и у
короткой стороны общего счёта, у длинных нет; версии семейств и день
смены объявлены, строка прежней версии в счёт не идёт; правило сказано
на странице книги; сквозной проход через сводки закрывает позицию при
подсаженной волне и молчит на плоской; подпись кэша охрану не несёт
намеренно.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wave as WV                                             # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import test_tail_screen as TT                                 # noqa: E402

H = 3600.0
AT = 1_789_002_000.0                         # граница часа: 496945 × 3600


class FakeMarket(WV.Market):
    """Волна по номеру часа от входа — без сводок; логика k_star настоящая."""

    def __init__(self, waves):
        super().__init__(hours=WV.Hours(root="/nonexistent"))
        self.waves = dict(waves)

    def wave(self, t0, t1):
        k = int(round((float(t1) - float(t0)) / H))
        w = self.waves.get(k)
        if w is None:
            self.wave_none += 1
        return w


def _rec(marks, state="closed", sym="AAAUSDT", exit="срок", lev=20.0):
    final = sum(d for _h, d in marks)
    return {"sym": sym, "at": AT, "exit_ts": AT + len(marks) * H, "side": "short",
            "lev": lev, "pnl": final, "pnl_net": final - 0.01, "exit": exit,
            "marks": marks, "entry_px": 100.0, "state": state}


def test_guard_closes_strictly_before_the_exit_and_only_in_lived_hours():
    steps = (0.05, -0.10, -0.05, 0.10, -0.30, -0.60)
    marks = [(AT + i * H, d) for i, d in enumerate(steps)]      # K = 6
    mkt = FakeMarket({1: 0.004, 2: None, 3: 0.021, 4: 0.03, 5: 0.05, 6: 0.06})
    out, st = WV.apply_guard([_rec(marks)], 2.0, mkt, kmax=23)
    r = out[0]
    assert r["exit"] == WV.GUARD_EXIT and len(r["marks"]) == 3, r["exit"]
    assert abs(r["pnl"] - (0.05 - 0.10 - 0.05)) < 1e-12 and r["state"] == "closed"
    assert r["exit_ts"] == AT + 3 * H - 1 and abs((r["pnl"] - r["pnl_net"]) - 0.01) < 1e-12
    assert st["closed_by_market"] == 1 and st["hours_no_wave"] == 1, st   # час 2 без волны посчитан
    # вышла на часе 3 сама — триггер на часе 3 уже «не строго до выхода»
    out2, st2 = WV.apply_guard([_rec(marks[:3], exit="пол")], 2.0, mkt, kmax=23)
    assert out2[0]["exit"] == "пол" and st2["closed_by_market"] == 0
    # открытая: отметки за 2 часа, триггер на часе 3 ещё не прожит — стоит открытой
    op = _rec(marks[:2], state="open")
    out3, st3 = WV.apply_guard([op], 2.0, mkt, kmax=23)
    assert out3[0]["state"] == "open" and st3["closed_by_market"] == 0
    # открытая с тремя прожитыми часами — закрывается на третьем
    out4, st4 = WV.apply_guard([_rec(marks[:3], state="open")], 2.0, mkt, kmax=23)
    assert out4[0]["state"] == "closed" and out4[0]["exit"] == WV.GUARD_EXIT
    assert st4["open_closed"] == 1
    # без отметок — не трогается и посчитана
    out5, st5 = WV.apply_guard([dict(_rec(marks), marks=[])], 2.0, mkt, kmax=23)
    assert out5[0]["exit"] == "срок" and st5["no_marks"] == 1
    # порог выше волны — ничего
    out6, st6 = WV.apply_guard([_rec(marks)], 10.0, mkt, kmax=23)
    assert out6[0]["exit"] == "срок" and st6["closed_by_market"] == 0
    print("ok  охрана: закрывает «рынком» строго до выхода, открытую — только в "
          "прожитом часе; час без волны и запись без отметок посчитаны")


def test_rule_is_declared_for_short_books_with_versions_and_page_text():
    for bk in ("safe_h", "optimal_h", "aggr_h"):
        assert R.wave_guard_of(bk) == 2.0, bk
    for pk in R.PAIR_ORDER:
        assert R.wave_guard_of(pk) == 2.0, pk          # короткая сторона общего счёта
    for lk in ("safe", "optimal", "aggr"):
        assert R.wave_guard_of(lk) is None, lk         # длинные не трогаются
    assert R.FAMILY_RULES == {"pair": 7, "h24": 3}, R.FAMILY_RULES
    assert R.FAMILY_SINCE == {"pair": "2026-09-13", "h24": "2026-09-13"}, R.FAMILY_SINCE
    # строка прежней версии в счёт не идёт, текущей — идёт
    old = {"rules": R.RULES, "book_rules": 2, "ruler": "safe_h"}
    new = {"rules": R.RULES, "book_rules": 3, "ruler": "safe_h"}
    assert not R.is_current(old) and R.is_current(new)
    assert not R.is_current({"rules": R.RULES, "book_rules": 6, "ruler": "pair_safe"})
    for k in ("safe_h", "pair_optimal"):
        plain = R.RULERS[k]["plain"]
        assert "охрана рынком" in plain and "≥ 2 %" in plain, (k, plain[-200:])
    assert "охрана рынком" not in R.RULERS["safe"]["plain"]
    print("ok  правило объявлено: порог 2 % у трёх коротких книг и короткой стороны "
          "общего счёта, версии h24 3 / pair 7 с 2026-09-13, прежние строки не в счёт, "
          "текст на вкладке")


def test_guard_shorts_reads_the_summaries_end_to_end():
    td = tempfile.mkdtemp()
    proxies = list(WV.PROXY[:6])
    start = AT - H                            # час решения — первый файл
    # цены прокси: час входа и час 1 — 100; с часа 2 — 100·(1+bump)
    def rows_of(bump):
        return lambda i: {"mid_close": 100.0 if i < 2 else 100.0 * (1 + bump)}
    for p in proxies:
        TT._write_hours(td, p, start, 6, rows_of(0.03))
    RP.reset_market()
    mkt = RP.market(root=td)
    marks = [(AT + i * H, -0.02) for i in range(5)]           # K = 5, срок
    said = []
    out, st = RP.guard_shorts([_rec(marks)], "safe_h", log=said.append, mkt=mkt)
    assert out[0]["exit"] == R.GUARD_EXIT and len(out[0]["marks"]) == 2, out[0]
    assert st["guard"] and st["pct"] == 2.0 and st["closed_by_market"] == 1, st
    assert any("охрана рынком" in x for x in said), said
    # плоский рынок — ничего; книга без порога — сквозь без слов
    td2 = tempfile.mkdtemp()
    for p in proxies:
        TT._write_hours(td2, p, start, 6, rows_of(0.0))
    RP.reset_market()
    out2, st2 = RP.guard_shorts([_rec(marks)], "safe_h", log=lambda *a: None,
                                mkt=RP.market(root=td2))
    assert out2[0]["exit"] == "срок" and st2["closed_by_market"] == 0
    out3, st3 = RP.guard_shorts([_rec(marks)], "safe", log=lambda *a: None)
    assert out3[0]["exit"] == "срок" and st3 == {"guard": False, "offered": 1}
    RP.reset_market()
    print("ok  сквозной проход: сводки → волна +3 % к часу 2 → позиция закрыта "
          "«рынком» на часе 2; плоский рынок — без изменений; длинной книге правила нет")


def test_cache_signature_does_not_carry_the_guard_on_purpose():
    sig = S.cache_sig()
    assert not any("guard" in str(k).lower() or "wave" in str(k).lower() for k in sig), sig
    # а исход позиции при этом другой — значит, версия семейства выросла
    assert R.FAMILY_RULES["h24"] >= 3
    print("ok  подпись кэша охрану не несёт (кэш хранит исход без охраны), "
          "версия семейства выросла")


if __name__ == "__main__":
    for t in (test_guard_closes_strictly_before_the_exit_and_only_in_lived_hours,
              test_rule_is_declared_for_short_books_with_versions_and_page_text,
              test_guard_shorts_reads_the_summaries_end_to_end,
              test_cache_signature_does_not_carry_the_guard_on_purpose):
        t()
    print("\nвсе 4 проверки прошли")
