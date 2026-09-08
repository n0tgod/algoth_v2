#!/usr/bin/env python3
"""
Проверки механики 12cc2578 — «вторая цель в листе сечения».

Проверяется то, где ошибка была бы НЕВИДИМОЙ: прогон не падает, отчёт
выглядит исправным, а книга торгует не тот горизонт, о котором вынесен
вердикт. Механика вся про это, и каждая проверка ниже названа тем, что
она ловит:

* **лист прежнего образца читается как «цели нет», а не как ноль** —
  строка без полей 24 ч не превращается в ногу с четырёхчасовым стопом.
  Молчаливая подстановка соседнего горизонта дала бы книгу, которая
  выглядит торгующей 24 ч, а торгует 4 ч;
* **исполнимость решает СОДЕРЖИМОЕ листа**, а не константа: и знаменатель
  испытаний, и жребий контрольной руки обязаны вырасти в тот же прогон,
  в который цикл начал писать вторую цель;
* **`id` ноги различает горизонт** — одна строка листа порождает две
  ноги, и общий `id` затёр бы исход одной другим (кэш `outcomes_for`
  ключуется именно им);
* **подмена горизонта меняет состав ног** — иначе ось `target` не решает
  ничего, а проверка этого не видит;
* **калибровочная пара**: подсаженный горизонт (24 ч — зеркало 4 ч)
  обязан найтись сторонами всех сделок, а на КОПИИ полей две дороги
  чтения обязаны дать одни и те же ноги. Без второй половины сломанное
  чтение строки неотличимо от «горизонт ничего не меняет»;
* **заглядывания в будущее нет** — дописанные позже листы не двигают ни
  одной ноги прошлого;
* **пустота не выдаёт себя за результат** — цель в листе есть, а ног
  ноль: это поломка чтения, и она названа числом строк;
* **наша дыра не становится вердиктом о кандидате** — книгу, которую
  нечем реплеить, правило вылета не судит;
* **вердиктовая фраза выведена из чисел**, а не стоит рядом с ними.

Запуск: `.venv/bin/python research/mech_12cc2578/test_horizon.py`.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
FACTORY = os.path.join(RESEARCH, "factory")
for _p in (FACTORY, os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import candidate as CD                                      # noqa: E402
import horizon as HZ                                        # noqa: E402
import ledger as LG                                         # noqa: E402
import pool as PL                                           # noqa: E402
import run_day as RD                                        # noqa: E402
import space as SP                                          # noqa: E402

FAILED = []
H = 3600.0
DAY = 86400.0
T0 = 1_780_000_000


def check(name, ok, got=""):
    print(("  ok   " if ok else "  ПРОВАЛ ") + name
          + ("" if ok else f" — {got}"))
    if not ok:
        FAILED.append(name)


# --- сырьё: лист сечения того же образца, что пишет цикл --------------
#
# Поля 4 ч — `fwd`, `fwd_z`, `mae`, `mfe` плюс квантильные концы;
# поля 24 ч — `fwd_24h`, `fwd_24h_z`, `mae_24h`, `mfe_24h` и НИКАКИХ
# квантилей: цикл их на 24 ч не учит, и подставной артефакт обязан
# выглядеть как живой, иначе проверка исполняет другую дорогу.
# `mae`/`mfe` — ходы ЦЕНЫ (минимум и максимум), а не позиции: сторону
# из них выводит `trades.position_path` по знаку прогноза.

def row(sym, fwd, fwd24=None, q=True, mae=-40.0, mfe=120.0,
        mae24=-80.0, mfe24=240.0, maeq=None):
    r = {"sym": sym, "px": 100.0, "beta": 1.0,
         "fwd": fwd, "fwd_z": fwd / 30.0, "mae": mae, "mfe": mfe}
    if q:
        r["mae_q"] = mae * 1.25 if maeq is None else maeq
        r["mfe_q"] = mfe
    if fwd24 is not None:
        r["fwd_24h"] = fwd24
        r["fwd_24h_z"] = fwd24 / 30.0
        r["mae_24h"] = mae24
        r["mfe_24h"] = mfe24
    return r


def write_sheet(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def rec_at(h, rows, arms=("gbm", "nn")):
    return {"hour": "2026-08-31-%02d" % h, "written_at": T0 + h * H,
            "arms": {a: rows for a in arms}}


def sheet(tmp, hours=4, with24=True, mirror=True, name="sheets.jsonl"):
    """Журнал листов. `mirror` — цель 24 ч зеркалит 4 ч (подсадка)."""
    recs = []
    for h in range(hours):
        rows = []
        for i in range(6):
            fwd = (60.0 + 5 * i) * (1 if i % 2 == 0 else -1)
            f24 = None
            if with24:
                f24 = -fwd if mirror else fwd
            rows.append(row(f"C{i}USDT", fwd, f24))
        recs.append(rec_at(h, rows))
    return write_sheet(os.path.join(tmp, name), recs)


def rule(**kw):
    r = {"target": "fwd_4h", "rank": "raw", "floor_bp": 0, "width": 3,
         "geom": "timer", "rr_band": "none", "sizing": "equal",
         "basket": "no", "agree": "no"}
    r.update(kw)
    return r


def outs_for(legs, move=100.0):
    g = CD.with_geometry(rule())
    return {(lg["id"], g["_stop"], g["_take"], g["_age"]):
            ("срок", move, lg["at"] + 4 * H, 100.0) for lg in legs}


def caps24(z=True, q=False, rows=12, records=4):
    """Разбор листа, несущего обе цели, — руками, без чтения файла."""
    return {"path": "—", "records": records, "at": T0, "hour": "h",
            "recent": {"fwd_4h": records, "fwd_24h": records},
            "targets": {"fwd_4h": {"rows": rows, "z": True, "q": True},
                        "fwd_24h": {"rows": rows, "z": z, "q": q}},
            "why": None}


# --- что лист несёт ---------------------------------------------------

def test_sheet_caps_reads_content_not_constant():
    tmp = tempfile.mkdtemp()
    old = sheet(tmp, with24=False, name="old.jsonl")
    new = sheet(tmp, with24=True, name="new.jsonl")
    c_old = HZ.sheet_caps(old)
    c_new = HZ.sheet_caps(new)
    check("лист прежнего образца несёт одну цель",
          sorted(c_old["targets"]) == ["fwd_4h"], str(sorted(c_old["targets"])))
    check("лист с обеими целями несёт обе",
          sorted(c_new["targets"]) == ["fwd_24h", "fwd_4h"],
          str(sorted(c_new["targets"])))
    # Числа, а не «есть блок»: строк в свежем листе и листов из
    # прочитанных. «Блок есть» проходило в этом проекте на пустом блоке.
    t4, t24 = c_new["targets"]["fwd_4h"], c_new["targets"]["fwd_24h"]
    check("строки цели посчитаны числом",
          t4["rows"] == 12 and t24["rows"] == 12,
          f"{t4['rows']}/{t24['rows']}")
    check("порядок в σ у обеих целей найден", t4["z"] and t24["z"],
          f"{t4['z']}/{t24['z']}")
    # Квантильных концов на 24 ч нет — и это ЧИТАЕТСЯ, а не назначается.
    check("квантильные концы: у 4 ч есть, у 24 ч нет",
          t4["q"] and not t24["q"], f"{t4['q']}/{t24['q']}")
    check("листов с целью посчитано",
          c_new["recent"] == {"fwd_4h": 4, "fwd_24h": 4},
          str(c_new["recent"]))
    check("момент и час свежего листа названы",
          c_new["at"] == T0 + 3 * H and c_new["hour"] == "2026-08-31-03",
          f"{c_new['at']}/{c_new['hour']}")
    # Пустота обязана быть объяснена: «журнала нет» и «в журнале нет
    # целей» лечатся по-разному, а молчаливый пустой словарь означал бы
    # «лист не несёт ничего».
    gone = HZ.sheet_caps(os.path.join(tmp, "нет-такого.jsonl"))
    check("отсутствующий журнал назван причиной, а не пустотой",
          not gone["targets"] and gone["why"] and "нет" in gone["why"],
          str(gone["why"]))
    empty = write_sheet(os.path.join(tmp, "empty.jsonl"), [])
    check("пустой журнал назван причиной",
          bool(HZ.sheet_caps(empty)["why"]), str(HZ.sheet_caps(empty)))


def test_caps_read_the_tail_not_the_head():
    """Отвечает СВЕЖИЙ лист: цель, появившаяся час назад, исполнима, а
    пропавшая час назад — нет, и оба случая надо видеть."""
    tmp = tempfile.mkdtemp()
    recs = [rec_at(0, [row("AAA", 70.0, -70.0)]),
            rec_at(1, [row("AAA", 70.0, -70.0)]),
            rec_at(2, [row("AAA", 70.0)])]          # поля 24 ч пропали
    p = write_sheet(os.path.join(tmp, "s.jsonl"), recs)
    c = HZ.sheet_caps(p)
    check("пропавшая цель в свежем листе не значится",
          sorted(c["targets"]) == ["fwd_4h"], str(sorted(c["targets"])))
    check("но её след в прочитанных листах виден числом",
          c["recent"].get("fwd_24h") == 2, str(c["recent"]))
    recs2 = [rec_at(0, [row("AAA", 70.0)]),
             rec_at(1, [row("AAA", 70.0)]),
             rec_at(2, [row("AAA", 70.0, -70.0)])]  # поля 24 ч пришли
    p2 = write_sheet(os.path.join(tmp, "s2.jsonl"), recs2)
    c2 = HZ.sheet_caps(p2)
    check("пришедшая цель исполнима с того же прогона",
          sorted(c2["targets"]) == ["fwd_24h", "fwd_4h"],
          str(sorted(c2["targets"])))
    check("листов с ней — одна из трёх",
          c2["recent"].get("fwd_24h") == 1, str(c2["recent"]))


def test_report_phrase_comes_from_the_numbers():
    """Фраза о листе ВЫВОДИТСЯ из чисел, а не стоит рядом литералом."""
    a = HZ.phrase(caps24(rows=12))
    b = HZ.phrase(caps24(rows=700))
    check("в фразе стоят числа своего разбора",
          "12" in a and "700" in b and a != b, f"{a} || {b}")
    check("отсутствие квантилей сказано словами",
          "квантильные концы НЕТ" in a, a)
    none = HZ.phrase({"targets": {}, "why": "журнала листов нет"})
    check("пустой разбор объясняет себя причиной",
          "не несёт ни одной цели" in none and "журнала листов нет" in none,
          none)


# --- ноги -------------------------------------------------------------

def test_old_sheet_is_refused_aloud_not_replayed_as_4h():
    """Лист без полей 24 ч — «цели нет», а не молчаливый реплей на 4 ч."""
    tmp = tempfile.mkdtemp()
    p = sheet(tmp, with24=False)
    caps = HZ.sheet_caps(p)
    r24 = rule(target="fwd_24h")
    why = SP.unavailable(r24, caps)
    check("отказ назван словами и назвал цель",
          bool(why) and "лист" in why and "fwd_24h" in why, str(why))
    stats = {}
    legs = HZ.legs_from_sheets([p], caps=caps, log=lambda *a: None,
                               stats=stats)
    n24 = sum(1 for g in legs if HZ.leg_target(g) == "fwd_24h")
    check("ног 24 ч из такого листа не выходит вовсе",
          n24 == 0 and stats.get("fwd_24h") is None, f"{n24} {stats}")
    check("ноги 4 ч при этом есть", stats.get("fwd_4h", 0) > 0, str(stats))
    outs = outs_for(legs)
    tr24 = CD.simulate(legs, outs, CD.with_geometry(r24))
    tr4 = CD.simulate(legs, outs, CD.with_geometry(rule()))
    # Главное: пустота книги 24 ч есть ОТСУТСТВИЕ ЦЕЛИ, а не поломка
    # машинерии — та же машинерия на 4 ч торгует.
    check("книга 24 ч не торгует четырёхчасовыми ногами",
          tr24 == [], f"{len(tr24)} сделок")
    check("книга 4 ч на том же листе торгует", len(tr4) > 0, str(len(tr4)))


def test_horizon_changes_the_leg_set():
    """Подмена горизонта обязана менять СОСТАВ ног, иначе ось не решает
    ничего, а проверка этого не видит."""
    tmp = tempfile.mkdtemp()
    p = sheet(tmp, with24=True, mirror=True)
    caps = HZ.sheet_caps(p)
    legs = HZ.legs_from_sheets([p], caps=caps, log=lambda *a: None)
    by = {}
    for g in legs:
        by.setdefault(HZ.leg_target(g), []).append(g)
    check("обе цели дали ноги",
          len(by.get("fwd_4h", [])) > 0 and len(by.get("fwd_24h", [])) > 0,
          str({k: len(v) for k, v in by.items()}))
    s4 = {(g["sym"], g["at"], g["arm"]): g["side"] for g in by["fwd_4h"]}
    s24 = {(g["sym"], g["at"], g["arm"]): g["side"] for g in by["fwd_24h"]}
    check("состав имён тот же, а стороны противоположны",
          set(s4) == set(s24) and all(s4[k] != s24[k] for k in s4),
          str(list(s4.items())[:2]) + str(list(s24.items())[:2]))
    outs = outs_for(legs)
    tr4 = CD.simulate(legs, outs, CD.with_geometry(rule()))
    tr24 = CD.simulate(legs, outs, CD.with_geometry(rule(
        target="fwd_24h")))
    k4 = {(t["sym"], t["at"], t["side"]) for t in tr4}
    k24 = {(t["sym"], t["at"], t["side"]) for t in tr24}
    check("книги двух горизонтов торгуют разное",
          bool(k4) and bool(k24) and not (k4 & k24),
          f"{len(k4)}/{len(k24)}/{len(k4 & k24)}")
    check("прогноз ноги взят из полей СВОЕЙ цели",
          all(abs(g["fwd"] + h["fwd"]) < 1e-9
              for g, h in zip(sorted(by["fwd_4h"], key=lambda x: (x["at"], x["arm"], x["sym"])),
                              sorted(by["fwd_24h"], key=lambda x: (x["at"], x["arm"], x["sym"])))),
          "прогноз 24 ч не зеркалит четырёхчасовой")


def test_ids_distinguish_horizon():
    """Одна строка листа — две ноги, и `id` у них разные.

    `id` есть ключ кэша исходов: общий на две ноги затёр бы исход одной
    другим, и книга торговала бы чужой форвард.
    """
    tmp = tempfile.mkdtemp()
    p = write_sheet(os.path.join(tmp, "s.jsonl"),
                    [rec_at(0, [row("AAA", 70.0, -70.0)], arms=("gbm",))])
    caps = HZ.sheet_caps(p)
    legs = HZ.legs_from_sheets([p], caps=caps, log=lambda *a: None)
    check("одна строка дала две ноги", len(legs) == 2, str(len(legs)))
    check("горизонты у них разные",
          {HZ.leg_target(g) for g in legs} == {"fwd_4h", "fwd_24h"},
          str([HZ.leg_target(g) for g in legs]))
    ids = [g["id"] for g in legs]
    check("id различает горизонт", len(set(ids)) == len(ids), str(ids))
    # И кэш исходов их не путает: разный исход у каждой ноги.
    g = CD.with_geometry(rule())
    outs = {}
    for lg in legs:
        move = 500.0 if HZ.leg_target(lg) == "fwd_4h" else -500.0
        outs[(lg["id"], g["_stop"], g["_take"], g["_age"])] = (
            "срок", move, lg["at"] + 4 * H, 100.0)
    tr4 = CD.simulate(legs, outs, CD.with_geometry(rule()))
    tr24 = CD.simulate(legs, outs, CD.with_geometry(rule(
        target="fwd_24h")))
    check("каждая книга получила СВОЙ исход",
          len(tr4) == 1 and len(tr24) == 1
          and tr4[0]["net"] > 0 and tr24[0]["net"] > 0,
          f"{tr4}/{tr24}")


def test_quantile_fields_do_not_leak_across_horizons():
    """Чужие поля пути в ногу не протекают.

    Квантильных концов на 24 ч нет; протеки в неё четырёхчасовой
    `mae_q`, и стоп 24-часовой ноги встал бы на уровень другого
    горизонта — книга выглядела бы 24-часовой, а рисковала бы по 4 ч.
    Квантиль здесь нарочно ДАЛЬШЕ средней линии 24 ч: `wider_stop`
    берёт дальний, значит протечка была бы видна числом.
    """
    tmp = tempfile.mkdtemp()
    r = row("AAA", 70.0, 70.0, maeq=-500.0, mae24=-80.0, mfe24=240.0)
    p = write_sheet(os.path.join(tmp, "s.jsonl"),
                    [rec_at(0, [r], arms=("gbm",))])
    legs = HZ.legs_from_sheets([p], caps=HZ.sheet_caps(p),
                               log=lambda *a: None)
    by = {HZ.leg_target(g): g for g in legs}
    check("обе ноги на месте", set(by) == {"fwd_4h", "fwd_24h"}, str(set(by)))
    check("нога 4 ч стоит на СВОЁМ квантильном стопе",
          abs(by["fwd_4h"]["adv_q"] + 500.0) < 1e-9,
          str(by["fwd_4h"]["adv_q"]))
    check("нога 24 ч стоит на своей линии, а не на квантиле 4 ч",
          abs(by["fwd_24h"]["adv_q"] + 80.0) < 1e-9,
          str(by["fwd_24h"]["adv_q"]))
    check("и отношение у неё посчитано своими концами",
          abs((by["fwd_24h"]["rr"] or 0) - 3.0) < 1e-9,
          str(by["fwd_24h"]["rr"]))


def test_calibration_planted_and_copy():
    """Калибровочная пара.

    Подсадка: цель 24 ч — зеркало 4 ч, и это обязано найтись сторонами
    ВСЕХ сделок. Шум: поля 24 ч — дословная копия четырёхчасовых, и две
    дороги чтения обязаны дать одни и те же ноги. Без второй половины
    сломанное чтение строки неотличимо от «горизонт ничего не меняет».
    """
    tmp = tempfile.mkdtemp()
    # --- половина 1: подсаженное зеркало
    p = sheet(tmp, with24=True, mirror=True, name="mirror.jsonl")
    legs = HZ.legs_from_sheets([p], caps=HZ.sheet_caps(p),
                               log=lambda *a: None)
    pairs = {}
    for g in legs:
        pairs.setdefault((g["at"], g["arm"], g["sym"]), {})[
            HZ.leg_target(g)] = g
    both = [v for v in pairs.values() if len(v) == 2]
    check("подсадка нашлась: стороны зеркальны у всех пар",
          len(both) > 0 and all(v["fwd_4h"]["side"] != v["fwd_24h"]["side"]
                                for v in both), str(len(both)))
    # --- половина 2: копия. Ноги обязаны совпасть ВСЕМИ полями, кроме
    # `id` и `target`: два читателя одного журнала не вправе разойтись.
    recs = []
    for h in range(3):
        rows = []
        for i in range(4):
            fwd = (60.0 + 7 * i) * (1 if i % 2 == 0 else -1)
            rows.append(row(f"C{i}USDT", fwd, fwd, q=False,
                            mae24=-40.0, mfe24=120.0))
        recs.append(rec_at(h, rows))
    p2 = write_sheet(os.path.join(tmp, "copy.jsonl"), recs)
    legs2 = HZ.legs_from_sheets([p2], caps=HZ.sheet_caps(p2),
                                log=lambda *a: None)
    a = sorted((g for g in legs2 if HZ.leg_target(g) == "fwd_4h"),
               key=lambda x: (x["at"], x["arm"], x["sym"]))
    b = sorted((g for g in legs2 if HZ.leg_target(g) == "fwd_24h"),
               key=lambda x: (x["at"], x["arm"], x["sym"]))
    check("копия дала столько же ног", len(a) == len(b) and len(a) > 0,
          f"{len(a)}/{len(b)}")
    diff = []
    for x, y in zip(a, b):
        for k in set(x) | set(y):
            if k in ("id", "target"):
                continue
            if x.get(k) != y.get(k):
                diff.append((k, x.get(k), y.get(k)))
    check("на копии полей две дороги чтения дали ОДНИ И ТЕ ЖЕ ноги",
          not diff, str(diff[:3]))


def test_no_lookahead_future_does_not_move_the_past():
    """Переписанное будущее не двигает ни одной ноги прошлого."""
    tmp = tempfile.mkdtemp()
    past = [rec_at(h, [row(f"C{i}USDT", 60.0 + 5 * i)
                       for i in range(4)]) for h in range(3)]
    p = write_sheet(os.path.join(tmp, "past.jsonl"), past)
    before = HZ.legs_from_sheets([p], caps=HZ.sheet_caps(p),
                                 log=lambda *a: None)
    future = past + [rec_at(h, [row(f"C{i}USDT", -900.0 - i, 900.0 + i)
                                for i in range(4)]) for h in (3, 4)]
    p2 = write_sheet(os.path.join(tmp, "future.jsonl"), future)
    after = HZ.legs_from_sheets([p2], caps=HZ.sheet_caps(p2),
                                log=lambda *a: None)
    old_at = max(g["at"] for g in before)
    kept = [g for g in after if g["at"] <= old_at]
    key = lambda g: (g["at"], g["arm"], g["sym"], HZ.leg_target(g))  # noqa: E731
    a = sorted(before, key=key)
    b = sorted(kept, key=key)
    check("ног прошлого столько же", len(a) == len(b), f"{len(a)}/{len(b)}")
    diff = [(k, x.get(k), y.get(k)) for x, y in zip(a, b)
            for k in set(x) | set(y) if k != "id" and x.get(k) != y.get(k)]
    check("ни одно поле прошлой ноги не шелохнулось", not diff,
          str(diff[:3]))
    check("будущее при этом дало свои ноги 24 ч",
          any(HZ.leg_target(g) == "fwd_24h" for g in after), "нет ног 24 ч")


def test_supply_gap_is_a_refusal_not_a_dash():
    """Цель в листе есть, а ног ноль — поломка чтения, а не тихий рынок."""
    caps = caps24(rows=120)
    why = HZ.supply_gap(caps, {"fwd_4h": 500, "fwd_24h": 0})
    check("ноль ног при непустом листе — отказ с числом",
          bool(why) and "120" in why and "fwd_24h" in why, str(why))
    check("ноги есть — отказа нет",
          HZ.supply_gap(caps, {"fwd_4h": 500, "fwd_24h": 7}) is None)
    check("цели в листе нет — и спрашивать не с чего",
          HZ.supply_gap({"targets": {}}, {}) is None)


# --- исполнимость -----------------------------------------------------

def test_quantile_geometry_is_refused_on_24h():
    """Стоп и тейк на 24 ч реплеить нечем, и это сказано словами."""
    caps = caps24()
    for geom in ("stop_take", "levels"):
        why = SP.unavailable(rule(target="fwd_24h", geom=geom), caps)
        check(f"геометрия {geom} на 24 ч отвергнута",
              bool(why) and "квантильн" in why, str(why))
    check("выход по времени на 24 ч исполним",
          SP.unavailable(rule(target="fwd_24h", geom="timer"), caps) is None,
          str(SP.unavailable(rule(target="fwd_24h"), caps)))
    check("на 4 ч квантили есть, и геометрия со стопом исполнима",
          SP.unavailable(rule(geom="stop_take"), caps) is None,
          str(SP.unavailable(rule(geom="stop_take"), caps)))


def test_risk_sizing_is_refused_on_24h():
    """Равный риск считается от ИСПОЛНЯЕМОГО стопа, которого на 24 ч нет."""
    caps = caps24()
    why = SP.unavailable(rule(target="fwd_24h", sizing="risk"), caps)
    check("равный риск на 24 ч отвергнут",
          bool(why) and "риск" in why, str(why))
    check("равный доллар на 24 ч исполним",
          SP.unavailable(rule(target="fwd_24h", sizing="equal"),
                         caps) is None)
    check("обратно σ на 24 ч исполним (поле σ в листе есть)",
          SP.unavailable(rule(target="fwd_24h", sizing="inv_sigma"),
                         caps) is None)
    check("на 4 ч равный риск исполним",
          SP.unavailable(rule(sizing="risk"), caps) is None)


def test_sigma_rank_needs_the_z_field():
    """Порядок в σ требует поля прогноза в единицах σ у ЭТОЙ цели."""
    no_z = caps24(z=False)
    why = SP.unavailable(rule(target="fwd_24h", rank="sigma"), no_z)
    check("без поля σ порядок в σ отвергнут",
          bool(why) and "σ" in why, str(why))
    check("и размер обратно σ тоже",
          bool(SP.unavailable(rule(target="fwd_24h", sizing="inv_sigma"),
                              no_z)))
    check("с полем σ обе оси исполнимы",
          SP.unavailable(rule(target="fwd_24h", rank="sigma"),
                         caps24()) is None)


def test_available_total_counts_content_not_the_constant():
    """Знаменатель исполнимого растёт в тот же прогон, что и лист."""
    base = SP.available_total()
    check("по объявленному образцу исполнима прежняя четверть",
          base == 1296, str(base))
    got = SP.available_total(caps24())
    extra = [SP.index_to_rule(i) for i in range(SP.TOTAL)
             if SP.unavailable(SP.index_to_rule(i), caps24()) is None
             and SP.unavailable(SP.index_to_rule(i)) is not None]
    check("с содержимым листа исполнимого больше", got > base,
          f"{got} против {base}")
    check("прибавка сходится с перечнем", got - base == len(extra),
          f"{got - base} против {len(extra)}")
    check("прибавка — только цель 24 ч, только выход по времени и не "
          "равным риском",
          all(r["target"] == "fwd_24h" and r["geom"] == "timer"
              and r["sizing"] != "risk" and r["basket"] == "no"
              for r in extra), str(extra[:1]))
    # Отказ по объявленному образцу обязан СКАЗАТЬ, что содержимое не
    # читали: иначе «в листе этого нет» и «мы не смотрели» неотличимы.
    why = SP.unavailable(rule(target="fwd_24h"))
    check("отказ по умолчанию признаётся, что лист не читался",
          bool(why) and "образцу" in why, str(why))


def test_draw_reaches_the_second_horizon():
    """Жребий тянет из того же исполнимого, что и отобранные."""
    caps = caps24()
    with_caps = SP.draw(4242, 40, caps=caps)
    default = SP.draw(4242, 40)
    check("по объявленному образцу 24 ч не выпадает",
          not any(r["target"] == "fwd_24h" for r in default))
    check("по содержимому листа 24 ч выпадает",
          any(r["target"] == "fwd_24h" for r in with_caps),
          str([SP.key(r) for r in with_caps[:3]]))
    check("жребий тянет только исполнимое",
          all(SP.unavailable(r, caps) is None for r in with_caps))


# --- книга ------------------------------------------------------------

def test_book_takes_only_its_own_horizon():
    """Нога без поля цели — базовая: она читала её поля."""
    legacy = [{"id": 0, "arm": "gbm", "sym": "AAA", "hour": "h",
               "at": float(T0), "side": "long", "fwd": 70.0, "px": 100.0,
               "fz": 2.0, "adv_q": -40.0, "adv_m": -40.0, "fav": 120.0,
               "rr": 3.0}]
    check("нога без поля горизонта считается базовой",
          HZ.leg_target(legacy[0]) == "fwd_4h", HZ.leg_target(legacy[0]))
    outs = outs_for(legacy)
    check("книга 4 ч её берёт",
          len(CD.simulate(legacy, outs, CD.with_geometry(rule()))) == 1)
    check("книга 24 ч её НЕ берёт",
          CD.simulate(legacy, outs,
                      CD.with_geometry(rule(target="fwd_24h"))) == [],
          "четырёхчасовая нога попала в книгу 24 ч")


def test_agreement_is_within_one_horizon():
    """Согласие рук есть свойство ОДНОГО прогноза.

    Рука `gbm` на 4 ч и рука `nn` на 24 ч, попавшие в одно имя, — не
    согласие двух рук, а совпадение двух разных вопросов.
    """
    def lg(i, arm, target, sym="AAA"):
        return {"id": i, "arm": arm, "sym": sym, "hour": "h",
                "at": float(T0), "side": "long", "fwd": 70.0, "px": 100.0,
                "fz": 2.0, "adv_q": -40.0, "adv_m": -40.0, "fav": 120.0,
                "rr": 3.0, "target": target}
    legs = [lg(0, "gbm", "fwd_4h"), lg(1, "nn", "fwd_24h")]
    outs = outs_for(legs)
    tr4 = CD.simulate(legs, outs, CD.with_geometry(rule(agree="yes")))
    tr24 = CD.simulate(legs, outs, CD.with_geometry(
        rule(target="fwd_24h", agree="yes")))
    check("согласие через горизонт не засчитывается",
          tr4 == [] and tr24 == [], f"{tr4}/{tr24}")
    legs2 = legs + [lg(2, "nn", "fwd_4h")]
    tr = CD.simulate(legs2, outs_for(legs2),
                     CD.with_geometry(rule(agree="yes")))
    check("согласие внутри одного горизонта засчитывается",
          len(tr) == 2, str(len(tr)))


def test_null_permutes_within_the_horizon():
    """Нуль переставляет исходы внутри часа, руки И горизонта.

    Исход 24-часовой ноги, попавший на четырёхчасовую, есть не другой
    нуль, а другая книга: сторона там определена другим прогнозом.
    """
    def lg(i, target, sym):
        return {"id": i, "arm": "gbm", "sym": sym, "hour": "h",
                "at": float(T0), "side": "long", "fwd": 70.0, "px": 100.0,
                "fz": 2.0, "adv_q": -40.0, "adv_m": -40.0, "fav": 120.0,
                "rr": 3.0, "target": target}
    legs = ([lg(i, "fwd_4h", f"A{i}") for i in range(4)]
            + [lg(4 + i, "fwd_24h", f"B{i}") for i in range(4)])
    g = CD.with_geometry(rule())
    outs = {}
    for l_ in legs:
        move = 500.0 if l_["target"] == "fwd_4h" else -500.0
        outs[(l_["id"], g["_stop"], g["_take"], g["_age"])] = (
            "срок", move, l_["at"] + 4 * H, 100.0)
    nulls = RD.null_daily(legs, outs, rule(width=10), seeds=5)
    vals = sorted({round(v, 3) for d in nulls for v in d.values()})
    check("нуль книги 4 ч остаётся книгой 4 ч",
          vals == [round(500.0 - 11.0, 3)], str(vals))


# --- суточный прогон --------------------------------------------------

def fake_bars(sym_up=("C0USDT",)):
    def read(root, sym, a, b):
        out, t = [], int(a // 60) * 60
        i = 0
        while t <= b:
            drift = 1.0 + 0.00004 * i * (1 if sym in sym_up else -1)
            p = 100.0 * drift
            out.append((float(t), p, p * 1.004, p * 0.996, p))
            t += 60
            i += 1
        return out
    return read


def run_day_on(tmp, sheets, extra_declare=(), argv=()):
    """Суточный прогон на синтетике, с подменёнными барами и публикацией."""
    base = os.path.join(tmp, "ledger")
    out = os.path.join(tmp, "out")
    os.makedirs(base, exist_ok=True)
    for cid, rec in extra_declare:
        LG.declare(cid, rec["rule"], rec.get("lane", "selected"),
                   at=rec.get("at"), base=base, source="test")
    was_b, was_pub = RD.SW.read_bars, RD.publish
    RD.SW.read_bars = fake_bars()
    RD.publish = lambda *a, **k: None
    try:
        rc = RD.main(["--sheets", sheets, "--root", tmp, "--out", out,
                      "--base", base, "--tag", "t", "--seed", "42",
                      "--no-declare", "--no-publish"] + list(argv))
    finally:
        RD.SW.read_bars, RD.publish = was_b, was_pub
    md = ""
    path = os.path.join(out, "FACTORY-day-t.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            md = f.read()
    js = {}
    jpath = os.path.join(out, "factory-day-t.json")
    if os.path.exists(jpath):
        with open(jpath, encoding="utf-8") as f:
            js = json.load(f)
    return rc, md, js, base


def test_run_day_replays_both_horizons():
    """Сквозная дорога: прогон исполняет обе цели и печатает числа.

    «Тесты зелёные» значит ровно те дороги, которые тесты ИСПОЛНЯЮТ
    (урок S11): отчёт, артефакт и реплей обеих книг — здесь.
    """
    tmp = tempfile.mkdtemp()
    p = sheet(tmp, hours=6, with24=True, mirror=True)
    now = time.time()
    rc, md, js, base = run_day_on(tmp, p, extra_declare=[
        ("c4", {"rule": rule(), "at": now - 2 * DAY}),
        ("c24", {"rule": rule(target="fwd_24h"), "at": now - 2 * DAY})])
    check("прогон дошёл до конца", rc == 0, str(rc))
    check("отчёт печатает, что несёт лист",
          "Что несёт лист сечения" in md and "fwd_24h" in md, md[:200])
    check("ноги посчитаны по целям",
          (js.get("meta") or {}).get("legs_by_target", {}).get("fwd_24h", 0)
          > 0, str((js.get("meta") or {}).get("legs_by_target")))
    cands = js.get("candidates") or {}
    check("обе книги дали сделки",
          (cands.get("c4") or {}).get("trades", 0) > 0
          and (cands.get("c24") or {}).get("trades", 0) > 0,
          str({k: v.get("trades") for k, v in cands.items()}))
    check("сделки у них разные",
          {(t["sym"], t["side"]) for t in cands["c4"]["last"]}
          != {(t["sym"], t["side"]) for t in cands["c24"]["last"]},
          "книги двух горизонтов торгуют одно и то же")
    check("знаменатель исполнимого посчитан по содержимому",
          (js.get("summary") or {}).get("available", 0)
          > (js.get("summary") or {}).get("available_declared", 0),
          str(js.get("summary")))


def test_run_refuses_when_a_target_gives_no_legs():
    """Цель в листе есть, а ног ноль — прогон ОТКАЗЫВАЕТСЯ.

    Пустой отчёт с прочерками выглядел бы исправной фабрикой без
    сделок: ровно так первый живой прогон отчитался кодом 0, когда у
    него было сломано чтение баров.
    """
    tmp = tempfile.mkdtemp()
    # Поля 24 ч на месте (лист их НЕСЁТ), но стороны в них
    # переставлены: ход против позиции смотрит в пользу. Знаковая
    # проверка `_leg` такую строку не пускает, и ног из цели не выходит.
    recs = [rec_at(h, [row(f"C{i}USDT", 60.0 + 5 * i, 70.0 + i,
                           mae24=80.0, mfe24=-240.0)
                       for i in range(4)]) for h in range(3)]
    p = write_sheet(os.path.join(tmp, "broken.jsonl"), recs)
    caps = HZ.sheet_caps(p)
    check("лист при этом цель НЕСЁТ",
          "fwd_24h" in caps["targets"], str(sorted(caps["targets"])))
    rc, md, js, base = run_day_on(tmp, p, extra_declare=[
        ("c4", {"rule": rule(), "at": time.time() - 2 * DAY})])
    check("прогон отказался, а не отчитался нулями", rc == 1, str(rc))
    check("отчёта при отказе нет", md == "", md[:120])


def test_blocked_candidate_is_named_and_not_swept():
    """Книгу, которую нечем реплеить, правило вылета НЕ судит.

    Ноль сделок у неё — НАША дыра в листе, а не её простой; вылет по
    ней был бы вердиктом о правиле, которого никто не мерил.
    """
    tmp = tempfile.mkdtemp()
    p = sheet(tmp, hours=6, with24=False)          # лист прежнего образца
    now = time.time()
    rc, md, js, base = run_day_on(tmp, p, extra_declare=[
        ("c4", {"rule": rule(), "at": now - 2 * DAY}),
        ("c24", {"rule": rule(target="fwd_24h"),
                 "at": now - (PL.IDLE_D + 10) * DAY})])
    check("прогон дошёл до конца", rc == 0, str(rc))
    check("кандидат назван в отчёте причиной",
          "нечем реплеить" in md and "c24" in md, md[-800:])
    check("причина уехала и в артефакт числами",
          "c24" in (js.get("blocked") or {}), str(js.get("blocked")))
    st = LG.state(LG.read(base)[0])
    check("в полосы и в счёт он не попал",
          "c24" not in (js.get("candidates") or {}),
          str(list((js.get("candidates") or {}))))
    check("и правилом вылета он НЕ отставлен",
          st["c24"]["retired_at"] is None,
          str(st["c24"].get("retired_at")))
    # Контроль на саму проверку: кандидат СТАРШЕ предела простоя, то
    # есть без исключения он был бы отставлен именно сейчас.
    check("при этом он старше предела простоя",
          (now - st["c24"]["declared_at"]) / DAY > PL.IDLE_D,
          str((now - st["c24"]["declared_at"]) / DAY))


TESTS = [
    test_sheet_caps_reads_content_not_constant,
    test_caps_read_the_tail_not_the_head,
    test_report_phrase_comes_from_the_numbers,
    test_old_sheet_is_refused_aloud_not_replayed_as_4h,
    test_horizon_changes_the_leg_set,
    test_ids_distinguish_horizon,
    test_quantile_fields_do_not_leak_across_horizons,
    test_calibration_planted_and_copy,
    test_no_lookahead_future_does_not_move_the_past,
    test_supply_gap_is_a_refusal_not_a_dash,
    test_quantile_geometry_is_refused_on_24h,
    test_risk_sizing_is_refused_on_24h,
    test_sigma_rank_needs_the_z_field,
    test_available_total_counts_content_not_the_constant,
    test_draw_reaches_the_second_horizon,
    test_book_takes_only_its_own_horizon,
    test_agreement_is_within_one_horizon,
    test_null_permutes_within_the_horizon,
    test_run_day_replays_both_horizons,
    test_run_refuses_when_a_target_gives_no_legs,
    test_blocked_candidate_is_named_and_not_swept,
]


def main():
    """Имя УПАВШЕГО блока печатается отдельной строкой `ПРОВАЛ <имя>`.

    По ней машина приёмки сверяет, что негативный контроль уронил
    именно ту проверку, которая обещана: контроль, роняющий соседнюю,
    проверяет не то правило, о котором заявлен.
    """
    bad = []
    t0 = time.time()
    for t in TESTS:
        print(t.__name__)
        n0 = len(FAILED)
        try:
            t()
        except Exception as e:                             # noqa: BLE001
            FAILED.append(f"{t.__name__}/{type(e).__name__}")
            print(f"  сорвался: {type(e).__name__}: {e}", flush=True)
        if len(FAILED) > n0:
            bad.append(t.__name__)
            print(f"ПРОВАЛ {t.__name__}", flush=True)
    if bad:
        # Список упавших блоков повторяется В КОНЦЕ и с тем же ярлыком:
        # приёмка читает ХВОСТ вывода (последние 4000 символов), и
        # сквозной прогон, печатающий отчёт, вытеснил бы оттуда имя
        # блока, упавшего в начале, — контроль объявился бы «упавшим не
        # на том».
        print("")
        for name in bad:
            print(f"ПРОВАЛ {name}", flush=True)
        print(f"ПРОВАЛЕНО: проверок {len(FAILED)}, блоков "
              f"{len(bad)} из {len(TESTS)}", flush=True)
        return 1
    print(f"\nвсе {len(TESTS)} блоков прошли за {time.time() - t0:.1f} с",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
