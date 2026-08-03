#!/usr/bin/env python3
"""
Отчёт о пробном прогоне конвейера — файлом, а не пересказом консоли.

Зачем отдельный файл
--------------------

Правило публикации проекта: каждый прогон пишет отчёт **файлом** в
`out/`, а `tools/publish.sh` его коммитит. Прогон идёт на сервере,
обсуждается в другом месте, и пересказ консоли скриншотами терял числа
и время. Артефакты пробного прогона в git не идут (они неотличимы от
боевых по содержимому), а отчёт по ним — идёт.

Что проверяет отчёт
-------------------

**Работу конвейера, а не качество модели.** На восьми сечениях IC есть
шум, а горизонт 24 часа не имеет ни одной цели вовсе. Поэтому отчёт
устроен как список шагов с ответом «прошёл / не прошёл и почему», а
числа качества печатаются с явной пометкой, что измерением не являются.

Единственное число, которое читать МОЖНО, — канарейка: обучение на
перемешанных целях обязано дать IC около нуля при любом объёме данных.
Она проверяет течь конвейера, а не рынок, и на малой выборке
осмысленна.

    .venv/bin/python research/s8_loop/probe_report.py
    .venv/bin/python research/s8_loop/probe_report.py --dir out/model

Зависимостей нет: только стандартная библиотека, чтобы отчёт собирался
и там, где окружение сломано (урок R1 — `report.py` тянул numpy через
пороги и не собирался из готового JSON).
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
TARGETS = ("fwd_1h", "fwd_4h", "fwd_24h", "mae_4h")
ARMS = ("gbm", "nn")
RU_ARM = {"gbm": "деревья (ML)", "nn": "сеть (AI)"}
CANARY_STOP = 0.01


def jload(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def jlines(path):
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


def step(ok, name, detail=""):
    """Строка таблицы шагов. Состояний ТРИ, а не два.

    «Разбирать нечего, это первый прогон» — не отказ, а нормальное
    состояние: живой IC, разбор факта и счета появляются со второго
    прогона по построению. Пометить их отказом значило бы поднять
    ложную тревогу и приучить не читать таблицу. `None` означает
    «ожидаемо пусто».
    """
    mark = {True: "прошёл", False: "**НЕ прошёл**",
            None: "ожидаемо пусто"}[ok]
    return f"| {name} | {mark} | {detail} |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(OUT, "model_probe"),
                    help="каталог артефактов прогона")
    ap.add_argument("--out", default=os.path.join(OUT,
                                                  "S8-probe-report.md"))
    a = ap.parse_args()
    d = a.dir if os.path.isabs(a.dir) else os.path.join(HERE, a.dir)
    if not os.path.isdir(d):
        raise SystemExit(f"нет каталога {d} — прогон не запускался?")

    man = jload(os.path.join(d, "manifest.json"))
    rd = jload(os.path.join(d, "readiness.json"))
    ic = jlines(os.path.join(d, "ic_history.jsonl"))
    picks = jlines(os.path.join(d, "picks.jsonl"))
    review = jlines(os.path.join(d, "review.jsonl"))
    thoughts = jlines(os.path.join(d, "thoughts.jsonl"))
    accs = {arm: jload(os.path.join(d, f"account_{arm}.json"))
            for arm in ARMS}
    weights = sorted(f for f in os.listdir(d)
                     if f.startswith("weights_") and f.endswith(".pkl"))

    L = ["# S8 — пробный прогон конвейера", ""]
    if man and not man.get("probe"):
        L += ["> **Внимание: это артефакты БОЕВОГО прогона** — в манифесте "
              "`probe: false`. Отчёт собран по ним как есть.", ""]
    else:
        L += ["Проверяется, что цепочка обучения работает целиком, а НЕ "
              "качество модели. Порог боевого обучения — "
              f"{(man or {}).get('min_sections', '?')} сечений против "
              f"{(rd or {}).get('need', 48)} у боевого прогона; на таком "
              "объёме числа качества являются шумом и приводятся только "
              "как признак того, что шаг вообще отработал.", ""]

    # ---------- накопление ----------
    L += ["## Что было на входе", ""]
    if rd:
        L += [f"- сечений годных: **{rd['sections']}** "
              f"(порог боевого обучения {rd['need']})",
              f"- монет в сборе: {rd['symbols']}, часов сведено: "
              f"{rd['hours']}, признаков: {rd['features']}",
              f"- сечением считается час, где годных имён "
              f"≥ {rd['min_section']}"]
        bh = rd.get("by_hour") or []
        thin = [h for h in bh if h["n"] < rd["min_section"]]
        L += [f"- из последних {len(bh)} часов не дотянули {len(thin)}",
              "",
              "Имён в часе, последние двенадцать: "
              + " · ".join(f"{h['h'][-2:]}ч {h['n']}" for h in bh[-12:])]
    else:
        L += ["- файла готовности нет"]
    L += [""]

    # ---------- шаги ----------
    L += ["## Шаги конвейера", "",
          "| шаг | итог | чем подтверждён |", "|---|---|---|"]
    L += [step(rd is not None, "сводка часов -> матрица",
               f"{(rd or {}).get('hours', '?')} часов × "
               f"{(rd or {}).get('symbols', '?')} монет")]

    can = (man or {}).get("canary_ic")
    can_ok = can is not None and abs(can) <= CANARY_STOP
    L += [step(can_ok, "канарейка (обучение на перемешанных целях)",
               f"IC {can:+.4f} при пороге ±{CANARY_STOP}"
               if can is not None else "не считалась")]

    have = {(w.split("_")[1], w[len("weights_"):-4].split("_", 1)[1])
            for w in weights}
    for arm in ARMS:
        got = sorted(t for t in TARGETS if (arm, t) in have)
        miss = [t for t in TARGETS if t not in got]
        L += [step(bool(got), f"обучение: {RU_ARM[arm]}",
                   ("веса на " + ", ".join(got) if got else "весов нет")
                   + (f"; без целей: {', '.join(miss)}" if miss else ""))]

    # Выбор обязан быть, если веса обеих целей отбора обучились: он и
    # есть то, ради чего конвейер существует. Его отсутствие при
    # готовых весах — настоящий отказ, а не «рано».
    can_pick = any((arm, "fwd_4h") in have and (arm, "mae_4h") in have
                   for arm in ARMS)
    L += [step(bool(picks) if can_pick else None,
               "выбор длинных и коротких",
               f"записей {len(picks)}" if picks else
               "нужны веса fwd_4h и mae_4h — на этой истории цели "
               "четырёх часов может не быть")]
    # Разбор и счета появляются со ВТОРОГО прогона по построению:
    # разбирать можно только прошлый выбор.
    L += [step(bool(review) or None, "разбор прошлого выбора фактом",
               f"записей {len(review)}"
               if review else "первый прогон — разбирать нечего")]
    L += [step(any(accs.values()) or None, "бумажные счета",
               " · ".join(f"{RU_ARM[k]} ${v['balance']}"
                          for k, v in accs.items() if v)
               or "счёт открывается со второго прогона")]
    L += [step(bool(thoughts), "мысли словами",
               f"строк {len(thoughts)}" if thoughts else "нет")]
    L += [""]

    # ---------- числа, которые НЕ измерение ----------
    L += ["## Числа прогона", "",
          "Ниже — не измерение. На таком числе сечений разброс IC "
          "перекрывает любую разницу между руками, а горизонты, у "
          "которых форвард не помещается в накопленную историю, целей "
          "не имеют вовсе.", ""]
    if ic:
        L += ["| рука | цель | IC | сечений |", "|---|---|---|---|"]
        for r in ic[-8:]:
            L += [f"| {RU_ARM.get(r.get('arm', 'gbm'), r.get('arm'))} "
                  f"| {r.get('target')} | {r.get('median_ic')} "
                  f"| {r.get('n', '—')} |"]
    else:
        L += ["Живого IC нет: он считается сравнением ПРОШЛЫХ весов с "
              "фактом, а прошлых весов у первого прогона не бывает."]
    L += [""]

    if man and man.get("importance"):
        L += ["### Что модель сочла важным", "",
              "Читается как признак того, что признаки доехали до "
              "модели, а не как содержательный вывод.", ""]
        for arm, per in sorted(man["importance"].items()):
            for tgt, imp in sorted(per.items()):
                top = ", ".join(f"{k} {v}"
                                for k, v in list(imp.items())[:5])
                L += [f"- **{RU_ARM.get(arm, arm)} / {tgt}**: {top}"]
        L += [""]

    if thoughts:
        L += ["### Мысли последнего прогона", ""]
        L += [f"- {t.get('text')}" for t in thoughts[-8:]] + [""]

    if man:
        L += ["## Манифест", "",
              f"- версия весов: v{man.get('version')}",
              f"- обучено до часа: {man.get('trained_upto')}",
              f"- пометка probe: **{man.get('probe')}**",
              f"- цикл занял: {man.get('cycle_sec')} с",
              f"- новых часов сводки за прогон: "
              f"{man.get('new_summary_hours')}", ""]

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"отчёт записан: {a.out}")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
