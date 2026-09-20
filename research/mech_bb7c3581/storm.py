#!/usr/bin/env python3
"""
Механика bb7c3581 — буря выкупа шортов ПО РЫНКУ.

Что утверждается
----------------

Хвост коротких книг `h24` (`safe_h`, `optimal_h`, `aggr_h`; правила как
сейчас — одиночный вход на 24 ч, цель ×2, пол 0.10 / 0.50 / 0.50,
возраст ≥ 7 суток, ОХРАНА РЫНКОМ 2 %, деньги нетто) делает не сквиз
СОБСТВЕННОГО имени (закрыто 19.09 механикой 357a7c60), а БУРЯ выкупа
шортов по всему рынку. Календарный час `k` бурный, когда

    ширина_k = (имён, у которых час помечен правилом родителя)
               / (имён, у которых час ИЗМЕРЕН)          ≥ q

Метка имени — константы родителя, а не ось: доля выкупа шортов в обороте
часа ≥ 1 % при потоке ≥ 1 000 $ (`squeeze_fuel.is_marked`). Ось здесь
ОДНА и объявлена до прогона — ширина `AXIS_Q` = 1 / 2 / 3 %, судит
СЕРЕДИНА (2 %), края печатаются рядом и не судят.

Правило — правило ВСЕЙ КНИГИ, а не позиции: на конце ПЕРВОГО бурного
часа закрываются ВСЕ открытые шорты трёх книг по почасовой отметке ядра,
поверх действующей охраны рынком и строго раньше базового выхода.
Равенство отметки усечению симуляции доказано охраной на 6 100 точках
(`dca_paper/out/DCA-wave-guard.md`), поэтому второго реплея нет — и это
же потолок замера: внутри часа путь не виден.

Почему контроль здесь ДРУГОЙ
----------------------------

У правила на позицию честен контроль «случайные выходы того же числа
сделок в те же часы среди открытых» (`path_screen.control_exits`). Для
правила ВСЕЙ книги он вырождается: в бурный час закрываются все
открытые, и случайная выборка того же числа в тот же час есть то же
самое множество. Поэтому случайными здесь становятся ЧАСЫ: столько же
закрытий книги целиком в случайных часах, с ТЕМ ЖЕ мультимножеством
часа суток (бурные часы кучкуются в 21:00 и 03:00 UTC — без
согласования контроль спрашивал бы «бывает ли час суток», а не «бывает
ли буря»). Это брат `control_exits`, а не правка чужого ядра.

Контргипотеза названа рядом и убивает механизм даже при удачных
деньгах: буря может быть КУЛЬМИНАЦИЕЙ, а не началом хода. Тогда
закрытие в этот час продаёт дно. Решает диагностика `before_worst`
родителя: доля хвостовых позиций, у которых первый бурный час стоит
раньше часа худшей отметки. Меньше `DIAG_MIN` — механизм мёртв.

Чего здесь НЕ живёт
-------------------

Второй копии расчётного ядра нет. Метка часа, сторона ленты, измеримость
часа, взгляды на кэш, «раньше худшей отметки» — родитель
(`mech_357a7c60/squeeze_fuel.py`); путь, отметки, закрытие записи и
охрана рынком как БАЗА — `dca_paper/wave.py` и `dca_paper/run_paper.py`;
деньги, дельты и касса — `dca_paper/path_screen.py` и
`dca_paper/agree_book.py`; концентрация и разбор по дням —
`dca_paper/wave_guard.py`; форма по дням — `factory/stability.py`.

Здесь живут ровно: таблица ширины по КАЛЕНДАРНОМУ часу, множество
бурных часов, применение правила к книге целиком, контроль случайными
часами и вердикт, выведенный из чисел.

Файлов этот модуль не открывает: сводки приходят строками, журнал —
готовым кэшем. Всё I/O — в `run_storm.py`.
"""
import collections
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (os.path.join(RESEARCH, "dca_paper"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "a1_universe"),
           os.path.join(RESEARCH, "mech_d71203f0"),
           os.path.join(RESEARCH, "mech_357a7c60")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agree_book as AG                                       # noqa: E402
import path_screen as P                                       # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import squeeze_fuel as SQ                                     # noqa: E402
import unprovoked as U                                        # noqa: E402
import wave as WV                                             # noqa: E402
import wave_guard as WG                                       # noqa: E402

# Чужой модуль под знакомым именем в этом проекте уже импортировался: на
# пути лежат семь каталогов, и `rules`, `costs`, `stability` есть больше
# чем в одном. Проверка — та же, что у родителя, и тем же кодом.
U.check_origin(AG, "dca_paper")
U.check_origin(P, "dca_paper")
U.check_origin(RP, "dca_paper")
U.check_origin(WV, "dca_paper")
U.check_origin(WG, "dca_paper")
U.check_origin(SQ, "mech_357a7c60")

HOUR = WV.HOUR
BOOK_KEYS = list(P.BOOK_KEYS)          # safe_h, optimal_h, aggr_h
MAIN_DEP = P.MAIN_DEP

# --- объявлено заданием ДО прогона, после результата не меняется -------
AXIS_Q = (0.01, 0.02, 0.03)     # ширина бури: доля помеченных имён
MIN_NAMES = 100                 # имён в часе; меньше — час НЕ ИЗМЕРИМ
MIN_CHANGED = 30                # изменённых позиций на книгу; меньше — судить нечем
COVER_BLOCK = SQ.COVER_BLOCK    # покрытие журнала ниже — блок
COVER_WARN = SQ.COVER_WARN      # ниже — вердикт с оговоркой
DIAG_MIN = SQ.DIAG_MIN          # убийца (в): буря раньше худшей отметки
BEAT_MAX = SQ.BEAT_MAX          # убийца (а): зёрен, где случайные не хуже
BOOKS_NEED = SQ.BOOKS_NEED      # книг из трёх, прошедших контроль
CTL_SEEDS = P.SEEDS             # зёрен контроля — объявлено дорогой сделки
SHIFT_H = 24                    # диагностика: ряд ширины, сдвинутый на сутки
QUIET_WAVE = 0.01               # |волна мажоров| за час, ниже которой охрана слепа

# --- константы РОДИТЕЛЯ: метка имени, а не ось этой механики -----------
# Ось родителя объявлена до его прогона и судилась серединой; здесь она
# не ось, а строительный блок, поэтому берётся ровно его судимая ячейка,
# а не переписанное число. Разойдись родитель с этой строкой — тест
# `test_mark_is_the_parent_judged_cell` скажет об этом вслух.
MARK_S = SQ.middle(SQ.AXIS_S)
MIN_USD = SQ.MIN_USD
LIQ_FIELDS = SQ.LIQ_FIELDS

EXIT_LABEL = "буря"
CTL_SEED0 = 8830000             # зерно ЧИСЛОМ: hash строки солится


def middle(axis=AXIS_Q):
    """Судимая ячейка — СЕРЕДИНА объявленной оси, а не лучшая."""
    return WG.middle(list(axis))


# ======================================================================
# 1. Ширина бури по КАЛЕНДАРНОМУ часу
# ======================================================================

def new_width():
    return {"hours": {}, "rows": 0, "names": 0, "unmeasured": 0,
            "no_hour": 0, "dup": 0}


def fold_width(rows, acc=None, s=MARK_S, min_usd=MIN_USD):
    """Счётчики ширины по календарному часу — по ОДНОМУ имени за проход.

    Считается для КАЖДОЙ колонки ликвидаций сразу, а не для той, что
    выберет калибровка: калибровка кончится только после прохода по всем
    772 именам, а второй проход стоил бы минут. Заодно это и есть
    контроль стороны — число бурных часов у переставленных колонок
    печатается рядом и обязано быть другим.

    Час имени ИЗМЕРЕН, когда сводка есть, поля ликвидаций заполнены и
    оборот больше нуля (`squeeze_fuel.flow_of`). Час без опроса метрик —
    ПРОЧЕРК, а не ноль потока: иначе выключенный сборщик выглядел бы как
    тихий рынок. Две строки одного имени на один час — дефект записи, и
    вторая не удваивает имя, а считается отдельным числом.
    """
    acc = acc if acc is not None else new_width()
    seen = set()
    for r in rows or []:
        acc["rows"] += 1
        hk = SQ.hour_no(r.get("hour"))
        if hk is None:
            acc["no_hour"] += 1
            continue
        if hk in seen:
            acc["dup"] += 1
            continue
        seen.add(hk)
        val, turn = SQ.flow_of(r, LIQ_FIELDS[0])
        if val is None or turn is None or float(turn) <= 0.0:
            acc["unmeasured"] += 1
            continue
        cell = acc["hours"].get(hk)
        if cell is None:
            cell = {"measured": 0, "marked": {f: 0 for f in LIQ_FIELDS}}
            acc["hours"][hk] = cell
        cell["measured"] += 1
        for f in LIQ_FIELDS:
            v, t = SQ.flow_of(r, f)
            if SQ.is_marked(v, t, s, min_usd=min_usd):
                cell["marked"][f] += 1
    return acc


def width_series(acc, field, min_names=MIN_NAMES):
    """{номер часа: ширина} — ПРОЧЕРК у часа с малым числом имён.

    Час, в котором измерено меньше `min_names` имён, ширины не имеет:
    доля по десятку имён скачет от одного всплеска, и «бури не было» там
    неотличимо от «мерить было не на чем». Прочерк, а не ноль.
    """
    out = {}
    for hk, c in (acc.get("hours") or {}).items():
        n = int(c["measured"])
        out[int(hk)] = (c["marked"][field] / n) if n >= int(min_names) else None
    return out


def width_stats(series):
    """Распределение ширины: медиана, p90, p95, p99, максимум.

    Чего нет — прочерк: ноль измеримых часов означает «мерить не на чем»,
    и печатать вместо этого нули значило бы выдать пустоту за тишину.
    """
    ws = [float(w) for w in (series or {}).values() if w is not None]
    out = {"measurable": len(ws), "unmeasurable": sum(
        1 for w in (series or {}).values() if w is None), "hours": len(series or {})}
    if not ws:
        out.update({"median": None, "p90": None, "p95": None, "p99": None,
                    "max": None})
        return out
    a = np.array(ws, dtype=float)
    out.update({"median": float(np.median(a)), "p90": float(np.percentile(a, 90)),
                "p95": float(np.percentile(a, 95)),
                "p99": float(np.percentile(a, 99)), "max": float(a.max())})
    return out


def storm_hours(series, q):
    """Календарные часы, в которых ширина ≥ q. Прочерк бурей НЕ БЫВАЕТ."""
    out = []
    for hk, w in sorted((series or {}).items()):
        if w is None:
            continue
        if float(w) >= float(q):
            out.append(int(hk))
    return out


def days_of(hours):
    """Суток, в которых стоит хотя бы один такой час."""
    return sorted({int(hk) // 24 for hk in hours})


def hod_hist(hours):
    """Гистограмма часа суток (UTC): номер часа записи и есть его час."""
    return dict(collections.Counter(int(hk) % 24 for hk in hours))


def shifted(series, hours=SHIFT_H):
    """Тот же ряд ширины, сдвинутый во ВРЕМЕНИ на `hours` часов.

    Диагностика, а не убийца: сдвинутая буря обязана давать ДРУГОЕ
    множество изменённых позиций. Совпало — правило метит не событие, а
    состав журнала.
    """
    return {int(hk) + int(hours): w for hk, w in (series or {}).items()}


def hour_wave(mkt, hk):
    """Волна двадцати прокси-имён ЗА час `hk` (ход от конца прошлого).

    Прочерк, если имён с ценой меньше пяти: «волна не измерена» и «рынок
    стоял» — разные ответы, и склеивать их нельзя.
    """
    return mkt.wave((int(hk) - 1) * HOUR, int(hk) * HOUR)


# ======================================================================
# 2. База: книги КАК СЕЙЧАС, то есть С охраной рынком
# ======================================================================

def guarded_books(cache, launch, now=None, log=lambda *a: None):
    """Записи каждой книги так, как они приходят в кассу.

    База этой механики — книги как сейчас, а охрана рынком есть правило
    книги с 13.09; кэш реплея хранит исход БЕЗ охраны. Поэтому правило
    применяется тем же кодом, каким его применяет прогон книги
    (`run_paper.age_shorts` → `run_paper.guard_shorts`), а не здесь
    заново. Касса (`short_grid.cell_stats`) применит оба правила ещё раз
    — они идемпотентны, и равенство базы проверяется ЧИСЛОМ
    (`run_storm`: «база по записям = база по кэшу»), а не обещанием.
    """
    packed = AG.packed_short(cache)
    out, st = {}, {}
    for bk in BOOK_KEYS:
        recs, a = RP.age_shorts(packed.get(bk) or [], bk, launch=launch,
                                log=log, now=now)
        recs, g = RP.guard_shorts(recs, bk, log=log, now=now)
        out[bk] = recs
        st[bk] = {"age": a, "guard": g}
    return out, st


def keyed(packed):
    """{(книга, имя, момент): запись} — ключ несёт КНИГУ, а не линейку.

    Две книги семейства (`optimal_h` и `aggr_h`) считаются на одной
    линейке `optimal_s` и различаются гейтом плеча, а порог охраны у них
    свой. Ключ линейки склеил бы их в одну запись, и правило всей книги
    закрывало бы чужие позиции.
    """
    out = {}
    for bk, recs in (packed or {}).items():
        for r in recs:
            out[(bk, r["sym"], round(float(r["at"]), 3))] = r
    return out


def repack(gcache):
    """Обратно в {книга: [записи]} — то, что ест касса семейства."""
    out = {bk: [] for bk in BOOK_KEYS}
    for (bk, _sym, _at), r in (gcache or {}).items():
        out.setdefault(bk, []).append(r)
    return out


# ======================================================================
# 3. Правило ВСЕЙ книги
# ======================================================================

def hours_of(view):
    """{календарный час: час жизни k} — часы, в которые правило вправе
    закрыть позицию.

    Часы СТРОГО до базового выхода (охрана рынком уже в базе). Час K —
    тот, в котором позицию закрыло ядро или охрана; заглянуть туда
    значило бы решать выход по тому, чем сделка кончилась, и находка
    была бы неотличима от находки.
    """
    at = float(view["rec"]["at"])
    return {SQ.hour_key(at, k): k for k in SQ.live_hours(view)}


def storm_exit(view, storms):
    """Первый бурный час жизни позиции либо None.

    ПЕРВЫЙ, а не худший и не последний: правило решает вперёд, а выбор
    лучшего из бурных часов был бы знанием о том, чем кончилось.
    """
    ks = [k for hk, k in hours_of(view).items() if int(hk) in storms]
    return min(ks) if ks else None


def apply_storm(views, storms):
    """{ключ сделки: час выхода} — ВСЕ открытые шорты, застигнутые бурей.

    Единица правила — ЧАС КНИГИ: в бурный час закрывается всё, что
    открыто, а не отобранные позиции. Укус делает именно одновременность
    (у безопасной в среднем 14.6 открытых, пик 32), поэтому ограничитель
    обязан быть книжным.
    """
    storms = set(int(x) for x in (storms or []))
    out = {}
    for key, v in (views or {}).items():
        k = storm_exit(v, storms)
        if k is not None:
            out[key] = k
    return out


def close_storm(gcache, changed, why=EXIT_LABEL):
    """Кэш книг с выходами по буре: та же запись, отметка ядра часа k.

    Закрытие записи — библиотечное (`wave.guard_record` через
    `path_screen.exit_at`), то же, чем закрывает охрана рынком. Своего
    закрытия здесь нет и быть не может: вторая формула исхода однажды
    разойдётся с первой.
    """
    mod = dict(gcache)
    for key, k in (changed or {}).items():
        mod[key] = P.exit_at(gcache[key], k, why=why)
    return mod


def by_book(views, changed):
    """Изменённых позиций по книгам — самый дешёвый убийца заявки."""
    out = {}
    for bk in BOOK_KEYS:
        keys = [key for key in changed if key[0] == bk]
        out[bk] = {"n": len(keys),
                   "tails": sum(1 for key in keys if views[key]["tail"]),
                   "positions": sum(1 for key in views if key[0] == bk)}
    return out


def cover_of(views, series):
    """Покрытие журнала РЯДОМ ШИРИНЫ: у скольких позиций измерим каждый
    час жизни.

    Это не `squeeze_fuel.coverage`: тот меряет поток в СОБСТВЕННОМ имени
    позиции, а здесь правило читает ширину по всему рынку, и измеримость
    часа — свойство часа, а не имени. Позиции, закрытые в первый же час,
    часов жизни не имеют вовсе — правилу там нечего смотреть; они
    считаются своим числом и в знаменатель не идут.
    """
    full = part = none = no_hours = 0
    hours_all = hours_ok = 0
    for _key, v in (views or {}).items():
        hs = hours_of(v)
        if not hs:
            no_hours += 1
            continue
        ok = sum(1 for hk in hs if (series or {}).get(int(hk)) is not None)
        hours_all += len(hs)
        hours_ok += ok
        if ok == len(hs):
            full += 1
        elif ok:
            part += 1
        else:
            none += 1
    n = full + part + none
    return {"n": n, "full": full, "part": part, "none": none,
            "no_hours": no_hours,
            "share": (full / n if n else None),
            "hours": hours_all, "hours_measured": hours_ok,
            "hours_share": (hours_ok / hours_all if hours_all else None)}


def guard_cross(views, changed, storms, guard_exit=None):
    """Пересечение с охраной рынком — числом, а не «по построению».

    Позиции, которые охрана закрыла раньше, правило не трогает по
    построению: база уже укорочена охраной, и бурный час после её выхода
    в часы жизни не попадает. «По построению» не число — вот число.
    """
    guard_exit = guard_exit or R.GUARD_EXIT
    storms = set(int(x) for x in (storms or []))
    by_guard = after_guard = both = 0
    for key, v in (views or {}).items():
        if (v["rec"].get("exit") or "") != guard_exit:
            continue
        by_guard += 1
        if key in changed:
            both += 1
            continue
        at = float(v["rec"]["at"])
        K = int(v["path"]["K"]) if v.get("path") else 0
        if K and SQ.hour_key(at, K) in storms:
            after_guard += 1
    return {"closed_by_guard": by_guard, "guard_and_storm": both,
            "storm_at_guard_hour": after_guard, "changed": len(changed)}


def quiet_share(waves, lim=QUIET_WAVE):
    """Доля бурных часов, в которые волна мажоров стояла на месте.

    Именно в них охрана рынком слепа по построению: она читает ЦЕНУ
    двадцати прокси-имён, а не ширину принудительного потока. Час с
    неизмеренной волной в знаменатель не идёт — прочерк, не ноль.
    """
    have = [w for w in (waves or []) if w is not None]
    if not have:
        return {"n": 0, "quiet": 0, "share": None,
                "missing": len(waves or [])}
    quiet = sum(1 for w in have if abs(float(w)) < float(lim))
    return {"n": len(have), "quiet": quiet, "share": quiet / len(have),
            "missing": len(waves or []) - len(have)}


# ======================================================================
# 4. Контроль: случайные ЧАСЫ с тем же часом суток
# ======================================================================

def hour_pool(series, lo=None, hi=None):
    """Измеримые часы записи, разложенные по часу суток.

    Окно ограничивается сроком журнала: час, в который книга не
    торговала, кандидатом быть не может — контроль иначе выбирал бы
    заведомо пустые часы и выигрывал бы тишиной.
    """
    pool = {}
    for hk, w in (series or {}).items():
        if w is None:
            continue
        if lo is not None and int(hk) < int(lo):
            continue
        if hi is not None and int(hk) > int(hi):
            continue
        pool.setdefault(int(hk) % 24, []).append(int(hk))
    return {h: sorted(v) for h, v in pool.items()}


def control_hours(real, pool, rnd):
    """Столько же закрытий книги в СЛУЧАЙНЫХ часах с тем же часом суток.

    Возвращает (множество часов, причина отказа). Часов суток не хватило
    — отказ С ПРИЧИНОЙ, а не выборка меньшего размера: фильтр, режущий
    число событий, сравнивается с выборкой ТОГО ЖЕ размера, и тихая
    замена размера сделала бы контроль слабее правила.
    """
    out = []
    for h, need in sorted(collections.Counter(int(hk) % 24
                                              for hk in (real or [])).items()):
        cand = list((pool or {}).get(h) or [])
        if len(cand) < need:
            return None, (f"часов суток {h:02d} измеримо {len(cand)} при "
                          f"нужных {need} — выборка того же размера "
                          "невозможна")
        out.extend(rnd.sample(cand, need))
    return set(out), None


def control_storm(gcache, views, real, pool, ctx, launch, seeds=CTL_SEEDS,
                  dep=MAIN_DEP, now=None, log=print, seed0=CTL_SEED0):
    """Контроль правила ВСЕЙ книги: те же закрытия в случайных часах.

    Брат `path_screen.control_exits`, а не правка чужого ядра: для
    книжного правила случайная выборка того же числа позиций в те же
    часы вырождается в само правило (множества совпадают), и мерить ею
    нечего. Случайными становятся ЧАСЫ.
    """
    out = {"books": {}, "sum": [], "n": [], "seeds": 0, "no_draw": 0,
           "why": None}
    import time as _t
    t0 = _t.time()
    for i in range(int(seeds)):
        rnd = random.Random(int(seed0) + i)
        hrs, why = control_hours(real, pool, rnd)
        if hrs is None:
            out["no_draw"] += 1
            out["why"] = why
            continue
        ch = apply_storm(views, hrs)
        st = AG.stats_of(repack(close_storm(gcache, ch)), ctx, launch,
                         BOOK_KEYS, deps=[dep], now=now)
        for bk in BOOK_KEYS:
            c = st.get(f"{bk}:{int(dep)}") or {}
            out["books"].setdefault(bk, []).append(
                {"final": c.get("final"), "ratio": c.get("ratio"),
                 "max_dd": c.get("max_dd")})
        d = P.deltas(gcache, views, ch)
        out["sum"].append(d["sum"])
        out["n"].append(d["n"])
        out["seeds"] += 1
        if i and i % 50 == 0:
            log(f"    контроль часов: {i} зёрен из {seeds}, "
                f"{_t.time() - t0:.0f} с")
    return out


def shape_of(stats_cell):
    """Форма по дням — мерой проекта (`stability.stats`), не своей."""
    return SQ.shape_of(stats_cell)


# ======================================================================
# 5. Вердикт: выводится из чисел
# ======================================================================

def _cell_of(art, q):
    for c in art.get("cells") or []:
        if abs(float(c["q"]) - float(q)) < 1e-12:
            return c
    return None


def verdict(art):
    """Убийцы по порядку; сработавший закрывает заявку.

    Порядок обязателен и не переставляется: (0) сторона, покрытие,
    измеримость часа и число изменённых позиций — ДО денег; (1) потолок
    на почасовых отметках — контроль случайными часами, «$ без 3 лучших
    дней», начало против кульминации. Каждая строка несёт своё ЧИСЛО:
    фраза, стоящая рядом с числом, а не выведенная из него, стареет
    молча и однажды противоречит ему.
    """
    rows = []

    def add(key, title, state, text):
        rows.append({"key": key, "title": title, "state": state, "text": text})

    side = art.get("side") or {}
    if not side.get("ok"):
        add("сторона", "0а. Сторона ленты ликвидаций", "блок",
            f"сторону выбрать нечем: {side.get('why')}. Замер не считается: "
            "знак был бы угадан.")
        return rows
    add("сторона", "0а. Сторона ленты ликвидаций", "пройдено", str(side["why"]))

    w = art.get("width") or {}
    if not int(w.get("measurable") or 0):
        add("измеримость", "0б. Измеримость календарного часа", "блок",
            f"часов с числом имён ≥ {MIN_NAMES} не нашлось ни одного "
            f"({w.get('unmeasurable')} часов — прочерк): ширину считать не "
            "на чем, и это отсутствие меры, а не отсутствие бури.")
        return rows
    add("измеримость", "0б. Измеримость календарного часа", "пройдено",
        f"измеримых часов {w.get('measurable')} из {w.get('hours')} "
        f"(прочерк у {w.get('unmeasurable')}); медиана ширины "
        f"{_pct(w.get('median'), 2)}, p90 {_pct(w.get('p90'), 2)}, "
        f"p99 {_pct(w.get('p99'), 2)}, максимум {_pct(w.get('max'), 1)}.")

    cov = art.get("cover") or {}
    sh = cov.get("share")
    if sh is None:
        add("покрытие", "0в. Покрытие журнала рядом ширины", "блок",
            "покрытие НЕ ИЗМЕРЕНО: позиций с часами жизни не нашлось.")
        return rows
    if sh < COVER_BLOCK:
        add("покрытие", "0в. Покрытие журнала рядом ширины", "блок",
            f"ряд ширины не покрывает журнал: каждый час жизни измерим у "
            f"{100 * sh:.1f} % позиций при пороге {100 * COVER_BLOCK:.0f} %.")
        return rows
    if sh < COVER_WARN:
        add("покрытие", "0в. Покрытие журнала рядом ширины", "оговорка",
            f"каждый час жизни измерим у {100 * sh:.1f} % позиций "
            f"(часов измеримо {_pct(cov.get('hours_share'))}) — вердикт ниже "
            "читается с этой оговоркой.")
    else:
        add("покрытие", "0в. Покрытие журнала рядом ширины", "пройдено",
            f"каждый час жизни измерим у {100 * sh:.1f} % позиций "
            f"(часов измеримо {_pct(cov.get('hours_share'))}).")

    q = float(art.get("judged") or middle())
    cell = _cell_of(art, q)
    if cell is None:
        add("объём", "0г. Изменённых позиций", "блок",
            f"судимая ячейка q = {100 * q:.1f} % не посчитана.")
        return rows
    bb = cell.get("by_book") or {}
    thin = {bk: v["n"] for bk, v in bb.items() if int(v["n"]) < MIN_CHANGED}
    if thin:
        add("объём", "0г. Изменённых позиций", "нечем судить",
            "охрана рынком уже покрывает то, что закрыла бы буря: "
            "изменённых позиций "
            + ", ".join(f"{bk} {n}" for bk, n in sorted(thin.items()))
            + f" при минимуме {MIN_CHANGED} на книгу. Это результат, а не "
            "сбой: ось не судится.")
        return rows
    add("объём", "0г. Изменённых позиций", "пройдено",
        "изменено позиций: "
        + ", ".join(f"{bk} {v['n']} (хвостовых {v['tails']})"
                    for bk, v in sorted(bb.items()))
        + f"; бурных часов {cell.get('storms')} в {cell.get('storm_days')} "
        "сутках.")

    seeds = int((cell.get("control") or {}).get("seeds") or 0)
    if seeds < CTL_SEEDS:
        add("контроль", "1а. Закрытия книги в случайных часах", "нечем судить",
            f"контроль прогнан на {seeds} зёрнах при объявленных "
            f"{CTL_SEEDS}: разрешение доли есть 1/зёрна, и планка "
            f"{100 * BEAT_MAX:.0f} % на стольких зёрнах не измерима. Это "
            "смоук ДОРОГИ, а не вердикт о гипотезе."
            + (f" Причина недобора: {(cell.get('control') or {}).get('why')}."
               if (cell.get("control") or {}).get("why") else ""))
        return rows

    beat = cell.get("beat") or {}
    good = [bk for bk in BOOK_KEYS
            if (beat.get(bk) or {}).get("final") is not None
            and float(beat[bk]["final"]) < BEAT_MAX]
    if len(good) < BOOKS_NEED:
        add("контроль", "1а. Закрытия книги в случайных часах", "убивает",
            f"книг, где случайные часы не хуже меньше чем в "
            f"{100 * BEAT_MAX:.0f} % зёрен: {len(good)} при нужных "
            f"{BOOKS_NEED} из {len(BOOK_KEYS)} ("
            + ", ".join(f"{bk} {_pct((beat.get(bk) or {}).get('final'), 0)}"
                        for bk in BOOK_KEYS) + ").")
        return rows
    add("контроль", "1а. Закрытия книги в случайных часах", "пройдено",
        f"книг, где случайные часы не хуже меньше чем в "
        f"{100 * BEAT_MAX:.0f} % зёрен: {len(good)} ({', '.join(good)}).")

    wo3 = cell.get("wo3") or {}
    grew = [bk for bk in good
            if (wo3.get(bk) or {}).get("rule") is not None
            and (wo3.get(bk) or {}).get("base") is not None
            and float(wo3[bk]["rule"]) > float(wo3[bk]["base"])]
    if not grew:
        add("концентрация", "1б. Деньги без трёх лучших дней", "убивает",
            "«$ без 3 лучших дней» не выросло ни в одной из прошедших "
            "контроль книг: "
            + ", ".join(f"{bk} {_usd((wo3.get(bk) or {}).get('base'))} → "
                        f"{_usd((wo3.get(bk) or {}).get('rule'))}"
                        for bk in good)
            + " — прибавка живёт лучшими днями.")
        return rows
    add("концентрация", "1б. Деньги без трёх лучших дней", "пройдено",
        "«$ без 3 лучших дней» выросло в "
        + ", ".join(f"{bk} {_usd((wo3.get(bk) or {}).get('base'))} → "
                    f"{_usd((wo3.get(bk) or {}).get('rule'))}" for bk in grew)
        + ".")

    dg = cell.get("diag") or {}
    dsh = dg.get("share")
    if dsh is None:
        add("механизм", "1в. Буря раньше худшей отметки", "не измерено",
            "хвостовых позиций, которых правило коснулось, не нашлось — "
            "доля НЕ ИЗМЕРЕНА, и механизм не подтверждён ничем.")
        return rows
    if dsh < DIAG_MIN:
        add("механизм", "1в. Буря раньше худшей отметки", "убивает",
            f"первый бурный час стоит раньше часа худшей отметки у "
            f"{100 * dsh:.1f} % хвостовых позиций ({dg.get('early')} из "
            f"{dg.get('n')}) при пороге {100 * DIAG_MIN:.0f} %: буря есть "
            "КУЛЬМИНАЦИЯ, правило продаёт дно — независимо от денег.")
        return rows
    add("механизм", "1в. Буря раньше худшей отметки", "пройдено",
        f"первый бурный час раньше худшей отметки у {100 * dsh:.1f} % "
        f"хвостовых позиций ({dg.get('early')} из {dg.get('n')}).")
    return rows


def reading(art):
    """Одна фраза итога — ВЫВЕДЕННАЯ из строк вердикта, а не дописанная."""
    rows = art.get("verdict") or verdict(art)
    for r in rows:
        if r["state"] in ("блок", "убивает", "нечем судить", "не измерено"):
            return f"**{r['title']}: {r['state']}.** {r['text']}"
    q = float(art.get("judged") or middle())
    return (f"**Все объявленные убийцы пройдены при q = {100 * q:.1f} %.** "
            "Это не правило и не книга: следующий шаг — внутричасовой реплей "
            "по ленте ликвидаций на изменённых позициях, а дорога вперёд "
            "(сестра книги со своим кэшем) — решение владельца.")


# ======================================================================
# 6. Показ
# ======================================================================

def _pct(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _usd(x):
    return "—" if x is None else f"{float(x):+,.0f} $"


def _i(x):
    return "—" if x is None else f"{int(x)}"


def _f(x, d=2):
    return "—" if x is None else f"{float(x):+.{d}f}"


def _e(x):
    return "—" if x is None else f"{float(x):.3g}"


def _side_table(side):
    L = ["| метка | колонка сводки | $ в часах падения | $ в часах роста "
         "| доля в падениях |", "|---|---|--:|--:|--:|"]
    for m in sorted(SQ.MARK_COLUMN):
        d = (side.get("usd_down") or {}).get(m)
        u = (side.get("usd_up") or {}).get(m)
        q = (side.get("share_down") or {}).get(m)
        L.append(f"| `{m}` | `{SQ.MARK_COLUMN[m]}` | {_e(d)} | {_e(u)} "
                 f"| {'—' if q is None else f'{q:.3f}'} |")
    return L


def _axis_table(art):
    L = ["| q | бурных часов | суток с бурей | доля часов записи "
         "| изменено позиций: " + " / ".join(BOOK_KEYS) + " |",
         "|--:|--:|--:|--:|--:|"]
    w = art.get("width") or {}
    meas = int(w.get("measurable") or 0)
    for c in art.get("cells") or []:
        mark = "**" if abs(float(c["q"]) - float(art.get("judged") or 0)) < 1e-12 else ""
        bb = c.get("by_book") or {}
        L.append(f"| {mark}{100 * c['q']:.1f} %{mark} | {c.get('storms')} "
                 f"| {c.get('storm_days')} "
                 f"| {_pct((c.get('storms') / meas) if meas else None, 2)} | "
                 + " / ".join(str((bb.get(bk) or {}).get("n")) for bk in BOOK_KEYS)
                 + " |")
    return L


def _money_table(art, cell):
    base = art.get("base") or {}
    dep = art.get("dep")
    L = ["| книга | итог: как есть → с правилом | просадка | сделок "
         "| хвостовых выходов | $ без 3 лучших дней | дней лучше / хуже "
         "| худший день, $ | укус | медиана дня | зелёных суток "
         "| зёрен, где случайные часы не хуже |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in BOOK_KEYS:
        b = base.get(f"{bk}:{dep}") or {}
        r = (cell.get("stats") or {}).get(f"{bk}:{dep}") or {}
        t = (cell.get("tails") or {}).get(bk) or {}
        w = (cell.get("wo3") or {}).get(bk) or {}
        dd = (cell.get("days") or {}).get(bk) or {}
        shp = (cell.get("shape") or {}).get(bk) or {}
        sb, sr = shp.get("base") or {}, shp.get("rule") or {}
        bt = (cell.get("beat") or {}).get(bk) or {}
        L.append(f"| {bk} | {_pp(b.get('final'))} → {_pp(r.get('final'))} "
                 f"| {_pp(b.get('max_dd'))} → {_pp(r.get('max_dd'))} "
                 f"| {_i(b.get('n'))} → {_i(r.get('n'))} "
                 f"| {_i(t.get('base'))} → {_i(t.get('rule'))} "
                 f"| {_usd(w.get('base'))} → {_usd(w.get('rule'))} "
                 f"| {_i(dd.get('better'))} / {_i(dd.get('worse'))} "
                 f"| {_usd(sb.get('worst'))} → {_usd(sr.get('worst'))} "
                 f"| {_f(sb.get('bite'), 1)} → {_f(sr.get('bite'), 1)} "
                 f"| {_f(b.get('day_median'), 5)} → {_f(r.get('day_median'), 5)} "
                 f"| {_pct(sb.get('green'))} → {_pct(sr.get('green'))} "
                 f"| {_pct(bt.get('final'), 0)} |")
    return L


def report(art):
    """Отчёт. Каждое число, которого нет, — прочерк с причиной."""
    q = float(art.get("judged") or middle())
    L = ["# Механика bb7c3581: буря выкупа шортов по рынку", "",
         "Утверждение: хвост коротких книг `h24` делает не сквиз "
         "СОБСТВЕННОГО имени (закрыто 19.09), а БУРЯ выкупа шортов по всему "
         "рынку. Календарный час бурный, когда всплеск принудительного "
         f"выкупа (доля ≥ {100 * MARK_S:.0f} % оборота часа при потоке ≥ "
         f"{MIN_USD:,.0f} $ — константы родителя, не ось) стоит "
         "одновременно у доли имён не меньше q. На конце ПЕРВОГО бурного "
         "часа закрываются ВСЕ открытые шорты трёх книг — поверх охраны "
         "рынком и строго раньше базового выхода.", "",
         "Ось объявлена до прогона: "
         + ", ".join(f"{100 * x:.0f} %" for x in art.get("axis") or AXIS_Q)
         + f"; судит СЕРЕДИНА ({100 * q:.0f} %), края печатаются рядом и не "
         "судят. Исход выхода — почасовая отметка ядра симуляции; внутри "
         "часа путь не виден, и это потолок, а не реплей.", ""]
    if art.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {art['error']}.", ""])
    L += ["## Итог", "", reading(art), "",
          "| убийца | состояние | число |", "|---|---|---|"]
    for r in art.get("verdict") or []:
        L.append(f"| {r['title']} | **{r['state']}** | {r['text']} |")

    L += ["", "## 0. Что измерено ДО денег", "",
          "**Сторона ленты.** Кодировка сводки известна (`Buy` → колонка "
          "`liq_short`, `Sell` → `liq_long`), а кого выбило — решают данные: "
          "шортов выбивают РОСТОМ, значит метка, доллары которой лежат в "
          "часах падения, маркирует ликвидацию лонга. Модуль верен при любом "
          "имени колонки.", ""]
    side = art.get("side") or {}
    L += _side_table(side) + ["", f"Решение: {side.get('why')}", ""]
    w = art.get("width") or {}
    L += [f"**Ширина по календарному часу.** Часов записи {w.get('hours')}, "
          f"измеримых (имён ≥ {MIN_NAMES}) {w.get('measurable')}, прочерк у "
          f"{w.get('unmeasurable')}. Распределение ширины: медиана "
          f"{_pct(w.get('median'), 2)}, p90 {_pct(w.get('p90'), 2)}, p95 "
          f"{_pct(w.get('p95'), 2)}, p99 {_pct(w.get('p99'), 2)}, максимум "
          f"{_pct(w.get('max'), 1)}. Имён в сводках {art.get('summary_names')}, "
          f"строк {(art.get('width_raw') or {}).get('rows')}, из них без полей "
          f"ликвидаций или с нулевым оборотом "
          f"{(art.get('width_raw') or {}).get('unmeasured')} — ПРОЧЕРК, не "
          "ноль потока.", ""]
    cov = art.get("cover") or {}
    L += [f"**Покрытие журнала рядом ширины.** Позиций с часами жизни "
          f"{cov.get('n')} (закрытых в первый же час — {cov.get('no_hours')}, "
          "им правило недоступно); каждый час жизни измерим у "
          f"{cov.get('full')} ({_pct(cov.get('share'))}), часть часов — у "
          f"{cov.get('part')}, ни одного — у {cov.get('none')}. Часов жизни "
          f"{cov.get('hours')}, измеримых {cov.get('hours_measured')} "
          f"({_pct(cov.get('hours_share'))}).", "",
          "**Ось ширины: бурные часы, сутки и изменённые позиции.**", ""]
    L += _axis_table(art) + [""]
    hod = art.get("hod") or {}
    if hod:
        L += ["**Гистограмма часа суток бурь (UTC), q судимой ячейки:** "
              + ", ".join(f"{int(h):02d}:00 — {n}"
                          for h, n in sorted(hod.items(), key=lambda kv: int(kv[0])))
              + ".", ""]
    sw = art.get("swap") or {}
    if sw:
        L += ["**Переставленные колонки стороны** (контроль, не результат): "
              f"на колонке `{sw.get('field')}` бурных часов "
              f"{sw.get('storms')} против {sw.get('real')} на выбранной "
              "данными — множества разные, значит сторона несёт смысл, а не "
              "имя.", ""]

    cell = _cell_of(art, q)
    L += ["## 1. Потолок на почасовых отметках", "",
          "База — книги КАК СЕЙЧАС, то есть С охраной рынком: кэш реплея "
          "хранит исход без неё, и она применена тем же кодом, каким её "
          "применяет прогон книги. Деньги — касса семейства на депозите "
          f"${art.get('dep')} нетто. Контроль — столько же закрытий ВСЕЙ "
          "книги в случайных часах с тем же мультимножеством часа суток, "
          f"{art.get('seeds')} зёрен.", ""]
    if cell:
        L += [f"### Судимая ячейка q = {100 * q:.0f} %", ""]
        L += _money_table(art, cell) + [""]
        d = cell.get("delta") or {}
        ctl = cell.get("control") or {}
        L += ["**Σ долей маржи изменённых сделок** (отдельно от кассы, чтобы "
              "деньги кассы не выдать за спасённый хвост): правило "
              f"{_f(d.get('sum'))} на {d.get('n')} сделках (хвостовых "
              f"{d.get('tails')}; срезано в минус {d.get('cut_worse')}), "
              f"случайные часы — медиана {_f(P._med(ctl.get('sum') or []))}; "
              "не хуже правила в "
              f"{_pct((cell.get('beat') or {}).get('sum'), 0)} зёрен. "
              + ("Слабо — и это сказано словами, а не спрятано в таблицу."
                 if ((cell.get("beat") or {}).get("sum") is not None
                     and float((cell.get("beat") or {})["sum"]) >= BEAT_MAX)
                 else "Контроль этой величины пройден."), ""]
        dg = cell.get("diag") or {}
        L += ["**Начало или кульминация.** Первый бурный час раньше часа "
              f"худшей отметки у {_pct(dg.get('share'))} хвостовых позиций, "
              f"которых правило коснулось ({dg.get('early')} из "
              f"{dg.get('n')}; в тот же час {dg.get('same')}, позже "
              f"{dg.get('late')}). Порог {100 * DIAG_MIN:.0f} % объявлен до "
              "прогона: ниже — буря есть кульминация, и правило продаёт дно.",
              ""]
        qs = cell.get("quiet") or {}
        L += ["**Чего охрана рынком не видит.** Волна двадцати прокси-имён "
              f"за бурный час измерена у {qs.get('n')} часов (прочерк у "
              f"{qs.get('missing')}); |волна| < {100 * QUIET_WAVE:.0f} % у "
              f"{qs.get('quiet')} из них ({_pct(qs.get('share'))}). В этих "
              "часах охрана слепа по построению: она читает ЦЕНУ мажоров от "
              "входа, а не ширину принудительного потока.", ""]
        gc = cell.get("guard_cross") or {}
        L += ["**Пересечение с охраной.** Охрана закрыла "
              f"{gc.get('closed_by_guard')} позиций базы; из них буря успела "
              f"раньше у {gc.get('guard_and_storm')}, и ровно в час выхода "
              f"охраны — у {gc.get('storm_at_guard_hour')}. Позиции, где "
              "охрана сработала раньше, правило не трогает ПО ПОСТРОЕНИЮ: "
              "база уже укорочена, и бурный час после её выхода в часы жизни "
              "не попадает.", ""]
        sh = cell.get("shift") or {}
        if sh:
            L += ["**Ряд ширины, сдвинутый на сутки** (диагностика): "
                  + "; ".join(
                      f"{k} — бурных часов {v.get('storms')}, изменённых "
                      f"{v.get('changed')}, общих с правилом {v.get('common')}"
                      for k, v in sorted(sh.items()))
                  + ". Сдвинутая буря обязана давать ДРУГОЕ множество: "
                  "совпадение означало бы, что правило метит состав журнала, "
                  "а не событие.", ""]
    L += ["## Как это читать", ""]
    if cell:
        base = art.get("base") or {}
        nb = sum(int(((base.get(f"{bk}:{art.get('dep')}") or {}).get("n") or 0))
                 for bk in BOOK_KEYS)
        nr = sum(int((((cell.get("stats") or {}).get(f"{bk}:{art.get('dep')}")
                       or {}).get("n") or 0)) for bk in BOOK_KEYS)
        L += [f"- Сделок по трём книгам стало {nb} → {nr}: правило укорачивает "
              "удержание, а короткая сделка раньше освобождает кассу — книга "
              "торгует БОЛЬШЕ. Деньги книги двигает и это, не только спасённый "
              "хвост; поэтому Σ долей маржи стоит отдельно со своим контролем."]
    L += ["- Разница правила живёт в днях бури: вне их книга НЕ ТРОНУТА, и "
          "«лучше в большинстве дней» здесь неприменимо — судят «$ без 3 "
          "лучших дней» и случайные часы с тем же часом суток.",
          "- Ось правилом не становится: право на итерацию одно. Сестра, если "
          f"владелец её заведёт, берёт СЕРЕДИНУ оси ({100 * q:.0f} %) — не "
          "лучшую ячейку.",
          "- «Бури не было» и «час не измерим» — разные строки: первое стоит "
          "числом бурных часов, второе — прочерком ширины.",
          "- Деньги нетто: издержки применены к каждой сделке "
          f"({'да' if not art.get('costs_error') else 'НЕТ — ' + str(art.get('costs_error'))}).",
          f"- Открытых записей, которых правило не касается: "
          f"{art.get('open_skipped')} (исход ещё не известен, и отметка "
          "открытой позиции в счёт книги не идёт).",
          f"- Расчёт: {art.get('computed_at')}, {art.get('secs')} с, "
          f"позиций {art.get('n')}.", ""]
    return "\n".join(L)
