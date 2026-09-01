"""Байткод, заслоняющий исходник: как он появляется и как его найти.

Питон считает лежащий `.pyc` свежим по ДВУМ грубым величинам — mtime
исходника в ЦЕЛЫХ секундах и его размеру в байтах. Правка, уложившаяся в
ту же секунду и давшая тот же размер, кеш не обесценивает: прогон читает
байткод ПРЕЖНЕЙ правки, а исходник на диске при этом говорит другое.

Это не гипотеза. Так была потеряна публикация целого захода строителя:
сюита `test_ceiling.py` докладывала пять провалов в
`test_the_pools_effective_n_must_grow`, и провалы были ЛОЖНЫМИ — вердикт
печатал «эффективное N пула растёт 2.90 → 2.29», то есть фраза
противоречила собственным числам, потому что фразу собирал исходник, а
ветку выбирал чужой байткод. Числа находки:

    в заголовке кеша: mtime 1788292539, размер 44381
    у исходника     : mtime 1788292539, размер 44381
    расходится ровно одна функция: `judge`

Тот же дефект уже нашли в машине негативных контролей (`_run_tests`
пишет байткод в свой каталог на каждый прогон). Там его чинит
`PYTHONPYCACHEPREFIX`; здесь чинить нечего — вопрос в том, чтобы отказ
не был неотличим от тишины. Заслонённый кеш **выглядит исправной
работой**: тесты идут, числа печатаются, вердикты выносятся — просто не
тем кодом, который лежит в ветке.

Чем этот страж отличается от проверки самого питона: питон сверяет
ЗАГОЛОВОК, а мы сверяем КОД. Заголовок в опасном случае совпадает по
построению — иначе питон перекомпилировал бы сам, и вреда не было бы
вовсе. Поэтому сверка заголовков здесь не осторожнее, а бесполезна, и
это закреплено отдельным негативным контролем.

Чего страж НЕ ловит: кеш, устаревший честно (заголовок разошёлся), — его
питон перекомпилирует сам, и находкой это не является; и правку, не
меняющую код после компиляции (перестановка комментария). Первое не
опасно, второе не является другой программой.

    python3 research/factory/pycguard.py            # найти и назвать
    python3 research/factory/pycguard.py --clear    # убрать заслоняющий

Модуль на стандартной библиотеке и без побочных действий: `--clear`
удаляет ТОЛЬКО `.pyc` внутри `__pycache__`, то есть порождённое
питоном, — исходников и артефактов не касается вовсе.
"""

import argparse
import importlib.util
import marshal
import os
import struct
import sys
import types

HEADER = 16                       # магия(4) + флаги(4) + два поля(4+4)
FLAG_HASH = 0b01                  # PEP 552: кеш по хешу, а не по mtime
FLAG_CHECKED = 0b10               # хеш-кеш, который питон всё же сверяет

HERE = os.path.dirname(os.path.abspath(__file__))


def cache_file(src):
    """Путь к кешу, который питон СЧЁЛ БЫ кешем этого исходника.

    Считается по дереву (`__pycache__` рядом с исходником), а не по
    `sys.pycache_prefix`, и это несущее решение, а не мелочь. Вопрос
    стража — не «откуда читаем МЫ», а «откуда прочитает ОБЫЧНЫЙ прогон»:
    суточный цикл, сторож, рука владельца в терминале. Сюита, которая
    увела свой кеш в сторону, спрашивая про свой же увод, доложила бы
    «заслона нет» ровно тогда, когда заслон есть.
    """
    keep = sys.pycache_prefix
    sys.pycache_prefix = None
    try:
        return importlib.util.cache_from_source(src)
    finally:
        sys.pycache_prefix = keep


def header(pyc):
    """(магия, флаги, поле1, поле2) заголовка кеша либо None."""
    try:
        with open(pyc, "rb") as f:
            raw = f.read(HEADER)
    except OSError:
        return None
    if len(raw) < HEADER:
        return None
    return struct.unpack("<4sIII", raw)


def looks_fresh(src, pyc):
    """Счёл бы питон этот кеш свежим — его же правилом, не нашим.

    Timestamp-кеш: совпали mtime исходника в ЦЕЛЫХ секундах и размер.
    Обе величины грубые, и в этом вся беда. Hash-кеш (PEP 552):
    непроверяемый берётся всегда, проверяемый — по хешу исходника.
    """
    h = header(pyc)
    if h is None or h[0] != importlib.util.MAGIC_NUMBER:
        return False
    _magic, flags, a, b = h
    if flags & FLAG_HASH:
        if not flags & FLAG_CHECKED:
            return True
        try:
            with open(src, "rb") as f:
                return struct.pack("<II", a, b) == \
                    importlib.util.source_hash(f.read())
        except OSError:
            return False
    try:
        st = os.stat(src)
    except OSError:
        return False
    return a == int(st.st_mtime) & 0xFFFFFFFF and b == st.st_size & 0xFFFFFFFF


def _defs(code):
    """Код каждого объявления верхнего уровня: {имя: код}.

    Нужен не для вердикта (его выносит сравнение модуля целиком), а для
    ИМЕНИ: «кеш заслоняет `ceiling.py`» лечится так же, как «заслоняет
    `judge`», но второе сразу говорит, куда смотреть.
    """
    return {c.co_name: c for c in code.co_consts
            if isinstance(c, types.CodeType)}


def source_code(src):
    """Код, скомпилированный из ИСХОДНИКА на диске."""
    with open(src, encoding="utf-8") as f:
        text = f.read()
    return compile(text, src, "exec", dont_inherit=True)


def cached_code(pyc):
    """Код, лежащий в кеше, либо None, если кеш не разбирается."""
    try:
        with open(pyc, "rb") as f:
            raw = f.read()
        return marshal.loads(raw[HEADER:])
    except (OSError, ValueError, EOFError, TypeError):
        return None


def shadow(src):
    """Заслоняет ли кеш исходник. Находка С ЧИСЛАМИ либо None.

    `None` значит «не заслоняет», и это не то же самое, что «кеша нет»
    или «кеш устарел»: устаревший кеш питон перекомпилирует сам, вреда
    от него никакого. Опасен ровно тот, который питон считает свежим, а
    код в нём другой.

    Сравнивается код МОДУЛЯ ЦЕЛИКОМ, а не только объявления: правка
    одной константы верхнего уровня (`MAX_CORR = 0.95`) объявлений не
    трогает, а программу меняет.
    """
    pyc = cache_file(src)
    if not os.path.exists(pyc) or not looks_fresh(src, pyc):
        return None
    cached = cached_code(pyc)
    if cached is None:
        return None
    try:
        fresh = source_code(src)
    except (OSError, SyntaxError):
        return None
    if cached == fresh:
        return None
    a, b = _defs(cached), _defs(fresh)
    differ = sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))
    return {"source": src, "cache": pyc,
            "differ": differ or ["<уровень модуля>"],
            "defs_in_source": len(b), "defs_in_cache": len(a),
            "bytes": os.path.getsize(pyc)}


def find_shadows(sources):
    """Находки по списку исходников, в порядке имён."""
    out = []
    for s in sorted(set(sources)):
        f = shadow(s)
        if f:
            out.append(f)
    return out


def loaded_here(base=HERE, mods=None):
    """Исходники модулей этого каталога, УЖЕ загруженных в процесс.

    Спрашивать надо про них, а не про весь каталог: заслон опасен там,
    где код исполняется, и список «что я импортировал» точнее любого
    перечня, который разойдётся с кодом при первом же новом импорте.
    """
    base = os.path.abspath(base)
    out = []
    for m in list((sys.modules if mods is None else mods).values()):
        f = getattr(m, "__file__", None) or ""
        if f.endswith(".py") and os.path.dirname(os.path.abspath(f)) == base:
            out.append(os.path.abspath(f))
    return out


def clear(finds):
    """Убрать заслоняющие кеши. Возвращает список убранных путей.

    Удаляется ТОЛЬКО `.pyc` внутри `__pycache__` — порождённое питоном и
    восстановимое им же. Всё прочее пропускается молча-не-молча: путь,
    не похожий на кеш, возвращается отдельным списком, а не удаляется на
    всякий случай.
    """
    gone, refused = [], []
    for f in finds:
        p = f.get("cache") if isinstance(f, dict) else f
        if not p or not p.endswith(".pyc") \
                or os.path.basename(os.path.dirname(p)) != "__pycache__":
            refused.append(p)
            continue
        try:
            os.remove(p)
            gone.append(p)
        except OSError:
            refused.append(p)
    return gone, refused


def describe(f):
    """Находка словами и числами."""
    return (f"{f['source']}: кеш {os.path.basename(f['cache'])} питон "
            f"считает свежим, а код в нём другой — расходятся "
            f"{', '.join(f['differ'])} "
            f"(объявлений в исходнике {f['defs_in_source']}, в кеше "
            f"{f['defs_in_cache']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sources", nargs="*",
                    help="исходники; по умолчанию весь каталог фабрики")
    ap.add_argument("--clear", action="store_true",
                    help="убрать заслоняющие кеши")
    a = ap.parse_args(argv)
    srcs = a.sources or [os.path.join(HERE, f) for f in os.listdir(HERE)
                         if f.endswith(".py")]
    finds = find_shadows(srcs)
    if not finds:
        print(f"заслоняющего байткода нет ({len(srcs)} исходников "
              f"просмотрено)")
        return 0
    for f in finds:
        print(describe(f))
    if not a.clear:
        # Отказ, а не тишина: молчаливый ноль здесь означал бы, что
        # прогоны идут прежним кодом и никто об этом не узнает.
        print(f"заслонено исходников: {len(finds)} — убрать: "
              f"python3 research/factory/pycguard.py --clear")
        return 1
    gone, refused = clear(finds)
    print(f"убрано кешей: {len(gone)}"
          + ("" if not refused else f"; не тронуто (не кеш): {refused}"))
    return 0 if not refused else 1


if __name__ == "__main__":
    raise SystemExit(main())
