#!/usr/bin/env python3
"""
D1 — реплей записи B1 на секундной сетке. Диагностика, вердикта нет.

Спека 11 §8: этап отвечает на «есть ли превышение над одновременной
кросс-секцией и как оно распадается с задержкой входа». Издержки,
проскальзывание обходом лесенки и вердикт — D2 и D3.

Что читается
------------

Только снимки книги сборщика: `<root>/book/<СИМВОЛ>/<час>.jsonl[.gz]`.
Из каждой строки нужны три числа — время, лучший бид, лучший аск, — а в
строке лежит вся лесенка. Полный `json.loads` на сотнях миллионов строк
стоит часы, поэтому разбор лёгкий (`mid_line`), и он **закреплён тестом
на совпадение с `json.loads` дословно**: ускорение, меняющее числа, есть
другая мера. Порчу архива при этом обрабатывает тот же код хранилища,
что и всегда — разбор передан в него параметром, а не скопирован.

Почему счёт идёт сутками
------------------------

Матрица «символы × секунды суток» на 518 именах — это 388 МБ, и она
нужна целиком: контроль 1 спрашивает, что делали ОСТАЛЬНЫЕ в ту же
секунду. Сутки берутся с часом запаса с каждой стороны: событию нужна
опора за 15 минут до и форвард на δ + h после, а без запаса края суток
молча теряли бы события — то есть выборка зависела бы от того, как
нарезан календарь.

Событие, пойманное в конце одних суток, не считается заново в начале
следующих: последнее событие символа переносится между сутками.

Имя модуля не `run.py` намеренно. Такой в проекте уже есть, и не один
(`l3_events`, `f1_carry`, `r4_costs`), а этот модуль кладёт `l3_events`
на путь импорта ради общих функций контроля — то есть `import run`
подхватил бы ЧУЖОЙ прогон. Ровно так в F3 импортировались чужие нули, и
совпади имена функций, подмену нельзя было бы заметить вовсе.

    .venv/bin/python research/d1_seconds/run_d1.py --days 8
    .venv/bin/python research/d1_seconds/run_d1.py --days 8 --jobs 4
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import detect as D                                        # noqa: E402
from store import read_hour                               # noqa: E402

BOOK_ROOT = os.path.join(RESEARCH, "b1_book", "out", "book")
PAD_SEC = 3600                    # запас по краям суток
DAY_SEC = 86400

# Круг издержек для чтения таблицы. Комиссия — тейкерский цикл по
# крипто-универсуму Bybit; спред берётся ИЗМЕРЕННЫЙ по нашей же записи,
# если рядом лежит артефакт проверки по ленте. Оценка L1 (11.7 б.п. по
# лесенке Binance) остаётся запасной и помечается как оценка: читать
# превышение против чужого числа, когда есть своё, значит льстить себе
# ровно на величину спреда — а он в момент события и есть главный
# расход.
COMMISSION_BP = 11.0
COST_ROUND_FALLBACK_BP = 11.7


def mem_available_mb():
    """Сколько памяти реально доступно. Linux; иначе `None`."""
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return None


def rss_mb():
    try:
        import resource
        return round(resource.getrusage(
            resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:                                     # noqa: BLE001
        return None


def mem_need_mb(rows, n):
    """Пик памяти на сутки, мегабайты.

    Считается по составу, а не на глаз: цены (4 Б на ячейку), индекс
    следующего наблюдения (4 Б), матрица запретов (1 Б) и разностный
    массив внутри неё пачкой строк (8 Б на пачку). Запас — треть.
    """
    per_cell = 4 + 4 + 1
    chunk = D.GUARD_CHUNK * n * 8
    return round((rows * n * per_cell + chunk) / 1e6 * 1.33, 1)


def mid_line(line):
    """Время и середина из строки снимка. Быстрый разбор трёх полей.

    Ищутся именно ключи в кавычках: `"bid":` не совпадает с `"bid_sz":`,
    а `,"t":` — с `"ts":`. Строка без нужных полей отвергается
    `ValueError` и пропускается хранилищем наравне с битой: снимок
    прежнего образца — не наблюдение с нулевой ценой.
    """
    i = line.find('"bid":')
    if i < 0:
        raise ValueError("нет bid")
    i += 6
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    bid = float(line[i:j])
    i = line.find('"ask":', j)
    if i < 0:
        raise ValueError("нет ask")
    i += 6
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    ask = float(line[i:j])
    i = line.rfind(',"t":')
    if i < 0:
        raise ValueError("нет метки времени")
    i += 5
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    return float(line[i:j]), (bid + ask) / 2.0


def hours_of(t0, n):
    """Часы, накрывающие отрезок `[t0, t0 + n)`."""
    a = datetime.fromtimestamp(t0, timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    b = datetime.fromtimestamp(t0 + n, timezone.utc)
    out, cur = [], a
    while cur <= b:
        out.append(cur.strftime("%Y-%m-%d-%H"))
        cur += timedelta(hours=1)
    return out


def symbol_row(root, sym, hours, t0, n):
    """Секундная сетка одного символа за отрезок."""
    d = os.path.join(root, sym)
    times, mids = [], []
    for h in hours:
        for t, m in read_hour(d, h, parse=mid_line):
            times.append(t)
            mids.append(m)
    # float32: сутки по 518 именам — это 388 МБ в двойной точности и
    # вдвое меньше здесь. Цена перехода измерена, а не объявлена малой
    # (тест `test_float32_prices_do_not_move_the_measure`): относительная
    # погрешность 6e-8 даёт около 0.001 б.п. на доходность при эффекте в
    # единицы б.п. и пороге события в 300. Память рядом со сборщиком
    # стоит дороже четвёртого знака.
    return D.place(times, mids, t0, n).astype(np.float32)


def _job(args):
    """Один символ за отрезок. Отказ по одному имени не валит прогон:
    сутки читаются по пятистам именам, и падение на одном файле стоило
    бы всех остальных. Имя, которое не прочлось, возвращается пустым и
    видно в покрытии."""
    root, sym, hours, t0, n = args
    try:
        return sym, symbol_row(root, sym, hours, t0, n)
    except (OSError, ValueError) as e:
        print(f"    {sym}: не прочитан ({type(e).__name__}: {e})")
        return sym, None


def available(root):
    """Символы и часы, которые есть на диске."""
    syms, hours = [], set()
    for sym in sorted(os.listdir(root)):
        d = os.path.join(root, sym)
        if not os.path.isdir(d):
            continue
        got = [f.split(".")[0] for f in os.listdir(d)
               if f.endswith(".jsonl") or f.endswith(".jsonl.gz")]
        if got:
            syms.append(sym)
            hours.update(got)
    return syms, sorted(hours)


def day_bounds(day):
    t = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(t.timestamp())


def load_day(root, syms, day, jobs=1, log=print):
    """Матрица «символы × секунды» суток с запасом по краям."""
    t0 = day_bounds(day) - PAD_SEC
    n = DAY_SEC + 2 * PAD_SEC
    hours = hours_of(t0, n)
    P = np.full((len(syms), n), np.nan, dtype=np.float32)
    tasks = [(root, s, hours, t0, n) for s in syms]
    done = 0
    started = time.time()
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        pos = {s: k for k, s in enumerate(syms)}
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            for sym, row in ex.map(_job, tasks, chunksize=4):
                if row is not None:
                    P[pos[sym]] = row
                done += 1
                if done % 100 == 0:
                    log(f"    {day}: прочитано {done}/{len(syms)} символов, "
                        f"{time.time() - started:.0f} с")
    else:
        for k, t in enumerate(tasks):
            sym, row = _job(t)
            if row is not None:
                P[k] = row
            done += 1
            if done % 100 == 0:
                log(f"    {day}: прочитано {done}/{len(syms)} символов, "
                    f"{time.time() - started:.0f} с")
    return P, t0, n


def cadence(P, lo, hi):
    """Как часто на деле стоят наблюдения: медиана промежутка, секунды.

    Не украшение отчёта, а граница измеримости. Сборщик снимает книгу
    проходом по всем именам, и живой журнал уже показывал проход в 2.5 с
    вместо секунды — «снимков в часе будет около 1441, не 3600».
    Задержка входа мельче фактического шага записью НЕ РАЗРЕШАЕТСЯ: в
    колонке δ = 1 с окажется тот же вход, что в δ = 5 с, и совпадение
    колонок читалось бы как «распада нет», хотя его просто нечем
    измерить.
    """
    gaps = []
    for r in range(P.shape[0]):
        idx = np.flatnonzero(np.isfinite(P[r, lo:hi]))
        if len(idx) > 10:
            gaps.append(float(np.median(np.diff(idx))))
    return float(np.median(gaps)) if gaps else float("nan")


def next_index(P):
    """Матрица «первое наблюдение начиная с этой секунды», int32.

    Только `nxt`: вход и выход ищутся вперёд, а опора за 15 минут
    считается построчно при отборе событий и матрицей не хранится —
    иначе на сутки уходило бы вдвое больше памяти без надобности.
    """
    NXT = np.empty(P.shape, dtype=np.int32)
    for r in range(P.shape[0]):
        NXT[r] = D.fill_index(P[r])[1]
    return NXT


def events_of_day(P, t0, drop, last_seen, day_lo, day_hi):
    """События суток: `(строка, секунда, метка времени)`.

    Берутся только решения ВНУТРИ суток (запас по краям служит опорой и
    форвардом, а не источником событий), и событие, отстоящее от
    прошлого события того же символа меньше чем на окно измерения, не
    считается новым — даже если прошлое случилось накануне.
    """
    rows, cols = [], []
    for r in range(P.shape[0]):
        prev, nxt = D.fill_index(P[r])
        idx = D.detect(P[r], drop, prev, nxt)
        for j in idx:
            if not (day_lo <= j < day_hi):
                continue
            t = t0 + int(j)
            if t - last_seen.get(r, -(1 << 40)) < D.DEDUP_SEC:
                continue
            last_seen[r] = t
            rows.append(r)
            cols.append(int(j))
    return np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64)


def measure(P, NXT, rows, cols, t0, cells, log=print):
    """Собственная доходность, фон и превышение по всем ячейкам сетки.

    Ячейки идут в порядке ШИРИНЫ защитного окна, а не как объявлены:
    матрица запретов на сутки — это полсотни мегабайт готовой и вчетверо
    больше на время построения, и держать одиннадцать штук разом значило
    бы отобрать память у сборщика. Записи, которую он ведёт, докачать
    неоткуда — это единственное необратимое в проекте.
    """
    out = {k: [] for k in cells}
    ban, cur = None, None
    for key in sorted(cells, key=lambda k: D.guard_sec(k[1], k[2])):
        _, delay, hor = key
        g = D.guard_sec(delay, hor)
        if g != cur:
            ban, cur = None, None            # старую отпускаем ДО новой
            ban, cur = D.guard_matrix(P.shape, rows, cols, g), g
            log(f"    защитное окно {g} с: матрица построена")
        for r, j in zip(rows, cols):
            own, bg, exc, width = D.excess(P, NXT, int(r), int(j),
                                           delay, hor, ban[:, int(j)])
            out[key].append((t0 + int(j), int(r), own, bg, exc, width))
    return out


def summarise(rec):
    """Сводка ячейки: по эпизодам, а не по событиям.

    Обвал накрывает рынок целиком, и сотня событий в одну минуту — одно
    наблюдение. Событие без измеренного фона в статистику не входит и
    считается отдельным числом: «не измеряется» — это не ноль.
    """
    t = np.array([r[0] for r in rec], dtype=np.float64)
    own = np.array([r[2] for r in rec], dtype=np.float64)
    bg = np.array([r[3] for r in rec], dtype=np.float64)
    exc = np.array([r[4] for r in rec], dtype=np.float64)
    width = np.array([r[5] for r in rec], dtype=np.float64)
    ok = np.isfinite(exc)
    thin = int(np.sum(width < D.MIN_CROSS))
    res = {
        "events": int(len(rec)),
        "measured": int(ok.sum()),
        "thin_background": thin,
        "thin_share": round(float(thin / len(rec)), 3) if len(rec) else None,
        "width_median": (round(float(np.median(width)), 1)
                         if len(width) else None),
        "symbols": int(len({r[1] for r in rec})),
    }
    if not ok.any():
        res.update({"episodes": 0, "excess_bp": None, "own_bp": None,
                    "bg_bp": None, "share_pos": None})
        return res
    ep = D.episodes(t[ok])
    ex_ep = D.by_episode(exc[ok], ep)
    res.update({
        "episodes": int(len(ex_ep)),
        "excess_bp": round(float(np.median(ex_ep)) * 1e4, 2),
        "excess_bp_by_event": round(float(np.median(exc[ok])) * 1e4, 2),
        "own_bp": round(float(np.median(own[ok])) * 1e4, 2),
        "bg_bp": round(float(np.median(bg[ok])) * 1e4, 2),
        "share_pos": round(float(np.mean(ex_ep > 0)), 3),
    })
    return res


def cost_round(out_dir, tag):
    """Круг издержек и откуда он взят.

    Вход платит половину спреда, выход вторую — это цена первого уровня,
    ниже которой исполнение быть не может. Проскальзывания обходом
    лесенки здесь по-прежнему нет, оно в D3.
    """
    for name in (f"D1-tape-check-{tag}.json", "D1-tape-check-1m.json"):
        p = os.path.join(out_dir, name)
        if not os.path.exists(p):
            continue
        try:
            g = (json.load(open(p, encoding="utf-8"))["groups"]
                 .get("подтверждено лентой") or {})
            si, so = g.get("spread_in_bp"), g.get("spread_out_bp")
            if si is not None and so is not None:
                return (COMMISSION_BP + (si + so) / 2.0,
                        f"комиссия {COMMISSION_BP:.0f} + спред "
                        f"{si:.1f}/{so:.1f} б.п., измеренный по записи")
        except (ValueError, KeyError, OSError):
            continue
    return (COST_ROUND_FALLBACK_BP,
            "оценка L1 по лесенке Binance; спред по нашей записи ещё не "
            "измерен — прогнать `tape_check.py`")


def report(art, path, out_dir=None):
    L = []
    a = art
    L.append("# D1 — отскок в первые секунды: реплей записи B1\n")
    L.append(f"Прогон: {a['run_at']}. Спека 11, этап D1.\n")
    L.append("**Это диагностика, а не вердикт.** Спека выносит его в D3, "
             "после издержек и проскальзывания обходом лесенки; здесь нет "
             "ни того, ни другого. Числа — валовые.\n")

    L.append("## 1. Что прочитано\n")
    L.append(f"- суток записи: **{a['days']}** ({a['day_from']} … "
             f"{a['day_to']})")
    L.append(f"- символов: **{a['symbols']}**")
    L.append(f"- секунд с ценой, медиана по символо-суткам: "
             f"**{a['coverage_median']}** из {DAY_SEC} "
             f"({a['coverage_share']} покрытия)")
    L.append(f"- шаг записи: снимок раз в **{a['cadence_sec']} с** "
             f"(объявлено — раз в секунду)")
    L.append(f"- прогон занял {a['took_min']} мин\n")
    blind = [d for d in a["delays"] if a["cadence_sec"]
             and d < a["cadence_sec"]]
    if blind:
        L.append(f"**Задержки {', '.join(str(d) for d in blind)} с "
                 f"записью не разрешаются.** Сборщик снимает книгу "
                 f"проходом по всем именам, и фактический шаг больше "
                 f"объявленного; в этих колонках стоит тот же вход, что "
                 f"в ближайшей разрешаемой, и совпадение колонок "
                 f"означает предел записи, а не отсутствие распада.\n")
    need = a["requirement"]
    L.append(f"Требование §3 (не меньше 14 суток по 300 символам): "
             f"**{'выполнено' if need['ok'] else 'НЕ выполнено'}** — "
             f"{need['why']}\n")

    L.append("## 2. Кривая распада по задержке входа\n")
    L.append("Превышение над одновременной кросс-секцией, базисные "
             "пункты, медиана по эпизодам (склейка 5 минут). Прочерк — "
             "**не измерено**: фон тоньше "
             f"{D.MIN_CROSS} имён либо цены нет.\n")
    for drop in a["drops"]:
        L.append(f"\n### Падение {int(drop * 100)} % за 15 минут\n")
        L.append("| удержание | " + " | ".join(
            f"δ = {d} с" for d in a["delays"]) + " | событий | эпизодов |")
        L.append("|---" * (len(a["delays"]) + 3) + "|")
        for hor in a["horizons"]:
            row, ev, eps = [], None, None
            for d in a["delays"]:
                c = a["cells"][f"{drop}|{d}|{hor}"]
                row.append("—" if c["excess_bp"] is None
                           else f"{c['excess_bp']:+.1f}")
                ev, eps = c["events"], c["episodes"]
            L.append(f"| {hor // 60} мин | " + " | ".join(row)
                     + f" | {ev} | {eps} |")
    L.append("")

    v = a["verdict_cell"]
    c = a["cells"][v["key"]]
    L.append("## 3. Ячейка вердикта\n")
    L.append(f"Объявлена спекой до прогона и одна: падение "
             f"{int(v['drop'] * 100)} %, задержка {v['delay_sec']} с, "
             f"удержание {v['horizon_sec'] // 60} минут. Остальные "
             f"{len(a['cells']) - 1} — диагностика распада, предъявлять "
             f"лучшую из них запрещено (урок R5).\n")
    if c["excess_bp"] is None:
        L.append("**Не измерена.** " + (
            f"Фон тоньше {D.MIN_CROSS} имён у "
            f"{c['thin_background']} событий из {c['events']}."))
    else:
        L.append(f"- превышение: **{c['excess_bp']:+.1f} б.п.** "
                 f"(по событиям {c['excess_bp_by_event']:+.1f})")
        L.append(f"- своя нога {c['own_bp']:+.1f}, фон "
                 f"{c['bg_bp']:+.1f} б.п.")
        L.append(f"- эпизодов {c['episodes']}, событий {c['events']}, "
                 f"имён {c['symbols']}")
        L.append(f"- доля прибыльных эпизодов {c['share_pos']}")
        L.append(f"- ширина фона: медиана {c['width_median']} имён, "
                 f"тоньше пола у {c['thin_share']} событий")
        ring, src = cost_round(out_dir or os.path.dirname(path),
                               art.get("tag", "1m"))
        net = c["excess_bp"] - ring
        L.append(f"\n**Круг издержек {ring:.1f} б.п.** ({src}). "
                 f"Нетто **{net:+.1f} б.п.**")
        L.append(f"\nКритерий §7 п.4 требует нетто не меньше двойного "
                 f"круга, то есть валового около {3 * ring:.0f} б.п. при "
                 f"имеющихся {c['excess_bp']:.1f} — "
                 f"**{'выполнен' if net >= 2 * ring else 'НЕ выполнен'}**. "
                 f"Проскальзывания обходом лесенки в этом числе нет, оно "
                 f"считается в D3 и может только ухудшить.")
    L.append("")

    L.append("## 4. Условия §7, измеримые уже сейчас\n")
    for k, s in a["checks"].items():
        L.append(f"- **{k}**: {s}")
    L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    """Точка входа. Падение здесь обязано САМО СЕБЯ доложить.

    Первый живой прогон оборвался и не оставил ничего: ни артефакта, ни
    следа. Снаружи это неотличимо от «забыли опубликовать», и круг
    переписки ушёл на угадывание. Теперь причина падения пишется в
    состояние и публикуется вместе с ним — тот же принцип, по которому
    сборщик считает отказы числом, а не молчит.
    """
    try:
        return _run()
    except SystemExit:
        raise
    except BaseException as e:                            # noqa: BLE001
        import traceback
        out, tag = _LAST.get("out"), _LAST.get("tag")
        if out and tag:
            st = _LAST.get("status") or {}
            st["state"] = "УПАЛ"
            st["error"] = f"{type(e).__name__}: {e}"
            st["traceback"] = traceback.format_exc()[-2000:]
            st["rss_mb"] = rss_mb()
            write_status(out, tag, st)
            print(f"ПРОГОН УПАЛ: {type(e).__name__}: {e}")
            if not _LAST.get("no_publish"):
                publish(f"D1: прогон упал ({tag})")
        raise


_LAST = {}


def _run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=BOOK_ROOT)
    ap.add_argument("--days", type=int, default=0,
                    help="сколько последних суток брать; 0 — все")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true",
                    help="не публиковать отчёт в git")
    ap.add_argument("--mem-share", type=float, default=0.6,
                    help="какую долю свободной памяти можно занять")
    a = ap.parse_args()
    # Частичный прогон НЕ занимает имя полного: смоук под именем
    # настоящего прогона в этом проекте уже подменял артефакт (F2), а по
    # содержимому они неотличимы — оба выглядят как отчёт этапа.
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"

    # Каталог создаётся ДО счёта, а не отчётом: прогон турнира однажды
    # досчитал всё и упал на записи в несуществующий каталог.
    os.makedirs(a.out, exist_ok=True)
    _LAST.update({"out": a.out, "tag": a.tag, "no_publish": a.no_publish})

    syms, hours = available(a.root)
    if a.symbols:
        want = set(a.symbols.split(","))
        syms = [s for s in syms if s in want]
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    print(f"символов {len(syms)}, суток {len(days)}: {days[0]} … {days[-1]}")

    # Память проверяется ДО счёта. Реплей работает рядом со сборщиком, и
    # если ядро прибьёт по памяти НЕ его, а сбор, это стоит суток
    # записи, которую неоткуда докачать — единственное необратимое в
    # проекте. Отказаться громко лучше, чем рискнуть молча.
    need = mem_need_mb(len(syms), DAY_SEC + 2 * PAD_SEC)
    have = mem_available_mb()
    print(f"память: нужно ~{need:.0f} МБ на сутки, доступно "
          f"{'неизвестно' if have is None else f'{have:.0f} МБ'}")
    if have is not None and need > have * a.mem_share:
        fits = int(len(syms) * have * a.mem_share / max(need, 1e-9))
        raise SystemExit(
            f"ОТКАЗ: на сутки нужно ~{need:.0f} МБ, а свободно "
            f"{have:.0f} МБ (порог {a.mem_share:.0%}). Рядом работает "
            f"сбор, и ронять его нельзя. Влезет около {fits} символов: "
            f"сузьте --symbols либо освободите память.")

    cells = [(d, dl, h) for d in D.DROPS for dl in D.DELAYS
             for h in D.HORIZONS_SEC]
    acc = {k: [] for k in cells}
    last_seen = {}
    cover, cadences = [], []
    t_start = time.time()
    status = {"state": "идёт", "tag": a.tag, "symbols": len(syms),
              "days_planned": len(days), "day_from": days[0],
              "day_to": days[-1], "mem_need_mb": need,
              "mem_available_mb": None if have is None else round(have),
              "days_done": [],
              "started_at": datetime.now(timezone.utc).strftime(
                  "%Y-%m-%d %H:%M UTC")}
    _LAST["status"] = status
    write_status(a.out, a.tag, status)
    for day in days:
        t_day = time.time()
        print(f"  {day}: читаю")
        P, t0, n = load_day(a.root, syms, day, a.jobs)
        cover += [int(np.isfinite(P[r, PAD_SEC:PAD_SEC + DAY_SEC]).sum())
                  for r in range(P.shape[0])]
        step = cadence(P, PAD_SEC, PAD_SEC + DAY_SEC)
        cadences.append(step)
        print(f"    шаг записи: снимок раз в {step:.1f} с")
        NXT = next_index(P)
        for drop in D.DROPS:
            rows, cols = events_of_day(P, t0, drop, last_seen.setdefault(
                drop, {}), PAD_SEC, PAD_SEC + DAY_SEC)
            print(f"    падение {int(drop * 100)} %: событий {len(rows)}")
            if len(rows) == 0:
                continue
            sub = [k for k in cells if k[0] == drop]
            got = measure(P, NXT, rows, cols, t0, sub)
            for k in sub:
                acc[k] += got[k]
        del P, NXT
        took = round((time.time() - t_day) / 60, 1)
        print(f"  {day}: готово за {took} мин, память {rss_mb()} МБ")
        # Состояние пишется ПОСЛЕ КАЖДЫХ суток, а не в конце. Прогон,
        # убитый по памяти, не пишет ничего — и снаружи это неотличимо
        # от «владелец забыл опубликовать». Оба раза ответ должен давать
        # файл, а не переписка.
        status["days_done"].append(
            {"day": day, "took_min": took, "rss_mb": rss_mb(),
             "cadence_sec": round(step, 2),
             "events": {str(k[0]): len(acc[k]) for k in cells
                        if k[1] == D.DELAYS[0] and k[2] == D.HORIZONS_SEC[0]}})
        write_status(a.out, a.tag, status)

    cov = np.array(cover, dtype=np.float64)
    status["state"] = "готов"
    write_status(a.out, a.tag, status)
    art = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "days": len(days), "day_from": days[0], "day_to": days[-1],
        "symbols": len(syms),
        "coverage_median": int(np.median(cov)) if len(cov) else 0,
        "coverage_share": round(float(np.median(cov) / DAY_SEC), 3)
        if len(cov) else 0.0,
        "cadence_sec": round(float(np.median(cadences)), 2)
        if cadences else None,
        "drops": list(D.DROPS), "delays": list(D.DELAYS),
        "horizons": list(D.HORIZONS_SEC),
        "verdict_cell": dict(D.VERDICT_CELL,
                             key=f"{D.VERDICT_CELL['drop']}|"
                                 f"{D.VERDICT_CELL['delay_sec']}|"
                                 f"{D.VERDICT_CELL['horizon_sec']}"),
        "cells": {f"{k[0]}|{k[1]}|{k[2]}": summarise(v)
                  if v else {"events": 0, "measured": 0, "episodes": 0,
                             "excess_bp": None, "own_bp": None,
                             "bg_bp": None, "share_pos": None,
                             "thin_background": 0, "thin_share": None,
                             "width_median": None, "symbols": 0}
                  for k, v in acc.items()},
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    art["requirement"] = {
        "ok": len(days) >= 14 and len(syms) >= 300,
        "why": f"{len(days)} суток, {len(syms)} символов",
    }
    art["checks"] = checks(art)
    p = os.path.join(a.out, f"D1-events-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    art["tag"] = a.tag
    report(art, os.path.join(a.out, f"D1-report-{a.tag}.md"), a.out)
    print(f"готово: {p}")
    if not a.no_publish:
        publish(f"D1: реплей записи B1 ({a.tag})")


def write_status(out, tag, status):
    """Состояние прогона отдельным файлом. Пишется атомарно.

    Это не журнал: журналы правило публикации не берёт намеренно (они
    меняются каждым запуском). Здесь — короткая сводка о том, докуда
    дошли и чем кончилось, и она обязана уехать в git даже у прогона,
    который упал.
    """
    p = os.path.join(out, f"D1-status-{tag}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def publish(msg):
    """Опубликовать отчёт сразу же, а не отдельной командой.

    Правило проекта — «каждый прогон пишет отчёт файлом, а publish.sh
    его коммитит», — но публикация оставалась ОТДЕЛЬНЫМ шагом, и первый
    же живой прогон на этом и запнулся: прогон случился, отчёт лежал на
    сервере, а в git не приехало ничего. Шаг, который можно забыть, рано
    или поздно забывают; шаг, который делает сам прогон, — нет.
    """
    import subprocess
    sh = os.path.join(RESEARCH, os.pardir, "tools", "publish.sh")
    sh = os.path.abspath(sh)
    if not os.path.exists(sh):
        print(f"публиковать нечем: нет {sh}")
        return
    print("публикую отчёт")
    try:
        r = subprocess.run(["bash", sh, msg], cwd=os.path.dirname(
            os.path.dirname(sh)), timeout=600)
        if r.returncode != 0:
            print(f"публикация не прошла (код {r.returncode}); "
                  f"отчёт на диске, повторить: tools/publish.sh '{msg}'")
    except Exception as e:                                # noqa: BLE001
        print(f"публикация не прошла ({type(e).__name__}: {e}); "
              f"отчёт на диске, повторить: tools/publish.sh '{msg}'")


def checks(art):
    """Условия немедленной остановки §7, которые видны без издержек."""
    out = {}
    v = art["cells"][art["verdict_cell"]["key"]]
    thin = v.get("thin_share")
    out["контроль построен"] = (
        "нечего проверять: событий нет" if not v["events"] else
        (f"фон тоньше {D.MIN_CROSS} имён у {thin} событий — "
         + ("КОНТРОЛЬ НЕ ПОСТРОЕН, числа не значат ничего"
            if thin is not None and thin > 0.5 else "порог не сработал")))
    # Кривая распада обязана убывать: не убывает — сломана мера, а не
    # рынок щедр.
    d = art["verdict_cell"]["drop"]
    h = art["verdict_cell"]["horizon_sec"]
    seq = [art["cells"][f"{d}|{dl}|{h}"]["excess_bp"] for dl in art["delays"]]
    seq = [x for x in seq if x is not None]
    cad = art.get("cadence_sec")
    out["шаг записи"] = (
        f"снимок раз в {cad} с; "
        + ("задержки мельче этого не разрешаются — колонки "
           + ", ".join(f"{d} с" for d in art["delays"] if d < cad)
           + " предъявлять нельзя"
           if cad and any(d < cad for d in art["delays"])
           else "вся объявленная ось задержек разрешается"))
    if len(seq) < 2:
        out["кривая распада"] = "не измерена"
    else:
        drops = sum(1 for i in range(len(seq) - 1) if seq[i + 1] <= seq[i])
        out["кривая распада"] = (
            f"{drops} убываний из {len(seq) - 1}: "
            + ("убывает" if drops >= len(seq) - 2 else
               "НЕ УБЫВАЕТ — проверять меру, а не радоваться")
            + f" ({', '.join(f'{x:+.1f}' for x in seq)} б.п.)")
    return out


if __name__ == "__main__":
    main()
