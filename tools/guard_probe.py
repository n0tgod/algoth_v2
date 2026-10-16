"""Зонд: что видела охрана рынком — волна прокси-имён с момента входа
коротких позиций по часам. Печатает порог, список прокси, ход каждого
имени и среднюю волну от входа к каждому следующему часу. Ничего не
меняет.

    run tools/guard_probe.py --at=2026-10-15-19 --at=2026-10-15-21
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "research", "dca_paper"))
import wave as WV                                             # noqa: E402
import rules as R                                             # noqa: E402


def ts(h):
    return datetime.strptime(h, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc).timestamp()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", action="append", default=[])
    ap.add_argument("--hours", type=int, default=20)
    a = ap.parse_args()
    mkt = WV.Market(WV.Hours())
    print("порог по книгам", R.WAVE_GUARD_PCT, "; прокси:", ", ".join(WV.PROXY), f"(мин. {WV.MIN_PROXY})")
    for h in a.at or ["2026-10-15-19", "2026-10-15-21"]:
        t_in = ts(h) + 3600 - 1          # вход — конец часа решения, как у k_star
        print(f"\nвход в час {h} (t_in {time.strftime('%d %H:%M', time.gmtime(t_in))} UTC):")
        for k in range(1, a.hours + 1):
            t1 = t_in + k * 3600
            w = mkt.wave(t_in, t1)
            parts = []
            for s in WV.PROXY:
                m = mkt.move(s, t_in, t1)
                if m is not None:
                    parts.append(f"{s[:-4]} {m * 100:+.1f}")
            flag = " ← ПОРОГ" if (w is not None and w >= 0.02) else ""
            print(f"  k={k:2d} до {time.strftime('%d %H:%M', time.gmtime(t1))}: волна "
                  f"{('—' if w is None else f'{w * 100:+.2f} %')}{flag}  [{'; '.join(parts)}]")
        k, miss = mkt.k_star(ts(h) + 3600, 2.0, R.H24_HOLD_H - 1)
        print(f"  k_star(порог 2 %) = {k}, часов без волны {miss}")


if __name__ == "__main__":
    main()
