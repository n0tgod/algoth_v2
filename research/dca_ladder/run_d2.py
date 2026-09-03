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
import json
import os
import statistics as st
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
BACK_H = 24                       # окно перед входом для структурных уровней
HOLD_H = 72                       # предельное удержание/капитуляция, часов
N_RUNGS = 4                       # база + до трёх доливов вниз
MIN_ADD_GAP = 0.015               # каждый долив ≥1.5 % ниже предыдущего (§R1)
WEIGHTS = [0.25, 0.25, 0.25, 0.25]
SURVIVE_MULT = 2.0                # §5: ликвидация не ближе mult·d_max
FLAT_MMR = 0.02                   # делистнутой ноге (§10 модальный)
FLOOR_FRAC = 0.10                 # пол капитуляции: у ликвидации ближе 10 %


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


def read_split(root, sym, at, back_h, fwd_h, src=None):
    """Бары [at−back_h, at+fwd_h] и индекс первого бара с t ≥ at.

    Возвращает (bars_all, now_i) или None, если баров нет либо первый бар
    входа отсутствует. Бары — 6-кортежи (t, open, high, low, close, qv).
    """
    a = at - back_h * 3600
    b = at + fwd_h * 3600
    get = src.bars if src else (lambda s, x, y: SW.read_bars(root, s, x, y))
    bars = get(sym, a, b)
    if not bars:
        return None
    now_i = None
    for i, bb in enumerate(bars):
        if bb[0] >= at:
            now_i = i
            break
    if now_i is None or now_i >= len(bars) - 1:
        return None                                  # нет баров после входа
    return bars, now_i


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


def run(limit=None, src=None, log=print):
    t_run = time.time()
    tiers_all = instruments_tiers()
    legs = TNT.legs_from_sheets([SHEETS], log=log)
    longs = [g for g in legs if g["side"] == "long"]
    log(f"ног всего {len(legs)}, лонгов {len(longs)}"
        + (f", лимит {limit}" if limit else ""))
    if limit:
        longs = longs[:limit]

    arms = {a: {"pnl": [], "liq": 0, "ruin": 0, "day": {}}
            for a in ("B", "H", "S")}
    depth_hist = []                                  # глубина лестницы S
    lev_hist = []                                    # плечо §5
    no_add = 0                                       # выборов без структурного долива
    n = 0
    skipped = 0
    said = time.time()
    for k, g in enumerate(longs):
        if time.time() - said > 30:
            log(f"  {k}/{len(longs)}  взято {n}")
            said = time.time()
        rs = read_split(ROOT, g["sym"], g["at"], BACK_H, HOLD_H, src=src)
        if rs is None:
            skipped += 1
            continue
        bars, now_i = rs
        hold = bars[now_i:]
        entry = float(hold[0][1])
        if entry <= 0:
            skipped += 1
            continue
        # уровни выхода из обещаний модели, якорь — вход (как в турнире)
        take_px = entry * (1 + g["fav"] / 1e4)       # mfe (выше входа у лонга)
        stop_px = entry * (1 + g["adv_q"] / 1e4)     # исполняемый стоп книги
        if not (take_px > entry and 0 < stop_px < entry):
            skipped += 1
            continue
        tiers = tiers_all.get(g["sym"]) or []
        look = lambda notl: L.mmr_for_notional(tiers, notl, flat=FLAT_MMR)

        # структурные рунги и §5-плечо
        lv = build_levels(bars, now_i)
        rungs = structural_rungs(entry, list(lv), MIN_ADD_GAP, N_RUNGS)
        if len(rungs) < 2:
            no_add += 1
            lev_s = 1.0                              # нет резерва — нет рычага
            d_max = 0.0
        else:
            d_max = (entry - rungs[-1]) / entry
            lev_s = L.max_leverage(rungs, WEIGHTS[:len(rungs)], 1.0, entry,
                                   d_max, look, SURVIVE_MULT)
            if lev_s <= 0:                           # забор отказал лестнице
                no_add += 1
                lev_s, d_max, rungs = 1.0, 0.0, [entry]

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

        for nm, res in (("B", b), ("H", h), ("S", s)):
            arms[nm]["pnl"].append(res["pnl_frac"])
            arms[nm]["liq"] += int(res.get("exit") == "ликвидация")
            arms[nm]["ruin"] += is_ruin
            day = time.strftime("%Y-%m-%d", time.gmtime(g["at"]))
            arms[nm]["day"][day] = arms[nm]["day"].get(day, 0.0) \
                + res["pnl_frac"]
        depth_hist.append(s["depth"])
        lev_hist.append(lev_s)
        n += 1

    return measures(arms, n, skipped, no_add, depth_hist, lev_hist,
                    time.time() - t_run)


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
        pnl = np.array(a["pnl"])
        win = pnl[pnl > 0]
        med_win = float(np.median(win)) if len(win) else float("nan")
        days = sorted(a["day"])
        cur = np.cumsum([a["day"][d] for d in days]) if days else np.array([])
        dd = float(np.min(cur - np.maximum.accumulate(cur))) if len(cur) else 0.0
        out["arms"][nm] = {
            "liq_freq": round(a["liq"] / n, 4),
            "ruin_freq": round(a["ruin"] / n, 4),
            "median": round(float(np.median(pnl)), 4),
            "mean": round(float(np.mean(pnl)), 4),
            "green": round(float(np.mean(pnl > 0)), 3),
            "worst": round(float(np.min(pnl)), 3),
            "bite": (round(abs(float(np.min(pnl))) / med_win, 1)
                     if med_win and med_win > 0 else None),
            "curve_dd": round(dd, 3),
        }
    # парные разности по позициям (те же выборы у всех рук)
    B = np.array(arms["B"]["pnl"])
    H = np.array(arms["H"]["pnl"])
    S = np.array(arms["S"]["pnl"])
    out["paired"] = {
        "S_minus_B_median": round(float(np.median(S - B)), 4),
        "S_beats_B_frac": round(float(np.mean(S > B)), 3),
        "S_minus_H_median": round(float(np.median(S - H)), 4),
        "S_beats_H_frac": round(float(np.mean(S > H)), 3),
    }
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
    names = {"B": "B книга 1×", "H": "H удержание §5", "S": "S DCA структ."}
    for nm in ("B", "H", "S"):
        a = s["arms"][nm]
        bite = a["bite"]
        P.append(f"| {names[nm]} | {a['liq_freq']*100:.2f} % | "
                 f"{a['ruin_freq']*100:.2f} % | {a['median']*100:+.2f} % | "
                 f"{a['mean']*100:+.2f} % | {a['green']*100:.1f} % | "
                 f"{a['worst']*100:+.1f} % | "
                 f"{('%.1f' % bite) if bite else '—'} | "
                 f"{a['curve_dd']*100:+.1f} % |")
    pr = s["paired"]
    P.append("\n## Парные разности (те же выборы)\n")
    P.append(f"- **S − B (DCA против нынешней книги): медиана "
             f"{pr['S_minus_B_median']*100:+.2f} %**, S выше B в "
             f"{pr['S_beats_B_frac']*100:.1f} % выборов")
    P.append(f"- **S − H (лестница при одном плече): медиана "
             f"{pr['S_minus_H_median']*100:+.2f} %**, S выше H в "
             f"{pr['S_beats_H_frac']*100:.1f} % выборов\n")
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
