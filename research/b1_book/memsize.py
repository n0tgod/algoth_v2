#!/usr/bin/env python3
"""Перепись памяти сборщика: кто сколько держит — числом, по структурам.

Повод (06.10). Сборщик держал 2.4 ГБ из 7.7 на машине, и пять суток
никто не знал, ЧТО именно: `status` печатал RSS целиком, а внутри —
десятки кэшей и колец. Виновник (посекундная история детектора, 1.9 ГБ
кортежами) нашёлся ручным опытом на стенде. Эта перепись делает то же
на живом процессе: по каждой известной структуре — число элементов и
оценка байтов, рядом RSS процесса и неучтённый остаток (интерпретатор,
модули, фрагментация аллокатора).

Оценка, а не мера: контейнеры длиннее `SAMPLE` меряются по первым
`SAMPLE` элементам с экстраполяцией; общие объекты не считаются дважды
внутри одного обхода; массивы numpy — по `nbytes`. Для точного ответа
«кто аллоцирует» есть `tracemalloc` (`trace=start|top|stop`): он дорог
(удваивает память отслеживаемых объектов), поэтому включается руками и
на короткое окно, и отказывает, когда процессу и так тесно.
"""
import gc
import sys
import threading
import time
import tracemalloc
from collections import Counter, deque
from itertools import islice

import numpy as np

SAMPLE = 256
MAX_DEPTH = 14
TRACE_RSS_MAX_MB = 2500
TRACE_AUTO_STOP_SEC = 20 * 60


def rss_mb():
    try:
        with open("/proc/self/status") as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    return int(ln.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def deep_size(obj, seen=None, sample=SAMPLE, depth=0):
    """Байты объекта с содержимым — оценка с выборкой у длинных контейнеров."""
    if seen is None:
        seen = set()
    oid = id(obj)
    if oid in seen:
        return 0
    seen.add(oid)
    if isinstance(obj, np.ndarray):
        return int(obj.nbytes) + 112
    size = sys.getsizeof(obj)
    if depth >= MAX_DEPTH or isinstance(obj, (str, bytes, int, float, bool,
                                              type(None))):
        return size
    if isinstance(obj, dict):
        n = len(obj)
        if not n:
            return size
        took = list(islice(obj.items(), sample))
        part = sum(deep_size(k, seen, sample, depth + 1)
                   + deep_size(v, seen, sample, depth + 1) for k, v in took)
        return size + int(part * (n / len(took)))
    if isinstance(obj, (list, tuple, set, frozenset, deque)):
        n = len(obj)
        if not n:
            return size
        took = list(islice(obj, sample))
        part = sum(deep_size(x, seen, sample, depth + 1) for x in took)
        return size + int(part * (n / len(took)))
    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict):
        size += deep_size(d, seen, sample, depth + 1)
    for cls in type(obj).__mro__:
        for slot in getattr(cls, "__slots__", ()):
            if slot in ("__dict__", "__weakref__"):
                continue
            try:
                size += deep_size(getattr(obj, slot), seen, sample, depth + 1)
            except AttributeError:
                continue
    return size


# Что переписывается у сборщика: имя для отчёта → атрибут. Список
# держится здесь, а не в `collect.py`: перепись — инструмент диагностики,
# и кэш, забытый в этом списке, виден по неучтённому остатку.
PARTS = (
    ("signals.by (детектор: кольца секунд, сделки, уровни)", "sig.by"),
    ("mid (середина для страницы, 15 мин × имя)", "mid"),
    ("tape (лента для страницы, 120 × имя)", "tape"),
    ("books (стаканы)", "books"),
    ("ccache (свечи закрытых часов)", "ccache"),
    ("hcache (тепловая карта закрытых часов)", "hcache"),
    ("_px_cache (цены входа по имени и часу)", "_px_cache"),
    ("_dca_parts (журналы DCA-книг разобранные)", "_dca_parts"),
    ("_model_cache (ответ /model)", "_model_cache"),
    ("_league_cache", "_league_cache"),
    ("_dca_cache (ответ /dca)", "_dca_cache"),
    ("_paper_cache", "_paper_cache"),
    ("_learn_cache", "_learn_cache"),
    ("_vol_cache", "_vol_cache"),
    ("_volmod_cache", "_volmod_cache"),
    ("_tour_cache", "_tour_cache"),
    ("_agents_cache", "_agents_cache"),
    ("_built_cache", "_built_cache"),
    ("_gloss_cache", "_gloss_cache"),
    ("_bdays_cache", "_bdays_cache"),
    ("_asks_cache", "_asks_cache"),
    ("_extras_cache", "_extras_cache"),
    ("_live_exec_cache", "_live_exec_cache"),
    ("_noise_cache", "_noise_cache"),
    ("px_ext", "px_ext"),
    ("lines (журнал страницы)", "lines"),
    ("rec (пересчёт)", "rec"),
    ("groups", "groups"),
    ("disk", "disk"),
    ("shards (соединения)", "shards"),
)


def _get(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _count(v):
    try:
        return len(v)
    except TypeError:
        return 1


def census(c, deep=False):
    """Перепись структур сборщика `c`: части, сумма, RSS, неучтённое."""
    t0 = time.time()
    parts = {}
    total = 0
    # Один набор «виденного» на всю перепись, и сам сборщик в нём с
    # самого начала: `Shard.c` ссылается назад на сборщик, и без этого
    # размер «соединений» вбирал бы в себя весь процесс — объект,
    # посчитанный в ранней части, в поздней не считается второй раз.
    seen = {id(c)}
    for name, attr in PARTS:
        v = _get(c, attr)
        if v is None:
            continue
        b = deep_size(v, seen)
        total += b
        parts[name] = {"n": _count(v), "mb": round(b / 2 ** 20, 1)}
    # Всё остальное у сборщика — автоматически: кэш, забытый в `PARTS`,
    # обязан быть виден здесь, а не в неучтённом остатке. Простые
    # значения (числа, строки, замки) пропускаются.
    known = {attr.split(".")[0] for _, attr in PARTS}
    others = []
    for name, v in list(vars(c).items()):
        if name in known or v is None or isinstance(v, (int, float, str, bool)):
            continue
        b = deep_size(v, seen)
        total += b
        if b >= 64 * 1024:
            others.append((b, name, _count(v)))
    for b, name, n in sorted(others, reverse=True)[:12]:
        parts[f"прочее: {name}"] = {"n": n, "mb": round(b / 2 ** 20, 1)}
    # Кеш разобранных журналов живёт на КЛАССЕ, не на экземпляре —
    # `vars(c)` его не видит, а 06.10 именно он держал 1.3 ГБ.
    jc = getattr(type(c), "_JSONL_CACHE", None)
    if isinstance(jc, dict):
        ents = []
        for path, e in jc.items():
            est = int(e.get("est") or 0)
            ents.append((est, path, e))
        tot = sum(x[0] for x in ents)
        total += tot
        parts["_JSONL_CACHE (разобранные журналы книг, класс)"] = {
            "n": len(ents), "mb": round(tot / 2 ** 20, 1),
            "budget_mb": round(getattr(type(c), "_JSONL_BUDGET", 0) / 2 ** 20),
            "stats": dict(getattr(type(c), "_JSONL_STATS", {}) or {}),
            "top": [{"file": "/".join(p.rsplit("/", 2)[-2:]),
                     "rows": len(e.get("rows") or ()),
                     "mb": round(est / 2 ** 20, 1),
                     "file_mb": round((e.get("sig") or (0, 0))[1] / 2 ** 20, 1)}
                    for est, p, e in sorted(ents, reverse=True)[:8]]}
    sig = _get(c, "sig.by") or {}
    n_sec = sum(len(getattr(l, "sec", ())) for l in sig.values())
    ring = sum(int(getattr(getattr(l, "sec", None), "nbytes", 0) or 0)
               for l in sig.values())
    parts["  из них кольца секунд (точно, nbytes)"] = {
        "n": n_sec, "mb": round(ring / 2 ** 20, 1)}
    wf = _get(c, "w.files")
    out = {"at": round(t0, 1), "rss_mb": rss_mb(), "parts": parts,
           "sum_mb": round(total / 2 ** 20, 1),
           "open_files": len(wf) if wf is not None else None,
           "threads": threading.active_count(),
           "took_ms": None}
    if out["rss_mb"] is not None:
        out["unaccounted_mb"] = round(out["rss_mb"] - total / 2 ** 20, 1)
        out["note"] = ("неучтённое — интерпретатор, модули, numpy, буферы "
                       "сокетов и фрагментация аллокатора; части — оценка "
                       f"по выборке {SAMPLE}")
    if deep:
        objs = gc.get_objects()
        hist = Counter(type(o).__name__ for o in objs)
        out["gc_objects"] = len(objs)
        out["types_top"] = hist.most_common(25)
        del objs
    out["trace"] = trace_state()
    out["took_ms"] = round((time.time() - t0) * 1000)
    return out


_TRACE = {"since": None}


def trace_state():
    if not tracemalloc.is_tracing():
        return {"on": False}
    cur, peak = tracemalloc.get_traced_memory()
    return {"on": True, "since": _TRACE["since"],
            "traced_mb": round(cur / 2 ** 20, 1),
            "peak_mb": round(peak / 2 ** 20, 1)}


def trace_control(cmd, top=25, now=None, rss=None):
    """`start` / `top` / `stop` для tracemalloc — с отказом, когда тесно.

    Авто-остановка: трассировка старше `TRACE_AUTO_STOP_SEC` гасится при
    любом обращении — забытая, она удваивала бы память процесса часами.
    """
    now = now if now is not None else time.time()
    rss = rss if rss is not None else rss_mb()
    if tracemalloc.is_tracing() and _TRACE["since"] \
            and now - _TRACE["since"] > TRACE_AUTO_STOP_SEC:
        tracemalloc.stop()
        _TRACE["since"] = None
        auto = "трассировка старше предела — остановлена сама"
    else:
        auto = None
    if cmd == "start":
        if tracemalloc.is_tracing():
            return {"ok": True, "note": "уже идёт", **trace_state()}
        if rss is not None and rss > TRACE_RSS_MAX_MB:
            return {"ok": False, "note": f"отказ: RSS {rss} МБ выше "
                    f"{TRACE_RSS_MAX_MB} — трассировка удвоила бы память"}
        tracemalloc.start(3)
        _TRACE["since"] = now
        return {"ok": True, "note": "включена (3 кадра)", **trace_state()}
    if cmd == "stop":
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        _TRACE["since"] = None
        return {"ok": True, "note": auto or "остановлена", "on": False}
    if cmd == "top":
        if not tracemalloc.is_tracing():
            return {"ok": False, "note": auto or "не идёт — сперва start"}
        snap = tracemalloc.take_snapshot()
        rows = []
        for st in snap.statistics("lineno")[:top]:
            fr = st.traceback[0]
            rows.append({"mb": round(st.size / 2 ** 20, 1), "n": st.count,
                         "where": f"{fr.filename.rsplit('/', 1)[-1]}:{fr.lineno}"})
        return {"ok": True, "top": rows, **trace_state()}
    return {"ok": False, "note": f"неизвестная команда: {cmd!r}"}
