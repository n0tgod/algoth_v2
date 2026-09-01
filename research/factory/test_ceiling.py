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


def artifact(pend_daily, pend_trades, live, pend_rule=None,
             record_days=None, live_trades=500):
    """Артефакт суточного прогона с заявкой и живыми книгами.

    Фикстура обязана быть ВОЗМОЖНОЙ для живого писателя: дневной ряд
    заводит день только от закрытой сделки (`candidate.daily_net`),
    значит суток в ряду не бывает больше, чем сделок. Прежняя фикстура
    измеримости несла семь сделок при сорока сутках ряда — комбинацию,
    которой живой прогон не производит никогда, и именно она создавала
    видимость, что ворота измеримости связывают.

    `record_days` — длина ЗАПИСИ, то самое число, которое кладёт в
    `meta` суточный прогон; по умолчанию столько, сколько суток в самом
    длинном ряду фикстуры.
    """
    rule = pend_rule or dict(SP.index_to_rule(0), geom="stop_take")
    cands = {}
    for cid, vals in live.items():
        d = series(vals)
        if len(d) > live_trades:
            raise ValueError(f"невозможная фикстура {cid}: суток {len(d)} "
                             f"при {live_trades} сделках")
        cands[cid] = {"lane": "selected", "trades": live_trades,
                      "net": sum(d.values()), "daily": d,
                      "rule": SP.index_to_rule(0)}
    pd = series(pend_daily)
    if len(pd) > pend_trades:
        raise ValueError(f"невозможная фикстура: суток {len(pd)} при "
                         f"{pend_trades} сделках — живой писатель заводит "
                         f"день только от закрытой сделки")
    if record_days is None:
        record_days = max([len(pd)] + [len(v) for v in live.values()])
    return {"meta": {"at": "тест", "record_days": record_days},
            "null_median": 0.0,
            "candidates": cands,
            "pending_why": None,
            "pending": {"key": SP.key(rule), "rule": rule,
                        "trades": pend_trades, "daily": pd}}


def three_book_pool():
    """Пул из ТРЁХ живых книг, где теснейшая связь не первая и не самая
    длинная.

    Боевой пул многокнижный (в живом артефакте пять книг, предел ста), а
    ни одна фикстура его не строила — и потому обе величины вердикта, КАК
    выбрана теснейшая книга и весь ли пул прочитан, не были закреплены
    ничем. Здесь заявка есть точная копия `live_b` в других единицах
    (`3·b + 5`), у `live_b` МЕНЬШЕ всего общих суток, а первой по
    алфавиту идёт слабо связанная `live_a`. Значит любая из трёх
    естественных подмен — взять первую измеренную, взять самую длинную
    пару, прочитать только первую книгу — даёт `pass` вместо `closed`.
    """
    b = noise(313, n=10)
    live = {"live_a": noise(323, n=40), "live_b": b, "live_c": noise(333)}
    pend = [3.0 * v + 5.0 for v in b] + noise(343, n=30)
    return pend, live


def key_sensitive_pool():
    """Пул, на котором ЧЕТЫРЕ естественных ключа выбирают РАЗНЫЕ книги.

    `three_book_pool` закрывает три поимённо названные подмены и к двум
    другим НЕЧУВСТВИТЕЛЕН по построению: там у копии связь +1.000 при
    десяти общих сутках, и взвешенный ключ (`r·days` = 10.0) выбирает ту
    же книгу, что знаковый, а зеркала в пуле нет вовсе. Фикстура, на
    которой ключи не расходятся, исполняет одну дорогу и выглядит
    исправной — ровно тот класс, которым в этом проекте кончались
    «блок есть» на пустом блоке.

    Здесь книги разведены так, что каждый ключ даёт своего победителя:

    * `live_a_broad` — 40 общих суток, связь около +0.50: побеждает по
      весу (`r·days` = 20.1 против 4.9 у настоящей теснейшей);
    * `live_b_tight` — почти копия заявки, связь +0.982 по 5 общим
      суткам: побеждает по ЗНАКОВОЙ связи, и только этот выбор даёт
      `closed`;
    * `live_c_mirror` — зеркало, связь −1.000 по 10 суткам: побеждает по
      модулю.

    Обе неверные книги стоят НИЖЕ предела связи, то есть любой из двух
    неверных ключей пропустил бы почти точную копию живой книги, а
    испытание тратится навсегда. Второе условие независимости здесь не
    выручает — эффективное `N` пула от этой заявки растёт.

    Фикстура возможна для живого писателя: суток у каждой книги много
    меньше, чем сделок, а короткий ряд `live_b_tight` — обычное дело,
    день в ряду заводит только закрытая сделка.
    """
    p = noise(1013, n=40)
    broad = [0.5 * v + w for v, w in zip(p, noise(1023, n=40, scale=30.0))]
    tight = [1.4 * v + 3.0 + w
             for v, w in zip(p[:5], noise(1033, n=5, scale=10.0))]
    mirror = [-2.0 * v + w
              for v, w in zip(p[:10], noise(1043, n=10, scale=1.0))]
    return p, {"live_a_broad": broad, "live_b_tight": tight,
               "live_c_mirror": mirror}


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
    mix_p, mix_live = None, None
    la, lb, lc = noise(401), noise(402), noise(403)
    mix_live = {"live_a": la, "live_b": lb, "live_c": lc}
    mix_p = [(x + y) / 2.0 for x, y in zip(la, lb)]
    three_p, three_live = three_book_pool()
    key_p, key_live = key_sensitive_pool()
    cases = {
        "проходит": artifact(a, 400, {"live_a": noise(202)}),
        # Многокнижные ветки судятся тем же правилом: правило,
        # закреплённое на пуле из одной книги, боевой пул не защищает.
        "копия одной из трёх": artifact(three_p, 400, three_live),
        # Пул с зеркалом отдельной веткой: переворот знака денег меняет
        # знак каждой пары на противоположный дважды, то есть связь и
        # выбор книги обязаны остаться теми же — а книга, выбранная по
        # модулю, на зеркале «не заметила бы» переворота тоже, и без
        # этой ветки правило проверялось бы только там, где зеркала нет.
        "ключи расходятся": artifact(key_p, 400, key_live),
        "смесь двух из трёх": artifact(mix_p, 400, mix_live),
        "независимая при трёх": artifact(noise(404), 400, mix_live),
        # Семь сделок — семь суток в ряду: столько, сколько живой
        # писатель и может завести. Запись при этом длиной в сорок.
        "тонкая книга": artifact(noise(102, n=7), 7, {"live_a": noise(202)},
                                 record_days=40),
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
    # Эффективное `N` пула — тем же `effective_n`, что печатает суточный
    # отчёт: вторая копия дала бы потолку своё число, и он закрывал бы
    # заявки величиной, которой у фабрики нигде больше нет.
    # Пул обязан нести ПОЛОЖИТЕЛЬНУЮ среднюю связь, иначе `effective_n`
    # подрезает её нулём и возвращает ровно номинальное число — тогда
    # сравнение «реестр против номинала» проходит на подмене молча.
    live = {"live_a": {i: v for i, v in enumerate(a)},
            "live_b": {i: v for i, v in enumerate(b)},
            "live_c": {i: 0.5 * x + 0.5 * y for i, (x, y)
                       in enumerate(zip(a, b))}}
    check("средняя связь пула положительна — номинал и эффективное "
          "разошлись", R.LG.effective_n(live)[1] > 0.05,
          str(R.LG.effective_n(live)))
    pend = {i: v for i, v in enumerate(noise(707))}
    check("N пула считается кодом реестра",
          abs(CL.pool_eff_n(live) - R.LG.effective_n(live)[0]) < 1e-12,
          f"{CL.pool_eff_n(live)} против {R.LG.effective_n(live)[0]}")
    with_p = dict(live, p=pend)
    check("N пула с заявкой — он же",
          abs(CL.pool_eff_n(live, pend, "p")
              - R.LG.effective_n(with_p)[0]) < 1e-12,
          str(CL.pool_eff_n(live, pend, "p")))
    check("номинальное число испытаний — не эффективное",
          abs(CL.pool_eff_n(with_p) - len(with_p)) > 1e-9,
          str(CL.pool_eff_n(with_p)))
    # Условие длины ряда тоже не копируется: спрашивается сам реестр.
    check("ряд короче того, что берёт реестр, пулом не считается",
          not CL.counted_by_pool({1: 1.0, 2: 2.0}), "двухдневный ряд учтён")
    check("ряд, который реестр берёт, считается",
          CL.counted_by_pool({1: 1.0, 2: 2.0, 3: 3.0}), "трёхдневный не учтён")


# --- многокнижный пул -------------------------------------------------

def test_the_whole_pool_is_read_and_the_closest_link_decides():
    """Теснейшая связь выбирается ПО ВЕЛИЧИНЕ, и читается весь пул.

    Обе величины вердикта — какая книга теснейшая и все ли книги
    прочитаны — до этой проверки не были закреплены ничем: ни одна
    фикстура не давала потолку больше одной живой книги, а в бою их
    пять при пределе в сто. Цена подмены здесь показана числом: заявка
    есть точная копия `live_b`, но первая по алфавиту `live_a` связана
    с ней слабо, и по ней вышел бы `pass` — то есть объявилась бы копия
    уже живой книги, а испытание тратится навсегда.
    """
    pend, live = three_book_pool()
    res = CL.judge(artifact(pend, 400, live))
    check("копия ВТОРОЙ книги пула закрыта", res["verdict"] == CL.CLOSED,
          f"{res['verdict']}: {res['why']}")
    check("теснейшей названа именно она",
          res["closest"]["id"] == "live_b", str(res.get("closest")))
    check("связь с ней стоит числом в причине", "+1.000" in res["why"],
          res["why"])
    ids = [lk["id"] for lk in res["links"]]
    check("прочитаны ВСЕ три живые книги",
          ids == ["live_a", "live_b", "live_c"], str(ids))
    first = res["links"][0]
    check("первая по порядку связана слабо — по ней был бы pass",
          first["id"] != res["closest"]["id"]
          and first["r"] < res["max_corr"], str(first))
    longest = max(res["links"], key=lambda lk: lk["days"])
    check("теснейшая — не самая длинная пара",
          longest["id"] != res["closest"]["id"]
          and longest["days"] > res["closest"]["days"],
          f"{longest} против {res['closest']}")


def test_the_closest_link_is_chosen_by_the_signed_correlation_itself():
    """Теснейшая — по ЗНАКОВОЙ связи: не по модулю и не со взвешиванием.

    Проверяется САМО ПРАВИЛО, а не список поимённо названных подмен.
    Оракул считается здесь же тремя строками и сверяется с тем, что
    выбрал потолок; фикстура при этом обязана быть чувствительной —
    первой же проверкой требуется, чтобы три ключа выбрали ТРИ РАЗНЫЕ
    книги. Иначе сверка исполняет одну дорогу и проходит на любой из
    подмен молча, как это и было с `three_book_pool`.
    """
    pend, live = key_sensitive_pool()
    run = artifact(pend, 400, live)
    res = CL.judge(run)
    ms = [lk for lk in res["links"] if lk["r"] is not None]
    by_signed = max(ms, key=lambda lk: lk["r"])["id"]
    by_weight = max(ms, key=lambda lk: lk["r"] * lk["days"])["id"]
    by_abs = max(ms, key=lambda lk: abs(lk["r"]))["id"]
    # Чувствительность фикстуры — раньше всего остального: проверка на
    # вырожденном пуле выглядела бы исправной, ничего не проверяя.
    check("фикстура чувствительна к ключу: три ключа — три разные книги",
          len({by_signed, by_weight, by_abs}) == 3,
          f"знаковый {by_signed}, взвешенный {by_weight}, "
          f"по модулю {by_abs}")
    check("измерены все три живые книги",
          len(ms) == 3, str(res["links"]))
    check("теснейшая выбрана по знаковой связи",
          res["closest"]["id"] == by_signed == "live_b_tight",
          f"{res['closest']} при знаковом максимуме {by_signed}")
    check("а не со взвешиванием на число общих суток",
          res["closest"]["id"] != by_weight,
          f"{res['closest']['id']} совпал с взвешенным {by_weight}")
    check("и не по модулю связи",
          res["closest"]["id"] != by_abs,
          f"{res['closest']['id']} совпал с модульным {by_abs}")
    # Цена ошибки — числом, а не рассуждением: только знаковый ключ
    # приводит к закрытию, обе неверные книги стоят ниже предела связи.
    check("по знаковому ключу заявка закрыта",
          res["verdict"] == CL.CLOSED and res["closest"]["r"] >= res["max_corr"],
          f"{res['verdict']}: {res['why']}")
    wrong = [lk for lk in ms if lk["id"] in (by_weight, by_abs)]
    check("обе неверные книги стоят НИЖЕ предела — любой из двух "
          "неверных ключей пропустил бы копию",
          all(lk["r"] < res["max_corr"] for lk in wrong), str(wrong))
    # И второе условие независимости от этой ошибки НЕ спасает. Это не
    # рассуждение: то же `pool_eff_n`, которым судит потолок.
    L = {cid: CL._days(c["daily"]) for cid, c in run["candidates"].items()}
    pd = CL._days(run["pending"]["daily"])
    before, after = CL.pool_eff_n(L), CL.pool_eff_n(L, pd, res["id"])
    check("рост N пула копию НЕ закрывает — выбор книги несущий",
          after > before, f"{before:.2f} → {after:.2f}")
    check("зеркало в пуле при этом не выдаёт себя за теснейшую",
          min(ms, key=lambda lk: lk["r"])["id"] == "live_c_mirror"
          and min(lk["r"] for lk in ms) < -0.99, str(ms))


def test_the_pair_numbers_belong_to_the_closest_book():
    """`N` пары и общие сутки описывают ТУ ЖЕ книгу, что названа теснейшей.

    Подмена книги здесь вердикта не меняет, и потому проходила молча, а
    фраза отчёта становилась самоопровергающей: «повторяют `X` со связью
    +0.98 по 5 общим суткам — пара несёт эффективное N 1.33», тогда как
    эта пара несёт 1.01. Одна строка отчёта описывала бы другую пару, чем
    соседняя.
    """
    pend, live = key_sensitive_pool()
    run = artifact(pend, 400, live)
    res = CL.judge(run)
    cid = res["closest"]["id"]
    pd = CL._days(run["pending"]["daily"])
    L = {k: CL._days(c["daily"]) for k, c in run["candidates"].items()}
    want = CL.pair_eff_n(pd, L[cid])
    check("N пары посчитано по ТЕСНЕЙШЕЙ книге",
          abs(res["pair_eff_n"] - want) < 1e-3,
          f"{res['pair_eff_n']} против {want:.3f} у `{cid}`")
    # Проверка не пустая только там, где подмена число МЕНЯЕТ.
    others = {k: CL.pair_eff_n(pd, v) for k, v in L.items() if k != cid}
    check("на этой фикстуре любая другая книга дала бы другое число",
          all(abs(v - want) > 0.05 for v in others.values()),
          f"{want:.3f} против {others}")
    first = res["links"][0]["id"]
    check("первая измеренная книга — не теснейшая: подмена видна",
          first != cid and abs(others[first] - want) > 0.3,
          f"{first} даёт {others.get(first)}, теснейшая {want:.3f}")
    check("общих суток названо столько же, сколько у этой пары",
          res["closest"]["days"] == len(set(pd) & set(L[cid])) == 5,
          f"{res['closest']['days']} против "
          f"{len(set(pd) & set(L[cid]))}")
    check("число пары стоит в самой причине вердикта",
          f"{res['pair_eff_n']:.2f}" in res["why"], res["why"])
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), res, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("в отчёте названа та же книга",
          f"| с какой книгой | {cid} |" in text, text[:900])
    check("в отчёте те же общие сутки этой пары",
          f"| общих суток у этой пары | {res['closest']['days']} |" in text,
          text[:900])
    check("в отчёте то же N пары",
          f"| эффективное N этой пары | {res['pair_eff_n']:.2f} |" in text,
          text[:900])


def test_the_pools_effective_n_must_grow():
    """Заявка, от которой эффективное `N` пула не растёт, закрывается.

    Это второе условие независимости, и оно ЗНАК, а не порог: сравнение
    идёт с нулём, подкручивать нечего. Ловит то, чего порог связи не
    видит, — заявку, смешанную из двух живых книг: с каждой по
    отдельности она связана ниже предела, а `N` пула роняет, потому что
    порог берёт максимум по парам только с заявкой, а пул усредняет
    связь по ВСЕМ парам.
    """
    la, lb, lc = noise(401), noise(402), noise(403)
    live = {"live_a": la, "live_b": lb, "live_c": lc}
    mix = [(x + y) / 2.0 for x, y in zip(la, lb)]
    res = CL.judge(artifact(mix, 400, live))
    check("смесь двух живых книг закрыта", res["verdict"] == CL.CLOSED,
          f"{res['verdict']}: {res['why']}")
    check("порог связи она при этом ДЕРЖИТ — закрыл не он",
          res["closest"]["r"] < res["max_corr"], str(res["closest"]))
    check("N пула от неё падает",
          res["pool_eff_n_with"] < res["pool_eff_n"],
          f"{res.get('pool_eff_n')} → {res.get('pool_eff_n_with')}")
    check("оба числа стоят в причине",
          f"{res['pool_eff_n']:.2f}" in res["why"]
          and f"{res['pool_eff_n_with']:.2f}" in res["why"], res["why"])
    check("причина названа ростом N, а не связью",
          "не растёт" in res["why"], res["why"])
    # Калибровочная пара: на ТОМ ЖЕ пуле независимая заявка обязана
    # пройти, иначе правило означало бы «закрывать всех подряд».
    good = CL.judge(artifact(noise(404), 400, live))
    check("независимая заявка на том же пуле проходит",
          good["verdict"] == CL.PASS, f"{good['verdict']}: {good['why']}")
    check("и N пула от неё растёт",
          good["pool_eff_n_with"] > good["pool_eff_n"],
          f"{good.get('pool_eff_n')} → {good.get('pool_eff_n_with')}")
    check("рост назван числами в причине pass",
          f"{good['pool_eff_n']:.2f} → {good['pool_eff_n_with']:.2f}"
          in good["why"], good["why"])
    # Величина не та же, которой мерит порог связи, — и это весь смысл
    # второго условия. Совпади они, оно было бы переодетым первым.
    check("N пула — не N пары",
          abs(res["pool_eff_n_with"] - res["pair_eff_n"]) > 0.05,
          f"{res['pool_eff_n_with']} против {res['pair_eff_n']}")
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), res, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("оба числа пула стоят в отчёте",
          f"| эффективное N пула без заявки | {res['pool_eff_n']:.2f} |"
          in text
          and f"| эффективное N пула с заявкой | "
              f"{res['pool_eff_n_with']:.2f} |" in text, text[:900])


def test_the_growth_condition_is_not_rendered_on_a_degenerate_pool():
    """На пустом и единичном пуле `N_eff` вырожден — и это СЛОВАМИ.

    Прочерк в таблице читался бы как «посчитали и ничего не вышло»,
    тогда как условия там не существует вовсе. Вырожденность считается
    по книгам, чей ряд пул ВООБЩЕ берёт: пул, где виден один ряд, для
    `N_eff` ничем не лучше пула из одной книги.
    """
    one = CL.judge(artifact(noise(411), 400, {"live_a": noise(412)}))
    check("на пуле из одной книги число не считалось",
          one.get("pool_eff_n") is None and one.get("pool_eff_n_with") is None,
          f"{one.get('pool_eff_n')}/{one.get('pool_eff_n_with')}")
    check("причина названа словами",
          "не выносится вовсе" in (one.get("pool_eff_n_why") or ""),
          str(one.get("pool_eff_n_why")))
    check("книга при этом всё равно проходит",
          one["verdict"] == CL.PASS, f"{one['verdict']}: {one['why']}")
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), one, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("в отчёте условие снято СЛОВАМИ, а не прочерком",
          "По этому условию вердикт НЕ выносился" in text
          and one["pool_eff_n_why"] in text, text[-900:])
    check("числа пула при этом прочерками",
          "| эффективное N пула без заявки | — |" in text, text[:900])
    # Книга, которую пул не считает, в двойку живых не идёт: иначе
    # «рост с 1.00 до 2.00» означал бы только то, что заявка существует.
    run = artifact(noise(421), 400,
                   {"live_a": noise(422), "live_b": noise(423)})
    run["candidates"]["live_b"]["daily"] = series([1.0, 2.0])
    res = CL.judge(run)
    check("слишком короткий ряд соседа в двойку не идёт",
          res.get("pool_eff_n") is None
          and "считает, 1 " in (res.get("pool_eff_n_why") or ""),
          str(res.get("pool_eff_n_why")))
    # И обратная сторона: на двух ПОЛНЫХ книгах условие выносится.
    ok = CL.judge(artifact(noise(421), 400,
                           {"live_a": noise(422), "live_b": noise(423)}))
    check("на двух полных книгах условие выносится",
          ok.get("pool_eff_n") is not None
          and not ok.get("pool_eff_n_why"), str(ok.get("pool_eff_n_why")))


def test_pending_days_are_counted_not_zeroed():
    """«Суток со сделками у заявки» — посчитанное число, а не ноль.

    Строка добавлена ради того, чтобы отделить ДЛИНУ ЗАПИСИ от суток
    книги; занулись она молча, и таблица утверждала бы «измерено и
    равно нулю» — ровно то, от чего отделяет прочерк в соседних
    строках.
    """
    run = artifact(noise(431, n=12), 400, {"live_a": noise(432)},
                   record_days=40)
    res = CL.judge(run)
    check("суток заявки посчитаны", res.get("pending_days") == 12,
          str(res.get("pending_days")))
    check("и это не длина записи",
          res["pending_days"] != res["days"],
          f"{res['pending_days']} и {res['days']}")
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), res, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("в отчёте стоит посчитанное число, а не ноль",
          "| из них суток со сделками у заявки | 12 |" in text, text[:600])
    # Та же строка на закрытой ветке: величина кладётся до развилки, и
    # проверка одной ветки не защищает остальные.
    thin = CL.judge(artifact(noise(433, n=7), 7, {"live_a": noise(434)},
                             record_days=40))
    check("на закрытой ветке суток заявки тоже посчитаны",
          thin["verdict"] == CL.CLOSED and thin.get("pending_days") == 7,
          f"{thin['verdict']}/{thin.get('pending_days')}")


# --- измеримость ------------------------------------------------------

def test_the_fixture_is_possible_for_a_live_writer():
    """Инвариант живого писателя: суток в ряду не больше, чем сделок.

    Проверяется НАСТОЯЩИМ писателем (`candidate.daily_net`), а не
    рассуждением: из этого инварианта и следует, что знаменатель
    измеримости нельзя брать по суткам самой книги — вклад заявки в
    такой знаменатель всегда покрыт её же числителем.
    """
    import candidate as CD                                   # noqa: E402
    trades = [{"exit": (DAY0 + i) * 86400.0 + 100.0, "net": 5.0, "w": 1.0}
              for i in range(7)]
    d = CD.daily_net(trades)
    check("суток в ряду не больше, чем сделок",
          len(d) <= len(trades), f"{len(d)} против {len(trades)}")
    one = CD.daily_net([dict(t, exit=DAY0 * 86400.0 + 100.0)
                        for t in trades])
    check("семь сделок одного дня дают один день ряда",
          len(one) == 1, str(sorted(one)))
    try:
        artifact(noise(61), 7, {})
        refused = False
    except ValueError:
        refused = True
    check("невозможная фикстура отвергнута", refused,
          "40 суток ряда при 7 сделках прошли как живая запись")


def test_the_denominator_is_the_record_not_the_books():
    """Знаменатель измеримости — ДЛИНА ЗАПИСИ, а не активность книг.

    Вето адверсария было ровно здесь: `n_days` считался объединением
    суток, в которые торговал хоть кто-то. У живой книги суток не
    больше, чем сделок, поэтому её вклад в такой знаменатель всегда
    покрыт её же числителем, и отношение падало ниже единицы только за
    счёт чужих суток. Не приносит их никто — ворота не связывают вовсе.
    """
    lonely = CL.judge(artifact([12.0], 1, {}, record_days=40))
    check("одна сделка за сорок суток записи закрыта",
          lonely["verdict"] == CL.CLOSED,
          f"{lonely['verdict']}: {lonely['why']}")
    check("в причине стоит длина записи, а не сутки книги",
          "за 40 суток" in lonely["why"], lonely["why"])
    # Тот же случай при непустом пуле: заявка торговала в те же трое
    # суток, что живая книга, — по старому знаменателю ровно 1.00.
    three = [1.0, -2.0, 3.0]
    shared = CL.judge(artifact(three, 3, {"live_a": three[:]},
                               record_days=90))
    check("три сделки в те же трое суток, что у живого, закрыты",
          shared["verdict"] == CL.CLOSED,
          f"{shared['verdict']}: {shared['why']}")
    own_rate = 3 / 3.0
    check("по суткам самой книги это ровно порог — то есть pass",
          own_rate >= CL.MIN_TRADES_PER_DAY, str(own_rate))
    # И ворота не закрывают всё подряд: та же запись, больше сделок.
    fine = CL.judge(artifact(noise(71), 400, {"live_a": noise(72)},
                             record_days=40))
    check("книга со сделками каждый день записи проходит",
          fine["verdict"] == CL.PASS, f"{fine['verdict']}: {fine['why']}")


def test_an_old_artifact_has_no_denominator_and_waits():
    """Длины записи в артефакте нет — кандидат ЖДЁТ.

    Молчаливый откат к суткам книг вернул бы ровно тот дефект, ради
    которого поле заведено, и выглядел бы исправным вердиктом.
    """
    run = artifact(noise(81), 400, {"live_a": noise(82)})
    del run["meta"]["record_days"]
    res = CL.judge(run)
    check("артефакт прежнего образца — undetermined",
          res["verdict"] == CL.UNDET, f"{res['verdict']}: {res['why']}")
    check("причина называет само поле", "record_days" in res["why"],
          res["why"])
    check("суток записи — прочерк, а не число", res.get("days") is None,
          str(res.get("days")))
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), res, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("в отчёте суток записи стоит прочерком",
          "| суток записи | — |" in text, text[:400])


def test_the_measurability_threshold_cannot_be_softened():
    """Порог измеримости закреплён ЗНАЧЕНИЕМ, а не комментарием.

    Тридцать сделок за сорок суток записи — 0.75 в сутки: выше
    половины порога и ниже самого порога. Уполовиненный порог такую
    книгу пропустил бы, и до этой проверки правка проходила молча.
    """
    res = CL.judge(artifact(noise(91, n=30), 30, {"live_a": noise(92)},
                            record_days=40))
    check("книга ниже порога закрыта", res["verdict"] == CL.CLOSED,
          f"{res['verdict']}: {res['why']}")
    check("скорость в причине посчитана", "0.75" in res["why"], res["why"])
    check("порог выведен из окна вылета, а не назначен",
          abs(CL.MIN_TRADES_PER_DAY
              - CL.MIN_TRADES_IN_WINDOW / float(R.PL.WINDOW_D)) < 1e-12,
          str(CL.MIN_TRADES_PER_DAY))
    check("объявленное значение закреплено числом",
          CL.MIN_TRADES_IN_WINDOW == 10
          and abs(CL.MIN_TRADES_PER_DAY - 1.0) < 1e-12,
          f"{CL.MIN_TRADES_IN_WINDOW}/{CL.MIN_TRADES_PER_DAY}")


def test_a_mirror_book_is_not_closed():
    """Связь ЗНАКОВАЯ: зеркало потолком не закрывается.

    Это решение, а не описка: пул считает информацию положительной
    связью — отрицательная подрезается нулём в `ledger.effective_n`, —
    и потолок обязан мерить ту же величину.

    Что ловит ИМЕННО эта проверка, а что нет: здесь закреплено
    СРАВНЕНИЕ с порогом — правка `abs(best["r"]) >= max_corr` её роняет.
    Правку `abs()` в ВЫБОРЕ книги она не ловит и никогда не ловила: в
    пуле из одной живой книги выбирать не из чего, и её прежняя
    docstring обещала защиту, которой не было. Выбор закреплён отдельно,
    на пуле с расходящимися ключами
    (`test_the_closest_link_is_chosen_by_the_signed_correlation_itself`).
    """
    live = noise(303)
    res = CL.judge(artifact([-v for v in live], 400, {"live_a": live}))
    check("зеркало проходит: для знаменателя пула это испытание",
          res["verdict"] == CL.PASS, f"{res['verdict']}: {res['why']}")
    check("связь и правда около −1", res["closest"]["r"] < -0.99,
          str(res["closest"]))


def test_day_keys_are_numbers_not_text():
    """День — номер суток, и читатель обязан вернуть ему тип.

    Строки сравниваются как текст: `'998' > '1000'`. Сегодня ни одна
    ветка потолка от порядка дней не зависит, но день в этом проекте
    всюду число (`pool.window_net` сравнивает арифметически), и первая
    же величина, посчитанная по окну, посчиталась бы по алфавиту.
    """
    got = CL._days({"998": 1.0, "1000": 2.0, "1001": 3.0})
    check("ключ дня — число",
          all(isinstance(k, int) for k in got), str(sorted(got, key=str)))
    check("дни сравниваются арифметически, а не как текст",
          sorted(got) == [998, 1000, 1001], str(sorted(got, key=str)))


def test_thin_book_is_closed_by_the_rate():
    """Книга, дающая единицы сделок, мертва по построению.

    Фикстура возможна для живого писателя: семь сделок — семь суток в
    ряду, а запись длиной в сорок суток. Прежняя несла семь сделок при
    сорока сутках ряда, и ворота «связывали» только благодаря этому.
    """
    run = artifact(noise(707, n=7), 7, {"live_a": noise(808)},
                   record_days=40)
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
                              {"live_a": noise(111, n=8)}, record_days=8))
    long_ = CL.judge(artifact(noise(909, n=20), 20,
                              {"live_a": noise(111, n=60)}, record_days=60))
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
    run = artifact([], 0, {"live_a": noise(131)}, record_days=40)
    run["candidates"]["live_a"]["trades"] = 0
    res = CL.judge(run)
    check("сломанный реплей — undetermined, а не closed",
          res["verdict"] == CL.UNDET, f"{res['verdict']}: {res['why']}")
    check("причина названа поломкой", "реплей" in res["why"], res["why"])
    alive = artifact([], 0, {"live_a": noise(131)}, record_days=40)
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
    # Оговорка про окно вылета считается ТЕМ ЖЕ порогом, которым
    # принято решение. Литерал `MIN_TRADES_IN_WINDOW` стоял здесь и
    # опровергал собственный вывод: «это 100.0 сделки при 10, то есть
    # подбрасывание монеты» — сто больше десяти.
    want = 50.0 * R.PL.WINDOW_D
    check("окно вылета в фразе считается тем же порогом",
          f"при требуемых {want:.1f}" in thin["why"], thin["why"])
    check("фраза не опровергает саму себя",
          f"при {CL.MIN_TRADES_IN_WINDOW}," not in thin["why"], thin["why"])


def test_the_report_prints_the_threshold_that_decided():
    """Отчёт печатает то число, которым решено, а не константу модуля.

    Потолок зовут с порогом аргументом, и константа в отчёте
    противоречила бы строке вердикта в том же файле: «общих суток
    меньше 12» вверху и «меньше 3» десятью строками ниже.
    """
    run = artifact(noise(241), 400, {"live_a": noise(251)})
    run["candidates"]["live_a"]["daily"] = series([1.0, 2.0, 3.0, 4.0, 5.0])
    res = CL.judge(run, min_pair_days=12)
    check("при своём пороге связь неизмерима",
          res["verdict"] == CL.UNDET, f"{res['verdict']}: {res['why']}")
    check("порог решения стоит в вердикте", "меньше 12" in res["why"],
          res["why"])
    tmp = tempfile.mkdtemp()
    md = CL.write_report(os.path.join(tmp, "C.md"), res, log=lambda *a: None)
    text = open(md, encoding="utf-8").read()
    check("в отчёте стоит порог, по которому решено",
          "меньше 12" in text, text[-600:])
    check("константа модуля в отчёт не просочилась",
          f"меньше {CL.MIN_PAIR_DAYS}," not in text, text[-600:])


# --- журнал -----------------------------------------------------------

def test_journal_records_changes_not_the_schedule():
    """Строка на КАЖДЫЙ вызов сделала бы журнал записью расписания."""
    tmp = tempfile.mkdtemp()
    res = CL.judge(artifact(noise(191, n=7), 7, {"live_a": noise(211)},
                            record_days=40))
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


def write_span_sheets(path, days=3, hours=3, syms=6):
    """Листы на несколько СУТОК, где гейт пропускает только последние.

    Нужно, чтобы «до отсева» и «после отсева» давали РАЗНОЕ число
    суток: иначе проверка порядка проверяла бы пустоту.
    """
    t0 = 1_780_000_000
    with open(path, "w", encoding="utf-8") as f:
        for d in range(days):
            for h in range(hours):
                at = t0 + d * 86400 + h * H
                rows = []
                for i in range(syms):
                    mag = 70.0 if d == days - 1 else 10.0
                    fwd = mag * (1 if i % 2 == 0 else -1)
                    rows.append(TRD.sheet_row(f"C{i}USDT", fwd, fwd / 30.0))
                f.write(json.dumps({
                    "hour": "2026-08-%02d-%02d" % (10 + d, h),
                    "written_at": at,
                    "arms": {"gbm": rows, "nn": rows}}) + "\n")
    return t0


def test_the_record_window_is_measured_before_the_gates():
    """Длину записи кладёт прогон, и меряет её ДО гейтов кандидата.

    Гейты не вправе укорачивать собственный знаменатель: книга,
    берущая ноги трёх часов, судилась бы окном в трое суток и проходила
    бы ворота измеримости построением.
    """
    legs = [{"at": 86400.0 * 20600 + 10.0},
            {"at": 86400.0 * 20600 + 20.0},
            {"at": 86400.0 * 20603 + 5.0}]
    check("сутки считаются, а не берутся размахом",
          R.record_days(legs) == 2, str(R.record_days(legs)))
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out")
    os.makedirs(out)
    base = os.path.join(tmp, "ledger")
    os.makedirs(base)
    sheets = os.path.join(tmp, "sheets.jsonl")
    t0 = write_span_sheets(sheets)
    live = dict(SP.index_to_rule(0), floor_bp=44, width=3, geom="stop_take")
    props = os.path.join(tmp, "proposals.jsonl")
    with open(props, "w", encoding="utf-8") as f:
        f.write(json.dumps({"rule": live}) + "\n")
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
        all_legs = R.load_legs(sheets, log=lambda *a: None)
        kept = R.needed_legs(all_legs, [R.CD.with_geometry(live)],
                             log=lambda *a: None)
        check("гейт и правда отсёк часть ног",
              art["meta"]["legs"] < len(all_legs),
              f"{art['meta']['legs']} из {len(all_legs)}")
        check("после гейта суток осталось бы меньше",
              R.record_days(kept) == 1, str(R.record_days(kept)))
        check("окно записи — все сутки журнала, а не сутки прошедших ног",
              art["meta"].get("record_days") == 3,
              str(art["meta"].get("record_days")))
        md = open(os.path.join(out, "FACTORY-day-t.md"),
                  encoding="utf-8").read()
        check("суток записи названы в отчёте отдельно от суток со сделками",
              "| суток записи в журнале листов | 3 |" in md
              and "| суток со сделками хоть у кого-то |" in md, "")
    finally:
        R.PROPOSALS, R.SW.read_bars, R.publish = was_p, was_b, was_pub


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
        # Дорога числа до вердикта проверяется целиком: величина, верная
        # в прогоне и не доехавшая до потолка, выглядит исправной с
        # обоих концов.
        check("потолок судил по длине записи из прогона",
              res.get("days") == art["meta"].get("record_days"),
              f"{res.get('days')} против {art['meta'].get('record_days')}")
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
             test_the_whole_pool_is_read_and_the_closest_link_decides,
             test_the_closest_link_is_chosen_by_the_signed_correlation_itself,
             test_the_pair_numbers_belong_to_the_closest_book,
             test_the_pools_effective_n_must_grow,
             test_the_growth_condition_is_not_rendered_on_a_degenerate_pool,
             test_pending_days_are_counted_not_zeroed,
             test_the_fixture_is_possible_for_a_live_writer,
             test_the_denominator_is_the_record_not_the_books,
             test_an_old_artifact_has_no_denominator_and_waits,
             test_the_measurability_threshold_cannot_be_softened,
             test_a_mirror_book_is_not_closed,
             test_day_keys_are_numbers_not_text,
             test_thin_book_is_closed_by_the_rate,
             test_required_trades_grow_with_the_record,
             test_empty_is_undetermined_and_never_pass,
             test_zero_trades_everywhere_is_a_broken_replay,
             test_unmeasured_link_is_a_dash_not_a_zero,
             test_no_live_books_is_a_pass_with_a_dash,
             test_the_phrase_is_derived_from_the_numbers,
             test_the_report_prints_the_threshold_that_decided,
             test_journal_records_changes_not_the_schedule,
             test_main_writes_both_forms_and_publishes,
             test_missing_run_is_a_named_refusal_not_zeros,
             test_the_record_window_is_measured_before_the_gates,
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
