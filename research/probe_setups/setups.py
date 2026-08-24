"""Зонд сетапов: есть ли ярлык ситуации, устойчивый по ВСЕМ книгам и рукам.

Вопрос владельца (2026-08-24): «есть ли у нас сетапы, которые
стабильнее всего отрабатывают по всем нашим моделям/книгам».

Что здесь считается сетапом. Дискретных стратегий у модели нет — она
одна на все ситуации. «Сетап» сделки есть ДОМИНИРУЮЩЕЕ СЕМЕЙСТВО
признаков в разложении вкладов ЭТОГО прогноза (`setup` в записи
выбора): чтение прогноза, а не исполненное правило. Это ограничение
меры, а не оговорка вежливости, и оно решает, как считать.

Три ловушки, названные ДО прогона, и защита от каждой
-------------------------------------------------------

1. ЯРЛЫК БОЛЬШИНСТВА. Семейство `book` доминирует почти в любом
   прогнозе (замер 2026-08-13: 61 % всех размеченных сделок). Такое
   семейство будет «устойчиво положительным» везде, где положительна
   сама книга, — и это скажет про книгу, а не про сетап. Поэтому мера
   не «сколько заработало семейство», а ПРЕВЫШЕНИЕ над своей же
   ячейкой: медиана семейства минус медиана ВСЕХ сделок той же книги и
   руки. Тот же приём, что одновременная кросс-секция в L3 и D1.

2. ОДНО РЕШЕНИЕ, ПОСЧИТАННОЕ СЕМЬ РАЗ. Книги ранжируют одно сечение
   одними весами: замер 2026-08-24 нашёл 5098 строк лиги на 3770
   различных решений, 78 % денег — на повторах, рекорд семь копий
   одного решения. Согласие «во всех книгах» у такого решения возникает
   по построению, а не потому, что сетап работает. Поэтому:
   а) ярлык берётся НА РЕШЕНИЕ (большинство копий, ничья по имени
      семейства) и разносится по всем копиям — иначе одно решение
      входило бы в разные семейства в разных книгах;
   б) главный нуль перемешивает ярлыки НА УРОВНЕ РЕШЕНИЙ, сохраняя
      структуру повторов целиком.

3. КОНЦЕНТРАЦИЯ. Деньги проекта не раз сидели в одном имени, и знак
   группы переворачивался его удалением. Поэтому у каждого семейства
   стоит столбец «без лучшего имени», и он входит в критерий.

Единицы. `net_bp` — нетто сделки в базисных пунктах ПОСЛЕ издержек
(круг 11 б.п. либо лесенка), то есть сравнение уже с учётом комиссии.
Деньги (`pnl`) зависят от размера позиции и правил кассы книги, и для
сравнения книг между собой не годятся; поэтому мера — б.п.

Что НЕ входит в вердикт и почему
--------------------------------
- Книги-эхо (`sit_r`, `h24b`, `h24bf`) — те же решения источника под
  другим правилом размера или выхода. Их включение утроило бы вес
  решений h24 и sit.
- Наблюдательная запись (`sit_obs`) — те же кандидаты, что у торгуемой
  ситуационной книги, но без гейта. Считается ОТДЕЛЬНЫМ блоком: она
  самая широкая выборка и потому полезна как проверка знака, но в
  меру «по всем книгам» входить не вправе — это не книга, а запись.

Пороги, объявленные ДО прогона
------------------------------
- ячейка (книга × рука × семейство) измерена при `n ≥ 30`;
- семейство измерено при `≥ 100` различных решений И присутствии
  минимум в `4` измеренных ячейках; иначе — НЕ ИЗМЕРЕНО, а не «ноль»;
- «устойчивый сетап» — все шесть условий разом:
  1. превышение медианы положительно в ≥ 2/3 измеренных ячеек,
  2. медиана нетто по решениям > 0,
  3. среднее нетто по решениям > 0,
  4. среднее > 0 и после удаления лучшего имени,
  5. взвешенное превышение выше 95-го процентиля НУЛЯ 2 (по
     максимуму среди семейств — поправка на то, что семейств
     семнадцать). Судится ВЕЛИЧИНА, а не доля ячеек: при полном
     дублировании решений между книгами доля насыщается — тот же
     набор решений под перемешанным ярлыком даёт согласие всех ячеек
     тоже. Найдено тестом на синтетике до прогона на живых данных,
  6. знак взвешенного превышения одинаков в обеих половинах истории.

Нули (оба с зерном, закреплённым ЧИСЛОМ — урок R3)
--------------------------------------------------
- НУЛЬ 2 (главный): перемешивание ярлыков между РЕШЕНИЯМИ. Структура
  повторов сохраняется целиком, рвётся только связь «ярлык ↔ исход».
- НУЛЬ 1 (диагностика): перемешивание внутри ячейки. Он НЕ сохраняет
  повторов, поэтому систематически мягче; разрыв между двумя нулями и
  есть цена дублирования решений, и её надо видеть числом.

Зонд вердикта по гипотезе не выносит и правил не предлагает: он
отвечает на один вопрос владельца и называет, чего его ответ не
означает.

Запуск на VPS (журналы книг живут там):
  cd ~/algoth_v2 && mkdir -p research/probe_setups/out
  cd ~/algoth_v2 && .venv/bin/python research/probe_setups/setups.py
"""

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))

# Торгуемые книги, входящие в меру. Карта та же, что у сервера;
# эхо-книги исключены намеренно (см. шапку).
BOOKS = (("h4", "model"), ("h24", "model_h24"), ("z", "model_h24z"),
         ("sit", "model_sit"), ("sit_lo", "model_sit_lo"))
ECHO = (("sit_r", "model_sit_r"), ("h24b", "model_h24b"),
        ("h24bf", "model_h24bf"))
OBS = ("sit_obs", "model_sit_obs")
ARMS = ("gbm", "nn")

MIN_CELL = 30            # сделок в ячейке, иначе ячейка не измерена
MIN_DEC = 100            # различных решений у семейства
MIN_CELLS = 4            # в скольких ячейках семейство обязано быть
STABLE_SHARE = 2.0 / 3   # доля ячеек с положительным превышением
PERMS = 1000
SEED = 20260824


def read_jsonl(path):
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


def median(xs):
    """Медиана с усреднением двух середин.

    На чётной длине брать верхнее из двух — это уже стоило странице
    неверного числа (`_median` в сборщике). Одно правило на проект.
    """
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def book_rows(mdir, hz):
    """Закрытые сделки книги — ядром `trades.py`, второй копии нет.

    Деньги штампует КАССА, а не разбор: `pnl` появляется у сделки
    только при пересчёте счёта. Лига однажды показывала ноль сделок
    ровно потому, что кассу не звала, — и собственный тест это
    пропустил, потому что положил `pnl` в фикстуру руками.
    """
    import trades as TR
    try:
        with open(os.path.join(mdir, "manifest.json"),
                  encoding="utf-8") as f:
            mman = json.load(f)
    except (OSError, ValueError):
        return [], None, None
    sit = bool(mman.get("situational"))
    hold = None if sit else int(mman.get("horizon_h") or TR.HOLD_H)
    tr = TR.build(read_jsonl(os.path.join(mdir, "picks.jsonl")),
                  read_jsonl(os.path.join(mdir, "review.jsonl")),
                  hold_h=hold,
                  books=TR.load_books(os.path.join(mdir, "books.jsonl")))
    real = {}
    for a in ARMS:
        TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                   slots=mman.get("slots"), sizing=mman.get("sizing"))
        real[a] = 0.0
    rows = []
    for t in tr:
        if t.get("state") != "закрыта" or t.get("pnl") is None:
            continue
        # У книги СО СРОКОМ события выхода нет вовсе (`exit_ts` пуст) —
        # первая версия зонда перелома фильтровала по нему и молча
        # теряла половину книг.
        ts = (t.get("exit_ts") or t.get("closes_at") or t.get("opened_at"))
        if not ts:
            continue
        arm = t.get("arm") or "gbm"
        real[arm] = real.get(arm, 0.0) + float(t["pnl"])
        su = t.get("setup") or []
        rows.append({
            "hz": hz, "arm": arm, "hour": t.get("hour"),
            "sym": t.get("sym"), "side": t.get("side"),
            "ts": float(ts), "net": float(t.get("net_bp") or 0.0),
            "pnl": float(t["pnl"]),
            # Ярлык КОПИИ. Ярлык решения считается отдельно и заменяет
            # его: одно решение не вправе входить в два семейства.
            "fam": (su[0][0] if su and su[0] else None),
            "share": (su[0][1] if su and su[0] else None),
            "reason": t.get("exit_reason")})
    return rows, mman, real


def account_check(mdir, real):
    """Встроенная сверка: мои деньги против счёта, писанного циклом.

    Счёт книги пересобирается циклом целиком (`rebuild_accounts`) и
    лежит на диске. `balance` — это `cash + busy`, то есть стартовый
    капитал плюс реализованное. Если мой обход журналов расходится с
    ним, я считаю не ту книгу — и об этом обязано быть сказано числом,
    а не выясняться потом.
    """
    out = {}
    for a in ARMS:
        try:
            with open(os.path.join(mdir, f"account_{a}.json"),
                      encoding="utf-8") as f:
                acc = json.load(f)
        except (OSError, ValueError):
            out[a] = None
            continue
        bal, start = acc.get("balance"), acc.get("start")
        if bal is None or start is None:
            out[a] = None
            continue
        out[a] = round(float(bal) - float(start) - real.get(a, 0.0), 2)
    return out


def decision_labels(rows):
    """Ярлык НА РЕШЕНИЕ: большинство копий, ничья — по имени семейства.

    Решение — это (имя, час, сторона). Книги ранжируют одно сечение, и
    у половины повторов ярлыки копий расходятся: у книг разные
    горизонты, а значит и разные вклады признаков. Оставить ярлык
    копии значило бы разнести одно решение по разным семействам и
    посчитать согласие там, где его нет.
    """
    votes = {}
    for r in rows:
        key = (r["sym"], r["hour"], r["side"])
        votes.setdefault(key, {})
        f = r["fam"]
        if f:
            votes[key][f] = votes[key].get(f, 0) + 1
    lab = {}
    for key, v in votes.items():
        lab[key] = (sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                    if v else None)
    return lab


def apply_labels(rows, lab):
    for r in rows:
        r["key"] = (r["sym"], r["hour"], r["side"])
        r["label"] = lab.get(r["key"])
    return rows


def decisions(rows):
    """Решения: нетто — СРЕДНЕЕ по копиям, не сумма.

    Сумма и есть нынешний счёт лиги, а брать лучшую копию значило бы
    выбирать исход задним числом.
    """
    agg = {}
    for r in rows:
        d = agg.setdefault(r["key"], {"nets": [], "pnl": 0.0,
                                      "sym": r["sym"], "ts": r["ts"],
                                      "label": r["label"],
                                      "side": r["side"]})
        d["nets"].append(r["net"])
        d["pnl"] += r["pnl"]
        d["ts"] = min(d["ts"], r["ts"])
    out = []
    for key, d in agg.items():
        out.append({"key": key, "sym": d["sym"], "side": d["side"],
                    "ts": d["ts"], "label": d["label"],
                    "copies": len(d["nets"]),
                    "net": sum(d["nets"]) / len(d["nets"]),
                    "pnl": d["pnl"]})
    out.sort(key=lambda d: d["ts"])
    return out


def cells(rows):
    """Ячейки (книга × рука) с базой: медиана и среднее ВСЕХ сделок."""
    out = {}
    for r in rows:
        out.setdefault((r["hz"], r["arm"]), []).append(r)
    return {k: {"rows": v, "med": median([x["net"] for x in v]),
                "mean": sum(x["net"] for x in v) / len(v), "n": len(v)}
            for k, v in out.items()}


def family_cells(cs, labels):
    """Превышение семейства над своей ячейкой, по каждой ячейке."""
    out = {}
    for f in labels:
        out[f] = {}
    for ck, c in cs.items():
        by = {}
        for r in c["rows"]:
            if r["label"]:
                by.setdefault(r["label"], []).append(r["net"])
        for f, nets in by.items():
            if len(nets) < MIN_CELL:
                continue
            out.setdefault(f, {})[ck] = {
                "n": len(nets),
                "med": median(nets), "mean": sum(nets) / len(nets),
                "exc_med": median(nets) - c["med"],
                "exc_mean": sum(nets) / len(nets) - c["mean"],
                "win": sum(1 for x in nets if x > 0) / len(nets)}
    return out


def stability(fc):
    """S1 — доля ячеек с положительным превышением; S2 — его величина."""
    out = {}
    for f, cellmap in fc.items():
        if not cellmap:
            continue
        pos = sum(1 for c in cellmap.values() if c["exc_med"] > 0)
        tot = sum(c["n"] for c in cellmap.values())
        s2 = sum(c["exc_med"] * c["n"] for c in cellmap.values()) / tot
        out[f] = {"cells": len(cellmap), "pos": pos,
                  "s1": pos / len(cellmap), "s2": s2, "n": tot}
    return out


def qualified(fc, decs):
    """Семейства, для которых мера вообще построена."""
    cnt = {}
    for d in decs:
        if d["label"]:
            cnt[d["label"]] = cnt.get(d["label"], 0) + 1
    return {f: cnt.get(f, 0) for f, cm in fc.items()
            if cnt.get(f, 0) >= MIN_DEC and len(cm) >= MIN_CELLS}


def null_decisions(rows, decs, qual, perms=PERMS, seed=SEED):
    """НУЛЬ 2: перемешать ярлыки между решениями, сохранив повторы.

    Ярлык переносится на ВСЕ копии решения — ровно так, как устроен
    сам замер. Поэтому нуль ломает только связь «ярлык ↔ исход»,
    оставляя нетронутыми и число копий, и состав ячеек.
    """
    keys = [d["key"] for d in decs]
    labs = [d["label"] for d in decs]
    rnd = random.Random(seed)
    base = [dict(r) for r in rows]
    m1, m2, per_fam = [], [], {f: [] for f in qual}
    for _ in range(perms):
        sh = labs[:]
        rnd.shuffle(sh)
        m = dict(zip(keys, sh))
        for r in base:
            r["label"] = m.get(r["key"])
        st = stability(family_cells(cells(base), qual))
        v1 = [st[f]["s1"] for f in qual if f in st]
        v2 = [st[f]["s2"] for f in qual if f in st]
        m1.append(max(v1) if v1 else 0.0)
        m2.append(max(v2) if v2 else 0.0)
        for f in qual:
            per_fam[f].append(st[f]["s2"] if f in st else 0.0)
    m1.sort()
    m2.sort()
    return {"bar": m1[int(0.95 * (len(m1) - 1))],
            "bar_s2": m2[int(0.95 * (len(m2) - 1))],
            "max_mean": sum(m1) / len(m1),
            "max_mean_s2": sum(m2) / len(m2),
            "per_fam": per_fam}


def null_incell(rows, qual, perms=200, seed=SEED + 1):
    """НУЛЬ 1 (диагностика): перемешивание внутри ячейки.

    Повторов решений он не сохраняет, поэтому систематически мягче.
    Разрыв с нулём 2 и есть цена дублирования решений между книгами —
    её надо видеть числом, а не предполагать.
    """
    rnd = random.Random(seed)
    by = {}
    for r in rows:
        by.setdefault((r["hz"], r["arm"]), []).append(r)
    maxes = []
    for _ in range(perms):
        base = []
        for ck, rs in by.items():
            labs = [r["label"] for r in rs]
            rnd.shuffle(labs)
            for r, l in zip(rs, labs):
                q = dict(r)
                q["label"] = l
                base.append(q)
        st = stability(family_cells(cells(base), qual))
        vals = [st[f]["s1"] for f in qual if f in st]
        maxes.append(max(vals) if vals else 0.0)
    maxes.sort()
    return {"bar": maxes[int(0.95 * (len(maxes) - 1))],
            "max_mean": sum(maxes) / len(maxes)}


def without_top(decs, fam):
    """Среднее нетто семейства без ЛУЧШЕГО имени.

    Колонка, которая уже переворачивала знак у четырёх групп лиги.
    """
    mine = [d for d in decs if d["label"] == fam]
    if not mine:
        return None, None
    by = {}
    for d in mine:
        by[d["sym"]] = by.get(d["sym"], 0.0) + d["net"]
    top = max(by.items(), key=lambda kv: kv[1])[0]
    rest = [d["net"] for d in mine if d["sym"] != top]
    return top, (sum(rest) / len(rest) if rest else None)


def halves(rows, qual):
    """Знак взвешенного превышения в обеих половинах истории.

    Половины режутся по МЕДИАНЕ времени закрытия, а не по календарю:
    иначе половина с редкими сделками не измеряет ничего.
    """
    ts = sorted(r["ts"] for r in rows)
    cut = ts[len(ts) // 2]
    out = {}
    for name, sel in (("early", [r for r in rows if r["ts"] < cut]),
                      ("late", [r for r in rows if r["ts"] >= cut])):
        st = stability(family_cells(cells(sel), qual))
        for f in qual:
            out.setdefault(f, {})[name] = (st[f]["s2"] if f in st else None)
    return out


def fam_title(f):
    try:
        import families as FAM
        g = FAM.GLOSSARY_BY_KEY.get(f) or {}
        return g.get("title_ru") or g.get("title") or f
    except Exception:                                     # noqa: BLE001
        return f


def analyse(rows):
    """Весь замер над уже загруженными строками — чистая функция."""
    lab = decision_labels(rows)
    rows = apply_labels(rows, lab)
    decs = decisions(rows)
    cs = cells(rows)
    all_fams = sorted({r["label"] for r in rows if r["label"]})
    fc = family_cells(cs, all_fams)
    st = stability(fc)
    qual = qualified(fc, decs)
    res = {}
    for f in sorted(qual, key=lambda x: -st[x]["s1"]):
        mine = [d["net"] for d in decs if d["label"] == f]
        top, wo = without_top(decs, f)
        res[f] = {"decisions": qual[f], "cells": st[f]["cells"],
                  "pos": st[f]["pos"], "s1": st[f]["s1"],
                  "s2": st[f]["s2"],
                  "med": median(mine), "mean": sum(mine) / len(mine),
                  "win": sum(1 for x in mine if x > 0) / len(mine),
                  "top_sym": top, "mean_wo_top": wo,
                  "cellmap": fc[f]}
    return {"rows": rows, "decs": decs, "cells": cs, "fams": all_fams,
            "stab": st, "qual": qual, "res": res, "fc": fc}


def verdict(res, n2, hv):
    """Шесть объявленных условий, каждое — отдельным флагом."""
    out = {}
    for f, r in res.items():
        h = hv.get(f, {})
        cond = {
            "s1": r["s1"] >= STABLE_SHARE,
            "med": (r["med"] or 0) > 0,
            "mean": r["mean"] > 0,
            "wo_top": (r["mean_wo_top"] is not None
                       and r["mean_wo_top"] > 0),
            # Судится ВЕЛИЧИНА превышения, а не доля ячеек: при
            # полном дублировании решений между книгами доля
            # насыщается — один и тот же набор решений даёт согласие
            # всех ячеек и у перемешанных ярлыков тоже. Найдено
            # тестом на синтетике ДО прогона на живых данных.
            "null": r["s2"] > n2["bar_s2"],
            "halves": (h.get("early") is not None
                       and h.get("late") is not None
                       and (h["early"] > 0) == (h["late"] > 0)
                       and h["early"] > 0)}
        out[f] = {"cond": cond, "stable": all(cond.values())}
    return out


def load(root, books):
    rows, checks = [], []
    for hz, name in books:
        mdir = os.path.join(root, name)
        rs, mman, real = book_rows(mdir, hz)
        if mman is None:
            checks.append({"book": name, "missing": True})
            continue
        checks.append({"book": name, "trades": len(rs),
                       "account_delta": account_check(mdir, real)})
        rows.extend(rs)
    return rows, checks


def fmt(x, nd=1):
    return "—" if x is None else f"{x:+.{nd}f}"


def write_report(path, data, meta):
    a, n2, n1, hv, vd = (data["a"], data["n2"], data["n1"],
                         data["hv"], data["vd"])
    res, decs, rows = a["res"], a["decs"], a["rows"]
    L = []
    L.append("# Зонд сетапов: что устойчиво по всем книгам и рукам\n")
    L.append(f"Прогон {meta['when']} · книги: "
             f"{', '.join(hz for hz, _ in BOOKS)} · "
             f"сделок {len(rows)} · решений {len(decs)}\n")
    L.append("**Что меряется.** «Сетап» сделки — доминирующее семейство "
             "признаков в разложении вкладов ЭТОГО прогноза, то есть "
             "ЧТЕНИЕ прогноза, а не выбранное правило. Мера — "
             "ПРЕВЫШЕНИЕ медианы нетто семейства над медианой ВСЕХ "
             "сделок той же книги и руки: без этого семейство "
             "большинства выглядело бы устойчивым везде, где "
             "положительна сама книга. Единица — базисные пункты нетто "
             "ПОСЛЕ издержек; деньги не годятся, у книг разный "
             "капитал и разные правила размера.\n")
    L.append("**Ярлык берётся на РЕШЕНИЕ** (имя, час, сторона), "
             "большинством копий: книги ранжируют одно сечение, и одно "
             "решение попадает в несколько книг. Нетто решения — "
             "среднее по копиям.\n")
    dup = sum(1 for d in decs if d["copies"] > 1)
    mx = max((d["copies"] for d in decs), default=0)
    lab = sum(1 for r in rows if r["label"])
    L.append(f"Повторов: решений с несколькими копиями {dup} из "
             f"{len(decs)} ({dup / max(1, len(decs)):.0%}), максимум "
             f"копий {mx}. Размечено сделок {lab} из {len(rows)} "
             f"({lab / max(1, len(rows)):.0%}); неразмеченные в "
             "семейства не идут — это пропуск, а не «прочее».\n")
    L.append("\n## Пороги (объявлены до прогона)\n")
    L.append(f"- ячейка измерена при n ≥ {MIN_CELL};\n"
             f"- семейство измерено при ≥ {MIN_DEC} решениях и ≥ "
             f"{MIN_CELLS} измеренных ячейках;\n"
             f"- устойчивый сетап — шесть условий разом: доля ячеек с "
             f"положительным превышением ≥ {STABLE_SHARE:.2f}; медиана "
             "и среднее нетто решений > 0; среднее > 0 и без лучшего "
             "имени; доля ячеек выше 95-го процентиля нуля 2; знак "
             "превышения одинаков в обеих половинах истории.\n")
    L.append("\n## Нули\n")
    L.append(f"- **нуль 2 (главный)** — перемешивание ярлыков между "
             f"решениями, {meta['perms']} перестановок, зерно {SEED}. "
             f"Планка по величине превышения (максимум среди "
             f"семейств): **{n2['bar_s2']:+.1f} б.п.** при среднем "
             f"максимуме {n2['max_mean_s2']:+.1f}. Планка по доле "
             f"ячеек — {n2['bar']:.2f}; она насыщается при "
             "дублировании решений и потому в критерий не входит;\n")
    L.append(f"- **нуль 1 (диагностика)** — перемешивание внутри "
             f"ячейки: планка {n1['bar']:.2f}. Он не сохраняет "
             "повторов решений между книгами и потому мягче; разрыв "
             "двух планок и есть цена дублирования.\n")
    L.append("\n## Семейства\n")
    L.append("| сетап | решений | ячеек | + | доля | превышение, б.п. | "
             "p | медиана | среднее | побед | без лучшего имени | "
             "устойчив |\n")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--|\n")
    for f, r in sorted(res.items(), key=lambda kv: -kv[1]["s1"]):
        v = vd[f]
        mark = "**да**" if v["stable"] else ", ".join(
            k for k, ok in v["cond"].items() if not ok)
        pf = n2["per_fam"].get(f) or []
        pv = ((sum(1 for x in pf if x >= r["s2"]) + 1) / (len(pf) + 1)
              if pf else None)
        L.append(f"| {f} | {r['decisions']} | {r['cells']} | {r['pos']} "
                 f"| {r['s1']:.2f} | {fmt(r['s2'])} | "
                 f"{'—' if pv is None else f'{pv:.3f}'} | "
                 f"{fmt(r['med'])} | "
                 f"{fmt(r['mean'])} | {r['win']:.2f} | "
                 f"{fmt(r['mean_wo_top'])} ({r['top_sym']}) | "
                 f"{mark} |\n")
    L.append("\n`p` — доля перестановок нуля 2, где у ЭТОГО семейства "
             "превышение вышло не меньше наблюдаемого (без поправки на "
             "число семейств; поправку несёт планка выше).\n")
    L.append("\nСтолбец «устойчив» перечисляет условия, которые НЕ "
             "выполнены: `s1` — согласие ячеек, `med`/`mean` — знак по "
             "решениям, `wo_top` — знак без лучшего имени, `null` — "
             "планка нуля, `halves` — половины истории.\n")
    L.append("\n## Превышение по ячейкам (медиана, б.п.)\n")
    cks = sorted(a["cells"])
    L.append("| сетап | " + " | ".join(f"{h}/{ar}" for h, ar in cks)
             + " |\n")
    L.append("|---" * (len(cks) + 1) + "|\n")
    for f, r in sorted(res.items(), key=lambda kv: -kv[1]["s1"]):
        cs = []
        for ck in cks:
            c = r["cellmap"].get(ck)
            cs.append("·" if not c else f"{c['exc_med']:+.0f}")
        L.append(f"| {f} | " + " | ".join(cs) + " |\n")
    L.append("\n«·» — ячейка не измерена (меньше "
             f"{MIN_CELL} сделок), это пропуск, а не ноль.\n")
    L.append("\n## Половины истории (взвешенное превышение, б.п.)\n")
    L.append("| сетап | ранняя | поздняя |\n|---|--:|--:|\n")
    for f in sorted(res, key=lambda x: -res[x]["s1"]):
        h = hv.get(f, {})
        L.append(f"| {f} | {fmt(h.get('early'))} | "
                 f"{fmt(h.get('late'))} |\n")
    if data.get("obs"):
        o = data["obs"]
        L.append("\n## Наблюдательная запись (не входит в вердикт)\n")
        L.append("Те же кандидаты, что у торгуемой ситуационной книги, "
                 "но без гейта — самая широкая выборка проекта. В меру "
                 "«по всем книгам» не входит: это запись, а не книга, и "
                 "её решения повторяют решения `sit`.\n\n")
        L.append("| сетап | сделок | медиана | среднее | побед |\n")
        L.append("|---|--:|--:|--:|--:|\n")
        for f, r in sorted(o.items(), key=lambda kv: -kv[1]["n"]):
            L.append(f"| {f} | {r['n']} | {fmt(r['med'])} | "
                     f"{fmt(r['mean'])} | {r['win']:.2f} |\n")
    L.append("\n## Сверка\n")
    L.append("Деньги обхода против счёта, писанного циклом "
             "(`balance − start`); расхождение обязано быть нулём.\n\n")
    L.append("| книга | сделок | Δ gbm, $ | Δ nn, $ |\n|---|--:|--:|--:|\n")
    for c in data["checks"]:
        if c.get("missing"):
            L.append(f"| {c['book']} | — | книги нет | |\n")
            continue
        d = c.get("account_delta") or {}
        L.append(f"| {c['book']} | {c['trades']} | "
                 f"{fmt(d.get('gbm'), 2)} | {fmt(d.get('nn'), 2)} |\n")
    L.append("\n## Чего этот замер НЕ означает\n")
    L.append("- Семейство — чтение вкладов, а не исполненная "
             "стратегия: модель одна на все ситуации и никогда не "
             "слышала «это зажим, делай так».\n")
    L.append("- Превышение считается над своей же книгой. Семейство с "
             "положительным превышением в убыточной книге всё равно "
             "теряет деньги — поэтому в критерий входит и знак "
             "самого нетто.\n")
    L.append("- История коротка, режим рынка один. Поверхность "
             "просмотрена ПОСЛЕ данных, поэтому выбрать лучшую строку "
             "и торговать её — ошибка R5; вердикт выносится только по "
             "объявленным условиям.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))


def obs_block(root):
    """Наблюдательная запись отдельным блоком — по копиям, без ячеек."""
    rows, _, _ = book_rows(os.path.join(root, OBS[1]), OBS[0])
    by = {}
    for r in rows:
        if r["fam"]:
            by.setdefault(r["fam"], []).append(r["net"])
    return {f: {"n": len(v), "med": median(v),
                "mean": sum(v) / len(v),
                "win": sum(1 for x in v if x > 0) / len(v)}
            for f, v in by.items() if len(v) >= MIN_CELL}


def publish(msg):
    sh = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                      "tools", "publish.sh")
    try:
        subprocess.run(["bash", sh, msg], check=False, timeout=300)
    except Exception as e:                                # noqa: BLE001
        print(f"публикация не прошла: {e}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(HERE), "s8_loop", "out"))
    ap.add_argument("--perms", type=int, default=PERMS)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args(argv)
    # Каталог артефактов создаётся ДО счёта: прогон, падающий на
    # последнем шаге, теряет всю работу — так уже вышло в турнире
    # политик и в зонде режимов.
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    print("читаю книги…", flush=True)
    rows, checks = load(args.root, BOOKS)
    if not rows:
        print("закрытых сделок нет — считать нечего", flush=True)
        return 1
    print(f"сделок {len(rows)}; считаю замер…", flush=True)
    a = analyse(rows)
    qual = a["qual"]
    if not qual:
        print("ни одно семейство не проходит порог измеримости",
              flush=True)
    hv = halves(a["rows"], qual)
    print(f"нуль 2: {args.perms} перестановок решений…", flush=True)
    n2 = null_decisions(a["rows"], a["decs"], qual, perms=args.perms)
    print("нуль 1: перемешивание внутри ячейки…", flush=True)
    n1 = null_incell(a["rows"], qual)
    vd = verdict(a["res"], n2, hv)
    try:
        obs = obs_block(args.root)
    except Exception as e:                                # noqa: BLE001
        print(f"наблюдательная запись не прочиталась: {e}", flush=True)
        obs = None
    tag = args.tag or "1m"
    path = os.path.join(out, f"SETUPS-report-{tag}.md")
    write_report(path, {"a": a, "n2": n2, "n1": n1, "hv": hv, "vd": vd,
                        "checks": checks, "obs": obs},
                 {"when": datetime.now(timezone.utc)
                  .strftime("%Y-%m-%d %H:%M UTC"),
                  "perms": args.perms})
    with open(os.path.join(out, f"setups-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"stab": {k: v for k, v in a["stab"].items()},
                   "qual": qual, "n2_bar": n2["bar"],
                   "n2_bar_s2": n2["bar_s2"], "n1_bar": n1["bar"],
                   "perms": args.perms,
                   "verdict": {k: v["stable"] for k, v in vd.items()},
                   "res": {k: {x: y for x, y in v.items()
                               if x != "cellmap"}
                           for k, v in a["res"].items()},
                   "checks": checks}, f, ensure_ascii=False)
    stable = [f for f, v in vd.items() if v["stable"]]
    print(f"отчёт: {path}", flush=True)
    print("устойчивых сетапов: "
          + (", ".join(stable) if stable else "ни одного"), flush=True)
    if not args.no_publish:
        publish("зонд сетапов: устойчивость по книгам и рукам")
    return 0


if __name__ == "__main__":
    sys.exit(main())
