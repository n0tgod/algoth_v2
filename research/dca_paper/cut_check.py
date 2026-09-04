#!/usr/bin/env python3
"""Позиции «оборвано записью» — досчитать по НАБЛЮДЁННЫМ ценам.

Зачем
-----

У бумажных DCA-книг часть позиций стоит в состоянии «оборвано записью»:
их окно не дошло до планового конца срока, исход неизвестен, и в счёт
книги они не входят. Считать их закрытыми «по сроку» нельзя — это
выдумало бы исход (правило `run_d6.position_state`). Но и оставить их
неизвестными нечестно, если цена в тот момент НАБЛЮДАЛАСЬ.

А она наблюдалась. Бары исходов читаются из ЛЕНТЫ (`sweep.read_bars` по
`out/trades/<sym>`), и минута без единой сделки бара не даёт вовсе — то
есть у тонкого имени хвост окна пуст не потому, что цены не было, а
потому, что по ней не торговали. При этом сборщик снимает СТАКАН раз в
секунду по каждому записываемому имени: середина в те же минуты
записана. Значит цена в хвосте есть, и она наблюдена, а не выдумана.

Что здесь считается
-------------------

Тот же дорогой проход (`run_d6.collect_recs`), но источник баров —
лента, ПРОДОЛЖЕННАЯ серединой стакана после последнего бара ленты
(`TailBars`). Пересчитываются только оборванные решения; остальные
берутся из кэша реплея как есть. Деньги книг считаются дважды тем же
кодом (`run_paper.build_rows` + `_stats`) — до подстановки и после.

Три правила, каждое объявлено до прогона
----------------------------------------

1. **Дописывается ТОЛЬКО хвост символа** — минуты ПОСЛЕ последнего бара
   ленты в запрошенном окне. Внутренние дыры (минуты без сделок внутри
   окна) не заполняются намеренно: вход, структурные уровни и цены
   рунгов считаются по тем же барам, и залив их серединой, мы получили
   бы не «ту же позицию с дописанным концом», а другую позицию. Сверх
   того рунг и тейк — ЛИМИТКИ: их исполняет чужой принт, и минута без
   сделок правом на заполнение не является. Отсюда же вторая половина
   правила: у ленты приоритет, середина берётся там, где ленты нет.
2. **Середина есть наблюдение, а не оценка.** Минутный бар хвоста
   строится из секундных снимков стакана: открытие — первая середина
   минуты, максимум и минимум — крайние, закрытие — последняя. Момент
   наблюдения снимка — `max(t, ts)` тем же правилом, что у Z2 (метка
   сборщика ставится один раз на проход по именам и у поздних символов
   отстаёт от факта).
3. **Нет книги в хвосте — позиция остаётся оборванной.** Пустой хвост
   не превращается в «срок»: отсутствие свидетельства не есть
   свидетельство. Число таких печатается отдельной строкой.

Чего замер НЕ делает
--------------------

Он не переписывает журнал книг и не трогает кэш реплея. Это ОТЧЁТ:
насколько посчитанный результат книги отличается от честного, если
досчитать известное. Решение, становится ли правило частью книги (а это
смена правил, то есть архив записи), — за владельцем.

Прогон: `run research/dca_paper/cut_check.py`. Смоук: `--limit 400`.
Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "z2_book"))
import rules as R                                             # noqa: E402
import run_paper as P                                         # noqa: E402
import run_d6 as D6                                           # noqa: E402
import sweep as SW                                            # noqa: E402
import bookfeat2 as BF                                        # noqa: E402
from store import read_hour                                   # noqa: E402

ROOT_B1 = D6.ROOT_B1
HOUR = 3600.0
MINUTE = 60.0


def book_minute_bars(root, sym, t0, t1, log=None):
    """Минутные бары по СЕРЕДИНЕ стакана в окне `[t0, t1]`.

    Формат тот же, что у ленты (`[t, open, high, low, close, объём]`),
    объём ноль: сделок в этой минуте не было, и придумывать их нечем.
    Минута без снимков отсутствует, а не выходит нулевой (урок A2).
    """
    by = {}
    h = int(t0 // HOUR) * HOUR
    while h <= t1:
        hh = datetime.fromtimestamp(h, timezone.utc).strftime("%Y-%m-%d-%H")
        rows = read_hour(os.path.join(root, "book", sym), hh, log=log,
                         parse=BF.snap_line)
        for r in rows:
            known, mid = float(r[0]), float(r[1])
            if known < t0 or known > t1 or mid <= 0:
                continue
            m = int(known // MINUTE) * MINUTE
            c = by.get(m)
            if c is None:
                by[m] = [m, mid, mid, mid, mid, 0.0]
            else:
                c[2] = max(c[2], mid)
                c[3] = min(c[3], mid)
                c[4] = mid
        h += HOUR
    return [by[k] for k in sorted(by)]


class TailBars:
    """Бары ленты, продолженные серединой стакана ПОСЛЕ последнего принта.

    Источник передаётся `collect_recs(src=…)` — тем же входом, которым
    туда подаётся любой другой поставщик баров. Второй копии решения не
    заводится: исход считает то же ядро, меняется только то, ЧЕМ оно
    накормлено в хвосте.
    """

    def __init__(self, root=ROOT_B1, log=None):
        self.root = root
        self.log = log
        self.added = {}        # символ → число дописанных минут
        self.dry = []          # символы, у которых хвоста нет и в книге
        self.span_h = {}       # символ → длина дописанного хвоста, часов

    def bars(self, sym, t0, t1):
        tape = SW.read_bars(self.root, sym, t0, t1)
        if not tape:
            # Ленты нет вовсе — значит нет ни входа, ни уровней. Такую
            # позицию досчитывать не из чего, и подменять её книгой
            # значило бы построить другую сделку, а не дописать эту.
            return tape
        last = float(tape[-1][0])
        # Хвост начинается со СЛЕДУЮЩЕЙ минуты: бар ленты минутно
        # выровнен, и минута самого последнего принта остаётся за
        # лентой целиком. Взяв `last`, мы получили бы ту же минуту
        # дважды — раз принтами, раз котировкой, — и это был бы не
        # дописанный хвост, а подмена последнего бара. Границей служит
        # ровно это число: отдельной проверки «бар позже последнего»
        # здесь нет, потому что она была бы мёртвым кодом (тот же класс,
        # что декоративная привязка сделки к интервалу в Z3).
        add = book_minute_bars(self.root, sym, last + MINUTE, t1,
                               log=self.log)
        if add:
            self.added[sym] = self.added.get(sym, 0) + len(add)
            self.span_h[sym] = round((t1 - last) / HOUR, 2)
        else:
            self.dry.append(sym)
        return tape + add


def cut_keys(cache):
    """Решения, оборванные записью хотя бы у одной линейки.

    Хотя бы у одной, а не у всех: линейки различаются плечом, и
    состояние у них общее (оно про запись, а не про правило), но
    перестраховка здесь дешева — лишний пересчёт даёт те же числа.
    """
    out = {}
    for (_pr, sym, at), r in cache.items():
        if r.get("state") == "cut":
            out[(sym, round(float(at), 3))] = True
    return sorted(out)


def data_end_of(cache):
    """Докуда дошла ЗАПИСЬ по всем решениям кэша.

    Берётся по полному кэшу, а не по пересчитанному подмножеству:
    досчитанный хвост двигает `end_ts` вверх, и посчитай мы границу по
    нему, классификация поехала бы вслед за собственной правкой.
    """
    end = 0.0
    for r in cache.values():
        if r.get("end_ts"):
            end = max(end, float(r["end_ts"]))
    return end


def money(cache, keys, now):
    """Деньги книг по этому кэшу: тем же кодом, что считает сама книга."""
    by_pair = {tuple(P.RULERS[k]): [] for k in keys}
    for (pr, _sym, _at), r in cache.items():
        if pr in by_pair:
            by_pair[pr].append(r)
    rows, cells, _one, live = P.build_rows(
        {k: by_pair[tuple(P.RULERS[k])] for k in keys},
        now=now, log=lambda m: None)
    out = {}
    for rk in keys:
        for dep in R.DEPOSITS:
            mine = [r for r in rows if int(r.get("dep", 0)) == int(dep)
                    and R.ruler_of(r) == rk]
            out[P._cell(rk, dep)] = {"stats": P._stats(mine, dep),
                                     "cut_n": cells[P._cell(rk, dep)]["cut_n"],
                                     "open_n": cells[P._cell(rk, dep)]["open_n"]}
    return out, live


def gap_profile(recs):
    """Профиль недостачи: на сколько окно не дошло до планового конца."""
    g = sorted((float(r["sched_end"]) - float(r["end_ts"])) / HOUR
               for r in recs if r.get("sched_end") and r.get("end_ts"))
    if not g:
        return {}
    n = len(g)
    return {"n": n, "med_h": round(g[n // 2], 2),
            "p90_h": round(g[min(n - 1, int(n * 0.9))], 2),
            "max_h": round(g[-1], 2)}


def run(limit=None, log=print):
    keys = list(R.RULER_ORDER)
    pairs = []
    for k in keys:
        if P.RULERS[k] not in pairs:
            pairs.append(P.RULERS[k])
    cache, why = P.read_cache()
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    end0 = data_end_of(cache)
    keys_cut = cut_keys(cache)
    if limit:
        keys_cut = keys_cut[:limit]
    was = {}
    for (_pr, sym, at), r in cache.items():
        if r.get("state") == "cut":
            was.setdefault((sym, round(float(at), 3)), r)
    log(f"в кэше решений {len(cache) // max(1, len(pairs))}, "
        f"оборванных записью {len(keys_cut)}")
    log(f"запись доходит до "
        f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(end0))} UTC")
    if not keys_cut:
        return {"error": "оборванных записью решений нет"}

    legs = D6.gated_legs(log=lambda m: None)
    src = TailBars(log=None)
    t0 = time.time()
    got = D6.collect_recs(rulers=pairs, legs=legs, only=keys_cut, src=src,
                          log=log)
    secs = round(time.time() - t0, 1)

    # Классификация — по ПРЕЖНЕЙ границе записи (см. `data_end_of`).
    fresh = {}
    for pr, lst in got["recs"].items():
        for r in lst:
            r["state"] = D6.position_state(r, end0)
            fresh[(tuple(pr), r["sym"], round(float(r["at"]), 3))] = r
    # Решение считается досчитанным, только если досчитались ВСЕ его
    # линейки: у них разное плечо, и «одна закрылась» означало бы книгу,
    # где одна линейка знает исход, а другая нет.
    by_key = {}
    for (_pr, sym, at), r in fresh.items():
        by_key.setdefault((sym, at), []).append(r["state"])
    resolved = sum(1 for v in by_key.values()
                   if v and all(x == "closed" for x in v))
    still = len(keys_cut) - resolved
    mixed = sum(1 for v in by_key.values()
                if len(set(v)) > 1)

    # Что изменилось у досчитанных. Считается ПО ЗАПИСЯМ, то есть по
    # парам «позиция × линейка»: исход у линеек разный по построению.
    exits, deeper, dpnl = {}, 0, []
    for k2, r in fresh.items():
        if r["state"] != "closed":
            continue
        prev = cache.get(k2)
        exits[r["exit"]] = exits.get(r["exit"], 0) + 1
        if prev and int(r.get("depth") or 0) > int(prev.get("depth") or 0):
            deeper += 1
        if prev:
            dpnl.append(float(r["pnl"]) - float(prev.get("pnl") or 0.0))

    now = time.time()
    before, _lv0 = money(cache, keys, now)
    patched = dict(cache)
    patched.update(fresh)
    after, _lv1 = money(patched, keys, now)

    return {
        "cut_before": len(keys_cut), "resolved": resolved, "still_cut": still,
        "dry_symbols": sorted(set(src.dry)),
        "added_minutes": int(sum(src.added.values())),
        "added_symbols": len(src.added),
        "tail_span_h": (round(sorted(src.span_h.values())[
            len(src.span_h) // 2], 2) if src.span_h else None),
        "gap": gap_profile(list(was.values())),
        "exits": exits, "deeper": deeper, "mixed": mixed,
        "dpnl_n": len(dpnl),
        "before": before, "after": after,
        "data_end": end0, "secs": secs,
        "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
    }


def _pct(v):
    return "—" if v is None else f"{v * 100:+.2f} %"


def report(s):
    L = []
    A = L.append
    A("# DCA: оборванные записью позиции, досчитанные по наблюдённым ценам")
    A("")
    if s.get("error"):
        A(f"Прогон не состоялся: {s['error']}.")
        return "\n".join(L) + "\n"
    A(f"Прогон {s['computed_at']} UTC, счёт {s['secs']:g} с. Запись доходит "
      f"до {time.strftime('%Y-%m-%d %H:%M', time.gmtime(s['data_end']))} UTC.")
    A("")
    A("## Что здесь измерено")
    A("")
    A("Позиция «оборвано записью» — та, чьё окно не дошло до планового "
      "конца срока: исход неизвестен, и в счёт книги она не входит. "
      "Бары исходов читаются из ЛЕНТЫ, а минута без единой сделки бара не "
      "даёт вовсе — значит хвост окна бывает пуст не потому, что цены не "
      "было, а потому, что по имени не торговали. Стакан при этом "
      "снимается раз в секунду по каждому записываемому имени.")
    A("")
    A("Здесь тот же проход считает те же позиции, но лента в ХВОСТЕ "
      "продолжена серединой стакана. Дописывается только хвост — минуты "
      "после последнего принта; внутренние дыры не заполняются, потому "
      "что по ним считаются вход, уровни и цены рунгов, а рунг и тейк "
      "суть лимитки, которые исполняет чужой принт. Цены хвоста "
      "НАБЛЮДЕНЫ, а не оценены.")
    A("")
    g = s.get("gap") or {}
    if g:
        A(f"Недостача до планового конца: медиана {g['med_h']:g} ч, "
          f"90-й процентиль {g['p90_h']:g} ч, максимум {g['max_h']:g} ч "
          f"({g['n']} позиций).")
        A("")
    A("## Сколько досчиталось")
    A("")
    A("| величина | число |")
    A("|---|---|")
    A(f"| было оборвано записью | {s['cut_before']} |")
    A(f"| досчитано до конца срока | {s['resolved']} |")
    A(f"| осталось оборванными | {s['still_cut']} |")
    A(f"| символов с дописанным хвостом | {s['added_symbols']} |")
    A(f"| дописано минут середины | {s['added_minutes']} |")
    if s.get("tail_span_h") is not None:
        A(f"| медианная длина хвоста, ч | {s['tail_span_h']:g} |")
    A(f"| символов без книги в хвосте | {len(s['dry_symbols'])} |")
    A("")
    if s["still_cut"]:
        A("Оставшиеся оборванными не превращаются в «срок»: книги в их "
          "хвосте нет, а отсутствие свидетельства свидетельством не "
          "является.")
        A("")
    ex = s.get("exits") or {}
    if ex:
        A("Чем кончились досчитанные: "
          + ", ".join(f"{k} {v}" for k, v in sorted(ex.items())) + ".")
        A(f"Лестница углубилась в хвосте у {s['deeper']} записей "
          f"(запись — «позиция × линейка»).")
        if s.get("mixed"):
            A(f"У {s['mixed']} решений линейки разошлись состоянием: одна "
              f"досчиталась, другая нет. Такое решение досчитанным НЕ "
              f"считается — книга, где одна линейка знает исход, а другая "
              f"нет, есть не одна книга.")
        A("")
        if not s["deeper"]:
            A("Ни один долив в хвосте не сработал, то есть вопрос «лимитка "
              "против котировки» на этих данных не встаёт вовсе: середина "
              "решает только цену закрытия по сроку.")
        else:
            A("**Оговорка:** долив и тейк — лимитки, и минута без принта "
              "правом на заполнение не является. Там, где лестница "
              "углубилась по котировке, исход оптимистичен.")
        A("")
    A("## Деньги книг: было и стало")
    A("")
    A("Считаны тем же кодом, что считает сама книга (`build_rows` + "
      "`_stats`), дважды: до подстановки досчитанных исходов и после. "
      "Единица — весь счёт книги (бэктест и форвард одной кривой).")
    A("")
    A("| книга | закрытых было | стало | $ было | $ стало | Δ $ | "
      "к депозиту было | стало | медиана дня было | стало |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for rk in R.RULER_ORDER:
        for dep in R.DEPOSITS:
            key = P._cell(rk, dep)
            b = (s["before"].get(key) or {}).get("stats") or {}
            a = (s["after"].get(key) or {}).get("stats") or {}
            A(f"| {R.ruler_title(rk)} ${int(dep):,} | {b.get('n', '—')} | "
              f"{a.get('n', '—')} | {b.get('usd', '—')} | "
              f"{a.get('usd', '—')} | "
              f"{round(float(a.get('usd') or 0) - float(b.get('usd') or 0), 2)} | "
              f"{_pct(b.get('final'))} | {_pct(a.get('final'))} | "
              f"{_pct(b.get('day_median'))} | {_pct(a.get('day_median'))} |"
              .replace(",", " "))
    A("")
    A("| книга | просадка была | стала | укус был | стал | "
      "зелёных дней было | стало | оборванных осталось |")
    A("|---|---|---|---|---|---|---|---|")
    for rk in R.RULER_ORDER:
        for dep in R.DEPOSITS:
            key = P._cell(rk, dep)
            b = (s["before"].get(key) or {}).get("stats") or {}
            a = (s["after"].get(key) or {}).get("stats") or {}
            cn = (s["after"].get(key) or {}).get("cut_n")
            A(f"| {R.ruler_title(rk)} ${int(dep):,} | {_pct(b.get('max_dd'))} "
              f"| {_pct(a.get('max_dd'))} | {b.get('bite', '—')} | "
              f"{a.get('bite', '—')} | {b.get('day_green', '—')} | "
              f"{a.get('day_green', '—')} | {cn} |".replace(",", " "))
    A("")
    A("## Чего замер не делает")
    A("")
    A("Он не переписывает ни журнал книг, ни кэш реплея: это отчёт о "
      "том, насколько посчитанный результат отличается от честного, а не "
      "правка книги. Сделать досчёт правилом книги — смена правил, то "
      "есть отставленная запись и новая кривая; это решение владельца.")
    A("")
    A("Второе, чего здесь нет: внутренние дыры ленты. Заливать их "
      "серединой значило бы менять вход, уровни и цены рунгов, то есть "
      "мерить другую позицию, а не дописывать эту.")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(R.OUT, exist_ok=True)
    s = run(limit=a.limit)
    with open(os.path.join(R.OUT, "DCA-cut-check.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-cut-check.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        P.publish("DCA: досчёт оборванных записью позиций")


if __name__ == "__main__":
    main()
