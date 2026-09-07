#!/usr/bin/env python3
"""Проверка величины funding: сколько начислений, с каким шагом и почему.

Вопрос владельца 2026-09-07: «ты точно издержки правильно посчитал?
Будто фандинг огромный, и не может быть таким, он же снимает с позиции
или добавляет каждые 8 часов, у нас сделки открыты всего по 20».

Возражение проверяемое, и проверяется оно тремя числами, а не доводом:

1. **Шаг ряда площадки.** Bybit начисляет не всем раз в восемь часов:
   у части перпов интервал 1, 2 или 4 часа. Если шаг ряда 8 ч, а
   позиция живёт 24 ч, начислений три; если шаг час — двадцать четыре.
   Здесь шаг МЕРЯЕТСЯ по самому ряду, а не берётся из головы.
2. **Дубликаты в ряду.** Загрузчик рядов дописывает файл, а читатель
   (`funding_series.load_funding`) только сортирует и НЕ выбрасывает
   повторы: повторная закачка того же окна удвоила бы каждое начисление
   молча. Считается число повторов и то, насколько изменился бы итог
   книги без них.
3. **Сама арифметика позиции.** Для самых дорогих по funding позиций
   печатается КАЖДОЕ начисление: момент, ставка, открытый нотионал и
   доллары. Складывать их можно глазами — это и есть проверка.

Ничего не исправляет: замер отвечает на вопрос «правильно ли
посчитано», и правку (если она нужна) делает отдельный шаг.

Запуск: `run research/dca_paper/fund_check.py`.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402

DEP = 10000.0
TOP = 6


def series_health(funding, assets=None):
    """Шаг ряда, повторы и разброс ставок — по каждому активу."""
    out = {}
    for a, (t, r) in (funding or {}).items():
        if assets is not None and a not in assets:
            continue
        t = np.asarray(t, dtype=np.int64)
        uniq = int(np.unique(t).size)
        d = np.diff(np.unique(t)) / 3600000.0 if uniq > 1 else np.array([])
        rr = np.abs(np.asarray(r, dtype=float))
        out[a] = {"n": int(t.size), "uniq": uniq, "dups": int(t.size - uniq),
                  "step_h": (round(float(np.median(d)), 2) if d.size else None),
                  "step_min_h": (round(float(np.min(d)), 2) if d.size else None),
                  "rate_median": (round(float(np.median(rr)), 6)
                                  if rr.size else None),
                  "rate_max": (round(float(np.max(rr)), 6) if rr.size else None),
                  "last": (int(t[-1]) if t.size else None)}
    return out


def steps_overview(health):
    """Сводка по шагу: сколько активов с каким интервалом начислений."""
    got = {}
    for a, h in health.items():
        k = ("нет точек" if h["step_h"] is None
             else f"{h['step_h']:g} ч")
        got[k] = got.get(k, 0) + 1
    return dict(sorted(got.items(), key=lambda kv: -kv[1]))


def dedup(funding):
    """Тот же ряд без повторов по времени (последнее значение)."""
    out = {}
    for a, (t, r) in (funding or {}).items():
        t = np.asarray(t, dtype=np.int64)
        r = np.asarray(r, dtype=float)
        if t.size == 0:
            out[a] = (t, r)
            continue
        # последний по порядку выигрывает: ряд уже отсортирован по времени
        u, idx = np.unique(t, return_index=False), None
        keep = {}
        for i in range(t.size):
            keep[int(t[i])] = float(r[i])
        tt = np.asarray(sorted(keep), dtype=np.int64)
        rr = np.asarray([keep[int(x)] for x in tt], dtype=float)
        out[a] = (tt, rr)
    return out


def book_funding(rows, funding, to_asset):
    """Сумма funding книги на ЭТОМ ряду — тем же ядром, что издержки."""
    tot, n, miss = 0.0, 0, 0
    for r in rows:
        a = to_asset.get(r.get("sym"))
        s = (funding or {}).get(a) if a else None
        v = CO.funding_usd(r, s, R.row_side(r)) if s is not None else None
        if v is None:
            miss += 1
            continue
        tot += float(v)
        n += 1
    return {"usd": round(tot, 2), "n": n, "missing": miss}


def explain_top(rows, funding, to_asset, k=TOP):
    """Самые дорогие по funding позиции — с каждым начислением отдельно."""
    got = []
    for r in rows:
        a = to_asset.get(r.get("sym"))
        s = (funding or {}).get(a) if a else None
        if s is None:
            continue
        v = CO.funding_usd(r, s, R.row_side(r))
        if v is not None:
            got.append((float(v), r, s))
    got.sort(key=lambda x: x[0])
    out = []
    for v, r, s in got[:k]:
        pnl, ev = CO.funding_usd(r, s, R.row_side(r), detail=True)
        m = float(r.get("margin") or 0.0)
        hold = (float(r["exit_ts"]) - float(r["at"])) / 3600.0
        out.append({
            "sym": r.get("sym"), "side": R.row_side(r),
            "lev": round(float(r.get("lev") or 0), 1), "margin": round(m, 2),
            "notional": round(R.notional_of(r) or 0.0, 2),
            "hold_h": round(hold, 1), "n_events": len(ev),
            "per_hour": (round(len(ev) / hold, 2) if hold > 0 else None),
            "rate_sum": round(sum(e["rate"] for e in ev), 6),
            "rate_max": (round(max(abs(e["rate"]) for e in ev), 6)
                         if ev else None),
            "funding_usd": round(pnl, 2),
            "funding_bp_margin": (round(pnl / m * 1e4, 0) if m > 0 else None),
            "events": ev[:30]})
    return out


def run(dep=DEP, log=print, short_path=None, ctx=None):
    t0 = time.time()
    ctx = ctx if ctx is not None else CO.context()
    if ctx.get("error") and not ctx.get("funding"):
        log(f"рядов funding нет: {ctx['error']}")
        return {"error": ctx["error"], "dep": dep}
    funding, to_asset = ctx.get("funding") or {}, ctx["to_asset"]
    rows, _bad = R.read_journal(short_path or R.H24_JOURNAL)
    rows = [r for r in rows if R.is_current(r)
            and int(float(r.get("dep") or 0)) == int(dep)]
    log(f"строк коротких книг на ${dep:,.0f}: {len(rows)}")
    used = {to_asset.get(r.get("sym")) for r in rows}
    used.discard(None)
    health = series_health(funding, used)
    clean = dedup(funding)
    out = {"dep": dep, "n_rows": len(rows),
           "assets_used": len(used),
           "steps": steps_overview(health),
           "dups_total": int(sum(h["dups"] for h in health.values())),
           "assets_with_dups": int(sum(1 for h in health.values()
                                       if h["dups"])),
           "books": {}, "health_sample": dict(list(health.items())[:5]),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    for sk in R.order_of("h24"):
        mine = [r for r in rows if R.ruler_of(r) == sk]
        if not mine:
            out["books"][sk] = {"why": "строк книги нет"}
            continue
        as_is = book_funding(mine, funding, to_asset)
        no_dup = book_funding(mine, clean, to_asset)
        out["books"][sk] = {
            "n": len(mine), "as_is": as_is, "dedup": no_dup,
            "delta": round(no_dup["usd"] - as_is["usd"], 2),
            "top": explain_top(mine, funding, to_asset)}
        log(f"{sk}: funding {as_is['usd']:+.2f} $ (без повторов "
            f"{no_dup['usd']:+.2f} $) на {as_is['n']} позициях")
    out["secs"] = round(time.time() - t0, 1)
    return out


def report(s):
    L = ["# Проверка величины funding", "",
         "Вопрос владельца 2026-09-07: «фандинг будто огромный, он же "
         "снимает каждые 8 часов, а сделки открыты по 20». Проверяется "
         "тремя числами: шаг ряда площадки, повторы в ряду и арифметика "
         "самых дорогих позиций по одному начислению.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не проверено:** {s['error']}.", ""])
    L += [f"Строк коротких книг на ${int(s['dep']):,}: {s['n_rows']}; "
          f"активов в них {s['assets_used']}.", "",
          "## Шаг начислений у площадки", "",
          "| интервал | активов |", "|---|--:|"]
    for k, v in (s.get("steps") or {}).items():
        L.append(f"| {k} | {v} |")
    L += ["", f"Повторов по времени в рядах: **{s.get('dups_total')}** "
          f"(активов с повторами {s.get('assets_with_dups')}). Повтор "
          "означал бы двойное начисление: читатель ряда только сортирует "
          "и повторы не выбрасывает.", "",
          "## Влияние повторов на итог книги", "",
          "| книга | позиций | funding как есть | без повторов | разница |",
          "|---|--:|--:|--:|--:|"]
    for sk, b in (s.get("books") or {}).items():
        if b.get("why"):
            L.append(f"| {R.ruler_title(sk)} | — | — | — | {b['why']} |")
            continue
        L.append(f"| {R.ruler_title(sk)} | {b['n']} | "
                 f"{b['as_is']['usd']:+.2f} | {b['dedup']['usd']:+.2f} | "
                 f"{b['delta']:+.2f} |")
    L += ["", "## Арифметика самых дорогих позиций", "",
          "Начисления печатаются по одному: момент, ставка площадки, "
          "открытый нотионал и доллары. Сумма столбца долларов и есть "
          "funding позиции — сложить можно глазами.", ""]
    for sk, b in (s.get("books") or {}).items():
        if b.get("why"):
            continue
        L += [f"### {R.ruler_title(sk)}", ""]
        for x in b.get("top") or []:
            L += [f"**{x['sym']}** ({x['side']}): маржа ${x['margin']}, "
                  f"плечо {x['lev']}×, нотионал ${x['notional']}, держали "
                  f"{x['hold_h']} ч; начислений **{x['n_events']}** "
                  f"({x['per_hour']} в час), сумма ставок {x['rate_sum']}, "
                  f"наибольшая {x['rate_max']}; итого "
                  f"**{x['funding_usd']:+.2f} $** "
                  f"({x['funding_bp_margin']:+.0f} б.п. маржи).", "",
                  "| момент | ставка | открытый нотионал $ | $ |",
                  "|---|--:|--:|--:|"]
            for e in x["events"]:
                L.append("| " + time.strftime("%m-%d %H:%M",
                                              time.gmtime(e["ts"]))
                         + f" | {e['rate']:+.6f} | {e['open_notional']} | "
                         f"{e['usd']:+.3f} |")
            L += [""]
    L += ["## Как читать", "",
          "- Начислений БОЛЬШЕ трёх за сутки — не ошибка счёта, если шаг "
          "ряда меньше восьми часов: у части перпов Bybit интервал 1, 2 "
          "или 4 часа, и это видно в таблице шага.",
          "- Повторы в ряду были бы ошибкой ДАННЫХ, и их влияние на итог "
          "стоит числом выше: ноль означает, что удвоения нет.",
          "- Ставка площадки нормирована на свой интервал: 0.0001 при "
          "часовом шаге за сутки даёт столько же, сколько 0.0008 при "
          "восьмичасовом, и сравнивать надо сумму ставок за жизнь "
          "позиции, а не отдельную ставку.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="проверка величины funding")
    ap.add_argument("--dep", type=float, default=DEP)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run(dep=a.dep)
    art = os.path.join(R.OUT, "DCA-fund-check.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-fund-check.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("проверка величины funding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
