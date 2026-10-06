#!/usr/bin/env python3
"""Три оси долива по повторному выбору — в ядре, одним проходом чтения.

Решение владельца 06.10 («давай замерим 3 эти оси») после замера
`short_rung`: вторая ступень 0.25 на первом повторе при поле книги хуже
книги (оптимальная 2.77 → 1.43, агрессивная 2.44 → 1.26) — общий пол
добивает 13–21 % позиций, хотя сигнал повтора настоящий (прирост на
позицию +0.6…0.8 % маржи против −0.3…−0.6 у нуля). Вопрос: есть ли форма
долива, которую пол не добивает.

Оси объявлены до прогона, все на геометрии книги (`fence:none:t2`), на
группе пола 0.5 — линейке оптимальной и агрессивной (судимые книги;
безопасная в этот замер не входит: её пол 0.1 и ей доливы вредят размером):

  ref        — как книга;
  r2         — 0.25 на первом повторе, пол книги (база, повтор `short_rung`);
  A, доля:   w05, w10 — 0.05 / 0.10 на первом повторе;
  B, порог:  p10, p25, p50 — 0.25 на первом повторе, при котором pnl
             позиции по открытию бара выше +10 / +25 / +50 % маржи;
  C, пол:    f25, f10 — 0.25 на первом повторе при поле 0.25 / 0.10
             вместо 0.5; рядом f25_ref, f10_ref — тот же пол БЕЗ долива,
             чтобы отделить вклад пола от вклада долива;
  нуль:      к каждой ячейке с доливом — три зерна той же политики с
             повторами ЧУЖОЙ позиции (перестановка задержек).

Кандидат (объявлено): ячейка лучше книги `ref` по итогу И доходу/просадке
у обеих судимых книг и выше каждого своего нулевого зерна по
доходу/просадке; у ячеек пола — ещё и лучше своего `*_ref`. Восемь
вариантов на одном окне: один прошедший при разрешении нуля в треть —
кандидат на запись вперёд, не рычаг (R5). Правила книг не меняются.

Память и время. Ячеек 35 × 5.5 тыс. решений в памяти не живут: записи
уходят на диск по мере счёта (`collect(sink=…)`, каталог кэша вне
публикации), касса читает ячейку за ячейкой. Чтение ленты — один проход
(~2 ч); ячейки добавляют только симуляции.

    run research/dca_paper/short_rung_axes.py            # ~2.5 ч
    run research/dca_paper/short_rung_axes.py --limit 200  # смоук
"""
import argparse
import gc
import json
import os
import random
import re
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
import run_d6 as D6                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_rung as SR                                       # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-rung-axes"
MAIN_DEP = SR.MAIN_DEP
GROUP = 0.5
BOOKS = [bk for bk in SR.BOOK_KEYS if R.floor_frac_of(bk, 0.1) == GROUP]      # optimal_h, aggr_h
NULL_SEEDS = 3
BASE = S.CELL
W = SR.ADD_W                                        # 0.25
# (имя, заголовок, доля, порог прибыли, пол ячейки|None, долив есть)
VARIANTS = (
    ("r2", "0.25 на первом повторе, пол книги", W, None, None, True),
    ("w05", "доля 0.05 на первом повторе", 0.05, None, None, True),
    ("w10", "доля 0.10 на первом повторе", 0.10, None, None, True),
    ("p10", "0.25 на первом повторе при pnl > +10 % маржи", W, 0.10, None, True),
    ("p25", "0.25 на первом повторе при pnl > +25 % маржи", W, 0.25, None, True),
    ("p50", "0.25 на первом повторе при pnl > +50 % маржи", W, 0.50, None, True),
    ("f25", "0.25 на первом повторе, пол 0.25", W, None, 0.25, True),
    ("f10", "0.25 на первом повторе, пол 0.10", W, None, 0.10, True),
)
REFS = (("ref", "как книга: без доливов, пол 0.5", None),
        ("f25_ref", "без доливов, пол 0.25", 0.25),
        ("f10_ref", "без доливов, пол 0.10", 0.10))
AXES = (("A — доля долива", ("r2", "w10", "w05")),
        ("B — порог прибыли", ("r2", "p10", "p25", "p50")),
        ("C — пол", ("ref", "r2", "f25_ref", "f25", "f10_ref", "f10")))
FLOOR_REF = {"f25": "f25_ref", "f10": "f10_ref"}
KILL_EXITS = SR.KILL_EXITS


def null_name(v, i):
    return f"{v}~n{int(i)}"


def all_names(seeds=NULL_SEEDS):
    names = [r[0] for r in REFS] + [v[0] for v in VARIANTS]
    for v in VARIANTS:
        names += [null_name(v[0], i) for i in range(1, int(seeds) + 1)]
    return names


def cells_for(seeds=NULL_SEEDS):
    return [(SR.cell_key(n), BASE[1], BASE[2], BASE[3]) for n in all_names(seeds)]


def null_offsets_all(reps, seed):
    """Нуль: ВСЕ задержки повторов чужой позиции (перестановка доноров)."""
    parents = sorted(k for k, v in reps.items() if v)
    donors = list(parents)
    random.Random(7000 + int(seed)).shuffle(donors)
    out = {}
    for k, d in zip(parents, donors):
        out[k] = [k[1] + (t - d[1]) for t in reps[d]]
    return out


def policy(name, key, reps, nulls):
    """Политика ячейки для позиции `key` — словарь ядра или None."""
    for rn, _t, floor in REFS:
        if name == rn:
            return {"adds": [], "floor_frac": floor} if floor is not None else None
    base, seed = (name.split("~n", 1) + [None])[:2]
    v = next((x for x in VARIANTS if x[0] == base), None)
    if v is None:
        raise ValueError(f"неизвестная ячейка {name}")
    _n, _t, share, min_profit, floor, _has = v
    times = (nulls.get(int(seed), {}).get(key) if seed is not None else reps.get(key)) or []
    if not times:
        return {"adds": [], "floor_frac": floor} if floor is not None else None
    cands = times if min_profit is not None else times[:1]
    pol = {"adds": [(t, share) for t in cands], "max": 1}
    if min_profit is not None:
        pol["min_profit"] = float(min_profit)
    if floor is not None:
        pol["floor_frac"] = float(floor)
    return pol


def make_adds_of(reps, nulls):
    def adds_of(g, key):
        return policy(SR.name_of(key), SR.pkey(g["sym"], g["at"]), reps, nulls)
    return adds_of


# ---------------------------------------------------------------- диск
def safe_name(cell_key):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cell_key)


class Sink:
    """Записи по ячейкам — на диск по мере счёта, по файлу на (линейка, ячейка)."""

    def __init__(self, root):
        self.root, self.fh, self.n = root, {}, 0
        os.makedirs(root, exist_ok=True)

    def path(self, rk, key):
        return os.path.join(self.root, f"{rk}__{safe_name(key)}.jsonl")

    def __call__(self, rk, key, rec):
        p = self.path(rk, key)
        f = self.fh.get(p)
        if f is None:
            f = self.fh[p] = open(p, "w", encoding="utf-8")
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.n += 1

    def close(self):
        for f in self.fh.values():
            f.close()
        self.fh = {}

    def read(self, rk, key, data_end):
        p = self.path(rk, key)
        out = {}
        if not os.path.exists(p):
            return out
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                r = json.loads(ln)
                r["state"] = D6.position_state(r, data_end)
                out[(rk, r["sym"], round(float(r["at"]), 3))] = r
        return out


def ratio_of(c):
    return SR.ratio_of(c)


def judge(cash, pos, seeds=NULL_SEEDS):
    """По каждому варианту: лучше книги? выше всех нулевых зёрен? лучше своего пола?"""
    out = {}
    for v in VARIANTS:
        name = v[0]
        rows = {}
        ok_all = True
        for bk in BOOKS:
            ref, cell = cash["ref"][bk], cash[name][bk]
            r_ref, r_cell = ratio_of(ref), ratio_of(cell)
            nz = [ratio_of(cash[null_name(name, i)][bk]) for i in range(1, int(seeds) + 1)]
            nz = [float(x) for x in nz if x is not None]
            fr = FLOOR_REF.get(name)
            r_fr = ratio_of(cash[fr][bk]) if fr else None
            better = (r_cell is not None and r_ref is not None and r_cell > r_ref
                      and float(cell.get("final") or 0) > float(ref.get("final") or 0))
            above_null = bool(nz) and r_cell is not None and all(r_cell > x for x in nz)
            better_floor = (r_fr is None) or (r_cell is not None and r_cell > r_fr
                                              and float(cell.get("final") or 0) > float(cash[fr][bk].get("final") or 0))
            rows[bk] = {"ratio": r_cell, "ratio_ref": r_ref, "ratio_floor_ref": r_fr, "null_ratios": nz,
                        "better_than_book": better, "above_null": above_null, "better_than_floor_ref": better_floor,
                        "null_beat": (sum(1 for x in nz if r_cell is not None and x >= r_cell) / len(nz) if nz else None)}
            ok_all = ok_all and better and above_null and better_floor
        out[name] = {"books": rows, "candidate": ok_all}
    return out


def verdict(jd):
    cands = [n for n, j in jd.items() if j["candidate"]]
    if not cands:
        return ("нет кандидатов: ни одна из восьми форм долива не лучше книги по итогу и доходу/просадке "
                "у обеих судимых книг с запасом над нулём")
    return ("КАНДИДАТ на запись вперёд (не рычаг — восемь вариантов на одном окне, разрешение нуля 1/3): "
            + ", ".join(cands))


def run(limit=None, src=None, log=print, legs_=None, ctx=None, launch=None, now=None,
        seeds=NULL_SEEDS, mem_limit=None, dep=MAIN_DEP, sink_dir=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        return {"error": "коротких решений на листе нет"}
    reps = SR.repeats_of(legs_)
    nulls = {i: null_offsets_all(reps, i) for i in range(1, int(seeds) + 1)}
    with_rep = sum(1 for v in reps.values() if v)
    offs_h = sorted((v[0] - k[1]) / SR.HOUR for k, v in reps.items() if v)
    log(f"решений {len(legs_)}, позиций {len(reps)}, с повтором в срок {with_rep} "
        f"({with_rep / max(1, len(reps)):.0%}); медиана задержки первого повтора "
        f"{(offs_h[len(offs_h) // 2] if offs_h else float('nan')):.1f} ч; ячеек {len(all_names(seeds))}")
    group = S.floor_groups()[GROUP]
    sink = Sink(sink_dir or os.path.join(S.CACHE_DIR, "rung-axes"))
    try:
        _out, tail = S.replay_cells(legs_, cells_for(seeds), src=src, log=log,
                                    adds_of=make_adds_of(reps, nulls), rulers=group, sink=sink)
    finally:
        sink.close()
    data_end = float((tail or {}).get("data_end") or 0.0)
    log(f"записей на диске {sink.n}, конец записи {time.strftime('%Y-%m-%d %H:%M', time.gmtime(data_end))} UTC "
        f"({time.time() - t0:.0f} с)")
    names = all_names(seeds)
    rk = group[0]
    ref_recs = sink.read(rk, SR.cell_key("ref"), data_end)
    cache, _why = S.read_cache(log=log)
    check = SR.ref_check(ref_recs, cache or {})
    log(f"сверка ref с кэшем книги — закрытых у обоих {check['compared']}, расхождений {check['mismatch']}")
    cash, pos = {}, {}
    for nm in names:
        recs = sink.read(rk, SR.cell_key(nm), data_end)
        st = SR.cash_of(recs, ctx, launch, dep=dep, now=now)
        cash[nm] = {bk: st[bk] for bk in BOOKS if bk in st}
        pos[nm] = {bk: SR.position_stats(recs, ref_recs, bk) for bk in BOOKS}
        if "~n" not in nm:
            log(f"{nm}: " + ", ".join(f"{bk} {ratio_of(cash[nm][bk])} (сделок {cash[nm][bk].get('n')})"
                                      for bk in BOOKS) + f" ({time.time() - t0:.0f} с)")
        del recs
        gc.collect()
    jd = judge(cash, pos, seeds)
    return {"dep": dep, "seeds": int(seeds), "legs": len(legs_), "positions": len(reps),
            "with_repeat": with_rep, "offset_med_h": (offs_h[len(offs_h) // 2] if offs_h else None),
            "group": GROUP, "books": BOOKS, "variants": [list(v[:2]) for v in VARIANTS],
            "refs": [list(r[:2]) for r in REFS], "axes": [[a, list(n)] for a, n in AXES],
            "cash": cash, "positions_stats": pos, "judge": jd, "ref_check": check, "tail": tail,
            "slip_bp": CO.SLIP_BP, "verdict": verdict(jd), "computed_at": G.stamp(),
            "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- отчёт
_p, _pp, _f, _n, _title = SR._p, SR._pp, SR._f, SR._n, SR._title


def _cell_title(name, s):
    for n, t in s["refs"] + s["variants"]:
        if n == name:
            return t
    return name


def report(s):
    if s.get("error"):
        return f"# Три оси долива\n\nОШИБКА: {s['error']}\n"
    chk = s["ref_check"]
    L_ = ["# Три оси долива по повторному выбору: доля, порог прибыли, пол — ядро лестницы, один проход",
          "",
          f"Решений {s['legs']}, позиций {s['positions']}, с повтором в срок {s['with_repeat']} "
          f"({s['with_repeat'] / max(1, s['positions']):.0%}); медиана задержки первого повтора "
          f"{_f(s['offset_med_h'], 1)} ч. Группа пола {s['group']:g} ({', '.join(_title(b) for b in s['books'])}); "
          f"касса ${s['dep']:,} нетто; нулевых зёрен на вариант {s['seeds']}; проскальзывание доливов "
          f"{s['slip_bp']} б.п.; посчитано {s['computed_at']} за {s['secs']} с.",
          "",
          f"Сверка «как книга» с кэшем книги: закрытых у обоих {chk['compared']}, расхождений {chk['mismatch']}.",
          ""]
    for bk in s["books"]:
        for axis, names in s["axes"]:
            L_ += [f"## {_title(bk)} — ось {axis}, по кассе", "",
                   "| ячейка | сделок | итог | просадка | доход/просадка | без 3 дней, $ | σ дня, $ | полом/ликв. | нуль: доход/просадка по зёрнам | зёрен не хуже |",
                   "|---|--:|--:|--:|--:|--:|--:|--:|---|--:|"]
            for nm in names:
                c = s["cash"][nm][bk]
                j = (s["judge"].get(nm) or {}).get("books", {}).get(bk) or {}
                nz = j.get("null_ratios")
                L_.append(f"| {_cell_title(nm, s)} | {_n(c.get('n'))} | {_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                          f"{_f(ratio_of(c))} | {_n(c.get('wo3'))} | {_n(c.get('sigma_day'))} | {_n(c.get('kill_n'))} | "
                          f"{(', '.join(_f(x) for x in nz) if nz else '—')} | {_pp(j.get('null_beat'))} |")
            L_.append("")
        L_ += [f"### {_title(bk)} — по позициям (приращение денег позиции от долива, доли маржи, нетто круга)", "",
               "| ячейка | позиций | с доливом | среднее | медиана | плюсовых | худшие 5 % | добито доливом |",
               "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for v in s["variants"]:
            p = s["positions_stats"][v[0]][bk]
            L_.append(f"| {v[1]} | {_n(p['positions'])} | {_n(p['adds'])} | {_p(p['mean'], 2)} | {_p(p['median'], 2)} | "
                      f"{_pp(p['pos_share'])} | {_p(p['p5'], 1)} | {_n(p['killed'])} |")
        L_.append("")
    L_ += ["## Суд по вариантам", "", "| вариант | лучше книги (обе) | выше всех зёрен нуля (обе) | лучше своего пола (обе) | кандидат |",
           "|---|---|---|---|---|"]
    for v in s["variants"]:
        j = s["judge"][v[0]]
        bb = j["books"]
        yes = lambda k: "да" if all(bb[b][k] for b in s["books"]) else "нет"          # noqa: E731
        L_.append(f"| {v[1]} | {yes('better_than_book')} | {yes('above_null')} | "
                  f"{yes('better_than_floor_ref') if v[0] in FLOOR_REF else '—'} | {'ДА' if j['candidate'] else 'нет'} |")
    L_ += ["", "## Вердикт (из чисел)", "", f"- {s['verdict']}", "",
           "Чего замер не делает: правил книг не меняет; окно одно, веса модели эти часы видели; восемь вариантов на "
           "одном окне — прошедший вариант есть кандидат на запись вперёд, не правило; безопасная не считалась "
           "(её пол 0.1 и доливы ей вредят размером, 06.10).", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seeds", type=int, default=NULL_SEEDS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    say = lambda *x: print(*x, flush=True)                          # noqa: E731
    smoke = a.limit is not None
    sink_dir = os.path.join(S.CACHE_DIR, "rung-axes-smoke" if smoke else "rung-axes")
    s = run(limit=a.limit, log=say, seeds=a.seeds, sink_dir=sink_dir)
    if s.get("error"):
        say(s["error"])
    G.write(s, f"{ART}-smoke" if smoke else ART, report, log=say)
    if not a.no_publish:
        publish("три оси долива по повторному выбору: доля, порог прибыли, пол")


if __name__ == "__main__":
    main()
