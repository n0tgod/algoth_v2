#!/usr/bin/env python3
"""Проверки сверки ряда funding с площадкой.

Кусаются: окно берётся ровно то, в котором жила позиция; совпадение
объявляется по ЧИСЛУ точек и сумме ставок, а не по факту ответа; лишняя
точка в нашем ряду ломает сверку; отказ площадки — причина словами, а не
«сошлось».
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import fund_probe as FP                                       # noqa: E402

H = 3600.0
T0 = 1786320000.0


class _Api:
    """Площадка-подделка: отвечает ровно тем, что ей положили."""
    CATEGORY = "linear"

    def __init__(self, interval=60, rows=None, fail=False):
        self.interval, self.rows, self.fail = interval, rows or [], fail

    def api_get(self, path, params, key):
        if self.fail:
            raise RuntimeError("нет сети")
        return {"list": [{"fundingInterval": self.interval}]}

    def collect_funding_symbol(self, symbol, d0, d1):
        # Отказ площадки — отказ ОБОИХ запросов: молчащий эндпоинт
        # истории при живом справочнике был бы другим случаем, и
        # проверка ловила бы не то, что называет.
        if self.fail:
            raise RuntimeError("нет сети")
        from datetime import datetime, timezone
        return [(datetime.fromtimestamp(t, timezone.utc).isoformat(), r)
                for t, r in self.rows]


def _ctx(points):
    t = np.asarray([int(x[0] * 1000) for x in points], dtype=np.int64)
    r = np.asarray([x[1] for x in points], dtype=float)
    return {"funding": {"A": (t, r)}, "to_asset": {"AAAUSDT": "A"}}


def test_window_and_match_are_decided_by_numbers():
    pts = [(T0 + i * H, -0.001) for i in range(24)]
    ctx = _ctx(pts + [(T0 - 5 * H, -0.5)])      # точка ВНЕ окна не в счёт
    api = _Api(interval=60, rows=pts)
    got = FP.compare([{"sym": "AAAUSDT", "t0": T0, "t1": T0 + 24 * H}],
                     ctx, api=api, log=lambda *a: None)[0]
    assert got["ours"]["n"] == 24 and got["venue"]["n"] == 24, got
    assert got["interval_min"] == 60 and got["match"] is True, got
    assert abs(got["ours"]["sum"] + 0.024) < 1e-9, got["ours"]
    print(f"ok  окно взято ровно позиции: {got['ours']['n']} точек, "
          f"интервал площадки {got['interval_min']} мин, сошлось")


def test_an_extra_point_of_ours_breaks_the_match():
    pts = [(T0 + i * H, -0.001) for i in range(24)]
    ctx = _ctx(pts + [(T0 + 0.5 * H, -0.001)])   # лишняя точка ВНУТРИ окна
    api = _Api(interval=60, rows=pts)
    got = FP.compare([{"sym": "AAAUSDT", "t0": T0, "t1": T0 + 24 * H}],
                     ctx, api=api, log=lambda *a: None)[0]
    assert got["ours"]["n"] == 25 and got["venue"]["n"] == 24, got
    assert got["match"] is False, got
    print("ok  лишняя точка в нашем ряду ломает сверку — контроль кусается")


def test_venue_silence_is_a_reason_not_a_match():
    pts = [(T0 + i * H, -0.001) for i in range(3)]
    got = FP.compare([{"sym": "AAAUSDT", "t0": T0, "t1": T0 + 24 * H}],
                     _ctx(pts), api=_Api(fail=True),
                     log=lambda *a: None)[0]
    assert got["match"] is False and got["why"], got
    txt = FP.report({"cases": [got], "n": 1, "match": 0})
    assert "площадка не ответила" in txt, txt[:300]
    print(f"ok  отказ площадки назван словами: «{got['why'][:40]}…», и это "
          "не «сошлось»")


if __name__ == "__main__":
    for t in (test_window_and_match_are_decided_by_numbers,
              test_an_extra_point_of_ours_breaks_the_match,
              test_venue_silence_is_a_reason_not_a_match):
        t()
    print("\nвсе 3 проверки прошли")
