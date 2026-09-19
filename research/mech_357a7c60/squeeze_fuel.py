#!/usr/bin/env python3
"""
Механика 357a7c60 — топливо сквиза по ходу позиции.

Что утверждается
----------------

Для коротких книг `h24` (`safe_h`, `optimal_h`, `aggr_h`; правила как
сейчас: одиночный вход на 24 ч, цель ×2, пол 0.10 / 0.50 / 0.50, возраст
≥ 7 суток, охрана рынком 2 %, деньги нетто) всплеск ПРИНУДИТЕЛЬНОГО
ВЫКУПА ШОРТОВ в СОБСТВЕННОМ имени позиции есть сквиз в ходу, делающий
хвост. Час k помечен, когда

    V_k / (B_k + S_k) ≥ s   и   V_k ≥ MIN_USD

где V_k — доллары принтов ликвидаций той стороны, которую ДАННЫЕ
определили как «выбит шорт», а B_k + S_k — оборот часа по ленте.
Позиция закрывается на конце первого помеченного часа по отметке ядра;
равенство отметки усечению симуляции доказано охраной рынком на 6 100
точках (`dca_paper/out/DCA-wave-guard.md`), поэтому второго реплея
здесь нет — и это же потолок: внутри часа путь не виден.

Ось порога объявлена ДО прогона: `AXIS_S` = 0.5 / 1 / 2 %. Судит
СЕРЕДИНА (`middle`), края печатаются рядом и не судят: право на
итерацию одно.

Контргипотеза объявлена рядом и убивает механизм даже при удачных
деньгах: всплеск может быть КУЛЬМИНАЦИЕЙ, а не началом (урок L-серии —
отскок после каскада принадлежит рынку). Тогда выход в этот час продаёт
дно. Решает диагностика `before_worst`: доля хвостовых позиций, у
которых первый всплеск стоит РАНЬШЕ часа худшей отметки хотя бы на час.
Меньше `DIAG_MIN` — механизм мёртв, что бы ни показали деньги.

Сторона решается ДАННЫМИ, а не именем колонки
---------------------------------------------

Сводка часа (`s8_loop/summary.py`) кладёт доллары принтов с меткой `Buy`
в колонку `liq_short`, с меткой `Sell` — в `liq_long`. Это КОДИРОВКА
(`MARK_COLUMN`): какая метка в какую колонку попала. Кого именно выбило
— лонга или шорта, — кодировка не знает, а имя колонки утверждает, и
утверждает, судя по нынешней записи, наоборот. Поэтому сторона здесь не
берётся из имени: `calibrate` считает доллары КАЖДОЙ метки в часах
роста и падения и отдаёт решение ядру `mech_d71203f0.unprovoked.long_mark`
— тому же, которым сторона решалась у неспровоцированного принта.
Второй копии этого решения не заводится.

Шортов выбивают РОСТОМ цены: метка, доллары которой лежат в часах
падения, маркирует ликвидацию ЛОНГА, вторая — наш выкуп шортов. Доля
внутри полосы `SIDE_BAND` вокруг половины — ОТКАЗ: перевёрнутый знак
неотличим от «эффекта нет», а знак, угаданный молча, переживает отчёт.

Этот модуль верен при любом имени колонки: переставь колонки местами —
калибровка назовёт другую метку и придёт к тому же ФИЗИЧЕСКОМУ потоку.
Именно это и проверяется тестом; переименование колонок в `summary.py`
— отдельное решение роли `fix` (оно меняет имена признаков модели и
подпись обучения), и эта механика его не ждёт.

Чего здесь НЕ живёт
-------------------

Второй копии расчётного ядра нет. Путь позиции и закрытие на отметке
часа — `dca_paper/wave.py` (`path_of`, `guard_record`); сводки — его же
`Hours`; деньги, дельты и контроль случайными выходами —
`dca_paper/path_screen.py` (`deltas`, `control_exits`, `exit_at`,
`open_index`) и `agree_book.stats_of`; концентрация и разбор по дням —
`dca_paper/wave_guard.py` (`wo3`, `day_diff`, `tails_of`, `middle`);
форма по дням — `factory/stability.py`; сторона — `unprovoked.long_mark`.
Здесь живут ровно: метка часа по потоку, калибровка стороны на сводках,
диагностика «всплеск раньше худшей отметки», перемешанный поток и
вердикт, выведенный из чисел.

Файлов этот модуль не открывает: сводки приходят объектом `Hours`,
журнал — готовым кэшем. Всё I/O — в `run_squeeze.py`.
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (os.path.join(RESEARCH, "dca_paper"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "mech_d71203f0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import path_screen as P                                      # noqa: E402
import tail_screen as T                                      # noqa: E402
import wave as WV                                            # noqa: E402
import wave_guard as WG                                      # noqa: E402
import stability as SB                                       # noqa: E402
import unprovoked as U                                       # noqa: E402

# Чужой модуль под знакомым именем в этом проекте уже импортировался: на
# пути лежат семь каталогов, и `stability`, `rules`, `costs` есть больше
# чем в одном. Проверка — та же, что у d71203f0, и тем же кодом.
U.check_origin(P, "dca_paper")
U.check_origin(T, "dca_paper")
U.check_origin(WV, "dca_paper")
U.check_origin(WG, "dca_paper")
U.check_origin(SB, "factory")
U.check_origin(U, "mech_d71203f0")

HOUR = WV.HOUR
# --- объявлено заданием ДО прогона, после результата не меняется -------
AXIS_S = (0.005, 0.010, 0.020)    # доля выкупа шортов в обороте часа
MIN_USD = 1000.0                  # долларов выкупа в часе — иначе не событие
MIN_MARKED = 30                   # помеченных позиций на книгу; меньше — ось судить нечем
SIDE_BAND = 0.10                  # полоса неразличимости: доля 0.4–0.6 — отказ
COVER_BLOCK = 0.50                # покрытие журнала сводками: ниже — блок
COVER_WARN = 0.90                 # ниже — вердикт с оговоркой
DIAG_MIN = 0.50                   # убийца (г): всплеск раньше худшей отметки
BEAT_MAX = 0.10                   # убийца (а): зёрен, где случайные не хуже
CTL_SEEDS = P.SEEDS               # зёрен контроля — объявлено дорогой сделки
BOOKS_NEED = 2                    # книг из трёх, прошедших контроль
TAIL_CUT = 0.25                   # убийца (б): хвостовых выходов стало меньше на
PERM_SEEDS = 200                  # зёрен перемешанного потока
LOSS_STOP = 0.25                  # уже измеренный ценовой стоп — колонка сравнения

# --- служебные допуски: свойства записи, а не гипотезы ------------------
# Пол калибровки отделяет «НЕ ИЗМЕРЕНО» от «поровну» и ничем больше не
# служит: на нынешней записи в часах падения лежит 3.7e8 $ — четыреста
# полов, так что нести решение он не может по построению. Назначен здесь
# же, где проверяется, и потому назван вслух.
MIN_CALIB_USD = 1e6
MARK_COLUMN = {"Buy": "liq_short", "Sell": "liq_long"}   # кодировка summary.py
LIQ_FIELDS = ("liq_short", "liq_long")
EXIT_LABEL = "поток"
PERM_SEED0 = 3570000              # зерно ЧИСЛОМ: hash строки солится


def middle(axis=AXIS_S):
    """Судимая ячейка — СЕРЕДИНА объявленной оси, а не лучшая."""
    return WG.middle(list(axis))


# ======================================================================
# 1. Сторона: решают данные, а не имя колонки
# ======================================================================

def hour_measured(row):
    """Час измерим? Сводка есть, поля ликвидаций и оборота заполнены.

    Ликвидации сводка считает ТОЛЬКО при живом опросе метрик того же
    часа (`summary.py`, комментарий у строки 200): час без опроса идёт
    без этих полей вовсе. Это ПРОЧЕРК, а не ноль потока — иначе
    выключенный сборщик выглядел бы как тихий рынок, и правило молчало
    бы там, где оно просто слепо.
    """
    if not row:
        return False
    for f in LIQ_FIELDS:
        if row.get(f) is None:
            return False
    return row.get("buy") is not None and row.get("sell") is not None


def flow_of(row, field):
    """(доллары потока, оборот часа) либо (None, None) — НЕ ИЗМЕРЕНО."""
    if not hour_measured(row):
        return None, None
    return float(row.get(field)), float(row["buy"]) + float(row["sell"])


def fold_calib(rows, acc=None):
    """Доллары каждой метки в часах роста и падения — по ОДНОМУ имени.

    Ход часа — закрытие середины к закрытию ПРЕДЫДУЩЕГО часа, и сосед
    берётся во ВРЕМЕНИ, а не по номеру строки: в записи есть дыры, и
    «предыдущая строка» через пропуск мерила бы ход за сутки как ход за
    час. Часы с дырой считаются отдельным числом, а не молча.
    """
    acc = acc if acc is not None else new_calib()
    prev_h, prev_px = None, None
    for r in sorted(rows or [], key=lambda x: str(x.get("hour") or "")):
        acc["rows"] += 1
        hr = str(r.get("hour") or "")
        px = r.get("mid_close")
        px = float(px) if px else None
        idx = hour_no(hr)
        if not hour_measured(r):
            acc["unmeasured"] += 1
        elif prev_px and px and idx is not None and prev_h is not None:
            if idx - prev_h != 1:
                acc["gap"] += 1
            else:
                mv = px / prev_px - 1.0
                where = "up" if mv > 0 else ("down" if mv < 0 else "flat")
                acc["hours"][where] += 1
                if where != "flat":
                    for mark, col in MARK_COLUMN.items():
                        acc["usd"][mark][where] += float(r.get(col) or 0.0)
                        acc["day"].setdefault(hr[:10], _zero_marks())
                        acc["day"][hr[:10]][mark][where] += float(r.get(col) or 0.0)
        if px:
            prev_h, prev_px = idx, px
    return acc


def hour_no(hour):
    """Номер календарного часа из метки сводки «ГГГГ-ММ-ДД-ЧЧ»."""
    try:
        import calendar
        import time as _t
        return int(calendar.timegm(_t.strptime(str(hour), "%Y-%m-%d-%H"))
                   // int(HOUR))
    except (ValueError, TypeError):
        return None


def _zero_marks():
    return {m: {"up": 0.0, "down": 0.0} for m in MARK_COLUMN}


def new_calib():
    return {"usd": _zero_marks(), "day": {}, "rows": 0, "names": 0,
            "unmeasured": 0, "gap": 0,
            "hours": {"up": 0, "down": 0, "flat": 0}}


def decide_side(usd, band=SIDE_BAND, min_usd=MIN_CALIB_USD):
    """Какая метка означает «выбит ШОРТ». Решают ДАННЫЕ.

    Два согласных решения об одном и том же, и оба обязаны сойтись:

    1. ЯДРО (`unprovoked.long_mark`, то же, что у d71203f0): какая метка
       ДОМИНИРУЕТ в часах падения — та и маркирует ликвидацию лонга,
       вторая есть выкуп шортов.
    2. ОБЪЯВЛЕННАЯ ПОЛОСА заявки: доля долларов КАЖДОЙ метки, лежащая в
       часах падения (сегодня Buy 0.805, Sell 0.143). Внутри
       `band` вокруг половины — сторона НЕ ИЗМЕРЕНА.

    Разошлись — отказ. Обе метки в часах одного знака — отказ. Отказ
    здесь дешевле ошибки: перевёрнутый знак выглядит ровно как
    «эффекта нет» и живёт в выводах месяцами.
    """
    down = {m: float(usd.get(m, {}).get("down", 0.0)) for m in MARK_COLUMN}
    up = {m: float(usd.get(m, {}).get("up", 0.0)) for m in MARK_COLUMN}
    out = {"ok": False, "mark_long": None, "mark_short": None,
           "field_short": None, "share_down": {}, "usd_down": down,
           "usd_up": up, "kernel_why": None, "why": None}
    mark_long, kw = U.long_mark(down["Sell"], down["Buy"], margin=float(band),
                                min_prints=float(min_usd))
    out["kernel_why"] = kw
    if mark_long is None:
        # Слова ядра остаются в `kernel_why` и в отчёт не идут: оно
        # считает ПРИНТЫ и так их и называет, а здесь в него поданы
        # ДОЛЛАРЫ. Подпись, лгущая о единицах, в этом проекте уже стоила
        # пяти ошибок — причина пересказывается своими словами.
        tot = down["Sell"] + down["Buy"]
        out["why"] = (
            (f"долларов ликвидаций в часах падения {tot:,.0f} при минимуме "
             f"{float(min_usd):,.0f} — сторона НЕ ИЗМЕРЕНА")
            if tot < float(min_usd) else
            (f"в часах падения Buy {down['Buy']:,.0f} $ против Sell "
             f"{down['Sell']:,.0f} $ — доля внутри полосы неразличимости "
             f"±{float(band):.2f}: сторону выбрать НЕЧЕМ, знак был бы угадан"))
        return out
    share = {}
    for m in MARK_COLUMN:
        tot = down[m] + up[m]
        if tot <= 0.0 or tot < float(min_usd):
            out["why"] = (f"метка {m}: долларов ликвидаций {tot:,.0f} при "
                          f"минимуме {float(min_usd):,.0f} — доля в часах "
                          "падения НЕ ИЗМЕРЕНА")
            return out
        share[m] = down[m] / tot
    out["share_down"] = share
    inside = [m for m in sorted(share) if abs(share[m] - 0.5) <= float(band)]
    if inside:
        out["why"] = ("доля долларов метки "
                      + ", ".join(f"{m} {share[m]:.3f}" for m in inside)
                      + f" в часах падения внутри полосы "
                      f"{0.5 - float(band):.1f}–{0.5 + float(band):.1f} — "
                      "сторону выбрать НЕЧЕМ, знак был бы угадан")
        return out
    if (share["Buy"] > 0.5) == (share["Sell"] > 0.5):
        out["why"] = (f"обе метки лежат в часах одного знака (Buy "
                      f"{share['Buy']:.3f}, Sell {share['Sell']:.3f}) — "
                      "разделить стороны нечем")
        return out
    dominant = "Buy" if share["Buy"] > share["Sell"] else "Sell"
    if dominant != mark_long:
        out["why"] = (f"ядро назвало лонгом метку {mark_long}, а доля в "
                      f"часах падения — {dominant}: решения разошлись, "
                      "сторона НЕ ИЗМЕРЕНА")
        return out
    mark_short = U.other_side(mark_long)
    out.update({"ok": True, "mark_long": mark_long, "mark_short": mark_short,
                "field_short": MARK_COLUMN[mark_short],
                "why": (f"доля долларов {mark_long} в часах падения "
                        f"{share[mark_long]:.3f}, {mark_short} — "
                        f"{share[mark_short]:.3f}: падениями выбивает "
                        f"{mark_long} (это ЛОНГИ), значит выкуп ШОРТОВ "
                        f"маркирован {mark_short} и лежит в колонке "
                        f"`{MARK_COLUMN[mark_short]}`")})
    return out


def calib_halves(acc, band=SIDE_BAND, min_usd=MIN_CALIB_USD):
    """Та же сторона на половинах записи: кодировка обязана НЕ МЕНЯТЬСЯ.

    Калибровка идёт по всей записи, то есть смотрит и в будущее любой
    отдельной сделки. Это допустимо ровно потому, что она меряет
    КОДИРОВКУ площадки, а не предсказывает цену, — но допустимость эта
    проверяется числом: сторона, разная на половинах, была бы уже не
    кодировкой, а подгонкой. Половины делятся по суткам записи.
    """
    days = sorted(acc.get("day") or {})
    if len(days) < 2:
        return {"why": f"суток записи {len(days)} — половин нет", "halves": []}
    cut = len(days) // 2
    out = []
    for name, part in (("первая половина", days[:cut]),
                       ("вторая половина", days[cut:])):
        usd = _zero_marks()
        for d in part:
            for m in MARK_COLUMN:
                for w in ("up", "down"):
                    usd[m][w] += acc["day"][d][m][w]
        d = decide_side(usd, band=band, min_usd=min_usd)
        out.append({"part": name, "days": [part[0], part[-1]] if part else [],
                    "mark_short": d["mark_short"], "ok": d["ok"],
                    "share_down": d["share_down"], "why": d["why"]})
    same = (len(out) == 2 and out[0]["ok"] and out[1]["ok"]
            and out[0]["mark_short"] == out[1]["mark_short"])
    return {"halves": out, "same": same,
            "why": (None if same else "сторона на половинах записи РАЗНАЯ "
                    "либо не измерена — это уже не кодировка площадки")}


def calibrate(name_rows, band=SIDE_BAND, min_usd=MIN_CALIB_USD):
    """Сторона по всей записи сводок. `name_rows` — пары (имя, строки)."""
    acc = new_calib()
    for _sym, rows in name_rows:
        acc["names"] += 1
        fold_calib(rows, acc)
    if not acc["rows"]:
        return dict(acc, ok=False, why="сводок не прочитано ни одной строки — "
                    "мерить сторону не на чем", halves={})
    d = decide_side(acc["usd"], band=band, min_usd=min_usd)
    out = dict(acc)
    out.pop("day", None)
    out.update(d)
    out["halves"] = calib_halves(acc, band=band, min_usd=min_usd)
    if out["ok"] and not out["halves"].get("same"):
        out["ok"] = False
        out["why"] = (str(out["halves"].get("why")) + "; " + str(out["why"]))
    return out


# ======================================================================
# 2. Метка часа: поток в СОБСТВЕННОМ имени позиции
# ======================================================================

def views_of(cache, rulers=None):
    """Лёгкий взгляд на записи: путь ядра, хвост, сама запись.

    Полей ровно три, и имена у них те же, что у `path_screen.view_of`,
    потому что их читают его же `deltas`, `open_index` и `control_exits`.
    Рынок, β и ход имени по часам эта механика не спрашивает: она читает
    поток, а не цену, и 72 часовых окна на запись стоили бы минут ни за
    что.
    """
    rulers = tuple(rulers if rulers is not None else T.RULERS)
    out = {}
    for key, r in cache.items():
        if key[0] not in rulers or (r.get("state") or "closed") != "closed":
            continue
        out[key] = {"rec": r, "path": WV.path_of(r), "tail": T.is_tail(r)}
    return out


def live_hours(view):
    """Часы, в которые правило вправе смотреть: СТРОГО до выхода.

    k = K — час, в котором позицию закрыло ядро. Заглянуть туда значило
    бы решать выход по тому, чем сделка кончилась, и находка была бы
    неотличима от находки. Это же правило держит контроль случайных
    выходов честным: он выбирает среди ОТКРЫТЫХ в тот час.
    """
    p = view.get("path")
    if not p:
        return []
    return list(range(1, int(p["K"])))


def hour_key(at, k):
    """Календарный час k-го часа жизни позиции.

    `at` — конец часа решения, поэтому последняя секунда часа k есть
    `at − 1 + k·3600`; тот же адрес, по которому `wave.Market.px` берёт
    закрытие часа, — иначе поток и цена читались бы из разных часов.
    """
    return int((float(at) - 1.0 + int(k) * HOUR) // HOUR)


def flow_cells(views, hours, field):
    """{(имя, номер часа): (доллары потока, оборот)} по часам жизни.

    Таблица строится по ИМЕНАМ, а не по записям: две линейки держат одно
    имя в один час, и поток у них один и тот же. Он же потом
    перемешивается между именами — по этой таблице.
    """
    cells = {}
    # Порядок обхода — по имени и времени: `Hours` держит в памяти файлы
    # последних суток, и вразнобой одни и те же сутки читались бы
    # десятками раз. На ответ порядок не влияет, на минуты — да.
    for _key, v in sorted(views.items(),
                          key=lambda kv: (kv[1]["rec"]["sym"],
                                          float(kv[1]["rec"]["at"]))):
        rec = v["rec"]
        sym, at = rec["sym"], float(rec["at"])
        for k in live_hours(v):
            ck = (sym, hour_key(at, k))
            if ck not in cells:
                cells[ck] = flow_of(hours.row(sym, at - 1.0 + k * HOUR), field)
    return cells


def is_marked(val, turn, s, min_usd=MIN_USD):
    """Час помечен? Доля выкупа шортов в обороте часа ≥ `s` ПРИ потоке
    не меньше `min_usd`.

    Правило живёт ОДНОЙ строкой на весь модуль: и час выхода, и доля
    помеченных часов, и перемешанный поток спрашивают его здесь. Вторая
    копия формулы однажды расходится с первой — так в этом проекте
    разъезжались список книг (восемь мест) и проверка версии правил
    журнала (шесть). Пол в долларах не украшение: доля у тонкого часа
    скачет от одной случайной заявки, и без пола правило метило бы
    тишину, а не сквиз. Прочерк (`None`) меткой не бывает.
    """
    if val is None or turn is None or float(turn) <= 0.0:
        return False
    return (float(val) >= float(min_usd)
            and float(val) / float(turn) >= float(s))


def marked_hour(view, cells, s, min_usd=MIN_USD):
    """Первый помеченный час позиции либо None; рядом — что измерено."""
    rec = view["rec"]
    sym, at = rec["sym"], float(rec["at"])
    st = {"measured": 0, "missing": 0}
    for k in live_hours(view):
        v, turn = cells.get((sym, hour_key(at, k)), (None, None))
        if v is None or turn is None:
            st["missing"] += 1
            continue
        st["measured"] += 1
        if is_marked(v, turn, s, min_usd=min_usd):
            return k, st
    return None, st


def mark_all(views, cells, s, min_usd=MIN_USD):
    """{ключ сделки: час выхода} по всем записям — и счёт измеримости."""
    changed, st = {}, {"measured": 0, "missing": 0, "scanned": 0}
    for key, v in views.items():
        k, d = marked_hour(v, cells, s, min_usd=min_usd)
        st["measured"] += d["measured"]
        st["missing"] += d["missing"]
        st["scanned"] += 1
        if k is not None:
            changed[key] = k
    return changed, st


def apply_flow(cache, changed, why=EXIT_LABEL):
    """Кэш с выходами по потоку: та же запись, закрытая отметкой часа k.

    `path_screen.apply_axis` сюда не зовётся потому, что он сам решает
    час — своими пятью осями через свой модульный `trigger`. Шестая ось
    читает сводки, поэтому час приходит готовым; закрытие же записи
    остаётся его: `exit_at` → `wave.guard_record`, то же, чем закрывает
    охрана рынком.
    """
    mod = dict(cache)
    for key, k in changed.items():
        mod[key] = P.exit_at(cache[key], k, why=why)
    return mod


def refuse_if_empty(n_names, side, root=""):
    """Ноль строк при непустом каталоге сводок — ОТКАЗ, а не вердикт.

    «Сторона не измерена» и «чтение сломано» лечатся разным: первое —
    ответ о площадке, второе — ответ о нас. Пустота, выданная за
    результат, в этом проекте уже печаталась дважды.
    """
    if n_names and not (side or {}).get("rows"):
        raise SystemExit(
            f"ОТКАЗ: каталог сводок {root} содержит {int(n_names)} имён, а "
            "прочитано ноль строк — это сломанное чтение, а не «сторона не "
            "измерена». Проверять надо запись и путь, а не гипотезу.")


def coverage(views, cells):
    """Покрытие журнала сводками: у скольких позиций измерим КАЖДЫЙ час.

    Позиции, закрытые в первый же час, часов жизни не имеют вовсе —
    правилу там нечего смотреть. Они считаются своим числом и в
    знаменатель не идут: вписав их в покрытие, мы подняли бы его тем,
    что правилу недоступно.
    """
    full = part = none = no_hours = 0
    hours_all = hours_ok = 0
    uncovered = []
    for key, v in views.items():
        ks = live_hours(v)
        if not ks:
            no_hours += 1
            continue
        rec = v["rec"]
        sym, at = rec["sym"], float(rec["at"])
        ok = sum(1 for k in ks
                 if cells.get((sym, hour_key(at, k)), (None, None))[0]
                 is not None)
        hours_all += len(ks)
        hours_ok += ok
        if ok == len(ks):
            full += 1
        elif ok:
            part += 1
            uncovered.append({"key": [key[0], key[1], key[2]],
                              "hours": len(ks), "measured": ok})
        else:
            none += 1
            uncovered.append({"key": [key[0], key[1], key[2]],
                              "hours": len(ks), "measured": 0})
    n = full + part + none
    return {"n": n, "full": full, "part": part, "none": none,
            "no_hours": no_hours,
            "share": (full / n if n else None),
            "hours": hours_all, "hours_measured": hours_ok,
            "hours_share": (hours_ok / hours_all if hours_all else None),
            "uncovered": sorted(uncovered,
                                key=lambda d: d["measured"] / max(1, d["hours"]))[:20],
            "n_uncovered": len(uncovered)}


def marked_share(views, cells, s, min_usd=MIN_USD):
    """Доля часов жизни, помеченных правилом, — среди ИЗМЕРИМЫХ часов.

    Прочерк в знаменатель не идёт: «правило не сработало ни разу» и
    «правило не считалось» обязаны различаться, а деление на все часы
    смешало бы их в одно маленькое число.
    """
    hit = meas = 0
    for _key, v in views.items():
        rec = v["rec"]
        sym, at = rec["sym"], float(rec["at"])
        for k in live_hours(v):
            val, turn = cells.get((sym, hour_key(at, k)), (None, None))
            if val is None or turn is None:
                continue
            meas += 1
            if is_marked(val, turn, s, min_usd=min_usd):
                hit += 1
    return {"hours_measured": meas, "hours_marked": hit,
            "share": (hit / meas if meas else None)}


def by_book(views, changed, books):
    """Помеченные позиции по КНИГАМ: линейка кормит книгу, не наоборот."""
    import run_short as S                                     # noqa: E402
    U.check_origin(S, "dca_paper")
    out = {}
    for bk in books:
        rk = S.BOOKS.get(bk)
        keys = [key for key in changed if key[0] == rk]
        out[bk] = {"ruler": rk, "n": len(keys),
                   "tails": sum(1 for key in keys if views[key]["tail"]),
                   "positions": sum(1 for key in views if key[0] == rk)}
    return out


# ======================================================================
# 3. Диагностика механизма: начало или кульминация
# ======================================================================

def worst_hour(path):
    """Час худшей отметки пути; при повторе минимума — ПЕРВЫЙ из них."""
    if not path:
        return None
    best_k, best_v = None, None
    for k in sorted(path["cum"]):
        c = path["cum"][k]
        if c is None:
            continue
        if best_v is None or float(c) < best_v - 1e-15:
            best_v, best_k = float(c), int(k)
    return best_k


def before_worst(views, changed, tail_only=True):
    """Всплеск РАНЬШЕ худшей отметки хотя бы на час — доля от хвоста.

    Убийца (г) заявки. Меньше `DIAG_MIN` — всплеск есть кульминация, а
    не начало: правило продаёт дно, и заявка мертва, даже если деньги
    прошли. Ни одной хвостовой позиции с всплеском — доля НЕ ИЗМЕРЕНА
    (прочерк), а не ноль.
    """
    n = early = 0
    same = late = 0
    for key, k in changed.items():
        v = views.get(key) or {}
        if tail_only and not v.get("tail"):
            continue
        w = worst_hour(v.get("path"))
        if w is None:
            continue
        n += 1
        if int(k) <= int(w) - 1:
            early += 1
        elif int(k) == int(w):
            same += 1
        else:
            late += 1
    return {"n": n, "early": early, "same": same, "late": late,
            "share": (early / n if n else None)}


def shuffle_cells(cells, rnd):
    """Тот же поток, розданный ДРУГИМ именам ТОГО ЖЕ часа.

    Инвариант перемешивания: внутри каждого календарного часа набор пар
    (доллары, оборот) остаётся прежним — меняется только то, в чьём
    имени они горели. Перемешай заодно и часы, и контроль отвечал бы на
    другой вопрос: «бывает ли такой поток вообще», а не «в этом ли он
    имени».
    """
    by_hour = {}
    for (sym, hk), cell in cells.items():
        by_hour.setdefault(hk, []).append((sym, cell))
    out = {}
    for hk, items in by_hour.items():
        vals = [c for _s, c in items]
        rnd.shuffle(vals)
        for (sym, _c), c in zip(items, vals):
            out[(sym, hk)] = c
    return out


def permuted_marks(views, cells, s, seeds=PERM_SEEDS, min_usd=MIN_USD,
                   seed0=PERM_SEED0, log=None):
    """Поток, ПЕРЕМЕШАННЫЙ между именами тех же часов — диагностика.

    Меняется только то, в ЧЬЁМ имени горел поток: час остаётся тем же,
    набор пар (доллары, оборот) внутри часа — тем же. Если перемешанный
    поток метит столько же хвостовых позиций, сколько настоящий, сигнал
    есть «буря на рынке ликвидаций вообще», а не сквиз ЭТОГО имени, и
    правило сводится к стопу по волатильности. Это диагностика, а не
    убийца, и печатается словами.
    """
    out = []
    for i in range(int(seeds)):
        shuffled = shuffle_cells(cells, random.Random(int(seed0) + i))
        changed, _st = mark_all(views, shuffled, s, min_usd=min_usd)
        out.append({"n": len(changed),
                    "tails": sum(1 for key in changed
                                 if views[key]["tail"])})
        if log and i and i % 50 == 0:
            log(f"    перемешанный поток: {i} зёрен из {seeds}")
    return out


def perm_stats(real, draws):
    """Настоящий поток против перемешанного: доля зёрен не хуже."""
    tails = [int(d["tails"]) for d in (draws or [])]
    ns = [int(d["n"]) for d in (draws or [])]
    if not tails:
        return {"seeds": 0, "beat_tails": None, "beat_n": None}
    return {"seeds": len(tails),
            "med_tails": float(np.median(tails)),
            "med_n": float(np.median(ns)),
            "beat_tails": round(sum(1 for x in tails
                                    if x >= int(real["tails"])) / len(tails), 3),
            "beat_n": round(sum(1 for x in ns
                                if x >= int(real["n"])) / len(ns), 3)}


def guard_cross(views, changed, mkt, pct, kmax):
    """Пересечение с охраной рынком: кого закрывают ОБА правила.

    Охрана читает волну двадцати прокси-имён, это правило — поток в
    собственном имени; скрин хвоста говорит, что у хвоста рынок молчит,
    значит множества по построению разные. «По построению» — не число,
    поэтому вот число.
    """
    both = only_flow = flow_first = guard_first = same_hour = 0
    for key, k in changed.items():
        v = views.get(key) or {}
        p = v.get("path")
        if not p:
            continue
        last = min(int(kmax), int(p["K"]) - 1)
        if last < 1:
            continue
        g, _miss = mkt.k_star(float(v["rec"]["at"]), float(pct), last)
        if g is None:
            only_flow += 1
            continue
        both += 1
        if int(k) < int(g):
            flow_first += 1
        elif int(k) > int(g):
            guard_first += 1
        else:
            same_hour += 1
    return {"marked": len(changed), "both": both, "only_flow": only_flow,
            "flow_first": flow_first, "guard_first": guard_first,
            "same_hour": same_hour, "pct": float(pct)}


def shape_of(stats_cell):
    """Форма по дням — мерой проекта (`stability.stats`), не своей."""
    days = (stats_cell or {}).get("days") or []
    daily = {str(d.get("d")): float(d.get("usd") or 0.0) for d in days
             if d.get("d")}
    return SB.stats(daily) if daily else None


# ======================================================================
# 4. Вердикт: выводится из чисел
# ======================================================================

def _cell_of(art, s):
    for c in art.get("cells") or []:
        if abs(float(c["s"]) - float(s)) < 1e-12:
            return c
    return None


def verdict(art):
    """Убийцы по порядку; сработавший закрывает заявку.

    Порядок обязателен: (0) сторона и покрытие — до денег; (1) потолок
    на почасовых отметках — четыре условия, любое из которых убивает.
    Каждая строка несёт своё ЧИСЛО: фраза, стоящая рядом с числом, а не
    выведенная из него, стареет молча и однажды противоречит ему.
    """
    rows = []

    def add(key, title, state, text):
        rows.append({"key": key, "title": title, "state": state, "text": text})

    side = art.get("side") or {}
    if not side.get("ok"):
        add("сторона", "0. Сторона ленты ликвидаций", "блок",
            f"сторону выбрать нечем: {side.get('why')}. Замер не считается: "
            "знак был бы угадан.")
        return rows
    add("сторона", "0. Сторона ленты ликвидаций", "пройдено", str(side["why"]))

    cov = art.get("cover") or {}
    sh = cov.get("share")
    if sh is None:
        add("покрытие", "0. Покрытие журнала сводками", "блок",
            "покрытие НЕ ИЗМЕРЕНО: позиций с часами жизни не нашлось.")
        return rows
    if sh < COVER_BLOCK:
        add("покрытие", "0. Покрытие журнала сводками", "блок",
            f"сводки не покрывают журнал: каждый час жизни измерим у "
            f"{100 * sh:.1f} % позиций при пороге {100 * COVER_BLOCK:.0f} %.")
        return rows
    if sh < COVER_WARN:
        add("покрытие", "0. Покрытие журнала сводками", "оговорка",
            f"каждый час жизни измерим у {100 * sh:.1f} % позиций "
            f"({cov.get('n_uncovered')} позиций с прочерками) — вердикт ниже "
            "читается с этой оговоркой.")
    else:
        add("покрытие", "0. Покрытие журнала сводками", "пройдено",
            f"каждый час жизни измерим у {100 * sh:.1f} % позиций "
            f"(часов измеримо {100 * (cov.get('hours_share') or 0):.1f} %).")

    s = float(art.get("judged") or middle())
    cell = _cell_of(art, s)
    if cell is None:
        add("объём", "0. Помеченные позиции", "блок",
            f"судимая ячейка s = {100 * s:.1f} % не посчитана.")
        return rows
    bb = cell.get("by_book") or {}
    thin = {bk: v["n"] for bk, v in bb.items() if int(v["n"]) < MIN_MARKED}
    if thin:
        add("объём", "0. Помеченные позиции", "нечем судить",
            "событие реже, чем думали: помеченных позиций "
            + ", ".join(f"{bk} {n}" for bk, n in sorted(thin.items()))
            + f" при минимуме {MIN_MARKED} на книгу. Это результат «событие "
            "реже, чем думали», а не «правило не работает»; ось не судится.")
        return rows
    add("объём", "0. Помеченные позиции", "пройдено",
        "помечено позиций: "
        + ", ".join(f"{bk} {v['n']} (хвостовых {v['tails']})"
                    for bk, v in sorted(bb.items())))

    seeds = int(art.get("seeds") or 0)
    if seeds < CTL_SEEDS:
        add("контроль", "1а. Случайные выходы того же числа в те же часы",
            "нечем судить",
            f"контроль прогнан на {seeds} зёрнах при объявленных "
            f"{CTL_SEEDS}: разрешение доли есть 1/зёрна, и планка "
            f"{100 * BEAT_MAX:.0f} % на стольких зёрнах не измерима. Это "
            "смоук ДОРОГИ, а не вердикт о гипотезе.")
        return rows

    beat = cell.get("beat") or {}
    good = [bk for bk in art.get("books") or []
            if (beat.get(bk) or {}).get("final") is not None
            and float(beat[bk]["final"]) < BEAT_MAX]
    if len(good) < BOOKS_NEED:
        add("контроль", "1а. Случайные выходы того же числа в те же часы",
            "убивает",
            f"книг, где случайные выходы не хуже меньше чем в "
            f"{100 * BEAT_MAX:.0f} % зёрен: {len(good)} при нужных "
            f"{BOOKS_NEED} из {len(art.get('books') or [])} ("
            + ", ".join(f"{bk} {_pct((beat.get(bk) or {}).get('final'))}"
                        for bk in art.get("books") or []) + ").")
        return rows
    add("контроль", "1а. Случайные выходы того же числа в те же часы",
        "пройдено",
        f"книг, где случайные не хуже меньше чем в {100 * BEAT_MAX:.0f} % "
        f"зёрен: {len(good)} ({', '.join(good)}).")

    tails = cell.get("tails") or {}
    cut = {}
    for bk in good:
        t = tails.get(bk) or {}
        b, r = t.get("base"), t.get("rule")
        cut[bk] = (None if not b else (float(b) - float(r)) / float(b))
    bad = [bk for bk in good if cut.get(bk) is None or cut[bk] < TAIL_CUT]
    if bad:
        add("хвост", "1б. Хвостовые выходы (пол + ликвидация)", "убивает",
            f"хвостовых выходов стало меньше на "
            + ", ".join(f"{bk} {_pct(cut.get(bk))}" for bk in good)
            + f" при нужных {100 * TAIL_CUT:.0f} % в КАЖДОЙ из прошедших "
            "контроль книг.")
        return rows
    add("хвост", "1б. Хвостовые выходы (пол + ликвидация)", "пройдено",
        "хвостовых выходов стало меньше на "
        + ", ".join(f"{bk} {_pct(cut.get(bk))}" for bk in good) + ".")

    wo3 = cell.get("wo3") or {}
    grew = [bk for bk in good
            if (wo3.get(bk) or {}).get("rule") is not None
            and (wo3.get(bk) or {}).get("base") is not None
            and float(wo3[bk]["rule"]) > float(wo3[bk]["base"])]
    if not grew:
        add("концентрация", "1в. Деньги без трёх лучших дней", "убивает",
            "«$ без 3 лучших дней» не выросло ни в одной из прошедших "
            "контроль книг: "
            + ", ".join(f"{bk} {_usd((wo3.get(bk) or {}).get('base'))} → "
                        f"{_usd((wo3.get(bk) or {}).get('rule'))}"
                        for bk in good)
            + " — прибавка живёт лучшими днями.")
        return rows
    add("концентрация", "1в. Деньги без трёх лучших дней", "пройдено",
        "«$ без 3 лучших дней» выросло в "
        + ", ".join(f"{bk} {_usd((wo3.get(bk) or {}).get('base'))} → "
                    f"{_usd((wo3.get(bk) or {}).get('rule'))}" for bk in grew)
        + ".")

    dg = cell.get("diag") or {}
    dsh = dg.get("share")
    if dsh is None:
        add("механизм", "1г. Всплеск раньше худшей отметки", "не измерено",
            "хвостовых позиций с всплеском не нашлось — доля НЕ ИЗМЕРЕНА, "
            "и механизм не подтверждён ничем.")
        return rows
    if dsh < DIAG_MIN:
        add("механизм", "1г. Всплеск раньше худшей отметки", "убивает",
            f"первый всплеск стоит раньше часа худшей отметки у "
            f"{100 * dsh:.1f} % хвостовых позиций ({dg.get('early')} из "
            f"{dg.get('n')}) при пороге {100 * DIAG_MIN:.0f} %: всплеск есть "
            "КУЛЬМИНАЦИЯ, правило продаёт дно и является стопом в чужой "
            "одежде — независимо от денег.")
        return rows
    add("механизм", "1г. Всплеск раньше худшей отметки", "пройдено",
        f"первый всплеск раньше худшей отметки у {100 * dsh:.1f} % хвостовых "
        f"позиций ({dg.get('early')} из {dg.get('n')}).")
    return rows


def reading(art):
    """Одна фраза итога — ВЫВЕДЕННАЯ из строк вердикта, а не дописанная."""
    rows = art.get("verdict") or verdict(art)
    for r in rows:
        if r["state"] in ("блок", "убивает", "нечем судить", "не измерено"):
            return (f"**{r['title']}: {r['state']}.** {r['text']}")
    s = float(art.get("judged") or middle())
    return (f"**Все объявленные убийцы пройдены при s = {100 * s:.1f} %.** "
            "Это не правило и не книга: следующий шаг — внутричасовой реплей "
            "по ленте на помеченных позициях, а дорога вперёд (сестра) — "
            "решение владельца.")


# ======================================================================
# 5. Показ
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


def _side_table(side):
    L = ["| метка | колонка сводки | $ в часах падения | $ в часах роста "
         "| доля в падениях |", "|---|---|--:|--:|--:|"]
    for m in sorted(MARK_COLUMN):
        d = (side.get("usd_down") or {}).get(m)
        u = (side.get("usd_up") or {}).get(m)
        q = (side.get("share_down") or {}).get(m)
        L.append(f"| `{m}` | `{MARK_COLUMN[m]}` | {_e(d)} | {_e(u)} "
                 f"| {'—' if q is None else f'{q:.3f}'} |")
    return L


def _e(x):
    return "—" if x is None else f"{float(x):.3g}"


def _cells_table(art):
    books = art.get("books") or []
    L = ["| s | помечено сделок (хвостовых; срезано в минус) "
         "| Σ долей маржи: правило / случайные | зёрен, где случайные не хуже | "
         + " | ".join(f"{bk}: итог, просадка / зёрен не хуже" for bk in books)
         + " |", "|--:|--:|--:|--:|" + "--:|" * len(books)]
    for c in art.get("cells") or []:
        mark = "**" if abs(float(c["s"]) - float(art.get("judged") or 0)) < 1e-12 else ""
        d = c.get("delta") or {}
        if not d.get("n"):
            L.append(f"| {mark}{100 * c['s']:.1f} %{mark} | 0 | — | — |"
                     + " не сработало ни разу |" * len(books))
            continue
        cells = []
        for bk in books:
            st = (c.get("stats") or {}).get(f"{bk}:{art.get('dep')}") or {}
            bt = (c.get("beat") or {}).get(bk) or {}
            cells.append(f"{_pp(st.get('final'))}, {_pp(st.get('max_dd'))} "
                         f"/ {_pct(bt.get('final'), 0)}")
        L.append(f"| {mark}{100 * c['s']:.1f} %{mark} | {d['n']} ({d['tails']}; "
                 f"{d.get('cut_worse')}) "
                 f"| {_f(d['sum'])} / {_f((c.get('control') or {}).get('sum_med'))} "
                 f"| {_pct((c.get('beat') or {}).get('sum'), 0)} | "
                 + " | ".join(cells) + " |")
    return L


def _money_table(art, cell):
    books = art.get("books") or []
    base = art.get("base") or {}
    dep = art.get("dep")
    L = ["| книга | итог: как есть → с правилом | просадка | сделок "
         "| хвостовых выходов | $ без 3 лучших дней | дней лучше / хуже "
         "| худший день, $ | укус | медиана дня | зелёных суток |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk in books:
        b = base.get(f"{bk}:{dep}") or {}
        r = (cell.get("stats") or {}).get(f"{bk}:{dep}") or {}
        t = (cell.get("tails") or {}).get(bk) or {}
        w = (cell.get("wo3") or {}).get(bk) or {}
        dd = (cell.get("days") or {}).get(bk) or {}
        shp = (cell.get("shape") or {}).get(bk) or {}
        sb, sr = shp.get("base") or {}, shp.get("rule") or {}
        L.append(f"| {bk} | {_pp(b.get('final'))} → {_pp(r.get('final'))} "
                 f"| {_pp(b.get('max_dd'))} → {_pp(r.get('max_dd'))} "
                 f"| {_i(b.get('n'))} → {_i(r.get('n'))} "
                 f"| {_i(t.get('base'))} → {_i(t.get('rule'))} "
                 f"| {_usd(w.get('base'))} → {_usd(w.get('rule'))} "
                 f"| {_i(dd.get('better'))} / {_i(dd.get('worse'))} "
                 f"| {_usd(sb.get('worst'))} → {_usd(sr.get('worst'))} "
                 f"| {_f(sb.get('bite'), 1)} → {_f(sr.get('bite'), 1)} "
                 f"| {_f(b.get('day_median'), 5)} → {_f(r.get('day_median'), 5)} "
                 f"| {_pct(sb.get('green'))} → {_pct(sr.get('green'))} |")
    return L


def report(art):
    """Отчёт. Каждое число, которого нет, — прочерк с причиной."""
    s = float(art.get("judged") or middle())
    L = ["# Механика 357a7c60: топливо сквиза по ходу позиции", "",
         "Утверждение: всплеск принудительного ВЫКУПА ШОРТОВ в СОБСТВЕННОМ "
         "имени позиции есть сквиз в ходу, делающий хвост коротких книг "
         f"`h24`; выход на конце первого такого часа (доля выкупа в обороте "
         f"часа ≥ s при потоке ≥ {MIN_USD:,.0f} $) снимает хвостовые выходы и "
         "худший день сильнее, чем случайные выходы того же числа сделок в те "
         "же часы, и не трогает обычный день.", "",
         f"Ось объявлена до прогона: "
         + ", ".join(f"{100 * x:.1f} %" for x in art.get("axis") or AXIS_S)
         + f"; судит СЕРЕДИНА ({100 * s:.1f} %), края печатаются рядом и не "
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
          "часах падения, маркирует ликвидацию лонга.", ""]
    side = art.get("side") or {}
    L += _side_table(side) + ["", f"Решение: {side.get('why')}", ""]
    halves = (side.get("halves") or {}).get("halves") or []
    if halves:
        L += ["Та же сторона на половинах записи (кодировка обязана не "
              "меняться): "
              + "; ".join(f"{h['part']} ({'—'.join(h.get('days') or ['—'])}) — "
                          f"{h.get('mark_short') or 'НЕ ИЗМЕРЕНА'}"
                          for h in halves) + ".", ""]
    cov = art.get("cover") or {}
    L += [f"**Покрытие журнала сводками.** Позиций с часами жизни "
          f"{cov.get('n')} (закрытых в первый же час — {cov.get('no_hours')}, "
          "им правило недоступно); каждый час жизни измерим у "
          f"{cov.get('full')} ({_pct(cov.get('share'))}), часть часов — у "
          f"{cov.get('part')}, ни одного — у {cov.get('none')}. Часов жизни "
          f"{cov.get('hours')}, из них со сводкой и полями ликвидаций "
          f"{cov.get('hours_measured')} ({_pct(cov.get('hours_share'))}). Час "
          "без опроса метрик — ПРОЧЕРК, не ноль потока.", "",
          "**Сколько часов правило метит и сколько позиций.**", "",
          "| s | помеченных часов от измеримых | "
          + " | ".join(f"{bk}: позиций (хвостовых) из всех"
                       for bk in art.get("books") or []) + " |",
          "|--:|--:|" + "--:|" * len(art.get("books") or [])]
    for c in art.get("cells") or []:
        ms = c.get("marked_share") or {}
        bb = c.get("by_book") or {}
        L.append(f"| {100 * c['s']:.1f} % | {_pct(ms.get('share'), 2)} "
                 f"({ms.get('hours_marked')} из {ms.get('hours_measured')}) | "
                 + " | ".join(f"{(bb.get(bk) or {}).get('n')} "
                              f"({(bb.get(bk) or {}).get('tails')}) из "
                              f"{(bb.get(bk) or {}).get('positions')}"
                              for bk in art.get("books") or []) + " |")
    L += ["", "## 1. Потолок на почасовых отметках", "",
          "Ось применяется как шестая ось дороги сделки: час срабатывания "
          "СТРОГО до фактического выхода, деньги кассой семейства на депозите "
          f"${art.get('dep')} нетто, контроль — случайные выходы ТОГО ЖЕ "
          "числа сделок в ТЕ ЖЕ часы среди открытых, "
          f"{art.get('seeds')} зёрен.", ""]
    L += _cells_table(art) + [""]
    cell = _cell_of(art, s)
    if cell:
        L += [f"### Судимая ячейка s = {100 * s:.1f} %", ""]
        L += _money_table(art, cell) + [""]
        dg = cell.get("diag") or {}
        L += ["**Механизм или кульминация.** Первый всплеск раньше часа "
              f"худшей отметки у {_pct(dg.get('share'))} хвостовых позиций "
              f"({dg.get('early')} из {dg.get('n')}; в тот же час "
              f"{dg.get('same')}, позже {dg.get('late')}). Порог "
              f"{100 * DIAG_MIN:.0f} % объявлен до прогона: ниже — всплеск "
              "есть кульминация, и правило продаёт дно.", ""]
        pm = cell.get("perm") or {}
        real = cell.get("perm_real") or {}
        L += ["**Поток, перемешанный между именами тех же часов** "
              f"({pm.get('seeds')} зёрен) — диагностика, не убийца: "
              f"настоящий поток метит {real.get('tails')} хвостовых позиций "
              f"из {real.get('n')} помеченных, перемешанный — медиана "
              f"{_f(pm.get('med_tails'), 0)}; не хуже настоящего в "
              f"{_pct(pm.get('beat_tails'), 0)} зёрен. Много — сигнал есть "
              "«буря на рынке ликвидаций вообще», а не сквиз ЭТОГО имени, и "
              "правило сводится к стопу по волатильности.", ""]
        gc = cell.get("guard_cross") or {}
        L += ["**Пересечение с охраной рынком** (порог "
              f"{gc.get('pct')} %): из {gc.get('marked')} помеченных позиций "
              f"охрана закрыла бы {gc.get('both')}, и только поток — "
              f"{gc.get('only_flow')}; поток раньше у {gc.get('flow_first')}, "
              f"охрана раньше у {gc.get('guard_first')}, в тот же час у "
              f"{gc.get('same_hour')}. Правила читают разное: охрана — волну "
              "двадцати прокси-имён, это — поток в собственном имени.", ""]
    ls = art.get("loss_stop") or {}
    if ls:
        L += [f"### Колонка сравнения: уже измеренный стоп по убытку "
              f"{LOSS_STOP:g} маржи", "",
              "Поток, не бьющий цену, есть украшение — поэтому рядом стоит "
              "ценовой стоп, посчитанный тем же кодом и той же кассой.", "",
              "| книга | $ без 3 лучших дней: как есть / поток / ценовой стоп "
              "| дней лучше–хуже: поток / ценовой стоп |", "|---|--:|--:|"]
        for bk in art.get("books") or []:
            w = ((cell or {}).get("wo3") or {}).get(bk) or {}
            wl = (ls.get("wo3") or {}).get(bk) or {}
            dd = ((cell or {}).get("days") or {}).get(bk) or {}
            dl = (ls.get("days") or {}).get(bk) or {}
            L.append(f"| {bk} | {_usd(w.get('base'))} / {_usd(w.get('rule'))} "
                     f"/ {_usd(wl.get('rule'))} | "
                     f"{_i(dd.get('better'))}–{_i(dd.get('worse'))} / "
                     f"{_i(dl.get('better'))}–{_i(dl.get('worse'))} |")
        L += ["", f"Ценовой стоп сработал у {(ls.get('delta') or {}).get('n')} "
              f"сделок (хвостовых {(ls.get('delta') or {}).get('tails')}), "
              "поток — у "
              f"{((cell or {}).get('delta') or {}).get('n')} "
              f"(хвостовых {((cell or {}).get('delta') or {}).get('tails')}); "
              f"совпало по сделкам {ls.get('overlap')}. Контроля случайными "
              "выходами у ценового стопа здесь нет: он измерен дорогой "
              "сделки (1 / 34 / 39 % зёрен) и стоит тут колонкой, а не "
              "соперником.", ""]
    L += ["## Как это читать", ""]
    if cell:
        base = art.get("base") or {}
        nb = sum(int(((base.get(f"{bk}:{art.get('dep')}") or {}).get("n") or 0))
                 for bk in art.get("books") or [])
        nr = sum(int((((cell.get("stats") or {}).get(f"{bk}:{art.get('dep')}")
                       or {}).get("n") or 0)) for bk in art.get("books") or [])
        L += [f"- Сделок по трём книгам стало {nb} → {nr}: правило укорачивает "
              "удержание, а короткая сделка раньше освобождает кассу — книга "
              "торгует БОЛЬШЕ. Деньги книги двигает и это, не только спасённый "
              "хвост; отдельно от кассы стоит Σ долей маржи изменённых сделок, "
              "и у неё свой контроль — случайные выходы не хуже в "
              f"{_pct((cell.get('beat') or {}).get('sum'), 0)} зёрен."]
    L += ["- Ось правилом не становится: право на итерацию одно, и тратится "
          "оно на новом окне. Сестра, если владелец её заведёт, берёт "
          f"СЕРЕДИНУ оси ({100 * s:.1f} %) — не лучшую ячейку.",
          "- «Не сработало ни разу» и «правило не считалось» — разные "
          "строки: первое стоит числом помеченных часов, второе — прочерком "
          "покрытия.",
          "- Деньги нетто: издержки применены к каждой сделке "
          f"({'да' if not art.get('costs_error') else 'НЕТ — ' + str(art.get('costs_error'))}).",
          f"- Расчёт: {art.get('computed_at')}, {art.get('secs')} с, "
          f"записей {art.get('n')}.", ""]
    return "\n".join(L)
