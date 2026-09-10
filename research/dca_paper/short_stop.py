#!/usr/bin/env python3
"""Пол капитуляции как СТОП: где резать позицию против хода.

Просьба владельца 2026-09-10 («давай замерим») по первому пункту
списка. Всё измеренное указывает сюда: минус короткой стороны делают
не отбор и не цель, а ХВОСТ — пол капитуляции и ликвидация. Их доля 4 /
12 / 25 % сделок у трёх книг, и они же съедают −6.5k / −21k / −44k при
том, что медиана сделки плюсовая во всех полосах плеча. Множитель тейка
проверен и рычагом не оказался: он живёт на стороне прибыли, а теряет
книга на стороне против позиции.

ОСЬ (объявлена здесь, до прогона) — доля расстояния «вход →
ликвидация», на которой стоит пол:

    0.10 (как сейчас) | 0.25 | 0.50 | 0.75

Читать её проще в съеденной марже: пол срабатывает, когда цена прошла
против позиции (1 − доля) этого расстояния, а ликвидация — это почти
вся маржа. То есть 0.10 ≈ «режем при съеденных ~90 % маржи» (нынешнее
правило, у самой ликвидации), 0.50 ≈ «при половине», 0.75 ≈ «при
четверти». Чем БОЛЬШЕ доля, тем РАНЬШЕ стоп.

Формула пола — ядра лестницы, не замера: `floor_px = p_liq + доля ·
(вход − p_liq)` (`ladder.simulate_dca`), и ось двигает ровно её
параметр. У коротких книг доливов нет, поэтому лестница «вычерпана» с
первого рунга и пол работает с самого входа.

Всё остальное — как книги торгуют сегодня: плечо забора, доливов нет,
цель ×2, срок 24 ч, гейт края ≥ 33 б.п., возраст имени ≥ 7 суток, доля
билета книги; деньги НЕТТО.

ЧЕГО ЗДЕСЬ НЕТ. Контроля случайной выборкой: стоп сделок не режет, он
меняет, чем они кончаются (как и тейк) — поэтому рядом с деньгами
печатается состав исходов, а таблица идёт целиком. Лучшая ячейка
правилом не назначается (ошибка R5): окно одно, веса модели эти часы
видели.

Ось считается ПО ОДНОЙ ячейке (пол — глобальный параметр симуляции, а
не ключ ячейки D10), артефакт сливается: у каждой ячейки своя дата, а
отчёт называет те, которых ещё нет.

Запуск: `run research/dca_paper/short_stop.py --floor f25`.
Смоук: `--limit 200`.
"""
import argparse
import os
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
import run_d2 as D2                                           # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import subprocess                                             # noqa: E402
import json                                                   # noqa: E402

# Ось объявлена до прогона. Ключ — для очереди (латиница), значение —
# доля расстояния «вход → ликвидация».
FLOORS = (("f10", 0.10), ("f25", 0.25), ("f50", 0.50), ("f75", 0.75))
# Ячейка книги: плечо забора, доливов нет, цель ×2 — то, чем книги
# торгуют. Ключ в языке D10, чтобы реплей считал ровно её.
CELL = ("fence:none:t2", "fence", "none", "t2")
ART = "DCA-short-stop"


def eaten(frac):
    """Сколько маржи съедено к моменту пола, долей. Обратная сторона оси."""
    return 1.0 - float(frac)


def run(floor_key, limit=None, src=None, log=print, legs_=None, ctx=None,
        now=None, launch=None, mem_limit=None):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    val = dict(FLOORS).get(floor_key)
    if val is None:
        return {"error": f"ячейка «{floor_key}» не объявлена в оси"}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        log("замер не считается: коротких решений на листе нет")
        return {"error": "коротких решений на листе нет"}
    # Пол — ПАРАМЕТР СИМУЛЯЦИИ, а не ключ ячейки: ставится на время
    # прогона и возвращается обратно, как срок у `run_d11.configure`.
    # Оставленный глобально, он сделал бы соседний замер другим замером
    # молча.
    was = D2.FLOOR_FRAC
    try:
        D2.FLOOR_FRAC = float(val)
        log(f"пол капитуляции на время замера: {val:g} "
            f"(≈ съедено {100 * eaten(val):.0f} % маржи), было {was:g}")
        got = G.replay(legs_, [CELL], src=src, log=log)
    finally:
        D2.FLOOR_FRAC = was
    st = G.cell_stats(G.pack(got.get("recs") or {}, CELL[0]), ctx, launch,
                      now=now, log=lambda *a: None)
    ref = st.get(f"safe_h:{int(R.DEPOSITS[1])}") or {}
    ex = ref.get("exits") or {}
    log(f"пол {val:g}: безопасная ${int(R.DEPOSITS[1])} → {ref.get('usd')} $, "
        f"просадка {ref.get('max_dd')}, полом {ex.get('пол', {}).get('n', 0)}, "
        f"ликвидаций {ex.get('ликвидация', {}).get('n', 0)} из {ref.get('n')}")
    return {"cells": {floor_key: st}, "cell": CELL[0], "legs": len(legs_),
            "positions": got.get("positions"), "skipped": got.get("skipped"),
            "window": got.get("window"), "hold_h": R.H24_HOLD_H,
            "launch_known": len(launch),
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def report(s):
    L = ["# Пол капитуляции как стоп: где резать против хода", "",
         "Просьба владельца 2026-09-10. Ось объявлена ДО прогона: доля "
         "расстояния «вход → ликвидация», на которой стоит пол — "
         "0.10 (как сейчас) / 0.25 / 0.50 / 0.75. В съеденной марже это "
         "«режем при ~90 / 75 / 50 / 25 % съеденной маржи»: чем больше "
         "доля, тем РАНЬШЕ стоп. Формула пола — ядра лестницы, ось "
         "двигает её параметр.", "",
         "Остальное — как книги торгуют сегодня: плечо забора, доливов "
         "нет, цель ×2, срок 24 ч, гейт края, возраст ≥ 7 суток, доля "
         "билета; деньги НЕТТО.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    have = {a["key"] for a in s.get("axis", [])}
    miss = [a for a in s.get("axis_all", []) if a["key"] not in have]
    if miss:
        L += ["**Ось посчитана не целиком:** нет ячеек "
              + ", ".join(f"{a['value']:g}" for a in miss)
              + ". Их ещё не считали — это не «их не бывает».", ""]
    ca = s.get("cell_at") or {}
    if len(set(ca.values())) > 1:
        L += ["Ячейки считаны разными прогонами: "
              + ", ".join(f"{a['value']:g} — {ca.get(a['key'], '—')}"
                          for a in s.get("axis", []))
              + ".", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}.", ""]
    for bk in R.H24_ORDER:
        L += [f"## {R.ruler_title(bk)}", "",
              "| пол | съедено маржи | депозит | сделок | Σ $ | итог | "
              "просадка | доход/просадка | тейк | срок | пол | "
              "ликвидация |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for a in s.get("axis", []):
            for dep in R.DEPOSITS:
                c = ((s.get("cells") or {}).get(a["key"]) or {}).get(
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
                    f"| {a['value']:g} | ~{100 * eaten(a['value']):.0f} % | "
                    f"${int(dep)} | {c.get('n')} | {_u(c.get('usd'))} | "
                    f"{_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
                    + ("—" if c.get("ratio") is None
                       else f"{c['ratio']:.2f}") + " | "
                    + " | ".join(_e(x) for x in ("тейк", "срок", "пол",
                                                 "ликвидация")) + " |")
        L.append("")
    L += ["## Как читать", "",
          "- Ранний стоп обязан двигать ДВА числа сразу: долю хвостовых "
          "исходов вниз и просадку вниз. Если просадка падает, а деньги "
          "падают вместе с ней — это не защита, а уменьшение книги, и "
          "то же самое даёт доля билета, только без потери сделок.",
          "- Ликвидации при раннем стопе обязаны исчезать: стоп стоит "
          "перед ней. Если они остаются — значит цена доходит до "
          "ликвидации ВНУТРИ бара, минуя пол, и это свойство разрыва, а "
          "не правила.",
          "- Ячейка правилом не назначается: окно одно, веса модели эти "
          "часы видели.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="пол капитуляции как стоп")
    ap.add_argument("--floor", choices=[k for k, _v in FLOORS], required=True,
                    help="ячейка оси (пол — глобальный параметр симуляции, "
                         "поэтому за прогон считается одна)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    s = run(a.floor, limit=a.limit)
    art = os.path.join(R.OUT, f"{ART}.json")
    s = G.merge_artifact(s, art, [(k, v) for k, v in FLOORS])
    G.write(s, ART, report, "пол капитуляции", log=print)
    if not a.no_publish:
        publish("пол капитуляции как стоп: где резать против хода")
    return 0


if __name__ == "__main__":
    sys.exit(main())
