#!/usr/bin/env python3
"""Короткие книги на сигнале `h24`: три режима рядом с длинными, хедж.

Решение владельца 2026-09-07: «давай делать рядом три варианта шорт-
стратегий (безопасная, оптимальная, агрессивная), а также режим общей
статистики, под хедж-режим».

Что это. Три бумажные книги (`safe_h`, `optimal_h`, `aggr_h` — реестр
`rules.RULERS`, порядок `rules.H24_ORDER`) × три депозита. Вход — КОРОТКИЕ
выборы книги со сроком `h24` (обе руки модели), срок 24 ч, доливов нет,
цель — обещание модели ×2, гейт края ≥ 33 б.п. при любом отношении.
Различаются режимы ровно плечом, как у длинных: запас 6σ, глубина
2·d_max, глубина плюс гейт ≥ 4×.

Почему именно так — всё из уже сделанных замеров, объявлено до прогона:
короткие книги на ситуационном листе в минусе на всём пространстве
выходов (D9, D10); единственный источник с плюсом у короткой стороны и в
кассе, и сырым — 24-часовой сигнал (разрез по стороне); лестница на нём
даёт 52–53 ликвидации и минус (D11); гейт RR ≥ 2 душит подачу
(`sheet_supply.py`).

ХЕДЖ-РЕЖИМ. Книга не смотрит на то, что держат длинные книги: шорт по
имени, которое длинная держит, разрешён. На бирже это законно только в
хедж-режиме позиции; в одностороннем такой шорт закрыл бы часть длинной,
и это разница ПРАВИЛ СЧЁТА, а не показа. Сколько таких совпадений — не
догадка, а число: считает книга общего счёта (`run_pair.py`).

Внутри семейства правило прежнее: одна позиция на имя (`D6.one_per_name`),
дубли проверяет тот же инвариант, что у длинных (`run_paper.dups`).

Запуск: `run research/dca_paper/run_short.py`. Смоук: `--limit 200`.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
import rules as R                                             # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d11 as D11                                         # noqa: E402
import tail as TL                                             # noqa: E402

# Ячейка сетки D10, которой торгует семейство: плечо забора, без доливов,
# цель ×2. Объявлена здесь одним местом — из неё же выводится подпись
# кэша, и вторая копия ключа однажды разошлась бы с прогоном.
CELL = ("fence:none:t2", "fence", "none", "t2")
# Книга → линейка забора, на которой считается её позиция. «Агрессивная»
# считается на той же линейке, что «оптимальная», и отличается ГЕЙТОМ
# плеча (`rules.min_lev_of`), как у длинных книг.
BOOKS = {"safe_h": "safe_s", "optimal_h": "optimal_s", "aggr_h": "optimal_s"}
ARMS = ("gbm", "nn")
# Кэш реплея лежит ВНЕ публикуемого каталога. `publish.sh` кладёт в
# историю весь `research/*/out`, и семимегабайтный кэш там упёрся в
# защиту от опасного коммита, заморозив публикацию на три часа: логи
# заданий, журнал книг и свод длинных книг не уезжали никуда. Правило
# игнора это лечит, но лечит ОДИН файл; каталог вне публикации лечит
# класс. Записи здесь нет: кэш выводится из журнала выборов и правил.
CACHE_DIR = os.path.join(HERE, "cache")
CACHE = os.path.join(CACHE_DIR, "recs-short.jsonl")


def cache_sig():
    """Подпись настроек, от которых зависит исход позиции.

    Кэш законен потому, что прошлое не меняется: закрытая позиция при тех
    же правилах даст тот же исход. Сменится ячейка, срок, гейт или пол
    капитуляции — кэш описывает другую книгу, и прогон обязан сказать это
    вслух и посчитать заново.
    """
    return {"cell": CELL[0], "hold_h": R.H24_HOLD_H, "edge": D2.MIN_EDGE_BP,
            "back_h": D2.BACK_H, "rungs": D2.N_RUNGS,
            "weights": list(D2.WEIGHTS), "gap": D2.MIN_ADD_GAP,
            # Пол капитуляции — СВОЙ У КНИГИ (решение владельца 10.09):
            # в подписи он картой, а не одним числом. Кэш, не знающий
            # про смену пола, отдал бы прогону исходы ДРУГОЙ книги —
            # молча, потому что ключ записи от пола не зависит.
            "floor": {bk: R.floor_frac_of(bk, D2.FLOOR_FRAC)
                      for bk in sorted(BOOKS)},
            "take": R.TAKE_MULT,
            "cost_bp": D10.ROUND_COST_BP, "books": sorted(set(BOOKS.values()))}


def legs(arms=ARMS, limit=None, log=print, path=None):
    """Короткие выборы `h24` ОБЕИХ рук: решение владельца «оставить обе».

    Порядок — по моменту, затем по руке и имени: он же порядок кассы, и
    ставить его случайным значило бы раздавать деньги по удаче.
    """
    out = []
    for arm in arms:
        got = D11.h24_legs(arm, path=path, limit=limit, log=log)
        out.extend(got)
    out.sort(key=lambda g: (g["at"], g.get("arm") or "", g["sym"]))
    log(f"ног обеих рук: {len(out)}")
    return out


def needs_replay(cache, legs_):
    """Какие решения считать заново: новых нет в кэше, открытые стареют."""
    need = []
    for g in legs_:
        k = (g["sym"], round(float(g["at"]), 3))
        for rk in set(BOOKS.values()):
            r = cache.get((rk, k[0], k[1]))
            if r is None or r.get("state") != "closed":
                need.append(g)
                break
    return need


def read_cache(path=None, log=print):
    """Кэш реплея семейства. Непригодный не чинится молча."""
    path = path or CACHE
    cache, why = RP.read_cache(path, sig=cache_sig())
    if why:
        log(f"кэш реплея семейства не используется: {why}")
    # ключ кэша `run_paper` — (пара, имя, момент); здесь пара есть ЛИНЕЙКА
    out = {}
    for (pair, sym, at), r in cache.items():
        rk = pair[0] if isinstance(pair, (list, tuple)) else pair
        out[(rk, sym, at)] = r
    return out, why


def write_cache(cache, path=None):
    path = path or CACHE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    RP.write_cache({((rk,), sym, at): r for (rk, sym, at), r in cache.items()},
                   path=path, sig=cache_sig())


def floor_groups():
    """Линейки D10 по ПОЛУ капитуляции: {доля: [линейки]}.

    Пол — свойство КНИГИ, а симуляция знает линейку, поэтому книги
    сначала переводятся в свои линейки. Линейка, кормящая две книги с
    РАЗНЫМ полом, была бы неразрешимой — и это проверяется, а не
    подразумевается: молча взять первую попавшуюся долю значило бы
    торговать книгой, которой нет.
    """
    out = {}
    for bk, rk in BOOKS.items():
        f = R.floor_frac_of(bk, D2.FLOOR_FRAC)
        for other, prev in out.items():
            if rk in prev and abs(other - f) > 1e-12:
                raise ValueError(
                    f"линейка {rk} кормит книги с разным полом "
                    f"({other:g} и {f:g}) — симуляция не может дать оба")
        out.setdefault(f, [])
        if rk not in out[f]:
            out[f].append(rk)
    return out


def replay(need, src=None, log=print):
    """Досчёт недостающих решений: одна ячейка, отметки и заполнения.

    Срок и гейт отсчёта ставятся НА ВРЕМЯ прогона (`run_d11.configure`) и
    возвращаются обратно: те же модули читает замер, и оставленный
    globally срок 24 ч сделал бы его другим замером молча.

    Пол капитуляции у книг РАЗНЫЙ (0.10 у безопасной, 0.50 у остальных),
    а в симуляции он глобален — поэтому проход идёт по группам пола, и
    в каждой группе считаются только СВОИ линейки. Один проход на все
    книги отдал бы двум из трёх чужой пол.
    """
    if not need:
        return {}, {}
    was = D11.configure(R.H24_HOLD_H)
    try:
        src = src or TL.TailBars(log=log)
        got = {"recs": {}}
        was_floor = D2.FLOOR_FRAC
        try:
            for frac, rulers in sorted(floor_groups().items()):
                D2.FLOOR_FRAC = float(frac)
                log(f"пол капитуляции {frac:g} — линейки "
                    + ", ".join(rulers))
                part = D10.collect(legs=need, cells=[CELL], rich=True,
                                   raw=True, src=src, log=log)
                for rk in rulers:
                    got["recs"][rk] = (part.get("recs") or {}).get(rk) or {}
        finally:
            D2.FLOOR_FRAC = was_floor
        # Хвост ленты — правило книги, и применяется он там, где источник
        # умеет его отдать. Источник без хвоста (проверка на подставных
        # барах) не превращается в «хвост не сработал»: причина называется.
        if hasattr(src, "stats") and hasattr(src, "last_tape"):
            tail = dict(src.stats(), **TL.apply(
                {k: v[CELL[0]] for k, v in got["recs"].items()},
                src.last_tape, src.last_book))
        else:
            tail = {"why": "источник баров без хвоста ленты"}
        out = {}
        for rk, byk in got["recs"].items():
            for r in byk[CELL[0]]:
                out[(rk, r["sym"], round(float(r["at"]), 3))] = r
        log(f"досчитано записей {len(out)} по {len(need)} решениям")
        return out, tail
    finally:
        D11.restore(was)


def run(limit=None, src=None, log=print, legs_=None, journal=None,
        cache_path=None, now=None, launch=None):
    t0 = time.time()
    legs_ = legs(limit=limit, log=log) if legs_ is None else list(legs_)
    cache, _why = read_cache(cache_path, log=log)
    need = needs_replay(cache, legs_)
    log(f"решений {len(legs_)}, в кэше {len(cache) // max(1, len(set(BOOKS.values())))}, "
        f"считаю заново {len(need)}")
    fresh, tail = replay(need, src=src, log=log)
    cache.update(fresh)
    write_cache(cache, cache_path)
    # обещание модели у записей: из тех же ног, что кормят реплей
    fav = {}
    for g in legs_:
        try:
            fav[(g["sym"], round(float(g["at"]), 3))] = float(g["fav"])
        except (KeyError, TypeError, ValueError):
            continue
    by_ruler = {}
    for (rk, sym, at), r in cache.items():
        if r.get("fav_bp") is None:
            r["fav_bp"] = fav.get((sym, at))
        by_ruler.setdefault(rk, []).append(r)
    packed = {bk: list(by_ruler.get(rk) or []) for bk, rk in BOOKS.items()}
    # ВОЗРАСТ ИМЕНИ на входе — правило книги с 2026-09-08 (решение
    # владельца «сделать такую же логику, как в общих»). Порог и доля
    # билета объявлены одной картой на все счета (`rules.MIN_AGE_DAYS`,
    # `rules.SHORT_SHARE`), применяет их одно ядро (`run_paper`).
    # Справочник читается ОДИН раз на прогон: его спрашивают все три
    # книги на каждое решение.
    launch = IR.launches() if launch is None else launch
    ages = {}
    for bk in list(packed):
        packed[bk], ages[bk] = RP.age_shorts(packed[bk], bk, launch=launch,
                                             log=log, now=now)
    rows, cells, one, live = RP.build_rows(packed, now=now,
                                           keys=R.H24_ORDER, log=log)
    RP.append_journal(rows, path=journal or R.H24_JOURNAL, log=log)
    s = RP.summarize(path=journal or R.H24_JOURNAL, live=live,
                     keys=R.H24_ORDER)
    s.update({"family": "h24", "cells": cells, "one_name": one, "ages": ages,
              "signal": {"book": "h24", "arms": list(ARMS), "cell": CELL[0],
                         "hold_h": R.H24_HOLD_H, "legs": len(legs_),
                         "gate": "край ≥ 33 б.п., отношение любое"},
              "hedge": True, "tail": tail,
              "positions": len(cache) // max(1, len(set(BOOKS.values()))),
              "replayed": len(fresh),
              "secs": round(time.time() - t0, 1),
              "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
              "rules": {"RULES": R.RULES, "DEPOSITS": list(R.DEPOSITS),
                        "AHEAD_H": R.AHEAD_H, "HOLD_H": R.H24_HOLD_H,
                        "TICKET": R.TICKET,
                        "RULERS": {k: dict(R.RULERS[k]) for k in R.H24_ORDER},
                        "RULER_ORDER": list(R.H24_ORDER)}})
    # Общий счёт (длинная книга и короткая на ОДНОМ депозите) считает
    # `run_pair.py` своей книгой и своим журналом. Прежний блок «общая
    # статистика» складывал два РАЗДЕЛЬНЫХ счёта и снят: владелец
    # попросил один общий счёт, а две «общих» с разными числами на одной
    # странице — это путаница, а не два взгляда.
    return s


def _p(x, d=2):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def report(s):
    sig = s.get("signal") or {}
    L = ["# Короткие книги на сигнале h24 (три режима, хедж-режим)", "",
         "Решение владельца 2026-09-07: три варианта коротких стратегий "
         "рядом с длинными и режим общей статистики, под хедж-режим. "
         "Вход — короткие выборы книги `h24` обеих рук модели, срок "
         f"{sig.get('hold_h')} ч, доливов нет, цель — обещание модели ×2, "
         f"гейт: {sig.get('gate')}. Режимы различаются ТОЛЬКО плечом, как "
         "у длинных книг.", "",
         f"Решений листа: {sig.get('legs')}; позиций в кэше реплея "
         f"{s.get('positions')}, из них пересчитано в этом прогоне "
         f"{s.get('replayed')}. Правила версии {s['rules']['RULES']}; "
         f"прогон {s.get('secs')} с.", "",
         "**Правила счёта** (решение владельца 2026-09-08 «сделать такую "
         "же логику, как и в общих»; объявлены ДО прогона, оба взяты у "
         "общего счёта и заново не подбирались):", "",
         "* **возраст имени** — книга не входит в имя, торгующееся "
         "меньше порога на момент решения; возраст неизвестен — входа "
         "тоже нет, и это своё число;",
         "* **доля билета** — "
         + ", ".join(f"{R.ruler_title(k)} {R.SHORT_SHARE.get(k, 1.0):g}×"
                     for k in R.H24_ORDER)
         + ", не ниже биржевого пола (на депозите $1 000 билеты и так "
         "стоят на полу, и доля там не кусается).", "",
         "| книга | порог | решений предложено | взято | моложе порога | "
         "возраст неизвестен | справочнику часов |",
         "|---|---|--:|--:|--:|--:|--:|"]
    for rk in R.H24_ORDER:
        a = (s.get("ages") or {}).get(rk) or {}
        fr = a.get("справочнику часов")
        L.append(f"| {R.ruler_title(rk)} | "
                 + ("нет" if not a.get("age")
                    else f"≥{float(a.get('days') or 0):g} сут")
                 + (f" ({a['why']})" if a.get("why") else "")
                 + f" | {a.get('offered', 0)} | {a.get('kept', 0)} | "
                 f"{a.get('моложе порога', 0)} | "
                 f"{a.get('возраст неизвестен', 0)} | "
                 + ("—" if fr is None else f"{fr:g}") + " |")
    L += ["",
         "## Книги", "",
         "| книга | депозит | билет | сделок | Σ $ | итог | просадка | "
         "медиана дня | плюсов | вперёд / пересчёт |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for rk in R.H24_ORDER:
        for dep in R.DEPOSITS:
            b = (s.get("books") or {}).get(f"{rk}:{int(dep)}") or {}
            st = b.get("all") or {}
            L.append(
                f"| `{rk}` ({R.ruler_title(rk)}) | ${int(dep)} | "
                f"${R.ticket_in(rk, rk, dep):g} | {st.get('n', 0)} | "
                f"{_u(st.get('usd'))} | {_p(st.get('final'))} | "
                f"{_p(st.get('max_dd'))} | {_u(st.get('day_median'))} | "
                f"{st.get('win', '—')} % | {b.get('n_forward', 0)} / "
                f"{b.get('n_restored', 0)} |")
    L += ["", "Вперёд — решения, записанные в течение "
          f"{R.AHEAD_H} ч после самого решения; остальное — пересчёт "
          "истории по нынешним правилам, и складывать их в один вердикт "
          "нельзя.", ""]
    L += ["## Чего замер НЕ говорит", "",
          "- Живого исполнения здесь нет: исходы считаются реплеем по "
          "барам записи. Проскальзывание, очередь в стакане и задержка "
          "входа не моделируются; издержки круга учтены в `pnl_net`, "
          "отдельный замер издержек — `costs.py`.",
          "- Общий счёт с длинной книгой считает `run_pair.py`: там "
          "депозит один на обе стороны, и числа его книг не равны сумме "
          "этой книги и длинной.",
          "- Хедж-режим есть ПРАВИЛО СЧЁТА этой книги: она не смотрит на "
          "длинные позиции. На бирже так можно только в хедж-режиме; в "
          "одностороннем совпадающий шорт резал бы длинную позицию, и "
          "число таких совпадений стоит выше.",
          "- Веса модели видели эти часы: пересчёт истории читается как "
          "оценка СВЕРХУ. Судит форвард.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="короткие книги на сигнале h24")
    ap.add_argument("--limit", type=int, default=None, help="ног, смоук")
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    s = run(limit=a.limit)
    art = R.H24_ARTIFACT if not a.limit else R.H24_ARTIFACT.replace(
        ".json", "-smoke.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    name = "DCA-short" if not a.limit else "DCA-short-smoke"
    with open(os.path.join(R.OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"DCA: короткие книги на сигнале h24{(' ' + a.tag) if a.tag else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
