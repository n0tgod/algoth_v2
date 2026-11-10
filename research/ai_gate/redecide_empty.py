#!/usr/bin/env python3
"""Дорешить решения книг ТВХ, принятые на пустых полях правила (решение
владельца 10.11).

До 09.11 проход судил час k по часам (5 мин после его конца), а не по тому,
легла ли сводка часа: пока цикл S8 учится, сводки опаздывают на часы, поле
правила читалось пустым, и «входа нет» (k = -1) записывалось навсегда.

Здесь: у ЖИВЫХ книг ТВХ отказы с пустым значением хотя бы одного поля
правила переносятся в архив `redecided` того же файла (прежняя запись не
стирается), и решение принимается заново ТЕМ ЖЕ кодом прохода
(`model_books.entry_decide`, с проверкой, что сводка часа легла). Поля
считаются только по закрытым часам ≤ k, цена входа — открытие следующей
свечи из истории: заглядывания вперёд нет. Новое решение несёт пометку
`redecided` (момент). Затем часовой тик книг — реплей сдвинутых входов.

Без `--apply` — сухой прогон: что изменится, без записи.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import model_books as MB                                      # noqa: E402

WHY = "решение 09.11 и раньше — на пустых полях (сводка часа не легла к моменту решения)"


def suspicious(b, d):
    if d.get("k", -1) != -1:
        return False
    v = d.get("vals")
    if not v:
        return False
    return any(v.get(c["field"]) is None for c in b["rule"]["when"])


def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(float(t)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    now = time.time()
    if a.apply:
        busy = subprocess.run(["pgrep", "-f", "ai_gate/model_books.py"], capture_output=True, text=True).stdout.strip()
        if busy:
            print(f"идёт проход книг модели (pid {busy}) — не трогаю состояние, повторить позже")
            return 2
    reg = MB.load()
    books = [b for b in reg["books"] if b["kind"] == "entry" and b["status"] == "live"]
    with open(MB.ENTRY_STATE, encoding="utf-8") as f:
        state = json.load(f)
    moved = {}
    for b in books:
        mine = state.get(b["id"]) or {}
        for sk, d in list(mine.items()):
            if suspicious(b, d):
                moved.setdefault(b["id"], {})[sk] = d
    n_moved = sum(len(v) for v in moved.values())
    print(f"живых книг ТВХ {len(books)}; отказов на пустых полях {n_moved}: "
          + ", ".join(f"{k} {len(v)}" for k, v in moved.items()))
    if not n_moved:
        return 0
    import run_short as S                                      # noqa: E402
    import entry_search as ES                                  # noqa: E402
    lo = min(float(b["born_at"]) for b in books)
    legs = [g for g in S.legs(log=lambda *x: None) if float(g["at"]) >= lo]
    feat = ES.feature_env(legs, days=min(45, int((now - lo) / MB.DAY) + 3))
    for bid, ds in moved.items():
        for sk in ds:
            del state[bid][sk]
    for b in books:
        MB.entry_decide(b, legs, feat, state, now)
    entered = unmeasured = same = waiting = 0
    for bid, ds in moved.items():
        for sk, old in sorted(ds.items(), key=lambda kv: kv[0].split("|")[1]):
            new = state[bid].get(sk)
            sym, at = sk.split("|")
            if new is None:
                waiting += 1
                print(f"  {bid} {ts(at)} {sym}: ждёт сводку часа (решится тиком)")
                continue
            new["redecided"] = round(now)
            if new["k"] >= 0:
                entered += 1
                print(f"  {bid} {ts(at)} {sym}: ВХОД на k={new['k']} — {new.get('vals')}; выход {new.get('exit')}")
            elif new["k"] == MB.UNMEASURED:
                unmeasured += 1
                print(f"  {bid} {ts(at)} {sym}: не измерено — {new.get('why')}")
            else:
                same += 1
    print(f"итог: входов {entered}, по-прежнему нет входа {same}, не измерено {unmeasured}, ждут {waiting}")
    if not a.apply:
        print("сухой прогон: ничего не записано (--apply — записать и дорешать)")
        return 0
    arch = state.setdefault("redecided", {})
    for bid, ds in moved.items():
        for sk, old in ds.items():
            arch.setdefault(bid, {})[sk] = dict(old, archived_at=round(now), why=WHY)
    with open(MB.ENTRY_STATE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(MB.ENTRY_STATE + ".tmp", MB.ENTRY_STATE)
    print(f"записано: {MB.ENTRY_STATE}; прежние решения — в state['redecided']")
    s = MB.tick(log=print, now=time.time())
    print(json.dumps(s, ensure_ascii=False))
    os.makedirs(os.path.dirname(MB.TICK), exist_ok=True)
    with open(MB.TICK, "w", encoding="utf-8") as f:
        json.dump(dict(s, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), f, ensure_ascii=False)
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                    f"книги ТВХ: дорешены {n_moved} отказов на пустых полях, входов {entered}"], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
