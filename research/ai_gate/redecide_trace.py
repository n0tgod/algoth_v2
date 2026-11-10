#!/usr/bin/env python3
"""Где теряются дорешённые входы книг ТВХ (10.11), только чтение: каждый
дорешённый вход проводится по шагам книги — кэш реплея, окно книги,
возраст имени, охрана рынком, касса (одна позиция на имя, места) — и
печатается шаг, на котором он выпал, с соседями того же имени."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import model_books as MB                                      # noqa: E402

H = 3600.0


def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(float(t))) if t else "-"


def main():
    import rules as R                                          # noqa: E402
    import run_paper as RP                                     # noqa: E402
    import model_branch as MBR                                 # noqa: E402
    import instruments_refresh as IR                           # noqa: E402
    now = time.time()
    st = json.load(open(MB.ENTRY_STATE, encoding="utf-8"))
    cache, why = MBR.read_cache(log=print)
    print(f"кэш реплея: {len(cache)} записей, why={why}")
    launch = IR.launches()
    for bid in ("m05", "m06"):
        bk = f"optimal_h_{bid}"
        want = []
        for sk, d in (st.get(bid) or {}).items():
            if d.get("redecided") and d["k"] >= 0:
                sym, at = sk.split("|")
                want.append((sym, float(at) + d["k"] * H))
        steps = {}
        recs, w = MBR.entry_recs(bk, cache=cache, log=lambda *a: None)
        steps["окно книги"] = recs
        a_recs, ages = RP.age_shorts(list(recs), bk, launch=launch, log=lambda *a: None, now=now)
        steps["возраст имени"] = a_recs
        g_recs, guards = RP.guard_shorts(list(a_recs), bk, log=lambda *a: None, now=now)
        steps["охрана рынком"] = g_recs
        rows, cells, one, live = RP.build_rows({bk: g_recs}, now=now, keys=[bk], log=lambda *a: None)
        took = {(r["sym"], round(float(r["at"]))) for r in rows if int(r.get("dep", 0)) == 10000 and not r.get("sizing")}
        print(f"\n== {bk}: дорешённых входов {len(want)}; записей окна {len(recs)}, после возраста {len(a_recs)}, "
              f"после охраны {len(g_recs)}, в кассе $10k {len(took)}")
        for sym, at in sorted(want, key=lambda x: x[1]):
            k = (bid, sym, round(at, 3))
            r = cache.get(k)
            where = None
            if r is None:
                where = "нет в кэше реплея"
            else:
                for nm, lst in steps.items():
                    if not any(x["sym"] == sym and abs(float(x["at"]) - at) < 1 for x in lst):
                        where = f"выпал на шаге «{nm}»"
                        break
                if where is None and (sym, round(at)) not in took:
                    near = sorted((ts(x["at"]), ts(x.get("exit_ts")), x.get("exit")) for x in g_recs
                                  if x["sym"] == sym and abs(float(x["at"]) - at) < 3 * 86400)
                    where = f"не взят кассой $10k; то же имя в книге: {near}"
            print(f"  {ts(at)} {sym}: {where or 'в книге'}"
                  + (f" · реплей: {r.get('state')} {r.get('exit')} выход {ts(r.get('exit_ts'))}" if r else ""))
        print(f"   возраст: {json.dumps(ages, ensure_ascii=False)[:300]}")
        print(f"   охрана: {json.dumps(guards, ensure_ascii=False)[:300]}")
        print(f"   одно имя: {json.dumps(one.get(bk) if isinstance(one, dict) else one, ensure_ascii=False)[:400]}")


if __name__ == "__main__":
    main()
