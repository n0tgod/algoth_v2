#!/usr/bin/env python3
"""Дорога сделки коротких книг: что происходит ПОСЛЕ входа и можно ли выйти раньше.

Просьба владельца 2026-09-13: изучить не только момент входа, а развитие
сделки — «может, в середине уже что-то происходит закономерное, и мы можем
выйти раньше», и связь актива с остальным рынком и гигантами.

Три части, все на ЗАКРЫТЫХ записях кэша реплея коротких книг `h24`:

A. **Анатомия пути.** Почасовые отметки позиции считает ядро симуляции
   (`ladder.simulate_dca(track=True)`: `(час, приращение pnl долей маржи)`,
   последняя равна исходу) — второй формулы здесь нет. К часу k: где стоит
   хвост и где остальные, бывал ли хвост в плюсе (пик), с какого часа хвост
   отделяется. Рядом рынок: волна — средний ход прокси-имён
   `side_wave.PROXY` (тот же список, что у S8), BTC, и остаток имени к
   волне с β, оценённой ДО входа по 72 часовым доходностям.

B. **Оси выхода, объявленные до прогона** (`AXES`): стоп по убытку, стоп
   по времени «если не в плюсе», охрана рынком (волна вверх), ранний тейк,
   остаток к рынку. Исход выхода — отметка ядра на границе часа: внутри
   часа путь не виден, стоп на −25 % в жизни сработал бы раньше и по
   другой цене — это оговорка, а не мелочь. Деньги — той же кассой, что у
   книг (`agree_book.stats_of`); контроль — случайные выходы ТОГО ЖЕ числа
   сделок в ТЕ ЖЕ часы среди открытых в тот час, 200 зёрен.

C. **Связь с рынком на входе** — β и ρ к волне за 72 ч, остаток разгона за
   сутки: квинтильный разрыв доли хвоста с перестановочным нулём, как в
   скрине входа (`tail_screen`).

Скрин и оси — КАНДИДАТЫ: правилом становится то, что пройдёт свою ось ещё
раз на новом окне; здесь право на итерацию одно.
"""
import argparse
import os
import random
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import tail_screen as T                                       # noqa: E402
import side_wave as SWV                                       # noqa: E402

ART = "DCA-path-screen"
SEEDS = 200                       # объявлено до прогона
PERMS = 200
MAIN_DEP = 10000                  # на нём идёт контроль
HOUR = 3600.0
K_LIST = (1, 2, 3, 4, 6, 8, 12, 18)          # часы анатомии
PEAKS = (0.10, 0.25, 0.50)                   # «бывал в плюсе на …» маржи
DEEP = 0.25                                  # «глубоко под водой» — четверть маржи
BETA_H = 72                                  # часов до входа для β
BETA_MIN = 48                                # меньше пар — β не измерена
PROXY = SWV.PROXY                            # волна — ТОТ ЖЕ список, что у S8
MIN_PROXY = SWV.MIN_PROXY
BOOK_KEYS = list(S.BOOKS)
# оси выхода: (ключ, название, значения) — объявлены до прогона
AXES = (
    ("loss", "стоп по убытку: выйти, когда pnl ≤ −x маржи", (0.25, 0.35, 0.50)),
    ("time", "стоп по времени: к часу k не в плюсе — выйти", (4, 8, 12)),
    ("wave", "охрана рынком: волна с входа выросла на ≥ y %", (1.0, 2.0, 3.0)),
    ("take", "ранний тейк: выйти при pnl ≥ +z маржи", (0.25, 0.50)),
    ("resid", "остаток к рынку: имя ушло вверх от волны на ≥ r % цены",
     (5.0, 10.0)),
)
# признаки связи с рынком на входе — часть C
MKT_FEATURES = (
    ("beta", "β к волне за 72 ч до входа", "рынок"),
    ("rho", "корреляция с волной за 72 ч", "рынок"),
    ("wave_24h", "ход волны за 24 ч до входа, б.п.", "рынок"),
    ("excess_24h", "ход имени минус волна за 24 ч, б.п.", "рынок"),
    ("resid_24h", "остаток имени к волне за 24 ч (с β), б.п.", "рынок"),
    ("btc_24h", "ход BTC за 24 ч до входа, б.п.", "рынок"),
)


def path_of(rec):
    """Путь позиции по часам из отметок ядра: {k: pnl долей маржи}.

    k = 1 — конец первого часа после входа (`at` — конец часа решения,
    отметка часа несёт его начало). Час без бара наследует прошлую отметку.
    """
    marks = rec.get("marks") or []
    if not marks:
        return None
    at = float(rec["at"])
    cum, raw = 0.0, {}
    for hr, d in marks:
        cum += float(d)
        k = max(1, int(round((float(hr) - at) / HOUR)) + 1)
        raw[k] = cum
    K = max(raw)
    # до первого бара позиция стоит по цене входа — pnl 0, как у самого
    # ядра (у тонкой ленты первый час бывает без единого бара)
    out, last, lead = {}, 0.0, 0
    first = min(raw)
    for k in range(1, K + 1):
        if k in raw:
            last = raw[k]
        elif k < first:
            lead += 1
        out[k] = last
    return {"cum": out, "K": K, "peak": max(out.values()), "final": out[K],
            "lead_gap": lead}


class Market:
    """Цены из часовых сводок: ход имени, волна прокси-имён, β до входа."""

    def __init__(self, hours, proxies=PROXY, min_proxy=MIN_PROXY):
        self.h = hours
        self.proxies = tuple(proxies)
        self.min_proxy = int(min_proxy)
        self._px, self._wave = {}, {}
        self.wave_none = 0

    def px(self, sym, ts):
        key = (sym, int(float(ts) // HOUR))
        if key not in self._px:
            r = self.h.row(sym, ts)
            v = r.get("mid_close") if r else None
            self._px[key] = float(v) if v else None
        return self._px[key]

    def move(self, sym, t0, t1):
        a, b = self.px(sym, t0), self.px(sym, t1)
        return (b / a - 1.0) if (a and b) else None

    def wave(self, t0, t1):
        """Средний ход прокси-имён за [t0, t1]; меньше MIN_PROXY цен — нет."""
        key = (int(float(t0) // HOUR), int(float(t1) // HOUR))
        if key not in self._wave:
            ms = [m for m in (self.move(p, t0, t1) for p in self.proxies)
                  if m is not None]
            w = float(np.mean(ms)) if len(ms) >= self.min_proxy else None
            if w is None:
                self.wave_none += 1
            self._wave[key] = w
        return self._wave[key]

    def beta_pre(self, sym, at, n=BETA_H, min_n=BETA_MIN):
        """β и ρ имени к волне по часовым доходностям ДО входа."""
        xs, ys = [], []
        t_in = float(at) - 1.0
        for j in range(int(n)):
            t1 = t_in - j * HOUR
            w, o = self.wave(t1 - HOUR, t1), self.move(sym, t1 - HOUR, t1)
            if w is None or o is None:
                continue
            xs.append(w)
            ys.append(o)
        if len(xs) < min_n:
            return None, None, len(xs)
        x, y = np.array(xs), np.array(ys)
        vx = float(x.var())
        if vx <= 0 or float(y.var()) <= 0:
            return None, None, len(xs)
        b = float(((x - x.mean()) * (y - y.mean())).mean() / vx)
        rho = float(np.corrcoef(x, y)[0, 1])
        return b, rho, len(xs)


def view_of(rec, mkt):
    """Одна сделка: путь по отметкам, рынок по часам, связь на входе."""
    p = path_of(rec)
    at, sym = float(rec["at"]), rec["sym"]
    t_in = at - 1.0
    b, rho, nb = mkt.beta_pre(sym, at)
    wave, btc, own, resid = {}, {}, {}, {}
    for k in range(1, (p["K"] if p else 0) + 1):
        t = t_in + k * HOUR
        wave[k] = mkt.wave(t_in, t)
        btc[k] = mkt.move("BTCUSDT", t_in, t)
        own[k] = mkt.move(sym, t_in, t)
        resid[k] = (own[k] - b * wave[k]
                    if (own[k] is not None and wave[k] is not None
                        and b is not None) else None)
    w24 = mkt.wave(t_in - 24 * HOUR, t_in)
    o24 = mkt.move(sym, t_in - 24 * HOUR, t_in)
    b24 = mkt.move("BTCUSDT", t_in - 24 * HOUR, t_in)
    bp = lambda v: None if v is None else v * 1e4         # noqa: E731
    f = {"beta": b, "rho": rho, "wave_24h": bp(w24), "btc_24h": bp(b24),
         "excess_24h": (bp(o24 - w24) if (o24 is not None and w24 is not None)
                        else None),
         "resid_24h": (bp(o24 - b * w24)
                       if (o24 is not None and w24 is not None
                           and b is not None) else None),
         "lev": rec.get("lev")}
    return {"rec": rec, "tail": T.is_tail(rec), "path": p, "wave": wave,
            "btc": btc, "own": own, "resid": resid, "beta": b, "rho": rho,
            "n_beta": nb, "f": f}


def _share(flags):
    flags = list(flags)
    return (sum(1 for x in flags if x) / len(flags)) if flags else None


def _med(xs):
    xs = [float(x) for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def _q(xs, q):
    xs = [float(x) for x in xs if x is not None]
    return float(np.percentile(xs, q)) if xs else None


def anatomy(views, k_list=K_LIST, deep=DEEP):
    """К часу k среди ещё открытых: где хвост, где остальные, что рынок."""
    out = []
    for k in k_list:
        op = [v for v in views if v["path"] and v["path"]["K"] > k]
        if not op:
            out.append({"k": k, "n": 0})
            continue
        tails = [v for v in op if v["tail"]]
        rest = [v for v in op if not v["tail"]]
        c_t = [v["path"]["cum"][k] for v in tails]
        c_r = [v["path"]["cum"][k] for v in rest]
        under = [v for v in op if v["path"]["cum"][k] is not None
                 and v["path"]["cum"][k] <= -deep]
        above = [v for v in op if v["path"]["cum"][k] is not None
                 and v["path"]["cum"][k] > -deep]
        out.append({
            "k": k, "n": len(op), "n_tail": len(tails),
            "tail_share": len(tails) / len(op),
            "med_tail": _med(c_t), "med_rest": _med(c_r),
            "deep_tail": _share(c is not None and c <= -deep for c in c_t),
            "deep_rest": _share(c is not None and c <= -deep for c in c_r),
            "n_under": len(under),
            "tail_under": _share(v["tail"] for v in under),
            "tail_above": _share(v["tail"] for v in above),
            "wave_tail": _med(v["wave"].get(k) for v in tails),
            "wave_rest": _med(v["wave"].get(k) for v in rest),
            "resid_tail": _med(v["resid"].get(k) for v in tails),
            "resid_rest": _med(v["resid"].get(k) for v in rest),
        })
    return out


def peaks(views, thresholds=PEAKS):
    """Бывал ли хвост в плюсе: доля с пиком ≥ порога, медиана пика, час выхода."""
    tails = [v for v in views if v["tail"] and v["path"]]
    rest = [v for v in views if not v["tail"] and v["path"]]
    pk_t = [v["path"]["peak"] for v in tails]
    pk_r = [v["path"]["peak"] for v in rest]
    ks = [v["path"]["K"] for v in tails]
    return {"n_tail": len(tails), "n_rest": len(rest),
            "peak_tail": [_share(p >= th for p in pk_t) for th in thresholds],
            "peak_rest": [_share(p >= th for p in pk_r) for th in thresholds],
            "med_peak_tail": _med(pk_t), "med_peak_rest": _med(pk_r),
            "exit_k": {"q25": _q(ks, 25), "q50": _q(ks, 50), "q75": _q(ks, 75)}}


def trigger(v, axis, val):
    """Час срабатывания оси СТРОГО до фактического выхода, иначе None."""
    p = v["path"]
    if not p:
        return None
    cum = p["cum"]
    for k in range(1, p["K"]):
        c = cum.get(k)
        if axis == "time":
            if k > val:
                return None
            if k == val and c is not None and c <= 0:
                return k
            continue
        if c is None:
            continue
        if axis == "loss" and c <= -val:
            return k
        if axis == "take" and c >= val:
            return k
        if axis == "wave":
            w = v["wave"].get(k)
            if w is not None and w >= val / 100.0:
                return k
        if axis == "resid":
            r = v["resid"].get(k)
            if r is not None and r >= val / 100.0:
                return k
    return None


def exit_at(rec, k, why="правило выхода"):
    """Та же запись, закрытая на отметке часа k: pnl ядра, срез отметок.

    Издержки те же (круг на заполненный нотионал), funding кассе даст
    короткий срок сам. Цена выхода — из pnl и плеча, для показа.
    """
    p = path_of(rec)
    c = p["cum"][k]
    at = float(rec["at"])
    marks = [m for m in rec["marks"]
             if int(round((float(m[0]) - at) / HOUR)) + 1 <= k]
    new = dict(rec, pnl=float(c), exit_ts=at + k * HOUR - 1.0, exit=why,
               marks=marks, state="closed")
    lev, e = float(rec.get("lev") or 0), rec.get("entry_px")
    if e and lev:
        new["exit_px"] = float(e) * (1.0 - float(c) / lev)      # шорт
    if rec.get("pnl_net") is not None:
        new["pnl_net"] = float(c) - (float(rec["pnl"]) - float(rec["pnl_net"]))
    return new


def apply_axis(cache, views, axis, val):
    """Кэш с выходами по оси и {ключ: час} изменённых сделок."""
    changed = {}
    for key, v in views.items():
        k = trigger(v, axis, val)
        if k is not None:
            changed[key] = k
    mod = dict(cache)
    for key, k in changed.items():
        mod[key] = exit_at(cache[key], k)
    return mod, changed


def deltas(cache, views, changed):
    """Сумма приращений pnl (долей маржи) и состав изменённых сделок."""
    d, tails, winners = 0.0, 0, 0
    for key, k in changed.items():
        old = float(cache[key]["pnl"])
        new = float(views[key]["path"]["cum"][k])
        d += new - old
        if views[key]["tail"]:
            tails += 1
        if new < old:
            winners += 1
    return {"sum": d, "n": len(changed), "tails": tails, "cut_worse": winners}


def open_index(views):
    """{линейка: {k: [ключи сделок, открытых после часа k]}} — для контроля."""
    idx = {}
    for key, v in views.items():
        if not v["path"]:
            continue
        for k in range(1, v["path"]["K"]):
            idx.setdefault(key[0], {}).setdefault(k, []).append(key)
    return idx


def control_exits(cache, views, changed, ctx, launch, seeds=SEEDS,
                  dep=MAIN_DEP, now=None, log=print, idx=None):
    """Случайные выходы ТОГО ЖЕ числа сделок в ТЕ ЖЕ часы среди открытых.

    Пары (линейка, час) берутся у самой оси: контроль сравнивает правило
    с «выйти столько же раз в те же часы наугад» — иначе он мерил бы
    другой срок, а не другой выбор.
    """
    idx = idx if idx is not None else open_index(views)
    hours = {}
    for key, k in changed.items():
        hours.setdefault(key[0], []).append(k)
    out = {"books": {}, "sum": [], "tails": [], "no_cand": 0}
    t0 = time.time()
    for i in range(int(seeds)):
        rnd = random.Random(1000 + i)
        mod, used, dsum, dtails = dict(cache), set(), 0.0, 0
        for rk, ks in hours.items():
            for k in ks:
                pool = (idx.get(rk) or {}).get(k) or []
                pick = None
                for _try in range(20):
                    if not pool:
                        break
                    c = rnd.choice(pool)
                    if c not in used:
                        pick = c
                        break
                if pick is None:
                    out["no_cand"] += 1
                    continue
                used.add(pick)
                mod[pick] = exit_at(cache[pick], k, why="случайный выход")
                dsum += float(views[pick]["path"]["cum"][k]) - float(cache[pick]["pnl"])
                dtails += 1 if views[pick]["tail"] else 0
        st = AG.stats_of(AG.packed_short(mod), ctx, launch, BOOK_KEYS,
                         deps=[dep], now=now)
        for bk in BOOK_KEYS:
            c = st.get(f"{bk}:{int(dep)}") or {}
            out["books"].setdefault(bk, []).append(
                {"final": c.get("final"), "ratio": c.get("ratio"),
                 "max_dd": c.get("max_dd")})
        out["sum"].append(dsum)
        out["tails"].append(dtails)
        if i and i % 50 == 0:
            log(f"    контроль: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    return out


def run_axes(cache, views, ctx, launch, seeds=SEEDS, dep=MAIN_DEP, now=None,
             log=print, axes=AXES):
    base = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                       deps=[dep], now=now)
    idx = open_index(views)
    out = []
    for axis, title, vals in axes:
        cells = []
        for val in vals:
            mod, changed = apply_axis(cache, views, axis, val)
            d = deltas(cache, views, changed)
            log(f"ось {axis} {val:g}: изменено {d['n']} сделок "
                f"(хвостовых {d['tails']}), Σ долей маржи {d['sum']:+.2f}")
            cell = {"val": val, "delta": d, "stats": None, "control": None}
            if changed:
                cell["stats"] = AG.stats_of(AG.packed_short(mod), ctx, launch,
                                            BOOK_KEYS, deps=[dep], now=now)
                ctl = control_exits(cache, views, changed, ctx, launch,
                                    seeds=seeds, dep=dep, now=now, log=log,
                                    idx=idx)
                cell["control"] = ctl
                beat = {}
                for bk in BOOK_KEYS:
                    st = cell["stats"].get(f"{bk}:{int(dep)}") or {}
                    beat[bk] = {f: AG.beat_share(ctl["books"].get(bk), st.get(f), f)[0]
                                for f in ("final", "ratio")}
                beat["sum"] = AG.beat_share([{"sum": x} for x in ctl["sum"]],
                                            d["sum"], "sum")[0]
                cell["beat"] = beat
            cells.append(cell)
        out.append({"axis": axis, "title": title, "cells": cells})
    return base, out


def market_screen(views, perms=PERMS, features=MKT_FEATURES):
    """Часть C: признаки связи с рынком на входе тем же разрывом квинтилей."""
    rows = []
    for key, title, src in features:
        have = [(v["f"].get(key), v["tail"]) for v in views
                if v["f"].get(key) is not None]
        n_miss = len(views) - len(have)
        if len(have) < 5 * T.QUANT:
            rows.append({"key": key, "title": title, "src": src,
                         "n": len(have), "missing": n_miss,
                         "why": ("лист этих полей не несёт" if not have
                                 else "сделок с признаком мало")})
            continue
        x = np.array([h[0] for h in have], dtype=float)
        y = np.array([1.0 if h[1] else 0.0 for h in have])
        sp, shares, n = T.quintile_spread(x, y)
        rows.append({"key": key, "title": title, "src": src, "n": n,
                     "missing": n_miss, "distinct": int(len(np.unique(x))),
                     "tail_share": float(y.mean()),
                     "med_tail": (float(np.median(x[y > 0])) if (y > 0).any()
                                  else None),
                     "med_rest": (float(np.median(x[y == 0])) if (y == 0).any()
                                  else None),
                     "spread": sp, "shares": shares,
                     "perm": T.perm_share(x, y, sp, perms=perms)})
    rows.sort(key=lambda d: -abs(d.get("spread") or 0.0))
    return rows


def run(seeds=SEEDS, perms=PERMS, log=print, summary_dir=None, mem_limit=None,
        now=None, launch=None, ctx=None, axes=AXES):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        log(f"дорога не считается: {why}")
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    hours = T.Hours(root=summary_dir or T.SUMMARY_DIR)
    mkt = Market(hours)
    closed = {key: r for key, r in cache.items()
              if key[0] in T.RULERS and r.get("state", "closed") == "closed"}
    views, no_marks, mismatch, lead = {}, 0, 0, 0
    for i, (key, r) in enumerate(sorted(closed.items(), key=lambda kv: kv[0][2])):
        v = view_of(r, mkt)
        if v["path"] is None:
            no_marks += 1
        elif abs(v["path"]["final"] - float(r["pnl"])) > 1e-6:
            mismatch += 1
        lead += 1 if (v["path"] and v["path"]["lead_gap"]) else 0
        views[key] = v
        if i and i % 1000 == 0:
            log(f"дорога: {i} сделок из {len(closed)}, {time.time() - t0:.0f} с")
    n_beta = sum(1 for v in views.values() if v["beta"] is not None)
    log(f"сделок {len(views)}, без отметок {no_marks}, отметка ≠ исходу "
        f"{mismatch}, первый час без бара у {lead}, β измерена у {n_beta}; "
        "волна не собралась "
        f"{mkt.wave_none} раз; сводок есть/нет {hours.hit}/{hours.miss}")
    rulers = []
    for rk in T.RULERS:
        vs = [v for key, v in views.items() if key[0] == rk]
        hi = [v for v in vs if (v["f"].get("lev") or 0) >= T.HIGH_LEV]
        rulers.append({"ruler": rk, "title": R.ruler_title(rk), "n": len(vs),
                       "n_tail": sum(1 for v in vs if v["tail"]),
                       "anatomy": anatomy(vs), "peaks": peaks(vs),
                       "market": market_screen(vs, perms=perms),
                       "market_high": market_screen(hi, perms=perms),
                       "n_high": len(hi)})
        log(f"{rk}: сделок {len(vs)}, хвостовых {rulers[-1]['n_tail']}")
    base, ax = run_axes(cache, views, ctx, launch, seeds=seeds, dep=MAIN_DEP,
                        now=now, log=log, axes=axes)
    return {"rulers": rulers, "base": base, "axes": ax, "seeds": int(seeds),
            "perms": int(perms), "dep": MAIN_DEP, "k_list": list(K_LIST),
            "peaks": list(PEAKS), "deep": DEEP, "beta_h": BETA_H,
            "proxies": len(PROXY), "books": BOOK_KEYS,
            "diag": {"n": len(views), "no_marks": no_marks,
                     "mismatch": mismatch, "lead_gap": lead, "beta": n_beta,
                     "wave_none": mkt.wave_none,
                     "hours": {"есть сводка": hours.hit,
                               "нет сводки": hours.miss}},
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):+.{d}f}"


def _anatomy_table(rows, deep):
    dp = f"{100 * deep:.0f} %"
    L = [f"| час k | открытых | хвостовых среди них | pnl хвоста (медиана) "
         f"| pnl остальных | хвост ниже −{dp} | остальные ниже −{dp} "
         f"| доля хвоста среди тех, кто ниже −{dp} | среди тех, кто выше "
         f"| волна: хвост / остальные | остаток к волне: хвост / остальные |",
         "|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for a in rows:
        if not a.get("n"):
            L.append(f"| {a['k']} | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        L.append(f"| {a['k']} | {a['n']} | {a['n_tail']} ({_p(a['tail_share'])}) "
                 f"| {_pp(a['med_tail'])} | {_pp(a['med_rest'])} "
                 f"| {_p(a['deep_tail'])} | {_p(a['deep_rest'])} "
                 f"| {_p(a['tail_under'])} ({a['n_under']}) | {_p(a['tail_above'])} "
                 f"| {_pp(a['wave_tail'], 2)} / {_pp(a['wave_rest'], 2)} "
                 f"| {_pp(a['resid_tail'], 2)} / {_pp(a['resid_rest'], 2)} |")
    return L


def _peaks_table(pk, thresholds):
    L = ["| | " + " | ".join(f"пик ≥ +{100 * t:.0f} % маржи" for t in thresholds)
         + " | медиана пика |", "|---|" + "--:|" * (len(thresholds) + 1)]
    L.append(f"| хвост ({pk['n_tail']}) | "
             + " | ".join(_p(x) for x in pk["peak_tail"])
             + f" | {_pp(pk['med_peak_tail'])} |")
    L.append(f"| остальные ({pk['n_rest']}) | "
             + " | ".join(_p(x) for x in pk["peak_rest"])
             + f" | {_pp(pk['med_peak_rest'])} |")
    e = pk["exit_k"]
    L += ["", f"Час выхода хвоста: медиана {_i(e['q50'])} (четверти "
          f"{_i(e['q25'])}–{_i(e['q75'])})."]
    return L


def _i(x):
    return "—" if x is None else f"{float(x):.0f}"


def _axes_tables(s):
    dep = int(s["dep"])
    base = s.get("base") or {}
    L = []
    for bk in s["books"]:
        b = base.get(f"{bk}:{dep}") or {}
        L.append(f"- {R.ruler_title(bk)} (`{bk}`), как сейчас: итог "
                 f"{_pp(b.get('final'))}, просадка {_pp(b.get('max_dd'))}, "
                 f"сделок {b.get('n') if b.get('n') is not None else '—'}.")
    L.append("")
    for ax in s["axes"]:
        L += [f"### {ax['title']}", "",
              "| порог | изменено сделок (хвостовых; срезано в минус) "
              "| Σ долей маржи: правило / случайные выходы (медиана) "
              "| зёрен, где случайные не хуже | "
              + " | ".join(f"{R.ruler_title(bk)}: итог, просадка / зёрен не хуже"
                           for bk in s["books"]) + " |",
              "|--:|--:|--:|--:|" + "--:|" * len(s["books"])]
        for c in ax["cells"]:
            d = c["delta"]
            if not d["n"]:
                L.append(f"| {c['val']:g} | 0 | — | — |"
                         + " не сработало ни разу |" * len(s["books"]))
                continue
            ctl = c.get("control") or {}
            med_ctl = _med(ctl.get("sum") or [])
            beat = c.get("beat") or {}
            cells = []
            for bk in s["books"]:
                st = (c.get("stats") or {}).get(f"{bk}:{dep}") or {}
                bt = beat.get(bk) or {}
                cells.append(f"{_pp(st.get('final'))}, {_pp(st.get('max_dd'))} "
                             f"/ {_p(bt.get('final'), 0)}")
            L.append(f"| {c['val']:g} | {d['n']} ({d['tails']}; {d['cut_worse']}) "
                     f"| {_f(d['sum'])} / {_f(med_ctl)} | {_p(beat.get('sum'), 0)} | "
                     + " | ".join(cells) + " |")
        L.append("")
    return L


def report(s):
    L = ["# Дорога сделки коротких книг: что происходит после входа и можно ли выйти раньше",
         "",
         "Просьба владельца 2026-09-13: смотреть не только момент входа, а "
         "развитие сделки — можно ли выйти раньше, и связь имени с рынком и "
         "гигантами. **Часть A** — анатомия пути по почасовым отметкам ядра "
         "симуляции (второй формулы pnl здесь нет); **часть B** — оси выхода, "
         "объявленные до прогона, деньги той же кассой, контроль — случайные "
         "выходы того же числа сделок в те же часы среди открытых "
         f"({s.get('seeds') or SEEDS} зёрен); **часть C** — связь с рынком на "
         "входе с перестановочным нулём. **Оговорка, без которой часть B "
         "читать нельзя:** исход выхода берётся по отметке ядра на границе "
         "часа — внутри часа путь не виден, стоп по убытку в жизни сработал "
         "бы раньше и по другой цене; это верхняя оценка аккуратности, а не "
         "реплей. Правилом ни одна ось не становится: право на итерацию одно, "
         "и оно тратится на новом окне.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    dg = s.get("diag") or {}
    L += [f"Сделок {dg.get('n')}, без отметок ядра {dg.get('no_marks')}, "
          f"последняя отметка ≠ исходу у {dg.get('mismatch')} (обязано быть 0), "
          f"первый час после входа без бара у {dg.get('lead_gap')} (там pnl 0 до "
          "первой отметки), "
          f"β к волне измерена у {dg.get('beta')} (нужно ≥ {BETA_MIN} часов из "
          f"{s.get('beta_h')}); волна — средний ход {s.get('proxies')} прокси-имён, "
          f"не собралась {dg.get('wave_none')} раз; сводок стакана есть/нет: "
          f"{(dg.get('hours') or {}).get('есть сводка')}/"
          f"{(dg.get('hours') or {}).get('нет сводки')}.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой части.", ""]
    L += ["## A. Анатомия пути", "",
          "Среди сделок, ещё ОТКРЫТЫХ после часа k: сколько из них окажутся "
          "хвостом, где стоит медианный pnl хвоста и остальных, какая доля "
          f"уже глубже −{100 * s.get('deep', DEEP):.0f} % маржи, и наоборот — "
          "какая доля хвоста среди тех, кто глубже (это и есть «отделяется ли "
          "хвост к часу k»). Рядом медианный ход волны рынка с момента входа и "
          "остаток имени к волне (ход имени минус β·волна, β до входа).", ""]
    for f in s.get("rulers") or []:
        L += [f"### {f['title']} (`{f['ruler']}`)", "",
              f"Сделок {f['n']}, хвостовых {f['n_tail']} "
              f"({_p(f['n_tail'] / max(1, f['n']))}).", ""]
        L += _anatomy_table(f["anatomy"], s.get("deep", DEEP)) + [""]
        L += ["**Бывал ли хвост в плюсе.**", ""]
        L += _peaks_table(f["peaks"], s.get("peaks") or PEAKS) + [""]
    L += ["## B. Оси выхода", "",
          "Каждая ось меняет только сделки, у которых она сработала СТРОГО до "
          "фактического выхода; остальные как есть. «Σ долей маржи» — сумма "
          "приращений pnl изменённых сделок в долях их маржи (+1.00 = спасена "
          "одна маржа); рядом та же сумма у случайных выходов того же числа в "
          "те же часы (медиана по зёрнам) и доля зёрен, где случайные не хуже. "
          "Деньги книг — касса семейства на депозите "
          f"${s.get('dep')}, нетто.", ""]
    L += _axes_tables(s)
    L += ["## C. Связь с рынком на входе", "",
          "Квинтильный разрыв доли хвоста по признаку и перестановочный нуль "
          f"({s.get('perms') or PERMS} перемешиваний меток), как в скрине "
          "входа; жирным — ни одна перестановка не дала такого разрыва.", ""]
    for f in s.get("rulers") or []:
        L += [f"### {f['title']} (`{f['ruler']}`) — все сделки", ""]
        L += T._table(f["market"], s.get("perms") or PERMS) + [""]
        L += [f"### {f['title']} — только плечо ≥ {T.HIGH_LEV:g}× ({f['n_high']})", ""]
        L += T._table(f["market_high"], s.get("perms") or PERMS) + [""]
    L += ["## Как читать", "",
          "- Хвост, который к часу k уже глубже −25 % и почти не встречается "
          "выше, — кандидат на стоп по убытку; хвост, который до конца стоит "
          "рядом с остальными, — стопом не берётся, он рождается в последний час.",
          "- Ось, чья Σ долей маржи не лучше случайных выходов в те же часы, "
          "не есть правило: она просто укорачивает сделки.",
          "- Ось с выигрышем по Σ маржи и проигрышем по итогу книги режет "
          "мотор: спасённые хвосты дешевле срезанных победителей.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--perms", type=int, default=PERMS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(seeds=a.seeds, perms=a.perms, log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("дорога сделки коротких книг: анатомия пути, оси выхода, рынок")


if __name__ == "__main__":
    main()
