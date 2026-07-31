#!/usr/bin/env python3
"""
M2: каркас walk-forward — чистая математика без чтения с диска.

Разделение то же, что в M1 (`features.py` против `build.py`), и по той
же причине: главный способ умереть для обучаемой модели — утечка из
будущего, а проверить её можно только на функциях, которым подаются
выдуманные данные. Загрузка и оркестровка живут в `run.py`.

Решения, принятые ДО прогона (менять после просмотра результатов
нельзя):

* **Окно оценки едино для всех рук: с 2024-07-01.** Статическая рука
  спеки §5 обучается на первых двух годах (2022-07…2024-06) и раньше
  предсказывать не может; критерий 2 требует сравнения «на тех же
  сечениях», значит и переобучаемые руки оцениваются только там же.
* **Обучающая выборка — всё прошлое** (расширяющееся окно): сечение `s`
  входит в обучение на дату `T`, если `s + h < T` — форвард сечения
  целиком известен до момента предсказания. Правило закреплено тестом,
  который переписывает форварды у самой границы.
* **Рука одиночного признака отбирается тем же walk-forward**: на
  каждую дату переобучения берётся признак с наибольшим |средним IC| по
  обучающим сечениям, знак — знак этого среднего. Никакого «мы знаем,
  что лучший — возврат»: знание из R2 получено на этих же данных, и
  зашить его значило бы подглядеть. Диагностикой рядом докладывается
  фиксированный возврат −ret_7.
* IC — ранговая корреляция Спирмена, статистика — по непересекающимся
  сечениям (каждое h-е), как во всех гипотезах с R2.
"""

import warnings
from datetime import date

import numpy as np

EVAL_START = "2024-07-01"          # первый день оценки, см. шапку
MIN_IC_PAIRS = 10                  # меньше пар — IC сечения не считается
SEED0 = 20260731                   # база всех зёрен; выводятся номерами

FREQ_DAYS = {"day": 1, "week": 7, "month": 30, "static": None}
CELLS = [(h, f) for h in (1, 5) for f in ("static", "month", "week", "day")]


def cell_name(h, freq):
    return f"h{h}_{freq}"


def fit_seed(cell_idx, fit_idx):
    """Зерно обучения из номеров — урок R3: зерно, которое нельзя
    воспроизвести, делает нулевую модель непроверяемой."""
    return SEED0 + cell_idx * 100_000 + fit_idx


def null3_seed(h, seed_idx):
    return SEED0 + 50_000_000 + h * 1_000_000 + seed_idx


def rankdata(v):
    """Ранги 1..n со средними на ничьих. Ничьи здесь не экзотика:
    funding-признаки совпадают побитово у многих активов (урок A1 про
    ничьи), и без усреднения IC был бы смещён порядком сортировки."""
    v = np.asarray(v, dtype=np.float64)
    order = np.argsort(v, kind="mergesort")
    sv = v[order]
    n = len(v)
    starts = np.r_[True, sv[1:] != sv[:-1]]
    grp = np.cumsum(starts) - 1
    counts = np.bincount(grp)
    ends = np.cumsum(counts)
    avg = (ends - counts + 1 + ends) / 2.0
    out = np.empty(n)
    out[order] = avg[grp]
    return out


def spearman(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < MIN_IC_PAIRS:
        return np.nan
    ra, rb = rankdata(a[ok]), rankdata(b[ok])
    ra -= ra.mean()
    rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    if den == 0:
        return np.nan
    return float((ra * rb).sum() / den)


def day_slices(day_idx):
    """Границы сечений в отсортированной по дню таблице: (день, lo, hi)."""
    changes = np.flatnonzero(np.diff(day_idx)) + 1
    lo = np.r_[0, changes]
    hi = np.r_[changes, len(day_idx)]
    return [(int(day_idx[a]), int(a), int(b)) for a, b in zip(lo, hi)]


def ic_by_day(x, y, slices):
    """IC каждого признака в каждом сечении: (дни, признаки)."""
    out = np.full((len(slices), x.shape[1]), np.nan)
    for si, (_, a, b) in enumerate(slices):
        yv = y[a:b]
        for j in range(x.shape[1]):
            out[si, j] = spearman(x[a:b, j], yv)
    return out


def shuffle_within_sections(y, slices, seed):
    """Нуль 3: цели перемешиваются ВНУТРИ сечения. Мультимножество дня
    сохраняется — рвётся только связь «какой актив получил какой
    форвард», ровно то, что модель должна была бы выучить."""
    rng = np.random.default_rng(seed)
    out = y.copy()
    for _, a, b in slices:
        out[a:b] = out[a:b][rng.permutation(b - a)]
    return out


def shuffle_global(y, seed):
    """Различитель для нуля 3: перестановка целей по ВСЕЙ истории.

    Перестановка внутри сечения сохраняет средний уровень дня, и модель
    в принципе может выучить «в какие дни сечение в среднем растёт» по
    признакам, общим для всего дня, — это свойство рынка, а не утечка в
    коде. Глобальная перестановка убивает и этот канал. Если нуль 3
    поднят, а глобальный нуль чист, конвейер НЕ течёт — течь показал бы
    только глобальный."""
    rng = np.random.default_rng(seed)
    out = y.copy()
    fin = np.flatnonzero(np.isfinite(out))
    out[fin] = out[fin][rng.permutation(len(fin))]
    return out


def train_rows(day_ord, fit_ord, h):
    """Строки, чей форвард целиком известен до дня обучения."""
    return np.flatnonzero(day_ord + h < fit_ord)


def fit_schedule(eval_ords, freq_days):
    """Номера оценочных дней, перед которыми модель переобучается.
    Статическая рука обучается один раз, перед первым днём оценки."""
    if freq_days is None:
        return [0]
    fits, last = [], None
    for i, o in enumerate(eval_ords):
        if last is None or o - last >= freq_days:
            fits.append(i)
            last = o
    return fits


def run_cell(x, y, day_ord, slices, eval_idx, h, freq_days,
             fit_fn, log=None):
    """Walk-forward одной ячейки.

    `fit_fn(x_train, y_train, fit_idx) -> model` — инъекция, чтобы нуль 3
    (обучение на перемешанных целях) шёл ровно тем же кодом, что прогон:
    отличаться нулю позволено только целями обучения.
    Возвращает предсказания на строках оценочных сечений (NaN вне их).
    """
    pred = np.full(len(y), np.nan)
    eval_ords = [slices[i][0] for i in eval_idx]
    fits = set(fit_schedule(eval_ords, freq_days))
    model, n_fits = None, 0
    for k, si in enumerate(eval_idx):
        d_ord, a, b = slices[si]
        if k in fits:
            rows = train_rows(day_ord, d_ord, h)
            model = fit_fn(x[rows], y[rows], n_fits)
            n_fits += 1
            if log:
                log(f"    обучение {n_fits}: день {k + 1}/{len(eval_idx)}, "
                    f"строк {len(rows)}")
        pred[a:b] = model.predict(x[a:b])
    return pred, n_fits


def single_feature_arm(ic_mat, day_ords, eval_idx, h, freq_days):
    """Рука одиночного признака тем же walk-forward.

    На дату переобучения берётся признак с наибольшим |средним IC| по
    обучающим сечениям (форвард которых уже известен), знак — знак
    среднего. Возвращает IC руки в каждом оценочном сечении и историю
    выбора (номер признака со знаком).
    """
    eval_ords = [day_ords[i] for i in eval_idx]
    fits = set(fit_schedule(eval_ords, freq_days))
    ics = np.full(len(eval_idx), np.nan)
    chosen = np.zeros(len(eval_idx), dtype=np.int64)
    j, sign = -1, 1.0
    for k, si in enumerate(eval_idx):
        d_ord = day_ords[si]
        if k in fits:
            hist = np.flatnonzero(np.asarray(day_ords) + h < d_ord)
            with warnings.catch_warnings():
                # у признака интереса до 2024 года IC нет ни в одном
                # сечении — колонка целиком NaN, и это законно
                warnings.simplefilter("ignore", RuntimeWarning)
                mean_ic = np.nanmean(ic_mat[hist], axis=0)
            j = int(np.nanargmax(np.abs(mean_ic)))
            sign = 1.0 if mean_ic[j] >= 0 else -1.0
        ics[k] = sign * ic_mat[si, j]
        chosen[k] = (j + 1) * int(sign)
    return ics, chosen


def stats(ic_list):
    """Сводка по ряду IC непересекающихся сечений."""
    v = np.asarray(ic_list, dtype=np.float64)
    v = v[np.isfinite(v)]
    n = len(v)
    if n == 0:
        return {"n": 0}
    mean = float(v.mean())
    sd = float(v.std(ddof=1)) if n > 1 else 0.0
    return {"n": n,
            "median": float(np.median(v)),
            "mean": mean,
            "t": mean / (sd / np.sqrt(n)) if sd > 0 else 0.0,
            "share_pos": float((v > 0).mean())}


def nonoverlap(eval_idx, h):
    """Каждое h-е оценочное сечение — статистика без перекрытия
    форвардов (урок R2)."""
    return eval_idx[::h]


def parse_day(s):
    return date.fromisoformat(s).toordinal()
