"""Сквозной прогон фабрики на синтетике.

У одноразового прогона дорог несколько — объявление, реплей, нуль,
отсев, отчёт, публикация, — и «тесты зелёные» значит ровно те дороги,
которые тесты ИСПОЛНЯЮТ. Урок S11: там прогон падал по очереди на
печати, на статистике ячейки и на сборке отчёта, и каждое падение
видно было только исполнением.

Публикация здесь ПОДМЕНЯЕТСЯ, а не выключается флагом: сквозной тест
D1 звал настоящий `publish.sh` и уцелел только потому, что публиковать
было нечего.
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger as LG                                        # noqa: E402
import run_day as R                                        # noqa: E402
import space as SP                                         # noqa: E402

FAILED = []
H = 3600.0


def check(name, ok, got=""):
    print(("  ok   " if ok else "  ПРОВАЛ ") + name
          + ("" if ok else f" — {got}"))
    if not ok:
        FAILED.append(name)


def sheet_row(sym, fwd, fz):
    sign = 1 if fwd > 0 else -1
    return {"sym": sym, "fwd": fwd, "fz": fz, "fwd_z": fz,
            "mae": -sign * 40.0, "mfe": sign * 120.0,
            "mae_q": -sign * 50.0, "mfe_q": sign * 120.0,
            "px": 100.0, "beta": 1.0}


def write_sheets(path, hours=6, syms=8):
    t0 = 1_780_000_000
    with open(path, "w", encoding="utf-8") as f:
        for h in range(hours):
            at = t0 + h * H
            rows = []
            for i in range(syms):
                fwd = (60.0 + 5 * i) * (1 if i % 2 == 0 else -1)
                rows.append(sheet_row(f"C{i}USDT", fwd, fwd / 30.0))
            f.write(json.dumps({
                "hour": "2026-08-31-%02d" % h, "written_at": at,
                "arms": {"gbm": rows, "nn": rows}}) + "\n")
    return t0


def fake_bars(t0):
    """Бары, на которых исход существует у любой геометрии."""
    def read(root, sym, a, b):
        out, t = [], int(a // 60) * 60
        px = 100.0
        i = 0
        while t <= b:
            drift = 1.0 + 0.00004 * i * (1 if sym.endswith("0USDT") else -1)
            p = px * drift
            out.append((float(t), p, p * 1.004, p * 0.996, p))
            t += 60
            i += 1
        return out
    return read


def setup(tmp):
    base = os.path.join(tmp, "ledger")
    os.makedirs(base, exist_ok=True)
    sheets = os.path.join(tmp, "sheets.jsonl")
    t0 = write_sheets(sheets)
    props = os.path.join(tmp, "proposals.jsonl")
    good1 = SP.index_to_rule(0)
    good2 = dict(good1, width=5, rank="sigma")
    bad = dict(good1, width=7)                    # значения нет в оси
    far = dict(good1, target="fwd_24h")           # неисполнимо сегодня
    # Негодное и неисполнимое стоят ПЕРВЫМИ: в конце списка их
    # отсекал бы предел партии, и проверка не отличала бы «отвергнуто
    # правилом» от «не хватило места» — контроль на снятую проверку
    # исполнимости на таком порядке не кусался.
    with open(props, "w", encoding="utf-8") as f:
        for r in (bad, far, good1, good2):
            f.write(json.dumps({"rule": r}) + "\n")
        f.write("{битая строка\n")
    return base, sheets, props, t0


def test_end_to_end():
    tmp = tempfile.mkdtemp()
    base, sheets, props, t0 = setup(tmp)
    was_p, was_b, was_pub = R.PROPOSALS, R.SW.read_bars, R.publish
    calls = []
    R.PROPOSALS = props
    R.SW.read_bars = fake_bars(t0)
    R.publish = lambda *a, **k: calls.append(a)
    try:
        out = os.path.join(tmp, "out")
        rc = R.main(["--sheets", sheets, "--root", tmp, "--out", out,
                     "--base", base, "--tag", "t", "--seed", "42",
                     "--no-publish"])
        check("прогон дошёл до конца", rc == 0, str(rc))
        st = LG.state(LG.read(base)[0])
        keys = set(st)
        check("годные предложения объявлены",
              SP.key(SP.index_to_rule(0)) in keys, str(sorted(keys))[:120])
        check("негодное правило не объявлено",
              not any(st[k]["rule"].get("width") == 7 for k in keys), "")
        check("неисполнимое правило не объявлено",
              not any(st[k]["rule"].get("target") == "fwd_24h"
                      for k in keys), "")
        lanes = {k: v["lane"] for k, v in st.items()}
        # Контроль добирается ДО ДОЛИ ПУЛА: при двух кандидатах
        # четверть равна половине книги, то есть нулю. Ожидание «в
        # первой же партии обязан быть случайный» было моим, а не
        # правила — проверяется само правило.
        want_ctl = int(round(0.25 * len(st)))
        got_ctl = sum(1 for v in lanes.values() if v == "control")
        check("случайных ровно столько, сколько просит доля пула",
              got_ctl == want_ctl, f"{got_ctl} против {want_ctl}")
        rep = os.path.join(out, "FACTORY-day-t.md")
        check("отчёт написан", os.path.exists(rep))
        md = open(rep, encoding="utf-8").read()
        check("число испытаний в отчёте", "объявлено всего" in md)
        check("эффективное N в отчёте", "эффективное N" in md)
        check("линия нуля в отчёте", "нуль (медиана" in md)
        check("вердикт выведен из чисел",
              "вердикта нет" in md or "фабрика закрывается" in md
              or "впереди случайных" in md, md[:200])
        check("сделки посчитаны",
              "| сделок |" in md and "`" in md, "")
        check("с флагом публикации не было", not calls, str(calls))
        rc = R.main(["--sheets", sheets, "--root", tmp, "--out", out,
                     "--base", base, "--tag", "t", "--seed", "42",
                     "--no-declare"])
        check("без флага публикация обязана случиться",
              rc == 0 and len(calls) == 1, str(calls))
        st2 = LG.state(LG.read(base)[0])
        check("повторный прогон не задваивает кандидатов",
              len(st2) == len(st), f"{len(st2)} против {len(st)}")
    finally:
        R.PROPOSALS, R.SW.read_bars, R.publish = was_p, was_b, was_pub


def test_null_keeps_the_book_and_shuffles_the_future():
    """Нуль обязан менять ИСХОДЫ, а не состав книги."""
    tmp = tempfile.mkdtemp()
    base, sheets, props, t0 = setup(tmp)
    was_b = R.SW.read_bars
    R.SW.read_bars = fake_bars(t0)
    try:
        legs = R.load_legs(sheets, log=lambda *a: None)
        outs = R.outcomes_for(legs, tmp, R.geometries(),
                              log=lambda *a: None)
        rule = SP.index_to_rule(0)
        import candidate as B
        real = B.simulate(legs, outs, B.with_geometry(rule))
        nulls = R.null_daily(legs, outs, rule, seeds=3)
        check("нуль посчитан", len(nulls) == 3, str(len(nulls)))
        n_tr = [len(d) for d in nulls]
        check("у нуля есть дни со сделками", any(n_tr), str(n_tr))
        # Состав книги не меняется: те же ноги, другой форвард.
        shifted = B.simulate(legs, outs, B.with_geometry(rule))
        check("реальный прогон воспроизводим",
              [t["sym"] for t in real] == [t["sym"] for t in shifted])
    finally:
        R.SW.read_bars = was_b


def test_only_needed_legs_are_priced():
    """Бары читаются только за ногами, которые кто-то возьмёт.

    Отбор спрашивает саму `passes` — ту же функцию, которой книга
    потом берёт ногу. Оценка «слабейшим гейтом» разошлась бы с ней при
    первом же добавлении оси, и состав сделок изменился бы молча.
    """
    import candidate as C
    legs = [{"fwd": 10.0, "rr": 3.0, "sym": "A", "id": 0},
            {"fwd": 90.0, "rr": 3.0, "sym": "B", "id": 1}]
    rules = [C.with_geometry(dict(SP.index_to_rule(0), floor_bp=30))]
    got = R.needed_legs(legs, rules, log=lambda *a: None)
    check("нога ниже гейта не оценивается",
          [g["sym"] for g in got] == ["B"], str([g["sym"] for g in got]))
    check("без кандидатов берутся все",
          len(R.needed_legs(legs, [], log=lambda *a: None)) == 2)


def test_zero_outcomes_is_a_failure_not_a_quiet_day():
    """Ноль исходов при непустых ногах — поломка чтения баров.

    Первый живой прогон отчитался кодом 0 и пустым отчётом: имя модуля
    перекрыло чужое, загрузчик падал на каждом символе, а снаружи это
    выглядело исправной фабрикой без сделок.
    """
    tmp = tempfile.mkdtemp()
    base, sheets, props, _t0 = setup(tmp)
    was_p, was_b, was_pub = R.PROPOSALS, R.SW.read_bars, R.publish
    R.PROPOSALS = props
    R.SW.read_bars = lambda *a, **k: []
    R.publish = lambda *a, **k: None
    try:
        out = os.path.join(tmp, "out")
        rc = R.main(["--sheets", sheets, "--root", tmp, "--out", out,
                     "--base", base, "--tag", "t", "--seed", "1",
                     "--no-publish"])
        check("прогон отказал, а не отчитался нулём", rc == 1, str(rc))
        check("пустой отчёт не написан",
              not os.path.exists(os.path.join(out, "FACTORY-day-t.md")))
    finally:
        R.PROPOSALS, R.SW.read_bars, R.publish = was_p, was_b, was_pub


def test_declaration_passes_only_the_ceiling_gate():
    """Объявляется ТОЛЬКО то, что потолок пропустил, и только сегодня.

    Объявление — единственное необратимое действие фабрики: с этой
    минуты кандидат тратит испытание и судится вперёд. Поэтому каждый
    отказ обязан быть НАЗВАН: «не прошёл» и «не считался» лечатся
    по-разному, а молчание одинаково выглядит и там, и там.

    Проверяется и правило, и дорога: круг обязан звать объявление
    ПОСЛЕ потолка, а суточный прогон в круге — не объявлять сам.
    """
    import declare as DEC
    import cycle as CY

    d = tempfile.mkdtemp()
    was_pub = R.publish
    R.publish = lambda *a, **k: None
    try:
        rule = SP.index_to_rule(0)
        key = SP.key(rule)
        run_path = os.path.join(d, "factory-day-t.json")

        def put(verdict="pass", cid=None, prop_rule=None, run_age=0.0):
            # Порядок записи повторяет круг: сперва числа судьи, потом
            # вердикт потолка. Вердикт, оказавшийся старше чисел,
            # судил не их — на этом и стоит одни из ворот.
            with open(os.path.join(d, R.PROPOSAL_NAME), "w",
                      encoding="utf-8") as f:
                json.dump({"proposed": True,
                           "rule": prop_rule or rule}, f)
            with open(run_path, "w", encoding="utf-8") as f:
                json.dump({"meta": {}}, f)
            if run_age:
                t = os.path.getmtime(run_path) - run_age
                os.utime(run_path, (t, t))
            cp = os.path.join(d, "ceiling.json")
            with open(cp, "w", encoding="utf-8") as f:
                json.dump({"verdict": verdict, "why": "проба",
                           "id": cid or key, "rule": rule}, f)
            t = os.path.getmtime(run_path) + 1.0
            os.utime(cp, (t, t))

        def run():
            DEC.main(["--out", d, "--base", d, "--tag", "t",
                      "--seed", "7", "--no-publish"])
            with open(os.path.join(d, "declare.json"),
                      encoding="utf-8") as f:
                res = json.load(f)
            return res, LG.state(LG.read(d)[0])

        # Потолок сказал «нет» — в реестре пусто, причина названа.
        put(verdict="closed")
        res, st = run()
        check("закрытое потолком не объявляется",
              key not in st and "closed" in (res.get("why") or ""),
              str(res.get("why")))
        # Контроль добирается и в день без заявки: его доля — свойство
        # пула, а не заявки.
        check("случайная рука добирается и без заявки",
              res["controls"] == len(st) and len(st) > 0,
              f"{res['controls']} против {len(st)}")

        # Вердикт о ДРУГОМ кандидате не объявляет сегодняшнюю заявку.
        put(prop_rule=SP.index_to_rule(1))
        res, st = run()
        check("вердикт о другом кандидате отвергнут",
              key not in st and "другом" in (res.get("why") or ""),
              str(res.get("why")))

        # Вчерашние числа описывают другой пул.
        put(run_age=2 * 86400.0)
        res, st = run()
        check("вердикт по вчерашнему прогону отвергнут",
              key not in st and "прогону за" in (res.get("why") or ""),
              str(res.get("why")))

        # Вердикт вчерашний: числа сегодняшние, а судил их вердикт,
        # вынесенный до них.
        put()
        cp = os.path.join(d, "ceiling.json")
        t = os.path.getmtime(cp) - 2 * 86400.0
        os.utime(cp, (t, t))
        res, st = run()
        check("вчерашний вердикт сегодня не объявляет",
              key not in st and "вердикт потолка за" in (res.get("why") or ""),
              str(res.get("why")))

        # Вердикт старше чисел, которые судит, — он судил не их.
        put()
        t = os.path.getmtime(run_path) - 60.0
        os.utime(cp, (t, t))
        res, st = run()
        check("вердикт раньше чисел отвергнут",
              key not in st and "РАНЬШЕ" in (res.get("why") or ""),
              str(res.get("why")))

        # Всё сошлось — объявляем.
        put()
        res, st = run()
        check("прошедшее потолок объявлено",
              key in st and res.get("candidate") == key, str(res))
        # Источник живёт в СОБЫТИИ реестра, а не в сводном состоянии:
        # сводка отвечает «что живо», журнал — «чем это объявлено».
        rows = [r for r in LG.read(d)[0]
                if r.get("id") == key and r.get("ev") == LG.DECLARE]
        check("источник объявления назван потолком",
              bool(rows) and rows[-1].get("source") == "ceiling",
              str(rows[-1:]))

        # Повтор испытания не тратит.
        res, st2 = run()
        check("повтор не объявляется дважды",
              "уже в реестре" in (res.get("why") or ""),
              str(res.get("why")))

        # Дорога круга: объявление стоит ПОСЛЕ потолка, а судья в
        # круге не объявляет сам.
        order = [k for k, _kind, _argv, _proof in CY.CIRCLE]
        check("объявление идёт после потолка",
              order.index("declare") > order.index("ceiling")
              > order.index("judge"), str(order))
        judge = [c for c in CY.CIRCLE if c[0] == "judge"][0]
        check("судья в круге не объявляет сам",
              "--no-declare" in (judge[2] or []), str(judge[2]))
    finally:
        R.publish = was_pub
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (test_end_to_end,
             test_declaration_passes_only_the_ceiling_gate,
             test_only_needed_legs_are_priced,
             test_zero_outcomes_is_a_failure_not_a_quiet_day, test_null_keeps_the_book_and_shuffles_the_future)
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
