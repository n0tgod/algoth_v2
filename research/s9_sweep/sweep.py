#!/usr/bin/env python3
"""
Перебор правил ситуационной книги по УЖЕ ЗАПИСАННЫМ решениям модели.

Вопрос владельца: что изменить, чтобы у ситуационных сделок появилась
положительная статистика — фильтр по RR (не 1:2, а 1:3 и выше), более
редкий и «ювелирный» вход, что-то ещё. Живая книга даёт десятки
сделок, и на них не измеряется ничего. Здесь берётся ВСЁ, что модель
успела записать: каждая нога каждого часового выбора несёт цену
входа, прогноз `fwd` и оба конца обещанного пути (`mae` — ход против
позиции, `mfe` — в пользу). Этого достаточно, чтобы прогнать сделку
по минутным барам собственной записи сборщика и посмотреть, чем бы
она кончилась при других порогах.

Чего этот прогон НЕ делает и почему
-----------------------------------

Он не переобучает модель по ходу истории: веса берутся те, что есть,
а предсказания — те, что уже записаны в выборы. Значит для старых
часов оценка ОПТИМИСТИЧНА (веса видели эти часы в обучении), и читать
её надо как верхнюю границу, а не как бэктест. Приём тот же, что
потолок рычагов в S1: сначала самая дешёвая оценка, способная убить
направление.

Он не рассматривает имена, которых модель не выбрала: в записи лежат
только шесть ног на час на руку. Значит распределение RR усечено
сверху отбором, и вопрос «а если брать только RR ≥ 3» отвечается на
той выборке, какую отбор и так даёт. Чтобы спрашивать шире, нужен
журнал листов сечения — он заведён этой же правкой (`sheets.jsonl`),
и через несколько суток перебор станет полным.

Сетка ОБЪЯВЛЕНА здесь и не меняется после результата
----------------------------------------------------

Порог края `|fwd| ∈ {22, 33, 44, 66}` б.п. (22 — двойной круг
издержек, дальше кратно), порог отношения `RR ∈ {1.5, 2, 3, 4}`,
выход `{с целью, без цели}`. Итого 32 ячейки. Отчёт печатает ВСЕ,
решение — по медиане, а не по лучшей: выбрать лучшую ячейку и
отчитаться по ней есть та же ошибка, от которой защищала поправка BH
в A4, только без поправки.

Нуль момента: те же ноги, та же геометрия, но вход сдвинут на шесть
часов вперёд. Если прогон не отличается от нуля, значит платим за
момент, которого нет (в T4 этот нуль стоил +2.9 б.п. из −14.9).

Издержки — круг `trades.ROUND_COST_BP` (11 б.п. на ногу), тот же
константой, что у книги и отчётов.

    python3 research/s9_sweep/sweep.py --root research/b1_book/out \\
        --books research/s8_loop/out/model research/s8_loop/out/model_sit
"""

import argparse
import json
import os
import statistics as st
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))
import trades as TR                                          # noqa: E402

# Объявленная сетка. Меняется только правкой этого файла ДО прогона.
EDGES = [22.0, 33.0, 44.0, 66.0]
RRS = [1.5, 2.0, 3.0, 4.0]
TAKE = [True, False]              # выход по цели / только стоп и срок
MAX_AGE_H = 24                    # предел возраста, как у книги
NULL_SHIFT_H = 6                  # сдвиг нуля момента
MIN_CELL = 30                     # меньше — «не измеряется», а не «ноль»


def hour_ts(hour):
    return TR._ts(hour)


class HttpBars:
    """Бары через страницу наблюдения, когда записи нет под рукой.

    Считать перебор можно там, где лежит запись (сервер), и там, где
    сидит ассистент (песочница) — второе требует того же источника, а
    не второй копии данных. Эндпоинт отдаёт минутные свечи из ТЕХ ЖЕ
    файлов, что читает локальный путь, поэтому числа совпадают.

    Две тонкости, каждая из которых молча испортила бы результат:
    окно эндпоинта не больше 72 часов (просьба о большем молча
    урезается), и неизвестный символ он ПОДМЕНЯЕТ первым из списка —
    значит ответ обязан сверяться по имени, иначе чужие бары уехали бы
    в чужую сделку.
    """

    def __init__(self, base, key, log=print, disk=None):
        self.base, self.key, self.log = base.rstrip("/"), key, log
        self.cache = {}
        self.miss = 0
        # Кеш на диске: добавить нулевую модель — значит пересчитать
        # те же ноги, и второй обход по сети за теми же барами есть
        # чистая потеря времени (первый шёл семь минут).
        self.disk = disk
        if disk:
            os.makedirs(disk, exist_ok=True)

    def bars(self, sym, t0, t1):
        import urllib.parse
        import urllib.request
        got = self.cache.get(sym)
        if got is None:
            got = self.cache[sym] = {}
        # Просим РОВНО нужное окно, а не предел эндпоинта: он читает
        # по часовому файлу на каждый запрошенный час, и лишние сорок
        # восемь часов — это втрое дольше на каждый запрос. Первый
        # прогон из-за этого шёл двадцать минут и был убит.
        need, end = [], t1
        while end > t0:
            span = min(72, max(1, int((end - t0) // 3600) + 1))
            need.append((end, span))
            end -= span * 3600
        out = []
        for e, span in need:
            key = (int(e // 3600), span)
            chunk = got.get(key)
            dpath = (os.path.join(self.disk, f"{sym}-{key[0]}-{key[1]}.json")
                     if self.disk else None)
            if chunk is None and dpath and os.path.exists(dpath):
                try:
                    with open(dpath, encoding="utf-8") as fh:
                        chunk = got[key] = json.load(fh)
                except (OSError, ValueError):
                    chunk = None
            if chunk is None:
                q = urllib.parse.urlencode({
                    "k": self.key, "sym": sym, "hours": span,
                    "end": int(e)})
                try:
                    with urllib.request.urlopen(
                            f"{self.base}/candles?{q}", timeout=60) as r:
                        d = json.loads(r.read().decode("utf-8"))
                except Exception as ex:                   # noqa: BLE001
                    self.log(f"  {sym}: свечи не пришли ({ex})")
                    d = {}
                if d.get("sym") != sym:
                    # Подмена символа сервером: молча взять эти бары —
                    # значит посчитать сделку по чужой цене.
                    self.miss += 1
                    d = {}
                chunk = got[key] = d.get("candles") or []
                if dpath:
                    try:
                        with open(dpath, "w", encoding="utf-8") as fh:
                            json.dump(chunk, fh)
                    except OSError:
                        pass
            out += chunk
        return sorted({b[0]: b for b in out}.values(),
                      key=lambda b: b[0])


def read_bars(root, sym, t0, t1):
    """Минутные бары собственной записи сборщика в окне `[t0, t1]`.

    Пустая минута отсутствует, а не выходит нулевой (урок A2), поэтому
    ходьба по барам обязана смотреть на время бара, а не на их число.
    """
    from collect import minute_bars
    from store import read_hour
    out = []
    h = int(t0 // 3600) * 3600
    while h <= t1:
        hh = datetime.fromtimestamp(h, timezone.utc).strftime(
            "%Y-%m-%d-%H")
        rows = read_hour(os.path.join(root, "trades", sym), hh)
        if rows:
            out += minute_bars(rows)
        h += 3600
    return [b for b in out if t0 <= b[0] <= t1]


def bracket(bars, entry_ts, entry_px, side, adv, fav, max_h=MAX_AGE_H,
            take=True):
    """Чем кончилась сделка: стоп, цель или срок.

    `adv` — обещанный ход ПРОТИВ позиции (у лонга отрицательный),
    `fav` — В ПОЛЬЗУ. Внутри одного бара касание обоих уровней
    решается ПРОТИВ нас: минута не разрешает порядок, и приписывать
    себе лучший исход значило бы завышать результат систематически
    (то же правило, что в замерах T3/T4 и у живого сторожа).

    Возвращает `(исход, ход в б.п., время выхода)`; `None` — если
    баров нет вовсе (запись не покрывает окно), и такая нога в
    статистику не идёт: пропуск не есть нулевой результат.
    """
    if not entry_px or entry_px <= 0:
        return None
    end = entry_ts + max_h * 3600
    seen = [b for b in bars if b[0] >= entry_ts and b[0] <= end]
    if not seen:
        return None
    hi_lvl = entry_px * (1 + (adv if side == "short" else fav) / 1e4)
    lo_lvl = entry_px * (1 + (fav if side == "short" else adv) / 1e4)
    for b in seen:
        low, high = b[3], b[2]
        if side == "long":
            if low <= lo_lvl:
                return "стоп", (lo_lvl / entry_px - 1) * 1e4, b[0]
            if take and high >= hi_lvl:
                return "цель", (hi_lvl / entry_px - 1) * 1e4, b[0]
        else:
            if high >= hi_lvl:
                return "стоп", (hi_lvl / entry_px - 1) * 1e4, b[0]
            if take and low <= lo_lvl:
                return "цель", (lo_lvl / entry_px - 1) * 1e4, b[0]
    last = seen[-1]
    return "срок", (last[4] / entry_px - 1) * 1e4, last[0]


def net_bp(side, move, adv):
    """Нетто ноги и её риск в тех же единицах.

    Знак переворачивается стороной, круг издержек вычитается один раз
    — ровно как в разборе книги (`train.situational_arm`).
    """
    raw = (1 if side == "long" else -1) * move - TR.ROUND_COST_BP
    risk = abs(adv) + TR.ROUND_COST_BP
    return raw, (raw / risk if risk else None)


def legs_of(book_dir):
    """Ноги всех выборов книги: цена входа, прогноз, обещания пути."""
    recs = []
    try:
        with open(os.path.join(book_dir, "picks.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return legs_of_records(recs, os.path.basename(book_dir))


def legs_of_records(recs, book):
    """Разбор записей выбора — ОДИН на оба источника (файл и HTTP).

    Вторая копия разбора однажды разошлась бы с первой, и перебор,
    считанный в песочнице, отличался бы от считанного на сервере, не
    выдавая себя ничем.
    """
    out = []
    for pk in recs:
        hour = pk.get("hour")
        t0 = hour_ts(hour)
        if t0 is None:
            continue
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                if p.get("mae") is None or p.get("mfe") is None:
                    continue
                if not p.get("px"):
                    continue
                out.append({
                    "book": book,
                    "arm": pk.get("arm") or "gbm",
                    "hour": hour, "sym": p.get("sym"),
                    "side": side, "px": float(p["px"]),
                    "fwd": float(p.get("fwd") or 0.0),
                    "mae": float(p["mae"]),
                    "mfe": float(p["mfe"]),
                    # Живой вход сканера открыт своей секундой;
                    # часовой — закрытием часа сигнала.
                    "at": float(p.get("at_ts") or (t0 + 3600)),
                })
    return out


def rr_of(leg):
    return abs(leg["mfe"]) / abs(leg["mae"]) if leg["mae"] else None


def run(root, books, log=print, src=None, legs=None):
    """`src` — источник баров (`None` — записи на диске)."""
    if legs is None:
        legs = []
        for b in books:
            got = legs_of(b)
            log(f"{os.path.basename(b)}: ног {len(got)}")
            legs += got
    if not legs:
        raise SystemExit("выборов не найдено — нечего перебирать")
    # Бары читаются ОДИН раз на ногу и переиспользуются всеми ячейками:
    # иначе один и тот же час читался бы тридцать два раза.
    said = time.time()
    for i, lg in enumerate(legs):
        if time.time() - said > 30:
            log(f"  бары: {i}/{len(legs)} ног")
            said = time.time()
        t0 = lg["at"]
        get = src.bars if src else (
            lambda sym, a, b: read_bars(root, sym, a, b))
        lg["bars"] = get(lg["sym"], t0, t0 + MAX_AGE_H * 3600)
        lg["bars_null"] = get(lg["sym"], t0 + NULL_SHIFT_H * 3600,
                              t0 + (NULL_SHIFT_H + MAX_AGE_H) * 3600)
        lg["rr"] = rr_of(lg)
    cells = []
    for edge in EDGES:
        for rr_min in RRS:
            for take in TAKE:
                sel = [g for g in legs
                       if abs(g["fwd"]) >= edge
                       and (g["rr"] or 0) >= rr_min]
                cell = {"edge": edge, "rr": rr_min, "take": take,
                        "n_legs": len(sel)}
                cell.update(measure(sel, take))
                cell.update({f"null_{k}": v for k, v in
                             measure(sel, take, null=True).items()})
                cell.update({f"mir_{k}": v for k, v in
                             measure(sel, take, mirror=True).items()})
                cells.append(cell)
    return legs, cells


def measure(sel, take, null=False, mirror=False):
    """`null` — сдвиг момента, `mirror` — та же сделка в другую сторону.

    Второй нуль решает вопрос, на который первый не отвечает: сдвиг
    времени сохраняет СТОРОНУ, которую выбрала модель, и если рынок в
    окне куда-то ехал, оба замера поймают этот ход одинаково. Зеркало
    оставляет момент и геометрию и переворачивает направление — если
    и оно даёт то же, значит меряется свойство рынка и ширина
    бракета, а не выбор модели.
    """
    nets, rs, out = [], [], {"стоп": 0, "цель": 0, "срок": 0}
    for g in sel:
        side = g["side"]
        adv, fav = g["mae"], g["mfe"]
        if mirror:
            # Зеркало: та же ширина уровней, другая сторона. Обещания
            # переставляются знаком, потому что записаны В ЕДИНИЦАХ
            # ПОЗИЦИИ, а не цены (`path_fields`).
            side = "short" if side == "long" else "long"
            adv, fav = -adv, -fav
        bars = g["bars_null"] if null else g["bars"]
        t0 = g["at"] + (NULL_SHIFT_H * 3600 if null else 0)
        px = g["px"]
        if null:
            # У нуля вход по цене ТОГО момента: сдвинуть время и
            # оставить прежнюю цену значило бы сравнивать сделку с
            # выдумкой, а не со случайным моментом.
            first = [b for b in bars if b[0] >= t0]
            if not first:
                continue
            px = first[0][1]
        got = bracket(bars, t0, px, side, adv, fav, take=take)
        if got is None:
            continue
        why, move, _ = got
        n, r = net_bp(side, move, adv)
        nets.append(n)
        if r is not None:
            rs.append(r)
        out[why] += 1
    n = len(nets)
    if not n:
        return {"n": 0}
    wins = sum(1 for v in nets if v > 0)
    return {
        "n": n,
        "win": round(wins / n, 3),
        "exp_bp": round(sum(nets) / n, 1),
        "med_bp": round(st.median(nets), 1),
        "exp_r": round(sum(rs) / len(rs), 3) if rs else None,
        "worst_bp": round(min(nets), 1),
        "best_bp": round(max(nets), 1),
        "stop": out["стоп"], "target": out["цель"], "time": out["срок"],
    }


def report(legs, cells, path, root, books):
    lines = ["# Перебор правил ситуационной книги", ""]
    lines += [
        f"- ног в записи: **{len(legs)}**, книги: "
        f"{', '.join(os.path.basename(b) for b in books)}",
        f"- бары: собственная запись сборщика (`{root}`), минутные",
        f"- издержки: круг {TR.ROUND_COST_BP} б.п. на ногу, "
        f"предел возраста {MAX_AGE_H} ч",
        f"- нуль момента: тот же набор со сдвигом входа на "
        f"{NULL_SHIFT_H} ч",
        f"- ячейка меньше {MIN_CELL} сделок считается НЕизмеренной и "
        f"в медиану не входит",
        "",
        "Оценка ОПТИМИСТИЧНА: веса модели видели эти часы в обучении, "
        "и рассматриваются только те имена, которые отбор уже выбрал. "
        "Читать как верхнюю границу, а не как бэктест.",
        "",
        "## Все ячейки объявленной сетки",
        "",
        "| край, б.п. | RR ≥ | цель | сделок | побед | ожидание, б.п. "
        "| медиана | R | стоп/цель/срок | нуль момента | зеркало |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    ok = [c for c in cells if c.get("n", 0) >= MIN_CELL]
    for c in cells:
        n = c.get("n", 0)
        if not n:
            lines.append(f"| {c['edge']:.0f} | {c['rr']} | "
                         f"{'да' if c['take'] else 'нет'} | 0 | — | — | "
                         f"— | — | — | — | — |")
            continue
        r_txt = "—" if c.get("exp_r") is None else f"{c['exp_r']:+.2f}"
        few = "" if n >= MIN_CELL else " ·мало"
        lines.append(
            f"| {c['edge']:.0f} | {c['rr']} | "
            f"{'да' if c['take'] else 'нет'} | {n}{few} | {c['win']} | "
            f"{c['exp_bp']:+} | {c['med_bp']:+} | {r_txt} | "
            f"{c['stop']}/{c['target']}/{c['time']} | "
            f"{c.get('null_exp_bp', '—')} | {c.get('mir_exp_bp', '—')} |")
    if ok:
        med = st.median([c["exp_bp"] for c in ok])
        med_null = st.median([c.get("null_exp_bp") or 0.0 for c in ok])
        med_mir = st.median([c.get("mir_exp_bp") or 0.0 for c in ok])
        best = max(ok, key=lambda c: c["exp_bp"])
        lines += [
            "", "## Итог", "",
            f"- измеренных ячеек: **{len(ok)}** из {len(cells)}",
            f"- медиана ожидания по измеренным: **{med:+.1f} б.п.**, "
            f"у нуля момента {med_null:+.1f}, у зеркала {med_mir:+.1f}",
            "- **читать надо разность, а не уровень**: если прогон, "
            "сдвинутый момент и перевёрнутая сторона дают одно и то же, "
            "меряется ширина бракета и ход рынка в окне, а не выбор "
            "модели",
            f"- лучшая ячейка: край {best['edge']:.0f}, RR ≥ "
            f"{best['rr']}, цель "
            f"{'да' if best['take'] else 'нет'} — {best['exp_bp']:+} "
            f"б.п. на {best['n']} сделках. Одна ячейка из "
            f"{len(cells)} — это ВЫБОР ИЗ МНОГИХ, и предъявлять её "
            f"как результат нельзя: смотреть надо на медиану.",
        ]
    else:
        lines += ["", "## Итог", "",
                  f"Ни одна ячейка не набрала {MIN_CELL} сделок — "
                  f"перебор ничего не измерил. Это ответ о размере "
                  f"выборки, а не о правилах."]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path



def legs_from_http(base, key, books, log=print):
    """Выборы через страницу наблюдения: те же записи, другой путь."""
    import urllib.parse
    import urllib.request
    q = urllib.parse.urlencode({"k": key})
    with urllib.request.urlopen(f"{base.rstrip('/')}/model?{q}",
                                timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    src = {"model": d}
    for name, b in (d.get("books") or {}).items():
        src["model_" + name] = b
    out = []
    for want in books:
        base_name = os.path.basename(want)
        blk = src.get(base_name)
        if not blk:
            log(f"{base_name}: книги нет в ответе — пропуск")
            continue
        got = legs_of_records(blk.get("picks") or [], base_name)
        log(f"{base_name}: ног {len(got)}")
        out += got
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(HERE), "b1_book", "out"))
    ap.add_argument("--books", nargs="+", default=[
        os.path.join(os.path.dirname(HERE), "s8_loop", "out", "model"),
        os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                     "model_sit")])
    ap.add_argument("--out", default=os.path.join(
        HERE, "out", "S9-sweep.md"))
    # Считать можно там, где лежит запись, и там, где сидит ассистент:
    # источник один и тот же, путь разный.
    ap.add_argument("--http", default="",
                    help="адрес страницы наблюдения вместо записей")
    ap.add_argument("--key", default="", help="ключ страницы")
    ap.add_argument("--cache", default="",
                    help="каталог кеша баров: пересчёт с другим нулём "
                         "не должен стоить нового обхода по сети")
    a = ap.parse_args()
    src = legs = None
    if a.http:
        src = HttpBars(a.http, a.key, disk=a.cache or None)
        legs = legs_from_http(a.http, a.key, a.books)
    legs, cells = run(a.root, a.books, src=src, legs=legs)
    if src and src.miss:
        print(f"ВНИМАНИЕ: {src.miss} ответов с чужим символом отброшено")
    with open(os.path.join(os.path.dirname(a.out), "cells.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": cells, "legs": len(legs)}, f,
                  ensure_ascii=False, indent=1)
    print("отчёт:", report(legs, cells, a.out, a.root, a.books))


if __name__ == "__main__":
    main()
