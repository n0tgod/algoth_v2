#!/usr/bin/env python3
"""Проверки замера «книги DCA на согласии рук».

Кусаются: согласие считается по ВЫБОРАМ обеих рук и по стороне тоже
(одно имя, один час, но разные стороны — не согласие); согласный лист
есть ПОДМНОЖЕСТВО нынешнего, а не другой лист; контроль берёт случайные
выборки ТОГО ЖЕ размера и не считается, когда выборки такого размера не
бывает; отчёт называет обе ветки и долю зёрен числом.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import agree_book as A                                        # noqa: E402


def _leg(sym, at, arm, side="long"):
    return {"sym": sym, "at": float(at), "arm": arm, "side": side,
            "fwd": 50.0, "fav": 100.0}


def test_agreement_needs_both_arms_and_the_same_side():
    legs = [_leg("AAAUSDT", 100, "gbm"), _leg("AAAUSDT", 100, "nn"),
            # одна рука — не согласие
            _leg("BBBUSDT", 100, "gbm"),
            # обе руки, но РАЗНЫЕ стороны: это не одно решение
            _leg("CCCUSDT", 100, "gbm", "long"),
            _leg("CCCUSDT", 100, "nn", "short"),
            # то же имя ДРУГИМ часом: согласие считается по часу
            _leg("AAAUSDT", 3700, "gbm")]
    ag, arms = A.agreed_of(legs)
    assert ag == {("AAAUSDT", 100.0, "long")}, ag
    assert sum(1 for a in arms.values() if len(a) == 1) == 4, arms
    print(f"ok  согласие: из {len(arms)} решений согласных {len(ag)}; "
          "разные стороны и разные часы согласием не считаются")


def test_agreed_sheet_is_a_subset_and_keeps_every_ruler():
    """Урезание идёт по РЕШЕНИЮ, а не по записи: линейки не расходятся."""
    cache = {}
    for pr in (("a", 1.0, "long"), ("b", 2.0, "long")):
        for sym, at in (("AAAUSDT", 100.0), ("BBBUSDT", 100.0)):
            cache[(pr, sym, at)] = {"sym": sym, "at": at, "side": "long",
                                    "usd": 1.0}
    want = {("AAAUSDT", 100.0, "long")}
    got = A.keep(cache, want)
    assert len(got) == 2, got                     # обе линейки одного решения
    assert {k[1] for k in got} == {"AAAUSDT"}, got
    assert set(got) <= set(cache), "урезание обязано быть подмножеством"
    assert A.keys_of(cache) == {("AAAUSDT", 100.0, "long"),
                                ("BBBUSDT", 100.0, "long")}
    print("ok  согласный лист — подмножество: решение уходит СО ВСЕМИ "
          "линейками, кэш не меняется")


def test_control_takes_the_same_size_and_says_when_it_cannot():
    """Выборка того же размера — или причина словами, а не пустой ответ."""
    cache = {}
    for i in range(10):
        cache[(("a", 1.0, "long"), f"S{i}USDT", 100.0 + i)] = {
            "sym": f"S{i}USDT", "at": 100.0 + i, "side": "long"}
    seen = []

    def _packer(sub):
        seen.append(len(A.keys_of(sub)))
        return {}

    A.control(cache, A.keys_of(cache), 4, _packer, None, {}, [],
              seeds=5, log=lambda *a: None)
    assert seen == [4] * 5, seen
    # согласных столько же, сколько решений: вычитать нечего
    why = A.control(cache, A.keys_of(cache), 10, _packer, None, {}, [],
                    seeds=5, log=lambda *a: None)
    assert "невозможна" in (why.get("why") or ""), why
    print(f"ok  контроль: {len(seen)} выборок ровно по {seen[0]} решений; "
          "выборка того же размера невозможна — причина словами")


def test_beat_share_counts_ties_against_the_filter():
    draws = [{"final": 0.1}, {"final": 0.2}, {"final": 0.3}, {"final": None}]
    sh, n = A.beat_share(draws, 0.2, "final")
    assert n == 3 and abs(sh - 0.667) < 5e-4, (sh, n)   # доля округлена
    sh0, _n0 = A.beat_share(draws, None, "final")
    assert sh0 is None, sh0
    print(f"ok  доля зёрен: ничья считается НЕ в пользу фильтра ({sh}); "
          "без величины — прочерк, а не ноль")


def test_report_reconciles_the_branch_with_the_live_book():
    """Ветка «обе руки» обязана сверяться с живой книгой ЧИСЛОМ.

    Замер считает книгу заново на кэше: разойдись он с живым сводом —
    отвечал бы про другую книгу, а числа выглядели бы как ответ на
    вопрос владельца. Сверка идёт в отчёт строкой, а не в лог.
    """
    import json
    import tempfile

    td = tempfile.mkdtemp()
    art = os.path.join(td, "art.json")
    dep = int(R.DEPOSITS[1])
    with open(art, "w", encoding="utf-8") as f:
        json.dump({"books": {f"safe:{dep}": {"all": {
            "n": 100, "usd": 250.0, "final": 0.025, "max_dd": -0.01}}}}, f)
    got = A.live_of(art, ["safe"], dep=dep)
    assert got["safe"]["usd"] == 250.0, got
    s = {"families": [{"name": "длинные книги", "keys": ["safe"],
                       "decisions": 10, "agreed": 3, "one_arm": 7,
                       "all": {f"safe:{dep}": {"n": 90, "usd": 100.0,
                                               "final": 0.01,
                                               "max_dd": -0.02}},
                       "agree": {}, "control": {}, "live": got}],
         "seeds": 0, "main_dep": dep, "computed_at": "2026-09-12 10:00"}
    txt = A.report(s)
    assert "Сверка ветки" in txt, txt[:400]
    assert "100 / 90" in txt and "-150.00" in txt, \
        [x for x in txt.splitlines() if "/" in x][:6]
    # свода нет — причина словами, а не тишина
    why = A.live_of(os.path.join(td, "нет.json"), ["safe"])
    assert "не прочитан" in (why.get("why") or ""), why
    txt2 = A.report(dict(s, families=[dict(s["families"][0], live=why)]))
    assert "не прочитан" in txt2, txt2[:400]
    print("ok  сверка с живой книгой: расхождение -150.00 $ напечатано, "
          "отсутствие свода названо причиной")


def test_report_names_both_branches_and_the_control():
    s = {"families": [{"name": "длинные книги", "keys": ["safe"],
                       "decisions": 100, "agreed": 30, "one_arm": 70,
                       "all": {f"safe:{int(R.DEPOSITS[1])}": {
                           "n": 100, "usd": 50.0, "final": 0.005,
                           "max_dd": -0.01, "ratio": 0.5}},
                       "agree": {f"safe:{int(R.DEPOSITS[1])}": {
                           "n": 30, "usd": 40.0, "final": 0.004,
                           "max_dd": -0.005, "ratio": 0.8}},
                       "control": {"safe": [{"final": 0.003, "ratio": 0.4},
                                            {"final": 0.006, "ratio": 0.9}]}}],
         "seeds": 2, "main_dep": int(R.DEPOSITS[1]),
         "computed_at": "2026-09-12 10:00"}
    txt = A.report(s)
    assert "обе руки" in txt and "согласие" in txt, txt[:400]
    assert "30" in txt and "30.0 %" in txt, txt[:400]
    assert "случайная выборка того же размера" in txt.lower(), txt[:600]
    assert "50 % из 2" in txt, [x for x in txt.splitlines() if "%" in x][:8]
    bad = A.report({"error": "кэш реплея непригоден: подпись чужая"})
    assert "Не посчитано" in bad and "подпись чужая" in bad, bad[:200]
    print("ok  отчёт: обе ветки, состав решений и доля зёрен числом; "
          "непригодный кэш — причина словами")


if __name__ == "__main__":
    for t in (test_agreement_needs_both_arms_and_the_same_side,
              test_report_reconciles_the_branch_with_the_live_book,
              test_agreed_sheet_is_a_subset_and_keeps_every_ruler,
              test_control_takes_the_same_size_and_says_when_it_cannot,
              test_beat_share_counts_ties_against_the_filter,
              test_report_names_both_branches_and_the_control):
        t()
    print("\nвсе 6 проверок прошли")
