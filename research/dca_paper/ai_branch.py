#!/usr/bin/env python3
"""Ветвь судьи спеки 19 над записями книги: одно место применения.

Записи основной книги → записи ветви `*_ai`: вход, которому модель с
новостями (`ai_news`) сказала skip, убирается; открытая позиция, которой
сторож сказал close, закрывается на отметке часа после решения по рынку
(`rules.JUDGE_EXIT`). Решения читаются из журнала записи вперёд
(`research/ai_gate/out/decisions/`), функции ветвей — те же, что считает
`gate_books.py` (одно ядро: `entry_index`, `close_index`, `filt`,
`apply_closes`).

Журнала нет или он не читается — записи остаются как у основной книги, а
причина идёт в свод словами (`why`): ветвь, совпавшая с книгой молча,
выглядела бы «судья ничего не убрал».
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GATE = os.path.join(ROOT, "research", "ai_gate")
if GATE not in sys.path:
    sys.path.insert(0, GATE)

_CACHE = {"sig": None, "rows": None}


def _decisions():
    import gate_run as G                                       # noqa: E402
    paths = sorted(os.listdir(G.DECISIONS)) if os.path.isdir(G.DECISIONS) else []
    sig = tuple((p, os.path.getmtime(os.path.join(G.DECISIONS, p))) for p in paths)
    if _CACHE["sig"] != sig:
        _CACHE.update(sig=sig, rows=G.read_decisions())
    return _CACHE["rows"]


def apply(recs, key, log=print):
    """→ (записи ветви, свод: убрано, без решения с дня рождения, закрыто сторожем, why)."""
    import rules as R                                          # noqa: E402
    if not R.is_ai(key):
        return recs, None
    base = R.AI_BRANCHES[key]
    # старт с нуля: позиции раньше старта ветви в её кассу не идут — депозит
    # чистый в момент старта, бэктеста у ветви нет (владелец 18.10)
    recs = [r for r in recs if float(r.get("at", 0)) >= R.AI_START_TS]
    try:
        import gate_books as GB                                # noqa: E402
        import gate_run as G                                   # noqa: E402
        rows = _decisions()
    except Exception as e:                                     # noqa: BLE001
        why = f"журнал решений судьи не прочитан: {type(e).__name__}: {e}"[:200]
        log(f"{key}: {why} — записи как у {base}")
        return recs, {"why": why, "cut": 0, "unjudged": None, "closes": 0}
    if not rows:
        return recs, {"why": "решений судьи ещё нет", "cut": 0, "unjudged": None, "closes": 0,
                      "start": R.AI_START_TS}
    dec = GB.entry_index(rows).get("ai_news", {})
    kept, cut, _unj = GB.filt(recs, base, dec)
    unjudged = sum(1 for r in recs if G.key_of(base, r) not in dec)
    out, n, _ks = GB.apply_closes(kept, base, GB.close_index(rows), R.JUDGE_EXIT)
    log(f"{key}: судья убрал {cut} входов, закрыл {n}; без решения с дня рождения {unjudged}")
    return out, {"why": None, "cut": cut, "unjudged": unjudged, "closes": n, "start": R.AI_START_TS}
