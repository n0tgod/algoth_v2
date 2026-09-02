#!/usr/bin/env python3
"""Почему молчит цикл обучения: хвост журнала и состояние манифеста.

Заводится потому, что молчащий цикл снаружи неотличим от здорового:
страницы отдают ПРОШЛЫЙ манифест, сборщик пишет книгу как ни в чём не
бывало, а живой исполнитель встаёт по правилу «цикл молчит три часа» —
и первым признаком отказа оказывается остановка живых денег. Спросить
об этом было нечем: очередь заданий пускает только `research/*.py` и
`tools/*.py`, а хвост журнала лежит на сервере.

Печатает: жив ли процесс, возраст манифеста и последнего обучения,
хвост `train.log` — и НЕ печатает ничего, чего нет: отсутствие файла
называется словами, а не пустотой.
"""

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "research", "s8_loop", "out")


def _rows(p):
    """Строки журнала книги. Файла нет — пусто, но это НЕ ошибка:
    книга, заведённая в этот час, разбора ещё не имеет."""
    out = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        return out
    return out


def age(p):
    try:
        return time.time() - os.path.getmtime(p)
    except OSError:
        return None


def main(argv=None):
    n = 60
    if argv:
        for a in argv:
            if a.startswith("--tail="):
                n = int(a.split("=", 1)[1])
    r = subprocess.run(["pgrep", "-af", "s8_loop/train.py"],
                       capture_output=True, text=True)
    live = [x for x in r.stdout.splitlines() if x.strip()]
    print("=== процесс цикла ===")
    print("\n".join(live) if live else "НЕ НАЙДЕН — цикл не работает")
    print("\n=== манифест модели ===")
    mp = os.path.join(OUT, "model", "manifest.json")
    a = age(mp)
    if a is None:
        print(f"манифеста нет: {mp}")
    else:
        try:
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError) as e:
            m = {"ошибка чтения": str(e)}
        print(f"возраст {a / 3600:.1f} ч")
        for k in ("trained_at", "train_seq", "cycle_sec",
                  "woke_after_hour_sec", "steps_sec", "canary_ic"):
            if k in m:
                print(f"  {k}: {m[k]}")
    # Возраст манифеста КАЖДОЙ книги: живой исполнитель встаёт по
    # возрасту манифеста СВОЕЙ книги, а не по общему манифесту модели,
    # и «цикл молчит» у него означает ровно это. Без этих чисел
    # причина остановки живых денег остаётся догадкой.
    print("\n=== манифесты книг ===")
    for d in sorted(os.listdir(OUT) if os.path.isdir(OUT) else []):
        bp = os.path.join(OUT, d, "manifest.json")
        if not os.path.exists(bp):
            continue
        print(f"  {d}: {age(bp) / 3600:.2f} ч")
    # Живой исполнитель: КОГДА он встал и на чём. Остановка хранится
    # до ручного снятия, поэтому её причина описывает МОМЕНТ отказа, а
    # не сейчас, — и без метки времени она читается как свежая.
    if "--live" in (argv or []):
        print("\n=== журнал живого исполнителя ===")
        ld = os.path.join(ROOT, "bot", "out", "live")
        fs = sorted(x for x in (os.listdir(ld) if os.path.isdir(ld)
                                else []) if x.endswith(".jsonl"))
        if not fs:
            print(f"журнала нет: {ld}")
        else:
            rows = []
            for x in fs[-2:]:
                with open(os.path.join(ld, x), encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            rows.append((x, line))
            print(f"файлов {len(fs)}, строк в двух последних "
                  f"{len(rows)}")
            for x, line in rows[-12:]:
                try:
                    r = json.loads(line)
                except ValueError:
                    print(f"  {x}: битая строка")
                    continue
                ms = r.get("at_ms")
                t = (time.strftime("%m-%d %H:%M:%S",
                                   time.gmtime(ms / 1000.0))
                     if ms else "—")
                ev = r.get("ev")
                note = r.get("note") or r.get("why") or ""
                print(f"  {t} {ev} {r.get('sym') or ''} "
                      f"{str(note)[:120]}")
    # Состав книг, которые ведёт СКАНЕР: он объявлен листом сечения, и
    # книга, не попавшая в этот список, не возьмёт ни одного входа —
    # каталог и манифест у неё при этом будут, то есть снаружи она
    # выглядит заведённой.
    if "--sheet" in (argv or []):
        print("\n=== книги в листе сечения ===")
        sp = os.path.join(OUT, "model_sit", "scan_sheet.json")
        try:
            with open(sp, encoding="utf-8") as f:
                sh = json.load(f)
        except (OSError, ValueError) as e:
            print(f"листа нет или он не читается: {e}")
        else:
            print(f"час {sh.get('hour')}, возраст "
                  f"{age(sp) / 60:.1f} мин")
            for b in sh.get("books") or []:
                print("  " + json.dumps(b, ensure_ascii=False))
    # Книги кандидатов фабрики: завелись ли и берёт ли КАЖДАЯ РУКА
    # входы. Сводка страницы `built` считает закрытые сделки, и рука,
    # не взявшая ни одного входа, там неотличима от руки, у которой
    # позиции ещё открыты: обе показывают ноль закрытых. Различает их
    # только счёт выборов и разбора по каждой руке.
    if "--cand" in (argv or []):
        print("\n=== книги кандидатов ===")
        ep = os.path.join(ROOT, "research", "s8_loop",
                          "books_extra.json")
        try:
            with open(ep, encoding="utf-8") as f:
                ex = json.load(f)
        except OSError:
            ex = None
            print(f"состава книг нет: {ep} — цикл его ещё не писал")
        except ValueError as e:
            ex = None
            print(f"состав книг не читается: {e}")
        if ex is not None:
            print(f"книг в составе: {len(ex)}")
            for b in ex:
                d = os.path.join(OUT, b.get("dir") or "")
                if not os.path.isdir(d):
                    print(f"  {b.get('key')}: каталога нет — {d}")
                    continue
                g = b.get("gate") or {}
                print(f"  {b.get('key')} [{b.get('lane')}] "
                      f"слотов {g.get('slots')} "
                      f"пол {g.get('floor_bp')} "
                      f"rr {g.get('min_rr')}..{g.get('max_rr')} "
                      f"на сторону {g.get('per_side')} "
                      f"согласие {g.get('agree')}")
                for arm in ("gbm", "nn"):
                    picks = _rows(os.path.join(d, "picks.jsonl"))
                    revs = _rows(os.path.join(d, "review.jsonl"))
                    pa = [r for r in picks if r.get("arm") == arm]
                    ra = [r for r in revs if r.get("arm") == arm]
                    # Открытая позиция — выбор, у которого разбора ещё
                    # нет. Ключ тот же, каким их сводит показ.
                    done = {(r.get("hour"), r.get("sym"))
                            for r in ra}
                    op = sum(1 for r in pa
                             if (r.get("hour"), r.get("sym"))
                             not in done)
                    last = max((r.get("at_ts") or 0) for r in pa) \
                        if pa else 0
                    la = (f"{(time.time() - last) / 60:.0f} мин назад"
                          if last else "выборов не было")
                    print(f"    {arm}: выборов {len(pa)}, "
                          f"разобрано {len(ra)}, открыто {op}, "
                          f"последний {la}")

    print("\n=== хвост train.log ===")
    lp = os.path.join(OUT, "train.log")
    if not os.path.exists(lp):
        print(f"журнала нет: {lp}")
        return 0
    print(f"возраст {age(lp) / 60:.1f} мин, размер "
          f"{os.path.getsize(lp)} Б")
    with open(lp, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for x in lines[-n:]:
        print(x.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
