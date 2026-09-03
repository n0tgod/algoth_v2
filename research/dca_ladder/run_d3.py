#!/usr/bin/env python3
"""
D3 (спека 14) — три замера ОДНИМ проходом по тем же выборам, что D2.

Владелец (2026-09-03) после закрытия трёх хеджей: «давай все 3 задачи
замеряй сразу». Три хеджа (а/б/в) закрыты, и арифметика объяснила почему
разом: у руки S ликвидаций 0.06 % — это ≈5 позиций из 8670, весь хвост
стоит ≈520 п.п., а бета-хедж уронил среднее на 2.88 п.п. × 8670 ≈ 24 970
п.п., то есть заплатил в 48 раз больше, чем страховал. **Любой линейный
хедж облагает все 8670 сделок ради страховки от пяти.** Значит вопрос не
«чем хеджировать», а «чем убрать хвост в источнике».

Отсюда три задачи, все на ОДНИХ данных и в ОДНОМ проходе:

1. **Граница забора** — сетка `SURVIVE_MULT × FLOOR_FRAC`, объявлена ниже
   ДО прогона. Прямой ответ на требование владельца «нет ликвидаций»: не
   число, а кривая «доля ликвидаций против дохода», точку на ней выбирает
   владелец. Состав позиций во ВСЕХ ячейках один и тот же (забор не
   отказывает позиции, а роняет её в 1× — поведение D2), поэтому сравнение
   ячеек парное по построению и отбором не загрязнено.
2. **Портрет хвоста** — что было ИЗВЕСТНО В МОМЕНТ ВХОДА у худшего 1 %
   позиций. Если признак есть, хвост дешевле не хеджировать, а не
   открывать: правило бесплатно для остальных 99 %. Планка — семейственный
   нуль (перестановка меток, максимум по признакам), иначе при десяти
   признаках и 87 наблюдениях «находка» появится сама. Канареечный признак
   (час входа) стоит в той же таблице: если он разделяет не хуже прочих,
   вся таблица есть шум.
3. **Покрытие опционами** — единственный выпуклый инструмент, читается из
   `a1_universe/out/options_inventory.json` (пишет `bybit_options.py`).
   Считается доля хвоста в именах, у которых опционы вообще существуют.

Встроенная сверка: ячейка (SURVIVE_MULT 2.0, FLOOR_FRAC 0.10) обязана
воспроизвести руку S опубликованного D2 — иначе прогон описывает другую
книгу, а обе таблицы выглядят исправными.

Оговорки (в силе с D2): веса видели эти часы (оценка сверху); издержки
круга в pnl не сняты (брутто); `curve_dd` — сумма долей капитала по
позициям без нормировки на книгу, вердиктом не является; ранняя
капитуляция рулевого §6 не считается.

Запуск (VPS — журнал листов и запись баров только там):

    setsid nohup .venv/bin/python research/dca_ladder/run_d3.py \\
        > research/dca_ladder/out/run_d3.log 2>&1 &

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
import tournament as TNT                                      # noqa: E402
import sweep as SW                                            # noqa: E402

# --- объявленная сетка (до прогона, не менять после чтения результата) ----
# Ряды: множитель забора §5. None = жёсткий 1× (плечо не выводится, а
# назначается единицей). У лонга при 1× цена ликвидации равна нулю — то есть
# ликвидация невозможна ПО ПОСТРОЕНИЮ, и эта строка отвечает на «нет
# ликвидаций» гарантированно; вопрос лишь в её цене.
GRID_SURVIVE = [2.0, 3.0, 4.0, 6.0, None]
# Колонки: пол капитуляции §6 долей расстояния «вход → ликвидация».
# None = пола нет вовсе (держим до ликвидации либо тейка), 0.50 = режем на
# полпути. Больше доля — выше пол — раньше выходим.
GRID_FLOOR = [None, 0.10, 0.25, 0.50]
BASE_CELL = (2.0, 0.10)            # ячейка D2 — предмет встроенной сверки

TAIL_Q = 0.01                      # «хвост» = худший 1 % позиций
NULL_PERM = 200                    # перестановок для семейственной планки
NULL_SEED = 20260904               # зерно ЧИСЛОМ (урок R3)
AVOID_Q = 0.10                     # правило избегания режет дециль признака

OPTIONS_INV = os.path.join(RESEARCH, "a1_universe", "out",
                           "options_inventory.json")
INSTRUMENTS = os.path.join(RESEARCH, "a1_universe", "out", "instruments.json")
ROOT_B1 = os.path.join(RESEARCH, "b1_book", "out")

# Человеческие имена признаков и их единица: «bp» — движение цены (в отчёте
# печатается процентами), «x» — отношение, «d» — сутки, «$» — деньги.
FEATURES = [
    ("fwd_bp", "обещание модели |fwd|", "bp"),
    ("rr", "обещанное отношение RR", "x"),
    ("beta", "бета к волне рынка", "x"),
    ("lev", "плечо, выданное забором §5", "x"),
    ("sigma_bp", "σ минутных доходностей за 24 ч до входа", "bp"),
    ("range_bp", "размах 24 ч до входа", "bp"),
    ("turnover", "медианный оборот минуты до входа", "$"),
    ("n_rungs", "сколько структурных рунгов нашлось", "x"),
    ("gap1_bp", "до первого долива", "bp"),
    ("age_d", "возраст листинга на площадке", "d"),
    ("hour", "час входа UTC (канарейка)", "x"),
]


def instruments():
    """Справочник площадки: символ → запись (`launch_time`, `base_coin`, …).

    Нет файла — пустой словарь, и оба зависящих признака честно становятся
    «не измерялось», а не нулём: «возраст неизвестен» и «возраст нулевой»
    суть разные утверждения.
    """
    try:
        with open(INSTRUMENTS, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def listed_days(inst):
    """Момент листинга на площадке (секунды эпохи) — известен ex ante."""
    out = {}
    for sym, rec in inst.items():
        if not isinstance(rec, dict):
            continue
        try:
            v = float(rec.get("launch_time"))
        except (TypeError, ValueError):
            continue
        if v > 1e11:                     # миллисекунды
            v /= 1000.0
        if v > 0:
            out[sym] = v
    return out


def window_stats(win, now_i):
    """Признаки окна ДО входа: σ, размах, оборот. Только прошлое.

    Берётся `win[:now_i + 1]` — бары, закрывшиеся не позже момента решения.
    Пустое или вырожденное окно даёт NaN, а не ноль (замороженный ряд не
    есть «спокойный ряд» — урок S1).
    """
    seg = win[:now_i + 1]
    nan = (float("nan"),) * 3
    if len(seg) < 10:
        return nan
    cl = np.array([b[4] for b in seg], dtype="float64")
    hi = np.array([b[2] for b in seg], dtype="float64")
    lo = np.array([b[3] for b in seg], dtype="float64")
    qv = np.array([b[5] for b in seg], dtype="float64")
    good = cl > 0
    if good.sum() < 10:
        return nan
    cl = cl[good]
    r = np.diff(np.log(cl))
    sigma = float(np.std(r)) * 1e4 if len(r) > 2 else float("nan")
    last = cl[-1]
    rng = ((float(np.max(hi)) - float(np.min(lo[lo > 0]))) / last * 1e4
           if last > 0 and (lo > 0).any() else float("nan"))
    turn = float(np.median(qv)) if len(qv) else float("nan")
    return sigma, rng, turn


def leg_cells(g, bars, ts, look, listed):
    """Один выбор во ВСЕХ ячейках сетки плюс его ex-ante признаки.

    Возвращает (cells, feat, extra, lev_by) либо None, если выбор непригоден
    (нет окна/цены/геометрии) — те же гейты, что в D2, чтобы состав позиций
    совпадал с ним бит в бит. `cells` — словарь (survive, floor) → результат
    `simulate_dca`; `feat` — признаки, известные В МОМЕНТ ВХОДА; `extra` —
    служебное (день, руина); `lev_by` — плечо на каждый множитель забора
    (колонки «плечо» и «доля 1×» отчёта — это и есть механизм, которым
    множитель убирает ликвидации, поэтому оно копится по КАЖДОЙ строке, а не
    только по базовой).
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

    # плечо на каждый множитель забора: считается ОДИН раз на выбор, потому
    # что от пола капитуляции оно не зависит (пол меняет выход, не размер)
    lev_by = {}
    rungs_by = {}
    for sm in GRID_SURVIVE:
        if sm is None:                       # жёсткий 1×: лестница остаётся
            lev_by[sm], rungs_by[sm] = 1.0, rungs_full
            continue
        if len(rungs_full) < 2:              # нет резерва — нет рычага (D2)
            lev_by[sm], rungs_by[sm] = 1.0, [entry]
            continue
        d_max = (entry - rungs_full[-1]) / entry
        lev = L.max_leverage(rungs_full, D2.WEIGHTS[:len(rungs_full)], 1.0,
                             entry, d_max, look, sm)
        if lev <= 0:                         # забор отказал лестнице (D2)
            lev_by[sm], rungs_by[sm] = 1.0, [entry]
        else:
            lev_by[sm], rungs_by[sm] = lev, rungs_full

    cells = {}
    for sm in GRID_SURVIVE:
        lev, rungs = lev_by[sm], rungs_by[sm]
        w = D2.WEIGHTS[:len(rungs)]
        mmr = look(1.0 * lev)
        for fl in GRID_FLOOR:
            cells[(sm, fl)] = L.simulate_dca(hold, rungs, w, 1.0, lev, mmr,
                                             take_px=take_px, floor_frac=fl)

    sigma, rng, turn = window_stats(win, now_i)
    lt = listed.get(g["sym"])
    feat = {
        "fwd_bp": abs(float(g["fwd"])),
        "rr": float(g["rr"]) if g.get("rr") is not None else float("nan"),
        "beta": (float(g["beta"]) if g.get("beta") is not None
                 else float("nan")),
        "lev": lev_by[BASE_CELL[0]],
        "sigma_bp": sigma,
        "range_bp": rng,
        "turnover": turn,
        "n_rungs": float(len(rungs_full)),
        "gap1_bp": ((entry - rungs_full[1]) / entry * 1e4
                    if len(rungs_full) > 1 else float("nan")),
        "age_d": ((g["at"] - lt) / 86400.0 if lt and g["at"] > lt
                  else float("nan")),
        "hour": float(time.gmtime(g["at"]).tm_hour),
    }
    extra = {
        "sym": g["sym"],
        "day": time.strftime("%Y-%m-%d", time.gmtime(g["at"])),
        # руина: ряд имени кончился внутри окна удержания (определение D2)
        "ruin": int(hold[-1][0] < g["at"] + D2.HOLD_H * 3600 - 3600
                    and len(hold) < 30),
    }
    return cells, feat, extra, lev_by


# ------------------------------------------------------------- статистика

def cell_stats(pnl, liq, exits, depth, lev, day):
    p = np.array(pnl, dtype=float)
    if len(p) == 0:
        return {"n": 0}
    win = p[p > 0]
    med_win = float(np.median(win)) if len(win) else float("nan")
    days = sorted(day)
    cur = np.cumsum([day[d] for d in days]) if days else np.array([])
    dd = (float(np.min(cur - np.maximum.accumulate(cur))) if len(cur)
          else 0.0)
    return {
        "n": len(p),
        "liq_freq": round(liq / len(p), 5),
        "median": round(float(np.median(p)), 4),
        "mean": round(float(np.mean(p)), 4),
        "green": round(float(np.mean(p > 0)), 3),
        "worst": round(float(np.min(p)), 3),
        "bite": (round(abs(float(np.min(p))) / med_win, 1)
                 if med_win and med_win > 0 else None),
        "curve_dd": round(dd, 3),
        "median_lev": round(float(np.median(lev)), 2),
        "frac_1x": round(float(np.mean(np.array(lev) <= 1.0 + 1e-9)), 3),
        "avg_depth": round(float(np.mean(depth)), 2),
        "exits": exits,
    }


def _avg_ranks(x):
    """Ранги со СРЕДНИМ на ничьих — иначе признак-константа даёт AUC ≠ 0.5."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x), dtype=float)
    sx = x[order]
    i = 0
    while i < len(sx):
        j = i
        while j + 1 < len(sx) and sx[j + 1] == sx[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def auc(vals, mask):
    """P(значение в группе выше, чем вне) с ничьими по 0.5. NaN не считаются.

    0.5 — признак не разделяет вовсе; 1.0 — у хвоста значения всегда выше.
    Возвращает (auc, n_группы, n_остальных); при пустой группе — NaN.
    """
    v = np.asarray(vals, dtype=float)
    m = np.asarray(mask, dtype=bool)
    ok = ~np.isnan(v)
    v, m = v[ok], m[ok]
    nt, nr = int(m.sum()), int((~m).sum())
    if nt == 0 or nr == 0:
        return float("nan"), nt, nr
    r = _avg_ranks(v)
    u = float(r[m].sum()) - nt * (nt + 1) / 2.0
    return u / (nt * nr), nt, nr


def family_bar(feats, mask, names, perms=NULL_PERM, seed=NULL_SEED):
    """Семейственная планка: 95-й процентиль МАКСИМУМА |AUC−0.5| под нулём.

    Нуль — перестановка меток хвоста при тех же размерах групп. Считать
    планку по одному признаку нельзя: при десяти признаках и 87 хвостовых
    наблюдениях «находка» появляется сама (урок Z1 — планка семейственная).
    """
    rng = np.random.default_rng(seed)
    m = np.asarray(mask, dtype=bool)
    best = []
    for _ in range(perms):
        pm = rng.permutation(m)
        mx = 0.0
        for nm in names:
            a, _nt, _nr = auc(feats[nm], pm)
            if a == a:
                mx = max(mx, abs(a - 0.5))
        best.append(mx)
    b = np.array(best)
    return {"bar95": round(float(np.percentile(b, 95)), 4),
            "bar_mean": round(float(np.mean(b)), 4),
            "perms": perms, "seed": seed}


def avoid_check(pnl, feat, hi_side, q=AVOID_Q):
    """Что даст правило «не открывать дециль признака» — польза И цена.

    `hi_side` — с какой стороны сидит хвост: True, если у хвоста значения
    ВЫШЕ (режем верхний дециль). Позиции с НЕизмеримым признаком остаются:
    правило не может сработать без измерения, и молча выбрасывать их
    значило бы приписать правилу чужую пользу.
    """
    p = np.array(pnl, dtype=float)
    v = np.array(feat, dtype=float)
    ok = ~np.isnan(v)
    if ok.sum() < 20:
        return None
    thr = float(np.quantile(v[ok], 1.0 - q if hi_side else q))
    cut = ok & ((v >= thr) if hi_side else (v <= thr))
    keep = ~cut
    if keep.sum() < 20:
        return None
    a, b = p[keep], p
    return {
        "dropped": int(cut.sum()),
        "unmeasured_kept": int((~ok).sum()),
        "threshold": round(thr, 4),
        "hi_side": bool(hi_side),
        "before": {"n": len(b), "median": round(float(np.median(b)), 4),
                   "mean": round(float(np.mean(b)), 4),
                   "worst": round(float(np.min(b)), 3),
                   "liq_freq": round(float(np.mean(b <= -0.999)), 5),
                   "green": round(float(np.mean(b > 0)), 3)},
        "after": {"n": len(a), "median": round(float(np.median(a)), 4),
                  "mean": round(float(np.mean(a)), 4),
                  "worst": round(float(np.min(a)), 3),
                  "liq_freq": round(float(np.mean(a <= -0.999)), 5),
                  "green": round(float(np.mean(a > 0)), 3)},
    }


def d2_crosscheck(base):
    """Сверка базовой ячейки с ОПУБЛИКОВАННЫМ D2 (рука S).

    Прогон, не воспроизводящий D2 на той же ячейке, описывает другую книгу —
    и обе таблицы при этом выглядят исправными. Нет артефакта D2 — так и
    сказано словом, а не выдано за совпадение.
    """
    p = os.path.join(OUT, "D2-dca-1m.json")
    try:
        with open(p, encoding="utf-8") as f:
            d2 = json.load(f)
    except (OSError, ValueError):
        return {"have": False}
    s = (d2.get("arms") or {}).get("S") or {}
    if not s:
        return {"have": False}
    bad = []
    for k, tol in (("median", 5e-4), ("mean", 5e-4), ("liq_freq", 1e-4),
                   ("worst", 5e-3), ("green", 2e-3)):
        a, b = base.get(k), s.get(k)
        if a is None or b is None or abs(a - b) > tol:
            bad.append({"field": k, "d3": a, "d2": b})
    return {"have": True, "d2_positions": d2.get("positions"),
            "d3_positions": base.get("n"), "mismatch": len(bad),
            "fields": bad}


def base_aliases(sym, inst):
    """Базовый актив символа и его алиасы без множителя лота.

    Справочник несёт `base_coin` точно (`1000000BABYDOGE`), но опционы
    котируются на сам актив (`BABYDOGE`), поэтому числовой множитель лота
    снимается алиасом. Нет справочника — снимаем котируемую валюту строкой.
    """
    rec = inst.get(sym) if isinstance(inst, dict) else None
    b = (rec or {}).get("base_coin") if isinstance(rec, dict) else None
    if not b:
        b = sym
        for suf in ("USDT", "USDC", "PERP"):
            if b.upper().endswith(suf):
                b = b[:-len(suf)]
                break
    b = str(b).upper()
    alts = {b}
    for pre in ("1000000", "100000", "10000", "1000"):
        if b.startswith(pre) and len(b) > len(pre):
            alts.add(b[len(pre):])
    return alts


def options_cover(tail_syms, inst):
    """Доля хвоста в именах, у которых опционы вообще существуют.

    Опцион — единственный выпуклый инструмент: премия мала в обычное время
    и платит в хвосте, то есть у него не возникает арифметики «переплатили
    в 48 раз», которой умерли все три линейных хеджа. Нет инвентаря —
    говорим словом, а не нулём: «не смотрели» и «нет» суть разные ответы.
    """
    try:
        with open(OPTIONS_INV, encoding="utf-8") as f:
            inv = json.load(f)
    except (OSError, ValueError):
        return {"have": False}
    coins = {str(c).upper() for c in (inv.get("base_coins") or [])}
    total = sum(tail_syms.values())
    if not coins:
        return {"have": True, "base_coins": 0, "covered": 0, "total": total,
                "names": [], "asof": inv.get("asof")}
    hit, names = 0, []
    for sym, cnt in tail_syms.items():
        if base_aliases(sym, inst) & coins:
            hit += cnt
            names.append(sym)
    return {"have": True, "base_coins": len(coins), "covered": hit,
            "total": total, "names": sorted(names), "asof": inv.get("asof")}


# ------------------------------------------------------------------ прогон

def run(limit=None, src=None, log=print):
    t0 = time.time()
    tiers_all = D2.instruments_tiers()
    inst = instruments()
    listed = listed_days(inst)
    legs = TNT.legs_from_sheets([D2.SHEETS], log=log)
    longs = [g for g in legs if g["side"] == "long"
             and abs(g["fwd"]) >= D2.MIN_EDGE_BP
             and (g["rr"] or 0) >= D2.MIN_RR]
    log(f"ног всего {len(legs)}, лонгов под гейтом книги {len(longs)}"
        + (f", лимит {limit}" if limit else ""))
    log(f"листингов в справочнике {len(listed)}")
    if limit:
        longs = longs[:limit]

    by_sym = {}
    for g in longs:
        by_sym.setdefault(g["sym"], []).append(g)
    log(f"символов {len(by_sym)}, ячеек сетки "
        f"{len(GRID_SURVIVE)}×{len(GRID_FLOOR)}")

    cellacc = {(sm, fl): {"pnl": [], "liq": 0, "exits": {}, "depth": [],
                          "day": {}}
               for sm in GRID_SURVIVE for fl in GRID_FLOOR}
    levacc = {sm: [] for sm in GRID_SURVIVE}     # плечо на КАЖДЫЙ множитель
    feats = {nm: [] for nm, _t, _u in FEATURES}
    syms, ruins = [], []
    n, skipped, said, done = 0, 0, time.time(), 0
    get = src.bars if src else (lambda s, x, y: SW.read_bars(ROOT_B1, s, x, y))

    for sym, glist in by_sym.items():
        done += 1
        if time.time() - said > 30:
            log(f"  символ {done}/{len(by_sym)}  взято {n}")
            said = time.time()
        a0 = min(gg["at"] for gg in glist) - D2.BACK_H * 3600
        b1 = max(gg["at"] for gg in glist) + D2.HOLD_H * 3600
        bars = get(sym, a0, b1)
        if not bars:
            skipped += len(glist)
            continue
        ts = [bb[0] for bb in bars]
        tiers = tiers_all.get(sym) or []
        look = lambda notl: L.mmr_for_notional(tiers, notl, flat=D2.FLAT_MMR)
        for g in glist:
            rs = leg_cells(g, bars, ts, look, listed)
            if rs is None:
                skipped += 1
                continue
            cells, feat, extra, lev_by = rs
            for key, r in cells.items():
                acc = cellacc[key]
                acc["pnl"].append(r["pnl_frac"])
                acc["liq"] += int(r["exit"] == "ликвидация")
                acc["exits"][r["exit"]] = acc["exits"].get(r["exit"], 0) + 1
                acc["depth"].append(r["depth"])
                acc["day"][extra["day"]] = (acc["day"].get(extra["day"], 0.0)
                                            + r["pnl_frac"])
            for sm, lv in lev_by.items():        # плечо от пола не зависит
                levacc[sm].append(lv)
            for nm, _t, _u in FEATURES:
                feats[nm].append(feat[nm])
            syms.append(extra["sym"])
            ruins.append(extra["ruin"])
            n += 1

    out = {"positions": n, "skipped": skipped,
           "secs": round(time.time() - t0, 1),
           "grid": {"survive": [("1x" if s is None else s)
                                for s in GRID_SURVIVE],
                    "floor": [("нет" if f is None else f)
                              for f in GRID_FLOOR]},
           "params": {"BACK_H": D2.BACK_H, "HOLD_H": D2.HOLD_H,
                      "N_RUNGS": D2.N_RUNGS, "MIN_ADD_GAP": D2.MIN_ADD_GAP,
                      "MIN_EDGE_BP": D2.MIN_EDGE_BP, "MIN_RR": D2.MIN_RR,
                      "TAIL_Q": TAIL_Q, "AVOID_Q": AVOID_Q},
           "cells": {}}
    if not n:
        return out

    for (sm, fl), acc in cellacc.items():
        key = f"{'1x' if sm is None else sm}|{'нет' if fl is None else fl}"
        out["cells"][key] = cell_stats(acc["pnl"], acc["liq"], acc["exits"],
                                       acc["depth"], levacc[sm], acc["day"])
    return finish(out, cellacc, feats, syms, ruins, inst)


def finish(out, cellacc, feats, syms, ruins, inst=None):
    """Хвост, признаки, планка и покрытие опционами — по базовой ячейке."""
    base_acc = cellacc[BASE_CELL]
    p = np.array(base_acc["pnl"], dtype=float)
    n = len(p)
    out["crosscheck_d2"] = d2_crosscheck(out["cells"][
        f"{BASE_CELL[0]}|{BASE_CELL[1]}"])

    k = max(5, int(round(n * TAIL_Q)))
    order = np.argsort(p)
    tail_idx = order[:k]
    mask = np.zeros(n, dtype=bool)
    mask[tail_idx] = True
    liq_mask = p <= -0.999

    tail_syms = {}
    for i in tail_idx:
        tail_syms[syms[i]] = tail_syms.get(syms[i], 0) + 1

    names = [nm for nm, _t, _u in FEATURES]
    bar = family_bar(feats, mask, names)
    rows = []
    for nm, title, unit in FEATURES:
        v = np.array(feats[nm], dtype=float)
        a, nt, nr = auc(v, mask)
        ok = ~np.isnan(v)
        rows.append({
            "key": nm, "title": title, "unit": unit,
            "auc": (round(a, 3) if a == a else None),
            "sep": (round(abs(a - 0.5), 4) if a == a else None),
            "clears": (bool(a == a and abs(a - 0.5) > bar["bar95"])),
            "tail_med": (round(float(np.median(v[mask & ok])), 4)
                         if (mask & ok).any() else None),
            "rest_med": (round(float(np.median(v[(~mask) & ok])), 4)
                         if ((~mask) & ok).any() else None),
            "measured": int(ok.sum()), "tail_n": nt, "rest_n": nr,
        })
    rows.sort(key=lambda r: (r["sep"] is None, -(r["sep"] or 0)))

    out["tail"] = {
        "q": TAIL_Q, "n": int(k),
        "liq_n": int(liq_mask.sum()),
        "tail_worst": round(float(p[tail_idx].min()), 3),
        "tail_cut": round(float(p[tail_idx].max()), 3),
        "tail_cost_pp": round(float(-p[tail_idx].sum()), 1),
        "book_sum_pp": round(float(p.sum()), 1),
        "ruin_share_tail": round(float(np.mean(np.array(ruins)[mask])), 3),
        "ruin_share_rest": round(float(np.mean(np.array(ruins)[~mask])), 3),
        "names": sorted(tail_syms.items(), key=lambda kv: -kv[1])[:25],
        "distinct_names": len(tail_syms),
        "bar": bar, "features": rows,
    }
    # правило избегания — только для признаков, прошедших планку
    avoid = {}
    for r in rows:
        if r["clears"]:
            hi = r["auc"] > 0.5
            res = avoid_check(p, feats[r["key"]], hi)
            if res:
                avoid[r["key"]] = res
    out["tail"]["avoid"] = avoid
    out["options"] = options_cover(tail_syms, inst or {})
    return out


# ------------------------------------------------------------------- отчёт

def _pct(x, digits=2):
    return "—" if x is None else f"{x * 100:+.{digits}f} %"


def report(s):
    P = []
    P.append("# D3 — граница забора, портрет хвоста, покрытие опционами "
             "(спека 14)\n")
    P.append("Диагностика, не вердикт: сетка объявлена в коде ДО прогона, "
             "печатаются ВСЕ ячейки, точку на границе выбирает владелец. "
             "Три задачи считаны одним проходом по тем же выборам модели, "
             "что D2 (лонги под гейтом книги).\n")
    P.append(f"Позиций {s['positions']}, пропущено {s['skipped']}, прогон "
             f"{s['secs']} с.\n")
    if not s["positions"]:
        P.append("**Позиций ноль** — журнала листов нет или баров нет.")
        return "\n".join(P) + "\n"

    cc = s.get("crosscheck_d2") or {}
    if not cc.get("have"):
        P.append("> Сверка с D2 не делалась: артефакта `D2-dca-1m.json` нет "
                 "рядом. Это не совпадение и не расхождение — измерения "
                 "просто не было.\n")
    elif cc.get("mismatch"):
        P.append(f"> ⚠ **Базовая ячейка НЕ воспроизводит руку S из D2**: "
                 f"расхождений {cc['mismatch']} ({cc['fields']}). Значит "
                 f"таблицы описывают другую книгу — числа ниже читать "
                 f"нельзя.\n")
    else:
        P.append(f"> Встроенная сверка: базовая ячейка воспроизводит руку S "
                 f"опубликованного D2 (позиций {cc['d3_positions']} против "
                 f"{cc['d2_positions']}, расхождений 0).\n")

    P.append("## 1. Граница забора: чем платим за «нет ликвидаций»\n")
    P.append("Строка — множитель забора §5 (`SURVIVE_MULT`: ликвидация не "
             "ближе `mult·d_max` от базы), колонка — пол капитуляции §6 "
             "(доля расстояния «вход → ликвидация»; больше — режем раньше). "
             "**Строка `1×` — плечо назначено единицей**: у лонга цена "
             "ликвидации тогда равна нулю, то есть ликвидация невозможна ПО "
             "ПОСТРОЕНИЮ. Состав позиций во всех ячейках один и тот же — "
             "забор не отказывает позиции, а роняет её в 1× (поведение D2), "
             "поэтому ячейки сравнимы парно и отбором не загрязнены.\n")
    P.append("| забор | пол | ликвид. | медиана | среднее | зелёных | "
             "худшая | укус | просадка | плечо | доля 1× | глубина |")
    P.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for sm in s["grid"]["survive"]:
        for fl in s["grid"]["floor"]:
            c = s["cells"].get(f"{sm}|{fl}")
            if not c or not c.get("n"):
                P.append(f"| {sm} | {fl} | — | — | — | — | — | — | — | — | — "
                         "| — |")
                continue
            bite = c["bite"]
            P.append(
                f"| {sm} | {fl} | {c['liq_freq']*100:.2f} % | "
                f"{_pct(c['median'])} | {_pct(c['mean'])} | "
                f"{c['green']*100:.1f} % | {_pct(c['worst'], 1)} | "
                f"{('%.1f' % bite) if bite else '—'} | "
                f"{_pct(c['curve_dd'], 1)} | {c['median_lev']}× | "
                f"{c['frac_1x']*100:.0f} % | {c['avg_depth']} |")
    P.append("")
    P.append("Как читать: **ликвидации убираются двумя разными рычагами, и "
             "путать их нельзя.** Множитель забора снижает плечо (колонка "
             "«плечо»), а на больших множителях ещё и роняет лестницу в "
             "одиночный вход (колонка «доля 1×»: забор отказывает, когда "
             "`mult·d_max ≥ 1`) — то есть строка 6.0 отвечает не только «мало "
             "плеча», но и «лестницы почти нет». Строка `1×` держит лестницу "
             "целиком (глубина не падает) и всё равно не ликвидируется — это "
             "и есть честная цена гарантии.\n")

    t = s["tail"]
    P.append("## 2. Портрет хвоста: что было известно в момент входа\n")
    P.append(f"Хвост — худший {t['q']*100:.0f} % позиций базовой ячейки: "
             f"{t['n']} штук, из них ликвидаций {t['liq_n']}; порог "
             f"{_pct(t['tail_cut'], 1)}, худшая {_pct(t['tail_worst'], 1)}. "
             f"Хвост стоит книге **{t['tail_cost_pp']:.0f} п.п.** при итоге "
             f"книги {t['book_sum_pp']:+.0f} п.п. Имён в хвосте "
             f"{t['distinct_names']}.\n")
    b = t["bar"]
    P.append(f"Планка семейственная: 95-й процентиль МАКСИМУМА |AUC−0.5| под "
             f"нулём (перестановка меток, {b['perms']} повторов, зерно "
             f"{b['seed']}) = **{b['bar95']}** (среднее максимума "
             f"{b['bar_mean']}). Признак ниже планки находкой не является ни "
             f"при каком AUC: при {len(t['features'])} признаках и "
             f"{t['n']} наблюдениях разделение такой силы возникает само.\n")
    P.append("| признак | AUC | |AUC−0.5| | планку | медиана хвоста | "
             "медиана прочих | измерен |")
    P.append("|---|--:|--:|:--:|--:|--:|--:|")
    for r in t["features"]:
        mark = "✓" if r["clears"] else "—"
        P.append(f"| {r['title']} | "
                 f"{('%.3f' % r['auc']) if r['auc'] is not None else '—'} | "
                 f"{('%.4f' % r['sep']) if r['sep'] is not None else '—'} | "
                 f"{mark} | "
                 f"{('%.4g' % r['tail_med']) if r['tail_med'] is not None else '—'} | "
                 f"{('%.4g' % r['rest_med']) if r['rest_med'] is not None else '—'} | "
                 f"{r['measured']} |")
    P.append("")
    P.append(f"Руина (ряд имени кончился внутри удержания — знание из "
             f"будущего, поэтому ПОТОЛОК, а не правило): в хвосте "
             f"{t['ruin_share_tail']*100:.1f} %, у прочих "
             f"{t['ruin_share_rest']*100:.1f} %.\n")
    P.append("**Час входа стоит в таблице канарейкой намеренно**: он не может "
             "нести содержания о риске позиции, и если он разделяет наравне с "
             "остальными — вся таблица есть шум, а не портрет.\n")

    av = t.get("avoid") or {}
    if not av:
        P.append("Планку не прошёл ни один признак — **правила избегания "
                 "нет**: хвост не отличается от остальных позиций ничем, что "
                 "известно в момент входа. Тогда единственный рычаг против "
                 "него — забор (раздел 1), а не отбор.\n")
    else:
        P.append("### Что даст правило «не открывать дециль признака»\n")
        P.append("| признак | режем | ликвид. до → после | худшая до → после "
                 "| медиана до → после | среднее до → после |")
        P.append("|---|--:|--:|--:|--:|--:|")
        for k, r in av.items():
            bf, af = r["before"], r["after"]
            side = "верхний" if r["hi_side"] else "нижний"
            P.append(
                f"| {k} ({side} дециль) | {r['dropped']} | "
                f"{bf['liq_freq']*100:.2f} % → {af['liq_freq']*100:.2f} % | "
                f"{_pct(bf['worst'], 1)} → {_pct(af['worst'], 1)} | "
                f"{_pct(bf['median'])} → {_pct(af['median'])} | "
                f"{_pct(bf['mean'])} → {_pct(af['mean'])} |")
        P.append("\nПравило меряется пользой И ценой: если ликвидации падают, "
                 "а медиана и среднее падают вместе с ними, правило режет "
                 "доход, а не риск. Позиции с НЕизмеримым признаком остаются "
                 "в книге — правило не срабатывает без измерения, и выбросить "
                 "их значило бы приписать ему чужую пользу.\n")

    o = s.get("options") or {}
    P.append("## 3. Опционы: единственный выпуклый инструмент\n")
    P.append("Линейный хедж облагает все позиции ради страховки от "
             "нескольких — это и убило варианты (а), (б), (в). Выпуклый "
             "инструмент (пут) стоит премию и платит только в хвосте, то есть "
             "у него такой арифметики нет. Вопрос один: существуют ли "
             "опционы на те имена, где сидит наш хвост.\n")
    if not o.get("have"):
        P.append("> Инвентаря опционов рядом нет (`a1_universe/out/"
                 "options_inventory.json`) — покрытие НЕ измерялось. Это не "
                 "«опционов нет», а «мы не смотрели»: запустить "
                 "`research/a1_universe/bybit_options.py` на VPS (из "
                 "песочницы площадка закрыта геоблоком).\n")
    else:
        cov = (o["covered"] / o["total"] * 100.0) if o.get("total") else 0.0
        P.append(f"Базовых активов с опционами на площадке: "
                 f"**{o['base_coins']}**. Позиций хвоста в именах, где "
                 f"опционы существуют: **{o['covered']} из {o['total']} "
                 f"({cov:.1f} %)**"
                 + (f"; это {', '.join(o['names'])}" if o.get("names")
                    else "")
                 + ".\n")
        if cov < 5:
            P.append("То есть **хвост опционами не хеджируется в принципе**: "
                     "у площадки опционы только на мажоры, а хвост живёт в "
                     "альтах. Пут на мажор — снова рыночный хедж, а замер (б) "
                     "уже показал, что рынок нашему хвосту не отвечает: хвост "
                     "идиосинкратический, альт валится сам, рынок при этом "
                     "часто растёт.\n")

    P.append("\n**Оговорки (в силе с D2):** веса видели эти часы — оценка "
             "сверху; издержки круга на ногу в pnl не сняты (брутто); "
             "`curve_dd` — сумма долей капитала по позициям без нормировки на "
             "книгу, вердиктом не является; ранняя капитуляция рулевого §6 не "
             "считается — вердикт по «только пол». Портрет хвоста стоит на "
             f"{t['n']} наблюдениях: это выборка для рангового теста, но не "
             "для оценки величины эффекта, и правило по нему объявляется "
             "вперёд, а не подгоняется по этой же таблице.")
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
    with open(os.path.join(OUT, f"D3-fence-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    if s.get("tail", {}).get("names"):
        with open(os.path.join(OUT, f"D3-tail-coins-{tag}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(dict(s["tail"]["names"]), f, ensure_ascii=False,
                      indent=1)
    rep = report(s)
    with open(os.path.join(OUT, f"D3-fence-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    if not a.no_publish:
        publish(f"d3-fence-{tag}")


if __name__ == "__main__":
    main()
