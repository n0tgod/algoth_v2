#!/usr/bin/env python3
"""
Цена правила «одно имя — одна позиция»: пересчёт по записанным сделкам.

Замечание владельца, из которого всё выросло: на одном аккаунте нельзя
держать несколько отдельных лонгов по одной паре. Можно долить в
позицию, можно держать хедж лонг+шорт, можно открыть второй лонг после
закрытия первого. Наши четырёхчасовые книги входят каждый час и держат
до ЧЕТЫРЁХ лотов на имени — то есть моделируют то, чего биржа не умеет.

Считаются три варианта, и ни один из них не правит кассу: это замер,
после которого решение принимает владелец.

  hedge   — лоты одной стороны складываются в одну позицию, лонг и
            шорт по имени живут одновременно (хедж-режим Bybit).
            ДЕНЬГИ РОВНО ТЕ ЖЕ, что сейчас: PnL линеен, и четыре лота,
            купленные по разным ценам и закрытые в разное время, дают
            ту же сумму, что долив в одну позицию. Меняется маржа, а
            не результат, поэтому вариант присутствует как ноль
            отсчёта, а не как «ещё один прогон».
  netting — то же, но противоположная сторона СХЛОПЫВАЕТ позицию
            (односторонний режим, умолчание биржи): новый шорт по
            имени с открытым лонгом закрывает лот досрочно и своей
            позиции не открывает.
  one     — пока по имени есть открытая позиция, новый вход не берётся
            вовсе.

Цена досрочного закрытия берётся из цены входа той сделки, которая его
вызвала: обе на одном имени в один момент, и это ровно та цена, по
которой биржа схлопнула бы позицию. Издержки досрочно закрытого лота
оставляются его собственные — величина того же порядка, и выдумывать
для неё второй расчёт незачем; допущение названо в отчёте.

Счёт пересчитывается НАСТОЯЩЕЙ кассой (`trades.account`) по каждому
варианту: вторая реализация счёта разошлась бы с первой.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trades as TR                                       # noqa: E402

RULES = ("hedge", "netting", "one")


def _end(t):
    return t.get("exit_ts") or t.get("closes_at") or 0


def apply_rule(rows, rule):
    """Список сделок под выбранным правилом; исходный не трогается."""
    # Правило разбирается ПО ВРЕМЕНИ, а список возвращается в ИСХОДНОМ
    # порядке. Касса сортирует события по целой секунде, а внутри
    # секунды очередь за деньгами задаёт порядок входного списка
    # (сортировка стабильна). В книге 4 ч 79 секунд несут несколько
    # входов, до двенадцати разом, — пересортировка меняла размеры и
    # уводила итог на 76 долларов. Замер, меняющий не то, что
    # объявлено, есть другой замер.
    out, open_by = [], {}
    keep = set()
    order = sorted(range(len(rows)),
                   key=lambda i: (rows[i].get("opened_at") or 0,
                                  rows[i].get("sym") or ""))
    early = {}
    for i in order:
        t = dict(rows[i])
        sym = t.get("sym")
        now = t.get("opened_at") or 0
        # Снимаем с учёта то, что к этому моменту уже закрылось.
        live = [q for q in open_by.get(sym, []) if _end(q) > now]
        open_by[sym] = live
        t["_i"] = i
        clash = [q for q in live if q.get("side") != t.get("side")]
        if rule == "one" and live:
            continue                       # вход не берётся вовсе
        if rule == "netting" and clash:
            # Схлопывание: самый старый встречный лот закрывается ЗДЕСЬ
            # и по ЭТОЙ цене, а новая позиция не открывается.
            victim = min(clash, key=lambda q: q.get("opened_at") or 0)
            vi = victim["_i"]
            px0, px1 = victim.get("entry_px"), t.get("entry_px")
            if px0 and px1:
                sign = 1.0 if victim.get("side") == "long" else -1.0
                move = sign * (px1 / px0 - 1.0) * 1e4
                cost = victim.get("exec_bp")
                if cost is None:
                    cost = TR.ROUND_COST_BP
                early[vi] = {"net_bp": round(move - cost, 1),
                             "closes_at": now, "exit_ts": now,
                             "state": "закрыта", "netted": True}
            live.remove(victim)
            continue
        keep.add(i)
        live.append(t)
    for i in sorted(keep):
        t = dict(rows[i])
        t.update(early.get(i) or {})
        out.append(t)
    return out


def stats(rows, arm, slots=None, hold_h=TR.HOLD_H):
    tr = [dict(t) for t in rows if t.get("arm") == arm]
    if not tr:
        return None
    # Издержки остаются ТЕМИ, что записаны прогоном. Лесенки книги
    # лежат в строках, и касса пересчитала бы круг по локальному
    # тарифу — это вторая переменная в замере одной правки, и она уже
    # разошлась с сервером на 81 доллар. Снимаем лесенки: тогда
    # `exec_cost` возвращает None и `net_bp` остаётся записанным.
    for t in tr:
        t.pop("cum_in", None)
        t.pop("cum_out", None)
    _, bal = TR.account(tr, arm, hold_h=hold_h, slots=slots)
    closed = [t for t in tr if t.get("state") == "закрыта"
              and t.get("pnl") is not None]
    pnl = sum(t["pnl"] for t in closed)
    by = {}
    for t in closed:
        by[t["sym"]] = by.get(t["sym"], 0.0) + t["pnl"]
    top = max(by.values()) if by else 0.0
    return {"trades": len(tr), "closed": len(closed),
            "pnl": round(pnl, 2), "balance": bal,
            "names": len(by),
            "top_name": max(by, key=by.get) if by else None,
            "top_pnl": round(top, 2),
            "without_top": round(pnl - top, 2),
            "win": round(sum(1 for t in closed if t["pnl"] > 0)
                         / len(closed), 3) if closed else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", help="выгрузка /model_trades (JSON)")
    ap.add_argument("--book", help="каталог книги на диске")
    ap.add_argument("--slots", type=int)
    ap.add_argument("--hold", type=int, default=TR.HOLD_H)
    ap.add_argument("--out")
    a = ap.parse_args()

    if a.rows:
        with open(a.rows, encoding="utf-8") as f:
            d = json.load(f)
        rows = d.get("rows") or []
        hold = d.get("horizon_h") or a.hold
    else:
        mdir = a.book
        picks = [json.loads(x) for x in
                 open(os.path.join(mdir, "picks.jsonl"), encoding="utf-8")
                 if x.strip()]
        revs = [json.loads(x) for x in
                open(os.path.join(mdir, "review.jsonl"), encoding="utf-8")
                if x.strip()]
        hold = a.hold
        rows = TR.build(picks, revs, hold_h=hold)
    rows = [t for t in rows if t.get("opened_at")]

    live = round(sum(t["pnl"] for t in rows
                     if t.get("state") == "закрыта"
                     and t.get("pnl") is not None), 2)
    res = {"live_pnl": live}
    for rule in RULES:
        sub = apply_rule(rows, rule)
        res[rule] = {arm: stats(sub, arm, a.slots, hold)
                     for arm in ("gbm", "nn")}
    got = round(sum(v["pnl"] for v in res["hedge"].values() if v), 2)
    # Сверка замера: складывание лотов одной стороны денег не меняет,
    # поэтому «хедж» ОБЯЗАН воспроизвести живой итог. Не сошлось —
    # в пересчёте есть вторая переменная, и сравнивать правила нельзя.
    res["hedge_matches_live"] = abs(got - live) < 0.02
    if not res["hedge_matches_live"]:
        print(f"ВНИМАНИЕ: хедж дал {got}, живой итог {live}",
              file=sys.stderr)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
