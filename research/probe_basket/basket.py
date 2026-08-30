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

# Вторая серия (вопрос владельца): лимит ВОЗРАСТА корзины и правило
# «один минус в день». Оси объявлены до прогона; базовый вариант
# (None, False) обязан совпадать с первой серией бит в бит.
# 24 ч — горизонт сигнала (дальше модель ничего не утверждала),
# 48 ч — вдвое; «минусовое» закрытие — любое закрытие корзины с
# отрицательным итогом (предел ИЛИ возраст), после него новые входы
# не берутся до конца суток UTC — родня живого дневного тормоза,
# только событием, а не суммой дня.
AGES = (None, 24, 48)
ONE_LOSS = (False, True)


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


def replay(picks, mids, take, floor, capital=CAPITAL, leg_usd=LEG_USD,
           age_h=None, one_loss_day=False):
    """Одна ячейка: корзина закрывается ТОЛЬКО целиком.

    Порядок такта — как у живой корзины: сперва решение по порогу на
    отметке часа, потом входы этого часа. Порог сравнивается с
    нереализованным результатом всей корзины в долях капитала.

    Два правила второй серии, оба выключены по умолчанию (база — бит
    в бит первая серия): `age_h` — корзина старше стольких часов
    закрывается целиком по отметке (приоритет у порогов: задетая цель
    или предел называются своим именем, возраст решает только когда
    пороги молчат); `one_loss_day` — после закрытия корзины в минус
    новые входы не берутся до конца суток UTC (вход — возможность,
    закрытие корзины правилом не гасится никогда).
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
               "no_price": 0, "loss_day": 0}
    blocked_hours = 0
    basket_open_ts = None
    last_loss_day = None
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
                hit_age = (age_h is not None
                           and ts - basket_open_ts >= age_h * HOUR)
                if hit_take or hit_floor or hit_age:
                    realized += unreal
                    baskets.append({
                        "why": ("take" if hit_take
                                else "floor" if hit_floor else "age"),
                        "pnl": round(unreal, 2), "legs": len(legs),
                        "age_h": (ts - basket_open_ts) // HOUR})
                    if unreal < 0:
                        last_loss_day = ts // 86400
                    legs, basket_open_ts = [], None
                eq = realized + (0.0 if not legs else unreal)
                equity_peak = max(equity_peak, eq)
                max_dd = min(max_dd, eq - equity_peak)
                curve.append(eq)
        # 2) входы часа
        for g in picks.get(ts) or []:
            if (one_loss_day and last_loss_day is not None
                    and ts // 86400 == last_loss_day):
                skipped["loss_day"] += 1
                continue
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
    n_floor = sum(1 for b in baskets if b["why"] == "floor")
    n_age = sum(1 for b in baskets if b["why"] == "age")
    return {"take": take, "floor": floor,
            "age_h_lim": age_h, "one_loss_day": one_loss_day,
            "n_age": n_age,
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


VARIANTS = [(a, o) for o in ONE_LOSS for a in AGES]


def vlabel(age, ol):
    base = "без лимита" if age is None else f"возраст ≤ {age} ч"
    return base + (" + один минус/день" if ol else "")


def total_of(c):
    return c["realized"] + (c["open_mark"] or 0.0)


def med(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return None
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def write_rules_report(path, arms, base_fact, meta):
    """arms: {arm: {(age, ol): {(take, floor): cell}}}."""
    L = ["# Корзина: лимит возраста и «один минус в день»\n",
         f"\nПрогон {meta['when']} · окно {meta['span']} · часов "
         f"{meta['hours']} · нога {LEG_USD:.2f} $ при капитале "
         f"{CAPITAL:.0f} · круг {TR.ROUND_COST_BP:g} б.п. на ногу\n",
         "\nВопрос владельца ко второй серии: что меняют лимит "
         "времени удержания корзины и запрет новых входов после "
         "одного минусового закрытия за сутки. Оси объявлены до "
         "прогона: возраст {нет, 24, 48 ч} × правило минуса "
         "{выкл, вкл}; base = первая серия. Сравнение ПАРНОЕ — тот "
         "же (цель, предел), итог = реализовано + отметка хвоста.\n",
         "\n**Диагностика, не вердикт: те же ~3 недели одного "
         "режима, выбор лучшей ячейки — ошибка R5.** Лимит 24 ч "
         "возвращает конструкцию к книге со сроком (ноги живут не "
         "дольше горизонта сигнала), «один минус/день» — родня "
         "живого дневного тормоза, событием вместо суммы.\n"]
    for arm in sorted(arms):
        by_var = arms[arm]
        base = by_var.get((None, False)) or {}
        if not base:
            continue
        bf = base_fact.get(arm) or {}
        L.append(f"\n## Рука {arm} — факт живой h24 за то же окно: "
                 f"{fmt(bf.get('pnl'))} $ на {bf.get('n', 0)} "
                 f"закрытых\n\n")
        L.append("| вариант | медиана итога, $ | парная Δ к базе "
                 "(медиана) | ячеек лучше базы | лучшая ячейка | "
                 "худшая корзина | пропуски кассы (мед.) | закрытий "
                 "(мед.) | возраст макс (мед.) |\n")
        L.append("|--|--:|--:|--:|--|--:|--:|--:|--:|\n")
        for var in VARIANTS:
            rows = by_var.get(var)
            if not rows:
                continue
            keys = sorted(rows, key=lambda k: (k[0], k[1] or 9.9))
            tot = {k: total_of(rows[k]) for k in keys}
            deltas = [tot[k] - total_of(base[k]) for k in keys
                      if k in base]
            best_k = max(keys, key=lambda k: tot[k])
            worst = min((rows[k]["worst_basket"] for k in keys
                         if rows[k]["worst_basket"] is not None),
                        default=None)
            L.append(
                f"| {vlabel(*var)} | {fmt(med(list(tot.values())))} | "
                f"{fmt(med(deltas)) if var != (None, False) else '—'} | "
                f"{(sum(1 for d in deltas if d > 0)) if var != (None, False) else '—'}"
                f"{'/' + str(len(deltas)) if var != (None, False) else ''} | "
                f"+{best_k[0]:.1%}/"
                f"{('−' + format(best_k[1], '.1%')) if best_k[1] else 'нет'}"
                f" → {tot[best_k]:+.2f} | {fmt(worst)} | "
                f"{med([rows[k]['skipped']['no_cash'] for k in keys]):g} | "
                f"{med([rows[k]['baskets'] for k in keys]):g} | "
                f"{med([rows[k]['age_max_h'] or 0 for k in keys]):g} |\n")
        L.append("\nИтог каждой ячейки по вариантам (реализовано + "
                 "отметка хвоста, $):\n\n")
        hdr = " | ".join(vlabel(*v) for v in VARIANTS)
        L.append(f"| цель | предел | {hdr} |\n")
        L.append("|--:|--:|" + "--:|" * len(VARIANTS) + "\n")
        for k in sorted(base, key=lambda k: (k[0], k[1] or 9.9)):
            cells = []
            for var in VARIANTS:
                c = (by_var.get(var) or {}).get(k)
                cells.append(f"{total_of(c):+.2f}" if c else "—")
            L.append(
                f"| +{k[0]:.1%} | "
                f"{('−' + format(k[1], '.1%')) if k[1] else 'нет'} | "
                + " | ".join(cells) + " |\n")
    L.append("\nПропуски кассы («сигнал получил размер 0») — мера "
             "слепоты вложенной книги: лимит возраста обязан её "
             "снижать, и насколько — видно в колонке. «Один "
             "минус/день» режет входы после минусового закрытия; "
             "его цена и польза — та же парная Δ.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="корзина без своих выходов")
    ap.add_argument("--s8", default=os.path.join(
        ROOT, "research", "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--rules", action="store_true",
                    help="вторая серия: возраст × один минус/день")
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
    base = baseline(a.s8, lo, hi + 86400 * 2)
    span = (datetime.fromtimestamp(lo, timezone.utc)
            .strftime("%Y-%m-%d %H:%M") + " … "
            + datetime.fromtimestamp(hi, timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"))
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"), "span": span,
            "hours": (hi - lo) // HOUR}

    if a.rules:
        arms = {}
        for arm, by in sorted(picks.items()):
            by_var = {}
            for var in VARIANTS:
                rows = {}
                for take in TAKES:
                    for floor in FLOORS:
                        c = replay(by, mids, take, floor,
                                   age_h=var[0], one_loss_day=var[1])
                        if c:
                            rows[(take, floor)] = c
                by_var[var] = rows
            arms[arm] = by_var
            log_(f"{arm}: часов {len(by)}, вариантов {len(by_var)}")
        art = {"leg_usd": LEG_USD, "capital": CAPITAL,
               "variants": {
                   arm: {vlabel(*v): list(rows.values())
                         for v, rows in by_var.items()}
                   for arm, by_var in arms.items()},
               "baseline": base,
               "took_sec": round(time.time() - t0, 1)}
        with open(os.path.join(out_dir, f"basket-rules-{a.tag}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(art, f, ensure_ascii=False, indent=1)
        path = write_rules_report(
            os.path.join(out_dir, f"BASKET-rules-{a.tag}.md"),
            arms, base, meta)
    else:
        cells = {}
        for arm, by in sorted(picks.items()):
            rows = []
            for take in TAKES:
                for floor in FLOORS:
                    c = replay(by, mids, take, floor)
                    if c:
                        rows.append(c)
            cells[arm] = rows
            log_(f"{arm}: часов {len(by)}, ячеек {len(rows)}")
        art = {"leg_usd": LEG_USD, "capital": CAPITAL,
               "cells": {arm: rows for arm, rows in cells.items()},
               "baseline": base,
               "took_sec": round(time.time() - t0, 1)}
        with open(os.path.join(out_dir, f"basket-{a.tag}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(art, f, ensure_ascii=False, indent=1)
        path = write_report(
            os.path.join(out_dir, f"BASKET-report-{a.tag}.md"),
            cells, base, meta)
    log_(f"отчёт: {path} · {round(time.time() - t0, 1)} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
