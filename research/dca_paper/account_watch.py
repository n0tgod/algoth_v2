#!/usr/bin/env python3
"""Слежение за счётом книг между прогонами (владелец 19.10: «нужно поставить
какое-то слежение за счётом, дабы не было непонятных скачков»).

Каждый прогон семейства (длинные, короткие, общий счёт) ПЕРЕД записью
артефакта сверяет новый свод с прошлым по каждой ячейке «книга:депозит
[:формат]» и называет словами каждое расхождение, которое читатель иначе
увидел бы как скачок:

* **закрылась, не побывав открытой** — в закрытых появилась позиция,
  которой не было в открытых прошлого свода. Две причины, обе печатаются:
  вход позже прошлого прогона (позиция прожила меньше одного такта —
  честный случай короткой жизни) либо вход был раньше, а в открытых её
  не было (кассе не хватило денег в тот прогон или сборщик её ещё не
  видел) — это и есть «из ниоткуда»;
* **итог изменился без новых сделок** — приращение итога закрытых не
  сходится с суммой новых закрытых сделок: пересчёт истории под теми же
  ключами;
* **открытая исчезла без закрытия** — была в открытых, нет ни в открытых,
  ни в новых закрытых: позицию отняла касса или правило;
* **открытая появилась задним числом** — вход раньше прошлого прогона, а в
  прошлых открытых её не было.

Состояние — своё на семейство, слим: `out/watch/<семейство>.json`
(по ячейке: итог, число закрытых, ключи закрытых хвоста, открытые с
отметкой). Находки идут в свод (`s["watch"]`) — на страницу и в
приложение, — и в `out/watch/log.jsonl` (хвост, в git). Ничего не
пересчитывает: сравнивает числа, которые уже посчитал прогон.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH_DIR = os.path.join(HERE, "out", "watch")
LOG = os.path.join(WATCH_DIR, "log.jsonl")
LATEST = os.path.join(WATCH_DIR, "latest.json")
LOG_KEEP = 2000
TOL_ABS = 0.05          # $: сумма новых сделок против приращения итога
TOL_REL = 0.002         # доля |итога|


def pos_key(p):
    return f"{p.get('sym')}:{int(float(p.get('at') or 0))}"


CLOSED_KEEP_S = 14 * 86400     # закрытые в состоянии — за 14 суток входа: дольше 72 ч позиция не живёт


def _recent(closed):
    """Закрытые за окно `CLOSED_KEEP_S` от самого свежего входа ячейки.

    Состояние «все закрытые за всю историю» есть O(запись): у общего счёта
    оно доросло до 5 МБ (20.10) и перестало публиковаться. Новая закрытая
    всегда свежая (вход не старше срока); старый ключ, всплывший заново, —
    пересчёт истории, и его ловит сверка итога (`recount`)."""
    if not closed:
        return {}
    ats = {k: float(k.rsplit(":", 1)[1]) for k in closed}
    edge = max(ats.values()) - CLOSED_KEEP_S
    return {k: v for k, v in closed.items() if ats[k] >= edge}


def slim(s):
    """Слим-состояние свода: по ячейке — итог, закрытые хвоста, открытые."""
    out = {}
    closed_all = s.get("_closed") or {}
    for cell, b in (s.get("books") or {}).items():
        a = b.get("all") or {}
        o = b.get("open") or {}
        out[cell] = {"n": a.get("n"), "usd": a.get("usd"),
                     "closed": _recent(dict(closed_all.get(cell) or {})),
                     "open": {pos_key(p): {"sym": p.get("sym"), "at": p.get("at"),
                                           "mark_usd": p.get("mark_usd"), "margin": p.get("margin")}
                              for p in (o.get("positions") or [])}}
    return out


def compare(prev, cur, prev_at, now, family):
    """Находки между двумя слим-состояниями; prev=None — первый срез, находок нет."""
    finds = []
    if not prev:
        return finds
    for cell, c in cur.items():
        p = prev.get(cell)
        if not p:
            continue
        p_edge = min((float(k.rsplit(":", 1)[1]) for k in p["closed"]), default=None)
        new_closed = {k: v for k, v in c["closed"].items() if k not in p["closed"]
                      and (p_edge is None or float(k.rsplit(":", 1)[1]) >= p_edge or k in p["open"])}
        for k, usd in new_closed.items():
            if k in p["open"]:
                continue
            at = float(k.rsplit(":", 1)[1])
            if at >= prev_at:
                why, code = "вход позже прошлого прогона: позиция прожила меньше одного такта", "short_life"
            else:
                why, code = ("вход был до прошлого прогона, а в открытых её не было: "
                             "в тот прогон её не взяла касса или не видел сборщик", "unseen")
            finds.append({"t": now, "family": family, "cell": cell, "kind": "closed_unseen",
                          "pos": k, "sym": k.split(":")[0], "at": at, "usd": usd,
                          "why": why, "why_code": code,
                          "text": f"закрылась, не побывав открытой: {k.split(':')[0]} ({usd:+.2f} $) — {why}"
                          if usd is not None else f"закрылась, не побывав открытой: {k.split(':')[0]} — {why}"})
        if p.get("usd") is not None and c.get("usd") is not None:
            d_usd = float(c["usd"]) - float(p["usd"])
            s_new = sum(float(v) for v in new_closed.values() if v is not None)
            gap = d_usd - s_new
            tol = max(TOL_ABS, TOL_REL * abs(float(c["usd"])))
            if abs(gap) > tol:
                finds.append({"t": now, "family": family, "cell": cell, "kind": "recount",
                              "gap_usd": round(gap, 2), "new_closed": len(new_closed),
                              "d_usd": round(d_usd, 2), "d_n": (c.get("n") or 0) - (p.get("n") or 0),
                              "text": f"итог изменился на {d_usd:+.2f} $, новые закрытые дают {s_new:+.2f} $: "
                                      f"пересчёт истории на {gap:+.2f} $ (закрытых {p.get('n')} → {c.get('n')})"})
        for k, op in p["open"].items():
            if k not in c["open"] and k not in c["closed"]:
                finds.append({"t": now, "family": family, "cell": cell, "kind": "open_vanished", "pos": k,
                              "sym": op.get("sym"), "at": op.get("at"), "mark_usd": op.get("mark_usd"),
                              "text": f"открытая исчезла без закрытия: {op.get('sym')} (вход {time.strftime('%m-%d %H:%M', time.gmtime(float(op.get('at') or 0)))} UTC, "
                                      f"отметка была {op.get('mark_usd')})"})
        for k, op in c["open"].items():
            if k not in p["open"] and float(op.get("at") or 0) < prev_at:
                finds.append({"t": now, "family": family, "cell": cell, "kind": "open_late", "pos": k,
                              "sym": op.get("sym"), "at": op.get("at"),
                              "text": f"открытая появилась задним числом: {op.get('sym')} (вход "
                                      f"{time.strftime('%m-%d %H:%M', time.gmtime(float(op.get('at') or 0)))} UTC, прошлый прогон её не показывал)"})
    return finds


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def check(s, family, now=None, watch_dir=WATCH_DIR, log=print):
    """Сверить свод семейства с прошлым, записать состояние и находки.
    → блок для свода: {at, prev_at, cells, findings, n}."""
    now = float(now if now is not None else time.time())
    os.makedirs(watch_dir, exist_ok=True)
    state_path = os.path.join(watch_dir, f"{family}.json")
    prev = _load(state_path, None)
    cur = slim(s)
    s.pop("_closed", None)               # служебное поле в артефакт не идёт
    finds = compare(prev.get("cells") if prev else None, cur, float(prev.get("at") or 0) if prev else 0.0, now, family)
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"at": now, "family": family, "cells": cur}, f, ensure_ascii=False)
    os.replace(tmp, state_path)
    if finds:
        lp = os.path.join(watch_dir, "log.jsonl")
        old = []
        if os.path.exists(lp):
            with open(lp, encoding="utf-8") as f:
                old = [x for x in f.read().splitlines() if x.strip()]
        with open(lp + ".tmp", "w", encoding="utf-8") as f:
            f.write("\n".join(old[-(LOG_KEEP - len(finds)):] + [json.dumps(x, ensure_ascii=False) for x in finds]) + "\n")
        os.replace(lp + ".tmp", lp)
        for x in finds:
            log(f"слежение за счётом [{x['cell']}]: {x['text']}")
    recent = [json.loads(x) for x in _load_lines(os.path.join(watch_dir, "log.jsonl"))[-400:]]
    recent = [x for x in recent if x.get("t", 0) >= now - 86400]
    block = {"at": now, "prev_at": (prev or {}).get("at"), "cells": len(cur), "findings": finds,
             "n": len(finds), "day": {"n": len(recent), "by_kind": _count(recent, "kind"),
                                      "items": recent[-60:]}}
    with open(os.path.join(watch_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(block, f, ensure_ascii=False)
    return block


def safe_check(s, family, **kw):
    """check(), который не вправе уронить прогон: отказ идёт в свод словами
    (`error`), а не в тишину — читатель видит «слежение не сработало: …»."""
    try:
        return check(s, family, **kw)
    except Exception as e:                                   # noqa: BLE001
        s.pop("_closed", None)
        msg = f"слежение за счётом не сработало: {type(e).__name__}: {e}"
        print(msg)
        return {"at": time.time(), "family": family, "error": msg, "n": 0, "findings": []}


def merge(blocks):
    """Свести блоки `watch` семейств в один для страницы и приложения:
    находки суток одним списком (по ячейке читатель отберёт сам), у каждого
    семейства — время, число ячеек и отказ словами; семейство без блока —
    «не велось», и это печатается, а не молчит."""
    fams, items, errors = {}, [], []
    for fam, b in blocks:
        if not isinstance(b, dict):
            fams[fam] = None
            continue
        fams[fam] = {"at": b.get("at"), "cells": b.get("cells"), "n": b.get("n"),
                     "error": b.get("error")}
        if b.get("error"):
            errors.append(f"{fam}: {b['error']}")
        items.extend((b.get("day") or {}).get("items") or [])
    items.sort(key=lambda x: float(x.get("t") or 0))
    ats = [f["at"] for f in fams.values() if f and f.get("at")]
    return {"at": max(ats) if ats else None, "families": fams, "errors": errors,
            "n": len(items), "items": items[-120:],
            "by_kind": _count(items, "kind")}


def _load_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [x for x in f.read().splitlines() if x.strip()]
    except OSError:
        return []


def _count(xs, key):
    out = {}
    for x in xs:
        out[x.get(key)] = out.get(x.get(key), 0) + 1
    return out
