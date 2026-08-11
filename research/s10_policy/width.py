#!/usr/bin/env python3
"""
Профиль ожидания по МЕСТУ в сечении: сколько ног стоит открывать.

Вопрос владельца: открывать не три первых и три последних, а одну или
десять — и не должен ли выбор ширины делать сам турнир.

Почему это замер, а не новая ось турнира
---------------------------------------

Ширина сейчас стоит в ЗАБОРЕ, а не в поиске (спека 10 §3): в обучающей
выборке нет ни одного слива, поэтому риск-параметры вынесены из
перебора целиком, а ширина — риск-параметр. Прежде чем двигать её в
поиск и умножать объявленные испытания втрое, дешевле спросить у уже
записанных данных: **зарабатывает ли первое место больше десятого.**

Три возможных ответа, и каждый решает сам:

- ожидание убывает с местом — узкая книга покупает эдж, и ширина есть
  настоящий размен «эдж против концентрации»;
- ожидание плоское — ширина эджа не меняет, меняет только разброс, и
  тогда шире строго лучше, а ось не нужна вовсе;
- ожидание рваное — ранжирование не несёт информации дальше самых
  краёв, и это находка о модели, а не о ширине.

Этот же профиль разрешает двусмысленность, которая уже есть: все деньги
книги сидят в трёх именах. Читать это можно двояко — «верхние места и
есть деньги» либо «одно везучее имя вытянуло независимо от места», — и
различает эти два случая только профиль.

Что считается
-------------

Голое удержание: ни стопа, ни цели, срок — горизонт книги. Правила
выхода здесь намеренно ни при чём, они предмет турнира; спрашивается
только, различает ли МЕСТО в сечении будущий ход. Исход берётся тем же
`outcome`, что у турнира (вход по открытию первого бара после решения,
касание двух уровней против нас), издержки — тот же круг на ногу.

Оговорки те же, что у турнира, и не снимаются: веса видели эти часы,
значит оценка оптимистична; скидка и взведение сканера не реплеятся.

    .venv/bin/python research/s10_policy/width.py
"""

import argparse
import json
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "s9_sweep"))
sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))

import sweep as SW                                        # noqa: E402
import tournament as T                                    # noqa: E402
import trades as TR                                       # noqa: E402

# Объявлено здесь: голое удержание на горизонте книги, места и ширины,
# по которым печатается профиль. Это не сетка выбора — вердикта у
# замера нет, он отвечает на «различает ли место» и ничего не выбирает.
AGE_H = 4
RANKS = (1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30)
WIDTHS = (1, 2, 3, 5, 10, 20)


def rank_legs(legs):
    """Место ноги в своём сечении: 1 — самый крайний прогноз стороны.

    Считается ВНУТРИ часа, руки и стороны: сравнивать место лонга с
    местом шорта нельзя, у них разные концы сечения. Ключ часа берётся
    из самой записи, а не из времени входа — час и есть сечение.
    """
    groups = {}
    for lg in legs:
        groups.setdefault((lg["hour"], lg["arm"], lg["side"]), []).append(lg)
    for key, rows in groups.items():
        rows.sort(key=lambda g: -abs(g["fwd"]))
        for i, lg in enumerate(rows):
            lg["rank"] = i + 1
            lg["of"] = len(rows)
    return groups


def measure(sheets, root, src=None, log=print):
    legs = T.legs_from_sheets(sheets, log=log)
    if not legs:
        raise SystemExit("листов сечения нет — нечего считать")
    groups = rank_legs(legs)
    log(f"сечений {len(groups)}, ног {len(legs)}")
    # Бары нужны только тем, кто попадает в рассматриваемые места:
    # сечение в пятьсот имён, а спрашиваем мы про первые тридцать.
    need = [g for g in legs if g["rank"] <= max(RANKS)]
    log(f"под замер попадает {len(need)} ног")
    said = time.time()
    out = []
    for i, lg in enumerate(need):
        if time.time() - said > 30:
            log(f"  бары: {i}/{len(need)}")
            said = time.time()
        get = src.bars if src else (
            lambda sym, a, b: SW.read_bars(root, sym, a, b))
        bars = get(lg["sym"], lg["at"], lg["at"] + AGE_H * 3600)
        # Голое удержание: стопа и цели нет вовсе.
        got = T.outcome(bars, lg["at"], lg["side"], None, None, AGE_H)
        if got is None:
            continue
        why, move, exit_ts, _ = got
        # Знак стороны и круг издержек — ровно как в `simulate`
        # турнира. Вторая формула нетто разошлась бы с первой, и
        # профиль описывал бы другие деньги, чем таблица вариантов.
        net = (1 if lg["side"] == "long" else -1) * move - TR.ROUND_COST_BP
        out.append(dict(lg, net=net, move=move, why=why, exit=exit_ts))
    log(f"посчитано {len(out)} ног")
    return out


def by_rank(rows):
    """Ожидание по каждому месту отдельно."""
    res = []
    for r in RANKS:
        sub = [x["net"] for x in rows if x["rank"] == r]
        if not sub:
            res.append({"rank": r, "n": 0})
            continue
        res.append({"rank": r, "n": len(sub),
                    "exp_bp": round(sum(sub) / len(sub), 1),
                    "med_bp": round(st.median(sub), 1),
                    "win": round(sum(1 for v in sub if v > 0) / len(sub), 3)})
    return res


def by_width(rows):
    """Ожидание книги, берущей места 1..N, и её концентрация.

    Концентрация считается по ИМЕНИ, а не по сделке: весь опыт проекта
    говорит, что итог делают одно-три имени, и без этой колонки узкая
    книга выглядела бы прибыльной ровно до дня, когда везучего имени
    не случится.
    """
    res = []
    for w in WIDTHS:
        sub = [x for x in rows if x["rank"] <= w]
        if not sub:
            res.append({"width": w, "n": 0})
            continue
        nets = [x["net"] for x in sub]
        total = sum(nets)
        by_sym = {}
        for x in sub:
            by_sym[x["sym"]] = by_sym.get(x["sym"], 0.0) + x["net"]
        top_sym, top_pnl = max(by_sym.items(), key=lambda kv: kv[1])
        res.append({
            "width": w, "n": len(nets),
            "exp_bp": round(total / len(nets), 1),
            "med_bp": round(st.median(nets), 1),
            "win": round(sum(1 for v in nets if v > 0) / len(nets), 3),
            "total_bp": round(total, 1),
            "syms": len(by_sym),
            "top_sym": top_sym, "top_bp": round(top_pnl, 1),
            "total_wo_top_bp": round(total - top_pnl, 1),
        })
    return res


def step(ranks, edge=5):
    """Средние по верхним местам и по хвосту — ДОБАВЛЕНО после прогона.

    Первый прогон показал: ожидание не убывает ровно, а стоит
    СТУПЕНЬКОЙ — верхние места богаты, дальше ноль. Проверка на
    монотонность назвала это «рваным профилем», и по существу она права
    («информации дальше краёв нет»), но величину ступени не показывала
    вовсе.

    Это добавленное ИЗМЕРЕНИЕ, а не подкрученный вердикт: фраза вывода
    и её порог остались прежними. Правило проекта запрещает менять
    пороги после результата — добавлять числа, которых не хватало, оно
    не запрещает.
    """
    got = [r for r in ranks if r.get("n", 0) >= 30]
    top = [r["exp_bp"] for r in got if r["rank"] <= edge]
    tail = [r["exp_bp"] for r in got if r["rank"] > edge]
    return {"edge": edge,
            "top_mean_bp": round(sum(top) / len(top), 1) if top else None,
            "tail_mean_bp": round(sum(tail) / len(tail), 2) if tail else None}


def reading(ranks, widths):
    """Вывод пишется из чисел: убывает ли ожидание с местом."""
    got = [r for r in ranks if r.get("n", 0) >= 30]
    if len(got) < 3:
        return ("Мест с достаточным числом наблюдений меньше трёх — "
                "профиль не измерен, судить нечем.")
    first = got[0]["exp_bp"]
    last = got[-1]["exp_bp"]
    drops = sum(1 for a, b in zip(got, got[1:]) if b["exp_bp"] <= a["exp_bp"])
    mono = drops >= len(got) - 2
    if first > last and mono:
        return (f"Ожидание убывает с местом ({first:+.1f} на первом против "
                f"{last:+.1f} на {got[-1]['rank']}-м, {drops} убываний из "
                f"{len(got) - 1}). Место в сечении несёт информацию, и "
                f"ширина есть настоящий размен эджа против концентрации — "
                f"ось в турнире оправдана.")
    if abs(first - last) < 5:
        return (f"Профиль плоский ({first:+.1f} против {last:+.1f} б.п.): "
                f"место в сечении ожидания не меняет. Тогда узкая книга "
                f"эджа не покупает, а разброс поднимает — шире строго "
                f"лучше, и отдельная ось турниру не нужна.")
    return (f"Профиль рваный: {first:+.1f} на первом месте против "
            f"{last:+.1f} на {got[-1]['rank']}-м при {drops} убываниях из "
            f"{len(got) - 1}. Ранжирование не несёт информации дальше "
            f"краёв — это находка о модели, а не о ширине.")


def report(art, path):
    L = ["# Профиль ожидания по месту в сечении\n",
         f"Прогон: {art['run_at']}.\n",
         "Отвечает на вопрос владельца: открывать одну пару, три или "
         "десять. **Вердикта у замера нет** — он не выбирает ширину, а "
         "проверяет, различает ли место в сечении будущий ход. Удержание "
         f"голое: ни стопа, ни цели, срок {AGE_H} ч; правила выхода — "
         "предмет турнира и здесь ни при чём.\n",
         f"- ног в листах: **{art['legs']}**, посчитано: "
         f"**{art['measured']}**, сечений: **{art['sections']}**",
         f"- круг издержек {TR.ROUND_COST_BP} б.п. на ногу\n",
         "Оценка ОПТИМИСТИЧНА и это не снимается: веса видели эти часы.\n",
         "## 1. По месту\n",
         "| место | ног | ожидание | медиана | побед |",
         "|---|---|---|---|---|"]
    for r in art["ranks"]:
        if not r.get("n"):
            L.append(f"| {r['rank']} | 0 | — | — | — |")
            continue
        L.append(f"| {r['rank']} | {r['n']} | {r['exp_bp']:+.1f} б.п. | "
                 f"{r['med_bp']:+.1f} | {r['win']:.3f} |")
    st_ = art.get("step") or {}
    if st_.get("top_mean_bp") is not None:
        L.append("")
        L.append(f"Ступень: места 1–{st_['edge']} дают в среднем "
                 f"**{st_['top_mean_bp']:+.1f} б.п.** на ногу, места "
                 f"дальше — **{st_['tail_mean_bp']:+.2f}**. Информация "
                 f"живёт у краёв сечения и обрывается, а не сходит на "
                 f"нет плавно.")
    L.append("")
    L.append("## 2. По ширине книги (места 1..N)\n")
    L.append("| ширина | ног | имён | ожидание | медиана | побед | итог | "
             "лучшее имя | итог без него |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in art["widths"]:
        if not r.get("n"):
            L.append(f"| {r['width']} | 0 | — | — | — | — | — | — | — |")
            continue
        L.append(f"| {r['width']} | {r['n']} | {r['syms']} | "
                 f"{r['exp_bp']:+.1f} б.п. | {r['med_bp']:+.1f} | "
                 f"{r['win']:.3f} | {r['total_bp']:+.1f} | "
                 f"{r['top_sym']} {r['top_bp']:+.1f} | "
                 f"{r['total_wo_top_bp']:+.1f} |")
    L.append("")
    L.append("## 3. Что из этого следует\n")
    L.append(art["reading"])
    L.append("")
    L.append("## 4. Чего замер не отменяет\n")
    L.append(f"- **потолок на имя {TR.NAME_CAP_SHARE:.0%} капитала книги "
             f"никуда не делся.** При одной ноге на сторону имя запросило "
             f"бы половину книги, потолок связал бы сразу, и книга стояла "
             f"бы вложенной на {2 * TR.NAME_CAP_SHARE:.0%}. Узкая книга "
             f"несовместима с уже принятым забором, пока владелец не "
             f"решит иначе;")
    L.append("- ширина — риск-параметр, а в обучающей выборке нет ни "
             "одного слива, поэтому она и стоит в заборе, а не в поиске "
             "(спека 10 §3);")
    L.append("- добавление оси втрое умножает объявленные испытания "
             "(72 → 216). Селектор судится сам, статистику это не "
             "портит, но выбирать ему становится труднее на том же "
             "журнале.")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", nargs="+", default=[os.path.join(
        RESEARCH, "s8_loop", "out", "model_sit", "sheets.jsonl")])
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--http", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    if not a.out:
        name = "V1-width" + (f"-{a.tag}" if a.tag else "")
        a.out = os.path.join(HERE, "out", name + ".md")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    src = SW.HttpBars(a.http, a.key, disk=a.cache or None) if a.http else None
    rows = measure(a.sheets, a.root, src=src)
    if not rows:
        raise SystemExit("исходов нет — нечего считать")
    ranks, widths = by_rank(rows), by_width(rows)
    art = {
        "run_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "legs": len({r["id"] for r in rows}) if rows else 0,
        "measured": len(rows),
        "sections": len({(r["hour"], r["arm"], r["side"]) for r in rows}),
        "age_h": AGE_H, "ranks": ranks, "widths": widths,
        "step": step(ranks),
    }
    art["reading"] = reading(ranks, widths)
    json.dump(art, open(a.out.replace(".md", ".json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    report(art, a.out)
    print(f"готово: {a.out}")
    print(art["reading"])
    if not a.no_publish:
        # Публикация — ЧАСТЬ прогона, а не отдельный шаг. Урок записан
        # два шага назад и тут же нарушен: прогон случился, отчёт остался
        # на сервере, в git не приехало ничего. Шаг, который можно
        # забыть, забывают — в том числе я.
        sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
        import run_d1 as RD                                # noqa: E402
        RD.publish(f"V1: профиль ожидания по месту в сечении"
                   + (f" ({a.tag})" if a.tag else ""))


if __name__ == "__main__":
    main()
