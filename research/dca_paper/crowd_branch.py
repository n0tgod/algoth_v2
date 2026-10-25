#!/usr/bin/env python3
"""Ветвь с гейтом толпы (спека 18, ось `crowd`; владелец 25.10).

Вход короткой книги не берётся, когда толпа Bybit уже в шорте: доля
длинных счетов (`buyRatio` записи состояния рынка, `research/market_state`)
последней строкой не позже часа сигнала ≤ порога ветви. Поля нет — вход как
у основной книги, и это считается отдельно («не измерено» ≠ «толпа в лонге»).

Правило меняет СОСТАВ входов, не исход позиции — поэтому это вид над
записью основной книги, как охрана и судья: кэш реплея не трогается,
записи те же, что у основной книги. Замер — `research/ai_gate/crowd_gate.py`
(25.10: гейт держит обе половины, вперёд и неделю пампов).

Толпа читается из той же записи и тем же правилом «последняя строка не
позже момента», что досье судьи (`context.crowd_of`), но через компактный
кэш: файл дня записи состояния несёт все источники и новости (гигабайты за
месяц), а ветви нужны только строки Bybit — `cache/crowd/<день>.jsonl`
пересобирается, когда файл дня записи изменился (докачка пишет в прошлые
дни).
"""
import bisect
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MS_RECORD = os.path.join(ROOT, "research", "market_state", "out", "record")
CACHE_DIR = os.path.join(HERE, "cache", "crowd")
SRC = "bybit"
FIELD = "long"
_MEM = {"key": None, "idx": None}


def _compact_path(day, cache_dir):
    return os.path.join(cache_dir, f"{day}.jsonl")


def compact(record_dir=MS_RECORD, cache_dir=CACHE_DIR, log=None):
    """Строки толпы Bybit по дням записи → компактные файлы; → список путей."""
    out = []
    try:
        days = sorted(p for p in os.listdir(record_dir) if p.startswith("state-") and p.endswith(".jsonl"))
    except OSError:
        return out
    os.makedirs(cache_dir, exist_ok=True)
    for name in days:
        src = os.path.join(record_dir, name)
        day = name[len("state-"):-len(".jsonl")]
        dst = _compact_path(day, cache_dir)
        st = os.stat(src)
        stamp = {"mtime": int(st.st_mtime), "size": st.st_size}
        head = None
        try:
            with open(dst, encoding="utf-8") as f:
                head = json.loads(f.readline())
        except (OSError, ValueError):
            head = None
        if head and head.get("src") == stamp:
            out.append(dst)
            continue
        rows = []
        with open(src, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("src") == SRC and r.get("sym") and r.get(FIELD) is not None and r.get("t") is not None:
                    rows.append([r["sym"], int(r["t"]), float(r[FIELD])])
        tmp = dst + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"src": stamp, "rows": len(rows)}) + "\n")
            for r in rows:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, dst)
        if log:
            log(f"толпа: {day} — {len(rows)} строк Bybit в компактный кэш")
        out.append(dst)
    return out


def index(record_dir=MS_RECORD, cache_dir=CACHE_DIR, log=None):
    """{sym: ([t_ms по возрастанию], [доля длинных])} из компактных файлов; в памяти, пока файлы те же."""
    paths = compact(record_dir, cache_dir, log=log)
    key = tuple((p, os.path.getmtime(p)) for p in paths)
    if _MEM["key"] == key:
        return _MEM["idx"]
    by = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            f.readline()
            for line in f:
                try:
                    sym, t, v = json.loads(line)
                except ValueError:
                    continue
                by.setdefault(sym, []).append((t, v))
    idx = {}
    for sym, rows in by.items():
        rows.sort()
        idx[sym] = ([t for t, _v in rows], [v for _t, v in rows])
    _MEM.update(key=key, idx=idx)
    return idx


def long_share(idx, sym, at_s):
    """Доля длинных в толпе последней строкой не позже момента (как `context.crowd_of`); нет — None."""
    rows = idx.get(sym)
    if not rows:
        return None
    ts, vs = rows
    i = bisect.bisect_right(ts, int(float(at_s) * 1000))
    return vs[i - 1] if i > 0 else None


def apply(recs, key, log=print, idx=None):
    """→ (записи ветви, свод: снято, не измерено, порог, why)."""
    import rules as R                                          # noqa: E402
    cap = R.crowd_cap_of(key)
    if cap is None:
        return recs, None
    try:
        idx = index(log=log) if idx is None else idx
    except Exception as e:                                     # noqa: BLE001
        why = f"запись толпы не прочитана: {type(e).__name__}: {e}"[:200]
        log(f"{key}: {why} — записи как у {R.base_of(key)}")
        return recs, {"why": why, "cut": 0, "unmeasured": None, "cap": cap}
    out, cut, unm = [], 0, 0
    for r in recs:
        v = long_share(idx, r["sym"], float(r["at"]))
        if v is None:
            unm += 1
        elif v <= cap:
            cut += 1
            continue
        out.append(r)
    why = None if idx else "записи толпы нет — записи как у основной книги"
    log(f"{key}: толпа ≤ {cap:g} сняла {cut} входов из {len(recs)}; без поля {unm}" + (f"; {why}" if why else ""))
    return out, {"why": why, "cut": cut, "unmeasured": unm, "cap": cap, "names": len(idx)}
