#!/usr/bin/env python3
"""Охрана рынком ВПЕРЁД: те же решения с охраной и без неё — с дня смены правил.

Вопрос владельца 2026-09-25: «насколько мы ближе к эджу». Число, которого
не даёт ни одна вкладка: сработало ли единственное внедрённое правило на
записи ВПЕРЁД — на решениях после 13.09, которых замер не видел. Кэш
реплея хранит исход позиции БЕЗ охраны (спека 14 §13), поэтому обе ветки
считаются одной кассой на одних записях: «без охраны» — с пустой картой
`rules.WAVE_GUARD_PCT` на время счёта, «с охраной» — как книги живут.

Это не замер оси и не подбор порога: порог один, объявленный; здесь
только вперёд/без и вперёд/с, по дням. Контроля случайными выходами нет
намеренно — он был у замера; вопрос тут другой: помогло ли правило на
новом окне.
"""
import argparse
import os
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
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import wave_guard as W                                        # noqa: E402

ART = "DCA-guard-forward"
MAIN_DEP = W.MAIN_DEP
BOOK_KEYS = W.BOOK_KEYS
SINCE = R.FAMILY_SINCE.get("h24") or "2026-09-13"


def since_ts(day):
    return float(time.mktime(time.strptime(day + " UTC", "%Y-%m-%d %Z")))


def forward_cache(cache, since):
    """Записи решений с дня `since` (00:00 UTC) — то, чего замер не видел."""
    t0 = since_ts(since)
    return {k: r for k, r in cache.items() if float(r.get("at") or 0) >= t0}


def stats_both(cache, ctx, launch, now=None, dep=MAIN_DEP):
    """Касса дважды на одних записях: без охраны (карта пуста) и с ней."""
    saved = dict(R.WAVE_GUARD_PCT)
    try:
        R.WAVE_GUARD_PCT.clear()
        off = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                          deps=[dep], now=now)
    finally:
        R.WAVE_GUARD_PCT.clear()
        R.WAVE_GUARD_PCT.update(saved)
    on = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                     deps=[dep], now=now)
    return off, on


def run(since=SINCE, log=print, now=None, launch=None, ctx=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    fwd = forward_cache(cache, since)
    log(f"записей всего {len(cache)}, с {since}: {len(fwd)}")
    off, on = stats_both(fwd, ctx, launch, now=now)
    books = {}
    for bk in BOOK_KEYS:
        a, b = off.get(f"{bk}:{MAIN_DEP}") or {}, on.get(f"{bk}:{MAIN_DEP}") or {}
        books[bk] = {"off": a, "on": b, "days": W.day_diff(a.get("days"), b.get("days"))}
        log(f"{bk}: без охраны {a.get('final')} / с охраной {b.get('final')}; "
            f"просадка {a.get('max_dd')} / {b.get('max_dd')}")
    return {"since": since, "n": len(fwd), "dep": MAIN_DEP, "books": books,
            "guard": dict(R.WAVE_GUARD_PCT), "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def report(s):
    L = ["# Охрана рынком вперёд: те же решения без охраны и с ней",
         "",
         f"Решения с {s.get('since', SINCE)} (00:00 UTC) — записи, которых замер оси не "
         "видел: правило выбрано на окне до этого дня. Обе колонки — одна касса на "
         f"одних записях, депозит ${int(s.get('dep') or MAIN_DEP):,}, нетто; «без охраны» — "
         "исход кэша реплея (пол, ликвидация, тейк, срок), «с охраной» — как книги "
         "живут. Это не замер оси и не подбор порога: порог один, объявленный; "
         "вопрос — помогло ли правило на новом окне.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой части.", ""]
    L += [f"Записей решений с {s['since']}: {s['n']}.", "",
          "| книга | сделок | итог: без → с | просадка: без → с | $ всего: без → с | "
          "$ без 3 лучших дней: без → с | хвостовых выходов (пол + ликвидация): без → с |",
          "|---|--:|--:|--:|--:|--:|--:|"]
    for bk, d in (s.get("books") or {}).items():
        a, b = d["off"], d["on"]
        at, aw, _ = W.wo3(a.get("days"))
        bt, bw, _ = W.wo3(b.get("days"))
        L.append(f"| {R.ruler_title(bk)} | {a.get('n', '—')} → {b.get('n', '—')} | "
                 f"{_pp(a.get('final'))} → **{_pp(b.get('final'))}** | "
                 f"{_pp(a.get('max_dd'))} → {_pp(b.get('max_dd'))} | "
                 f"{_usd(at)} → {_usd(bt)} | {_usd(aw)} → **{_usd(bw)}** | "
                 f"{W.tails_of(a)} → {W.tails_of(b)} |")
    L += ["", "## По дням", ""]
    for bk, d in (s.get("books") or {}).items():
        dd = d.get("days") or {}
        L += [f"**{R.ruler_title(bk)}**: дней {dd.get('n_days')}, с охраной лучше в "
              f"{dd.get('better')}, хуже в {dd.get('worse')}, разница всего "
              f"{_usd(dd.get('sum_diff'))}.", ""]
        rows = dd.get("rows") or []
        if rows:
            L += ["| день | без охраны | с охраной | разница |", "|---|--:|--:|--:|"]
            L += [f"| {x['d']} | {_usd(x['base'])} | {_usd(x['rule'])} | {_usd(x['diff'])} |"
                  for x in rows]
            L.append("")
    L += ["## Как читать", "",
          "- Разница по итогу и по «без 3 лучших дней» — вклад правила на окне, "
          "которого оно не видело; знак и размах — вот и весь ответ.",
          "- Дней мало: колонка «по дням» важнее итога — правило, что помогло одним "
          "днём и вредило остальными, и вперёд остаётся эпизодом.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default=SINCE, help="день смены правил, ГГГГ-ММ-ДД UTC")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(since=a.since, log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("охрана рынком вперёд: те же решения без охраны и с ней")


if __name__ == "__main__":
    main()
