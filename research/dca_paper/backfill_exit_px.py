#!/usr/bin/env python3
"""Добор верной цены выхода охраны рынком в уже записанные строки журналов.

Повод (26.09). Цена выхода «рынок» — поле показа: она восстанавливалась
из отметки ядра формулой «вход × (1 − pnl/плечо)», которая считает, что
на плече работает вся маржа, а у книги без доливов заполнена четверть
билета. Ход цены выходил вчетверо меньше настоящего: медиана |разницы|
с закрытием часа по принтам — 271 б.п. на 450 выходах (`guard_fill`),
точка выхода на графике вставала там, где цены не было. Формула
исправлена (`wave.exit_px_of`), прошлые строки несут прежнее число.

Почему это не нарушает write-ahead. Не меняются ни момент записи, ни
деньги, ни исход, ни состав: `pnl_frac` и `usd` те же. Меняется поле
ПОКАЗА, и прежнее значение сохраняется рядом (`exit_px_was`), а способ
— помечается (`exit_px_from: "fills"`); строки без заполнений не
трогаются и считаются. Сверка встроена: число строк совпадает, каждая
тронутая строка отличается от прежней ровно тремя полями показа.

    run research/dca_paper/backfill_exit_px.py            # сухой
    run research/dca_paper/backfill_exit_px.py --write
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402
import wave as WV                                             # noqa: E402

JOURNALS = (R.H24_JOURNAL, R.PAIR_JOURNAL)
FIELDS = {"exit_px", "exit_px_was", "exit_px_from"}
TOL = 1e-12


def _sig(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def _unchanged(path, sig):
    return _sig(path) == sig


def fixed_px(row):
    """Верная цена выхода для строки «рынок»; None — не пересчитать."""
    if row.get("exit") != R.GUARD_EXIT or not R.is_current(row):
        return None
    if row.get("exit_px_from") == "fills":
        return None
    try:
        return WV.exit_px_of(row, float(row["pnl_frac"]), float(row["exit_ts"]))
    except (KeyError, TypeError, ValueError):
        return None


def patch_file(path, write=False):
    """(строк, тронуто, без заполнений); кусок, изменившийся за время
    добора, не пишется."""
    sig = _sig(path)
    src = open(path, encoding="utf-8").read().splitlines()
    out, touched, nofill = [], 0, 0
    for ln in src:
        if not ln.strip():
            out.append(ln)
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            out.append(ln)
            continue
        if r.get("exit") == R.GUARD_EXIT and R.is_current(r) \
                and r.get("exit_px_from") != "fills":
            px = fixed_px(r)
            if px is None:
                nofill += 1
            else:
                was = r.get("exit_px")
                if was is None or abs(float(was) - px) > TOL:
                    r["exit_px_was"] = was
                    r["exit_px"] = px
                    r["exit_px_from"] = "fills"
                    touched += 1
                    out.append(json.dumps(r, ensure_ascii=False))
                    continue
        out.append(ln)
    if len(out) != len(src):
        raise SystemExit(f"{path}: строк стало {len(out)} против {len(src)}")
    for a, b in zip(src, out):
        if a == b:
            continue
        ra, rb = json.loads(a), json.loads(b)
        changed = {k for k in set(ra) | set(rb) if ra.get(k) != rb.get(k)}
        if not changed <= FIELDS or "exit_px" not in changed \
                or ra.get("pnl_frac") != rb.get("pnl_frac") \
                or ra.get("usd") != rb.get("usd"):
            raise SystemExit(f"{path}: строка изменилась не только полями "
                             f"показа: {sorted(changed)}")
    if write and touched:
        if not _unchanged(path, sig):
            print(f"  {os.path.basename(path)}: изменился во время добора — "
                  "НЕ записан, повторить прогон")
            return len(src), 0, nofill
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    return len(src), touched, nofill


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    tot = tou = nof = 0
    for j in JOURNALS:
        for p in R.journal_parts(j):
            n, t, m = patch_file(p, write=a.write)
            tot += n
            tou += t
            nof += m
            if t or m:
                print(f"  {os.path.basename(p)}: строк {n}, исправлено {t}, "
                      f"без заполнений {m}")
    print(f"итого строк {tot}, исправлено {tou}, без заполнений {nof}"
          + ("" if a.write else "  (СУХОЙ прогон, ничего не записано)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
