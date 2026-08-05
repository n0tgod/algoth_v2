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
pyenv.need("numpy")

import numpy as np                                        # noqa: E402

import bookfeat as FB                                      # noqa: E402
import gbm                                                 # noqa: E402
import nn                                                  # noqa: E402
import summary as SM                                       # noqa: E402
from trades import ROUND_COST_BP as TR_COST                # noqa: E402
import wf                                                  # noqa: E402

OUT = os.path.join(HERE, "out")
MODEL_DIR = os.path.join(OUT, "model")

MODEL_VERSION = 2
TARGETS = [f"{k}_{h}h" for k in ("fwd", "mfe", "mae") for h in FB.HORIZONS]
# Турнир: две руки на одних данных, объявлены до окна вердикта.
# gbm — деревья (ML), nn — сеть (AI-рука). Прогноз до запуска записан:
# на табличных признаках и неделях данных сеть скорее проиграет.
ARMS = (("gbm", gbm.fit), ("nn", nn.fit))
CYCLE_SEC = 24 * 3600             # спека §5: раз в сутки
RETRY_SEC = 3600                  # не обучился — проверить через час
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


def assemble(mats):
    """Матрицы сводки → (X, имена признаков, цели, elig, r)."""
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
    targets = FB.target_pack(mats, r, elig, beta)
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
            ics = section_ic(pred, targets[tgt], elig, cols)
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


PRETEST_CANARY_SEEDS = 5


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
        y = targets[name]
        vals.append(canary(x, y, elig, grid, seed + 1000 * k, log_,
                           name=name))
    vals = [v for v in vals if np.isfinite(v)]
    if not vals:
        return float("nan"), float("nan"), 0
    mean = float(np.mean(vals))
    spread = float(np.max(vals) - np.min(vals)) if len(vals) > 1 else 0.0
    log_(f"канарейка по {len(vals)} зёрнам: среднее {mean:+.4f}, "
         f"разброс {spread:.4f} (одиночный замер на такой выборке "
         f"вердикта не несёт)")
    return mean, spread, len(vals)


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


def canary_target(targets, elig, want="fwd_4h", need=1000):
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
    for name in [want] + [t for t in TARGETS if t != want]:
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
    hour = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d-%H")
    out = {}
    if not book_root:
        # Записи стакана нет вовсе — числа не будет, и это правильно:
        # пропуск обязан остаться пропуском.
        return out
    for sym in syms:
        d = os.path.join(book_root, "book", sym)
        best = None
        try:
            for r in SM.read_hour(d, hour):
                bid, ask = r.get("bid"), r.get("ask")
                t = r.get("t") or 0.0
                if not bid or not ask:
                    continue
                if best is None or t > best[1]:
                    best = ((bid + ask) / 2.0, t)
        except OSError:
            best = None
        if best is not None:
            out[sym] = best
    if log_ is not None and len(out) < len(syms):
        log_(f"живая цена входа найдена у {len(out)} имён из {len(syms)}")
    return out


def cycle(sum_dir, log_, book_root=SM.BOOK_ROOT):
    t0 = time.time()
    if book_root and os.path.isdir(os.path.join(book_root, "book")):
        n_new = SM.run(book_root, sum_dir, None, log_)
    else:
        n_new = 0
        log_("сырой записи здесь нет — работаю по готовым сводкам")
    mats, syms, grid = load_matrices(sum_dir)
    if mats is None:
        log_("сводок ещё нет — цикл пропущен")
        write_outcome("сводок ещё нет")
        return False
    x, names, targets, elig = assemble(mats)
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

    # Две меры, а не одна. `score_preds` оценивает сохранённые векторы
    # по мере закрытия форварда — это и есть живой IC при переобучении
    # каждый час. `eval_previous` берёт прежние веса на всём окне после
    # обучения — она осмысленна при суточном переобучении. Порядок
    # важен: сохранённые считаются первыми, потому что именно они
    # описывают ранжирование, по которому шли сделки.
    ic_rows = score_preds(targets, elig, grid, syms, log_)
    ic_rows += eval_previous(x, targets, elig, grid, log_)

    # Проверка на течь и наличие главной цели — РАЗНЫЕ вопросы, и
    # слив их в один стоил ровно того, ради чего проба и делалась:
    # конвейер отказывался проверяться именно там, где его только что
    # переписали. Канарейка считается на любой годной цели, а нехватка
    # `fwd_4h` — отдельный гейт ниже.
    cname = canary_target(targets, elig)
    spread, nseed = 0.0, 1
    if not cname:
        med = float("nan")
    elif PRETEST:
        # Предпросмотр живёт на малой выборке, где одна канарейка
        # кричит от собственного шума. Зёрен несколько, вердикт по
        # среднему — иначе предпросмотр молча стоял бы навсегда.
        med, spread, nseed = canary_many(
            x, targets, elig, grid, SEED0 + len(grid), log_, cname,
            PRETEST_CANARY_SEEDS)
    else:
        med = canary(x, targets[cname], elig, grid, SEED0 + len(grid),
                     log_, name=cname)
    verdict = canary_verdict(med)
    if verdict == "не считалась":
        log_(f"канарейка не считается: ни одна цель не набирает строк. "
             f"Веса НЕ обновляются: непосчитанная проверка не является "
             f"пройденной")
        write_outcome("канарейка не считалась", last_hour=grid[-1],
                      sections=n_sections,
                      hours_per_symbol=int(hist_h),
                      beta_min_hours=FB.BETA_MIN)
        return False
    if verdict == "кричит":
        log_(f"КАНАРЕЙКА КРИЧИТ: |IC| {abs(med):.3f} > {CANARY_STOP} — "
             f"похоже на течь конвейера, веса НЕ обновляются")
        write_outcome("канарейка кричит", sections=n_sections,
                      canary_ic=round(float(med), 4),
                      canary_target=cname, canary_stop=CANARY_STOP,
                      canary_spread=round(spread, 4), canary_seeds=nseed)
        return False

    # Главная цель отдельным гейтом. Без `fwd_4h` не будет ни выбора
    # монет (ему нужны fwd_4h и mae_4h), ни живого IC, ни счетов —
    # то есть боевые веса вели бы контур, который ничего не выбирает.
    # Проба этот гейт проходит НАСКВОЗЬ: её дело — показать, что
    # обучение работает, а не притворяться боевой.
    main_ok = int((elig & np.isfinite(targets["fwd_4h"])).sum()) >= 1000
    if not main_ok:
        msg = (f"главной цели fwd_4h нет: ей нужна бета, бете — "
               f"{FB.BETA_MIN} ч годной истории на монету, есть около "
               f"{int(hist_h)}")
        if not (PROBE or PRETEST):
            log_(msg + ". Веса НЕ обновляются: выбирать монеты не на чем")
            write_outcome("нет главной цели", last_hour=grid[-1],
                          sections=n_sections,
                          hours_per_symbol=int(hist_h),
                          beta_min_hours=FB.BETA_MIN,
                          canary_ic=round(float(med), 4),
                          canary_target=cname, canary_stop=CANARY_STOP)
            return False
        log_(msg + ". Проба идёт дальше: обучатся цели, которые есть, "
                   "выбора монет не будет")

    os.makedirs(MODEL_DIR, exist_ok=True)
    nov_lo, nov_hi = novelty_bounds(x, elig)
    imp_all = {}
    models = {}
    for ai, (arm, fit_fn) in enumerate(ARMS):
        for ti, tgt in enumerate(TARGETS):
            xs, ys, _ = flatten(x, targets[tgt], elig)
            if len(ys) < 1000:
                log_(f"{arm}/{tgt}: строк {len(ys)} — пропуск")
                continue
            t1 = time.time()
            model = fit_fn(xs, ys,
                           seed=SEED0 + 10_000 * ai + 100 * ti + len(grid))
            models[(arm, tgt)] = model
            tot = model.importance.sum() or 1.0
            imp = {names[j]: round(float(model.importance[j] / tot), 4)
                   for j in np.argsort(model.importance)[::-1][:10]}
            imp_all.setdefault(arm, {})[tgt] = imp
            blob = {"model": model, "features": names, "target": tgt,
                    "arm": arm, "version": MODEL_VERSION,
                    "trained_upto": grid[-1], "rows": len(ys)}
            p = os.path.join(MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            with open(p + ".tmp", "wb") as f:
                pickle.dump(blob, f)
            os.replace(p + ".tmp", p)
            log_(f"{arm}/{tgt}: обучена на {len(ys):,} строках за "
                 f"{time.time() - t1:.0f} с; топ: "
                 + ", ".join(f"{k} {v}" for k, v in list(imp.items())[:3]))

    mp = os.path.join(MODEL_DIR, "manifest.json")
    prev_man = None
    try:
        with open(mp, encoding="utf-8") as f:
            prev_man = json.load(f)
    except (OSError, ValueError):
        pass

    man = {"version": MODEL_VERSION, "trained_upto": grid[-1],
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
           "targets_all": list(TARGETS),
           "canary_stop": CANARY_STOP,
           "canary_target": cname,
           "canary_spread": round(spread, 4),
           "canary_seeds": nseed,
           "canary_ic": round(med, 4) if np.isfinite(med) else None,
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
           "cycle_sec": round(time.time() - t0, 1)}
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    os.replace(mp + ".tmp", mp)

    # Выбор -> ожидание -> факт, по каждой руке турнира отдельно:
    # сводка по смеси рук осмысленна на вид и бессмысленна по сути.
    ppath = os.path.join(MODEL_DIR, "picks.jsonl")
    # Разбираются ВСЕ неразобранные выборы, а не только последний.
    #
    # Прежде хранился один выбор на руку — предыдущий, — и разбор шёл
    # только по нему. При цикле раз в час и горизонте цели в четыре часа
    # форвард предыдущего выбора ещё не закрыт, поэтому разбор выходил
    # пустым; а к следующему циклу этот выбор уже не был «предыдущим» и
    # не разбирался НИКОГДА. Замер на живом предпросмотре: 48 сделок,
    # закрытых ноль, шесть «без исхода» на руку. Сделки не закрывались
    # бы вовсе — при исправном на вид цикле.
    all_picks = []
    try:
        with open(ppath, encoding="utf-8") as f:
            for line in f:
                try:
                    all_picks.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    seen_picks = {((p.get("arm") or "gbm"), p.get("hour"))
                  for p in all_picks}
    reviewed = set()
    try:
        with open(os.path.join(MODEL_DIR, "review.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                try:
                    rr = json.loads(line)
                    reviewed.add((rr.get("arm") or "gbm", rr.get("hour")))
                except ValueError:
                    continue
    except OSError:
        pass

    at = datetime.now(timezone.utc).strftime("%m-%d %H:%M")
    all_lines = []
    si = {s: i for i, s in enumerate(syms)}
    j_last = max((jj for jj in range(len(grid))
                  if elig[:, jj].sum() >= FB.MIN_SECTION), default=None)
    for arm, _ in ARMS:
        # Последний ЗАПИСАННЫЙ разбор, а не последняя итерация цикла:
        # у свежего выбора форвард ещё не закрыт, разбор выходит пустым,
        # и мысли молчали бы о разборе, который на деле состоялся.
        review = None
        acc = pnl = None
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
                    got = targets["fwd_4h"][i, j]
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
                # В разбор кладётся только ФАКТ: движение цены и то же
                # движение за вычетом круга издержек. Денег здесь нет —
                # они зависят от размера позиции, а размер задаётся
                # счётом, который считается по ВСЕЙ истории сразу
                # (`trades.account`). Класть сюда деньги значило бы
                # завести второе определение размера позиции.
                for r in rows_rv:
                    r["net"] = round((1 if r["side"] == "long" else -1)
                                     * r["got"] - ROUND_COST_BP, 1)
                with open(os.path.join(MODEL_DIR, "review.jsonl"), "a",
                          encoding="utf-8") as f:
                    f.write(json.dumps(
                        {"arm": arm, "hour": lp["hour"],
                         "cost_bp": ROUND_COST_BP, "rows": rows_rv},
                        ensure_ascii=False) + "\n")
                review = rows_rv
        picks = None
        if (arm, "fwd_4h") in models and (arm, "mae_4h") in models \
                and j_last is not None:
            rows_m = np.flatnonzero(elig[:, j_last])
            xj = x[rows_m, j_last]
            fwd = models[(arm, "fwd_4h")].predict(xj)
            # Ход ПРОТИВ позиции у длинной и короткой ноги — разные
            # цели. `mae_4h` есть минимум цены за горизонт, `mfe_4h` —
            # максимум; обе считаются по ЦЕНЕ, а не по позиции. Значит
            # лонгу против идёт mae, а шорту — mfe. Показывать шорту
            # mae значило бы подписывать ход в его ПОЛЬЗУ словами «ход
            # против», то есть врать в самую важную колонку.
            mae = models[(arm, "mae_4h")].predict(xj)
            mfe = (models[(arm, "mfe_4h")].predict(xj)
                   if (arm, "mfe_4h") in models else None)
            o = np.argsort(fwd)
            # Весь вектор сечения — в файл, а не только шесть выбранных.
            # Через горизонт по нему посчитается живой вневыборочный IC:
            # ранговая корреляция по шести именам мерой не является, а
            # других способов её получить при часовом переобучении нет.
            save_preds(arm, grid[-1], syms, rows_m, fwd)

            def mk(i, side):
                adv = (float(mae[i]) if side == "long"
                       else (float(mfe[i]) if mfe is not None else None))
                px = float(mats["mid_close"][rows_m[i], j_last])
                d = {"sym": syms[rows_m[i]], "fwd": float(fwd[i]),
                     # Цена входа = закрытие часа сигнала. Без неё
                     # открытую сделку нечем переоценивать.
                     "px": px if np.isfinite(px) else None,
                     # Имя поля прежнее — его читают старые записи, — но
                     # смысл теперь «ход против ЭТОЙ позиции».
                     "mae": adv, "adverse_of": ("mae_4h" if side == "long"
                                                else "mfe_4h")}
                nv = novelty(xj[i], nov_lo, nov_hi)
                if nv is not None:
                    d["odd"] = round(nv, 3)
                return d
            picks = {"arm": arm, "hour": grid[-1],
                     # Момент, когда решение стало известно. Час
                     # решения и момент решения — разные вещи: цикл
                     # просыпается через минуты после закрытия часа, и
                     # это задержка входа, а не ноль.
                     "at_ts": round(time.time()),
                     "long": [mk(i, "long") for i in o[::-1][:3]],
                     "short": [mk(i, "short") for i in o[:3]]}
            # Цена, доступная в момент решения. Ставится ПОСЛЕ отбора —
            # раньше неизвестно, у кого её спрашивать. Прежняя цена
            # (`px`, закрытие часа сигнала) остаётся в записи рядом:
            # разность двух — и есть цена подарка, и узнать её можно
            # только измерив, а не сняв.
            lp = live_px([p["sym"] for s in ("long", "short")
                          for p in picks[s]], book_root, log_=log_)
            for s in ("long", "short"):
                for p in picks[s]:
                    got = lp.get(p["sym"])
                    if got:
                        p["px_live"], p["px_live_at"] = got[0], round(got[1])
            # Один выбор на (руку, час) — и не больше.
            #
            # Цикл писал выбор при каждом проходе, а проходов внутри
            # одного часа бывает несколько: перезапуск цикла (каждая
            # заливка!) сразу гонит проход, и следующий по расписанию
            # приходит в тот же час. Замер на живом предпросмотре: у
            # часа 20 тридцать шесть сделок вместо двенадцати, у часа
            # 19 — двадцать четыре. Дубли не портят счёт (разбор помнит
            # разобранные часы), но вытесняют из таблицы настоящую
            # историю и делают статистику вида «сколько сделок» ложной.
            if (arm, picks["hour"]) not in seen_picks:
                seen_picks.add((arm, picks["hour"]))
                with open(ppath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(picks, ensure_ascii=False) + "\n")

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
            # Про счёт мысль пишется ПОСЛЕ его пересборки, ниже: тут его
            # ещё нет, а брать прежний баланс значило бы говорить о
            # состоянии до этой самой сделки.
            lines.insert(0, f"разбор прошлых выборов ({len(review)} имён, "
                            f"угадан знак у {hits}): " + "; ".join(
                                f"{r['sym'].replace('USDT','')} "
                                f"{'лонг' if r['side'] == 'long' else 'шорт'}: "
                                f"ждал {pct(r['expected'])}, вышло "
                                f"{pct(r['got'])}" for r in review))
        all_lines += [f"[{'деревья' if arm == 'gbm' else 'сеть'}] {t}"
                      for t in lines]
    # Счёт пересобирается ЦЕЛИКОМ из выборов и разборов, а не
    # накапливается по шагам. Так он остаётся функцией от истории:
    # повторный проход не может провести те же сделки дважды, а
    # изменение модели капитала применяется ко всей истории разом, а не
    # с середины.
    try:
        import trades as TR
        all_tr = TR.build(
            [json.loads(x) for x in open(ppath, encoding="utf-8")],
            [json.loads(x) for x in open(
                os.path.join(MODEL_DIR, "review.jsonl"),
                encoding="utf-8")])
        for arm, _ in ARMS:
            hist, bal = TR.account(all_tr, arm)
            apath = os.path.join(MODEL_DIR, f"account_{arm}.json")
            with open(apath + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"balance": bal, "history": hist[-500:],
                           "start": TR.START_BALANCE,
                           "leverage": 1.0}, f, ensure_ascii=False)
            os.replace(apath + ".tmp", apath)
            if hist:
                who = "деревья" if arm == "gbm" else "сеть"
                all_lines.append(
                    f"[{who}] счёт: {bal:+.2f} $ из {TR.START_BALANCE:.0f} "
                    f"после {len(hist)} закрытых сделок "
                    f"({pct((bal / TR.START_BALANCE - 1) * 1e4)} "
                    f"от старта, плечо 1×, издержки учтены).")
    except (OSError, ValueError) as e:
        log_(f"счёт пересобрать не вышло: {e}")

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
        # Сутки — период ПЕРЕОБУЧЕНИЯ (спека §5), а не наказание за
        # «ещё рано». Цикл, не обучившийся (мало сечений, крикнула
        # канарейка, упал), обязан проверить снова скоро: иначе сутки
        # ожидания данных превращаются в двое, и ждать выглядит ровно
        # как работать. Тот же класс, что «отказ неотличим от тишины».
        # Предпросмотр переобучается каждый час независимо от успеха:
        # его смысл — показывать, как модель меняется по мере
        # накопления, а сутки ожидания это скрыли бы.
        wait = RETRY_SEC if (a.pretest or not trained) else CYCLE_SEC
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
