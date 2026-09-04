#!/usr/bin/env python3
"""Бумажные DCA-книги: одни правила, три депозита ($1k / $10k / $100k).

Что это и чем НЕ является. Книга ведёт запись ВПЕРЁД: суточный прогон
дописывает в журнал решения, чьи исходы уже закрылись, и помечает каждое
моментом записи. Решение, попавшее в журнал позже `rules.AHEAD_H` часов
после самого себя, есть ПЕРЕСЧЁТ по прошлому, а не наблюдение, и в одну
сумму с наблюдением не идёт никогда (`rules.split_rows`). Первый прогон
восстанавливает всю накопленную историю — она вся помечена пересчётом.

Живого исполнения здесь нет: сделки считаются реплеем по барам записи, а
не сканером на живой цене. Что для настоящего живого контура пришлось бы
достроить, названо в отчёте, а не подразумевается.

Три книги отличаются РОВНО депозитом. Билет один и тот же ($25, вывод —
`rules.TICKET`), поэтому число мест растёт вместе с деньгами: 40 / 400 /
4000. Это и есть предмет сравнения: что покупает депозит.

Биржевое правило соблюдается с первого дня: у имени позиция ОДНА, второй
выбор по той же монете пропускается (`rules.ONE_PER_NAME`).

Прогон: `run research/dca_paper/run_paper.py`. Смоук: `--limit 400`.
Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))      # корень репозитория
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import run_d6 as D6                                           # noqa: E402

RULER = ("depth", R.SURVIVE_MULT)      # ограда книг = база D3/D4


def _key(r):
    """Ключ решения: имя плюс секунда входа. Ими и дедуплицируется."""
    return f"{int(r['at'])}:{r['sym']}"


def build_rows(recs, now=None, log=print):
    """Решения, взятые каждой книгой, с деньгами в долларах.

    Одна позиция на имя применяется ДО раздачи кассы: правило биржи не
    зависит от депозита, и применив его после, мы дали бы разным книгам
    разные составы по чужой причине.
    """
    now = float(now if now is not None else time.time())
    keep, skipped = (D6.one_per_name(recs) if R.ONE_PER_NAME
                     else (list(recs), 0))
    out, cells = [], {}
    for dep in R.DEPOSITS:
        rows = []
        c = D6.ration(keep, R.share(dep), deposit=dep,
                      min_notional=R.MIN_NOTIONAL, keep_rows=rows)
        c["slots"] = R.slots(dep)
        cells[str(int(dep))] = c
        for (r, margin) in rows:
            out.append({
                "dep": int(dep), "at": float(r["at"]),
                "exit_ts": float(r["exit_ts"]), "sym": r["sym"],
                "lev": round(float(r["lev"]), 3),
                "margin": round(float(margin), 4),
                "pnl_frac": round(float(r["pnl"]), 6),
                "usd": round(float(r["pnl"]) * float(margin), 4),
                "exit": r.get("exit"), "written_at": now,
                "rules": R.RULES})
        log(f"  депозит ${dep:,.0f}: мест {c['slots']}, взято {c['taken']}, "
            f"нет кассы {c['no_cash']}, мельче ${R.MIN_NOTIONAL:g} "
            f"{c['too_small']}")
    return out, cells, {"kept": len(keep), "skipped_repeats": skipped}


def append_journal(rows, path=R.JOURNAL, log=print):
    """Дописывает только НОВЫЕ решения. Запись write-ahead: строка,
    однажды попавшая в журнал, не переписывается — иначе момент записи
    можно было бы подвинуть, и «вперёд» перестало бы что-то значить."""
    old, bad = R.read_journal(path)
    seen = {(r.get("dep"), _key(r)) for r in old}
    fresh = [r for r in rows if (r["dep"], _key(r)) not in seen]
    if fresh:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in fresh:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log(f"журнал: было {len(old)}, дописано {len(fresh)}"
        + (f", битых строк {bad}" if bad else ""))
    return {"had": len(old), "added": len(fresh), "bad": bad}


def _stats(rows, deposit):
    """Итог, просадка и форма по дням — на ЭТОМ подмножестве строк."""
    if not rows:
        return None
    day = {}
    for r in rows:
        d = time.strftime("%Y-%m-%d", time.gmtime(float(r["exit_ts"])))
        day[d] = day.get(d, 0.0) + float(r["usd"])
    ks = sorted(day)
    v = np.array([day[k] for k in ks], dtype=float)
    eq = float(deposit) + np.cumsum(v)
    dd = float(np.min(eq / np.maximum.accumulate(eq) - 1.0))
    pos = [x for x in v if x > 0]
    best = max(rows, key=lambda r: float(r["usd"]))
    wo = sum(float(r["usd"]) for r in rows if r["sym"] != best["sym"])
    return {
        "n": len(rows), "days": len(ks),
        "usd": round(float(v.sum()), 2),
        "final": round(float(v.sum()) / float(deposit), 4),
        "max_dd": round(dd, 4),
        "day_median": round(float(np.median(v)) / float(deposit), 5),
        "day_worst": round(float(np.min(v)) / float(deposit), 4),
        "day_green": round(float(np.mean(v > 0)), 3),
        # укус: |худший день| / медиана прибыльного дня (мера устойчивости)
        "bite": (round(abs(float(np.min(v))) / float(np.median(pos)), 1)
                 if pos and float(np.median(pos)) > 0 else None),
        "top_sym": best["sym"],
        "usd_wo_top": round(wo, 2),
        "names": len({r["sym"] for r in rows}),
    }


def summarize(path=R.JOURNAL):
    """Свод по книгам: наблюдение и пересчёт ПОРОЗНЬ, никогда не в сумме."""
    rows, bad = R.read_journal(path)
    out = {"bad_lines": bad, "books": {}}
    for dep in R.DEPOSITS:
        mine = [r for r in rows if int(r.get("dep", 0)) == int(dep)
                and int(r.get("rules", 0)) == R.RULES]
        fwd, back = R.split_rows(mine)
        out["books"][str(int(dep))] = {
            "deposit": dep, "slots": R.slots(dep), "ticket": R.TICKET,
            "forward": _stats(fwd, dep), "restored": _stats(back, dep),
            "n_forward": len(fwd), "n_restored": len(back)}
    return out


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def report(s):
    L = ["# DCA — бумажные книги на трёх депозитах", "",
         "Три книги отличаются РОВНО депозитом: правила, гейты, ограда и "
         "выходы у них одни. Билет тоже один — "
         f"**${R.TICKET:g}**, — поэтому с деньгами растёт число мест, и "
         "это и есть предмет сравнения: что депозит покупает.", "",
         "**Билет выведен из пола биржи, а не назначен.** Минимальный "
         f"ордер площадки ровно ${R.MIN_NOTIONAL:g}, самый мелкий рунг "
         f"лестницы — {R.RUNG_SHARE:g} нотионала, значит нотионал не "
         "бывает меньше $20, а маржа — меньше $20/плечо; забор выдаёт от "
         "1×, то есть худший случай требует ровно $20. Четверть сверху — "
         "запас на просадку: маржа считается от текущего счёта и проседает "
         "вместе с ним.", "",
         "**Биржевое правило соблюдается с первого дня:** у имени позиция "
         "одна, второй выбор по той же монете пропущен. Реплей D-серии "
         "этого не делал, и его «пик 3206» описывал ЛОТЫ, а не позиции.",
         "",
         "**Наблюдение и пересчёт не складываются никогда.** Решение "
         f"считается записанным вперёд, если попало в журнал не позже "
         f"{R.AHEAD_H} ч после самого себя (предел жизни позиции "
         f"{R.HOLD_H} ч плюс двое суток на прогон). Первый прогон "
         "восстанавливает накопленное — оно всё помечено пересчётом.", ""]
    for name, key in (("Наблюдение (записано вперёд)", "forward"),
                      ("Пересчёт по прошлому", "restored")):
        L += [f"## {name}", "",
              "| депозит | мест | сделок | имён | дней | $ | к депозиту | "
              "просадка | медиана дня | худший день | зелёных | укус | "
              "$ без лучшего имени |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for dep in R.DEPOSITS:
            b = (s.get("books") or {}).get(str(int(dep))) or {}
            st = b.get(key)
            if not st:
                L.append(f"| ${dep:,.0f} | {b.get('slots', '—')} | 0 | — | "
                         "— | — | — | — | — | — | — | — | — |")
                continue
            L.append(
                f"| ${dep:,.0f} | {b['slots']} | {st['n']} | {st['names']} | "
                f"{st['days']} | {st['usd']:,.2f} | {_pct(st['final'])} | "
                f"{_pct(st['max_dd'])} | {_pct(st['day_median'], 3)} | "
                f"{_pct(st['day_worst'])} | {st['day_green']:.2f} | "
                f"{'—' if st['bite'] is None else st['bite']} | "
                f"{st['usd_wo_top']:,.2f} |")
        L.append("")
        if key == "forward" and all(
                not ((s.get("books") or {}).get(str(int(d))) or {}).get(key)
                for d in R.DEPOSITS):
            L += ["Наблюдения ещё нет ни у одной книги, и это не пустота "
                  "показа: журнал начат сегодня, а решение попадает сюда "
                  "только после того, как его позиция закрылась. Первые "
                  "строки появятся следующим суточным прогоном.", ""]
    L += ["## Чего эти числа НЕ описывают", "",
          "Живого исполнения здесь нет: сделки считаются реплеем по барам "
          "записи, а не сканером на живой цене. Значит не моделируются "
          "проскальзывание, очередь в стакане и задержка входа; долив "
          "лотов в одно имя запрещён правилом, а не сведён в позицию, то "
          "есть маржа и цена ликвидации по-прежнему считаются по каждой "
          "позиции отдельно — на бирже они считаются по слитой. Веса "
          "модели видели эти часы, поэтому пересчёт читается как оценка "
          "СВЕРХУ. Период один и режим рынка один.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--restat", action="store_true",
                    help="пересобрать свод и отчёт из журнала, не считая")
    a = ap.parse_args()
    os.makedirs(R.OUT, exist_ok=True)
    t0 = time.time()
    extra = {}
    if not a.restat:
        got = D6.collect_recs(limit=a.limit, rulers=[RULER])
        rows, cells, one = build_rows(got["recs"][RULER])
        append_journal(rows)
        extra = {"positions": got["positions"], "skipped": got["skipped"],
                 "window": got["window"], "cells": cells, "one_name": one}
    s = summarize()
    s.update(extra)
    s["secs"] = round(time.time() - t0, 1)
    s["rules"] = {"RULES": R.RULES, "TICKET": R.TICKET,
                  "DEPOSITS": R.DEPOSITS, "AHEAD_H": R.AHEAD_H,
                  "HOLD_H": R.HOLD_H, "ONE_PER_NAME": R.ONE_PER_NAME,
                  "MIN_EDGE_BP": R.MIN_EDGE_BP, "MIN_RR": R.MIN_RR,
                  "SURVIVE_MULT": R.SURVIVE_MULT,
                  "FLOOR_FRAC": R.FLOOR_FRAC}
    with open(R.ARTIFACT, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-paper.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("DCA: бумажные книги на трёх депозитах")


if __name__ == "__main__":
    main()
