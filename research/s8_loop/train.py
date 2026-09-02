#!/usr/bin/env python3
"""
S8.2: цикл переобучения модели на стакане (спека 08 §5).

Один цикл: дожать сводку часов → собрать матрицы → оценить ПРЕЖНЮЮ
модель на часах, пришедших после её обучения (живой вневыборочный IC —
то, что смотрит владелец) → обучить свежие модели по всем целям →
атомарно подменить веса. Обучение на всём накопленном: честность
обеспечивается самими целями — у последних h часов форвард не закрыт
и они в обучение не попадают, а признаки смотрят только назад
(тест «будущее не трогает прошлое» в test_s8.py).

Канарейка утечки: при каждом переобучении одна модель учится на целях,
перемешанных внутри сечений. Шум зерна у такой модели ±0.01–0.015
(замер M2), поэтому канарейка кричит только на грубую течь —
|медианный IC| > 0.05. Полный нуль 3 десятью зёрнами — в вердикте §7,
здесь именно канарейка, а не критерий.

Версия модели штампуется в веса и обязана попадать в каждую бумажную
сделку (урок RULES_VERSION): сводка по смеси версий осмысленна на вид
и бессмысленна по сути.

    .venv/bin/python research/s8_loop/train.py --once
    setsid nohup .venv/bin/python research/s8_loop/train.py \
        >> research/s8_loop/out/train.log 2>&1 &
"""

import argparse
import json
import os
import pickle
import sys
import time
import warnings
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "m2_walkforward"))
sys.path.insert(0, os.path.dirname(RESEARCH))

# Проверка ДО первого тяжёлого импорта: системный python3 на сервере
# зависимостей не имеет, и голый ModuleNotFoundError уже дважды стоил
# захода на сервер впустую.
from research.common import pyenv                         # noqa: E402
from research.common import universe_filter as UF          # noqa: E402
pyenv.need("numpy")

import numpy as np                                        # noqa: E402

import books as BK                                         # noqa: E402
import bookfeat as FB                                      # noqa: E402
import gbm                                                 # noqa: E402
import nn                                                  # noqa: E402
import summary as SM                                       # noqa: E402
import sit_absorb as SA                                     # noqa: E402
import trades as TR                                         # noqa: E402
from trades import ROUND_COST_BP as TR_COST                # noqa: E402
import wf                                                  # noqa: E402

OUT = os.path.join(HERE, "out")
MODEL_DIR = os.path.join(OUT, "model")
# Боевой каталог, запомненный НА ИМПОРТЕ. Демо-прогон, песочный контур
# и тесты подменяют `MODEL_DIR`, а состав книг кандидатов лежит рядом
# с реестром книг — то есть один на все прогоны. Писать его вправе
# только боевой цикл: песочница переписала бы боевой состав книг, и
# отказ был бы невиден до следующего часа. Сравнение с этой
# константой защищает и тот тест, который о ней не знает.
LIVE_MODEL_DIR = MODEL_DIR
# Откуда берутся кандидаты и куда пишется состав их книг. Константами,
# а не выражением на месте: тест обязан подставить СВОИ пути, иначе он
# исполняет чужую дорогу — либо не исполняет её вовсе.
FACTORY_OUT = os.path.join(RESEARCH, "factory", "out")
EXTRAS_PATH = os.path.join(HERE, BK.EXTRAS_FILE)

MODEL_VERSION = 2

# Горизонт, на котором ставятся заявки (он же `SIT_SIGNAL_H` ниже:
# сигнал ситуационной книги). Квантильные цели заводятся ТОЛЬКО на нём:
# часовая и суточная книги закрываются по времени, стопа у них нет
# вовсе, а каждая лишняя цель стоит двух обучений в час — цикл и так
# опаздывает на минуты, и платить временем за уровень, которым никто
# не пользуется, нечем.
STOP_H = 4
# Доля случаев, в которых цена ВПРАВЕ зайти за стоп. Число объявлено
# до прогона и выведено из замера `s9_sweep/stops.py`, а не выбрано на
# вкус: стоп на условном среднем хода против касается 52 % сделок, и
# 37 % касаний возвращаются к цели — то есть нынешнее правило зря
# убивает каждую пятую сделку (0.52 × 0.37 ≈ 0.19). Уровень с долей
# захода 0.20 опускает это до 0.07 и не идёт дальше по двум причинам:
# риск ноги растёт ровно на величину сдвига (в том же замере плоский
# буфер глубже ×1.25 ожидание уже ухудшал), а гейт входа считает
# отношение по ИСПОЛНЯЕМОЙ геометрии — чем дальше стоп, тем меньше
# имён проходит RR ≥ 2.
STOP_TAU = 0.20
# Цель квантильной модели — та же КОЛОНКА, что у средней; отличается
# только потеря обучения. Отдельная колонка была бы вторым именем
# одних и тех же чисел, а расхождение двух копий данных в этом проекте
# уже случалось. Низкий квантиль минимума цены — стоп ЛОНГА, высокий
# квантиль максимума — стоп ШОРТА (стороны разводит `position_path`).
QUANT_TARGETS = {f"maeq_{STOP_H}h": (f"mae_{STOP_H}h", STOP_TAU),
                 f"mfeq_{STOP_H}h": (f"mfe_{STOP_H}h", 1.0 - STOP_TAU)}
# Ранжирующая цель книги в единицах собственной σ монеты. Заведена
# по замеру отбора: размах выбранной моделью монеты равен 6.1 медианы
# сечения (86 % выборов выше медианы), потому что признаки нормированы,
# а цели были сырыми. Геометрия сделки при этом НЕ трогается — стоп и
# цель остаются на сырых `mae`/`mfe`, — чтобы разница между книгами
# принадлежала ранжированию, а не другой сделке.
RANK_Z = f"fwd_{FB.SIGNAL_H}h_z"


def rank_z(h):
    """Ключ порядка сечения в единицах σ для своего горизонта.

    Функция, а не константа: книг в σ теперь несколько, и брать чужой
    горизонт значило бы упорядочивать часовую книгу мерой разброса
    четырёхчасовой.
    """
    return f"fwd_{h}h_z"


TARGETS = ([f"{k}_{h}h" for k in ("fwd", "mfe", "mae")
            for h in FB.HORIZONS] + list(QUANT_TARGETS)
           + [rank_z(h) for h in FB.HORIZONS])


def target_col(tgt):
    """Колонка целей, по которой обучается и оценивается цель `tgt`."""
    return QUANT_TARGETS.get(tgt, (tgt, None))[0]


# Правило сторон пути живёт в `trades` (общий модуль со сборщиком);
# здесь псевдонимы — вторая копия однажды переставила бы стороны.
position_path = TR.position_path
path_fields = TR.path_fields


# Турнир: две руки на одних данных, объявлены до окна вердикта.
# gbm — деревья (ML), nn — сеть (AI-рука). Прогноз до запуска записан:
# на табличных признаках и неделях данных сеть скорее проиграет.
ARMS = (("gbm", gbm.fit), ("nn", nn.fit))
# Цикл ЕЖЕЧАСНЫЙ, а не суточный (спека §5 писала «раз в сутки» про
# переобучение). Причина не в качестве весов — М2 замерил, что частота
# переобучения сама по себе не меняет ничего (+0.000…+0.004 сутки
# против месяца), — а в темпе книг: выбор и разбор идут раз в час, у
# часовой книги сделка живёт один час, и спящий сутками цикл держал бы
# её «ждёт разбора» двадцать три лишних часа. Ровно это и случилось на
# боевом контуре: разбор приходил только с деплоем.
RETRY_SEC = 3600                  # не обучился — проверить через час
# Каденция переобучения. Час — темп КНИГ, а не весов: замер
# `cycle_health` 2026-08-31 показал, что цикл перевалил за час 08-23 и
# с 08-25 не укладывается ни разу (медиана 6025 с при 3600), прогонов в
# сутки стало 10–12 вместо 24 — то есть половина часов оставалась без
# свежего листа и без цикловых выходов, а исполняет их живой
# исполнитель настоящими деньгами. Разбивка: обучение 3990 с и
# канарейка 1142 из 5207, книги 26.
#
# Свежесть весов на этот час не стоит почти ничего, и это измерено, а
# не предположено: M2 намерил, что суточное переобучение против
# месячного даёт +0.000…+0.004 IC. Значит обучение уходит из часового
# пути на объявленную каденцию, а книги, разбор и лист остаются
# ежечасными.
TRAIN_EVERY_H = 24
# Запас после закрытия часа: сначала его надо свести по всем монетам, и
# только потом обучаться. Он же есть нижняя граница запаздывания входа.
MARGIN_SEC = 120
# Предпросмотр сводку не пишет — он читает готовую, а пишет её боевой
# цикл. Значит приходить он обязан ПОСЛЕ него, иначе увидит сетку без
# только что закрывшегося часа и отстанет ровно на час. Ровно это и
# случилось на сервере: предпросмотр в 23:00:01, сведение часа 22 в
# 23:03 — и сделки, которым срок вышел в 23:00, провисели «ждёт
# разбора» до следующего часа.
PRETEST_MARGIN_SEC = 360
# Пришёл, а сводка ещё не дописана — ждать час незачем: пробуем скоро.
STALE_RETRY_SEC = 300
MIN_TRAIN_SECTIONS = 48           # меньше двух суток сечений — рано
# Пробный прогон: тот же конвейер на том, что уже накоплено, но в свой
# каталог и со своей пометкой. Порог 48 не трогается — см. `--probe`.
PROBE_MIN_SECTIONS = 4
PROBE = False
# Предпросмотр: та же модель на том, что уже накоплено, своим циклом и
# в свой каталог. Задача — показать владельцу работу обучения СЕЙЧАС, а
# не ждать четверо суток; вердикт по нему не выносится никогда.
PRETEST = False
PRETEST_MIN_SECTIONS = 4
# Режим хеджа — строкой, а не флагом: она едет в манифест, на страницу и
# в проверку смены режима. Смена этой строки означает ДРУГУЮ книгу, и
# смешивать две книги в одном счёте нельзя (см. `fresh_on_mode_change`).
HEDGE_PRETEST = "грубый: бета = 1 (посимвольная не оценима)"
HEDGE_LIVE = "включён"
CANARY_STOP = 0.05                # грубая течь; шум зерна тут ±0.015
# Меньше тысячи строк цель не обучается: гейт главной цели, пропуск
# цели в обучении и объяснение «книга ждёт» на странице обязаны мерить
# ОДНИМ числом — три разных литерала однажды разошлись бы.
MIN_TARGET_ROWS = 1000
# Бумажный счёт руки: старт $1000, 6 позиций равными долями, тейкерский
# круг 11 б.п. с позиции, без проскальзывания (сказано прямо), плечо 1.
# Счёт — наблюдение для владельца, вердикт остаётся за §7.
START_BALANCE = 1000.0
# Круг издержек — из `trades`: его читает и сборщик, переоценивая
# открытые сделки. Одно определение на двоих.
ROUND_COST_BP = TR_COST
SEED0 = 20260801


def log(m):
    print(f"[{datetime.now(timezone.utc).strftime('%m-%d %H:%M:%S')}] {m}",
          flush=True)


# --- мысли модели: перевод её состояния в трейдерские слова ------------
# Это НЕ речь модели (бустинг не говорит), а честный пересказ трёх
# измеримых вещей: чему она верит (важности), как сбылись её прошлые
# прогнозы (живой IC) и кого она выбрала бы сейчас (предсказания на
# последнем сечении). Всё, что нельзя вывести из этих чисел, в мыслях
# не появляется.
FEATURE_RU = (
    ("imb_best", "перекос у лучших цен"),
    ("imb_", "перекос глубины стакана"),
    ("depth_b", "глубина бидов"),
    ("depth_a", "глубина асков"),
    ("spread_rel", "спред"),
    ("upd_rel", "суета обновлений книги"),
    ("big_rel", "крупные уровни"),
    ("turn_rel", "оборот против обычного"),
    ("delta", "перевес агрессора в ленте"),
    ("burst", "всплески объёма"),
    ("traded_share", "непрерывность торгов"),
    ("eat_bid", "выедание бидов"),
    ("eat_ask", "выедание асков"),
    ("net_path", "чистота хода (без пилы)"),
    ("squeeze_", "зажим (сжатие диапазона)"),
    ("tilt_", "наклон сжатия"),
    ("dwell_", "проторговка (время у цены)"),
    ("range_pos", "место в суточном диапазоне"),
    ("ret_", "ход цены к своей волатильности"),
    ("beta", "связь с рынком"),
    ("age_rec", "возраст записи"),
    ("fr_bp", "ставка funding"),
    ("mins_fund", "минут до начисления funding"),
    ("oi_rel", "открытый интерес против обычного"),
    ("oi_chg", "приток/уход позиций (интерес)"),
    ("basis_bp", "базис (перп к споту)"),
    ("liq_long", "ликвидации лонгов"),
    ("liq_short", "ликвидации шортов"),
    ("liq_imb", "перекос ликвидаций"),
    ("vol_regime", "режим волатильности (день к неделе)"),
    ("hod_", "час суток"),
    ("dow", "день недели"),
    ("btc_ret", "ход BTC (лидер рынка)"),
    ("sec_ret", "ход своего сектора"),
    ("rel_sec", "отставание от сектора"),
    ("dist_round", "близость к круглому числу"),
)


def pct(bp):
    """Базисные пункты → процент движения цены, строкой.

    Решение владельца: везде, где показывается сделка, единица —
    ПРОЦЕНТ, а не базисный пункт. Процент читается как движение цены,
    базисный пункт требует пересчёта в голове.

    Внутри всё остаётся в б.п.: цели модели, издержки, формула счёта.
    Меняется только показ — единица хранения и единица показа разные
    вещи, и смешивать их значит однажды посчитать комиссию в процентах.

    Знаков после запятой два, а при мелких величинах три: у нетто после
    издержек типичное значение единицы б.п., и на двух знаках оно
    схлопнулось бы в «0.00 %» — то есть исчезло бы ровно то число,
    ради которого таблица и существует.
    """
    if bp is None:
        return "—"
    d = 2 if abs(bp) >= 10 else 3
    return f"{bp / 100.0:+.{d}f} %"


def feat_ru(name):
    for pref, ru in FEATURE_RU:
        if name.startswith(pref):
            return ru
    return name


def _ic_words(v):
    if v >= 0.03:
        return "сбывались заметно лучше случайного"
    if v >= 0.01:
        return "сбывались слабо, но в плюс"
    if v > -0.01:
        return "легли около нуля"
    return "шли мимо"


def think(prev_man, man, ic_rows, picks):
    """Мысли одного цикла. Чистая функция — закреплена тестами."""
    out = []
    ic = next((r for r in ic_rows or [] if r["target"] == "fwd_4h"), None)
    if ic:
        out.append(f"проверил вчерашние прогнозы на {ic['sections']} новых "
                   f"сечениях: направления {_ic_words(ic['median_ic'])} "
                   f"(IC {ic['median_ic']:+.3f}).")
    imp = (man.get("importance") or {}).get("fwd_4h") or {}
    top = list(imp)[:3]
    if top:
        out.append("сильнее всего сейчас смотрю на: "
                   + ", ".join(feat_ru(t) for t in top) + ".")
    prev_imp = ((prev_man or {}).get("importance") or {}).get("fwd_4h")
    if prev_imp and imp:
        diff = [(k, imp.get(k, 0.0) - prev_imp.get(k, 0.0))
                for k in set(imp) | set(prev_imp)]
        up = max(diff, key=lambda x: x[1])
        dn = min(diff, key=lambda x: x[1])
        if up[1] > 0.02:
            out.append(f"после переобучения стал больше доверять: "
                       f"{feat_ru(up[0])} (+{up[1]:.2f} веса), меньше — "
                       f"{feat_ru(dn[0])} ({dn[1]:+.2f}).")
    if picks:
        long_s = ", ".join(
            f"{p['sym'].replace('USDT','')} (жду {pct(p['fwd'])} за "
            f"4 ч, путь против до {pct(p['mae'])})"
            for p in picks["long"])
        short_s = ", ".join(
            f"{p['sym'].replace('USDT','')} ({pct(p['fwd'])}"
            + (f", путь против до {pct(p['mae'])}"
               if p.get("mae") is not None else "") + ")"
            for p in picks["short"])
        out.append(f"если бы торговал сейчас: лонг — {long_s}; "
                   f"шорт — {short_s}. Это ожидание в среднем, не "
                   f"обещание пути.")
        odds = [(p.get("odd"), p["sym"])
                for p in (picks.get("long") or []) +
                (picks.get("short") or []) if p.get("odd") is not None]
        if odds:
            avg = sum(o for o, _ in odds) / len(odds)
            worst = max(odds)
            out.append(
                f"новизна выбора: в среднем {avg * 100:.0f} % признаков "
                f"у выбранных монет вне того, что я видел в обучении"
                + (f"; самый незнакомый — "
                   f"{worst[1].replace('USDT', '')} "
                   f"({worst[0] * 100:.0f} %)" if worst[0] > 0 else "")
                + ". На новизне мои прогнозы надёжны меньше — это "
                  "замер, торговлю он пока не ограничивает.")
    can = man.get("canary_ic")
    if can is not None:
        # Разброс по зёрнам — часть вердикта, а не украшение: если он
        # шире порога, проверка на такой выборке ничего не различает, и
        # «чиста» было бы обещанием, которого замер не даёт.
        spread = man.get("canary_spread") or 0.0
        weak = spread > CANARY_STOP
        out.append(
            f"проверка на шум "
            f"{'чиста' if abs(can) <= CANARY_STOP else 'ПОДНЯТА'} "
            f"({can:+.3f}"
            + (f", разброс по {man.get('canary_seeds')} зёрнам "
               f"{spread:.3f}" if spread else "") + "): "
            + ("разброс шире порога — на такой выборке проверка ловит "
               "только грубую течь, слабую не увидит."
               if weak else
               "на перемешанных данных я бы ничего не «увидел» — "
               "значит то, что вижу, не выдумка конвейера."))
    if not prev_man:
        out.insert(0, f"первое обучение: {man.get('sections')} сечений по "
                      f"{man.get('symbols')} монетам. Пока выборка "
                      f"короткая — выводы будут гулять, это нормально.")
    return out


def load_matrices(sum_dir):
    """Сводки всех символов → словарь матриц (символы, часы).

    Сетка часов общая и непрерывная от первого до последнего часа:
    дыра записи — колонка NaN, а не выпавшая колонка. Склей мы только
    имеющиеся часы, форвард через дыру склеил бы вечер с утром — тот же
    дефект, что `diff` по дырявым барам, закрытый в R1.
    """
    rows_by_sym = {}
    hours = set()
    fields_seen = set()
    try:
        symbols = sorted(os.listdir(sum_dir))
    except OSError:
        return None, [], []
    for sym in symbols:
        rr = []
        sdir = os.path.join(sum_dir, sym)
        for fn in sorted(os.listdir(sdir)):
            if not fn.endswith(".jsonl"):
                continue
            with open(os.path.join(sdir, fn), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        rr.append(r)
                        hours.add(r["hour"])
                        # Состав полей — по ВСЕМ строкам: сводка
                        # расширялась по ходу записи, и поле, которого
                        # нет в первой строке, иначе выпало бы молча.
                        fields_seen.update(r)
                    except (ValueError, KeyError):
                        continue
        if rr:
            rows_by_sym[sym] = rr
    if not rows_by_sym:
        return None, [], []
    h0 = min(hours)
    h1 = max(hours)
    grid = []
    t = datetime.strptime(h0, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    end = datetime.strptime(h1, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    while t <= end:
        grid.append(t.strftime("%Y-%m-%d-%H"))
        t = datetime.fromtimestamp(t.timestamp() + 3600, timezone.utc)
    idx = {h: i for i, h in enumerate(grid)}
    syms = sorted(rows_by_sym)
    fields = fields_seen
    fields.discard("hour")
    mats = {f: np.full((len(syms), len(grid)), np.nan) for f in fields}
    for si, sym in enumerate(syms):
        # Строки идут в порядке дозаписи; пересведённый час стоит позже
        # исходного и побеждает — на это опирается summary --redo.
        for r in rows_by_sym[sym]:
            j = idx.get(r["hour"])
            if j is None:
                continue
            for f in fields:
                v = r.get(f)
                if isinstance(v, (int, float)):
                    mats[f][si, j] = v
    mats.update(context_mats(syms, grid))
    return mats, syms, grid


def context_mats(syms, grid):
    """Контекст, который несут не сводки, а сами оси: время и сектор.

    hour_ts — начало часа (epoch), из него признаки времени; sector —
    код группы A3 (NaN у неразмеченных); is_btc — флаг ряда BTCUSDT
    для признака «ход лидера». Всё это входит в общий словарь матриц,
    чтобы один тест на заглядывание накрывал и эти признаки.
    """
    S = len(syms)
    ts = np.array([datetime.strptime(h, "%Y-%m-%d-%H")
                   .replace(tzinfo=timezone.utc).timestamp()
                   for h in grid])
    out = {"hour_ts": np.tile(ts, (S, 1))}
    sector = np.full((S, 1), np.nan)
    try:
        sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))
        from collect import symbol_groups
        for gi, g in enumerate(symbol_groups(syms)):
            if g["id"] == "other":
                continue                 # «прочие» — не сектор, а незнание
            for s in g["symbols"]:
                sector[syms.index(s), 0] = float(gi)
    except Exception as e:                                 # noqa: BLE001
        log(f"группы недоступны, сектор пуст: {type(e).__name__}: {e}")
    out["sector"] = sector
    out["is_btc"] = np.array(
        [[1.0 if s == "BTCUSDT" else 0.0] for s in syms])
    return out


def assemble(mats, horizons=None):
    """Матрицы сводки → (X, имена признаков, цели, elig, r).

    `horizons` — сетка горизонтов целей для зонда; умолчание — ось
    наблюдения FB.HORIZONS, и оно обязано давать прежнее бит в бит.
    """
    feats, r, elig = FB.feature_pack(mats)
    beta = feats["beta"]
    if PRETEST:
        # Предпросмотр живёт на недельной записи, а бете нужно
        # FB.BETA_MIN часов — значит `fwd_*` пусты, а без них нет ни
        # выбора монет, ни счёта, то есть смотреть не на что.
        #
        # Подставляется ЕДИНИЦА там, где беты нет, и это не произвол:
        # средняя бета по сечению равна единице ПО ПОСТРОЕНИЮ — каждый
        # актив входит в волну с весом 1/n. R1 это и намерил на живых
        # данных: медиана по 48 окнам 1.015, диапазон 0.954–1.042.
        #
        # Первая версия ставила ноль как «честное отключение хеджа».
        # Формулировка была честной, выбор — хуже доступного: с нулём
        # цель есть сырая доходность, в которой сидит ход рынка за час,
        # общий для всех имён. Кросс-секционные признаки предсказать его
        # не могут в принципе, то есть это чистый шум в метке — а R1
        # намерил его долю: около 65 % дисперсии доходностей объясняет
        # волна. Единица убирает этот шум бесплатно.
        #
        # Чего замена НЕ меняет: выбор монет. Волна в данный час общая
        # для всех имён, сечение ранжируется, а вычитание одного и того
        # же числа у всех порядок не трогает.
        #
        # Хедж всё равно грубый — посимвольной беты нет, — поэтому
        # пометка едет во все артефакты и на страницу, а не в
        # комментарий.
        beta = np.where(np.isfinite(beta), beta, 1.0)
    targets = FB.target_pack(mats, r, elig, beta, horizons=horizons)
    names = sorted(feats)
    S, H = mats["mid_close"].shape
    x = np.stack([feats[n] for n in names], axis=-1)    # (S, H, F)
    return x, names, targets, elig


def flatten(x, y, elig):
    """(S, H) → строки обучения: только сечения, только закрытые цели."""
    m = elig & np.isfinite(y)
    return x[m], y[m], m


def novelty_bounds(x, elig):
    """Диапазон обучения по каждому признаку: 0.5–99.5 процентили по
    строкам сечений. Это ЗАМЕР, а не правило (идея «данные не похожи
    на обучение — не торгуй» из обзора публичных решений): любое
    правило «не торгуй» механически красит просадку, и вводить его
    можно только после сравнения со случайным гейтом той же доли —
    урок нуля 4 гипотезы 4. Пока — только метка на каждом выборе.
    """
    xe = x[elig]
    with warnings.catch_warnings():
        # Колонка целиком из NaN законна (запись признака ещё не
        # началась) — у неё нет диапазона, новизна по ней не судится.
        warnings.simplefilter("ignore", RuntimeWarning)
        lo = np.nanpercentile(xe, 0.5, axis=0)
        hi = np.nanpercentile(xe, 99.5, axis=0)
    return lo, hi


def novelty(xrow, lo, hi):
    """Доля признаков монеты вне диапазона обучения, 0…1.

    Считаются только измеримые признаки: NaN — «данных нет», у него
    своя дорожка (NaN-корзина у деревьев, флаг у сети), новизной он
    не является. Судить не по чему — None, а не ноль: ноль означал бы
    «всё знакомо», чего никто не проверял.
    """
    fin = np.isfinite(xrow) & np.isfinite(lo) & np.isfinite(hi)
    if not fin.any():
        return None
    out = (xrow[fin] < lo[fin]) | (xrow[fin] > hi[fin])
    return float(out.mean())


def section_ic(pred_mat, y_mat, elig, cols):
    out = []
    for j in cols:
        m = elig[:, j] & np.isfinite(y_mat[:, j]) & np.isfinite(
            pred_mat[:, j])
        if m.sum() < FB.MIN_SECTION:
            continue
        out.append(wf.spearman(pred_mat[m, j], y_mat[m, j]))
    return [v for v in out if np.isfinite(v)]


def predict_matrix(model, x, elig):
    S, H, Fn = x.shape
    pred = np.full((S, H), np.nan)
    m = elig.copy()
    if m.any():
        pred[m] = model.predict(x[m])
    return pred


PREDS_KEEP_H = 48                 # дольше держать нечего — см. score_preds
WHY_TOP = 3                       # признаков в объяснении сделки
WHY_FLOOR_BP = 1.0                # мельче — шум, а не довод


def explain_rows(model, xj, names):
    """«Почему прогноз такой»: главные признаки КАЖДОЙ строки, в б.п.

    Просьба владельца: сделка обязана нести объяснение, почему модель
    открыла её именно здесь. Глобальная важность на этот вопрос не
    отвечает — она одна на все сделки часа. Здесь вклад признаков в
    ЭТОТ прогноз: у деревьев — точное разложение по пути (тождество
    под тестом), у сети — замена признака медианой обучения, мера
    грубее и подписывается так же честно.

    Возвращает список списков `[[имя, б.п.], …]` по строкам либо
    `None` — у весов прежнего образца разложения нет, и выдумывать
    его нельзя. Зовётся ТОЛЬКО для целей квадратичной потери: у
    квантильной листья — квантили, и разложение по средним было бы
    числами без смысла.

    Второй ответ — СИТУАЦИЯ, словами владельца: выедение стакана,
    ликвидации, зажим, наклонка. У модели нет дискретных стратегий, но
    вклад раскладывается по семействам признаков (`FB.family`), и
    доминирующее семейство — честное имя того, на чём стоит прогноз.
    Возвращаются два верхних с долями; страница обязана подписывать
    это как чтение вкладов, а не как выбранную стратегию.
    """
    fn = getattr(model, "contrib", None)
    if fn is None:
        return None, None
    c = fn(xj)
    if c is None:
        return None, None
    whys, setups = [], []
    for i in range(len(xj)):
        idx = np.argsort(-np.abs(c[i]))[:WHY_TOP]
        whys.append([[names[j], round(float(c[i][j]), 1)]
                     for j in idx
                     if abs(c[i][j]) >= WHY_FLOOR_BP])
        fam = {}
        for j in range(len(names)):
            v = abs(float(c[i][j]))
            if v > 0:
                k = FB.family(names[j])
                fam[k] = fam.get(k, 0.0) + v
        tot = sum(fam.values())
        top = sorted(fam.items(), key=lambda kv: -kv[1])[:2]
        setups.append([[k, round(v / tot, 2)] for k, v in top
                       if tot and v / tot >= 0.15])
    return whys, setups



def save_preds(arm, hour, syms, rows_m, pred, target="fwd_4h"):
    """Сохранить ВЕСЬ вектор предсказаний сечения, а не только выбор.

    Живой вневыборочный IC иначе не считается вовсе, и это не «мало
    данных», а конструкция. `eval_previous` оценивает прежние веса на
    часах СТРОГО ПОСЛЕ их обучения; при переобучении каждый час такой
    час ровно один — последний, — а у него форвард ещё не закрыт.
    Цель `NaN`, IC пуст, файл не пишется. И так каждый раз: пустая
    панель выглядит как «ещё рано», хотя измерение невозможно.

    Здесь наоборот: вектор кладётся сейчас, а оценивается через
    горизонт, когда факт станет известен. Он вневыборочный по
    построению — строка последнего часа в обучение не попадала, её
    цель на момент обучения была пуста.

    Берётся ТОТ ЖЕ вектор, из которого сделан выбор монет, поэтому IC
    описывает качество ровно того ранжирования, которое торгуется, а не
    соседнего. Разбор по шести выбранным именам этого не заменяет:
    ранговая корреляция по шести точкам — не мера.
    """
    rec = {"arm": arm, "hour": hour, "target": target,
           "syms": [syms[i] for i in rows_m],
           "pred": [round(float(v), 4) for v in pred]}
    with open(os.path.join(MODEL_DIR, "preds.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def score_preds(targets, elig, grid, syms, log_):
    """Оценить сохранённые векторы, у которых форвард уже закрылся.

    Возвращает строки того же вида, что `eval_previous`, и дописывает
    их в общую историю IC. Поле `kind` их различает: `section` — этот
    замер, один час на запись; `window` — прежние веса на всех часах
    после обучения. Две разные меры в одном списке без метки однажды
    были бы сложены в одно среднее.

    Оценённые записи из файла убираются. Записи старше `PREDS_KEEP_H`
    часов выбрасываются с сообщением: час мог выпасть из сетки, и
    молча копить неоценимое значило бы растить файл вечно, делая вид,
    что замер ещё впереди.
    """
    path = os.path.join(MODEL_DIR, "preds.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            recs = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []
    if not recs:
        return []
    col = {h: j for j, h in enumerate(grid)}
    si = {s: i for i, s in enumerate(syms)}
    newest = grid[-1] if grid else ""
    rows, keep, dropped = [], [], 0
    for r in recs:
        j = col.get(r.get("hour"))
        y = targets.get(r.get("target"))
        if j is None or y is None:
            # Часа нет в сетке — оценить нечем. Свежий подождёт,
            # старый выбрасывается.
            if r.get("hour", "") and _hours_apart(r["hour"], newest) \
                    > PREDS_KEEP_H:
                dropped += 1
            else:
                keep.append(r)
            continue
        idx = [(si[s], p) for s, p in zip(r["syms"], r["pred"])
               if s in si]
        idx = [(i, p) for i, p in idx
               if elig[i, j] and np.isfinite(y[i, j])]
        if len(idx) < FB.MIN_SECTION:
            # Форвард ещё не закрыт — ждём. Если ждать уже поздно,
            # запись уходит, и это видно числом, а не тишиной.
            if _hours_apart(r["hour"], newest) > PREDS_KEEP_H:
                dropped += 1
            else:
                keep.append(r)
            continue
        ii = np.array([i for i, _ in idx])
        pp = np.array([p for _, p in idx], dtype=float)
        ic = wf.spearman(pp, y[ii, j])
        if not np.isfinite(ic):
            dropped += 1
            continue
        rows.append({"arm": r["arm"], "target": r["target"],
                     "kind": "section", "hour": r["hour"],
                     "median_ic": round(float(ic), 4),
                     "sections": 1, "names": len(ii)})
    if dropped:
        log_(f"векторов предсказаний выброшено без оценки: {dropped} "
             f"(старше {PREDS_KEEP_H} ч или сечение уже: "
             f"нужно {FB.MIN_SECTION} имён)")
    if rows:
        with open(os.path.join(MODEL_DIR, "ic_history.jsonl"), "a",
                  encoding="utf-8") as f:
            at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            for r in rows:
                r["at"] = at
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        for arm, _ in ARMS:
            mine = [r["median_ic"] for r in rows
                    if r["arm"] == arm and r["target"] == "fwd_4h"]
            if mine:
                log_(f"живой IC [{arm}]: fwd_4h "
                     f"{float(np.median(mine)):+.4f} по {len(mine)} "
                     f"закрывшимся сечениям")
    if len(keep) != len(recs):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    return rows


def _hours_apart(a, b):
    """Сколько часов между двумя ключами часа. Не смогли — считаем много."""
    try:
        ta = datetime.strptime(a, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
        tb = datetime.strptime(b, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
        return abs((tb - ta).total_seconds()) / 3600.0
    except (ValueError, TypeError):
        return float("inf")


def eval_previous(x, targets, elig, grid, log_):
    """Живой вневыборочный IC: прежние веса на часах после их обучения."""
    man_path = os.path.join(MODEL_DIR, "manifest.json")
    try:
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
        upto = man["trained_upto"]
    except (OSError, ValueError, KeyError):
        return []
    cols = [j for j, h in enumerate(grid) if h > upto]
    if not cols:
        return []
    rows = []
    for arm, _ in ARMS:
        for tgt in TARGETS:
            wpath = os.path.join(MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            try:
                with open(wpath, "rb") as f:
                    saved = pickle.load(f)
            except OSError:
                continue
            pred = predict_matrix(saved["model"], x, elig)
            ics = section_ic(pred, targets[target_col(tgt)], elig, cols)
            if not ics:
                continue
            rows.append({"arm": arm, "target": tgt,
                         "version": saved.get("version"),
                         "trained_upto": upto,
                         "median_ic": round(float(np.median(ics)), 4),
                         "sections": len(ics)})
    if not rows:
        return []
    with open(os.path.join(MODEL_DIR, "ic_history.jsonl"), "a",
              encoding="utf-8") as f:
        at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        for r in rows:
            r["at"] = at
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    for arm, _ in ARMS:
        ml = next((r for r in rows if r["target"] == "fwd_4h"
                   and r.get("arm") == arm), None)
        if ml:
            log_(f"живой IC [{arm}]: fwd_4h {ml['median_ic']:+.4f} на "
                 f"{ml['sections']} новых сечениях")
    return rows


CANARY_SEEDS = 5


def canary_many(x, targets, elig, grid, seed, log_, name, seeds):
    """Канарейка несколькими зёрнами: среднее — оценка, разброс — шум.

    На малой выборке одна канарейка кричит от собственного шума, а не
    от течи: её медианный IC есть медиана по сечениям, и стандартная
    ошибка растёт как `1/√числа сечений`. На девяти сечениях это
    сравнимо с самим порогом 0.05, то есть одиночный замер вердикта не
    несёт — проверено сразу: на шестидесяти часах синтетики канарейка
    закричала при заведомо исправном конвейере.

    Отключать проверку нельзя — она и есть защита от течи. Правильный
    ход тот же, что вынес R3: судить по расстоянию от СРЕДНЕГО
    распределения зёрен, а не по одному броску. Настоящая течь смещает
    все зёрна в одну сторону, шум — нет.
    """
    vals = []
    for k in range(seeds):
        y = targets[target_col(name)]
        vals.append(canary(x, y, elig, grid, seed + 1000 * k, log_,
                           name=name))
    vals = [v for v in vals if np.isfinite(v)]
    if not vals:
        return float("nan"), float("nan"), 0
    mean = float(np.mean(vals))
    spread = float(np.max(vals) - np.min(vals)) if len(vals) > 1 else 0.0
    log_(f"канарейка по {len(vals)} зёрнам: среднее {mean:+.4f}, "
         f"разброс {spread:.4f} (одиночный замер на такой выборке "
         f"вердикта не несёт); зёрна "
         f"{', '.join(f'{v:+.4f}' for v in vals)}")
    # Сами зёрна возвращаются, а не только сводка: течь смещает ВСЕ в
    # одну сторону, шум разбрасывает. Различить это по среднему и
    # размаху нельзя, а по списку — можно, и он обязан лежать в
    # артефакте, иначе диагноз потребует повторного прогона.
    return mean, spread, len(vals), [round(v, 4) for v in vals]


def canary_verdict(med):
    """Три состояния канарейки, а не два.

    `NaN` означает «проверка не считалась», и это НЕ «прошла».
    Канарейка считается по `fwd_4h` — остатку к волне, — а тому нужна
    бета, бете нужно `FB.BETA_MIN` часов истории на монету. Пока их
    нет, цель пуста и медиана выходит `NaN`.

    Прежнее условие было слитным (`isfinite(med) and |med| > порог`) и
    читало `NaN` как «крика не было»: веса записывались, а потом вели
    бы бумажные счета без единой проверки на течь. Найдено пробным
    прогоном на восьми сечениях, но существенно для боевого: 48 сечений
    меньше, чем BETA_MIN = 96 часов, то есть первое настоящее обучение
    случилось бы ровно в этом состоянии.
    """
    if not np.isfinite(med):
        return "не считалась"
    return "кричит" if abs(med) > CANARY_STOP else "молчит"


def canary_target(targets, elig, want="fwd_4h",
                  need=MIN_TARGET_ROWS):
    """На какой цели считать канарейку.

    Канарейка ловит течь конвейера — нормировку на будущем и прочее, —
    и для этого годится ЛЮБАЯ цель с достаточным числом строк.
    Привязка к `fwd_4h` была моим упрощением, и она обошлась дорого:
    `fwd_4h` есть остаток к волне, ему нужна бета, бете нужны
    `FB.BETA_MIN` часов, — и на молодой записи проверка на течь
    оказывалась невозможна ровно тогда, когда конвейер только что
    переписали и проверять надо больше всего.

    Возвращает имя цели или `None`, если не годится ни одна.
    """
    # Квантильные цели канарейке не нужны: колонка у них та же, что у
    # средних, и течь конвейера они ловили бы дважды одними данными.
    for name in [want] + [t for t in TARGETS
                          if t != want and t not in QUANT_TARGETS]:
        y = targets.get(name)
        if y is None:
            continue
        if int((elig & np.isfinite(y)).sum()) >= need:
            return name
    return None


def canary(x, y, elig, grid, seed, log_, name="fwd_4h"):
    """Обучение на перемешанных целях: кричит только на грубую течь."""
    day_idx = np.broadcast_to(np.arange(len(grid)), elig.shape)
    m = elig & np.isfinite(y)
    xs, ys = x[m], y[m].copy()
    secs = day_idx[m]
    rng = np.random.default_rng(seed)
    for j in np.unique(secs):
        sel = np.flatnonzero(secs == j)
        ys[sel] = ys[sel][rng.permutation(len(sel))]
    model = gbm.fit(xs, ys, seed=seed + 1)
    pred = np.full(elig.shape, np.nan)
    pred[m] = model.predict(xs)
    ics = section_ic(pred, y, elig, list(range(len(grid))))
    med = float(np.median(ics)) if ics else float("nan")
    log_(f"канарейка (перемешанные цели, {name}): "
         f"медианный IC {med:+.4f}")
    return med


def write_readiness(syms, grid, per_hour, n_sections, n_feat,
                    hist_h, log_):
    """Готовность к обучению — файлом, а не строкой в журнале.

    Это третий раз, когда одна и та же слепота стоит суток. Сбор
    выглядел исправным, страница показывала живые числа, а сечений было
    ноль — узнать об этом можно было только зайдя на сервер и прочитав
    журнал цикла. Признак результата обязан лежать там же, где его
    смотрят: файл читается страницей через `/model`.

    Пишутся не итоги, а разложение по часам: ноль сечений при живой
    записи и ноль при мёртвой выглядят одинаково, а «имён в часе 12 при
    пороге 30» и «имён в часе 0» — уже разные диагнозы.
    """
    os.makedirs(MODEL_DIR, exist_ok=True)
    hours = [{"h": h, "n": int(v)} for h, v in zip(grid, per_hour)]
    out = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbols": len(syms), "hours": len(grid),
        "sections": n_sections, "need": MIN_TRAIN_SECTIONS,
        "min_section": FB.MIN_SECTION, "features": n_feat,
        # Сечений мало — не единственное, чего можно ждать. Главная цель
        # `fwd_4h` есть остаток к волне, ей нужна бета, а бете —
        # BETA_MIN часов годной истории НА МОНЕТУ. Сорок восемь сечений
        # меньше девяноста шести, то есть по одному счётчику ждать
        # осталось двое суток, а по другому четверо. Показывать надо оба,
        # иначе «обучение началось, а выборов нет» выглядит поломкой.
        "beta_min_hours": FB.BETA_MIN,
        "hours_per_symbol": int(hist_h),
        "pretest": PRETEST,
        "by_hour": hours[-72:],
    }
    tmp = os.path.join(MODEL_DIR, "readiness.json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(MODEL_DIR, "readiness.json"))
    except OSError as e:
        log_(f"готовность записать не вышло: {e}")


def fresh_on_mode_change(mode, log_=None):
    """Сменился режим хеджа — прежние выборы и счёт отставляются в архив.

    Книга с хеджем и книга без него — разные книги. Сложить их в одну
    кривую счёта значило бы получить число, которого не было ни у той,
    ни у другой: кривая считается чистой функцией по ВСЕМ выборам
    каталога, и старые записи молча вошли бы в новый счёт.

    Это тот же урок, что «сводка без указания разрешения»: прогон на 1m
    молча затёр прогон на 15m, потому что признаком результата служило
    имя файла, а не его содержимое. Здесь наоборот — содержимое (режим
    в манифесте) решает судьбу каталога.

    Каталог не удаляется, а переименовывается: старая книга остаётся
    читаемой, если понадобится сравнить.
    """
    man = os.path.join(MODEL_DIR, "manifest.json")
    try:
        with open(man, encoding="utf-8") as f:
            was = (json.load(f) or {}).get("hedge")
    except (OSError, ValueError):
        return None                    # каталога нет или он пуст — нечего
    if not was or was == mode:
        return None
    # Имя архива выводится из ПРЕЖНЕГО режима, а не из времени: так
    # видно, что именно отложено, и повторный запуск не плодит копии.
    tag = "".join(c if c.isalnum() else "_" for c in was)[:40]
    dst = f"{MODEL_DIR}.was-{tag}"
    n = 0
    while os.path.exists(dst):
        n += 1
        dst = f"{MODEL_DIR}.was-{tag}-{n}"
    try:
        os.rename(MODEL_DIR, dst)
    except OSError as e:
        if log_:
            log_(f"режим хеджа сменился, но каталог не отставить: {e}")
        return None
    if log_:
        log_(f"режим хеджа сменился ({was} → {mode}) — прежние выборы и "
             f"счёт отставлены в {os.path.basename(dst)}, книга "
             f"начинается заново")
    return dst


def tradable_rows(rows_m, syms, ref=None):
    """Строки сечения, которыми МОЖНО торговать: не-крипто отсечено.

    Фильтр общий со сборщиком (`research/common/universe_filter`) —
    два определения «не-крипто» однажды разошлись бы, и модель выбирала
    бы то, чего сборщик не пишет. Отсечение стоит на ВЫБОРЕ, а не на
    обучении: ряды исключённых уходят из матриц сами вместе с
    прекращением записи, а выдёргивать их из истории значило бы менять
    выборку задним числом.
    """
    ref = UF.non_crypto_set() if ref is None else ref
    return np.array([j for j in rows_m
                     if not UF.is_non_crypto(syms[j], ref)], dtype=int)


def write_outcome(reason, **nums):
    """Чем кончился ЭТОТ цикл — отдельным файлом, всегда.

    Манифест пишется только при успехе, а готовность — в начале цикла.
    Значит у прогона, остановленного канарейкой, свежим остаётся один
    файл из двух, и отчёт по манифесту рассказывает про ПРОШЛЫЙ прогон:
    те же веса, те же важности, та же строка «цикл занял 4 с».
    Предупреждения по времени мало — судить о шагах всё равно не по
    чему.

    Поэтому исход пишется всегда и отдельно: он и есть ответ на вопрос
    «что сделал этот запуск», не выводимый ни из манифеста, ни из
    готовности.
    """
    os.makedirs(MODEL_DIR, exist_ok=True)
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "reason": reason, "probe": PROBE, "pretest": PRETEST,
           **nums}
    tmp = os.path.join(MODEL_DIR, "last_run.json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(MODEL_DIR, "last_run.json"))
    except OSError:
        pass
    return out


def _read_jsonl(path):
    """Строки jsonl; битая строка пропускается, нет файла — пусто."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


# --- книги турнира темпов ---------------------------------------------
# Одни веса — несколько книг: цели уже обучаются на всех горизонтах
# наблюдения (`FB.HORIZONS`), а выбор и разбор до сих пор жили только у
# 4-часовой. Книга каждого горизонта — свой каталог со своими выборами,
# разборами и счетами; главной остаётся 4-часовая (`model`) — её ведёт
# тень бота, и её имя менять нельзя. Логика выбора, разбора и счёта
# ОДНА на все книги — вторая копия расчётного ядра запрещена правилами
# проекта, и различия между книгами исчерпываются параметром горизонта.

# Решение владельца (2026-08-11): книги 4 ч, 1 ч и ситуационная
# упорядочиваются в единицах СОБСТВЕННОЙ волатильности монеты; у 24 ч
# прежний порядок остаётся, а рядом заводится второй вариант в σ —
# контрольная пара, на которой вопрос «помогает ли per σ» и будет
# решаться дальше. Парный замер на 134 общих часах преимущества по
# доходности не показал (доля часов 0.515, интервал накрывает ноль);
# решение принято по доводу о РИСКЕ: книга в σ берёт спокойные имена,
# потолок на имя связывает её вчетверо реже, и без лучшего имени она
# остаётся положительной.
#
# Карта одна на весь цикл: порядок сечения — свойство книги, и
# перечислять его по месту вызова значило бы завести второй список,
# который однажды разойдётся с первым (как уже было со списком книг в
# четырёх местах).
RANK_BY_HORIZON = {1: True, 4: True, 24: False}


def rank_key_for(h, sigma=None):
    """Ключ порядка сечения книги горизонта `h`.

    `None` — порядок по сырому прогнозу. `sigma=True/False` перебивает
    карту: у 24 ч живут ОБА варианта, и второй просит порядок в σ явно.
    """
    want = RANK_BY_HORIZON.get(h, False) if sigma is None else sigma
    return rank_z(h) if want else None


def book_key(h, sigma=False):
    """Ключ книги по горизонту и порядку сечения.

    Соглашение (h, σ) → ключ живёт здесь, а имя каталога — в реестре:
    цикл, страницы и дерево обязаны звать книгу одним каталогом, и
    вторая запись имени однажды развела бы их — цикл писал бы туда,
    куда страница не смотрит.
    """
    if sigma and not RANK_BY_HORIZON.get(h, False):
        return "z"
    return "h4" if h == TR.HOLD_H else f"h{h}"


def book_dir(h, sigma=False):
    """Каталог книги горизонта `h` часов рядом с главным каталогом.

    У книги 24 ч вариант в σ живёт своим каталогом: две книги в одном
    означали бы смешанную историю, по которой ничего не сравнить.
    """
    return MODEL_DIR + BK.suffix(book_key(h, sigma))


def review_arm(mdir, arm, hold_h, targets, si, grid, book_root, log_):
    """Разобрать все неразобранные выборы одной руки одной книги.

    Цель разбора — `fwd_{hold_h}h`: книга меряется тем горизонтом, на
    который выбирала. Возвращает строки последнего записанного разбора
    (мысли главной книги пересказывают именно его).
    """
    y = targets.get(f"fwd_{hold_h}h")
    if y is None:
        return None
    all_picks = _read_jsonl(os.path.join(mdir, "picks.jsonl"))
    reviewed = {(r.get("arm") or "gbm", r.get("hour"))
                for r in _read_jsonl(os.path.join(mdir, "review.jsonl"))}
    review = None
    # По возрастанию часа: счёт складывается последовательно, и
    # порядок сделок в нём обязан быть хронологическим.
    pend = sorted(
        (p for p in all_picks
         if (p.get("arm") or "gbm") == arm
         and (arm, p.get("hour")) not in reviewed
         and p.get("hour") in grid),
        key=lambda p: p.get("hour") or "")
    for lp in pend:
        j = grid.index(lp["hour"])
        rows_rv = []
        for side in ("long", "short"):
            for pk in lp.get(side) or []:
                i = si.get(pk["sym"])
                if i is None:
                    continue
                got = y[i, j]
                if np.isfinite(got):
                    rr = {"sym": pk["sym"], "side": side,
                          "expected": round(pk["fwd"], 1),
                          "got": round(float(got), 1)}
                    # Новизна едет из выбора в разбор: вопрос
                    # «сбывается ли хуже на незнакомом» отвечается
                    # соединением этих двух полей, и делать его
                    # руками по двум файлам никто не станет.
                    if pk.get("odd") is not None:
                        rr["odd"] = pk["odd"]
                    rows_rv.append(rr)
        if rows_rv:
            # В разбор кладётся только ФАКТ: движение цены и книга в
            # момент выхода. Денег здесь нет — они зависят от размера
            # позиции, а размер задаётся счётом, который считается по
            # ВСЕЙ истории сразу (`trades.account`). Класть сюда
            # деньги значило бы завести второе определение размера.
            out_ts = TR.hour_end(lp["hour"])
            out_ts = (out_ts + hold_h * 3600) if out_ts else None
            bk_out = stamp_book([r["sym"] for r in rows_rv], out_ts,
                                book_root, log_, "выхода")
            for r in rows_rv:
                r["net"] = round((1 if r["side"] == "long" else -1)
                                 * r["got"] - ROUND_COST_BP, 1)
                if r["sym"] in bk_out:
                    r["cum"] = bk_out[r["sym"]]
            with open(os.path.join(mdir, "review.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(
                    {"arm": arm, "hour": lp["hour"],
                     "cost_bp": ROUND_COST_BP,
                     # Момент записи разбора. Без него касса счёта
                     # закрывала позицию задним числом по плановому
                     # времени — знание из будущего в кассе, тот же
                     # класс дефекта, что отбор универсума по
                     # сегодняшнему списку.
                     "at_ts": round(time.time(), 3),
                     "rows": rows_rv},
                    ensure_ascii=False) + "\n")
            review = rows_rv
    return review


# --- ситуационная книга -----------------------------------------------
# Решение владельца (2026-08-07): книга, которая входит не по
# расписанию, а когда модель видит ситуацию, и выходит не по сроку, а
# когда ситуация кончилась. Сигнал — прогнозы главного горизонта
# (fwd/mae/mfe за 4 ч): это лучше всего обученные цели.
#
# Пороги объявлены ДО прогона и после результатов не двигаются
# (правило проекта). Все три выведены из уже измеренного, а не взяты
# на вкус:
#  - вход только если прогноз перекрывает круг издержек ВТРОЕ: зонд
#    крайности (probe_extreme, 2026-08-12) показал, что весь запас
#    сигнала сидит в верхнем квинтиле |прогноза| — его граница
#    ≈30 б.п. ≈ 3× круга; на прежних 22 (2× круга) книга торговала
#    середину профиля, которая даёт +2…+5 б.п. и не платит за себя.
#    Тот же порог, что пол входа главной книги (H4_FLOOR_BP): сигнал
#    у обеих один — цели 4-часового горизонта;
#  - обещанный ход В ПОЛЬЗУ не меньше чем вдвое больше обещанного хода
#    ПРОТИВ (RR ≥ 2 — число владельца). Обе величины из целей пути по
#    СЫРОЙ цене: сравнивать fwd (остаток к волне) с путём цены — та же
#    ошибка единиц, что уже ловилась в замере бракета;
#  - предел возраста сутки: позиция без исхода не вправе жить вечно, а
#    прогноз дальше 24 ч эта модель не видела никогда.
SIT_SLOTS = 6                     # одновременных позиций не больше
SIT_MIN_EDGE_BP = 3 * ROUND_COST_BP
SIT_MIN_RR = 2.0
# Книга НИЗКОГО RR (решение владельца 2026-08-22). Замер по
# наблюдательной записи (2321 закрытая сделка, неделя 08-14…08-21)
# дал монотонный градиент ПРОТИВ высокого отношения: доля побед
# 54 % при RR<1 против 34 % при RR≥2 и 22 % при RR≥4, а механизм —
# узкий стоп, не крупная цель (медиана обещанного стопа сжимается
# 354 → 57 б.п. при почти постоянной цели, доля выходов по стопу
# растёт 17 % → 78 %). Порог 1.5 объявлен ДО проверочных данных;
# лучшую корзину 0–1 нарочно не берём — резать тоньше после
# просмотра поверхности есть ошибка R5. Нижнего порога нет: гейт
# книги — «обещание есть и RR не выше потолка», остальные правила
# v13 (край, скидка, полоса, шум, съеденное) общие.
SIT_LO_MAX_RR = 1.5
SIT_LO_SLOTS = 6
# Цена обязана ПРИЙТИ К НАМ, а не лист — объявить. Остаток хода
# обязан превышать то, что обещал сам лист, на круг издержек ноги.
# Без этого требования гейт пускал имя в первый же такт после свежего
# листа: пока цена не двинулась, остаток РАВЕН полному прогнозу, то
# есть проходили сразу все, кого выбрала модель. На живом прогоне так
# и вышло — входы легли на минуты циклов (20:16, 20:31, 20:46, 21:06
# по Вене), и книга набиралась пачкой по таймеру, ровно от чего эта
# книга и строилась. Величина не выбрана на глаз: круг издержек ноги
# и есть цена того, что вход вообще состоится, — пока цена не отдала
# хотя бы его, вход ничем не лучше входа по самому листу.
SIT_MIN_DISC_BP = ROUND_COST_BP
# Полоса нечувствительности взведения. Требование «имя было замечено
# НЕ проходящим гейт» отличает пересечение при нас от состояния, в
# котором мы имя застали, — но НЕ отличает настоящее движение от
# дрожания вокруг линии, у которой имя и так стояло. На живом прогоне
# это видно прямо в журнале: пачки входов со скидками +11, +12, +13,
# +14, +18 при пороге 11 — целая когорта, подошедшая к линии за
# слепые шесть минут запаздывания цикла, и пять секунд шума решали,
# кто перетечёт.
#
# Взведение поэтому требует запаса: имя обязано быть замечено НЕ
# ближе полосы к спусковому крючку. Величина та же, что у скидки, и
# по той же причине — ход, который мы наблюдаем своими глазами,
# обязан стоить не меньше круга издержек, иначе мы платим 11 б.п. за
# то, чтобы поторговать двухпунктовым дрожанием. При равенстве
# полосы и скидки правило читается одной фразой: имя обязано быть
# увидено ДО того, как цена начала отдавать, и пройти всю скидку при
# нас.
SIT_ARM_BAND_BP = ROUND_COST_BP
# Потолок на съеденную долю обещания против (правило v11, часть 2).
# Ход цены против прогноза до входа считался ДВАЖДЫ в плюс — скидка
# растёт (|rem| − |fwd0|), RR растёт (переякоренный риск сжимается,
# награда растёт) — и ни разу в минус, хотя тот же ход съедает
# обещанный моделью запас до стопа. TWT 2026-08-13: лист честно видел
# −37.5 б.п. (v10 пройден), цена ушла +102 б.п. против шорта, съев
# 86 % обещания; запас 16 б.п. пробил бар самого входа — круг
# издержек за нулевой ход. У пяти стопнутых сделок v10 съедено
# 44–86 %. Порог — правило большинства: карта модели обязана быть
# целой хотя бы наполовину; якоря в издержках у него нет, и это
# сказано честно. Объявлен до замера по записанным сделкам
SIT_MAX_EATEN = 0.5
SIT_MAX_AGE_H = 24
# Книга равного риска (решение владельца 2026-08-13): сделка
# закрывается ТОЛЬКО уровнем — стопом или тейком. Разворот прогноза и
# предел возраста её позиций не трогают: выход «по середине» ломает
# математику ожидания в деньгах (−R либо +r·R), ради которой книга и
# заведена. Цена решения названа: позиция, не задевшая ни один
# уровень, живёт дольше суток и держит слот.
SIT_R_EXIT_POLICY = "levels_only"
# Политика кандидата фабрики: уровни и предел возраста, без разворота
# прогноза. Ровно то, чем закрывает сделку реплей `candidate.simulate`
# (стоп, тейк, возраст): живая книга и её реплей обязаны закрываться
# одними причинами, иначе расхождение между ними ничего не означает.
SIT_LEVELS_AGE = "levels_age"

# Только предел возраста: ни стопа, ни цели, ни разворота прогноза.
# Так устроена ось `geom: timer` фабрики — «выход по времени». Живая
# книга обязана закрываться ТЕМИ ЖЕ причинами, что её реплей, иначе
# сравнивать её с собственным реплеем нечем.
SIT_AGE_ONLY = "age_only"
# Второе правило той же книги (решение владельца после #ptadyrc):
# запас до стопа обязан быть не тоньше ПОЛУТОРА живых минутных шумов
# монеты. Базовый гейт v11 требует один шум, и сделка #ptadyrc прошла
# его с запасом 1.7 б.п. (стоп 39 при шуме 37.3) — стоп шириной в
# один фитиль на тонком имени, снятый минутой позже входа. Порог —
# правило КНИГИ, как размер и выходы: торгуемая книга не меняется,
# и разница результатов остаётся приписуемой правилам sit_r.
SIT_R_NOISE_MULT = 1.5
# Третье правило той же книги (решение владельца: «размер тейков и
# стопов должен быть одинаковый»): вход только при исполняемом стопе
# не тоньше этого порога. Порог ВЫВЕДЕН из двух чисел забора, а не
# назначен: риск сделки R = FIXED_RISK_SHARE капитала, потолок на имя
# NAME_CAP_SHARE капитала, и равный риск помещается под потолок только
# при стопе ≥ R/потолок = 0.1 %/10 % = 1 %. Тоньше — размер срезал бы
# потолок (замерено: 45 сделок из 69, две трети книги, риск 0.2–0.9 R
# вместо R — контракт «−R либо +r·R» держался у трети сделок). Взятая
# сделка теперь несёт ровно R; цена — книга входит втрое реже.
SIT_R_MIN_STOP_BP = TR.FIXED_RISK_SHARE / TR.NAME_CAP_SHARE * 1e4
# Наблюдательная книга: те же гейты, КРОМЕ отношения. Нужна затем,
# чтобы фильтру владельца было что показывать ниже боевого порога: в
# торгуемой книге сделок с RR < 2 нет вовсе, и порог 1 к 1 добавить
# ничего не может. Слотов больше, потому что при снятом требовании
# кандидатов больше, и шесть мест отобрали бы не по качеству, а по
# очерёдности — состав книги перестал бы описывать распределение.
#
# Торгуемая книга от этого не меняется НИ ЧЕМ: у наблюдательной свой
# каталог, свой счёт и своя запись, тень бота её не читает. Смешать
# их в одном счёте было бы той же ошибкой, что смешать правила разных
# версий: кривая описывала бы книгу, которой не было.
SIT_OBS_SLOTS = 24
SIT_OBS_MIN_RR = 0.0
SIT_SIGNAL_H = 4                  # горизонт целей, дающих сигнал
# Версия ПРАВИЛ книги — часть её определения (урок RULES_VERSION).
# v1 — часовые входы, и в выходах жил дефект перестановки сторон у
# шортов; v2 — живой сканер ПЛЮС часовой вход «страховкой» — на живом
# прогоне страховка заполнила книгу сделками по таймеру, ровно тем,
# от чего книга и строилась; v3 — вход ТОЛЬКО от сканера. Сделки
# разных правил нельзя сводить в один счёт: кривая описывала бы
# книгу, которой не было. Смена версии отставляет старую книгу в
# архив — тем же приёмом, что смена режима хеджа.
# v4 — вход требует, чтобы цена отдала круг издержек сверх обещания
# листа: без этого сканер входил в первый же такт после листа, и
# сделки снова ложились на минуты циклов. v5 — вход требует ещё и
# ПЕРЕСЕЧЕНИЯ на наших глазах: имя, у которого условие было верно уже
# при первом взгляде (перезапуск сборщика, опоздавшее чтение листа),
# пропускается — иначе накопленный за час запас выпускает всех разом,
# и это снова пачка входов одной секундой. v6 — у книги появилась
# ЦЕЛЬ: выходов было три (разворот прогноза, ход против, предел
# возраста), то есть стоп был, а тейка не было вовсе — обещанное
# гейтом отношение RR ≥ 2 держалось лишь наполовину: рисковали по
# правилу, брали по случаю. Найдено владельцем на XNYUSDT: цена
# прошла обещанный уровень почти сразу, сделка осталась открытой.
# v8 — взведение с полосой: пересечение засчитывается, только если
# имя перед этим видели не ближе `SIT_ARM_BAND_BP` к крючку. Без
# полосы пачки возвращались четвёртый раз — не от старой логики, а
# оттого, что когорта имён стоит вплотную к линии и переливается
# через неё шумом за пять секунд.
# v7 — стоп переехал ЗА линию прогноза: до неё он стоял ровно там,
# куда модель сама предсказывала цену, то есть на уровне, который по
# построению перекрывается примерно в половине случаев (замер
# `s9_sweep/stops.py`: касаются 52 %). Теперь уровень предсказывает
# отдельная квантильная модель (`STOP_TAU`), а гейт считает отношение
# по ИСПОЛНЯЕМОЙ геометрии — по тому стопу, который реально стоит.
# v10: лист сам обязан видеть ситуацию — |fwd0| ≥ гейт до
# переякорения. Остаток раздувается любым крупным ходом, и при
# прогнозе −0.011 % книга шортила разгон +2.17 % как «ситуацию»
# (найдено владельцем по сделкам-точкам с got 0.000 %). Смена версии
# заодно уносит в архив сделки v9, рождённые этим же обходом.
# v9: гейт входа 22 → 33 б.п. (зонд крайности).
# v11 — два правила против фейда разгона, найденного по TWT и всей
# молодой истории v10 (5 закрытий из 6 — стоп после входа против
# сильного хода, −553 б.п. суммой): запас до стопа обязан переживать
# живой минутный шум монеты (медианный минутный размах середины за
# ~15 минут; нет меры — нет входа), и цена не вправе съесть больше
# `SIT_MAX_EATEN` обещанного хода против до входа. Ход против
# прогноза перестал считаться только в плюс.
# v12 — мера шума исправлена по CATSTOCK 2026-08-13: у тонкого
# инструмента медиана целых минут — ноль (котировка большинство минут
# стоит), и правило v11 видело «шум 0» при входе внутрь минуты с
# фитилём в 225 б.п. Шум стал максимумом из медианы целых минут и
# размаха ТЕКУЩЕЙ минуты; нулевой итог — отсутствие меры (котировка,
# не шевелившаяся 15 минут, — замороженный ряд, не безопасность),
# и входа нет.
# v13 — тейк стал лимиткой (решение владельца по #6wa5abp): когда
# ПРИНТЫ прошли строго сквозь уровень цели, исполнение засчитывается
# по цене уровня — сквозной проход не может обойти заявку, стоящую с
# входа (приоритет цена-время). Касание без прохода — по-прежнему по
# доступной середине (правило v1 о касании в силе), стоп цену уровня
# не получает никогда. Замер: по 11 тейкам отдано +164 б.п. против
# цены уровня, 5 из 6 проверяемых — сквозные; у #6wa5abp принты
# прошли уровень на 124 б.п., а выход записан на 63.5 б.п. хуже.
# Издержки выхода НЕ трогаются (считаются тейкерскими) — консервативно.
SIT_RULES_VERSION = 13


# Файлы, которые принадлежат КНИГЕ, а не модели. Всё остальное в
# каталоге — веса, манифест модели, сохранённые векторы, мысли, история
# IC, лист сечения — принадлежит модели и переживает смену книги.
#
# Различие не косметическое, и стоило оно остановки живого контура. У
# боковых книг каталог содержит только книгу, поэтому «отставить книгу»
# делалось переименованием каталога — и у ГЛАВНОЙ книги тем же
# движением уезжала сама модель: `MODEL_DIR` и есть каталог модели.
# Следующий цикл падал на `preds.jsonl` в несуществующем каталоге, а
# наружу это выглядело как «цикл упал», без единого намёка на причину.
# Живые события сканера — тоже файлы КНИГИ. Оставить их в живом
# каталоге значит дать циклу пересоздать из них всю старую книгу:
# ровно это случилось при правилах v9 — архив унёс выборы, а
# `entries_live` остался, и 812 сделок прежнего гейта возродились
# первым же циклом как «свежие».
BOOK_FILES = ("picks.jsonl", "review.jsonl",
              "entries_live.jsonl", "exits_live.jsonl")


def archive_book(mdir, dst, log_=None):
    """Перенести КНИГУ каталога `mdir` в каталог `dst`.

    Не переименование каталога: переезжают только файлы книги (выборы,
    разбор, счета рук), а копия манифеста кладётся рядом, чтобы архив
    сам говорил, чем эта книга была. Модель остаётся на месте.

    Одна функция на все поводы отставить книгу (смена порядка сечения,
    смена правил): два места, решающих одно, однажды разойдутся — и
    разошлись бы ровно так, как разошлись главная и боковые книги.
    """
    try:
        os.makedirs(dst, exist_ok=True)
        moved = []
        for f in BOOK_FILES:
            src = os.path.join(mdir, f)
            if os.path.exists(src):
                os.rename(src, os.path.join(dst, f))
                moved.append(f)
        for f in sorted(os.listdir(mdir)):
            if f.startswith("account_") and f.endswith(".json"):
                os.rename(os.path.join(mdir, f), os.path.join(dst, f))
                moved.append(f)
        mp = os.path.join(mdir, "manifest.json")
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                was = f.read()
            with open(os.path.join(dst, "manifest.json"), "w",
                      encoding="utf-8") as f:
                f.write(was)
    except OSError as e:
        if log_:
            log_(f"книгу не отставить: {e}")
        return None
    return moved


def fresh_book_on_rank_change(mdir, want, log_=None, floor=None):
    """Сменился ПОРЯДОК сечения — старая книга уходит в архив.

    Книга, упорядоченная по сырому прогнозу, и книга, упорядоченная в
    единицах σ, — разные книги, даже если каталог один. Дописать вторую
    к первой значит получить кривую, описывающую то одну, то другую, и
    сравнить их станет нечем. Тот же приём, что у смены правил
    ситуационной книги: книга не удаляется, а переезжает в архивный
    каталог — история прогона это запись, а не мусор.
    """
    # Прежний порядок читается из ПОСЛЕДНЕЙ ЗАПИСИ ВЫБОРА, а не из
    # манифеста. У главной книги манифест — это манифест МОДЕЛИ, он
    # пишется в начале цикла, до книг; проверка читала оттуда значение,
    # которое тот же цикл только что и записал, и потому не срабатывала
    # никогда. У часовых книг манифест свой, и там всё работало — из-за
    # этой асимметрии дефект и выглядел избирательным.
    #
    # Запись выбора несёт `rank_want` — чем книга упорядочивала сечение
    # НА САМОМ ДЕЛЕ. Подделать его нечем: его пишет тот же код, который
    # выбирает.
    # Смотрится ВСЯ книга, а не последняя запись. Цикл, заметивший смену
    # первым, уже успел записать выборы нового порядка — и проверка «что
    # было в прошлый раз» видела бы своё же новое значение и не
    # срабатывала никогда, оставив в книге СМЕСЬ: старые сделки одного
    # порядка, новые другого. Отставлять надо ровно тогда, когда в
    # истории есть запись, упорядоченная иначе.
    pf = os.path.join(mdir, "picks.jsonl")
    was, mixed = None, False
    want_floor = float(floor or 0)
    try:
        with open(pf, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line) or {}
                except ValueError:
                    continue
                got = rec.get("rank_want")
                got_floor = float(rec.get("floor_bp") or 0)
                if got != want:
                    was, mixed = got, True
                    break
                if got_floor != want_floor:
                    # Смена ПОЛА входа — тоже смена книги: населения
                    # сделок до и после пола не смешиваются в одну
                    # кривую по той же причине, что и порядки сечения.
                    was, mixed = f"floor{got_floor:g}", True
                    break
    except OSError:
        return None
    if not mixed:
        return None
    if was == want:
        return None
    tag = (was or "raw").replace("/", "-")
    dst = f"{mdir}.rank-{tag}"
    n = 0
    while os.path.exists(dst):
        n += 1
        dst = f"{mdir}.rank-{tag}-{n}"
    if archive_book(mdir, dst, log_) is None:
        return None
    if log_:
        log_(f"порядок сечения книги {os.path.basename(mdir)} сменился "
             f"({was or 'сырой прогноз'} → {want or 'сырой прогноз'}) — "
             f"старые сделки отставлены в {os.path.basename(dst)}, "
             f"книга начинается заново")
    return dst


def fresh_sit_on_rules_change(mdir, log_=None, rules=None,
                              version=None):
    """Сменились правила ситуационной книги — старая уходит в архив.

    Книга не удаляется, а переезжает в архивный каталог: история
    прогона — запись, а не мусор, и сравнить старую книгу с новой можно
    будет чтением. Имя архива выводится из ПРЕЖНЕЙ версии правил,
    повторный запуск копий не плодит.

    `rules` — правила самой книги сверх общей версии (политика
    выходов, множитель шума): ключ манифеста → требуемое значение.
    Смена любого из них отставляет книгу так же, как смена версии —
    кривые, писанные разными правилами, не сшиваются. Отсутствие поля
    в манифесте — тоже смена: книга, писанная до правила, не писалась
    по нему.

    `version` — какая версия общих правил ожидается в манифесте; по
    умолчанию `SIT_RULES_VERSION`. Корзинные книги-эхо передают 1: их
    манифесты версию ситуационных правил не несут вовсе, и сравнение
    с ней отставляло бы книгу каждый цикл — у них решает словарь
    `rules`.
    """
    try:
        with open(os.path.join(mdir, "manifest.json"),
                  encoding="utf-8") as f:
            man = json.load(f) or {}
        was = int(man.get("rules_version") or 1)
    except (OSError, ValueError):
        return None                # каталога нет или пуст — нечего
    want_ver = SIT_RULES_VERSION if version is None else int(version)
    diff = [(k, man.get(k), v) for k, v in (rules or {}).items()
            if man.get(k) != v]
    if was == want_ver and not diff:
        return None
    dst = f"{mdir}.rules-v{was}"
    n = 0
    while os.path.exists(dst):
        n += 1
        dst = f"{mdir}.rules-v{was}-{n}"
    if archive_book(mdir, dst, log_) is None:
        return None
    why = (f"v{was} → v{want_ver}"
           if was != want_ver
           else "; ".join(f"{k}: {w if w is not None else 'нет'} → {v}"
                          for k, w, v in diff))
    if log_:
        log_(f"правила ситуационной книги сменились ({why}) — "
             f"старые сделки отставлены в {os.path.basename(dst)}, "
             f"книга начинается заново")
    return dst


def situational_arm(mdir, arm, models, x, mats, syms, rows_m, j_last,
                    grid, nov_lo, nov_hi, book_root, log_,
                    beta_row=None, names=None, train_seq=None):
    """Один проход ситуационной книги: сначала выходы, потом входы.

    Порядок обязателен: закрытие освобождает слот и кассу, и вход в
    тот же час имеет право занять их. Выход и вход по одному имени в
    один час запрещены отдельно — перевороты внутри часа были бы
    торговлей шумом переобучения.

    Возвращает ЛИСТ сечения для живого сканера (прогноз, сырые
    обещания пути, бета, цена закрытия по каждому имени) — карту, по
    которой сборщик между часами якорит прогноз к живой цене.
    """
    kf, km, kx = (f"fwd_{SIT_SIGNAL_H}h", f"mae_{SIT_SIGNAL_H}h",
                  f"mfe_{SIT_SIGNAL_H}h")
    kmq, kxq = f"maeq_{SIT_SIGNAL_H}h", f"mfeq_{SIT_SIGNAL_H}h"
    if any((arm, k) not in models for k in (kf, km, kx)) \
            or j_last is None:
        return None
    # Живые события (входы сканера, выходы сторожа) поглощает общий
    # модуль `sit_absorb` — тот же зовёт сборщик в МОМЕНТ события,
    # поэтому pnl появляется секундами после закрытия, а не ближайшим
    # часом (просьба владельца). Здесь тот же вызов — страховка на
    # случай упавшего сборщика и старых событий; одновременную
    # дозапись двух процессов разводит замок каталога книги. Лесенка
    # выхода у цикла — снимок записи на момент прогона; сборщик
    # ставит её секундами после события, что ближе к правде
    # исполнения, а источник и сжатие у обоих одни.
    SA.absorb(mdir,
              lambda ss: stamp_book(ss, time.time(), book_root,
                                    log_, "выхода"),
              log_, arms=(arm,))
    picks_all = _read_jsonl(os.path.join(mdir, "picks.jsonl"))
    reviews_all = _read_jsonl(os.path.join(mdir, "review.jsonl"))
    open_pos = SA.sit_open_positions(picks_all, reviews_all, arm)
    si = {s: i for i, s in enumerate(syms)}
    cur = grid[j_last]
    mid = mats["mid_close"]
    # Политика выходов — из МАНИФЕСТА книги, а не из имени каталога:
    # у книги равного риска сделку закрывает только уровень (стоп или
    # тейк, решение владельца), и часовые причины «разворот прогноза»
    # и «предел возраста» её позиций не трогают. Манифест пишет этот
    # же цикл до вызова руки; нет манифеста (свежий каталог, тесты) —
    # политика прежняя, все причины в силе.
    #
    # Политик три, и различаются они тем, какие ПРИЧИНЫ живы:
    #   (умолчание) — уровни, разворот прогноза, предел возраста;
    #   `levels_only` — только уровни (книга равного риска);
    #   `levels_age` — уровни и возраст, без разворота: так устроен
    #       реплей кандидата фабрики (стоп, тейк, предел возраста), и
    #       живая книга обязана закрываться теми же причинами, иначе
    #       сравнивать её с собственным реплеем нечем;
    #   `age_only` — ТОЛЬКО предел возраста: ось `geom: timer` фабрики
    #       («выход по времени») не ставит ни стопа, ни цели. Уровни у
    #       такой книги гасятся и здесь, и у 5-секундного сторожа —
    #       иначе сторож закрывал бы по уровню то, чему уровня не
    #       объявляли, и книга торговала бы не своё правило.
    # Предел возраста тоже из манифеста: у кандидатов он ось правила
    # (24 ч либо 72), и глобальная константа сделала бы книгу не той,
    # которую объявили.
    try:
        with open(os.path.join(mdir, "manifest.json"),
                  encoding="utf-8") as f:
            _mm = json.load(f) or {}
    except (OSError, ValueError):
        _mm = {}
    _pol = _mm.get("exit_policy")
    lvl_only = _pol == SIT_R_EXIT_POLICY
    age_only = _pol == SIT_AGE_ONLY
    no_flip = lvl_only or _pol in (SIT_LEVELS_AGE, SIT_AGE_ONLY)
    max_age_h = float(_mm.get("max_age_h") or SIT_MAX_AGE_H)

    # --- выходы: ситуация кончилась (часовые причины) ----------------
    # Событийные выходы уже поглощены выше; остаются причины, которым
    # нужны модель и цены часа: страховочный замер уровней по закрытию
    # часа (живой сторож мог не видеть цены), разворот прогноза и
    # предел возраста.
    closed_syms, by_hour = set(), {}
    # Цена суда — закрытие часа `cur`. Позиция, открытая ПОЗЖЕ этого
    # закрытия (вход сканера в окно между концом часа и запуском
    # цикла), судилась бы ценой из ПРОШЛОГО — седьмой дефект кассы:
    # у ENSUSDT вход 10:24:44, «разворот» оценён закрытием 10:00, и
    # бумага записала +363 б.п., которых у сделки не было ни секунды;
    # таких сделок 32 из 827 (3.9 %), страховочный стоп записывал до
    # −950 б.п. по до-входным обвалам. Такую позицию цикл не судит
    # вовсе: уровни ведёт 5-секундный сторож по живому пути, а
    # разворот и возраст подождут цикл, чей час вход уже содержит, —
    # тот же принцип, что «свежей позиции путь не даётся» у сторожа.
    cut = TR.hour_end(cur)
    for p in open_pos:
        ent = p.get("at_ts")
        if ent is not None and cut is not None and float(ent) >= cut:
            continue
        i = si.get(p["sym"])
        px = float(mid[i, j_last]) if i is not None else float("nan")
        if not (np.isfinite(px) and p.get("px")):
            # Цены нет — судить не по чему; позиция ждёт цены.
            continue
        # Строка выбора УЖЕ несёт стороны: `mae` — ход против ЭТОЙ
        # позиции, `mfe` — в пользу (path_fields). Применять
        # position_path повторно нельзя: у шорта это переставило бы
        # стороны обратно, и любой ход закрывал бы позицию —
        # дефект найден здесь и закрыт тестом.
        adv, fav = p.get("mae"), p.get("mfe")
        reason = None
        move = (px / p["px"] - 1.0) * 1e4
        age = _hours_apart(p["hour"], cur)
        fresh = float(models[(arm, kf)].predict(
            x[i:i + 1, j_last])[0])
        # Уровни идут ПЕРЕД разворотом прогноза: задетый уровень —
        # факт цены, разворот — мнение модели. Прежде разворот
        # стоял первым, и позиция, ушедшая за свой стоп, попадала
        # в разбор с чужой причиной. Ход ПРОТИВ проверяется раньше
        # цели: ничью внутри часа разрешаем не в свою пользу, как
        # в замерах T3/T4.
        #
        # Это страховка на случай, когда живой сторож не видел
        # цены: часовой замер берёт цену конца часа.
        if not age_only and adv is not None and (
                (p["side"] == "long" and move <= adv)
                or (p["side"] == "short" and move >= adv)):
            reason = "цена прошла обещанный ход против"
        # ЦЕЛЬ. До версии 6 её не существовало вовсе: стоп стоял,
        # тейка не было, и сделка, дошедшая до обещанного уровня,
        # висела до разворота прогноза или суток возраста.
        elif not age_only and fav is not None and (
                (p["side"] == "long" and move >= fav)
                or (p["side"] == "short" and move <= fav)):
            reason = "цена дошла до обещанной цели"
        # Прогноз развернулся: модель больше не ждёт того, ради
        # чего входила. У книги «только уровни» ни разворот, ни
        # возраст позицию не трогают — каждый её исход обязан быть
        # −R либо +r·R.
        elif not no_flip and (p["side"] == "long") != (fresh > 0):
            reason = "прогноз развернулся"
        elif not lvl_only and age is not None \
                and age >= max_age_h:
            reason = "предел возраста"
        if reason is None:
            continue
        rr = {"sym": p["sym"], "side": p["side"],
              # Ожидание — обещанный ход В ПОЛЬЗУ по сырой цене: исход
              # здесь тоже сырой ход цены, и единицы обязаны совпадать.
              "expected": round(fav, 1) if fav is not None else None,
              "got": round(move, 1),
              "net": round((1 if p["side"] == "long" else -1) * move
                           - ROUND_COST_BP, 1),
              "exit_hour": cur, "reason": reason}
        by_hour.setdefault(p["hour"], []).append(rr)
        closed_syms.add(p["sym"])
    if by_hour:
        syms_out = sorted({r["sym"] for rows_rv in by_hour.values()
                           for r in rows_rv})
        with SA.book_lock(mdir):
            SA.write_reviews(mdir, arm, by_hour,
                             stamp_book(syms_out, time.time(),
                                        book_root, log_, "выхода"),
                             log_)

    # --- лист сечения для живого сканера ------------------------------
    # Карта от модели: прогноз, СЫРЫЕ обещания пути и бета по каждому
    # имени сечения. Сборщик секундами якорит её к живым ценам и
    # спускает курок, когда остаток обещанного хода проходит гейты.
    # Лист пишется ВСЕГДА, даже при полной кассе: сторожу выходов и
    # сканеру нужна свежая карта независимо от свободных слотов.
    xj = x[rows_m, j_last]
    fwd = models[(arm, kf)].predict(xj)
    mae = models[(arm, km)].predict(xj)
    mfe = models[(arm, kx)].predict(xj)
    # Квантильные концы пути — уровни стопа. Их может не быть (цель не
    # набрала строк на молодой записи): тогда лист идёт без них, и
    # сканер ставит стоп по среднему, как прежде. Отсутствие уровня
    # обязано быть видно в самом листе полем `stop_tau`, а не
    # угадываться по тому, есть ли ключ.
    maeq = (models[(arm, kmq)].predict(xj)
            if (arm, kmq) in models else None)
    mfeq = (models[(arm, kxq)].predict(xj)
            if (arm, kxq) in models else None)
    # Объяснение прогноза — по каждой строке листа: сканер скопирует
    # его в событие входа, цикл — в запись выбора. Считается здесь,
    # потому что только у цикла есть и модель, и имена признаков;
    # сканеру ехать должен готовый ответ.
    whys, setups = (explain_rows(models[(arm, kf)], xj, names)
                    if names is not None else (None, None))
    # Прогноз в единицах собственной σ монеты — для ПОРЯДКА, а не для
    # гейта. Решение владельца переводит ситуационные сделки на per σ, и
    # переводится именно приоритет: когда гейт проходят больше имён, чем
    # есть мест, слот достаётся тому, у кого ход крупен ДЛЯ НЕГО. Порог
    # входа остаётся в базисных пунктах намеренно — он выведен из круга
    # издержек, а в единицах σ такого якоря не существует, и назначать
    # его заново значило бы взять число с потолка.
    kz = rank_z(SIT_SIGNAL_H)
    fwd_z = (models[(arm, kz)].predict(xj)
             if (arm, kz) in models else None)
    if fwd_z is None:
        log_(f"[{arm}] ситуационная: порядок {kz} недоступен — "
             f"приоритет по сырому прогнозу")
    sheet = []
    for i in range(len(rows_m)):
        px = float(mats["mid_close"][rows_m[i], j_last])
        if not np.isfinite(px):
            continue
        row = {"sym": syms[rows_m[i]], "fwd": round(float(fwd[i]), 2),
               "mae": round(float(mae[i]), 2),
               "mfe": round(float(mfe[i]), 2),
               "beta": (round(float(beta_row[i]), 4)
                        if beta_row is not None
                        and np.isfinite(beta_row[i]) else 1.0),
               "px": px}
        if fwd_z is not None and np.isfinite(fwd_z[i]):
            row["fwd_z"] = round(float(fwd_z[i]), 4)
        if maeq is not None and mfeq is not None:
            row["mae_q"] = round(float(maeq[i]), 2)
            row["mfe_q"] = round(float(mfeq[i]), 2)
        if whys is not None and whys[i]:
            row["why"] = whys[i]
        if setups is not None and setups[i]:
            row["setup"] = setups[i]
        nv = novelty(xj[i], nov_lo, nov_hi)
        if nv is not None:
            row["odd"] = round(nv, 3)
        sheet.append(row)

    # Входов здесь НЕТ — единственная дверь в книгу живой сканер
    # сборщика (события `entries_live`, превращённые выше). Часовой
    # вход стоял тут «страховкой на случай упавшего сборщика» и на
    # живом прогоне заполнил книгу сделками по таймеру — ровно тем,
    # от чего книга строилась. Страховка, меняющая природу сделки,
    # не страховка, а другая книга; упавший сборщик означает «входов
    # нет», и это честнее, чем «входы не те».
    return sheet


# Пол на вход книги 4 ч — из зонда крайности (probe_extreme,
# 2026-08-12): исход растёт монотонно с величиной прогноза, и весь
# запас сидит в верхнем квинтиле (его граница ≈30 б.п. ≈ 3× круга
# издержек; +11.2 б.п. превышения против +2.0 у середины, без лучшего
# имени +8.3). Нога мельче пола не входит; тихий час — книга не
# торгует. Порог объявлен до внедрения и по исходам не подгонялся.
H4_FLOOR_BP = 30.0
# Снятые горизонты турнира темпов — из реестра книг, а не числом
# здесь: почему часовая удалена, записано там же, где состав книг.
REMOVED_BOOKS = set(BK.REMOVED_HORIZONS)

# Корзинные книги-эхо 24 ч (решение владельца 2026-08-14): под-модель,
# которая смотрит не на сделку, а на ОБЩИЙ нереализованный результат
# всех открытых позиций руки разом, и при пороге закрывает корзину
# целиком. Пороги — доли капитала руки, объявлены до прогона и
# выведены из замера шума собственной кривой: суточная σ PnL руки
# книги 24 ч ≈ 160 $ ≈ 5.3 % капитала 3000 $, медианный суточный
# размах 145–190 $ — тейк равен одному суточному ходу, пол
# диагностической книги симметричен ему.
#
# Честная теория записана до прогона: правило «закрыть, когда сумма
# дошла до X» ожидания НЕ создаёт — остановка по порогу не меняет
# среднего, а входы идут по расписанию источника независимо от
# корзины, то есть и комиссия та же. Оно меняет ФОРМУ распределения:
# частые фиксации у тейка против редких глубоких минусов — та же
# carry-форма, которой Sharpe льстит. Судить книги по просадке и
# хвосту ПАРНО против источника, а не по среднему. Мартингейла
# («открывать дальше и ждать плюса») забор не допускает: касса и так
# вкладывает всё, что позволяют потолки, доливать нечем.
BASKET_H = 24                     # книга-источник — model_h24
BASKET_TAKE_SHARE = 0.05          # тейк корзины: +5 % капитала руки
BASKET_FLOOR_SHARE = 0.05         # пол (только у …bf): −5 % капитала
BASKET_TAKE_REASON = "корзина дошла до цели"
BASKET_FLOOR_REASON = "корзина дошла до предела убытка"
# Третья корзинная книга `model_h24c` (решение владельца 2026-08-30,
# по реплею probe_basket серии 1–2): у ног НЕТ отдельных выходов
# вовсе — ни таймера, ни разборов источника, — корзина закрывается
# ТОЛЬКО целиком: цель +5 %, предел −5 % либо возраст 24 ч. Возраст —
# горизонт самого сигнала (единственный порог с якорем; 48 ч в
# реплее выглядел лучше, но выбрать его значило бы выбрать по
# просмотренной поверхности — ошибка R5). Правило «один минус в
# день» НЕ взято: парная медиана его эффекта в реплее ровно 0.00.
# Слоты кассы фиксированы числом реплея (6 имён × 24 ч) — у книги
# без срока кассе не из чего вывести «имена × горизонт».
BASKET_AGE_H = 24
BASKET_AGE_REASON = "корзина дошла до предела возраста"
BASKET_SLOTS = 6 * BASKET_H


def make_pick(arm, hold_h, models, x, mats, syms, rows_m, j_last, grid,
              nov_lo, nov_hi, book_root, log_, names=None,
              train_seq=None, rank_key=None, floor_bp=None):
    """Выбор монет одной книги: цели fwd/mae/mfe СВОЕГО горизонта.

    Возвращает запись выбора или `None`, когда у книги нет своих
    моделей (цель не набрала строк) либо нет годного сечения.
    """
    kf, km, kx = (f"fwd_{hold_h}h", f"mae_{hold_h}h", f"mfe_{hold_h}h")
    if (arm, kf) not in models or (arm, km) not in models \
            or j_last is None:
        return None
    # Порядок в единицах σ недоступен (цель не набрала строк) — книга НЕ
    # молчит, а падает на сырой прогноз. Для боковой книги молчание было
    # терпимо, для главной оно означает остановку торговли без единого
    # признака отказа. Подмена при этом громкая: она идёт в журнал и в
    # саму запись выбора.
    rank_used = rank_key
    if rank_key is not None and (arm, rank_key) not in models:
        log_(f"[{arm}] порядок {rank_key} недоступен — сечение "
             f"упорядочено сырым прогнозом")
        rank_key = None
    xj = x[rows_m, j_last]
    fwd = models[(arm, kf)].predict(xj)
    # Порядок сечения задаёт ОДНА величина, и какая именно — свойство
    # книги. У книги в единицах σ это прогноз, делённый на собственную
    # волатильность монеты; ожидание при этом записывается сырым, иначе
    # «обещание / факт» у двух книг мерилось бы в разных единицах и
    # сравнить их было бы нечем.
    rank_by = (models[(arm, rank_key)].predict(xj)
               if rank_key is not None else fwd)
    # Ход ПРОТИВ позиции у длинной и короткой ноги — разные цели:
    # `mae` — минимум цены за горизонт, `mfe` — максимум, обе по ЦЕНЕ.
    # Лонгу против идёт mae, шорту — mfe; связка под тестом в
    # `path_fields`.
    mae = models[(arm, km)].predict(xj)
    mfe = models[(arm, kx)].predict(xj) if (arm, kx) in models else None
    # Весь вектор сечения — в файл: через горизонт по нему посчитается
    # живой вневыборочный IC своей цели.
    save_preds(arm, grid[-1], syms, rows_m, fwd, target=kf)
    if rank_key is not None:
        save_preds(arm, grid[-1], syms, rows_m, rank_by, target=rank_key)
    o = np.argsort(rank_by)
    if floor_bp:
        # Пол в СЫРЫХ б.п. при ранжировании в σ — намеренно: порог
        # выведен из круга издержек, а в единицах σ такого якоря нет
        # (то же решение, что у гейта ситуационной книги). Обе оси
        # зонда дали почти один профиль.
        o = np.array([i for i in o if abs(float(fwd[i])) >= floor_bp],
                     dtype=int)
        if not len(o):
            log_(f"[{arm}] час тихий: ни одного прогноза не мельче "
                 f"пола {floor_bp:g} б.п. — книга не торгует")
            return None
    # Объяснение — только для выбранных шести, а не для всего сечения:
    # у часовых книг сделка и есть выбор, остальным строкам объяснять
    # нечего. `rank` — место в сечении по прогнозу: стратегия часовой
    # книги ровно в этом («самые крайние из N»), и без места в записи
    # ответ «почему эта монета» был бы словами, а не числом.
    chosen = list(o[::-1][:3]) + list(o[:3])
    whys, setups = (explain_rows(models[(arm, kf)], xj[chosen], names)
                    if names is not None else (None, None))
    wmap = ({int(i): w for i, w in zip(chosen, whys)}
            if whys is not None else {})
    smap = ({int(i): w for i, w in zip(chosen, setups)}
            if setups is not None else {})

    def mk(i, side):
        px = float(mats["mid_close"][rows_m[i], j_last])
        d = {"sym": syms[rows_m[i]], "fwd": float(fwd[i]),
             "px": px if np.isfinite(px) else None,
             **path_fields(side, float(mae[i]),
                           float(mfe[i]) if mfe is not None else None,
                           h=hold_h)}
        # Место 1 — самый крайний прогноз своей стороны.
        d["rank"] = int((len(fwd) - 1 - np.where(o == i)[0][0])
                        if side == "long" else np.where(o == i)[0][0]) + 1
        d["of"] = int(len(fwd))
        if wmap.get(int(i)):
            d["why"] = wmap[int(i)]
        if smap.get(int(i)):
            d["setup"] = smap[int(i)]
        nv = novelty(xj[i], nov_lo, nov_hi)
        if nv is not None:
            d["odd"] = round(nv, 3)
        return d
    picks = {"arm": arm, "hour": grid[-1], "train_seq": train_seq,
             # Чем упорядочено сечение НА САМОМ ДЕЛЕ: настройка книги
             # говорит о намерении, а это поле — о факте. Без него кусок
             # истории, упорядоченный подменой, ничем себя не выдаёт.
             "rank_by": rank_key, "rank_want": rank_used,
             "floor_bp": floor_bp,
             # Момент, когда решение стало известно: цикл просыпается
             # через минуты после закрытия часа, и это задержка входа,
             # а не ноль.
             # Точность та же, что у разбора (`round(t, 3)`): касса
             # сравнивает эти метки между собой, и целая секунда против
             # миллисекунд означала бы сравнение округлений.
             "at_ts": round(time.time(), 3),
             "long": [mk(i, "long") for i in o[::-1][:3]],
             "short": [mk(i, "short") for i in o[:3]]}
    # Цена, доступная в момент решения. Ставится ПОСЛЕ отбора — раньше
    # неизвестно, у кого её спрашивать.
    names = [p["sym"] for s in ("long", "short") for p in picks[s]]
    bk = stamp_book(names, time.time(), book_root, log_, "входа")
    for s in ("long", "short"):
        for p in picks[s]:
            got = bk.get(p["sym"])
            if got:
                p["px_live"], p["px_live_at"] = got["mid"], got["t"]
                # Книга целиком, а не одна цена: заявка на $42 и на
                # $800 исполняется по-разному, а размер позиции знает
                # только счёт.
                p["cum"] = got
    return picks


def write_pick(mdir, picks):
    """Один выбор на (руку, час) — и не больше.

    Цикл перезапускается (каждая заливка!), и проходов внутри часа
    бывает несколько; дубли не портят счёт, но вытесняют из таблицы
    настоящую историю и делают статистику «сколько сделок» ложной.
    """
    ppath = os.path.join(mdir, "picks.jsonl")
    seen = {((p.get("arm") or "gbm"), p.get("hour"))
            for p in _read_jsonl(ppath)}
    if (picks["arm"], picks["hour"]) in seen:
        return False
    with open(ppath, "a", encoding="utf-8") as f:
        f.write(json.dumps(picks, ensure_ascii=False) + "\n")
    return True


def rebuild_accounts(mdir, hold_h, slots=None):
    """Счета книги — пересборкой ЦЕЛИКОМ из выборов и разборов.

    Счёт остаётся функцией от истории: повторный проход не может
    провести те же сделки дважды, а изменение модели капитала
    применяется ко всей истории разом, а не с середины. Горизонт
    задаёт число слотов кассы (`имена × часы удержания`), поэтому
    передаётся явно; у ситуационной книги горизонта нет — слоты
    приходят числом (`slots`).
    """
    all_tr = TR.build(_read_jsonl(os.path.join(mdir, "picks.jsonl")),
                      _read_jsonl(os.path.join(mdir, "review.jsonl")),
                      hold_h=hold_h)
    # Правило размера — из манифеста САМОЙ книги: его же читают
    # страницы, и два места, решающих одно, однажды разошлись бы.
    try:
        with open(os.path.join(mdir, "manifest.json"),
                  encoding="utf-8") as f:
            sizing = (json.load(f) or {}).get("sizing")
    except (OSError, ValueError):
        sizing = None
    out = {}
    for arm, _ in ARMS:
        hist, bal = TR.account(all_tr, arm, hold_h=hold_h or TR.HOLD_H,
                               slots=slots, sizing=sizing)
        apath = os.path.join(mdir, f"account_{arm}.json")
        with open(apath + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"balance": bal, "history": hist[-500:],
                       "start": TR.START_BALANCE,
                       "leverage": 1.0}, f, ensure_ascii=False)
        os.replace(apath + ".tmp", apath)
        out[arm] = (hist, bal)
    return out


def echo_picks(mdir, src_dir, cur_hour):
    """Скопировать в книгу-эхо выборы источника за текущий час.

    Эхо не выбирает ничего само — его сделки суть сделки источника, и
    копия обязана быть дословной (запись целиком): любое переложение
    полей однажды разошлось бы с оригиналом. Берётся только текущий
    час: эхо начинается с развёртывания, а не импортирует историю
    источника — по прошлой истории корзинное правило не применялось,
    и унаследованная кривая выдавала бы чужую книгу за свою.
    """
    if not cur_hour:
        return 0
    n = 0
    for pk in _read_jsonl(os.path.join(src_dir, "picks.jsonl")):
        if pk.get("hour") == cur_hour and write_pick(mdir, pk):
            n += 1
    return n


def echo_reviews(mdir, src_dir):
    """Скопировать разборы источника для выборов, живущих в эхе.

    Ключ — (рука, час). Закрытие корзины уже занимает его, поэтому
    таймерный разбор источника, пришедший ПОЗЖЕ, не копируется:
    позиция в эхе закрыта раньше, чем в источнике, и второй разбор
    описывал бы сделку, которой в этой книге нет.
    """
    have = {((p.get("arm") or "gbm"), p.get("hour"))
            for p in _read_jsonl(os.path.join(mdir, "picks.jsonl"))}
    seen = {((r.get("arm") or "gbm"), r.get("hour"))
            for r in _read_jsonl(os.path.join(mdir, "review.jsonl"))}
    add = []
    for rv in _read_jsonl(os.path.join(src_dir, "review.jsonl")):
        key = ((rv.get("arm") or "gbm"), rv.get("hour"))
        if key in have and key not in seen:
            add.append(rv)
            seen.add(key)
    if add:
        with open(os.path.join(mdir, "review.jsonl"), "a",
                  encoding="utf-8") as f:
            for rv in add:
                f.write(json.dumps(rv, ensure_ascii=False) + "\n")
    return len(add)


def agree_keys(src_dir, hour):
    """Что выбрала КАЖДАЯ рука источника за час: {(имя, сторона)}.

    Согласие считается из ВЫБОРОВ, не из исходов (правило зонда
    согласия): флаг обязан быть известен в момент входа. Выбор с
    нулевым размером — всё равно решение руки: согласие меряет
    модель, а не кассу.
    """
    keys = {a: set() for a, _ in ARMS}
    for p in _read_jsonl(os.path.join(src_dir, "picks.jsonl")):
        if p.get("hour") != hour:
            continue
        arm = p.get("arm") or "gbm"
        if arm not in keys:
            continue
        for side in ("long", "short"):
            for leg in p.get(side) or []:
                if leg.get("sym"):
                    keys[arm].add((leg["sym"], side))
    return keys


def agree_echo_cycle(mdir, src_dir, cur_hour, hold_h, log_):
    """Один проход согласной книги-эха: пересечение рук источника.

    Решение владельца (2026-08-31) по зонду согласия: у книги 24 ч
    решения, взятые ОБЕИМИ руками, дают +441/+358 б.п. на сделку
    против одиночных (p = 0.000, переживает «без лучшего имени» и
    половины истории). Правило книги одно — нога живёт, только если
    ДРУГАЯ рука в тот же час выбрала то же (имя, сторона); всё
    остальное — дословная копия источника: выбор с отфильтрованными
    ногами, таймерный разбор источника, отфильтрованный до СВОИХ ног
    (лишняя нога разбора описывала бы сделку, которой в книге нет).

    Час без единого согласия выбора НЕ пишет: книга редкая, как
    ситуационная, и пустая строка выдавала бы решение, которого не
    было. Слоты кассе не назначаются — касса выводит их из потока
    самой книги, как у всякой книги со сроком.

    Замер-предупреждение, вписанный при заведении (разрез слива
    2026-08-31): согласие — фильтр СЕРЕДИНЫ, не хвоста. В дни слива
    08-24…27 согласные теряли наравне с одиночными (−297…−391 б.п.
    на сделку); от хвоста книгу держит дневной тормоз, не фильтр.
    """
    os.makedirs(mdir, exist_ok=True)
    other = {"gbm": "nn", "nn": "gbm"}
    if cur_hour:
        keys = agree_keys(src_dir, cur_hour)
        for pk in _read_jsonl(os.path.join(src_dir, "picks.jsonl")):
            if pk.get("hour") != cur_hour:
                continue
            arm = pk.get("arm") or "gbm"
            if arm not in other:
                continue
            cp = dict(pk)
            kept = total = 0
            for side in ("long", "short"):
                legs = pk.get(side) or []
                total += len(legs)
                cp[side] = [g for g in legs
                            if (g.get("sym"), side)
                            in keys[other[arm]]]
                kept += len(cp[side])
            if kept:
                # Сколько отфильтровано — в саму запись: правило
                # проверяется числом по артефакту, а не доверием.
                cp["agree_kept"] = [kept, total]
                write_pick(mdir, cp)
    # Разборы источника — для своих часов и ТОЛЬКО своих ног.
    have = {}
    for p in _read_jsonl(os.path.join(mdir, "picks.jsonl")):
        k = ((p.get("arm") or "gbm"), p.get("hour"))
        have[k] = {(g.get("sym"), s) for s in ("long", "short")
                   for g in p.get(s) or []}
    seen = {((r.get("arm") or "gbm"), r.get("hour"))
            for r in _read_jsonl(os.path.join(mdir, "review.jsonl"))}
    add = []
    for rv in _read_jsonl(os.path.join(src_dir, "review.jsonl")):
        key = ((rv.get("arm") or "gbm"), rv.get("hour"))
        if key not in have or key in seen:
            continue
        cp = dict(rv)
        cp["rows"] = [r for r in rv.get("rows") or []
                      if (r.get("sym"), r.get("side")) in have[key]]
        add.append(cp)
        seen.add(key)
    if add:
        with open(os.path.join(mdir, "review.jsonl"), "a",
                  encoding="utf-8") as f:
            for rv in add:
                f.write(json.dumps(rv, ensure_ascii=False) + "\n")
    rebuild_accounts(mdir, hold_h)
    return len(add)


def basket_state(trades, arm):
    """Деньги корзины руки: сумма нереализованного нетто открытых.

    Возвращает `(pnl, открытые, без цены)`. Деньги — только по
    позициям с размером и переоценкой, та же арифметика, что у
    `unreal_pnl` сводки (size × unreal_net_bp): вторая формула
    разошлась бы с той, которую владелец видит на странице. Позиция
    БЕЗ цены блокирует решение у вызывающего: её минус мог быть
    любым, и закрывать корзину, не видя одной ноги, значило бы
    решать вслепую. Позиция без размера (кассе не хватило денег)
    экспозиции не несёт и в сумму не входит, но закрывается вместе
    со всеми — корзина закрывается целиком, а не по описи.
    """
    op = [t for t in trades
          if t.get("arm") == arm and t.get("state") == "открыта"]
    unpriced = [t for t in op if t.get("unreal_bp") is None]
    pnl = round(sum(t["size"] * t["unreal_net_bp"] / 1e4
                    for t in op
                    if t.get("size")
                    and t.get("unreal_net_bp") is not None), 2)
    return pnl, op, unpriced


def basket_close_records(op, arm, reason, now, books=None):
    """Записи разбора закрытия корзины — по одной на час выбора.

    Форма строки та же, что у таймерного разбора, с полями раннего
    выхода, как у живых выходов ситуационной книги: `got` — сырой ход
    цены (переоценка, у шорта с обратным знаком), `net` — ход по
    позиции минус круг, `exit_ts` — секунда решения: касса возвращает
    деньги тогда, когда закрытие случилось, а не концом часа.
    """
    ex_hour = datetime.fromtimestamp(now, timezone.utc)\
        .strftime("%Y-%m-%d-%H")
    by_hour = {}
    for t in op:
        by_hour.setdefault(t.get("hour"), []).append(t)
    recs = []
    for hour in sorted(by_hour):
        rows = []
        for t in sorted(by_hour[hour], key=lambda q: q.get("sym") or ""):
            raw = (t["unreal_bp"] if t.get("side") == "long"
                   else -t["unreal_bp"])
            r = {"sym": t.get("sym"), "side": t.get("side"),
                 "expected": t.get("expected_bp"),
                 "got": round(raw, 1),
                 "net": t.get("unreal_net_bp"),
                 "exit_hour": ex_hour,
                 "exit_ts": round(now, 3),
                 "reason": reason,
                 "exit_px": t.get("cur_px")}
            cum = (books or {}).get(t.get("sym"))
            if cum is not None:
                r["cum"] = cum
            rows.append(r)
        recs.append({"arm": arm, "hour": hour,
                     "cost_bp": TR.ROUND_COST_BP,
                     "at_ts": round(now, 3), "rows": rows})
    return recs


def basket_echo_cycle(mdir, src_dir, cur_hour, take_share, floor_share,
                      book_root, log_, now=None, prices=None,
                      age_h=None, timer_exits=True, slots=None):
    """Один проход корзинной книги-эха: копия, переоценка, решение.

    Проверка ЧАСОВАЯ — раз в цикл, вместе с остальными книгами: у
    порогов масштаб суточного хода кривой, минутная точность им не
    нужна, а отдельный сторож был бы второй реализацией переоценки.
    `prices` — цены для переоценки (тестам); живой прогон берёт
    середину книги в момент решения (`live_px`).

    `timer_exits=False` — книга БЕЗ отдельных выходов (`model_h24c`):
    разборы источника не копируются вовсе, сделки собираются без
    срока (`hold_h=None` — сборка с горизонтом перевела бы ноги в
    «ждёт разбора» по часам и вернула бы кассе деньги, которые
    позиция ещё держит), а `age_h` даёт третий повод закрыть корзину
    целиком — возраст старейшей открытой ноги. Приоритет у порогов:
    задетые цель и предел называются своим именем, возраст решает
    только когда пороги молчат (порядок реплея probe_basket).

    Возвращает `{рука: (причина, деньги, позиций)}` по закрытым.
    """
    now = now if now is not None else time.time()
    os.makedirs(mdir, exist_ok=True)
    echo_picks(mdir, src_dir, cur_hour)
    if timer_exits:
        echo_reviews(mdir, src_dir)
    build_h = BASKET_H if timer_exits else None
    picks = _read_jsonl(os.path.join(mdir, "picks.jsonl"))
    closed = {}
    for arm, _ in ARMS:
        reviews = _read_jsonl(os.path.join(mdir, "review.jsonl"))
        trades = TR.build(picks, reviews, now=now, hold_h=build_h)
        TR.account(trades, arm, hold_h=BASKET_H, slots=slots)
        op = [t for t in trades
              if t.get("arm") == arm and t.get("state") == "открыта"]
        if not op:
            continue
        syms = sorted({t["sym"] for t in op})
        px = (prices if prices is not None
              else {s: v[0] for s, v in
                    live_px(syms, book_root).items()})
        TR.mark(trades, px)
        pnl, op, unpriced = basket_state(trades, arm)
        if unpriced:
            # Пропуск, а не ноль: непереоценённая нога могла быть в
            # любом минусе, и решение по неполной сумме было бы
            # решением вслепую. Причина видна журналом, а не молчит.
            log_(f"корзина {os.path.basename(mdir)}/{arm}: у "
                 f"{len(unpriced)} позиций из {len(op)} нет цены — "
                 "решение не принимается")
            continue
        cap = TR.START_BALANCE
        if pnl >= take_share * cap:
            reason = BASKET_TAKE_REASON
        elif floor_share is not None and pnl <= -floor_share * cap:
            reason = BASKET_FLOOR_REASON
        elif age_h is not None and now - min(
                (t.get("opened_at") or now) for t in op) \
                >= age_h * 3600:
            reason = BASKET_AGE_REASON
        else:
            continue
        bk = stamp_book(syms, now, book_root, log_, "выхода корзины")
        recs = basket_close_records(op, arm, reason, now, books=bk)
        with open(os.path.join(mdir, "review.jsonl"), "a",
                  encoding="utf-8") as f:
            for rv in recs:
                f.write(json.dumps(rv, ensure_ascii=False) + "\n")
        closed[arm] = (reason, pnl, len(op))
        log_(f"корзина {os.path.basename(mdir)}/{arm}: {reason} "
             f"({pnl:+.2f} $ по {len(op)} позициям) — закрыта целиком")
    rebuild_accounts(mdir, build_h, slots=slots)
    return closed


def live_px(syms, book_root, now=None, log_=None):
    """Цена, доступная В МОМЕНТ РЕШЕНИЯ, а не в момент сигнала.

    Признаки кончаются закрытием часа `t`, а цикл будит инференс через
    несколько минут после него — замер на живом предпросмотре даёт
    медиану 393 с и максимум 921. Войти по закрытию часа `t` значит
    купить по цене, которой в момент решения уже нет: это ровно тот
    подарок, который зонд L1 снимал правилом `next_open`, а зонд
    возврата измерил числом — минута задержки съедала 55–70 % эффекта.

    Здесь брать «открытие следующего бара» нечего: сетка часовая, а
    следующий бар кончится через час. Зато сборщик пишет снимок книги
    раз в секунду, и текущий (незакрытый) час лежит простым файлом —
    его последняя запись и есть первая доступная нам цена.

    Возвращает `{sym: (mid, t)}`. Символ без свежего снимка в словарь
    не попадает: цена входа тогда останется прежней, и это видно в
    самой сделке полем `px_live`, а не молча.
    """
    now = now if now is not None else time.time()
    out = {}
    if not book_root:
        # Записи стакана нет вовсе — числа не будет, и это правильно:
        # пропуск обязан остаться пропуском.
        return out
    for sym in syms:
        r = book_at(sym, now, book_root)
        if r is not None:
            out[sym] = ((r["bid"] + r["ask"]) / 2.0, r.get("t") or now)
    if log_ is not None and len(out) < len(syms):
        log_(f"живая цена входа найдена у {len(out)} имён из {len(syms)}")
    return out


def book_at(sym, ts, book_root, tol=120.0):
    """Снимок книги, ближайший к моменту `ts` и не позже него.

    «Не позже» — не придирка: снимок будущего есть заглядывание, а на
    выходе сделки он дал бы цену, которой в момент закрытия ещё не
    было. Допуск в две минуты нужен потому, что запись идёт раз в
    секунду и может прерваться; дальше двух минут снимок описывает уже
    другой рынок, и вернуть его значило бы выдать соседний час за наш.
    """
    if not book_root or ts is None:
        return None
    hour = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d-%H")
    best = None
    # Час метки и предыдущий: момент может прийтись на первые секунды
    # часа, где своих снимков ещё нет.
    for h in (hour, datetime.fromtimestamp(
            ts - 3600, timezone.utc).strftime("%Y-%m-%d-%H")):
        try:
            rows = SM.read_hour(os.path.join(book_root, "book", sym), h)
        except OSError:
            continue
        for r in rows:
            t = r.get("t")
            if t is None or t > ts or ts - t > tol:
                continue
            if not r.get("bid") or not r.get("ask"):
                continue
            if best is None or t > best.get("t", 0):
                best = r
        if best is not None:
            break
    return best


def stamp_book(syms, ts, book_root, log_=None, what=""):
    """`{символ: {mid, b, a, t}}` — книга для расчёта исполнения.

    Лесенка сжимается `trades.cum_ladder` до потолка нотионала: снимок
    несёт до двухсот уровней, а сделке нужны первые несколько. Сжимает
    ОДНА функция, потому что по этим же числам считается цена
    исполнения, и вторая её запись однажды разошлась бы.
    """
    out = {}
    if not book_root:
        return out
    for sym in syms:
        r = book_at(sym, ts, book_root)
        if r is None:
            continue
        b = TR.cum_ladder(r.get("b"))
        a = TR.cum_ladder(r.get("a"))
        if not b or not a:
            continue
        out[sym] = {"mid": (r["bid"] + r["ask"]) / 2.0,
                    "b": b, "a": a, "t": round(r.get("t") or ts, 1)}
    if log_ is not None and len(out) < len(syms):
        log_(f"книга {what}: снята у {len(out)} имён из {len(syms)}")
    return out


def log_cycle(row, log_):
    """Строка журнала циклов. Один писатель на оба пути.

    Часовой цикл и цикл с обучением пишут в один файл, и `kind`
    различает их: без метки суточная медиана смешала бы двухминутный
    прогон с полуторачасовым и сказала бы неправду про оба. Запись
    прежнего образца метки не несёт — она вся про обучение, и читатель
    трактует её отсутствие как `train`.
    """
    try:
        with open(os.path.join(MODEL_DIR, "train_log.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        log_(f"журнал обучений не дописан: {e}")


def train_due(prev_man, now_ts, every_h=None):
    """Пора ли переобучать: (да/нет, причина словами).

    Каденция берётся из модуля В МОМЕНТ ВЫЗОВА, а не из значения по
    умолчанию: `every_h=TRAIN_EVERY_H` в сигнатуре связывается при
    определении функции, и подмена константы после импорта не меняла
    бы ничего — правило, которое нельзя переставить, невозможно и
    проверить.

    Причина возвращается ВСЕГДА и уезжает в журнал: цикл, молча
    пропустивший обучение, неотличим от цикла, который не смог, — а
    это ровно тот класс отказа, против которого весь проект.

    Обучение обязательно, если весов нет, если манифест не помнит
    времени обучения и если это время В БУДУЩЕМ (переставленные часы,
    восстановленная копия): свежесть, посчитанная от будущего, вечно
    держала бы веса необновлёнными.
    """
    if every_h is None:
        every_h = TRAIN_EVERY_H
    if not prev_man:
        return True, "весов прошлого цикла нет"
    at = prev_man.get("trained_at")
    if not at:
        return True, "манифест без времени обучения"
    try:
        t = datetime.fromisoformat(at).timestamp()
    except (TypeError, ValueError):
        return True, f"время обучения не разобрано: {at!r}"
    age_h = (now_ts - t) / 3600.0
    if age_h < 0:
        return True, f"время обучения в будущем ({age_h:.1f} ч)"
    if age_h >= every_h:
        return True, f"весам {age_h:.1f} ч при каденции {every_h}"
    return False, f"весам {age_h:.1f} ч при каденции {every_h}"


def load_prev_models(names):
    """Веса ПРОШЛОГО цикла с диска — для шага книг до обучения.

    Ранний шаг книг законен только на полном и совместимом наборе:
    манифест читается (он даёт номер обучения и поля для манифестов
    книг), на диске лежит ВСЯ сетка весов ARMS×TARGETS, и каждый блоб
    обучен на том же списке признаков той же версии модели. Любое
    несовпадение — честный отказ (None): книги в этом цикле пойдут
    после обучения, как раньше. Полнота требуется нарочно: считать
    часть целей прошлыми весами, а часть свежими значило бы смешать
    две модели в одном листе, ничем этого не выдав.
    """
    try:
        with open(os.path.join(MODEL_DIR, "manifest.json"),
                  encoding="utf-8") as f:
            man_prev = json.load(f) or {}
    except (OSError, ValueError):
        return None, 0, None
    if not man_prev.get("train_seq"):
        return None, 0, None
    models = {}
    for arm, _ in ARMS:
        for tgt in TARGETS:
            wp = os.path.join(MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            try:
                with open(wp, "rb") as f:
                    blob = pickle.load(f)
            except (OSError, EOFError, AttributeError, ImportError,
                    pickle.UnpicklingError):
                return None, 0, None
            if (blob.get("version") != MODEL_VERSION
                    or blob.get("features") != names):
                return None, 0, None
            models[(arm, tgt)] = blob["model"]
    return models, int(man_prev["train_seq"]), man_prev


def cand_sheet_entry(b):
    """Запись кандидата в списке книг листа сечения.

    Гейт кандидата — правило из реестра испытаний, а не настройка
    книги ядра: пол входа, полоса отношения, места и требование
    согласия рук приходят из объявленного правила и переписаны быть
    не могут. Каталог идёт БАЗОВЫМ ИМЕНЕМ, как у книг ядра: сканер
    складывает его со своим корнем.
    """
    g = b.get("gate") or {}
    e = {"dir": b["dir"], "slots": int(g.get("slots") or 6),
         "min_rr": float(g.get("min_rr") or 0.0)}
    if g.get("max_rr") is not None:
        e["max_rr"] = float(g["max_rr"])
    # Пол входа кандидата — на прогнозе ЛИСТА, как у правила v10: это
    # та же величина, по которой отбирает реплей (`passes`), и она
    # известна до всякого хода цены.
    if g.get("floor_bp"):
        e["floor_bp"] = float(g["floor_bp"])
    # Места по СТОРОНАМ: реплей считает ширину на сторону, и общий
    # счётчик пустил бы десять лонгов в книгу шириной пять.
    if g.get("per_side"):
        e["per_side"] = int(g["per_side"])
    if g.get("agree"):
        e["agree"] = True
    # Книга «выход по времени» уровней не имеет вовсе, и 5-секундный
    # сторож обязан знать об этом: иначе он закрывал бы по стопу и
    # цели то, чему уровней не объявляли, и книга торговала бы не своё
    # правило. Флаг едет ЛИСТОМ, а не выводится сканером из имени
    # каталога, — состав книг объявляет цикл, второго списка нет.
    if g.get("no_levels"):
        e["no_levels"] = True
    return e


def cand_book(b, sm, models_b, x, mats, syms, rows_sit, j_last, grid,
              nov_lo, nov_hi, book_root, log_, *, beta_row, names,
              train_seq):
    """Свести одну книгу кандидата: манифест, выборы, счёт.

    Манифест несёт ПРАВИЛО целиком (`rule`) и применённые пороги: файл
    `books_extra.json` есть инструкция, а манифест — запись о том, чем
    книга торговала на самом деле, и расхождение между ними обязано
    быть видно. Смена правила отставляет книгу в архив тем же
    механизмом, что у сестринских книг, — правило кандидата в реестре
    неизменно, поэтому это страховка, а не рабочий путь.

    Вылетевший кандидат книгу сохраняет и НЕ берёт новых входов: его
    записи нет в списке книг листа, значит сканер её не видит, а
    разбор и счёт идут — выход есть обязанность перед позицией.
    """
    g = b.get("gate") or {}
    cdir = MODEL_DIR + BK.suffix(b["key"], BK.load()[0])
    rules = {"exit_policy": (SIT_AGE_ONLY if g.get("no_levels")
                            else SIT_LEVELS_AGE),
             "min_rr": float(g.get("min_rr") or 0.0),
             "max_rr": g.get("max_rr"),
             "floor_bp": g.get("floor_bp"),
             "per_side": g.get("per_side"),
             "agree": bool(g.get("agree")),
             "sizing": b.get("sizing")}
    fresh_sit_on_rules_change(cdir, log_, rules=rules)
    os.makedirs(cdir, exist_ok=True)
    cm = dict(sm, candidate=True, lane=b.get("lane"),
              rule=b.get("rule"), declared_at=b.get("declared_at"),
              retired_at=b.get("retired_at"),
              slots=int(g.get("slots") or 6),
              # Предел возраста — ось правила (24 ч либо 72), и часовые
              # выходы берут его отсюда, а не из глобальной константы.
              max_age_h=float(g.get("age_h") or 24),
              **rules)
    mp = os.path.join(cdir, "manifest.json")
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(cm, f, ensure_ascii=False, indent=1)
    os.replace(mp + ".tmp", mp)
    for arm, _ in ARMS:
        situational_arm(cdir, arm, models_b, x, mats, syms, rows_sit,
                        j_last, grid, nov_lo, nov_hi, book_root, log_,
                        beta_row=beta_row, names=names,
                        train_seq=train_seq)
    rebuild_accounts(cdir, None, slots=int(g.get("slots") or 6))


def candidate_books(log_):
    """Кандидаты фабрики → живые книги. Возвращает список записей.

    Решение владельца (2026-09-02): объявленный кандидат обязан
    получить ЖИВУЮ бумажную книгу, а не только реплей по журналу
    листов. Реплей отвечает «что бы вышло», живая книга — «что
    выходит», и второе и есть предмет поиска.

    Состояние пишется ЦЕЛИКОМ из реестра испытаний каждый цикл, а не
    дельтой: список книг есть функция реестра, и дописывание однажды
    оставило бы книгу, которой в реестре уже нет (тот же дефект, что
    сводка сборки в A2 — там признаком результата служила дельта
    прогона вместо состояния диска).

    Отказ здесь НЕ роняет цикл и не молчит: фабрики может не быть
    вовсе (песочница, демо-прогон), и это норма; сломанный реестр —
    строка в журнал, а книги ядра идут как шли.
    """
    # Демо- и песочный прогон книг кандидатов НЕ заводит: `MODEL_DIR`
    # у него подменён, а файл состава лежит рядом с реестром книг —
    # то есть один и тот же на боевой и на песочный прогон. Песочница
    # переписала бы боевой состав книг, и это был бы отказ, невидимый
    # до следующего часа.
    if PROBE or PRETEST or MODEL_DIR != LIVE_MODEL_DIR:
        return []
    try:
        sys.path.insert(0, os.path.join(RESEARCH, "factory"))
        import ledger as LGF
        import live_books as LB
        import space as SPF
    except ImportError as e:
        log_(f"кандидаты фабрики не читаны: {type(e).__name__}: {e}")
        return []
    fdir = FACTORY_OUT
    if not os.path.exists(LGF.path(fdir)):
        return []                     # фабрика книг ещё не заводила
    try:
        rows, broken = LGF.read(fdir)
        st = LGF.state(rows)
        books, skipped = LB.build(st, describe=SPF.describe)
        LB.write(EXTRAS_PATH, books)
    except (OSError, ValueError) as e:
        log_(f"книги кандидатов не собраны: {type(e).__name__}: {e}")
        return []
    live = sum(1 for b in books if not b.get("retired_at"))
    # Пропущенные считаются ЧИСЛОМ и называются причиной: «книги нет»
    # и «книга невозможна» снаружи неотличимы, а нам надо знать, какую
    # часть пула мы судим вживую.
    log_(f"кандидаты фабрики: книг {len(books)} (живых {live}), "
         f"без живой книги {len(skipped)}"
         + (", битых строк реестра %d" % broken if broken else ""))
    for sk in skipped:
        log_(f"  {sk['id']}: живой книги нет — {sk['why']}")
    return books


def run_books(models_b, seq_b, man_b, *, x, mats, syms, targets, elig,
              grid, si, j_last, rows_m, nov_lo, nov_hi, names,
              book_root, log_, n_sections):
    """Шаг книг: разбор, выборы, лист сканера и счета всех книг.

    Вынесен из тела цикла, чтобы идти ДО обучения, на весах прошлого
    часа (правка по SCRTUSDT): цена циклового выхода — закрытие часа,
    исполняет его живой исполнитель в момент записи, и всё, что стоит
    в цикле перед этим шагом, живая сделка оплачивает ходом цены.
    `models_b`/`seq_b`/`man_b` — веса, номер обучения и манифест,
    КОТОРЫМИ считаются выборы: у раннего пути это прошлый цикл, у
    запасного — только что обученные. Номер обучения в записи выбора
    и в листе — номер этих весов, а не текущего цикла: сделка обязана
    называть веса, которыми посчитана. Возвращает разборы и выборы по
    рукам и строки счёта — мысли пишутся позже, по свежему манифесту.
    """
    out = {"arms": {}, "acct_lines": []}
    # Дневной тормоз (забор владельца 2026-08-29): состояние пишет
    # сборщик (`day_brake.json`, единственный писатель — деньги считает
    # та же касса, что у страниц), цикл только читает. Тормоз закрывает
    # ВХОДЫ часовых книг (выборы часа не пишутся); разбор, выходы,
    # счета и лист сканера идут как шли — выход есть обязанность.
    # Устаревшее или отсутствующее состояние не тормозит (fail-open):
    # сборщик мог стоять, и молча замереть без входов было бы отказом,
    # неотличимым от тишины. Факт блокировки — строкой в журнал
    # тормоза: час без выборов обязан читаться работой правила.
    # Файл лежит РЯДОМ с каталогами книг (родитель MODEL_DIR): в бою
    # это s8_loop/out, в тестах — временный корень фикстуры.
    brake_st, braked = TR.read_day_brake(
        os.path.join(os.path.dirname(MODEL_DIR), TR.DAY_BRAKE_FILE),
        time.time())
    if braked:
        log_(f"ДНЕВНОЙ ТОРМОЗ: день {brake_st.get('realized', 0):+.2f} $ "
             f"при пороге −{brake_st.get('limit', 0):.0f} — выборы часа "
             f"{grid[j_last] if j_last is not None else '—'} не пишутся; "
             f"разбор и выходы идут")
        try:
            with open(os.path.join(MODEL_DIR, "brake_log.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(
                    {"hour": grid[j_last] if j_last is not None else None,
                     "at": round(time.time(), 1),
                     "realized": brake_st.get("realized"),
                     "limit": brake_st.get("limit")},
                    ensure_ascii=False) + "\n")
        except OSError as e:
            log_(f"журнал тормоза не записан: {e}")
    # Выбор -> ожидание -> факт, по каждой руке турнира отдельно:
    # сводка по смеси рук осмысленна на вид и бессмысленна по сути.
    # Разбираются ВСЕ неразобранные выборы, а не только последний
    # (`review_arm`); выбор пишется один на (руку, час) — дубли
    # перезапусков снимает `write_pick`.
    # Порядок сечения главной книги сменился — прежние сделки в архив.
    fresh_book_on_rank_change(MODEL_DIR, rank_key_for(TR.HOLD_H), log_,
                              floor=H4_FLOOR_BP)
    for arm, _ in ARMS:
        # Последний ЗАПИСАННЫЙ разбор, а не последняя итерация цикла:
        # у свежего выбора форвард ещё не закрыт, разбор выходит пустым,
        # и мысли молчали бы о разборе, который на деле состоялся.
        review = review_arm(MODEL_DIR, arm, TR.HOLD_H, targets, si,
                            grid, book_root, log_)
        picks = [] if braked else make_pick(
            arm, TR.HOLD_H, models_b, x, mats, syms, rows_m,
            j_last, grid, nov_lo, nov_hi, book_root, log_,
            names=names, train_seq=seq_b,
            rank_key=rank_key_for(TR.HOLD_H),
            floor_bp=H4_FLOOR_BP)
        if picks:
            write_pick(MODEL_DIR, picks)
        # Разбор и выбор — в итог: мысли пишутся ПОЗЖЕ, по СВЕЖЕМУ
        # манифесту, а не по тому, чьими весами шли книги.
        out["arms"][arm] = {"review": review, "picks": picks}
    # Счёт пересобирается ЦЕЛИКОМ из выборов и разборов, а не
    # накапливается по шагам (`rebuild_accounts`).
    try:
        for arm, (hist, bal) in rebuild_accounts(
                MODEL_DIR, TR.HOLD_H).items():
            if hist:
                who = "деревья" if arm == "gbm" else "сеть"
                out["acct_lines"].append(
                    f"[{who}] счёт: {bal:+.2f} $ из {TR.START_BALANCE:.0f} "
                    f"после {len(hist)} закрытых сделок "
                    f"({pct((bal / TR.START_BALANCE - 1) * 1e4)} "
                    f"от старта, плечо 1×, издержки учтены).")
    except (OSError, ValueError) as e:
        log_(f"счёт пересобрать не вышло: {e}")

    # Книги остальных горизонтов — турнир темпов. Те же веса и то же
    # сечение, различаются целью (`fwd_{h}h`), сроком закрытия и числом
    # слотов кассы. Каждая живёт своим каталогом; вердикта по ним нет —
    # это наблюдение «какой темп учится быстрее», а не отдельная
    # гипотеза. Ошибка книги не роняет цикл: главная книга и веса уже
    # записаны, а сломанная книга обязана быть видна журналом.
    for h in FB.HORIZONS:
        if h == TR.HOLD_H or h in REMOVED_BOOKS:
            continue
        try:
            mdir = book_dir(h)
            fresh_book_on_rank_change(mdir, rank_key_for(h), log_)
            os.makedirs(mdir, exist_ok=True)
            for arm, _ in ARMS:
                review_arm(mdir, arm, h, targets, si, grid,
                           book_root, log_)
                pk = [] if braked else make_pick(
                    arm, h, models_b, x, mats, syms, rows_m,
                    j_last, grid, nov_lo, nov_hi,
                    book_root, log_, names=names,
                    train_seq=seq_b,
                    rank_key=rank_key_for(h))
                if pk:
                    write_pick(mdir, pk)
            rebuild_accounts(mdir, h)
            # Манифест книги минимален: страница берёт из него
            # присутствие, версию и ГОРИЗОНТ — по нему же сборщик
            # строит сделки с верным сроком закрытия.
            kf = f"fwd_{h}h"
            rk_h = rank_key_for(h)
            n_rows = (int((elig & np.isfinite(targets[kf])).sum())
                      if kf in targets else 0)
            sm = {"version": MODEL_VERSION, "horizon_h": h,
                  "hedge": man_b.get("hedge"),
                  "trained_at": man_b.get("trained_at"),
                  "sections": n_sections, "symbols": len(syms),
                  "canary_ic": man_b.get("canary_ic"),
                  # Готовность цели книги: строка обучения требует
                  # закрытого форварда своего горизонта, и медленная
                  # книга стартует позже быстрых. Без этих чисел пустая
                  # книга неотличима от сломанной.
                  "target": kf, "target_rows": n_rows,
                  "target_need": MIN_TARGET_ROWS,
                  # Чем упорядочено сечение — В АРТЕФАКТЕ, а не в имени
                  # каталога: по нему же следующий цикл узнаёт смену
                  # порядка и отставляет прежнюю книгу.
                  "rank_target": rk_h,
                  "probe": PROBE, "pretest": PRETEST}
            smp = os.path.join(mdir, "manifest.json")
            with open(smp + ".tmp", "w", encoding="utf-8") as f:
                json.dump(sm, f, ensure_ascii=False, indent=1)
            os.replace(smp + ".tmp", smp)
        except Exception as e:                            # noqa: BLE001
            log_(f"книга {h} ч не сведена: {type(e).__name__}: {e}")

    # Контрольная пара горизонта 24 ч: тот же горизонт, то же сечение и
    # та же геометрия, отличается РОВНО порядок — по прогнозу,
    # делённому на волатильность монеты. Прежде такая пара стояла на
    # 4 ч (`model_z`); с переводом главной книги на σ она стала бы
    # дубликатом, и вопрос «помогает ли per σ» решать было бы нечем.
    # Пара переехала на 24 ч решением владельца: сравнение сохраняется,
    # но на том горизонте, который не переводится.
    #
    # Прежний каталог `model_z` больше не пишется. Его история — это и
    # есть накопленная запись торговли в σ на 4 ч, и трогать её нельзя:
    # с ней сравнивают то, что главная книга начнёт писать теперь.
    try:
        zdir = book_dir(24, sigma=True)
        os.makedirs(zdir, exist_ok=True)
        for arm, _ in ARMS:
            review_arm(zdir, arm, 24, targets, si, grid,
                       book_root, log_)
            pk = make_pick(arm, 24, models_b, x, mats, syms,
                           rows_m, j_last, grid, nov_lo, nov_hi,
                           book_root, log_, names=names, train_seq=seq_b,
                           rank_key=rank_key_for(24, sigma=True))
            if pk:
                write_pick(zdir, pk)
        rebuild_accounts(zdir, 24)
        zkey = rank_key_for(24, sigma=True)
        n_z = (int((elig & np.isfinite(targets[zkey])).sum())
               if zkey in targets else 0)
        zm = {"version": MODEL_VERSION, "horizon_h": 24,
              "hedge": man_b.get("hedge"), "trained_at": man_b.get("trained_at"),
              "sections": n_sections, "symbols": len(syms),
              "canary_ic": man_b.get("canary_ic"),
              # Чем эта книга отличается от главной — В АРТЕФАКТЕ, а не
              # в имени каталога: через месяц по записи должно быть
              # видно, каким правилом её сечение упорядочено.
              "rank_target": zkey, "target": "fwd_24h",
              "target_rows": n_z, "target_need": MIN_TARGET_ROWS,
              "probe": PROBE, "pretest": PRETEST}
        zp = os.path.join(zdir, "manifest.json")
        with open(zp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(zm, f, ensure_ascii=False, indent=1)
        os.replace(zp + ".tmp", zp)
    except Exception as e:                                # noqa: BLE001
        log_(f"книга в σ не сведена: {type(e).__name__}: {e}")

    # Корзинные книги-эхо 24 ч (решение владельца 2026-08-14): те же
    # выборы, что у model_h24, но раз в цикл проверяется ОБЩИЙ
    # нереализованный результат открытых позиций руки, и порог
    # закрывает корзину целиком. `model_h24b` — только тейк (+5 %
    # капитала руки), `model_h24bf` — тейк плюс симметричный пол −5 %:
    # диагностическая рука вопроса владельца «пересиживать общий минус
    # или резать». В лигу и суммы корня книги не входят (эхо чужих
    # решений); порядок сечения им не проверяется — он унаследован
    # копией выборов источника.
    # …а `model_h24c` (решение владельца 2026-08-30) — корзина БЕЗ
    # отдельных выходов вовсе: закрытие только целиком — цель +5 %,
    # предел −5 % либо возраст 24 ч (горизонт сигнала — единственный
    # порог с якорем; 48 ч из реплея выглядел лучше, но был бы
    # выбором по просмотренной поверхности). Слоты у книги без срока
    # фиксированы числом реплея.
    for bdir, b_take, b_floor, b_age, b_timer in (
            (MODEL_DIR + BK.suffix("h24b"),
             BASKET_TAKE_SHARE, None, None, True),
            (MODEL_DIR + BK.suffix("h24bf"), BASKET_TAKE_SHARE,
             BASKET_FLOOR_SHARE, None, True),
            (MODEL_DIR + BK.suffix("h24c"), BASKET_TAKE_SHARE,
             BASKET_FLOOR_SHARE, BASKET_AGE_H, False)):
        try:
            # У манифестов эха нет версии ситуационных правил —
            # сравнение с ней отставляло бы книгу каждый цикл; решает
            # словарь правил самой книги (version=1). Новые ключи
            # (возраст, отсутствие таймера) в правила h24b/h24bf НЕ
            # добавляются: отсутствие поля в манифесте — тоже смена,
            # и их истории отставились бы ни за что.
            rules = {"basket_take_share": b_take,
                     "basket_floor_share": b_floor}
            if not b_timer:
                rules["basket_age_h"] = b_age
                rules["no_timer"] = True
            fresh_sit_on_rules_change(bdir, log_, version=1,
                                      rules=rules)
            os.makedirs(bdir, exist_ok=True)
            bkf = f"fwd_{BASKET_H}h"
            n_rows = (int((elig & np.isfinite(targets[bkf])).sum())
                      if bkf in targets else 0)
            bkm = {"version": MODEL_VERSION, "horizon_h": BASKET_H,
                   "hedge": man_b.get("hedge"),
                   "trained_at": man_b.get("trained_at"),
                   "sections": n_sections, "symbols": len(syms),
                   "canary_ic": man_b.get("canary_ic"),
                   # Эхо: сделки — копия model_h24, своё только
                   # корзинное правило. Пороги — в артефакт: страница
                   # объясняет книгу по ним, а `fresh_…` ловит их
                   # смену и отставляет несшиваемую историю.
                   "echo_of": "model_h24",
                   "basket_take_share": b_take,
                   "basket_floor_share": b_floor,
                   "rank_target": rank_key_for(BASKET_H),
                   "target": bkf, "target_rows": n_rows,
                   "target_need": MIN_TARGET_ROWS,
                   "probe": PROBE, "pretest": PRETEST}
            if not b_timer:
                bkm.update({"basket_age_h": b_age, "no_timer": True,
                            "slots": BASKET_SLOTS,
                            "max_age_h": b_age})
            bmp = os.path.join(bdir, "manifest.json")
            with open(bmp + ".tmp", "w", encoding="utf-8") as f:
                json.dump(bkm, f, ensure_ascii=False, indent=1)
            os.replace(bmp + ".tmp", bmp)
            basket_echo_cycle(bdir, book_dir(BASKET_H),
                              grid[j_last] if j_last is not None
                              else None,
                              b_take, b_floor, book_root, log_,
                              age_h=b_age, timer_exits=b_timer,
                              slots=(None if b_timer
                                     else BASKET_SLOTS))
        except Exception as e:                        # noqa: BLE001
            log_(f"корзинная книга {os.path.basename(bdir)} не "
                 f"сведена: {type(e).__name__}: {e}")

    # Согласные книги-эхо (решение владельца 2026-08-31, по зонду
    # согласия и разрезу слива): у источника остаётся ровно
    # ПЕРЕСЕЧЕНИЕ рук — нога живёт, только если обе руки в тот же час
    # выбрали то же (имя, сторона). `model_h24a` — от model_h24,
    # `model_h24za` — от model_h24z (per σ). Выходы — таймерные
    # разборы источника по своим ногам; правило одно, различие
    # результатов принадлежит ему. Эхо: в лигу, суммы корня и тормоз
    # книги не входят. Согласие — фильтр середины, не хвоста (в слив
    # согласные теряли наравне) — от хвоста остаётся дневной тормоз.
    for adir, a_srcdir, a_src in (
            (MODEL_DIR + BK.suffix("h24a"), book_dir(BASKET_H),
             "model_h24"),
            (MODEL_DIR + BK.suffix("h24za"), book_dir(24, sigma=True),
             "model_h24z")):
        try:
            fresh_sit_on_rules_change(adir, log_, version=1,
                                      rules={"agree_filter": True})
            os.makedirs(adir, exist_ok=True)
            akey = (rank_key_for(24, sigma=True)
                    if a_src == "model_h24z"
                    else rank_key_for(BASKET_H))
            n_a = (int((elig & np.isfinite(targets[akey])).sum())
                   if akey in targets else 0)
            am = {"version": MODEL_VERSION, "horizon_h": BASKET_H,
                  "hedge": man_b.get("hedge"),
                  "trained_at": man_b.get("trained_at"),
                  "sections": n_sections, "symbols": len(syms),
                  "canary_ic": man_b.get("canary_ic"),
                  # Эхо: сделки — пересечение рук источника, своё
                  # только правило согласия. Оно в артефакте: страница
                  # объясняет книгу по нему, `fresh_…` ловит смену.
                  "echo_of": a_src, "agree_filter": True,
                  "rank_target": akey, "target": f"fwd_{BASKET_H}h",
                  "target_rows": n_a, "target_need": MIN_TARGET_ROWS,
                  "probe": PROBE, "pretest": PRETEST}
            amp = os.path.join(adir, "manifest.json")
            with open(amp + ".tmp", "w", encoding="utf-8") as f:
                json.dump(am, f, ensure_ascii=False, indent=1)
            os.replace(amp + ".tmp", amp)
            agree_echo_cycle(adir, a_srcdir,
                             grid[j_last] if j_last is not None
                             else None,
                             BASKET_H, log_)
        except Exception as e:                        # noqa: BLE001
            log_(f"согласная книга {os.path.basename(adir)} не "
                 f"сведена: {type(e).__name__}: {e}")

    # Ситуационная книга: вход когда модель видит ситуацию, выход когда
    # ситуация кончилась. Сигнал — цели главного горизонта; своя касса
    # с фиксированными слотами; правила и пороги — у `situational_arm`.
    # Книги кандидатов фабрики: состав и гейты нужны ДО записи листа —
    # состав книг сканера объявляет лист, и второго списка у сканера
    # нет (два места, решающих одно, однажды разойдутся).
    cands = candidate_books(log_)
    try:
        mdir = MODEL_DIR + BK.suffix("sit")
        fresh_sit_on_rules_change(mdir, log_)
        os.makedirs(mdir, exist_ok=True)
        # Манифест — ДО первых выборов: тень бота читает режим книги
        # из него, и книга с выборами без манифеста один такт
        # считалась бы часовой — с чужими слотами и чужим сроком.
        kf = f"fwd_{SIT_SIGNAL_H}h"
        n_rows = (int((elig & np.isfinite(targets[kf])).sum())
                  if kf in targets else 0)
        sm = {"version": MODEL_VERSION, "situational": True,
              "rules_version": SIT_RULES_VERSION,
              "horizon_h": None, "slots": SIT_SLOTS,
              "hedge": man_b.get("hedge"), "trained_at": man_b.get("trained_at"),
              "sections": n_sections, "symbols": len(syms),
              "canary_ic": man_b.get("canary_ic"),
              # Правила — в артефакт: отчёт обязан описывать тот
              # прогон, который породил файл, а не текущие исходники.
              "min_edge_bp": SIT_MIN_EDGE_BP, "min_rr": SIT_MIN_RR,
              "min_disc_bp": SIT_MIN_DISC_BP,
              "arm_band_bp": SIT_ARM_BAND_BP,
              "max_eaten": SIT_MAX_EATEN,
              "max_age_h": SIT_MAX_AGE_H, "stop_tau": STOP_TAU,
              "target": kf, "target_rows": n_rows,
              "target_need": MIN_TARGET_ROWS,
              "probe": PROBE, "pretest": PRETEST}
        smp = os.path.join(mdir, "manifest.json")
        with open(smp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(sm, f, ensure_ascii=False, indent=1)
        os.replace(smp + ".tmp", smp)
        # Бета по имени — из признака сечения: сканеру она нужна,
        # чтобы вычесть волну из живого хода и сравнить остаток с
        # прогнозом в одних единицах.
        # Решение владельца (2026-08-13): ситуационная книга вправе
        # торговать НЕ-КРИПТО — её выход по уровню, а не по времени,
        # и календарная компонента спреда (базовый актив стоит в
        # выходные) не держит позицию через закрытую биржу неделями.
        # Книги со сроком не-крипто по-прежнему не видят (rows_m).
        rows_sit = (np.flatnonzero(elig[:, j_last])
                    if j_last is not None else rows_m)
        beta_row = None
        if j_last is not None and "beta" in names:
            beta_row = x[rows_sit, j_last, names.index("beta")]
        sheets = {}
        for arm, _ in ARMS:
            sh = situational_arm(mdir, arm, models_b, x, mats, syms,
                                 rows_sit, j_last, grid, nov_lo, nov_hi,
                                 book_root, log_, beta_row=beta_row,
                                 names=names, train_seq=seq_b)
            if sh:
                sheets[arm] = sh
        if sheets and j_last is not None:
            sp = os.path.join(mdir, "scan_sheet.json")
            with open(sp + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"hour": grid[j_last],
                           "written_at": round(time.time(), 1),
                           "train_seq": seq_b,
                           # По какой очереди сканер раздаёт слоты:
                           # гейт ситуационной книги не менялся, а
                           # приоритет менялся, и без этого поля запись
                           # о нём молчала бы.
                           "scan_rank": rank_z(SIT_SIGNAL_H),
                           "min_edge_bp": SIT_MIN_EDGE_BP,
                           "min_rr": SIT_MIN_RR,
                           "min_disc_bp": SIT_MIN_DISC_BP,
                           "arm_band_bp": SIT_ARM_BAND_BP,
                           "max_eaten": SIT_MAX_EATEN,
                           "slots": SIT_SLOTS, "stop_tau": STOP_TAU,
                           # Книги, которые ведёт сканер. Торгуемая
                           # идёт первой и не меняется; наблюдательная
                           # берёт всё, что прошло остальные гейты, —
                           # иначе фильтру владельца нечего добавлять
                           # ниже боевого порога. Обход кандидатов
                           # ОДИН на обе: второй считал бы ту же волну
                           # дважды и мог бы разойтись с первой.
                           "books": [
                               {"dir": os.path.basename(
                                    MODEL_DIR + BK.suffix("sit")),
                                "min_rr": SIT_MIN_RR,
                                "slots": SIT_SLOTS},
                               {"dir": os.path.basename(
                                    MODEL_DIR + BK.suffix("sit_obs")),
                                "min_rr": SIT_OBS_MIN_RR,
                                "slots": SIT_OBS_SLOTS,
                                # Наблюдательную запись дневной тормоз
                                # НЕ трогает: она и есть контрольная
                                # рука — без неё цену тормоза потом
                                # нечем измерить. Денег она не держит.
                                "no_brake": True},
                               # Книга равного риска: те же гейты и
                               # места, что у торгуемой, — различие
                               # ровно одно, правило РАЗМЕРА (равный
                               # доллар риска, манифест sizing).
                               # Контрольная рука: другой состав
                               # сделок не позволил бы приписать
                               # разницу правилу.
                               # Её же правило запаса: стоп не
                               # тоньше полутора живых шумов (после
                               # #ptadyrc — стоп в один фитиль).
                               {"dir": os.path.basename(
                                    MODEL_DIR + BK.suffix("sit_r")),
                                "min_rr": SIT_MIN_RR,
                                "slots": SIT_SLOTS,
                                "noise_mult": SIT_R_NOISE_MULT,
                                "min_stop_bp": SIT_R_MIN_STOP_BP},
                               # Книга низкого RR: тот же кандидат,
                               # другой конец распределения отношения.
                               # Потолок вместо пола — и это ЕДИНСТ-
                               # венное отличие от торгуемой.
                               {"dir": os.path.basename(
                                    MODEL_DIR + BK.suffix("sit_lo")),
                                "min_rr": 0.0,
                                "max_rr": SIT_LO_MAX_RR,
                                "slots": SIT_LO_SLOTS},
                           ] + [cand_sheet_entry(b) for b in cands
                                if not b.get("retired_at")],
                           "arms": sheets}, f, ensure_ascii=False)
            os.replace(sp + ".tmp", sp)
            # Лист ПЕРЕЗАПИСЫВАЕТСЯ каждый час, то есть история решений
            # не хранится нигде: перебрать пороги задним числом можно
            # было бы только по шести выбранным именам, а не по всему
            # сечению. Дописываем копию в журнал — 500 имён на час это
            # около мегабайта в сутки, а без него любой вопрос «а если
            # бы порог был другим» упирается в то, что спрашивать не у
            # чего.
            with open(os.path.join(mdir, "sheets.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(
                    {"hour": grid[j_last],
                     "written_at": round(time.time(), 1),
                     "train_seq": seq_b,
                     "scan_rank": rank_z(SIT_SIGNAL_H),
                     "min_edge_bp": SIT_MIN_EDGE_BP,
                     "min_rr": SIT_MIN_RR,
                     "min_disc_bp": SIT_MIN_DISC_BP,
                     "arm_band_bp": SIT_ARM_BAND_BP,
                     "max_eaten": SIT_MAX_EATEN,
                     "slots": SIT_SLOTS, "stop_tau": STOP_TAU,
                     "arms": sheets},
                    ensure_ascii=False) + "\n")
        rebuild_accounts(mdir, None, slots=SIT_SLOTS)
        # Наблюдательная книга: та же ситуация без требования к
        # отношению. Свой каталог, свой счёт, своя запись — торгуемая
        # не меняется ни чем, и тень бота её не читает. Лист сечения
        # один на обе: он лежит у торгуемой, сканер берёт из него
        # состав книг.
        obs = MODEL_DIR + BK.suffix("sit_obs")
        fresh_sit_on_rules_change(obs, log_)
        os.makedirs(obs, exist_ok=True)
        som = dict(sm, slots=SIT_OBS_SLOTS, min_rr=SIT_OBS_MIN_RR,
                   observation=True)
        with open(os.path.join(obs, "manifest.json.tmp"), "w",
                  encoding="utf-8") as f:
            json.dump(som, f, ensure_ascii=False, indent=1)
        os.replace(os.path.join(obs, "manifest.json.tmp"),
                   os.path.join(obs, "manifest.json"))
        for arm, _ in ARMS:
            situational_arm(obs, arm, models_b, x, mats, syms,
                            rows_m, j_last, grid, nov_lo, nov_hi,
                            book_root, log_, beta_row=beta_row,
                            names=names, train_seq=seq_b)
        rebuild_accounts(obs, None, slots=SIT_OBS_SLOTS)
        # Книга равного риска (просьба владельца): при одном RR тейк
        # приносил то 20 $, то 5 $, а стоп забирал 15 — уровни у
        # сделок разной ширины, а размер один, и доллар риска пляшет.
        # Здесь размер обратен исполняемому стопу: стоп всегда −R,
        # тейк при RR r — +r·R. Сделки ТЕ ЖЕ, что у торгуемой
        # (гейты и места совпадают): меняется только распределение
        # размера, и разница результатов принадлежит правилу.
        rbk = MODEL_DIR + BK.suffix("sit_r")
        fresh_sit_on_rules_change(rbk, log_, rules={
            "exit_policy": SIT_R_EXIT_POLICY,
            "noise_mult": SIT_R_NOISE_MULT,
            "min_stop_bp": SIT_R_MIN_STOP_BP})
        os.makedirs(rbk, exist_ok=True)
        srm = dict(sm, sizing="fixed_risk",
                   risk_share=TR.FIXED_RISK_SHARE,
                   exit_policy=SIT_R_EXIT_POLICY,
                   noise_mult=SIT_R_NOISE_MULT,
                   min_stop_bp=SIT_R_MIN_STOP_BP)
        with open(os.path.join(rbk, "manifest.json.tmp"), "w",
                  encoding="utf-8") as f:
            json.dump(srm, f, ensure_ascii=False, indent=1)
        os.replace(os.path.join(rbk, "manifest.json.tmp"),
                   os.path.join(rbk, "manifest.json"))
        for arm, _ in ARMS:
            situational_arm(rbk, arm, models_b, x, mats, syms,
                            rows_m, j_last, grid, nov_lo, nov_hi,
                            book_root, log_, beta_row=beta_row,
                            names=names, train_seq=seq_b)
        rebuild_accounts(rbk, None, slots=SIT_SLOTS)
        # Книга низкого RR (решение владельца 2026-08-22): вход при
        # обещанном отношении НЕ ВЫШЕ потолка. Правило — потолок в
        # манифесте; его смена отставляет книгу, как любая смена
        # правил. Сделки дизъюнктны с торгуемой по построению
        # (rr ≤ 1.5 против rr ≥ 2) — двойного счёта в лиге нет.
        lo = MODEL_DIR + BK.suffix("sit_lo")
        fresh_sit_on_rules_change(lo, log_, rules={
            "max_rr": SIT_LO_MAX_RR})
        os.makedirs(lo, exist_ok=True)
        slm = dict(sm, slots=SIT_LO_SLOTS, min_rr=0.0,
                   max_rr=SIT_LO_MAX_RR)
        with open(os.path.join(lo, "manifest.json.tmp"), "w",
                  encoding="utf-8") as f:
            json.dump(slm, f, ensure_ascii=False, indent=1)
        os.replace(os.path.join(lo, "manifest.json.tmp"),
                   os.path.join(lo, "manifest.json"))
        for arm, _ in ARMS:
            situational_arm(lo, arm, models_b, x, mats, syms,
                            rows_m, j_last, grid, nov_lo, nov_hi,
                            book_root, log_, beta_row=beta_row,
                            names=names, train_seq=seq_b)
        rebuild_accounts(lo, None, slots=SIT_LO_SLOTS)
        # Книги кандидатов фабрики. Та же машинерия, что у сестринских
        # книг: свой каталог, свой манифест, своя касса; различается
        # ровно правило, объявленное реестром испытаний.
        #
        # Ошибка ОДНОЙ книги не роняет остальные и не молчит: пул
        # растёт сам собой, и сломанный кандидат не вправе останавливать
        # ни ядро, ни соседей.
        for b in cands:
            try:
                cand_book(b, sm, models_b, x, mats, syms, rows_sit,
                          j_last, grid, nov_lo, nov_hi, book_root,
                          log_, beta_row=beta_row, names=names,
                          train_seq=seq_b)
            except Exception as e:                        # noqa: BLE001
                log_(f"книга кандидата {b.get('key')} не сведена: "
                     f"{type(e).__name__}: {e}")
    except Exception as e:                                # noqa: BLE001
        log_(f"ситуационная книга не сведена: {type(e).__name__}: {e}")

    return out


def cycle(sum_dir, log_, book_root=SM.BOOK_ROOT):
    t0 = time.time()
    # Из чего складывается запаздывание входа. Владелец увидел шесть
    # минут между закрытием часа и выбором и спросил, почему нельзя
    # сразу; ответить на это можно только замером по шагам — общее
    # время цикла не различает сведение часа, обучение и работу с
    # книгами, а лечится каждый из них по-своему. Секунды по шагам
    # едут в манифест: отчёт обязан описывать тот прогон, который
    # породил файл.
    steps = {}

    def step(name, since):
        steps[name] = round(time.time() - since, 1)
        return time.time()

    ts = t0
    if book_root and os.path.isdir(os.path.join(book_root, "book")):
        n_new = SM.run(book_root, sum_dir, None, log_)
    else:
        n_new = 0
        log_("сырой записи здесь нет — работаю по готовым сводкам")
    ts = step("сведение часа", ts)
    mats, syms, grid = load_matrices(sum_dir)
    if mats is None:
        log_("сводок ещё нет — цикл пропущен")
        write_outcome("сводок ещё нет")
        return False
    x, names, targets, elig = assemble(mats)
    ts = step("матрица", ts)
    per_hour = elig.sum(axis=0)
    n_sections = int((per_hour >= FB.MIN_SECTION).sum())
    log_(f"матрица: {len(syms)} символов × {len(grid)} часов, "
         f"сечений с ≥{FB.MIN_SECTION} именами: {n_sections}, "
         f"признаков {len(names)}")
    # Часов годной истории НА МОНЕТУ — второй счётчик ожидания,
    # независимый от числа сечений: бете нужен именно он.
    hist_h = float(np.median(elig.sum(axis=1))) if elig.size else 0
    write_readiness(syms, grid, per_hour, n_sections, len(names),
                    hist_h, log_)
    if PROBE:
        log_(f"ПРОБНЫЙ ПРОГОН: сечений {n_sections}, порог понижен до "
             f"{PROBE_MIN_SECTIONS}. Проверяется, что конвейер работает "
             f"целиком, а НЕ качество модели: на таком числе сечений "
             f"числа — шум, и опираться на них нельзя ни в какую "
             f"сторону. Артефакты идут в {MODEL_DIR} и помечены probe.")
    floor = (PROBE_MIN_SECTIONS if PROBE
             else PRETEST_MIN_SECTIONS if PRETEST
             else MIN_TRAIN_SECTIONS)
    if n_sections < floor:
        log_(f"сечений {n_sections} из {MIN_TRAIN_SECTIONS} — учиться "
             f"рано, запись копится (осталось "
             f"~{MIN_TRAIN_SECTIONS - n_sections} ч)")
        write_outcome("мало сечений", last_hour=grid[-1],
                      sections=n_sections,
                      need=MIN_TRAIN_SECTIONS, hours_per_symbol=int(hist_h),
                      beta_min_hours=FB.BETA_MIN)
        return False

    # Данные, нужные шагу книг — и раннему, и запасному.
    at = datetime.now(timezone.utc).strftime("%m-%d %H:%M")
    si = {s: i for i, s in enumerate(syms)}
    j_last = max((jj for jj in range(len(grid))
                  if elig[:, jj].sum() >= FB.MIN_SECTION), default=None)
    # Не-крипто не торгуется (решение владельца, A1 и 2026-08-07). Из
    # ОБУЧЕНИЯ имена не выдёргиваются: запись по ним останавливается, и
    # ряды уходят из матриц сами. Сечение общее для всех книг.
    rows_m = (tradable_rows(np.flatnonzero(elig[:, j_last]), syms)
              if j_last is not None else [])

    # ПОРЯДОК ЦИКЛА (правка по SCRTUSDT): книги — разбор, выборы и
    # лист сканера — идут ДО обучения, на весах ПРОШЛОГО часа. Цена
    # циклового выхода — закрытие часа, а исполняет его живой
    # исполнитель в момент записи; пока перед шагом книг стояли
    # обучение (~17 мин) и канарейка (~4 мин), живая сделка оплачивала
    # зазор ходом цены (SCRT: −3.2 % живьём при −0.11 % бумаги).
    # Свежесть весов на один час не стоит ничего — М2: сутки против
    # месяца переобучения дают +0.000…+0.004 IC. Ранний шаг требует
    # ПОЛНОГО набора совместимых весов; иначе (первый запуск, смена
    # признаков или версии) книги идут после обучения, как раньше.
    # Побочное следствие названо, а не спрятано: кричащая канарейка
    # больше не замораживает книги — она про СВЕЖЕЕ обучение, а книги
    # считаются прошлыми весами, прошедшими свою канарейку; выход —
    # обязанность перед открытой позицией (урок X2).
    booked = None
    nov_lo = nov_hi = None
    prev_models, prev_seq, prev_used = load_prev_models(names)
    if prev_models is not None:
        ts = time.time()
        nov_lo, nov_hi = novelty_bounds(x, elig)
        try:
            booked = run_books(
                prev_models, prev_seq, prev_used, x=x, mats=mats,
                syms=syms, targets=targets, elig=elig, grid=grid,
                si=si, j_last=j_last, rows_m=rows_m, nov_lo=nov_lo,
                nov_hi=nov_hi, names=names, book_root=book_root,
                log_=log_, n_sections=n_sections)
        except Exception as e:                            # noqa: BLE001
            # Ранний шаг не вправе ронять цикл: упавшие книги пойдут
            # запасным путём после обучения — повтор безопасен, дубли
            # выборов и разборов снимаются при записи.
            log_(f"ранний шаг книг упал: {type(e).__name__}: {e} — "
                 f"книги пойдут после обучения")
            booked = None
        ts = step("книги", ts)

    # Две меры, а не одна. `score_preds` оценивает сохранённые векторы
    # по мере закрытия форварда — это и есть живой IC при переобучении
    # каждый час. `eval_previous` берёт прежние веса на всём окне после
    # обучения — она осмысленна при суточном переобучении. Порядок
    # важен: сохранённые считаются первыми, потому что именно они
    # описывают ранжирование, по которому шли сделки.
    ts = time.time()
    ic_rows = score_preds(targets, elig, grid, syms, log_)
    ts = step("оценка", ts)

    # КАДЕНЦИЯ ОБУЧЕНИЯ. Дальше идут дорогие шаги — прежние веса на
    # всём окне, канарейка многими зёрнами и само обучение, — и по
    # замеру `cycle_health` они и есть весь перерасход часа (3990 + 1142
    # из 5207 с). Книги, разбор и лист сканера к этому моменту уже
    # записаны ранним шагом, живой IC сечения — тоже (`score_preds`
    # сам дописывает историю), поэтому часовой контур от пропуска
    # обучения не теряет ничего, кроме свежести весов, которая по M2
    # стоит +0.000…+0.004 IC.
    #
    # Пропуск возможен ТОЛЬКО когда ранний шаг книг прошёл: если он
    # отказал (первый запуск, смена признаков или версии), веса нужны
    # прямо сейчас — иначе книга этого часа не будет посчитана ничем.
    due, why = train_due(prev_used, time.time())
    if not due and booked is not None:
        cyc = round(time.time() - t0, 1)
        log_(f"обучение пропущено по каденции: {why}; цикл {cyc:.0f} с ("
             + ", ".join(f"{k} {v:.0f} с" for k, v in steps.items()) + ")")
        write_outcome("часовой цикл без обучения", last_hour=grid[-1],
                      sections=n_sections, train_due=False,
                      train_why=why, steps_sec=steps, cycle_sec=cyc,
                      woke_after_hour_sec=round(t0 % 3600, 1))
        log_cycle({"kind": "books", "seq": prev_seq,
                   "hour": grid[-1],
                   "at": datetime.now(timezone.utc)
                   .strftime("%m-%d %H:%M"),
                   "sections": n_sections, "symbols": len(syms),
                   "train_why": why,
                   "steps_sec": steps, "cycle_sec": cyc}, log_)
        return False
    if due and prev_used:
        log_(f"переобучаю: {why}")

    ic_rows += eval_previous(x, targets, elig, grid, log_)

    # Проверка на течь и наличие главной цели — РАЗНЫЕ вопросы, и
    # слив их в один стоил ровно того, ради чего проба и делалась:
    # конвейер отказывался проверяться именно там, где его только что
    # переписали. Канарейка считается на любой годной цели, а нехватка
    # `fwd_4h` — отдельный гейт ниже.
    cname = canary_target(targets, elig)
    spread, nseed, cvals = 0.0, 1, []
    if not cname:
        med = float("nan")
    else:
        # Зёрен несколько у ОБЕИХ рук. Прежде многозёренная канарейка
        # стояла только у предпросмотра, а боевая рука судила по одному
        # броску — при том что довод в пользу нескольких записан прямо
        # в `canary_many` и от руки не зависит вовсе: он про размер
        # выборки. А первое обучение боевых рук случается ровно на
        # пороге в 48 сечений, то есть в том самом малом режиме.
        #
        # Стоило это ложного крика 5 августа: одно зерно на `mfe_1h`
        # дало −0.0719 при пороге 0.05, веса не обновились, и отличить
        # течь от шума было нечем.
        med, spread, nseed, cvals = canary_many(
            x, targets, elig, grid, SEED0 + len(grid), log_, cname,
            CANARY_SEEDS)
    # Поля канарейки собираются ОДИН раз и кладутся всюду одинаково.
    # Прежде они перечислялись в каждой ветке своим списком, и ветка
    # «нет главной цели» — та единственная, что реально сработала на
    # боевых руках, — не несла ни числа зёрен, ни их списка. То есть
    # диагностика, ради которой всё и добавлялось, отсутствовала ровно
    # там, где понадобилась: по артефакту нельзя было отличить пять
    # зёрен от одного.
    can = {"canary_ic": round(float(med), 4) if np.isfinite(med) else None,
           "canary_target": cname, "canary_stop": CANARY_STOP,
           "canary_spread": round(spread, 4), "canary_seeds": nseed,
           "canary_vals": cvals}
    ts = step("канарейка", ts)
    verdict = canary_verdict(med)
    if verdict == "не считалась":
        log_(f"канарейка не считается: ни одна цель не набирает строк. "
             f"Веса НЕ обновляются: непосчитанная проверка не является "
             f"пройденной")
        write_outcome("канарейка не считалась", last_hour=grid[-1],
                      sections=n_sections,
                      hours_per_symbol=int(hist_h),
                      beta_min_hours=FB.BETA_MIN, **can)
        return False
    if verdict == "кричит":
        log_(f"КАНАРЕЙКА КРИЧИТ: |IC| {abs(med):.3f} > {CANARY_STOP} — "
             f"похоже на течь конвейера, веса НЕ обновляются")
        write_outcome("канарейка кричит", sections=n_sections, **can)
        return False

    # Главная цель отдельным гейтом. Без `fwd_4h` не будет ни выбора
    # монет (ему нужны fwd_4h и mae_4h), ни живого IC, ни счетов —
    # то есть боевые веса вели бы контур, который ничего не выбирает.
    # Проба этот гейт проходит НАСКВОЗЬ: её дело — показать, что
    # обучение работает, а не притворяться боевой.
    main_ok = int((elig & np.isfinite(
        targets["fwd_4h"])).sum()) >= MIN_TARGET_ROWS
    if not main_ok:
        msg = (f"главной цели fwd_4h нет: ей нужна бета, бете — "
               f"{FB.BETA_MIN} ч годной истории на монету, есть около "
               f"{int(hist_h)}")
        if not (PROBE or PRETEST):
            log_(msg + ". Веса НЕ обновляются: выбирать монеты не на чем")
            write_outcome("нет главной цели", last_hour=grid[-1],
                          sections=n_sections,
                          hours_per_symbol=int(hist_h),
                          beta_min_hours=FB.BETA_MIN, **can)
            return False
        log_(msg + ". Проба идёт дальше: обучатся цели, которые есть, "
                   "выбора монет не будет")

    os.makedirs(MODEL_DIR, exist_ok=True)
    ts = time.time()
    if nov_lo is None:
        nov_lo, nov_hi = novelty_bounds(x, elig)
    # Номер обучения — просьба владельца: у каждой сделки должно быть
    # видно, КАКИМ обучением она открыта. Возраст весов для этого не
    # годится (он меняется каждую минуту), час обучения — коряво в
    # показе; счётчик растёт на единицу за каждый успешный цикл и
    # штампуется в веса, манифест, лист сечения и каждую запись
    # выбора. Живёт в манифесте: своя копия в отдельном файле однажды
    # разошлась бы с ним.
    train_seq = 1
    try:
        with open(os.path.join(MODEL_DIR, "manifest.json"),
                  encoding="utf-8") as f:
            train_seq = int((json.load(f) or {}).get("train_seq")
                            or 0) + 1
    except (OSError, ValueError):
        pass
    imp_all = {}
    models = {}
    breach = {}
    for ai, (arm, fit_fn) in enumerate(ARMS):
        for ti, tgt in enumerate(TARGETS):
            col, tau = QUANT_TARGETS.get(tgt, (tgt, None))
            xs, ys, _ = flatten(x, targets[col], elig)
            if len(ys) < MIN_TARGET_ROWS:
                log_(f"{arm}/{tgt}: строк {len(ys)} — пропуск")
                continue
            t1 = time.time()
            kw = {} if tau is None else {"tau": tau}
            model = fit_fn(xs, ys,
                           seed=SEED0 + 10_000 * ai + 100 * ti + len(grid),
                           **kw)
            models[(arm, tgt)] = model
            tot = model.importance.sum() or 1.0
            imp = {names[j]: round(float(model.importance[j] / tot), 4)
                   for j in np.argsort(model.importance)[::-1][:10]}
            imp_all.setdefault(arm, {})[tgt] = imp
            blob = {"model": model, "features": names, "target": tgt,
                    "arm": arm, "version": MODEL_VERSION,
                    "target_col": col, "tau": tau,
                    "train_seq": train_seq,
                    "trained_upto": grid[-1], "rows": len(ys)}
            p = os.path.join(MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            with open(p + ".tmp", "wb") as f:
                pickle.dump(blob, f)
            os.replace(p + ".tmp", p)
            extra = ""
            if tau is not None:
                # Доля захода за уровень: величина, ради которой
                # квантильная потеря и заведена, — сколько строк
                # оказалось ДАЛЬШЕ предсказанного стопа. Должна выйти
                # около `tau`; заметно ниже — модель подогналась под
                # обучающие часы. Число внутривыборочное и вердиктом
                # не является: честную долю даст сама книга своими
                # сделками, здесь проверяется, что потеря делает то,
                # что обещает.
                pr = model.predict(xs)
                sh = float(np.mean(ys < pr) if tau < 0.5
                           else np.mean(ys > pr))
                breach.setdefault(arm, {})[tgt] = round(sh, 3)
                extra = (f"; заход за уровень {sh:.3f} "
                         f"при объявленных {min(tau, 1 - tau):.2f}")
            log_(f"{arm}/{tgt}: обучена на {len(ys):,} строках за "
                 f"{time.time() - t1:.0f} с; топ: "
                 + ", ".join(f"{k} {v}" for k, v in list(imp.items())[:3])
                 + extra)

    ts = step("обучение", ts)
    mp = os.path.join(MODEL_DIR, "manifest.json")
    prev_man = None
    try:
        with open(mp, encoding="utf-8") as f:
            prev_man = json.load(f)
    except (OSError, ValueError):
        pass

    man = {"version": MODEL_VERSION, "trained_upto": grid[-1],
           "train_seq": train_seq,
           # Пометка обязана лежать В артефакте, а не в имени каталога:
           # каталог переименуют или скопируют, а манифест поедет с
           # весами. Прогон F2 однажды уже подменил артефакт настоящего
           # прогона смоуковым — по содержимому они были неотличимы.
           "probe": PROBE,
           "pretest": PRETEST,
           "hedge": HEDGE_PRETEST if PRETEST else HEDGE_LIVE,
           "min_sections": (PROBE_MIN_SECTIONS if PROBE
                            else MIN_TRAIN_SECTIONS),
           "trained_at": datetime.now(timezone.utc).isoformat(
               timespec="seconds"),
           "symbols": len(syms), "hours": len(grid),
           "sections": n_sections, "targets": sorted(imp_all),
           # Полный список объявленных целей и порог канарейки — В
           # артефакт: отчёт держал их своими константами и разошёлся с
           # прогоном в тот же вечер (девять целей против четырёх, порог
           # 0.05 против 0.01).
           "rank_target": rank_key_for(TR.HOLD_H),
           "entry_floor_bp": H4_FLOOR_BP,
           "targets_all": list(TARGETS),
           # Уровень стопа: чем он объявлен и что вышло на обучающих
           # часах. Правило заявки обязано лежать в артефакте рядом с
           # весами, которыми она поставлена, — иначе через месяц по
           # сделке нельзя будет сказать, каким правилом её стопили.
           "stop_tau": STOP_TAU,
           "stop_targets": list(QUANT_TARGETS),
           "stop_breach_insample": breach,
           **can,
           "new_summary_hours": n_new,
           "importance": imp_all,
           # Диапазоны новизны — в артефакт: определение обязано жить
           # с прогоном, который им пользовался, а не в исходниках.
           "novelty_pct": [0.5, 99.5],
           "novelty_bounds": {
               names[j]: [None if not np.isfinite(nov_lo[j])
                          else float(f"{nov_lo[j]:.6g}"),
                          None if not np.isfinite(nov_hi[j])
                          else float(f"{nov_hi[j]:.6g}")]
               for j in range(len(names))},
           # Секунды по шагам и то, НАСКОЛЬКО ПОЗДНО цикл проснулся
           # после закрытия часа: вместе они и есть запаздывание
           # входа, которое таблица сделок показывает полем `lag`.
           "steps_sec": steps,
           "woke_after_hour_sec": round(t0 % 3600, 1),
           "cycle_sec": round(time.time() - t0, 1)}
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    os.replace(mp + ".tmp", mp)

    # Запасной путь: ранние книги не шли (первый запуск, смена
    # признаков или версии, падение раннего шага) — книги идут здесь,
    # на только что обученных весах, как было до правки порядка.
    if booked is None:
        ts = time.time()
        booked = run_books(
            models, train_seq, man, x=x, mats=mats, syms=syms,
            targets=targets, elig=elig, grid=grid, si=si,
            j_last=j_last, rows_m=rows_m, nov_lo=nov_lo,
            nov_hi=nov_hi, names=names, book_root=book_root,
            log_=log_, n_sections=n_sections)
        ts = step("книги", ts)

    # Мысли — по СВЕЖЕМУ манифесту и живому IC: выборы и разборы к
    # этому моменту уже записаны, и записаны номером тех весов,
    # которыми посчитаны (у ранних книг — прошлым).
    all_lines = []
    for arm, _ in ARMS:
        got = booked["arms"].get(arm) or {}
        review, picks = got.get("review"), got.get("picks")
        man_arm = dict(man, importance=imp_all.get(arm) or {})
        prev_arm = None
        if prev_man:
            pi = prev_man.get("importance") or {}
            prev_arm = dict(prev_man,
                            importance=pi.get(arm) if arm in pi else pi)
        ic_arm = [r for r in ic_rows or [] if r.get("arm") == arm]
        lines = think(prev_arm, man_arm, ic_arm, picks)
        if review:
            hits = sum(1 for r in review
                       if (r["got"] > 0) == (r["side"] == "long"))
            lines.insert(0, f"разбор прошлых выборов ({len(review)} имён, "
                            f"угадан знак у {hits}): " + "; ".join(
                                f"{r['sym'].replace('USDT','')} "
                                f"{'лонг' if r['side'] == 'long' else 'шорт'}: "
                                f"ждал {pct(r['expected'])}, вышло "
                                f"{pct(r['got'])}" for r in review))
        all_lines += [f"[{'деревья' if arm == 'gbm' else 'сеть'}] {t}"
                      for t in lines]
    all_lines += booked.get("acct_lines") or []
    # Манифест дописывается итогом — одно место, где хранится время
    # цикла. Шаг книг замерен у своего вызова: у раннего пути он уже
    # лежал в steps при первой записи манифеста.
    man["steps_sec"] = steps
    man["cycle_sec"] = round(time.time() - t0, 1)
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    os.replace(mp + ".tmp", mp)
    log_("запаздывание входа: проснулся через "
         f"{man['woke_after_hour_sec']:.0f} с после закрытия часа, "
         f"цикл {man['cycle_sec']:.0f} с ("
         + ", ".join(f"{k} {v:.0f} с" for k, v in steps.items()) + ")")
    # Строка на обучение: чем модель РАСПОЛАГАЛА в этот раз. Манифест
    # хранит только текущее состояние и переписывается каждый час, то
    # есть ряд «сколько сечений видело обучение» не восстановим ничем
    # — задним числом его взять неоткуда, а без него на вопрос «умнеет
    # ли модель» отвечать нечем, кроме самого IC. Одна строка в час.
    log_cycle({"kind": "train",
               "seq": train_seq, "hour": grid[-1], "at": at,
               "sections": n_sections, "symbols": len(syms),
               "canary_ic": man["canary_ic"],
               "canary_target": cname,
               "hedge": man["hedge"],
               # Секунды ПО ШАГАМ — в журнал, а не только в манифест:
               # манифест переписывается каждый час, то есть ряда «куда
               # уходило время» задним числом взять неоткуда, а именно
               # он отвечает, чем чинить переполнение цикла. Тот же
               # довод, по которому в журнал попали сечения.
               "steps_sec": steps,
               "cycle_sec": man["cycle_sec"]}, log_)

    lines = all_lines
    with open(os.path.join(MODEL_DIR, "thoughts.jsonl"), "a",
              encoding="utf-8") as f:
        for t in lines:
            f.write(json.dumps({"at": at, "text": t},
                               ensure_ascii=False) + "\n")
    for t in lines:
        log_(f"мысль: {t}")
    log_(f"цикл закончен за {man['cycle_sec']:.0f} с, веса v{MODEL_VERSION} "
         f"до часа {grid[-1]}")
    write_outcome("обучилась", last_hour=grid[-1],
                  sections=n_sections,
                  hours_per_symbol=int(hist_h),
                  beta_min_hours=FB.BETA_MIN,
                  canary_ic=man["canary_ic"], canary_target=cname,
                  canary_stop=CANARY_STOP,
                  trained=sorted(f"{a}/{t}" for a, t in models),
                  picks=bool(all_lines), cycle_sec=man["cycle_sec"])
    return True


def stale_summary():
    """Отстал ли последний прогон от закрывшегося часа.

    Сравнивается час, на котором работал цикл (`last_hour` в исходе), с
    последним ЗАКРЫВШИМСЯ часом. Если цикл видел более ранний, значит
    сводка на момент его прохода ещё не была дописана.
    """
    try:
        with open(os.path.join(MODEL_DIR, "last_run.json"),
                  encoding="utf-8") as f:
            lh = json.load(f).get("last_hour")
    except (OSError, ValueError):
        return False
    if not lh:
        return False
    want = datetime.fromtimestamp(time.time() - 3600, timezone.utc)\
        .strftime("%Y-%m-%d-%H")
    return lh < want


def demo():
    """Полный вывод цикла на синтетике — ответ на «что я буду видеть».

    Проба на живых данных показать этого не может и не сможет ещё
    несколько суток: выбор монет требует цели `fwd_4h`, той нужна бета,
    бете — `FB.BETA_MIN` часов записи. Ждать четверо суток, чтобы
    впервые увидеть форму вывода, незачем: форма от данных не зависит.

    Поэтому здесь берутся синтетические сводки с ЗАЛОЖЕННЫМ сигналом
    (дельта ленты предсказывает следующий час) и прогоняются ДВА цикла
    подряд — второй нужен, чтобы появились живой IC, разбор прошлого
    выбора фактом и бумажные счета: разбирать можно только прошлый
    выбор.

    Данные фальшивые целиком. Числа отсюда не значат ничего о рынке —
    значат они ровно одно: конвейер производит то, что обещал.
    """
    global MODEL_DIR, PROBE
    import shutil
    import tempfile

    import synth
    MODEL_DIR = os.path.join(OUT, "model_demo")
    shutil.rmtree(MODEL_DIR, ignore_errors=True)
    PROBE = False
    log("ПОКАЗ НА СИНТЕТИКЕ: данные выдуманы, сигнал заложен руками. "
        "Смысл — форма вывода, а не измерение.")
    sd = tempfile.mkdtemp(prefix="s8demo-")
    try:
        synth.write_summaries(sd, D=260)
        log("цикл 1 из 2 (первое обучение)")
        cycle(sd, log, book_root=None)
        synth.write_summaries(sd, D=300)     # те же зерно и старт
        log("цикл 2 из 2 (появятся живой IC, разбор и счета)")
        cycle(sd, log, book_root=None)
    finally:
        shutil.rmtree(sd, ignore_errors=True)
    try:
        import probe_report
        path, _ = probe_report.write(MODEL_DIR,
                                     os.path.join(OUT, "S8-demo-report.md"))
        log(f"отчёт показа: {path}")
    except Exception as e:                                # noqa: BLE001
        log(f"отчёт показа не собрался: {type(e).__name__}: {e}")


def main():
    global MODEL_DIR, PROBE, PRETEST
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--summary-dir", default=SM.OUT)
    ap.add_argument("--probe", action="store_true",
                    help="пробный прогон конвейера на накопленном: свой "
                         "каталог, свои артефакты, порог сечений "
                         "понижен. Числа НЕ являются измерением.")
    ap.add_argument("--demo", action="store_true",
                    help="показ полного вывода на СИНТЕТИЧЕСКИХ данных "
                         "с заложенным сигналом: выбор монет, живой IC, "
                         "разбор фактом, бумажные счета. Отвечает на "
                         "вопрос «что я буду видеть», измерением не "
                         "является ни в какой части.")
    ap.add_argument("--pretest", action="store_true",
                    help="предпросмотр: та же модель на том, что уже "
                         "накоплено, своим циклом и в свой каталог. "
                         "Показывает работу обучения сейчас; вердикт по "
                         "нему не выносится никогда.")
    a = ap.parse_args()
    if a.demo:
        return demo()
    if a.pretest:
        # Каталог свой — боевые веса, счета и выборы не трогаются, и
        # живой контур не может поехать на модели, обученной на неделе
        # данных. Порог 48 остаётся ровно тем же.
        MODEL_DIR = os.path.join(OUT, "model_pretest")
        PRETEST = True
        # Смена режима хеджа означает другую книгу. Проверяется ДО
        # первого цикла: иначе новые выборы легли бы в один счёт со
        # старыми, и кривая описывала бы книгу, которой не было.
        fresh_on_mode_change(HEDGE_PRETEST, log)
    if a.probe:
        # Порог 48 остаётся нетронутым, меняется КАТАЛОГ. Иначе
        # пробный прогон записал бы веса, счета и выборы поверх
        # боевых, и живой контур поехал бы на модели, обученной на
        # шуме, — а снаружи это выглядело бы как работающая модель.
        MODEL_DIR = os.path.join(OUT, "model_probe")
        PROBE = True
        a.once = True
    try:
        # Приём данных важнее счёта, а предпросмотр — важнее всего
        # прочего НЕ является: он уступает и сбору, и боевому циклу.
        os.nice(15 if a.pretest else 10)
    except OSError:
        pass
    while True:
        trained = False
        try:
            # Предпросмотр НЕ сводит часы сам. Сводку пишет боевой
            # цикл, и два процесса, пишущих одни файлы, однажды
            # разошлись бы посреди строки. Предпросмотр только читает
            # готовое — отсюда и гарантия «помешать не может».
            trained = bool(cycle(a.summary_dir, log,
                                 book_root=None if a.pretest
                                 else SM.BOOK_ROOT))
        except Exception as e:                            # noqa: BLE001
            # Цикл живёт сутками; одна упавшая итерация не вправе
            # убить процесс — но обязана быть видна.
            import traceback
            log(f"цикл упал: {type(e).__name__}: {e}")
            traceback.print_exc()
            # Падение — тоже исход, и оно обязано лежать в артефакте, а
            # не только в журнале. Журнал лежит на сервере, а страницу
            # смотрят снаружи: без этой записи упавший цикл выглядит
            # ровно как ещё не отработавший.
            try:
                write_outcome("цикл упал",
                              error=f"{type(e).__name__}: {e}")
            except Exception:                             # noqa: BLE001
                pass
        if a.once:
            if PROBE:
                # Отчёт пишет сама проба, а не человек следом. Отдельная
                # команда публикации забывается ровно тогда, когда
                # результат нужен: прогон был, а посмотреть на него
                # нечего — так уже вышло на первом же повторе.
                try:
                    import probe_report
                    probe_report.write(MODEL_DIR,
                                       os.path.join(OUT,
                                                    "S8-probe-report.md"))
                except Exception as e:                    # noqa: BLE001
                    log(f"отчёт о пробе не собрался: "
                        f"{type(e).__name__}: {e}")
            break
        # Час — темп ВСЕГО контура, удался цикл или нет: книги
        # закрываются каждый час, и их разбор не вправе ждать. Спящий
        # после успеха цикл уже стоил боевому контуру суток без
        # разборов — сделки висели «ждёт разбора» до случайного деплоя.
        wait = RETRY_SEC
        # Предпросмотр отдельно проверяет, СВЕЖУЮ ли сводку он видел.
        # Он её не пишет, а читает; придя раньше боевого цикла, он
        # увидит сетку без только что закрывшегося часа и отстанет на
        # час — а вместе с ним на час зависнут все сделки, которым срок
        # вышел. Ждать час в такой ситуации незачем: сводка допишется
        # через минуты.
        if a.pretest and stale_summary():
            log("сводка ещё не догнала закрывшийся час — "
                f"повтор через {STALE_RETRY_SEC // 60} мин")
            time.sleep(STALE_RETRY_SEC)
            continue
        if wait == RETRY_SEC:
            # Часовой цикл ждёт до ГРАНИЦЫ ЧАСА, а не ровно час от
            # прошлого раза. Разница видна числом: запаздывание входа
            # (`lag` в таблице сделок) равно тому, насколько поздно
            # цикл проснулся после закрытия часа. При отсчёте «час от
            # прошлого раза» смещение задаётся моментом запуска и живёт
            # вечно — на сервере оно закрепилось на пятнадцати минутах
            # просто потому, что в 15 минут был перезапуск.
            #
            # Запас нужен: час сначала надо свести. Меньше запаса —
            # цикл увидит незакрытый час и выберет по прошлому.
            margin = PRETEST_MARGIN_SEC if a.pretest else MARGIN_SEC
            wait = max(margin, 3600 - (time.time() % 3600) + margin)
        log(f"следующая попытка через {wait // 60:.0f} мин "
            f"({'переобучение по расписанию' if trained else 'обучения не было'})")
        time.sleep(wait)


if __name__ == "__main__":
    main()
