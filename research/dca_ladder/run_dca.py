#!/usr/bin/env python3
"""
D1 (спека 14) — дешёвый потолок DCA-лестницы: реплей по хранилищу A2.

Отвечает на числа §8 в порядке дешевизны, каждое закрывает направление
само:

1. **Частота ликвидации на реальных разрывах** — прямой ответ на цель
   владельца «чтобы не было ликвидаций». §5-плечо даёт «редко», не
   «никогда»; сколько именно — считается на минутных (или 15m) низах,
   а не предполагается.
2. **Руина отдельно от ликвидации** — доля лестниц в имя, делистнутое
   внутри удержания (актив → 0 губит лестницу, не тронув маржу).
3. **Бьёт ли лестница наивное удержание** — контрольная рука `hold`:
   тот же капитал и плечо, вход один. Парная разность по позициям.
4. **Форма распределения** — доля зелёных, худшая, укус, просадка кривой.

Уровни рунгов — σ-СЕТКА (объявленный §4 каркас и БАЗА, против которой
структурные уровни T4 судятся нулём §8.6 отдельным проходом): рунг `i`
на `i · spacing · σ` ниже базы, σ — суточная волатильность имени на окне
оценки. Пол σ берётся из САМОГО СЕЧЕНИЯ (урок S1: обратная величина без
пола — ловушка замороженных рядов), иначе тонкий по σ инструмент получил
бы бритвенную лестницу и максимальное плечо.

Плечо ВЫВОДИТСЯ из забора §5 по тирам maintenance margin D0
(`risk_limits.json`); делистнутой ноге без тиров — дорогой плоский MMR
(§10, модальный 0.02). Ядро забора и реплея — `ladder.py`, второй копии
нет.

Запуск (VPS, store только там; отцепленно — прогон длиннее минуты):

    setsid nohup .venv/bin/python research/dca_ladder/run_dca.py \\
        --interval 1m > research/dca_ladder/out/run.log 2>&1 &

В песочнице смоук на 15m: `--interval 15m --smoke` (узкий универсум).
Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
import ladder as L                        # noqa: E402
import series as S                        # noqa: E402

# --- объявленная сетка (до прогона) ---------------------------------------
START = "2022-07-01"                      # площадка исполнения раньше пуста
STEP = "1h"                               # разрешение пути удержания
EVAL_D = 30                               # окно оценки σ, суток
HOLD_D = 20                               # окно удержания, суток (ось)
STRIDE_D = 20                             # шаг дат входа — непересекающиеся
N_RUNGS = 4                               # база + три долива вниз
SPACING_SIG = 2.0                         # рунг каждые 2 суточные σ
SURVIVE_MULT = 2.0                        # §5: ликвидация не ближе mult·d_max
WEIGHTS = [0.25, 0.25, 0.25, 0.25]        # форма лестницы (равная)
FLAT_MMR = 0.02                           # делистнутой ноге (§10 модальный)
SIG_FLOOR_Q = 0.10                        # пол σ — 10-й процентиль сечения
MIN_SECTION = 20                          # меньше имён — сечения нет
MEM_SHARE = 0.6                           # не откусывать больше у машины


def instruments_tiers():
    p = os.path.join(RESEARCH, "a1_universe", "out", "risk_limits.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def universe(smoke):
    p = os.path.join(RESEARCH, "a1_universe", "out", "universe.json")
    with open(p, encoding="utf-8") as f:
        man = json.load(f)
    syms = []
    for rec in man["assets"].values():
        if rec.get("asset_class") == "non_crypto":
            continue
        s = rec.get("bybit_symbol") or rec.get("binance_symbol")
        if s:
            syms.append(s)
    syms = sorted(set(syms))
    # Смоук берёт широкий срез намеренно: хранилище A2 — по символам Binance,
    # а универсум предпочитает bybit_symbol, поэтому доля имён с рядом в A2
    # ниже единицы (первый прогон: 14 из 40). Узкий срез не набирает
    # MIN_SECTION, и ладдерный путь не исполняется вовсе — смоук обязан быть
    # шире порога сечения, а не «первые сорок».
    return syms[:160] if smoke else syms


def read_name(con, sym, t0, t1, step, interval):
    """Ряд имени: (времена мс, закрытия, низы) по шагу, СО СДЕЛКАМИ.

    Закрытие бакета — последний бар со сделками (`trades > 0`, как в
    `series.load`: замороженная минута не подменяет закрытие). Низ бакета
    — минимум `low` среди баров со сделками: по нему ловятся и заполнение
    рунга, и пробой цены ликвидации внутри бара.
    """
    files = S.partition_files(interval, t0, t1)
    if not files:
        return None
    bucket = S.STEPS[step] or "open_time"
    flist = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    q = f"""
        WITH src AS (
            SELECT open_time, close, low
            FROM read_parquet([{flist}])
            WHERE symbol = '{sym.replace("'", "''")}'
              AND open_time >= TIMESTAMPTZ '{t0}'
              AND open_time <  TIMESTAMPTZ '{t1}'
              AND trades > 0
        )
        SELECT {bucket} AS t,
               arg_max(close, open_time) AS close,
               min(low) AS low
        FROM src GROUP BY 1 ORDER BY 1
    """
    tbl = con.execute(q).fetch_arrow_table()
    if tbl.num_rows == 0:
        return None
    t = tbl.column("t").to_numpy(zero_copy_only=False)
    t = t.astype("datetime64[ms]").astype("int64")
    c = tbl.column("close").to_numpy(zero_copy_only=False).astype(np.float64)
    lo = tbl.column("low").to_numpy(zero_copy_only=False).astype(np.float64)
    return t, c, lo


def daily_sigma(times_ms, closes):
    """σ суточных лог-доходностей ряда (доля цены)."""
    if len(closes) < 3:
        return float("nan")
    # приведём к суткам: последнее закрытие каждого календарного дня
    day = times_ms // 86_400_000
    edges = np.flatnonzero(day[1:] != day[:-1]) + 1
    ends = np.concatenate((edges, [len(closes)])) - 1
    dc = closes[ends]
    dc = dc[dc > 0]
    if len(dc) < 3:
        return float("nan")
    r = np.diff(np.log(dc))
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return float("nan")
    return float(np.std(r))


def mmr_lookup_for(tiers):
    """Функция ставки по нотионалу для имени; нет тиров — плоский §10."""
    def look(notional):
        return L.mmr_for_notional(tiers, notional, flat=FLAT_MMR)
    return look


def entry_dates(start, end_hold):
    d0 = date.fromisoformat(start)
    d1 = end_hold
    out = []
    d = d0
    while d <= d1:
        out.append(d)
        d += timedelta(days=STRIDE_D)
    return out


def mem_ok():
    avail = None
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    avail = int(ln.split()[1]) / 1024        # МБ
                    break
    except OSError:
        return True, None
    return True, avail


def slice_window(t, c, lo, ts0, ts1):
    """Кусок ряда в [ts0, ts1) миллисекунд."""
    i = np.searchsorted(t, ts0, "left")
    j = np.searchsorted(t, ts1, "left")
    return t[i:j], c[i:j], lo[i:j]


def run(interval, smoke, days_limit=None):
    t_run = time.time()
    con = S.connect()
    tiers_all = instruments_tiers()
    syms = universe(smoke)
    # конец: последняя дата входа так, чтобы окно удержания влезло в данные
    end = date(2026, 8, 26)
    dates = entry_dates(START, end - timedelta(days=HOLD_D))
    if days_limit:
        dates = dates[:days_limit]

    # читаем ряд каждого имени за всю историю один раз (партиция кладёт
    # символ отдельной row group — посимвольный запрос дёшев)
    print(f"чтение {len(syms)} имён…", file=sys.stderr, flush=True)
    series = {}
    for k, sym in enumerate(syms):
        r = read_name(con, sym, START, end.isoformat(), STEP, interval)
        if r is not None and len(r[0]) >= 5:
            series[sym] = r
        if (k + 1) % 100 == 0:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            print(f"  {k+1}/{len(syms)}  RSS {rss:.0f} МБ",
                  file=sys.stderr, flush=True)
    print(f"рядов {len(series)}", file=sys.stderr, flush=True)

    lad_pnl, hold_pnl = [], []             # парно по позициям
    liq = 0
    ruin = 0
    depth_sum = 0
    n = 0
    skipped_fence = 0
    per_day = {}                           # дата входа → сумма нетто лестницы

    day_ms = 86_400_000
    for d in dates:
        ts0 = int(np.datetime64(d.isoformat() + "T00:00:00", "ms")
                  .astype("int64"))
        ts_eval0 = ts0 - EVAL_D * day_ms
        ts_hold1 = ts0 + HOLD_D * day_ms

        # сечение: имена, живые на t0 (есть бар около t0) и с окном оценки
        sigmas, cand = {}, []
        for sym, (t, c, lo) in series.items():
            te, ce, _ = slice_window(t, c, lo, ts_eval0, ts0)
            if len(ce) < 3:
                continue
            sg = daily_sigma(te, ce)
            if not np.isfinite(sg) or sg <= 0:
                continue
            # база — первое закрытие в окне удержания (вход next-open грубо
            # — открытие бакета t0)
            th, ch, loh = slice_window(t, c, lo, ts0, ts_hold1)
            if len(ch) < 2:
                continue
            sigmas[sym] = sg
            cand.append(sym)
        if len(cand) < MIN_SECTION:
            continue
        floor = float(np.quantile(list(sigmas.values()), SIG_FLOOR_Q))
        floor = max(floor, 0.005)          # и абсолютный минимум 0.5 %

        day_net = 0.0
        for sym in cand:
            sg = max(sigmas[sym], floor)
            t, c, lo = series[sym]
            th, ch, loh = slice_window(t, c, lo, ts0, ts_hold1)
            base = float(ch[0])
            if base <= 0:
                continue
            try:
                rungs, d_max = L.sigma_rungs(base, sg, N_RUNGS, SPACING_SIG)
            except ValueError:
                continue                    # сетка глубже 100 %
            tiers = tiers_all.get(sym) or []
            look = mmr_lookup_for(tiers)
            lev = L.max_leverage(rungs, WEIGHTS, 1.0, base, d_max, look,
                                 SURVIVE_MULT)
            if lev <= 0:
                skipped_fence += 1
                continue
            # руина: ряд имени кончился внутри удержания (делистинг)
            last_ms = int(t[-1])
            is_ruin = last_ms < ts_hold1 - day_ms
            lad = L.simulate_ladder(list(ch), list(loh), rungs, WEIGHTS,
                                    1.0, lev, look(1.0 * lev))
            hold = L.simulate_hold(list(ch), list(loh), base, 1.0, lev,
                                   look(1.0 * lev))
            lad_pnl.append(lad["pnl_frac"])
            hold_pnl.append(hold["pnl_frac"])
            liq += int(lad["liquidated"])
            ruin += int(is_ruin)
            depth_sum += lad["depth"]
            day_net += lad["pnl_frac"]
            n += 1
        per_day[d.isoformat()] = day_net

    summary = measures(lad_pnl, hold_pnl, liq, ruin, depth_sum, n,
                       skipped_fence, per_day, interval, smoke,
                       time.time() - t_run)
    return summary


def measures(lad, hold, liq, ruin, depth_sum, n, skipped, per_day,
             interval, smoke, secs):
    lad = np.array(lad)
    hold = np.array(hold)
    out = {
        "interval": interval, "smoke": smoke, "positions": n,
        "secs": round(secs, 1),
        "liq_freq": (liq / n) if n else None,
        "ruin_freq": (ruin / n) if n else None,
        "avg_depth": (depth_sum / n) if n else None,
        "skipped_fence": skipped,
        "params": {"START": START, "STEP": STEP, "EVAL_D": EVAL_D,
                   "HOLD_D": HOLD_D, "N_RUNGS": N_RUNGS,
                   "SPACING_SIG": SPACING_SIG, "SURVIVE_MULT": SURVIVE_MULT,
                   "FLAT_MMR": FLAT_MMR},
    }
    if n:
        diff = lad - hold
        out["lad_median"] = float(np.median(lad))
        out["hold_median"] = float(np.median(hold))
        out["diff_median"] = float(np.median(diff))
        out["lad_beats_hold_frac"] = float(np.mean(lad > hold))
        out["green_frac"] = float(np.mean(lad > 0))
        out["worst"] = float(np.min(lad))
        # укус: |худшая| / медиана прибыльной
        win = lad[lad > 0]
        med_win = float(np.median(win)) if len(win) else float("nan")
        out["bite"] = (abs(float(np.min(lad))) / med_win
                       if med_win and med_win > 0 else None)
        # просадка кривой по дням входа
        days = sorted(per_day)
        cur = np.cumsum([per_day[d] for d in days]) if days else np.array([])
        if len(cur):
            peak = np.maximum.accumulate(cur)
            out["curve_dd"] = float(np.min(cur - peak))
    return out


def report(s):
    L1 = []
    P = L1.append
    tag = "смоук " if s["smoke"] else ""
    P(f"# D1 — потолок DCA-лестницы ({tag}{s['interval']})\n")
    P("Диагностика, не вердикт: пороги §9 судит владелец. Реплей по "
      "хранилищу A2, забор §5 по тирам D0, уровни σ-сеткой.\n")
    P(f"Позиций {s['positions']}, прогон {s['secs']} с, "
      f"отсеяно забором {s['skipped_fence']}.\n")
    if not s["positions"]:
        P("**Позиций ноль** — сечение не собралось (мало имён/истории).")
        return "\n".join(L1) + "\n"
    P("## §8.1 Ликвидация на разрывах — цель владельца числом\n")
    P(f"- **доля ликвидированных лестниц {s['liq_freq']*100:.2f} %** "
      f"(порог §9 ≤ 0.5 %)")
    P(f"- средняя глубина заполнения {s['avg_depth']:.2f} из {N_RUNGS} рунгов\n")
    P("## §8.2 Руина (делистинг внутри удержания)\n")
    P(f"- доля лестниц в делистнутое имя {s['ruin_freq']*100:.2f} % "
      f"(выше 2 % — режется фильтр 30 суток до снятия)\n")
    P("## §8.3 Бьёт ли лестница удержание\n")
    P(f"- медиана лестницы {s['lad_median']*100:+.2f} % капитала, "
      f"удержания {s['hold_median']*100:+.2f} %")
    P(f"- **парная разность медиана {s['diff_median']*100:+.2f} %**, "
      f"лестница выше удержания в {s['lad_beats_hold_frac']*100:.1f} % позиций\n")
    P("## §8.4 Форма распределения (для устойчивости)\n")
    P(f"- доля зелёных {s['green_frac']*100:.1f} % (порог §9 ≥ 55 %)")
    P(f"- худшая позиция {s['worst']*100:+.1f} % капитала")
    bite = s.get("bite")
    P(f"- укус |худшая|/медиана прибыльной "
      f"{('%.1f' % bite) if bite else '—'} (порог §9 ≤ 10)")
    if "curve_dd" in s:
        P(f"- просадка кривой по датам входа {s['curve_dd']*100:+.1f} % "
          f"(сумма долей капитала)\n")
    P("\n**Что НЕ в числах и оговорки:** нуль «структурные уровни против "
      "случайных» (§8.6) — отдельный проход; издержки посимвольной комиссии "
      "в pnl лестницы ещё не сняты (первый ответ — на брутто); вход в базу "
      "по закрытию бакета t0 — мелкий подарок на многодневном удержании; "
      "MMR делистнутой ноги плоский (§10), точный тир площадка не отдаёт. "
      "Убыль убытка от лестницы против удержания на 2022–2026 может "
      "льстить: выборка — в основном откупленные просадки.")
    return "\n".join(L1) + "\n"


def publish(name):
    subprocess.run(["tools/publish.sh", f"job: {name}"],
                   cwd=RESEARCH + "/..", check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--days-limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    s = run(a.interval, a.smoke, a.days_limit)
    tag = f"{'smoke-' if a.smoke else ''}{a.interval}"
    with open(os.path.join(OUT, f"D1-dca-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    rep = report(s)
    with open(os.path.join(OUT, f"D1-dca-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    if not a.no_publish:
        publish(f"d1-dca-{tag}")


if __name__ == "__main__":
    main()
