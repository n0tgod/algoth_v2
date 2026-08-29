"""Реплей корзины БЕЗ отдельных выходов: одна цель, один предел, всё
закрывается только разом.

Вопрос владельца: книга как `model_h24b`, но позиции не закрываются
сами по отдельности (ни срока 24 ч, ни своих стопов) — у корзины одна
общая цель +T и один общий предел убытка −F, и сделки закрываются
только все одновременно; перебрать, какие T и F дали бы самый
благоприятный результат.

Порядок тот же, что дважды оправдался (схлопывание, тормоз): сперва
ЗАМЕР реплеем по записанным выборам, потом внедрение. Это диагностика,
не вердикт: **выбрать лучшую ячейку после чтения таблицы — ошибка R5**,
и записи всего ~2.5 недели одного режима (внутри — слив 08-24…27).
Таблица печатается целиком, лучшая ячейка называется С ЭТОЙ оговоркой.

**Сетка объявлена до прогона:** цель T ∈ {2.5, 5, 10, 20} % капитала
руки × предел F ∈ {2.5, 5, 10, 20, нет} = 20 ячеек, обе руки. Пороги
— доли ФИКСИРОВАННОГО капитала 3000 $ (как у живых корзинных книг),
без капитализации.

**Механика реплея, каждое правило из живой кассы или названо:**
- топливо — записанные выборы `model_h24` (те же, что копирует эхо
  h24b); вход по цене записи (закрытие часа сигнала), нога
  3000/144 ≈ 20.8 $ — сайзинг живой книги 24 ч;
- касса: гросс не выше капитала, потолок на имя 10 % (забор
  `NAME_CAP_SHARE`) — ноги сверх получают размер 0 и считаются
  числом («no cash» уже был находкой на живой книге: сигнал записан,
  экспозиции нет). Без отдельных выходов книга наполняется и стоит
  вложенной, пока корзина не закроется, — это следствие конструкции,
  и его доля видна в отчёте;
- встречная нога в удерживаемое имя НЕ открывается (на бирже она
  схлопнула бы позицию — отдельный выход, которого в этой книге нет
  по замыслу); пропуски считаются числом;
- переоценка — ЧАСОВАЯ по серединам площадки исполнения (сводки B1,
  тот же загрузчик, что у реплея тормоза); проверка порога раз в час
  — та же каденция, что у живых корзинных книг («отдельный
  5-секундный сторож был бы второй реализацией переоценки»). Внутри
  часа порог может быть перелетён — как и у живой h24b, это записано;
- нога без цены блокирует решение корзины (правило живой книги:
  «минус непереоценённой ноги мог быть любым — решение вслепую
  запрещено»); часы блокировки считаются;
- издержки: полный круг `ROUND_COST_BP` на ногу, начисляется при
  входе — консервативно к частым корзинам;
- корзина, не закрывшаяся к концу записи, идёт ОТДЕЛЬНОЙ строкой
  отметкой, а не в реализованное: не измерено ≠ ноль.

Рядом — базлайн: фактический результат живой `model_h24` (свои выходы
по сроку) за то же окно, той же кассой.

Запуск на VPS:
  cd ~/algoth_v2 && .venv/bin/python research/probe_basket/basket.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np                                         # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(os.path.dirname(HERE), "probe_drain"),
          os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import brake as BK                                         # noqa: E402
import trades as TR                                        # noqa: E402
import turn as PT                                          # noqa: E402

CAPITAL = 3000.0
LEG_USD = CAPITAL / 144.0            # 6 имён × 24 ч — сайзинг h24
TAKES = (0.025, 0.05, 0.10, 0.20)
FLOORS = (0.025, 0.05, 0.10, 0.20, None)
NAME_CAP = TR.NAME_CAP_SHARE * CAPITAL
COST = TR.ROUND_COST_BP / 1e4        # полный круг на ногу, при входе
HOUR = 3600


def log_(m):
    print(m, flush=True)


def hour_ts(hour):
    return int(datetime.strptime(hour, "%Y-%m-%d-%H")
               .replace(tzinfo=timezone.utc).timestamp())


def load_picks(mdir):
    """Ноги выборов по (руке, часу): sym, side, px."""
    out = {}
    for p in PT.read_jsonl(os.path.join(mdir, "picks.jsonl")):
        arm, hour = p.get("arm"), p.get("hour")
        if not arm or not hour:
            continue
        legs = []
        for side in ("long", "short"):
            for r in p.get(side) or []:
                if r.get("sym") and r.get("px"):
                    legs.append({"sym": r["sym"], "side": side,
                                 "px": float(r["px"])})
        if legs:
            out.setdefault(arm, {})[hour_ts(hour)] = legs
    return out


def mid_at(mids, sym, ts, last):
    """Середина часа с переносом последней известной.

    Дыра в сводке — не ноль: нога без ЕДИНОЙ цены блокирует решение
    корзины (правило живой книги), а короткий пропуск закрывается
    последней известной серединой.
    """
    d = mids.get(sym)
    if d is None:
        return None
    v = d.get(ts)
    if v is not None:
        last[sym] = v
        return v
    return last.get(sym)


def replay(picks, mids, take, floor, capital=CAPITAL, leg_usd=LEG_USD):
    """Одна ячейка: корзина закрывается ТОЛЬКО целиком.

    Порядок такта — как у живой корзины: сперва решение по порогу на
    отметке часа, потом входы этого часа. Порог сравнивается с
    нереализованным результатом всей корзины в долях капитала.
    """
    if not picks:
        return None
    t0, t1 = min(picks), max(picks)
    # Корзина живёт и ПОСЛЕ последнего входа — до закрытия либо до
    # конца записи цен. Обрыв реплея на последнем часе выборов оставил
    # бы каждую корзину неоценённой: вход происходит в конце такта, а
    # отметка — в начале следующего (порядок живой корзины).
    t_end = max([t1] + [max(d) for d in mids.values() if d])
    legs, last = [], {}
    realized, baskets, curve = 0.0, [], []
    skipped = {"no_cash": 0, "name_cap": 0, "opposite": 0,
               "no_price": 0}
    blocked_hours = 0
    basket_open_ts = None
    equity_peak, max_dd = 0.0, 0.0
    for ts in range(t0, t_end + HOUR, HOUR):
        # 1) отметка и решение корзины
        if legs:
            unreal, priced = 0.0, True
            for g in legs:
                m = mid_at(mids, g["sym"], ts, last)
                if m is None:
                    priced = False
                    break
                sign = 1.0 if g["side"] == "long" else -1.0
                unreal += g["size"] * (sign * (m / g["px"] - 1.0)
                                       - COST)
            if not priced:
                blocked_hours += 1
            else:
                hit_take = unreal >= take * capital
                hit_floor = (floor is not None
                             and unreal <= -floor * capital)
                if hit_take or hit_floor:
                    realized += unreal
                    baskets.append({
                        "why": "take" if hit_take else "floor",
                        "pnl": round(unreal, 2), "legs": len(legs),
                        "age_h": (ts - basket_open_ts) // HOUR})
                    legs, basket_open_ts = [], None
                eq = realized + (0.0 if not legs else unreal)
                equity_peak = max(equity_peak, eq)
                max_dd = min(max_dd, eq - equity_peak)
                curve.append(eq)
        # 2) входы часа
        for g in picks.get(ts) or []:
            held = {x["sym"]: x["side"] for x in legs}
            if g["sym"] in held and held[g["sym"]] != g["side"]:
                skipped["opposite"] += 1
                continue
            gross = sum(x["size"] for x in legs)
            if gross + leg_usd > capital + 1e-9:
                skipped["no_cash"] += 1
                continue
            by_name = sum(x["size"] for x in legs
                          if x["sym"] == g["sym"])
            if by_name + leg_usd > NAME_CAP + 1e-9:
                skipped["name_cap"] += 1
                continue
            if g["sym"] not in mids and g["sym"] not in last:
                skipped["no_price"] += 1
                continue
            if not legs:
                basket_open_ts = ts
            legs.append({**g, "size": leg_usd})
    # хвост записи: открытая корзина — отметкой, не реализованным
    open_mark, open_legs = None, len(legs)
    if legs:
        unreal, priced = 0.0, True
        for g in legs:
            m = mid_at(mids, g["sym"], t_end, last)
            if m is None:
                priced = False
                break
            sign = 1.0 if g["side"] == "long" else -1.0
            unreal += g["size"] * (sign * (m / g["px"] - 1.0) - COST)
        open_mark = round(unreal, 2) if priced else None
    n_take = sum(1 for b in baskets if b["why"] == "take")
    n_floor = len(baskets) - n_take
    return {"take": take, "floor": floor,
            "realized": round(realized, 2),
            "open_mark": open_mark, "open_legs": open_legs,
            "baskets": len(baskets), "n_take": n_take,
            "n_floor": n_floor,
            "worst_basket": (min((b["pnl"] for b in baskets),
                                 default=None)),
            "age_med_h": (sorted(b["age_h"] for b in baskets)
                          [len(baskets) // 2] if baskets else None),
            "age_max_h": max((b["age_h"] for b in baskets),
                             default=None),
            "max_dd": round(max_dd, 2),
            "blocked_hours": blocked_hours, "skipped": skipped}


def baseline(s8, t0, t1):
    """Факт живой h24 (свои выходы по сроку) за то же окно."""
    trades, _m = PT.book_trades(os.path.join(s8, "model_h24"))
    out = {}
    for arm in ("gbm", "nn"):
        rows = [t for t in trades if t.get("arm") == arm
                and t.get("t_money") and t0 <= t["t_money"] <= t1]
        out[arm] = {"n": len(rows),
                    "pnl": round(sum(t["pnl"] for t in rows), 2)}
    return out


def fmt(v, spec="+.2f", dash="—"):
    if v is None:
        return dash
    return format(v, spec)


def write_report(path, cells, base, meta):
    L = ["# Реплей корзины без отдельных выходов: одна цель, один "
         "предел\n",
         f"\nПрогон {meta['when']} · окно {meta['span']} · часов "
         f"{meta['hours']} · нога {LEG_USD:.2f} $ при капитале "
         f"{CAPITAL:.0f} · круг {TR.ROUND_COST_BP:g} б.п. на ногу\n",
         "\n**Диагностика, не вердикт.** Записи ~2.5 недели одного "
         "режима (внутри слив 08-24…27); выбрать лучшую ячейку из "
         "двадцати после чтения — ошибка R5. Проверка порога часовая, "
         "как у живых корзинных книг: внутри часа порог может быть "
         "перелетён. Корзина, не закрывшаяся к концу записи, — "
         "отметкой отдельно, не в реализованном.\n"]
    for arm in ("gbm", "nn"):
        rows = cells.get(arm) or []
        if not rows:
            continue
        b = base.get(arm) or {}
        L.append(f"\n## Рука {arm} — факт живой h24 за то же окно: "
                 f"{fmt(b.get('pnl'))} $ на {b.get('n', 0)} закрытых "
                 f"(свои выходы по сроку)\n\n")
        L.append("| цель | предел | закрытий (цель/предел) | "
                 "реализовано, $ | хвост открыт: ног | отметка, $ | "
                 "худшая корзина | медиана возраста, ч | макс | "
                 "просадка, $ | пропуски (кассы/имени/встречных) |\n")
        L.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|\n")
        for c in rows:
            sk = c["skipped"]
            L.append(
                f"| +{c['take']:.1%} | "
                f"{('−' + format(c['floor'], '.1%')) if c['floor'] else 'нет'} | "
                f"{c['n_take']}/{c['n_floor']} | "
                f"**{c['realized']:+.2f}** | {c['open_legs']} | "
                f"{fmt(c['open_mark'])} | {fmt(c['worst_basket'])} | "
                f"{c['age_med_h'] if c['age_med_h'] is not None else '—'} | "
                f"{c['age_max_h'] if c['age_max_h'] is not None else '—'} | "
                f"{c['max_dd']:+.2f} | "
                f"{sk['no_cash']}/{sk['name_cap']}/{sk['opposite']} |\n")
        best = max(rows, key=lambda c: c["realized"]
                   + (c["open_mark"] or 0.0))
        L.append(f"\nЛучшая ячейка по «реализовано + отметка хвоста»: "
                 f"цель +{best['take']:.1%}, предел "
                 f"{('−' + format(best['floor'], '.1%')) if best['floor'] else 'нет'} "
                 f"→ {best['realized']:+.2f} $ реализовано"
                 + (f" и {best['open_mark']:+.2f} $ отметкой"
                    if best['open_mark'] is not None else "")
                 + ". **Названа как диагностика: выбор лучшей из "
                 "двадцати по 2.5 неделям — ошибка R5, а не правило "
                 "книги.**\n")
    L.append("\n**Что конструкция делает с кассой, видно в колонке "
             "пропусков:** без отдельных выходов книга наполняется до "
             "гросса и стоит вложенной до закрытия корзины — новые "
             "сигналы в это время получают размер 0. Это не дефект "
             "реплея, а свойство самой конструкции, и жить с ним "
             "придётся и живой книге.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="корзина без своих выходов")
    ap.add_argument("--s8", default=os.path.join(
        ROOT, "research", "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)

    picks = load_picks(os.path.join(a.s8, "model_h24"))
    if not picks:
        log_("выборов model_h24 нет — считать нечего")
        return 1
    syms = {g["sym"] for by in picks.values()
            for legs in by.values() for g in legs}
    mids = BK.load_mids(syms)
    lo = min(min(by) for by in picks.values())
    hi = max(max(by) for by in picks.values())
    cells, spans = {}, []
    for arm, by in sorted(picks.items()):
        rows = []
        for take in TAKES:
            for floor in FLOORS:
                c = replay(by, mids, take, floor)
                if c:
                    rows.append(c)
        cells[arm] = rows
        log_(f"{arm}: часов {len(by)}, ячеек {len(rows)}")
    base = baseline(a.s8, lo, hi + 86400 * 2)

    art = {"leg_usd": LEG_USD, "capital": CAPITAL,
           "cells": {arm: rows for arm, rows in cells.items()},
           "baseline": base,
           "took_sec": round(time.time() - t0, 1)}
    with open(os.path.join(out_dir, f"basket-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    span = (datetime.fromtimestamp(lo, timezone.utc)
            .strftime("%Y-%m-%d %H:%M") + " … "
            + datetime.fromtimestamp(hi, timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"))
    path = write_report(
        os.path.join(out_dir, f"BASKET-report-{a.tag}.md"),
        cells, base,
        {"when": datetime.now(timezone.utc)
         .strftime("%Y-%m-%d %H:%M UTC"), "span": span,
         "hours": (hi - lo) // HOUR})
    log_(f"отчёт: {path} · {art['took_sec']} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
