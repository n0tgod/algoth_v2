#!/usr/bin/env python3
"""Фикстура чётности: Python-счёт порождает ожидаемые числа для Rust.

Смысл — сверка E2 в миниатюре: синтетические выборы и разборы
прогоняются через НАСТОЯЩИЕ `trades.build` + `trades.account`, и их
результат (размеры, нетто, деньги, баланс) записывается ожиданием.
Rust-движок обязан сойтись с ним до цента на тех же входных файлах.
Разойдётся формула любой из сторон — тест назовёт сделку.

Запуск из корня репозитория:

    python3 bot/tests/gen_parity.py

Фикстура детерминирована (зерно закреплено) и лежит в git: тест Rust
читает готовые файлы и не требует Python на машине сборки.
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "research", "s8_loop"))
import trades as TR  # noqa: E402

OUT = os.path.join(HERE, "fixtures", "parity")
rng = random.Random(20260806)

FEES = [
    {"symbol": "AAAUSDT", "takerFeeRate": "0.00055"},
    {"symbol": "BBBUSDT", "takerFeeRate": "0.000275"},
    {"symbol": "CCCUSDT", "takerFeeRate": "0.0011"},
    # DDDUSDT в таблице нет — умолчание 5.5 и признак «не знаем».
]


def ladder(mid, side, thin=False):
    """Накопленная лесенка вокруг середины, как штампует stamp_book.

    `thin=True` — нарочно мелкая книга: заявка не влезает целиком, и
    честность частичного исполнения проверяется, а не предполагается.
    """
    out, cum, px = [], 0.0, mid
    step = mid * 0.0004
    for i in range(1, 6):
        px = mid + step * i if side == "a" else mid - step * i
        cum += (3.0 if thin else 120.0) + rng.random() * 5
        out.append([round(px, 6), round(cum, 2)])
    return out


def book(mid, thin=False):
    return {"mid": mid, "b": ladder(mid, "b", thin), "a": ladder(mid, "a", thin),
            "t": 0.0}


def leg(sym, px, drift_bp, thin=False, with_book=True):
    """Нога выбора и её же исход: выход сдвинут на drift_bp от входа."""
    out_mid = px * (1 + drift_bp / 1e4)
    entry = {"sym": sym, "px": px, "fwd": drift_bp, "mae": -drift_bp / 2}
    if with_book:
        entry["cum"] = book(px, thin)
    exit_row = {"cum": book(out_mid, thin)} if with_book else {}
    # Нетто прежней основы — для ноги без книг: got минус плоские 11.
    exit_row["got"] = drift_bp
    exit_row["net"] = drift_bp - 11.0
    return entry, exit_row


def main():
    os.makedirs(OUT, exist_ok=True)
    hours = ["2026-08-05-10", "2026-08-05-11", "2026-08-05-12"]
    picks, reviews = [], []
    for hi, hour in enumerate(hours):
        longs, shorts, rows = [], [], []
        for i, (sym, side) in enumerate(
                [("AAAUSDT", "long"), ("BBBUSDT", "long"),
                 ("CCCUSDT", "short"), ("DDDUSDT", "short")]):
            px = [50.0, 0.031, 1200.0, 7.5][i] * (1 + 0.001 * hi)
            drift = rng.uniform(-300, 300)
            # Одна нога без книг (прежняя основа), одна — тонкая книга.
            with_book = not (hi == 1 and i == 3)
            thin = hi == 2 and i == 0
            e, x = leg(sym, px, drift, thin=thin, with_book=with_book)
            (longs if side == "long" else shorts).append(e)
            x.update(sym=sym, side=side)
            rows.append(x)
        picks.append({"arm": "gbm", "hour": hour, "ver": 3,
                      "at_ts": (TR._ts(hour) or 0) + 3960,
                      "long": longs, "short": shorts})
        # Третий час остаётся без разбора — сделки обязаны висеть
        # открытыми, а не закрыться нулём.
        if hi < 2:
            reviews.append({"arm": "gbm", "hour": hour, "rows": rows})

    with open(os.path.join(OUT, "picks.jsonl"), "w", encoding="utf-8") as f:
        for p in picks:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "review.jsonl"), "w", encoding="utf-8") as f:
        for r in reviews:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "fees.json"), "w", encoding="utf-8") as f:
        json.dump(FEES, f)

    # Ожидание — НАСТОЯЩИМ Python-счётом по тем же файлам.
    table = {r["symbol"]: round(float(r["takerFeeRate"]) * 1e4, 4)
             for r in FEES}
    now = (TR._ts(hours[-1]) or 0) + 3600 + 5 * 3600
    tr = TR.build(picks, reviews, now=now)
    hist, balance = TR.account(tr, "gbm", start=1000.0, table=table)
    expected = {"balance": balance, "trades": []}
    for t in sorted((t for t in tr if t.get("size") is not None),
                    key=lambda t: (t["hour"], t["sym"], t["side"])):
        row = {"pos": f"gbm:{t['hour']}:{t['sym']}:{t['side']}",
               "size": t["size"], "state": t["state"]}
        if t["state"] == "закрыта":
            row.update(pnl=t.get("pnl"), net_bp=t.get("net_bp"),
                       basis=t.get("cost_basis"),
                       fill_in=t.get("fill_in"), fill_out=t.get("fill_out"))
        expected["trades"].append(row)
    with open(os.path.join(OUT, "expected.json"), "w", encoding="utf-8") as f:
        json.dump(expected, f, ensure_ascii=False, indent=1)
    closed = sum(1 for t in expected["trades"] if t["state"] == "закрыта")
    print(f"фикстура: сделок {len(expected['trades'])}, закрыто {closed}, "
          f"баланс {balance}")


if __name__ == "__main__":
    main()
