#!/usr/bin/env python3
"""Зонд корреляции: навык модели у «скоррелированных» и «своей жизнью».

Идея владельца: «торговать только те активы, которые либо максимально
скоррелированы с рынком, либо наоборот те, которые живут своей жизнью».
Обе ветки — две крайние трети ОДНОГО состояния, поэтому состояние одно
и объявлено до прогона:

    `mkt_corr` — корреляция Пирсона дневных лог-доходностей актива с
    равновзвешенной волной рынка за скользящие 90 дней, окно кончается
    ДНЁМ РЕШЕНИЯ включительно (тот же набор знаний, что у признаков
    модели: ret_1 видит закрытие дня решения). Актив исключён из
    собственной волны — включение себя завышает связь (замер R1: актив
    без всякой связи с рынком получал β > 0.5). Меньше 60 конечных пар
    из 90 — меры НЕТ (NaN), а не ноль; день волны тоньше 30 чужих
    имён парой не считается.

Фильтр полезен тогда и только тогда, когда НАВЫК модели различается по
состоянию: одинаковый навык означает «торговать реже, а не лучше»
(формулировка W3). Машина суда — зонд режимов, не копируется:
случайные трети того же размера, тем же кодом, в тот же день.

Честный приор отрицательный, и он идёт в отчёт: это ДЕВЯТАЯ
конструкция «обстановки» (шесть режимов рынка, путь, волна — все ноль),
и среди шести режимов была `beta`. Корреляция — не бета: бета мешает
связь с размахом (β = corr × σᵢ/σ_рынка), разогнанная монета получает
высокую бету при средней связи. Вопрос владельца — ровно про связь.

Механическая оговорка, названная до прогона: у имени, почти идеально
скоррелированного с рынком, остаток после хеджа волной мал по
построению — модели там почти нечего предсказывать. Если верхняя треть
покажет слабый IC, это может быть свойством конструкции цели, а не
навыка; читать вместе с σ прогнозов по третям нельзя, поэтому в отчёте
рядом стоит IC нижней и верхней третей — обе ветки владельца читаются
из одной таблицы.

Данные — дневная сводка M1 (`daily_1m`: день без сделок не несёт
закрытия — замороженные ряды выпадают по построению), векторы M2
(walk-forward, вне выборки), матрица M1. Всё локально, прогон
минуты.

    .venv/bin/python research/probe_corr/corr_probe.py
"""

import argparse
import glob
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, os.path.join(RESEARCH, "probe_turn"))
import turn as PT                                         # noqa: E402

# Машина суда — зонд режимов, по файлу и с проверкой (урок F3/W3:
# одноимённый модуль на пути подменил бы машину молча).
_spec = importlib.util.spec_from_file_location(
    "regimes_probe", os.path.join(RESEARCH, "probe_regimes", "probe.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
assert hasattr(R, "RANDOM_DRAWS"), "загружен не зонд режимов"

# --- пространство, объявленное до прогона -------------------------------

CORR_W = 90                    # окно корреляции, дней
CORR_MIN = 60                  # меньше конечных пар — меры нет
MIN_WAVE = 30                  # чужих имён в дне волны; тоньше — не пара
CORR_REGIMES = [
    ("mkt_corr", "корреляция с волной рынка, 90 дней, без себя"),
]
VECTORS = ("vectors_h5_day.npz", "vectors_h1_day.npz")


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_daily(dir_):
    """Дневные закрытия из сводки M1: (дни, символы, матрица закрытий).

    Сводка несёт только дни СО сделками — на общей сетке дней прочие
    остаются NaN, и доходность через дыру не считается (правило R1:
    только соседние наблюдения; NaN заражает пару).
    """
    import pyarrow.parquet as pq
    days_set, rows = set(), []
    for f in sorted(glob.glob(os.path.join(dir_, "*.parquet"))):
        t = pq.read_table(f, columns=["symbol", "day", "close"])
        sym = t.column("symbol").to_pylist()
        day = [str(d) for d in t.column("day").to_pylist()]
        cl = t.column("close").to_pylist()
        rows.append((sym, day, cl))
        days_set.update(day)
    days = np.array(sorted(days_set))
    d_ix = {d: i for i, d in enumerate(days)}
    syms_set = sorted({s for sym, _, _ in rows for s in sym})
    s_ix = {s: i for i, s in enumerate(syms_set)}
    close = np.full((len(syms_set), len(days)), np.nan)
    for sym, day, cl in rows:
        for s, d, c in zip(sym, day, cl):
            if c is not None:
                close[s_ix[s], d_ix[d]] = float(c)
    return days, np.array(syms_set), close


def log_returns(close):
    """Дневные лог-доходности: только между соседними днями сетки."""
    r = np.full_like(close, np.nan)
    a, b = close[:, :-1], close[:, 1:]
    ok = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
    r[:, 1:][ok] = np.log(b[ok] / a[ok])
    return r


def corr_series(r_i, wave_sum, wave_cnt, q_ix):
    """Корреляция актива с волной БЕЗ СЕБЯ в заданные дни.

    Волна дня для актива i: (Σ доходностей − rᵢ) / (счёт − 1) — только
    в дни, где rᵢ конечна (иначе пары нет) и чужих имён не меньше
    `MIN_WAVE`. Окно [d−89, d] включает день решения — тот же набор
    знаний, что у признаков.
    """
    out = np.full(len(q_ix), np.nan)
    fin_i = np.isfinite(r_i)
    w = np.full_like(r_i, np.nan)
    ok = fin_i & (wave_cnt - 1 >= MIN_WAVE)
    w[ok] = (wave_sum[ok] - r_i[ok]) / (wave_cnt[ok] - 1)
    for k, j in enumerate(q_ix):
        if j < 0 or j >= len(r_i):
            continue
        lo = max(0, j - CORR_W + 1)
        x, y = r_i[lo:j + 1], w[lo:j + 1]
        m = np.isfinite(x) & np.isfinite(y)
        if int(m.sum()) < CORR_MIN:
            continue
        xs, ys = x[m], y[m]
        xs = xs - xs.mean()
        ys = ys - ys.mean()
        den = np.sqrt((xs * xs).sum() * (ys * ys).sum())
        if den > 0:
            out[k] = float((xs * ys).sum() / den)
    return out


def build_corr_column(cols, daily_dir, log=log_, uni=None):
    """Колонка `mkt_corr`, выровненная со строками матрицы M1.

    Матрица держит АКТИВЫ («ADA»), дневная сводка — СИМВОЛЫ
    («ADAUSDT»); карта — универсум A1 (дорога W3, где первый живой
    прогон упал ровно на этом). Актив без символа остаётся без
    состояния и считается числом.
    """
    if uni is None:
        sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
        import data as D
        uni = D.universe()
    days, syms, close = load_daily(daily_dir)
    log(f"дневная сводка: символов {len(syms)}, дней {len(days)}")
    r = log_returns(close)
    wave_sum = np.nansum(r, axis=0)
    wave_cnt = np.isfinite(r).sum(axis=0)
    d_ix = {d: i for i, d in enumerate(days)}
    s_ix = {s: i for i, s in enumerate(syms)}
    sym_of = {v["asset"]: s for s, v in uni.items()}
    asset_arr = np.array([str(v) for v in cols["asset"]])
    day_arr = np.array([str(v) for v in cols["day"]])
    out = np.full(len(asset_arr), np.nan)
    missing = sorted({a for a in np.unique(asset_arr)
                      if sym_of.get(a) not in s_ix})
    if missing:
        log(f"  активов без ряда закрытий: {len(missing)} "
            f"(напр. {missing[:4]}) — их строки без состояния")
    t0 = time.time()
    assets = [a for a in np.unique(asset_arr) if a not in missing]
    for done, a in enumerate(assets, 1):
        rows = np.flatnonzero(asset_arr == a)
        q_ix = np.array([d_ix.get(d, -1) for d in day_arr[rows]])
        out[rows] = corr_series(r[s_ix[sym_of[a]]], wave_sum,
                                wave_cnt, q_ix)
        if done % 100 == 0:
            log(f"  {done}/{len(assets)} активов, "
                f"{time.time() - t0:.0f} с")
    n = int(np.isfinite(out).sum())
    log(f"  mkt_corr: заполнено {n:,} из {len(out):,} "
        f"({n / len(out):.0%})")
    return out


def judge(cols, pred, key, log=log_):
    """Суд машиной зонда режимов. Признак непрерывный — нуль прежний
    (равные случайные трети; matched нужен только дискретным, W3)."""
    old = R.REGIMES
    try:
        R.REGIMES = CORR_REGIMES
        out, n_days = R.run(cols, pred, key, log=log)
        rows = R.summarise(out)
    finally:
        R.REGIMES = old
    return rows, n_days


def reading(rows):
    """Фраза вывода — из чисел (правило: вердикт выводится, а не
    стоит рядом)."""
    if not rows:
        return "состояние не измерено — фильтру не из чего строиться."
    r = rows[0]
    if r["wider"] <= 0.55:
        return ("навык модели по связи с рынком не различается: доля "
                f"дней с разбросом шире случайного {r['wider']:.2f} "
                "при нуле 0.50. Торговать только скоррелированные или "
                "только «своей жизнью» значит торговать реже, а не "
                "лучше — девятая обстановка с тем же итогом.")
    side = ("«своей жизнью» (нижняя треть)" if r["top_bin"] == 0
            else "«скоррелированные» (верхняя треть)"
            if r["top_bin"] == 2 else "середина — ни одна из веток")
    return (f"связь с рынком разводит навык: разброс шире случайного "
            f"в {r['wider']:.0%} дней при нуле 50 %, лучшая треть — "
            f"{side}, держится {r['top_share']:.0%} дней при нуле "
            "33 %. Это повод для спеки фильтра с порогами, а не вывод.")


def write_report(path, blocks, meta):
    L = ["# Зонд корреляции — «скоррелированные» против «своей жизнью»\n"]
    L.append(f"Прогон {meta['when']} · окно корреляции {CORR_W} дней "
             f"(минимум {CORR_MIN} пар), волна без себя, день волны "
             f"от {MIN_WAVE} чужих имён · машина суда — зонд режимов\n")
    L.append("**Вопрос владельца:** торговать только максимально "
             "скоррелированные с рынком имена либо только живущие "
             "своей жизнью. Обе ветки — крайние трети одного "
             "состояния: треть 0 — «своей жизнью», треть 2 — "
             "«скоррелированные».\n")
    L.append("**Приор честно отрицательный:** это девятая конструкция "
             "«обстановки», восемь прошлых дали ноль, и среди них была "
             "бета. Корреляция — не бета (бета мешает связь с "
             "размахом), поэтому мерить всё же стоило. Механическая "
             "оговорка: у идеально скоррелированного имени остаток "
             "после хеджа волной мал по построению — слабый IC верхней "
             "трети может быть свойством цели, а не навыка.\n")
    for name, rows, n_days in blocks:
        L.append(f"\n## Вектор {name} — сечений {n_days}\n")
        L.append("| состояние | IC всего | IC по третям "
                 "(своей жизнью / середина / скоррелированные) | "
                 "разброс | случайный | шире случайного | "
                 "лучшая треть держится |")
        L.append("|---|--:|---|--:|--:|--:|--:|")
        for r in rows:
            L.append(f"| {r['name']} | {r['ic_all']:+.4f} | "
                     + " / ".join(f"{v:+.3f}" for v in r["bins"])
                     + f" | {r['spread_med']:.3f} | "
                     f"{r['rand_spread_med']:.3f} | {r['wider']:.2f} | "
                     f"{r['top_share']:.2f} (треть {r['top_bin']}) |")
        L.append(f"\n**Читается так:** {reading(rows)}\n")
    L.append("\nНуль у «шире случайного» — 0.50, у «лучшая треть "
             "держится» — 0.33. Оценка по векторам M2 (walk-forward, "
             "вне выборки, ~3.6 года) — про дневную модель гипотезы 6; "
             "живая часовая книга короче месяца, и судить её по "
             "обстановке пока не на чем.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="фильтр по связи с рынком")
    ap.add_argument("--matrix", default=os.path.join(
        RESEARCH, "m1_features", "out", "features_1m.parquet"))
    ap.add_argument("--vectors-dir", default=os.path.join(
        RESEARCH, "m2_walkforward", "out"))
    ap.add_argument("--daily", default=os.path.join(
        RESEARCH, "m1_features", "out", "daily_1m"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)

    blocks, corr = [], None
    for vec in VECTORS:
        vpath = os.path.join(a.vectors_dir, vec)
        if not os.path.exists(vpath):
            log_(f"вектора {vec} нет — пропуск")
            continue
        cols, pred, key = R.load(a.matrix, vpath, log=log_)
        if corr is None:
            corr = build_corr_column(cols, a.daily)
        cols = dict(cols)
        cols["mkt_corr"] = corr
        rows, n_days = judge(cols, pred, key)
        blocks.append((vec, rows, n_days))
        for r in rows:
            log_(f"  {vec}: шире случайного {r['wider']:.2f}, "
                 f"лучшая треть {r['top_bin']} ({r['top_share']:.2f}), "
                 "IC по третям "
                 + " / ".join(f"{v:+.3f}" for v in r["bins"]))
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC")}
    path = write_report(
        os.path.join(OUT, f"CORR-filter-{a.tag}.md"), blocks, meta)
    with open(os.path.join(OUT, f"corr-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"blocks": [
            {"vector": n, "rows": rows, "days": d}
            for n, rows, d in blocks], "meta": meta},
            f, ensure_ascii=False, indent=1)
    log_(f"отчёт: {path}")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
