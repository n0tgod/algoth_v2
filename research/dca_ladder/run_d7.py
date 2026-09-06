#!/usr/bin/env python3
"""D7 — замер СРОКА удержания DCA-книги (вопрос владельца 2026-09-04).

Вопрос: «может лучше не 2 дня, а 3 или неделя, может 1 день». Нынешнее
правило — `D2.HOLD_H = 72 ч`, то есть трое суток, и оно назначено, а не
измерено. Здесь сетка сроков объявлена ДО прогона и печатаются ВСЕ
ячейки:

    сроки  1 / 2 / 3 / 5 / 7 суток   (24 / 48 / 72 / 120 / 168 ч)

**Срок — свойство ОБОРОТА книги, а не позиции, и мерить его сумой долей
позиции нельзя.** Длинная позиция держит слот и отказывает новым
сигналам по кассе, короткая освобождает его раньше; поэтому каждая
ячейка прогоняется через ту же кассу, что ведёт бумажные книги
(`D6.ration` с билетом `rules.ticket`), и метрики формы считаются тем же
`run_paper._stats`, что печатает страница наблюдения. Второй реализации
ни кассы, ни формы здесь нет.

**Один проход на все сроки.** Симуляция идёт по самому длинному сроку с
контрольными точками (`ladder.simulate_dca(checkpoints=…)`): на границе
каждого срока запоминается переоценка по закрытию ПОСЛЕДНЕГО бара окна —
ровно то, чем кончилась бы симуляция с этим сроком. Равенство усечения
прямой симуляции закреплено тестом: пересчёт, дающий другие числа, есть
другая мера.

**Выборка одна на все сроки.** Решение годится, только если запись
доживает до конца САМОГО ДЛИННОГО срока: иначе длинные сроки судились бы
по обрезанным сделкам, а короткие по полным. Сколько решений выброшено —
печатается числом.

Чего замер НЕ делает: не меняет правил книги (это отдельное решение
владельца — вместе со сроком двигается `rules.AHEAD_H = HOLD_H + 48`),
не мерит вторую линейку плеча (считается «оптимальная», база
агрессивного режима), не моделирует живое исполнение.

Прогон: `run research/dca_ladder/run_d7.py`. Смоук: `--limit 400`.
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
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as PP                                        # noqa: E402

OUT = os.path.join(HERE, "out")
HOUR = 3600

# --- сетка объявлена ДО прогона ----------------------------------------
# 72 ч — нынешнее правило книги, оно же точка отсчёта. Верх сетки — неделя
# (владелец назвал её сам); дальше идти незачем: окно записи 26 суток, и
# при сроке в декаду общая выборка теряет больше трети календаря.
HOLDS_H = [24, 48, 72, 120, 168]
REF_H = D2.HOLD_H
# Допуск на границе окна: бары минутные, и последний бар срока стоит не
# ровно на границе. Больше двух минут разрыва означает дыру записи, а не
# округление — такой исход «по сроку» не измерен.
TOL_S = 120
RULER = ("depth", D2.SURVIVE_MULT if hasattr(D2, "SURVIVE_MULT")
         else R.SURVIVE_MULT)
# Ключ режима бумажной книги, чью кассу мы занимаем: билет считается из
# пола и пика РЕЖИМА, поэтому имя обязано совпадать с линейкой выше.
RULER_KEY = "optimal"
# Два места, решающих одно, однажды разойдутся — поэтому совпадение
# доказывается, а не подразумевается.
assert RULER == (R.RULERS[RULER_KEY]["rule"], R.RULERS[RULER_KEY]["param"]), (
    RULER, R.RULERS[RULER_KEY])


def truncate(r, hold_h, idx):
    """Исход ТОЙ ЖЕ позиции при сроке `hold_h`; None — измерить нечем.

    Выход раньше границы (тейк, пол, ликвидация) от срока не зависит
    вовсе — он случился бы и при более длинном окне. Позже границы —
    сделка закрывается по сроку: цена та же, что у контрольной точки, то
    есть закрытие последнего бара, вошедшего в окно.

    `marks` (почасовые приращения для кривой кассы) обрезаются по часу
    границы, а последнее приращение правится так, чтобы их сумма равнялась
    исходу: касса складывает именно их, и разойдись сумма с pnl, кривая
    книги считала бы движение ПОСЛЕ выхода. Внутричасовая доля остаётся
    приближением — кривая и так почасовая.
    """
    lim = float(r["at"]) + float(hold_h) * HOUR
    if float(r["exit_ts"]) <= lim:
        # Выход по УРОВНЮ (тейк, пол, ликвидация) от срока не зависит и
        # честен при любом окне. А вот «срок» на ОБРЫВЕ ряда честным не
        # является: запись просто кончилась раньше границы, и выдать это
        # за исход срока значило бы измерить длину записи, а не правило.
        if r.get("exit") == "срок" and float(r.get("end_ts") or 0) + TOL_S                 < lim:
            return None
        return dict(r)
    ck = (r.get("ckpt") or [None] * (idx + 1))[idx]
    if not ck:
        return None                     # ряд кончился раньше границы
    _t_grid, t_bar, pnl = ck
    hr_lim = int(t_bar) - int(t_bar) % HOUR
    marks = [(h, d) for (h, d) in (r.get("marks") or []) if h <= hr_lim]
    if marks:
        fix = float(pnl) - sum(d for (_h, d) in marks)
        marks[-1] = (marks[-1][0], marks[-1][1] + fix)
    else:
        marks = [(hr_lim, float(pnl))]
    return dict(r, exit="срок", exit_ts=float(t_bar), pnl=float(pnl),
                marks=marks)


def common_sample(recs, holds, log=print):
    """Решения, годные при КАЖДОМ сроке сетки. Остальные — числом."""
    keep, lost = [], 0
    for r in recs:
        if all(truncate(r, h, i) is not None for i, h in enumerate(holds)):
            keep.append(r)
        else:
            lost += 1
    log(f"общая выборка: {len(keep)} решений, не дожили до самого "
        f"длинного срока {lost}")
    return keep, lost


def _exits(rows):
    """Раскладка выходов по причинам — она и объясняет механизм срока."""
    out = {}
    for (r, _m) in rows:
        out[r["exit"]] = out.get(r["exit"], 0) + 1
    return out


def cell(recs, hold_h, idx, dep):
    """Одна ячейка «срок × депозит»: касса та же, что у бумажной книги."""
    tr = [truncate(r, hold_h, idx) for r in recs]
    tr = [x for x in tr if x is not None]
    return cell_rows(tr, dep, hold_h=hold_h)


def cell_rows(tr, dep, ruler_key=None, hold_h=None):
    """Ячейка по УЖЕ решённым исходам — касса и форма книги.

    Вынесено из `cell`, потому что читателя стало два: срок (D7) и
    варианты выхода коротких книг (D9). Второй проход через кассу и
    форму разошёлся бы с первым. `ruler_key` — режим, чей билет занимаем:
    пол и пик у режимов свои, и чужой билет дал бы другое число мест.
    """
    ruler_key = ruler_key or RULER_KEY
    keep, skipped = D6.one_per_name(tr)
    rows = []
    # режим у замера один — тот, которым он считает, и билет берётся ЕГО
    c = D6.ration(keep, R.share(dep, ruler_key), deposit=dep,
                  min_notional=R.MIN_NOTIONAL, keep_rows=rows)
    # форма считается ТЕМ ЖЕ кодом, что печатает страница наблюдения
    st = PP._stats([{"exit_ts": r["exit_ts"], "sym": r["sym"],
                     "usd": float(r["pnl"]) * float(m)}
                    for (r, m) in rows], dep) or {}
    liq = sum(1 for (r, _m) in rows if r["exit"] == "ликвидация")
    worst = min((float(r["pnl"]) for (r, _m) in rows), default=None)
    return {"hold_h": hold_h, "deposit": dep, "skipped_repeats": skipped,
            "taken": c["taken"], "no_cash": c["no_cash"],
            "too_small": c["too_small"], "final": c["final"],
            "max_dd": c["max_dd"], "day_median": st.get("day_median"),
            "day_green": st.get("day_green"), "bite": st.get("bite"),
            "day_worst": st.get("day_worst"), "days": st.get("days"),
            "open_mean": c["open_mean"], "open_max": c["open_max"],
            "liq_share": round(liq / len(rows), 4) if rows else None,
            "worst_pos": round(worst, 4) if worst is not None else None,
            "exits": _exits(rows), "fp": c["fp"]}


def halves(base):
    """Разрез выборки НАДВОЕ по времени решения — проверка на шум окна.

    Купол по сроку на одном окне может быть свойством правила, а может —
    свойством этих 26 суток. Половины не складываются в целое: у каждой
    своя касса с полного депозита, то есть это две независимые книги по
    13 суток, а не разложение одной. Отвечают они на один вопрос: держится
    ли порядок сроков в обеих.
    """
    ts = sorted(float(r["at"]) for r in base)
    if not ts:
        return None, [], []
    mid = ts[len(ts) // 2]
    a = [r for r in base if float(r["at"]) < mid]
    b = [r for r in base if float(r["at"]) >= mid]
    return mid, a, b


def run(limit=None, src=None, log=print):
    t0 = time.time()
    hold_max = max(HOLDS_H)
    got = D6.collect_recs(limit=limit, src=src, log=log, rulers=[RULER],
                          hold_h=hold_max, ckpt_h=HOLDS_H)
    recs = got["recs"][RULER]
    log(f"позиций посчитано {len(recs)} (срок прохода {hold_max} ч)")
    base, lost = common_sample(recs, HOLDS_H, log=log)
    cells = {}
    for i, h in enumerate(HOLDS_H):
        for dep in R.DEPOSITS:
            cells[f"{h}:{int(dep)}"] = cell(base, h, i, dep)
        log(f"  срок {h} ч посчитан")
    # Половины считаются на самом крупном депозите: там касса не
    # связывает вовсе, значит различие половин принадлежит правилу, а не
    # нехватке денег.
    mid, ha, hb = halves(base)
    dep_h = R.DEPOSITS[-1]
    half = {"mid_ts": mid, "n_a": len(ha), "n_b": len(hb),
            "deposit": dep_h, "cells": {}}
    for i, h in enumerate(HOLDS_H):
        half["cells"][f"A:{h}"] = cell(ha, h, i, dep_h)
        half["cells"][f"B:{h}"] = cell(hb, h, i, dep_h)
    log(f"  половины: {len(ha)} и {len(hb)} решений")
    return {"holds_h": HOLDS_H, "ref_h": REF_H, "deposits": R.DEPOSITS,
            "half": half,
            "ruler": list(RULER), "positions": len(recs),
            "sample": len(base), "lost_short_record": lost,
            "window": got["window"], "cells": cells,
            "tickets": {str(int(d)): R.ticket(d, RULER_KEY)
                        for d in R.DEPOSITS},
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def report(s):
    w = s.get("window") or {}
    L = ["# D7 — сколько держать позицию: замер срока", "",
         "Вопрос владельца: «нужно сделать замер самого оптимального "
         "срока, может лучше не 2 дня, а 3 или неделя, может 1 день». "
         f"Нынешнее правило книги — **{s.get('ref_h')} ч (трое суток)**, и "
         "оно было назначено, а не измерено. Сетка объявлена ДО прогона и "
         "печатается целиком: "
         + " / ".join(f"{h} ч" for h in s.get("holds_h") or []) + ".", "",
         "**Срок — свойство оборота книги, а не позиции.** Длинная "
         "позиция держит слот и отказывает новым сигналам по кассе, "
         "короткая освобождает его раньше — поэтому каждая ячейка "
         "прогоняется через ту же кассу, что ведёт бумажные книги, с тем "
         "же билетом; сумма долей позиции на этот вопрос не отвечает "
         "вовсе.", "",
         "**Один проход на все сроки.** Симуляция идёт по самому длинному "
         "сроку с контрольными точками: на границе каждого срока берётся "
         "переоценка по закрытию последнего бара окна — ровно то, чем "
         "кончилась бы симуляция с этим сроком. Равенство усечения прямой "
         "симуляции закреплено тестом.", "",
         f"**Выборка одна на все сроки: {s.get('sample')} решений**, "
         f"выброшено {s.get('lost_short_record')} — запись не доживает до "
         "конца самого длинного срока. Иначе длинные сроки судились бы по "
         "обрезанным сделкам, а короткие по полным.", ""]
    if w:
        L += [f"Окно решений {w.get('from')} … {w.get('to')} UTC "
              f"({w.get('span_d')} суток). Линейка плеча — «оптимальная» "
              "(глубина лестницы), база агрессивного режима; на другие "
              "линейки вывод не переносится без замера.", ""]
    cells = s.get("cells") or {}
    L += ["## Ячейки", "",
          "| срок | депозит | взято | нет кассы | итог | просадка | "
          "медиана дня | зелёных | укус | худший день | ликвидаций | "
          "худшая позиция | занято мест |",
          "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for h in s.get("holds_h") or []:
        for dep in s.get("deposits") or []:
            c = cells.get(f"{h}:{int(dep)}")
            if not c:
                continue
            ref = " ←" if h == s.get("ref_h") else ""
            L.append(
                f"| {h} ч{ref} | ${dep:,.0f} | {c['taken']} | "
                f"{c['no_cash']} | {_pct(c['final'])} | "
                f"{_pct(c['max_dd'])} | {_pct(c['day_median'], 3)} | "
                + ("—" if c.get("day_green") is None
                   else f"{c['day_green']:.2f}") + " | "
                + ("—" if c.get("bite") is None else f"{c['bite']}") + " | "
                + _pct(c.get("day_worst")) + " | "
                + ("—" if c.get("liq_share") is None
                   else f"{c['liq_share'] * 100:.2f} %") + " | "
                + _pct(c.get("worst_pos")) + " | "
                f"{c['open_mean']} |")
    L += ["", "Стрелка помечает нынешнее правило книги — точку отсчёта, а "
          "не победителя. **Вердикт выносится по ФОРМЕ (медиана дня, доля "
          "зелёных, укус, просадка), а не по итогу:** выбрать лучшую "
          "ячейку из пятнадцати по итогу есть ошибка R5, и сетка объявлена "
          "до прогона ровно затем, чтобы этого не сделать.", ""]
    L += ["## Чем кончаются сделки", "",
          "Раскладка объясняет механизм срока: короткий срок режет правый "
          "хвост (сделка не успевает дойти до тейка), длинный даёт дойти, "
          "но держит слот и добирает пол капитуляции с ликвидациями.", "",
          "| срок | тейк | пол | ликвидация | срок вышел |",
          "|---|--:|--:|--:|--:|"]
    for h in s.get("holds_h") or []:
        c = cells.get(f"{h}:{int(R.DEPOSITS[-1])}") or {}
        e = c.get("exits") or {}
        L.append(f"| {h} ч | {e.get('тейк', 0)} | {e.get('пол', 0)} | "
                 f"{e.get('ликвидация', 0)} | {e.get('срок', 0)} |")
    L += ["", f"(по книге ${R.DEPOSITS[-1]:,.0f} — там касса связывает "
          "меньше всего, то есть раскладка описывает сигнал, а не нехватку "
          "денег)", ""]
    hf = s.get("half") or {}
    if hf.get("cells"):
        dep_h = hf.get("deposit") or 0
        L += ["## Держится ли порядок на половинах окна", "",
              "Купол по сроку на одном окне бывает свойством правила, а "
              "бывает свойством этих суток. Выборка разрезана НАДВОЕ по "
              f"времени решения ({hf.get('n_a')} и {hf.get('n_b')} "
              "решений); половины не складываются в целое — у каждой своя "
              f"касса с полного депозита ${dep_h:,.0f}, где касса не "
              "связывает вовсе. **Разошёлся порядок сроков — различие "
              "соседних ячеек есть шум окна, а не свойство срока.**", "",
              "| срок | итог A | итог B | укус A | укус B | зелёных A | "
              "зелёных B |", "|---|--:|--:|--:|--:|--:|--:|"]
        for h in s.get("holds_h") or []:
            a = hf["cells"].get(f"A:{h}") or {}
            b = hf["cells"].get(f"B:{h}") or {}
            ref = " ←" if h == s.get("ref_h") else ""
            L.append(
                f"| {h} ч{ref} | {_pct(a.get('final'))} | "
                f"{_pct(b.get('final'))} | "
                + ("—" if a.get("bite") is None else f"{a['bite']}") + " | "
                + ("—" if b.get("bite") is None else f"{b['bite']}") + " | "
                + ("—" if a.get("day_green") is None
                   else f"{a['day_green']:.2f}") + " | "
                + ("—" if b.get("day_green") is None
                   else f"{b['day_green']:.2f}") + " |")
        best_a = max((s.get("holds_h") or []),
                     key=lambda h: (hf["cells"].get(f"A:{h}") or {})
                     .get("final") or -9)
        best_b = max((s.get("holds_h") or []),
                     key=lambda h: (hf["cells"].get(f"B:{h}") or {})
                     .get("final") or -9)
        L += ["", f"Лучший по итогу срок: **{best_a} ч** в первой половине "
              f"и **{best_b} ч** во второй — "
              + ("совпал, то есть порядок пережил разрез окна."
                 if best_a == best_b else
                 "РАЗОШЁЛСЯ, то есть выбирать срок по итогу на этой "
                 "длине записи нечем.") + " Это диагностика, а не вердикт: "
              "половины по 13 суток шумят вдвое сильнее целого.", ""]
    L += ["## Чего этот замер НЕ говорит", "",
          "Правил книги он не меняет: срок двигает и правило записи "
          f"(`AHEAD_H = HOLD_H + 48`), и решение об этом за владельцем. "
          "Окно записи одно и режим рынка один; веса модели видели эти "
          "часы, значит оценка читается СВЕРХУ. Живого исполнения нет — "
          "сделки считаются реплеем по барам записи. Вторая линейка плеча "
          "(«безопасная») не мерилась: у неё своё плечо, и перенос вывода "
          "требует своего прогона.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)          # каталог создаётся ДО счёта
    s = run(limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    with open(os.path.join(OUT, f"D7-hold-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"D7-hold-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D7: замер срока удержания DCA ({tag})")


if __name__ == "__main__":
    main()
