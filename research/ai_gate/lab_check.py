#!/usr/bin/env python3
"""Сквозная проверка книг ТВХ модели после починок 10.11 — только чтение.

1. Решения после починки: сколько, сколько входов, «не измерено» (k = -2),
   отказы с пустыми полями — и лёг ли их час СЕЙЧАС (если час есть, а поле
   пустое — это настоящее «нет числа», а не опоздание).
2. Сдвинутые входы живых книг: каждый либо с записью реплея, либо помечен
   «не вошли» (no_cell); без того и другого — сколько и с какого часа
   (свежие — данных ещё нет, старые — дыра).
3. Дорешённые 10.11 входы: есть ли запись реплея и где сейчас.
4. Тики: возраст последнего, хвост лога с «к реплею» и «ячейк».
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import model_books as MB                                      # noqa: E402

FIX_AT = 1794300600.0          # 10.11 08:50 UTC — код починки на сервере (nc63)
H = 3600.0


def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(float(t)))


def main():
    import run_short as S                                      # noqa: E402
    import entry_search as ES                                  # noqa: E402
    import model_branch as MBR                                 # noqa: E402
    import wave as WV                                          # noqa: E402
    q = lambda *a: None                                        # noqa: E731
    now = time.time()
    reg = MB.load()
    st = json.load(open(MB.ENTRY_STATE, encoding="utf-8"))
    cache, why = MBR.read_cache(log=q)
    hours = WV.Hours()
    print(f"сейчас {ts(now)} UTC; кэш реплея {len(cache)} (why={why})")
    try:
        tk = json.load(open(MB.TICK, encoding="utf-8"))
        print(f"последний тик: {tk.get('at')} — {json.dumps({k: tk.get(k) for k in ('new_decisions', 'replayed', 'no_cell')})}")
    except (OSError, ValueError) as e:
        print(f"тик: {e}")
    books = [b for b in reg["books"] if b["kind"] == "entry"]
    lo = min(float(b["born_at"]) for b in books)
    legs = [g for g in S.legs(log=q) if float(g["at"]) >= lo]
    bad = 0
    for b in [x for x in books if x["status"] == "live"]:
        mine = st.get(b["id"]) or {}
        fields = [c["field"] for c in b["rule"]["when"]]
        after = {k: d for k, d in mine.items() if float(d.get("t") or 0) >= FIX_AT and not d.get("redecided")}
        ent = sum(1 for d in after.values() if d["k"] >= 0)
        unm = [k for k, d in after.items() if d["k"] == MB.UNMEASURED]
        empty = [(k, d) for k, d in after.items() if d["k"] == -1 and any((d.get("vals") or {}).get(f) is None for f in fields)]
        late_now = []
        for k, d in empty:
            sym, at = k.split("|")
            W = int(b["rule"]["W"])
            tm = float(at) + W * H - 1.0
            if not ES.landed(hours, sym, tm, fields):
                late_now.append(k)
        print(f"\n== {b['id']}: решений после починки {len(after)}, входов {ent}, «не измерено» {len(unm)}, "
              f"отказов с пустым полем {len(empty)} (из них час и сейчас не лёг: {len(late_now)})")
        for k, d in empty[:6]:
            print(f"   пустое поле при лёгшем часе: {k} {d.get('vals')} решено {ts(d['t'])}")
        if late_now:
            bad += len(late_now)
            print(f"   ДЕФЕКТ: решение при нелёгшем часе: {late_now[:5]}")
        sh = MB.shifted_legs(b, legs, st)
        nc = sum(1 for d in mine.values() if d.get("no_cell"))
        lost = [g for g in sh if (b["id"], g["sym"], round(float(g["at"]), 3)) not in cache]
        old = [g for g in lost if now - float(g["at"]) > 6 * H]
        print(f"   сдвинутых входов {len(sh)}, «не вошли: нет ячейки» {nc}, без записи реплея {len(lost)} "
              f"(старше 6 ч: {len(old)})")
        for g in old[:6]:
            print(f"   ДЕФЕКТ: вход без записи и без пометки: {ts(g['at'])} {g['sym']} выход {g['exit']}")
        bad += len(old)
        rd = [(k, d) for k, d in mine.items() if d.get("redecided") and d["k"] >= 0]
        for k, d in rd:
            sym, at = k.split("|")
            at_e = round(float(at) + d["k"] * H, 3)
            r = cache.get((b["id"], sym, at_e))
            where = ("не вошли: нет ячейки" if d.get("no_cell") else
                     f"реплей: {r.get('state')} {r.get('exit')} выход {ts(r['exit_ts']) if r.get('exit_ts') else '-'}" if r
                     else "НЕТ ЗАПИСИ")
            if where == "НЕТ ЗАПИСИ":
                bad += 1
            print(f"   дорешённый {ts(at_e)} {sym}: {where}")
    lg = os.path.join(HERE, "out", "model_books.log")
    tail = [l for l in open(lg, encoding="utf-8").read().splitlines()[-3000:] if "к реплею" in l or "ячейк" in l]
    print("\nтики (хвост):\n  " + "\n  ".join(tail[-8:]))
    print(f"\nИТОГ: дефектов {bad}")


if __name__ == "__main__":
    main()
