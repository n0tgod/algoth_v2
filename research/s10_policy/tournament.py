#!/usr/bin/env python3
"""
Турнир политик исполнения ситуационной книги (спека 10, этапы V1–V2).

Вопрос владельца: пусть система сама пробует варианты поведения —
стоп/тейк/предел возраста/порог RR — и сама определяет лучшие, а не
ждёт «а давай попробуем поменять то». Проверяемая формулировка из
спеки: выбор политики по её же прошлому (walk-forward) обязан быть
лучше СЛУЧАЙНОГО выбора из того же пространства — иначе «система сама
подстраивается» есть украшение.

Главная опасность имеет имя: перебор без поправки (R5: при 96 ячейках
лучшая из пустышек дала бы Sharpe 1.19 случайно). Поэтому судится не
победитель, а ПРАВИЛО ВЫБОРА: пространство объявлено ниже и не растёт
после подглядывания, селектор работает walk-forward без права
переиграть, испытание в статистике одно. Таблица всех вариантов
публикуется как диагностика; выбрать по ней лучшую ячейку и предъявить
её — запрещено спекой.

Топливо — журнал листов сечения (`sheets.jsonl`): каждый час всё
сечение с прогнозом, обещаниями пути и квантильными концами. Исходы —
по минутным барам собственной записи сборщика. Оговорки, объявленные
до прогона и не снимаемые результатом: веса видели эти часы (верхняя
граница); скидка и взведение живого сканера не реплеятся (одинаково у
всех вариантов); журнал начат 2026-08-08, вердикт §8 ждёт календаря.

    .venv/bin/python research/s10_policy/tournament.py \\
        --sheets research/s8_loop/out/model_sit/sheets.jsonl \\
        --root research/b1_book/out
"""

import argparse
import json
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s9_sweep"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))
import trades as TR                                          # noqa: E402
import sweep as SW                                           # noqa: E402

# ---------------------------------------------------------------------
# Пространство политик. ОБЪЯВЛЕНО спекой 10 §3 и не меняется после
# результата; новые оси — новая редакция раздела 3 ДО их прогона.
EDGES = [22.0, 33.0]
RRS = [1.5, 2.0, 3.0]
STOPS = ["q", "m", "none"]        # выученный квантиль / прогноз / нет
TAKES = [True, False]
AGES = [24, 72]
# Вариант текущих правил живой книги — референс селектора.
CURRENT = "e22_rr2.0_sq_t1_a24"

SLOTS = 6                          # забор, не ось поиска (спека §3)
SEL_STEP_D = 7                     # точка выбора — раз в 7 суток
SEL_WIN_D = 28                     # окно оценки селектора
MIN_WIN_TRADES = 30                # годность варианта в окне
N_SEEDS = 10                       # случайных селекторов
MIN_POINTS = 8                     # календарь вердикта §8.2
MIN_WF_TRADES = 300
# Рука kill-10 (§7.1, правка владельца 2026-08-10 до первого прогона):
# вариант с отрицательной суммой за последние KILL_D суток при не
# менее чем KILL_MIN_TRADES сделках — сливающий: не выбирается нигде,
# держимый снимается немедленно. Правило по СУММЕ, а не по серии
# красных дней: копеечная зелёная свеча не должна обнулять счётчик.
KILL_D = 10
KILL_MIN_TRADES = 10
DAY = 86400


def variants():
    """Все 72 объявленных варианта; ключ — имя ячейки в артефактах."""
    out = []
    for edge in EDGES:
        for rr in RRS:
            for stop in STOPS:
                for take in TAKES:
                    for age in AGES:
                        out.append({
                            "key": f"e{edge:.0f}_rr{rr}_s{stop[0]}_"
                                   f"t{int(take)}_a{age}",
                            "edge": edge, "rr": rr, "stop": stop,
                            "take": take, "age": age})
    return out


# ---------------------------------------------------------------------
# Ноги из журнала листов.

def legs_from_sheets(paths, log=print):
    """Каждая строка каждого листа — кандидат в сделку.

    Сторона — знак прогноза (так входит и живой сканер). Геометрия —
    через `TR.path_fields`, тот же код, что у книги: исполняемый стоп
    — дальний из квантильного и среднего (`wider_stop`), линия
    прогноза остаётся полем `mae_m`. Риск для гейта RR — ВСЕГДА
    исполняемый уровень, у всех осей стопа одинаково: гейт, меняющий
    определение риска вместе с осью, сравнивал бы ячейки по разным
    величинам (спека §3).
    """
    legs = []
    for path in paths:
        n0 = len(legs)
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
                at = rec.get("written_at") or (
                    (TR._ts(rec.get("hour")) or 0) + 3600)
                if not at:
                    continue
                for arm, rows in (rec.get("arms") or {}).items():
                    for row in rows or []:
                        lg = _leg(row, arm, rec.get("hour"), float(at))
                        if lg is not None:
                            legs.append(lg)
        log(f"{os.path.basename(path)}: ног {len(legs) - n0}")
    legs.sort(key=lambda g: (g["at"], g["arm"], g["sym"]))
    for i, lg in enumerate(legs):
        lg["id"] = i
    return legs


def _leg(row, arm, hour, at):
    fwd = row.get("fwd")
    px = row.get("px")
    if not px or fwd is None or not fwd:
        return None
    if row.get("mae") is None or row.get("mfe") is None:
        return None
    side = "long" if fwd > 0 else "short"
    pf = TR.path_fields(side, float(row["mae"]), float(row["mfe"]),
                        mae_q=row.get("mae_q"), mfe_q=row.get("mfe_q"))
    adv_q, fav = pf["mae"], pf["mfe"]
    adv_m = pf.get("mae_m", adv_q)
    # Знаковая проверка сторон — та же, что у сканера: обещание,
    # смотрящее не в ту сторону, не есть заявка модели.
    if side == "long" and not (fav > 0 and adv_q < 0):
        return None
    if side == "short" and not (fav < 0 and adv_q > 0):
        return None
    risk = abs(adv_q)
    return {"arm": arm or "gbm", "sym": row.get("sym"), "hour": hour,
            "at": at, "side": side, "fwd": float(fwd), "px": float(px),
            "adv_q": adv_q, "adv_m": adv_m, "fav": fav,
            "rr": abs(fav) / risk if risk else None}


# ---------------------------------------------------------------------
# Исход одной ноги при заданных уровнях.

def outcome(bars, t0, side, adv, fav, age_h):
    """Чем кончилась сделка: стоп, цель или срок.

    Вход — ОТКРЫТИЕ первого бара после `t0` (первая доступная цена, не
    подарок — правило `next_open` зонда возврата). Уровни якорятся к
    цене ВХОДА: обещания записаны в б.п. от цены листа, а вход
    случается минутами позже; переякорить точнее нечем — волна листа в
    реплее не воспроизводится, и приближение одинаково у всех
    вариантов. Касание двух уровней внутри одного бара решается ПРОТИВ
    нас (правило T3/T4 и живого сторожа). `adv`/`fav` могут быть
    `None` — ось без стопа / без тейка. Нет баров — `None`: пропуск,
    а не наблюдение (урок A2).
    """
    end = t0 + age_h * 3600
    seen = [b for b in bars if t0 <= b[0] <= end]
    if not seen:
        return None
    entry_px = seen[0][1]
    if not entry_px or entry_px <= 0:
        return None
    long = side == "long"
    stop_lvl = entry_px * (1 + adv / 1e4) if adv is not None else None
    take_lvl = entry_px * (1 + fav / 1e4) if fav is not None else None
    for b in seen:
        low, high = b[3], b[2]
        if stop_lvl is not None and (
                low <= stop_lvl if long else high >= stop_lvl):
            return "стоп", (stop_lvl / entry_px - 1) * 1e4, b[0], entry_px
        if take_lvl is not None and (
                high >= take_lvl if long else low <= take_lvl):
            return "цель", (take_lvl / entry_px - 1) * 1e4, b[0], entry_px
    last = seen[-1]
    return "срок", (last[4] / entry_px - 1) * 1e4, last[0], entry_px


def leg_outcomes(lg, bars):
    """Исходы ноги по всем сочетаниям осей выхода — один раз на ногу.

    Ячеек 72, но уникальных сочетаний (стоп × тейк × возраст) — 12:
    гейты (`edge`, `rr`) лишь фильтруют, и считать бракет по 72 раза
    значило бы платить вшестеро за те же числа.
    """
    out = {}
    for stop in STOPS:
        adv = {"q": lg["adv_q"], "m": lg["adv_m"], "none": None}[stop]
        for take in TAKES:
            fav = lg["fav"] if take else None
            for age in AGES:
                out[(stop, take, age)] = outcome(
                    bars, lg["at"], lg["side"], adv, fav, age)
    return out


# ---------------------------------------------------------------------
# Книга одного варианта: слоты и одна позиция на имя — забор, который
# моделируется, а не игнорируется: вариант с мягким гейтом берёт
# больше сделок только в пределах тех же шести мест, иначе сравнивались
# бы книги разной ширины.

def simulate(legs, outs, var):
    trades = []
    books = {}                      # рука -> {имя: момент выхода}
    for lg in legs:
        if abs(lg["fwd"]) < var["edge"]:
            continue
        if (lg["rr"] or 0) < var["rr"]:
            continue
        got = outs.get((lg["id"], var["stop"], var["take"], var["age"]))
        if got is None:
            continue
        book = books.setdefault(lg["arm"], {})
        for s, e in list(book.items()):
            if e <= lg["at"]:
                del book[s]
        if lg["sym"] in book or len(book) >= SLOTS:
            continue
        why, move, exit_ts, entry_px = got
        net = ((1 if lg["side"] == "long" else -1) * move
               - TR.ROUND_COST_BP)
        book[lg["sym"]] = exit_ts
        trades.append({"at": lg["at"], "exit": exit_ts,
                       "net": round(net, 1), "why": why,
                       "sym": lg["sym"], "arm": lg["arm"],
                       "side": lg["side"]})
    return trades


def daily(trades):
    """День ВЫХОДА -> (сумма нетто б.п., число сделок).

    Сделка принадлежит дню, когда деньги стали известны, — то же
    правило, что у лиги; иначе селектор в точке выбора видел бы
    сделки, чей исход ещё не наступил.
    """
    d = {}
    for t in trades:
        day = int(t["exit"] // DAY)
        rec = d.setdefault(day, [0.0, 0])
        rec[0] += t["net"]
        rec[1] += 1
    return d


# ---------------------------------------------------------------------
# Селектор и его нули.

def _win(series, d0, d1):
    """Сумма и число сделок по дням `[d0, d1)`."""
    tot = n = 0.0
    for day, (s, c) in series.items():
        if d0 <= day < d1:
            tot += s
            n += c
    return tot, int(n)


def _elig(series_by_key, keys, D):
    """Годные варианты на день `D`: окно 28 суток, не тоньше 30 сделок."""
    out = []
    for k in keys:
        tot, n = _win(series_by_key[k], D - SEL_WIN_D, D)
        if n >= MIN_WIN_TRADES:
            out.append((k, tot))
    return out


def _bleeding(series, D):
    """Сливает ли вариант по правилу kill-10 на день `D`.

    Вариант без сделок в окне не сливает, а простаивает — его правило
    не трогает (иначе тихая книга снималась бы за тишину).
    """
    tot, n = _win(series, D - KILL_D, D)
    return tot < 0 and n >= KILL_MIN_TRADES


def _rnd_pick(seed, point_idx, n):
    """Зерно выводится ЧИСЛОМ из номера зерна и номера точки.

    Не `hash`: хеш строки солится на процесс, и нулевую модель было
    бы не повторить (дефект R3). Значения закреплены тестом числом.
    """
    return (seed * 1000003 + point_idx * 7919) % n


def walk_forward(series_by_key, keys, log=print):
    """Кривые селектора, оракула, случайных и референса.

    Селектор: в точке `D` окно оценки — `[D-28, D)` по дням ВЫХОДА,
    годность ≥ 30 сделок, метрика — сумма нетто, argmax; при
    равенстве остаётся прежний (устойчивость, а не второй параметр).
    Оракул выбирает из ТОГО ЖЕ годного множества лучшего в следующем
    окне — потолок с знанием будущего (приём S1/T1): если оракул
    неотличим от случайного, варианты не различаются и направление
    закрыто дёшево.
    """
    days = [d for s in series_by_key.values() for d in s]
    if not days:
        return None
    first, last = min(days), max(days)
    points = []
    d0 = first + SEL_WIN_D
    while d0 <= last:
        points.append(d0)
        d0 += SEL_STEP_D
    if not points:
        return None
    sel = {"picks": [], "days": {}, "trades": 0}
    ora = {"picks": [], "days": {}, "trades": 0}
    rnd = [{"days": {}, "trades": 0} for _ in range(N_SEEDS)]
    prev = None
    for i, D in enumerate(points):
        elig = _elig(series_by_key, keys, D)
        if not elig:
            # Точка без годных: держим прежний выбор, а не выдумываем.
            if prev is None:
                continue
            elig = [(prev, 0.0)]
        best = max(v for _, v in elig)
        top = [k for k, v in elig if v == best]
        pick = prev if prev in top else top[0]
        prev = pick
        sel["picks"].append({"day": D, "pick": pick,
                             "elig": len(elig)})
        fwd_end = min(D + SEL_STEP_D, last + 1)
        _add(sel, series_by_key[pick], D, fwd_end)
        onames = [k for k, _ in elig]
        obest = max(onames, key=lambda k: _win(
            series_by_key[k], D, fwd_end)[0])
        ora["picks"].append(obest)
        _add(ora, series_by_key[obest], D, fwd_end)
        for s in range(N_SEEDS):
            rk = onames[_rnd_pick(s + 1, i, len(onames))]
            _add(rnd[s], series_by_key[rk], D, fwd_end)
    if not sel["picks"]:
        return None
    kill, kill_ev = _kill_arm(series_by_key, keys, points, last)
    span = (sel["picks"][0]["day"], last + 1)
    ref = {"days": {}, "trades": 0}
    if CURRENT in series_by_key:
        _add(ref, series_by_key[CURRENT], span[0], span[1])
    return {"points": sel["picks"], "sel": _tot(sel), "ora": _tot(ora),
            "rnd": [_tot(r) for r in rnd], "ref": _tot(ref),
            "kill": _tot(kill), "kill_events": kill_ev,
            "span_days": span[1] - span[0]}


def _kill_arm(series_by_key, keys, points, last):
    """Рука kill-10: базовый селектор плюс правило свежести (§7.1).

    Нуль этой руки — сама базовая ветка: обе идут по одним дням, и
    разность кривых ЕСТЬ эффект правила. Ходит по дням, а не по
    точкам: снятие сливающего варианта не ждёт расписания.
    """
    acc = {"days": {}, "trades": 0, "picks": []}
    events = []
    pts = set(points)
    prev = None
    held = 0
    for D in range(points[0], last + 1):
        if D in pts:
            elig = [(k, v) for k, v in _elig(series_by_key, keys, D)
                    if not _bleeding(series_by_key[k], D)]
            if elig:
                best = max(v for _, v in elig)
                top = [k for k, v in elig if v == best]
                prev = prev if prev in top else top[0]
                acc["picks"].append({"day": D, "pick": prev})
            elif prev is not None:
                held += 1              # некого выбрать — держим текущий
        elif prev is not None and _bleeding(series_by_key[prev], D):
            was = prev
            elig = [(k, v) for k, v in _elig(series_by_key, keys, D)
                    if k != prev
                    and not _bleeding(series_by_key[k], D)]
            if elig:
                best = max(v for _, v in elig)
                prev = [k for k, v in elig if v == best][0]
                events.append({"day": D, "was": was, "to": prev})
                acc["picks"].append({"day": D, "pick": prev,
                                     "kill": True})
            else:
                held += 1
        if prev is not None:
            got = series_by_key[prev].get(D)
            if got:
                acc["days"][D] = acc["days"].get(D, 0.0) + got[0]
                acc["trades"] += got[1]
    acc["held_bleeding"] = held
    return acc, events


def _add(acc, series, d0, d1):
    for day, (s, c) in series.items():
        if d0 <= day < d1:
            rec = acc["days"].setdefault(day, 0.0)
            acc["days"][day] = rec + s
            acc["trades"] += c


def curve_dd(day_sums):
    """Глубочайший провал накопленной кривой и её итог.

    Единица — та же, в которой считаются сами ячейки: СУММА
    результатов ног (`Σ` процентов на ногу), а не процент депозита —
    размер позиции реплей не моделирует, он моделирует слоты. Значит
    это просадка КРИВОЙ ветки, и называть её просадкой баланса
    нельзя: при шести слотах шесть ног по −3 % дают день в −18, но
    депозит столько не теряет.

    Одна реализация на ячейки таблицы и на кривые селектора: вторая
    однажды разошлась бы, и таблица говорила бы одно, а вердикт
    другое.
    """
    run = peak = dd = 0.0
    for d in sorted(day_sums):
        run += day_sums[d]
        peak = max(peak, run)
        dd = min(dd, run - peak)
    return round(run, 1), round(dd, 1)


def _tot(acc):
    run, dd = curve_dd(acc["days"])
    return {"total_bp": run, "dd_bp": dd,
            "trades": acc.get("trades", 0),
            "picks": acc.get("picks", None)}


def verdict(wf):
    """Вердикт по §8 спеки 10 — либо честное «диагностика, не вердикт».

    95-й процентиль десяти значений есть попросту их максимум
    (nearest-rank, урок R3 о чтении процентиля десяти) — поэтому рядом
    печатается и расстояние в сигмах.
    """
    if wf is None:
        return {"status": "нет точек выбора — журнал короче 28 суток"}
    rnd = sorted(r["total_bp"] for r in wf["rnd"])
    med = st.median(rnd)
    p95 = rnd[-1]
    sel = wf["sel"]["total_bp"]
    sd = st.pstdev(rnd) or None
    out = {"rnd_median_bp": round(med, 1), "rnd_p95_bp": round(p95, 1),
           "sigma": round((sel - st.mean(rnd)) / sd, 1) if sd else None,
           "points": len(wf["points"]), "wf_trades": wf["sel"]["trades"]}
    if sel < med:
        out["status"] = ("НЕМЕДЛЕННАЯ ОСТАНОВКА §8.1: селектор ниже "
                         "медианы случайных — выбор по прошлому не "
                         "несёт информации")
        return out
    if len(wf["points"]) < MIN_POINTS \
            or wf["sel"]["trades"] < MIN_WF_TRADES:
        out["status"] = (f"диагностика, не вердикт: точек "
                         f"{len(wf['points'])} из {MIN_POINTS}, сделок "
                         f"{wf['sel']['trades']} из {MIN_WF_TRADES} "
                         f"(§8.2)")
        return out
    ref = wf["ref"]
    ok = (sel > p95 and sel >= ref["total_bp"]
          and wf["sel"]["dd_bp"] >= 1.5 * ref["dd_bp"])
    out["status"] = ("ПОЛОЖИТЕЛЬНЫЙ §8.3 — открывается V3"
                     if ok else "критерии §8.3 не выполнены")
    # §8.5: рука kill-10 идёт в V3 вместо базовой только если на общих
    # днях её итог выше И она сама выше 95-го процентиля случайных.
    if ok and wf.get("kill"):
        kt = wf["kill"]["total_bp"]
        out["v3_arm"] = ("kill-10" if kt > sel and kt > p95
                         else "base")
    return out


# ---------------------------------------------------------------------

def run(sheets, root, src=None, log=print):
    legs = legs_from_sheets(sheets, log=log)
    # Бары нужны только ногам, проходящим слабейший гейт: остальные не
    # возьмёт ни один вариант, и сеть за ними — чистая потеря.
    need = [g for g in legs if abs(g["fwd"]) >= min(EDGES)
            and (g["rr"] or 0) >= min(RRS)]
    log(f"ног всего {len(legs)}, под слабейшим гейтом {len(need)}")
    outs, said = {}, time.time()
    span = max(AGES) * 3600
    for i, lg in enumerate(need):
        if time.time() - said > 30:
            log(f"  бары: {i}/{len(need)}")
            said = time.time()
        get = src.bars if src else (
            lambda sym, a, b: SW.read_bars(root, sym, a, b))
        bars = get(lg["sym"], lg["at"], lg["at"] + span)
        for k, v in leg_outcomes(lg, bars).items():
            outs[(lg["id"],) + k] = v
    cells = []
    series = {}
    for var in variants():
        tr = simulate(need, outs, var)
        day = daily(tr)
        series[var["key"]] = day
        nets = [t["net"] for t in tr]
        row = dict(var, n=len(nets))
        if nets:
            wins = sum(1 for v in nets if v > 0)
            _, dd = curve_dd({d: v[0] for d, v in day.items()})
            row.update(win=round(wins / len(nets), 3),
                       exp_bp=round(sum(nets) / len(nets), 1),
                       med_bp=round(st.median(nets), 1),
                       total_bp=round(sum(nets), 1),
                       # Худшая СДЕЛКА и просадка КРИВОЙ — разные
                       # величины: сделка могла провалиться глубже и
                       # вернуться, а кривая копит провал по дням.
                       worst_bp=round(min(nets), 1),
                       dd_bp=dd)
        cells.append(row)
    wf = walk_forward(series, [v["key"] for v in variants()], log=log)
    return legs, cells, wf


def report(legs, cells, wf, path):
    v = verdict(wf)
    ok = [c for c in cells if c.get("n", 0) >= MIN_WIN_TRADES]
    lines = [
        "# Турнир политик исполнения (спека 10)", "",
        f"- ног в журнале листов: **{len(legs)}**; слоты {SLOTS}, одна "
        f"позиция на имя, круг {TR.ROUND_COST_BP} б.п. на ногу",
        "- оценка ОПТИМИСТИЧНА: веса видели эти часы; скидка и "
        "взведение сканера не реплеятся. Верхняя граница, не бэктест",
        "- таблица вариантов — ДИАГНОСТИКА. Выбрать лучшую ячейку и "
        "предъявить её нельзя (§2); вердикт выносится по селектору",
        "",
        "## Селектор (вердикт §8)", "",
    ]
    if wf is None:
        lines.append(f"- {v['status']}")
    else:
        sel, ref, ora = wf["sel"], wf["ref"], wf["ora"]
        kl = wf.get("kill")
        kev = wf.get("kill_events") or []
        rnds = [r["total_bp"] for r in wf["rnd"]]
        lines += [
            f"- статус: **{v['status']}**",
            f"- селектор: **{sel['total_bp']:+.1f} б.п.** за "
            f"{wf['span_days']} дн., {sel['trades']} сделок, просадка "
            f"{sel['dd_bp']:.1f} б.п.; точек выбора {len(wf['points'])}",
            f"- случайный селектор (10 зёрен): медиана "
            f"{v['rnd_median_bp']:+.1f}, максимум {v['rnd_p95_bp']:+.1f}"
            f"; расстояние {v['sigma']} σ" if v.get("sigma") is not None
            else f"- случайные: {rnds}",
            f"- референс (текущие правила, {CURRENT}): "
            f"{ref['total_bp']:+.1f} б.п., просадка {ref['dd_bp']:.1f}",
            f"- оракул (знание будущего, потолок): "
            f"{ora['total_bp']:+.1f} б.п. — если он рядом со "
            f"случайными, варианты не различаются и направление "
            f"закрыто дёшево",
            (f"- рука kill-10 (\u00a77.1): {kl['total_bp']:+.1f} "
             f"б.п., просадка {kl['dd_bp']:.1f}, снятий {len(kev)}; "
             f"разность с базовым на общих днях "
             f"{kl['total_bp'] - sel['total_bp']:+.1f} б.п. — она и "
             f"есть эффект правила") if kl
            else "- рука kill-10: точек нет",
            "- выбор по точкам: " + ", ".join(
                f"{p['pick']}({p['elig']})" for p in wf["points"]),
        ]
    lines += [
        "", "## Все 72 варианта (диагностика)", "",
        f"ячейка тоньше {MIN_WIN_TRADES} сделок — неизмерена, а не "
        f"нулевая", "",
        "| вариант | сделок | побед | ожидание, б.п. | медиана | "
        "итог | худшая |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in sorted(cells, key=lambda q: q["key"]):
        n = c.get("n", 0)
        cur = " **·текущие**" if c["key"] == CURRENT else ""
        if not n:
            lines.append(f"| {c['key']}{cur} | 0 | — | — | — | — | — |")
            continue
        few = "" if n >= MIN_WIN_TRADES else " ·мало"
        lines.append(
            f"| {c['key']}{cur} | {n}{few} | {c['win']} | "
            f"{c['exp_bp']:+} | {c['med_bp']:+} | {c['total_bp']:+} | "
            f"{c['worst_bp']:+} |")
    if ok:
        lines += ["", f"- измеренных {len(ok)} из {len(cells)}; медиана "
                  f"ожидания по измеренным "
                  f"{st.median([c['exp_bp'] for c in ok]):+.1f} б.п."]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", nargs="+", default=[os.path.join(
        os.path.dirname(HERE), "s8_loop", "out", "model_sit",
        "sheets.jsonl")])
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(HERE), "b1_book", "out"))
    ap.add_argument("--http", default="",
                    help="адрес страницы наблюдения вместо записей")
    ap.add_argument("--key", default="")
    ap.add_argument("--cache", default="")
    # Имя артефакта различает источник и смоук: смоук однажды уже
    # подменял артефакт настоящего прогона (урок F2).
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.out:
        name = "V1-tournament"
        if a.http:
            name += "-remote"
        if a.tag:
            name += f"-{a.tag}"
        a.out = os.path.join(HERE, "out", name + ".md")
    # Каталог артефактов создаётся ДО счёта, а не в report(): живой
    # прогон на сервере досчитал все бары и упал на записи JSON —
    # свежий чекаут каталога out/ не несёт, а создавал его только
    # отчёт, который зовётся после. Полтора часа работы терялись на
    # последнем шаге — тот же класс отказа, что прогон A1 с
    # --with-fees, падавший на подписи после обхода всех символов.
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    src = None
    if a.http:
        src = SW.HttpBars(a.http, a.key, disk=a.cache or None)
    legs, cells, wf = run(a.sheets, a.root, src=src)
    if src and src.miss:
        print(f"ВНИМАНИЕ: {src.miss} ответов с чужим символом отброшено")
    with open(a.out.replace(".md", ".json"), "w", encoding="utf-8") as f:
        json.dump({"cells": cells, "legs": len(legs),
                   "wf": wf, "verdict": verdict(wf)},
                  f, ensure_ascii=False, indent=1)
    print("отчёт:", report(legs, cells, wf, a.out))


if __name__ == "__main__":
    main()
