#!/usr/bin/env python3
"""Сдвинутые входы книг ТВХ без записи реплея (10.11), только чтение: для
каждого — реплей в ЕГО ячейке выхода и в той же ячейке с плечом книги вместо
равного риска. Есть запись с плечом книги и нет с равным риском — ячейки
равного риска у позиции нет (`run_d10.eq_leverage`: ликвидация ближе
EQ_LIQ_MULT·стопа или убыток на полу не положителен)."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import model_books as MB                                      # noqa: E402


def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(float(t)))


def main():
    import run_short as S                                      # noqa: E402
    import entry_search as ES                                  # noqa: E402
    import model_branch as MBR                                 # noqa: E402
    import run_d10 as D10                                      # noqa: E402
    q = lambda *a: None                                        # noqa: E731
    reg = MB.load()
    st = json.load(open(MB.ENTRY_STATE, encoding="utf-8"))
    cache, _ = MBR.read_cache(log=q)
    books = [b for b in reg["books"] if b["kind"] == "entry"]
    lo = min(float(b["born_at"]) for b in books)
    legs = [g for g in S.legs(log=q) if float(g["at"]) >= lo]
    rk = S.BOOKS[MB.BASE]
    print(f"EQ_LEV_CAP {D10.EQ_LEV_CAP}, EQ_LIQ_MULT {D10.EQ_LIQ_MULT}")
    for b in books:
        sh = MB.shifted_legs(b, legs, st)
        miss = [g for g in sh if (b["id"], g["sym"], round(float(g["at"]), 3)) not in cache]
        print(f"\n== {b['id']} ({b['status']}): сдвинутых входов {len(sh)}, без записи реплея {len(miss)}")
        for g in miss:
            cell, pol = ES.exit_cell(g["exit"])
            got = {}
            for nm, p in (("своя ячейка", pol), ("плечо книги", dict(pol or {}, lev_risk=False) if pol else None)):
                out, _t = S.replay_cells([g], [cell], log=q, rulers=[rk],
                                         adds_of=(lambda gg, key, _p=p: _p) if p else None)
                recs = (out.get(cell[0]) or {})
                got[nm] = next(iter(recs.values()), None)
            a, bb = got["своя ячейка"], got["плечо книги"]
            why = ("ячейки равного риска нет" if a is None and bb is not None
                   else "записи нет ни в одной ячейке" if a is None else "запись есть (кэш устарел?)")
            print(f"  {ts(g['at'])} {g['sym']} выход {g['exit']}: {why}"
                  + (f"; с плечом книги {bb.get('lev')}× {bb.get('exit')}, нетто {bb.get('pnl_frac')}" if bb else ""))


if __name__ == "__main__":
    main()
