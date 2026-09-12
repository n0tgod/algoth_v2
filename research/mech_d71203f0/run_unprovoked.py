#!/usr/bin/env python3
"""
Механика d71203f0 — прогон по записи B1. Потолок заявки, не вердикт.

Что делает
----------

Один проход по суткам записи. За каждые сутки:

1. читает принты `allLiquidation` всех имён (`probe_liqsplit.liq_of_day`)
   и склеивает принты одного имени в пределах 60 с в ОДНО событие;
2. считает тишину шести окон по σ **прошлых** суток — своей и
   кросс-секционной (`unprovoked.scan_day`);
3. калибрует метку стороны по падениям на 3 % (та же конструкция, что у
   LIQSPLIT: в падениях ликвидируют лонгов, доминирующая там метка и есть
   наша);
4. меряет превышение над одновременной кросс-секцией (`detect.excess`) на
   горизонтах 5 / 15 / 30 минут;
5. считает нуль «случайная секунда того же имени и того же часа».

Первые сутки прогона идут ТОЛЬКО на σ: судить по ним нечем, и события с
них не берутся вовсе. Сутки, в которые лента ликвидаций молчала целиком,
событий не дают и считаются отдельным числом — но цены их прочитаны, и σ
следующим суткам они отдают: отказ подписки не должен заодно выбрасывать
исправную запись книги.

Память
------

Прогон идёт РЯДОМ со сборщиком на машине в 7.7 ГБ без свопа, и ядро уже
убивало не прогон, а часовой цикл. Поэтому память проверяется ДО счёта по
составу (`run_d1.mem_need_mb`), а во время счёта прогон сторожит себя сам
тем же `run_d10.mem_guard`, которым сторожат длинные прогоны DCA: вырос
выше объявленного — снялся сам, вслух и с числом.

    .venv/bin/python research/mech_d71203f0/run_unprovoked.py --days 3
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
for _p in (HERE, os.path.join(RESEARCH, "d1_seconds"),
           os.path.join(RESEARCH, "b1_book"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "probe_liqsplit"),
           os.path.join(RESEARCH, "dca_ladder")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import detect as D                                          # noqa: E402
import run_d1 as R                                          # noqa: E402
import liqsplit as LQ                                       # noqa: E402
import run_d10 as D10                                       # noqa: E402
import unprovoked as U                                      # noqa: E402

# Модуль под знакомым именем уже подменялся в этом проекте (F3), и
# совпади имена функций, подмену нельзя было бы заметить. Сверка — одной
# функцией на все дороги (`unprovoked.check_origin`), а не повторённым
# здесь условием: копия проверки однажды разошлась бы с оригиналом.
for _m, _want in ((D, "d1_seconds"), (R, "d1_seconds"),
                  (LQ, "probe_liqsplit"), (D10, "dca_ladder")):
    U.check_origin(_m, _want)

# Запас к объявленной потребности: сторож ловит РОСТ сверх состава, а не
# сам состав. Ниже потребности предел означал бы прогон, который всегда
# снимает себя сам, — отказ, неотличимый от поломки.
MEM_SLACK = 1.3

# Круг издержек берётся ИЗМЕРЕННЫЙ по нашей же записи (комиссия плюс
# половина спреда на входе и половина на выходе) — тем же кодом, которым
# его читает D1. Порог убийцы 2 объявлен заданием числом 17.4; измеренный
# круг печатается рядом, и расхождение видно, а не замазано.
COST_ROUND_BP, COST_SRC = R.cost_round(
    os.path.join(RESEARCH, "d1_seconds", "out"), "1m")


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ----------------------------------------------------------------------
# Принты суток
# ----------------------------------------------------------------------

def prints_of_day(root, syms, hours, t0, lo, hi):
    """Принты всех имён за сутки и события после склейки 60 с.

    Возвращает `(по строкам сырые принты, события)`. Событие — кортеж
    `(строка, секунда сетки, метка стороны, нотионал, число принтов)`.
    Секунда события — секунда ПЕРВОГО принта кластера: он и есть момент,
    когда решение стало возможно.
    """
    raw, events = {}, []
    for r, sym in enumerate(syms):
        lt, lu, lb = LQ.liq_of_day(root, sym, hours)
        if len(lt) == 0:
            continue
        raw[r] = (lt, lu, lb)
        jj = np.floor(lt).astype(np.int64) - int(t0)
        inside = (jj >= int(lo)) & (jj < int(hi))
        if not inside.any():
            continue
        for mark, m in (("Buy", lb == 1), ("Sell", lb == 0)):
            sel = inside & m
            if not sel.any():
                continue
            for t, usd, n in U.glue_prints(lt[sel], lu[sel]):
                events.append((r, int(np.floor(t)) - int(t0), mark,
                               float(usd), int(n)))
    events.sort(key=lambda e: (e[1], e[0]))
    return raw, events


def calibrate_day(P, t0, raw, drop_seen, lo, hi, log=print):
    """Стороны принтов в окнах падений на 3 %: `(Sell, Buy)` числом.

    Конструкция дословно LIQSPLIT: событие — падение середины на 3 % за
    15 минут, окно принтов = окно обнаружения. В падениях ликвидируют
    ЛОНГОВ, значит доминирующая там метка и означает «лонг закрыт».
    Семантику поля решают данные: моё чтение «ликвидация лонга идёт как
    Sell» уже было опровергнуто первым же прогоном зонда.
    """
    rows, cols = R.events_of_day(P, t0, U.DROP, drop_seen, int(lo), int(hi))
    n_sell = n_buy = 0
    for r, j in zip(rows, cols):
        got = raw.get(int(r))
        if got is None:
            continue
        lt, _lu, lb = got
        a = float(t0 + int(j) - D.W_SEC)
        b = float(t0 + int(j))
        i0 = int(np.searchsorted(lt, a, side="left"))
        i1 = int(np.searchsorted(lt, b, side="right"))
        if i1 <= i0:
            continue
        n_buy += int(lb[i0:i1].sum())
        n_sell += int(i1 - i0 - lb[i0:i1].sum())
    log(f"    падений 3 %: {len(rows)}, принтов в их окнах "
        f"{n_sell + n_buy} (Sell {n_sell}, Buy {n_buy})")
    return n_sell, n_buy


def null_second(seed, row, j, t0, lo, hi):
    """Случайная секунда ТОГО ЖЕ имени и ТОГО ЖЕ часа. `-1` — нет такой.

    Зерно выводится из `(зерно, строка, секунда)`, а не из счётчика:
    нуль, зависящий от порядка событий, нельзя повторить на другом
    разрезе суток, а непроверяемый нуль ничего не доказывает (дефект R3).
    """
    t = float(t0) + float(j)
    hour_lo = int(np.floor(t / 3600.0) * 3600.0) - int(t0)
    a = max(int(hour_lo), int(lo))
    b = min(int(hour_lo) + 3600, int(hi))
    if b - a < 2:
        return -1
    rng = np.random.default_rng([int(seed), int(row), int(j)])
    return int(rng.integers(a, b))


# ----------------------------------------------------------------------
# Сутки целиком
# ----------------------------------------------------------------------

def measure_day(root, syms, day, jobs, state, log=print, mem_limit=None):
    """Сутки: события, тишина, превышение, нуль.

    Возвращает `(записи, жива ли лента ликвидаций)`. `state` переживает
    сутки и несёт σ ПРОШЛЫХ суток, счётчики калибровки и память о
    падениях (`drop_seen`). Через него же уходит σ нынешних суток —
    следующим суткам, а не этим.
    """
    book = os.path.join(root, "book")
    P, t0, n = R.load_day(book, syms, day, jobs, log)
    lo, hi = R.PAD_SEC, R.PAD_SEC + R.DAY_SEC
    hours = R.hours_of(t0, n)
    D10.mem_guard(f"{day}: матрица цен", log, mem_limit)

    alive = LQ.liq_day_alive(root, day)
    raw, events = prints_of_day(root, syms, hours, t0, lo, hi)
    if not alive:
        log(f"    {day}: лента ликвидаций молчит ЦЕЛИКОМ — событий с "
            f"этих суток нет, но цены прочитаны и σ следующим суткам "
            f"они дают")
        events = []
    log(f"    принтов у {len(raw)} имён, событий после склейки "
        f"{U.GLUE_SEC} с: {len(events)}")

    # Калибровка стороны считается ВСЕГДА, в том числе на первых сутках и
    # на сутках с молчащей лентой: она про семантику поля площадки, а не
    # про доходность.
    n_sell, n_buy = calibrate_day(P, t0, raw, state.setdefault(
        "drop_seen", {}), lo, hi, log)
    state["n_sell"] = state.get("n_sell", 0) + n_sell
    state["n_buy"] = state.get("n_buy", 0) + n_buy
    state.setdefault("calib_days", []).append(
        {"day": day, "sell": n_sell, "buy": n_buy})

    ev_by_row = {}
    for r, j, _mark, _usd, _n in events:
        ev_by_row.setdefault(int(r), []).append(int(j))
    sc = U.scan_day(P, lo, hi, ev_by_row, log=log)
    D10.mem_guard(f"{day}: тишина посчитана", log, mem_limit)

    sig_own_prev = state.get("sigma_own")
    sig_cross_prev = state.get("sigma_cross")
    # σ НЫНЕШНИХ суток уходит следующим суткам. Ключ — имя, а не номер
    # строки: состав записи растёт ступенями (25 → 518 → 559 → 725), и
    # номер строки на соседних сутках означал бы другое имя.
    state["sigma_own"] = {syms[r]: v for r, v in sc["sigma_own"].items()}
    state["sigma_cross"] = sc["sigma_cross"]

    if not events:
        del P
        return [], alive
    if sig_own_prev is None or sig_cross_prev is None:
        log(f"    {day}: σ прошлых суток нет — эти сутки идут ТОЛЬКО на σ, "
            f"событий с них не берём")
        del P
        return [], alive

    recs = []
    for r, j, mark, usd, npr in events:
        own = sc["moves"].get(int(r), {}).get(int(j))
        cx = U.cross_at(sc["cross_med"], int(j))
        so = sig_own_prev.get(syms[int(r)])
        rec = {"sym": syms[int(r)], "row": int(r), "t": float(t0 + int(j)),
               "j": int(j), "day": day, "side": mark, "usd": float(usd),
               "n_prints": int(npr),
               "mv": {int(w): (None if own is None else own.get(int(w)))
                      for w in U.WINDOWS_SEC},
               "cx": {int(w): cx.get(int(w)) for w in U.WINDOWS_SEC},
               "quiet": U.quiet_of(own, cx, so, sig_cross_prev,
                                   k=U.K_SIGMA),
               "quiet2": U.quiet_of(own, cx, so, sig_cross_prev,
                                    k=U.K_SIGMA_DIAG)}
        recs.append(rec)

    NXT = R.next_index(P)
    D10.mem_guard(f"{day}: индекс следующей цены", log, mem_limit)
    rows_a = np.array([e["row"] for e in recs], dtype=np.int64)
    cols_a = np.array([e["j"] for e in recs], dtype=np.int64)
    for hor in sorted({U.HORIZON_SEC, *U.DIAG_HORIZONS},
                      key=lambda h: D.guard_sec(U.ENTRY_SEC, h)):
        g = D.guard_sec(U.ENTRY_SEC, hor)
        ban = D.guard_matrix(P.shape, rows_a, cols_a, g)
        log(f"    удержание {hor // 60} мин: защитное окно {g} с")
        suf = "" if hor == U.HORIZON_SEC else f"_h{hor // 60}"
        for e in recs:
            own_r, _bg, exc, width = D.excess(
                P, NXT, e["row"], e["j"], U.ENTRY_SEC, hor, ban[:, e["j"]])
            e["own" + suf] = own_r
            e["exc" + suf] = exc
            e["width" + suf] = int(width)
        if hor == U.HORIZON_SEC:
            for e in recs:
                if e["quiet"] is not True:
                    continue
                vals = []
                for s in range(U.NULL_SEEDS):
                    jn = null_second(U.NULL_SEED0 + s, e["row"], e["j"],
                                     t0, lo, hi)
                    if jn < 0:
                        vals.append(float("nan"))
                        continue
                    _o, _b, xc, _w = D.excess(P, NXT, e["row"], jn,
                                              U.ENTRY_SEC, hor, ban[:, jn])
                    vals.append(xc)
                e["null"] = vals
        del ban
        D10.mem_guard(f"{day}: удержание {hor // 60} мин", log, mem_limit)
    del P, NXT
    return recs, alive


# ----------------------------------------------------------------------
# Сводка
# ----------------------------------------------------------------------

def live_daily(path):
    """Дневные деньги живых кандидатов пула. Нет файла — пустой словарь."""
    if not path or not os.path.exists(path):
        return {}
    try:
        art = json.load(open(path, encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    out = {}
    for cid, rec in (art.get("candidates") or {}).items():
        d = rec.get("daily") or {}
        if d:
            out[cid] = {int(k): float(v) for k, v in d.items()}
    return out


def summarise(rows, live_days, dead_days, state, live_path, sigma_only=1):
    """Все числа отчёта. Порядок — от самого дешёвого убийцы к прочим."""
    mark, why = U.long_mark(state.get("n_sell", 0), state.get("n_buy", 0))
    other = U.other_side(mark)
    main = [e for e in rows if e["side"] == mark] if mark else []
    unp = [e for e in main if e["quiet"] is True]
    prov = [e for e in main if e["quiet"] is False]
    unknown = [e for e in main if e["quiet"] is None]

    per_day = {d: 0 for d in live_days}
    for e in unp:
        if e["day"] in per_day:
            per_day[e["day"]] += 1
    med = (float(np.median(list(per_day.values()))) if per_day else None)

    hor_keys = ["exc"] + [f"exc_h{h // 60}" for h in U.DIAG_HORIZONS]
    daily = U.daily_series(unp, COST_ROUND_BP)
    corr, who, cdays = U.live_corr(daily, live_daily(live_path))
    nb, best_name = U.drop_best_name(unp)
    nd, best_days = U.drop_best_days(unp)

    art = {
        "prints": int(sum(e["n_prints"] for e in rows)),
        "events_glued": len(rows),
        "long_mark": mark, "long_mark_why": why,
        "calib_sell": int(state.get("n_sell", 0)),
        "calib_buy": int(state.get("n_buy", 0)),
        "events_side": len(main),
        "events_unprovoked": len(unp),
        "events_provoked": len(prov),
        "events_unclassified": len(unknown),
        "events_per_day": {d: per_day[d] for d in sorted(per_day)},
        "events_per_day_median": med,
        "days_live": len(live_days), "dead_days": int(dead_days),
        "days_sigma_only": int(sigma_only),
        "cost_round_bp": round(COST_ROUND_BP, 2), "cost_src": COST_SRC,
        "horizons": [U.HORIZON_SEC] + list(U.DIAG_HORIZONS),
        "split": U.split_by_quiet(main),
        "ceiling_bp": U.ceiling_bp(unp, hor_keys),
        "null": U.null_stats(unp),
        "no_best_name": nb, "best_name": best_name,
        "no_best_days": nd, "best_days": best_days,
        "terciles": U.terciles(unp),
        "form": U.form_stats(daily),
        "daily": {str(k): v for k, v in sorted(daily.items())},
        "live_corr": None if corr is None else round(corr, 3),
        "live_corr_with": who, "live_corr_days": int(cdays),
        "diagnostics": diagnostics(rows, main, mark, other, state),
        "thresholds": {
            "windows_sec": list(U.WINDOWS_SEC), "k_sigma": U.K_SIGMA,
            "glue_sec": U.GLUE_SEC, "entry_sec": U.ENTRY_SEC,
            "horizon_sec": U.HORIZON_SEC, "need_mean_bp": U.NEED_MEAN_BP,
            "need_gross_bp": U.NEED_GROSS_BP,
            "min_events_per_day": U.MIN_EVENTS_PER_DAY,
            "null_seeds": U.NULL_SEEDS, "null_seed0": U.NULL_SEED0,
            "min_sigma_pts": U.MIN_SIGMA_PTS,
            "cross_step_sec": U.CROSS_STEP_SEC},
    }
    art["killers"] = U.killers(art)
    art["reading"] = U.reading(art)
    return art


def diagnostics(rows, main, mark, other, state):
    """Ячейки, которые считаются рядом и предъявлять которые запрещено."""
    out = {}
    for h in U.DIAG_HORIZONS:
        out[f"удержание {h // 60} мин"] = U.split_by_quiet(
            main, key=f"exc_h{h // 60}")
    out[f"порог тишины {U.K_SIGMA_DIAG:.0f}σ"] = U.split_by_quiet(
        main, flag="quiet2")
    if other:
        out[f"вторая сторона ({other}): {U.SIDE_TITLE['short']}"] = \
            U.split_by_quiet([e for e in rows if e["side"] == other])
    days = sorted({e["day"] for e in main})
    if days:
        cut = days[len(days) // 2]
        out["первая половина записи"] = U.split_by_quiet(
            [e for e in main if e["day"] < cut])
        out["вторая половина записи"] = U.split_by_quiet(
            [e for e in main if e["day"] >= cut])
    # Устойчивость самой КАЛИБРОВКИ: разойдись половины записи, верить
    # нельзя ни одной, и вся ячейка считалась бы перевёрнутым знаком.
    cal = state.get("calib_days") or []
    if len(cal) >= 2:
        half = len(cal) // 2
        halves = {}
        for name, part in (("первая половина", cal[:half]),
                           ("вторая половина", cal[half:])):
            s = sum(x["sell"] for x in part)
            b = sum(x["buy"] for x in part)
            m, w = U.long_mark(s, b)
            halves[name] = {"events": s + b, "episodes": 0,
                            "mean_bp": None, "median_bp": None,
                            "share_pos": (round(s / (s + b), 3)
                                          if (s + b) else None),
                            "names": 0, "mark": m, "why": w}
        out["калибровка стороны по половинам записи "
            "(доля Sell — в колонке «доля > 0»)"] = halves
    return out


# ----------------------------------------------------------------------
# Прогон
# ----------------------------------------------------------------------

def write_status(out, tag, status):
    """Состояние прогона отдельным файлом, атомарно, после КАЖДЫХ суток.

    Прогон, убитый ядром по памяти, не пишет ничего, и снаружи это
    неотличимо от «забыли запустить». Ответ обязан давать файл, а не
    переписка.
    """
    p = os.path.join(out, f"MECH-unprov-status-{tag}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


_LAST = {}


def main():
    """Точка входа. Падение обязано САМО СЕБЯ доложить."""
    try:
        return _run()
    except SystemExit:
        raise
    except BaseException as e:                              # noqa: BLE001
        import traceback
        out, tag = _LAST.get("out"), _LAST.get("tag")
        if out and tag:
            st = _LAST.get("status") or {}
            st["state"] = "УПАЛ"
            st["error"] = f"{type(e).__name__}: {e}"
            st["traceback"] = traceback.format_exc()[-2000:]
            write_status(out, tag, st)
            print(f"ПРОГОН УПАЛ: {type(e).__name__}: {e}")
            if not _LAST.get("no_publish"):
                R.publish(f"механика d71203f0: прогон упал ({tag})")
        raise


def _run():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--mem-share", type=float, default=0.6)
    ap.add_argument("--live", default=os.path.join(
        RESEARCH, "factory", "out", "factory-day-1m.json"))
    a = ap.parse_args()
    # Частичный прогон не занимает имя полного: смоук под именем
    # настоящего прогона в этом проекте уже подменял артефакт (F2).
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"
    # Каталог создаётся ДО счёта: прогон турнира однажды досчитал всё и
    # упал на записи в несуществующий каталог.
    os.makedirs(a.out, exist_ok=True)
    _LAST.update({"out": a.out, "tag": a.tag, "no_publish": a.no_publish})

    syms, hours = R.available(os.path.join(a.root, "book"))
    if a.symbols:
        want = set(a.symbols.split(","))
        syms = [s for s in syms if s in want]
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    log_(f"символов {len(syms)}, суток {len(days)}: {days[0]} … {days[-1]}")
    if len(days) < 2:
        raise SystemExit(
            f"ОТКАЗ: суток {len(days)}, а нужно не меньше двух. σ тишины "
            f"берётся у ПРОШЛЫХ суток, и на одних сутках её взять "
            f"неоткуда — это не «эффекта нет», это нечем мерить.")

    # Память проверяется ДО счёта: рядом идёт запись стакана —
    # единственное необратимое в проекте, и прибитый ядром сборщик стоит
    # суток, которые неоткуда докачать.
    need = R.mem_need_mb(len(syms), R.DAY_SEC + 2 * R.PAD_SEC)
    have = R.mem_available_mb()
    log_(f"память: нужно ~{need:.0f} МБ на сутки, доступно "
         f"{'неизвестно' if have is None else f'{have:.0f} МБ'}")
    if have is not None and need > have * a.mem_share:
        fits = int(len(syms) * have * a.mem_share / max(need, 1e-9))
        raise SystemExit(
            f"ОТКАЗ: на сутки нужно ~{need:.0f} МБ, а свободно "
            f"{have:.0f} МБ (порог {a.mem_share:.0%}). Влезет около "
            f"{fits} символов: сузьте --symbols либо освободите память.")
    mem_limit = max(D10.MEM_LIMIT_MB, int(need * MEM_SLACK))
    log_(f"сторож памяти: предел {mem_limit} МБ "
         f"(объявленная потребность {need:.0f} × {MEM_SLACK})")

    rows, state = [], {}
    live_days, dead = [], 0
    t_start = time.time()
    status = {"state": "идёт", "tag": a.tag, "symbols": len(syms),
              "days_planned": len(days), "day_from": days[0],
              "day_to": days[-1], "mem_need_mb": need,
              "mem_limit_mb": mem_limit, "days_done": [],
              "started_at": datetime.now(timezone.utc).strftime(
                  "%Y-%m-%d %H:%M UTC")}
    _LAST["status"] = status
    write_status(a.out, a.tag, status)

    for k, day in enumerate(days):
        t_day = time.time()
        log_(f"  {day}: читаю")
        got, alive = measure_day(a.root, syms, day, a.jobs, state, log=log_,
                                 mem_limit=mem_limit)
        # Первые сутки прогона судить нечем: σ тишины берётся у прошлых
        # суток. Они не «живые» и не «молчащие» — они третьего рода, и
        # считаются своим числом, а не подмешиваются к чужому.
        first = k == 0
        if first:
            pass
        elif not alive:
            dead += 1
        else:
            live_days.append(day)
        rows += got
        took = round((time.time() - t_day) / 60, 1)
        log_(f"  {day}: записей {len(got)}, всего {len(rows)}, {took} мин, "
             f"память {R.rss_mb()} МБ"
             + (" (первые сутки — только σ)" if first else ""))
        status["days_done"].append(
            {"day": day, "took_min": took, "rss_mb": R.rss_mb(),
             "alive": bool(alive), "sigma_only": bool(first),
             "records": len(rows)})
        write_status(a.out, a.tag, status)

    # Ноль наблюдений при непустом входе — ОТКАЗ, а не отчёт с
    # прочерками: пустота не вправе выдавать себя за результат. Малое
    # число событий отказом НЕ является — это убийца 1, и он числом.
    if not rows:
        raise SystemExit(
            f"ОТКАЗ: за {len(days)} суток по {len(syms)} именам не "
            f"нашлось ни одного принта ликвидации, пригодного к разметке "
            f"(молчавших лентой суток {dead}). Это не «эффекта нет», это "
            f"нечего мерить: проверять надо запись и подписку, а не "
            f"гипотезу.")
    mark, why = U.long_mark(state.get("n_sell", 0), state.get("n_buy", 0))
    if mark is None:
        raise SystemExit(
            f"ОТКАЗ: метку стороны выбрать нечем — {why}. Знак каждой "
            f"сделки был бы угадан, а перевёрнутый знак выглядит ровно "
            f"как «эффекта нет».")

    art = summarise(rows, live_days, dead, state, a.live, sigma_only=1)
    art.update({
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "days": len(days), "day_from": days[0], "day_to": days[-1],
        "symbols": len(syms),
        "took_min": round((time.time() - t_start) / 60, 1)})
    status["state"] = "готов"
    write_status(a.out, a.tag, status)
    p = os.path.join(a.out, f"MECH-unprov-{a.tag}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    U.report(art, os.path.join(a.out, f"MECH-unprov-{a.tag}.md"))
    log_(f"готово: {p}")
    log_(art["reading"])
    if not a.no_publish:
        # Публикация — часть прогона: шаг, который можно забыть, рано
        # или поздно забывают (урок D1).
        R.publish(f"механика d71203f0: неспровоцированный принт "
                  f"ликвидации ({a.tag})")
    return 0


if __name__ == "__main__":
    main()
