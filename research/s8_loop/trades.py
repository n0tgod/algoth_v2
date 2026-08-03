#!/usr/bin/env python3
"""
Сделки модели: выбор + разбор фактом = одна сущность с состоянием.

Зачем отдельный модуль
----------------------

Цикл пишет два файла: `picks.jsonl` — кого выбрал, `review.jsonl` — что
из этого вышло. По отдельности это не читается: владелец спрашивает «где
сделки», а видит два списка, между которыми надо соединять глазами.

Сделка здесь — запись со временем входа, стороной, ожиданием, сроком
закрытия и — когда срок прошёл — фактом и деньгами. Пока срок не
наступил, она **открыта**, и у неё есть прогноз, но нет исхода. Это и
есть ответ на «если сделка ещё не состоялась, хочу видеть прогноз».

Чего здесь НЕТ намеренно
------------------------

Арифметики денег. `pnl` каждой сделки считает цикл в момент разбора и
кладёт в `review.jsonl` рядом с исходом. Здесь только соединение по
ключу. Причина та же, по которой сводка бумажных сделок считается ядром
`t3_brackets`, а не своим кодом страницы: две реализации одной формулы
однажды разойдутся, и таблица покажет одно, а баланс другое.

Только стандартная библиотека: это читает страница сборщика, а тянуть
ради неё numpy незачем.
"""

import json
import os
import time
from datetime import datetime, timezone

HOLD_H = 4                        # горизонт выбора — цель fwd_4h
# Круг издержек живёт ЗДЕСЬ, а не в цикле обучения: его читают и цикл
# (при разборе), и сборщик (при переоценке открытых сделок). Две копии
# одного числа однажды разойдутся, и таблица покажет одну цену круга, а
# счёт другую. Модуль на стандартной библиотеке нарочно — его импорт не
# должен требовать numpy.
ROUND_COST_BP = 11.0


def _ts(hour):
    """`2026-08-03-17` → epoch-секунды начала часа."""
    try:
        return datetime.strptime(hour, "%Y-%m-%d-%H").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def _hour_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime(
        "%Y-%m-%d-%H")


def build(picks, reviews, now=None, hold_h=HOLD_H, px_at=None):
    """Сделки из выборов и разборов, свежие сверху.

    `picks` и `reviews` — строки соответствующих `.jsonl`.

    Про время входа
    ---------------

    `hour` — час, на ЗАКРЫТИИ которого модель приняла решение. Значит
    войти можно не раньше конца этого часа: признаки считаются по всему
    часу, и в 20:00 их ещё нет. Цель `fwd_4h` определена так же —
    движение от закрытия часа `t` до закрытия часа `t+4`.

    Первая версия ставила вход на НАЧАЛО часа и закрытие на «начало
    плюс четыре». Обе метки уезжали на час назад: обратный отсчёт врал,
    метка на графике стояла до того, как сигнал вообще существовал, а
    состояние «без исхода» наступало на час раньше срока.
    """
    now = now if now is not None else time.time()
    done = {}
    for rv in reviews or []:
        for r in rv.get("rows") or []:
            done[(rv.get("arm") or "gbm", rv.get("hour"), r.get("sym"),
                  r.get("side"))] = (r, rv)
    # Самый поздний РАЗОБРАННЫЙ час по каждой руке. Он и различает два
    # разных случая, которые прежде звались одним словом «без исхода»:
    # выбор, до которого разбор ещё не дошёл, и выбор, который разбор
    # рассмотрел и ничего не смог посчитать. Первое — ожидание, второе —
    # дефект данных, и путать их нельзя.
    last_rev = {}
    for rv in reviews or []:
        a = rv.get("arm") or "gbm"
        h = rv.get("hour") or ""
        if h > last_rev.get(a, ""):
            last_rev[a] = h
    out = []
    made = set()
    for pk in picks or []:
        arm = pk.get("arm") or "gbm"
        hour = pk.get("hour")
        # Уже записанные дубли (руки, часа) снимаются на чтении: файл
        # исправить задним числом нельзя, а показывать историю в
        # двойном объёме — значит врать в счётчике сделок.
        if (arm, hour) in made:
            continue
        made.add((arm, hour))
        h0 = _ts(hour)
        # Вход — на ЗАКРЫТИИ часа решения, а не на его начале.
        t0 = (h0 + 3600) if h0 is not None else None
        # Когда решение было принято на самом деле: цикл просыпается
        # через несколько минут после закрытия часа, и это задержка
        # входа, которую нельзя выдавать за ноль. Пишется циклом; у
        # старых записей её нет, и тогда поле остаётся пустым.
        decided = pk.get("at_ts")
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                key = (arm, hour, p.get("sym"), side)
                got, rv = done.get(key, (None, None))
                t_close = (t0 + hold_h * 3600) if t0 is not None else None
                tr = {
                    "arm": arm, "hour": hour, "sym": p.get("sym"),
                    "side": side,
                    "opened_at": t0, "closes_at": t_close,
                    "decided_at": decided,
                    "lag_sec": (round(decided - t0)
                                if decided and t0 else None),
                    "close_hour": (_hour_of(t_close) if t_close
                                   else None),
                    "expected_bp": p.get("fwd"),
                    # Цена закрытия часа сигнала — она же цена входа.
                    # Если выбор её не несёт (записан до того, как поле
                    # появилось), берётся из сводки того же часа —
                    # величина та же самая, а не приблизительная.
                    "entry_px": (p.get("px")
                                 or (px_at or {}).get(
                                     (p.get("sym"), hour))),
                    # Ожидаемый ход ПРОТИВ позиции — то, что модель
                    # обещает пережить. Без него ожидание читается как
                    # обещание пути, а это разные вещи.
                    "mae_bp": p.get("mae"),
                    "odd": p.get("odd"),
                    "ver": pk.get("ver"),
                }
                if got is not None:
                    tr.update(state="закрыта", got_bp=got.get("got"),
                              net_bp=got.get("net"), pnl=got.get("pnl"),
                              pos=got.get("pos"),
                              cost_bp=(rv or {}).get("cost_bp"),
                              hit=(got.get("got") or 0) > 0
                              if side == "long"
                              else (got.get("got") or 0) < 0)
                elif t_close is not None and now >= t_close:
                    # Срок вышел, а разбора нет. Ни в каком случае это
                    # НЕ «закрыта в ноль»: посчитать неизвестный исход
                    # нулём значило бы разбавить статистику выдумкой
                    # (урок оборванных бумажных сделок; урок A2, где
                    # бар без сделок — пропуск, а не нулевая доходность).
                    #
                    # Но случая два. Если разбор уже дошёл до БОЛЕЕ
                    # ПОЗДНЕГО часа этой руки, значит и этот он
                    # рассмотрел — выборы разбираются по возрастанию
                    # часа — и цель посчитать не смог: в удержании была
                    # дыра записи, монета выпала из универсума, беты не
                    # хватило. Это окончательно, и это дефект данных.
                    #
                    # Если позднее ничего не разобрано, разбор до него
                    # просто не дошёл: цикл идёт раз в час, и сделка
                    # ждёт своего прохода. Это ожидание, а не потеря.
                    tr.update(state=("без исхода"
                                     if last_rev.get(arm, "") > hour
                                     else "ждёт разбора"))
                else:
                    tr.update(state="открыта",
                              closes_in_sec=(t_close - now
                                             if t_close else None))
                out.append(tr)
    out.sort(key=lambda t: (t["opened_at"] or 0), reverse=True)
    return out


def summary(trades, arm=None, balance=None):
    """Сводка: закрытые — фактом, открытые — переоценкой.

    Закрытые и открытые считаются РАЗДЕЛЬНО и никогда не смешиваются в
    одну цифру. У закрытой исход известен, у открытой это лишь текущая
    отметка, которая до срока может стать любой; сложить их значило бы
    выдать незавершённое за результат.

    Размер позиции для нереализованных денег берётся так же, как его
    берёт разбор: баланс делится на число позиций ТОГО ЖЕ часа. Иначе
    получилось бы второе определение размера позиции, и деньги на
    странице разошлись бы с деньгами в счёте.
    """
    rows = [t for t in trades
            if (arm is None or t["arm"] == arm)]
    closed = [t for t in rows if t["state"] == "закрыта"]
    op = [t for t in rows if t["state"] == "открыта"]
    lost = [t for t in rows if t["state"] == "без исхода"]
    wait = [t for t in rows if t["state"] == "ждёт разбора"]
    out = {"closed": len(closed), "open": len(op),
           "no_outcome": len(lost), "awaiting": len(wait)}
    _unreal(rows, out, balance)
    if not closed:
        return out
    hits = sum(1 for t in closed if t.get("hit"))
    nets = [t.get("net_bp") for t in closed if t.get("net_bp") is not None]
    pnls = [t.get("pnl") for t in closed if t.get("pnl") is not None]
    exps = [t.get("expected_bp") for t in closed
            if t.get("expected_bp") is not None]
    gots = [t.get("got_bp") for t in closed if t.get("got_bp") is not None]
    out.update(
        hit_rate=round(hits / len(closed), 3),
        net_bp_avg=round(sum(nets) / len(nets), 1) if nets else None,
        pnl=round(sum(pnls), 2) if pnls else None,
        expected_avg=round(sum(exps) / len(exps), 1) if exps else None,
        got_avg=round(sum(gots) / len(gots), 1) if gots else None)
    # Насколько ожидание вообще похоже на факт — самое честное число в
    # этой таблице: модель может угадывать знак и при этом обещать
    # вчетверо больше, чем даёт.
    if exps and gots and len(exps) == len(gots):
        out["expected_over_got"] = (
            round(sum(abs(e) for e in exps) / max(
                sum(abs(g) for g in gots), 1e-9), 2))
    return out


def _unreal(rows, out, balance):
    """Переоценка открытых — отдельными полями, не смешивая с фактом."""
    marked = [t for t in rows if t["state"] == "открыта"
              and t.get("unreal_net_bp") is not None]
    out["marked"] = len(marked)
    if not marked:
        return
    nets = [t["unreal_net_bp"] for t in marked]
    out["unreal_net_avg_bp"] = round(sum(nets) / len(nets), 1)
    out["unreal_win"] = round(
        sum(1 for v in nets if v > 0) / len(nets), 3)
    if balance:
        # Позиций в часе столько же, сколько их выбрано, — как и в
        # разборе. Число берётся по факту, а не константой шесть:
        # ячейка сетки может выбирать другую ширину.
        per_hour = {}
        for t in marked:
            per_hour.setdefault((t["arm"], t["hour"]), []).append(t)
        money = 0.0
        for grp in per_hour.values():
            pos = balance / max(len(grp), 1)
            money += sum(pos * t["unreal_net_bp"] / 1e4 for t in grp)
        out["unreal_pnl"] = round(money, 2)


def entry_prices(sum_dir, pairs):
    """Цены входа из почасовых сводок: `{(символ, час): цена}`.

    Цена входа — закрытие часа сигнала, и она уже лежит в сводке полем
    `mid_close`. Значит записывать её в выбор было удобством, а не
    необходимостью: у выборов, сделанных до того, как это поле
    появилось, цена НЕ потеряна — её надо просто прочитать.

    Берётся то же самое поле, по которому цикл считает цели, поэтому
    второго определения «цены входа» здесь не заводится.

    Читаются только нужные символо-дни, а не весь каталог: открытых
    сделок десятки, и обходить сводки целиком ради них незачем.
    """
    want = {}
    for sym, hour in pairs:
        if not sym or not hour:
            continue
        want.setdefault((sym, hour[:10]), set()).add(hour)
    out = {}
    for (sym, day), hours in want.items():
        path = os.path.join(sum_dir, sym, day + ".jsonl")
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    h = r.get("hour")
                    if h in hours and r.get("mid_close"):
                        # Поздняя строка часа побеждает — тот же порядок,
                        # что при сборке матриц.
                        out[(sym, h)] = float(r["mid_close"])
        except OSError:
            continue
    return out


def mark(trades, prices, cost_bp=ROUND_COST_BP):
    """Проставить открытым сделкам нереализованный результат.

    `prices` — текущая цена по символу (середина стакана). Считается
    здесь, а не на странице: формула одна на весь проект, и вторая её
    запись в JavaScript однажды разошлась бы с той, по которой ведётся
    счёт.

    Величина в базисных пунктах, как и всё остальное внутри; в проценты
    её переводит показ. Нетто — за вычетом круга издержек: открытая
    сделка, показанная брутто, выглядит лучше, чем закроется, а разница
    как раз в размере типичного движения за четыре часа.
    """
    n = 0
    for t in trades:
        if t.get("state") != "открыта":
            continue
        px0, px1 = t.get("entry_px"), prices.get(t.get("sym"))
        if not px0 or not px1:
            continue
        raw = (px1 / px0 - 1.0) * 1e4
        t["cur_px"] = px1
        t["unreal_bp"] = round(raw if t["side"] == "long" else -raw, 1)
        t["unreal_net_bp"] = round(t["unreal_bp"] - cost_bp, 1)
        n += 1
    return n


def by_symbol(trades, sym):
    """Сделки одной монеты — для меток на её графике."""
    return [t for t in trades if t.get("sym") == sym]
