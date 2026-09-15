#!/usr/bin/env python3
"""Забор не ближе вчерашнего размаха: пол запаса коротких книг `h24`.

Механика `dc3b6317` (заявка предлагающего 2026-09-15). Утверждение одно:

    запас забора = max(запас линейки, размах имени за 24 ч до входа)

то есть расстояние «вход → ликвидация» у позиции не вправе быть меньше
того, что имя УЖЕ прошло за сутки перед входом. Размах — та самая
величина `rng`, которую `run_d3.window_stats` считает рядом с σ и
которую забор сегодня выбрасывает.

ОТКУДА ЗАЯВКА. Безопасная линейка коротких книг выдаёт плечо от σ окна
записи (запас 6 суточных σ, `run_d5.fence_leverage`), и потолок 25×
позиция получает, только когда 6σ укладываются примерно в 3.5 % цены,
то есть при суточной σ ≤ 0.6 %. Портрет хвоста тех же книг печатает у
этой полосы медианный размах суток ПЕРЕД входом 1403–1972 б.п. Два
наших числа противоречат друг другу: у случайного блуждания размах
суток около 1.6 σ, и 14–20 % размаха отвечают σ около 9 %, а не 0.6 %.
Одно из двух неверно, и в полосе 25× живёт 71 % денег книги.

ЧТО ЗДЕСЬ ПОСТРОЕНО. Шаги идут в объявленном заданием порядке, и
следующий читается только после предыдущего:

    0. разрешение противоречия — σ, которую видел забор, размах того же
       окна, их отношение, число баров и доля минут без движения, кто
       связал плечо; по полосам плеча. Вердикта не выносит, но без него
       заявку нельзя читать;
    1. инертность — пол связывает меньше 5 % позиций либо у полосы 25×
       после пола плечо всё ещё ≥ 15×: судить нечего;
    2. потолок с идеальным знанием будущего — запас каждой позиции равен
       её РЕАЛИЗОВАННОМУ неблагоприятному ходу: верхняя граница любой
       переменной забора;
    3. равномерный контроль — то же среднее плечо, полученное одним
       множителем и отдельно одним плоским потолком;
    4. случайная выборка того же размера — тот же мультимножество
       множителей плеча, назначенное случайным позициям, 200 зёрен;
    5. форма на записи — «без 3 лучших дней», медиана дня, укус;
    6. форвард — правило вылета пула (`factory/pool.shape_why`); здесь
       считается по ПЕРЕСЧЁТУ и вердикта не несёт, о чём сказано вслух.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Второй копии расчётного ядра: плечо выводит
`ladder.max_leverage`, исход считает `ladder.simulate_dca`, позицию
собирает `run_d10.one_position`, правила книги применяет `run_paper`
(возраст → охрана рынком → касса), деньги нетто — `costs.apply_to_rows`,
форму — `factory/stability.stats`. Пол входит в счёт ПЕРЕХВАТОМ этих же
функций (`bound`), а не переписыванием: перехват ставит другое ПЛЕЧО и
возвращает всё на место, а числа считает ядро.

Живого кэша реплея (`dca_paper/cache/recs-short.jsonl`) замер не
трогает ни при каком исходе: свой кэш он не ведёт вовсе, а считает оба
прохода на месте. Правил книг не меняет — они остаются версии `RULES`.

Множитель размаха объявлен ЗДЕСЬ, до прогона, и равен 1.0: это не
сетка, а тождество «один вчерашний размах». 0.5 и 2.0 печатаются
диагностикой и вердикта не получают.

ТРАКТОВОК У ЗАЯВКИ ДВЕ, и выбор между ними не за замером. Задание
говорит «пол как параметр `fence_leverage`» — то есть на ПОЛНОСТЬЮ
НАБРАННОЙ лестнице, как забор считает сегодня (`fence`, умолчание).
Сама заявка говорит «расстояние вход → ликвидация у КАЖДОЙ позиции», а
книга `h24` торгует ячейку `fence:none:t2` и доливов не делает вовсе —
лестница не набирается никогда (`flat`). Числа расходятся не на
проценты: у неполной лестницы (рунгов 2 из 4, Σ весов 0.5) забор
считает себе запас 107 %, а у позиции без доливов на том же плече он
2 % — измерено смоуком 15.09, см. `RUNBOOK.md`. Обе считаются каждым
прогоном; вердикт несёт ОБЪЯВЛЕННАЯ ключом `--verdict`, вторая идёт
диагностикой: выбрать её после просмотра чисел — ошибка R5.

Прогон: `run research/mech_dc3b6317/fence_floor.py`. Смоук: `--limit 200`.
Публикует отчёт сам; `--no-publish` выключает.
"""
import argparse
import calendar
import contextlib
import inspect
import json
import os
import random
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d3 as D3                                           # noqa: E402
import run_d5 as D5                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import run_d10 as D10                                         # noqa: E402
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import arm_book as AB                                         # noqa: E402
import costs as CO                                            # noqa: E402
import tail as TL                                             # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import stability as SB                                        # noqa: E402
import pool as PL                                             # noqa: E402


def _by_path(name, rel, need):
    """Модуль по ПУТИ, а не по имени: одноимённые файлы в проекте есть.

    `ceiling.py` живёт и в фабрике, и в `t4_structure`, и обычный
    `import` берёт тот, чей каталог попал в `sys.path` раньше, — то
    есть чужой, молча. Поймано на первом же прогоне: связь книг
    считалась бы не тем модулем (а точнее — падала бы в самом конце,
    после всего счёта). Наличие нужного имени проверяется здесь же,
    чтобы отказ случился при ввозе, а не через час.
    """
    import importlib.util
    path = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, need):
        raise ImportError(f"{rel}: нет {need} — это не тот модуль")
    return mod


CE = _by_path("factory_ceiling", "research/factory/ceiling.py", "pair_corr")

OUT = os.path.join(HERE, "out")
ART = "FLOOR-range"
HOUR = 3600.0

# --- объявлено ДО прогона --------------------------------------------
#
# Все пороги ниже взяты из задания и заявки (`out/build_task.md`,
# `out/proposal.md`), а не назначены здесь: порог, назначенный тем же,
# кто его проверяет, слабее назначенного независимо.

RANGE_MULT = 1.0             # тождество «один вчерашний размах» — вердикт
DIAG_MULTS = (0.5, 2.0)      # только диагностика, не выбираются
HONEST_RATIO = 3.0           # размах/σ_сут ≤ — σ честна, дефекта меры нет
DEFECT_RATIO = 10.0          # ≥ — σ забора есть дефект меры (роль fix)
BROWN_RATIO = 1.6            # размах/σ_сут у случайного блуждания
INERT_SHARE = 0.05           # пол связал меньше — судить нечего
INERT_LEV = 15.0             # плечо полосы 25× после пола ≥ — судить нечего
CLAIM_SHARE = 0.15           # заявка: пол трогает не более 15 % позиций
CLAIM_TAIL = 0.04            # заявка: хвост тронутых падает до уровня 1–5×
SEED_KILL = 0.10             # случайная не хуже в ≥ — механика мертва
SEEDS = 200                  # зёрна НОМЕРАМИ: 0 … 199
BASE_WO3D_SHARE = 0.52       # 1623.72 / 3109.94 у базы (DCA-short.md)
ORACLE_EPS_BP = 1.0          # «плюс шаг цены» у потолка: 1 б.п. запаса

# Ячейка вердикта одна и названа заданием.
VERDICT_BOOK = "safe_h"
VERDICT_DEP = 10000.0
# ДВЕ ТРАКТОВКИ заявки, и выбор между ними — не за строителем.
# `fence` — буквально по заданию: пол как параметр `fence_leverage`, то
# есть на полностью НАБРАННОЙ лестнице. `flat` — по словам самой заявки
# («расстояние вход → ликвидация у КАЖДОЙ позиции»): на той позиции,
# которой книга торгует, а торгует она ячейку без доливов. Вердикт
# несёт объявленная прогоном (`--verdict`, умолчание — задание),
# вторая считается рядом и печатается диагностикой.
FLOOR_VARIANTS = {"fence": ("floor", "пол на лестнице забора (по заданию)"),
                  "flat": ("floor_flat",
                           "пол на позиции без доливов (по словам заявки)")}
VERDICT_VARIANT = "fence"


def after_of(row, variant=VERDICT_VARIANT):
    """Плечо после пола в объявленной трактовке."""
    return row["lev_after_flat"] if variant == "flat" else row["lev_after"]


def moved_of(row, variant=VERDICT_VARIANT):
    """Связал ли пол эту позицию в объявленной трактовке."""
    return bool(row["moved_flat"] if variant == "flat" else row["moved"])
# Дни, которые задание требует отдельными строками.
DAYS_NAMED = ("2026-08-13", "2026-09-12", "2026-09-13")
# Ячейка D10, которой торгует семейство: плечо забора, без доливов,
# цель ×2. Берётся у самого прогона книг, а не повторяется строкой.
CELL = S.CELL
CELL_KEY = CELL[0]
SIDE = "short"

BANDS = (("1x", "ровно 1×"), ("1-5", "1–5×"), ("5-15", "5–15×"),
         ("15-25", "15–25×"), ("25x", "ровно 25×"))
BAND_TITLE = dict(BANDS)
# Потолок плеча берётся У САМОГО ЯДРА (умолчание `ladder.max_leverage`),
# а не повторяется числом: полоса «ровно 25×» есть полоса «упёрлись в
# потолок», и разойдись эти два числа, полоса описывала бы не то.
LEV_CAP = float(inspect.signature(L.max_leverage)
                .parameters["lev_cap"].default)


def band_of(lev):
    """Полоса плеча — те же пять, которыми заявка читает книгу."""
    v = float(lev)
    if v <= 1.0 + 1e-9:
        return "1x"
    if v >= LEV_CAP - 1e-9:
        return "25x"
    if v < 5.0:
        return "1-5"
    if v < 15.0:
        return "5-15"
    return "15-25"


def ruler_of(rule, param):
    """Линейка книги по паре (правило, параметр) — картой САМОГО замера
    D10, а не своим списком: разойдись они, диагностика подписывала бы
    строки чужой линейкой."""
    for rk, pr in D10.RULERS.items():
        if pr == (rule, param):
            return rk
    return None


# --- правило: пол запаса из размаха -----------------------------------

def range_frac(rng_bp, mult=RANGE_MULT):
    """Пол запаса ДОЛЕЙ ЦЕНЫ из размаха в б.п. Нет меры — None.

    `window_stats` отдаёт размах в базисных пунктах (сотых долях
    процента), а забор считает запас долей цены: ошибка единиц ловилась
    в проекте пять раз, поэтому перевод стоит одним местом и закреплён
    тестом с литералом (1000 б.п. = 0.10 цены).

    Размах, которого НЕТ (окно короче десяти баров, цены нулевые), —
    прочерк, а не ноль: ноль здесь означал бы «имя не двигалось», то
    есть ровно ту подмену, против которой заявка.
    """
    if rng_bp is None:
        return None
    v = float(rng_bp)
    if v != v or v <= 0:
        return None
    return v / 1e4 * float(mult)


def depth_frac(entry, rungs_full):
    """Глубина лестницы долей цены — ТЕМ ЖЕ выражением, что у забора.

    `run_d5.fence_leverage` считает `d_max = |вход − последний рунг| /
    вход` и через него переводит требуемый запас в множитель. Здесь
    нужно то же самое число, и равенство закреплено тестом: пол,
    выставленный ровно в `param · d_max`, обязан дать линейке `depth`
    ТО ЖЕ плечо бит в бит (`test_floor_equals_the_depth_ruler`).
    """
    if len(rungs_full) < 2:
        return None
    d = abs(float(entry) - float(rungs_full[-1])) / float(entry)
    return d if d > 0 else None


def floor_leverage(entry, rungs_full, look, rng_bp, mult=RANGE_MULT,
                   side=SIDE, lev_look=None, weights=None):
    """Плечо, при котором запас равен ровно размаху. (плечо, почему).

    Считает ОДНА `ladder.max_leverage` — та же, что у забора; меняется
    ровно требуемый запас, выраженный в её множителе (`запас / d_max`).
    Второй копии вывода плеча здесь нет.

    `None` с причиной вместо числа: размах не измерен; лестницы нет
    (тогда плечо и так 1×); забор отказывает лестнице даже без плеча.
    """
    rf = range_frac(rng_bp, mult)
    if rf is None:
        return None, "размах не измерен"
    d_max = depth_frac(entry, rungs_full)
    if d_max is None:
        return None, "нет лестницы"
    w = (list(weights) if weights is not None
         else D2.WEIGHTS[:len(rungs_full)])
    lev = L.max_leverage(rungs_full, w, 1.0, entry, d_max, look,
                         rf / d_max, side=side, lev_lookup=lev_look)
    if lev <= 0:
        return None, "пол недостижим"
    return float(lev), "пол"


def under_floor(lev_ruler, lev_floor):
    """Плечо под полом и кто его связал.

    Тождество «запас = max(запас линейки, размах)» здесь выражено как
    `min(плечо линейки, плечо пола)`: плечо `max_leverage` не растёт с
    ростом требуемого запаса, поэтому минимум двух плеч РАВЕН плечу,
    посчитанному по большему из двух запасов. Равенство проверяется
    тестом на самих числах, а не подразумевается.
    """
    if lev_floor is None:
        return float(lev_ruler), "линейка"
    if float(lev_floor) < float(lev_ruler) - 1e-9:
        return float(lev_floor), "пол"
    return float(lev_ruler), "линейка"


def flat_floor_leverage(entry, look, rng_bp, mult=RANGE_MULT, side=SIDE,
                        cap=None):
    """Пол на ТОЙ позиции, которой книга торгует: один вход, без доливов.

    ВТОРАЯ ТРАКТОВКА заявки, и она названа вслух, а не выбрана молча.
    Задание говорит «пол как параметр `fence_leverage`», и `floor_leverage`
    выше считает его на ПОЛНОСТЬЮ НАБРАННОЙ лестнице — так забор считает
    сегодня. Но семейство `h24` торгует ячейку `fence:none:t2`, то есть
    доливов не делает ВОВСЕ: лестница остаётся из одного входа, и
    расстояние «вход → ликвидация» у неё совсем другое (при 25× оно
    2 %, а не 106 %, — измерено, см. отчёт). Заявка же говорит про
    «расстояние вход → ликвидация у КАЖДОЙ позиции».

    Обе трактовки посчитаны, вердикт несёт объявленная прогоном
    (`--verdict`), вторая печатается диагностикой. Выбирать за
    предлагающего строитель не вправе.

    Плечо ищется двоичным поиском по той же паре функций ядра
    (`fully_loaded` → `liq_price`), что стоит внутри `max_leverage`:
    запас монотонно убывает с плечом, второй копии формулы нет.
    """
    rf = range_frac(rng_bp, mult)
    if rf is None:
        return None, "размах не измерен"
    top = float(cap if cap is not None else LEV_CAP)

    def gap(lv):
        return liq_gap(entry, [float(entry)], lv, look, side, weights=[1.0])

    if gap(top) >= rf:
        return top, "пол"
    if gap(1.0) < rf:
        return None, "пол недостижим"
    lo, hi = 1.0, top
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if gap(mid) >= rf:
            lo = mid
        else:
            hi = mid
    return lo, "пол"


def liq_gap(entry, rungs_full, lev, look, side=SIDE, weights=None):
    """Расстояние «вход → ликвидация» долей цены, ядром лестницы.

    Нужно для проверки самого тождества заявки: после пола этот запас
    обязан быть не меньше размаха (либо плечо равно 1× и пол недостижим
    — и это названо отдельно). Считается на ПОЛНОСТЬЮ набранной
    лестнице, то есть ровно так, как его считает забор.
    """
    w = (list(weights) if weights is not None
         else D2.WEIGHTS[:len(rungs_full)])
    qty, p_avg, notl = L.fully_loaded(rungs_full, w, 1.0, float(lev))
    p_liq = L.liq_price(p_avg, qty, 1.0, look(notl), side)
    return abs(float(p_liq) - float(entry)) / float(entry)


def oracle_frac(adv_frac, floor_frac, eps_bp=ORACLE_EPS_BP):
    """Запас потолка с идеальным знанием будущего, долей цены.

    Потолок обязан не доходить НИ ДО ПОЛА КАПИТУЛЯЦИИ, ни до ликвидации.
    Пол стоит на доле `floor_frac` расстояния «вход → ликвидация» от
    самой ликвидации (`ladder.simulate_dca`), то есть срабатывает,
    когда цена прошла против позиции `(1 − floor_frac)` этого
    расстояния. Значит запас обязан быть больше реализованного
    неблагоприятного хода, делённого на `(1 − floor_frac)`; шаг цены
    добавлен, чтобы неравенство было строгим.
    """
    a = float(adv_frac)
    if a != a or a < 0:
        return None
    f = float(floor_frac or 0.0)
    if not 0.0 <= f < 1.0:
        raise ValueError(f"доля пола капитуляции вне [0,1): {f}")
    return (a + float(eps_bp) / 1e4) / (1.0 - f)


# --- диагностика окна --------------------------------------------------

def seg_closes(win, now_i):
    """Закрытия окна ДО входа — ТЕМ ЖЕ отрезком, что `window_stats`.

    Отрезок один: `win[:now_i + 1]`, цены больше нуля, не меньше десяти
    точек. Совпадение с самой `window_stats` закреплено тестом (σ по
    этому отрезку обязана равняться её σ бит в бит) — разойдись они,
    доля замороженных минут описывала бы другое окно, чем σ.
    """
    seg = win[:now_i + 1]
    if len(seg) < 10:
        return None
    cl = np.array([b[4] for b in seg], dtype="float64")
    cl = cl[cl > 0]
    return cl if len(cl) >= 10 else None


def flat_share(win, now_i):
    """Доля минут БЕЗ движения цены в окне до входа. Нет окна — None.

    Это и есть подпись замороженного ряда: σ такого окна близка к нулю
    не потому, что имя спокойно, а потому, что котировка не менялась.
    """
    cl = seg_closes(win, now_i)
    if cl is None or len(cl) < 3:
        return None
    r = np.diff(np.log(cl))
    if not len(r):
        return None
    return float(np.mean(r == 0.0))


def adverse_frac(win, now_i, side=SIDE):
    """Реализованный ход ПРОТИВ позиции за удержание, долей цены.

    ЗАГЛЯДЫВАЕТ В БУДУЩЕЕ намеренно и только для потолка с идеальным
    знанием: `win[now_i:]` — это бары удержания, то есть то, чего в
    момент решения не видно. Считается лишь тогда, когда прогон прямо
    попросил потолок (`Bench.oracle`), чтобы правило пола не могло
    коснуться будущего даже случайно.
    """
    hold = win[now_i:]
    if not hold:
        return None
    entry = float(hold[0][1])
    if entry <= 0:
        return None
    adv = (max(float(b[2]) for b in hold) if side == SIDE
           else min(float(b[3]) for b in hold))
    return abs(adv - entry) / entry


# --- перехват реплея ---------------------------------------------------

class Stale(RuntimeError):
    """Забор спросили о ЧУЖОМ окне: пол считать не из чего.

    Размах приходит к забору от того же прохода, что и σ (ядро их
    считает одной функцией и σ передаёт дальше, а размах выбрасывает).
    Подстраховка на случай, если дорога ядра изменится: тождество окна
    проверяется по входу и по самой σ, и несовпадение — отказ вслух, а
    не молчаливый пол от прошлой позиции.
    """


def _same(a, b):
    """Равенство чисел, где NaN равен NaN: σ бывает не измерена."""
    if a is None or b is None:
        return (a is None) and (b is None)
    a, b = float(a), float(b)
    if a != a and b != b:
        return True
    return a == b


class Bench:
    """Перехват дороги реплея: то же ядро, другое ПЛЕЧО.

    Три функции ядра подменяются на время прохода и возвращаются на
    место (`bound`): `run_d3.window_stats` — чтобы запомнить размах
    окна, который ядро считает и выбрасывает; `run_d5.fence_leverage` —
    чтобы поставить плечо варианта; `run_d10.one_position` — чтобы
    узнать, ЧЬЯ сейчас позиция, и посчитать её несколько раз подряд на
    одних барах (варианты и зёрна читают бары один раз, а не по разу на
    вариант).

    Сами числа считает ядро: перехват не умеет ни симулировать, ни
    выводить плечо.
    """

    def __init__(self, plan=None, oracle=False, mults=(RANGE_MULT,),
                 rulers=None, log=None):
        self.plan = plan            # ключ → [(вариант, правило плеча)]
        self.oracle = bool(oracle)
        self.mults = tuple(mults)
        # Линейки, которые считает ЭТОТ проход. Ядро считает обе всегда
        # (`run_d10.RULERS`), и без этого списка чужая линейка попадала
        # бы в счётчик «вне плана» три тысячи раз подряд — число,
        # которое кричит всегда, перестаёт быть сигналом.
        self.rulers = (set(rulers) if rulers is not None
                       else set(D10.RULERS))
        self.log = log or (lambda *a: None)
        self.rows = {}              # ключ → диагностика окна и плеча
        self.recs = {}              # вариант → линейка → ключ → запись
        self.seeds = {}             # ключ → множитель → запись
        self.no_plan = 0            # позиций, которых не было в проходе A
        self.cur = None

    # -- подмены

    def _window_stats(self, orig):
        def wrap(win, now_i):
            got = orig(win, now_i)
            b = self.cur
            if b is not None and 0 <= now_i < len(win):
                b["sigma_bp"] = got[0]
                b["rng_bp"] = got[1]
                b["entry"] = float(win[now_i][1])
                b["n_bars"] = int(min(now_i + 1, len(win)))
                b["flat"] = flat_share(win, now_i)
                if self.oracle:
                    b["adv"] = adverse_frac(win, now_i, SIDE)
            return got
        return wrap

    def _fence(self, orig):
        def wrap(rule, param, entry, rungs_full, look, sigma_bp,
                 weights=None, side="long", lev_look=None):
            lev0, rungs0, binder = orig(rule, param, entry, rungs_full,
                                        look, sigma_bp, weights=weights,
                                        side=side, lev_look=lev_look)
            b = self.cur
            if b is None:
                return lev0, rungs0, binder
            b["calls"] = b.get("calls", 0) + 1
            if b["calls"] > 1:
                # второй забор одной позиции — σ-лестница ячейки, которой
                # семейство не торгует: пол стоит на СТРУКТУРНОЙ
                return lev0, rungs0, binder
            if not _same(b.get("entry"), entry) or \
                    not _same(b.get("sigma_bp"), sigma_bp):
                raise Stale(
                    f"забор спросили о чужом окне: вход {entry!r} против "
                    f"{b.get('entry')!r}, σ {sigma_bp!r} против "
                    f"{b.get('sigma_bp')!r}")
            b["lev_base"] = float(lev0)
            b["binder"] = binder
            b["d_max"] = depth_frac(entry, rungs_full)
            w = (list(weights) if weights is not None
                 else D2.WEIGHTS[:len(rungs_full)])
            b["n_rungs"] = len(rungs_full)
            b["w_sum"] = float(sum(w))
            # Чем ЗАБОР считает позицию: средняя цена и запас до
            # ликвидации полностью НАБРАННОЙ лестницы. У семейства без
            # доливов лестница не набирается никогда, и эти два числа
            # говорят, насколько то, что забор считает, отличается от
            # того, чем книга торгует.
            try:
                _q, p_avg, _n = L.fully_loaded(rungs_full, w, 1.0,
                                               float(lev0))
                b["avg_ratio"] = float(p_avg) / float(entry)
                b["gap"] = liq_gap(entry, rungs_full, lev0, look, side,
                                   weights=w)
                b["gap_flat"] = liq_gap(entry, [float(entry)], lev0, look,
                                        side, weights=[1.0])
            except (ValueError, ZeroDivisionError):
                b["avg_ratio"] = b["gap"] = b["gap_flat"] = None
            spec = b.get("spec") or {"kind": "base"}
            need = set(self.mults)
            if spec.get("kind") in ("floor", "floor_flat"):
                need.add(float(spec.get("mult") or RANGE_MULT))
            for m in sorted(need):
                lv, why = floor_leverage(entry, rungs_full, look,
                                         b.get("rng_bp"), mult=m, side=side,
                                         lev_look=lev_look)
                b.setdefault("lev_floor", {})[m] = lv
                b.setdefault("floor_why", {})[m] = why
                lf, wf = flat_floor_leverage(entry, look, b.get("rng_bp"),
                                             mult=m, side=side)
                b.setdefault("lev_flat", {})[m] = lf
                b.setdefault("flat_why", {})[m] = wf
            lev = self._resolve(spec, b, entry, rungs_full, look, side,
                                lev_look)
            b["lev_used"] = float(lev)
            if abs(float(lev) - float(lev0)) > 1e-12:
                b["moved"] = True
            return float(lev), rungs0, binder
        return wrap

    def _resolve(self, spec, b, entry, rungs_full, look, side, lev_look):
        """Плечо варианта. Умолчание — плечо самого забора."""
        kind = spec.get("kind")
        lev0 = float(b["lev_base"])
        if kind in (None, "base"):
            return lev0
        if kind == "floor":
            m = float(spec.get("mult") or RANGE_MULT)
            lev, _w = under_floor(lev0, (b.get("lev_floor") or {}).get(m))
            return lev
        if kind == "floor_flat":
            m = float(spec.get("mult") or RANGE_MULT)
            lev, _w = under_floor(lev0, (b.get("lev_flat") or {}).get(m))
            return lev
        if kind == "scale":
            v = float(spec["v"])
            if v > 1.0 + 1e-12:
                raise ValueError(f"равномерный контроль УМЕНЬШАЕТ плечо, "
                                 f"а множитель {v:g} больше единицы")
            return max(1.0, lev0 * v)
        if kind == "cap":
            return max(1.0, min(lev0, float(spec["v"])))
        if kind == "oracle":
            adv = b.get("adv")
            if adv is None:
                return lev0
            rf = oracle_frac(adv, D2.FLOOR_FRAC)
            d_max = depth_frac(entry, rungs_full)
            if rf is None or d_max is None:
                return lev0
            lev = L.max_leverage(rungs_full,
                                 D2.WEIGHTS[:len(rungs_full)], 1.0, entry,
                                 d_max, look, rf / d_max, side=side,
                                 lev_lookup=lev_look)
            return float(lev) if lev > 0 else 1.0
        raise ValueError(f"неизвестное правило плеча: {kind!r}")

    def _one_position(self, orig):
        def wrap(g, bars, ts, look, rule, param, lev_look=None, cells=None,
                 rich=False, checkpoints=None):
            rk = ruler_of(rule, param)
            key = (rk, g["sym"], round(float(g["at"]), 3))
            if rk not in self.rulers:       # чужая линейка — считает ядро
                self.cur = None
                return orig(g, bars, ts, look, rule, param,
                            lev_look=lev_look, cells=cells, rich=rich,
                            checkpoints=checkpoints)
            specs = (list(self.plan.get(key) or []) if self.plan is not None
                     else [("base", {"kind": "base"})])
            if self.plan is not None and not specs:
                self.no_plan += 1
                specs = [("base", {"kind": "base"})]
            base = None
            for name, spec in specs:
                self.cur = {"calls": 0, "spec": spec}
                try:
                    out = orig(g, bars, ts, look, rule, param,
                               lev_look=lev_look, cells=cells, rich=rich,
                               checkpoints=checkpoints)
                finally:
                    b, self.cur = self.cur, None
                if name == "base":
                    base = out
                    self._note(key, b)
                rec = (out or {}).get(CELL_KEY)
                if rec is None:
                    continue
                if name == "seed":
                    self.seeds.setdefault(key, {})[float(spec["v"])] = rec
                else:
                    self.recs.setdefault(name, {}).setdefault(
                        rk, {})[key] = rec
            return base
        return wrap

    def _note(self, key, b):
        """Строка диагностики позиции. Забора не было — считать нечем."""
        if not b or "lev_base" not in b:
            return
        sd = D5.sigma_day(b.get("sigma_bp"))
        rf = range_frac(b.get("rng_bp"), 1.0)
        lev0 = float(b["lev_base"])
        row = {"ruler": key[0], "sym": key[1], "at": key[2],
               "sigma_bp": _num(b.get("sigma_bp")),
               "sigma_day": sd, "rng": rf,
               "ratio": (None if not sd or rf is None or sd <= 0
                         else rf / sd),
               "n_bars": b.get("n_bars"), "flat": b.get("flat"),
               "binder": b.get("binder"), "lev": lev0,
               "band": band_of(lev0), "d_max": b.get("d_max"),
               "adv": b.get("adv"), "n_rungs": b.get("n_rungs"),
               "w_sum": b.get("w_sum"), "avg_ratio": b.get("avg_ratio"),
               "gap": b.get("gap"), "gap_flat": b.get("gap_flat"),
               "lev_floor": {str(m): v for m, v
                             in (b.get("lev_floor") or {}).items()},
               "floor_why": {str(m): w for m, w
                             in (b.get("floor_why") or {}).items()},
               "lev_flat": {str(m): v for m, v
                            in (b.get("lev_flat") or {}).items()},
               "flat_why": {str(m): w for m, w
                            in (b.get("flat_why") or {}).items()}}
        # Обе трактовки считаются всегда; какая несёт вердикт — объявляет
        # прогон (`--verdict`), а не строка кода, увидевшая числа.
        lv, who = under_floor(lev0, (b.get("lev_floor") or {}).get(RANGE_MULT))
        row["lev_after"], row["bound"] = lv, who
        row["moved"] = bool(who == "пол")
        lv2, who2 = under_floor(lev0,
                                (b.get("lev_flat") or {}).get(RANGE_MULT))
        row["lev_after_flat"], row["bound_flat"] = lv2, who2
        row["moved_flat"] = bool(who2 == "пол")
        self.rows[key] = row


def _num(x):
    """Число или прочерк: NaN — это «не измерено», а не значение."""
    if x is None:
        return None
    v = float(x)
    return None if v != v else v


@contextlib.contextmanager
def bound(bench):
    """Перехват на время прохода. Возврат — в любом исходе.

    Оставленная подмена сделала бы СОСЕДНИЙ прогон другим замером молча
    — тем же классом, что глобально оставленный срок удержания
    (`run_d11.configure`).
    """
    ws, fl, op = D3.window_stats, D5.fence_leverage, D10.one_position
    D3.window_stats = bench._window_stats(ws)
    D5.fence_leverage = bench._fence(fl)
    D10.one_position = bench._one_position(op)
    try:
        yield bench
    finally:
        D3.window_stats, D5.fence_leverage, D10.one_position = ws, fl, op


# --- проходы -----------------------------------------------------------

def scan(legs_, src=None, log=print, oracle=True, mults=None, rulers=None):
    """Проход A: окно, σ, размах и плечо КАЖДОЙ позиции. Без симуляции.

    `cells=[]` — ячеек не считается ни одной, то есть ни одного вызова
    симуляции: геометрия и забор считаются всё равно (ядро зовёт их до
    цикла ячеек), а исход здесь не нужен. Это дешевле полного реплея и
    даёт ровно ту таблицу, которой в `DCA-short.md` нет.
    """
    b = Bench(plan=None, oracle=oracle, log=log, rulers=rulers,
              mults=tuple(mults if mults is not None
                          else (RANGE_MULT,) + DIAG_MULTS))
    log("проход A: ячеек ноль — исход НЕ считается вовсе, только окно и "
        "забор; строка ядра «запись доходит до …» в этом проходе "
        "бессмысленна (ей нечего мерить) и вердикта не несёт")
    with bound(b):
        G.replay(legs_, [], src=src, log=log)
    rows = list(b.rows.values())
    log(f"проход A: позиций с забором {len(rows)} из {len(legs_)} решений "
        f"× {len(D10.RULERS)} линеек")
    return rows, b


def sim(legs_, plan, src=None, log=print, oracle=True, books=None):
    """Проход B: исход позиции на плече КАЖДОГО варианта.

    Пол капитуляции у книг РАЗНЫЙ (0.10 у безопасной, 0.50 у остальных),
    а в симуляции он глобален, — поэтому проход идёт по группам пола той
    же картой, что у прогона книг (`run_short.floor_groups`), и в каждой
    группе берутся только СВОИ линейки. Один проход на все книги отдал
    бы двум из трёх чужой пол.
    """
    want = set(books or [VERDICT_BOOK])
    groups = {}
    for frac, rulers in S.floor_groups().items():
        mine = [rk for rk in rulers
                if any(S.BOOKS.get(bk) == rk for bk in want)]
        if mine:
            groups[frac] = mine
    if not groups:
        raise ValueError(f"книги {sorted(want)} не ведут ни к одной линейке")
    out, benches, data_end = {}, [], 0.0
    was = D2.FLOOR_FRAC
    try:
        for frac, rulers in sorted(groups.items()):
            D2.FLOOR_FRAC = float(frac)
            log(f"пол капитуляции {frac:g} — линейки " + ", ".join(rulers))
            b = Bench(plan=plan, oracle=oracle, log=log, rulers=rulers)
            with bound(b):
                got = G.replay(legs_, [CELL], src=src, log=log)
            data_end = max(data_end, float(got.get("data_end") or 0.0))
            benches.append((b, set(rulers)))
    finally:
        D2.FLOOR_FRAC = was
    for b, rulers in benches:
        for name, by_rk in b.recs.items():
            for rk, byk in by_rk.items():
                if rk not in rulers:
                    continue
                out.setdefault(name, {}).setdefault(rk, {}).update(byk)
    seeds = {}
    for b, rulers in benches:
        for key, bym in b.seeds.items():
            if key[0] in rulers:
                seeds.setdefault(key, {}).update(bym)
    # Состояние позиции (закрыта / открыта / оборвана записью) ставит то
    # же правило, что у прогона книг, и по ТОЙ ЖЕ границе записи.
    for byrk in out.values():
        for byk in byrk.values():
            for r in byk.values():
                r["state"] = D6.position_state(r, data_end)
    for bym in seeds.values():
        for r in bym.values():
            r["state"] = D6.position_state(r, data_end)
    no_plan = sum(bb.no_plan for bb, _r in benches)
    log(f"проход B: вариантов {sorted(out)}, зёрен-записей "
        f"{sum(len(v) for v in seeds.values())}, вне плана {no_plan}")
    return {"recs": out, "seeds": seeds, "data_end": data_end,
            "no_plan": no_plan}


# --- выбор контролей ---------------------------------------------------

def mean_lev(rows, field="lev"):
    v = [float(r[field]) for r in rows if r.get(field) is not None]
    return (sum(v) / len(v)) if v else None


def solve_scale(rows, want):
    """Множитель `k`, при котором среднее плечо равно `want`.

    Плечо не опускается ниже 1× (позиция без плеча — это позиция без
    плеча), поэтому среднее `max(1, k·плечо)` монотонно, но не линейно,
    и `k` ищется двоичным поиском, а не делением средних.
    """
    if want is None:
        return None
    lo, hi = 0.0, 1.0

    def mean_at(k):
        return sum(max(1.0, float(r["lev"]) * k) for r in rows) / len(rows)

    if not rows or mean_at(1.0) <= want + 1e-12:
        return 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if mean_at(mid) > want:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def solve_cap(rows, want):
    """Плоский потолок `c`, при котором среднее плечо равно `want`."""
    if want is None or not rows:
        return None
    lo, hi = 1.0, max(float(r["lev"]) for r in rows)

    def mean_at(c):
        return sum(max(1.0, min(float(r["lev"]), c)) for r in rows) / len(rows)

    if mean_at(hi) <= want + 1e-12:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if mean_at(mid) > want:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def seed_picks(rows, n_seeds=SEEDS, variant=VERDICT_VARIANT):
    """Случайные подмножества ТОГО ЖЕ размера с тем же мультимножеством.

    Множители берутся у самих тронутых позиций (плечо после пола делить
    на плечо до) и раздаются случайным позициям. Тянутся они из позиций
    с плечом БОЛЬШЕ 1×: на позиции, стоящей ровно на 1×, уменьшение
    плеча не делает ничего, и включив их в жеребьёвку, мы построили бы
    контроль, заведомо более слабый, чем правило. Число тех и других
    печатается, чтобы выбор был виден.
    """
    touched = [r for r in rows if moved_of(r, variant)]
    pool = [r for r in rows if float(r["lev"]) > 1.0 + 1e-9]
    mults = []
    for r in touched:
        lev, aft = float(r["lev"]), float(after_of(r, variant))
        if lev > 0:
            mults.append(min(1.0, aft / lev))
    picks = {}
    if not mults or len(pool) < len(mults):
        return picks, {"touched": len(touched), "pool": len(pool),
                       "mults": len(mults), "seeds": 0,
                       "why": ("тронутых позиций нет" if not mults else
                               "позиций с плечом > 1× меньше, чем тронутых")}
    for s in range(int(n_seeds)):
        rnd = random.Random(s)
        who = rnd.sample(pool, len(mults))
        mm = list(mults)
        rnd.shuffle(mm)
        picks[s] = {(r["ruler"], r["sym"], r["at"]): m
                    for r, m in zip(who, mm)}
    return picks, {"touched": len(touched), "pool": len(pool),
                   "mults": len(mults), "seeds": len(picks)}


def build_plan(rows, scale=None, cap=None, picks=None, oracle=True):
    """План прохода B: что считать на каждой позиции.

    Варианты объявлены здесь и одинаковы для всех позиций; зёрна
    добавляют позиции ровно те множители, которые ей выпали хотя бы в
    одном зерне (повторы считаются один раз — исход от номера зерна не
    зависит).
    """
    plan = {}
    for r in rows:
        key = (r["ruler"], r["sym"], r["at"])
        specs = [("base", {"kind": "base"}),
                 ("floor", {"kind": "floor", "mult": RANGE_MULT}),
                 ("floor_flat", {"kind": "floor_flat", "mult": RANGE_MULT})]
        if oracle:
            specs.append(("oracle", {"kind": "oracle"}))
        if scale is not None:
            specs.append(("scale", {"kind": "scale", "v": float(scale)}))
        if cap is not None:
            specs.append(("cap", {"kind": "cap", "v": float(cap)}))
        plan[key] = specs
    for _s, pick in (picks or {}).items():
        for key, m in pick.items():
            if key not in plan:
                continue
            have = {round(float(sp["v"]), 12) for nm, sp in plan[key]
                    if nm == "seed"}
            if round(float(m), 12) in have:
                continue
            plan[key].append(("seed", {"kind": "scale", "v": float(m)}))
    return plan


# --- касса и форма -----------------------------------------------------

def book_stats(by_ruler, ctx, launch, now=None, keys=None, deps=None,
               log=None):
    """Книги семейства на этих записях: правила книги, деньги НЕТТО.

    Правила и порядок — те же, что у прогона и у соседних замеров оси
    (`run_paper.age_shorts` → `guard_shorts` → `build_rows` →
    `costs.apply_to_rows` → `run_paper._stats`). Отличие от
    `short_grid.cell_stats` ровно одно: наружу отдаётся ВЕСЬ `_stats`,
    потому что колонки концентрации («без лучшего имени», «без 3 лучших
    дней», просадка без худшего дня) заказаны заданием, а та функция их
    не отдаёт. Совпадение с ней по всем общим полям закреплено тестом:
    разойдись они, замер судил бы другую книгу под тем же именем.
    """
    log = log or (lambda *a: None)
    packed = {bk: list(by_ruler.get(rk) or [])
              for bk, rk in S.BOOKS.items()}
    keys = list(keys if keys is not None else R.H24_ORDER)
    deps = list(deps if deps is not None else R.DEPOSITS)
    packed = {bk: v for bk, v in packed.items() if bk in keys}
    for bk in list(packed):
        packed[bk], _a = RP.age_shorts(packed[bk], bk, launch=launch,
                                       log=log, now=now)
        packed[bk], _g = RP.guard_shorts(packed[bk], bk, log=log, now=now)
    rows, cells_, _one, _live = RP.build_rows(packed, now=now, keys=keys,
                                              log=log)
    out = {}
    for bk in keys:
        for dep in deps:
            mine = [r for r in rows if R.ruler_of(r) == bk
                    and int(r.get("dep", 0)) == int(dep)]
            if ctx is not None and not ctx.get("error"):
                mine, _c = CO.apply_to_rows(mine, ctx)
            st = dict(RP._stats(mine, dep) or {})
            c = cells_.get(RP._cell(bk, dep)) or {}
            fin, dd = st.get("final"), st.get("max_dd")
            st.update({
                "book": bk, "dep": int(dep),
                "ratio": (None if not fin or not dd
                          else round(float(fin) / abs(float(dd)), 2)),
                "exits": _exits(mine),
                "lev_mean": (round(mean_lev(mine), 3) if mine else None),
                "lev_median": (round(float(np.median(
                    [float(r["lev"]) for r in mine])), 3) if mine else None),
                "taken": c.get("taken"), "no_cash": c.get("no_cash"),
                "open_mean": c.get("open_mean"), "open_max": c.get("open_max"),
                "fp": c.get("fp"),
                "bands": _by_band(mine)})
            out[f"{bk}:{int(dep)}"] = st
    return out


def _exits(rows):
    by = {}
    for r in rows:
        k = r.get("exit") or "—"
        d = by.setdefault(k, {"n": 0, "usd": 0.0})
        d["n"] += 1
        d["usd"] += float(r.get("usd") or 0.0)
    for d in by.values():
        d["usd"] = round(d["usd"], 2)
    return by


TAIL_EXITS = ("пол", "ликвидация")


def _by_band(rows):
    """Сделки книги по полосам плеча: доля хвостовых исходов и деньги."""
    out = {}
    for r in rows:
        b = out.setdefault(band_of(r["lev"]), {"n": 0, "tail": 0, "usd": 0.0})
        b["n"] += 1
        b["usd"] += float(r.get("usd") or 0.0)
        if (r.get("exit") or "") in TAIL_EXITS:
            b["tail"] += 1
    for b in out.values():
        b["usd"] = round(b["usd"], 2)
        b["tail_share"] = round(b["tail"] / b["n"], 4) if b["n"] else None
    return out


def daily_of(st):
    """Ряд «сутки → нетто» из разбивки книги. Нет разбивки — нет ряда."""
    return {d["d"]: float(d["usd"]) for d in (st or {}).get("days_rows") or []}


def daily_by_no(st):
    """Тот же ряд НОМЕРАМИ суток: правило вылета пула считает по ним.

    `pool.split_forward` делит ряд по номеру суток (`int(d) >= d0`), а
    книга держит дату строкой. Перевод стоит одним местом и идёт через
    `pool.day_no` — вторая арифметика суток разошлась бы с правилом.
    """
    out = {}
    for d in (st or {}).get("days_rows") or []:
        t = float(calendar.timegm(time.strptime(d["d"], "%Y-%m-%d")))
        k = PL.day_no(t)
        out[k] = out.get(k, 0.0) + float(d["usd"])
    return out


def shape_of(st):
    """Форма книги — мерой проекта (`factory/stability.stats`)."""
    return SB.stats(daily_of(st))


def wo_top3d_share(st):
    """Доля итога, остающаяся без трёх лучших суток. Нечего вычитать — None."""
    usd, wo = (st or {}).get("usd"), (st or {}).get("usd_wo_top3d")
    if usd in (None, 0) or wo is None:
        return None
    return float(wo) / float(usd)


# --- шаги и вердикты ---------------------------------------------------

def _med_mean(v):
    v = [float(x) for x in v if x is not None and float(x) == float(x)]
    if not v:
        return {"n": 0, "med": None, "mean": None}
    a = np.asarray(v, dtype=float)
    return {"n": len(v), "med": float(np.median(a)), "mean": float(np.mean(a))}


def bands_table(rows, variant=VERDICT_VARIANT):
    """Шаг 0: σ забора против размаха, по полосам плеча.

    Медиана и среднее печатаются РЯДОМ везде: расхождение знака между
    ними есть подпись короткой волатильности, и одной из двух величин
    таблица врала бы.
    """
    out = {}
    for bk, _t in BANDS:
        mine = [r for r in rows if r["band"] == bk]
        binders = {}
        for r in mine:
            binders[r.get("binder") or "—"] = \
                binders.get(r.get("binder") or "—", 0) + 1
        moved = [r for r in mine if moved_of(r, variant)]
        out[bk] = {
            "n": len(mine),
            "sigma_day": _med_mean([r.get("sigma_day") for r in mine]),
            "rng": _med_mean([r.get("rng") for r in mine]),
            "ratio": _med_mean([r.get("ratio") for r in mine]),
            "n_bars": _med_mean([r.get("n_bars") for r in mine]),
            "flat": _med_mean([r.get("flat") for r in mine]),
            # чем ЗАБОР считает позицию против того, чем её торгуют
            "n_rungs": _med_mean([r.get("n_rungs") for r in mine]),
            "w_sum": _med_mean([r.get("w_sum") for r in mine]),
            "avg_ratio": _med_mean([r.get("avg_ratio") for r in mine]),
            "gap": _med_mean([r.get("gap") for r in mine]),
            "gap_flat": _med_mean([r.get("gap_flat") for r in mine]),
            "binders": binders,
            "moved": len(moved),
            "moved_share": (round(len(moved) / len(mine), 4) if mine
                            else None),
            "lev": _med_mean([r.get("lev") for r in mine]),
            "lev_after": _med_mean([after_of(r, variant) for r in mine]),
            "lev_after_fence": _med_mean([r.get("lev_after") for r in mine]),
            "lev_after_flat": _med_mean([r.get("lev_after_flat")
                                         for r in mine]),
            "no_measure": sum(1 for r in mine if r.get("ratio") is None)}
    return out


def partial_note(rows, band="25x"):
    """Чем забор СЧИТАЕТ позицию полосы — и чем её торгуют. Из чисел.

    Третье объяснение полосы 25×, которого заявка не называла: забор
    выводит плечо из ликвидации ПОЛНОСТЬЮ НАБРАННОЙ лестницы, а
    семейство `h24` торгует ячейку без доливов и не набирает её никогда.
    У неполной лестницы (рунгов меньше четырёх) сумма весов меньше
    единицы, средняя цена набранной лестницы уходит выше входа во
    столько же раз, и запас, который забор себе считает, оказывается в
    разы больше того, который у позиции есть на деле.
    """
    mine = [r for r in rows if r["band"] == band]
    if not mine:
        return None, f"позиций полосы «{BAND_TITLE.get(band, band)}» нет"
    part = [r for r in mine
            if r.get("w_sum") is not None and r["w_sum"] < 1.0 - 1e-9]
    g = _med_mean([r.get("gap") for r in mine])
    gf = _med_mean([r.get("gap_flat") for r in mine])
    rg = _med_mean([r.get("rng") for r in mine])
    ar = _med_mean([r.get("avg_ratio") for r in mine])
    nr = _med_mean([r.get("n_rungs") for r in mine])
    if not part:
        return False, (
            f"у полосы «{BAND_TITLE.get(band, band)}» лестница полная у "
            f"всех {len(mine)} позиций (рунгов медиана {_f(nr['med'], 1)}): "
            "забор считает ту же позицию, которой торгуют")
    return True, (
        f"у {len(part)} из {len(mine)} позиций полосы "
        f"«{BAND_TITLE.get(band, band)}» лестница НЕПОЛНАЯ (рунгов медиана "
        f"{_f(nr['med'], 1)} из {D2.N_RUNGS}); забор считает запас "
        f"{_s(g['med'], 1)} — это средняя цена набранной лестницы в "
        f"{_f(ar['med'], 2)} раза выше входа, — а у позиции БЕЗ ДОЛИВОВ, "
        f"которой книга торгует, запас на том же плече {_s(gf['med'], 1)} "
        f"при размахе суток {_s(rg['med'], 1)}. То есть полосу делает не "
        "σ, а лестница, которую забор считает набранной, хотя семейство "
        "её не набирает: пол, выраженный через ту же `max_leverage`, этих "
        "позиций не связывает по построению")


def sigma_verdict(table):
    """Вердикт шага 0 — ИЗ ЧИСЛА, а не рядом с ним."""
    b = (table or {}).get("25x") or {}
    ratio = (b.get("ratio") or {}).get("med")
    if not b.get("n"):
        return None, "полосы 25× в выборке нет — судить нечего"
    if ratio is None:
        return None, ("отношение размах / σ_сут у полосы 25× не измерено "
                      "ни у одной позиции")
    flat = (b.get("flat") or {}).get("med")
    fl = "—" if flat is None else f"{100.0 * flat:.0f} %"
    if ratio >= DEFECT_RATIO:
        return "дефект", (
            f"у полосы 25× медиана размах / σ_сут = {ratio:.1f} при "
            f"{BROWN_RATIO:g} у случайного блуждания и пределе "
            f"{DEFECT_RATIO:g}; доля минут без движения {fl} — σ забора "
            "описывает не имя, а замороженный ряд, и это дефект меры "
            "(класс «не измерено ≠ ноль», чинит роль fix)")
    if ratio <= HONEST_RATIO:
        return "честна", (
            f"у полосы 25× медиана размах / σ_сут = {ratio:.1f} при "
            f"{BROWN_RATIO:g} у случайного блуждания и пороге "
            f"{HONEST_RATIO:g} — σ честна, имена были тихими на самом "
            "деле и разогнались после; дефекта меры нет, пол остаётся "
            "правилом «тихая перед разгоном»")
    return "между", (
        f"у полосы 25× медиана размах / σ_сут = {ratio:.1f} — между "
        f"порогами {HONEST_RATIO:g} и {DEFECT_RATIO:g}: ни дефект меры, "
        "ни честная σ не объявляются, число названо как есть")


def inert_verdict(rows, table, variant=VERDICT_VARIANT):
    """Шаг 1: связывает ли пол хоть что-нибудь."""
    n = len(rows)
    moved = sum(1 for r in rows if moved_of(r, variant))
    share = (moved / n) if n else None
    b25 = ((table or {}).get("25x") or {}).get("lev_after") or {}
    lev25 = b25.get("med")
    if not n:
        return True, "позиций нет — судить нечего", {"share": None}
    if share < INERT_SHARE:
        return True, (
            f"пол связал {moved} позиций из {n} ({100 * share:.1f} %) при "
            f"пороге {100 * INERT_SHARE:.0f} % — судить нечего, закрыто"
        ), {"share": share, "moved": moved, "lev25": lev25}
    if lev25 is not None and lev25 >= INERT_LEV:
        return True, (
            f"у полосы 25× после пола медианное плечо {lev25:.1f}× при "
            f"пороге {INERT_LEV:g}× — то есть размах суток у неё не "
            "больше того, что забор уже разрешал: портрет хвоста мерил "
            "другое, закрыто"
        ), {"share": share, "moved": moved, "lev25": lev25}
    return False, (
        f"пол связал {moved} позиций из {n} ({100 * share:.1f} %), у "
        f"полосы 25× медианное плечо после пола "
        + ("—" if lev25 is None else f"{lev25:.1f}×")
        + f" при пороге {INERT_LEV:g}× — судить есть что"
    ), {"share": share, "moved": moved, "lev25": lev25}


def claims_check(rows, cells, variant=VERDICT_VARIANT):
    """Следствия, объявленные ДО счёта: сбылись или нет — числом."""
    n = len(rows)
    moved = sum(1 for r in rows if moved_of(r, variant))
    share = (moved / n) if n else None
    out = {"share_touched": share, "claim_share": CLAIM_SHARE,
           "share_ok": (None if share is None else share <= CLAIM_SHARE)}
    bands_before = (cells.get("base") or {}).get("bands") or {}
    bands_after = (cells.get(FLOOR_VARIANTS[variant][0])
                   or {}).get("bands") or {}
    out["tail_before"] = {k: v.get("tail_share")
                          for k, v in bands_before.items()}
    out["tail_after"] = {k: v.get("tail_share")
                         for k, v in bands_after.items()}
    hi = [bands_before.get(k, {}).get("tail_share") for k in ("15-25", "25x")]
    hi = [x for x in hi if x is not None]
    out["tail_hi_before"] = max(hi) if hi else None
    lo = bands_after.get("1-5", {}).get("tail_share")
    out["tail_lo_after"] = lo
    out["claim_tail"] = CLAIM_TAIL
    return out


def better(a, b):
    """Лучше ли книга `a`, чем `b`, по укусу И по доходу на просадку.

    «Не измерено» не побеждает и не проигрывает: сравнение, у которого
    нет одной из величин, — прочерк, а не победа.
    """
    ba, bb = (a or {}).get("bite"), (b or {}).get("bite")
    ra, rb = (a or {}).get("ratio"), (b or {}).get("ratio")
    if None in (ba, bb, ra, rb):
        return None
    return (float(ba) <= float(bb)) and (float(ra) >= float(rb))


def pack_cell(st):
    """Клетка сравнения: укус, доход на просадку, форма и концентрация."""
    if not st:
        return None
    sh = shape_of(st) or {}
    return {"n": st.get("n"), "usd": st.get("usd"), "final": st.get("final"),
            "max_dd": st.get("max_dd"), "ratio": st.get("ratio"),
            "bite": sh.get("bite"), "med": sh.get("med"),
            "green": sh.get("green"), "days": sh.get("days"),
            "thin": sh.get("thin"),
            "day_median_usd": sh.get("med"),
            "usd_wo_top": st.get("usd_wo_top"),
            "usd_wo_top3d": st.get("usd_wo_top3d"),
            "wo3d_share": wo_top3d_share(st),
            "max_dd_wo_worst": st.get("max_dd_wo_worst"),
            "top_sym": st.get("top_sym"), "worst_day": st.get("worst_day"),
            "lev_mean": st.get("lev_mean"), "lev_median": st.get("lev_median"),
            "open_mean": st.get("open_mean"), "open_max": st.get("open_max"),
            "taken": st.get("taken"), "no_cash": st.get("no_cash"),
            "fp": st.get("fp"), "exits": st.get("exits"),
            "bands": st.get("bands"),
            "named_days": {d: next((x["usd"] for x in
                                    (st.get("days_rows") or [])
                                    if x["d"] == d), None)
                           for d in DAYS_NAMED}}


def uniform_verdict(cells, vkey="floor"):
    """Шаг 3: не «меньше плеча в новом костюме» ли это."""
    f = cells.get(vkey)
    outs = []
    for name, title in (("scale", "равномерный множитель"),
                        ("cap", "плоский потолок")):
        c = cells.get(name)
        if not c or not f:
            outs.append((name, None, f"{title}: не посчитан"))
            continue
        win = better(f, c)
        if win is None:
            outs.append((name, None,
                         f"{title}: сравнение не измерено (укус или доход "
                         "на просадку отсутствует)"))
            continue
        outs.append((name, win, (
            f"{title}: укус {_f(c.get('bite'))} против {_f(f.get('bite'))} "
            f"у пола, доход на просадку {_f(c.get('ratio'))} против "
            f"{_f(f.get('ratio'))}; среднее плечо {_f(c.get('lev_mean'))} "
            f"против {_f(f.get('lev_mean'))} — "
            + ("пол лучше" if win else "пол НЕ лучше: правило есть "
                                       "уменьшение плеча в новом костюме"))))
    # Ни одного ИЗМЕРЕННОГО сравнения — контроль не проведён, а не
    # пройден: «жива» на неизмеренном есть разрешение объявлять.
    dead = (any(w is False for _n, w, _t in outs)
            if any(w is not None for _n, w, _t in outs) else None)
    return dead, outs


def oracle_verdict(cells, vkey="floor"):
    """Шаг 2: верхняя граница любой переменной забора."""
    o, s = cells.get("oracle"), cells.get("scale")
    if not o:
        return None, "потолок не посчитан"
    ex = o.get("exits") or {}
    tail = sum((ex.get(k) or {}).get("n", 0) for k in TAIL_EXITS)
    note = (f"хвостовых исходов у потолка {tail} при ожидаемом нуле "
            "(потолок ставит запас больше реализованного хода; остаток — "
            "позиции, упёршиеся в потолок плеча 25× или в предел тира)"
            if tail else "хвостовых исходов у потолка нет, как и должно")
    if not s:
        return None, note + "; равномерного контроля рядом нет"
    win = better(o, s)
    if win is None:
        return None, note + "; сравнение не измерено"
    if win is False:
        return True, (note + f"; укус потолка {_f(o.get('bite'))} против "
                      f"{_f(s.get('bite'))} у равномерного, доход на "
                      f"просадку {_f(o.get('ratio'))} против "
                      f"{_f(s.get('ratio'))} — даже идеальное знание "
                      "будущего не бьёт равномерное уменьшение плеча: "
                      "переменная забора книгу не выправит, закрыто")
    return False, (note + f"; укус потолка {_f(o.get('bite'))} против "
                   f"{_f(s.get('bite'))} у равномерного, доход на просадку "
                   f"{_f(o.get('ratio'))} против {_f(s.get('ratio'))} — "
                   "верхняя граница переменной забора выше равномерного "
                   "контроля, судить есть что")


def seed_verdict(floor_cell, seed_cells):
    """Шаг 4: случайная выборка того же размера."""
    n = len(seed_cells)
    if not n or not floor_cell:
        return None, {"n": 0}, "зёрен не посчитано — контроль не проведён"
    wins = 0
    unmeasured = 0
    for c in seed_cells:
        w = better(c, floor_cell)
        if w is None:
            unmeasured += 1
            continue
        wins += 1 if w else 0
    # Доля считается от ИЗМЕРЕННЫХ зёрен: зерно, у которого нет укуса
    # (суток меньше окна) или нет просадки, не есть зерно «случайная не
    # лучше» — ноль побед на неизмеренном был бы разрешением объявлять.
    measured = n - unmeasured
    if not measured:
        return None, {"n": n, "unmeasured": unmeasured, "wins": 0,
                      "share": None, "kill": SEED_KILL}, (
            f"ни у одного из {n} зёрен сравнение не измерено (нет укуса "
            "или просадки) — контроль не проведён, а не пройден")
    share = wins / measured
    st = {"n": n, "measured": measured, "wins": wins, "share": share,
          "unmeasured": unmeasured, "kill": SEED_KILL,
          "bite": _med_mean([c.get("bite") for c in seed_cells]),
          "ratio": _med_mean([c.get("ratio") for c in seed_cells]),
          "usd": _med_mean([c.get("usd") for c in seed_cells])}
    dead = share >= SEED_KILL
    why = (f"случайная выборка того же размера не хуже пола по укусу И по "
           f"доходу на просадку у {wins} зёрен из {measured} измеренных "
           f"({100 * share:.1f} %) при пороге {100 * SEED_KILL:.0f} % — "
           + ("выигрыш даёт «случайно уменьшили несколько крупных», а не "
              "размах, закрыто" if dead else
              "пол объясняется размахом, а не случайным уменьшением"))
    if unmeasured:
        why += f"; у {unmeasured} зёрен сравнение не измерено"
    return dead, st, why


def shape_verdict(cell):
    """Шаг 5: форма на записи."""
    if not cell:
        return None, "книга не посчитана"
    wo3 = cell.get("usd_wo_top3d")
    share = cell.get("wo3d_share")
    med = cell.get("med")
    if wo3 is None or med is None:
        return None, ("форма не измерена: суток меньше четырёх, вычитать "
                      "три лучших не из чего")
    bad = []
    if float(wo3) <= 0:
        bad.append(f"без 3 лучших дней {wo3:+.2f} $ — книга описывает "
                   "эпизод, а не правило")
    if share is not None and float(share) < BASE_WO3D_SHARE:
        bad.append(f"без 3 лучших дней остаётся {100 * share:.0f} % итога "
                   f"при {100 * BASE_WO3D_SHARE:.0f} % у базы")
    if float(med) < 0:
        bad.append(f"медиана дня {med:+.2f} $ отрицательна")
    if bad:
        return True, "; ".join(bad)
    return False, (f"без 3 лучших дней {wo3:+.2f} $ "
                   + ("" if share is None
                      else f"({100 * share:.0f} % итога при "
                           f"{100 * BASE_WO3D_SHARE:.0f} % у базы) ")
                   + f"при медиане дня {med:+.2f} $ — форма держится")


def forward_note(st_floor, st_base):
    """Шаг 6: правило вылета пула — и честная оговорка о том, что это.

    `pool.shape_why` судит ФОРВАРД, а здесь суток форварда нет вовсе:
    книга-сестра не объявлена и вперёд не записывала ни дня. Поэтому
    правило считается по ПЕРЕСЧЁТУ и вердикта не несёт — иначе замер
    судил бы кандидата бэктестом, ровно тем, против чего правило.
    """
    d_floor, d_base = daily_of(st_floor), daily_of(st_base)
    why = PL.shape_why(daily_by_no(st_floor), declared_at=0.0)
    corr, days = CE.pair_corr(d_floor, d_base)
    return {"shape_why": why, "corr": corr, "corr_days": days,
            "days": len(d_floor),
            "verdict": ("правило вылета на пересчёте молчит"
                        if why is None else f"правило вылета сказало бы: "
                                            f"{why}")}


def _f(x, d=2):
    return "—" if x is None else f"{float(x):.{d}f}"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _s(x, d=0):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


# --- прогон ------------------------------------------------------------

def run(limit=None, src=None, log=print, legs_=None, ctx=None, launch=None,
        now=None, n_seeds=SEEDS, books=None, mem_limit=None, oracle=True,
        variant=VERDICT_VARIANT):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    if variant not in FLOOR_VARIANTS:
        return {"error": f"трактовка «{variant}» не объявлена: есть "
                         + ", ".join(sorted(FLOOR_VARIANTS))}
    vkey = FLOOR_VARIANTS[variant][0]
    books = list(books or [VERDICT_BOOK])
    ctx = ctx if ctx is not None else CO.context(log=log)
    launch = IR.launches() if launch is None else launch
    legs_ = S.legs(limit=limit, log=log) if legs_ is None else list(legs_)
    if not legs_:
        return {"error": "коротких решений на листе нет — считать нечего"}
    rk_want = {S.BOOKS[bk] for bk in books if bk in S.BOOKS}
    if not rk_want:
        return {"error": f"книги {books} не ведут ни к одной линейке"}

    rows_all, _b = scan(legs_, src=src, log=log, oracle=oracle)
    rows = [r for r in rows_all if r["ruler"] in rk_want]
    if not rows:
        # Отказ вместо пустоты: ноль позиций при непустом листе означает,
        # что мерить нечем, и отчёт с прочерками выдавал бы это за
        # результат.
        return {"error": f"забор не посчитан ни у одной позиции при "
                         f"{len(legs_)} решениях листа — мерить нечем"}
    table = bands_table(rows, variant)
    s_kind, s_why = sigma_verdict(table)
    p_part, p_why = partial_note(rows)
    inert, i_why, i_num = inert_verdict(rows, table, variant)

    want_mean = sum(after_of(r, variant) for r in rows) / len(rows)
    scale = solve_scale(rows, want_mean)
    cap = solve_cap(rows, want_mean)
    picks, pick_st = seed_picks(rows, n_seeds=n_seeds, variant=variant)
    plan = build_plan(rows, scale=scale, cap=cap, picks=picks, oracle=oracle)
    log(f"план: вариантов на позицию "
        f"{len(plan[next(iter(plan))]) if plan else 0}, зёрен "
        f"{pick_st.get('seeds')}, множитель равномерного "
        f"{_f(scale, 4)}, плоский потолок {_f(cap, 2)}×, среднее плечо "
        f"цели {_f(want_mean, 3)}")

    got = sim(legs_, plan, src=src, log=log, oracle=oracle, books=books)
    # Обещание модели у записей — из тех же ног, что кормят реплей (как в
    # прогоне книг): ядро его в запись не кладёт, а книга им рисует цель.
    fav = {}
    for g in legs_:
        try:
            fav[(g["sym"], round(float(g["at"]), 3))] = float(g["fav"])
        except (KeyError, TypeError, ValueError):
            continue
    for byrk in (got.get("recs") or {}).values():
        for byk in byrk.values():
            for (_rk, sym, at), r in byk.items():
                if r.get("fav_bp") is None:
                    r["fav_bp"] = fav.get((sym, at))
    for (_rk, sym, at), bym in (got.get("seeds") or {}).items():
        for r in bym.values():
            if r.get("fav_bp") is None:
                r["fav_bp"] = fav.get((sym, at))
    cells, stats = {}, {}
    for name, byrk in (got.get("recs") or {}).items():
        by_ruler = {rk: list(byk.values()) for rk, byk in byrk.items()}
        st = book_stats(by_ruler, ctx, launch, now=now, keys=books,
                        log=lambda *a: None)
        stats[name] = st
        cells[name] = pack_cell(st.get(f"{VERDICT_BOOK}:{int(VERDICT_DEP)}"))
    if not cells.get("base") or not cells.get(vkey):
        return {"error": "ни база, ни книга с полом не посчитаны кассой — "
                         "сравнивать нечего"}

    # Зёрна: книга собирается из БАЗОВЫХ записей, у которых подменены
    # ровно выпавшие зерну позиции. Исход зависит от плеча, поэтому
    # каждая подменённая позиция — своя симуляция, а не масштаб.
    base_recs = (got.get("recs") or {}).get("base") or {}
    seed_cells = []
    for s in sorted(picks):
        by_ruler = {}
        pick = picks[s]
        for rk, byk in base_recs.items():
            mine = []
            for key, rec in byk.items():
                m = pick.get(key)
                alt = (got.get("seeds") or {}).get(key, {}).get(
                    float(m)) if m is not None else None
                mine.append(alt if alt is not None else rec)
            by_ruler[rk] = mine
        st = book_stats(by_ruler, ctx, launch, now=now, keys=[VERDICT_BOOK],
                        deps=[VERDICT_DEP], log=lambda *a: None)
        c = pack_cell(st.get(f"{VERDICT_BOOK}:{int(VERDICT_DEP)}"))
        if c:
            seed_cells.append(c)
        if (s + 1) % 25 == 0:
            log(f"  зёрна {s + 1}/{len(picks)}")

    o_dead, o_why = oracle_verdict(cells, vkey)
    u_dead, u_why = uniform_verdict(cells, vkey)
    sd_dead, sd_st, sd_why = seed_verdict(cells.get(vkey), seed_cells)
    sh_dead, sh_why = shape_verdict(cells.get(vkey))
    cell_key = f"{VERDICT_BOOK}:{int(VERDICT_DEP)}"
    fwd = forward_note(stats.get(vkey, {}).get(cell_key),
                       stats.get("base", {}).get(cell_key))

    steps = [{"n": 0, "name": "разрешение противоречия", "dead": None,
              "why": s_why + ". " + (p_why or ""), "kind": s_kind},
             {"n": 1, "name": "инертность", "dead": inert, "why": i_why},
             {"n": 2, "name": "потолок с идеальным знанием будущего",
              "dead": o_dead, "why": o_why},
             {"n": 3, "name": "равномерный контроль", "dead": u_dead,
              "why": "; ".join(t for _n, _w, t in u_why)},
             {"n": 4, "name": "случайная выборка того же размера",
              "dead": sd_dead, "why": sd_why},
             {"n": 5, "name": "форма на записи", "dead": sh_dead,
              "why": sh_why},
             {"n": 6, "name": "вперёд", "dead": None,
              "why": fwd["verdict"] + " (пересчёт, не форвард)"}]
    stop = next((st for st in steps if st["dead"] is True), None)
    return {
        "mech": "dc3b6317", "books": books, "verdict_cell":
            f"{VERDICT_BOOK}:{int(VERDICT_DEP)}",
        "mult": RANGE_MULT, "diag_mults": list(DIAG_MULTS),
        "variant": variant, "variant_key": vkey,
        "variant_title": FLOOR_VARIANTS[variant][1],
        "variants": {k: v[1] for k, v in FLOOR_VARIANTS.items()},
        "legs": len(legs_), "positions": len(rows),
        "table": table, "sigma_kind": s_kind,
        "partial": p_part, "partial_why": p_why,
        "inert": i_num, "claims": claims_check(rows, cells, variant),
        "scale": scale, "cap": cap, "mean_lev_target": want_mean,
        "picks": pick_st, "seeds": sd_st, "seed_cells": len(seed_cells),
        "cells": cells, "books_all": {k: {kk: _thin(vv) for kk, vv
                                          in v.items()}
                                      for k, v in stats.items()},
        "forward": fwd, "steps": steps,
        "stopped_at": (None if stop is None else stop["n"]),
        "no_plan": got.get("no_plan"),
        "costs_error": (ctx or {}).get("error"),
        "launch_known": len(launch or {}),
        "hold_h": R.H24_HOLD_H, "rules": R.RULES,
        "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


def _thin(st):
    """Книга в артефакт БЕЗ построчной разбивки: суточный ряд остаётся."""
    out = {k: v for k, v in (st or {}).items() if k != "days_rows"}
    out["days_rows"] = [{"d": d["d"], "usd": d["usd"], "n": d["n"]}
                        for d in (st or {}).get("days_rows") or []]
    return out


# --- отчёт -------------------------------------------------------------

def report(s):
    L = ["# Забор не ближе вчерашнего размаха: пол запаса коротких книг "
         "h24", "",
         "Механика `dc3b6317`. Утверждение: расстояние «вход → "
         "ликвидация» не вправе быть меньше собственного размаха имени "
         "за 24 ч до входа — **запас = max(запас линейки, размах)**. "
         f"Множитель размаха объявлен до прогона и равен {RANGE_MULT:g} "
         "(тождество «один вчерашний размах», а не сетка); "
         + ", ".join(f"{m:g}" for m in DIAG_MULTS)
         + " считаются диагностикой и не выбираются.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    L += [f"Ячейка вердикта одна: `{s.get('verdict_cell')}`. Решений "
          f"листа {s.get('legs')}, позиций линейки {s.get('positions')}, "
          f"срок {s.get('hold_h')} ч, правила версии {s.get('rules')}; "
          f"прогон {s.get('secs')} с ({s.get('computed_at')} UTC).", "",
          "**Трактовок у заявки две, и выбор между ними не за замером.** "
          "Задание говорит «пол как параметр `fence_leverage`» — это пол "
          "на ПОЛНОСТЬЮ НАБРАННОЙ лестнице забора. Сама заявка говорит "
          "«расстояние вход → ликвидация у КАЖДОЙ позиции» — а книга "
          "`h24` торгует ячейку БЕЗ ДОЛИВОВ, и лестницу не набирает "
          "никогда. Посчитаны обе; вердикт несёт объявленная прогоном: "
          f"**{s.get('variant_title')}** (`--verdict {s.get('variant')}`). "
          "Вторая печатается рядом диагностикой и вердикта не несёт — "
          "чтобы судить её, нужно объявить её заранее, а не выбрать "
          "после просмотра чисел.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']} — деньги ниже "
              "брутто, и сравнивать их с нетто-числами базы нельзя.", ""]
    if s.get("no_plan"):
        L += [f"**Вне плана {s['no_plan']} позиций:** второй проход увидел "
              "решения, которых не было в первом, и они посчитаны только "
              "базой.", ""]

    L += ["## Шаг 0. Что видел забор: σ против размаха", "",
          "Таблица читается и без заявки: она говорит, на чём стоит плечо "
          "книги. У случайного блуждания размах суток примерно "
          f"{BROWN_RATIO:g} σ_сут; отношение сильно выше означает, что σ "
          "описывает не имя, а замороженную котировку. Медиана и среднее "
          "стоят рядом везде.", "",
          "| полоса плеча | позиций | σ_сут мед / срд | размах мед / срд | "
          "размах/σ мед / срд | баров мед | минут без движения мед | "
          "не измерено | рунгов мед | запас забора мед | запас без доливов "
          "мед | плечо до мед | плечо после мед | связал пол |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for bk, title in BANDS:
        b = (s.get("table") or {}).get(bk) or {}
        if not b.get("n"):
            L.append(f"| {title} | 0 |" + " — |" * 13)
            continue
        L.append(
            f"| {title} | {b['n']} | "
            f"{_s(b['sigma_day']['med'], 2)} / {_s(b['sigma_day']['mean'], 2)}"
            f" | {_s(b['rng']['med'], 1)} / {_s(b['rng']['mean'], 1)} | "
            f"{_f(b['ratio']['med'], 1)} / {_f(b['ratio']['mean'], 1)} | "
            f"{_f(b['n_bars']['med'], 0)} | {_s(b['flat']['med'], 0)} | "
            f"{b['no_measure']} | {_f(b['n_rungs']['med'], 1)} | "
            f"{_s(b['gap']['med'], 1)} | {_s(b['gap_flat']['med'], 1)} | "
            f"{_f(b['lev']['med'], 1)}× | "
            f"{_f(b['lev_after']['med'], 1)}× | "
            f"{b['moved']} ({_s(b['moved_share'], 0)}) |")
    L += ["", "**Кто связал плечо** — по полосам:", ""]
    for bk, title in BANDS:
        b = (s.get("table") or {}).get(bk) or {}
        if not b.get("n"):
            continue
        L.append(f"* {title}: "
                 + ", ".join(f"{k} {v}" for k, v
                             in sorted((b.get("binders") or {}).items(),
                                       key=lambda x: -x[1])))
    L += ["", "**Две колонки запаса — не опечатка.** «Запас забора» — "
          "расстояние «вход → ликвидация», которое забор СЧИТАЕТ, выводя "
          "плечо: он считает его у полностью набранной лестницы. «Запас "
          "без доливов» — то же расстояние у позиции, которой семейство "
          "`h24` торгует на самом деле (ячейка `fence:none:t2`, доливов "
          "нет). Расходятся они там, где лестница неполная: у неё сумма "
          "весов меньше единицы, и средняя цена набранной лестницы "
          "уходит выше входа во столько же раз.", ""]
    if s.get("partial_why"):
        L += [f"**Чем забор считает позицию полосы 25×:** "
              f"{s['partial_why']}.", ""]
    st0 = next((x for x in s.get("steps") or [] if x["n"] == 0), {})
    L += [f"**Вердикт шага 0:** {st0.get('why')}", ""]

    L += ["## Шаги 1–6: чем механика убивается", ""]
    for st in s.get("steps") or []:
        mark = ("—" if st["dead"] is None
                else ("**МЁРТВА**" if st["dead"] else "жива"))
        L.append(f"{st['n']}. **{st['name']}** — {mark}: {st['why']}.")
    stop = s.get("stopped_at")
    L += ["", (f"**Механика закрыта на шаге {stop}.** Числа дальнейших "
               "шагов напечатаны ниже как диагностика и вердикта не несут: "
               "шаг, стоящий после убийцы, не вправе воскрешать заявку."
               if stop is not None else
               "**Ни один убийца не сработал.** Это не значит «работает»: "
               "форму судит форвард, а окно здесь одно и веса модели эти "
               "часы видели."), ""]

    cl = s.get("claims") or {}
    L += ["## Следствия, объявленные ДО счёта", "",
          f"* пол трогает не более {100 * CLAIM_SHARE:.0f} % позиций — "
          f"тронуто {_s(cl.get('share_touched'), 1)}: "
          + ("сбылось" if cl.get("share_ok") else "НЕ сбылось"),
          f"* доля хвостовых исходов у тронутых полос падает до уровня "
          f"1–5× (≤ {100 * CLAIM_TAIL:.0f} %): было "
          f"{_s(cl.get('tail_hi_before'), 1)} у полос 15–25× и 25×, стало "
          f"{_s(cl.get('tail_lo_after'), 1)} у полосы 1–5× книги с полом",
          ""]

    L += ["## Книги: база, пол, потолок, равномерные контроли", "",
          f"Ячейка вердикта — `{s.get('verdict_cell')}`, деньги НЕТТО. "
          f"Равномерный множитель {_f(s.get('scale'), 4)}, плоский потолок "
          f"{_f(s.get('cap'), 2)}×; оба подобраны так, чтобы среднее плечо "
          f"равнялось {_f(s.get('mean_lev_target'), 3)}× — среднему у "
          "книги с полом. Достигнутое среднее печатается колонкой: "
          "равенство на ВЗЯТЫХ кассой позициях не гарантировано, и "
          "утверждать его без числа нельзя.", "",
          "| книга | сделок | Σ $ | итог | просадка | доход/просадка | "
          "укус | медиана дня | зелёных | без лучш. имени | без 3 лучш. "
          "дней | доля итога | просадка без худш. дня | плечо срд | "
          "загрузка срд / пик |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    vk = s.get("variant_key") or "floor"
    rowset = (("base", "база (как сейчас)"),
              ("floor", "пол = размах, на лестнице забора"
                        + (" — ВЕРДИКТ" if vk == "floor" else
                           " (диагностика)")),
              ("floor_flat", "пол = размах, на позиции без доливов"
                             + (" — ВЕРДИКТ" if vk == "floor_flat" else
                                " (диагностика)")),
              ("oracle", "потолок: знание будущего"),
              ("scale", "равномерный множитель"),
              ("cap", "плоский потолок"))
    for name, title in rowset:
        c = (s.get("cells") or {}).get(name)
        if not c:
            L.append(f"| {title} |" + " — |" * 14)
            continue
        L.append(
            f"| {title} | {c.get('n')} | {_u(c.get('usd'))} | "
            f"{_p(c.get('final'))} | {_p(c.get('max_dd'))} | "
            f"{_f(c.get('ratio'))} | {_f(c.get('bite'), 1)} | "
            f"{_u(c.get('med'))} | {_s(c.get('green'), 0)} | "
            f"{_u(c.get('usd_wo_top'))} | {_u(c.get('usd_wo_top3d'))} | "
            f"{_s(c.get('wo3d_share'), 0)} | "
            f"{_p(c.get('max_dd_wo_worst'))} | "
            f"{_f(c.get('lev_mean'), 2)}× | "
            f"{_f(c.get('open_mean'), 1)} / {c.get('open_max')} |")

    L += ["", "**Дни, названные заданием отдельно** ($ нетто):", "",
          "| книга | " + " | ".join(DAYS_NAMED) + " |",
          "|---|" + "--:|" * len(DAYS_NAMED)]
    for name, title in (("base", "база"), ("floor", "пол на лестнице"),
                        ("floor_flat", "пол без доливов")):
        c = (s.get("cells") or {}).get(name) or {}
        nd = c.get("named_days") or {}
        L.append(f"| {title} | "
                 + " | ".join(_u(nd.get(d)) for d in DAYS_NAMED) + " |")

    L += ["", "**Состав исходов** (сделок и деньги):", "",
          "| книга | " + " | ".join(("тейк", "срок", "пол", "ликвидация",
                                     "рынок")) + " |",
          "|---|--:|--:|--:|--:|--:|"]
    for name, title in (("base", "база"), ("floor", "пол на лестнице"),
                        ("floor_flat", "пол без доливов"),
                        ("oracle", "потолок"), ("scale", "равномерный"),
                        ("cap", "плоский потолок")):
        c = (s.get("cells") or {}).get(name) or {}
        ex = c.get("exits") or {}

        def _e(k, ex=ex):
            v = ex.get(k) or {}
            return "—" if not v.get("n") else f"{v['n']} ({v['usd']:+.0f} $)"
        L.append(f"| {title} | "
                 + " | ".join(_e(k) for k in ("тейк", "срок", "пол",
                                              "ликвидация", R.GUARD_EXIT))
                 + " |")

    sd = s.get("seeds") or {}
    pk = s.get("picks") or {}
    L += ["", "## Контроль случайной выборкой того же размера", "",
          f"Множители плеча тронутых позиций ({pk.get('mults')} штук) "
          f"раздаются случайным позициям из тех, где уменьшать есть что "
          f"(плечо больше 1×: {pk.get('pool')} позиций), "
          f"{sd.get('n')} зёрен номерами. Позиция на 1× в жеребьёвку не "
          "входит намеренно: уменьшение плеча там не делает ничего, и "
          "контроль был бы заведомо слабее правила.", ""]
    if pk.get("why"):
        L += [f"**Контроль не проведён:** {pk['why']} — это «не измерено», "
              "а не «случайная проиграла».", ""]
    L += [
          f"Случайная не хуже пола по укусу И по доходу на просадку у "
          f"{sd.get('wins')} зёрен из {sd.get('measured')} измеренных "
          f"(всего {sd.get('n')}, не измерено {sd.get('unmeasured')}): "
          f"{_s(sd.get('share'), 1)} при пороге "
          f"{100 * SEED_KILL:.0f} %. Укус случайных: медиана "
          f"{_f((sd.get('bite') or {}).get('med'), 1)}, среднее "
          f"{_f((sd.get('bite') or {}).get('mean'), 1)}; доход на просадку: "
          f"медиана {_f((sd.get('ratio') or {}).get('med'))}, среднее "
          f"{_f((sd.get('ratio') or {}).get('mean'))}.", ""]

    fw = s.get("forward") or {}
    L += ["## Вперёд", "",
          f"Суток в ряду {fw.get('days')}; связь дневных денег с базой "
          f"{_f(fw.get('corr'))} по {fw.get('corr_days')} общим суткам "
          "(высокая по построению: входы те же, меняется только плечо). "
          f"{fw.get('verdict')}.", "",
          "**Это пересчёт, а не форвард.** Книга-сестра не объявлена и "
          "вперёд не записала ни дня; правило вылета пула судит форвард, и "
          "применять его к пересчёту значило бы судить кандидата "
          "бэктестом. Форму судит запись вперёд — не меньше 30 суток со "
          "сделками, как у сестры с охраной.", ""]

    L += ["## Чего замер НЕ говорит", "",
          "- Живого исполнения здесь нет: исходы считаются реплеем по "
          "барам записи, проскальзывание и очередь в стакане не "
          "моделируются.",
          "- Веса модели видели эти часы: пересчёт истории читается как "
          "оценка СВЕРХУ.",
          "- Окно одно и режим рынка один; «лучшая ячейка» здесь не "
          "выбирается — множитель размаха объявлен до прогона и равен "
          f"{RANGE_MULT:g}.",
          "- Линейки глубины (`optimal_h`, `aggr_h`) под тем же полом — "
          "диагностика без вердикта: у них запас 2·d_max мал, пол связал "
          "бы почти каждую позицию, и это была бы смена линейки, а не пол.",
          "- Живой кэш реплея коротких книг не тронут: замер считает оба "
          "прохода на месте и своего кэша не ведёт.", ""]
    return "\n".join(L)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def write(s, name=ART, log=print):
    os.makedirs(OUT, exist_ok=True)
    art = os.path.join(OUT, f"{name}.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    log(txt)
    return txt


def main(argv=None):
    ap = argparse.ArgumentParser(description="пол забора из размаха суток")
    ap.add_argument("--limit", type=int, default=None, help="ног, смоук")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--books", default=VERDICT_BOOK,
                    help="книги через запятую; вердикт — только "
                         f"{VERDICT_BOOK}")
    ap.add_argument("--verdict", choices=sorted(FLOOR_VARIANTS),
                    default=VERDICT_VARIANT,
                    help="какая ТРАКТОВКА заявки несёт вердикт: "
                         + "; ".join(f"{k} — {v[1]}"
                                     for k, v in FLOOR_VARIANTS.items()))
    ap.add_argument("--no-oracle", action="store_true",
                    help="без потолка с идеальным знанием будущего")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)          # каталог артефактов ДО счёта
    s = run(limit=a.limit, n_seeds=a.seeds,
            books=[b for b in a.books.split(",") if b],
            oracle=not a.no_oracle, variant=a.verdict)
    name = ART if not a.limit else f"{ART}-smoke"
    if a.verdict != VERDICT_VARIANT:
        name += f"-{a.verdict}"
    write(s, name=name)
    if not a.no_publish:
        publish("механика dc3b6317: пол забора из размаха суток")
    return 0


if __name__ == "__main__":
    sys.exit(main())
