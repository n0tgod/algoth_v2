"""Проверки потолка заявки.

Главное требование к этому файлу — чтобы проверки КУСАЛИСЬ. В проекте
десятками находились проверки, проходившие на пустом блоке, искавшие
фразу в соседнем комментарии или исполнявшие другую дорогу. Поэтому:

* правило «по доходности не судим» закреплено ДВАЖДЫ — переворотом
  знака всех дневных денег и умножением их на положительное число;
* калибровочная пара обязательна: подсаженную связь потолок обязан
  найти, а на случайном блуждании промолчать — сломанный расчёт связи
  выглядит ровно как «книги независимы», и это уже дважды случалось;
* пустота проверяется отдельно от нуля: «не измерено» и «измерено и
  равно нулю» — разные утверждения, и первое обязано быть прочерком.

Подставной артефакт выглядит как ЖИВОЙ: дневной ряд со строковыми
ключами (JSON чисел в ключах не знает), поля `lane`, `trades`, `net`,
`rule` — те же, что пишет суточный прогон. Фикстура, не похожая на
живую запись, исполняет другую дорогу, а выглядит исправной.
"""

import json
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ceiling as CL                                         # noqa: E402
import run_day as R                                          # noqa: E402
import space as SP                                           # noqa: E402
import test_run_day as TRD                                   # noqa: E402

FAILED = []
H = 3600.0
DAY0 = 20600          # номер суток, как их считает `candidate.daily_net`


def check(name, ok, got=""):
    print(("  ok   " if ok else "  ПРОВАЛ ") + name
          + ("" if ok else f" — {got}"))
    if not ok:
        FAILED.append(name)


# --- фикстуры ---------------------------------------------------------

def series(vals, start=DAY0):
    """Дневной ряд, каким его кладёт в артефакт `json.dump`: ключ дня
    строкой. Ряд с числовыми ключами не пересёкся бы с прочитанным из
    файла ни одним днём, и проверка исполняла бы другую дорогу."""
    return {str(start + i): float(v) for i, v in enumerate(vals)}


def noise(seed, n=40, scale=30.0):
    """Случайное блуждание дневных денег. Зерно закреплено ЧИСЛОМ: нуль,
    который нельзя повторить, не является проверяемым (урок R3)."""
    rnd = random.Random(seed)
    return [rnd.gauss(0.0, scale) for _ in range(n)]


def artifact(pend_daily, pend_trades, live, pend_rule=None):
    """Артефакт суточного прогона с заявкой и живыми книгами."""
    rule = pend_rule or dict(SP.index_to_rule(0), geom="stop_take")
    cands = {}
    for cid, vals in live.items():
        d = series(vals)
        cands[cid] = {"lane": "selected", "trades": 500,
                      "net": sum(d.values()), "daily": d,
                      "rule": SP.index_to_rule(0)}
    pd = series(pend_daily)
    return {"meta": {"at": "тест"}, "null_median": 0.0,
            "candidates": cands,
            "pending_why": None,
            "pending": {"key": SP.key(rule), "rule": rule,
                        "trades": pend_trades, "daily": pd}}


def flip(run):
    """Знак ВСЕХ дневных денег наоборот — и заявки, и живых книг."""
    return _scale(run, -1.0)


def _scale(run, k):
    out = json.loads(json.dumps(run))
    for c in out["candidates"].values():
        c["daily"] = {d: k * v for d, v in c["daily"].items()}
        c["net"] = k * c["net"]
    out["pending"]["daily"] = {d: k * v
                               for d, v in out["pending"]["daily"].items()}
    return out


# --- по доходности не судим ------------------------------------------

def test_profit_never_decides():
    """Переворот знака денег не меняет вердикта НИ В ОДНОЙ ветке.

    Отбирая по прошлому, фабрика объявляла бы только то, что уже
    выглядело хорошо на записи, и вердикт вперёд терял бы смысл — это
    ошибка R5. Проверяются все ветки разом, а не одна: правило,
    закреплённое на единственном случае, не защищает остальные.
    """
    a = noise(101)
    cases = {
        "проходит": artifact(a, 400, {"live_a": noise(202)}),
        "тонкая книга": artifact(a, 7, {"live_a": noise(202)}),
        "копия живого": artifact(a, 400, {"live_a": a}),
        "живых нет": artifact(a, 400, {}),
    }
    for name, run in cases.items():
        was = CL.judge(run)
        now = CL.judge(flip(run))
        check(f"знак денег не меняет вердикта — {name}",
              was == now, f"{was.get('verdict')}/{was.get('why')} против "
                          f"{now.get('verdict')}/{now.get('why')}")
        big = CL.judge(_scale(run, 7.0))
        check(f"величина денег не меняет вердикта — {name}",
              was == big, f"{was.get('why')} против {big.get('why')}")
    check("ветки в наборе разные",
          len({CL.judge(r)["verdict"] for r in cases.values()}) >= 2,
          str([CL.judge(r)["verdict"] for r in cases.values()]))


# --- калибровочная пара ----------------------------------------------

def test_calibration_finds_a_planted_link_and_is_silent_on_noise():
    """Подсаженную связь потолок обязан найти, на шуме — промолчать.

    Без этой пары сломанный расчёт связи выглядит ровно как «книги
    независимы», то есть как разрешение объявлять.
    """
    live = noise(303)
    same = CL.judge(artifact(live, 400, {"live_a": live}))
    check("копия живой книги закрывается",
          same["verdict"] == CL.CLOSED, f"{same['verdict']}: {same['why']}")
    check("в причине стоит само число связи",
          "+1.000" in same["why"], same["why"])
    # Тот же ряд в других единицах и с другим уровнем — та же ставка.
    scaled = [3.0 * v + 11.0 for v in live]
    same2 = CL.judge(artifact(scaled, 400, {"live_a": live}))
    check("масштабированная копия — та же ставка",
          same2["verdict"] == CL.CLOSED, same2["why"])
    indep = CL.judge(artifact(noise(404), 400, {"live_a": live}))
    check("независимый ряд проходит",
          indep["verdict"] == CL.PASS, f"{indep['verdict']}: {indep['why']}")
    r = indep["closest"]["r"]
    check("связь на шуме далека от предела",
          abs(r) < 0.5, str(r))


def test_the_pool_measure_is_not_reimplemented():
    """Связь и эффективное `N` считает `ledger`, а не вторая копия.

    Копия формулы разошлась бы с той, которой фабрика печатает своё `N`,
    и потолок закрывал бы кандидатов, которых пул считает независимыми.
    """
    a, b = noise(505), noise(606)
    r, days = CL.pair_corr({i: v for i, v in enumerate(a)},
                           {i: v for i, v in enumerate(b)})
    want = R.LG._corr(a, b)
    check("связь считается кодом реестра", abs(r - want) < 1e-12,
          f"{r} против {want}")
    check("общие сутки посчитаны", days == len(a), str(days))


# --- измеримость ------------------------------------------------------

def test_thin_book_is_closed_by_the_rate():
    """Книга, дающая единицы сделок, мертва по построению."""
    run = artifact(noise(707), 7, {"live_a": noise(808)})
    res = CL.judge(run)
    check("тонкая книга закрыта", res["verdict"] == CL.CLOSED, res["why"])
    check("в причине стоит и число сделок, и порог",
          "7 сделок" in res["why"] and "1.00" in res["why"], res["why"])
    fat = CL.judge(artifact(noise(707), 400, {"live_a": noise(808)}))
    check("та же книга с достаточным числом сделок проходит",
          fat["verdict"] == CL.PASS, fat["why"])


def test_required_trades_grow_with_the_record():
    """Требуется СКОРОСТЬ, а не абсолютное число: порог, стоящий
    литералом, означал бы разное на записи в неделю и в год."""
    short = CL.judge(artifact(noise(909, n=8), 20,
                              {"live_a": noise(111, n=8)}))
    long_ = CL.judge(artifact(noise(909, n=60), 20,
                              {"live_a": noise(111, n=60)}))
    check("двадцати сделок хватает на восьми сутках",
          short["verdict"] == CL.PASS, short["why"])
    check("тех же двадцати не хватает на шестидесяти",
          long_["verdict"] == CL.CLOSED, long_["why"])


# --- пустота не выдаёт себя за результат ------------------------------

def test_empty_is_undetermined_and_never_pass():
    """Посчитать нечем — кандидат ЖДЁТ, а не проходит по умолчанию."""
    cases = {
        "артефакта нет": None,
        "заявки нет": {"candidates": {}, "pending": None,
                       "pending_why": "заявка h4_x уже в реестре"},
        "суток нет": artifact([], 400, {}),
    }
    for name, run in cases.items():
        res = CL.judge(run)
        check(f"{name} — undetermined", res["verdict"] == CL.UNDET,
              f"{res['verdict']}: {res['why']}")
        check(f"{name} — причина названа словами",
              len(res["why"]) > 20, res["why"])
    res = CL.judge(cases["заявки нет"])
    check("причина из артефакта доехала до вердикта",
          "уже в реестре" in res["why"], res["why"])


def test_zero_trades_everywhere_is_a_broken_replay():
    """Ноль сделок У ВСЕХ книг — сломанный реплей, а не мёртвая заявка.

    Тем же правилом суточный прогон отказывает при нуле исходов: первый
    живой прогон отчитался кодом 0 и пустым отчётом, и снаружи это
    выглядело исправной фабрикой без сделок.
    """
    run = artifact(noise(121), 0, {"live_a": noise(131)})
    run["candidates"]["live_a"]["trades"] = 0
    res = CL.judge(run)
    check("сломанный реплей — undetermined, а не closed",
          res["verdict"] == CL.UNDET, f"{res['verdict']}: {res['why']}")
    check("причина названа поломкой", "реплей" in res["why"], res["why"])
    alive = artifact(noise(121), 0, {"live_a": noise(131)})
    res2 = CL.judge(alive)
    check("та же заявка при живых соседях закрыта по измеримости",
          res2["verdict"] == CL.CLOSED, f"{res2['verdict']}: {res2['why']}")


def test_unmeasured_link_is_a_dash_not_a_zero():
    """Связь, которой нет, — прочерк. Ноль читался бы как «измерено и
    книги независимы», то есть как разрешение объявлять."""
    run = artifact(noise(141, n=30), 400,
                   {"live_a": noise(151, n=30)})
    # У живой книги всего двое общих суток с заявкой.
    run["candidates"]["live_a"]["daily"] = series([1.0, 2.0], start=DAY0)
    res = CL.judge(run)
    check("неизмеримая связь не даёт pass",
          res["verdict"] == CL.UNDET, f"{res['verdict']}: {res['why']}")
    check("связь стоит None, а не нулём",
          res["links"][0]["r"] is None, str(res["links"]))
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), res, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("в отчёте прочерк, а не ноль",
          "| — |" in text and "| +0.000 |" not in text, text[:400])


def test_no_live_books_is_a_pass_with_a_dash():
    """Пустой пул: повторять нечего, связь — прочерк, но не отказ."""
    res = CL.judge(artifact(noise(161), 400, {}))
    check("при пустом пуле объявлять можно",
          res["verdict"] == CL.PASS, f"{res['verdict']}: {res['why']}")
    check("связь названа прочерком", res.get("closest") is None
          and "прочерк" in res["why"], res["why"])


# --- фраза выводится из числа ----------------------------------------

def test_the_phrase_is_derived_from_the_numbers():
    """Вердиктовая фраза собирается из посчитанных величин.

    Проза, стоящая рядом с числом литералом, однажды разойдётся со своей
    же таблицей — это уже случалось в отчёте о цене прохода лесенки.
    """
    a = noise(171)
    b = [0.7 * v + 0.3 * w for v, w in zip(a, noise(181))]
    loose = CL.judge(artifact(a, 400, {"live_a": b}), max_corr=0.99)
    tight = CL.judge(artifact(a, 400, {"live_a": b}), max_corr=0.10)
    check("порог связи попал во фразу",
          "0.99" in loose["why"] and "0.10" in tight["why"],
          loose["why"] + " | " + tight["why"])
    check("тот же ряд при разных порогах судится по-разному",
          loose["verdict"] != tight["verdict"],
          f"{loose['verdict']}/{tight['verdict']}")
    thin = CL.judge(artifact(a, 400, {"live_a": b}), min_tpd=50.0)
    check("порог сделок попал во фразу", "50.00" in thin["why"],
          thin["why"])


# --- журнал -----------------------------------------------------------

def test_journal_records_changes_not_the_schedule():
    """Строка на КАЖДЫЙ вызов сделала бы журнал записью расписания."""
    tmp = tempfile.mkdtemp()
    res = CL.judge(artifact(noise(191), 7, {"live_a": noise(211)}))
    check("первая запись прошла", CL.record(res, at=1.0, base=tmp) is None)
    again = CL.record(res, at=2.0, base=tmp)
    check("тот же вердикт второй раз не пишется", again is not None,
          str(again))
    rows, bad = CL.read_journal(tmp)
    check("в журнале ровно одна строка", len(rows) == 1 and bad == 0,
          f"{len(rows)}/{bad}")
    check("строка несёт вердикт и причину",
          rows[0]["verdict"] == CL.CLOSED and rows[0]["why"],
          str(rows[0])[:160])
    passed = CL.judge(artifact(noise(191), 400, {"live_a": noise(211)}))
    check("смена вердикта пишется",
          CL.record(passed, at=3.0, base=tmp) is None)
    rows, _bad = CL.read_journal(tmp)
    check("журнал ведёт обе стороны — и закрытых, и пропущенных",
          [r["verdict"] for r in rows] == [CL.CLOSED, CL.PASS],
          str([r["verdict"] for r in rows]))
    # Журнал потолка ОТДЕЛЬНЫЙ от реестра объявлений: закрытая потолком
    # заявка испытанием не стала и знаменатель не тратит.
    check("реестр объявлений потолком не тронут",
          not os.path.exists(os.path.join(tmp, "ledger.jsonl")))


# --- прогон целиком ---------------------------------------------------

def test_main_writes_both_forms_and_publishes():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out")
    os.makedirs(out)
    run = artifact(noise(221), 400, {"live_a": noise(231)})
    with open(os.path.join(out, "factory-day-t.json"), "w",
              encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False)
    calls = []
    was = CL.publish
    CL.publish = lambda *a, **k: calls.append(1)
    try:
        rc = CL.main(["--out", out, "--tag", "t", "--no-publish"])
        check("прогон дошёл до конца", rc == 0, str(rc))
        check("машинная форма написана",
              os.path.exists(os.path.join(out, "ceiling.json")))
        md = os.path.join(out, "CEILING-t.md")
        check("человеческая форма написана", os.path.exists(md))
        text = open(md, encoding="utf-8").read()
        check("в отчёте сказано, что по доходности не судили",
              "По доходности заявка НЕ судилась" in text, text[:200])
        check("вердикт в отчёте", CL.PASS in text, text[:200])
        check("журнал дописан",
              os.path.exists(os.path.join(out, CL.JOURNAL)))
        check("с флагом публикации не было", not calls, str(calls))
        rc = CL.main(["--out", out, "--tag", "t"])
        check("без флага публикация обязана случиться",
              rc == 0 and len(calls) == 1, str(calls))
    finally:
        CL.publish = was


def test_missing_run_is_a_named_refusal_not_zeros():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out")
    was = CL.publish
    CL.publish = lambda *a, **k: None
    try:
        rc = CL.main(["--out", out, "--tag", "t", "--no-publish"])
        check("прогон без артефакта не падает", rc == 0, str(rc))
        res = json.load(open(os.path.join(out, "ceiling.json"),
                             encoding="utf-8"))
        check("вердикт undetermined", res["verdict"] == CL.UNDET,
              res["verdict"])
        check("причина названа файлом",
              "суточного прогона нет" in res["why"], res["why"])
        check("журнал не дописан ничем",
              not os.path.exists(os.path.join(out, CL.JOURNAL)))
    finally:
        CL.publish = was


# --- заявка в суточном прогоне ---------------------------------------

def write_sheets(path, hours=24, syms=8):
    """Лист сечения, где ПОЛ ВХОДА действительно связывает: два имени
    крупных, шесть мелких. На листе, где все прогнозы крупные, пол не
    отсекает ничего, и проверка отбора ног проверяла бы пустоту."""
    t0 = 1_780_000_000
    with open(path, "w", encoding="utf-8") as f:
        for h in range(hours):
            at = t0 + h * H
            rows = []
            for i in range(syms):
                big = i < 2
                mag = 70.0 if big else (10.0 + 4 * i)
                fwd = mag * (1 if i % 2 == 0 else -1)
                rows.append(TRD.sheet_row(f"C{i}USDT", fwd, fwd / 30.0))
            f.write(json.dumps({
                "hour": "2026-08-31-%02d" % h, "written_at": at,
                "arms": {"gbm": rows, "nn": rows}}) + "\n")
    return t0


def test_pending_is_replayed_but_not_declared():
    """Заявка прогоняется теми же ногами — и объявлением не становится.

    Её гейты шире гейтов живых, и без её правила `needed_legs` отсекла бы
    её собственные ноги: заявка вышла бы мёртвой по числу сделок не
    потому, что мертва, а потому, что её ног не оценивали, — и потолок
    закрыл бы её этим числом молча.
    """
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out")
    os.makedirs(out)
    base = os.path.join(tmp, "ledger")
    os.makedirs(base)
    sheets = os.path.join(tmp, "sheets.jsonl")
    t0 = write_sheets(sheets)
    live = dict(SP.index_to_rule(0), floor_bp=44, width=3, geom="stop_take")
    pend = dict(live, floor_bp=0)
    props = os.path.join(tmp, "proposals.jsonl")
    with open(props, "w", encoding="utf-8") as f:
        f.write(json.dumps({"rule": live}) + "\n")
    with open(os.path.join(out, "proposal.json"), "w",
              encoding="utf-8") as f:
        json.dump({"proposed": True, "rule": pend}, f, ensure_ascii=False)
    was_p, was_b, was_pub = R.PROPOSALS, R.SW.read_bars, R.publish
    R.PROPOSALS = props
    R.SW.read_bars = TRD.fake_bars(t0)
    R.publish = lambda *a, **k: None
    try:
        rc = R.main(["--sheets", sheets, "--root", tmp, "--out", out,
                     "--base", base, "--tag", "t", "--seed", "5",
                     "--no-publish"])
        check("суточный прогон дошёл до конца", rc == 0, str(rc))
        art = json.load(open(os.path.join(out, "factory-day-t.json"),
                             encoding="utf-8"))
        p = art.get("pending")
        check("заявка попала в артефакт", isinstance(p, dict), str(p)[:120])
        check("у заявки свой ключ", p["key"] == SP.key(pend), p["key"])
        live_key = SP.key(live)
        lt = art["candidates"][live_key]["trades"]
        check("ноги заявки оценены: сделок у неё больше, чем у живого",
              p["trades"] > lt, f"{p['trades']} против {lt}")
        check("дневной ряд заявки в артефакте",
              isinstance(p["daily"], dict) and p["daily"], str(p)[:120])
        check("дневной ряд живого в артефакте",
              bool(art["candidates"][live_key].get("daily")), "")
        st = R.LG.state(R.LG.read(base)[0])
        check("заявка НЕ объявлена: испытание не потрачено",
              SP.key(pend) not in st, str(sorted(st)))
        md = open(os.path.join(out, "FACTORY-day-t.md"),
                  encoding="utf-8").read()
        check("отчёт называет заявку и говорит, что это не объявление",
              SP.key(pend) in md and "НЕ является" in md, "")
        # А теперь потолок судит её теми же числами.
        was_c = CL.publish
        CL.publish = lambda *a, **k: None
        try:
            CL.main(["--out", out, "--tag", "t", "--no-publish"])
        finally:
            CL.publish = was_c
        res = json.load(open(os.path.join(out, "ceiling.json"),
                             encoding="utf-8"))
        check("потолок судил именно заявку", res.get("id") == SP.key(pend),
              str(res.get("id")))
        check("вердикт из трёх объявленных",
              res["verdict"] in (CL.PASS, CL.CLOSED, CL.UNDET),
              res["verdict"])
    finally:
        R.PROPOSALS, R.SW.read_bars, R.publish = was_p, was_b, was_pub


def test_declared_proposal_is_not_pending_anymore():
    """Заявка, уже стоящая в реестре, потолком не судится: испытание
    потрачено, и судить её поздно."""
    tmp = tempfile.mkdtemp()
    rule = SP.index_to_rule(0)
    p = os.path.join(tmp, "proposal.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rule": rule}, f)
    got, why = R.pending_rule({}, p)
    check("незаявленная заявка возвращается", got == rule, str(why))
    got, why = R.pending_rule({SP.key(rule): {}}, p)
    check("объявленная не возвращается", got is None, str(got))
    check("причина названа", "уже в реестре" in (why or ""), str(why))
    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump({"rule": dict(rule, width=7)}, f)
    got, why = R.pending_rule({}, bad)
    check("негодное правило не прогоняется", got is None, str(got))
    check("причина негодности названа", "негодно" in (why or ""), str(why))
    far = os.path.join(tmp, "far.json")
    with open(far, "w", encoding="utf-8") as f:
        json.dump({"rule": dict(rule, target="fwd_24h")}, f)
    got, why = R.pending_rule({}, far)
    check("неисполнимое правило не прогоняется", got is None, str(got))
    got, why = R.pending_rule({}, os.path.join(tmp, "нет.json"))
    check("отсутствие файла — названная причина",
          got is None and "заявки нет" in (why or ""), str(why))


def main():
    tests = (test_profit_never_decides,
             test_calibration_finds_a_planted_link_and_is_silent_on_noise,
             test_the_pool_measure_is_not_reimplemented,
             test_thin_book_is_closed_by_the_rate,
             test_required_trades_grow_with_the_record,
             test_empty_is_undetermined_and_never_pass,
             test_zero_trades_everywhere_is_a_broken_replay,
             test_unmeasured_link_is_a_dash_not_a_zero,
             test_no_live_books_is_a_pass_with_a_dash,
             test_the_phrase_is_derived_from_the_numbers,
             test_journal_records_changes_not_the_schedule,
             test_main_writes_both_forms_and_publishes,
             test_missing_run_is_a_named_refusal_not_zeros,
             test_pending_is_replayed_but_not_declared,
             test_declared_proposal_is_not_pending_anymore)
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
