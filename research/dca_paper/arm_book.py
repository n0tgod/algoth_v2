#!/usr/bin/env python3
"""Книга DCA на решениях ОДНОЙ руки: деревья против сети, честно.

Вопрос владельца 2026-09-07: «чьи сигналы лучше — сети или деревьев?».
Разрез журнала (`arm_split.py`) на него не отвечает: у рук разные
СОСТАВЫ решений, и рука, чьих решений больше, набирает больше денег, не
будучи лучше. Здесь считается другое — книга, которая брала бы решения
ТОЛЬКО одной руки, теми же правилами и на том же депозите. Различие
между двумя прогонами ровно одно: чей лист.

Откуда берутся исходы. Кэш реплея книги (`out/recs.jsonl`) держит по
одной записи на (пара линейки, имя, момент) — и когда обе руки выбрали
одно имя в один час, в кэше остаётся ОДНА из них, а вторая не считалась
вовсе. Поэтому:

1. записи кэша разбираются по рукам сравнением с ногами листа (прогноз
   и обещание ноги — поля записи `fwd` и `fav_bp`);
2. чего у руки не хватает, досчитывается реплеем ТОЛЬКО этих ног
   (`run_d6.collect_recs` тем же ядром и тем же хвостом ленты) — кэш
   книги при этом не трогается вовсе, файл не переписывается;
3. дальше каждая рука проходит ТУ ЖЕ сборку книги, что и настоящая
   (`run_paper.build_rows`: гейт плеча, одна позиция на имя, раздача
   кассы), — второй копии правил книги здесь нет.

Чего замер НЕ говорит. Каждой руке даётся ВЕСЬ депозит: это ответ на
«что если бы книга слушала только её», а не разложение нынешней книги на
две. Билет остаётся объявленным билетом режима (у одной руки решений
меньше, и по своему пику ей полагался бы билет крупнее) — измеренный пик
руки печатается рядом, чтобы запас был виден. Деньги — брутто; издержки
меряет `costs.py` и они пропорциональны обороту.

Запуск: run research/dca_paper/arm_book.py
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import run_d6 as D6                                           # noqa: E402
import run_paper as RP                                        # noqa: E402
import tail as TL                                             # noqa: E402

ARMS = ("gbm", "nn")
ARM_TITLE = {"gbm": "деревья", "nn": "сеть"}
MAIN_DEP = 10000
EPS = 1e-6
# Тяжёлый прогон рядом с часовым циклом убивает не себя, а ЦИКЛ: ядро
# выбирает жертву по-своему, и D10 уже уронил обучение на сутки. Предел
# и самоостанов живут В САМОМ прогоне.
MEM_LIMIT_MB = 1200


def _rss_mb():
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1048576.0
    except (OSError, ValueError, IndexError):
        return 0.0


def guarded(log, limit=MEM_LIMIT_MB, rss=None):
    """Лог реплея со сторожем памяти: превысили предел — останавливаемся
    сами, вслух и с числом, а не ждём, кого выберет ядро."""
    rss = rss or _rss_mb

    def _log(*a):
        log(*a)
        mb = rss()
        if mb > limit:
            log(f"СТОП: память {mb:.0f} МБ больше предела {limit} МБ — "
                "прогон останавливается сам, цикл не трогаем")
            raise SystemExit(3)
    return _log


def arm_title(arm):
    return ARM_TITLE.get(arm, str(arm))


def pairs_of():
    """Пары (правило, параметр, сторона) без повторов — как у книги."""
    out = []
    for k in R.RULER_ORDER:
        pr = RP.RULERS[k]
        if pr not in out:
            out.append(pr)
    return out


def key_of(sym, at):
    return (str(sym), round(float(at), 3))


def legs_index(legs):
    """(имя, момент) → список ног: рука, |прогноз|, обещание, сторона."""
    idx = {}
    for g in legs:
        idx.setdefault(key_of(g["sym"], g["at"]), []).append(
            {"arm": g.get("arm") or "gbm", "fwd": abs(float(g["fwd"])),
             "fav": float(g["fav"]), "side": g.get("side") or "long",
             "leg": g})
    return idx


def match_arm(rec, cands):
    """Чья это запись: сравнение с ногами по прогнозу и обещанию.

    Рука не выводится из правила «побеждает больший прогноз»: в кэше
    остаётся та запись, что легла последней, и это свойство КОДА, а не
    правило книги. Сравниваются числа самой записи.
    """
    side = rec.get("side") or "long"
    same = [c for c in cands if c["side"] == side]
    if not same:
        return None, "нет ноги"
    fwd = abs(float(rec.get("fwd") or 0))
    fav = rec.get("fav_bp")
    hit = []
    for c in same:
        if abs(c["fwd"] - fwd) > EPS:
            continue
        if fav is not None and abs(c["fav"] - float(fav)) > EPS:
            continue
        hit.append(c)
    arms = {c["arm"] for c in hit}
    if len(arms) == 1:
        return hit[0]["arm"], None
    if not arms:
        return None, "нога не сошлась"
    return None, "руки неразличимы"


def split_cache(cache, idx, log=print):
    """Записи кэша по рукам плюс счёт причин, по которым рука не вышла."""
    owned, why = {}, {"нет ноги": 0, "нога не сошлась": 0,
                      "руки неразличимы": 0}
    disputed = {a: 0 for a in ARMS}
    for (pair, sym, at), rec in cache.items():
        cands = idx.get(key_of(sym, at)) or []
        arm, bad = match_arm(rec, cands)
        if arm is None:
            why[bad] = why.get(bad, 0) + 1
            continue
        owned[(pair, sym, round(float(at), 3))] = (arm, rec)
        side = rec.get("side") or "long"
        if len({c["arm"] for c in cands if c["side"] == side}) > 1:
            disputed[arm] = disputed.get(arm, 0) + 1
    log(f"кэш: записей {len(cache)}, разобрано {len(owned)}, "
        f"без руки {sum(why.values())} ({why})")
    log(f"спорные решения (обе руки на имени и часе) достались: "
        + ", ".join(f"{arm_title(a)} {n}" for a, n in disputed.items()))
    return owned, why, disputed


def missing_legs(legs, owned, pairs):
    """Ноги, чьей записи у ИХ руки нет: их и надо досчитать."""
    need = []
    for g in legs:
        side = g.get("side") or "long"
        arm = g.get("arm") or "gbm"
        k = key_of(g["sym"], g["at"])
        for pr in pairs:
            if (pr[2] if len(pr) > 2 else "long") != side:
                continue
            got = owned.get((tuple(pr), k[0], k[1]))
            if got is None or got[0] != arm:
                need.append(g)
                break
    return need


def replay(need, pairs, src=None, log=print):
    """Досчёт недостающих ног ТЕМ ЖЕ ядром и тем же хвостом ленты.

    Кэш книги не читается на запись и не переписывается: файл книги —
    её собственная память, и замер не вправе её менять.
    """
    if not need:
        return {}, {}
    src = src or TL.TailBars(log=log)
    got = D6.collect_recs(rulers=pairs, legs=need, src=src,
                          log=guarded(log))
    tail = dict(src.stats(), **TL.apply(got["recs"], src.last_tape,
                                        src.last_book))
    out = {}
    for pr, lst in got["recs"].items():
        for r in lst:
            out[(tuple(pr), r["sym"], round(float(r["at"]), 3))] = r
    log(f"досчитано записей {len(out)} по {len(need)} ногам")
    return out, tail


def _median(xs):
    if not xs:
        return None
    ys = sorted(xs)
    m = len(ys) // 2
    return ys[m] if len(ys) % 2 else 0.5 * (ys[m - 1] + ys[m])


def stats(rows, mid=None):
    if not rows:
        return {"n": 0}
    usd = [float(r.get("usd") or 0) for r in rows]
    pct = [100.0 * float(r.get("pnl_frac") or 0) for r in rows]
    ex = {}
    for r in rows:
        ex[r.get("exit") or "—"] = ex.get(r.get("exit") or "—", 0) + 1
    s = {"n": len(rows), "usd": round(sum(usd), 2),
         "pct_median": round(_median(pct), 3),
         "win": round(100.0 * sum(1 for x in usd if x > 0) / len(usd), 1),
         "worst": round(min(usd), 2), "best": round(max(usd), 2),
         "exits": ex}
    days = {}
    for r in rows:
        d = time.strftime("%Y-%m-%d", time.gmtime(float(r.get("exit_ts") or 0)))
        days[d] = days.get(d, 0.0) + float(r.get("usd") or 0)
    s["days"] = len(days)
    s["day_median"] = round(_median(list(days.values())), 2) if days else None
    if mid is not None:
        a = [float(r.get("usd") or 0) for r in rows if float(r.get("at") or 0) < mid]
        b = [float(r.get("usd") or 0) for r in rows if float(r.get("at") or 0) >= mid]
        s["half_a"] = round(sum(a), 2) if a else None
        s["half_b"] = round(sum(b), 2) if b else None
        s["n_a"], s["n_b"] = len(a), len(b)
    return s


def run(log=print, limit=None, src=None, legs=None, cache=None):
    t0 = time.time()
    pairs = pairs_of()
    legs = legs if legs is not None else D6.gated_legs(side=None, log=log,
                                                       limit=limit)
    if cache is None:
        cache, why = RP.read_cache()
        if why:
            log(f"кэш реплея непригоден: {why}")
            return {"error": f"кэш реплея непригоден: {why}"}
    idx = legs_index(legs)
    owned, why, disputed = split_cache(cache, idx, log=log)
    need = missing_legs(legs, owned, pairs)
    log(f"ног всего {len(legs)}, досчитать надо {len(need)}")
    extra, tail = replay(need, pairs, src=src, log=log)
    # досчитанные записи разбираются по рукам ТЕМ ЖЕ сравнением
    extra_owned = {}
    for k, rec in extra.items():
        arm, bad = match_arm(rec, idx.get((k[1], k[2])) or [])
        if arm is not None:
            extra_owned[k] = (arm, rec)
        else:
            why[bad] = why.get(bad, 0) + 1
    ats = [float(g["at"]) for g in legs]
    mid = 0.5 * (min(ats) + max(ats)) if ats else None
    books = {}
    for arm in ARMS:
        own = {k: v for k, v in owned.items() if v[0] == arm}
        own.update({k: v for k, v in extra_owned.items() if v[0] == arm})
        by_ruler = {}
        for k, (_a, rec) in own.items():
            by_ruler.setdefault(k[0], []).append(rec)
        packed = {rk: list(by_ruler.get(tuple(RP.RULERS[rk])) or [])
                  for rk in R.RULER_ORDER}
        rows, cells, one, _live = RP.build_rows(packed, log=log)
        got = {}
        for rk in R.RULER_ORDER:
            key = f"{rk}:{MAIN_DEP}"
            rs = [r for r in rows if r.get("ruler") == rk
                  and int(float(r.get("dep") or 0)) == MAIN_DEP]
            c = cells.get(key) or {}
            got[rk] = {"stats": stats(rs, mid),
                       "final": c.get("final"), "max_dd": c.get("max_dd"),
                       "taken": c.get("taken"), "no_cash": c.get("no_cash"),
                       "too_small": c.get("too_small"),
                       "peak": (one.get(rk) or {}).get("peak_names"),
                       "peak_declared": (one.get(rk) or {}).get("peak_declared"),
                       "kept": (one.get(rk) or {}).get("kept"),
                       "positions": (one.get(rk) or {}).get("positions")}
        books[arm] = got
    return {"at": time.time(), "secs": round(time.time() - t0, 1),
            "legs": len(legs), "cache": len(cache), "owned": len(owned),
            "replayed": len(extra), "why": why, "disputed": disputed,
            "mid": mid, "dep": MAIN_DEP, "books": books, "tail": tail,
            "rules": R.RULES}


def verdict(s):
    """Кто лучше — по каждой книге отдельно, и только там, где обе руки
    дали не меньше 30 сделок; иначе вердикта нет."""
    v = {}
    for rk in R.RULER_ORDER:
        a = (s["books"]["gbm"].get(rk) or {})
        b = (s["books"]["nn"].get(rk) or {})
        sa, sb = a.get("stats") or {"n": 0}, b.get("stats") or {"n": 0}
        if sa.get("n", 0) < 30 or sb.get("n", 0) < 30:
            v[rk] = {"why": "сделок меньше 30 хотя бы у одной руки",
                     "n": [sa.get("n", 0), sb.get("n", 0)]}
            continue
        fa, fb = a.get("final") or 0.0, b.get("final") or 0.0
        halves = {"gbm": (sa.get("half_a"), sa.get("half_b")),
                  "nn": (sb.get("half_a"), sb.get("half_b"))}
        v[rk] = {"final": {"gbm": fa, "nn": fb},
                 "day_median": {"gbm": sa.get("day_median"),
                                "nn": sb.get("day_median")},
                 "winner": "gbm" if fa > fb else ("nn" if fb > fa else None),
                 "winner_holds_halves": bool(
                     all(x is not None and x > 0
                         for x in halves["gbm" if fa > fb else "nn"]))}
    return v


def _p(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def report(s):
    if s.get("error"):
        return f"# Книга DCA по руке модели\n\nЗамер не состоялся: {s['error']}.\n"
    L = ["# Книга DCA на решениях одной руки: деревья против сети", "",
         "Вопрос владельца: «чьи сигналы лучше — сети или деревьев?». "
         "Разрез журнала на него не отвечает: составы решений у рук "
         "разные, и рука с бо́льшим числом решений набирает больше денег, "
         "не будучи лучше. Здесь для каждой руки собрана СВОЯ книга: те "
         "же правила, тот же депозит, весь депозит — различие ровно одно, "
         "чей лист.", "",
         f"Ног листа {s['legs']}; записей кэша реплея {s['cache']}, из них "
         f"разобрано по рукам {s['owned']}; досчитано реплеем {s['replayed']} "
         "(кэш книги при этом не переписывался). Спорные решения — те, где "
         "обе руки выбрали одно имя в один час; в кэше книги от такого "
         "решения оставалась одна запись, и кому она досталась, видно "
         "числом: " + ", ".join(f"{arm_title(a)} {n}"
                                for a, n in s["disputed"].items()) + ".", ""]
    if any(s["why"].values()):
        L += ["Записи без руки: " + ", ".join(
            f"{k} — {v}" for k, v in s["why"].items() if v) + ".", ""]
    L += [f"## Итог книг на ${s['dep']} (брутто журнала)", "",
          "| книга | рука | взято | итог | просадка | медиана дня $ | Σ $ | "
          "медиана % маржи | плюсов | половина A $ | половина B $ |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for rk in R.RULER_ORDER:
        for arm in ARMS:
            b = (s["books"][arm].get(rk) or {})
            st = b.get("stats") or {"n": 0}
            L += [f"| `{rk}` ({R.ruler_title(rk)}) | {arm_title(arm)} | "
                  f"{b.get('taken')} | {_p(b.get('final'))} | "
                  f"{_p(b.get('max_dd'))} | {_u(st.get('day_median'))} | "
                  f"{_u(st.get('usd'))} | "
                  + ("—" if st.get("pct_median") is None
                     else f"{st['pct_median']:+.2f} %")
                  + f" | {st.get('win', '—')} % | {_u(st.get('half_a'))} | "
                  f"{_u(st.get('half_b'))} |"]
    L += ["", "## Вердикт", "",
          "| книга | итог деревья | итог сеть | кто лучше | держит обе половины |",
          "|---|---:|---:|---|---|"]
    for rk, v in verdict(s).items():
        if v.get("why"):
            L += [f"| `{rk}` | — | — | вердикта нет: {v['why']} "
                  f"({v['n'][0]} и {v['n'][1]}) | — |"]
        else:
            L += [f"| `{rk}` | {_p(v['final']['gbm'])} | {_p(v['final']['nn'])} | "
                  f"{arm_title(v['winner']) if v['winner'] else 'поровну'} | "
                  f"{'да' if v['winner_holds_halves'] else 'нет'} |"]
    L += ["", "## Запас по местам (билет остался объявленным)", "",
          "| книга | рука | решений | после одной на имя | пик измеренный | пик объявленный |",
          "|---|---|---:|---:|---:|---:|"]
    for rk in R.RULER_ORDER:
        for arm in ARMS:
            b = (s["books"][arm].get(rk) or {})
            L += [f"| `{rk}` | {arm_title(arm)} | {b.get('positions')} | "
                  f"{b.get('kept')} | {b.get('peak')} | {b.get('peak_declared')} |"]
    L += ["", "## Чего замер НЕ говорит", "",
          "- Каждой руке дан ВЕСЬ депозит: это ответ на «что если книга "
          "слушала бы только её», а не разложение нынешней книги на две. "
          "Сложить два итога нельзя.",
          "- Билет остался объявленным билетом режима. У руки решений "
          "меньше, и по своему пику ей полагался бы билет крупнее — "
          "измеренный пик стоит рядом, чтобы запас был виден.",
          "- Деньги — брутто. Издержки меряет `costs.py`; они "
          "пропорциональны обороту и у руки с бо́льшим числом сделок "
          "съедят больше.",
          "- Окно одно и то же для обеих рук, и оно короткое: две трети "
          "денег книги сделаны за всплеск 20–22.08. Половины окна "
          "печатаются именно поэтому.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="книга DCA на решениях одной руки")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run(limit=a.limit)
    name = f"DCA-arm-book-{a.tag}" if not a.limit else f"DCA-arm-book-smoke-{a.tag}"
    with open(os.path.join(R.OUT, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(R.OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"DCA: книга на решениях одной руки ({a.tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
