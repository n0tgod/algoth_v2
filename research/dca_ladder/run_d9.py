#!/usr/bin/env python3
"""D9 — варианты ВЫХОДА коротких DCA-книг (вопрос владельца 2026-09-05).

Вопрос дословно: «изменить шорт стратегии, чтобы они были плюсовыми:
затестить разные варианты временного закрытия — через день, два, три,
или ситуационный вариант: если сделка не в минусе или в минимальном
минусе, то не срезать её по времени, или наоборот».

Замер D7 уже ответил про срок ДЛИННОЙ книги (72 ч менять не надо), но у
коротких книг форма исхода другая: после правки забора деньги теряет пол
капитуляции (12.7 % выходов у шортов против 0.6 % у лонгов), и потолок
пользы от срока там не измерен вовсе. Сетка объявлена ДО прогона:

    A  таймер T          T ∈ {24, 48, 72, 120, 168} ч      — 5 ячеек
    B  «резать минус»    в момент T позиция ещё открыта и её отметка
                         ниже −θ → закрыть на T; иначе держать до H.
                         (T, H) ∈ {(24,72),(48,72),(24,168),(48,168),
                         (72,168)}, θ ∈ {0, 0.02}         — 10 ячеек
    C  «наоборот»        в момент T позиция открыта и в ПЛЮСЕ →
                         зафиксировать на T; в минусе — держать до H.
                         те же пять пар, θ = 0             — 5 ячеек

Итого 20 ячеек на книгу. Выход по УРОВНЮ (тейк, пол, ликвидация),
случившийся раньше T, ни один вариант не трогает: он случился бы при
любом правиле времени. B и C — ровно две прочитки просьбы владельца,
и обе стоят рядом намеренно: выбрать одну заранее значило бы решить
ответ до замера.

**Один проход, все варианты — пересчёт.** Симуляция идёт по самому
длинному сроку с контрольными точками (машинерия D7); отметка позиции на
T и её исход при удержании до H берутся из тех же точек, поэтому ячейки
B и C ПАРНЫ своему таймеру A:H по построению — те же позиции, тот же
путь, другое правило. Разность «ячейка минус A:H» и есть цена правила,
и она печатается рядом с самой ячейкой.

Книги: `optimal_s`, `safe_s` (свой проход по барам), `aggr_s` — тот же
проход, что у `optimal_s`, плюс гейт плеча самого режима (ровно так
книгу собирает `run_paper`); и длинная `optimal` КОНТРОЛЬНОЙ рукой —
правило, помогающее только шортам, говорит о хвосте шортов, правило,
помогающее всем, есть правило времени вообще.

Чего замер НЕ говорит и что стоит в отчёте словами: шортов под гейтом
около трёх сотен (3.4 % от лонгов), половины окна шумят; веса модели
видели эти часы; вердикт по ФОРМЕ и парной разности, а не по лучшей
ячейке из двадцати — это ошибка R5. Правил книг он не меняет.

Прогон: `run research/dca_ladder/run_d9.py`. Смоук: `--limit 60`
(первые N ног КАЖДОЙ стороны — не представительны, только механика).
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
import run_d7 as D7                                           # noqa: E402
import rules as R                                             # noqa: E402

OUT = os.path.join(HERE, "out")
HOUR = 3600

# --- сетка объявлена ДО прогона ----------------------------------------
# Сроки — ТЕ ЖЕ, что у D7: контрольные точки одного прохода, и только
# тогда таймерные ячейки коротких книг сравнимы с замером срока длинной.
HOLDS = list(D7.HOLDS_H)
REF_H = D2.HOLD_H
PAIRS = [(24, 72), (48, 72), (24, 168), (48, 168), (72, 168)]
THETAS = [0.0, 0.02]
MODES = ("A", "B", "C")

# Книги замера: ключ режима бумажной книги → линейка прохода. Совпадение
# с реестром режимов ДОКАЗЫВАЕТСЯ ниже, а не подразумевается: два места,
# решающих одно, однажды разойдутся.
BOOKS = {
    "optimal_s": ("depth", D2.SURVIVE_MULT, "short"),
    "safe_s": ("sigma", R.SIGMA_MULT, "short"),
    "optimal": ("depth", D2.SURVIVE_MULT, "long"),       # контроль
}
# Режим с гейтом плеча считается НЕ вторым проходом, а фильтром по
# плечу над проходом своей линейки — ровно так его собирает `run_paper`
# (гейт первым, до правила одной на имя).
DERIVED = {"aggr_s": "optimal_s"}
SHORT_BOOKS = ["optimal_s", "safe_s", "aggr_s"]
CONTROL_BOOK = "optimal"
for _k, (_rule, _param, _side) in BOOKS.items():
    assert (_rule, _param) == (R.RULERS[_k]["rule"], R.RULERS[_k]["param"]), (
        _k, (_rule, _param), R.RULERS[_k])
    assert _side == R.side_of(_k), (_k, _side, R.side_of(_k))
for _k, _base in DERIVED.items():
    assert (R.RULERS[_k]["rule"], R.RULERS[_k]["param"]) == (
        R.RULERS[_base]["rule"], R.RULERS[_base]["param"]), (_k, _base)
    assert R.side_of(_k) == R.side_of(_base), (_k, _base)
    assert R.min_lev_of(_k) is not None, _k
    assert R.min_lev_of(_base) is None, _base


def grid():
    """Все 20 ячеек в объявленном порядке: (режим, T, H, θ)."""
    cells = [("A", h, None, None) for h in HOLDS]
    for (t, h) in PAIRS:
        for th in THETAS:
            cells.append(("B", t, h, th))
    for (t, h) in PAIRS:
        cells.append(("C", t, h, 0.0))
    return cells


def cell_key(c):
    mode, t, h, th = c
    if mode == "A":
        return f"A:{t}"
    return f"{mode}:{t}:{h}:{th:g}"


def base_key(c):
    """Таймерная ячейка, с которой условная ПАРНА: тот же срок H."""
    mode, t, h, _th = c
    return f"A:{t}" if mode == "A" else f"A:{h}"


def decide(r, mode, t, h=None, theta=0.0):
    """Исход ТОЙ ЖЕ позиции при варианте выхода; None — измерить нечем.

    Порядок правил объявлен: (1) уровень, задетый раньше T, ни один
    вариант не трогает — он случился бы при любом правиле времени;
    (2) в момент T позиция ещё открыта, и решает её ОТМЕТКА на T:
    B режет минус глубже θ и держит остальное до H, C фиксирует плюс и
    держит минус до H; (3) удержанная до H позиция получает исход
    таймера H — тем же `D7.truncate`, которым посчитана отметка на T.
    Второй реализации усечения здесь нет: расхождение двух дало бы
    ячейкам разные пути при одних позициях.

    Поле `d9` называет, ЧТО с позицией сделал вариант: `level` — уровень
    раньше T, `cut` — закрыта на T по правилу, `held` — удержана до H,
    `timer` — простой таймер. Без него раскладка выходов сливала бы
    «срок на T» и «срок на H» в одно слово.
    """
    it = HOLDS.index(t)
    a = D7.truncate(r, t, it)
    if a is None:
        return None
    if mode == "A":
        return dict(a, d9="timer")
    if a["exit"] != "срок":
        return dict(a, d9="level")
    mark = float(a["pnl"])
    if mode == "B":
        cut = mark < -float(theta)
    elif mode == "C":
        cut = mark > float(theta)
    else:
        raise ValueError(mode)
    if cut:
        return dict(a, d9="cut")
    b = D7.truncate(r, h, HOLDS.index(h))
    if b is None:
        return None
    return dict(b, d9="held")


def book_recs(recs_by_book, key):
    """Записи книги: свой проход либо гейт плеча над базовым (aggr_s)."""
    if key in DERIVED:
        ml = R.min_lev_of(key)
        return [r for r in recs_by_book[DERIVED[key]]
                if float(r["lev"]) >= ml]
    return list(recs_by_book[key])


def _d9_counts(dec):
    out = {}
    for x in dec:
        out[x["d9"]] = out.get(x["d9"], 0) + 1
    return out


def cell(recs, c, dep, ruler_key):
    """Одна ячейка «вариант × депозит»: касса и форма — как у книги."""
    mode, t, h, th = c
    dec = [decide(r, mode, t, h, th or 0.0) for r in recs]
    dec = [x for x in dec if x is not None]
    out = D7.cell_rows(dec, dep, ruler_key=ruler_key,
                       hold_h=(t if mode == "A" else h))
    out.update({"mode": mode, "t": t, "h": h, "theta": th,
                "n_sample": len(dec), "d9": _d9_counts(dec)})
    return out


def lev_split(recs, h=REF_H):
    """Диагностика: исход текущего правила по плечу — 1× против лестницы.

    Мотив замера: у коротких книг около 85 % позиций идут с плечом 1×
    (структурных уровней выше входа не нашлось — лестницы нет), а весь
    хвост сидит в остальных 15 % с плечом 7–25×. Единицы — доли МАРЖИ
    позиции, до кассы: это раскладка сигнала, а не деньги книги.
    """
    ih = HOLDS.index(h)
    out = {}
    for name, cond in (("lev1", lambda r: float(r["lev"]) <= 1.0),
                       ("lev_gt1", lambda r: float(r["lev"]) > 1.0)):
        rows = [D7.truncate(r, h, ih) for r in recs if cond(r)]
        rows = [x for x in rows if x is not None]
        pn = np.array([float(x["pnl"]) for x in rows], dtype=float)
        ex = {}
        for x in rows:
            ex[x["exit"]] = ex.get(x["exit"], 0) + 1
        out[name] = {"n": len(rows),
                     "pnl_sum": round(float(pn.sum()), 4) if len(pn) else 0.0,
                     "pnl_median": (round(float(np.median(pn)), 4)
                                    if len(pn) else None),
                     "pnl_worst": (round(float(pn.min()), 4)
                                   if len(pn) else None),
                     "lev_median": (round(float(np.median(
                         [float(x["lev"]) for x in rows])), 2)
                         if rows else None),
                     "exits": ex}
    return out


def run(limit=None, src=None, log=print, with_control=True):
    t0 = time.time()
    hold_max = max(HOLDS)
    legs = D6.gated_legs(side=None, log=log)
    if limit:
        # Смоук: первые N ног КАЖДОЙ стороны. Первые ноги журнала — один
        # час, и представительными они не являются; смоук проверяет
        # механику, а не числа (урок D2).
        sh = [g for g in legs if g.get("side") == "short"][:limit]
        lg = [g for g in legs if g.get("side") != "short"][:limit]
        legs = sh + lg
    rulers = [BOOKS[k] for k in BOOKS if with_control or k != CONTROL_BOOK]
    got = D6.collect_recs(src=src, log=log, rulers=rulers, legs=legs,
                          hold_h=hold_max, ckpt_h=HOLDS)
    raw = {}
    for k, ruler in BOOKS.items():
        if ruler in got["recs"]:
            raw[k] = got["recs"][ruler]
    # Выборка ОДНА на все варианты каждой книги: запись, не дожившая до
    # самого длинного срока, выбрасывается целиком — иначе H = 168
    # судился бы по обрезанным сделкам, а T = 24 по полным (правило D7).
    base, lost = {}, {}
    for k, recs in raw.items():
        base[k], lost[k] = D7.common_sample(recs, HOLDS,
                                            log=lambda *_: None)
        log(f"книга {k}: позиций {len(recs)}, общая выборка {len(base[k])}, "
            f"не дожили {lost[k]}")
    for k, b in DERIVED.items():
        if b in base:
            base[k] = book_recs(base, k)
            lost[k] = lost[b]
            log(f"книга {k}: гейт плеча ≥ {R.min_lev_of(k):g}× оставил "
                f"{len(base[k])} из {len(base[b])}")
    order = [k for k in SHORT_BOOKS + [CONTROL_BOOK] if k in base]
    cells, halves = {}, {}
    dep_h = R.DEPOSITS[-1]
    for k in order:
        cells[k] = {}
        for c in grid():
            for dep in R.DEPOSITS:
                cells[k][f"{cell_key(c)}@{int(dep)}"] = cell(
                    base[k], c, dep, k)
        # Половины — только у коротких книг и на самом крупном депозите,
        # где касса не связывает: различие половин тогда принадлежит
        # правилу, а не нехватке денег (правило D7).
        if k != CONTROL_BOOK:
            mid, ha, hb = D7.halves(base[k])
            halves[k] = {"mid_ts": mid, "n_a": len(ha), "n_b": len(hb),
                         "deposit": dep_h, "cells": {}}
            for c in grid():
                halves[k]["cells"][f"A:{cell_key(c)}"] = cell(ha, c, dep_h, k)
                halves[k]["cells"][f"B:{cell_key(c)}"] = cell(hb, c, dep_h, k)
        log(f"  книга {k}: {len(grid())} ячеек × {len(R.DEPOSITS)} "
            f"депозитов посчитано")
    split = {k: lev_split(base[k]) for k in order}
    return {"holds_h": HOLDS, "ref_h": REF_H, "pairs": PAIRS,
            "thetas": THETAS, "grid": [cell_key(c) for c in grid()],
            "deposits": R.DEPOSITS, "books": order,
            "short_books": [k for k in SHORT_BOOKS if k in base],
            "control_book": CONTROL_BOOK if CONTROL_BOOK in base else None,
            "positions": {k: len(v) for k, v in raw.items()},
            "sample": {k: len(v) for k, v in base.items()},
            "lost_short_record": lost, "window": got["window"],
            "cells": cells, "half": halves, "lev_split": split,
            "min_lev": {k: R.min_lev_of(k) for k in DERIVED},
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


# --- чтение результата: парная разность и устойчивость ------------------
def paired(cells_book, dep):
    """Δ итога условной ячейки к своему таймеру A:H (те же позиции)."""
    out = {}
    for c in grid():
        if c[0] == "A":
            continue
        k, b = cell_key(c), base_key(c)
        me = cells_book.get(f"{k}@{int(dep)}") or {}
        ref = cells_book.get(f"{b}@{int(dep)}") or {}
        if me.get("final") is None or ref.get("final") is None:
            out[k] = None
        else:
            out[k] = round(float(me["final"]) - float(ref["final"]), 4)
    return out


def summarize(s):
    """Числа, из которых выводится вердикт; отчёт печатает их, не прозу."""
    dep = s["deposits"][-1]
    out = {}
    for k in s["books"]:
        cb = s["cells"][k]
        pd = paired(cb, dep)
        pos_form = [ck for ck in s["grid"]
                    if (cb.get(f"{ck}@{int(dep)}") or {}).get("final")
                    is not None
                    and cb[f"{ck}@{int(dep)}"]["final"] > 0
                    and (cb[f"{ck}@{int(dep)}"].get("day_median") or -1) >= 0]
        better = [ck for ck, d in pd.items() if d is not None and d > 0]
        stable = []
        hf = (s.get("half") or {}).get(k)
        if hf:
            for c in grid():
                if c[0] == "A":
                    continue
                ck, b = cell_key(c), base_key(c)
                ok = True
                for side in ("A", "B"):
                    me = hf["cells"].get(f"{side}:{ck}") or {}
                    ref = hf["cells"].get(f"{side}:{b}") or {}
                    if me.get("final") is None or ref.get("final") is None \
                            or float(me["final"]) <= float(ref["final"]):
                        ok = False
                if ok and ck in better:
                    stable.append(ck)
        out[k] = {"paired": pd, "pos_form": pos_form, "better": better,
                  "stable": stable, "n_cond": len(pd)}
    return out


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def _n(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def _cell_row(ck, c, pd, ref):
    e = c.get("exits") or {}
    d9 = c.get("d9") or {}
    delta = pd.get(ck)
    return (f"| {ck}{ref} | {c['taken']} | {_pct(c['final'])} | "
            + ("—" if delta is None else _pct(delta)) + " | "
            f"{_pct(c['max_dd'])} | {_pct(c['day_median'], 3)} | "
            + ("—" if c.get("day_green") is None
               else f"{c['day_green']:.2f}") + " | "
            + ("—" if c.get("bite") is None else f"{c['bite']}") + " | "
            + _pct(c.get("day_worst")) + " | "
            + _pct(c.get("worst_pos")) + " | "
            f"{e.get('тейк', 0)}/{e.get('пол', 0)}/"
            f"{e.get('ликвидация', 0)}/{e.get('срок', 0)} | "
            f"{d9.get('cut', 0)}/{d9.get('held', 0)}/{d9.get('level', 0)} |")


def report(s):
    w = s.get("window") or {}
    dep = s["deposits"][-1]
    sm = summarize(s)
    L = ["# D9 — варианты выхода коротких DCA-книг", "",
         "Вопрос владельца: «изменить шорт стратегии, чтобы они были "
         "плюсовыми — затестить разные варианты временного закрытия: "
         "через день, два, три, или ситуационный: если сделка не в минусе "
         "или в минимальном минусе, не срезать её по времени, или "
         "наоборот». Сетка объявлена ДО прогона и печатается целиком: "
         "таймер A (" + " / ".join(f"{h} ч" for h in s["holds_h"]) + "), "
         "«резать минус» B (пары T→H "
         + ", ".join(f"{t}→{h}" for (t, h) in s["pairs"])
         + " при порогах θ " + ", ".join(f"{x:g}" for x in s["thetas"])
         + ") и «наоборот» C (те же пары, фиксировать плюс на T, минус "
         "держать до H) — " + f"{len(s['grid'])} ячеек на книгу.", "",
         "**Все варианты — пересчёт ОДНОГО прохода** по контрольным точкам "
         "(машинерия D7): отметка позиции на T и её исход при удержании до "
         "H берутся из одних точек, поэтому условная ячейка ПАРНА своему "
         "таймеру A:H — те же позиции, другое правило. Колонка «Δ к A:H» и "
         "есть цена правила. Выход по уровню раньше T (тейк, пол, "
         "ликвидация) ни один вариант не трогает.", "",
         "**Вердикт по ФОРМЕ и по парной разности, а не по лучшей "
         "ячейке из двадцати** — выбрать её по итогу есть ошибка R5. "
         "Ячейка судится тем, что улучшила против своего таймера при тех "
         "же позициях, и держится ли знак разности на обеих половинах "
         "окна.", ""]
    if w:
        L += [f"Окно решений {w.get('from')} … {w.get('to')} UTC "
              f"({w.get('span_d')} суток). Выборка одна на все варианты "
              "каждой книги: " + ", ".join(
                  f"{k} {s['sample'].get(k)} (не дожили до 168 ч "
                  f"{(s.get('lost_short_record') or {}).get(k)})"
                  for k in s["books"]) + ".", ""]
    if s.get("min_lev"):
        L += ["Книга `aggr_s` — тот же проход, что `optimal_s`, плюс гейт "
              "плеча режима (" + ", ".join(
                  f"≥ {v:g}×" for v in s["min_lev"].values())
              + "), как её собирает бумажная книга; отдельный проход дал "
              "бы те же записи.", ""]
    hdr = ("| ячейка | взято | итог | Δ к A:H | просадка | медиана дня | "
           "зелёных | укус | худший день | худшая позиция | "
           "тейк/пол/ликв/срок | cut/held/level |",
           "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for k in s["books"]:
        cb = s["cells"][k]
        pd = sm[k]["paired"]
        role = " (контроль, лонг)" if k == s.get("control_book") else ""
        L += [f"## Книга `{k}`{role} — депозит ${dep:,.0f}", "", *hdr]
        for c in grid():
            ck = cell_key(c)
            cc = cb.get(f"{ck}@{int(dep)}")
            if not cc:
                continue
            ref = " ←" if ck == f"A:{s['ref_h']}" else ""
            L.append(_cell_row(ck, cc, pd, ref))
        L += ["", f"Стрелка — нынешнее правило книги (таймер {s['ref_h']} "
              "ч), точка отсчёта. Последняя колонка — сколько позиций "
              "вариант закрыл на T по правилу (cut), удержал до H (held) "
              "и сколько вышли по уровню раньше T (level); считается по "
              "выборке до кассы.", ""]
        n_cond = sm[k]["n_cond"]
        L += [f"Условных ячеек {n_cond}; лучше своего таймера по итогу "
              f"**{len(sm[k]['better'])}**"
              + (f", из них знак разности держится на обеих половинах "
                 f"окна у **{len(sm[k]['stable'])}**" if k in (s.get("half")
                                                            or {}) else "")
              + f"; положительны и по итогу, и по медиане дня "
              f"{len(sm[k]['pos_form'])} ячеек из {len(s['grid'])}"
              + (": " + ", ".join(sm[k]["pos_form"]) if sm[k]["pos_form"]
                 else "") + ".", ""]
    # половины
    hf = s.get("half") or {}
    if hf:
        L += ["## Держится ли знак на половинах окна", "",
              "Выборка каждой короткой книги разрезана надвое по времени "
              "решения; у половин своя касса с полного депозита "
              f"${dep:,.0f}, в целое они не складываются. Печатается Δ "
              "условной ячейки к своему таймеру A:H в каждой половине: "
              "**разошёлся знак — разность есть шум окна, а не свойство "
              "правила.**", ""]
        for k, h in hf.items():
            L += [f"### `{k}` — половины {h['n_a']} и {h['n_b']} решений",
                  "", "| ячейка | итог 1-я | итог 2-я | Δ 1-я | Δ 2-я | "
                  "знак |", "|---|--:|--:|--:|--:|:--:|"]
            for c in grid():
                if c[0] == "A":
                    continue
                ck, b = cell_key(c), base_key(c)
                row = [ck]
                ds = []
                for side in ("A", "B"):
                    me = h["cells"].get(f"{side}:{ck}") or {}
                    ref = h["cells"].get(f"{side}:{b}") or {}
                    row.append(_pct(me.get("final")))
                    if me.get("final") is None or ref.get("final") is None:
                        ds.append(None)
                    else:
                        ds.append(float(me["final"]) - float(ref["final"]))
                row += [("—" if d is None else _pct(d)) for d in ds]
                if any(d is None for d in ds):
                    sign = "—"
                elif (ds[0] > 0) == (ds[1] > 0):
                    sign = "держится" if ds[0] > 0 else "минус в обеих"
                else:
                    sign = "РАЗОШЁЛСЯ"
                row.append(sign)
                L.append("| " + " | ".join(row) + " |")
            L.append("")
    # плечо
    L += ["## Откуда деньги и хвост: 1× против лестницы", "",
          "Диагностика по выборке до кассы, единицы — доли маржи позиции "
          f"при нынешнем таймере {s['ref_h']} ч. У коротких книг лестницы "
          "чаще всего нет (структурных уровней выше входа не нашлось) и "
          "плечо ровно 1×; хвост живёт там, где лестница есть и забор "
          "выдал крупное плечо.", "",
          "| книга | группа | n | плечо медиана | Σ pnl | медиана | худшая "
          "| тейк/пол/ликв/срок |", "|---|---|--:|--:|--:|--:|--:|--:|"]
    for k in s["books"]:
        for grp, g in (s.get("lev_split") or {}).get(k, {}).items():
            e = g.get("exits") or {}
            L.append(f"| {k} | {'1×' if grp == 'lev1' else 'лестница'} | "
                     f"{g['n']} | {_n(g.get('lev_median'))} | "
                     f"{_pct(g.get('pnl_sum'), 1)} | "
                     f"{_pct(g.get('pnl_median'))} | "
                     f"{_pct(g.get('pnl_worst'))} | "
                     f"{e.get('тейк', 0)}/{e.get('пол', 0)}/"
                     f"{e.get('ликвидация', 0)}/{e.get('срок', 0)} |")
    L.append("")
    # вердикт из чисел
    sb = [k for k in s.get("short_books") or [] if k in sm]
    tot_better = sum(len(sm[k]["better"]) for k in sb)
    tot_stable = sum(len(sm[k]["stable"]) for k in sb)
    tot_cond = sum(sm[k]["n_cond"] for k in sb)
    tot_pos = sum(len(sm[k]["pos_form"]) for k in sb)
    L += ["## Что из этого следует", "",
          f"По коротким книгам условных ячеек {tot_cond}, лучше своего "
          f"таймера {tot_better}, устойчивых по половинам {tot_stable}; "
          f"положительных по итогу и медиане дня {tot_pos} из "
          f"{len(sb) * len(s['grid'])}. "
          + ("**Устойчивого улучшения нет: ни одна условная ячейка не "
             "держит знак разности на обеих половинах окна** — правило "
             "времени короткие книги в плюс не выводит, и спорить с этим "
             "лучшей ячейкой значит совершить ошибку R5."
             if tot_stable == 0 else
             f"**Есть направление: {tot_stable} ячеек лучше таймера в "
             "обеих половинах окна.** Это диагностика на трёх сотнях "
             "решений, а не вердикт — правило книги меняется только "
             "решением владельца и судится форвардом."), "",
          "## Чего замер НЕ говорит", "",
          "Шортов под гейтом около трёх сотен на книгу (3.4 % от лонгов), "
          "половины окна шумят вдвое сильнее целого; веса модели видели "
          "эти часы — оценка читается сверху; один режим рынка. Правил "
          "книг замер не меняет, и порог θ он не подбирает: обе величины "
          "объявлены до прогона. Вход и доливы не трогались вовсе — здесь "
          "меняется ровно правило выхода, иначе разность нельзя было бы "
          "приписать ему.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-control", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)          # каталог создаётся ДО счёта
    s = run(limit=a.limit, with_control=not a.no_control)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    with open(os.path.join(OUT, f"D9-exit-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"D9-exit-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D9: варианты выхода коротких DCA-книг ({tag})")


if __name__ == "__main__":
    main()
