#!/usr/bin/env python3
"""
Синтетические сводки часов: заложенный сигнал, который цикл обязан найти.

Зачем это отдельный модуль, а не кусок теста
--------------------------------------------

Его зовут двое: сквозной тест цикла и показ `train.py --demo`. Вторая
копия генератора однажды разошлась бы с первой, и тогда «на демо
работает, а в тестах нет» объяснялось бы часами. В проекте это правило
уже стоило урока: одна `normalize()`, одна `funding.py`, одно ядро
`t3_brackets` для страницы и отчётов.

Устройство сигнала
------------------

Дельта ленты часа `t` предсказывает доходность часа `t+1`. Сила выбрана
правдоподобной (IC около 0.2, а не 0.5) намеренно: шум проекции
канарейки растёт вместе с настоящим сигналом, и на перегретой синтетике
канарейка кричала бы без всякой течи.

Данные фальшивые и годятся ровно для одного — показать ФОРМУ вывода и
проверить, что конвейер её производит. Измерением они не являются ни в
какой части.
"""

import json
import os
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
import sys                                                # noqa: E402
sys.path.insert(0, HERE)
from book import BANDS                                    # noqa: E402


def write_summaries(d, S=36, D=260, seed=5, start="2026-08-01-00"):
    """Разложить синтетические сводки по каталогу `d`."""
    r = np.random.default_rng(seed)
    t0 = time.mktime(time.strptime(start, "%Y-%m-%d-%H"))
    sig = r.normal(0, 1, (S, D))
    close = np.empty((S, D))
    close[:, 0] = 100.0
    for t in range(1, D):
        close[:, t] = close[:, t - 1] * (
            1 + 0.004 * sig[:, t - 1] * 0.22
            + r.normal(0, 0.004, S))
    for si in range(S):
        sym = f"S{si:02d}USDT"
        os.makedirs(os.path.join(d, sym), exist_ok=True)
        fh = {}
        for t in range(D):
            hour = datetime.fromtimestamp(t0 + t * 3600, timezone.utc)\
                .strftime("%Y-%m-%d-%H")
            day = hour[:10]
            buy = 1e6 * (1 + 0.4 * np.tanh(sig[si, t]))
            sell = 2e6 - buy
            row = {"hour": hour, "n_snap": 3600,
                   "mid_close": round(close[si, t], 6),
                   "mid_high": round(close[si, t] * 1.002, 6),
                   "mid_low": round(close[si, t] * 0.998, 6),
                   "spread_bp": 5.0, "upd": 100.0, "reach_bp": 60.0,
                   "best_b": 1e4, "best_a": 1e4,
                   "big_med": 1e5, "big_max": 2e5,
                   "n_trades": 500, "buy": round(buy, 2),
                   "sell": round(sell, 2),
                   "vol_max_1s": 1e4, "traded_secs": 1800,
                   "depth_eat_b": 2e5, "depth_eat_a": 2e5}
            for w in BANDS:
                row[f"bq_b{w}"] = 1e5
                row[f"bq_a{w}"] = 1e5
                row[f"cov_b{w}"] = 1.0
                row[f"cov_a{w}"] = 1.0
            f = fh.get(day)
            if f is None:
                f = fh[day] = open(os.path.join(d, sym, day + ".jsonl"),
                                   "a", encoding="utf-8")
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        for f in fh.values():
            f.close()
