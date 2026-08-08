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
# Свой каталог — явно: модуль грузят и по пути (сборщик), и тогда
# соседний `families` иначе не находится вовсе.
sys.path.insert(0, HERE)
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
# Горизонт сигнала: на нём книга торгует, и только на нём заведены
# производные цели (квантильный стоп, единицы собственной σ).
SIGNAL_H = 4

# Семейства признаков — вид СИТУАЦИИ словами владельца: выедение
# стакана, ликвидации, зажим, наклонка и так далее. Карта живёт в
# `families.py` — стандартная библиотека без numpy, потому что её
# читает ещё и веб-сервер справочника, а тянуть туда математику M1
# незачем. Копии здесь нет намеренно: две таблицы, решающие одно,
# однажды разойдутся, и новый признак молча падал бы в «прочее».
#
# Зачем: у модели нет дискретных стратегий — она одна на все ситуации.
# Но разложение вклада (`contrib`) говорит, какие признаки двигали
# ЭТОТ прогноз, и доминирующее семейство — честное имя ситуации:
# «прогноз стоит на ликвидациях», «на выедении стакана». Это чтение
# вкладов, а не выбор стратегии, и страница обязана подписывать его
# именно так.
from families import (FAMILY_EXACT, FAMILY_PREFIX,   # noqa: E402,F401
                      family)

MIN_SNAPS = 1800        # запасное правило для сводок старого образца
MIN_SPAN_SEC = 1800     # снимки обязаны накрывать полчаса из часа
MAX_GAP_SEC = 300       # дыра длиннее пяти минут — час не сечение
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


def eligibility(close, n_snap, span=None, gap=None):
    """Час участвует в сечении, если книга писалась почти весь час.

    Мера — ПОКРЫТИЕ ВО ВРЕМЕНИ, а не число снимков. Счёт снимков был
    прокси, молча предполагавшим ровно один снимок в секунду; на 540
    символах полный проход длится дольше, и полностью записанный час
    даёт 1200 снимков вместо 3600. Живой сервер показал цену этого
    предположения: сечений с ≥30 именами было РОВНО НОЛЬ при исправной
    записи, то есть модель не обучилась бы никогда.

    Требуется: снимки накрывают не меньше половины часа и нет дыры
    длиннее пяти минут. Обрывок после перезапуска так же не проходит
    (у него мал охват), а редкая сетка — проходит, и правильно.

    Сводки старого образца охвата не несут — для них остаётся прежнее
    правило по числу: пропуск полей не вправе молча открывать ворота.
    """
    ok = np.isfinite(close)
    if span is None or gap is None:
        return ok & (np.nan_to_num(n_snap) >= MIN_SNAPS)
    have = np.isfinite(span) & np.isfinite(gap)
    cover = have & (np.nan_to_num(span) >= MIN_SPAN_SEC) \
        & (np.nan_to_num(gap, nan=1e9) <= MAX_GAP_SEC)
    old = ~have & (np.nan_to_num(n_snap) >= MIN_SNAPS)
    return ok & (cover | old)


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


def rolling_extreme(x, win, fn):
    """Скользящий максимум/минимум за последние win часов, только назад."""
    S, D = x.shape
    out = np.full((S, D), np.nan)
    for t in range(D):
        a = max(0, t - win + 1)
        sl = x[:, a:t + 1]
        ok = np.isfinite(sl).all(axis=1) & (t - a + 1 == win)
        if ok.any():
            v = fn(sl, axis=1)
            out[ok, t] = v[ok]
    return out


def formations(s):
    """Формации владельца (зажимка, наклонка, проторговка) — числами.

    Идея из практики команды владельца (2026-08-02): сжатие диапазона у
    уровня, наклонное сжатие и набор в диапазоне. Здесь они не правила
    входа, а ПРИЗНАКИ: модель сама выучит, какие и в каких сочетаниях
    несут ожидание. Контекст честности: T3/T4 измерили уровни БЕЗ
    условия сжатия — исходы легли на случайность; сжатие как условие —
    непроверенное место, потому и признак.
    """
    close, hi, lo = s["mid_close"], s["mid_high"], s["mid_low"]
    f = {}
    for k in (4, 24):
        rng = rolling_extreme(hi, k, np.nanmax) -             rolling_extreme(lo, k, np.nanmin)
        with np.errstate(all="ignore"):
            rng_rel = rng / close                      # ход окна в долях
            # зажим: диапазон окна к своему обычному; < 1 — сжатие
            f[f"squeeze_{k}h"] = rng_rel / F.trailing_median(
                rng_rel, NORM_WIN, NORM_MIN)
        if k == 4:
            net = np.full_like(close, np.nan)
            net[:, k:] = close[:, k:] - close[:, :-k]
            with np.errstate(all="ignore"):
                # наклонка: чистый ход в долях диапазона, знак — наклон
                f["tilt_4h"] = net / rng
    rng24 = rolling_extreme(hi, 24, np.nanmax) -         rolling_extreme(lo, 24, np.nanmin)
    with np.errstate(all="ignore"):
        # место в суточном диапазоне: 0 — у низа, 1 — у верха
        f["range_pos"] = (close - rolling_extreme(lo, 24, np.nanmin)) / rng24
    # проторговка: сколько из 24 часов закрывались внутри текущего
    # 4-часового коридора — время у цены, а не объём (объём отдельно)
    rng4 = rolling_extreme(hi, 4, np.nanmax) -         rolling_extreme(lo, 4, np.nanmin)
    S, D = close.shape
    dwell = np.full((S, D), np.nan)
    for t in range(24, D):
        past = close[:, t - 24:t]
        okp = np.isfinite(past).all(axis=1) & np.isfinite(close[:, t])             & np.isfinite(rng4[:, t])
        half = rng4[:, t] / 2.0
        inside = (np.abs(past - close[:, t][:, None])
                  <= half[:, None]).mean(axis=1)
        dwell[okp, t] = inside[okp]
    f["dwell_24h"] = dwell
    for v in f.values():
        v[~np.isfinite(v)] = np.nan
    return f


def _opt(s, key, like):
    """Матрица сводки, которой может не быть (поле добавлено позже
    начала записи): нет — весь ряд NaN, признак честно пуст."""
    v = s.get(key)
    return v if v is not None else np.full_like(like, np.nan)


def lagged_change(x, k):
    """x[t]/x[t−k] − 1; дыра в любом конце — NaN, а не склейка."""
    out = np.full_like(x, np.nan)
    with np.errstate(all="ignore"):
        out[:, k:] = x[:, k:] / x[:, :-k] - 1.0
    out[~np.isfinite(out)] = np.nan
    return out


def clock_features(s, like):
    """Час суток и день недели из начала часа — сезонность.

    Час — синусом и косинусом, чтобы 23:00 и 00:00 были соседями, а
    не краями шкалы; день недели — числом 0–6, деревьям этого
    достаточно, а у сети берёт на себя стандартизация.
    """
    ts = s.get("hour_ts")
    if ts is None:
        nanm = np.full_like(like, np.nan)
        return {"hod_sin": nanm, "hod_cos": nanm.copy(),
                "dow": nanm.copy()}
    hod = (ts / 3600.0) % 24
    dow = (ts / 86400.0 + 3) % 7            # эпоха — четверг; 0 — Пн
    return {"hod_sin": np.sin(2 * np.pi * hod / 24),
            "hod_cos": np.cos(2 * np.pi * hod / 24),
            "dow": np.floor(dow)}


def leader_features(s, close):
    """Ход BTC и своего сектора за 4 часа — запаздывание за лидером.

    Сектор берёт среднее по СВОИМ без себя (как волна): включить себя
    значило бы подмешать собственный ход в «чужой» признак. Меньше
    трёх соседей — NaN: среднее двух имён не сектор, а сосед.
    """
    S, D = close.shape
    r4 = lagged_change(close, 4)
    out = {}
    is_btc = s.get("is_btc")
    if is_btc is not None and np.nansum(is_btc) == 1:
        bi = int(np.argmax(is_btc[:, 0]))
        out["btc_ret_4h"] = np.tile(r4[bi], (S, 1))
    else:
        out["btc_ret_4h"] = np.full((S, D), np.nan)
    sec = s.get("sector")
    sec_ret = np.full((S, D), np.nan)
    if sec is not None:
        codes = sec[:, 0]
        for c in np.unique(codes[np.isfinite(codes)]):
            rows = np.where(codes == c)[0]
            if len(rows) < 4:
                continue
            g = r4[rows]
            fin = np.isfinite(g)
            n = fin.sum(axis=0)
            tot = np.where(fin, g, 0.0).sum(axis=0)
            with np.errstate(all="ignore"):
                excl = (tot[None, :] - np.where(fin, g, 0.0)) \
                    / (n[None, :] - fin)
            excl[(n[None, :] - fin) < 3] = np.nan
            sec_ret[rows] = excl
    out["sec_ret_4h"] = sec_ret
    with np.errstate(all="ignore"):
        out["rel_sec_4h"] = r4 - sec_ret
    return out


def dist_round(close):
    """Близость к круглому числу в долях шага круглой сетки, 0…0.5.

    Шаг — на порядок ниже разряда цены: у BTC на 90 000 это 1 000, у
    монеты на 0.05 — 0.001. Мера безразмерна и не зависит от того, во
    сколько знаков площадка котирует тикер.
    """
    with np.errstate(all="ignore"):
        step = np.power(10.0, np.floor(np.log10(close)) - 1.0)
        x = close / step
        d = np.abs(x - np.round(x))
    d[~np.isfinite(d)] = np.nan
    return d


def feature_pack(s):
    """Все признаки спеки 08 §3 разом из словаря матриц сводки.

    Одна точка сборки — тест на заглядывание проверяет все признаки
    одним проходом (правило M1). Пакеты, добавленные решением
    владельца 2026-08-02 (до первого обучения): время, funding/интерес/
    ликвидации, режим волатильности, лидер и сектор, круглые числа.
    """
    close = s["mid_close"]
    r = F.daily_returns(close)                 # доходности час к часу
    elig = eligibility(close, s["n_snap"],
                       s.get("snap_span_sec"), s.get("snap_gap_max_sec"))

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
    with np.errstate(all="ignore"):
        # день к неделе: >1 — рынок у монеты проснулся, <1 — заснул
        f["vol_regime"] = F.trailing_std(r, 24, 12) / sig

    # --- funding / интерес / базис / ликвидации (запись с 2026-08) ---
    fr = _opt(s, "fr", close)
    f["fr_bp"] = fr * 1e4
    f["mins_fund"] = _opt(s, "mins_fund", close)
    oi = _opt(s, "oi_usd", close)
    f["oi_rel"] = rel_to_past(oi)
    f["oi_chg_4h"] = lagged_change(oi, 4)
    f["oi_chg_24h"] = lagged_change(oi, 24)
    f["basis_bp"] = _opt(s, "basis_bp", close)
    liq_l = _opt(s, "liq_long", close)
    liq_s = _opt(s, "liq_short", close)
    with np.errstate(all="ignore"):
        # доля принудительных в обороте часа: безразмерна, сравнима
        # между монетами; ноль — законное наблюдение «никого не выбило»
        f["liq_long_share"] = liq_l / turn
        f["liq_short_share"] = liq_s / turn
    f["liq_imb"] = imbalance(liq_s, liq_l)

    # --- время, лидер/сектор, круглые числа --------------------------
    f.update(clock_features(s, close))
    f.update(leader_features(s, close))
    f["dist_round"] = dist_round(close)

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

    f.update(formations(s))
    for v in f.values():
        v[~np.isfinite(v)] = np.nan
    return f, r, elig


def target_pack(s, r, elig, beta):
    """Цели: остаток к волне + путь, по каждому горизонту.

    Рядом с сырыми — те же цели в единицах СОБСТВЕННОЙ волатильности
    монеты (суффикс `_z`), только на горизонте сигнала.

    Зачем, и это найдено замером, а не вкусом: признаки уже нормированы
    (`ret_*` делятся на `σ·√k`), а цели были в сырых базисных пунктах —
    асимметрия, из-за которой «предсказанный ход» у бешеной монеты
    больше просто потому, что она бешеная. Живой замер отбора: размах
    выбранной моделью монеты равен 6.1 медианы сечения, 86 % выборов
    выше медианы. То есть ранжирование по прогнозу частично есть
    ранжирование по волатильности.

    Делитель — `σ·√h`, ровно тот же, что у признаков: другая шкала
    сделала бы цель несравнимой с ними, и «в единицах σ» означало бы
    у цели одно, а у признака другое.

    Сырые цели остаются и не меняются ни на бит: книга на них торгует,
    и вердикт выносится сравнением двух ранжирований на одних часах, а
    не подменой одного другим.
    """
    close = s["mid_close"]
    r_sig = F.trailing_std(r, SIGMA_WIN, SIGMA_MIN)
    out = {}
    for h in HORIZONS:
        resid, _ = F.forward_residual(close, r, elig, beta, h)
        mfe, mae = forward_path(close, s["mid_high"], s["mid_low"], h)
        out[f"fwd_{h}h"] = resid
        out[f"mfe_{h}h"] = mfe
        out[f"mae_{h}h"] = mae
        if h != SIGNAL_H:
            continue
        # Цели в б.п., σ — в долях: множитель 1e4 приводит их к одной
        # единице. Без него «в сигмах» вышло бы в десять тысяч раз
        # больше, и порог на такую цель значил бы не то, что написано.
        with np.errstate(all="ignore"):
            den = r_sig * np.sqrt(float(h)) * 1e4
            for k, v in (("fwd", resid), ("mfe", mfe), ("mae", mae)):
                z = v / den
                z[~np.isfinite(z)] = np.nan
                out[f"{k}_{h}h_z"] = z
    return out
