#!/usr/bin/env python3
"""Рычаги коротких книг, которых стенд ещё не мерил: один скрин, оси до прогона.

Вопрос владельца 2026-10-03: «включай свои возможности на максимум и ищи
ещё варианты совершенствования стратегий». За три недели по коротким книгам
мерено: стоп по доле маржи, стоп по времени «не в плюсе», ранний тейк,
остаток к рынку, охрана рынком (стала правилом), возраст имени (правило),
пол капитуляции, билет, гейт плеча забора, отбор по ставке funding,
согласию рук, запасу до пола и тесноте. Не мерено — пять рычагов ниже;
каждый объявлен здесь, с порогами, ДО прогона, и судится своим контролем.

A. **Срок 12 / 18 ч вместо 24** — безусловный выход на отметке часа. Точно:
   отметка часа k ядра равна усечению срока в `at + k·3600 − 1` бит в бит
   (замер верности охраны, 13.09). Контроля случайной выборкой нет
   намеренно: срок — не отбор сделок, а другая книга; вопрос — зарабатывают
   ли последние часы срока. Судится по дням, без 3 лучших дней и по хвосту.
B. **Трейлинг от достигнутого**: взвод при +arm маржи, выход при откате на
   give долей маржи от пика. По ЧАСОВЫМ отметкам — внутри часа пути не
   видно, точный ответ дал бы реплей ядра с `trail`; это оговорка, не
   мелкий шрифт. Оси (0.25; 0.15) и (0.50; 0.25). Контроль — случайные
   выходы того же числа сделок в те же часы среди открытых (как у дороги).
C. **Пауза по имени после СВОЕГО выхода книги** (позиции, взятые кассой на
   $10k, как книга живёт): после пола/ликвидации 6 / 12 / 24 ч и после
   любого выхода 6 / 12 / 24 ч. Это отбор — режет сделки, — и судится
   против случайного удаления того же числа записей книги (200 зёрен).
D. **Одна рука**: только `nn`, только `gbm`. Отбор — тот же контроль.
E. **Вол-таргет книги**: билет × clip(σ_ref / σ_20, 0.5…1.5), σ_ref — σ дня
   первых 20 дней, σ_20 — прошлых 20 дней без заглядывания. ОЦЕНКА ПО
   ЖУРНАЛУ дней, не касса: допустима как скрин потому, что касса на билет
   0.5 ответила почти линейно (σ дня ×0.42, деньги ×0.5; 03.10). Любое
   решение по ней — только после кассы.

Исходы записей меняют лишь A и B (срез отметок ядра, издержки те же);
C и D — состав; E — масштаб. Деньги — касса семейства, $10k, нетто.
"""
import argparse
import collections
import os
import statistics
import subprocess
import sys
import time

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
import run_paper as RP                                        # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import entry_gate as E                                        # noqa: E402
import path_screen as P                                       # noqa: E402
import short_size as Z                                        # noqa: E402
import tail_screen as T                                       # noqa: E402
import wave as WV                                             # noqa: E402
import wave_guard as W                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-levers"
SEEDS = 200                       # объявлено до прогона
MAIN_DEP = 10000
HOUR = 3600.0
BOOK_KEYS = list(S.BOOKS)
TAIL_EXITS = T.TAIL_EXITS
# Оси — объявлены здесь, до прогона (ошибка R5 — выбрать ячейку после).
HOLD_H = (12, 18)
TRAILS = ((0.25, 0.15), (0.50, 0.25))          # (взвод, откат) долями маржи
COOL_H = (6, 12, 24)
COOL_KINDS = (("tail", "после пола/ликвидации"), ("any", "после любого выхода"))
ARMS = ("nn", "gbm")
VOL_REF_DAYS = 20
VOL_CLIP = (0.5, 1.5)
TRAIL_EXIT = "трейл (отметка)"


def closed_views(cache):
    """Закрытые записи линеек коротких книг с путём по отметкам — без рынка."""
    out = {}
    for key, r in cache.items():
        if key[0] not in T.RULERS or (r.get("state") or "closed") != "closed":
            continue
        out[key] = {"rec": r, "path": WV.path_of(r), "tail": T.is_tail(r),
                    "wave": {}, "resid": {}}
    return out


def hold_trigger(v, hours):
    """Безусловный срок: выход на отметке часа `hours`, если позиция ещё жива."""
    p = v["path"]
    if not p or p["K"] <= int(hours):
        return None
    return int(hours)


def trail_trigger(v, arm, give):
    """Трейлинг по отметкам: взвод при cum ≥ arm, выход при cum ≤ пик − give.

    Срабатывание СТРОГО до фактического выхода (час K — сам выход).
    """
    p = v["path"]
    if not p:
        return None
    cum, peak = p["cum"], None
    for k in range(1, p["K"]):
        c = cum.get(k)
        if c is None:
            continue
        if peak is None:
            if c >= arm:
                peak = c
            continue
        peak = max(peak, c)
        if c <= peak - give:
            return k
    return None


def apply_rule(cache, views, fn, why):
    """Кэш с выходами по правилу `fn(view) → час | None` и {ключ: час}."""
    changed = {}
    for key, v in views.items():
        k = fn(v)
        if k is not None:
            changed[key] = k
    mod = dict(cache)
    for key, k in changed.items():
        mod[key] = WV.guard_record(cache[key], k, why=why)
    return mod, changed


def ruled(packed, launch, now=None):
    """Записи под правилами книги — тем же порядком, что касса (`cell_stats`)."""
    out = {}
    quiet = lambda *a: None                                   # noqa: E731
    for bk, recs in packed.items():
        recs, _a = RP.age_shorts(recs, bk, launch=launch, log=quiet, now=now)
        recs, _g = RP.guard_shorts(recs, bk, log=quiet, now=now)
        out[bk] = recs
    return out


def taken_rows(ruled_packed, now=None, dep=MAIN_DEP):
    """Позиции, которые книги на $dep ВЗЯЛИ, по книгам — окна паузы берутся из них."""
    rows, _c, _o, _l = RP.build_rows(ruled_packed, now=now, keys=BOOK_KEYS,
                                     log=lambda *a: None)
    out = {bk: [] for bk in BOOK_KEYS}
    for r in rows:
        if int(r.get("dep", 0)) != int(dep):
            continue
        bk = R.ruler_of(r)
        if bk in out:
            out[bk].append(r)
    return out


def cooldown(recs, taken, hours, kind):
    """Записи вне окна паузы: имя закрыто `hours` часов после своего выхода.

    Окно — [выход, выход + hours): решение в секунду выхода уже под паузой.
    `kind` «tail» — только после пола/ликвидации, «any» — после любого.
    """
    win = collections.defaultdict(list)
    for r in taken:
        if kind == "tail" and (r.get("exit") or "") not in TAIL_EXITS:
            continue
        win[r["sym"]].append(float(r["exit_ts"]))
    span = float(hours) * HOUR
    keep, dropped = [], 0
    for r in recs:
        at = float(r["at"])
        if any(x <= at < x + span for x in win.get(r["sym"], ())):
            dropped += 1
            continue
        keep.append(r)
    return keep, dropped


def arm_map(legs_):
    """{(имя, момент): {руки}} из ног листа — у записи кэша руки нет."""
    m = {}
    for g in legs_:
        m.setdefault((g["sym"], round(float(g["at"]), 3)), set()).add(g.get("arm") or "gbm")
    return m


def arm_select(recs, amap, arm):
    """Записи, которые выбрала рука `arm` (обе руки — тоже); без ноги — не измерено."""
    keep, unknown = [], 0
    for r in recs:
        a = amap.get((r["sym"], round(float(r["at"]), 3)))
        if a is None:
            unknown += 1
            continue
        if arm in a:
            keep.append(r)
    return keep, unknown


def vol_target(days, ref_days=VOL_REF_DAYS, clip=VOL_CLIP):
    """Дни книги под вол-таргетом: множитель дня из σ ПРОШЛЫХ дней, без заглядывания.

    Первые `ref_days` дней идут как есть и дают σ_ref; дальше множитель
    clip(σ_ref / σ прошлых ref_days дней). Мало дней — не измерено (None).
    """
    rows = sorted(days or [], key=lambda d: d["d"])
    u = [float(d.get("usd") or 0.0) for d in rows]
    if len(u) <= int(ref_days):
        return None, None
    sref = statistics.pstdev(u[:ref_days])
    out, facs = [], []
    for i, x in enumerate(u):
        if i < ref_days:
            f = 1.0
        else:
            s = statistics.pstdev(u[i - ref_days:i])
            f = 1.0 if (s <= 0 or sref <= 0) else min(clip[1], max(clip[0], sref / s))
        facs.append(f)
        out.append({"d": rows[i]["d"], "usd": x * f})
    return out, facs


def summ(c):
    """Сводка ячейки кассы: деньги, форма дня, хвост."""
    sd, ratio = Z.day_sigma(c.get("days"))
    _t, wo, _top = W.wo3(c.get("days"))
    return {"n": c.get("n"), "final": c.get("final"), "max_dd": c.get("max_dd"),
            "usd": c.get("usd"), "wo3": wo, "sigma_day": sd, "ratio_day": ratio,
            "tails": W.tails_of(c), "days": c.get("days")}


def summ_days(days, dep, n=None):
    """Та же сводка из ряда дней (вол-таргет): просадка — формулой кассы."""
    if not days:
        return {"n": n, "final": None, "max_dd": None, "usd": None, "wo3": None,
                "sigma_day": None, "ratio_day": None, "tails": None, "days": None}
    v = [float(d["usd"]) for d in days]
    sd, ratio = Z.day_sigma(days)
    _t, wo, _top = W.wo3(days)
    return {"n": n, "final": round(sum(v) / float(dep), 4),
            "max_dd": round(RP._dd(v, dep), 4), "usd": round(sum(v), 2), "wo3": wo,
            "sigma_day": sd, "ratio_day": ratio, "tails": None, "days": days}


def verdict_sel(beat):
    """Фраза из числа: доля зёрен, где случайная выборка не хуже правила."""
    if not beat or beat.get("final") is None or beat.get("ratio") is None:
        return "не измерено"
    bf, br = float(beat["final"]), float(beat["ratio"])
    if bf <= 0.05 and br <= 0.05:
        return "лучше случайной"
    if bf >= 0.95 and br >= 0.95:
        return "хуже случайной"
    return "в шуме случайной"


def _beat(ctl_books, st, bk, dep):
    c = st.get(f"{bk}:{int(dep)}") or {}
    return {f: AG.beat_share(ctl_books.get(bk), c.get(f), f)[0] for f in ("final", "ratio")}


def run(seeds=SEEDS, log=print, now=None, launch=None, ctx=None, mem_limit=None,
        dep=MAIN_DEP, legs_=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    packed = AG.packed_short(cache)
    stats = lambda p: AG.stats_of(p, ctx, launch, BOOK_KEYS, deps=[dep], now=now)   # noqa: E731
    cell = lambda st, bk: summ(st.get(f"{bk}:{int(dep)}") or {})                    # noqa: E731
    base_st = stats(packed)
    base = {bk: cell(base_st, bk) for bk in BOOK_KEYS}
    views = closed_views(cache)
    no_marks = sum(1 for v in views.values() if v["path"] is None)
    log(f"записей {len(cache)}, закрытых {len(views)}, без отметок {no_marks}; "
        + ", ".join(f"{bk} сделок {base[bk]['n']}" for bk in BOOK_KEYS))
    idx = P.open_index(views)

    # A. срок
    hold = []
    for h in HOLD_H:
        mod, changed = apply_rule(cache, views, lambda v, h=h: hold_trigger(v, h),
                                  why=f"срок {h} ч")
        d = P.deltas(cache, views, changed)
        st = stats(AG.packed_short(mod)) if changed else {}
        books = {}
        for bk in BOOK_KEYS:
            c = cell(st, bk)
            c["days_diff"] = {k: v for k, v in W.day_diff(base[bk]["days"], c["days"]).items()
                              if k != "rows"}
            books[bk] = c
        log(f"A срок {h} ч: изменено {d['n']} (хвостовых {d['tails']}), Σ маржи {d['sum']:+.2f}")
        hold.append({"hours": h, "delta": d, "books": books})

    # B. трейлинг
    trail = []
    for arm, give in TRAILS:
        mod, changed = apply_rule(cache, views,
                                  lambda v, a=arm, g=give: trail_trigger(v, a, g),
                                  why=TRAIL_EXIT)
        d = P.deltas(cache, views, changed)
        log(f"B трейл {arm:g}/{give:g}: изменено {d['n']} (хвостовых {d['tails']}), "
            f"Σ маржи {d['sum']:+.2f}")
        row = {"arm": arm, "give": give, "delta": d, "books": {}, "beat_sum": None}
        if changed:
            st = stats(AG.packed_short(mod))
            ctl = P.control_exits(cache, views, changed, ctx, launch, seeds=seeds,
                                  dep=dep, now=now, log=log, idx=idx)
            for bk in BOOK_KEYS:
                c = cell(st, bk)
                c["beat"] = _beat(ctl["books"], st, bk, dep)
                c["verdict"] = verdict_sel(c["beat"])
                row["books"][bk] = c
            row["beat_sum"] = AG.beat_share([{"sum": x} for x in ctl["sum"]], d["sum"], "sum")[0]
            row["no_cand"] = ctl.get("no_cand")
        trail.append(row)

    # C. пауза по имени — окна из позиций, взятых кассой, как книга живёт
    taken = taken_rows(ruled(packed, launch, now=now), now=now, dep=dep)
    log("C позиций взято: " + ", ".join(f"{bk} {len(taken[bk])}" for bk in BOOK_KEYS))
    cool = []
    for kind, title in COOL_KINDS:
        for h in COOL_H:
            sub, sizes, dropped = {}, {}, {}
            for bk in BOOK_KEYS:
                sub[bk], dropped[bk] = cooldown(packed[bk], taken[bk], h, kind)
                sizes[bk] = len(sub[bk])
            st = stats(sub)
            ctl = E.control_rows(packed, sizes, ctx, launch, BOOK_KEYS, seeds=seeds,
                                 dep=dep, now=now, log=log)
            books = {}
            for bk in BOOK_KEYS:
                c = cell(st, bk)
                c["dropped"] = dropped[bk]
                c["beat"] = _beat(ctl, st, bk, dep)
                c["verdict"] = verdict_sel(c["beat"])
                books[bk] = c
            log(f"C пауза {title} {h} ч: убрано "
                + ", ".join(f"{bk} {dropped[bk]}" for bk in BOOK_KEYS))
            cool.append({"kind": kind, "title": title, "hours": h, "books": books})

    # D. одна рука
    legs_ = S.legs(log=log) if legs_ is None else legs_
    amap = arm_map(legs_)
    arms = []
    for arm in ARMS:
        sub, sizes, unknown = {}, {}, {}
        for bk in BOOK_KEYS:
            sub[bk], unknown[bk] = arm_select(packed[bk], amap, arm)
            sizes[bk] = len(sub[bk])
        st = stats(sub)
        ctl = E.control_rows(packed, sizes, ctx, launch, BOOK_KEYS, seeds=seeds,
                             dep=dep, now=now, log=log)
        books = {}
        for bk in BOOK_KEYS:
            c = cell(st, bk)
            c["kept"] = sizes[bk]
            c["unknown"] = unknown[bk]
            c["beat"] = _beat(ctl, st, bk, dep)
            c["verdict"] = verdict_sel(c["beat"])
            books[bk] = c
        log(f"D рука {arm}: записей " + ", ".join(f"{bk} {sizes[bk]}" for bk in BOOK_KEYS)
            + f"; без ноги {unknown[BOOK_KEYS[0]]}")
        arms.append({"arm": arm, "books": books})
    both = sum(1 for a in amap.values() if len(a) > 1)

    # E. вол-таргет — по журналу дней
    vol = {}
    for bk in BOOK_KEYS:
        days, facs = vol_target(base[bk]["days"])
        c = summ_days(days, dep, n=base[bk]["n"])
        c["factors"] = (None if not facs else
                        {"min": round(min(facs), 2), "med": round(statistics.median(facs), 2),
                         "max": round(max(facs), 2),
                         "n_scaled": sum(1 for f in facs if f != 1.0)})
        vol[bk] = c

    return {"dep": dep, "seeds": int(seeds), "books": BOOK_KEYS, "base": base,
            "hold": hold, "trail": trail, "cool": cool, "arms": arms, "vol": vol,
            "axes": {"hold_h": list(HOLD_H), "trails": [list(t) for t in TRAILS],
                     "cool_h": list(COOL_H), "vol_ref_days": VOL_REF_DAYS,
                     "vol_clip": list(VOL_CLIP)},
            "diag": {"records": len(cache), "closed": len(views), "no_marks": no_marks,
                     "legs": len(legs_), "both_arms": both},
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def halves(base_days, rule_days):
    """Разница «правило − опора» по половинам календаря дней.

    Единственная положительная ячейка скрина обязана стоять на обеих
    половинах окна, иначе это эпизод; мало дней — не измерено.
    """
    b = {d["d"]: float(d.get("usd") or 0.0) for d in (base_days or [])}
    r = {d["d"]: float(d.get("usd") or 0.0) for d in (rule_days or [])}
    ds = sorted(set(b) | set(r))
    if len(ds) < 4:
        return None
    mid = len(ds) // 2
    out = {}
    for name, part in (("first", ds[:mid]), ("second", ds[mid:])):
        diffs = [r.get(d, 0.0) - b.get(d, 0.0) for d in part]
        out[name] = {"days": len(part), "from": part[0], "to": part[-1],
                     "sum": round(sum(diffs), 2),
                     "better": sum(1 for x in diffs if x > 0),
                     "worse": sum(1 for x in diffs if x < 0)}
    return out


def hold_robust(cache, views, ctx, launch, deps, now=None, log=print):
    """Срок 12 / 18 ч на всех депозитах и по половинам окна — та же ячейка, не новая ось."""
    deps = [float(d) for d in deps]
    main = str(int(MAIN_DEP if MAIN_DEP in [int(d) for d in deps] else deps[0]))
    base_st = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS, deps=deps, now=now)
    base = {str(int(d)): {bk: summ(base_st.get(f"{bk}:{int(d)}") or {}) for bk in BOOK_KEYS}
            for d in deps}
    out = {"deps": [int(d) for d in deps], "main": main, "base": base, "hold": []}
    for h in HOLD_H:
        mod, changed = apply_rule(cache, views, lambda v, h=h: hold_trigger(v, h),
                                  why=f"срок {h} ч")
        d = P.deltas(cache, views, changed)
        st = AG.stats_of(AG.packed_short(mod), ctx, launch, BOOK_KEYS, deps=deps, now=now)
        by = {str(int(dp)): {bk: summ(st.get(f"{bk}:{int(dp)}") or {}) for bk in BOOK_KEYS}
              for dp in deps}
        hv = {bk: halves(base[main][bk]["days"], by[main][bk]["days"]) for bk in BOOK_KEYS}
        log(f"A срок {h} ч: изменено {d['n']}, Σ маржи {d['sum']:+.2f}; "
            + ", ".join(f"{bk} ${int(dp):,} {_pp(by[str(int(dp))][bk]['final'])}"
                        for dp in deps for bk in BOOK_KEYS))
        out["hold"].append({"hours": h, "delta": d, "by_dep": by, "halves": hv})
    return out


def run_hold(log=print, now=None, launch=None, ctx=None, mem_limit=None, deps=None):
    """Только ось срока — устойчивость единственной положительной ячейки скрина."""
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    views = closed_views(cache)
    s = hold_robust(cache, views, ctx, launch, deps or R.DEPOSITS, now=now, log=log)
    s.update({"books": BOOK_KEYS, "axes": {"hold_h": list(HOLD_H)},
              "diag": {"records": len(cache), "closed": len(views)},
              "costs_error": (ctx or {}).get("error"),
              "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)})
    return s


# ---------------------------------------------------------------- отчёт

def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _sd(x):
    return "—" if x is None else f"{float(x):.0f} $"


def _i(x):
    return "—" if x is None else str(x)


def _dsig(c, b):
    """σ дня против опоры, в процентах — число, из которого читается стабильность."""
    if c.get("sigma_day") is None or not b.get("sigma_day"):
        return "—"
    return f"{100.0 * (float(c['sigma_day']) / float(b['sigma_day']) - 1.0):+.0f} %"


CELL_HEAD = "сделок | итог | просадка | $ без 3 лучших дней | σ дня | Δσ | день/σ | хвостовых"
CELL_SEP = "--:|--:|--:|--:|--:|--:|--:|--:"


def _cells(c, b):
    return (f"{_i(c.get('n'))} | {_pp(c.get('final'))} | {_pp(c.get('max_dd'))} | "
            f"{_usd(c.get('wo3'))} | {_sd(c.get('sigma_day'))} | {_dsig(c, b)} | "
            f"{_f(c.get('ratio_day'))} | {_i(c.get('tails'))}")


def _ctl(c):
    b = c.get("beat") or {}
    return f"{_pp(b.get('final'), 0)} / {_pp(b.get('ratio'), 0)} | {c.get('verdict', '—')}"


def report(s):
    L = ["# Рычаги коротких книг: срок, трейлинг, пауза по имени, одна рука, вол-таргет", "",
         "Вопрос владельца 2026-10-03: «ищи ещё варианты совершенствования стратегий». "
         "Пять рычагов, которых стенд по коротким книгам ещё не мерил; оси и пороги "
         "объявлены в коде до прогона. Деньги — касса семейства на записях кэша, "
         f"${int(s.get('dep') or MAIN_DEP):,}, нетто. Отбор (пауза, рука) судится против "
         f"случайного удаления того же числа записей книги ({s.get('seeds') or SEEDS} зёрен); "
         "трейлинг — против случайных выходов того же числа сделок в те же часы; срок — по "
         "дням (это другая книга, не отбор); вол-таргет — оценка по журналу дней, "
         "решения по ней не принимаются без кассы.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой части.", ""]
    dg = s.get("diag") or {}
    L += [f"Записей {_i(dg.get('records'))}, закрытых {_i(dg.get('closed'))}, без отметок "
          f"{_i(dg.get('no_marks'))}; ног листа {_i(dg.get('legs'))}, решений обеих рук "
          f"{_i(dg.get('both_arms'))}.", ""]
    base = s.get("base") or {}
    books = s.get("books") or BOOK_KEYS
    L += ["## Опора — книги как сейчас", "",
          f"| книга | {CELL_HEAD} |", f"|---|{CELL_SEP}|"]
    for bk in books:
        b = base.get(bk) or {}
        L.append(f"| {R.ruler_title(bk)} | {_cells(b, b)} |")
    L.append("")

    L += ["## A. Срок 12 / 18 ч вместо 24", "",
          "Безусловный выход на отметке часа; позиции, вышедшие раньше (цель, пол, "
          "ликвидация, охрана), не меняются. Σ маржи — сумма приращений pnl изменённых "
          "записей: знак говорит, зарабатывают ли последние часы срока.", ""]
    for h in s.get("hold") or []:
        d = h.get("delta") or {}
        L.append(f"**Срок {h['hours']} ч:** изменено {_i(d.get('n'))} сделок (хвостовых "
                 f"{_i(d.get('tails'))}), Σ долей маржи {_f(d.get('sum'), 2)} — последние часы "
                 f"{'зарабатывают' if float(d.get('sum') or 0) < 0 else 'теряют'} "
                 "(при выходе раньше книга их теряет/избегает).")
    L += ["", f"| книга | срок | {CELL_HEAD} | дней лучше / хуже | разница |",
          f"|---|---|{CELL_SEP}|--:|--:|"]
    for h in s.get("hold") or []:
        for bk in books:
            c = (h.get("books") or {}).get(bk) or {}
            dd = c.get("days_diff") or {}
            L.append(f"| {R.ruler_title(bk)} | {h['hours']} ч | {_cells(c, base.get(bk) or {})} | "
                     f"{_i(dd.get('better'))} / {_i(dd.get('worse'))} | {_usd(dd.get('sum_diff'))} |")
    L.append("")

    L += ["## B. Трейлинг от достигнутого — по часовым отметкам", "",
          "Взвод при +arm маржи, выход при откате на give от пика. Внутри часа пути не "
          "видно — это приближение; точный ответ даст реплей ядра с `trail`, если здесь "
          "будет за что платить.", "",
          f"| книга | взвод / откат | {CELL_HEAD} | случайная не хуже: итог / доход-просадка | вывод |",
          f"|---|---|{CELL_SEP}|--:|---|"]
    for t in s.get("trail") or []:
        d = t.get("delta") or {}
        for bk in books:
            c = (t.get("books") or {}).get(bk) or {}
            L.append(f"| {R.ruler_title(bk)} | {t['arm']:g} / {t['give']:g} | "
                     f"{_cells(c, base.get(bk) or {})} | {_ctl(c)} |")
        L.append(f"| *изменено* | {t['arm']:g} / {t['give']:g} | {_i(d.get('n'))} сделок, хвостовых "
                 f"{_i(d.get('tails'))}, Σ маржи {_f(d.get('sum'), 2)}; случайные выходы не хуже по Σ "
                 f"в {_pp(t.get('beat_sum'), 0)} зёрен | | | | | | | | |")
    L.append("")

    L += ["## C. Пауза по имени после своего выхода", "",
          "Окна — из позиций, которые книга на этом депозите взяла; запись под паузой не "
          "торгуется. Это отбор: правило обязано удержать деньги и срезать σ дня там, где "
          "случайное удаление того же числа записей их уносит.", "",
          f"| книга | правило | убрано | {CELL_HEAD} | случайная не хуже: итог / доход-просадка | вывод |",
          f"|---|---|--:|{CELL_SEP}|--:|---|"]
    for cc in s.get("cool") or []:
        for bk in books:
            c = (cc.get("books") or {}).get(bk) or {}
            L.append(f"| {R.ruler_title(bk)} | {cc['title']} {cc['hours']} ч | {_i(c.get('dropped'))} | "
                     f"{_cells(c, base.get(bk) or {})} | {_ctl(c)} |")
    L.append("")

    L += ["## D. Одна рука", "",
          "Запись взята, если её выбрала эта рука (решения обеих рук входят в обе ячейки); "
          "запись без ноги в листе — не измерена и убрана из обеих.", "",
          f"| книга | рука | записей | без ноги | {CELL_HEAD} | случайная не хуже: итог / доход-просадка | вывод |",
          f"|---|---|--:|--:|{CELL_SEP}|--:|---|"]
    for a in s.get("arms") or []:
        for bk in books:
            c = (a.get("books") or {}).get(bk) or {}
            L.append(f"| {R.ruler_title(bk)} | {a['arm']} | {_i(c.get('kept'))} | {_i(c.get('unknown'))} | "
                     f"{_cells(c, base.get(bk) or {})} | {_ctl(c)} |")
    L.append("")

    ax = s.get("axes") or {}
    L += ["## E. Вол-таргет книги — оценка по журналу дней", "",
          f"Множитель дня = clip(σ_ref / σ прошлых {ax.get('vol_ref_days', VOL_REF_DAYS)} дней, "
          f"{ax.get('vol_clip', list(VOL_CLIP))[0]:g}…{ax.get('vol_clip', list(VOL_CLIP))[1]:g}); "
          "первые дни идут как есть. Касса не считалась — слоты и очередь денег при "
          "переменном билете здесь не видны; это направление, не решение.", "",
          f"| книга | {CELL_HEAD} | множитель мин / мед / макс | дней с множителем |",
          f"|---|{CELL_SEP}|---|--:|"]
    for bk in books:
        c = (s.get("vol") or {}).get(bk) or {}
        f = c.get("factors") or {}
        L.append(f"| {R.ruler_title(bk)} | {_cells(c, base.get(bk) or {})} | "
                 f"{_f(f.get('min'))} / {_f(f.get('med'))} / {_f(f.get('max'))} | "
                 f"{_i(f.get('n_scaled'))} |")
    L += ["", "## Как читать", "",
          "- Стабильность читается по σ дня (Δσ против опоры) и хвостовым выходам при "
          "удержанных деньгах без 3 лучших дней; доход сам по себе рычагом не считается.",
          "- «Лучше случайной» — случайная выборка того же размера не хуже правила не более "
          "чем в 5 % зёрен по итогу И по доходу/просадке; «в шуме» — всё остальное.",
          "- Срок и трейлинг меняют исход записей по отметкам ядра (отметка часа = усечение "
          "срока бит в бит); трейлинг внутри часа не виден — оговорка названа.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def report_hold(s):
    L = ["# Срок 12 / 18 ч у коротких книг: устойчивость по депозитам и половинам окна", "",
         "Проверка единственной ячейки скрина рычагов (`DCA-short-levers`), где касса "
         "на $10k дала больше денег при меньшей σ дня у оптимальной и агрессивной книги. "
         "Это та же объявленная ось (12 / 18 ч), не новый порог: вопрос — стоит ли "
         "ячейка на всех депозитах и на обеих половинах календаря, или это эпизод. "
         "Деньги нетто, касса семейства.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой части.", ""]
    books = s.get("books") or BOOK_KEYS
    base = s.get("base") or {}
    L += [f"| книга | депозит | срок | {CELL_HEAD} |", f"|---|--:|---|{CELL_SEP}|"]
    for dp in s.get("deps") or []:
        k = str(int(dp))
        for bk in books:
            b = (base.get(k) or {}).get(bk) or {}
            L.append(f"| {R.ruler_title(bk)} | ${int(dp):,} | 24 ч (опора) | {_cells(b, b)} |")
            for h in s.get("hold") or []:
                c = ((h.get("by_dep") or {}).get(k) or {}).get(bk) or {}
                L.append(f"| {R.ruler_title(bk)} | ${int(dp):,} | {h['hours']} ч | {_cells(c, b)} |")
    main = s.get("main") or str(MAIN_DEP)
    L += ["", f"## По половинам окна, ${int(main):,}", "",
          "Разница «срок − опора» по дням: первая половина календаря и вторая. Ячейка, "
          "стоящая на одной половине, — эпизод.", "",
          "| книга | срок | 1-я половина | дней лучше / хуже | разница | 2-я половина | "
          "дней лучше / хуже | разница |", "|---|---|---|--:|--:|---|--:|--:|"]
    for h in s.get("hold") or []:
        for bk in books:
            hv = (h.get("halves") or {}).get(bk) or {}
            f, g = hv.get("first") or {}, hv.get("second") or {}
            L.append(f"| {R.ruler_title(bk)} | {h['hours']} ч | {f.get('from', '—')} … {f.get('to', '—')} | "
                     f"{_i(f.get('better'))} / {_i(f.get('worse'))} | {_usd(f.get('sum'))} | "
                     f"{g.get('from', '—')} … {g.get('to', '—')} | {_i(g.get('better'))} / "
                     f"{_i(g.get('worse'))} | {_usd(g.get('sum'))} |")
    L += ["", "## Как читать", "",
          "- Срок — не отбор, контроля случайной выборкой нет; судится по депозитам, "
          "половинам окна, σ дня и деньгам без 3 лучших дней.",
          "- Знак разницы, разный на половинах или на депозитах, — эпизод, не правило.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--hold-only", action="store_true",
                    help="только ось срока: депозиты и половины окна (артефакт -hold)")
    a = ap.parse_args(argv)
    if a.hold_only:
        s = run_hold(log=print)
        if s.get("error"):
            print(s["error"])
        G.write(s, ART + "-hold", report_hold, log=print)
        if not a.no_publish:
            publish("срок 12/18 ч у коротких книг: депозиты и половины окна")
        return
    s = run(seeds=a.seeds, log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("рычаги коротких книг: срок, трейлинг, пауза по имени, рука, вол-таргет")


if __name__ == "__main__":
    main()
