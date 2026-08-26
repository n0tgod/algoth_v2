#!/usr/bin/env python3
"""
Тесты зонда месячного горизонта.

Главная пара — калибровочная: на синтетике с ИЗВЕСТНЫМ месячным
возвратом (уровень AR(1), телескоп сцепления точный) зонд обязан дать
высокий IC при нуле около ноля, а на случайном блуждании — ноль оба.
Без этой пары отрицательный результат не значил бы ничего.

Второй столп — тождества сцепления числом: сигнал k=30 равен минус
сумме трёх прошлых кирпичей, форвард h=30 — сумме трёх будущих, и обе
меры ИНВАРИАНТНЫ к перетасовке имён между датами (выравнивание по
имени, не по индексу — класс дефекта basket_spread §5.2).

    python3 research/probe_monthly/test_probe.py
"""

import io
import contextlib
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import probe as P                                         # noqa: E402
import nulls as N                                         # noqa: E402
import run_d1 as R                                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def synth_vec(n_days=400, n_names=60, mode="revert", seed=7,
              shuffle_names=False):
    """Векторы формата R2 на ежедневных датах.

    Уровень L_i(t): AR(1) с ρ=0.9 (возврат — месячные изменения
    антикоррелированы) либо случайное блуждание. Кирпич согласован
    телескопом: fwd10(t) = L(t+10) − L(t), сигнал R2
    sig14(t) = −(L(t) − L(t−14)). NaN и перетасовка имён — по флагам.
    """
    rng = np.random.default_rng(seed)
    T = n_days + 140
    eps = rng.normal(0.0, 0.02, size=(T, n_names))
    if mode == "revert":
        L = np.zeros((T, n_names))
        for t in range(1, T):
            L[t] = 0.9 * L[t - 1] + eps[t]
    else:
        L = np.cumsum(eps, axis=0)
    d0 = date(2024, 1, 1)
    base = [f"A{i:03d}" for i in range(n_names)]
    vec = {}
    for t in range(110, 110 + n_days):
        day = (d0 + timedelta(days=t)).isoformat()
        order = (rng.permutation(n_names) if shuffle_names
                 else np.arange(n_names))
        vec[day] = {
            "names": [base[i] for i in order],
            "sig": {14: (-(L[t] - L[t - 14]))[order].copy()},
            "fwd": {10: (L[t + 10] - L[t])[order].copy()},
        }
    return vec


def test_signal_chain_identity():
    """Сигнал k=30 равен минус сумме трёх прошлых кирпичей — числом."""
    vec = synth_vec(n_days=120)
    cache = {}
    t = sorted(vec)[60]
    sig = P.build_signal(vec, cache, t, 30)
    want = -(np.asarray(vec[P.shift(t, -30)]["fwd"][10])
             + np.asarray(vec[P.shift(t, -20)]["fwd"][10])
             + np.asarray(vec[P.shift(t, -10)]["fwd"][10]))
    check("сигнал k=30 — телескоп трёх кирпичей",
          sig is not None and np.allclose(sig, want, atol=1e-12),
          f"{None if sig is None else float(np.abs(sig - want).max())}")


def test_forward_chain_identity():
    vec = synth_vec(n_days=120)
    cache = {}
    t = sorted(vec)[10]
    fwd = P.build_forward(vec, cache, t, 30)
    want = (np.asarray(vec[t]["fwd"][10])
            + np.asarray(vec[P.shift(t, 10)]["fwd"][10])
            + np.asarray(vec[P.shift(t, 20)]["fwd"][10]))
    check("форвард h=30 — сумма трёх кирпичей вперёд",
          fwd is not None and np.allclose(fwd, want, atol=1e-12),
          f"{None if fwd is None else float(np.abs(fwd - want).max())}")


def test_alignment_is_by_name():
    """Перетасовка имён между датами НЕ меняет меру ячейки.

    Состав сечения реальных векторов различается от даты к дате;
    позиционное сцепление молча сложило бы остатки разных активов и
    дало бы другое число — этот тест его и ловит."""
    plain = synth_vec(n_days=200, seed=11)
    shuf = synth_vec(n_days=200, seed=11, shuffle_names=True)
    counters = {k: 0 for k in ("нет прошлого для сигнала",
                               "нет будущего для форварда",
                               "сечение вырождено", "дециль вырождается")}
    dates = sorted(plain)[::30]
    pa = P.build_pairs(plain, {}, dates, 30, 30, dict(counters))
    pb = P.build_pairs(shuf, {}, dates, 30, 30, dict(counters))
    a = P.measure_pairs(plain, pa, dict(counters))
    b = P.measure_pairs(shuf, pb, dict(counters))
    check("мера инвариантна к перетасовке имён",
          a is not None and b is not None
          and abs(a["ic_mean"] - b["ic_mean"]) < 1e-9
          and abs(a["spread_mean_bp"] - b["spread_mean_bp"]) < 1e-6,
          f"{a and a['ic_mean']} против {b and b['ic_mean']}")


def test_missing_day_breaks_the_chain():
    """Дата вне сетки → None, а не сцепление через дыру (класс L2)."""
    vec = synth_vec(n_days=120)
    t = sorted(vec)[60]
    del vec[P.shift(t, -20)]
    got = P.build_signal(vec, {}, t, 30)
    check("дыра в кирпичах — нет сигнала", got is None, f"{got}")


def test_nan_name_stays_nan():
    """NaN в одном кирпиче заражает имя целиком — пропуск, не ноль."""
    vec = synth_vec(n_days=120)
    t = sorted(vec)[60]
    vec[P.shift(t, -20)]["fwd"][10][3] = np.nan
    sig = P.build_signal(vec, {}, t, 30)
    check("NaN кирпича — NaN сцепления",
          sig is not None and np.isnan(sig[3])
          and np.isfinite(sig[4]), f"{sig is not None and sig[3]}")


def test_turnover():
    a = {"x": 0.5, "y": -0.5}
    check("одинаковые книги — оборот 0", P.turnover(a, dict(a)) == 0.0,
          "")
    check("полная смена — оборот 2",
          P.turnover(a, {"p": 0.5, "q": -0.5}) == 2.0, "")


def test_calibration_finds_planted_reversion():
    """Зонд обязан НАХОДИТЬ месячный возврат, который в данных есть,
    и не находить его на случайном блуждании; нуль ≈ 0 в обоих."""
    counters = {k: 0 for k in ("нет прошлого для сигнала",
                               "нет будущего для форварда",
                               "сечение вырождено", "дециль вырождается")}
    rev = synth_vec(n_days=400, mode="revert")
    rw = synth_vec(n_days=400, mode="rw")
    dr = sorted(rev)[::30]
    dw = sorted(rw)[::30]
    p_rev = P.build_pairs(rev, {}, dr, 30, 30, dict(counters))
    p_rw = P.build_pairs(rw, {}, dw, 30, 30, dict(counters))
    a = P.measure_pairs(rev, p_rev, dict(counters))
    b = P.measure_pairs(rw, p_rw, dict(counters))
    check("подсаженный возврат найден (IC > 0.15)",
          a is not None and a["ic_mean"] > 0.15, f"{a and a['ic_mean']}")
    check("на случайном блуждании ноль (|IC| < 0.1)",
          b is not None and abs(b["ic_mean"]) < 0.1,
          f"{b and b['ic_mean']}")
    nz = P.run_nulls(rev, {"k30_h30": p_rev}, dict(counters))
    check("нуль на живом возврате около ноля",
          abs(nz["k30_h30"]["ic_mean_seeds"]) < 0.08,
          f"{nz['k30_h30']}")
    nz2 = P.run_nulls(rev, {"k30_h30": p_rev}, dict(counters))
    check("нуль воспроизводим",
          nz == nz2, f"{nz} против {nz2}")


def test_verdict_phrase_follows_numbers():
    both = {"net_mean_bp": 30.0, "net_median_bp": 25.0,
            "cost_mean_bp": 8.0, "spread_mean_bp": 76.0}
    split = {"net_mean_bp": -5.0, "net_median_bp": 12.0,
             "cost_mean_bp": 8.0, "spread_mean_bp": 6.0}
    dead = {"net_mean_bp": -9.0, "net_median_bp": -4.0,
            "cost_mean_bp": 8.0, "spread_mean_bp": -2.0}
    check("обе меры в плюс — «живёт»",
          "живёт по обеим" in P.verdict_phrase(both),
          P.verdict_phrase(both))
    check("расхождение знака названо хвостом",
          "подпись хвоста" in P.verdict_phrase(split),
          P.verdict_phrase(split))
    check("обе в минус — «не окупается»",
          "не окупается" in P.verdict_phrase(dead),
          P.verdict_phrase(dead))
    check("нет ячейки — нет фразы",
          "не измерена" in P.verdict_phrase(None), "")


def write_vectors(vec, vdir, interval="1m"):
    os.makedirs(vdir, exist_ok=True)
    dump = {}
    for d, v in vec.items():
        dump[d] = {"names": v["names"],
                   "sig": {str(k): np.asarray(x).tolist()
                           for k, x in v["sig"].items()},
                   "fwd": {str(h): np.asarray(x).tolist()
                           for h, x in v["fwd"].items()}}
    with open(os.path.join(vdir, f"{interval}_synth.json"), "w",
              encoding="utf-8") as f:
        json.dump(dump, f)


def run_main(vdir, out):
    argv, pub, vd = sys.argv, R.publish, N.VECTORS
    R.publish = lambda msg: None
    N.VECTORS = vdir
    sys.argv = ["probe.py", "--interval", "1m", "--out", out,
                "--tag", "t", "--no-publish"]
    try:
        P.main()
    finally:
        sys.argv, R.publish, N.VECTORS = argv, pub, vd
    return json.load(open(os.path.join(out, "MONTHLY-t.json"),
                          encoding="utf-8"))


def test_end_to_end():
    """Сквозной прогон настоящим main() на подсаженном возврате."""
    tmp = tempfile.mkdtemp()
    try:
        write_vectors(synth_vec(n_days=400), os.path.join(tmp, "v"))
        out = os.path.join(tmp, "out")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            art = run_main(os.path.join(tmp, "v"), out)
        main_cell = art["cells"].get(art["main_cell"])
        check("главная ячейка измерена", main_cell is not None,
              f"{sorted(art['cells'])}")
        check("все восемь ячеек измерены", len(art["cells"]) == 8,
              f"{sorted(art['cells'])}")
        v = art["verdict"]
        ok = ("живёт по обеим" in v) == (
            main_cell["net_mean_bp"] > 0
            and main_cell["net_median_bp"] > 0)
        check("фраза согласована с числами", ok,
              f"{main_cell['net_mean_bp']}/{main_cell['net_median_bp']}"
              f" — {v}")
        md = open(os.path.join(out, "MONTHLY-t.md"),
                  encoding="utf-8").read()
        check("отчёт несёт нуль и оговорку про β",
              "перестановка сигнала" in md.lower()
              or "Нуль 1" in md, "")
        check("отчёт несёт оговорку про funding",
              "funding" in md, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_run_names_reasons():
    """Пустой прогон печатает причины (урок первого смоука calm)."""
    tmp = tempfile.mkdtemp()
    try:
        vec = synth_vec(n_days=60)
        for d in vec:
            vec[d]["fwd"][10][:] = np.nan
        write_vectors(vec, os.path.join(tmp, "v"))
        out = os.path.join(tmp, "out")
        buf = io.StringIO()
        raised = False
        try:
            with contextlib.redirect_stdout(buf):
                run_main(os.path.join(tmp, "v"), out)
        except SystemExit:
            raised = True
        check("пустой прогон падает", raised, "прошёл")
        check("причина в логе", "сечение вырождено" in buf.getvalue(),
              buf.getvalue()[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("тождества сцепления")
    test_signal_chain_identity()
    test_forward_chain_identity()
    test_alignment_is_by_name()
    test_missing_day_breaks_the_chain()
    test_nan_name_stays_nan()
    test_turnover()
    print("калибровка")
    test_calibration_finds_planted_reversion()
    print("фраза вердикта")
    test_verdict_phrase_follows_numbers()
    print("сквозной прогон")
    test_end_to_end()
    test_empty_run_names_reasons()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
