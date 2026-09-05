#!/usr/bin/env python3
"""
D5 (спека 14) — ЛИНЕЙКА забора: глубины лестницы против движений монеты.

Вопрос владельца после D3/D4: забор §5 антиселективен — он выдал хвосту
медианное плечо 7.34× против 3.02× по книге, то есть больше всего рычага
досталось самым бешеным именам. Причина в самой линейке, а не в пороге:
`max_leverage` ставит ликвидацию на `mult · d_max` ниже входа, где `d_max`
— глубина лестницы В ПРОЦЕНТАХ ЦЕНЫ. Процент цены у разных монет означает
разное время: спокойная проходит 6 % за неделю, разогнанная за час. Забор
этой разницы не видит вовсе.

Замер меняет ЛИНЕЙКУ, а не порог: запас меряется в СУТОЧНЫХ σ самой
монеты, известных в момент входа (то же окно `BACK_H`, что уже считает
D3.window_stats). Одно число на всех: «ликвидация не ближе N суточных σ».

Сетка объявлена ДО прогона и не меняется после чтения результата:

    ("depth", 2.0)  — нынешнее правило, якорь и предмет сверки
    ("depth", 3.0)  — «просто меньше плеча всем» (контроль: это НЕ линейка)
    ("sigma", N) при N = 3, 4, 6, 8, 12 суточных σ

Пол капитуляции фиксирован (D2.FLOOR_FRAC): его ось уже измерена в D3, и
второй раз платить за неё поправкой незачем.

Два инварианта линейки, оба под тестами и оба — уроки проекта:

* **σ нет или σ = 0 → плеча нет (1×).** Замороженный ряд имеет нулевую σ,
  и σ-правило выдало бы ему потолок 25× (ловушка S1 в новом костюме).
  Неизмеримое не есть безопасное.
* **Запас никогда не мельче самой лестницы** (`max(N·σ, d_max)`): иначе
  ликвидация встала бы ВЫШЕ последнего планового долива, то есть позицию
  закрыли бы раньше, чем лестница успела набраться. Это требование
  конструкции, а не линейки, и оно печатается числом — доля позиций, где
  связала лестница, а не σ.

Считается в ДВУХ единицах разом, иначе вердикт не вынести:

1. по позициям (единица D1–D3: доля капитала позиции) — медиана, доля
   зелёных, худшая, укус, доля ликвидаций;
2. по КНИГЕ (единица D4: доходность на занятый капитал) — итог, просадка
   счёта, медиана дня. Именно её владелец назвал главным критерием.

Главная новая колонка — ПЕРЕРАСПРЕДЕЛЕНИЕ: медианное плечо в верхнем и
нижнем дециле σ. Если правило работает, у бешеных плечо падает, у
спокойных растёт, и это видно числом, а не рассуждением.

Рядом — ВРЕМЯ В ПОЗИЦИИ (просьба владельца): среднее, минимум, максимум,
медиана и разбивка по причине выхода. Оно не украшение таблицы: линейка
меняет плечо, плечо двигает цену ликвидации и пол капитуляции, а те
решают, ДОЖИВЁТ ли позиция до тейка или её вынесет раньше. Максимум
упирается в предел удержания (`HOLD_H`), минимум может быть нулевым —
это значит, что цель задета внутри той же минуты, в которую вошли.

Встроенная сверка: ячейка ("depth", 2.0) обязана воспроизвести
опубликованные D3 (`2.0|0.1`) и D4 (базовая книга). Разошлась — прогон
описывает другую книгу, а обе таблицы выглядят исправными.

Сверка делится надвое, потому что ЖУРНАЛ ЛИСТОВ РАСТЁТ КАЖДЫЙ ЧАС.
Медианы и доли на несколько дописанных строк нечувствительны и сверяются
всегда — расхождение там есть настоящий дефект. Среднее и накопленные
величины книги (итог, просадка) от длины журнала зависят по построению и
сверяются, только если позиций и часов ровно столько же; иначе они
печатаются справкой, а рост журнала называется числом. Иначе «якорь не
сошёлся» означало бы просто «сегодня позиций больше», и настоящий дефект
утонул бы в этой ложной тревоге.

Оговорки (в силе с D2): веса видели эти часы (оценка сверху); издержки
круга в pnl позиции не сняты; σ меряется по минутным барам 24 ч до входа
и переводится в сутки множителем √1440 — это оценка, а не реализованная
суточная волатильность; хвост слипается во времени (канарейка D3), и
улучшение может оказаться свойством периода.

Запуск (VPS — журнал листов и бары только там):

    setsid nohup .venv/bin/python research/dca_ladder/run_d5.py \\
        > research/dca_ladder/out/run_d5.log 2>&1 &

Смоук: `--limit 400`. Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import math
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
import tournament as TNT                                      # noqa: E402
import sweep as SW                                            # noqa: E402

ROOT_B1 = D4.ROOT_B1
HOUR = 3600

# --- объявленная сетка (до прогона) --------------------------------------
GRID_RULE = [("depth", 2.0), ("depth", 3.0),
             ("sigma", 3.0), ("sigma", 4.0), ("sigma", 6.0),
             ("sigma", 8.0), ("sigma", 12.0)]
ANCHOR = ("depth", 2.0)            # якорь сверки с D3/D4
MIN_PER_DAY = 1440                 # σ минуты → σ суток множителем √1440
DECILE = 0.10                      # верхний и нижний дециль σ

# Опубликованные числа якоря (D3 `2.0|0.1`, D4 базовая книга) и длина
# журнала, при которой они посчитаны. ЖУРНАЛ ЛИСТОВ РАСТЁТ КАЖДЫЙ ЧАС,
# поэтому сверка делится надвое, иначе «якорь не сошёлся» будет означать
# просто «сегодня позиций больше», и настоящий дефект утонет в этой
# ложной тревоге.
#
# УСТОЙЧИВЫЕ — медианы и доли: несколько дописанных строк их не двигают,
# и расхождение здесь есть настоящий дефект.
ANCHOR_ROBUST = {"median": 0.0191, "liq_freq": 0.00058, "median_lev": 3.03,
                 "frac_1x": 0.233}
# ОТ ДЛИНЫ ЗАВИСЯТ — среднее (одна хвостовая позиция его двигает) и всё,
# что накоплено книгой по часам. Сверяются, только если журнал ровно тот
# же; иначе печатаются рядом как справка, а не как расхождение.
ANCHOR_LEN = {"mean": 0.0288, "final": 0.0732, "max_dd": -0.1911}
ANCHOR_N = {"D3_positions": 8670, "D4_positions": 8673, "D4_hours": 634}
TOL = {"median": 5e-4, "mean": 5e-4, "liq_freq": 5e-5, "median_lev": 0.02,
       "frac_1x": 0.005, "final": 5e-4, "max_dd": 5e-4}


def sigma_day(sigma_bp):
    """Суточная σ долей цены из минутной σ в б.п. Нет меры — None.

    Ноль тоже None: замороженная котировка не есть спокойная монета — у
    неё σ = 0, и правило «запас в N·σ» выдало бы ей потолок плеча.
    """
    if sigma_bp is None or sigma_bp != sigma_bp or sigma_bp <= 0:
        return None
    return sigma_bp / 1e4 * math.sqrt(MIN_PER_DAY)


def fence_leverage(rule, param, entry, rungs_full, look, sigma_bp,
                   weights=None, side="long", lev_look=None):
    """Плечо по объявленной линейке. Возвращает (плечо, рунги, кто связал).

    `depth` — нынешнее правило: запас `param · d_max` (глубины лестницы).
    `sigma` — новая линейка: запас `param · σ_сут`, но не мельче самой
    лестницы. Обе идут через ОДНУ `L.max_leverage`: второй копии вывода
    плеча не заводится, меняется ровно требуемый запас.

    `weights` — веса лестницы, если они не `D2.WEIGHTS`. Забор считает
    цену ликвидации ПОЛНОСТЬЮ заполненной лестницы, поэтому веса обязаны
    быть теми же, какими её потом торгуют: посчитав плечо по одним весам
    и заполнив другими, мы получили бы запас, которого нет. Умолчание
    даёт прежний счёт бит в бит.

    `side` — сторона позиции: у шорта лестница уходит ВВЕРХ, ликвидация
    стоит выше входа, и требуемый запас меряется тем же модулем. Правило
    одно, зеркалится только знак; лонг не тронут.

    `lev_look` — предел плеча тира ПЛОЩАДКИ (`L.lev_cap_for_notional`).
    Без него забор ограничен только неравенством безопасности, и на узкой
    лестнице (у шорта она узкая почти всегда) упирается в наш потолок 25×
    даже там, где биржа даёт 5×. Умолчание `None` — прежний счёт бит в
    бит, поэтому у старых прогонов числа не двигаются.
    """
    if len(rungs_full) < 2:                    # нет резерва — нет рычага (D2)
        return 1.0, [entry], "нет лестницы"
    d_max = abs(entry - rungs_full[-1]) / entry
    if d_max <= 0:
        return 1.0, [entry], "нет лестницы"
    if rule == "depth":
        mult, binder = float(param), "лестница"
    elif rule == "sigma":
        sd = sigma_day(sigma_bp)
        if sd is None:                         # меры нет — рычага нет
            return 1.0, [entry], "нет σ"
        buf = float(param) * sd
        binder = "σ" if buf > d_max else "лестница"
        mult = max(buf, d_max) / d_max
    else:
        raise ValueError(f"неизвестная линейка: {rule}")
    w = (list(weights) if weights is not None
         else D2.WEIGHTS[:len(rungs_full)])
    lev = L.max_leverage(rungs_full, w, 1.0, entry, d_max, look, mult,
                         side=side, lev_lookup=lev_look)
    if lev <= 0:                               # забор отказал лестнице (D2)
        return 1.0, [entry], "забор отказал"
    return lev, rungs_full, binder


def leg_cells(g, bars, ts, look):
    """Один выбор во всех ячейках сетки, с почасовой отметкой книги.

    Гейты и геометрия — общие с D2 (`split_window`/`build_levels`/
    `structural_rungs`), чтобы состав позиций совпадал с D2–D4 бит в бит.
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
    sigma_bp, _rng, _turn = D3.window_stats(win, now_i)

    cells = {}
    for rule, param in GRID_RULE:
        lev, rungs, binder = fence_leverage(rule, param, entry, rungs_full,
                                            look, sigma_bp)
        w = D2.WEIGHTS[:len(rungs)]
        r = L.simulate_dca(hold, rungs, w, 1.0, lev, look(1.0 * lev),
                           take_px=take_px, floor_frac=D2.FLOOR_FRAC,
                           track=True)
        r["lev"] = lev
        r["binder"] = binder
        # время в позиции: от бара входа до бара выхода, часов
        r["hold_h"] = max(0.0, (float(r["exit_ts"]) - float(hold[0][0]))
                          / HOUR)
        cells[(rule, param)] = r
    return cells, sigma_bp


def _hold_stats(hold, by_exit):
    """Время в позиции: среднее, медиана, край и разбивка по выходу.

    Минимум ноль законен — цель задета внутри минуты входа; это НЕ пропуск
    и прочерком не подменяется. Максимум обязан упираться в предел
    удержания, и если он заметно больше, замер описывает не ту книгу.
    """
    if not hold:
        return None
    h = np.array(hold, dtype=float)
    out = {"mean_h": round(float(np.mean(h)), 2),
           "median_h": round(float(np.median(h)), 2),
           "min_h": round(float(np.min(h)), 3),
           "max_h": round(float(np.max(h)), 2),
           "by_exit": {}}
    for k, v in by_exit.items():
        if v:
            a = np.array(v, dtype=float)
            out["by_exit"][k] = {"n": len(a),
                                 "mean_h": round(float(np.mean(a)), 2),
                                 "median_h": round(float(np.median(a)), 2)}
    return out


def _exposure(hrs, X, N, sum_pnl, final):
    """Чем книга занята: гросс-нотионал и сколько позиций открыто разом.

    Без этих чисел «итог книги» прочесть нельзя. Знаменатель кривой —
    ГРОСС-НОТИОНАЛ (`ret = ΔPnL / X`), то есть итог есть доходность на
    гросс, а не на депозит. Перевод в депозит — тождество:

        доходность депозита = доходность гросса × (гросс / депозит)

    и второй множитель есть решение об ограде (сколько позиций разом и
    какой потолок на имя), а не свойство рынка. Печатаем оба, иначе
    читатель подставит своё.
    """
    if not hrs:
        return None
    x = np.array([X.get(h, 0.0) for h in hrs], dtype=float)
    nn = np.array([N.get(h, 0) for h in hrs], dtype=float)
    mx, mn = float(np.mean(x)), float(np.mean(nn))
    return {
        "gross_mean": round(mx, 1), "gross_median": round(float(np.median(x)), 1),
        "gross_max": round(float(np.max(x)), 1),
        "open_mean": round(mn, 1), "open_median": round(float(np.median(nn)), 1),
        "open_max": int(np.max(nn)),
        "notional_per_pos": round(mx / mn, 3) if mn > 0 else None,
        "sum_pnl": round(sum_pnl, 2),
        # сверка тождества: сумма исходов, делённая на средний гросс,
        # обязана быть того же порядка, что итог книги. Разошлось на
        # порядок — знаменатель понят неверно, и вердикт по деньгам не
        # выносится
        "sum_over_gross": round(sum_pnl / mx, 4) if mx > 0 else None,
        "final": final,
    }


def _dec_stats(lev, liq, mask):
    """Медианное плечо и доля ликвидаций внутри среза σ."""
    if not mask.any():
        return None, None
    return (round(float(np.median(np.array(lev)[mask])), 2),
            round(float(np.mean(np.array(liq)[mask])), 5))


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

    keys = list(GRID_RULE)
    acc = {k: {"pnl": [], "liq": [], "lev": [], "depth": [], "exits": {},
               "binder": {}, "dP": {}, "X": {}, "day": {},
               "hold": [], "hold_by": {}, "N": {}} for k in keys}
    sig, n, skipped = [], 0, 0
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
            r = leg_cells(g, bars, ts, look)
            if r is None:
                skipped += 1
                continue
            cells, sigma_bp = r
            sig.append(sigma_bp)
            day = time.strftime("%Y-%m-%d", time.gmtime(g["at"]))
            for k in keys:
                c, a = cells[k], acc[k]
                a["pnl"].append(c["pnl_frac"])
                a["liq"].append(int(c["exit"] == "ликвидация"))
                a["lev"].append(c["lev"])
                a["depth"].append(c["depth"])
                a["exits"][c["exit"]] = a["exits"].get(c["exit"], 0) + 1
                a["hold"].append(c["hold_h"])
                a["hold_by"].setdefault(c["exit"], []).append(c["hold_h"])
                a["binder"][c["binder"]] = a["binder"].get(c["binder"], 0) + 1
                a["day"][day] = a["day"].get(day, 0.0) + c["pnl_frac"]
                prev = 0.0
                for (hr, cash, pnl) in c["track"]:
                    a["dP"][hr] = a["dP"].get(hr, 0.0) + (pnl - prev)
                    a["X"][hr] = a["X"].get(hr, 0.0) + cash
                    a["N"][hr] = a["N"].get(hr, 0) + 1
                    prev = pnl
            n += 1

    out = {"positions": n, "skipped": skipped,
           "grid": [[r, p] for r, p in GRID_RULE],
           "params": {"FLOOR_FRAC": D2.FLOOR_FRAC, "BACK_H": D2.BACK_H,
                      "HOLD_H": D2.HOLD_H, "MIN_PER_DAY": MIN_PER_DAY,
                      "DECILE": DECILE},
           "cells": {}, "anchor": {}, "secs": 0.0}
    if not n:
        out["secs"] = round(time.time() - t0, 1)
        return out

    s = np.array(sig, dtype=float)
    ok = np.isfinite(s) & (s > 0)
    out["sigma_measured"] = int(ok.sum())
    if ok.sum() >= 20:
        lo_c = float(np.quantile(s[ok], DECILE))
        hi_c = float(np.quantile(s[ok], 1.0 - DECILE))
        calm = ok & (s <= lo_c)
        wild = ok & (s >= hi_c)
        out["sigma_deciles"] = {
            "calm_max_bp": round(lo_c, 2), "wild_min_bp": round(hi_c, 2),
            "calm_n": int(calm.sum()), "wild_n": int(wild.sum()),
            "calm_day_pct": round(sigma_day(float(np.median(s[calm]))) * 100,
                                  2),
            "wild_day_pct": round(sigma_day(float(np.median(s[wild]))) * 100,
                                  2)}
    else:
        calm = wild = np.zeros(len(s), dtype=bool)
        out["sigma_deciles"] = None

    for k in keys:
        a = acc[k]
        st = D3.cell_stats(a["pnl"], sum(a["liq"]), a["exits"], a["depth"],
                           a["lev"], a["day"])
        hrs = sorted(a["X"])
        book = D4.simulate_hedge(hrs, a["dP"], a["X"], {}, {}, {}, 1e9, 0.0)
        bs = D4.curve_stats(book)
        st["book"] = {kk: bs.get(kk) for kk in
                      ("final", "max_dd", "day_median", "day_worst",
                       "day_green", "days", "hours")}
        lw, liqw = _dec_stats(a["lev"], a["liq"], wild)
        lc, liqc = _dec_stats(a["lev"], a["liq"], calm)
        st["lev_wild"], st["liq_wild"] = lw, liqw
        st["lev_calm"], st["liq_calm"] = lc, liqc
        st["hold"] = _hold_stats(a["hold"], a["hold_by"])
        st["exposure"] = _exposure(hrs, a["X"], a["N"], sum(a["pnl"]),
                                   bs.get("final"))
        tot = sum(a["binder"].values()) or 1
        st["binder"] = {b: round(c / tot, 3) for b, c in a["binder"].items()}
        out["cells"][f"{k[0]}|{k[1]}"] = st

    # Встроенная сверка якоря с опубликованными D3 и D4. Журнал листов
    # растёт каждый час, поэтому «столько же позиций» — не данность, и
    # проверка обязана отличать выросший журнал от разошедшегося счёта.
    a = out["cells"][f"{ANCHOR[0]}|{ANCHOR[1]}"]
    hours = (a.get("book") or {}).get("hours")
    same_len = (n == ANCHOR_N["D4_positions"]
                and hours == ANCHOR_N["D4_hours"])
    bad, drift = [], []
    for f, want in ANCHOR_ROBUST.items():
        got = a.get(f)
        if got is None or abs(got - want) > TOL[f]:
            bad.append({"поле": f, "было": want, "стало": got})
    for f, want in ANCHOR_LEN.items():
        got = a.get(f) if f in a else (a.get("book") or {}).get(f)
        off = got is None or abs(got - want) > TOL[f]
        if off and same_len:
            bad.append({"поле": f, "было": want, "стало": got})
        elif off:
            drift.append({"поле": f, "было": want, "стало": got})
    out["anchor"] = {
        "cell": f"{ANCHOR[0]}|{ANCHOR[1]}",
        "mismatch": len(bad), "fields": bad,
        "same_len": bool(same_len), "drift": drift,
        "positions": n, "positions_d4": ANCHOR_N["D4_positions"],
        "hours": hours, "hours_d4": ANCHOR_N["D4_hours"],
        "robust_checked": len(ANCHOR_ROBUST),
    }
    out["secs"] = round(time.time() - t0, 1)
    return out


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def _lvl(x, d=2):
    return "—" if x is None else f"{x * 100:.{d}f} %"


def _mins(h):
    """Мелкое время читается в минутах: «0.02 ч» ничего не говорит."""
    if h is None:
        return "—"
    return f"{h * 60:.0f} мин" if h < 1.0 else f"{h:.1f} ч"


def report(s):
    n = s.get("positions", 0)
    L1 = [
        "# D5 — линейка забора: глубины лестницы против движений монеты",
        "",
        "Диагностика, не вердикт: сетка объявлена в коде до прогона, "
        "печатаются все ячейки. Вопрос владельца — забор §5 антиселективен "
        "(D3: медианное плечо хвоста 7.34× против 3.02× по книге).",
        "",
        "**Что меняется.** Не порог, а ЛИНЕЙКА. Нынешний забор требует "
        "запас `mult · глубина лестницы` — в процентах цены. Процент цены "
        "у разных монет означает разное время: спокойная проходит 6 % за "
        "неделю, разогнанная за час. Новая линейка требует запас "
        "`N · суточных σ самой монеты`, известных в момент входа. Одно "
        "число на всех — различие делают данные монеты, а не список имён.",
        "",
        f"Позиций {n}, пропущено {s.get('skipped', 0)}, "
        f"σ измерима у {s.get('sigma_measured', 0)}, "
        f"прогон {s.get('secs', 0)} с.",
        "",
    ]
    a = s.get("anchor") or {}
    if a:
        if a.get("mismatch"):
            L1 += [f"> **Сверка якоря НЕ сошлась** ({a['mismatch']} полей): "
                   f"`{json.dumps(a['fields'], ensure_ascii=False)}` — "
                   "читать таблицу нельзя, прогон описывает другую книгу.",
                   ""]
        else:
            L1 += [f"> Встроенная сверка: ячейка `{a['cell']}` воспроизвела "
                   f"опубликованные D3 (`2.0|0.1`) и D4 по "
                   f"{a.get('robust_checked')} устойчивым полям (медиана, "
                   "доля ликвидаций, медианное плечо, доля 1×) — "
                   "расхождений 0.", ""]
        if not a.get("same_len"):
            L1 += [f"> **Журнал листов вырос**: позиций "
                   f"{a.get('positions')} против {a.get('positions_d4')} у "
                   f"D4, часов книги {a.get('hours')} против "
                   f"{a.get('hours_d4')}. Журнал дописывается каждый час, "
                   "поэтому среднее и накопленные величины книги от длины "
                   "зависят и якорю не сверяются — они стоят рядом справкой: "
                   f"`{json.dumps(a.get('drift') or [], ensure_ascii=False)}`."
                   " Сверяются медианы и доли, на дописанные строки "
                   "нечувствительные.", ""]
    d = s.get("sigma_deciles")
    if d:
        L1 += [f"Дециль спокойных — σ суток около {d['calm_day_pct']} %, "
               f"дециль бешеных — около {d['wild_day_pct']} % "
               f"(по {d['calm_n']} и {d['wild_n']} позиций).", ""]

    L1 += ["## Ячейки", "",
           "| линейка | запас | плечо: медиана | у бешеных | у спокойных | "
           "ликвидаций | у бешеных | медиана позиции | итог книги | "
           "просадка книги | худший день |",
           "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for rule, param in GRID_RULE:
        c = s["cells"].get(f"{rule}|{param}")
        if not c:
            continue
        b = c.get("book") or {}
        name = ("глубины лестницы" if rule == "depth" else "суточные σ")
        buf = (f"{param:g} · d_max" if rule == "depth" else f"{param:g} · σ")
        L1.append(
            f"| {name} | {buf} | {c.get('median_lev')}× | "
            f"{c.get('lev_wild')}× | {c.get('lev_calm')}× | "
            f"{_lvl(c.get('liq_freq'), 3)} | {_lvl(c.get('liq_wild'), 3)} | "
            f"{_pct(c.get('median'))} | {_pct(b.get('final'))} | "
            f"{_pct(b.get('max_dd'))} | {_pct(b.get('day_worst'))} |")

    L1 += ["", "Первая строка — нынешнее правило книги (якорь). Вторая — "
           "«просто меньше плеча всем»: она НЕ меняет линейку и стоит здесь "
           "контролем, иначе улучшение σ-линейки нельзя отличить от общего "
           "снижения рычага.", ""]

    L1 += ["## Кто связал запас", "",
           "У σ-линейки запас не бывает мельче самой лестницы: иначе "
           "ликвидация встала бы выше последнего планового долива. Доля "
           "позиций, где связала лестница, а не σ, — мера того, работает ли "
           "правило вообще.", "",
           "| линейка | запас | что связывало |", "|---|---|---|"]
    for rule, param in GRID_RULE:
        c = s["cells"].get(f"{rule}|{param}")
        if not c:
            continue
        bd = c.get("binder") or {}
        parts = ", ".join(f"{k} {v * 100:.0f} %" for k, v in
                          sorted(bd.items(), key=lambda kv: -kv[1]))
        buf = (f"{param:g} · d_max" if rule == "depth" else f"{param:g} · σ")
        name = ("глубины лестницы" if rule == "depth" else "суточные σ")
        L1.append(f"| {name} | {buf} | {parts} |")

    L1 += ["", "## Время в позиции", "",
           "Просьба владельца. Максимум упирается в предел удержания "
           f"({D2.HOLD_H} ч) — это не рынок, а правило книги. Минимум ноль "
           "означает, что цель задета внутри той же минуты, в которую "
           "вошли: это факт записи, а не пропуск.", "",
           "| линейка | запас | среднее | медиана | минимум | максимум | "
           "по причине выхода |",
           "|---|---|--:|--:|--:|--:|---|"]
    for rule, param in GRID_RULE:
        c = s["cells"].get(f"{rule}|{param}")
        if not c:
            continue
        h = c.get("hold")
        buf = (f"{param:g} · d_max" if rule == "depth" else f"{param:g} · σ")
        name = ("глубины лестницы" if rule == "depth" else "суточные σ")
        if not h:
            L1.append(f"| {name} | {buf} | — | — | — | — | — | — | — |")
            continue
        # причины перечисляются ВСЕ, какие есть в записи: поимённый
        # список молча терял бы новую (в первом прогоне так пропали 40
        # выходов «пол» — 8636 показанных из 8676)
        be = h["by_exit"]
        by = ", ".join(f"{k} {v['mean_h']:.1f} ч ({v['n']})" for k, v in
                       sorted(be.items(), key=lambda kv: -kv[1]["n"]))
        shown = sum(v["n"] for v in be.values())
        if shown != c["n"]:
            by += f" — ПОКАЗАНО {shown} из {c['n']}"
        L1.append(
            f"| {name} | {buf} | {h['mean_h']:.1f} ч | "
            f"{h['median_h']:.1f} ч | {_mins(h['min_h'])} | "
            f"{h['max_h']:.1f} ч | {by} |")

    a0 = s["cells"].get(f"{ANCHOR[0]}|{ANCHOR[1]}") or {}
    ex = a0.get("exposure")
    if ex:
        dep = ex["open_max"]          # депозит под пик одновременных позиций
        idle = 1.0 - ex["open_median"] / dep if dep else None
        swing = (ex["gross_max"] / ex["gross_median"]
                 if ex.get("gross_median") else None)
        L1 += ["", "## Сколько это в процентах к депозиту", "",
               "Итог книги выше — доходность на ВЛОЖЕННЫЙ доллар: кривая "
               "считается как `ΔPnL / гросс`, то есть описывает фонд, у "
               "которого капитал всегда равен тому, что сейчас в позициях. "
               "Доходность на ДЕПОЗИТ — другая величина, и разводит их "
               "одно число: гросс книги гуляет "
               + (f"в {swing:.0f} раз " if swing else "")
               + f"(медиана {ex['gross_median']}, максимум "
               f"{ex['gross_max']} капиталов позиции).", "",
               f"Открытыми книга держит в среднем **{ex['open_mean']} "
               f"позиций**, медиана {ex['open_median']}, максимум "
               f"**{ex['open_max']}**. Реплей кассу НЕ нормирует: каждый "
               "прошедший гейт выбор получает полный капитал, сколько бы "
               "их ни было открыто. Значит депозит, при котором книга "
               f"исполнима целиком, равен пику — {dep} капиталов позиции, "
               + (f"и тогда он простаивает **{idle * 100:.0f} % времени** "
                  f"(медианная загрузка {ex['open_median'] / dep * 100:.1f} "
                  "%)." if idle is not None else "."), "",
               "| нормировка | что это | доход за период | просадка |",
               "|---|---|--:|--:|"]
        for rule, param in GRID_RULE:
            c = s["cells"].get(f"{rule}|{param}")
            if not c:
                continue
            e, b = c.get("exposure") or {}, c.get("book") or {}
            name = ("глубины лестницы" if rule == "depth" else "суточные σ")
            buf = (f"{param:g}·d_max" if rule == "depth" else f"{param:g}·σ")
            L1.append(f"| **{name} {buf}** | на вложенный доллар | "
                      f"{_pct(b.get('final'))} | {_pct(b.get('max_dd'))} |")
            if e.get("sum_pnl") is not None and dep:
                L1.append(f"| | на депозит под пик ({dep}) | "
                          f"{_pct(e['sum_pnl'] / dep)} | "
                          f"{_pct((c.get('curve_dd') or 0.0) / dep)} |")
        L1 += ["", "**Две строки у каждой линейки расходятся, и путать их "
               "нельзя.** «На вложенный доллар» отвечает на вопрос «как "
               "ведут себя эти позиции»; «на депозит» — на вопрос «что "
               "будет со счётом». Просадка у них различается на порядок по "
               "той же причине, по которой различается доход: депозит под "
               "пик почти всегда простаивает, и любая величина, поделённая "
               "на него, мельчает.", "",
               "**Чего эта таблица НЕ говорит.** Ни одна из двух строк не "
               "есть результат торгуемой книги. Реплей не нормирует кассу "
               "вовсе, а нынешняя ограда допускает шесть позиций по 10 % "
               "капитала — то есть настоящая книга взяла бы малое "
               "подмножество этих выборов, и её доход на депозит надо "
               "мерить, а не выводить отсюда: узкая книга — другая книга. "
               "Плюс период один и режим рынка один.", ""]

    L1 += ["", "## Форма и хвост", "",
           "| линейка | запас | зелёных | худшая позиция | укус | "
           "медиана дня книги | зелёных дней |", "|---|---|--:|--:|--:|--:|--:|"]
    for rule, param in GRID_RULE:
        c = s["cells"].get(f"{rule}|{param}")
        if not c:
            continue
        b = c.get("book") or {}
        buf = (f"{param:g} · d_max" if rule == "depth" else f"{param:g} · σ")
        name = ("глубины лестницы" if rule == "depth" else "суточные σ")
        L1.append(
            f"| {name} | {buf} | {_lvl(c.get('green'), 1)} | "
            f"{_pct(c.get('worst'), 1)} | {c.get('bite')} | "
            f"{_pct(b.get('day_median'), 3)} | "
            f"{_lvl(b.get('day_green'), 1)} |")

    L1 += ["", "**Оговорки.** σ считается по минутным барам 24 ч до входа и "
           "переводится в суточную множителем √1440 — оценка, а не "
           "реализованная суточная волатильность. Издержки круга в медиане "
           "позиции не сняты (брутто), в книге — тоже. Веса модели видели "
           "эти часы. Хвост слипается во времени (канарейка D3: час входа "
           "разделял не хуже настоящих признаков), поэтому улучшение может "
           "оказаться свойством периода, а не правила — судить придётся "
           "накоплением записи.", ""]
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
    base = os.path.join(OUT, f"D5-ruler-{tag}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D5: линейка забора ({tag})")


if __name__ == "__main__":
    main()
