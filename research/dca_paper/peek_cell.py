#!/usr/bin/env python3
"""Заглянуть в одну ячейку книг на сервере (только чтение): хвосты логов
прогонов, запись имени в кэше коротких, строки имени в живом артефакте
общего счёта — чтобы «позиции нигде не было, а потом она закрылась»
разбиралось фактом, а не гипотезой.

    run research/dca_paper/peek_cell.py CTUSDT pair_optimal_g2 100
(ключ ячейки — двумя словами: двоеточие белый список очереди не пропускает)
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
    cell = (sys.argv[2] if len(sys.argv) > 2 else "pair_optimal_g2") + ":" + (sys.argv[3] if len(sys.argv) > 3 else "100")
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
    # --- журнал ячейки за 36 ч: что закрылось и чем (23.10: позиции исчезли с экрана)
    import rules as R                                          # noqa: E402
    rk, _, dep = cell.partition(":")
    try:
        rows, _bad = R.read_journal(R.journal_of(rk))
    except Exception as e:                                     # noqa: BLE001
        rows = []
        print(f"== журнал {rk}: не прочитан: {type(e).__name__}: {e}")
    lo = time.time() - 36 * 3600
    mine = [r for r in rows if r.get("ruler") == rk and str(int(float(r.get("dep", 0) or 0))) == dep
            and not r.get("sizing") and (float(r.get("exit_ts") or 0) >= lo or float(r.get("at") or 0) >= lo
                                         or float(r.get("t") or r.get("written") or r.get("rec_at") or 0) >= lo)]
    print(f"== журнал {rk}:{dep}: строк всего {sum(1 for r in rows if r.get('ruler') == rk)}, за 36 ч {len(mine)}; "
          f"поля строки: {sorted((mine or rows[-1:] or [{}])[0].keys())}")
    for r in sorted(mine, key=lambda r: float(r.get("exit_ts") or 0)):
        extra = {k: r.get(k) for k in r if k not in ("sym", "side", "at", "exit_ts", "exit", "lev", "margin", "usd",
                                                     "ruler", "dep", "sizing", "walk", "fills", "levels", "tail")}
        print(f"  {r.get('sym')} {r.get('side')} вход {ts(r.get('at'))} выход {ts(r.get('exit_ts'))} {r.get('exit')} "
              f"lev={r.get('lev')} margin={r.get('margin')} usd={r.get('usd')} {extra}")
    # --- состояние сторожа счёта по ячейке: что он считает закрытым
    try:
        with open(os.path.join(out, "watch", "pair.json" if rk.startswith("pair_") else "h24.json"), encoding="utf-8") as f:
            wst = json.load(f)
        c = (wst.get("cells") or {}).get(cell) or {}
        print(f"== watch/{'pair' if rk.startswith('pair_') else 'h24'}.json at {ts(wst.get('at'))}: {cell} n={c.get('n')} usd={c.get('usd')}; "
              f"закрытые с сегодняшним входом: " + str({k: v for k, v in (c.get('closed') or {}).items() if int(k.rsplit(':', 1)[-1]) >= int(time.time()) - 36 * 3600}))
    except (OSError, ValueError, KeyError) as e:
        print(f"== состояние сторожа не прочитано: {e}")
    # --- охрана рынком по этой книге в логе общего счёта: последние прогоны
    tail(os.path.join(out, "pair.log"), 14, grep=[f"{rk}: охрана", f"{rk}: возраст", "computed_at", "общий счёт:", "за "])
    # --- сторож счёта: находки по ячейке за 24 ч
    import account_watch as AW                                 # noqa: E402
    print("== сторож счёта (watch/log.jsonl), ячейка за 24 ч:")
    try:
        with open(AW.LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if x.get("cell") == cell and float(x.get("t", 0)) >= time.time() - 24 * 3600:
                    print(f"  {ts(x['t'])} {x.get('kind')} {x.get('text')}")
    except OSError as e:
        print(f"  лог не читается: {e}")
    # --- почему не публикуется: хвосты логов прогонов по словам
    for lg in ("pair.log", "short.log", "paper.log"):
        tail(os.path.join(out, lg), 25, grep=["публик", "push", "rebase", "lock", "разош", "ОТКАЗ", "ошибк", "Traceback",
                                               "Error", "охрана рынком", "pair_optimal_g2"])
    # --- сводки волны (охрана рынком читает их): какие часы переписаны сегодня
    import wave as WV                                          # noqa: E402
    print(f"== сводки часов {os.path.relpath(WV.SUMMARY_DIR, HERE)}: изменённые за 12 ч (имя → изменён):")
    try:
        names = sorted(os.listdir(WV.SUMMARY_DIR))
        fresh = [(n, os.stat(os.path.join(WV.SUMMARY_DIR, n)).st_mtime) for n in names]
        fresh = [(n, m) for n, m in fresh if m >= time.time() - 12 * 3600]
        for n, m in sorted(fresh, key=lambda x: x[1])[-40:]:
            print(f"  {n} → {ts(m)}")
        print(f"  всего файлов {len(names)}, изменено за 12 ч {len(fresh)}")
    except OSError as e:
        print(f"  каталог не читается: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
