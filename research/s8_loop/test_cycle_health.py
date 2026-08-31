#!/usr/bin/env python3
"""Проверки замера бюджета цикла.

Дорога настоящая: фикстура пишет `train_log.jsonl` живого образца, а
читает его тот же `read_log`, что и прогон; сквозной прогон зовёт
настоящий `main()` с подменённой публикацией.

    .venv/bin/python \
        research/s8_loop/test_cycle_health.py
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cycle_health as CH                                 # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def write_log(mdir, rows):
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "train_log.jsonl"), "w",
              encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def row(day, h, sec, seq, sections):
    """Строка ЖИВОГО образца: метка `at` идёт форматом `%m-%d %H:%M`,
    то есть без года — ровно так её пишет цикл. Первая версия фикстуры
    несла ISO-метку, и дефект ключа суток прошёл мимо проверок: на
    живом журнале вышло 216 «суток» на 216 строк."""
    return {"seq": seq, "hour": f"{day}-{h:02d}",
            "at": f"{day[5:]} {h:02d}:30",
            "sections": sections, "symbols": 700,
            "canary_ic": 0.03, "cycle_sec": sec}


def test_median_is_a_median():
    """Медиана на чётной длине — среднее двух средних, а не верхнее.

    Числа закреплены литералом: формула от констант модуля прошла бы и
    на подделке."""
    check("чётная длина: 2.5, а не 3", CH.median([1, 2, 3, 4]) == 2.5,
          str(CH.median([1, 2, 3, 4])))
    check("нечётная длина: 3", CH.median([1, 2, 3, 4, 100]) == 3,
          str(CH.median([1, 2, 3, 4, 100])))
    check("пусто — меры нет, а не ноль", CH.median([]) is None, "")


def test_verdict_comes_from_numbers():
    """Вердикт выводится из чисел четырьмя ветками."""
    d = tempfile.mkdtemp()
    try:
        mdir = os.path.join(d, "model")
        # Сутки, где цикл укладывается, и сутки, где нет.
        rows = [row("2026-08-20", h, 1200, 100 + h, 600)
                for h in range(6)]
        rows += [row("2026-08-31", h, 5300, 200 + h, 670)
                 for h in range(6)]
        write_log(mdir, rows)
        s = CH.summarize(CH.read_log(
            os.path.join(mdir, "train_log.jsonl")), None)
        check("суток посчитано две", len(s["per_day"]) == 2,
              str([p["day"] for p in s["per_day"]]))
        check("доля прогонов длиннее часа — числом",
              s["per_day"][0]["over_share"] == 0.0
              and s["per_day"][1]["over_share"] == 1.0,
              str([p["over_share"] for p in s["per_day"]]))
        v = CH.verdict(s)
        check("переполнение названо словами и числом",
              "НЕ укладывается" in v and "5300" in v, v)
        check("сутки, с которых началось, названы",
              "с 2026-08-31" in v or s["first_over_day"] == "2026-08-31",
              str(s["first_over_day"]))
        # Обратная сторона: исправный цикл обязан МОЛЧАТЬ, иначе
        # тревога висит всегда и её перестают читать.
        write_log(mdir, [row("2026-08-20", h, 1200, 100 + h, 600)
                         for h in range(6)])
        s2 = CH.summarize(CH.read_log(
            os.path.join(mdir, "train_log.jsonl")), None)
        check("исправный цикл не кричит",
              "укладывается в час" in CH.verdict(s2)
              and "НЕ укладывается" not in CH.verdict(s2),
              CH.verdict(s2))
        check("пустой журнал — «не измерено», а не «всё хорошо»",
              "не измерено" in CH.verdict(CH.summarize([], None)),
              CH.verdict(CH.summarize([], None)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_day_key_survives_a_live_record():
    """Ключ суток обязан пережить живую метку без года.

    Проверяется числом: у суток из 24 строк обязано выйти ОДНИ сутки,
    а не двадцать четыре."""
    rows = [row("2026-08-30", h, 1200, 100 + h, 500) for h in range(24)]
    s = CH.summarize(rows, None)
    check("сутки из 24 строк — это одни сутки",
          len(s["per_day"]) == 1 and s["per_day"][0]["n"] == 24,
          str([(p["day"], p["n"]) for p in s["per_day"]]))
    check("ключ суток — календарная дата",
          s["per_day"][0]["day"] == "2026-08-30",
          str(s["per_day"][0]["day"]))
    # Запись прежнего образца (только ISO-метка, без часа сечения)
    # обязана читаться тоже: журнал переживает смену формата.
    iso = [{"seq": 1, "at": "2026-08-30T05:30:00+00:00",
            "sections": 500, "symbols": 700, "cycle_sec": 1200}]
    si = CH.summarize(iso, None)
    check("ISO-запись прежнего образца читается",
          len(si["per_day"]) == 1
          and si["per_day"][0]["day"] == "2026-08-30",
          str([p["day"] for p in si["per_day"]]))


def test_kinds_are_counted_apart():
    """Часовой цикл и цикл с обучением считаются раздельно.

    После правки каденции в журнале лежат оба вида, и без разделения
    суточная медиана смешала бы двухминутный прогон с полуторачасовым
    — сказав неправду про оба. Запись прежнего образца метки не несёт
    и обязана читаться как обучение."""
    rows = [dict(row("2026-08-31", h, 120, 300 + h, 670), kind="books")
            for h in range(23)]
    rows.append(dict(row("2026-08-31", 23, 5300, 301, 670),
                     kind="train"))
    s = CH.summarize(rows, None)
    p = s["per_day"][0]
    check("обучений за сутки — одно из двадцати четырёх",
          p["n"] == 24 and p["n_train"] == 1,
          f"{p['n']} / {p['n_train']}")
    old = [row("2026-08-20", h, 1200, 100 + h, 600) for h in range(3)]
    check("запись прежнего образца считается обучением",
          CH.summarize(old, None)["per_day"][0]["n_train"] == 3,
          str(CH.summarize(old, None)["per_day"][0]))


def test_growth_is_measured_not_assumed():
    """Растёт ли цикл с данными — ранговой связью, а не на глаз."""
    rows = [row("2026-08-20", h % 24, 1000 + 40 * h, 100 + h, 500 + h)
            for h in range(30)]
    s = CH.summarize(rows, None)
    check("рост вместе с сечениями виден числом",
          s["rho_sections"] is not None and s["rho_sections"] > 0.9,
          str(s["rho_sections"]))
    flat = [row("2026-08-20", h % 24, 1200, 100 + h, 500 + h)
            for h in range(30)]
    sf = CH.summarize(flat, None)
    check("ровный цикл связи не показывает",
          sf["rho_sections"] is None or abs(sf["rho_sections"]) < 0.2,
          str(sf["rho_sections"]))


def test_e2e_report():
    d = tempfile.mkdtemp()
    calls = []
    was = CH.publish
    try:
        mdir = os.path.join(d, "model")
        write_log(mdir, [row("2026-08-31", h, 5300, 200 + h, 670)
                         for h in range(4)])
        with open(os.path.join(mdir, "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"steps_sec": {"обучение": 4137.4,
                                     "книги": 43.1},
                       "cycle_sec": 5304.5,
                       "woke_after_hour_sec": 3301.3,
                       "sections": 672}, f)
        CH.publish = lambda m: calls.append(m)
        out = os.path.join(d, "out")
        rc = CH.main(["--model-dir", mdir, "--tag", "t", "--out", out,
                      "--no-publish"])
        check("прогон завершился нулём", rc == 0, str(rc))
        p = os.path.join(out, "CYCLE-health-t.md")
        check("отчёт написан", os.path.exists(p), p)
        md = open(p, encoding="utf-8").read()
        check("вердикт в отчёте выведен из чисел",
              "НЕ укладывается" in md, md[:200])
        check("разбивка по шагам названа снимком, а не рядом",
              "ряда по шагам не существует" in md, "")
        check("шаг обучения назван числом", "4137" in md, "")
        check("с флагом публикации нет", not calls, str(calls))
        rc = CH.main(["--model-dir", mdir, "--tag", "t", "--out", out])
        check("без флага публикация обязана случиться",
              rc == 0 and len(calls) == 1, str(calls))
        # Не та машина: ни журнала, ни манифеста — отчёт НЕ пишется.
        empty = os.path.join(d, "nothing")
        os.makedirs(empty, exist_ok=True)
        out2 = os.path.join(d, "out2")
        rc = CH.main(["--model-dir", empty, "--tag", "t", "--out", out2,
                      "--no-publish"])
        check("без данных прогон отказывается, а не пишет пустоту",
              rc == 1 and not os.path.exists(
                  os.path.join(out2, "CYCLE-health-t.md")), str(rc))
    finally:
        CH.publish = was
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (test_median_is_a_median,
             test_verdict_comes_from_numbers,
             test_day_key_survives_a_live_record,
             test_kinds_are_counted_apart,
             test_growth_is_measured_not_assumed,
             test_e2e_report)
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
