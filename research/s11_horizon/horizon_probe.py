"""Зонд горизонта сигнала ситуационных книг: 4 ч против 5/6/8/12/24.

Вопрос владельца (2026-08-23) двойной: какая была бы статистика книги
на 24-часовом сигнале вместо 4-часового, и на каком горизонте сигнала
вообще лучше торговать. Это ЗОНД, а не гипотеза: ни порогов, ни
вердикта; сетка горизонтов объявлена здесь и не растёт после
просмотра поверхности. Выбрать лучшую ячейку и торговать её — ошибка
R5; решение по поверхности — за владельцем.

Устройство: одна честная разбивка по времени (walk-forward в один
шаг). Модели каждого горизонта обучаются ТОЛЬКО на первых SPLIT_FRAC
часах записи, с отступом на сам горизонт (правило M2 `s + h < T`:
цель часа `j` смотрит вперёд на `h`, и час обучения обязан целиком
лежать до разреза). Реплей книги идёт по хвосту, которого обучение не
видело. Исходы — по минутным барам собственной записи сборщика, тем
же ядром, что турнир политик (`outcome`/`simulate` — вторая копия
однажды разошлась бы).

Оговорки, объявленные ДО прогона и не снимаемые результатом:
- обучение одно на разбивку, без ежемесячного переобучения — M2
  замерил, что частота переобучения почти ничего не меняет
  (+0.000…+0.004 IC), но это допущение, а не тождество;
- вход в реплее — закрытие часа; скидка, взведение, полоса, шум и
  потолок съеденного (правила v4–v12 сканера) не воспроизводятся —
  одинаково у ВСЕХ горизонтов, как в турнире политик (спека 10 §4);
- стоп — линия СРЕДНЕГО `mae` у всех горизонтов, включая 4 ч (живая
  книга стопит по выученному квантилю, но квантильные цели есть
  только у 4 ч) — сравнимость дороже точности, различие названо;
- запись короткая, режим рынка один; хвост записи короче предела
  возраста не торгуется (сделка без полного окна была бы срезана
  краем записи и посчитана «сроком»).

Запуск на VPS (данные — сводки и минутные бары — живут там):
  cd ~/algoth_v2 && nice -n 19 .venv/bin/python \
      research/s11_horizon/horizon_probe.py
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for d in ("s8_loop", "s10_policy", "s9_sweep"):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), d))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))

# Сетка объявлена до прогона. 4 — контроль (живой сигнал книги),
# 24 — прямой вопрос владельца, остальные — «и т.д.» с шагом,
# различимым на короткой записи.
PROBE_HORIZONS = (4, 5, 6, 8, 12, 24)
SPLIT_FRAC = 0.6                  # доля часов в обучении
EDGE_BP = 33.0                    # гейт входа живой книги (3× круга)
GATES = (("sit", 2.0, None),      # (имя, rr_min, rr_max)
         ("lo", 0.0, 1.5))
AGE_H = 24                        # предел возраста живой книги
SLOTS_NOTE = "слоты и одна позиция на имя — моделью турнира"


def edge_pass(fwd):
    """Нога слабее гейта входа не торгуется НИ в одной ячейке (край
    один на всю сетку), поэтому и не хранится. Первый прогон держал
    все 1.26 млн ног двенадцати сочетаний (~1 ГБ словарей) и был убит
    ядром по памяти на 2.6 ГБ RSS рядом с часовым обучением цикла.
    Тождество предфильтра с гейтом `simulate` закреплено тестом.
    """
    return fwd is not None and abs(fwd) >= EDGE_BP


def train_cols(n_hours, split_j, h):
    """Колонки обучения горизонта `h` при разрезе `split_j`.

    Цель часа `j` смотрит вперёд на `h` часов; час годен обучению,
    только если всё окно цели лежит ДО разреза: `j + h < split_j`
    (правило M2 `s + h < T` — ошибка ровно в один час поймана тестом).
    """
    return [j for j in range(n_hours) if j + h < split_j]


def gate_pool(legs, rr_max):
    """Кандидаты книги: потолок отношения — правило книги lo.

    Отсутствие потолка — все ноги; нога без измеримого отношения не
    проходит НИ ОДИН порог (неизмеримое не есть удовлетворяющее —
    правило фильтра RR со страницы сделок).
    """
    if rr_max is None:
        return legs
    return [g for g in legs
            if g["rr"] is not None and g["rr"] <= rr_max]


def hour_epoch(hour_key):
    return int(datetime.strptime(hour_key, "%Y-%m-%d-%H")
               .replace(tzinfo=timezone.utc).timestamp())


def cell_stats(trades):
    import numpy as np
    import tournament as TN
    if not trades:
        return {"n": 0}
    nets = [t["net"] for t in trades]
    # daily() отдаёт «день → [сумма, счётчик]», curve_dd ждёт «день →
    # сумма» и возвращает (итог, просадка) — на этой композиции первый
    # прогон упал на ПОСЛЕДНЕМ шаге, после часа счёта; дорога
    # исполняется тестом.
    run, dd = TN.curve_dd({d: rec[0]
                           for d, rec in TN.daily(trades).items()})
    return {"n": len(trades),
            "win": round(sum(1 for v in nets if v > 0) / len(nets), 3),
            "mean_bp": round(float(np.mean(nets)), 1),
            "median_bp": round(float(np.median(nets)), 1),
            "total_bp": round(float(np.sum(nets)), 1),
            "worst_bp": round(float(min(nets)), 1),
            "curve_dd_bp": round(dd, 1),
            "by_why": {w: sum(1 for t in trades if t["why"] == w)
                       for w in {t["why"] for t in trades}}}


def fit_predict(h, arm, fit_fn, x, targets, elig, el_tr):
    """Обучение трёх целей горизонта и предсказание на всей сетке.

    Вынесено из main() ради ИСПОЛНЯЕМОГО теста: дефект «печать читает
    `ys` после `del`» жил только на дороге исполнения — py_compile
    молчал, а первый живой прогон падал UnboundLocalError на первом же
    обучении. Смоук на синтетике исполняет ровно эти строки.
    None — ячейка горизонта не измерена (мало строк).
    """
    import train as T
    preds = {}
    for kind in ("fwd", "mae", "mfe"):
        key = f"{kind}_{h}h"
        xs, ys, _ = T.flatten(x, targets[key], el_tr)
        n_rows = len(ys)
        if n_rows < T.MIN_TARGET_ROWS:
            print(f"{arm}/{key}: строк {n_rows} — ячейка не измерена",
                  flush=True)
            return None
        tt = time.time()
        model = fit_fn(xs, ys, seed=T.SEED0 + 17 * h)
        del xs, ys          # пик памяти: рядом учится цикл
        preds[kind] = T.predict_matrix(model, x, elig)
        print(f"{arm}/{key}: строк {n_rows}, обучение "
              f"{time.time() - tt:.0f} с", flush=True)
    return preds


def main():
    import numpy as np
    import train as T
    import bookfeat as FB
    import tournament as TN
    import sweep as SW

    ap = argparse.ArgumentParser()
    ap.add_argument("--summary-dir", default=None,
                    help="каталог почасовых сводок (умолчание цикла)")
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(HERE), "b1_book", "out"),
        help="запись сборщика (минутные бары исходов)")
    ap.add_argument("--split", type=float, default=SPLIT_FRAC)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--tag", default="1m")
    args = ap.parse_args()

    t0 = time.time()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)   # урок турнира: до счёта
    try:
        with open("/proc/meminfo") as f:
            avail = next(int(ln.split()[1]) // 1024 for ln in f
                         if ln.startswith("MemAvailable:"))
        print(f"память доступна: {avail} МБ", flush=True)
    except (OSError, StopIteration):
        pass

    import summary as SM
    sum_dir = args.summary_dir or SM.OUT
    print(f"сводки: {sum_dir}", flush=True)
    mats, syms, grid = T.load_matrices(sum_dir)
    if mats is None:
        print("сводок нет — считать не на чем")
        return 1
    x, names, targets, elig = T.assemble(mats, horizons=PROBE_HORIZONS)
    n = len(grid)
    split_j = int(n * args.split)
    print(f"матрица: {len(syms)} символов × {n} часов, разрез на "
          f"{grid[split_j]} (обучение {split_j} ч, хвост {n - split_j})",
          flush=True)

    # Обучение и предсказание по каждому горизонту. Порядок просмотра
    # кандидатов в реплее — по |прогнозу| (упрощение зонда, одинаково
    # у всех горизонтов; живая книга упорядочивает per σ).
    cells = {}
    ics = {}
    legs_by = {}
    for h in PROBE_HORIZONS:
        cols_tr = train_cols(n, split_j, h)
        el_tr = elig.copy()
        keep = np.zeros(n, dtype=bool)
        keep[cols_tr] = True
        el_tr[:, ~keep] = False
        for arm, fit_fn in T.ARMS:
            preds = fit_predict(h, arm, fit_fn, x, targets, elig,
                                el_tr)
            if preds is None:
                continue
            cols_te = list(range(split_j, n))
            ic = T.section_ic(preds["fwd"], targets[f"fwd_{h}h"],
                              elig, cols_te)
            ics[(h, arm)] = (round(float(np.median(ic)), 4)
                            if ic else None, len(ic))
            # Ноги: хвост записи короче предела возраста не торгуется.
            legs = []
            for j in range(split_j, n - AGE_H):
                rows_m = T.tradable_rows(
                    np.flatnonzero(elig[:, j]), syms)
                at = hour_epoch(grid[j]) + 3600
                for i in rows_m:
                    px = float(mats["mid_close"][i, j])
                    if not np.isfinite(px) or px <= 0:
                        continue
                    row = {"sym": syms[i], "px": px}
                    for kind in ("fwd", "mae", "mfe"):
                        v = preds[kind][i, j]
                        row[kind] = (round(float(v), 2)
                                     if np.isfinite(v) else None)
                    lg = TN._leg(row, arm, grid[j], at)
                    if lg is not None and edge_pass(lg["fwd"]):
                        legs.append(lg)
            legs.sort(key=lambda g: (g["at"], -abs(g["fwd"]),
                                     g["sym"]))
            for i, lg in enumerate(legs):
                lg["id"] = i
            legs_by[(h, arm)] = legs
            print(f"{arm}/{h}h: ног после гейта знаков {len(legs)}",
                  flush=True)

    # Матрицы признаков и целей реплею не нужны — освободить ДО баров:
    # первый прогон умер по памяти, урок D1 «пик считается составом».
    del x, targets, elig, mats

    # Исходы: бары по ОДНОМУ имени за раз — пик памяти не растёт с
    # универсумом (все ~500 имён разом стоили бы сотни МБ).
    by_sym = {}
    for combo, legs in legs_by.items():
        for lg in legs:
            by_sym.setdefault(lg["sym"], []).append((combo, lg))
    outs_by = {combo: {} for combo in legs_by}
    for k, (sym, items) in enumerate(sorted(by_sym.items())):
        a = min(lg["at"] for _, lg in items)
        b = max(lg["at"] for _, lg in items)
        sym_bars = SW.read_bars(args.root, sym, a - 60,
                                b + AGE_H * 3600 + 60)
        for combo, lg in items:
            outs_by[combo][(lg["id"], "m", True, AGE_H)] = TN.outcome(
                sym_bars, lg["at"], lg["side"], lg["adv_m"],
                lg["fav"], AGE_H)
        if k % 25 == 0:
            print(f"бары: {k}/{len(by_sym)} имён", flush=True)
        del sym_bars

    for (h, arm), legs in legs_by.items():
        outs = outs_by[(h, arm)]
        for gate, rr_min, rr_max in GATES:
            pool = gate_pool(legs, rr_max)
            var = {"edge": EDGE_BP, "rr": rr_min, "stop": "m",
                   "take": True, "age": AGE_H}
            trades = TN.simulate(pool, outs, var)
            cells[f"h{h}_{gate}_{arm}"] = cell_stats(trades)

    art = {"tag": args.tag, "horizons": list(PROBE_HORIZONS),
           "split_hour": grid[split_j], "hours": n,
           "train_hours": split_j, "test_hours": n - split_j,
           "edge_bp": EDGE_BP, "age_h": AGE_H, "stop": "mean-mae",
           "gates": [{"name": g, "rr_min": lo, "rr_max": hi}
                     for g, lo, hi in GATES],
           "ic_test": {f"h{h}_{arm}": v
                       for (h, arm), v in ics.items()},
           "cells": cells,
           "took_sec": round(time.time() - t0, 1)}
    jp = os.path.join(out_dir, f"S11-horizon-{args.tag}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    write_report(art, os.path.join(out_dir,
                                   f"S11-horizon-{args.tag}.md"))
    print(f"готово за {art['took_sec']} с → {jp}", flush=True)
    if not args.no_publish:
        publish()
    return 0


def write_report(art, path):
    L = ["# S11 — зонд горизонта сигнала ситуационных книг", "",
         f"Часов {art['hours']}, разрез {art['split_hour']} "
         f"(обучение {art['train_hours']} ч, реплей "
         f"{art['test_hours']} ч). Гейт входа {art['edge_bp']} б.п., "
         f"стоп — линия среднего `mae` у ВСЕХ горизонтов, предел "
         f"возраста {art['age_h']} ч. Это диагностика поверхности, "
         f"не вердикт: выбрать лучшую ячейку задним числом — ошибка "
         f"R5; вход реплея — закрытие часа, правила сканера v4–v12 "
         f"не воспроизводятся (одинаково у всех горизонтов); оценка "
         f"по одной разбивке времени.", "",
         "## IC на хвосте (вне обучения), медиана по сечениям", "",
         "| горизонт | рука | IC | сечений |", "|---|---|---|---|"]
    for k, (ic, ns) in sorted(art["ic_test"].items()):
        h, arm = k.rsplit("_", 1)
        L.append(f"| {h} | {arm} | "
                 f"{'—' if ic is None else f'{ic:+.4f}'} | {ns} |")
    for gate in [g["name"] for g in art["gates"]]:
        L += ["", f"## Книга `{gate}`", "",
              "| горизонт | рука | сделок | побед | средн. б.п. | "
              "медиана | итог | худшая | просадка кривой |",
              "|---|---|---|---|---|---|---|---|---|"]
        for key, c in sorted(art["cells"].items()):
            hpart, gpart, arm = key.split("_")
            if gpart != gate:
                continue
            if not c.get("n"):
                L.append(f"| {hpart} | {arm} | 0 | — | — | — | — | "
                         f"— | — |")
                continue
            L.append(f"| {hpart} | {arm} | {c['n']} | {c['win']:.2f} "
                     f"| {c['mean_bp']:+.1f} | {c['median_bp']:+.1f} "
                     f"| {c['total_bp']:+.0f} | {c['worst_bp']:+.0f} "
                     f"| {c['curve_dd_bp']:+.0f} |")
    L += ["", f"Прогон {art['took_sec']} с."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def publish():
    """Отчёт публикует сам прогон: шаг, который можно забыть,
    забывают (уроки D1 и width)."""
    sh = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                      "tools", "publish.sh")
    try:
        subprocess.run(["bash", sh], check=False, timeout=300)
    except Exception as e:                            # noqa: BLE001
        print(f"публикация не прошла: {e}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
