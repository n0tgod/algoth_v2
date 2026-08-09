#!/usr/bin/env python3
"""Проверки турнира политик: геометрия, слоты, селектор без заглядывания.

Три места, где ошибка была бы невидимой, и на каждое стоит проверка,
построенная так, чтобы неверная реализация дала ДРУГОЕ число, а не
упала: заглядывание селектора в будущее (вариант, великий только в
будущем окне, обязан достаться оракулу и НЕ достаться селектору);
подмена риска гейта осью стопа (вариант без стопа обязан фильтроваться
тем же квантильным риском); слоты и одна позиция на имя (мягкий гейт
не имеет права расширить книгу).

    python3 research/s10_policy/test_tournament.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tournament as T                                       # noqa: E402

FAIL = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  ПАДЕНИЕ ") + name
          + ("" if ok else f": {extra}"))
    if not ok:
        FAIL.append(name)


def bar(t, o, h, l, c):
    return [t, o, h, l, c, 1.0]


def test_variants():
    vs = T.variants()
    check("объявленных вариантов ровно 72", len(vs) == 72, str(len(vs)))
    keys = [v["key"] for v in vs]
    check("ключи вариантов уникальны", len(set(keys)) == len(keys))
    check("вариант текущих правил присутствует", T.CURRENT in keys,
          T.CURRENT)


def test_legs():
    import json
    import tempfile
    rows = [
        # Лонг: fwd > 0; квантильный стоп дальше среднего → риск 45.
        {"sym": "AUSDT", "fwd": 30.0, "mae": -30.0, "mfe": 90.0,
         "mae_q": -45.0, "mfe_q": 80.0, "px": 100.0, "beta": 1.0},
        # Шорт: fwd < 0; у шорта ход против — верхний конец (mfe).
        {"sym": "BUSDT", "fwd": -25.0, "mae": -80.0, "mfe": 20.0,
         "mae_q": -90.0, "mfe_q": 35.0, "px": 50.0, "beta": 1.0},
        # Без обещаний пути — не кандидат.
        {"sym": "CUSDT", "fwd": 40.0, "px": 10.0},
    ]
    rec = {"hour": "2026-08-05-10", "written_at": 1_786_000_000.0,
           "arms": {"gbm": rows}}
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sheets.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        legs = T.legs_from_sheets([p], log=lambda *a: None)
    check("ног две: строка без обещаний пути выпала", len(legs) == 2,
          str(len(legs)))
    la = next(g for g in legs if g["sym"] == "AUSDT")
    lb = next(g for g in legs if g["sym"] == "BUSDT")
    check("сторона — знак прогноза",
          la["side"] == "long" and lb["side"] == "short",
          f"{la['side']} / {lb['side']}")
    # Исполняемый стоп — дальний из квантильного и среднего.
    check("стоп лонга — квантильный уровень (дальше среднего)",
          la["adv_q"] == -45.0 and la["adv_m"] == -30.0,
          f"{la['adv_q']} / {la['adv_m']}")
    # RR всегда по исполняемому риску: 90/45 = 2, а не 90/30 = 3.
    # Реализация, берущая риск по оси стопа, дала бы здесь 3 — и
    # вариант без стопа прошёл бы гейт RR ≥ 3, которого у сделки нет.
    check("RR считается по квантильному риску", la["rr"] == 2.0,
          str(la["rr"]))
    # У шорта против позиции идёт верхний конец: mfe_q = +35.
    check("у шорта риск — верхний квантиль", lb["adv_q"] == 35.0,
          str(lb["adv_q"]))


def test_outcome():
    t0 = 1_786_000_000
    up = [bar(t0 + 30, 100.0, 100.05, 99.95, 100.0),
          bar(t0 + 90, 100.0, 100.45, 99.99, 100.4)]
    got = T.outcome(up, t0, "long", -20.0, 40.0, 24)
    check("лонг: цель взята вторым баром",
          got and got[0] == "цель" and round(got[1]) == 40, str(got))
    # Вход — открытие ПЕРВОГО бара после t0, не цена листа.
    check("вход — первая доступная цена", got and got[3] == 100.0,
          str(got))
    both = [bar(t0, 100.0, 100.50, 99.70, 100.2)]
    got = T.outcome(both, t0, "long", -20.0, 40.0, 24)
    check("оба уровня в одном баре — стоп (против нас)",
          got and got[0] == "стоп", str(got))
    # Ось «без стопа»: тот же бар, стопа нет — цель.
    got = T.outcome(both, t0, "long", None, 40.0, 24)
    check("без стопа тот же бар отдаёт цель",
          got and got[0] == "цель", str(got))
    # Ось «без тейка»: доживает до среза возраста последним закрытием.
    got = T.outcome(up, t0, "long", None, None, 24)
    check("без уровней сделка выходит по сроку",
          got and got[0] == "срок" and round(got[1]) == 40, str(got))
    # Возраст режет окно: бар за пределом не виден.
    late = up + [bar(t0 + 25 * 3600, 100.4, 100.6, 100.3, 100.5)]
    got = T.outcome(late, t0, "long", None, None, 24)
    check("бар за пределом возраста не участвует",
          got and round(got[1]) == 40, str(got))
    check("нет баров — пропуск, а не ноль",
          T.outcome([], t0, "long", -20.0, 40.0, 24) is None)


def _leg(i, sym, at, fwd=30.0, arm="gbm"):
    side = "long" if fwd > 0 else "short"
    return {"id": i, "arm": arm, "sym": sym, "hour": "h", "at": at,
            "side": side, "fwd": fwd, "px": 100.0,
            "adv_q": -20.0 if side == "long" else 20.0,
            "adv_m": -15.0 if side == "long" else 15.0,
            "fav": 60.0 if side == "long" else -60.0, "rr": 3.0}


def _outs(legs, why="цель", move=60.0, hold=3600):
    outs = {}
    for lg in legs:
        for stop in T.STOPS:
            for take in T.TAKES:
                for age in T.AGES:
                    outs[(lg["id"], stop, take, age)] = (
                        why, move if lg["side"] == "long" else -move,
                        lg["at"] + hold, 100.0)
    return outs


def test_slots():
    t0 = 1_786_000_000
    var = dict(T.variants()[0], edge=22.0, rr=1.5, stop="q",
               take=True, age=24)
    legs = [_leg(i, f"S{i}USDT", t0 + i) for i in range(8)]
    tr = T.simulate(legs, _outs(legs), var)
    check("восьми кандидатам достаётся шесть мест", len(tr) == 6,
          str(len(tr)))
    # Одна позиция на имя: то же имя при живой позиции — пропуск,
    # после выхода — новая сделка.
    legs = [_leg(0, "AUSDT", t0), _leg(1, "AUSDT", t0 + 600),
            _leg(2, "AUSDT", t0 + 7200)]
    tr = T.simulate(legs, _outs(legs, hold=3600), var)
    check("одна позиция на имя, повторный вход после выхода",
          len(tr) == 2, str(len(tr)))
    # Гейт по краю: слабый прогноз не входит.
    legs = [_leg(0, "AUSDT", t0, fwd=10.0)]
    tr = T.simulate(legs, _outs(legs), var)
    check("прогноз слабее края не входит", len(tr) == 0, str(len(tr)))


def test_selector():
    # Дневные ряды строятся руками. Вариант A стабильно хорош в
    # прошлом и будущем; вариант B — великий ТОЛЬКО в будущем окне.
    # Селектор без заглядывания обязан взять A; реализация, читающая
    # будущее, взяла бы B — этим тест и кусается. Оракулу B положен.
    day0 = 20_000
    A, B = {}, {}
    for d in range(day0, day0 + T.SEL_WIN_D):
        A[d] = [10.0, 2]            # +10 б.п. в день, 2 сделки
        B[d] = [-5.0, 2]
    for d in range(day0 + T.SEL_WIN_D, day0 + T.SEL_WIN_D + 7):
        A[d] = [10.0, 2]
        B[d] = [500.0, 2]
    wf = T.walk_forward({"A": A, "B": B}, ["A", "B"],
                        log=lambda *a: None)
    check("селектор выбрал прошлое, не будущее",
          wf["points"][0]["pick"] == "A", str(wf["points"][0]))
    check("оракул взял вариант, великий в будущем",
          wf["ora"]["picks"] if False else wf["ora"]["total_bp"] > 3000,
          str(wf["ora"]))
    check("кривая селектора — деньги выбранного варианта",
          wf["sel"]["days"] if False else wf["sel"]["total_bp"] == 70.0,
          str(wf["sel"]))
    # Годность: вариант тоньше 30 сделок в окне не участвует.
    thin = {d: [100.0, 1] for d in range(day0, day0 + 10)}
    wf2 = T.walk_forward({"A": A, "thin": thin}, ["A", "thin"],
                         log=lambda *a: None)
    check("тонкий вариант не годен, выбран A",
          all(p["pick"] == "A" for p in wf2["points"]),
          str(wf2["points"]))
    # Случайный выбор воспроизводим и закреплён ЧИСЛОМ (урок R3).
    got = [T._rnd_pick(s, 0, 7) for s in (1, 2, 3)]
    check("зерно случайного селектора закреплено числом",
          got == [1000003 % 7, 2000006 % 7, 3000009 % 7], str(got))
    check("значения зерна — 4, 1, 5 (правка формулы сломает нуль)",
          got == [4, 1, 5], str(got))


def test_kill_arm():
    """Рука kill-10: сливающий вариант снимается немедленно.

    B великолепен 28 дней и дальше сливает по −20 в день; базовый
    селектор держит его до плановой точки, пока 28-дневное окно не
    протухнет, и заканчивает −310. Рука kill-10 обязана снять B в
    первый же день, когда его 10-дневная сумма ушла в минус, и не
    возвращать, пока он сливает. Реализация, где правило не работает,
    даст ровно базовые числа — этим тест и кусается.
    """
    day0 = 30_000
    A, B = {}, {}
    for d in range(day0, day0 + 60):
        A[d] = [10.0, 4]
        B[d] = [50.0, 4] if d < day0 + 28 else [-20.0, 4]
    wf = T.walk_forward({"A": A, "B": B}, ["A", "B"],
                        log=lambda *a: None)
    check("база выбирает B и платит за инерцию −310",
          wf["sel"]["total_bp"] == -310.0, str(wf["sel"]))
    check("kill-10 снимает B в первый день минусовой десятидневки",
          len(wf["kill_events"]) == 1
          and wf["kill_events"][0]["day"] == day0 + 36
          and wf["kill_events"][0]["was"] == "B"
          and wf["kill_events"][0]["to"] == "A",
          str(wf["kill_events"]))
    check("рука kill-10 заканчивает +80 против −310 у базы",
          wf["kill"]["total_bp"] == 80.0, str(wf["kill"]))
    check("снятый не возвращается, пока сливает",
          all(p["pick"] == "A" for p in wf["kill"]["picks"]
              if p["day"] >= day0 + 36),
          str(wf["kill"]["picks"]))
    # Правило свежести напрямую: без десяти сделок в окне вариант
    # простаивает, а не сливает, — тихая книга не снимается за тишину.
    idle = {d: [-5.0, 1] for d in range(100, 109)}
    check("вариант без десяти сделок не сливает",
          T._bleeding(idle, 109) is False, str(T._bleeding(idle, 109)))
    busy = {d: [-5.0, 1] for d in range(100, 110)}
    check("десять сделок в минус — сливает",
          T._bleeding(busy, 110) is True, str(T._bleeding(busy, 110)))


def test_artifacts_survive_fresh_checkout():
    """Прогон целиком, в каталог, которого ещё нет, — оба артефакта.

    Живой прогон на сервере досчитал все 710 ног по барам и упал на
    ЗАПИСИ JSON: свежий чекаут не несёт research/s10_policy/out/, а
    каталог создавал только report() — после записи. Вся работа
    терялась на последнем шаге; смоук в песочнице этого не ловил,
    потому что писал во ВРЕМЕННЫЙ каталог, который существовал.
    Здесь прогоняется настоящий main() в несуществующий каталог.
    """
    import json as _json
    import subprocess
    import tempfile
    td = tempfile.mkdtemp()
    sheets = os.path.join(td, "sheets.jsonl")
    rec = {"hour": "2026-08-05-10", "written_at": 1_786_000_000.0,
           "arms": {"gbm": [{"sym": "AUSDT", "fwd": 30.0,
                             "mae": -30.0, "mfe": 90.0,
                             "px": 100.0, "beta": 1.0}]}}
    with open(sheets, "w", encoding="utf-8") as f:
        f.write(_json.dumps(rec) + "\n")
    out = os.path.join(td, "no", "such", "dir", "V1.md")
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "tournament.py"),
         "--sheets", sheets, "--root", td, "--out", out],
        capture_output=True, text=True, timeout=300)
    check("прогон в свежем чекауте не падает", r.returncode == 0,
          (r.stderr or r.stdout)[-300:])
    check("оба артефакта написаны",
          os.path.exists(out)
          and os.path.exists(out.replace(".md", ".json")), out)


def test_verdict():
    # Немедленная остановка: селектор ниже медианы случайных.
    wf = {"points": [{"day": 1, "pick": "A", "elig": 2}] * 3,
          "sel": {"total_bp": -50.0, "dd_bp": -60.0, "trades": 100},
          "ora": {"total_bp": 500.0, "dd_bp": 0.0, "trades": 100},
          "ref": {"total_bp": 10.0, "dd_bp": -20.0, "trades": 100},
          "rnd": [{"total_bp": float(v), "dd_bp": -10.0, "trades": 90}
                  for v in range(10)], "span_days": 21}
    v = T.verdict(wf)
    check("селектор ниже медианы случайных — немедленная остановка",
          "ОСТАНОВКА" in v["status"], v["status"])
    # До календаря §8.2 — диагностика, не вердикт.
    wf["sel"]["total_bp"] = 100.0
    v = T.verdict(wf)
    check("до 8 точек и 300 сделок вердикта нет",
          "диагностика" in v["status"], v["status"])
    check("нет точек — честное объяснение",
          "журнал" in T.verdict(None)["status"],
          T.verdict(None)["status"])


if __name__ == "__main__":
    test_variants()
    test_legs()
    test_outcome()
    test_slots()
    test_selector()
    test_kill_arm()
    test_artifacts_survive_fresh_checkout()
    test_verdict()
    if FAIL:
        print(f"\nПАДЕНИЙ: {len(FAIL)} — " + "; ".join(FAIL))
        sys.exit(1)
    print("\nвсе проверки прошли")
