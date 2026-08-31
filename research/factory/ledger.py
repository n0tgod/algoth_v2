"""Реестр испытаний фабрики — журнал событий, а не таблица состояний.

Строка на СОБЫТИЕ (объявили кандидата, отправили в отставку), состояние
выводится перечитыванием. Так же устроен журнал исполнительного ядра, и
по той же причине: переписываемую таблицу нельзя проверить задним
числом, а журнал говорит, что и когда было решено. Момент объявления —
единственное, от чего считается форвард кандидата (§5 спеки 13), и
переписать его нечем.

Три правила реестра, каждое из уроков проекта:

* **`N` печатается рядом с любым числом фабрики.** Число без своего
  знаменателя испытаний не публикуется — ошибка R5 стоила проекту
  месяца ровно на этом.
* **Эффективное `N` МЕРЯЕТСЯ, а не считается номинально.**
  Параметрические соседи — почти одна ставка, и сто книг с попарной
  связью 0.9 несут информации меньше десяти независимых.
* **Число вылетевших — обязательное число отчёта.** Без знаменателя
  выжившие нечитаемы: «лучшая из ста» и «лучшая из ста, где девяносто
  выбыли» — разные утверждения.

Модуль на стандартной библиотеке: его читают и суточный прогон, и
страницы, а страницы живут в процессе записи стакана.
"""

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = "ledger.jsonl"

DECLARE = "declare"
RETIRE = "retire"
LANES = ("selected", "control")


def path(base=None):
    return os.path.join(base or HERE, LEDGER)


def read(base=None):
    """События реестра и число НЕразобранных строк.

    Битая строка пропускается, но считается: молча потерянный кандидат
    сдвинул бы знаменатель испытаний, а это и есть то число, ради
    которого реестр существует.
    """
    p = path(base)
    rows, bad = [], 0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(r, dict) and r.get("ev") in (DECLARE, RETIRE):
                    rows.append(r)
                else:
                    bad += 1
    except OSError:
        return [], 0
    return rows, bad


def state(rows):
    """Состояние кандидатов по журналу: id → запись.

    Отставка приходит ОТДЕЛЬНЫМ событием, поэтому у кандидата виден и
    момент объявления, и момент вылета с причиной — по одной таблице
    состояний этого было бы не восстановить.
    """
    st = {}
    for r in rows:
        cid = r.get("id")
        if not cid:
            continue
        if r["ev"] == DECLARE:
            if cid in st:
                continue          # дубль объявления — первое главнее
            st[cid] = {"id": cid, "rule": r.get("rule"),
                       "lane": r.get("lane"), "seed": r.get("seed"),
                       "note": r.get("note"),
                       "declared_at": r.get("at"),
                       "retired_at": None, "why": None}
        elif cid in st and st[cid]["retired_at"] is None:
            st[cid]["retired_at"] = r.get("at")
            st[cid]["why"] = r.get("why")
    return st


def active(st):
    return {k: v for k, v in st.items() if v["retired_at"] is None}


def retired(st):
    return {k: v for k, v in st.items() if v["retired_at"] is not None}


def _append(row, base=None):
    p = path(base)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def declare(cid, rule, lane, seed=None, at=None, base=None, source=None,
            note=None):
    """Объявить кандидата. Возвращает причину отказа или None.

    Отказ, а не исключение: суточный прогон объявляет пятерых, и
    падение на третьем оставило бы реестр в состоянии, которого никто
    не выбирал.
    """
    if lane not in LANES:
        return f"полоса {lane!r} не объявлена"
    st = state(read(base)[0])
    if cid in st:
        return f"кандидат {cid} уже в реестре"
    # Довод, по которому кандидат предложен, хранится вместе с ним:
    # судится ВЫБОР ассистента, и запись без причины выбора описывала
    # бы результат, но не то, что его породило.
    _append({"ev": DECLARE, "id": cid, "at": at or _now(), "rule": rule,
             "lane": lane, "seed": seed, "source": source,
             "note": note}, base)
    return None


def retire(cid, why, at=None, base=None):
    st = state(read(base)[0])
    if cid not in st:
        return f"кандидата {cid} в реестре нет"
    if st[cid]["retired_at"] is not None:
        return f"кандидат {cid} уже отставлен"
    _append({"ev": RETIRE, "id": cid, "at": at or _now(), "why": why}, base)
    return None


def _now():
    return round(time.time(), 1)


def spent(st):
    """Сколько испытаний потрачено — по полосам и всего.

    Считаются ВСЕ объявленные, включая вылетевших: испытание потрачено
    в момент объявления, и вылет его не возвращает.
    """
    out = {"total": len(st), "active": len(active(st)),
           "retired": len(retired(st))}
    for lane in LANES:
        out[lane] = sum(1 for v in st.values() if v["lane"] == lane)
        out[lane + "_active"] = sum(
            1 for v in active(st).values() if v["lane"] == lane)
    return out


def effective_n(series):
    """Эффективное число испытаний по попарной связи дневных денег.

    `series` — id → {день: деньги}. Сто книг, ходящих вместе, несут
    информации меньше десяти независимых, и номинальное `N` тогда
    льстит. Формула стандартная: `N / (1 + (N−1)·средняя связь)`, связь
    считается по общим дням и снизу подрезается нулём — отрицательная
    средняя связь означала бы `N_eff > N`, а больше собственных
    наблюдений у нас не появляется.
    """
    ids = [k for k, v in series.items() if len(v) >= 3]
    n = len(ids)
    if n < 2:
        return float(n), 0.0
    tot, cnt = 0.0, 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = series[ids[i]], series[ids[j]]
            days = sorted(set(a) & set(b))
            if len(days) < 3:
                continue
            xs = [a[d] for d in days]
            ys = [b[d] for d in days]
            r = _corr(xs, ys)
            if r is not None:
                tot += r
                cnt += 1
    if not cnt:
        return float(n), 0.0
    mean_r = max(0.0, tot / cnt)
    return n / (1.0 + (n - 1) * mean_r), mean_r


def _corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / (sxx ** 0.5 * syy ** 0.5)
