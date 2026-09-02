#!/usr/bin/env python3
"""Дописать журналу разведчика текст идей, записанных заголовком.

Зачем. Меню живёт в `research/factory/out/scout.json`, и каждый прогон
перезаписывает его свежим. Журнал `scout.jsonl` — единственное, что
переживает прогон, а первая его версия хранила только заголовок и
источники: идея объявлялась принесённой (и потому запрещённой к
повтору) тогда, когда её текста не оставалось нигде, кроме истории git.
Запрет без содержания есть потеря — это заметил сам разведчик на первом
удачном прогоне.

Как. Журнал write-ahead: строку не переписываем — знание доезжает
ОТДЕЛЬНОЙ записью, ровно как поправка `Adjust` в журнале живого
исполнителя. Восстановленная запись несёт исходный момент `at` (чтобы
порядок и граница прогона не сдвинулись), полный текст идеи и поле
`restored_from` — откуда текст взят. Повторный прогон не делает ничего:
у заголовка уже есть полная запись.

    python3 research/factory/scout_backfill.py            # из истории git
    python3 research/factory/scout_backfill.py --menu FILE  # из файла
    python3 research/factory/scout_backfill.py --dry        # только показать
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import runlog as RL                                        # noqa: E402

MENU = "research/factory/out/scout.json"
FIELDS = ("claim", "mechanism", "kills_it", "novelty", "needs")


def read_journal(path):
    """Строки журнала как есть. Битая строка считается, а не глотается."""
    rows, broken = [], 0
    if not os.path.exists(path):
        return rows, broken
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except ValueError:
                broken += 1
    return rows, broken


def incomplete(rows):
    """Заголовки, у которых НИ ОДНА запись не несёт текста идеи.

    Полнота решается по всему журналу, а не по строке: восстановление
    и есть вторая запись того же заголовка, и второй прогон обязан
    увидеть её и промолчать.
    """
    full, seen = set(), []
    for r in rows:
        t = (r.get("title") or "").strip()
        if not t:
            continue
        if t.lower() not in [x.lower() for x in seen]:
            seen.append(t)
        if (r.get("mechanism") or "").strip():
            full.add(t.lower())
    return [t for t in seen if t.lower() not in full]


def first_at(rows, title):
    """Момент ПЕРВОЙ записи заголовка: восстановление не сдвигает порядок."""
    ats = [r.get("at") for r in rows
           if (r.get("title") or "").strip().lower() == title.lower()
           and isinstance(r.get("at"), (int, float))]
    return min(ats) if ats else None


def restore(rows, menus):
    """Записи-поправки для заголовков без текста.

    `menus` — пары (откуда, меню): версии `scout.json`, свежие первыми.
    Первое совпадение по заголовку и выигрывает.
    """
    want = incomplete(rows)
    out = []
    for t in want:
        for src, menu in menus:
            for it in (menu.get("ideas") or []):
                if not isinstance(it, dict):
                    continue
                if (it.get("title") or "").strip().lower() != t.lower():
                    continue
                if not (it.get("mechanism") or "").strip():
                    continue
                rec = {"at": first_at(rows, t), "title": t,
                       "sources": [c for c in (it.get("sources") or [])
                                   if isinstance(c, str)][:5],
                       "restored_from": src}
                for k in FIELDS:
                    v = (it.get(k) or "").strip()
                    if v:
                        rec[k] = v
                out.append(rec)
                break
            else:
                continue
            break
    return out


def git_menus(root, limit=40):
    """Версии меню из истории git, свежие первыми."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "-n", str(limit), "--", MENU],
            cwd=root, capture_output=True, text=True, timeout=60)
    except OSError as e:                                   # noqa: BLE001
        print("git недоступен: %s" % e)
        return []
    out = []
    for sha in (shas.stdout or "").split():
        r = subprocess.run(["git", "show", "%s:%s" % (sha, MENU)],
                           cwd=root, capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            continue
        try:
            d = json.loads(r.stdout)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append((sha[:7], d))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", action="append", default=[],
                    help="файл меню вместо истории git (можно повторять)")
    ap.add_argument("--out", default=os.path.join(ROOT, "research",
                                                  "factory", "out"))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)

    path = os.path.join(a.out, RL.SCOUT_SEEN)
    rows, broken = read_journal(path)
    print("журнал: строк %d, битых %d" % (len(rows), broken))
    if not rows:
        print("журнала нет — восстанавливать нечего")
        return 0

    menus = []
    for p in a.menu:
        with open(p, encoding="utf-8") as f:
            menus.append((os.path.basename(p), json.load(f)))
    if not menus:
        menus = git_menus(ROOT)
    print("версий меню просмотрено: %d" % len(menus))

    want = incomplete(rows)
    print("заголовков без текста: %d" % len(want))
    for t in want:
        print("  · %s" % t)
    recs = restore(rows, menus)
    print("нашлось в истории: %d" % len(recs))
    for r in recs:
        print("  + %s ← %s" % (r["title"], r["restored_from"]))
    missing = [t for t in want
               if t.lower() not in {r["title"].lower() for r in recs}]
    for t in missing:
        # Не найденное молчанием не объявляется: заголовок остаётся
        # запрещённым к повтору, а текста у нас нет — это состояние
        # надо видеть, а не выводить из пустой разницы чисел.
        print("  ? текста не нашлось: %s" % t)

    if a.dry or not recs:
        print("ничего не дописано%s" % (" (--dry)" if a.dry else ""))
        return 0
    with open(path, "a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("дописано записей: %d" % len(recs))
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "агенты: восстановлен текст идей разведчика"],
                       cwd=ROOT, timeout=600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
