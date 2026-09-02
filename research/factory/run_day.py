"""Суточный прогон фабрики: объявить, прогнать, отсеять, доложить.

Порядок шагов не произволен.

1. **Объявление.** Кандидатов предлагает ассистент — файлом
   `proposals.jsonl`, а не аргументом команды: канал заданий пускает
   только латиницу без скобок, и правило, приходящее строкой в
   командной строке, нельзя ни проверить, ни сохранить. Контрольная
   рука добирается ТУТ ЖЕ жребием: объявленная позже сравнивалась бы с
   отобранными по другому календарю.
2. **Прогон.** Каждый живой кандидат реплеится по журналу листов.
3. **Нуль.** Перестановка «кто какой исход получил» внутри часа —
   нуль 1 проекта. Считается K зёрнами и общий для книг одной ширины и
   горизонта: у всех кандидатов одно сечение и один форвард, и
   отдельный нуль на книгу был бы тем же числом, посчитанным сто раз.
4. **Отсев.** Вылет по сумме окна против медианы нуля (§6).
5. **Отчёт.** Число испытаний печатается рядом с любым числом: без
   знаменателя «лучшая из ста» есть порядковая статистика шума.

Вердиктом ретро-прогон НЕ является никогда (§2, полоса 2). Судится
кандидат только на данных, которых в момент его объявления не
существовало, и это единственная защита от R5, которую нельзя обойти
подгонкой.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import candidate as CD                                     # noqa: E402
import ledger as LG                                        # noqa: E402
import pool as PL                                          # noqa: E402
import space as SP                                         # noqa: E402
import sweep as SW                                         # noqa: E402
import tournament as TN                                    # noqa: E402

OUT = os.path.join(HERE, "out")
PROPOSALS = os.path.join(HERE, "proposals.jsonl")
# Заявка предлагающего — та самая, которую судит ПОТОЛОК, и она ещё не
# объявлена: между ней и реестром стоит шаг потолка. Файл отдельный от
# `proposals.jsonl` потому, что это разные состояния одного пути —
# «предложено ролью» и «допущено к объявлению». Путь берётся от
# каталога прогона, а не от каталога модуля: иначе прогон в песочнице
# читал бы боевую заявку и судил бы её по своим синтетическим числам.
PROPOSAL_NAME = "proposal.json"
NULL_SEEDS = 10
DAY = 86400.0


# --- объявление ------------------------------------------------------

def read_proposals(path=None):
    """Предложения ассистента: правило и, необязательно, довод.

    Битая строка пропускается и считается — молча потерянное
    предложение сдвинуло бы знаменатель испытаний.

    Путь разрешается В МОМЕНТ ВЫЗОВА, а не в сигнатуре: значение по
    умолчанию связывается при определении функции, и подменить его
    потом нечем — то есть правило, которое нельзя переставить,
    невозможно и проверить. Ровно на этом сегодня уже попался гейт
    каденции обучения (`every_h=TRAIN_EVERY_H`).
    """
    path = path or PROPOSALS
    out, bad = [], 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(r, dict) and isinstance(r.get("rule"), dict):
                    out.append(r)
                else:
                    bad += 1
    except OSError:
        return [], 0
    return out, bad


def pending_rule(state, path):
    """Заявка, которую судит потолок: (правило, причина отсутствия).

    Правило возвращается ТОЛЬКО если оно годно как строка объявленного
    пространства, исполнимо сегодня и ещё НЕ объявлено. Во всех
    остальных случаях причина называется словами: «заявки нет» и
    «заявка негодна» лечатся по-разному, а потолок, увидев пустоту,
    обязан сказать, чем она вызвана, а не пропустить кандидата по
    умолчанию.

    Путь приходит АРГУМЕНТОМ, а не берётся из константы модуля: иначе
    прогон в песочнице читал бы боевую заявку и судил бы её по своим
    синтетическим числам, оставаясь на вид исправным.
    """
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except OSError as e:
        return None, f"заявки нет ({os.path.basename(path)}): {e.strerror}"
    except ValueError as e:
        return None, f"заявка не разбирается: {e}"
    if not isinstance(d, dict) or not isinstance(d.get("rule"), dict):
        return None, "в заявке нет правила"
    rule = d["rule"]
    why = SP.validate(rule)
    if why:
        return None, f"правило заявки негодно: {why}"
    why = SP.unavailable(rule)
    if why:
        return None, f"заявка неисполнима: {why}"
    k = SP.key(rule)
    if k in state:
        return None, (f"заявка {k} уже в реестре: испытание потрачено, "
                      f"судить её потолком поздно")
    return rule, None


def run_pending(rule, legs, outs):
    """Числа заявки тем же реплеем, что у живых кандидатов.

    Это НЕ объявление: заявка испытанием не стала, в число потраченных
    не входит и в реестр не пишется. Прогоняется она здесь потому, что
    ноги и исходы уже загружены — отдельный проход по хранилищу ради
    одной книги был бы стократной платой за то же число.
    """
    tr = CD.simulate(legs, outs, CD.with_geometry(rule))
    return {"key": SP.key(rule), "rule": rule, "trades": len(tr),
            "daily": CD.daily_net(tr)}


def declare_today(base, now, seed, log=print, per_day=None):
    """Объявить предложенных и добрать контрольную руку жребием."""
    per_day = PL.PER_DAY if per_day is None else per_day
    rows, bad = LG.read(base)
    st = LG.state(rows)
    props, bad_p = read_proposals()
    if bad or bad_p:
        log(f"битых строк: реестр {bad}, предложения {bad_p}")
    fresh = []
    for p in props:
        rule = p["rule"]
        note = p.get("note")
        why = SP.validate(rule)
        if why:
            log(f"предложение отвергнуто: {why}")
            continue
        why = SP.unavailable(rule)
        if why:
            log(f"предложение неисполнимо: {why}")
            continue
        k = SP.key(rule)
        if k in st or any(k == SP.key(r) for r, _n in fresh):
            continue
        fresh.append((rule, note))
    return declare_rules(base, now, seed, fresh, log=log, per_day=per_day,
                         source="assistant")


def declare_rules(base, now, seed, fresh, log=print, per_day=None,
                  source="assistant"):
    """Объявить названные правила и добрать контрольную руку жребием.

    Одна реализация на оба канала объявления — ручной список и вердикт
    потолка. Второе место, пишущее в реестр по своим правилам, однажды
    разошлось бы с первым, а реестр и есть знаменатель доказательства:
    испытание, потраченное дважды, отменить нечем.

    Контроль добирается ВСЕГДА, даже когда объявлять нечего: его доля —
    свойство пула, а не заявки. Иначе день без заявки молча ронял бы
    долю случайной руки, и сравнивать отобранных стало бы не с чем.
    """
    per_day = PL.PER_DAY if per_day is None else per_day
    st = LG.state(LG.read(base)[0])
    n_act = len(LG.active(st))
    n_ctl = sum(1 for v in LG.active(st).values()
                if v["lane"] == "control")
    n_sel, n_ctl_new, why = PL.plan_batch(n_act, n_ctl, len(fresh) or
                                          per_day, per_day=per_day)
    if why:
        log(f"партия усечена: {why}")
    declared = []
    for rule, note in fresh[:n_sel]:
        k = SP.key(rule)
        if LG.declare(k, rule, "selected", seed=None, at=now, base=base,
                      source=source, note=note) is None:
            declared.append((k, "selected"))
    taken = set(LG.state(LG.read(base)[0]))
    for rule in SP.draw(seed, n_ctl_new, exclude=taken):
        k = SP.key(rule)
        if LG.declare(k, rule, "control", seed=seed, at=now,
                      base=base, source="draw") is None:
            declared.append((k, "control"))
    return declared


# --- прогон ----------------------------------------------------------

def needed_legs(legs, rules, log=print):
    """Ноги, которые возьмёт ХОТЯ БЫ ОДИН живой кандидат.

    Бары за остальными — чистая потеря: их не возьмёт никто. Отбор
    здесь ТОЧНЫЙ, а не по слабейшему гейту: спрашивается сама
    `passes`, та же функция, которой книга потом берёт ногу. Оценка
    «слабейшим гейтом» разошлась бы с ней при первом же добавлении оси,
    и состав сделок изменился бы молча.
    """
    if not rules:
        return legs
    need = [g for g in legs if any(CD.passes(g, r) for r in rules)]
    log(f"ног всего {len(legs)}, нужных живым кандидатам {len(need)}")
    return need


def record_days(legs):
    """Длина ЗАПИСИ в сутках — сколько календарных суток вообще есть в
    журнале листов сечения.

    Это знаменатель измеримости у потолка, и считать его обязан прогон,
    а не потолок: в артефакте до сих пор не было ни одного числа,
    описывающего длину записи, — `summary.days` есть объединение суток
    КНИГ, то есть величина, зависящая от того, сколько они наторговали.

    Два свойства, каждое из которых и делает число знаменателем:

    * считается по ВСЕМ ногам журнала, ДО отсева `needed_legs` — гейты
      кандидата не вправе укорачивать собственный знаменатель, иначе
      книга, берущая ноги трёх часов, судилась бы окном в трое суток и
      проходила бы ворота построением;
    * сутки СЧИТАЮТСЯ, а не берутся размахом: дня, которого в записи нет
      (сборщик стоял), книге торговать не давали, и ставить его в
      знаменатель значило бы наказывать кандидата за нашу дыру.

    Что число НЕ учитывает, и это сказано, чтобы не читалось шире:
    сутки, в которые лист есть, а баров нет, входят сюда наравне с
    остальными — книга там торговать не могла. Направление ошибки в
    сторону строгости (знаменатель завышен), и оно предпочтительнее
    обратного; чтобы учесть и это, пришлось бы мерить окно по исходам,
    а исходы считаются только за ногами, прошедшими чьи-то гейты, то
    есть знаменатель снова стал бы зависеть от кандидата.
    """
    return len({int(g["at"] // DAY) for g in legs if g.get("at")})


def load_legs(sheets, log=print):
    paths = [sheets] if os.path.isfile(sheets) else []
    if not paths:
        log(f"журнала листов нет: {sheets}")
        return []
    return TN.legs_from_sheets(paths, log=log)


def outcomes_for(legs, root, geoms, log=print):
    """Исходы всех ног при всех нужных геометриях.

    Бары читаются ОДИН раз на имя: сто кандидатов делят одни и те же
    ноги, и второй проход по хранилищу был бы стократной платой за то
    же число.
    """
    outs = {}
    by_sym = {}
    for lg in legs:
        by_sym.setdefault(lg["sym"], []).append(lg)
    for i, (sym, group) in enumerate(sorted(by_sym.items()), 1):
        a = min(g["at"] for g in group) - 3600.0
        b = max(g["at"] for g in group) + 80 * 3600.0
        try:
            bars = SW.read_bars(root, sym, a, b)
        except Exception as e:                            # noqa: BLE001
            log(f"{sym}: баров нет ({type(e).__name__}: {e})")
            continue
        if not bars:
            continue
        for lg in group:
            for stop, take, age in geoms:
                got = TN.outcome(bars, lg["at"], lg["side"],
                                 _adv(lg, stop), _fav(lg, take), age)
                if got is not None:
                    outs[(lg["id"], stop, take, age)] = got
        if i % 50 == 0:
            log(f"  бары: {i} имён из {len(by_sym)}")
    return outs


def _adv(lg, stop):
    if stop == "no":
        return None
    return lg["adv_m"] if stop == "m" else lg["adv_q"]


def _fav(lg, take):
    return lg["fav"] if take else None


def geometries():
    """Все тройки геометрии, какие может попросить пространство."""
    seen = []
    for g in SP.VALUES["geom"]:
        t = CD.geometry({"geom": g})
        if t not in seen:
            seen.append(t)
    return seen


# Сколько последних сделок кандидата кладётся в артефакт. Полный
# список — десятки тысяч строк на кандидата: артефакт стал бы
# неподъёмным, а страница всё равно показывает хвост. Число невелико
# намеренно: показ не должен становиться причиной хранить всё.
LAST_TRADES = 40


def run_candidates(state, legs, outs, log=print):
    """Сделки и дневной нетто по каждому живому кандидату.

    В артефакт едет и ХВОСТ сделок: без него страница может показать
    только суммы, а «книга заработала» без сделок нечем оспорить —
    владелец не увидит ни имён, ни сторон, ни причин выхода.
    """
    res = {}
    for cid, rec in sorted(LG.active(state).items()):
        rule = rec.get("rule") or {}
        if SP.validate(rule):
            log(f"{cid}: правило в реестре негодно — пропуск")
            continue
        tr = CD.simulate(legs, outs, CD.with_geometry(rule))
        last = [{"at": t["at"], "exit": t["exit"], "sym": t["sym"],
                 "side": t["side"], "arm": t["arm"],
                 "net_bp": t["net"], "why": t["why"]}
                for t in tr[-LAST_TRADES:]]
        res[cid] = {"trades": len(tr), "daily": CD.daily_net(tr),
                    "last": last,
                    "declared_at": rec.get("declared_at"),
                    "note": rec.get("note"),
                    "lane": rec.get("lane"), "rule": rule}
    return res


# --- нуль ------------------------------------------------------------

def null_daily(legs, outs, rule, seeds=NULL_SEEDS):
    """Дневной нетто книги на ПЕРЕМЕШАННЫХ внутри часа исходах.

    Переставляется соответствие «нога → исход», то есть кто какой
    форвард получил. Сигнал, гейты и очередь за слотом остаются на
    месте: иначе мы мерили бы другую книгу, а не ту же книгу под нулём.

    **Пул перестановки — ноги, которые кто-то из живых кандидатов
    берёт, а не всё сечение,** и это не то же самое, что нуль 1 в R3
    (там перемешивалось сечение целиком). Различие названо, а не
    сглажено: здешний нуль спрашивает «добавляет ли ОТБОР внутри
    допущенных», и гейт им не проверяется вовсе — гейт есть часть
    правила и проверяется контрольной рукой, которая тянет из
    пространства целиком.
    """
    by_hour = {}
    for lg in legs:
        by_hour.setdefault((lg["at"], lg["arm"]), []).append(lg)
    out = []
    for s in range(seeds):
        rnd = random.Random(1000003 + s)
        remap = {}
        for group in by_hour.values():
            ids = [g["id"] for g in group]
            shuffled = ids[:]
            rnd.shuffle(shuffled)
            remap.update(dict(zip(ids, shuffled)))
        shifted = {}
        for (lid, st, tk, ag), got in outs.items():
            src = remap.get(lid)
            if src is not None:
                shifted[(src, st, tk, ag)] = got
        tr = CD.simulate(legs, shifted, CD.with_geometry(rule))
        out.append(CD.daily_net(tr))
    return out


def null_median(nulls, now, window_d=PL.WINDOW_D):
    """Медиана нуля за окно вылета — то число, с которым сравнивается
    кандидат. Одно на группу, а не на книгу."""
    vals = []
    for d in nulls:
        net, _n = PL.window_net(d, now, window_d)
        vals.append(net)
    if not vals:
        return 0.0
    vals.sort()
    n = len(vals)
    return (vals[n // 2] if n % 2 else
            0.5 * (vals[n // 2 - 1] + vals[n // 2]))


# --- отчёт -----------------------------------------------------------

def _med(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def verdict(sel, ctl, n_days):
    """Фраза вердикта ВЫВОДИТСЯ из чисел, а не стоит рядом с ними.

    Проза, утверждающая своё, однажды разойдётся с таблицей — это уже
    случалось в отчёте о цене прохода лесенки, где вывод стоял
    литералом и противоречил собственному числу отчёта.
    """
    if not sel or not ctl:
        have = "отобранных" if not sel else "случайных"
        return (f"вердикта нет: {have} книг в пуле ещё нет — фабрика "
                f"судится ПАРНЫМ сравнением полос, и одной полосой оно "
                f"не считается")
    if n_days < 90:
        return (f"вердикта нет: календаря {n_days} суток при требуемых 90 "
                f"(§9) — числа ниже суть диагностика, а не результат")
    ms, mc = _med(sel), _med(ctl)
    if ms is None or mc is None:
        return "вердикта нет: полосы пусты"
    if ms <= mc:
        return (f"фабрика закрывается: медиана отобранных {ms:+.1f} б.п. "
                f"не бьёт случайных {mc:+.1f} — правило отбора не "
                f"работает (§9)")
    return (f"отобранные впереди случайных: {ms:+.1f} против {mc:+.1f} "
            f"б.п. — предъявлять можно только вместе с числом испытаний")


def write_report(path, meta, cands, st, nulls_med, log=print, pending=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sp = LG.spent(st)
    sel = [c for c in cands.values() if c["lane"] == "selected"]
    ctl = [c for c in cands.values() if c["lane"] == "control"]
    sel_net = [sum(c["daily"].values()) for c in sel]
    ctl_net = [sum(c["daily"].values()) for c in ctl]
    days = sorted({d for c in cands.values() for d in c["daily"]})
    n_days = len(days)
    series = {cid: c["daily"] for cid, c in cands.items()}
    n_eff, mean_r = LG.effective_n(series)
    L = []
    L.append("# Фабрика гипотез — суточный прогон\n")
    L.append(f"Прогон {meta['at']} · ног {meta['legs']} · "
             f"кандидатов в пуле {sp['active']}\n")
    L.append(f"**{verdict(sel_net, ctl_net, n_days)}**\n")
    L.append("## Испытания\n")
    L.append("| величина | число |")
    L.append("|---|--:|")
    L.append(f"| объявлено всего | {sp['total']} |")
    L.append(f"| живых | {sp['active']} |")
    L.append(f"| вылетело | {sp['retired']} |")
    L.append(f"| отобранных живых | {sp['selected_active']} |")
    L.append(f"| случайных живых | {sp['control_active']} |")
    L.append(f"| эффективное N | {n_eff:.1f} |")
    L.append(f"| средняя связь дневных денег | {mean_r:+.3f} |")
    L.append(f"| пространство объявлено | {SP.TOTAL} |")
    L.append(f"| из него исполнимо сегодня | {SP.available_total()} |")
    rec = meta.get("record_days")
    L.append(f"| суток записи в журнале листов | "
             f"{'—' if rec is None else rec} |")
    L.append(f"| суток со сделками хоть у кого-то | {n_days} |")
    L.append("")
    L.append("Суток ЗАПИСИ и суток со сделками — разные числа, и путать "
             "их нельзя: второе есть функция от того, сколько книги "
             "наторговали, и знаменателем измеримости служить не может. "
             "Дневной ряд книги заводит день только от закрытой сделки, "
             "то есть суток у неё никогда не больше, чем сделок.\n")
    L.append("Эффективное `N` меряется, а не считается номинально: "
             "параметрические соседи — почти одна ставка, и сто книг со "
             "связью 0.9 несут информации меньше десяти независимых.\n")
    L.append("## Полосы против нуля\n")
    L.append("| полоса | книг | медиана нетто | максимум | минимум |")
    L.append("|---|--:|--:|--:|--:|")
    for name, arr in (("отобранные", sel_net), ("случайные", ctl_net)):
        if arr:
            L.append(f"| {name} | {len(arr)} | {_med(arr):+.1f} | "
                     f"{max(arr):+.1f} | {min(arr):+.1f} |")
        else:
            L.append(f"| {name} | 0 | — | — | — |")
    L.append(f"| нуль (медиана {NULL_SEEDS} зёрен) | — | "
             f"{nulls_med:+.1f} | — | — |")
    L.append("")
    L.append("Нуль переставляет «нога → исход» ВНУТРИ часа среди ног, "
             "допущенных гейтами живых кандидатов: он спрашивает, "
             "добавляет ли отбор внутри допущенных. Сам гейт им не "
             "проверяется — это часть правила, и её проверяет "
             "контрольная рука, тянущая из пространства целиком.")
    L.append("")
    L.append("**Максимум случайной полосы и есть эмпирический «лучший "
             "из N» под нулём** — теории не нужно. Топ книг без этой "
             "строки не печатается никогда: он и есть генератор ошибки "
             "R5 в виде таблицы.\n")
    if cands:
        L.append("## Кандидаты\n")
        L.append("| ключ | полоса | сделок | дней | форвард | до объявл. "
                 "| нетто | правило |")
        L.append("|---|---|--:|--:|--:|--:|--:|---|")
        for cid, c in sorted(cands.items(),
                             key=lambda kv: -sum(kv[1]["daily"].values())):
            fwd, pre = PL.split_forward(c["daily"], c.get("declared_at"))
            L.append(f"| `{cid}` | {c['lane']} | {c['trades']} | "
                     f"{len(c['daily'])} | "
                     f"{sum(fwd.values()):+.1f} ({len(fwd)}) | "
                     f"{sum(pre.values()):+.1f} ({len(pre)}) | "
                     f"{sum(c['daily'].values()):+.1f} | "
                     f"{SP.describe(c['rule'])} |")
        L.append("")
        L.append("**Колонка «нетто» складывает форвард с реплеем по "
                 "прошлому, и предъявлять её как результат нельзя.** "
                 "Кандидат реплеится по всему журналу листов, а вперёд "
                 "торгует только со дня объявления; до этого дня ряд "
                 "есть пересчёт по прошлому, которое ассистент видел, "
                 "когда предлагал. Правило вылета этим не задето — оно "
                 "не судит книгу, пока ей меньше "
                 f"{PL.WINDOW_D} суток, то есть судит уже по форварду. "
                 "Полосы выше считаны по полному ряду и потому суть "
                 "диагностика, а не сравнение полос.\n")
    if pending:
        L.append("## Заявка на рассмотрении потолка\n")
        L.append(f"`{pending['key']}` — сделок {pending['trades']}, "
                 f"суток {len(pending['daily'])}. "
                 f"{SP.describe(pending['rule'])}\n")
        L.append("Это НЕ объявление: заявка испытанием не стала, в число "
                 "потраченных не входит и в реестр не пишется. Числа "
                 "здесь существуют затем, чтобы потолок ответил, можно "
                 "ли её вообще измерить, — и по доходности он её не "
                 "судит.\n")
    if meta.get("retired"):
        L.append("## Вылетели этим прогоном\n")
        for cid, why in meta["retired"]:
            L.append(f"- `{cid}` — {why}")
        L.append("")
    L.append("Ретро-прогон по записи вердиктом НЕ является: кандидат "
             "судится на данных, которых в момент его объявления не "
             "существовало (§2 полоса 3). Числа выше — диагностика "
             "полосы 2.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    log(f"отчёт: {path}")
    # Сводка возвращается ЧИСЛАМИ и уезжает в json рядом с отчётом:
    # страница наблюдения обязана читать величины, а не разбирать
    # прозу отчёта — разбор прозы стареет молча при первой же правке
    # формулировки.
    return {"spent": sp, "eff_n": round(n_eff, 2),
            "mean_r": round(mean_r, 4), "days": n_days,
            "record_days": meta.get("record_days"),
            "verdict": verdict(sel_net, ctl_net, n_days),
            "null_median": nulls_med}


def publish(path, log=print, msg="фабрика: суточный прогон"):
    """Публикация — часть прогона, а не отдельный шаг: шаг, который
    можно забыть, рано или поздно забывают (урок D1).

    `publish.sh` берёт СООБЩЕНИЕ и сам публикует `research/*/out` —
    отсюда и место реестра: он лежит в `out`, иначе запись испытаний
    осталась бы на сервере, а знаменатель фабрики существует только
    пока его видно.
    """
    try:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), msg],
                       cwd=ROOT, check=False, timeout=600)
    except Exception as e:                                # noqa: BLE001
        log(f"публикация не удалась: {type(e).__name__}: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", default=os.path.join(
        RESEARCH, "s8_loop", "out", "model_sit", "sheets.jsonl"))
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--base", default=OUT)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--proposal", default=None,
                    help="заявка предлагающего (по умолчанию "
                         "<out>/proposal.json)")
    ap.add_argument("--no-declare", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    now = time.time()
    log = print
    seed = a.seed if a.seed is not None else int(now // DAY)
    declared = []
    if not a.no_declare:
        declared = declare_today(a.base, now, seed, log=log)
        log(f"объявлено: {len(declared)} "
            f"({sum(1 for _k, l in declared if l == 'control')} случайных)")
    st = LG.state(LG.read(a.base)[0])
    if not LG.active(st):
        log("живых кандидатов нет — прогонять нечего")
    legs = load_legs(a.sheets, log=log)
    log(f"ног из журнала листов: {len(legs)}")
    rules = [CD.with_geometry(v["rule"]) for v in LG.active(st).values()
             if v.get("rule") and not SP.validate(v["rule"])]
    pend_rule, pend_why = pending_rule(
        st, a.proposal or os.path.join(a.out, PROPOSAL_NAME))
    log(f"заявка: {SP.key(pend_rule) if pend_rule else pend_why}")
    # Гейты заявки могут быть шире гейтов живых, и без её правила
    # `needed_legs` отсекла бы её собственные ноги — заявка вышла бы
    # мёртвой по числу сделок не потому, что мертва, а потому, что её
    # ног не оценивали. Потолок закрыл бы её этим числом молча.
    if pend_rule is not None:
        rules.append(CD.with_geometry(pend_rule))
    # Длина записи меряется ДО гейтов: после `needed_legs` в журнале
    # остаются только ноги, которые кто-то берёт, и знаменатель
    # измеримости стал бы функцией от гейтов самого кандидата.
    rec_days = record_days(legs)
    legs = needed_legs(legs, rules, log=log)
    log(f"суток записи в журнале листов: {rec_days}")
    outs = outcomes_for(legs, a.root, geometries(), log=log) if legs else {}
    log(f"исходов посчитано: {len(outs)}")
    if legs and not outs:
        # Ноль исходов при непустых ногах означает, что сломано чтение
        # баров, а не что рынок молчал. Первый живой прогон отчитался
        # кодом 0 и пустым отчётом ровно так: имя модуля перекрыло
        # чужое, загрузчик падал на каждом символе, а снаружи это
        # выглядело исправной фабрикой без сделок.
        log("исходов нет ни у одной ноги — чтение баров сломано; "
            "отчёт не пишется, чтобы пустота не выдала себя за прогон")
        return 1
    cands = run_candidates(st, legs, outs, log=log) if outs else {}
    pending = (run_pending(pend_rule, legs, outs)
               if pend_rule is not None and outs else None)
    if pending:
        log(f"заявка прогнана: сделок {pending['trades']}, суток "
            f"{len(pending['daily'])} — объявлением это НЕ является")
    # Нуль общий для группы: одно сечение и один форвард на всех.
    base_rule = None
    for c in cands.values():
        base_rule = c["rule"]
        break
    nulls = (null_daily(legs, outs, base_rule) if base_rule and outs
             else [])
    nmed = null_median(nulls, now) if nulls else 0.0
    retired = []
    if cands:
        daily_by_id = {cid: c["daily"] for cid, c in cands.items()}
        for cid, why in PL.sweep(st, daily_by_id, now, nmed):
            if LG.retire(cid, why, at=now, base=a.base) is None:
                retired.append((cid, why))
        if retired:
            log(f"вылетело: {len(retired)}")
    st = LG.state(LG.read(a.base)[0])
    meta = {"at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now)),
            "legs": len(legs), "record_days": rec_days,
            "declared": declared, "retired": retired}
    path = os.path.join(a.out, f"FACTORY-day-{a.tag}.md")
    summary = write_report(path, meta, cands, st, nmed, log=log,
                           pending=pending)
    with open(os.path.join(a.out, f"factory-day-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        # Дневной ряд едет в артефакт целиком: потолок мерит СВЯЗЬ
        # дневных денег, и по одному итогу её не посчитать. Ключ дня —
        # число, JSON превратит его в строку, и читатель обязан вернуть
        # обратно (иначе ряды не пересекутся ни одним днём).
        json.dump({"meta": meta,
                   "summary": summary,
                   "null_median": nmed,
                   "pending": pending,
                   "pending_why": pend_why,
                   "candidates": {k: {"lane": v["lane"],
                                      "trades": v["trades"],
                                      "net": sum(v["daily"].values()),
                                      "daily": v["daily"],
                                      "last": v.get("last") or [],
                                      "declared_at": v.get("declared_at"),
                                      "note": v.get("note"),
                                      "rule": v["rule"]}
                                  for k, v in cands.items()}},
                  f, ensure_ascii=False, indent=1)
    if not a.no_publish:
        publish(path, log=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
