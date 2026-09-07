#!/usr/bin/env python3
"""Разрез бумажных DCA-книг ПО РУКЕ МОДЕЛИ: деревья (`gbm`) и сеть (`nn`).

Вопрос владельца 2026-09-07: «у DCA лонг используются сигналы ml или ai,
или обе?» По построению — обе. Вход книги DCA не изобретается: первый
рунг открывает выбор ситуационной книги `sit` (спека 14 §D2), а лист
сечения пишется ДВУМЯ руками сразу (`s8_loop/train.ARMS`: бустинг
деревьев и нейросеть на numpy — в проекте они и названы «деревья» и
«сеть»), обе руки ложатся в один журнал листов, и ноги DCA берутся из
него без отбора по руке (`run_d6.gated_legs`).

Но СКОЛЬКО денег принесла каждая рука, журнал книги не знает: рука
теряется при сборке позиции — `run_d6.one_position` её в запись не
кладёт. Ответ «обе» без числа — ровно то, что проект запрещает себе
считать измерением, поэтому рука восстанавливается здесь.

Как восстанавливается. Нога журнала листов несёт руку, имя, сторону и
момент решения; строка журнала книги — имя, сторону, момент и деньги.
Соединяем по (имя, сторона, момент):

- имя в этот момент выбрала ОДНА рука — она и автор;
- выбрали ОБЕ — правило книги `one_per_name` берёт ногу с БОЛЬШИМ
  модулем прогноза (сортировка `(int(at), -fwd)`), она и автор;
- модули прогноза равны — «неразрешимо», отдельным числом;
- ноги нет вовсе — «решения нет» (журнал листов начат позже книги либо
  лист потерян), тоже отдельным числом.

Чего замер НЕ говорит. Он не сравнивает руки на одном составе: составы
разные по построению, и рука, чьих решений больше, тем самым имеет
больше и денег. Он не судит правило «брать только одну руку» — такой
книги не было; половины окна считаются здесь именно затем, чтобы такую
мысль было чем проверять. Деньги — брутто журнала (издержки меряет
`costs.py`; они пропорциональны обороту и знак разреза не переставляют,
но и не вычтены).

Запуск: run research/dca_paper/arm_split.py
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

ARMS = ("gbm", "nn")
ARM_TITLE = {"gbm": "деревья", "nn": "сеть"}
MAIN_DEP = 10000                      # таблица показа; json — по всем
N_MIN = 30                            # меньше — вердикта нет


def arm_title(arm):
    return ARM_TITLE.get(arm, str(arm))


def key_of(sym, side, at):
    """Ключ соединения: имя, сторона, момент решения с точностью записи.

    Момент листа округлён до десятой секунды при записи (`written_at`),
    и позиция несёт его же — но через float, поэтому ключ округляется
    ЯВНО в обоих концах, а не полагается на побитовое равенство.
    """
    return (str(sym), str(side or "long"), round(float(at), 1))


def legs_index(legs):
    """(имя, сторона, момент) → список (рука, модуль прогноза)."""
    idx = {}
    for g in legs:
        k = key_of(g.get("sym"), g.get("side") or "long", g.get("at") or 0)
        idx.setdefault(k, []).append(((g.get("arm") or "gbm"),
                                      abs(float(g.get("fwd") or 0))))
    return idx


def author(cands):
    """Рука-автор решения и причина, если её нет.

    Возвращает (рука, причина). Причина названа всегда, когда руки нет:
    молчаливый пропуск в разрезе денег неотличим от руки без денег.
    """
    if not cands:
        return None, "нет решения"
    best = sorted(cands, key=lambda c: -c[1])
    if len(best) > 1 and best[0][1] == best[1][1] and best[0][0] != best[1][0]:
        return None, "неразрешимо"
    return best[0][0], None


def attribute(rows, idx, log=print):
    """Каждой строке журнала — рука; счётчики причин рядом, не молча."""
    out = []
    cnt = {"one": 0, "both": 0, "tie": 0, "no_leg": 0}
    for r in rows:
        cands = idx.get(key_of(r.get("sym"), r.get("side") or R.side_of(R.ruler_of(r)),
                               r.get("at") or 0)) or []
        arm, why = author(cands)
        if arm is None:
            cnt["tie" if why == "неразрешимо" else "no_leg"] += 1
        else:
            cnt["both" if len({c[0] for c in cands}) > 1 else "one"] += 1
        out.append(dict(r, arm=arm, arm_why=why))
    n = len(rows) or 1
    log(f"рука восстановлена у {cnt['one'] + cnt['both']} строк из {len(rows)} "
        f"({100.0 * (cnt['one'] + cnt['both']) / n:.1f} %): одна рука "
        f"{cnt['one']}, обе {cnt['both']}; неразрешимо {cnt['tie']}, "
        f"решения нет {cnt['no_leg']}")
    return out, cnt


def _median(xs):
    if not xs:
        return None
    ys = sorted(xs)
    m = len(ys) // 2
    return ys[m] if len(ys) % 2 else 0.5 * (ys[m - 1] + ys[m])


def stats(rows, mid=None):
    """Деньги руки: сумма, медиана позиции в % маржи, доля плюсов, половины."""
    if not rows:
        return {"n": 0}
    usd = [float(r.get("usd") or 0) for r in rows]
    pct = [100.0 * float(r.get("pnl_frac") or 0) for r in rows]
    s = {"n": len(rows), "usd": round(sum(usd), 2),
         "pct_median": round(_median(pct), 3),
         "pct_mean": round(sum(pct) / len(pct), 3),
         "win": round(100.0 * sum(1 for x in usd if x > 0) / len(usd), 1),
         "usd_median": round(_median(usd), 4)}
    if mid is not None:
        a = [float(r.get("usd") or 0) for r in rows if float(r.get("at") or 0) < mid]
        b = [float(r.get("usd") or 0) for r in rows if float(r.get("at") or 0) >= mid]
        s["half_a"] = round(sum(a), 2) if a else None
        s["half_b"] = round(sum(b), 2) if b else None
        s["n_a"], s["n_b"] = len(a), len(b)
    return s


def window(rows):
    ats = [float(r.get("at") or 0) for r in rows if r.get("at")]
    if not ats:
        return None
    f = time.strftime("%Y-%m-%d %H:%M", time.gmtime(min(ats)))
    t = time.strftime("%Y-%m-%d %H:%M", time.gmtime(max(ats)))
    return {"from": f, "to": t, "mid": 0.5 * (min(ats) + max(ats)),
            "span_d": round((max(ats) - min(ats)) / 86400.0, 2)}


def by_day(legs, rows, ruler=None, dep=None):
    """Активность по суткам: решения листа по руке и строки книги.

    Нужна затем, что сумма за окно молчит о том, РОВНО ЛИ книга работала:
    месяц с недельным всплеском и месяц с ежедневной торговлей дают одну
    и ту же строку итога. Сутки берутся по МОМЕНТУ РЕШЕНИЯ (не записи) —
    вопрос в том, когда сигнал был, а не когда его посчитали.
    """
    d = {}
    for g in legs:
        k = time.strftime("%Y-%m-%d", time.gmtime(float(g.get("at") or 0)))
        cell = d.setdefault(k, {"gbm": 0, "nn": 0, "rows": 0})
        cell[(g.get("arm") or "gbm")] = cell.get(g.get("arm") or "gbm", 0) + 1
    for r in rows:
        if ruler is not None and R.ruler_of(r) != ruler:
            continue
        if dep is not None and int(float(r.get("dep") or 0)) != int(dep):
            continue
        k = time.strftime("%Y-%m-%d", time.gmtime(float(r.get("at") or 0)))
        d.setdefault(k, {"gbm": 0, "nn": 0, "rows": 0})["rows"] += 1
    return d


def run(rows=None, legs=None, log=print):
    t0 = time.time()
    if legs is None:
        legs = D6.gated_legs(side=None, log=log)
    if rows is None:
        st = {}
        rows, bad = R.read_journal(stats=st)
        log(f"журнал: {len(rows)} строк, битых {bad}, кусков {st.get('parts')}")
    n_all = len(rows)
    rows = [r for r in rows if R.is_current(r)]
    log(f"текущей версии правил ({R.RULES}): {len(rows)} строк из {n_all}")

    comp = {}
    for g in legs:
        side = g.get("side") or "long"
        arm = g.get("arm") or "gbm"
        comp.setdefault(side, {}).setdefault(arm, 0)
        comp[side][arm] += 1
    pairs = {}
    for g in legs:
        k = key_of(g.get("sym"), g.get("side") or "long", g.get("at") or 0)
        pairs.setdefault(k, set()).add(g.get("arm") or "gbm")
    both = sum(1 for v in pairs.values() if len(v) > 1)
    agree = {"decisions": len(pairs), "both_arms": both,
             "share": round(100.0 * both / len(pairs), 1) if pairs else None}
    log(f"ноги листов: {len(legs)}, решений (имя, сторона, час) {len(pairs)}, "
        f"обе руки на одном решении {both} ({agree['share']} %)")

    rich, cnt = attribute(rows, legs_index(legs), log=log)
    win = window(rich)
    mid = win["mid"] if win else None
    fwd, back = R.split_rows(rich)
    seen = {r.get("at") for r in fwd}

    cells = {}
    for r in rich:
        rk, dep = R.ruler_of(r), int(float(r.get("dep") or 0))
        cells.setdefault((rk, dep), []).append(r)
    out = {}
    for (rk, dep), rs in sorted(cells.items()):
        key = f"{rk}:{dep}"
        arms = {}
        for arm in ARMS:
            arms[arm] = stats([r for r in rs if r.get("arm") == arm], mid)
        lost = [r for r in rs if r.get("arm") is None]
        arms["нет руки"] = stats(lost, mid)
        out[key] = {"ruler": rk, "dep": dep, "side": R.side_of(rk),
                    "title": R.ruler_title(rk), "all": stats(rs, mid),
                    "arms": arms}
    days = by_day(legs, rich, ruler="optimal", dep=MAIN_DEP)
    return {"at": time.time(), "secs": round(time.time() - t0, 1),
            "days": days, "rules_since": R.RULES_SINCE,
            "rules": R.RULES, "legs": len(legs), "rows": len(rows),
            "rows_all": n_all, "forward": len(fwd), "back": len(back),
            "forward_hours": len(seen), "composition": comp, "agree": agree,
            "attribution": cnt, "window": win, "cells": out,
            "deposits": [int(d) for d in R.DEPOSITS], "main_dep": MAIN_DEP}


def verdict(s):
    """По книге на главном депозите: у какой руки плюс и держится ли он
    на обеих половинах окна. Меньше `N_MIN` сделок — вердикта нет."""
    v = {}
    for key, c in s["cells"].items():
        if c["dep"] != s["main_dep"]:
            continue
        rows = []
        for arm in ARMS:
            a = c["arms"].get(arm) or {"n": 0}
            if a.get("n", 0) < N_MIN:
                rows.append({"arm": arm, "n": a.get("n", 0),
                             "why": f"сделок меньше {N_MIN}"})
                continue
            ha, hb = a.get("half_a"), a.get("half_b")
            rows.append({"arm": arm, "n": a["n"], "usd": a["usd"],
                         "plus": a["usd"] > 0,
                         "both_halves": bool(ha is not None and hb is not None
                                             and ha > 0 and hb > 0)})
        v[c["ruler"]] = rows
    return v


def _u(x):
    return "—" if x is None else f"{x:+.2f}"


def _p(x):
    return "—" if x is None else f"{x:+.3f}"


def report(s):
    L = ["# DCA-книги в разрезе руки модели (деревья / сеть)", "",
         "Вопрос владельца 2026-09-07: «у DCA лонг используются сигналы ml "
         "или ai, или обе?». Вход книги DCA — выбор ситуационной книги "
         "`sit`, а её лист пишут ОБЕ руки турнира моделей: бустинг деревьев "
         "(`gbm`) и нейросеть (`nn`). Отбора по руке у DCA нет — в ноги "
         "идут решения обеих. Рука в запись позиции не попадает, поэтому "
         "здесь она восстановлена соединением журнала книги с журналом "
         "листов по (имя, сторона, момент); спор двух рук за одно имя "
         "решает то же правило, что у книги — больший модуль прогноза.", ""]
    w = s.get("window") or {}
    L += [f"Журнал: {s['rows']} строк текущей версии правил ({s['rules']}) из "
          f"{s['rows_all']}; окно решений {w.get('from', '—')} … "
          f"{w.get('to', '—')} UTC ({w.get('span_d', '—')} суток). Ноги "
          f"листов: {s['legs']}, решений {s['agree']['decisions']}, из них "
          f"обе руки на одном имени и часе — {s['agree']['both_arms']} "
          f"({s['agree']['share']} %).", ""]
    since = time.strftime("%Y-%m-%d", time.gmtime(float(s.get("rules_since") or 0)))
    L += [f"**Наблюдение против пересчёта.** Правила версии {s['rules']} "
          f"действуют с {since}, поэтому вперёд записано всего "
          f"{s['forward']} строк ({s['forward_hours']} ч), а {s['back']} — "
          "пересчёт истории по нынешним правилам. Весь разрез ниже есть "
          "БЭКТЕСТ по построению, и читать его как результат книги, "
          "проверенной вперёд, нельзя.", ""]
    a = s["attribution"]
    L += ["## Восстановление руки", "",
          "| исход соединения | строк |", "|---|---:|",
          f"| одна рука на решении | {a['one']} |",
          f"| обе руки, взята с бо́льшим прогнозом | {a['both']} |",
          f"| прогнозы равны — неразрешимо | {a['tie']} |",
          f"| ноги нет (лист старше журнала книги) | {a['no_leg']} |", ""]
    comp = s.get("composition") or {}
    L += ["## Состав ног листа по руке", "",
          "| сторона | деревья | сеть |", "|---|---:|---:|"]
    for side in ("long", "short"):
        c = comp.get(side) or {}
        L += [f"| {side} | {c.get('gbm', 0)} | {c.get('nn', 0)} |"]
    L += ["", f"## Деньги книг по руке (депозит ${s['main_dep']}, брутто журнала)", "",
          "| книга | рука | сделок | Σ $ | медиана % маржи | плюсов | половина A $ | половина B $ |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for key, c in sorted(s["cells"].items()):
        if c["dep"] != s["main_dep"]:
            continue
        for arm in list(ARMS) + ["нет руки"]:
            st = c["arms"].get(arm) or {"n": 0}
            if not st.get("n"):
                continue
            L += [f"| `{c['ruler']}` ({c['title']}) | {arm_title(arm)} | "
                  f"{st['n']} | {_u(st.get('usd'))} | {_p(st.get('pct_median'))} | "
                  f"{st.get('win')} % | {_u(st.get('half_a'))} | {_u(st.get('half_b'))} |"]
        st = c["all"]
        L += [f"| `{c['ruler']}` ({c['title']}) | **вся книга** | {st['n']} | "
              f"{_u(st.get('usd'))} | {_p(st.get('pct_median'))} | {st.get('win')} % | "
              f"{_u(st.get('half_a'))} | {_u(st.get('half_b'))} |"]
    days = s.get("days") or {}
    if days:
        L += ["", "## Активность по суткам (решения листа по руке; строки "
              f"книги `optimal` на ${s['main_dep']})", "",
              "| сутки | деревья | сеть | строк книги |", "|---|---:|---:|---:|"]
        for k in sorted(days):
            c = days[k]
            L += [f"| {k} | {c.get('gbm', 0)} | {c.get('nn', 0)} | {c.get('rows', 0)} |"]
        L += ["", "Ровность работы книги видна только здесь: итог за окно "
              "одинаков у месяца ежедневной торговли и у месяца с одним "
              "всплеском, а решения о размере и о доверии к книге — разные.", ""]
    L += ["", "## Вердикт", "",
          f"Вердикт ставится книге на ${s['main_dep']} и только руке с "
          f"{N_MIN}+ сделками; «плюс на обеих половинах» — единственная "
          "форма, которую окно в месяц вообще может подтвердить.", "",
          "| книга | рука | сделок | Σ $ | плюс | обе половины |",
          "|---|---|---:|---:|---|---|"]
    for rk, rows in sorted(verdict(s).items()):
        for r in rows:
            if r.get("why"):
                L += [f"| `{rk}` | {arm_title(r['arm'])} | {r['n']} | — | — | "
                      f"{r['why']} |"]
            else:
                L += [f"| `{rk}` | {arm_title(r['arm'])} | {r['n']} | "
                      f"{_u(r['usd'])} | {'да' if r['plus'] else 'нет'} | "
                      f"{'да' if r['both_halves'] else 'нет'} |"]
    L += ["", "## Чего замер НЕ говорит", "",
          "- Он не сравнивает руки на ОДНОМ составе: составы разные по "
          "построению, и рука, чьих решений больше, имеет больше и денег.",
          "- Он не судит правило «книга берёт только одну руку»: такой "
          "книги не было. Половины окна посчитаны именно затем, чтобы такую "
          "мысль было чем проверять, а не чтобы её объявить.",
          "- Деньги — брутто журнала. Издержки меряет `costs.py`; они "
          "пропорциональны обороту, знак разреза не переставляют, но и не "
          "вычтены здесь.",
          "- Строки без ноги («лист старше журнала книги») деньгами не "
          "приписаны никому и стоят отдельной строкой «нет руки» — их "
          "молчаливое зачисление в любую руку было бы подделкой разреза.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="DCA-книги по руке модели")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run()
    name = f"DCA-arms-{a.tag}"
    with open(os.path.join(R.OUT, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(R.OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"DCA: разрез книг по руке модели ({a.tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
