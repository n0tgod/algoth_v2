"""Самоограничитель памяти сборщика (починка 10.10).

Дефект. Сборщик рос до 2.3 ГБ за 4–5 часов и погибал от ядра (OOM
03:01 UTC 10.10; за 09.10 — 15 убийств), хотя перепись `/mem`
насчитывала в его структурах ~1.1 ГБ: кеш журналов книг тасовался (290
полных разборов за 2.5 ч, выброшено 11.7 ГБ объектов), и остаток —
фрагментация аллокатора — рос молча до 630 МБ. Сторож перезапускал по
потолку 2500 МБ, которого процесс не доживал: рядом стояли прогоны, и
ядро выбирало его раньше. Класс ошибки — предел снаружи у процесса,
который обязан держать себя сам (урок «предел памяти и самоостанов — в
самом прогоне»).

Правило. Раз в минуту читается RSS. Выше МЯГКОГО порога сбрасываются
кеши страниц и журналов, собирается мусор и память возвращается ядру
(`malloc_trim(0)` glibc: иначе освобождённые объекты остаются в аренах
и RSS не падает). Если и после этого RSS выше ЖЁСТКОГО порога — процесс
просит себя остановиться (SIGTERM: тот же путь, что у деплоя — запись
закрывается, сторож поднимает за 5 мин). Каждое действие — строкой в
лог с числами ДО и ПОСЛЕ и счётчиком в `/mem` и `status.json`: сброс,
которого никто не видел, неотличим от тишины.

Пороги — из бюджета машины (7745 МБ, гейт обучения 3072, цикл до
1.6 ГБ, прогоны книг 1.2): мягкий 1700 — там, где перепись 10.10
показала 1719 через 2.5 ч при учтённых 1090; жёсткий 2100 — ниже
убившего ядра 2296 с запасом на минуту роста.
"""
import ctypes
import gc
import os
import signal
import time

SOFT_MB = 1700
HARD_MB = 2100


def rss_mb():
    """RSS процесса по `/proc/self/status`; None — не прочитан."""
    try:
        with open("/proc/self/status") as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    return int(ln.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def malloc_trim():
    """Вернуть ядру свободные страницы арен glibc. 1 — что-то вернулось,
    0 — нечего, None — не glibc (не измерено, не ноль)."""
    try:
        libc = ctypes.CDLL("libc.so.6")
        return int(libc.malloc_trim(0))
    except (OSError, AttributeError):
        return None


def ask_stop():
    """Остановиться тем же путём, что при деплое: SIGTERM себе."""
    os.kill(os.getpid(), signal.SIGTERM)


class MemGuard:
    def __init__(self, drop, rss=rss_mb, trim=malloc_trim, die=ask_stop, log=print,
                 soft_mb=SOFT_MB, hard_mb=HARD_MB):
        self.drop, self.rss, self.trim, self.die, self.log = drop, rss, trim, die, log
        self.soft, self.hard = int(soft_mb), int(hard_mb)
        self.stats = {"ticks": 0, "unmeasured": 0, "drops": 0, "dies": 0,
                      "last_rss_mb": None, "max_rss_mb": None,
                      "last_drop": None, "trim_total_mb": 0}

    def tick(self):
        """Один такт: вернуть, что сделано. Чистая логика вокруг вызовов."""
        st = self.stats
        st["ticks"] += 1
        r = self.rss()
        if r is None:
            st["unmeasured"] += 1
            return {"rss_mb": None, "action": "не измерено"}
        st["last_rss_mb"] = r
        st["max_rss_mb"] = r if st["max_rss_mb"] is None else max(st["max_rss_mb"], r)
        if r <= self.soft:
            return {"rss_mb": r, "action": None}
        dropped = self.drop() or {}
        gc.collect()
        trimmed = self.trim()
        after = self.rss()
        st["drops"] += 1
        freed = (r - after) if after is not None else None
        if freed is not None:
            st["trim_total_mb"] += max(0, freed)
        st["last_drop"] = {"at": time.time(), "before_mb": r, "after_mb": after,
                           "dropped": dropped, "trim": trimmed}
        self.log(f"ПАМЯТЬ: RSS {r} МБ выше мягкого порога {self.soft} — кеши сброшены "
                 f"({', '.join(f'{k} {v}' for k, v in dropped.items()) or 'нечего'}), "
                 f"malloc_trim {trimmed}, после {after if after is not None else '—'} МБ")
        if after is not None and after > self.hard:
            st["dies"] += 1
            self.log(f"ПАМЯТЬ: RSS {after} МБ выше жёсткого порога {self.hard} после сброса — "
                     "останавливаюсь, сторож поднимет")
            self.die()
            return {"rss_mb": r, "after_mb": after, "action": "stop"}
        return {"rss_mb": r, "after_mb": after, "action": "drop"}
