"""Тесты зонда сетапов. Каждая дорога исполняется, а не подразумевается.

Урок S11: у одноразового зонда дорог несколько (загрузка, замер, нули,
вердикт, отчёт, публикация), и «тесты зелёные» значит ровно те дороги,
которые тесты ИСПОЛНЯЮТ. Поэтому здесь есть и сквозной смоук с
настоящими каталогами книг, и проверка, что публикация зовётся ровно
тогда, когда её не выключили.
"""

import json
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))

import setups as S                                        # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name
          + ("" if cond else f"  · {extra}"))
    if not cond:
        FAILED.append(name)


def row(hz, arm, sym, hour, side, net, fam, ts=None):
    return {"hz": hz, "arm": arm, "sym": sym, "hour": hour,
            "side": side, "net": float(net), "pnl": float(net) / 100,
            "ts": float(ts if ts is not None else abs(hash(hour)) % 9e5),
            "fam": fam, "share": 0.5, "reason": "срок"}


def test_label_is_taken_per_decision():
    """Одно решение — один ярлык: большинство копий, ничья по имени."""
    rows = [row("h4", "gbm", "AAA", "h1", "long", 10, "tape"),
            row("z", "gbm", "AAA", "h1", "long", 10, "tape"),
            row("h24", "gbm", "AAA", "h1", "long", 10, "book"),
            # Ничья двух семейств — решается именем, а не порядком
            # чтения книг: иначе результат зависел бы от того, какую
            # книгу прочитали первой.
            row("h4", "nn", "BBB", "h1", "short", 5, "oi"),
            row("z", "nn", "BBB", "h1", "short", 5, "book")]
    lab = S.decision_labels(rows)
    check("ярлык решения — большинство копий",
          lab[("AAA", "h1", "long")] == "tape", str(lab))
    check("ничья решается именем семейства",
          lab[("BBB", "h1", "short")] == "book", str(lab))
    S.apply_labels(rows, lab)
    # Ярлык обязан ДОЕХАТЬ до строк: копия из h24 размечена `book`, но
    # решение — `tape`, и в замер она входит как `tape`. Первый
    # отрицательный контроль (подменить ярлык решения ярлыком копии)
    # эту проверку НЕ ронял — она смотрела словарь ярлыков, а не
    # дорогу до строки, то есть защищала не то место.
    h24 = next(r for r in rows if r["hz"] == "h24")
    check("ярлык решения доехал до строки, а не остался в словаре",
          h24["label"] == "tape" and h24["fam"] == "book", str(h24))
    d = {x["key"]: x for x in S.decisions(rows)}
    check("нетто решения — среднее по копиям, не сумма",
          abs(d[("AAA", "h1", "long")]["net"] - 10.0) < 1e-9
          and d[("AAA", "h1", "long")]["copies"] == 3,
          str(d[("AAA", "h1", "long")]))


def test_excess_is_measured_over_own_cell():
    """Семейство большинства в плюсовой книге НЕ получает превышения.

    Это защита от ловушки 1: `book` доминирует почти в любом прогнозе,
    и мера «сколько заработало семейство» назвала бы его лучшим
    сетапом в любой прибыльной книге. Сравнение с нулём здесь дало бы
    +50, сравнение со своей ячейкой даёт 0.
    """
    rows = []
    for i in range(60):
        rows.append(row("h4", "gbm", f"S{i}", f"h{i}", "long", 50,
                        "book"))
    a = S.analyse(rows)
    c = a["fc"]["book"][("h4", "gbm")]
    check("превышение над своей ячейкой равно нулю",
          abs(c["exc_med"]) < 1e-9 and abs(c["med"] - 50) < 1e-9,
          str(c))


def test_thin_cell_is_a_gap_not_a_zero():
    """Ячейка тоньше порога — пропуск, а не наблюдение с нулём."""
    rows = [row("h4", "gbm", f"S{i}", f"h{i}", "long", 10, "book")
            for i in range(40)]
    rows += [row("h4", "gbm", f"T{i}", f"g{i}", "long", 999, "liq")
             for i in range(5)]
    a = S.analyse(rows)
    check("тонкое семейство не попало в ячейки",
          ("liq" not in a["fc"]) or not a["fc"]["liq"],
          str(a["fc"].get("liq")))


def synth(seed=1, edge_fam="tape", edge=40.0, books=None, hours=140):
    """Синтетика: у одного семейства настоящее превышение во всех ячейках."""
    rnd = random.Random(seed)
    books = books or [b[0] for b in S.BOOKS]
    fams = ["book", "tape", "oi", "move"]
    rows = []
    for h in range(hours):
        for j in range(6):
            sym = f"S{j}"
            fam = fams[(h + j) % len(fams)]
            base = rnd.gauss(0, 60)
            for hz in books:
                for arm in ("gbm", "nn"):
                    net = base + rnd.gauss(0, 20)
                    if fam == edge_fam:
                        net += edge
                    rows.append(row(hz, arm, sym, f"H{h}", "long", net,
                                    fam, ts=1000.0 + h))
    return rows


def test_finds_a_real_setup_and_rejects_noise():
    rows = synth()
    a = S.analyse(rows)
    qual = a["qual"]
    check("семейства прошли порог измеримости", len(qual) >= 3,
          str(qual))
    n2 = S.null_decisions(a["rows"], a["decs"], qual, perms=60)
    hv = S.halves(a["rows"], qual)
    vd = S.verdict(a["res"], n2, hv)
    check("настоящий сетап найден", vd["tape"]["stable"],
          str(vd["tape"]["cond"]) + " " + str(a["res"]["tape"]["s1"]))
    others = [f for f in vd if f != "tape" and vd[f]["stable"]]
    check("шумные семейства устойчивыми не названы", not others,
          str(others))


def test_pure_noise_names_nobody():
    """На чистом шуме устойчивых сетапов быть не должно ни одного."""
    rows = synth(seed=7, edge=0.0)
    a = S.analyse(rows)
    n2 = S.null_decisions(a["rows"], a["decs"], a["qual"], perms=60)
    hv = S.halves(a["rows"], a["qual"])
    vd = S.verdict(a["res"], n2, hv)
    stable = [f for f, v in vd.items() if v["stable"]]
    check("на шуме не назван никто", not stable, str(stable))


def test_duplicate_null_is_harder_than_incell_null():
    """Нуль 2 обязан быть СТРОЖЕ нуля 1 — в этом цена повторов.

    Одно решение живёт во всех книгах разом, поэтому перемешивание
    внутри ячейки рвёт согласие ячеек, которого в реальности не было
    бы: планка выходит ниже, и слабый результат легко её перебивает.
    """
    rows = synth(seed=3, edge=0.0)
    a = S.analyse(rows)
    n2 = S.null_decisions(a["rows"], a["decs"], a["qual"], perms=60)
    n1 = S.null_incell(a["rows"], a["qual"], perms=60)
    check("планка нуля 2 выше планки нуля 1", n2["bar"] > n1["bar"],
          f"n2={n2['bar']:.2f} n1={n1['bar']:.2f}")


def mkbook(root, name, hz, hours=40, syms=6, sit=False):
    """Каталог книги, как его пишет цикл: манифест, выборы, разборы."""
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    man = {"horizon_h": 4, "situational": sit, "slots": 24}
    with open(os.path.join(d, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(man, f)
    rnd = random.Random(hash(name) % 1000)
    fams = ["book", "tape", "oi", "move"]
    pk, rv = [], []
    for h in range(hours):
        for arm in ("gbm", "nn"):
            legs = []
            for j in range(syms):
                fam = fams[(h + j) % len(fams)]
                legs.append({"sym": f"S{j}", "fwd": 40.0, "px": 100.0,
                             "mae": -30.0, "mfe": 60.0,
                             "setup": [[fam, 0.6]],
                             "train_seq": 1})
            hour = f"2026-07-{1 + h // 24:02d}-{h % 24:02d}"
            pk.append({"arm": arm, "hour": hour, "long": legs,
                       "short": []})
            rows = []
            for j, leg in enumerate(legs):
                fam = leg["setup"][0][0]
                got = rnd.gauss(0, 50) + (40.0 if fam == "tape" else 0.0)
                rows.append({"sym": leg["sym"], "side": "long",
                             "got": round(got, 1),
                             "net": round(got - 11.0, 1)})
            rv.append({"arm": arm, "hour": hour, "rows": rows,
                       "at_ts": 1.75e9 + h * 3600})
    with open(os.path.join(d, "picks.jsonl"), "w", encoding="utf-8") as f:
        for p in pk:
            f.write(json.dumps(p) + "\n")
    with open(os.path.join(d, "review.jsonl"), "w", encoding="utf-8") as f:
        for r in rv:
            f.write(json.dumps(r) + "\n")
    return d


def test_smoke_runs_every_road_to_the_report():
    """Сквозной прогон: настоящие каталоги книг → отчёт на диске."""
    root = tempfile.mkdtemp()
    try:
        for hz, name in S.BOOKS:
            mkbook(root, name, hz, hours=130)
        called = []
        orig = S.publish
        S.publish = lambda msg: called.append(msg)
        try:
            rc = S.main(["--root", root, "--perms", "40",
                         "--tag", "smoke", "--no-publish"])
        finally:
            S.publish = orig
        rep = os.path.join(HERE, "out", "SETUPS-report-smoke.md")
        txt = open(rep, encoding="utf-8").read() if os.path.exists(rep) \
            else ""
        check("сквозной прогон дошёл до конца", rc == 0, str(rc))
        check("отчёт написан файлом", len(txt) > 800, str(len(txt)))
        check("в отчёте есть таблица семейств и сверка",
              "## Семейства" in txt and "## Сверка" in txt, txt[:200])
        check("в отчёте есть мера с вычтенным направлением",
              "внутри стороны" in txt and "остаток" in txt, txt[:200])
        check("настоящий сетап виден в отчёте", "tape" in txt,
              txt[:200])
        check("публикация выключена флагом и НЕ звалась", not called,
              str(called))
        # Вторая половина той же проверки: без флага публикация
        # обязана случиться сама. «Публикует по умолчанию» однажды
        # окажется выключенным молча — так D1 потерял отчёт.
        S.publish = lambda msg: called.append(msg)
        try:
            S.main(["--root", root, "--perms", "5", "--tag", "smoke"])
        finally:
            S.publish = orig
        check("без флага публикация зовётся сама", len(called) == 1,
              str(called))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        for t in ("SETUPS-report-smoke.md", "setups-smoke.json"):
            p = os.path.join(HERE, "out", t)
            if os.path.exists(p):
                os.remove(p)


def test_side_excess_removes_the_direction_confound():
    """Семейство из одних лонгов в растущей книге НЕ получает превышения.

    Ловушка названа историей проекта («переодетый шорт беты», спека
    04): если лонги книги в этом периоде бьют шорты, то любое
    длинное семейство выглядит сетапом — за направление, а не за
    ситуацию. Сравнение внутри стороны обязано это снимать.
    """
    # Состав подобран так, чтобы медиана ЯЧЕЙКИ была нулём, а медиана
    # лонгов — плюс сотней: только тогда видно, что даёт направление, а
    # что ситуация. Семейство `beta` — одни лонги с тем же результатом,
    # что у остальных лонгов, то есть сетапа в нём нет вовсе.
    rows = []
    for i in range(60):
        rows.append(row("h4", "gbm", f"L{i}", f"h{i}", "long", 100,
                        "book"))
    for i in range(100):
        rows.append(row("h4", "gbm", f"S{i}", f"g{i}", "short", -100,
                        "book"))
    for i in range(40):
        rows.append(row("h4", "gbm", f"B{i}", f"b{i}", "long", 100,
                        "beta"))
    a = S.analyse(rows)
    c = a["fc"]["beta"][("h4", "gbm")]
    check("над всей ячейкой превышение крупное",
          c["exc_med"] > 90, str(c["exc_med"]))
    check("внутри стороны превышения нет",
          abs(c["exc_side"]) < 1e-9, str(c["exc_side"]))
    check("доля лонгов семейства названа числом",
          abs(c["long_share"] - 1.0) < 1e-9, str(c["long_share"]))


def test_account_check_counts_only_what_the_file_could_know():
    """Закрытое ПОСЛЕ записи файла счёта — не расхождение реализаций.

    Файл пишет цикл раз в час, а ситуационная книга закрывает позиции
    живым сторожем: между циклами мой обход честно богаче файла.
    Голая разность выглядела бы отказом сверки — и на первом же живом
    прогоне так и вышло (+25 и +44 доллара у ситуационных книг).
    """
    root = tempfile.mkdtemp()
    try:
        d = mkbook(root, "model", "h4", hours=10)
        rows, _, real, when = S.book_rows(d, "h4")
        for a in ("gbm", "nn"):
            with open(os.path.join(d, f"account_{a}.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"balance": 3000.0 + real[a], "start": 3000.0},
                          f)
        got = S.account_check(d, real, when)
        check("сошедшийся счёт даёт ноль",
              abs(got["gbm"]["resid"]) < 0.01, str(got["gbm"]))
        # Файл, записанный ДО последних закрытий: разность крупная, а
        # остаток обязан остаться нулём.
        late = sum(p for t, p in when["gbm"] if t >= sorted(
            t for t, _ in when["gbm"])[len(when["gbm"]) // 2])
        with open(os.path.join(d, "account_gbm.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"balance": 3000.0 + real["gbm"] - late,
                       "start": 3000.0}, f)
        mid = sorted(t for t, _ in when["gbm"])[len(when["gbm"]) // 2]
        os.utime(os.path.join(d, "account_gbm.json"), (mid - 1, mid - 1))
        got = S.account_check(d, real, when)
        check("отставший файл счёта расхождением не назван",
              abs(got["gbm"]["resid"]) < 0.01
              and abs(got["gbm"]["delta"]) > 0.01, str(got["gbm"]))
        # А настоящее расхождение обязано остаться видимым.
        with open(os.path.join(d, "account_nn.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"balance": 3000.0 + real["nn"] + 7.0,
                       "start": 3000.0}, f)
        got = S.account_check(d, real, when)
        check("настоящее расхождение названо числом",
              abs(got["nn"]["resid"] - 7.0) < 0.01, str(got["nn"]))
        check("сделки прочитаны с ярлыком сетапа",
              rows and any(r["fam"] for r in rows), str(rows[:1]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [test_label_is_taken_per_decision,
         test_excess_is_measured_over_own_cell,
         test_thin_cell_is_a_gap_not_a_zero,
         test_finds_a_real_setup_and_rejects_noise,
         test_pure_noise_names_nobody,
         test_duplicate_null_is_harder_than_incell_null,
         test_side_excess_removes_the_direction_confound,
         test_smoke_runs_every_road_to_the_report,
         test_account_check_counts_only_what_the_file_could_know]


def main():
    for t in TESTS:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)} — " + ", ".join(FAILED))
        return 1
    print(f"все проверки прошли ({len(TESTS)} блоков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
