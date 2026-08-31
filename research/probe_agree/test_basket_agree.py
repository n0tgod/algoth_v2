#!/usr/bin/env python3
"""Проверки замера «согласие голов на корзине h24c».

Дорога настоящая, не пересказ: фикстура пишет picks.jsonl живого
образца, читают его те же BB.load_picks и AG.pick_keys, что и прогон.
Сломанное пересечение (своя рука вместо другой) или нуль, игнорирующий
ширину, обязаны падать — оба отрицательных контроля прогоняются
копией файла через scratchpad.

    cd /home/user/algoth_v2 && .venv/bin/python \
        research/probe_agree/test_basket_agree.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import basket_agree as BA                                 # noqa: E402

BB, AG = BA.BB, BA.AG
FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def hour_key(ts):
    return datetime.fromtimestamp(ts, timezone.utc) \
        .strftime("%Y-%m-%d-%H")


T0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
H = 3600


def write_fixture(mdir):
    """Выборы живого образца: две головы, час с частичным согласием
    и час, где вторая голова не выбирала вовсе."""
    os.makedirs(mdir, exist_ok=True)
    rows = [
        {"arm": "gbm", "hour": hour_key(T0 + H), "at_ts": T0 + H,
         "long": [{"sym": "AAAUSDT", "px": 100.0, "fwd": 40.0},
                  {"sym": "BBBUSDT", "px": 50.0, "fwd": 30.0}],
         "short": [{"sym": "CCCUSDT", "px": 10.0, "fwd": -35.0}]},
        {"arm": "nn", "hour": hour_key(T0 + H), "at_ts": T0 + H,
         "long": [{"sym": "AAAUSDT", "px": 100.0, "fwd": 38.0},
                  {"sym": "DDDUSDT", "px": 5.0, "fwd": 25.0}],
         "short": [{"sym": "CCCUSDT", "px": 10.0, "fwd": -30.0}]},
        {"arm": "gbm", "hour": hour_key(T0 + 2 * H),
         "at_ts": T0 + 2 * H,
         "long": [{"sym": "BBBUSDT", "px": 50.5, "fwd": 20.0}],
         "short": []},
    ]
    with open(os.path.join(mdir, "picks.jsonl"), "w",
              encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load_all(mdir):
    return BB.load_picks(mdir), AG.pick_keys(mdir)


def test_agreed_intersection():
    d = tempfile.mkdtemp()
    try:
        mdir = os.path.join(d, "model_h24")
        write_fixture(mdir)
        picks, keys = load_all(mdir)
        agreed = BA.agreed_picks(picks, keys)
        g = agreed.get("gbm") or {}
        n = agreed.get("nn") or {}
        got_g = sorted((x["sym"], x["side"]) for x in
                       (g.get(T0 + H) or []))
        got_n = sorted((x["sym"], x["side"]) for x in
                       (n.get(T0 + H) or []))
        want = [("AAAUSDT", "long"), ("CCCUSDT", "short")]
        check("пересечение gbm — ровно общие ноги", got_g == want,
              str(got_g))
        check("пересечение nn — те же ноги (симметрия)",
              got_n == want, str(got_n))
        check("нога только одной головы не входит",
              all(x["sym"] != "BBBUSDT" for x in g.get(T0 + H) or [])
              and all(x["sym"] != "DDDUSDT"
                      for x in n.get(T0 + H) or []),
              str((g, n)))
        check("час без выбора второй головы ОТСУТСТВУЕТ, а не пуст",
              (T0 + 2 * H) not in g, str(sorted(g)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_null_width_and_determinism():
    d = tempfile.mkdtemp()
    try:
        mdir = os.path.join(d, "model_h24")
        write_fixture(mdir)
        picks, keys = load_all(mdir)
        agreed = BA.agreed_picks(picks, keys)
        n1 = BA.null_picks(picks, agreed, 3)
        n2 = BA.null_picks(picks, agreed, 3)
        check("нуль той же ширины по часу",
              len((n1.get("gbm") or {}).get(T0 + H) or [])
              == len((agreed.get("gbm") or {}).get(T0 + H) or []),
              str(n1.get("gbm")))
        check("час без согласия отсутствует и у нуля",
              (T0 + 2 * H) not in (n1.get("gbm") or {}),
              str(sorted(n1.get("gbm") or {})))
        check("одно зерно — один нуль (воспроизводимость)",
              n1 == n2, "")
        seen = {json.dumps(BA.null_picks(picks, agreed, s),
                           sort_keys=True, default=str)
                for s in BA.SEEDS}
        check("разные зёрна дают разные подмножества",
              len(seen) > 1, f"вариантов {len(seen)}")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verdict_from_numbers():
    nulls = [{"realized": v} for v in (-5.0, -1.0, 2.0, 4.0)]
    check("выше максимума нуля — «сверх сужения»",
          "СВЕРХ сужения" in BA.verdict({"realized": 9.0}, nulls), "")
    check("ниже минимума нуля — «хуже случайного»",
          "ХУЖЕ случайного" in BA.verdict({"realized": -9.0}, nulls),
          "")
    check("внутри распределения — «неотличимо»",
          "неотличимо" in BA.verdict({"realized": 1.0}, nulls), "")
    check("нет замера — «не измерено», не вердикт",
          "не измерено" in BA.verdict(None, nulls), "")


def synth_mids(syms, n=60):
    """Середины дрожат, как живые (урок calm-зонда: ровная фикстура
    вырождает меры)."""
    out = {}
    for i, s in enumerate(syms):
        base = 10.0 + i
        out[s] = {T0 + j * H: base * (1 + 0.0006 * j
                                      * (1 if j % 3 else -1))
                  for j in range(n)}
    return out


def wide_picks(hours=8, per_hour=6):
    syms = [f"S{i}USDT" for i in range(24)]
    picks = {}
    for h in range(hours):
        legs = []
        for i in range(per_hour):
            legs.append({"sym": syms[(h * per_hour + i) % 24],
                         "side": "long" if i % 2 else "short",
                         "px": 10.0 + (h * per_hour + i) % 24})
        picks[T0 + h * H] = legs
    return picks, syms


def test_invest_full():
    """Ветвь `full` обязана ОБОБЩАТЬ живой размер, а не заменять его.

    Тождество проверяется числом и целым реплеем: при шести ногах в
    часе капитал/24/6 и есть LEG_USD, значит результат обязан совпасть
    с умолчанием ПОЛНОСТЬЮ. И она обязана действительно вкладывать
    больше там, где ног мало."""
    full = BA.leg_rule("full")
    check("при шести ногах в часе — ровно размер живой книги",
          full(T0, 6) == BB.LEG_USD,
          f"{full(T0, 6)} против {BB.LEG_USD}")
    check("одна нога забирает часовой ломоть капитала",
          abs(full(T0, 1) - BB.CAPITAL / BA.CELL["age_h"]) < 1e-12,
          str(full(T0, 1)))
    check("час без ног не получает ничего (и не делит на ноль)",
          full(T0, 0) == 0.0, str(full(T0, 0)))
    check("ветвь leg — прежнее число", BA.leg_rule("leg")
          == BB.LEG_USD, str(BA.leg_rule("leg")))

    picks, syms = wide_picks()
    mids = synth_mids(syms)
    a = BB.replay(picks, mids, BA.CELL["take"], BA.CELL["floor"],
                  age_h=BA.CELL["age_h"])
    b = BB.replay(picks, mids, BA.CELL["take"], BA.CELL["floor"],
                  age_h=BA.CELL["age_h"], leg_usd=full)
    check("на шести ногах в часе full повторяет умолчание бит в бит",
          a == b, f"{a}\n{b}")

    thin, syms2 = wide_picks(hours=8, per_hour=1)
    mids2 = synth_mids(syms2)
    t_leg = BB.replay(thin, mids2, BA.CELL["take"], BA.CELL["floor"],
                      age_h=BA.CELL["age_h"])
    t_full = BB.replay(thin, mids2, BA.CELL["take"], BA.CELL["floor"],
                       age_h=BA.CELL["age_h"], leg_usd=full)
    check("на узкой книге full вкладывает ровно вшестеро больше",
          abs(t_full["gross_share"] / t_leg["gross_share"] - 6.0)
          < 0.05,
          f"{t_full['gross_share']} против {t_leg['gross_share']}")
    check("вложенная доля названа числом, а не отсутствует",
          t_leg["gross_share"] is not None
          and t_leg["gross_share"] > 0, str(t_leg["gross_share"]))


def test_e2e_report():
    d = tempfile.mkdtemp()
    was_out, was_mids, was_pub = BA.OUT, BB.BK.load_mids, BA.PT.publish
    calls = []
    try:
        s8 = os.path.join(d, "s8")
        write_fixture(os.path.join(s8, "model_h24"))
        # Середины дрожат, как живые (урок calm-зонда: ровная фикстура
        # вырождает меры), и тянутся за предел возраста корзины.
        mids = {}
        for i, sym in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT",
                                 "DDDUSDT")):
            base = [100.0, 50.0, 10.0, 5.0][i]
            mids[sym] = {T0 + j * H: base * (1 + 0.0007 * j
                                             * (1 if j % 3 else -1))
                         for j in range(30)}
        BA.OUT = os.path.join(d, "out")
        BB.BK.load_mids = lambda syms, log=None: mids
        BA.PT.publish = lambda *a, **k: calls.append(1)
        rc = BA.main(["--s8", s8, "--tag", "t", "--no-publish"])
        check("прогон завершился нулём", rc == 0, str(rc))
        path = os.path.join(BA.OUT, "AGREE-basket-t.md")
        check("отчёт написан", os.path.exists(path), path)
        md = open(path, encoding="utf-8").read()
        check("вердикт выведен из чисел и назван по головам",
              "Вердикт gbm (выведен из чисел)" in md
              and "Вердикт nn (выведен из чисел)" in md, md[:300])
        check("согласные ноги названы числом",
              "Согласных ног 2 из 4" in md, "")
        check("строки base и agreed в таблице",
              "| gbm · base |" in md and "| gbm · agreed |" in md, "")
        check("артефакт json написан",
              os.path.exists(os.path.join(BA.OUT,
                                          "agree-basket-t.json")), "")
        check("с флагом --no-publish публикации нет",
              not calls, str(calls))
        check("умолчание НЕ выдаёт себя за полное вложение",
              "ВЛОЖЕНО ПОЛНОСТЬЮ" not in md, "")
        rc = BA.main(["--s8", s8, "--tag", "t"])
        check("без флага публикация обязана случиться",
              rc == 0 and len(calls) == 1, str(calls))

        rc = BA.main(["--s8", s8, "--tag", "t", "--invest", "full",
                      "--no-publish"])
        pf = os.path.join(BA.OUT, "AGREE-basket-t-full.md")
        check("полное вложение пишет СВОЙ артефакт",
              rc == 0 and os.path.exists(pf), pf)
        mdf = open(pf, encoding="utf-8").read()
        check("отчёт называет ветвь размера",
              "ВЛОЖЕНО ПОЛНОСТЬЮ" in mdf and "размер ноги: full"
              in mdf, mdf[:400])
        check("гросс стоит колонкой числом",
              "| гросс |" in mdf, "")
        check("прежний отчёт не затёрт",
              open(path, encoding="utf-8").read() == md, "")
    finally:
        BA.OUT, BB.BK.load_mids, BA.PT.publish = (was_out, was_mids,
                                                  was_pub)
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (test_agreed_intersection,
             test_null_width_and_determinism,
             test_verdict_from_numbers,
             test_invest_full,
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
