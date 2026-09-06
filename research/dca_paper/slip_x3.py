#!/usr/bin/env python3
"""Распределение проскальзывания живого исполнителя X3 — по его журналу.

Зачем. Замер издержек DCA-книг (`costs.py`) берёт проскальзывание одним
числом — медианой входа X3 (4.4 б.п.). Одно число скрывает форму: у
проскальзывания хвост (X3: −15.6…+17.1 б.п. на первых сделках, потолок
30), и нижняя граница издержек от верхней отличается именно хвостом.
Здесь та же мера, что на странице `/live-page` (вход против цены
СИГНАЛА, знак нормирован: плюс — хуже нас у обеих сторон), но по всему
журналу и с квантилями. Выходов здесь нет: тейк X3 — лимитка по уровню
(проскальзывание ноль по построению), а у рыночных закрытий цены
сигнала в журнале нет — их проскальзывание не измерено, не ноль.

Читает журнал `bot/out/live` тем же `sverka.read_journal`, что панель.
Пишет `out/DCA-slip-x3.{json,md}` и публикует.

Запуск на VPS: run research/dca_paper/slip_x3.py
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
sys.path.insert(0, os.path.join(ROOT, "bot"))
import sverka as SV                                           # noqa: E402

OUT = os.path.join(HERE, "out")
LIVE = os.path.join(ROOT, "bot", "out", "live")
CAP_BP = 30.0            # потолок проскальзывания входа у исполнителя


def pair(recs):
    """(нога, проскальзывание б.п.) по журналу: решение ↔ открытие."""
    decisions, opens = {}, {}
    for r in recs:
        ev = r.get("ev")
        if ev == "decision":
            k = ":".join((r.get("arm") or "", r.get("hour") or "",
                          r.get("sym") or "", r.get("side") or ""))
            decisions[k] = r
        elif ev == "open":
            opens[r.get("pos")] = r
    out, no_sig, no_entry = [], 0, 0
    for pos, o in opens.items():
        parts = (str(pos).split(":", 3) + ["", "", "", ""])[:4]
        _arm, _hour, sym, side = parts
        d = decisions.get(pos)
        sig = d.get("px") if d else None
        entry = o.get("entry_px")
        if not sig:
            no_sig += 1
            continue
        if not entry:
            no_entry += 1
            continue
        sgn = 1.0 if side == "long" else -1.0
        slip = (float(entry) / float(sig) - 1.0) * 1e4 * sgn
        out.append({"pos": pos, "sym": sym, "side": side, "sig_px": sig,
                    "entry_px": entry, "slip_bp": round(slip, 2),
                    "notional_usd": o.get("notional_usd"),
                    "ts": o.get("ts") or o.get("at")})
    return out, {"opens": len(opens), "no_signal_px": no_sig,
                 "no_entry_px": no_entry}


def _q(v, q):
    return round(float(np.percentile(v, q)), 2) if len(v) else None


def stats(rows):
    v = np.array([r["slip_bp"] for r in rows], dtype=float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "median": round(float(np.median(v)), 2),
            "mean": round(float(v.mean()), 2), "p25": _q(v, 25),
            "p75": _q(v, 75), "p90": _q(v, 90), "min": round(float(v.min()), 2),
            "max": round(float(v.max()), 2),
            "share_worse": round(float(np.mean(v > 0)), 3),
            "share_over_cap": round(float(np.mean(v > CAP_BP)), 3)}


def run(jdir=LIVE, log=print):
    t0 = time.time()
    if not os.path.isdir(jdir):
        log(f"журнала нет: {jdir}")
        return {"present": False, "jdir": jdir}
    recs = SV.read_journal(jdir)
    rows, miss = pair(recs)
    log(f"журнал: записей {len(recs)}, открытий {miss['opens']}, "
        f"с ценой сигнала и входа {len(rows)}; без цены сигнала "
        f"{miss['no_signal_px']}, без цены входа {miss['no_entry_px']}")
    by_side = {sd: stats([r for r in rows if r["side"] == sd])
               for sd in ("long", "short")}
    return {"present": True, "jdir": jdir, "records": len(recs), "miss": miss,
            "all": stats(rows), "by_side": by_side, "cap_bp": CAP_BP,
            "rows": sorted(rows, key=lambda r: r["slip_bp"]),
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def _f(x):
    return "—" if x is None else f"{x:+.1f}"


def report(s):
    P = ["# Проскальзывание живого исполнителя X3 — по журналу", ""]
    if not s.get("present"):
        P.append(f"Журнала нет: `{s.get('jdir')}` — распределение не измерено.")
        return "\n".join(P) + "\n"
    a = s["all"]
    P += [f"Прогон {s['computed_at']} UTC · записей журнала {s['records']} · "
          f"открытий {s['miss']['opens']} · с ценой сигнала и входа {a.get('n', 0)} "
          f"(без цены сигнала {s['miss']['no_signal_px']}, без цены входа "
          f"{s['miss']['no_entry_px']}).", "",
          "Мера — вход против цены СИГНАЛА (та же, что на `/live-page`): "
          "плюс — хуже нас у обеих сторон. Выходы не меряются: тейк X3 — "
          "лимитка по уровню (ноль по построению), у рыночных закрытий цены "
          "сигнала в журнале нет — не измерено, не ноль.", ""]
    if a.get("n"):
        P += ["| срез | n | медиана | среднее | p25 | p75 | p90 | мин | макс | "
              "хуже сигнала | выше потолка 30 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name, st in [("все", a)] + list(s["by_side"].items()):
            if not st.get("n"):
                P.append(f"| {name} | 0 | — | — | — | — | — | — | — | — | — |")
                continue
            P.append(f"| {name} | {st['n']} | {_f(st['median'])} | {_f(st['mean'])} | "
                     f"{_f(st['p25'])} | {_f(st['p75'])} | {_f(st['p90'])} | "
                     f"{_f(st['min'])} | {_f(st['max'])} | "
                     f"{st['share_worse'] * 100:.0f} % | {st['share_over_cap'] * 100:.0f} % |")
        P += ["", "Б.п. от цены сигнала; замер на 300 $ за имя — у крупных "
              "билетов проскальзывание больше, это нижняя граница. В `costs.py` "
              "идёт медиана «все»; p90 — стресс.", ""]
    else:
        P.append("Заполнений с ценой сигнала нет — распределения нет.")
    return "\n".join(P) + "\n"


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="проскальзывание X3 по журналу")
    ap.add_argument("--jdir", default=LIVE)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(jdir=a.jdir)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "DCA-slip-x3.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, "DCA-slip-x3.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        n = (s.get("all") or {}).get("n", 0)
        publish(f"DCA: проскальзывание X3 по журналу ({n} заполнений)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
