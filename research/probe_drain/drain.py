"""Разбор слива 2026-08-24…27: что случилось со сделками всех книг.

Вопрос владельца: до 23.08 почти каждый день плюсовой по всем моделям,
24–27.08 — три-четыре дня, когда все книги отдали накопленное. Нужно
понять, что происходило со сделками, и найти, за что зацепиться, чтобы
такие дни минимизировать.

Это РАЗБОР, а не гипотеза: порогов и вердикта нет, зонд отвечает
фактами. Окно слива названо владельцем (2026-08-24…27), база —
2026-08-13…23: с 13-го капитал книг равен 3000 $, то есть доллары
внутри базы и окна сравнимы; более ранние дни считались другой кассой.

Что считается и почему ровно это:

1. **Дневные деньги по книгам** — тем же ядром `trades.py` через
   `probe_turn.book_trades` (второй копии счёта нет; деньги штампует
   касса, а не разбор — урок лиги). День сделки — момент, когда деньги
   стали известны, как на странице learning.
2. **Состав сделок окна против базы**: доля побед, медиана, причины
   выходов ЧИСЛОМ И ДЕНЬГАМИ, стороны (лонг/шорт отдельными деньгами —
   ловушка «переодетый шорт беты» ловится только так), концентрация
   (худшее имя и итог без него — приём, переворачивавший выводы лиги).
3. **Рынок тех же дней** — по хранилищу A2 (докачано до ~08-26):
   медианная дневная доходность крипто-универсума, BTC/ETH, доля
   упавших имён, межквартильный размах сечения. Отдельный источник —
   отдельная колонка; дня без партиции НЕТ В ТАБЛИЦЕ ЧИСЛОМ, там
   прочерк («не измерено ≠ ноль», урок A2).
4. **Навык тех же дней** — медианный живой IC (fwd_4h, обе руки) из
   `ic_history.jsonl`: слив при живом IC и слив при умершем IC — два
   разных диагноза.
5. **Здоровье цикла** — `train_log.jsonl`: медианная длительность
   цикла по дням. Цикл, переставший влезать в час, задерживает выходы
   и старит лист сканера — внутренний подозреваемый, а не рыночный.
6. **Смены правил в окне** — архивы книг (`*.rules-*`, `*.rank-*`) с
   датой: слив, совпавший со сменой правил, читается иначе, чем слив
   на неизменных правилах.

Топ убыточных сделок окна печатается поимённо с `tid` — чтобы каждую
можно было открыть разбором, а не обсуждать по памяти.

Запуск на VPS (журналы книг живут там):
  cd ~/algoth_v2 && .venv/bin/python research/probe_drain/drain.py
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop"),
          os.path.join(os.path.dirname(HERE), "a4_cointegration")):
    if p not in sys.path:
        sys.path.insert(0, p)

import turn as PT                                          # noqa: E402

DAY = 86400
# Окно слива названо владельцем; база — дни ТОЙ ЖЕ кассы (капитал 3000
# с 2026-08-13). Сравнивать доллары через смену капитала нельзя.
DRAIN = ("2026-08-24", "2026-08-27")
BASE = ("2026-08-13", "2026-08-23")
TOP_TRADES = 15


def log_(m):
    print(m, flush=True)


def day_int(iso):
    return int(datetime.fromisoformat(iso + "T00:00:00+00:00")
               .timestamp()) // DAY


def dstr(d):
    return datetime.fromtimestamp(d * DAY, timezone.utc).strftime("%m-%d")


def in_win(day, win):
    return day_int(win[0]) <= day <= day_int(win[1])


def slice_stats(trades):
    """Состав среза сделок: победы, причины, стороны, концентрация."""
    if not trades:
        return {"n": 0}
    pnl = [t["pnl"] for t in trades]
    nets = sorted(t["net"] for t in trades if t.get("net") is not None)
    reasons = {}
    for t in trades:
        r = t.get("reason") or "срок"
        if not isinstance(r, str):
            r = str(r)
        d = reasons.setdefault(r, {"n": 0, "pnl": 0.0})
        d["n"] += 1
        d["pnl"] += t["pnl"]
    by_sym = {}
    for t in trades:
        by_sym[t["sym"]] = by_sym.get(t["sym"], 0.0) + t["pnl"]
    worst = min(by_sym, key=lambda s: by_sym[s])
    longs = [t for t in trades if t.get("side") == "long"]
    shorts = [t for t in trades if t.get("side") == "short"]
    return {
        "n": len(trades), "pnl": round(sum(pnl), 2),
        "win": round(sum(1 for v in pnl if v > 0) / len(pnl), 3),
        "med_bp": round(nets[len(nets) // 2], 1) if nets else None,
        "long_n": len(longs), "short_n": len(shorts),
        "long_pnl": round(sum(t["pnl"] for t in longs), 2),
        "short_pnl": round(sum(t["pnl"] for t in shorts), 2),
        "reasons": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)}
                    for k, v in sorted(reasons.items(),
                                       key=lambda kv: kv[1]["pnl"])},
        "worst_sym": worst, "worst_pnl": round(by_sym[worst], 2),
        "pnl_wo_worst": round(sum(pnl) - by_sym[worst], 2)}


def crypto_symbols():
    """Крипто-универсум по справочнику: не-крипто в контекст не идёт —
    его календарная компонента (биржа закрыта ночью и в выходные)
    искривила бы медиану сечения."""
    path = os.path.join(ROOT, "research", "a1_universe", "out",
                        "universe.json")
    with open(path, encoding="utf-8") as f:
        u = json.load(f)
    return sorted(a["binance_symbol"] for a in u["assets"].values()
                  if a.get("asset_class") == "crypto"
                  and a.get("binance_symbol"))


def market_ctx(d0, d1, log=log_):
    """Дневная доходность сечения по A2: медиана, BTC/ETH, доля вниз.

    Открытие дня — первый бар со сделкой, закрытие — последний: бар с
    `trades = 0` — пропуск, а не наблюдение (урок A2, замороженные
    ряды). День без партиции отсутствует в ответе — таблица обязана
    печатать там прочерк, а не ноль.
    """
    import duckdb                                          # noqa: F401
    import series as S
    syms = crypto_symbols()
    want = "', '".join(syms)
    months = sorted({datetime.fromtimestamp(d * DAY, timezone.utc)
                     .strftime("%Y-%m") for d in range(d0, d1 + 1)})
    con = S.connect()
    rows = []
    for mon in months:
        path = os.path.join(S.PARQUET, "1m", f"{mon}.parquet")
        if not os.path.exists(path):
            log(f"  контекст: партиции {mon} нет — дни без чисел")
            continue
        q = f"""
            SELECT symbol,
                   epoch(open_time)::BIGINT // {DAY} AS d,
                   arg_min(open, open_time) AS o,
                   arg_max(close, open_time) AS c
            FROM read_parquet('{path}')
            WHERE trades > 0 AND symbol IN ('{want}')
              AND epoch(open_time) >= {d0 * DAY}
              AND epoch(open_time) < {(d1 + 1) * DAY}
            GROUP BY 1, 2
        """
        rows += con.execute(q).fetchall()
    import numpy as np
    by_day = {}
    for sym, d, o, c in rows:
        if o and o > 0 and c and c > 0:
            by_day.setdefault(int(d), {})[sym] = c / o - 1.0
    out = {}
    for d, rets in by_day.items():
        v = np.array(list(rets.values()))
        # Медиана сечения по паре сотен имён — не «полный день»
        # автоматически: день, обрезанный краем архива, даст
        # доходность огрызка. Имён меньше сотни — день не считается.
        if len(v) < 100:
            continue
        out[d] = {"n": len(v),
                  "med": round(float(np.median(v)) * 1e4, 0),
                  "btc": round(rets.get("BTCUSDT", float("nan")) * 1e4, 0),
                  "eth": round(rets.get("ETHUSDT", float("nan")) * 1e4, 0),
                  "down": round(float((v < 0).mean()), 2),
                  "iqr": round(float(np.percentile(v, 75)
                                     - np.percentile(v, 25)) * 1e4, 0)}
    return out


def ic_by_day(model_dir):
    """Медианный живой IC (fwd_4h, обе руки) по дням."""
    import numpy as np
    rows = PT.read_jsonl(os.path.join(model_dir, "ic_history.jsonl"))
    per = {}
    for r in rows:
        if r.get("target") != "fwd_4h" or r.get("kind") != "section":
            continue
        h = r.get("hour") or ""
        if len(h) < 10:
            continue
        d = day_int(h[:10])
        per.setdefault(d, []).append(float(r.get("median_ic") or 0.0))
    return {d: {"ic": round(float(np.median(v)), 4), "n": len(v)}
            for d, v in per.items()}


def cycle_by_day(model_dir):
    """Длительность цикла по дням: не влезающий в час цикл старит лист
    сканера и задерживает выходы — внутренний подозреваемый."""
    import numpy as np
    rows = PT.read_jsonl(os.path.join(model_dir, "train_log.jsonl"))
    per = {}
    for r in rows:
        h = r.get("hour") or ""
        c = r.get("cycle_sec")
        if len(h) < 10 or c is None:
            continue
        per.setdefault(day_int(h[:10]), []).append(float(c))
    return {d: {"med": round(float(np.median(v)), 0),
                "max": round(float(max(v)), 0), "n": len(v)}
            for d, v in per.items()}


def rule_archives(s8, d0, d1):
    """Архивы книг, датированные окном: смена правил — событие разбора."""
    out = []
    try:
        names = sorted(os.listdir(s8))
    except OSError:
        return out
    for name in names:
        if ".rules-" not in name and ".rank-" not in name:
            continue
        try:
            mt = os.path.getmtime(os.path.join(s8, name))
        except OSError:
            continue
        d = int(mt) // DAY
        if d0 - 1 <= d <= d1 + 1:
            out.append({"dir": name,
                        "at": datetime.fromtimestamp(
                            mt, timezone.utc).strftime("%Y-%m-%d %H:%M")})
    return out


def collect(s8, log=log_):
    books = {}
    for key, name, echo in PT.BOOKS:
        trades, _man = PT.book_trades(os.path.join(s8, name))
        base = [t for t in trades if in_win(t["day"], BASE)]
        drain = [t for t in trades if in_win(t["day"], DRAIN)]
        books[key] = {"echo": echo,
                      "daily": PT.daily(trades),
                      "base": slice_stats(base),
                      "drain": slice_stats(drain),
                      "drain_trades": drain}
        log(f"{key}: базовых сделок {len(base)}, в окне {len(drain)}")
    return books


def top_losers(books, k=TOP_TRADES):
    rows = []
    for key, b in books.items():
        if b.get("echo"):
            continue                 # эхо повторяет решения источника
        for t in b["drain_trades"]:
            rows.append({"book": key, **{f: t.get(f) for f in
                        ("arm", "sym", "side", "day", "net",
                         "pnl", "reason", "tid")}})
    return sorted(rows, key=lambda r: r["pnl"])[:k]


def fmt(v, spec="+.2f", dash="—"):
    if v is None:
        return dash
    try:
        if v != v:
            return dash
    except TypeError:
        return dash
    return format(v, spec)


def write_report(path, books, ctx, ic, cyc, arch, meta):
    d0, d1 = day_int(BASE[0]), day_int(DRAIN[1])
    keys = [k for k, _n, _e in PT.BOOKS]
    L = ["# Разбор слива 2026-08-24…27\n",
         f"\nПрогон {meta['when']} · база {BASE[0]}…{BASE[1]} (та же "
         f"касса: капитал 3000 $ с 08-13) · окно слива {DRAIN[0]}…"
         f"{DRAIN[1]} (названо владельцем)\n",
         "\nЭто разбор, а не гипотеза: порогов и вердикта нет. Деньги "
         "считает та же касса, что у страниц (`trades.py`); день "
         "сделки — момент, когда деньги стали известны, как на "
         "странице learning.\n"]

    L.append("\n## Деньги по дням и книгам ($)\n\n")
    L.append("| день | " + " | ".join(keys) + " | всего | сделок |\n")
    L.append("|---|" + "--:|" * (len(keys) + 2) + "\n")
    for d in range(d0, d1 + 1):
        cells, tot, n = [], 0.0, 0
        for k in keys:
            v = books[k]["daily"].get(d)
            cells.append(fmt(v))
            if v is not None and not books[k]["echo"]:
                tot += v
            n += sum(1 for t in books[k].get("drain_trades", [])
                     if t["day"] == d) if in_win(d, DRAIN) else 0
        mark = " ←" if in_win(d, DRAIN) else ""
        L.append(f"| {dstr(d)}{mark} | " + " | ".join(cells)
                 + f" | **{tot:+.2f}** | {n or '—'} |\n")
    L.append("\n«Всего» — сумма БЕЗ книг-эха (sit_r, h24b, h24bf — те "
             "же решения под другим правилом, второй счёт был бы "
             "двойным). Колонка сделок заполнена только в окне.\n")

    L.append("\n## Рынок, навык и цикл тех же дней\n\n")
    L.append("| день | имён | медиана сечения, б.п. | BTC | ETH | "
             "доля вниз | IQR, б.п. | IC дня | цикл, с (мед./макс.) |\n")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|\n")
    for d in range(d0, d1 + 1):
        c = ctx.get(d)
        i = ic.get(d)
        cy = cyc.get(d)
        mark = " ←" if in_win(d, DRAIN) else ""
        L.append(
            f"| {dstr(d)}{mark} | {c['n'] if c else '—'} | "
            f"{fmt(c and c['med'], '+.0f')} | {fmt(c and c['btc'], '+.0f')} | "
            f"{fmt(c and c['eth'], '+.0f')} | {fmt(c and c['down'], '.2f')} | "
            f"{fmt(c and c['iqr'], '.0f')} | "
            f"{fmt(i and i['ic'], '+.4f')} | "
            + (f"{cy['med']:.0f}/{cy['max']:.0f}" if cy else "—") + " |\n")
    L.append("\nДень без чисел рынка — партиции A2 ещё нет (суточный "
             "архив выходит после конца суток): это пропуск, а не "
             "ноль. IC — медианный живой IC fwd_4h за день по обеим "
             "рукам.\n")

    L.append("\n## Окно против базы, по книгам\n\n")
    L.append("| книга | срез | сделок | $ | побед | медиана, б.п. | "
             "лонгов | $ лонгов | $ шортов | худшее имя | $ без него |\n")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|---|--:|\n")
    for k in keys:
        b = books[k]
        for tag, s in (("база", b["base"]), ("слив", b["drain"])):
            if not s.get("n"):
                L.append(f"| {k} | {tag} | 0 | — | — | — | — | — | — "
                         f"| — | — |\n")
                continue
            L.append(
                f"| {k}{' (эхо)' if b['echo'] else ''} | {tag} | "
                f"{s['n']} | {s['pnl']:+.2f} | {s['win']:.2f} | "
                f"{fmt(s['med_bp'], '+.1f')} | {s['long_n']} | "
                f"{s['long_pnl']:+.2f} | {s['short_pnl']:+.2f} | "
                f"{s['worst_sym']} {s['worst_pnl']:+.2f} | "
                f"{s['pnl_wo_worst']:+.2f} |\n")

    L.append("\n## Причины выходов: деньги причин в окне (не-эхо)\n\n")
    agg = {}
    for k in keys:
        b = books[k]
        if b["echo"] or not b["drain"].get("n"):
            continue
        for r, v in b["drain"]["reasons"].items():
            d = agg.setdefault(r, {"n": 0, "pnl": 0.0})
            d["n"] += v["n"]
            d["pnl"] += v["pnl"]
    L.append("| причина выхода | сделок | $ |\n|---|--:|--:|\n")
    for r, v in sorted(agg.items(), key=lambda kv: kv[1]["pnl"]):
        L.append(f"| {r} | {v['n']} | {v['pnl']:+.2f} |\n")

    L.append(f"\n## Худшие сделки окна (топ-{TOP_TRADES}, не-эхо)\n\n")
    L.append("| книга | рука | имя | стор. | день | нетто, б.п. | $ | "
             "причина | tid |\n|---|---|---|:--:|---|--:|--:|---|---|\n")
    for r in top_losers(books):
        L.append(f"| {r['book']} | {r['arm']} | {r['sym']} | "
                 f"{'L' if r['side'] == 'long' else 'S'} | "
                 f"{dstr(r['day'])} | {fmt(r['net'], '+.1f')} | "
                 f"{r['pnl']:+.2f} | {r['reason']} | "
                 f"{r.get('tid') or '—'} |\n")

    L.append("\n## Смены правил книг вокруг окна\n\n")
    if arch:
        for a in arch:
            L.append(f"- `{a['dir']}` — архив от {a['at']} UTC\n")
        L.append("\nСлив на фоне смены правил читается иначе, чем слив "
                 "на неизменных: часть истории в эти дни принадлежит "
                 "другой книге.\n")
    else:
        L.append("Архивов книг, датированных окном, нет — правила в "
                 "эти дни не менялись.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="разбор слива 08-24…27")
    ap.add_argument("--s8", default=os.path.join(
        ROOT, "research", "s8_loop", "out"))
    ap.add_argument("--tag", default="0824")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)      # урок турнира: до счёта

    books = collect(a.s8)
    d0, d1 = day_int(BASE[0]), day_int(DRAIN[1])
    try:
        ctx = market_ctx(d0, d1)
    except Exception as e:                                # noqa: BLE001
        log_(f"контекст рынка не посчитан: {e}")
        ctx = {}
    model_dir = os.path.join(a.s8, "model")
    ic = ic_by_day(model_dir)
    cyc = cycle_by_day(model_dir)
    arch = rule_archives(a.s8, d0, d1)

    art = {"base": BASE, "drain": DRAIN,
           "books": {k: {kk: v[kk] for kk in ("base", "drain", "echo")}
                     for k, v in books.items()},
           "daily": {k: {str(d): round(v, 2)
                         for d, v in b["daily"].items() if d0 <= d <= d1}
                     for k, b in books.items()},
           "ctx": {str(d): v for d, v in ctx.items()},
           "ic": {str(d): v for d, v in ic.items()},
           "cycle": {str(d): v for d, v in cyc.items()},
           "top": top_losers(books), "archives": arch,
           "took_sec": round(time.time() - t0, 1)}
    with open(os.path.join(out_dir, f"drain-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    path = write_report(
        os.path.join(out_dir, f"DRAIN-report-{a.tag}.md"),
        books, ctx, ic, cyc, arch,
        {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
    log_(f"отчёт: {path} · {art['took_sec']} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
