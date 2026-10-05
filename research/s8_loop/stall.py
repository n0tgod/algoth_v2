#!/usr/bin/env python3
"""Стоит ли обучение S8 — одно правило для сторожа, `status` и страницы.

Повод. Обучение не шло с 30.09 05:27 по 04.10 21:46 — 109 часов при
каденции 24, — и ни одна поверхность этого не называла: цикл честно
писал «обучение отложено по памяти» в лог, который никто не читает,
книги считались на старых весах, страницы были исправны. Класс
отказа — исправность, неотличимая от поломки.

Правило одно и живёт здесь, чтобы сторож (`tools/train_alarm.py`),
`status` и страница обучения не разошлись в числе: веса старше
`STALL_H` часов — тревога. Порог — полторы каденции: один пропуск по
памяти законен и объявлен в самом цикле, второй подряд — уже стояние.
«Не измерено» (манифеста нет, время не разобрано) — не ноль и не
тревога: отдельная строка с причиной.
"""
import json
import os
from datetime import datetime, timezone

# Каденция обучения — та же, что `train.TRAIN_EVERY_H`; дублируется
# числом, потому что импорт `train` стоит секунды и тянет numpy, а
# сторож зовёт это каждые пять минут. Равенство держит проверка.
CADENCE_H = 24
STALL_H = 36


def read_state(mdir):
    """(манифест, исход последнего цикла) с диска; нет файла — None."""
    out = []
    for name in ("manifest.json", "last_run.json"):
        try:
            with open(os.path.join(mdir, name), encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            out.append(None)
    return out[0], out[1]


def stall_of(manifest, last_run, now, threshold_h=None):
    """Состояние обучения словами и числами.

    Возвращает словарь: `measured` — есть ли мера (время обучения
    прочитано), `age_h` — возраст весов, `stalled` — возраст не меньше
    порога, `threshold_h`, `trained_at`, и из исхода последнего цикла —
    `last_at`, `last_why` (почему цикл не учился: «отложено по
    памяти…», «пропущено по каденции…»).
    """
    if threshold_h is None:
        threshold_h = STALL_H
    st = {"measured": False, "stalled": False, "age_h": None,
          "threshold_h": threshold_h, "cadence_h": CADENCE_H,
          "trained_at": None, "last_at": None, "last_why": None,
          "note": None}
    lr = last_run or {}
    st["last_at"] = lr.get("at")
    st["last_why"] = lr.get("train_why") or lr.get("reason")
    if not manifest:
        st["note"] = "манифеста весов нет — обучения не было ни разу или каталог другой"
        return st
    at = manifest.get("trained_at")
    if not at:
        st["note"] = "манифест без времени обучения"
        return st
    try:
        t = datetime.fromisoformat(at).timestamp()
    except (TypeError, ValueError):
        st["note"] = f"время обучения не разобрано: {at!r}"
        return st
    st["measured"] = True
    st["trained_at"] = at
    st["age_h"] = round((now - t) / 3600.0, 1)
    st["stalled"] = st["age_h"] >= threshold_h
    return st


def line(st):
    """Строка для `status` и сторожа — вердикт выводится из числа."""
    if not st["measured"]:
        return f"обучение S8: не измерено — {st['note']}"
    at = (st["trained_at"] or "")[:16].replace("T", " ")
    head = (f"обучение S8: веса от {at} UTC, {st['age_h']} ч назад "
            f"(каденция {st['cadence_h']}, тревога с {st['threshold_h']} ч)")
    if st["stalled"]:
        head = "ТРЕВОГА " + head + " — обучение стоит"
    if st["last_why"]:
        when = (st["last_at"] or "")[11:16]
        head += f"; последний цикл {when} UTC: {st['last_why']}"
    return head
