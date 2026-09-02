#!/usr/bin/env python3
"""Очередь МЕХАНИК: заявки, которых движок ещё не умеет.

Заявка предлагающего бывает двух видов. `row` — строка объявленного
пространства: её судят потолок и судья, и она объявляется кандидатом
сегодня же. `mechanism` — механика, которой у движка нет вовсе; такую
заявку раньше только записывали словами в `proposal.json`, а тот
перезаписывается следующим прогоном. То есть механика жила ровно сутки
и терялась — тот же дефект, что журнал разведчика из одних заголовков.

Здесь она живёт в журнале и ждёт строителя. Журнал append-only:
поставили в очередь одной записью, отдали строителю другой, закрыли
третьей. Состояние выводится перечитыванием, а не хранится.

    python3 research/factory/mech_queue.py            # показать очередь
    python3 research/factory/mech_queue.py --next     # задание строителю
"""
import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
QUEUE = "mechanisms.jsonl"
TASK = "build_task.md"
TASK_PREV = "build_task-prev.md"
MARK = "<!-- механика: %s -->"


def key_of(title):
    t = " ".join((title or "").lower().split())
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:8]


def read(out):
    rows, broken = [], 0
    p = os.path.join(out, QUEUE)
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
    with open(os.path.join(out, QUEUE), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def queue(out, prop, src="propose"):
    """Поставить механику из заявки. Возвращает ключ либо None.

    Повтор по ключу не ставится: механика, предложенная второй раз,
    заняла бы очередь дважды и строитель построил бы одно и то же.
    """
    if (prop or {}).get("kind") != "mechanism":
        return None
    title = (prop.get("title") or "").strip()
    if not title:
        return None
    k = key_of(title)
    rows, _ = read(out)
    if any(r.get("id") == k for r in rows if r.get("ev") == "queued"):
        return None
    rec = {"ev": "queued", "at": round(time.time(), 3), "id": k,
           "from": src, "title": title}
    for f in ("hypothesis", "kills_it", "ceiling", "needs", "shape",
              "differs_from_live"):
        v = (prop.get(f) or "").strip()
        if v:
            rec[f] = v
    rec["cites"] = [c for c in (prop.get("cites") or [])
                    if isinstance(c, str)][:8]
    append(out, rec)
    return k


def mark(out, ev, mid, note=""):
    """Отметить механику: `given` (отдана), `built`, `blocked`."""
    append(out, {"ev": ev, "at": round(time.time(), 3), "id": mid,
                 "note": note or ""})


def state(out):
    """Механики со состоянием, старые первыми (очередь, а не стопка)."""
    rows, broken = read(out)
    seen = {}
    for r in rows:
        mid = r.get("id")
        if not mid:
            continue
        if r.get("ev") == "queued":
            seen.setdefault(mid, dict(r, state="ждёт", note=""))
        elif mid in seen:
            seen[mid]["state"] = {"given": "отдана строителю",
                                  "built": "построена",
                                  "blocked": "ждёт владельца"}.get(
                                      r["ev"], r["ev"])
            seen[mid]["note"] = r.get("note") or ""
            seen[mid]["last_at"] = r.get("at")
    out_rows = sorted(seen.values(), key=lambda r: r.get("at") or 0)
    return out_rows, broken


def pending(out):
    """Механики, которых строитель ещё не брал и которые не закрыты."""
    rows, _ = state(out)
    return [r for r in rows if r["state"] == "ждёт"]


def task_id(path):
    """Чья механика лежит в задании. Нет метки — задание рукописное."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        head = f.read(4000)
    i = head.find("<!-- механика: ")
    if i < 0:
        return None
    j = head.find(" -->", i)
    return head[i + len("<!-- механика: "):j].strip() if j > 0 else None


def task_text(rec):
    """Задание строителю из заявки. Слова заявки, а не мой пересказ."""
    L = [MARK % rec["id"],
         "# Задание строителю: механика «%s»" % rec["title"], "",
         "Это НОВАЯ механика, а не починка: движок её не умеет, и",
         "предлагающий подал её как `mechanism`. Строишь ты — целиком:",
         "модуль, тесты, кусающиеся контроли.", ""]
    for name, field in (("Что утверждается", "hypothesis"),
                        ("Чем это убивается", "kills_it"),
                        ("Самый дешёвый расчёт (потолок)", "ceiling"),
                        ("Какой формы ждут кривую", "shape"),
                        ("Чем отличается от живого", "differs_from_live"),
                        ("Чего механика ждёт", "needs")):
        v = (rec.get(field) or "").strip()
        if v:
            L += ["## %s" % name, "", v, ""]
    if rec.get("cites"):
        L += ["## На что ссылалась заявка", ""]
        L += ["- `%s`" % c for c in rec["cites"]] + [""]
    L += [
        "## Где строить",
        "",
        "Новый каталог `research/<короткое имя>/` и тесты рядом. В",
        "чужие каталоги не пиши: публикуется ровно объявленное тобой,",
        "а неназванная правка останется на сервере.",
        "",
        "## Если нужного нет у нас",
        "",
        "Данные, ключ, аккаунт, оплаченный доступ — этого ты не",
        "достанешь и добывать не пробуй. Назови это в `needs_owner`",
        "отчёта (`what`, `why`, `unblocks`, при возможности `check` —",
        "путь, по которому машина увидит, что дело сделано), а",
        "построй ту часть, которая строится без этого. Просьба",
        "попадёт на страницу владельца; выдуманные данные —",
        "единственное, чего делать нельзя ни при каких условиях.",
        "",
    ]
    return "\n".join(L)


def write_task(out, rec):
    """Положить задание строителю. Прежнее не теряется, а отходит."""
    p = os.path.join(out, TASK)
    prev = task_id(p)
    if os.path.exists(p):
        os.replace(p, os.path.join(out, TASK_PREV))
    with open(p, "w", encoding="utf-8") as f:
        f.write(task_text(rec))
    return prev


STATE = "mech_task.json"


def write_state(out, decided, mid=None, note=""):
    """След шага круга: что решено СЕГОДНЯ.

    Шаг обязан оставлять артефакт, даже когда строить нечего: круг
    считает шаг сделанным по свежести артефакта, а «сегодня очередь
    пуста» — это результат, а не пустота. Без него шаг переспрашивал
    бы очередь каждые пять минут до предела попыток.
    """
    os.makedirs(out, exist_ok=True)
    rec = {"at": round(time.time(), 3), "decided": decided,
           "id": mid, "note": note}
    tmp = os.path.join(out, STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(out, STATE))
    return rec


def build_ready(out):
    """Есть ли ЧТО строить: задание машины, ещё не закрытое.

    Гейт нужен, чтобы круг не звал модель впустую: строитель без
    задания стоит столько же, сколько строитель с заданием.
    """
    mid = task_id(os.path.join(out, TASK))
    if not mid:
        return False
    cur = {r["id"]: r for r in state(out)[0]}.get(mid)
    return bool(cur and cur["state"] in ("ждёт", "отдана строителю"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--next", action="store_true",
                    help="выдать строителю следующую механику")
    a = ap.parse_args(argv)

    rows, broken = state(a.out)
    print("механик в очереди: %d, битых строк: %d" % (len(rows), broken))
    for r in rows:
        print("  %-8s %-16s %s" % (r["id"], r["state"], r["title"][:60]))
        if r.get("note"):
            print("           %s" % r["note"][:90])
    if not a.next:
        return 0

    p = os.path.join(a.out, TASK)
    cur = task_id(p)
    if cur:
        alive = {r["id"]: r for r in rows}.get(cur)
        if alive and alive["state"] in ("ждёт", "отдана строителю"):
            print("задание уже лежит и не закрыто: %s (%s) — не трогаю"
                  % (cur, alive["state"]))
            write_state(a.out, "занято", cur, alive["state"])
            return 0
    wait = [r for r in rows if r["state"] == "ждёт"]
    if not wait:
        print("строить нечего: механик в очереди нет")
        write_state(a.out, "нечего")
        return 0
    rec = wait[0]
    had = os.path.exists(os.path.join(a.out, TASK))
    prev = write_task(a.out, rec)
    mark(a.out, "given", rec["id"], "задание положено")
    write_state(a.out, "выдано", rec["id"], rec["title"])
    print("задание положено: %s — %s" % (rec["id"], rec["title"]))
    if prev:
        print("прежнее задание (%s) отошло в %s" % (prev, TASK_PREV))
    elif had:
        print("прежнее задание было рукописным, отошло в %s" % TASK_PREV)
    else:
        print("прежнего задания не было")
    return 0


if __name__ == "__main__":
    sys.exit(main())
