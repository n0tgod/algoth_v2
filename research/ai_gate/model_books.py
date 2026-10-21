#!/usr/bin/env python3
"""Книги, которые заводит модель (спека 19 §12, решение владельца 2026-10-21).

Владелец: «хочу, чтобы модель сама заводила новые книги, когда находила
интересные наблюдения». Выбор владельца 21.10: порог мягкий, виды оба,
живых ≤ 10, новых ≤ 2 в неделю.

Наблюдения приходят из недельного прохода модели и уже проверены числом:
* правила skip уроков (`lessons.json`, §11.4) — на ВСЕХ разобранных случаях;
* правила входа модели (`entry_rules.json`, §11.8) — по таблице поиска
  (`entry_search.json`, поле `model[].all`).
Код (не модель) решает, родится ли книга: мягкий порог §12.2, пределы
§12.3, подпись правила не повторяется. Рождение — со следующего целого часа
UTC, старт с нуля; правило замораживается.

Каждый день — отставка (§12.5): прожив ≥ 10 суток, книга, чья сумма нетто
за последние 10 полных суток ($10k) ниже суммы основной книги за те же
сутки, отставляется; без позиций 30 суток — простой. И отчёт группой
(§12.6): книга, основная книга на её окне, нуль книги.

Каждый час (`--tick`) — книги ТВХ: для сигналов после рождения считаются
параметры состояния на часах k = 0…W (`entry_search.feature_env` — те же
формулы, что поиск), первый час по условию фиксируется в состоянии
(`out/model_entry.json`, решение не пересматривается), сдвинутый вход
считается реплеем книги (`run_short.replay_cells`, линейка Depth Short),
кэш — `research/dca_paper/cache/recs-model.jsonl`.

Только бумага: API отклоняет подписку на книги корня `lab`, живой
исполнитель их не знает.

    model_books.py [--tick] [--dry] [--no-publish]
"""
import argparse
import calendar
import json
import math
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))

OUT = os.path.join(HERE, "out")
REGISTRY = os.path.join(OUT, "model_books.json")
ENTRY_STATE = os.path.join(OUT, "model_entry.json")
REPORT = os.path.join(OUT, "MODEL-BOOKS.md")
LATEST = os.path.join(OUT, "model_books_latest.json")
TICK = os.path.join(OUT, "record", "model_tick.json")

BASE = "optimal_h"                 # основная книга: Depth Short
CAP_LIVE = 10                      # живых модельных книг (владелец 21.10)
CAP_ENTRY = 3                      # из них книг ТВХ — каждая свой реплей каждый час
PER_WEEK = 2                       # новых за скользящие 7 суток (владелец 21.10)
SOFT_MIN = 10                      # случаев (фильтр) / сработавших (ТВХ) на всём окне
SOFT_P = 0.20                      # случайные не хуже — не больше этой доли из 400
RETIRE_MIN_D = 10                  # прожить до суда отставкой, суток
WINDOW_D = 10                      # окно отставки, полных суток после дня рождения
IDLE_D = 30                        # простой без позиций, суток
DEP = 10000                        # ячейка суда
SEEDS = 20                         # нуль фильтра: случайные фильтры той же доли
EDGE_S = 300                       # сводка часа ложится 2–3 мин — решение по часу не раньше
H = 3600
DAY = 86400
WEEK_S = 7 * DAY


# ------------------------------------------------------------ реестр

def load(path=None):
    try:
        with open(path or REGISTRY, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = {}
    reg.setdefault("books", [])
    return reg


def save(reg, path=None):
    path = path or REGISTRY
    os.makedirs(os.path.dirname(path), exist_ok=True)
    reg["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def sig(kind, rule):
    """Подпись правила: вид, условия (поле, знак, порог), окно."""
    return json.dumps({"kind": kind, "W": rule.get("W") if kind == "entry" else None,
                       "when": sorted([c["field"], c["op"], round(float(c["value"]), 6)] for c in rule["when"])},
                      sort_keys=True, ensure_ascii=False)


def live(reg):
    return [b for b in reg["books"] if b.get("status") == "live"]


def key_of_book(bid):
    return f"{BASE}_{bid}"


def next_id(reg):
    n = [int(str(b["id"])[1:]) for b in reg["books"] if str(b.get("id", "")).startswith("m")]
    return f"m{(max(n) + 1) if n else 1:02d}"


def matches(rule, f):
    """Все условия выполнены; нет числа — не выполнено (как `first_k`)."""
    for c in rule["when"]:
        v = f.get(c["field"])
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return False
        x = float(c["value"])
        if not (v <= x if c["op"] == "<=" else v >= x if c["op"] == ">=" else v < x if c["op"] == "<" else v > x):
            return False
    return True


def rule_text(kind, rule):
    w = " и ".join(f"{c['field']} {c['op']} {float(c['value']):g}" for c in rule["when"])
    return w + (f", окно {rule['W']} ч" if kind == "entry" else "")


# ------------------------------------------------------------ кандидаты и порог

def soft_skip(a):
    """Порог рождения фильтра (§12.2) по итогу урока на ВСЕХ случаях."""
    m = a.get("matched") or 0
    if m < SOFT_MIN:
        return f"подходящих {m} < {SOFT_MIN}"
    if a.get("mean_matched") is None or a.get("mean_rest") is None or not a["mean_matched"] < a["mean_rest"]:
        return "подходящие не хуже остальных"
    p = a.get("p_random")
    if p is None or p > SOFT_P:
        return f"случайные не хуже в {p} > {SOFT_P}"
    return None


def soft_entry(a):
    """Порог рождения книги ТВХ (§12.2) по таблице поиска на всём окне."""
    t = a.get("trig") or 0
    if t < SOFT_MIN:
        return f"сработавших {t} < {SOFT_MIN}"
    if a.get("rule_mean") is None or a.get("book_mean") is None or not a["rule_mean"] > a["book_mean"]:
        return "в час правила не лучше, чем в час сигнала"
    p = a.get("p_random_hour")
    if p is None or p > SOFT_P:
        return f"случайный час не хуже в {p} > {SOFT_P}"
    return None


def skip_candidates(lstate):
    out = []
    for r in (lstate.get("accepted") or []) + (lstate.get("proposed") or []):
        if (r.get("do") or "skip") != "skip" or not r.get("when"):
            continue
        a = (r.get("test") or {}).get("all") or {}
        rule = {"when": [{"field": c["field"], "op": c["op"], "value": float(c["value"])} for c in r["when"]]}
        out.append({"kind": "skip", "rule": rule, "why": r.get("why"), "text": r.get("text"),
                    "source": f"lessons:{r.get('id')}", "fail": soft_skip(a),
                    "gate": {k: a.get(k) for k in ("n", "matched", "mean_matched", "mean_rest", "p_random")},
                    "p": a.get("p_random"), "n": a.get("matched") or 0})
    return out


def entry_candidates(search, rules_file):
    why_of = {}
    for r in (rules_file or {}).get("rules") or []:
        try:
            why_of[sig("entry", r)] = r
        except (KeyError, TypeError, ValueError):
            continue
    out = []
    for m in (search or {}).get("model") or []:
        if m.get("why") or not m.get("rule"):
            continue
        rule = {"when": m["rule"]["when"], "W": int(m["rule"]["W"])}
        a = m.get("all") or {}
        src = why_of.get(sig("entry", rule)) or {}
        out.append({"kind": "entry", "rule": rule, "why": src.get("why"), "text": None,
                    "source": f"patterns:{src.get('proposed_at') or '?'}", "fail": soft_entry(a),
                    "gate": dict(a, search_at=(search or {}).get("computed_at")),
                    "p": a.get("p_random_hour"), "n": a.get("trig") or 0})
    return out


def births(reg, cands, now):
    """Рождение по порогу и пределам (§12.2–12.3) → (родились, ждут мест)."""
    have = {b["sig"] for b in reg["books"]}
    ok, seen = [], set()
    for c in cands:
        s = sig(c["kind"], c["rule"])
        if c["fail"] or s in have or s in seen:
            continue
        seen.add(s)
        ok.append(dict(c, sig=s))
    ok.sort(key=lambda c: (c["p"] if c["p"] is not None else 1.0, -c["n"]))
    room_week = PER_WEEK - sum(1 for b in reg["books"] if now - float(b["decided_at"]) < WEEK_S)
    lv = live(reg)
    room_live = CAP_LIVE - len(lv)
    room_entry = CAP_ENTRY - sum(1 for b in lv if b["kind"] == "entry")
    born, wait = [], []
    for c in ok:
        if room_week <= 0:
            wait.append({"rule": rule_text(c["kind"], c["rule"]), "why": f"предел {PER_WEEK} новых за 7 суток"})
            continue
        if room_live <= 0:
            wait.append({"rule": rule_text(c["kind"], c["rule"]), "why": f"живых уже {CAP_LIVE}"})
            continue
        if c["kind"] == "entry" and room_entry <= 0:
            wait.append({"rule": rule_text(c["kind"], c["rule"]), "why": f"книг ТВХ уже {CAP_ENTRY}"})
            continue
        bid = next_id(reg)
        b = {"id": bid, "key": key_of_book(bid), "kind": c["kind"], "rule": c["rule"], "sig": c["sig"],
             "why": c["why"], "text": c["text"], "source": c["source"], "gate": c["gate"],
             "decided_at": now, "born_at": float((int(now // H) + 1) * H), "status": "live"}
        reg["books"].append(b)
        born.append(b)
        room_week -= 1
        room_live -= 1
        if c["kind"] == "entry":
            room_entry -= 1
    return born, wait


# ------------------------------------------------------------ отставка

def day_str(t):
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def retire_why(b, days_book, days_base, now):
    """Причина отставки (§12.5) или None. `days_*` — {день: (usd, позиций)}."""
    born = float(b["born_at"])
    pos_days = sorted(d for d, (_u, n) in days_book.items() if n)
    last = (calendar.timegm(time.strptime(pos_days[-1], "%Y-%m-%d")) + DAY) if pos_days else born
    if now - max(born, last) >= IDLE_D * DAY:
        return f"простой: без позиций {IDLE_D} суток"
    if now - born < RETIRE_MIN_D * DAY:
        return None
    born_day = day_str(born)
    days = [day_str(now - i * DAY) for i in range(1, WINDOW_D + 1)]
    if min(days) <= born_day:                # окно — только полные сутки после дня рождения
        return None
    mine = sum(days_book.get(d, (0.0, 0))[0] for d in days)
    base = sum(days_base.get(d, (0.0, 0))[0] for d in days)
    if mine < base:
        return f"за {WINDOW_D} суток {mine:+.2f} $ против основной книги {base:+.2f} $ (ячейка ${DEP})"
    return None


def retire(reg, days_of, now):
    """`days_of(key)` → {день: (usd, позиций)} или None (книга не посчитана)."""
    out = []
    base = days_of(BASE) or {}
    for b in live(reg):
        mine = days_of(b["key"])
        if mine is None:
            continue
        why = retire_why(b, mine, base, now)
        if why:
            b.update(status="retired", retired_at=float(now), retired_why=why)
            out.append(b)
    return out


# ------------------------------------------------------------ книги ТВХ вперёд

def entry_decide(b, legs, feat, state, now):
    """Первый час k ≤ W по условию для сигналов после рождения → новые решения.

    Решение по часу k принимается, когда сводка часа легла (`EDGE_S`), и
    больше не пересматривается: запись вперёд (класс A)."""
    W = int(b["rule"]["W"])
    mine = state.setdefault(b["id"], {})
    hi = float(b["retired_at"]) if b.get("retired_at") else None
    new = 0
    for g in legs:
        at = float(g["at"])
        sk = f"{g['sym']}|{int(at)}"
        if at < float(b["born_at"]) or (hi is not None and at >= hi) or sk in mine:
            continue
        got = None
        for k in range(W + 1):
            if now < at + k * H + EDGE_S:
                got = "wait"
                break
            if matches(b["rule"], feat(g, k)):
                got = k
                break
        if got == "wait":
            continue
        mine[sk] = {"k": -1 if got is None else int(got), "t": round(now)}
        new += 1
    return new


def shifted_legs(b, legs, state):
    """Сдвинутые входы книги: вход в час срабатывания; один на (имя, час)."""
    mine = state.get(b["id"]) or {}
    out, seen = [], set()
    for g in sorted(legs, key=lambda g: float(g["at"])):
        d = mine.get(f"{g['sym']}|{int(float(g['at']))}")
        if not d or d["k"] < 0:
            continue
        at = float(g["at"]) + d["k"] * H
        if (g["sym"], at) in seen:
            continue
        seen.add((g["sym"], at))
        out.append(dict(g, at=at, at_signal=float(g["at"])))
    return out


def tick(log=print, now=None, dry=False):
    """Часовой проход книг ТВХ: решения о часе входа и реплей сдвинутых входов."""
    now = now or time.time()
    reg = load()
    books = [b for b in reg["books"] if b["kind"] == "entry"]
    if not books:
        return {"books": 0, "why": "книг ТВХ нет"}
    import model_branch as MB                                  # noqa: E402
    import run_short as S                                      # noqa: E402
    import entry_search as ES                                  # noqa: E402
    try:
        with open(ENTRY_STATE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    quiet = lambda *a: None                                    # noqa: E731
    lo = min(float(b["born_at"]) for b in books)
    legs = [g for g in S.legs(log=quiet) if float(g["at"]) >= lo]
    act = [b for b in books if b["status"] == "live"]
    new = 0
    if act and legs:
        feat = ES.feature_env(legs, days=min(45, int((now - lo) / DAY) + 3))
        for b in act:
            n = entry_decide(b, legs, feat, state, now)
            new += n
            log(f"{b['id']}: новых решений о часе входа {n}")
    cache, _why = MB.read_cache(log=log)
    need, by_leg = [], {}
    for b in books:
        for g in shifted_legs(b, legs, state):
            k = (b["id"], g["sym"], round(float(g["at"]), 3))
            r = cache.get(k)
            if r is None or r.get("state") != "closed":
                need.append(g)
                by_leg.setdefault((g["sym"], round(float(g["at"]), 3)), []).append((b["id"], g))
    uniq = list({(g["sym"], round(float(g["at"]), 3)): g for g in need}.values())
    log(f"книг ТВХ {len(books)}, сигналов после рождения {len(legs)}, новых решений {new}, к реплею {len(uniq)}")
    if uniq:
        rk = S.BOOKS[BASE]
        out, _tail = S.replay_cells(uniq, [S.CELL], log=log, rulers=[rk])
        for (r_rk, sym, at), r in (out.get(S.CELL[0]) or {}).items():
            if r_rk != rk:
                continue
            for bid, g in by_leg.get((sym, at), []):
                cache[(bid, sym, at)] = dict(r, at_signal=g["at_signal"], mbook=bid)
    if not dry:
        MB.write_cache(cache)
        os.makedirs(OUT, exist_ok=True)
        with open(ENTRY_STATE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(ENTRY_STATE + ".tmp", ENTRY_STATE)
    return {"books": len(books), "legs": len(legs), "new_decisions": new, "replayed": len(uniq)}


# ------------------------------------------------------------ касса и отчёт

def cash_days(recs, now, ctx):
    """Нетто ячейки $10k тем же путём, что книги: итог и {день: (usd, позиций)}."""
    import run_paper as RP                                     # noqa: E402
    import costs as CO                                         # noqa: E402
    if not recs:
        return {"final": None, "n": 0, "usd": None}, {}
    rows, _c, _o, _l = RP.build_rows({BASE: recs}, now=now, keys=[BASE], log=lambda *a: None)
    rows, _cs = CO.apply_to_rows(rows, ctx)
    sub = [r for r in rows if r.get("ruler") == BASE and int(r.get("dep", 0)) == DEP
           and not r.get("sizing") and r.get("usd") is not None]
    st_ = RP._stats(sub, DEP) or {}
    days = {d["d"]: (float(d["usd"]), int(d.get("n") or 0)) for d in st_.get("days_rows") or []}
    return {m: st_.get(m) for m in ("final", "max_dd", "n", "win", "usd")}, days


def run(log=print, now=None, dry=False, client_cands=None):
    import rules as R                                          # noqa: E402
    import gate_run as G                                       # noqa: E402
    import gate_books as GB                                    # noqa: E402
    import entry_shift as E                                    # noqa: E402
    import model_branch as MB                                  # noqa: E402
    import costs as CO                                         # noqa: E402
    import entry_search as ES                                  # noqa: E402
    import lessons as LS                                       # noqa: E402
    t0 = time.time()
    now = now or time.time()
    R.DEPOSITS[:] = [float(DEP)]
    R.SIZINGS = (R.SIZING_COMPOUND,)
    reg = load()
    books, why = G.candidates(log)
    if why:
        return {"error": f"книги не загружены: {why}"}
    base_all = books.get(BASE) or []
    rows = G.read_decisions()
    eidx = GB.entry_index(rows)
    ctx = CO.context()
    cache, cwhy = MB.read_cache(log=log)
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "books": [], "cache_why": cwhy}
    per = {}

    def book_recs(b):
        if b["kind"] == "skip":
            win = MB.window(base_all, b)
            return GB.filt(win, BASE, eidx.get(b["id"], {}))[0], win
        mine = MB.window([r for (bid, _s, _a), r in cache.items() if bid == b["id"]], b)
        return E.book_chain(mine, lambda *a: None, now), None

    for b in reg["books"]:
        recs, win = book_recs(b)
        st_, days = cash_days(recs, now, ctx)
        lo = float(b["born_at"])
        base_win = [r for r in base_all if float(r["at"]) >= lo]
        bst, _bd = cash_days(base_win, now, ctx)
        null = None
        if b["kind"] == "skip" and win:
            dec = eidx.get(b["id"], {})
            nbh = GB.cut_by_hour(win, BASE, dec)
            pool = {k for k, v in dec.items() if v in ("open", "skip")}
            keyed = [dict(r, _key=G.key_of(BASE, r)) for r in win]
            fs = []
            for s in range(SEEDS):
                c, _ = cash_days(GB.rand_cut(keyed, nbh, random.Random(2000 + s), pool), now, ctx)
                if c.get("final") is not None:
                    fs.append(c["final"])
            fs.sort()
            null = {"what": "медиана 20 случайных фильтров той же доли", "median_final": fs[len(fs) // 2] if fs else None,
                    "not_worse_share": (round(sum(1 for f in fs if st_.get("final") is not None and f >= st_["final"])
                                              / len(fs), 2) if fs and st_.get("final") is not None else None),
                    "cut": sum(nbh.values())}
        elif b["kind"] == "entry":
            sigs = {(r["sym"], int(float(r.get("at_signal", r["at"])))) for r in recs}
            same = [r for r in base_all if (r["sym"], int(float(r["at"]))) in sigs]
            c, _ = cash_days(same, now, ctx)
            null = {"what": "основная книга на тех же сигналах (вход в час сигнала)", "median_final": c.get("final"),
                    "not_worse_share": None}
        per[b["key"]] = days
        res["books"].append({"id": b["id"], "key": b["key"], "kind": b["kind"], "status": b["status"],
                             "rule": rule_text(b["kind"], b["rule"]), "why": b.get("why"),
                             "born_at": b["born_at"], "retired_why": b.get("retired_why"),
                             "days": round((now - lo) / DAY, 2), "book": st_, "base": bst, "null": null})
    _bs, per[BASE] = cash_days(base_all, now, ctx)
    gone = [] if dry else retire(reg, lambda k: per.get(k), now)
    for g in gone:
        log(f"отставлена {g['id']}: {g['retired_why']}")
    # кандидаты недели и рождение
    try:
        lstate = LS.load_state()
    except Exception:                                         # noqa: BLE001
        lstate = {}
    try:
        with open(ES.LATEST, encoding="utf-8") as f:
            search = json.load(f)
    except (OSError, ValueError):
        search = {}
    try:
        with open(ES.RULES_FILE, encoding="utf-8") as f:
            rfile = json.load(f)
    except (OSError, ValueError):
        rfile = {}
    cands = client_cands if client_cands is not None else skip_candidates(lstate) + entry_candidates(search, rfile)
    born, wait = births(reg, cands, now)
    for b in born:
        log(f"родилась {b['id']} ({b['kind']}): {rule_text(b['kind'], b['rule'])}")
    lv = live(reg)
    better = [x for x in res["books"] if x["status"] == "live" and (x["book"].get("final") is not None)
              and (x["base"].get("final") is not None) and x["book"]["final"] > x["base"]["final"]]
    res.update({"born": [{k: b[k] for k in ("id", "kind", "born_at", "sig")} | {"rule": rule_text(b["kind"], b["rule"])}
                         for b in born],
                "retired": [{"id": g["id"], "why": g["retired_why"]} for g in gone], "waiting": wait,
                "candidates": [{"kind": c["kind"], "rule": rule_text(c["kind"], c["rule"]), "fail": c["fail"],
                                "p": c["p"], "n": c["n"]} for c in cands],
                "live": len(lv), "group": {"live_with_cash": sum(1 for x in res["books"] if x["status"] == "live"
                                                                 and x["book"].get("final") is not None),
                                           "better_than_base": len(better)},
                "limits": {"cap_live": CAP_LIVE, "cap_entry": CAP_ENTRY, "per_week": PER_WEEK, "soft_min": SOFT_MIN,
                           "soft_p": SOFT_P, "retire_min_d": RETIRE_MIN_D, "window_d": WINDOW_D, "idle_d": IDLE_D},
                "secs": round(time.time() - t0, 1)})
    if not dry:
        save(reg)
    return res


def pct(x):
    return "—" if x is None else f"{100 * x:+.2f} %"


def report(r):
    if r.get("error"):
        return f"# Книги модели\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    L = ["# Книги, которые заводит модель (спека 19 §12)", "",
         f"Посчитано {r['computed_at']}; живых {r['live']} из {r['limits']['cap_live']}; порог рождения мягкий "
         f"(≥ {r['limits']['soft_min']} случаев, случайные не хуже ≤ {int(100 * r['limits']['soft_p'])} %); "
         f"новых ≤ {r['limits']['per_week']} за 7 суток; отставка — {r['limits']['window_d']} суток ниже основной "
         f"книги или {r['limits']['idle_d']} суток простоя. Только бумага.", ""]
    if r["born"]:
        L += ["**Родились в этом проходе:** " + "; ".join(f"{b['id']} ({b['kind']}) — `{b['rule']}`" for b in r["born"]), ""]
    if r["retired"]:
        L += ["**Отставлены:** " + "; ".join(f"{g['id']} — {g['why']}" for g in r["retired"]), ""]
    L += ["| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |",
          "|---|---|---|---|---|---|---|---|---|"]
    for x in r["books"]:
        nl = x.get("null") or {}
        nt = pct(nl.get("median_final")) + (f" (не хуже {nl['not_worse_share']})" if nl.get("not_worse_share") is not None else "")
        st_ = "живая" if x["status"] == "live" else f"отставлена: {x.get('retired_why')}"
        L.append(f"| {x['id']} | {'фильтр' if x['kind'] == 'skip' else 'ТВХ'} | `{x['rule']}` | {x['days']} | "
                 f"{x['book'].get('n') or 0} | {pct(x['book'].get('final'))} | {pct(x['base'].get('final'))} | {nt} | {st_} |")
    if not r["books"]:
        L.append("| — | | книг ещё нет | | | | | | |")
    g = r["group"]
    L += ["", f"**Группой:** лучше основной книги {g['better_than_base']} из {g['live_with_cash']} живых с позициями; "
          "без эджа ожидается около половины — это не вердикт.", ""]
    for x in r["books"]:
        if x.get("why"):
            L.append(f"- {x['id']}: {x['why']}")
    L += ["", "## Наблюдения недели и порог", "",
          "| вид | правило | случаев | случайные не хуже | вердикт |", "|---|---|---|---|---|"]
    for c in r["candidates"]:
        L.append(f"| {'фильтр' if c['kind'] == 'skip' else 'ТВХ'} | `{c['rule']}` | {c['n']} | {c['p']} | "
                 f"{c['fail'] or 'проходит'} |")
    if r["waiting"]:
        L += ["", "Прошли порог, ждут места: " + "; ".join(f"`{w['rule']}` — {w['why']}" for w in r["waiting"])]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true", help="часовой проход книг ТВХ")
    ap.add_argument("--dry", action="store_true", help="без записи реестра, состояния и кэша")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                     # noqa: E402
    log = AB.guarded(print, limit=2500)
    if a.tick:
        s = tick(log=log, dry=a.dry)
        print(json.dumps(s, ensure_ascii=False))
        if not a.dry:
            # отметка тика — по ней сторож судит, был ли час (вне git)
            os.makedirs(os.path.dirname(TICK), exist_ok=True)
            with open(TICK, "w", encoding="utf-8") as f:
                json.dump(dict(s, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), f, ensure_ascii=False)
        return 0
    r = run(log=log, dry=a.dry)
    txt = report(r)
    if not a.dry:
        os.makedirs(OUT, exist_ok=True)
        with open(LATEST, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, default=str)
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write(txt)
    print(txt)
    if not a.dry and not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "книги модели"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
