"""Кусаются ли подделки правил ПРОГОНА (`run_squeeze.py`).

Зачем отдельно от `controls_check.py`: приёмка держит предел на число
объявленных контролей (`runlog.BUILD_MAX_CONTROLS` = 24), и все 24 слота
заняты правилами МЕРЫ. У прогона своё правило — ПОРЯДОК УБИЙЦ: пока
сторона ленты и покрытие журнала не измерены, касса не трогается
(`run_squeeze.run`, два досрочных возврата). Оно закрыто проверкой
`test_run_counts_money_only_after_side_and_coverage`, но слота в отчёте
постройки ей не осталось, а проверка без укуса ничего не проверяет.
Поэтому укус показывается здесь и той же машиной, что у приёмки
(`runlog._run_tests`: свой каталог байткода на прогон — иначе `.pyc`
предыдущей подделки исполняется вместо новой, и врёт это в обе стороны).

Обе подделки минимальны: снимают ровно досрочный возврат, синтаксис не
ломают. Восстановление — из прочитанного в память исходника, в
`finally`, и никогда `git checkout`.

    .venv/bin/python research/mech_357a7c60/controls_run.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import runlog as RL                                            # noqa: E402

TESTS = "research/mech_357a7c60/test_squeeze_fuel.py"
FILE = "research/mech_357a7c60/run_squeeze.py"

CONTROLS = [
    {"old": "    if not side.get(\"ok\"):",
     "new": "    if False:",
     "expect": "ПАДЕНИЕ порядок: сторона не измерена — денег не считали"},
    {"old": "    if (cover[\"share\"] or 0) < SQ.COVER_BLOCK:",
     "new": "    if False:",
     "expect": "ПАДЕНИЕ порядок: покрытие ниже половины — денег не считали"},
]


def main():
    p = os.path.join(ROOT, FILE)
    bad = []
    ok, out = RL._run_tests(ROOT, TESTS)
    print("база: " + ("зелёная" if ok else "КРАСНАЯ — дальше смысла нет"))
    if not ok:
        print(out[-1500:])
        return 1
    for i, c in enumerate(CONTROLS, 1):
        with open(p, encoding="utf-8") as f:
            src = f.read()
        if src.count(c["old"]) != 1:
            bad.append(f"подделка {i}: строка встречается "
                       f"{src.count(c['old'])} раз, нужна ровно одна")
            continue
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src.replace(c["old"], c["new"], 1))
            fell, out = RL._run_tests(ROOT, TESTS)
        finally:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src)
        if fell:
            bad.append(f"подделка {i} НЕ КУСАЕТСЯ: прошла мимо тестов")
        elif c["expect"] not in out:
            # Укус, неразборчивый снаружи, считается холостым: подделка
            # 1 сперва роняла сюиту трассировкой из недр чтения потока,
            # и какое правило исчезло, по выводу видно не было.
            bad.append(f"подделка {i}: упало не то, что обещано — "
                       f"{c['expect']!r} в выводе нет")
        else:
            print(f"подделка {i} кусается: {c['expect']}")
    for b in bad:
        print("  БЕДА: " + b)
    print("ИТОГ: " + ("все подделки кусаются" if not bad else "ЕСТЬ ХОЛОСТЫЕ"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
