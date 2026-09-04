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

Книг шесть: две линейки плеча × три депозита. По депозиту книги
отличаются РОВНО им — билет один и тот же ($25, вывод — `rules.TICKET`),
поэтому число мест растёт вместе с деньгами: 40 / 400 / 4000. По линейке
отличается то, из чего выводится плечо (`rules.RULERS`): «безопасная»
считает запас от собственной σ имени, «оптимальная» — от глубины
лестницы. Обе ведутся параллельно: какая лучше, решает форвард.

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

# Линейки плеча объявлены В ПРАВИЛАХ, а не здесь: их читает и страница
# наблюдения, и вторая запись однажды разошлась бы с той, по которой
# книга торгует.
RULERS = {k: (v["rule"], v["param"]) for k, v in R.RULERS.items()}


def _key(r):
    """Ключ решения: имя плюс секунда входа. Ими и дедуплицируется."""
    return f"{int(r['at'])}:{r['sym']}"


def _cell(ruler, dep):
    """Ключ книги: линейка и депозит. Одно решение живёт в обеих книгах,
    и склеив их одним ключом, мы потеряли бы вторую целиком."""
    return f"{ruler}:{int(dep)}"


def build_rows(by_ruler, now=None, log=print):
    """Решения, взятые каждой книгой, с деньгами в долларах.

    Одна позиция на имя применяется ДО раздачи кассы: правило биржи не
    зависит от депозита, и применив его после, мы дали бы разным книгам
    разные составы по чужой причине. По линейкам состав РАЗЛИЧАЕТСЯ
    законно: ограда отказывает по-разному, и это свойство линейки, а не
    артефакт — числа отказов печатаются по каждой отдельно.
    """
    now = float(now if now is not None else time.time())
    out, cells, one = [], {}, {}
    for rk in R.RULER_ORDER:
        recs = by_ruler.get(rk) or []
        keep, skipped = (D6.one_per_name(recs) if R.ONE_PER_NAME
                         else (list(recs), 0))
        one[rk] = {"positions": len(recs), "kept": len(keep),
                   "skipped_repeats": skipped}
        log(f"линейка {R.ruler_title(rk)} ({rk}): позиций {len(recs)}, "
            f"после правила одной на имя {len(keep)}")
        for dep in R.DEPOSITS:
            rows = []
            c = D6.ration(keep, R.share(dep), deposit=dep,
                          min_notional=R.MIN_NOTIONAL, keep_rows=rows)
            c["slots"] = R.slots(dep)
            cells[_cell(rk, dep)] = c
            for (r, margin) in rows:
                out.append({
                    "dep": int(dep), "ruler": rk, "at": float(r["at"]),
                    "exit_ts": float(r["exit_ts"]), "sym": r["sym"],
                    "lev": round(float(r["lev"]), 3),
                    "margin": round(float(margin), 4),
                    "pnl_frac": round(float(r["pnl"]), 6),
                    "usd": round(float(r["pnl"]) * float(margin), 4),
                    "exit": r.get("exit"), "written_at": now,
                    "rules": R.RULES})
            log(f"  депозит ${dep:,.0f}: мест {c['slots']}, "
                f"взято {c['taken']}, нет кассы {c['no_cash']}, "
                f"мельче ${R.MIN_NOTIONAL:g} {c['too_small']}")
    return out, cells, one


def append_journal(rows, path=R.JOURNAL, log=print):
    """Дописывает только НОВЫЕ решения. Запись write-ahead: строка,
    однажды попавшая в журнал, не переписывается — иначе момент записи
    можно было бы подвинуть, и «вперёд» перестало бы что-то значить."""
    old, bad = R.read_journal(path)
    # Ключ дедупа несёт ЛИНЕЙКУ: одно решение живёт в обеих книгах, и без
    # неё вторая книга целиком читалась бы повтором первой и не писалась
    # бы никогда.
    seen = {(R.ruler_of(r), r.get("dep"), _key(r)) for r in old}
    fresh = [r for r in rows
             if (R.ruler_of(r), r["dep"], _key(r)) not in seen]
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
    # Концентрация по ДНЯМ — не то же, что по именам: один рыночный
    # эпизод раздаёт деньги десяткам имён сразу, и колонка «без лучшего
    # имени» его не видит. Три дня из трёх вычитать нечего, поэтому там
    # величина НЕ измерена, а не равна нулю.
    top3 = sorted(v, reverse=True)[:3]
    wo3d = (round(float(v.sum() - sum(top3)), 2) if len(ks) > 3 else None)
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
        "top_day": ks[int(np.argmax(v))],
        "usd_wo_top3d": wo3d,
        "names": len({r["sym"] for r in rows}),
    }


def summarize(path=R.JOURNAL):
    """Свод по книгам: наблюдение и пересчёт ПОРОЗНЬ, никогда не в сумме.

    Книга есть пара «линейка × депозит», и ключ свода несёт обе: склеив
    их по депозиту, мы сложили бы две книги в одну кривую.
    """
    rows, bad = R.read_journal(path)
    out = {"bad_lines": bad, "books": {},
           "rulers": list(R.RULER_ORDER), "deposits": list(R.DEPOSITS)}
    for rk in R.RULER_ORDER:
        for dep in R.DEPOSITS:
            mine = [r for r in rows if int(r.get("dep", 0)) == int(dep)
                    and int(r.get("rules", 0)) == R.RULES
                    and R.ruler_of(r) == rk]
            fwd, back = R.split_rows(mine)
            out["books"][_cell(rk, dep)] = {
                "deposit": dep, "ruler": rk, "ruler_title": R.ruler_title(rk),
                "slots": R.slots(dep), "ticket": R.TICKET,
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
         "восстанавливает накопленное — оно всё помечено пересчётом.", "",
         "**Две колонки концентрации отвечают на РАЗНЫЕ вопросы.** «Без "
         "лучшего имени» ловит одну разогнанную монету; «без 3 лучших "
         "дней» ловит один рыночный эпизод, который раздаёт деньги "
         "десяткам имён разом, и первой колонке он невидим. Если вторая "
         "уводит итог в минус, книга описывает не правило, а тот эпизод. "
         "У книги моложе четырёх дней вычитать нечего, и там стоит "
         "прочерк — величина не измерена, а не равна нулю.", "",
         "**Линеек плеча две, и книг поэтому шесть.** Плечо не настройка "
         "агрессивности: оно выводится из неравенства безопасности. "
         + " ".join(f"**{v['title'].capitalize()}** — {v['plain']}"
                    for k, v in ((k, R.RULERS[k]) for k in R.RULER_ORDER))
         + " Имена — ярлыки, а не вердикт: какая линейка лучше, покажет "
         "форвард, и обе ведутся параллельно ровно затем, чтобы вопрос "
         "решали числа, а не выбор задним числом.", ""]
    for name, key in (("Наблюдение (записано вперёд)", "forward"),
                      ("Пересчёт по прошлому", "restored")):
        L += [f"## {name}", "",
              "| линейка | депозит | мест | сделок | имён | дней | $ | "
              "к депозиту | просадка | медиана дня | худший день | "
              "зелёных | укус | $ без лучшего имени | $ без 3 лучших дней |",
              "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        # порядок «депозит, внутри линейки» ставит пару рядом: сравнивают
        # линейки при ОДНОМ депозите, а не депозиты при одной линейке
        for dep in R.DEPOSITS:
            for rk in R.RULER_ORDER:
                b = (s.get("books") or {}).get(_cell(rk, dep)) or {}
                nm, st = R.ruler_title(rk), b.get(key)
                if not st:
                    L.append(f"| {nm} | ${dep:,.0f} | "
                             f"{b.get('slots', '—')} | 0 | — | — | — | — | "
                             "— | — | — | — | — | — | — |")
                    continue
                L.append(
                    f"| {nm} | ${dep:,.0f} | {b['slots']} | {st['n']} | "
                    f"{st['names']} | {st['days']} | {st['usd']:,.2f} | "
                    f"{_pct(st['final'])} | {_pct(st['max_dd'])} | "
                    f"{_pct(st['day_median'], 3)} | "
                    f"{_pct(st['day_worst'])} | {st['day_green']:.2f} | "
                    f"{'—' if st['bite'] is None else st['bite']} | "
                    f"{st['usd_wo_top']:,.2f} | "
                    + ("—" if st.get("usd_wo_top3d") is None
                       else f"{st['usd_wo_top3d']:,.2f}") + " |")
        L.append("")
        if key == "forward" and all(
                not ((s.get("books") or {}).get(_cell(rk, d)) or {}).get(key)
                for d in R.DEPOSITS for rk in R.RULER_ORDER):
            L += ["Наблюдения ещё нет ни у одной книги, и это не пустота "
                  "показа: журнал начат сегодня, а решение попадает сюда "
                  "только после того, как его позиция закрылась. Первые "
                  "строки появятся следующим суточным прогоном.", ""]
    cells = s.get("cells") or {}
    L += ["## Что связывает депозит", ""]
    if not cells:
        L += ["Числа отказов даёт только счётный прогон, а этот был "
              "пересборкой свода из журнала. Прочерка тут нет: величины "
              "не потеряны, их просто не считали сегодня.", ""]
    else:
        L += [f"Числа счётного прогона {s.get('computed_at') or ''}. "
              "Касса раздаёт деньги по очереди решений, поэтому книга, "
              "которой не хватает мест, берёт не лучшие сигналы, а "
              "первые: отказ по кассе меняет не только объём, но и "
              "СОСТАВ.", "",
              "| линейка | депозит | мест | взято | нет кассы | "
              "мельче пола |", "|---|---|--:|--:|--:|--:|"]
        for dep in R.DEPOSITS:
            for rk in R.RULER_ORDER:
                c = cells.get(_cell(rk, dep))
                if not c:
                    continue
                L.append(f"| {R.ruler_title(rk)} | ${dep:,.0f} | "
                         f"{c.get('slots', '—')} | {c.get('taken', '—')} | "
                         f"{c.get('no_cash', '—')} | "
                         f"{c.get('too_small', '—')} |")
        L.append("")
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
        keys = list(R.RULER_ORDER)
        got = D6.collect_recs(limit=a.limit,
                              rulers=[RULERS[k] for k in keys])
        rows, cells, one = build_rows(
            {k: got["recs"][RULERS[k]] for k in keys})
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
                  "FLOOR_FRAC": R.FLOOR_FRAC,
                  "RULERS": {k: dict(R.RULERS[k]) for k in R.RULER_ORDER},
                  "RULER_ORDER": list(R.RULER_ORDER)}
    with open(R.ARTIFACT, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-paper.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("DCA: бумажные книги, две линейки плеча × три депозита")


if __name__ == "__main__":
    main()
