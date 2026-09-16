#!/usr/bin/env python3
"""Механика 1d5e7287 — гейт RR ≥ 2 у длинной лестницы: заслонка ПОДАЧИ или
фильтр КАЧЕСТВА.

Что утверждает заявка. Длинная DCA-лестница (правила версии 6: доливы по
структурным уровням, забор §5, тейк 2·mfe от плавающей ТВХ, пол
капитуляции 0.10, срок 72 ч) берёт решения листа через гейт «край ≥ 33
б.п. И обещанное отношение RR ≥ 2». Знаменатель RR — исполняемый стоп
4-часовой модели — в правилах лестницы не участвует НИГДЕ. Значит гейт
режет подачу (≈ 98 % решений с тем же краем), не отбирая по исходу. Это
проверяемое утверждение, и здесь оно меряется.

Ячейка вердикта ОДНА и объявлена до счёта: линейка `safe`, депозит
$10 000, полоса RR ≤ 1.5, край ≥ 33 б.п. Линейки `optimal`/`aggr` и
подполосы RR печатаются диагностикой БЕЗ выбора. Полоса — уже
объявленное число проекта (книга `sit_lo`, ось `rr_band` пространства
фабрики), новых порогов не вводится.

Чего замер НЕ утверждает: что полоса RR ≤ 1.5 хороша сама по себе (под
геометрией S8 она в минусе у обеих рук, и четыре строки пула с этой
полосой вылетели по форме); что сестра пройдёт форму пула при полной
загрузке; что RR не несёт информации для книги со СТОПОМ.

--------------------------------------------------------------------
Второй копии ядра здесь нет, и вот чем это обеспечено по каждому месту.

* **Полоса — ПАРАМЕТР того же фильтра ног, а не новый предикат.**
  Границы полосы читаются у `factory/live_books.RR_BAND` (ось `rr_band`
  пространства), край — у `dca_ladder/run_d2.MIN_EDGE_BP` (та копия, по
  которой книги реально входят). Третьей копии констант модуль не
  заводит; тест `test_band_hi_is_the_live_gate` требует, чтобы полоса
  `hi` дала РОВНО те же ноги, что живой `run_d6.gated_legs`.
* **Геометрия ноги** — `s10_policy/tournament._leg`, та же функция, что
  у `legs_from_sheets` и у отчёта подачи. Чтение журнала листов
  потоковое (`stream_legs`) — не ради вкуса: `legs_from_sheets`
  материализует 1.26 млн ног и стоит 1033 МБ RSS при пределе прогона
  1200 МБ, а рядом живут сборщик и часовой цикл. Потоковый отбор той же
  функцией стоит 107 МБ. Равенство двух читателей не обещано прозой, а
  проверено (`test_stream_legs_matches_tournament`).
* **Исход позиции** — `run_d6.collect_recs` → `run_d6.one_position` →
  `ladder.simulate_dca`, правила версии 6 из `dca_paper/rules.py`
  (`take_rule`, `RULERS`, `FLOOR_FRAC`, `HOLD_H`).
* **Касса и колонки книги** — `run_paper.build_rows` (билет, «одна на
  имя», гейт плеча, раздача) и `run_paper._stats` (медиана дня, зелёные,
  укус, «без 3 лучших дней», «без лучшего имени», просадка без худшего
  дня). Диагностики, которых `build_rows` выразить не может (решение к
  решению и книга с ограниченной загрузкой), собирают строки
  собственным `rows_from` — и `test_rows_from_matches_build_rows`
  требует совпадения с `build_rows` до цента на тех же записях.
* **Издержки** — `dca_paper/costs.apply_to_rows`, в КАЖДУЮ сделку.
* **Форма** — `factory/stability.stats`, правило вылета —
  `factory/pool.shape_why`. Связь книг — `factory/ceiling.pair_corr`.

**Кэш сестры — свой файл со своей подписью.** Живой кэш реплея
(`run_paper.cache_path()`) модуль ТОЛЬКО ЧИТАЕТ: полоса меняет состав,
а не исход, но подпись живых книг не трогается ни при каком исходе.
Живой журнал (`rules.JOURNAL`) не пишется вовсе.

--------------------------------------------------------------------
Что делает прогон, по шагам (шаг 0 печатается первым — он читается и
без заявки).

0. **Подача.** Подполосы RR по суткам и рукам, уникальные (имя, час) в
   полосе, оценка стоимости реплея ДО реплея. Измеримость: решения
   полосы меньше чем в трети суток журнала — судить нечего.
1. **Решение к решению.** Исходы гейтованных решений берутся из живого
   кэша; для полосы реплеится ОБЪЯВЛЕННАЯ выборка (3 × N_гейт ног,
   зерно 20260916, равномерно по ногам). Медиана нетто-исхода в долях
   маржи, доля хвостовых исходов (пол, ликвидация), 200 зёрен случайных
   подмножеств того же размера из объединения «полоса ∪ гейт», то же
   внутри полос плеча, доля решений с доливом и медиана глубины.
2. **Книга.** Сестра `safe_lo` на $10 000 против базы `safe` на тех же
   сутках и против случайных подмножеств решений сестры того же числа,
   что взяла база (200 зёрен).
3. **Форма.** Правило вылета пула (медиана дня ≥ 0, укус ≤ 10 по ≥ 10
   суткам) — по ЗАПИСИ, то есть по пересчёту; форвардного вердикта у
   сестры нет и быть не может, и печатаются оба вердикта раздельно.

Калибровочная пара, которая обязана кусаться, считается ПЕРЕД шагом 1:
копии гейтованных решений с переписанным rr = 1.0 не должны объявить
гейт фильтром (доля зёрен около половины), те же копии со сдвигом
исходов вниз на литерал −5 % маржи — обязаны. Не сошлось — прогон
останавливается: сломанная загрузка выглядит ровно как «эффекта нет».

--------------------------------------------------------------------
Запуск через очередь заданий (`jobs/<имя>.job`, одной строкой):

    run research/mech_1d5e7287/rr_supply.py --steps 0
    run research/mech_1d5e7287/rr_supply.py --steps 0,1
    run research/mech_1d5e7287/rr_supply.py --steps 0,1,2,3

Смоук (минуты): `--limit 300 --seeds 20 --steps 0,1`.
Ключи перечислены в `RUNBOOK.md`; отчёт публикует сам прогон.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
OUT = os.path.join(HERE, "out")
for _p in ("dca_paper", "dca_ladder", "s8_loop", "s10_policy", "s9_sweep",
           "t4_structure", "factory", "a1_universe"):
    _q = os.path.join(RESEARCH, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import numpy as np                                            # noqa: E402

import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import run_d10 as D10                                         # noqa: E402
import costs as CO                                            # noqa: E402
import tail as TL                                             # noqa: E402
import tournament as TNT                                      # noqa: E402
import trades as TR                                           # noqa: E402
import live_books as LB                                       # noqa: E402
import pool as PL                                             # noqa: E402
import stability as SB                                        # noqa: E402
import ceiling as CE                                          # noqa: E402

# --- объявлено ДО прогона ------------------------------------------------
# Ни одно число здесь не назначено этим замером заново: полоса взята у
# оси `rr_band` пространства фабрики, край — у гейта книг, пороги формы —
# у правила вылета пула, зерно и число зёрен объявлены заявкой.
BAND = "lo"                    # полоса заявки: RR ≤ 1.5 (книга `sit_lo`)
GATE = "hi"                    # полоса гейта книг: RR ≥ 2
RULER = "safe"                 # ячейка вердикта — безопасная линейка
DEPOSIT = 10000.0              # ячейка вердикта — депозит
SEED = 20260916                # зерно объявленной выборки полосы
SEEDS = 200                    # зёрен случайных подмножеств
SAMPLE_MULT = 3                # выборка полосы = 3 × N гейта
WIN_SHARE = 0.95               # «бьёт контроль» — доля зёрен
DAY_SHARE = 1.0 / 3.0          # измеримость: доля суток журнала с решениями
HOLD_H = R.HOLD_H              # срок позиции — у правил книги, не свой
MEM_LIMIT_MB = D10.MEM_LIMIT_MB
# Хвостовой исход позиции: пол капитуляции и ликвидация. Тейк и срок
# хвостом не являются — это выход по правилу.
TAIL_EXITS = ("пол", "ликвидация")
# Подполосы RR — ДИАГНОСТИКА, ячейки вердикта в них нет.
SUB_BANDS = (("RR < 1", None, 1.0), ("RR 1…1.5", 1.0, 1.5),
             ("RR 1.5…2", 1.5, 2.0), ("RR ≥ 2", 2.0, None))
# Полосы плеча — приём портрета хвоста (`DCA-tail-screen.md`): различие,
# исчезающее внутри полос плеча, есть переодетое плечо. Полосы ДИЗЪЮНКТНЫ
# (четвёртое поле — «нижняя граница строгая»), и имена названы тем, что
# код делает: иначе решение с плечом ровно 1× попало бы в две полосы, а
# читатель складывал бы их глазами.
LEV_BANDS = (("ровно 1×", 1.0, 1.0, False),
             ("выше 1× до 3×", 1.0, 3.0, True),
             ("выше 3×", 3.0, None, True))
# Загрузка, ограниченная долей депозита, — ДИАГНОСТИКА без выбора ячейки.
LOAD_CAPS = (0.25, 0.50)
# Сутки базы, названные заявкой отдельной строкой: худший день базы
# (−25.11 $ при 28 позициях, `research/dca_paper/out/DCA-paper.md`).
BASE_WORST_DAY = "2026-08-12"
# Калибровочная пара: литералы объявлены здесь, до чтения любых чисел.
CAL_FLAT_LO, CAL_FLAT_HI = 0.30, 0.70     # копия гейта: доля зёрен «около ½»
CAL_SHIFT = -0.05                          # сдвиг исходов вниз, доли маржи
CAL_SHIFT_MIN = 0.95                       # сдвинутая полоса: гейт — фильтр
# Сколько гейтованных решений реплеить СВОИМ проходом, чтобы сверить его с
# живым кэшем бит в бит. Число объявлено, а не выбрано по результату:
# случайные решения ложатся по одному на имя, поэтому окно чтения у них
# короткое и сверка стоит минуты, а не часы.
CHECK_N = 200
# Во сколько раз разобранная в память запись дороже своей строки в кэше.
# Измерено на живом кэше книг (24.9 МБ на диске — около 230 МБ в памяти
# у часового прогона): держат вес почасовые отметки позиции, список из
# 73 пар. Число нужно, чтобы цена прогона называлась ДО прогона.
MEM_RATIO = 10.0


def estimate(n_recs, path=None):
    """Чего будет стоить реплей: память и время, названные ДО счёта.

    Цена записи меряется по УЖЕ посчитанному кэшу (байт на запись на
    диске), а не берётся из головы; разобранная в память запись стоит
    примерно вдесятеро дороже своей строки — множитель измерен на живом
    кэше книг. Оценка печатается числом именно затем, чтобы прогон,
    который не влезет, был виден до того, как он съест вечер.
    """
    p = path or cache_path()
    per = None
    for q in (p, RP.cache_path()):
        try:
            n = sum(1 for _ in open(q, encoding="utf-8")) - 1
            if n > 0:
                per = os.path.getsize(q) / n
                break
        except OSError:
            continue
    if per is None:
        return {"records": n_recs, "bytes_per_rec": None,
                "why": "посчитанного кэша нет — цена записи не измерена"}
    mb = per * MEM_RATIO * n_recs / 1048576.0
    return {"records": n_recs, "bytes_per_rec": round(per, 1),
            "ram_mb": round(mb, 1), "limit_mb": MEM_LIMIT_MB,
            "fits": bool(mb < MEM_LIMIT_MB),
            "why": None if mb < MEM_LIMIT_MB else
            (f"ожидаемые {mb:.0f} МБ выше предела {MEM_LIMIT_MB} МБ: "
             "прогон снимет себя сам — либо `--band-limit`, либо "
             "`--mem-limit` осознанно и в тихий час")}


def pair_of(ruler):
    """Пара реплея линейки: (правило, параметр, сторона) — ключ кэша."""
    return tuple(RP.RULERS[ruler])


# --- полоса как параметр того же фильтра ног -----------------------------

def band_bounds(band):
    """Границы полосы RR. Читаются у оси `rr_band` пространства фабрики.

    Своего числа у модуля нет намеренно: полоса `lo` объявлена проектом
    для книги `sit_lo`, и вторая копия «1.5» однажды разошлась бы с
    первой — ровно так уже разошлись две копии гейта (`run_d2.py` и
    `rules.py`), и книги входят по одной, а страница печатает другую.
    """
    if band not in LB.RR_BAND:
        raise ValueError(f"полосы {band!r} у оси rr_band нет: "
                         f"{sorted(LB.RR_BAND)}")
    return LB.RR_BAND[band]


def in_band(rr, band):
    """Отношение попадает в полосу? `None` — НЕ попадает ни в какую.

    «Не измерено» внутри фильтра есть сам по себе фильтр, и именно так
    подделался гейт по ставке funding (+21…+23 % делались 773
    решениями, отсечёнными как «ставка неизвестна»). Поэтому нога без
    отношения не проходит ни полосу, ни гейт, и считается ОТДЕЛЬНЫМ
    числом.
    """
    if rr is None:
        return False
    lo, hi = band_bounds(band)
    if lo is not None and float(rr) < float(lo):
        return False
    if hi is not None and float(rr) > float(hi):
        return False
    return True


def leg_keep(band, side="long", edge_bp=None):
    """Предикат отбора ног: край книги плюс полоса. Одна формула на все
    полосы — гейт книг есть частный случай `band="hi"`."""
    edge = D2.MIN_EDGE_BP if edge_bp is None else float(edge_bp)

    def keep(g):
        if side is not None and (g.get("side") or "long") != side:
            return False
        if abs(float(g["fwd"])) < edge:
            return False
        return in_band(g.get("rr"), band)
    return keep


def pick_legs(legs, band, side="long", edge_bp=None):
    """Ноги полосы из уже прочитанного списка."""
    keep = leg_keep(band, side=side, edge_bp=edge_bp)
    return [g for g in legs if keep(g)]


# --- чтение журнала листов: потоком, той же геометрией -------------------

def stream_legs(paths, keep=None, log=print, limit_hours=None):
    """Ноги журнала листов ПОТОКОМ, геометрией `tournament._leg`.

    Зачем не `legs_from_sheets`: он материализует ВСЕ ноги (1.26 млн на
    2026-09-16) и стоит 1033 МБ RSS при пределе прогона 1200 МБ, а рядом
    живут сборщик (1.5 ГБ) и часовой цикл (до 3.3 ГБ). Потоковый отбор
    той же функцией стоит 107 МБ.

    Равенство с каноническим читателем не обещано прозой: `keep=None`
    обязано давать тот же список (порядок и поля, кроме `id`), и это
    проверено тестом. Поле `id` здесь НЕ проставляется намеренно — его
    нумерация у `legs_from_sheets` сквозная по всему журналу, и
    проставить своё значило бы завести второй номер с тем же именем.
    """
    out, hours, bad, seen = [], 0, 0, 0
    for path in paths:
        try:
            fh = open(path, encoding="utf-8")
        except OSError:
            log(f"{path}: журнала листов нет — пропуск")
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                at = rec.get("written_at") or (
                    (TR._ts(rec.get("hour")) or 0) + 3600)
                if not at:
                    bad += 1
                    continue
                hours += 1
                for arm, rows in (rec.get("arms") or {}).items():
                    for row in rows or []:
                        seen += 1
                        lg = TNT._leg(row, arm, rec.get("hour"), float(at))
                        if lg is None:
                            continue
                        if keep is None or keep(lg):
                            out.append(lg)
                if limit_hours and hours >= limit_hours:
                    break
    out.sort(key=lambda g: (g["at"], g["arm"],
                            -abs(g["fz"]) if g["fz"] is not None else 0,
                            g["sym"]))
    log(f"листов {hours}, строк {seen}, битых {bad}, отобрано {len(out)}")
    return out, {"hours": hours, "rows": seen, "bad": bad, "kept": len(out)}


# --- шаг 0: подача -------------------------------------------------------

def _median(xs):
    if not xs:
        return None
    ys = sorted(xs)
    m = len(ys) // 2
    return ys[m] if len(ys) % 2 else 0.5 * (ys[m - 1] + ys[m])


def day_of(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))


def supply_table(legs, edge_bp=None):
    """Подполосы RR по суткам и рукам — шаг 0, печатается ПЕРВЫМ.

    Считается по ногам с краем ≥ гейта книг: вопрос заявки — что гейт RR
    режет ПРИ ТОМ ЖЕ КРАЕ, и подполосы без края отвечали бы на другой
    вопрос. Ноги без отношения считаются своим числом.
    """
    edge = D2.MIN_EDGE_BP if edge_bp is None else float(edge_bp)
    days = {}
    for g in legs:
        if (g.get("side") or "long") != "long":
            continue
        if abs(float(g["fwd"])) < edge:
            continue
        d = day_of(g["at"])
        arm = g.get("arm") or "gbm"
        c = days.setdefault(d, {}).setdefault(arm, {
            "n": 0, "rr_unknown": 0, "sub": {k[0]: 0 for k in SUB_BANDS},
            "band": 0, "gate": 0, "rrs": [], "pairs": set()})
        c["n"] += 1
        rr = g.get("rr")
        if rr is None:
            c["rr_unknown"] += 1
            continue
        c["rrs"].append(float(rr))
        for (name, lo, hi) in SUB_BANDS:
            if (lo is None or rr >= lo) and (hi is None or rr < hi):
                c["sub"][name] += 1
                break
        if in_band(rr, BAND):
            c["band"] += 1
            c["pairs"].add((g["sym"], g.get("hour")))
        if in_band(rr, GATE):
            c["gate"] += 1
    out = {}
    for d, arms in days.items():
        out[d] = {}
        for arm, c in arms.items():
            out[d][arm] = {
                "n": c["n"], "rr_unknown": c["rr_unknown"],
                "sub": dict(c["sub"]), "band": c["band"], "gate": c["gate"],
                "rr_median": (round(_median(c["rrs"]), 2) if c["rrs"]
                              else None),
                "band_pairs": len(c["pairs"])}
    return out


def measurable(table, days_total):
    """Измеримость шага 0: решений полосы меньше чем в трети суток — судить
    нечего, и вердикт этот выводится из ЧИСЛА, а не стоит рядом с ним."""
    with_band = sum(1 for d in table
                    if any(c["band"] > 0 for c in table[d].values()))
    need = max(1, int(round(DAY_SHARE * max(1, days_total))))
    ok = with_band >= need
    return {"days_total": days_total, "days_with_band": with_band,
            "need": need, "share": (round(with_band / days_total, 3)
                                    if days_total else None),
            "measurable": bool(ok),
            "verdict": ("судить есть чем: полоса непуста в "
                        f"{with_band} сутках из {days_total} при пороге "
                        f"{need}"
                        if ok else
                        "судить НЕЧЕМ: полоса непуста лишь в "
                        f"{with_band} сутках из {days_total} при пороге "
                        f"{need} — механика закрыта измеримостью")}


# --- объявленная выборка полосы -----------------------------------------

def declared_sample(legs, n_gate, mult=SAMPLE_MULT, seed=SEED):
    """Объявленная выборка полосы: `mult × n_gate` ног, равномерно, зерно
    номером. Полоса меньше выборки — берётся целиком, и это ЧИСЛО, а не
    молчаливое совпадение."""
    want = int(mult) * int(n_gate)
    if want <= 0:
        return [], {"want": want, "have": len(legs), "taken": 0,
                    "whole": False, "seed": int(seed)}
    if len(legs) <= want:
        return list(legs), {"want": want, "have": len(legs),
                            "taken": len(legs), "whole": True,
                            "seed": int(seed)}
    idx = sorted(random.Random(int(seed)).sample(range(len(legs)), want))
    return [legs[i] for i in idx], {"want": want, "have": len(legs),
                                    "taken": want, "whole": False,
                                    "seed": int(seed)}


# --- реплей: тот же проход, свой кэш ------------------------------------

def cache_path(band=BAND):
    """Кэш СЕСТРЫ — свой файл. Живой кэш книг не трогается ни при каком
    исходе: он описывает другой состав, и подпись у него своя."""
    return os.path.join(OUT, f"recs-{band}.jsonl")


def cache_sig(band=BAND):
    """Подпись кэша сестры: подпись живого реплея плюс ПОЛОСА.

    Полоса меняет СОСТАВ, а не исход, — но кэш, посчитанный на другой
    полосе, описывает другой набор решений, и склеить их одним файлом
    значило бы отдать исходы чужой книги.
    """
    return dict(RP.cache_sig(), band=str(band),
                band_bounds=list(band_bounds(band)), mech="1d5e7287")


def replay(legs, ruler=RULER, src=None, log=print, path=None, band=BAND,
           mem=True, limit_mb=None):
    """Исходы решений — ТЕМ ЖЕ проходом, что у живых длинных книг.

    Инкрементально: закрытая позиция окончательна (прошлые бары не
    меняются), поэтому пересчитываются только новые и незакрытые.
    """
    path = path or cache_path(band)
    lim = MEM_LIMIT_MB if limit_mb is None else float(limit_mb)
    pair = pair_of(ruler)
    cache, why = RP.read_cache(path=path, sig=cache_sig(band))
    if why:
        log(f"кэш сестры не используется: {why}")
    need = RP.needs_replay(cache, legs, [pair])
    est = estimate(len(legs), path=path)
    log(f"решений полосы {len(legs)}, в кэше {len(cache)}, "
        f"считаю заново {len(need)}; цена в памяти ≈ "
        f"{est.get('ram_mb', '—')} МБ при пределе {lim:g} МБ"
        + (f" — {est['why']}" if est.get("why") else ""))
    if mem:
        D10.mem_guard("до реплея полосы", log=log, limit=lim)
    src = src if src is not None else TL.TailBars(log=log)
    # Срок передаётся ЯВНО и берётся у правил книги (`rules.HOLD_H`), а не
    # оставляется умолчанию реплея: срок есть правило ИСХОДА, и книга,
    # которую судят, обязана торговать тем же сроком, каким её считают.
    # Он же — единственная граница, за которую этот модуль смотрит во
    # времени, и тест на заглядывание в будущее кусается именно здесь.
    got = D6.collect_recs(rulers=[pair], legs=legs, src=src, hold_h=HOLD_H,
                          only=[(g["sym"], g["at"]) for g in need], log=log)
    tail = dict(src.stats() if hasattr(src, "stats") else {},
                **TL.apply(got["recs"], getattr(src, "last_tape", {}),
                           getattr(src, "last_book", {})))
    for r in got["recs"][pair]:
        cache[(pair, r["sym"], round(float(r["at"]), 3))] = r
    RP.write_cache(cache, path=path, sig=cache_sig(band))
    if mem:
        D10.mem_guard("после реплея полосы", log=log, limit=lim)
    recs = [r for (pr, _s, _a), r in cache.items() if pr == pair]
    log(f"записей сестры в кэше {len(recs)}, пересчитано "
        f"{got['positions']}, пропущено {got['skipped']}")
    return recs, {"replayed": got["positions"], "skipped": got["skipped"],
                  "states": got.get("states"), "cached": len(recs),
                  "estimate": est, "tail": tail}


def live_recs(ruler=RULER, log=print):
    """Исходы ГЕЙТОВАННЫХ решений — из живого кэша книг, только чтение."""
    cache, why = RP.read_cache()
    pair = pair_of(ruler)
    recs = [r for (pr, _s, _a), r in cache.items() if pr == pair]
    log(f"живой кэш: записей линейки {ruler} {len(recs)}"
        + (f"; непригоден: {why}" if why else ""))
    return recs, {"why": why, "n": len(recs)}


def cache_check(mine, live):
    """Реплей гейтованных ног обязан воспроизводить живой кэш БИТ В БИТ.

    Сверяются исход, момент выхода, плечо и деньги позиции по общим
    (имя, момент). Расхождение означает, что ядро НЕ одно, и это отказ,
    а не замечание. Общих записей нет — величина не измерена, и это
    прочерк с причиной, а не «сошлось».

    Сверяются только ЗАКРЫТЫЕ с обеих сторон: у открытой позиции отметка
    меняется с ценой, и вчерашняя запись живого кэша законно отличается
    от сегодняшней. Сколько таких — считается отдельным числом.

    И отдельно — позиции, ПОМЕЧЕННЫЕ ХВОСТОМ хоть с одной стороны. Их
    исход считан не только принтами: правило хвоста (`tail.TailBars`)
    продолжает ленту серединой стакана ПОСЛЕ последнего бара ЗАПРОШЕННОГО
    окна, а окно символа задаёт тот набор ног, который реплеится в этом
    проходе. Значит у позиции, чей срок упирается в конец ленты, исход
    зависит от того, какими ногами шёл проход, — и сверять такие записи
    бит в бит нельзя: расходятся не ядра, а окна. Число таких печатается,
    потому что молчаливый пропуск читался бы как «сошлось».
    """
    by = {(r["sym"], round(float(r["at"]), 3)): r for r in live}
    same = diff = openish = tailish = 0
    worst = None
    for r in mine:
        k = (r["sym"], round(float(r["at"]), 3))
        o = by.get(k)
        if o is None:
            continue
        if r.get("state") != "closed" or o.get("state") != "closed":
            openish += 1
            continue
        if r.get("tail") or o.get("tail"):
            tailish += 1
            continue
        ok = (r.get("exit") == o.get("exit")
              and abs(float(r["pnl"]) - float(o["pnl"])) < 1e-12
              and abs(float(r["exit_ts"]) - float(o["exit_ts"])) < 1e-9
              and abs(float(r["lev"]) - float(o["lev"])) < 1e-12)
        if ok:
            same += 1
        else:
            diff += 1
            if worst is None:
                worst = {"sym": r["sym"], "at": r["at"],
                         "mine": {"exit": r.get("exit"), "pnl": r["pnl"]},
                         "live": {"exit": o.get("exit"), "pnl": o["pnl"]}}
    n = same + diff
    return {"common": n, "same": same, "diff": diff, "open": openish,
            "tail_skipped": tailish, "example": worst,
            "verdict": ("не измерено: общих закрытых записей без хвоста нет"
                        if not n
                        else (f"ядро одно: {same} из {n} совпали бит в бит"
                              if not diff else
                              f"ЯДРО НЕ ОДНО: разошлись {diff} из {n}"))}


# --- строки книги и деньги ----------------------------------------------

def rows_from(taken, deposit, ruler, now=None):
    """Записи реплея с выданной маржой → строки журнальной формы.

    Формула денег та же, что у кассы живых книг (`usd = pnl × маржа`), и
    равенство это не обещано прозой: `test_rows_from_matches_build_rows`
    требует совпадения с `run_paper.build_rows` до цента на тех же
    записях. Нужна эта сборка там, где `build_rows` неприменим по
    устройству: решение к решению (кассы нет вовсе) и книга с
    ограниченной загрузкой (у кассы такого правила нет).
    """
    now = float(now if now is not None else time.time())
    out = []
    for (r, margin) in taken:
        if r.get("state", "closed") != "closed":
            continue
        out.append({
            "dep": int(deposit), "ruler": ruler, "at": float(r["at"]),
            "side": r.get("side") or R.side_of(ruler),
            "exit_ts": float(r["exit_ts"]), "sym": r["sym"],
            "lev": round(float(r["lev"]), 3),
            "margin": round(float(margin), 4),
            "pnl_frac": round(float(r["pnl"]), 6),
            "usd": round(float(r["pnl"]) * float(margin), 4),
            "exit": r.get("exit"), "tail": r.get("tail"),
            "entry_px": r.get("entry_px"), "exit_px": r.get("exit_px"),
            "avg": r.get("avg"), "depth": r.get("depth"),
            "fills": r.get("fills"), "fav_bp": r.get("fav_bp"),
            "written_at": now, "rules": R.RULES})
    return out


def net(rows, ctx, log=print):
    """Издержки — в КАЖДУЮ сделку, тем же ядром, что у живых книг."""
    if not rows:
        return [], {"n": 0, "applied": 0, "error": "строк нет"}
    got, summ = CO.apply_to_rows(rows, ctx)
    return got, summ


def net_frac(rows):
    """Нетто-исход решения в долях маржи — только у ПОЛНОСТЬЮ измеренных.

    Строка, у которой хоть одна издержка неизмерима, в меру не идёт:
    смешивать брутто с нетто в одной медиане значит выдавать пропуск за
    число. Сколько таких — считается отдельно.
    """
    vals, skip = [], 0
    for r in rows:
        m = float(r.get("margin") or 0.0)
        if r.get("costs_why") is not None or m <= 0:
            skip += 1
            continue
        vals.append(float(r["usd"]) / m)
    return vals, skip


# --- шаг 1: решение к решению -------------------------------------------

def decision_rows(recs, ctx, ruler=RULER, deposit=DEPOSIT, log=print):
    """Псевдо-строки «одно решение — один билет»: кассы здесь нет вовсе.

    Маржа у всех одна и равна билету книги, потому что вопрос шага —
    КАЧЕСТВО решения, а не то, кому досталась касса. Мера от масштаба
    маржи не зависит: комиссия, проскальзывание и funding линейны по
    нотионалу, а нотионал линеен по марже.
    """
    ticket = R.ticket(float(deposit), ruler)
    rows = rows_from([(r, ticket) for r in recs], deposit, ruler)
    got, summ = net(rows, ctx, log=log)
    log(f"решений {len(recs)}, строк с исходом {len(got)}, "
        f"издержки применены у {summ.get('applied')}")
    return got, summ


def outcome_stats(rows, name=""):
    """Мера исходов набора решений: медиана и среднее нетто в долях маржи,
    доля хвостовых исходов, глубина лестницы.

    Ноль наблюдений при непустом входе — ОТКАЗ, а не отчёт с прочерками:
    пустота не вправе выдавать себя за результат.
    """
    vals, skip = net_frac(rows)
    if rows and not vals:
        raise SystemExit(
            f"ОТКАЗ: у набора «{name}» {len(rows)} строк и НИ ОДНОЙ с "
            "измеренными издержками — это отказ загрузки, а не результат")
    if not vals:
        return None
    v = np.array(vals, dtype=float)
    tail = [r for r in rows if r.get("exit") in TAIL_EXITS]
    dep = [int(r.get("depth") or 1) for r in rows if r.get("depth")]
    return {"n": len(rows), "measured": len(vals), "unmeasured": skip,
            "median": round(float(np.median(v)), 5),
            "mean": round(float(np.mean(v)), 5),
            "green": round(float(np.mean(v > 0)), 3),
            "worst": round(float(np.min(v)), 4),
            "tail_share": round(len(tail) / len(rows), 4),
            "tail_n": len(tail),
            "add_share": (round(sum(1 for d in dep if d >= 2) / len(dep), 4)
                          if dep else None),
            "depth_median": (round(float(np.median(dep)), 2) if dep
                             else None),
            "names": len({r["sym"] for r in rows})}


def _med_tail(rows):
    """Пара «медиана нетто, доля хвоста» для одного набора строк."""
    vals, _skip = net_frac(rows)
    if not vals:
        return None, None
    tail = sum(1 for r in rows if r.get("exit") in TAIL_EXITS) / len(rows)
    return float(np.median(vals)), float(tail)


def seed_test(gate_rows, band_rows, seeds=SEEDS, seed0=SEED):
    """Гейт против СЛУЧАЙНОЙ выборки того же размера из «полоса ∪ гейт».

    Урок проекта: фильтр, который РЕЖЕТ число сделок, сравнивается со
    случайной выборкой ТОГО ЖЕ размера, на многих зёрнах и по той же
    величине, о которой спор. Одна выборка — сам шум; разрешение доли
    есть 1/зёрна.
    """
    union = list(gate_rows) + list(band_rows)
    k = len(gate_rows)
    if k < 1 or len(union) <= k:
        return {"seeds": 0, "why": "объединение не больше гейта — сравнивать "
                                   "не с чем"}
    g_med, g_tail = _med_tail(gate_rows)
    if g_med is None:
        return {"seeds": 0, "why": "у гейта нет измеренных издержек"}
    med_win = tail_win = done = 0
    meds, tails = [], []
    for i in range(int(seeds)):
        rnd = random.Random(int(seed0) + i)
        sub = rnd.sample(union, k)
        m, t = _med_tail(sub)
        if m is None:
            continue
        done += 1
        meds.append(m)
        tails.append(t)
        # Ничья засчитывается ПОПОЛАМ, и это не смягчение. Объединение
        # содержит сам гейт, поэтому случайное подмножество делит с ним
        # часть решений, а у копий совпадения точны — строгое «больше»
        # тогда систематически недосчитывало бы гейту и выдавало бы
        # антиселективность там, где наборы тождественны. Конвенция та
        # же, что у ранговой статистики, и объявлена до чисел.
        med_win += (1.0 if g_med > m else (0.5 if g_med == m else 0.0))
        tail_win += (1.0 if g_tail < t else (0.5 if g_tail == t else 0.0))
    if not done:
        return {"seeds": 0, "why": "ни одно зерно не дало измеренной выборки"}
    return {"seeds": done, "k": k, "union": len(union),
            "gate_median": round(g_med, 5), "gate_tail": round(g_tail, 4),
            "rnd_median_median": round(float(np.median(meds)), 5),
            "rnd_tail_median": round(float(np.median(tails)), 4),
            "median_win": round(med_win / done, 3),
            "tail_win": round(tail_win / done, 3),
            "resolution": round(1.0 / done, 4)}


def gate_verdict(st, win=WIN_SHARE):
    """Вердикт шага 1б — ВЫВЕДЕН из чисел, а не поставлен рядом с ними."""
    if not st or not st.get("seeds"):
        return "не измерено: " + (st or {}).get("why", "зёрен нет")
    mw, tw = st["median_win"], st["tail_win"]
    if mw >= win or tw >= win:
        return (f"ГЕЙТ ЕСТЬ ФИЛЬТР КАЧЕСТВА: гейтованный набор лучше "
                f"случайного того же размера в {mw:.0%} зёрен по медиане и "
                f"{tw:.0%} по хвосту при пороге {win:.0%} — заявка мертва")
    if mw <= 1.0 - win or tw <= 1.0 - win:
        return (f"ГЕЙТ АНТИСЕЛЕКТИВЕН: случайная выборка того же размера "
                f"лучше гейта в {1 - mw:.0%} зёрен по медиане и "
                f"{1 - tw:.0%} по хвосту")
    return (f"ОТБОРА НЕТ: гейт лучше случайной выборки того же размера в "
            f"{mw:.0%} зёрен по медиане и {tw:.0%} по хвосту — ни то ни "
            f"другое не дотягивает до {win:.0%}")


def lev_split(gate_rows, band_rows, seeds=SEEDS, seed0=SEED):
    """То же сравнение ВНУТРИ полос плеча: различие, исчезающее внутри
    полос, есть переодетое плечо."""
    out = []
    for (name, lo, hi, strict) in LEV_BANDS:
        def pick(rows, lo=lo, hi=hi, strict=strict):
            got = []
            for r in rows:
                lv = float(r.get("lev") or 0.0)
                if lo is not None and (lv <= lo + 1e-9 if strict
                                       else lv < lo - 1e-9):
                    continue
                if hi is not None and lv > hi + 1e-9:
                    continue
                got.append(r)
            return got
        g, b = pick(gate_rows), pick(band_rows)
        st = seed_test(g, b, seeds=seeds, seed0=seed0) if g and b else {
            "seeds": 0, "why": "в полосе нет одного из наборов"}
        out.append({"band": name, "gate_n": len(g), "band_n": len(b),
                    "gate": outcome_stats(g, name) if g else None,
                    "lo": outcome_stats(b, name) if b else None,
                    "seed": st, "verdict": gate_verdict(st)})
    return out


def mech_check(gate_st, band_st):
    """Проверка НАЗВАННОГО механизма: у полосы доливов обязано быть больше.

    Заявка объясняет ожидаемый плюс тем, что низкое RR при том же крае —
    это обещание большого хода ПРОТИВ входа, то есть ровно те решения,
    где у лестницы будут доливы. Если у полосы доливов не больше,
    механизм назван неверно, и даже живая заявка стоит на другом.
    """
    if not gate_st or not band_st:
        return {"verdict": "не измерено: один из наборов пуст"}
    a, b = gate_st.get("add_share"), band_st.get("add_share")
    if a is None or b is None:
        return {"verdict": "не измерено: глубина лестницы не записана"}
    d = b - a
    return {"gate_add": a, "band_add": b, "delta": round(d, 4),
            "gate_depth": gate_st.get("depth_median"),
            "band_depth": band_st.get("depth_median"),
            "verdict": (f"механизм назван верно: доливы у полосы {b:.1%} "
                        f"против {a:.1%} у гейта (+{d:.1%})" if d > 0 else
                        f"МЕХАНИЗМ НАЗВАН НЕВЕРНО: доливы у полосы {b:.1%} "
                        f"против {a:.1%} у гейта ({d:+.1%}) — заявка "
                        f"объясняет плюс тем, чего нет")}


# --- калибровочная пара --------------------------------------------------

def calibration(gate_rows, seeds=SEEDS, seed0=SEED, mult=SAMPLE_MULT):
    """Найти подсаженное и промолчать на копии. Литералы объявлены выше.

    (i) полоса из КОПИЙ гейтованных решений — гейт не вправе оказаться
        фильтром, доля зёрен обязана лечь около половины;
    (ii) те же копии с исходами, сдвинутыми вниз на `CAL_SHIFT` доли
        маржи, — гейт обязан быть объявлен фильтром.

    Без этой пары сломанная загрузка выглядит ровно как «эффекта нет», и
    это в проекте уже случалось дважды.
    """
    if not gate_rows:
        return {"ok": False, "why": "гейтованных строк нет — калибровать "
                                    "нечем"}
    flat, shift = [], []
    for i in range(int(mult)):
        for r in gate_rows:
            c = dict(r)
            c["at"] = float(r["at"]) + 1e-6 * (i + 1)     # копия, не та же нога
            flat.append(c)
            s = dict(c)
            m = float(r.get("margin") or 0.0)
            s["usd"] = float(r["usd"]) + CAL_SHIFT * m
            shift.append(s)
    st_flat = seed_test(gate_rows, flat, seeds=seeds, seed0=seed0)
    st_shift = seed_test(gate_rows, shift, seeds=seeds, seed0=seed0)
    mw_f = st_flat.get("median_win")
    mw_s = st_shift.get("median_win")
    ok_flat = (mw_f is not None and CAL_FLAT_LO <= mw_f <= CAL_FLAT_HI
               and "ФИЛЬТР КАЧЕСТВА" not in gate_verdict(st_flat))
    ok_shift = (mw_s is not None and mw_s >= CAL_SHIFT_MIN
                and "ФИЛЬТР КАЧЕСТВА" in gate_verdict(st_shift))
    return {"ok": bool(ok_flat and ok_shift),
            "flat": {"median_win": mw_f, "ok": bool(ok_flat),
                     "want": [CAL_FLAT_LO, CAL_FLAT_HI],
                     "verdict": gate_verdict(st_flat)},
            "shift": {"median_win": mw_s, "ok": bool(ok_shift),
                      "want": CAL_SHIFT_MIN, "shift": CAL_SHIFT,
                      "verdict": gate_verdict(st_shift)},
            "why": None if (ok_flat and ok_shift) else
            ("копия гейта объявлена фильтром либо доля зёрен вне "
             f"[{CAL_FLAT_LO}, {CAL_FLAT_HI}]" if not ok_flat else
             f"сдвиг на {CAL_SHIFT:+.0%} маржи НЕ пойман")}


# --- шаг 2: книга --------------------------------------------------------

def book_rows(recs, ruler=RULER, deposit=DEPOSIT, ctx=None, log=print):
    """Книга на записи: касса и колонки — кодом ЖИВЫХ длинных книг.

    `build_rows` считает все три депозита разом (по ним книга и
    различается билетом); ячейка вердикта берётся из них по ключу.
    Живой журнал при этом не пишется вовсе.
    """
    rows, cells, one, _live = RP.build_rows({ruler: list(recs)}, log=log,
                                            keys=[ruler])
    mine = [r for r in rows if int(r["dep"]) == int(deposit)]
    got, summ = net(mine, ctx, log=log) if ctx is not None else (mine, {})
    cell = cells.get(f"{ruler}:{int(deposit)}") or {}
    return got, {"cell": cell, "one_name": one.get(ruler) or {},
                 "costs": summ}


def book_stats(rows, deposit=DEPOSIT):
    """Форма книги — `run_paper._stats`, та же, которой судят живые."""
    return RP._stats(rows, float(deposit))


def daily_usd(rows):
    """День ВЫХОДА → нетто в долларах. День — когда деньги стали известны."""
    d = {}
    for r in rows:
        d[day_of(r["exit_ts"])] = d.get(day_of(r["exit_ts"]), 0.0) \
            + float(r["usd"])
    return d


def daily_no(rows):
    """Тот же ряд, но ключом НОМЕР суток: правило вылета пула и связь книг
    считаются по номерам, а не по датам строкой."""
    d = {}
    for r in rows:
        k = int(float(r["exit_ts"]) // PL.DAY)
        d[k] = d.get(k, 0.0) + float(r["usd"])
    return d


def ratio(st):
    """Доход на просадку книги. Просадки нет — величина НЕ СУЩЕСТВУЕТ, и
    прочерк здесь честнее бесконечности."""
    if not st:
        return None
    dd = float(st.get("max_dd") or 0.0)
    if dd >= -1e-12:
        return None
    return float(st.get("final") or 0.0) / abs(dd)


def book_seed_test(sister_rows, base_rows, deposit=DEPOSIT, seeds=SEEDS,
                   seed0=SEED):
    """База против СЛУЧАЙНЫХ подмножеств решений сестры того же числа.

    Если база бьёт случайную того же размера по доходу на просадку в
    ≥ 95 % зёрен — гейт выбирает лучшие решения и на уровне книги, и
    заявка закрыта.
    """
    k = len(base_rows)
    if k < 1 or len(sister_rows) <= k:
        return {"seeds": 0, "why": "сестра не больше базы — сравнивать не с "
                                   "чем"}
    base_r = ratio(book_stats(base_rows, deposit))
    if base_r is None:
        return {"seeds": 0, "why": "у базы нет просадки — отношения не "
                                   "существует"}
    win, done, rs = 0, 0, []
    for i in range(int(seeds)):
        sub = random.Random(int(seed0) + i).sample(sister_rows, k)
        r = ratio(book_stats(sub, deposit))
        if r is None:
            continue
        done += 1
        rs.append(r)
        win += int(base_r > r)
    if not done:
        return {"seeds": 0, "why": "ни одно зерно не дало просадки"}
    return {"seeds": done, "k": k, "base_ratio": round(base_r, 3),
            "rnd_ratio_median": round(float(np.median(rs)), 3),
            "base_win": round(win / done, 3),
            "resolution": round(1.0 / done, 4),
            "verdict": ((f"ГЕЙТ ВЫБИРАЕТ ЛУЧШИЕ РЕШЕНИЯ И НА УРОВНЕ КНИГИ: "
                         f"база бьёт случайную того же размера в "
                         f"{win / done:.0%} зёрен при пороге "
                         f"{WIN_SHARE:.0%} — заявка закрыта")
                        if win / done >= WIN_SHARE else
                        (f"на уровне книги отбора нет: база бьёт случайную "
                         f"того же размера в {win / done:.0%} зёрен при "
                         f"пороге {WIN_SHARE:.0%}"))}


def cap_rows(recs, ruler=RULER, deposit=DEPOSIT, pot=None):
    """Книга ТОЙ ЖЕ кассой (`run_d6.ration`) при заданном размере кассы.

    Билет остаётся билетом книги; меняется только то, сколько денег у
    кассы. При `pot = deposit` это в точности живая книга, и равенство
    проверено тестом против `run_paper.build_rows` — иначе здесь завелась
    бы вторая касса, а страница и замер разошлись бы молча.

    Правило «одна позиция на имя» применяется ДО раздачи, как у книг:
    правило биржи от депозита не зависит.
    """
    pot = float(deposit if pot is None else pot)
    ticket = R.ticket(float(deposit), ruler)
    keep, _skip = (D6.one_per_name(list(recs)) if R.ONE_PER_NAME
                   else (list(recs), 0))
    plan = [(dict(r, exit_ts=float(r.get("sched_end") or r["exit_ts"]))
             if r.get("state") in ("open", "cut") else r) for r in keep]
    rows = []
    cell = D6.ration(plan, (lambda _r, _p=pot: ticket / _p), deposit=pot,
                     min_notional=R.MIN_NOTIONAL, keep_rows=rows)
    return rows_from(rows, deposit, ruler), cell


def load_caps(recs, ruler=RULER, deposit=DEPOSIT, caps=LOAD_CAPS, ctx=None,
              log=print):
    """Форма при загрузке, ограниченной долей депозита — ДИАГНОСТИКА.

    Ячейки вердикта здесь нет: заявка объявила, что при полной загрузке
    укус ожидается около 20, и лечится он РАЗМЕРОМ загрузки — решение
    владельца, для которого нужна измеренная форма, а не выбранная.
    """
    out = []
    for cap in caps:
        pot = float(cap) * float(deposit)
        got, c = cap_rows(recs, ruler, deposit, pot)
        if ctx is not None:
            got, _summ = net(got, ctx, log=lambda *a: None)
        st = book_stats(got, deposit)
        out.append({"cap": float(cap), "pot": round(pot, 2),
                    "taken": c["taken"], "no_cash": c["no_cash"],
                    "too_small": c["too_small"],
                    "open_mean": c["open_mean"], "open_max": c["open_max"],
                    "stats": st})
        log(f"загрузка ≤ {cap:.0%}: взято {c['taken']}, нет кассы "
            f"{c['no_cash']}, мельче минимума {c['too_small']}")
    return out


# --- шаг 3: форма --------------------------------------------------------

def shape(rows, deposit=DEPOSIT, declared_at=None):
    """Правило вылета пула по форме — `pool.shape_why`, оно же у кандидатов.

    Здесь оно судит ЗАПИСЬ (пересчёт по прошлому): форвардного ряда у
    сестры не существует, и выдать один вердикт за другой нельзя.
    Порогов модуль не назначает — они взяты у правила.
    """
    dl = daily_no(rows)
    st = SB.stats(dl)
    why = PL.shape_why(dl, declared_at)
    return {"days": (st or {}).get("days"), "thin": (st or {}).get("thin"),
            "med": (st or {}).get("med"), "bite": (st or {}).get("bite"),
            "green": (st or {}).get("green"), "worst": (st or {}).get("worst"),
            "min_days": SB.MIN_DAYS, "min_med": PL.MIN_MED_DAY,
            "max_bite": PL.MAX_BITE,
            "why": why,
            "verdict": ("вердикта нет: суток меньше "
                        f"{SB.MIN_DAYS} — не измерено не есть провал"
                        if (st or {}).get("thin", True) else
                        (f"по форме ПРОШЛА бы: медиана дня "
                         f"{st['med']:+.2f} $, укус "
                         + (f"{st['bite']:.1f}" if st.get("bite") is not None
                            else "—") + f" при пределе {PL.MAX_BITE:.0f}"
                         if why is None else f"вылет по форме: {why}")),
            "forward": "форвардного ряда у сестры нет: книга не заведена, "
                       "и этот вердикт вынесен по ПЕРЕСЧЁТУ прошлого"}


# --- прогон ---------------------------------------------------------------

def run(limit=None, seeds=SEEDS, steps=(0, 1, 2, 3), src=None, log=print,
        band_limit=None, ruler=RULER, deposit=DEPOSIT, sheets=None,
        mem=True, ctx=None, limit_mb=None):
    t0 = time.time()
    lim = MEM_LIMIT_MB if limit_mb is None else float(limit_mb)
    steps = set(int(x) for x in steps)
    s = {"at": time.time(), "band": BAND, "gate": GATE,
         "bounds": list(band_bounds(BAND)), "edge_bp": D2.MIN_EDGE_BP,
         "ruler": ruler, "deposit": float(deposit), "seed": SEED,
         "seeds": int(seeds), "sample_mult": SAMPLE_MULT,
         "hold_h": HOLD_H, "ticket": R.ticket(float(deposit), ruler),
         "rules": R.RULES, "steps": sorted(steps), "mem_limit_mb": lim,
         # Ячейка вердикта заполняется ТОЛЬКО полным прогоном. Урезанный
         # чем угодно прогон описывает другую книгу, и назвать его
         # вердиктом значило бы выдать смоук за замер.
         "capped": bool(limit or band_limit),
         "cap_why": (None if not (limit or band_limit) else
                     f"прогон урезан (--limit {limit}, --band-limit "
                     f"{band_limit}): ячейка вердикта НЕ заполнена")}

    # --- шаг 0 ----------------------------------------------------------
    paths = [sheets or D2.SHEETS]
    keep_any = lambda g: (abs(float(g["fwd"])) >= D2.MIN_EDGE_BP  # noqa: E731
                          and (g.get("side") or "long") == "long")
    legs, rd = stream_legs(paths, keep=keep_any, log=log)
    s["read"] = rd
    if rd["rows"] and not legs:
        raise SystemExit(
            f"ОТКАЗ: журнал листов непуст ({rd['rows']} строк), а ног с "
            f"краем ≥ {D2.MIN_EDGE_BP} б.п. ноль — это отказ чтения, а не "
            "результат")
    if not legs:
        raise SystemExit("ОТКАЗ: журнала листов нет или он пуст — судить "
                         "нечем, и прочерк здесь честнее нуля")
    table = supply_table(legs)
    s["supply"] = table
    s["measurable"] = measurable(table, len({day_of(g["at"]) for g in legs}))
    log(s["measurable"]["verdict"])

    band_legs = pick_legs(legs, BAND)
    gate_legs = pick_legs(legs, GATE)
    s["counts"] = {
        "legs": len(legs), "band": len(band_legs), "gate": len(gate_legs),
        "band_syms": len({g["sym"] for g in band_legs}),
        "gate_syms": len({g["sym"] for g in gate_legs}),
        "band_pairs": len({(g["sym"], g.get("hour")) for g in band_legs}),
        "band_days": len({day_of(g["at"]) for g in band_legs}),
        "gate_days": len({day_of(g["at"]) for g in gate_legs})}
    log(f"полоса {len(band_legs)} ног на {s['counts']['band_syms']} именах, "
        f"гейт {len(gate_legs)} на {s['counts']['gate_syms']}")
    if limit:
        band_legs, gate_legs = band_legs[:limit], gate_legs[:limit]
    del legs

    if not steps & {1, 2, 3}:
        s["secs"] = round(time.time() - t0, 1)
        return s

    # --- реплей ---------------------------------------------------------
    sample, samp_info = declared_sample(band_legs, len(gate_legs),
                                        seed=SEED)
    if band_limit:
        sample = sample[:int(band_limit)]
        samp_info["capped"] = int(band_limit)
    s["sample"] = samp_info
    log(f"объявленная выборка полосы: {samp_info['taken']} из "
        f"{samp_info['have']} (хотели {samp_info['want']}, зерно {SEED})")
    # Книге (шаг 2) нужна ВСЯ полоса, а не выборка: книга есть касса на
    # подаче, и подача, урезанная выборкой, описывает другую книгу.
    want = list(sample) if not (steps & {2, 3}) else list(band_legs)
    if band_limit:
        want = want[:int(band_limit)]
    recs, rep = replay(want, ruler=ruler, src=src, log=log, mem=mem,
                       limit_mb=lim)
    s["replay"] = {k: v for k, v in rep.items() if k != "tail"}
    s["tail"] = rep.get("tail")
    if want and not recs:
        raise SystemExit(
            f"ОТКАЗ: решений полосы {len(want)}, а записей реплея ноль — "
            "баров записи нет либо источник отказал; пустота не вправе "
            "выдавать себя за результат")

    all_gate, live_info = live_recs(ruler=ruler, log=log)
    # Гейтованный набор — РОВНО те решения, что дал фильтр ног этого
    # прогона. Живой кэш шире (в нём остаются записи прежних листов), и
    # взяв его целиком, мы сравнили бы полосу с другим набором.
    gate_ids = {(g["sym"], round(float(g["at"]), 3)) for g in gate_legs}
    gate_recs = [r for r in all_gate
                 if (r["sym"], round(float(r["at"]), 3)) in gate_ids]
    live_info["matched"] = len(gate_recs)
    s["live_cache"] = live_info
    log(f"гейтованных записей из живого кэша {len(gate_recs)} из "
        f"{len(all_gate)}")
    if not gate_recs:
        raise SystemExit(
            "ОТКАЗ: в живом кэше реплея нет записей линейки "
            f"{ruler} под гейтом — сравнивать полосу не с чем")

    ctx = ctx if ctx is not None else CO.context(log=log)
    s["costs_ctx"] = {"funding_rows": (ctx or {}).get("n_funding"),
                      "error": (ctx or {}).get("error")}

    # --- шаг 1 ----------------------------------------------------------
    if 1 in steps:
        if mem:
            D10.mem_guard("шаг 1", log=log, limit=lim)
        want_ids = {(g["sym"], round(float(g["at"]), 3)) for g in sample}
        band_sample_recs = [r for r in recs
                            if (r["sym"], round(float(r["at"]), 3))
                            in want_ids]
        b_rows, b_sum = decision_rows(band_sample_recs, ctx, ruler, deposit,
                                      log=log)
        g_rows, g_sum = decision_rows(gate_recs, ctx, ruler, deposit, log=log)
        cal = calibration(g_rows, seeds=seeds)
        s["calibration"] = cal
        if not cal.get("ok"):
            raise SystemExit(
                "ОТКАЗ по калибровочной паре: " + str(cal.get("why"))
                + " — сломанная загрузка выглядит как «эффекта нет», и "
                "судить по ней нельзя")
        log("калибровочная пара сошлась: копия гейта фильтром не объявлена, "
            f"сдвиг {CAL_SHIFT:+.0%} маржи пойман")
        g_st = outcome_stats(g_rows, "гейт")
        b_st = outcome_stats(b_rows, "полоса")
        st = seed_test(g_rows, b_rows, seeds=seeds)
        s["step1"] = {
            "gate": g_st, "band": b_st, "seed": st,
            "verdict": gate_verdict(st),
            "band_alone": (
                "не измерено" if not b_st else
                ("лестница низкое RR НЕ спасает: медиана нетто-исхода "
                 f"полосы {b_st['median']:+.2%} маржи ≤ 0 — шаг 1а "
                 "закрывает механику"
                 if b_st["median"] <= 0 else
                 "лестница на низком RR в плюсе по ОДНОМУ решению: медиана "
                 f"нетто-исхода полосы {b_st['median']:+.2%} маржи > 0 — "
                 "шаг 1а механику не закрывает")),
            "lev": lev_split(g_rows, b_rows, seeds=seeds),
            "mech": mech_check(g_st, b_st),
            "costs": {"band": b_sum, "gate": g_sum}}
        log(s["step1"]["verdict"])
        # Контроль «ядро одно»: объявленные CHECK_N гейтованных решений
        # реплеятся СВОИМ проходом в СВОЙ кэш и сверяются с живым бит в
        # бит. Без этого «тем же кодом» осталось бы обещанием прозы.
        n_chk = min(int(CHECK_N), len(gate_legs))
        chk_legs = random.Random(SEED).sample(list(gate_legs), n_chk)
        chk_recs, chk_info = replay(chk_legs, ruler=ruler, src=src, log=log,
                                    path=cache_path(GATE), band=GATE,
                                    mem=mem, limit_mb=lim)
        s["cache_check"] = dict(cache_check(chk_recs, all_gate),
                                asked=n_chk, replayed=chk_info["replayed"])
        log("сверка с живым кэшем: " + s["cache_check"]["verdict"])

    # --- шаг 2 ----------------------------------------------------------
    if 2 in steps or 3 in steps:
        if mem:
            D10.mem_guard("шаг 2", log=log, limit=lim)
        sis_rows, sis_info = book_rows(recs, ruler, deposit, ctx, log=log)
        base_rows, base_info = book_rows(gate_recs, ruler, deposit, ctx,
                                         log=log)
        days = set(daily_usd(sis_rows)) & set(daily_usd(base_rows))
        sis_same = [r for r in sis_rows if day_of(r["exit_ts"]) in days]
        base_same = [r for r in base_rows if day_of(r["exit_ts"]) in days]
        sis_st = book_stats(sis_rows, deposit)
        base_st = book_stats(base_rows, deposit)
        # Знаменатель измеримости книги — те же сутки журнала листов, что
        # у шага 0: две меры «третьей части суток» с разными знаменателями
        # читались бы как одна и разошлись бы молча.
        cap_days = s["measurable"]["days_total"]
        with_tr = len(daily_usd(sis_rows))
        need = max(1, int(round(DAY_SHARE * max(1, cap_days))))
        corr, common = CE.pair_corr(daily_no(sis_rows), daily_no(base_rows))
        ticket = R.ticket(float(deposit), ruler)
        cell = sis_info["cell"]
        s["step2"] = {
            "sister": sis_st, "base": base_st,
            "sister_same_days": book_stats(sis_same, deposit),
            "base_same_days": book_stats(base_same, deposit),
            "common_days": len(days),
            "cell": cell, "one_name": sis_info["one_name"],
            "base_cell": base_info["cell"],
            "costs": sis_info["costs"],
            "load": {"ticket": ticket,
                     "mean": (round(cell["open_mean"] * ticket
                                    / float(deposit), 3)
                              if cell.get("open_mean") is not None else None),
                     "peak": (round(cell["open_max"] * ticket
                                    / float(deposit), 3)
                              if cell.get("open_max") is not None else None),
                     "open_mean": cell.get("open_mean"),
                     "open_max": cell.get("open_max"),
                     "no_cash": cell.get("no_cash"),
                     "too_small": cell.get("too_small")},
            "measurable": {
                "days_with_trades": with_tr, "days_band": cap_days,
                "need": need, "ok": with_tr >= need,
                "verdict": (f"сделки есть в {with_tr} сутках из {cap_days} "
                            f"при пороге {need} — судить есть чем"
                            if with_tr >= need else
                            f"сделки лишь в {with_tr} сутках из {cap_days} "
                            f"при пороге {need} — книгу судить НЕЧЕМ")},
            "base_worst_day": {
                "day": BASE_WORST_DAY,
                "sister": round(daily_usd(sis_rows).get(BASE_WORST_DAY), 2)
                if BASE_WORST_DAY in daily_usd(sis_rows) else None,
                "base": round(daily_usd(base_rows).get(BASE_WORST_DAY), 2)
                if BASE_WORST_DAY in daily_usd(base_rows) else None},
            "corr": (None if corr is None else round(float(corr), 3)),
            "corr_days": common,
            "book_seed": book_seed_test(sis_rows, base_rows, deposit,
                                        seeds=seeds),
            "caps": load_caps(recs, ruler, deposit, ctx=ctx, log=log)}
        log(s["step2"]["measurable"]["verdict"])

    # --- шаг 3 ----------------------------------------------------------
    if 3 in steps and s.get("step2"):
        s["step3"] = {"sister": shape(sis_rows, deposit),
                      "base": shape(base_rows, deposit)}

    s["secs"] = round(time.time() - t0, 1)
    if mem:
        D10.mem_guard("конец", log=log, limit=lim)
    return s


# --- отчёт ---------------------------------------------------------------

def _p(x, d=2):
    return "—" if x is None else f"{float(x) * 100:+.{d}f} %"


def _u(x):
    return "—" if x is None else f"{float(x):+.2f} $"


def _n(x):
    return "—" if x is None else f"{x:g}"


def _st_row(name, st):
    if not st:
        return f"| {name} | закрытых сделок нет | | | | | | | | |"
    return (f"| {name} | {st['n']} | {st['days']} | {_u(st['usd'])} "
            f"({_p(st['final'])}) | {_p(st['day_median'], 3)} | "
            f"{st['day_green']:.2f} | {_p(st['day_worst'])} | "
            f"{_n(st['bite'])} | {_u(st['usd_wo_top3d'])} | "
            f"{_u(st['usd_wo_top'])} | {_p(st['max_dd'])} | "
            f"{_p(st['max_dd_wo_worst'])} |")


def report(s):
    L = ["# Гейт RR ≥ 2 у длинной лестницы: заслонка подачи или фильтр "
         "качества", "",
         "Механика `1d5e7287`. Полоса — `" + s["band"] + "` (RR "
         f"{_n(s['bounds'][0])}…{_n(s['bounds'][1])}), край ≥ "
         f"{_n(s['edge_bp'])} б.п. Ячейка вердикта ОДНА: линейка "
         f"`{s['ruler']}`, депозит ${s['deposit']:,.0f}, деньги НЕТТО "
         "(издержки в каждой сделке). Всё остальное — диагностика без "
         "выбора.", "",
         f"Прогон {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(s['at']))}, "
         f"{s.get('secs')} с. Правила книг версии {s['rules']}, срок "
         f"{s['hold_h']} ч, билет ${s['ticket']:,.2f}.", "",
         ("**" + s["cap_why"] + ".** Числа ниже описывают урезанный "
          "набор решений и вердиктом не являются." if s.get("capped")
          else "Прогон полный: ячейка вердикта заполнена."), "",
         "Полоса здесь — ПАРАМЕТР того же фильтра ног, которым входят "
         "живые книги: границы читаются у оси `rr_band` пространства "
         "фабрики, край — у гейта книг, исход считает то же ядро "
         "(`run_d6.collect_recs` → `ladder.simulate_dca`), касса и колонки "
         "— код живых длинных книг. Второй копии расчёта нет, и это "
         "проверено тестами, а не обещано.", ""]

    m = s.get("measurable") or {}
    L += ["## Шаг 0 — подача: что лист вообще отдаёт", "",
          f"**{m.get('verdict', '—')}**", "",
          f"Прочитано листов {s['read']['hours']}, строк "
          f"{s['read']['rows']}, битых {s['read']['bad']}.", ""]
    c = s.get("counts") or {}
    if c:
        L += [f"Лонгов с краем ≥ {_n(s['edge_bp'])} б.п. — {c['legs']}; из "
              f"них полоса {c['band']} ({c['band_syms']} имён, "
              f"{c['band_pairs']} пар «имя, час», {c['band_days']} суток), "
              f"гейт {c['gate']} ({c['gate_syms']} имён, {c['gate_days']} "
              f"суток). Отношение подачи "
              f"{(c['band'] / c['gate']):.1f}×." if c.get("gate") else "", ""]
    L += ["| сутки | рука | решений | RR < 1 | RR 1…1.5 | RR 1.5…2 | "
          "RR ≥ 2 | полоса | гейт | RR нет | медиана RR |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for d in sorted(s.get("supply") or {}):
        for arm in sorted(s["supply"][d]):
            x = s["supply"][d][arm]
            sub = x["sub"]
            L.append(f"| {d} | {arm} | {x['n']} | "
                     + " | ".join(str(sub[k[0]]) for k in SUB_BANDS)
                     + f" | {x['band']} | {x['gate']} | {x['rr_unknown']} | "
                     f"{_n(x['rr_median'])} |")
    L += ["", "Колонка «RR нет» — решения, у которых отношение не "
          "измерено. Они не проходят НИ полосу, ни гейт: «не измерено» "
          "внутри фильтра есть сам по себе фильтр, и ровно так однажды "
          "подделался гейт по ставке funding.", ""]

    s1 = s.get("step1")
    if s1:
        cal = s.get("calibration") or {}
        L += ["## Шаг 1 — решение к решению", "",
              "Калибровочная пара (считается ДО меры): копия гейтованных "
              f"решений с переписанным RR — доля зёрен "
              f"{_n(cal.get('flat', {}).get('median_win'))} при объявленном "
              f"коридоре {CAL_FLAT_LO}…{CAL_FLAT_HI}; те же копии со "
              f"сдвигом {CAL_SHIFT:+.0%} маржи — "
              f"{_n(cal.get('shift', {}).get('median_win'))} при пороге "
              f"{CAL_SHIFT_MIN}. Пара сошлась, иначе прогон бы остановился.",
              "",
              "| набор | решений | измерено | медиана нетто | среднее | "
              "зелёных | худшее | доля хвоста | доливов | глубина | имён |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for nm, st in (("гейт RR ≥ 2", s1["gate"]), ("полоса RR ≤ 1.5",
                                                     s1["band"])):
            if not st:
                L.append(f"| {nm} | — | — | — | — | — | — | — | — | — | — |")
                continue
            L.append(f"| {nm} | {st['n']} | {st['measured']} | "
                     f"{_p(st['median'], 3)} | {_p(st['mean'], 3)} | "
                     f"{st['green']:.2f} | {_p(st['worst'])} | "
                     f"{st['tail_share']:.1%} | "
                     + ("—" if st['add_share'] is None
                        else f"{st['add_share']:.1%}")
                     + f" | {_n(st['depth_median'])} | {st['names']} |")
        sd = s1["seed"]
        L += ["", f"**{s1['verdict']}**", "",
              f"**{s1['band_alone']}**", "",
              f"Зёрен {sd.get('seeds')}, размер выборки {sd.get('k')} из "
              f"объединения {sd.get('union')}; разрешение доли "
              f"{_n(sd.get('resolution'))}. Медиана случайных выборок "
              f"{_p(sd.get('rnd_median_median'), 3)} против "
              f"{_p(sd.get('gate_median'), 3)} у гейта; доля хвоста "
              f"{_n(sd.get('rnd_tail_median'))} против "
              f"{_n(sd.get('gate_tail'))}.", "",
              f"**Механизм:** {s1['mech']['verdict']}", "",
              "### Внутри полос плеча", "",
              "Различие, исчезающее внутри полос плеча, есть переодетое "
              "плечо (приём портрета хвоста).", "",
              "| полоса плеча | гейт, n | полоса, n | медиана гейта | "
              "медиана полосы | доля зёрен | вердикт |",
              "|---|---:|---:|---:|---:|---:|---|"]
        for row in s1["lev"]:
            g, b = row["gate"], row["lo"]
            L.append(f"| {row['band']} | {row['gate_n']} | {row['band_n']} | "
                     + (_p(g['median'], 3) if g else "—") + " | "
                     + (_p(b['median'], 3) if b else "—") + " | "
                     + _n(row["seed"].get("median_win")) + " | "
                     + row["verdict"].split(":")[0] + " |")
        cc = s.get("cache_check") or {}
        L += ["", f"**Ядро одно?** {cc.get('verdict', '—')} — "
              f"{_n(cc.get('asked'))} гейтованных решений реплеены СВОИМ "
              f"проходом в свой кэш и сверены с живым; сверено "
              f"{_n(cc.get('common'))}, пропущено незакрытых "
              f"{_n(cc.get('open'))} и помеченных хвостом "
              f"{_n(cc.get('tail_skipped'))}.", "",
              "Про пропущенные хвостом надо сказать прямо, потому что это "
              "не мелочь учёта. Правило хвоста продолжает ленту серединой "
              "стакана после последнего бара ЗАПРОШЕННОГО окна, а окно "
              "символа задаёт набор ног, идущий в проход. Значит у "
              "позиции, чей срок упирается в конец ленты, исход зависит от "
              "того, какими ногами шёл проход, — и живой кэш книг "
              "воспроизводим не бит в бит, а с точностью до состава "
              "инкрементального прохода. Замечено этим прогоном, роль "
              "`fix`.", ""]

    s2 = s.get("step2")
    if s2:
        L += ["## Шаг 2 — книга на записи", "",
              f"**{s2['measurable']['verdict']}**", "",
              "| книга | сделок | суток | итог | медиана дня | зелёных | "
              "худший день | укус | без 3 лучших дней | без лучшего имени | "
              "просадка | просадка без худшего дня |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
              _st_row(f"сестра `{s['ruler']}_lo`", s2["sister"]),
              _st_row(f"база `{s['ruler']}`", s2["base"]),
              _st_row("сестра на общих сутках", s2["sister_same_days"]),
              _st_row("база на общих сутках", s2["base_same_days"]), ""]
        ld = s2["load"]
        L += [f"Общих суток {s2['common_days']}. Загрузка: средняя "
              f"{_n(ld['mean'])}, пиковая {_n(ld['peak'])} долей депозита "
              f"(одновременно открытых в среднем {_n(ld['open_mean'])}, в "
              f"пике {_n(ld['open_max'])}, билет ${ld['ticket']:,.2f}). "
              "Загрузка считается как «одновременно открытых × номинальный "
              "билет / депозит»: настоящая маржа считается от ТЕКУЩЕГО "
              "счёта и проседает вместе с ним, поэтому это оценка, а не "
              "касса.", "",
              f"Отказов кассы: нет денег {_n(ld['no_cash'])}, мельче "
              f"биржевого минимума {_n(ld['too_small'])}.", "",
              f"Сутки {s2['base_worst_day']['day']} (худший день базы) "
              f"отдельной строкой: сестра "
              f"{_u(s2['base_worst_day']['sister'])}, база "
              f"{_u(s2['base_worst_day']['base'])}.", "",
              f"Связь дневных денег сестры и базы: "
              f"{_n(s2['corr'])} по {s2['corr_days']} общим суткам "
              "(прочерк означает «не измерено», а не «книги "
              "независимы»).", "",
              f"**{(s2['book_seed'].get('verdict') or s2['book_seed'].get('why'))}** "
              f"(зёрен {_n(s2['book_seed'].get('seeds'))}, размер "
              f"{_n(s2['book_seed'].get('k'))}, отношение базы "
              f"{_n(s2['book_seed'].get('base_ratio'))} против медианы "
              f"случайных {_n(s2['book_seed'].get('rnd_ratio_median'))}).",
              "", "### Диагностика: форма при ограниченной загрузке", "",
              "Ячейки вердикта здесь нет. Билет остаётся билетом книги, "
              "меняется только то, сколько денег у кассы.", "",
              "| предел загрузки | взято | нет кассы | мельче минимума | "
              "итог | медиана дня | укус | просадка |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for cp in s2["caps"]:
            st = cp["stats"] or {}
            L.append(f"| ≤ {cp['cap']:.0%} | {cp['taken']} | "
                     f"{cp['no_cash']} | {cp['too_small']} | "
                     f"{_u(st.get('usd'))} | {_p(st.get('day_median'), 3)} | "
                     f"{_n(st.get('bite'))} | {_p(st.get('max_dd'))} |")
        L.append("")

    s3 = s.get("step3")
    if s3:
        L += ["## Шаг 3 — форма и правило вылета пула", "",
              "Правило взято у пула (`pool.shape_why`): медиана дня ≥ "
              f"{PL.MIN_MED_DAY:g}, укус ≤ {PL.MAX_BITE:g} по ≥ "
              f"{SB.MIN_DAYS} суткам со сделками. Здесь оно судит "
              "**запись**, то есть пересчёт по прошлому.", "",
              "| книга | суток | медиана дня | укус | зелёных | вердикт |",
              "|---|---:|---:|---:|---:|---|"]
        for nm, x in (("сестра", s3["sister"]), ("база", s3["base"])):
            L.append(f"| {nm} | {_n(x['days'])} | {_u(x['med'])} | "
                     f"{_n(x['bite'])} | {_n(x['green'])} | {x['verdict']} |")
        L += ["", f"{s3['sister']['forward']}. Заявка объявила заранее: при "
              "полной загрузке укус сестры ожидается около 20, то есть ВЫШЕ "
              f"предела {PL.MAX_BITE:g}, и как кандидат пула она, вероятно, "
              "вылетит по форме. Это ДВА разных вердикта — ответ на вопрос "
              "о подаче (шаги 1–2) и годность сестры как кандидата (шаг 3), "
              "— и печатаются они оба.", ""]

    L += ["## Чего замер НЕ говорит", "",
          "- Он не утверждает, что полоса RR ≤ 1.5 хороша сама по себе: "
          "под геометрией S8 (стоп и тейк модели) она в минусе у обеих рук, "
          "и четыре строки пула с этой полосой вылетели по форме. "
          "Различие ровно одно — лестница вместо стопа, и меряется именно "
          "оно.",
          "- Он не судит RR как признак вообще: у книги СО СТОПОМ "
          "знаменатель RR участвует в исходе, и там вывод может быть "
          "обратным.",
          "- Веса модели видели эти часы: запись — пересчёт по прошлому, и "
          "форвардного вердикта у сестры нет ни по одному шагу.",
          "- Живой журнал книг и живой кэш реплея прогон не пишет: кэш "
          "сестры лежит своим файлом со своей подписью.", ""]
    return "\n".join(L) + "\n"


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="гейт RR: подача или отбор")
    ap.add_argument("--limit", type=int, default=None,
                    help="ног на набор (смоук)")
    ap.add_argument("--band-limit", type=int, default=None,
                    help="предел ног полосы, отправляемых в реплей")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--steps", default="0,1,2,3")
    ap.add_argument("--mem-limit", type=float, default=None,
                    help="предел памяти, МБ; поднимать ОСОЗНАННО и в "
                         "тихий час — рядом сборщик и часовой цикл")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    # Каталог артефактов создаётся ДО счёта: редирект лога — тоже каталог.
    os.makedirs(OUT, exist_ok=True)
    steps = [int(x) for x in str(a.steps).split(",") if x.strip()]
    s = run(limit=a.limit, seeds=a.seeds, steps=steps,
            band_limit=a.band_limit, limit_mb=a.mem_limit)
    tag = a.tag or ("smoke" if (a.limit or a.band_limit) else "1m")
    with open(os.path.join(OUT, f"RR-supply-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, default=str)
    txt = report(s)
    with open(os.path.join(OUT, f"RR-supply-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"механика 1d5e7287: гейт RR — подача или отбор ({tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
