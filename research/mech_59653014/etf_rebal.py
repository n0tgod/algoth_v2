#!/usr/bin/env python3
"""
Ребаланс плечевых крипто-ETF в последний час Нью-Йорка: ядро механики.

Что утверждается
----------------

Фонд с дневным целевым плечом L и активами A обязан к расчёту стоимости
пая (16:00 Нью-Йорка) изменить экспозицию на A·L·(L−1)·r, где r — ход
базового актива за день фонда; для L = 2 это 2·A·r, и знак совпадает со
знаком хода дня. Обратный фонд (L = −1) торгует в ту же сторону:
(−1)·(−2) = +2. Экспозиция держится фьючерсами CME или свопами, хедж
свопов идёт во фьючерс, базисные столы держат фьючерс против перпов —
поток доходит до перпа в те же минуты.

Отсюда гипотеза: в час 15:00 → 16:00 Нью-Йорка перп идёт в сторону хода
дня, взятого от 16:00 предыдущего дня фонда к 15:00 сегодняшнего; эффект
есть только в дни работы американского рынка, только после запуска фонда
на имя, только в этот час, и он не меньше круга одной ноги.

Сделка, если гипотеза жива: в 15:00 позиция по знаку хода дня при
|ход дня| ≥ 2 %, выход в 16:00 ПО ЧАСАМ, без стопа и тейка, размер по σ
часа. Пороги объявлены заявкой ДО расчёта и здесь только записаны
числами (`QUAL_ABS_R`, `MIN_QUAL_DAYS`, `K*`), ни один из них этим
модулем не подбирается.

Сигнал и исполнение — разные цены, и это не косметика
-----------------------------------------------------

`sig_price(t)` — закрытие минуты, ЗАКОНЧИВШЕЙСЯ в t: последняя цена,
известная строго до t. `fill_price(t)` — открытие минуты, НАЧИНАЮЩЕЙСЯ в
t: первая цена после t. Ход дня и размер позиции считаются только по
`sig_price`, исполняется сделка только по `fill_price`. На этом
разделении стоит проверка на заглядывание в будущее: переписать всё, что
после 15:00, — ход дня, признак квалификации и σ̂ шелохнуться не должны.

Четыре категории дня, и ни одна не сваливается в другую
-------------------------------------------------------

Календарь ведёт `nyse_cal.py`. Полная сессия закрывается в 16:00, ранняя
— в 13:00, и в ранний день часа 15–16 у фонда не существует вовсе:
такие дни ИСКЛЮЧЕНЫ отдельной категорией, а не смешаны с обычными.
Исключён и день, чей предыдущий день фонда был ранним: у него точка
отсчёта хода дня лежит в 13:00, а не в 16:00. Оба исключения считаются и
печатаются числом — «не измерено» ≠ ноль.

Час-вердикт есть частный случай общей машины
--------------------------------------------

K3 требует тот же расчёт для каждого из 24 часов суток. Поэтому замер
написан как сдвиг часов: сигнал в h:00, выход в (h+1):00, точка отсчёта
— (h+1):00 предыдущего дня фонда. При h = 15 это ровно измеряемая
сделка, и `day_table` при h = 15 обязана давать те же числа, что час
15–16 в K3, — иначе вердикт мерился бы одним кодом, а контроль другим.

Все деньги считаются на брутто-ходе, круг издержек берётся ОДИН —
`research/s8_loop/trades.ROUND_COST_BP`. Второй копии этого числа здесь
нет.
"""

import datetime as dt
import math
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))

import bars as BR                                            # noqa: E402
import nyse_cal as CAL                                       # noqa: E402
from trades import ROUND_COST_BP                             # noqa: E402

ET = ZoneInfo("America/New_York")
MIN_MS = BR.MIN_MS
HOUR_MS = 3_600_000

# --- пороги, объявленные заявкой ДО расчёта ---------------------------

# Квалификация суток: |ход дня| не меньше двух процентов.
QUAL_ABS_R = 0.02
# Меньше этого числа квалифицированных дней — «не измерено», не вердикт.
MIN_QUAL_DAYS = 200
# K1: круг ОДНОЙ ноги. Число живёт в расчётном ядре проекта, и второй
# копии у него быть не должно.
K1_FLOOR_BP = ROUND_COST_BP
# K2 и K4: разность окон и разность календарей значима при t ≥ 2.
K2_MIN_T = 2.0
K4_MIN_T = 2.0
# K3: час-вердикт обязан быть выше p95 распределения по остальным часам.
K3_PCT = 95.0
VERDICT_HOUR = 15
# K5: наклон хода со знаком на |ход дня| обязан быть положительным.
K5_MIN_SLOPE = 0.0

# Бутстрап по дням: дни независимы, перекрытия здесь нет.
BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260928

# Размер позиции: доля депозита = min(1, целевой риск / σ̂ часа).
RISK_PER_HOUR = 0.005
SIGMA_LOOKBACK_MIN = 1440
# Ниже этого покрытия окна σ̂ — ПРОЧЕРК, а не «σ маленькая». Обратная
# волатильность без пола есть замороженный ряд в новом костюме.
SIGMA_MIN_MINUTES = 1200

# Окна. Даты запуска фондов объявлены заявкой и сверяются `fund_dates.py`
# по страницам фондов; сверенная дата побеждает названную, и обе
# печатаются отчётом.
FUND_START_DECLARED = {
    "BTCUSDT": dt.date(2023, 6, 27),
    "ETHUSDT": dt.date(2024, 6, 4),
}
FUND_END = dt.date(2026, 9, 25)
PLACEBO_LO = dt.date(2021, 1, 1)
PLACEBO_HI = dt.date(2023, 6, 26)

REF_PREV_SESSION = "prev_session"
REF_PREV_CALENDAR = "prev_calendar"

UNMEASURED = "не измерено"
DEAD = "мертво"
ALIVE = "жив"


# --- время ------------------------------------------------------------

def et_instant(day, hour):
    """Момент (мс UTC) стенных часов Нью-Йорка `hour:00` на `day`.

    `hour` может быть 24 и больше — это следующие календарные сутки.

    Возвращает None, когда таких стенных часов не существует или их
    два: в час перехода на летнее время 02:00 не наступает вовсе, а при
    возврате на зимнее 01:00 наступает дважды. Выдумать, который из двух
    имелся в виду, нельзя, поэтому такой час — прочерк с причиной, а не
    молчаливый выбор первого.
    """
    d = day + dt.timedelta(days=hour // 24)
    h = hour % 24
    naive = dt.datetime(d.year, d.month, d.day, h)
    a = naive.replace(tzinfo=ET)
    b = naive.replace(tzinfo=ET, fold=1)
    if a.timestamp() != b.timestamp():
        return None                                  # час неоднозначен
    back = a.astimezone(dt.timezone.utc).astimezone(ET)
    if (back.hour, back.minute) != (h, 0):
        return None                                  # часа не существует
    return int(a.timestamp() * 1000)


def sig_price(b, ms):
    """Цена сигнала: последняя цена, известная строго ДО момента `ms`."""
    return None if ms is None else b.at_close(ms)


def fill_price(b, ms):
    """Цена исполнения: первая цена ПОСЛЕ момента `ms`."""
    return None if ms is None else b.at_open(ms)


# --- размер позиции ---------------------------------------------------

def sigma_hour(b, ms):
    """Реализованная σ минутных ходов за сутки до `ms`, приведённая к часу.

    Окно задано ВО ВРЕМЕНИ, а не в номерах баров: «точка есть» ловит не
    всё, и ряд с дырой иначе набрал бы сутки из двух суток. Покрытия
    меньше `SIGMA_MIN_MINUTES` — прочерк, не ноль.
    """
    if ms is None:
        return None
    a, z = b.window(ms - SIGMA_LOOKBACK_MIN * MIN_MS, ms)
    if z - a < SIGMA_MIN_MINUTES:
        return None
    px = b.close[a:z]
    if px.size < 2 or float(px.min()) <= 0:
        return None
    r = np.diff(np.log(px))
    s = float(r.std(ddof=1))
    if not math.isfinite(s) or s <= 0:
        return None
    return s * math.sqrt(60.0)


def size_frac(sig_h):
    """Доля депозита в нотионале: min(1, риск на час / σ̂ часа).

    Потолок ОБЯЗАТЕЛЕН: без него тихий час даёт плечо в десятки раз, и
    хвост книги оказывается плечом, а не сигналом — это ровно то, чем
    объяснились короткие DCA-книги. Прочерк σ̂ — прочерк размера.
    """
    if sig_h is None or sig_h <= 0:
        return None
    return min(1.0, RISK_PER_HOUR / sig_h)


# --- строка дня -------------------------------------------------------

def hour_row(b, cal, day, hour=VERDICT_HOUR, ref_mode=REF_PREV_SESSION,
             with_extras=True):
    """Один день при сдвиге часов `hour`. Возвращает (строка, причина).

    Ровно одно из двух непусто. Причина отказа НАЗВАНА всегда: день,
    выпавший молча, превратил бы пропуск в ноль.
    """
    kind = cal.kind(day)
    if ref_mode == REF_PREV_SESSION:
        if kind == CAL.EARLY:
            return None, "ранняя сессия: пай считают к 13:00"
        if kind != CAL.TRADE:
            return None, f"неторговый день ({kind})"
        ref_day = cal.prev_session(day)
        if ref_day is None:
            return None, "нет предыдущего дня фонда в календаре"
        if cal.kind(ref_day) == CAL.EARLY:
            return None, "предыдущий день фонда — ранняя сессия"
    else:
        if kind in (CAL.TRADE, CAL.EARLY):
            return None, f"день с сессией ({kind})"
        ref_day = day - dt.timedelta(days=1)

    t_ref = et_instant(ref_day, hour + 1)
    t_sig = et_instant(day, hour)
    t_out = et_instant(day, hour + 1)
    if t_ref is None or t_sig is None or t_out is None:
        return None, "переход летнего/зимнего времени: часа нет или их два"

    p_ref = sig_price(b, t_ref)
    p_sig = sig_price(b, t_sig)
    if p_ref is None or p_sig is None or p_ref <= 0 or p_sig <= 0:
        return None, "нет минуты для хода дня"
    p_in = fill_price(b, t_sig)
    p_out = fill_price(b, t_out)
    if p_in is None or p_out is None or p_in <= 0 or p_out <= 0:
        return None, "нет минуты для входа или выхода"

    r_day = p_sig / p_ref - 1.0
    sign = 1.0 if r_day > 0 else (-1.0 if r_day < 0 else 0.0)
    move = p_out / p_in - 1.0
    row = {
        "day": day.isoformat(), "kind": kind, "hour": hour,
        "ref_day": ref_day.isoformat(),
        "r_day": r_day, "sign": sign,
        "move_bp": move * 1e4,
        "signed_bp": sign * move * 1e4,
        "qual": abs(r_day) >= QUAL_ABS_R,
    }
    if with_extras:
        row.update(_extras(b, day, hour, sign, t_sig, t_out))
    return row, None


def _extras(b, day, hour, sign, t_sig, t_out):
    """Столбцы, которые вердикта не выносят: полчаса, откат, размер, лента."""
    out = {}
    t_half = t_sig + 30 * MIN_MS
    p_half, p_out = fill_price(b, t_half), fill_price(b, t_out)
    out["signed_half_bp"] = (None if p_half is None or p_out is None
                             else sign * (p_out / p_half - 1.0) * 1e4)
    t_next = et_instant(day, hour + 2)
    p_next = fill_price(b, t_next) if t_next is not None else None
    p_in_next = fill_price(b, t_out)
    out["signed_after_bp"] = (None if p_next is None or p_in_next is None
                              else sign * (p_next / p_in_next - 1.0) * 1e4)
    s = sigma_hour(b, t_sig)
    out["sigma_hour"] = s
    out["size_frac"] = size_frac(s)
    out["aggr_signed_pp"] = aggressor_signed_pp(b, t_sig, t_out, sign)
    out["usd_volume"] = usd_volume(b, t_sig, t_out)
    return out


def aggressor_signed_pp(b, t0, t1, sign):
    """Перевес агрессора-покупателя в окне, со знаком хода дня, в п.п.

    Источник — поле `taker_buy_volume` минутного архива Binance: это
    объём, инициированный покупателем. Отпечаток потока, не убийца.
    Нулевого объёма в окне не бывает у мажора, но если он нулевой —
    прочерк, а не 0.5: «не измерено» ≠ ноль.
    """
    if t0 is None or t1 is None or sign == 0:
        return None
    a, z = b.window(t0, t1)
    if z <= a:
        return None
    v = float(b.volume[a:z].sum())
    if v <= 0:
        return None
    share = float(b.taker_buy[a:z].sum()) / v
    return sign * (share - 0.5) * 100.0


def usd_volume(b, t0, t1):
    """Оборот окна в долларах: объём минуты на её цену. Пусто — прочерк.

    Нужно для одной строки отчёта: поток фонда 2·A·|r| против того, во
    что он приходит. Само по себе вердикта не выносит, но отвечает на
    вопрос «почему не видно» числом, а не словами.
    """
    if t0 is None or t1 is None:
        return None
    a, z = b.window(t0, t1)
    if z <= a:
        return None
    return float((b.volume[a:z] * b.close[a:z]).sum())


def day_table(b, cal, days, hour=VERDICT_HOUR, ref_mode=REF_PREV_SESSION,
              with_extras=True):
    """Строки по списку дней. Ноль строк при непустом входе — ОТКАЗ.

    Пустота не вправе выдавать себя за результат: отчёт с прочерками на
    сломанной загрузке неотличим от «эффекта нет», и это уже случалось
    дважды. Поэтому здесь исключение, а не пустой список.
    """
    rows, skips = [], {}
    for d in days:
        row, why = hour_row(b, cal, d, hour, ref_mode, with_extras)
        if row is None:
            skips[why] = skips.get(why, 0) + 1
        else:
            rows.append(row)
    if days and not rows:
        raise ValueError(
            f"{b.symbol}: из {len(days)} дней не построилось ни одной строки "
            f"(час {hour}, {ref_mode}); причины: {skips} — это отказ "
            "замера, а не отсутствие эффекта")
    return rows, skips


def qualified(rows):
    """Квалифицированные строки: |ход дня| ≥ порога и знак не ноль."""
    return [r for r in rows if r["qual"] and r["sign"] != 0]


# --- статистика -------------------------------------------------------

def stat(values):
    """Среднее, t по наблюдениям, бутстрап-интервал. Пусто — прочерк.

    t считается по ДНЯМ: наблюдений столько, сколько независимых дней, и
    раздувать их частотой замера нечем — окно одно на день.
    """
    v = np.asarray([x for x in values if x is not None], dtype=np.float64)
    if v.size == 0:
        return {"n": 0, "mean": None, "t": None, "lo": None, "hi": None,
                "sd": None, "median": None}
    m = float(v.mean())
    sd = float(v.std(ddof=1)) if v.size > 1 else None
    t = (None if not sd or v.size < 2 or sd <= 0
         else m / (sd / math.sqrt(v.size)))
    lo = hi = None
    if v.size > 1:
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        draws = rng.integers(0, v.size, size=(BOOTSTRAP, v.size))
        means = v[draws].mean(axis=1)
        lo, hi = (float(x) for x in np.percentile(means, [2.5, 97.5]))
    return {"n": int(v.size), "mean": m, "t": t, "lo": lo, "hi": hi,
            "sd": sd, "median": float(np.median(v))}


def welch_t(a, b):
    """t разности средних двух независимых выборок. Мало данных — прочерк."""
    x = np.asarray([v for v in a if v is not None], dtype=np.float64)
    y = np.asarray([v for v in b if v is not None], dtype=np.float64)
    if x.size < 2 or y.size < 2:
        return None, None
    d = float(x.mean() - y.mean())
    se = math.sqrt(x.var(ddof=1) / x.size + y.var(ddof=1) / y.size)
    return d, (None if se <= 0 else d / se)


def slope_on_abs_r(rows):
    """Наклон хода со знаком (б.п.) на |ход дня| (%) и его t.

    Знак наклона и есть содержание K5: поток фонда равен 2·A·r, значит
    выплата обязана РАСТИ с величиной хода дня. Плоская линия означает,
    что мерится что-то другое.
    """
    x = np.asarray([abs(r["r_day"]) * 100.0 for r in rows], dtype=np.float64)
    y = np.asarray([r["signed_bp"] for r in rows], dtype=np.float64)
    if x.size < 3 or float(x.std()) <= 0:
        return {"slope": None, "t": None, "n": int(x.size)}
    xm, ym = float(x.mean()), float(y.mean())
    sxx = float(((x - xm) ** 2).sum())
    beta = float(((x - xm) * (y - ym)).sum()) / sxx
    resid = y - (ym + beta * (x - xm))
    dof = x.size - 2
    s2 = float((resid ** 2).sum()) / dof
    se = math.sqrt(s2 / sxx) if sxx > 0 and s2 > 0 else None
    return {"slope": beta, "t": (None if not se else beta / se),
            "n": int(x.size)}


# --- калибровочная пара -----------------------------------------------

def plant_bars(b, cal, days, bp=30.0, frac=0.5, seed=7, shape="flat",
               hour=VERDICT_HOUR):
    """Подсадить ход `bp` б.п. в час h → h+1 на доле `frac` квалифицированных
    дней, ПРЯМО В ЦЕНЫ. Возвращает (новый ряд, число подсаженных дней).

    Подсадка живёт в ценах, а не в таблице дней, намеренно: калибровка
    обязана проверять и загрузку тоже. Сломанный читатель архива иначе
    выглядел бы ровно как «эффекта нет».

    Форма `flat` — плюс `bp` на каждом подсаженном дне; форма `prop` —
    плюс `bp`·|r|/среднее|r|, то есть ∝ |r|, как и требует сам механизм
    (ΔE = 2·A·r). Разница существенна для K5: ровная подсадка наклона на
    |r| НЕ создаёт, поэтому пройти K5 обязана именно `prop`.
    """
    rows, _ = day_table(b, cal, days, hour, with_extras=False)
    qs = qualified(rows)
    if not qs:
        raise ValueError("подсаживать некуда: квалифицированных дней нет")
    rng = np.random.default_rng(seed)
    pick = rng.permutation(len(qs))[: max(1, int(round(frac * len(qs))))]
    mean_abs = float(np.mean([abs(r["r_day"]) for r in qs]))
    op = b.open.copy()
    n = 0
    for i in pick:
        r = qs[int(i)]
        d = dt.date.fromisoformat(r["day"])
        j = b.index(et_instant(d, hour + 1))
        if j is None:
            continue
        k = bp if shape == "flat" else bp * abs(r["r_day"]) / mean_abs
        op[j] = op[j] * (1.0 + r["sign"] * k / 1e4)
        n += 1
    if not n:
        raise ValueError("подсадка не легла ни на один день")
    return BR.Bars(b.symbol, b.ts, op, b.close, b.volume, b.taker_buy), n


def shuffle_signs(rows, seed=11):
    """Перемешать знаки хода дня по дням, оставив ходы на местах.

    Нуль честной формы: механизм утверждает связь знака ХОДА ДНЯ с ходом
    часа; перестановка метки разрывает именно её, сохраняя и календарь, и
    распределение часовых ходов. Ход дня у строки остаётся своим — иначе
    порвался бы и отбор по квалификации, и мерился бы другой набор дней.
    """
    rng = np.random.default_rng(seed)
    src = [r for r in rows if r["sign"] != 0]
    perm = rng.permutation(len(src))
    out, k = [], 0
    for r in rows:
        r = dict(r)
        if r["sign"] != 0:
            r["sign"] = src[int(perm[k])]["sign"]
            k += 1
            r["signed_bp"] = r["sign"] * r["move_bp"]
        out.append(r)
    return out


# --- убийцы -----------------------------------------------------------

def _cmp_phrase(value, thr, dead, unit, what):
    """Фраза убийцы, выведенная ИЗ ЧИСЛА.

    И сравнение, и слово вердикта считаются от значения, а не стоят
    рядом с ним литералом: фраза, набранная руками, стареет молча и
    однажды противоречит своему же числу.
    """
    if value is None:
        return f"{what}: прочерк — {UNMEASURED}"
    sign = "≤" if dead else ">"
    return (f"{what}: {value:.2f}{unit} {sign} {thr:.2f}{unit} — "
            f"{DEAD if dead else ALIVE}")


def killers(rows_fund, rows_placebo, rows_nontrade, by_hour):
    """K1–K5 числами и фразами. Каждая фраза выведена из своего числа.

    `by_hour` — {час: среднее м по квалифицированным дням}, включая
    час-вердикт: p95 считается по ОСТАЛЬНЫМ 23 часам.
    """
    qf = qualified(rows_fund)
    m = stat([r["signed_bp"] for r in qf])
    out = {}

    v = m["mean"]
    dead = v is None or v <= K1_FLOOR_BP
    out["K1"] = {"value": v, "thr": K1_FLOOR_BP, "dead": bool(dead),
                 "n": m["n"], "t": m["t"], "lo": m["lo"], "hi": m["hi"],
                 "phrase": _cmp_phrase(v, K1_FLOOR_BP, dead, " б.п.",
                                       "K1 ход со знаком в окне фонда")}

    qp = qualified(rows_placebo)
    d, t = welch_t([r["signed_bp"] for r in qf], [r["signed_bp"] for r in qp])
    dead = t is None or t <= K2_MIN_T
    out["K2"] = {"value": t, "thr": K2_MIN_T, "dead": bool(dead), "diff": d,
                 "n_placebo": len(qp),
                 "phrase": _cmp_phrase(t, K2_MIN_T, dead, "",
                                       "K2 t разности с плацебо-окном")}

    others = [x for h, x in sorted(by_hour.items())
              if h != VERDICT_HOUR and x is not None]
    p95 = float(np.percentile(others, K3_PCT)) if len(others) >= 2 else None
    v15 = by_hour.get(VERDICT_HOUR)
    dead = v15 is None or p95 is None or v15 <= p95
    out["K3"] = {"value": v15, "thr": p95, "dead": bool(dead),
                 "hours": len(others),
                 "phrase": (f"K3 час 15–16: прочерк — {UNMEASURED}"
                            if v15 is None or p95 is None else
                            _cmp_phrase(v15, p95, dead, " б.п.",
                                        f"K3 час 15–16 против p{K3_PCT:.0f} "
                                        f"остальных {len(others)} часов"))}

    qn = qualified(rows_nontrade)
    d, t = welch_t([r["signed_bp"] for r in qf], [r["signed_bp"] for r in qn])
    dead = t is None or t <= K4_MIN_T
    out["K4"] = {"value": t, "thr": K4_MIN_T, "dead": bool(dead), "diff": d,
                 "n_nontrade": len(qn),
                 "phrase": _cmp_phrase(t, K4_MIN_T, dead, "",
                                       "K4 t разности с выходными и "
                                       "праздниками")}

    sl = slope_on_abs_r(qf)
    v = sl["slope"]
    dead = v is None or v <= K5_MIN_SLOPE
    out["K5"] = {"value": v, "thr": K5_MIN_SLOPE, "dead": bool(dead),
                 "t": sl["t"], "n": sl["n"],
                 "phrase": _cmp_phrase(v, K5_MIN_SLOPE, dead,
                                       " б.п. на % хода",
                                       "K5 наклон на |ход дня|")}
    return out


def verdict(ks, n_qual):
    """Вердикт заявке: живо, мертво или не измерено. Выводится из чисел.

    Покрытие идёт ПЕРВЫМ: квалифицированных дней меньше объявленного
    минимума — ответ «не измерено», и ни один убийца вердикта не
    выносит. Число дней, названное после вердикта, уже ничего не решает.
    """
    dead = sorted(k for k, v in ks.items() if v["dead"])
    if n_qual < MIN_QUAL_DAYS:
        return {"verdict": UNMEASURED, "dead_by": dead, "n_qual": n_qual,
                "phrase": (f"квалифицированных дней {n_qual} при минимуме "
                           f"{MIN_QUAL_DAYS} — {UNMEASURED}")}
    if dead:
        return {"verdict": DEAD, "dead_by": dead, "n_qual": n_qual,
                "phrase": (f"на {n_qual} квалифицированных днях сработали "
                           f"убийцы {', '.join(dead)} — {DEAD}")}
    return {"verdict": ALIVE, "dead_by": [], "n_qual": n_qual,
            "phrase": (f"на {n_qual} квалифицированных днях ни один из "
                       f"{len(ks)} убийц не сработал — {ALIVE}")}


# --- деньги -----------------------------------------------------------

def money(rows, cost_bp=ROUND_COST_BP):
    """Счёт сделки на квалифицированных днях, в процентах депозита.

    Размер — доля депозита по σ̂ часа; издержки снимаются с НОТИОНАЛА,
    то есть той же долей. Дни без размера (прочерк σ̂) в счёт не входят
    и считаются отдельно: подставить им единицу значило бы выдумать
    плечо там, где его нечем было посчитать.
    """
    qs = qualified(rows)
    used = [r for r in qs if r.get("size_frac") is not None]
    pnl = [r["size_frac"] * (r["signed_bp"] - cost_bp) / 100.0 for r in used]
    if not pnl:
        return {"n": 0, "no_size": len(qs), "net_pct": None, "median_pct": None,
                "win_share": None, "worst_pct": None, "worst_day": None,
                "without_top3_pct": None, "gross_pct": None}
    a = np.asarray(pnl, dtype=np.float64)
    order = np.argsort(a)
    return {
        "n": len(used), "no_size": len(qs) - len(used),
        "gross_pct": float(sum(r["size_frac"] * r["signed_bp"] / 100.0
                               for r in used)),
        "net_pct": float(a.sum()),
        "median_pct": float(np.median(a)),
        "win_share": float((a > 0).mean()),
        "worst_pct": float(a.min()),
        "worst_day": used[int(order[0])]["day"],
        "without_top3_pct": (float(a.sum() - a[order[-3:]].sum())
                             if a.size > 3 else None),
        "size_frac_median": float(np.median([r["size_frac"] for r in used])),
    }


# --- сборка окна ------------------------------------------------------

def windows(symbol, fund_start=None, fund_end=None):
    """Окна имени: фонд, плацебо. Дата запуска — сверенная либо объявленная.

    Конец окна — параметр, а не только константа: он есть конец АРХИВА,
    и прогон обязан называть его по данным, которые у него на диске.
    """
    lo = fund_start or FUND_START_DECLARED[symbol]
    return {"fund": (lo, fund_end or FUND_END),
            "placebo": (PLACEBO_LO, PLACEBO_HI)}


def by_hour_means(b, cal, lo, hi, log=None):
    """Среднее м по квалифицированным дням для каждого из 24 часов.

    Час-вердикт считается ТОЙ ЖЕ функцией, что и остальные: разойдись
    они, вердикт мерился бы одним кодом, а его контроль другим.
    """
    out, counts = {}, {}
    days = cal.days(lo, hi, (CAL.TRADE,))
    for h in range(24):
        rows, _ = day_table(b, cal, days, h, with_extras=False)
        qs = qualified(rows)
        out[h] = float(np.mean([r["signed_bp"] for r in qs])) if qs else None
        counts[h] = len(qs)
        if log:
            log(f"  час {h:02d}–{(h + 1) % 24:02d}: дней {len(qs)}, "
                f"м {'—' if out[h] is None else format(out[h], '.2f')} б.п.")
    return out, counts


def measure_symbol(b, cal, fund_start=None, fund_end=None, log=None):
    """Полный замер имени: строки окон, K1–K5, вердикт, деньги, покрытие."""
    w = windows(b.symbol, fund_start, fund_end)
    say = log or (lambda *_: None)
    lo, hi = w["fund"]
    say(f"{b.symbol}: окно фонда {lo} → {hi}")
    fund_days = cal.days(lo, hi, (CAL.TRADE, CAL.EARLY))
    rows_f, skips_f = day_table(b, cal, fund_days)
    plo, phi = w["placebo"]
    rows_p, skips_p = day_table(b, cal, cal.days(plo, phi,
                                                 (CAL.TRADE, CAL.EARLY)))
    nt = cal.days(lo, hi, (CAL.WEEKEND, CAL.HOLIDAY))
    rows_n, skips_n = day_table(b, cal, nt, ref_mode=REF_PREV_CALENDAR)
    say(f"{b.symbol}: строк окна {len(rows_f)}, плацебо {len(rows_p)}, "
        f"неторговых {len(rows_n)}")
    say(f"{b.symbol}: перебор 24 часов")
    bh, bh_n = by_hour_means(b, cal, lo, hi, log=log)
    ks = killers(rows_f, rows_p, rows_n, bh)
    qf = qualified(rows_f)
    return {
        "symbol": b.symbol,
        "fund_start": lo.isoformat(), "fund_end": hi.isoformat(),
        "placebo": [plo.isoformat(), phi.isoformat()],
        "n_qual": len(qf), "n_rows": len(rows_f),
        "qual_share": (len(qf) / len(rows_f)) if rows_f else None,
        "skips_fund": skips_f, "skips_placebo": skips_p,
        "skips_nontrade": skips_n,
        "killers": ks,
        "verdict": verdict(ks, len(qf)),
        "m": stat([r["signed_bp"] for r in qf]),
        "m_half": stat([r["signed_half_bp"] for r in qf]),
        "m_after": stat([r["signed_after_bp"] for r in qf]),
        "aggr": stat([r["aggr_signed_pp"] for r in qf]),
        "usd_volume": stat([r["usd_volume"] for r in qf]),
        "abs_r": stat([abs(r["r_day"]) for r in qf]),
        "by_hour": bh, "by_hour_n": bh_n,
        "money": money(rows_f),
        "buckets": buckets(rows_f),
        "rows_fund": rows_f, "rows_placebo": rows_p, "rows_nontrade": rows_n,
    }


BUCKETS = ((0.01, 0.02), (0.02, 0.03), (0.03, 0.05), (0.05, 9.99))


def buckets(rows):
    """Ход со знаком по корзинам |ход дня|. Пустая корзина — прочерк."""
    out = []
    for lo, hi in BUCKETS:
        v = [r["signed_bp"] for r in rows
             if lo <= abs(r["r_day"]) < hi and r["sign"] != 0]
        s = stat(v)
        out.append({"lo": lo, "hi": hi, "n": s["n"], "mean": s["mean"],
                    "t": s["t"], "median": s["median"]})
    return out
