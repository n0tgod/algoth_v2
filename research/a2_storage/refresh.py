#!/usr/bin/env python3
"""Ежедневная докачка хранилища A2 свежими барами Binance.

Зачем. Хранилище A2 — снимок: 78 партиций, 2020-01 … 2026-06, и оно
само не пополняется. Живой сбор на сервере пишет стакан Bybit, а не
свечи Binance, на которых стоит вся R-серия. Бумажная месячная книга
упёрлась в это первым же прогоном: решения возможны примерно до 14
июля, а дальше покрытие окна оценки β падает ниже половины и дециль
вырождается — ни одного НАСТОЯЩЕГО наблюдения книга записать не может.

Что делает. Определяет край хранилища ПО ДАННЫМ (максимальная метка
времени в последней партиции), качает суточные архивы Binance за дни
после края и пересобирает партиции затронутых месяцев. Ничего своего:
загрузка — `binance_klines.fetch_day` (та же проверка контрольной
суммы), сборка — `build.py` (та же дедупликация по `(symbol,
open_time)`, о необходимости которой предупреждала A1).

Три правила, без которых докачка врала бы молча:

1. **Край берётся из хранилища, а не из имён файлов сырья.** Сырьё
   может лежать скачанным, но не собранным; книга читает партиции, и
   край обязан описывать то, что она видит.
2. **Сегодняшний день не качается.** Суточный архив закрытых суток
   появляется после их конца; неполный день дал бы обрыв ряда там,
   где его нет.
3. **404 — не ошибка.** У архива отсутствующий день обычное дело
   (инструмент ещё не листнут или уже снят), и три попытки на каждый
   такой день превратили бы обход в сутки ожидания пустоты — урок
   `venue.fetch_binary` из L2.

    python3 research/a2_storage/refresh.py --interval 1m
    python3 research/a2_storage/refresh.py --interval 1m --days 3
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
PARQUET = os.path.join(OUT, "parquet")
A1 = os.path.join(RESEARCH, "a1_universe")
sys.path.insert(0, A1)
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import binance_klines as BK                               # noqa: E402
import run_d1 as R                                        # noqa: E402

WORKERS = 16          # у BK свои 6: там месячные файлы по 100 МБ,
#                       здесь суточные по десяткам килобайт
MAX_DAYS = 120        # предохранитель: больше — это не докачка, а A1


def storage_edge(interval="1m"):
    """Последний день, покрытый хранилищем. `None` — хранилища нет.

    Читается ПО ДАННЫМ последней партиции: имя партиции говорит лишь
    про месяц, а внутри он может быть неполным — ровно так и выглядит
    край живого архива.
    """
    d = os.path.join(PARQUET, interval)
    if not os.path.isdir(d):
        return None
    parts = sorted(f for f in os.listdir(d) if f.endswith(".parquet"))
    if not parts:
        return None
    import duckdb
    con = duckdb.connect()
    path = os.path.join(d, parts[-1]).replace("'", "''")
    row = con.execute(
        f"SELECT max(open_time) FROM read_parquet('{path}')").fetchone()
    con.close()
    if not row or row[0] is None:
        return None
    return row[0].date() if hasattr(row[0], "date") else None


def live_symbols(universe_path=None, on_day=None):
    """Символы Binance, живые на площадке исполнения в этот день.

    Мёртвые не качаются: их суточных файлов нет, и обход тратил бы
    время на 404. Новые листинги после снимка универсума докачка не
    видит — их приносит полный прогон A1, и это записано оговоркой.
    """
    p = universe_path or os.path.join(A1, "out", "universe.json")
    with open(p, encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    day = (on_day or date.today()).isoformat()
    out = []
    for _a, v in sorted(assets.items()):
        s = v.get("binance_symbol")
        if not s:
            continue
        last = v.get("last_trading_day")
        if last and last < day:
            continue
        out.append(s)
    return sorted(set(out))


def days_to_fetch(edge, today=None, max_days=MAX_DAYS):
    """Дни от края хранилища до вчера включительно.

    Сегодня не берётся: суточный архив появляется после конца суток, и
    неполный день выглядел бы обрывом ряда.
    """
    if edge is None:
        return []
    today = today or datetime.now(timezone.utc).date()
    first = edge + timedelta(days=1)
    last = today - timedelta(days=1)
    out, d = [], first
    while d <= last and len(out) < max_days:
        out.append(d)
        d += timedelta(days=1)
    return out


def fetch_all(symbols, days, interval, workers=WORKERS, log=print):
    """Скачать суточные файлы. Возвращает (скачано, отсутствует)."""
    jobs = [(s, d) for s in symbols for d in days]
    got = missing = 0
    done = [0]
    t0 = time.time()

    def work(job):
        s, d = job
        return BK.fetch_day(s, interval, d, keep=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ok in ex.map(work, jobs):
            done[0] += 1
            if ok:
                got += 1
            else:
                missing += 1
            if done[0] % 2000 == 0:
                el = (time.time() - t0) / 60
                log(f"  {done[0]}/{len(jobs)} файлов, скачано {got}, "
                    f"нет в архиве {missing}, {el:.1f} мин")
    return got, missing


def rebuild(months, interval, log=print):
    """Пересобрать партиции месяцев ТЕМ ЖЕ `build.py`.

    Вызовом, а не импортом: у сборки свой разбор аргументов и свой
    контроль памяти, и повторять их здесь значило бы завести вторую
    сборку хранилища.
    """
    if not months:
        return 0
    cmd = [sys.executable, os.path.join(HERE, "build.py"),
           "--interval", interval, "--months", ",".join(sorted(months))]
    log(f"  пересборка партиций: {' '.join(cmd[-4:])}")
    r = subprocess.run(cmd, cwd=RESEARCH, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        log(f"    {line}")
    if r.returncode != 0:
        log(f"    ОТКАЗ сборки: {(r.stderr or '').strip()[-400:]}")
    return r.returncode


def report(art, path):
    a = art
    L = ["# Докачка хранилища A2\n",
         f"Прогон: {a['run_at']}, разрешение `{a['interval']}`.\n",
         f"**{a['verdict']}**\n",
         "| величина | значение |", "|---|---|",
         f"| край хранилища до прогона | {a['edge_before']} |",
         f"| край хранилища после | {a['edge_after']} |",
         f"| дней запрошено | {a['days']} |",
         f"| символов | {a['symbols']} |",
         f"| файлов скачано | {a['fetched']} |",
         f"| нет в архиве (норма) | {a['missing']} |",
         f"| партиций пересобрано | {a['months']} |",
         f"| прогон, мин | {a['took_min']} |", "",
         "«Нет в архиве» — не отказ: у инструмента может не быть дня "
         "(ещё не листнут, уже снят, разрыв торгов). Отказом был бы "
         "неподвижный край хранилища при непустой докачке.\n",
         "## Оговорки\n",
         "- новые листинги ПОСЛЕ снимка универсума докачка не видит: "
         "она качает символы из `universe.json`, а новые приносит "
         "полный прогон A1;",
         "- сегодняшний день не качается — суточный архив появляется "
         "после конца суток;",
         "- дедупликация `(symbol, open_time)` делается сборкой, той "
         "же, что собирала хранилище: суточный файл приносит день "
         "целиком и пересекается с уже собранным."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--days", type=int, default=0,
                    help="взять только последние N дней (пилот)")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()

    edge = storage_edge(a.interval)
    if edge is None:
        raise SystemExit(f"нет хранилища {a.interval} — сначала A2")
    days = days_to_fetch(edge)
    if a.days:
        days = days[-a.days:]
    print(f"край хранилища {edge}, дней к докачке {len(days)}")
    if not days:
        print("  хранилище свежее, качать нечего")

    syms = live_symbols(on_day=edge) if days else []
    got = missing = 0
    months = set()
    if days:
        print(f"символов {len(syms)}, файлов к обходу "
              f"{len(syms) * len(days)}")
        got, missing = fetch_all(syms, days, a.interval, a.workers)
        months = {d.isoformat()[:7] for d in days}
        print(f"скачано {got}, нет в архиве {missing}")
        rebuild(months, a.interval)

    edge2 = storage_edge(a.interval)
    moved = edge2 is not None and edge is not None and edge2 > edge
    if not days:
        verdict = f"хранилище свежее: край {edge}, качать нечего"
    elif moved:
        verdict = (f"край хранилища сдвинут {edge} → {edge2}: скачано "
                   f"{got} файлов, пересобрано партиций {len(months)}")
    else:
        verdict = (f"край хранилища НЕ сдвинулся ({edge}) при {got} "
                   f"скачанных файлах — докачка не дошла до партиций")
    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "interval": a.interval,
        "edge_before": str(edge), "edge_after": str(edge2),
        "days": len(days), "symbols": len(syms),
        "fetched": got, "missing": missing, "months": len(months),
        "verdict": verdict,
        "took_min": round((time.time() - t0) / 60, 1),
    }
    p = os.path.join(a.out, f"A2-refresh-{a.interval}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"A2-refresh-{a.interval}.md"))
    print(f"готово: {p} ({art['took_min']} мин)")
    print(f"  {verdict}")
    if not a.no_publish:
        R.publish(f"докачка A2 ({a.interval})")


if __name__ == "__main__":
    main()
