#!/usr/bin/env python3
"""
D6 (спека 14) — НОРМИРОВКА КАССЫ: мало крупных мест или много мелких.

Вопрос владельца: «убрать правило шести мест, открывать как можно больше,
но давать каждому меньше денег». D5 показал, почему вопрос настоящий:
реплей кассу не нормирует вовсе — каждый прошедший гейт выбор получает
полный капитал, книга держит от 70 до 3206 позиций разом, и депозит под
пик простаивает 98 % времени. То есть «сколько приносит стратегия» на
таких числах назвать нельзя: это доход сигнала, а не счёта.

Здесь добавляется единственное, чего не хватало, — КАССА. Депозит
фиксирован, доля на позицию объявлена, и вход, которому не хватило денег,
не случается. Тогда «мало крупных против много мелких» становится
измеримым разменом, а не спором.

**Почему это дёшево.** Исход позиции не зависит от того, сколько ещё
позиций открыто: рынка мы не двигаем, а забор считает плечо по данным
самой позиции. Значит проход по хранилищу нужен ОДИН, а раздача денег
есть чистая бухгалтерия поверх готовых исходов. PnL масштабируется
линейно: доля капитала × выданная маржа.

Сетка объявлена ДО прогона и не меняется после чтения результата:

    доля депозита на позицию: 1/6, 1/20, 1/60, 1/200, 1/600
    линейка забора: нынешняя (2·d_max) и σ-линейка (6·σ)

Вторая ось — не украшение: минимальный ордер площадки ровно $5 у 1540
инструментов из 1540 (замер справочника), лестница набирается четырьмя
рунгами по 25 %, значит нотионал позиции обязан быть не меньше $20, а
денег из депозита на неё нужно `$20 / плечо`. σ-линейка снижает плечо и
тем самым УВЕЛИЧИВАЕТ минимальный кусок депозита — то есть два рычага
дерутся, и увидеть это можно только на общей сетке.

Три правила раздачи, каждое объявлено до прогона:

* **Деньги возвращаются раньше, чем тратятся.** Позиция, закрывшаяся в
  ту же секунду, освобождает кассу до того, как её займёт новая — то же
  правило, что в живой кассе проекта (`trades.account`).
* **Внутри секунды деньги достаются лучшим по |прогноз|.** Порядок
  прихода произволен, и раздача по нему сравнивала бы удачу, а не
  ширину: узкая книга обязана брать лучшие сигналы, иначе её проигрыш
  припишется ширине.
* **Мелкий ордер — отказ, а не округление вверх.** Округлив до минимума,
  мы дали бы позиции больше денег, чем позволяет доля, и узкая книга
  победила бы арифметикой показа.

Отказы считаются ПО ПРИЧИНАМ раздельно: «нет кассы» и «мельче минимума
биржи» лечатся разным (первое — уже места, второе — крупнее депозит).

Единица ответа одна и та же у всех ячеек: **доход и просадка в процентах
ДЕПОЗИТА**, потому что депозит фиксирован. Это и есть число, которого до
сих пор не было.

Оговорки (в силе с D2): веса модели видели эти часы; издержки круга в
исходе позиции не сняты; период один и режим рынка один; проскальзывание
не моделируется, а книга из сотен мелких ордеров платит его больше.

Запуск (VPS — журнал листов и бары только там):

    setsid nohup .venv/bin/python research/dca_ladder/run_d6.py \\
        > research/dca_ladder/out/run_d6.log 2>&1 &

Смоук: `--limit 400`. Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import run_d4 as D4                                           # noqa: E402
import run_d5 as D5                                           # noqa: E402
import tournament as TNT                                      # noqa: E402
import sweep as SW                                            # noqa: E402
import trades as TR                                           # noqa: E402

ROOT_B1 = D4.ROOT_B1
HOUR = 3600

# --- объявленная сетка и правила (до прогона) ----------------------------
DEPOSIT = TR.START_BALANCE          # 3000 $ — капитал бумажной книги
MIN_NOTIONAL = 5.0                  # минимум ордера: ровно $5 у 1540 из 1540
RUNG_SHARE = min(D2.WEIGHTS)        # 0.25 — самый мелкий рунг лестницы
GRID_SHARE = [1.0 / 6, 1.0 / 20, 1.0 / 60, 1.0 / 200, 1.0 / 600]
GRID_RULER = [("depth", 2.0), ("sigma", 6.0)]


def one_position(g, bars, ts, look, rule, param):
    """Исход одной позиции при заданной линейке забора. Гейты — D2.

    Возвращает запись для раздачи: когда решение, когда выход, доля
    капитала, плечо и почасовые отметки (для кривой счёта).
    """
    rs = D2.split_window(bars, ts, g["at"], D2.BACK_H, D2.HOLD_H)
    if rs is None:
        return None
    win, now_i = rs
    hold = win[now_i:]
    entry = float(hold[0][1])
    if entry <= 0:
        return None
    take_px = entry * (1 + g["fav"] / 1e4)
    stop_px = entry * (1 + g["adv_q"] / 1e4)
    if not (take_px > entry and 0 < stop_px < entry):
        return None
    lv = D2.build_levels(win, now_i)
    rungs_full = D2.structural_rungs(entry, list(lv), D2.MIN_ADD_GAP,
                                     D2.N_RUNGS)
    sigma_bp, _r, _t = D3.window_stats(win, now_i)
    lev, rungs, _binder = D5.fence_leverage(rule, param, entry, rungs_full,
                                            look, sigma_bp)
    r = L.simulate_dca(hold, rungs, D2.WEIGHTS[:len(rungs)], 1.0, lev,
                       look(1.0 * lev), take_px=take_px,
                       floor_frac=D2.FLOOR_FRAC, track=True)
    marks, prev = [], 0.0
    for (hr, _cash, pnl) in r["track"]:
        marks.append((hr, pnl - prev))     # приращение отметки за час
        prev = pnl
    return {"at": float(g["at"]), "exit_ts": float(r["exit_ts"]),
            "pnl": float(r["pnl_frac"]), "lev": float(lev),
            "fwd": abs(float(g["fwd"])), "sym": g["sym"],
            "exit": r["exit"], "marks": marks}


def queue(recs):
    """Очередь за деньгами: по секунде решения, внутри секунды — лучшие.

    Правило объявлено до прогона и вынесено отдельно намеренно: раздача
    по порядку прихода сравнивала бы удачу, а не ширину, и узкая книга
    проигрывала бы не потому, что узка. Отдельная функция делает правило
    проверяемым — подменив её, контроль обязан уронить проверку.
    """
    return sorted(recs, key=lambda r: (int(r["at"]), -r["fwd"]))


def ration(recs, share, deposit=DEPOSIT, min_notional=MIN_NOTIONAL):
    """Хронологическая раздача кассы. Возвращает сводку и кривую счёта.

    Порядок объявлен: деньги возвращаются раньше, чем тратятся, а внутри
    секунды достаются лучшим по |прогноз|. Отказы считаются по причинам
    раздельно — «нет кассы» и «мельче минимума биржи» лечатся разным.
    """
    order = queue(recs)
    equity, free = float(deposit), float(deposit)
    live = []                       # (exit_ts, маржа, доля капитала, marks)
    taken, no_cash, too_small = 0, 0, 0
    dH, openN = {}, {}
    bysym, best_trade = {}, 0.0
    for r in order:
        now = int(r["at"])
        # 1. деньги возвращаются раньше, чем тратятся
        still = []
        for p in live:
            if int(p[0]) <= now:
                free += p[1]
                equity += p[1] * p[2]
            else:
                still.append(p)
        live = still
        # 2. размер по доле ТЕКУЩЕГО счёта
        margin = equity * share
        notional = margin * r["lev"]
        if notional * RUNG_SHARE < min_notional:
            too_small += 1
            continue
        if margin > free + 1e-9:
            no_cash += 1
            continue
        free -= margin
        taken += 1
        live.append((r["exit_ts"], margin, r["pnl"], r["marks"]))
        got = r["pnl"] * margin
        bysym[r["sym"]] = bysym.get(r["sym"], 0.0) + got
        best_trade = max(best_trade, got)
        for (hr, d) in r["marks"]:
            dH[hr] = dH.get(hr, 0.0) + d * margin
        h0 = now - (now % HOUR)
        h1 = int(r["exit_ts"]) - (int(r["exit_ts"]) % HOUR)
        for hr in range(h0, h1 + HOUR, HOUR):
            openN[hr] = openN.get(hr, 0) + 1
    for p in live:                  # хвост: закрываем то, что осталось
        equity += p[1] * p[2]
    hrs = sorted(dH)
    eq, curve, day = float(deposit), [], {}
    for hr in hrs:
        eq += dH[hr]
        curve.append(eq)
        d = time.strftime("%Y-%m-%d", time.gmtime(hr))
        day[d] = day.get(d, 0.0) + dH[hr]
    c = np.array(curve, dtype=float) if curve else np.array([deposit])
    dd = float(np.min(c / np.maximum.accumulate(c) - 1.0)) if len(c) else 0.0
    dv = np.array([day[k] for k in sorted(day)], dtype=float) if day \
        else np.array([0.0])
    nn = np.array([openN[h] for h in hrs], dtype=float) if hrs \
        else np.array([0.0])
    total = taken + no_cash + too_small
    return {
        "taken": taken, "no_cash": no_cash, "too_small": too_small,
        "take_share": round(taken / total, 4) if total else None,
        "final": round(equity / deposit - 1.0, 4),
        "max_dd": round(dd, 4),
        "day_median": round(float(np.median(dv)) / deposit, 5),
        "day_worst": round(float(np.min(dv)) / deposit, 4),
        "day_green": round(float(np.mean(dv > 0)), 3),
        "days": len(day),
        "open_mean": round(float(np.mean(nn)), 1),
        "open_median": round(float(np.median(nn)), 1),
        "open_max": int(np.max(nn)) if len(nn) else 0,
        "slots": int(round(1.0 / share)),
        "ticket": round(deposit * share, 2),
        # концентрация: вычитание, а не пересчёт (см. отчёт)
        "names": len(bysym),
        "top_sym": max(bysym, key=bysym.get) if bysym else None,
        "top_pnl": round(max(bysym.values()), 2) if bysym else 0.0,
        "final_wo_top": (round((equity - max(bysym.values())) / deposit - 1.0,
                               4) if bysym else None),
        "top_trade": round(best_trade, 2),
    }


def run(limit=None, src=None, log=print):
    t0 = time.time()
    legs = TNT.legs_from_sheets([D2.SHEETS], log=log)
    get = src.bars if src else (lambda s, a, b: SW.read_bars(ROOT_B1, s, a, b))
    tiers_all = D2.instruments_tiers()
    longs = [g for g in legs if g["side"] == "long"
             and abs(g["fwd"]) >= D2.MIN_EDGE_BP
             and (g["rr"] or 0) >= D2.MIN_RR]
    if limit:
        longs = longs[:limit]
    by_sym = {}
    for g in longs:
        by_sym.setdefault(g["sym"], []).append(g)
    log(f"лонгов под гейтом {len(longs)}, символов {len(by_sym)}")

    recs = {k: [] for k in GRID_RULER}
    n, skipped = 0, 0
    said, done = time.time(), 0
    for sym, glist in by_sym.items():
        done += 1
        if time.time() - said > 30:
            log(f"  символ {done}/{len(by_sym)}  взято {n}")
            said = time.time()
        a0 = min(gg["at"] for gg in glist) - D2.BACK_H * HOUR
        b1 = max(gg["at"] for gg in glist) + D2.HOLD_H * HOUR
        bars = get(sym, a0, b1)
        if not bars:
            skipped += len(glist)
            continue
        ts = [bb[0] for bb in bars]
        tiers = tiers_all.get(sym) or []
        look = lambda notl: L.mmr_for_notional(tiers, notl, flat=D2.FLAT_MMR)
        for g in glist:
            got = 0
            for k in GRID_RULER:
                r = one_position(g, bars, ts, look, k[0], k[1])
                if r is not None:
                    recs[k].append(r)
                    got = 1
            n += got
            skipped += (1 - got)

    out = {"positions": n, "skipped": skipped,
           "grid": {"share": GRID_SHARE,
                    "ruler": [[a, b] for a, b in GRID_RULER]},
           "params": {"DEPOSIT": DEPOSIT, "MIN_NOTIONAL": MIN_NOTIONAL,
                      "RUNG_SHARE": RUNG_SHARE, "HOLD_H": D2.HOLD_H,
                      "FLOOR_FRAC": D2.FLOOR_FRAC},
           "cells": {}, "unlimited": {}, "secs": 0.0}
    for k in GRID_RULER:
        rs = recs[k]
        # опора: без нормировки кассы (то, что мерил D5) — доля 1.0 и
        # минимум ордера снят; иначе «ширина помогла» будет неотличимо от
        # «мы просто дали больше денег»
        out["unlimited"][f"{k[0]}|{k[1]}"] = {
            "n": len(rs), "sum_pnl": round(sum(r["pnl"] for r in rs), 2)}
        for sh in GRID_SHARE:
            out["cells"][f"{k[0]}|{k[1]}|{sh:.6f}"] = ration(rs, sh)
    out["secs"] = round(time.time() - t0, 1)
    return out


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def report(s):
    p = s.get("params", {})
    dep = p.get("DEPOSIT", DEPOSIT)
    L1 = [
        "# D6 — нормировка кассы: мало крупных мест или много мелких",
        "",
        "Диагностика, не вердикт: сетка объявлена в коде до прогона, "
        "печатаются все ячейки. Вопрос владельца — «убрать правило шести "
        "мест, открывать как можно больше, но давать каждому меньше».",
        "",
        "**Чего не хватало до этого.** Реплей D2–D5 кассу не нормирует "
        "вовсе: каждый прошедший гейт выбор получает полный капитал. "
        "Поэтому его числа — доход СИГНАЛА, а не счёта. Здесь депозит "
        f"фиксирован (**${dep:g}**, капитал бумажной книги), доля на "
        "позицию объявлена, и вход, которому не хватило денег, не "
        "случается. Единица ответа одна у всех ячеек — проценты ДЕПОЗИТА.",
        "",
        f"Позиций {s.get('positions', 0)}, пропущено {s.get('skipped', 0)}, "
        f"прогон {s.get('secs', 0)} с.",
        "",
        "## Ячейки",
        "",
        "| линейка | мест | на позицию | взято | нет кассы | мельче $5 | "
        "открыто разом | доход на депозит | просадка | худший день |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for rule, param in GRID_RULER:
        name = ("нынешняя 2·d_max" if rule == "depth" else f"σ-линейка {param:g}·σ")
        for sh in GRID_SHARE:
            c = s["cells"].get(f"{rule}|{param}|{sh:.6f}")
            if not c:
                continue
            L1.append(
                f"| {name} | {c['slots']} | ${c['ticket']:g} | "
                f"{c['taken']} | {c['no_cash']} | {c['too_small']} | "
                f"{c['open_mean']:.0f} (макс {c['open_max']}) | "
                f"{_pct(c['final'])} | {_pct(c['max_dd'])} | "
                f"{_pct(c['day_worst'])} |")
    L1 += ["", "«Мест» — сколько позиций помещается в депозит при этой "
           "доле; «на позицию» — сколько денег ей достаётся. Отказы "
           "разделены намеренно: **нет кассы** лечится бо́льшим числом "
           "мест, **мельче $5** — только бо́льшим депозитом, и смешивать "
           "их значит лечить не то.", "",
           "**Ячейки не парны, и складывать их разницу с шириной нельзя.** "
           "При разном числе мест касса пускает РАЗНЫЕ выборы: у шести "
           "мест это единицы процентов сигнала, у шестисот — пятая часть. "
           "Значит различие итогов принадлежит и ширине, и составу "
           "взятого, а разделить их эта сетка не умеет.", ""]
    L1 += ["## Концентрация: сколько принадлежит одному имени", "",
           "Итог из тысячи сделок выглядит статистикой, пока не сказано, "
           "сколько денег в нём принадлежит одному разгону. Колонка "
           "«без лучшего имени» — ВЫЧИТАНИЕ, а не пересчёт: убрав имя, "
           "книга потратила бы освободившиеся деньги на другие входы. "
           "Она отвечает на «чьи это деньги», а не на «что было бы».", "",
           "| линейка | мест | имён | лучшее имя | его $ | итог без него | "
           "лучшая сделка |",
           "|---|--:|--:|---|--:|--:|--:|"]
    for rule, param in GRID_RULER:
        name = ("нынешняя 2·d_max" if rule == "depth"
                else f"σ-линейка {param:g}·σ")
        for sh in GRID_SHARE:
            c = s["cells"].get(f"{rule}|{param}|{sh:.6f}")
            if not c:
                continue
            if not c.get("names"):
                L1.append(f"| {name} | {c['slots']} | 0 | — | — | — | — |")
                continue
            L1.append(
                f"| {name} | {c['slots']} | {c['names']} | "
                f"{c.get('top_sym') or '—'} | ${c['top_pnl']:g} | "
                f"{_pct(c['final_wo_top'])} | ${c['top_trade']:g} |")
    L1.append("")
    u = s.get("unlimited") or {}
    if u:
        L1 += ["## Опора: без нормировки кассы", "",
               "То, что мерил D5 — каждый выбор получает полный капитал. "
               "Стоит здесь, чтобы «ширина помогла» не оказалось "
               "неотличимо от «мы просто дали книге больше денег».", "",
               "| линейка | позиций | Σ исходов (капиталов позиции) |",
               "|---|--:|--:|"]
        for rule, param in GRID_RULER:
            v = u.get(f"{rule}|{param}")
            if v:
                name = ("нынешняя 2·d_max" if rule == "depth"
                        else f"σ-линейка {param:g}·σ")
                L1.append(f"| {name} | {v['n']} | {v['sum_pnl']} |")
        L1.append("")
    L1 += ["**Оговорки.** Веса модели видели эти часы (оценка сверху). "
           "Издержки круга в исходе позиции не сняты, а книга из сотен "
           "мелких ордеров платит проскальзывания больше — оно не "
           "моделируется вовсе. Период один и режим рынка один. Внутри "
           "секунды деньги достаются лучшим по |прогноз|: раздача по "
           "порядку прихода сравнивала бы удачу, а не ширину.", ""]
    return "\n".join(L1)


def publish(name):
    sh = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools",
                      "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    s = run(limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    base = os.path.join(OUT, f"D6-cash-{tag}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D6: нормировка кассы ({tag})")


if __name__ == "__main__":
    main()
