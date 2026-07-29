#!/usr/bin/env python3
"""
Разбор набора `metrics` архива Binance — открытый интерес и потоки.

Общий модуль, а не функция внутри этапа: те же файлы читают зонд L1
(`l1_cascades/probe.py`, `lag.py`) и сбор L2 (`l2_data/oi_binance.py`).
Вторая копия разбора колонок в этом проекте уже приводила к тихому
дефекту — загрузчик funding брал ставку по номеру колонки, что верно
для Bybit и неверно для Binance, и агрегат выходил ровно нулём.

Два правила, оба выведены из уже случившихся ошибок:

1. **Колонки ищутся по имени заголовка, не по номеру.** Состав набора
   между площадками и годами не совпадает.
2. **Метка времени — UTC явно.** `datetime.fromisoformat` без зоны
   берёт локальную, и на машине не в UTC вся сетка молча съезжает на
   часы, а проверка «цена сошлась» при этом продолжает проходить.

Что означает метка — отдельный вопрос, и он измерен, а не предположен
(`l1_cascades/lag.py`): **строка с меткой `t` описывает интервал
`[t, t+5)` и завершена только в `t+5`.** Снимок открытого интереса
стоит на конце интервала. Значит любой расчёт, использующий строку с
меткой `t`, обязан относить её к моменту `t + 5 мин`, иначе это
заглядывание в будущее. Константа `PUBLISH_LAG_MIN` живёт здесь, чтобы
у всех потребителей она была одна.

Только стандартная библиотека.
"""

import csv
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

STEP_MIN = 5              # шаг сетки набора
PUBLISH_LAG_MIN = 5       # строка с меткой t известна в t+5 (lag.py)

TIME_COL = "create_time"
OI_COL = "sum_open_interest"
OI_USD_COL = "sum_open_interest_value"
TAKER_RATIO_COL = "sum_taker_long_short_vol_ratio"


def metrics_url(symbol, day):
    """`metrics` бывает только суточным — месячной выкладки не существует."""
    return (f"{S3}/data/futures/um/daily/metrics/{symbol}/"
            f"{symbol}-metrics-{day}.zip")


def days_between(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += timedelta(days=1)
    return out


def read_zip_csv(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with z.open(z.namelist()[0]) as f:
            return list(csv.reader(io.TextIOWrapper(f, "utf-8")))


def parse_metrics(raw, columns=(OI_COL,)):
    """Строки суточного файла: `[(время_сек, знач1, знач2, …), …]`.

    Время — секунды эпохи UTC. Отсутствующая колонка есть ошибка
    формата, а не повод вернуть пусто: молчаливое «данных нет»
    неотличимо от «файла нет», и именно так однажды был отрапортован
    прогон с нулями.
    """
    rows = read_zip_csv(raw)
    if len(rows) < 2:
        return []
    head = [c.strip().lower() for c in rows[0]]
    try:
        it = head.index(TIME_COL)
        idx = [head.index(c) for c in columns]
    except ValueError as e:
        raise ValueError(
            f"нет колонки в metrics: {e}; заголовок {rows[0]}") from None
    need = max([it] + idx)
    out = []
    for r in rows[1:]:
        if len(r) <= need:
            continue
        try:
            t = datetime.fromisoformat(r[it].strip()).replace(
                tzinfo=timezone.utc).timestamp()
            out.append((t, *(float(r[i]) for i in idx)))
        except ValueError:
            continue
    return out
