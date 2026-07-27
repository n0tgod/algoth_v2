#!/usr/bin/env python3
"""
A1 — персистентность funding во времени: признак отбора или только издержка.

Отвечает на вопрос 12.4 спеки 01: «дифференциал ставок между ногами — это
измеримый денежный поток; сейчас он у нас только издержка, возможно, он же
должен входить в критерий отбора пар».

**Почему прежнего измерения недостаточно.** Уже измерено, что дифференциал
funding между ногами по всем 258 840 парам имеет медиану 19.7 % годовых.
Это величина *задним числом*, посчитанная по всей истории пары. Из неё не
следует ничего о торговле: чтобы отбирать пары по funding, дифференциал
нужно знать **на входе в позицию**, то есть по прошлому — и он должен
дожить до конца удержания. Величина за всю историю оба условия обходит.

**Как это проверяется здесь.** История режется на непересекающиеся окна
удержания длиной `H` дней. Перед каждым таким окном берётся окно
формирования длиной `F` дней, целиком в прошлом. По обоим окнам считается
одна и та же величина — фактически начисленное, приведённое к годовым:

    годовая ставка = сумма начислений в окне / длина окна × 365 × 100 %

Дальше сравнивается прошлое с будущим, и только так:

* **Знак пары.** Для каждой пары активов (i, j) знак `f_i − f_j` в окне
  формирования против знака `g_i − g_j` в окне удержания. Доля совпадений
  по всем парам сразу — это доля согласованных пар, она считается через
  число инверсий за `O(n log n)`, а не перебором 258 840 пар на каждую дату.
  Ноль информации даёт 50 %.
* **Ранговая корреляция** Спирмена между сечением прошлого и сечением
  будущего. Ноль информации даёт 0.
* **Децильный спред.** Отбираем верхний и нижний дециль по прошлому —
  это и есть «отбор пар по funding»: шорт дорогой ноги, лонг дешёвой.
  Сравниваем спред, обещанный окном формирования, с тем, что **эти же
  активы** дали в окне удержания. Отношение второго к первому и есть доля
  дожившего до сделки. Ноль информации даёт 0.

Позиция в парной торговле направлена сигналом возврата к среднему, а не
funding: та же пара сегодня лонг A / шорт B, завтра наоборот. Поэтому
устойчивый дифференциал сам по себе не приносит денег — он пригоден только
как фильтр на входе, когда направление уже известно. Отсюда и требование:
предсказуемость должна быть на горизонте удержания 1–5 дней, а не «в
среднем за историю».

Второй, отдельный вопрос — **расхождение площадок** (раздел 5.2 спеки 02).
Измеренные 3.4 п.п. медианы это среднее за окно в 580 дней. Если знак
расхождения по активу устойчив, подмену площадки можно было бы (в теории)
чинить поправкой; если дрейфует — нельзя ничем, кроме ставок площадки
исполнения. Считается по той же сетке окон.

Запуск (после `bybit_api.py` и `binance_funding.py`):

    python3 funding_persistence.py

Пишет `out/funding_persistence.json`; раздел отчёта рендерит
`data_report.py`. Только stdlib.
"""

import bisect
import csv
import gzip
import json
import os
import random
import sys
from array import array
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
BYBIT_DIR = os.path.join(OUT, "funding")
BINANCE_DIR = os.path.join(OUT, "funding_binance")

sys.path.insert(0, RESEARCH)
from common.funding import annualized_from_sum  # noqa: E402

MS_DAY = 86_400_000

# Пары «окно формирования — окно удержания», в сутках. Удержание 1–5 дней
# задано разделом 3.2 спеки 01; 30 и 90 добавлены, чтобы увидеть, теряется
# предсказуемость на коротком горизонте или её нет вовсе.
GRID = [(7, 5), (30, 5), (90, 5), (30, 30), (90, 90)]

# Распад: то же формирование, но окно удержания отодвинуто на разрыв.
# Настоящая предсказуемость обязана убывать с расстоянием; если бы она не
# убывала, измерялся бы не рынок, а что-то постоянное в самом стенде.
DECAY_FORM, DECAY_HOLD = 30, 5
DECAY_GAPS = [0, 5, 30, 90, 365]

MIN_CROSS_SECTION = 50   # сечение меньше — статистика по нему не считается
STEP_SAMPLE = 64         # промежутков в выборке для медианного шага окна
DECILE = 0.10
VENUE_WINDOW_DAYS = 90   # сетка для расхождения площадок


# ------------------------------------------------------------------ ряды

def read_series(path, rate_col):
    """(отметки времени, ставки, префиксные суммы ставок) — три массива.

    Префиксные суммы нужны потому, что сумма по окну спрашивается порядка
    миллиона раз: 700 активов × 360 дат × два окна × пять конфигураций.
    С ними одно окно стоит два бинарных поиска и одно вычитание.
    """
    ts, rates = array("q"), array("d")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
    for row in rows:
        if not row:
            continue
        t = datetime.fromisoformat(row[0])
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        ts.append(int(t.timestamp() * 1000))
        rates.append(float(row[rate_col]))
    if not ts:
        return None
    order = sorted(range(len(ts)), key=ts.__getitem__)
    ts = array("q", (ts[i] for i in order))
    rates = array("d", (rates[i] for i in order))
    pre = array("d", [0.0])
    s = 0.0
    for r in rates:
        s += r
        pre.append(s)
    return ts, rates, pre


def window_rate(series, t0, t1):
    """Годовая ставка по фактически начисленному в окне [t0, t1).

    Возвращает `None`, если окно покрыто не полностью. Проверяется тремя
    условиями, и все три обязательны:

    1. Ряд существует по обе стороны окна — иначе внутрь окна попал
       листинг или делистинг, и деление на полную длину окна занизит
       ставку тем сильнее, чем меньше инструмент прожил.
    2. В окне не меньше трёх начислений — на двух нечего усреднять.
    3. Отступ от края окна до ближайшего начисления не больше двух
       медианных шагов ряда **в этом же окне**. Порог берётся локальный,
       а не общий по активу: Bybit меняет режим начисления по ходу
       истории, и общий шаг на часовом участке отверг бы законные окна.

    Медиана шага берётся не по всем промежуткам окна, а по выборке из
    `STEP_SAMPLE` штук с равномерным шагом. Функция зовётся порядка двух
    миллионов раз, и на девяностодневном часовом окне полная сортировка
    двух тысяч промежутков дороже всего остального вместе взятого.
    Среднее вместо медианы не годится: одна дыра его раздувает, и проверка
    края становится слабее ровно там, где ряд хуже.
    """
    ts, rates, pre = series
    if ts[0] > t0 or ts[-1] < t1:
        return None
    lo = bisect.bisect_left(ts, t0)
    hi = bisect.bisect_left(ts, t1)
    n = hi - lo
    if n < 3:
        return None
    stride = max(1, (n - 1) // STEP_SAMPLE)
    steps = sorted(ts[i + 1] - ts[i] for i in range(lo, hi - 1, stride))
    med = steps[len(steps) // 2]
    if (ts[lo] - t0) > 2 * med or (t1 - ts[hi - 1]) > 2 * med:
        return None
    return annualized_from_sum(pre[hi] - pre[lo], (t1 - t0) / MS_DAY)


# -------------------------------------------------------------- статистика

def _count_inversions(seq):
    """Число инверсий сортировкой слиянием. Ties считаются согласованными."""
    buf = list(seq)
    tmp = [0] * len(buf)
    inv = 0

    width = 1
    n = len(buf)
    while width < n:
        for lo in range(0, n, 2 * width):
            mid, hi = min(lo + width, n), min(lo + 2 * width, n)
            i, j, k = lo, mid, lo
            while i < mid and j < hi:
                if buf[i] <= buf[j]:
                    tmp[k] = buf[i]; i += 1
                else:
                    tmp[k] = buf[j]; j += 1
                    inv += mid - i
                k += 1
            while i < mid:
                tmp[k] = buf[i]; i += 1; k += 1
            while j < hi:
                tmp[k] = buf[j]; j += 1; k += 1
        buf, tmp = tmp, buf
        width *= 2
    return inv


def _tied_pairs(sorted_keys):
    """Число пар с одинаковым ключом в отсортированной последовательности."""
    total, i, n = 0, 0, len(sorted_keys)
    while i < n:
        j = i
        while j + 1 < n and sorted_keys[j + 1] == sorted_keys[i]:
            j += 1
        k = j - i + 1
        total += k * (k - 1) // 2
        i = j + 1
    return total


def pair_sign_agreement(f, g):
    """Доля пар (i, j), у которых знак `f_i − f_j` совпал со знаком `g_i − g_j`.

    Перебирать 258 840 пар на каждую из сотен дат незачем: число
    несогласованных пар — это в точности число инверсий последовательности
    `g`, упорядоченной по `f`. Считается за `O(n log n)`.

    **Ничьи исключаются из знаменателя, и это не косметика.** Ставка
    funding очень часто равна ровно базовой, поэтому за одинаковое число
    начислений два актива дают побитово одинаковую сумму за окно. Такие
    пары не имеют знака: дифференциал равен нулю, торговать в них нечего.
    Если засчитывать их как согласие, мера уезжает вверх — на перестановке
    меток, где связи нет по построению, получалось 0.520 вместо 0.500.
    Читалось бы это как «слабая, но связь есть».

    Порядок сортировки — по `f`, затем по `g`. Тогда пары, равные по `f`,
    идут по неубыванию `g` и инверсией не считаются: иначе их вклад
    зависел бы от произвольного порядка равных элементов.
    """
    n = len(f)
    total = n * (n - 1) // 2
    if total == 0:
        return None, None, 0
    order = sorted(range(n), key=lambda i: (f[i], g[i]))
    fs = [f[i] for i in order]
    gs = [g[i] for i in order]
    discordant = _count_inversions(gs)
    tied_f = _tied_pairs(fs)
    tied_g = _tied_pairs(sorted(gs))
    tied_both = _tied_pairs([(f[i], g[i]) for i in order])
    ties = tied_f + tied_g - tied_both
    ranked = total - ties
    if ranked <= 0:
        return None, 1.0, total
    return (ranked - discordant) / ranked, ties / total, total


def _ranks(vals):
    order = sorted(range(len(vals)), key=vals.__getitem__)
    r = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(f, g):
    n = len(f)
    if n < 3:
        return None
    a, b = _ranks(f), _ranks(g)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else None


def decile_spread(f, g):
    """Спред «шорт верхний дециль / лонг нижний» — обещанный и полученный.

    Отбор идёт строго по `f` (прошлое). `g` считается по тем же активам:
    это и есть проверка «отобрали по прошлому — получили в будущем».
    """
    n = len(f)
    k = max(1, int(n * DECILE))
    order = sorted(range(n), key=f.__getitem__)
    lowk, highk = order[:k], order[-k:]
    prom = (sum(f[i] for i in highk) - sum(f[i] for i in lowk)) / k
    real = (sum(g[i] for i in highk) - sum(g[i] for i in lowk)) / k
    return prom, real, k, lowk, highk


def quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    s = sorted(vals)
    if not s:
        return {}
    return {str(q): s[min(len(s) - 1, int(q * (len(s) - 1)))] for q in qs}


def median(vals):
    s = sorted(vals)
    return s[len(s) // 2] if s else None


# ------------------------------------------------------ дифференциал ног

def run_grid(series, t_start, t_end, form_days, hold_days,
             gap_days=0, permute=False):
    """Прогон одной конфигурации «формирование → удержание» по всей истории.

    Окна удержания непересекающиеся: соседние наблюдения не делят между
    собой ни одного начисления, иначе выборка была бы искусственно
    раздута перекрытием.

    `gap_days` — разрыв между концом окна формирования и началом окна
    удержания. При нуле измеряется предсказуемость, при большом разрыве —
    та её часть, что держится годами. Разрыв нужен как проверка на распад:
    настоящая предсказуемость должна убывать с расстоянием.

    `permute` — плацебо: метки активов между прошлым и будущим
    перемешиваются. Все связи разрушаются, и любая мера, оставшаяся
    ненулевой, измеряет не рынок, а дефект самого измерения. Перестановка
    детерминированная (фиксированное зерно), чтобы прогон воспроизводился.
    """
    F, H, G = form_days * MS_DAY, hold_days * MS_DAY, gap_days * MS_DAY
    dates, agree_w, agree_n, tie_w = [], 0.0, 0, 0.0
    ics, promised, realized, retentions, sign_hits, sizes = [], [], [], [], [], []
    picked_short, picked_long = {}, {}
    rnd = random.Random(20260727)

    t = t_start + F
    while t + G + H <= t_end:
        f, g, names = [], [], []
        for asset, s in series.items():
            a = window_rate(s, t - F, t)
            if a is None:
                continue
            b = window_rate(s, t + G, t + G + H)
            if b is None:
                continue
            f.append(a)
            g.append(b)
            names.append(asset)
        if permute:
            rnd.shuffle(g)
        if len(f) >= MIN_CROSS_SECTION:
            share, tie_share, npairs = pair_sign_agreement(f, g)
            if share is not None:
                agree_w += share * npairs
                tie_w += tie_share * npairs
                agree_n += npairs
            rho = spearman(f, g)
            if rho is not None:
                ics.append(rho)
            prom, real, _, lowk, highk = decile_spread(f, g)
            promised.append(prom)
            realized.append(real)
            for i in highk:
                picked_short[names[i]] = picked_short.get(names[i], 0) + 1
            for i in lowk:
                picked_long[names[i]] = picked_long.get(names[i], 0) + 1
            if prom > 0:
                retentions.append(real / prom)
            sign_hits.append(
                sum(1 for x, y in zip(f, g) if x * y > 0) / len(f))
            sizes.append(len(f))
            dates.append(datetime.fromtimestamp(t / 1000, timezone.utc)
                         .date().isoformat())
        t += G + H

    return {
        "form_days": form_days,
        "hold_days": hold_days,
        "gap_days": gap_days,
        "permuted": permute,
        "windows": len(sizes),
        "median_cross_section": median(sizes),
        "first_window": dates[0] if dates else None,
        "last_window": dates[-1] if dates else None,
        # Доля пар, сохранивших знак дифференциала. 50 % — отсутствие связи.
        "pair_sign_agreement": (agree_w / agree_n) if agree_n else None,
        # Доля пар без знака: дифференциал равен нулю на одном из концов.
        "pair_tie_share": (tie_w / agree_n) if agree_n else None,
        "pairs_evaluated": agree_n,
        # Ранговая корреляция сечения «прошлое → будущее».
        "ic_median": median(ics),
        "ic_quantiles": quantiles(ics),
        "ic_share_positive": (sum(1 for x in ics if x > 0) / len(ics)) if ics else None,
        # Децильный спред в процентах годовых: обещанный и полученный.
        "decile_promised_median": median(promised),
        "decile_realized_median": median(realized),
        "decile_retention_median": median(retentions),
        "decile_retention_quantiles": quantiles(retentions),
        "decile_realized_share_positive":
            (sum(1 for x in realized if x > 0) / len(realized)) if realized else None,
        # Устойчивость знака самой ставки актива (не дифференциала пары).
        "asset_sign_agreement": median(sign_hits),
        # Кого именно отбирает признак. Нужно не для статистики, а чтобы
        # владелец увидел инструменты: у ставки в сотни процентов годовых
        # обычно и стакан соответствующий, а ликвидность в A1 не измерена.
        "picked_short_top": dict(sorted(picked_short.items(),
                                        key=lambda kv: -kv[1])[:20]),
        "picked_long_top": dict(sorted(picked_long.items(),
                                       key=lambda kv: -kv[1])[:20]),
        "distinct_picked": len(set(picked_short) | set(picked_long)),
    }


# ----------------------------------------------- расхождение площадок

def venue_drift(by_series, bn_series, t_start, t_end, win_days):
    """Держится ли знак расхождения Bybit − Binance от окна к окну.

    Считается по активам, а не по парам: вопрос в том, можно ли расхождение
    площадок трактовать как поправку к активу.
    """
    W = win_days * MS_DAY
    per_asset, flips_all = {}, []
    for asset, sby in by_series.items():
        sbn = bn_series.get(asset)
        if sbn is None:
            continue
        vals, t = [], t_start
        while t + W <= t_end:
            a = window_rate(sby, t, t + W)
            b = window_rate(sbn, t, t + W)
            if a is not None and b is not None:
                vals.append((t, a - b))
            t += W
        if len(vals) < 4:
            continue
        d = [v for _, v in vals]
        pos = sum(1 for v in d if v > 0)
        dominant = max(pos, len(d) - pos) / len(d)
        flips = sum(1 for x, y in zip(d, d[1:]) if x * y < 0)
        same_next = 1 - flips / (len(d) - 1)
        per_asset[asset] = {
            "windows": len(d),
            "dominant_sign_share": dominant,
            "next_window_same_sign": same_next,
            "median_abs_pp": median([abs(v) for v in d]),
            "min_pp": min(d),
            "max_pp": max(d),
        }
        flips_all.append(same_next)

    dom = [v["dominant_sign_share"] for v in per_asset.values()]
    return {
        "window_days": win_days,
        "assets": len(per_asset),
        "median_windows_per_asset": median([v["windows"] for v in per_asset.values()]),
        # Доля окон, где знак совпал с преобладающим у этого актива.
        "dominant_sign_share_quantiles": quantiles(dom),
        "dominant_sign_share_median": median(dom),
        # Доля соседних окон, где знак не поменялся. 50 % — монетка.
        "next_window_same_sign_median": median(flips_all),
        "assets_never_flip": sum(1 for v in per_asset.values()
                                 if v["next_window_same_sign"] == 1.0),
        "per_asset": per_asset,
    }


# ------------------------------------------------------------------- main

def load_all(universe, key, directory, rate_col):
    series = {}
    for asset, rec in universe["assets"].items():
        sym = rec.get(key)
        if not sym:
            continue
        path = os.path.join(directory, f"{sym}.csv.gz")
        if not os.path.exists(path):
            continue
        s = read_series(path, rate_col)
        if s and len(s[0]) >= 10:
            series[asset] = s
    return series


def main():
    universe = json.load(open(os.path.join(OUT, "universe.json"), encoding="utf-8"))

    print("чтение рядов funding Bybit...", file=sys.stderr, flush=True)
    by = load_all(universe, "bybit_symbol", BYBIT_DIR, 1)
    print(f"  {len(by)} активов", file=sys.stderr, flush=True)

    print("чтение рядов funding Binance...", file=sys.stderr, flush=True)
    bn = load_all(universe, "binance_symbol", BINANCE_DIR, 2)
    print(f"  {len(bn)} активов", file=sys.stderr, flush=True)

    t_start = min(s[0][0] for s in by.values())
    t_end = max(s[0][-1] for s in by.values())
    # Сетка выравнивается по суткам UTC, иначе окна поедут относительно
    # моментов начисления и покрытие будет проверяться по-разному у разных
    # конфигураций.
    t_start = (t_start // MS_DAY) * MS_DAY
    t_end = (t_end // MS_DAY) * MS_DAY

    legs = []
    for F, H in GRID:
        print(f"дифференциал ног: формирование {F} д → удержание {H} д...",
              file=sys.stderr, flush=True)
        legs.append(run_grid(by, t_start, t_end, F, H))

    decay = []
    for gap in DECAY_GAPS:
        print(f"распад: разрыв {gap} д...", file=sys.stderr, flush=True)
        decay.append(run_grid(by, t_start, t_end, DECAY_FORM, DECAY_HOLD,
                              gap_days=gap))

    print("плацебо: перестановка меток активов...", file=sys.stderr, flush=True)
    placebo = run_grid(by, t_start, t_end, DECAY_FORM, DECAY_HOLD, permute=True)

    print(f"расхождение площадок по окнам {VENUE_WINDOW_DAYS} д...",
          file=sys.stderr, flush=True)
    venue = venue_drift(by, bn, t_start, t_end, VENUE_WINDOW_DAYS)

    doc = {
        "meta": {
            "venue": "bybit",
            "assets_bybit": len(by),
            "assets_binance": len(bn),
            "history_start": datetime.fromtimestamp(t_start / 1000, timezone.utc)
                                     .date().isoformat(),
            "history_end": datetime.fromtimestamp(t_end / 1000, timezone.utc)
                                   .date().isoformat(),
            "min_cross_section": MIN_CROSS_SECTION,
            "decile": DECILE,
        },
        "legs": legs,
        "decay": decay,
        "placebo": placebo,
        "venue_drift": venue,
    }

    path = os.path.join(OUT, "funding_persistence.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)

    brief = {
        "history": f"{doc['meta']['history_start']}..{doc['meta']['history_end']}",
        "legs": [
            {
                "F→H": f"{r['form_days']}→{r['hold_days']}",
                "окон": r["windows"],
                "сечение": r["median_cross_section"],
                "знак пары": r["pair_sign_agreement"],
                "ничьи": r["pair_tie_share"],
                "IC": r["ic_median"],
                "обещано %": r["decile_promised_median"],
                "получено %": r["decile_realized_median"],
                "доля дожившего": r["decile_retention_median"],
            }
            for r in legs
        ],
        "decay": [
            {
                "разрыв": f"{r['gap_days']} д",
                "знак пары": r["pair_sign_agreement"],
                "ничьи": r["pair_tie_share"],
                "IC": r["ic_median"],
                "доля дожившего": r["decile_retention_median"],
            }
            for r in decay
        ],
        "placebo": {
            "знак пары": placebo["pair_sign_agreement"],
            "ничьи": placebo["pair_tie_share"],
            "IC": placebo["ic_median"],
            "доля дожившего": placebo["decile_retention_median"],
        },
        "venue_drift": {
            "активов": venue["assets"],
            "знак держится, медиана": venue["dominant_sign_share_median"],
            "знак не сменился к следующему окну": venue["next_window_same_sign_median"],
            "ни разу не сменили знак": venue["assets_never_flip"],
        },
    }
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    print(f"записан {path}")


if __name__ == "__main__":
    main()
