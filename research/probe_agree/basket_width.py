#!/usr/bin/env python3
"""Вопрос владельца (2026-08-31): «а если корзину только из согласных,
но шире — по 12 ног?»

Повод прямой: первый замер согласия на корзине h24c нашёл, что
согласная корзина УЗКАЯ — 21 закрытие из 21 по возрасту, ни одного по
цели или пределу. Узкий гросс не достаёт порогов в долях капитала, и
правило корзины вырождается в «держим сутки и закрываем». Расширить
состав — законный ход, и он проверяем.

**Что означает «шире» механически.** Живая h24 берёт топ-3 в лонг и
топ-3 в шорт (`chosen = o[::-1][:3] + o[:3]` в train.py), то есть
6 ног в час; «по 12» — это 6+6. Записанные выборы несут только эти
шесть, поэтому состав шире строится из ПОЛНОГО вектора сечения:
`save_preds` кладёт в `preds.jsonl` весь ряд предсказаний часа, а не
выбранное. Правило отбора воспроизводится дословно — сортировка по
прогнозу, пол по МОДУЛЮ сырого прогноза, затем n/2 с каждого конца.

**Мост обязателен и стоит первым.** При N = 6 состав из `preds`
обязан совпасть с записанными выборами; доля совпадения печатается
числом, и ниже `BRIDGE_MIN` замер НЕ считается вовсе. Иначе я мерил
бы другую книгу, а таблица выглядела бы исправной (урок «сверка с
артефактом» из R3 и F2).

**Ось объявлена до прогона:** N ∈ {6, 12, 20, 30} ног в час
(3+3, 6+6, 10+10, 15+15). Правило корзины ОДНО и то же — живая h24c:
цель +5 %, предел −5 %, возраст 24 ч; сетки правил нет, перебор
порогов после вопроса был бы ошибкой R5.

**Нога масштабируется с шириной: `leg = CAPITAL / (N × 24)`.** Это не
удобство, а условие измеримости: при неизменной ноге 3000/144 корзина
шириной 12 просила бы вдвое больше капитала, касса связала бы её
потолком, и половина ног получила бы размер 0 — замер мерил бы
ГОЛОДАНИЕ кассы, а не ширину (первая серия корзины уже находила
1000–2300 таких сигналов). Правило одно на все три руки ширины.

Три руки на каждую ширину:
- `base` — весь топ-N (якорь того же прогона);
- `agreed` — только ноги, выбранные ОБЕИМИ головами в тот же час;
- `null` — случайное подмножество ТОЙ ЖЕ ширины, 10 зёрен числом.

Пересечение и нуль берутся из `basket_agree` (тот же код, что дал
первый ответ) — второй копии правила согласия не заводится.

Оговорки, объявленные до прогона и не снимаемые результатом:
- согласная корзина вложена на долю согласия, поэтому пороги в долях
  КАПИТАЛА в долях её гросса стоят дальше; нуль той же ширины несёт
  ровно то же искажение, и разность принадлежит согласию;
- расширение берёт ноги из более глубоких мест сечения. Профиль по
  месту уже измерен (`V1-width`: места 6–10 −2.0 б.п. на ногу, 11–20
  −15.4), но там ситуационный лист и горизонт 4 ч — перенос на
  24-часовую книгу не автоматический, потому ось и меряется;
- цена входа ног, которых нет в записанных выборах, берётся из
  середин сводок B1 на час решения — та же конвенция «вход по
  закрытию часа», что у книг со сроком; своей записи у них нет;
- `pred` в `preds.jsonl` округлён до четырёх знаков, а выбор делался
  по полной точности: на границе места состав может разойтись. Ровно
  это и меряет мост;
- запись ~месяц одного режима, внутри слив 08-24…27.

Запуск на VPS:
  cd ~/algoth_v2 && .venv/bin/python research/probe_agree/basket_width.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

for p in (HERE, os.path.join(RESEARCH, "probe_basket"),
          os.path.join(RESEARCH, "probe_turn")):
    if p not in sys.path:
        sys.path.insert(0, p)

import basket as BB                                       # noqa: E402
import basket_agree as BA                                 # noqa: E402
import turn as PT                                         # noqa: E402

WIDTHS = (6, 12, 20, 30)             # ног в час: 3+3, 6+6, 10+10, 15+15
CELL = BA.CELL                       # правило живой h24c, одно на все
SEEDS = BA.SEEDS                     # те же зёрна числом (урок R3)
HOLD_H = 24                          # горизонт книги h24: слоты = N × 24
BRIDGE_MIN = 0.90                    # ниже — замер не считается вовсе


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_sections(mdir_model, target):
    """Полное сечение часа из `preds.jsonl`: {рука: {ts: [(имя, прогноз)]}}.

    Берётся вектор ТОЙ цели, которой книга упорядочивает сечение, —
    иначе состав строился бы по чужому ранжированию и мост бы это
    поймал (а без моста не поймал бы никто).
    """
    out = {}
    path = os.path.join(mdir_model, "preds.jsonl")
    for r in PT.read_jsonl(path):
        if r.get("target") != target:
            continue
        arm, hour = r.get("arm"), r.get("hour")
        syms, pred = r.get("syms") or [], r.get("pred") or []
        if not arm or not hour or len(syms) != len(pred):
            continue
        out.setdefault(arm, {})[BB.hour_ts(hour)] = list(zip(syms, pred))
    return out


def pick_n(row, n, floor_bp):
    """Топ-n/2 с каждого конца сечения — правило книги дословно.

    `train.py`: сечение сортируется по прогнозу, пол применяется к
    МОДУЛЮ сырого прогноза, лонг берётся с конца (самые крупные),
    шорт с начала (самые мелкие). Требования на ЗНАК нет — при
    сплошь положительном сечении шорт возьмёт наименее положительные,
    и повторить это обязательно: иначе состав был бы другой книгой.
    """
    o = sorted(range(len(row)), key=lambda i: row[i][1])
    if floor_bp:
        o = [i for i in o if abs(float(row[i][1])) >= floor_bp]
    # Концы не вправе пересечься: имя, взятое и в лонг, и в шорт, дало
    # бы встречные ноги, а реплей вторую в удерживаемое имя молча
    # пропускает — ширина вышла бы меньше объявленной, и заметить это
    # было бы нечем. Уже сечения ширина быть не может.
    k = min(max(1, n // 2), len(o) // 2)
    legs = []
    for i in o[::-1][:k]:
        legs.append({"sym": row[i][0], "side": "long"})
    for i in o[:k]:
        legs.append({"sym": row[i][0], "side": "short"})
    return legs


def priced(legs, mids, ts, last):
    """Цена входа — середина часа решения (конвенция книг со сроком).

    Нет цены — ноги нет: молчаливый ноль на месте отсутствующей цены
    уже стоил проекту нескольких дефектов.
    """
    out = []
    for g in legs:
        px = BB.mid_at(mids, g["sym"], ts, last)
        if px:
            out.append({"sym": g["sym"], "side": g["side"],
                        "px": float(px)})
    return out


def build(sections, n, floor_bp, mids):
    """Состав всех часов заданной ширины, по рукам."""
    out, last = {}, {}
    for arm, by in sections.items():
        for ts in sorted(by):
            legs = priced(pick_n(by[ts], n, floor_bp), mids, ts, last)
            if legs:
                out.setdefault(arm, {})[ts] = legs
    return out


def bridge(built6, recorded):
    """Доля часов, где состав из сечения совпал с записанным выбором.

    Сравниваются множества (имя, сторона): порядок ног внутри часа
    книга не фиксирует, а состав — фиксирует.
    """
    same = tot = 0
    for arm, by in recorded.items():
        got = built6.get(arm) or {}
        for ts, legs in by.items():
            if ts not in got:
                continue
            tot += 1
            a = {(g["sym"], g["side"]) for g in legs}
            b = {(g["sym"], g["side"]) for g in got[ts]}
            same += 1 if a == b else 0
    return (same / tot if tot else 0.0), tot


def leg_usd(n, capital=BB.CAPITAL):
    """Нога ширины: капитал делится на объявленные слоты N × 24."""
    return capital / float(n * HOLD_H)


def run_arm(by, mids, n):
    return BB.replay(by, mids, CELL["take"], CELL["floor"],
                     leg_usd=leg_usd(n), age_h=CELL["age_h"])


def legs_per_hour(by):
    if not by:
        return 0.0
    return sum(len(v) for v in by.values()) / float(len(by))


def fmt(v, spec="+.2f", dash="—"):
    return dash if v is None else format(v, spec)


def cell_row(name, c, extra=""):
    if not c:
        return f"| {name} | — | — | — | — | — |{extra}"
    return (f"| {name} | {fmt(c['realized'])} | "
            f"{c['baskets']} ({c['n_take']}/{c['n_floor']}/"
            f"{c['n_age']}) | {fmt(c['worst_basket'])} | "
            f"{fmt(c['max_dd'])} |{extra}")


def write_report(path, res, meta):
    L = ["# Ширина согласной корзины (правило h24c)\n"]
    L.append(
        f"Прогон {meta['when']} · окно {meta['span']} · правило ОДНО — "
        f"живая h24c: цель +{CELL['take'] * 100:g} %, предел "
        f"−{CELL['floor'] * 100:g} %, возраст {CELL['age_h']} ч · ось "
        f"ширины {', '.join(str(n) for n in WIDTHS)} ног в час · нога "
        f"= капитал / (N × {HOLD_H}) · нуль — случайное подмножество "
        f"ТОЙ ЖЕ ширины, {len(SEEDS)} зёрен числом\n")
    L.append(
        f"**Мост: состав из полного сечения при N = 6 совпал с "
        f"записанными выборами в {meta['bridge']:.3f} часов "
        f"({meta['bridge_n']} часов сравнено).** Ниже "
        f"{BRIDGE_MIN:.2f} замер не считался бы вовсе — состав из "
        f"`preds` описывал бы другую книгу, а таблица выглядела бы "
        f"исправной.\n")
    L.append(
        "**Это зонд, порогов вердикта нет; вердиктовая фраза выведена "
        "из чисел.** Ширина меняет ДВЕ вещи разом: качество ног "
        "(глубокие места сечения) и достижимость порогов в долях "
        "капитала (гросс корзины). Нуль той же ширины несёт вторую "
        "целиком, поэтому разность agreed − null принадлежит "
        "согласию, а не расширению.\n")
    L.append("| ширина · рука | realized $ | корзин "
             "(цель/предел/возраст) | худшая | просадка | ног в час |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for n in WIDTHS:
        r = res.get(n)
        if not r:
            L.append(f"| N={n} | — | — | — | — | — |")
            continue
        for arm in sorted(r["arms"]):
            a = r["arms"][arm]
            L.append(cell_row(f"N={n} · {arm} · base", a["base"],
                              f" {a['n_base']:.2f} |"))
            L.append(cell_row(f"N={n} · {arm} · agreed", a["agreed"],
                              f" {a['n_agreed']:.2f} |"))
            ns = a["null_summary"]
            if ns:
                L.append(
                    f"| N={n} · {arm} · null×{len(SEEDS)} | "
                    f"{fmt(ns['mean'])} [{fmt(ns['min'])} … "
                    f"{fmt(ns['max'])}] | — | {fmt(ns['worst_mean'])} | "
                    f"{fmt(ns['dd_mean'])} | {a['n_agreed']:.2f} |")
    L.append("\n## Согласие по ширине\n")
    L.append("| ширина | ног в час у base | согласных в час | доля |")
    L.append("|---|--:|--:|--:|")
    for n in WIDTHS:
        r = res.get(n)
        if not r:
            continue
        b = sum(a["n_base"] for a in r["arms"].values()) / len(r["arms"])
        g = sum(a["n_agreed"] for a in r["arms"].values()) / len(r["arms"])
        L.append(f"| N={n} | {b:.2f} | {g:.2f} | "
                 f"{(g / b if b else 0):.3f} |")
    for n in WIDTHS:
        r = res.get(n)
        if not r:
            continue
        for arm in sorted(r["arms"]):
            L.append(f"\n**N={n}, {arm} (выведен из чисел):** "
                     f"{r['arms'][arm]['verdict']}")
    L.append(
        "\nЧитать: доля согласия по ширине и есть прямой ответ на "
        "вопрос — растёт ли согласный состав вместе с сечением или "
        "согласие живёт только у краёв. Сравнивать agreed с base в "
        "долларах нельзя (разный гросс), сравнение идёт agreed против "
        "null той же ширины. Колонка «корзин» показывает, достаёт ли "
        "корзина порогов вовсе: закрытия по возрасту при нулях в цели "
        "и пределе означают, что правило корзины выродилось в "
        "суточное закрытие.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="ширина согласной корзины")
    ap.add_argument("--s8", default=os.path.join(
        RESEARCH, "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--target", default="fwd_24h")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)

    mdir = os.path.join(a.s8, "model_h24")
    recorded = BB.load_picks(mdir)
    if not recorded:
        log_("выборов model_h24 нет — считать нечего")
        return 1
    floor_bp = 0.0
    for r in PT.read_jsonl(os.path.join(mdir, "picks.jsonl")):
        if r.get("floor_bp"):
            floor_bp = float(r["floor_bp"])
            break
    sections = load_sections(os.path.join(a.s8, "model"), a.target)
    if not sections:
        log_(f"сечений цели {a.target} в preds.jsonl нет — "
             f"состав шире записанного не построить")
        return 1
    hours = sum(len(v) for v in sections.values())
    log_(f"сечений {hours} по {len(sections)} рукам, пол {floor_bp:g} б.п.")

    syms = {s for by in sections.values() for row in by.values()
            for s, _ in row}
    mids = BB.BK.load_mids(syms)
    keys = BA.AG.pick_keys(mdir)

    built6 = build(sections, 6, floor_bp, mids)
    share, n_cmp = bridge(built6, recorded)
    log_(f"мост N=6: совпало {share:.3f} на {n_cmp} часах")
    if share < BRIDGE_MIN:
        log_(f"мост ниже {BRIDGE_MIN:.2f} — состав из сечения "
             f"описывает другую книгу, замер не считается")
        return 1

    lo = min(min(by) for by in sections.values())
    hi = max(max(by) for by in sections.values())
    span = (datetime.fromtimestamp(lo, timezone.utc)
            .strftime("%Y-%m-%d %H:%M") + " … "
            + datetime.fromtimestamp(hi, timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"))

    res = {}
    for n in WIDTHS:
        picks = built6 if n == 6 else build(sections, n, floor_bp, mids)
        agreed = BA.agreed_picks(picks, keys)
        arms = {}
        for arm, by in sorted(picks.items()):
            ag_by = agreed.get(arm) or {}
            base = run_arm(by, mids, n)
            agr = run_arm(ag_by, mids, n)
            nulls = []
            for seed in SEEDS:
                nb = BA.null_picks({arm: by}, agreed, seed).get(arm) or {}
                c = run_arm(nb, mids, n)
                if c:
                    nulls.append(c)
            arms[arm] = {
                "base": base, "agreed": agr,
                "null_summary": BA.null_summary(nulls) if nulls else None,
                "verdict": BA.verdict(agr, nulls),
                "n_base": legs_per_hour(by),
                "n_agreed": legs_per_hour(ag_by)}
            log_(f"N={n} {arm}: base {fmt(base and base['realized'])}, "
                 f"agreed {fmt(agr and agr['realized'])}, "
                 f"ног в час {legs_per_hour(by):.1f}/"
                 f"{legs_per_hour(ag_by):.1f}")
        res[n] = {"arms": arms}

    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"), "span": span,
            "bridge": share, "bridge_n": n_cmp, "floor_bp": floor_bp}
    with open(os.path.join(OUT, f"agree-width-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"meta": meta, "cell": CELL, "widths": list(WIDTHS),
                   "seeds": list(SEEDS), "res": res,
                   "took_sec": round(time.time() - t0, 1)},
                  f, ensure_ascii=False, indent=1, default=str)
    path = write_report(
        os.path.join(OUT, f"AGREE-width-{a.tag}.md"), res, meta)
    log_(f"отчёт: {path} · {round(time.time() - t0, 1)} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
