"""Проверки реестра и пространства фабрики.

Главное здесь — не поведение функций, а два числа, которые обязаны
быть неподвижны: размер объявленного пространства (знаменатель всех
чисел фабрики) и воспроизводимость жребия контрольной руки. Первое
меняется только событием (§10 спеки), второе — никогда: нуль, который
нельзя повторить, не является проверяемым.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agents as AG  # noqa: E402
import runlog as RL  # noqa: E402
import ledger as L   # noqa: E402
import space as S    # noqa: E402

FAILED = []


def check(name, ok, got=""):
    print(("  ok   " if ok else "  ПРОВАЛ ") + name
          + ("" if ok else f" — {got}"))
    if not ok:
        FAILED.append(name)


# Снимок пространства на день объявления. Числа ЛИТЕРАЛАМИ: формула от
# самих осей была бы тавтологией и не заметила бы снятого значения.
AXES_SNAPSHOT = (
    ("target", ("fwd_4h", "fwd_24h")),
    ("rank", ("raw", "sigma")),
    ("floor_bp", (0, 22, 30, 44)),
    ("width", (3, 5, 10)),
    ("geom", ("timer", "stop_take", "levels")),
    ("rr_band", ("none", "lo", "hi")),
    ("sizing", ("equal", "risk", "inv_sigma")),
    ("basket", ("no", "whole")),
    ("agree", ("no", "yes")),
)


def test_space_is_declared_and_frozen():
    check("пространство ровно 5184 сочетания", S.TOTAL == 5184, str(S.TOTAL))
    check("оси и значения как объявлены", S.AXES == AXES_SNAPSHOT,
          str(S.AXES))
    keys = {S.key(S.index_to_rule(i)) for i in range(S.TOTAL)}
    check("у каждого сочетания свой ключ", len(keys) == S.TOTAL,
          f"{len(keys)} ключей на {S.TOTAL} сочетаний")
    ch = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    bad = [k for k in keys if set(k) - ch]
    check("ключ годится для адреса и пути", not bad, str(bad[:3]))


def test_validate_bites_on_both_sides():
    good = S.index_to_rule(0)
    check("годное правило принято", S.validate(good) is None,
          str(S.validate(good)))
    miss = dict(good)
    miss.pop("sizing")
    check("пропущенная ось отвергнута", S.validate(miss) is not None)
    extra = dict(good, whatever=1)
    check("лишняя ось отвергнута", S.validate(extra) is not None)
    wrong = dict(good, width=7)
    check("необъявленное значение отвергнуто",
          S.validate(wrong) is not None)


def test_draw_is_reproducible_and_random():
    a = [S.key(r) for r in S.draw(777, 25)]
    b = [S.key(r) for r in S.draw(777, 25)]
    check("тот же номер зерна — тот же жребий", a == b, str(a[:2]))
    c = [S.key(r) for r in S.draw(778, 25)]
    # Иначе «случайная» рука не случайна: зерно ничего не решает, и
    # контроль сравнивал бы отобранных с одним и тем же набором.
    check("другое зерно — другой жребий", a != c, "жребий не зависит от зерна")
    check("повторов в жребии нет", len(set(a)) == len(a))
    ex = a[:5]
    d = [S.key(r) for r in S.draw(777, 5, exclude=ex)]
    check("занятые ключи не выпадают", not (set(d) & set(ex)), str(d))
    check("жребий берёт только исполнимое",
          all(S.unavailable(r) is None for r in S.draw(777, 40)))


def test_unavailable_is_named_by_number():
    # Половина пространства сегодня не исполнима, и это надо говорить
    # числом: «кандидатов нет» и «кандидаты невозможны» снаружи
    # неотличимы.
    # Четверть: горизонт 24 ч не лежит в листе, корзина требует пути
    # открытых ног. Обе причины снимаются кодом, и до тех пор число
    # обязано стоять рядом с любым числом фабрики.
    check("исполнима ровно четверть", S.available_total() == 1296,
          str(S.available_total()))
    r24 = dict(S.index_to_rule(0), target="fwd_24h", basket="no")
    why = S.unavailable(r24)
    check("причина по горизонту названа словами",
          bool(why) and "лист" in why, str(why))
    bk = dict(r24, target="fwd_4h", basket="whole")
    why = S.unavailable(bk)
    check("причина по корзине названа словами",
          bool(why) and "корзина" in why, str(why))
    check("исполнимое правило проходит",
          S.unavailable(dict(bk, basket="no")) is None)


def test_describe_names_every_axis():
    r = {"target": "fwd_24h", "rank": "sigma", "floor_bp": 30, "width": 5,
         "geom": "levels", "rr_band": "lo", "sizing": "risk",
         "basket": "whole", "agree": "yes"}
    t = S.describe(r)
    for must in ("24 ч", "σ", "30", "5+5", "уровни", "1.5", "риск",
                 "целиком", "согласн"):
        check(f"объяснение несёт «{must}»", must in t, t)


def test_ledger_is_a_journal_not_a_table():
    d = tempfile.mkdtemp()
    r1, r2 = S.index_to_rule(3), S.index_to_rule(9)
    k1, k2 = S.key(r1), S.key(r2)
    check("объявление принято",
          L.declare(k1, r1, "selected", seed=1, at=100.0, base=d) is None)
    check("дубль отвергнут",
          L.declare(k1, r1, "selected", at=101.0, base=d) is not None)
    check("необъявленная полоса отвергнута",
          L.declare(k2, r2, "whatever", at=101.0, base=d) is not None)
    L.declare(k2, r2, "control", seed=777, at=102.0, base=d)
    st = L.state(L.read(d)[0])
    check("момент объявления сохранён дословно",
          st[k1]["declared_at"] == 100.0, str(st[k1]))
    check("вылет неизвестного отвергнут",
          L.retire("нет-такого", "x", base=d) is not None)
    check("вылет записан",
          L.retire(k1, "ниже медианы нуля", at=200.0, base=d) is None)
    check("повторный вылет отвергнут",
          L.retire(k1, "x", base=d) is not None)
    st = L.state(L.read(d)[0])
    sp = L.spent(st)
    check("испытание вылетом не возвращается",
          sp["total"] == 2 and sp["retired"] == 1 and sp["active"] == 1,
          str(sp))
    check("полосы считаются врозь",
          sp["selected"] == 1 and sp["control"] == 1
          and sp["control_active"] == 1, str(sp))
    check("причина вылета сохранена",
          st[k1]["why"] == "ниже медианы нуля", str(st[k1]))


def test_broken_line_is_counted_not_swallowed():
    d = tempfile.mkdtemp()
    r = S.index_to_rule(5)
    L.declare(S.key(r), r, "selected", at=1.0, base=d)
    with open(L.path(d), "a", encoding="utf-8") as f:
        f.write("{это не json\n")
        f.write(json.dumps({"ev": "странное", "id": "x"}) + "\n")
    rows, bad = L.read(d)
    check("битые строки посчитаны", bad == 2, str(bad))
    check("годная строка уцелела", len(rows) == 1, str(rows))


def test_effective_n_is_measured():
    same = {"a": {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0},
            "b": {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0},
            "c": {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}}
    n_eff, r = L.effective_n(same)
    check("три одинаковых книги — одно испытание", n_eff < 1.05,
          f"{n_eff:.2f} при связи {r:.2f}")
    ind = {"a": {1: 1.0, 2: -1.0, 3: 2.0, 4: -2.0},
           "b": {1: -1.0, 2: 1.0, 3: -2.0, 4: 2.0}}
    n_eff, r = L.effective_n(ind)
    check("несвязанные книги — своё число", n_eff >= 1.9,
          f"{n_eff:.2f} при связи {r:.2f}")


def test_agents_registry_is_one_source_and_complete():
    """Реестр автономной системы: один источник и полон на двух языках.

    Реестр читает страница, а позже будет читать запускалка ролей —
    она соберёт промпт из той же записи, которой страница объясняет
    владельцу, что этот агент делает. Значит ломаться реестр обязан
    громко: потерянный перевод дал бы страницу с английским абзацем
    среди русских, а `proof` мимо репозитория — вечное «не построен»
    у построенного шага.
    """
    keys = [x["key"] for x in AG.pipeline()]
    check("ключи шагов уникальны", len(keys) == len(set(keys)),
          str(keys))
    check("вид шага только role или mech",
          all(x["kind"] in ("role", "mech") for x in AG.pipeline()))
    check("роли и механика вместе дают весь конвейер",
          len(AG.roles()) + len(AG.mech()) == len(AG.pipeline()))
    check("у роли назван класс модели",
          all((x.get("model") or "").strip() for x in AG.roles()))
    check("оба языка на месте", AG.missing_translations() == [],
          str(AG.missing_translations()))
    root = os.path.dirname(HERE)
    root = os.path.dirname(root)
    bad = [x["key"] for x in AG.pipeline()
           if not x.get("proof")
           or os.path.isabs(x["proof"])
           or ".." in x["proof"].split("/")]
    check("путь-доказательство относительный и без выхода вверх",
          not bad, str(bad))
    # Хотя бы один шаг обязан быть построен и хотя бы один нет: реестр,
    # у которого всё построено, ничего не проверяет, а реестр, у
    # которого не построено ничего, означает потерянные пути.
    ex = [os.path.exists(os.path.join(root, x["proof"]))
          for x in AG.pipeline()]
    check("пути-доказательства ведут в репозиторий", any(ex), str(root))
    check("по каждому шагу известно, чем он ограничен",
          all((x.get("forbid") or "").strip() and (x.get("doubt") or "")
              for x in AG.pipeline()))
    # Модель и усилие — НАСТРОЙКА роли, а не умолчание среды. Прежде
    # запускалка не передавала ни того, ни другого: роли шли на том,
    # что стоит у CLI, и смена умолчания изменила бы поведение молча.
    for st in AG.roles():
        m, e = AG.model_of(st["key"]), AG.effort_of(st["key"])
        check(f"у роли {st['key']} объявлена модель и усилие",
              bool(m) and e in ("low", "medium", "high", "xhigh", "max"),
              f"{m}/{e}")
    check("механический шаг модели не требует",
          all(not (x.get("model_id") or "") for x in AG.mech()))
    check("границы и отказы не пусты",
          len(AG.BOUNDARIES) >= 3 and len(AG.RISKS) >= 3)
    # Инвариант, найденный первым боевым прогоном: роль, которая
    # обязана оставить файл, обязана иметь право его написать. Иначе
    # прогон уходит в обход и тратит время на борьбу с харнессом.
    for st in AG.roles():
        if st.get("produces"):
            t = AG.tools(st["key"])
            check(f"роль {st['key']} умеет писать то, что производит",
                  "Write" in t, str(t))
    # Права — списком, а не режимом «разрешить всё»: граница взрыва у
    # автономной сессии держится правами.
    check("ни одна роль не просит обхода проверок",
          all("bypass" not in x.lower()
              for st in AG.roles() for x in AG.tools(st["key"])))


def test_run_log_counts_every_wake_up():
    """Журнал прогонов: тишина запрещена, сухой прогон не работа.

    Остановившаяся запускалка выглядит ровно как спокойный день —
    это самый дешёвый отказ из всех, и ловится он только тем, что
    КАЖДОЕ пробуждение оставляет строку, включая отказ.

    Сухой прогон модель не зовёт вовсе, поэтому засчитывать его за
    работу роли значило бы объявить построенным то, что ни разу не
    работало.
    """
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "runs.jsonl")
        RL.append(p, "brief", "ok", 100.0, ended=101.0, dry=True)
        RL.append(p, "brief", "no-key", 200.0, ended=200.5,
                  note="ключа API нет")
        RL.append(p, "propose", "ok", 300.0, ended=340.0)
        rows, broken = RL.read(p)
        check("строк столько же, сколько пробуждений", len(rows) == 3,
              str(len(rows)))
        check("битых нет", broken == 0)
        check("сухой прогон не считается работой роли",
              RL.ok_runs(rows) == {"propose"}, str(RL.ok_runs(rows)))
        last = RL.last_by_role(rows)
        check("последний прогон роли — по времени, а не по порядку",
              last["brief"]["status"] == "no-key", str(last["brief"]))
        with open(p, "a", encoding="utf-8") as f:
            f.write("{обрыв записи\n")
        rows, broken = RL.read(p)
        check("битая строка сосчитана, а не проглочена",
              broken == 1 and len(rows) == 3, f"{broken}/{len(rows)}")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_running_now_is_a_separate_question():
    """«Работает сейчас» и «последний прогон» — разные вопросы.

    Просьба владельца: нажав на агента, видеть, работает ли он прямо
    сейчас. Склеив это с последним прогоном, страница показывала бы
    старый отказ во время исправной работы.

    Оборванный прогон (строка `start`, чей процесс мёртв) идущим НЕ
    считается: иначе убитая роль вечно выглядела бы работающей —
    тревога, которой нет, хуже её отсутствия.
    """
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "runs.jsonl")
        RL.append(p, "brief", "start", 100.0, pid=os.getpid())
        rows, _ = RL.read(p)
        st = RL.state_of(rows)["brief"]
        check("идущий прогон виден", st["running"] is not None)
        check("законченного прогона ещё нет", st["last"] is None)

        RL.append(p, "brief", "ok", 100.0, ended=160.0)
        rows, _ = RL.read(p)
        st = RL.state_of(rows)["brief"]
        check("после конца прогон не идёт", st["running"] is None)
        check("последний прогон — законченный",
              st["last"] and st["last"]["status"] == "ok")

        # Мёртвый номер процесса: прогон оборван, а не идёт.
        RL.append(p, "brief", "start", 200.0, pid=2 ** 22 + 7)
        rows, _ = RL.read(p)
        st = RL.state_of(rows)["brief"]
        check("мёртвый процесс не считается идущим",
              st["running"] is None, str(st["running"]))
        check("оборванный прогон назван отдельно",
              st["broken"] is not None)

        hist = RL.history(rows, "brief")
        check("в истории все строки, включая отказы",
              len(hist) == 3, str(len(hist)))
        check("история новыми сверху",
              (hist[0].get("at") or 0) >= (hist[-1].get("at") or 0))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_brief_contract_is_mechanical():
    """Контракт брифа проверяет машина, и проверяет ровно проверяемое.

    Главный отказ схемы — агенты пишут друг другу правдоподобный
    текст, и он становится фактом без сверки с данными. Просить
    модель проверить себя бесполезно. Машина умеет две вещи: посчитать
    размер и убедиться, что названные файлы существуют. Бриф,
    сославшийся на несуществующий файл, есть выдумка, пойманная без
    читателя.
    """
    root = os.path.dirname(HERE)
    root = os.path.dirname(root)
    good = ("- гипотеза закрыта хвостом "
            "(research/f3_nulls/out/F3-report-1m.md)\n"
            "- пул и вылет: research/factory/pool.py\n"
            "- публикация: tools/publish.sh\n")
    ok, why, got = RL.check_brief(good, root)
    check("годный бриф проходит", ok, str(why))
    check("указатели найдены", len(got) == 3, str(got))

    ok, why, _ = RL.check_brief(good.replace(
        "research/factory/pool.py", "research/factory/nosuch.py"), root)
    check("выдуманный файл ловится машиной", not ok
          and any("несуществующ" in w for w in why), str(why))

    ok, why, _ = RL.check_brief("возврат работает, модель стала лучше",
                                root)
    check("бриф без указателей отвергается", not ok
          and any("указател" in w for w in why), str(why))

    ok, why, _ = RL.check_brief(good + "x" * RL.BRIEF_BUDGET_CHARS, root)
    check("потолок размера кусается", not ok
          and any("потолк" in w for w in why), str(why))

    ok, why, _ = RL.check_brief("", root)
    check("пустой бриф не годен", not ok, str(why))

    # Дефект, найденный ПЕРВЫМ БОЕВЫМ прогоном роли: альтернация в
    # питоне берёт первое совпадение, а не самое длинное, и при
    # порядке «json | jsonl» путь `ledger.jsonl` обрезался до
    # несуществующего `ledger.json` — бриф объявлялся выдумкой целиком.
    # Практически это запрещало ролям ссылаться ровно на два файла,
    # которые описывают состояние фабрики.
    got = RL.cites("см. research/factory/out/ledger.jsonl и "
                   "research/factory/out/agents-runs.jsonl")
    check("путь с расширением jsonl не обрезается",
          got == ["research/factory/out/ledger.jsonl",
                  "research/factory/out/agents-runs.jsonl"], str(got))
    check("расширение внутри слова указателем не считается",
          RL.cites("y.jsonlx") == [], str(RL.cites("y.jsonlx")))


def test_proposal_must_be_checkable_not_persuasive():
    """Заявка на испытание проверяется машиной по форме, не по красоте.

    Каждое объявленное испытание тратит бюджет доказательства: оно
    ухудшает поправку всем остальным и занимает слот на месяцы, потому
    что вердикт выносится только вперёд. Поэтому форма жёсткая — что
    утверждается, чем убивается, каким дешёвым расчётом закрывается,
    чем отличается от живых, — а красноречие ничего не стоит.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    long = "x" * 200
    rule = {"target": "fwd_4h", "rank": "sigma", "floor_bp": 30,
            "width": 5, "geom": "levels", "rr_band": "lo",
            "sizing": "equal", "basket": "no", "agree": "no"}
    good = {"proposed": True, "kind": "row", "title": "проба",
            "hypothesis": long, "kills_it": long, "ceiling": long,
            "differs_from_live": long,
            "cites": ["research/factory/out/brief.md",
                      "research/factory/space.py",
                      "research/factory/pool.py"],
            "rule": rule}

    def chk(d, ids=()):
        return RL.check_proposal(json.dumps(d, ensure_ascii=False), root,
                                 ledger_ids=ids, space=S)

    ok, why = chk(good)
    # Бриф на диске песочницы может отсутствовать — тогда годной
    # заявка быть и не должна, и это тоже верное поведение.
    if os.path.exists(os.path.join(root, RL.BRIEF_PATH)):
        check("годная заявка проходит", ok, str(why))
    else:
        check("без брифа заявка не годна", not ok, str(why))

    ok, why = chk(dict(good, rule=dict(rule, width=7)))
    check("значение вне объявленного пространства отвергнуто",
          not ok and any("пространств" in w for w in why), str(why))

    ok, why = chk(dict(good, rule={k: v for k, v in rule.items()
                                   if k != "agree"}))
    check("пропущенная ось отвергнута",
          not ok and any("нет оси" in w for w in why), str(why))

    ok, why = chk(good, ids=[S.key(rule)])
    check("повтор уже объявленного отвергнут",
          not ok and any("уже объявлен" in w for w in why), str(why))

    ok, why = chk(dict(good, hypothesis="коротко"))
    check("заявка без содержания отвергнута",
          not ok and any("hypothesis" in w for w in why), str(why))

    # Голое имя файла указателем не считается: первый прогон
    # предлагающего был отвергнут за три упоминания в прозе, каждое из
    # которых было верным, — «candidate.py:186» не говорит, какой из
    # десятка одноимённых файлов имеется в виду.
    check("голое имя файла не указатель",
          RL.cites("см. candidate.py и FACTORY-day-1m.md") == [],
          str(RL.cites("см. candidate.py и FACTORY-day-1m.md")))
    # Проза не сканируется: путь в ней бывает назван затем, чтобы
    # сказать «его ещё нет», и такое утверждение полезно.
    # Путь взят ЗАВЕДОМО НЕСУЩЕСТВУЮЩИЙ навсегда. Первая версия
    # использовала `research/factory/ceiling.py` — файл, который
    # заданием велено было создать; строитель его создал, и фикстура
    # протухла. Нашёл это он же и чинить отказался: ослаблять чужую
    # проверку ради своей нельзя.
    gone = "research/factory/_never_exists_probe.py"
    ok, why = chk(dict(good, ceiling=good["ceiling"]
                       + f" шага {gone} пока нет"))
    check("отсутствующий путь в прозе заявку не валит", ok, str(why))
    ok, why = chk(dict(good, cites=good["cites"] + [gone]))
    check("отсутствующий путь в cites заявку валит",
          not ok and any("cites" in w for w in why), str(why))

    ok, why = chk(dict(good, cites=["research/factory/space.py",
                                    "research/factory/pool.py",
                                    "research/factory/ledger.py"]))
    check("заявка без ссылки на бриф отвергнута",
          not ok and any("brief.md" in w for w in why), str(why))

    ok, why = chk(dict(good, kind="mechanism", rule=None))
    check("механизм без названного шага отвергнут",
          not ok and any("шага конвейера" in w for w in why), str(why))

    ok, why = chk({"proposed": False, "why": "коротко"})
    check("пустой день без обоснования отвергнут",
          not ok and any("не обоснован" in w for w in why), str(why))
    ok, why = chk({"proposed": False, "why": "п" * 150})
    check("обоснованный пустой день — законный ответ", ok, str(why))
    ok, why = RL.check_proposal("не json", root, space=S)
    check("неразбираемая заявка отвергнута", not ok, str(why))


def test_prompt_actually_reaches_the_model():
    """Промпт обязан ДОЙТИ до модели, а не потеряться в аргументах.

    Первый прогон предлагающего умер ровно так: `--allowedTools` берёт
    список переменной длины и, стоя перед промптом, проглотил его
    целиком — слова промпта стали «правилами доступа», а модель
    осталась без задания. Отказ был громким, но слот и время сгорели.

    Гоняется настоящий скрипт с подставным `claude`, который
    записывает, сколько байт получил на вход. Роль взята та, чей
    продукт в репозитории отсутствует, — тогда прогон останавливается
    на контракте и не доходит до публикации.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sh = os.path.join(root, "tools", "agents_run.sh")
    d = tempfile.mkdtemp()
    try:
        bin_d = os.path.join(d, "bin")
        os.makedirs(bin_d)
        seen = os.path.join(d, "seen.txt")
        with open(os.path.join(bin_d, "claude"), "w",
                  encoding="utf-8") as f:
            f.write('#!/bin/sh\n'
                    'if [ "$1" = "auth" ]; then\n'
                    '  echo \'{ "loggedIn": true }\'\n'
                    '  exit 0\n'
                    'fi\n'
                    'wc -c > "%s"\n'
                    'echo "подставная модель отработала"\n' % seen)
        os.chmod(os.path.join(bin_d, "claude"), 0o755)
        env = dict(os.environ, AGENTS_OUT=d, AGENTS_NO_PUBLISH="1",
                   PATH=bin_d + os.pathsep + os.environ.get("PATH", ""))
        env.pop("ANTHROPIC_API_KEY", None)
        # stdin ЗАКРЫТ намеренно: при сломанной форме вызова
        # подставная модель ждала бы ввода вечно, и контроль вешал бы
        # проверку вместо того, чтобы её ронять. Закрытый вход
        # превращает поломку в ноль байт, то есть в честный провал.
        try:
            r = subprocess.run([sh, "propose"], cwd=root, env=env,
                               capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=120)
        except subprocess.TimeoutExpired:
            check("прогон роли не зависает", False, "120 с")
            return
        got = 0
        if os.path.exists(seen):
            with open(seen, encoding="utf-8") as f:
                got = int((f.read() or "0").strip() or 0)
        check("промпт дошёл до модели целиком", got > 2000, str(got))
        # Чем кончился прогон, здесь не предмет: продукт роли может
        # уже лежать в репозитории от настоящего прогона, и тогда
        # контракт законно проходит. Предмет — дошёл ли промпт и
        # оставил ли прогон след.
        check("вердикт контракта вынесен", "КОНТРАКТ" in r.stdout,
              r.stdout[-300:])
        rows, _ = RL.read(os.path.join(d, RL.RUNS))
        got_st = [x["status"] for x in rows]
        check("в журнале начало и терминальная строка",
              len(got_st) == 2 and got_st[0] == "start"
              and got_st[1] in ("ok", "contract"), str(got_st))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_build_contract_makes_the_controls_bite():
    """Главное в постройке — не «тесты зелёные», а кусаются ли контроли.

    Проверка, которая не кусается, не проверяет ничего, и таких в этом
    проекте находили десятками. Поэтому каждая подделка применяется к
    файлу, тесты прогоняются заново и ОБЯЗАНЫ упасть; контроль, не
    укусивший, валит весь прогон — то есть отчёт «построено» без
    кусающихся контролей получить нельзя.

    Гоняется настоящий механизм на временных файлах в том же каталоге:
    подделка чужого файла запрещена самим контрактом, и проверять это
    надо там, где запрет действует.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    mod = "research/factory/_tmp_probe.py"
    tst = "research/factory/_tmp_test_probe.py"
    rule = "    if x < 0:\n        return None"
    try:
        with open(os.path.join(root, mod), "w", encoding="utf-8") as f:
            f.write("def measure(x):\n"
                    "    # правило: отрицательное — не наблюдение\n"
                    + rule + "\n"
                    "    return x * 2\n")
        with open(os.path.join(root, tst), "w", encoding="utf-8") as f:
            f.write("import os, sys\n"
                    "sys.path.insert(0, os.path.dirname("
                    "os.path.abspath(__file__)))\n"
                    "import _tmp_probe as M\n"
                    "bad = []\n"
                    "if M.measure(2) != 4:\n"
                    "    bad.append('обычное значение')\n"
                    "if M.measure(-1) is not None:\n"
                    "    bad.append('отрицательное не наблюдение')\n"
                    "print('ПАДЕНИЕ ' + ';'.join(bad) if bad "
                    "else 'все проверки прошли')\n"
                    "sys.exit(1 if bad else 0)\n")

        def rep(controls, **kw):
            d = {"built": True, "module": mod, "tests": tst,
                 "controls": controls}
            d.update(kw)
            return RL.check_build(json.dumps(d, ensure_ascii=False), root)

        ok, why = rep([{"file": mod, "old": rule,
                        "new": "    pass",
                        "expect": "отрицательное не наблюдение"}])
        check("постройка с кусающимся контролем принята", ok, str(why))

        # Подделка, ничего не меняющая по существу: тесты остаются
        # зелёными, и контракт обязан это назвать.
        ok, why = rep([{"file": mod, "old": "    return x * 2",
                        "new": "    return x + x", "expect": ""}])
        check("контроль, который не кусается, валит постройку",
              not ok and any("НЕ КУСАЕТСЯ" in w for w in why), str(why))

        ok, why = rep([])
        check("постройка без контролей отвергнута",
              not ok and any("контрол" in w for w in why), str(why))

        ok, why = rep([{"file": mod, "old": rule, "new": "    pass",
                        "expect": "такой проверки нет"}])
        check("упало не то, что обещано — тоже отказ",
              not ok and any("не то, что обещано" in w for w in why),
              str(why))

        ok, why = rep([{"file": "research/s8_loop/trades.py",
                        "old": "x", "new": "y", "expect": ""}])
        check("подделка чужого файла запрещена",
              not ok and any("вне своего каталога" in w for w in why),
              str(why))

        with open(os.path.join(root, mod), encoding="utf-8") as f:
            check("файл восстановлен после каждой подделки",
                  rule in f.read())

        ok, why = RL.check_build(json.dumps(
            {"built": False, "why": "коротко"}), root)
        check("неудача без объяснения отвергнута", not ok, str(why))
        ok, why = RL.check_build(json.dumps(
            {"built": False, "why": "п" * 130}), root)
        check("объяснённая неудача — законный ответ", ok, str(why))
    finally:
        for rel in (mod, tst):
            try:
                os.remove(os.path.join(root, rel))
            except OSError:
                pass


def test_adversary_must_show_what_it_tried():
    """«Не смог сломать» обязано отличаться от «не пробовал».

    Отличает их только список попыток, и попытка настоящая, если в ней
    названо конкретное действие: какой файл подделан, какая команда
    запущена, какое число пересчитано. Иначе вето накладывать
    некому — а сильнее адверсария в системе никого нет.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    good_try = {"attack": "контроль строителя",
                "how": "подделал research/factory/_x.py строкой pass "
                       "и прогнал тесты кандидата",
                "result": "тесты упали на проверке возраста"}
    base = {"verdict": "pass", "tried": [dict(good_try) for _ in range(3)],
            "cites": ["research/factory/out/brief.md"]}

    def chk(d):
        return RL.check_adversary(json.dumps(d, ensure_ascii=False), root)

    ok, why = chk(base)
    check("разбор с тремя настоящими попытками принят", ok, str(why))

    ok, why = chk(dict(base, tried=base["tried"][:2]))
    check("двух попыток мало", not ok
          and any("не пробовал" in w for w in why), str(why))

    ok, why = chk(dict(base, tried=[{"attack": "смотрел",
                                     "how": "просмотрел код",
                                     "result": "ничего"}] * 3))
    check("«просмотрел код» попыткой не считается",
          not ok and any("попыткой не является" in w for w in why),
          str(why))

    ok, why = chk(dict(base, verdict="ok"))
    check("вердикт вне трёх объявленных отвергнут",
          not ok and any("вердикт" in w for w in why), str(why))

    ok, why = chk(dict(base, verdict="veto", why="коротко"))
    check("вето без объяснения отвергнуто",
          not ok and any("вето" in w for w in why), str(why))

    ok, why = chk(dict(base, verdict="veto", why="п" * 120))
    check("объяснённое вето принято", ok, str(why))

    ok, why = chk(dict(base, verdict="undetermined"))
    check("«не могу подтвердить» — законный ответ", ok, str(why))

    ok, why = chk(dict(base, cites=["research/factory/nosuch_probe.py"]))
    check("несуществующий указатель отвергнут",
          not ok and any("несуществующ" in w for w in why), str(why))


def test_fallback_happens_only_on_a_limit_and_is_recorded():
    """Откат на запасную модель — только по лимиту, ровно раз, и в журнал.

    Решение владельца: предлагающему — самая способная модель, а на
    исчерпанном лимите переходить на запасную, иначе роль в такой день
    молча выпадает из суточного круга.

    Молчаливый перебор моделей превратил бы «роль отработала» в
    «отработала неизвестно чем», поэтому проверяется не только сам
    откат, но и то, что строка прогона называет ФАКТИЧЕСКУЮ модель.

    Нераспознанный отказ отката вызывать не должен: это безопасное
    направление ошибки — прогон падает громко, а не тратит вторую
    модель на беду, которая повторится.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sh = os.path.join(root, "tools", "agents_run.sh")

    def run(first_fails_with):
        d = tempfile.mkdtemp()
        bin_d = os.path.join(d, "bin")
        os.makedirs(bin_d)
        seen = os.path.join(d, "models.txt")
        with open(os.path.join(bin_d, "claude"), "w",
                  encoding="utf-8") as f:
            f.write('#!/bin/sh\n'
                    'if [ "$1" = "auth" ]; then\n'
                    '  echo \'{ "loggedIn": true }\'\n'
                    '  exit 0\n'
                    'fi\n'
                    'm=""\n'
                    'while [ $# -gt 0 ]; do\n'
                    '  if [ "$1" = "--model" ]; then m="$2"; fi\n'
                    '  shift\n'
                    'done\n'
                    'cat > /dev/null\n'
                    'echo "$m" >> "%s"\n'
                    'if [ "$m" = "fable" ]; then\n'
                    '  echo "%s"; exit 1\n'
                    'fi\n'
                    'echo "подставная модель отработала"\n'
                    % (seen, first_fails_with))
        os.chmod(os.path.join(bin_d, "claude"), 0o755)
        env = dict(os.environ, AGENTS_OUT=d, AGENTS_NO_PUBLISH="1",
                   PATH=bin_d + os.pathsep + os.environ.get("PATH", ""))
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run([sh, "propose"], cwd=root, env=env,
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=180)
        used = []
        if os.path.exists(seen):
            with open(seen, encoding="utf-8") as f:
                used = [x.strip() for x in f if x.strip()]
        rows, _ = RL.read(os.path.join(d, RL.RUNS))
        shutil.rmtree(d, ignore_errors=True)
        return r, used, rows

    r, used, rows = run("Error: usage limit reached for this model")
    check("на лимите зовётся запасная модель",
          used == ["fable", "opus"], str(used))
    st = [x["status"] for x in rows]
    check("откат оставил свою строку в журнале",
          "fallback" in st, str(st))
    last = [x for x in rows if x["status"] in ("ok", "contract")]
    check("строка прогона называет ФАКТИЧЕСКУЮ модель",
          bool(last) and "opus" in (last[-1].get("note") or ""),
          str(last[-1].get("note") if last else None))
    check("о переходе сказано громко",
          "ЛИМИТ" in r.stdout, r.stdout[-200:])

    # Отказ, не похожий на лимит: откат не делается, прогон падает.
    r, used, rows = run("Error: something else entirely went wrong")
    check("на чужом отказе запасная не зовётся",
          used == ["fable"], str(used))
    check("прогон упал, а не откатился",
          r.returncode != 0
          and [x["status"] for x in rows] == ["start", "fail"],
          str([x["status"] for x in rows]))
    check("в строке падения названа модель",
          any("fable" in (x.get("note") or "") for x in rows),
          str([x.get("note") for x in rows]))


def test_runner_leaves_a_line_on_every_refusal():
    """Запускалка: отказ называется и всё равно оставляет строку.

    Гоняется НАСТОЯЩИЙ скрипт — пересказ проверял бы мой пересказ.
    Каталог артефактов уведён, чтобы проверка не писала в журнал
    прогонов сервера.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sh = os.path.join(root, "tools", "agents_run.sh")
    if not os.path.exists(sh):
        check("запускалка на месте", False, sh)
        return
    d = tempfile.mkdtemp()
    try:
        # Подставной `claude`, который докладывает «не вошёл». Без него
        # проверка отказа на машине с ЖИВЫМ входом пошла бы дальше и
        # позвала настоящую модель — то есть проверяла бы не отказ, а
        # кошелёк владельца.
        bin_d = os.path.join(d, "bin")
        os.makedirs(bin_d)
        fake = os.path.join(bin_d, "claude")
        with open(fake, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\n'
                    'if [ "$1" = "auth" ]; then\n'
                    '  echo \'{ "loggedIn": false }\'\n'
                    '  exit 0\n'
                    'fi\n'
                    'echo "подставной claude звать не положено" >&2\n'
                    'exit 9\n')
        os.chmod(fake, 0o755)
        env = dict(os.environ, AGENTS_OUT=d, ANTHROPIC_KEY_FILE="/nope",
                   PATH=bin_d + os.pathsep + os.environ.get("PATH", ""))
        env.pop("ANTHROPIC_API_KEY", None)
        r1 = subprocess.run([sh, "nosuchrole"], cwd=root, env=env,
                            capture_output=True, text=True, timeout=120)
        r2 = subprocess.run([sh, "brief"], cwd=root, env=env,
                            capture_output=True, text=True, timeout=120)
        r3 = subprocess.run([sh, "brief", "--dry"], cwd=root, env=env,
                            capture_output=True, text=True, timeout=120)
        check("роль без промпта отвергнута кодом", r1.returncode != 0,
              r1.stdout[-200:])
        check("причина названа: нет промпта",
              "промпта роли нет" in r1.stdout, r1.stdout[-200:])
        check("боевой прогон без авторизации отвергнут",
              r2.returncode != 0)
        check("причина названа и оба пути перечислены",
              "авторизации нет" in r2.stdout
              and "auth login" in r2.stdout
              and "ключ" in r2.stdout, r2.stdout[-300:])
        check("модель при отказе не звалась",
              "подставной claude звать не положено" not in r2.stdout,
              r2.stdout[-200:])
        check("сухой прогон проходит и модель не зовёт",
              r3.returncode == 0 and "модель НЕ вызывается" in r3.stdout,
              r3.stdout[-200:])
        rows, _ = RL.read(os.path.join(d, RL.RUNS))
        got = sorted((r["role"], r["status"]) for r in rows)
        # Отказ ПОСЛЕ взятия замка оставляет две строки: начало и
        # причину. Отказ ДО замка (нет промпта) — только причину:
        # прогон не начинался, и объявлять начало было бы выдумкой.
        check("обе беды оставили строку в журнале",
              got == [("brief", "no-auth"), ("brief", "start"),
                      ("nosuchrole", "no-prompt")], str(got))
        st = RL.state_of(rows)
        check("после отказа роль не числится работающей",
              st["brief"]["running"] is None, str(st["brief"]))
        check("причина отказа — последний прогон роли",
              st["brief"]["last"]["status"] == "no-auth")
        dry, _ = RL.read(os.path.join(d, "agents-runs-dry.jsonl"))
        check("сухой прогон пишет в свой журнал и в общий не лезет",
              len(dry) == 2 and all(r["dry"] for r in dry)
              and [r["status"] for r in dry] == ["start", "ok"], str(dry))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (test_space_is_declared_and_frozen,
             test_control_share_is_of_the_pool_not_the_batch,
             test_control_share_converges,
             test_batch_respects_the_owners_limits,
             test_window_is_calendar_not_last_entries,
             test_retire_rule_follows_the_owner_by_sum,
             test_young_candidate_is_not_judged,
             test_silence_frees_the_slot,
             test_sweep_judges_control_by_the_same_rule,
             test_validate_bites_on_both_sides,
             test_draw_is_reproducible_and_random,
             test_unavailable_is_named_by_number,
             test_describe_names_every_axis,
             test_ledger_is_a_journal_not_a_table,
             test_broken_line_is_counted_not_swallowed,
             test_effective_n_is_measured,
             test_agents_registry_is_one_source_and_complete,
             test_run_log_counts_every_wake_up,
             test_running_now_is_a_separate_question,
             test_brief_contract_is_mechanical,
             test_proposal_must_be_checkable_not_persuasive,
             test_build_contract_makes_the_controls_bite,
             test_adversary_must_show_what_it_tried,
             test_runner_leaves_a_line_on_every_refusal,
             test_prompt_actually_reaches_the_model,
             test_fallback_happens_only_on_a_limit_and_is_recorded)
    for t in tests:
        print(t.__name__)
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0



import pool as P  # noqa: E402


def test_control_share_is_of_the_pool_not_the_batch():
    sel, ctl, _ = P.plan_batch(0, 0, 5)
    check("пустой пул: 4 отобранных и 1 случайный", (sel, ctl) == (4, 1),
          f"{sel}/{ctl}")
    # Доля считается от ПУЛА: контроль, отставший от четверти, забирает
    # партию целиком. При доле «четверть каждой партии» он так и остался
    # бы отставшим навсегда.
    sel, ctl, _ = P.plan_batch(40, 2, 5)
    check("отставший контроль догоняет", ctl == 5 and sel == 0,
          f"{sel}/{ctl}")
    sel, ctl, _ = P.plan_batch(40, 12, 5)
    check("догнавший контроль не растёт сверх доли", ctl <= 1,
          f"{sel}/{ctl}")


def test_control_share_converges():
    """Доля контроля обязана сходиться к четверти, а не совпадать с ней
    в каждой партии: при пуле из двух четверть равна нулю, и требовать
    случайного в первой же партии значит требовать больше, чем сказано
    в §3."""
    n_act = n_ctl = 0
    for _ in range(30):
        sel, ctl, _ = P.plan_batch(n_act, n_ctl, 3)
        n_act += sel + ctl
        n_ctl += ctl
    share = n_ctl / n_act
    check("доля случайных сошлась к четверти", abs(share - 0.25) <= 0.02,
          f"{share:.3f} при {n_ctl} из {n_act}")


def test_batch_respects_the_owners_limits():
    sel, ctl, why = P.plan_batch(0, 0, 9)
    check("предел суток — пять", sel + ctl == 5, f"{sel}+{ctl}")
    check("усечение названо словами", bool(why), str(why))
    sel, ctl, why = P.plan_batch(98, 25, 5)
    check("пул не переполняется", sel + ctl == 2, f"{sel}+{ctl}")
    sel, ctl, why = P.plan_batch(100, 25, 5)
    check("полный пул не принимает никого", sel + ctl == 0, f"{sel}+{ctl}")
    check("причина полного пула названа", bool(why), str(why))


def test_window_is_calendar_not_last_entries():
    now = 1000 * P.DAY
    # Три дня внутри окна и один далеко за ним: старая крупная прибыль
    # не имеет права спасать книгу, слившую последние десять суток.
    daily = {now - 1 * P.DAY: -5.0, now - 3 * P.DAY: -4.0,
             now - 9 * P.DAY: -3.0, now - 40 * P.DAY: +500.0}
    net, n = P.window_net(daily, now)
    check("окно берёт только свои сутки", abs(net + 12.0) < 1e-9 and n == 3,
          f"{net} за {n} дней")


def test_retire_rule_follows_the_owner_by_sum():
    now = 1000 * P.DAY
    born = now - 20 * P.DAY
    losing = {now - i * P.DAY: -2.0 for i in range(1, 10)}
    why = P.should_retire(losing, now, 0.0, born)
    check("сумма ниже медианы нуля — вылет", bool(why), str(why))
    # Копеечная зелёная свеча не обнуляет счётчик: правило по СУММЕ, а
    # не по серии — иначе мёртвая книга вылетала бы раз в полтора года.
    losing_with_green = dict(losing)
    losing_with_green[now - 5 * P.DAY] = +0.5
    check("зелёный день серию не обнуляет",
          bool(P.should_retire(losing_with_green, now, 0.0, born)))
    winning = {now - i * P.DAY: +2.0 for i in range(1, 10)}
    check("книга выше нуля живёт",
          P.should_retire(winning, now, 0.0, born) is None)
    # Сравнение со СВОИМ нулём: та же книга при нуле выше неё вылетает.
    check("нуль выше книги — вылет",
          bool(P.should_retire(winning, now, +100.0, born)))


def test_young_candidate_is_not_judged():
    now = 1000 * P.DAY
    young = now - 3 * P.DAY
    losing = {now - i * P.DAY: -9.0 for i in range(1, 3)}
    check("окна ещё нет — вердикта нет",
          P.should_retire(losing, now, 0.0, young) is None,
          str(P.should_retire(losing, now, 0.0, young)))


def test_silence_frees_the_slot():
    now = 1000 * P.DAY
    check("молчание дольше предела — вылет",
          bool(P.should_retire({}, now, 0.0, now - 40 * P.DAY)))
    check("молчание в пределах — не вылет",
          P.should_retire({}, now, 0.0, now - 20 * P.DAY) is None)


def test_sweep_judges_control_by_the_same_rule():
    now = 1000 * P.DAY
    born = now - 20 * P.DAY
    st = {"s1": {"lane": "selected", "declared_at": born, "retired_at": None},
          "c1": {"lane": "control", "declared_at": born, "retired_at": None},
          "s2": {"lane": "selected", "declared_at": born,
                 "retired_at": 5.0}}
    daily = {"s1": {now - 1 * P.DAY: -5.0},
             "c1": {now - 1 * P.DAY: -5.0},
             "s2": {now - 1 * P.DAY: -5.0}}
    got = dict(P.sweep(st, daily, now, 0.0))
    check("контрольная рука судится тем же правилом", "c1" in got, str(got))
    check("отобранная тоже", "s1" in got, str(got))
    check("уже отставленный не судится дважды", "s2" not in got, str(got))


if __name__ == "__main__":
    raise SystemExit(main())
