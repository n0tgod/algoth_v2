#!/usr/bin/env python3
"""Вопрос владельца (2026-08-31): пережили ли СОГЛАСНЫЕ сделки слив
08-24…27 так же, как книги целиком?

Зонд согласия проверял устойчивость половинами истории, а слив — это
четыре конкретных дня. Здесь тот же флаг согласия (из выборов, машина
`agree.py` — вторая копия не заводится) разрезается окном слива по
ДНЮ ДЕНЕГ (момент выхода/разбора, правило лиги и разбора слива):
внутри окна и вне его — числа обеих групп, Δ и перестановочный p с
тем же внутридневным нулём, только по сделкам окна.

Деньги ($) здесь печатаются НАРЯДУ с б.п. — внутри одной ячейки они
сравнимы (одна касса), а вопрос владельца ровно про деньги слива.
Худшее имя каждой группы в окне называется поимённо: слив делали
конкретные шорты, и «согласным» он был или «одиночным» — это и есть
ответ.

Это ответ на вопрос, не вердикт: окно одно, объявлено чужим разбором
(probe_drain, 2026-08-24…27) до этого вопроса, и не перебиралось.

    .venv/bin/python research/probe_agree/drain.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "probe_setups"))
sys.path.insert(0, os.path.join(RESEARCH, "probe_turn"))

import agree as AG                                        # noqa: E402
import setups as SP                                       # noqa: E402
import turn as PT                                         # noqa: E402

DRAIN = ("2026-08-24", "2026-08-27")   # окно разбора слива, включительно
MIN_GRP = 10                           # тоньше — числа с пометкой


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def date_of(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc) \
        .date().isoformat()


def in_drain(ts):
    d = date_of(ts)
    return DRAIN[0] <= d <= DRAIN[1]


def grp_stats(rows):
    """Числа одной группы: сделок, средний б.п., сумма $, худшее имя."""
    if not rows:
        return {"n": 0, "mean_bp": None, "pnl": 0.0,
                "worst_sym": None, "worst_pnl": None}
    by = {}
    for r in rows:
        by[r["sym"]] = by.get(r["sym"], 0.0) + r["pnl"]
    worst = min(by, key=by.get)
    return {"n": len(rows),
            "mean_bp": sum(r["net"] for r in rows) / len(rows),
            "pnl": sum(r["pnl"] for r in rows),
            "worst_sym": worst, "worst_pnl": by[worst]}


def split_cell(rows):
    """Ячейка → окно слива и остальное, каждая часть по группам."""
    out = {}
    for part, sel in (("слив", [r for r in rows if in_drain(r["ts"])]),
                      ("вне", [r for r in rows
                               if not in_drain(r["ts"])])):
        agr = [r for r in sel if r["agree"]]
        sol = [r for r in sel if not r["agree"]]
        rec = {"agree": grp_stats(agr), "solo": grp_stats(sol),
               "thin": len(agr) < MIN_GRP or len(sol) < MIN_GRP,
               "delta_bp": None, "p": None}
        if agr and sol:
            rec["delta_bp"] = (rec["agree"]["mean_bp"]
                               - rec["solo"]["mean_bp"])
            if not rec["thin"]:
                trades = [{"ts": r["ts"], "net": r["net"],
                           "agree": r["agree"]} for r in sel]
                rec["p"] = AG.perm_p(trades, rec["delta_bp"])
        out[part] = rec
    assert out["слив"]["agree"]["n"] + out["слив"]["solo"]["n"] \
        + out["вне"]["agree"]["n"] + out["вне"]["solo"]["n"] \
        == len(rows), "разрез потерял сделки"
    return out


def by_day_table(rows, days):
    out = []
    for d in days:
        sel = [r for r in rows if date_of(r["ts"]) == d]
        agr = [r for r in sel if r["agree"]]
        sol = [r for r in sel if not r["agree"]]
        out.append((d, grp_stats(agr), grp_stats(sol)))
    return out


def fmt_bp(v):
    return "—" if v is None else f"{v:+.0f}"


def fmt_p(v):
    return "—" if v is None else f"{v:.3f}"


def write_report(path, cells, day_rows, meta):
    L = ["# Согласие рук в окне слива 08-24…27\n"]
    L.append(f"Прогон {meta['when']} · окно слива {DRAIN[0]}…{DRAIN[1]}"
             " (день ДЕНЕГ, UTC — правило лиги) · флаг согласия из "
             "выборов, машина agree.py · группа тоньше "
             f"{MIN_GRP} сделок помечена «тонко», p не считается\n")
    L.append("**Ответ на вопрос владельца, не вердикт: окно одно и "
             "объявлено разбором слива до вопроса.** Δ — среднее б.п. "
             "согласных минус одиночных; p — внутридневная "
             "перестановка ТОЛЬКО по сделкам части.\n")
    L.append("| ячейка | часть | обе: n / ср. б.п. / Σ $ | одна: n / "
             "ср. б.п. / Σ $ | Δ б.п. | p | худшее имя (обе) | худшее "
             "имя (одна) |")
    L.append("|---|---|--:|--:|--:|--:|---|---|")
    for name, parts in cells.items():
        for part in ("слив", "вне"):
            r = parts[part]
            a, s = r["agree"], r["solo"]
            thin = " ·тонко" if r["thin"] and part == "слив" else ""
            L.append(
                f"| {name} | {part}{thin} | "
                f"{a['n']} / {fmt_bp(a['mean_bp'])} / {a['pnl']:+.0f} | "
                f"{s['n']} / {fmt_bp(s['mean_bp'])} / {s['pnl']:+.0f} | "
                f"{fmt_bp(r['delta_bp'])} | {fmt_p(r['p'])} | "
                + (f"{a['worst_sym']} {a['worst_pnl']:+.0f}"
                   if a["worst_sym"] else "—")
                + " | "
                + (f"{s['worst_sym']} {s['worst_pnl']:+.0f}"
                   if s["worst_sym"] else "—") + " |")
    L.append("\n## Дни слива у книги 24 ч (обе руки разом)\n")
    L.append("| день | обе: n / Σ $ | одна: n / Σ $ |")
    L.append("|---|--:|--:|")
    for d, a, s in day_rows:
        L.append(f"| {d} | {a['n']} / {a['pnl']:+.0f} | "
                 f"{s['n']} / {s['pnl']:+.0f} |")
    L.append("\nЧитать: Σ $ сравнимы только ВНУТРИ ячейки (одна "
             "касса). Согласных сделок ~пятая часть — их Σ $ надо "
             "читать рядом с их долей, а не против всей книги.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="согласие в окне слива")
    ap.add_argument("--s8", default=os.path.join(
        RESEARCH, "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)

    days = []
    d0 = datetime.strptime(DRAIN[0], "%Y-%m-%d")
    while d0.date().isoformat() <= DRAIN[1]:
        days.append(d0.date().isoformat())
        d0 = datetime.fromtimestamp(d0.timestamp() + 86400)

    cells = {}
    h24_rows = []
    for hz, name in SP.BOOKS:
        mdir = os.path.join(a.s8, name)
        got = SP.book_rows(mdir, hz)
        rows = got[0] if got else []
        if not rows:
            log_(f"{hz}: сделок нет — пропуск")
            continue
        AG.flag_rows(rows, AG.pick_keys(mdir))
        if hz == "h24":
            h24_rows = rows
        for arm in SP.ARMS:
            sub = [r for r in rows if r["arm"] == arm]
            if sub:
                cells[f"{hz} · {arm}"] = split_cell(sub)
                log_(f"{hz} · {arm}: слив "
                     f"{cells[f'{hz} · {arm}']['слив']['agree']['n']}"
                     f"+{cells[f'{hz} · {arm}']['слив']['solo']['n']}")
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC")}
    path = write_report(
        os.path.join(OUT, f"AGREE-drain-{a.tag}.md"),
        cells, by_day_table(h24_rows, days), meta)
    with open(os.path.join(OUT, f"agree-drain-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"meta": meta, "cells": cells}, f,
                  ensure_ascii=False, default=str)
    log_(f"отчёт: {path}")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
