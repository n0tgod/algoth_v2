#!/usr/bin/env python3
"""Книги DCA на СОГЛАСИИ рук: что было бы, если лист брать пересечением.

Вопрос владельца 2026-09-12: «какая была бы статистика всех DCA, если бы
они были построены на книге agreed». Сегодня лист книг пишут ОБЕ руки
модели (деревья и сеть), отбора по руке нет, дубли снимает правило
«одна позиция на имя». Согласная книга S8 берёт другое подмножество —
ПЕРЕСЕЧЕНИЕ выборов.

СОГЛАСИЕ считается ровно так же, как у согласной книги S8
(`s8_loop/train.agree_keys`): решение согласное, если ОБЕ руки выбрали
это имя в этот час на эту сторону. Согласие есть свойство ВЫБОРА, а не
исхода — иначе фильтр знал бы будущее. Выбор с нулевым размером тоже
решение руки: согласие меряет модель, а не кассу.

РЕПЛЕЯ ПО БАРАМ ЗДЕСЬ НЕТ ВОВСЕ. Согласный лист есть ПОДМНОЖЕСТВО
нынешнего, и исход каждого его решения уже посчитан — записи берутся из
кэшей реплея самих семейств. Значит обе ветки считаются на одних и тех
же позициях, и разница чисел есть разница ЛИСТА, а не счёта. Кэш при
этом не переписывается: файл семейства — его собственная память.

КОНТРОЛЬ объявлен ДО прогона и обязателен: согласие РЕЖЕТ число решений,
а книга на меньшем числе решений меняется сама по себе. Поэтому рядом
считается случайная выборка ТОГО ЖЕ размера на `SEEDS` зёрнах, по той же
величине, о которой спор (итог и доход/просадка на среднем депозите).
Одна выборка — сам шум; разрешение доли есть 1/зёрна.

ЧЕГО ЗАМЕР НЕ ГОВОРИТ. Он не заводит книгу: это вопрос «что было бы»,
а не предложение правила. Веса модели эти часы видели, поэтому пересчёт
истории читается как оценка СВЕРХУ — у согласной ветки ровно так же, как
у нынешней. Сравнение с раздельными счетами внутри общего счёта здесь не
считается (журналы книг замер не трогает).

Запуск: `run research/dca_paper/agree_book.py`. Смоук: `--limit 400`.
"""
import argparse
import json
import os
import random
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
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_pair as PR                                         # noqa: E402
import run_d6 as D6                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ARMS = ("gbm", "nn")
ART = "DCA-agree-book"
SEEDS = 200                      # объявлено до прогона
MAIN_DEP = 10000                 # на нём идёт контроль


def agreed_of(legs):
    """Согласные решения листа и состав рук на каждом.

    Ключ решения — (имя, час, сторона): тот же состав, каким согласие
    считает S8. Возвращает (множество согласных, карта «решение → руки»).
    """
    arms = {}
    for g in legs or []:
        try:
            k = (str(g["sym"]), round(float(g["at"]), 3),
                 g.get("side") or "long")
        except (KeyError, TypeError, ValueError):
            continue
        arms.setdefault(k, set()).add(g.get("arm") or "gbm")
    want = set(ARMS)
    return {k for k, a in arms.items() if want.issubset(a)}, arms


def keys_of(cache):
    """Решения кэша: (имя, час, сторона) — по одному на все линейки."""
    out = set()
    for (_rk, sym, at), r in cache.items():
        out.add((str(sym), round(float(at), 3), r.get("side") or "long"))
    return out


def keep(cache, want):
    """Записи кэша, чьё решение попало в `want`. Кэш не меняется."""
    out = {}
    for k, r in cache.items():
        d = (str(k[1]), round(float(k[2]), 3), r.get("side") or "long")
        if d in want:
            out[k] = r
    return out


def packed_long(cache, keys=None):
    """Записи длинных книг по книгам — тем же реестром, что у прогона."""
    keys = list(keys if keys is not None else R.RULER_ORDER)
    by_pair = {}
    for (pr, _sym, _at), r in cache.items():
        by_pair.setdefault(tuple(pr), []).append(r)
    return {k: list(by_pair.get(tuple(RP.RULERS[k])) or []) for k in keys}


def packed_short(cache):
    """Записи коротких книг по книгам семейства `h24`."""
    by_ruler = {}
    for (rk, _sym, _at), r in cache.items():
        by_ruler.setdefault(rk, []).append(r)
    return {bk: list(by_ruler.get(rk) or []) for bk, rk in S.BOOKS.items()}


def stats_of(packed, ctx, launch, keys, deps=None, now=None):
    """Книги на этих записях — ТЕМ ЖЕ ядром, что считает прогон."""
    return G.cell_stats(packed, ctx, launch, now=now, keys=keys,
                        deps=(deps if deps is not None else R.DEPOSITS))


def control(cache, all_keys_, n_keep, packer, ctx, launch, keys, seeds=SEEDS,
            dep=MAIN_DEP, now=None, log=print):
    """Случайные выборки ТОГО ЖЕ размера: фильтр против своей же доли.

    Выбирается РЕШЕНИЕ, а не запись: одно решение кормит все линейки
    сразу, и выборка по записям дала бы книгам разные составы по чужой
    причине.
    """
    pool = sorted(all_keys_)
    out = {}
    if n_keep <= 0 or n_keep >= len(pool):
        return {"why": "выборка того же размера невозможна: согласных "
                       f"{n_keep} при {len(pool)} решениях"}
    t0 = time.time()
    for i in range(int(seeds)):
        rnd = random.Random(1000 + i)
        want = set(rnd.sample(pool, n_keep))
        st = stats_of(packer(keep(cache, want)), ctx, launch, keys,
                      deps=[dep], now=now)
        for bk in keys:
            c = st.get(f"{bk}:{int(dep)}") or {}
            out.setdefault(bk, []).append({"final": c.get("final"),
                                           "ratio": c.get("ratio"),
                                           "n": c.get("n")})
        if i and i % 50 == 0:
            log(f"контроль: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    return out


def beat_share(draws, value, field):
    """Доля зёрен, у которых случайная выборка не хуже названной величины."""
    vals = [d.get(field) for d in (draws or []) if d.get(field) is not None]
    if not vals or value is None:
        return None, len(vals)
    n = sum(1 for x in vals if float(x) >= float(value))
    return round(n / len(vals), 3), len(vals)


def live_of(path, keys, dep=MAIN_DEP):
    """Числа ЖИВОЙ книги из её свода — для сверки с веткой «обе руки».

    Ветка «обе руки» обязана воспроизводить живую книгу: она считается
    на том же кэше теми же правилами. Разойдись они — замер отвечает не
    про ту книгу, что стоит на странице, и молчать об этом нельзя.
    Сверка идёт ЧИСЛОМ и едет в отчёт, а не остаётся в логе.
    """
    try:
        with open(path, encoding="utf-8") as f:
            a = json.load(f)
    except (OSError, ValueError) as e:                      # noqa: BLE001
        return {"why": f"свод не прочитан: {str(e)[:80]}"}
    out = {}
    for bk in keys:
        b = ((a.get("books") or {}).get(f"{bk}:{int(dep)}") or {})
        st = b.get("all") or {}
        if st:
            out[bk] = {"n": st.get("n"), "usd": st.get("usd"),
                       "final": st.get("final"), "max_dd": st.get("max_dd")}
    return out


def run_family(name, cache, legs_, packer, keys, ctx, launch, seeds=SEEDS,
               now=None, log=print, live_path=None):
    """Одна семья книг: обе ветки листа, состав решений и контроль."""
    agreed, arms_map = agreed_of(legs_)
    have = keys_of(cache)
    mine = have & agreed
    st_all = stats_of(packer(cache), ctx, launch, keys, now=now)
    st_ag = stats_of(packer(keep(cache, mine)), ctx, launch, keys, now=now)
    log(f"{name}: решений в кэше {len(have)}, согласных {len(mine)} "
        f"({100.0 * len(mine) / max(1, len(have)):.1f} %)")
    ctl = control(cache, have, len(mine), packer, ctx, launch, keys,
                  seeds=seeds, now=now, log=log) if seeds else {}
    live = live_of(live_path, keys) if live_path else {}
    return {"name": name, "keys": list(keys),
            "decisions": len(have), "agreed": len(mine),
            "legs": len(legs_ or []),
            "one_arm": sum(1 for k, a in arms_map.items() if len(a) == 1),
            "all": st_all, "agree": st_ag, "control": ctl, "live": live}


def run_pair_family(long_cache, short_cache, long_keep, short_keep, tmp,
                    launch, now=None, log=print):
    """Общий счёт: те же кэши, но урезанные согласием. Журнал — временный.

    Книги общего счёта считает ИХ прогон (`run_pair.run`), а не копия
    его правил: связь сторон, гейты и билет стороны живут внутри него.
    """
    out = {}
    for br, (lc, sc) in (("all", (long_cache, short_cache)),
                         ("agree", (long_keep, short_keep))):
        jp = os.path.join(tmp, f"pair-{br}.jsonl")
        s = PR.run(log=log, now=now, journal=jp, long_cache=lc,
                   short_cache=sc, launch=launch,
                   long_journal=os.path.join(tmp, f"long-{br}.jsonl"),
                   short_journal=os.path.join(tmp, f"short-{br}.jsonl"))
        if s.get("error"):
            return {"error": s["error"]}
        got = {}
        for pk in R.PAIR_ORDER:
            for dep in R.DEPOSITS:
                b = (s.get("books") or {}).get(RP._cell(pk, dep)) or {}
                a = b.get("all") or {}
                fin, dd = a.get("final"), a.get("max_dd")
                got[f"{pk}:{int(dep)}"] = {
                    "n": a.get("n"), "usd": a.get("usd"), "final": fin,
                    "max_dd": dd, "day_median": a.get("day_median"),
                    "days": a.get("days_rows"),
                    "ratio": (None if not fin or not dd
                              else round(float(fin) / abs(float(dd)), 2))}
        out[br] = got
    return {"name": "общий счёт", "keys": list(R.PAIR_ORDER),
            "all": out["all"], "agree": out["agree"], "control": {}}


def run(limit=None, seeds=SEEDS, log=print, now=None, launch=None, ctx=None,
        tmp=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    lcache, why_l = RP.read_cache()
    scache, why_s = S.read_cache(log=log)
    if why_l or why_s:
        why = why_l or why_s
        log(f"замер не считается: {why}")
        return {"error": f"кэш реплея непригоден: {why}"}
    llegs = D6.gated_legs(limit=limit, side="long", log=log)
    slegs = S.legs(limit=limit, log=log)
    fams = [run_family("длинные книги", lcache, llegs, packed_long,
                       list(R.RULER_ORDER), ctx, launch, seeds=seeds,
                       now=now, log=log, live_path=R.ARTIFACT),
            run_family("короткие книги h24", scache, slegs, packed_short,
                       list(R.H24_ORDER), ctx, launch, seeds=seeds,
                       now=now, log=log, live_path=R.H24_ARTIFACT)]
    # Общий счёт считается СВОИМ прогоном на тех же урезанных кэшах.
    import tempfile
    tmp = tmp or tempfile.mkdtemp(prefix="agree-")
    lag, _a = agreed_of(llegs)
    sag, _b = agreed_of(slegs)
    pair = run_pair_family(lcache, scache, keep(lcache, lag),
                           keep(scache, sag), tmp, launch, now=now, log=log)
    if not pair.get("error"):
        fams.append(pair)
    else:
        log(f"общий счёт не посчитан: {pair['error']}")
    return {"families": fams, "pair_error": pair.get("error"),
            "seeds": int(seeds), "main_dep": MAIN_DEP,
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _r(x):
    return "—" if x is None else f"{float(x):.2f}"


def _days_map(cell):
    """Деньги по суткам одной книги: дата → доллары."""
    out = {}
    for r in (cell or {}).get("days") or []:
        try:
            out[str(r["d"])] = float(r["usd"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _day_table(s, dep, last=7):
    """Последние сутки обеих веток по каждой книге, рядом."""
    rows, dates = [], set()
    for f in s.get("families") or []:
        for bk in f.get("keys") or []:
            a = _days_map((f.get("all") or {}).get(f"{bk}:{dep}"))
            g = _days_map((f.get("agree") or {}).get(f"{bk}:{dep}"))
            if not a and not g:
                continue
            rows.append((bk, a, g))
            dates |= set(a) | set(g)
    if not rows:
        return []
    ks = sorted(dates)[-int(last):]
    L = ["| книга | ветка | " + " | ".join(ks) + " |",
         "|---|---|" + "--:|" * len(ks)]
    for bk, a, g in rows:
        for ttl, m in (("обе руки", a), ("согласие", g)):
            L.append(f"| {R.ruler_title(bk)} | {ttl} | "
                     + " | ".join("—" if m.get(k) is None
                                  else f"{m[k]:+.0f}" for k in ks) + " |")
    return L + [""]


def report(s):
    L = ["# Книги DCA на согласии рук: что было бы", "",
         "Вопрос владельца 2026-09-12: «какая была бы статистика всех DCA, "
         "если бы они были построены на книге agreed». Лист книг сегодня "
         "пишут ОБЕ руки модели, отбора по руке нет. Согласная ветка "
         "берёт ПЕРЕСЕЧЕНИЕ: решение идёт в книгу, только если обе руки "
         "выбрали это имя в этот час на эту сторону — то же правило, по "
         "которому живёт согласная книга S8, и считается оно по ВЫБОРАМ, "
         "а не по исходам.", "",
         "Реплея по барам здесь нет: согласный лист есть подмножество "
         "нынешнего, исходы взяты из кэшей реплея самих семейств. Обе "
         "ветки считаются на ОДНИХ И ТЕХ ЖЕ позициях теми же правилами "
         "книг — разница чисел есть разница листа, а не счёта.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}. "
              "Числа ниже брутто.", ""]
    if s.get("pair_error"):
        L += [f"**Общий счёт не посчитан:** {s['pair_error']}.", ""]
    L += ["## Сколько решений остаётся", "",
          "| семья | решений листа | из них согласных | доля | "
          "решений одной руки |", "|---|--:|--:|--:|--:|"]
    for f in s.get("families") or []:
        if f.get("decisions") is None:
            continue
        d, a = f.get("decisions") or 0, f.get("agreed") or 0
        L.append(f"| {f['name']} | {d} | {a} | "
                 f"{100.0 * a / max(1, d):.1f} % | {f.get('one_arm', '—')} |")
    L += ["", "Решение — это (имя, час, сторона): одно решение кормит все "
          "книги семьи сразу. У общего счёта состав считает его "
          "собственный прогон на тех же урезанных кэшах.", ""]
    dep = int(s.get("main_dep") or MAIN_DEP)
    rows = []
    for f in s.get("families") or []:
        live = f.get("live") or {}
        if live.get("why"):
            rows.append(f"| {f['name']} | — | — | {live['why']} |")
            continue
        for bk in f.get("keys") or []:
            lv, br = live.get(bk), (f.get("all") or {}).get(f"{bk}:{dep}")
            if not lv or not br:
                continue
            d = (None if lv.get("usd") is None or br.get("usd") is None
                 else float(br["usd"]) - float(lv["usd"]))
            rows.append(
                f"| {R.ruler_title(bk)} | {lv.get('n')} / {br.get('n')} | "
                f"{_u(lv.get('usd'))} / {_u(br.get('usd'))} | "
                + ("—" if d is None else f"{d:+.2f}") + " |")
    if rows:
        L += ["## Сверка ветки «обе руки» с живой книгой", "",
              f"Ветка «обе руки» обязана воспроизводить живую книгу: тот "
              f"же кэш, те же правила, депозит ${dep}. Расхождение "
              "значит, что замер отвечает не про ту книгу, что стоит на "
              "странице, — и тогда числа ниже читать нельзя.", "",
              "| книга | сделок: живая / замер | Σ $: живая / замер | "
              "разница |", "|---|--:|--:|--:|"] + rows + [""]
    for f in s.get("families") or []:
        L += [f"## {f['name'].capitalize()}", "",
              "| книга | депозит | ветка | сделок | Σ $ | итог | просадка | "
              "доход/просадка |", "|---|--:|---|--:|--:|--:|--:|--:|"]
        for bk in f.get("keys") or []:
            for d in R.DEPOSITS:
                for br, ttl in (("all", "обе руки"), ("agree", "согласие")):
                    c = (f.get(br) or {}).get(f"{bk}:{int(d)}") or {}
                    if not c:
                        continue
                    L.append(f"| {R.ruler_title(bk)} | ${int(d)} | {ttl} | "
                             f"{c.get('n', '—')} | {_u(c.get('usd'))} | "
                             f"{_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                             f"{_r(c.get('ratio'))} |")
        L.append("")
        ctl = f.get("control") or {}
        if ctl.get("why"):
            L += [f"**Контроля нет:** {ctl['why']}.", ""]
            continue
        if not ctl:
            continue
        L += [f"**Контроль — случайная выборка того же размера**, "
              f"{s.get('seeds')} зёрен, депозит ${dep}. Доля зёрен, у "
              "которых СЛУЧАЙНЫЙ лист не хуже согласного: если она "
              "велика, работает размер выборки, а не согласие.", "",
              "| книга | согласие: итог | случайные: медиана | "
              "доля зёрен не хуже | согласие: доход/просадка | "
              "доля зёрен не хуже |", "|---|--:|--:|--:|--:|--:|"]
        for bk in f.get("keys") or []:
            c = (f.get("agree") or {}).get(f"{bk}:{dep}") or {}
            draws = ctl.get(bk) or []
            fins = sorted(x["final"] for x in draws
                          if x.get("final") is not None)
            med = fins[len(fins) // 2] if fins else None
            sh_f, n_f = beat_share(draws, c.get("final"), "final")
            sh_r, n_r = beat_share(draws, c.get("ratio"), "ratio")
            L.append(f"| {R.ruler_title(bk)} | {_p(c.get('final'))} | "
                     f"{_p(med)} | "
                     + ("—" if sh_f is None else f"{100 * sh_f:.0f} % "
                                                 f"из {n_f}") + " | "
                     + _r(c.get("ratio")) + " | "
                     + ("—" if sh_r is None else f"{100 * sh_r:.0f} % "
                                                 f"из {n_r}") + " |")
        L.append("")
    L += [f"## Последние сутки: обе ветки рядом (депозит ${dep})", "",
          "Итог месяца молчит о том, КОГДА книга потеряла. Здесь деньги "
          "каждого дня у обеих веток: согласный лист либо проходит "
          "плохой день мягче, либо теряет так же — и это разные ответы "
          "на вопрос, зачем он нужен.", ""]
    days = _day_table(s, dep)
    L += days if days else ["Дней у веток нет: разбивка по суткам не "
                            "посчитана.", ""]
    L += ["## Как читать", "",
          "- Согласие РЕЖЕТ число решений, а книга на меньшем листе "
          "меняется сама по себе: случайная выборка того же размера "
          "стоит рядом именно поэтому. Правилом согласие становится "
          "только если оно бьёт свою же долю на большинстве зёрен.",
          "- Веса модели видели эти часы у ОБЕИХ веток одинаково: "
          "сравнение честное, но обе ветки — оценка сверху.",
          "- Книга здесь не заводится: это ответ на «что было бы», а не "
          "предложение правила.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="книги DCA на согласии рук")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    s = run(limit=a.limit, seeds=a.seeds)
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("книги DCA на согласии рук: что было бы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
