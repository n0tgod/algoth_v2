#!/usr/bin/env python3
"""D12 — билет от СОБСТВЕННОГО пика: сколько даёт сигнал h24 (шорт),
когда депозит делится на места ЭТОЙ книги, а не пула DCA.

Вопрос владельца 2026-09-07: «если без доливов, а просто открывать
больше сделок — рассчитывая от суммы депозита, то есть давать больше
ячеек». Замер D11 показал: касса ни разу не отказала (`no_cash` 0 на
$10k и $100k), а 70 % решений отброшены как повтор уже открытого имени
(`skipped_repeats`) — верхние три шорта h24 повторяются час за часом.
Значит «больше ячеек» упирается не в деньги и не в число решений, а в
БИЛЕТ: правило бумажных книг делит депозит на пик пула DCA (457 мест ×
1.5), и на $10k билет упирается в пол $25 — 0.25 % депозита на позицию,
тогда как книга на трёх именах в час и сроком 24 ч держит разом
десятки позиций, а не сотни. Депозит стоит.

Здесь тот же реплей (D10/D11: одиночный вход или лестница, забор,
пол, нетто круга), а размер — по правилу книги, но от СВОЕГО пика:
билет = депозит / (пик одновременно открытых × запас 1.5), не ниже
пола биржи; пик меряется в самом реплее по (вход, выход) каждой
ячейки. Рядом — та же ячейка с билетом пула (как в D11), чтобы
разница была видна числом. Пик измерен на том же окне — это правило
книги, а не оптимизация, и оно объявлено тем же, что у DCA-книг.

Ячейки — узкий набор из D10/D11 (объявлен): правило книги
`fence:struct:t2`; без доливов на заборе `fence:none:t2`; потолки
1×/2×/3× без доливов и со структурными доливами; цель ×1 у двух из
них. Судится форма и половины, не лучшая ячейка.

Запуск на VPS:
  run research/dca_ladder/run_d12.py --arm nn --hold 24
  run research/dca_ladder/run_d12.py --arm nn
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dca_paper"))
import run_d10 as D10                                         # noqa: E402
import run_d11 as D11                                         # noqa: E402
import rules as R                                             # noqa: E402

OUT = os.path.join(HERE, "out")
KEYS = ["fence:struct:t2", "fence:none:t2", "c3:none:t2", "c2:none:t2",
        "c1:none:t2", "c3:struct:t2", "c1:struct:t2", "fence:none:t1",
        "c1:none:t1"]
BOOKS = ("optimal_s", "safe_s")
PEAK_MARGIN = float(R.PEAK_MARGIN)          # тот же запас, что у книг


def peak_open(rows):
    """Пик одновременно открытых позиций по (вход, выход) — заметающая
    прямая; None — записей нет."""
    ev = []
    for r in rows:
        ev.append((float(r["at"]), 1))
        ev.append((float(r["exit_ts"]), -1))
    if not ev:
        return None
    ev.sort(key=lambda e: (e[0], e[1]))      # выход раньше входа в ту же секунду
    cur = best = 0
    for _t, d in ev:
        cur += d
        best = max(best, cur)
    return best


def own_share(dep, peak, book):
    """Доля счёта на позицию от собственного пика, не ниже пола режима."""
    if not peak:
        return None
    ticket = max(float(R.floor_of(book)), float(dep) / (peak * PEAK_MARGIN))
    return min(1.0, ticket / float(dep))


def run(arm="nn", hold_h=None, limit=None, src=None, log=print, legs=None):
    t0 = time.time()
    was = D11.configure(hold_h)
    try:
        legs = legs if legs is not None else D11.h24_legs(arm, limit=limit, log=log)
        got = D10.collect(src=src, log=log, legs=legs)
        out = {"signal": {"book": "h24", "arm": arm, "hold_h": D10.D2.HOLD_H,
                          "ref_gate": D11.REF_GATE, "legs": len(legs)},
               "keys": KEYS, "books": list(BOOKS), "deposits": R.DEPOSITS,
               "peak_margin": PEAK_MARGIN, "cells": {}, "peaks": {},
               "window": got["window"], "positions": got["positions"],
               "sample": {}}
        for book in BOOKS:
            rk = D10.BOOK_RULER[book]
            stores, n_ok, lost = D10.common_sample(got["recs"][rk], log=log)
            out["sample"][book] = {"n": n_ok, "lost": lost}
            for key in KEYS:
                rows = stores[key].rows()
                # пик — по позициям, которые взяла бы касса при билете пула
                # (один вход на имя): те же правила отбора, что у ячейки
                ml = R.min_lev_of(book)
                sub = [r for r in rows if D11.REF_GATE in (r.get("gates") or [])]
                gated = ([r for r in sub if float(r["lev"]) >= ml]
                         if ml is not None else sub)
                keep, _sk = D10.D6.one_per_name(gated)
                peak = peak_open(keep)
                out["peaks"][f"{key}|{book}"] = peak
                for dep in R.DEPOSITS:
                    sh = own_share(dep, peak, book)
                    for net in (False, True):
                        tag = "net" if net else "gross"
                        base = D10.cell(rows, book, dep, net=net)
                        own = (D10.cell(rows, book, dep, net=net, share=sh)
                               if sh is not None else None)
                        out["cells"][f"{key}|{book}|{int(dep)}|{tag}"] = {
                            "pool": base, "own": own,
                            "own_share": sh,
                            "own_ticket": (round(sh * dep, 2) if sh else None),
                            "pool_ticket": round(R.ticket(dep, book), 2)}
                # половины — по времени входа, при СВОЁМ билете, $10k
                dep = R.DEPOSITS[1]
                sh = own_share(dep, peak, book)
                ts = sorted(float(r["at"]) for r in rows)
                if ts and sh is not None:
                    mid = ts[len(ts) // 2]
                    a = [r for r in rows if float(r["at"]) < mid]
                    b = [r for r in rows if float(r["at"]) >= mid]
                    out["cells"][f"{key}|{book}|{int(dep)}|halves"] = {
                        "mid": mid,
                        "A": D10.cell(a, book, dep, net=True, share=sh),
                        "B": D10.cell(b, book, dep, net=True, share=sh)}
            log(f"книга {book}: ячейки посчитаны")
            D10.mem_guard(f"книга {book}", log=log)
        out["secs"] = round(time.time() - t0, 1)
        out["rss_mb"] = D10._rss_mb()
        out["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        return out
    finally:
        D11.restore(was)


def verdict(s):
    """Из чисел: при своём билете нетто > 0 на $10k, медиана дня ≥ 0 и обе
    половины ≥ 0 — «держится»; печатается списком, не лучшей ячейкой."""
    dep = int(s["deposits"][1])
    out = {}
    for book in s["books"]:
        held, pos = [], []
        for key in s["keys"]:
            c = (s["cells"].get(f"{key}|{book}|{dep}|net") or {}).get("own") or {}
            h = s["cells"].get(f"{key}|{book}|{dep}|halves") or {}
            ok = (c.get("final") or 0) > 0 and (c.get("day_median") or 0) >= 0
            if ok:
                pos.append(key)
            if ok and h and (h["A"].get("final") or 0) >= 0 and (h["B"].get("final") or 0) >= 0:
                held.append(key)
        out[book] = {"positive_net": pos, "held_both_halves": held}
    return out


def _p(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{x:+,.2f}"


def report(s):
    sig = s["signal"]
    v = verdict(s)
    dep = int(s["deposits"][1])
    P = [f"# D12 — билет от собственного пика: сигнал h24 (шорт, рука {sig['arm']}, "
         f"срок {sig['hold_h']} ч)", "",
         "Вопрос владельца 2026-09-07: «без доливов, но больше сделок — от суммы "
         "депозита, больше ячеек». D11: касса не отказывала ни разу, 70 % решений — "
         "повтор уже открытого имени; узкое место — билет: правило книг делит депозит "
         "на пик ПУЛА DCA (457 × 1.5), и на $10k билет упирается в пол $25 при "
         "десятках одновременных позиций у этого источника. Здесь билет — от "
         f"СОБСТВЕННОГО пика ячейки (депозит / (пик × {s['peak_margin']:g}), не ниже "
         "пола режима), рядом — билет пула. Пик измерен на том же окне: это правило "
         "книги, объявленное тем же, что у DCA-книг, а не подбор.", "",
         f"Ног {sig['legs']}, гейт отсчёта «{sig['ref_gate']}», окно "
         f"{(s.get('window') or {}).get('from')} … {(s.get('window') or {}).get('to')} UTC; "
         f"общая выборка: " + ", ".join(f"{b} {x['n']} (выброшено до {x['lost']})"
                                        for b, x in s["sample"].items()) + ".", ""]
    for book in s["books"]:
        P += [f"## Книга `{book}`, депозит ${dep:,}", "",
              "| ячейка | пик | билет пула → свой | взято пул → свой | итог брутто пул → свой | "
              "итог нетто пул → свой | просадка (свой) | медиана дня нетто (свой) | зелёных | "
              "укус | половины нетто A / B (свой) | тейк/пол/ликв/срок (свой) |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for key in s["keys"]:
            g = s["cells"].get(f"{key}|{book}|{dep}|gross") or {}
            n = s["cells"].get(f"{key}|{book}|{dep}|net") or {}
            h = s["cells"].get(f"{key}|{book}|{dep}|halves") or {}
            pg, og = g.get("pool") or {}, g.get("own") or {}
            pn, on = n.get("pool") or {}, n.get("own") or {}
            ex = on.get("exits") or {}
            mark = " ⟵ правило книги" if key == D10.REF else ""
            P.append(f"| `{key}`{mark} | {s['peaks'].get(f'{key}|{book}')} | "
                     f"${g.get('pool_ticket')} → ${g.get('own_ticket')} | "
                     f"{pg.get('taken')} → {og.get('taken')} | "
                     f"{_p(pg.get('final'))} → {_p(og.get('final'))} | "
                     f"{_p(pn.get('final'))} → **{_p(on.get('final'))}** | "
                     f"{_p(on.get('max_dd'))} | {_p(on.get('day_median'), 3)} | "
                     f"{_p(on.get('day_green'), 0)} | "
                     f"{on.get('bite') if on.get('bite') is not None else '—'} | "
                     f"{_p((h.get('A') or {}).get('final'))} / {_p((h.get('B') or {}).get('final'))} | "
                     f"{ex.get('тейк', 0)}/{ex.get('пол', 0)}/{ex.get('ликвидация', 0)}/{ex.get('срок', 0)} |")
        vb = v[book]
        P += ["", f"Нетто > 0 при своём билете на ${dep:,}: {len(vb['positive_net'])} из "
              f"{len(s['keys'])}" + (" — " + ", ".join(f"`{k}`" for k in vb["positive_net"])
                                     if vb["positive_net"] else "")
              + f"; из них держат обе половины окна: **{len(vb['held_both_halves'])}**"
              + (" — " + ", ".join(f"`{k}`" for k in vb["held_both_halves"])
                 if vb["held_both_halves"] else "") + ".", ""]
    P += ["## Чего замер НЕ говорит", "",
          "Пик измерен на том же окне, что и результат (правило книги, но in-sample); "
          "решений в час у источника три на руку — больше имён в час историей не "
          "воспроизвести (лист сечения пишется только у ситуационной модели); "
          "проскальзывания и funding в нетто нет (круг — комиссия); окно одно."]
    return "\n".join(P) + "\n"


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="D12: билет от собственного пика, сигнал h24")
    ap.add_argument("--arm", default="nn", choices=("nn", "gbm"))
    ap.add_argument("--hold", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                     # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    s = run(arm=a.arm, hold_h=a.hold, limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    name = f"D12-own-{a.arm}-h{s['signal']['hold_h']}-{tag}"
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D12: билет от своего пика, h24/{a.arm}, срок {s['signal']['hold_h']} ч ({tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
