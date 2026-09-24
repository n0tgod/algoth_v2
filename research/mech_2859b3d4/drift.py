#!/usr/bin/env python3
"""
Дрейф после экстремального начисления funding: ядро механики.

Что утверждается
----------------

После начисления funding со ставкой ниже −1 % за одно начисление (ставка,
РАСЧИТАННАЯ площадкой в момент T, а не предсказанная) цена имени
продолжает падать ещё около получаса сверх того, что это же имя делает в
те же сутки в другие часы. Ячейка вердикта объявлена заявкой и здесь
только записана числами: вход тейкером на первом снимке в окне
[T+3 с, T+10 с], выход тейкером на первом снимке в окне
[T+1800 с, T+1810 с], билет 1 000 $, плечо 1×, одна позиция на имя,
позиция НИКОГДА не проходит через расчёт.

Прохода по хранилищу здесь нет вовсе: снимки и принты подаёт
`run_drift.py`, а этот модуль работает на списках. Поэтому калибровочная
пара и проверка на заглядывание в будущее гоняются на НАСТОЯЩИХ функциях
замера, а не на их пересказе.

Сторона: почему шорт, а не лонг
-------------------------------

Соглашение загрузчика (`research/common/funding_series.py`):
положительная ставка означает, что лонги платят шортам. Отрицательная
ставка выталкивает шортов, и рефлекс carry здесь — ЛОНГ (так и устроен
`probe_fshift.side_of_rate`). Механика утверждает ПРОТИВОПОЛОЖНОЕ и
именно поэтому она не carry: позиция открывается ПОСЛЕ расчёта, когда
выплата уже произошла, и живёт тридцать минут на потоке тех, кто стоял в
длинной ради выплаты и после неё продаёт. Ни одного начисления внутри
позиции нет, funding она не платит и не получает вовсе.

Знак закреплён ЧИСЛОМ (`test_side_by_number`): перевёрнутый развернул бы
сторону молча, и весь замер описывал бы другую сделку.

Две модели издержек, и обе объявлены
------------------------------------

* **плоская** — взятие считается по лучшим ценам (продажа по биду,
  выкуп по аску, спред внутри) минус круг 19.8 б.п.: комиссия тейкера
  11 (`research/s8_loop/trades.py`) плюс проскальзывание X3 4.4 на ногу
  (`research/dca_paper/costs.py`, живой замер 300 $). Это НИЖНЯЯ
  граница издержек: 4.4 намерено на билете в 300 $;
* **проходом по лесенке** (убийца K2) — вход продаёт в биды записанного
  стакана на 1 000 $ нотионала, выход выкупает ровно те же монеты с
  асков; проскальзывание тогда не константа, а то, что лежало в
  записи, и к нему добавляется только комиссия 11 б.п.

Лесенка записи конечна (50 уровней у альтов, `reach_b` бывает 20 б.п., а
бывает 160). Билет, который её исчерпал, даёт **прочерк, а не ноль**:
цена за пределами записи неизвестна, и назвать её нулём проскальзывания
значило бы выдумать число. Доля таких событий печатается.

Что здесь НЕ решается
---------------------

Ни один порог этим модулем не назначен. Полосы ставки, окна входа и
выхода, билет, число зёрен, доля покрытия — объявлены заявкой
(`research/factory/out/proposal.md`) и стоят здесь константами с
именами. Правило вылета по форме не переписано, а вызвано:
`factory/pool.shape_why` и `factory/stability.stats` — те же, которыми
судят живые книги.

Только numpy и stdlib.
"""

import bisect
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "dca_paper"),
           RESEARCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import costs as CO                                           # noqa: E402
import pool as PL                                            # noqa: E402
import stability as SB                                       # noqa: E402
import trades as TR                                          # noqa: E402

MS_S = 1000
MS_H = 3_600_000
MS_D = 86_400_000

# --- ячейка вердикта: всё объявлено заявкой ---------------------------

ENTRY_LAG_S = 3           # вход не раньше третьей секунды после расчёта
ENTRY_MAX_LAG_S = 10      # позже — событие НЕ ПОКРЫТО записью
EXIT_S = 1800             # выход через тридцать минут
# Допуск выхода. Заявка говорит «первый снимок ≥ T+1800 с» и верхней
# границы не называет. Без границы дыра в записи молча отдала бы цену из
# другого часа — а именно этим дефектом («ряд, скачанный однажды,
# стареет молча») проект уже платил. Берётся ТОТ ЖЕ допуск, что у входа:
# выход приходится на середину часа, где первый снимок после точки
# отстаёт на 0.8 с медианно и 4.2 с в девяностом перцентиле (§9 заявки),
# так что десять секунд — запас, а не отбор. Событие без снимка выхода в
# допуске идёт в НЕПОКРЫТЫЕ, и число таких печатается.
EXIT_MAX_LAG_S = ENTRY_MAX_LAG_S
TICKET_USD = 1000.0       # билет; плечо 1× — ликвидации нет по построению
LEVERAGE = 1.0

# Полосы ставки. Судит первая, остальные печатаются рядом и не судят.
VERDICT_BAND = "lt1"
BANDS = (
    ("lt1", None, -0.01, -1),
    ("m1_m05", -0.01, -0.005, -1),
    ("m05_m02", -0.005, -0.002, -1),
    ("pos", 0.002, None, +1),
    ("quiet", -0.0005, 0.0005, -1),
)
BAND_TITLE = {"lt1": "< −1 %", "m1_m05": "−1…−0.5 %",
              "m05_m02": "−0.5…−0.2 %", "pos": "длинная, > +0.2 %",
              "quiet": "тихие границы часа"}

# Издержки. Оба числа ВВЕЗЕНЫ, а не повторены: круг тейкера живёт в
# `trades.ROUND_COST_BP`, живое проскальзывание X3 — в `costs.SLIP_BP`.
COMMISSION_BP = float(TR.ROUND_COST_BP)          # 11 б.п. на круг
SLIP_BP = float(CO.SLIP_BP)                      # 4.4 б.п. на ногу
FLAT_COST_BP = COMMISSION_BP + 2 * SLIP_BP       # 19.8 б.п.
# Проход по лесенке САМ несёт проскальзывание — константу к нему не
# добавляют, иначе одно и то же заплачено дважды.
WALK_COST_BP = COMMISSION_BP

# Контроли и нули
SEEDS = 200               # зёрен у случайной выборки
RNG_SEED = 0              # зерно зерна: прогон обязан повторяться
MIN_COVER = 0.70          # ниже — K0 блокирует: судится запись, а не рынок
K1_MAX_SHARE = 0.05       # случайная не хуже в ≥ 5 % зёрен — механика мертва
CONTROL_GAP_H = 2         # контроль не ближе двух часов к событию
CONTROL_MAX_RATE = 0.002  # граница часа со ставкой круче — не контроль
TOP_DAYS = 3              # «без трёх лучших дней»
K4_MIN_EVENTS = 30        # вперёд: меньше — вердикта нет вовсе
FORWARD_FROM = "2026-09-24"   # день объявления ячейки (задание)

# Профиль середины. Диагностика, не вердикт.
PROFILE_POINTS = (-60, -2, 0, 1, 3, 60, 300, 900, 1800)
PROFILE_BASE_S = -60
PROFILE_TOL_S = 60        # диагностике допуск шире: она никого не судит
# Профиль ДО СЛЕДУЮЩЕГО начисления: долями интервала, потому что шаг у
# площадки разный (1, 2, 4 и 8 ч), и «через четыре часа» для часового
# имени означало бы четыре пропущенных расчёта.
NEXT_FRACTIONS = (0.25, 0.5, 0.75, 1.0)
FLOW_WINDOW_S = 60        # лента за первую минуту после расчёта
# Сплошное диагностическое окно после расчёта: в нём меряется дыра
# записи. Прогон обязан прочитать ровно его; дальше идёт уже снимок
# выхода, и мерить по нему «задержку» значило бы выдумать полчаса.
DIAG_CAP_S = 180
DEPTH_FIELD = "0025"      # глубина в 25 б.п. — поле записи, не наш счёт


class Empty(Exception):
    """Ноль наблюдений при непустом входе.

    Отдельное исключение, а не отчёт с прочерками: пустота не вправе
    выдавать себя за результат. Прочерк ставится ВЕЛИЧИНЕ, которой нет;
    отсутствие всех величин при непустом входе — отказ.
    """


# --- полосы и сторона -------------------------------------------------

def band_of(rate):
    """Полоса ставки или None — «вне объявленных полос».

    Полоса замкнута СНИЗУ и открыта сверху: `lo ≤ ставка < hi`. Иначе
    ставка ровно в −1 % не попала бы никуда — ни в ячейку вердикта (там
    строго «ниже −1 %»), ни в соседнюю полосу, — и выпала бы из замера
    молча. Ячейка вердикта от соглашения не зависит: она объявлена
    строгим неравенством и им же осталась.

    None означает «вне полос» и НЕ означает «тихая»: между −0.2 % и
    −0.05 % лежит ставка, которая ни крайняя, ни тихая, и считать её
    тишиной значило бы разбавить контроль.
    """
    if rate is None or not np.isfinite(rate):
        return None
    for name, lo, hi, _side in BANDS:
        if name == "quiet":
            if abs(rate) <= hi:
                return name
            continue
        if lo is not None and rate < lo:
            continue
        if hi is not None and rate >= hi:
            continue
        return name
    return None


def side_of_band(band):
    """Сторона позиции полосы. −1 шорт, +1 лонг, None — полосы нет.

    ВНИМАНИЕ: это НЕ `probe_fshift.side_of_rate`. Тот отвечает на вопрос
    carry — «кого выталкивает ставка», и при отрицательной ставке даёт
    ЛОНГ. Здесь сторона задана утверждением механики: после крайне
    отрицательного начисления цена продолжает падать, и позиция —
    ШОРТ. Две противоположные стороны в одном проекте обязаны быть
    названы врозь и закреплены числом, иначе одна из них однажды
    подменит другую.
    """
    for name, _lo, _hi, side in BANDS:
        if name == band:
            return side
    return None


def legs_of(side):
    """Какие стороны стакана ест сделка: (вход, выход).

    Шорт продаёт в биды и выкупает с асков, лонг наоборот.
    """
    return ("b", "a") if side < 0 else ("a", "b")


# --- выбор снимков: строго по объявленным окнам -----------------------

def snapshot_index(ts_list, lo_ms, hi_ms):
    """Индекс ПЕРВОГО снимка в окне [lo, hi] либо None.

    Верхняя граница обязательна. Без неё «первый снимок не раньше
    T+3 с» на дыре записи молча берёт снимок через сорок минут, и
    сделка оказывается другой — той, которую никто не объявлял.
    """
    i = bisect.bisect_left(ts_list, lo_ms)
    if i >= len(ts_list):
        return None
    if ts_list[i] > hi_ms:
        return None
    return i


def first_after_s(ts_list, t_ms, lag_s=ENTRY_LAG_S, cap_s=DIAG_CAP_S):
    """Задержка ПЕРВОГО снимка не раньше T+`lag_s`, секундами.

    Это диагностика самого сборщика, а не выбор цены: именно она
    превращает «событие непокрыто» из счёта в измеренную величину —
    иначе K0 говорит, что запись плоха, и не говорит НАСКОЛЬКО.

    `cap_s` обязателен и равен ширине сплошного диагностического окна,
    которое читает прогон. За его пределами следующий доступный снимок —
    это уже снимок ВЫХОДА, в получасе, и вернуть его значило бы
    объявить дыру в полчаса там, где её никто не мерил. Дыра длиннее
    потолка — `None`, то есть прочерк, и такие события считаются
    отдельным числом.
    """
    i = bisect.bisect_left(ts_list, t_ms + lag_s * MS_S)
    if i >= len(ts_list):
        return None
    v = (ts_list[i] - t_ms) / MS_S
    if cap_s is not None and v > cap_s:
        return None
    return v


def entry_exit(ts_list, t_ms, entry_lag_s=ENTRY_LAG_S,
               entry_max_s=ENTRY_MAX_LAG_S, exit_s=EXIT_S,
               exit_max_s=EXIT_MAX_LAG_S):
    """(индекс входа, индекс выхода, причина непокрытия).

    Причина — строка или None. Строка означает «событие не покрыто
    записью», и это НЕ то же самое, что «сделка не заработала»: первое
    судит запись, второе — рынок, и K0 отвечает именно за первое.
    """
    i_in = snapshot_index(ts_list, t_ms + entry_lag_s * MS_S,
                          t_ms + entry_max_s * MS_S)
    if i_in is None:
        return None, None, (f"нет снимка входа в окне T+{entry_lag_s}…"
                            f"{entry_max_s} с")
    i_out = snapshot_index(ts_list, t_ms + exit_s * MS_S,
                           t_ms + (exit_s + exit_max_s) * MS_S)
    if i_out is None:
        # Индекс входа возвращается и здесь: K0 объявлен как «доля
        # событий, у которых есть снимок ВХОДА», и склеив две разные
        # беды в одну, мы считали бы дыру на выходе браком входа.
        return i_in, None, (f"нет снимка выхода в окне T+{exit_s}…"
                            f"{exit_s + exit_max_s} с")
    return i_in, i_out, None


# --- лесенка ----------------------------------------------------------

def ladder(snap, kind):
    """Уровни стороны стакана, от ЛУЧШЕЙ цены. `kind` — 'b' либо 'a'.

    Порядок наводится здесь, а не предполагается. Запись его соблюдает,
    но проход по лесенке, начатый не с лучшей цены, даёт цену
    исполнения лучше возможной — ошибку, которая выглядит как эдж.
    """
    out = []
    for lv in (snap.get(kind) or ()):
        try:
            p, v = float(lv[0]), float(lv[1])
        except (TypeError, ValueError, IndexError):
            continue
        if p > 0 and v > 0:
            out.append((p, v))
    out.sort(key=(lambda x: -x[0]) if kind == "b" else (lambda x: x[0]))
    return out


def walk_open(levels, usd):
    """Открыть на `usd` долларов нотионала проходом по лесенке.

    Возвращает (средняя цена, монет) либо **None**, если записанной
    лесенки не хватило на билет: цена за её пределами неизвестна, и
    частичное исполнение, выданное за полное, польстило бы входу.
    """
    if usd <= 0:
        return None
    got, coins = 0.0, 0.0
    for p, v in levels:
        cap = p * v
        if got + cap >= usd:
            coins += (usd - got) / p
            return usd / coins, coins
        got += cap
        coins += v
    return None                      # лесенки записи не хватило на билет


def walk_close(levels, coins):
    """Закрыть ровно `coins` монет проходом по лесенке.

    Возвращает среднюю цену либо None — лесенки не хватило.
    """
    if coins <= 0:
        return None
    left, paid = float(coins), 0.0
    for p, v in levels:
        take = v if v < left else left
        paid += take * p
        left -= take
        if left <= 1e-12:
            return paid / coins
    return None                      # лесенки записи не хватило на выкуп


def depth_usd(snap, kind, field=DEPTH_FIELD):
    """Глубина в 25 б.п. от лучшей цены, долларами. None — поля нет.

    Берётся ПОЛЕ ЗАПИСИ (`bq0.0025` / `aq0.0025`), а не считается заново
    по уровням: сборщик считает его на полном стакане, а в файл кладёт
    срез уровней — свой счёт по срезу дал бы другое число под тем же
    именем.
    """
    v = snap.get(("bq0." if kind == "b" else "aq0.") + field)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --- арифметика сделки ------------------------------------------------

def take_bp(p_in, p_out, side, cost_bp):
    """Взятие позиции нетто, в базисных пунктах.

    Одно место на весь замер: событие, контроль, плацебо и калибровка
    считаются этой функцией. Вторая формула знака стороны однажды
    разошлась бы, и таблица сравнивала бы шорт с лонгом.
    """
    if not (p_in and p_out) or p_in <= 0:
        return None
    return float(side) * (float(p_out) - float(p_in)) / float(p_in) * 1e4 \
        - float(cost_bp)


def mid(snap):
    """Середина стакана. None — цены нет."""
    b, a = snap.get("bid"), snap.get("ask")
    if not b or not a:
        return None
    return (float(b) + float(a)) / 2.0


def spread_bp(snap):
    """Спред снимка в базисных пунктах середины. None — цены нет."""
    m = mid(snap)
    if not m:
        return None
    return (float(snap["ask"]) - float(snap["bid"])) / m * 1e4


def best_prices(s_in, s_out, side):
    """Цены тейкера по лучшим ценам: (вход, выход). Спред внутри."""
    if side < 0:
        return s_in.get("bid"), s_out.get("ask")
    return s_in.get("ask"), s_out.get("bid")


def flow_usd(prints, t0_ms, t1_ms):
    """Лента за окно: продано минус куплено, долларами.

    Сторона принта — сторона АГРЕССОРА (`b1_book/book.parse_trades`):
    +1 значит «купили по аску». Перевес продаж — величина
    положительная, и именно она утверждается механикой как
    принудительный поток.
    """
    s = 0.0
    n = 0
    for t in prints or ():
        ts = t[0] if isinstance(t, (tuple, list)) else t.get("ts")
        if ts is None or ts < t0_ms or ts > t1_ms:
            continue
        if isinstance(t, (tuple, list)):
            side, p, v = t[1], t[2], t[3]
        else:
            side, p, v = t.get("side"), t.get("p"), t.get("v")
        try:
            s -= float(side) * float(p) * float(v)
        except (TypeError, ValueError):
            continue
        n += 1
    return (s, n) if n else (None, 0)


# --- замер одного события ---------------------------------------------

def measure_event(snaps, t_ms, side, ticket_usd=TICKET_USD, prints=None,
                  next_accrual_ms=None, **win):
    """Одна сделка ячейки. Возвращает строку замера (словарь).

    `snaps` — снимки ОДНОГО имени, отсортированные по метке; каждый
    несёт `ts`, `bid`, `ask`, `b`, `a` и поля глубины. `prints` — лента
    того же имени. `next_accrual_ms` — метка СЛЕДУЮЩЕГО начисления:
    позиция не вправе через него пройти, и это проверяется, а не
    предполагается.

    Поле `cover` отвечает на вопрос K0 («есть ли запись»), поля
    `flat_bp` и `walk_bp` — на вопрос рынка. Величина, которой нет,
    равна None и печатается прочерком: ноль означал бы «измерено и равно
    нулю».
    """
    row = {"ts": int(t_ms), "side": int(side), "in_record": bool(snaps),
           "cover": False, "used": False, "why": None,
           "entry_ts": None, "exit_ts": None, "entry_lag_s": None,
           "exit_lag_s": None, "mid_in": None, "mid_out": None,
           "spread_in_bp": None, "spread_out_bp": None,
           "flat_bp": None, "mid_bp": None, "walk_bp": None,
           "walk_in_bp": None,
           "walk_out_bp": None, "depth_bp25": None, "flow_usd": None,
           "flow_prints": 0, "coins": None, "ticket": float(ticket_usd),
           "first_after_s": None, "snaps_minute": None, "entry_ok": False}
    ts_list = [s["ts"] for s in snaps]
    if ts_list != sorted(ts_list):
        raise ValueError("снимки поданы не по возрастанию метки")
    if not ts_list:
        # Снимков имени вокруг расчёта нет ВОВСЕ — ни одного за
        # получас, хотя сборщик пишет их тысячами в час. Значит имя
        # тогда не собиралось (состав записи рос ступенями 25 → 518 →
        # 559 → 725 имён), и это НЕ пауза у границы часа. Различать
        # обязательно: K0 спрашивает, годна ли ЗАПИСЬ там, где она есть,
        # а «имени в записи ещё не было» — не измерено, и мерой
        # качества записи служить не может. Оба числа печатаются.
        row["why"] = "снимков имени вокруг расчёта нет: запись его не вела"
        return row
    # Диагностика сборщика: считается ДО всякого выбора цены и у
    # непокрытых событий тоже — именно она отвечает, насколько запись
    # опоздала, а не только «опоздала ли».
    row["first_after_s"] = first_after_s(
        ts_list, t_ms, win.get("entry_lag_s", ENTRY_LAG_S))
    row["snaps_minute"] = sum(1 for t in ts_list
                              if t_ms <= t <= t_ms + 60 * MS_S)
    i_in, i_out, why = entry_exit(ts_list, t_ms, **win)
    row["entry_ok"] = i_in is not None
    if why:
        row["why"] = why
        return row
    exit_ts = ts_list[i_out]
    # Покрытие записью УЖЕ установлено: снимки входа и выхода есть, и
    # именно на этот вопрос отвечает K0. Расписание площадки к записи
    # отношения не имеет, поэтому событие, чья позиция прошла бы через
    # расчёт, покрытым остаётся, но сделки не даёт — иначе K0 судил бы
    # календарь биржи вместо нашего сборщика.
    row["cover"] = True
    if next_accrual_ms is not None and int(next_accrual_ms) <= exit_ts:
        # Позиция прошла бы через расчёт — это уже другая сделка, с
        # выплатой внутри. Ячейка вердикта такого не содержит.
        row["why"] = "следующее начисление внутри позиции"
        return row
    s_in, s_out = snaps[i_in], snaps[i_out]
    row["used"] = True
    row["entry_ts"], row["exit_ts"] = ts_list[i_in], exit_ts
    row["entry_lag_s"] = (ts_list[i_in] - t_ms) / MS_S
    row["exit_lag_s"] = (exit_ts - t_ms - EXIT_S * MS_S) / MS_S
    row["mid_in"], row["mid_out"] = mid(s_in), mid(s_out)
    # Спред считается и печатается ОТДЕЛЬНО, хотя он уже внутри взятия.
    # Без него разница между «взятием по серединам» и «взятием по
    # лучшим ценам» выглядит необъяснимой, а она ровно в спред и есть:
    # у тесных имён в сквизе он десятки базисных пунктов, и это главная
    # причина, по которой одна и та же сделка считается двумя числами.
    row["spread_in_bp"] = spread_bp(s_in)
    row["spread_out_bp"] = spread_bp(s_out)

    p_in, p_out = best_prices(s_in, s_out, side)
    row["flat_bp"] = take_bp(p_in, p_out, side, FLAT_COST_BP)
    # То же взятие ПО СЕРЕДИНАМ — диагностика и верхняя граница: так
    # считают, когда спред «забывают», и разница двух чисел равна
    # спреду. Судит `flat_bp`: тейкер платит спред, и полоса событий —
    # тесные имена, где он десятки базисных пунктов.
    row["mid_bp"] = take_bp(row["mid_in"], row["mid_out"], side,
                            FLAT_COST_BP)

    leg_in, leg_out = legs_of(side)
    lad_in = ladder(s_in, leg_in)
    opened = walk_open(lad_in, ticket_usd)
    if opened is not None:
        w_in, coins = opened
        w_out = walk_close(ladder(s_out, leg_out), coins)
        if w_out is not None:
            row["coins"] = coins
            row["walk_bp"] = take_bp(w_in, w_out, side, WALK_COST_BP)
            if p_in:
                row["walk_in_bp"] = abs(w_in - p_in) / p_in * 1e4
            if p_out:
                row["walk_out_bp"] = abs(w_out - p_out) / p_out * 1e4
    row["depth_bp25"] = depth_usd(s_in, leg_in)
    if prints is not None:
        f, n = flow_usd(prints, t_ms, t_ms + FLOW_WINDOW_S * MS_S)
        row["flow_usd"], row["flow_prints"] = f, n
    return row


def usd_of(row, field="flat_bp"):
    """Деньги строки: базисные пункты × билет. None — прочерк."""
    v = row.get(field)
    if v is None:
        return None
    return float(v) / 1e4 * float(row.get("ticket") or TICKET_USD)


def profile_bp(snaps, t_ms, points=PROFILE_POINTS, base_s=PROFILE_BASE_S,
               tol_s=PROFILE_TOL_S):
    """Ход середины от T+`base_s`, в базисных пунктах, по точкам.

    Диагностика: она ничего не судит и потому живёт с широким допуском.
    Точка без снимка — None, а не ноль.
    """
    ts_list = [s["ts"] for s in snaps]
    i0 = snapshot_index(ts_list, t_ms + base_s * MS_S,
                        t_ms + (base_s + tol_s) * MS_S)
    if i0 is None:
        return None
    m0 = mid(snaps[i0])
    if not m0:
        return None
    out = {}
    for p in points:
        i = snapshot_index(ts_list, t_ms + p * MS_S,
                           t_ms + (p + tol_s) * MS_S)
        m = mid(snaps[i]) if i is not None else None
        out[p] = None if not m else (m - m0) / m0 * 1e4
    return out


def profile_to_next(snaps, t_ms, next_ms, fracs=NEXT_FRACTIONS,
                    base_s=PROFILE_BASE_S, tol_s=PROFILE_TOL_S):
    """Ход середины от T+`base_s` ДО следующего начисления, долями пути.

    Диагностика: она отвечает на вопрос «а дальше-то что», и вердикта не
    несёт — позиция ячейки живёт тридцать минут и до следующего расчёта
    не доживает по построению. `None` — следующего начисления в ряду нет
    либо записи на эту долю пути нет; ноль здесь означал бы «цена
    вернулась», а это другое утверждение.
    """
    if next_ms is None:
        return None
    span = int(next_ms) - int(t_ms)
    if span <= 0:
        return None
    ts_list = [s["ts"] for s in snaps]
    i0 = snapshot_index(ts_list, t_ms + base_s * MS_S,
                        t_ms + (base_s + tol_s) * MS_S)
    if i0 is None:
        return None
    m0 = mid(snaps[i0])
    if not m0:
        return None
    out = {}
    for f in fracs:
        at = int(t_ms + span * float(f))
        i = snapshot_index(ts_list, at, at + tol_s * MS_S)
        m = mid(snaps[i]) if i is not None else None
        out[f] = None if not m else (m - m0) / m0 * 1e4
    return out


def lag_stats(rows):
    """Дыра записи у границы часа: задержка входа и выхода, секундами.

    Это МЕРА САМОГО СБОРЩИКА, а не рынка, и она печатается рядом с K0:
    у границы часа смена часа закрывает и сжимает все файлы разом, и
    первый снимок после расчёта отстаёт. Величина, которой нет,
    отсутствует в своде, а не равна нулю.
    """
    out = {}
    for f in ("entry_lag_s", "exit_lag_s"):
        v = _finite([r.get(f) for r in rows if r.get("cover")])
        if not v:
            out[f] = None
            continue
        a = np.asarray(v, dtype=float)
        out[f] = {"n": len(v), "med": float(np.median(a)),
                  "p90": float(np.percentile(a, 90)),
                  "p95": float(np.percentile(a, 95)),
                  "max": float(a.max())}
    return out


# --- своды ------------------------------------------------------------

def _finite(xs):
    return [float(x) for x in xs if x is not None and np.isfinite(x)]


def stat_block(vals):
    """Медиана, среднее, перцентили, доля выше круга. Пусто — отказ.

    «Выше круга» есть `> 0`, потому что взятие уже НЕТТО: круг вычтен
    в `take_bp`. Сравнивать нетто ещё раз с кругом значило бы заплатить
    издержки дважды — ошибка единиц, ловленная в проекте пять раз.
    """
    v = _finite(vals)
    if not v:
        raise Empty("ни одного взятия при непустом входе")
    a = np.asarray(v, dtype=float)
    return {"n": len(v), "med": float(np.median(a)), "mean": float(a.mean()),
            "p10": float(np.percentile(a, 10)),
            "p25": float(np.percentile(a, 25)),
            "p75": float(np.percentile(a, 75)),
            "p90": float(np.percentile(a, 90)),
            "min": float(a.min()), "max": float(a.max()),
            "above_cost": float((a > 0).mean()),
            "worse_100": float((a < -100).mean())}


def day_no(ts_ms):
    return int(ts_ms) // MS_D


def daily_usd(rows, field="flat_bp"):
    """{номер суток: деньги за эти сутки}. Непокрытые строки не считаются.

    Непокрытое событие не есть убыточный день: сделки не было вовсе.
    Смешав их, мы посчитали бы дыру в записи торговлей.
    """
    out = {}
    for r in rows:
        v = usd_of(r, field)
        if v is None:
            continue
        d = day_no(r["ts"])
        out[d] = out.get(d, 0.0) + v
    return out


def without_top_days(daily, k=TOP_DAYS):
    """Сумма без `k` лучших суток. Колонка обязательная: концентрация
    переворачивает знак, и без неё эпизод читается трендом."""
    vals = sorted(daily.values(), reverse=True)
    return float(sum(vals[k:]))


def by_name(rows, field="flat_bp"):
    """{имя: деньги}. Имя берётся из строки замера."""
    out = {}
    for r in rows:
        v = usd_of(r, field)
        if v is None:
            continue
        s = r.get("sym") or "?"
        out[s] = out.get(s, 0.0) + v
    return out


def halves(rows, field="flat_bp"):
    """Деньги первой и второй половин окна по КАЛЕНДАРЮ, не по числу
    сделок: половина, в которой сделок вдвое больше, — тоже ответ."""
    ts = [r["ts"] for r in rows if usd_of(r, field) is not None]
    if not ts:
        return None, None
    lo, hi = min(ts), max(ts)
    cut = lo + (hi - lo) / 2.0
    a = sum(usd_of(r, field) for r in rows
            if usd_of(r, field) is not None and r["ts"] <= cut)
    b = sum(usd_of(r, field) for r in rows
            if usd_of(r, field) is not None and r["ts"] > cut)
    return float(a), float(b)


def form(rows, field="flat_bp", top=TOP_DAYS):
    """Форма по суткам — ТОЙ ЖЕ мерой, которой судят живые книги.

    `stability.stats` не переписывается: вторая копия «укуса» однажды
    разошлась бы с правилом вылета, и отчёт обещал бы одно, а пул судил
    другое.
    """
    daily = daily_usd(rows, field)
    if not daily:
        raise Empty("ни одних суток с закрытой сделкой")
    st = SB.stats(daily)
    names = by_name(rows, field)
    best = max(names, key=lambda k: names[k]) if names else None
    h1, h2 = halves(rows, field)
    return {"st": st, "days": len(daily),
            "tot": float(sum(daily.values())),
            "without_top": without_top_days(daily, top),
            "top_days": top,
            "best_name": best,
            "best_name_usd": None if best is None else names[best],
            "without_best_name": (None if best is None
                                  else float(sum(v for k, v in names.items()
                                                 if k != best))),
            "half1": h1, "half2": h2, "daily": daily}


# --- K0: покрытие записью ---------------------------------------------

def k0(rows, min_share=MIN_COVER):
    """Доля событий со снимком входа и выхода. Печатается ПЕРВОЙ.

    Знаменатель — события, которые запись ВЕДЁТ («покрытые»), а не все
    начисления окна: состав записи рос ступенями 25 → 518 → 559 → 725
    имён, и начисление имени, которого тогда не собирали, — это «не
    измерено», а не брак сборщика. K0 спрашивает ровно одно: годна ли
    запись там, где она есть. Оба числа печатаются, и событие вне записи
    молча не исчезает.

    Вердиктовая фраза выведена из числа, а не поставлена рядом: фраза,
    стоящая рядом с числом, стареет молча и однажды ему противоречит.
    """
    total = len(rows)
    if not total:
        return {"ok": None, "n": 0, "in_record": 0, "cover": 0,
                "share": None,
                "say": "событий в окне нет — покрытие не измерено"}
    inrec = sum(1 for r in rows if r.get("in_record"))
    # Судит ВХОД: K0 объявлен как «доля событий, у которых в записи есть
    # снимок входа не позже T+10 с». Событий со сделкой (вход И выход)
    # печатается рядом — это другая величина, и молча подменять ею
    # объявленную нельзя.
    ent = sum(1 for r in rows if r.get("entry_ok"))
    cov = sum(1 for r in rows if r.get("cover"))
    used = sum(1 for r in rows if r.get("used"))
    why = {}
    for r in rows:
        if r.get("why"):
            why[r["why"]] = why.get(r["why"], 0) + 1
    if not inrec:
        return {"ok": None, "n": total, "in_record": 0, "cover": 0,
                "used": 0, "why": why, "share": None,
                "say": f"ни одно из {total} событий окна запись не вела — "
                       "покрытие не измерено, а не равно нулю"}
    share = ent / inrec
    ok = share >= min_share
    # Насколько именно опоздала запись — ВЕЛИЧИНОЙ, а не счётом: «запись
    # плоха» без числа не лечится и не проверяется.
    late = _finite([r.get("first_after_s") for r in rows
                    if r.get("in_record")])
    lag = None
    if late:
        a = np.asarray(late, dtype=float)
        lag = {"n": len(late), "med": float(np.median(a)),
               "p90": float(np.percentile(a, 90)),
               "p95": float(np.percentile(a, 95)),
               "max": float(a.max())}
    cad = _finite([r.get("snaps_minute") for r in rows
                   if r.get("in_record")])
    say = (f"покрытие входа {share:.1%} ({ent} из {inrec} покрытых "
           f"записью; до сделки со снимком выхода дошло {cov}; ещё "
           f"{total - inrec} начислений запись не вела вовсе)"
           + (f" — выше порога {min_share:.0%}, судим рынок"
              if ok else
              f" — БЛОК: ниже порога {min_share:.0%}, судится запись, "
              "а не рынок")
           + (f"; первый снимок не раньше T+{ENTRY_LAG_S} с приходит с "
              f"задержкой {lag['med']:.1f} с медианно и {lag['p90']:.1f} "
              f"в девяностом перцентиле при потолке {ENTRY_MAX_LAG_S} с"
              if lag else ""))
    return {"ok": ok, "n": total, "in_record": inrec, "entry": ent,
            "cover": cov, "used": used, "share": share, "why": why,
            "lag": lag, "holes_over_cap": inrec - len(late),
            "snaps_minute_med": (float(np.median(cad)) if cad else None),
            "say": say}


# --- K1: контроль тех же имени и суток --------------------------------

def control_times(hours, accruals, events, gap_h=CONTROL_GAP_H,
                  max_rate=CONTROL_MAX_RATE):
    """Границы часа, годные в контроль.

    `hours` — все границы часа суток (мс), `accruals` — {метка: ставка}
    этого имени, `events` — метки событий этого имени.

    Годна граница, которая: не является начислением со ставкой круче
    `max_rate` по модулю; отстоит от КАЖДОГО события не меньше чем на
    `gap_h` часов. Второе условие берёт все события имени, а не только
    события этих суток: эпизод, севший на полночь, иначе дал бы контроль
    в двух часах от события предыдущего дня.
    """
    out = []
    for t in sorted(hours):
        r = accruals.get(t)
        if r is not None and abs(r) > max_rate:
            continue
        if any(abs(t - e) < gap_h * MS_H for e in events):
            continue
        out.append(t)
    return out


def seed_shares(ev_vals, pools, seeds=SEEDS, rng_seed=RNG_SEED):
    """Доля зёрен, где случайная выборка ТОГО ЖЕ размера не хуже события.

    `ev_vals` — значения событий, `pools` — список списков: по одному
    пулу контролей на событие (контроли ЕГО имени и суток). Событие с
    пустым пулом выбывает вместе со своим контролем — иначе сравнивались
    бы выборки разного размера.

    Сравниваются ДВЕ величины, и обе объявлены заявкой: сумма нетто и
    медиана взятия. Одна выборка сама по себе шум; разрешение доли есть
    1/зёрна.
    """
    pairs = [(v, p) for v, p in zip(ev_vals, pools)
             if v is not None and np.isfinite(v) and p]
    if not pairs:
        raise Empty("ни одного события с непустым пулом контролей")
    vals = np.array([v for v, _ in pairs], dtype=float)
    ev_sum, ev_med = float(vals.sum()), float(np.median(vals))
    rng = np.random.default_rng(rng_seed)
    sums, meds = [], []
    for _ in range(seeds):
        pick = np.array([p[rng.integers(len(p))] for _, p in pairs],
                        dtype=float)
        sums.append(float(pick.sum()))
        meds.append(float(np.median(pick)))
    s = np.asarray(sums)
    m = np.asarray(meds)
    return {"n": len(pairs), "seeds": seeds,
            "ev_sum": ev_sum, "ev_med": ev_med,
            "share_sum": float((s >= ev_sum).mean()),
            "share_med": float((m >= ev_med).mean()),
            "ctl_sum_med": float(np.median(s)), "ctl_sum_max": float(s.max()),
            "ctl_med_med": float(np.median(m)),
            "ctl_med_p95": float(np.percentile(m, 95))}


def k1(sh, max_share=K1_MAX_SHARE):
    """Вердикт контроля. Мертва, если случайная не хуже в ≥ 5 % зёрен
    хотя бы по ОДНОЙ из двух величин."""
    if sh is None:
        return {"ok": None, "say": "контроль не измерен"}
    dead = (sh["share_sum"] >= max_share) or (sh["share_med"] >= max_share)
    return {"ok": not dead, "share_sum": sh["share_sum"],
            "share_med": sh["share_med"],
            "say": (f"случайная выборка того же размера не хуже события "
                    f"в {sh['share_sum']:.1%} зёрен по сумме и "
                    f"{sh['share_med']:.1%} по медиане"
                    + (f" — обе ниже {max_share:.0%}, потолок подтверждён"
                       if not dead else
                       f" — МЕРТВА: порог {max_share:.0%} достигнут"))}


def percentile_among(x, xs):
    """Перцентиль значения среди контролей. None — сравнивать не с чем.

    Та же мера, что у `probe_fshift.rate_extremity`: доля контролей
    СТРОГО МЕНЬШЕ. Нуль такой меры — 0.5.
    """
    v = _finite(xs)
    if x is None or not np.isfinite(x) or not v:
        return None
    return float(np.searchsorted(np.sort(v), float(x), side="left") / len(v))


def calib_percentile(ev_rows, ctl_rows_by_key, key_of, field="flat_bp"):
    """Средний и медианный перцентиль события среди СВОИХ контролей.

    Это величина калибровочной пары: подсаженный дрейф обязан поднять её
    к 1, шум — оставить у 0.5. Без такой пары сломанная загрузка
    выглядит ровно как «эффекта нет», и в этом проекте так уже бывало
    дважды.
    """
    ps = []
    for r in ev_rows:
        v = usd_of(r, field)
        pool = [usd_of(c, field) for c in ctl_rows_by_key.get(key_of(r), ())]
        p = percentile_among(v, pool)
        if p is not None:
            ps.append(p)
    if not ps:
        raise Empty("перцентиль не посчитан ни у одного события")
    return {"n": len(ps), "mean": float(np.mean(ps)),
            "med": float(np.median(ps))}


# --- K3: плацебо меток ------------------------------------------------

def placebo_shares(ev_med, pool_vals, n, seeds=SEEDS, rng_seed=RNG_SEED):
    """Метка события, поставленная случайным начислениям тех же имён.

    Возвращает p95 медиан плацебо и долю зёрен, где плацебо не хуже.
    """
    v = _finite(pool_vals)
    if len(v) < n or n <= 0:
        raise Empty("пул плацебо меньше числа событий")
    rng = np.random.default_rng(rng_seed)
    a = np.asarray(v, dtype=float)
    meds = [float(np.median(rng.choice(a, size=n, replace=False)))
            for _ in range(seeds)]
    m = np.asarray(meds)
    return {"n": n, "pool": len(v), "seeds": seeds, "ev_med": float(ev_med),
            "p95": float(np.percentile(m, 95)), "med": float(np.median(m)),
            "share": float((m >= ev_med).mean())}


def k3(sh):
    """Мертва, если медиана события НЕ ВЫШЕ p95 плацебо-медиан."""
    if sh is None:
        return {"ok": None, "say": "плацебо не измерено"}
    dead = sh["ev_med"] <= sh["p95"]
    return {"ok": not dead, "say": (
        f"медиана события {sh['ev_med']:+.2f} $ против p95 плацебо "
        f"{sh['p95']:+.2f} $ на {sh['seeds']} зёрнах"
        + (" — выше, метка значит что-то" if not dead
           else " — МЕРТВА: метка «< −1 %» не отличима от случайной"))}


# --- K2: ликвидность --------------------------------------------------

def k2(rows, field="walk_bp"):
    """Реплей проходом по лесенке. Мертва, если медиана взятия нетто ≤ 0
    либо медиана дня < 0.

    Событие, у которого лесенки записи не хватило на билет, в медиану не
    входит и считается ОТДЕЛЬНО: цена за пределами записи неизвестна, и
    прочерк здесь честнее нуля.
    """
    got = [r for r in rows if r.get("used")]
    have = [r for r in got if r.get(field) is not None]
    if not have:
        return {"ok": None, "n": 0, "thin": len(got),
                "say": "проход по лесенке не посчитан ни у одного события"}
    med = float(np.median([r[field] for r in have]))
    f = form(have, field)
    med_day = f["st"]["med"]
    dead = (med <= 0) or (med_day < 0)
    return {"ok": not dead, "n": len(have), "thin": len(got) - len(have),
            "med_bp": med, "med_day": med_day,
            "tot": f["tot"], "form": f,
            "say": (f"медиана взятия по лесенке {med:+.1f} б.п., медиана "
                    f"дня {med_day:+.2f} $, лесенки не хватило у "
                    f"{len(got) - len(have)} событий из {len(got)}"
                    + (" — жива" if not dead else
                       " — МЕРТВА: проход по записанному стакану съедает "
                       "взятие"))}


# --- K4: вперёд, правилом пула ----------------------------------------

def forward_day(day=FORWARD_FROM):
    """Номер суток, с которых начинается форвард."""
    return int(np.datetime64(day + "T00:00:00", "ms").astype("int64")) // MS_D


def k4(rows, field="flat_bp", from_day=None, min_events=K4_MIN_EVENTS,
       top=TOP_DAYS):
    """Суд вперёд правилом пула. До календаря вердикта НЕТ ВОВСЕ.

    Правило не переписано, а вызвано: `pool.shape_why` — то же, которым
    судят кандидатов пула (медиана дня ≥ 0, укус ≤ 10). Сверх него
    заявка объявила третью границу: сумма нетто без трёх лучших дней
    должна остаться положительной.
    """
    d0 = forward_day() if from_day is None else from_day
    fwd = [r for r in rows if r.get("used") and day_no(r["ts"]) >= d0]
    daily = daily_usd(fwd, field)
    n_days = len(daily)
    if len(fwd) < min_events or n_days < SB.MIN_DAYS:
        return {"ok": None, "events": len(fwd), "days": n_days,
                "say": (f"вперёд {len(fwd)} событий на {n_days} сутках — "
                        f"вердикта нет: нужно {min_events} событий и "
                        f"{SB.MIN_DAYS} суток")}
    why = PL.shape_why(daily, d0 * MS_D / MS_S)
    wt = without_top_days(daily, top)
    if why is None and wt <= 0:
        why = (f"без {top} лучших дней остаётся {wt:+.2f} $: ожидание "
               "живёт в эпизоде, а не в обычном дне")
    return {"ok": why is None, "events": len(fwd), "days": n_days,
            "without_top": wt, "why": why,
            "say": (f"вперёд {len(fwd)} событий на {n_days} сутках; "
                    + ("форма выдержала правило пула, без "
                       f"{top} лучших дней {wt:+.2f} $"
                       if why is None else f"МЕРТВА: {why}"))}


# --- общий вердикт ----------------------------------------------------

KILLERS = ("K0", "K1", "K2", "K3", "K4")


def verdict(res):
    """Порядок обязателен, сработавший убийца закрывает.

    Три исхода, и «не измерено» среди них отдельный: убийца, которого
    нечем посчитать, не есть пройденный убийца. Фраза выводится из
    состояния, а не хранится рядом с ним.
    """
    for k in KILLERS:
        r = res.get(k) or {}
        if r.get("ok") is False:
            return {"alive": False, "at": k,
                    "say": f"{k} закрыл механику: {r.get('say')}"}
    for k in KILLERS:
        r = res.get(k) or {}
        if r.get("ok") is None:
            return {"alive": None, "at": k,
                    "say": f"{k} не измерен: {r.get('say')}"}
    return {"alive": True, "at": None,
            "say": "ни один объявленный убийца не сработал: "
                   + "; ".join(f"{k} — {(res.get(k) or {}).get('say')}"
                               for k in KILLERS)}
