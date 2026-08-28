"""Зонд перелома: почему книги сначала зарабатывают, а потом сливают.

Наблюдение владельца (2026-08-24): «все наши модели сначала
зарабатывают, а потом в какой-то момент начинают сливать всё — то есть
что-то происходит на рынке». Вопрос законный, и у него ТРИ разных
ответа, требующих разных действий:

1. РЕЖИМ. На рынке действительно меняется что-то общее, и книги ломает
   одновременно. Тогда нужен детектор режима, а не новая гипотеза.
2. ФОРМА. Все проверенные конструкции собирают понемногу и изредка
   отдают много (короткая волатильность). Тогда «слив» не событие, а
   свойство распределения, и лечится он размером и гейтом.
3. ИЛЛЮЗИЯ ПИКА. Кумулятивная кривая ПОСЛЕ своего максимума идёт вниз
   по определению — «момент перелома» находится и в чистом шуме.

Третье проверяется первым, потому что оно самое дешёвое и обесценивает
остальные: если наблюдаемая картина неотличима от той же истории с
ПЕРЕМЕШАННЫМИ днями, никакого «момента» нет вовсе. Приём тот же, что
перемешанные метки групп в A4.

Что считается:
- дневные деньги каждой книги — ядром `trades.py` (второй копии счёта
  в проекте нет);
- пик кривой, доля денег, набранная до пика, глубина падения после;
- перестановочный нуль по дням, зерно закреплено ЧИСЛОМ (урок R3:
  нуль, который нельзя повторить, не является проверяемым);
- синхронность книг — доля дней, когда в минусе ВСЕ книги разом,
  против того же на перемешанных днях каждой книги отдельно (при
  независимости совпадения редки, при общем факторе — часты);
- что изменилось в самих сделках до и после пика: доля выходов по
  стопу, стороны, доля денег одного имени.

Чего зонд НЕ делает: не выносит вердикта и не предлагает правил. Он
отвечает на один вопрос — есть ли перелом на самом деле, и общий ли он
у книг.

Запуск на VPS (данные — журналы книг — живут там):
  cd ~/algoth_v2 && .venv/bin/python research/probe_turn/turn.py
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))

DAY = 86400
PERMS = 2000
# Сколько дней истории нужно книге, чтобы участвовать в мере
# синхронности: у книги, заведённой вчера, общих дней с остальными нет
# по построению.
MIN_DAYS = 10
SEED = 20260824          # зерно числом, а не от часов запуска

# Торгуемые книги: та же карта, что у сервера. Эхо-книги (тот же
# набор решений под другим правилом) помечаются, но не выбрасываются —
# вопрос владельца ровно про то, ломается ли ВСЁ разом, и книга-эхо
# отвечает на него наравне с источником.
BOOKS = (("h4", "model", False), ("h24", "model_h24", False),
         ("h24b", "model_h24b", True), ("h24bf", "model_h24bf", True),
         ("sit", "model_sit", False), ("sit_lo", "model_sit_lo", False),
         ("sit_r", "model_sit_r", True), ("z", "model_h24z", False))


def read_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def book_trades(mdir):
    """Закрытые сделки книги с деньгами — ядром `trades.py`.

    Деньги штампует КАССА, а не разбор: в `review.jsonl` лежат ход и
    нетто, а `pnl` появляется только при пересчёте счёта — размер
    позиции знает лишь он. Лига однажды уже показывала ноль сделок
    ровно потому, что кассу не звала.
    """
    import trades as TR
    try:
        with open(os.path.join(mdir, "manifest.json"),
                  encoding="utf-8") as f:
            mman = json.load(f)
    except (OSError, ValueError):
        return [], None
    sit = bool(mman.get("situational"))
    hold = None if sit else int(mman.get("horizon_h") or TR.HOLD_H)
    picks = read_jsonl(os.path.join(mdir, "picks.jsonl"))
    revs = read_jsonl(os.path.join(mdir, "review.jsonl"))
    tr = TR.build(picks, revs, hold_h=hold,
                  books=TR.load_books(os.path.join(mdir, "books.jsonl")))
    for a in ("gbm", "nn"):
        TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                   slots=mman.get("slots"), sizing=mman.get("sizing"))
    out = []
    for t in tr:
        if t.get("state") != "закрыта" or t.get("pnl") is None:
            continue
        # День, когда деньги стали ИЗВЕСТНЫ, а не когда позиция
        # открыта: то же выражение, что у лиги. У книги СО СРОКОМ
        # события выхода нет вовсе — она закрывается временем, и
        # `exit_ts` там пуст; первая версия зонда фильтровала по нему
        # и молча теряла все книги со сроком, то есть половину
        # вопроса владельца. Поймано смоуком.
        ts = (t.get("exit_ts") or t.get("closes_at")
              or t.get("opened_at"))
        if not ts:
            continue
        # Причина выхода — `exit_reason`. Поле `why` у живой сделки
        # занято ДРУГИМ: это объяснение ВХОДА, до трёх признаков с
        # вкладом, то есть список. Первый прогон на сервере упал на
        # нём («unhashable type: list»), а смоук прошёл, потому что
        # фикстура несла строку — подставной артефакт обязан
        # выглядеть как живой (урок лиги).
        out.append({"day": int(ts // DAY), "pnl": float(t["pnl"]),
                    "net": t.get("net_bp"),
                    "reason": t.get("exit_reason") or "срок",
                    "side": t.get("side"), "sym": t.get("sym"),
                    # id сделки едет дальше, чтобы разбор слива мог
                    # назвать худшие сделки поимённо, а не по памяти
                    "tid": t.get("tid"),
                    "arm": t.get("arm")})
    return out, mman


def daily(trades):
    d = {}
    for t in trades:
        d[t["day"]] = d.get(t["day"], 0.0) + t["pnl"]
    return d


def curve(days):
    """Кумулятивная кривая по календарю, без пропусков дней."""
    if not days:
        return [], []
    lo, hi = min(days), max(days)
    xs, run, ys = [], 0.0, []
    for d in range(lo, hi + 1):
        run += days.get(d, 0.0)
        xs.append(d)
        ys.append(run)
    return xs, ys


def peak_stats(days):
    """Пик кривой и что было по обе стороны от него.

    `share_before` — доля ИТОГОВОГО хода, набранная до пика. У чисто
    растущей книги она равна единице, у шума — около половины по
    построению, и именно поэтому одна эта величина ничего не
    доказывает: её обязан судить перестановочный нуль.
    """
    xs, ys = curve(days)
    if not ys:
        return None
    top = max(range(len(ys)), key=lambda i: ys[i])
    peak, end = ys[top], ys[-1]
    return {"days": len(ys), "peak_i": top, "peak": round(peak, 2),
            "end": round(end, 2), "drop": round(peak - end, 2),
            "share_before": round(top / max(1, len(ys) - 1), 3),
            "dd": round(min(y - max(ys[:i + 1])
                            for i, y in enumerate(ys)), 2)}


def perm_test(days, perms=PERMS, seed=SEED):
    """Те же дни в случайном порядке: как выглядит «перелом» у шума.

    Порядок дней — единственное, что меняется. Значит любая разница
    принадлежит ПОРЯДКУ (то есть времени, то есть режиму), а не
    величине дневных денег и не их разбросу.
    """
    import numpy as np
    obs = peak_stats(days)
    if obs is None or obs["days"] < 5:
        return {"n": 0}
    vals = [days.get(d, 0.0)
            for d in range(min(days), max(days) + 1)]
    rng = np.random.default_rng(seed)
    drops, shares = [], []
    for _ in range(perms):
        v = rng.permutation(vals)
        run = np.cumsum(v)
        top = int(np.argmax(run))
        drops.append(float(run[top] - run[-1]))
        shares.append(top / max(1, len(v) - 1))
    drops, shares = np.array(drops), np.array(shares)
    return {"n": perms,
            "drop_obs": obs["drop"],
            "drop_null_med": round(float(np.median(drops)), 2),
            "drop_null_p95": round(float(np.percentile(drops, 95)), 2),
            # Доля перестановок, где падение после пика НЕ МЕНЬШЕ
            # наблюдаемого: это и есть p-значение «перелом есть».
            "p_drop": round(float((drops >= obs["drop"]).mean()), 4),
            "share_obs": obs["share_before"],
            "share_null_med": round(float(np.median(shares)), 3),
            "p_share": round(float((shares >= obs["share_before"]).mean()),
                             4)}


def sync_stats(books, seed=SEED):
    """Синхронны ли просадки книг — против того же на перемешанных днях.

    Меряется доля общих дней, где в минусе ВСЕ книги разом. При
    независимости такие дни редки (произведение долей), при общем
    факторе — часты. Нуль строится перемешиванием дней КАЖДОЙ книги
    по отдельности: он сохраняет и число убыточных дней, и величины,
    ломая только совпадение по календарю.
    """
    import numpy as np
    # Пересечение ВСЕХ книг равно пересечению с самой молодой: одна
    # книга, заведённая вчера, обнуляла бы меру для всех остальных.
    # Поэтому синхронность считается по книгам с достаточной
    # историей, а молодые называются отдельно — иначе «мера не
    # построена» выглядело бы как «синхронности нет».
    long_enough = {k: v for k, v in books.items() if len(v) >= MIN_DAYS}
    skipped = sorted(set(books) - set(long_enough))
    keys = sorted(long_enough)
    if len(keys) < 2:
        return {"books": len(keys), "skipped": skipped,
                "why": "книг с историей меньше двух"}
    common = sorted(set.intersection(*[set(long_enough[k]) for k in keys]))
    if len(common) < 5:
        return {"books": len(keys), "common_days": len(common),
                "skipped": skipped,
                "why": "общих дней меньше пяти"}
    books = long_enough
    m = np.array([[books[k].get(d, 0.0) for d in common] for k in keys])
    all_down = float(np.mean(np.all(m < 0, axis=0)))
    all_up = float(np.mean(np.all(m > 0, axis=0)))
    rng = np.random.default_rng(seed)
    downs, ups = [], []
    for _ in range(500):
        p = np.array([rng.permutation(row) for row in m])
        downs.append(float(np.mean(np.all(p < 0, axis=0))))
        ups.append(float(np.mean(np.all(p > 0, axis=0))))
    # Попарная связь дневных денег: если книги ломает общее, она
    # положительна и заметно выше нуля.
    cors = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = m[i], m[j]
            if a.std() > 0 and b.std() > 0:
                cors.append(float(np.corrcoef(a, b)[0, 1]))
    return {"books": len(keys), "common_days": len(common),
            "skipped": skipped, "names": keys,
            "all_down": round(all_down, 3),
            "all_down_null": round(float(np.median(downs)), 3),
            "p_all_down": round(float((np.array(downs) >= all_down).mean()),
                                4),
            "all_up": round(all_up, 3),
            "all_up_null": round(float(np.median(ups)), 3),
            "corr_med": round(float(np.median(cors)), 3) if cors else None,
            "corr_min": round(float(min(cors)), 3) if cors else None,
            "corr_max": round(float(max(cors)), 3) if cors else None,
            "pairs": len(cors)}


def split_by_peak(trades, days):
    """Что изменилось в сделках до и после пика кривой.

    Если перелом настоящий, он обязан быть видим не только в деньгах,
    но и в СОСТАВЕ: доля выходов по стопу, стороны, вклад одного
    имени. Одинаковый состав при разных деньгах — довод в пользу
    режима рынка, разный — в пользу того, что изменились мы.
    """
    st = peak_stats(days)
    if st is None:
        return {}
    cut = min(days) + st["peak_i"]
    out = {}
    for name, part in (("before", [t for t in trades if t["day"] <= cut]),
                       ("after", [t for t in trades if t["day"] > cut])):
        if not part:
            out[name] = {"n": 0}
            continue
        pnl = [t["pnl"] for t in part]
        by_sym = {}
        for t in part:
            by_sym[t["sym"]] = by_sym.get(t["sym"], 0.0) + t["pnl"]
        top_sym = max(by_sym, key=lambda s: abs(by_sym[s]))
        whys = {}
        for t in part:
            key = t.get("reason") or "—"
            if not isinstance(key, str):
                key = str(key)      # причина обязана быть ярлыком
            whys[key] = whys.get(key, 0) + 1
        out[name] = {
            "n": len(part), "pnl": round(sum(pnl), 2),
            "win": round(sum(1 for v in pnl if v > 0) / len(pnl), 3),
            "median_bp": round(sorted(
                t["net"] for t in part if t["net"] is not None)
                [len([t for t in part if t["net"] is not None]) // 2], 1)
            if any(t["net"] is not None for t in part) else None,
            "long_share": round(sum(1 for t in part
                                    if t["side"] == "long") / len(part), 3),
            "top_sym": top_sym, "top_sym_pnl": round(by_sym[top_sym], 2),
            "pnl_wo_top": round(sum(pnl) - by_sym[top_sym], 2),
            "why": dict(sorted(whys.items(), key=lambda kv: -kv[1])[:4])}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s8", default=os.path.join(
        os.path.dirname(HERE), "s8_loop", "out"))
    ap.add_argument("--perms", type=int, default=PERMS)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)      # урок турнира: до счёта

    books, per_book = {}, {}
    for key, name, echo in BOOKS:
        mdir = os.path.join(args.s8, name)
        trades, mman = book_trades(mdir)
        if not trades:
            per_book[key] = {"n": 0, "echo": echo}
            print(f"{key}: закрытых сделок нет", flush=True)
            continue
        days = daily(trades)
        books[key] = days
        per_book[key] = {
            "n": len(trades), "echo": echo,
            "first_day": min(days), "last_day": max(days),
            "peak": peak_stats(days),
            "perm": perm_test(days, perms=args.perms),
            "parts": split_by_peak(trades, days)}
        p = per_book[key]["perm"]
        print(f"{key}: сделок {len(trades)}, падение после пика "
              f"{per_book[key]['peak']['drop']:.2f} $, у перемешанных "
              f"{p.get('drop_null_med')} $, p={p.get('p_drop')}",
              flush=True)

    art = {"tag": args.tag, "perms": args.perms, "seed": SEED,
           "books": per_book, "sync": sync_stats(books),
           "took_sec": round(time.time() - t0, 1)}
    jp = os.path.join(out_dir, f"TURN-{args.tag}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    write_report(art, os.path.join(out_dir, f"TURN-report-{args.tag}.md"))
    print(f"готово за {art['took_sec']} с → {jp}", flush=True)
    if not args.no_publish:
        publish()
    return 0


def day_str(d):
    return datetime.fromtimestamp(d * DAY, timezone.utc).strftime("%m-%d")


def write_report(art, path):
    s = art["sync"]
    L = ["# Зонд перелома: общий ли у книг «сначала плюс, потом слив»",
         "",
         "Вопрос владельца: все книги сначала зарабатывают, а потом "
         "начинают сливать — что происходит на рынке. Прежде чем искать "
         "причину, проверяется, есть ли перелом вообще: кумулятивная "
         "кривая после своего максимума идёт вниз ПО ОПРЕДЕЛЕНИЮ, и "
         "«момент» находится даже в чистом шуме. Нуль — те же дни в "
         f"случайном порядке ({art['perms']} перестановок, зерно "
         f"{art['seed']} числом). Меняется только ПОРЯДОК дней, значит "
         "разница принадлежит времени, а не величине дневных денег.",
         "",
         "## Перелом по книгам", "",
         "| книга | сделок | дней | пик $ | итог $ | падение после пика |"
         " у перемешанных | p | доля дней до пика | у перемешанных |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for key, b in sorted(art["books"].items()):
        if not b.get("n"):
            L.append(f"| {key} | 0 | — | — | — | — | — | — | — | — |")
            continue
        pk, pm = b["peak"], b["perm"]
        L.append(
            f"| {key}{' (эхо)' if b.get('echo') else ''} | {b['n']} | "
            f"{pk['days']} | {pk['peak']:+.2f} | {pk['end']:+.2f} | "
            f"{pk['drop']:.2f} | {pm.get('drop_null_med', '—')} | "
            f"{pm.get('p_drop', '—')} | {pk['share_before']:.2f} | "
            f"{pm.get('share_null_med', '—')} |")
    L += ["",
          "`p` — доля перестановок, где падение после пика не меньше "
          "наблюдаемого. Крупное `p` означает, что перелом такой же "
          "величины даёт простая перетасовка тех же дней, то есть "
          "«момента» нет — есть распределение.",
          "",
          "## Синхронность книг", ""]
    if s.get("all_down") is not None:
        L += [f"Общих дней {s['common_days']}, книг {s['books']}, пар "
              f"{s.get('pairs')}.", "",
              f"- дней, когда в минусе ВСЕ книги разом: "
              f"**{s['all_down']:.3f}** против {s['all_down_null']:.3f} "
              f"у перемешанных (p={s['p_all_down']})",
              f"- дней, когда в плюсе все разом: {s['all_up']:.3f} "
              f"против {s['all_up_null']:.3f}",
              f"- попарная связь дневных денег: медиана "
              f"{s.get('corr_med')}, от {s.get('corr_min')} до "
              f"{s.get('corr_max')}"]
    else:
        L.append(f"Синхронность не измерена: {s.get('why', '—')} "
                 f"(книг с историей {s.get('books', 0)}, общих дней "
                 f"{s.get('common_days', 0)}). Это НЕ значит, что "
                 f"синхронности нет: мера просто не построена.")
    if s.get("skipped"):
        L.append("")
        L.append(f"Молодые книги вне меры: {', '.join(s['skipped'])} "
                 f"(история короче {MIN_DAYS} дней).")
    L += ["", "## Что изменилось в сделках до и после пика", "",
          "| книга | часть | сделок | $ | побед | медиана б.п. | "
          "доля лонгов | лучшее имя | $ без него | выходы |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for key, b in sorted(art["books"].items()):
        for part in ("before", "after"):
            p = (b.get("parts") or {}).get(part) or {}
            if not p.get("n"):
                continue
            med = p.get("median_bp")
            med_s = "—" if med is None else f"{med:+.1f}"
            L.append(
                f"| {key} | {'до' if part == 'before' else 'после'} | "
                f"{p['n']} | {p['pnl']:+.2f} | {p['win']:.2f} | "
                f"{med_s} | "
                f"{p['long_share']:.2f} | {p['top_sym']} "
                f"({p['top_sym_pnl']:+.2f}) | {p['pnl_wo_top']:+.2f} | "
                f"{p['why']} |")
    L += ["", f"Прогон {art['took_sec']} с."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def publish():
    sh = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                      "tools", "publish.sh")
    try:
        subprocess.run(["bash", sh], check=False, timeout=300)
    except Exception as e:                                # noqa: BLE001
        print(f"публикация не прошла: {e}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
