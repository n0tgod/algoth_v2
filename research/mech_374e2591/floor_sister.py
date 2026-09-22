#!/usr/bin/env python3
"""Механика 374e2591 — пол капитуляции 0.75 у безопасной короткой книги h24.

Заявка предлагающего 2026-09-22 (`research/factory/out/proposal.md`):
сестра книги `safe_h` с ОДНИМ изменённым правилом — пол капитуляции
стоит на 0.75 расстояния «вход → ликвидация» (порез примерно при
четверти съеденной маржи) вместо 0.10 (у самой ликвидации). Остальное
то же: линейка σ 6, билет 1×, возраст имени ≥ 7 суток, охрана рынком
2 %, срок 24 ч, доливов нет, деньги НЕТТО.

Ни одно число правила здесь не назначается заново. Доля пола берётся у
ОБЪЯВЛЕННОЙ оси замера `short_stop.FLOORS` (ячейка `f75`), пол базовой
книги — у `rules.floor_frac_of`, порог охраны — у `rules.wave_guard_of`,
порог возраста — у `rules.min_age_days`, число зёрен контроля — у
`path_screen.SEEDS`. Порог, назначенный тем же, кто его проверяет,
слабее назначенного независимо, и проверка `правила_берутся_у_книги`
держит это перезагрузкой модуля с подменённым источником.

Два шага, и они отвечают на разные вопросы.

1. **Потолок по почасовым отметкам** (`--marks`, десятки секунд).
   Пол — уровень ЦЕНЫ, а отметки ядра есть переоценка на границе часа,
   поэтому по ним видно не всё. Считаются ДВА варианта пореза, и они
   берут цену выхода в вилку: «по отметке» — позиция закрыта отметкой
   часа (то же, что делает охрана рынком, `wave.guard_record`), «по
   уровню» — ровно на полу, то есть в предположении, что разрыва нет.
   Правда лежит между ними по ЦЕНЕ, но НЕ по составу: отметки не видят
   ни касания внутри часа, после которого позиция отскочила (ядро
   режет — отметки молчат), ни хвоста, родившегося в последний час
   (ядро режет — а час выхода в счёт не идёт). Поэтому потолок по
   отметкам не является границей убийцы (А) ни сверху, ни снизу, и
   вердикт по нему помечен предварительным.

   Уровень пола считается ФОРМУЛОЙ ЯДРА (`ladder.liq_price` +
   `ladder.open_mark`) от собственных чисел позиции, а не плоскими
   −25 % маржи: доля съеденной маржи на полу зависит от плеча
   (у 3× это ≈ −24 %, у 25× ≈ −12 %), и плоский порог торговал бы
   другим правилом. Вывод сверяется с записью: у позиций, кончившихся
   ликвидацией, выведенная цена ликвидации обязана совпасть с
   `exit_px` самой записи — расхождение печатается числом.

2. **Реплей ядром** (`--replay`, одна ячейка, сотни секунд, через
   очередь заданий). Пол ставится параметром симуляции на время
   прогона и возвращается обратно — тем же способом, что у
   `short_stop.py`, — и только он видит касание внутри бара, цену
   закрытия бара пореза и хвост, проходящий пол РАЗРЫВОМ. Записи
   сестры живут в СВОЁМ кэше со СВОЕЙ подписью (пол входит в подпись):
   правило, меняющее исход позиции, обязано войти в подпись, иначе кэш
   базовой книги отдал бы прогону исходы другой книги молча.

Касса — та же, что у книги: возраст → охрана → раздача денег →
издержки → форма (`run_paper`), и равенство кассе семейства
(`short_grid.cell_stats`) на общих полях закреплено проверкой. Своего
счёта денег здесь нет вовсе.

Чего здесь НЕТ и быть не может: форварда. У необъявленной сестры
форвардных суток ноль, поэтому убийца (Г) — прочерк с причиной, а не
вердикт. Окно с даты правил семейства считается и печатается, но оно
ПЕРЕСЧЁТ, а не наблюдение, и помечено так.

Запуск:

    run research/mech_374e2591/floor_sister.py                 # потолок
    run research/mech_374e2591/floor_sister.py --replay        # ядром

Смоук: `--limit 400 --seeds 8 --no-publish`.
"""
import argparse
import calendar
import collections
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
CACHE_DIR = os.path.join(HERE, "cache")
for _rel in ("research/dca_paper", "research", "research/a1_universe",
             "research/dca_ladder", "research/s8_loop", "research/factory"):
    _p = os.path.join(ROOT, _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import short_stop as SS                                       # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import path_screen as P                                       # noqa: E402
import wave_guard as WG                                       # noqa: E402
import wave as WV                                             # noqa: E402
import tail_screen as T                                       # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import run_d2 as D2                                           # noqa: E402
import ladder as L                                            # noqa: E402
import pool as PL                                             # noqa: E402

ART = "FLOOR-sister"
MECH = "374e2591"
# --- назначено ЗАДАНИЕМ, а не этим файлом --------------------------------
BOOK = "safe_h"                     # книга вердикта: безопасная короткая
RULER = S.BOOKS[BOOK]               # линейка, на которой считается позиция
DEP = 10000.0                       # депозит вердикта
FLOOR_KEY = "f75"                   # ячейка объявленной оси пола
# --- взято у объявленных источников, а не назначено здесь ----------------
FLOOR = dict(SS.FLOORS)[FLOOR_KEY]          # доля пола сестры — ось short_stop
BASE_FLOOR = R.floor_frac_of(BOOK, D2.FLOOR_FRAC)   # пол базовой книги
GUARD = R.wave_guard_of(BOOK)               # порог охраны — у книги
AGE_D = R.min_age_days(BOOK)                # порог возраста имени — у книги
SEEDS = P.SEEDS                             # 200 зёрен контроля
EXIT = "пол"                                # метка исхода — та же, что у ядра
TAIL_EXITS = T.TAIL_EXITS                   # хвостовые исходы — у скрина хвоста
# --- пороги убийц, объявленные ЗАДАНИЕМ до прогона -----------------------
# (А) худший день сестры не глубже этой доли худшего дня базовой книги.
# Доля, а не доллары: число −540 $ в задании ВЫВЕДЕНО из −811 $ базовой,
# и записанное литералом оно молча состарилось бы вместе с записью.
WORST_SHARE = 2.0 / 3.0
# (Б) доля зёрен, при которой случайные выходы убивают правило.
BEAT_MAX = 0.05
# (Г) суток со сделками, начиная с которых судит правило формы пула.
MIN_FWD_DAYS = 10
# Сколько долей маржи считать расхождением при сверке цены ликвидации.
LIQ_TOL_BP = 1.0                    # б.п. цены; больше — расхождение
HOUR = 3600.0
EPS = 1e-9


def _quiet(*_a):
    pass


def log_line(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


# --- уровень пола: формулой ядра от чисел самой позиции -------------------

def floor_level(rec, frac=None):
    """Цена пола и pnl на ней для ОДНОЙ записи. Не посчитать — причина.

    Возвращает `{"p_liq", "px", "pnl", "mmr", "flat"}` либо
    `{"why": …}`. Второй формулы здесь нет: цену ликвидации даёт
    `ladder.liq_price`, переоценку на цене — `ladder.open_mark`, а сам
    пол есть строка ядра `floor_px = p_liq + доля · (вход − p_liq)`
    (`ladder.simulate_dca`). Капитал позиции в записи равен единице
    (`run_d6.one_position` зовёт симуляцию с `capital = 1.0`), доли
    рунгов лежат в `fills`, и заполненный нотионал обязан сойтись с
    полем `filled` — не сошёлся, значит запись описывает другую
    позицию, и считать по ней пол нельзя.

    Ставка поддерживающей маржи берётся ТЕМ ЖЕ справочником, что у
    реплея (`rules.mmr_look` на нотионале `1.0 · плечо`); тиров у имени
    нет — ядро ставит плоскую ставку, и такие записи считаются
    отдельным числом, а не молчат.
    """
    frac = FLOOR if frac is None else float(frac)
    try:
        avg = float(rec["avg"])
        entry = float(rec["entry_px"])
        lev = float(rec["lev"])
        ws = [float(f[2]) for f in (rec.get("fills") or [])]
    except (KeyError, TypeError, ValueError, IndexError):
        return {"why": "в записи нет входа, плеча или рунгов"}
    if not (avg > 0 and entry > 0 and lev > 0 and ws):
        return {"why": "вход, плечо или доли рунгов не положительны"}
    cash = lev * sum(ws)
    filled = rec.get("filled")
    if filled is not None and abs(float(filled) - cash) > 1e-6 * max(1.0, cash):
        return {"why": "заполненный нотионал записи не сходится с рунгами"}
    tiers = (R.risk_tiers() or {}).get(str(rec.get("sym") or "").upper()) or []
    mmr = float(R.mmr_look(rec.get("sym"))(cash))
    p_liq = float(L.liq_price(avg, cash / avg, 1.0, mmr, "short"))
    if not p_liq > 0:
        return {"why": "цена ликвидации не посчитана"}
    px = p_liq + frac * (entry - p_liq)
    pnl = L.open_mark(px, avg, 1.0, lev, ws, "short")
    if pnl is None:
        return {"why": "переоценка на полу не посчитана"}
    return {"p_liq": p_liq, "px": float(px), "pnl": float(pnl), "mmr": mmr,
            "flat": not tiers}


def levels_of(views, frac=None):
    """Уровни пола по записям: {ключ: pnl пола} и диагностика.

    Уровень, который не отрицателен, правилом не является: пол стоит
    ПРОТИВ позиции, и положительный «пол» резал бы прибыльную сделку.
    Такая запись выбывает с названной причиной, а не считается нулём.
    """
    out, why = {}, collections.Counter()
    flat, liq = 0, {}
    for key, v in views.items():
        got = floor_level(v["rec"], frac)
        if got.get("why"):
            why[got["why"]] += 1
            continue
        if not got["pnl"] < 0:
            why["уровень пола не отрицателен"] += 1
            continue
        out[key] = got["pnl"]
        liq[key] = got["p_liq"]
        flat += 1 if got["flat"] else 0
    return out, {"n": len(out), "why": dict(why), "flat_mmr": flat,
                 "p_liq": liq}


def liq_check(views, p_liq, tol_bp=LIQ_TOL_BP):
    """Сверка выведенной ликвидации с записью — калибровка вывода.

    У позиции, кончившейся ликвидацией, ядро записало цену выхода
    РОВНО ценой ликвидации (`simulate_dca`: `exit_px = p_liq`). Значит
    выведенная здесь цена обязана совпасть с ней; расхождение означает,
    что уровень пола выведен не из той позиции, и молчать об этом
    нельзя — из него считается ВСЁ правило.
    """
    n, bad, worst = 0, 0, None
    for key, v in views.items():
        r = v["rec"]
        if r.get("exit") != "ликвидация" or key not in p_liq:
            continue
        e = float(r.get("exit_px") or 0.0)
        if not e > 0:
            continue
        n += 1
        d = abs(p_liq[key] / e - 1.0) * 1e4
        worst = d if worst is None else max(worst, d)
        if d > float(tol_bp):
            bad += 1
    return {"n": n, "bad": bad, "worst_bp": (None if worst is None
                                             else round(worst, 3)),
            "tol_bp": float(tol_bp),
            "why": (None if n else "ликвидаций в выборке нет — сверять нечем")}


# --- срез позиции полом ---------------------------------------------------

def views_of(cache, ruler=RULER, limit=None):
    """Лёгкие виды закрытых записей линейки: путь ядра и хвостовой исход.

    Путь берётся у `wave.path_of` (отметки ядра), хвост — у
    `tail_screen.is_tail`: обе меры уже есть в проекте, и вторая их
    копия однажды разошлась бы с книгой.
    """
    out, no_marks = {}, 0
    keys = sorted((k for k, r in cache.items()
                   if k[0] == ruler and (r.get("state") or "closed") == "closed"),
                  key=lambda k: k[2])
    if limit:
        keys = keys[-int(limit):]
    for key in keys:
        r = cache[key]
        p = WV.path_of(r)
        if not p:
            no_marks += 1
            continue
        out[key] = {"rec": r, "tail": T.is_tail(r), "path": p}
    return out, no_marks


def hits(views, levels):
    """Час пореза каждой позиции: {ключ: час} — осью `path_screen`.

    Час ищет `path_screen.trigger` осью «стоп по убытку» на СВОЁМ
    уровне позиции: та же функция, тот же порядок и то же правило
    «строго до фактического выхода», которыми считаются все оси выхода
    коротких книг. Своего обхода пути здесь нет — обход, смотрящий на
    час выхода, и есть заглядывание в будущее.
    """
    out = {}
    for key, v in views.items():
        lvl = levels.get(key)
        if lvl is None:
            continue
        k = P.trigger(v, "loss", -lvl)
        if k is not None:
            out[key] = k
    return out


def cut_record(rec, k, pnl=None, why=EXIT):
    """Запись, срезанная полом на часе k. Цена выхода — двумя способами.

    `pnl=None` — порез ПО ОТМЕТКЕ: запись закрывается отметкой ядра за
    час k, ровно как это делает охрана рынком (`wave.guard_record`), и
    второго среза здесь не заводится.

    Число — порез ПО УРОВНЮ: отметка часа k подменяется уровнем пола,
    после чего работает тот же срез. Это верхняя оценка: ядро режет по
    ЗАКРЫТИЮ бара, на котором цена дошла до пола, и разрыв внутри бара
    уводит исход ниже уровня. Подменяется РОВНО последнее приращение
    среза, приращения после часа k выбрасываются вместе с хвостом
    записи — будущее в цену выхода не заглядывает.
    """
    if pnl is None:
        return WV.guard_record(rec, k, why=why)
    at = float(rec["at"])
    mk = [list(m) for m in (rec.get("marks") or [])
          if int(round((float(m[0]) - at) / HOUR)) + 1 <= k]
    if not mk:
        return WV.guard_record(rec, k, why=why)
    cum = sum(float(m[1]) for m in mk)
    mk[-1][1] = float(mk[-1][1]) + (float(pnl) - cum)
    return WV.guard_record(dict(rec, marks=mk), k, why=why)


def apply_floor(cache, changed, levels=None):
    """Кэш, в котором сработавшие позиции срезаны полом.

    `levels=None` — порез по отметке, карта уровней — порез по уровню.
    Охрана рынком здесь НЕ применяется: её накладывает касса книги
    (`run_paper.guard_shorts`) тем же кодом, что у прогона. Порядок от
    этого выходит правильным сам: срезанная запись живёт до часа
    пореза, и охрана может сработать только РАНЬШЕ него, а ничья
    остаётся за полом — он срабатывает внутри часа, а охрана по его
    закрытию.
    """
    mod = dict(cache)
    for key, k in changed.items():
        mod[key] = cut_record(cache[key], k,
                              None if levels is None else levels.get(key))
    return mod


# --- касса книги: те же функции и тот же порядок --------------------------

def in_window(rows, since):
    """Строки, вышедшие не раньше `since`. Окно — ПОКАЗ, а не счёт."""
    if since is None:
        return list(rows)
    return [r for r in rows if float(r.get("exit_ts") or 0) >= float(since)]


def book_form(cache, ctx, launch, dep=DEP, book=BOOK, now=None, log=_quiet,
              mkt=None, since=None):
    """Форма книги на этих записях — ТЕМИ ЖЕ функциями, что касса.

    Порядок ровно как у кассы семейства (`short_grid.cell_stats`):
    возраст имени → охрана рынком → раздача денег → издержки → форма.
    Зачем не сама касса: её ячейка не отдаёт колонок концентрации
    («без лучшего имени», «без 3 лучших дней», просадка без худшего
    дня), укуса и худшего дня, а спор заявки идёт ровно о них.
    Считает их `run_paper._stats` — одной формулой на весь проект, — и
    равенство кассе на общих полях закреплено проверкой
    `форма_равна_кассе`: разойдись они, сюита падает, и вторая касса не
    заведётся молча. Дописать поля в `short_grid.py` нельзя: публикация
    постройки несёт только свой каталог, и правка чужого файла осталась
    бы на сервере.

    `since` — окно ПОКАЗА, а не счёта: строки фильтруются ПОСЛЕ кассы.
    Урезать можно то, что отдаёшь, но не то, на чём считаешь: деньги,
    занятые позицией вне окна, кассе внутри окна недоступны, и счёт
    есть функция от всей истории.
    """
    packed = AG.packed_short(cache)
    recs, ages = RP.age_shorts(packed.get(book) or [], book, launch=launch,
                               log=log, now=now)
    recs, guard = RP.guard_shorts(recs, book, log=log, now=now, mkt=mkt)
    rows, cells, _one, _live = RP.build_rows({book: recs}, now=now,
                                             keys=[book], log=log)
    mine = [r for r in rows if R.ruler_of(r) == book
            and int(r.get("dep", 0)) == int(dep)]
    if ctx is not None and not ctx.get("error"):
        mine, _c = CO.apply_to_rows(mine, ctx)
    mine = in_window(mine, since)
    st = RP._stats(mine, dep)
    if st is None:
        return None
    c = cells.get(RP._cell(book, dep)) or {}
    fin, dd = st.get("final"), st.get("max_dd")
    ex, usd = collections.Counter(), collections.defaultdict(float)
    for r in mine:
        ex[r.get("exit") or "—"] += 1
        usd[r.get("exit") or "—"] += float(r.get("usd") or 0.0)
    daily = {}
    for r in mine:
        d = PL.day_no(float(r["exit_ts"]))
        daily[d] = daily.get(d, 0.0) + float(r["usd"])
    return dict(st, taken=c.get("taken"), no_cash=c.get("no_cash"),
                offered=c.get("offered"), ages=ages, guard=guard,
                ratio=(None if not fin or not dd
                       else round(float(fin) / abs(float(dd)), 2)),
                exits={k: {"n": v, "usd": round(usd[k], 2)}
                       for k, v in ex.items()},
                daily_no={int(k): round(v, 4) for k, v in daily.items()})


def columns(st, dep=DEP):
    """Колонки спора из формы книги. Чего нет — ПРОЧЕРК, а не ноль.

    Все величины берутся у `run_paper._stats`, то есть посчитаны там
    же, где деньги книги; здесь только выбор полей и перевод долей
    депозита в доллары — ноль на месте неизмеренного читался бы как
    «измерено и равно нулю».
    """
    if not st:
        return None
    out = {k: st.get(k) for k in ("n", "usd", "final", "max_dd", "ratio",
                                  "win", "day_median", "day_green", "bite",
                                  "day_worst", "worst_day", "top_day",
                                  "top_sym", "usd_wo_top", "usd_wo_top3d",
                                  "max_dd_wo_worst", "days", "taken",
                                  "no_cash", "exits", "daily_no")}
    out["day_median_usd"] = (None if st.get("day_median") is None
                             else round(float(st["day_median"]) * dep, 2))
    out["day_worst_usd"] = (None if st.get("day_worst") is None
                            else round(float(st["day_worst"]) * dep, 2))
    out["tails"] = sum(int((st.get("exits") or {}).get(e, {}).get("n") or 0)
                       for e in TAIL_EXITS)
    return out


# --- вердикты: фраза выводится из числа -----------------------------------

def verdict_worst(base, sis, share=WORST_SHARE):
    """Убийца (А): худший день сестры против доли худшего дня базовой."""
    bw = (base or {}).get("day_worst_usd")
    sw = (sis or {}).get("day_worst_usd")
    if bw is None or sw is None:
        return {"key": "А", "dead": None,
                "why": "худший день не измерен ни у одной из книг"}
    thr = float(share) * float(bw)
    dead = float(sw) <= thr
    return {"key": "А", "dead": bool(dead), "thr": round(thr, 2),
            "base": float(bw), "sister": float(sw),
            "why": (f"худший день сестры {sw:+.0f} $ ({sis.get('worst_day')}) "
                    f"против {bw:+.0f} $ ({base.get('worst_day')}) у базовой; "
                    f"порог {thr:+.0f} $ = {share:.2f} худшего дня базовой — "
                    + ("МЕРТВА: порез хвост не ограничил"
                       if dead else "жива: порез ограничил хвост"))}


def verdict_control(beat, seeds, n_changed, max_beat=BEAT_MAX):
    """Убийца (Б): Σ приращения pnl против случайных выходов."""
    if beat is None:
        return {"key": "Б", "dead": None,
                "why": ("контроль не посчитан: правило не сработало ни разу"
                        if not n_changed else "контроль не посчитан")}
    dead = float(beat) >= float(max_beat)
    return {"key": "Б", "dead": bool(dead), "beat": float(beat),
            "why": (f"случайные выходы того же числа ({n_changed}) в те же "
                    f"часы не хуже правила в {100 * float(beat):.1f} % из "
                    f"{int(seeds)} зёрен при пороге {100 * max_beat:.0f} % — "
                    + ("МЕРТВА: правило лишь укорачивает сделки"
                       if dead else "жива: выбор часа не случаен"))}


def verdict_shape(sis):
    """Убийца (В): обычный день и «без 3 лучших дней» у сестры."""
    med = (sis or {}).get("day_median_usd")
    wo3 = (sis or {}).get("usd_wo_top3d")
    if med is None:
        return {"key": "В", "dead": None, "why": "медиана дня не измерена"}
    if wo3 is None:
        return {"key": "В", "dead": bool(med < 0),
                "med": med, "wo3": None,
                "why": (f"медиана дня {med:+.0f} $; «без 3 лучших дней» не "
                        "измерено (суток меньше четырёх) — "
                        + ("МЕРТВА по медиане" if med < 0
                           else "по медиане жива, вторая половина убийцы "
                                "не измерена"))}
    dead = (med < 0) or (float(wo3) < 0)
    return {"key": "В", "dead": bool(dead), "med": med, "wo3": float(wo3),
            "why": (f"медиана дня {med:+.0f} $, «без 3 лучших дней» "
                    f"{float(wo3):+.0f} $ — "
                    + ("МЕРТВА: прибавка пришла эпизодом"
                       if dead else "жива: день обычный, эпизодом не живёт"))}


def verdict_forward(fwd_days, min_days=MIN_FWD_DAYS):
    """Убийца (Г): форвард. У необъявленной сестры его НЕТ.

    Прочерк с названной причиной, а не «жива»: отсутствие меры не есть
    прохождение.
    """
    if not fwd_days:
        return {"key": "Г", "dead": None, "days": 0,
                "why": ("форвардных суток у сестры ноль: книга не объявлена, "
                        "и все её сутки — пересчёт по прошлому. Правило формы "
                        "пула судит запись ВПЕРЁД, поэтому вердикта нет")}
    if int(fwd_days) < int(min_days):
        return {"key": "Г", "dead": None, "days": int(fwd_days),
                "why": (f"суток со сделками {int(fwd_days)} при пороге "
                        f"{int(min_days)} — не измерено")}
    return {"key": "Г", "dead": None, "days": int(fwd_days),
            "why": "форвард судится правилом формы пула вне этого замера"}


def verdicts(base, sis, beat, seeds, n_changed, fwd_days=0):
    """Все объявленные убийцы — по порядку, фразами из чисел."""
    return [verdict_worst(base, sis), verdict_control(beat, seeds, n_changed),
            verdict_shape(sis), verdict_forward(fwd_days)]


def summary_of(vs, step):
    """Одна строка итога: мертва — по каким убийцам, иначе по каким жива."""
    dead = [v["key"] for v in vs if v.get("dead")]
    alive = [v["key"] for v in vs if v.get("dead") is False]
    unknown = [v["key"] for v in vs if v.get("dead") is None]
    if dead:
        head = "МЕХАНИКА МЕРТВА по убийце " + ", ".join(dead)
    elif alive:
        head = "ни один посчитанный убийца не сработал (жива по " \
               + ", ".join(alive) + ")"
    else:
        head = "не посчитано ни одного убийцы"
    if unknown:
        head += "; не измерено: " + ", ".join(unknown)
    return f"{head} — {step}"


# --- шаг 1: потолок по почасовым отметкам ---------------------------------

def run_marks(seeds=SEEDS, limit=None, log=log_line, now=None, ctx=None,
              launch=None, cache=None, mkt=None, frac=None):
    """Потолок: пол по отметкам ядра, два варианта цены, контроль.

    Ноль сработавших при непустом входе есть ОТКАЗ, а не результат:
    правило, не срабатывающее ни разу, не имеет ни денег, ни контроля,
    и отчёт с прочерками на его месте выглядел бы работой.
    """
    t0 = time.time()
    frac = FLOOR if frac is None else float(frac)
    if cache is None:
        cache, why = S.read_cache(log=log)
        if why:
            return {"error": f"кэш реплея непригоден: {why}"}
    if not cache:
        return {"error": "кэш реплея пуст: считать нечего"}
    ctx = CO.context() if ctx is None else ctx
    launch = IR.launches() if launch is None else launch
    views, no_marks = views_of(cache, limit=limit)
    if not views:
        return {"error": f"закрытых записей линейки {RULER} нет "
                         f"(записей в кэше {len(cache)}, без отметок "
                         f"{no_marks})"}
    levels, ldiag = levels_of(views, frac)
    if not levels:
        return {"error": "уровень пола не посчитан ни у одной записи: "
                         + "; ".join(f"{k} — {v}"
                                     for k, v in (ldiag["why"] or {}).items())}
    lq = liq_check(views, ldiag.pop("p_liq"))
    log(f"записей {len(views)} (без отметок {no_marks}), уровень пола "
        f"посчитан у {len(levels)}, плоская ставка mmr у {ldiag['flat_mmr']}; "
        f"сверка ликвидации: расхождений {lq['bad']} из {lq['n']}")
    changed = hits(views, levels)
    if not changed:
        return {"error": f"пол {frac:g} не сработал НИ РАЗУ на {len(views)} "
                         "записях: при непустом входе это отказ, а не "
                         "результат"}
    by_exit = collections.Counter(views[k]["rec"].get("exit") or "—"
                                  for k in changed)
    delta = P.deltas(cache, views, changed)
    log(f"пол {frac:g} сработал у {len(changed)} записей "
        f"(хвостовых {delta['tails']}, срезано в минус {delta['cut_worse']}), "
        f"Σ долей маржи {delta['sum']:+.2f}")
    base = book_form(cache, ctx, launch, now=now, log=_quiet, mkt=mkt)
    mark = book_form(apply_floor(cache, changed), ctx, launch, now=now,
                     log=_quiet, mkt=mkt)
    lvl = book_form(apply_floor(cache, changed, levels), ctx, launch, now=now,
                    log=_quiet, mkt=mkt)
    cb, cm, cl = columns(base), columns(mark), columns(lvl)
    log(f"база: {cb['usd']:+.0f} $, просадка {100 * cb['max_dd']:+.1f} %, "
        f"худший день {cb['day_worst_usd']:+.0f} $ ({cb['worst_day']}); "
        f"сестра по отметке {cm['usd']:+.0f} $, худший день "
        f"{cm['day_worst_usd']:+.0f} $ ({cm['worst_day']})")
    ctl, beat = None, None
    if seeds:
        log(f"контроль: {int(seeds)} зёрен случайных выходов того же числа "
            "в те же часы среди открытых")
        ctl = P.control_exits(cache, views, changed, ctx, launch, seeds=seeds,
                              dep=DEP, now=now, log=log)
        # Судится Σ ПО ОТМЕТКЕ: случайные выходы тоже считаются отметками,
        # и сравнивать их с порезом по уровню значило бы дать правилу
        # фору, которой у контроля нет.
        beat = AG.beat_share([{"sum": x} for x in (ctl.get("sum") or [])],
                             delta["sum"], "sum")[0]
    vs = verdicts(cb, cm, beat, seeds, len(changed))
    return {"n_views": len(views), "no_marks": no_marks, "levels": ldiag,
            "limit": (int(limit) if limit else None),
            "liq_check": lq, "frac": frac,
            "level_stats": _quant([levels[k] for k in levels]),
            "changed": {"n": len(changed), "tails": delta["tails"],
                        "cut_worse": delta["cut_worse"],
                        "by_exit": dict(by_exit),
                        "hours": _quant([float(k) for k in changed.values()])},
            "delta": delta, "control": _ctl_stats(ctl), "beat": beat,
            "seeds": int(seeds),
            "base": cb, "sister_mark": cm, "sister_level": cl,
            "days": WG.day_diff(base.get("days_rows"), mark.get("days_rows")),
            "verdicts": vs, "summary": summary_of(vs, "потолок по отметкам"),
            "window": _window_of(cache, ctx, launch, changed, levels, now, mkt),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _quant(xs):
    """Квантили ряда — прочерк, а не ноль, когда ряда нет."""
    xs = sorted(float(x) for x in xs if x is not None)
    if not xs:
        return {"n": 0, "med": None, "q05": None, "q95": None}
    q = lambda p: xs[min(len(xs) - 1, max(0, int(p * (len(xs) - 1))))]  # noqa: E731
    return {"n": len(xs), "med": round(q(0.5), 4), "q05": round(q(0.05), 4),
            "q95": round(q(0.95), 4)}


def _ctl_stats(ctl):
    if not ctl:
        return None
    return {"sum": _quant(ctl.get("sum") or []),
            "tails": _quant(ctl.get("tails") or []),
            "no_cand": ctl.get("no_cand")}


def _window_of(cache, ctx, launch, changed, levels, now, mkt):
    """Окно с даты правил семейства: ПЕРЕСЧЁТ, а не наблюдение.

    Считается потому, что оба дня, породившие заявку, лежат в нём, а
    помечается пересчётом потому, что сестра не объявлена: решения
    записаны не вперёд, и назвать это форвардом значило бы выдать
    бэктест за наблюдение.
    """
    since = R.family_since(BOOK)
    if not since:
        return {"why": "у семейства книги нет даты смены правил"}
    ts = calendar.timegm(time.strptime(since, "%Y-%m-%d"))
    base = book_form(cache, ctx, launch, now=now, log=_quiet, mkt=mkt,
                     since=ts)
    sis = book_form(apply_floor(cache, changed), ctx, launch, now=now,
                    log=_quiet, mkt=mkt, since=ts)
    return {"since": since, "base": columns(base), "sister": columns(sis),
             "forward": False,
             "why": "решения записаны не вперёд: сестра не объявлена"}


# --- шаг 2: реплей ядром --------------------------------------------------

def sister_sig(frac=None):
    """Подпись кэша СЕСТРЫ: подпись семейства плюс её собственный пол.

    Пол меняет ИСХОД позиции, поэтому обязан войти в подпись: кэш, не
    знающий про смену пола, отдал бы прогону исходы другой книги молча.
    Записи сестры лежат в своём файле — кэш базовой книги они не трогают
    ни при каком исходе прогона.
    """
    frac = FLOOR if frac is None else float(frac)
    sig = dict(S.cache_sig())
    sig["floor"] = dict(sig.get("floor") or {}, **{BOOK: float(frac)})
    sig["sister"] = f"{MECH}:{BOOK}:{FLOOR_KEY}"
    return sig


def cache_path(frac=None):
    frac = FLOOR if frac is None else float(frac)
    return os.path.join(CACHE_DIR, f"recs-floor{int(round(100 * frac)):d}.jsonl")


def read_sister_cache(frac=None, log=_quiet):
    path = cache_path(frac)
    cache, why = RP.read_cache(path, sig=sister_sig(frac))
    if why:
        log(f"кэш сестры не используется: {why}")
    out = {}
    for (pair, sym, at), r in cache.items():
        rk = pair[0] if isinstance(pair, (list, tuple)) else pair
        out[(rk, sym, at)] = r
    return out, why


def write_sister_cache(cache, frac=None):
    path = cache_path(frac)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    RP.write_cache({((rk,), sym, at): r for (rk, sym, at), r in cache.items()},
                   path=path, sig=sister_sig(frac))
    return path


def need_legs(cache, legs_):
    """Решения, которых в кэше сестры нет либо они ещё не закрыты."""
    out = []
    for g in legs_:
        r = cache.get((RULER, g["sym"], round(float(g["at"]), 3)))
        if r is None or r.get("state") != "closed":
            out.append(g)
    return out


def replay_floor(legs_, frac=None, src=None, log=log_line):
    """Реплей ядром с ЧУЖИМ полом — тем же способом, что у `short_stop`.

    Пол есть глобальный параметр симуляции, а не ключ ячейки, поэтому
    он ставится на время прогона и возвращается обратно в `finally`.
    Оставленный глобально, он сделал бы соседний замер другим замером
    молча — и именно этим соседом здесь является ЖИВАЯ книга.
    """
    frac = FLOOR if frac is None else float(frac)
    was = D2.FLOOR_FRAC
    try:
        D2.FLOOR_FRAC = float(frac)
        log(f"пол капитуляции на время реплея {frac:g} "
            f"(≈ съедено {100 * SS.eaten(frac):.0f} % маржи), было {was:g}")
        got = G.replay(legs_, [S.CELL], src=src, log=log)
    finally:
        D2.FLOOR_FRAC = was
    out = {}
    for r in ((got.get("recs") or {}).get(RULER) or {}).get(S.CELL[0]) or []:
        out[(RULER, r["sym"], round(float(r["at"]), 3))] = r
    return out, got


def gap_of(views, levels):
    """Насколько исход хвоста ПРОШЁЛ пол разрывом внутри бара.

    Ядро режет по ЗАКРЫТИЮ бара, на котором цена дошла до пола, а не по
    самому полу: разрыв не держит на уровне. Разность «исход минус
    уровень» и есть цена разрыва; отрицательная — позиция ушла ниже
    пола. Ликвидация считается отдельно: она означает, что цена прошла
    сквозь пол целиком.
    """
    gaps, below, liq, n = [], 0, 0, 0
    for key, v in views.items():
        r = v["rec"]
        if r.get("exit") not in TAIL_EXITS or key not in levels:
            continue
        n += 1
        if r.get("exit") == "ликвидация":
            liq += 1
        d = float(r["pnl"]) - float(levels[key])
        gaps.append(d)
        below += 1 if d < -EPS else 0
    return {"n": n, "below": below, "liq": liq,
            "share": (round(below / n, 3) if n else None),
            "gap": _quant(gaps),
            "why": (None if n else "хвостовых исходов у сестры нет — "
                                   "мерить разрыв не на чем")}


def replay_changed(base_cache, sister, base_views):
    """Позиции, чей исход изменил ПОЛ, и час их выхода — для контроля.

    Пол умеет только УКОРАЧИВАТЬ позицию: путь цены у сестры и у базовой
    книги один и тот же, и все прочие исходы (тейк, срок, ликвидация,
    рынок) наступают в тот же час. Значит изменённая позиция — та, что
    вышла РАНЬШЕ, и её час есть час пореза.

    Час, которого нет в записи базовой книги (позиция там уже закрыта),
    в контроль не идёт: случайный выход надо разыгрывать среди тех, кто
    в этот час ОТКРЫТ, и час вне записи такого выбора не даёт. Число
    таких считается, а не молчит.
    """
    out, why = {}, collections.Counter()
    for key, r in sister.items():
        b = base_cache.get(key)
        if b is None:
            why["решения нет в кэше базовой книги"] += 1
            continue
        if float(r["exit_ts"]) >= float(b["exit_ts"]):
            continue
        p = (base_views.get(key) or {}).get("path")
        k = int((float(r["exit_ts"]) - float(r["at"])) // HOUR) + 1
        if not p or not 1 <= k < p["K"]:
            why["час пореза вне записи базовой"] += 1
            continue
        out[key] = k
    return out, dict(why)


def replay_delta(base_cache, sister, changed):
    """Σ приращения pnl (долей маржи) по изменённым позициям — по ИСХОДУ.

    У шага 2 исход сестры есть настоящий исход ядра, а не отметка часа,
    поэтому сумма считается разностью исходов. У контроля отметки —
    других цен у него нет, — и это асимметрия, которую надо называть: у
    правила цена выхода внутри бара, у случайного выхода — на границе
    часа.

    «Хвостовых» считается по записи БАЗОВОЙ книги, а не сестры: у сестры
    порезанная позиция всегда кончается полом, то есть всегда хвостовым
    исходом, и такое число равнялось бы числу порезов тождественно —
    оно выглядело бы мерой, ничего не меря. Вопрос же стоит обратный:
    сколько из перехваченных позиций были хвостом БЕЗ пола.
    """
    d, tails = 0.0, 0
    for key in changed:
        d += float(sister[key]["pnl"]) - float(base_cache[key]["pnl"])
        tails += 1 if T.is_tail(base_cache[key]) else 0
    return {"sum": d, "n": len(changed), "tails": tails}


def run_replay(limit=None, seeds=SEEDS, log=log_line, now=None, ctx=None,
               launch=None, src=None, frac=None, legs_=None, mem_limit=None,
               mkt=None, base_cache=None, replay=None):
    """Реплей ядром: сестра на своих исходах рядом с базовой книгой.

    Базовая книга берётся из ЖИВОГО кэша семейства на тех же решениях:
    её исходы посчитаны тем же ядром с её собственным полом, и считать
    их второй раз значило бы платить за ответ, который уже есть. Число
    решений, которых в живом кэше не нашлось, печатается, а не молчит.
    """
    t0 = time.time()
    frac = FLOOR if frac is None else float(frac)
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    ctx = CO.context() if ctx is None else ctx
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        return {"error": "коротких решений на листе нет"}
    cache, _why = read_sister_cache(frac, log=log)
    need = need_legs(cache, legs_)
    log(f"решений {len(legs_)}, в кэше сестры {len(cache)}, "
        f"считаю заново {len(need)}")
    fresh, got = ({}, {})
    if need:
        fresh, got = (replay or replay_floor)(need, frac=frac, src=src, log=log)
        cache.update(fresh)
        write_sister_cache(cache, frac)
    if not cache:
        return {"error": "реплей не дал ни одной записи сестры"}
    if base_cache is None:
        base_cache, why = S.read_cache(log=log)
        if why:
            return {"error": f"кэш базовой книги непригоден: {why}"}
    views, no_marks = views_of(cache, limit=None)
    if not views:
        return {"error": f"закрытых записей сестры нет (в кэше {len(cache)}, "
                         f"без отметок {no_marks})"}
    levels, ldiag = levels_of(views, frac)
    ldiag.pop("p_liq", None)
    # База — те же решения из живого кэша. Позиции, которых там нет,
    # считаются числом: сравнение по разным составам не есть сравнение.
    same = {k: base_cache[k] for k in views if k in base_cache}
    missing = len(views) - len(same)
    base = book_form(base_cache, ctx, launch, now=now, log=_quiet, mkt=mkt)
    base_same = book_form(same, ctx, launch, now=now, log=_quiet, mkt=mkt)
    sis = book_form(cache, ctx, launch, now=now, log=_quiet, mkt=mkt)
    cb, cbs, cs = columns(base), columns(base_same), columns(sis)
    ex = collections.Counter(v["rec"].get("exit") or "—"
                             for v in views.values())
    # Контроль убийцы (Б): случайные выходы того же числа в те же часы
    # среди открытых — тот же розыгрыш, что у осей выхода коротких книг.
    bviews, _nm = views_of(base_cache)
    changed, why_ch = replay_changed(base_cache, {k: v["rec"] for k, v
                                                  in views.items()}, bviews)
    delta = replay_delta(base_cache, {k: v["rec"] for k, v in views.items()},
                         changed)
    log(f"пол изменил исход у {delta['n']} позиций (хвостовых "
        f"{delta['tails']}), Σ долей маржи {delta['sum']:+.2f}")
    ctl, beat = None, None
    if seeds and changed:
        ctl = P.control_exits(base_cache, bviews, changed, ctx, launch,
                              seeds=seeds, dep=DEP, now=now, log=log)
        beat = AG.beat_share([{"sum": x} for x in (ctl.get("sum") or [])],
                             delta["sum"], "sum")[0]
    vs = verdicts(cbs or cb, cs, beat, seeds, delta["n"])
    return {"frac": frac, "legs": len(legs_), "replayed": len(fresh),
            "limit": (int(limit) if limit else None),
            "positions": len(cache), "no_marks": no_marks,
            "levels": ldiag, "missing_in_base": missing,
            "exits": dict(ex), "gap": gap_of(views, levels),
            "base": cb, "base_same": cbs, "sister": cs,
            "changed": dict(delta, why=why_ch), "seeds": int(seeds),
            "control": _ctl_stats(ctl), "beat": beat,
            "window": (got or {}).get("window"),
            "cache": os.path.relpath(cache_path(frac), ROOT),
            "verdicts": vs, "summary": summary_of(vs, "реплей ядром"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# --- отчёт ----------------------------------------------------------------

def _u(x, d=0):
    return "—" if x is None else f"{float(x):+,.{d}f}".replace(",", " ")


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _sh(x, d=1):
    """Доля — БЕЗ знака: у доли знака не бывает, а «+66 %» читается как
    прирост. Движение со знаком и доля без знака — разные величины
    (решение владельца 2026-09-02 о единицах показа)."""
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _n(x):
    return "—" if x is None else f"{x}"


COLS = (("usd", "$ всего", _u), ("final", "итог", _p),
        ("max_dd", "просадка", _p), ("ratio", "доход/просадка", None),
        ("day_median_usd", "медиана дня", _u),
        ("day_green", "зелёных суток", _sh),
        ("win", "прибыльных сделок", _sh),
        ("day_worst_usd", "худший день", _u), ("bite", "укус", None),
        ("usd_wo_top3d", "$ без 3 лучших дней", _u),
        ("usd_wo_top", "$ без лучшего имени", _u),
        ("max_dd_wo_worst", "просадка без худшего дня", _p),
        ("n", "сделок", None), ("taken", "взято кассой", None),
        ("tails", "хвостовых исходов", None))


def _cols_table(pairs):
    """Таблица «величина | книга | книга …» — колонки спора построчно."""
    L = ["| величина | " + " | ".join(t for t, _c in pairs) + " |",
         "|---|" + "--:|" * len(pairs)]
    for key, title, fn in COLS:
        cells = []
        for _t, c in pairs:
            v = (c or {}).get(key)
            cells.append(_n(v) if fn is None else fn(v))
        L.append(f"| {title} | " + " | ".join(cells) + " |")
    return L


def _exits_table(pairs):
    names = []
    for _t, c in pairs:
        for k in ((c or {}).get("exits") or {}):
            if k not in names:
                names.append(k)
    L = ["| исход | " + " | ".join(t for t, _c in pairs) + " |",
         "|---|" + "--:|" * len(pairs)]
    for nm in names:
        cells = []
        for _t, c in pairs:
            e = ((c or {}).get("exits") or {}).get(nm)
            cells.append("—" if not e else f"{e['n']} ({_u(e['usd'])} $)")
        L.append(f"| {nm} | " + " | ".join(cells) + " |")
    return L


def _verdict_lines(vs):
    L = ["| убийца | вердикт | из чего |", "|---|---|---|"]
    for v in vs or []:
        mark = ("МЕРТВА" if v.get("dead") else
                ("жива" if v.get("dead") is False else "не измерено"))
        L.append(f"| ({v['key']}) | **{mark}** | {v.get('why')} |")
    return L


def report(s):
    L = [f"# Пол капитуляции {FLOOR:g} у безопасной короткой книги h24: "
         "сестра книги `safe_h`", "",
         f"Заявка `{MECH}` предлагающего: сестра книги "
         f"«{R.ruler_title(BOOK)}» с ОДНИМ изменённым правилом — пол "
         f"капитуляции {FLOOR:g} вместо {BASE_FLOOR:g} (порез примерно при "
         f"{100 * SS.eaten(FLOOR):.0f} % съеденной маржи вместо "
         f"{100 * SS.eaten(BASE_FLOOR):.0f} %). Всё остальное то же: "
         f"линейка σ 6, билет 1×, возраст имени ≥ {AGE_D:g} суток, охрана "
         f"рынком ≥ {GUARD:g} %, срок {R.H24_HOLD_H} ч, доливов нет, деньги "
         f"НЕТТО, депозит ${int(DEP)}.", "",
         f"Доля пола взята у объявленной оси `short_stop.FLOORS[{FLOOR_KEY}]`, "
         "пороги охраны и возраста — у самой книги (`rules`), число зёрен "
         "контроля — у `path_screen.SEEDS`. Здесь не назначено ни одного "
         "числа правила.", ""]
    m = s.get("marks") or {}
    r = s.get("replay") or {}
    # Смоук обязан кричать, что он смоук: выборочные числа, поставленные
    # рядом с полными, через день становятся полными молча.
    for step, got in (("Шаг 1", m), ("Шаг 2", r)):
        if got.get("limit"):
            L += [f"> **{step} посчитан на ОГРАНИЧЕННОЙ выборке** "
                  f"(`--limit {got['limit']}`): числа предварительные и "
                  "книге целиком не равны.", ""]
    L += ["## Вердикт", ""]
    if m.get("summary"):
        L += [f"- **Шаг 1, потолок по отметкам** ({m.get('computed_at')}): "
              f"{m['summary']}."]
    elif m.get("error"):
        L += [f"- **Шаг 1 не посчитан:** {m['error']}."]
    else:
        L += ["- **Шаг 1 не считался.**"]
    if r.get("summary"):
        L += [f"- **Шаг 2, реплей ядром** ({r.get('computed_at')}): "
              f"{r['summary']}."]
    elif r.get("error"):
        L += [f"- **Шаг 2 не посчитан:** {r['error']}."]
    else:
        L += ["- **Шаг 2 (реплей ядром) не считался** — это он даёт вердикт "
              "по убийцам (А)–(В); потолок по отметкам их только "
              "предвосхищает. Команда: "
              "`run research/mech_374e2591/floor_sister.py --replay`."]
    L += [""]
    L += _step1(m) + _step2(r)
    L += ["## Чего замер не говорит", "",
          "- **Потолок по отметкам не есть граница убийцы (А).** Отметка "
          "ядра — переоценка на границе часа, а пол есть уровень ЦЕНЫ. "
          "Отметки не видят двух вещей сразу: касания внутри часа, после "
          "которого позиция отскочила (ядро режет — здесь тихо), и хвоста, "
          "родившегося в последний час (ядро режет — а час выхода в счёт не "
          "идёт по правилу «строго до фактического выхода»). Первое делает "
          "сестру ЛУЧШЕ, чем она есть, второе — ХУЖЕ, и какое сильнее, "
          "показывает только реплей ядром.",
          "- **Форварда у сестры нет.** Книга не объявлена, её сутки — "
          "пересчёт по прошлому, и убийца (Г) остаётся прочерком с "
          "названной причиной. Окно с даты правил семейства посчитано "
          "рядом, но помечено пересчётом.",
          "- **Веса модели видели эти часы:** лист решений тот же, что у "
          "живой книги, и вся запись читается как оценка СВЕРХУ.",
          "- Живого исполнения здесь нет: исходы считаются по барам записи, "
          "проскальзывание и очередь в стакане не моделируются; издержки "
          "круга вычтены той же кассой, что у книги.", ""]
    return "\n".join(L)


def _step1(m):
    if not m or m.get("error"):
        return []
    L = ["## Шаг 1. Потолок по почасовым отметкам", "",
         f"Закрытых записей линейки `{RULER}`: {m.get('n_views')} (без "
         f"отметок {m.get('no_marks')}). Уровень пола посчитан у "
         f"{(m.get('levels') or {}).get('n')} записей, плоская ставка "
         f"поддерживающей маржи (тиров у имени нет) у "
         f"{(m.get('levels') or {}).get('flat_mmr')}.", ""]
    lq = m.get("liq_check") or {}
    if lq.get("why"):
        L += [f"**Сверка вывода:** {lq['why']}.", ""]
    else:
        L += [f"**Сверка вывода с записью:** у {lq.get('n')} позиций, "
              "кончившихся ликвидацией, выведенная цена ликвидации сверена с "
              f"`exit_px` записи — расхождений больше {lq.get('tol_bp')} б.п. "
              f"{lq.get('bad')}, худшее {_n(lq.get('worst_bp'))} б.п. "
              "Уровень пола выводится из той же цены, поэтому сверка есть "
              "калибровка всего правила.", ""]
    ls = m.get("level_stats") or {}
    L += [f"**Где стоит пол.** Уровень {FLOOR:g} в долях маржи: медиана "
          f"{_n(ls.get('med'))}, края {_n(ls.get('q05'))} … "
          f"{_n(ls.get('q95'))}. Это не плоские −25 %: доля съеденной маржи "
          "на полу зависит от плеча (ликвидация у крупного плеча ближе, и "
          "четверть расстояния до неё стоит дешевле).", ""]
    ch = m.get("changed") or {}
    d = m.get("delta") or {}
    L += [f"**Сколько раз сработал.** {ch.get('n')} записей из "
          f"{m.get('n_views')} "
          f"({100.0 * (ch.get('n') or 0) / max(1, m.get('n_views') or 1):.1f} %), "
          f"из них хвостовых {ch.get('tails')}; в минус срезано "
          f"{ch.get('cut_worse')} позиций, которые без пола вышли лучше. "
          "Состав исходов, которые пол перехватил: "
          + ", ".join(f"{k} {v}" for k, v in
                      sorted((ch.get("by_exit") or {}).items(),
                             key=lambda kv: -kv[1]))
          + f". Час пореза: медиана {_n((ch.get('hours') or {}).get('med'))}, "
          f"края {_n((ch.get('hours') or {}).get('q05'))} … "
          f"{_n((ch.get('hours') or {}).get('q95'))}.", ""]
    ctl = m.get("control") or {}
    L += [f"**Σ приращения pnl** изменённых сделок (долей маржи, +1.00 = "
          f"спасена одна маржа): правило {_u(d.get('sum'), 2)}, случайные "
          "выходы того же числа в те же часы среди открытых — медиана "
          f"{_u((ctl.get('sum') or {}).get('med'), 2)} по {m.get('seeds')} "
          f"зёрнам; случайные не хуже правила в {_sh(m.get('beat'), 1)} "
          "зёрен.", "",
          "### Книга рядом с базовой", "",
          "«По отметке» — позиция закрыта отметкой часа (так же, как "
          "закрывает охрана рынком); «по уровню» — ровно на полу, то есть в "
          "предположении, что разрыва внутри бара нет. Цена выхода лежит "
          "между ними; состав — нет (см. «чего замер не говорит»).", ""]
    pairs = [("базовая `safe_h`", m.get("base")),
             (f"сестра, пол {FLOOR:g}, по отметке", m.get("sister_mark")),
             ("сестра, по уровню", m.get("sister_level"))]
    L += _cols_table(pairs) + [""]
    L += ["**Состав исходов.**", ""] + _exits_table(pairs) + [""]
    dd = m.get("days") or {}
    L += [f"**По дням** (сестра по отметке против базовой): суток "
          f"{dd.get('n_days')}, лучше в {dd.get('better')}, хуже в "
          f"{dd.get('worse')}, Σ разницы {_u(dd.get('sum_diff'))} $. Дни, "
          f"где разница ≥ {WG.DAY_MIN_USD:g} $:", "",
          "| сутки | базовая | сестра | разница |", "|---|--:|--:|--:|"]
    for x in sorted(dd.get("rows") or [], key=lambda z: z["diff"]):
        L.append(f"| {x['d']} | {_u(x['base'])} | {_u(x['rule'])} | "
                 f"{_u(x['diff'])} |")
    L += [""]
    w = m.get("window") or {}
    if w.get("since"):
        L += [f"### Окно с {w['since']} — ПЕРЕСЧЁТ, а не наблюдение", "",
              f"{w.get('why')}. Показано потому, что оба дня, породившие "
              "заявку, лежат в этом окне.", ""]
        L += _cols_table([("базовая", w.get("base")),
                          ("сестра по отметке", w.get("sister"))]) + [""]
    L += ["### Объявленные убийцы", "",
          "Пороги объявлены заданием ДО прогона: (А) худший день сестры не "
          f"глубже {WORST_SHARE:.2f} худшего дня базовой; (Б) Σ приращения "
          f"pnl лучше случайных выходов в ≥ {100 * (1 - BEAT_MAX):.0f} % "
          "зёрен; (В) медиана дня и «$ без 3 лучших дней» не ниже нуля; "
          f"(Г) форвард при ≥ {MIN_FWD_DAYS} сутках со сделками.", ""]
    L += _verdict_lines(m.get("verdicts")) + [""]
    return L


def _step2(r):
    if not r or r.get("error"):
        return []
    L = ["## Шаг 2. Реплей ядром", "",
         f"Решений листа {r.get('legs')}, записей сестры "
         f"{r.get('positions')} (пересчитано в этом прогоне "
         f"{r.get('replayed')}), кэш сестры — `{r.get('cache')}` со своей "
         "подписью: пол входит в неё, и кэш живой книги не тронут. Решений, "
         f"которых нет в живом кэше базовой книги: {r.get('missing_in_base')}."
         , ""]
    g = r.get("gap") or {}
    if g.get("why") or not g:
        L += ["**Разрыв через пол:** "
              + (g.get("why") or "не посчитан") + ".", ""]
    else:
        L += [f"**Хвост, прошедший пол разрывом.** Хвостовых исходов "
              f"{_n(g.get('n'))}, из них ушли НИЖЕ уровня пола "
              f"{_n(g.get('below'))} "
              f"({_sh(g.get('share'), 0)}), ликвидаций среди них "
              f"{_n(g.get('liq'))}. Разность «исход минус уровень» в долях "
              f"маржи: медиана {_n((g.get('gap') or {}).get('med'))}, края "
              f"{_n((g.get('gap') or {}).get('q05'))} … "
              f"{_n((g.get('gap') or {}).get('q95'))}. Это та величина, "
              "которой потолок по отметкам не знает вовсе.", ""]
    ch = r.get("changed") or {}
    ctl = r.get("control") or {}
    L += [f"**Что изменил пол.** Исход сестры отличается от базовой у "
          f"{_n(ch.get('n'))} позиций (из них были хвостом и БЕЗ пола — "
          f"{_n(ch.get('tails'))}), Σ "
          f"приращения pnl {_u(ch.get('sum'), 2)} долей маржи; случайные "
          "выходы того же числа в те же часы среди открытых — медиана "
          f"{_u((ctl.get('sum') or {}).get('med'), 2)} по {r.get('seeds')} "
          f"зёрнам, не хуже правила в {_sh(r.get('beat'), 1)} зёрен. "
          "Асимметрия названа: у правила цена выхода лежит ВНУТРИ бара, у "
          "случайного выхода — на границе часа, других цен у контроля нет."
          + ("" if not ch.get("why") else
             " Не вошли в контроль: "
             + ", ".join(f"{k} — {v}" for k, v in ch["why"].items()) + "."),
          ""]
    L += _cols_table([("базовая, вся запись", r.get("base")),
                      ("базовая, те же решения", r.get("base_same")),
                      (f"сестра, пол {FLOOR:g}, ядром", r.get("sister"))])
    L += [""]
    L += ["**Состав исходов.**", ""]
    L += _exits_table([("базовая, те же решения", r.get("base_same")),
                       ("сестра ядром", r.get("sister"))]) + [""]
    L += ["### Объявленные убийцы по реплею", ""]
    L += _verdict_lines(r.get("verdicts")) + [""]
    return L


# --- артефакт и запуск ----------------------------------------------------

def merge(new, path):
    """Слить шаги: посчитанный шаг перекрывает прежний, другой остаётся.

    Шаги стоят разных денег и считаются разными прогонами, поэтому
    артефакт обязан помнить оба — и помнить, КОГДА посчитан каждый:
    отчёт, выдающий вчерашний шаг за сегодняшний, стареет молча.
    """
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = {}
    out = dict(old)
    out.update({k: v for k, v in new.items() if v is not None})
    for step in ("marks", "replay"):
        if new.get(step) is None and old.get(step) is not None:
            out[step] = old[step]
    return out


def write(s, name=ART, log=print):
    os.makedirs(OUT, exist_ok=True)
    art = os.path.join(OUT, f"{name}.json")
    s = merge(s, art)
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    log(txt)
    return s, txt


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay", action="store_true",
                    help="шаг 2: реплей ядром (сотни секунд, очередь)")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--limit", type=int, default=None,
                    help="смоук: записей (шаг 1) или ног листа (шаг 2)")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    step = "replay" if a.replay else "marks"
    fn = run_replay if a.replay else run_marks
    got = fn(seeds=a.seeds, limit=a.limit, log=log_line)
    if got.get("error"):
        log_line(f"шаг «{step}» не посчитан: {got['error']}")
    s = {"mech": MECH, "book": BOOK, "ruler": RULER, "dep": DEP,
         "floor": {"sister": FLOOR, "base": BASE_FLOOR, "key": FLOOR_KEY},
         "guard": GUARD, "age_days": AGE_D, step: got}
    # Смоук не трогает артефакт замера: выборочные числа в файле, который
    # читают как полный, — это подставной артефакт (правило `run_short`).
    write(s, name=(ART if not a.limit else ART + "-smoke"), log=print)
    if not a.no_publish:
        publish(f"механика {MECH}: пол {FLOOR:g} у безопасной короткой книги")
    return 1 if got.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
