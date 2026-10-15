#!/usr/bin/env python3
"""Почему кэш баров не попадает в коротком реплее (15.10, профиль: 3964
read_hour на 68 чтений). Берёт первые решения из `need` коротких книг,
читает бары дважды через `sweep.read_bars(cache=…)` и печатает: время,
число вызовов read_hour, подписи часов и ключи pickle. Ничего не меняет
кроме самого кэша баров.

    run tools/bars_cache_probe.py
"""
import os
import pickle
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research", "dca_paper"))
sys.path.insert(0, os.path.join(HERE, "..", "research", "s9_sweep"))
sys.path.insert(0, os.path.join(HERE, "..", "research", "b1_book"))
import run_short as S                                         # noqa: E402
import tail as TL                                             # noqa: E402
import sweep as SW                                            # noqa: E402
import store                                                  # noqa: E402

HOUR = 3600.0


def main():
    quiet = lambda m: None                                    # noqa: E731
    legs_ = S.legs(log=quiet)
    cache, _ = S.read_cache(log=quiet)
    need = S.needs_replay(cache, legs_)[:3]
    print(f"заново {len(need)}; кэш баров {TL.BARS_CACHE}: файлов "
          f"{len(os.listdir(TL.BARS_CACHE)) if os.path.isdir(TL.BARS_CACHE) else 'нет каталога'}")
    calls = []
    real = store.read_hour

    def spy(dirpath, hour, log=None, parse=None):
        calls.append(hour)
        return real(dirpath, hour, log, parse) if parse else real(dirpath, hour, log)
    store.read_hour = spy
    try:
        for g in need:
            sym, at = g["sym"], float(g["at"])
            t0, t1 = at - 2 * HOUR, at + 26 * HOUR
            cp = SW._bars_cache_path(TL.BARS_CACHE, sym)
            had = os.path.exists(cp)
            for k in (1, 2):
                calls.clear()
                t = time.time()
                bars = SW.read_bars(TL.ROOT_B1, sym, t0, t1, cache=TL.BARS_CACHE)
                dt = time.time() - t
                print(f"{sym} проход {k}: {dt:.2f} с, баров {len(bars)}, read_hour {len(calls)} "
                      f"(pickle был: {had})")
            dirpath = os.path.join(TL.ROOT_B1, "trades", sym)
            hh = SW.datetime.fromtimestamp(int(t0 // 3600) * 3600 + 3 * 3600, SW.timezone.utc).strftime("%Y-%m-%d-%H")
            print(f"  подпись {hh}: {SW._hour_sig(dirpath, hh)}; файлы: "
                  f"{[f for f in os.listdir(dirpath) if f.startswith(hh)] if os.path.isdir(dirpath) else 'нет каталога'}")
            try:
                with open(cp, "rb") as f:
                    d = pickle.load(f)
                ks = sorted(d)
                print(f"  pickle: часов {len(ks)}, {ks[:2]} … {ks[-2:]}; {hh} в pickle: {hh in d}; "
                      f"подпись там: {d.get(hh, (None,))[0]}")
            except Exception as e:                            # noqa: BLE001
                print(f"  pickle не читается: {e}")
    finally:
        store.read_hour = real
    return 0


if __name__ == "__main__":
    sys.exit(main())
