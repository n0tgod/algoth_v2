#!/usr/bin/env python3
"""
D4 (спека 14) — хедж на уровне КНИГИ, а не позиции.

Владелец (2026-09-04): «хедж на уровне книги, а не позиции ещё нужно
проверить». Это последняя непроверенная форма, и замером (б) она НЕ
закрыта — там мерилась другая вещь.

Чем отличается от уже закрытого. Рука SH в D2 хеджировала КАЖДУЮ позицию
отдельно: свой короткий BTC на β·нотионал, открыт с её входом, закрыт с
её выходом, всегда. Книжный хедж отличается тремя вещами, и каждая
меняет арифметику:

1. **Сальдирование.** Хеджируется суммарная экспозиция ОТКРЫТЫХ позиций в
   каждый час, а не каждая по отдельности. Позиционный хедж сматчен к
   ИТОГОВОМУ нотионалу лестницы и потому перехеджирует, пока лестница ещё
   не набрана.
2. **Условность.** Хедж включается, только когда книга в просадке — «чтобы
   поддержать деп» дословно. В обычное время он не стоит ничего, и
   арифметика «переплатили в 48 раз» к нему не применима по построению.
3. **Единица.** Размер считается от экспозиции книги, а не от позиции.

И главное: **просадка КНИГИ — не то же, что хвост ПОЗИЦИИ.** Замер (б)
показал, что хвост позиции идиосинкратичен (альт валится сам, рынок при
этом часто рос), и рыночным хеджем не берётся. Но книга проседает, когда
просело МНОГО позиций разом, а это уже кандидат в рыночное событие.
Поэтому вопрос владельца открыт, а не отвечен задним числом.

Что считается. Базовая ячейка (забор 2.0, пол 0.10 — книга как она
торгует сегодня) прогоняется с почасовой отметкой каждой позиции;
отметки сворачиваются в почасовую книгу: экспозиция, изменение денег,
средневзвешенная бета. Дальше — сетка правил хеджа, объявленная ДО
прогона, и обязательный нуль СЛУЧАЙНОГО МОМЕНТА: тот же хедж, включённый
на столько же часов, но выбранных наугад. Без него «хедж помог»
неотличимо от «мы случайно были в шорте на падении» — то же место, где
нуль 4 был обязателен в S1.

Хронология без заглядывания: размер хеджа в час `h` считается по
экспозиции, бете и просадке, известным к КОНЦУ часа `h−1`; просадка
меряется по СОБСТВЕННОЙ кривой хеджированной книги (её и видит оператор),
а не по нехеджированной. Издержки хеджа — половина круга на каждое
изменение нотионала, то есть полный круг за «включил и выключил».

Встроенная сверка: сумма почасовых изменений книги обязана совпасть с
суммой исходов позиций базовой ячейки — иначе свод описывает другую
книгу.

Запуск (VPS):

    setsid nohup .venv/bin/python research/dca_ladder/run_d4.py \\
        > research/dca_ladder/out/run_d4.log 2>&1 &

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
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import tournament as TNT                                      # noqa: E402
import sweep as SW                                            # noqa: E402
import trades as TR                                           # noqa: E402

HOUR = 3600
ROOT_B1 = os.path.join(RESEARCH, "b1_book", "out")

# --- объявленная сетка (до прогона) ---------------------------------------
# Порог просадки книги, при котором хедж включается. 0.0 — всегда включён
# (это сальдированный аналог руки SH и заодно верхняя граница цены хеджа).
GRID_DD = [0.0, 0.03, 0.07, 0.15]
# Доля хеджируемой беты: 1.0 — полная нейтрализация рыночной ноги.
GRID_MULT = [0.5, 1.0]
NULL_SEEDS = 10                    # нулей случайного момента, зерно числом
NULL_SEED0 = 20260904
MARKET = D2.MARKET                 # прокси рыночной волны — BTC
HALF_ROUND = TR.ROUND_COST_BP / 2.0 / 1e4      # половина круга на изменение


def book_hours(legs, get, log, limit=None):
    """Почасовая книга: экспозиция, изменение денег, бета — из отметок позиций.

    Возвращает (часы, dP, X, BW, coverage, sum_pnl, n). `dP[h]` — изменение
    денег книги за час `h` в долях капитала ПОЗИЦИИ (у каждой позиции
    капитал 1.0), `X[h]` — занятый нотионал открытых на конец часа,
    `BW[h]` — сумма `β·нотионал` по тем, у кого бета известна.
    """
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

    dP, X, BW, BC = {}, {}, {}, {}
    sum_pnl, n, skipped = 0.0, 0, 0
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
            r = _one(g, bars, ts, look)
            if r is None:
                skipped += 1
                continue
            beta = g.get("beta")
            prev = 0.0
            for (hr, cash, pnl) in r["track"]:
                dP[hr] = dP.get(hr, 0.0) + (pnl - prev)
                X[hr] = X.get(hr, 0.0) + cash
                if beta is not None:
                    BW[hr] = BW.get(hr, 0.0) + float(beta) * cash
                    BC[hr] = BC.get(hr, 0.0) + cash
                prev = pnl
            sum_pnl += r["pnl_frac"]
            n += 1
    hrs = sorted(X)
    cov = (sum(BC.get(h, 0.0) for h in hrs) / sum(X[h] for h in hrs)
           if hrs and sum(X[h] for h in hrs) > 0 else 0.0)
    return hrs, dP, X, BW, BC, cov, sum_pnl, n, skipped


def _one(g, bars, ts, look):
    """Базовая ячейка (забор 2.0, пол 0.10) одной позиции — с отметкой.

    Геометрия и забор берутся у D3 (`leg_cells` считает всю сетку), но
    здесь нужна ровно одна ячейка с почасовой отметкой, поэтому шаги
    повторяют её путь через ОБЩИЕ функции D2, а не через свою копию.
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
    rungs = D2.structural_rungs(entry, list(lv), D2.MIN_ADD_GAP, D2.N_RUNGS)
    if len(rungs) < 2:
        lev, rungs = 1.0, [entry]
    else:
        d_max = (entry - rungs[-1]) / entry
        lev = L.max_leverage(rungs, D2.WEIGHTS[:len(rungs)], 1.0, entry,
                             d_max, look, D2.SURVIVE_MULT)
        if lev <= 0:
            lev, rungs = 1.0, [entry]
    return L.simulate_dca(hold, rungs, D2.WEIGHTS[:len(rungs)], 1.0, lev,
                          look(1.0 * lev), take_px=take_px,
                          floor_frac=D2.FLOOR_FRAC, track=True)


def market_returns(hrs, get, log):
    """Часовые доходности рыночной ноги на сетке книги. Нет бара — NaN."""
    if not hrs:
        return {}
    bars = get(MARKET, hrs[0] - 2 * HOUR, hrs[-1] + 2 * HOUR)
    if not bars:
        log(f"баров {MARKET} нет — хедж не считается")
        return {}
    close = {}
    for (bt, _o, _h, _l, cl, _v) in bars:
        close[bt - (bt % HOUR)] = float(cl)       # последний бар часа
    out = {}
    for h in hrs:
        a, b = close.get(h - HOUR), close.get(h)
        out[h] = (b / a - 1.0) if (a and b and a > 0) else float("nan")
    return out


def simulate_hedge(hrs, dP, X, BW, BC, rmkt, dd_on, mult, on_hours=None):
    """Кривая книги с хеджем. Решение часа `h` — по состоянию конца `h−1`.

    `on_hours` — если задано, хедж включается ровно в эти часы (нуль
    случайного момента), а порог просадки игнорируется: сравнивать надо
    ту же экспозицию, включённую наугад.
    """
    eq, peak = 1.0, 1.0
    curve, day, prev_notl, cost_tot, on_n = [], {}, 0.0, 0.0, 0
    for i, h in enumerate(hrs):
        ph = hrs[i - 1] if i else None
        xp = X.get(ph, 0.0) if ph is not None else 0.0
        den = X.get(h, 0.0) or xp
        # решение по состоянию, известному к концу прошлого часа
        if on_hours is not None:
            on = h in on_hours
        else:
            dd = (1.0 - eq / peak) if peak > 0 else 0.0
            on = dd >= dd_on
        bp = (BW.get(ph, 0.0) / BC[ph]) if (ph is not None
                                            and BC.get(ph, 0.0) > 0) else 0.0
        notl = mult * bp * xp if on else 0.0
        r = rmkt.get(h, float("nan"))
        hedge = 0.0 if (notl == 0.0 or r != r) else -notl * r
        cost = abs(notl - prev_notl) * HALF_ROUND
        cost_tot += cost
        on_n += int(notl > 0)
        prev_notl = notl
        ret = ((dP.get(h, 0.0) + hedge - cost) / den) if den > 0 else 0.0
        eq *= (1.0 + ret)
        peak = max(peak, eq)
        curve.append(eq)
        d = time.strftime("%Y-%m-%d", time.gmtime(h))
        day[d] = day.get(d, 0.0) + ret
        if eq <= 0:                               # книга обнулилась — стоп
            break
    return {"curve": curve, "day": day, "cost": cost_tot,
            "duty": on_n / len(hrs) if hrs else 0.0}


def curve_stats(res, base_day=None):
    c = np.array(res["curve"], dtype=float)
    if len(c) == 0:
        return {"hours": 0}
    dd = float(np.min(c / np.maximum.accumulate(c) - 1.0))
    days = sorted(res["day"])
    dv = np.array([res["day"][d] for d in days], dtype=float)
    out = {
        "hours": len(c),
        "final": round(float(c[-1] - 1.0), 4),
        "max_dd": round(dd, 4),
        "day_median": round(float(np.median(dv)), 5),
        "day_worst": round(float(np.min(dv)), 4),
        "day_green": round(float(np.mean(dv > 0)), 3),
        "days": len(days),
        "duty": round(res["duty"], 3),
        "cost": round(res["cost"], 3),
    }
    if base_day is not None:
        common = sorted(set(days) & set(base_day))
        if common:
            d = np.array([res["day"][k] - base_day[k] for k in common])
            out["vs_base_day_median"] = round(float(np.median(d)), 5)
            out["vs_base_day_better"] = round(float(np.mean(d > 0)), 3)
    return out


def run(limit=None, src=None, log=print):
    t0 = time.time()
    legs = TNT.legs_from_sheets([D2.SHEETS], log=log)
    get = src.bars if src else (lambda s, a, b: SW.read_bars(ROOT_B1, s, a, b))
    hrs, dP, X, BW, BC, cov, sum_pnl, n, skipped = book_hours(
        legs, get, log, limit=limit)
    log(f"часов книги {len(hrs)}, позиций {n}, пропущено {skipped}")
    out = {"positions": n, "skipped": skipped, "hours": len(hrs),
           "beta_coverage": round(cov, 4),
           "secs": round(time.time() - t0, 1),
           "grid": {"dd": GRID_DD, "mult": GRID_MULT},
           "params": {"SURVIVE_MULT": D2.SURVIVE_MULT,
                      "FLOOR_FRAC": D2.FLOOR_FRAC,
                      "ROUND_COST_BP": TR.ROUND_COST_BP,
                      "NULL_SEEDS": NULL_SEEDS, "NULL_SEED0": NULL_SEED0},
           "cells": {}, "nulls": {}}
    if not hrs:
        return out
    # встроенная сверка: почасовая книга обязана сойтись с суммой исходов
    got = sum(dP.values())
    out["crosscheck"] = {"sum_positions": round(sum_pnl, 4),
                         "sum_hourly": round(got, 4),
                         "residual": round(got - sum_pnl, 6)}
    rmkt = market_returns(hrs, get, log)
    out["market_hours"] = int(sum(1 for h in hrs if rmkt.get(h, float("nan"))
                                  == rmkt.get(h, float("nan"))))
    base = simulate_hedge(hrs, dP, X, BW, BC, rmkt, 1e9, 0.0)   # без хеджа
    out["base"] = curve_stats(base)
    # Часы, в которые хедж ВООБЩЕ можно рассчитать: у прошлого часа есть и
    # экспозиция, и бета. Жребий обязан тянуться только из них — иначе нуль
    # получает меньшую фактическую долю включённых часов, и сравниваются
    # разные экспозиции, а не разные моменты.
    elig = [h for i, h in enumerate(hrs)
            if i and X.get(hrs[i - 1], 0.0) > 0 and BC.get(hrs[i - 1], 0.0) > 0]
    out["eligible_hours"] = len(elig)
    rng = np.random.default_rng(NULL_SEED0)
    for dd_on in GRID_DD:
        for mult in GRID_MULT:
            key = f"{dd_on}|{mult}"
            res = simulate_hedge(hrs, dP, X, BW, BC, rmkt, dd_on, mult)
            out["cells"][key] = curve_stats(res, base["day"])
            # нуль случайного момента: та же доля часов, выбранных наугад
            # хедж не включался ни разу — нуля не существует: сравнивать
            # «без хеджа» со «случайным хеджем на час» значило бы сравнивать
            # разные экспозиции, а не разные моменты
            k = min(len(elig), int(round(res["duty"] * len(hrs))))
            if k <= 0:
                out["nulls"][key] = {"never_on": True, "seeds": 0,
                                     "cell_duty": round(res["duty"], 3)}
                continue
            fin, ddw, dut = [], [], []
            for _s in range(NULL_SEEDS):
                pick = set(np.array(elig)[rng.choice(len(elig), size=k,
                                                     replace=False)].tolist())
                nres = simulate_hedge(hrs, dP, X, BW, BC, rmkt, 0.0, mult,
                                      on_hours=pick)
                st = curve_stats(nres)
                fin.append(st["final"])
                ddw.append(st["max_dd"])
                dut.append(st["duty"])
            out["nulls"][key] = {
                "final_mean": round(float(np.mean(fin)), 4),
                "final_p95": round(float(np.percentile(fin, 95)), 4),
                "dd_mean": round(float(np.mean(ddw)), 4),
                "dd_best": round(float(np.max(ddw)), 4),
                "duty_mean": round(float(np.mean(dut)), 3),
                "cell_duty": round(res["duty"], 3),
                "seeds": NULL_SEEDS,
            }
    out["secs"] = round(time.time() - t0, 1)
    return out


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def report(s):
    P = ["# D4 — хедж на уровне КНИГИ, а не позиции (спека 14)\n"]
    P.append("Диагностика, не вердикт: сетка объявлена в коде до прогона, "
             "печатаются все ячейки. Просьба владельца — последняя "
             "непроверенная форма хеджа.\n")
    P.append("**Чем это НЕ является уже закрытым замером (б).** Там каждая "
             "позиция хеджировалась отдельно, всегда и по итоговому нотионалу "
             "лестницы. Здесь хеджируется суммарная экспозиция открытых "
             "позиций, и только пока книга в просадке. И главное: хвост "
             "ПОЗИЦИИ идиосинкратичен (замер (б) это показал — альт валится "
             "сам, рынок часто растёт), а просадка КНИГИ случается, когда "
             "просело много позиций разом, то есть она кандидат в рыночное "
             "событие. Это разные утверждения.\n")
    if not s.get("hours"):
        P.append("**Часов книги ноль** — журнала листов нет или баров нет.")
        return "\n".join(P) + "\n"
    P.append(f"Позиций {s['positions']}, часов книги {s['hours']}, бета "
             f"известна у {s['beta_coverage']*100:.1f} % экспозиции, "
             f"рыночная нога есть в {s.get('market_hours', 0)} часах, прогон "
             f"{s['secs']} с.\n")
    cc = s.get("crosscheck") or {}
    if cc:
        ok = abs(cc.get("residual", 1.0)) < 1e-6
        P.append(("> Встроенная сверка: сумма почасовых изменений книги "
                  f"{cc['sum_hourly']:+.4f} против суммы исходов позиций "
                  f"{cc['sum_positions']:+.4f}, расхождение "
                  f"{cc['residual']:+.6f}"
                  + (" — сходится.\n" if ok else
                     " — **НЕ сходится, свод описывает другую книгу**.\n")))
    b = s["base"]
    P.append("## Книга без хеджа\n")
    P.append(f"Итог {_pct(b['final'])}, просадка **{_pct(b['max_dd'])}**, "
             f"медиана дня {_pct(b['day_median'], 3)}, худший день "
             f"{_pct(b['day_worst'])}, зелёных дней "
             f"{b['day_green']*100:.1f} % из {b['days']}.\n")
    P.append("Единица — доходность на ЗАНЯТЫЙ капитал: каждый час деньги "
             "книги делятся на её экспозицию того часа, и получившиеся "
             "доходности складываются в счёт. Это настоящая просадка счёта, "
             "а не сумма долей по позициям (единица, которой в D1–D3 нельзя "
             "было выносить вердикт).\n")
    P.append("## Хедж по просадке книги\n")
    P.append("Строка — порог просадки, при котором хедж включается (0 % — "
             "всегда включён, сальдированный аналог руки SH), колонка — доля "
             "хеджируемой беты. Решение часа принимается по экспозиции, бете "
             "и просадке, известным к концу ПРОШЛОГО часа; просадка меряется "
             "по собственной кривой хеджированной книги.\n")
    P.append("| порог | доля β | вкл. часов | итог | просадка | худший день | "
             "медиана дня | Δ к базе за день | лучше базы дней | издержки |")
    P.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for dd_on in s["grid"]["dd"]:
        for mult in s["grid"]["mult"]:
            c = s["cells"].get(f"{dd_on}|{mult}")
            if not c or not c.get("hours"):
                P.append(f"| {dd_on*100:.0f} % | {mult} | — | — | — | — | — | "
                         "— | — | — |")
                continue
            P.append(
                f"| {dd_on*100:.0f} % | {mult} | {c['duty']*100:.0f} % | "
                f"{_pct(c['final'])} | {_pct(c['max_dd'])} | "
                f"{_pct(c['day_worst'])} | {_pct(c['day_median'], 3)} | "
                f"{_pct(c.get('vs_base_day_median'), 3)} | "
                f"{(c.get('vs_base_day_better') or 0)*100:.0f} % | "
                f"{c['cost']:.3f} |")
    P.append("")
    P.append("## Нуль случайного момента\n")
    P.append("Тот же хедж, включённый на столько же часов, но выбранных "
             "НАУГАД (десять зёрен, зерно числом). Без него «хедж помог» "
             "неотличимо от «мы случайно были в шорте на падении» — ровно то "
             "место, где нуль 4 был обязателен в S1. Хедж что-то умеет, "
             "только если он лучше своего случайного двойника.\n")
    P.append("| порог | доля β | итог хеджа | итог нуля (среднее / 95-й) | "
             "просадка хеджа | просадка нуля (среднее / лучшая) | бьёт нуль |")
    P.append("|---|--:|--:|--:|--:|--:|:--:|")
    for dd_on in s["grid"]["dd"]:
        for mult in s["grid"]["mult"]:
            k = f"{dd_on}|{mult}"
            c, z = s["cells"].get(k), s["nulls"].get(k)
            if not c or not z or not c.get("hours"):
                P.append(f"| {dd_on*100:.0f} % | {mult} | — | — | — | — | — |")
                continue
            if z.get("never_on"):
                P.append(f"| {dd_on*100:.0f} % | {mult} | {_pct(c['final'])} "
                         f"| хедж не включался | {_pct(c['max_dd'])} | — | "
                         "— |")
                continue
            beats = (c["final"] > z["final_p95"]
                     and c["max_dd"] > z["dd_best"])
            P.append(
                f"| {dd_on*100:.0f} % | {mult} | {_pct(c['final'])} | "
                f"{_pct(z['final_mean'])} / {_pct(z['final_p95'])} | "
                f"{_pct(c['max_dd'])} | {_pct(z['dd_mean'])} / "
                f"{_pct(z['dd_best'])} | {'✓' if beats else '—'} |")
    P.append("")
    P.append("«Бьёт нуль» означает одновременно: итог выше 95-го процентиля "
             "случайных И просадка мельче лучшей из случайных. Одного из двух "
             "мало: хедж, который просто сокращает экспозицию, улучшает "
             "просадку у ЛЮБОГО момента включения.\n")
    P.append("**Оговорки.** Рыночная нога — BTC как прокси волны, а бета "
             "измерена к волне универсума (M1): приближение, названное ещё в "
             "D2. Издержки хеджа — половина круга на каждое изменение "
             "нотионала, то есть полный круг за «включил и выключил»; "
             "проскальзывание не моделируется. Веса модели видели эти часы, "
             "как и во всех прогонах D-серии. Книга — базовая ячейка (забор "
             "2.0, пол 0.10), то есть та, которой книга торгует сегодня.")
    return "\n".join(P) + "\n"


def publish(name):
    subprocess.run(["tools/publish.sh", f"job: {name}"],
                   cwd=os.path.dirname(RESEARCH), check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    s = run(a.limit)
    tag = "smoke" if a.limit else "1m"
    with open(os.path.join(OUT, f"D4-bookhedge-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    rep = report(s)
    with open(os.path.join(OUT, f"D4-bookhedge-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    if not a.no_publish:
        publish(f"d4-bookhedge-{tag}")


if __name__ == "__main__":
    main()
