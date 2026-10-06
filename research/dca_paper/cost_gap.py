#!/usr/bin/env python3
"""Куда уходят 30 б.п.: разрыв между эджем решения в цене и кассой коротких книг.

Повод (03.10, `short_levcap`): по записям реплея ожидание в цене
+34…36 б.п. нотионала у всех трёх коротких книг, а касса на $10k с
издержками оставляет 0–17 б.п. Решение владельца 05.10: разложить
разрыв по осям, объявленным ДО прогона:

  S0  записи книги, равный вес, плоские издержки реплея
      (`pnl_net` = pnl − 11 б.п. на заполненную долю);
  S1  те же записи, но только ВЗЯТЫЕ кассой (отбор кассы: места,
      «одна на имя», билет) — Δ_отбор = S1 − S0;
  S2  взятые, взвешенные ДОЛЛАРАМИ нотионала (билет × плечо) —
      Δ_вес = S2 − S1;
  S3  взятые, доллары, НАСТОЯЩИЕ издержки (комиссия площадки по
      заполнениям, проскальзывание X3 4.4 б.п., funding по рядам) —
      Δ_издержки = S3 − S2, с разбивкой: плоские 11 б.п. снимаются,
      комиссия, проскальзывание, funding ставятся.

Все четыре — в б.п. нотионала, то есть в ЦЕНЕ; тождество S3 − S0 =
Δ_отбор + Δ_вес + Δ_издержки держит проверка. Разрез — по книгам и по
полосам плеча забора записи (≤3, 3–6, 6–10, 10–15, 15–25×): где именно
издержки съедают ход. Издержки считаются только у строк, у которых они
измеримы (`costs.apply_to_rows`); доля таких строк печатается, строки
без издержек в S1–S3 не входят — иначе брутто смешалось бы с нетто.

Вердикт выводится из чисел: названа наибольшая по модулю ось.
Замер читает кэш реплея и журналы, ничего не пересчитывает по барам.

    run research/dca_paper/cost_gap.py
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_short as S                                         # noqa: E402
import run_paper as RP                                        # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import short_levers as L                                      # noqa: E402
import instruments_refresh as IR                              # noqa: E402

ART = "DCA-cost-gap"
MAIN_DEP = 10000
BOOK_KEYS = list(S.BOOKS)
# Полосы плеча забора — объявлены до прогона; верхняя граница входит.
BANDS = ((0.0, 3.0, "≤3×"), (3.0, 6.0, "3–6×"), (6.0, 10.0, "6–10×"),
         (10.0, 15.0, "10–15×"), (15.0, 1e9, "15–25×"))
STEPS = ("S0", "S1", "S2", "S3")


def band_of(lev):
    lev = float(lev)
    for lo, hi, name in BANDS:
        if lo < lev <= hi:
            return name
    return BANDS[0][2] if lev <= 0 else BANDS[-1][2]


def rec_key(r):
    return (r.get("sym"), round(float(r["at"]), 3))


def closed_recs(recs, book):
    """Закрытые записи книги с её гейтом плеча — как `short_levcap.record_pairs`."""
    ml = R.min_lev_of(book)
    out = []
    for r in recs:
        if (r.get("state") or "closed") != "closed" or r.get("pnl_net") is None:
            continue
        lev = float(r.get("lev") or 0.0)
        if not lev > 0 or (ml is not None and lev < float(ml)):
            continue
        out.append(r)
    return out


def costed_rows(rows):
    """Строки кассы с измеренными издержками (комиссия и проскальзывание есть)."""
    return [r for r in rows if r.get("fee_usd") is not None
            and r.get("slip_usd") is not None and r.get("usd_gross") is not None
            and float(r.get("margin") or 0) > 0 and float(r.get("lev") or 0) > 0]


def join(rows, recs):
    """Строки кассы → записи реплея по (имя, момент решения). Возвращает
    (пары (строка, запись), число строк без записи)."""
    by = {rec_key(r): r for r in recs}
    pairs, lost = [], 0
    for row in rows:
        rec = by.get(rec_key(row))
        if rec is None:
            lost += 1
            continue
        pairs.append((row, rec))
    return pairs, lost


def _mean(xs):
    return (sum(xs) / len(xs)) if xs else None


def _bp(x):
    return None if x is None else x * 1e4


def chain(recs, rows, book):
    """Цепочка S0 → S3 и дельты, в б.п. нотионала, плюс состав по полосам."""
    kept = closed_recs(recs, book)
    s0 = _mean([float(r["pnl_net"]) / float(r["lev"]) for r in kept])
    pairs, lost = join(costed_rows(rows), kept)
    if not pairs:
        return {"n_records": len(kept), "n_taken": 0, "lost": lost,
                "S0": _bp(s0), "S1": None, "S2": None, "S3": None,
                "note": "касса не взяла ни одной записи с измеренными издержками"}
    s1 = _mean([float(rec["pnl_net"]) / float(rec["lev"]) for _row, rec in pairs])
    notl = sum(float(row["margin"]) * float(row["lev"]) for row, _rec in pairs)
    flat_usd = sum((float(rec["pnl"]) - float(rec["pnl_net"])) * float(row["margin"])
                   for row, rec in pairs)
    gross_usd = sum(float(row["usd_gross"]) for row, _rec in pairs)
    fee = sum(float(row["fee_usd"]) for row, _rec in pairs)
    slip = sum(float(row["slip_usd"]) for row, _rec in pairs)
    fund_rows = [row for row, _rec in pairs if row.get("fund_usd") is not None]
    fund = sum(float(row["fund_usd"]) for row in fund_rows)
    s2 = (gross_usd - flat_usd) / notl
    s3 = (gross_usd - fee - slip + fund) / notl
    s3_eq = _mean([(float(row["usd_gross"]) - float(row["fee_usd"]) - float(row["slip_usd"])
                    + float(row.get("fund_usd") or 0.0)) / (float(row["margin"]) * float(row["lev"]))
                   for row, _rec in pairs])
    hold_h = _mean([(float(rec["exit_ts"]) - float(rec["at"])) / 3600.0 for _row, rec in pairs])
    out = {"n_records": len(kept), "n_taken": len(pairs), "lost": lost,
           "n_rows_costed": len(pairs), "n_rows_all": len(rows),
           "cover": (len(pairs) / len(rows)) if rows else None,
           "n_funding": len(fund_rows),
           "S0": _bp(s0), "S1": _bp(s1), "S2": _bp(s2), "S3": _bp(s3),
           "S3_eq": _bp(s3_eq),
           "d_select": _bp(s1 - s0), "d_weight": _bp(s2 - s1), "d_costs": _bp(s3 - s2),
           "flat_bp": _bp(flat_usd / notl), "fee_bp": _bp(fee / notl),
           "slip_bp": _bp(slip / notl), "fund_bp": _bp(fund / notl),
           "notional_usd": notl, "hold_h": hold_h,
           "bands": {}}
    # полосы плеча: записи книги (все) и взятые кассой — одной сеткой
    for _lo, _hi, name in BANDS:
        rk = [r for r in kept if band_of(r["lev"]) == name]
        pk = [(row, rec) for row, rec in pairs if band_of(rec["lev"]) == name]
        b = {"n_records": len(rk),
             "S0": _bp(_mean([float(r["pnl_net"]) / float(r["lev"]) for r in rk])),
             "n_taken": len(pk)}
        if pk:
            nb = sum(float(row["margin"]) * float(row["lev"]) for row, _r in pk)
            b.update({
                "S1": _bp(_mean([float(rec["pnl_net"]) / float(rec["lev"]) for _row, rec in pk])),
                "S3": _bp(sum(float(row["usd_gross"]) - float(row["fee_usd"]) - float(row["slip_usd"])
                             + float(row.get("fund_usd") or 0.0) for row, _r in pk) / nb),
                "fee_bp": _bp(sum(float(row["fee_usd"]) for row, _r in pk) / nb),
                "slip_bp": _bp(sum(float(row["slip_usd"]) for row, _r in pk) / nb),
                "fund_bp": _bp(sum(float(row.get("fund_usd") or 0.0) for row, _r in pk) / nb),
                "hold_h": _mean([(float(rec["exit_ts"]) - float(rec["at"])) / 3600.0
                                 for _row, rec in pk]),
                "share_notional": nb / notl})
        out["bands"][name] = b
    return out


def verdict(c):
    """Фраза из чисел: наибольшая по модулю ось разрыва."""
    if not c or c.get("S3") is None:
        return "касса не взяла записей с измеримыми издержками — разрыв не раскладывается"
    axes = (("отбор кассой", c["d_select"]), ("вес долларами (плечо × билет)", c["d_weight"]),
            ("издержки против плоских 11 б.п.", c["d_costs"]))
    name, val = max(axes, key=lambda kv: abs(kv[1] or 0))
    gap = c["S3"] - c["S0"]
    share = (val / gap) if gap else None
    return (f"из {gap:+.1f} б.п. разрыва больше всего даёт «{name}»: {val:+.1f} б.п."
            + (f" ({share:.0%})" if share is not None and 0 < abs(share) < 10 else ""))


def run(log=print, now=None, launch=None, ctx=None, mem_limit=None, dep=MAIN_DEP):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None else mem_limit))
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    ctx = ctx if ctx is not None else CO.context()
    if not ctx or ctx.get("error"):
        return {"error": f"контекста издержек нет: {(ctx or {}).get('error')}"}
    launch = IR.launches() if launch is None else launch
    packed = AG.packed_short(cache)
    ruled = L.ruled(packed, launch, now=now)
    rows, _c, _o, _l = RP.build_rows(ruled, now=now, keys=BOOK_KEYS, log=lambda *a: None)
    books = {}
    for bk in BOOK_KEYS:
        mine = [r for r in rows if R.ruler_of(r) == bk and int(r.get("dep", 0)) == int(dep)]
        mine, cs = CO.apply_to_rows(mine, ctx)
        c = chain(packed.get(bk) or [], mine, bk)
        c["costs_summary"] = {k: cs.get(k) for k in ("applied", "no_fills", "no_funding",
                                                       "cover", "slip_bp")}
        c["verdict"] = verdict(c)
        books[bk] = c
        log(f"{bk}: записей {c['n_records']}, взято кассой {c['n_taken']}, "
            f"S0 {c['S0']:+.1f} → S3 {c['S3']:+.1f} б.п." if c.get("S3") is not None
            else f"{bk}: {c.get('note')}")
    return {"dep": dep, "books": BOOK_KEYS, "chain": books,
            "bands": [b[2] for b in BANDS], "steps": STEPS,
            "diag": {"records": len(cache), "rows": len(rows)},
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- отчёт
def _b(x, d=1):
    return "—" if x is None else f"{x:+.{d}f}"


def _n(x):
    return "—" if x is None else f"{int(x)}"


def _h(x):
    return "—" if x is None else f"{x:.1f}"


def _title(bk):
    return {"safe_h": "безопасная", "optimal_h": "оптимальная", "aggr_h": "агрессивная"}.get(bk, bk)


def report(s):
    if s.get("error"):
        return f"# Куда уходят 30 б.п.\n\nОШИБКА: {s['error']}\n"
    L_ = ["# Куда уходят 30 б.п.: разрыв между эджем в цене и кассой коротких книг",
          "",
          f"Касса ${s['dep']:,}; записей реплея {s['diag']['records']}, строк кассы {s['diag']['rows']}; "
          f"посчитано {s['computed_at']} за {s['secs']} с. Все числа — б.п. нотионала (в цене).",
          "",
          "Оси объявлены до прогона: S0 записи книги (равный вес, плоские 11 б.п. на заполненную долю) → "
          "S1 только взятые кассой (отбор) → S2 взвешенные долларами нотионала (вес) → "
          "S3 настоящие издержки: комиссия по заполнениям, проскальзывание X3, funding по рядам (издержки). "
          "S3 − S0 = Δ отбор + Δ вес + Δ издержки.",
          "",
          "| книга | записей | взято кассой | S0 | Δ отбор | S1 | Δ вес | S2 | Δ издержки | S3 | S3 равный вес | плоские | комиссия | проскальз. | funding | срок, ч |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in s["books"]:
        c = s["chain"][bk]
        L_.append(f"| {_title(bk)} | {_n(c['n_records'])} | {_n(c['n_taken'])} | {_b(c['S0'])} | "
                  f"{_b(c.get('d_select'))} | {_b(c.get('S1'))} | {_b(c.get('d_weight'))} | {_b(c.get('S2'))} | "
                  f"{_b(c.get('d_costs'))} | {_b(c.get('S3'))} | {_b(c.get('S3_eq'))} | "
                  f"{_b(c.get('flat_bp'))} | {_b(c.get('fee_bp'))} | {_b(c.get('slip_bp'))} | "
                  f"{_b(c.get('fund_bp'))} | {_h(c.get('hold_h'))} |")
    L_ += ["", "Издержки измерены у строк с записью заполнений и ценой выхода; доля таких строк и строки без ряда funding:", ""]
    for bk in s["books"]:
        c = s["chain"][bk]
        cs = c.get("costs_summary") or {}
        L_.append(f"- {_title(bk)}: с издержками {c.get('n_rows_costed', 0)} из {c.get('n_rows_all', 0)} строк"
                  f" ({(c.get('cover') or 0):.0%}), без ряда funding {c.get('n_rows_costed', 0) - c.get('n_funding', 0)},"
                  f" без записи реплея {c.get('lost', 0)}; проскальзывание модели "
                  f"{'—' if cs.get('slip_bp') is None else cs.get('slip_bp')} б.п.")
    L_ += ["", "## По полосам плеча забора", "",
           "Записи книги и взятые кассой — одной сеткой; S3 и издержки — по взятым, долларами.", ""]
    for bk in s["books"]:
        c = s["chain"][bk]
        L_ += [f"### {_title(bk)}", "",
               "| полоса | записей | S0 | взято | S1 | S3 | комиссия | проскальз. | funding | срок, ч | доля нотионала |",
               "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for name in s["bands"]:
            b = (c.get("bands") or {}).get(name) or {}
            L_.append(f"| {name} | {_n(b.get('n_records', 0))} | {_b(b.get('S0'))} | {_n(b.get('n_taken', 0))} | "
                      f"{_b(b.get('S1'))} | {_b(b.get('S3'))} | {_b(b.get('fee_bp'))} | {_b(b.get('slip_bp'))} | "
                      f"{_b(b.get('fund_bp'))} | {_h(b.get('hold_h'))} | "
                      f"{'—' if b.get('share_notional') is None else format(b['share_notional'], '.0%')} |")
        L_.append("")
    L_ += ["## Вердикт (из чисел)", ""]
    for bk in s["books"]:
        L_.append(f"- {_title(bk)}: {s['chain'][bk].get('verdict')}")
    L_ += ["", "Чего замер не делает: не меняет правила книг и не судит направление; "
           "он называет ось, на которой теряется ход, — что с ней делать, решает владелец.", ""]
    return "\n".join(L_)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(log=print)
    if s.get("error"):
        print(s["error"])
    G.write(s, ART, report, log=print)
    if not a.no_publish:
        publish("разрыв издержек коротких книг: куда уходят 30 б.п.")


if __name__ == "__main__":
    main()
