#!/usr/bin/env python3
"""W1 — зонд волнового анализа: повторяются ли волны и платит ли это.

**Зонд, а не гипотеза.** Ни вердикта, ни права на итерацию: его дело —
ответить на вопрос владельца числами и решить, стоит ли писать спеку.
Но пространство объявлено ЦЕЛИКОМ здесь и после прогона не растёт, и
решение читается по медиане сетки, а не по лучшей ячейке: выбрать
лучшую из шестнадцати задним числом — это ошибка R5, стоившая проекту
целой гипотезы.

Что спрашивается
----------------

Владелец: «найти в данных повторяющиеся волны, чтобы строить на этом
стратегии». Слово «волна» имеет две прочитки, и зонд меряет обе.

**Прочитка 1 — форма повторяется со смыслом.** Берётся путь цены за
последние `W` часов, снимаются уровень и масштаб, ищутся `K` ближайших
по форме кусков ИЗ ПРОШЛОГО, и их будущее становится предсказанием.
Никаких допущений о том, что такое волна: если формы повторяются, это
видно прямо.

**Прочитка 2 — структура волн (то, что трейдер зовёт Эллиоттом).**
Цена раскладывается зигзагом на ноги, и меряется распределение
коэффициента отката. Центральное числовое утверждение волнового
анализа — что откаты садятся на уровни Фибоначчи — проверяется против
суррогата с тем же распределением приращений.

Главная ловушка, названная ДО прогона
-------------------------------------

Проект уже измерил, что **краткосрочный возврат существует**: R2 дала
IC 0.047, зонд возврата +15.8 б.п. сверх кросс-секции после падения на
3 %, D1 — +26 б.п. на секундной записи. Поэтому любой «волновой»
сигнал скорее всего окажется этим самым возвратом в новом костюме.

Защит две, и обе встроены в конструкцию, а не приделаны сбоку:

1. **Масштаб снимается нормировкой.** Величина хода — это и есть
   возврат; поделив путь на его собственный размах, мы оставляем
   только форму. Если она предсказывает, это второй сигнал.
2. **Контроль возврата считается рядом.** На тех же сечениях меряется
   IC простого `−ret_W`, и IC предсказания ПОСЛЕ снятия с него
   возврата кросс-секционной регрессией. Не осталось добавки — значит
   мы переоткрыли R2, и об этом надо сказать, а не назвать волной.

И третья, независимая от первых двух: **градиент по тесноте
совпадения**. Если механизм — форма, то у запросов, чьи соседи совпали
теснее, IC обязан быть выше. Ровно этот довод закрыл уровневый зонд
T2: в измеренной области градиент смотрел в другую сторону, и крупные
числа стояли на пяти эпизодах.

Нуль
----

Соседи выбираются СЛУЧАЙНО из того же пула, той же эры, тем же числом.
Если похожие соседи предсказывают не лучше случайных, форма не несёт
ничего, а положительная величина принадлежит эре.

Единицы
-------

Всё считается сверх ОДНОВРЕМЕННОЙ кросс-секции (равновзвешенной, а не
медианной: медиана робастна, но она не портфель — урок Z1). Деньги — в
долях гросс-нотионала книги, Σ|w| = 1: прибыль книги равна половине
спреда дециля, полная замена книги стоит 11 б.п. при тейкере 5.5. Это
конвенция R4, и заведена она потому, что сравнение спреда «на ногу» с
циклом «на пару ног» уже однажды дало нестрогое число.

    .venv/bin/python research/w1_waves/probe.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "z1_screen"))

import data as D                                          # noqa: E402
import screen as Z                                        # noqa: E402
import waves as W                                         # noqa: E402

# --- пространство, объявленное до прогона -------------------------------

STEP_SEC = 3600                   # часовая сетка: мельче начинается
STEP_H = 1                        # микроструктура (замер A4)
WINDOWS = (12, 24, 48, 168)       # длина формы, часов: полсуток…неделя
HORIZONS = (1, 4, 12, 24)         # горизонт, часов
K = 50                            # соседей на запрос
MIN_NB_SHARE = 0.2                # доля соседей с известным будущим,
                                  # иначе предсказания нет вовсе
POOL = 20_000                     # форм в пуле
POOL_DAYS = 365                   # пул берётся из года ПЕРЕД кварталом
QUERY_EVERY_H = 12                # два сечения в сутки
MIN_CROSS = 50                    # символов в сечении, иначе не сечение
SIM_BANDS = ((0.50, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01))

# Зигзаг: порог разворота в суточных сигмах САМОГО символа.
THETAS = (1.0, 2.0, 3.0)
BOOT = 20                         # суррогатов на символ
BLOCK_H = 24                      # блок бутстрапа — сутки
MIN_HOURS_ZZ = 24 * 90            # часов истории, иначе ног не набрать

ROUND_COST_BP = 11.0              # полная замена книги, тейкер 5.5 б.п.

START = "2023-01-01"              # тестовая эра
END = "2026-06-01"
MIN_SHARE = 0.90                  # фильтр ликвидности A3
SEED = 20260825                   # зерно ЧИСЛОМ, а не от часов запуска
BLOCK_Q = 1024                    # запросов в блоке умножения
MEM_SHARE = 0.5                   # доля свободной памяти, которую берём


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def free_mb():
    """Доступная память машины. Ноль — значит не спросили, а не «нет»."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


def memory_plan(n_sym, n_h, log=log_):
    """Сколько нужно и сколько есть — ДО счёта, а не после падения.

    Рядом идёт живой сбор стакана, и записи, которую он потеряет, не
    докачать ниоткуда. Прогон D1 однажды был убит ядром по памяти
    именно так, и урок оттуда прямой: память считается составом, а не
    на глаз. Отказаться громко лучше, чем рискнуть молча.
    """
    px = n_sym * n_h * 4 / 1e6                    # матрица цен
    need = px * (1 + len(HORIZONS))               # цены плюс форварды
    need += BLOCK_Q * POOL * 4 / 1e6              # блок «запросы × пул»
    need += POOL * (max(WINDOWS) + 1) * 4 / 1e6   # формы пула
    have = free_mb()
    log(f"память: нужно ~{need:.0f} МБ, доступно {have:.0f} МБ")
    if have and need > MEM_SHARE * have:
        raise SystemExit(
            f"нужно ~{need:.0f} МБ при доступных {have:.0f} — это больше "
            f"объявленной доли {MEM_SHARE:.0%}. Уменьшить можно BLOCK_Q "
            f"({BLOCK_Q}) или POOL ({POOL:,}); ни то, ни другое ответа не "
            "меняет.")
    return need


def grid(start, end):
    t0 = int(datetime.fromisoformat(start)
             .replace(tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(end)
             .replace(tzinfo=timezone.utc).timestamp())
    return np.arange(t0, t1, STEP_SEC, dtype=np.int64)


def quarters(start, end):
    """Границы кварталов тестовой эры: пул строится заново на каждый."""
    a = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    b = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    out = []
    while a < b:
        m = a.month + 3
        y = a.year + (m - 1) // 12
        nxt = a.replace(year=y, month=(m - 1) % 12 + 1)
        out.append((a, min(nxt, b)))
        a = nxt
    return out


def load_prices(symbols, times, interval, log=log_):
    """Логарифмические цены и маски годности. Пустая матрица — отказ.

    Берётся открытие часового бара — первая цена, по которой можно
    купить в этот момент. Бар без сделок не наблюдение (правило A2), и
    замороженный ряд отсюда уходит сам: у него открытий со сделками нет.
    """
    P = D.price_matrix(symbols, times, interval, log)
    fill = float(np.isfinite(P).mean())
    if fill < 0.01:
        # Пустая матрица — не «волн нет», а сломанная загрузка. Зонд
        # возврата однажды молча напечатал нулевой отчёт именно так.
        raise SystemExit(f"матрица цен заполнена на {fill:.2%} — "
                         "проверить шаг сетки и хранилище A2")
    uni = D.universe()
    share, min_share = D.liquid_days(interval, MIN_SHARE)
    ok = np.isfinite(P)
    for r, sym in enumerate(symbols):
        if not ok[r].any():
            continue
        ok[r] &= D.delist_mask(sym, times, uni)
        ok[r] &= D.liquidity_mask(sym, times, share, min_share)
    L = np.where(ok, np.log(np.maximum(P, 1e-300)), np.nan).astype(np.float32)
    log(f"  цены: заполнено {fill:.1%}, годных символо-часов "
        f"{int(np.isfinite(L).sum()):,}")
    return L


def excess_forward(L, h, min_cross=MIN_CROSS):
    """Избыточная доходность вперёд: сверх РАВНОВЗВЕШЕННОЙ кросс-секции.

    Контроль средним, а не медианой. Медиана робастна, но она не
    портфель: хеджировать об неё нельзя, и Z1 намерил, что превышение
    над медианой несёт снос, не зависящий от условия. Равновзвешенная
    корзина такого сноса не имеет по построению.

    Сечение тоньше `min_cross` — пропуск целиком: это ловушка, на
    которой у зонда возврата выродилась целая ячейка.
    """
    n = L.shape[1]
    F = np.full(L.shape, np.nan, dtype=np.float32)
    if h < n:
        F[:, :n - h] = L[:, h:] - L[:, :n - h]
    fin = np.isfinite(F)
    cnt = fin.sum(axis=0)
    s = np.where(fin, F, 0.0).sum(axis=0)
    mean = np.where(cnt >= min_cross, s / np.maximum(cnt, 1), np.nan)
    return (F - mean[None, :]).astype(np.float32)


def paths(L, rows, cols, W):
    """Сырые пути `W+1` баров, кончающиеся в своей колонке."""
    off = np.arange(-W, 1, dtype=np.int64)[None, :]
    return L[rows[:, None], cols[:, None] + off]


def sample_pool(L, ok_cols, t_lo, t_hi, W, rng, want=POOL):
    """Пул форм из ПРОШЛОГО: строки-символы, колонки-времена.

    Пул строится строго раньше запросов, поэтому запрещать соседей по
    времени не приходится вовсе: у одновременных соседей будущее одно
    и то же — рынок, — и предсказание выродилось бы в подсматривание.
    """
    lo = max(t_lo, W)
    if t_hi <= lo:
        return None
    cand_c = np.flatnonzero(ok_cols[lo:t_hi]) + lo
    if len(cand_c) == 0:
        return None
    rows = np.arange(L.shape[0])
    R, C = np.meshgrid(rows, cand_c, indexing="ij")
    R, C = R.ravel(), C.ravel()
    good = np.isfinite(L[R, C])
    R, C = R[good], C[good]
    if len(R) == 0:
        return None
    take = rng.choice(len(R), size=min(want, len(R)), replace=False)
    return R[take], C[take]


def _median_of(nb, n, g):
    """Медиана будущего соседей — только там, где соседей достаточно.

    Предсказание, собранное по двум соседям из пятидесяти, — не та
    мера, которую объявляли: у пула бывают пропуски будущего (тонкое
    сечение в его собственный момент). Мало соседей — ПРОПУСК, а не
    значение по тем, что нашлись.
    """
    out = np.full(n, np.nan)
    cnt = np.isfinite(nb).sum(axis=1)
    ok = cnt >= max(1, int(round(MIN_NB_SHARE * nb.shape[1])))
    if ok.any():
        v = np.full(nb.shape[0], np.nan)
        v[ok] = np.nanmedian(nb[ok], axis=1)
        out[g] = v
    return out


def cell_key(w, h):
    return f"W{w}h{h}"


def section_stats(pred, actual, rev, sim, acc, w, h):
    """Одно сечение: IC, спред дециля, нуль и контроль возврата.

    Всё считается ПО СЕЧЕНИЮ и складывается в накопитель: итог есть
    медиана по сечениям, а не среднее по сделкам. Сечения на сутки
    отстоят друг от друга, поэтому при горизонте до суток они не
    перекрываются по построению.
    """
    ok = np.isfinite(pred) & np.isfinite(actual)
    if int(ok.sum()) < MIN_CROSS:
        return
    p, a = pred[ok], actual[ok]
    key = cell_key(w, h)
    d = acc.setdefault(key, {"ic": [], "spread": [], "rev_ic": [],
                             "resid_ic": [], "bands": {}, "n": 0})
    d["n"] += 1
    d["ic"].append(W.spearman(p, a))
    # Спред дециля: длинно-короткая книга по краям сечения.
    m = max(int(round(0.1 * len(p))), 1)
    order = np.argsort(-p)
    d["spread"].append(float(a[order[:m]].mean() - a[order[-m:]].mean()))
    # Контроль возврата: тот же сигнал, что уже измерен проектом.
    r = rev[ok]
    if np.isfinite(r).sum() >= MIN_CROSS:
        d["rev_ic"].append(W.spearman(r, a))
        # Остаток предсказания после снятия возврата кросс-секционно:
        # если добавки нет, волна есть возврат в костюме.
        fr = np.isfinite(r)
        x, y = r[fr], p[fr]
        xc = x - x.mean()
        den = float((xc * xc).sum())
        if den > 0:
            b = float((xc * (y - y.mean())).sum() / den)
            res = np.full(len(p), np.nan)
            res[fr] = y - y.mean() - b * xc
            d["resid_ic"].append(W.spearman(res, a))
    # Градиент по тесноте совпадения — полосы объявлены до прогона.
    for lo, hi in SIM_BANDS:
        sel = ok & np.isfinite(sim) & (sim >= lo) & (sim < hi)
        if int(sel.sum()) >= 10:
            d["bands"].setdefault((lo, hi), []).append(
                W.spearman(pred[sel], actual[sel]))


def run_knn(L, times, symbols, rng, log=log_):
    """Прочитка 1: повторяется ли форма со смыслом."""
    ok_cols = np.isfinite(L).sum(axis=0) >= MIN_CROSS
    acc, acc0 = {}, {}
    q_step = QUERY_EVERY_H // STEP_H
    fwd = {h: excess_forward(L, h) for h in HORIZONS}
    t_of = {int(t): i for i, t in enumerate(times)}
    for qa, qb in quarters(START, END):
        ja = t_of.get(int(qa.timestamp()))
        jb = t_of.get(int(qb.timestamp()), L.shape[1])
        if ja is None:
            continue
        pool_lo = t_of.get(int((qa - timedelta(days=POOL_DAYS)).timestamp()), 0)
        qcols = np.arange(ja, jb, q_step, dtype=np.int64)
        qcols = qcols[ok_cols[qcols]]
        if len(qcols) == 0:
            continue
        for w in WINDOWS:
            pool = sample_pool(L, ok_cols, pool_lo, ja, w, rng)
            if pool is None:
                continue
            pr, pc = pool
            PZ, pok = W.znorm(paths(L, pr, pc, w))
            keep = pok & np.isfinite(PZ).all(axis=1)
            PZ, pr, pc = PZ[keep], pr[keep], pc[keep]
            if len(pr) < K * 4:
                continue
            pf = {h: fwd[h][pr, pc] for h in HORIZONS}
            t0 = time.time()
            for j in qcols:
                rows = np.flatnonzero(np.isfinite(L[:, j]))
                if len(rows) < MIN_CROSS:
                    continue
                X = paths(L, rows, np.full(len(rows), j), w)
                QZ, qok = W.znorm(X)
                if not qok.any():
                    continue
                idx, sim = W.top_neighbours(QZ, PZ, K, block=BLOCK_Q)
                # Считается только по строкам, у которых форма есть.
                # Гонять nanmedian по строкам сплошных пропусков — это
                # поток предупреждений numpy, в котором утонет
                # настоящее; и ответ от этого не меняется.
                g = qok & (idx >= 0).any(axis=1)
                if not g.any():
                    continue
                msim = np.full(len(rows), np.nan)
                msim[g] = np.nanmean(np.where(idx[g] >= 0, sim[g], np.nan),
                                     axis=1)
                ridx = rng.integers(0, len(pr), size=(int(g.sum()), K))
                rev = -(L[rows, j] - L[rows, j - w]).astype(np.float64)
                for h in HORIZONS:
                    nb = np.where(idx[g] >= 0, pf[h][idx[g]], np.nan)
                    act = fwd[h][rows, j]
                    pred = _median_of(nb, len(rows), g)
                    section_stats(pred, act, rev, msim, acc, w, h)
                    p0 = _median_of(pf[h][ridx], len(rows), g)
                    section_stats(p0, act, rev, msim, acc0, w, h)
            log(f"  {qa.date()} W={w}: сечений {len(qcols)}, пул "
                f"{len(pr):,}, {time.time() - t0:.0f} с")
    return acc, acc0


def sigma_hour(L, lo, hi):
    """Часовая σ приращений по окну ПЕРЕД замером — по символу."""
    seg = L[:, lo:hi].astype(np.float64)
    d = np.diff(seg, axis=1)
    with np.errstate(invalid="ignore"):
        s = np.nanstd(d, axis=1)
    n = np.isfinite(d).sum(axis=1)
    s[n < 200] = np.nan
    return s


def run_zigzag(L, times, symbols, rng, log=log_):
    """Прочитка 2: похожа ли структура ног на случайное блуждание."""
    t_of = {int(t): i for i, t in enumerate(times)}
    ja = t_of.get(int(datetime.fromisoformat(START)
                      .replace(tzinfo=timezone.utc).timestamp()), 0)
    sig = sigma_hour(L, 0, ja) * np.sqrt(24.0)      # суточная σ
    out = {}
    for mult in THETAS:
        real, sur, lags, sizes = [], [], [], []
        used = 0
        for r, sym in enumerate(symbols):
            if not np.isfinite(sig[r]) or sig[r] <= 0:
                continue
            x = L[r, ja:].astype(np.float64)
            if np.isfinite(x).sum() < MIN_HOURS_ZZ:
                continue
            th = float(mult * sig[r])
            piv = W.zigzag(x, th)
            lg = W.legs(x, piv)
            if len(lg) < 5:
                continue
            used += 1
            real.extend(v["ratio"] for v in lg)
            lags.extend(v["i_confirm"] - v["i_to"] for v in lg)
            sizes.extend(v["size"] for v in lg)
            d = np.diff(x)
            for _ in range(BOOT):
                s = W.block_bootstrap(d, BLOCK_H, rng)
                fin = np.isfinite(s)
                # Пропуск в приращениях означает, что наблюдения нет:
                # уровень переносится (нулевое приращение), а сама
                # точка остаётся пропуском — иначе дыра стала бы ногой.
                y = np.empty(len(x))
                y[0] = x[0]
                y[1:] = x[0] + np.cumsum(np.where(fin, s, 0.0))
                y[1:][~fin] = np.nan
                sur.extend(v["ratio"] for v in W.legs(y, W.zigzag(y, th)))
        out[mult] = {
            "symbols": used,
            "legs": int(np.isfinite(real).sum()),
            "real": W.fib_shares(real),
            "surrogate": W.fib_shares(sur),
            "lag_median_h": (float(np.median(lags)) if lags
                             else float("nan")),
            "size_median_bp": (float(np.median(sizes)) * 1e4 if sizes
                               else float("nan")),
            "ratio_median": (float(np.nanmedian(real)) if real
                             else float("nan")),
            "ratio_median_sur": (float(np.nanmedian(sur)) if sur
                                 else float("nan")),
        }
        log(f"  порог {mult}σ: символов {used}, ног "
            f"{out[mult]['legs']:,}, задержка подтверждения "
            f"{out[mult]['lag_median_h']:.0f} ч")
    return out


def med(v):
    v = [x for x in v if np.isfinite(x)]
    return float(np.median(v)) if v else float("nan")


def cells_table(acc, acc0):
    rows = []
    for w in WINDOWS:
        for h in HORIZONS:
            k = cell_key(w, h)
            d, z = acc.get(k), acc0.get(k)
            if not d:
                continue
            spread_bp = med(d["spread"]) * 1e4
            rows.append({
                "W": w, "h": h, "sections": d["n"],
                "ic": med(d["ic"]),
                "ic_null": med(z["ic"]) if z else float("nan"),
                "rev_ic": med(d["rev_ic"]),
                "resid_ic": med(d["resid_ic"]),
                "spread_bp": spread_bp,
                "book_bp": spread_bp / 2.0,
                "bands": {f"{a:.2f}-{b:.2f}": med(v)
                          for (a, b), v in sorted(d["bands"].items())},
            })
    return rows


def write_report(path, rows, zz, meta):
    L = []
    L.append("# W1 — зонд волнового анализа\n")
    L.append(f"Прогон {meta['when']} · {meta['start']}…{meta['end']} · "
             f"символов {meta['symbols']} · шаг {STEP_H} ч · "
             f"соседей {K} · пул {POOL:,}\n")
    L.append("**Зонд, а не гипотеза:** вердикта нет, право на итерацию "
             "не тратится. Пространство объявлено до прогона и после "
             "него не росло; читать надо медиану сетки, а не лучшую "
             "ячейку — выбрать лучшую из шестнадцати задним числом есть "
             "ошибка R5.\n")

    L.append("\n## 1. Повторяется ли форма со смыслом\n")
    L.append("Путь за `W` часов, уровень и масштаб сняты, "
             f"{K} ближайших форм ИЗ ПРОШЛОГО (пул за год перед "
             "кварталом), их будущее — предсказание. Всё сверх "
             "одновременной равновзвешенной кросс-секции.\n")
    L.append("\n| W, ч | h, ч | сечений | IC | IC нуля | IC возврата | "
             "IC остатка | спред дециля, б.п. | книга, б.п. |")
    L.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in rows:
        L.append(f"| {r['W']} | {r['h']} | {r['sections']:,} | "
                 f"{r['ic']:+.4f} | {r['ic_null']:+.4f} | "
                 f"{r['rev_ic']:+.4f} | {r['resid_ic']:+.4f} | "
                 f"{r['spread_bp']:+.1f} | {r['book_bp']:+.1f} |")
    if rows:
        ic = med([r["ic"] for r in rows])
        ic0 = med([r["ic_null"] for r in rows])
        rv = med([r["rev_ic"] for r in rows])
        rs = med([r["resid_ic"] for r in rows])
        bk = med([r["book_bp"] for r in rows])
        L.append(f"\nМедиана по сетке: IC {ic:+.4f} при нуле {ic0:+.4f}; "
                 f"IC возврата {rv:+.4f}; IC остатка после снятия "
                 f"возврата {rs:+.4f}; прибыль книги {bk:+.1f} б.п. "
                 f"против полной замены в {ROUND_COST_BP:.0f} б.п.\n")
        # Вердиктовая фраза выводится ИЗ ЧИСЕЛ, а не стоит рядом с
        # ними: проза, написанная под ожидаемый результат, однажды уже
        # противоречила собственной таблице.
        if not np.isfinite(ic):
            L.append("\n**Читается так:** ни одной измеренной ячейки — "
                     "считать нечего.\n")
        elif ic <= ic0:
            L.append("\n**Читается так:** похожие соседи предсказывают "
                     "НЕ лучше случайных — форма сама по себе не несёт "
                     "ничего.\n")
        elif not np.isfinite(rs) or abs(rs) < 0.5 * abs(ic):
            L.append("\n**Читается так:** форма предсказывает лучше "
                     "случайной, но после снятия возврата от неё "
                     "остаётся меньше половины — это уже измеренный "
                     "проектом возврат (R2, зонд возврата, D1) в новом "
                     "костюме, а не второй сигнал.\n")
        elif bk < ROUND_COST_BP:
            L.append("\n**Читается так:** сигнал сверх возврата есть, "
                     "но книга не перебивает круг издержек.\n")
        else:
            L.append("\n**Читается так:** форма несёт сигнал сверх "
                     "возврата, и книга перебивает круг издержек — "
                     "повод писать спеку, а не вывод.\n")

    L.append("\n### Градиент по тесноте совпадения\n")
    L.append("Если механизм — форма, то у запросов, чьи соседи совпали "
             "теснее, IC обязан быть выше. Ровно этот довод закрыл "
             "уровневый зонд T2.\n")
    bands = [f"{a:.2f}-{b:.2f}" for a, b in SIM_BANDS]
    L.append("\n| W, ч | h, ч | " + " | ".join(bands) + " |")
    L.append("|--:|--:|" + "--:|" * len(bands))
    for r in rows:
        cells = " | ".join(
            (f"{r['bands'][b]:+.4f}" if b in r["bands"]
             and np.isfinite(r["bands"][b]) else "—") for b in bands)
        L.append(f"| {r['W']} | {r['h']} | {cells} |")

    L.append("\n## 2. Похожа ли структура ног на случайное блуждание\n")
    L.append("Зигзаг по порогу в суточных σ САМОГО символа; откат — "
             "отношение ноги к предыдущей. Суррогат: те же приращения, "
             "порядок разбит блоками по суткам — он сохраняет "
             "кластеризацию волатильности и рвёт всё, что длиннее "
             "суток.\n")
    L.append("\n**Задержка подтверждения** — цена честности: вершина "
             "видна не в вершине, а когда цена отошла на порог. "
             "Разметка, берущая вершину задним числом, заглядывает в "
             "будущее.\n")
    lv = list(W.FIB_LEVELS)
    L.append("\n| порог | символов | ног | задержка, ч | медиана ноги, "
             "б.п. | медиана отката | " + " | ".join(f"{f:.3f}"
                                                     for f in lv) + " |")
    L.append("|--:|--:|--:|--:|--:|--:|" + "--:|" * len(lv))
    for mult in THETAS:
        d = zz.get(mult)
        if not d:
            continue
        for who, name in (("real", "факт"), ("surrogate", "суррогат")):
            s = d[who]
            cells = " | ".join(f"{s[f]:.3f}" if np.isfinite(s.get(f, np.nan))
                               else "—" for f in lv)
            head = (f"| {mult:.0f}σ {name} | {d['symbols']} | {s['n']:,} | "
                    f"{d['lag_median_h']:.0f} | {d['size_median_bp']:.0f} | "
                    f"{d['ratio_median' if who == 'real' else 'ratio_median_sur']:.3f} | ")
            L.append(head + cells + " |")
    diffs = []
    for mult in THETAS:
        d = zz.get(mult)
        if not d:
            continue
        for f in lv:
            a, b = d["real"].get(f), d["surrogate"].get(f)
            if np.isfinite(a) and np.isfinite(b):
                diffs.append(a - b)
    if diffs:
        L.append(f"\nМедианное превышение доли над суррогатом по всем "
                 f"уровням и порогам: {np.median(diffs):+.4f} "
                 f"(полоса ±{W.FIB_BAND}).\n")
        if abs(float(np.median(diffs))) < 0.01:
            L.append("\n**Читается так:** откаты садятся на уровни "
                     "Фибоначчи ровно настолько, насколько на них "
                     "садится случайное блуждание с тем же "
                     "распределением приращений. Числовое ядро "
                     "волнового анализа в этих данных не "
                     "подтверждается.\n")
        else:
            L.append("\n**Читается так:** доли отличаются от "
                     "суррогатных — величину надо читать по таблице "
                     "уровень за уровнем, а не в среднем.\n")

    L.append("\n## Чего зонд не мерил\n")
    L.append("- Разметку по правилам Эллиотта (счёт волн 1–5 и A–B–C): "
             "она требует выбора из нескольких допустимых счётов, а "
             "выбор задним числом и есть то, что делает волновой "
             "анализ неопровержимым. Здесь меряется то, что от счёта "
             "не зависит.\n")
    L.append("- Торгуемое правило по состоянию волны: это следующий "
             "шаг, и он имеет смысл только если что-то из первых двух "
             "мер выжило.\n")
    L.append(f"- Внутридневные волны короче {STEP_H} ч: шаг выбран по "
             "замеру A4 (на мелком баре измеряется микроструктура, а "
             "не рынок).\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    global START, END
    ap = argparse.ArgumentParser(description="зонд волнового анализа")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--tag", default="1h")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--skip-knn", action="store_true")
    ap.add_argument("--skip-zigzag", action="store_true")
    a = ap.parse_args(argv)
    START, END = a.start, a.end
    os.makedirs(OUT, exist_ok=True)

    uni = D.universe()
    symbols = ([s for s in a.symbols.split(",") if s]
               or sorted(uni.keys()))
    # Пул соседей берётся из года ПЕРЕД тестовой эрой, поэтому цены
    # грузятся с запасом назад: без него первый квартал остался бы без
    # пула, и сетка молча начиналась бы позже объявленного.
    lo = (datetime.fromisoformat(START).replace(tzinfo=timezone.utc)
          - timedelta(days=POOL_DAYS)).date().isoformat()
    times = grid(lo, END)
    log_(f"символов {len(symbols)}, часов {len(times):,}")
    memory_plan(len(symbols), len(times))
    L = load_prices(symbols, times, a.interval)
    rng = np.random.default_rng(SEED)

    rows, zz = [], {}
    if not a.skip_knn:
        log_("прочитка 1: повторяется ли форма…")
        acc, acc0 = run_knn(L, times, symbols, rng)
        rows = cells_table(acc, acc0)
    if not a.skip_zigzag:
        log_("прочитка 2: структура ног против суррогата…")
        zz = run_zigzag(L, times, symbols, rng)

    path = os.path.join(OUT, f"W1-waves-{a.tag}.md")
    meta = {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "start": START, "end": END, "symbols": len(symbols)}
    write_report(path, rows, zz, meta)
    with open(os.path.join(OUT, f"w1-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": rows,
                   "zigzag": {str(k): v for k, v in zz.items()},
                   "meta": meta}, f, ensure_ascii=False)
    log_(f"отчёт: {path}")
    if rows:
        log_("медиана по сетке: IC "
             f"{med([r['ic'] for r in rows]):+.4f}, нуль "
             f"{med([r['ic_null'] for r in rows]):+.4f}, книга "
             f"{med([r['book_bp'] for r in rows]):+.1f} б.п.")
    if not a.no_publish:
        # Публикация — часть прогона, а не отдельный шаг: шаг, который
        # можно забыть, однажды забывают, и прогон случается, а отчёт
        # остаётся на сервере.
        Z.publish("W1: зонд волнового анализа")
    return 0


if __name__ == "__main__":
    sys.exit(main())
