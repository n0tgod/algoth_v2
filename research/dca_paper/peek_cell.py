#!/usr/bin/env python3
"""Заглянуть в одну ячейку книг на сервере (только чтение): хвосты логов
прогонов, запись имени в кэше коротких, строки имени в живом артефакте
общего счёта — чтобы «позиции нигде не было, а потом она закрылась»
разбиралось фактом, а не гипотезой.

    run research/dca_paper/peek_cell.py CTUSDT pair_optimal_g2:100
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def ts(t):
    try:
        return time.strftime("%m-%d %H:%M:%S", time.gmtime(float(t)))
    except (TypeError, ValueError):
        return str(t)


def tail(path, n, grep=None):
    print(f"== {os.path.relpath(path, HERE)}: {'есть' if os.path.exists(path) else 'НЕТ'}")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if grep:
        lines = [x for x in lines if any(g in x for g in grep)]
    print("".join(lines[-n:]).rstrip())


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "CTUSDT"
    cell = sys.argv[2] if len(sys.argv) > 2 else "pair_optimal_g2:100"
    out = os.path.join(HERE, "out")
    tail(os.path.join(out, "short.log"), 70)
    tail(os.path.join(out, "pair.log"), 70)
    import run_short as S                                      # noqa: E402
    cache, why = S.read_cache(log=lambda *a: None)
    print(f"== кэш коротких: записей {len(cache)}, {why or 'ок'}; {sym}:")
    for (rk, s, at), r in sorted(cache.items(), key=lambda kv: kv[0][2]):
        if s == sym and float(at) >= time.time() - 36 * 3600:
            print(f"  {rk} вход {ts(at)} state={r.get('state')} exit={r.get('exit')} exit_ts={ts(r.get('exit_ts'))} "
                  f"pnl={r.get('pnl')} marks={len(r.get('marks') or [])} fills={[(ts(f[0]), f[1], f[2]) for f in (r.get('fills') or [])]} "
                  f"lev={r.get('lev')}")
    for name in ("DCA-pair.json", "DCA-short.json"):
        p = os.path.join(out, name)
        try:
            st = os.stat(p)
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            print(f"== {name}: не читается: {e}")
            continue
        print(f"== {name}: {st.st_size / 1e6:.1f} МБ, изменён {ts(st.st_mtime)}, computed_at {d.get('computed_at')}")
        for ck in (cell, cell.replace("pair_optimal_g2", "optimal_h_g2"), cell.replace("pair_optimal_g2", "optimal_h")):
            v = (d.get("books") or {}).get(ck)
            if not v:
                continue
            o = v.get("open") or {}
            print(f"  {ck}: закрытых {((v.get('all') or {}).get('n'))}, открытых {len(o.get('positions') or [])}, "
                  f"cut {len(o.get('cut') or [])}, open.at {ts(o.get('at'))}")
            for p_ in (o.get("positions") or []) + (o.get("cut") or []):
                if p_.get("sym") == sym:
                    print(f"    {sym} в open: state={p_.get('state')} at={ts(p_.get('at'))} margin={p_.get('margin')} "
                          f"cut_why={p_.get('cut_why')} mark={p_.get('mark_usd')}")
            cells = d.get("cells") or {}
            print(f"  cells ключи: {list(cells)[:6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
