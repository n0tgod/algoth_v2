#!/usr/bin/env python3
"""
Шаг объявления: заявка, прошедшая потолок, попадает в реестр.

Объявление — единственное необратимое действие фабрики. С этой минуты
кандидат тратит испытание и судится только ВПЕРЁД: ослабить вердикт
задним числом нельзя, поэтому ворота здесь жёсткие и каждый отказ
называется словами, а не пустотой.

Ворота, и все они проверяемы машиной:

  * вердикт потолка есть, и он `pass` — «не прошёл» и «не считался»
    лечатся по-разному, поэтому названы порознь;
  * вердикт вынесен о ТОЙ ЖЕ заявке, что лежит сейчас (сверка ключа):
    вчерашний `pass` не вправе объявлять сегодняшнего кандидата;
  * числа, на которых вердикт вынесен, СЕГОДНЯШНИЕ — вердикт по
    позавчерашнему прогону описывает другой пул;
  * ключ ещё не в реестре — повтор тратит бюджет впустую.

Контрольная рука добирается ВСЕГДА, даже когда объявлять нечего: её
доля есть свойство пула, а не заявки.

    .venv/bin/python research/factory/declare.py
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ledger as LG                                       # noqa: E402
import run_day as RD                                      # noqa: E402
import space as SP                                        # noqa: E402

OUT = os.path.join(HERE, "out")
DAY = 86400.0


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except OSError as e:
        return None, f"{os.path.basename(path)}: {e.strerror}"
    except ValueError as e:
        return None, f"{os.path.basename(path)} не разбирается: {e}"


def gate(ceil, prop, run_at, now, state, ceil_at=None):
    """Можно ли объявлять. Возвращает (правило, причина отказа).

    Причина — всегда слова. Пустой ответ здесь означал бы «объявлять
    нечего» и «объявлять нельзя» одним и тем же молчанием.
    """
    if ceil is None:
        return None, "вердикта потолка нет: шаг потолка не отработал"
    v = ceil.get("verdict")
    if v != "pass":
        return None, (f"потолок сказал {v}: {ceil.get('why')}")
    rule = ceil.get("rule")
    cid = ceil.get("id")
    if not isinstance(rule, dict) or not cid:
        return None, "вердикт без кандидата: в нём нет правила"
    why = SP.validate(rule)
    if why:
        return None, f"правило вердикта негодно: {why}"
    if SP.key(rule) != cid:
        return None, "ключ вердикта не совпадает с его же правилом"
    # Вердикт обязан быть о ТОЙ заявке, которая лежит сейчас: иначе
    # вчерашний `pass` объявил бы сегодняшнего кандидата, и никакой
    # проверки заявки при этом не было бы вовсе.
    if prop is not None and isinstance(prop.get("rule"), dict):
        if SP.key(prop["rule"]) != cid:
            return None, ("вердикт о другом кандидате: заявка "
                          f"{SP.key(prop['rule'])}, вердикт {cid}")
    if run_at is None:
        return None, "неизвестно, по какому прогону вынесен вердикт"
    if _day(run_at) != _day(now):
        return None, (f"вердикт вынесен по прогону за {_day(run_at)}, "
                      f"а сегодня {_day(now)}: числа описывают другой пул")
    # Свежесть проверяется у ОБОИХ: числа сегодняшние — это про
    # артефакт прогона, а вердикт мог остаться вчерашним (шаг потолка
    # сегодня не отработал), и тогда сегодняшние числа судил бы
    # позавчерашний вердикт. Вердикт обязан быть посчитан ПОСЛЕ чисел,
    # которые судит, — иначе он судил не их.
    if ceil_at is None:
        return None, "неизвестно, когда вынесен вердикт"
    if _day(ceil_at) != _day(now):
        return None, (f"вердикт потолка за {_day(ceil_at)}, а сегодня "
                      f"{_day(now)}: шаг потолка сегодня не отработал")
    if ceil_at < run_at:
        return None, ("вердикт вынесен РАНЬШЕ чисел, которые судит: "
                      "он судил не этот прогон")
    if cid in state:
        return None, f"кандидат {cid} уже в реестре"
    return rule, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--base", default=None,
                    help="каталог реестра (по умолчанию --out)")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    log = print
    base = a.base or a.out
    now = time.time()
    seed = a.seed if a.seed is not None else int(now // DAY)

    ceil, why_c = read_json(os.path.join(a.out, "ceiling.json"))
    prop, _ = read_json(os.path.join(a.out, RD.PROPOSAL_NAME))
    run_path = os.path.join(a.out, f"factory-day-{a.tag}.json")
    run_at = os.path.getmtime(run_path) if os.path.exists(run_path) else None
    cpath = os.path.join(a.out, "ceiling.json")
    ceil_at = os.path.getmtime(cpath) if os.path.exists(cpath) else None

    st = LG.state(LG.read(base)[0])
    rule, why = gate(ceil if ceil is not None else None, prop, run_at,
                     now, st, ceil_at=ceil_at)
    if ceil is None and why_c:
        why = f"вердикта потолка нет ({why_c})"
    fresh = []
    if rule is not None:
        note = (ceil.get("why") or "")[:200]
        fresh.append((rule, f"потолок: {note}"))
        log(f"объявляю {SP.key(rule)}")
    else:
        log(f"объявлять нечего — {why}")

    declared = RD.declare_rules(base, now, seed, fresh, log=log,
                                source="ceiling")
    res = {"at": now, "declared": declared,
           "candidate": None if rule is None else SP.key(rule),
           "why": why,
           "controls": sum(1 for _k, l in declared if l == "control")}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "declare.json"), "w",
              encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    log(f"объявлено: {len(declared)} ({res['controls']} случайных)")
    if not a.no_publish:
        RD.publish(os.path.join(a.out, "declare.json"), log=log,
                   msg="фабрика: объявление")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
