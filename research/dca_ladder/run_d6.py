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
import hashlib
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
# Ось билета добавлена ПОСЛЕ первого прогона, под вопрос владельца о другом
# депозите, и потому диагностика, а не часть объявленной сетки. Нужна она
# потому, что связывает здесь АБСОЛЮТНЫЙ пол биржи ($5 на ордер): при
# фиксированной доле процент к депозиту от размера депозита не зависит
# вовсе, и единственный канал влияния — этот пол. Билет $7 и $5 при
# депозите $3000 почти совпадают с долей 1/428 и 1/600, при $10000 дают
# 1/1429 и 1/2000 — то есть показывают, докуда ширина доходит с деньгами.
GRID_TICKET = [7.0, 5.0]


def shares_for(deposit):
    """Доли сетки плюс доли, задающие объявленные билеты при этом депозите."""
    out = list(GRID_SHARE) + [t / float(deposit) for t in GRID_TICKET]
    keep = []
    for x in sorted(set(round(v, 9) for v in out), reverse=True):
        if all(abs(x - y) > 1e-9 for y in keep):
            keep.append(x)
    return keep


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


def ration(recs, share, deposit=DEPOSIT, min_notional=MIN_NOTIONAL,
           keep_rows=False):
    """Хронологическая раздача кассы. Возвращает сводку и кривую счёта.

    Порядок объявлен: деньги возвращаются раньше, чем тратятся, а внутри
    секунды достаются лучшим по |прогноз|. Отказы считаются по причинам
    раздельно — «нет кассы» и «мельче минимума биржи» лечатся разным.
    """
    order = queue(recs)
    equity, free = float(deposit), float(deposit)
    # допуск кассы ОТНОСИТЕЛЕН счёту: абсолютный 1e-9 при разных депозитах
    # решает пограничный вход по-разному, и «тот же замер на другом
    # депозите» переставал быть тем же замером
    eps = 1e-9 * float(deposit)
    live = []                       # (exit_ts, маржа, доля капитала, marks)
    taken, no_cash, too_small = 0, 0, 0
    dH, openN = {}, {}
    bysym, best_trade = {}, 0.0
    ids, pnl_taken = [], 0.0
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
        if margin > free + eps:
            no_cash += 1
            continue
        free -= margin
        taken += 1
        live.append((r["exit_ts"], margin, r["pnl"], r["marks"]))
        ids.append(f"{r['at']:.3f}:{r['sym']}")
        if keep_rows is not False:
            keep_rows.append((r, margin))
        pnl_taken += r["pnl"]
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
        # отпечаток ВЗЯТОГО набора: без него «ячейки разошлись» неотличимо
        # от «взяли разные сделки», а лечится это разным
        "fp": hashlib.sha1("|".join(sorted(ids)).encode()).hexdigest()[:12],
        "pnl_taken": round(pnl_taken, 4),
        "names": len(bysym),
        "top_sym": max(bysym, key=bysym.get) if bysym else None,
        "top_pnl": round(max(bysym.values()), 2) if bysym else 0.0,
        "final_wo_top": (round((equity - max(bysym.values())) / deposit - 1.0,
                               4) if bysym else None),
        "top_trade": round(best_trade, 2),
    }


def window(longs):
    """Окно замера ПО РЕШЕНИЯМ, а не по календарю запуска.

    Доход в процентах без окна не читается: «+20 %» за месяц и за год —
    разные утверждения. Считается по секундам решений, попавших в реплей;
    сутки — календарные UTC, как у дневного ряда книги.
    """
    if not longs:
        return None
    a0 = min(float(g["at"]) for g in longs)
    b1 = max(float(g["at"]) for g in longs)
    f = "%Y-%m-%d %H:%M"
    return {"from": time.strftime(f, time.gmtime(a0)),
            "to": time.strftime(f, time.gmtime(b1)),
            "from_ts": a0, "to_ts": b1,
            "span_h": round((b1 - a0) / HOUR, 1),
            "span_d": round((b1 - a0) / (24.0 * HOUR), 1),
            "dates": len({time.strftime("%Y-%m-%d", time.gmtime(float(g["at"])))
                          for g in longs})}


def peak_open(recs):
    """Пик одновременности — В ЛОТАХ и В ИМЕНАХ, и это РАЗНЫЕ числа.

    Реплей D-серии считает каждый выбор независимой позицией, а на одном
    счёте в одностороннем режиме у имени позиция ОДНА: второй выбор по той
    же монете есть ДОЛИВ. Значит «пик 3206» описывает лоты, а не позиции,
    и называть его позициями нельзя.

    Деньги от этого не меняются: маржа лота та же, слитая позиция требует
    их суммы, а PnL линеен (четыре лота дают то же, что одна позиция со
    средней ценой). Меняются МАРЖА И ЛИКВИДАЦИЯ — биржа считает их по
    слитой позиции, — и встречная сторона, которая на счёте схлопывает,
    а не открывает вторую.

    Очередь событий та же, что у кассы: внутри секунды закрытие раньше
    открытия. Иначе пик завышен ровно на число стыков.
    """
    ev = []
    for r in recs:
        ev.append((int(r["at"]), 1, r["sym"]))
        ev.append((int(r["exit_ts"]), -1, r["sym"]))
    ev.sort(key=lambda x: (x[0], x[1]))
    cnt, cur = {}, 0
    lots = names_at_lots = names_max = per_max = 0
    for _, d, sym in ev:
        cur += d
        c = cnt.get(sym, 0) + d
        if c > 0:
            cnt[sym] = c
        else:
            cnt.pop(sym, None)
        per_max = max(per_max, c)
        names_max = max(names_max, len(cnt))
        if cur > lots:
            lots, names_at_lots = cur, len(cnt)
    return {"lots": lots, "names_at_peak": names_at_lots,
            "names_max": names_max, "max_lots_one_name": per_max}


def one_per_name(recs):
    """Строгое биржевое правило: второй выбор по открытому имени пропущен.

    Диагностическая рука к вопросу владельца. Долив тут НЕ моделируется —
    он равен независимому лоту по деньгам, и вопрос ровно в другом: во
    сколько обойдётся, если такие сигналы просто не брать.
    """
    open_until = {}
    keep, skip = [], 0
    for r in sorted(recs, key=lambda x: (int(x["at"]), -x["fwd"])):
        t = int(r["at"])
        u = open_until.get(r["sym"])
        if u is not None and u > t:
            skip += 1
            continue
        open_until[r["sym"]] = int(r["exit_ts"])
        keep.append(r)
    return keep, skip


def full_cover(recs, min_notional=MIN_NOTIONAL, rung=RUNG_SHARE,
               log=print):
    """Депозит, при котором НИ ОДИН сигнал не отвергнут.

    Связывают ДВА условия сразу, и лечатся они одним и тем же депозитом
    только вместе с числом мест:

      мест   >= пик одновременных позиций   (иначе «нет кассы»)
      билет  >= min_notional / rung / плечо  (иначе «мельче $5»)

    Билет решает САМАЯ СЛАБАЯ по плечу позиция: взять «каждый сигнал»
    значит взять и её. Отсюда арифметический пол депозита = пик × билет;
    он и проверяется прогоном кассы, потому что маржа считается от
    ТЕКУЩЕГО счёта, и в просадке она проседает вместе с ним.
    """
    if not recs:
        return None
    pk = peak_open(recs)
    peak = pk["lots"]
    lev_min = min(float(r["lev"]) for r in recs)
    ticket = min_notional / rung / lev_min
    floor_dep = peak * ticket
    share = 1.0 / peak
    total = len(recs)
    # арифметический пол проверяется кассой: ищем наименьший множитель,
    # при котором взяты ВСЕ — иначе «хватает» осталось бы утверждением
    lo, hi, best = 1.0, 1.0, None
    for _ in range(12):
        r = ration(recs, share, deposit=floor_dep * hi,
                   min_notional=min_notional)
        if r["taken"] == total:
            best = (hi, r)
            break
        lo, hi = hi, hi * 1.25
    if best is None:
        log("  полный охват не достигнут даже при ×%.2f" % hi)
        return {"peak": peak, "peak_names": pk["names_at_peak"],
                "names_max": pk["names_max"],
                "max_lots_one_name": pk["max_lots_one_name"],
                "lev_min": round(lev_min, 3),
                "ticket": round(ticket, 2), "floor_dep": round(floor_dep, 2),
                "deposit": None, "cell": None, "total": total}
    m_hi = best[0]
    for _ in range(20):                       # уточняем вниз до 0.5 %
        mid = (lo + m_hi) / 2.0
        if m_hi - lo < 0.005:
            break
        r = ration(recs, share, deposit=floor_dep * mid,
                   min_notional=min_notional)
        if r["taken"] == total:
            m_hi, best = mid, (mid, r)
        else:
            lo = mid
    dep = floor_dep * best[0]
    cell = best[1]
    cell["ticket"] = round(dep * share, 2)
    return {"peak": peak, "peak_names": pk["names_at_peak"],
            "names_max": pk["names_max"],
            "max_lots_one_name": pk["max_lots_one_name"],
            "lev_min": round(lev_min, 3),
            "ticket": round(ticket, 2), "floor_dep": round(floor_dep, 2),
            "deposit": round(dep, 2), "mult": round(best[0], 3),
            "cell": cell, "total": total}


def coverage_curve(recs, peak, deps, min_notional=MIN_NOTIONAL):
    """Сколько сигналов берётся при депозите меньше полного охвата."""
    out = []
    for d in deps:
        r = ration(recs, 1.0 / peak, deposit=d, min_notional=min_notional)
        out.append({"deposit": round(d, 2), "taken": r["taken"],
                    "share_taken": round(r["taken"] / len(recs), 4),
                    "no_cash": r["no_cash"], "too_small": r["too_small"],
                    "final": r["final"], "max_dd": r["max_dd"]})
    return out


def collect_recs(limit=None, src=None, log=print, rulers=None):
    """Дорогой проход: исход КАЖДОГО гейтованного лонга при каждой линейке.

    Вынесен из `run`, потому что читателя стало два — сетка кассы D6 и
    бумажные книги DCA (`research/dca_paper`). Вторая копия этого прохода
    означала бы, что книга и её замер считают исходы разным кодом.
    """
    rulers = list(rulers or GRID_RULER)
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
    win = window(longs)
    log(f"лонгов под гейтом {len(longs)}, символов {len(by_sym)}")
    if win:
        log(f"окно решений {win['from']} … {win['to']} UTC "
            f"({win['span_d']:g} суток, дат {win['dates']})")

    recs = {k: [] for k in rulers}
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
            for k in rulers:
                r = one_position(g, bars, ts, look, k[0], k[1])
                if r is not None:
                    recs[k].append(r)
                    got = 1
            n += got
            skipped += (1 - got)
    return {"recs": recs, "positions": n, "skipped": skipped, "window": win}


def run(limit=None, src=None, log=print, deposit=DEPOSIT, anchor_dep=None):
    t0 = time.time()
    got = collect_recs(limit=limit, src=src, log=log)
    recs, n, skipped, win = (got["recs"], got["positions"],
                             got["skipped"], got["window"])

    shares = shares_for(deposit)
    if anchor_dep:
        # общий набор долей: опора обязана сравнивать ячейку с ячейкой
        shares = sorted(set(shares) | set(shares_for(anchor_dep)),
                        reverse=True)
    out = {"positions": n, "skipped": skipped,
           "grid": {"share": GRID_SHARE, "ticket": GRID_TICKET,
                    "shares_used": shares,
                    "ruler": [[a, b] for a, b in GRID_RULER]},
           "params": {"DEPOSIT": float(deposit), "MIN_NOTIONAL": MIN_NOTIONAL,
                      "RUNG_SHARE": RUNG_SHARE, "HOLD_H": D2.HOLD_H,
                      "FLOOR_FRAC": D2.FLOOR_FRAC},
           "window": win,
           "cells": {}, "anchor_cells": {}, "anchor_dep": anchor_dep,
           "unlimited": {}, "full": {}, "secs": 0.0}
    for k in GRID_RULER:
        rs = recs[k]
        # опора: без нормировки кассы (то, что мерил D5) — доля 1.0 и
        # минимум ордера снят; иначе «ширина помогла» будет неотличимо от
        # «мы просто дали больше денег»
        out["unlimited"][f"{k[0]}|{k[1]}"] = {
            "n": len(rs), "sum_pnl": round(sum(r["pnl"] for r in rs), 2)}
        fc = full_cover(rs, log=log)
        keep, skipped_rep = one_per_name(rs)
        fc1 = full_cover(keep, log=log) if keep else None
        if fc1:
            fc1["skipped_repeats"] = skipped_rep
            fc1["kept"] = len(keep)
        out["one_name"] = out.get("one_name") or {}
        out["one_name"][f"{k[0]}|{k[1]}"] = fc1
        out["full"][f"{k[0]}|{k[1]}"] = fc
        if fc and fc.get("deposit"):
            log(f"  полный охват {k[0]} {k[1]}: пик {fc['peak']}, "
                f"билет ${fc['ticket']:g}, депозит ${fc['deposit']:,.0f}")
            out["full"][f"{k[0]}|{k[1]}"]["curve"] = coverage_curve(
                rs, fc["peak"],
                [fc["deposit"] * q for q in (0.1, 0.25, 0.5, 0.75, 1.0)])
        for sh in shares:
            key = f"{k[0]}|{k[1]}|{sh:.6f}"
            out["cells"][key] = ration(rs, sh, deposit=deposit)
            if anchor_dep:
                out["anchor_cells"][key] = ration(rs, sh, deposit=anchor_dep)
    out["secs"] = round(time.time() - t0, 1)
    return out


def anchor_deposit(s):
    """Опора по депозиту — встроенная проверка меры, считается В ОДНОМ
    прогоне на ОДНИХ исходах.

    Сравнивать с артефактом прошлого прогона нельзя: хранилище баров
    дописывается каждый час, и исходы позиций у двух прогонов слегка
    расходятся сами — «мера сломана» тогда означало бы «данные подросли».

    Правило: при фиксированной доле процент к депозиту от депозита не
    зависит — маржа пропорциональна счёту, исход есть доля её капитала.
    Значит ячейка, взявшая ТОТ ЖЕ набор сделок (отпечаток совпал), обязана
    дать тот же процент; разошедшийся отпечаток обязан объясняться полом
    биржи. Иначе мера сломана.
    """
    ref = s.get("anchor_cells") or {}
    if not ref:
        return None
    rows, bad = [], []
    for k, c in sorted(s.get("cells", {}).items()):
        c0 = ref.get(k)
        if not c0:
            continue
        same_fp = c.get("fp") == c0.get("fp")
        same = abs(c["final"] - c0["final"]) < 1e-9
        floor = bool(c["too_small"] or c0["too_small"])
        ok = (same if same_fp else floor)
        rows.append({"cell": k, "final": c["final"], "final_ref": c0["final"],
                     "same": same, "same_fp": same_fp, "floor": floor,
                     "ok": ok, "pnl_taken": c.get("pnl_taken"),
                     "pnl_taken_ref": c0.get("pnl_taken"),
                     "too_small": c["too_small"],
                     "too_small_ref": c0["too_small"]})
        if not ok:
            bad.append(k)
    return {"dep": (s.get("params") or {}).get("DEPOSIT"),
            "dep_ref": s.get("anchor_dep"),
            "rows": rows, "bad": bad,
            "n_same": sum(1 for x in rows if x["same"])}


def _anchor_block(a):
    if not a:
        return []
    L = ["## Опора: тот же замер на депозите "
         f"${a['dep_ref']:g}", "",
         "Встроенная проверка меры, а не справка, и считается она В ЭТОМ "
         "ЖЕ прогоне на ОДНИХ исходах: хранилище баров дописывается "
         "каждый час, и сравнение с артефактом прошлого прогона называло "
         "бы «мерой сломанной» подросшие данные.", "",
         "При фиксированной доле процент к депозиту от размера депозита "
         "НЕ зависит — маржа пропорциональна счёту, исход позиции есть "
         "доля её капитала. Единственный канал влияния — абсолютный пол "
         "биржи в $5. Значит ячейка, взявшая ТОТ ЖЕ набор сделок "
         "(отпечаток совпал), обязана дать тот же процент, а разошедшийся "
         "набор обязан объясняться полом.", "",
         "| ячейка | доход здесь | там | совпало | отказов по полу |",
         "|---|--:|--:|:--|--:|"]
    for x in a["rows"]:
        if x["same"]:
            mark = "да"
        elif not x["same_fp"]:
            mark = ("взят другой набор — пол биржи" if x["floor"]
                    else "**взят другой набор БЕЗ пола — мера сломана**")
        else:
            mark = "**тот же набор, а процент другой — мера сломана**"
        L.append(f"| {x['cell']} | {_pct(x['final'])} | "
                 f"{_pct(x['final_ref'])} | {mark} | "
                 f"{x['too_small']} / {x['too_small_ref']} |")
    L.append("")
    if a["bad"]:
        L += ["**Мера сломана: расхождение без отказов по полу в ячейках "
              + ", ".join(a["bad"]) + ". Таблицу читать нельзя.**", ""]
    else:
        L += [f"Совпало дословно {a['n_same']} ячеек из {len(a['rows'])}; "
              "остальные расходятся ровно там, где пол биржи связывает. "
              "Проверка пройдена.", ""]
    return L


def _full_block(s):
    """Депозит, при котором берётся каждый сигнал, и что тогда выходит."""
    full = s.get("full") or {}
    if not full:
        return []
    L = ["## Полный охват: депозит, при котором не отвергнут НИ ОДИН сигнал",
         "",
         "Связывают два условия сразу, и порознь они не лечатся: мест "
         "должно быть не меньше ПИКА одновременных позиций (иначе «нет "
         "кассы»), а билет — не меньше `$5 / 0.25 / плечо` (иначе «мельче "
         "$5»). Билет назначает САМАЯ СЛАБАЯ по плечу позиция: «каждый "
         "сигнал» включает и её.", "",
         "**Пик считается в ЛОТАХ, а не в позициях, и путать их нельзя.** "
         "Реплей берёт каждый выбор независимо, а на одном счёте в "
         "одностороннем режиме у имени позиция ОДНА: второй выбор по той "
         "же монете есть долив. Деньги от этого не меняются (маржа лота та "
         "же, PnL линеен), а вот маржа и цена ликвидации на бирже "
         "считаются по СЛИТОЙ позиции — этого реплей не моделирует.", "",
         "| линейка | сигналов | пик лотов | имён в пике | макс. лотов на "
         "имя | мин. плечо | билет | депозит | загрузка | доход | "
         "просадка | худший день |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for rule, param in GRID_RULER:
        f = full.get(f"{rule}|{param}")
        if not f:
            continue
        name = ("нынешняя 2·d_max" if rule == "depth"
                else f"σ-линейка {param:g}·σ")
        c = f.get("cell")
        pre = (f"| {name} | {f['total']} | {f['peak']} | "
               f"{f.get('peak_names', '—')} | "
               f"{f.get('max_lots_one_name', '—')} | {f['lev_min']:g}× |")
        if not c:
            L.append(pre + f" ${f['ticket']:g} | — | — | — | — | — |")
            continue
        u = c["open_mean"] * c["ticket"] / f["deposit"]
        L.append(
            pre + f" ${c['ticket']:g} | ${f['deposit']:,.0f} | "
            f"{100 * u:.1f} % | {_pct(c['final'])} | {_pct(c['max_dd'])} | "
            f"{_pct(c['day_worst'])} |")
    L += ["",
          "**Итог полного охвата предсказуем арифметикой, и это проверка, "
          "а не совпадение:** когда взяты ВСЕ сигналы и у каждого одна и "
          "та же доля счёта `1/пик`, доход к депозиту равен сумме исходов, "
          "делённой на пик. Депозит из формулы не выпадает вовсе — он "
          "решает только, помещаются ли все, а не сколько они приносят.",
          ""]
    one = s.get("one_name") or {}
    if any(one.values()):
        L += ["### Строгое биржевое правило: одна позиция на имя", "",
              "Второй выбор по уже открытому имени просто пропущен. Долив "
              "здесь НЕ моделируется намеренно: по деньгам он равен "
              "независимому лоту, и вопрос ровно в другом — во сколько "
              "обойдётся, если такие сигналы не брать вовсе.", "",
              "| линейка | взято | пропущено повторов | пик лотов | "
              "депозит | доход | просадка |", "|---|--:|--:|--:|--:|--:|--:|"]
        for rule, param in GRID_RULER:
            f1 = one.get(f"{rule}|{param}")
            if not f1:
                continue
            name = ("нынешняя 2·d_max" if rule == "depth"
                    else f"σ-линейка {param:g}·σ")
            c1 = f1.get("cell")
            dep = (f"${f1['deposit']:,.0f}" if f1.get("deposit") else "—")
            L.append(
                f"| {name} | {f1.get('kept', '—')} | "
                f"{f1.get('skipped_repeats', '—')} | {f1['peak']} | {dep} | "
                + (f"{_pct(c1['final'])} | {_pct(c1['max_dd'])} |"
                   if c1 else "— | — |"))
        L.append("")
    rows = []
    for rule, param in GRID_RULER:
        f = full.get(f"{rule}|{param}")
        for x in (f or {}).get("curve") or []:
            name = ("нынешняя 2·d_max" if rule == "depth"
                    else f"σ-линейка {param:g}·σ")
            rows.append((name, x))
    if rows:
        L += ["### Чем платит депозит меньше полного", "",
              "| линейка | депозит | взято | нет кассы | мельче $5 | доход | "
              "просадка |", "|---|--:|--:|--:|--:|--:|--:|"]
        for name, x in rows:
            L.append(
                f"| {name} | ${x['deposit']:,.0f} | "
                f"{x['taken']} ({100 * x['share_taken']:.0f} %) | "
                f"{x['no_cash']} | {x['too_small']} | {_pct(x['final'])} | "
                f"{_pct(x['max_dd'])} |")
        L += ["", "Число мест здесь ОДНО и равно пику — меняется только "
              "депозит, то есть размер билета. Поэтому падение охвата "
              "читается по колонкам отказов: пока связывает «нет кассы», "
              "помогут и деньги, и места; когда «мельче $5» — только "
              "деньги.", ""]
    return L


def _shares_of(s):
    """Доли берутся из АРТЕФАКТА, а не из констант: отчёт обязан описывать
    тот прогон, который породил файл (урок R1)."""
    g = s.get("grid") or {}
    return g.get("shares_used") or g.get("share") or GRID_SHARE


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
        f"фиксирован (**${dep:g}**), доля на "
        "позицию объявлена, и вход, которому не хватило денег, не "
        "случается. Единица ответа одна у всех ячеек — проценты ДЕПОЗИТА.",
        "",
        f"Позиций {s.get('positions', 0)}, пропущено {s.get('skipped', 0)}, "
        f"прогон {s.get('secs', 0)} с.",
        "",
        _window_line(s.get("window")),
        "",
        "## Ячейки",
        "",
        "| линейка | мест | на позицию | взято | нет кассы | мельче $5 | "
        "открыто разом | доход на депозит | просадка | худший день |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for rule, param in GRID_RULER:
        name = ("нынешняя 2·d_max" if rule == "depth" else f"σ-линейка {param:g}·σ")
        for sh in _shares_of(s):
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
        for sh in _shares_of(s):
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
    L1 += _full_block(s)
    L1 += _anchor_block(s.get("anchor_deposit"))
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


def _restat_window(s, log=print):
    """Окно дописывается в готовый артефакт, ЧИСЕЛ не трогая.

    Журнал листов растёт каждый час, поэтому окно, посчитанное позже
    прогона, может оказаться шире того, что прогон видел. Расхождение
    называется числом, а не сглаживается (узор опоры D5).
    """
    legs = TNT.legs_from_sheets([D2.SHEETS])
    longs = [g for g in legs if g["side"] == "long"
             and abs(g["fwd"]) >= D2.MIN_EDGE_BP
             and (g["rr"] or 0) >= D2.MIN_RR]
    w = window(longs)
    was = s.get("positions")
    if w and was and len(longs) != was:
        w["grown"] = len(longs) - was
        log(f"журнал вырос с прогона: {was} → {len(longs)} выборов; "
            "окно шире того, что видел прогон, на этот хвост")
    return w


def _window_line(w):
    if not w:
        return ("**Окно замера не записано** — прогон прежнего образца; "
                "доход в процентах без окна не читается.")
    return (f"**Окно замера: {w['from']} … {w['to']} UTC, это "
            f"{w['span_d']:g} суток** ({w['dates']} календарных дат с "
            "решениями). Весь доход в таблицах — за этот отрезок целиком, "
            "а не за год: годовых здесь нет и приводить их к году на "
            "одном месяце одного режима рынка нельзя."
            + (f" Окно дописано в готовый артефакт позже прогона, и журнал "
               f"с тех пор вырос на {w['grown']} выборов — то есть верхний "
               "край окна шире того, что прогон видел, на этот хвост."
               if w.get("grown") else ""))


def publish(name):
    sh = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools",
                      "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--deposit", type=float, default=DEPOSIT)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--window", action="store_true",
                    help="напечатать окно замера и выйти")
    ap.add_argument("--restat", action="store_true",
                    help="дописать окно в готовый артефакт и пересобрать "
                         "отчёт, не пересчитывая ничего")
    a = ap.parse_args()
    if a.window:
        legs = TNT.legs_from_sheets([D2.SHEETS])
        longs = [g for g in legs if g["side"] == "long"
                 and abs(g["fwd"]) >= D2.MIN_EDGE_BP
                 and (g["rr"] or 0) >= D2.MIN_RR]
        w = window(longs)
        print(f"лонгов под гейтом {len(longs)}")
        print(_window_line(w))
        return
    os.makedirs(OUT, exist_ok=True)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    if abs(a.deposit - DEPOSIT) > 1e-9:
        tag = f"{tag}-d{int(round(a.deposit))}"
    base = os.path.join(OUT, f"D6-cash-{tag}")
    if a.restat:
        with open(base + ".json", encoding="utf-8") as f:
            s = json.load(f)
        s["window"] = _restat_window(s, log=print)
    else:
        anc = DEPOSIT if abs(a.deposit - DEPOSIT) > 1e-9 else None
        s = run(limit=a.limit, deposit=a.deposit, anchor_dep=anc)
        s["anchor_deposit"] = anchor_deposit(s)
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
