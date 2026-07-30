#!/usr/bin/env python3
"""
Замер сделки: стоп по уровню, цель по структуре, ожидание как критерий.

Модуль назван `brackets`, а не `probe`, намеренно: `probe.py` в проекте
уже несколько, и импорт подхватывает первый попавшийся в путях. В F3 это
дало подмену модуля без единого признака — здесь имя различает.

**Зонд, а не гипотеза.** Ни объявленной сетки, ни вердикта.

Почему это не повторение T1 и T2
--------------------------------

T1 и T2 мерили среднее и медианное превышение за фиксированный горизонт.
Для конструкции, где риск заведомо меньше прибыли, такая мера
**структурно слепа**: при доле побед 20 % медианная сделка — небольшой
убыток, а ожидание положительное. Мои прошлые замеры оценили бы такую
стратегию нулём, будучи совершенно правыми по своей арифметике и
бессмысленными по существу. Это зеркало ошибки, найденной в carry: там
медиана льстила, а убивал хвост; здесь медиана хоронит то, что в хвосте
живёт.

Поэтому меряется не доходность за горизонт, а **исход сделки**.

Логика сделки
-------------

**Стоп задаёт уровень, а не наш выбор.** У найденной полосы набора есть
толщина; стоп ставится за её край. Прошли уровень насквозь — крупного
там нет либо не было, идея кончилась. Не переставляем, не усредняем
(правила проекта).

**Цель задаёт структура впереди.** Не «×N от стопа», а ближайшая полка
объёма: место, где за предыдущий час много торговали и где цену
вероятно притормозит. Это то, что читают по кластерам глазами.

**Отношение считается, а не назначается.** `(до цели − издержки) / до
стопа`. Вышло 1 к 2 — нормально; вышло 1 к 6 — тоже.

**Сделки может не быть.** Если ближайшая структура впереди слишком
близко и отношение меньше минимально приемлемого, событие пропускается —
и доля пропущенных идёт в отчёт числом. Это правило «не открывать, если
не видно выхода», а не оговорка.

Что здесь честно, а что приближение
-----------------------------------

**Исполнение лимитной заявки не предполагается.** Вход тейкером по
первой цене после закрытия окна. Ошибка движка v1 была ровно в обратном.

**Неоднозначность решается против нас.** Если в одну секунду задеты и
стоп, и цель, засчитывается стоп: порядок внутри секунды нам неизвестен.

**Полка объёма — приближение к «где лучше закрываться».** У владельца
это оценка ситуации; здесь — профиль объёма за час до события. Проверить
приближение можно только глазами, поэтому зонд умеет выгружать события с
полной картинкой (`--dump N`).

**Нуль обязателен и устроен так же.** Тот же бракет в случайные моменты
того же символа и того же часа суток, **с тем же требованием видеть
выход впереди**. Без него «работает чтение ленты» неотличимо от
«работает требование далёкой цели».

    tools/run.sh "T3: замер сделки" research/t3_brackets/brackets.py \\
      --symbols BTCUSDT,ETHUSDT --start 2025-03-03 --end 2025-03-09 --dump 40
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
import tape as T                                          # noqa: E402

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "LINKUSDT", "ARBUSDT", "AVAXUSDT", "SUIUSDT", "APTUSDT",
           "INJUSDT", "SEIUSDT", "OPUSDT", "NEARUSDT", "ATOMUSDT",
           "FILUSDT")
START = "2025-03-03"
END = "2025-03-09"

STEP_SEC = 1
WINDOWS = (60, 300)
VOL_MULTS = (5.0, 10.0)
MOVE_MULT = 0.5
IMB = 0.3
CONCS = (0.4, 0.6)
BANDS = 10
MIN_RRS = (1.5, 2.0, 3.0)         # минимально приемлемое отношение
LOOKBACK_SEC = 3600               # профиль объёма для поиска цели
MAX_HOLD_SEC = 3600               # дольше держать не пробуем
SHELF_Q = 0.80                    # полка — полоса выше этого квантиля
STOP_MIN_BP = 3.0                 # стоп короче — исполнить нечем
NULLS_PER_EVENT = 1

TAKER_BP = 5.5                    # одна сторона
MAKER_BP = 2.0


def bracket(g, i0, side, stop_px, target_px, max_hold_sec):
    """Пройти по секундам вперёд: что задето первым, стоп или цель.

    Вход — открытие следующей секунды после решения (первая цена, по
    которой сделка возможна). Возвращает словарь исхода; если в одну
    секунду задеты оба уровня, засчитывается **стоп** — порядок внутри
    секунды нам неизвестен, и неоднозначность решается против нас.
    """
    op, hi, lo, cl = g["open"], g["high"], g["low"], g["close"]
    n = len(op)
    j = i0 + 1
    while j < n and not np.isfinite(op[j]):
        j += 1                     # секунда без сделок — не наблюдение
    if j >= n:
        return None
    entry = float(op[j])
    steps = int(max_hold_sec / g["step_sec"])
    end = min(n - 1, j + steps)
    long = side < 0                # поглощение продаж -> лонг
    k = j
    last = entry
    while k <= end:
        h, l = hi[k], lo[k]
        if np.isfinite(h):
            last = float(cl[k])
            if long:
                hit_stop = l <= stop_px
                hit_tgt = h >= target_px
            else:
                hit_stop = h >= stop_px
                hit_tgt = l <= target_px
            if hit_stop:
                return {"entry": entry, "exit": float(stop_px),
                        "outcome": "стоп", "held": (k - j) * g["step_sec"]}
            if hit_tgt:
                return {"entry": entry, "exit": float(target_px),
                        "outcome": "цель", "held": (k - j) * g["step_sec"]}
        k += 1
    return {"entry": entry, "exit": last, "outcome": "время",
            "held": (end - j) * g["step_sec"]}


def profile(tape, t_from, t_to, width):
    """Профиль объёма за окно: полосы шириной `width` и их объём."""
    ts, sg, sz, px = tape
    a = int(np.searchsorted(ts, t_from, "left"))
    b = int(np.searchsorted(ts, t_to, "left"))
    if b - a < 10 or width <= 0:
        return None, None
    p = px[a:b]
    q = sz[a:b] * p
    lo = float(p.min())
    k = ((p - lo) / width).astype(np.int64)
    nb = int(k.max()) + 1
    if nb < 3:
        return None, None
    vol = np.bincount(k, weights=q, minlength=nb)
    centers = lo + (np.arange(nb) + 0.5) * width
    return centers, vol


def shelf_ahead(centers, vol, entry, long, q=SHELF_Q):
    """Ближайшая полка объёма впереди — цель.

    Полка: полоса, где объём выше квантиля `q` профиля и не меньше, чем
    у соседей. Берётся **ближайшая**, а не самая крупная: первое
    препятствие на пути и есть то место, где цену притормозит.
    """
    if centers is None:
        return None
    thr = np.quantile(vol[vol > 0], q) if np.any(vol > 0) else 0.0
    big = vol >= thr
    peak = np.zeros(len(vol), dtype=bool)
    peak[1:-1] = (vol[1:-1] >= vol[:-2]) & (vol[1:-1] >= vol[2:])
    cand = centers[big & peak]
    ahead = cand[cand > entry] if long else cand[cand < entry]
    if len(ahead) == 0:
        return None
    return float(ahead.min() if long else ahead.max())


def evaluate(g, tape, i, side, level, width, min_rr, cost_bp,
             lookback_sec=LOOKBACK_SEC):
    """Собрать сделку по событию: стоп, цель, отношение, исход.

    Возвращает `None`, если сделки нет: не нашлось структуры впереди,
    отношение вышло меньше минимального, стоп короче исполнимого.
    """
    t_now = float(g["t"][i]) + g["step_sec"]
    j = i + 1
    op = g["open"]
    while j < len(op) and not np.isfinite(op[j]):
        j += 1
    if j >= len(op):
        return None
    entry = float(op[j])
    long = side < 0
    stop_px = level - width if long else level + width
    stop_bp = abs(entry - stop_px) / entry * 1e4
    if stop_bp < STOP_MIN_BP or (long and stop_px >= entry) or (
            not long and stop_px <= entry):
        return {"skip": "стоп неисполним"}
    centers, vol = profile(tape, t_now - lookback_sec, t_now, width)
    target_px = shelf_ahead(centers, vol, entry, long)
    if target_px is None:
        return {"skip": "нет структуры впереди"}
    tgt_bp = abs(target_px - entry) / entry * 1e4
    rr = (tgt_bp - cost_bp) / stop_bp
    if rr < min_rr:
        return {"skip": "отношение мало"}
    res = bracket(g, i, side, stop_px, target_px, MAX_HOLD_SEC)
    if res is None:
        return {"skip": "нет цены после события"}
    sign = 1.0 if long else -1.0
    gross = sign * (res["exit"] / res["entry"] - 1.0) * 1e4
    res.update({"stop_bp": stop_bp, "target_bp": tgt_bp, "rr": rr,
                "gross_bp": gross, "net_bp": gross - cost_bp,
                "level": level, "stop_px": stop_px, "target_px": target_px,
                "i": int(i), "side": int(side)})
    return res


def rng_for(day_idx, cell_idx, seed):
    """Зерно из чисел, а не из хеша строки.

    Хеш строки в Python солится на каждый процесс: в R3 из-за этого два
    прогона одного кода на одних данных давали разные нули, а комментарий
    рядом утверждал «результат воспроизводим».
    """
    return np.random.default_rng(1_000_003 * seed + 7919 * day_idx
                                 + 31 * cell_idx)


def stats(trades, cost_bp):
    """Сводка по сделкам: ожидание и безубыточная доля побед."""
    if not trades:
        return None
    net = np.array([t["net_bp"] for t in trades])
    rr = np.array([t["rr"] for t in trades])
    win = np.array([t["outcome"] == "цель" for t in trades])
    stop = np.array([t["stop_bp"] for t in trades])
    # Безубыточная доля побед считается по ФАКТИЧЕСКОМУ отношению каждой
    # сделки, а не по номинальному порогу: цель ставит структура.
    be = float(np.mean((stop + cost_bp) / (stop * (1.0 + rr))))
    return {"trades": len(trades),
            "win_rate": float(win.mean()),
            "stop_bp_median": float(np.median(stop)),
            "break_even": be,
            "expectancy_bp": float(net.mean()),
            "median_bp": float(np.median(net)),
            "rr_median": float(np.median(rr)),
            "held_median_sec": float(np.median([t["held"] for t in trades])),
            "share_target": float(np.mean(win)),
            "share_stop": float(np.mean([t["outcome"] == "стоп"
                                         for t in trades])),
            "share_time": float(np.mean([t["outcome"] == "время"
                                         for t in trades]))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--dump", type=int, default=0,
                    help="выгрузить N событий с картинкой для просмотра")
    ap.add_argument("--bundle", default="",
                    help="выгрузить бэктест ячейки для графика: "
                         "окно,объём,сосредоточенность,мин.отношение "
                         "(например 60,5,0.4,1.5)")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.tag and not a.tag.startswith("-"):
        a.tag = "-" + a.tag
    os.makedirs(OUT, exist_ok=True)
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    t0 = time.time()

    def log(m):
        print(f"[{time.time() - t0:6.0f} с] {m}", file=sys.stderr, flush=True)

    cost = 2 * TAKER_BP
    cells = list(product(WINDOWS, VOL_MULTS, CONCS, MIN_RRS,
                         ((-1, "набор под ценой"), (1, "разгрузка над ценой"))))
    acc = {k: {"trades": [], "null": [], "seen": 0, "skip": {}} for k in cells}
    # Выгрузка отбирается равномерно по всему прогону, а не «первые N»:
    # первые тридцать сделок приходятся на первые сутки и два символа,
    # и смотреть глазами пришлось бы один день одного инструмента.
    dump, n_tr = [], 0
    dump_rng = np.random.default_rng(20250303)
    want = None
    if a.bundle:
        v = [float(x) for x in a.bundle.split(",")]
        want = (int(v[0]), v[1], v[2], v[3])
    candles = {}
    days = T.days_between(a.start, a.end)
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
            if want is not None:
                candles.setdefault(sym, {}).update(
                    minute_bars(g, t_day))
            for ci, key in enumerate(cells):
                win, mult, conc_min, min_rr, (side, name) = key
                idx, _ = T.absorption(g, win, mult, MOVE_MULT, side, IMB)
                if len(idx) == 0:
                    continue
                keep, conc, lvl, away, width = T.level_filter(
                    tp, g, idx, win, side, BANDS)
                if len(keep) == 0:
                    continue
                take = conc >= conc_min
                keep, lvl, width = keep[take], lvl[take], width[take]
                d = acc[key]
                d["seen"] += len(keep)
                for i, L, w in zip(keep, lvl, width):
                    r = evaluate(g, tp, int(i), side, float(L), float(w),
                                 min_rr, cost)
                    if r is None or "skip" in r:
                        why = r["skip"] if r else "нет данных"
                        d["skip"][why] = d["skip"].get(why, 0) + 1
                        continue
                    r["symbol"] = sym
                    r["time"] = T.stamp(g["t"][i])
                    d["trades"].append(r)
                    n_tr += 1
                    if a.dump:
                        if len(dump) < a.dump:
                            dump.append(pack(g, tp, r, key, sym, day))
                        else:
                            j = int(dump_rng.integers(n_tr))
                            if j < a.dump:
                                dump[j] = pack(g, tp, r, key, sym, day)
                # Нуль: те же правила, случайный момент того же часа.
                rng = rng_for(di, ci, 1)
                for i, L, w in zip(keep, lvl, width):
                    same = np.flatnonzero((hours == hours[i])
                                          & np.isfinite(g["open"]))
                    same = same[np.abs(same - i) > win]
                    if len(same) == 0:
                        continue
                    for _ in range(NULLS_PER_EVENT):
                        jj = int(same[rng.integers(len(same))])
                        # Уровнем нуля служит цена в этот момент, а
                        # толщиной — та же, что у настоящего события:
                        # иначе сравнивались бы разные размеры стопа.
                        r = evaluate(g, tp, jj, side, float(g["close"][jj]),
                                     float(w), min_rr, cost)
                        if r and "skip" not in r:
                            d["null"].append(r)
        log("    " + ", ".join(
            f"{w}с×{m:g}/{c:g}/rr{rr:g}{'↑' if s < 0 else '↓'}="
            f"{len(acc[k]['trades'])}"
            for k in cells for (w, m, c, rr, (s, _)) in [k]
            if len(acc[k]["trades"])) or "    сделок пока нет")

    rows = []
    for key in cells:
        win, mult, conc_min, min_rr, (side, name) = key
        d = acc[key]
        st = stats(d["trades"], cost)
        if st is None:
            continue
        nl = stats(d["null"], cost)
        rows.append({"window_sec": win, "vol_mult": mult, "conc": conc_min,
                     "min_rr": min_rr, "side": name, "events": d["seen"],
                     "taken_share": st["trades"] / max(1, d["seen"]),
                     "skip": d["skip"], **st,
                     "null_expectancy_bp": nl["expectancy_bp"] if nl else None,
                     "null_win_rate": nl["win_rate"] if nl else None,
                     "null_trades": nl["trades"] if nl else 0})

    if want is not None:
        write_bundle(OUT, a.tag, want, acc, candles, cost, a, log)

    cfg = {"symbols": syms, "start": a.start, "end": a.end,
           "windows": list(WINDOWS), "vol_mults": list(VOL_MULTS),
           "concs": list(CONCS), "min_rrs": list(MIN_RRS), "imb": IMB,
           "bands": BANDS, "lookback_sec": LOOKBACK_SEC,
           "max_hold_sec": MAX_HOLD_SEC, "cost_bp": cost,
           "taker_bp": TAKER_BP, "maker_bp": MAKER_BP}
    with open(os.path.join(OUT, f"brackets{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"config": cfg, "rows": rows}, f, ensure_ascii=False,
                  indent=1)
    if dump:
        with open(os.path.join(OUT, f"events{a.tag}.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"config": cfg, "events": dump}, f, ensure_ascii=False)
        log(f"выгружено событий для просмотра: {len(dump)}")

    text = report(cfg, rows)
    dst = os.path.join(OUT, f"T3-bracket-probe{a.tag}.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    log(f"записано {dst}")


def minute_bars(g, t_day):
    """Секундную сетку суток — в минутные свечи для графика.

    Минута без сделок остаётся пустой, а не повторяет прошлую цену:
    урок A2, бар без сделок — пропуск, а не наблюдение.
    """
    n = 1440
    op = g["open"][:86_400].reshape(n, 60)
    hi = g["high"][:86_400].reshape(n, 60)
    lo = g["low"][:86_400].reshape(n, 60)
    cl = g["close"][:86_400].reshape(n, 60)
    has = np.isfinite(op)
    out = {}
    with np.errstate(invalid="ignore"):
        H = np.nanmax(np.where(has, hi, np.nan), axis=1)
        L = np.nanmin(np.where(has, lo, np.nan), axis=1)
    first = np.argmax(has, axis=1)
    last = 59 - np.argmax(has[:, ::-1], axis=1)
    any_ = has.any(axis=1)
    for m in np.flatnonzero(any_):
        out[int(t_day) + int(m) * 60] = (
            float(op[m, first[m]]), float(H[m]), float(L[m]),
            float(cl[m, last[m]]))
    return out


def write_bundle(out_dir, tag, want, acc, candles, cost, a, log):
    """Бэктест одной ячейки для графика: свечи, сделки, кривая счёта.

    Ячейка задаётся порогами, а СТОРОНЫ объединяются: это одна
    стратегия, где направление задаёт событие — лонг после набора под
    ценой, шорт после разгрузки над ценой.
    """
    win, mult, conc, min_rr = want
    trades = []
    for (w, m, c, rr, (side, name)), d in acc.items():
        if (w, m, c, rr) != (win, mult, conc, min_rr):
            continue
        for t in d["trades"]:
            trades.append({"sym": t["symbol"], "t": t["time"],
                           "side": int(t["side"]), "entry": t["entry"],
                           "stop": t["stop_px"], "target": t["target_px"],
                           "exit": t["exit"], "outcome": t["outcome"],
                           "held": int(t["held"]), "rr": round(t["rr"], 2),
                           "net": round(t["net_bp"], 1),
                           "level": t["level"]})
    trades.sort(key=lambda x: x["t"])
    if not trades:
        log("бэктест: в этой ячейке сделок нет, выгружать нечего")
        return
    # Цены — целыми в шагах цены: файл иначе распухает вчетверо, а
    # разрешение от этого не страдает.
    have = {t["sym"] for t in trades}
    ser = {}
    for sym, bars in candles.items():
        if not bars or sym not in have:
            continue          # символ без сделок в этой ячейке не нужен
        ts = sorted(bars)
        vals = [v for t in ts for v in bars[t]]
        step = tick_of(vals)
        base = min(vals)
        # Закрытие хранится приращением к предыдущему, остальные три цены
        # — смещением от закрытия своей же свечи. Числа выходят
        # однозначными вместо шестизначных, и файл сжимается вчетверо
        # без потери разрешения: шаг цены сохранён точно.
        c = [int(round((bars[t][3] - base) / step)) for t in ts]
        dc, prev = [], 0
        for v in c:
            dc.append(v - prev)
            prev = v
        ser[sym] = {
            "base": round(base, 10), "tick": step, "t0": ts[0],
            "dt": [(ts[i] - ts[i - 1]) // 60 for i in range(1, len(ts))],
            "dc": dc,
            "o": [int(round((bars[t][0] - bars[t][3]) / step)) for t in ts],
            "h": [int(round((bars[t][1] - bars[t][3]) / step)) for t in ts],
            "l": [int(round((bars[t][2] - bars[t][3]) / step)) for t in ts]}
    path = os.path.join(out_dir, f"backtest{tag}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cell": {"window_sec": win, "vol_mult": mult,
                            "conc": conc, "min_rr": min_rr,
                            "cost_bp": cost, "imb": IMB,
                            "start": a.start, "end": a.end},
                   "series": ser, "trades": trades}, f, ensure_ascii=False)
    log(f"бэктест: {len(trades)} сделок, {len(ser)} символов, "
        f"{os.path.getsize(path) // 1024} КиБ -> {path}")


def tick_of(vals):
    """Шаг цены — наименьшее ненулевое различие цен, а не догадка."""
    u = np.unique(np.round(np.asarray(vals, dtype=np.float64), 10))
    d = np.diff(u)
    d = d[d > 0]
    return float(d.min()) if len(d) else 1e-8


def pack(g, tape, r, key, sym, day):
    """Событие с картинкой: кластер, дельта, путь цены, уровни сделки."""
    win = key[0]
    i = r["i"]
    a0 = max(0, i - win - 120)
    a1 = min(len(g["t"]) - 1, i + 1)
    ts, sg, sz, px = tape
    t_from, t_to = float(g["t"][a0]), float(g["t"][a1]) + 1
    k0 = int(np.searchsorted(ts, t_from, "left"))
    k1 = int(np.searchsorted(ts, t_to, "left"))
    p = px[k0:k1]
    if len(p) == 0:
        return None
    lo, hi = float(p.min()), float(p.max())
    nb = 30
    w = max((hi - lo) / nb, 1e-12)
    band = np.clip(((p - lo) / w).astype(np.int64), 0, nb - 1)
    sec = np.clip(((ts[k0:k1] - t_from)).astype(np.int64), 0, a1 - a0)
    q = sz[k0:k1] * p
    buy = np.zeros((nb, a1 - a0 + 1))
    sell = np.zeros((nb, a1 - a0 + 1))
    m = sg[k0:k1] > 0
    np.add.at(buy, (band[m], sec[m]), q[m])
    np.add.at(sell, (band[~m], sec[~m]), q[~m])
    # Путь после входа — по пять секунд, иначе выгрузка распухает.
    fwd0 = i + 1
    fwd1 = min(len(g["t"]) - 1, fwd0 + int(r["held"]) + 60)
    step = 5
    idx = np.arange(fwd0, fwd1 + 1, step)
    path = [[float(g["t"][j]), None if not np.isfinite(g["close"][j])
             else round(float(g["close"][j]), 8)] for j in idx]
    return {"symbol": sym, "day": day, "time": r["time"],
            "side": r["side"], "window_sec": win, "vol_mult": key[1],
            "conc": key[2], "min_rr": key[3],
            "t_from": t_from, "price_lo": lo, "price_hi": hi, "bands": nb,
            "buy": [[int(v) for v in row] for row in buy.tolist()],
            "sell": [[int(v) for v in row] for row in sell.tolist()],
            "level": r["level"], "entry": r["entry"],
            "stop": r["stop_px"], "target": r["target_px"],
            "outcome": r["outcome"], "held": r["held"], "rr": r["rr"],
            "net_bp": r["net_bp"], "path": path}


def report(cfg, rows):
    md = ["# Замер сделки: стоп по уровню, цель по структуре\n",
          f"Символов {len(cfg['symbols'])}, окно {cfg['start']} … "
          f"{cfg['end']}. Круг издержек {cfg['cost_bp']:.0f} б.п. "
          f"(тейкер в обе стороны — исполнение лимитом не "
          f"предполагается).\n",
          "**Мерится исход сделки, а не доходность за горизонт.** Стоп "
          "ставится за край полосы набора, цель — на ближайшей полке "
          "объёма за предыдущий час, отношение считается, а не "
          "назначается. Событие без выхода впереди пропускается — доля "
          "взятых стоит отдельной колонкой.\n",
          "Решает **ожидание**: сравнивать долю побед надо не с половиной, "
          "а с безубыточной долей для фактического отношения. И рядом — "
          "нуль: тот же бракет в случайные моменты того же символа и "
          "часа, с тем же требованием видеть выход.\n"]
    for name in ("набор под ценой", "разгрузка над ценой"):
        md.append(f"\n## {name.capitalize()}\n")
        md.append("| Окно | Объём | Сосред. | Мин. rr | Событий | Взято | "
                  "Сделок | Отн. | Побед | Безубыт. | Ожидание | Нуль |")
        md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for win, mult, cc, rr in product(cfg["windows"], cfg["vol_mults"],
                                         cfg["concs"], cfg["min_rrs"]):
            r = next((x for x in rows if x["window_sec"] == win
                      and x["vol_mult"] == mult and x["conc"] == cc
                      and x["min_rr"] == rr and x["side"] == name), None)
            if r is None:
                continue
            nul = ("—" if r["null_expectancy_bp"] is None
                   else f"{r['null_expectancy_bp']:+.1f}")
            md.append(
                f"| {win} с | ×{mult:g} | {cc:g} | {rr:g} | {r['events']} | "
                f"{r['taken_share']:.0%} | {r['trades']} | "
                f"{r['stop_bp_median']:.0f} б.п. | "
                f"{r['rr_median']:.1f} | {r['win_rate']:.0%} | "
                f"{r['break_even']:.0%} | {r['expectancy_bp']:+.1f} б.п. | "
                f"{nul} |")
        md.append("")
    md.append("\n## Исходы и пропуски\n")
    md.append("| Окно | Объём | Сосред. | Мин. rr | Сторона | Цель | Стоп | "
              "Время | Держали | Почему пропущено |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        why = ", ".join(f"{k}: {v}" for k, v in
                        sorted(r["skip"].items(), key=lambda x: -x[1])) or "—"
        md.append(f"| {r['window_sec']} с | ×{r['vol_mult']:g} | "
                  f"{r['conc']:g} | {r['min_rr']:g} | {r['side']} | "
                  f"{r['share_target']:.0%} | {r['share_stop']:.0%} | "
                  f"{r['share_time']:.0%} | {r['held_median_sec']:.0f} с | "
                  f"{why} |")
    md.append("")
    md.append("\n## Как читать\n")
    md.append("**Ожидание — единственный критерий.** Доля побед сама по "
              "себе ничего не значит: при отношении 1 к 3 достаточно "
              "тридцати процентов, при 1 к 1 не хватит и половины. "
              "Сравнивать её надо с колонкой «безубыт.».\n")
    md.append("**Нуль решает, что именно работает.** Если ожидание нуля "
              "такое же, значит работает бракет с далёкой целью, а не "
              "чтение ленты, и событие ни при чём.\n")
    md.append("**Доля взятых** — то самое «не открывать, если не видно "
              "выхода». Низкая доля не порок: она означает, что правило "
              "отбирает.\n")
    md.append("**Стоп в единицы базисных пунктов** — уровень тоньше "
              "спреда, и такую позицию выбьет шумом независимо от того, "
              "верно ли прочитан набор. Сравнивать надо с кругом издержек: "
              "стоп меньше него означает, что комиссия съедает половину "
              "выигрыша даже при верном направлении.\n")
    md.append("**Исход «время»** — вышли по истечении часа, не задев ни "
              "стопа, ни цели. Много таких означает, что цель поставлена "
              "слишком далеко для этого события.\n")
    return "\n".join(md)


if __name__ == "__main__":
    main()
