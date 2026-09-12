#!/usr/bin/env python3
"""Гейты ВХОДА книг DCA: запас до пола и теснота стакана.

Просьба владельца 2026-09-12 («по максимуму отбирать плохие дни и
сделки»), пункты 1 и 3 разбора. Разбор 11–12.09 показал, из чего сделан
убыток: у безопасной короткой книги ПЯТЬ позиций из тридцати дали 83 %
потерь, и у всех пяти плечо 19–25×, то есть пол капитуляции стоял в
3–4 % цены от входа. Отбор по имени закрыт четырежды (согласие рук,
гейт ставки funding, множитель тейка, цель) — поэтому здесь меряются не
имена, а ГЕОМЕТРИЯ входа.

ОСИ ОБЪЯВЛЕНЫ ДО ПРОГОНА, их две и они считаются независимо:

  A. запас до пола, доля цены от входа:   3 % | 5 % | 8 % | 12 %
  B. теснота: наш нотионал к долларам у лучшей цены СВОЕЙ стороны
     (шорт входит в бид, лонг в аск):     ≤ 5× | ≤ 2× | ≤ 1× | ≤ 0.5×

Рядом с каждой стоит ветка «как сейчас» — без гейта. Обе оси считаются
на ОДНИХ И ТЕХ ЖЕ записях: гейт решает, входить ли, и не меняет исход
входа. Реплея по барам нет вовсе — записи берутся из кэшей реплея
семейств, кэш не переписывается.

ОТКУДА ГЕОМЕТРИЯ. Пол считает ядро лестницы (`ladder.liq_price` через
`rules.liq_walk`, тиры площадки по имени), доля пола — правило КНИГИ
(`rules.floor_frac_of`: 0.10 у безопасных, 0.50 у оптимальной и
агрессивной коротких). Глубину даёт часовая сводка стакана
(`s8_loop/out/summary/<имя>/<дата>.jsonl`, поля `best_b`/`best_a` в
долларах) — та же запись, на которой учится модель.

«НЕ ИЗМЕРЕНО» НЕ ФИЛЬТР. Решение, у которого сводки часа нет, гейт
тесноты ПРОПУСКАЕТ и считает отдельным числом. Иначе повторился бы
гейт по ставке funding: он «работал» ровно потому, что молча отсекал
773 решения с неизвестной ставкой.

КОНТРОЛЬ обязателен и объявлен: гейт РЕЖЕТ число сделок, а книга на
меньшем числе сделок меняется сама по себе. Рядом с каждым порогом
считается случайная выборка ТОГО ЖЕ размера (по каждой книге своя, на
`SEEDS` зёрнах) по той же величине — итог и доход/просадка.

ЧЕГО ЗАМЕР НЕ ГОВОРИТ. Правила он не заводит: лучшая ячейка правилом не
объявляется (ошибка R5), окно одно, веса модели эти часы видели. Он
считает бумажные книги; живого исполнения здесь нет.

Запуск: `run research/dca_paper/entry_gate.py`. Смоук: `--seeds 0`.
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
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-entry-gate"
SEEDS = 200                       # объявлено до прогона
MAIN_DEP = 10000                  # на нём идёт контроль
# Ось A: минимальный запас до пола, доля цены от входа.
FLOOR_GAPS = (("g03", 0.03), ("g05", 0.05), ("g08", 0.08), ("g12", 0.12))
# Ось B: потолок «наш нотионал к долларам у лучшей цены своей стороны».
TIGHT_CAPS = (("t5", 5.0), ("t2", 2.0), ("t1", 1.0), ("t05", 0.5))
SUMMARY_DIR = os.path.join(ROOT, "research", "s8_loop", "out", "summary")


def floor_gap(rec, book, look=None):
    """Доля цены от входа до ПОЛА капитуляции. Нет данных — None.

    Геометрия берётся ядром лестницы, а не своей формулой: пол книги
    выведен из цены ликвидации (`ladder.liq_price` по тирам площадки),
    а доля пола — правило самой книги.
    """
    try:
        entry = float(rec.get("entry_px"))
        lev = float(rec.get("lev"))
    except (TypeError, ValueError):
        return None
    if not entry > 0 or not lev > 0:
        return None
    side = rec.get("side") or "long"
    fills = rec.get("fills") or [[rec.get("at"), entry, 1.0]]
    walk = R.avg_walk(fills, entry, R.notional_of(rec), side=side)
    if not walk:
        return None
    look = look if look is not None else R.mmr_look(rec.get("sym"))
    R.liq_walk(walk, lev, side, look=look)
    liq = (walk[0] or {}).get("liq")
    if liq is None:
        return None
    frac = R.floor_frac_of(book, D2.FLOOR_FRAC)
    floor = float(liq) + float(frac) * (entry - float(liq))
    return abs(entry - floor) / entry


class Depth:
    """Доллары у лучшей цены на час решения — из часовых сводок стакана.

    Файл дня читается один раз на имя: сводок 725 имён × 40 дней, и
    открывать их на каждое решение значило бы читать один файл сотни
    раз. Часа нет в записи — величина НЕ ИЗМЕРЕНА, и это своё число.
    """

    def __init__(self, root=SUMMARY_DIR, log=print):
        self.root, self.log = root, log
        self._day = {}
        self.miss_file = 0
        self.miss_hour = 0
        self.hit = 0

    def _load(self, sym, day):
        key = (sym, day)
        if key in self._day:
            return self._day[key]
        path = os.path.join(self.root, sym, day + ".jsonl")
        rows = {}
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("hour"):
                        rows[r["hour"]] = r
        except OSError:
            rows = None
        if len(self._day) > 4000:                 # окно памяти, не течём
            self._day.clear()
        self._day[key] = rows
        return rows

    def touch_usd(self, rec):
        """Доллары у лучшей цены СВОЕЙ стороны входа. Нет записи — None."""
        sym, at = rec.get("sym"), rec.get("at")
        if not sym or at is None:
            return None
        hour = time.strftime("%Y-%m-%d-%H", time.gmtime(float(at) - 1))
        rows = self._load(sym, hour[:10])
        if rows is None:
            self.miss_file += 1
            return None
        r = rows.get(hour)
        if not r:
            self.miss_hour += 1
            return None
        # Шорт ВХОДИТ В БИД, лонг в аск: теснота меряется той стороной
        # стакана, об которую бьёт вход, а не средней по книге.
        v = r.get("best_b") if (rec.get("side") or "long") == "short" \
            else r.get("best_a")
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        self.hit += 1
        return v if v > 0 else None

    def tightness(self, rec):
        """Наш нотионал к долларам у лучшей цены. Нет записи — None."""
        usd = self.touch_usd(rec)
        if usd is None:
            return None
        try:
            notl = float(R.notional_of(rec))
        except (TypeError, ValueError):
            return None
        return None if not notl > 0 else notl / usd

    def why(self):
        return {"измерено": self.hit, "нет файла записи": self.miss_file,
                "нет часа в записи": self.miss_hour}


def gate_records(recs, book, keep_fn):
    """Записи книги, прошедшие гейт. Величина неизвестна — ПРОПУСКАЕМ.

    «Не измерено» фильтром быть не должно: гейт по ставке funding
    «работал» ровно тем, что молча отсекал решения без ряда.
    """
    out, unknown = [], 0
    for r in recs:
        v = keep_fn(r, book)
        if v is None:
            unknown += 1
            out.append(r)
            continue
        if v:
            out.append(r)
    return out, unknown


def branch(packed, book_gate, ctx, launch, keys, now=None):
    """Одна ветка оси: гейт по каждой книге, затем правила книг и деньги."""
    got, unknown = {}, 0
    for bk, recs in packed.items():
        kept, u = gate_records(recs, bk, book_gate)
        got[bk], unknown = kept, unknown + u
    st = AG.stats_of(got, ctx, launch, keys, now=now)
    return st, got, unknown


def control_rows(packed, sizes, ctx, launch, keys, seeds=SEEDS,
                 dep=MAIN_DEP, now=None, log=print):
    """Случайные выборки ТОГО ЖЕ размера — по каждой книге своя.

    Гейт живёт на ЗАПИСИ (у книг разное плечо на одном решении), значит
    и выборка берётся по записям книги, а не по решениям: иначе размеры
    сравниваемых книг разошлись бы по чужой причине.
    """
    out = {}
    t0 = time.time()
    for i in range(int(seeds)):
        rnd = random.Random(5000 + i)
        sub = {}
        for bk, recs in packed.items():
            n = int(sizes.get(bk) or 0)
            sub[bk] = list(recs) if n >= len(recs) else rnd.sample(recs, n)
        st = AG.stats_of(sub, ctx, launch, keys, deps=[dep], now=now)
        for bk in keys:
            c = st.get(f"{bk}:{int(dep)}") or {}
            out.setdefault(bk, []).append({"final": c.get("final"),
                                           "ratio": c.get("ratio"),
                                           "n": c.get("n")})
        if i and i % 50 == 0:
            log(f"контроль: {i} зёрен из {seeds}, {time.time() - t0:.0f} с")
    return out


def run_axis(name, axis, packed, gate_of, ctx, launch, keys, seeds=SEEDS,
             now=None, log=print):
    """Ось целиком: ветка «как сейчас» плюс по ветке на порог."""
    base = AG.stats_of(packed, ctx, launch, keys, now=now)
    cells, ctl = {}, {}
    for key, val in axis:
        st, got, unknown = branch(packed, gate_of(val), ctx, launch, keys,
                                  now=now)
        sizes = {bk: len(v) for bk, v in got.items()}
        cells[key] = {"value": val, "stats": st, "unknown": unknown,
                      "sizes": sizes}
        log(f"{name} {key} ({val:g}): взято "
            + ", ".join(f"{bk} {sizes[bk]} из {len(packed[bk])}"
                        for bk in keys if bk in sizes)
            + f", величина неизвестна у {unknown}")
        if seeds:
            ctl[key] = control_rows(packed, sizes, ctx, launch, keys,
                                    seeds=seeds, now=now, log=log)
    return {"name": name, "keys": list(keys), "axis": [
        {"key": k, "value": v} for k, v in axis],
        "base": base, "cells": cells, "control": ctl}


def run(seeds=SEEDS, log=print, now=None, launch=None, ctx=None,
        mem_limit=None, summary_dir=None):
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
    dep_src = Depth(root=summary_dir or SUMMARY_DIR, log=log)
    fams = []
    for fname, cache, packer, keys, live_path in (
            ("короткие книги h24", scache, AG.packed_short,
             list(R.H24_ORDER), R.H24_ARTIFACT),
            ("длинные книги", lcache, AG.packed_long,
             list(R.RULER_ORDER), R.ARTIFACT)):
        packed = packer(cache)
        log(f"{fname}: записей " + ", ".join(f"{k} {len(v)}"
                                             for k, v in sorted(packed.items())))
        axes = [run_axis("запас до пола", FLOOR_GAPS, packed,
                         lambda v: (lambda r, bk: (
                             None if floor_gap(r, bk) is None
                             else floor_gap(r, bk) >= v)),
                         ctx, launch, keys, seeds=seeds, now=now, log=log),
                run_axis("теснота входа", TIGHT_CAPS, packed,
                         lambda v: (lambda r, bk: (
                             None if dep_src.tightness(r) is None
                             else dep_src.tightness(r) <= v)),
                         ctx, launch, keys, seeds=seeds, now=now, log=log)]
        fams.append({"name": fname, "keys": list(keys), "axes": axes,
                     "live": AG.live_of(live_path, keys)})
    return {"families": fams, "seeds": int(seeds), "main_dep": MAIN_DEP,
            "depth": dep_src.why(),
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _r(x):
    return "—" if x is None else f"{float(x):.2f}"


def report(s):
    L = ["# Гейты входа книг DCA: запас до пола и теснота стакана", "",
         "Просьба владельца 2026-09-12 отбирать плохие сделки. Разбор "
         "11–12.09: у безопасной короткой книги ПЯТЬ позиций из тридцати "
         "дали 83 % убытка, у всех плечо 19–25× — то есть пол капитуляции "
         "стоял в 3–4 % цены от входа. Отбор по имени закрыт четырежды, "
         "поэтому здесь меряется ГЕОМЕТРИЯ входа, а не имя.", "",
         "Оси объявлены до прогона: **запас до пола** 3 / 5 / 8 / 12 % "
         "цены и **теснота** — наш нотионал к долларам у лучшей цены "
         "своей стороны, потолок 5 / 2 / 1 / 0.5×. Гейт решает, входить "
         "ли; исход входа он не меняет, и обе ветки считаются на одних и "
         "тех же записях.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}. Числа "
              "брутто.", ""]
    d = s.get("depth") or {}
    if d:
        L += ["**Запись стакана под теснотой:** "
              + ", ".join(f"{k} {v}" for k, v in d.items())
              + ". Решение без записи часа гейт тесноты ПРОПУСКАЕТ и "
              "считает отдельно: «не измерено» фильтром быть не должно "
              "(гейт по ставке funding «работал» именно этим).", ""]
    dep = int(s.get("main_dep") or MAIN_DEP)
    for f in s.get("families") or []:
        L += [f"## {f['name'].capitalize()}", ""]
        live = f.get("live") or {}
        if live and not live.get("why"):
            rows = []
            for bk in f["keys"]:
                lv = live.get(bk)
                base = ((f.get("axes") or [{}])[0].get("base")
                        or {}).get(f"{bk}:{dep}")
                if not lv or not base:
                    continue
                rows.append(f"| {R.ruler_title(bk)} | {lv.get('n')} / "
                            f"{base.get('n')} | {_u(lv.get('usd'))} / "
                            f"{_u(base.get('usd'))} |")
            if rows:
                L += ["Сверка ветки «как сейчас» с живой книгой "
                      f"(депозит ${dep}):", "",
                      "| книга | сделок: живая / замер | Σ $: живая / "
                      "замер |", "|---|--:|--:|"] + rows + [""]
        for ax in f.get("axes") or []:
            L += [f"### {ax['name']}", "",
                  "| книга | порог | сделок | Σ $ | итог | просадка | "
                  "доход/просадка | доля зёрен не хуже |",
                  "|---|---|--:|--:|--:|--:|--:|--:|"]
            for bk in f["keys"]:
                b = (ax.get("base") or {}).get(f"{bk}:{dep}") or {}
                L.append(f"| {R.ruler_title(bk)} | как сейчас | "
                         f"{b.get('n', '—')} | {_u(b.get('usd'))} | "
                         f"{_p(b.get('final'))} | {_p(b.get('max_dd'))} | "
                         f"{_r(b.get('ratio'))} | — |")
                for a in ax.get("axis") or []:
                    c = ((ax.get("cells") or {}).get(a["key"]) or {})
                    st = (c.get("stats") or {}).get(f"{bk}:{dep}") or {}
                    draws = ((ax.get("control") or {}).get(a["key"])
                             or {}).get(bk)
                    sh, n = AG.beat_share(draws, st.get("final"), "final")
                    shr, nr = AG.beat_share(draws, st.get("ratio"), "ratio")
                    L.append(
                        f"| {R.ruler_title(bk)} | {a['value']:g} | "
                        f"{st.get('n', '—')} | {_u(st.get('usd'))} | "
                        f"{_p(st.get('final'))} | {_p(st.get('max_dd'))} | "
                        f"{_r(st.get('ratio'))} | "
                        + ("—" if sh is None
                           else f"итог {100 * sh:.0f} % из {n}, "
                                f"д/п {'—' if shr is None else f'{100 * shr:.0f} %'}")
                        + " |")
            L.append("")
    L += ["## Как читать", "",
          "- Гейт режет число сделок, поэтому рядом стоит доля зёрен, у "
          "которых СЛУЧАЙНАЯ выборка того же размера не хуже. Велика "
          "доля — работает размер, а не гейт.",
          "- Порог правилом здесь не назначается: окно одно, веса модели "
          "эти часы видели, а лучшая ячейка после просмотра — ошибка R5. "
          "Если ось работает, правило объявляется отдельным решением "
          "владельца и наименьшим из работающих порогов.",
          "- Запас до пола и теснота — РАЗНЫЕ вопросы: первый про "
          "геометрию нашей позиции, второй про то, во что мы входим. "
          "Оси считаются независимо и складывать их нельзя.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="гейты входа книг DCA")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    s = run(seeds=a.seeds)
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("гейты входа книг DCA: запас до пола и теснота стакана")
    return 0


if __name__ == "__main__":
    sys.exit(main())
