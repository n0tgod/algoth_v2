#!/usr/bin/env python3
"""Проверки судьи хвостов.

Калибровочная пара обязательна (урок W1): судья обязан НАХОДИТЬ
подсаженный хвост и молчать на ровном — сломанная дорога выглядит
ровно как «хвост распределён равномерно». Третья проверка — форма
нуля: эффект ДНЯ (в плохие дни и флагов больше, и нетто хуже) не
вправе выдавать себя за эффект состояния.

    cd /home/user/algoth_v2 && .venv/bin/python \
        research/probe_tailveto/test_tailveto.py
"""

import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tailveto as TV                                     # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def synth(n_days=30, per_day=30, planted=False, seed=3):
    rng = np.random.default_rng(seed)
    out = []
    for d in range(n_days):
        for i in range(per_day):
            flag = i % 3 == 0
            net = float(rng.normal(-10, 60))
            if planted and flag and rng.random() < 0.12:
                net -= 900.0
            out.append({"net": net, "day": f"d{d:02d}",
                        "sym": f"S{i % 9}", "flag": flag})
    return out


def test_judge_finds_planted_and_stays_silent():
    c = TV.tail_judge(synth(planted=True))
    check("подсаженный хвост найден",
          c["measured"] and c["ratio"] > 1.5 and c["p"] < 0.05, str(c))
    check("вето-сумма отрицательна (хвост в группе)",
          c["veto_sum"] < 0, str(c.get("veto_sum")))
    flat = TV.tail_judge(synth(planted=False))
    check("на ровном — не значимо", flat["p"] > 0.1,
          str((flat["ratio"], flat["p"])))
    thin = TV.tail_judge(synth(n_days=2, per_day=10))
    check("тонкая ячейка не измерена, а не нулевая",
          not thin["measured"], str(thin))


def test_day_effect_not_mistaken_for_state():
    """В плохие дни и флагов больше, и нетто хуже — но ВНУТРИ дня флаг
    с исходом не связан. Концентрация выходит выше единицы, а p обязан
    быть большим: ровно это отличает внутридневной нуль от наивного."""
    rng = np.random.default_rng(11)
    out = []
    for d in range(30):
        bad = d % 2 == 0
        for i in range(30):
            out.append({"net": float(rng.normal(-80 if bad else 40, 40)),
                        "day": f"d{d:02d}", "sym": f"S{i % 9}",
                        "flag": rng.random() < (0.7 if bad else 0.3)})
    c = TV.tail_judge(out)
    check("эффект дня даёт концентрацию выше 1 (ловушка настоящая)",
          c["measured"] and c["ratio"] > 1.15, str(c.get("ratio")))
    check("и внутридневной нуль его НЕ засчитывает (p большой)",
          c["p"] > 0.1, str((c["ratio"], c["p"])))


def test_terciles_and_entry_state():
    rng = np.random.default_rng(5)
    S, H = 40, 5
    M = rng.normal(0, 1, (S, H))
    # Колонка 2: имя 0 — заведомо верхняя треть; колонка 3 — нижняя.
    M[0, 2] = 9.0
    M[0, 3] = -9.0
    hi, lo = TV.col_terciles(M)
    check("пороги конечны при 40 именах", np.isfinite(hi).all(), str(hi))
    thin = M.copy()
    thin[10:, :] = np.nan
    hi_t, _ = TV.col_terciles(thin)
    check("тонкое сечение порога не имеет",
          not np.isfinite(hi_t).any(), str(hi_t))

    grid = [f"2026-08-30-{h:02d}" for h in range(H)]
    grid_ix = {g: i for i, g in enumerate(grid)}
    sym_ix = {"AAAUSDT": 0}
    at3 = datetime(2026, 8, 30, 3, 7, tzinfo=timezone.utc).timestamp()
    top, bot = TV.entry_state(M, hi, lo, sym_ix, grid_ix,
                              "AAAUSDT", at3)
    check("состояние берётся с ПОСЛЕДНЕГО ЗАКРЫТОГО часа (кол. 2)",
          top is True and bot is False, str((top, bot)))
    at4 = datetime(2026, 8, 30, 4, 7, tzinfo=timezone.utc).timestamp()
    top4, bot4 = TV.entry_state(M, hi, lo, sym_ix, grid_ix,
                                "AAAUSDT", at4)
    check("часом позже то же имя — нижняя треть (кол. 3)",
          top4 is False and bot4 is True, str((top4, bot4)))
    check("чужое имя — None, не ноль",
          TV.entry_state(M, hi, lo, sym_ix, grid_ix, "ZZZ", at3)
          == (None, None), "")
    at0 = datetime(2026, 8, 30, 0, 7, tzinfo=timezone.utc).timestamp()
    check("вход в первый час сетки — состояния нет (закрытого часа нет)",
          TV.entry_state(M, hi, lo, sym_ix, grid_ix, "AAAUSDT", at0)
          == (None, None), "")


def test_missing_book_unpack():
    """Ранний возврат book_rows несёт ТРИ значения, полный — четыре:
    распаковка по счёту уронила первый живой прогон на пустой книге.
    Дорога зонда берёт [0] и обязана переживать несуществующий
    каталог."""
    got = TV.SP.book_rows(os.path.join(tempfile.gettempdir(),
                                       "no_such_book_dir"), "h4")
    check("пустая книга — пустой список, а не падение",
          got[0] == [], str(got[:1]))


def test_report_smoke():
    good = TV.tail_judge(synth(planted=True))
    thin = TV.tail_judge(synth(n_days=2, per_day=10))
    tmp = tempfile.mkdtemp()
    try:
        p = TV.write_report(
            os.path.join(tmp, "r.md"),
            [("Шорты · V1 funding (толпа в лонге)",
              [("h4 · gbm", good), ("h24 · nn", thin)])],
            [("h4 · gbm · лонги-зеркало", thin)],
            {"when": "тест", "unknown": 7, "total": 100})
        txt = open(p, encoding="utf-8").read()
        check("нуль назван по правилу",
              "перестановка флага внутри дня" in txt, txt[:200])
        check("оговорка одного эпизода на странице",
              "ограничена одним эпизодом" in txt, "")
        check("правило не внедряется — сказано",
              "правило не внедряется" in txt, "")
        check("тонкая ячейка — «не измерена»", "не измерена" in txt, "")
        check("неизвестное состояние — счётчик, не ноль",
              "7 из 100" in txt and "не ноль" in txt, "")
        check("чтение измеренных ячеек присутствует",
              ("повод считать спеку" in txt)
              or ("резало бы сделки" in txt), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = (test_judge_finds_planted_and_stays_silent,
             test_day_effect_not_mistaken_for_state,
             test_terciles_and_entry_state,
             test_missing_book_unpack,
             test_report_smoke)
    for t in tests:
        print(t.__name__)
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
