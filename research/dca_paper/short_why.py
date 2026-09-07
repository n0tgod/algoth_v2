#!/usr/bin/env python3
"""Почему у короткой книги такая просадка и откуда минус у агрессивной.

Вопрос владельца 2026-09-07: «почему по шорту такая просадка и минус на
агрессивной, задача была выровнять кривую».

Замер отвечает по ЗАПИСИ книг, ничего не пересчитывая по барам и не
трогая ни правил, ни порогов. Разбор идёт по четырём осям, и каждая
отвечает на свой вопрос:

* **исход** (тейк, срок, стоп, пол, трейл, ликвидация) — где книга
  теряет: в редких больших исходах или ровным слоем;
* **плечо** — D10 уже намерил, что хвост коротких книг есть ПЛЕЧО; здесь
  та же ось на живом журнале и в деньгах НЕТТО;
* **концентрация** — сколько дают худшие 1, 5 и 10 позиций и худший
  день: хвост, который делают три сделки, и хвост, который делает вся
  книга, лечатся разным;
* **издержки** — комиссия, проскальзывание и funding по тем же сделкам,
  и отдельно самые дорогие по funding позиции: медиана funding около
  нуля, а среднее в разы дальше, значит платят немногие.

Плюс прямой ответ на «выровнять кривую»: сетка «доля короткой стороны»
— что стало бы с деньгами и просадкой ПАРЫ, если бы короткая сторона
входила меньшим билетом. Это ВОПРОС, а не правило: выбранная ячейка
станет результатом только объявленной заранее и проверенной вперёд.

Запуск: `run research/dca_paper/short_why.py`.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_d13 as D13                                         # noqa: E402

DEP = 10000.0
# Полосы плеча объявлены до прогона и одни на все книги: сравнивать
# книги можно только на общей сетке.
LEV_EDGES = (0.0, 3.0, 5.0, 10.0, 20.0, 1e9)
LEV_NAMES = ("<3×", "3–5×", "5–10×", "10–20×", "≥20×")
# Доли билета короткой стороны для сетки «выровнять кривую». Единица —
# нынешняя книга; ниже — та же книга меньшим билетом.
SHARES = (1.0, 0.75, 0.5, 0.25, 0.1)


def load(path, ruler, dep=DEP, ctx=None):
    """Строки книги ТЕКУЩИХ правил, деньги — НЕТТО (издержки в сделке)."""
    rows, _bad = R.read_journal(path)
    mine = [r for r in rows if R.is_current(r)
            and int(float(r.get("dep") or 0)) == int(dep)
            and R.ruler_of(r) == ruler]
    if ctx is None:
        return mine, {"applied": 0, "n": len(mine), "error": "контекста нет"}
    import costs as CO
    return CO.apply_to_rows(mine, ctx)


def by_exit(rows):
    """Деньги по исходу. Ликвидация — своя строка, а не «прочее»."""
    out = {}
    for r in rows:
        k = r.get("exit") or "—"
        b = out.setdefault(k, {"n": 0, "usd": 0.0, "vals": []})
        b["n"] += 1
        b["usd"] += float(r.get("usd") or 0.0)
        b["vals"].append(float(r.get("usd") or 0.0))
    for k, b in out.items():
        v = np.array(b.pop("vals"), dtype=float)
        b["usd"] = round(b["usd"], 2)
        b["median"] = round(float(np.median(v)), 2)
        b["worst"] = round(float(np.min(v)), 2)
        b["share_of_loss"] = None
    loss = sum(b["usd"] for b in out.values() if b["usd"] < 0)
    for b in out.values():
        b["share_of_loss"] = (round(b["usd"] / loss, 3)
                              if loss < 0 and b["usd"] < 0 else None)
    return out


def by_lev(rows):
    """Деньги по полосе плеча — на объявленной сетке."""
    out = {n: {"n": 0, "usd": 0.0, "vals": [], "margin": 0.0}
           for n in LEV_NAMES}
    for r in rows:
        lv = float(r.get("lev") or 0.0)
        for i in range(len(LEV_NAMES)):
            if LEV_EDGES[i] <= lv < LEV_EDGES[i + 1]:
                b = out[LEV_NAMES[i]]
                b["n"] += 1
                b["usd"] += float(r.get("usd") or 0.0)
                b["margin"] += float(r.get("margin") or 0.0)
                b["vals"].append(float(r.get("usd") or 0.0))
                break
    for b in out.values():
        v = np.array(b.pop("vals") or [0.0], dtype=float)
        b["usd"] = round(b["usd"], 2)
        b["median"] = round(float(np.median(v)), 2)
        b["worst"] = round(float(np.min(v)), 2)
        # доход на вложенную маржу: числа полос иначе несравнимы
        b["per_margin"] = (round(b["usd"] / b["margin"], 4)
                           if b["margin"] > 0 else None)
        b["margin"] = round(b["margin"], 2)
    return out


def concentration(rows, dep=DEP):
    """Сколько дают худшие позиции и худший день. Хвост трёх сделок и
    хвост всей книги лечатся разным, и различает их только это число."""
    if not rows:
        return {"why": "строк нет"}
    v = sorted(float(r.get("usd") or 0.0) for r in rows)
    tot = float(sum(v))
    days = D13.series(rows)
    dv = sorted(days.values())
    out = {"n": len(v), "usd": round(tot, 2),
           "worst1": round(v[0], 2),
           "worst5": round(float(sum(v[:5])), 2),
           "worst10": round(float(sum(v[:10])), 2),
           "usd_wo_worst5": round(tot - float(sum(v[:5])), 2),
           "usd_wo_worst10": round(tot - float(sum(v[:10])), 2),
           "worst_day": (round(dv[0], 2) if dv else None),
           "usd_wo_worst_day": (round(tot - dv[0], 2) if dv else None),
           "days": len(dv)}
    out["dd"] = D13.curve_dd([days[k] for k in sorted(days)], dep)
    out["dd_wo_worst5"] = None
    if len(v) > 5:
        # «Худшие пять» — пять худших ПО ДЕНЬГАМ строк, а не пять любых с
        # похожими числами: выбор по значению уже однажды выкинул из
        # книги прибыльные сделки с тем же числом.
        srt = sorted(rows, key=lambda r: float(r.get("usd") or 0.0))
        d2 = D13.series(srt[5:])
        out["dd_wo_worst5"] = D13.curve_dd([d2[k] for k in sorted(d2)], dep)
    return out


def funding_top(rows, k=5):
    """Позиции, которые заплатили funding больше всех: чем они особенны."""
    got = [r for r in rows if r.get("fund_usd") is not None]
    got.sort(key=lambda r: float(r["fund_usd"]))
    out = []
    for r in got[:k]:
        m = float(r.get("margin") or 0.0)
        out.append({"sym": r.get("sym"), "lev": round(float(r.get("lev") or 0), 1),
                    "margin": round(m, 2),
                    "hold_h": round((float(r["exit_ts"]) - float(r["at"]))
                                    / 3600.0, 1),
                    "fund_usd": round(float(r["fund_usd"]), 2),
                    "fund_bp": (round(float(r["fund_usd"]) / m * 1e4, 0)
                                if m > 0 else None),
                    "usd": round(float(r.get("usd") or 0.0), 2),
                    "exit": r.get("exit")})
    return out


def pair_grid(long_rows, short_rows, shares=SHARES, dep=DEP):
    """«Выровнять кривую»: пара при УМЕНЬШЕННОМ билете короткой стороны.

    Деньги короткой стороны линейны по билету (маржа × доля исхода),
    поэтому доля билета есть множитель её денег. Это оценка СВЕРХУ по
    точности: с меньшим билетом книга взяла бы БОЛЬШЕ решений (кассы
    хватало бы чаще), и состав сделок сдвинулся бы. Числа читаются как
    «что было бы с этими же сделками», а не как новый прогон.
    """
    ls, ss = D13.series(long_rows), D13.series(short_rows)
    days = sorted(set(ls) | set(ss))
    out = []
    for f in shares:
        both = [ls.get(d, 0.0) + f * ss.get(d, 0.0) for d in days]
        out.append({"share": f,
                    "usd": round(float(sum(both)), 2),
                    "final": round(float(sum(both)) / dep, 4),
                    "dd": D13.curve_dd(both, dep),
                    "short_usd": round(f * float(sum(ss.values())), 2),
                    "long_usd": round(float(sum(ls.values())), 2)})
    return {"days": len(days), "rows": out}


def run(dep=DEP, log=print, short_path=None, long_path=None, ctx=None):
    t0 = time.time()
    if ctx is None:
        try:
            import costs as CO
            ctx = CO.context()
        except Exception as e:                            # noqa: BLE001
            ctx = {"error": f"контекст издержек не собран: {e}"[:200]}
    out = {"dep": dep, "books": {}, "costs_ctx": ctx.get("error"),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    longs = {}
    for lk in R.order_of("sit"):
        rows, _c = load(long_path or R.JOURNAL, lk, dep, ctx)
        longs[lk] = rows
    for sk in R.order_of("h24"):
        rows, cs = load(short_path or R.H24_JOURNAL, sk, dep, ctx)
        if not rows:
            out["books"][sk] = {"why": "строк книги нет"}
            log(f"{sk}: строк нет")
            continue
        st = RP._stats(rows, dep) or {}
        b = {"n": len(rows), "stats": st, "costs_applied": cs.get("applied"),
             "gross": round(sum(float(r.get("usd_gross", r.get("usd") or 0.0))
                                for r in rows), 2),
             "net": round(sum(float(r.get("usd") or 0.0) for r in rows), 2),
             "by_exit": by_exit(rows), "by_lev": by_lev(rows),
             "conc": concentration(rows, dep), "fund_top": funding_top(rows)}
        # пара с длинной книгой того же режима — та же связка, что в
        # книге общего счёта
        lk = [x for x in R.order_of("sit")
              if R.PAIR_PARTS.get(f"pair_{x}", (None, None))[1] == sk]
        b["long_key"] = lk[0] if lk else None
        if b["long_key"]:
            b["grid"] = pair_grid(longs.get(b["long_key"]) or [], rows,
                                  dep=dep)
        out["books"][sk] = b
        log(f"{sk}: сделок {len(rows)}, нетто {b['net']:+.2f} $, "
            f"просадка {100 * (st.get('max_dd') or 0):.1f} %")
    out["secs"] = round(time.time() - t0, 1)
    return out


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def report(s):
    dep = int(s.get("dep") or DEP)
    L = ["# Почему у короткой книги такая просадка", "",
         "Вопрос владельца 2026-09-07: «почему по шорту такая просадка и "
         "минус на агрессивной, задача была выровнять кривую». Замер идёт "
         f"по ЗАПИСИ книг на депозите ${dep}, деньги НЕТТО (издержки "
         "учтены в каждой сделке), правила и пороги не тронуты.", ""]
    if s.get("costs_ctx"):
        L += [f"**Издержки посчитать не удалось:** {s['costs_ctx']}. "
              "Деньги ниже — брутто.", ""]
    for sk, b in s.get("books", {}).items():
        L += [f"## {R.ruler_title(sk)} (`{sk}`)", ""]
        if b.get("why"):
            L += [f"Не считалась: {b['why']}.", ""]
            continue
        st = b.get("stats") or {}
        L += [f"Сделок {b['n']}, брутто {_u(b['gross'])} $, НЕТТО "
              f"{_u(b['net'])} $ ({_p(st.get('final'))} к депозиту), "
              f"просадка {_p(st.get('max_dd'))}, плюсовых "
              f"{100 * (st.get('win') or 0):.0f} %, худший день "
              f"{_p(st.get('day_worst'))}.", "",
              "### Где теряется: по исходу", "",
              "| исход | сделок | Σ $ | медиана | худшая | доля убытка |",
              "|---|--:|--:|--:|--:|--:|"]
        for k, v in sorted((b.get("by_exit") or {}).items(),
                           key=lambda kv: kv[1]["usd"]):
            L.append(f"| {k} | {v['n']} | {_u(v['usd'])} | {_u(v['median'])} "
                     f"| {_u(v['worst'])} | "
                     + ("—" if v.get("share_of_loss") is None
                        else f"{100 * v['share_of_loss']:.0f} %") + " |")
        L += ["", "### Где теряется: по плечу", "",
              "| плечо | сделок | Σ $ | медиана | худшая | на вложенную маржу |",
              "|---|--:|--:|--:|--:|--:|"]
        for k in LEV_NAMES:
            v = (b.get("by_lev") or {}).get(k) or {}
            if not v.get("n"):
                continue
            L.append(f"| {k} | {v['n']} | {_u(v['usd'])} | {_u(v['median'])} "
                     f"| {_u(v['worst'])} | {_p(v.get('per_margin'))} |")
        c = b.get("conc") or {}
        L += ["", "### Концентрация: хвост трёх сделок или хвост книги", "",
              f"Худшая позиция {_u(c.get('worst1'))} $, худшие пять "
              f"{_u(c.get('worst5'))} $, худшие десять "
              f"{_u(c.get('worst10'))} $. Без худших пяти книга дала бы "
              f"{_u(c.get('usd_wo_worst5'))} $ при просадке "
              f"{_p(c.get('dd_wo_worst5'))} (с ними — {_u(c.get('usd'))} $ "
              f"при {_p(c.get('dd'))}). Худший день {_u(c.get('worst_day'))} $ "
              f"из {c.get('days')}; без него {_u(c.get('usd_wo_worst_day'))} $.",
              ""]
        ft = b.get("fund_top") or []
        if ft:
            L += ["### Кто платит funding", "",
                  "| имя | плечо | маржа $ | держали ч | funding $ | "
                  "б.п. маржи | итог сделки $ | исход |",
                  "|---|--:|--:|--:|--:|--:|--:|---|"]
            for x in ft:
                L.append(f"| {x['sym']} | {x['lev']}× | {x['margin']} | "
                         f"{x['hold_h']} | {_u(x['fund_usd'])} | "
                         + ("—" if x["fund_bp"] is None
                            else f"{x['fund_bp']:+.0f}")
                         + f" | {_u(x['usd'])} | {x['exit']} |")
            L += [""]
        g = b.get("grid") or {}
        if g.get("rows"):
            L += ["### «Выровнять кривую»: пара при меньшем билете шорта", "",
                  "Длинная книга та же, короткая входит долей своего билета. "
                  "Деньги короткой линейны по билету, поэтому это оценка "
                  "ТЕХ ЖЕ сделок, а не новый прогон: с меньшим билетом "
                  "книга взяла бы решений больше. Ячейка станет правилом "
                  "только объявленной заранее и проверенной вперёд.", "",
                  "| доля билета шорта | Σ $ пары | к депозиту | просадка пары "
                  "| Σ $ шорта | Σ $ длинной |", "|---|--:|--:|--:|--:|--:|"]
            for r in g["rows"]:
                L.append(f"| {r['share']:g}× | {_u(r['usd'])} | "
                         f"{_p(r['final'], 2)} | {_p(r['dd'])} | "
                         f"{_u(r['short_usd'])} | {_u(r['long_usd'])} |")
            L += [""]
    L += ["## Чего замер НЕ говорит", "",
          "- Сетка билета пересчитывает ТЕ ЖЕ сделки: настоящий прогон с "
          "меньшим билетом взял бы больше решений (кассы хватало бы чаще), "
          "и состав сдвинулся бы. Числа — ориентир для решения, а не "
          "результат книги.",
          "- Пороги действующих книг задним числом не меняются: выбранная "
          "по этой таблице доля станет правилом, только будучи объявленной "
          "и проверенной вперёд.",
          "- Окно одно и режим рынка один; веса модели видели эти часы.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="почему у короткой книги хвост")
    ap.add_argument("--dep", type=float, default=DEP)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run(dep=a.dep)
    art = os.path.join(R.OUT, "DCA-short-why.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-short-why.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("почему у короткой книги просадка")
    return 0


if __name__ == "__main__":
    sys.exit(main())
