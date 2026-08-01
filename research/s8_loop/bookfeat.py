#!/usr/bin/env python3
"""
S8.1, этап 2: признаки и цели из почасовых сводок — чистая математика.

Форма — матрицы `(символы, часы)`, как в M1 `(символы, дни)`; пропуск —
NaN, а не ноль; всё скользящее смотрит строго назад. Общие функции
(скользящие окна, волна без себя, β, форвардный остаток) берутся из
`m1_features/features.py` — они не привязаны к шагу сетки, и вторая
копия ядра запрещена правилами проекта.

Файл называется `bookfeat`, а не `features`: одноимённый модуль в
проекте уже есть (M1), и при обоих каталогах в sys.path импорт молча
возвращал бы САМ СЕБЯ вместо чужой математики. Этот класс дефекта уже
был (`nulls.py` в F3), и здесь его поймал первый же прогон тестов.
Математика M1 грузится по явному пути под несталкивающимся именем.

Цели — направление И путь (спека 08 §4): форвардный остаток к волне
плюс максимальный ход в пользу и против внутри горизонта. Геометрия
сделки учится на рыночных путях, где наблюдений миллионы, а не на
собственных сделках, где их десятки.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))
from book import BANDS                                     # noqa: E402

import importlib.util as _ilu                              # noqa: E402

_spec = _ilu.spec_from_file_location(
    "m1_features_math", os.path.join(RESEARCH, "m1_features",
                                     "features.py"))
F = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(F)

NORM_WIN, NORM_MIN = 168, 48      # неделя часов; меньше двух суток — NaN
SIGMA_WIN, SIGMA_MIN = 168, 48
BETA_WIN, BETA_MIN = 168, 96
HORIZONS = (1, 4, 24)             # часы, ось наблюдения (не перебирается)
MIN_SNAPS = 1800                  # полчаса снимков — иначе час не сечение
MIN_SECTION = 30


def rel_to_past(x, win=NORM_WIN, min_n=NORM_MIN):
    """x к своей скользящей медиане. Текущий час входит в окно — он
    известен в момент расчёта; будущее не входит (закреплено тестом)."""
    med = F.trailing_median(x, win, min_n)
    with np.errstate(all="ignore"):
        out = x / med
    out[~np.isfinite(out)] = np.nan
    return out


def imbalance(b, a):
    with np.errstate(all="ignore"):
        out = (b - a) / (b + a)
    out[~np.isfinite(out)] = np.nan
    return out


def eligibility(close, n_snap):
    """Час участвует в сечении, если книга писалась почти весь час.

    Порог по числу снимков, а не «файл есть»: недописанный час после
    перезапуска — это обрывок, и признак из него — выдумка (тот же
    класс, что замороженные ряды A2).
    """
    return np.isfinite(close) & (np.nan_to_num(n_snap) >= MIN_SNAPS)


def forward_path(close, high, low, h):
    """Максимальный ход в пользу/против за следующие h часов, в б.п.

    Путь собирается из почасовых максимумов и минимумов ВПЕРЁД от
    закрытия часа t: бары t+1 … t+h. Ни одна точка прошлого в него не
    входит (закреплено тестом «будущее не трогает прошлое» наоборот —
    прошлое не трогает форвард).
    """
    S, D = close.shape
    hi = np.full((S, D), -np.inf)
    lo = np.full((S, D), np.inf)
    # Требуется ПОЛНЫЙ путь: дыра в любом часе горизонта гасит цель.
    # Обрывок пути занижал бы и ход в пользу, и ход против, выглядя
    # «спокойным» ровно там, где запись рвалась, — тот же класс, что
    # замороженные ряды A2.
    ok = np.zeros((S, D), dtype=bool)
    ok[:, :D - h] = True
    for k in range(1, h + 1):
        end = D - k
        hh = high[:, k:]
        ll = low[:, k:]
        good = np.isfinite(hh) & np.isfinite(ll)
        ok[:, :end] &= good
        hi[:, :end] = np.maximum(hi[:, :end], np.where(good, hh, -np.inf))
        lo[:, :end] = np.minimum(lo[:, :end], np.where(good, ll, np.inf))
    with np.errstate(all="ignore"):
        mfe = (hi / close - 1.0) * 1e4
        mae = (lo / close - 1.0) * 1e4
    mfe[~ok] = np.nan
    mae[~ok] = np.nan
    mfe[~np.isfinite(mfe)] = np.nan
    mae[~np.isfinite(mae)] = np.nan
    return mfe, mae


def feature_pack(s):
    """Все признаки спеки 08 §3 разом из словаря матриц сводки.

    Одна точка сборки — тест на заглядывание проверяет все признаки
    одним проходом (правило M1).
    """
    close = s["mid_close"]
    r = F.daily_returns(close)                 # доходности час к часу
    elig = eligibility(close, s["n_snap"])

    f = {}
    for w in BANDS:
        b, a = s[f"bq_b{w}"], s[f"bq_a{w}"]
        f[f"depth_b{w}"] = rel_to_past(b)
        f[f"depth_a{w}"] = rel_to_past(a)
        f[f"imb_{w}"] = imbalance(b, a)
    f["imb_best"] = imbalance(s["best_b"], s["best_a"])
    f["spread_rel"] = rel_to_past(s["spread_bp"])
    f["upd_rel"] = rel_to_past(s["upd"])
    f["big_rel"] = rel_to_past(s["big_max"])

    turn = s["buy"] + s["sell"]
    f["turn_rel"] = rel_to_past(turn)
    f["delta"] = imbalance(s["buy"], s["sell"])
    f["burst"] = rel_to_past(s["vol_max_1s"])
    f["traded_share"] = s["traded_secs"] / 3600.0
    with np.errstate(all="ignore"):
        # выедено против показанного: агрессия ленты за час к показанной
        # глубине узкой полосы противоположной стороны
        f["eat_bid"] = s["sell"] / s["depth_eat_b"]
        f["eat_ask"] = s["buy"] / s["depth_eat_a"]

    sig = F.trailing_std(r, SIGMA_WIN, SIGMA_MIN)
    for k in (1, 4, 24):
        f[f"ret_{k}h"] = F.ret_norm(close, k, sig)
    f["net_path_24h"] = F.net_over_path(close, r, 24)

    wave = F.wave_excl_self(np.where(elig, r, np.nan), elig)
    f["beta"] = F.rolling_beta(r, wave, win=BETA_WIN, min_n=BETA_MIN)

    # Возраст: часы с первого записанного часа. Цензурирован началом
    # записи — у всех стартовых имён возраст одинаково растёт; честный
    # возраст листинга подставится из универсума на этапе вердикта.
    first = np.argmax(np.isfinite(close), axis=1).astype(float)
    none = ~np.isfinite(close).any(axis=1)
    idx = np.arange(close.shape[1], dtype=float)[None, :]
    age = (idx - first[:, None]) / 24.0
    age[age < 0] = np.nan
    age[none, :] = np.nan
    f["age_rec"] = age

    for v in f.values():
        v[~np.isfinite(v)] = np.nan
    return f, r, elig


def target_pack(s, r, elig, beta):
    """Цели: остаток к волне + путь, по каждому горизонту."""
    close = s["mid_close"]
    out = {}
    for h in HORIZONS:
        resid, _ = F.forward_residual(close, r, elig, beta, h)
        mfe, mae = forward_path(close, s["mid_high"], s["mid_low"], h)
        out[f"fwd_{h}h"] = resid
        out[f"mfe_{h}h"] = mfe
        out[f"mae_{h}h"] = mae
    return out
