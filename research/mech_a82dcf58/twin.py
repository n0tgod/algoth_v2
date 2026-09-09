#!/usr/bin/env python3
"""Механика a82dcf58 — двойник по ИМЕНИ: чьи это деньги, выбор модели
или час рынка.

Ядро механики (чистые функции; диск и журнал листов — в `run_twin.py`).

Что переставляется. Позиция DCA-книги есть тройка «имя × геометрия ×
плечо». Спека 14 §8 называет шесть нулей, и ни один не меняет ИМЯ:
сестринская механика 49b535f8 переставляет УРОВНИ на тех же именах
(вопрос «где доливать»), здесь фиксированы уровни, тейк и плечо, а
случайно ИМЯ — вопрос «что покупать». Двойник берётся из строки ТОГО ЖЕ
ЧАСА журнала листов (в строке лежит всё сечение, около 700 имён), то
есть контроль — ОДНОВРЕМЕННАЯ кросс-секция, тот самый, которым проект
закрыл каскады, ленту и первые секунды.

Почему двойника нельзя обмануть формой. Лестница переупаковывает то же
среднее в «часто по копейке, редко −100 %» (D2: S и H равны по среднему
при 43.9 % против 90.6 % зелёных). Двойник эту переупаковку не снимает,
а ДЕРЖИТ ПОСТОЯННОЙ: у него та же лестница, тот же тейк и то же плечо.
Значит единственное, что он может показать, есть содержание выбора.

Что здесь СВОЁ и что зовётся у хозяев (второй копии не заводится):

* деньги позиции — `dca_ladder/ladder.simulate_dca` (единственная дорога,
  `sim`);
* забор §5 и глубина — `mech_49b535f8/place.fence_lev`, `place.depth_of`;
* σ окна до входа — `dca_ladder/run_d3.window_stats` (линейка D5);
* уровни T4 — `dca_ladder/run_d2.build_levels`, рунги —
  `ladder.structural_rungs`;
* сетка порогов D2/D3 (гейт, срок, рунги, веса, забор, пол) — у D2;
* нуль по розыгрышам, парный бутстрап по суткам, сводка руки —
  `mech_49b535f8/place` (`null_place`, `draw_pool`, `paired_day_boot`,
  `cell_stats`): у сестринской механики тот же вид нуля, и две копии
  правила «выше 95-го процентиля» однажды разошлись бы;
* не-крипто — `common/universe_filter`.

Своё здесь: пул часа, подбор дециля σ, ПЕРЕСАДКА геометрии в долях цены
входа, заранее назначенные розыгрыши и вердиктовые фразы, выведенные из
чисел.
"""

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in ("dca_ladder", "s10_policy", "s8_loop", "s9_sweep", "t4_structure",
           "common", "dca_paper", "factory", "mech_49b535f8"):
    _d = os.path.join(RESEARCH, _p)
    if _d not in sys.path:
        sys.path.insert(0, _d)

import ladder as L                                          # noqa: E402
import run_d2 as D2                                         # noqa: E402
import run_d3 as D3                                         # noqa: E402
import place as P                                           # noqa: E402
import universe_filter as UF                                # noqa: E402

# --- объявленная сетка: чужие величины берутся У ХОЗЯЕВ --------------------
# Ячейка вердикта — базовая ячейка D2/D3, и ни одно из этих чисел здесь не
# назначается заново: порог, назначенный тем, кто его проверяет, слабее
# назначенного независимо.
MIN_EDGE_BP = D2.MIN_EDGE_BP          # гейт края книги, 33 б.п.
MIN_RR = D2.MIN_RR                    # гейт отношения, 2.0
BACK_H = D2.BACK_H                    # окно до входа: уровни и σ, 24 ч
HOLD_H = D2.HOLD_H                    # срок удержания, 72 ч
N_RUNGS = D2.N_RUNGS                  # база плюс до трёх доливов
MIN_ADD_GAP = D2.MIN_ADD_GAP          # ≥1.5 % ниже прошлого рунга (§R1)
WEIGHTS = D2.WEIGHTS                  # равные доли нотионала
SURVIVE_MULT = D2.SURVIVE_MULT        # забор §5
FLOOR_FRAC = D2.FLOOR_FRAC            # пол капитуляции §6
FLAT_MMR = D2.FLAT_MMR                # делистнутой ноге (§10 модальный)

# --- своё, объявлено ДО прогона -------------------------------------------
DRAWS = 100                           # цель задания; минимум 20
MIN_DRAWS = 20                        # ниже — розыгрышей не хватает на нуль
SEED = 20260909                       # зерно ЧИСЛОМ (урок R3)
BOOT = P.BOOT                         # повторов парного бутстрапа по суткам
NULL_Q = P.NULL_Q                     # 95-й процентиль розыгрышей
N_DEC = 10                            # децилей σ внутри часа
COVER_MIN = 0.80                      # ниже — «не измерено», не «не бьёт»

# Тир двойника. Пересаживается ВСЯ конструкция позиции, включая ставку
# поддерживающей маржи выбора: заявка говорит «меняется только имя с его
# ЦЕНОВЫМ ПУТЁМ», а MMR путём не является. Взять MMR двойника значило бы
# переставить заодно и тир площадки — мелкие имена ликвидируются чаще, и
# часть разности S − T оказалась бы разницей тиров, а не выбора. Ключ
# `--mmr own` считает тем же кодом по тиру двойника; ячейка вердикта —
# `pick`, и это объявлено здесь, а не выбрано молча.
MMR_FROM = "pick"


def day_of(at):
    return time.strftime("%Y-%m-%d", time.gmtime(float(at)))


# ------------------------------------------------------------- геометрия

def geometry(entry, rungs, take_px, lev):
    """Геометрия позиции В ДОЛЯХ цены входа: смещения рунгов, тейк, плечо.

    Ровно то, что пересаживается двойнику. Абсолютные цены выбора
    двойнику не годятся (у него своя цена), а доли — годятся: лестница
    «−3 %, −7 %, −12 % от входа, тейк +4 %, плечо 3.1×» есть форма, не
    зависящая от имени. `off[0]` равен нулю по построению — рунг 0 есть
    сам вход.
    """
    entry = float(entry)
    if not (entry > 0):
        raise ValueError("цена входа ≤ 0 — геометрии нет")
    if not rungs:
        raise ValueError("пустая лестница")
    return {"off": [float(p) / entry - 1.0 for p in rungs],
            "take": float(take_px) / entry - 1.0,
            "lev": float(lev), "k": int(len(rungs))}


def transplant(geo, entry):
    """Та же геометрия на ДРУГОЙ цене входа: цены рунгов и цена тейка.

    Пересадка на цену самого выбора обязана возвращать исходные цены —
    иначе руки S и T мерились бы разными лестницами, и разность несла бы
    ошибку пересадки, а не содержание выбора. Закреплено тестом.
    """
    entry = float(entry)
    if not (entry > 0):
        raise ValueError("цена входа двойника ≤ 0")
    rungs = [entry * (1.0 + o) for o in geo["off"]]
    take = entry * (1.0 + geo["take"])
    return rungs, take


def sim(hold, rungs, lev, mmr, take_px):
    """Единственная дорога до ядра лестницы. Второй копии нет."""
    w = WEIGHTS[:len(rungs)]
    return L.simulate_dca(hold, rungs, w, 1.0, lev, mmr,
                          take_px=take_px, floor_frac=FLOOR_FRAC)


def sigma_at(bars, ts, at, back_h=BACK_H):
    """σ окна ДО решения — та же линейка, что у D3/D5.

    Смотрит РОВНО прошлое: окно `[at − back_h, at]` берётся до индекса
    решения (`window_stats(win, now_i)`). Переписать будущее — σ не
    шелохнётся, и это закреплено тестом с негативным контролем: без него
    сдвиг окна на бар вперёд неотличим от исправности.

    Нет окна либо мера не считается — NaN, а не ноль: замороженный ряд не
    есть спокойный ряд (урок S1).
    """
    rs = D2.split_window(bars, ts, at, back_h, 1)
    if rs is None:
        return float("nan")
    win, now_i = rs
    s_bp, _rng, _turn = D3.window_stats(win, now_i)
    return float(s_bp)


def twin_window(bars, ts, at, back_h=BACK_H, hold_h=HOLD_H):
    """Окно двойника на тот же момент решения. None — баров нет.

    Момент входа у двойника ТОТ ЖЕ, что у выбора: контроль есть
    одновременная кросс-секция, и двойник, входящий позже, мерил бы уже
    другой час рынка.
    """
    return D2.split_window(bars, ts, at, back_h, hold_h)


def own_geometry(win, now_i, fav, look):
    """Своя геометрия двойника (диагностическая рука T2).

    Свои уровни T4 по СВОИМ 24 ч, своё §5-плечо, свой тейк по своему mfe
    из той же строки листа. Отвечает на вопрос «что книга заработала бы
    на случайных именах», и потому диагностика, а не вердикт: у неё
    другая лестница, и разность с S смешала бы имя с геометрией.

    Уровни строятся по `win[:now_i + 1]` — только прошлое. `fav` ≤ 0
    (модель звала имя в шорт) — длинной геометрии у него нет, и это
    прочерк с причиной, а не ноль.
    """
    hold = win[now_i:]
    entry = float(hold[0][1])
    if not (entry > 0):
        return None, "цена входа ≤ 0"
    if not (fav is not None and float(fav) > 0):
        return None, "у имени нет длинного обещания (mfe ≤ 0)"
    take_px = entry * (1.0 + float(fav) / 1e4)
    if not (take_px > entry):
        return None, "тейк не выше входа"
    lv = D2.build_levels(win, now_i)
    rungs = L.structural_rungs(entry, list(lv), MIN_ADD_GAP, N_RUNGS)
    lev, rungs = P.fence_lev(rungs, entry, P.depth_of(entry, rungs), look)
    return {"hold": hold, "entry": entry, "take_px": take_px,
            "rungs": rungs, "lev": lev}, None


# ------------------------------------------------------------- пул часа

def pool_mask(syms, gated, non_crypto):
    """Кого час допускает в двойники: булева маска по именам сечения.

    Два запрета, и оба названы заявкой. `gated` — имена ВСЕХ гейтованных
    выборов этого часа; в нём по построению лежит и сам выбор, поэтому
    отдельного запрета «не сам выбор» не нужно, и его отсутствие
    закреплено тестом (двойник не вправе оказаться той же позицией, иначе
    контроль сравнивал бы книгу с собой). `non_crypto` — перпы не на
    криптоактив (`universe_filter`, решение владельца A1): у базового
    актива календарь биржи, и календарная компонента выглядит сигналом,
    не будучи им.
    """
    out = np.ones(len(syms), dtype=bool)
    for i, s in enumerate(syms):
        if s in gated or s in non_crypto:
            out[i] = False
    return out


def decile_edges(vals, n=N_DEC):
    """Границы децилей σ внутри часа. Меньше `n` измеренных — децилей нет.

    None означает «не измерено», и подбор по σ тогда не состоялся —
    позиция уходит в непокрытые, а не получает двойника «как будто из
    того дециля».
    """
    v = np.asarray([x for x in vals if x == x], dtype=float)
    if len(v) < int(n):
        return None
    return np.percentile(v, np.arange(1, int(n)) * (100.0 / int(n)))


def decile_of(x, edges):
    """Номер дециля значения. NaN или нет границ — None, а не ноль."""
    if edges is None or x is None or x != x:
        return None
    return int(np.searchsorted(np.asarray(edges, dtype=float), float(x),
                               side="right"))


def draw_rng(seed, draw, leg_id):
    """Генератор РОЗЫГРЫША, а не прогона: имя двойника назначено заранее.

    Ключ — тройка (зерно, номер розыгрыша, номер ноги). Отсюда двойник
    позиции не зависит ни от порядка обхода символов, ни от того, сколько
    позиций взято до неё: боевой проход идёт ПО СИМВОЛУ, и генератор,
    зависящий от порядка, дал бы другую книгу при `--limit`.
    """
    return np.random.default_rng([int(seed), int(draw), int(leg_id)])


def assign_twins(pool_idx, pool_dec, pick_dec, n_draws, leg_id, seed=SEED):
    """Имена двойников на каждый розыгрыш: подобранный по σ и без подбора.

    Возвращает `(matched, plain)` — по `n_draws` элементов в каждом,
    значения суть индексы в сечении часа либо None. None у `matched`
    означает «в дециле σ выбора никого нет», у `plain` — «сечение часа
    пусто»; обе причины разные, и ни одна не ноль.
    """
    pool_idx = list(pool_idx)
    same = [i for i, d in zip(pool_idx, pool_dec) if d is not None
            and pick_dec is not None and d == pick_dec]
    matched, plain = [], []
    for j in range(int(n_draws)):
        rng = draw_rng(seed, j, leg_id)
        matched.append(same[int(rng.integers(len(same)))] if same else None)
        plain.append(pool_idx[int(rng.integers(len(pool_idx)))]
                     if pool_idx else None)
    return matched, plain


# ------------------------------------------------------------- сводки

def beats_both(nulls):
    """Рука выше 95-го процентиля розыгрышей И по медиане, И по среднему.

    Одной из двух мало: расхождение медианы и среднего знаком есть
    подпись короткой волатильности (F, Z1), а лестница — ровно такая
    форма.
    """
    a = (nulls or {}).get("median")
    b = (nulls or {}).get("mean")
    return bool(a and b and a.get("beats") and b.get("beats"))


def paired(s_pnl, t_pnl):
    """Парная разность S − T по ПОЗИЦИЯМ: медиана и среднее рядом.

    Считается по маске измеримости: позиция без двойника пары не
    образует, и подставить ей ноль значило бы объявить «двойник сработал
    ровно в ноль» там, где двойника не было.
    """
    s = np.asarray(s_pnl, dtype=float)
    t = np.asarray(t_pnl, dtype=float)
    m = ~(np.isnan(s) | np.isnan(t))
    if not m.any():
        return None
    d = s[m] - t[m]
    return {"n": int(m.sum()),
            "median": round(float(np.median(d)), 5),
            "mean": round(float(np.mean(d)), 5),
            "s_beats_t": round(float(np.mean(s[m] > t[m])), 3),
            "same_sign": bool(np.median(d) * np.mean(d) > 0)}


def form_nulls(st_s, st_draws):
    """Где стоит дневная форма S среди форм книг-двойников.

    Три величины владельца: медиана дня, худший день, укус. У укуса
    «лучше» значит МЕНЬШЕ, и это сказано `lower_is_better`, а не спрятано
    в знаке.
    """
    if not st_s or not st_draws:
        return None
    out = {}
    for key, low in (("med", False), ("worst", False), ("bite", True)):
        vals = [d.get(key) for d in st_draws if d and d.get(key) is not None]
        out[key] = P.null_place(st_s.get(key), vals, lower_is_better=low)
    return out


def conc_nulls(c_s, c_draws):
    """Колонки концентрации против розыгрышей: без 3 лучших суток и без
    лучшего имени.

    Обязательна по уроку проекта — концентрация переворачивает знак: у
    бумажных DCA-книг 92.7 % итога легло в трое суток (20–22 августа), и
    превышение, живущее только в этом эпизоде, есть цена одного эпизода,
    а не выбор модели.
    """
    if not c_s or not c_draws:
        return None
    out = {}
    for key in ("tot", "no_top3_days", "no_best_name"):
        vals = [c.get(key) for c in c_draws if c and c.get(key) is not None]
        out[key] = P.null_place(c_s.get(key), vals)
    return out


# ------------------------------------------------------------- вердикты
#
# Все фразы ниже СОБИРАЮТСЯ ИЗ ЧИСЕЛ. Вердиктовая фраза, стоящая рядом с
# числом литералом, стареет молча и однажды противоречит своему же числу
# (урок Z1) — поэтому здесь нет ни одной готовой фразы «выбор работает».

def verdict_choice(nulls):
    """Убийца (1): имя выбора против имён того же часа.

    Живёт: медиана И среднее исхода позиции у руки S выше 95-го
    процентиля тех же величин по книгам-двойникам. Не выполнено хоть
    одно — имя, выбранное моделью, есть украшение, а деньги принадлежат
    часу рынка, лестнице и плечу.
    """
    need = ("median", "mean")
    have = {k: (nulls or {}).get(k) for k in need}
    missing = [k for k in need if not have.get(k)]
    if missing:
        return {"killed": None, "why": [
            "нуль по розыгрышам не посчитан по: " + ", ".join(missing)
            + " — это «не измерено», а не «не бьёт»"], "parts": have}
    parts = []
    for k in need:
        h = have[k]
        parts.append(
            f"{k}: S {h['real']:+.5f} против {NULL_Q:.0f}-го процентиля "
            f"{h['edge']:+.5f} ({h['reps']} розыгрышей, среднее "
            f"{h['mean']:+.5f}, {h['sigmas']} σ) — "
            + ("выше" if h["beats"] else "НЕ выше"))
    fails = [k for k in need if not have[k]["beats"]]
    if fails:
        return {"killed": True, "parts": parts, "why": [
            "выбор модели НЕ бьёт одновременную кросс-секцию своего часа: "
            + ", ".join(fails) + " не выше 95-го процентиля двойников — "
            "имя есть украшение, деньги принадлежат часу, лестнице и плечу"]}
    return {"killed": False, "parts": parts, "why": [
        "S выше 95-го процентиля двойников И по медиане, И по среднему — "
        "выбор имени несёт что-то сверх часа"]}


def verdict_pair(pos, days, boot):
    """Убийца (2): парная разность S − T.

    Медиана и среднее разности разошлись знаком — подпись короткой
    волатильности, и вердикта «выбор работает» нет ни при каком одном из
    двух. Разность считается и по позициям, и по суткам: заявка называет
    сутки, а расхождение знаком ловится на позициях, и требовать
    согласия обеих строже, чем требовать одной. Строгость названа здесь,
    а не спрятана.
    """
    if not pos or not days:
        return {"killed": None, "why": ["парная разность не посчитана: "
                                        "измеримых пар нет"], "parts": []}
    parts = [f"по позициям ({pos['n']}): медиана {pos['median']:+.5f}, "
             f"среднее {pos['mean']:+.5f}, S выше T в "
             f"{pos['s_beats_t'] * 100:.1f} %",
             f"по суткам ({days['n']}): медиана {days['median']:+.5f}, "
             f"среднее {days['mean']:+.5f}"]
    if boot:
        parts.append(f"парный бутстрап по суткам ({boot['days']} суток, "
                     f"{BOOT} повторов): медиана {boot['median']:+.5f}, "
                     f"интервал [{boot['lo']:+.5f}; {boot['hi']:+.5f}] — "
                     + ("накрывает ноль" if boot["covers_zero"]
                        else "ноль НЕ накрывает"))
    bad = []
    if not pos["same_sign"]:
        bad.append("медиана и среднее по позициям разошлись знаком")
    if not days["same_sign"]:
        bad.append("медиана и среднее по суткам разошлись знаком")
    if pos["median"] <= 0 or pos["mean"] <= 0:
        bad.append("разность по позициям не положительна")
    if boot is None:
        bad.append("бутстрапа нет: суток меньше трёх")
    elif boot["covers_zero"]:
        bad.append("интервал парного бутстрапа накрывает ноль")
    if bad:
        return {"killed": True, "parts": parts,
                "why": ["парная разность вердикта не даёт: "
                        + "; ".join(bad)]}
    return {"killed": False, "parts": parts,
            "why": ["парная разность S − T положительна по обеим "
                    "величинам, интервал бутстрапа ноль не накрывает"]}


def verdict_form(nulls):
    """Убийца (3): дневная форма при ОДНОЙ кассе.

    Медиана дня, худший день и укус руки S против 95-го процентиля тех
    же величин по книгам-двойникам. Это форма, по которой судит владелец:
    выбор, не покупающий формы, не покупает и продукта.
    """
    need = ("med", "worst", "bite")
    have = {k: (nulls or {}).get(k) for k in need}
    missing = [k for k in need if not have.get(k)]
    if missing:
        return {"killed": None, "parts": [],
                "why": ["дневная форма не посчитана по: "
                        + ", ".join(missing)]}
    parts = []
    for k in need:
        h = have[k]
        parts.append(f"{k}: S {h['real']:+.5f} против края {h['edge']:+.5f} "
                     + ("(лучше — меньше) " if h["lower_is_better"] else "")
                     + ("— лучше" if h["beats"] else "— НЕ лучше"))
    worse = [k for k in need if not have[k]["beats"]]
    if worse:
        return {"killed": True, "parts": parts,
                "why": ["дневная форма выбора не лучше формы двойников по: "
                        + ", ".join(worse)]}
    return {"killed": False, "parts": parts,
            "why": ["дневная форма S лучше 95 % книг-двойников по медиане "
                    "дня, худшему дню и укусу"]}


def verdict_conc(nulls):
    """Убийца (4): колонка «без 3 лучших суток».

    Если превышение S над двойниками живёт только в 20–22 августа и без
    этих суток уходит в полосу нуля — выбор стоил одного эпизода. Рядом
    печатается «без лучшего имени»: концентрация бывает и по имени.
    """
    a = (nulls or {}).get("no_top3_days")
    if not a:
        return {"killed": None, "parts": [],
                "why": ["колонка «без 3 лучших суток» не посчитана"]}
    b = (nulls or {}).get("no_best_name")
    parts = [f"без 3 лучших суток: S {a['real']:+.2f} $ против края "
             f"{a['edge']:+.2f} $ — " + ("выше" if a["beats"] else "НЕ выше")]
    if b:
        parts.append(f"без лучшего имени: S {b['real']:+.2f} $ против края "
                     f"{b['edge']:+.2f} $ — "
                     + ("выше" if b["beats"] else "НЕ выше"))
    if not a["beats"]:
        return {"killed": True, "parts": parts,
                "why": ["без трёх лучших суток превышение S над двойниками "
                        "уходит в полосу нуля — выбор стоил одного эпизода"]}
    return {"killed": False, "parts": parts,
            "why": ["превышение S держится и без трёх лучших суток"]}


def verdict_cover(cover, n_pairs):
    """Измеримость — РАНЬШЕ четырёх убийц.

    Доля позиций, у которых двойник нашёлся и имеет бары в окне.
    Непокрытые суть «не измерено», и вердикт выносится по измеренным с
    названным числом, а не по всем с нулями вместо пропусков.
    """
    if n_pairs <= 0:
        return {"ok": False, "why": ["измеримых пар ноль — вердикта нет"]}
    ok = cover >= COVER_MIN
    return {"ok": bool(ok), "cover": round(float(cover), 4),
            "pairs": int(n_pairs),
            "why": [f"двойник найден и имеет бары у {cover * 100:.1f} % "
                    f"пар «позиция × розыгрыш» ({n_pairs}) при пороге "
                    f"{COVER_MIN * 100:.0f} % — "
                    + ("покрытие достаточное"
                       if ok else "вердикт ТОЛЬКО по измеренным, "
                                  "непокрытые суть «не измерено»")]}


def verdict(cover, killers):
    """Общий ответ механики, собранный из четырёх убийц и измеримости.

    Порядок дешевизны — тот, что назван заявкой. Хоть один убийца сработал
    — механика убита; ни один не сработал и все посчитаны — жива; что-то
    не посчитано — «не измерено», и это третий ответ, а не второй.
    """
    parts = []
    killed = [k for k in killers if k and k.get("killed") is True]
    unknown = [k for k in killers if k and k.get("killed") is None]
    for k in killers:
        parts += (k or {}).get("why") or []
    if not cover.get("ok"):
        parts = cover["why"] + parts
    if killed:
        head = (f"УБИТА: сработало убийц {len(killed)} из "
                f"{len(killers)} названных заявкой")
        res = True
    elif unknown:
        head = (f"НЕ ИЗМЕРЕНО: убийц не сработало, но {len(unknown)} из "
                f"{len(killers)} не посчитаны — молчание не есть ответ")
        res = None
    else:
        head = ("ЖИВА: ни один из четырёх убийц не сработал — выбор модели "
                "бьёт одновременную кросс-секцию своего часа ПОСЛЕ лестницы")
        res = False
    return {"killed": res, "head": head, "why": parts}


# ------------------------------------------------------------- калибровка
#
# Без калибровочной пары сломанное чтение баров двойника (пустое окно →
# исход прочерком → книга двойника из двух позиций) выглядит в точности
# как «выбор работает». В проекте это уже случалось дважды.

def bars_of(prices, t0, vol=1000.0, wick=0.0005, step=60):
    """Минутные бары из ряда цен: (t, open, high, low, close, объём)."""
    out = []
    for i, p in enumerate(prices):
        p = float(p)
        out.append((t0 + i * step, p, p * (1.0 + wick), p * (1.0 - wick),
                    p, vol))
    return out


def walk(rng, n, sigma=0.0015, start=100.0):
    """Случайное блуждание — нуль честной формы."""
    return list(float(start) * np.exp(np.cumsum(rng.normal(0.0, sigma, n))))


def lift_to_take(prices, at_i, up=0.12, span=60):
    """Подсаженный ход: с бара `at_i` цена идёт ВВЕРХ до тейка за час.

    Подделка обязана выглядеть как живая: подъём не ступенькой, а
    равномерным ходом, дальше — прежний путь, поднятый на ту же долю.
    Легла ли она — проверяется числом (максимум после входа выше входа на
    `up`), а не верой.
    """
    out = list(prices)
    base = float(out[at_i])
    for k in range(1, int(span) + 1):
        i = at_i + k
        if i >= len(out):
            break
        out[i] = base * (1.0 + up * k / float(span))
    for i in range(at_i + int(span) + 1, len(out)):
        out[i] = float(out[i]) * (1.0 + up)
    return out
