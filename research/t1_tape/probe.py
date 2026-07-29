#!/usr/bin/env python3
"""
Зонд: зарабатывает ли поглощение в ленте.

**Зонд, а не гипотеза.** Ни объявленной сетки, ни порогов-критериев, ни
вердикта. Задача — увидеть числа на малом срезе и решить, стоит ли
писать спеку.

Что проверяется
---------------

Поглощение: за окно в несколько секунд в стакан льют агрессивный объём
многократно выше обычного, **а цена не идёт**. Значит с другой стороны
стоит крупный лимитник и набирает позицию. Ожидание — цена пойдёт в его
сторону. Это то, что читают глазами по ленте и кластерам; здесь оно
считается числом.

Три вещи, без которых замер бессмыслен
--------------------------------------

**1. Контроль одновременной кросс-секцией.** Главный урок L3: из сорока
трёх базисных пунктов сырого отскока после каскада сорок принадлежали
рынку, а не активу. Поэтому берётся сразу несколько символов, и
превышение считается над медианой тех, у кого в этот момент события не
было. На одном символе такого контроля не построить вовсе.

**2. Издержки в тех же единицах.** Тейкерский круг на Bybit — 11 б.п.
(5.5 в каждую сторону), мейкерский — 4 б.п. (2.0). Поглощение
естественно торгуется мейкером: заявка встаёт рядом с поглощающим. Но
мейкерское исполнение в этом проекте требует модели очереди, поэтому
докладываются оба круга, а вывод делается по тейкерскому — он
достижим наверняка.

**3. Ход против позиции.** Считается по минимумам и максимумам ячеек:
без него нельзя сказать, где обязан стоять ограничитель убытка и сколько
он будет стоить. Зонд возврата показал, что ход против бывает в десять
раз больше эджа — и это убивает конструкцию вернее, чем слабый сигнал.

Порядок работы: начинаем с малого среза, расширяем добавлением суток.

    .venv/bin/python research/t1_tape/probe.py
    .venv/bin/python research/t1_tape/probe.py --start 2025-03-01 --end 2025-03-31
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
import events as E                                        # noqa: E402
import tape as T                                          # noqa: E402

# Ликвидные перпы Bybit разного размера. Кросс-секция должна быть шире
# одного имени, иначе контроля 1 не существует.
SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "LINKUSDT",
           "ARBUSDT")
START = "2025-03-06"
END = "2025-03-10"

STEP_SEC = 1                      # шаг сетки
WINDOWS = (10, 30)                # окно поглощения, секунды
VOL_MULTS = (5.0, 10.0)           # во сколько раз объём выше обычного
MOVE_MULT = 0.5                   # цена ушла не больше половины обычного хода
HORIZONS = (5, 10, 30, 60, 300)   # горизонты удержания, секунды
# Слипание событий разных символов. На непрерывном сигнале длинное
# окно вырождается: события суток схлопываются в один эпизод, и
# мера независимости перестаёт что-либо мерить. Берётся кратным
# окну обнаружения, а не «по-крупному».
EPISODE_SEC = 300
# Защитное окно кросс-секции: сосед, у которого событие рядом по
# времени, в фон не входит. Величина НЕ константа, а `max(окно
# обнаружения, горизонт)` — загрязняет фон ровно то событие, чей
# форвард накрывает наш замер. Плоские 300 с на секундной сетке
# запрещали 76–81 % ячеек и оставляли с контролем 1 % событий; на
# непрерывном сигнале это то же вырождение, что убило слипание в
# эпизоды у зонда возврата.
MIN_CROSS = 3                     # символов в кросс-секции минимум
# Доля символов, требуемая в фоне. Держится НИЗКОЙ намеренно. Строгое
# требование (половина) выбрасывает ровно те моменты, когда поглощают
# многие сразу, то есть отбирает события по состоянию рынка — смещение,
# которого в результате не видно. Слабое требование оставляет фон узким
# и шумным, а шум виден: он расходит ячейки, а не двигает их в одну
# сторону. Ширина фона поэтому докладывается числом.
MIN_CROSS_SHARE = 0.2

TAKER_ROUND_BP = 11.0             # 5.5 в каждую сторону
MAKER_ROUND_BP = 4.0              # 2.0 в каждую сторону


def cross(P, cols, rows, horizon_sec, banned, guard_sec, min_cross,
          step_sec=STEP_SEC):
    """Контроль 1 через общую функцию L3.

    Функция `E.cross_section` работает в **единицах сетки**: она делит
    горизонт на шаг, и какая это единица — минуты или секунды — ей
    безразлично, лишь бы обе величины были в одной. Здесь передаются
    секунды. Второй копии кросс-секции в проекте не заводится.
    """
    return E.cross_section(P, cols, rows, horizon_sec,
                           guard_min=guard_sec, step_min=step_sec,
                           banned=banned, min_cross=min_cross)


def day_matrix(symbols, day, step_sec, log):
    """Ленты всех символов за сутки на общей сетке.

    Возвращает `(времена, close, high, low, гриды)`. Символ без ленты
    просто отсутствует в списке — это не ошибка, а факт архива.
    """
    t0 = datetime.fromisoformat(day).replace(
        tzinfo=timezone.utc).timestamp()
    t1 = t0 + 86_400
    n = int(86_400 / step_sec)
    have, grids = [], {}
    for sym in symbols:
        tp = T.load_day(sym, day)
        if tp is None:
            log(f"    {sym}: ленты нет")
            continue
        g = T.to_grid(tp, step_sec, t0=t0, t1=t1)
        if len(g["t"]) != n:
            g = {k: (v[:n] if isinstance(v, np.ndarray) else v)
                 for k, v in g.items()}
        grids[sym] = g
        have.append(sym)
        log(f"    {sym}: принтов {len(tp[0]):,}, "
            f"ячеек со сделками {int((g['prints'] > 0).sum()):,}")
    if not have:
        return None
    C = np.full((len(have), n), np.nan, dtype=np.float64)
    H = np.full((len(have), n), np.nan, dtype=np.float64)
    L = np.full((len(have), n), np.nan, dtype=np.float64)
    for r, sym in enumerate(have):
        g = grids[sym]
        C[r, :len(g["close"])] = g["close"]
        H[r, :len(g["high"])] = g["high"]
        L[r, :len(g["low"])] = g["low"]
    # Цена в ячейке без сделок — последняя известная: для форварда нужна
    # цена, по которой можно выйти, а её отсутствие означает лишь, что
    # сделок в эту секунду не было. Для ОБНАРУЖЕНИЯ используются сырые
    # ячейки, там перенос запрещён.
    C_ff = forward_fill(C)
    times = t0 + np.arange(n) * step_sec
    return times, C, C_ff, H, L, grids, have


def forward_fill(M):
    """Перенос последней известной цены вперёд по каждой строке."""
    out = M.copy()
    n = out.shape[1]
    for r in range(out.shape[0]):
        row = out[r]
        idx = np.flatnonzero(np.isfinite(row))
        if len(idx) == 0:
            continue
        pos = np.searchsorted(idx, np.arange(n), "right") - 1
        ok = pos >= 0
        out[r, ok] = row[idx[pos[ok]]]
    return out


def episodes_of(times, cols):
    return E.episodes(times[cols], gap_sec=EPISODE_SEC)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--step-sec", type=int, default=STEP_SEC)
    # Смоук пишется под своим именем и в git не идёт: коммит F2 однажды
    # уже подменил артефакт настоящего прогона смоуковым, и отличить их
    # по содержимому нельзя — оба выглядят как отчёт этапа.
    ap.add_argument("--tag", default="",
                    help="суффикс артефактов, например -smoke")
    a = ap.parse_args()
    if a.tag and not a.tag.startswith("-"):
        a.tag = "-" + a.tag
    os.makedirs(OUT, exist_ok=True)
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    t_start = time.time()

    def log(m):
        print(f"[{time.time() - t_start:6.0f} с] {m}", file=sys.stderr,
              flush=True)

    acc = {}
    days = T.days_between(a.start, a.end)
    log(f"символов {len(syms)}, суток {len(days)}, шаг {a.step_sec} с")
    for day in days:
        log(f"  {day}")
        got = day_matrix(syms, day, a.step_sec, log)
        if got is None:
            continue
        times, C_raw, C, H, L, grids, have = got
        for win in WINDOWS:
            for mult in VOL_MULTS:
                for side, name in ((-1, "поглощение продаж"),
                                   (1, "поглощение покупок")):
                    rows, cols = [], []
                    for r, sym in enumerate(have):
                        idx, _ = T.absorption(grids[sym], win, mult,
                                              MOVE_MULT, side)
                        rows += [r] * len(idx)
                        cols += list(idx)
                    if not cols:
                        continue
                    rows = np.array(rows, dtype=np.int64)
                    cols = np.array(cols, dtype=np.int64)
                    ep = episodes_of(times, cols)
                    # Фон обязан быть шире одного соседа: медиана по двум
                    # именам не оценивает движение рынка, а повторяет его
                    # случайную половину.
                    min_cross = max(MIN_CROSS,
                                    int(round(MIN_CROSS_SHARE * len(have))))
                    bans = {}
                    for h in HORIZONS:
                        k = cols + h // a.step_sec
                        fit = k < C.shape[1]
                        with np.errstate(invalid="ignore", divide="ignore"):
                            f = np.where(fit, C[rows, np.clip(
                                k, 0, C.shape[1] - 1)] / C[rows, cols] - 1.0,
                                np.nan)
                        # Знак приводится к «в пользу поглощающего»:
                        # поглощение продаж ждёт роста, покупок — падения.
                        f = f * (1 if side < 0 else -1)
                        guard = max(win, h)
                        if guard not in bans:
                            bans[guard] = E.ban_matrix(
                                C.shape, rows, cols, guard_min=guard,
                                step_min=a.step_sec)
                        cs = cross(C, cols, rows, h, bans[guard], guard,
                                   min_cross, a.step_sec) * (
                            1 if side < 0 else -1)
                        exc = np.where(np.isfinite(cs) & np.isfinite(f),
                                       f - cs, np.nan)
                        wid = cross_width(C, bans[guard], cols,
                                          h // a.step_sec)
                        mae, mfe = excursion(C, H, L, rows, cols,
                                             h // a.step_sec, side)
                        key = (win, mult, name, h)
                        d = acc.setdefault(key, {"exc": [], "ep": [],
                                                 "mae": [], "mfe": [],
                                                 "n": 0, "with_cross": 0,
                                                 "wid": [],
                                                 "guard": guard,
                                                 "min_cross": min_cross})
                        d["exc"].append(exc)
                        d["ep"].append(ep + 10**7 * len(d["ep"]))
                        d["mae"].append(mae)
                        d["mfe"].append(mfe)
                        d["wid"].append(wid)
                        d["n"] += len(cols)
                        d["with_cross"] += int(np.isfinite(exc).sum())
        del C, C_raw, H, L, grids

    rows_out = []
    for (win, mult, name, h), v in sorted(acc.items(), key=lambda x: str(x[0])):
        exc = np.concatenate(v["exc"])
        ep = np.concatenate(v["ep"])
        e = E.by_episode(exc, ep)
        mae = np.concatenate(v["mae"])
        mfe = np.concatenate(v["mfe"])
        mae = mae[np.isfinite(mae)]
        mfe = mfe[np.isfinite(mfe)]
        if len(e) < 5:
            continue
        rows_out.append({
            "window_sec": win, "vol_mult": mult, "side": name,
            "horizon_sec": h, "events": int(v["n"]), "episodes": int(len(e)),
            "with_cross": int(v["with_cross"]),
            "cross_cover": float(v["with_cross"]) / max(1, v["n"]),
            "cross_width": float(np.median(np.concatenate(v["wid"]))),
            "guard_sec": int(v["guard"]), "min_cross": int(v["min_cross"]),
            "excess_bp": float(np.median(e)) * 1e4,
            "share_pos": float(np.mean(e > 0)),
            "mae_bp": float(np.median(mae)) * 1e4 if len(mae) else None,
            "mfe_bp": float(np.median(mfe)) * 1e4 if len(mfe) else None,
        })

    with open(os.path.join(OUT, f"tape_probe{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"config": {"symbols": syms, "start": a.start,
                              "end": a.end, "step_sec": a.step_sec,
                              "windows": list(WINDOWS),
                              "vol_mults": list(VOL_MULTS),
                              "move_mult": MOVE_MULT,
                              "horizons_sec": list(HORIZONS),
                              "episode_sec": EPISODE_SEC,
                              "min_cross_share": MIN_CROSS_SHARE},
                   "rows": rows_out}, f, ensure_ascii=False, indent=1)

    md = ["# Зонд: поглощение в ленте\n",
          f"Символов {len(syms)}, окно {a.start} … {a.end}, сетка "
          f"{a.step_sec} с. Поглощение — агрессивный объём выше обычного "
          f"в заданное число раз при движении цены не более "
          f"{MOVE_MULT:g} обычного хода за то же окно.\n",
          "Все величины — **превышение над одновременной кросс-секцией**, "
          "по эпизодам, знак приведён к «в пользу поглощающего». "
          f"Сравнивать с кругом издержек: тейкер **{TAKER_ROUND_BP:.0f} "
          f"б.п.**, мейкер {MAKER_ROUND_BP:.0f}.\n",
          "Фон берётся из соседей, у которых в это время события не было; "
          "защитное окно равно `max(окно, горизонт)`. Колонки «с "
          "контролем» (доля событий, которым фон удалось построить) и "
          "«имён в фоне» (медианная его ширина) — цена контроля, и "
          "читать их надо раньше величин: узкий фон означает шумную "
          "оценку, низкое покрытие — отбор событий по состоянию рынка.\n"]
    for name in ("поглощение продаж", "поглощение покупок"):
        md.append(f"\n## {name.capitalize()}\n")
        md.append("| Окно | Объём | Событий | Эпизодов | С контролем | "
                  "Имён в фоне | "
                  + " | ".join(f"{h} с" for h in HORIZONS) + " |")
        md.append("|---" * (len(HORIZONS) + 6) + "|")
        for win in WINDOWS:
            for mult in VOL_MULTS:
                cells, eps, ev, cov, wid = [], 0, 0, [], []
                for h in HORIZONS:
                    r = next((x for x in rows_out
                              if x["window_sec"] == win
                              and x["vol_mult"] == mult
                              and x["side"] == name
                              and x["horizon_sec"] == h), None)
                    cells.append(f"{r['excess_bp']:+.1f}" if r else "—")
                    eps = max(eps, r["episodes"] if r else 0)
                    ev = max(ev, r["events"] if r else 0)
                    if r:
                        cov.append(r["cross_cover"])
                        wid.append(r["cross_width"])
                c = f"{min(cov):.0%}–{max(cov):.0%}" if cov else "—"
                w = f"{min(wid):.0f}–{max(wid):.0f}" if wid else "—"
                md.append(f"| {win} с | ×{mult:g} | {ev} | {eps} | {c} | "
                          f"{w} | " + " | ".join(cells) + " |")
        md.append("")
    md.append("\n## Ход против позиции и в её пользу\n")
    md.append("| Окно | Объём | Сторона | Горизонт | Против | В пользу |")
    md.append("|---|---|---|---|---|---|")
    for r in rows_out:
        if r["mae_bp"] is None:
            continue
        md.append(f"| {r['window_sec']} с | ×{r['vol_mult']:g} | "
                  f"{r['side']} | {r['horizon_sec']} с | "
                  f"{r['mae_bp']:+.0f} б.п. | {r['mfe_bp']:+.0f} б.п. |")
    md.append("")
    md.append("\n## Как читать\n")
    md.append("**Превышение ниже круга издержек** — сигнал есть, торговать "
              "нечем. Именно так закрылись каскады: 11.4 б.п. против "
              "11.7 круга.\n")
    md.append("**Ход против больше превышения в разы** — ограничитель "
              "убытка не спасёт: стоп, который что-то ограничивает, "
              "срабатывает на медианной сделке.\n")
    md.append("**Эпизодов мало** — на малом срезе это ожидаемо, и вывод "
              "делать рано; расширяется добавлением **символов**, а не "
              "суток: фон строится по одновременным соседям, и связывает "
              "их число.\n")
    md.append("**Событий на эпизод много** — слипание вырождено, сигнал "
              "почти непрерывен, и число эпизодов перестаёт быть мерой "
              "независимости. Так вело себя падение на 2 % в зонде "
              "возврата.\n")
    text = "\n".join(md)
    dst = os.path.join(OUT, f"T1-tape-probe{a.tag}.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    log(f"записано {dst}")


def cross_width(C, banned, cols, steps_h):
    """Сколько символов оказалось в фоне на каждом событии.

    Ширина фона — качество контроля, и её надо видеть числом: медиана
    по трём именам оценивает движение рынка много хуже медианы по
    двадцати, а в самой величине превышения это никак не проявляется.
    """
    n = C.shape[1]
    j = np.asarray(cols, dtype=np.int64)
    k = np.clip(j + steps_h, 0, n - 1)
    ok = (~banned[:, j]) & np.isfinite(C[:, j]) & np.isfinite(C[:, k])
    return ok.sum(axis=0).astype(np.float64)


def excursion(C, H, L, rows, cols, steps_h, side):
    """Ход против позиции и в её пользу за горизонт, по краям ячеек."""
    n = C.shape[1]
    entry = C[rows, cols]
    run_lo = np.full(len(cols), np.inf)
    run_hi = np.full(len(cols), -np.inf)
    for k in range(0, steps_h + 1):
        j = np.clip(cols + k, 0, n - 1)
        fit = (cols + k) < n
        run_lo = np.fmin(run_lo, np.where(fit, L[rows, j], np.nan))
        run_hi = np.fmax(run_hi, np.where(fit, H[rows, j], np.nan))
    with np.errstate(invalid="ignore", divide="ignore"):
        lo = run_lo / entry - 1.0
        hi = run_hi / entry - 1.0
    # Для поглощения продаж «против» — вниз; для покупок — вверх.
    return (lo, hi) if side < 0 else (-hi, -lo)


if __name__ == "__main__":
    main()
