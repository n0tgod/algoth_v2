#!/usr/bin/env python3
"""
D2 (спека 14) — DCA-стратегия НА ВЫБОРАХ МОДЕЛИ, а не «где попало».

D1 открывал лестницу на каждом имени каждые 20 суток и держал по
таймеру — слепое усреднение по универсуму. Владелец поправил: решение
создавать DCA-книги уже есть, найти надо ПОДХОД — когда и где открывать,
когда и где закрывать. Его выбор (2026-09-03):

- **вход = сигнал обученной модели** (первый рунг открывает ситуационная
  книга; DCA не изобретает вход, а управляет доливами и выходом ПОВЕРХ
  выбора модели);
- **доливы = структурные уровни** ниже входа (полки объёма, круглые,
  экстремумы суток — T4), с запасом, не дважды на одном (§R1);
- **выход = цель + капитуляция §6** (тейк на уровне mfe модели плюс пол
  капитуляции: лестница вычерпана и цена подошла к ликвидации → режем в
  минус по доступной цене).

Что меряется: на РЕАЛЬНЫХ выборах модели (журнал листов сечения) —
помогает ли усреднение на структурных уровнях против того, как книга
торгует сейчас (один вход). ПАРНО по выборам, три руки:

- **B (книга):** одиночный вход 1×, стоп (исполняемый квантиль) + тейк
  (mfe) — как книга торгует сейчас.
- **H (удержание):** одиночный вход при ТОМ ЖЕ §5-плече, что у DCA —
  контроль на плечо: изолирует «лестница против всё-сразу при одном
  риске» (метод D1 §8.3).
- **S (DCA структурный):** доливы на структурных уровнях, §5-плечо,
  тейк + пол капитуляции.

Пары: **S − B** (бьёт ли DCA нынешнюю книгу — вопрос продукта), **S − H**
(помогает ли лестница при одном плече — механизм). Первый срез — ЛОНГИ
(естественный DCA-вниз); шорты зеркало, следом. Каждый выбор оценивается
НЕЗАВИСИМО (без слотов) — так пара чиста (те же выборы у всех рук), как в
реплее D1; книжная реалистичность слотов — уточнение потом.

Оговорки (объявлены до прогона): веса видели эти часы (оценка сверху);
ранняя капитуляция рулевого §6 здесь НЕ считается — она мерится против
пола отдельной рукой (пересчёт), вердикт по «только пол»; издержки —
круг `ROUND_COST_BP` на ногу; нуль §8.6 (структура против σ-сетки) —
отдельная рука, следом.

Запуск (VPS, журнал листов и запись баров только там):

    setsid nohup .venv/bin/python research/dca_ladder/run_d2.py \\
        > research/dca_ladder/out/run_d2.log 2>&1 &

Смоук: `--limit 400` (первые N ног). Публикует отчёт сам; `--no-publish`
выключает.
"""

import argparse
import bisect
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
sys.path.insert(0, os.path.join(RESEARCH, "s10_policy"))
sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))
sys.path.insert(0, os.path.join(RESEARCH, "s9_sweep"))
sys.path.insert(0, os.path.join(RESEARCH, "t4_structure"))
import ladder as L                                           # noqa: E402
import tournament as TNT                                     # noqa: E402
import trades as TR                                          # noqa: E402
import sweep as SW                                           # noqa: E402
import levels as LV                                          # noqa: E402

# --- объявленная сетка (до прогона) ---------------------------------------
SHEETS = os.path.join(RESEARCH, "s8_loop", "out", "model_sit", "sheets.jsonl")
ROOT = os.path.join(RESEARCH, "b1_book", "out")
MARKET = "BTCUSDT"                 # прокси рыночной волны для бета-хеджа (§б)
# Гейт книги: реплеим ТОЛЬКО выборы, которые ситуационная книга реально
# открывает (её вход = «сигнал модели», выбор владельца). Полное сечение
# журнала — 840 тыс. ног, гейт режет до тех, что книга торгует; иначе
# меряли бы весь кросс-срез, а не выборы, и 96 ч баров на ногу × 495 тыс.
# лонгов неисполнимы. Скидку/взведение сканера v11–v13 реплей не
# воспроизводит (как турнир) — гейтованные ноги суть кандидаты книги.
MIN_EDGE_BP = 33.0                # SIT_MIN_EDGE_BP (гейт края)
MIN_RR = 2.0                      # SIT_MIN_RR (гейт отношения)
BACK_H = 24                       # окно перед входом для структурных уровней
HOLD_H = 72                       # предельное удержание/капитуляция, часов
N_RUNGS = 4                       # база + до трёх доливов вниз
MIN_ADD_GAP = 0.015               # каждый долив ≥1.5 % ниже предыдущего (§R1)
WEIGHTS = [0.25, 0.25, 0.25, 0.25]
SURVIVE_MULT = 2.0                # §5: ликвидация не ближе mult·d_max
FLAT_MMR = 0.02                   # делистнутой ноге (§10 модальный)
FLOOR_FRAC = 0.10                 # пол капитуляции: у ликвидации ближе 10 %
SS_SHORT_BETA = 1.0               # рука SS (§а): нотионал короткого = β_s·нотионал лонга (полный хедж — потолок)


def instruments_tiers():
    p = os.path.join(RESEARCH, "a1_universe", "out", "risk_limits.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def structural_rungs(entry, level_prices, min_gap, n_rungs):
    """Цены рунгов DCA-лонга: вход плюс структурные уровни НИЖЕ.

    Берём уровни ниже входа, ближайший первым, каждый обязан стоять не
    ближе `min_gap` (доля цены) от предыдущего рунга — это «запас на
    дальнейший пролив» §R1 и «не дважды на одном уровне». Возвращает
    список по УБЫВАНИЮ (rung[0] = вход), длиной ≤ n_rungs; если ни один
    уровень не годится, вернёт `[entry]` — лестница вырождается в
    одиночный вход (без доливов), и плечо тогда 1× (нет резерва — нет
    рычага). Чистая функция.
    """
    if entry <= 0:
        return [entry]
    below = sorted([p for p in level_prices if 0 < p < entry], reverse=True)
    rungs = [entry]
    for p in below:
        if len(rungs) >= n_rungs:
            break
        if (rungs[-1] - p) / rungs[-1] >= min_gap:   # ≥min_gap ниже прошлого
            rungs.append(p)
    return rungs


def split_window(bars, ts, at, back_h, fwd_h):
    """Окно [at−back_h, at+fwd_h] из УЖЕ прочитанного ряда символа.

    `bars` — весь ряд символа (сорт. по времени), `ts` — список его меток
    (кэш, чтобы не пересобирать на каждую ногу). Возвращает (окно, now_i —
    индекс первого бара с t ≥ at ВНУТРИ окна) или None. Много гейтованных
    выборов делят символ, и читать перекрывающиеся 96-часовые окна на
    каждую ногу — главная цена прогона; кэш на символ её снимает.
    """
    a = at - back_h * 3600
    b = at + fwd_h * 3600
    i0 = bisect.bisect_left(ts, a)
    i1 = bisect.bisect_right(ts, b)
    win = bars[i0:i1]
    if not win:
        return None
    now_i = None
    for i, bb in enumerate(win):
        if bb[0] >= at:
            now_i = i
            break
    if now_i is None or now_i >= len(win) - 1:
        return None                                  # нет баров после входа
    return win, now_i


def build_levels(bars, now_i):
    """Структурные уровни на момент входа по 24-часовому окну до него."""
    lo = max(0, now_i - LV.LOOKBACK_MIN)
    seg = bars[lo:now_i + 1]
    if len(seg) < LV.MIN_HISTORY_MIN:
        return np.array([])                          # мало истории — уровней нет
    t = np.array([b[0] for b in seg], dtype="int64")
    H = np.array([b[2] for b in seg], dtype="float64")
    Lo = np.array([b[3] for b in seg], dtype="float64")
    P = np.array([b[4] for b in seg], dtype="float64")
    V = np.array([b[5] for b in seg], dtype="float64")
    prices, _kinds, _noise, _slow = LV.build(t, H, Lo, P, V, len(seg) - 1)
    return prices


def px_at(bars, ts, t):
    """Цена закрытия рыночной ноги (BTC) на последнем баре с временем ≤ t.

    Хедж мерится закрытие-в-закрытие: вход хеджа — закрытие бара входа
    лонга, выход — закрытие бара выхода лонга (bisect по меткам `ts`).
    Нет бара ≤ t (событие раньше первого бара) — None, хедж не считается.
    """
    if not bars:
        return None
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return float(bars[i][4])


def run(limit=None, src=None, log=print):
    t_run = time.time()
    tiers_all = instruments_tiers()
    legs = TNT.legs_from_sheets([SHEETS], log=log)
    longs = [g for g in legs if g["side"] == "long"
             and abs(g["fwd"]) >= MIN_EDGE_BP and (g["rr"] or 0) >= MIN_RR]
    log(f"ног всего {len(legs)}, лонгов под гейтом книги "
        f"(край≥{MIN_EDGE_BP}, RR≥{MIN_RR}) {len(longs)}"
        + (f", лимит {limit}" if limit else ""))
    if limit:
        longs = longs[:limit]

    # группируем выборы по символу: ряд символа читается ОДИН раз на весь
    # его диапазон, окна нарезаются срезом (split_window)
    by_sym = {}
    for g in longs:
        by_sym.setdefault(g["sym"], []).append(g)
    log(f"символов {len(by_sym)}")

    arms = {a: {"pnl": [], "liq": 0, "ruin": 0, "day": {}, "ok": 0}
            for a in ("B", "H", "S", "SH", "SS")}
    depth_hist = []                                  # глубина лестницы S
    lev_hist = []                                    # плечо §5
    no_add = 0                                       # выборов без структурного долива
    n = 0
    skipped = 0
    said = time.time()
    done_sym = 0
    get = src.bars if src else (lambda s, x, y: SW.read_bars(ROOT, s, x, y))
    # рыночная нога бета-хеджа (§б): BTC читается ОДИН раз на весь диапазон
    # выборов; хедж = короткий BTC на β·нотионал лонга, открыт с входом лонга,
    # закрыт с его выходом (`exit_ts`). Нет BTC — SH не считается (nan).
    if longs:
        ga = min(g["at"] for g in longs) - BACK_H * 3600
        gb = max(g["at"] for g in longs) + HOLD_H * 3600
        btc_bars = get(MARKET, ga, gb)
    else:
        btc_bars = []
    btc_ts = [bb[0] for bb in btc_bars]
    if not btc_bars:
        log(f"BTC ({MARKET}) баров нет — бета-хедж (рука SH) не считается")
    for sym, glist in by_sym.items():
        done_sym += 1
        if time.time() - said > 30:
            log(f"  символ {done_sym}/{len(by_sym)}  взято {n}")
            said = time.time()
        a0 = min(gg["at"] for gg in glist) - BACK_H * 3600
        b1 = max(gg["at"] for gg in glist) + HOLD_H * 3600
        bars = get(sym, a0, b1)
        if not bars:
            skipped += len(glist)
            continue
        ts = [bb[0] for bb in bars]
        tiers = tiers_all.get(sym) or []
        look = lambda notl: L.mmr_for_notional(tiers, notl, flat=FLAT_MMR)
        for g in glist:
            stt = _process_leg(g, bars, ts, look, arms, depth_hist, lev_hist,
                               btc_bars, btc_ts)
            if stt is None:
                skipped += 1
                continue
            if stt == "no_add":
                no_add += 1
            n += 1
    return measures(arms, n, skipped, no_add, depth_hist, lev_hist,
                    time.time() - t_run)


def _process_leg(g, bars, ts, look, arms, depth_hist, lev_hist,
                 btc_bars=None, btc_ts=None):
    """Обработать один выбор на прочитанном ряде символа.

    Возвращает: None — пропуск (нет окна/геометрии); "no_add" — без
    структурного долива (лестница вырождается в одиночный вход); "ok".
    Побочно дописывает pnl рук и гистограммы. Вынесено, чтобы кэш символа
    и обработка ноги были раздельно проверяемы. `btc_bars`/`btc_ts` —
    рыночная нога бета-хеджа (рука SH); нет их или беты — SH = nan.
    """
    rs = split_window(bars, ts, g["at"], BACK_H, HOLD_H)
    if rs is None:
        return None
    win, now_i = rs
    hold = win[now_i:]
    entry = float(hold[0][1])
    if entry <= 0:
        return None
    # уровни выхода из обещаний модели, якорь — вход (как в турнире)
    take_px = entry * (1 + g["fav"] / 1e4)       # mfe (выше входа у лонга)
    stop_px = entry * (1 + g["adv_q"] / 1e4)     # исполняемый стоп книги
    if not (take_px > entry and 0 < stop_px < entry):
        return None

    # структурные рунги и §5-плечо
    lv = build_levels(win, now_i)
    rungs = structural_rungs(entry, list(lv), MIN_ADD_GAP, N_RUNGS)
    status = "ok"
    if len(rungs) < 2:
        status, lev_s = "no_add", 1.0            # нет резерва — нет рычага
    else:
        d_max = (entry - rungs[-1]) / entry
        lev_s = L.max_leverage(rungs, WEIGHTS[:len(rungs)], 1.0, entry,
                               d_max, look, SURVIVE_MULT)
        if lev_s <= 0:                           # забор отказал лестнице
            status, lev_s, rungs = "no_add", 1.0, [entry]

    # руина: ряд имени кончился внутри окна удержания
    is_ruin = int(hold[-1][0] < g["at"] + HOLD_H * 3600 - 3600
                  and len(hold) < 30)

    # рука B — книга: одиночный вход 1×, стоп + тейк
    b = L.simulate_single(hold, 1.0, 1.0, look(1.0),
                          take_px=take_px, stop_px=stop_px)
    # рука H — одиночный вход при §5-плече лестницы, стоп + тейк
    h = L.simulate_single(hold, 1.0, lev_s, look(1.0 * lev_s),
                          take_px=take_px, stop_px=stop_px)
    # рука S — DCA структурный: тейк + пол капитуляции
    wS = WEIGHTS[:len(rungs)]
    s = L.simulate_dca(hold, rungs, wS, 1.0, lev_s, look(1.0 * lev_s),
                       take_px=take_px, floor_frac=FLOOR_FRAC)

    # рука SH — S плюс бета-хедж рынком (§б): короткий BTC на β·нотионал
    # лонга, открыт с входом лонга (закрытие бара входа), закрыт с его
    # выходом (`s["exit_ts"]`). Короткий BTC даёт плюс при падении BTC —
    # поддерживает деп ровно в обвале, когда лонг проседает. Единицы те
    # же, что у S (доля капитала позиции = 1.0): нотионал лонга уже
    # захеджирован в `filled_notional`. Нет беты или BTC — SH = nan.
    sh_pnl = float("nan")
    if g.get("beta") is not None and btc_bars:
        be = px_at(btc_bars, btc_ts, hold[0][0])
        bx = px_at(btc_bars, btc_ts, s["exit_ts"])
        if be and bx and be > 0:
            hedge = -g["beta"] * s["filled_notional"] * (bx / be - 1.0)
            sh_pnl = s["pnl_frac"] + hedge

    # рука SS — S плюс короткий на ТОЙ ЖЕ монете в просадке (§а, идея
    # владельца): триггер = первый долив (`rungs[1]`), нотионал короткого
    # β_s·нотионал лонга, закрывается ПО ВОССТАНОВЛЕНИЮ (просадка кончилась,
    # лонг едет дальше сам — median не ест) либо с лонгом при продолжении
    # падения (гасит хвост). Только у позиций с доливом (у 1× лестницы
    # хвоста-ликвидации нет). SS = S, если короткий не активировался.
    ss_pnl = s["pnl_frac"]
    ss_active = False
    if len(rungs) >= 2:
        short = L.same_coin_short(hold, rungs[1], s["exit_ts"], s["exit_px"],
                                  SS_SHORT_BETA * s["filled_notional"])
        if short is not None:
            ss_pnl = s["pnl_frac"] + short
            ss_active = True

    day = time.strftime("%Y-%m-%d", time.gmtime(g["at"]))
    for nm, res in (("B", b), ("H", h), ("S", s)):
        arms[nm]["pnl"].append(res["pnl_frac"])
        arms[nm]["ok"] += 1
        arms[nm]["liq"] += int(res.get("exit") == "ликвидация")
        arms[nm]["ruin"] += is_ruin
        arms[nm]["day"][day] = arms[nm]["day"].get(day, 0.0) + res["pnl_frac"]
    # SH хранится ВЫРОВНЕННО по позициям (тот же индекс, что B/H/S) —
    # nan там, где хеджа нет; парная разность считается по маске (measures)
    a = arms["SH"]
    a["pnl"].append(sh_pnl)
    if sh_pnl == sh_pnl:                             # не nan
        a["ok"] += 1
        a["liq"] += int(s.get("exit") == "ликвидация")   # ликвид. ЛОНГА
        a["ruin"] += is_ruin
        a["day"][day] = a["day"].get(day, 0.0) + sh_pnl
    # SS — полная книга (= S там, где короткий не сработал); active считает,
    # у скольких позиций короткий реально включался в просадке
    a = arms["SS"]
    a["pnl"].append(ss_pnl)
    a["ok"] += 1
    a["active"] = a.get("active", 0) + int(ss_active)
    a["liq"] += int(s.get("exit") == "ликвидация")
    a["ruin"] += is_ruin
    a["day"][day] = a["day"].get(day, 0.0) + ss_pnl
    depth_hist.append(s["depth"])
    lev_hist.append(lev_s)
    return status


def measures(arms, n, skipped, no_add, depth_hist, lev_hist, secs):
    out = {"positions": n, "skipped": skipped, "no_add": no_add,
           "secs": round(secs, 1),
           "avg_depth": round(float(np.mean(depth_hist)), 2) if depth_hist
           else None,
           "median_lev": round(float(np.median(lev_hist)), 2) if lev_hist
           else None,
           "max_lev": round(float(np.max(lev_hist)), 2) if lev_hist else None,
           "params": {"BACK_H": BACK_H, "HOLD_H": HOLD_H, "N_RUNGS": N_RUNGS,
                      "MIN_ADD_GAP": MIN_ADD_GAP, "SURVIVE_MULT": SURVIVE_MULT,
                      "FLOOR_FRAC": FLOOR_FRAC},
           "arms": {}}
    if not n:
        return out
    for nm, a in arms.items():
        pnl = np.array(a["pnl"], dtype=float)
        good = pnl[~np.isnan(pnl)]              # у SH бывают nan (нет хеджа)
        ok = a["ok"]
        if len(good) == 0:
            out["arms"][nm] = {"ok": 0}
            continue
        win = good[good > 0]
        med_win = float(np.median(win)) if len(win) else float("nan")
        days = sorted(a["day"])
        cur = np.cumsum([a["day"][d] for d in days]) if days else np.array([])
        dd = float(np.min(cur - np.maximum.accumulate(cur))) if len(cur) else 0.0
        out["arms"][nm] = {
            "ok": ok,
            "liq_freq": round(a["liq"] / ok, 4) if ok else None,
            "ruin_freq": round(a["ruin"] / ok, 4) if ok else None,
            "median": round(float(np.median(good)), 4),
            "mean": round(float(np.mean(good)), 4),
            "green": round(float(np.mean(good > 0)), 3),
            "worst": round(float(np.min(good)), 3),
            "bite": (round(abs(float(np.min(good))) / med_win, 1)
                     if med_win and med_win > 0 else None),
            "curve_dd": round(dd, 3),
        }
    # парные разности по позициям (те же выборы у всех рук; выравнивание
    # по индексу — один и тот же выбор во всех четырёх массивах)
    B = np.array(arms["B"]["pnl"], dtype=float)
    H = np.array(arms["H"]["pnl"], dtype=float)
    S = np.array(arms["S"]["pnl"], dtype=float)
    SH = np.array(arms["SH"]["pnl"], dtype=float)
    out["paired"] = {
        "S_minus_B_median": round(float(np.median(S - B)), 4),
        "S_beats_B_frac": round(float(np.mean(S > B)), 3),
        "S_minus_H_median": round(float(np.median(S - H)), 4),
        "S_beats_H_frac": round(float(np.mean(S > H)), 3),
    }
    m = ~np.isnan(SH)                            # где хедж измерим
    out["paired"]["hedge_ok"] = int(m.sum())
    out["paired"]["hedge_missing"] = int((~m).sum())
    if m.any():
        out["paired"].update({
            "SH_minus_S_median": round(float(np.median((SH - S)[m])), 4),
            "SH_beats_S_frac": round(float(np.mean(SH[m] > S[m])), 3),
            "SH_minus_B_median": round(float(np.median((SH - B)[m])), 4),
            "SH_beats_B_frac": round(float(np.mean(SH[m] > B[m])), 3),
        })
    SS = np.array(arms["SS"]["pnl"], dtype=float)
    out["paired"].update({
        "short_active": int(arms["SS"].get("active", 0)),
        "SS_minus_S_median": round(float(np.median(SS - S)), 4),
        "SS_beats_S_frac": round(float(np.mean(SS > S)), 3),
        "SS_minus_B_median": round(float(np.median(SS - B)), 4),
        "SS_beats_B_frac": round(float(np.mean(SS > B)), 3),
    })
    return out


def report(s):
    P = []
    P.append("# D2 — DCA-стратегия на выборах модели (спека 14)\n")
    P.append("Диагностика, не вердикт. Вход = выбор модели (журнал листов), "
             "доливы = структурные уровни T4, выход = тейк (mfe) + пол "
             "капитуляции §6. Только ЛОНГИ; парно по выборам.\n")
    P.append(f"Позиций {s['positions']}, пропущено {s['skipped']} (нет "
             f"баров/уровней/геометрии), без структурного долива {s['no_add']}, "
             f"прогон {s['secs']} с.\n")
    if not s["positions"]:
        P.append("**Позиций ноль** — журнал листов пуст или баров нет.")
        return "\n".join(P) + "\n"
    P.append(f"Лестница S: средняя глубина {s['avg_depth']} из {N_RUNGS}, "
             f"плечо §5 медиана {s['median_lev']}×, максимум {s['max_lev']}×.\n")
    P.append("## Руки (доля капитала позиции)\n")
    P.append("| рука | ликвид. | руина | медиана | среднее | зелёных | "
             "худшая | укус | просадка |")
    P.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    names = {"B": "B книга 1×", "H": "H удержание §5", "S": "S DCA структ.",
             "SH": "SH DCA + бета-хедж", "SS": "SS DCA + шорт той же монеты"}
    for nm in ("B", "H", "S", "SH", "SS"):
        a = s["arms"][nm]
        if not a.get("ok"):                      # SH без единого хеджа
            P.append(f"| {names[nm]} | — | — | — | — | — | — | — | — |")
            continue
        bite = a["bite"]
        lq = f"{a['liq_freq']*100:.2f} %" if a['liq_freq'] is not None else "—"
        ru = f"{a['ruin_freq']*100:.2f} %" if a['ruin_freq'] is not None else "—"
        P.append(f"| {names[nm]} | {lq} | {ru} | {a['median']*100:+.2f} % | "
                 f"{a['mean']*100:+.2f} % | {a['green']*100:.1f} % | "
                 f"{a['worst']*100:+.1f} % | "
                 f"{('%.1f' % bite) if bite else '—'} | "
                 f"{a['curve_dd']*100:+.1f} % |")
    pr = s["paired"]
    P.append(f"\nХедж измерим у {pr['hedge_ok']} позиций, нет беты/BTC у "
             f"{pr['hedge_missing']}.")
    P.append("\n## Парные разности (те же выборы)\n")
    P.append(f"- **S − B (DCA против нынешней книги): медиана "
             f"{pr['S_minus_B_median']*100:+.2f} %**, S выше B в "
             f"{pr['S_beats_B_frac']*100:.1f} % выборов")
    P.append(f"- **S − H (лестница при одном плече): медиана "
             f"{pr['S_minus_H_median']*100:+.2f} %**, S выше H в "
             f"{pr['S_beats_H_frac']*100:.1f} % выборов")
    if "SH_minus_S_median" in pr:
        P.append(f"- **SH − S (бета-хедж против голого DCA): медиана "
                 f"{pr['SH_minus_S_median']*100:+.2f} %**, SH выше S в "
                 f"{pr['SH_beats_S_frac']*100:.1f} % выборов "
                 f"(на {pr['hedge_ok']} хеджированных)")
        P.append(f"- **SH − B (бета-хедж против нынешней книги): медиана "
                 f"{pr['SH_minus_B_median']*100:+.2f} %**, SH выше B в "
                 f"{pr['SH_beats_B_frac']*100:.1f} % выборов")
    P.append(f"- **SS − S (шорт той же монеты против голого DCA): медиана "
             f"{pr['SS_minus_S_median']*100:+.2f} %**, SS выше S в "
             f"{pr['SS_beats_S_frac']*100:.1f} % выборов "
             f"(короткий включался у {pr['short_active']} из {s['positions']})")
    P.append(f"- **SS − B (шорт той же монеты против нынешней книги): медиана "
             f"{pr['SS_minus_B_median']*100:+.2f} %**, SS выше B в "
             f"{pr['SS_beats_B_frac']*100:.1f} % выборов\n")
    P.append("\n**Шорт той же монеты (рука SS, §а):** параллельный короткий "
             "на ТОЙ ЖЕ монете, включается когда цена доходит до первого "
             "долива (просадка), нотионал β_s·нотионал лонга. Закрывается ПО "
             "ВОССТАНОВЛЕНИЮ (цена вернулась к триггеру — просадка кончилась, "
             "короткий вышел ~в ноль по уровню, лонг забирает отскок сам) "
             "либо с лонгом при продолжении падения (гасит хвост). В отличие "
             "от бета-хеджа короткий КОРРЕЛИРОВАН с хвостом (та же монета "
             "падает), поэтому хвост режет, а не углубляет. Оговорки: "
             "короткий ОДИН на позицию (второй провал после восстановления не "
             "хеджируется — занижает пользу); вход/выход по уровню (модель "
             "v13, как тейк) — оптимистично; β_s = 1.0 (полный хедж) — "
             "потолок пользы, реальный размер меньше стоит меньше защиты; "
             "триггер = первый долив (сдвинуть глубже — меньше активаций, "
             "меньше защиты и меньше цены). Вопрос владельца про РИСК: смотреть "
             "худшую/укус/просадку SS против S ценой в медиане.")
    P.append("\n**Хедж (рука SH):** короткий BTC на β·нотионал лонга, открыт "
             "с входом лонга, закрыт с его выходом; в обвале (лонг падает, "
             "BTC падает) даёт плюс — поддерживает деп в просадке. Вопрос "
             "владельца про РИСК, не доход: смотреть худшую, укус и просадку "
             "SH против S, ценой в медиане. Оговорки хеджа: β — к волне "
             "универсума (M1), а инструмент хеджа BTC (прокси рынка) — "
             "приближение; размер сматчен к ИТОГОВОМУ нотионалу лестницы "
             "(реальный отслеживал бы заполнение, по базе недохеджировал бы — "
             "но в хвосте лестница заполняется целиком, где хедж и нужен); "
             "хедж мерится закрытие-в-закрытие BTC, лонг входит по открытию — "
             "лёгкий базис входа.")
    P.append("\n**Оговорки:** веса видели эти часы (оценка сверху); ранняя "
             "капитуляция рулевого §6 не считается — вердикт по «только пол»; "
             "нуль §8.6 (структура против σ-сетки) отдельной рукой следом; "
             "шорты (DCA-вверх) зеркалом следом; `curve_dd` — сумма долей "
             "капитала по позициям без нормировки на книгу, вердиктом не "
             "является (единица турнира). Издержки круга на ногу в pnl ещё "
             "не сняты (первый ответ — брутто).")
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
    with open(os.path.join(OUT, f"D2-dca-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    rep = report(s)
    with open(os.path.join(OUT, f"D2-dca-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    if not a.no_publish:
        publish(f"d2-dca-{tag}")


if __name__ == "__main__":
    main()
