#!/usr/bin/env python3
"""Множитель тейка на коротком листе `h24`: ось объявлена до прогона.

Просьба владельца 2026-09-10 («давай померим»). Вопрос возник из
разреза выходов: у коротких книг тейк формально есть, а срабатывает у
5.5–5.9 % сделок — цель стоит в 26–29 % от ТВХ, потому что обещание
модели на этом листе крупное (медиана −13 %), а множитель ×2 достался
книгам ПО НАСЛЕДСТВУ от длинного ситуационного листа, где обещание
2.6 % при суточной σ имени 5.5 %. Правило, разумное при цели 5 %, при
цели 26 % может значить совсем другое — это и меряется.

ОСЬ (объявлена здесь, до прогона): множитель обещания
**0.5 / 1 / 1.5 / 2 / 3**. Всё остальное — как книга торгует сегодня:
ячейка `fence:none` (плечо забора, доливов нет), срок 24 ч, гейт края
≥ 33 б.п., правила семейства (возраст имени ≥ 7 суток, доля билета) и
деньги НЕТТО — комиссия, проскальзывание и funding в каждой сделке.

ПОЧЕМУ ЗДЕСЬ НЕТ КОНТРОЛЯ СЛУЧАЙНОЙ ВЫБОРКОЙ. Он нужен там, где
правило РЕЖЕТ число сделок (фильтр возраста): «меньше сделок» само по
себе двигает счёт. Множитель тейка сделок не режет — те же решения
входят в книгу и закрываются иначе. Поэтому контроль здесь другой:
таблица печатается ЦЕЛИКОМ, все пять ячеек считаются на ОДНИХ И ТЕХ ЖЕ
решениях, и рядом с деньгами стоит состав исходов (тейк / срок / пол /
ликвидация) — механизм, а не только итог.

ЧЕГО ЗАМЕР НЕ ДЕЛАЕТ. Правил книг он не меняет: лучшая ячейка правилом
не назначается (ошибка R5), и любое изменение множителя станет правилом
только объявленным заранее и проверенным вперёд. Окно одно, веса модели
эти часы видели, ось просмотрена целиком — оговорки те же, что у D10.

Прогон читает БАРЫ (это не пересчёт кэша: другой тейк — другой исход
позиции), поэтому он долгий и идёт со сторожем памяти. Память растёт
ЛИНЕЙНО с числом записей (решения × ячейки): вся ось разом на месячном
листе упирается в предел, и первый прогон был остановлен на трети
именно поэтому. Поэтому ось можно считать ЧАСТЯМИ (`--take`), а
артефакт СЛИВАЕТСЯ: ячейка, посчитанная прежним прогоном, остаётся с
собственной датой, а отчёт печатает, каких ячеек ещё нет. Ось от этого
не меняется — меняется только порядок счёта.

Запуск: `run research/dca_paper/short_take.py` (вся ось) или частями:
`run research/dca_paper/short_take.py --take t05 --take t1 --take t15`.
Смоук: `--limit 200`.
"""
import argparse
import collections
import json
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
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d11 as D11                                         # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import tail as TL                                             # noqa: E402

# Ось. Ключ ячейки — тот же язык, что у D10 (`плечо:доливы:цель`), и
# множители кладутся в ЕГО карту: цель считает `run_d10.take_for`, и
# второй арифметики цели здесь нет.
TAKES = (("t05", 0.5), ("t1", 1.0), ("t15", 1.5), ("t2", 2.0), ("t3", 3.0))
LEV, ADDS = "fence", "none"
MEM_LIMIT_MB = 1200


def cells(takes=TAKES):
    """Ячейки оси в форме D10 и регистрация множителей в его карте."""
    D10.TAKE_MULT.update({k: float(m) for k, m in takes})
    return [(f"{LEV}:{ADDS}:{k}", LEV, ADDS, k) for k, _m in takes]


def replay(legs_, cl, src=None, log=print):
    """Один проход по барам на ВСЕ ячейки оси: бары символа читаются раз.

    Срок и гейт отсчёта ставятся на время прогона тем же способом, что у
    книги (`run_d11.configure`), и возвращаются обратно: оставленный
    глобально срок сделал бы соседний замер другим замером молча.
    """
    was = D11.configure(R.H24_HOLD_H)
    try:
        src = src or TL.TailBars(log=log)
        got = D10.collect(legs=legs_, cells=cl, rich=True, raw=True,
                          src=src, log=log)
    finally:
        D11.restore(was)
    return got


def pack(recs, key):
    """Записи ячейки по книгам семейства — той же картой, что у прогона."""
    return {bk: list((recs.get(rk) or {}).get(key) or [])
            for bk, rk in S.BOOKS.items()}


def cell_stats(packed, ctx, launch, now=None, log=lambda *a: None):
    """Книги семейства на этих записях: деньги НЕТТО, состав исходов.

    Правила книги применяются ТЕ ЖЕ и в том же порядке, что в прогоне
    (`run_paper.age_shorts` → `build_rows`): замер, торгующий другими
    правилами, отвечал бы на другой вопрос.
    """
    packed = dict(packed)
    for bk in list(packed):
        packed[bk], _why = RP.age_shorts(packed[bk], bk, launch=launch,
                                         log=log, now=now)
    rows, cells_, _one, _live = RP.build_rows(packed, now=now,
                                              keys=R.H24_ORDER, log=log)
    out = {}
    for bk in R.H24_ORDER:
        for dep in R.DEPOSITS:
            mine = [r for r in rows if R.ruler_of(r) == bk
                    and int(r.get("dep", 0)) == int(dep)]
            if ctx is not None and not ctx.get("error"):
                mine, _c = CO.apply_to_rows(mine, ctx)
            st = RP._stats(mine, dep) or {}
            fin, dd = st.get("final"), st.get("max_dd")
            by = collections.Counter(r.get("exit") or "—" for r in mine)
            usd = collections.defaultdict(float)
            for r in mine:
                usd[r.get("exit") or "—"] += float(r.get("usd") or 0.0)
            c = cells_.get(RP._cell(bk, dep)) or {}
            out[f"{bk}:{int(dep)}"] = {
                "book": bk, "dep": int(dep), "n": st.get("n"),
                "usd": st.get("usd"), "final": fin, "max_dd": dd,
                "win": st.get("win"), "day_median": st.get("day_median"),
                "ratio": (None if not fin or not dd
                          else round(float(fin) / abs(float(dd)), 2)),
                "exits": {k: {"n": v, "usd": round(usd[k], 2)}
                          for k, v in by.items()},
                "no_cash": c.get("no_cash"), "taken": c.get("taken")}
    return out


def run(limit=None, src=None, log=print, legs_=None, ctx=None, now=None,
        launch=None, takes=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    takes = tuple(takes or TAKES)
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        log("замер не считается: коротких решений на листе нет")
        return {"error": "коротких решений на листе нет"}
    cl = cells(takes)
    got = replay(legs_, cl, src=src, log=log)
    out = {"takes": [{"key": k, "mult": float(m)} for k, m in takes],
           "cell": f"{LEV}:{ADDS}", "legs": len(legs_),
           "positions": got.get("positions"), "skipped": got.get("skipped"),
           "window": got.get("window"), "cells": {},
           "hold_h": R.H24_HOLD_H, "launch_known": len(launch),
           "costs_error": (ctx or {}).get("error"),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    for k, m in takes:
        key = f"{LEV}:{ADDS}:{k}"
        st = cell_stats(pack(got.get("recs") or {}, key), ctx, launch,
                        now=now, log=lambda *a: None)
        out["cells"][k] = st
        ref = st.get(f"safe_h:{int(R.DEPOSITS[1])}") or {}
        log(f"цель ×{m:g}: безопасная ${int(R.DEPOSITS[1])} → "
            f"{ref.get('usd')} $, просадка {ref.get('max_dd')}, "
            f"тейков {(ref.get('exits') or {}).get('тейк', {}).get('n', 0)} "
            f"из {ref.get('n')}")
    out["secs"] = round(time.time() - t0, 1)
    return out


def merge_artifact(s, path):
    """Слить ячейки этого прогона с уже посчитанными.

    Ось объявлена целиком, а считаться может частями (память): ячейка
    прежнего прогона остаётся со СВОЕЙ датой, и отчёт не выдаёт разные
    прогоны за один. Ячейка, посчитанная заново, перекрывает старую.
    """
    now = s.get("computed_at")
    s["cell_at"] = {k: now for k in (s.get("cells") or {})}
    if s.get("error") or not os.path.exists(path):
        s["takes_all"] = [{"key": k, "mult": float(m)} for k, m in TAKES]
        return s
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    cells_ = dict(old.get("cells") or {})
    at = dict(old.get("cell_at") or {})
    cells_.update(s.get("cells") or {})
    at.update(s["cell_at"])
    s["cells"], s["cell_at"] = cells_, at
    s["takes"] = [{"key": k, "mult": float(m)} for k, m in TAKES
                  if k in cells_]
    s["takes_all"] = [{"key": k, "mult": float(m)} for k, m in TAKES]
    return s


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def report(s):
    L = ["# Множитель тейка на коротком листе h24", "",
         "Просьба владельца 2026-09-10. Ось объявлена ДО прогона: "
         "множитель обещания модели 0.5 / 1 / 1.5 / 2 / 3. Всё "
         "остальное — как книги торгуют сегодня: плечо забора, доливов "
         "нет, срок "
         + f"{s.get('hold_h', 24)} ч, гейт края ≥ 33 б.п., возраст имени "
         "≥ 7 суток, доля билета книги; деньги НЕТТО (комиссия, "
         "проскальзывание и funding в каждой сделке).", "",
         "Множитель ×2 книги получили ПО НАСЛЕДСТВУ от длинного "
         "ситуационного листа, где медианное обещание 2.6 % при суточной "
         "σ имени 5.5 %. На этом листе обещание крупнее (медиана −13 %), "
         "то есть цель стоит в 26 % от ТВХ — и берётся у 6 % сделок.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    w = s.get("window") or {}
    L += [f"Решений листа {s.get('legs')}, позиций посчитано "
          f"{s.get('positions')}, пропущено (нет баров) {s.get('skipped')}"
          + (f"; окно {w.get('from')} … {w.get('to')} UTC" if w else "")
          + f"; прогон {s.get('secs')} с.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}.", ""]
    have = {t["key"] for t in s.get("takes", [])}
    miss = [t for t in s.get("takes_all", s.get("takes", []))
            if t["key"] not in have]
    if miss:
        L += ["**Ось посчитана не целиком:** нет ячеек "
              + ", ".join(f"×{t['mult']:g}" for t in miss)
              + ". Это не «их не бывает» — их ещё не считали (память "
              "прогона: ось идёт частями). Сравнивать можно только то, "
              "что в таблице.", ""]
    ca = s.get("cell_at") or {}
    if len(set(ca.values())) > 1:
        L += ["Ячейки считаны РАЗНЫМИ прогонами: "
              + ", ".join(f"×{t['mult']:g} — {ca.get(t['key'], '—')}"
                          for t in s.get("takes", []))
              + ". Лист и правила у них одни, но окно записи у более "
              "позднего прогона длиннее.", ""]
    deps = list(R.DEPOSITS)
    for bk in R.H24_ORDER:
        L += [f"## {R.ruler_title(bk)}", "",
              "| цель | депозит | сделок | Σ $ | итог | просадка | "
              "доход/просадка | тейк | срок | пол | ликвидация |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for t in s.get("takes", []):
            for dep in deps:
                c = ((s.get("cells") or {}).get(t["key"]) or {}).get(
                    f"{bk}:{int(dep)}")
                if not c:
                    continue
                ex = c.get("exits") or {}

                def _e(name, ex=ex, n=c.get("n") or 0):
                    v = ex.get(name) or {}
                    if not v.get("n"):
                        return "—"
                    return (f"{v['n']} ({100.0 * v['n'] / max(1, n):.0f} %) "
                            f"{v['usd']:+.0f} $")
                L.append(
                    f"| ×{t['mult']:g} | ${int(dep)} | {c.get('n')} | "
                    f"{_u(c.get('usd'))} | {_p(c.get('final'))} | "
                    f"{_p(c.get('max_dd'))} | "
                    + ("—" if c.get("ratio") is None
                       else f"{c['ratio']:.2f}") + " | "
                    + " | ".join(_e(x) for x in ("тейк", "срок", "пол",
                                                 "ликвидация")) + " |")
        L.append("")
    L += ["## Как читать", "",
          "- Все ячейки считаны на ОДНИХ И ТЕХ ЖЕ решениях листа: "
          "множитель тейка сделок не режет, он меняет, чем они кончаются. "
          "Поэтому контроль здесь — состав исходов рядом с деньгами, а не "
          "случайная выборка того же размера (она нужна фильтрам).",
          "- Ближняя цель забирает сделки у выхода «по сроку» и режет "
          "хвост; дальняя оставляет позицию открытой на весь срок. "
          "Смотреть надо на пару «деньги + просадка», а не на деньги.",
          "- Ячейка правилом НЕ назначается: лучшая из просмотренных — "
          "ошибка R5. Правилом станет только объявленное заранее и "
          "проверенное вперёд.",
          "- Окно одно, веса модели эти часы видели: это оценка сверху.",
          ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="множитель тейка на листе h24")
    ap.add_argument("--limit", type=int, default=None)
    # Ось частями: аргументы очереди — только латиница, поэтому флаг
    # повторяется, а не перечисляется запятыми.
    ap.add_argument("--take", action="append", default=None,
                    choices=[k for k, _m in TAKES],
                    help="считать только эти ячейки оси (можно повторять)")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    want = ([t for t in TAKES if t[0] in set(a.take)] if a.take else TAKES)
    s = run(limit=a.limit, takes=want)
    art = os.path.join(R.OUT, "DCA-short-take.json")
    s = merge_artifact(s, art)
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-short-take.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("множитель тейка на коротком листе h24")
    return 0


if __name__ == "__main__":
    sys.exit(main())
