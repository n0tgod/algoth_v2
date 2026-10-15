#!/usr/bin/env python3
"""Профиль реплея коротких книг (спека 17 §0): где 123 с — чтение баров
или сам счёт позиций. Берёт первые N решений, которые прогон считал бы
заново, гоняет `run_short.replay` под cProfile и печатает верх по
накопленному времени. Кэш реплея НЕ пишет.

    run tools/short_profile.py --n=60
"""
import argparse
import cProfile
import io
import os
import pstats
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research", "dca_paper"))
import run_short as S                                         # noqa: E402
import tail as TL                                             # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()
    quiet = lambda m: None                                    # noqa: E731
    t = time.time()
    legs_ = S.legs(log=quiet)
    cache, _why = S.read_cache(log=quiet)
    need = S.needs_replay(cache, legs_)
    print(f"решений {len(legs_)}, в кэше {len(cache)}, заново {len(need)}; подготовка {time.time() - t:.1f} с")
    need = need[:a.n]
    src = TL.TailBars(log=quiet, cache=TL.BARS_CACHE)
    pr = cProfile.Profile()
    t = time.time()
    pr.enable()
    fresh, tail = S.replay(need, src=src, log=quiet)
    pr.disable()
    print(f"реплей {len(need)} решений: {time.time() - t:.1f} с, записей {len(fresh)}")
    buf = io.StringIO()
    st = pstats.Stats(pr, stream=buf)
    st.sort_stats("cumulative").print_stats(28)
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    for ln in lines[:40]:
        print(ln[:170])
    buf = io.StringIO()
    st = pstats.Stats(pr, stream=buf)
    st.sort_stats("tottime").print_stats(14)
    print("--- по собственному времени ---")
    for ln in [ln for ln in buf.getvalue().splitlines() if ln.strip()][5:22]:
        print(ln[:170])
    return 0


if __name__ == "__main__":
    sys.exit(main())
