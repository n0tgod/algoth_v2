#!/usr/bin/env python3
"""Живые события ситуационной книги → строки выбора и разбора.

Просьба владельца: pnl должен появляться сразу после закрытия сделки,
а не в ближайший часовой цикл. Число само по себе простое; час стоил
не расчёт, а дисциплина — у файлов книги один писатель, и деньги
обязаны быть одними у страницы, кассы и Rust-тени. Поэтому решение
такое: превращение событий вынесено в ОДИН модуль, его зовут два
места — сборщик в момент события (секунды) и часовой цикл страховкой
(упавший сборщик, старые события), — а одновременную запись двух
процессов разводит файловый замок. Ни одна формула не копируется:
`net` считается здесь и только здесь, лесенку сжимает `trades.
cum_ladder`, деньги по-прежнему штампует касса при чтении.

Стандартная библиотека намеренно: модуль импортирует сборщик, который
живёт без numpy.

Лесенка исполнения: цикл ставил её на момент СВОЕГО прогона (до часа
после выхода), сборщик ставит на момент поглощения — секунды после
события. Второе ближе к правде исполнения; источник у обоих один —
книга площадки, сжатая одной функцией.
"""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import trades as TR


def read_jsonl(path):
    """Строки jsonl; битая строка пропускается, нет файла — пусто."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


@contextmanager
def book_lock(mdir):
    """Замок книги: выборы и разбор пишут два процесса по очереди.

    Сборщик поглощает события в момент их записи, цикл — страховкой
    раз в час; без замка их дозапись в один файл однажды переплелась
    бы. Замок берётся на КАТАЛОГ книги целиком: превращение читает
    оба файла и дописывает оба, и замок на каждый файл отдельно
    оставил бы окно между ними.
    """
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, ".book.flock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def sit_open_positions(picks, reviews, arm):
    """Открытые позиции ситуационной книги — перечитыванием файлов.

    Состояние выводится, а не накапливается (правило журнала бота):
    позиция открыта, если её выбор записан, а разбора с её ключом нет.
    """
    done = set()
    for rv in reviews:
        if (rv.get("arm") or "gbm") != arm:
            continue
        for r in rv.get("rows") or []:
            done.add((rv.get("hour"), r.get("sym"), r.get("side")))
    out = []
    for pk in picks:
        if (pk.get("arm") or "gbm") != arm:
            continue
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                if (pk.get("hour"), p.get("sym"), side) in done:
                    continue
                out.append({"hour": pk.get("hour"), "sym": p.get("sym"),
                            "side": side, "px": p.get("px"),
                            "fwd": p.get("fwd"), "mae": p.get("mae"),
                            "mfe": p.get("mfe")})
    return out


def fresh_picks(mdir, arm, picks_all=None):
    """Живые входы сканера, ещё не ставшие строками выбора.

    Возвращает записи выбора по часам листа — БЕЗ записи на диск:
    писать решает вызвавший, под замком. Поля события переезжают в
    строку целиком, включая номер обучения листа (`train_seq` идёт с
    листа, породившего вход, а не с цикла — между ними может лежать
    новое обучение) и числа правил v11 (`noise_bp`, `eaten`).
    """
    ev_entries = [e for e in read_jsonl(
        os.path.join(mdir, "entries_live.jsonl"))
        if (e.get("arm") or "gbm") == arm]
    if picks_all is None:
        picks_all = read_jsonl(os.path.join(mdir, "picks.jsonl"))
    have = {(p.get("sym"), p.get("at_ts"))
            for pk in picks_all if (pk.get("arm") or "gbm") == arm
            for side in ("long", "short")
            for p in pk.get(side) or []}
    fresh = {}
    for e in ev_entries:
        if (e.get("sym"), e.get("at_ts")) in have:
            continue
        row = {"sym": e.get("sym"), "fwd": e.get("fwd"),
               "px": e.get("px"), "mae": e.get("mae"),
               "mfe": e.get("mfe"), "rr": e.get("rr"),
               "fwd0": e.get("fwd0"),
               "at_ts": e.get("at_ts"), "scan": True}
        for k in ("mae_m", "adverse_of", "favourable_of", "why",
                  "setup", "train_seq", "scan_rank",
                  "noise_bp", "eaten"):
            if e.get(k) is not None:
                row[k] = e[k]
        if e.get("odd") is not None:
            row["odd"] = e["odd"]
        rec = fresh.setdefault(e.get("hour"), {
            "arm": arm, "hour": e.get("hour"),
            "at_ts": round(time.time(), 3), "scan": True,
            "long": [], "short": []})
        rec[e.get("side") or "long"].append(row)
    return [fresh[h] for h in sorted(fresh)]


def write_picks(mdir, recs, log_=None):
    for rec in recs:
        with open(os.path.join(mdir, "picks.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if log_ is not None:
            n = len(rec["long"]) + len(rec["short"])
            log_(f"ситуационная [{rec['arm']}]: {n} живых входов часа "
                 f"{rec['hour']} записаны в книгу")


def live_exit_rows(mdir, arm, picks_all=None, reviews_all=None):
    """Строки разбора для позиций, закрытых ЖИВЫМ сторожем.

    Только событийные выходы: цена и время — из момента пересечения
    (урок S1 про закрытие пробившего бара). Часовые причины (разворот
    прогноза, предел возраста, страховочный замер по концу часа)
    остаются циклу — им нужны модель и цены часа. Первое пересечение
    решает; событие по уже разобранной позиции отсеивается тем, что
    открытых с её ключом больше нет.
    """
    if picks_all is None:
        picks_all = read_jsonl(os.path.join(mdir, "picks.jsonl"))
    if reviews_all is None:
        reviews_all = read_jsonl(os.path.join(mdir, "review.jsonl"))
    events = {}
    for ev in read_jsonl(os.path.join(mdir, "exits_live.jsonl")):
        if (ev.get("arm") or "gbm") != arm:
            continue
        k = (ev.get("hour"), ev.get("sym"), ev.get("side"))
        if k not in events:              # первое пересечение решает
            events[k] = ev
    by_hour = {}
    for p in sit_open_positions(picks_all, reviews_all, arm):
        ev = events.get((p["hour"], p["sym"], p["side"]))
        if ev is None:
            continue
        fav = p.get("mfe")
        move = float(ev.get("move_bp") or 0.0)
        exit_ts = ev.get("at_ts")
        exit_hour = (datetime.fromtimestamp(
            exit_ts, timezone.utc).strftime("%Y-%m-%d-%H")
            if exit_ts else None)
        rr = {"sym": p["sym"], "side": p["side"],
              "expected": round(fav, 1) if fav is not None else None,
              "got": round(move, 1),
              "net": round((1 if p["side"] == "long" else -1) * move
                           - TR.ROUND_COST_BP, 1),
              "exit_hour": exit_hour,
              "reason": (ev.get("reason")
                         or "цена прошла обещанный ход против"),
              "live": True, "exit_ts": exit_ts,
              "exit_px": ev.get("px")}
        by_hour.setdefault(p["hour"], []).append(rr)
    return by_hour


def write_reviews(mdir, arm, by_hour, ladders, log_=None):
    """Дозапись строк разбора; лесенка выхода — из переданной книги."""
    for hour, rows_rv in by_hour.items():
        for r in rows_rv:
            if r["sym"] in (ladders or {}):
                r["cum"] = ladders[r["sym"]]
        with open(os.path.join(mdir, "review.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(
                {"arm": arm, "hour": hour,
                 "cost_bp": TR.ROUND_COST_BP,
                 "at_ts": round(time.time(), 3), "rows": rows_rv},
                ensure_ascii=False) + "\n")
        if log_ is not None:
            log_(f"ситуационная [{arm}]: закрыто {len(rows_rv)} "
                 f"({'; '.join(r['sym'] + ' — ' + r['reason'] for r in rows_rv)})")


def absorb(mdir, ladder_of, log_=None, arms=("gbm", "nn")):
    """Полное поглощение живых событий книги, под замком.

    `ladder_of(syms)` — книга исполнения на момент вызова:
    `{sym: {mid, b, a, t}}` со сжатыми лесенками (`trades.cum_ladder`).
    Сборщик передаёт свою живую книгу, цикл — снимок из записи.
    Возвращает `(входов, выходов)`; повторный вызов ничего не находит
    — превращённое отсеивается чтением самих файлов, состояние не
    накапливается нигде.
    """
    n_in = n_out = 0
    with book_lock(mdir):
        for arm in arms:
            recs = fresh_picks(mdir, arm)
            write_picks(mdir, recs, log_)
            n_in += sum(len(r["long"]) + len(r["short"]) for r in recs)
            by_hour = live_exit_rows(mdir, arm)
            if by_hour:
                syms = sorted({r["sym"] for rows in by_hour.values()
                               for r in rows})
                write_reviews(mdir, arm, by_hour,
                              ladder_of(syms) if ladder_of else {},
                              log_)
                n_out += sum(len(v) for v in by_hour.values())
    return n_in, n_out
