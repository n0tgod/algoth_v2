#!/usr/bin/env python3
"""
Ряды funding площадки исполнения: загрузка, накопление, оценка.

Общая реализация для R4 (funding как издержка) и F1 (funding как
предмет измерения). Двух копий нет по той же причине, по которой одна
`normalize()` и одна `residual_matrix`: расхождение копий не падает и
не выглядит подозрительно — оно просто даёт другой вердикт.

Формат файлов
-------------

То, что пишет сборщик A1 (`bybit_api.py`): gzip-CSV с заголовком
`funding_time,funding_rate`, файл на символ площадки. Формат угадывался
дважды и дважды неверно — сначала за json, потом за миллисекунды, — и
оба раза ошибка стоила круга на сервер. Поэтому разбор времени
принимает оба вида и **падает громко** на незнакомом, а покрытие
считается числом: пустой словарь при существующем каталоге уже один раз
прошёл проверку `is not None` и был отрапортован как «funding включён»
с нулями.

Знак
----

Положительная ставка означает, что **лонги платят шортам**. Отсюда:

    издержка позиции = вес · сумма_ставок          (лонг с плюсом платит)
    оценка для отбора = − средняя суточная ставка  (плюс = «покупаем»)

Знак оценки перевёрнут намеренно, чтобы во всех отчётах проекта
«больше — лучше»; без этого соглашения его пришлось бы держать в
голове при каждом чтении таблицы.
"""

import csv
import gzip
import os
from datetime import date, datetime, timedelta

import numpy as np

# Ниже этого числа символов покрытие считается отсутствующим: частичное
# даёт заниженную издержку, выдавая её за полную.
MIN_FUNDING_SYMBOLS = 50


def parse_time_ms(x):
    """Метка времени в миллисекундах из того, что лежит в файле.

    Принимает и целые миллисекунды, и ISO-строку. На незнакомом виде
    поднимает `ValueError` — молчаливый пропуск здесь уже стоил круга:
    пустой результат выглядел как посчитанный ноль.
    """
    x = x.strip()
    try:
        return int(x)
    except ValueError:
        pass
    return int(datetime.fromisoformat(x).timestamp() * 1000)


def column_indices(header, where=""):
    """Позиции колонок времени и ставки — **по имени, а не по номеру**.

    Первая редакция брала `row[1]` как ставку. Для рядов Bybit это
    верно (`funding_time,funding_rate`), а у рядов Binance колонок три
    (`funding_time,interval_hours,funding_rate`), и `row[1]` есть число
    часов интервала. Прогон при этом не падал: книга «получала» ровно
    столько же восьмёрок, сколько «платила», агрегат по книге выходил
    точно ноль и читался как «funding нейтрален».

    Поймало это разложение по ногам — длинная нога показала −60.0, а
    короткая +60.0. Ради этого §5.1 спеки и требует докладывать ноги
    отдельно, а не только сумму.
    """
    if not header:
        raise ValueError(f"{where}: пустой файл, заголовка нет")
    cols = [c.strip().lower() for c in header]
    try:
        return cols.index("funding_time"), cols.index("funding_rate")
    except ValueError:
        raise ValueError(
            f"{where}: в заголовке нет funding_time/funding_rate — {header}")


def load_funding(directory, universe, symbols, symbol_field="bybit_symbol"):
    """`{актив: (времена_мс, ставки)}` по каталогу рядов.

    Возвращает `None`, если каталога нет вовсе. Пустой словарь при
    существующем каталоге — это НЕ то же самое: он означает, что имена
    символов не сошлись, и вызывающий обязан различать эти случаи.

    `symbol_field` — по какому символу назван файл. Ряды площадки
    исполнения названы символом Bybit, архив Binance — символом
    Binance. Совпадают они у большинства активов, но не у всех, и
    сопоставление «по умолчанию Bybit» тихо теряло бы часть архива.
    """
    if not os.path.isdir(directory):
        return None
    by_symbol = {v[symbol_field]: a for a, v in universe.items()
                 if v.get(symbol_field)}
    out = {}
    for fn in sorted(os.listdir(directory)):
        if not fn.endswith(".csv.gz"):
            continue
        a = by_symbol.get(fn[:-len(".csv.gz")])
        if a is None or a not in symbols:
            continue
        t, r = [], []
        with gzip.open(os.path.join(directory, fn), "rt", encoding="utf-8") as f:
            rd = csv.reader(f)
            head = next(rd, None)
            it, ir = column_indices(head, fn)
            for row in rd:
                if len(row) <= max(it, ir):
                    continue
                t.append(parse_time_ms(row[it]))
                r.append(float(row[ir]))
        if t:
            o = np.argsort(t)
            out[a] = (np.asarray(t, dtype=np.int64)[o],
                      np.asarray(r, dtype=np.float64)[o])
    return out


def ms(day):
    return int(np.datetime64(day + "T00:00:00", "ms").astype("int64"))


def accrued(funding, asset, t0_ms, t1_ms):
    """Сумма ставок, начисленных в `[t0, t1)`; `None` — ряда нет.

    Число начислений берётся из ряда, а не из объявленного интервала:
    318 символов из 722 меняли режим по ходу истории, и константа даёт
    у 128 активов ошибку больше 15 %, местами двукратную.
    """
    v = funding.get(asset)
    if v is None:
        return None
    t, r = v
    i0 = int(np.searchsorted(t, t0_ms, "left"))
    i1 = int(np.searchsorted(t, t1_ms, "left"))
    if i1 <= i0:
        return 0.0
    return float(r[i0:i1].sum())


def accrual_count(funding, asset, t0_ms, t1_ms):
    """Число начислений в окне. Нужно ловушке §5.6: смена режима."""
    v = funding.get(asset)
    if v is None:
        return None
    t, _ = v
    return int(np.searchsorted(t, t1_ms, "left")
               - np.searchsorted(t, t0_ms, "left"))


def funding_score(funding, names, at, form_days):
    """Оценка отбора: минус средняя **суточная** ставка за окно.

    Суточная, а не на начисление: у актива на часовых начислениях та же
    ставка стоит вчетверо дороже, чем у актива на четырёхчасовых, и
    средняя на начисление сравнивала бы несравнимое.

    Возвращает `(за_сутки, за_начисление)` — вторая величина идёт в
    артефакт проверкой устойчивости прочтения, а не в отбор.

    `NaN` там, где ряда нет или в окне не было ни одного начисления.
    Ноль означал бы «ставка была нулевой» — наблюдение, которого не
    было; тот же класс ошибки, что замороженные ряды A2.
    """
    t1 = ms(at)
    t0 = ms((date.fromisoformat(at) - timedelta(days=form_days)).isoformat())
    per_day = np.full(len(names), np.nan)
    per_accrual = np.full(len(names), np.nan)
    for i, s in enumerate(names):
        v = funding.get(s)
        if v is None:
            continue
        t, r = v
        i0 = int(np.searchsorted(t, t0, "left"))
        i1 = int(np.searchsorted(t, t1, "left"))
        if i1 <= i0:
            continue
        tot = float(r[i0:i1].sum())
        per_day[i] = -tot / form_days
        per_accrual[i] = -tot / (i1 - i0)
    return per_day, per_accrual
