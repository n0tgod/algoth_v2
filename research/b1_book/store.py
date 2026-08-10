#!/usr/bin/env python3
"""
Хранение потока: запись без потерь и чтение через порчу.

Почему не «дописывать в gzip»
-----------------------------

Первая версия открывала почасовой `.jsonl.gz` на дозапись. У такого
файла каждый запуск добавляет новый член архива, и остановка процесса
посреди записи оставляет член недописанным. Питоновский читатель
доходит до порчи и останавливается — то есть **теряется весь хвост
файла**, а не последняя строка. На сервере это дало `zlib.error` на всех
файлах сразу и нули там, где порча пришлась на начало.

Ошибка не в восстановлении истории, а в самом хранении: недельный сбор
не имеет права зависеть от того, как именно был остановлен процесс.

Как устроено сейчас
-------------------

Текущий час пишется **простым текстом**, строка за строкой. Обрыв на
любой строке стоит этой строки, а не файла. Когда час закрывается, файл
сжимается целиком и атомарно (`.tmp` + `rename`), а исходник удаляется:
на диске лежит то же самое, что и раньше, но битым оно быть не может.

Чтение принимает три вида: простой файл, сжатый файл и **сжатый файл с
порчей**. В последнем случае поток режется по границам членов архива и
разбирается по частям — уже испорченные файлы прошлого сбора так
спасаются, а не выбрасываются.

Только стандартная библиотека.
"""

import gzip
import json
import os
import threading
import time
import zlib
from datetime import datetime, timezone

MAGIC = b"\x1f\x8b\x08"           # начало члена gzip
STEP = 1 << 12                    # шаг подачи байтов в распаковщик


class Writer:
    """Почасовые файлы по видам данных и символам.

    Пишет в открытый текстовый файл; на смене часа закрывает его и
    сжимает. Сжатие делается в отдельном потоке: оно не должно
    задерживать приём потока с биржи.
    """

    def __init__(self, root, log=None):
        self.root = root
        self.log = log or (lambda m: None)
        self.files = {}
        self.lock = threading.Lock()
        # Счётчик записей ПО ВИДАМ. Вид, переставший писаться, снаружи
        # неотличим от вида, которому нечего писать: книга встала на
        # двое суток при исправном виде процесса, и заметить это удалось
        # только по отсутствию сводок. Число на каждый вид делает
        # «пишется ли» проверяемым, а не предполагаемым.
        self.n_by_kind = {}
        self.last_by_kind = {}
        # Сжатие — одной очередью, а не потоком на файл. На смене часа
        # закрываются ВСЕ файлы разом: при сотнях символов «поток на
        # файл» означает сотни одновременных gzip — процессор встаёт
        # колом ровно раз в час, и именно в ту минуту, когда приходит
        # новый час данных. Очередь жуёт файлы по одному, приёму потока
        # она не мешает.
        self._packq = []
        # У очереди свой замок: `_pack` зовётся из `write()` под общим
        # замком записи, и общий замок здесь был бы дедлоком.
        self._packlock = threading.Lock()
        self._packev = threading.Event()
        self._packer = threading.Thread(target=self._pack_worker,
                                        daemon=True)
        self._packer.start()

    @staticmethod
    def hour(ts):
        return datetime.fromtimestamp(ts, timezone.utc).strftime(
            "%Y-%m-%d-%H")

    def path(self, kind, symbol, hour, gz=False):
        return os.path.join(self.root, kind, symbol,
                            f"{hour}.jsonl" + (".gz" if gz else ""))

    def write(self, kind, symbol, obj, ts=None):
        ts = ts if ts is not None else time.time()
        hour = self.hour(ts)
        key = (kind, symbol)
        with self.lock:
            cur = self.files.get(key)
            if cur is not None and cur[0] != hour:
                cur[1].close()
                self._pack(self.path(kind, symbol, cur[0]))
                cur = None
            if cur is None:
                p = self.path(kind, symbol, hour)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                cur = [hour, open(p, "a", encoding="utf-8")]
                self.files[key] = cur
            cur[1].write(json.dumps(obj, separators=(",", ":")) + "\n")
            self.n_by_kind[kind] = self.n_by_kind.get(kind, 0) + 1
            self.last_by_kind[kind] = ts

    def _pack(self, path):
        """Поставить закрытый час в очередь сжатия."""
        with self._packlock:
            self._packq.append(path)
        self._packev.set()

    def _pack_worker(self):
        """Единственный поток сжатия: файлы по одному, без штурма CPU.

        Недожатое на выходе не теряется: `pack_stale` следующего запуска
        дожимает простые файлы прошлых часов.
        """
        while True:
            self._packev.wait()
            with self._packlock:
                if not self._packq:
                    self._packev.clear()
                    continue
                path = self._packq.pop(0)
                depth = len(self._packq)
            if depth and depth % 100 == 0:
                self.log(f"очередь сжатия: {depth} файлов")
            try:
                tmp = path + ".gz.tmp"
                with open(path, "rb") as src, gzip.open(tmp, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                os.replace(tmp, path + ".gz")
                os.remove(path)
            except Exception as e:                        # noqa: BLE001
                self.log(f"не удалось сжать {os.path.basename(path)}: {e}")

    def flush(self):
        with self.lock:
            for _, f in self.files.values():
                f.flush()

    def close(self):
        with self.lock:
            for _, f in self.files.values():
                f.close()
            self.files.clear()

    def pack_stale(self, keep_hour=None):
        """Сжать простые файлы прошлых часов, оставшиеся от прошлых
        запусков: иначе они так и лежали бы несжатыми."""
        keep = keep_hour or self.hour(time.time())
        n = 0
        for base, _, files in os.walk(self.root):
            for f in files:
                if f.endswith(".jsonl") and not f.startswith(keep):
                    self._pack(os.path.join(base, f))
                    n += 1
        return n


def read_jsonl(path, log=None, parse=json.loads):
    """Прочитать файл записей: простой, сжатый или сжатый с порчей.

    Обычное чтение сжатого файла останавливается на первом испорченном
    члене архива, теряя весь хвост. Здесь при отказе поток режется по
    сигнатурам членов и разбирается по частям — данные, записанные ПОСЛЕ
    порчи, остаются доступны.

    `parse` — чем разбирается строка. Умолчание отдаёт запись целиком;
    D1 передаёт свой лёгкий разбор (нужны три числа из ста уровней, и
    полный `json.loads` на сотнях миллионов строк стоит часы). Разбор
    сделан параметром, а не второй копией функции: **порча обрабатывается
    одним кодом** — иначе быстрый путь однажды потерял бы хвост файла
    там, где медленный его спасает. Строка, которую `parse` отвергает
    `ValueError`, пропускается — так же, как битая.
    """
    log = log or (lambda m: None)
    name = os.path.basename(path)
    if path.endswith(".gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                rows, ok = _parse(f, parse)
        except OSError as e:
            log(f"{name}: {e}")
            return []
        if ok:
            return rows
        log(f"{name}: обычное чтение оборвалось на {len(rows)} записях, "
            f"разбираю по членам архива")
        more = _salvage(path, log, parse)
        return more if len(more) > len(rows) else rows
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows, _ = _parse(f, parse)
    except OSError as e:
        log(f"{name}: {e}")
        return []
    return rows


def read_hour(dirpath, hour, log=None, parse=json.loads):
    """Записи одного часа: простой файл, сжатый или оба сразу.

    Оба сразу бывают по двум разным причинам. Сжатие прервали между
    переименованием и удалением исходника — тогда содержимое совпадает
    дословно. Либо час достался от прежнего устройства хранения, где
    архив дозаписывался, а новый запуск начал писать рядом простой файл
    — тогда содержимое разное, и терять его нельзя.

    Снаружи эти случаи неразличимы, поэтому берутся оба файла, а
    совпадающие записи снимаются: удвоить час хуже, чем потерять
    дословно повторившийся принт. Удвоение било бы по «обычному
    объёму» — той самой величине, в разах от которой считаются пороги.
    """
    log = log or (lambda m: None)
    have = [p for p in (os.path.join(dirpath, f"{hour}.jsonl" + s)
                        for s in ("", ".gz")) if os.path.exists(p)]
    seen = set() if len(have) > 1 else None
    rows, dup = [], 0
    for p in have:
        for r in read_jsonl(p, log, parse):
            if seen is not None:
                # Ключ снятия повторов зависит от того, ЧТО вернул
                # разбор: у записи целиком порядок ключей не обязан
                # совпадать (отсюда `sort_keys`), а лёгкий разбор отдаёт
                # кортеж чисел, который сам себе ключ.
                k = r if isinstance(r, tuple) else json.dumps(
                    r, sort_keys=True, separators=(",", ":"))
                if k in seen:
                    dup += 1
                    continue
                seen.add(k)
            rows.append(r)
    if dup:
        log(f"{hour}: снято {dup} записей, повторённых в двух файлах")
    return rows


def _parse(f, parse=json.loads):
    """Разобрать построчно. Возвращает `(записи, дочитано ли до конца)`.

    Решение о запасном пути принимает вызывающий: если проглотить отказ
    здесь, `read_jsonl` никогда не узнает, что файл оборван, и вернёт
    первый кусок как весь файл. Ровно так и было — «спасено 50 из 150».
    """
    out = []
    try:
        for line in f:
            try:
                out.append(parse(line))
            except ValueError:
                continue                                  # обрыв строки
    except Exception:                                     # noqa: BLE001
        return out, False
    return out, True


def _salvage(path, log, parse=json.loads):
    """Разобрать сжатый файл по членам, пропуская испорченные.

    Распаковка потоковая, а не «поделить по сигнатуре и разжать куски»:
    байты `1f 8b 08` встречаются и внутри сжатых данных, и деление по
    ним рвёт целые члены. Здесь член разжимается до отказа, после отказа
    сохраняется всё, что успело выйти, и поиск следующего члена идёт от
    места обрыва.

    Байты подаются мелким шагом намеренно. `decompress` при отказе не
    отдаёт ничего из того куска, который разбирал, — значит крупный шаг
    теряет столько данных, сколько в него влезло. Шаг в 4 КиБ
    ограничивает потерю концом испорченного члена.
    """
    try:
        raw = open(path, "rb").read()
    except OSError:
        return []
    out, pos, members, bad = [], raw.find(MAGIC), 0, 0
    while 0 <= pos < len(raw):
        d = zlib.decompressobj(31)
        chunks, i = [], pos
        while i < len(raw):
            end = min(i + STEP, len(raw))
            try:
                chunks.append(d.decompress(raw[i:end]))
            except zlib.error:
                break
            i = end
            if d.eof:
                break
        members += 1
        text = b"".join(chunks).decode("utf-8", "replace")
        for line in text.splitlines():
            try:
                out.append(parse(line))
            except ValueError:
                continue
        if d.eof:
            # Член дочитан, конец известен точно: `unused_data` — хвост
            # ПОСЛЕДНЕГО КУСКА, а не хвост файла, поэтому отсчёт от `i`.
            pos = raw.find(MAGIC, i - len(d.unused_data))
        else:
            # Член не дочитан — где он кончился, неизвестно, и продолжать
            # от места подачи нельзя: она уже внутри следующего члена.
            # Ищем следующий заголовок с начала испорченного.
            bad += 1
            pos = raw.find(MAGIC, pos + 3)
    log(f"{os.path.basename(path)}: спасено {len(out)} записей, "
        f"членов архива {members}, испорчено {bad}")
    return out
