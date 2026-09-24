#!/usr/bin/env python3
"""
Прогон механики «дрейф после экстремального начисления funding».

Что делает
----------

Собирает события из рядов начислений площадки
(`research/a1_universe/out/funding`), берёт вокруг каждого секундную
запись стакана и ленты (`research/b1_book/out/book`, `…/trades`,
читатель `research/b1_book/store.py`), считает сделку ячейки вердикта
ядром `drift.py` и предъявляет убийц по объявленному порядку:

* **K0** — покрытие записью. Печатается ПЕРВОЙ: ниже 70 % судится
  запись, а не рынок, и остальные числа не имеют смысла;
* **K1** — контроль тех же имени и суток на других границах часа,
  200 зёрен, по сумме И по медиане;
* **K2** — реплей проходом по записанной лесенке вместо плоских 4.4 б.п.;
* **K3** — плацебо меток: метка «< −1 %» случайным начислениям тех же
  имён того же окна, 200 зёрен;
* **K4** — вперёд, правилом пула (`factory/pool.shape_why`), с
  объявленного дня; до календаря вердикта НЕТ ВОВСЕ.

Рядом печатается и НЕ судит: полосы −1…−0.5 %, −0.5…−0.2 %, длинная
после ставки > +0.2 %, тихие границы часа, профиль середины по секундам,
взятие по горизонтам 60/300/900/1800 с, глубина в 25 б.п., лента за
первую минуту, форма по суткам.

Почему проход по хранилищу здесь, а счёт в `drift.py`
-----------------------------------------------------

Чтобы калибровочная пара и проверка на заглядывание в будущее гонялись
на НАСТОЯЩИХ функциях замера, а не на их пересказе: ядро работает на
списках снимков, и тест собирает такой список руками за миллисекунды.

Прогон длиннее минуты: каталог артефактов создаётся ДО счёта, лог
строчный, состояние пишется файлом после каждого шага, предел памяти —
общий предел прогонов очереди (`dca_ladder/run_d10.MEM_LIMIT_MB`),
публикация — часть прогона.

    cd ~/algoth_v2 && .venv/bin/python research/mech_2859b3d4/run_drift.py
    cd ~/algoth_v2 && .venv/bin/python research/mech_2859b3d4/run_drift.py \\
        --limit 20 --skip-diag --no-publish        # дымовой прогон
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (HERE, os.path.join(RESEARCH, "b1_book"),
           os.path.join(RESEARCH, "common"),
           os.path.join(RESEARCH, "dca_ladder"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "dca_paper"), RESEARCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import drift as DR                                           # noqa: E402
import funding_series as FS                                  # noqa: E402
import run_d10 as D10                                        # noqa: E402
import store as ST                                           # noqa: E402

OUT = os.path.join(HERE, "out")
BOOK = os.path.join(RESEARCH, "b1_book", "out", "book")
TRADES = os.path.join(RESEARCH, "b1_book", "out", "trades")
FUNDING = os.path.join(RESEARCH, "a1_universe", "out", "funding")
REPORT = os.path.join(OUT, "MECH-drift-1m.md")
DATA = os.path.join(OUT, "drift.json")
STATE = os.path.join(OUT, "state.json")
LOG = os.path.join(OUT, "run.log")
PUBLISH = os.path.join(ROOT, "tools", "publish.sh")

# Горизонты выхода. Судит 1800 с (ячейка вердикта), остальные —
# чувствительность и только.
EXIT_HORIZONS = (60, 300, 900, 1800)
# Задержки входа, которые печатаются рядом: заявка объявила 3 с и
# спрашивает, насколько число держится, если опоздать.
ENTRY_LAGS = (3, 10, 30)
# Тихих начислений в окне сотни тысяч; контролю нужна выборка, и её
# размер объявлен здесь, а не подобран: столько же взял потолок заявки.
QUIET_SAMPLE = 900
# Пул плацебо: во сколько раз больше числа событий. Каждое зерно тянет
# из него выборку размером с событие, поэтому пул обязан быть
# существенно шире — двадцать крат дают запас и стоят минуты чтения.
PLACEBO_MULT = 20
# Запас на расхождение часов: файл назван по часам сборщика, метка
# снимка — биржевая. Две минуты — заведомо больше наблюдаемой разницы
# (около секунды) и дёшевы: лишний час читается только у окна, которое
# начинается у границы часа.
CLOCK_SKEW_MS = 120_000


def _hour(ms):
    """Имя часового файла записи. Раскладку задаёт сам сборщик."""
    return ST.Writer.hour(ms / 1000.0)


def ts_of_line(line):
    """Метка снимка без разбора всей строки.

    Полный `json.loads` на сотнях уровней стоит десятки миллисекунд, а
    нам из часа нужны единицы строк. Тот же приём, что у D1 (параметр
    `parse` в `store.read_jsonl`): порча при этом обрабатывается ОДНИМ
    кодом, второго читателя не заводится.
    """
    i = line.find('"ts":', 0, 64)
    if i < 0:
        raise ValueError("в строке нет метки")
    j = i + 5
    while j < len(line) and line[j] == " ":
        j += 1
    k = j
    while k < len(line) and line[k].isdigit():
        k += 1
    if k == j:
        raise ValueError("метка не число")
    return int(line[j:k])


def _keeper(windows):
    """Разбор, оставляющий только строки нужных окон.

    Строка вне окон отвергается `ValueError` — тем же способом, каким
    читатель пропускает битую. Это НЕ потеря данных: окна заданы
    объявленной ячейкой, и всё, что вне их, замеру не нужно ни в одной
    из веток.
    """
    def parse(line):
        t = ts_of_line(line)
        for lo, hi in windows:
            if lo <= t <= hi:
                return (t, line)
        raise ValueError("вне окон замера")
    return parse


def read_snaps(sym, windows):
    """Снимки имени в окнах, по возрастанию метки.

    Час файла сборщик берёт по СВОИМ часам (`t`), а метка снимка `ts` —
    биржевая, и они расходятся на секунды (у BTC в записи `ts` опережает
    `t` на 1.03 с). Значит снимок с меткой сразу ПОСЛЕ границы часа
    вполне может лежать в файле предыдущего часа. Поэтому у окна,
    начинающегося у границы, читается и предыдущий час: иначе замер «в
    секунду начисления» терял бы снимки по причине, не имеющей к рынку
    никакого отношения, и списывал бы это на паузу сборщика.
    """
    d = os.path.join(BOOK, sym)
    hours = set()
    for lo, hi in windows:
        hours.add(_hour(lo))
        hours.add(_hour(hi))
        if lo % DR.MS_H < CLOCK_SKEW_MS:
            hours.add(_hour(lo - CLOCK_SKEW_MS))
    got = []
    for h in sorted(hours):
        got += ST.read_hour(d, h, parse=_keeper(windows))
    got.sort(key=lambda x: x[0])
    out = []
    for _t, line in got:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def read_prints(sym, t0, t1):
    """Лента имени в окне, кортежами `(метка, сторона, цена, объём)`."""
    d = os.path.join(TRADES, sym)

    def parse(line):
        t = ts_of_line(line)
        if not (t0 <= t <= t1):
            raise ValueError("вне окна")
        r = json.loads(line)
        return (int(r["ts"]), int(r["side"]), float(r["p"]), float(r["v"]))

    out = []
    for h in sorted({_hour(t0), _hour(t1)}):
        out += ST.read_hour(d, h, parse=parse)
    return out


def load_rates(sym):
    """Ряд начислений имени: (метки мс, ставки). Пусто — ряда нет.

    Разбор времени и колонок — ОБЩИЙ (`common/funding_series.py`):
    формат этих файлов угадывался в проекте дважды и дважды неверно.
    Своей здесь только раскладка по имени файла: запись стакана
    разложена символом площадки, а `load_funding` ключуется активом
    универсума, и часть имён записи в универсуме ещё нет.
    """
    import csv
    import gzip
    p = os.path.join(FUNDING, sym + ".csv.gz")
    if not os.path.exists(p):
        return None
    t, r = [], []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        rd = csv.reader(f)
        head = next(rd, None)
        it, ir = FS.column_indices(head, sym)
        for row in rd:
            if len(row) <= max(it, ir):
                continue
            t.append(FS.parse_time_ms(row[it]))
            r.append(float(row[ir]))
    if not t:
        return None
    o = np.argsort(t)
    return (np.asarray(t, dtype=np.int64)[o],
            np.asarray(r, dtype=np.float64)[o])


# --- события -----------------------------------------------------------

def collect_events(symbols, lo_ms, hi_ms, log=print):
    """Начисления всех имён записи в окне: список строк-событий.

    Строка несёт имя, метку, ставку, полосу, сторону полосы и метку
    СЛЕДУЮЩЕГО начисления — последняя нужна, чтобы позиция не прошла
    через расчёт, и берётся из ряда, а не предполагается по шагу.
    """
    out, no_series = [], []
    for s in symbols:
        ser = load_rates(s)
        if ser is None:
            no_series.append(s)
            continue
        t, r = ser
        for i in range(len(t)):
            if not (lo_ms <= int(t[i]) < hi_ms):
                continue
            b = DR.band_of(float(r[i]))
            if b is None:
                continue
            out.append({"sym": s, "ts": int(t[i]), "rate": float(r[i]),
                        "band": b, "side": DR.side_of_band(b),
                        "next_ms": int(t[i + 1]) if i + 1 < len(t) else None})
    out.sort(key=lambda x: (x["ts"], x["sym"]))
    log(f"имён без ряда начислений: {len(no_series)}")
    return out, no_series


def event_windows(t_ms, horizons=EXIT_HORIZONS, lags=ENTRY_LAGS,
                  profile=True, next_ms=None):
    """Окна записи, нужные одному событию.

    Узкие намеренно: час записи альта — это две тысячи снимков по
    восемь килобайт, а замеру их нужно полтора десятка.
    """
    w = []
    for lg in lags:
        w.append((t_ms + lg * DR.MS_S,
                  t_ms + (lg + DR.ENTRY_MAX_LAG_S) * DR.MS_S))
    for h in horizons:
        w.append((t_ms + h * DR.MS_S,
                  t_ms + (h + DR.EXIT_MAX_LAG_S) * DR.MS_S))
    if profile:
        for p in DR.PROFILE_POINTS:
            w.append((t_ms + p * DR.MS_S,
                      t_ms + (p + DR.PROFILE_TOL_S) * DR.MS_S))
        # Сплошное окно диагностики дыры: ровно то, по которому меряется
        # задержка первого снимка (`drift.DIAG_CAP_S`). Оно обязано
        # совпадать с потолком меры — иначе «дыры длиннее потолка»
        # окажется больше, чем есть, просто потому что прогон туда не
        # смотрел.
        w.append((t_ms, t_ms + DR.DIAG_CAP_S * DR.MS_S))
    if next_ms:
        span = int(next_ms) - int(t_ms)
        for f in DR.NEXT_FRACTIONS:
            at = int(t_ms + span * float(f))
            w.append((at, at + DR.PROFILE_TOL_S * DR.MS_S))
    return w


def measure_one(ev, ticket, horizons=EXIT_HORIZONS, lags=ENTRY_LAGS,
                profile=True, tape=True, to_next=False):
    """Событие целиком: сделка ячейки, соседние горизонты, профиль, лента."""
    snaps = read_snaps(ev["sym"], event_windows(
        ev["ts"], horizons, lags, profile,
        next_ms=ev["next_ms"] if to_next else None))
    prints = None
    if tape:
        try:
            prints = read_prints(ev["sym"], ev["ts"],
                                 ev["ts"] + DR.FLOW_WINDOW_S * DR.MS_S)
        except OSError:
            prints = None
    row = DR.measure_event(snaps, ev["ts"], ev["side"], ticket_usd=ticket,
                           prints=prints, next_accrual_ms=ev["next_ms"])
    row.update({"sym": ev["sym"], "rate": ev["rate"], "band": ev["band"]})
    # Соседние горизонты и задержки — диагностика. Считаются тем же
    # ядром с другими окнами, а не отдельной формулой.
    row["by_exit"] = {}
    for h in horizons:
        r = DR.measure_event(snaps, ev["ts"], ev["side"], ticket_usd=ticket,
                             next_accrual_ms=ev["next_ms"], exit_s=h)
        row["by_exit"][h] = r["flat_bp"] if r.get("used") else None
    row["by_lag"] = {}
    for lg in lags:
        r = DR.measure_event(snaps, ev["ts"], ev["side"], ticket_usd=ticket,
                             next_accrual_ms=ev["next_ms"], entry_lag_s=lg,
                             entry_max_s=lg + DR.ENTRY_MAX_LAG_S)
        row["by_lag"][lg] = r["flat_bp"] if r.get("used") else None
    if profile:
        row["profile"] = DR.profile_bp(snaps, ev["ts"])
    if to_next:
        row["to_next"] = DR.profile_to_next(snaps, ev["ts"], ev["next_ms"])
    return row


def measure_plain(sym, t_ms, side, ticket, next_ms=None):
    """Сделка ячейки без диагностики — контроль и плацебо.

    Тем же ядром и теми же окнами: контроль, посчитанный другой
    формулой, сравнивал бы не то, о чём спор.
    """
    snaps = read_snaps(sym, event_windows(t_ms, horizons=(DR.EXIT_S,),
                                          lags=(DR.ENTRY_LAG_S,),
                                          profile=False))
    row = DR.measure_event(snaps, t_ms, side, ticket_usd=ticket,
                           next_accrual_ms=next_ms)
    row["sym"] = sym
    return row


# --- контроль K1: те же имя и сутки ------------------------------------

def control_plan(events, accrual_by_sym, gap_h=DR.CONTROL_GAP_H):
    """{(имя, сутки): [границы часа]} — что мерить контролем.

    Границы берутся у ТЕХ ЖЕ суток того же имени, как объявлено
    заявкой: контроль обязан отвечать на вопрос «а это имя в этот день
    и так падало?», а не «а рынок падал?».
    """
    ev_ts = {}
    for e in events:
        ev_ts.setdefault(e["sym"], []).append(e["ts"])
    plan = {}
    for e in events:
        d = DR.day_no(e["ts"])
        key = (e["sym"], d)
        if key in plan:
            continue
        hours = [d * DR.MS_D + k * DR.MS_H for k in range(24)]
        plan[key] = DR.control_times(hours, accrual_by_sym.get(e["sym"], {}),
                                     ev_ts[e["sym"]], gap_h=gap_h)
    return plan


def _fmt(v, d=2, dash="—", suffix=""):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return dash
    return f"{v:+.{d}f}{suffix}"


def _plain(v, d=1, dash="—"):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return dash
    return f"{v:.{d}f}"


# --- отчёт -------------------------------------------------------------

def band_table(rows_by_band, ticket):
    """Взятие по горизонтам и полосам, нетто, в базисных пунктах."""
    out = ["| выход | " + " | ".join(
        DR.BAND_TITLE.get(b, b) + f" (n={sum(1 for r in rows_by_band[b] if r.get('used'))})"
        for b in rows_by_band) + " |",
        "|---" * (len(rows_by_band) + 1) + "|"]
    for h in EXIT_HORIZONS:
        cells = []
        for b, rows in rows_by_band.items():
            v = [r["by_exit"].get(h) for r in rows
                 if r.get("used") and r.get("by_exit")]
            v = [x for x in v if x is not None]
            if not v:
                cells.append("—")
                continue
            a = np.asarray(v, dtype=float)
            cells.append(f"{np.median(a):+.1f} / {a.mean():+.1f}; "
                         f"{(a > 0).mean():.0%}")
        out.append(f"| T+{h} с | " + " | ".join(cells) + " |")
    return "\n".join(out)


def profile_table(rows_by_band):
    """Ход середины от T−60 с, б.п., медиана / среднее."""
    head = ["| точка | " + " | ".join(DR.BAND_TITLE.get(b, b)
                                      for b in rows_by_band) + " |",
            "|---" * (len(rows_by_band) + 1) + "|"]
    for p in DR.PROFILE_POINTS:
        if p == DR.PROFILE_BASE_S:
            continue
        cells = []
        for b, rows in rows_by_band.items():
            v = [(r.get("profile") or {}).get(p) for r in rows
                 if r.get("profile")]
            v = [x for x in v if x is not None]
            if not v:
                cells.append("—")
                continue
            a = np.asarray(v, dtype=float)
            cells.append(f"{np.median(a):+.1f} / {a.mean():+.1f}")
        head.append(f"| T{p:+d} с | " + " | ".join(cells) + " |")
    return "\n".join(head)


def report(res, at):
    """Отчёт. Каждая вердиктовая фраза ВЫВЕДЕНА из своего числа."""
    v = res["verdict"]
    k = res["killers"]
    cell = res["cell"]
    L = [
        "# Дрейф после экстремального начисления funding",
        "",
        f"Прогон {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(at))}; "
        f"окно записи {res['window'][0]}…{res['window'][1]}, "
        f"имён записи {res['n_symbols']}, билет "
        f"{res['ticket']:.0f} $, плечо {DR.LEVERAGE:g}×.",
        "",
        "Ячейка вердикта объявлена заявкой до прогона: начисление с "
        "фактической ставкой ниже −1 % за одно начисление, вход тейкером "
        f"на первом снимке в окне T+{DR.ENTRY_LAG_S}…{DR.ENTRY_MAX_LAG_S} с, "
        f"выход на первом снимке в окне T+{DR.EXIT_S}…"
        f"{DR.EXIT_S + DR.EXIT_MAX_LAG_S} с, одна позиция на имя, ни одного "
        "начисления внутри позиции. Всё остальное в отчёте — диагностика "
        "и не судит.",
        "",
        f"**Итог: {v['say']}**",
        "",
        "## K0 — покрытие записью (до всяких денег)",
        "",
        k["K0"]["say"] + ".",
        "",
        f"Событий в полосе вердикта {k['K0']['n']}, из них запись вела "
        f"{k['K0'].get('in_record')}, снимок входа в окне есть у "
        f"{k['K0'].get('entry')}, снимок выхода тоже — у "
        f"{k['K0']['cover']}, дошло до сделки {k['K0'].get('used')} "
        "(разница последних двух — позиция прошла бы через расчёт: такое "
        "считается отдельно и покрытие записи не портит).",
        "",
    ]
    if k["K0"].get("why"):
        L += ["Чем непокрыты:", ""]
        for why, n in sorted(k["K0"]["why"].items(), key=lambda x: -x[1]):
            L.append(f"* {why} — {n}")
        L.append("")
    if k["K0"].get("lag"):
        g = k["K0"]["lag"]
        L += [f"**Насколько опоздала запись.** Первый снимок не раньше "
              f"T+{DR.ENTRY_LAG_S} с приходит с задержкой: медиана "
              f"{g['med']:.1f} с, p90 {g['p90']:.1f}, p95 {g['p95']:.1f}, "
              f"максимум {g['max']:.1f} при потолке окна входа "
              f"{DR.ENTRY_MAX_LAG_S} с; дыр длиннее "
              f"{DR.DIAG_CAP_S} с — {k['K0'].get('holes_over_cap')} "
              "(их величина не мерена: дальше идёт уже снимок выхода). "
              f"Снимков имени за первую минуту "
              f"после расчёта — медиана "
              f"{_plain(k['K0'].get('snaps_minute_med'), 0)}. Это мера "
              "САМОГО СБОРЩИКА: у границы часа он закрывает и сжимает "
              "все файлы разом, и окно входа шириной в семь секунд "
              "попадает не всегда. Лечится это правкой сборщика (роль "
              "`fix`), а не расширением окна задним числом.", ""]
    lag = res.get("lag") or {}
    if lag.get("entry_lag_s"):
        e, x = lag["entry_lag_s"], lag.get("exit_lag_s") or {}
        L += ["**Дыра записи у границы часа** — мера самого сборщика, а "
              "не рынка: задержка первого снимка входа медиана "
              f"{e['med']:.1f} с, p90 {e['p90']:.1f}, p95 {e['p95']:.1f}, "
              f"максимум {e['max']:.1f} при потолке "
              f"{DR.ENTRY_MAX_LAG_S} с; у выхода (середина часа) медиана "
              + (f"{x['med']:.1f} с, p90 {x['p90']:.1f}. " if x else "— . ")
              + "У границы часа сборщик закрывает и сжимает все файлы "
                "разом, и первый снимок после расчёта отстаёт; любой "
                "замер «в секунду начисления» этим ограничен.", ""]
    L += [
        "## Ячейка вердикта числами",
        "",
        f"Взятие нетто (плоские издержки {DR.FLAT_COST_BP:.1f} б.п. = "
        f"комиссия {DR.COMMISSION_BP:.0f} + проскальзывание X3 "
        f"{DR.SLIP_BP:.1f} × 2 ноги): медиана "
        f"{_fmt(cell['stat']['med'], 1)} б.п., среднее "
        f"{_fmt(cell['stat']['mean'], 1)}, p10 "
        f"{_fmt(cell['stat']['p10'], 1)}, p90 "
        f"{_fmt(cell['stat']['p90'], 1)}; выше круга "
        f"{cell['stat']['above_cost']:.0%}; хуже −100 б.п. "
        f"{cell['stat']['worse_100']:.0%}.",
        "",
        f"**Спред внутри взятия.** То же взятие ПО СЕРЕДИНАМ стакана: "
        f"медиана {_fmt(res['mid_take']['med'], 1)} б.п. при спреде на "
        f"входе {_plain(res['spread']['in_med'])} б.п. и на выходе "
        f"{_plain(res['spread']['out_med'])} б.п. Разница двух чисел и "
        "есть спред: тейкер платит его дважды, и в полосе событий — "
        "тесных именах в сквизе — он не шесть базисных пунктов, как у "
        "ликвидных. Судит взятие по ЛУЧШИМ ЦЕНАМ, по серединам — "
        "верхняя граница.",
        "",
        f"Деньгами на билете {res['ticket']:.0f} $: сумма "
        f"{_fmt(cell['form']['tot'])} $, медиана дня "
        f"{_fmt(cell['form']['st']['med'])} $, прибыльных суток "
        f"{cell['form']['st']['green']:.0%} из {cell['form']['days']}, "
        f"худший день {_fmt(cell['form']['st']['worst'])} $, укус "
        f"{_plain(cell['form']['st']['bite'])} при пределе "
        f"{k['K4'].get('max_bite', 10)}.",
        "",
        f"**Концентрация.** Без {cell['form']['top_days']} лучших дней "
        f"остаётся {_fmt(cell['form']['without_top'])} $; лучшее имя "
        f"{cell['form']['best_name']} даёт "
        f"{_fmt(cell['form']['best_name_usd'])} $, без него "
        f"{_fmt(cell['form']['without_best_name'])} $; половины окна "
        f"{_fmt(cell['form']['half1'])} / "
        f"{_fmt(cell['form']['half2'])} $. Колонка обязательная: "
        "концентрация переворачивает знак, и без неё эпизод читается "
        "трендом.",
        "",
        "## K1 — контроль тех же имени и суток",
        "",
        k["K1"]["say"] + ".",
        "",
    ]
    if res.get("k1"):
        s = res["k1"]
        L += [f"Событий со своим пулом контролей {s['n']}, зёрен "
              f"{s['seeds']}; сумма события {_fmt(s['ev_sum'])} $ против "
              f"медианы случайной {_fmt(s['ctl_sum_med'])} $ и максимума "
              f"{_fmt(s['ctl_sum_max'])} $; медиана события "
              f"{_fmt(s['ev_med'])} $ против p95 случайной "
              f"{_fmt(s['ctl_med_p95'])} $.", ""]
    if res.get("calib"):
        c = res["calib"]
        L += [f"Перцентиль события среди контролей своего имени-суток: "
              f"средний {c['mean']:.3f}, медиана {c['med']:.3f} "
              f"(нуль 0.5, {c['n']} событий). Это та же величина, на "
              "которой стоит калибровочная пара тестов: подсаженный дрейф "
              "поднимает её к 1, шум оставляет у 0.5.", ""]
    L += [
        "## K2 — ликвидность: проход по записанной лесенке",
        "",
        k["K2"]["say"] + ".",
        "",
        "Вход продаёт в биды записанного стакана на билет, выход "
        "выкупает ровно те же монеты с асков; проскальзывание тогда не "
        f"константа, а то, что лежало в записи, и к нему добавляется "
        f"только комиссия {DR.COMMISSION_BP:.0f} б.п. События, у "
        "которого записанной лесенки не хватило на билет, в медиану не "
        "входят: цена за пределами записи неизвестна, и прочерк здесь "
        "честнее нуля.",
        "",
    ]
    if res.get("slip"):
        s = res["slip"]
        L += [f"Проскальзывание прохода: вход медиана {_plain(s['in_med'])} "
              f"б.п., выход {_plain(s['out_med'])} б.п. — против плоских "
              f"{DR.SLIP_BP:.1f} б.п. живого замера X3 на 300 $. Глубина в "
              f"25 б.п. на секунде входа: медиана {_plain(s['depth_med'], 0)} $, "
              f"p10 {_plain(s['depth_p10'], 0)} $.", ""]
    L += [
        "## K3 — плацебо меток",
        "",
        k["K3"]["say"] + ".",
        "",
        "## K4 — вперёд, правилом пула",
        "",
        k["K4"]["say"] + ".",
        "",
        f"Судит то же правило, которым пул отставляет кандидатов "
        f"(`research/factory/pool.py`): медиана дня ≥ 0 и укус ≤ 10, плюс "
        f"объявленная заявкой третья граница — сумма без "
        f"{DR.TOP_DAYS} лучших дней должна остаться положительной. Окно "
        f"вперёд начинается {DR.FORWARD_FROM}; всё, что до него, — "
        "запись, которую предлагающий уже видел, и вердиктом она быть не "
        "может.",
        "",
        "## Рядом и не судит",
        "",
        "### Взятие по горизонтам и полосам (медиана / среднее; доля выше круга)",
        "",
        res["tables"]["by_band"],
        "",
        "### Ход середины от T−60 с (медиана / среднее, б.п.)",
        "",
        res["tables"]["profile"],
        "",
        "### Чувствительность к задержке входа (полоса вердикта, T+1800 с)",
        "",
        res["tables"]["by_lag"],
        "",
        "### Лента за первую минуту после расчёта",
        "",
        res["tables"]["flow"],
        "",
        "### Ход середины ДО следующего начисления (полоса вердикта)",
        "",
        res["tables"]["to_next"],
        "",
        "## Чего этот прогон не говорит",
        "",
        "Ёмкость мала по стакану (билет ограничен глубиной, событий "
        "около трёх в сутки): это эдж механики и калибровки исполнения, "
        "а не масштаб фазы D, и сказано это заранее. Ожидание живёт в "
        "редких сутках — колонка «без трёх лучших дней» выше, — поэтому "
        "единственный настоящий вердикт даёт K4 по календарю, а не эта "
        "страница.",
        "",
    ]
    return "\n".join(L)


# --- прогон ------------------------------------------------------------

def state(step, **kw):
    kw["step"] = step
    kw["at"] = round(time.time(), 3)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(kw, f, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", default="2026-08-04")
    ap.add_argument("--to", dest="hi", default=None,
                    help="по умолчанию — завтрашние сутки UTC")
    ap.add_argument("--ticket", type=float, default=DR.TICKET_USD)
    ap.add_argument("--seeds", type=int, default=DR.SEEDS)
    ap.add_argument("--quiet-sample", type=int, default=QUIET_SAMPLE)
    ap.add_argument("--placebo-mult", type=int, default=PLACEBO_MULT)
    ap.add_argument("--limit", type=int, default=0,
                    help="ограничить число событий полосы вердикта")
    ap.add_argument("--skip-diag", action="store_true")
    ap.add_argument("--no-next", action="store_true",
                    help="не считать профиль до следующего начисления: "
                         "он один стоит четырёх лишних часов записи на "
                         "событие")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)

    # Каталог артефактов — ДО счёта: редирект лога это тоже каталог.
    os.makedirs(OUT, exist_ok=True)
    logf = open(LOG, "a", encoding="utf-8")

    def log(m):
        line = f"[{time.strftime('%H:%M:%S', time.gmtime())}] {m}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    t_start = time.time()
    state("старт")
    log(f"прогон механики 2859b3d4, билет {a.ticket:.0f} $")
    lo_ms = int(np.datetime64(a.lo + "T00:00:00", "ms").astype("int64"))
    hi_day = a.hi or time.strftime("%Y-%m-%d",
                                   time.gmtime(time.time() + 86400))
    hi_ms = int(np.datetime64(hi_day + "T00:00:00", "ms").astype("int64"))

    if not os.path.isdir(BOOK):
        raise SystemExit(f"ОТКАЗ: записи стакана нет — {BOOK}")
    symbols = sorted(os.listdir(BOOK))
    log(f"имён в записи: {len(symbols)}")
    events, no_series = collect_events(symbols, lo_ms, hi_ms, log)
    if not events:
        raise SystemExit(
            "ОТКАЗ: ни одного начисления в объявленных полосах за окно "
            f"{a.lo}…{hi_day} при {len(symbols)} именах записи. Пустое "
            "множество событий — это отказ, а не результат с нулями: "
            "проверьте ряды начислений и окно.")
    by_band = {}
    for e in events:
        by_band.setdefault(e["band"], []).append(e)
    log("событий по полосам: " + ", ".join(
        f"{b} {len(v)}" for b, v in sorted(by_band.items())))
    D10.mem_guard("события собраны", log)

    rng = np.random.default_rng(DR.RNG_SEED)
    if len(by_band.get("quiet", [])) > a.quiet_sample:
        idx = rng.choice(len(by_band["quiet"]), size=a.quiet_sample,
                         replace=False)
        by_band["quiet"] = [by_band["quiet"][i] for i in sorted(idx)]
        log(f"тихих взято выборкой: {len(by_band['quiet'])}")

    cell_events = by_band.get(DR.VERDICT_BAND) or []
    if a.limit:
        cell_events = cell_events[:a.limit]
    if not cell_events:
        raise SystemExit(
            f"ОТКАЗ: в полосе вердикта «{DR.VERDICT_BAND}» событий нет, "
            "хотя начисления в окне есть — судить нечего")

    # --- полоса вердикта
    state("полоса вердикта", n=len(cell_events))
    rows = []
    for i, e in enumerate(cell_events, 1):
        rows.append(measure_one(e, a.ticket, to_next=not a.no_next))
        if i % 25 == 0 or i == len(cell_events):
            log(f"полоса вердикта: {i} из {len(cell_events)}")
            state("полоса вердикта", done=i, of=len(cell_events))
    D10.mem_guard("полоса вердикта посчитана", log)
    k0 = DR.k0(rows)
    log("K0: " + k0["say"])

    used = [r for r in rows if r.get("used")]
    cell = {"stat": DR.stat_block([r["flat_bp"] for r in used]),
            "form": DR.form(used)}
    mid_take = DR.stat_block([r["mid_bp"] for r in used])
    spread = {}
    for side_name, f in (("in_med", "spread_in_bp"),
                         ("out_med", "spread_out_bp")):
        v = [r[f] for r in used if r.get(f) is not None]
        spread[side_name] = float(np.median(v)) if v else None
    log(f"спред: вход {_plain(spread['in_med'])}, "
        f"выход {_plain(spread['out_med'])} б.п.; "
        f"взятие по серединам медиана {mid_take['med']:+.1f} б.п.")
    log(f"ячейка: медиана {cell['stat']['med']:+.1f} б.п., сумма "
        f"{cell['form']['tot']:+.2f} $")

    # --- K1: контроль тех же имени и суток
    state("контроль K1")
    acc_by_sym = {}
    for e in events:
        acc_by_sym.setdefault(e["sym"], {})[e["ts"]] = e["rate"]
    plan = control_plan(cell_events, acc_by_sym)
    ctl_rows = {}
    n_ctl = sum(len(v) for v in plan.values())
    log(f"контролей к замеру: {n_ctl} границ часа в "
        f"{len(plan)} именах-сутках")
    done = 0
    for key, times in sorted(plan.items()):
        got = []
        for t in times:
            got.append(measure_plain(key[0], t, -1, a.ticket))
            done += 1
            if done % 200 == 0:
                log(f"контроль: {done} из {n_ctl}")
                state("контроль K1", done=done, of=n_ctl)
        ctl_rows[key] = [g for g in got if g.get("used")]
    D10.mem_guard("контроль посчитан", log)

    def key_of(r):
        return (r["sym"], DR.day_no(r["ts"]))

    pools = [[DR.usd_of(c) for c in ctl_rows.get(key_of(r), ())]
             for r in used]
    pools = [[x for x in p if x is not None] for p in pools]
    k1s = DR.seed_shares([DR.usd_of(r) for r in used], pools, seeds=a.seeds)
    k1 = DR.k1(k1s)
    log("K1: " + k1["say"])
    calib = DR.calib_percentile(used, ctl_rows, key_of)
    log(f"перцентиль события среди своих контролей: средний "
        f"{calib['mean']:.3f}, медиана {calib['med']:.3f} (нуль 0.5)")

    # --- K2: лесенка
    k2 = DR.k2(rows)
    log("K2: " + k2["say"])
    slip = None
    w_in = [r["walk_in_bp"] for r in used if r.get("walk_in_bp") is not None]
    w_out = [r["walk_out_bp"] for r in used
             if r.get("walk_out_bp") is not None]
    dep = [r["depth_bp25"] for r in used if r.get("depth_bp25") is not None]
    if w_in and dep:
        slip = {"in_med": float(np.median(w_in)),
                "out_med": float(np.median(w_out)) if w_out else None,
                "depth_med": float(np.median(dep)),
                "depth_p10": float(np.percentile(dep, 10))}

    # --- K3: плацебо меток
    state("плацебо K3")
    names = {r["sym"] for r in used}
    pool_ev = [e for e in events
               if e["sym"] in names and e["band"] != DR.VERDICT_BAND]
    want = min(len(pool_ev), a.placebo_mult * max(len(used), 1))
    if len(pool_ev) > want:
        idx = rng.choice(len(pool_ev), size=want, replace=False)
        pool_ev = [pool_ev[i] for i in sorted(idx)]
    log(f"плацебо: пул {len(pool_ev)} начислений тех же имён")
    pl_rows = []
    for i, e in enumerate(pool_ev, 1):
        pl_rows.append(measure_plain(e["sym"], e["ts"], -1, a.ticket,
                                     e["next_ms"]))
        if i % 200 == 0:
            log(f"плацебо: {i} из {len(pool_ev)}")
            state("плацебо K3", done=i, of=len(pool_ev))
    pl_vals = [DR.usd_of(r) for r in pl_rows if r.get("used")]
    ev_med_usd = float(np.median([DR.usd_of(r) for r in used]))
    k3s = DR.placebo_shares(ev_med_usd, pl_vals, len(used), seeds=a.seeds)
    k3 = DR.k3(k3s)
    log("K3: " + k3["say"])
    D10.mem_guard("плацебо посчитано", log)

    # --- K4: вперёд
    k4 = DR.k4(rows)
    k4["max_bite"] = DR.PL.MAX_BITE
    log("K4: " + k4["say"])

    # --- диагностические полосы
    state("диагностика")
    diag = {}
    if not a.skip_diag:
        for b, evs in by_band.items():
            if b == DR.VERDICT_BAND:
                continue
            got = []
            for i, e in enumerate(evs, 1):
                got.append(measure_one(e, a.ticket))
                if i % 200 == 0:
                    log(f"полоса {b}: {i} из {len(evs)}")
                    state("диагностика", band=b, done=i, of=len(evs))
            diag[b] = got
            log(f"полоса {b}: посчитано {len(got)}")
            D10.mem_guard(f"полоса {b}", log)
    rows_by_band = {DR.VERDICT_BAND: rows}
    for b in ("m1_m05", "m05_m02", "pos", "quiet"):
        if b in diag:
            rows_by_band[b] = diag[b]

    # --- таблицы
    lag_lines = ["| задержка входа | медиана | среднее | n |",
                 "|---|---:|---:|---:|"]
    for lg in ENTRY_LAGS:
        v = [r["by_lag"].get(lg) for r in rows if r.get("by_lag")]
        v = [x for x in v if x is not None]
        lag_lines.append(
            f"| T+{lg} с | " + (f"{np.median(v):+.1f} б.п. | "
                                f"{np.mean(v):+.1f} | {len(v)} |"
                                if v else "— | — | 0 |"))
    flow_lines = ["| полоса | продано минус куплено, медиана | "
                  "доля с перевесом продаж | принтов |", "|---|---:|---:|---:|"]
    for b, rr in rows_by_band.items():
        v = [r["flow_usd"] for r in rr if r.get("flow_usd") is not None]
        n = sum(r.get("flow_prints") or 0 for r in rr)
        flow_lines.append(
            f"| {DR.BAND_TITLE.get(b, b)} | "
            + (f"{np.median(v):+,.0f} $ | {np.mean(np.asarray(v) > 0):.0%} "
               f"| {n} |" if v else "— | — | 0 |"))

    next_lines = ["| доля пути до следующего начисления | медиана | "
                  "среднее | n |", "|---|---:|---:|---:|"]
    for f in DR.NEXT_FRACTIONS:
        v = [(r.get("to_next") or {}).get(f) for r in rows
             if r.get("to_next")]
        v = [x for x in v if x is not None]
        next_lines.append(
            f"| {f:.0%} | " + (f"{np.median(v):+.1f} б.п. | "
                               f"{np.mean(v):+.1f} | {len(v)} |"
                               if v else "— | — | 0 |"))
    res = {"at": time.time(), "window": [a.lo, hi_day],
           "n_symbols": len(symbols), "no_series": len(no_series),
           "ticket": a.ticket,
           "killers": {"K0": k0, "K1": k1, "K2": k2, "K3": k3, "K4": k4},
           "k1": k1s, "calib": calib, "slip": slip, "cell": cell,
           "mid_take": mid_take, "spread": spread,
           "lag": DR.lag_stats(rows),
           "tables": {"by_band": band_table(rows_by_band, a.ticket),
                      "profile": profile_table(rows_by_band),
                      "by_lag": "\n".join(lag_lines),
                      "flow": "\n".join(flow_lines),
                      "to_next": "\n".join(next_lines)}}
    res["verdict"] = DR.verdict(res["killers"])
    log("ВЕРДИКТ: " + res["verdict"]["say"])

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(report(res, res["at"]))
    dump = dict(res)
    dump["cell"] = {"stat": cell["stat"],
                    "form": {k: v for k, v in cell["form"].items()
                             if k != "daily"},
                    "daily": {str(k): v for k, v in
                              cell["form"]["daily"].items()}}
    dump["rows"] = [{k: v for k, v in r.items()
                     if k not in ("profile", "to_next")} for r in rows]
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=1, default=str)
    log(f"отчёт: {REPORT} ({time.time() - t_start:.0f} с)")
    state("готово", report=REPORT)
    if not a.no_publish and os.path.exists(PUBLISH):
        # Публикация — часть прогона: шаг, который можно забыть, рано
        # или поздно забывают.
        subprocess.run([PUBLISH, REPORT, "механика 2859b3d4: дрейф после "
                        "экстремального начисления"], check=False)
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
