#!/usr/bin/env python3
"""
L2 — открытый интерес по всему крипто-универсуму, архив Binance.

Спека 06, раздел 10. Зонд L1 работал на двенадцати активах; вердикт
раздела 9 выносится на **подтверждающей** части универсума, то есть на
всех остальных. Число независимых эпизодов и есть бюджет доказательства
этой гипотезы, а растёт оно с шириной универсума, а не с длиной истории
(§2 спеки) — поэтому сбор широкий, а не глубокий.

Размер работы, посчитанный по универсуму A1, а не на глаз
------------------------------------------------------------

621 крипто-актив с историей Binance пересекает окно 2024-01…2026-06.
Суммарно **362 784 символо-дня** (медиана 586 дней на актив), файл
суточного `metrics` весит около 11 КБ, то есть примерно 4 ГБ трафика.
Хранить сырые архивы незачем: из каждой строки берутся два числа.
Итоговые ряды — около 1.7 ГБ.

Устройство прогона
------------------

**Единица возобновления — символ.** Готовый `<SYMBOL>.npz` означает,
что символ собран целиком; повторный запуск его пропускает. Зипы на
диск не кладутся (`cache=False`): единица возобновления крупнее файла,
и кэш только съел бы 4 ГБ.

**Прерывание прогона не должно портить состояние, и это проверено
жизнью дважды.** В A2 перезагрузка VPS заставила сборку доложить
дельту прогона вместо состояния хранилища; здесь ряд пишется через
временный файл, а манифест — атомарной заменой, потому что перезапись
поверх себя оставляет после обрыва обрезанный JSON, на котором падает
уже следующий запуск. Если манифест всё же потерян, состояние
**читается с диска**, а не берётся из утверждения: готовые ряды
пересчитываются в манифест, и прогон продолжается с того же места.

**Дни берутся из интервалов жизни инструмента**, а не подряд по
календарю. Универсум A1 знает, когда инструмент листингован и когда
перестал торговаться; запрашивать дни вне этих интервалов значит
получить 404 на половине обхода.

**Отсутствующий день не является ошибкой, но считается.** Архив
Binance уже дважды ловили на дырах (месячные файлы 2022-02 и 2022-04).
Доля пропусков идёт в манифест числом — если она велика, это находка, а
не мелочь.

Что НЕ делается здесь
---------------------

Отбор событий, отсечение окна делистинга (§7.1 спеки), фильтр по
минимальному интересу (§7.3). Всё это — L3. Сбор обязан быть тупым:
любое правило, применённое при сборе, потом невозможно ни изменить, ни
измерить.

    .venv/bin/python research/l2_data/oi_binance.py --limit 3   # пилот
    .venv/bin/python research/l2_data/oi_binance.py             # весь универсум
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
A1_OUT = os.path.join(RESEARCH, "a1_universe", "out")
OUT = os.path.join(HERE, "out")
SERIES = os.path.join(OUT, "oi_binance")

sys.path.insert(0, RESEARCH)
from common.oi_metrics import (                             # noqa: E402
    OI_COL, OI_USD_COL, days_between, metrics_url, parse_metrics,
)
from common.venue import fetch_binary                       # noqa: E402

UA = "l2-oi-binance/1.0"
START = "2024-01-01"          # окно спеки 06; итерация §9.3 расширяет до 2020
END = "2026-06-30"
WORKERS = 16                  # обход по дням внутри символа


def universe_symbols():
    """Крипто-активы с историей Binance и их интервалы жизни."""
    with open(os.path.join(A1_OUT, "universe.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    out = {}
    for name, v in assets.items():
        if v.get("asset_class") != "crypto" or not v.get("binance_symbol"):
            continue
        out[v["binance_symbol"]] = {
            "asset": name,
            "intervals": v.get("intervals", []),
            "last_trading_day": v.get("last_trading_day"),
            "delisted": bool(v.get("delisted")),
        }
    return out


def days_of(intervals, start, end):
    """Дни жизни инструмента внутри окна, без дублей и по порядку."""
    w0, w1 = date.fromisoformat(start), date.fromisoformat(end)
    got = set()
    for s, e in intervals:
        a, b = date.fromisoformat(s), date.fromisoformat(e)
        a, b = max(a, w0), min(b, w1)
        if a <= b:
            got.update(days_between(a.isoformat(), b.isoformat()))
    return sorted(got)


def collect_symbol(symbol, days, workers):
    """Ряд интереса по символу. Возвращает `(массивы, сводка)`."""
    missing = []

    def one(day):
        try:
            raw = fetch_binary(metrics_url(symbol, day), OUT, cache=False,
                               user_agent=UA)
        except FileNotFoundError:
            missing.append(day)
            return []
        except Exception as e:                        # noqa: BLE001
            missing.append(day)
            print(f"  {symbol} {day}: {str(e)[:70]}", file=sys.stderr)
            return []
        return parse_metrics(raw, (OI_COL, OI_USD_COL))

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(one, days):
            rows += part
    if not rows:
        return None, {"days": len(days), "days_missing": len(missing),
                      "rows": 0}
    rows.sort()
    # Дедупликация по метке: архив уже приносил один и тот же интервал
    # дважды (A1, дозакрытие суточными файлами). Ключ — время.
    t, oi, usd = [], [], []
    last = None
    for r in rows:
        if r[0] == last:
            continue
        last = r[0]
        t.append(r[0])
        oi.append(r[1])
        usd.append(r[2])
    arr = (np.array(t, dtype=np.int64),
           np.array(oi, dtype=np.float32),
           np.array(usd, dtype=np.float32))
    return arr, {
        "days": len(days), "days_missing": len(missing), "rows": len(t),
        "dups": len(rows) - len(t),
        "first": int(arr[0][0]), "last": int(arr[0][-1]),
        "median_oi_usd": float(np.median(arr[2])),
    }


def write_json(path, doc):
    """Атомарная запись: обрыв не оставляет обрезанного файла."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)


def scan_series():
    """Состояние — с диска, а не из манифеста.

    Урок A2: сводка, написанная прогоном, описывает прогон, а не
    хранилище. Здесь то же самое: если манифест потерян или побит
    обрывом, готовые ряды всё равно лежат на диске и должны быть
    учтены, иначе перезапуск скачает заново то, что уже есть.
    """
    out = {}
    if not os.path.isdir(SERIES):
        return out
    for fn in sorted(os.listdir(SERIES)):
        if not fn.endswith(".npz") or fn.endswith(".tmp.npz"):
            continue
        sym = fn[:-len(".npz")]
        try:
            with np.load(os.path.join(SERIES, fn)) as z:
                t, usd = z["t"], z["oi_usd"]
        except Exception:                                 # noqa: BLE001
            continue                     # битый файл — пусть соберётся заново
        if len(t) == 0:
            continue
        out[sym] = {"rows": int(len(t)), "first": int(t[0]),
                    "last": int(t[-1]),
                    "median_oi_usd": float(np.median(usd)),
                    "recovered": True}
    return out


def is_done(info, sym, days, start, end):
    """Собран ли символ **за нужное окно**, а не просто «файл есть».

    Дефект, найденный по манифесту первого полного прогона: пилот из
    инструкции собирал три символа за пять дней, а полный прогон их
    пропускал, потому что признаком готовности было существование
    файла. Три инструмента из 618 несли пять суток вместо 912, и
    заметить это в сводке было нечем — она докладывала «618 из 621».

    Поэтому окно запоминается в манифесте и сверяется. У записей,
    восстановленных с диска (окна там нет по определению), готовность
    проверяется **по данным**: ряд обязан накрывать план от первого
    дня до последнего, иначе символ собирается заново.
    """
    if not info:
        return False
    npz = os.path.join(SERIES, f"{sym}.npz")
    # Ноль строк при совпавшем плане — знание, а не пробел: файлов у
    # архива нет вовсе, и перезапрашивать их каждый прогон незачем.
    if info.get("start") == start and info.get("end") == end:
        return info.get("rows", 0) == 0 or os.path.exists(npz)
    # Записи прежнего формата окна не несут, но несут число дней плана
    # на момент сбора. Совпало с нынешним планом — окно то же; у трёх
    # символов, собранных пилотом, оно не совпадёт.
    if info.get("days") is not None and not info.get("recovered"):
        if info["days"] != len(days):
            return False
        return info.get("rows", 0) == 0 or os.path.exists(npz)
    if not info.get("recovered") or not os.path.exists(npz):
        return False
    first, last = info.get("first"), info.get("last")
    if not first or not last or not days:
        return False
    plan_first = int(np.datetime64(days[0] + "T00:00:00", "s").astype("int64"))
    plan_last = int(np.datetime64(days[-1] + "T23:59:59", "s").astype("int64"))
    tol = 3 * 86400
    return first <= plan_first + tol and last >= plan_last - tol


def load_manifest(path):
    """Манифест плюс то, что найдено на диске. Диск главнее."""
    man = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                man = json.load(f).get("symbols", {})
        except (json.JSONDecodeError, OSError) as e:
            print(f"манифест не читается ({str(e)[:60]}) — "
                  f"состояние восстанавливается с диска", file=sys.stderr)
    disk = scan_series()
    for sym, info in disk.items():
        if sym not in man:
            man[sym] = info
    return man


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--limit", type=int, default=0,
                    help="взять первые N символов — пилот")
    ap.add_argument("--symbols", default="",
                    help="список через запятую вместо универсума")
    a = ap.parse_args()
    os.makedirs(SERIES, exist_ok=True)

    uni = universe_symbols()
    if a.symbols:
        want = [s.strip() for s in a.symbols.split(",") if s.strip() in uni]
    else:
        want = sorted(uni)
    plan = []
    for sym in want:
        d = days_of(uni[sym]["intervals"], a.start, a.end)
        if d:
            plan.append((sym, d))
    if a.limit:
        plan = plan[:a.limit]

    total_days = sum(len(d) for _, d in plan)
    print(f"символов {len(plan)}, символо-дней {total_days}, "
          f"оценка трафика {total_days * 11 / 1e6:.1f} ГБ",
          file=sys.stderr, flush=True)

    manifest_path = os.path.join(OUT, "oi_binance_manifest.json")
    manifest = load_manifest(manifest_path)
    ready = sum(1 for sym, d in plan
                if is_done(manifest.get(sym), sym, d, a.start, a.end))
    if ready:
        print(f"уже собрано {ready} символов, остаётся {len(plan) - ready}",
              file=sys.stderr, flush=True)

    done = 0
    t_start = time.time()
    for sym, days in plan:
        dst = os.path.join(SERIES, f"{sym}.npz")
        if is_done(manifest.get(sym), sym, days, a.start, a.end):
            done += 1
            continue
        t0 = time.time()
        arr, info = collect_symbol(sym, days, a.workers)
        info["start"], info["end"] = a.start, a.end
        info["asset"] = uni[sym]["asset"]
        info["delisted"] = uni[sym]["delisted"]
        info["seconds"] = round(time.time() - t0, 1)
        if arr is not None:
            # Запись через временный файл: прерывание прогона не должно
            # оставить наполовину записанный ряд, который на следующем
            # запуске будет принят за готовый.
            np.savez_compressed(dst + ".tmp.npz", t=arr[0], oi=arr[1],
                                oi_usd=arr[2])
            os.replace(dst + ".tmp.npz", dst)
        manifest[sym] = info
        done += 1
        write_json(manifest_path, {"config": {"start": a.start, "end": a.end},
                                   "symbols": manifest})
        el = time.time() - t_start
        print(f"[{done}/{len(plan)}] {sym}: строк {info['rows']}, "
              f"дней {info['days']}, пропущено {info['days_missing']}, "
              f"{info['seconds']} с (всего {el / 60:.1f} мин)",
              file=sys.stderr, flush=True)

    # Манифест пишется и в конце: если он был потерян и состояние
    # восстановлено с диска, восстановление должно закрепиться, а не
    # повторяться на каждом запуске.
    write_json(manifest_path, {"config": {"start": a.start, "end": a.end},
                               "symbols": manifest})

    ok = [v for v in manifest.values() if v.get("rows")]
    counted = [v for v in manifest.values() if not v.get("recovered")]
    rec = len(manifest) - len(counted)
    miss = sum(v.get("days_missing", 0) for v in counted)
    days = sum(v.get("days", 0) for v in counted)
    print("\nИТОГ СБОРА")
    print(f"  символов с рядом      {len(ok)} из {len(manifest)}")
    print(f"  строк                 {sum(v['rows'] for v in ok):,}")
    print(f"  символо-дней          {days:,}")
    print(f"  дней без файла        {miss:,} ({miss / max(days, 1):.2%})")
    print(f"  дублей по метке       {sum(v.get('dups', 0) for v in ok):,}")
    if rec:
        # Честно: у восстановленных с диска нет статистики загрузки, и
        # три числа выше их не считают. Молча приплюсовать было бы той
        # же ошибкой, что дельта прогона вместо состояния в A2.
        print(f"  восстановлено с диска {rec} — доля пропусков и дублей "
              f"по ним неизвестна")
    print(f"\nманифест {manifest_path}")
    print(f"ряды     {SERIES}")


if __name__ == "__main__":
    main()
