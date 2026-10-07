#!/usr/bin/env python3
"""Пол капитуляции коротких книг как ОСЬ — ядро лестницы, один проход на
группу пола, записи на диск.

Решение владельца 07.10 («давай замерим») после наблюдения в замере трёх
осей долива: пол 0.25 без долива лучше книги у обеих судимых книг (2.89
против 2.78 у оптимальной, 2.74 против 2.46 у агрессивной), пол 0.10 —
хуже у обеих; 03.10 убит пол 0.75. Пол — доля отрезка «вход → ликвидация»,
остающаяся до ликвидации в момент, когда книга режет позицию сама: 0.5 —
посередине (≈ −50 % маржи), 0.25 — ближе к ликвидации (≈ −75 %), 0.10 —
почти у неё (≈ −90 %). Меньше число — шире стоп.

Оси объявлены до прогона: пол 0.10 / 0.15 / 0.25 / 0.35 / 0.50 / 0.65 /
0.75 на геометрии книги (`fence:none:t2`), без доливов, срок 24 ч, по
группам пола книг — 0.5 (оптимальная и агрессивная — судимые) и 0.1
(безопасная — печатается). ГЛАВНАЯ ячейка — 0.25 против пола книги: она
объявлена вчера по чужому замеру; остальные ячейки — форма кривой, лучшая
из них правилом не назначается (R5).

Случайного нуля нет — тот же довод, что у множителя тейка (`short_take`):
пол не режет число сделок, те же решения входят и закрываются иначе.
Контроль здесь другой и обязательный: касса на трёх депозитах ($1k / $10k
/ $100k), ОБЕ половины окна по дате входа, состав выходов (пол /
ликвидация / тейк / срок / рынок), «без трёх лучших дней», σ дня.

Кандидат (объявлено): пол 0.25 лучше пола книги по доходу/просадке у обеих
судимых книг на $10k, в обеих половинах окна и на всех трёх депозитах.
Прошедший — кандидат на сестринские книги вперёд, не правило. Ячейка пола
книги обязана совпасть с кэшем книги (сверка числом).

    run research/dca_paper/short_floor.py --group 0.5    # ~1.7 ч
    run research/dca_paper/short_floor.py --group 0.1
    run research/dca_paper/short_floor.py --assemble
"""
import argparse
import gc
import json
import os
import statistics
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
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_rung as SR                                       # noqa: E402
import short_rung_axes as AX                                  # noqa: E402
import short_size as Z                                        # noqa: E402
import wave_guard as W                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-floor"
FLOORS = (0.10, 0.15, 0.25, 0.35, 0.50, 0.65, 0.75)
MAIN_FLOOR = 0.25
DEPS = (1000.0, 10000.0, 100000.0)
MAIN_DEP = 10000.0
JUDGE = ("optimal_h", "aggr_h")
BASE = S.CELL
BOOK_KEYS = list(S.BOOKS)


def cell_name(f):
    return f"f{int(round(float(f) * 100)):03d}"


def cells_for():
    return [(SR.cell_key(cell_name(f)), BASE[1], BASE[2], BASE[3]) for f in FLOORS]


def floor_of_name(name):
    return int(name[1:]) / 100.0


def policy(name):
    """Пол ячейки — явно у каждой, включая пол книги: окно и ядро глобал не трогают."""
    return {"adds": [], "floor_frac": floor_of_name(SR.name_of(name) if "#" in name else name)}


def adds_of(_g, key):
    return policy(key)


def book_floor(bk):
    return float(R.floor_frac_of(bk, 0.10))


def halves(days, dep):
    """Две половины окна по ДАТЕ (первая и вторая половина дней кассы):
    итог, просадка, доход/просадка — формулой кассы."""
    rows = sorted((d for d in (days or []) if d.get("d")), key=lambda d: d["d"])
    if len(rows) < 4:
        return [None, None]
    cut = len(rows) // 2
    out = []
    for part in (rows[:cut], rows[cut:]):
        v = [float(d.get("usd") or 0.0) for d in part]
        fin = sum(v) / float(dep)
        dd = RP._dd(v, dep)
        out.append({"from": part[0]["d"], "to": part[-1]["d"], "days": len(part),
                    "final": round(fin, 4), "max_dd": round(dd, 4),
                    "ratio": (round(fin / abs(dd), 2) if fin and dd else None)})
    return out


def cash_of(cell_recs, ctx, launch, books, now=None):
    """Касса ячейки на трёх депозитах по книгам группы + половины окна на $10k."""
    packed = SR.packed_of(cell_recs)
    keys = [bk for bk in books if packed.get(bk)]
    st = G.cell_stats({bk: packed[bk] for bk in keys}, ctx, launch, now=now, keys=keys, deps=list(DEPS))
    out = {}
    for bk in keys:
        by_dep = {}
        for dep in DEPS:
            c = st.get(f"{bk}:{int(dep)}") or {}
            d = {"n": c.get("n"), "final": c.get("final"), "max_dd": c.get("max_dd"), "usd": c.get("usd"),
                 "ratio": SR.ratio_of(c)}
            if int(dep) == int(MAIN_DEP):
                sd, _r = Z.day_sigma(c.get("days"))
                _t, wo, _top = W.wo3(c.get("days"))
                ex = c.get("exits") or {}
                d.update({"sigma_day": sd, "wo3": wo,
                          "exits": {k: int((v or {}).get("n") or 0) for k, v in ex.items()},
                          "kill_n": sum(int((ex.get(k) or {}).get("n") or 0) for k in SR.KILL_EXITS),
                          "halves": halves(c.get("days"), dep)})
            by_dep[str(int(dep))] = d
        out[bk] = by_dep
    return out


def judge(cash, books):
    """Главная ячейка 0.25 против пола книги: $10k, обе половины, все депозиты, обе книги."""
    rows, ok_all = {}, True
    main, = [cell_name(MAIN_FLOOR)]
    for bk in books:
        ref_name = cell_name(book_floor(bk))
        a, b = cash[main].get(bk) or {}, cash[ref_name].get(bk) or {}
        md = str(int(MAIN_DEP))
        r_main, r_ref = (a.get(md) or {}).get("ratio"), (b.get(md) or {}).get("ratio")
        deps_ok = all((a.get(str(int(d))) or {}).get("ratio") is not None and (b.get(str(int(d))) or {}).get("ratio") is not None
                      and float(a[str(int(d))]["ratio"]) > float(b[str(int(d))]["ratio"]) for d in DEPS)
        ha, hb = (a.get(md) or {}).get("halves") or [None, None], (b.get(md) or {}).get("halves") or [None, None]
        halves_ok = all(x and y and x.get("ratio") is not None and y.get("ratio") is not None
                        and float(x["ratio"]) > float(y["ratio"]) for x, y in zip(ha, hb))
        better = r_main is not None and r_ref is not None and float(r_main) > float(r_ref)
        rows[bk] = {"book_floor": book_floor(bk), "ratio_main": r_main, "ratio_book": r_ref,
                    "better_10k": better, "all_deps": deps_ok, "both_halves": halves_ok,
                    "halves_main": ha, "halves_book": hb}
        if bk in JUDGE:
            ok_all = ok_all and better and deps_ok and halves_ok
    return {"books": rows, "candidate": ok_all and all(bk in rows for bk in JUDGE)}


def verdict(jd):
    if not all(bk in jd["books"] for bk in JUDGE):
        return "не измерено: нет группы пола судимых книг"
    if jd["candidate"]:
        return (f"КАНДИДАТ на сестринские книги вперёд (не правило — одно окно): пол {MAIN_FLOOR:g} лучше пола книги "
                "у обеих судимых книг на $10k, в обеих половинах окна и на всех трёх депозитах")
    why = []
    for bk in JUDGE:
        r = jd["books"][bk]
        miss = [n for n, ok in (("$10k", r["better_10k"]), ("все депозиты", r["all_deps"]), ("обе половины", r["both_halves"])) if not ok]
        if miss:
            why.append(f"{bk}: не прошёл — {', '.join(miss)}")
    return f"не кандидат: пол {MAIN_FLOOR:g} против пола книги — " + "; ".join(why)


# ---------------------------------------------------------------- части и сборка
def part_path(frac, out_dir=None):
    return os.path.join(out_dir or R.OUT, f"{ART}-part-{float(frac):g}.json")


def write_part(part, out_dir=None):
    os.makedirs(out_dir or R.OUT, exist_ok=True)
    path = part_path(part["frac"], out_dir)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(part, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)
    return path


def read_parts(out_dir=None):
    out = {}
    for frac in S.floor_groups():
        p = part_path(frac, out_dir)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    out[float(frac)] = json.load(f)
            except (OSError, ValueError) as e:
                out[float(frac)] = {"error": f"часть не читается: {e}"}
    return out


def run(limit=None, src=None, log=print, legs_=None, ctx=None, launch=None, now=None,
        groups=None, mem_limit=None, out_dir=None, sink_dir=None, cache=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        return {"error": "коротких решений на листе нет"}
    if cache is None:
        cache, _why = S.read_cache(log=log)
    cache = cache or {}
    want = (set(float(x) for x in groups) if groups is not None else None)
    names = [cell_name(f) for f in FLOORS]
    for frac, group in sorted(S.floor_groups().items()):
        if want is not None and float(frac) not in want:
            continue
        books = [bk for bk in BOOK_KEYS if S.BOOKS[bk] in group]
        rk = group[0]
        sink = AX.Sink(os.path.join(sink_dir or os.path.join(S.CACHE_DIR, "floor"), f"g{float(frac):g}"))
        try:
            _out, tail = S.replay_cells(legs_, cells_for(), src=src, log=log, adds_of=adds_of,
                                        rulers=group, sink=sink)
        finally:
            sink.close()
        data_end = float((tail or {}).get("data_end") or 0.0)
        log(f"пол {frac:g}: записей на диске {sink.n}, конец записи "
            f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(data_end))} UTC ({time.time() - t0:.0f} с)")
        ref_recs = sink.read(rk, SR.cell_key(cell_name(float(frac))), data_end)
        check = SR.ref_check(ref_recs, cache)
        log(f"пол {frac:g}: сверка ячейки пола книги с кэшем — закрытых у обоих {check['compared']}, "
            f"расхождений {check['mismatch']}")
        del ref_recs
        part = {"frac": float(frac), "rulers": list(group), "books": books, "cash": {}, "ref_check": check,
                "tail": tail, "legs": len(legs_), "computed_at": G.stamp()}
        for nm in names:
            recs = sink.read(rk, SR.cell_key(nm), data_end)
            part["cash"][nm] = cash_of(recs, ctx, launch, books, now=now)
            log(f"пол {frac:g} {nm}: " + ", ".join(
                f"{bk} {part['cash'][nm][bk][str(int(MAIN_DEP))]['ratio']} (сделок {part['cash'][nm][bk][str(int(MAIN_DEP))]['n']})"
                for bk in books if bk in part["cash"][nm]) + f" ({time.time() - t0:.0f} с)")
            del recs
            gc.collect()
        part["secs"] = round(time.time() - t0, 1)
        log(f"часть записана: {write_part(part, out_dir)}")
    s = assemble(out_dir=out_dir)
    s["secs_run"] = round(time.time() - t0, 1)
    return s


def assemble(out_dir=None):
    parts = read_parts(out_dir)
    names = [cell_name(f) for f in FLOORS]
    cash = {nm: {} for nm in names}
    check = {"compared": 0, "mismatch": 0, "sample": []}
    meta, missing, have = {}, [], []
    for frac, group in sorted(S.floor_groups().items()):
        p = parts.get(float(frac))
        books = [bk for bk in BOOK_KEYS if S.BOOKS[bk] in group]
        if not p or p.get("error"):
            missing.append({"frac": float(frac), "books": books, "why": (p or {}).get("error") or "часть не посчитана"})
            continue
        meta[f"{float(frac):g}"] = {"computed_at": p.get("computed_at"), "secs": p.get("secs"), "legs": p.get("legs"),
                                     "books": books, "ref_check": p.get("ref_check")}
        c = p.get("ref_check") or {}
        check["compared"] += int(c.get("compared") or 0)
        check["mismatch"] += int(c.get("mismatch") or 0)
        for nm in names:
            for bk in books:
                v = (p.get("cash") or {}).get(nm, {}).get(bk)
                if v is not None:
                    cash[nm][bk] = v
        have += books
    jd = judge(cash, have) if have else {"books": {}, "candidate": False}
    return {"floors": list(FLOORS), "main_floor": MAIN_FLOOR, "deps": list(DEPS), "main_dep": MAIN_DEP,
            "judge_books": list(JUDGE), "books": have, "missing": missing, "parts": meta,
            "cash": cash, "judge": jd, "ref_check": check, "verdict": verdict(jd), "computed_at": G.stamp()}


# ---------------------------------------------------------------- отчёт
_p, _pp, _f, _n, _title = SR._p, SR._pp, SR._f, SR._n, SR._title


def report(s):
    if s.get("error"):
        return f"# Пол капитуляции как ось\n\nОШИБКА: {s['error']}\n"
    md = str(int(s["main_dep"]))
    L_ = ["# Пол капитуляции коротких книг как ось: 0.10 … 0.75 — ядро лестницы, без доливов, срок 24 ч", ""]
    for frac, m in sorted((s.get("parts") or {}).items(), key=lambda kv: float(kv[0])):
        c = m.get("ref_check") or {}
        L_.append(f"- группа пола {frac} ({', '.join(_title(b) for b in m.get('books') or [])}): решений {m.get('legs')}, "
                  f"посчитана {m.get('computed_at')} за {_n(m.get('secs'))} с; сверка ячейки пола книги с кэшем: "
                  f"{c.get('compared')} закрытых, расхождений {c.get('mismatch')}.")
    for m in s.get("missing") or []:
        L_.append(f"- группа пола {m['frac']:g} ({', '.join(_title(b) for b in m['books'])}): НЕ ПОСЧИТАНА — {m['why']}.")
    L_ += ["", f"Пол — доля отрезка «вход → ликвидация», остающаяся до ликвидации при капитуляции: меньше число — шире стоп. "
               f"Главная ячейка {s['main_floor']:g} против пола книги; остальные — форма кривой. Деньги нетто; "
               f"касса ${int(s['main_dep']):,} в таблице, рядом ${int(s['deps'][0]):,} и ${int(s['deps'][2]):,}; половины окна по дате.", ""]
    for bk in s["books"]:
        bf = book_floor(bk)
        L_ += [f"## {_title(bk)} (пол книги {bf:g})", "",
               "| пол | сделок | итог | просадка | доход/просадка | $1k | $100k | 1-я половина | 2-я половина | без 3 дней, $ | σ дня, $ | пол | ликв. | тейк | срок | рынок |",
               "|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for f in s["floors"]:
            c = (s["cash"].get(cell_name(f)) or {}).get(bk)
            if not c:
                L_.append(f"| {f:g} | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |")
                continue
            d = c.get(md) or {}
            h = d.get("halves") or [None, None]
            ex = d.get("exits") or {}
            mark = " **(книга)**" if abs(f - bf) < 1e-9 else (" **(главная)**" if abs(f - s["main_floor"]) < 1e-9 else "")
            L_.append(f"| {f:g}{mark} | {_n(d.get('n'))} | {_p(d.get('final'))} | {_p(d.get('max_dd'))} | {_f(d.get('ratio'))} | "
                      f"{_f((c.get(str(int(s['deps'][0]))) or {}).get('ratio'))} | {_f((c.get(str(int(s['deps'][2]))) or {}).get('ratio'))} | "
                      f"{_f((h[0] or {}).get('ratio')) if h[0] else '—'} | {_f((h[1] or {}).get('ratio')) if h[1] else '—'} | "
                      f"{_n(d.get('wo3'))} | {_n(d.get('sigma_day'))} | {ex.get('пол', 0)} | {ex.get('ликвидация', 0)} | "
                      f"{ex.get('тейк', 0)} | {ex.get('срок', 0)} | {ex.get('рынок', 0)} |")
        j = (s["judge"].get("books") or {}).get(bk)
        if j:
            hm, hb = j["halves_main"], j["halves_book"]
            win = (hm[0] or {}).get("from"), (hm[0] or {}).get("to"), (hm[1] or {}).get("from"), (hm[1] or {}).get("to")
            L_ += ["", f"Главная {s['main_floor']:g} против книги {j['book_floor']:g}: $10k {_f(j['ratio_main'])} против {_f(j['ratio_book'])} "
                       f"({'лучше' if j['better_10k'] else 'не лучше'}); все депозиты — {'да' if j['all_deps'] else 'нет'}; "
                       f"обе половины — {'да' if j['both_halves'] else 'нет'}"
                       + (f" (1-я {win[0]}…{win[1]}: {_f((hm[0] or {}).get('ratio'))} против {_f((hb[0] or {}).get('ratio'))}; "
                          f"2-я {win[2]}…{win[3]}: {_f((hm[1] or {}).get('ratio'))} против {_f((hb[1] or {}).get('ratio'))})" if hm[0] and hb[0] else "") + "."]
        L_.append("")
    L_ += ["## Вердикт (из чисел)", "", f"- {s['verdict']}", "",
           "Чего замер не делает: правил книг не меняет; окно одно, веса модели эти часы видели; лучшая ячейка кривой "
           "правилом не назначается — судится объявленная 0.25; у безопасной пол книги 0.10, её строка печатается, не судится.", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--group", action="append", default=None)
    ap.add_argument("--assemble", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    say = lambda *x: print(*x, flush=True)                          # noqa: E731
    smoke = a.limit is not None
    out_dir = os.path.join(R.OUT, "short-floor-smoke") if smoke else None
    sink_dir = os.path.join(S.CACHE_DIR, "floor-smoke" if smoke else "floor")
    if a.assemble:
        s = assemble(out_dir=out_dir)
    else:
        groups = [float(x) for x in a.group] if a.group else None
        s = run(limit=a.limit, log=say, groups=groups, out_dir=out_dir, sink_dir=sink_dir)
    if s.get("error"):
        say(s["error"])
    G.write(s, f"{ART}-smoke" if smoke else ART, report, log=say)
    if not a.no_publish:
        publish("пол капитуляции коротких книг как ось")


if __name__ == "__main__":
    main()
