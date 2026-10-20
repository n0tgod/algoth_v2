#!/usr/bin/env python3
"""Новая точка входа из пути цены (спека 19 §11.7, U4): проверка сдвигом.

Владелец 20.10: «ai при обучении должен сам искать паттерны поведения цены
внутри сделки, что-то повторяющееся, что можно перевести в новую стратегию
с новой ТВХ». Паттерн входа — это правило «не входить в час сигнала, а
дождаться условия»: отката против позиции (`pullback`), хода в пользу
(`confirm`) или просто времени (`delay`). Здесь он проверяется ЧИСЛОМ.

Как считается — тем же ядром, что книга, без второй копии: момент сигнала
`at` сдвигается на минуту срабатывания условия, и короткая книга Depth
пересчитывает позицию своим реплеем (`run_short.replay` → `run_d10`):
вход — открытие первой минутной свечи после условия (рыночный, не
«коснулись лимитки»), уровни, плечо, цель, пол и срок 24 ч — от нового
входа по правилам книги; затем возраст имени, охрана рынком и касса
(`gate_books.cash_net`). Не сработало условие за `within_h` — сделки нет.

Сравнения (объявлены до прогона):
1. вариант против книги на тех же сигналах: средний результат нетто на
   маржу НА СИГНАЛ (не сработавший — ноль) и касса $1k/$10k;
2. вариант против СЛУЧАЙНОГО момента входа в том же окне `within_h` для
   тех же сработавших сигналов (`NULL_SEEDS` зёрен) — иначе выигрыш от
   отбора сигналов («какие откатились») неотличим от выигрыша времени
   входа (урок проекта: пассивный вход — смена выборки);
3. обе половины по времени сигнала.

Вариант — «кандидат в новую ТВХ», если в ОБЕИХ половинах: сработавших ≥
`MIN_HALF`, средний на сигнал выше книги, средний на сработавший выше
медианы случайных моментов; и касса $10k выше книги. Кандидат — не книга:
новую книгу заводит только владелец.

Проверка самой проверки: те же сигналы БЕЗ сдвига, пересчитанные реплеем,
обязаны совпасть с кэшем книги (`reproduce` — доля совпавших pnl).

    entry_shift.py [--since 2026-09-20] [--limit N] [--no-publish]
"""
import argparse
import json
import os
import random
import statistics as st
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import gate_run as G                                          # noqa: E402

OUT = os.path.join(HERE, "out")
REPORT = os.path.join(OUT, "ENTRY-SHIFT.md")
LATEST = os.path.join(OUT, "entry_shift.json")
HYPS_FILE = os.path.join(OUT, "entry_hyps.json")       # гипотезы модели (U4b) — дописываются к сетке
BOOK, RULER = "optimal_h", "optimal_s"
H = 3600.0
MIN_HALF = 30
NULL_SEEDS = 3
# Сетка объявлена ДО первого прогона (20.10) и по результатам не меняется.
GRID = [{"id": "pullback_2pct_3h", "kind": "pullback", "pct": 2.0, "within_h": 3},
        {"id": "pullback_4pct_6h", "kind": "pullback", "pct": 4.0, "within_h": 6},
        {"id": "confirm_2pct_3h", "kind": "confirm", "pct": 2.0, "within_h": 3},
        {"id": "delay_1h", "kind": "delay", "after_h": 1}]
KINDS = ("pullback", "confirm", "delay")


def valid(h):
    if h.get("kind") not in KINDS:
        return "вид вне словаря"
    if h["kind"] == "delay":
        return None if 0 < float(h.get("after_h") or 0) <= 12 else "задержка вне (0, 12] ч"
    if not (0 < float(h.get("pct") or 0) <= 20):
        return "порог вне (0, 20] %"
    if not (0 < float(h.get("within_h") or 0) <= 12):
        return "окно вне (0, 12] ч"
    return None


def trigger(h, bars, at, side="short"):
    """Момент нового входа или None. `bars` — минутные [t,o,h,l,c,v] от `at`.

    Опора — цена входа книги: открытие первой свечи с t ≥ at. Против шорта —
    рост (high), в пользу — падение (low); у лонга зеркально. Новый `at` —
    КОНЕЦ минуты срабатывания: вход книги — открытие следующей свечи.
    """
    after = [b for b in bars if float(b[0]) >= at]
    if not after:
        return None
    if h["kind"] == "delay":
        t = at + float(h["after_h"]) * H
        return t if any(float(b[0]) >= t for b in after) else None
    e0 = float(after[0][1])
    lim = at + float(h["within_h"]) * H
    up = side == "short"
    p = float(h["pct"]) / 100.0
    for b in after:
        t = float(b[0])
        if t > lim:
            return None
        hi, lo = float(b[2]), float(b[3])
        against = (hi >= e0 * (1 + p)) if up else (lo <= e0 * (1 - p))
        favour = (lo <= e0 * (1 - p)) if up else (hi >= e0 * (1 + p))
        if (h["kind"] == "pullback" and against) or (h["kind"] == "confirm" and favour):
            return t + 60.0
    return None


def shifted(legs, h, bars_of, rng=None):
    """→ [(нога, новая нога | None)]. rng — случайный момент в окне (нуль)."""
    out = []
    w = float(h.get("within_h") or h.get("after_h") or 1)
    for g in legs:
        at = float(g["at"])
        bars = bars_of(g["sym"], at, at + (w + 0.5) * H)
        t = trigger(h, bars, at)
        if t is not None and rng is not None:
            t = at + 60.0 * int(rng.uniform(1, w * 60))
        out.append((g, dict(g, at=t, at_signal=at) if t is not None else None))
    return out


def recs_of(replayed, legs):
    """Записи линейки книги из ответа реплея по ногам (ключ — имя и момент)."""
    out = []
    for g in legs:
        r = replayed.get((RULER, g["sym"], round(float(g["at"]), 3)))
        if r is not None:
            out.append(r)
    return out


def book_chain(recs, log, now):
    """Те же правила после реплея, что у книги: возраст имени, охрана рынком."""
    import run_paper as RP                                     # noqa: E402
    import instruments_refresh as IR                           # noqa: E402
    quiet = lambda *a: None                                    # noqa: E731
    kept, _ = RP.age_shorts(list(recs), BOOK, launch=IR.launches(), log=quiet, now=now)
    kept, _ = RP.guard_shorts(kept, BOOK, log=quiet, now=now)
    return kept


def per_signal(pairs, recs_by_key, halves_at):
    """Средний нетто на маржу на сигнал (не сработавший — 0) и на сработавший, по половинам."""
    out = {}
    for name, sel in (("first", lambda a: a < halves_at), ("second", lambda a: a >= halves_at), ("all", lambda a: True)):
        sig, trig = [], []
        for g, ng in pairs:
            if not sel(float(g["at"])):
                continue
            if ng is None:
                sig.append(0.0)
                continue
            r = recs_by_key.get((ng["sym"], round(float(ng["at"]), 3)))
            v = float(r.get("pnl_net", r.get("pnl", 0.0))) if r else 0.0
            sig.append(v)
            trig.append(v)
        out[name] = {"signals": len(sig), "triggered": len(trig),
                     "mean_signal": round(st.mean(sig), 5) if sig else None,
                     "mean_triggered": round(st.mean(trig), 5) if trig else None}
    return out


def run(log=print, since=None, limit=None, now=None, src=None, replay=None, legs=None, cash=None):
    t0 = time.time()
    now = now or time.time()
    import run_short as S                                      # noqa: E402
    import gate_books as GB                                    # noqa: E402
    import costs as CO                                         # noqa: E402
    replay = replay or (lambda need: S.replay(need, src=src, log=lambda *a: None)[0])
    if legs is None:
        legs = S.legs(log=lambda *a: None)
    lo = since or (now - 30 * 86400)
    # сигнал обязан успеть: самое длинное окно + срок + час на дозапись
    hi = now - (24 + 12 + 1) * H
    legs = [g for g in legs if lo <= float(g["at"]) <= hi]
    if limit:
        legs = legs[:int(limit)]
    if len(legs) < 2 * MIN_HALF:
        return {"error": f"сигналов {len(legs)} < {2 * MIN_HALF}"}
    if src is None:
        import tail as TL                                      # noqa: E402
        src = TL.TailBars(log=lambda *a: None, cache=TL.BARS_CACHE)
    bars_memo = {}

    def bars_of(sym, a, b):
        k = (sym, int(a // H), int(b // H))
        if k not in bars_memo:
            bars_memo[k] = src.bars(sym, a, b) or []
        return bars_memo[k]
    halves_at = st.median(float(g["at"]) for g in legs)
    hyps = list(GRID)
    try:
        with open(HYPS_FILE, encoding="utf-8") as f:
            extra = json.load(f).get("hypotheses") or []
        hyps += [x for x in extra if not valid(x) and x.get("id") not in {h["id"] for h in hyps}]
    except (OSError, ValueError):
        pass
    log(f"сигналов {len(legs)} ({time.strftime('%Y-%m-%d', time.gmtime(lo))} … "
        f"{time.strftime('%Y-%m-%d', time.gmtime(hi))}), гипотез {len(hyps)}")
    ctx = CO.context()
    cash = cash or (lambda recs: GB.cash_net(BOOK, recs, now, ctx)[0])
    # 0. база: реплей без сдвига — та же книга; совпадение с кэшем — проверка проверки
    base_rep = replay(legs)
    base = recs_of(base_rep, legs)
    cache, _why = S.read_cache(log=lambda *a: None)
    same = tot = 0
    diffs, by_exit = [], {}
    for r in base:
        c = cache.get((RULER, r["sym"], round(float(r["at"]), 3)))
        if c is not None and c.get("state") == "closed" and r.get("state") == "closed":
            tot += 1
            if abs(float(c["pnl"]) - float(r["pnl"])) < 1e-9:
                same += 1
                continue
            # расхождение — с примерами: какой выход и где, у кэша и у реплея
            k = f"{c.get('exit')}→{r.get('exit')}"
            by_exit[k] = by_exit.get(k, 0) + 1
            if len(diffs) < 12:
                diffs.append({"sym": r["sym"], "at": r["at"], "cache": {f: c.get(f) for f in ("exit", "pnl", "exit_ts", "lev")},
                              "replay": {f: r.get(f) for f in ("exit", "pnl", "exit_ts", "lev")}})
    reproduce = {"compared": tot, "same": same, "share": round(same / tot, 4) if tot else None,
                 "diff_by_exit": by_exit, "diff_examples": diffs}
    log(f"проверка проверки: реплей без сдвига совпал с кэшем книги у {same} из {tot}")
    base_pairs = [(g, g) for g in legs]
    base_by = {(r["sym"], round(float(r["at"]), 3)): r for r in book_chain(base, log, now)}
    res = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "book": BOOK,
           "signals": len(legs), "since": lo, "until": hi, "halves_at": halves_at,
           "reproduce": reproduce, "grid_declared": GRID,
           "base": {"per_signal": per_signal(base_pairs, base_by, halves_at), "cash": cash(list(base_by.values()))},
           "hypotheses": []}
    for h in hyps:
        t1 = time.time()
        pairs = shifted(legs, h, bars_of)
        new_legs = [ng for _g, ng in pairs if ng is not None]
        rep = replay(new_legs) if new_legs else {}
        recs = book_chain(recs_of(rep, new_legs), log, now)
        by = {(r["sym"], round(float(r["at"]), 3)): r for r in recs}
        ps = per_signal(pairs, by, halves_at)
        nulls = []
        for s in range(NULL_SEEDS):
            npairs = shifted(legs, h, bars_of, rng=random.Random(100 + s))
            nl = [ng for _g, ng in npairs if ng is not None]
            nrep = replay(nl) if nl else {}
            nby = {(r["sym"], round(float(r["at"]), 3)): r for r in book_chain(recs_of(nrep, nl), log, now)}
            nulls.append(per_signal(npairs, nby, halves_at))
        null_med = {hn: (st.median([x[hn]["mean_triggered"] for x in nulls if x[hn]["mean_triggered"] is not None])
                         if any(x[hn]["mean_triggered"] is not None for x in nulls) else None)
                    for hn in ("first", "second", "all")}
        c = cash(recs)
        b = res["base"]

        def ok(hn):
            v, bb = ps[hn], b["per_signal"][hn]
            return (v["triggered"] >= MIN_HALF and v["mean_signal"] is not None and bb["mean_signal"] is not None
                    and v["mean_signal"] > bb["mean_signal"] and null_med[hn] is not None
                    and v["mean_triggered"] is not None and v["mean_triggered"] > null_med[hn])
        f10 = ((c.get(10000) or {}).get("final"), (b["cash"].get(10000) or {}).get("final"))
        passed = ok("first") and ok("second") and None not in f10 and f10[0] > f10[1]
        why = None if passed else ("первая половина не держит" if not ok("first") else
                                   "вторая половина не держит" if not ok("second") else "касса $10k не выше книги")
        res["hypotheses"].append({"id": h["id"], "rule": h, "per_signal": ps, "null_median_triggered": null_med,
                                  "cash": c, "candidate": passed, "why": why, "secs": round(time.time() - t1, 1)})
        log(f"{h['id']}: сработало {ps['all']['triggered']} из {ps['all']['signals']}, на сигнал "
            f"{ps['all']['mean_signal']} против книги {b['per_signal']['all']['mean_signal']}, "
            f"на сработавший {ps['all']['mean_triggered']} против случайного момента {null_med['all']} — "
            f"{'КАНДИДАТ' if passed else why} ({time.time() - t1:.0f} с)")
    res["secs"] = round(time.time() - t0, 1)
    return res


def report(r):
    if r.get("error"):
        return f"# Новая ТВХ из пути цены\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    pct = lambda v: "—" if v is None else f"{100 * v:+.2f} %"   # noqa: E731
    rp = r["reproduce"]
    share_txt = "—" if rp["share"] is None else "%.1f %%" % (100 * rp["share"])
    L = ["# Новая ТВХ из пути цены (спека 19 §11.7, U4)", "",
         f"Посчитано {r['computed_at']}; книга Depth · Short (`{r['book']}`); сигналов {r['signals']} "
         f"с {time.strftime('%Y-%m-%d', time.gmtime(r['since']))} по {time.strftime('%Y-%m-%d', time.gmtime(r['until']))}; "
         f"половины по {time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['halves_at']))} UTC; за {r['secs']} с.", "",
         f"**Проверка проверки:** реплей без сдвига совпал с кэшем книги у {rp['same']} из {rp['compared']} "
         f"закрытых ({share_txt}). Меньше 95 % — числам ниже не верить. Расхождения по выходу (кэш→реплей): "
         + (", ".join(f"{k} {v}" for k, v in sorted((rp.get("diff_by_exit") or {}).items(), key=lambda x: -x[1])) or "нет")
         + ". Книга и варианты ниже считаются ОДНИМ реплеем в одно время — расхождение с кэшем их сравнение не сдвигает.", "",
         "Средний результат нетто на маржу НА СИГНАЛ (не сработавший — 0) и НА СРАБОТАВШИЙ; «случайный момент» — "
         f"медиана {NULL_SEEDS} зёрен входа в случайную минуту того же окна для тех же сработавших сигналов.", "",
         "| вариант | сработало | на сигнал: 1-я / 2-я | на сработавший: 1-я / 2-я | случайный момент: 1-я / 2-я | касса $10k | вывод |",
         "|---|---|---|---|---|---|---|"]
    b = r["base"]
    bp = b["per_signal"]
    L.append(f"| книга (вход в час сигнала) | {bp['all']['triggered']} | {pct(bp['first']['mean_signal'])} / "
             f"{pct(bp['second']['mean_signal'])} | — | — | {pct((b['cash'].get(10000) or b['cash'].get('10000') or {}).get('final'))} | — |")
    for h in r["hypotheses"]:
        p, n = h["per_signal"], h["null_median_triggered"]
        c10 = (h["cash"].get(10000) or h["cash"].get("10000") or {}).get("final")
        L.append(f"| `{h['id']}` | {p['all']['triggered']} / {p['all']['signals']} | {pct(p['first']['mean_signal'])} / "
                 f"{pct(p['second']['mean_signal'])} | {pct(p['first']['mean_triggered'])} / {pct(p['second']['mean_triggered'])} | "
                 f"{pct(n['first'])} / {pct(n['second'])} | {pct(c10)} | {'**кандидат**' if h['candidate'] else h['why']} |")
    L += ["", "Кандидат — не книга: новую книгу (сестру с этой ТВХ, запись вперёд) заводит только владелец."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="ГГГГ-ММ-ДД, умолчание — 30 суток назад")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                     # noqa: E402
    import calendar
    since = calendar.timegm(time.strptime(a.since, "%Y-%m-%d")) if a.since else None
    r = run(log=AB.guarded(print, limit=2500), since=since, limit=a.limit)
    os.makedirs(OUT, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    txt = report(r)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "новая ТВХ из пути цены"], cwd=ROOT, check=False)
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
