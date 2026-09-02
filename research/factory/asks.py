#!/usr/bin/env python3
"""Чего система ждёт ОТ ВЛАДЕЛЬЦА — журнал и его состояние.

Агент не может завести аккаунт, оплатить доступ, положить ключ и
принять решение о деньгах. Пока такой просьбы нет в одном месте, она
живёт в прозе отчёта, который читают один раз: система молча стоит, а
снаружи это спокойный день — тот самый отказ, неотличимый от тишины.

Журнал append-only, как все журналы проекта: просьба записывается один
раз (повтор по ключу не пишется), закрывается ОТДЕЛЬНОЙ записью. У
просьбы есть ПРОВЕРКА — путь, по существованию которого машина сама
видит, что дело сделано. Проверки нет — состояние решает слово
владельца, и это говорится прямо, а не выдаётся за измерение.

    python3 research/factory/asks.py                 # показать
    python3 research/factory/asks.py --done ID       # закрыть словом
"""
import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ASKS = "asks.jsonl"
MIN_WHAT = 20
MIN_WHY = 40


def key_of(what):
    """Ключ просьбы: одна и та же просьба не задаётся дважды."""
    t = " ".join((what or "").lower().split())
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:8]


def read(out):
    """Строки журнала. Битая строка считается, а не глотается."""
    rows, broken = [], 0
    p = os.path.join(out, ASKS)
    if not os.path.exists(p):
        return rows, broken
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except ValueError:
                broken += 1
    return rows, broken


def append(out, rec):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, ASKS), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def record(out, items, src):
    """Записать просьбы роли. Возвращает число НОВЫХ.

    Дубль по ключу не пишется: одна и та же просьба, повторённая
    каждым кругом, превращает страницу в шум, а шум не читают.
    """
    rows, _ = read(out)
    was = {r.get("id") for r in rows}
    n = 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        what = (it.get("what") or "").strip()
        why = (it.get("why") or "").strip()
        if len(what) < MIN_WHAT or len(why) < MIN_WHY:
            continue
        k = key_of(what)
        if k in was:
            continue
        was.add(k)
        rec = {"ev": "ask", "at": round(time.time(), 3), "id": k,
               "from": src, "what": what, "why": why}
        for f in ("unblocks", "check"):
            v = (it.get(f) or "").strip()
            if v:
                rec[f] = v
        append(out, rec)
        n += 1
    return n


def done(out, ask_id, note=""):
    """Закрыть просьбу словом владельца. Отдельная запись, не правка."""
    rows, _ = read(out)
    ids = {r.get("id") for r in rows if r.get("ev") == "ask"}
    if ask_id not in ids:
        return False
    append(out, {"ev": "done", "at": round(time.time(), 3),
                 "id": ask_id, "note": note or ""})
    return True


def checked(path, root=ROOT):
    """Проверка просьбы: (есть ли ответ, чем проверено).

    Проверка — существование файла. Команду сюда пускать нельзя:
    страницу читает тот же процесс, что ведёт запись стакана.
    """
    if not path:
        return None, "проверять нечем — состояние по слову владельца"
    p = path if os.path.isabs(path) else os.path.join(root, path)
    p = os.path.expanduser(p)
    return os.path.exists(p), "проверено сейчас: %s" % path


def state(out, root=ROOT, now=None):
    """Просьбы с состоянием, свежие первыми.

    Состояние считается СЕЙЧАС, а не хранится: сохранённое «сделано»
    старело бы молча, а ключ, который потом убрали, выглядел бы живым.
    """
    rows, broken = read(out)
    said = {r.get("id"): r for r in rows if r.get("ev") == "done"}
    out_rows = []
    for r in rows:
        if r.get("ev") != "ask":
            continue
        ok, how = checked(r.get("check"), root)
        d = said.get(r.get("id"))
        rec = dict(r)
        rec["check_ok"] = ok
        rec["check_how"] = how
        rec["said_done"] = bool(d)
        if d:
            rec["done_at"] = d.get("at")
            rec["done_note"] = d.get("note") or ""
        # Машина видит ответ либо владелец сказал слово. Порядок
        # важен: проверка сильнее слова — файл, которого нет, не
        # становится существующим оттого, что о нём сказали.
        rec["open"] = not (ok is True or (ok is None and d))
        out_rows.append(rec)
    out_rows.sort(key=lambda r: r.get("at") or 0, reverse=True)
    return out_rows, broken


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--done", metavar="ID")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.done:
        ok = done(a.out, a.done, a.note)
        print("закрыта: %s" % a.done if ok else
              "нет такой просьбы: %s" % a.done)
        return 0 if ok else 1
    rows, broken = state(a.out)
    print("просьб: %d, битых строк: %d" % (len(rows), broken))
    for r in rows:
        mark = "ЖДЁТ" if r["open"] else "сделано"
        print("%-8s %-7s %s" % (r["id"], mark, r["what"][:70]))
        print("         зачем: %s" % r["why"][:80])
        print("         %s" % r["check_how"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
