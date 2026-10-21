#!/usr/bin/env python3
"""Поиск новой ТВХ по состоянию рынка (спека 19 §11.8, U4c).

Владелец 21.10: «правила входа не должны быть просто ход цены, это
слишком просто; должен быть более комплексный поиск с разными ячейками, с
анализом всех параметров рынка в каждой волне». Правило входа здесь —
«войти в ПЕРВЫЙ час после сигнала (k = 0…W), когда состояние рынка
удовлетворяет условиям»; не наступило за W ч — сделки нет. Условия — на
параметрах каталога критериев судьи (§3a), посчитанных на КАЖДОМ часе
после сигнала (`features`): толпа (A), микроструктура записи B1 (B),
сигнал (C), режим рынка (D), ход имени и путь с сигнала, история имени
(F). Всё строго «до момента входа»: час k — закрытые часы ≤ at + k·ч.

Счёт без второй копии ядра и без тысячи реплеев: книга Depth · Short
пересчитывает каждый сигнал своим реплеем со входом через k = 0…6 ч
(семь реплеев, `entry_shift`), затем возраст имени и охрана — таблица
исходов O[сигнал, k] (нетто на маржу). Любое правило — выбор k по
сигналу и поиск в таблице.

Протокол (объявлен ДО первого прогона, 21.10; не меняется по
результатам):
* ячейки: каждое поле с покрытием ≥ 90 % и ≥ 10 различными значениями ×
  порог на квантилях 20/40/60/80 % (по обучающей половине) × знак ≤ / ≥
  × окно W ∈ {3, 6} ч; затем пары условий из 20 лучших одиночных той же
  половины; плюс правила модели (`out/entry_rules.json`) того же вида;
* мера ячейки: средний нетто на маржу НА СИГНАЛ (не вошедший — 0) минус
  тот же у книги; вошедших ≥ 30;
* судится ПРАВИЛО ОТБОРА, а не победитель (урок R5): лучшая ячейка
  обучающей половины применяется к другой половине; два направления
  (1-я → 2-я и 2-я → 1-я); на проверочной половине она обязана быть
  выше книги на сигнал И выше случайного часа входа для тех же сигналов
  (k равномерно в 0…W, 400 зёрен, доля не хуже ≤ 10 %);
* отрицательный контроль: тот же отбор на ПЕРЕМЕШАННЫХ параметрах
  (строки состояния переставлены между сигналами) обязан молчать;
* кандидат — правило, выбранное на всём окне, если отбор держит в обоих
  направлениях и контроль молчит; его проверяет `entry_shift`-реплей с
  кассой. Новую книгу заводит только владелец.

    entry_search.py [--since 2026-09-25] [--no-publish]
"""
import argparse
import calendar
import json
import os
import random
import statistics as st
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import entry_shift as E                                        # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "ENTRY-SEARCH.md")
LATEST = os.path.join(OUT, "entry_search.json")
TABLE = os.path.join(OUT, "record", "entry_table.npz")      # таблица исходов — не в git
RULES_FILE = os.path.join(OUT, "entry_rules.json")          # правила модели (U4b)
H = 3600.0
KMAX = 6
WINDOWS = (3, 6)
QUANTS = (0.2, 0.4, 0.6, 0.8)
MIN_COVER = 0.90
MIN_DISTINCT = 10
MIN_TRIG = 30
TOP_PAIRS = 20
NULL_DRAWS = 400
P_MAX = 0.10


# ------------------------------------------------------------ параметры

def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _move(a, b):
    return (b / a - 1.0) if (a and b) else None


def features(g, k, hours, mkt, state, market_rows, hist, crowd_of, at_or_before):
    """Параметры состояния на час k после сигнала `g` (закрытые часы ≤ t)."""
    sym = g["sym"]
    t = float(g["at"]) + k * H
    tm = t - 1.0                                   # последний ЗАКРЫТЫЙ час
    px = lambda s, ts: mkt.px(s, ts)                # noqa: E731
    out = {}
    p_now = px(sym, tm)
    for n in (1, 4, 24, 168):
        out[f"px_{n}h"] = _move(px(sym, tm - n * H), p_now)
        if n <= 24:
            out[f"btc_{n}h"] = _move(px("BTCUSDT", tm - n * H), px("BTCUSDT", tm))
    out["since_signal"] = _move(px(sym, float(g["at"]) - 1.0), p_now) if k > 0 else 0.0
    # микроструктура записи B1 — сводка последнего закрытого часа и 24 ч до него
    r = hours.row(sym, tm) or {}
    back = [x for x in hours.back(sym, tm, 24) if x]
    out["spread_bp"] = _f(r.get("spread_bp"))
    b, s_ = _f(r.get("buy")), _f(r.get("sell"))
    out["buy_share"] = (b / (b + s_)) if (b is not None and s_ is not None and b + s_ > 0) else None
    nt = [_f(x.get("n_trades")) for x in back if _f(x.get("n_trades"))]
    out["trades_ratio"] = (_f(r.get("n_trades")) / st.mean(nt)) if (nt and _f(r.get("n_trades")) is not None) else None
    vm = [_f(x.get("vol_max_1s")) for x in back if _f(x.get("vol_max_1s"))]
    out["burst_ratio"] = (_f(r.get("vol_max_1s")) / st.mean(vm)) if (vm and _f(r.get("vol_max_1s")) is not None) else None
    out["depth_eat_bid"] = _f(r.get("depth_eat_b"))
    out["depth_eat_ask"] = _f(r.get("depth_eat_a"))
    out["funding"] = _f(r.get("fr"))
    out["basis_bp"] = _f(r.get("basis_bp"))
    oi_now = _f(r.get("oi_usd"))
    r1 = hours.row(sym, tm - H) or {}
    r24 = hours.row(sym, tm - 24 * H) or {}
    out["oi_1h"] = _move(_f(r1.get("oi_usd")), oi_now)
    out["oi_24h"] = _move(_f(r24.get("oi_usd")), oi_now)
    # толпа (A) и рынок (D) — запись состояния рынка, не позже момента
    c = crowd_of(state, sym, int(t * 1000)) or {}
    out["crowd_bybit"] = _f((c.get("bybit") or {}).get("now"))
    by24 = _f((c.get("bybit") or {}).get("24h_ago"))
    out["crowd_bybit_shift"] = (out["crowd_bybit"] - by24) if (out["crowd_bybit"] is not None and by24 is not None) else None
    out["crowd_bn_global"] = _f((c.get("bn_global") or {}).get("now"))
    out["crowd_bn_top"] = _f((c.get("bn_top") or {}).get("now"))
    m = at_or_before(market_rows, int(t * 1000)) or {}
    out["fng"] = _f(m.get("fng"))
    out["btc_dom"] = _f(m.get("btc_dom"))
    out["mcap_24h"] = _f(m.get("mcap_24h_pct"))
    # сигнал (C) и история имени (F) — на сигнал
    out["signal_fav_bp"] = _f(g.get("fav"))
    out["signal_rr"] = _f(g.get("rr"))
    out["name_positions"] = _f(hist.get("n"))
    out["name_floor_share"] = (hist["floors"] / hist["n"]) if hist.get("n") else None
    return out


def build_table(legs, out_by_k, get_features):
    """→ (names, F[n, K+1, f], O[n, K+1(, ячейки)], ячейки выхода) — O NaN, где входа нет."""
    n, K = len(legs), KMAX + 1
    rows = [[get_features(g, k) for k in range(K)] for g in legs]
    names = sorted({x for r in rows for d in r for x in d})
    F = np.full((n, K, len(names)), np.nan)
    for i, r in enumerate(rows):
        for k, d in enumerate(r):
            for j, nm in enumerate(names):
                v = d.get(nm)
                if v is not None:
                    F[i, k, j] = v
    # исходы: число (одна ячейка — выход книги) или {ячейка выхода: число}
    exits = sorted({e for d in out_by_k for v in d.values() if isinstance(v, dict) for e in v}) or [BOOK_EXIT]
    O = np.full((n, K, len(exits)), np.nan)
    for i, g in enumerate(legs):
        for k in range(K):
            v = out_by_k[k].get(i)
            if v is None:
                continue
            for c, ex in enumerate(exits):
                x = v.get(ex) if isinstance(v, dict) else (v if ex == BOOK_EXIT else None)
                if x is not None:
                    O[i, k, c] = x
    return names, F, (O if len(exits) > 1 else O[:, :, 0]), exits


# ------------------------------------------------------------ выходы (§11.9)

# Сетка выхода, объявленная 21.10 ДО первого прогона: стоп в доле цены от
# средней (нет — только пол книги), тейк — обещание модели ×1/×2/×3, плечо
# книги (`book`) или равного риска (`eq`, только со стопом). Ячейка книги —
# `s0:t2:book`, ровно `run_short.CELL` без политики.
STOPS = (None, 0.01, 0.02, 0.03, 0.05, 0.08)
TAKES = ("t1", "t2", "t3")
BOOK_EXIT = "s0:t2:book"


def _exits():
    out = []
    for st_ in STOPS:
        for tk in TAKES:
            for lev in ("book", "eq"):
                if lev == "eq" and st_ is None:
                    continue
                out.append({"name": f"s{0 if st_ is None else round(st_ * 100)}:{tk}:{lev}",
                            "stop": st_, "take": tk, "lev": lev})
    return out


EXITS = _exits()
EXIT_BY = {e["name"]: e for e in EXITS}
assert BOOK_EXIT in EXIT_BY


def exit_cell(name):
    """→ (ячейка ядра D10, политика ячейки или None). Ячейка книги — та же,
    что у книги (`run_short.CELL`), без политики: исход бит в бит."""
    e = EXIT_BY[name]
    tk = e["take"]
    key = f"fence:none:{tk}" if (e["stop"] is None and e["lev"] == "book") else f"fence:none:{tk}#{name}"
    pol = ({"adds": [], "stop_frac": e["stop"], "lev_risk": e["lev"] == "eq"}
           if e["stop"] is not None else None)
    return (key, "fence", "none", tk), pol


def exit_text(name):
    e = EXIT_BY.get(name) or {}
    st_ = "без стопа" if e.get("stop") is None else f"стоп {100 * e['stop']:g} %"
    lev = "плечо книги" if e.get("lev") == "book" else "равный риск"
    return f"{st_}, тейк обещание ×{str(e.get('take', 't2'))[1:]}, {lev}"


# ------------------------------------------------------------ правила

ALWAYS = {"when": [], "W": 0, "by": "grid"}     # вход книги (k = 0): только выход


def first_k(F, names, rule):
    """Первый час k ≤ W, где выполнены ВСЕ условия; −1 — не наступил."""
    W = int(rule["W"])
    ok = np.ones(F.shape[:2], dtype=bool)
    for c in rule["when"]:
        x = F[:, :, names.index(c["field"])]
        with np.errstate(invalid="ignore"):
            ok &= (x <= c["value"]) if c["op"] == "<=" else (x >= c["value"])
    ok[:, W + 1:] = False
    any_ = ok.any(axis=1)
    return np.where(any_, ok.argmax(axis=1), -1)


def as3(O):
    """Таблица исходов O[сигнал, k, ячейка выхода]; прежняя двумерная — одна ячейка."""
    return O[:, :, None] if O.ndim == 2 else O


def score(O, ks, idx):
    """Средний на сигнал (не вошедший — 0) и число вошедших на подмножестве idx.
    `O` — исходы одной ячейки выхода O[сигнал, k]."""
    idx = np.asarray(list(idx), dtype=int)
    if not len(idx):
        return None, 0
    k = ks[idx]
    v = np.where(k >= 0, O[idx, np.maximum(k, 0)], np.nan)
    trig = int(np.sum(~np.isnan(v)))
    return float(np.mean(np.nan_to_num(v, nan=0.0))), trig


def null_p(O, ks, idx, W, mean_rule, rng):
    """Доля случайных часов входа (k ~ U[0, W]) для тех же вошедших, не хуже правила."""
    trig = [i for i in idx if ks[i] >= 0 and not np.isnan(O[i, ks[i]])]
    if not trig:
        return None
    n_all = len(idx)
    ge = 0
    for _ in range(NULL_DRAWS):
        s = 0.0
        for i in trig:
            v = O[i, rng.randint(0, W)]
            s += 0.0 if np.isnan(v) else float(v)
        ge += (s / n_all) >= mean_rule
    return ge / NULL_DRAWS


def cells(F, names, idx_train):
    """Одиночные ячейки: поле × квантиль (по обучающей половине) × знак × окно."""
    out = []
    n_rows = F.shape[0] * F.shape[1]
    for j, nm in enumerate(names):
        x = F[idx_train][:, :, j].ravel()
        x = x[~np.isnan(x)]
        cover = np.sum(~np.isnan(F[:, :, j])) / n_rows
        if cover < MIN_COVER or len(np.unique(x)) < MIN_DISTINCT:
            continue
        for q in QUANTS:
            thr = float(np.quantile(x, q))
            for op in ("<=", ">="):
                for W in WINDOWS:
                    out.append({"when": [{"field": nm, "op": op, "value": round(thr, 6)}], "W": W, "by": "grid"})
    return out


def _jb(exits):
    return exits.index(BOOK_EXIT) if BOOK_EXIT in exits else 0


def select(F, O, names, idx_train, extra=(), exits=None, always=True):
    """Лучшие пары «правило входа + ячейка выхода» обучающей половины по
    приросту к КНИГЕ (её вход, её выход) на сигнал."""
    O = as3(O)
    exits = list(exits or [BOOK_EXIT])
    jb = _jb(exits)
    n = len(O)
    base, _ = score(O[:, :, jb], np.zeros(n, dtype=int), idx_train)
    singles = cells(F, names, idx_train)
    ks_of = [(r, first_k(F, names, r)) for r in singles]
    pool, n_single = [], 0
    for c, ex in enumerate(exits):
        Oc = O[:, :, c]
        mine = []
        for rule, ks in ks_of:
            m, trig = score(Oc, ks, idx_train)
            if m is not None and trig >= MIN_TRIG:
                mine.append((m - base, dict(rule, exit=ex), trig))
        n_single += len(mine)
        mine.sort(key=lambda x: -x[0])
        pool += mine
        top = mine[:TOP_PAIRS]
        for a in range(len(top)):
            for b in range(a + 1, len(top)):
                ra, rb = top[a][1], top[b][1]
                if ra["W"] != rb["W"] or ra["when"][0]["field"] == rb["when"][0]["field"]:
                    continue
                rule = {"when": ra["when"] + rb["when"], "W": ra["W"], "by": "grid", "exit": ex}
                m, trig = score(Oc, first_k(F, names, rule), idx_train)
                if m is not None and trig >= MIN_TRIG:
                    pool.append((m - base, rule, trig))
        if always:
            m, trig = score(Oc, np.zeros(n, dtype=int), idx_train)
            if m is not None and trig >= MIN_TRIG:
                pool.append((m - base, dict(ALWAYS, exit=ex), trig))
    for rule in extra:
        ex = rule.get("exit") or BOOK_EXIT
        if ex in exits and all(c["field"] in names for c in rule["when"]):
            m, trig = score(O[:, :, exits.index(ex)], first_k(F, names, rule), idx_train)
            if m is not None and trig >= MIN_TRIG:
                pool.append((m - base, dict(rule, exit=ex), trig))
    pool.sort(key=lambda x: -x[0])
    return pool, base, n_single


def judge(F, O, names, rule, test, exits, seed):
    """Правило на проверочной половине: среднее на сигнал против книги и
    доля случайных часов того же окна С ТОЙ ЖЕ ячейкой выхода, не хуже.
    У правила «всегда, k = 0» случайного часа нет — судит только книга."""
    O = as3(O)
    c = exits.index(rule.get("exit") or BOOK_EXIT)
    ks = first_k(F, names, rule)
    m, trig = score(O[:, :, c], ks, test)
    base_te, _ = score(O[:, :, _jb(exits)], np.zeros(len(O), dtype=int), test)
    W = int(rule["W"])
    p = (null_p(O[:, :, c], ks, test, W, m, random.Random(seed)) if (m is not None and W > 0) else None)
    held = (m is not None and trig >= MIN_TRIG and m > base_te and (W == 0 or (p is not None and p <= P_MAX)))
    return {"test_mean": None if m is None else round(m, 5), "test_book": round(base_te, 5), "test_trig": trig,
            "p_random_hour": p, "held": held}


def fold(F, O, names, train, test, extra, seed, exits=None, always=True):
    exits = list(exits or [BOOK_EXIT])
    pool, base_tr, n_single = select(F, O, names, train, extra, exits, always)
    if not pool:
        return {"why": "ни одна ячейка не набрала вошедших", "cells": 0}
    gain_tr, rule, trig_tr = pool[0]
    out = {"rule": rule, "train_gain": round(gain_tr, 5), "train_trig": trig_tr, "cells": len(pool),
           "singles": n_single, **judge(F, O, names, rule, test, exits, seed),
           "top5_train": [{"rule": r, "gain": round(gn, 5), "trig": tg} for gn, r, tg in pool[:5]]}
    # мера цели владельца (§11.9): лучшее правило С КАЖДЫМ стопом — на проверке
    by_stop = {}
    for gn, r, tg in pool:
        st_ = (EXIT_BY.get(r.get("exit")) or {}).get("stop")
        k = "нет" if st_ is None else f"{100 * st_:g}"
        if k not in by_stop:
            by_stop[k] = {"rule": r, "train_gain": round(gn, 5), "train_trig": tg,
                          **judge(F, O, names, r, test, exits, seed + 101)}
    out["by_stop"] = by_stop
    return out


def search(F, O, names, at, extra=(), seed=0, exits=None, always=True):
    order = np.argsort(at)
    half = len(order) // 2
    a, b = list(order[:half]), list(order[half:])
    f1 = fold(F, O, names, a, b, extra, seed, exits, always)
    f2 = fold(F, O, names, b, a, extra, seed + 1, exits, always)
    return f1, f2


def shortest_stop(f1, f2):
    """Самый короткий стоп, чьё лучшее правило держится в обоих направлениях."""
    held = [k for k in (f1.get("by_stop") or {}) if k != "нет"
            and (f1["by_stop"][k].get("held") and (f2.get("by_stop") or {}).get(k, {}).get("held"))]
    return min(held, key=float) if held else None


def trig_stats(O, ks, W, rng, Ob=None):
    """Порог рождения книги ТВХ (§12.2) на всём окне: сработавшие сигналы —
    средний в час правила (своя ячейка выхода `O`), у тех же в час сигнала
    с выходом книги (`Ob`, умолчание — та же ячейка) и доля случайных часов
    окна той же ячейки, не хуже правила (400 зёрен)."""
    Ob = O if Ob is None else Ob
    T = [i for i in range(len(ks)) if ks[i] >= 0 and not np.isnan(O[i, ks[i]])]
    if not T:
        return {"trig": 0, "rule_mean": None, "book_mean": None, "p_random_hour": None}
    rule_mean = float(np.mean([O[i, ks[i]] for i in T]))
    b = [Ob[i, 0] for i in T if not np.isnan(Ob[i, 0])]
    ge = 0
    for _ in range(NULL_DRAWS):
        v = [O[i, rng.randint(0, W)] for i in T]
        v = [0.0 if np.isnan(x) else float(x) for x in v]
        ge += float(np.mean(v)) >= rule_mean
    return {"trig": len(T), "rule_mean": round(rule_mean, 5), "book_mean": round(float(np.mean(b)), 5) if b else None,
            "p_random_hour": round(ge / NULL_DRAWS, 4) if W > 0 else None}


def model_scores(F, O, names, at, extra, seed=0, exits=None):
    """Каждое правило модели на каждой половине: прирост к книге на сигнал и случайный час.

    Описание, не отбор: модель видела сводку тех же сделок, так что честная
    проверка её правил — вперёд; здесь видно, где они стоят рядом с сеткой.
    """
    O = as3(O)
    exits = list(exits or [BOOK_EXIT])
    jb = _jb(exits)
    order = np.argsort(at)
    half = len(order) // 2
    halves = (list(order[:half]), list(order[half:]))
    out = []
    for n, rule in enumerate(extra):
        ex = rule.get("exit") or BOOK_EXIT
        if not all(c["field"] in names for c in rule["when"]):
            out.append({"rule": rule, "why": "поле вне таблицы"})
            continue
        if ex not in exits:
            out.append({"rule": rule, "why": f"ячейки выхода {ex} нет в таблице"})
            continue
        Oc = O[:, :, exits.index(ex)]
        ks = first_k(F, names, rule)
        row = {"rule": {k: rule[k] for k in ("when", "W")} | ({"exit": ex} if rule.get("exit") else {}),
               "halves": []}
        for h, idx in enumerate(halves):
            m, trig = score(Oc, ks, idx)
            base, _ = score(O[:, :, jb], np.zeros(len(O), dtype=int), idx)
            p = null_p(Oc, ks, idx, int(rule["W"]), m, random.Random(seed + 101 + 2 * n + h)) if trig else None
            row["halves"].append({"gain": None if m is None else round(m - base, 5), "trig": trig, "p_random_hour": p})
        row["all"] = trig_stats(Oc, ks, int(rule["W"]), random.Random(seed + 7), O[:, :, jb])
        out.append(row)
    return out


def shuffled(F, seed):
    """Отрицательный контроль: строки состояния (по сигналам) переставлены."""
    rng = np.random.default_rng(seed)
    G = F.copy()
    G[:, :, :] = F[rng.permutation(F.shape[0])]
    return G


def rule_text(rule):
    w = " и ".join(f"{c['field']} {c['op']} {c['value']:g}" for c in rule["when"])
    w = (w + f", окно {rule['W']} ч") if rule["when"] else "вход книги (час сигнала)"
    ex = rule.get("exit")
    return w + (f"; {exit_text(ex)}" if ex and ex != BOOK_EXIT else "")


# ------------------------------------------------------------ прогон

def run(log=print, since=None, now=None, legs=None, table=None, seed=0):
    t0 = time.time()
    now = now or time.time()
    if table is None:
        table = make_table(log, since, now, legs)
    if table.get("error"):
        return table
    names, F, O, at, n_legs = table["names"], table["F"], as3(table["O"]), table["at"], table["n"]
    exits = list(table.get("exits") or [BOOK_EXIT])
    jb = _jb(exits)
    extra = []
    try:
        with open(RULES_FILE, encoding="utf-8") as f:
            extra = [dict(r, by="model") for r in (json.load(f).get("rules") or [])]
    except (OSError, ValueError):
        pass
    cover = {nm: round(float(np.mean(~np.isnan(F[:, :, j]))), 3) for j, nm in enumerate(names)}
    f1, f2 = search(F, O, names, at, extra, seed, exits)
    # контроль — правила по параметрам; «вход книги + выход» перестановка не меняет
    c1, c2 = search(shuffled(F, seed + 7), O, names, at, extra=(), seed=seed + 11, exits=exits, always=False)
    control_silent = not (c1.get("held") and c2.get("held"))
    procedure = bool(f1.get("held") and f2.get("held") and control_silent)
    mine = model_scores(F, O, names, at, extra, seed, exits)
    final = None
    if procedure:
        pool, base_all, _ = select(F, O, names, list(range(len(O))), extra, exits)
        final = {"rule": pool[0][1], "gain_all": round(pool[0][0], 5), "trig": pool[0][2]}
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "signals": n_legs,
           "fields": names, "cover": cover, "kmax": KMAX, "windows": list(WINDOWS),
           "book_mean": round(float(np.nanmean(np.where(np.isnan(O[:, 0, jb]), 0.0, O[:, 0, jb]))), 5),
           "exits": exits, "shortest_stop": shortest_stop(f1, f2),
           "fold_1to2": f1, "fold_2to1": f2, "control": {"fold_1to2": c1, "fold_2to1": c2, "silent": control_silent},
           "procedure_holds": procedure, "candidate": final, "model_rules": len(extra), "model": mine,
           "secs": round(time.time() - t0, 1)}
    log(f"поиск ТВХ: сигналов {n_legs}, полей {len(names)}; 1→2 {'держит' if f1.get('held') else 'нет'}, "
        f"2→1 {'держит' if f2.get('held') else 'нет'}, контроль {'молчит' if control_silent else 'НЕ молчит'}")
    return res


def make_table(log, since, now, legs=None):
    """Семь реплеев (вход через k = 0…6 ч) и параметры на каждом часе."""
    import run_short as S                                     # noqa: E402
    if legs is None:
        legs = S.legs(log=lambda *a: None)
    lo = since or (now - 30 * 86400)
    hi = now - (24 + KMAX + 1) * H
    legs = [g for g in legs if lo <= float(g["at"]) <= hi]
    if len(legs) < 4 * MIN_TRIG:
        return {"error": f"сигналов {len(legs)} < {4 * MIN_TRIG}"}
    log(f"сигналов {len(legs)}; реплей со входом через 0…{KMAX} ч, ячеек выхода {len(EXITS)}")
    cell_of = {e["name"]: exit_cell(e["name"]) for e in EXITS}
    cell_list = [c for c, _p in cell_of.values()]
    pol_by_key = {c[0]: p for c, p in cell_of.values()}

    def adds_of(g, key):
        return pol_by_key.get(key)
    out_by_k = []
    for k in range(KMAX + 1):
        t1 = time.time()
        lk = [dict(g, at=float(g["at"]) + k * H, at_signal=float(g["at"])) for g in legs]
        out, _tail = S.replay_cells(lk, cell_list, log=log, rulers=[E.RULER], adds_of=adds_of)
        d = {}
        for name, (cell, _pol) in cell_of.items():
            recs = E.book_chain(E.recs_of(out.get(cell[0]) or {}, lk), lambda *a: None, now)
            by = {(r["sym"], round(float(r["at"]), 3)): r for r in recs}
            for i, g in enumerate(lk):
                r = by.get((g["sym"], round(float(g["at"]), 3)))
                if r is not None:
                    d.setdefault(i, {})[name] = float(r.get("pnl_net", r.get("pnl", 0.0)))
        del out
        out_by_k.append(d)
        log(f"  k={k}: позиций {len(d)}, ячеек выхода {len(cell_of)} ({time.time() - t1:.0f} с)")
    names, F, O, exits = build_table(legs, out_by_k, feature_env(legs, days=45))
    os.makedirs(os.path.dirname(TABLE), exist_ok=True)
    np.savez_compressed(TABLE, F=F, O=O, at=np.array([float(g["at"]) for g in legs]), names=np.array(names),
                        exits=np.array(exits))
    return {"names": names, "F": F, "O": O, "at": np.array([float(g["at"]) for g in legs]), "n": len(legs),
            "exits": exits}


def load_table(path=None):
    """Таблица исходов прошлого прогона (`make_table` её сохраняет)."""
    try:
        z = np.load(path or TABLE, allow_pickle=False)
    except OSError as e:
        return {"error": f"таблицы нет ({type(e).__name__}) — нужен полный прогон"}
    exits = [str(x) for x in z["exits"]] if "exits" in z.files else [BOOK_EXIT]
    return {"names": [str(x) for x in z["names"]], "F": z["F"], "O": z["O"], "at": z["at"], "n": len(z["at"]),
            "exits": exits}


def feature_env(legs, days=45):
    """→ feat(g, k): параметры состояния на час k после сигнала — одним
    окружением на поиск (§11.8) и книги ТВХ модели вперёд (§12)."""
    import run_short as S                                     # noqa: E402
    import context as CTX                                     # noqa: E402
    import wave as WV                                         # noqa: E402
    # история имени — по записи книги до сигнала
    cache, _ = S.read_cache(log=lambda *a: None)
    book = sorted((r for (rk, _s, _a), r in cache.items() if rk == E.RULER), key=lambda r: float(r["at"]))
    by_sym = {}
    for r in book:
        by_sym.setdefault(r["sym"], []).append(r)
    del cache, book

    def hist(sym, at):
        prev = [r for r in by_sym.get(sym, []) if float(r["at"]) < at]
        return {"n": len(prev), "floors": sum(1 for r in prev if r.get("exit") == "пол")}
    syms = sorted({g["sym"] for g in legs} | {"BTCUSDT"})
    state, market_rows, _ev = CTX.load_state(days=days, syms=syms)
    hours = WV.Hours()
    mkt = WV.Market(hours=hours)
    return lambda g, k: features(g, k, hours, mkt, state, market_rows, hist(g["sym"], float(g["at"])),
                                 CTX.crowd_of, CTX.at_or_before)


def report(r):
    if r.get("error"):
        return f"# Поиск ТВХ по состоянию рынка\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    pct = lambda v: "—" if v is None else f"{100 * v:+.2f} %"   # noqa: E731
    L = ["# Поиск ТВХ по состоянию рынка (спека 19 §11.8, U4c)", "",
         f"Посчитано {r['computed_at']}; Depth · Short; сигналов {r['signals']}; вход — первый час k ≤ W после сигнала, "
         f"когда выполнены условия; полей {len(r['fields'])}; книга (вход в час сигнала): {pct(r['book_mean'])} на сигнал; "
         f"правил модели {r['model_rules']}; за {r['secs']} с.", "",
         "Судится правило отбора: лучшая ячейка одной половины на другой половине — выше книги и выше случайного часа "
         "входа (доля не хуже ≤ 10 %); контроль — тот же отбор на перемешанных параметрах.", "",
         "| направление | выбранная ячейка | ячеек | прирост на обучении | на проверке: правило / книга | вошло | случайный час не хуже | держит |",
         "|---|---|---|---|---|---|---|---|"]
    for nm, f in (("1-я → 2-я", r["fold_1to2"]), ("2-я → 1-я", r["fold_2to1"]),
                  ("контроль 1→2", r["control"]["fold_1to2"]), ("контроль 2→1", r["control"]["fold_2to1"])):
        if f.get("why"):
            L.append(f"| {nm} | {f['why']} | | | | | | нет |")
            continue
        L.append(f"| {nm} | `{rule_text(f['rule'])}` | {f['cells']} | {pct(f['train_gain'])} | "
                 f"{pct(f['test_mean'])} / {pct(f['test_book'])} | {f['test_trig']} | {f['p_random_hour']} | "
                 f"{'**да**' if f['held'] else 'нет'} |")
    L += ["", f"**Отбор держит в обоих направлениях и контроль молчит:** {'ДА' if r['procedure_holds'] else 'нет'}."]
    b1, b2 = r["fold_1to2"].get("by_stop") or {}, r["fold_2to1"].get("by_stop") or {}
    if b1 or b2:
        L += ["", "## Стоп: лучшее правило с каждым стопом (спека 19 §11.9)", "",
              "Мера цели владельца — самый короткий стоп, чьё лучшее правило держится на проверке в обоих "
              "направлениях. Выход книги — без стопа (только пол), тейк — обещание ×2.", "",
              "| стоп | 1-я → 2-я: правило | на проверке / книга | держит | 2-я → 1-я: правило | на проверке / книга | держит |",
              "|---|---|---|---|---|---|---|"]
        for k in sorted(set(b1) | set(b2), key=lambda x: -1.0 if x == "нет" else float(x)):
            x, y = b1.get(k) or {}, b2.get(k) or {}
            cell = lambda z: (f"`{rule_text(z['rule'])}` | {pct(z.get('test_mean'))} / {pct(z.get('test_book'))} | "   # noqa: E731
                              f"{'**да**' if z.get('held') else 'нет'}") if z else "— | — | —"
            L.append(f"| {k if k == 'нет' else k + ' %'} | {cell(x)} | {cell(y)} |")
        ss = r.get("shortest_stop")
        L += ["", f"**Самый короткий стоп, который держится:** {ss + ' %' if ss else 'нет — короткого стопа у книги пока нет'}."]
    if r.get("model"):
        L += ["", "Правила модели — каждое на обеих половинах (описание, не отбор: модель видела сводку тех же сделок, "
              "честная проверка — вперёд):", "",
              "| правило | 1-я: прирост к книге / вошло / случайный час не хуже | 2-я: то же |", "|---|---|---|"]
        for m in r["model"]:
            if m.get("why"):
                L.append(f"| `{rule_text(m['rule'])}` | {m['why']} | |")
                continue
            cell = lambda h: f"{pct(h['gain'])} / {h['trig']} / {h['p_random_hour'] if h['p_random_hour'] is not None else '—'}"  # noqa: E731
            L.append(f"| `{rule_text(m['rule'])}` | {cell(m['halves'][0])} | {cell(m['halves'][1])} |")
    if r.get("candidate"):
        c = r["candidate"]
        L += [f"Кандидат (выбран на всём окне): `{rule_text(c['rule'])}`, прирост {pct(c['gain_all'])} на сигнал, вошло {c['trig']}. "
              "Книгу с этим правилом может завести модель по порогу §12 (только бумага)."]
    L += ["", "Покрытие полей (доля сигнало-часов с числом): " +
          ", ".join(f"{k} {v:.0%}" for k, v in sorted(r["cover"].items(), key=lambda x: x[1]))]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--from-table", action="store_true",
                    help="без реплея: таблица исходов прошлого прогона (новые правила модели на тех же сигналах)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                     # noqa: E402
    since = calendar.timegm(time.strptime(a.since, "%Y-%m-%d")) if a.since else None
    table = load_table() if a.from_table else None
    r = run(log=AB.guarded(print, limit=2500), since=since, table=table)
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "поиск ТВХ по состоянию рынка"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
