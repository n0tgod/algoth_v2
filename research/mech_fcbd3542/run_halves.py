#!/usr/bin/env python3
"""
Механика `fcbd3542` — отскок первых секунд по половинам универсума.

Дешёвый потолок заявки: тот же реплей записи B1, что и в D1, но каждое
событие несёт метку своего имени — шаг цены в единицах волатильности
(`ticksig.py`). Вопрос один: сосредоточен ли измеренный D1 отскок
(+26.2 б.п. валовых при круге 17.4) в половине с МЕЛКИМ шагом.

**Это диагностика, а не вердикт.** Вердикт по заявке выносит потолок
фабрики и владелец; здесь считаются числа, каждое из которых способно
заявку закрыть.

Второй копии ядра здесь нет
---------------------------

Событие, вход, выход и одновременный фон считает `d1_seconds/detect.py`
— то же и единственное место решения, которым пользуются реплей D1 и
живой сканер. Чтение записи, отбор событий суток, ширина защитного окна,
склейка в эпизоды, сводка ячейки и круг издержек берутся у
`d1_seconds/run_d1.py`. Устойчивость дневного ряда считает
`factory/stability.py`, день выхода — `s10_policy/tournament.py`, связь
дневных денег — `factory/ceiling.py`. Своего здесь ровно три вещи:
метка, деление по ней и нули к этому делению.

Одно исключение объявлено явно. `detect.excess` возвращает фон МЕДИАНОЙ
сечения, а заявка требует обе статистики: медиана есть статистика, а не
портфель, и у случайного лонга превышение над ней положительно по
построению (Z1 намерил этот снос). Менять чужую функцию строителю
нельзя, поэтому `excess_both` считает обе — ту же `returns_matrix`, то
же исключение своей ноги, ту же маску запретов, — а её медианная ветка
**закреплена тестом на совпадение с `detect.excess` дословно**. Приём
тот же, каким Z3 держал быстрый путь рядом с образцовым: расхождение
невозможно молча.

Что печатается и в каком порядке
--------------------------------

Числа идут в порядке дешевизны, и каждое закрывает заявку само:

1. распределение `ticksig` — размах меньше порядка означает, что
   разрезать нечего;
2. превышение по половинам в ячейке вердикта и **верхняя граница**:
   лучшая половина при идеальном знании, какая лучше. Ниже трёх кругов
   издержек — закрыто без второго шага (приём S1);
3. нуль перестановки метки между именами;
4. медиана И среднее по эпизодам рядом, доля прибыльных эпизодов, число
   эпизодов на половину;
5. контроль оборота: разрез по `ticksig` ВНУТРИ половин по обороту;
6. фон обеими статистиками — медианой сечения и равновзвешенным
   средним;
7. книга по дням: медиана дня, худший день, укус;
8. диагностика — остальные ячейки сетки по половинам, естественный
   эксперимент со сменой шага, связь дневных денег с живыми книгами.

Как прогонять
-------------

Счёт идёт НА СЕРВЕРЕ заданием очереди, одним потоком и с пониженным
приоритетом: рядом работает сборщик стакана, и запись — единственное
необратимое в проекте. Память проверяется до счёта и прогон
отказывается, если не влезает в объявленную долю свободной.

    run research/mech_fcbd3542/run_halves.py --jobs 1

Цена, замеренная смоуком на этой машине: двое суток по 90 именам —
2.8 минуты (чтение записи и есть главный расход). На всей записи это
около 8 минут на сутки, то есть **4–6 часов** на тридцать пять суток
по 748 именам; пик памяти около гигабайта. Состояние пишется после
каждых суток (`HALVES-status-*.json`), отчёт публикуется самим
прогоном — прогон без следа неотличим от повисшего.

Мелкий срез для проверки дороги целиком — `.smoke.sh` рядом: свой тег,
чужой каталог артефактов, публикации нет. Смоук по содержимому
неотличим от настоящего прогона, и путать их нельзя.

Второй модуль механики — `ticksig.py` (метка tick/σ). Он публикуется
вместе с этим: приёмка и публикация берут файлы, названные негативными
контролями, а пять контролей метки указывают на него.
"""

import argparse
import json
import os
import statistics as st
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
# Пути ставятся ЗДЕСЬ и все сразу, а не по мере надобности внутри
# функций. Иначе модуль работает лишь потому, что кто-то раньше ввёз
# соседа и путь поправил за него: `book_days` зовёт `tournament`
# (s10_policy) и `trades` (s8_loop), и в сюите это держалось только
# порядком проверок по алфавиту — то есть сломалось бы от
# переименования чужой проверки.
for _p in (HERE, os.path.join(RESEARCH, "d1_seconds"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import detect as D                                          # noqa: E402
import run_d1 as R1                                         # noqa: E402
import ticksig as TS                                        # noqa: E402

# --- объявлено ДО прогона --------------------------------------------
NULL_PERMS = 200        # перестановок метки между именами
NULL_SEED = 20260904    # зерно ЧИСЛОМ: нуль, который нельзя повторить,
#                         проверяемым не является (урок R3)
SLOTS = 6               # мест в книге, объявлено формой кривой заявки
HEDGE_SYMBOL = "BTCUSDT"
CACHE = os.path.join(HERE, ".cache_ann")   # СИБЛИНГ out/, не внутри:
#   публикация коммитит `research/*/out`, и кэш ответов площадки уехал
#   бы в git целиком (так уже случилось с кэшем риск-лимитов D0).

# Индексы записи события. Первые шесть — ровно то, что ждёт
# `run_d1.summarise`, и порядок менять нельзя.
I_T, I_ROW, I_OWN, I_BGM, I_EXCM, I_WID, I_BGA, I_EXCA, I_HEDGE = range(9)


def excess_both(P, NXT, row, j, delay_sec, horizon_sec, banned,
                hedge_row=None, min_cross=D.MIN_CROSS,
                wait=D.FILL_WAIT_SEC):
    """Превышение над сечением ОБЕИМИ статистиками фона.

    Возвращает `(своя, фон_медиана, превышение_медиана, фон_среднее,
    превышение_среднее, ширина, нога хеджа)`.

    Медианная ветка обязана совпадать с `detect.excess` дословно — это
    закреплено тестом, а не обещанием. Среднее считается рядом потому,
    что торгуемая величина сравнивается с ПОРТФЕЛЕМ, а медиана сечения
    портфелем не является: Z1 намерил у случайной длинной ноги
    положительное превышение над медианой из ничего, пропорциональное
    времени удержания.
    """
    r = D.returns_matrix(P, NXT, j, delay_sec, horizon_sec, wait)
    own = float(r[int(row)])
    bg = np.array(r, copy=True)
    bg[int(row)] = np.nan                     # своя нога в фон не входит
    if banned is not None:
        bg[np.asarray(banned, dtype=bool)] = np.nan
    v = bg[np.isfinite(bg)]
    width = int(len(v))
    hedge = float("nan")
    if hedge_row is not None and 0 <= int(hedge_row) < len(r):
        hedge = float(r[int(hedge_row)])
    nan = float("nan")
    if width < int(min_cross):
        return own, nan, nan, nan, nan, width, hedge
    med, mean = float(np.median(v)), float(np.mean(v))
    exc_m = own - med if np.isfinite(own) else nan
    exc_a = own - mean if np.isfinite(own) else nan
    return own, med, exc_m, mean, exc_a, width, hedge


def measure_halves(P, NXT, rows, cols, t0, cells, hedge_row=None,
                   log=print):
    """Замер всех ячеек. Порядок ячеек — по ширине защитного окна.

    Тот же порядок, что у `run_d1.measure`, и по той же причине:
    матрица запретов на сутки — полсотни мегабайт готовой и вчетверо
    больше на время построения, и держать тридцать штук разом значило
    бы отобрать память у сборщика. Записи, которую он ведёт, докачать
    неоткуда.
    """
    out = {k: [] for k in cells}
    ban, cur = None, None
    for key in sorted(cells, key=lambda k: D.guard_sec(k[1], k[2])):
        _, delay, hor = key
        g = D.guard_sec(delay, hor)
        if g != cur:
            ban, cur = None, None            # старую отпускаем ДО новой
            ban, cur = D.guard_matrix(P.shape, rows, cols, g), g
            log(f"    защитное окно {g} с: матрица построена")
        for r, j in zip(rows, cols):
            own, bgm, em, bga, ea, w, hg = excess_both(
                P, NXT, int(r), int(j), delay, hor, ban[:, int(j)],
                hedge_row)
            out[key].append((t0 + int(j), int(r), own, bgm, em, w,
                             bga, ea, hg))
    return out


_MONTH_CACHE = {}


def month_of(ts):
    """Месяц события в UTC — то, чем метка привязана к имени.

    Ответ запоминается по НОМЕРУ СУТОК, а не по секунде: разбор даты
    зовётся десятки миллионов раз (тридцать ячеек сетки на десятки
    тысяч событий, да ещё двести перестановок нуля), и без этого он
    один стоит дороже всего замера. Ключ — сутки, потому что месяц
    внутри суток не меняется.
    """
    day = int(float(ts) // 86400)
    m = _MONTH_CACHE.get(day)
    if m is None:
        m = datetime.fromtimestamp(day * 86400.0,
                                   timezone.utc).strftime("%Y-%m")
        _MONTH_CACHE[day] = m
    return m


def episode_stats(rec, col):
    """Статистика столбца по ЭПИЗОДАМ, а не по событиям.

    Обвал накрывает рынок целиком, и сотня событий в одну минуту — одно
    наблюдение. Медиана и среднее печатаются РЯДОМ: расхождение их
    знаков и есть подпись формы фейда, которой умер зонд всплеска
    (медиана +63.6 при среднем +4.9).
    """
    if not rec:
        return {"episodes": 0, "median_bp": None, "mean_bp": None,
                "share_pos": None, "events": 0}
    t = np.array([r[I_T] for r in rec], dtype=np.float64)
    e = np.array([r[col] for r in rec], dtype=np.float64)
    ok = np.isfinite(e)
    if not ok.any():
        return {"episodes": 0, "median_bp": None, "mean_bp": None,
                "share_pos": None, "events": int(len(rec))}
    v = D.by_episode(e[ok], D.episodes(t[ok]))
    return {"episodes": int(len(v)),
            "median_bp": round(float(np.median(v)) * 1e4, 2),
            "mean_bp": round(float(np.mean(v)) * 1e4, 2),
            "share_pos": round(float(np.mean(v > 0)), 3),
            "events": int(len(rec))}


def half_of(labels, month, sym):
    """Половина имени НА МЕСЯЦ события.

    Метка помесячная, и по-другому спрашивать её нельзя: `ticksig`
    меняется от месяца к месяцу, и одно имя бывает тонким в июле и
    крупным в августе. Разрез «по имени вообще» смешал бы два разных
    состояния инструмента и выглядел бы исправным.
    """
    return (labels.get(month) or {}).get("half", {}).get(sym)


def split_records(rec, syms, labels):
    """Разложить записи по половинам месяца события.

    Возвращает `{"thin": [...], "coarse": [...], "unlabelled": [...]}`.
    Неразмеченное — ТРЕТЬЯ группа, а не молчаливое присоединение к
    одной из половин: имя без метки не есть имя с мелким шагом.
    """
    out = {"thin": [], "coarse": [], "unlabelled": []}
    for r in rec:
        sym = syms[int(r[I_ROW])]
        h = half_of(labels, month_of(r[I_T]), sym)
        out[h if h in ("thin", "coarse") else "unlabelled"].append(r)
    return out


def half_stats(rec, syms, labels):
    """Полная сводка по половинам для одной ячейки сетки."""
    parts = split_records(rec, syms, labels)
    out = {}
    for name, sub in parts.items():
        s = R1.summarise(sub) if sub else None      # чужая сводка, не своя
        med = episode_stats(sub, I_EXCM)
        mean = episode_stats(sub, I_EXCA)
        out[name] = {"d1": s, "by_median_bg": med, "by_mean_bg": mean,
                     "symbols": len({int(r[I_ROW]) for r in sub})}
    a = out["thin"]["by_median_bg"]["median_bp"]
    b = out["coarse"]["by_median_bg"]["median_bp"]
    out["diff_bp"] = None if a is None or b is None else round(a - b, 2)
    out["best_half_bp"] = None if a is None and b is None else max(
        x for x in (a, b) if x is not None)
    return out


# --- нуль перестановки метки -----------------------------------------

def index_records(rec, syms, col=I_EXCM):
    """Разложить записи один раз, чтобы нуль не делал это двести.

    Возвращает `(ключи, номер ключа у каждой записи, время, значения)`.
    Ключ — пара `(месяц, имя)`: метка помесячная, и фильтр по имени
    вообще сложил бы два состояния инструмента в одно.

    Без этого шага перестановочный нуль пересобирал бы месяц каждой
    записи на каждой перестановке — на живой записи это десятки
    миллионов разборов даты, то есть замер, который дороже прогона.
    """
    keys, kid = [], []
    seen = {}
    for r in rec:
        k = (month_of(r[I_T]), syms[int(r[I_ROW])])
        i = seen.get(k)
        if i is None:
            i = seen[k] = len(keys)
            keys.append(k)
        kid.append(i)
    return (keys, np.array(kid, dtype=np.int64),
            np.array([r[I_T] for r in rec], dtype=np.float64),
            np.array([r[col] for r in rec], dtype=np.float64))


def _median_of(idx, want):
    """Медиана по эпизодам среди записей, чей ключ в `want`."""
    keys, kid, t, v = idx
    if len(kid) == 0:
        return None
    pick = np.array([k in want for k in keys], dtype=bool)
    sel = pick[kid] & np.isfinite(v)
    if not sel.any():
        return None
    ep = D.episodes(t[sel])
    return round(float(np.median(D.by_episode(v[sel], ep))) * 1e4, 2)


def _half_median(rec, syms, want, col=I_EXCM):
    """То же одним вызовом — для мест, где перестановок нет."""
    return _median_of(index_records(rec, syms, col), want)


def permutation_null(rec, syms, labels, perms=NULL_PERMS, seed=NULL_SEED,
                     col=I_EXCM):
    """Нуль: метка `ticksig` переставлена МЕЖДУ ИМЕНАМИ внутри месяца.

    Переставляется именно метка, а не события: состав событий, их
    моменты, фон и слипание в эпизоды остаются теми же, меняется ровно
    то, чем имена делятся пополам. Разность половин, не перебивающая
    95-й процентиль такого нуля, означает, что переменная не разделяет
    ничего.

    Зерно — число, и это не педантизм: в R3 нуль брался от `hash`
    строки, а он солится на каждый процесс, и два прогона одного кода
    на одних данных давали разные нули при комментарии «результат
    воспроизводим».
    """
    rng = np.random.default_rng(int(seed))
    months = {}
    for m, rec_m in labels.items():
        vals = rec_m.get("values") or {}
        if len(vals) >= 2:
            months[m] = (list(vals.keys()), np.array(list(vals.values()),
                                                     dtype=np.float64))
    if not months:
        return {"perms": 0, "p95": None, "mean": None, "observed": None,
                "beats": None}
    idx = index_records(rec, syms, col)
    obs_thin, obs_coarse = set(), set()
    for m, r_m in labels.items():
        for s, h in (r_m.get("half") or {}).items():
            (obs_thin if h == "thin" else obs_coarse).add((m, s))
    a = _median_of(idx, obs_thin)
    b = _median_of(idx, obs_coarse)
    observed = None if a is None or b is None else round(a - b, 2)
    draws = []
    for _ in range(int(perms)):
        thin, coarse = set(), set()
        for m, (names, vals) in months.items():
            v = rng.permutation(vals)
            med = float(np.median(v))
            for s, x in zip(names, v):
                (thin if x < med else coarse).add((m, s))
        x = _median_of(idx, thin)
        y = _median_of(idx, coarse)
        if x is not None and y is not None:
            draws.append(x - y)
    if not draws:
        return {"perms": 0, "p95": None, "mean": None, "observed": observed,
                "beats": None}
    d = np.array(draws, dtype=np.float64)
    p95 = float(np.percentile(d, 95))
    return {"perms": int(len(d)), "p95": round(p95, 2),
            "mean": round(float(d.mean()), 2),
            "sd": round(float(d.std(ddof=1)), 2) if len(d) > 1 else None,
            "observed": observed,
            "beats": None if observed is None else bool(observed > p95)}


def turnover_control(rec, syms, labels):
    """Разрез по `ticksig` ВНУТРИ половин по обороту.

    Убийца (5) заявки: если внутри каждой половины по обороту метка не
    разделяет, то переменная есть ликвидность в новом костюме, а деление
    по обороту уже среди закрытых конструкций обстановки.
    """
    groups = {"low_turnover": (set(), set()), "high_turnover": (set(), set())}
    for m, r_m in labels.items():
        vals = r_m.get("values") or {}
        turn = r_m.get("turnover") or {}
        both = {s: (vals[s], turn[s]) for s in vals
                if turn.get(s) is not None}
        if len(both) < 4:
            continue
        tmed = st.median(v[1] for v in both.values())
        for gname, pick in (("low_turnover", lambda x: x < tmed),
                            ("high_turnover", lambda x: x >= tmed)):
            sub = {s: v[0] for s, v in both.items() if pick(v[1])}
            if len(sub) < 2:
                continue
            gmed = st.median(sub.values())
            thin, coarse = groups[gname]
            for s, v in sub.items():
                (thin if v < gmed else coarse).add((m, s))
    out = {}
    idx = index_records(rec, syms)
    for gname, (thin, coarse) in groups.items():
        a = _median_of(idx, thin)
        b = _median_of(idx, coarse)
        out[gname] = {"thin_bp": a, "coarse_bp": b, "names_thin": len(thin),
                      "names_coarse": len(coarse),
                      "diff_bp": None if a is None or b is None
                      else round(a - b, 2)}
    return out


# --- книга по дням ----------------------------------------------------

def book_trades(rec, syms, want, delay_sec, horizon_sec, ring_bp,
                slots=SLOTS, hedged=False, hedge_ring_bp=0.0):
    """Сделки книги: шесть мест, одна позиция на имя, вход по времени.

    `want` — множество пар `(месяц, имя)`, то есть половина берётся на
    месяц события, а не «по имени вообще».

    Мера — ГОЛАЯ нога (`own`), а не превышение: превышение есть
    доходность захеджированной ноги, а живая книга голая и в каскадный
    день несёт рынок. Хеджированный вариант считается рядом
    диагностикой формы и платит собственный круг.
    """
    legs = []
    for r in rec:
        if (month_of(r[I_T]), syms[int(r[I_ROW])]) not in want:
            continue
        move = r[I_OWN] - r[I_HEDGE] if hedged else r[I_OWN]
        if not np.isfinite(move):
            continue
        at = float(r[I_T]) + int(delay_sec)
        legs.append({"at": at, "exit": at + int(horizon_sec),
                     "sym": syms[int(r[I_ROW])],
                     "net": float(move) * 1e4 - float(ring_bp)
                     - (float(hedge_ring_bp) if hedged else 0.0)})
    legs.sort(key=lambda x: x["at"])
    book, trades = {}, []
    for lg in legs:
        for s, e in list(book.items()):
            if e <= lg["at"]:
                del book[s]
        if lg["sym"] in book or len(book) >= int(slots):
            continue
        book[lg["sym"]] = lg["exit"]
        trades.append(lg)
    return trades


def book_days(trades, cap_share=None):
    """Дневной ряд книги в ПРОЦЕНТАХ капитала и его устойчивость.

    День сделки — день ВЫХОДА, тем же правилом, что у лиги и турнира:
    сделка принадлежит суткам, когда деньги стали известны. Размер ноги
    — потолок на имя из забора проекта, а не своё число: при шести
    местах равная доля (1/6) крупнее потолка, значит связывает потолок.
    """
    import tournament as TN
    import stability as SB
    if cap_share is None:
        import trades as TR
        cap_share = TR.NAME_CAP_SHARE
    daily = TN.daily(trades)
    pct = {d: v[0] * float(cap_share) / 100.0 for d, v in daily.items()}
    return pct, SB.stats(pct)


def require_events(rec, days, symbols):
    """Ноль наблюдений при непустом входе — ОТКАЗ, а не отчёт.

    Пустота не вправе выдавать себя за результат: отчёт с прочерками по
    всем ячейкам читается как «эффекта нет», хотя означает «мера не
    построена». Проект уже печатал такой отчёт дважды — зашитая
    пятиминутная сетка в загрузчике цен и вырожденная колонка форварда
    в T2, — и оба раза его спасала только сверка с логом.
    """
    if rec:
        return len(rec)
    raise SystemExit(
        f"ОТКАЗ: в ячейке вердикта нет ни одного события при {days} "
        f"сутках записи и {symbols} символах. Ноль наблюдений при "
        f"непустом входе — отказ, а не отчёт с прочерками.")


def active_share(pct, record_days):
    """Доля суток записи хотя бы с одной закрытой сделкой.

    Третья величина потолка фабрики: кандидат, закрывающий сделки
    залпом в редкие дни, по форме неизмерим при любой скорости сделок,
    а слот занимает. Порог берётся У ПОТОЛКА, а не повторяется числом.
    """
    if not record_days:
        return None
    return round(len(pct) / float(record_days), 3)


# --- калибровочная пара ----------------------------------------------

def synthetic(n_event=40, n_quiet=90, n_sec=20000, rebound=0.02,
              planted=True, seed=7, drop=0.05):
    """Подставной день: половина имён отскакивает, половина нет.

    Нужна не для красоты. Сломанная загрузка выглядит ровно как
    «эффекта нет» — так в зонде дней недели молчащая мера читалась бы
    отрицательным результатом. Поэтому машина обязана НАХОДИТЬ
    подсаженный отскок и МОЛЧАТЬ на случайном блуждании, и обе половины
    пары гоняются одним кодом.

    Возвращает `(P, syms, ticksig)`, где `ticksig` подобран так, что
    отскакивающие имена попадают в тонкую половину.
    """
    rng = np.random.default_rng(int(seed))
    rows = int(n_event) + int(n_quiet)
    base = 100.0 * np.exp(np.cumsum(
        rng.normal(0, 1e-5, size=(rows, int(n_sec))), axis=1))
    P = base.astype(np.float64)
    syms = [f"E{i:03d}USDT" for i in range(int(n_event))] + \
           [f"Q{i:03d}USDT" for i in range(int(n_quiet))]
    ticksig = {}
    half = int(n_event) // 2
    for i in range(int(n_event)):
        # Первая половина событийных имён — «тонкая» (мелкий шаг).
        ticksig[syms[i]] = 1.0 if i < half else 9.0
    for i in range(int(n_quiet)):
        ticksig[syms[int(n_event) + i]] = 1.0 + 8.0 * ((i % 2) == 1)
    # Хвост оставляется с запасом: последнему событию нужны и окно
    # падения, и задержка, и всё удержание, иначе отскок обрезается
    # краем массива и подсадка выходит слабее объявленной.
    tail = D.W_SEC + D.VERDICT_CELL["delay_sec"] + \
        D.VERDICT_CELL["horizon_sec"] + 100
    starts = list(range(1200, max(1800, int(n_sec) - tail), 1800))
    for k, t_ev in enumerate(starts):
        for i in range(int(n_event)):
            a, b = t_ev, t_ev + D.W_SEC
            ramp = np.linspace(0.0, -float(drop), b - a)
            P[i, a:b] *= (1.0 + ramp)
            P[i, b:] *= (1.0 - float(drop))
            if planted and i < half:
                c = b + 5 + 1800
                up = np.linspace(0.0, float(rebound), c - b)
                P[i, b:c] *= (1.0 + up)
                P[i, c:] *= (1.0 + float(rebound))
    return P, syms, ticksig


def calibrate(planted=True, seed=7, **kw):
    """Прогнать пару на подставном дне. Возвращает разность половин."""
    P, syms, ts = synthetic(planted=planted, seed=seed, **kw)
    if not planted:
        # На случайном блуждании метка перемешивается: проверяется, что
        # мера молчит и когда эффекта нет, и когда метка ни при чём.
        rng = np.random.default_rng(int(seed) + 1)
        vals = rng.permutation(list(ts.values()))
        ts = dict(zip(ts.keys(), vals))
    P32 = P.astype(np.float32)
    NXT = R1.next_index(P32)
    rows, cols = R1.events_of_day(P32, 0, D.VERDICT_CELL["drop"], {}, 0,
                                  P32.shape[1])
    if len(rows) == 0:
        return {"diff_bp": None, "thin_bp": None, "coarse_bp": None,
                "events": 0}
    key = (D.VERDICT_CELL["drop"], D.VERDICT_CELL["delay_sec"],
           D.VERDICT_CELL["horizon_sec"])
    got = measure_halves(P32, NXT, rows, cols, 0, [key], log=lambda *_: None)
    med = st.median(ts.values())
    labels = {month_of(0): {
        "values": dict(ts),
        "half": {s: ("thin" if v < med else "coarse") for s, v in ts.items()},
        "turnover": {}}}
    h = half_stats(got[key], syms, labels)
    return {"diff_bp": h["diff_bp"],
            "thin_bp": h["thin"]["by_median_bg"]["median_bp"],
            "coarse_bp": h["coarse"]["by_median_bg"]["median_bp"],
            "events": len(rows)}


# --- естественный эксперимент и связь с живыми книгами ----------------

TICK_CHANGE_HINT = "tick size"


def announcements(cache=CACHE):
    """Объявления площадки. Отдельной функцией, чтобы её подменяли.

    Сеть в проверках не участвует: живой эндпоинт делает проверку
    медленной, зависимой от связи и — хуже — оставляет ветку отказа
    неисполненной, а значит непроверенной. Ровно на этом первый заход
    и попался: контроль на выдумку списка не кусался, потому что
    площадка отвечала.
    """
    sys.path.insert(0, os.path.join(RESEARCH, "common"))
    import venue as V
    url = ("https://api.bybit.com/v5/announcements/index"
           "?locale=en-US&limit=50&page=1")
    raw = V.fetch(url, cache, cache_key="ann-1")
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return (data.get("result") or {}).get("list") or []


def tick_change_symbols(known, path=None, cache=CACHE, fetch=None):
    """Имена, у которых площадка меняла шаг цены 11.08.2026.

    Список либо снимается с публичного эндпоинта объявлений, либо
    подаётся файлом. Не снялся — возвращается `None`, и эксперимент
    печатается «не измерено». **Выдумать список нельзя ни при каких
    условиях**: пустое место, названное словом, лечится за день, а
    выдуманное число живёт в выводах месяцами.
    """
    if path and os.path.exists(path):
        got = [s.strip().upper() for s in open(path, encoding="utf-8")
               if s.strip()]
        return sorted({s for s in got if s in known}), "файл"
    try:
        items = (fetch or announcements)(cache)
    except Exception as e:                                  # noqa: BLE001
        return None, f"эндпоинт объявлений не ответил ({type(e).__name__})"
    hit = set()
    for it in items or []:
        text = f"{it.get('title', '')} {it.get('description', '')}"
        if TICK_CHANGE_HINT not in text.lower():
            continue
        for s in known:
            if s in text:
                hit.add(s)
    if not hit:
        return None, "в снятых объявлениях смены шага не найдено"
    return sorted(hit), "объявления площадки"


def tick_change_at():
    """Момент смены шага цены, объявленный заявкой: 11.08.2026 08:30 UTC."""
    return datetime(2026, 8, 11, 8, 30, tzinfo=timezone.utc).timestamp()


def _median_mask(t, v, mask):
    """Медиана по эпизодам под маской. Пусто — «не измерено»."""
    sel = np.asarray(mask, dtype=bool) & np.isfinite(v)
    if not sel.any():
        return None, 0
    ep = D.episodes(t[sel])
    got = D.by_episode(v[sel], ep)
    return round(float(np.median(got)) * 1e4, 2), int(len(got))


def tick_change_experiment(rec, syms, changed, at_ts=None, col=I_EXCM):
    """Естественный эксперимент: имена со сменой шага против соседей.

    Площадка меняет шаг цены по объявлению, то есть переменная
    двигается САМА, без нашего отбора. Если механизм заявки настоящий,
    у сменивших шаг превышение обязано измениться, а у одновременного
    контроля без смены — нет.

    Диагностика, и только: смена шага случилась однажды, контроль не
    рандомизирован, а окно «до» короче окна «после». Вердикт на неё не
    опирается — это записано в отчёте.
    """
    if not changed:
        return None
    at = float(at_ts if at_ts is not None else tick_change_at())
    t = np.array([r[I_T] for r in rec], dtype=np.float64)
    v = np.array([r[col] for r in rec], dtype=np.float64)
    ch = np.array([syms[int(r[I_ROW])] in set(changed) for r in rec],
                  dtype=bool)
    out = {"at": at, "symbols": sorted(changed)}
    for name, m in (("before_bp", ch & (t < at)),
                    ("after_bp", ch & (t >= at)),
                    ("control_before_bp", ~ch & (t < at)),
                    ("control_after_bp", ~ch & (t >= at))):
        out[name], out[name.replace("_bp", "_episodes")] = \
            _median_mask(t, v, m)
    return out


def killers(art):
    """Условия, каждое из которых закрывает заявку. Фразы ИЗ ЧИСЕЛ.

    Отдельным блоком, а не «видно из таблицы»: таблица показывает
    величины, а вопрос заявки — прошла она или нет, и ответ обязан
    выводиться из числа, а не стоять рядом с ним литералом.
    """
    v = art["verdict"]
    ring = float(art["cost_round_bp"])
    need = 3.0 * ring
    thin = v["thin"]["by_median_bg"]
    best = v["best_half_bp"]
    out = {}

    out["1. величина"] = (
        "не измерено" if best is None else
        f"лучшая половина при идеальном знании {best:+.1f} б.п. против "
        f"{need:.1f} требуемых — "
        + ("НЕ ПРОХОДИТ, направление закрыто" if best < need
           else "проходит"))

    n = art["null"]
    out["2. нуль перестановки"] = (
        "не измерено" if n.get("beats") is None else
        f"разность {n['observed']:+.1f} против 95-го процентиля "
        f"{n['p95']:+.1f} — "
        + ("выше, метка что-то разделяет" if n["beats"]
           else "НЕ ВЫШЕ, метка не разделяет ничего"))

    d = v.get("diff_bp")
    out["3. знак разделения"] = (
        "не измерено" if d is None else
        f"тонкая минус крупная {d:+.1f} б.п. — "
        + ("знак ОБРАТНЫЙ заявленному: больше отскока там, где шаг "
           "крупнее" if d < 0 else "знак тот, что заявлен"))

    med, mean = thin.get("median_bp"), thin.get("mean_bp")
    pos = thin.get("share_pos")
    if med is None or mean is None:
        out["4. форма"] = "не измерено"
    else:
        agree = (med > 0) == (mean > 0)
        out["4. форма"] = (
            f"в тонкой половине медиана {med:+.1f}, среднее {mean:+.1f}, "
            f"доля прибыльных эпизодов "
            f"{'—' if pos is None else f'{pos:.2f}'} — "
            + ("медиана и среднее РАСХОДЯТСЯ ЗНАКОМ: форма фейда, "
               "которой умер зонд всплеска" if not agree else
               ("доля прибыльных ниже 0.60"
                if pos is not None and pos < 0.60
                else "медиана и среднее согласны, доля прибыльных "
                     "не ниже 0.60")))

    t = art["turnover"]
    ds = [t[g].get("diff_bp") for g in ("low_turnover", "high_turnover")]
    got = [x for x in ds if x is not None]
    # «Не измерено» и «не разделяет» — разные ответы, и склеивать их
    # нельзя: одна измеренная половина из двух не даёт права сказать
    # «ни в одной». Найдено на смоуке, где вторая половина молчала, а
    # фраза уже утверждала за обе.
    out["5. контроль оборота"] = (
        "не измерено ни в одной половине по обороту" if not got else
        "разрез внутри половин по обороту: "
        + ", ".join(f"{x:+.1f}" for x in got) + " б.п. "
        + (f"(измерена {len(got)} половина из 2) " if len(got) < 2 else "")
        + "— "
        + (("НИ В ОДНОЙ не разделяет: переменная есть ликвидность в "
            "новом костюме" if len(got) == 2 else
            "в измеренной не разделяет, вторая молчит — этого мало для "
            "вывода") if all(x <= 0 for x in got)
           else "разделяет хотя бы в одной"))

    b = art.get("book") or {}
    a_sh, a_need = b.get("active_share"), b.get("active_need")
    out["измеримость формы"] = (
        "не измерено" if a_sh is None or a_need is None else
        f"сделки закрывались в {a_sh} доле суток при пороге "
        f"{a_need:.2f} — "
        + ("выполнено" if a_sh >= a_need else "НЕ выполнено"))
    return out


FACTORY_DAY = os.path.join(RESEARCH, "factory", "out", "factory-day-1m.json")


def link_to_pool(pct, path=FACTORY_DAY):
    """Связь дневных денег реплея с кандидатами пула.

    Связь считает `ceiling.pair_corr` — тем же кодом, которым фабрика
    судит независимость заявок, а дневные ряды берутся из ЕЁ ЖЕ
    суточного артефакта, а не спрашиваются у сервера по HTTP. Первый
    заход спрашивал `stability.live_rows`, и это было прямой ошибкой:
    та функция отдаёт СВОДКУ (`st`), а не дневной ряд, — то есть связь
    считалась бы по пустому словарю и печаталась бы прочерком, выглядя
    измеренной. Поймано чтением её кода до долгого прогона.

    Нечего читать — «не измерено», а не ноль: ноль здесь читался бы как
    «книги независимы», то есть как разрешение объявлять.

    ВЕСЬ разбор внутри `try`: этот шаг последний в пятичасовом прогоне,
    и падение на нём стоит всей работы — ровно так A1 теряла обход с
    ключом на подписи последнего запроса.
    """
    try:
        import ceiling as CE
        run = json.load(open(path, encoding="utf-8"))
        cands = (run.get("candidates") or {})
        mine = {str(k): float(v) for k, v in (pct or {}).items()}
        if not mine:
            return None, "у реплея нет ни одних суток со сделками"
        if not cands:
            return None, "в суточном артефакте фабрики нет кандидатов"
        out = {}
        for cid, c in cands.items():
            days = CE._days(c.get("daily"))
            r, n = CE.pair_corr({str(k): v for k, v in days.items()}, mine)
            out[cid] = {"corr": None if r is None else round(r, 3),
                        "days": n}
        return out, (f"кандидаты суточного прогона фабрики, "
                     f"{os.path.basename(path)}")
    except Exception as e:                                  # noqa: BLE001
        return None, f"не измерено ({type(e).__name__}: {e})"


# --- отчёт ------------------------------------------------------------

def fmt(x, plus=True):
    if x is None:
        return "—"
    return f"{x:+.1f}" if plus else f"{x:.1f}"


def report(art, path):
    a = art
    L = ["# Механика fcbd3542 — отскок первых секунд по половинам "
         "универсума\n",
         f"Прогон: {a['run_at']}. Заявка `fcbd3542`, дешёвый потолок.\n",
         "**Это диагностика, а не вердикт.** Числа валовые там, где так "
         "сказано; круг издержек назван и вычтен только там, где это "
         "оговорено. Ячейка вердикта объявлена заявкой ДО прогона и "
         "одна; остальные ячейки сетки — диагностика распада, "
         "предъявлять лучшую из них запрещено (урок R5).\n"]

    L.append("## 1. Что прочитано\n")
    L.append(f"- суток записи: **{a['days']}** ({a['day_from']} … "
             f"{a['day_to']}), символов **{a['symbols']}**")
    L.append(f"- шаг записи: снимок раз в **{a['cadence_sec']} с**")
    L.append(f"- прогон занял {a['took_min']} мин\n")

    lab = a["labels"]
    L.append("## 2. Метка: шаг цены в единицах волатильности\n")
    L.append("Окно метки — тридцать суток, кончающихся в полночь первого "
             "дня месяца события: ни один бар самого месяца в неё не "
             "входит.\n")
    L.append("| месяц | окно | размечено | без метки | медиана | 5-й | "
             "95-й | размах |")
    L.append("|---|---|---|---|---|---|---|---|")
    for m in sorted(lab):
        r = lab[m]
        L.append(f"| {m} | {r['window'][0]} … {r['window'][1]} | "
                 f"{r['labelled']} | {r['unlabelled']} | "
                 f"{r['median']} | {r['p05']} | {r['p95']} | "
                 f"{r['span']} |")
    L.append("")
    span = a["span_overall"]
    L.append(f"Размах по всем месяцам: **{span}×** — "
             + ("меньше порядка, разрезать нечего, заявка закрыта здесь"
                if span is not None and span < 10 else
                "больше порядка, деление осмысленно")
             + ".\n")
    if a["label_why"]:
        L.append("Почему имя осталось без метки:\n")
        for why, cnt in sorted(a["label_why"].items(), key=lambda x: -x[1]):
            L.append(f"- {why}: {cnt}")
        L.append("")

    v = a["verdict"]
    L.append("## 3. Ячейка вердикта по половинам\n")
    L.append(f"Падение {int(a['verdict_cell']['drop'] * 100)} % за 15 "
             f"минут, задержка {a['verdict_cell']['delay_sec']} с, "
             f"удержание {a['verdict_cell']['horizon_sec'] // 60} минут. "
             f"Фон — медиана сечения (как в D1) и равновзвешенное "
             f"среднее рядом.\n")
    L.append("| половина | эпизодов | событий | имён | медиана (фон "
             "медианой) | среднее | доля > 0 | медиана (фон средним) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name, title in (("thin", "тонкая (мелкий шаг)"),
                        ("coarse", "крупная"),
                        ("unlabelled", "без метки")):
        h = v[name]
        m, mm = h["by_median_bg"], h["by_mean_bg"]
        L.append(f"| {title} | {m['episodes']} | {m['events']} | "
                 f"{h['symbols']} | {fmt(m['median_bp'])} | "
                 f"{fmt(m['mean_bp'])} | "
                 f"{'—' if m['share_pos'] is None else m['share_pos']} | "
                 f"{fmt(mm['median_bp'])} |")
    L.append("")
    L.append(f"Разность половин: **{fmt(v['diff_bp'])} б.п.** "
             f"(тонкая минус крупная).\n")

    ring = a["cost_round_bp"]
    need = 3.0 * ring
    best = v["best_half_bp"]
    L.append(f"**Верхняя граница.** Круг издержек {ring:.1f} б.п. "
             f"({a['cost_source']}); критерий 4 спеки 11 требует нетто не "
             f"меньше двойного круга, то есть валового **{need:.1f} б.п.** "
             f"Лучшая половина ПРИ ИДЕАЛЬНОМ ЗНАНИИ, какая лучше — "
             f"{fmt(best)} б.п.: "
             + ("ниже требуемого, и второго шага не нужно — направление "
                "закрыто самым дешёвым числом"
                if best is None or best < need else
                "требуемое перекрыто, замер продолжается") + ".\n")

    L.append("**Что закрывает заявку.** Каждое условие названо ДО "
             "прогона; фраза выводится из числа, а не стоит рядом с "
             "ним.\n")
    # Артефакт прежнего образца этого блока не несёт. Тогда так и
    # сказано: отчёт обязан описывать ТОТ прогон, который породил файл,
    # и падать на его возрасте не вправе (урок R1 и листа турнира).
    for k, s in (a.get("killers") or {}).items():
        L.append(f"- **{k}**: {s}")
    if not a.get("killers"):
        L.append("- *не измерено: артефакт сделан до появления блока*")
    L.append("")

    n = a["null"]
    L.append("## 4. Нуль перестановки метки\n")
    L.append(f"Метка переставлена между именами внутри месяца, "
             f"{n['perms']} перестановок, зерно {NULL_SEED} числом. "
             f"Состав событий, их моменты и фон при этом те же — меняется "
             f"ровно то, чем имена делятся пополам.\n")
    L.append(f"- наблюдённая разность: **{fmt(n['observed'])} б.п.**")
    L.append(f"- нуль: среднее {fmt(n['mean'])}, 95-й процентиль "
             f"{fmt(n['p95'])} б.п.")
    L.append("- вывод: " + ("не измерено" if n["beats"] is None else
                            ("разность выше 95-го процентиля нуля"
                             if n["beats"] else
                             "разность НЕ выше 95-го процентиля нуля — "
                             "переменная не разделяет ничего")) + "\n")

    t = a["turnover"]
    L.append("## 5. Контроль оборота\n")
    L.append("Разрез по метке ВНУТРИ половин по обороту. Если метка не "
             "разделяет ни в одной, переменная есть ликвидность в новом "
             "костюме, а деление по обороту уже среди закрытых "
             "конструкций обстановки.\n")
    L.append("| половина по обороту | имён тонких | имён крупных | тонкая | "
             "крупная | разность |")
    L.append("|---|---|---|---|---|---|")
    for g, title in (("low_turnover", "низкий оборот"),
                     ("high_turnover", "высокий оборот")):
        r = t[g]
        L.append(f"| {title} | {r['names_thin']} | {r['names_coarse']} | "
                 f"{fmt(r['thin_bp'])} | {fmt(r['coarse_bp'])} | "
                 f"{fmt(r['diff_bp'])} |")
    L.append("")

    L.append("## 6. Калибровочная пара\n")
    c = a["calibration"]
    L.append(f"- подсаженный отскок в тонкой половине: разность "
             f"**{fmt(c['planted']['diff_bp'])} б.п.** "
             f"({c['planted']['events']} событий) — мера обязана его "
             f"находить")
    L.append(f"- случайное блуждание, метка перемешана: разность "
             f"**{fmt(c['random']['diff_bp'])} б.п.** — мера обязана "
             f"молчать")
    L.append("\nБез этой пары сломанная загрузка выглядела бы ровно как "
             "«эффекта нет».\n")

    L.append("## 7. Книга по дням: форма кривой\n")
    b = a["book"]
    if not b.get("naked"):
        L.append("Не измерено: сделок в тонкой половине нет.\n")
    else:
        L.append(f"Шесть мест, одна позиция на имя, размер — потолок на "
                 f"имя {b['cap_share']:.0%} капитала, вход по времени "
                 f"события. Единица — проценты капитала. Издержки "
                 f"вычтены ({ring:.1f} б.п. на ногу).\n")
        L.append("| книга | суток | сделок | доля зелёных | медиана дня | "
                 "худший день | укус | просадка | итог |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for k, title in (("naked", "тонкая половина, голая нога"),
                         ("hedged", "она же с шортом BTC (диагностика)"),
                         ("coarse", "крупная половина, голая нога")):
            s = b.get(k)
            if not s:
                L.append(f"| {title} | — | — | — | — | — | — | — | — |")
                continue
            L.append(f"| {title} | {s['days']} | {s['trades']} | "
                     f"{s['green']} | {fmt(s['med'])} | {fmt(s['worst'])} | "
                     f"{'—' if s['bite'] is None else s['bite']} | "
                     f"{fmt(s['dd'])} | {fmt(s['tot'])} |")
        L.append("")
        L.append(f"Измеримость формы: сделки закрывались в "
                 f"**{b['active_share']}** доле суток записи при пороге "
                 f"потолка {b['active_need']:.2f} — "
                 + ("выполнено" if b["active_share"] is not None
                    and b["active_share"] >= b["active_need"]
                    else "НЕ выполнено") + ".\n")
        L.append(f"Правило вылета пула по форме сказало бы: "
                 f"**{b['shape_why'] or 'ничего — форма проходит'}**.\n")

    L.append("## 8. Диагностика\n")
    L.append("### Остальные ячейки сетки по половинам\n")
    L.append("Медиана превышения по эпизодам, тонкая / крупная, б.п. "
             "Предъявлять лучшую запрещено.\n")
    for drop in a["drops"]:
        L.append(f"\n**Падение {int(drop * 100)} %**\n")
        L.append("| удержание | " + " | ".join(f"δ = {d} с"
                                               for d in a["delays"]) + " |")
        L.append("|---" * (len(a["delays"]) + 1) + "|")
        for hor in a["horizons"]:
            row = []
            for d in a["delays"]:
                c2 = a["cells"].get(f"{drop}|{d}|{hor}")
                if not c2:
                    row.append("—")
                    continue
                row.append(
                    f"{fmt(c2['thin']['by_median_bg']['median_bp'])} / "
                    f"{fmt(c2['coarse']['by_median_bg']['median_bp'])}")
            L.append(f"| {hor // 60} мин | " + " | ".join(row) + " |")
    L.append("")
    L.append("### Естественный эксперимент: смена шага цены\n")
    tc = a["tick_change"]
    ex = tc.get("experiment")
    if not tc.get("symbols"):
        L.append(f"**Не измерено** — {tc.get('why')}. Вердикт на этот "
                 f"эксперимент не опирается.\n")
    elif not ex:
        L.append(f"Имён со сменой шага: {len(tc['symbols'])} "
                 f"({tc.get('why')}), но **замер не построен** — "
                 f"событий у этих имён в записи нет.\n")
    else:
        L.append(f"Имён со сменой шага: {len(tc['symbols'])} "
                 f"({tc.get('why')}). Медиана превышения по эпизодам, "
                 f"б.п.:\n")
        L.append("| группа | до смены | эпизодов | после | эпизодов |")
        L.append("|---|---|---|---|---|")
        L.append(f"| сменили шаг | {fmt(ex.get('before_bp'))} | "
                 f"{ex.get('before_episodes')} | "
                 f"{fmt(ex.get('after_bp'))} | "
                 f"{ex.get('after_episodes')} |")
        L.append(f"| одновременный контроль | "
                 f"{fmt(ex.get('control_before_bp'))} | "
                 f"{ex.get('control_before_episodes')} | "
                 f"{fmt(ex.get('control_after_bp'))} | "
                 f"{ex.get('control_after_episodes')} |")
        L.append("\nДиагностика, и только: смена случилась однажды, "
                 "контроль не рандомизирован, окно «до» короче окна "
                 "«после». Вердикт на неё не опирается.\n")
    L.append("### Связь дневных денег с кандидатами пула\n")
    lk = a["link"]
    if not isinstance(lk, dict) or not lk:
        L.append(f"**Не измерено** — {a.get('link_why')}.\n")
    else:
        L.append(f"Источник: {a.get('link_why')}. Прочерк — общих суток "
                 f"меньше порога пары, то есть НЕ ИЗМЕРЕНО, а не ноль.\n")
        L.append("| кандидат | связь | общих суток |")
        L.append("|---|---|---|")
        for k, r in sorted(lk.items()):
            L.append(f"| {k} | {'—' if r['corr'] is None else r['corr']} "
                     f"| {r['days']} |")
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


# --- прогон -----------------------------------------------------------

_LAST = {}


def write_status(out, tag, status):
    """Состояние прогона отдельным файлом, атомарно и ПОСЛЕ КАЖДЫХ суток.

    Часовой прогон без следа неотличим от повисшего — это стоило D1
    круга переписки на угадывание.
    """
    p = os.path.join(out, f"HALVES-status-{tag}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def build_labels(months, syms, con=None, min_obs=TS.MIN_OBS):
    """Метки по месяцам записи. Возвращает `{месяц: {...}}`."""
    close = TS.closes_loader(con)
    turn = TS.turnover_loader(con)
    out = {}
    for m in months:
        lab, win = TS.build(m, syms, close, turn, min_obs=min_obs)
        thin, coarse, med = TS.halves(lab)
        vals = {s: r["ticksig"] for s, r in lab.items()
                if r.get("ticksig") is not None}
        why = {}
        for r in lab.values():
            if r.get("ticksig") is None:
                why[r.get("why") or "без причины"] = \
                    why.get(r.get("why") or "без причины", 0) + 1
        arr = sorted(vals.values())
        out[m] = {
            "window": list(win), "values": vals,
            "turnover": {s: r["turnover"] for s, r in lab.items()
                         if r.get("turnover") is not None},
            "half": {**{s: "thin" for s in thin},
                     **{s: "coarse" for s in coarse}},
            "labelled": len(vals), "unlabelled": len(lab) - len(vals),
            "why": why,
            "median": None if med is None else float(f"{med:.4g}"),
            "p05": float(f"{arr[int(0.05 * len(arr))]:.4g}") if arr else None,
            "p95": float(f"{arr[min(int(0.95 * len(arr)), len(arr) - 1)]:.4g}")
            if arr else None,
            "span": round(arr[-1] / arr[0], 1) if arr and arr[0] > 0 else None,
        }
    return out


def main():
    try:
        return _run()
    except SystemExit:
        raise
    except BaseException as e:                              # noqa: BLE001
        import traceback
        out, tag = _LAST.get("out"), _LAST.get("tag")
        if out and tag:
            st_ = _LAST.get("status") or {}
            st_["state"] = "УПАЛ"
            st_["error"] = f"{type(e).__name__}: {e}"
            st_["traceback"] = traceback.format_exc()[-2000:]
            write_status(out, tag, st_)
            print(f"ПРОГОН УПАЛ: {type(e).__name__}: {e}")
            if not _LAST.get("no_publish"):
                R1.publish(f"fcbd3542: прогон упал ({tag})")
        raise


def _run():
    R1.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=R1.BOOK_ROOT)
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--perms", type=int, default=NULL_PERMS)
    ap.add_argument("--tick-change-file", default="")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--no-link", action="store_true")
    ap.add_argument("--mem-share", type=float, default=0.6)
    ap.add_argument("--duck-share", type=float, default=TS.MEMORY_SHARE,
                    help="доля памяти под DuckDB на время сборки метки")
    a = ap.parse_args()
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"

    # Каталог создаётся ДО счёта: прогон турнира однажды досчитал всё и
    # упал на записи в несуществующий каталог, а зонд режимов повторил
    # это слово в слово.
    os.makedirs(a.out, exist_ok=True)
    _LAST.update({"out": a.out, "tag": a.tag, "no_publish": a.no_publish})

    syms, hours = R1.available(a.root)
    if a.symbols:
        want = set(a.symbols.split(","))
        syms = [s for s in syms if s in want]
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    print(f"символов {len(syms)}, суток {len(days)}: {days[0]} … {days[-1]}")

    need = R1.mem_need_mb(len(syms), R1.DAY_SEC + 2 * R1.PAD_SEC)
    have = R1.mem_available_mb()
    print(f"память: нужно ~{need:.0f} МБ на сутки, доступно "
          f"{'неизвестно' if have is None else f'{have:.0f} МБ'}")
    if have is not None and need > have * a.mem_share:
        fits = int(len(syms) * have * a.mem_share / max(need, 1e-9))
        raise SystemExit(
            f"ОТКАЗ: на сутки нужно ~{need:.0f} МБ, а свободно "
            f"{have:.0f} МБ (порог {a.mem_share:.0%}). Рядом идёт запись "
            f"стакана, и ронять её нельзя. Влезет около {fits} символов.")

    months = sorted({d[:7] for d in days})
    print(f"метка tick/σ: месяцев {len(months)} — {', '.join(months)}")
    con = TS.connect(a.duck_share)
    labels = build_labels(months, syms, con)
    con.close()          # буферы DuckDB держать незачем: рядом сборщик
    for m in months:
        print(f"  {m}: размечено {labels[m]['labelled']}, без метки "
              f"{labels[m]['unlabelled']}, медиана {labels[m]['median']}")

    hedge_row = syms.index(HEDGE_SYMBOL) if HEDGE_SYMBOL in syms else None
    if hedge_row is None:
        print(f"  {HEDGE_SYMBOL} в записи нет: хедж-диагностика не "
              f"считается")

    cells = [(d, dl, h) for d in D.DROPS for dl in D.DELAYS
             for h in D.HORIZONS_SEC]
    acc = {k: [] for k in cells}
    last_seen, cadences = {}, []
    t_start = time.time()
    status = {"state": "идёт", "tag": a.tag, "symbols": len(syms),
              "days_planned": len(days), "day_from": days[0],
              "day_to": days[-1], "mem_need_mb": need, "days_done": [],
              "started_at": datetime.now(timezone.utc).strftime(
                  "%Y-%m-%d %H:%M UTC")}
    _LAST["status"] = status
    write_status(a.out, a.tag, status)

    for day in days:
        t_day = time.time()
        print(f"  {day}: читаю")
        P, t0, n = R1.load_day(a.root, syms, day, a.jobs)
        step = R1.cadence(P, R1.PAD_SEC, R1.PAD_SEC + R1.DAY_SEC)
        cadences.append(step)
        print(f"    шаг записи: снимок раз в {step:.1f} с")
        NXT = R1.next_index(P)
        for drop in D.DROPS:
            rows, cols = R1.events_of_day(
                P, t0, drop, last_seen.setdefault(drop, {}), R1.PAD_SEC,
                R1.PAD_SEC + R1.DAY_SEC)
            print(f"    падение {int(drop * 100)} %: событий {len(rows)}")
            if len(rows) == 0:
                continue
            sub = [k for k in cells if k[0] == drop]
            got = measure_halves(P, NXT, rows, cols, t0, sub, hedge_row)
            for k in sub:
                acc[k] += got[k]
        del P, NXT
        took = round((time.time() - t_day) / 60, 1)
        print(f"  {day}: готово за {took} мин, память {R1.rss_mb()} МБ")
        status["days_done"].append(
            {"day": day, "took_min": took, "rss_mb": R1.rss_mb(),
             "cadence_sec": round(step, 2),
             "events": {str(k[0]): len(acc[k]) for k in cells
                        if k[1] == D.DELAYS[0]
                        and k[2] == D.HORIZONS_SEC[0]}})
        write_status(a.out, a.tag, status)

    key = (D.VERDICT_CELL["drop"], D.VERDICT_CELL["delay_sec"],
           D.VERDICT_CELL["horizon_sec"])
    rec = acc[key]
    require_events(rec, len(days), len(syms))

    ring, src = R1.cost_round(os.path.join(RESEARCH, "d1_seconds", "out"),
                              "1m")
    print(f"круг издержек {ring:.1f} б.п. — {src}")
    verdict = half_stats(rec, syms, labels)
    null = permutation_null(rec, syms, labels, a.perms)
    turn = turnover_control(rec, syms, labels)

    thin_set = {(m, s) for m in labels
                for s, h in labels[m]["half"].items() if h == "thin"}
    coarse_set = {(m, s) for m in labels
                  for s, h in labels[m]["half"].items() if h == "coarse"}
    book = {}
    import ceiling as CE
    import trades as TR
    for name, rows_set, hedged in (("naked", thin_set, False),
                                   ("hedged", thin_set, True),
                                   ("coarse", coarse_set, False)):
        if hedged and hedge_row is None:
            continue
        tr = book_trades(rec, syms, rows_set, key[1], key[2], ring,
                         hedged=hedged,
                         hedge_ring_bp=R1.COMMISSION_BP)
        if not tr:
            continue
        pct, s = book_days(tr)
        if s:
            s = dict(s, trades=len(tr))
            book[name] = s
        if name == "naked":
            book["cap_share"] = TR.NAME_CAP_SHARE
            book["active_share"] = active_share(pct, len(days))
            book["active_need"] = CE.MIN_ACTIVE_SHARE
            import pool as PL
            book["shape_why"] = PL.shape_why(pct, 0.0)
            book["daily_pct"] = {str(k): round(v, 4) for k, v in pct.items()}

    tc_syms, tc_why = tick_change_symbols(set(syms), a.tick_change_file)
    link, link_why = (None, "выключено ключом --no-link") if a.no_link \
        else link_to_pool(book.get("daily_pct") or {})

    spans = [labels[m]["span"] for m in labels if labels[m]["span"]]
    art = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tag": a.tag, "days": len(days), "day_from": days[0],
        "day_to": days[-1], "symbols": len(syms),
        "cadence_sec": round(float(np.median(cadences)), 2)
        if cadences else None,
        "drops": list(D.DROPS), "delays": list(D.DELAYS),
        "horizons": list(D.HORIZONS_SEC),
        "verdict_cell": dict(D.VERDICT_CELL),
        "cost_round_bp": round(ring, 2), "cost_source": src,
        "labels": {m: {k: v for k, v in labels[m].items()
                       if k not in ("values", "half", "turnover")}
                   for m in labels},
        "label_why": {w: sum(labels[m]["why"].get(w, 0) for m in labels)
                      for w in {w for m in labels for w in labels[m]["why"]}},
        "span_overall": round(max(spans), 1) if spans else None,
        "verdict": verdict, "null": null, "turnover": turn, "book": book,
        "calibration": {"planted": calibrate(True),
                        "random": calibrate(False)},
        "tick_change": {
            "symbols": tc_syms, "why": tc_why,
            "experiment": tick_change_experiment(rec, syms, tc_syms)},
        "link": link, "link_why": link_why,
        "cells": {f"{k[0]}|{k[1]}|{k[2]}": half_stats(v, syms, labels)
                  for k, v in acc.items() if v},
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    art["killers"] = killers(art)
    status["state"] = "готов"
    write_status(a.out, a.tag, status)
    p = os.path.join(a.out, f"HALVES-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"HALVES-report-{a.tag}.md"))
    print(f"готово: {p}")
    if not a.no_publish:
        R1.publish(f"fcbd3542: отскок по половинам tick/σ ({a.tag})")


if __name__ == "__main__":
    main()
