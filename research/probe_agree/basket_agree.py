#!/usr/bin/env python3
"""Вопрос владельца (2026-08-31): как повели бы себя КОРЗИННЫЕ книги
24 ч на согласных ногах?

Разложение до замера, и оно сужает вопрос честно. У `h24b`/`h24bf`
ноги живут своими таймерными выходами (эхо копирует разборы h24
дословно) — их по-ножная часть под согласием УЖЕ измерена основным
зондом (+441/+358 б.п. на сделку, p = 0.000): это буквально те же
сделки. Подлинно новый вопрос только у конструкции `h24c` — отдельных
выходов у ног НЕТ, корзина закрывается целиком, и состав корзины
меняет саму динамику выходов. Фильтром записанных сделок h24c не
ответить: убери ноги — цель, предел и возраст сработали бы в другие
моменты. Значит реплей, и ровно тем ядром, что мерило корзину
(`probe_basket.replay` — второй копии нет).

**Ячейка ОДНА и это правило живой книги h24c: цель +5 %, предел −5 %,
возраст 24 ч.** Сетки нет — перебор порогов после вопроса был бы
ошибкой R5.

Три руки на каждую голову (gbm/nn), объявлены до прогона:
- `base` — все ноги (тот же реплей в том же прогоне — парный якорь);
- `agreed` — ноги, которые в тот же час выбрала и ДРУГАЯ голова
  (правило model_h24a; ключи — `agree.pick_keys`, флаг известен в
  момент входа: оба выбора пишет один цикл);
- `null` — случайное подмножество ТОЙ ЖЕ ширины по каждому часу,
  10 зёрен числом. Нуль обязателен: у узкой корзины те же пороги в
  долях КАПИТАЛА стоят дальше в долях гросса, и любое сужение меняет
  динамику выходов само по себе — нуль несёт это искажение ровно
  так же, и разность agreed − null принадлежит содержанию согласия.

Две ветви размера, и вторая отвечает на вопрос владельца «а если
шире» (`--invest`):
- `leg` (умолчание) — размер ноги живой книги (`LEG_USD`), меняется
  ровно состав. Согласная корзина потому вложена в разы мельче, и
  пороги ±5 % капитала в долях её гросса дальше. Это свойство ЖИВОЙ
  согласной корзины с теми же порогами, а не дефект замера;
- `full` — час получает `капитал / возраст` и делит его между СВОИМИ
  ногами, сколько бы их ни было. Правило причинное (число ног часа
  известно в момент входа) и обобщает первое ТОЧНО: при шести ногах
  в часе `3000/24/6` и есть `LEG_USD`, то есть база не сдвигается ни
  на цент — закреплено тестом. Ширина корзины при этом не «12 ног»:
  согласных ног ~1 в час, то есть в корзине их и так больше двадцати
  разом; узок был не состав, а ВЛОЖЕННЫЙ ГРОСС, и это ветвь его и
  чинит. Достигнутая доля капитала печатается числом — вложить
  больше, чем нашлось согласных часов, нельзя;
- записи ~месяц одного режима, внутри слив 08-24…27; согласие —
  фильтр СЕРЕДИНЫ, не хвоста (замер слива);
- это зонд: порогов вердикта нет, вердиктовая фраза выводится из
  чисел (agreed против распределения нуля), решение за владельцем.

Запуск на VPS:
  cd ~/algoth_v2 && .venv/bin/python research/probe_agree/basket_agree.py
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

for p in (HERE, os.path.join(RESEARCH, "probe_basket"),
          os.path.join(RESEARCH, "probe_setups"),
          os.path.join(RESEARCH, "probe_turn")):
    if p not in sys.path:
        sys.path.insert(0, p)

import agree as AG                                        # noqa: E402
import basket as BB                                       # noqa: E402
import turn as PT                                         # noqa: E402

# Правило живой книги h24c: цель, предел (доли капитала), возраст.
CELL = {"take": 0.05, "floor": 0.05, "age_h": 24}
SEEDS = tuple(range(1, 11))          # зерно числом (урок R3)
OTHER = {"gbm": "nn", "nn": "gbm"}


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def hour_str(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc) \
        .strftime("%Y-%m-%d-%H")


def agreed_picks(picks, keys):
    """Пересечение голов: нога остаётся, если ту же (имя, сторону) в
    тот же час выбрала и другая голова. Ключи — `agree.pick_keys`
    (та же машина, что у зонда согласия и у книг model_h24a/za);
    час без единого согласия ОТСУТСТВУЕТ, а не пуст."""
    out = {}
    for arm, by in picks.items():
        ok = keys.get(OTHER.get(arm)) or set()
        for ts, legs in by.items():
            hs = hour_str(ts)
            kept = [g for g in legs if (hs, g["sym"], g["side"]) in ok]
            if kept:
                out.setdefault(arm, {})[ts] = kept
    return out


def null_picks(picks, agreed, seed):
    """Случайное подмножество ТОЙ ЖЕ ширины по каждому часу.

    Ширина берётся у согласной руки того же часа: нуль обязан нести
    то же искажение «узкая корзина против порогов в долях капитала»,
    иначе разность мерила бы сужение, а не согласие. Час, где
    согласных ног нет, пропускается и у нуля."""
    out = {}
    for arm, by in picks.items():
        ag_by = agreed.get(arm) or {}
        # Зерно числом (урок R3): хеш строки солится на процесс, а
        # нуль обязан воспроизводиться между запусками.
        rnd = random.Random(seed * 1000003
                            + (1 if arm == "nn" else 0))
        for ts in sorted(by):
            k = len(ag_by.get(ts) or [])
            if not k:
                continue
            legs = by[ts]
            kept = rnd.sample(legs, min(k, len(legs)))
            if kept:
                out.setdefault(arm, {})[ts] = kept
    return out


def leg_rule(invest):
    """Размер ноги: живой `LEG_USD` либо полный капитал по часам.

    `full` даёт часу `капитал / возраст` и делит его между ногами
    ЭТОГО часа. Тождество, которое делает ветвь обобщением, а не
    другой книгой: при шести ногах выходит ровно `LEG_USD` живой
    книги 24 ч. Час без ног ничего не получает — вложить в пустоту
    нельзя, и достигнутый гросс печатается числом."""
    if invest != "full":
        return BB.LEG_USD
    per_hour = BB.CAPITAL / float(CELL["age_h"])

    def size(_ts, n):
        return per_hour / float(n) if n else 0.0
    return size


def name_stats(by):
    """Сколько РАЗНЫХ имён в ногах и как они сгущены.

    Число ног отвечает «насколько узка книга по счёту», а забор
    (потолок 10 % капитала на имя) связывает по ИМЕНАМ: если согласие
    выпадает на одни и те же инструменты, вложить капитал нельзя не
    из-за рынка, а из-за собственного правила. Мера прямая — доля ног
    у пяти самых частых имён."""
    cnt = {}
    for legs in by.values():
        for g in legs:
            cnt[g["sym"]] = cnt.get(g["sym"], 0) + 1
    n = sum(cnt.values())
    if not n:
        return None
    top = sorted(cnt.values(), reverse=True)
    return {"legs": n, "names": len(cnt),
            "top1": round(top[0] / n, 3),
            "top5": round(sum(top[:5]) / n, 3)}


def run_arm(by, mids, leg_usd=BB.LEG_USD):
    return BB.replay(by, mids, CELL["take"], CELL["floor"],
                     age_h=CELL["age_h"], leg_usd=leg_usd)


def verdict(agr, nulls):
    """Вердиктовая фраза выводится из числа, а не стоит рядом.

    Сравнивается реализованное: agreed против распределения десяти
    зёрен нуля той же ширины."""
    if agr is None or not nulls:
        return "не измерено — нечего сравнивать"
    vals = [n["realized"] for n in nulls]
    a = agr["realized"]
    if a > max(vals):
        return ("согласие добавляет СВЕРХ сужения: realized выше "
                "максимума десяти зёрен нуля той же ширины")
    if a < min(vals):
        return ("согласные ноги ХУЖЕ случайного сужения той же "
                "ширины: realized ниже минимума десяти зёрен")
    return ("неотличимо от случайного сужения той же ширины: "
            "realized внутри распределения десяти зёрен нуля")


def fmt(v, spec="+.2f", dash="—"):
    return dash if v is None else format(v, spec)


def null_summary(nulls):
    vals = sorted(n["realized"] for n in nulls)
    worst = [n["worst_basket"] for n in nulls
             if n["worst_basket"] is not None]
    dd = [n["max_dd"] for n in nulls]
    gr = [n["gross_share"] for n in nulls
          if n.get("gross_share") is not None]
    return {"mean": sum(vals) / len(vals), "min": vals[0],
            "max": vals[-1],
            "worst_mean": (sum(worst) / len(worst) if worst else None),
            "dd_mean": sum(dd) / len(dd),
            "gross_mean": (sum(gr) / len(gr) if gr else None)}


def write_report(path, res, meta):
    invest = meta.get("invest", "leg")
    L = ["# Согласие голов на корзине без своих выходов (правило "
         "h24c)\n"]
    L.append(f"Прогон {meta['when']} · окно {meta['span']} · ячейка "
             f"ОДНА — правило живой h24c: цель +{CELL['take'] * 100:g}"
             f" %, предел −{CELL['floor'] * 100:g} %, возраст "
             f"{CELL['age_h']} ч · нуль — случайное подмножество ТОЙ "
             f"ЖЕ ширины, {len(SEEDS)} зёрен числом · размер ноги: "
             f"{invest}\n")
    L.append("**Это зонд, порогов вердикта нет; вердиктовая фраза "
             "выведена из чисел.** У h24b/h24bf по-ножная часть под "
             "согласием уже измерена основным зондом (+441/+358 "
             "б.п., p = 0.000) — это те же сделки h24; здесь меряется "
             "единственно новое: корзина, закрывающаяся ТОЛЬКО "
             "целиком, на согласном составе.\n")
    if invest == "full":
        L.append("**Размер ноги: ВЛОЖЕНО ПОЛНОСТЬЮ.** Час получает "
                 f"капитал / {CELL['age_h']} ч и делит его между "
                 "своими ногами — правило причинное (число ног часа "
                 "известно в момент входа) и при шести ногах даёт "
                 "ровно размер живой книги. Отвечает на вопрос «а "
                 "если шире»: у согласной корзины узок был не состав "
                 "(ног в ней и так больше двадцати разом), а "
                 "вложенный гросс — пороги ±5 % КАПИТАЛА в долях "
                 "мелкого гросса стоят вшестеро дальше, и корзина "
                 "закрывалась одним возрастом. Достигнутая доля "
                 "капитала — колонка «гросс»: вложить больше, чем "
                 "нашлось согласных часов, нельзя.\n")
    else:
        L.append("Размер ноги не менялся — согласная корзина вложена "
                 "в разы мельче, и пороги в долях капитала в долях "
                 "её гросса дальше; нуль той же ширины несёт то же "
                 "искажение, разность принадлежит согласию. Ветвь "
                 "`--invest full` вкладывает капитал полностью и "
                 "лежит отдельным отчётом.\n")
    L.append("| голова · рука | realized $ | отметка хвоста | корзин "
             "(цель/предел/возраст) | худшая | просадка | гросс | ног "
             "в открытой |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for arm in sorted(res):
        r = res[arm]
        for name in ("base", "agreed"):
            c = r[name]
            if not c:
                L.append(f"| {arm} · {name} | — | — | — | — | — | — |"
                         " — |")
                continue
            L.append(
                f"| {arm} · {name} | {fmt(c['realized'])} | "
                f"{fmt(c['open_mark'])} | {c['baskets']} "
                f"({c['n_take']}/{c['n_floor']}/{c['n_age']}) | "
                f"{fmt(c['worst_basket'])} | {fmt(c['max_dd'])} | "
                f"{fmt(c.get('gross_share'), '.2f')} | "
                f"{c['open_legs']} |")
        ns = null_summary(r["nulls"])
        L.append(
            f"| {arm} · null×{len(SEEDS)} | {fmt(ns['mean'])} "
            f"[{fmt(ns['min'])} … {fmt(ns['max'])}] | — | — | "
            f"{fmt(ns['worst_mean'])} | {fmt(ns['dd_mean'])} | "
            f"{fmt(ns['gross_mean'], '.2f')} | — |")
    L.append("\nНа сколько РАЗНЫХ имён ложатся ноги — забор стоит на "
             "имени (потолок 10 % капитала), и книга, согласная на "
             "одних и тех же инструментах, упирается не в рынок, а в "
             "собственное правило:\n")
    L.append("| голова · рука | ног | имён | доля верхнего | доля "
             "пяти верхних | срез по имени |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for arm in sorted(res):
        ns = res[arm].get("names") or {}
        caps = {"base": (res[arm]["base"] or {}).get("skipped", {}),
                "agreed": (res[arm]["agreed"] or {}).get("skipped",
                                                         {})}
        nulls = res[arm]["nulls"]
        caps["null"] = {"name_cap": (
            round(sum(c["skipped"]["name_cap"] for c in nulls)
                  / len(nulls), 1) if nulls else None)}
        for name in ("base", "agreed", "null"):
            s = ns.get(name)
            if not s:
                continue
            L.append(f"| {arm} · {name} | {s['legs']} | {s['names']} "
                     f"| {s['top1']:.3f} | {s['top5']:.3f} | "
                     f"{fmt(caps[name].get('name_cap'), '.0f')} |")
    for arm in sorted(res):
        L.append(f"\n**Вердикт {arm} (выведен из чисел):** "
                 f"{res[arm]['verdict']}. Согласных ног "
                 f"{res[arm]['n_agree']} из {res[arm]['n_all']}.")
    tail = ("\nЧитать: `base` — полная корзина (якорь того же "
            "прогона), `agreed` — только ноги, выбранные обеими "
            "головами, `null` — случайное подмножество той же "
            "ширины. ")
    if invest == "full":
        tail += ("Гросс выровнен по построению, поэтому доллары "
                 "сравнимы и с `base` — но у `base` они принадлежат "
                 "другому составу, а вопрос «добавляет ли согласие» "
                 "решает по-прежнему только пара agreed / null: "
                 "случайное сужение той же ширины вложено ровно так "
                 "же. ")
    else:
        tail += ("Согласных ног мало, корзина узкая — сравнивать "
                 "agreed с base в долларах нельзя (разный гросс), "
                 "сравнение идёт agreed против null. ")
    tail += ("Запись ~месяц одного режима, внутри слив 08-24…27; "
             "согласие — фильтр середины, не хвоста.\n")
    L.append(tail)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="согласие на корзине h24c")
    ap.add_argument("--s8", default=os.path.join(
        RESEARCH, "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--invest", choices=("leg", "full"),
                    default="leg",
                    help="leg — размер ноги живой книги; full — час "
                         "делит капитал/возраст между своими ногами")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)

    mdir = os.path.join(a.s8, "model_h24")
    picks = BB.load_picks(mdir)
    if not picks:
        log_("выборов model_h24 нет — считать нечего")
        return 1
    keys = AG.pick_keys(mdir)
    agreed = agreed_picks(picks, keys)
    n_all = {arm: sum(len(v) for v in by.values())
             for arm, by in picks.items()}
    n_agr = {arm: sum(len(v) for v in by.values())
             for arm, by in (agreed or {}).items()}
    for arm in sorted(picks):
        log_(f"{arm}: ног всего {n_all.get(arm, 0)}, согласных "
             f"{n_agr.get(arm, 0)}")

    syms = {g["sym"] for by in picks.values()
            for legs in by.values() for g in legs}
    mids = BB.BK.load_mids(syms)
    lo = min(min(by) for by in picks.values())
    hi = max(max(by) for by in picks.values())
    span = (datetime.fromtimestamp(lo, timezone.utc)
            .strftime("%Y-%m-%d %H:%M") + " … "
            + datetime.fromtimestamp(hi, timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"))

    rule = leg_rule(a.invest)
    res = {}
    for arm, by in sorted(picks.items()):
        base = run_arm(by, mids, rule)
        agr = run_arm(agreed.get(arm) or {}, mids, rule)
        nulls = []
        for seed in SEEDS:
            nb = null_picks({arm: by}, agreed, seed).get(arm) or {}
            c = run_arm(nb, mids, rule)
            if c:
                nulls.append(c)
        nn_stats = [s for s in
                    (name_stats(null_picks({arm: by}, agreed, seed)
                                .get(arm) or {}) for seed in SEEDS)
                    if s]
        res[arm] = {"base": base, "agreed": agr, "nulls": nulls,
                    "verdict": verdict(agr, nulls),
                    "n_all": n_all.get(arm, 0),
                    "n_agree": n_agr.get(arm, 0),
                    "names": {
                        "base": name_stats(by),
                        "agreed": name_stats(agreed.get(arm) or {}),
                        "null": ({
                            "legs": nn_stats[0]["legs"],
                            "names": round(sum(s["names"] for s in
                                               nn_stats)
                                           / len(nn_stats), 1),
                            "top1": round(sum(s["top1"] for s in
                                              nn_stats)
                                          / len(nn_stats), 3),
                            "top5": round(sum(s["top5"] for s in
                                              nn_stats)
                                          / len(nn_stats), 3)}
                            if nn_stats else None)}}
        log_(f"{arm}: base {fmt(base and base['realized'])}, agreed "
             f"{fmt(agr and agr['realized'])}, нулей {len(nulls)}")

    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"), "span": span,
            "invest": a.invest}
    # Имя артефакта несёт ветвь размера: два прогона на один файл уже
    # приводили к склейке конфликта (урок S9-sweep).
    sfx = "" if a.invest == "leg" else f"-{a.invest}"
    with open(os.path.join(OUT, f"agree-basket-{a.tag}{sfx}.json"),
              "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cell": CELL, "seeds": list(SEEDS),
                   "res": res,
                   "took_sec": round(time.time() - t0, 1)},
                  f, ensure_ascii=False, indent=1, default=str)
    path = write_report(
        os.path.join(OUT, f"AGREE-basket-{a.tag}{sfx}.md"), res, meta)
    log_(f"отчёт: {path} · {round(time.time() - t0, 1)} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
