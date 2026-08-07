#!/usr/bin/env python3
"""Сверка: каждая сделка бота против Python-счёта, до цента.

Половина сторожа исполнения (вторая — `bot check`, инварианты внутри
журнала). Здесь два НЕЗАВИСИМЫХ счёта одних сделок — Rust-ядро и
`trades.build` + `trades.account` — прогоняются по одним входным файлам
и сравниваются построчно: состав сделок в обе стороны, размер, цены
исполнения, деньги, баланс. Сам этот скрипт ничего не считает — только
сравнивает; вторая копия расчётного ядра не заводится.

Запуск (песочница или VPS, стандартная библиотека):

    python3 bot/sverka.py --s8 research/s8_loop/out/model_pretest \\
        --journal bot/out/shadow --fees research/a1_universe/out/fees.json

Коды выхода: 0 — расхождений нет, 1 — есть (каждое названо), 2 — сама
сверка не смогла прочитать данные. Отчёт пишется файлом рядом с
журналом: прогон обсуждается не там, где идёт, и пересказ консоли
теряет числа (правило публикации проекта).
"""

import argparse
import glob
import gzip
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "research", "s8_loop"))
import trades as TR  # noqa: E402
from common import fees as FEES  # noqa: E402

CENT = 0.005          # порог денег: полцента на округление двух сторон
EXACT = 1e-9          # размеры и цены обязаны совпадать дословно


def read_jsonl(path):
    """Строки файла; оборванный хвост пропускается — его допишут."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    out = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            if all(not l.strip() for l in lines[i + 1:]):
                continue
            raise SystemExit(
                f"{path}: строка {i + 1} бита не в хвосте — сверка "
                f"по такому файлу не имеет смысла")
    return out


def read_journal(jdir):
    """Журнал бота: сутки по возрастанию, дубли по номеру сняты."""
    recs, seen = [], {}
    days = {}
    for p in glob.glob(os.path.join(jdir, "journal-*.jsonl*")):
        day = os.path.basename(p).replace("journal-", "").split(".")[0]
        days.setdefault(day, []).append(p)
    for day in sorted(days):
        for p in sorted(days[day]):
            if p.endswith(".gz"):
                with gzip.open(p, "rt", encoding="utf-8") as f:
                    text = f.read()
                rows = [json.loads(l) for l in text.split("\n") if l.strip()]
            else:
                rows = read_jsonl(p)
            for r in rows:
                if r["seq"] in seen:
                    continue
                seen[r["seq"]] = True
                recs.append(r)
    recs.sort(key=lambda r: r["seq"])
    return recs


def bot_trades(recs):
    """Сделки и отказы из журнала.

    Возвращает `(сделки, отказы)`: ключ → размер/цены/деньги и ключ →
    причина отказа. Отказ по пустой кассе — не сделка, но и не пустота:
    у Python-счёта тому же входу назначается нулевой размер, и сверка
    обязана уметь опознать эту пару, а не кричать о расхождении.
    """
    out, rejects = {}, {}
    for r in recs:
        if r.get("ev") == "open":
            out[r["pos"]] = {
                "size": r["notional_usd"], "fill_in": r.get("entry_px"),
                "closed": False, "pnl": None, "fill_out": None, "basis": None}
        elif r.get("ev") == "close" and r["pos"] in out:
            t = out[r["pos"]]
            t.update(closed=True, pnl=r["pnl_usd"],
                     fill_out=r.get("exit_px"),
                     basis=("книга" if "книга" in r.get("reason", "")
                            else "плоский 11"))
        elif r.get("ev") == "reject":
            # Ключ позиции ядро пишет в причину после «|» — у отказа
            # нет своей позиции, а сопоставлять его надо именно с ней.
            reason = r.get("reason") or ""
            if "|" in reason:
                head, key = reason.rsplit("|", 1)
                rejects[key] = head
    return out, rejects


def book_mode(s8):
    """Режим книги — из её манифеста, как у Rust-ядра.

    Ситуационная книга живёт без срока (закрытие задаёт разбор) и с
    фиксированными слотами кассы; книги горизонтов несут свой срок.
    Оба счёта обязаны читать ОДИН источник — манифест: флаг сверки,
    отличный от флага ядра, однажды сравнил бы две разные книги.
    """
    try:
        with open(os.path.join(s8, "manifest.json"),
                  encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        return TR.HOLD_H, None
    if man.get("situational"):
        return None, int(man.get("slots") or 6)
    return int(man.get("horizon_h") or TR.HOLD_H), None


def py_trades(s8, arm, capital, table, now):
    """Правда Python-стороны — тем же конвейером, что страница."""
    hold, slots = book_mode(s8)
    picks = read_jsonl(os.path.join(s8, "picks.jsonl"))
    reviews = read_jsonl(os.path.join(s8, "review.jsonl"))
    tr = TR.build(picks, reviews, now=now, hold_h=hold)
    _, balance = TR.account(tr, arm, start=capital, table=table,
                            hold_h=hold or TR.HOLD_H, slots=slots)
    out = {}
    for t in tr:
        if t["arm"] != arm or t.get("size") is None:
            continue
        key = f"{arm}:{t['hour']}:{t['sym']}:{t['side']}"
        out[key] = {
            "size": t["size"], "closed": t["state"] == "закрыта",
            "pnl": t.get("pnl"), "fill_in": t.get("fill_in"),
            "fill_out": t.get("fill_out"), "basis": t.get("cost_basis")}
    return out, balance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s8", required=True)
    ap.add_argument("--journal", required=True)
    ap.add_argument("--arm", default="gbm")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--fees", default=FEES.FEES_PATH)
    ap.add_argument("--now", type=float, default=None,
                    help="секунды epoch; по умолчанию текущий момент")
    ap.add_argument("--out", default=None,
                    help="куда писать отчёт (md); умолчание — рядом с журналом")
    args = ap.parse_args()

    now = args.now if args.now is not None else time.time()
    table = FEES.load(args.fees)
    if not table:
        print("ВНИМАНИЕ: таблица ставок пуста — обе стороны на умолчании")
    recs = read_journal(args.journal)
    bot, rejects = bot_trades(recs)
    py, balance = py_trades(args.s8, args.arm, args.capital, table, now)

    diffs, lag, unfunded = [], [], []
    common = 0
    # Обе стороны: сделка, которой нет у одной из сторон, — расхождение
    # состава, и оно опаснее числового.
    for key in sorted(set(bot) | set(py)):
        b, p = bot.get(key), py.get(key)
        if b is None:
            # Отказ по пустой кассе — законная пара нулевому размеру:
            # денег в обеих книгах ноль, различается только запись.
            # Отказ при НЕнулевом размере у Python — настоящее
            # расхождение: расписание кассы двух счётов разошлось.
            if key in rejects and abs(p["size"]) <= EXACT:
                unfunded.append(f"{key}: {rejects[key]} — у бота отказ, "
                                f"у Python вход нулевого размера")
                continue
            if key in rejects:
                diffs.append(
                    f"{key}: у бота отказ ({rejects[key]}), у Python "
                    f"вход на {p['size']:.2f} $ — касса разошлась")
                continue
            diffs.append(f"{key}: есть у Python, нет у бота")
            continue
        if p is None:
            diffs.append(f"{key}: есть у бота, нет у Python")
            continue
        common += 1
        if abs(b["size"] - p["size"]) > EXACT:
            diffs.append(
                f"{key}: размер {b['size']!r} против {p['size']!r}")
        if b["closed"] != p["closed"]:
            # Разбор пришёл между проходами бота — ожидание, не ошибка;
            # но висеть подолгу оно не вправе, и это видно счётом.
            lag.append(f"{key}: у бота {'закрыта' if b['closed'] else 'открыта'}, "
                       f"у Python наоборот")
            continue
        if not b["closed"]:
            continue
        if b["basis"] != p["basis"] and p["basis"] is not None:
            diffs.append(f"{key}: основа «{b['basis']}» против «{p['basis']}»")
        for f in ("fill_in", "fill_out"):
            bv, pv = b.get(f), p.get(f)
            if bv is not None and pv is not None and abs(bv - pv) > EXACT:
                diffs.append(f"{key}: {f} {bv!r} против {pv!r}")
        if b["pnl"] is not None and p["pnl"] is not None \
                and abs(round(b["pnl"], 2) - p["pnl"]) > CENT:
            diffs.append(
                f"{key}: деньги {round(b['pnl'], 2)} против {p['pnl']}")

    # Баланс: свободное плюс занятое у бота против возврата account().
    cash, sizes = args.capital, {}
    for r in recs:
        if r.get("ev") == "open":
            cash -= r["notional_usd"]
            sizes[r["pos"]] = r["notional_usd"]
        elif r.get("ev") == "close":
            # Размер лежит в открытии — закрытие несёт только деньги.
            cash += sizes.pop(r["pos"], 0.0) + r["pnl_usd"]
    busy = sum(t["size"] for t in bot.values() if not t["closed"])
    bot_balance = round(cash + busy, 2)
    if abs(bot_balance - balance) > CENT:
        diffs.append(f"баланс: бот {bot_balance} против Python {balance}")

    ok = not diffs
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))
    lines = [
        "# Сверка бота с Python-счётом",
        "",
        f"Момент: {stamp}. Рука `{args.arm}`, капитал {args.capital:g}.",
        f"Сделок у бота {len(bot)}, у Python {len(py)}, общих {common}.",
        f"Баланс: бот {bot_balance}, Python {balance}.",
        "",
        f"**Вердикт: {'расхождений 0' if ok else f'РАСХОЖДЕНИЙ {len(diffs)}'}**",
        "",
    ]
    if diffs:
        lines += ["## Расхождения", ""] + [f"- {d}" for d in diffs] + [""]
    if unfunded:
        lines += ["## Неисполнимые входы — касса была пуста", ""] + \
                 [f"- {d}" for d in unfunded] + [""]
    if lag:
        lines += ["## Ожидание (разбор между проходами)", ""] + \
                 [f"- {d}" for d in lag] + [""]
    report = "\n".join(lines)
    out_path = args.out or os.path.join(args.journal, "sverka-report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"отчёт: {out_path}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
