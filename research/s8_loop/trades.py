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


def hour_end(hour):
    """Когда час кончился. Нужно тем, кто решает, ждать ли сводку."""
    ts = _ts(hour)
    return None if ts is None else ts + 3600


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


START_BALANCE = 1000.0


def account(trades, arm, start=START_BALANCE, hold_h=HOLD_H):
    """Счёт ОДНОГО капитала: экспозиция не превышает его.

    Прежняя модель считала каждый час независимо — весь баланс делился
    на шесть позиций часа. При горизонте в четыре часа таких наборов
    одновременно открыто четыре, то есть экспозиция выходила
    ЧЕТЫРЁХКРАТНОЙ, а счёт показывал её как торговлю на тысячу. Плечо
    брать можно, но не молча и не задним числом.

    Здесь капитал один. Размер позиции при входе — доля свободных денег
    на число одновременных слотов: позиций в своём часе, умноженное на
    горизонт в часах. При шести именах и четырёх часах это двадцать
    четыре слота, то есть гросс равен капиталу — плечо ровно единица,
    как и требует фаза C.

    Свободные деньги считаются по КАССЕ: занятое возвращается только при
    закрытии позиции. Размер, посчитанный от нереализованной прибыли,
    наращивал бы плечо на растущем рынке — ровно та ошибка, которой этот
    пересчёт и посвящён.

    Функция ЧИСТАЯ и полная: она пересчитывает счёт с начала по списку
    сделок. Поэтому повторный прогон цикла не может провести те же
    сделки дважды — состояние не накапливается, а выводится.

    Возвращает `(история, баланс)` и проставляет каждой сделке `size` —
    сумму, которая в ней стоит.
    """
    # Проверка на `is not None`, а не на истинность: метка времени
    # может быть нулём, и тогда сделка молча выпадала бы из счёта —
    # тот же род ошибки, что «честный ноль не есть отсутствие
    # измерения» в замере диска.
    rows = [t for t in trades
            if t["arm"] == arm and t.get("opened_at") is not None]
    if not rows:
        return [], start
    per_hour = {}
    for t in rows:
        per_hour.setdefault(t["hour"], []).append(t)
    # В один и тот же момент ЗАКРЫТИЕ идёт раньше открытия: деньги
    # возвращаются в кассу до того, как их снова размещают. Порядок был
    # обратным, и на живых данных это дало `size = 0` у всей свежей
    # руки: при горизонте в четыре часа выход часа H совпадает со
    # входом часа H+4, и открытие пыталось занять деньги, которые ещё
    # не вернулись. Ошибка тихая — счёт при этом не падал, просто
    # переставал торговать.
    ev = []
    for t in rows:
        if t["state"] == "закрыта" and t.get("closes_at"):
            ev.append((t["closes_at"], 0, t))      # 0 — сначала выход
        ev.append((t["opened_at"], 1, t))          # 1 — потом вход
    ev.sort(key=lambda x: (x[0], x[1]))
    cash, busy, hist = start, 0.0, []
    for _, kind, t in ev:
        if kind == 1:
            slots = max(1, len(per_hour[t["hour"]]) * max(1, hold_h))
            want = (cash + busy) / slots
            # Больше свободных денег в позицию не положить. Настоящий
            # счёт ведёт себя так же, и молчать об этом нельзя: урезание
            # видно полем `size`.
            size = max(0.0, min(want, cash))
            # Округлять размер НЕЛЬЗЯ: касса уменьшается на настоящую
            # величину, и округлённая копия перестала бы сходиться с
            # ней — двадцать четыре позиции по 41.67 дают 1000.08, то
            # есть гросс выше капитала. Округляет показ.
            t["size"] = size
            cash -= size
            busy += size
        else:
            size = t.get("size") or 0.0
            pnl = size * (t.get("net_bp") or 0.0) / 1e4
            t["pnl"] = round(pnl, 2)
            cash += size + pnl
            busy -= size
            hist.append({"hour": t["hour"], "sym": t["sym"],
                         "pnl": round(pnl, 2),
                         "balance": round(cash + busy, 2)})
    return hist, round(cash + busy, 2)


def dd_money(trades, deposit=START_BALANCE):
    """Просадку — в деньгах и в долях ДЕПОЗИТА, а не позиции.

    Решение владельца, и причина видна на живом числе: шорт HFT показал
    −47.67 %, что читается как «потеряли половину», тогда как позиция
    составляет 1/24 счёта и в деньгах это −19.90 $, то есть 2 % депозита.
    Процент от позиции — факт о ЦЕНЕ, процент от депозита — факт о
    СЧЁТЕ, и решения принимаются по второму.

    Знаменателем взят стартовый депозит, а не текущий баланс: одна и та
    же прошлая сделка не должна менять свою просадку оттого, что счёт с
    тех пор вырос. Числитель — размер позиции, проставленный счётом;
    своей арифметики размера здесь нет.

    Сделка без размера остаётся без денежной просадки: ноль вместо
    неизвестного был бы наблюдением, которого не было.
    """
    n = 0
    for t in trades:
        dd, size = t.get("dd_bp"), t.get("size")
        if dd is None or not size or not deposit:
            continue
        t["dd_usd"] = round(size * dd / 1e4, 2)
        # В б.п. депозита — той же единице, в которой страница показывает
        # всё прочее, поэтому показ не заводит второго преобразования.
        t["dd_cap_bp"] = round(dd * size / deposit, 1)
        n += 1
    return n


def summary(trades, arm=None, capital=None):
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
    _unreal(rows, out, capital)
    _dd(rows, out)
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


def _dd(rows, out):
    """Просадка по сделкам: худшая, медианная и сколько их измерено.

    Ведущая единица — доли ДЕПОЗИТА (`*_cap_bp`) и деньги, потому что
    решения принимаются по ним. Процент от позиции остаётся рядом, но
    вторым: −47.67 % от позиции и −1.99 % от депозита — одно и то же
    событие, и путать их нельзя.

    Худшая отвечает на «какую просадку мы держали в моменте», медианная
    — на «а обычно сколько». Разница между ними и есть форма риска: у
    carry она была огромной, и именно это, а не среднее, убило гипотезу.

    Знаменателем служит число ИЗМЕРЕННЫХ сделок, а не всех: у сделки без
    цены входа или без сводок за часы удержания просадки нет, и считать
    её нулём значило бы разбавить статистику выдумкой.
    """
    got = sorted(t["dd_bp"] for t in rows if t.get("dd_bp") is not None)
    out["dd_measured"] = len(got)
    if not got:
        return
    out["dd_worst_bp"] = round(got[0], 1)
    out["dd_med_bp"] = round(got[len(got) // 2], 1)
    # В долях депозита сортировать надо ЗАНОВО: худшая по цене и худшая
    # по деньгам — разные сделки, если размеры позиций различаются.
    cap = sorted((t["dd_cap_bp"], t.get("dd_usd"))
                 for t in rows if t.get("dd_cap_bp") is not None)
    if cap:
        out["dd_worst_cap_bp"] = round(cap[0][0], 1)
        out["dd_worst_usd"] = cap[0][1]
        out["dd_med_cap_bp"] = round(cap[len(cap) // 2][0], 1)
        out["dd_sized"] = len(cap)
    # Открытые отдельно: у них просадка ещё может углубиться, и мешать
    # их с завершёнными значило бы выдавать незаконченное за результат —
    # та же причина, по которой не смешиваются деньги.
    live = sorted(t["dd_cap_bp"] for t in rows
                  if t["state"] == "открыта"
                  and t.get("dd_cap_bp") is not None)
    if live:
        out["dd_open_worst_cap_bp"] = round(live[0], 1)


def _unreal(rows, out, capital):
    """Переоценка открытых — отдельными полями, не смешивая с фактом."""
    op = [t for t in rows if t["state"] == "открыта"]
    # Экспозиция — по ВСЕМ открытым, а не только по переоценённым.
    # Позиция без текущей цены (книга молчит) экспозицию всё равно
    # несёт, и считать её нулём значило бы занижать плечо ровно там,
    # где с инструментом что-то не так.
    exp = sum(t["size"] for t in op if t.get("size"))
    if exp:
        out["exposure"] = round(exp, 2)
        if capital:
            out["capital"] = round(capital, 2)
            # Плечо — то, ради чего экспозицию и показывают. В долларах
            # она читается неверно, если капиталов несколько: у двух
            # рук по тысяче, и 1504 $ на вкладке «обе» — это 0.75, а
            # вовсе не полтора плеча.
            out["leverage"] = round(exp / capital, 2)
    marked = [t for t in op if t.get("unreal_net_bp") is not None]
    out["marked"] = len(marked)
    if not marked:
        return
    nets = [t["unreal_net_bp"] for t in marked]
    out["unreal_net_avg_bp"] = round(sum(nets) / len(nets), 1)
    out["unreal_win"] = round(
        sum(1 for v in nets if v > 0) / len(nets), 3)
    # Деньги — по тому же размеру позиции, что проставил счёт. Своя
    # арифметика здесь была бы вторым определением размера, и сумма на
    # странице разошлась бы с суммой в счёте.
    sized = [t for t in marked if t.get("size")]
    if sized:
        out["unreal_pnl"] = round(
            sum(t["size"] * t["unreal_net_bp"] / 1e4 for t in sized), 2)


def hour_rows(sum_dir, pairs):
    """Цена часа из почасовых сводок: `{(символ, час): {c, hi, lo}}`.

    Один загрузчик на всё, что берётся из сводок: и цена входа, и путь
    внутри удержания. Второй обход тех же файлов был бы вторым
    определением «цены часа» — ровно то, чего в проекте не заводят.

    `hi` и `lo` — крайние значения середины стакана за час, снятые из
    посекундных снимков. Значит просадка по ним есть **нижняя** оценка:
    ход внутри секунды в снимок не попал.

    Читаются только нужные символо-дни, а не весь каталог: сделок
    десятки, и обходить сводки целиком ради них незачем.
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
                        c = float(r["mid_close"])
                        # Поздняя строка часа побеждает — тот же порядок,
                        # что при сборке матриц.
                        out[(sym, h)] = {
                            "c": c,
                            "hi": float(r.get("mid_high") or c),
                            "lo": float(r.get("mid_low") or c)}
        except OSError:
            continue
    return out


def entry_prices(sum_dir, pairs):
    """Цены входа: `{(символ, час): цена}` — закрытие часа сигнала.

    Цена входа уже лежит в сводке полем `mid_close`. Значит записывать
    её в выбор было удобством, а не необходимостью: у выборов, сделанных
    до того, как поле появилось, цена НЕ потеряна — её надо прочитать.
    """
    return {k: v["c"] for k, v in hour_rows(sum_dir, pairs).items()}


def live_hours(t, hold_h=HOLD_H, now=None):
    """Часы, которые позиция прожила: от `час+1` до часа закрытия.

    Вход — на закрытии часа сигнала, то есть позиция живёт со следующего
    часа. У открытой сделки берутся только ЗАКРЫВШИЕСЯ часы: текущий час
    ещё пишется, и его крайние значения будут другими через минуту.
    """
    h0 = _ts(t.get("hour"))
    if h0 is None:
        return []
    now = now if now is not None else time.time()
    last_done = (now // 3600) * 3600            # начало текущего часа
    out = []
    for i in range(1, max(1, hold_h) + 1):
        ts = h0 + i * 3600
        if ts >= last_done:                     # час ещё не закрыт
            break
        out.append(_hour_of(ts))
    return out


def excursion(trades, rows, hold_h=HOLD_H, now=None):
    """Худший ход ПРОТИВ позиции за время удержания, в б.п.

    Отвечает на вопрос «какую просадку мы держим в моменте»: итог сделки
    говорит, чем всё кончилось, и ничего не говорит о том, сколько
    позиция была в минусе по дороге. У лонга это минимум середины, у
    шорта максимум — стороны считаются раздельно, иначе у шорта
    благоприятный ход был бы записан как просадка (эта ошибка в проекте
    уже случалась с колонкой `mae`).

    Величина ВСЕГДА ≤ 0 и берётся брутто: издержки платятся один раз на
    круг, а просадка — это то, что видно на позиции по дороге.

    Час без сводки не считается нулём — он просто не входит в замер, и
    число покрытых часов пишется рядом полем `dd_hours`. Ноль вместо
    пропуска был бы наблюдением, которого не было.
    """
    n = 0
    for t in trades:
        px0 = t.get("entry_px")
        if not px0:
            continue
        worst, at = None, None
        seen = 0
        for h in live_hours(t, hold_h, now):
            r = rows.get((t.get("sym"), h))
            if not r:
                continue
            seen += 1
            px = r["lo"] if t.get("side") == "long" else r["hi"]
            move = (px / px0 - 1.0) * 1e4
            adv = move if t.get("side") == "long" else -move
            if worst is None or adv < worst:
                worst, at = adv, h
        t["dd_hours"] = seen
        if worst is None:
            continue
        # Позиция, ни разу не уходившая в минус, имеет просадку ноль, а
        # не положительную величину: «просадка» есть ход против, и вверх
        # она не бывает.
        t["dd_bp"] = round(min(0.0, worst), 1)
        t["dd_at"] = at
        n += 1
    return n


def equity(trades, arm, rows, start=START_BALANCE, hold_h=HOLD_H,
           cost_bp=ROUND_COST_BP, now=None):
    """Почасовая кривая счёта С УЧЁТОМ открытых позиций.

    Кривая по одним закрытиям систематически льстит: позиция, уходившая
    в минус на 40 % и вернувшаяся, входит в неё мелким убытком, и
    просадка счёта выходит меньше пережитой. Здесь каждый час все живые
    позиции переоцениваются по закрытию этого часа — это и есть «сколько
    мы держали в моменте».

    Переоценка НЕТТО, как и у открытых сделок на странице: реализованный
    результат уже за вычетом круга, и брутто-отметка давала бы скачок
    вниз ровно в момент закрытия — разрыв кривой на ровном месте.

    Час, в котором хоть одну живую позицию переоценить нечем, помечается
    `full = False`: считать пропущенную ногу нулём значило бы занизить
    просадку там, где по инструменту как раз нет данных.
    """
    rowsa = [t for t in trades
             if t["arm"] == arm and t.get("opened_at") is not None]
    if not rowsa:
        return []
    alive = {}                                  # час → живые сделки
    closed_at = {}                              # час → закрытые в нём
    for t in rowsa:
        for h in live_hours(t, hold_h, now):
            alive.setdefault(h, []).append(t)
        if t["state"] == "закрыта" and t.get("closes_at"):
            closed_at.setdefault(
                _hour_of(t["closes_at"] - 1), []).append(t)
    out, bal = [], start
    for h in sorted(set(alive) | set(closed_at)):
        for t in closed_at.get(h, []):
            bal += t.get("pnl") or 0.0
        mark_sum, full = 0.0, True
        for t in alive.get(h, []):
            if t in closed_at.get(h, []):
                continue                        # уже в балансе
            r = rows.get((t["sym"], h))
            size = t.get("size") or 0.0
            if not r or not t.get("entry_px") or not size:
                if size:
                    full = False
                continue
            move = (r["c"] / t["entry_px"] - 1.0) * 1e4
            adv = move if t["side"] == "long" else -move
            mark_sum += size * (adv - cost_bp) / 1e4
        out.append({"hour": h, "eq": round(bal + mark_sum, 2),
                    "cash": round(bal, 2), "open": len(alive.get(h, [])),
                    # Переоценка ВСЕЙ живой книги на этот час. Из неё
                    # берётся «сколько мы держали в минусе одновременно»,
                    # и считать её отдельным проходом было бы вторым
                    # определением одной величины.
                    "op": round(mark_sum, 2),
                    "full": full})
    return out


def worst_open(curve, deposit=START_BALANCE):
    """Худший момент по КНИГЕ: все открытые позиции разом.

    Просьба владельца, и разница с худшей сделкой настоящая. Одна
    сделка на −2 % депозита — это одна сделка; двадцать четыре позиции,
    одновременно стоящие −8 %, — это состояние счёта, и переживать
    приходится именно его. Совпадать эти числа не обязаны: худшая сделка
    может случиться в час, когда остальные в плюсе и книга в целом
    спокойна.

    Позиции складываются СО ЗНАКОМ: прибыльные гасят убыточные, потому
    что в этот момент на счёте лежит именно сальдо. Сумма одних лишь
    убыточных была бы не просадкой, а валовым убытком — величиной,
    которой счёт никогда не видел.
    """
    if not curve:
        return None
    w = min(curve, key=lambda p: p.get("op", 0.0))
    op = w.get("op", 0.0)
    out = {"usd": round(op, 2), "hour": w["hour"], "open": w.get("open"),
           "full": w.get("full", True)}
    if deposit:
        out["cap_bp"] = round(op / deposit * 1e4, 1)
    return out


def merge(curves):
    """Общая кривая нескольких счетов: сумма по часам.

    Час, в котором у одной руки записи нет, берётся её последним
    известным значением, а не нулём: рука со счётом в тысячу не
    перестаёт стоить тысячу оттого, что в этот час у неё не было сделок.
    """
    curves = [c for c in curves if c]
    if not curves:
        return []
    hours = sorted({p["hour"] for c in curves for p in c})
    idx = [{p["hour"]: p for p in c} for c in curves]
    last = [None] * len(curves)
    out = []
    for h in hours:
        tot, op, opn, full, known = 0.0, 0, 0.0, True, False
        for i, m in enumerate(idx):
            p = m.get(h) or last[i]
            if p is None:
                continue          # рука ещё не начинала — её тут нет
            known = True
            if h in m:
                last[i] = m[h]
            tot += p["eq"]
            # Баланс переносится, переоценка — НЕТ. Часа нет в кривой
            # руки ровно тогда, когда у неё в этот час не было живых
            # позиций, то есть открытая переоценка равна нулю, а не
            # прошлой величине. Перенести её значило бы держать призрак
            # закрытой позиции в просадке книги.
            if h in m:
                op += p["open"]
                opn += p.get("op", 0.0)
            full = full and p.get("full", True)
        if known:
            out.append({"hour": h, "eq": round(tot, 2), "open": op,
                        "op": round(opn, 2), "full": full})
    return out


def max_dd(curve):
    """Максимальная просадка кривой: доля от достигнутого максимума."""
    if not curve:
        return None
    peak, depth, at, top = None, 0.0, None, None
    for p in curve:
        eq = p["eq"]
        if peak is None or eq > peak:
            peak, top = eq, p["hour"]
        if peak and eq < peak:
            d = eq / peak - 1.0
            if d < depth:
                depth, at = d, p["hour"]
    if at is None:
        return {"pct": 0.0, "at": None, "from": top, "hours": len(curve)}
    return {"pct": round(depth * 100.0, 2), "at": at, "from": top,
            "hours": len(curve),
            # Час, где хоть одну живую ногу переоценить было нечем,
            # делает просадку заниженной — и молчать об этом нельзя.
            "gaps": sum(1 for p in curve if not p.get("full"))}


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
