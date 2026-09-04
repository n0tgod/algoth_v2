#!/usr/bin/env python3
"""Соответствуют ли режимы DCA своим именам (вопрос владельца 2026-09-04).

Имя режима — ярлык, и проверять его надо числами, иначе оно живёт своей
жизнью. Здесь две группы мер, и путать их нельзя:

* **риск ПОЗИЦИИ** — плечо, квантили исхода, доля тяжёлых убытков,
  ликвидации. Это то, чем режим отличается по построению;
* **риск КНИГИ** — просадка, зелёные дни, укус. Это то, что видит
  владелец, и оно зависит ещё и от ЗАГРУЗКИ: книга, которая почти не
  вложена, выглядит спокойной, не будучи спокойной.

Загрузка считается интегралом занятой маржи по времени, делённым на
`депозит × окно`: сколько денег книга держала в рынке в среднем. Рядом —
доход на ЗАНЯТЫЙ капитал: он показывает, сколько риска приходится на
вложенный доллар, и именно он разводит «спокойная» и «недогруженная».

Свод книги (просадка, зелёные, укус) берётся ИЗ АРТЕФАКТА прогона, а не
пересчитывается: его числа считает сама книга и публикует отчётом, и
вторая реализация здесь однажды разошлась бы с тем, что уехало в git.

Прогон: `run research/dca_paper/name_check.py` (журнал лежит в git, счёт
секундный). Публикует отчёт сам; `--no-publish` выключает.
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
import rules as R                                             # noqa: E402


def load_share(rows, deposit, window=None):
    """Средняя занятая доля депозита: интеграл маржи по времени / окно.

    Считается по событиям «занял / вернул», как касса: доля есть время,
    взвешенное деньгами, а не доля сделок. Пик — максимум одновременно
    занятого.

    **Окно обязано быть ОБЩИМ на все режимы**, иначе редко торгующий
    режим меряется своим коротким окном и выглядит полностью вложенным:
    знаменатель у сравниваемых величин один, иначе сравниваются разные
    вопросы. Своё окно (`window=None`) остаётся только для одиночного
    замера.
    """
    ev = []
    for r in rows:
        ev.append((float(r["at"]), float(r["margin"])))
        ev.append((float(r["exit_ts"]), -float(r["margin"])))
    if not ev:
        return None, None
    ev.sort()
    t0, t1 = (window if window else (ev[0][0], ev[-1][0]))
    if t1 <= t0:
        return None, None
    cur, prev, area, peak = 0.0, t0, 0.0, 0.0
    for (t, d) in ev:
        area += cur * (t - prev)
        prev = t
        cur += d
        peak = max(peak, cur)
    return area / ((t1 - t0) * float(deposit)), peak / float(deposit)


def mode_stats(rows, deposit, window=None):
    """Риск позиции и загрузка книги по строкам одного режима."""
    if not rows:
        return None
    p = np.array([float(r["pnl_frac"]) for r in rows], dtype=float)
    lev = np.array([float(r["lev"]) for r in rows], dtype=float)
    load, peak = load_share(rows, deposit, window=window)
    usd = sum(float(r["usd"]) for r in rows)
    days = {time.strftime("%Y-%m-%d", time.gmtime(float(r["exit_ts"])))
            for r in rows}
    return {
        "n": len(rows), "days": len(days),
        "lev_median": round(float(np.median(lev)), 2),
        "pnl_median": round(float(np.median(p)), 4),
        "pnl_p05": round(float(np.percentile(p, 5)), 4),
        "pnl_worst": round(float(p.min()), 4),
        "heavy_loss": round(float(np.mean(p < -0.5)), 4),
        "liq": sum(1 for r in rows if r.get("exit") == "ликвидация"),
        "load": None if load is None else round(load, 4),
        "peak": None if peak is None else round(peak, 4),
        "usd": round(usd, 2),
        "final": round(usd / float(deposit), 4),
        # доход на ЗАНЯТЫЙ капитал: он и разводит «спокойная» и
        # «недогруженная» — у второй он высокий при скромном итоге книги
        "on_load": (None if not load else round(usd / float(deposit) / load,
                                                3)),
    }


def collect(path=R.JOURNAL, art=R.ARTIFACT):
    rows, bad = R.read_journal(path)
    rows = [r for r in rows if int(r.get("rules", 0)) == R.RULES]
    book = {}
    if os.path.exists(art):
        try:
            with open(art, encoding="utf-8") as f:
                book = (json.load(f) or {}).get("books") or {}
        except (OSError, ValueError):
            book = {}
    out = {"bad_lines": bad, "rules": R.RULES, "deposits": list(R.DEPOSITS),
           "rulers": list(R.RULER_ORDER), "cells": {}, "book": {}}
    for dep in R.DEPOSITS:
        # окно ОДНО на все режимы этого депозита: иначе редко торгующий
        # режим мерился бы своим коротким окном и выходил бы полностью
        # вложенным, ничем себя не выдав
        here = [r for r in rows if int(r.get("dep", 0)) == int(dep)]
        win = ((min(float(r["at"]) for r in here),
                max(float(r["exit_ts"]) for r in here)) if here else None)
        for rk in R.RULER_ORDER:
            mine = [r for r in here if R.ruler_of(r) == rk]
            out["cells"][f"{rk}:{int(dep)}"] = mode_stats(mine, dep,
                                                          window=win)
            b = (book.get(f"{rk}:{int(dep)}") or {}).get("restored") or {}
            out["book"][f"{rk}:{int(dep)}"] = {
                k: b.get(k) for k in
                ("max_dd", "day_green", "bite", "day_median",
                 "usd_wo_top3d")}
    return out


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def _lvl(x, d=2):
    return "—" if x is None else f"{x * 100:.{d}f} %"


def report(s):
    L = ["# DCA — соответствуют ли режимы своим именам", "",
         "Имя режима — ярлык, и проверять его надо числами. Здесь две "
         "группы мер, и они отвечают на РАЗНЫЕ вопросы: риск ПОЗИЦИИ "
         "(плечо, хвост исхода, ликвидации) — то, чем режим отличается по "
         "построению; риск КНИГИ (просадка, зелёные, укус) — то, что "
         "видит владелец. Между ними стоит ЗАГРУЗКА: книга, которая почти "
         "не вложена, выглядит спокойной, не будучи спокойной.", "",
         "Загрузка — интеграл занятой маржи по времени, делённый на "
         "`депозит × окно`: сколько денег книга держала в рынке в среднем, "
         "а не какая доля сделок ей досталась. Доход на занятый капитал "
         "стоит рядом ровно затем, чтобы «спокойная» и «недогруженная» "
         "перестали выглядеть одинаково.", "",
         "Числа позиции — из журнала книг, свод книги — из артефакта "
         "прогона (его считает сама книга; вторая реализация здесь "
         "разошлась бы с тем, что уехало в git). Всё это ПЕРЕСЧЁТ по "
         "прошлому: наблюдения вперёд у режимов ещё нет.", ""]
    for dep in s.get("deposits") or []:
        L += [f"## Депозит ${dep:,.0f}", "",
              "| режим | сделок | дней | плечо | медиана сделки | "
              "5-й процентиль | худшая | доля < −50 % | ликвидаций | "
              "загрузка | пик | итог | на занятый | просадка | зелёных | "
              "укус |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"
              "--:|--:|"]
        for rk in s.get("rulers") or []:
            c = (s.get("cells") or {}).get(f"{rk}:{int(dep)}")
            b = (s.get("book") or {}).get(f"{rk}:{int(dep)}") or {}
            if not c:
                continue
            L.append(
                f"| {R.ruler_title(rk)} | {c['n']} | {c['days']} | "
                f"{c['lev_median']}× | {_pct(c['pnl_median'])} | "
                f"{_pct(c['pnl_p05'])} | {_pct(c['pnl_worst'])} | "
                f"{_lvl(c['heavy_loss'])} | {c['liq']} | "
                f"{_lvl(c['load'], 1)} | {_lvl(c['peak'], 1)} | "
                f"{_pct(c['final'])} | "
                + ("—" if c["on_load"] is None
                   else f"{c['on_load'] * 100:+.0f} %") + " | "
                + _pct(b.get("max_dd")) + " | "
                + ("—" if b.get("day_green") is None
                   else f"{b['day_green']:.2f}") + " | "
                + ("—" if b.get("bite") is None else f"{b['bite']}") + " |")
        L.append("")
    # вердикт выводится ИЗ ЧИСЕЛ, а не стоит рядом с ними
    dep = (s.get("deposits") or [None])[-1]
    cells = s.get("cells") or {}
    loads = {rk: (cells.get(f"{rk}:{int(dep)}") or {}).get("load")
             for rk in s.get("rulers") or []}
    ok = {k: v for k, v in loads.items() if v}
    L += ["## Что из этого следует", ""]
    if ok:
        top = max(ok, key=lambda k: ok[k])
        thin = [k for k in ok if ok[k] < 0.5 * ok[top]]
        for k in thin:
            c = cells.get(f"{k}:{int(dep)}") or {}
            L += [f"**«{R.ruler_title(k).capitalize()}» вложена вдвое с "
                  f"лишним меньше самой вложенной книги: {_lvl(ok[k], 1)} "
                  f"против {_lvl(ok[top], 1)} — столько держит "
                  f"«{R.ruler_title(top)}».** "
                  "Значит её просадка и укус описывают не спокойствие "
                  "правила, а НЕДОГРУЗ: на занятый доллар она даёт "
                  + ("—" if c.get("on_load") is None
                     else f"{c['on_load'] * 100:+.0f} %")
                  + f" при доле тяжёлых убытков {_lvl(c.get('heavy_loss'))}"
                  ". Имя описывает вход (плечо), а не риск книги.", ""]
        if not thin:
            L += ["Загрузка режимов сопоставима, значит риск книги можно "
                  "сравнивать напрямую: имена описывают то же, что "
                  "показывают просадка и укус.", ""]
    L += ["Оговорка на все числа: окно записи одно, режим рынка один, "
          "веса модели видели эти часы. Это пересчёт по прошлому, а не "
          "наблюдение вперёд.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(R.OUT, exist_ok=True)
    s = collect()
    with open(os.path.join(R.OUT, "DCA-names.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-names.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("DCA: соответствуют ли режимы своим именам")


if __name__ == "__main__":
    main()
