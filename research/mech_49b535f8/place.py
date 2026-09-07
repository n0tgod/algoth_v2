#!/usr/bin/env python3
"""
Механика 49b535f8 — ГДЕ усреднять: места доливов DCA-лестницы.

Здесь живут ЧИСТЫЕ функции размещения и вердикта; чтение журналов,
баров и печать отчёта — в `run_place.py`. Разделение не косметическое:
подделка негативного контроля обязана попадать в правило, а не в
обвязку, и правило должно быть проверяемо без единого байта записи.

Вопрос механики один: **место доливов** при неизменном всём остальном.
Позиции — те же гейтованные лонги журнала листов, что у D2/D3; вход,
тейк (mfe модели), пол капитуляции 0.10, срок 72 ч, забор §5
(`SURVIVE_MULT` 2.0, тиры D0) и равные веса — общие для всех рук.
Меняются ТОЛЬКО цены рунгов:

* **S** — структурные уровни T4 (`ladder.structural_rungs` поверх
  `run_d2.build_levels`), правило живых бумажных книг;
* **R** — нуль §8.6: случайные уровни ТОЙ ЖЕ глубины и ТОЙ ЖЕ формы
  (нижний рунг закреплён на `d_max` структурной лестницы, число рунгов
  и веса те же, зазор ≥ `MIN_ADD_GAP`), плечо ВЗЯТО У S. Зерно числом;
* **G** — σ-сетка (`ladder.sigma_rungs`, шаг 2 суточные σ, как в
  `run_dca.py`) со СВОЕЙ глубиной и своим §5-плечом: вопрос о КАРКАСЕ;
* **G′** — тот же σ-каркас (равный шаг), приведённый к глубине
  структурной лестницы, с плечом S: вопрос о МЕСТЕ при том же плече.

**G′ равномерен, и это следствие, а не выбор.** Шаг σ-сетки равный, и
приведение равного шага к чужой глубине снова даёт равный шаг; σ у G′
не остаётся ни в одном числе. Иначе разность S − G мешала бы «место» с
«плечом»: у σ-сетки своя глубина, а D3 намерил, что плечо и есть
источник и дохода, и хвоста.

**Розыгрыш нуля равномерен по множеству допустимых лестниц той же
формы, а не «случайные цены с отбраковкой».** В логарифме цены
лестница есть набор 0 = u₀ < u₁ < … < u_m = U с приращениями не меньше
c = −ln(1 − зазор), где U = −ln(1 − d_max). Свободный остаток
U − m·c раскладывается по m приращениям равномерно (Дирихле единиц), и
это ТОЧНО равномерный розыгрыш допустимой лестницы: отбраковки нет,
неудачных розыгрышей нет, глубина совпадает с точностью машины.
Существование хотя бы одной такой лестницы гарантировано самой S: её
зазоры уже не меньше `min_gap`, значит U ≥ m·c.

**Зазор у σ-каркаса не спрашивается.** Правило «не дважды на одном
уровне» (§R1) принадлежит СТРУКТУРНОМУ правилу; σ-сетка в `run_dca.py`
никакого зазора не знает. Навязать его сетке значило бы сравнивать не
каркасы, а свою правку каркаса. Доля лестниц G′, чей верхний зазор
оказался мельче `MIN_ADD_GAP`, печатается числом.

**Где розыгрыш вырождается — там он и объявляется вырожденным.** При
двух рунгах (база плюс один долив) промежуточных мест нет вовсе, а
нижний рунг закреплён на `d_max`, — значит R совпадает с S ТОЖДЕСТВЕННО
и парная разность равна нулю не потому, что место не важно, а потому,
что выбирать было не из чего. Такие позиции считаются числом и в
парное сравнение (1) не входят — по тому же правилу, по которому в него
не входят позиции без лестницы вовсе (задание: «обе руки
вырождаются»). Их включение подарило бы нулю ровно тот вердикт,
который мы и ждём («S ≈ R»), причём даром.

Единица везде — доля капитала позиции (`pnl_frac` ядра). Ядро одно:
`research/dca_ladder/ladder.py`; второй копии забора, долива и
симуляции здесь нет.
"""

import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)

for _p in (HERE, os.path.join(RESEARCH, "a4_cointegration"),
           os.path.join(RESEARCH, "dca_ladder"),
           os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "s9_sweep"),
           os.path.join(RESEARCH, "t4_structure")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ladder as L                                           # noqa: E402
import run_d2 as D2                                          # noqa: E402
import run_d5 as D5                                          # noqa: E402
import run_dca as D1                                         # noqa: E402

# --- объявленная сетка: чужие величины берутся У ХОЗЯЕВ -------------------
#
# Ни одно из этих чисел не назначено здесь. Повтор числом означал бы, что
# механика судит ячейку, которой у D2/D1 нет, а обе таблицы выглядели бы
# исправными (урок «одно ядро»).
N_RUNGS = D2.N_RUNGS                  # 4: база плюс до трёх доливов
WEIGHTS = D2.WEIGHTS                  # равные доли нотионала
MIN_GAP = D2.MIN_ADD_GAP              # ≥1.5 % ниже прошлого рунга (§R1)
SURVIVE_MULT = D2.SURVIVE_MULT        # забор §5
FLOOR_FRAC = D2.FLOOR_FRAC            # пол капитуляции §6
FLAT_MMR = D2.FLAT_MMR                # делистнутой ноге (§10 модальный)
SPACING_SIG = D1.SPACING_SIG          # σ-сетка: рунг каждые 2 суточные σ
SIG_FLOOR_Q = D1.SIG_FLOOR_Q          # пол σ — 10-й процентиль сечения

# Абсолютный пол σ. В `run_dca.py` он стоит литералом внутри `run`
# (`floor = max(floor, 0.005)`) и импортируемого имени не имеет, поэтому
# повторён здесь ОДИН раз и с указанием хозяина, а не размножен по коду.
ABS_SIG_FLOOR = 0.005

# --- пороги вердикта: чужие, объявлены до прогона -------------------------
#
# Убийца (1) — правило §9 спеки 14 дословно: «структурные уровни выше
# 95-го процентиля случайных по нетто И по укусу».
NULL_Q = 95.0
# Укус — величина ПЛОХОГО: |худшая| / медиана прибыльной. «Выше по
# укусу» у меры плохого означает МЕНЬШЕ, поэтому сравнение идёт с
# ЗЕРКАЛЬНЫМ процентилем (`100 − NULL_Q`, то есть с пятым): S обязана
# кусать слабее, чем 95 % розыгрышей. Прочтение названо здесь, а не
# выбрано молча, и живёт одной строкой в `null_place` — второй порог
# укуса, стоящий отдельным числом, однажды разошёлся бы с этим.
# Убийца (2) — задание: полоса неразличимости каркасов.
GRID_BAND = 0.0010                    # ±0.10 % капитала по медиане S − G
GRID_FRAC_LO = 0.45
GRID_FRAC_HI = 0.55

DRAWS = 100                           # розыгрышей нуля (задание: ≥ 100)
SEED = 20260907                       # зерно ЧИСЛОМ (урок R3)
BOOT = 2000                           # повторов парного бутстрапа по дням


# ------------------------------------------------------------ геометрия

def log_gap(min_gap):
    """Минимальный зазор в логарифме цены: p ≤ p_prev·(1 − зазор)."""
    return -math.log1p(-float(min_gap))


def gap_ok(rungs, min_gap=MIN_GAP, tol=1e-9):
    """Лестница соблюдает зазор §R1 — тем же неравенством, что ядро.

    Предикат один на розыгрыш и на проверку: `ladder.structural_rungs`
    берёт уровень, когда `(prev − p)/prev ≥ min_gap`, и тест закрепляет,
    что выход ядра этот предикат проходит. Второе неравенство «почти
    такое же» однажды разошлось бы с первым.
    """
    for prev, p in zip(rungs, rungs[1:]):
        if not (p > 0 and prev > 0):
            return False
        if (prev - p) / prev < min_gap - tol:
            return False
    return True


def depth_of(entry, rungs):
    """Глубина лестницы долей цены входа. Один рунг — глубины нет (0)."""
    if entry <= 0 or len(rungs) < 2:
        return 0.0
    return (entry - rungs[-1]) / entry


def draw_rungs(entry, k, d_max, rng, min_gap=MIN_GAP):
    """Случайная лестница ТОЙ ЖЕ глубины и формы (нуль §8.6).

    `k` — сколько рунгов всего (вместе с базой), `d_max` — глубина
    структурной лестницы. Нижний рунг ЗАКРЕПЛЁН: `entry·(1 − d_max)`.
    Промежуточные тянутся равномерно по множеству допустимых лестниц
    (см. докстроку модуля). Возвращает список цен по убыванию (первая —
    вход) либо None, если лестницы такой формы не существует.
    """
    if entry <= 0 or k < 2 or not (0.0 < d_max < 1.0):
        return None
    m = k - 1                                   # доливов
    U = -math.log1p(-d_max)
    c = log_gap(min_gap)
    rem = U - m * c
    if rem < -1e-12:
        return None                             # формы не существует
    rem = max(rem, 0.0)
    if m == 1:
        step = np.array([rem])
    else:
        step = rng.dirichlet(np.ones(m)) * rem
    u = np.cumsum(step + c)
    # Нижний рунг ставится ТОЧНО на глубину структурной лестницы, а не
    # «почти»: накопленная сумма приращений имеет свою ошибку, и уплыви
    # глубина даже на 1e-12, розыгрыш отвечал бы на другой вопрос —
    # «глубже или мельче», а не «где».
    px = [float(entry * math.exp(-x)) for x in u[:-1]]
    return [float(entry)] + px + [float(entry * (1.0 - d_max))]


def draws_for(entry, k, d_max, n_draws, leg_id, seed=SEED, min_gap=MIN_GAP):
    """Розыгрыши позиции, назначенные ЗАРАНЕЕ парой (зерно, номер ноги).

    Зерно ЧИСЛОМ и от порядка обработки не зависит: символы читаются в
    порядке словаря, а нуль обязан воспроизводиться при любом порядке и
    при любом `--limit`. Розыгрыши идут подряд из одного потока, поэтому
    прогон на 20 розыгрышей есть ПРЕФИКС прогона на 100.
    """
    rng = np.random.default_rng([int(seed), int(leg_id)])
    out = []
    for _ in range(int(n_draws)):
        out.append(draw_rungs(entry, k, d_max, rng, min_gap))
    return out


def even_rungs(entry, k, d_max):
    """σ-каркас, приведённый к чужой глубине: равный шаг по цене (G′).

    Тот же шаг, что у `ladder.sigma_rungs` (равные доли цены), только
    масштаб выбран так, чтобы нижний рунг сел на `d_max` структурной
    лестницы. σ в результате не остаётся — см. докстроку модуля.
    """
    if entry <= 0 or k < 2 or not (0.0 < d_max < 1.0):
        return None
    step = d_max / (k - 1)
    return [float(entry * (1.0 - i * step)) for i in range(k)]


def sigma_grid(entry, sig_day, n_rungs=N_RUNGS, spacing=SPACING_SIG):
    """σ-сетка своей глубины (рука G). Нет σ — НЕТ РУКИ, а не ноль.

    Замороженный ряд имеет σ = 0, и сетка с нулевым шагом получила бы
    нулевую глубину, а забор §5 при нулевой глубине выдаёт потолок плеча
    (ловушка S1 в новом костюме). Поэтому «σ не измерена» доезжает до
    вызывающего пропуском: прочерк — не ноль.
    """
    if entry <= 0 or sig_day is None or not (sig_day > 0):
        return None, None
    try:
        prices, d_max = L.sigma_rungs(entry, sig_day, n_rungs, spacing)
    except ValueError:
        return None, None                      # сетка глубже 100 %
    if not (0.0 < d_max < 1.0):
        return None, None
    return prices, d_max


def sigma_day_of(sigma_bp):
    """Суточная σ долей цены из минутной σ в б.п. — линейкой D5."""
    return D5.sigma_day(sigma_bp)


def sigma_floor(sigmas, q=SIG_FLOOR_Q, abs_floor=ABS_SIG_FLOOR):
    """Пол σ ИЗ САМОГО СЕЧЕНИЯ (урок S1), не из головы.

    `sigmas` — суточные σ имён сечения (долей цены). Пол — `q`-квантиль
    сечения, но не ниже абсолютного: тонкое по σ имя иначе получило бы
    бритвенную лестницу и максимум плеча. Сечения нет — остаётся
    абсолютный пол, и это НЕ то же самое, что «пола нет».
    """
    v = np.asarray([s for s in sigmas if s is not None and s == s and s > 0],
                   dtype=float)
    if len(v) < D1.MIN_SECTION:
        return float(abs_floor)
    return float(max(float(np.quantile(v, q)), abs_floor))


def fence_lev(rungs, entry, d_max, look, mult=SURVIVE_MULT,
              weights=WEIGHTS):
    """Плечо забора §5 и лестница, которую оно допускает.

    Поведение при отказе — дословно D2 (`_process_leg`): забор не
    выбрасывает позицию, а роняет её в одиночный вход 1×. Отсюда состав
    позиций у всех рук ОДИН, и пара чиста.
    """
    if rungs is None or len(rungs) < 2:
        return 1.0, [float(entry)]
    if not (d_max > 0):
        return 1.0, [float(entry)]
    lev = L.max_leverage(rungs, weights[:len(rungs)], 1.0, entry, d_max,
                         look, mult)
    if lev <= 0:
        return 1.0, [float(entry)]
    return float(lev), list(rungs)


def sim(hold, rungs, lev, look, take_px):
    """Реплей одной руки ЯДРОМ. Единственная дорога до `simulate_dca`."""
    w = WEIGHTS[:len(rungs)]
    return L.simulate_dca(hold, rungs, w, 1.0, lev, look(1.0 * lev),
                          take_px=take_px, floor_frac=FLOOR_FRAC)


def over_tier(tiers, lev):
    """Плечо выше предела тира площадки? Нет справочника — не знаем (None).

    Обе руки считаются БЕЗ `lev_lookup` — как D2/D3, прогнанные до
    правки ядра 2026-09-05, иначе абсолютные числа разошлись бы с
    опубликованными. Пара от этого честна (правило одно у всех рук), но
    неточность названа и печатается долей по каждой руке.
    """
    cap = L.lev_cap_for_notional(tiers, 1.0 * lev, flat=None)
    if cap is None:
        return None
    return bool(lev > float(cap) + 1e-9)


# ------------------------------------------------------------ одна позиция

def position_arms(hold, entry, rungs_s, take_px, look, sig_day,
                  n_draws=DRAWS, leg_id=0, seed=SEED, tiers=None):
    """Все руки одной позиции. Возвращает словарь величин, а не отчёт.

    Плечо S считается ОДИН раз и передаётся рукам R и G′: они отвечают
    на вопрос «где», и плечо у них обязано быть тем же, иначе разность
    смешает место с рычагом (D3: рычаг и есть источник дохода и хвоста).
    У G плечо своё — она отвечает на вопрос «какой каркас».
    """
    lev_s, rungs_s = fence_lev(rungs_s, entry, depth_of(entry, rungs_s),
                               look)
    # Число рунгов и глубина берутся ПОСЛЕ забора: отказавший забор
    # роняет лестницу в одиночный вход (правило D2), и население нуля
    # обязано считаться по той лестнице, которой торговали, а не по той,
    # которую хотели.
    k = len(rungs_s)
    d_max = depth_of(entry, rungs_s)
    res = {"k": k, "d_max": d_max, "lev_s": lev_s,
           "degenerate": k < 3, "no_ladder": k < 2}
    res["S"] = sim(hold, rungs_s, lev_s, look, take_px)
    res["over_S"] = over_tier(tiers, lev_s)

    # --- G: σ-сетка своей глубины и своего плеча
    g_rungs, g_depth = sigma_grid(entry, sig_day)
    if g_rungs is None:
        # Причина отсутствия руки НАЗЫВАЕТСЯ: «σ не измерена» и «сетка
        # глубже 100 % цены» — разные вещи, и обе не ноль. Сложи их в
        # молчаливый пропуск, и доля позиций без σ-каркаса читалась бы
        # как свойство данных, а не как граница самого каркаса.
        res["G"] = None
        res["lev_g"] = None
        res["over_G"] = None
        res["g_why"] = ("нет σ" if sig_day is None or not (sig_day > 0)
                        else "сетка глубже 100 %")
    else:
        lev_g, g_rungs = fence_lev(g_rungs, entry, g_depth, look)
        res["G"] = sim(hold, g_rungs, lev_g, look, take_px)
        res["lev_g"] = lev_g
        res["d_max_g"] = depth_of(entry, g_rungs)
        res["over_G"] = over_tier(tiers, lev_g)

    # --- G′: тот же каркас на глубине S, плечо S
    if k < 2:
        res["GP"] = res["S"]                 # лестницы нет — рук нет
        res["gp_thin_gap"] = False
    else:
        gp = even_rungs(entry, k, d_max)
        res["GP"] = sim(hold, gp, lev_s, look, take_px)
        res["gp_thin_gap"] = not gap_ok(gp)

    # --- R: розыгрыши нуля §8.6
    if k < 3:
        # Два рунга: промежуточных мест нет, нижний закреплён — розыгрыш
        # ТОЖДЕСТВЕН S. Повторный реплей дал бы те же числа ценой
        # 100 симуляций на позицию; равенство закреплено тестом.
        res["R"] = [res["S"]] * int(n_draws)
        res["r_identical"] = True
    else:
        res["r_identical"] = False
        out, failed = [], 0
        for rg in draws_for(entry, k, d_max, n_draws, leg_id, seed):
            if rg is None:
                # Розыгрыш не сложился (формы не существует) — подстановка
                # S тянет пару к нулю, то есть в пользу вердикта
                # «украшение». Поэтому такие случаи СЧИТАЮТСЯ и
                # печатаются: молчаливая замена была бы подарком нулю.
                failed += 1
            out.append(res["S"] if rg is None else
                       sim(hold, rg, lev_s, look, take_px))
        res["R"] = out
        res["draw_failed"] = failed
    return res


# ------------------------------------------------------------ сводки

def cell_stats(pnl, liq=None, lev=None, over=None, exits=None):
    """Сводка руки. Медиана И среднее рядом — одной из них мало.

    Расхождение их знака есть подпись короткой волатильности (Z1, F);
    печатать одну значит терять именно ту форму, которой умерли четыре
    гипотезы. Пусто — `n: 0` и никаких прочерков, выданных за числа.
    """
    p = np.asarray([x for x in pnl if x == x], dtype=float)
    if len(p) == 0:
        return {"n": 0}
    win = p[p > 0]
    med_win = float(np.median(win)) if len(win) else float("nan")
    out = {
        "n": int(len(p)),
        "median": round(float(np.median(p)), 5),
        "mean": round(float(np.mean(p)), 5),
        "green": round(float(np.mean(p > 0)), 3),
        "worst": round(float(np.min(p)), 4),
        "bite": (round(abs(float(np.min(p))) / med_win, 2)
                 if med_win and med_win > 0 else None),
    }
    if liq is not None:
        out["liq_freq"] = round(float(liq) / len(p), 5)
    if lev is not None:
        lv = np.asarray([x for x in lev if x == x], dtype=float)
        out["median_lev"] = (round(float(np.median(lv)), 2) if len(lv)
                             else None)
        out["frac_1x"] = (round(float(np.mean(lv <= 1.0 + 1e-9)), 3)
                          if len(lv) else None)
    if over is not None:
        known = [x for x in over if x is not None]
        out["over_tier"] = (round(float(np.mean(known)), 4) if known
                            else None)
    if exits is not None:
        out["exits"] = dict(exits)
    return out


def null_place(real, draws, lower_is_better=False, q=NULL_Q):
    """Где стоит рука S среди розыгрышей: процентиль И расстояние в σ.

    Вердикт §9 выносится по процентилю, но при сотне розыгрышей
    процентиль шумен сам по себе (R3: отношение к нему гуляет втрое),
    поэтому рядом печатается расстояние от среднего розыгрышей. Обе
    величины — не роскошь: по одной из них уже ошибались.

    `lower_is_better` — для меры ПЛОХОГО (укус): «выше по укусу»
    означает «кусает слабее», то есть ниже 5-го процентиля.
    """
    v = np.asarray([x for x in draws if x is not None and x == x],
                   dtype=float)
    if len(v) == 0 or real is None or real != real:
        return None
    qq = (100.0 - q) if lower_is_better else q
    edge = float(np.percentile(v, qq))
    sd = float(np.std(v))
    beats = (float(real) < edge) if lower_is_better else (float(real) > edge)
    # Ранг руки среди розыгрышей — та же величина без сглаживания:
    # процентиль интерполирует, ранг считает штуки.
    rank = (float(np.mean(v > float(real))) if lower_is_better
            else float(np.mean(v < float(real))))
    return {"reps": int(len(v)), "real": round(float(real), 5),
            "mean": round(float(np.mean(v)), 5),
            "edge": round(edge, 5),
            "min": round(float(np.min(v)), 5),
            "max": round(float(np.max(v)), 5),
            "beats": bool(beats),
            "rank": round(rank, 3),
            "sigmas": (round((float(real) - float(np.mean(v))) / sd, 2)
                       if sd > 0 else None),
            "lower_is_better": bool(lower_is_better)}


def draw_pool(s_pnl, r_pnl):
    """Сводка S и РАСПРЕДЕЛЕНИЕ розыгрышей по трём величинам вердикта.

    `s_pnl` — исходы руки S по позициям, `r_pnl` — их же по каждому
    розыгрышу (`(позиций × розыгрышей)`). Каждый розыгрыш есть ЦЕЛАЯ
    книга: медиана, среднее и укус считаются ВНУТРИ розыгрыша по всем
    позициям, и только потом сравниваются с S. Считать наоборот (усреднить
    розыгрыши по позиции, а потом взять медиану) значило бы сравнивать S
    со средним из ста книг — величиной, которой ни один розыгрыш не
    равен, и разброс которой вдесятеро уже.

    Одна дорога и у боевого прогона, и у калибровки: калибровка, идущая
    мимо проверяемого пути, проверяет не его.
    """
    s = np.asarray([x for x in s_pnl if x == x], dtype=float)
    if len(s) == 0 or not r_pnl:
        return None
    r = np.asarray(r_pnl, dtype=float)
    if r.ndim != 2 or r.shape[0] != len(s_pnl):
        raise ValueError("розыгрыши не выровнены по позициям")
    real = cell_stats(s)
    med, mean, bite = [], [], []
    for j in range(r.shape[1]):
        st = cell_stats(r[:, j])
        med.append(st.get("median"))
        mean.append(st.get("mean"))
        bite.append(st.get("bite"))
    nulls = {
        "median": null_place(real.get("median"), med),
        "mean": null_place(real.get("mean"), mean),
        "bite": null_place(real.get("bite"), bite, lower_is_better=True),
    }
    return {"n": int(len(s)), "draws": int(r.shape[1]), "real": real,
            "nulls": nulls,
            "draw_median_of_medians": round(float(np.median(med)), 5),
            "draw_median_of_means": round(float(np.median(mean)), 5)}


def paired_day_boot(days_a, days_b, n_boot=BOOT, seed=SEED):
    """Парный бутстрап по СУТКАМ: интервал разности итогов дня.

    Пересэмплируются целые ПАРЫ суток: руки торгуют одни и те же дни, и
    независимый ресэмпл разорвал бы связь, завысив разброс, — то есть
    сделал бы вывод «различия нет» слишком лёгким (тот же довод, что в
    `r5_backtest/compare_arms.py`).
    """
    keys = sorted(set(days_a) & set(days_b))
    if len(keys) < 3:
        return None
    a = np.array([days_a[k] for k in keys], dtype=float)
    b = np.array([days_b[k] for k in keys], dtype=float)
    d = a - b
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(keys), size=(int(n_boot), len(keys)))
    med = np.median(d[idx], axis=1)
    lo, hi = np.percentile(med, [2.5, 97.5])
    return {"days": len(keys), "median": round(float(np.median(d)), 5),
            "mean": round(float(np.mean(d)), 5),
            "lo": round(float(lo), 5), "hi": round(float(hi), 5),
            "covers_zero": bool(lo <= 0.0 <= hi)}


# ------------------------------------------------------------ вердикты

def verdict_null(nulls):
    """Убийца (1) — правило §9 дословно, собранное ИЗ ЧИСЕЛ.

    Живёт: S выше 95-го процентиля розыгрышей И по медиане, И по
    среднему, И кусает слабее 95 % розыгрышей. Не выполнено хоть одно —
    структурные уровни суть украшение.

    Фраза выводится из величин, а не стоит рядом с ними литералом: та,
    что стоит рядом, однажды противоречит своему же числу (урок Z1).
    """
    need = ("median", "mean", "bite")
    have = {k: (nulls or {}).get(k) for k in need}
    missing = [k for k in need if not have.get(k)]
    if missing:
        return {"killed": None, "why": [
            "нуль §8.6 не посчитан по: " + ", ".join(missing)
            + " — это «не измерено», а не «не бьёт»"], "parts": have}
    fails = [k for k in need if not have[k]["beats"]]
    parts = []
    for k in need:
        h = have[k]
        word = "кусает слабее" if h["lower_is_better"] else "выше"
        parts.append(f"{k}: {h['real']:+.5f} против границы {h['edge']:+.5f} "
                     f"({'' if h['beats'] else 'НЕ '}{word}), "
                     f"{h['sigmas']} σ от среднего розыгрышей")
    if fails:
        why = ("убийца 1 (нуль §8.6): структурные уровни не выше 95-го "
               "процентиля случайных по " + ", ".join(fails)
               + " — «стратегический уровень» есть украшение")
    else:
        why = ("структурные уровни выше 95-го процентиля случайных по "
               "медиане, среднему И укусу — правило §9 выполнено")
    return {"killed": bool(fails), "why": [why], "parts": parts,
            "fails": fails}


def verdict_grid(med_diff, frac_better, n):
    """Убийца (2) — каркасы неразличимы: полоса задана заданием.

    Убивает, когда И медиана парной разности лежит внутри ±`GRID_BAND`,
    И доля выборов, где S выше G, лежит в полосе 0.45–0.55.
    """
    if n == 0 or med_diff is None or frac_better is None:
        return {"killed": None,
                "why": ["сравнение с σ-сеткой не посчитано — «не "
                        "измерено», а не «не различимы»"]}
    in_band = abs(float(med_diff)) <= GRID_BAND
    in_frac = GRID_FRAC_LO <= float(frac_better) <= GRID_FRAC_HI
    killed = bool(in_band and in_frac)
    why = (f"медиана S − G {med_diff*100:+.3f} % капитала "
           f"({'внутри' if in_band else 'вне'} полосы "
           f"±{GRID_BAND * 100:.2f} %), "
           f"S выше G у {frac_better*100:.1f} % выборов "
           f"({'внутри' if in_frac else 'вне'} полосы "
           f"{GRID_FRAC_LO:.2f}–{GRID_FRAC_HI:.2f}) на {n} позициях — "
           + ("выбор каркаса не различим, структурная машинерия T4 "
              "живым книгам не нужна" if killed else
              "каркасы различимы хотя бы по одной из двух величин"))
    return {"killed": killed, "why": [why], "in_band": in_band,
            "in_frac": in_frac}


# Что у меры считается «лучше»: у медианы дня, доли зелёных и просадки —
# больше, у укуса — меньше. Таблица объявлена ЗДЕСЬ, а не решается по
# месту в трёх ветках `if`: третья ветка однажды считала бы иначе.
FORM_BETTER_HIGH = {"med": True, "green": True, "bite": False, "dd": True}


def verdict_form(st_s, others):
    """Убийца (3) — дневная форма: S не лучше ни по одной из четырёх мер.

    `others` — словарь имя → сводка `stability.stats` тех рук, с
    которыми сравнивается S (задание: σ-сетка G и МЕДИАННЫЙ розыгрыш R).
    Убивает, когда ни по медиане дня, ни по доле зелёных, ни по укусу,
    ни по просадке S не превосходит ОБЕ руки сразу.
    """
    if not st_s or not others or not all(others.values()):
        return {"killed": None,
                "why": ["дневная форма посчитана не у всех рук — «не "
                        "измерено», а не «не лучше»"], "parts": []}
    wins, parts = [], []
    for m, high in FORM_BETTER_HIGH.items():
        a = st_s.get(m)
        if a is None:
            parts.append(f"{m}: у S не посчитано")
            continue
        ok, txt = True, []
        for nm, st in others.items():
            b = st.get(m)
            if b is None:
                ok = False
                txt.append(f"{nm} —")
                continue
            better = (a > b) if high else (a < b)
            ok = ok and better
            txt.append(f"{nm} {b}")
        parts.append(f"{m}: S {a} против " + ", ".join(txt)
                     + (" — лучше обеих" if ok else " — не лучше обеих"))
        if ok:
            wins.append(m)
    killed = not wins
    why = ("убийца 3 (дневная форма): S не лучше σ-сетки и медианного "
           "розыгрыша НИ ПО ОДНОЙ из четырёх мер — «где усреднять» не "
           "покупает формы, по которой судит владелец"
           if killed else
           "S лучше обеих рук по: " + ", ".join(wins))
    return {"killed": killed, "why": [why], "parts": parts, "wins": wins}


# ------------------------------------------------------------ калибровка

def _bars(prices, t0=1_770_000_000, vol=1000.0, wick=0.0005):
    """Минутные бары из ряда цен: (t, open, high, low, close, объём)."""
    out = []
    for i, p in enumerate(prices):
        p = float(p)
        out.append((t0 + i * 60, p, p * (1.0 + wick), p * (1.0 - wick),
                    p, vol))
    return out


def _path_bounce(entry, bounce_px, take, hold_n=600):
    """Путь, отскакивающий РОВНО от подсаженного уровня и уходящий в тейк.

    Цена сходит вниз чуть ниже подсаженного уровня `bounce_px`,
    разворачивается и едет до тейка. Самый глубокий рунг лестницы при
    этом НЕ достаётся — и в этом весь смысл: место доливов решает, много
    ли капитала успело встать по дешёвой цене к моменту разворота. Рунги
    S стоят на точке разворота, случайные — где придётся.
    """
    down = list(np.linspace(entry, bounce_px, hold_n // 2))
    up = list(np.linspace(bounce_px, take * 1.02, hold_n - len(down)))
    return down + up


def _walk(rng, n, sigma=0.0015, start=100.0):
    return list(start * np.exp(np.cumsum(rng.normal(0.0, sigma, n))))


def calibrate(n_draws=DRAWS, seed=SEED, planted_n=20, noise_n=60,
              hold_n=600):
    """Калибровочная пара: найти подсаженное и промолчать на шуме.

    Без неё сломанное чтение уровней (пустой список → одиночный вход)
    выглядит в точности как «уровни не важны», и это в проекте уже
    случалось дважды. Обе половины обязательны и считаются ТОЙ ЖЕ
    дорогой, что боевой прогон (`position_arms` → `draw_pool` →
    `verdict_null`): калибровка, идущая мимо проверяемого пути, проверяет
    не его.

    * **подсаженное** — путь отскакивает от уровня, на котором стоит
      рунг S; S обязана бить розыгрыши по правилу §9;
    * **шум** — случайные блуждания и случайные уровни; S обязана лечь
      ВНУТРИ полосы розыгрышей.
    """
    look = (lambda notl: 0.005)
    rng = np.random.default_rng(int(seed) + 1)

    # --- половина 1: подсаженные уровни
    s_pl, r_pl = [], []
    for i in range(int(planted_n)):
        entry = 100.0 * float(1.0 + rng.normal(0.0, 0.01))
        # уровни подсажены с дрожанием: подставной набор, повторяющий
        # себя числом в числе, отличим от живого и однажды прячет ошибку
        # (урок «подставной артефакт обязан выглядеть как живой»).
        d1 = float(rng.uniform(0.03, 0.05))
        d2 = d1 + float(rng.uniform(0.03, 0.05))
        d3 = d2 + float(rng.uniform(0.03, 0.05))
        rungs = [entry] + [entry * (1.0 - d) for d in (d1, d2, d3)]
        take = entry * float(1.0 + rng.uniform(0.02, 0.05))
        hold = _bars(_path_bounce(entry, rungs[2] * 0.998, take, hold_n))
        a = position_arms(hold, entry, list(rungs), take, look, None,
                          n_draws=n_draws, leg_id=i, seed=seed)
        s_pl.append(a["S"]["pnl_frac"])
        r_pl.append([x["pnl_frac"] for x in a["R"]])
    planted = draw_pool(s_pl, r_pl)

    # --- половина 2: ОБМЕНИВАЕМОСТЬ. Лестница «S» на случайных блужданиях
    # рисуется ТЕМ ЖЕ законом, что и розыгрыши, — значит по построению
    # она есть один из них, и любое систематическое превосходство здесь
    # означало бы дефект самой машинерии (сбитая пара, чужое плечо,
    # выравнивание не по той позиции), а не свойство рынка.
    s_v, r_v = [], []
    for i in range(int(noise_n)):
        hold = _bars(_walk(rng, hold_n))
        e = float(hold[0][1])
        d_max = float(rng.uniform(0.06, 0.25))
        rg = draw_rungs(e, N_RUNGS, d_max, rng)
        if rg is None:
            continue
        a = position_arms(hold, e, rg, e * 1.03, look, None,
                          n_draws=n_draws, leg_id=1000 + i, seed=seed)
        s_v.append(a["S"]["pnl_frac"])
        r_v.append([x["pnl_frac"] for x in a["R"]])
    noise = draw_pool(s_v, r_v) if len(s_v) >= 10 else None

    # --- диагностика геометрии (числом, без утверждения): структурное
    # правило берёт БЛИЖАЙШИЕ уровни первыми, а розыгрыш равномерен по
    # допустимому множеству — значит рунги S систематически выше
    # равномерных, и часть любой разности S − R есть эта геометрия, а не
    # «структурность» уровней. Здесь она измерена на чистом блуждании,
    # где уровни к пути отношения не имеют вовсе.
    g_s, g_r = [], []
    for i in range(int(noise_n)):
        hold = _bars(_walk(rng, hold_n))
        e = float(hold[0][1])
        lv = sorted(e * (1.0 - rng.uniform(0.02, 0.25, 6)), reverse=True)
        rg = L.structural_rungs(e, list(lv), MIN_GAP, N_RUNGS)
        if len(rg) < 3:
            continue
        a = position_arms(hold, e, rg, e * 1.03, look, None,
                          n_draws=n_draws, leg_id=2000 + i, seed=seed)
        g_s.append(a["S"]["pnl_frac"])
        g_r.append([x["pnl_frac"] for x in a["R"]])
    geom = draw_pool(g_s, g_r) if len(g_s) >= 10 else None
    # Подсажен НЕТТО-эффект (место долива у точки разворота), поэтому
    # калибровка судится по нетто — медиане И среднему. Укус в
    # подсаженной половине не значит ничего: там все позиции зелёные, и
    # делить худшую не на что; строка укуса печатается, но утверждением
    # калибровки не является — и это названо здесь, а не умолчано.
    return {"planted": planted, "noise": noise, "geom": geom,
            "planted_n": len(s_pl), "noise_n": len(s_v),
            "geom_n": len(g_s),
            "found": bool(planted and _net_beats(planted["nulls"])),
            "quiet": bool(noise and not _net_beats(noise["nulls"]))}


def _net_beats(nulls):
    """S бьёт розыгрыши по НЕТТО — и по медиане, и по среднему."""
    a = (nulls or {}).get("median")
    b = (nulls or {}).get("mean")
    return bool(a and b and a["beats"] and b["beats"])
