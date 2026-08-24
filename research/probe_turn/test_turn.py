"""Тесты зонда перелома.

Главное здесь — что мера РАЗЛИЧАЕТ два случая. «Кривая после пика идёт
вниз» верно всегда, поэтому зонд, который на любых данных отвечает
«перелом есть», бесполезен ровно так же, как зонд, который всегда
отвечает «нет». Проверяется обе стороны: чистый шум обязан дать
крупное `p` (перелом неотличим от порядка дней), а настоящий разлом —
малое.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import turn as T                                          # noqa: E402

OK = []


def check(name, cond, note=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name
          + (f": {note}" if note and not cond else ""))
    OK.append(bool(cond))


def days_from(vals, start=20000):
    return {start + i: float(v) for i, v in enumerate(vals)}


def test_peak_stats_reads_the_curve():
    d = days_from([1.0, 1.0, 1.0, -0.5, -0.5])
    st = T.peak_stats(d)
    check("пик найден на максимуме кривой", st["peak_i"] == 2, str(st))
    check("итог и падение после пика считаны",
          st["peak"] == 3.0 and st["end"] == 2.0 and st["drop"] == 1.0,
          str(st))
    check("просадка кривой отрицательна", st["dd"] == -1.0, str(st))
    check("день без сделок не выпадает из календаря",
          T.peak_stats({20000: 1.0, 20005: -1.0})["days"] == 6)
    check("пустая книга не даёт пика", T.peak_stats({}) is None)


def test_noise_gives_no_turning_point():
    # Чистый шум с нулевым ожиданием: «перелом» в нём есть всегда,
    # и перестановочный нуль обязан это показать крупным p.
    rng = np.random.default_rng(11)
    d = days_from(rng.normal(0, 1.0, 120))
    r = T.perm_test(d, perms=400, seed=T.SEED)
    check("на шуме перелом неотличим от порядка дней",
          r["p_drop"] > 0.10, f"p={r['p_drop']}")


def test_real_break_is_caught():
    # Настоящий разлом: сорок дней уверенного плюса, затем сорок
    # уверенного минуса. Такой порядок перестановкой не воспроизводится.
    rng = np.random.default_rng(12)
    good = rng.normal(+1.0, 0.3, 40)
    bad = rng.normal(-1.0, 0.3, 40)
    d = days_from(np.concatenate([good, bad]))
    r = T.perm_test(d, perms=400, seed=T.SEED)
    check("настоящий разлом мера ловит", r["p_drop"] < 0.02,
          f"p={r['p_drop']}")
    check("доля дней до пика у разлома высокая",
          r["share_obs"] > 0.4, str(r["share_obs"]))


def test_sync_separates_common_from_independent():
    rng = np.random.default_rng(13)
    n = 90
    # Независимые книги: общий минус случается редко.
    indep = {f"b{i}": days_from(rng.normal(0, 1, n)) for i in range(4)}
    si = T.sync_stats(indep, seed=T.SEED)
    check("у независимых книг общий минус редок и не значим",
          si["p_all_down"] > 0.10, f"p={si['p_all_down']}")
    check("попарная связь независимых книг около нуля",
          abs(si["corr_med"]) < 0.25, str(si["corr_med"]))
    # Общий фактор: у всех книг один и тот же день плохой.
    common = rng.normal(0, 1, n)
    shared = {f"b{i}": days_from(common + rng.normal(0, 0.2, n))
              for i in range(4)}
    ss = T.sync_stats(shared, seed=T.SEED)
    check("общий фактор виден как синхронный минус",
          ss["p_all_down"] < 0.02, f"p={ss['p_all_down']}")
    check("попарная связь при общем факторе высокая",
          ss["corr_med"] > 0.8, str(ss["corr_med"]))


def test_split_by_peak_reports_both_sides():
    tr = []
    for i in range(10):
        tr.append({"day": 20000 + i, "pnl": 1.0, "net": 50.0,
                   "why": "цель", "side": "long", "sym": "AAAUSDT",
                   "arm": "gbm"})
    for i in range(10):
        tr.append({"day": 20010 + i, "pnl": -1.0, "net": -60.0,
                   "why": "стоп", "side": "short", "sym": "BBBUSDT",
                   "arm": "gbm"})
    parts = T.split_by_peak(tr, T.daily(tr))
    check("до пика — прибыльная часть",
          parts["before"]["n"] == 10 and parts["before"]["pnl"] == 10.0,
          str(parts["before"]))
    check("после пика — убыточная часть",
          parts["after"]["n"] == 10 and parts["after"]["pnl"] == -10.0,
          str(parts["after"]))
    check("состав выходов различается по сторонам пика",
          "цель" in parts["before"]["why"]
          and "стоп" in parts["after"]["why"])
    check("вклад лучшего имени назван отдельно",
          parts["before"]["top_sym"] == "AAAUSDT"
          and parts["before"]["pnl_wo_top"] == 0.0,
          str(parts["before"]))


def test_whole_run_executes_to_report():
    """Прогон целиком: книга на диске → артефакт и отчёт.

    Зонд S11 дважды падал на дорогах, которых не исполнял ни один
    тест: сперва на первом обучении, потом на последнем шаге, после
    часа счёта. Здесь исполняется весь путь — чтение журналов ядром
    `trades.py`, перестановки, синхронность, сборка отчёта, — на
    настоящем каталоге книги во временном корне.
    """
    import json as _json
    import tempfile
    from datetime import datetime, timezone

    root = tempfile.mkdtemp()
    s8 = os.path.join(root, "s8_loop", "out")
    for name in ("model", "model_h24"):
        mdir = os.path.join(s8, name)
        os.makedirs(mdir)
        with open(os.path.join(mdir, "manifest.json"), "w",
                  encoding="utf-8") as f:
            _json.dump({"version": 2, "horizon_h": 4}, f)
        base = 1786000000
        pk, rv = [], []
        for i in range(480):        # 20 суток: нулю нужны дни
            hour = datetime.fromtimestamp(
                base + i * 3600, timezone.utc).strftime("%Y-%m-%d-%H")
            pk.append({"arm": "gbm", "hour": hour,
                       "at_ts": base + i * 3600 + 3900,
                       "long": [{"sym": "AAAUSDT", "fwd": 60.0,
                                 "mae": -30.0, "mfe": 90.0,
                                 "px": 100.0}],
                       "short": []})
            # Первая половина прибыльна, вторая — нет: у прогона
            # обязан получиться непустой разбор по обе стороны пика.
            got = 40.0 if i < 240 else -80.0
            rv.append({"arm": "gbm", "hour": hour, "cost_bp": 11.0,
                       "at_ts": base + (i + 4) * 3600 + 60,
                       "rows": [{"sym": "AAAUSDT", "side": "long",
                                 "expected": 60.0, "got": got,
                                 "net": got - 11.0}]})
        for fname, rows in (("picks.jsonl", pk), ("review.jsonl", rv)):
            with open(os.path.join(mdir, fname), "w",
                      encoding="utf-8") as f:
                for r in rows:
                    f.write(_json.dumps(r, ensure_ascii=False) + "\n")
    out_was = T.HERE
    try:
        T.HERE = os.path.join(root, "probe_turn")
        rc = T.main.__wrapped__(s8) if hasattr(T.main, "__wrapped__") \
            else _run_main(s8)
        check("прогон дошёл до конца", rc == 0, str(rc))
        rep = os.path.join(T.HERE, "out", "TURN-report-smoke.md")
        art = os.path.join(T.HERE, "out", "TURN-smoke.json")
        check("артефакт и отчёт написаны",
              os.path.exists(art) and os.path.exists(rep))
        body = open(rep, encoding="utf-8").read()
        check("в отчёте есть таблица перелома и синхронность",
              "Перелом по книгам" in body
              and "Синхронность книг" in body, body[:120])
        data = _json.load(open(art, encoding="utf-8"))
        check("книга посчитана, сделки найдены",
              (data["books"]["h4"]["n"] or 0) > 0,
              str(data["books"]["h4"].get("n")))
        check("обе стороны пика непусты",
              data["books"]["h4"]["parts"]["before"]["n"] > 0
              and data["books"]["h4"]["parts"]["after"]["n"] > 0)
    finally:
        T.HERE = out_was


def _run_main(s8):
    argv = sys.argv
    sys.argv = ["turn.py", "--s8", s8, "--perms", "200",
                "--tag", "smoke", "--no-publish"]
    try:
        return T.main()
    finally:
        sys.argv = argv


def main():
    test_whole_run_executes_to_report()
    test_peak_stats_reads_the_curve()
    test_noise_gives_no_turning_point()
    test_real_break_is_caught()
    test_sync_separates_common_from_independent()
    test_split_by_peak_reports_both_sides()
    if not all(OK):
        print("ЕСТЬ ПАДЕНИЯ")
        return 1
    print("все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
