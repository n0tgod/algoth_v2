#!/usr/bin/env python3
"""Проверки механики 13a67a67 — возраст имени как режим прогноза.

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть.
Проверка, которая не кусается, не проверяет ничего.

Что проверяется: момент решения (метка часа, а не `at_ts`) и
заглядывание в будущее; знак стороны у хода; ничья не в свою пользу;
прочерк вместо нуля у пустой ячейки и у слабого бутстрапа; отказ вместо
пустоты; своя полоса у неизвестного возраста; три убийцы вердикта;
час как единица независимости; калибровочная пара обеими ногами;
сторона у фильтра возраста и контроль размера из своей стороны; ничья
контроля фильтру не в зачёт; вердиктовые фразы, выведенные из чисел.

Вывод намеренно скуп: приёмка смотрит ПОСЛЕДНИЕ 4000 символов, и строка
«ПРОВАЛ имя», утонувшая в середине, есть контроль, который здесь
пройдёт, а там нет.

    .venv/bin/python research/mech_13a67a67/test_age_mode.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import age_mode as AM                                        # noqa: E402
import run_age_mode as RM                                    # noqa: E402
from age_mode import PA, TR                                  # noqa: E402

TESTS = []
H = 3600.0
T0 = TR._ts("2026-08-12-00")


def test(fn):
    TESTS.append(fn)
    return fn


def quiet(*_a):
    pass


# ------------------------------------------------------------ фикстуры

def line(hour_i, arm, rows, at_ts=None):
    """Строка журнала разбора в ЖИВОЙ форме.

    `at_ts` по умолчанию заведомо ПОЗЖЕ часа — ровно так его и пишет
    цикл; фикстура, где `at_ts` совпадает с часом, спрятала бы разницу
    между моментом решения и моментом записи.
    """
    hour = TR._hour_of(T0 + hour_i * H)
    return {"arm": arm, "hour": hour, "cost_bp": 11.0,
            "at_ts": (T0 + hour_i * H + 5 * 86400.0 if at_ts is None
                      else at_ts),
            "rows": list(rows)}


def row(sym, side, got, net=None):
    return {"sym": sym, "side": side, "expected": 40.0, "got": float(got),
            "net": (float(net) if net is not None
                    else round((1 if side == "long" else -1) * float(got)
                               - 11.0, 1))}


def launch_of(**days):
    """Символ → момент листинга, отсчитанный от начала окна фикстур."""
    return {sym: T0 - float(d) * 86400.0 for sym, d in days.items()}


def small(n_hours=6, per_hour=4):
    """Небольшой живой на вид журнал: обе руки, обе стороны, дрожание."""
    rng = np.random.default_rng(7)
    lines = []
    for i in range(n_hours):
        for arm in ("gbm", "nn"):
            rows = [row(f"S{j}USDT", "long" if (i + j) % 2 else "short",
                        round(float(rng.normal(0.0, 50.0)), 1))
                    for j in range(per_hour)]
            lines.append(line(i, arm, rows))
    launch = launch_of(**{f"S{j}USDT": (2.0 if j % 2 == 0 else 400.0)
                          for j in range(per_hour)})
    return lines, launch


def two_band(n_old=200, n_young=200, hit_old=0.7, hit_young=0.4, seed=1,
             side="long", hours=40, med_shift=0.0, mean_only=False):
    """Выборы двух объявленных полос с заданными долями попаданий."""
    rng = np.random.default_rng(seed)
    out = []
    for tag, n, p, age in (("O", n_old, hit_old, 400.0),
                           ("Y", n_young, hit_young, 2.0)):
        for i in range(n):
            fav = abs(float(rng.normal(0.0, 50.0)))
            if rng.random() >= p:
                fav = -fav
            if tag == "Y":
                fav += med_shift
                if mean_only and i == 0:
                    fav += 100000.0
            got = fav if side == "long" else -fav
            out.append({"sheet": "t", "arm": "gbm",
                        "hour": TR._hour_of(T0 + (i % hours) * H),
                        "at": T0 + (i % hours) * H, "sym": f"{tag}{i}USDT",
                        "side": side, "got": got,
                        "fav": AM.favour(got, side),
                        "net": AM.favour(got, side) - 11.0, "age": age,
                        "band": PA.band_of(age)})
    return out


def dca_rec(sym, k, side="long", lev=3.0, pnl=0.02, hold_h=40):
    """Запись реплея длинной книги в форме кэша `run_paper`."""
    at = T0 - (T0 % H) + k * 6 * H
    ex = at + hold_h * H
    h0 = int(at - at % H)
    marks = [[h, pnl * (i + 1) / hold_h]
             for i, h in enumerate(range(h0, int(ex) + int(H), int(H)))]
    return {"at": at, "sym": sym, "side": side, "lev": lev,
            "state": "closed", "pnl": pnl, "exit": "тейк", "exit_ts": ex,
            "sched_end": at + 72 * H, "end_ts": at + 72 * H,
            "entry_px": 10.0, "avg": 9.8, "exit_px": 10.4, "depth": 2,
            "fav_bp": 120.0, "fwd": 60.0,
            "fills": [[at, 10.0, 0.5], [at + H, 9.6, 0.5]], "marks": marks}


# ------------------------------------------- момент решения и будущее

@test
def момент_решения_это_конец_часа():
    ln = line(3, "gbm", [row("S0USDT", "long", 10.0)])
    assert AM.decision_ts(ln) == TR.hour_end(ln["hour"]), AM.decision_ts(ln)
    assert AM.decision_ts(ln) == T0 + 3 * H + H
    assert AM.decision_ts({"hour": None}) is None
    assert AM.decision_ts({}) is None


@test
def будущее_не_меняет_прошлого():
    """Переписать `at_ts` — прошлое не должно шелохнуться.

    `at_ts` — момент ЗАПИСИ разбора, то есть будущее относительно
    решения; на ситуационном листе туда попадает вовсе момент выхода.
    Возьми механика его за момент решения — переписанное будущее
    двигало бы возраст, полосу и все числа.
    """
    lines, launch = small()
    base = AM.cells(AM.with_age(AM.choices(lines, "t")[0], launch))
    for k, mult in ((0, 900.0), (1, -900.0)):
        moved = [dict(ln, at_ts=ln["at_ts"] + mult * 86400.0)
                 for ln in lines]
        got = AM.cells(AM.with_age(AM.choices(moved, "t")[0], launch))
        assert got == base, f"будущее (сдвиг {mult} сут) сдвинуло прошлое"
    nolab = [dict(ln) for ln in lines]
    for ln in nolab:
        ln.pop("at_ts", None)
    assert AM.cells(AM.with_age(AM.choices(nolab, "t")[0], launch)) == base


# --------------------------------------------------- знак и попадание

@test
def знак_стороны_у_хода():
    assert AM.favour(100.0, "long") == 100.0
    assert AM.favour(100.0, "short") == -100.0
    assert AM.favour(-40.0, "short") == 40.0
    chs, _w = AM.choices([line(0, "gbm", [row("S0USDT", "short", -80.0)])],
                         "t")
    assert chs[0]["got"] == -80.0 and chs[0]["fav"] == 80.0, chs[0]
    # У шортов буквальное P(got > 0) и доля попаданий обязаны РАЗОЙТИСЬ:
    # в этом и была ошибка формулы заявки.
    c = AM.cell_stats([dict(chs[0])])
    assert c["hit"] == 1.0 and c["hit_raw"] == 0.0, c


@test
def ничья_не_попадание():
    assert AM.hit_share([0.0, 0.0, 1.0]) == 1.0 / 3.0
    assert AM.hit_share([-1.0, 0.0]) == 0.0
    assert AM.hit_share([]) is None


# --------------------------------------------- прочерк вместо нуля

@test
def пустая_ячейка_прочерк():
    c = AM.cell_stats([])
    assert c["n"] == 0, c
    for k in ("hit", "hit_raw", "fav_med", "fav_mean", "got_med", "got_mean",
              "net_med", "net_mean"):
        assert c[k] is None, f"{k} = {c[k]!r}, а величины нет вовсе"


@test
def отказ_вместо_пустоты():
    """Непустой вход, давший ноль наблюдений, — отказ, а не отчёт."""
    lines = [line(0, "gbm", [{"sym": "S0USDT", "side": "long", "got": None}]),
             line(1, "gbm", [])]
    try:
        AM.choices(lines, "t")
    except ValueError as e:
        assert "выборов ноль" in str(e), str(e)
    else:
        raise AssertionError("пустота выдала себя за результат")
    # пустой вход — законный ноль, отказом не является
    assert AM.choices([], "t")[0] == []


@test
def слабый_бутстрап_прочерк():
    """Годных повторов мало — интервала НЕТ, и это не пара нулей."""
    old = two_band(n_old=60, n_young=1, hours=60)[:60]
    young = [c for c in two_band(n_old=0, n_young=1, hours=60)]
    for c in young:              # молодой всего один и в СВОЁМ часе
        c["hour"] = "2026-01-01-00"
    b = AM.boot_diff(old, young, unit="часы", reps=200, seed=3)
    assert b["weak"] is True, b
    assert b["lo"] is None and b["hi"] is None and b["covers_zero"] is None, b
    assert b["used"] < 200


# ----------------------------------------------------- полосы возраста

@test
def возраст_неизвестен_своя_полоса():
    chs, _w = AM.choices([line(0, "gbm", [row("НЕТUSDT", "long", 10.0)])],
                         "t")
    got = AM.with_age(chs, {})
    assert got[0]["age"] is None and got[0]["band"] == AM.UNKNOWN, got[0]
    assert AM.band_key(None) is None, "неизвестный возраст попал в полосу"
    old, young = AM.split_bands(got, "long")
    assert not old and not young, (len(old), len(young))


@test
def полосы_вердикта_объявлены():
    """Границы взяты у `pair_age`, а не назначены здесь заново."""
    assert AM.YOUNG_MAX_D == 7.0 and AM.OLD_MIN_D == 60.0, (
        AM.YOUNG_MAX_D, AM.OLD_MIN_D)
    assert AM.YOUNG_MAX_D in PA.BAND_EDGES and AM.OLD_MIN_D in PA.BAND_EDGES
    assert AM.band_key(6.99) == AM.YOUNG and AM.band_key(7.0) is None
    assert AM.band_key(59.9) is None and AM.band_key(60.0) == AM.OLD


# ----------------------------------------------------- убийцы вердикта

@test
def порог_измеримости_кусается():
    chs = two_band(n_old=400, n_young=AM.MIN_CHOICES - 1)
    old, young = AM.split_bands(chs, "long")
    v = AM.verdict(AM.cell_stats(old), AM.cell_stats(young),
                   [AM.boot_diff(old, young, "выборы", reps=200)])
    assert v["measured"] is False and v["killer"] == 0, v
    assert v["alive"] is False
    assert str(AM.MIN_CHOICES) in v["phrase"], v["phrase"]


@test
def разность_ниже_порога_убивает():
    oc = {"n": 900, "hit": 0.50, "fav_med": 5.0, "fav_mean": 5.0}
    yc = {"n": 900, "hit": 0.47, "fav_med": 1.0, "fav_mean": 1.0}
    tight = {"unit": "выборы", "lo": 1.0, "hi": 5.0, "covers_zero": False,
             "used": 2000, "reps": 2000}
    v = AM.verdict(oc, yc, [tight, dict(tight, unit="часы")])
    assert v["killer"] == 1 and v["alive"] is False, v
    assert "+3.0 п.п." in v["phrase"], v["phrase"]


@test
def интервал_поверх_нуля_убивает():
    oc = {"n": 900, "hit": 0.60, "fav_med": 20.0, "fav_mean": 20.0}
    yc = {"n": 900, "hit": 0.50, "fav_med": 1.0, "fav_mean": 1.0}
    tight = {"unit": "выборы", "lo": 3.0, "hi": 17.0, "covers_zero": False,
             "used": 2000, "reps": 2000}
    wide = {"unit": "часы", "lo": -2.0, "hi": 21.0, "covers_zero": True,
            "used": 2000, "reps": 2000}
    v = AM.verdict(oc, yc, [tight, wide])
    assert v["killer"] == 1 and v["alive"] is False, v
    assert "часы" in v["phrase"], v["phrase"]
    # оба тесных — утверждение живёт: иначе проверка ловила бы что угодно
    assert AM.verdict(oc, yc, [tight, dict(tight, unit="часы")])["alive"]


@test
def интервала_нет_не_значит_нуля():
    """Прочерк интервала обязан убивать так же, как накрытый ноль."""
    oc = {"n": 900, "hit": 0.60, "fav_med": 20.0, "fav_mean": 20.0}
    yc = {"n": 900, "hit": 0.50, "fav_med": 1.0, "fav_mean": 1.0}
    tight = {"unit": "выборы", "lo": 3.0, "hi": 17.0, "covers_zero": False,
             "used": 2000, "reps": 2000}
    none_ = {"unit": "часы", "lo": None, "hi": None, "covers_zero": None,
             "used": 11, "reps": 2000, "weak": True}
    v = AM.verdict(oc, yc, [tight, none_])
    assert v["killer"] == 1 and v["alive"] is False, v
    assert "интервала нет" in v["phrase"], v["phrase"]


@test
def лотерея_вердикта_не_выносит():
    """Медиана хуже, среднее лучше — подпись лотереи, вердикта нет."""
    oc = {"n": 900, "hit": 0.60, "fav_med": 20.0, "fav_mean": 20.0}
    yc = {"n": 900, "hit": 0.50, "fav_med": -30.0, "fav_mean": 900.0}
    tight = {"unit": "выборы", "lo": 3.0, "hi": 17.0, "covers_zero": False,
             "used": 2000, "reps": 2000}
    v = AM.verdict(oc, yc, [tight, dict(tight, unit="часы")])
    assert v["killer"] == 2 and v["alive"] is False, v
    assert "лотереи" in v["phrase"], v["phrase"]
    # оба хуже — вердикт выносится
    ok = AM.verdict(oc, dict(yc, fav_mean=-30.0),
                    [tight, dict(tight, unit="часы")])
    assert ok["alive"] is True and ok["killer"] is None, ok


@test
def фраза_вердикта_из_чисел():
    """Вердиктовая фраза выводится из чисел, а не стоит рядом с ними."""
    oc = {"n": 900, "hit": 0.60, "fav_med": 20.0, "fav_mean": 20.0}
    yc = {"n": 900, "hit": 0.50, "fav_med": 1.0, "fav_mean": 1.0}
    tight = {"unit": "выборы", "lo": 3.0, "hi": 17.0, "covers_zero": False,
             "used": 2000, "reps": 2000}
    a = AM.verdict(oc, yc, [tight, dict(tight, unit="часы")])["phrase"]
    b = AM.verdict(dict(oc, hit=0.75), yc,
                   [tight, dict(tight, unit="часы")])["phrase"]
    assert a != b, "фраза не изменилась вслед за числом"
    assert "60.0 %" in a and "75.0 %" in b, (a, b)


# -------------------------------------------- час как единица счёта

@test
def час_единица_независимости():
    """Выборы одного часа делят рынок: интервал по часам обязан быть шире.

    Данные нарочно склеены часом: внутри часа исход полосы у всех один,
    а у двух полос он свой. Тогда независимых наблюдений ровно столько,
    сколько ЧАСОВ, и пересчёт по выборам врёт в сторону узости — ровно
    тот дефект, из-за которого перекрытие раздувало t втрое.
    """
    rng = np.random.default_rng(11)
    chs = []
    for h in range(30):
        signs = {"O": 1.0 if rng.random() < 0.5 else -1.0,
                 "Y": 1.0 if rng.random() < 0.5 else -1.0}
        for j in range(20):
            for tag, age in (("O", 400.0), ("Y", 2.0)):
                fav = signs[tag] * abs(float(rng.normal(0.0, 40.0)))
                chs.append({"sheet": "t", "arm": "gbm",
                            "hour": TR._hour_of(T0 + h * H),
                            "at": T0 + h * H, "sym": f"{tag}{h}_{j}USDT",
                            "side": "long", "got": fav, "fav": fav,
                            "net": fav - 11.0, "age": age,
                            "band": PA.band_of(age)})
    old, young = AM.split_bands(chs, "long")
    bc = AM.boot_diff(old, young, "выборы", reps=400, seed=5)
    bh = AM.boot_diff(old, young, "часы", reps=400, seed=5)
    assert bc["lo"] is not None and bh["lo"] is not None, (bc, bh)
    assert (bh["hi"] - bh["lo"]) > (bc["hi"] - bc["lo"]), (
        f"по часам {bh['hi'] - bh['lo']:.2f}, по выборам "
        f"{bc['hi'] - bc['lo']:.2f} — час не стал единицей")


@test
def единица_бутстрапа_объявлена():
    chs = two_band(n_old=50, n_young=50)
    old, young = AM.split_bands(chs, "long")
    try:
        AM.boot_diff(old, young, unit="как-нибудь", reps=10)
    except ValueError as e:
        assert "единица" in str(e), str(e)
    else:
        raise AssertionError("необъявленная единица посчиталась молча")


# ------------------------------------------------- калибровочная пара

@test
def калибровка_подсадка_ложится():
    """Подделка обязана сперва доказать, что легла, — числом."""
    chs = two_band(n_old=200, n_young=200, side="short")
    sp, n = AM.spike(chs, 200.0)
    assert n == 200, n
    y0 = [c for c in chs if AM.band_key(c["age"]) == AM.YOUNG]
    y1 = [c for c in sp if AM.band_key(c["age"]) == AM.YOUNG]
    assert len(y0) == 200 and len(y1) == 200, (len(y0), len(y1))
    assert all(abs(b["fav"] - a["fav"] - 200.0) < 1e-6
               for a, b in zip(y0, y1)), "ход в пользу не сдвинулся"
    # у шорта сырой ход обязан уйти ВНИЗ: подсадка идёт В ПОЛЬЗУ сделки
    assert all(abs(b["got"] - a["got"] + 200.0) < 1e-6
               for a, b in zip(y0, y1)), "сырой ход двинут не по стороне"
    o0 = [c for c in chs if AM.band_key(c["age"]) == AM.OLD]
    o1 = [c for c in sp if AM.band_key(c["age"]) == AM.OLD]
    assert all(a["fav"] == b["fav"] for a, b in zip(o0, o1)), "тронуты старые"


@test
def калибровка_подсадка_переворачивает():
    chs = two_band(n_old=300, n_young=300, hit_old=0.7, hit_young=0.4)
    old, young = AM.split_bands(chs, "long")
    base = AM._diff_pp([c["fav"] for c in old], [c["fav"] for c in young])
    sp, n = AM.spike(chs, 100000.0)
    so, sy = AM.split_bands(sp, "long")
    got = AM._diff_pp([c["fav"] for c in so], [c["fav"] for c in sy])
    assert base > 0 and got < 0, (base, got, n)


@test
def калибровка_перемешивание_внутри_часа():
    """Возраста мешаются ВНУТРИ часа: состав часа обязан устоять."""
    chs = two_band(n_old=300, n_young=300, hours=25)
    mixed, moved = AM.shuffle_ages(chs, seed=4)
    assert moved > 0, "подделка НЕ ЛЕГЛА: полосу не сменил никто"
    for a, b in zip(chs, mixed):
        assert a["fav"] == b["fav"] and a["hour"] == b["hour"], (a, b)
    by_a, by_b = {}, {}
    for c in chs:
        by_a.setdefault(c["hour"], []).append(c["age"])
    for c in mixed:
        by_b.setdefault(c["hour"], []).append(c["age"])
    assert set(by_a) == set(by_b)
    for h in by_a:
        assert sorted(by_a[h]) == sorted(by_b[h]), (
            f"час {h}: состав возрастов изменился — перемешали не внутри "
            "часа, и замер стал про календарь")


@test
def калибровка_перемешивание_уравнивает():
    chs = two_band(n_old=400, n_young=400, hit_old=0.75, hit_young=0.35,
                   hours=30)
    old, young = AM.split_bands(chs, "long")
    было = AM.boot_diff(old, young, "выборы", reps=300, seed=6)
    assert было["covers_zero"] is False, было
    mixed, moved = AM.shuffle_ages(chs, seed=6)
    mo, my = AM.split_bands(mixed, "long")
    стало = AM.boot_diff(mo, my, "выборы", reps=300, seed=6)
    assert стало["covers_zero"] is True, стало
    assert moved > 0


@test
def подсаженный_режим_находится():
    """Первая нога пары: меру видно там, где эффект подсажен."""
    lines, launch = RM.synth(n_hours=90, per_hour=8, effect_pp=0.30)
    chs = AM.with_age(AM.choices(lines, "синтетика")[0], launch)
    s = RM.step1(chs, log=quiet, reps=300)
    for side in AM.SIDES:
        v = s["sides"][side]["verdict"]
        assert v["alive"] is True, (side, v)


@test
def на_шуме_молчит():
    """Вторая нога пары: на случайном блуждании мера обязана молчать."""
    lines, launch = RM.synth(n_hours=90, per_hour=8, effect_pp=0.0)
    chs = AM.with_age(AM.choices(lines, "синтетика")[0], launch)
    s = RM.step1(chs, log=quiet, reps=300)
    for side in AM.SIDES:
        v = s["sides"][side]["verdict"]
        assert v["alive"] is False, (side, v)


# --------------------------------------------- фильтр возраста и сторона

@test
def сторона_фильтра_не_трогает_чужую():
    """Фильтр видит СВОЮ сторону; чужие записи проходят нетронутыми."""
    launch = launch_of(МОЛОДОЙUSDT=2.0, СТАРЫЙUSDT=400.0)
    recs = [{"sym": "МОЛОДОЙUSDT", "at": T0, "side": "long"},
            {"sym": "МОЛОДОЙUSDT", "at": T0, "side": "short"},
            {"sym": "СТАРЫЙUSDT", "at": T0, "side": "long"},
            {"sym": "СТАРЫЙUSDT", "at": T0, "side": "short"}]
    keep, why = AM.pick_side(recs, launch, 7.0, side="long")
    syms = sorted((r["sym"], r["side"]) for r in keep)
    assert syms == [("МОЛОДОЙUSDT", "short"), ("СТАРЫЙUSDT", "long"),
                    ("СТАРЫЙUSDT", "short")], syms
    assert why["другая сторона"] == 2 and why["моложе порога"] == 1, why
    # без стороны — как у хозяина: фильтруется всё
    keep2, _w = AM.pick_side(recs, launch, 7.0)
    assert len(keep2) == 2, keep2


@test
def контроль_размера_из_своей_стороны():
    """Случайный контроль берёт столько же и ИЗ СВОЕЙ стороны."""
    days = {f"L{i}USDT": 400.0 for i in range(20)}
    days.update({f"S{i}USDT": 400.0 for i in range(20)})
    days["МОЛОДОЙUSDT"] = 1.0
    launch = launch_of(**days)
    recs = ([{"sym": f"L{i}USDT", "at": T0, "side": "long"}
             for i in range(20)]
            + [{"sym": f"S{i}USDT", "at": T0, "side": "short"}
               for i in range(20)]
            + [{"sym": "МОЛОДОЙUSDT", "at": T0, "side": "long"}])
    keep, _w = AM.pick_side(recs, launch, 7.0, side="long")
    n_long = sum(1 for r in keep if r["side"] == "long")
    assert n_long == 20 and len(keep) == 40, (n_long, len(keep))
    rnd, why = AM.pick_side(recs, launch, 7.0, side="long",
                            n_random=n_long)
    assert sum(1 for r in rnd if r["side"] == "long") == n_long
    assert sum(1 for r in rnd if r["side"] == "short") == 20, why
    small_, _w = AM.pick_side(recs, launch, 7.0, side="long", n_random=5)
    assert sum(1 for r in small_ if r["side"] == "long") == 5
    assert sum(1 for r in small_ if r["side"] == "short") == 20


@test
def ничья_контроля_фильтру_не_в_зачёт():
    assert AM.beat_share(2.0, [1.0, 2.0, 3.0, 4.0]) == 0.75
    assert AM.beat_share(2.0, [1.0, 1.5]) == 0.0
    assert AM.beat_share(None, [1.0]) is None
    assert AM.beat_share(2.0, []) is None


@test
def отношение_без_просадки_прочерк():
    assert AM.ratio_of({"final": 0.2, "max_dd": -0.1}) == 2.0
    assert AM.ratio_of({"final": 0.2, "max_dd": 0.0}) is None
    assert AM.ratio_of({"final": None, "max_dd": -0.1}) is None
    assert AM.ratio_of(None) is None


@test
def вердикт_переноса_из_чисел():
    rows = [{"key": "safe", "beat_ratio": 0.02},
            {"key": "optimal", "beat_ratio": 0.33},
            {"key": "aggr", "beat_ratio": 0.01}]
    v = AM.transfer_verdict(rows, seeds=200)
    assert v["alive"] is False and v["worst_key"] == "optimal", v
    assert "33.0 %" in v["phrase"] and "200 зёрен" in v["phrase"], v["phrase"]
    ok = AM.transfer_verdict([dict(r, beat_ratio=0.02) for r in rows],
                             seeds=200)
    assert ok["alive"] is True, ok
    # число зёрен приходит параметром, а не стареет литералом
    assert "3 зёрен" in AM.transfer_verdict(rows, seeds=3)["phrase"]
    miss = AM.transfer_verdict(rows[:2] + [{"key": "aggr",
                                            "beat_ratio": None}])
    assert miss["measured"] is False and miss["alive"] is False, miss


# ------------------------------------------------ дорога до книги и отказы

@test
def книга_считается_чужим_ядром():
    """Деньги длинной книги — `run_paper`, своей симуляции здесь нет."""
    recs = [dca_rec(f"A{i}USDT", i, pnl=(0.03 if i % 3 else -0.05))
            for i in range(24)]
    ctx = {"error": "издержки в проверке не считаются"}
    c = RM.book_cell(recs, "safe", 10000.0, ctx)
    assert c["n"] == 24, c
    assert c["usd"] is not None and c["day_median"] is not None, c
    assert c["ratio"] == AM.ratio_of({"final": c["final"],
                                      "max_dd": c["max_dd"]}), c
    assert c["usd_wo_top"] is not None and c["top_sym"], c
    assert c["tail"] == 0 and c["tail_share"] == 0.0, c
    tailed = [dict(r, exit=PA.TAIL_EXITS[0]) for r in recs]
    ct = RM.book_cell(tailed, "safe", 10000.0, ctx)
    assert ct["tail"] == 24 and ct["tail_share"] == 1.0, ct


@test
def перенос_считает_обе_ветки():
    """Шаг 2: фильтр возраста и контроль того же размера — одной дорогой."""
    launch = launch_of(**{f"A{i}USDT": (2.0 if i < 4 else 400.0)
                          for i in range(24)})
    cache = {}
    for i in range(24):
        r = dca_rec(f"A{i}USDT", i, pnl=(0.03 if i % 3 else -0.05))
        cache[(tuple(RM.RP.RULERS["safe"]), r["sym"], r["at"])] = r
    s = RM.step2(launch, dep=10000.0, seeds=4, log=quiet,
                 ctx={"error": "издержки в проверке не считаются"},
                 long_cache=cache, keys=["safe"])
    assert not s.get("error"), s
    r0 = s["rows"][0]
    assert r0["offered"] == 24 and r0["cut"] > 0, r0
    assert r0["kept"] == 24 - r0["cut"], r0
    assert r0["no_at"] == 0, r0
    assert s["min_days"] == RM.R.min_age_days(RM.R.PAIR_ORDER[0]), s
    assert s["verdict"]["seeds"] == 4, s["verdict"]


@test
def справочник_пуст_отказ():
    """Пустой справочник — отказ, а не запись целиком в «неизвестен»."""
    try:
        RM.run(log=quiet, launch={}, transfer=False)
    except ValueError as e:
        assert "справочник" in str(e), str(e)
    else:
        raise AssertionError("пустой справочник выдал себя за результат")


@test
def повтор_выбора_не_удваивает():
    """Один выбор дважды удвоил бы вес часа в бутстрапе."""
    r = row("S0USDT", "long", 30.0)
    chs, why = AM.choices([line(0, "gbm", [r, dict(r)]),
                           line(0, "nn", [r])], "t")
    assert len(chs) == 2, [(c["arm"], c["sym"]) for c in chs]
    assert why["повторов"] == 1, why


@test
def лист_без_журнала_не_ноль():
    """Нет файла — причина словами, а не пустая ячейка листа."""
    got, why = RM.load_choices(log=quiet, paths={"h4": "/нет/такого.jsonl"},
                               sheets=(("h4", "model"),
                                       ("sit", "model_sit")))
    assert "нет файла" in (why.get("h4") or {}), why
    assert got, "второй лист не прочитан"


def main():
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as e:                                # noqa: BLE001
            failed.append((fn.__name__, f"{type(e).__name__}: {e}"[:90]))
    print(f"проверок {len(TESTS)}, прошло {len(TESTS) - len(failed)}, "
          f"провалов {len(failed)}")
    for name, err in failed:
        print(f"ПРОВАЛ {name}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
