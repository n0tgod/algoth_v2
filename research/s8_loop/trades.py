#!/usr/bin/env python3
"""
Сделки модели: выбор + разбор фактом = одна сущность с состоянием.

Зачем отдельный модуль
----------------------

Цикл пишет два файла: `picks.jsonl` — кого выбрал, `review.jsonl` — что
из этого вышло. По отдельности это не читается: владелец спрашивает «где
сделки», а видит два списка, между которыми надо соединять глазами.

Сделка здесь — запись со временем входа, стороной, ожиданием, сроком
закрытия и — когда срок прошёл — фактом и деньгами. Пока срок не
наступил, она **открыта**, и у неё есть прогноз, но нет исхода. Это и
есть ответ на «если сделка ещё не состоялась, хочу видеть прогноз».

Чего здесь НЕТ намеренно
------------------------

Арифметики денег. `pnl` каждой сделки считает цикл в момент разбора и
кладёт в `review.jsonl` рядом с исходом. Здесь только соединение по
ключу. Причина та же, по которой сводка бумажных сделок считается ядром
`t3_brackets`, а не своим кодом страницы: две реализации одной формулы
однажды разойдутся, и таблица покажет одно, а баланс другое.

Только стандартная библиотека: это читает страница сборщика, а тянуть
ради неё numpy незачем.
"""

import time
from datetime import datetime, timedelta, timezone

HOLD_H = 4                        # горизонт выбора — цель fwd_4h


def _ts(hour):
    """`2026-08-03-17` → epoch-секунды начала часа."""
    try:
        return datetime.strptime(hour, "%Y-%m-%d-%H").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def _hour_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime(
        "%Y-%m-%d-%H")


def build(picks, reviews, now=None, hold_h=HOLD_H):
    """Сделки из выборов и разборов, свежие сверху.

    `picks` и `reviews` — строки соответствующих `.jsonl`.
    """
    now = now if now is not None else time.time()
    done = {}
    for rv in reviews or []:
        for r in rv.get("rows") or []:
            done[(rv.get("arm") or "gbm", rv.get("hour"), r.get("sym"),
                  r.get("side"))] = (r, rv)
    out = []
    for pk in picks or []:
        arm = pk.get("arm") or "gbm"
        hour = pk.get("hour")
        t0 = _ts(hour)
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                key = (arm, hour, p.get("sym"), side)
                got, rv = done.get(key, (None, None))
                t_close = (t0 + hold_h * 3600) if t0 is not None else None
                tr = {
                    "arm": arm, "hour": hour, "sym": p.get("sym"),
                    "side": side,
                    "opened_at": t0, "closes_at": t_close,
                    "close_hour": (_hour_of(t_close) if t_close
                                   else None),
                    "expected_bp": p.get("fwd"),
                    # Ожидаемый ход ПРОТИВ позиции — то, что модель
                    # обещает пережить. Без него ожидание читается как
                    # обещание пути, а это разные вещи.
                    "mae_bp": p.get("mae"),
                    "odd": p.get("odd"),
                    "ver": pk.get("ver"),
                }
                if got is not None:
                    tr.update(state="закрыта", got_bp=got.get("got"),
                              net_bp=got.get("net"), pnl=got.get("pnl"),
                              pos=got.get("pos"),
                              cost_bp=(rv or {}).get("cost_bp"),
                              hit=(got.get("got") or 0) > 0
                              if side == "long"
                              else (got.get("got") or 0) < 0)
                elif t_close is not None and now >= t_close:
                    # Срок вышел, а разбора нет: час ещё не сведён либо
                    # цель не посчиталась. Это НЕ «закрыта в ноль» —
                    # посчитать её нулём значило бы разбавить статистику
                    # выдумкой (урок оборванных бумажных сделок).
                    tr.update(state="без исхода")
                else:
                    tr.update(state="открыта",
                              closes_in_sec=(t_close - now
                                             if t_close else None))
                out.append(tr)
    out.sort(key=lambda t: (t["opened_at"] or 0), reverse=True)
    return out


def summary(trades, arm=None):
    """Сводка по закрытым: сколько, доля угаданных, деньги.

    Открытые в статистику не входят — у них нет исхода, и считать его
    нулём значило бы разбавить ожидание выдумкой.
    """
    rows = [t for t in trades
            if (arm is None or t["arm"] == arm)]
    closed = [t for t in rows if t["state"] == "закрыта"]
    op = [t for t in rows if t["state"] == "открыта"]
    lost = [t for t in rows if t["state"] == "без исхода"]
    out = {"closed": len(closed), "open": len(op), "no_outcome": len(lost)}
    if not closed:
        return out
    hits = sum(1 for t in closed if t.get("hit"))
    nets = [t.get("net_bp") for t in closed if t.get("net_bp") is not None]
    pnls = [t.get("pnl") for t in closed if t.get("pnl") is not None]
    exps = [t.get("expected_bp") for t in closed
            if t.get("expected_bp") is not None]
    gots = [t.get("got_bp") for t in closed if t.get("got_bp") is not None]
    out.update(
        hit_rate=round(hits / len(closed), 3),
        net_bp_avg=round(sum(nets) / len(nets), 1) if nets else None,
        pnl=round(sum(pnls), 2) if pnls else None,
        expected_avg=round(sum(exps) / len(exps), 1) if exps else None,
        got_avg=round(sum(gots) / len(gots), 1) if gots else None)
    # Насколько ожидание вообще похоже на факт — самое честное число в
    # этой таблице: модель может угадывать знак и при этом обещать
    # вчетверо больше, чем даёт.
    if exps and gots and len(exps) == len(gots):
        out["expected_over_got"] = (
            round(sum(abs(e) for e in exps) / max(
                sum(abs(g) for g in gots), 1e-9), 2))
    return out


def by_symbol(trades, sym):
    """Сделки одной монеты — для меток на её графике."""
    return [t for t in trades if t.get("sym") == sym]
