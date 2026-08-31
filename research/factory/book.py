"""Реплей одного кандидата: строка параметров → сделки книги.

Второй копии расчётного ядра здесь нет и быть не может: ноги приходят
из журнала листов тем же `legs_from_sheets`, что у турнира политик,
исходы — тем же `leg_outcomes`, издержки — тем же `TR.ROUND_COST_BP`.
Фабрика добавляет ровно то, чего у турнира нет: ширину книги, порядок
сечения, требование согласия рук и правило размера.

Что делает каждая ось, и почему именно так:

* **пол входа** и **полоса RR** — гейты ноги, как у живой книги;
* **ширина** — число мест НА СТОРОНУ: «3+3» есть три лонга и три
  шорта, а не шесть мест на всех. Иначе в растущем рынке книга
  набралась бы одними лонгами и мерила бы бету, а не отбор;
* **порядок** решает, кому достанется место, когда проходящих больше,
  чем мест, — это правило книги, а не ось поиска, и в реплее оно
  обязано совпадать с живым сканером (тот раздаёт по модулю прогноза);
* **согласие рук** — нога берётся, только если обе руки в этот час
  выбрали то же имя и ту же сторону;
* **размер** меняет ВЕС ноги в дневном итоге, а не её исход: сделка
  та же, доля книги в ней другая.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tournament as TN                                   # noqa: E402
import trades as TR                                       # noqa: E402

DAY = 86400.0

# Полоса отношения: «низкое» и «высокое» — те же края, которыми живут
# книги sit_lo и sit (потолок 1.5 против пола 2). Середина между ними
# принадлежит обеим осям и потому не объявлена третьим значением.
RR_LO_MAX = 1.5
RR_HI_MIN = 2.0


def passes(lg, rule):
    """Проходит ли нога гейты правила (без учёта мест и согласия)."""
    if abs(lg["fwd"]) < float(rule["floor_bp"]):
        return False
    rr = lg.get("rr")
    band = rule["rr_band"]
    if band == "lo":
        # Неизмеримое отношение не есть удовлетворяющее — то же
        # правило, что у фильтра владельца на странице.
        return rr is not None and rr <= RR_LO_MAX
    if band == "hi":
        return rr is not None and rr >= RR_HI_MIN
    return True


def agreed_keys(legs):
    """Ключи (час, имя, сторона), которые выбрали ОБЕ руки.

    Согласие считается по листу, а не по сделкам: сделок у второй руки
    может не быть из-за мест, и тогда «согласие» означало бы «первой
    руке хватило места», а не «обе руки увидели одно».
    """
    seen = {}
    for lg in legs:
        k = (lg.get("hour"), lg["sym"], lg["side"])
        seen.setdefault(k, set()).add(lg["arm"])
    return {k for k, arms in seen.items() if len(arms) > 1}


def order_value(lg, rule):
    """Чем меряется место в очереди за слотом.

    Сырой порядок — модуль прогноза в б.п.; порядок в σ — модуль
    прогноза, делённого на волатильность монеты. Второй берётся из
    самого листа (`fwd_z`), а не пересчитывается: пересчёт был бы
    второй реализацией нормировки.
    """
    if rule["rank"] == "sigma":
        fz = lg.get("fz")
        return abs(fz) if fz is not None else None
    return abs(lg["fwd"])


def weight(lg, rule):
    """Вес ноги в дневном итоге по правилу размера.

    * равный доллар — единица;
    * равный риск — обратно исполняемому стопу: сделка со стопом вдвое
      теснее занимает вдвое больший вес, и тогда стоп стоит одинаково
      в деньгах (ради этой арифметики и заведена книга sit_r);
    * обратно волатильности — σ монеты выводится из самого листа как
      `fwd / fwd_z`, потому что нормировка цели уже поделила прогноз
      на неё; отдельного поля σ в листе нет.

    Неизмеримый вес — это ПРОПУСК ноги, а не вес 1.0: подставив
    единицу, мы молча смешали бы два правила размера в одной книге.
    """
    if rule["sizing"] == "equal":
        return 1.0
    if rule["sizing"] == "risk":
        # Именно `adv_q` — ИСПОЛНЯЕМЫЙ стоп, тот же уровень, которым
        # гейт RR меряет риск. Поля `adv` у ноги нет вовсе, и первая
        # версия читала его: книга с равным риском молча не дала бы ни
        # одной сделки, а выглядела бы заведённой.
        adv = abs(lg.get("adv_q") or 0.0)
        return 1.0 / adv if adv > 1e-9 else None
    fz, fwd = lg.get("fz"), lg.get("fwd")
    if fz is None or not fwd or abs(fwd) < 1e-9:
        return None
    sigma = abs(fwd) / abs(fz) if abs(fz) > 1e-9 else None
    if not sigma or sigma < 1e-12:
        return None
    return 1.0 / sigma


def simulate(legs, outs, rule):
    """Сделки книги кандидата.

    Места считаются ПО СТОРОНАМ и по рукам: у каждой руки свой счёт,
    как у всех книг проекта. Занятое имя не берётся второй раз — на
    одном счёте вторая позиция по той же паре не открывается (правило
    исполнимости, найденное владельцем).
    """
    width = int(rule["width"])
    need_agree = rule["agree"] == "yes"
    ok_keys = agreed_keys(legs) if need_agree else None
    # Очередь за слотом задаёт ПРАВИЛО, а не порядок, в котором ноги
    # пришли из журнала. Первая версия полагалась на порядок входа, и
    # проверка проходила лишь потому, что вход сортировал сам тест, —
    # то есть ось порядка не решала ничего. Ключ повторяет живой
    # сканер: час, рука, величина по правилу, имя (последнее — чтобы
    # ничья решалась одинаково от прогона к прогону).
    legs = sorted(
        legs,
        key=lambda g: (g["at"], g["arm"],
                       -(order_value(g, rule) or 0.0), g["sym"] or ""))
    trades = []
    books = {}          # (рука, сторона) -> {имя: момент выхода}
    held = {}           # рука -> {имя: момент выхода}
    for lg in legs:
        if not passes(lg, rule):
            continue
        if need_agree and (lg.get("hour"), lg["sym"],
                           lg["side"]) not in ok_keys:
            continue
        if order_value(lg, rule) is None:
            continue
        w = weight(lg, rule)
        if w is None:
            continue
        got = outs.get((lg["id"], rule["_stop"], rule["_take"],
                        rule["_age"]))
        if got is None:
            continue
        side_book = books.setdefault((lg["arm"], lg["side"]), {})
        arm_book = held.setdefault(lg["arm"], {})
        for b in (side_book, arm_book):
            for s, e in list(b.items()):
                if e <= lg["at"]:
                    del b[s]
        if lg["sym"] in arm_book or len(side_book) >= width:
            continue
        why, move, exit_ts, entry_px = got
        net = ((1 if lg["side"] == "long" else -1) * move
               - TR.ROUND_COST_BP)
        side_book[lg["sym"]] = exit_ts
        arm_book[lg["sym"]] = exit_ts
        trades.append({"at": lg["at"], "exit": exit_ts,
                       "net": round(net, 1), "w": round(w, 6),
                       "why": why, "sym": lg["sym"], "arm": lg["arm"],
                       "side": lg["side"]})
    return trades


def geometry(rule):
    """Ось геометрии → тройка (стоп, тейк, предел возраста) турнира.

    Значения те же, которыми живут книги: стоп — исполняемый
    квантильный уровень, тейк — обещанный ход в пользу, предел
    возраста — сутки горизонта сигнала.
    """
    if rule["geom"] == "timer":
        return ("no", False, 24)
    if rule["geom"] == "stop_take":
        return ("q", True, 24)
    return ("q", True, 72)


def with_geometry(rule):
    """Правило плюс поля геометрии, которых ждёт `simulate`."""
    st, tk, ag = geometry(rule)
    out = dict(rule)
    out["_stop"], out["_take"], out["_age"] = st, tk, ag
    return out


def daily_net(trades):
    """День выхода → взвешенный нетто книги в б.п. гросса.

    Вес делит долю книги между ногами того же дня: иначе правило
    размера меняло бы не распределение, а масштаб, и книги с разным
    размером нельзя было бы сравнивать между собой.
    """
    by_day = {}
    for t in trades:
        d = int(t["exit"] // DAY)
        rec = by_day.setdefault(d, [0.0, 0.0, 0])
        rec[0] += t["net"] * t["w"]
        rec[1] += t["w"]
        rec[2] += 1
    return {d: (s / w if w > 0 else 0.0) for d, (s, w, _n) in by_day.items()}


def trade_counts(trades):
    by_day = {}
    for t in trades:
        by_day[int(t["exit"] // DAY)] = by_day.get(
            int(t["exit"] // DAY), 0) + 1
    return by_day
