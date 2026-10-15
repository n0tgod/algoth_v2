#!/usr/bin/env python3
"""Кэш минутных баров на диске (`sweep.read_bars(cache=…)`, 15.10): с кэшем
то же, что без него, бит в бит; второй вызов не читает принты закрытых
часов; дописанный час (другая подпись) считается заново; подложенный
pickle с верной подписью читается (контроль: кэш — источник), дописка
его вытесняет; файл имени держит не больше BARS_CACHE_KEEP_H часов.

    .venv/bin/python research/s9_sweep/test_bars_cache.py
"""
import json
import os
import pickle
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "b1_book"))
import sweep as SW                                            # noqa: E402
import store                                                  # noqa: E402

H = 3600


def hh(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d-%H")


def write_hour(d, sym, t, n=30, px=100.0):
    p = os.path.join(d, "trades", sym, f"{hh(t)}.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"ts": int((t + i * 60) * 1000), "p": px + i * 0.1, "v": 1.0 + i}) + "\n")
    return p


def main():
    d = tempfile.mkdtemp()
    cache = os.path.join(d, "cache")
    t0 = (int(time.time()) // H - 50) * H
    sym = "AUSDT"
    for k in range(4):
        write_hour(d, sym, t0 + k * H, px=100.0 + k)
    a0, a1 = t0 + 10 * 60, t0 + 3 * H + 20 * 60
    ref = SW.read_bars(d, sym, a0, a1)
    assert len(ref) > 100, len(ref)
    got1 = SW.read_bars(d, sym, a0, a1, cache=cache)
    assert got1 == ref and os.path.exists(os.path.join(cache, f"{sym}.pkl"))
    # второй вызов: принты закрытых часов не читаются — подменяем читателя
    real = store.read_hour
    calls = []

    def spy(dirpath, hour, log=None, parse=json.loads):
        calls.append(hour)
        return real(dirpath, hour, log, parse)
    store.read_hour = spy
    try:
        got2 = SW.read_bars(d, sym, a0, a1, cache=cache)
        assert got2 == ref and calls == [], calls
        # дописанный час — подпись другая, читается только он
        time.sleep(0.01)
        write_hour(d, sym, t0 + 3 * H, n=5, px=200.0)
        calls.clear()
        got3 = SW.read_bars(d, sym, a0, a1, cache=cache)
        assert calls == [hh(t0 + 3 * H)], calls
        assert got3 == SW.read_bars(d, sym, a0, a1), "с кэшем и без после дописки расходятся"
        assert got3 != ref, "дописка той же минуты меняет бары, а ответ тот же"
        # контроль: подделка с верной подписью читается
        cp = SW._bars_cache_path(cache, sym)
        with open(cp, "rb") as f:
            dd = pickle.load(f)
        key = hh(t0 + H)
        sig = dd[key][0]
        dd[key] = (sig, [[t0 + H, 1.0, 1.0, 1.0, 1.0, 999.0]])
        with open(cp, "wb") as f:
            pickle.dump(dd, f)
        fake = SW.read_bars(d, sym, a0, a1, cache=cache)
        assert any(b[5] == 999.0 for b in fake), "контроль не лёг: подделка не прочитана"
        time.sleep(0.01)
        write_hour(d, sym, t0 + H, n=1, px=300.0)
        fixed = SW.read_bars(d, sym, a0, a1, cache=cache)
        assert not any(b[5] == 999.0 for b in fixed) and fixed == SW.read_bars(d, sym, a0, a1)
        # часа на диске нет — не кэшируется, ответ тот же
        calls.clear()
        far = SW.read_bars(d, sym, t0 + 10 * H, t0 + 11 * H, cache=cache)
        assert far == [] and hh(t0 + 10 * H) in calls
        with open(cp, "rb") as f:
            assert hh(t0 + 10 * H) not in pickle.load(f)
        # предел часов на имя
        was = SW.BARS_CACHE_KEEP_H
        SW.BARS_CACHE_KEEP_H = 2
        try:
            SW._bars_cache_save(cache, sym, SW._bars_cache_load(cache, sym), keep=2)
            with open(cp, "rb") as f:
                kept = pickle.load(f)
            assert sorted(kept) == sorted([hh(t0 + 2 * H), hh(t0 + 3 * H)]), sorted(kept)
        finally:
            SW.BARS_CACHE_KEEP_H = was
    finally:
        store.read_hour = real
    print(f"ok  кэш баров: с кэшем = без кэша ({len(ref)} баров), второй вызов без чтения принтов, "
          "дописанный час — заново, подделка читается (контроль) и вытесняется, предел часов держится")
    return 0


if __name__ == "__main__":
    sys.exit(main())
