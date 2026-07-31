#!/usr/bin/env python3
"""
M1: математика признаков — чистые функции над дневными рядами.

Устройство намеренно двухслойное: здесь только numpy-математика на
матрицах «символ × день», без единого чтения с диска. Загрузка живёт в
`build.py`. Разделение не ради красоты: заглядывание в будущее — главный
способ умереть для обучаемой модели (§9 спеки 07), и проверить его можно
только на функциях, которым можно подать выдуманные данные и посмотреть,
что они трогают. Функция, которая сама ходит в хранилище, непроверяема.

Соглашения, единые для всего файла
----------------------------------

* Матрицы имеют форму `(символы, дни)`, день — календарные сутки UTC.
* Пропуск — это `NaN`, а не ноль. День без сделок не наблюдение с
  нулевой доходностью, а отсутствие наблюдения (урок A2 про замороженные
  ряды: нулевая доходность выглядит «стабильностью» и модели полюбится).
* Всё «скользящее» смотрит строго назад: значение на день `t` считается
  по окну, КОНЧАЮЩЕМУСЯ днём `t`. Это закреплено тестом, который меняет
  будущее и требует, чтобы прошлое не шелохнулось.
* Признаки безразмерны и нормированы на собственное прошлое инструмента:
  проект трижды измерил, что абсолютные величины между инструментами
  несравнимы, а в единицах своего прошлого правила общие (T1, T4, B1).

Только numpy.
"""

import warnings

import numpy as np

DAY_MS = 86_400_000
DAY_SEC = 86_400

# Окна, объявленные спекой §4. Менять после просмотра результатов нельзя.
RET_WINDOWS = (1, 3, 7, 14, 30)
PATH_WINDOWS = (7, 14)
SIGMA_SHORT, SIGMA_LONG = 7, 30
BETA_WIN, BETA_MIN = 60, 40
TURN_MED_WIN = 30
FUND_MEAN_WIN, FUND_REGIME_WIN = 7, 30
LIQ_WIN, LIQ_MIN_DAYS, LIQ_SHARE = 90, 60, 0.90
MIN_SECTION = 10                  # меньше активов — волна не определена
HORIZONS = (1, 5)                 # дни форварда, ось сетки M2


def daily_returns(close):
    """Дневные доходности; NaN, если нет любого из двух закрытий."""
    r = np.full_like(close, np.nan)
    r[:, 1:] = close[:, 1:] / close[:, :-1] - 1.0
    return r


def _trailing(x, win, min_n, fn):
    """Скользящее окно, кончающееся текущим днём. Только назад."""
    S, D = x.shape
    out = np.full((S, D), np.nan)
    for t in range(D):
        a = max(0, t - win + 1)
        sl = x[:, a:t + 1]
        n = np.sum(np.isfinite(sl), axis=1)
        ok = n >= min_n
        if ok.any():
            with np.errstate(all="ignore"), warnings.catch_warnings():
                # nanstd на пустом срезе кричит RuntimeWarning; пустой
                # срез здесь законен — его отсеивает `min_n` строкой ниже.
                warnings.simplefilter("ignore", RuntimeWarning)
                v = fn(sl)
            out[ok, t] = v[ok]
    return out


def trailing_std(x, win, min_n):
    return _trailing(x, win, min_n, lambda s: np.nanstd(s, axis=1))


def trailing_mean(x, win, min_n):
    return _trailing(x, win, min_n, lambda s: np.nanmean(s, axis=1))


def trailing_median(x, win, min_n):
    return _trailing(x, win, min_n, lambda s: np.nanmedian(s, axis=1))


def trailing_sum_abs(x, win, min_n):
    return _trailing(x, win, min_n,
                     lambda s: np.nansum(np.abs(s), axis=1))


def ret_k(close, k):
    """Доходность за k дней; NaN без любого из закрытий-концов."""
    out = np.full_like(close, np.nan)
    out[:, k:] = close[:, k:] / close[:, :-k] - 1.0
    return out


def ret_norm(close, k, sigma_long):
    """Доходность за k дней в единицах собственной σ, растянутой на k.

    Деление на `σ·√k` делает признаки разных окон сравнимыми между
    собой: без него ret_30 был бы в ~5 раз шире ret_1 просто по
    построению, и модель читала бы масштаб окна, а не рынок.
    """
    with np.errstate(all="ignore"):
        return ret_k(close, k) / (sigma_long * np.sqrt(float(k)))


def net_over_path(close, r, k, min_frac=0.8):
    """«Чистое/путь» за k дней — та же величина, что в `path_norm`.

    Путь требует не меньше 80 % дней окна: на дырявом хвосте путь из
    трёх дней при чистом за четырнадцать дал бы отношение больше
    единицы, чего у настоящей величины не бывает.
    """
    net = ret_k(close, k)
    path = trailing_sum_abs(r, k, int(np.ceil(k * min_frac)))
    with np.errstate(all="ignore"):
        out = net / path
    out[~np.isfinite(out)] = np.nan
    return out


def wave_excl_self(r, elig):
    """Рыночная волна для каждого актива — среднее ПО ОСТАЛЬНЫМ.

    Включение себя в волну завышает β слабосвязанного актива (замер R1:
    на синтетике из двадцати активов несвязанный получал β > 0.5).
    Для актива вне отбора волна — просто среднее по отобранным.
    """
    m = elig & np.isfinite(r)
    rz = np.where(m, r, 0.0)
    s = rz.sum(axis=0)                       # (дни,)
    n = m.sum(axis=0).astype(float)
    num = s[None, :] - np.where(m, r, 0.0)
    den = n[None, :] - m.astype(float)
    with np.errstate(all="ignore"):
        w = num / den
    w[:, n < MIN_SECTION] = np.nan
    return w


def rolling_beta(r, w, win=BETA_WIN, min_n=BETA_MIN):
    """β актива к волне по скользящему окну, только назад."""
    S, D = r.shape
    out = np.full((S, D), np.nan)
    for t in range(D):
        a = max(0, t - win + 1)
        x = w[:, a:t + 1]
        y = r[:, a:t + 1]
        m = np.isfinite(x) & np.isfinite(y)
        n = m.sum(axis=1)
        ok = n >= min_n
        if not ok.any():
            continue
        xm = np.where(m, x, 0.0)
        ym = np.where(m, y, 0.0)
        with np.errstate(all="ignore"):
            mx = xm.sum(axis=1) / n
            my = ym.sum(axis=1) / n
            cov = (np.where(m, (x - mx[:, None]) * (y - my[:, None]), 0.0)
                   .sum(axis=1) / n)
            var = (np.where(m, (x - mx[:, None]) ** 2, 0.0)
                   .sum(axis=1) / n)
            b = cov / var
        good = ok & np.isfinite(b)
        out[good, t] = b[good]
    return out


def funding_daily(t_ms, rates, day0_ms, n_days):
    """Начисления funding по календарным дням: (сумма б.п., число).

    День без единого начисления — NaN, а не ноль: ряд мог ещё не
    начаться либо иметь дыру, и нулевая ставка была бы выдумкой.
    Частота начислений — сама по себе признак (A1: режим менялся у 318
    символов из 722), поэтому возвращается и число начислений.
    """
    d = ((np.asarray(t_ms, dtype=np.int64) - day0_ms) // DAY_MS)
    ok = (d >= 0) & (d < n_days)
    idx = d[ok].astype(np.int64)
    sums = np.zeros(n_days)
    cnt = np.zeros(n_days)
    np.add.at(sums, idx, np.asarray(rates, dtype=np.float64)[ok] * 1e4)
    np.add.at(cnt, idx, 1.0)
    bp = np.where(cnt > 0, sums, np.nan)
    return bp, cnt


def sign_stability(x, win, min_n):
    """Доля положительных среди последних `win` наблюдений."""
    return _trailing(x, win, min_n,
                     lambda s: np.nanmean((s > 0).astype(float), axis=1))


def oi_daily(t_sec, oi_usd, day0_sec, n_days, lag_sec=300):
    """Открытый интерес на конец дня — по моменту, когда он ИЗВЕСТЕН.

    Строка metrics с меткой t публикуется в t+5 минут (замер
    `l1_cascades/lag.py`, константа в `common/oi_metrics.py`). Точка
    относится ко дню момента ПУБЛИКАЦИИ: снимок 23:58 известен в 00:03
    следующего дня и принадлежать прошлому дню не имеет права — это
    было бы то же заглядывание, что убило первый прогон L1.
    """
    out = np.full(n_days, np.nan)
    known = np.asarray(t_sec, dtype=np.int64) + lag_sec
    d = (known - day0_sec) // DAY_SEC
    ok = (d >= 0) & (d < n_days)
    # Точки отсортированы по времени, и при повторяющихся индексах
    # присваивание оставляет ПОСЛЕДНЕЕ значение — это и есть «на конец
    # дня». Свойство закреплено тестом: полагаться на него молча нельзя.
    out[d[ok].astype(np.int64)] = np.asarray(oi_usd, dtype=np.float64)[ok]
    return out


def rel_change(x, k):
    """Относительное изменение за k дней; NaN без любого из концов."""
    out = np.full_like(x, np.nan)
    with np.errstate(all="ignore"):
        out[:, k:] = x[:, k:] / x[:, :-k] - 1.0
    out[~np.isfinite(out)] = np.nan
    return out


def forward_residual(close, r, elig, beta, h):
    """Цель обучения: форвард за h дней СВЕРХ рыночной волны, в б.п.

    Форвард строго вперёд: от закрытия дня t к закрытию дня t+h, ни
    один бар прошлого в него не входит (дефект R2 с окном на бар раньше
    ребаланса ловится тестом). Волна форварда — среднее форвардов по
    остальным, β — вчерашняя оценка, только прошлое.
    """
    fwd = np.full_like(close, np.nan)
    fwd[:, :-h] = close[:, h:] / close[:, :-h] - 1.0
    wf = wave_excl_self(fwd, elig)
    with np.errstate(all="ignore"):
        res = (fwd - beta * wf) * 1e4
    return res, fwd * 1e4


def feature_pack(close, turnover, traded_share, elig,
                 fund_bp=None, fund_cnt=None, oi_usd=None, age_days=None):
    """Все признаки спеки §4 разом: `{имя: матрица (символы, дни)}`.

    Одна точка сборки, чтобы тест на заглядывание проверял ВСЕ признаки
    одним проходом, а не каждый по отдельности: забытый в тесте признак
    — это дыра ровно того размера, что и забытый в коде сдвиг.
    """
    r = daily_returns(close)
    s_long = trailing_std(r, SIGMA_LONG, 20)
    s_short = trailing_std(r, SIGMA_SHORT, 5)
    turn_med = trailing_median(turnover, TURN_MED_WIN, 15)

    f = {}
    for k in RET_WINDOWS:
        f[f"ret_{k}"] = ret_norm(close, k, s_long)
    for k in PATH_WINDOWS:
        f[f"net_path_{k}"] = net_over_path(close, r, k)
    with np.errstate(all="ignore"):
        f["vol_ratio"] = s_short / s_long
        f["turn_rel"] = turnover / turn_med
        f["log_turn"] = np.log10(turn_med)
    f["traded_7"] = trailing_mean(traded_share, 7, 4)

    wave = wave_excl_self(r, elig)
    f["beta"] = rolling_beta(r, wave)

    if fund_bp is not None:
        f["f_day"] = fund_bp
        f["f_mean7"] = trailing_mean(fund_bp, FUND_MEAN_WIN, 4)
        f["f_sign7"] = sign_stability(fund_bp, FUND_MEAN_WIN, 4)
        cnt = np.where(fund_cnt > 0, fund_cnt, np.nan)
        f["f_regime"] = trailing_mean(cnt, FUND_REGIME_WIN, 15)
    if oi_usd is not None:
        with np.errstate(all="ignore"):
            f["oi_turn"] = oi_usd / turn_med
        f["d_oi_1"] = rel_change(oi_usd, 1)
        f["d_oi_7"] = rel_change(oi_usd, 7)
    if age_days is not None:
        # Возраст листинга (§4 п. 7 спеки 07) — в годах. Признак был
        # упущен первой сборкой и добавлен ДО первого прогона модели:
        # после просмотра результатов это была бы новая итерация.
        f["age"] = age_days / 365.25

    for k, v in f.items():
        v[~np.isfinite(v)] = np.nan
    return f
