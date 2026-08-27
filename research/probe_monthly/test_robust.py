#!/usr/bin/env python3
"""
Тесты трёх замеров устойчивости месячного зонда.

Столпы: сцепление префиксом различает ДЕЛИСТИНГ и ДЫРУ (числом);
поправка Ньюи–Уэста проверена точным значением, посчитанным
независимо, и обязана кусаться на автокоррелированном ряде; замер
выживших ловит имя, которое базовая рука выбрасывает.

    python3 research/probe_monthly/test_robust.py
"""

import io
import contextlib
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import robust as RB                                       # noqa: E402
import probe as P                                         # noqa: E402
import test_probe as TP                                   # noqa: E402
import nulls as N                                         # noqa: E402
import run_d1 as R                                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def counters():
    return {k: 0 for k in ("нет прошлого для сигнала",
                           "нет будущего для форварда",
                           "дециль вырождается")}


def test_newey_west_exact_number():
    """Точное значение, посчитанное независимо (ряд 1,2,3,4; лаг 1).

    mean = 2.5; g0 = 1.25; g1 = 0.3125; s = g0 + 2·(1−1/2)·g1 = 1.5625;
    t_nw = 2.5 / sqrt(1.5625/4) = 4.0; наивный = 2.5/(sqrt(5/3)/2)
    = 3.873."""
    mean, tn, tw, n = RB.newey_west_t([1.0, 2.0, 3.0, 4.0], lag=1)
    check("среднее", abs(mean - 2.5) < 1e-12, f"{mean}")
    check("t Ньюи–Уэста равен 4.0", abs(tw - 4.0) < 1e-9, f"{tw}")
    check("наивный t равен 3.873", abs(tn - 3.8730) < 1e-3, f"{tn}")
    check("n верно", n == 4, f"{n}")


def test_newey_west_bites_on_autocorrelation():
    """На положительно автокоррелированном ряде NW ОБЯЗАН быть меньше
    наивного; на белом шуме — близок к нему.

    Это и есть свойство, ради которого поправка нужна: перекрывающиеся
    месячные окна автокоррелированы по построению."""
    rng = np.random.default_rng(11)
    e = rng.normal(0.0, 1.0, 3000)
    ar = np.zeros(3000)
    for i in range(1, 3000):
        ar[i] = 0.9 * ar[i - 1] + e[i]
    ar = ar + 0.5
    _, tn_a, tw_a, _ = RB.newey_west_t(ar, lag=29)
    check("на автокорреляции NW сильно меньше наивного",
          abs(tw_a) < 0.6 * abs(tn_a), f"{tw_a} против {tn_a}")
    white = e + 0.05
    _, tn_w, tw_w, _ = RB.newey_west_t(white, lag=29)
    check("на белом шуме NW близок к наивному",
          abs(tw_w - tn_w) < 0.35 * abs(tn_w) + 0.2,
          f"{tw_w} против {tn_w}")


def make_vec(n_days=400, seed=7):
    return TP.synth_vec(n_days=n_days, seed=seed)


def test_chain_alive_tells_delisting_from_hole():
    """Три статуса числом: целое, оборванный хвост, дыра в середине."""
    vec = make_vec(n_days=120)
    t = sorted(vec)[60]
    days = [P.shift(t, 0), P.shift(t, 10), P.shift(t, 20)]
    base = vec[t]["names"]
    # имя 0 — целое; имя 1 — хвост оборван со второго кирпича;
    # имя 2 — дыра во втором кирпиче, третий на месте
    vec[days[1]]["fwd"][10][1] = np.nan
    vec[days[2]]["fwd"][10][1] = np.nan
    vec[days[1]]["fwd"][10][2] = np.nan
    got = RB.chain_alive(vec, {}, base, days)
    check("сцепление посчитано", got is not None, "")
    total, cnt, status = got
    check("целое имя: статус 2, три кирпича",
          status[0] == 2 and cnt[0] == 3, f"{status[0]} {cnt[0]}")
    want1 = float(vec[days[0]]["fwd"][10][1])
    check("делистинг: статус 1, сумма ПЕРВОГО кирпича",
          status[1] == 1 and cnt[1] == 1
          and abs(total[1] - want1) < 1e-12,
          f"{status[1]} {cnt[1]} {total[1]} против {want1}")
    check("дыра: статус 0 и NaN",
          status[2] == 0 and np.isnan(total[2]),
          f"{status[2]} {total[2]}")


def test_missing_first_brick_is_not_alive():
    vec = make_vec(n_days=120)
    t = sorted(vec)[60]
    days = [P.shift(t, 0), P.shift(t, 10), P.shift(t, 20)]
    vec[days[0]]["fwd"][10][3] = np.nan
    total, cnt, status = RB.chain_alive(vec, {}, vec[t]["names"], days)
    check("нет первого кирпича — имени нет",
          status[3] == 0 and np.isnan(total[3]), f"{status[3]}")


def test_alive_arm_keeps_what_base_drops():
    """Базовая рука выбрасывает делистнутое имя, живая — держит.

    Хвост роняется у имён с ЭКСТРЕМАЛЬНЫМ сигналом — так и бывает на
    рынке (делистятся упавшие, а они же на краю ранжирования), и
    только там дефект виден: имя со средним сигналом в дециль не
    попадает, и его выпадение ничего не меняет. Первая версия
    фикстуры роняла первые десять имён по индексу — базовая рука
    честно выбрасывала 120 имён, а нетто рук совпадало до нуля, и
    проверка проходила бы на сломанном коде."""
    vec = make_vec(n_days=400)
    dates = sorted(vec)
    cut = dates[::30]
    cache = {}
    for t in cut:
        sig = P.build_signal(vec, cache, t, 30)
        if sig is None:
            continue
        order = np.argsort(np.where(np.isfinite(sig), sig, 0.0))
        edge = list(order[:3]) + list(order[-3:])
        for d in (P.shift(t, 10), P.shift(t, 20)):
            if d in vec:
                idx = P.name_index(vec, d, cache)
                for i in edge:
                    j = idx.get(vec[t]["names"][i])
                    if j is not None:
                        vec[d]["fwd"][10][j] = np.nan
    s = RB.survivorship(vec, {}, cut, 30, 30, counters())
    check("замер собрался", s is not None, "")
    check("базовая рука выбрасывала имена",
          s["dropped_by_base_total"] > 0,
          f"{s['dropped_by_base_total']}")
    check("руки различаются", s["diff_mean_bp"] != 0.0,
          f"{s['diff_mean_bp']}")
    check("оборванные ноги посчитаны по сторонам",
          s["partial_long_per_section"] + s["partial_short_per_section"]
          > 0, f"{s}")


def test_halves_split_covers_both():
    vec = make_vec(n_days=400)
    hv = RB.halves(vec, {}, sorted(vec), 30, 30, counters())
    check("обе половины посчитаны",
          set(hv) == {"первая", "вторая"}, f"{sorted(hv)}")
    check("периоды не пересекаются",
          hv["первая"]["to"] < hv["вторая"]["from"],
          f"{hv['первая']['to']} / {hv['вторая']['from']}")


def test_overlap_null_calibration():
    """Ключевая калибровка: на подсаженном возврате t по NW большой, на
    перемешанном сигнале — около ноля. Без неё поправке верить нельзя.
    """
    vec = make_vec(n_days=400)
    dates = sorted(vec)
    real = RB.overlapping(vec, {}, dates, 30, 30, counters())
    check("реальный NW t заметно положителен",
          real is not None and real["t_nw"] > 2.0, f"{real}")
    check("наивный t выше NW (перекрытие раздувает)",
          real["t_naive"] > real["t_nw"],
          f"{real['t_naive']} против {real['t_nw']}")
    nulls = []
    for s in (1, 2, 3):
        got = RB.overlapping(vec, {}, dates, 30, 30, counters(), seed=s)
        if got and got["t_nw"] is not None:
            nulls.append(got["t_nw"])
    check("нуль по NW около ноля",
          nulls and abs(float(np.mean(nulls))) < RB.NULL_T_MAX,
          f"{nulls}")


def test_verdict_phrase_follows_numbers():
    base = {"survivorship": {P.MAIN_CELL: {
                "diff_mean_bp": -20.0, "base_mean_bp": 90.0,
                "alive_mean_bp": 70.0}},
            "overlap": {P.MAIN_CELL: {"t_nw": 3.1, "t_naive": 9.0}},
            "halves": {P.MAIN_CELL: {
                "первая": {"mean_bp": 80.0},
                "вторая": {"mean_bp": 60.0}}},
            "nw_calibrated": True}
    v = RB.verdict_phrase(base)
    check("смещение названо съеданием", "съедает 20" in v, v)
    check("предъявимость названа по порогу", "предъявимы" in v, v)
    check("устойчивость знака названа", "знак держится" in v, v)

    flip = json.loads(json.dumps(base))
    flip["halves"][P.MAIN_CELL]["вторая"]["mean_bp"] = -40.0
    check("переворот знака назван",
          "ПЕРЕВОРАЧИВАЕТСЯ" in RB.verdict_phrase(flip),
          RB.verdict_phrase(flip))

    dead = json.loads(json.dumps(base))
    dead["overlap"][P.MAIN_CELL]["t_nw"] = 1.2
    check("низкий t назван отсутствием бюджета",
          "бюджета доказательства нет" in RB.verdict_phrase(dead),
          RB.verdict_phrase(dead))

    bad = json.loads(json.dumps(base))
    bad["nw_calibrated"] = False
    check("проваленная калибровка запрещает читать t",
          "НЕ прошла калибровку" in RB.verdict_phrase(bad),
          RB.verdict_phrase(bad))
    check("нет замеров — нет фразы",
          "фразы нет" in RB.verdict_phrase({}), "")


def run_main(vdir, out):
    argv, pub, vd = sys.argv, R.publish, N.VECTORS
    R.publish = lambda msg: None
    N.VECTORS = vdir
    sys.argv = ["robust.py", "--interval", "1m", "--out", out,
                "--tag", "t", "--no-publish"]
    try:
        RB.main()
    finally:
        sys.argv, R.publish, N.VECTORS = argv, pub, vd
    return json.load(open(os.path.join(out, "MONTHLY-robust-t.json"),
                          encoding="utf-8"))


def test_end_to_end():
    tmp = tempfile.mkdtemp()
    try:
        vdir = os.path.join(tmp, "v")
        TP.write_vectors(make_vec(n_days=400), vdir)
        out = os.path.join(tmp, "out")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            art = run_main(vdir, out)
        check("главная ячейка во всех трёх замерах",
              P.MAIN_CELL in art["survivorship"]
              and P.MAIN_CELL in art["overlap"]
              and art["halves"].get(P.MAIN_CELL), f"{sorted(art)}")
        check("калибровка нуля прошла", art["nw_calibrated"],
              f"{art['null_t_nw']}")
        md = open(os.path.join(out, "MONTHLY-robust-t.md"),
                  encoding="utf-8").read()
        check("отчёт несёт все три секции",
              "Смещение выживших" in md and "Ньюи" in md
              and "половинам истории" in md, "")
        check("отчёт называет статус калибровки",
              "ПРОЙДЕНА" in md or "ПРОВАЛЕНА" in md, "")
        check("отчёт говорит, что funding здесь не вычтен",
              "funding здесь не вычтен" in md, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("Ньюи–Уэст")
    test_newey_west_exact_number()
    test_newey_west_bites_on_autocorrelation()
    print("сцепление и выжившие")
    test_chain_alive_tells_delisting_from_hole()
    test_missing_first_brick_is_not_alive()
    test_alive_arm_keeps_what_base_drops()
    print("половины и калибровка")
    test_halves_split_covers_both()
    test_overlap_null_calibration()
    print("фраза и сквозной прогон")
    test_verdict_phrase_follows_numbers()
    test_end_to_end()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
