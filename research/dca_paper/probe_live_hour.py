#!/usr/bin/env python3
"""Зонд 10.10: что бумажная короткая книга сделала с решениями последних
часов, которые живой исполнитель Ladder взял (STRK, RLC, APR в 20:00 UTC).

Только чтение: выборы h24, кэш реплея семейства, справочник возраста.
Печатает по каждому решению последних `--hours` часов: руку, край, есть ли
запись реплея и её состояние у линейки `aggr_h`, возраст имени.

    run research/dca_paper/probe_live_hour.py
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_short as RS                                        # noqa: E402

T = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(float(t)))   # noqa: E731


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    a = ap.parse_args(argv)
    now = time.time()
    legs = RS.legs(log=lambda *x: print(*x))
    recent = [g for g in legs if float(g["at"]) >= now - a.hours * 3600]
    print(f"сейчас {T(now)} UTC; ног всего {len(legs)}, за {a.hours:g} ч {len(recent)}; "
          f"последняя нога {T(max(float(g['at']) for g in legs)) if legs else '—'}")
    try:
        print(f"файл выборов {RS.D11.PICKS}: изменён {T(os.path.getmtime(RS.D11.PICKS))}")
    except OSError as e:
        print(f"файл выборов: {e}")
    cache, why = RS.read_cache(log=print)
    print(f"кэш реплея: записей {len(cache)}" + (f", не годен: {why}" if why else "")
          + (f"; изменён {T(os.path.getmtime(RS.CACHE))}" if os.path.exists(RS.CACHE) else ""))
    launch = RS.IR.launches()
    rk = RS.BOOKS["aggr_h"]
    for g in recent:
        r = cache.get((rk, g["sym"], round(float(g["at"]), 3)))
        age = RS.IR.age_days(launch, g["sym"], g["at"]) if launch else None
        st = "нет записи" if r is None else f"{r.get('state')} {r.get('exit') or ''}".strip()
        print(f"  {T(g['at'])} {g['sym']} {g.get('arm')} fwd {g.get('fwd')} | реплей {rk}: {st} | "
              f"возраст {('%.1f сут' % age) if age is not None else 'неизвестен'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
