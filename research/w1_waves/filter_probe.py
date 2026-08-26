#!/usr/bin/env python3
"""W3 — волновое состояние как фильтр сделок наших моделей.

Вопрос владельца: «что если использовать это как вспомогательный фильтр
для наших моделей и фильтровать сделки». Фильтр полезен тогда и только
тогда, когда НАВЫК модели различается по состоянию волны: если модель
угадывает одинаково во всех состояниях, фильтр не отсеивает плохие
сделки — он отсеивает сделки, то есть торговать реже, а не лучше (ровно
эта формулировка стояла в зонде крайности до его прогона).

Проверяется дёшево и без единого нового обучения: по уже сохранённым
walk-forward-векторам M2 (вне выборки, 1330 сечений, 4 года). Машина
суда — зонд режимов (`probe_regimes`): деление сечения на трети по
признаку против СЛУЧАЙНЫХ третей того же размера, тем же кодом, в тот
же день. Вторая копия этой машины не пишется — она импортируется.

Честный приор, и он идёт в отчёт: шесть режимов рынка уже дали ровно
ноль (46–49 % дней шире случайного при нуле 50 %), а нормировка «на
путь» оказалась вариантом того же сигнала. Волновое состояние — седьмая
попытка. Её единственное настоящее основание: чередование глубин 2/4
выжило против суррогата (W2), а волновых величин в признаках модели
нет.

Пять состояний, объявленных ДО прогона (все причинные — только
ПОДТВЕРЖДЁННЫЕ развороты, вершина без подтверждения не существует):

- `wv_leg_age` — зрелость текущей ноги: часов от подтверждения
  последнего разворота, в долях медианной длительности ноги символа
  (медиана — по завершённым ногам ДО этого момента);
- `wv_depth` — глубина текущего хода в долях предыдущей завершённой
  ноги: «где мы в откате»;
- `wv_dir_move` — тот же ход со знаком направления текущей ноги, в
  единицах порога зигзага;
- `wv_prev_ratio` — откат предыдущей завершённой ноги: чередование W2
  предсказывает, что после глубокой коррекции идёт мелкая;
- `wv_imp_rules` — сколько правил импульса (0–3) прошло последнее окно
  из пяти завершённых ног: «мы после импульса».

Порог зигзага один и объявлен: 2σ — медианная нога ~6 суток (W2), тот
же масштаб, что горизонты модели 1–5 дней. σ символа — по его ПЕРВЫМ
60 суткам (порог из будущего был бы заглядыванием, `own_theta` W2).

Состояние берётся на ОТКРЫТИИ последнего часа дня решения — то есть
слегка СТАРШЕ признаков модели (те видят закрытие дня): консервативно,
заглядывание исключено по построению.

    .venv/bin/python research/w1_waves/filter_probe.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "z1_screen"))
sys.path.insert(0, os.path.join(RESEARCH, "probe_regimes"))

import importlib.util                                     # noqa: E402

import grammar as G                                       # noqa: E402
import grammar_probe as GP                                # noqa: E402
import probe as P                                         # noqa: E402
import screen as Z                                        # noqa: E402
import waves as W                                         # noqa: E402

# Машина суда — зонд режимов. Его модуль тоже зовётся probe.py, а наш
# probe.py стоит на пути первым: обычный import отдал бы НАШ модуль, и
# машина суда молча оказалась бы не той — тот же класс подмены, что
# nulls.py в F3. Поэтому по файлу, явно.
_spec = importlib.util.spec_from_file_location(
    "regimes_probe", os.path.join(RESEARCH, "probe_regimes", "probe.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
assert hasattr(R, "RANDOM_DRAWS"), "загружен не зонд режимов"

# --- пространство, объявленное до прогона -------------------------------

THETA_MULT = 2.0                  # медианная нога ~6 суток — масштаб 1–5 д
START, END = "2022-07-01", "2026-06-01"
VECTORS = ("vectors_h5_day.npz", "vectors_h1_day.npz")
WAVE_REGIMES = [
    ("wv_leg_age", "зрелость текущей ноги (от подтверждения, в медианах)"),
    ("wv_depth", "глубина текущего хода в долях предыдущей ноги"),
    ("wv_dir_move", "ход со знаком направления ноги, в порогах"),
    ("wv_prev_ratio", "откат предыдущей ноги (чередование W2)"),
    ("wv_imp_rules", "правил импульса у последних пяти ног (0–3)"),
]
SEED = 20260827


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def day_hour(day, grid0_ts):
    """Час решения дня: ОТКРЫТИЕ его последнего часа, индексом сетки.

    Решение конца дня видит закрытие дня; открытие последнего часа —
    строго раньше. Состояние волны намеренно чуть старше признаков
    модели: консервативно, а заглядывание исключено по построению.
    """
    ts = int(datetime.strptime(str(day), "%Y-%m-%d")
             .replace(tzinfo=timezone.utc).timestamp())
    return (ts - grid0_ts) // 3600 + 23


def wave_states(x, theta, queries):
    """Пять волновых состояний в заданные часы. Пропуск — NaN.

    Всё причинно: разворот существует с момента ПОДТВЕРЖДЕНИЯ
    (`i_confirm`), не с момента вершины — вершина видна задним числом,
    и состояние по ней было бы заглядыванием (плата, измеренная W1:
    подтверждение приходит, когда 35–39 % следующей ноги уже прошло).
    Цена «сейчас» — последняя конечная не старше `MAX_GAP` часов:
    протухшая цена — не состояние, а дыра записи.
    """
    out = {k: np.full(len(queries), np.nan) for k, _ in WAVE_REGIMES}
    piv = W.zigzag(x, theta)
    lg = W.legs(x, piv, max_gap=W.MAX_GAP)
    if not lg:
        return out
    conf = np.array([v["i_confirm"] for v in lg], dtype=np.int64)
    durs = np.array([v["bars"] for v in lg], dtype=np.float64)
    fin = np.isfinite(x)
    last_fin = np.maximum.accumulate(
        np.where(fin, np.arange(len(x)), -1))
    for qi, t in enumerate(queries):
        if t < 0 or t >= len(x):
            continue
        k = int(np.searchsorted(conf, t, side="right")) - 1
        if k < 0:
            continue
        j = int(last_fin[t])
        if j < 0 or t - j > W.MAX_GAP:
            continue                      # цена протухла — состояния нет
        leg = lg[k]
        med = float(np.median(durs[:k + 1]))
        if med > 0:
            out["wv_leg_age"][qi] = (t - leg["i_confirm"]) / med
        raw = float(x[j]) - leg["px_to"]
        if leg["size"] > 0:
            out["wv_depth"][qi] = abs(raw) / leg["size"]
        out["wv_dir_move"][qi] = (-leg["dir"]) * raw / theta
        out["wv_prev_ratio"][qi] = leg["ratio"]
        if k >= 4:
            w5 = lg[k - 4:k + 1]
            if G.contiguous(w5):
                st = G.impulse_stats(w5)
                out["wv_imp_rules"][qi] = float(
                    st["rule2"] + st["rule3"] + st["rule4"])
    return out


def build_wave_columns(cols, log=log_):
    """Волновые колонки, выровненные со строками матрицы M1."""
    syms = cols["symbol"]
    days = cols["day"]
    uniq = sorted(set(str(s) for s in syms))
    times = P.grid(START, END)
    grid0 = int(times[0])
    log(f"волновое состояние: символов {len(uniq)}, строк {len(syms):,}")
    L = P.load_prices(uniq, times, "1m", log=log)
    row_of = {s: i for i, s in enumerate(uniq)}
    wave = {k: np.full(len(syms), np.nan) for k, _ in WAVE_REGIMES}
    sym_arr = np.array([str(v) for v in syms])
    hours = np.array([day_hour(d, grid0) for d in days], dtype=np.int64)
    t0 = time.time()
    done = 0
    for s in uniq:
        rows = np.flatnonzero(sym_arr == s)
        x_full = L[row_of[s]].astype(np.float64)
        theta, start = GP.own_theta(x_full)
        done += 1
        if done % 50 == 0:
            log(f"  {done}/{len(uniq)} символов, {time.time() - t0:.0f} с")
        if theta is None:
            continue
        st = wave_states(x_full[start:], theta,
                         [int(h) - start for h in hours[rows]])
        for k, _ in WAVE_REGIMES:
            wave[k][rows] = st[k]
    for k, _ in WAVE_REGIMES:
        n = int(np.isfinite(wave[k]).sum())
        log(f"  {k}: заполнено {n:,} из {len(syms):,} "
            f"({n / len(syms):.0%})")
    return wave


def judge(cols, pred, key, log=log_):
    """Суд машиной зонда режимов над волновыми состояниями.

    Меняется только СПИСОК состояний; run(), случайные трети и свод —
    чужие и не копируются: вторая копия машины суда однажды разошлась
    бы с первой, тем в проекте кончались nulls.py и загрузчик funding.
    """
    old = R.REGIMES
    try:
        R.REGIMES = WAVE_REGIMES
        out, n_days = R.run(cols, pred, key, log=log)
        rows = R.summarise(out)
    finally:
        R.REGIMES = old
    return rows, n_days


def reading(rows):
    """Фраза вывода — из чисел, а не рядом с ними."""
    if not rows:
        return ("ни одно состояние не измерено — фильтру не из чего "
                "строиться.")
    top = max(rows, key=lambda r: r["wider"])
    if top["wider"] <= 0.55:
        return ("навык модели по состоянию волны не различается: доля "
                "дней, где разброс шире случайного, "
                f"{top['wider']:.2f} у лучшего состояния при нуле 0.50. "
                "Фильтр по волне отсеивал бы сделки, а не плохие "
                "сделки — торговать реже, а не лучше.")
    return (f"состояние «{top['feat']}» разводит навык модели: разброс "
            f"шире случайного в {top['wider']:.0%} дней при нуле 50 %, "
            f"лучшая корзина держится {top['top_share']:.0%} дней при "
            "нуле 33 %. Это повод для спеки фильтра с порогами, а не "
            "вывод.")


def write_report(path, blocks, meta):
    L = ["# W3 — волновое состояние как фильтр сделок модели\n"]
    L.append(f"Прогон {meta['when']} · порог зигзага "
             f"{THETA_MULT:.0f}σ · пять состояний, объявленных до "
             "прогона · машина суда — зонд режимов (случайные трети "
             "того же размера, тем же кодом, в тот же день)\n")
    L.append("**Вопрос:** различается ли навык модели по состоянию "
             "волны. Если нет — фильтр отсеивает сделки, а не плохие "
             "сделки. **Приор честно отрицательный:** шесть режимов "
             "рынка уже дали ноль, а нормировка «на путь» оказалась "
             "вариантом того же сигнала. Основание всё же мерить: "
             "чередование глубин выжило против суррогата (W2), и "
             "волновых величин в признаках модели нет.\n")
    for name, rows, n_days in blocks:
        L.append(f"\n## Вектор {name} — сечений {n_days}\n")
        L.append("| состояние | IC всего | IC по третям | разброс | "
                 "случайный | шире случайного | лучшая треть держится |")
        L.append("|---|--:|---|--:|--:|--:|--:|")
        for r in rows:
            L.append(f"| {r['name']} | {r['ic_all']:+.4f} | "
                     + " / ".join(f"{v:+.3f}" for v in r["bins"])
                     + f" | {r['spread_med']:.3f} | "
                     f"{r['rand_spread_med']:.3f} | {r['wider']:.2f} | "
                     f"{r['top_share']:.2f} (треть {r['top_bin']}) |")
        L.append(f"\n**Читается так:** {reading(rows)}\n")
    L.append("\nНуль у «шире случайного» — 0.50, у «лучшая треть "
             "держится» — 0.33: деление на трети шумнее целого по "
             "построению, и без случайных третей любой разброс "
             "читался бы как находка.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="волновой фильтр сделок")
    ap.add_argument("--matrix", default=os.path.join(
        RESEARCH, "m1_features", "out", "features_1m.parquet"))
    ap.add_argument("--vectors-dir", default=os.path.join(
        RESEARCH, "m2_walkforward", "out"))
    ap.add_argument("--tag", default="1h")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)

    blocks, wave = [], None
    for vec in VECTORS:
        vpath = os.path.join(a.vectors_dir, vec)
        if not os.path.exists(vpath):
            log_(f"вектора {vec} нет — пропуск")
            continue
        cols, pred, key = R.load(a.matrix, vpath, log=log_)
        if wave is None:
            wave = build_wave_columns(cols)
        cols = dict(cols)
        cols.update(wave)
        rows, n_days = judge(cols, pred, key)
        blocks.append((vec, rows, n_days))
        for r in rows:
            log_(f"  {vec} · {r['feat']}: шире случайного {r['wider']:.2f},"
                 f" лучшая треть {r['top_share']:.2f}")
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC")}
    path = os.path.join(OUT, f"W3-wavefilter-{a.tag}.md")
    write_report(path, blocks, meta)
    with open(os.path.join(OUT, f"w3-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"blocks": [{"vectors": n, "rows": r, "sections": d}
                              for n, r, d in blocks],
                   "meta": meta}, f, ensure_ascii=False)
    log_(f"отчёт: {path}")
    if not a.no_publish:
        Z.publish("W3: волновое состояние как фильтр сделок")
    return 0


if __name__ == "__main__":
    sys.exit(main())
