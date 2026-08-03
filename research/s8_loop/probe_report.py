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
ARMS = ("gbm", "nn")
RU_ARM = {"gbm": "деревья (ML)", "nn": "сеть (AI)"}
# Ни списка целей, ни порога канарейки здесь НЕТ намеренно. Первая
# версия отчёта держала их константами, и обе разошлись с прогоном за
# один вечер: целей оказалось девять, а не четыре, и отчёт объявил
# шесть обученных целей «пропущенными»; порог канарейки был записан
# 0.01 против 0.05 в цикле. Отчёт обязан описывать ТОТ прогон, который
# породил файл (урок R1) — значит и цели, и пороги читаются из
# артефакта.


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


def write(d, out_path):
    """Собрать отчёт по каталогу артефактов. Возвращает путь."""
    # Обычная ошибка, а не SystemExit: `write` зовут из цикла обучения,
    # и `SystemExit` мимо `except Exception` убил бы прогон целиком —
    # отчёт не вправе ронять то, о чём отчитывается.
    if not os.path.isdir(d):
        raise FileNotFoundError(f"нет каталога {d} — прогон не запускался?")

    man = jload(os.path.join(d, "manifest.json"))
    rd = jload(os.path.join(d, "readiness.json"))
    run = jload(os.path.join(d, "last_run.json"))
    ic = jlines(os.path.join(d, "ic_history.jsonl"))
    picks = jlines(os.path.join(d, "picks.jsonl"))
    review = jlines(os.path.join(d, "review.jsonl"))
    thoughts = jlines(os.path.join(d, "thoughts.jsonl"))
    accs = {arm: jload(os.path.join(d, f"account_{arm}.json"))
            for arm in ARMS}
    weights = sorted(f for f in os.listdir(d)
                     if f.startswith("weights_") and f.endswith(".pkl"))

    L = ["# S8 — пробный прогон конвейера", ""]
    # Манифест пишется В КОНЦЕ цикла, а готовность — в начале. Значит
    # прогон, остановленный канарейкой или нехваткой сечений, оставляет
    # манифест ПРОШЛОГО прогона нетронутым, и отчёт по нему рассказал бы
    # про обучение, которого сейчас не было. Различить это можно только
    # по времени, и молчать тут нельзя: артефакт прошлого прогона,
    # выдающий себя за нынешний, — самый частый дефект этого проекта.
    ref = (run or {}).get("at") or (rd or {}).get("at")
    stale = (man and ref and man.get("trained_at")
             and man["trained_at"] < ref)
    if run:
        L += [f"**Чем кончился этот прогон: {run['reason']}** "
              f"({run['at']}).", ""]
    if stale:
        L += [f"> **Манифест старше этого прогона** — обучение "
              f"{man['trained_at']}, прогон {ref}. Веса, важности и мысли "
              f"ниже описывают ПРОШЛЫЙ прогон, а не этот: цикл "
              f"остановился до их записи.", ""]
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
        L += [f"- из последних {len(bh)} часов не дотянули {len(thin)}"]
        bmin, hps = rd.get("beta_min_hours"), rd.get("hours_per_symbol")
        if bmin is not None and hps is not None:
            L += [f"- часов годной истории на монету: **{hps}** при "
                  f"{bmin}, нужных бете — а без беты нет цели `fwd_4h`, "
                  f"то есть ни канарейки, ни выбора"]
        L += ["",
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

    # Канарейка судится по ИСХОДУ этого прогона, а не по манифесту:
    # манифест мог остаться от прошлого, и его `canary_ic` описывал бы
    # чужую проверку.
    reason = (run or {}).get("reason")
    can = (run or man or {}).get("canary_ic")
    stop = (run or man or {}).get("canary_stop")
    if reason == "канарейка не считалась":
        L += [step(False, "канарейка (обучение на перемешанных целях)",
                   "**не считалась — а это не то же самое, что "
                   "пройдена**: цель fwd_4h пуста, ей нужна бета")]
    elif reason == "канарейка кричит":
        L += [step(False, "канарейка (обучение на перемешанных целях)",
                   f"IC {can:+.4f} при пороге ±{stop} — похоже на течь")]
    elif can is not None and stop is not None:
        L += [step(abs(can) <= stop,
                   "канарейка (обучение на перемешанных целях)",
                   f"IC {can:+.4f} при пороге ±{stop}")]
    else:
        L += [step(None, "канарейка (обучение на перемешанных целях)",
                   "до неё не дошло" if reason else "исхода прогона нет")]

    # Цели берутся из самого прогона: имена весов плюс ключи важностей.
    have = {(w[len("weights_"):-4].split("_", 1)[0],
             w[len("weights_"):-4].split("_", 1)[1]) for w in weights}
    declared = sorted({t for _, t in have}
                      | {t for per in ((man or {}).get("importance")
                                       or {}).values() for t in per}
                      | set((man or {}).get("targets_all") or ()))
    trained_now = reason == "обучилась" or reason is None
    for arm in ARMS:
        got = sorted(t for t in declared if (arm, t) in have)
        miss = [t for t in declared if (arm, t) not in have]
        detail = ((f"веса на {len(got)} целях: " + ", ".join(got)
                   if got else "весов нет")
                  + (f"; без целей ({len(miss)}): " + ", ".join(miss)
                     if miss else ""))
        if not trained_now:
            # Веса на диске есть, но положил их не этот прогон. Назвать
            # шаг пройденным значило бы записать чужую работу в свою.
            L += [step(None, f"обучение: {RU_ARM[arm]}",
                       f"этот прогон до обучения не дошёл ({reason}); "
                       f"на диске лежит прошлое: {detail}")]
        else:
            L += [step(bool(got), f"обучение: {RU_ARM[arm]}", detail)]

    # Выбор обязан быть, если веса обеих целей отбора обучились: он и
    # есть то, ради чего конвейер существует. Его отсутствие при
    # готовых весах — настоящий отказ, а не «рано».
    can_pick = any((arm, "fwd_4h") in have and (arm, "mae_4h") in have
                   for arm in ARMS)
    L += [step(bool(picks) if (can_pick and trained_now) else None,
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
    L += [step(bool(thoughts) if trained_now else None, "мысли словами",
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

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out_path, L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(OUT, "model_probe"),
                    help="каталог артефактов прогона")
    ap.add_argument("--out", default=os.path.join(OUT,
                                                  "S8-probe-report.md"))
    a = ap.parse_args()
    d = a.dir if os.path.isabs(a.dir) else os.path.join(HERE, a.dir)
    try:
        path, L = write(d, a.out)
    except FileNotFoundError as e:
        raise SystemExit(str(e))
    print(f"отчёт записан: {path}")
    print("\n".join(L[:44]))


if __name__ == "__main__":
    main()
