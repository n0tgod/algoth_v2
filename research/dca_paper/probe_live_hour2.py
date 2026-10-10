#!/usr/bin/env python3
"""Зонд 10.10 (второй): почему общий счёт `pair_aggr` не взял короткие
решения 20:00 UTC (STRK, RLC, APR), которые взял живой исполнитель.

Повторяет шаги `run_pair.run` для короткой стороны ОДНОГО счёта — возраст,
охрана рынком, гейт плеча, одна на имя — на кэше реплея и печатает судьбу
решений последних `--hours` часов по каждому шагу, плюс прежние ноги тех же
имён (одна на имя считает ноги РЕПЛЕЯ, а не взятые кассой). Только чтение.

    run research/dca_paper/probe_live_hour2.py
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_short as RS                                        # noqa: E402
import run_paper as RP                                        # noqa: E402
import rules as R                                             # noqa: E402
import run_d6 as D6                                           # noqa: E402

T = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(float(t))) if t else "—"   # noqa: E731


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="pair_aggr")
    ap.add_argument("--hours", type=float, default=7.0)
    ap.add_argument("--back", type=float, default=48.0)
    a = ap.parse_args(argv)
    now = time.time()
    lk, sk = R.parts_of(a.pair)
    cache, why = RS.read_cache(log=print)
    base = RS.BOOKS[sk]
    recs = [dict(r, book=sk) for (rk, _s, _a), r in cache.items() if rk == base]
    print(f"{a.pair}: короткая сторона {sk} (реплей {base}), записей {len(recs)}"
          + (f"; кэш не годен: {why}" if why else ""))
    targets = sorted({r["sym"] for r in recs if float(r["at"]) >= now - a.hours * 3600})
    launch = RS.IR.launches()
    aged, why_age = RP.age_shorts(recs, a.pair, launch=launch, log=print, now=now)
    print(f"возраст: {why_age}")
    guarded, why_g = RP.guard_shorts(aged, a.pair, log=print, now=now)
    print(f"охрана рынком: {str(why_g)[:300]}")
    ml = R.min_lev_of(sk)
    gated = [r for r in guarded if ml is None or float(r["lev"]) >= ml]
    kept, skipped = D6.one_per_name(gated) if R.ONE_PER_NAME else (gated, 0)
    print(f"гейт плеча {ml}: осталось {len(gated)} из {len(guarded)}; одна на имя: оставлено {len(kept)}, пропущено {skipped}")
    ids = lambda xs: {(r["sym"], round(float(r["at"]), 3)) for r in xs}   # noqa: E731
    s_aged, s_g, s_gate, s_kept = ids(aged), ids(guarded), ids(gated), ids(kept)
    for sym in targets:
        print(f"\n{sym}:")
        for r in sorted((r for r in recs if r["sym"] == sym and float(r["at"]) >= now - a.back * 3600),
                        key=lambda r: float(r["at"])):
            k = (r["sym"], round(float(r["at"]), 3))
            step = ("возраст" if k not in s_aged else "охрана" if k not in s_g else
                    "гейт плеча" if k not in s_gate else "одна на имя (повтор)" if k not in s_kept else "к кассе")
            g2 = next((x for x in guarded if (x["sym"], round(float(x["at"]), 3)) == k), r)
            print(f"  {T(r['at'])} плечо {float(r['lev']):.2f} {r.get('state')} {r.get('exit') or ''} "
                  f"выход {T(g2.get('exit_ts'))} конец срока {T(g2.get('sched_end'))} → {step}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
