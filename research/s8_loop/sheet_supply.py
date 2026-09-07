#!/usr/bin/env python3
"""Подача листа сечения по суткам и по руке: сколько решений вообще есть.

Зачем. Разрез DCA-книг по руке (2026-09-07) показал провал активности:
20–22.08 книга брала по 300–400 позиций в сутки, с 26.08 — единицы, и
провал НЕСИММЕТРИЧЕН по рукам (у деревьев решений под гейтом почти не
осталось, у сети десятки). Итог за окно об этом молчит: месяц с одним
всплеском и месяц ровной торговли дают одну и ту же сумму. Прежде чем
объяснять провал рынком, надо разделить три причины, и разделяются они
только числом:

1. **рынка нет** — строк в листе столько же, но обещания стали мельче
   (медиана |прогноза| падает у ОБЕИХ рук);
2. **рука сдулась** — у одной руки медиана падает, у другой нет;
3. **лист похудел** — строк в листе стало меньше (сканер отдаёт меньше
   имён: флэт-фильтр, универсум, отбор в самом цикле).

Считается по журналу листов `s8_loop/out/model_sit/sheets.jsonl` — той
же геометрией, что строит ноги (`s10_policy.tournament._leg`), второй
копии правила не заводится. По суткам и руке печатаются: строк листа,
из них с путём (есть `mae/mfe`), медиана |прогноза| и медиана RR, и
сколько прошло каждый гейт по отдельности — край ≥ 33 б.п., RR ≥ 2 и
оба сразу (гейт книг DCA).

Замер НИЧЕГО не чинит и ни на что не влияет: он читает журнал листов и
пишет отчёт. Живой книги `sit_lo` (низкий RR) он тоже не описывает —
у неё гейт RR другой, и её подача считается своей колонкой (RR ≤ 1.5).

Запуск: run research/s8_loop/sheet_supply.py
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "s10_policy"))
import tournament as TNT                                     # noqa: E402
import trades as TR                                          # noqa: E402

OUT = os.path.join(HERE, "out")
SHEETS = os.path.join(HERE, "out", "model_sit", "sheets.jsonl")
EDGE_BP = 33.0                        # гейт края книг (`sit`, DCA)
MIN_RR = 2.0                          # гейт отношения книги `sit` и DCA
LO_RR = 1.5                           # потолок отношения живой книги `sit_lo`
ARMS = ("gbm", "nn")
ARM_TITLE = {"gbm": "деревья", "nn": "сеть"}


def _median(xs):
    if not xs:
        return None
    ys = sorted(xs)
    m = len(ys) // 2
    return ys[m] if len(ys) % 2 else 0.5 * (ys[m - 1] + ys[m])


def blank():
    return {"rows": 0, "with_path": 0, "edge": 0, "rr": 0, "both": 0,
            "lo": 0, "fwd": [], "rrs": []}


def scan(path=None, log=print, limit=None):
    """Журнал листов → сутки × рука × числа подачи."""
    path = path or SHEETS
    days, hours, bad = {}, 0, 0
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        log(f"{path}: журнала листов нет")
        return {}, 0
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            hour = rec.get("hour")
            at = rec.get("written_at") or ((TR._ts(hour) or 0) + 3600)
            if not at:
                bad += 1
                continue
            hours += 1
            day = time.strftime("%Y-%m-%d", time.gmtime(float(at)))
            for arm, rows in (rec.get("arms") or {}).items():
                cell = days.setdefault(day, {}).setdefault(arm, blank())
                for row in rows or []:
                    cell["rows"] += 1
                    lg = TNT._leg(row, arm, hour, float(at))
                    if lg is None:
                        continue
                    cell["with_path"] += 1
                    fwd, rr = abs(float(lg["fwd"])), lg.get("rr")
                    cell["fwd"].append(fwd)
                    if rr is not None:
                        cell["rrs"].append(rr)
                    ok_e = fwd >= EDGE_BP
                    ok_r = rr is not None and rr >= MIN_RR
                    cell["edge"] += 1 if ok_e else 0
                    cell["rr"] += 1 if ok_r else 0
                    cell["both"] += 1 if (ok_e and ok_r) else 0
                    cell["lo"] += 1 if (ok_e and rr is not None
                                        and rr <= LO_RR) else 0
            if limit and hours >= limit:
                break
    log(f"листов {hours}, битых строк {bad}, суток {len(days)}")
    return days, hours


def summarize(days):
    out = {}
    for day, arms in days.items():
        out[day] = {}
        for arm, c in arms.items():
            out[day][arm] = {
                "rows": c["rows"], "with_path": c["with_path"],
                "edge": c["edge"], "rr": c["rr"], "both": c["both"],
                "lo": c["lo"],
                "fwd_median": (round(_median(c["fwd"]), 1)
                               if c["fwd"] else None),
                "rr_median": (round(_median(c["rrs"]), 2)
                              if c["rrs"] else None)}
    return out


def diagnose(s, tail_days=7, head_days=7):
    """Три причины провала подачи, разделённые числом.

    Сравниваются последние `tail_days` суток с первыми `head_days`
    суток ОКНА, а не с «лучшим днём»: лучший день выбирается после
    просмотра, и такой выбор уже был ошибкой R5.
    """
    ds = sorted(s)
    if len(ds) < head_days + tail_days:
        return {"why": f"суток {len(ds)} — меньше {head_days + tail_days}"}
    head, tail = ds[:head_days], ds[-tail_days:]
    out = {"head": [head[0], head[-1]], "tail": [tail[0], tail[-1]], "arms": {}}
    for arm in ARMS:
        def agg(dd, key):
            return sum((s[d].get(arm) or {}).get(key, 0) for d in dd)

        def med(dd):
            xs = [(s[d].get(arm) or {}).get("fwd_median") for d in dd]
            return _median([x for x in xs if x is not None])
        out["arms"][arm] = {
            "rows_head": agg(head, "rows"), "rows_tail": agg(tail, "rows"),
            "both_head": agg(head, "both"), "both_tail": agg(tail, "both"),
            "fwd_med_head": med(head), "fwd_med_tail": med(tail)}
    return out


def run(path=None, log=print, limit=None):
    t0 = time.time()
    days, hours = scan(path=path, log=log, limit=limit)
    s = summarize(days)
    return {"at": time.time(), "secs": round(time.time() - t0, 1),
            "hours": hours, "days": s, "diagnose": diagnose(s),
            "edge_bp": EDGE_BP, "min_rr": MIN_RR, "lo_rr": LO_RR,
            "path": path or SHEETS}


def _n(x):
    return "—" if x is None else f"{x:g}"


def report(s):
    L = ["# Подача листа сечения по суткам и по руке", "",
         "Разрез DCA-книг по руке (07.09) показал провал активности: "
         "20–22.08 книга брала по 300–400 позиций в сутки, с 26.08 — "
         "единицы, и провал несимметричен по рукам. Здесь считается "
         "ПОДАЧА: сколько решений лист вообще отдаёт, какой у них край и "
         "отношение. Геометрия — та же функция, что строит ноги книг "
         "(`tournament._leg`), второй копии правила нет.", "",
         f"Листов прочитано: {s['hours']}, суток {len(s['days'])}. Гейты: "
         f"край ≥ {_n(s['edge_bp'])} б.п., RR ≥ {_n(s['min_rr'])} (книга "
         f"`sit` и книги DCA); колонка «низкий RR» — край ≥ "
         f"{_n(s['edge_bp'])} при RR ≤ {_n(s['lo_rr'])}, это подача живой "
         "книги `sit_lo`.", "",
         "| сутки | рука | строк листа | с путём | край | RR | оба (гейт книг) | низкий RR | медиана \\|прогноза\\| | медиана RR |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for day in sorted(s["days"]):
        for arm in ARMS:
            c = (s["days"][day] or {}).get(arm)
            if not c:
                continue
            L += [f"| {day} | {ARM_TITLE.get(arm, arm)} | {c['rows']} | "
                  f"{c['with_path']} | {c['edge']} | {c['rr']} | {c['both']} | "
                  f"{c['lo']} | {_n(c['fwd_median'])} | {_n(c['rr_median'])} |"]
    d = s.get("diagnose") or {}
    L += ["", "## Что именно упало", ""]
    if d.get("why"):
        L += [f"Разделить причины нечем: {d['why']}.", ""]
    else:
        L += [f"Сравниваются первые сутки окна ({d['head'][0]} … "
              f"{d['head'][1]}) с последними ({d['tail'][0]} … "
              f"{d['tail'][1]}). Границы объявлены по краям окна, а не "
              "выбраны после просмотра.", "",
              "| рука | строк листа: начало → конец | под гейтом книг: начало → конец | медиана \\|прогноза\\|: начало → конец |",
              "|---|---|---|---|"]
        for arm in ARMS:
            a = d["arms"][arm]
            L += [f"| {ARM_TITLE.get(arm, arm)} | {a['rows_head']} → "
                  f"{a['rows_tail']} | {a['both_head']} → {a['both_tail']} | "
                  f"{_n(a['fwd_med_head'])} → {_n(a['fwd_med_tail'])} |"]
        L += ["", "Читать так: строк столько же, а медиана прогноза упала у "
              "ОБЕИХ рук — рынок стих; упала у одной — сдулась рука; строк "
              "стало меньше при той же медиане — похудел сам лист (флэт-"
              "фильтр, универсум, отбор цикла), и тогда искать надо в "
              "цикле, а не в модели.", ""]
    L += ["## Чего замер НЕ говорит", "",
          "- Он не судит качество решений — только их наличие. Рука, "
          "отдающая больше решений, не тем самым лучше.",
          "- Он не описывает живую книгу `sit_lo` целиком: у неё свой "
          "гейт (RR ≤ 1.5), и здесь она стоит одной колонкой подачи.",
          "- Он не чинит подачу и не трогает цикл: это чтение журнала "
          "листов и отчёт.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="подача листа по суткам и руке")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--limit", type=int, default=None, help="листов, смоук")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    s = run(limit=a.limit)
    name = f"SHEET-supply-{a.tag}" if not a.limit else f"SHEET-supply-smoke-{a.tag}"
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"S8: подача листа по суткам и руке ({a.tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
