#!/usr/bin/env python3
"""
D1 — проверка события по ленте: падала цена или только котировка.

Зачем это считается ПЕРВЫМ
--------------------------

Событие D1 определено по середине стакана, а середина падает и без
единой сделки: достаточно, чтобы сняли биды. Тогда «отскок» есть
возврат котировки на место, торговать его нельзя ни при какой задержке,
и +26.6 б.п. отчёта D1 — не эдж, а рисунок пустой книги.

Проверка дешёвая и решающая, поэтому идёт до нулей D2 — тот же приём,
которым потолок рычагов закрыл направление в S1 без недели работы: если
превышение живёт только там, где сделок не было, направление закрыто.

Что считается
-------------

По каждому событию ячейки вердикта:

- **падение по сделкам** против падения по середине. Цена сделки берётся
  ближайшая по времени к тем же двум моментам, что и у середины;
- **сколько сделок** прошло в окне падения. Ноль сделок — это не «не
  подтвердилось», это «нечем проверять», и такие события идут третьей
  группой, а не в отказ;
- **спред в момент события** и во сколько раз он шире обычного для этого
  имени. Заодно это первый честный взгляд на исполнение: вход платит
  половину спреда, выход вторую, и если спред в обвале 20 б.п., то от
  превышения не остаётся ничего ещё до комиссии.

Пороги объявлены здесь и до прогона.

    .venv/bin/python research/d1_seconds/tape_check.py --days 3
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
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import detect as D                                        # noqa: E402
import run_d1 as R                                        # noqa: E402
from store import read_hour                               # noqa: E402

# --- объявлено до прогона ---------------------------------------------
TRADE_TOL_SEC = 60        # допуск на поиск цены сделки у границы окна
MIN_TRADES = 10           # меньше — «нечем проверять», а не «не подтвердилось»
CONFIRM_SHARE = 0.5       # падение по сделкам не мельче половины от середины
COMMISSION_BP = 11.0      # круг тейкера по крипто-универсуму Bybit


def book_line(line):
    """Время, бид и аск из строки снимка.

    Отдельно от `run_d1.mid_line`, потому что здесь нужен спред, а не
    только середина. Совпадение двух разборов закреплено тестом: разойдясь,
    они дали бы «проверку» на других событиях, чем сам прогон.
    """
    i = line.find('"bid":')
    if i < 0:
        raise ValueError("нет bid")
    i += 6
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    bid = float(line[i:j])
    i = line.find('"ask":', j)
    if i < 0:
        raise ValueError("нет ask")
    i += 6
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    ask = float(line[i:j])
    i = line.rfind(',"t":')
    if i < 0:
        raise ValueError("нет метки времени")
    i += 5
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    return float(line[i:j]), bid, ask


def trade_line(line):
    """Время и цена сделки. Метка в миллисекундах — как её пишет сборщик."""
    i = line.find('"ts":')
    if i < 0:
        raise ValueError("нет ts")
    i += 5
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    ts = float(line[i:j]) / 1000.0
    i = line.find('"p":')
    if i < 0:
        raise ValueError("нет цены")
    i += 4
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    return ts, float(line[i:j])


def book_grids(root, sym, hours, t0, n):
    """Середина и спред (б.п.) на секундной сетке."""
    d = os.path.join(root, "book", sym)
    ts, mid, spr = [], [], []
    for h in hours:
        for t, bid, ask in read_hour(d, h, parse=book_line):
            m = (bid + ask) / 2.0
            if m <= 0:
                continue
            ts.append(t)
            mid.append(m)
            spr.append((ask - bid) / m * 1e4)
    return (D.place(ts, mid, t0, n).astype(np.float32),
            D.place(ts, spr, t0, n).astype(np.float32))


def trade_grids(root, sym, hours, t0, n):
    """Цена последней сделки секунды и число сделок в секунде."""
    d = os.path.join(root, "trades", sym)
    ts, px = [], []
    for h in hours:
        for t, p in read_hour(d, h, parse=trade_line):
            ts.append(t)
            px.append(p)
    grid = D.place(ts, px, t0, n).astype(np.float32)
    cnt = np.zeros(n, dtype=np.int32)
    if ts:
        j = np.floor(np.asarray(ts) - t0).astype(np.int64)
        j = j[(j >= 0) & (j < n)]
        np.add.at(cnt, j, 1)
    return grid, cnt


def at_time(prev, nxt, k, tol):
    """Индекс ближайшего наблюдения к секунде `k`. Обёртка над ядром."""
    return int(D.nearest(prev, nxt, np.array([int(k)]), tol=tol)[0])


def check_day(root, syms, day, jobs, log=print):
    """События суток с приписанной к ним проверкой по ленте."""
    P, t0, n = R.load_day(os.path.join(root, "book"), syms, day, jobs, log)
    NXT = R.next_index(P)
    drop = D.VERDICT_CELL["drop"]
    delay = D.VERDICT_CELL["delay_sec"]
    hor = D.VERDICT_CELL["horizon_sec"]
    rows, cols = R.events_of_day(P, t0, drop, {}, R.PAD_SEC,
                                 R.PAD_SEC + R.DAY_SEC)
    log(f"    событий {len(rows)}")
    if len(rows) == 0:
        return [], 0
    ban = D.guard_matrix(P.shape, rows, cols, D.guard_sec(delay, hor))
    hours = R.hours_of(t0, n)
    out, mismatch = [], 0
    by_sym = {}
    for r, j in zip(rows, cols):
        by_sym.setdefault(int(r), []).append(int(j))
    for k, (r, js) in enumerate(sorted(by_sym.items())):
        sym = syms[r]
        mid2, spr = book_grids(root, sym, hours, t0, n)
        # Свободная сверка: своя загрузка обязана дать ту же середину,
        # что и прогон. Разойдись они, проверка описывала бы другие
        # события, а выглядела бы исправной.
        both = np.isfinite(mid2) & np.isfinite(P[r])
        if both.any():
            mismatch += int(np.sum(np.abs(mid2[both] - P[r][both])
                                   > np.abs(P[r][both]) * 1e-6))
        tpx, tcnt = trade_grids(root, sym, hours, t0, n)
        tprev, tnxt = D.fill_index(tpx)
        cum = np.concatenate([[0], np.cumsum(tcnt)])
        # Считается ОДИН раз на символ, а не на событие: и падение по
        # середине, и обычный спред суток — величины ряда, а не события.
        mfall = D.falls(P[r])
        usual = float(np.nanmedian(spr[R.PAD_SEC:R.PAD_SEC + R.DAY_SEC]))
        for j in js:
            own, bg, exc, width = D.excess(P, NXT, r, j, delay, hor,
                                           ban[:, j])
            i_now = at_time(tprev, tnxt, j, TRADE_TOL_SEC)
            i_ref = at_time(tprev, tnxt, j - D.W_SEC, TRADE_TOL_SEC)
            t_fall = (float(tpx[i_now] / tpx[i_ref] - 1.0)
                      if i_now >= 0 and i_ref >= 0 else float("nan"))
            n_tr = int(cum[min(j + 1, n)] - cum[max(j - D.W_SEC, 0)])
            i_out = int(D.first_at_or_after(
                NXT[r], np.array([j + delay + hor]), D.FILL_WAIT_SEC)[0])
            out.append({
                "sym": sym, "t": t0 + j, "excess": exc, "own": own,
                "bg": bg, "width": width, "mid_fall": float(mfall[j]),
                "trade_fall": t_fall, "n_trades": n_tr,
                "spread_in": float(spr[j]) if np.isfinite(spr[j]) else None,
                "spread_out": (float(spr[i_out]) if i_out >= 0
                               and np.isfinite(spr[i_out]) else None),
                "spread_usual": usual,
            })
        if (k + 1) % 25 == 0:
            log(f"    проверено {k + 1}/{len(by_sym)} имён")
    del P, NXT, ban
    return out, mismatch


def group_of(e):
    """Три группы, и третья обязана быть отдельной.

    «Сделок не было» — это не опровержение события, а отсутствие
    свидетельства. Смешав их с опровергнутыми, мы объявили бы дефектом
    то, чего не измеряли.
    """
    if e["n_trades"] < MIN_TRADES or not np.isfinite(e["trade_fall"]):
        return "нечем проверять"
    if e["trade_fall"] <= CONFIRM_SHARE * e["mid_fall"]:
        return "подтверждено лентой"
    return "только котировка"


def med(v):
    v = [x for x in v if x is not None and np.isfinite(x)]
    return float(np.median(v)) if v else None


def summarise(rows):
    out = {}
    for g in ("подтверждено лентой", "только котировка", "нечем проверять"):
        sub = [e for e in rows if group_of(e) == g]
        if not sub:
            out[g] = {"events": 0}
            continue
        exc = np.array([e["excess"] for e in sub], dtype=np.float64)
        ok = np.isfinite(exc)
        # `None` НЕ приводится к нулю: у группы «нечем проверять»
        # падения по сделкам не существует, а «+0.00 %» в таблице
        # читается как «цена не двигалась» — то есть как измерение.
        # Тот же молчаливый ноль, что ловится в этом проекте с A2.
        mf = med([e["mid_fall"] for e in sub])
        tf = med([e["trade_fall"] for e in sub])
        rec = {
            "events": len(sub),
            "measured": int(ok.sum()),
            "mid_fall_pct": None if mf is None else round(mf * 100, 2),
            "trade_fall_pct": None if tf is None else round(tf * 100, 2),
            "trades_median": med([e["n_trades"] for e in sub]),
            "spread_in_bp": round(med([e["spread_in"] for e in sub]) or 0, 1),
            "spread_out_bp": round(med([e["spread_out"] for e in sub]) or 0,
                                   1),
            "spread_ratio": None,
            "excess_bp": None, "episodes": 0, "share_pos": None,
        }
        rr = [e["spread_in"] / e["spread_usual"] for e in sub
              if e["spread_in"] and e["spread_usual"]]
        rec["spread_ratio"] = round(med(rr) or 0, 2)
        if ok.any():
            t = np.array([e["t"] for e in sub], dtype=np.float64)[ok]
            ep = D.episodes(t)
            v = D.by_episode(exc[ok], ep)
            rec["episodes"] = int(len(v))
            rec["excess_bp"] = round(float(np.median(v)) * 1e4, 2)
            rec["share_pos"] = round(float(np.mean(v > 0)), 3)
        out[g] = rec
    return out


def report(art, path):
    L = ["# D1 — проверка события по ленте\n",
         f"Прогон: {art['run_at']}. Спека 11, к этапу D1.\n",
         "Вопрос один: **падала цена или только котировка.** Середина "
         "стакана падает и без единой сделки — достаточно, чтобы сняли "
         "биды; такой «отскок» есть возврат котировки на место, и "
         "торговать его нельзя ни при какой задержке.\n",
         f"Считается по ячейке вердикта: падение "
         f"{int(D.VERDICT_CELL['drop'] * 100)} %, задержка "
         f"{D.VERDICT_CELL['delay_sec']} с, удержание "
         f"{D.VERDICT_CELL['horizon_sec'] // 60} мин. Пороги объявлены до "
         f"прогона: сделок в окне не меньше {MIN_TRADES}, падение по "
         f"сделкам не мельче {CONFIRM_SHARE:.0%} от падения середины, "
         f"допуск на поиск цены сделки {TRADE_TOL_SEC} с.\n",
         f"- суток: **{art['days']}**, событий: **{art['events']}**",
         f"- сверка загрузки: расхождений середины с прогоном D1 — "
         f"**{art['mismatch']}**\n",
         "## 1. Где живёт превышение\n",
         "| группа | событий | эпизодов | превышение, б.п. | доля > 0 | "
         "падение середины | падение по сделкам | сделок в окне |",
         "|---|---|---|---|---|---|---|---|"]
    for g, r in art["groups"].items():
        if not r.get("events"):
            L.append(f"| {g} | 0 | — | — | — | — | — | — |")
            continue
        dash = lambda v, f: "—" if v is None else format(v, f)
        L.append(
            f"| {g} | {r['events']} | {r['episodes']} | "
            f"{dash(r['excess_bp'], '+.1f')} | "
            f"{dash(r['share_pos'], '')} | "
            f"{dash(r['mid_fall_pct'], '+.2f')} % | "
            f"{dash(r['trade_fall_pct'], '+.2f')} % | "
            f"{dash(r['trades_median'], '.0f')} |")
    L.append("")
    L.append("## 2. Спред: чем придётся платить\n")
    L.append("Вход платит половину спреда, выход вторую. Это ещё не "
             "проскальзывание обходом лесенки (оно в D3) — это цена "
             "первого уровня, ниже которой исполнение быть не может.\n")
    L.append("| группа | спред на входе | спред на выходе | во сколько раз "
             "шире обычного | круг со спредом |")
    L.append("|---|---|---|---|---|")
    for g, r in art["groups"].items():
        if not r.get("events"):
            L.append(f"| {g} | — | — | — | — |")
            continue
        ring = COMMISSION_BP + (r["spread_in_bp"] + r["spread_out_bp"]) / 2
        # Круг со спредом печатается рядом с превышением намеренно:
        # именно их отношение решает, а не величина сама по себе.
        L.append(f"| {g} | {r['spread_in_bp']:.1f} б.п. | "
                 f"{r['spread_out_bp']:.1f} б.п. | "
                 f"{r['spread_ratio']:.2f}× | {ring:.1f} б.п. |")
    L.append("")
    L.append("## 3. Как читать\n")
    L.append(art["reading"])
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def reading(g):
    """Вывод пишется из чисел, а не из надежды."""
    c = g.get("подтверждено лентой") or {}
    q = g.get("только котировка") or {}
    n = g.get("нечем проверять") or {}
    if not c.get("events") and not q.get("events"):
        # Все события в третьей группе — это НЕ опровержение: сделок в
        # записи может не быть по нашей же вине (лента не писалась,
        # имя тонкое). Отсутствие свидетельства и свидетельство
        # отсутствия — разные вещи, и путать их здесь значит закрыть
        # направление по дефекту сбора.
        return (f"Судить нечем: все {n.get('events', 0)} событий попали в "
                f"«нечем проверять» — сделок в окне меньше {MIN_TRADES}. "
                f"Это не опровержение, а отсутствие свидетельства: сперва "
                f"проверить, пишется ли лента вообще.")
    if not c.get("events"):
        return ("Событий, подтверждённых лентой, нет вовсе, а "
                f"опровергнутых {q.get('events')} — значит падения "
                "середины происходят без сделок, и отскок торговать "
                "нельзя. Направление закрыто.")
    if c.get("excess_bp") is None:
        return "Превышение в подтверждённой группе не измерено."
    ce, qe = c["excess_bp"], q.get("excess_bp")
    if qe is None:
        return (f"Превышение живёт в подтверждённой группе "
                f"({ce:+.1f} б.п. на {c['episodes']} эпизодах); группа "
                f"«только котировка» не измерена. Угроза котировочного "
                f"артефакта не подтвердилась.")
    if ce <= 0 and qe > 0:
        return (f"**Превышение живёт ТОЛЬКО там, где сделок не было** "
                f"({qe:+.1f} против {ce:+.1f} б.п.). Это котировочный "
                f"артефакт, а не эдж: торговать возврат снятой котировки "
                f"нельзя. Направление закрыто.")
    if qe > ce:
        return (f"Превышение больше там, где сделок не было "
                f"({qe:+.1f} против {ce:+.1f} б.п.) — часть результата "
                f"котировочная. Эдж подтверждённой группы предъявлять "
                f"можно, но считать надо по ней одной.")
    return (f"Превышение живёт в подтверждённой лентой группе: "
            f"{ce:+.1f} б.п. на {c['episodes']} эпизодах против "
            f"{qe:+.1f} у «только котировки». Угроза котировочного "
            f"артефакта не подтвердилась — событие есть движение цены.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"
    os.makedirs(a.out, exist_ok=True)

    syms, hours = R.available(os.path.join(a.root, "book"))
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    print(f"символов {len(syms)}, суток {len(days)}")
    t_start = time.time()
    rows, mism = [], 0
    for day in days:
        print(f"  {day}: читаю")
        got, m = check_day(a.root, syms, day, a.jobs)
        rows += got
        mism += m
        print(f"  {day}: событий {len(got)}, расхождений середины {m}")
    art = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "days": len(days), "events": len(rows), "mismatch": mism,
        "thresholds": {"min_trades": MIN_TRADES,
                       "confirm_share": CONFIRM_SHARE,
                       "trade_tol_sec": TRADE_TOL_SEC},
        "groups": summarise(rows),
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    art["reading"] = reading(art["groups"])
    p = os.path.join(a.out, f"D1-tape-check-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"D1-tape-check-{a.tag}.md"))
    print(f"готово: {p}")
    print(art["reading"])
    if not a.no_publish:
        R.publish(f"D1: проверка события по ленте ({a.tag})")


if __name__ == "__main__":
    main()
