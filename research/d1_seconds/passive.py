#!/usr/bin/env python3
"""
D1 — исполнимость пассивного входа в первые секунды после падения.

Что решается
------------

Полный D1 дал превышение +26.2 б.п. при тейкерском круге 17.4 — нетто
+8.8 против требуемых спекой 34.8. Нули и лесенка величину поднять не
могут: первое проверяет случайность, второе добавляет расход. Значит
вердикт предрешён, **если не меняется структура издержек**, а меняет её
единственное — пассивный вход.

Потолок пассивного входа проходит (при круге 4 б.п. нетто было бы
+22.2 при пороге 8), поэтому замер оправдан: в R5 такой же потолок
направление закрывал и экономил недели, здесь он этого не делает.

Почему это ЗАМЕР, а не допущение
--------------------------------

Правило проекта: не считать лимитную заявку исполненной оттого, что
цену коснулись — это была ошибка движка v1. Здесь оно не нарушается, а
проверяется: в записи лежит вся лесенка и все сделки с агрессором,
значит очередь моделируется по факту.

**Заявка исполняется, когда сквозь её уровень прошло больше продающей
агрессии, чем стояло в очереди впереди неё.** Очередь берётся размером
уровня из снимка книги в момент постановки; отмены заявок нам не видны,
и мы их не учитываем — это работает ПРОТИВ нас, потому что отменённая
очередь исполнила бы нас раньше.

Отсюда же берётся неблагоприятный отбор, ради которого всё и считается:
пассивная покупка исполняется ровно тогда, когда продавцы продолжают
давить, то есть на худшей половине событий. Он не назначается
коэффициентом, а выпадает из данных сам.

Три руки, объявлены до прогона
------------------------------

- **тейкер** — покупка по аску, продажа по биду, комиссия 5.5 + 5.5;
- **мейкер на лучшем биде** — очередь впереди равна размеру уровня;
- **мейкер на середине** — заявка улучшает бид, очереди впереди нет.

У обеих мейкерских рук выход тейкерский, по биду: предполагать
пассивный выход значило бы дважды считать то, что и проверяем.

    .venv/bin/python research/d1_seconds/passive.py --jobs 2
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import detect as D                                        # noqa: E402
import run_d1 as R                                        # noqa: E402
from store import read_hour                               # noqa: E402

# --- объявлено до прогона ---------------------------------------------
SIZE_USD = 5000.0         # размер ноги, спека 11 §6
WAIT_SEC = 60             # сколько заявка стоит, прежде чем снята
MAKER_BP = 2.0            # ставка мейкера Bybit, крипто-универсум
TAKER_BP = 5.5            # ставка тейкера, модальная по A1
ARMS = ("тейкер", "мейкер на биде", "мейкер на середине")


def book_line(line):
    """Время, бид, аск и размеры лучших уровней обеих сторон.

    `ask_sz` добавлен для зонда пассивного входа в спокойном рынке:
    продажа лимиткой стоит в очереди НА АСКЕ, и без размера этого
    уровня сторону продажи мерить нечем. Поле пишется сборщиком с
    первого дня (`book.py`: `"ask_sz": self.asks[ask]`).
    """
    def num(key, start=0):
        i = line.find(key, start)
        if i < 0:
            raise ValueError(f"нет {key}")
        i += len(key)
        j = i
        while j < len(line) and line[j] not in ",}":
            j += 1
        return float(line[i:j]), j
    bid, p = num('"bid":')
    ask, p = num('"ask":', p)
    sz, p = num('"bid_sz":', p)
    asz, _ = num('"ask_sz":', p)
    i = line.rfind(',"t":')
    if i < 0:
        raise ValueError("нет метки времени")
    i += 5
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    return float(line[i:j]), bid, ask, sz, asz


def trade_line(line):
    """Время (с), цена, объём, сторона агрессора (+1 покупка, −1 продажа)."""
    def num(key):
        i = line.find(key)
        if i < 0:
            raise ValueError(f"нет {key}")
        i += len(key)
        j = i
        while j < len(line) and line[j] not in ",}":
            j += 1
        return float(line[i:j])
    return (num('"ts":') / 1000.0, num('"p":'), num('"v":'),
            num('"side":'))


def book_grids(root, sym, hours, t0, n):
    """Бид, аск и размеры лучших уровней на секундной сетке."""
    ts, bid, ask, sz, asz = [], [], [], [], []
    d = os.path.join(root, "book", sym)
    for h in hours:
        for t, b, a, q, qa in read_hour(d, h, parse=book_line):
            if b <= 0 or a <= 0:
                continue
            ts.append(t)
            bid.append(b)
            ask.append(a)
            sz.append(q)
            asz.append(qa)
    return (D.place(ts, bid, t0, n).astype(np.float32),
            D.place(ts, ask, t0, n).astype(np.float32),
            D.place(ts, sz, t0, n).astype(np.float32),
            D.place(ts, asz, t0, n).astype(np.float32))


def trade_arrays(root, sym, hours, t0):
    """Сделки отрезка: время, цена, объём, сторона. Отсортированы."""
    ts, px, vol, side = [], [], [], []
    d = os.path.join(root, "trades", sym)
    for h in hours:
        for t, p, v, s in read_hour(d, h, parse=trade_line):
            ts.append(t - t0)
            px.append(p)
            vol.append(v)
            side.append(s)
    if not ts:
        return (np.empty(0), np.empty(0), np.empty(0), np.empty(0))
    o = np.argsort(np.asarray(ts), kind="stable")
    return (np.asarray(ts)[o], np.asarray(px)[o], np.asarray(vol)[o],
            np.asarray(side)[o])


def fill_at(tt, tp, tv, tside, t_place, limit, queue, size,
            wait=WAIT_SEC, side=1):
    """Когда исполнится пассивная заявка по цене `limit`.

    `side=+1` — покупка: её исполняет ПРОДАЮЩАЯ агрессия по цене не
    выше нашей. `side=-1` — продажа, зеркально: покупающая агрессия по
    цене не ниже. Умолчание — прежняя покупка, счёт D1 бит в бит.

    Очередь впереди — `queue` в единицах базового актива. Исполнение
    наступает, когда накопленная встречная агрессия сквозь наш уровень
    превысит очередь плюс наш размер: пока сквозь уровень не прошло
    чужого объёма больше, чем стояло перед нами, наша заявка не
    тронута.

    Возвращает секунду исполнения от `t_place` либо `None`.
    """
    if len(tt) == 0:
        return None
    lo = int(np.searchsorted(tt, t_place, side="right"))
    hi = int(np.searchsorted(tt, t_place + wait, side="right"))
    if hi <= lo:
        return None
    if side > 0:
        m = (tside[lo:hi] < 0) & (tp[lo:hi] <= limit)
    else:
        m = (tside[lo:hi] > 0) & (tp[lo:hi] >= limit)
    if not m.any():
        return None
    need = queue + size
    cum = np.cumsum(tv[lo:hi][m])
    k = int(np.searchsorted(cum, need, side="left"))
    if k >= len(cum):
        return None
    return float(tt[lo:hi][m][k] - t_place)


def measure_day(root, syms, day, jobs, log=print):
    """События суток с исходом по каждой руке."""
    P, t0, n = R.load_day(os.path.join(root, "book"), syms, day, jobs, log)
    NXT = R.next_index(P)
    drop = D.VERDICT_CELL["drop"]
    delay = D.VERDICT_CELL["delay_sec"]
    hor = D.VERDICT_CELL["horizon_sec"]
    rows, cols = R.events_of_day(P, t0, drop, {}, R.PAD_SEC,
                                 R.PAD_SEC + R.DAY_SEC)
    log(f"    событий {len(rows)}")
    if len(rows) == 0:
        return []
    ban = D.guard_matrix(P.shape, rows, cols, D.guard_sec(delay, hor))
    hours = R.hours_of(t0, n)
    by_sym = {}
    for r, j in zip(rows, cols):
        by_sym.setdefault(int(r), []).append(int(j))
    out = []
    for k, (r, js) in enumerate(sorted(by_sym.items())):
        sym = syms[r]
        bid, ask, bsz, _ = book_grids(root, sym, hours, t0, n)
        _, bnxt = D.fill_index(bid)
        tt, tp, tv, tside = trade_arrays(root, sym, hours, t0)
        for j in js:
            _, bg, exc, width = D.excess(P, NXT, r, j, delay, hor,
                                         ban[:, j])
            i_in = int(D.first_at_or_after(
                bnxt, np.array([j + delay]), D.FILL_WAIT_SEC)[0])
            i_out = int(D.first_at_or_after(
                bnxt, np.array([j + delay + hor]), D.FILL_WAIT_SEC)[0])
            if i_in < 0 or i_out < 0 or not np.isfinite(bg):
                continue
            b, a, q = float(bid[i_in]), float(ask[i_in]), float(bsz[i_in])
            mid = (b + a) / 2.0
            out_bid = float(bid[i_out])
            if not (b > 0 and a > 0 and out_bid > 0):
                continue
            rec = {"sym": sym, "t": t0 + j, "bg": bg, "excess_mid": exc,
                   "width": width, "spread_bp": (a - b) / mid * 1e4}
            # тейкер: купили по аску, продали по биду
            rec["тейкер"] = {
                "filled": True, "wait_sec": 0.0,
                "ret": out_bid / a - 1.0,
                "fee_bp": 2 * TAKER_BP}
            for arm, limit, queue in (("мейкер на биде", b, q),
                                      ("мейкер на середине", mid, 0.0)):
                w = fill_at(tt, tp, tv, tside, float(j + delay), limit,
                            queue, SIZE_USD / limit)
                rec[arm] = {
                    "filled": w is not None,
                    "wait_sec": w,
                    "ret": (out_bid / limit - 1.0) if w is not None
                    else None,
                    "fee_bp": MAKER_BP + TAKER_BP}
            out.append(rec)
        if (k + 1) % 25 == 0:
            log(f"    посчитано {k + 1}/{len(by_sym)} имён")
    del P, NXT, ban
    return out


def summarise(rows):
    """По каждой руке: доля исполнения, превышение нетто, эпизоды."""
    res = {}
    for arm in ARMS:
        got = [e for e in rows if e[arm]["filled"]]
        rec = {"events": len(rows), "filled": len(got),
               "fill_rate": round(len(got) / len(rows), 3) if rows else None}
        if not got:
            res[arm] = dict(rec, excess_net_bp=None, episodes=0,
                            share_pos=None, wait_median=None,
                            excess_mid_bp=None)
            continue
        net = np.array([(e[arm]["ret"] - e["bg"]) * 1e4 - e[arm]["fee_bp"]
                        for e in got], dtype=np.float64)
        t = np.array([e["t"] for e in got], dtype=np.float64)
        ep = D.episodes(t)
        v = D.by_episode(net, ep)
        w = [e[arm]["wait_sec"] for e in got if e[arm]["wait_sec"] is not None]
        rec.update({
            "excess_net_bp": round(float(np.median(v)), 2),
            "episodes": int(len(v)),
            "share_pos": round(float(np.mean(v > 0)), 3),
            "wait_median": round(float(np.median(w)), 1) if w else None,
            # То же превышение по СЕРЕДИНЕ на исполненном подмножестве:
            # разница с полной выборкой и есть неблагоприятный отбор.
            "excess_mid_bp": round(float(np.median(D.by_episode(
                np.array([e["excess_mid"] * 1e4 for e in got]), ep))), 2),
        })
        res[arm] = rec
    all_mid = np.array([e["excess_mid"] * 1e4 for e in rows])
    ep_all = D.episodes(np.array([e["t"] for e in rows], dtype=np.float64))
    res["_all_mid_bp"] = round(float(np.median(
        D.by_episode(all_mid, ep_all))), 2)
    return res


def report(art, path):
    a = art
    L = ["# D1 — исполнимость пассивного входа\n",
         f"Прогон: {a['run_at']}. Спека 11, к этапу D3.\n",
         "Тейкерский круг съедает две трети превышения, и вердикт по "
         "объявленному порогу без пассивного входа предрешён. Здесь "
         "проверяется, **исполняется ли лимитная заявка** в первые "
         "секунды после падения — по факту прошедшего сквозь неё "
         "объёма, а не по касанию цены.\n",
         f"- суток: **{a['days']}**, событий: **{a['events']}**",
         f"- размер ноги ${SIZE_USD:.0f}, заявка стоит {WAIT_SEC} с, "
         f"ставки: мейкер {MAKER_BP}, тейкер {TAKER_BP} б.п.",
         f"- превышение по середине на ВСЕЙ выборке: "
         f"**{a['summary']['_all_mid_bp']:+.1f} б.п.**\n",
         "## 1. Руки\n",
         "| рука | исполнено | доля | ждали, с | превышение нетто | "
         "доля > 0 | эпизодов |",
         "|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        r = a["summary"][arm]
        d = lambda v, f: "—" if v is None else format(v, f)
        L.append(f"| {arm} | {r['filled']} | {d(r['fill_rate'], '.3f')} | "
                 f"{d(r['wait_median'], '.1f')} | "
                 f"{d(r['excess_net_bp'], '+.1f')} б.п. | "
                 f"{d(r['share_pos'], '.3f')} | {r['episodes']} |")
    L.append("")
    L.append("## 2. Неблагоприятный отбор\n")
    L.append("Пассивная покупка исполняется тогда, когда продавцы "
             "продолжают давить, — то есть на худшей половине событий. "
             "Мера прямая: превышение по середине на исполненном "
             "подмножестве против всей выборки. Издержек в этих числах "
             "нет, сравниваются одни и те же величины.\n")
    L.append("| рука | превышение на исполненных | на всей выборке | "
             "цена отбора |")
    L.append("|---|---|---|---|")
    base = a["summary"]["_all_mid_bp"]
    for arm in ARMS[1:]:
        r = a["summary"][arm]
        if r["excess_mid_bp"] is None:
            L.append(f"| {arm} | — | {base:+.1f} | — |")
            continue
        L.append(f"| {arm} | {r['excess_mid_bp']:+.1f} б.п. | "
                 f"{base:+.1f} б.п. | "
                 f"{r['excess_mid_bp'] - base:+.1f} б.п. |")
    L.append("")
    L.append("## 3. Вердикт §7 п.4\n")
    L.append("Требуется нетто не меньше двойного круга издержек.\n")
    L.append("| рука | круг | нетто | нужно | |")
    L.append("|---|---|---|---|---|")
    for arm in ARMS:
        r = a["summary"][arm]
        if r["excess_net_bp"] is None:
            L.append(f"| {arm} | — | — | — | не измерено |")
            continue
        ring = (2 * TAKER_BP if arm == "тейкер" else MAKER_BP + TAKER_BP)
        need = 2 * ring
        ok = r["excess_net_bp"] >= need
        L.append(f"| {arm} | {ring:.1f} б.п. | {r['excess_net_bp']:+.1f} | "
                 f"{need:.1f} | **{'выполнен' if ok else 'НЕ выполнен'}** |")
    L.append("")
    L.append("## 4. Оговорки, не снимаемые этим замером\n")
    L.append("- отмены заявок в записи не видны, очередь берётся "
             "размером уровня в момент постановки. Это работает ПРОТИВ "
             "нас: отменённая очередь исполнила бы раньше;")
    L.append("- своя заявка на рынок не влияет. При $5 000 на ногу "
             "допущение мягкое, но оно есть;")
    L.append("- выход тейкерский по биду у всех рук. Пассивный выход "
             "дал бы лучше, но его пришлось бы мерить так же, а не "
             "предполагать;")
    L.append("- очередь на уровне могла обновиться между секундными "
             "снимками; исполнение считается по сделкам, снимок даёт "
             "только размер очереди.")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"
    os.makedirs(a.out, exist_ok=True)

    syms, hours = R.available(os.path.join(a.root, "book"))
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    print(f"символов {len(syms)}, суток {len(days)}")
    rows, t_start = [], time.time()
    for day in days:
        print(f"  {day}: читаю")
        got = measure_day(a.root, syms, day, a.jobs)
        rows += got
        print(f"  {day}: событий {len(got)}, всего {len(rows)}, "
              f"{(time.time() - t_start) / 60:.1f} мин")
    if not rows:
        raise SystemExit("событий нет")
    art = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "days": len(days), "events": len(rows),
        "size_usd": SIZE_USD, "wait_sec": WAIT_SEC,
        "maker_bp": MAKER_BP, "taker_bp": TAKER_BP,
        "summary": summarise(rows),
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    p = os.path.join(a.out, f"D1-passive-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"D1-passive-{a.tag}.md"))
    print(f"готово: {p}")
    for arm in ARMS:
        r = art["summary"][arm]
        print(f"  {arm}: исполнено {r['fill_rate']}, нетто "
              f"{r['excess_net_bp']} б.п.")
    if not a.no_publish:
        R.publish(f"D1: исполнимость пассивного входа ({a.tag})")


if __name__ == "__main__":
    main()
