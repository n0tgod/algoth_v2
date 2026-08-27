#!/usr/bin/env python3
"""Зонд первых дней жизни инструмента (листинги).

Выбор владельца (№3 карты направлений). Правило «365 дней истории»
систематически вырезало первые дни жизни каждого инструмента из всех
семи гипотез — там, где волатильность ×2.9 (замер A2), экстремальный
funding и сотни событий. Отсутствие проверки не есть опровержение:
что там за эффект (распад хайпа, дрейф, funding-перекос) — честно
неизвестно, это и есть предмет зонда.

Это зонд, не гипотеза: порогов и вердикта нет, пространство объявлено
до прогона, решение за владельцем. Событийная конструкция: измеримость
покупается ЧИСЛОМ событий (847 листингов с 2022), а не годами.

Мера
----
Событие — дата листинга `listed` из справочника универсума (первый
день ряда Binance, начало `intervals[0]` — начало после дыры листингом
не является). Вход — по ЗАКРЫТИЮ дня `listed + d` (задержка d вырезает
листинговый день: купить по цене первого бара нельзя); горизонт h дней.
Величина — доходность новичка МИНУС равновзвешенное среднее той же
доходности по зрелым именам (возраст ≥ 365 дней) за то же окно —
одновременная кросс-секция, иначе откроем «рынок рос». Контроль
средним, не медианой (Z1: медиана — статистика, а не портфель).

Правила меры:
- новичок, ДЕЛИСТНУТЫЙ внутри горизонта, считается до последнего бара
  (принудительный выход — часть эффекта; вырезать его значило бы
  вырезать худшие исходы), контроль берётся за то же фактическое окно;
  доля оборванных печатается;
- событие у края хранилища (форвард упирается в конец данных) — не
  измерено, а не ноль;
- день без закрытия (дыра, бар без сделок) — пропуск события в ячейке;
- не-крипто исключены (у них календарная компонента и свои ставки).

Свод — по событиям И по когортам (месяц листинга — один голос):
листинги идут волнами, и 30 имён одной волны — не 30 наблюдений.
Медиана И среднее обязательны обе (хвосты новичков дикие).

Нуль — псевдо-события: случайные пары (зрелое имя, дата), той же
численности, тем же кодом. Ожидание нуля ≈ 0 по построению; его дело —
поймать дефект конвейера (проект дважды печатал нулевой отчёт там, где
была сломана загрузка).

Рядом — funding новичков по рядам площадки исполнения: средняя
суточная ставка в окнах [0, 7) и [7, 30) дней от первого начисления,
квартили распределения и доля отрицательных (толпа в шорте).

Запуск (на VPS, где хранилище A2 и ряды funding):

    python3 research/probe_listings/probe.py --tag 1d
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta, datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
sys.path.insert(0, RESEARCH)

import run_d1 as R                                        # noqa: E402
from common import universe_filter as UF                  # noqa: E402
from common import funding_series as FS                   # noqa: E402

# --- объявлено до прогона ---------------------------------------------
DELAYS = (1, 3, 7)           # вход по закрытию дня listed + d
HORIZONS = (7, 30, 90)       # удержание, дни
MAIN_CELL = "d1_h30"         # самый ранний реализуемый вход, месячный
#                              горизонт — объявлено до прогона
MATURE_AGE = 365             # контрольная кросс-секция: возраст ≥ 365
MIN_MATURE = 30              # тоньше — контроля нет, событие не измерено
MAIN_FROM = "2022-01-01"     # вердиктовая часть: площадка исполнения
#                              раньше пуста; ранние годы — диагностика
SEEDS = (1, 2, 3, 4, 5)
FUND_WINS = ((0, 7), (7, 30))
T_START, T_END = "2020-01-01", "2026-07-01"


def load_universe(path=None):
    p = path or os.path.join(A1, "universe.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["assets"]


def crypto_assets(universe):
    """Активы-крипто с символом Binance и датой листинга."""
    ref = UF.non_crypto_set()
    out = {}
    for a, v in universe.items():
        s = v.get("bybit_symbol") or v.get("binance_symbol")
        if s and UF.is_non_crypto(s, ref):
            continue
        if v.get("binance_symbol") and v.get("listed"):
            out[a] = v
    return out


def day_index(d0, day):
    return (date.fromisoformat(day) - date.fromisoformat(d0)).days


def build_matrix(con, symbols, t0=T_START, t1=T_END):
    """Матрица дневных закрытий `[день × символ]` из хранилища A2.

    Закрытие дня — последний бар СО СДЕЛКАМИ (защита series.load от
    замороженных рядов); день без сделок — NaN, пропуск.
    """
    import series as S
    raw = S.load(con, sorted(symbols), t0, t1, step="1d", interval="1m")
    n_days = day_index(t0, t1)
    syms = sorted(raw)
    M = np.full((n_days, len(syms)), np.nan)
    t0_ms = int(np.datetime64(t0 + "T00:00:00", "ms").astype("int64"))
    for j, s in enumerate(syms):
        t, c = raw[s]
        idx = ((t - t0_ms) // 86_400_000).astype(np.int64)
        keep = (idx >= 0) & (idx < n_days)
        M[idx[keep], j] = c[keep]
    return syms, M


def measure_events(M, col_of, ages, events, d, h, counters, end_idx):
    """Записи ячейки (d, h): превышение новичка над зрелой кросс-секцией.

    `ages[i, j]` — возраст символа j в день i (дни от листинга, может
    быть отрицательным). `events` — [(asset, symbol, listed_iso)].
    """
    out = []
    for asset, sym, listed in events:
        j = col_of.get(sym)
        if j is None:
            counters["нет ряда в хранилище"] += 1
            continue
        i0 = events_entry_index(M, j, listed, d)
        if i0 is None:
            counters["нет цены входа"] += 1
            continue
        i_want = i0 + h
        if i_want >= end_idx:
            counters["форвард упирается в край данных"] += 1
            continue
        # выход: цена дня i_want; ряд оборвался раньше — последний бар
        col = M[:, j]
        if np.isfinite(col[i_want]):
            i1, truncated = i_want, False
        else:
            fin = np.flatnonzero(np.isfinite(col[i0 + 1:i_want + 1]))
            if len(fin) == 0:
                counters["ряд оборван сразу после входа"] += 1
                continue
            i1, truncated = i0 + 1 + int(fin[-1]), True
        r_new = col[i1] / col[i0] - 1.0
        mature = (ages[i0] >= MATURE_AGE) & np.isfinite(M[i0]) \
            & np.isfinite(M[i1])
        mature[j] = False
        if int(mature.sum()) < MIN_MATURE:
            counters["контрольная база тоньше пола"] += 1
            continue
        r_base = float(np.mean(M[i1, mature] / M[i0, mature] - 1.0))
        out.append({
            "asset": asset, "listed": listed,
            "month": listed[:7], "year": listed[:4],
            "excess_bp": (r_new - r_base) * 1e4,
            "raw_bp": r_new * 1e4, "base_bp": r_base * 1e4,
            "truncated": truncated,
        })
    return out


def events_entry_index(M, j, listed, d):
    """Индекс дня входа: закрытие дня `listed + d`, без подглядывания.

    Дня без закрытия достаточно для пропуска: взять ближайший
    следующий значило бы молча удлинить задержку."""
    i = day_index(T_START, listed) + d
    if i < 0 or i >= len(M) or not np.isfinite(M[i, j]):
        return None
    return i


def summarise(records):
    """Свод по событиям и по когортам (месяц листинга — один голос)."""
    if not records:
        return None
    ev = np.array([r["excess_bp"] for r in records])
    by_month = {}
    for r in records:
        by_month.setdefault(r["month"], []).append(r["excess_bp"])
    per = [float(np.median(v)) for v in by_month.values()]
    return {
        "events": len(records),
        "truncated_share": round(float(np.mean(
            [r["truncated"] for r in records])), 3),
        "ev_median_bp": round(float(np.median(ev)), 1),
        "ev_mean_bp": round(float(np.mean(ev)), 1),
        "ev_pos_share": round(float(np.mean(ev > 0)), 3),
        "cohorts": len(per),
        "coh_median_bp": round(float(np.median(per)), 1),
        "coh_mean_bp": round(float(np.mean(per)), 1),
        "coh_pos_share": round(float(np.mean(np.array(per) > 0)), 3),
    }


def by_year(records):
    out = {}
    for r in records:
        out.setdefault(r["year"], []).append(r["excess_bp"])
    return {y: {"n": len(v),
                "median_bp": round(float(np.median(v)), 1),
                "mean_bp": round(float(np.mean(v)), 1)}
            for y, v in sorted(out.items())}


def null_events(M, col_of, ages, syms, n_events, seed, end_idx, d, h):
    """Псевдо-события: случайные (зрелое имя, дата), той же численности.

    Дата подбирается так, чтобы у пары был и вход, и полный форвард в
    зрелой жизни имени — нуль меряет конвейер, а не край данных."""
    rng = np.random.default_rng([seed, 104_729])
    lo, hi = MATURE_AGE + d + 1, end_idx - h - d - 1
    if hi <= lo:
        return []
    out = []
    tries = 0
    while len(out) < n_events and tries < n_events * 50:
        tries += 1
        j = int(rng.integers(0, len(syms)))
        i = int(rng.integers(lo, hi))
        if ages[i][j] < MATURE_AGE + d:
            continue
        if not np.isfinite(M[i, j]):
            continue
        listed = (date.fromisoformat(T_START)
                  + timedelta(days=i - d)).isoformat()
        out.append(("null", syms[j], listed))
    return out


def funding_newborns(funding, events):
    """Средняя суточная ставка новичка в окнах от ПЕРВОГО начисления.

    Ряда нет — событие в funding-свод не входит (не ноль)."""
    wins = {w: [] for w in FUND_WINS}
    covered = 0
    for asset, _sym, _listed in events:
        v = funding.get(asset)
        if v is None or len(v[0]) == 0:
            continue
        covered += 1
        t, r = v
        t0 = t[0]
        for a, b in FUND_WINS:
            i0 = int(np.searchsorted(t, t0 + a * 86_400_000, "left"))
            i1 = int(np.searchsorted(t, t0 + b * 86_400_000, "left"))
            if i1 > i0:
                wins[(a, b)].append(float(r[i0:i1].sum()) / (b - a) * 1e4)
    out = {"covered": covered}
    for w, vals in wins.items():
        if not vals:
            continue
        v = np.array(vals)
        out[f"d{w[0]}_{w[1]}"] = {
            "n": len(v),
            "median_bp_day": round(float(np.median(v)), 2),
            "q25": round(float(np.percentile(v, 25)), 2),
            "q75": round(float(np.percentile(v, 75)), 2),
            "neg_share": round(float(np.mean(v < 0)), 3),
        }
    return out


def verdict_phrase(cell):
    """Фраза выводится ИЗ чисел главной ячейки (урок Z2)."""
    if cell is None:
        return "главная ячейка не измерена — фразы нет"
    med, mean = cell["coh_median_bp"], cell["coh_mean_bp"]
    if med * mean > 0:
        word = "ОТСТАЁТ от рынка" if med < 0 else "ОБГОНЯЕТ рынок"
        return (f"новичок в первый месяц {word}: медиана когорт "
                f"{med:+.0f} б.п., среднее {mean:+.0f} — знак согласован "
                f"обеими мерами")
    return (f"знак не согласован: медиана когорт {med:+.0f} б.п. при "
            f"среднем {mean:+.0f} — расхождение мер есть подпись "
            f"хвоста, направления нет")


def report(art, path):
    a = art
    x = a.get("extras", {})
    L = ["# Зонд: первые дни жизни инструмента\n",
         f"Прогон: {a['run_at']}. Событие A (вердиктовое) — РОЖДЕНИЕ "
         "ряда Binance, взятое из самих данных (первый день с ценой; "
         "поле `listed` справочника — дата листинга Bybit и датой "
         f"рождения не является: месяц расходится у "
         f"{x.get('born_vs_listed_month_mismatch', '—')} имён из "
         f"{x.get('events_born', '—')}). События {a['main_from']}+ "
         "(ранние годы — диагностика); вход по закрытию дня "
         "`рождение + d`, превышение над равновзвешенной кросс-секцией "
         "зрелых (возраст ≥ 365 дн ПО ДАННЫМ) за то же окно. Зонд, не "
         "гипотеза: порогов нет, решение за владельцем.\n",
         f"**{a['verdict']}**\n",
         "## Сетка (события с " + a["main_from"] + ")\n",
         "| d | h | событий | оборв. | медиана (соб.) | среднее (соб.) "
         "| >0 | когорт | медиана (ког.) | среднее (ког.) | >0 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in DELAYS:
        for h in HORIZONS:
            c = a["cells"].get(f"d{d}_h{h}")
            if c is None:
                L.append(f"| {d} | {h} | — | — | — | — | — | — | — | "
                         f"— | — |")
                continue
            mark = " **⟵**" if f"d{d}_h{h}" == MAIN_CELL else ""
            L.append(
                f"| {d} | {h} | {c['events']} | "
                f"{c['truncated_share']:.2f} | {c['ev_median_bp']:+.0f} "
                f"| {c['ev_mean_bp']:+.0f} | {c['ev_pos_share']:.2f} | "
                f"{c['cohorts']} | {c['coh_median_bp']:+.0f} | "
                f"{c['coh_mean_bp']:+.0f} | {c['coh_pos_share']:.2f}"
                f"{mark} |")
    L += ["", "Превышение в б.п. за период; «оборв.» — доля событий, "
          "где ряд кончился раньше горизонта (делистинг: считаны до "
          "последнего бара, контроль за то же окно). Когорта — месяц "
          "листинга, один голос.\n",
          "## Нуль: псевдо-события на зрелых именах "
          f"({len(SEEDS)} зёрен, главная ячейка)\n"]
    nz = a.get("null")
    if nz:
        L.append(f"медиана когорт по {nz['seeds']} зёрнам: среднее "
                 f"{nz['coh_median_mean']:+.1f} б.п., наибольшая по "
                 f"модулю {nz['coh_median_absmax']:+.1f}; у прогона "
                 f"{a['cells'][MAIN_CELL]['coh_median_bp']:+.1f}")
    bc = x.get("bybit_cell")
    L += ["", "## Событие B: листинг Bybit у зрелого на Binance имени\n",
          "Другое событие, не рождение: инструмент уже торгуется на "
          "Binance ≥ 30 дней, и появляется перп площадки исполнения "
          "(приток шортовой площадки). Геометрия главной ячейки "
          "(d = 1, h = 30).\n"]
    if bc:
        L.append(f"- событий {bc['events']}, когорт {bc['cohorts']}: "
                 f"медиана (соб.) {bc['ev_median_bp']:+.0f}, среднее "
                 f"{bc['ev_mean_bp']:+.0f}; медиана (ког.) "
                 f"**{bc['coh_median_bp']:+.0f}**, среднее "
                 f"**{bc['coh_mean_bp']:+.0f} б.п.**, доля когорт > 0 "
                 f"{bc['coh_pos_share']:.2f}")
    else:
        L.append("- не измерено (событий нет либо база тоньше пола)")
    L += ["", "## По годам листинга (главная ячейка, диагностика)\n",
          "| год | n | медиана | среднее |", "|---|---|---|---|"]
    for y, v in a.get("years", {}).items():
        L.append(f"| {y} | {v['n']} | {v['median_bp']:+.0f} | "
                 f"{v['mean_bp']:+.0f} |")
    L += ["", "## Funding новичков (суточная ставка, б.п./сутки)\n"]
    f = a.get("funding") or {}
    L.append(f"рядов покрыто: {f.get('covered', 0)}\n")
    L += ["| окно, дни | n | медиана | q25 | q75 | доля отрицательных |",
          "|---|---|---|---|---|---|"]
    for w in FUND_WINS:
        v = f.get(f"d{w[0]}_{w[1]}")
        if v:
            L.append(f"| {w[0]}–{w[1]} | {v['n']} | "
                     f"{v['median_bp_day']:+.2f} | {v['q25']:+.2f} | "
                     f"{v['q75']:+.2f} | {v['neg_share']:.2f} |")
    L += ["", "Отрицательная ставка — платят шорты (толпа в шорте "
          "новичка). Справочно: медиана суточной ставки универсума "
          "≈ +0.5 б.п. (замер спеки 04).\n",
          "## Пропуски\n"]
    for kk, v in sorted(a["skipped"].items()):
        L.append(f"- {kk}: {v}")
    L += ["", "## Оговорки, не снимаемые замером\n",
          "- цены — архив Binance; событие A — рождение ряда Binance, "
          "торговать же придётся на Bybit, где перп появляется в "
          "другой день (событие B меряет ровно этот разрыв);",
          "- издержки не вычтены: круг ноги 11 б.п., с хеджем об "
          "кросс-секцию 22 — против величин таблицы это справка, а не "
          "порог;",
          "- события кластеризованы волнами листингов: свод по "
          "событиям завышает независимость, главная мера — по "
          "когортам-месяцам;",
          "- funding отсчитан от первого начисления ряда Bybit — оно "
          "может отстоять от листинга Binance на дни и недели."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def born_index(M):
    """День рождения каждого ряда — ПО ДАННЫМ: первый конечный день.

    Поле `listed` справочника — дата листинга ПЛОЩАДКИ ИСПОЛНЕНИЯ
    (Bybit), а не Binance: у 171 имени Binance торгует раньше неё, у
    135 — позже. Первый прогон зонда прочёл его как дату рождения ряда
    и измерил СМЕСЬ двух событий, а в контрольную базу пускал имена с
    завышенным возрастом. Источник правды — сама матрица.
    """
    born = np.full(M.shape[1], 10**9)
    for j in range(M.shape[1]):
        fin = np.flatnonzero(np.isfinite(M[:, j]))
        if len(fin):
            born[j] = int(fin[0])
    return born


def run(M, syms, universe, events_all, counters):
    """Вся сетка + нуль + по-годам. Вынесено ради тестов на синтетике.

    Событие A (вердиктовое) — рождение ряда Binance, взятое ИЗ ДАННЫХ
    (первый конечный день колонки). Событие B (отдельная секция) —
    листинг Bybit (`listed`) у имени, уже зрелого на Binance: это
    другое событие — приток площадки шортов, не рождение инструмента.
    """
    col_of = {s: j for j, s in enumerate(syms)}
    born = born_index(M)
    ages = np.arange(len(M))[:, None] - born[None, :]
    end_idx = len(M)

    # события A: рождение ряда по данным; дата — из матрицы
    events_born, mism = [], 0
    for asset, sym, listed in events_all:
        j = col_of.get(sym)
        if j is None or born[j] >= 10**9:
            counters["нет ряда в хранилище"] += 1
            continue
        b_iso = (date.fromisoformat(T_START)
                 + timedelta(days=int(born[j]))).isoformat()
        if b_iso[:7] != listed[:7]:
            mism += 1
        events_born.append((asset, sym, b_iso))

    # события B: листинг Bybit у зрелого на Binance имени (возраст ≥ 30)
    events_bybit = []
    for asset, sym, listed in events_all:
        j = col_of.get(sym)
        if j is None or born[j] >= 10**9:
            continue
        li = day_index(T_START, listed)
        if 0 <= li < end_idx and li - born[j] >= 30:
            events_bybit.append((asset, sym, listed))

    cells, main_records = {}, None
    for d in DELAYS:
        for h in HORIZONS:
            rec = measure_events(M, col_of, ages, events_born, d, h,
                                 counters, end_idx)
            rec_main = [r for r in rec if r["listed"] >= MAIN_FROM]
            got = summarise(rec_main)
            if got:
                cells[f"d{d}_h{h}"] = got
            if f"d{d}_h{h}" == MAIN_CELL:
                main_records = rec_main
    years = by_year(main_records) if main_records else {}

    # событие B меряется только в главной геометрии (d=1, h=30):
    # это отдельный вопрос, а не ось сетки — плодить ячейки незачем
    bybit_cell = None
    if events_bybit:
        nc = {k: 0 for k in counters}
        rec_b = [r for r in measure_events(M, col_of, ages, events_bybit,
                                           1, 30, nc, end_idx)
                 if r["listed"] >= MAIN_FROM]
        bybit_cell = summarise(rec_b)
        if bybit_cell:
            bybit_cell["skipped"] = {k: v for k, v in nc.items() if v}

    null = None
    if cells.get(MAIN_CELL):
        d = int(MAIN_CELL.split("_")[0][1:])
        h = int(MAIN_CELL.split("_")[1][1:])
        meds = []
        for s in SEEDS:
            pe = null_events(M, col_of, ages, syms,
                             cells[MAIN_CELL]["events"], s, end_idx,
                             d, h)
            nc = {k: 0 for k in counters}
            rec = measure_events(M, col_of, ages, pe, d, h, nc, end_idx)
            got = summarise(rec)
            if got:
                meds.append(got["coh_median_bp"])
        if meds:
            null = {"seeds": len(meds),
                    "coh_median_mean": round(float(np.mean(meds)), 1),
                    "coh_median_absmax": round(
                        float(max(np.abs(meds))), 1)}
    extras = {"born_vs_listed_month_mismatch": mism,
              "events_born": len(events_born),
              "events_bybit": len(events_bybit),
              "bybit_cell": bybit_cell}
    return cells, years, null, extras


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="1d")
    ap.add_argument("--universe", default=None)
    ap.add_argument("--funding-dir", default=os.path.join(A1, "funding"))
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    t_start = time.time()
    universe = load_universe(a.universe)
    cryptos = crypto_assets(universe)
    events_all = [(x, v["binance_symbol"], v["listed"])
                  for x, v in sorted(cryptos.items())]
    print(f"активов-крипто с листингом: {len(events_all)}, памяти "
          f"свободно {R.mem_available_mb():.0f} МБ")

    import series as S
    con = S.connect()
    symbols = sorted({s for _, s, _ in events_all})
    print("строю матрицу дневных закрытий")
    syms, M = build_matrix(con, symbols)
    print(f"матрица {M.shape[0]} дней × {M.shape[1]} имён")

    counters = {k: 0 for k in (
        "нет ряда в хранилище", "нет цены входа",
        "форвард упирается в край данных",
        "ряд оборван сразу после входа",
        "контрольная база тоньше пола")}
    cells, years, null, extras = run(M, syms, universe, events_all,
                                     counters)
    if not cells:
        for kk, v in sorted(counters.items()):
            print(f"  пропуск — {kk}: {v}")
        raise SystemExit("ни одной измеренной ячейки — причины выше")

    funding = FS.load_funding(a.funding_dir, universe,
                              set(cryptos)) or {}
    fund = funding_newborns(funding, events_all) if funding else None

    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "delays": list(DELAYS), "horizons": list(HORIZONS),
        "main_cell": MAIN_CELL, "main_from": MAIN_FROM,
        "mature_age": MATURE_AGE, "events_total": len(events_all),
        "extras": extras,
        "cells": cells, "years": years, "null": null,
        "funding": fund, "skipped": counters,
        "verdict": verdict_phrase(cells.get(MAIN_CELL)),
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    p = os.path.join(a.out, f"LISTINGS-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"LISTINGS-{a.tag}.md"))
    print(f"готово: {p} ({art['took_min']} мин)")
    print(f"  {art['verdict']}")
    if not a.no_publish:
        R.publish(f"зонд первых дней жизни инструмента ({a.tag})")


if __name__ == "__main__":
    main()
