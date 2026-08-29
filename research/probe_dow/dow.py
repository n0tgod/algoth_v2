"""Зонд дней недели: есть ли смысл торговать только в определённые дни.

Вопрос владельца: «торговать только на выходных, или не торговать на
выходных, потести разные варианты». Это зонд, а не гипотеза: порогов
и вердикта нет; он отвечает, отличается ли день недели от остальных
БОЛЬШЕ, чем у перемешанных меток, — и на каком материале это вообще
измеримо.

**Живые книги для этого вопроса непригодны, и это сказано до счёта:**
записи 2–3 недели, каждый день недели встречался 2–4 раза, а окно
слива 08-24…27 (один эпизод) закрашивает четыре дня недели разом.
Живой разрез печатается ЧЕСТНЫМ АНЕКДОТОМ с числом различных дат —
приём страницы волатильности.

**Мерить надо там, где по ~190 наблюдений на день недели: векторы R2**
(3.6 года, ~1330 сечений, тот же возвратный сигнал, что доминирует в
живой модели). Ячейки объявлены до прогона: k=7, h=1 — главная (при
удержании в сутки день недели форварда определён; у длинных удержаний
«суббота» размазана по неделе), k=14, h=1 — диагностика. Метка дня —
UTC-день даты ребаланса; форвард h=1 живёт с этого дня до следующего.

**Суд — перестановочный нуль меток дня недели** (2000 перестановок,
зерно числом — нуль, который нельзя повторить, не является
проверяемым): у семи дней СЕМЬ шансов отклониться, и планка
семейственная — 95-й процентиль МАКСИМАЛЬНОГО отклонения дня от
общего среднего под нулём (приём планки Z1). Именованные варианты
владельца — «только выходные» и «без выходных» — судятся разностью
средних против той же перестановки. Сезонность дня недели — ровно то,
про что память проекта говорит «на короткой истории проще всего
переобучить» (семейство clock), поэтому без нуля здесь читать нечего.

Оговорка единиц: спред дециля — «на ногу», прибыль книги = ½ спреда
(конвенция R4); издержки от дня недели не зависят и в сравнение не
входят. Торговля реже означает и реже платить круг — но сначала
должен существовать сам эффект дня.

Запуск на VPS (векторы R2 живут там):
  cd ~/algoth_v2 && .venv/bin/python research/probe_dow/dow.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(os.path.dirname(HERE), "r2_residual"),
          os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import nulls as N                                          # noqa: E402
import residual as RS                                      # noqa: E402
import turn as PT                                          # noqa: E402

SEED = 20260829
PERMS = 2000
CELLS = ((7, 1), (14, 1))            # (k, h): главная и диагностика
WIDTH = 0.10                         # дециль, как в R2
DAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKEND = (5, 6)


def log_(m):
    print(m, flush=True)


def dow_of(date_str):
    """День недели UTC-даты ребаланса, 0=понедельник … 6=воскресенье."""
    return datetime.fromisoformat(date_str).replace(
        tzinfo=timezone.utc).weekday()


def per_date(vec, k, h):
    """IC и спред дециля по каждой дате ребаланса — ядром R2.

    Тот же `spearman`/`basket_spread`, что считал опубликованные
    отчёты: вторая копия меры однажды разошлась бы с первой.
    """
    out = []
    for d in sorted(vec):
        v = vec[d]
        sig = v["sig"].get(k)
        fwd = v["fwd"].get(h)
        if sig is None or fwd is None:
            continue
        ic, _n = RS.spearman(sig, fwd)
        b = RS.basket_spread(np.asarray(sig), np.asarray(fwd), WIDTH)
        if ic is None or b is None:
            continue
        out.append({"date": d, "dow": dow_of(d), "ic": float(ic),
                    "spread_bp": float(b["spread"]) * 1e4})
    return out


def by_dow(rows, field):
    g = {i: [] for i in range(7)}
    for r in rows:
        g[r["dow"]].append(r[field])
    return g


def family_null(rows, field, perms=PERMS, seed=SEED):
    """Планка семейственная: максимум отклонения дня под нулём.

    Перестановка меток дня недели сохраняет и величины, и их число по
    дням — ломается только привязка к календарю. Значит всё, что
    переживает планку, принадлежит календарю, а не форме распределения.
    """
    vals = np.array([r[field] for r in rows])
    dows = np.array([r["dow"] for r in rows])
    overall = float(vals.mean())
    obs_dev = {i: float(vals[dows == i].mean()) - overall
               for i in range(7) if (dows == i).any()}
    rng = np.random.default_rng(seed)
    maxes = np.empty(perms)
    wk = np.isin(dows, WEEKEND)
    obs_diff = (float(vals[wk].mean() - vals[~wk].mean())
                if wk.any() and (~wk).any() else None)
    diffs = np.empty(perms)
    for i in range(perms):
        p = rng.permutation(dows)
        devs = [abs(float(vals[p == j].mean()) - overall)
                for j in range(7) if (p == j).any()]
        maxes[i] = max(devs)
        pw = np.isin(p, WEEKEND)
        diffs[i] = (float(vals[pw].mean() - vals[~pw].mean())
                    if pw.any() and (~pw).any() else np.nan)
    out = {"overall": overall, "dev": obs_dev,
           "bar95": float(np.percentile(maxes, 95)),
           "max_dev": max(abs(v) for v in obs_dev.values()),
           "weekend_diff": obs_diff}
    if obs_diff is not None:
        d = diffs[np.isfinite(diffs)]
        out["weekend_p"] = round(
            float((np.abs(d) >= abs(obs_diff)).mean()), 4)
    return out


def live_books(s8):
    """Живой разрез по дням недели — анекдот, и это сказано числом дат."""
    rows = []
    for key, name, echo in PT.BOOKS:
        if echo:
            continue
        trades, _m = PT.book_trades(os.path.join(s8, name))
        rows += trades
    g = {i: {"pnl": 0.0, "n": 0, "win": 0, "dates": set()}
         for i in range(7)}
    for t in rows:
        d = datetime.fromtimestamp(t["day"] * 86400,
                                   timezone.utc).weekday()
        g[d]["pnl"] += t["pnl"]
        g[d]["n"] += 1
        g[d]["win"] += 1 if t["pnl"] > 0 else 0
        g[d]["dates"].add(t["day"])
    return {i: {"pnl": round(v["pnl"], 2), "n": v["n"],
                "win": round(v["win"] / v["n"], 2) if v["n"] else None,
                "dates": len(v["dates"])}
            for i, v in g.items()}


def write_report(path, cells, live, meta):
    L = ["# Зонд дней недели: торговать ли только в определённые дни\n",
         f"\nПрогон {meta['when']} · сечений {meta['sections']} · "
         f"перестановок {PERMS} · зерно {SEED}\n",
         "\nЭто зонд, а не гипотеза: порогов и вердикта нет. Суд — "
         "перестановочный нуль меток дня недели; планка семейственная "
         "(95-й процентиль МАКСИМАЛЬНОГО отклонения дня под нулём): у "
         "семи дней семь шансов отклониться, и лучший из семи обязан "
         "судиться как лучший из семи. Спред — «на ногу», прибыль "
         "книги = ½ спреда (конвенция R4); издержки от дня недели не "
         "зависят.\n"]
    for (k, h), c in cells.items():
        tag = "главная" if (k, h) == CELLS[0] else "диагностика"
        L.append(f"\n## Ячейка k={k}, h={h} ({tag}) — {c['n']} сечений, "
                 f"{meta['span']}\n\n")
        L.append("| день | сечений | IC медиана | спред, б.п.: среднее "
                 "| медиана | доля+ | отклонение среднего |\n")
        L.append("|---|--:|--:|--:|--:|--:|--:|\n")
        fam = c["fam_spread"]
        for i in range(7):
            r = c["dow"].get(i)
            if not r:
                continue
            dev = fam["dev"].get(i, 0.0)
            mark = " ⚑" if abs(dev) > fam["bar95"] else ""
            L.append(f"| {DAYS_RU[i]} | {r['n']} | {r['ic_med']:+.4f} | "
                     f"{r['sp_mean']:+.1f} | {r['sp_med']:+.1f} | "
                     f"{r['win']:.2f} | {dev:+.1f}{mark} |\n")
        L.append(f"\nОбщее среднее {fam['overall']:+.1f} б.п.; худший/"
                 f"лучший день отклоняются на {fam['max_dev']:.1f} при "
                 f"планке нуля **{fam['bar95']:.1f}** — "
                 + ("отклонение ПЕРЕЖИВАЕТ планку.\n"
                    if fam["max_dev"] > fam["bar95"] else
                    "то есть день недели не отличим от перемешанных "
                    "меток.\n"))
        wd = fam["weekend_diff"]
        wi = c["fam_ic"]["weekend_diff"]
        # Разности может не быть (нет сечений выходных) — прочерк, а
        # не падение на последнем шаге после всего счёта.
        L.append("\n**Именованные варианты владельца.** «Только "
                 "выходные» против «без выходных»: разность средних "
                 "спредов **"
                 + (f"{wd:+.1f}" if wd is not None else "—")
                 + f" б.п.** на сечение (p = "
                 f"{fam.get('weekend_p', '—')} под перестановкой). ")
        L.append("По IC: разность "
                 + (f"{wi:+.4f}" if wi is not None else "—")
                 + f" (p = {c['fam_ic'].get('weekend_p', '—')}).\n")
    L.append("\n## Живые книги по дням недели — анекдот, не замер\n\n")
    L.append("Каждый день недели встречался считанные разы, и окно "
             "слива 08-24…27 закрашивает четыре дня одним эпизодом. "
             "Таблица стоит здесь, чтобы её НЕ читали как замер.\n\n")
    L.append("| день | сделок | различных дат | $ | побед |\n")
    L.append("|---|--:|--:|--:|--:|\n")
    for i in range(7):
        r = live[i]
        L.append(f"| {DAYS_RU[i]} | {r['n']} | {r['dates']} | "
                 f"{r['pnl']:+.2f} | "
                 f"{r['win'] if r['win'] is not None else '—'} |\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="зонд дней недели")
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--s8", default=os.path.join(
        ROOT, "research", "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)

    vec = N.load_vectors(a.interval)
    cells, n_rows, span = {}, 0, "—"
    for k, h in CELLS:
        rows = per_date(vec, k, h)
        if not rows:
            log_(f"k={k}, h={h}: пар сигнал/форвард нет — пропуск")
            continue
        n_rows = max(n_rows, len(rows))
        span = f"{rows[0]['date']}…{rows[-1]['date']}"
        dd = {}
        for i, ics in by_dow(rows, "ic").items():
            sps = by_dow(rows, "spread_bp")[i]
            if not ics:
                continue
            dd[i] = {"n": len(ics),
                     "ic_med": float(np.median(ics)),
                     "sp_mean": float(np.mean(sps)),
                     "sp_med": float(np.median(sps)),
                     "win": float(np.mean(np.array(sps) > 0))}
        cells[(k, h)] = {"n": len(rows), "dow": dd,
                         "fam_spread": family_null(rows, "spread_bp"),
                         "fam_ic": family_null(rows, "ic")}
        f = cells[(k, h)]["fam_spread"]
        wd = f["weekend_diff"]
        log_(f"k={k} h={h}: {len(rows)} сечений, макс. отклонение дня "
             f"{f['max_dev']:.1f} б.п. при планке {f['bar95']:.1f}, "
             f"выходные − будни "
             + (f"{wd:+.1f}" if wd is not None else "—")
             + f" (p={f.get('weekend_p')})")
    if not cells:
        log_("ни одной ячейки — считать нечего")
        return 1
    live = live_books(a.s8)

    art = {"seed": SEED, "perms": PERMS, "cells": {
        f"k{k}_h{h}": {"n": c["n"],
                       "dow": {str(i): v for i, v in c["dow"].items()},
                       "fam_spread": {kk: (vv if kk != "dev" else
                                           {str(i): x for i, x
                                            in vv.items()})
                                      for kk, vv in
                                      c["fam_spread"].items()},
                       "fam_ic": {kk: (vv if kk != "dev" else
                                       {str(i): x for i, x
                                        in vv.items()})
                                  for kk, vv in c["fam_ic"].items()}}
        for (k, h), c in cells.items()},
        "live": {str(i): v for i, v in live.items()},
        "took_sec": round(time.time() - t0, 1)}
    with open(os.path.join(out_dir, f"dow-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    path = write_report(
        os.path.join(out_dir, f"DOW-report-{a.tag}.md"), cells, live,
        {"when": datetime.now(timezone.utc)
         .strftime("%Y-%m-%d %H:%M UTC"),
         "sections": n_rows, "span": span})
    log_(f"отчёт: {path} · {art['took_sec']} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
