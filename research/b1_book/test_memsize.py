#!/usr/bin/env python3
"""Проверка переписи памяти: оценка размеров, выборка, циклы, трассировка."""
import os
import sys
import tempfile
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memsize as M  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name + ("" if cond else f": {detail}"))
    if not cond:
        FAILED.append(name)


def main():
    # 1. Список одинаковых чисел: выборка экстраполирует в пределах 5 %.
    xs = [10 ** 6 + k for k in range(20000)]
    true = sys.getsizeof(xs) + sum(sys.getsizeof(x) for x in xs)
    est = M.deep_size(xs)
    check("список 20 000 чисел — оценка в 5 % от точной", abs(est - true) / true < 0.05,
          f"{est} vs {true}")
    # 2. Кольцо кортежей против массива: отношение как на стенде (≈ 4×).
    # разные float-объекты в каждом кортеже — как у живой ленты
    dq = deque((1791200000 + k, 1.5 + k, 2.5 + k, 100.1 + k * 1e-3,
                99.9 - k * 1e-3, 100.0 + k * 1e-4) for k in range(5000))
    arr = np.zeros((5000, 6), dtype=np.float64)
    r = M.deep_size(dq) / M.deep_size(arr)
    check("кортежи дороже массива в 3–6 раз", 3 < r < 6, f"{r:.2f}")
    check("numpy — по nbytes", abs(M.deep_size(arr) - arr.nbytes) < 200)
    # 3. Циклы и общие объекты не считаются дважды и не зацикливают.
    a = []
    a.append(a)
    check("список, содержащий себя, меряется конечно", M.deep_size(a) < 1000)
    shared = [0.5] * 1000
    pair = (shared, shared)
    check("общий объект считается один раз",
          M.deep_size(pair) < 2 * M.deep_size(shared) + 200)
    # 4. Объекты со __slots__ и __dict__.
    sys.path.insert(0, HERE)
    import signals as SG
    ring = SG.SecRing(1000)
    check("SecRing меряется массивом (nbytes + мелочь)",
          abs(M.deep_size(ring) - ring.nbytes) < 500, str(M.deep_size(ring)))
    class O:
        def __init__(self):
            self.big = list(range(3000))
    check("объект с __dict__ меряется с содержимым", M.deep_size(O()) > 3000 * 28)
    # 5. Перепись на подставном сборщике.
    import collect as C
    root = tempfile.mkdtemp()
    c = C.Collector(["AAAUSDT", "BBBUSDT"], [], root, lambda m: None, paper=True)
    for k in range(40):
        c.sig.by["AAAUSDT"].on_trade({"p": 1.0 + k * 1e-3, "v": 2.0, "side": 1,
                                      "ts": (1791200000 + k) * 1000})
    rep = M.census(c)
    parts = rep["parts"]
    check("перепись несёт RSS, сумму частей и неучтённое",
          isinstance(rep["rss_mb"], int) and rep["sum_mb"] >= 0
          and "unaccounted_mb" in rep, str({k: rep[k] for k in ("rss_mb", "sum_mb")}))
    ring_row = parts["  из них кольца секунд (точно, nbytes)"]
    check("кольца секунд посчитаны точно: 39 секунд, 2 кольца × 14400×48 байт",
          ring_row["n"] == 39 and abs(ring_row["mb"] - 2 * 14400 * 48 / 2 ** 20) < 0.05,
          str(ring_row))
    check("детектор — самая большая часть у свежего сборщика",
          max(parts, key=lambda k: parts[k]["mb"]).startswith("signals.by"),
          str(sorted(((v["mb"], k) for k, v in parts.items()), reverse=True)[:3]))
    rep2 = c.mem_report(trace="stop")
    check("маршрут сборщика отдаёт перепись и состояние трассировки",
          "parts" in rep2 and rep2["trace"].get("ok") is True, str(rep2.get("trace")))
    deep = M.census(c, deep=True)
    check("глубокая перепись несёт гистограмму типов",
          deep["gc_objects"] > 1000 and len(deep["types_top"]) == 25)
    # 6. Трассировка: start → top → stop; отказ при тесноте; авто-стоп.
    st = M.trace_control("start", rss=100, now=1000.0)
    junk = [bytearray(1 << 16) for _ in range(20)]
    top = M.trace_control("top", rss=100, now=1001.0)
    check("трассировка включается и показывает места выделений",
          st["ok"] and top["ok"] and top["top"] and "where" in top["top"][0], str(top)[:200])
    stop = M.trace_control("stop")
    check("остановлена", stop["ok"] and not M.trace_state()["on"])
    deny = M.trace_control("start", rss=3000, now=2000.0)
    check("при RSS выше предела — отказ, не включение", deny["ok"] is False and "отказ" in deny["note"])
    M.trace_control("start", rss=100, now=5000.0)
    late = M.trace_control("top", rss=100, now=5000.0 + M.TRACE_AUTO_STOP_SEC + 1)
    check("забытая трассировка гасится сама при обращении",
          late["ok"] is False and "сама" in late["note"] and not M.trace_state()["on"], str(late))
    del junk
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
