#!/usr/bin/env python3
"""Диагностика книг ТВХ модели (только чтение, 09.11): решения о часе входа,
принятые на ПУСТЫХ полях правила, — час сводки не лёг к моменту решения или
сводки у имени нет вовсе. Печатает: какие часы сводок лежат сейчас, сколько
«пустых» отказов теперь измеримы и сколько из них стали бы входами по тому же
правилу, флаг обучения, отметку тика, хвост лога книг модели. Ничего не пишет.
"""
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

H = 3600.0
SUM = os.path.join(ROOT, "research", "s8_loop", "out", "summary")


def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(t)) if t else "-"


def file_info(p):
    try:
        st = os.stat(p)
        return f"есть, mtime {ts(st.st_mtime)}, {st.st_size} Б"
    except OSError:
        return "нет"


def hours_in(sym, day):
    p = os.path.join(SUM, sym, day + ".jsonl")
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line).get("hour", "?")[-2:])
                except ValueError:
                    continue
    except OSError:
        return None
    return sorted(set(out))


def main():
    now = time.time()
    print(f"сейчас {ts(now)} UTC")
    for p in ("research/s8_loop/out/train_wait.flag", "research/ai_gate/out/record/model_tick.json",
              "research/ai_gate/out/model_entry.json", "research/ai_gate/out/model_books_latest.json"):
        print(f"{p}: {file_info(os.path.join(ROOT, p))}")
    try:
        ps = subprocess.run(["pgrep", "-af", "train.py|model_books.py|summary.py"], capture_output=True, text=True).stdout
        print("процессы:\n" + "\n".join("  " + l[:160] for l in ps.splitlines() if "pgrep" not in l))
    except OSError as e:
        print(f"pgrep: {e}")
    days = [time.strftime("%Y-%m-%d", time.gmtime(now - d * 86400)) for d in (2, 1, 0)]
    st = json.load(open(MB.ENTRY_STATE, encoding="utf-8"))
    reg = MB.load()
    books = [b for b in reg["books"] if b["kind"] == "entry" and b["status"] == "live"]
    syms = {"BTCUSDT"}
    empties = []
    for b in books:
        for sk, d in (st.get(b["id"]) or {}).items():
            sym, at = sk.split("|")
            at = float(at)
            v = d.get("vals") or {}
            if at > now - 4 * 86400:
                syms.add(sym)
            if at > now - 4 * 86400 and d["k"] < 0 and v and all(x is None for x in v.values()):
                empties.append((b, sym, at, d))
    print(f"\nчасы сводок по дням {days} (что лежит СЕЙЧАС):")
    for sym in sorted(syms)[:40]:
        print(f"  {sym:16s} " + " | ".join(
            f"{day[5:]}: {('нет файла' if h is None else (str(len(h)) + ' ч, послед ' + (h[-1] if h else '-')))}"
            for day, h in ((day, hours_in(sym, day)) for day in days)))
    print(f"\nотказов на ПУСТЫХ полях за 4 суток: {len(empties)}")
    if not empties:
        return
    import run_short as S                                      # noqa: E402
    import entry_search as ES                                  # noqa: E402
    legs = {(g["sym"], float(g["at"])): g for g in S.legs(log=lambda *a: None) if float(g["at"]) > now - 5 * 86400}
    feat = ES.feature_env(list(legs.values()), days=8)
    meas = would = 0
    by_reason = {}
    for b, sym, at, d in sorted(empties, key=lambda x: x[2]):
        g = legs.get((sym, at))
        if g is None:
            by_reason["сигнала нет в списке ног"] = by_reason.get("сигнала нет в списке ног", 0) + 1
            continue
        W = int(b["rule"]["W"])
        got, last = None, None
        any_val = False
        for k in range(W + 1):
            f = feat(g, k)
            last = {c["field"]: f.get(c["field"]) for c in b["rule"]["when"]}
            if any(x is not None for x in last.values()):
                any_val = True
            if MB.matches(b["rule"], f):
                got = k
                break
        if any_val:
            meas += 1
        else:
            r = "имени нет в сводках" if hours_in(sym, time.strftime("%Y-%m-%d", time.gmtime(at))) is None \
                else "часы окна пусты и сейчас"
            by_reason[r] = by_reason.get(r, 0) + 1
        if got is not None:
            would += 1
            print(f"  {b['id']} {ts(at)} {sym}: сейчас ВХОД на k={got} "
                  f"{ {k2: (round(x, 4) if isinstance(x, float) else x) for k2, x in last.items()} }; решение было в {ts(d.get('t'))}")
    print(f"теперь измеримы {meas} из {len(empties)}; стали бы входами {would}; неизмеримы и сейчас: {by_reason}")
    lg = os.path.join(ROOT, "research/ai_gate/out/model_books.log")
    try:
        tail = open(lg, encoding="utf-8").read().splitlines()[-30:]
        print("\nхвост model_books.log:\n" + "\n".join("  " + l[:200] for l in tail))
    except OSError as e:
        print(f"лог: {e}")


if __name__ == "__main__":
    main()
