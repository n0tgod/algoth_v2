#!/usr/bin/env python3
"""Зонд продолжения сквиза: ЛОНГ после каскада ликвидаций ВВЕРХ.

Клетка, которую гипотеза 5 не считала никогда: L1 намерил, что после
каскада вверх цена ПРОДОЛЖАЕТ (+0.17/+0.31/+0.62 % на 5/15 мин и
сутках), но спека 06 пошла за отскоком вниз, и «вверх» на
подтверждающей части не проверялся. Это единственная конструкция
проекта с ПОЛОЖИТЕЛЬНЫМ хвостом — все закрытые гипотезы собирали
понемногу и отдавали помногу.

Это ЗОНД: порогов вердикта нет. Пороги события — те же, что у спеки
06, не перебираются: интерес −1 %, ход +3 % за 15 минут (диагностикой
рядом −3 %/+3 %... нет: вторая клетка НЕ считается — просмотр
поверхности после данных и был бы перебором). Горизонты 15/60/240 мин
плюс справочные 5 и 1440. Событие: цена ВЫРОСЛА на 3 % при ПАДЕНИИ
интереса на 1 % — принудительно закрывают шортов; позиция — лонг
продолжения.

Всё чужое переиспользовано, а не скопировано: отбор событий, форварды,
контроль 1 (одновременная кросс-секция), контроль 2 (тот же рост БЕЗ
условия на интерес — если продолжение то же, механизм ликвидаций есть
украшение), оба нуля и разбиение на разведочную/подтверждающую части —
функции `l3_events` (`scan_symbols(direction=+1)`, `measure`).

Как это умрёт, названо до прогона: контроль 1 — продолжение
принадлежит рынку, как отскок вниз принадлежал ему на 88–90 %; либо
контроль 2 — «покупай рост» без ликвидаций даёт то же. И оговорка
исполнения: вход в момент сквиза — покупка в вертикальном движении,
спред раздут (D1 мерил ×1.2 на падениях), так что валовые числа —
верхняя граница.

    setsid nohup .venv/bin/python research/probe_upcascade/up.py \
        > research/probe_upcascade/out/run.log 2>&1 &
"""

import argparse
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

sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "probe_turn"))

import data as D                                          # noqa: E402
import events as E                                        # noqa: E402
import turn as PT                                         # noqa: E402

# Плоские имена `data`/`events` в проекте не уникальны, и чужой модуль
# на пути импорта уже подменял нули в F3. Проверяем, ЧТО загрузилось.
for _mod, _want in ((D, "l3_events"), (E, "l3_events"),
                    (PT, "probe_turn")):
    _got = os.path.basename(os.path.dirname(os.path.abspath(_mod.__file__)))
    assert _got == _want, f"чужой модуль: {_mod.__name__} из {_got}"

# `import run` подхватил бы чужой прогон — модулей run в проекте
# десяток (урок D1). По файлу, с проверкой.
_spec = importlib.util.spec_from_file_location(
    "l3_run", os.path.join(RESEARCH, "l3_events", "run.py"))
L3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L3)
assert hasattr(L3, "scan_symbols") and hasattr(L3, "measure"), \
    "загружен не прогон L3"

DIRECTION = +1                     # рост; событие — каскад ВВЕРХ


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def fmt_bp(v):
    return "—" if v is None or not np.isfinite(v) else f"{v * 1e4:+.1f}"


def med(a):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.median(a)) if len(a) else float("nan")


def rows_for(res):
    """Строки таблицы одной руки: по горизонтам — сырой ход, сверх
    кросс-секции (по событиям и по эпизодам), доля положительных
    эпизодов, нули."""
    out = []
    for h in L3.HORIZONS + L3.DIAGNOSTIC:
        f = res.get(f"fwd_{h}")
        if f is None:
            continue
        cs = res.get(f"cross_{h}")
        exc = (np.where(np.isfinite(f) & np.isfinite(cs), f - cs,
                        np.nan) if cs is not None else None)
        epx = res.get(f"ep_cross_{h}")
        n1 = res.get(f"null1_{h}")
        row = {
            "h": h,
            "raw_med": med(f),
            "exc_med": med(exc) if exc is not None else None,
            "ep_exc_med": med(epx) if epx is not None else None,
            "ep_pos": (float(np.mean(np.asarray(epx)[
                np.isfinite(epx)] > 0))
                if epx is not None and np.isfinite(epx).any()
                else None),
            "n_ep": (int(np.isfinite(epx).sum())
                     if epx is not None else 0),
            "null1_med": (med(n1) if n1 is not None and len(n1)
                          else None),
            "null2": res.get(f"null2_{h}")}
        out.append(row)
    return out


def write_report(path, blocks, meta):
    L = ["# Зонд продолжения сквиза — лонг после каскада ВВЕРХ\n"]
    L.append(f"Прогон {meta['when']} · порог {L3.OI_DROP:.0%} интереса"
             f" / +{L3.MOVE:.0%} цены за {E.WINDOW_MIN} мин · символов "
             f"{meta['symbols']} · окно {meta['start']}…{meta['end']}\n")
    L.append("**Зонд, не вердикт.** Пороги — спеки 06, не "
             "перебираются; вторая клетка порога НЕ считается. "
             "Позиция — лонг продолжения. Событие: рост при ПАДЕНИИ "
             "интереса (закрывают шортов). Контроль 1 — одновременная "
             "кросс-секция (не «рынок растёт»), контроль 2 — тот же "
             "рост БЕЗ условия на интерес (не «покупай рост»). "
             "Исполнение не смоделировано: вход в вертикальном "
             "движении, валовые числа — верхняя граница.\n")
    for name, arms in blocks:
        L.append(f"\n## {name} часть\n")
        for arm_name, res in arms:
            if res is None:
                L.append(f"\n### {arm_name}: событий нет\n")
                continue
            L.append(f"\n### {arm_name} — событий {res['events']:,}, "
                     f"эпизодов {res['episodes']:,}\n")
            L.append("| горизонт, мин | сырой ход | сверх кросс-секции"
                     " | по эпизодам | доля эпизодов >0 | эпизодов | "
                     "нуль 1 | нуль 2 |")
            L.append("|--:|--:|--:|--:|--:|--:|--:|--:|")
            for r in rows_for(res):
                L.append(
                    f"| {r['h']} | {fmt_bp(r['raw_med'])} | "
                    f"{fmt_bp(r['exc_med'])} | "
                    f"{fmt_bp(r['ep_exc_med'])} | "
                    + ("—" if r["ep_pos"] is None
                       else f"{r['ep_pos']:.2f}")
                    + f" | {r['n_ep']} | {fmt_bp(r['null1_med'])} | "
                    f"{fmt_bp(r['null2'])} |")
    L.append("\nЧитать: «сверх кросс-секции» по эпизодам — главная "
             "колонка (б.п.); событие обязано бить контроль 2 — иначе "
             "механизм ликвидаций ничего не добавляет к «покупай "
             "рост». Круг издержек: 11 б.п. комиссии на $10 тыс. плюс "
             "спред момента события (D1 мерил 6–7 б.п. на сторону в "
             "стрессе).\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="лонг после каскада вверх")
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", default=D.START)
    ap.add_argument("--end", default=D.END)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()

    times = D.grid(a.start, a.end)
    uni = D.universe()
    have = sorted(s[:-len(".npz")] for s in os.listdir(D.OI_SERIES)
                  if s.endswith(".npz"))
    symbols = [s for s in have if s in uni]
    if a.limit:
        symbols = symbols[:a.limit]
    log_(f"символов {len(symbols)}, моментов {len(times):,}")
    share, min_share = D.liquid_days(a.interval)
    P = D.price_matrix(symbols, times, a.interval, log_)
    log_(f"матрица {P.shape}, заполнено {np.isfinite(P).mean():.1%}")

    rec, valid_by_row, hours = L3.scan_symbols(
        symbols, times, P, uni, share, min_share, log_,
        direction=DIRECTION)
    log_(f"событий всего {len(rec['col']):,} "
         f"({time.time() - t0:.0f} с)")
    blocks = []
    if len(rec["col"]):
        confirm = np.array([s not in D.EXPLORATORY
                            for s in rec["sym"]])
        for part, mask in (("Подтверждающая", confirm),
                           ("Разведочная", ~confirm)):
            sub = {k: v[mask] for k, v in rec.items()}
            arms = []
            for arm in ("event", "control2"):
                log_(f"замер: {part}, рука {arm}")
                arms.append((
                    "событие (рост + падение интереса)"
                    if arm == "event"
                    else "контроль 2 (рост без условия на интерес)",
                    L3.measure(sub, arm, times, P, valid_by_row,
                               hours, log_)))
            blocks.append((part, arms))
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"),
            "symbols": len(symbols), "start": a.start, "end": a.end}
    path = write_report(os.path.join(OUT, f"UPCASCADE-{a.tag}.md"),
                        blocks, meta)
    # В json уходят СТРОКИ таблицы, а не сырые векторы: артефакт
    # отвечает «что напечатано», сырьё пересчитывается прогоном.
    art = {"meta": meta, "blocks": [
        (part, [(an, None if res is None else
                 {"events": res["events"], "episodes": res["episodes"],
                  "rows": rows_for(res)})
                for an, res in arms])
        for part, arms in blocks]}
    with open(os.path.join(OUT, f"upcascade-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False)
    log_(f"отчёт: {path} · {time.time() - t0:.0f} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
