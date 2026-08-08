#!/usr/bin/env python3
"""
Где ставить стоп: замер пробоя обещанной линии и возврата за ней.

Замечание владельца, и оно верное по существу: сейчас стоп стоит
РОВНО на `mae` — на том уровне, куда модель сама предсказывает ход
против позиции. То есть заявка ставится туда, куда цена, по нашему же
прогнозу, придёт. Стоп обязан стоять ЗА этой линией, а насколько
за — не выдумывается, а меряется.

Что считается
-------------

По каждой ноге (цена входа, сторона, обещания `mae`/`mfe`) проходим
минутные бары до предела возраста и берём три величины:

1. **Касание.** Дошла ли цена до линии `mae` вообще. Доля касаний —
   это и есть цена нынешнего правила: столько сделок оно закрывает.
2. **Пробой.** Насколько дальше линии ушла цена, в базисных пунктах
   и в долях самого `|mae|` (безразмерно — у имён разный масштаб, и
   складывать б.п. BTC с б.п. мелкого альта нельзя).
3. **Возврат.** Вернулась ли цена за линию и дошла ли ПОСЛЕ этого до
   цели `mfe` в пределах возраста. Вот это и есть сделки, которые
   нынешний стоп убивает зря, а буфер спасает.

Отсюда буфер: распределение пробоя У ВЕРНУВШИХСЯ. Если вернувшиеся
пробивали линию на 0.2 её длины, буфер в 0.2 спасает половину из них,
в 0.5 — почти всех. Плата за буфер тоже считается: те, кто не
вернулся, теряют ровно на величину буфера больше.

Чего замер НЕ делает
--------------------

Не выбирает буфер за владельца и не объявляет правило. Он даёт
распределение и цену, а решение — какой процент вернувшихся спасать —
торговое. И не переобучает модель: `mae` берётся тот, что записан в
выборе, то есть оценка оптимистична ровно так же, как в переборе.

    python3 research/s9_sweep/stops.py --http http://адрес --key ключ
"""

import argparse
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep as S                                            # noqa: E402

# Буферы, по которым считается цена решения. Объявлены здесь и до
# прогона: доли от |mae|, потому что сама линия у каждого имени своя.
BUFFERS = [0.0, 0.1, 0.25, 0.5, 1.0]


def walk(bars, entry_ts, entry_px, side, adv, fav, max_h=S.MAX_AGE_H):
    """Путь ноги относительно обещанных линий.

    Возвращает `None`, если баров нет (пропуск, а не нулевой исход).
    Иначе — словарь: было ли касание линии против, максимальный пробой
    за неё (в б.п. и в долях `|adv|`), и дошла ли цена до цели ПОСЛЕ
    касания.
    """
    if not entry_px or entry_px <= 0 or adv is None or fav is None:
        return None
    seen = [b for b in bars
            if entry_ts <= b[0] <= entry_ts + max_h * 3600]
    if not seen:
        return None
    lvl_adv = entry_px * (1 + adv / 1e4)
    lvl_fav = entry_px * (1 + fav / 1e4)
    long_ = side == "long"
    touched, over, hit_after = False, 0.0, False
    for b in seen:
        low, high = b[3], b[2]
        if long_:
            if low <= lvl_adv:
                touched = True
                # Пробой считается по САМОЙ дальней точке за линией.
                over = max(over, (lvl_adv - low) / entry_px * 1e4)
            if touched and high >= lvl_fav:
                hit_after = True
                break
        else:
            if high >= lvl_adv:
                touched = True
                over = max(over, (high - lvl_adv) / entry_px * 1e4)
            if touched and low <= lvl_fav:
                hit_after = True
                break
    return {"touched": touched, "over_bp": round(over, 1),
            "over_x": round(over / abs(adv), 3) if adv else None,
            "recovered": hit_after}


def measure_buffer(legs, buf):
    """Что даёт буфер `buf` (в долях `|mae|`) на этой выборке.

    Считается ровно тем же ядром сделки, что перебор: стоп отодвинут,
    цель на месте. Иначе сравнивать было бы не с чем — две реализации
    бракета разошлись бы, и разницу приписали бы буферу.
    """
    nets, out = [], {"стоп": 0, "цель": 0, "срок": 0}
    for g in legs:
        adv = g["mae"] * (1.0 + buf)
        got = S.bracket(g.get("bars") or [], g["at"], g["px"],
                        g["side"], adv, g["mfe"])
        if got is None:
            continue
        why, move, _ = got
        n, _ = S.net_bp(g["side"], move, adv)
        nets.append(n)
        out[why] += 1
    if not nets:
        return {"n": 0}
    return {"n": len(nets),
            "exp_bp": round(sum(nets) / len(nets), 1),
            "med_bp": round(st.median(nets), 1),
            "win": round(sum(1 for v in nets if v > 0) / len(nets), 3),
            "stop": out["стоп"], "target": out["цель"],
            "time": out["срок"]}


def run(legs):
    rows = []
    for g in legs:
        w = walk(g.get("bars") or [], g["at"], g["px"], g["side"],
                 g["mae"], g["mfe"])
        if w:
            rows.append({**w, "sym": g["sym"], "side": g["side"]})
    return rows


def report(rows, legs, path):
    touched = [r for r in rows if r["touched"]]
    rec = [r for r in touched if r["recovered"]]
    dead = [r for r in touched if not r["recovered"]]
    q = lambda v, p: (round(sorted(v)[min(len(v) - 1,          # noqa: E731
                                          int(p * len(v)))], 3)
                      if v else None)
    over_rec = [r["over_x"] for r in rec if r["over_x"] is not None]
    over_dead = [r["over_x"] for r in dead if r["over_x"] is not None]
    lines = [
        "# Где ставить стоп: пробой обещанной линии и возврат", "",
        "Сейчас стоп стоит РОВНО на `mae` — там, куда модель сама "
        "предсказывает ход против позиции. Замечание владельца: заявка "
        "стоит там, куда цена по нашему же прогнозу придёт. Здесь "
        "меряется, сколько это стоит и насколько линию надо отодвинуть.",
        "",
        f"- ног с барами: **{len(rows)}** из {len(legs)}",
        f"- касаются линии `mae`: **{len(touched)}** "
        f"({len(touched) / len(rows) * 100:.0f} % — столько сделок "
        f"нынешнее правило закрывает)" if rows else "",
        f"- из них ВОЗВРАЩАЮТСЯ и доходят до цели: **{len(rec)}** "
        f"({len(rec) / len(touched) * 100:.0f} % касаний) — это "
        f"сделки, которые стоп убивает зря" if touched else "",
        "",
        "## Насколько пробивают линию (в долях её длины)", "",
        "| кто | сделок | медиана | 75-й | 90-й | максимум |",
        "|---|---|---|---|---|---|",
        f"| вернувшиеся к цели | {len(over_rec)} | "
        f"{q(over_rec, 0.5)} | {q(over_rec, 0.75)} | "
        f"{q(over_rec, 0.9)} | {max(over_rec) if over_rec else None} |",
        f"| не вернувшиеся | {len(over_dead)} | {q(over_dead, 0.5)} | "
        f"{q(over_dead, 0.75)} | {q(over_dead, 0.9)} | "
        f"{max(over_dead) if over_dead else None} |",
        "",
        "Буфер в долях `|mae|` спасает вернувшегося, если он больше "
        "его пробоя. Столбец «75-й» у вернувшихся — это буфер, "
        "спасающий три четверти из них.",
        "",
        "## Цена решения: тот же бракет со сдвинутым стопом", "",
        "| буфер | сделок | побед | ожидание, б.п. | медиана | "
        "стоп/цель/срок |",
        "|---|---|---|---|---|---|",
    ]
    for buf in BUFFERS:
        m = measure_buffer(legs, buf)
        if not m.get("n"):
            lines.append(f"| ×{1 + buf:.2f} | 0 | — | — | — | — |")
            continue
        lines.append(
            f"| ×{1 + buf:.2f} | {m['n']} | {m['win']} | "
            f"{m['exp_bp']:+} | {m['med_bp']:+} | "
            f"{m['stop']}/{m['target']}/{m['time']} |")
    lines += [
        "",
        "Буфер увеличивает риск ноги ровно на свою величину: у "
        "невернувшихся убыток растёт, у вернувшихся сделка доживает до "
        "цели. Замер показывает баланс этих двух, а решение — какую "
        "долю вернувшихся спасать — торговое.",
        "",
        "Оценка ОПТИМИСТИЧНА теми же двумя способами, что перебор: "
        "веса видели эти часы в обучении, и рассматриваются только "
        "имена, которые отбор уже выбрал.",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(x for x in lines if x is not None) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(HERE), "b1_book", "out"))
    ap.add_argument("--books", nargs="+", default=[
        os.path.join(os.path.dirname(HERE), "s8_loop", "out", "model"),
        os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                     "model_sit")])
    ap.add_argument("--http", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.out:
        a.out = os.path.join(HERE, "out", "S9-stops%s.md"
                             % ("-remote" if a.http else ""))
    src = legs = None
    if a.http:
        src = S.HttpBars(a.http, a.key, disk=a.cache or None)
        legs = S.legs_from_http(a.http, a.key, a.books)
    # Бары тянет тот же код, что перебор: вторая загрузка однажды
    # разошлась бы с первой окном или правилом пропуска.
    legs, _cells = S.run(a.root, a.books, src=src, legs=legs)
    rows = run(legs)
    with open(a.out.replace(".md", "-rows.json"), "w",
              encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print("отчёт:", report(rows, legs, a.out))


if __name__ == "__main__":
    main()
