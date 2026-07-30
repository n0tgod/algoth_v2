#!/usr/bin/env python3
"""
Замер сделки на структурных уровнях: лента даёт момент, структура — цену.

Что изменилось против T3 и почему
---------------------------------

В T3 уровень выдумывала лента: полоса равнялась десятой части хода
минутного окна. Итог — медианный стоп **7 базисных пунктов при круге
издержек 11**, доля побед 19 % при безубыточной 52 %, ожидание
отрицательное во всех 24 ячейках, и ровно такое же у нуля. Проигрывало
не событие, а геометрия: стоп сидел внутри обычного шума минутной
свечи, и его выбивало независимо от того, верно ли прочитано событие.

Здесь роли разделены так, как их описывает трейдер:

- **структура задаёт цену** — уровень берётся из полок объёма за сутки,
  экстремумов прошедших суток и круглых чисел (`levels.py`);
- **лента задаёт момент** — событием считается поглощение у этого
  уровня: в него льют, а он держит;
- **шум задаёт стоп** — он ставится за уровень на один медианный ход
  минутной свечи, то есть заведомо снаружи шума. Это исправление
  главного дефекта T3, выраженное числом.

Всё остальное переносится без изменений: проход по секундам с ничьёй
против нас, вход по первой доступной цене, издержки тейкерским кругом,
нуль в случайные моменты того же символа и часа. Ядро сделки не
копируется, а импортируется из `t3_brackets`.

    tools/run.sh "T4: уровни из структуры" research/t4_structure/run.py \\
      --symbols BTCUSDT,ETHUSDT --start 2025-03-03 --end 2025-03-09
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from itertools import product

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, os.path.join(RESEARCH, "t1_tape"))
sys.path.insert(0, os.path.join(RESEARCH, "t3_brackets"))
sys.path.insert(0, HERE)
import brackets as B                                      # noqa: E402
import levels as LV                                       # noqa: E402
import tape as T                                          # noqa: E402

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "LINKUSDT", "ARBUSDT", "AVAXUSDT", "SUIUSDT", "APTUSDT",
           "INJUSDT", "SEIUSDT", "OPUSDT", "NEARUSDT", "ATOMUSDT",
           "FILUSDT")
START = "2025-03-03"
END = "2025-03-09"

STEP_SEC = 1
WINDOW = 60                       # окно поглощения, секунды
VOL_MULTS = (5.0, 10.0)
MOVE_MULT = 0.5
IMB = 0.3
MIN_RRS = (1.5, 2.0, 3.0)
TOUCH_NOISE = 0.5                 # «цена у уровня» — в долях шума
# Ширина стопа в долях шума — ось сетки, а не константа. Смоук показал,
# почему: обычный ход минутной свечи ликвидного перпа сам равен 10–15
# б.п., поэтому стоп «на один шум за уровень» упирается в круг издержек
# 11. Более широкий стоп удешевляет издержки в долях, но уменьшает
# отношение — что перевесит, решают данные, а не я.
STOP_NOISES = (1.0, 2.0, 4.0)
MAX_HOLD_SEC = 4 * 3600           # уровни держат дольше, чем микрополосы
NULLS_PER_EVENT = 1
TAKER_BP = 5.5
MAKER_BP = 2.0


def evaluate(g, i, side, level, stop_px, target_px, min_rr, cost_bp,
             max_hold=None):
    """Собрать сделку у структурного уровня.

    Отличие от `brackets.evaluate` — только источник уровня и стопа;
    проход по секундам, вход и правило ничьей общие, из `t3_brackets`.
    """
    op = g["open"]
    j = i + 1
    while j < len(op) and not np.isfinite(op[j]):
        j += 1
    if j >= len(op):
        return {"skip": "нет цены после события"}
    entry = float(op[j])
    long = side < 0
    if (long and (stop_px >= entry or target_px <= entry)) or \
       (not long and (stop_px <= entry or target_px >= entry)):
        return {"skip": "уровни по разные стороны входа"}
    stop_bp = abs(entry - stop_px) / entry * 1e4
    tgt_bp = abs(target_px - entry) / entry * 1e4
    if stop_bp < 1e-9:
        return {"skip": "стоп нулевой"}
    rr = (tgt_bp - cost_bp) / stop_bp
    if rr < min_rr:
        return {"skip": "отношение мало"}
    res = B.bracket(g, i, side, stop_px, target_px,
                    max_hold or MAX_HOLD_SEC)
    if res is None:
        return {"skip": "нет цены после события"}
    sign = 1.0 if long else -1.0
    gross = sign * (res["exit"] / res["entry"] - 1.0) * 1e4
    res.update({"stop_bp": stop_bp, "target_bp": tgt_bp, "rr": rr,
                "gross_bp": gross, "net_bp": gross - cost_bp,
                "level": level, "stop_px": stop_px, "target_px": target_px,
                "i": int(i), "side": int(side)})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--bundle", default="", help="ячейка для графика: "
                    "объём,мин.отношение (например 5,1.5)")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.tag and not a.tag.startswith("-"):
        a.tag = "-" + a.tag
    os.makedirs(OUT, exist_ok=True)
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    cost = 2 * TAKER_BP
    t_start = time.time()

    def log(m):
        print(f"[{time.time() - t_start:6.0f} с] {m}", file=sys.stderr,
              flush=True)

    want = None
    if a.bundle:
        v = [float(x) for x in a.bundle.split(",")]
        want = (v[0], v[1])
    candles = {}

    cells = list(product(VOL_MULTS, STOP_NOISES, MIN_RRS,
                         ((-1, "поддержка · лонг"),
                          (1, "сопротивление · шорт"))))
    acc = {k: {"trades": [], "null": [], "seen": 0, "skip": {}, "kind": {},
               "stop": []} for k in cells}
    days = T.days_between(a.start, a.end)
    # История для уровней тянется через границу суток: профиль строится
    # по последним 24 часам, а не по календарному дню.
    hist = {}
    for di, day in enumerate(days):
        log(f"  {day}")
        for sym in syms:
            tp = T.load_day(sym, day)
            if tp is None:
                continue
            t_day = datetime.fromisoformat(day).replace(
                tzinfo=timezone.utc).timestamp()
            g = T.to_grid(tp, STEP_SEC, t0=t_day, t1=t_day + 86_400)
            hours = ((g["t"] - t_day) // 3600).astype(np.int64)
            t_m, H, L, P, V = LV.minute_series(g)
            prev = hist.get(sym)
            if prev is not None:
                t_all = np.concatenate([prev["t"], t_m])
                H_all = np.concatenate([prev["H"], H])
                L_all = np.concatenate([prev["L"], L])
                P_all = np.concatenate([prev["P"], P])
                V_all = np.concatenate([prev["V"], V])
                prev_hl = (float(np.nanmax(prev["H"])),
                           float(np.nanmin(prev["L"])))
                off = len(prev["t"])
            else:
                t_all, H_all, L_all = t_m, H, L
                P_all, V_all = P, V
                prev_hl, off = None, 0
            hist[sym] = {"t": t_m, "H": H, "L": L, "P": P, "V": V}
            if want is not None:
                candles.setdefault(sym, {}).update(B.minute_bars(g, t_day))

            # Уровни пересчитываются раз в час: за час структура не
            # меняется, а считать их на каждое событие незачем.
            lv_cache = {}

            def levels_at(sec):
                h = int(sec // 3600)
                if h not in lv_cache:
                    now = off + int(np.searchsorted(t_m, t_day + h * 3600))
                    lv_cache[h] = LV.build(t_all, H_all, L_all, P_all, V_all,
                                           now, prev_hl)
                return lv_cache[h]

            for ci, (mult, stop_k, min_rr, (side, name)) in enumerate(cells):
                key = (mult, stop_k, min_rr, (side, name))
                idx, _ = T.absorption(g, WINDOW, mult, MOVE_MULT, side, IMB)
                d = acc[key]
                d["seen"] += len(idx)
                for i in idx:
                    sec = float(g["t"][i]) - t_day
                    px, kinds, noise = levels_at(sec)
                    if len(px) == 0 or not np.isfinite(noise):
                        d["skip"]["нет истории для уровней"] = \
                            d["skip"].get("нет истории для уровней", 0) + 1
                        continue
                    price = float(g["close"][i])
                    if not np.isfinite(price):
                        continue
                    near = LV.nearest(px, kinds, price, TOUCH_NOISE * noise)
                    if near is None:
                        d["skip"]["не у уровня"] = \
                            d["skip"].get("не у уровня", 0) + 1
                        continue
                    lvl, kind = near
                    long = side < 0
                    stop_px = lvl - stop_k * noise if long \
                        else lvl + stop_k * noise
                    tgt = LV.ahead(px, price, long, stop_k * noise)
                    if tgt is None:
                        d["skip"]["нет уровня впереди"] = \
                            d["skip"].get("нет уровня впереди", 0) + 1
                        continue
                    r = evaluate(g, int(i), side, lvl, stop_px, tgt,
                                 min_rr, cost)
                    if "skip" in r:
                        d["skip"][r["skip"]] = d["skip"].get(r["skip"], 0) + 1
                        continue
                    r["symbol"] = sym
                    r["time"] = T.stamp(g["t"][i])
                    r["kind"] = kind
                    d["trades"].append(r)
                    d["kind"][kind] = d["kind"].get(kind, 0) + 1
                    d["stop"].append(r["stop_bp"])

                    # Нуль: тот же уровень и та же геометрия, но момент
                    # случайный — проверяем чтение ленты, а не уровень.
                    rng = B.rng_for(di, ci, 2)
                    same = np.flatnonzero((hours == hours[i])
                                          & np.isfinite(g["open"]))
                    same = same[np.abs(same - i) > WINDOW]
                    for _ in range(NULLS_PER_EVENT):
                        if len(same) == 0:
                            break
                        jj = int(same[rng.integers(len(same))])
                        p2 = float(g["close"][jj])
                        n2 = LV.nearest(px, kinds, p2, TOUCH_NOISE * noise)
                        if n2 is None:
                            continue
                        l2 = n2[0]
                        s2 = l2 - stop_k * noise if long \
                            else l2 + stop_k * noise
                        t2 = LV.ahead(px, p2, long, stop_k * noise)
                        if t2 is None:
                            continue
                        r2 = evaluate(g, jj, side, l2, s2, t2, min_rr, cost)
                        if "skip" not in r2:
                            d["null"].append(r2)
        log("    " + ", ".join(
            f"×{m:g}/{sk:g}ш/rr{rr:g}{'↑' if s < 0 else '↓'}="
            f"{len(acc[k]['trades'])}"
            for k in cells for (m, sk, rr, (s, _)) in [k]))

    rows = []
    for key in cells:
        mult, stop_k, min_rr, (side, name) = key
        d = acc[key]
        st = B.stats(d["trades"], cost)
        if st is None:
            continue
        nl = B.stats(d["null"], cost)
        rows.append({"vol_mult": mult, "stop_noise": stop_k,
                     "min_rr": min_rr, "side": name,
                     "maker_expectancy_bp":
                         st["expectancy_bp"] + 2 * (TAKER_BP - MAKER_BP),
                     "events": d["seen"],
                     "taken_share": st["trades"] / max(1, d["seen"]),
                     "skip": d["skip"], "kind": d["kind"], **st,
                     "null_expectancy_bp": nl["expectancy_bp"] if nl else None,
                     "null_trades": nl["trades"] if nl else 0})

    cfg = {"symbols": syms, "start": a.start, "end": a.end,
           "window_sec": WINDOW, "vol_mults": list(VOL_MULTS),
           "min_rrs": list(MIN_RRS), "imb": IMB, "cost_bp": cost,
           "touch_noise": TOUCH_NOISE, "stop_noises": list(STOP_NOISES),
           "maker_bp": MAKER_BP,
           "lookback_min": LV.LOOKBACK_MIN, "max_hold_sec": MAX_HOLD_SEC}
    with open(os.path.join(OUT, f"structure{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"config": cfg, "rows": rows}, f, ensure_ascii=False,
                  indent=1)

    if want is not None:
        sel = [k for k in cells if (k[0], k[2]) == want and k[1] == 1.0]
        trades = [t for k in sel for t in acc[k]["trades"]]
        bundle(OUT, a.tag, want, trades, candles, cost, a, log)

    text = report(cfg, rows)
    dst = os.path.join(OUT, f"T4-structure{a.tag}.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    log(f"записано {dst}")


def bundle(out_dir, tag, want, trades, candles, cost, a, log):
    """Выгрузка для графика — тем же форматом, что читает `chart.py`."""
    if not trades:
        log("бэктест: сделок нет, выгружать нечего")
        return
    items = sorted(({"sym": t["symbol"], "t": t["time"], "side": int(t["side"]),
                     "entry": t["entry"], "stop": t["stop_px"],
                     "target": t["target_px"], "exit": t["exit"],
                     "outcome": t["outcome"], "held": int(t["held"]),
                     "rr": round(t["rr"], 2), "net": round(t["net_bp"], 1),
                     "level": t["level"]} for t in trades),
                   key=lambda x: x["t"])
    have = {x["sym"] for x in items}
    ser = {}
    for sym, bars in candles.items():
        if not bars or sym not in have:
            continue
        ts = sorted(bars)
        vals = [v for t in ts for v in bars[t]]
        step = B.tick_of(vals)
        base = min(vals)
        c = [int(round((bars[t][3] - base) / step)) for t in ts]
        dc, prev = [], 0
        for v in c:
            dc.append(v - prev)
            prev = v
        ser[sym] = {"base": round(base, 10), "tick": step, "t0": ts[0],
                    "dt": [(ts[i] - ts[i - 1]) // 60
                           for i in range(1, len(ts))],
                    "dc": dc,
                    "o": [int(round((bars[t][0] - bars[t][3]) / step))
                          for t in ts],
                    "h": [int(round((bars[t][1] - bars[t][3]) / step))
                          for t in ts],
                    "l": [int(round((bars[t][2] - bars[t][3]) / step))
                          for t in ts]}
    path = os.path.join(out_dir, f"backtest{tag}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cell": {"window_sec": WINDOW, "vol_mult": want[0],
                            "conc": 0.0, "min_rr": want[1], "cost_bp": cost,
                            "imb": IMB, "start": a.start, "end": a.end},
                   "series": ser, "trades": items}, f, ensure_ascii=False)
    log(f"бэктест: {len(items)} сделок, {len(ser)} символов, "
        f"{os.path.getsize(path) // 1024} КиБ -> {path}")


def report(cfg, rows):
    md = ["# Замер сделки на структурных уровнях\n",
          f"Символов {len(cfg['symbols'])}, окно {cfg['start']} … "
          f"{cfg['end']}. Круг издержек {cfg['cost_bp']:.0f} б.п. тейкером.\n",
          "**Роли разделены.** Структура задаёт цену: уровень — полка "
          f"объёма за {cfg['lookback_min'] // 60} ч, экстремум прошедших "
          "суток или круглое число. Лента задаёт момент: поглощение у "
          "этого уровня. Шум задаёт стоп: он ставится за уровень на "
          f"{'/'.join(f'{v:g}' for v in cfg['stop_noises'])} медианного "
          "хода минутной свечи, то есть "
          "заведомо снаружи шума.\n",
          "Это прямое исправление дефекта T3, где уровень выдумывала "
          "лента и медианный стоп выходил 7 б.п. при круге издержек 11. "
          "**Смотреть надо на колонку «стоп»:** если он снова окажется "
          "сравним с издержками, дело не в источнике уровня.\n"]
    for name in ("поддержка · лонг", "сопротивление · шорт"):
        md.append(f"\n## {name.capitalize()}\n")
        md.append("| Объём | Стоп | Мин. rr | Событий | Взято | Сделок | "
                  "Стоп, б.п. | Отн. | Побед | Безубыт. | Ожидание | "
                  "Мейкер | Нуль |")
        md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for mult, sk, rr in product(cfg["vol_mults"], cfg["stop_noises"],
                                    cfg["min_rrs"]):
            r = next((x for x in rows if x["vol_mult"] == mult
                      and x["stop_noise"] == sk and x["min_rr"] == rr
                      and x["side"] == name), None)
            if r is None:
                continue
            nul = ("—" if r["null_expectancy_bp"] is None
                   else f"{r['null_expectancy_bp']:+.1f}")
            md.append(
                f"| ×{mult:g} | {sk:g} ш | {rr:g} | {r['events']} | "
                f"{r['taken_share']:.0%} | {r['trades']} | "
                f"{r['stop_bp_median']:.0f} | {r['rr_median']:.1f} | "
                f"{r['win_rate']:.0%} | {r['break_even']:.0%} | "
                f"{r['expectancy_bp']:+.1f} | "
                f"{r['maker_expectancy_bp']:+.1f} | {nul} |")
        md.append("")
    md.append("\n## Откуда уровни и почему события пропускались\n")
    md.append("| Объём | Стоп | Мин. rr | Сторона | Виды уровней | "
              "Пропуски |")
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        if r["stop_noise"] != cfg["stop_noises"][0]:
            continue
        kinds = ", ".join(f"{k}: {v}" for k, v in
                          sorted(r["kind"].items(), key=lambda x: -x[1])) or "—"
        why = ", ".join(f"{k}: {v}" for k, v in
                        sorted(r["skip"].items(), key=lambda x: -x[1])) or "—"
        md.append(f"| ×{r['vol_mult']:g} | {r['stop_noise']:g} ш | "
                  f"{r['min_rr']:g} | {r['side']} | {kinds} | {why} |")
    md.append("")
    md.append("\n## Как читать\n")
    md.append("**Стоп против круга издержек.** Ради этого всё и делалось: "
              "стоп обязан быть кратно больше 11 б.п., иначе комиссия "
              "съедает выигрыш даже при верном направлении.\n")
    md.append("**Ожидание против нуля.** Нуль здесь — тот же уровень и та "
              "же геометрия, но момент случайный. Он проверяет чтение "
              "ленты, а не уровень: если ожидания совпали, лента ни при "
              "чём, работает (или не работает) сама структура.\n")
    md.append("**Столбец «мейкер» — верхняя граница, а не результат.** "
              "Он показывает то же ожидание при круге издержек "
              f"{2 * cfg['maker_bp']:.0f} б.п. вместо "
              f"{cfg['cost_bp']:.0f}, на тех же сделках. Исполнение "
              "лимитной заявкой при этом НЕ предполагается: правило "
              "проекта, и модели очереди у нас нет. Читать как «столько "
              "останется, если исполнение окажется мейкерским», а не как "
              "достигнутое.\n")
    md.append("**Виды уровней.** Если сделки идут только с одного "
              "источника, это надо видеть до того, как усреднять по "
              "всем.\n")
    return "\n".join(md)


if __name__ == "__main__":
    main()
