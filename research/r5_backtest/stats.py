#!/usr/bin/env python3
"""
R5 — статистическая валидация. Ядро расчёта.

Спека 03 §8.3, критерии 6–8; спека 02 §7. Здесь только арифметика по ряду
доходностей: Sharpe, поправка на число испытаний, просадка, подпериоды.

Определение поправки Sharpe закрепляется здесь
----------------------------------------------

Спека утвердила **порог** (0.8), но не **способ** поправки, и это пробел.
Способ фиксируется до прогона и докладываются обе общепринятые версии,
чтобы выбор определения нельзя было подогнать под результат:

1. **Sharpe за вычетом ожидаемого максимума под нулём** —
   `SR − SR₀(N)`, где `SR₀` есть тот Sharpe, который лучшая из `N`
   пустышек показала бы чистой случайностью. Величина в тех же
   единицах, что и порог, поэтому вердикт §8.3 п. 6 выносится по ней.

2. **Deflated Sharpe Ratio** (Bailey, López de Prado) — вероятность
   того, что истинный Sharpe положителен, с учётом числа испытаний,
   длины ряда, асимметрии и тяжести хвостов. Величина безразмерная,
   поэтому порогом 0.8 не проверяется, но приводится рядом: у ряда с
   тяжёлыми хвостами она падает там, где обычный Sharpe этого не
   показывает, а хвосты у нас именно тяжёлые (отдельные сечения от
   −2006 до +2608 б.п.).

Ожидаемый максимум под нулём (Bailey, López de Prado 2014):

    SR₀ ≈ σ_SR · [ (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ]

где `σ_SR` — разброс Sharpe по испытаниям, γ ≈ 0.5772 (постоянная
Эйлера — Маскерони). Смысл прост: если перебрать 96 вариантов, лучший
из них покажет заметный Sharpe даже когда эджа нет вовсе, и вычесть эту
величину обязательно.
"""

import math

EULER = 0.5772156649015329


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Обратная функция нормального распределения, метод Акклама.

    Своя реализация, а не scipy: весь стенд держится на стандартной
    библиотеке и numpy, и тащить scipy ради одной функции незачем.
    Точность около 1e-9 — на порядки больше, чем нужно для порога.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p вне (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= ph:
        q = p - 0.5
        r = q * q
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
            (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    # Один шаг Ньютона — доводит точность до предела double.
    e = norm_cdf(x) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def moments(v):
    n = len(v)
    if n < 2:
        return None
    m = sum(v) / n
    var = sum((x - m) ** 2 for x in v) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    # Вырожденный ряд даёт не ноль, а остаток округления: у постоянного
    # ряда из 0.01 дисперсия выходит порядка 1e-36, корень 1e-18, и
    # отношение среднего к нему — 4.5e16. Такое число не падает и не
    # выглядит подозрительно в таблице, поэтому порог явный.
    if sd <= 1e-12 * max(abs(m), 1e-12):
        return {"n": n, "mean": m, "sd": 0.0, "skew": 0.0, "kurt": 3.0}
    s3 = sum(((x - m) / sd) ** 3 for x in v) / n
    s4 = sum(((x - m) / sd) ** 4 for x in v) / n
    return {"n": n, "mean": m, "sd": sd, "skew": s3, "kurt": s4}


def sharpe(v, periods_per_year):
    """Годовой Sharpe по ряду доходностей за период."""
    m = moments(v)
    if not m or m["sd"] <= 0:
        return None
    return (m["mean"] / m["sd"]) * math.sqrt(periods_per_year)


def expected_max_sharpe(n_trials, sr_std):
    """Sharpe, который лучшая из `n_trials` пустышек даст случайностью."""
    if n_trials < 2 or sr_std <= 0:
        return 0.0
    a = norm_ppf(1.0 - 1.0 / n_trials)
    b = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return sr_std * ((1.0 - EULER) * a + EULER * b)


def deflated_sharpe(v, periods_per_year, n_trials, sr_std):
    """Обе версии поправки. Возвращает словарь, ничего не выбирая.

    `sr_ann` и `sr0_ann` — в годовых единицах, чтобы сравниваться с
    порогом 0.8 напрямую. `dsr` — вероятность, безразмерная.
    """
    m = moments(v)
    if not m or m["sd"] <= 0:
        return None
    sr_per = m["mean"] / m["sd"]                    # Sharpe за период
    scale = math.sqrt(periods_per_year)
    sr0_ann = expected_max_sharpe(n_trials, sr_std)
    sr0_per = sr0_ann / scale

    # Deflated Sharpe Ratio: знаменатель учитывает асимметрию и хвосты.
    n = m["n"]
    denom = 1.0 - m["skew"] * sr_per + (m["kurt"] - 1.0) / 4.0 * sr_per ** 2
    dsr = None
    if denom > 0 and n > 1:
        z = (sr_per - sr0_per) * math.sqrt(n - 1) / math.sqrt(denom)
        dsr = norm_cdf(z)
    return {"sharpe_annual": sr_per * scale,
            "sr0_annual": sr0_ann,
            "sharpe_deflated": sr_per * scale - sr0_ann,
            "dsr_probability": dsr,
            "skew": m["skew"], "kurtosis": m["kurt"], "periods": n}


def max_drawdown(v):
    """Максимальная просадка кривой эквити, построенной сложением.

    Доходности складываются как `∏(1+r)`, а не суммируются: при малых
    величинах разница мала, но просадка — величина о потере капитала, и
    считать её надо так же, как считает счёт.
    """
    eq = 1.0
    peak = 1.0
    worst = 0.0
    curve = []
    for r in v:
        eq *= (1.0 + r)
        curve.append(eq)
        peak = max(peak, eq)
        worst = min(worst, eq / peak - 1.0)
    return {"max_drawdown": worst, "final_equity": eq, "curve": curve}


def split_by_year(dates, v):
    """Ряд, разложенный по календарным годам."""
    out = {}
    for d, x in zip(dates, v):
        out.setdefault(d[:4], []).append(x)
    return out


def split_equal(v, parts):
    """Ряд, разрезанный на равные куски — подпериоды без привязки к дате."""
    n = len(v)
    if n < parts:
        return {}
    step = n // parts
    return {f"{i + 1}/{parts}": v[i * step:(i + 1) * step if i < parts - 1
                                  else n]
            for i in range(parts)}
