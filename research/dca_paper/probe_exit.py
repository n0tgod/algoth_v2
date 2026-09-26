#!/usr/bin/env python3
"""Разбор одного выхода: где стояла цена по записи и что видит график.

Повод (26.09, RAREUSDT, шорт 25.09 16:00, выход «рынок» 23:59:59 по
0.016103): владелец видит точку выхода на верной цене, а свечи в этот
момент — ниже. Вопрос про источники: цена выхода охраны выводится из
отметки ядра за последний бар часа (закрытие), график рисует свечи
принтов. Здесь печатается всё, что нужно сверить глазами и числом:

- строки журналов `h24` и `pair` по этому решению (выход, момент, цена);
- запись кэша реплея с почасовыми отметками и восстановленным путём
  (`wave.path_of`) — из какой отметки родилась цена выхода;
- минутные бары ПРИНТОВ (то, что рисует график) в окне ±10 минут вокруг
  выхода, и бары реплея (`TailBars`: принты + хвост серединой стакана);
- три кандидата цены на границе часа: закрытие последнего бара ДО
  границы, закрытие бара, начинающегося НА границе, открытие первого
  бара ПОСЛЕ границы — и на сколько каждый отличается от записанной.

    run research/dca_paper/probe_exit.py --sym RAREUSDT --at 2026-09-25-16
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s9_sweep"))
sys.path.insert(0, os.path.join(ROOT, "research", "b1_book"))
import rules as R                                             # noqa: E402
import run_short as S                                         # noqa: E402
import wave as WV                                             # noqa: E402
import tail as TL                                             # noqa: E402
import sweep as SW                                            # noqa: E402

MIN = 60.0


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(t)))


def hour_ts(s):
    return datetime.strptime(s, "%Y-%m-%d-%H").replace(
        tzinfo=timezone.utc).timestamp()


def rows_for(path, sym, at):
    rows, _ = R.read_journal(path)
    return [r for r in rows if r.get("sym") == sym and R.is_current(r)
            and abs(float(r["at"]) - at) < 1]


def candidates(bars, boundary):
    """Три цены на границе часа из списка баров [t, o, h, l, c, v]."""
    before = [b for b in bars if b[0] < boundary]
    at_b = [b for b in bars if b[0] == boundary]
    after = [b for b in bars if b[0] > boundary]
    return {"close_before": (before[-1] if before else None),
            "bar_at": (at_b[0] if at_b else None),
            "first_after": (after[0] if after else None)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", required=True)
    ap.add_argument("--at", required=True, help="час решения ГГГГ-ММ-ДД-ЧЧ")
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--replay", action="store_true",
                    help="реплей решения заново тем же кодом, что у книги")
    a = ap.parse_args(argv)
    at = hour_ts(a.at)
    print(f"# {a.sym} — решение {ts(at)} UTC")
    for name, path in (("h24", R.H24_JOURNAL), ("pair", R.PAIR_JOURNAL)):
        for r in rows_for(path, a.sym, at):
            print(f"{name:4s} {R.ruler_of(r):13s} ${int(r.get('dep') or 0):>6} "
                  f"lev {float(r.get('lev') or 0):5.2f} entry {r.get('entry_px')} "
                  f"exit {r.get('exit')} {ts(r['exit_ts'])} px {r.get('exit_px')} "
                  f"pnl {float(r.get('pnl_frac') or 0):+.6f} tail {r.get('tail')}")
    cache, why = S.read_cache(log=lambda m: None)
    recs = [(k, r) for k, r in cache.items()
            if k[1] == a.sym and abs(float(k[2]) - at) < 1]
    exit_ts = None
    for k, r in recs:
        p = WV.path_of(r)
        print(f"\nкэш {k[0]}: exit {r.get('exit')} {ts(r['exit_ts'])} px {r.get('exit_px')} "
              f"state {r.get('state')} lev {r.get('lev')} n_rungs {r.get('n_rungs')} "
              f"depth {r.get('depth')} avg {r.get('avg')} entry {r.get('entry_px')}")
        if p:
            print("  путь по часам (k: pnl долей маржи): "
                  + ", ".join(f"{k_}: {v:+.5f}" for k_, v in sorted(p["cum"].items())[:12]))
            lev, e = float(r.get("lev") or 0), r.get("entry_px")
            if e and lev:
                for k_ in sorted(p["cum"])[:12]:
                    px = float(e) * (1.0 - p["cum"][k_] / lev)
                    print(f"    k={k_} → цена из отметки {px:.6f} ({ts(at + k_ * 3600 - 1)})")
    # бары: принты (график) и реплей (принты + хвост)
    jr = rows_for(R.H24_JOURNAL, a.sym, at)
    exit_ts = float(jr[0]["exit_ts"]) if jr else at + 3600.0
    boundary = float(int(exit_ts + 1.0))
    t0, t1 = boundary - a.minutes * MIN, boundary + a.minutes * MIN
    tape = SW.read_bars(TL.ROOT_B1, a.sym, t0, t1)
    src = TL.TailBars(log=lambda m: None)
    rep = src.bars(a.sym, t0, t1)
    print(f"\nграница часа {ts(boundary)}; бары принтов в окне {len(tape)}, "
          f"бары реплея {len(rep)} (из них хвост {sum(1 for b in rep if float(b[5]) <= 0)})")
    print("время             open      high      low       close     объём$   источник")
    reps = {b[0]: b for b in rep}
    for b in sorted({x[0] for x in tape} | set(reps)):
        bb = reps.get(b) or next(x for x in tape if x[0] == b)
        src_ = "принты" if float(bb[5]) > 0 else "хвост(стакан)"
        mark = " ← граница" if bb[0] == boundary else ""
        print(f"{ts(bb[0])}  {bb[1]:<9.6g} {bb[2]:<9.6g} {bb[3]:<9.6g} {bb[4]:<9.6g} "
              f"{bb[5]:<8.0f} {src_}{mark}")
    # закрытия часов по принтам на всём сроке — против цен из отметок
    hold_h = R.H24_HOLD_H
    full = SW.read_bars(TL.ROOT_B1, a.sym, at, at + (hold_h + 1) * 3600.0)
    print(f"\nзакрытия часов по принтам (срок {hold_h} ч) — против цены из отметки кэша:")
    cache_cum = {}
    for k, r in recs:
        p = WV.path_of(r)
        lev, e = float(r.get("lev") or 0), r.get("entry_px")
        if p and e and lev:
            cache_cum[k[0]] = {k_: float(e) * (1.0 - v / lev) for k_, v in p["cum"].items()}
    for h in range(1, hold_h + 1):
        h_end = at + h * 3600.0
        in_h = [b for b in full if h_end - 3600.0 <= b[0] < h_end]
        last_b = in_h[-1] if in_h else None
        marks = " ".join(f"{rk}:{cc.get(h, float('nan')):.6f}" for rk, cc in cache_cum.items())
        print(f"  k={h:2d} {ts(h_end - 1)}  принты: "
              + (f"последний бар {ts(last_b[0])[11:]} close {last_b[4]:.6g}, баров {len(in_h)}"
                 if last_b else "баров нет")
              + f"  | из отметок: {marks}")
    if a.replay:
        # тот же код, что кормит книгу: реплей одного решения заново
        legs_ = [g for g in S.legs(log=lambda m: None)
                 if g["sym"] == a.sym and abs(float(g["at"]) - at) < 1]
        print(f"\nреплей заново: ног {len(legs_)}")
        if legs_:
            fresh, _tail = S.replay(legs_[:1], src=TL.TailBars(log=lambda m: None),
                                    log=lambda m: None)
            for k, r in fresh.items():
                p = WV.path_of(r)
                lev, e = float(r.get("lev") or 0), r.get("entry_px")
                print(f"  свежий {k[0]}: exit {r.get('exit')} {ts(r['exit_ts'])} px {r.get('exit_px')} "
                      f"state {r.get('state')} entry {e}")
                if p and e and lev:
                    print("    цены из свежих отметок: "
                          + ", ".join(f"k={k_}: {float(e) * (1.0 - v / lev):.6f}"
                                      for k_, v in sorted(p["cum"].items())[:12]))
    c = candidates(tape, boundary)
    px = float(jr[0]["exit_px"]) if jr and jr[0].get("exit_px") else None
    print("\nкандидаты цены на границе (принты):")
    for name, b in c.items():
        if b is None:
            print(f"  {name:12s}: нет бара")
            continue
        v = b[4] if name != "first_after" else b[1]
        d = f"{(v - px) / px * 1e4:+.1f} б.п. к записанной" if px else ""
        print(f"  {name:12s}: {ts(b[0])} {'close' if name != 'first_after' else 'open'} {v:.6g}  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
