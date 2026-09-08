#!/usr/bin/env python3
"""Догон рядов funding площадки исполнения до сегодняшнего дня.

Сборщик A1 (`bybit_api.py`) возобновляем по СУЩЕСТВОВАНИЮ файла: символ с
файлом не перекачивается, то есть ряды кончаются на дне того прогона и
не растут никогда. Замер издержек бумажных DCA-книг (`dca_paper/costs.py`)
это и обнаружил: 513 рядов, покрытие позиций 0 % — все позиции книг
позже последней точки любого ряда. Этот модуль дописывает ХВОСТ каждого
ряда с последней сохранённой точки (минус сутки перекрытия, повторы
снимаются по времени) по сегодня; тем же кодом пагинации, что у
сборщика (`collect_funding_symbol`), и тем же форматом файла — второй
копии разбора страниц нет.
Справочник инструментов и сводку A1 не трогает.

Символы: все `bybit_symbol` универсума, те, у кого уже есть файл, и те,
что площадка торгует СЕЙЧАС (универсум — снимок на момент времени, и
листинги после него в нём не появляются: 45 имён живых книг на 08.09
были именно такими, и ставка на входе у них была «неизвестна»).
Ряд — класс B (`docs/DATA-SAFETY.md`): переписывается ЦЕЛИКОМ из
объединения старого и нового, сперва во временный файл, потом атомарной
заменой; неудача сети у символа оставляет прежний файл нетронутым и
считается числом. Кэш ответов у ключа хвоста несёт ДЕНЬ прогона: вчерашний
ответ на тот же запрос не годится сегодня.

Отчёт: `out/funding-refresh.md` (край рядов до и после, добавлено точек,
отказов), публикуется сам. Запуск очередью: `run research/a1_universe/funding_refresh.py`.
"""

import csv
import gzip
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bybit_api as B                                         # noqa: E402

OUT = B.OUT
OVERLAP_D = 1                # перекрытие с хвостом ряда: повтор снимается


def read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rd = csv.reader(f)
        head = next(rd, None)
        if not head or [c.strip().lower() for c in head[:2]] != \
                ["funding_time", "funding_rate"]:
            raise ValueError(f"{path}: незнакомый заголовок {head}")
        return [(r[0], r[1]) for r in rd if len(r) >= 2]


def last_day(rows):
    if not rows:
        return None
    return datetime.fromisoformat(max(r[0] for r in rows)).date()


def merge(old, new):
    """Объединение по ВРЕМЕНИ: новая точка побеждает старую с той же меткой."""
    by = {t: r for (t, r) in old}
    for (t, r) in new:
        by[t] = r
    return sorted(by.items())


def refresh_symbol(sym, today, fetch=None, read=None):
    """Хвост одного символа. Возвращает (было, добавлено, край, ошибка)."""
    fetch = fetch or B.collect_funding_symbol
    read = read or read_rows
    path = os.path.join(B.FUNDING_DIR, f"{sym}.csv.gz")
    old = read(path) if os.path.exists(path) else []
    ld = last_day(old)
    start = (ld - timedelta(days=OVERLAP_D)) if ld else today - timedelta(days=3650)
    if ld is not None and ld >= today:
        return len(old), 0, ld.isoformat(), None
    try:
        new = fetch(sym, start, today)
    except Exception as e:                       # noqa: BLE001 — сеть
        return len(old), 0, ld.isoformat() if ld else None, str(e)[:120]
    if not new:
        return len(old), 0, ld.isoformat() if ld else None, None
    rows = merge(old, new)
    added = len(rows) - len(old)
    tmp = path + ".tmp"
    write_tmp(rows, tmp)                          # сперва во временное имя
    os.replace(tmp, path)                         # потом атомарно на место
    return len(old), added, last_day(rows).isoformat(), None


def write_tmp(rows, tmp):
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["funding_time", "funding_rate"])
        w.writerows(rows)


def traded_now(log=print):
    """Символы, которые площадка торгует СЕЙЧАС.

    Универсум — снимок на момент времени, и листинги после него в нём не
    появляются сами: на 2026-09-08 книги торговали 45 именами, которых в
    универсуме нет вовсе, и ряда funding у них не было ни одного. Для
    правила, читающего ставку на входе (гейт короткой стороны общего
    счёта), отсутствие ряда означает «ставка неизвестна» — то есть
    отставший справочник закрывал бы книгу молча.

    Отказ сети — не пустой список, а причина словами: пустой список
    здесь читался бы как «площадка ничего не торгует».
    """
    try:
        res = B.api_get("/v5/market/instruments-info",
                        {"category": B.CATEGORY, "status": "Trading",
                         "limit": 1000},
                        f"instr_trading_{date.today().isoformat()}")
    except Exception as e:                                # noqa: BLE001
        log(f"справочник торгуемых не получен: {e}")
        return set()
    got = {it["symbol"] for it in (res.get("list") or [])
           if str(it.get("symbol", "")).endswith("USDT")}
    log(f"площадка торгует сейчас: {len(got)} перпов USDT")
    return got


def symbols(assets, extra=None):
    out = {v["bybit_symbol"] for v in assets.values() if v.get("bybit_symbol")}
    if os.path.isdir(B.FUNDING_DIR):
        out |= {f[:-len(".csv.gz")] for f in os.listdir(B.FUNDING_DIR)
                if f.endswith(".csv.gz")}
    out |= set(extra or ())
    return sorted(out)


def run(syms, today, workers=B.WORKERS, log=print, fetch=None):
    t0 = time.time()
    res, done, said = {}, [0], time.time()

    def work(sym):
        r = refresh_symbol(sym, today, fetch=fetch)
        done[0] += 1
        if time.time() - said > 30:
            log(f"  {done[0]}/{len(syms)}")
        return sym, r
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sym, r in ex.map(work, syms):
            res[sym] = {"had": r[0], "added": r[1], "end": r[2], "error": r[3]}
    ends = sorted(v["end"] for v in res.values() if v["end"])
    return {"symbols": len(syms), "added": sum(v["added"] for v in res.values()),
            "errors": sum(1 for v in res.values() if v["error"]),
            "empty": sum(1 for v in res.values() if not v["end"]),
            "end_min": ends[0] if ends else None,
            "end_median": ends[len(ends) // 2] if ends else None,
            "end_max": ends[-1] if ends else None,
            "today": today.isoformat(), "secs": round(time.time() - t0, 1),
            "per_symbol": res}


def report(s):
    errs = [k for k, v in s["per_symbol"].items() if v["error"]]
    return "\n".join([
        "# Догон рядов funding площадки исполнения", "",
        f"Прогон {s['today']}: символов {s['symbols']}, добавлено точек "
        f"{s['added']}, отказов сети {s['errors']}, пустых рядов {s['empty']}, "
        f"{s['secs']} с.", "",
        f"Край рядов после догона: минимум {s['end_min']}, медиана "
        f"{s['end_median']}, максимум {s['end_max']}. Ряд, край которого "
        "старше сегодняшнего дня, у площадки кончился (контракт снят) либо "
        "отказал сетью — отказы поимённо ниже.", "",
        ("Отказы: " + ", ".join(errs[:40]) + (" …" if len(errs) > 40 else "")
         if errs else "Отказов нет."), ""])


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "universe.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    live = traded_now(log=lambda m: print(m, flush=True))
    syms = symbols(assets, extra=live)
    known = {v["bybit_symbol"] for v in assets.values()
             if v.get("bybit_symbol")}
    new = sorted(live - known)
    if new:
        print(f"торгуются, но в универсуме их нет: {len(new)} "
              f"({', '.join(new[:8])}{'…' if len(new) > 8 else ''}) — "
              "ряды им качаются тоже", flush=True)
    if a.limit:
        syms = syms[:a.limit]
    today = datetime.now(timezone.utc).date()
    print(f"funding: догон {len(syms)} символов по {today}", flush=True)
    s = run(syms, today, log=lambda m: print(m, flush=True))
    slim = dict(s)
    slim["per_symbol"] = {k: v for k, v in s["per_symbol"].items()
                          if v["error"] or v["added"]}
    with open(os.path.join(OUT, "funding-refresh.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, "funding-refresh.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"A1: догон рядов funding до {today} (+{s['added']} точек)")


if __name__ == "__main__":
    main()
