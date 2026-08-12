#!/usr/bin/env python3
"""Зонд: платит ли ЗАШКАЛ прогноза — профиль исхода по крайности.

Вопрос владельца (на примере RSI): можно открывать сто сделок на любых
значениях индикатора, а можно — только когда он зашкаливает. Наш сигнал
и есть такой индикатор; вопрос в том, несёт ли ХВОСТ его распределения
больше, чем середина. Это зонд, а не гипотеза: ни порогов вердикта, ни
объявленной сетки — его дело ответить, стоит ли строить фильтр.

Две оси корзин, объявлены до прогона:

- **rel** — крайность ДЛЯ ЭТОЙ МОНЕТЫ: |прогноз| в разах от медианного
  |прогноза| той же монеты по всему журналу. Это и есть смысл RSI —
  нормировка собственной шкалой. Замер к Келли показал, что сырая
  величина прогноза меряет волатильность монеты, а не силу ситуации
  (внутри монеты связь +0.02, p=0.36) — ось rel это вычитает.
- **raw** — сырой |прогноз| в б.п., контрольная ось: если профили rel и
  raw совпадают, «крайность» — это переодетая волатильность.

Границы корзин — квинтили распределения САМОЙ крайности (приём страницы
волатильности): пороги, выбранные по исходам, были бы перебором без
поправки.

Исход — превышение хода ноги над МЕДИАНОЙ её же сечения за тот же
горизонт, со знаком стороны (контроль одновременной кросс-секцией, как
в L3): без него «зашкал платит» неотличимо от «рынок в тот час ходил».
Вход — открытие первого бара ПОСЛЕ листа (`next_open`, не подарок).
Нет цены — нога пропускается и считается числом, а не нулём (урок A2).

    cd ~/algoth_v2 && setsid nohup .venv/bin/python \\
        research/probe_extreme/probe.py > /tmp/extreme.log 2>&1 &
"""
import argparse
import collections
import json
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))
sys.path.insert(0, os.path.join(RESEARCH, "s9_sweep"))

HORIZONS_H = (1, 4)          # часовая книга и главный горизонт
N_BUCKETS = 5                # квинтили крайности
MIN_SYM_LEGS = 20            # медиана |прогноза| монеты — не по трём точкам
ENTRY_TOL_SEC = 600          # входа нет в 10 минут — нет измерения
EXIT_TOL = 0.2               # выход не раньше 80 % горизонта
ROUND_COST_BP = 11.0         # круг тейкера, для чтения профиля


def unbuffer_output():
    """Печатать построчно, даже когда вывод уходит в файл.

    Урок D1, нарушенный здесь в третий раз по проекту: отцепленный
    прогон с перенаправлением в файл молчит блоками буфера и снаружи
    неотличим от повисшего — владелец увидел ровно это. Ставится В
    КОДЕ, а не ключом `-u`: команду набирают руками.
    """
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass


def load_legs(paths, log=print):
    """Ноги из журнала листов: (время, час, рука, монета, прогноз, цена).

    Берётся ВСЁ сечение, а не прошедшие гейт: профиль строится по
    распределению целиком, иначе хвост сравнивать не с чем.
    """
    legs = []
    for path in paths:
        try:
            fh = open(path, encoding="utf-8")
        except OSError:
            log(f"{path}: журнала нет — пропуск")
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                at = rec.get("written_at")
                if not at:
                    continue
                for arm, rows in (rec.get("arms") or {}).items():
                    for r in rows or []:
                        fwd, px = r.get("fwd"), r.get("px")
                        if not fwd or not px:
                            continue
                        legs.append({
                            "at": float(at), "hour": rec.get("hour"),
                            "arm": arm, "sym": r.get("sym"),
                            "fwd": float(fwd)})
    legs.sort(key=lambda g: (g["sym"], g["at"]))
    return legs


def moves_for_symbol(bars, legs):
    """Ход цены по горизонтам для ног ОДНОЙ монеты.

    Вход — открытие первого бара после листа (в пределах допуска),
    выход — закрытие последнего бара до конца горизонта; выход раньше
    80 % горизонта означает дыру записи, и нога не измерена.
    """
    for lg in legs:
        ent = next((b for b in bars
                    if lg["at"] < b[0] <= lg["at"] + ENTRY_TOL_SEC), None)
        if ent is None or not ent[1]:
            continue
        lg["entry_t"], lg["entry_px"] = ent[0], ent[1]
        for h in HORIZONS_H:
            end = lg["entry_t"] + h * 3600
            ex = None
            for b in bars:
                if b[0] > end:
                    break
                if b[0] >= lg["entry_t"]:
                    ex = b
            if ex is None or ex[0] < lg["entry_t"] + (1 - EXIT_TOL) * h * 3600:
                continue
            lg[f"move_{h}"] = (ex[4] / lg["entry_px"] - 1) * 1e4


def excess_by_section(legs):
    """Превышение над медианой СВОЕГО сечения, со знаком стороны.

    Сечение — (лист, рука): все измеренные ноги того же листа. Ноги
    сечений тоньше десяти имён не меряются: медиана трёх точек — не фон
    (ловушка тонкого фона из T1).
    """
    by_sheet = collections.defaultdict(list)
    for lg in legs:
        by_sheet[(lg["at"], lg["arm"])].append(lg)
    for rows in by_sheet.values():
        for h in HORIZONS_H:
            got = [r[f"move_{h}"] for r in rows if f"move_{h}" in r]
            if len(got) < 10:
                continue
            med = st.median(got)
            for r in rows:
                if f"move_{h}" in r:
                    sign = 1.0 if r["fwd"] > 0 else -1.0
                    r[f"ex_{h}"] = sign * (r[f"move_{h}"] - med)


def extremeness(legs, log=print):
    """Оси крайности: rel — в разах от обычного прогноза монеты, raw — б.п.

    Монеты, у которых меньше `MIN_SYM_LEGS` ног, оси rel не получают:
    медиана по трём точкам назвала бы крайним что угодно.
    """
    by_sym = collections.defaultdict(list)
    for lg in legs:
        by_sym[lg["sym"]].append(abs(lg["fwd"]))
    med = {s: st.median(v) for s, v in by_sym.items()
           if len(v) >= MIN_SYM_LEGS and st.median(v) > 0}
    thin = sum(1 for lg in legs if lg["sym"] not in med)
    if thin:
        log(f"без оси rel (тонкая монета): {thin} ног")
    for lg in legs:
        lg["raw"] = abs(lg["fwd"])
        if lg["sym"] in med:
            lg["rel"] = abs(lg["fwd"]) / med[lg["sym"]]


def bucket_edges(vals, n=N_BUCKETS):
    """Границы корзин — квантили распределения самой величины."""
    xs = sorted(vals)
    if len(xs) < n * 10:
        return None
    return [xs[int(len(xs) * i / n)] for i in range(1, n)]


def profile(legs, axis, h):
    """Профиль исхода по корзинам крайности, с «без лучшего имени».

    Возвращает (границы, строки корзин). Ловушка TUT обязательна: хвост
    крайности может оказаться одним разгоном, и колонка без лучшего
    имени различает правило и лотерею.
    """
    got = [lg for lg in legs if axis in lg and f"ex_{h}" in lg]
    edges = bucket_edges([lg[axis] for lg in got])
    if edges is None:
        return None, []
    rows = []
    for i in range(N_BUCKETS):
        lo = edges[i - 1] if i else None
        hi = edges[i] if i < N_BUCKETS - 1 else None
        sub = [lg for lg in got
               if (lo is None or lg[axis] >= lo)
               and (hi is None or lg[axis] < hi)]
        if not sub:
            rows.append({"bucket": i + 1, "n": 0})
            continue
        ex = [lg[f"ex_{h}"] for lg in sub]
        by_sym = collections.defaultdict(float)
        for lg in sub:
            by_sym[lg["sym"]] += lg[f"ex_{h}"]
        top_sym, top_v = max(by_sym.items(), key=lambda kv: kv[1])
        rows.append({
            "bucket": i + 1,
            "lo": None if lo is None else round(lo, 2),
            "hi": None if hi is None else round(hi, 2),
            "n": len(ex),
            "dates": len({time.strftime("%Y-%m-%d", time.gmtime(lg["at"]))
                          for lg in sub}),
            "syms": len(by_sym),
            "mean_bp": round(sum(ex) / len(ex), 1),
            "med_bp": round(st.median(ex), 1),
            "pos": round(sum(1 for v in ex if v > 0) / len(ex), 3),
            "total_bp": round(sum(ex), 1),
            "top_sym": top_sym,
            "wo_top_mean_bp": round(
                (sum(ex) - top_v) / max(1, len(ex) - sum(
                    1 for lg in sub if lg["sym"] == top_sym)), 1),
        })
    return edges, rows


def reading(art):
    """Чтение профиля — по объявленным исходам, а не по лучшей клетке."""
    out = []
    for axis in ("rel", "raw"):
        for h in HORIZONS_H:
            rows = [r for r in art["profiles"][f"{axis}_{h}h"]["rows"]
                    if r.get("n")]
            if len(rows) < N_BUCKETS:
                out.append(f"{axis}/{h}h: корзины пусты — не измерено")
                continue
            top, mid = rows[-1], rows[len(rows) // 2]
            step = top["mean_bp"] - mid["mean_bp"]
            frag = (top["wo_top_mean_bp"] <= 0 < top["mean_bp"])
            if frag:
                out.append(f"{axis}/{h}h: хвост держит одно имя "
                           f"({top['top_sym']}) — лотерея, не правило")
            elif step > ROUND_COST_BP / 2 and top["mean_bp"] > 0:
                out.append(f"{axis}/{h}h: ступенька +{step:.1f} б.п. "
                           f"(зашкал {top['mean_bp']:+.1f}, середина "
                           f"{mid['mean_bp']:+.1f}) — фильтр настоящий")
            else:
                out.append(f"{axis}/{h}h: плоско (зашкал "
                           f"{top['mean_bp']:+.1f}, середина "
                           f"{mid['mean_bp']:+.1f}) — фильтр по "
                           f"крайности означает торговать реже, а не "
                           f"лучше")
    return out


def report(art, path):
    L = [
        "# Зонд: платит ли зашкал прогноза",
        "",
        f"Прогон: {art['run_at']} · ног в журнале {art['legs_total']}, "
        f"измерено {art['legs_measured']} · листов {art['sheets']} · "
        f"монет {art['syms']}",
        "",
        "Исход — превышение хода ноги над медианой её же сечения за тот "
        "же горизонт, со знаком стороны. Круг издержек "
        f"{ROUND_COST_BP:g} б.п. на ногу. Это зонд: порогов вердикта "
        "нет, оценка оптимистична (веса видели эти часы).",
        "",
    ]
    names = {"rel": "крайность для монеты (в разах от её обычного "
                    "прогноза) — ось вопроса",
             "raw": "сырой |прогноз|, б.п. — контроль на волатильность"}
    for axis in ("rel", "raw"):
        for h in HORIZONS_H:
            pf = art["profiles"][f"{axis}_{h}h"]
            L += [f"## {names[axis]} · горизонт {h} ч", ""]
            L += ["| корзина | границы | ног | дат | монет | среднее "
                  "б.п. | медиана | доля + | без лучшего имени |",
                  "|---|---|---|---|---|---|---|---|---|"]
            for r in pf["rows"]:
                if not r.get("n"):
                    L.append(f"| {r['bucket']} | — | 0 | — | — | — | — "
                             f"| — | — |")
                    continue
                b = (f"{'' if r['lo'] is None else r['lo']}…"
                     f"{'' if r['hi'] is None else r['hi']}")
                L.append(
                    f"| {r['bucket']} | {b} | {r['n']} | {r['dates']} | "
                    f"{r['syms']} | {r['mean_bp']:+.1f} | "
                    f"{r['med_bp']:+.1f} | {r['pos']:.2f} | "
                    f"{r['wo_top_mean_bp']:+.1f} ({r['top_sym']}) |")
            L.append("")
    L += ["## Чтение", ""] + [f"- {x}" for x in art["reading"]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def run(sheets, root, src=None, log=print):
    import sweep as SW
    legs = load_legs(sheets, log=log)
    if not legs:
        raise SystemExit("журнал листов пуст — мерить нечего")
    log(f"ног в журнале {len(legs)}, "
        f"монет {len({g['sym'] for g in legs})} — начинаю обход баров")
    extremeness(legs, log=log)
    by_sym = collections.defaultdict(list)
    for lg in legs:
        by_sym[lg["sym"]].append(lg)
    said = time.time()
    for i, (sym, rows) in enumerate(sorted(by_sym.items())):
        if time.time() - said > 30:
            log(f"  бары: монета {i}/{len(by_sym)}")
            said = time.time()
        t0 = min(r["at"] for r in rows)
        t1 = max(r["at"] for r in rows) + max(HORIZONS_H) * 3600 + 600
        get = src.bars if src else (
            lambda s, a, b: SW.read_bars(root, s, a, b))
        moves_for_symbol(get(sym, t0, t1) or [], rows)
    excess_by_section(legs)
    measured = sum(1 for lg in legs if any(
        f"ex_{h}" in lg for h in HORIZONS_H))
    art = {
        "run_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "legs_total": len(legs), "legs_measured": measured,
        "sheets": len({(lg["at"], lg["arm"]) for lg in legs}),
        "syms": len(by_sym),
        "buckets": N_BUCKETS, "cost_bp": ROUND_COST_BP,
        "profiles": {},
    }
    for axis in ("rel", "raw"):
        for h in HORIZONS_H:
            edges, rows = profile(legs, axis, h)
            art["profiles"][f"{axis}_{h}h"] = {
                "edges": edges and [round(e, 3) for e in edges],
                "rows": rows}
    art["reading"] = reading(art)
    return art


def main():
    unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", nargs="+", default=[os.path.join(
        RESEARCH, "s8_loop", "out", "model_sit", "sheets.jsonl")])
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--http", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    name = "extreme-profile" + (f"-{a.tag}" if a.tag else "")
    out = os.path.join(HERE, "out", name + ".md")
    # Каталог артефактов — ДО счёта (урок турнира и зонда режимов:
    # записанный урок не защищает новый модуль сам собой).
    os.makedirs(os.path.dirname(out), exist_ok=True)
    src = None
    if a.http:
        import sweep as SW
        src = SW.HttpBars(a.http, a.key)
    art = run(a.sheets, a.root, src=src)
    with open(out.replace(".md", ".json"), "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    report(art, out)
    print("отчёт:", out)
    for x in art["reading"]:
        print(" ", x)
    if not a.no_publish:
        # Публикация — часть прогона (урок width.py, третий раз).
        sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
        import run_d1 as RD                                # noqa: E402
        RD.publish("Зонд: профиль исхода по крайности прогноза"
                   + (f" ({a.tag})" if a.tag else ""))


if __name__ == "__main__":
    main()
