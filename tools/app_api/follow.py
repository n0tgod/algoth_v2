"""Сухой исполнитель-следователь (спека 15, Y2 в сухом режиме).

Что делает. Для каждой активной подписки берёт из свода книг (`/dca`
сборщика) ячейку подписки — книга × депозит × формат размера — и
превращает её позиции в события журнала исполнителя (§7.6): первый
рунг — `entry`, каждый следующий — `rung` (с глубиной и новой средней)
и `take_set` (цель переехала вместе с ТВХ), исход — `take` / `floor` /
`term` / `market` / `liq` с ценой выхода и нетто. События пишутся в
`bot/out/dca/<subscription_id>/events.jsonl` с растущим `seq` — тем же
форматом, который будет писать живой исполнитель, — и дальше идут той
же дорогой: приём → запись `trades` → пуш на телефон → вкладка Trades.

Чего НЕ делает. Денег не считает (маржа, pnl, уровни — числа книги как
записаны; `paper_margin_usd` так и назван), на биржу ничего не шлёт
(`mode: "dry"`). Позиции, открытые ДО подписки, не ведёт: подписка
входит со следующего входа (§2). Решения приходят с часовым прогоном
книг — события несут время РЕШЕНИЯ (`ts` — секунда заполнения или
выхода), а не время записи.

Дедуп — состоянием подписки (`state_json.follow.seen`: по ключу
позиции сколько рунгов и закрытие уже отданы): повторное чтение свода
ничего не дублирует; хвост `trades` свода — 200 последних, у ячейки с
часовым шагом этого хватает на часы вперёд, а пропуск считается и
называется (`follow.gaps`).
"""
import json
import os
import time

EXIT_KINDS = {"тейк": "take", "пол": "floor", "срок": "term",
              "рынок": "market", "ликвидация": "liq", "команда": "cmd_close"}


def cell_key(book, deposit, sizing):
    k = f"{book}:{int(float(deposit))}"
    return k if (sizing or "compound") == "compound" else f"{k}:{sizing}"


def pos_key(p):
    return f"{p.get('sym')}:{int(float(p.get('at') or 0))}"


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def events_for(p, seen, since, closed):
    """События одной позиции сверх уже отданных. `seen` — {"fills": n,
    "closed": bool}; возвращает (события, новое seen)."""
    at = _f(p.get("at"))
    if at is None or at < since:
        return [], seen
    fills = p.get("fills") or []
    walk = p.get("walk") or []
    n_seen = int(seen.get("fills") or 0)
    out = []
    depth_n = len(fills)
    lv = p.get("levels") or {}
    base = {"mode": "dry", "sym": p.get("sym"), "side": p.get("side"),
            "lev": _f(p.get("lev")), "paper_margin_usd": _f(p.get("margin")),
            "margin_usd": _f(p.get("margin")),
            # уровни строки книги (Y1): пол и ликвидация — как записаны
            "floor_px": _f(lv.get("floor_px")), "liq_px": _f(lv.get("liq_px"))}
    for i in range(n_seen, len(fills)):
        f = fills[i]
        w = walk[i] if i < len(walk) else {}
        ts, px = _f(f[0]) if len(f) > 0 else None, _f(f[1]) if len(f) > 1 else None
        ev = dict(base, ts=ts or at, px=px, qty=_f(w.get("dq")), avg=_f(w.get("avg")),
                  depth=f"{i + 1}/{depth_n}", take_px=_f(w.get("take")))
        if i == 0:
            ev["ev"] = "entry"
            ev["term_ts"] = _f(p.get("sched_end"))
            out.append(ev)
        else:
            ev["ev"] = "rung"
            out.append(ev)
            if w.get("take") is not None:
                out.append(dict(base, ev="take_set", ts=ts or at, px=_f(w.get("take")),
                                avg=_f(w.get("avg")), depth=f"{i + 1}/{depth_n}"))
    new = {"fills": max(n_seen, len(fills)), "closed": bool(seen.get("closed"))}
    if closed and not seen.get("closed"):
        kind = EXIT_KINDS.get(str(p.get("exit") or ""), "cmd_close" if p.get("exit") else None)
        if kind:
            pf, lev = _f(p.get("pnl_frac")), _f(p.get("lev"))
            out.append(dict(base, ev=kind, ts=_f(p.get("exit_ts")) or at, px=_f(p.get("exit_px")),
                            avg=_f(p.get("avg")), depth=f"{depth_n}/{depth_n}",
                            pnl_usd=_f(p.get("usd")),
                            pnl_bp=(round(pf / lev * 1e4, 1) if pf is not None and lev else None),
                            reason=("по котировке хвоста" if p.get("tail") else None)))
            new["closed"] = True
    return out, new


def plan(book, state, since):
    """Все новые события ячейки по своду книги. Возвращает (события
    по времени, новое состояние слежения)."""
    fl = dict(state.get("follow") or {})
    seen = dict(fl.get("seen") or {})
    out = []
    op = ((book.get("open") or {}).get("positions") or [])
    for p in op:
        evs, s2 = events_for(p, seen.get(pos_key(p), {}), since, closed=False)
        out += evs
        seen[pos_key(p)] = s2
    for t in (book.get("trades") or []):
        evs, s2 = events_for(t, seen.get(pos_key(t), {}), since, closed=True)
        out += evs
        seen[pos_key(t)] = s2
    out.sort(key=lambda e: (e.get("ts") or 0, 0 if e["ev"] == "entry" else 1))
    # хвост свода конечен: если самая старая закрытая в хвосте моложе
    # подписки и хвост полон — что-то между могло пройти мимо
    tr = book.get("trades") or []
    gap = bool(tr and len(tr) >= 200 and _f(tr[-1].get("at")) and _f(tr[-1].get("at")) > since
               and book.get("trades_total", 0) > len(tr))
    fl.update({"seen": {k: v for k, v in seen.items()}, "at": time.time(),
               "gaps": int(fl.get("gaps") or 0) + (1 if gap and not fl.get("gap_seen") else 0),
               "gap_seen": gap})
    return out, fl


def append_events(root, sub_id, events):
    """Дописать события с растущим seq; вернуть сколько записано."""
    if not events:
        return 0
    d = os.path.join(root, sub_id)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "events.jsonl")
    seq = 0
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    seq = max(seq, int(json.loads(ln)["seq"]))
                except (ValueError, KeyError, TypeError):
                    pass
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            seq += 1
            f.write(json.dumps(dict(ev, seq=seq, written_at=time.time()), ensure_ascii=False) + "\n")
    return len(events)


def tick(db, dca, root, log=print):
    """Один такт по всем активным подпискам. Возвращает число событий."""
    if not dca or not dca.get("books"):
        return 0
    n = 0
    for s in db.c.execute("SELECT * FROM subscriptions WHERE status='active'").fetchall():
        st = json.loads(s["state_json"] or "{}")
        book = (dca.get("books") or {}).get(cell_key(s["book"], s["deposit"], st.get("sizing")))
        if not book:
            continue
        since = float((st.get("follow") or {}).get("since") or s["created"])
        evs, fl = plan(book, st, since)
        fl["since"] = since
        if evs:
            n += append_events(root, s["id"], evs)
            log(f"следователь {s['book']} {float(s['deposit']):g} $: событий {len(evs)}")
        st["follow"] = fl
        db.set_sub_state(s["id"], st)
    return n
