#!/usr/bin/env python3
"""Страница состояния рынка (`web.market_state_json`): нет файла — причина
словами, не пустой объект; возраст считается от `computed_at`; порог
тревоги 2 ч; повреждённый файл — своя причина. Подделка — литерал."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))
import web as W                                              # noqa: E402


def test_market_state_json_ages_and_names_absence():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "latest.json")
        r = W.market_state_json(p)
        assert r["error"].startswith("срез не записан"), r
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"computed_at": "2026-10-18T10:00:00Z", "names": {}}, f)
        assert json.load(open(p))["computed_at"] == "2026-10-18T10:00:00Z"
        now = 1792317600 + 600                                   # 10:10 UTC того же дня
        r = W.market_state_json(p, now=now)
        assert r["age_s"] == 600 and r["stale"] is False, r
        r = W.market_state_json(p, now=now + 2 * 3600)
        assert r["stale"] is True and r["age_s"] == 7800
        with open(p, "w", encoding="utf-8") as f:
            f.write("{не json")
        assert W.market_state_json(p)["error"].startswith("срез повреждён")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"computed_at": "2026-10-18T10:00:00Z"}, f)
        assert W.news_state_json(p, now=now + 30 * 60)["stale"] is False
        assert W.news_state_json(p, now=now + 50 * 60)["stale"] is True, "новости: порог 45 мин, не 2 ч"
        assert W.market_state_json(p, now=now + 50 * 60)["stale"] is False
    assert '"/market-page", "market", "рынок"' in W.NAVJS, "страница есть в меню"
    assert "/news_state?k=" in W.MARKETPAGE and "renderNews" in W.MARKETPAGE
    assert "/gate_state?k=" in W.MARKETPAGE and "renderGate" in W.MARKETPAGE
    with tempfile.TemporaryDirectory() as d:
        g = W.gate_state_json(d)
        assert g["error"].startswith("срез не записан") and g["books"]["error"] == "ветки ещё не посчитаны"
        json.dump({"computed_at": "2026-10-18T10:00:00Z", "today": {}}, open(os.path.join(d, "latest.json"), "w"))
        json.dump({"days": 1.0, "books": {}}, open(os.path.join(d, "AI-gate-books.json"), "w"))
        g = W.gate_state_json(d, now=1792317600 + 50 * 60)
        assert g["stale"] is True and g["books"]["days"] == 1.0, "судья: порог 45 мин, ветки рядом"
    assert "/market_state?k=" in W.MARKETPAGE and 'navMount("/market-page")' in W.MARKETPAGE
    print("ok  страница: нет файла — причина, возраст от computed_at, тревога > 2 ч, в меню есть")


if __name__ == "__main__":
    test_market_state_json_ages_and_names_absence()
    print("\nвсе 1 проверки прошли")
