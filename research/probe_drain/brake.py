"""Реплей двух правил против слива 08-24…27: тормоз дня и потолок шорта.

Решение владельца («оба запускай») по итогам разбора
`DRAIN-report-0824.md`: слив сделали шорты разогнанных имён и стопы на
раздутой волатильности, IC при этом был живой. Здесь оба названных
рычага меряются РЕПЛЕЕМ по записанным сделкам — сколько правило срезало
бы в окне слива и сколько стоило бы в базе. Это замер цены правила ДО
внедрения — порядок, дважды оправдавшийся на схлопывании и «доливе
только в плюс».

**Сетки объявлены до прогона и не растут.**

Правило 1 — ТОРМОЗ ДНЯ (забор, не обучение): когда реализованный
результат группы за календарные сутки UTC достиг −X, новые ВХОДЫ до
конца суток не открываются; выходы не гасятся никогда (выход —
обязанность, урок X2). Группа — (книга, рука): касса живёт по рукам,
и у каждой руки свой капитал 3000 $. X ∈ {30, 60, 90, 150} $ — это
1/2/3/5 % капитала руки. Рядом та же механика ОДНОЙ группой по всем
не-эхо книгам (X ∈ {300, 600, 900, 1500} $ — 1/2/3/5 % от 30 000).

Правило 2 — ПОТОЛОК ШОРТА В РАЗОГНАННЫХ: шорт не берётся, если ход
имени за R суток к моменту входа не меньше +T. Ход считается по
почасовым сводкам B1 (`s8_loop/out/summary/<SYM>/<день>.jsonl`,
`mid_close`) — середины ПЛОЩАДКИ ИСПОЛНЕНИЯ, тот же источник, на
котором книги торгуют; берётся последний ЗАКРЫТЫЙ час перед входом —
час входа ещё не закрыт и брать его значило бы заглядывать.
R ∈ {2, 3, 5} суток × T ∈ {20, 50, 100} %. Ход не измерен (нет сводки)
— сделка ОСТАЁТСЯ и считается отдельным числом: не измерено ≠ отсеяно.

**Оговорки, не снимаемые результатом.** (1) Эпизод слива один; выбор
лучшей ячейки после чтения таблицы — ошибка R5, таблица печатается
целиком как диагностика. (2) Касса не пересчитывается: выброшенная
сделка в реальности освободила бы деньги и изменила размеры соседних —
реплей меряет только снятый PnL. (3) Веса модели видели эти дни.

Запуск на VPS:
  cd ~/algoth_v2 && .venv/bin/python research/probe_drain/brake.py
"""

import argparse
import bisect
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(os.path.dirname(HERE), "probe_turn"),
          os.path.join(os.path.dirname(HERE), "s8_loop")):
    if p not in sys.path:
        sys.path.insert(0, p)

import drain as DR                                         # noqa: E402
import turn as PT                                          # noqa: E402

DAY = 86400
BRAKE_X = (30.0, 60.0, 90.0, 150.0)          # $ на (книга, рука)
BRAKE_X_GLOBAL = (300.0, 600.0, 900.0, 1500.0)
RUNUP_R = (2, 3, 5)                          # суток назад
RUNUP_T = (0.20, 0.50, 1.00)                 # порог хода
SUMMARY = os.path.join(ROOT, "research", "s8_loop", "out", "summary")


def log_(m):
    print(m, flush=True)


def load_trades(s8):
    """Закрытые сделки не-эхо книг с моментами входа и денег.

    Эхо-книги — те же решения под другим правилом: реплей по ним
    посчитал бы одно решение дважды.
    """
    out = []
    for key, name, echo in PT.BOOKS:
        if echo:
            continue
        trades, _m = PT.book_trades(os.path.join(s8, name))
        for t in trades:
            if t.get("t_in") is None or t.get("t_money") is None:
                continue
            if not (DR.in_win(t["day"], DR.BASE)
                    or DR.in_win(t["day"], DR.DRAIN)):
                continue
            out.append({**t, "book": key})
    return out


def replay_brake(trades, x, group_of):
    """Тормоз дня: вход при реализованном дне группы ≤ −X не берётся.

    Хронология честная: решение о входе видит только деньги, ставшие
    известными ДО момента входа, и только от ПРИНЯТЫХ сделок — деньги
    выброшенной сделки не существуют и тормозить не могут.
    """
    entries = sorted(trades, key=lambda t: t["t_in"])
    pending = []                 # деньги принятых сделок, ждут момента
    realized = {}                # (группа, день) -> $
    dropped = []
    pi = 0
    for t in entries:
        # долить деньги, ставшие известными к моменту входа
        while pi < len(pending) and pending[pi][0] <= t["t_in"]:
            _tm, _k, g, d, pnl = pending[pi]
            realized[(g, d)] = realized.get((g, d), 0.0) + pnl
            pi += 1
        g = group_of(t)
        d_in = int(t["t_in"] // DAY)
        if realized.get((g, d_in), 0.0) <= -x:
            dropped.append(t)
            continue
        # деньги ПРИНЯТОЙ сделки встают в очередь по своему моменту;
        # ключ-счётчик разводит равные моменты, не сравнивая группы
        bisect.insort(pending, (t["t_money"], len(pending), g,
                                int(t["t_money"] // DAY), t["pnl"]))
    return dropped


def brake_table(trades, xs, group_of, label):
    rows = []
    for x in xs:
        dropped = replay_brake(trades, x, group_of)
        dr_ids = {id(t) for t in dropped}
        row = {"x": x, "label": label}
        for tag, win in (("base", DR.BASE), ("drain", DR.DRAIN)):
            inw = [t for t in trades if DR.in_win(t["day"], win)]
            cut = [t for t in inw if id(t) in dr_ids]
            row[tag] = {"pnl0": round(sum(t["pnl"] for t in inw), 2),
                        "cut": round(-sum(t["pnl"] for t in cut), 2),
                        "n_cut": len(cut), "n": len(inw)}
        rows.append(row)
    return rows


def load_mids(symbols, log=log_):
    """Почасовые середины по сводкам B1: {sym: {hour_ts: mid}}."""
    mids = {}
    missing = 0
    for sym in sorted(symbols):
        sdir = os.path.join(SUMMARY, sym)
        try:
            days = sorted(os.listdir(sdir))
        except OSError:
            missing += 1
            continue
        d = {}
        for fn in days:
            if not fn.endswith(".jsonl"):
                continue
            for r in PT.read_jsonl(os.path.join(sdir, fn)):
                h, m = r.get("hour"), r.get("mid_close")
                if not h or m is None:
                    continue
                ts = int(datetime.strptime(
                    h, "%Y-%m-%d-%H").replace(
                    tzinfo=timezone.utc).timestamp())
                d[ts] = float(m)
        if d:
            mids[sym] = d
    if missing:
        log(f"  сводок нет у {missing} имён — их ход не измерен")
    return mids


def runup(mids, sym, t_in, r_days):
    """Ход за R суток к последнему ЗАКРЫТОМУ часу перед входом.

    Час входа ещё идёт, его закрытие в момент решения не существует —
    взять его значило бы заглядывать (тот же класс, что цена
    незакрытого бара в L1).
    """
    d = mids.get(sym)
    if not d:
        return None
    h_now = (int(t_in) // 3600) * 3600 - 3600
    a = d.get(h_now)
    b = d.get(h_now - r_days * DAY)
    if a is None or b is None or b <= 0:
        return None
    return a / b - 1.0


def runup_table(trades, mids):
    shorts = [t for t in trades if t.get("side") == "short"]
    rows = []
    for r_days in RUNUP_R:
        ru = {id(t): runup(mids, t["sym"], t["t_in"], r_days)
              for t in shorts}
        unmeasured = sum(1 for v in ru.values() if v is None)
        for thr in RUNUP_T:
            cut_ids = {k for k, v in ru.items()
                       if v is not None and v >= thr}
            row = {"r": r_days, "t": thr, "unmeasured": unmeasured}
            for tag, win in (("base", DR.BASE), ("drain", DR.DRAIN)):
                inw = [t for t in shorts if DR.in_win(t["day"], win)]
                cut = [t for t in inw if id(t) in cut_ids]
                nets = [t["net"] for t in inw if id(t) not in cut_ids
                        and t.get("net") is not None]
                row[tag] = {
                    "n": len(inw), "n_cut": len(cut),
                    "cut": round(-sum(t["pnl"] for t in cut), 2),
                    "worst_after": round(min(nets), 1) if nets else None}
            rows.append(row)
    return rows


def write_report(path, brk, brk_g, ru, meta):
    L = ["# Реплей правил против слива: тормоз дня и потолок шорта\n",
         f"\nПрогон {meta['when']} · база {DR.BASE[0]}…{DR.BASE[1]} · "
         f"окно слива {DR.DRAIN[0]}…{DR.DRAIN[1]} · сделок в реплее "
         f"{meta['n']} (не-эхо книги)\n",
         "\n**Это замер цены правила, а не внедрение.** Сетки объявлены "
         "до прогона; эпизод слива один, и выбор лучшей ячейки после "
         "чтения — ошибка R5. Касса не пересчитывается: реплей меряет "
         "снятый PnL, а не перераспределение освободившихся денег.\n"]

    L.append("\n## Правило 1 — тормоз дня\n\n")
    L.append("Вход не берётся, когда реализованный день группы уже "
             "хуже −X; выходы не гасятся никогда. «Срезано» — PnL "
             "выброшенных сделок с обратным знаком: плюс означает, что "
             "правило деньги СЭКОНОМИЛО.\n\n")
    for label, rows in (("по (книга, рука), X от капитала руки 3000 $",
                         brk),
                        ("одной группой по всем книгам, X от 30 000 $",
                         brk_g)):
        L.append(f"\n### {label}\n\n")
        L.append("| X, $ | срезано в сливе, $ | сделок | из них | "
                 "срезано в базе, $ | сделок | из них | итог окна "
                 "с правилом | итог базы с правилом |\n")
        L.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|\n")
        for r in rows:
            b, d = r["base"], r["drain"]
            L.append(
                f"| {r['x']:.0f} | **{d['cut']:+.2f}** | {d['n_cut']} "
                f"| {d['n']} | {b['cut']:+.2f} | {b['n_cut']} | "
                f"{b['n']} | {d['pnl0'] + d['cut']:+.2f} | "
                f"{b['pnl0'] + b['cut']:+.2f} |\n")
        L.append(f"\nБез правила: окно {rows[0]['drain']['pnl0']:+.2f} "
                 f"$, база {rows[0]['base']['pnl0']:+.2f} $.\n")

    L.append("\n## Правило 2 — потолок шорта в разогнанных именах\n\n")
    L.append("Шорт не берётся при ходе имени за R суток не меньше +T "
             "(по серединам площадки исполнения, последний закрытый "
             "час перед входом). Лонги не тронуты. Ход не измерен — "
             "сделка остаётся: не измерено ≠ отсеяно.\n\n")
    L.append("| R, сут | T | не измерено | срезано в сливе, $ | "
             "шортов срезано | из | срезано в базе, $ | шортов | из | "
             "худший нетто после, б.п. (слив) |\n")
    L.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|\n")
    for r in ru:
        b, d = r["base"], r["drain"]
        L.append(
            f"| {r['r']} | +{r['t']:.0%} | {r['unmeasured']} | "
            f"**{d['cut']:+.2f}** | {d['n_cut']} | {d['n']} | "
            f"{b['cut']:+.2f} | {b['n_cut']} | {b['n']} | "
            f"{DR.fmt(d['worst_after'], '+.1f')} |\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="реплей тормоза и потолка")
    ap.add_argument("--s8", default=os.path.join(
        ROOT, "research", "s8_loop", "out"))
    ap.add_argument("--tag", default="0824")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)

    trades = load_trades(a.s8)
    log_(f"сделок в реплее: {len(trades)}")
    if not trades:
        log_("сделок нет — реплеить нечего")
        return 1
    brk = brake_table(trades, BRAKE_X,
                      lambda t: (t["book"], t["arm"]), "per-arm")
    brk_g = brake_table(trades, BRAKE_X_GLOBAL,
                        lambda t: "all", "global")
    syms = {t["sym"] for t in trades if t.get("side") == "short"}
    mids = load_mids(syms)
    ru = runup_table(trades, mids)

    art = {"n": len(trades), "brake": brk, "brake_global": brk_g,
           "runup": ru, "took_sec": round(time.time() - t0, 1)}
    with open(os.path.join(out_dir, f"brake-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    path = write_report(
        os.path.join(out_dir, f"DRAIN-brake-{a.tag}.md"),
        brk, brk_g, ru,
        {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
         "n": len(trades)})
    log_(f"отчёт: {path} · {art['took_sec']} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
