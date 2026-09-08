"""Горизонт цели в листе сечения: что лист НЕСЁТ и как из этого ноги.

Механика `12cc2578` — «вторая цель в листе сечения». Пространство
фабрики объявляет ось `target` двумя значениями (`fwd_4h`, `fwd_24h`),
но реплей до сих пор умел ровно одно: `tournament.legs_from_sheets`
читает поля `fwd`, `mae`, `mfe` — то есть горизонт сигнала, и только
его. Кандидат на 24 ч был неисполним не рынком, а полями листа: 2592
сочетания из 5184 стояли закрытыми константой `space.SHEET_TARGETS`.

Этот модуль снимает ровно это и ровно так, как велит задание:

* **цель берётся из оси `target` правила**, а набор полей — из таблицы
  `FIELDS`. Одна строка листа порождает СТОЛЬКО ног, сколько целей она
  несёт, и `id` ноги их различает: иначе исходы двух горизонтов легли
  бы в кэш `outcomes_for` под одним ключом и затёрли друг друга;
* **исполнимость решается СОДЕРЖИМЫМ листа** (`sheet_caps`), а не
  константой. Константа осталась умолчанием на случай «содержимое не
  читали», и отказ в этом случае так и говорит — иначе объявленный
  образец листа однажды разошёлся бы с тем, что цикл пишет на самом
  деле, и разойтись мог бы молча;
* **лист прежнего образца читается как «цели нет», а не как ноль.**
  Строка без полей 24 ч не превращается в ногу с 4-часовым стопом:
  подстановка соседнего горизонта дала бы книгу, которая выглядит
  торгующей 24 ч, а торгует 4 ч, — и вердикт был бы о другой книге.

Второй копии расчётного ядра здесь нет: сама нога считается тем же
`tournament._leg` (стороны, `path_fields`, отношение), базовый горизонт
собирается ДОСЛОВНО тем же `tournament.legs_from_sheets`. Своего у
модуля ровно две вещи — таблица полей по горизонту и чтение содержимого
листа. Равенство двух дорог чтения закреплено проверкой: лист, где поля
24 ч дословно повторяют 4-часовые, обязан дать ноги, отличающиеся
только `id` и `target`.

Чего на 24-часовой цели НЕТ и почему это сказано словами, а не обойдено:
квантильных концов пути (`maeq`/`mfeq`) цикл на 24 ч не обучает. Значит
исполнимы только геометрия `timer` (выход по времени, ни стопа, ни
цели) и размер, отличный от `risk` (равный риск считается от
ИСПОЛНЯЕМОГО стопа, которого нет). Это правило задания, и живёт оно в
`space.unavailable`, потому что читателей у него трое — объявление,
потолок и суточный прогон.

Импорт турнира ЛЕНИВЫЙ: содержимое листа читает и приёмка
(`runlog.check_proposal`), которой numpy и загрузчик баров не нужны ни
на одном её шаге.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)

import space as SP                                          # noqa: E402

# Журнал листов сечения. Путь живёт ЗДЕСЬ и один: суточный прогон,
# объявление и приёмка обязаны смотреть в один и тот же файл — каждая
# со своей копией пути однажды судила бы кандидата по одному листу, а
# реплеила по другому.
SHEETS = os.path.join(RESEARCH, "s8_loop", "out", "model_sit",
                      "sheets.jsonl")

# Базовая цель — та, которую читает `tournament.legs_from_sheets` без
# всякого перевода полей. Ноги старого образца (журнал турнира, тесты
# реплея) поля `target` не несут вовсе, и для них база — единственный
# честный ответ: именно её поля они и читали.
BASE_TARGET = "fwd_4h"

# Канонические имена, которых ждёт `tournament._leg`. Перечислены здесь
# затем, чтобы вид строки под другой горизонт СНИМАЛ чужие поля, а не
# добавлял свои поверх: строка, где рядом лежат `mae` (4 ч) и `mae_24h`,
# иначе отдала бы 24-часовой ноге четырёхчасовой стоп.
CANON = ("fwd", "fwd_z", "mae", "mfe", "mae_q", "mfe_q")

# Поля горизонта в строке листа. Имена 24 ч — дословно те, которые
# задание велит роли `fix` дописать в `scan_sheet.json` и `sheets.jsonl`
# рядом с полями 4 ч (`fwd_24h`, `fwd_24h_z`, `mae_24h`, `mfe_24h`).
# Квантильных концов на 24 ч нет и не будет, пока цикл их не учит.
FIELDS = {
    "fwd_4h": {"fwd": "fwd", "fwd_z": "fwd_z", "mae": "mae", "mfe": "mfe",
               "mae_q": "mae_q", "mfe_q": "mfe_q"},
    "fwd_24h": {"fwd": "fwd_24h", "fwd_z": "fwd_24h_z", "mae": "mae_24h",
                "mfe": "mfe_24h"},
}

# Без этих трёх цели в строке нет вовсе: `_leg` вернул бы None, а
# подставить их неоткуда — соседний горизонт есть другая величина.
REQUIRED = ("fwd", "mae", "mfe")

# Сколько последних листов читается, чтобы ответить, что лист несёт
# СЕЙЧАС. Число диагностическое: решение принимается по САМОМУ свежему
# листу со строками, а остальные печатаются рядом числом — «поля
# появились час назад» и «поля лежат сутки» лечатся по-разному.
TAIL_RECORDS = 24
TAIL_STEP = 1 << 20
TAIL_MAX = 64 << 20


def _tn():
    """Турнир политик — ленивым импортом (см. шапку модуля)."""
    import sys
    for p in (os.path.join(RESEARCH, "s10_policy"),
              os.path.join(RESEARCH, "s8_loop")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import tournament as TN
    return TN


def leg_target(lg):
    """Горизонт ноги. Нога без поля — базовая: она читала его поля."""
    return lg.get("target") or BASE_TARGET


# --- что лист несёт --------------------------------------------------

def row_caps(row):
    """Что несёт ОДНА строка листа: цель → (порядок в σ, квантили).

    Возвращает словарь только по тем целям, у которых в строке есть все
    обязательные поля. Поле, лежащее значением `null`, отсутствию
    равнозначно: «не измерено» не есть ноль, и нога из него не выйдет.
    """
    out = {}
    for tgt, names in FIELDS.items():
        if any(row.get(names[k]) is None for k in REQUIRED):
            continue
        z = row.get(names.get("fwd_z") or "") is not None
        q = (names.get("mae_q") is not None
             and row.get(names.get("mae_q") or "") is not None
             and row.get(names.get("mfe_q") or "") is not None)
        out[tgt] = {"z": z, "q": q}
    return out


def record_caps(rec):
    """Что несёт один ЛИСТ: цель → {строк, порядок в σ, квантили}.

    Считается по всем рукам: лист пишут обе, и цель, лежащая у одной
    руки, уже читается реплеем — отсев по руке случится ниже, в
    `agreed_keys` и в местах книги.
    """
    out = {}
    for _arm, rows in (rec.get("arms") or {}).items():
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for tgt, c in row_caps(row).items():
                got = out.setdefault(tgt, {"rows": 0, "z": False,
                                           "q": False})
                got["rows"] += 1
                got["z"] = got["z"] or c["z"]
                got["q"] = got["q"] or c["q"]
    return out


def _tail_lines(path, n):
    """Последние `n` полных строк файла. (строки, причина пустоты).

    Читается с конца кусками, удваивая их до тех пор, пока не наберётся
    нужное число строк: журнал листов — сотни мегабайт (269 МБ на
    2026-09-08, около 370 КБ на лист), и вопрос «что лист несёт СЕЙЧАС»
    не стоит полного прохода по нему.
    Первая строка прочитанного куска отбрасывается, пока он не упёрся в
    начало файла: она обрезана посередине, и разобрать её значило бы
    молча потерять запись.
    """
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return [], f"журнала листов нет ({path}): {e.strerror}"
    if not size:
        return [], f"журнал листов пуст: {path}"
    step = TAIL_STEP
    while True:
        take = min(size, step)
        with open(path, "rb") as f:
            f.seek(size - take)
            data = f.read(take)
        lines = data.split(b"\n")
        if take < size:
            lines = lines[1:]
        lines = [x for x in lines if x.strip()]
        if len(lines) >= n or take >= size or step >= TAIL_MAX:
            return lines[-n:], None
        step *= 2


def sheet_caps(path, tail=TAIL_RECORDS):
    """Что лист сечения несёт СЕЙЧАС — по содержимому, а не по константе.

    Решение принимается по САМОМУ СВЕЖЕМУ листу, в котором есть строки:
    вопрос ведь именно «несёт ли лист цель сегодня». Сколько из
    прочитанных листов её несут — печатается рядом числом (`recent`) и
    вердиктом не является: цель, появившаяся час назад, исполнима, а
    цель, пропавшая час назад, — нет, и оба случая надо ВИДЕТЬ.

    Пустота всегда объяснена полем `why`: «журнала нет», «журнал пуст»,
    «в последнем листе нет строк» лечатся по-разному, и молчаливый
    пустой словарь означал бы «лист не несёт ничего» — то есть отказ,
    неотличимый от исправности.
    """
    caps = {"path": path, "targets": {}, "records": 0, "recent": {},
            "at": None, "hour": None, "why": None}
    lines, why = _tail_lines(path, tail)
    if why:
        caps["why"] = why
        return caps
    recs = []
    for raw in lines:
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict):
            recs.append(rec)
    caps["records"] = len(recs)
    if not recs:
        caps["why"] = f"в последних {len(lines)} строках журнала нет листов"
        return caps
    for rec in recs:
        for tgt in record_caps(rec):
            caps["recent"][tgt] = caps["recent"].get(tgt, 0) + 1
    for rec in reversed(recs):
        got = record_caps(rec)
        if got:
            caps["targets"] = got
            caps["at"] = rec.get("written_at")
            caps["hour"] = rec.get("hour")
            break
    if not caps["targets"]:
        caps["why"] = (f"в последних {len(recs)} листах нет ни одной "
                       f"строки с полными полями цели")
    return caps


def targets_of(caps):
    """Цели, которые лист несёт. Нет разбора — объявленный образец.

    Умолчание названо честно: `space.SHEET_TARGETS` есть то, что цикл
    писал в лист на день объявления пространства, и служит ответом
    ровно там, где содержимое НЕ читали.
    """
    tg = (caps or {}).get("targets") if isinstance(caps, dict) else None
    if not tg:
        return tuple(SP.SHEET_TARGETS)
    # База идёт первой: её ноги собирает существующий загрузчик, и
    # порядок сборки не должен зависеть от порядка ключей словаря.
    rest = sorted(t for t in tg if t != BASE_TARGET)
    return tuple(([BASE_TARGET] if BASE_TARGET in tg else []) + rest)


def phrase(caps):
    """Фраза о листе, ВЫВЕДЕННАЯ из чисел, а не стоящая рядом с ними.

    Проза, утверждающая своё, однажды разойдётся с таблицей — в этом
    проекте это уже случалось в отчёте о цене прохода лесенки.
    """
    tg = (caps or {}).get("targets") or {}
    if not tg:
        return ("лист сечения не несёт ни одной цели: "
                + ((caps or {}).get("why") or "причина не названа"))
    parts = []
    for t in sorted(tg):
        c = tg[t]
        seen = (caps.get("recent") or {}).get(t, 0)
        parts.append(f"{t} — строк {c['rows']}, листов из "
                     f"{caps.get('records', 0)}: {seen}, порядок в σ "
                     f"{'есть' if c.get('z') else 'НЕТ'}, квантильные "
                     f"концы {'есть' if c.get('q') else 'НЕТ'}")
    return "; ".join(parts)


def report_lines(caps):
    """Таблица «что несёт лист» для отчёта суточного прогона."""
    L = ["## Что несёт лист сечения\n",
         f"**{phrase(caps)}**\n",
         "| цель | строк в свежем листе | листов из "
         f"{(caps or {}).get('records', 0)} | порядок в σ | "
         "квантильные концы |",
         "|---|--:|--:|---|---|"]
    tg = (caps or {}).get("targets") or {}
    if not tg:
        L.append("| — | — | — | — | — |")
    for t in sorted(tg):
        c = tg[t]
        seen = (caps.get("recent") or {}).get(t, 0)
        L.append(f"| `{t}` | {c['rows']} | {seen} | "
                 f"{'есть' if c.get('z') else 'нет'} | "
                 f"{'есть' if c.get('q') else 'нет'} |")
    L.append("")
    L.append("Цель, которой лист не несёт, читается как «цели нет», а не "
             "как ноль: кандидат на неё не объявляется, а объявленный "
             "раньше не реплеится полями соседнего горизонта. Строка, "
             "лежащая тут, — содержимое журнала, а не константа "
             "пространства: разойдись они, кандидат судился бы по "
             "листу, которого нет.\n")
    return L


# --- ноги --------------------------------------------------------------

def _view(row, target):
    """Строка листа глазами ОДНОЙ цели, или None.

    Чужие канонические поля сняты, свои подставлены под каноническими
    именами. Обязательного поля нет — цели в строке нет, и это ответ:
    подставить сюда соседний горизонт значило бы выдать книгу 24 ч за
    книгу 4 ч и не сказать об этом никому.
    """
    names = FIELDS[target]
    out = {k: v for k, v in row.items() if k not in CANON}
    for canon, src in names.items():
        got = row.get(src)
        if got is None:
            if canon in REQUIRED:
                return None
            continue
        out[canon] = got
    return out


def _records(paths, log=print):
    """Листы журнала по порядку. Битая строка пропускается молча — так
    же, как её пропускает существующий загрузчик."""
    for path in paths:
        try:
            fh = open(path, encoding="utf-8")
        except OSError:
            log(f"{path}: журнала нет — пропуск")
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec


def _legs_for(paths, target, TN, log=print):
    """Ноги ОДНОЙ небазовой цели тем же `_leg`, что у базовой."""
    legs = []
    for rec in _records(paths, log=log):
        at = rec.get("written_at") or (
            (TN.TR._ts(rec.get("hour")) or 0) + 3600)
        if not at:
            continue
        for arm, rows in (rec.get("arms") or {}).items():
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                view = _view(row, target)
                if view is None:
                    continue
                lg = TN._leg(view, arm, rec.get("hour"), float(at))
                if lg is not None:
                    lg["target"] = target
                    legs.append(lg)
    return legs


def _order(g):
    """Очередь ног — та же, что у существующего загрузчика, плюс
    горизонт последним ключом: при одном горизонте порядок от этого не
    меняется ни на строку, при двух — становится определённым."""
    return (g["at"], g["arm"],
            -abs(g["fz"]) if g["fz"] is not None else 0,
            g["sym"] or "", leg_target(g))


def legs_from_sheets(paths, caps=None, log=print, stats=None):
    """Ноги ВСЕХ целей, которые несёт лист.

    Базовая цель собирается дословно тем же вызовом, что и до этой
    механики: числа четырёхчасовых книг не вправе шелохнуться от того,
    что рядом появился второй горизонт.

    `id` сквозной и назначается ПОСЛЕ слияния: он есть ключ кэша исходов
    (`run_day.outcomes_for`), и две ноги одной строки листа обязаны
    получить разные — иначе исход 24-часовой ноги затёр бы исход
    четырёхчасовой, и книга торговала бы чужой форвард.

    `stats` — необязательный словарь «цель → сколько ног»: суточный
    прогон печатает его числом и отказывается, если цель лист несёт, а
    ног из неё не вышло (`supply_gap`).
    """
    TN = _tn()
    legs = TN.legs_from_sheets(paths, log=log)
    for lg in legs:
        lg["target"] = BASE_TARGET
    if stats is not None:
        stats[BASE_TARGET] = len(legs)
    for tgt in targets_of(caps):
        if tgt == BASE_TARGET or tgt not in FIELDS:
            continue
        got = _legs_for(paths, tgt, TN, log=log)
        log(f"{tgt}: ног {len(got)}")
        if stats is not None:
            stats[tgt] = len(got)
        legs.extend(got)
    legs.sort(key=_order)
    for i, lg in enumerate(legs):
        lg["id"] = i
    return legs


def supply_gap(caps, stats):
    """Цель есть в листе, а ног из неё ноль — причина отказа или None.

    Ноль наблюдений при непустом входе есть поломка чтения, а не тихий
    рынок: ровно так первый живой прогон фабрики отчитался кодом 0 и
    пустым отчётом. Здесь тот же класс — и он назван числом строк.
    """
    tg = (caps or {}).get("targets") or {}
    bad = []
    for t in sorted(tg):
        rows = tg[t].get("rows") or 0
        if rows and not (stats or {}).get(t):
            bad.append(f"{t}: строк в свежем листе {rows}, а ног ноль")
    if not bad:
        return None
    return ("лист несёт цель, из которой не вышло ни одной ноги — это "
            "поломка чтения, а не тихий рынок: " + "; ".join(bad))
