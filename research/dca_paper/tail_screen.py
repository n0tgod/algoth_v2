#!/usr/bin/env python3
"""Портрет хвоста коротких книг: что общего у минусовых сделок.

Просьба владельца 2026-09-12 («что общего ещё мы можем найти у этих
минусовых сделок — по стакану, ленте, объёмам в момент входа или до
входа»). Отбор по имени и по геометрии входа закрыт пятью замерами;
здесь спрашивается не «какое правило завести», а «чем хвостовая сделка
отличалась от остальных В МОМЕНТ РЕШЕНИЯ».

ЭТО СКРИН, А НЕ ЗАМЕР ПРАВИЛА. Признаков много, сделок одних и тех же —
и лучшая ячейка находится всегда (ошибка R5). Поэтому:

* хвост объявлен ДО просмотра: сделка вышла полом или ликвидацией
  (`TAIL_EXITS`). Это событие симуляции, а не порог на деньгах;
* список признаков объявлен ДО просмотра (`FEATURES`), считается
  число испытаний и ожидаемое число ложных находок при уровне 1/200;
* у каждого признака стоит ПЕРЕСТАНОВОЧНЫЙ нуль: метки хвоста
  перемешиваются `PERMS` раз, и печатается доля перестановок, давших
  разрыв не меньше наблюдаемого. Одна таблица без нуля — сам шум;
* хвост живёт на большом плече по построению (пол ближе), и признак,
  связанный с плечом, «найдётся» из-за него. Поэтому скрин считается
  дважды: на всех сделках и ВНУТРИ полосы плеча ≥ `HIGH_LEV`;
* результат скрина — КАНДИДАТ для одной объявленной оси с контролем
  случайной выборкой того же размера, и ничего больше.

ОТКУДА ПРИЗНАКИ. Момент входа — часовая сводка стакана и ленты
(`s8_loop/out/summary/<имя>/<дата>.jsonl`): спред, доллары у лучшей
цены, съедаемая глубина, крупные принты, число сделок, перекос
покупок/продаж, пик объёма за секунду, ставка funding, открытый
интерес, базис, принудительные закрытия шортов и лонгов за час. «До
входа» — те же сводки за прошлые 1/6/24 часа: ход цены, размах,
отношение объёма и спреда к своей суточной медиане, изменение интереса,
сумма принудительных закрытий. Модель — из ног листа: |прогноз|,
отношение, новизна признаков (`odd`), бета, прогноз в σ. Позиция —
плечо и час суток.

«Не измерено» — прочерк: признак без записи в сделке не участвует, и
число таких сделок печатается рядом с каждым признаком.

Запуск: `run research/dca_paper/tail_screen.py`. Смоук: `--perms 5`.
"""
import argparse
import json
import math
import os
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
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402

ART = "DCA-tail-screen"
PERMS = 200                       # объявлено до прогона
HIGH_LEV = 15.0                   # полоса, где живёт хвост
QUANT = 5                         # квинтили признака
TAIL_EXITS = ("пол", "ликвидация")
SUMMARY_DIR = os.path.join(ROOT, "research", "s8_loop", "out", "summary")
HOUR = 3600.0
# Линейки коротких книг: безопасная (пол 0.10) и оптимальная (пол 0.50).
RULERS = tuple(dict.fromkeys(S.BOOKS.values()))

# Признаки объявлены ДО просмотра — (ключ, подпись, откуда).
FEATURES = (
    # момент входа: стакан и лента
    ("spread_bp", "спред, б.п.", "стакан"),
    ("touch_usd", "доллары у лучшей цены своей стороны", "стакан"),
    ("depth_eat", "съедаемая глубина своей стороны, $", "стакан"),
    ("big_med", "медианный крупный принт, $", "лента"),
    ("n_trades", "сделок за час", "лента"),
    ("imb", "перекос покупок к продажам, −1…+1", "лента"),
    ("vol_max_1s", "пик объёма за секунду", "лента"),
    ("reach_bp", "досягаемость цены за час, б.п.", "лента"),
    ("upd", "обновлений стакана в секунду", "стакан"),
    ("range_bp", "размах часа, б.п.", "цена"),
    ("fr", "ставка funding", "площадка"),
    ("oi_usd", "открытый интерес, $", "площадка"),
    ("basis_bp", "базис к индексу, б.п.", "площадка"),
    ("liq_short", "принудительно выкуплено шортов за час, $", "площадка"),
    ("liq_long", "принудительно продано лонгов за час, $", "площадка"),
    # до входа
    ("ret_1h", "ход цены за 1 ч, б.п.", "до входа"),
    ("ret_6h", "ход цены за 6 ч, б.п.", "до входа"),
    ("ret_24h", "ход цены за 24 ч, б.п.", "до входа"),
    ("range_24h_bp", "размах за 24 ч, б.п.", "до входа"),
    ("vol_ratio", "объём часа к своей суточной медиане", "до входа"),
    ("spread_ratio", "спред к своей суточной медиане", "до входа"),
    ("oi_chg_24h", "изменение интереса за 24 ч, доля", "до входа"),
    ("liq_short_24h", "выкуплено шортов за 24 ч, $", "до входа"),
    # модель
    ("fwd", "|прогноз|, б.п.", "модель"),
    ("rr", "отношение обещания к риску", "модель"),
    ("adv_q", "ожидаемый ход против, б.п.", "модель"),
    ("odd", "новизна вектора признаков", "модель"),
    ("beta", "бета к волне", "модель"),
    ("fwd_z", "прогноз в σ", "модель"),
    # позиция
    ("lev", "плечо", "позиция"),
    ("hour_utc", "час суток входа, UTC", "позиция"),
)


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class Hours:
    """Часовые сводки по имени с оглядкой назад — файл дня читается раз."""

    def __init__(self, root=SUMMARY_DIR):
        self.root = root
        self._day = {}
        self.miss = 0
        self.hit = 0

    def _load(self, sym, day):
        key = (sym, day)
        if key in self._day:
            return self._day[key]
        rows = {}
        try:
            with open(os.path.join(self.root, sym, day + ".jsonl"),
                      encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("hour"):
                        rows[r["hour"]] = r
        except OSError:
            rows = {}
        if len(self._day) > 6000:
            self._day.clear()
        self._day[key] = rows
        return rows

    def row(self, sym, ts):
        """Сводка часа, в который попадает момент `ts`."""
        hour = time.strftime("%Y-%m-%d-%H", time.gmtime(float(ts)))
        r = self._load(sym, hour[:10]).get(hour)
        if r is None:
            self.miss += 1
        else:
            self.hit += 1
        return r

    def back(self, sym, ts, n):
        """Сводки n предыдущих часов, старые сначала; пропуски — None."""
        return [self.row(sym, float(ts) - k * HOUR) for k in range(n, 0, -1)]


def _med(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def features_of(rec, leg, hours):
    """Портрет ОДНОГО решения — признаки момента входа и суток до него.

    Час решения — час, закрытие которого и есть момент входа (`at` —
    конец часа выбора), поэтому сводка берётся за `at − 1 с`.
    """
    sym, at = rec.get("sym"), float(rec["at"])
    side = rec.get("side") or "short"
    f = {}
    h0 = hours.row(sym, at - 1.0)
    if h0:
        f["spread_bp"] = _f(h0.get("spread_bp"))
        f["touch_usd"] = _f(h0.get("best_b" if side == "short" else "best_a"))
        f["depth_eat"] = _f(h0.get("depth_eat_b" if side == "short"
                                   else "depth_eat_a"))
        f["big_med"] = _f(h0.get("big_med"))
        f["n_trades"] = _f(h0.get("n_trades"))
        b, s_ = _f(h0.get("buy")), _f(h0.get("sell"))
        f["imb"] = (None if b is None or s_ is None or b + s_ <= 0
                    else (b - s_) / (b + s_))
        f["vol_max_1s"] = _f(h0.get("vol_max_1s"))
        f["reach_bp"] = _f(h0.get("reach_bp"))
        f["upd"] = _f(h0.get("upd"))
        hi, lo, cl = (_f(h0.get("mid_high")), _f(h0.get("mid_low")),
                      _f(h0.get("mid_close")))
        f["range_bp"] = (None if not cl or hi is None or lo is None
                         else (hi - lo) / cl * 1e4)
        f["fr"] = _f(h0.get("fr"))
        f["oi_usd"] = _f(h0.get("oi_usd"))
        f["basis_bp"] = _f(h0.get("basis_bp"))
        f["liq_short"] = _f(h0.get("liq_short"))
        f["liq_long"] = _f(h0.get("liq_long"))
        prev = hours.back(sym, at - 1.0, 24)
        closes = [_f(p.get("mid_close")) if p else None for p in prev]

        def _ret(k):
            c0 = closes[-k] if k <= len(closes) else None
            return (None if not c0 or not cl else (cl / c0 - 1.0) * 1e4)
        f["ret_1h"], f["ret_6h"], f["ret_24h"] = _ret(1), _ret(6), _ret(24)
        highs = [_f(p.get("mid_high")) for p in prev if p]
        lows = [_f(p.get("mid_low")) for p in prev if p]
        highs = [x for x in highs if x is not None]
        lows = [x for x in lows if x is not None]
        f["range_24h_bp"] = (None if not cl or len(highs) < 12 or not lows
                             else (max(highs) - min(lows)) / cl * 1e4)
        mt = _med([_f(p.get("n_trades")) for p in prev if p])
        f["vol_ratio"] = (None if not mt or f["n_trades"] is None
                          else f["n_trades"] / mt)
        ms = _med([_f(p.get("spread_bp")) for p in prev if p])
        f["spread_ratio"] = (None if not ms or f["spread_bp"] is None
                             else f["spread_bp"] / ms)
        oi0 = _f(prev[0].get("oi_usd")) if prev and prev[0] else None
        f["oi_chg_24h"] = (None if not oi0 or f["oi_usd"] is None
                           else f["oi_usd"] / oi0 - 1.0)
        ls = [_f(p.get("liq_short")) for p in prev if p]
        ls = [x for x in ls if x is not None]
        f["liq_short_24h"] = sum(ls) if len(ls) >= 12 else None
    for k in ("fwd", "rr", "adv_q", "odd", "beta", "fwd_z"):
        v = (leg or {}).get(k)
        f[k] = None if v is None else abs(_f(v)) if k == "fwd" else _f(v)
    f["lev"] = _f(rec.get("lev"))
    f["hour_utc"] = float(time.gmtime(at - 1.0).tm_hour)
    return f


def is_tail(rec):
    return (rec.get("exit") or "") in TAIL_EXITS


def quintile_spread(x, y, q=QUANT):
    """Доля хвоста в верхнем квинтиле признака минус в нижнем.

    Квинтили по рангу с случайным разрывом связей не нужны: связи у
    признаков стакана редки, а у часа суток квинтили заведомо грубы —
    об этом сказано в отчёте, а не спрятано в формуле.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(x)
    if n < 5 * q:
        return None, None, None
    order = np.argsort(x, kind="stable")
    bins = np.array_split(order, q)
    shares = [float(y[b].mean()) if len(b) else None for b in bins]
    return shares[-1] - shares[0], shares, n


def perm_share(x, y, spread, perms=PERMS, seed=7):
    """Доля перестановок меток, давших разрыв не меньше наблюдаемого."""
    if spread is None:
        return None
    rnd = np.random.default_rng(seed)
    y = np.asarray(y, dtype=float)
    hits = 0
    for _ in range(int(perms)):
        sp, _s, _n = quintile_spread(x, rnd.permutation(y))
        if sp is not None and abs(sp) >= abs(spread) - 1e-12:
            hits += 1
    return hits / max(1, int(perms))


def screen(rows, perms=PERMS):
    """Таблица скрина по признакам: разрыв квинтилей и его нуль."""
    out = []
    y_all = np.array([1.0 if r["tail"] else 0.0 for r in rows])
    for key, title, src in FEATURES:
        xs = [(r["f"].get(key), r["tail"]) for r in rows]
        have = [(x, t) for x, t in xs if x is not None]
        n_miss = len(xs) - len(have)
        if len(have) < 5 * QUANT:
            out.append({"key": key, "title": title, "src": src,
                        "n": len(have), "missing": n_miss,
                        "why": "сделок с признаком мало"})
            continue
        x = np.array([h[0] for h in have])
        y = np.array([1.0 if h[1] else 0.0 for h in have])
        sp, shares, n = quintile_spread(x, y)
        out.append({"key": key, "title": title, "src": src, "n": n,
                    "missing": n_miss,
                    "tail_share": float(y.mean()),
                    "med_tail": (float(np.median(x[y > 0])) if (y > 0).any()
                                 else None),
                    "med_rest": (float(np.median(x[y == 0]))
                                 if (y == 0).any() else None),
                    "spread": sp, "shares": shares,
                    "perm": perm_share(x, y, sp, perms=perms)})
    out.sort(key=lambda d: -abs(d.get("spread") or 0.0))
    return out


def portrait(rows, k=20):
    """Худшие сделки окна и ранг каждого их признака среди всех сделок.

    Ранг в долях (0 — самое малое значение, 1 — самое большое): портрет
    хвоста читается по тому, где у него стоят медианные ранги.
    """
    worst = sorted(rows, key=lambda r: float(r["rec"].get("pnl") or 0))[:k]
    ranks = {}
    for key, _t, _s in FEATURES:
        xs = np.array([r["f"].get(key) for r in rows
                       if r["f"].get(key) is not None], dtype=float)
        if len(xs) < 10:
            continue
        xs.sort()
        ranks[key] = xs
    out = []
    for r in worst:
        pr = {}
        for key, xs in ranks.items():
            v = r["f"].get(key)
            if v is None:
                continue
            pr[key] = float(np.searchsorted(xs, v, side="right") / len(xs))
        out.append({"sym": r["rec"].get("sym"),
                    "at": time.strftime("%m-%d %H:%M",
                                        time.gmtime(float(r["rec"]["at"]))),
                    "pnl": float(r["rec"].get("pnl") or 0),
                    "exit": r["rec"].get("exit"),
                    "lev": r["f"].get("lev"), "ranks": pr})
    med = {}
    for key in ranks:
        vals = [o["ranks"].get(key) for o in out if o["ranks"].get(key)
                is not None]
        if vals:
            med[key] = float(np.median(vals))
    return {"worst": out, "median_rank": med}


def run(perms=PERMS, log=print, summary_dir=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        log(f"скрин не считается: {why}")
        return {"error": f"кэш реплея непригоден: {why}"}
    legs = S.legs(log=log)
    leg_of = {}
    for g in legs:
        leg_of.setdefault((g["sym"], round(float(g["at"]), 3)), g)
    hours = Hours(root=summary_dir or SUMMARY_DIR)
    fams = []
    for rk in RULERS:
        recs = [r for (k, _s, _a), r in cache.items() if k == rk
                and r.get("state", "closed") == "closed"]
        rows = []
        for r in recs:
            leg = leg_of.get((r["sym"], round(float(r["at"]), 3)))
            rows.append({"rec": r, "tail": is_tail(r),
                         "f": features_of(r, leg, hours)})
        n_tail = sum(1 for r in rows if r["tail"])
        log(f"{rk}: сделок {len(rows)}, хвостовых {n_tail} "
            f"({100.0 * n_tail / max(1, len(rows)):.1f} %)")
        hi = [r for r in rows if (r["f"].get("lev") or 0) >= HIGH_LEV]
        fams.append({"ruler": rk, "title": R.ruler_title(rk),
                     "n": len(rows), "n_tail": n_tail,
                     "all": screen(rows, perms=perms),
                     "high": screen(hi, perms=perms),
                     "n_high": len(hi),
                     "n_tail_high": sum(1 for r in hi if r["tail"]),
                     "portrait": portrait(rows)})
    return {"rulers": fams, "perms": int(perms), "high_lev": HIGH_LEV,
            "features": len(FEATURES), "tail_exits": list(TAIL_EXITS),
            "hours": {"есть сводка": hours.hit, "нет сводки": hours.miss},
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _v(x):
    if x is None:
        return "—"
    x = float(x)
    if abs(x) >= 1e5:
        return f"{x:,.0f}"
    if abs(x) >= 100:
        return f"{x:.0f}"
    return f"{x:.3g}"


def _table(rows, perms):
    L = ["| признак | откуда | сделок (без признака) | медиана хвоста | "
         "медиана остальных | хвост в нижнем квинтиле | в верхнем | "
         "разрыв | доля перестановок не меньше |",
         "|---|---|--:|--:|--:|--:|--:|--:|--:|"]
    for d in rows:
        if d.get("why"):
            L.append(f"| {d['title']} | {d['src']} | {d['n']} ({d['missing']}) "
                     f"| — | — | — | — | — | {d['why']} |")
            continue
        sh = d.get("shares") or [None, None]
        pm = d.get("perm")
        mark = "**" if pm is not None and pm <= 1.0 / max(1, perms) else ""
        sp = d.get("spread")
        sp_s = "—" if sp is None else f"{100.0 * sp:+.1f} п.п."
        pm_s = "—" if pm is None else f"{100.0 * pm:.1f} %"
        L.append(f"| {mark}{d['title']}{mark} | {d['src']} | {d['n']} "
                 f"({d['missing']}) | {_v(d.get('med_tail'))} | "
                 f"{_v(d.get('med_rest'))} | {_p(sh[0])} | {_p(sh[-1])} | "
                 f"{sp_s} | {pm_s} |")
    return L


def report(s):
    # у отчёта об отказе чисел прогона нет — константы скрина печатаются
    # из модуля, а не словом None
    nf = int(s.get("features") or len(FEATURES))
    npm = int(s.get("perms") or PERMS)
    L = ["# Портрет хвоста коротких книг: что общего у минусовых сделок",
         "",
         "Просьба владельца 2026-09-12: найти, что общего у минусовых "
         "сделок по стакану, ленте и объёмам — в момент входа и до него. "
         "**Это скрин, а не замер правила.** Хвост объявлен до просмотра "
         f"(выход {' или '.join(s.get('tail_exits') or TAIL_EXITS)}), "
         f"признаков {nf}, у каждого перестановочный нуль "
         f"({npm} перестановок меток). Ожидаемое число ложных "
         f"находок на уровне 1/{npm} при {nf} "
         "признаках × 2 полосы × 2 линейки — около "
         f"{4 * nf / max(1, npm):.1f}"
         ". Жирным — признаки, у которых ни одна перестановка не дала "
         "такого разрыва; правилом и они не становятся, а идут "
         "кандидатами в одну объявленную ось с контролем случайной "
         "выборкой.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    hs = s.get("hours") or {}
    L += [f"Сводок стакана на моменты решений: {hs}. Признак без записи "
          "в сделке не участвует — число таких сделок стоит в скобках "
          "рядом с каждым признаком.", "",
          "**Как читать разрыв.** Сделки делятся на пять квинтилей по "
          "признаку; печатается доля хвоста в нижнем и верхнем и их "
          "разность в процентных пунктах. Знак говорит, на каком конце "
          "хвост чаще. «Доля перестановок не меньше» — сколько из "
          "случайных перемешиваний меток дали разрыв такой же или больше: "
          "50 % значит «как монетка».", ""]
    for f in s.get("rulers") or []:
        L += [f"## {f['title']} (`{f['ruler']}`)", "",
              f"Сделок {f['n']}, хвостовых {f['n_tail']} "
              f"({100.0 * f['n_tail'] / max(1, f['n']):.1f} %); в полосе плеча "
              f"≥ {s.get('high_lev'):g}× сделок {f['n_high']}, хвостовых "
              f"{f['n_tail_high']}.", "",
              "### Все сделки", ""] + _table(f["all"], s.get("perms")) + [""]
        L += [f"### Только плечо ≥ {s.get('high_lev'):g}×", "",
              "Хвост живёт на большом плече по построению — пол ближе. "
              "Признак, работающий и здесь, не есть переодетое плечо.", ""]
        L += _table(f["high"], s.get("perms")) + [""]
        pt = f.get("portrait") or {}
        med = pt.get("median_rank") or {}
        if med:
            L += ["### Портрет двадцати худших", "",
                  "Ранг признака среди всех сделок линейки: 0 — самое малое "
                  "значение, 1 — самое большое; печатается медиана ранга по "
                  "двадцати худшим. Ранг около 0.5 — хвост ничем не выделен; "
                  "у края — есть за что зацепиться.", "",
                  "| признак | медиана ранга у худших |", "|---|--:|"]
            for key, title, _src in FEATURES:
                if key in med:
                    L.append(f"| {title} | {med[key]:.2f} |")
            L.append("")
            L += ["| сделка | вход | % маржи | исход | плечо |",
                  "|---|---|--:|---|--:|"]
            for w in pt.get("worst") or []:
                L.append(f"| {w['sym']} | {w['at']} | {100 * w['pnl']:+.0f} | "
                         f"{w['exit']} | {_v(w.get('lev'))} |")
            L.append("")
    L += ["## Как читать", "",
          "- Скрин находит КАНДИДАТОВ, не правила: признак, прошедший "
          "нуль в обеих полосах у обеих линеек, заслуживает своей "
          "объявленной оси с контролем случайной выборкой того же размера "
          "— и только после неё может стать правилом.",
          "- Признак, работающий на всех сделках и молчащий внутри полосы "
          "плеча ≥ 15×, есть переодетое плечо: хвост у него оттого, что "
          "пол ближе, а не оттого, что стакан что-то знал.",
          "- Веса модели видели эти часы; окно одно; хвостовых событий у "
          "оптимальной линейки больше, чем у безопасной, потому что её "
          "пол 0.50 ближе к входу — это свойство правила, а не рынка.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="портрет хвоста коротких книг")
    ap.add_argument("--perms", type=int, default=PERMS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    s = run(perms=a.perms)
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("портрет хвоста коротких книг: что общего у минусовых сделок")
    return 0


if __name__ == "__main__":
    sys.exit(main())
