#!/usr/bin/env python3
"""
L3 — события, эпизоды, нули и контроли. Единственный дорогой проход.

Спека 06, раздел 10. Отсюда выходят векторы, из которых L4 и L5
считаются пересчётом за секунды — тот же приём, что дал полтора десятка
замеров в F1–F3 и S1.

**Вердикт выносится только на подтверждающей части универсума.**
Двенадцать активов зонда L1 считаются отдельно и докладываются справкой:
на них выбраны пороги, и вердикт по ним был бы выбором, выданным за
предсказание (§4 спеки).

Порядок в отчёте не случаен. Сначала два контроля, потом всё остальное:
контроль 2 — самый вероятный убийца гипотезы, и стоять он должен перед
дорогой частью, а не после. Урок A4, где перестановочный тест обесценил
результат месячного прогона.

    .venv/bin/python research/l3_events/run.py
    .venv/bin/python research/l3_events/run.py --limit 40    # пилот
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
import data as D                                          # noqa: E402
import events as E                                        # noqa: E402

# Объявлено спекой §5.1 и §6, перебору не подлежит.
OI_DROP = 0.01
MOVE = 0.03
HORIZONS = (15, 60, 240)          # вердикт
DIAGNOSTIC = (5, 1440)            # справка
MIN_OI_USD = 5_000_000            # §7.3
NULL_SEEDS = 10


def stamp(sec):
    return datetime.fromtimestamp(int(sec), timezone.utc).isoformat()


def scan_symbols(symbols, times, P, uni, share, min_share, log):
    """Отбор событий по всем символам. Возвращает векторы."""
    hours = np.array([datetime.fromtimestamp(int(t), timezone.utc).hour
                      for t in times], dtype=np.int8)
    rec = {k: [] for k in ("row", "col", "sym", "oi_change", "price_change",
                           "oi_usd", "arm")}
    valid_by_row = {}
    for r, sym in enumerate(symbols):
        oi_c, oi_u = D.oi_series(sym, times)
        if oi_c is None:
            continue
        px = P[r]
        ok = (np.isfinite(px) & np.isfinite(oi_c) & np.isfinite(oi_u)
              & (oi_u >= MIN_OI_USD)
              & D.delist_mask(sym, times, uni)
              & D.liquidity_mask(sym, times, share, min_share))
        if not ok.any():
            continue
        valid_by_row[r] = ok
        w = E.steps(E.WINDOW_MIN)
        for arm, need_oi in (("event", True), ("control2", False)):
            idx = E.detect(oi_c, px, ok, OI_DROP, MOVE, require_oi=need_oi)
            for j in idx:
                rec["row"].append(r)
                rec["col"].append(int(j))
                rec["sym"].append(sym)
                rec["oi_change"].append(float(oi_c[j] / oi_c[j - w] - 1.0))
                rec["price_change"].append(float(px[j] / px[j - w] - 1.0))
                rec["oi_usd"].append(float(oi_u[j]))
                rec["arm"].append(arm)
        if (r + 1) % 50 == 0:
            log(f"  просмотрено {r + 1} из {len(symbols)}, "
                f"событий {sum(1 for a in rec['arm'] if a == 'event')}")
    out = {k: np.array(v) for k, v in rec.items()}
    return out, valid_by_row, hours


def measure(rec, arm, times, P, valid_by_row, hours, log):
    """Форварды, эпизоды, контроль 1 и оба нуля для одной руки."""
    m = rec["arm"] == arm
    rows, cols = rec["row"][m].astype(int), rec["col"][m].astype(int)
    if len(cols) == 0:
        return None
    ep = E.episodes(times[cols])
    res = {"events": int(len(cols)), "episodes": int(len(np.unique(ep)))}
    n = len(times)

    for h in HORIZONS + DIAGNOSTIC:
        # Векторно по матрице: поэлементный цикл на десятках тысяч
        # событий стоил бы минут, а даёт то же самое.
        k = cols + E.steps(h)
        good = k < P.shape[1]
        with np.errstate(invalid="ignore", divide="ignore"):
            f = np.where(good,
                         P[rows, np.clip(k, 0, P.shape[1] - 1)]
                         / P[rows, cols] - 1.0, np.nan)
        res[f"fwd_{h}"] = f
        res[f"ep_{h}"] = E.by_episode(f, ep)
        # Контроль 1 — одновременная кросс-секция.
        cs = E.cross_section(P, cols, rows, h)
        res[f"cross_{h}"] = cs
        res[f"ep_cross_{h}"] = E.by_episode(np.where(
            np.isfinite(cs) & np.isfinite(f), f - cs, np.nan), ep)

    # Нуль 1: случайные моменты того же актива и часа, десять зёрен.
    guard = E.steps(24 * 60)
    for h in HORIZONS:
        per_seed = []
        for s in range(NULL_SEEDS):
            vals = []
            for r in np.unique(rows):
                sel = rows == r
                jj = E.null_matched_times(valid_by_row[r], cols[sel], hours,
                                          20260729 + s, guard)
                good = jj >= 0
                if good.any():
                    vals.append(E.forward(P[r], jj[good], h))
            if vals:
                v = np.concatenate(vals)
                v = v[np.isfinite(v)]
                if len(v):
                    per_seed.append(float(np.median(v)))
        res[f"null1_{h}"] = np.array(per_seed)
        log(f"  нуль 1, {h} мин: зёрен {len(per_seed)}")

    # Нуль 2: тот же актив, момент сдвинут на год.
    for h in HORIZONS:
        vals = []
        for r in np.unique(rows):
            sel = rows == r
            jj = E.null_shift(cols[sel], n)
            good = jj >= 0
            if good.any():
                vals.append(E.forward(P[r], jj[good], h))
        v = np.concatenate(vals) if vals else np.array([])
        v = v[np.isfinite(v)]
        res[f"null2_{h}"] = float(np.median(v)) if len(v) else float("nan")
    return res


def block(name, res):
    """Строки отчёта по одной руке."""
    if not res:
        return [f"### {name}\n", "Событий нет.\n"]
    out = [f"### {name}\n",
           f"Событий {res['events']}, эпизодов **{res['episodes']}**.\n",
           "| Горизонт | Превышение над кросс-секцией | Медиана форварда | "
           "Доля + | Нуль 1, ср. | Нуль 2 |", "|---|---|---|---|---|---|"]
    for h in HORIZONS + DIAGNOSTIC:
        ec = res.get(f"ep_cross_{h}", np.array([]))
        e = res.get(f"ep_{h}", np.array([]))
        n1 = res.get(f"null1_{h}")
        n2 = res.get(f"null2_{h}")
        cell = (f"**{np.median(ec) * 1e4:+.1f}** б.п." if len(ec) else "—")
        med = (f"{np.median(e) * 1e4:+.1f} б.п." if len(e) else "—")
        pos = (f"{np.mean(ec > 0):.0%}" if len(ec) else "—")
        s1 = (f"{np.mean(n1) * 1e4:+.1f}" if n1 is not None and len(n1)
              else "—")
        s2 = (f"{n2 * 1e4:+.1f}" if n2 is not None and np.isfinite(n2)
              else "—")
        mark = "" if h in HORIZONS else " *(справка)*"
        out.append(f"| {h} мин{mark} | {cell} | {med} | {pos} | {s1} | {s2} |")
    out.append("")
    return out


def ratio_cell(a, b):
    """Отношение «событие / контроль 2» с честным разбором знаков.

    Отношение двух величин осмысленно, только когда знаменатель
    положителен. Контроль ниже нуля означает, что без условия на
    интерес отскока нет вовсе, — это в пользу гипотезы, но числом
    «−4.27×» такое выражать нельзя.
    """
    if not (np.isfinite(a) and np.isfinite(b)):
        return "—", None
    if b <= 0:
        return ("контроль ≤ 0" if a > 0 else "оба ≤ 0"), (a > 0)
    return f"{a / b:.2f}×", (a / b >= 1.5)


def verdict(ev, c2):
    """Критерий немедленной остановки §9.1 — числом, а не на глаз."""
    out = ["## Критерий немедленной остановки §9.1\n",
           "| Условие | Замер | Срабатывает |", "|---|---|---|"]
    fired = []

    # 1. Превышение против кросс-секции ≤ 0 в большинстве ячеек.
    cs = [float(np.median(ev.get(f"ep_cross_{h}", [np.nan])))
          for h in HORIZONS]
    bad = sum(1 for v in cs if not (np.isfinite(v) and v > 0))
    f1 = bad > len(HORIZONS) / 2
    fired.append(f1)
    out.append(f"| Контроль 1: превышение над одновременной кросс-секцией "
               f"≤ 0 | ячеек с непревышением {bad} из {len(HORIZONS)} | "
               f"{'**ДА**' if f1 else 'нет'} |")

    # 2. Контроль 2: интерес не добавляет.
    worse = 0
    for h in HORIZONS:
        a = float(np.median(ev.get(f"ep_cross_{h}", [np.nan])))
        b = float(np.median(c2.get(f"ep_cross_{h}", [np.nan])))
        if not (np.isfinite(a) and np.isfinite(b)) or a <= b:
            worse += 1
    f2 = worse > len(HORIZONS) / 2
    fired.append(f2)
    out.append(f"| Контроль 2: события без условия на интерес не хуже | "
               f"ячеек {worse} из {len(HORIZONS)} | "
               f"{'**ДА**' if f2 else 'нет'} |")

    # 3. Нуль 1: сравниваются одинаковые величины — медиана форварда.
    below = 0
    for h in HORIZONS:
        e = ev.get(f"ep_{h}", np.array([]))
        n1 = ev.get(f"null1_{h}", np.array([]))
        if len(e) == 0 or len(n1) == 0:
            below += 1
            continue
        if float(np.median(e)) <= float(np.percentile(n1, 95)):
            below += 1
    f3 = below >= 2
    fired.append(f3)
    out.append(f"| Нуль 1: не выше 95-го процентиля десяти зёрен | "
               f"ячеек {below} из {len(HORIZONS)} | "
               f"{'**ДА**' if f3 else 'нет'} |")

    out.append("")
    out.append("**Сработало условий: "
               f"{sum(fired)} из {len(fired)}.** "
               + ("Работа прекращается до этапа L5."
                  if any(fired) else
                  "Ни одно не сработало — можно считать L4."))
    out.append("")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--limit", type=int, default=0, help="пилот на N символах")
    ap.add_argument("--start", default=D.START)
    ap.add_argument("--end", default=D.END)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t_start = time.time()

    def log(msg):
        print(f"[{time.time() - t_start:6.0f} с] {msg}", file=sys.stderr,
              flush=True)

    times = D.grid(a.start, a.end)
    uni = D.universe()
    have = sorted(s[:-len(".npz")] for s in os.listdir(D.OI_SERIES)
                  if s.endswith(".npz"))
    symbols = [s for s in have if s in uni]
    if a.limit:
        symbols = symbols[:a.limit]
    log(f"символов {len(symbols)}, моментов сетки {len(times):,}")

    share, min_share = D.liquid_days(a.interval)
    log(f"ликвидность: символов {len(share):,}")

    P = D.price_matrix(symbols, times, a.interval, log)
    log(f"матрица цен {P.shape}, заполнено {np.isfinite(P).mean():.1%}")

    rec, valid_by_row, hours = scan_symbols(symbols, times, P, uni, share,
                                            min_share, log)
    log(f"событий всего {len(rec['col']):,}")
    if len(rec["col"]) == 0:
        # Пустой результат — тоже результат, но отчёт о нём должен
        # быть отчётом, а не падением на первом же сравнении.
        with open(os.path.join(OUT, f"L3-report-{a.interval}.md"), "w",
                  encoding="utf-8") as f:
            f.write("# L3 — событий не найдено\n\nНи одного события при "
                    f"пороге {OI_DROP:.0%}/{MOVE:.0%} на {len(symbols)} "
                    "символах. Это либо слишком строгий порог, либо "
                    "дефект фильтров §7 — проверять надо второе.\n")
        raise SystemExit("событий нет")

    confirm = np.array([s not in D.EXPLORATORY for s in rec["sym"]])
    results = {}
    for part, mask in (("подтверждающая", confirm),
                       ("разведочная", ~confirm)):
        sub = {k: v[mask] for k, v in rec.items()}
        for arm in ("event", "control2"):
            log(f"замер: {part}, рука {arm}")
            results[(part, arm)] = measure(sub, arm, times, P, valid_by_row,
                                           hours, log)

    np.savez_compressed(
        os.path.join(OUT, "l3_events.npz"),
        row=rec["row"], col=rec["col"], sym=rec["sym"],
        oi_change=rec["oi_change"], price_change=rec["price_change"],
        oi_usd=rec["oi_usd"], arm=rec["arm"],
        times=times, symbols=np.array(symbols))

    md = ["# L3 — события, эпизоды и контроли\n",
          f"Окно {a.start} … {a.end}, шаг сетки {D.STEP_MIN} мин. "
          f"Порог §5.1: интерес −{OI_DROP:.0%} и цена −{MOVE:.0%} за "
          f"{E.WINDOW_MIN} минут. Символов {len(symbols)}.\n",
          "Момент решения — метка `metrics` плюс 5 минут; вход по первой "
          "цене после него. Падение интереса считается **в контрактах**: "
          "долларовый интерес падает вместе с ценой сам собой, и условие "
          "на нём было бы тавтологией.\n",
          "## 1. Вердиктная часть — подтверждающая\n"]
    md += block("Событие (условие на интерес есть)",
                results[("подтверждающая", "event")])
    md += block("Контроль 2 (условие на интерес снято)",
                results[("подтверждающая", "control2")])

    ev = results[("подтверждающая", "event")]
    c2 = results[("подтверждающая", "control2")]
    if ev and c2:
        md.append("### Критерий 8: во сколько раз интерес добавляет\n")
        md.append("Обе величины — превышение над одновременной "
                  "кросс-секцией, по эпизодам.\n")
        md.append("| Горизонт | Событие | Контроль 2 | Отношение | Порог 1.5 |")
        md.append("|---|---|---|---|---|")
        for h in HORIZONS:
            a_ = float(np.median(ev.get(f"ep_cross_{h}", [np.nan])))
            b_ = float(np.median(c2.get(f"ep_cross_{h}", [np.nan])))
            cell, ok = ratio_cell(a_, b_)
            md.append(f"| {h} мин | {a_ * 1e4:+.1f} б.п. | "
                      f"{b_ * 1e4:+.1f} б.п. | {cell} | "
                      f"{'да' if ok else '**НЕТ**'} |")
        md.append("")
        md += verdict(ev, c2)
    md.append("## 2. Справка — разведочная часть\n")
    md.append("Вердикт по ней не выносится: на этих двенадцати активах "
              "выбраны пороги.\n")
    md += block("Событие", results[("разведочная", "event")])
    md += block("Контроль 2", results[("разведочная", "control2")])

    text = "\n".join(md)
    dst = os.path.join(OUT, f"L3-report-{a.interval}.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    log(f"записано {dst}")


if __name__ == "__main__":
    main()
