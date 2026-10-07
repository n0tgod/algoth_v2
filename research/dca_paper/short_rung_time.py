#!/usr/bin/env python3
"""Повтор как ВРЕМЯ, а не размер: продление срока и перенос цели по повторному
выбору модели — в ядре, одним проходом чтения.

Решение владельца 07.10 («давай пункт 1 начинаем»). Сигнал повтора доказан
четырьмя замерами (`cost_gap`, `pick_rule`, `repeat_entry`, `short_rung`),
а оба способа его собрать — вход («одна на имя») и размер (долив при общем
поле, девять форм) — закрыты. Третий канал — время: при повторном выборе
того же имени не добавлять размер, а дать позиции дольше жить и/или
отсчитать цель заново от текущей цены по новому обещанию модели.

Оси объявлены до прогона, группа пола 0.5 (оптимальная и агрессивная),
геометрия и пол книги, окно прохода 48 ч; повтор — первый повторный выбор
имени в первые 24 ч позиции (пока книга её держит):

  ref    — как книга: срок 24 ч;
  t36    — срок 36 ч, если повтор был в первые 24 ч, иначе 24 (главная
           ячейка вместе с t48);
  t48    — срок 48 ч при повторе, иначе 24;
  all48  — срок 48 ч у ВСЕХ позиций (контроль: что делает сам срок);
  tgt    — срок 24 ч, при повторе цель переносится: неподвижный уровень от
           открытия бара повтора по обещанию ПОВТОРА (`rules.take_rule`,
           та же доля ×2, что у входа);
  tgt48  — продление до 48 ч и перенос цели вместе;
  нуль   — к каждой ячейке с повтором три зерна: повтор ЧУЖОЙ позиции
           (перестановка доноров: его задержка и его обещание).

Кандидат (объявлено): ячейка лучше книги по итогу и доходу/просадке у
обеих судимых книг, выше каждого нулевого зерна по доходу/просадке, а
ячейки продления — ещё и выше `all48` (выборочное продление обязано бить
слепое). Четыре варианта на одном окне, разрешение нуля треть: прошедший
— кандидат на запись вперёд, не правило. Книги не трогаются.

Срок ячейки режет окно прохода включительно, как `split_window`: ячейка
24 ч внутри 48-часового окна считает те же бары и обязана совпасть с
кэшем книги (сверка печатается числом). Записи — на диск по мере счёта.

    run research/dca_paper/short_rung_time.py            # ~2.5 ч
    run research/dca_paper/short_rung_time.py --limit 200  # смоук
"""
import argparse
import gc
import os
import random
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
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_rung as SR                                       # noqa: E402
import short_rung_axes as AX                                  # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-short-rung-time"
MAIN_DEP = SR.MAIN_DEP
GROUP = AX.GROUP
BOOKS = AX.BOOKS
NULL_SEEDS = 3
BASE = S.CELL
BOOK_HOLD = float(R.H24_HOLD_H)            # 24
PASS_HOLD = 48.0                           # окно прохода
HOUR = SR.HOUR
KILL_EXITS = SR.KILL_EXITS
# (имя, заголовок, срок при повторе, перенос цели, всем ли)
VARIANTS = (
    ("t36", "срок 36 ч при повторе в первые 24 ч", 36.0, False, False),
    ("t48", "срок 48 ч при повторе в первые 24 ч", 48.0, False, False),
    ("tgt", "перенос цели по обещанию повтора, срок 24 ч", BOOK_HOLD, True, False),
    ("tgt48", "срок 48 ч и перенос цели при повторе", 48.0, True, False),
)
CONTROLS = (("ref", "как книга: срок 24 ч", BOOK_HOLD),
            ("all48", "срок 48 ч у всех позиций (контроль срока)", PASS_HOLD))
EXT_NAMES = ("t36", "t48", "tgt48")        # ячейки продления — судятся и против all48


def null_name(v, i):
    return f"{v}~n{int(i)}"


def all_names(seeds=NULL_SEEDS):
    names = [c[0] for c in CONTROLS] + [v[0] for v in VARIANTS]
    for v in VARIANTS:
        names += [null_name(v[0], i) for i in range(1, int(seeds) + 1)]
    return names


def cells_for(seeds=NULL_SEEDS):
    return [(SR.cell_key(n), BASE[1], BASE[2], BASE[3]) for n in all_names(seeds)]


def repeat_favs(legs):
    """{(имя, момент): обещание выбора} — при двух руках в секунду берётся
    выбор с большим |прогнозом|, как в кассе и в `label`."""
    out = {}
    for g in sorted(legs, key=lambda g: (float(g["at"]), -abs(float(g.get("fwd") or 0.0)))):
        k = SR.pkey(g["sym"], g["at"])
        if k not in out:
            out[k] = float(g.get("fav") or 0.0)
    return out


def first_repeat(reps, key, until_h=BOOK_HOLD):
    """Момент первого повтора в первые `until_h` часов позиции или None."""
    for t in reps.get(key) or []:
        if t <= key[1] + until_h * HOUR:
            return t
    return None


def null_donors(reps, seed, until_h=BOOK_HOLD):
    """Нуль: каждой позиции с повтором — ЧУЖАЯ позиция с повтором (перестановка)."""
    parents = sorted(k for k in reps if first_repeat(reps, k, until_h) is not None)
    donors = list(parents)
    random.Random(7000 + int(seed)).shuffle(donors)
    return dict(zip(parents, donors))


def policy(name, key, reps, favs, nulls):
    """Политика ячейки для позиции `key`."""
    # Окно прохода (48 ч) шире срока книги: «как книга» обязано нести свой
    # срок ЯВНО, иначе ячейка унаследует срок окна (поймано проверкой 07.10).
    as_book = {"adds": [], "hold_h": BOOK_HOLD}
    for cn, _t, hold in CONTROLS:
        if name == cn:
            return {"adds": [], "hold_h": float(hold)}
    base, seed = (name.split("~n", 1) + [None])[:2]
    v = next((x for x in VARIANTS if x[0] == base), None)
    if v is None:
        raise ValueError(f"неизвестная ячейка {name}")
    _n, _t, hold, move, _all = v
    if seed is None:
        t_rep = first_repeat(reps, key)
        fav = favs.get((key[0], round(t_rep, 3))) if t_rep is not None else None
    else:
        donor = (nulls.get(int(seed)) or {}).get(key)
        if donor is None:
            return dict(as_book)
        t_d = first_repeat(reps, donor)
        t_rep = key[1] + (t_d - donor[1])
        fav = favs.get((donor[0], round(t_d, 3)))
    if t_rep is None:
        return dict(as_book)                          # повтора нет — как книга
    pol = {"adds": [], "hold_h": float(hold)}
    if move:
        rule = R.take_rule(fav, "short") if fav is not None else None
        if rule:
            pol["take_events"] = [(float(t_rep), float(rule["frac"]))]
    return pol


def make_adds_of(reps, favs, nulls):
    def adds_of(g, key):
        return policy(SR.name_of(key), SR.pkey(g["sym"], g["at"]), reps, favs, nulls)
    return adds_of


def changed(rec):
    """Позиция, у которой правило ячейки сработало: срок длиннее книги или цель перенесена."""
    return float(rec.get("hold_h") or BOOK_HOLD) > BOOK_HOLD or int(rec.get("take_moves") or 0) > 0


def position_stats(cell_recs, ref_recs, book):
    """Приращение денег позиции от правила (нетто круга) — где оно сработало."""
    ml = R.min_lev_of(book)
    rk = S.BOOKS[book]
    inc, killed, n_pos, longer = [], 0, 0, []
    for key, r in cell_recs.items():
        if key[0] != rk or (r.get("state") or "closed") != "closed":
            continue
        ref = ref_recs.get(key)
        if ref is None or (ref.get("state") or "closed") != "closed":
            continue
        lev = float(r.get("lev") or 0.0)
        if not lev > 0 or (ml is not None and lev < float(ml)):
            continue
        n_pos += 1
        if not changed(r):
            continue
        inc.append(float(r["pnl_net"]) - float(ref["pnl_net"]))
        longer.append((float(r["exit_ts"]) - float(ref["exit_ts"])) / HOUR)
        if r.get("exit") in KILL_EXITS and ref.get("exit") not in KILL_EXITS:
            killed += 1
    if not inc:
        return {"positions": n_pos, "changed": 0, "mean": None, "median": None, "pos_share": None,
                "p5": None, "killed": 0, "extra_h_med": None}
    return {"positions": n_pos, "changed": len(inc), "mean": statistics.fmean(inc),
            "median": statistics.median(inc), "pos_share": sum(1 for x in inc if x > 0) / len(inc),
            "p5": SR._p5(inc), "killed": killed, "extra_h_med": statistics.median(longer)}


def judge(cash, seeds=NULL_SEEDS):
    out = {}
    for v in VARIANTS:
        name = v[0]
        rows, ok_all = {}, True
        for bk in BOOKS:
            ref, cell, blanket = cash["ref"][bk], cash[name][bk], cash["all48"][bk]
            r_ref, r_cell, r_all = SR.ratio_of(ref), SR.ratio_of(cell), SR.ratio_of(blanket)
            nz = [SR.ratio_of(cash[null_name(name, i)][bk]) for i in range(1, int(seeds) + 1)]
            nz = [float(x) for x in nz if x is not None]
            better = (r_cell is not None and r_ref is not None and r_cell > r_ref
                      and float(cell.get("final") or 0) > float(ref.get("final") or 0))
            above_null = bool(nz) and r_cell is not None and all(r_cell > x for x in nz)
            above_all = (name not in EXT_NAMES) or (r_cell is not None and r_all is not None and r_cell > r_all)
            rows[bk] = {"ratio": r_cell, "ratio_ref": r_ref, "ratio_all48": r_all, "null_ratios": nz,
                        "better_than_book": better, "above_null": above_null, "above_all48": above_all,
                        "null_beat": (sum(1 for x in nz if r_cell is not None and x >= r_cell) / len(nz) if nz else None)}
            ok_all = ok_all and better and above_null and above_all
        out[name] = {"books": rows, "candidate": ok_all}
    return out


def verdict(jd):
    cands = [n for n, j in jd.items() if j["candidate"]]
    if not cands:
        return ("нет кандидатов: ни продление срока, ни перенос цели по повтору не лучше книги по итогу и "
                "доходу/просадке у обеих судимых книг с запасом над нулём и над слепым продлением")
    return ("КАНДИДАТ на запись вперёд (не рычаг — четыре варианта на одном окне, разрешение нуля 1/3): "
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
    favs = repeat_favs(legs_)
    nulls = {i: null_donors(reps, i) for i in range(1, int(seeds) + 1)}
    with_rep = sum(1 for k in reps if first_repeat(reps, k) is not None)
    log(f"решений {len(legs_)}, позиций {len(reps)}, с повтором в первые 24 ч {with_rep} "
        f"({with_rep / max(1, len(reps)):.0%}); ячеек {len(all_names(seeds))}, окно прохода {PASS_HOLD:g} ч")
    group = S.floor_groups()[GROUP]
    sink = AX.Sink(sink_dir or os.path.join(S.CACHE_DIR, "rung-time"))
    try:
        _out, tail = S.replay_cells(legs_, cells_for(seeds), src=src, log=log,
                                    adds_of=make_adds_of(reps, favs, nulls), rulers=group,
                                    sink=sink, hold_h=int(PASS_HOLD))
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
    log(f"сверка ref (срок 24 ч внутри окна 48) с кэшем книги — закрытых у обоих {check['compared']}, "
        f"расхождений {check['mismatch']}")
    cash, pos = {}, {}
    for nm in names:
        recs = sink.read(rk, SR.cell_key(nm), data_end)
        st = SR.cash_of(recs, ctx, launch, dep=dep, now=now)
        cash[nm] = {bk: st[bk] for bk in BOOKS if bk in st}
        pos[nm] = {bk: position_stats(recs, ref_recs, bk) for bk in BOOKS}
        if "~n" not in nm:
            log(f"{nm}: " + ", ".join(f"{bk} {SR.ratio_of(cash[nm][bk])} (сделок {cash[nm][bk].get('n')})"
                                      for bk in BOOKS) + f" ({time.time() - t0:.0f} с)")
        del recs
        gc.collect()
    jd = judge(cash, seeds)
    return {"dep": dep, "seeds": int(seeds), "legs": len(legs_), "positions": len(reps),
            "with_repeat": with_rep, "group": GROUP, "books": BOOKS, "pass_hold_h": PASS_HOLD,
            "controls": [list(c[:2]) for c in CONTROLS], "variants": [list(v[:2]) for v in VARIANTS],
            "cash": cash, "positions_stats": pos, "judge": jd, "ref_check": check, "tail": tail,
            "verdict": verdict(jd), "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- отчёт
_p, _pp, _f, _n, _title = SR._p, SR._pp, SR._f, SR._n, SR._title


def _cell_title(name, s):
    for n, t in s["controls"] + s["variants"]:
        if n == name:
            return t
    return name


def report(s):
    if s.get("error"):
        return f"# Повтор как время\n\nОШИБКА: {s['error']}\n"
    chk = s["ref_check"]
    L_ = ["# Повтор как время: продление срока и перенос цели по повторному выбору — ядро лестницы, один проход",
          "",
          f"Решений {s['legs']}, позиций {s['positions']}, с повтором в первые 24 ч {s['with_repeat']} "
          f"({s['with_repeat'] / max(1, s['positions']):.0%}). Группа пола {s['group']:g} "
          f"({', '.join(_title(b) for b in s['books'])}); окно прохода {s['pass_hold_h']:g} ч; касса ${s['dep']:,} "
          f"нетто; нулевых зёрен на вариант {s['seeds']}; посчитано {s['computed_at']} за {s['secs']} с.",
          "",
          f"Сверка «как книга» (срок 24 ч внутри окна 48) с кэшем книги: закрытых у обоих {chk['compared']}, "
          f"расхождений {chk['mismatch']}.",
          ""]
    order = [c[0] for c in s["controls"]] + [v[0] for v in s["variants"]]
    for bk in s["books"]:
        L_ += [f"## {_title(bk)} — по кассе", "",
               "| ячейка | сделок | итог | просадка | доход/просадка | без 3 дней, $ | σ дня, $ | полом/ликв. | нуль: доход/просадка по зёрнам | зёрен не хуже |",
               "|---|--:|--:|--:|--:|--:|--:|--:|---|--:|"]
        for nm in order:
            c = s["cash"][nm][bk]
            j = (s["judge"].get(nm) or {}).get("books", {}).get(bk) or {}
            nz = j.get("null_ratios")
            L_.append(f"| {_cell_title(nm, s)} | {_n(c.get('n'))} | {_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                      f"{_f(SR.ratio_of(c))} | {_n(c.get('wo3'))} | {_n(c.get('sigma_day'))} | {_n(c.get('kill_n'))} | "
                      f"{(', '.join(_f(x) for x in nz) if nz else '—')} | {_pp(j.get('null_beat'))} |")
        L_ += ["", f"### {_title(bk)} — по позициям (приращение денег позиции от правила там, где оно сработало; доли маржи, нетто круга)", "",
               "| ячейка | позиций | сработало | среднее | медиана | плюсовых | худшие 5 % | добито полом/ликв. | дольше книги, ч (медиана) |",
               "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for nm in ["all48"] + [v[0] for v in s["variants"]]:
            p = s["positions_stats"][nm][bk]
            L_.append(f"| {_cell_title(nm, s)} | {_n(p['positions'])} | {_n(p['changed'])} | {_p(p['mean'], 2)} | "
                      f"{_p(p['median'], 2)} | {_pp(p['pos_share'])} | {_p(p['p5'], 1)} | {_n(p['killed'])} | {_f(p['extra_h_med'], 1)} |")
        L_.append("")
    L_ += ["## Суд по вариантам", "",
           "| вариант | лучше книги (обе) | выше всех зёрен нуля (обе) | выше слепого продления (обе) | кандидат |",
           "|---|---|---|---|---|"]
    for v in s["variants"]:
        j = s["judge"][v[0]]
        bb = j["books"]
        yes = lambda k: "да" if all(bb[b][k] for b in s["books"]) else "нет"          # noqa: E731
        L_.append(f"| {v[1]} | {yes('better_than_book')} | {yes('above_null')} | "
                  f"{yes('above_all48') if v[0] in EXT_NAMES else '—'} | {'ДА' if j['candidate'] else 'нет'} |")
    L_ += ["", "## Вердикт (из чисел)", "", f"- {s['verdict']}", "",
           "Чего замер не делает: правил книг не меняет; окно одно, веса модели эти часы видели; четыре варианта на "
           "одном окне — прошедший есть кандидат на запись вперёд, не правило; безопасная не считалась; повторы "
           "после 24-го часа и второе продление не объявлены.", ""]
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
    sink_dir = os.path.join(S.CACHE_DIR, "rung-time-smoke" if smoke else "rung-time")
    s = run(limit=a.limit, log=say, seeds=a.seeds, sink_dir=sink_dir)
    if s.get("error"):
        say(s["error"])
    G.write(s, f"{ART}-smoke" if smoke else ART, report, log=say)
    if not a.no_publish:
        publish("повтор как время: продление срока и перенос цели по повторному выбору")


if __name__ == "__main__":
    main()
