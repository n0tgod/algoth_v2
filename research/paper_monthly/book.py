#!/usr/bin/env python3
"""Бумажная месячная книга: запись решений вперёд, разбор через 30 дней.

Решение владельца (2026-08-27) по итогам зонда `probe_monthly` и трёх
замеров устойчивости. Спека не пишется: при t = 1.06 по Ньюи–Уэсту она
провалит любой честный критерий, и это видно ДО прогона. Единственный
рычаг, который здесь работает, — КАЛЕНДАРЬ, и книга существует ровно
затем, чтобы его копить.

Что здесь принципиально нового против зонда
-------------------------------------------

1. **Честное и восстановленное различаются в самой записи.** Решение
   несёт `written_at` — момент, когда оно попало в журнал. Записанное
   ДО начала форвардного окна есть настоящее наблюдение; досчитанное
   задним числом — бэктест, не хуже и не лучше зонда. Свод считает две
   группы ОТДЕЛЬНО и никогда их не смешивает: иначе через полгода
   кривая будет выглядеть треком, будучи наполовину пересчётом.

2. **Исход считается ОДНОЙ β — так, как торговали бы.** Зонд собирал
   месячный форвард сцеплением трёх 10-дневных кирпичей, каждый по
   своей β (готовые векторы R2 другого не позволяли), и честно
   записал это оговоркой, которую не смог измерить. Книга держит β,
   оценённую в момент решения, все 30 дней — прямое требование
   CLAUDE.md «не пересчитывать β на живой позиции». Расхождение книги
   с зондом на общих датах и есть цена той оговорки.

3. **Делистнутая нога держится до последнего бара** — исправление,
   найденное `robust.py`: выпадение умерших имён стоило зонду 44
   б.п./мес, и почти всё выпадение приходилось на длинную ногу.

Конструкция (объявлена до первого прогона и не меняется)
--------------------------------------------------------
Транши: каждый день открывается новый транш на равную долю капитала,
живёт `H = 30` дней и закрывается. Формация `k = 14`, ширина — дециль,
факторная модель — рыночная волна (ступень 1 лестницы §3.3), шаг бара
1h, окно оценки β 90 дней. Это ровно главная ячейка зонда `k14_h30`,
объявленная там до прогона; никакой сетки здесь нет и не будет —
книга проверяет ОДНУ конструкцию, а не выбирает лучшую.

Издержки транша: полная замена книги, оборот 2.0 × 5.5 б.п. = 11 б.п.
Транши не сальдируются между собой намеренно: пересечение составов
удешевило бы исполнение, но это оптимизация, а не свойство сигнала, и
считать её до того, как сигнал доказан, значит льстить себе.

Правило журнала: запись write-ahead, дедуп по дате, повторный прогон
не задваивает и НЕ переписывает. Меняются правила — версия в записи;
кривая по смешанным правилам не считается.

    python3 research/paper_monthly/book.py --catchup      # догнать
    python3 research/paper_monthly/book.py --report       # только свод
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "r1_factor"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
sys.path.insert(0, RESEARCH)

import residual as RS                                     # noqa: E402
import factor as FA                                       # noqa: E402
import series as S                                        # noqa: E402
import pairs as PR                                        # noqa: E402
import crosssection as CS                                 # noqa: E402
import run_d1 as R                                        # noqa: E402
from common import funding_series as FS                   # noqa: E402

# --- конструкция, объявлена до первого прогона ------------------------
RULES = 1
K_DAYS = 14              # формация сигнала
H_DAYS = 30              # удержание транша
FORM_DAYS = 90           # окно оценки β
WIDTH = 0.10             # дециль
STEP = "1h"
BARS_PER_DAY = 24
TAKER_BP = 5.5
TURNOVER = 2.0           # транш открывается и закрывается целиком
COST_BP = TURNOVER * TAKER_BP
MIN_ASSETS = 30
MODEL = "market"
START = "2026-08-01"     # засев: раньше — уже измерено зондом
# Решение считается записанным ВПЕРЁД, если попало в журнал не позже
# чем через двое суток после даты сечения.
#
# Двое, а не одни: задержка структурная, а не случайная. Суточный архив
# Binance за день `D` публикуется ПОСЛЕ конца суток `D`, а решению на
# дату `D` нужен бар с меткой `D` — значит раньше `D + 1` его посчитать
# нечем ни при каком расписании прогонов. Запас во вторые сутки — на
# сам прогон и на задержку публикации архива.
#
# Цена названа числом и меряется на каждой записи (`elapsed`): к
# моменту записи прожита ОДНА тридцатая форварда, 3.3 %. Это не
# подглядывание в сигнал — сигнал по-прежнему кончается на `D`, — но
# знать, что первый день форварда уже случился, честнее, чем молчать.
# Полностью снять задержку может только другой источник свежих баров
# (REST площадки вместо архива), и это отдельная работа.
AHEAD_TOL_SEC = 2 * 86400

DEC = os.path.join(OUT, "decisions.jsonl")
RES = os.path.join(OUT, "resolutions.jsonl")


def ms(day):
    return int(np.datetime64(day + "T00:00:00", "ms").astype("int64"))


def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def today():
    return datetime.now(timezone.utc).date().isoformat()


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_jsonl(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def archive_journal(reason, out=None):
    """Отставить журнал целиком, назвав причину.

    Журнал append-only: строку из него не правят и не удаляют. Но
    запись, сделанная ДЕФЕКТНЫМ кодом, недействительна — и оставлять её
    рядом с честными нельзя, иначе свод считает по смеси. Механизм тот
    же, что у ситуационной книги при смене правил: каталог уезжает в
    архив с меткой времени и причиной, запись начинается заново.
    """
    out = out or OUT
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    moved = []
    for name in ("decisions.jsonl", "resolutions.jsonl"):
        src = os.path.join(out, name)
        if os.path.exists(src):
            dst = os.path.join(out, f"{name}.{stamp}")
            os.replace(src, dst)
            moved.append(os.path.basename(dst))
    if moved:
        with open(os.path.join(out, f"ARCHIVED.{stamp}.txt"), "w",
                  encoding="utf-8") as f:
            f.write(f"{stamp}\n{reason}\n" + "\n".join(moved) + "\n")
    return moved


def note(why, reason):
    """Счётчик причины отказа. Пустой прогон обязан объяснять себя.

    Первый живой прогон дал «новых решений 0» и ни слова о том,
    почему, — тот же класс отказа, что чинился в зонде спокойного
    рынка: отсылка к причинам, которых никто не печатает.
    """
    if why is not None:
        why[reason] = why.get(reason, 0) + 1


def storage_span(interval="1m"):
    """Первая и последняя партиция хранилища A2 — как есть на диске.

    Нужна, чтобы пустой прогон объяснял себя числом: книга считается по
    хранилищу, а оно снимок, и если его край раньше запрошенных дат,
    решений не будет ни одного — это состояние данных, а не дефект
    сигнала, и путать их нельзя.
    """
    d = os.path.join(S.PARQUET, interval)
    if not os.path.isdir(d):
        return None, None, 0
    parts = sorted(f[:-len(".parquet")] for f in os.listdir(d)
                   if f.endswith(".parquet"))
    if not parts:
        return None, None, 0
    return parts[0], parts[-1], len(parts)


def build(con, at, liq, universe, of_group, forward, why=None):
    """Сечение даты `at`: β, сигнал и — при `forward` — исход.

    Одно окно данных `[at−90, at+30)`: факторы строятся на всём
    отрезке, β оценивается ТОЛЬКО на `[at−90, at)`, остаток форварда
    считается по ней же. Порядок тот же, что в `crosssection.run_date`,
    и формулы вызываются оттуда же — второй копии ядра нет.

    Возвращает `(names, beta, sig, fwd, bars, n_assets)`; `fwd` и
    `bars` равны `None`, когда `forward` выключен.
    """
    t0 = shift(at, -FORM_DAYS)
    # Окно решения кончается на СЛЕДУЮЩЕМ дне, а не на `at`, и это не
    # заглядывание: сетка помечает бар его НАЧАЛОМ, а цена бара — это
    # закрытие, известное в его конце. Значит цена с меткой `i_t − 1`
    # становится известна ровно в `at`, а последняя доходность сигнала
    # (`R[i_t − 1]`, конвенция `run_date` в R2) — часом позже, и вход
    # по конвенции R2 идёт по той же цене. Без этого бара срез
    # `Rm[f0:i_t]` молча выходил за конец матрицы и терял последний
    # час сигнала — решение расходилось с разбором той же даты, что
    # и поймала проверка «сигнал одинаков с будущим и без него».
    # Лишние часы загружены, но НЕ используются: границы окон считаются
    # от `at`, и это защита №1; вторая — само окно загрузки.
    t1 = shift(at, H_DAYS if forward else 1)
    st = PR.state_at(liq, universe, at)
    live = {a for a, s in st.items()
            if s["share_traded"] >= PR.MIN_SHARE_TRADED}
    sym_of = {a: universe[a]["binance_symbol"] for a in live
              if universe[a].get("binance_symbol")}
    if len(sym_of) < MIN_ASSETS:
        note(why, "живых и ликвидных имён меньше пола")
        return None
    raw = S.load(con, sorted(sym_of.values()), t0, t1, step=STEP,
                 interval="1m")
    by_asset = {a: raw[s] for a, s in sym_of.items() if s in raw}
    if len(by_asset) < MIN_ASSETS:
        note(why, "хранилище вернуло меньше имён, чем пол сечения")
        return None
    grid, cols, PX = FA.price_grid(by_asset, STEP, ms(t0), ms(t1))
    i_t = int(np.searchsorted(grid, ms(at)))
    i_form = 0
    if i_t - i_form < FORM_DAYS * BARS_PER_DAY // 2:
        note(why, "баров до даты меньше половины окна оценки β")
        return None
    # Наблюдения В ДЕНЬ РЕШЕНИЯ обязаны быть. Без этой проверки книга
    # записывает решение на дату, до которой данные не дошли: сигнал
    # кончается раньше на сутки, цены входа не существует, а запись
    # выглядит сегодняшней и честной. Живой прогон так и сделал —
    # решение на 27 августа при крае хранилища 26-го.
    # Нужен именно бар С МЕТКОЙ `at`: последняя доходность сигнала —
    # переход `PX[i_t − 1] → PX[i_t]` (конвенция R2), и без него окно
    # сигнала короче объявленного на сутки.
    have = (int(np.isfinite(PX[i_t]).sum()) if i_t < len(PX) else 0)
    if have < MIN_ASSETS:
        note(why, "нет наблюдений в день решения")
        return None

    Rm = FA.log_returns(PX)
    # Волна и β — ядром R2, не своей сборкой: формула остатка в
    # проекте одна, и вторая копия однажды разошлась бы (уроки
    # nulls.py в F3 и загрузчика funding).
    FACT = CS.build_factors(Rm, cols, of_group, MODEL)
    need = int(FA.MIN_COVERAGE * (i_t - i_form))
    (f0, f1), _, _ = RS.window_bounds(i_form, i_t, len(Rm), 1, 1,
                                      BARS_PER_DAY)
    B = CS.fit_window(Rm[f0:f1], FACT[f0:f1], need)
    fitted = np.isfinite(B).all(axis=1)
    E = RS.residual_matrix(Rm, FACT, B)

    _, (s0, s1), _ = RS.window_bounds(i_form, i_t, len(Rm), K_DAYS, 1,
                                      BARS_PER_DAY)
    e, _ = RS.accumulate_resid(E, s0, s1)
    sig = np.where(fitted, -e, np.nan)

    fwd = bars = None
    if forward:
        _, _, (w0, w1) = RS.window_bounds(i_form, i_t, len(Rm), 1,
                                          H_DAYS, BARS_PER_DAY)
        # Нога, чей ряд оборвался внутри окна, считается по имеющимся
        # барам: на бирже позиция дожила бы до последнего бара, а не
        # исчезла. Это исправление robust.py — выпадение умерших имён
        # стоило зонду 44 б.п./мес.
        acc, nb = RS.accumulate_resid(E, w0, w1)
        fwd = np.where(fitted & (nb > 0), acc, np.nan)
        # Число баров и ОБРЫВ РЯДА — разные вещи, и путать их нельзя.
        # Пропуски есть почти у каждого имени (бар без сделок — не
        # наблюдение), поэтому «баров меньше полного месяца» верно для
        # 82 % ног и делистингом не является. Обрыв — это когда
        # ПОСЛЕДНИЙ бар с наблюдением стоит заметно раньше конца окна.
        win = np.isfinite(E[w0:w1])
        idx = np.where(win, np.arange(w1 - w0)[:, None], -1)
        last = idx.max(axis=0)
        bars = np.vstack([nb, last])
    return cols, B[:, 0], sig, fwd, bars, len(cols)


def pick(names, beta, sig, width=WIDTH):
    """Дециль по сигналу: веса, Σ|w| = 1, ноги равновзвешены внутри."""
    m = np.isfinite(sig)
    n = int(m.sum())
    k = int(n * width)
    if k < 1:
        return None
    orig = np.flatnonzero(m)
    order = np.argsort(sig[m], kind="mergesort")
    lo, hi = orig[order[:k]], orig[order[-k:]]
    legs = []
    for i in hi:
        legs.append({"sym": names[i], "w": round(0.5 / k, 8),
                     "beta": round(float(beta[i]), 6),
                     "sig": round(float(sig[i]), 8)})
    for i in lo:
        legs.append({"sym": names[i], "w": round(-0.5 / k, 8),
                     "beta": round(float(beta[i]), 6),
                     "sig": round(float(sig[i]), 8)})
    return legs


def decide(con, at, liq, universe, of_group, why=None):
    """Решение даты `at`. Данных после `at` не касается вовсе."""
    got = build(con, at, liq, universe, of_group, forward=False, why=why)
    if got is None:
        return None
    names, beta, sig, _f, _b, n = got
    legs = pick(names, beta, sig)
    if legs is None:
        note(why, "дециль вырождается")
        return None
    return {"at": at, "written_at": round(time.time(), 1),
            "elapsed": round(max(0.0, (time.time() - ms(at) / 1000.0)
                                 / (H_DAYS * 86400.0)), 4),
            "rules": RULES, "k": K_DAYS, "h": H_DAYS,
            "width": WIDTH, "model": MODEL, "assets": n,
            "legs": legs}


def resolve(con, rec, liq, universe, of_group, funding=None):
    """Разбор транша `rec`: исход по ногам, издержки, funding, нетто."""
    at = rec["at"]
    got = build(con, at, liq, universe, of_group, forward=True)
    if got is None:
        return None
    names, beta, _sig, fwd, bars, _n = got
    idx = {s: i for i, s in enumerate(names)}
    full = H_DAYS * BARS_PER_DAY
    # Обрывом считается ряд, чей последний бар отстоит от конца окна
    # больше чем на сутки: суточный допуск отделяет делистинг от
    # обычной вечерней дыры тонкого имени.
    cut = full - BARS_PER_DAY
    legs, gross, missing = [], 0.0, 0.0
    for lg in rec["legs"]:
        i = idx.get(lg["sym"])
        if i is None or not np.isfinite(fwd[i]):
            missing += abs(lg["w"])
            legs.append({"sym": lg["sym"], "w": lg["w"],
                         "resid_bp": None, "bars": 0, "last_bar": None,
                         "truncated": None})
            continue
        r = float(fwd[i]) * 1e4
        gross += lg["w"] * r
        nb, last = int(bars[0, i]), int(bars[1, i])
        legs.append({"sym": lg["sym"], "w": lg["w"],
                     "resid_bp": round(r, 2), "bars": nb,
                     "last_bar": last,
                     "coverage": round(nb / full, 3),
                     "truncated": bool(last < cut),
                     "beta_now": round(float(beta[i]), 6)})
    fund = None
    if funding:
        t0, t1 = FS.ms(at), FS.ms(shift(at, H_DAYS))
        f, un = 0.0, 0.0
        for lg in rec["legs"]:
            acc = FS.accrued(funding, lg["sym"], t0, t1)
            if acc is None:
                un += abs(lg["w"])
                continue
            f += lg["w"] * acc * 1e4
        fund = {"bp": round(f, 2), "uncovered": round(un, 4)}
    net = gross - COST_BP - (fund["bp"] if fund else 0.0)
    return {"at": at, "resolved_at": round(time.time(), 1),
            "rules": rec.get("rules", RULES),
            "gross_bp": round(gross, 2), "cost_bp": COST_BP,
            "funding_bp": (fund["bp"] if fund else None),
            "funding_uncovered": (fund["uncovered"] if fund else None),
            "net_bp": round(net, 2),
            "missing_weight": round(missing, 4),
            "truncated_legs": sum(1 for l in legs if l.get("truncated")),
            "coverage_median": round(float(np.median(
                [l["coverage"] for l in legs
                 if l.get("coverage") is not None])), 3)
            if any(l.get("coverage") is not None for l in legs) else None,
            "legs": legs}


def ahead(rec):
    """Записано ли решение ВПЕРЁД, до начала форвардного окна."""
    w = rec.get("written_at")
    if w is None:
        return False
    return w <= ms(rec["at"]) / 1000.0 + AHEAD_TOL_SEC


def catchup(con, liq, universe, of_group, funding, start=START,
            end=None, log=print):
    """Досчитать всё, чего нет в журнале: решения и созревшие разборы.

    Идемпотентно: повторный прогон ничего не задваивает и не
    переписывает — журнал append-only.
    """
    end = end or today()
    have_d = {r["at"] for r in read_jsonl(DEC)}
    have_r = {r["at"] for r in read_jsonl(RES)}
    made_d = made_r = 0
    why = {}
    d = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while d <= last:
        at = d.isoformat()
        d += timedelta(days=1)
        if at not in have_d:
            rec = decide(con, at, liq, universe, of_group, why=why)
            if rec:
                append_jsonl(DEC, rec)
                have_d.add(at)
                made_d += 1
                log(f"  решение {at}: ног {len(rec['legs'])}, "
                    f"универсум {rec['assets']}")
    for rec in read_jsonl(DEC):
        at = rec["at"]
        if at in have_r or shift(at, H_DAYS) > end:
            continue
        got = resolve(con, rec, liq, universe, of_group, funding)
        if got:
            append_jsonl(RES, got)
            made_r += 1
            log(f"  разбор {at}: нетто {got['net_bp']:+.1f} б.п.")
    # Причины отказа печатаются ВСЕГДА, когда они были, а не только
    # при полном нуле: первый диагностический прогон записал 105
    # решений и молча оборвался на 2026-07-14, потому что счётчики
    # показывались лишь при нулевом итоге. Частичный отказ так же
    # неотличим от тишины, как полный.
    if why:
        first, last_p, n_p = storage_span()
        log(f"  отказов при отборе дат: {sum(why.values())}. "
            f"Хранилище A2: {n_p} партиций, {first} … {last_p}; "
            f"просили {start} … {end}")
        for r, c in sorted(why.items(), key=lambda x: -x[1]):
            log(f"  причина — {r}: {c}")
        if last_p and start[:7] > last_p:
            log("  край хранилища РАНЬШЕ запрошенных дат: книга "
                "считается по A2, а он снимок и сам не пополняется")
    return made_d, made_r


def newey_west_t(vals, lag):
    """t с поправкой Ньюи–Уэста. Общая с `probe_monthly/robust.py`."""
    sys.path.insert(0, os.path.join(RESEARCH, "probe_monthly"))
    import robust as RB
    return RB.newey_west_t(vals, lag)


def summarise(decisions, resolutions):
    """Свод: честное и восстановленное — ОТДЕЛЬНО, всегда."""
    by_at = {r["at"]: r for r in decisions}
    groups = {"ahead": [], "backfilled": []}
    for res in resolutions:
        dec = by_at.get(res["at"])
        if dec is None:
            continue
        res = dict(res, elapsed=dec.get("elapsed"))
        groups["ahead" if ahead(dec) else "backfilled"].append(res)
    out = {}
    for name, rows in groups.items():
        if not rows:
            out[name] = {"tranches": 0}
            continue
        rows = sorted(rows, key=lambda r: r["at"])
        nets = [r["net_bp"] for r in rows]
        gross = [r["gross_bp"] for r in rows]
        indep = [r["net_bp"] for i, r in enumerate(rows)
                 if i % H_DAYS == 0]
        m, t_, n = RS.tstat(nets)
        mi, ti, ni = RS.tstat(indep)
        _, _, nw, _ = newey_west_t(nets, lag=H_DAYS - 1)
        fund = [r["funding_bp"] for r in rows
                if r.get("funding_bp") is not None]
        out[name] = {
            "tranches": len(rows),
            "from": rows[0]["at"], "to": rows[-1]["at"],
            "gross_mean_bp": round(float(np.mean(gross)), 1),
            "net_mean_bp": round(m, 1),
            "net_median_bp": round(float(np.median(nets)), 1),
            "net_pos_share": round(float(np.mean(np.array(nets) > 0)), 3),
            "t_naive": round(t_, 2) if t_ is not None else None,
            "t_nw": round(nw, 2) if nw is not None else None,
            "independent": ni,
            "t_independent": round(ti, 2) if ti is not None else None,
            "net_mean_independent_bp": (round(mi, 1) if mi is not None
                                        else None),
            "funding_mean_bp": (round(float(np.mean(fund)), 1)
                                if fund else None),
            "truncated_legs_total": sum(r.get("truncated_legs", 0)
                                        for r in rows),
            "elapsed_median": (round(float(np.median(
                [r["elapsed"] for r in rows
                 if r.get("elapsed") is not None])), 4)
                if any(r.get("elapsed") is not None for r in rows)
                else None),
            "coverage_median": (round(float(np.median(
                [r["coverage_median"] for r in rows
                 if r.get("coverage_median") is not None])), 3)
                if any(r.get("coverage_median") is not None
                       for r in rows) else None),
        }
    return out


def verdict_phrase(sm):
    """Фраза выводится ИЗ чисел, и честная группа названа первой."""
    a = sm.get("ahead", {})
    b = sm.get("backfilled", {})
    if not a.get("tranches"):
        n = b.get("tranches", 0)
        return (f"настоящих наблюдений пока НЕТ: записано вперёд 0 "
                f"траншей, восстановлено задним числом {n} — кривая "
                f"восстановленной части есть бэктест, а не трек")
    need = 3.0
    if a.get("t_independent") is not None and a["t_independent"] >= need:
        return (f"записано вперёд {a['tranches']} траншей, нетто "
                f"{a['net_mean_bp']:+.1f} б.п.; t по независимым "
                f"{a['t_independent']:.2f} — порог {need:.0f} взят")
    return (f"записано вперёд {a['tranches']} траншей "
            f"({a['from']} … {a['to']}), нетто {a['net_mean_bp']:+.1f} "
            f"б.п. в среднем, независимых сечений {a['independent']} — "
            f"копим календарь, вердикта нет")


def report(art, path):
    a = art
    L = ["# Бумажная месячная книга\n",
         f"Прогон: {a['run_at']}. Одна конструкция, объявленная до "
         f"первого прогона: формация {K_DAYS} дн, удержание {H_DAYS} "
         f"дн, дециль, рыночная волна, β на {FORM_DAYS} днях, издержки "
         f"транша {COST_BP:.0f} б.п. Сетки нет — книга проверяет одну "
         "конструкцию, а не выбирает лучшую.\n",
         f"**{a['verdict']}**\n",
         "## Честное и восстановленное\n",
         "Решение, записанное в журнал ДО начала форвардного окна, — "
         "настоящее наблюдение. Досчитанное задним числом — бэктест, "
         "не хуже и не лучше зонда. Группы не смешиваются никогда: "
         "иначе через полгода кривая выглядела бы треком, будучи "
         "наполовину пересчётом.\n",
         "| группа | траншей | период | брутто | нетто ср. | нетто мед. "
         "| >0 | t наив. | t Ньюи–Уэста | независ. | t независ. | "
         "funding | оборв. ног | покрытие |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, nm in (("ahead", "записано вперёд"),
                    ("backfilled", "восстановлено")):
        s = a["summary"].get(key, {})
        if not s.get("tranches"):
            L.append(f"| {nm} | 0 | — | — | — | — | — | — | — | — | — "
                     f"| — | — | — |")
            continue
        L.append(
            f"| {nm} | {s['tranches']} | {s['from']} … {s['to']} | "
            f"{s['gross_mean_bp']:+.1f} | {s['net_mean_bp']:+.1f} | "
            f"{s['net_median_bp']:+.1f} | {s['net_pos_share']:.2f} | "
            f"{s['t_naive']} | {s['t_nw']} | {s['independent']} | "
            f"{s['t_independent']} | {s['funding_mean_bp']} | "
            f"{s['truncated_legs_total']} | {s.get('coverage_median')} |")
    a_el = a["summary"].get("ahead", {}).get("elapsed_median")
    L += ["",
          "**Задержка записи структурная.** Суточный архив Binance за "
          "день `D` выходит после конца суток `D`, а решению на дату "
          "`D` нужен бар с меткой `D`: раньше `D + 1` его посчитать "
          "нечем ни при каком расписании. К моменту записи прожита "
          f"доля форварда — медиана честной группы "
          f"{a_el if a_el is not None else '—'} (одна тридцатая — это "
          "0.033). Сигнал по-прежнему кончается на `D`; снять задержку "
          "может только другой источник свежих баров.\n",
          "«Оборв. ног» — ноги, чей последний бар отстоит от "
          "конца окна больше чем на сутки (делистинг); «покрытие» — "
          "медианная доля часов с наблюдением. Пропуски есть почти у "
          "каждого имени, поэтому считать обрывом «баров меньше "
          "полного месяца» нельзя: так помечались бы 82 % ног.\n",
          "Транши перекрываются (каждый день открывается новый), "
          "поэтому наивный t завышен по построению; честные меры — "
          "по Ньюи–Уэсту и по независимым (каждый 30-й транш). "
          "Замер `robust.py` намерил, что на месячных окнах перекрытие "
          "раздувает t ровно втрое.\n",
          "## Чем книга отличается от зонда\n",
          "- **исход считается ОДНОЙ β**, оценённой в момент решения и "
          "неизменной 30 дней — так, как торговали бы; зонд собирал "
          "месяц из трёх 10-дневных кирпичей, каждый по своей β, и "
          "записал это оговоркой, которую не мог измерить. Расхождение "
          "восстановленной части книги с числами зонда и есть цена "
          "этой оговорки;",
          "- **делистнутая нога держится до последнего бара** "
          "(исправление robust.py: выпадение умерших стоило зонду 44 "
          "б.п./мес);",
          "- **транши не сальдируются** между собой: оборот 2.0 на "
          "транш. Пересечение составов удешевило бы исполнение, но это "
          "оптимизация, а не свойство сигнала.\n",
          "## Что записано в журнале\n",
          f"- решений: {a['decisions']}, разборов: {a['resolutions']}",
          f"- журнал: `{os.path.relpath(DEC, RESEARCH)}` и "
          f"`{os.path.relpath(RES, RESEARCH)}`, append-only, дедуп по "
          f"дате, версия правил {RULES}\n",
          "## Чего книга НЕ доказывает\n",
          "- восстановленная часть — тот же бэктест, что зонд: её "
          "числа не являются подтверждением;",
          "- бумажная запись не проверяет исполнение: проскальзывание "
          "и ликвидность дециля здесь не моделируются вовсе;",
          "- порог для честной группы объявлен: t по независимым "
          "сечениям ≥ 3. При 12 независимых наблюдениях в год это "
          "годы — и это ровно то, что книга покупает временем."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=None)
    ap.add_argument("--catchup", action="store_true")
    ap.add_argument("--archive-journal", default="",
                    help="отставить журнал в архив с указанной причиной")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="30d")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t_start = time.time()

    if a.archive_journal:
        moved = archive_journal(a.archive_journal, a.out)
        print(f"журнал отставлен: {moved or 'нечего отставлять'}")

    if a.catchup or not a.report:
        liq, universe = PR.load_liquidity(a.interval)
        funding = FS.load_funding(os.path.join(A1, "funding"), universe,
                                  set(universe)) or {}
        con = S.connect()
        print(f"универсум {len(universe)}, рядов funding {len(funding)}")
        md, mr = catchup(con, liq, universe, None, funding,
                         start=a.start, end=a.end)
        print(f"новых решений {md}, новых разборов {mr}")

    dec, res = read_jsonl(DEC), read_jsonl(RES)
    sm = summarise(dec, res)
    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "rules": RULES, "k": K_DAYS, "h": H_DAYS, "width": WIDTH,
        "cost_bp": COST_BP,
        "decisions": len(dec), "resolutions": len(res),
        "summary": sm, "verdict": verdict_phrase(sm),
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    p = os.path.join(a.out, f"PAPER-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"PAPER-{a.tag}.md"))
    print(f"готово: {p} ({art['took_min']} мин)")
    print(f"  {art['verdict']}")
    if not a.no_publish:
        R.publish(f"бумажная месячная книга ({a.tag})")


if __name__ == "__main__":
    main()
