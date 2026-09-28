#!/usr/bin/env python3
"""
Минутные бары из архива A1 — чтение, дедупликация, доступ по метке.

Вторая копия загрузчика тут не заводится: архив качает и сверяет
`research/a1_universe/binance_klines.py`, здесь только ЧТЕНИЕ уже
лежащих на диске зипов. Скачивания в этом модуле нет ни строки —
механика на архиве, новых данных ей не нужно.

Три вещи, ради которых модуль отдельный:

* **дедупликация по метке времени.** Дыру месячного файла архив
  закрывает СУТОЧНЫМ файлом, и тот приносит день целиком — вместе с
  барами, которые в месячном уже были. Об этом прямо предупреждает
  `binance_klines.read_symbol_timestamps`: хранилище обязано
  дедуплицировать по `(symbol, open_time)`, иначе часть баров войдёт в
  ряд дважды.
* **пропуск — прочерк, а не ноль и не соседний бар.** Минуты, которой в
  архиве нет, не существует: `at_open`/`at_close` возвращают None.
  Интерполяции здесь нет намеренно — подставленная цена минуты, которой
  не было, есть выдуманное число.
* **кеш своим каталогом.** Разбор 3.5 млн строк CSV занимает минуту на
  символ; `.npz` рядом с механикой делает повторный прогон секундным.
  Кеш помечен составом: символ, интервал, диапазон месяцев и суммарный
  размер зипов. Разойдись состав — кеш не берётся, а не отдаёт молча
  ряд другого окна.

Память считается составом ДО счёта: 3.5 млн минут × 5 полей × 8 байт —
около 140 МБ на символ. На сервере рядом со сборщиком это существенно,
поэтому `load` печатает объём сразу после разбора.
"""

import array
import csv
import io
import json
import os
import sys
import time
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ARCHIVE = os.path.join(ROOT, "research", "a1_universe", "out", "klines")
CACHE = os.path.join(HERE, "cache")

MIN_MS = 60_000

# Поля бара Binance, которые механике нужны. Остальные не читаются: у
# нас минутный ряд на шесть лет, и лишний столбец — это 28 МБ.
COL_OPEN_TIME, COL_OPEN, COL_CLOSE = 0, 1, 4
COL_VOLUME, COL_TAKER_BUY = 5, 9


class Bars:
    """Минутный ряд одного символа: метки и поля в numpy, доступ по метке.

    Метки отсортированы и уникальны. Поиск — `searchsorted`, а не
    словарь: словарь на 3.5 млн ключей стоит впятеро больше памяти.
    """

    def __init__(self, symbol, ts, op, cl, vol, tbv):
        self.symbol = symbol
        self.ts = np.asarray(ts, dtype=np.int64)
        self.open = np.asarray(op, dtype=np.float64)
        self.close = np.asarray(cl, dtype=np.float64)
        self.volume = np.asarray(vol, dtype=np.float64)
        self.taker_buy = np.asarray(tbv, dtype=np.float64)
        if self.ts.size and np.any(np.diff(self.ts) <= 0):
            raise ValueError(f"{symbol}: метки не строго возрастают")

    def __len__(self):
        return int(self.ts.size)

    def index(self, ts_ms):
        """Номер бара с ТОЧНО этой меткой; такого бара нет — None."""
        i = int(np.searchsorted(self.ts, int(ts_ms)))
        if i >= self.ts.size or int(self.ts[i]) != int(ts_ms):
            return None
        return i

    def at_open(self, ts_ms):
        """Цена открытия минуты `ts_ms` — цена в момент `ts_ms`.

        Ею исполняется сделка: это первая цена ПОСЛЕ момента решения.
        """
        i = self.index(ts_ms)
        return None if i is None else float(self.open[i])

    def at_close(self, ts_ms):
        """Цена закрытия минуты, ЗАКОНЧИВШЕЙСЯ в `ts_ms`.

        Ею считается сигнал: это последняя цена, известная строго ДО
        момента `ts_ms`. Разделение сигнала и исполнения здесь не
        косметика — на нём стоит вся проверка на заглядывание в будущее.
        """
        i = self.index(int(ts_ms) - MIN_MS)
        return None if i is None else float(self.close[i])

    def window(self, lo_ms, hi_ms):
        """Номера баров в полуинтервале [lo, hi) — как срез (a, b)."""
        a = int(np.searchsorted(self.ts, int(lo_ms), "left"))
        b = int(np.searchsorted(self.ts, int(hi_ms), "left"))
        return a, b

    def bytes(self):
        return int(sum(a.nbytes for a in (self.ts, self.open, self.close,
                                          self.volume, self.taker_buy)))


def _zips(symbol, interval):
    d = os.path.join(ARCHIVE, interval, symbol)
    if not os.path.isdir(d):
        raise FileNotFoundError(
            f"архива нет: {d} — качает research/a1_universe/binance_klines.py")
    return sorted(os.path.join(d, f) for f in os.listdir(d)
                  if f.endswith(".zip"))


def _stamp(paths, symbol, interval, lo_ms, hi_ms):
    """Состав кеша: чем он отличается от кеша другого окна или прогона."""
    return {"symbol": symbol, "interval": interval,
            "lo_ms": int(lo_ms), "hi_ms": int(hi_ms),
            "files": len(paths),
            "bytes": sum(os.path.getsize(p) for p in paths)}


def _read_zips(paths, lo_ms, hi_ms, log):
    """Разбор архива в `array`, а не в списки, и это про ПАМЯТЬ.

    Питоновский список из 3.5 млн чисел стоит около 130 МБ на столбец
    (объект float 24 байта плюс указатель), пять столбцов — 700 МБ пика.
    На сервере прогону очереди остаётся около 1.2 ГБ рядом со сборщиком
    (`run_d10.MEM_LIMIT_MB`), и тяжёлый прогон там убивает не себя, а
    часовой цикл. `array('d')` держит те же данные в 8 байтах на число.
    """
    ts = array.array("q")
    op, cl, vol, tbv = (array.array("d") for _ in range(4))
    for k, p in enumerate(paths, 1):
        try:
            with zipfile.ZipFile(p) as z:
                with z.open(z.namelist()[0]) as f:
                    for r in csv.reader(io.TextIOWrapper(f, encoding="utf-8")):
                        if not r or r[COL_OPEN_TIME].startswith("open_time"):
                            continue
                        t = int(r[COL_OPEN_TIME])
                        if t < lo_ms or t >= hi_ms:
                            continue
                        ts.append(t)
                        op.append(float(r[COL_OPEN]))
                        cl.append(float(r[COL_CLOSE]))
                        vol.append(float(r[COL_VOLUME]))
                        tbv.append(float(r[COL_TAKER_BUY]))
        except (zipfile.BadZipFile, ValueError, IndexError) as e:
            log(f"  битый архив, пропущен: {os.path.basename(p)} — {e}")
        if k % 25 == 0 or k == len(paths):
            log(f"  разобрано {k}/{len(paths)} файлов, баров {len(ts)}")
    return ts, op, cl, vol, tbv


def load(symbol, lo_ms, hi_ms, interval="1m", use_cache=True, log=print):
    """Ряд символа в полуинтервале [lo_ms, hi_ms). Пусто — ОТКАЗ.

    Ноль баров при существующем архиве значит не «рынок молчал», а
    «окно мимо данных»: такой ряд обязан быть исключением, иначе весь
    замер отчитается прочерками, и сломанная загрузка окажется
    неотличима от «эффекта нет».
    """
    paths = _zips(symbol, interval)
    stamp = _stamp(paths, symbol, interval, lo_ms, hi_ms)
    cpath = os.path.join(CACHE, f"{symbol}-{interval}.npz")
    if use_cache and os.path.exists(cpath):
        try:
            z = np.load(cpath, allow_pickle=False)
            if json.loads(str(z["stamp"])) == stamp:
                b = Bars(symbol, z["ts"], z["open"], z["close"],
                         z["volume"], z["taker_buy"])
                log(f"{symbol}: кеш, баров {len(b)}, "
                    f"{b.bytes() / 2**20:.0f} МБ")
                return b
            log(f"{symbol}: кеш другого состава, перечитываю архив")
        except Exception as e:                            # noqa: BLE001
            log(f"{symbol}: кеш не читается ({e}), перечитываю архив")

    t0 = time.time()
    ts, op, cl, vol, tbv = _read_zips(paths, lo_ms, hi_ms, log)
    if not ts:
        raise ValueError(
            f"{symbol}: в архиве ({len(paths)} файлов) нет ни одного бара в "
            f"окне [{lo_ms}, {hi_ms}) — это отказ загрузки, а не пустой рынок")
    a_ts = np.frombuffer(ts, dtype=np.int64)
    order = np.argsort(a_ts, kind="stable")
    a_ts = a_ts[order]
    keep = np.ones(a_ts.size, dtype=bool)
    keep[1:] = np.diff(a_ts) > 0                 # дубли суточных файлов
    dups = int((~keep).sum())
    idx = order[keep]
    b = Bars(symbol, a_ts[keep],
             *(np.frombuffer(c, dtype=np.float64)[idx]
               for c in (op, cl, vol, tbv)))
    log(f"{symbol}: баров {len(b)}, дублей снято {dups}, "
        f"{b.bytes() / 2**20:.0f} МБ, {time.time() - t0:.0f} с")
    if use_cache:
        os.makedirs(CACHE, exist_ok=True)
        np.savez(cpath, stamp=json.dumps(stamp, sort_keys=True), ts=b.ts,
                 open=b.open, close=b.close, volume=b.volume,
                 taker_buy=b.taker_buy)
    return b


def from_rows(symbol, rows):
    """Ряд из списка `(ts_ms, open, close, volume, taker_buy)` — для тестов.

    Настоящий конструктор, а не пересказ: проверки гоняют ТЕ ЖЕ функции
    замера, что и прогон, иначе проверялся бы тест, а не механика.
    """
    rows = sorted(rows, key=lambda r: r[0])
    cols = list(zip(*rows)) if rows else ([], [], [], [], [])
    return Bars(symbol, *cols)


def coverage(b, lo_ms, hi_ms):
    """Доля минут окна, покрытых барами. Покрытие — число ДО вердикта."""
    want = max(0, (int(hi_ms) - int(lo_ms)) // MIN_MS)
    if not want:
        return None
    a, z = b.window(lo_ms, hi_ms)
    return (z - a) / want


def main():
    import datetime as dt
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    lo = int(dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    hi = int(dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc).timestamp() * 1000)
    b = load(sym, lo, hi)
    print(json.dumps({
        "symbol": sym, "bars": len(b),
        "first": int(b.ts[0]), "last": int(b.ts[-1]),
        "coverage": round(coverage(b, lo, hi), 5),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
