#!/usr/bin/env python3
"""Возраст имени как фильтр входа короткой стороны общего счёта.

Гипотеза, оставшаяся от опровергнутого гейта по ставке funding: его
результат держался на «ставке неизвестна» — 773 решения по именам, у
которых рядов не было вовсе. Это были ЛИСТИНГИ ПОСЛЕ снимка универсума,
и их отсечение помогало. Значит проверять надо не незнание, а то, что за
ним стояло: **возраст имени на момент решения**.

Ось объявлена ДО прогона: не входить в шорт, если имя моложе N суток,
N ∈ (0, 3, 7, 14, 30, 60). Ноль — как сейчас, фильтра нет.

Контроль тот же, что у гейта, и по той же причине: фильтр РЕЖЕТ число
сделок, а короткая сторона в минусе — значит меньше шортов само по себе
улучшает счёт. На каждый порог считается случайная выборка ровно того же
размера, на 200 зёрнах, и печатается доля выборок, которые фильтр НЕ
побил, — отдельно по деньгам и по отношению доход/просадка.

Возраст берётся из справочника площадки (`instruments.json`,
`launch_time`); имя без даты листинга — «возраст неизвестен», и такие
решения считаются ОТДЕЛЬНО, а не молча приравниваются к старым: ровно
на этом сгорел гейт.

Журнал книг замер не трогает: это проба.

Запуск: `run research/dca_paper/pair_age.py`.
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
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_pair as PR                                         # noqa: E402
import pair_gate as PG                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402

DAYS = (0, 3, 7, 14, 30, 60)
# Полосы возраста для разреза «почему»: те же границы, что у порогов,
# чтобы таблица фильтра и таблица механизма читались одна через другую.
BAND_EDGES = (0.0, 3.0, 7.0, 14.0, 30.0, 60.0, float("inf"))
BAND_NAMES = ("<3 сут", "3–7 сут", "7–14 сут", "14–30 сут", "30–60 сут",
              "≥60 сут")
UNKNOWN = "возраст неизвестен"
# Исходы, которые и делают хвост короткой стороны (замер `short_why`):
# пол капитуляции и ликвидация. Тейк и срок — не хвост.
TAIL_EXITS = ("пол", "ликвидация")
SEEDS = 200
SEED = 20260908
INSTR = IR.PATH


def launches(path=None):
    """Символ → момент листинга. Читает ЯДРО справочника, своей копии нет."""
    return IR.launches(path)


def age_days(launch, sym, at):
    """Возраст имени на момент решения, сутки. Нет даты — None."""
    return IR.age_days(launch, sym, at)


def band_of(age):
    """Полоса возраста. Нет даты листинга — своя полоса, а не «старое»."""
    if age is None:
        return UNKNOWN
    for i, name in enumerate(BAND_NAMES):
        if BAND_EDGES[i] <= float(age) < BAND_EDGES[i + 1]:
            return name
    return UNKNOWN


def bands(rows, launch):
    """Исполненные короткие сделки по возрасту имени — механизм фильтра.

    Сетка выше говорит только «стало лучше», а лучше становится и от
    того, что сделок меньше. Механизм называется здесь: если минус
    живёт в молодых именах и его делают пол с ликвидацией на большом
    плече и дорогом funding — это свойство имени, а не удачная ячейка.
    """
    out = {}
    for r in rows:
        b = out.setdefault(
            band_of(age_days(launch, r.get("sym"), r.get("at"))),
            {"n": 0, "usd": 0.0, "margin": 0.0, "tail": 0, "vals": [],
             "lev": [], "fund_bp": []})
        b["n"] += 1
        b["usd"] += float(r.get("usd") or 0.0)
        m = float(r.get("margin") or 0.0)
        b["margin"] += m
        b["vals"].append(float(r.get("usd") or 0.0))
        b["lev"].append(float(r.get("lev") or 0.0))
        if (r.get("exit") or "") in TAIL_EXITS:
            b["tail"] += 1
        fu = r.get("fund_usd")
        # funding не измерен — прочерк, а не ноль: ряд площадки мог
        # кончиться раньше сделки, и нулём это подменять нельзя.
        if fu is not None and m > 0:
            b["fund_bp"].append(float(fu) / m * 1e4)
    for b in out.values():
        v = np.array(b.pop("vals"), dtype=float)
        lv = np.array(b.pop("lev"), dtype=float)
        fb = np.array(b.pop("fund_bp") or [], dtype=float)
        b["usd"] = round(b["usd"], 2)
        b["median"] = round(float(np.median(v)), 2)
        b["worst"] = round(float(np.min(v)), 2)
        b["lev"] = round(float(np.median(lv)), 1)
        b["tail_share"] = round(b["tail"] / b["n"], 3)
        b["per_margin"] = (round(b["usd"] / b["margin"], 4)
                           if b["margin"] > 0 else None)
        b["margin"] = round(b["margin"], 2)
        b["fund_n"] = int(fb.size)
        b["fund_bp"] = (round(float(np.median(fb)), 0) if fb.size else None)
        b["fund_bp_mean"] = (round(float(np.mean(fb)), 0) if fb.size else None)
        b["fund_bp_worst"] = (round(float(np.min(fb)), 0) if fb.size else None)
    return out


def pick(shorts, launch, min_days, seed=SEED, n_random=None):
    """Решения после фильтра возраста плюс счётчики отказов.

    `n_random` — взять случайное подмножество такого размера вместо
    фильтра: это контроль, и он объявлен здесь же, чтобы «фильтр» и
    «просто меньше сделок» считались одним кодом.
    """
    why = {"моложе порога": 0, "возраст неизвестен": 0}
    keep = []
    for r in shorts:
        if n_random is None and min_days > 0:
            a = age_days(launch, r.get("sym"), r.get("at"))
            if a is None:
                why["возраст неизвестен"] += 1
                continue
            if a < min_days:
                why["моложе порога"] += 1
                continue
        keep.append(r)
    if n_random is not None:
        rs = np.random.default_rng(seed)
        idx = (sorted(rs.choice(len(keep), size=min(n_random, len(keep)),
                                replace=False).tolist()) if keep else [])
        why["контроль размера"] = len(keep) - len(idx)
        keep = [keep[i] for i in idx]
    return keep, why


def run(dep=None, log=print, ctx=None, long_cache=None, short_cache=None,
        keys=None, now=None, seeds=None, days=None, launch=None):
    t0 = time.time()
    dep = float(dep or R.DEPOSITS[1])
    keys = list(keys or R.PAIR_ORDER)
    days = tuple(days or DAYS)
    seeds = int(seeds or SEEDS)
    ctx = ctx if ctx is not None else CO.context()
    launch = launches() if launch is None else launch
    longs, why_l = PR.long_recs(long_cache, log=log)
    shorts, why_s = PR.short_recs(short_cache, log=log)
    if why_l or why_s or not longs or not shorts:
        why = why_l or why_s or "позиций в кэшах нет"
        log(f"замер не считается: {why}")
        return {"error": why, "dep": dep}
    if not launch:
        log("справочник инструментов не читается — возраст неизвестен всем")
    out = {"dep": dep, "days": list(days), "seeds": seeds, "cells": {},
           "bands": {}, "launch_known": len(launch),
           "costs_error": (ctx or {}).get("error"),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    for pk in keys:
        lk, sk = R.parts_of(pk)
        lrec, srec = longs.get(lk) or [], shorts.get(sk) or []
        for d in days:
            keep, why = pick(srec, launch, d)
            c = PG.cell(lrec, keep, pk, dep, ctx, now=now, want_rows=(d == 0))
            # Строки нужны один раз — на разрез механизма; в артефакт
            # они не идут (это книга целиком, а не сводка).
            rws = c.pop("rows", [])
            out["cells"][f"{pk}|{d}"] = dict(c, pair=pk, min_days=d,
                                             offered=len(srec),
                                             kept=len(keep), drops=why)
            log(f"{pk} ≥{d} сут: коротких {len(keep)} из {len(srec)}, "
                f"счёт {c.get('usd')} $, отношение {c.get('ratio')}")
            if d == 0:
                out["bands"][pk] = bands(
                    [r for r in rws if (r.get("book") or pk) == sk], launch)
                for nm, b in out["bands"][pk].items():
                    log(f"   {pk} {nm}: сделок {b['n']}, {b['usd']:+.0f} $, "
                        f"хвостом кончились {100 * b['tail_share']:.0f} %")
                continue
            got = []
            for k in range(seeds):
                rk_, _w = pick(srec, launch, d, seed=SEED + 100 * k,
                               n_random=len(keep))
                got.append(PG.cell(lrec, rk_, pk, dep, ctx, now=now))
            usd = [x["usd"] or 0.0 for x in got]
            rt = [x["ratio"] for x in got if x.get("ratio") is not None]
            base = out["cells"][f"{pk}|{d}"]
            out["cells"][f"{pk}|{d}|random"] = {
                "pair": pk, "min_days": d, "seeds": seeds, "kept": len(keep),
                "usd": round(float(np.median(usd)), 2),
                "usd_p10": round(float(np.quantile(usd, 0.1)), 2),
                "usd_p90": round(float(np.quantile(usd, 0.9)), 2),
                "ratio": (round(float(np.median(rt)), 2) if rt else None),
                "ratio_p10": (round(float(np.quantile(rt, 0.1)), 2)
                              if rt else None),
                "ratio_p90": (round(float(np.quantile(rt, 0.9)), 2)
                              if rt else None),
                "max_dd": round(float(np.median([x["max_dd"] or 0.0
                                                 for x in got])), 4),
                "beat_usd": (None if base.get("usd") is None else
                             round(float(np.mean(np.array(usd)
                                                 >= base["usd"])), 3)),
                "beat_ratio": (None if not rt or base.get("ratio") is None
                               else round(float(np.mean(
                                   np.array(rt) >= base["ratio"])), 3))}
            log(f"   контроль ({seeds} зёрен): медиана отношения "
                f"{out['cells'][f'{pk}|{d}|random']['ratio']}, бьют фильтр "
                f"{out['cells'][f'{pk}|{d}|random']['beat_ratio']}")
    out["secs"] = round(time.time() - t0, 1)
    return out


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def report(s):
    L = ["# Возраст имени как фильтр входа короткой стороны", "",
         "Гипотеза осталась от опровергнутого гейта по ставке funding: его "
         "результат держался на «ставке неизвестна» — решениях по "
         "листингам без рядов. Проверяется то, что за этим стояло: "
         "возраст имени на момент решения. Ось объявлена до прогона, "
         "контроль — случайная выборка ровно того же размера.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    dep = int(s["dep"])
    L += [f"Общий счёт, депозит ${dep:,}, деньги НЕТТО. Момент листинга "
          f"известен у {s['launch_known']} символов справочника; имя без "
          "даты в фильтр не проходит и считается отдельной колонкой.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}.", ""]
    L += ["| книга | порог | коротких взято | моложе порога | возраст "
          "неизвестен | Σ $ | просадка | доход/просадка | контроль: "
          "медиана отношения (p10…p90) | бьют фильтр (деньги / отношение) |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for pk in (R.PAIR_ORDER):
        for d in s.get("days", DAYS):
            c = (s.get("cells") or {}).get(f"{pk}|{d}")
            if not c:
                continue
            r = (s.get("cells") or {}).get(f"{pk}|{d}|random") or {}
            dr = c.get("drops") or {}
            L.append(
                f"| {R.ruler_title(pk)} | "
                + ("нет" if not d else f"≥{d} сут")
                + f" | {c['kept']} из {c['offered']} | "
                f"{dr.get('моложе порога', 0)} | "
                f"{dr.get('возраст неизвестен', 0)} | {_u(c.get('usd'))} | "
                f"{_p(c.get('max_dd'))} | "
                + ("—" if c.get("ratio") is None else f"{c['ratio']:.2f}")
                + " | "
                + ("—" if r.get("ratio") is None
                   else f"{r['ratio']:.2f} ({r['ratio_p10']:.2f}…"
                        f"{r['ratio_p90']:.2f})")
                + " | "
                + ("—" if r.get("beat_usd") is None
                   else f"{100 * r['beat_usd']:.0f} % / "
                        + ("—" if r.get("beat_ratio") is None
                           else f"{100 * r['beat_ratio']:.0f} %")) + " |")
    bs = s.get("bands") or {}
    if bs:
        L += ["", "## Почему: где живёт минус короткой стороны", "",
              "Разрез ИСПОЛНЕННЫХ коротких сделок без всякого фильтра по "
              "возрасту имени на момент входа. Сетка выше говорит только "
              "«стало лучше» — лучше становится и просто от меньшего "
              "числа сделок; полоса называет причину. Хвост — исходы "
              "«пол» и «ликвидация»; funding в б.п. вложенной маржи, "
              "прочерк — ряда площадки на эти часы нет.", ""]
        for pk in R.PAIR_ORDER:
            b = bs.get(pk)
            if not b:
                continue
            L += [f"### {R.ruler_title(pk)}", "",
                  "| возраст имени | сделок | Σ $ | медиана | худшая | "
                  "хвостом | медиана плеча | funding медиана / среднее "
                  "б.п. |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
            for nm in list(BAND_NAMES) + [UNKNOWN]:
                v = b.get(nm)
                if not v:
                    continue
                L.append(
                    f"| {nm} | {v['n']} | {_u(v['usd'])} | "
                    f"{_u(v['median'])} | {_u(v['worst'])} | "
                    f"{100 * v['tail_share']:.0f} % | {v['lev']}× | "
                    + ("—" if v.get("fund_bp") is None
                       else f"{v['fund_bp']:+.0f} / {v['fund_bp_mean']:+.0f}")
                    + " |")
            L.append("")
    L += ["", "## Как читать", "",
          "- Строка «нет» — как сейчас, фильтра нет; с ней и сравнивается "
          "всё остальное.",
          "- Контроль берёт столько же коротких решений, сколько оставляет "
          "порог, но выбирает их случайно. Возраст что-то отбирает только "
          "там, где доля «бьют фильтр» мала.",
          "- «Возраст неизвестен» — своя колонка: именно её молчаливое "
          "превращение в отказ и создало ложный результат гейта по ставке.",
          "- Ячейка становится правилом только объявленной заранее и "
          "проверенной вперёд; окно одно, веса модели эти часы видели.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="возраст имени как фильтр")
    ap.add_argument("--dep", type=float, default=None)
    ap.add_argument("--seeds", type=int, default=None)
    # Разрез механизма считается по ячейке без фильтра: сетка с
    # контролем на 200 зёрнах идёт 11 минут, а «почему» — секунды.
    ap.add_argument("--only-why", action="store_true",
                    help="только разрез по возрасту, без сетки и контроля")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run(dep=a.dep, seeds=a.seeds,
            days=((0,) if a.only_why else None))
    art = os.path.join(R.OUT, "DCA-pair-age" + ("-why" if a.only_why else "")
                       + ".json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-pair-age"
                           + ("-why" if a.only_why else "") + ".md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    publish("возраст имени как фильтр короткой стороны")
    return 0


if __name__ == "__main__":
    sys.exit(main())
