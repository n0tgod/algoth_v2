#!/usr/bin/env python3
"""Книги модели спеки 19 §12 над записями книги: одно место применения.

Фильтр (`skip`): записи основной книги Depth Short с часа рождения, без
входов, которым правило книги сказало skip. Решения пишет проход судьи
(`gate_run`) строками ветви с именем книги (`m01`, …) — тот же журнал и те
же функции, что у веток судьи (`gate_books.entry_index`, `filt`).

ТВХ (`entry`): записи своего реплея (`model_books.tick` — сдвинутые входы
тем же `run_short.replay_cells`), кэш `cache/recs-model.jsonl` с подписью
книги; здесь они только читаются.

Отставленная книга (`retired_at`) новых входов не берёт: позиции с часом
входа после отставки не идут в кассу, открытые доживают до выхода.

Журнала или кэша нет — книга пуста, а причина идёт в свод словами (`why`):
пустая книга молча выглядела бы «правило всё отсекло».
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GATE = os.path.join(ROOT, "research", "ai_gate")
if GATE not in sys.path:
    sys.path.insert(0, GATE)

CACHE = os.path.join(HERE, "cache", "recs-model.jsonl")


def window(recs, b):
    """Записи книги в её окне жизни: с часа рождения, до отставки."""
    lo = float(b["born_at"])
    hi = float(b["retired_at"]) if b.get("retired_at") else None
    return [r for r in recs if float(r.get("at", 0)) >= lo and (hi is None or float(r.get("at", 0)) < hi)]


def apply_skip(recs, key, log=print, rows=None):
    """→ (записи книги-фильтра, свод: убрано, без решения, why)."""
    import rules as R                                          # noqa: E402
    b = R.MODEL_BOOKS.get(key)
    if not b or b.get("kind") != "skip":
        return recs, None
    recs = window(recs, b)
    try:
        import gate_books as GB                                # noqa: E402
        import gate_run as G                                   # noqa: E402
        if rows is None:
            import ai_branch as AIB                            # noqa: E402
            rows = AIB._decisions()
    except Exception as e:                                     # noqa: BLE001
        why = f"журнал решений не прочитан: {type(e).__name__}: {e}"[:200]
        log(f"{key}: {why} — записи как у {R.MODEL_BASE}")
        return recs, {"why": why, "cut": 0, "unjudged": None}
    dec = GB.entry_index(rows).get(b["id"], {})
    kept, cut, unj = GB.filt(recs, R.MODEL_BASE, dec)
    log(f"{key}: правило убрало {cut} входов из {len(recs)}, без решения {unj}")
    return kept, {"why": None if dec else "решений правила ещё нет", "cut": cut, "unjudged": unj,
                  "start": float(b["born_at"])}


def read_cache(path=None, log=print):
    """{(книга, имя, момент): запись} кэша реплея книг ТВХ; подпись — книги."""
    import run_paper as RP                                     # noqa: E402
    import run_short as S                                      # noqa: E402
    cache, why = RP.read_cache(path or CACHE, sig=S.cache_sig())
    if why:
        log(f"кэш книг ТВХ модели не используется: {why}")
    out = {}
    for (pair, sym, at), r in cache.items():
        bid = pair[0] if isinstance(pair, (list, tuple)) else pair
        out[(bid, sym, at)] = r
    return out, why


def write_cache(cache, path=None):
    import run_paper as RP                                     # noqa: E402
    import run_short as S                                      # noqa: E402
    path = path or CACHE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    RP.write_cache({((bid,), sym, at): r for (bid, sym, at), r in cache.items()}, path=path, sig=S.cache_sig())


def entry_recs(key, cache=None, log=print):
    """→ (записи книги ТВХ до возраста и охраны, why)."""
    import rules as R                                          # noqa: E402
    b = R.MODEL_BOOKS.get(key)
    if not b or b.get("kind") != "entry":
        return [], "не книга ТВХ модели"
    if cache is None:
        cache, why = read_cache(log=log)
        if why and not cache:
            return [], why
    mine = [r for (bid, _s, _a), r in cache.items() if bid == b["id"]]
    mine = window(mine, b)
    # ранний выход по смене состояния (§11.11): решения книги из её состояния,
    # закрытие на отметке часа после решения тем же ядром, что сторож и охрана
    if b.get("close_rules"):
        import model_books as MBK                              # noqa: E402
        try:
            with open(MBK.ENTRY_STATE, encoding="utf-8") as f:
                estate = json.load(f)
        except (OSError, ValueError):
            estate = {}
        mine, n_cl = MBK.apply_closes(mine, b, estate, R.RULE_EXIT)
        if n_cl:
            log(f"{key}: ранних выходов по состоянию {n_cl}")
    return sorted(mine, key=lambda r: float(r["at"])), (None if mine else "входов по правилу ещё не было")

