#!/usr/bin/env python3
"""
Зонд: зарабатывает ли набор НА ЦЕНЕ — уровневое поглощение.

**Зонд, а не гипотеза.** Ни объявленной сетки, ни порогов-вердикта.

Чем отличается от T1
--------------------

T1 спрашивал «много ли лили в окне» и цену уровня игнорировал вовсе.
Ответ был нулевой там, где мера построена: на 30 и 60 секундах
превышение над одновременной кросс-секцией −0.22 и −0.27 б.п. при круге
издержек 11, покрытие 90 и 80 %, фон 8–10 имён. Плюс потолок сверху:
лучший возможный выход внутри минуты равен 7–13 б.п., то есть короткие
горизонты мертвы по арифметике при любом сигнале.

Непроверенным остался **уровень**. Набор крупного лимитника — событие на
конкретной цене: он стоит заявкой, её выедают, он подставляет снова.
Объём, размазанный по всему ходу окна, — это активная торговля, а не
набор, и в T1 оба рода шли в одну выборку. Мера сосредоточенности —
`tape.level_filter`, безразмерная и потому сравнимая между
инструментами.

Почему фон из хранилища A2, а не из ленты
-----------------------------------------

В T1 длинные горизонты не измерялись не из-за рынка, а из-за узости
фона: защитное окно равно горизонту, и на получасе оно запрещало почти
всех соседей — покрытие падало до 3 %, фон до нуля имён. Но фон **не
обязан** приходить из ленты. Событие нужно с секундной точностью, а
форвард и фон на горизонте 5–30 минут прекрасно считаются по минутному
хранилищу A2, где лежат все 720 символов универсума и которое уже на
сервере. Фон становится сотнями имён вместо десяти, и скачивать не надо
ничего.

Три следствия этого решения, каждое существенно
-----------------------------------------------

**Вход перестал быть подарком.** В T1 он брался по закрытию секунды
обнаружения, то есть по последней цене ДО решения — купить по ней
нельзя. Здесь вход — открытие первого минутного бара, начинающегося
после события, то есть первая цена, по которой сделка возможна. То же
исправление, что `next_open` в зонде возврата.

**Форвард события и фон считаются из одного источника.** Лента — Bybit,
хранилище — Binance, и если брать форвард из ленты, а фон из хранилища,
то систематический базис между площадками войдёт в разность как эдж.
Обе величины берутся из хранилища; лента служит только метками времени.

**Соседи по ленте запрещаются, остальные семьсот — нет.** У них своё
поглощение неизвестно, потому что ленты для них не качали. При фоне из
сотен имён это загрязнение пренебрежимо, но сказать о нём надо: мера
слегка консервативна к событию, а не в его пользу.

    tools/run.sh "T2: уровень с фоном A2" research/t2_levels/probe.py \\
      --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT --start 2025-03-03 --end 2025-03-09
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from itertools import product

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "t1_tape"))
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
import data as D                                          # noqa: E402
import events as E                                        # noqa: E402
import tape as T                                          # noqa: E402

A1_OUT = os.path.join(RESEARCH, "a1_universe", "out")

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "LINKUSDT", "ARBUSDT", "AVAXUSDT", "SUIUSDT", "APTUSDT",
           "INJUSDT", "SEIUSDT", "OPUSDT", "NEARUSDT", "ATOMUSDT",
           "FILUSDT")
START = "2025-03-03"
END = "2025-03-09"

STEP_SEC = 1                      # шаг сетки ленты
WINDOWS = (60, 300)               # окно набора, секунды
VOL_MULTS = (5.0, 10.0)           # объём выше обычного, в разах
MOVE_MULT = 0.5                   # цена ушла не больше половины обычного хода
IMB = 0.3                         # перевес давящей стороны
CONCS = (0.4, 0.6)                # доля объёма в самой загруженной полосе
BANDS = 10                        # полос на ход окна
# Горизонты в минутах: короче пяти нет смысла — потолок T1 показал, что
# лучший возможный выход внутри минуты меньше круга издержек.
HORIZONS_MIN = (5, 15, 30)
EPISODE_SEC = 900                 # слипание событий в эпизоды
MIN_CROSS = 20                    # имён в фоне минимум
MIN_CROSS_SHARE = 0.1

TAKER_ROUND_BP = 11.0
MAKER_ROUND_BP = 4.0


def tape_to_store():
    """Карта: символ ленты Bybit -> символ хранилища Binance.

    Тикеры расходятся (SHIB: `SHIB1000USDT` против `1000SHIBUSDT`), и
    сопоставление по имени однажды уже дало пустой сбор в проверке Bybit.
    """
    with open(os.path.join(A1_OUT, "universe.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    out = {}
    for v in assets.values():
        if v.get("asset_class") != "crypto":
            continue
        b, n = v.get("bybit_symbol"), v.get("binance_symbol")
        if b and n:
            out[b] = n
    return out


def bg_grid(start, end, step_sec):
    """Сетка фона: от начала первых суток до конца последних."""
    t0 = int(datetime.fromisoformat(start).replace(
        tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(end).replace(
        tzinfo=timezone.utc).timestamp()) + 86_400
    return np.arange(t0, t1, step_sec, dtype=np.int64)


def detect_day(sym, day, win, mult, conc_min, side, log):
    """События уровневого набора у одного символа за сутки.

    Возвращает `(времена событий, сосредоточенность, отход от уровня)`.
    """
    tp = T.load_day(sym, day)
    if tp is None:
        return None
    t0 = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    g = T.to_grid(tp, STEP_SEC, t0=t0, t1=t0 + 86_400)
    idx, _ = T.absorption(g, win, mult, MOVE_MULT, side, IMB)
    if len(idx) == 0:
        return np.empty(0), np.empty(0), np.empty(0)
    keep, conc, lvl, away, _w = T.level_filter(tp, g, idx, win, side,
                                              BANDS)
    if len(keep) == 0:
        return np.empty(0), np.empty(0), np.empty(0)
    take = conc >= conc_min
    return g["t"][keep[take]], conc[take], away[take]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--interval", default="1m",
                    help="разрешение хранилища для фона")
    ap.add_argument("--tag", default="", help="суффикс артефактов, напр. -smoke")
    a = ap.parse_args()
    if a.tag and not a.tag.startswith("-"):
        a.tag = "-" + a.tag
    os.makedirs(OUT, exist_ok=True)
    step_sec = 60 if a.interval == "1m" else 900
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    t_start = time.time()

    def log(m):
        print(f"[{time.time() - t_start:6.0f} с] {m}", file=sys.stderr,
              flush=True)

    # Горизонт короче шага хранилища даёт НОЛЬ шагов вперёд, то есть
    # форвард, тождественно равный нулю, — и в таблице это выглядит как
    # «эффекта нет», а не как «замер невозможен». Тот же род дефекта, что
    # зашитый шаг в загрузчике цен: пустота печаталась как результат.
    horizons = [h for h in HORIZONS_MIN
                if h * 60 >= step_sec and (h * 60) % step_sec == 0]
    dropped = [h for h in HORIZONS_MIN if h not in horizons]
    if dropped:
        log(f"горизонты {dropped} мин при шаге хранилища {step_sec} с не "
            f"считаются: не кратны шагу или короче его")
    if not horizons:
        raise SystemExit(f"ни один горизонт не кратен шагу {step_sec} с")

    # 1. Фон: всё крипто-хранилище на минутной сетке за период.
    m = tape_to_store()
    uni = sorted(set(D.universe()))
    times = bg_grid(a.start, a.end, step_sec)
    log(f"фон: {len(uni)} символов хранилища, {len(times)} моментов, "
        f"шаг {step_sec} с")
    P = D.price_matrix(uni, times, interval=a.interval, log=log,
                       columns=("open", "high", "low"))
    O, HI, LO = P["open"], P["high"], P["low"]
    fill = float(np.isfinite(O).mean())
    log(f"фон заполнен на {fill:.1%}")
    if fill < 0.01:
        raise SystemExit("фон почти пуст — проверь разрешение хранилища; "
                         "пустота не является результатом")
    row_of = {s: i for i, s in enumerate(uni)}

    # 2. События из ленты.
    days = T.days_between(a.start, a.end)
    cells = list(product(WINDOWS, VOL_MULTS, CONCS,
                         ((-1, "набор под ценой"), (1, "разгрузка над ценой"))))
    ev = {k: {"row": [], "col": [], "t": [], "conc": [], "away": []}
          for k in cells}
    missing = []
    for day in days:
        log(f"  {day}")
        for sym in syms:
            store = m.get(sym)
            if store is None or store not in row_of:
                if sym not in missing:
                    missing.append(sym)
                continue
            for key in cells:
                win, mult, conc_min, (side, _) = key
                got = detect_day(sym, day, win, mult, conc_min, side, log)
                if got is None or len(got[0]) == 0:
                    continue
                te, cc, aw = got
                # Вход — открытие первого бара, начинающегося ПОСЛЕ
                # события: первая цена, по которой сделка возможна.
                col = np.searchsorted(times, te, "right")
                ok = (col < len(times) - max(horizons) * 60 // step_sec)
                d = ev[key]
                d["row"] += [row_of[store]] * int(ok.sum())
                d["col"] += list(col[ok])
                d["t"] += list(te[ok])
                d["conc"] += list(cc[ok])
                d["away"] += list(aw[ok])
        log(f"    события: " + ", ".join(
            f"{w}с×{mu:g}/{c:g}{'↑' if s < 0 else '↓'}={len(ev[k]['col'])}"
            for k in cells for (w, mu, c, (s, _)) in [k]))
    if missing:
        log(f"нет в хранилище (пропущены): {', '.join(missing)}")

    # 3. Замер: превышение над одновременной кросс-секцией.
    rows_out, thin = [], []
    n_bg = int((np.isfinite(O).sum(axis=1) > 0).sum())
    min_cross = max(MIN_CROSS, int(round(MIN_CROSS_SHARE * n_bg)))
    log(f"имён с ценой в фоне {n_bg}, требуется в фоне не меньше {min_cross}")
    for key in cells:
        win, mult, conc_min, (side, name) = key
        d = ev[key]
        if not d["col"]:
            continue
        rows = np.array(d["row"], dtype=np.int64)
        cols = np.array(d["col"], dtype=np.int64)
        te = np.array(d["t"], dtype=np.float64)
        ep = E.episodes(te, gap_sec=EPISODE_SEC)
        bans = {}
        for hm in horizons:
            h = hm * 60 // step_sec
            guard = max(win, hm * 60)
            if guard not in bans:
                bans[guard] = E.ban_matrix(O.shape, rows, cols,
                                           guard_min=guard, step_min=step_sec)
            k = np.clip(cols + h, 0, O.shape[1] - 1)
            with np.errstate(invalid="ignore", divide="ignore"):
                f = np.where(cols + h < O.shape[1],
                             O[rows, k] / O[rows, cols] - 1.0, np.nan)
            f = f * (1 if side < 0 else -1)
            cs = E.cross_section(O, cols, rows, hm * 60, guard_min=guard,
                                 step_min=step_sec, banned=bans[guard],
                                 min_cross=min_cross) * (1 if side < 0 else -1)
            exc = np.where(np.isfinite(cs) & np.isfinite(f), f - cs, np.nan)
            wid = cross_width(O, bans[guard], cols, h)
            mae, mfe = excursion(O, HI, LO, rows, cols, h, side)
            e = E.by_episode(exc, ep)
            if len(e) < 5:
                thin.append({"window_sec": win, "vol_mult": mult,
                             "conc": conc_min, "side": name,
                             "horizon_min": hm, "events": len(cols),
                             "episodes": int(len(e))})
                continue
            mae = mae[np.isfinite(mae)]
            mfe = mfe[np.isfinite(mfe)]
            rows_out.append({
                "window_sec": win, "vol_mult": mult, "conc": conc_min,
                "side": name, "horizon_min": hm, "events": int(len(cols)),
                "episodes": int(len(e)),
                "cross_cover": float(np.isfinite(exc).sum()) / len(cols),
                "cross_width": float(np.median(wid)),
                "excess_bp": float(np.median(e)) * 1e4,
                "share_pos": float(np.mean(e > 0)),
                "mae_bp": float(np.median(mae)) * 1e4 if len(mae) else None,
                "mfe_bp": float(np.median(mfe)) * 1e4 if len(mfe) else None,
                "median_conc": float(np.median(d["conc"])),
                "away_bp": float(np.median(d["away"])) * 1e4,
            })

    cfg = {"symbols": syms, "start": a.start, "end": a.end,
           "interval": a.interval, "step_sec": step_sec,
           "windows": list(WINDOWS), "vol_mults": list(VOL_MULTS),
           "concs": list(CONCS), "bands": BANDS, "imb": IMB,
           "move_mult": MOVE_MULT, "horizons_min": horizons,
           "horizons_dropped": dropped,
           "episode_sec": EPISODE_SEC, "min_cross": min_cross,
           "background_symbols": n_bg, "missing_in_store": missing}
    with open(os.path.join(OUT, f"level_probe{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"config": cfg, "rows": rows_out, "thin": thin}, f,
                  ensure_ascii=False, indent=1)

    text = report(cfg, rows_out, thin)
    dst = os.path.join(OUT, f"T2-level-probe{a.tag}.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    log(f"записано {dst}")


def cross_width(P, banned, cols, steps_h):
    n = P.shape[1]
    j = np.asarray(cols, dtype=np.int64)
    k = np.clip(j + steps_h, 0, n - 1)
    ok = (~banned[:, j]) & np.isfinite(P[:, j]) & np.isfinite(P[:, k])
    return ok.sum(axis=0).astype(np.float64)


def excursion(P, HI, LO, rows, cols, steps_h, side):
    """Ход против позиции и в её пользу за горизонт, по краям баров."""
    n = P.shape[1]
    entry = P[rows, cols]
    lo = np.full(len(cols), np.inf)
    hi = np.full(len(cols), -np.inf)
    for k in range(steps_h + 1):
        j = np.clip(cols + k, 0, n - 1)
        fit = (cols + k) < n
        lo = np.fmin(lo, np.where(fit, LO[rows, j], np.nan))
        hi = np.fmax(hi, np.where(fit, HI[rows, j], np.nan))
    with np.errstate(invalid="ignore", divide="ignore"):
        a, b = lo / entry - 1.0, hi / entry - 1.0
    return (a, b) if side < 0 else (-b, -a)


def report(cfg, rows_out, thin):
    md = ["# Зонд: набор на цене, фон из хранилища A2\n",
          f"Символов ленты {len(cfg['symbols'])}, окно {cfg['start']} … "
          f"{cfg['end']}. События — из ленты Bybit по секундной сетке; "
          f"**форвард и фон — из хранилища A2** ({cfg['interval']}, "
          f"{cfg['background_symbols']} символов), и оба из одного "
          f"источника: иначе базис между площадками вошёл бы в разность "
          f"как эдж.\n",
          "Вход — открытие первого бара, начинающегося ПОСЛЕ события, то "
          "есть первая цена, по которой сделка возможна. В T1 вход брался "
          "по закрытию секунды обнаружения — по цене, которой уже нет.\n",
          f"Набор — агрессия выше обычного в заданное число раз при "
          f"перевесе стороны ≥ {cfg['imb']:g} и **доле объёма в самой "
          f"загруженной полосе** ≥ порога, полос {cfg['bands']} на ход "
          f"окна. Круг издержек: тейкер **{TAKER_ROUND_BP:.0f} б.п.**, "
          f"мейкер {MAKER_ROUND_BP:.0f}. В фоне требуется не меньше "
          f"{cfg['min_cross']} имён.\n"]
    if cfg["missing_in_store"]:
        md.append("Пропущены (нет в хранилище): "
                  + ", ".join(cfg["missing_in_store"]) + "\n")
    for name in ("набор под ценой", "разгрузка над ценой"):
        md.append(f"\n## {name.capitalize()}\n")
        md.append("| Окно | Объём | Сосред. | Событий | Эпизодов | "
                  "С контролем | Имён в фоне | Отход | "
                  + " | ".join(f"{h} мин" for h in cfg["horizons_min"])
                  + " |")
        md.append("|---" * (len(cfg["horizons_min"]) + 8) + "|")
        for win, mult, cc in product(cfg["windows"], cfg["vol_mults"],
                                     cfg["concs"]):
            cells, eps, evn, cov, wid, away = [], 0, 0, [], [], None
            for hm in cfg["horizons_min"]:
                r = next((x for x in rows_out
                          if x["window_sec"] == win and x["vol_mult"] == mult
                          and x["conc"] == cc and x["side"] == name
                          and x["horizon_min"] == hm), None)
                if r:
                    cells.append(f"{r['excess_bp']:+.1f}")
                    eps = max(eps, r["episodes"])
                    evn = max(evn, r["events"])
                    cov.append(r["cross_cover"])
                    wid.append(r["cross_width"])
                    away = r["away_bp"]
                else:
                    t = next((x for x in thin
                              if x["window_sec"] == win
                              and x["vol_mult"] == mult and x["conc"] == cc
                              and x["side"] == name
                              and x["horizon_min"] == hm), None)
                    cells.append("нет фона" if t and t["events"] else "—")
                    if t:
                        evn = max(evn, t["events"])
            c = f"{min(cov):.0%}–{max(cov):.0%}" if cov else "—"
            w = f"{min(wid):.0f}–{max(wid):.0f}" if wid else "—"
            aw = f"{away:.0f} б.п." if away is not None else "—"
            md.append(f"| {win} с | ×{mult:g} | {cc:g} | {evn} | {eps} | "
                      f"{c} | {w} | {aw} | " + " | ".join(cells) + " |")
        md.append("")
    md.append("\n## Ход против позиции и в её пользу\n")
    md.append("| Окно | Объём | Сосред. | Сторона | Горизонт | Против | "
              "В пользу | В пользу / против |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in rows_out:
        if r["mae_bp"] is None:
            continue
        ratio = abs(r["mfe_bp"] / r["mae_bp"]) if r["mae_bp"] else float("nan")
        md.append(f"| {r['window_sec']} с | ×{r['vol_mult']:g} | "
                  f"{r['conc']:g} | {r['side']} | {r['horizon_min']} мин | "
                  f"{r['mae_bp']:+.0f} б.п. | {r['mfe_bp']:+.0f} б.п. | "
                  f"{ratio:.2f} |")
    md.append("")
    md.append("\n## Как читать\n")
    md.append("**«Отход»** — насколько цена к концу окна ушла от уровня "
              "набора. Большая величина означает, что войти по уровню уже "
              "нельзя, и замер описывает другую сделку.\n")
    md.append("**Превышение ниже круга издержек** — сигнал есть, торговать "
              "нечем. Так закрылись каскады (11.4 б.п. против 11.7) и "
              "поглощение без уровня (−0.2 б.п. при круге 11).\n")
    md.append("**«В пользу» есть потолок сверху** — лучший возможный выход "
              "внутри горизонта, при идеальном знании будущего. Меньше "
              "круга — ячейка мертва по арифметике при любом сигнале.\n")
    md.append("**Отношение «в пользу / против» около единицы** — размах "
              "симметричен, и ставить ограничитель некуда. Асимметрия "
              "одного знака у ОБЕИХ сторон означает снос рынка за период, "
              "а не свойство события: в T1 так и было.\n")
    return "\n".join(md)


if __name__ == "__main__":
    main()
