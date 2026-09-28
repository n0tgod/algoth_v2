#!/usr/bin/env python3
"""
Проверки механики «ребаланс плечевых ETF в последний час Нью-Йорка».

Архив здесь не читается — кроме одной проверки, которая собирает
НАСТОЯЩИЕ зипы на четыре бара в своём временном каталоге: дедупликацию
суточных файлов иначе нечем проверить, а без неё часть баров входит в
ряд дважды (об этом прямо предупреждает
`research/a1_universe/binance_klines.read_symbol_timestamps`).

Всё остальное гоняет ТЕ ЖЕ функции замера на синтетической ленте,
собранной по часовым границам Нью-Йорка. Пересказа формул в тестах нет:
пересказ проверял бы тест, а не механику.

Что здесь обязано быть и есть:

* **заглядывание в будущее** — переписать ВСЁ, что с 15:00 и позже, и ни
  ход дня, ни признак квалификации, ни σ̂ размера не шелохнутся; рядом
  проверено, что подделка легла (ход часа обязан измениться, `assert` на
  литерал), иначе тест был бы холостым;
* **калибровочная пара** — подсаженный в ЦЕНЫ ход обязан пройти K1–K5, а
  случайное блуждание и перемешанные знаки обязаны его не найти;
* **отказ вместо пустоты** — ноль строк при непустом списке дней и пустое
  окно загрузки суть исключения, а не отчёт с прочерками;
* **прочерк вместо нуля** — отсутствующая минута, неоднозначный час
  перехода времени, недобор окна σ̂ и нулевой объём дают None, не 0.0;
* **вердиктовая фраза из числа** — и слово убийцы, и знак сравнения
  выведены из значения, подделка значения переворачивает фразу;
* **час-вердикт считается тем же кодом**, что и остальные 23 часа K3.

    cd ~/algoth_v2 && .venv/bin/python research/mech_59653014/test_etf_rebal.py
"""

import datetime as dt
import io
import os
import shutil
import sys
import tempfile
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bars as BR                                            # noqa: E402
import etf_rebal as ER                                       # noqa: E402
import fund_dates as FD                                      # noqa: E402
import nyse_cal as CAL                                       # noqa: E402

D = dt.date
MIN = BR.MIN_MS


def eq(a, b, tol=1e-9, what=""):
    assert a is not None, f"{what}: прочерк там, где ждали {b}"
    assert abs(a - b) <= tol, f"{what}: {a} != {b}"


# --- синтетическая лента ----------------------------------------------

class Tape:
    """Лента по часовым границам Нью-Йорка: только нужные минуты.

    Минуты, которые механике не нужны, не пишутся вовсе — и это часть
    проверки: пропуск обязан быть прочерком, а не соседним баром.
    """

    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol
        self.rows = {}

    def put(self, ts, op=None, cl=None, vol=1000.0, tbv=500.0):
        if ts is None:
            return
        o, c, v, t = self.rows.get(ts, (None, None, 0.0, 0.0))
        self.rows[ts] = (op if op is not None else o,
                         cl if cl is not None else c,
                         vol if vol is not None else v,
                         tbv if tbv is not None else t)

    def hour(self, day, hour, sig=None, fill=None, vol=1000.0, tbv=500.0):
        """Цена сигнала в `hour:00` (закрытие предыдущей минуты) и цена
        исполнения в `hour:00` (открытие этой минуты)."""
        t = ER.et_instant(day, hour)
        if t is None:
            return
        if sig is not None:
            self.put(t - MIN, cl=sig, op=sig, vol=vol, tbv=tbv)
        if fill is not None:
            self.put(t, op=fill, cl=fill, vol=vol, tbv=tbv)

    def bars(self):
        rows = [(t, o if o is not None else c, c if c is not None else o,
                 v, b) for t, (o, c, v, b) in self.rows.items()]
        return BR.from_rows(self.symbol, sorted(rows))


def walk_tape(lo, hi, hour_sd_bp=25.0, day_lo=2.0, day_hi=6.0, seed=3,
              symbol="BTCUSDT", every_hour=True, vol=1000.0, tbv=500.0):
    """Лента, у которой ход дня и ход часа заданы по отдельности.

    Цена отсчёта у каждого часа своя и равна 100: замер берёт ОТНОШЕНИЯ,
    и уровень ему безразличен, а раздельные уровни дают точный контроль
    над |ход дня| (чтобы квалификация была объявленной, а не случайной) и
    над ходом часа (чтобы подсадку было видно на фоне объявленного шума).
    """
    rng = np.random.default_rng(seed)
    tp = Tape(symbol)
    d = lo
    hours = range(24) if every_hour else (ER.VERDICT_HOUR,)
    while d <= hi:
        for h in hours:
            r = rng.uniform(day_lo, day_hi) / 100.0 * rng.choice([-1.0, 1.0])
            m = rng.normal(0.0, hour_sd_bp) / 1e4
            # Отсчёт хода дня: закрытие минуты перед (h+1):00 — его
            # прочтёт СЛЕДУЮЩИЙ день фонда.
            tp.hour(d, h + 1, sig=100.0, vol=vol, tbv=tbv)
            tp.hour(d, h, sig=100.0 * (1.0 + r), fill=100.0,
                    vol=vol, tbv=tbv)
            tp.hour(d, h + 1, fill=100.0 * (1.0 + m), vol=vol, tbv=tbv)
        d += dt.timedelta(days=1)
    return tp.bars()


CAL_LO, CAL_HI = D(2021, 1, 1), D(2026, 9, 25)
_CACHE = {}


def calib_bars(**kw):
    """Лента калибровки на полном диапазоне окон. Считается один раз."""
    key = tuple(sorted(kw.items()))
    if key not in _CACHE:
        _CACHE[key] = walk_tape(CAL_LO - dt.timedelta(days=4), CAL_HI, **kw)
    return _CACHE[key]


def cal_():
    return CAL.Calendar()


# --- календарь --------------------------------------------------------

def test_calendar_matches_known_nyse_dates():
    """Правила календаря дают ИЗВЕСТНЫЕ даты, а не правдоподобные.

    Литералы взяты из регламента NYSE по годам: правило, проверенное
    самим собой, не проверено ничем.
    """
    c = cal_()
    for d, kind in [
        (D(2021, 4, 2), CAL.HOLIDAY),     # Страстная пятница
        (D(2021, 7, 5), CAL.HOLIDAY),     # 4 июля на воскресенье → 5-е
        (D(2021, 12, 24), CAL.HOLIDAY),   # Рождество на субботу → 24-е
        (D(2022, 6, 20), CAL.HOLIDAY),    # Джунтинс на воскресенье → 20-е
        (D(2022, 12, 26), CAL.HOLIDAY),   # Рождество на воскресенье → 26-е
        (D(2023, 1, 2), CAL.HOLIDAY),     # Новый год на воскресенье → 2-е
        (D(2023, 7, 3), CAL.EARLY),       # канун 4 июля (вторника)
        (D(2024, 3, 29), CAL.HOLIDAY),    # Страстная пятница
        (D(2024, 12, 24), CAL.EARLY),     # канун Рождества, вторник
        (D(2025, 1, 9), CAL.HOLIDAY),     # траур по Дж. Картеру
        (D(2025, 11, 28), CAL.EARLY),     # пятница после благодарения
        (D(2026, 7, 3), CAL.HOLIDAY),     # 4 июля на субботу → 3-е
        (D(2026, 1, 2), CAL.TRADE),       # обычная пятница
    ]:
        got = c.kind(d)
        assert got == kind, f"{d} ({d.strftime('%a')}): {got}, ждали {kind}"
    # Джунтинс появился в 2022-м: в 2021-м 18 июня — торговая пятница.
    assert c.kind(D(2021, 6, 18)) == CAL.TRADE, "Джунтинса в 2021 году нет"


def test_calendar_refuses_a_year_it_was_not_declared_for():
    """Год, чьи правила не сверены, — ОТКАЗ, а не «наверное, торговый».

    Молчаливая экстраполяция календаря есть выдуманный торговый день.
    """
    c = cal_()
    for d in (D(2019, 6, 3), D(2030, 6, 3)):
        try:
            c.kind(d)
        except ValueError:
            continue
        raise AssertionError(f"{d} вне объявленных лет, а ответ дан")


def test_early_close_day_is_its_own_category():
    """Ранняя сессия закрывается в 13:00, и это не 16:00 и не выходной."""
    c = cal_()
    eq(c.close_hour(D(2024, 12, 24)), CAL.EARLY_CLOSE_H,
       what="закрытие кануна Рождества")
    eq(c.close_hour(D(2024, 12, 23)), CAL.CLOSE_H, what="обычный день")
    assert c.close_hour(D(2024, 12, 25)) is None, "у праздника закрытия нет"
    assert c.why(D(2024, 12, 24)), "у ранней сессии обязано быть имя"


# --- время Нью-Йорка --------------------------------------------------

def test_new_york_hour_moves_with_daylight_saving():
    """16:00 ET — это 20:00 UTC летом и 21:00 зимой, а не одно число."""
    summer = ER.et_instant(D(2024, 7, 10), 16)
    winter = ER.et_instant(D(2024, 12, 10), 16)
    for ms, want in ((summer, 20), (winter, 21)):
        h = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).hour
        eq(h, want, what=f"час UTC для 16:00 ET ({ms})")


def test_missing_and_doubled_hour_of_the_dst_switch_are_dashes():
    """Час, которого нет, и час, которых два, — прочерк, не молчаливый выбор."""
    assert ER.et_instant(D(2024, 3, 10), 2) is None, "02:00 весной не наступает"
    assert ER.et_instant(D(2024, 11, 3), 1) is None, "01:00 осенью наступает дважды"
    assert ER.et_instant(D(2024, 3, 10), 3) is not None, "03:00 весной есть"


# --- бары -------------------------------------------------------------

def test_signal_is_the_previous_minute_close_and_fill_is_this_minute_open():
    """Сигнал — закрытие минуты ДО момента, исполнение — открытие минуты С него.

    Разделение не косметическое: на нём стоит вся проверка на
    заглядывание в будущее.
    """
    t = ER.et_instant(D(2024, 7, 10), 15)
    b = BR.from_rows("X", [(t - MIN, 1.0, 2.0, 10.0, 5.0),
                           (t, 3.0, 4.0, 10.0, 5.0)])
    eq(ER.sig_price(b, t), 2.0, what="цена сигнала")
    eq(ER.fill_price(b, t), 3.0, what="цена исполнения")


def test_missing_minute_is_a_dash_not_a_neighbour():
    """Минуты, которой в архиве нет, не существует: None, не соседний бар."""
    t = ER.et_instant(D(2024, 7, 10), 15)
    b = BR.from_rows("X", [(t - 5 * MIN, 1.0, 2.0, 10.0, 5.0),
                           (t + 5 * MIN, 3.0, 4.0, 10.0, 5.0)])
    assert b.at_open(t) is None, "открытие отсутствующей минуты — прочерк"
    assert b.at_close(t) is None, "закрытие отсутствующей минуты — прочерк"
    assert ER.fill_price(b, t) is None and ER.sig_price(b, t) is None


def test_duplicate_bars_from_daily_files_are_dropped():
    """Суточный файл приносит день целиком — дубли снимаются по метке.

    Собираются настоящие зипы того же формата, что у архива: подставной
    артефакт обязан выглядеть как живой, иначе проверка холостая.
    """
    tmp = tempfile.mkdtemp(prefix="mech59-arch-")
    old_a, old_c = BR.ARCHIVE, BR.CACHE
    try:
        d = os.path.join(tmp, "1m", "ZZZUSDT")
        os.makedirs(d)
        head = ("open_time,open,high,low,close,volume,close_time,"
                "quote_volume,count,taker_buy_volume,taker_buy_quote_volume,"
                "ignore\n")

        def row(ts, px):
            return (f"{ts},{px},{px},{px},{px},1.0,{ts + MIN - 1},"
                    f"{px},10,0.5,{px / 2},0\n")

        base = 1_700_000_000_000 // MIN * MIN
        pack = [("ZZZUSDT-1m-2023-11", [0, 1, 2]),
                ("ZZZUSDT-1m-2023-11-15", [1, 2, 3])]
        for stem, offs in pack:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr(stem + ".csv", head + "".join(
                    row(base + o * MIN, 100.0 + o) for o in offs))
            with open(os.path.join(d, stem + ".zip"), "wb") as f:
                f.write(buf.getvalue())
        BR.ARCHIVE, BR.CACHE = tmp, os.path.join(tmp, "cache")
        b = BR.load("ZZZUSDT", base, base + 10 * MIN, use_cache=False,
                    log=lambda *_: None)
        eq(len(b), 4, what="баров после снятия дублей")
        eq(b.at_open(base + 1 * MIN), 101.0, what="цена не удвоилась")
        eq(BR.coverage(b, base, base + 4 * MIN), 1.0, what="покрытие окна")
    finally:
        BR.ARCHIVE, BR.CACHE = old_a, old_c
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_refuses_an_empty_window():
    """Ноль баров при существующем архиве — ОТКАЗ загрузки, не пустой рынок."""
    tmp = tempfile.mkdtemp(prefix="mech59-arch-")
    old_a = BR.ARCHIVE
    try:
        d = os.path.join(tmp, "1m", "ZZZUSDT")
        os.makedirs(d)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", "open_time,open,high,low,close,volume,a,b,c,"
                                "d,e,f\n1700000000000,1,1,1,1,1,1,1,1,1,1,0\n")
        with open(os.path.join(d, "ZZZUSDT-1m-2023-11.zip"), "wb") as f:
            f.write(buf.getvalue())
        BR.ARCHIVE = tmp
        try:
            BR.load("ZZZUSDT", 1, 2, use_cache=False, log=lambda *_: None)
        except ValueError:
            return
        raise AssertionError("пустое окно вернуло ряд вместо отказа")
    finally:
        BR.ARCHIVE = old_a
        shutil.rmtree(tmp, ignore_errors=True)


def test_coverage_is_a_number_before_the_verdict():
    """Покрытие окна — число; окно нулевой длины — прочерк, не единица."""
    t = ER.et_instant(D(2024, 7, 10), 15)
    b = BR.from_rows("X", [(t + i * MIN, 1.0, 1.0, 1.0, 0.5) for i in (0, 2)])
    eq(BR.coverage(b, t, t + 4 * MIN), 0.5, what="покрытие половины окна")
    assert BR.coverage(b, t, t) is None, "окно нулевой длины — прочерк"


# --- строка дня -------------------------------------------------------

def _one_day_tape(day, r_day=0.03, move_bp=40.0, prev=None, hour=15):
    c = cal_()
    prev = prev or c.prev_session(day)
    tp = Tape()
    tp.hour(prev, hour + 1, sig=100.0)
    tp.hour(day, hour, sig=100.0 * (1.0 + r_day), fill=100.0)
    tp.hour(day, hour + 1, fill=100.0 * (1.0 + move_bp / 1e4))
    tp.hour(day, hour + 2, fill=100.0)
    tp.hour(day, hour, fill=100.0)
    t = ER.et_instant(day, hour)
    tp.put(t + 30 * MIN, op=100.0, cl=100.0)
    return tp


def test_day_row_signs_the_hour_move_by_the_day_move():
    """Ход часа берётся СО ЗНАКОМ хода дня — и на падении тоже."""
    c = cal_()
    day = D(2024, 7, 10)
    up, _ = ER.hour_row(_one_day_tape(day, 0.03, 40.0).bars(), c, day)
    eq(up["signed_bp"], 40.0, tol=1e-6, what="рост дня, рост часа")
    dn, _ = ER.hour_row(_one_day_tape(day, -0.03, -40.0).bars(), c, day)
    eq(dn["signed_bp"], 40.0, tol=1e-6, what="падение дня, падение часа")
    eq(dn["move_bp"], -40.0, tol=1e-6, what="сырой ход часа остался своим")


def test_qualification_gate_uses_the_declared_two_percent():
    """Квалификация — объявленные 2 % по |ход дня|, и порог не подбирается."""
    c, day = cal_(), D(2024, 7, 10)
    eq(ER.QUAL_ABS_R, 0.02, what="объявленный порог квалификации")
    hi, _ = ER.hour_row(_one_day_tape(day, 0.0201).bars(), c, day)
    lo, _ = ER.hour_row(_one_day_tape(day, 0.0199).bars(), c, day)
    assert hi["qual"], "2.01 % обязан квалифицироваться"
    assert not lo["qual"], "1.99 % квалифицироваться не должен"
    assert ER.qualified([hi, lo]) == [hi], "в отбор идут только годные"


def test_early_close_day_is_not_a_full_session():
    """В ранний день пай считают к 13:00 — часа 15–16 у фонда нет."""
    c, day = cal_(), D(2024, 12, 24)
    assert c.kind(day) == CAL.EARLY, "24.12.2024 — ранняя сессия"
    row, why = ER.hour_row(_one_day_tape(day).bars(), c, day)
    assert row is None, "ранний день попал в замер как обычный"
    assert why and "13:00" in why, f"причина не названа: {why!r}"


def test_day_after_early_close_is_skipped_with_a_named_reason():
    """У дня после ранней сессии отсчёт хода дня лежит в 13:00, не в 16:00."""
    c, day = cal_(), D(2024, 12, 26)
    assert c.kind(c.prev_session(day)) == CAL.EARLY
    row, why = ER.hour_row(_one_day_tape(day).bars(), c, day)
    assert row is None, "день после ранней сессии измерен по чужому отсчёту"
    assert why and "ранняя" in why, f"причина не названа: {why!r}"


def test_non_trading_day_needs_the_calendar_reference():
    """У выходного нет предыдущего дня фонда — отсчёт календарный, и это сказано."""
    c, sat = cal_(), D(2024, 7, 13)
    assert c.kind(sat) == CAL.WEEKEND
    tp = _one_day_tape(sat, 0.03, 40.0, prev=sat - dt.timedelta(days=1))
    row, why = ER.hour_row(tp.bars(), c, sat, ref_mode=ER.REF_PREV_CALENDAR)
    assert row is not None, f"выходной не измерен: {why}"
    eq(row["signed_bp"], 40.0, tol=1e-6, what="ход часа выходного")
    assert row["ref_day"] == "2024-07-12", row["ref_day"]
    none_row, why2 = ER.hour_row(tp.bars(), c, sat)
    assert none_row is None and "неторговый" in (why2 or ""), why2


def test_day_table_refuses_zero_rows_on_a_non_empty_input():
    """Ноль строк при непустом списке дней — исключение, не отчёт с прочерками."""
    c = cal_()
    empty = BR.from_rows("X", [(1_700_000_000_000, 1.0, 1.0, 1.0, 0.5)])
    try:
        ER.day_table(empty, c, [D(2024, 7, 10), D(2024, 7, 11)])
    except ValueError as e:
        assert "отказ" in str(e), str(e)
        eq(len(ER.day_table(empty, c, [])[0]), 0, what="пустой вход — пусто")
        return
    raise AssertionError("пустая таблица выдала себя за результат")


def test_skips_are_counted_by_named_reason():
    """Выпавший день считается с названной причиной: пропуск ≠ ноль."""
    c = cal_()
    days = [D(2024, 12, 23), D(2024, 12, 24), D(2024, 12, 26)]
    tp = Tape()
    for d in days + [D(2024, 12, 20)]:
        tp.hour(d, 16, sig=100.0)
        tp.hour(d, 15, sig=103.0, fill=100.0)
        tp.hour(d, 16, fill=100.4)
        tp.hour(d, 17, fill=100.0)
    rows, skips = ER.day_table(tp.bars(), c, days)
    eq(len(rows), 1, what="измеренных дней")
    eq(sum(skips.values()), 2, what="выпавших дней")
    assert all(k and not k.isspace() for k in skips), skips


# --- заглядывание в будущее -------------------------------------------

def test_signal_does_not_read_the_future():
    """Переписать всё с 15:00 — сигнал не шелохнётся, а исполнение изменится.

    Рядом проверено, что подделка ЛЕГЛА: без этого тест был бы холостым
    — «ничего не изменилось» получалось бы и на нетронутой записи.
    """
    c, day = cal_(), D(2024, 7, 10)
    t_sig = ER.et_instant(day, ER.VERDICT_HOUR)
    t_out = ER.et_instant(day, ER.VERDICT_HOUR + 1)
    prev = c.prev_session(day)
    tp = Tape()
    # Сутки минут до 15:00 — чтобы σ̂ было числом, а не прочерком.
    # Заливка идёт ПЕРВОЙ: она перекрывает минуту перед 15:00, то есть
    # саму цену сигнала, и порядок здесь есть часть фикстуры (первая
    # версия теста переворачивала знак хода дня именно этим).
    for i in range(1, ER.SIGMA_LOOKBACK_MIN + 1):
        tp.put(t_sig - i * MIN, op=100.0 + 0.01 * (i % 7),
               cl=100.0 + 0.01 * (i % 7))
    tp.hour(prev, 16, sig=100.0)
    tp.hour(day, 15, sig=103.0, fill=100.0)
    tp.hour(day, 16, fill=100.4)
    tp.hour(day, 17, fill=100.0)
    before, _ = ER.hour_row(tp.bars(), c, day)
    eq(before["r_day"], 0.03, tol=1e-9, what="ход дня до подделки")
    eq(before["signed_bp"], 40.0, tol=1e-6, what="ход часа до подделки")
    assert before["sigma_hour"] is not None, "σ̂ обязана быть числом"

    b = tp.bars()
    op, cl = b.open.copy(), b.close.copy()
    later = b.ts >= t_sig
    assert int(later.sum()) >= 3, "переписывать нечего — фикстура пуста"
    op[later] *= 1.5
    cl[later] *= 1.5
    b2 = BR.Bars(b.symbol, b.ts, op, cl, b.volume, b.taker_buy)
    # Подделка ЛЕГЛА, и это assert на литерал: «ничего не изменилось»
    # без такой проверки получается и на нетронутой записи.
    eq(b2.at_open(t_out), 150.6, tol=1e-6, what="цена выхода после подделки")
    after, _ = ER.hour_row(b2, c, day)
    for k in ("r_day", "sign", "qual", "sigma_hour", "size_frac"):
        assert before[k] == after[k], (
            f"{k} зависит от будущего: {before[k]} → {after[k]}")


def test_the_future_rewrite_test_is_not_hollow():
    """Правка ЦЕНЫ ВЫХОДА обязана менять ход часа — тест не холостой."""
    c, day = cal_(), D(2024, 7, 10)
    tp = _one_day_tape(day, 0.03, 40.0)
    before, _ = ER.hour_row(tp.bars(), c, day)
    b = tp.bars()
    op = b.open.copy()
    j = b.index(ER.et_instant(day, 16))
    assert j is not None, "минуты выхода нет — фикстура пуста"
    op[j] *= 1.01
    after, _ = ER.hour_row(BR.Bars(b.symbol, b.ts, op, b.close, b.volume,
                                   b.taker_buy), c, day)
    eq(before["signed_bp"], 40.0, tol=1e-6, what="ход часа до подделки")
    assert abs(after["signed_bp"] - 140.4) < 1.0, after["signed_bp"]
    eq(after["r_day"], before["r_day"], what="ход дня от правки выхода")


# --- размер позиции ---------------------------------------------------

def test_sigma_needs_its_minutes_else_a_dash():
    """Недобор окна σ̂ — прочерк, а не «σ маленькая»."""
    t = ER.et_instant(D(2024, 7, 10), 15)
    rng = np.random.default_rng(5)
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.0005,
                                            ER.SIGMA_LOOKBACK_MIN)))
    dense = BR.from_rows("X", [(t - (ER.SIGMA_LOOKBACK_MIN - i) * MIN,
                                float(px[i]), float(px[i]), 1.0, 0.5)
                               for i in range(ER.SIGMA_LOOKBACK_MIN)])
    s = ER.sigma_hour(dense, t)
    assert s is not None and 0.0005 * 60 ** 0.5 * 0.5 < s < 0.0005 * 60 ** 0.5 * 2, s
    sparse = BR.from_rows("X", [(t - (ER.SIGMA_LOOKBACK_MIN - i) * MIN,
                                 float(px[i]), float(px[i]), 1.0, 0.5)
                                for i in range(0, ER.SIGMA_MIN_MINUTES - 1)])
    assert ER.sigma_hour(sparse, t) is None, "недобор минут обязан быть прочерком"
    assert ER.size_frac(None) is None, "прочерк σ̂ — прочерк размера"


def test_size_is_capped_at_the_deposit():
    """Тихий час не даёт плеча: доля депозита не превышает единицы.

    Без потолка хвост книги оказывается плечом, а не сигналом — это
    ровно то, чем объяснились короткие DCA-книги.
    """
    eq(ER.size_frac(1e-6), 1.0, what="доля при почти нулевой σ̂")
    eq(ER.size_frac(ER.RISK_PER_HOUR), 1.0, what="доля при σ̂ ровно в риск")
    eq(ER.size_frac(4 * ER.RISK_PER_HOUR), 0.25, what="доля при σ̂ вчетверо")


def test_money_counts_only_days_with_a_size():
    """День без размера в счёт не входит и считается отдельно."""
    rows = [{"qual": True, "sign": 1.0, "signed_bp": 111.0, "size_frac": 0.5,
             "day": "2024-07-10", "r_day": 0.03},
            {"qual": True, "sign": 1.0, "signed_bp": 500.0, "size_frac": None,
             "day": "2024-07-11", "r_day": 0.03}]
    m = ER.money(rows, cost_bp=11.0)
    eq(m["n"], 1, what="дней в счёте")
    eq(m["no_size"], 1, what="дней без размера")
    eq(m["net_pct"], 0.5 * 100.0 / 100.0, what="нетто процентов депозита")
    assert m["without_top3_pct"] is None, "на одном дне «без трёх» — прочерк"
    empty = ER.money([{"qual": True, "sign": 1.0, "signed_bp": 5.0,
                       "size_frac": None, "day": "x", "r_day": 0.03}])
    assert empty["net_pct"] is None, "нет дней с размером — прочерк, не ноль"


# --- статистика -------------------------------------------------------

def test_stat_is_a_dash_on_emptiness_not_a_zero():
    """Пустая выборка — прочерки; ноль означает «измерено и равно нулю»."""
    s = ER.stat([])
    assert s["mean"] is None and s["t"] is None and s["lo"] is None, s
    eq(s["n"], 0, what="наблюдений")
    s2 = ER.stat([1.0, None, 3.0])
    eq(s2["n"], 2, what="прочерки не считаются наблюдениями")
    eq(s2["mean"], 2.0, what="среднее по измеренным")


def test_slope_measures_growth_with_the_move():
    """K5 меряет рост выплаты с |ход дня|: поток фонда есть 2·A·r."""
    rows = [{"r_day": 0.01 * k, "signed_bp": 10.0 * k, "sign": 1.0,
             "qual": True} for k in range(2, 12)]
    sl = ER.slope_on_abs_r(rows)
    eq(sl["slope"], 10.0, tol=1e-6, what="наклон на % хода")
    flat = [{"r_day": 0.01 * k, "signed_bp": 30.0, "sign": 1.0, "qual": True}
            for k in range(2, 12)]
    eq(ER.slope_on_abs_r(flat)["slope"], 0.0, tol=1e-9,
       what="ровная подсадка наклона не создаёт")
    assert ER.slope_on_abs_r(rows[:2])["slope"] is None, "две точки — прочерк"


# --- убийцы и вердикт -------------------------------------------------

def _ks(m_bp=30.0, n=250, placebo_bp=0.0, nontrade_bp=0.0, hour15=30.0,
        others=5.0, slope=1.0):
    rng = np.random.default_rng(17)

    def rows(mean, k, sl=0.0):
        out = []
        for i in range(k):
            r = 0.02 + 0.04 * rng.random()
            out.append({"qual": True, "sign": 1.0, "r_day": r,
                        "signed_bp": mean + sl * r * 100.0
                                     + rng.normal(0, 1.0),
                        "move_bp": mean})
        return out
    by_hour = {h: others for h in range(24)}
    by_hour[ER.VERDICT_HOUR] = hour15
    return ER.killers(rows(m_bp, n, slope), rows(placebo_bp, n),
                      rows(nontrade_bp, n), by_hour)


def test_k1_compares_with_the_round_of_one_leg():
    """Порог K1 — круг ОДНОЙ ноги из расчётного ядра, а не своя копия числа."""
    from trades import ROUND_COST_BP
    eq(ER.K1_FLOOR_BP, ROUND_COST_BP, what="порог K1")
    assert _ks(m_bp=ROUND_COST_BP + 5.0)["K1"]["dead"] is False
    assert _ks(m_bp=ROUND_COST_BP - 5.0)["K1"]["dead"] is True


def test_k3_compares_the_verdict_hour_with_the_other_hours_p95():
    """Час 15–16 судится против p95 ОСТАЛЬНЫХ часов, а не против себя."""
    ks = _ks(hour15=30.0, others=5.0)
    eq(ks["K3"]["hours"], 23, what="часов в контроле")
    eq(ks["K3"]["thr"], 5.0, what="p95 остальных часов")
    assert ks["K3"]["dead"] is False, ks["K3"]
    assert _ks(hour15=4.0, others=5.0)["K3"]["dead"] is True


def test_too_few_days_is_unmeasured_not_a_verdict():
    """Дней меньше объявленного минимума — «не измерено», и покрытие первым."""
    ks = _ks(m_bp=30.0)
    eq(ER.MIN_QUAL_DAYS, 200, what="объявленный минимум квалифицированных дней")
    v = ER.verdict(ks, ER.MIN_QUAL_DAYS - 1)
    eq(len(v["verdict"]), len(ER.UNMEASURED), what="длина слова вердикта")
    assert v["verdict"] == ER.UNMEASURED, v
    assert str(ER.MIN_QUAL_DAYS - 1) in v["phrase"], v["phrase"]
    assert ER.verdict(ks, ER.MIN_QUAL_DAYS)["verdict"] != ER.UNMEASURED


def test_verdict_phrase_follows_the_number():
    """Фраза вердикта выведена из чисел: подделка числа её переворачивает."""
    alive = ER.verdict(_ks(m_bp=40.0, hour15=40.0, others=5.0, slope=2.0),
                       300)
    assert alive["verdict"] == ER.ALIVE, alive
    assert ER.ALIVE in alive["phrase"] and "300" in alive["phrase"], alive
    dead = ER.verdict(_ks(m_bp=1.0, hour15=1.0, others=5.0, slope=-2.0), 300)
    assert dead["verdict"] == ER.DEAD, dead
    assert "K1" in dead["phrase"] and ER.DEAD in dead["phrase"], dead


def test_killer_phrase_flips_with_the_number():
    """И знак сравнения, и слово убийцы считаются от значения, а не стоят рядом."""
    live = _ks(m_bp=40.0)["K1"]["phrase"]
    dead = _ks(m_bp=1.0)["K1"]["phrase"]
    assert " > " in live and ER.ALIVE in live, live
    assert " ≤ " in dead and ER.DEAD in dead, dead
    assert ER.UNMEASURED in ER._cmp_phrase(None, 1.0, True, "", "что-то")


# --- час-вердикт и перебор часов --------------------------------------

def test_verdict_hour_is_the_same_code_as_the_hour_sweep():
    """Час 15–16 в K3 обязан быть тем же числом, что измеряемая сделка.

    Разойдись они — вердикт мерился бы одним кодом, а его контроль
    другим, и K3 сравнивал бы яблоки с грушами.
    """
    c = cal_()
    b = calib_bars()
    lo, hi = D(2024, 1, 1), D(2024, 12, 31)
    rows, _ = ER.day_table(b, c, c.days(lo, hi, (CAL.TRADE, CAL.EARLY)))
    direct = float(np.mean([r["signed_bp"] for r in ER.qualified(rows)]))
    bh, bn = ER.by_hour_means(b, c, lo, hi)
    eq(bh[ER.VERDICT_HOUR], direct, tol=1e-9, what="час 15–16 против сделки")
    eq(bn[ER.VERDICT_HOUR], len(ER.qualified(rows)), what="дней часа 15–16")
    assert len(bh) == 24, "часов обязано быть двадцать четыре"


# --- калибровочная пара -----------------------------------------------

def _measure(b, **kw):
    return ER.measure_symbol(b, cal_(), fund_end=CAL_HI, **kw)


def test_random_walk_stays_silent():
    """На случайном блуждании замер обязан МОЛЧАТЬ: K1 мертво."""
    res = _measure(calib_bars())
    assert res["n_qual"] >= ER.MIN_QUAL_DAYS, res["n_qual"]
    assert res["killers"]["K1"]["dead"] is True, res["killers"]["K1"]
    assert abs(res["killers"]["K1"]["value"]) < ER.K1_FLOOR_BP, \
        res["killers"]["K1"]["value"]
    assert res["verdict"]["verdict"] == ER.DEAD, res["verdict"]


def test_planted_move_in_prices_passes_the_killers():
    """Подсадка ∝ |ход дня| в ЦЕНЫ обязана пройти K1–K5.

    Подсадка живёт в ценах, а не в таблице дней: калибровка обязана
    проверять и загрузку тоже, иначе сломанный читатель архива выглядит
    ровно как «эффекта нет».
    """
    c, b = cal_(), calib_bars()
    days = c.days(ER.FUND_START_DECLARED["BTCUSDT"], CAL_HI,
                  (CAL.TRADE, CAL.EARLY))
    pb, n = ER.plant_bars(b, c, days, bp=30.0, frac=0.5, shape="prop")
    assert n > 100, f"подсажено всего {n} дней"
    res = _measure(pb)
    ks = res["killers"]
    bad = [k for k, v in ks.items() if v["dead"]]
    assert not bad, f"подсадку не нашли: {[ks[k]['phrase'] for k in bad]}"
    assert res["verdict"]["verdict"] == ER.ALIVE, res["verdict"]


def test_flat_plant_passes_k1_to_k4_and_leaves_k5_to_the_shape():
    """Ровная подсадка обязана пройти K1–K4 — и НЕ обязана проходить K5.

    K5 меряет форму потока (ΔE = 2·A·r), а ровный плюс её не имеет: это
    не дефект замера, а разница между «эффект есть» и «эффект той
    формы, которую утверждает механизм».
    """
    c, b = cal_(), calib_bars()
    days = c.days(ER.FUND_START_DECLARED["BTCUSDT"], CAL_HI,
                  (CAL.TRADE, CAL.EARLY))
    pb, _ = ER.plant_bars(b, c, days, bp=30.0, frac=0.5, shape="flat")
    ks = _measure(pb)["killers"]
    bad = [k for k in ("K1", "K2", "K3", "K4") if ks[k]["dead"]]
    assert not bad, f"ровную подсадку не нашли: {[ks[k]['phrase'] for k in bad]}"
    assert abs(ks["K5"]["value"]) < 10.0, (
        "ровная подсадка не вправе давать наклон: " + ks["K5"]["phrase"])


def test_shuffled_signs_kill_k1_and_flatten_the_slope():
    """Перемешанные знаки хода дня обязаны уронить K1 и обнулить наклон.

    Нуль честной формы: календарь и распределение часовых ходов на
    месте, разорвана ровно связь со знаком хода дня.

    Заявка просила «обязано ронять K1 и K5». K1 падает на КАЖДОМ зерне.
    K5 при пороге «наклон ≤ 0» есть монета: у нуля наклон симметричен
    относительно нуля, и на половине зёрен он выйдет положительным на
    величину шума. Требовать от одного зерна падения K5 значило бы
    объявить проверкой бросок монеты, поэтому проверяется то, что у нуля
    действительно обязано быть: наклон неотличим от нуля (|t| < 2) и в
    разы меньше подсаженного. Доля зёрен, на которых K5 всё же падает,
    печатается прогоном рядом — как число, а не как вердикт.
    """
    c, b = cal_(), calib_bars()
    days = c.days(ER.FUND_START_DECLARED["BTCUSDT"], CAL_HI,
                  (CAL.TRADE, CAL.EARLY))
    pb, _ = ER.plant_bars(b, c, days, bp=30.0, frac=0.5, shape="prop")
    rows, _ = ER.day_table(pb, c, days)
    hours = {ER.VERDICT_HOUR: 15.0, 0: 1.0, 1: 1.0}
    live = ER.killers(rows, [], [], hours)
    assert live["K1"]["dead"] is False, live["K1"]["phrase"]
    assert live["K5"]["dead"] is False, live["K5"]["phrase"]
    planted_slope = live["K5"]["value"]

    fell = 0
    for seed in range(8):
        sh = ER.shuffle_signs(rows, seed=seed)
        eq(len(sh), len(rows), what="строк после перестановки")
        ks = ER.killers(sh, [], [], {ER.VERDICT_HOUR: 1.0, 0: 1.0, 1: 1.0})
        assert ks["K1"]["dead"] is True, (
            f"зерно {seed}: перемешанные знаки прошли K1: "
            + ks["K1"]["phrase"])
        sl, t = ks["K5"]["value"], ks["K5"]["t"]
        assert abs(t) < 2.0, f"зерно {seed}: у нуля наклон значим, t={t}"
        assert abs(sl) < abs(planted_slope) / 2.0, (
            f"зерно {seed}: наклон нуля {sl} не мельче подсаженного "
            f"{planted_slope}")
        fell += bool(ks["K5"]["dead"])
    assert 0 < fell < 8, f"K5 у нуля обязан быть монетой, а упал {fell} из 8"


# --- отпечаток потока и сверка дат ------------------------------------

def test_aggressor_share_is_a_dash_on_zero_volume():
    """Нулевой объём — прочерк, а не 0.5: «не измерено» ≠ ноль."""
    t = ER.et_instant(D(2024, 7, 10), 15)
    rows = [(t + i * MIN, 100.0, 100.0, 10.0, 7.5) for i in range(60)]
    b = BR.from_rows("X", rows)
    eq(ER.aggressor_signed_pp(b, t, t + 60 * MIN, 1.0), 25.0,
       what="перевес агрессора при доле 0.75")
    eq(ER.aggressor_signed_pp(b, t, t + 60 * MIN, -1.0), -25.0,
       what="перевес со знаком падения")
    dead = BR.from_rows("X", [(t + i * MIN, 100.0, 100.0, 0.0, 0.0)
                              for i in range(60)])
    assert ER.aggressor_signed_pp(dead, t, t + 60 * MIN, 1.0) is None
    assert ER.aggressor_signed_pp(b, t, t + 60 * MIN, 0.0) is None


def test_fund_date_parsers_refuse_a_wrong_catch():
    """Разборщик страницы фонда молчит там, где схватил не то.

    Живой случай: хвост «as of 09/25/2026 $1,320,640,709.94» без
    требования знака доллара разбирался в 9 долларов активов.
    """
    eq(FD.parse_money("as of 09/25/2026 $1,320,640,709.94"), 1_320_640_709.94,
       tol=0.01, what="активы фонда")
    assert FD.parse_money("as of 09/25/2026") is None, "дата — не активы"
    assert FD.parse_money("$9.00") is None, "девять долларов — не фонд"
    eq(FD.parse_money("$1.32 billion"), 1.32e9, tol=1.0, what="активы словом")
    assert FD.parse_date("fund inception 06/27/2023") == "2023-06-27"
    assert FD.parse_date("Inception June 4, 2024") == "2024-06-04"
    assert FD.parse_date("no date here") is None, "нет даты — прочерк"
    lab, tail, v = FD.find_value("Inception NAV 70.9% Inception Date 06/07/2024",
                                 FD.DATE_LABELS, FD.parse_date)
    assert v == "2024-06-07", (lab, tail, v)


def test_fund_window_prefers_the_checked_date():
    """Сверенная дата побеждает объявленную, а её отсутствие — прочерк."""
    w = ER.windows("BTCUSDT")
    assert w["fund"][0] == ER.FUND_START_DECLARED["BTCUSDT"], w
    w2 = ER.windows("BTCUSDT", fund_start=D(2023, 7, 1))
    assert w2["fund"][0] == D(2023, 7, 1), w2
    assert w2["placebo"] == (ER.PLACEBO_LO, ER.PLACEBO_HI), w2
    assert FD.read(os.path.join(HERE, "нет-такого-файла.json")) == {}


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    bad = []
    for fn in ALL:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            bad.append(fn.__name__)
            print(f"  ПРОВАЛ {fn.__name__} — {e}")
        except Exception as e:                              # noqa: BLE001
            bad.append(fn.__name__)
            print(f"  ПРОВАЛ {fn.__name__} — {type(e).__name__}: {e}")
    print(f"\nпроверок {len(ALL)}, провалов {len(bad)}")
    if bad:
        # Список провалов повторяется в ХВОСТЕ вывода: приёмка фабрики
        # смотрит последние 4000 знаков и ищет в них имя названной
        # проверки, а длинная сюита вытеснила бы его наверх.
        print("провалились: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
