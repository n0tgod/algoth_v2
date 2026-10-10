#!/usr/bin/env python3
"""Зонд 10.10 (третий): касса общего счёта `pair_aggr` 100 $ в моменты
решений, которые взял живой исполнитель и не взяла бумага.

Собирает решения счёта теми же функциями, что `run_pair.run`, затем
повторяет раздачу кассы `run_d6.ration` с печатью состояния в момент
каждого решения последних `--hours` часов: счёт, свободные деньги, маржа
позиции, нотионал рунга против минимума, и кто держит деньги. Повтор
сверяется с `ration` по составу взятых — расхождение печатается числом.
Только чтение; это диагностика, деньги книги считает `ration`.

    run research/dca_paper/probe_live_hour3.py
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_pair as PR                                         # noqa: E402
import run_paper as RP                                        # noqa: E402
import rules as R                                             # noqa: E402
import run_d6 as D6                                           # noqa: E402

T = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(float(t))) if t else "—"   # noqa: E731


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="pair_aggr")
    ap.add_argument("--dep", type=float, default=100.0)
    ap.add_argument("--hours", type=float, default=7.0)
    a = ap.parse_args(argv)
    now = time.time()
    pk = a.pair
    lk, sk = R.parts_of(pk)
    longs, why_l = PR.long_recs(log=print)
    shorts, why_s = PR.short_recs(log=print)
    if why_l or why_s:
        print("кэш не годен:", why_l, why_s)
        return 1
    packed = PR.pack(longs, shorts, [pk])[pk]
    mine = [r for r in packed if (r.get("book") or pk) == sk]
    kept, _ = PR.gate_shorts(mine, pk, None, log=print)
    kept, _ = RP.age_shorts(kept, pk, log=print, now=now)
    kept, _ = RP.guard_shorts(kept, pk, log=print, now=now)
    recs = [r for r in packed if (r.get("book") or pk) == lk] + kept
    parts = {}
    for r in recs:
        parts.setdefault(r.get("book") or pk, []).append(r)
    keep = []
    for b in sorted(parts):
        ml = R.min_lev_of(b)
        g = [r for r in parts[b] if ml is None or float(r["lev"]) >= ml]
        k, _ = D6.one_per_name(g) if R.ONE_PER_NAME else (g, 0)
        keep += [dict(r, book=b) for r in k]
    plan = [(dict(r, exit_ts=float(r.get("sched_end") or r["exit_ts"]))
             if r.get("state") in ("open", "cut") else r) for r in keep]
    share = lambda r: R.share_in(pk, r.get("book") or pk, a.dep)     # noqa: E731
    rows = []
    D6.ration(plan, share, deposit=a.dep, min_notional=R.MIN_NOTIONAL, keep_rows=rows,
              sizing=R.DEFAULT_SIZING)
    taken_ration = {f"{float(r['at']):.3f}:{r['sym']}" for r, _m in rows}
    # повтор раздачи с печатью — те же шаги, что `ration`
    equity = free = float(a.dep)
    eps = 1e-9 * float(a.dep)
    live, taken = [], set()
    print(f"\n{pk} {a.dep:g} $: решений к кассе {len(plan)} (длинных {sum(1 for r in plan if r.get('book') == lk)}, "
          f"коротких {sum(1 for r in plan if r.get('book') == sk)}); доля шорта {share({'book': sk}):.4f}, "
          f"лонга {share({'book': lk}):.4f}")
    for r in D6.queue(plan):
        t = int(r["at"])
        still = []
        for p in live:
            if int(p[0]) <= t:
                free += p[1]
                equity += p[1] * p[2]
            else:
                still.append(p)
        live = still
        margin = equity * float(share(r))
        notional = margin * r["lev"]
        verdict = "взято"
        if notional * D6.RUNG_SHARE < R.MIN_NOTIONAL:
            verdict = f"мельче минимума: рунг {notional * D6.RUNG_SHARE:.2f} $ < {R.MIN_NOTIONAL:g}"
        elif margin > free + eps:
            verdict = f"нет кассы: маржа {margin:.2f} $ > свободно {free:.2f} $"
        else:
            free -= margin
            live.append((r["exit_ts"], margin, r["pnl"], r["sym"], r.get("book"), r["at"]))
            taken.add(f"{float(r['at']):.3f}:{r['sym']}")
        if float(r["at"]) >= now - a.hours * 3600:
            print(f"  {T(r['at'])} {r['sym']} {r.get('book')} плечо {float(r['lev']):.2f}: счёт {equity:.2f} $, "
                  f"маржа {margin:.2f} $ → {verdict}")
            if verdict.startswith("нет кассы"):
                for p in sorted(live, key=lambda p: -p[1])[:12]:
                    print(f"      держит {p[3]} {p[4]} с {T(p[5])} до {T(p[0])}: {p[1]:.2f} $")
    print(f"\nсверка повтора с ration: взято {len(taken)} / {len(taken_ration)}, "
          f"расхождение {len(taken ^ taken_ration)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
