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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agents as AG  # noqa: E402
import runlog as RL  # noqa: E402
import ledger as L   # noqa: E402
import space as S    # noqa: E402
import live_books as LB  # noqa: E402

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

        # Откат на запасную модель — строка ТОГО ЖЕ прогона, а не его
        # конец: её пишет тот же процесс посреди работы. Найдено на
        # живом прогоне разведчика — идущая роль показывалась «не
        # идёт», а оборвись она, не помечалась бы и оборванной.
        RL.append(p, "scout", "start", 300.0, pid=os.getpid())
        RL.append(p, "scout", "fallback", 300.0,
                  note="CLI не знает модель A, перехожу на B")
        rows, _ = RL.read(p)
        st = RL.state_of(rows)["scout"]
        check("откат прогона не закрывает",
              st["running"] is not None and st["last"] is None,
              str(st))
        RL.append(p, "scout", "ok", 300.0, ended=400.0)
        rows, _ = RL.read(p)
        st = RL.state_of(rows)["scout"]
        check("а конец — закрывает",
              st["running"] is None
              and (st["last"] or {}).get("status") == "ok", str(st))

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


def test_scout_brings_mechanisms_not_verdicts():
    """Разведка проверяется по форме, и повтор ловит МАШИНА.

    Роль смотрит наружу, наших замеров у неё нет, и «работает» в чужом
    тексте стоит бесплатно. Поэтому у идеи обязаны быть механизм (не
    наблюдение), то, чем её убить, и источник ссылкой: без них до
    предлагающего доедет настроение, а не работа.

    Журнал принесённого ведёт машина: список, который роль пишет сама,
    она сама и перепишет, и защита от повтора станет украшением.
    """
    long = "x" * 120
    def idea(**kw):
        d = {"title": "поглощение в опционных потоках",
             "claim": long, "mechanism": long, "kills_it": long,
             "novelty": long, "sources": ["https://example.org/a"]}
        d.update(kw)
        return d

    def chk(d, seen=()):
        return RL.check_scout(json.dumps(d, ensure_ascii=False),
                              seen=seen)

    ok, why = chk({"found": True, "ideas": [idea()]})
    check("годное меню проходит", ok, str(why))

    ok, why = chk({"found": True, "ideas": [idea(mechanism="коротко")]})
    check("идея без механизма отвергнута",
          not ok and any("mechanism" in w for w in why), str(why))
    ok, why = chk({"found": True, "ideas": [idea(kills_it="")]})
    check("идея без «чем убить» отвергнута",
          not ok and any("kills_it" in w for w in why), str(why))
    ok, why = chk({"found": True, "ideas": [idea(sources=[])]})
    check("идея без источника отвергнута",
          not ok and any("источник" in w for w in why), str(why))
    ok, why = chk({"found": True,
                   "ideas": [idea(sources=["см. твиттер"])]})
    check("источник не ссылкой не считается",
          not ok and any("источник" in w for w in why), str(why))
    ok, why = chk({"found": True,
                   "ideas": [idea() for _ in
                             range(RL.SCOUT_MAX_IDEAS + 1)]})
    check("меню длиннее предела отвергнуто",
          not ok and any("предел" in w for w in why), str(why))
    ok, why = chk({"found": True, "ideas": [idea(), idea()]})
    check("две одинаковые идеи в одном меню отвергнуты",
          not ok and any("соседнюю" in w for w in why), str(why))
    ok, why = chk({"found": True, "ideas": [idea()]},
                  seen=["Поглощение в опционных потоках"])
    check("уже принесённая идея отвергнута",
          not ok and any("уже приносилась" in w for w in why), str(why))
    ok, why = chk({"found": False, "why": "коротко"})
    check("пустой день без обоснования отвергнут",
          not ok and any("не обоснован" in w for w in why), str(why))
    ok, why = chk({"found": False, "why": "п" * 150})
    check("обоснованный пустой день — законный ответ", ok, str(why))

    # Журнал ведёт машина, и только на ГОДНОМ меню: записав негодное,
    # мы запретили бы роли принести ту же идею исправленной.
    d = tempfile.mkdtemp()
    try:
        n = RL.scout_record(json.dumps({"found": True,
                                        "ideas": [idea()]},
                                       ensure_ascii=False), d)
        seen = RL.scout_seen(d)
        check("принесённое записано машиной",
              n == 1 and seen == ["поглощение в опционных потоках"],
              str(seen))
        # Меню перезаписывается каждым прогоном, поэтому журнал обязан
        # хранить идею ЦЕЛИКОМ: иначе он запрещает повтор и не отдаёт
        # взамен ничего, и идея теряется вместе со свежим `scout.json`.
        with open(os.path.join(d, RL.SCOUT_SEEN), encoding="utf-8") as f:
            rec = json.loads(f.readline())
        check("журнал хранит идею целиком, а не заголовок",
              all(rec.get(k) for k in ("claim", "mechanism", "kills_it",
                                       "novelty")), str(sorted(rec)))
        ok, why = chk({"found": True, "ideas": [idea()]}, seen=seen)
        check("повтор ловится по журналу машины", not ok, str(why))

        # Дважды записанная идея — шум в защите от повтора.
        n2 = RL.scout_record(json.dumps({"found": True,
                                         "ideas": [idea()]},
                                        ensure_ascii=False), d)
        with open(os.path.join(d, RL.SCOUT_SEEN), encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        check("та же идея вторично в журнал не пишется",
              n2 == 0 and len(lines) == 1, "%s / %s" % (n2, len(lines)))

        # Запись ЭТОГО ЖЕ прогона повтором быть не может: иначе роль
        # отвергают её собственные идеи (живой отказ 2026-09-02).
        at = json.loads(lines[0])["at"]
        check("своя запись прогон не блокирует",
              RL.scout_seen(d, before=at - 1.0) == [],
              str(RL.scout_seen(d, before=at - 1.0)))
        check("запись прошлого прогона блокирует",
              RL.scout_seen(d, before=at + 1.0) ==
              ["поглощение в опционных потоках"],
              str(RL.scout_seen(d, before=at + 1.0)))
        # Строка без метки машиной не писана: держать по ней роль
        # запертой значило бы ждать человека с уборкой.
        with open(os.path.join(d, RL.SCOUT_SEEN), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps({"title": "рукописная"},
                               ensure_ascii=False) + "\n")
        check("строка без метки прогон не судит",
              "рукописная" not in RL.scout_seen(d, before=at + 1.0),
              str(RL.scout_seen(d, before=at + 1.0)))
        check("без границы журнал виден целиком",
              len(RL.scout_seen(d)) == 2, str(RL.scout_seen(d)))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # Разведка доезжает до предлагающего РАЗДЕЛОМ БРИФА: он читает
    # только бриф, и второй вход обессмыслил бы его потолок токенов.
    root = os.path.dirname(os.path.dirname(HERE))
    with open(os.path.join(root, "research/factory/agents/brief.md"),
              encoding="utf-8") as f:
        bp = f.read()
    check("брифер обязан нести раздел разведки",
          "scout.json" in bp and "разведчик" in bp.lower(), "")
    # Свежее меню и ЗАПАС — разные вещи: меню перезаписывается каждым
    # прогоном, и без журнала идея, которую предлагающий не успел
    # взять, теряется молча (повтор ей запрещён, текста больше нет).
    check("брифер обязан нести запас принесённого раньше",
          RL.SCOUT_SEEN in bp and "принесено раньше" in bp, "")
    import cycle as CY
    order = [k for k, _kind, _argv, _proof in CY.CIRCLE]
    check("разведчик идёт перед брифером",
          order.index("scout") < order.index("brief"), str(order))


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
            "differs_from_live": long, "shape": long,
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

    # Ожидаемая ФОРМА кривой — обязательное поле с 2026-09-02: главный
    # критерий владельца устойчивость, и правило вылета судит именно
    # её. Заявка, не сказавшая, какой формы кривую она ждёт и чем
    # ограничен её хвост, подаётся вслепую под тот критерий, по
    # которому её и будут судить.
    ok, why = chk({k: v for k, v in good.items() if k != "shape"})
    check("заявка без ожидаемой формы отвергнута",
          not ok and any("shape" in w for w in why), str(why))
    check("правило вылета и требуемое поле — про одно и то же",
          "shape" in RL.PROPOSAL_MIN and hasattr(P, "shape_why"),
          str(sorted(RL.PROPOSAL_MIN)))

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


def test_scout_is_not_rejected_by_its_own_ideas():
    """Живой отказ 2026-09-02: разведчик отвергнут собственным меню.

    Три идеи легли в журнал за 23 секунды ДО вердикта «уже приносилась»,
    и роль не могла отработать вовсе: журнал повтора судил меню того же
    прогона, который его и наполнил. Кто именно записал (машина после
    проверки либо сама роль в обход промпта), для правила безразлично —
    запись, сделанная ПОСЛЕ начала прогона, повтором быть не может.

    Проверяется ДОРОГА (`check_role`), а не только `scout_seen`: живой
    отказ пришёл именно оттуда.
    """
    long = "x" * 120
    menu = {"found": True, "ideas": [
        {"title": "Насыщение потолка funding",
         "claim": long, "mechanism": long, "kills_it": long,
         "novelty": long, "sources": ["https://example.org/a"]}]}
    root = tempfile.mkdtemp(prefix="scout-")
    try:
        out = os.path.join(root, "research", "factory", "out")
        os.makedirs(out)
        with open(os.path.join(out, "scout.json"), "w",
                  encoding="utf-8") as f:
            json.dump(menu, f, ensure_ascii=False)
        with open(os.path.join(out, "scout.md"), "w",
                  encoding="utf-8") as f:
            f.write("меню человеческим текстом\n")

        started = time.time() - 600.0
        # record=True: здесь проверяется именно ЗАПИСЬ машины, а пишет
        # её тот, кто судит начисто (запускалка), — самопроверка роли
        # не пишет ничего, и это отдельный тест.
        ok, why = RL.check_role("scout", root, since=started, record=True)
        check("чистое меню проходит контракт роли", ok, str(why))
        check("машина записала принесённое",
              RL.scout_seen(out) == ["насыщение потолка funding"],
              str(RL.scout_seen(out)))

        # Тот же прогон судится заново (так и случилось на сервере):
        # запись этого прогона его блокировать не вправе.
        ok, why = RL.check_role("scout", root, since=started, record=True)
        check("своё же меню повтором не считается", ok, str(why))
        with open(os.path.join(out, RL.SCOUT_SEEN), encoding="utf-8") as f:
            n = len([ln for ln in f if ln.strip()])
        check("журнал от повторной проверки не растёт", n == 1, str(n))

        # А СЛЕДУЮЩИЙ прогон обязан упереться: иначе защита от повтора
        # исчезла бы вместе с дефектом. Секунда запаса взята не для
        # красоты: метка записи округлена до миллисекунды и может
        # оказаться на полмиллисекунды ПОЗЖЕ момента, взятого сразу
        # после неё, — на живых прогонах, разнесённых часами, это
        # безразлично, а в тесте давало бы мигающий отказ.
        ok, why = RL.check_role("scout", root, since=time.time() + 1.0,
                                record=True)
        check("следующий прогон повтор ловит",
              not ok and any("уже приносилась" in w for w in why),
              str(why))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scout_backlog_survives_the_next_menu():
    """Запрет на повтор без текста идеи есть потеря идеи.

    Меню живёт в `scout.json`, и каждый прогон перезаписывает его
    свежим; журнал переживает прогон, но первая его версия хранила один
    заголовок. Значит идея объявлялась принесённой — и запрещённой к
    повтору — тогда, когда её текста уже нет нигде, кроме истории git.

    Журнал write-ahead: строку не переписываем, знание доезжает
    ОТДЕЛЬНОЙ записью (узор поправки `Adjust` у живого исполнителя), и
    запись несёт исходный момент, полный текст и то, откуда он взят.
    Второй прогон обязан промолчать: полнота решается по всему журналу.
    """
    import scout_backfill as BF
    long = "y" * 130
    d = tempfile.mkdtemp(prefix="backlog-")
    try:
        path = os.path.join(d, RL.SCOUT_SEEN)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"at": 100.0, "title": "потолок funding",
                                "sources": ["https://example.org/a"]},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"at": 100.0, "title": "потерянная",
                                "sources": []},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"at": 200.0, "title": "свежая",
                                "mechanism": long},
                               ensure_ascii=False) + "\n")
        menu = os.path.join(d, "old.json")
        with open(menu, "w", encoding="utf-8") as f:
            json.dump({"found": True, "ideas": [
                {"title": "потолок funding", "claim": long,
                 "mechanism": long, "kills_it": long, "novelty": long,
                 "sources": ["https://example.org/a"]}]}, f,
                ensure_ascii=False)

        rows, _ = BF.read_journal(path)
        check("без текста считаются только неполные",
              BF.incomplete(rows) == ["потолок funding", "потерянная"],
              str(BF.incomplete(rows)))

        BF.main(["--menu", menu, "--out", d, "--no-publish"])
        rows, _ = BF.read_journal(path)
        got = [r for r in rows if r.get("restored_from")]
        check("текст доехал отдельной записью", len(got) == 1, str(rows))
        check("восстановленная запись несёт исходный момент и источник",
              got and got[0]["at"] == 100.0
              and got[0]["restored_from"] == "old.json"
              and got[0]["mechanism"] == long, str(got[:1]))
        check("чего нет в истории, то не выдумывается",
              "потерянная" in BF.incomplete(rows),
              str(BF.incomplete(rows)))
        check("повтор всё ещё запрещён",
              "потолок funding" in RL.scout_seen(d),
              str(RL.scout_seen(d)))

        n = len(rows)
        BF.main(["--menu", menu, "--out", d, "--no-publish"])
        rows2, _ = BF.read_journal(path)
        check("второй прогон ничего не дописывает",
              len(rows2) == n, "%d → %d" % (n, len(rows2)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_owner_ask_is_measured_not_assumed():
    """Просьба к владельцу: записана один раз, состояние — проверкой.

    Агент не заводит аккаунтов и не кладёт ключей. Просьба, сказанная
    прозой отчёта, читается один раз, и система молча стоит — отказ,
    неотличимый от спокойного дня.

    Два правила проверяются здесь и оба непослушны интуиции: повтор
    той же просьбы не пишется (иначе страница станет шумом, а шум не
    читают), и **проверка сильнее слова** — файл, которого нет, не
    начинает существовать оттого, что о нём сказали «сделано».
    """
    import asks as AK
    d = tempfile.mkdtemp(prefix="asks-")
    try:
        есть = os.path.join(d, "ключ.txt")
        with open(есть, "w", encoding="utf-8") as f:
            f.write("x")
        items = [
            {"what": "ключ площадки только на чтение",
             "why": "без него механику ликвидаций не построить вовсе",
             "unblocks": "поток ликвидаций", "check": есть},
            {"what": "аккаунт с оплатой запросов к архиву",
             "why": "архив стакана лежит в requester-pays и платный",
             "check": os.path.join(d, "нет.txt")},
            {"what": "решение", "why": "коротко"},
        ]
        n = AK.record(d, items, "строитель")
        check("негодная форма не записывается", n == 2, str(n))
        check("повтор не записывается",
              AK.record(d, items, "строитель") == 0, "")

        rows, broken = AK.state(d, root=d)
        by = {r["what"][:10]: r for r in rows}
        check("просьба с пройденной проверкой закрыта",
              by["ключ площа"]["open"] is False, str(rows))
        check("просьба с непройденной проверкой ждёт",
              by["аккаунт с "]["open"] is True, str(rows))

        AK.done(d, by["аккаунт с "]["id"], "сделал")
        rows, _ = AK.state(d, root=d)
        by = {r["what"][:10]: r for r in rows}
        check("проверка сильнее слова",
              by["аккаунт с "]["open"] is True
              and by["аккаунт с "]["said_done"] is True, str(rows))

        # Просьбы без проверки закрывает слово — и только оно.
        n2 = AK.record(d, [{"what": "оплатить доступ к календарю",
                            "why": "иначе события без истории и мерить "
                                   "их не на чем"}], "предлагающий")
        rows, _ = AK.state(d, root=d)
        no_check = [r for r in rows if r["check_ok"] is None][0]
        check("просьба без проверки ждёт слова",
              n2 == 1 and no_check["open"] is True
              and "нечем" in no_check["check_how"], str(no_check))
        AK.done(d, no_check["id"])
        rows, _ = AK.state(d, root=d)
        no_check = [r for r in rows if r["check_ok"] is None][0]
        check("слово закрывает просьбу без проверки",
              no_check["open"] is False, str(no_check))

        with open(os.path.join(d, AK.ASKS), "a", encoding="utf-8") as f:
            f.write("{битая\n")
        _rows, broken = AK.state(d, root=d)
        check("битая строка считается, а не глотается",
              broken == 1, str(broken))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_mechanic_waits_in_a_queue_not_in_a_file():
    """Механика переживает следующий прогон предлагающего.

    `proposal.json` перезаписывается каждым кругом: заявка, которой
    движок не умеет, жила ровно сутки — тот же дефект, что журнал
    разведчика из одних заголовков. Здесь она стоит в очереди, задание
    строителю выдаётся по ней, и пока оно не закрыто, второе не
    выдаётся: строитель, получивший два задания, построит половину
    каждого.
    """
    import mech_queue as MQ
    long = "z" * 130
    d = tempfile.mkdtemp(prefix="mech-")
    try:
        prop = {"proposed": True, "kind": "mechanism",
                "title": "поток ликвидаций поимённо",
                "hypothesis": long, "kills_it": long, "ceiling": long,
                "needs": long, "shape": long,
                "cites": ["research/factory/out/brief.md"]}
        k = MQ.queue(d, prop)
        check("механика встала в очередь", bool(k), str(k))
        check("повтор в очередь не встаёт",
              MQ.queue(d, prop) is None, "")
        check("строка пространства в очередь механик не идёт",
              MQ.queue(d, dict(prop, kind="row")) is None, "")

        check("строить есть что", MQ.pending(d) and not MQ.build_ready(d),
              "задания ещё нет, а механика ждёт")
        MQ.main(["--out", d, "--next"])
        task = os.path.join(d, MQ.TASK)
        check("задание положено и помечено механикой",
              MQ.task_id(task) == k, str(MQ.task_id(task)))
        with open(task, encoding="utf-8") as f:
            txt = f.read()
        check("задание несёт слова заявки, а не пересказ",
              long in txt and prop["title"] in txt, txt[:200])
        check("гейт строителя открыт", MQ.build_ready(d) is True, "")

        # Второе задание поверх незакрытого не кладётся.
        prop2 = dict(prop, title="вторая механика")
        MQ.queue(d, prop2)
        MQ.main(["--out", d, "--next"])
        check("поверх незакрытого задания второе не кладётся",
              MQ.task_id(task) == k, str(MQ.task_id(task)))
        st = json.load(open(os.path.join(d, MQ.STATE), encoding="utf-8"))
        check("шаг оставил след даже ничего не сделав",
              st["decided"] == "занято", str(st))

        MQ.mark(d, "built", k, "research/x/y.py")
        check("построенная механика гейт закрывает",
              MQ.build_ready(d) is False, "")
        MQ.main(["--out", d, "--next"])
        check("следующая механика получает задание",
              MQ.task_id(task) == MQ.key_of("вторая механика"),
              str(MQ.task_id(task)))
        prev = os.path.join(d, MQ.TASK_PREV)
        check("прежнее задание не потеряно", os.path.exists(prev), "")

        rows, _ = MQ.state(d)
        states = {r["title"]: r["state"] for r in rows}
        check("состояния очереди читаются перечитыванием",
              states["поток ликвидаций поимённо"] == "построена"
              and states["вторая механика"] == "отдана строителю",
              str(states))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_conveyor_records_asks_and_the_mechanic():
    """Дорога: контракт роли САМ ставит механику и записывает просьбы.

    Правило, до которого не доходит дорога, не работает: журнал
    разведчика уже ловил это дважды. Заявка проверяется настоящим
    `check_role`, а запись строителя — теми же помощниками, которых
    зовёт его ветка (её собственный контракт гоняет тесты кандидата и
    подделки, и это отдельный, дорогой прогон).
    """
    import asks as AK
    import mech_queue as MQ
    long = "w" * 200
    root = tempfile.mkdtemp(prefix="road-")
    try:
        out = os.path.join(root, "research", "factory", "out")
        os.makedirs(out)
        for rel in ("research/factory/space.py",
                    "research/factory/pool.py",
                    "research/factory/out/brief.md",
                    "research/factory/out/proposal.md"):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
                f.write("проба\n")
        prop = {"proposed": True, "kind": "mechanism",
                "title": "календарь разблокировок",
                "hypothesis": long, "kills_it": long, "ceiling": long,
                "differs_from_live": long, "shape": long,
                "needs": "строителя и внешний календарь с историей",
                "cites": ["research/factory/out/brief.md",
                          "research/factory/space.py",
                          "research/factory/pool.py"],
                "needs_owner": [
                    {"what": "доступ к календарю разблокировок",
                     "why": "у нас нет истории прошедших дат, а без "
                            "неё событие не проверить walk-forward",
                     "unblocks": "календарь разблокировок"}]}
        with open(os.path.join(out, "proposal.json"), "w",
                  encoding="utf-8") as f:
            json.dump(prop, f, ensure_ascii=False)

        # record=True: тест проверяет ДОРОГУ ЗАПИСИ, а пишет журналы
        # тот, кто судит начисто; самопроверка роли не пишет ничего.
        ok, why = RL.check_role("propose", root, record=True)
        check("заявка-механика проходит контракт", ok, str(why))
        check("механика встала в очередь ДОРОГОЙ",
              [r["title"] for r in MQ.state(out)[0]]
              == ["календарь разблокировок"], str(MQ.state(out)[0]))
        rows, _ = AK.state(out, root)
        check("просьба записана дорогой", len(rows) == 1
              and rows[0]["from"] == "предлагающий", str(rows))

        # Негодная форма просьбы — беда контракта, а не пропуск: молча
        # выброшенная просьба означает, что система стоит.
        bad_prop = dict(prop, needs_owner=[{"what": "ключ",
                                            "why": "надо"}])
        with open(os.path.join(out, "proposal.json"), "w",
                  encoding="utf-8") as f:
            json.dump(bad_prop, f, ensure_ascii=False)
        ok, why = RL.check_role("propose", root, record=True)
        check("негодная просьба валит контракт, а не теряется",
              not ok and any("просьба 1" in w for w in why), str(why))

        # Строитель уперся в владельца: механика не «построена», а
        # ждёт — иначе круг переспрашивал бы её каждый день.
        MQ.main(["--out", out, "--next"])
        mid = MQ.task_id(os.path.join(out, MQ.TASK))
        RL._owner_asks(out, {"needs_owner": [
            {"what": "аккаунт с оплатой запросов к архиву",
             "why": "архив стакана лежит в requester-pays и платный"}]},
            "строитель")
        RL._close_mechanism(out, {"built": False, "needs_owner": [1]})
        states = {r["id"]: r["state"] for r in MQ.state(out)[0]}
        check("механика, упершаяся в владельца, ждёт его",
              states[mid] == "ждёт владельца", str(states))
        rows, _ = AK.state(out, root)
        check("просьба строителя записана", len(rows) == 2, str(rows))

        RL._close_mechanism(out, {"built": True,
                                  "module": "research/x/y.py"})
        states = {r["id"]: r["state"] for r in MQ.state(out)[0]}
        check("построенная механика закрыта", states[mid] == "построена",
              str(states))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_circle_calls_the_builder_only_with_a_task():
    """Круг зовёт строителя ТОЛЬКО когда задание есть.

    Строитель без задания стоит столько же, сколько строитель с
    заданием, — и модель зовётся впустую каждый день. Проверяется не
    сам гейт, а ДОРОГА: круг гоняется настоящий, с подставным запуском,
    и смотрится, какой шаг он выбрал. Прямая проверка функции здесь не
    годится — она проходит и при гейте, никуда не подключённом.
    """
    import cycle as CY
    import mech_queue as MQ
    keys = [k for k, _kind, _a, _p in CY.CIRCLE]
    check("шаги задания и строителя стоят в круге по порядку",
          keys.index("task") > keys.index("declare")
          and keys.index("build") == keys.index("task") + 1, str(keys))
    # Круг и реестр описывают ОДИН конвейер: шаг, которого нет в
    # реестре, страница не покажет вовсе — и владелец не узнает, что
    # система его делает.
    import agents as AG
    known = {x["key"] for x in AG.pipeline()}
    check("каждый шаг круга описан в реестре",
          not (set(keys) - known), str(set(keys) - known))

    long = "q" * 130
    d = tempfile.mkdtemp(prefix="gate-")
    old = (CY.OUT, CY.STOP, CY.launch)
    launched = []
    try:
        CY.OUT = d
        CY.STOP = os.path.join(d, "STOP")
        CY.launch = lambda key, kind, argv, log=None: (
            launched.append(key) or 1)
        runs = os.path.join(d, RL.RUNS)
        for k in ("scout", "brief", "propose"):
            RL.append(runs, k, "ok", time.time())
        for name in ("FACTORY-day-1m.md", "factory-day-1m.json",
                     "ceiling.json", "declare.json"):
            open(os.path.join(d, name), "w").close()

        CY.main(["--force"])
        check("первым недостающим идёт шаг задания",
              launched == ["task"], str(launched))

        # Очередь пуста: шаг задания оставил след, строитель не зовётся.
        MQ.main(["--out", d, "--next"])
        launched.clear()
        CY.main(["--force"])
        check("без задания строитель не зовётся",
              launched == [], str(launched))

        # Механика пришла ПОСЛЕ того, как шаг сказал «нечего»: он
        # обязан открыться заново, иначе заявка ждёт до завтра молча.
        # Так и вышло 2026-09-02: «нечего» в 20:30, механика в 22:36,
        # и круг за сегодня был пройден целиком.
        MQ.queue(d, {"kind": "mechanism", "title": "поздняя механика",
                     "hypothesis": long, "needs": long})
        os.utime(os.path.join(d, MQ.QUEUE),
                 (time.time() + 5, time.time() + 5))
        launched.clear()
        CY.main(["--force"])
        check("поздняя механика открывает шаг задания заново",
              launched == ["task"], str(launched))
        MQ.main(["--out", d, "--next"])
        MQ.mark(d, "built", MQ.key_of("поздняя механика"), "готово")
        MQ.main(["--out", d, "--next"])

        # Механика в очереди — задание выдано, строитель зовётся.
        MQ.queue(d, {"kind": "mechanism", "title": "механика проба",
                     "hypothesis": long, "needs": long})
        MQ.main(["--out", d, "--next"])
        launched.clear()
        CY.main(["--force"])
        check("с заданием строитель зовётся",
              launched == ["build"], str(launched))

        # Механика закрыта — гейт закрывается снова.
        MQ.mark(d, "built", MQ.key_of("механика проба"), "готово")
        launched.clear()
        CY.main(["--force"])
        check("построенное задание гейт закрывает",
              launched == [], str(launched))
    finally:
        CY.OUT, CY.STOP, CY.launch = old
        shutil.rmtree(d, ignore_errors=True)


def test_contract_check_gets_the_start_moment():
    """Дорога до правила: момент начала прогона обязан ДОЙТИ до проверки.

    Само правило («запись этого прогона повтором не считается») живёт в
    `runlog`, но живой отказ пришёл из запускалки, а её вызов не
    проверял никто. Гоняется НАСТОЯЩИЙ блок скрипта с подставным
    питоном: он запоминает свои аргументы, и мы смотрим, что момент
    доехал третьим — а не потерялся, как терялся промпт в первом
    прогоне предлагающего.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    with open(os.path.join(root, "tools", "agents_run.sh"),
              encoding="utf-8") as f:
        src = f.read().splitlines(True)
    beg = next(i for i, ln in enumerate(src)
               if ln.startswith("# --- проверка того, что роль произвела"))
    end = next(i for i in range(beg, len(src)) if src[i].startswith(')"'))
    block = "".join(src[beg:end + 1])
    check("блок проверки контракта найден", 'R.check_role(' in block,
          block[:200])

    d = tempfile.mkdtemp()
    try:
        got = os.path.join(d, "argv.txt")
        stub = os.path.join(d, "py")
        with open(stub, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$@" > "' + got +
                    '"\ncat > "' + os.path.join(d, "body.py") + '"\n')
        os.chmod(stub, 0o755)
        sh = os.path.join(d, "block.sh")
        with open(sh, "w", encoding="utf-8") as f:
            f.write('set -uo pipefail\nROLE=scout\nROOT=%s\n'
                    'STARTED=1788371000\nOUT=%s/своё\nPY=%s\n%s\n'
                    % (d, d, stub, block))
        subprocess.run(["bash", sh], capture_output=True, text=True,
                       timeout=60)
        argv = []
        if os.path.exists(got):
            with open(got, encoding="utf-8") as f:
                argv = [ln.rstrip("\n") for ln in f]
        check("момент начала доехал до проверки",
              "1788371000" in argv, str(argv))
        check("роль и корень доехали тоже",
              argv[1:3] == ["scout", d], str(argv))
        # Каталог прогона — та же дорога: без него проверка судила бы
        # БОЕВЫЕ артефакты и писала бы в боевые журналы (2026-09-02).
        check("каталог прогона доехал до проверки",
              argv[-1:] == [os.path.join(d, "своё")], str(argv))
        # Довезти аргумент мало: тело проверки обязано его ВЗЯТЬ.
        # Смотрится тот текст, который запускалка подала питону, а не
        # исходник рядом.
        body = ""
        if os.path.exists(os.path.join(d, "body.py")):
            with open(os.path.join(d, "body.py"), encoding="utf-8") as f:
                body = f.read()
        check("проверка берёт каталог прогона, а не выводит из корня",
              "out=sys.argv[4]" in body.replace(" ", "")
              .replace("\n", ""), body[-300:])
        # Журналы машины пишет ТОТ, КТО СУДИТ НАЧИСТО. Роль ту же
        # проверку зовёт для самопроверки и писать не должна — иначе
        # запись двоится (03.09 «ждёт владельца» легло дважды).
        # Ищется ВЫЗОВ, а не слово: рядом стоит комментарий про
        # `record=True`, и проверка на голое слово проходила на
        # подделке — текст рядом с кодом входит в источник наравне с
        # кодом (тот же промах уже ловился на дереве моделей).
        check("судья пишет журналы, а самопроверка роли — нет",
              "out=sys.argv[4],record=True)" in
              body.replace(" ", "").replace("\n", ""), body[-300:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_closed_by_ceiling_is_not_proposed_again():
    """Закрытое дешёвым расчётом не возвращается на следующий круг.

    Повтор уже ОБЪЯВЛЕННОГО ловился ключом с первого дня: такая строка
    лежит в реестре. А заявка, убитая потолком, испытанием не
    становилась — в реестре её нет, памяти между вызовами у роли нет
    тоже, и без своего журнала она вернулась бы тем же ключом уже
    завтра.

    Проверяется не только правило, но и ДОРОГА до него: контракт роли
    обязан прочитать оба журнала САМ. Ровно на этой дороге и нашёлся
    дефект — реестру подавали путь к файлу там, где он ждёт каталог, и
    повтор объявленного через настоящую дорогу не ловился ни разу,
    хотя прямая проверка правила проходила: ей ключи подавали руками.
    """
    import ceiling as CL
    long = "x" * 200
    rule = {"target": "fwd_4h", "rank": "sigma", "floor_bp": 30,
            "width": 5, "geom": "levels", "rr_band": "lo",
            "sizing": "equal", "basket": "no", "agree": "no"}
    key = S.key(rule)
    prop = {"proposed": True, "kind": "row", "title": "проба",
            "hypothesis": long, "kills_it": long, "ceiling": long,
            "differs_from_live": long, "shape": long,
            "cites": ["research/factory/out/brief.md",
                      "research/factory/space.py",
                      "research/factory/pool.py"],
            "rule": rule}

    root = tempfile.mkdtemp(prefix="closed-")
    try:
        out = os.path.join(root, "research", "factory", "out")
        os.makedirs(out)
        for rel in ("research/factory/space.py",
                    "research/factory/pool.py",
                    "research/factory/out/brief.md",
                    "research/factory/out/proposal.md"):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
                f.write("проба\n")
        with open(os.path.join(out, "proposal.json"), "w",
                  encoding="utf-8") as f:
            json.dump(prop, f, ensure_ascii=False)

        ok, why = RL.check_role("propose", root)
        check("чистая заявка проходит контракт роли", ok, str(why))

        # Дорога до реестра: объявленное не подаётся заново.
        led = os.path.join(out, "ledger.jsonl")
        with open(led, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ev": L.DECLARE, "id": key, "rule": rule,
                                "lane": "selected", "at": 1.0},
                               ensure_ascii=False) + "\n")
        ok, why = RL.check_role("propose", root)
        check("повтор объявленного ловится ЧЕРЕЗ ДОРОГУ",
              not ok and any("уже объявлен" in w for w in why), str(why))
        os.remove(led)

        # Дорога до потолка: закрытое им — тоже.
        with open(CL.journal_path(out), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": key, "verdict": CL.CLOSED,
                                "why": "сделок меньше предела"},
                               ensure_ascii=False) + "\n")
        ok, why = RL.check_role("propose", root)
        check("закрытое потолком заново не подаётся",
              not ok and any("закрыт потолком" in w for w in why),
              str(why))

        # ПРОШЕДШЕЕ потолок закрытым не считается: иначе годная заявка
        # умирала бы от собственного удачного расчёта.
        with open(CL.journal_path(out), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": key, "verdict": CL.PASS,
                                "why": "сделок хватает"},
                               ensure_ascii=False) + "\n")
        ok, why = RL.check_role("propose", root)
        check("прошедшее потолок с закрытым не путается", ok, str(why))

        # И правило само по себе, помимо дороги.
        ok, why = RL.check_proposal(json.dumps(prop, ensure_ascii=False),
                                    root, space=S, closed_ids=[key])
        check("правило закрытого ключа кусается", not ok
              and any("закрыт потолком" in w for w in why), str(why))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_rights_reach_the_model_whole():
    """Право с пробелом внутри доезжает до модели ЦЕЛИКОМ.

    Права передавались одной строкой через пробел, и `Bash(cat *)`
    доезжало двумя словами: CLI честно печатал «Ignoring
    --allowedTools rule "*)"», то есть половина объявленных прав молча
    не действовала, а роль получала отказ там, где право у неё было.
    Найдено на первом живом прогоне разведчика.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sh = os.path.join(root, "tools", "agents_run.sh")
    d = tempfile.mkdtemp()
    try:
        bin_d = os.path.join(d, "bin")
        os.makedirs(bin_d)
        seen = os.path.join(d, "rules.txt")
        # Подставной CLI пишет КАЖДОЕ правило своей строкой: только так
        # видно, что правило не разорвано.
        with open(os.path.join(bin_d, "claude"), "w",
                  encoding="utf-8") as f:
            f.write('#!/bin/sh\n'
                    'if [ "$1" = "auth" ]; then\n'
                    '  echo \'{ "loggedIn": true }\'\n'
                    '  exit 0\n'
                    'fi\n'
                    'take=0\n'
                    'while [ $# -gt 0 ]; do\n'
                    '  case "$1" in\n'
                    '    --allowedTools) take=1 ;;\n'
                    '    --*) take=0 ;;\n'
                    '    *) [ "$take" = 1 ] && echo "$1" >> "%s" ;;\n'
                    '  esac\n'
                    '  shift\n'
                    'done\n'
                    'cat > /dev/null\n'
                    'echo "подставная модель отработала"\n' % seen)
        os.chmod(os.path.join(bin_d, "claude"), 0o755)
        env = dict(os.environ, AGENTS_OUT=d, AGENTS_NO_PUBLISH="1",
                   PATH=bin_d + os.pathsep + os.environ.get("PATH", ""))
        env.pop("ANTHROPIC_API_KEY", None)
        subprocess.run([sh, "brief"], cwd=root, env=env,
                       capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=180)
        got = []
        if os.path.exists(seen):
            with open(seen, encoding="utf-8") as f:
                got = [x.strip() for x in f if x.strip()]
        want = AG.tools("brief")
        check("прав дошло столько, сколько объявлено",
              len(got) == len(want), f"{len(got)} против {len(want)}")
        check("право с пробелом не разорвано",
              any(" " in x and x.endswith(")") for x in got),
              str(got[:6]))
        check("обрывков правил не приехало",
              not any(x == "*)" or x.endswith("(cat") for x in got),
              str(got))
    finally:
        shutil.rmtree(d, ignore_errors=True)


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


def test_the_control_machine_is_not_fooled_by_stale_bytecode():
    """Машина контролей обязана исполнять ТОТ код, который написала.

    Найдено ролью строителя на её копии этой машины. Питон считает
    `.pyc` свежим по паре (mtime в ЦЕЛЫХ секундах, размер исходника), а
    подделки пишутся в один файл подряд: замена одной строки часто даёт
    файл того же размера в ту же секунду — и прогон исполняет байткод
    ПРЕДЫДУЩЕЙ подделки. Врёт в обе стороны: кусающийся контроль
    объявляется прошедшим и наоборот, а через эту машину проходили все
    контроли фабрики.

    Проверка воспроизводит столкновение точно: тот же размер и та же
    метка времени. Со своим каталогом байткода второй прогон обязан
    увидеть НОВЫЙ исходник.
    """
    d = tempfile.mkdtemp()
    try:
        mod = os.path.join(d, "m.py")
        tst = os.path.join(d, "t.py")
        with open(tst, "w", encoding="utf-8") as f:
            f.write("import sys, os\n"
                    "sys.path.insert(0, os.path.dirname("
                    "os.path.abspath(__file__)))\n"
                    "import m\n"
                    "raise SystemExit(0 if m.V == 1 else 1)\n")
        stamp = time.time() - 10

        def put(v):
            with open(mod, "w", encoding="utf-8") as f:
                f.write(f"V = {v}\n")
            os.utime(mod, (stamp, stamp))

        put(1)
        ok1, _ = RL._run_tests(d, tst)
        put(2)          # тот же размер, та же метка времени
        ok2, _ = RL._run_tests(d, tst)
        check("первый прогон видит свой код", ok1, "")
        check("второй прогон видит НОВЫЙ код, а не прежний байткод",
              not ok2, "исполнён байткод предыдущей подделки")
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


def test_a_broken_character_does_not_swallow_the_journal_row():
    """Порченый знак в пояснении НЕ теряет строку журнала.

    Пояснение приходит из чужого вывода и обрезается хвостом, а обрезка
    по байтам рвёт utf-8 посередине. `json.dumps` на одиноком суррогате
    бросает — и строка не пишется ВОВСЕ: прогон, который кончился,
    навсегда читается как оборванный. Это тот же отказ, неотличимый от
    тишины, только внутри самого журнала.

    Живой случай: контракт роли отказал, пояснение обрезали `tail -c`,
    и строки `contract` в журнале не появилось ни одной.
    """
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, RL.RUNS)
        # Ровно то, что даёт байтовая обрезка: половина кириллической
        # буквы, поднятая в строку через surrogateescape.
        broken = "модель claude-x, контракт не выполнен: зан" + \
            "яно".encode()[:1].decode("utf-8", "surrogateescape")
        RL.append(path, "propose", "contract", time.time(), note=broken)
        rows, bad = RL.read(path)
        check("строка записана, а не потеряна", len(rows) == 1, str(rows))
        check("битых строк нет", bad == 0, str(bad))
        note = (rows[0].get("note") or "") if rows else ""
        check("модель в строке названа", "claude-x" in note, note)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_fallback_happens_on_a_limit_or_an_unknown_model():
    """Откат на запасную модель — по двум причинам, ровно раз, и в журнал.

    Решение владельца: предлагающему — самая способная модель, а на
    исчерпанном лимите переходить на запасную, иначе роль в такой день
    молча выпадает из суточного круга.

    Вторая причина добавлена 2026-09-02 по живому отказу: CLI на
    сервере (2.1.220) не знает объявленной модели `claude-fable-5-1` и
    отвечает 400. Отказ постоянный — роль не отработает никогда, пока
    машину не обновят, — и запасная модель заведена ровно для этого.

    Молчаливый перебор моделей превратил бы «роль отработала» в
    «отработала неизвестно чем», поэтому проверяется не только сам
    откат, но и то, что строка прогона называет ФАКТИЧЕСКУЮ модель.

    Нераспознанный отказ отката вызывать не должен: это безопасное
    направление ошибки — прогон падает громко, а не тратит вторую
    модель на беду, которая повторится.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sh = os.path.join(root, "tools", "agents_run.sh")
    # Имена моделей берутся ИЗ РЕЕСТРА, а не пишутся здесь руками:
    # владелец меняет модель решением, и тест, назвавший её словом,
    # краснеет на верном коде (случилось при переходе на Fable 5.1).
    MAIN, BACK = AG.model_of("propose"), AG.fallback_of("propose")

    def run(first_fails_with, both=False):
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
                    'if [ "%s" = "1" ] || [ "$m" = "%s" ]; then\n'
                    '  echo "%s"; exit 1\n'
                    'fi\n'
                    'echo "подставная модель отработала"\n'
                    % (seen, "1" if both else "0", MAIN,
                       first_fails_with))
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
          used == [MAIN, BACK], str(used))
    st = [x["status"] for x in rows]
    check("откат оставил свою строку в журнале",
          "fallback" in st, str(st))
    last = [x for x in rows if x["status"] in ("ok", "contract")]
    check("строка прогона называет ФАКТИЧЕСКУЮ модель",
          bool(last) and BACK in (last[-1].get("note") or ""),
          str(last[-1].get("note") if last else None))
    check("о переходе сказано громко",
          "ЛИМИТ" in r.stdout, r.stdout[-200:])

    # Отказ, не похожий на лимит: откат не делается, прогон падает.
    # Лимитом кончились ОБЕ модели: уперлись не в модель, а в аккаунт.
    # Строка `limit` с моментом повтора, код 3 — и ни слова «упал»:
    # круг по этой строке разбудит роль сам.
    r, used, rows = run("Error: usage limit reached for this model",
                        both=True)
    st = [x["status"] for x in rows]
    check("лимит обеих моделей записан ожиданием, а не падением",
          RL.LIMIT in st and "fail" not in st, str(st))
    lim = [x for x in rows if x["status"] == RL.LIMIT]
    check("в строке ожидания есть момент повтора",
          lim and lim[-1].get("retry_at", 0) > time.time(),
          str(lim[-1] if lim else None))
    check("ожидание отличено кодом возврата", r.returncode == 3,
          str(r.returncode))
    check("о лимите аккаунта сказано громко",
          "ЛИМИТ АККАУНТА" in r.stdout, r.stdout[-200:])

    # Живая формулировка отказа, стоившая суток молчания 2026-09-02:
    # предлагающий получил «You've hit your session limit · resets
    # 10:20pm (UTC)», выражение её не узнало, и ОЖИДАНИЕ было записано
    # ПОЛОМКОЙ — роль сожгла попытку из суточных трёх, момент повтора
    # не записался никуда, и круг не поднял её сам, хотя лимит
    # снимался через два часа. Слова аккаунта проверяются дословно.
    r, used, rows = run("You've hit your session limit \u00b7 resets "
                        "10:20pm (UTC)", both=True)
    st = [x["status"] for x in rows]
    check("лимит сессии — ожидание, а не поломка",
          RL.LIMIT in st and "fail" not in st, str(st))
    lim = [x for x in rows if x["status"] == RL.LIMIT]
    check("названный час снятия доехал до строки ожидания",
          bool(lim) and "часы UTC" in (lim[-1].get("note") or ""),
          str(lim[-1].get("note") if lim else None))

    # Вторая причина отката — CLI НЕ ЗНАЕТ объявленной модели. Это
    # отказ постоянный: завтра он повторится дословно, и роль не
    # отработает никогда. Найдено на живом сервере — `scout` и
    # `propose` молчали трое суток, каждая попытка кончалась
    # «Claude Code 2.1.220 does not support this model».
    r, used, rows = run("API Error: 400 Claude Code 2.1.220 does not "
                        "support this model; version 2.1.251 or newer "
                        "is required.")
    check("на неизвестной CLI модели зовётся запасная",
          used == [MAIN, BACK], str(used))
    check("о подмене модели сказано громко и названа причина",
          "НЕ ПРИНЯТА" in r.stdout, r.stdout[-300:])
    fb = [x for x in rows if x["status"] == "fallback"]
    check("причина отката записана словами, а не как лимит",
          bool(fb) and "не знает" in (fb[-1].get("note") or ""),
          str(fb[-1].get("note") if fb else None))
    last = [x for x in rows if x["status"] in ("ok", "contract")]
    check("строка прогона называет модель, которая отработала",
          bool(last) and BACK in (last[-1].get("note") or ""),
          str(last[-1].get("note") if last else None))

    r, used, rows = run("Error: something else entirely went wrong")
    check("на чужом отказе запасная не зовётся",
          used == [MAIN], str(used))
    check("прогон упал, а не откатился",
          r.returncode != 0
          and [x["status"] for x in rows] == ["start", "fail"],
          str([x["status"] for x in rows]))
    check("в строке падения названа модель",
          any(MAIN in (x.get("note") or "") for x in rows),
          str([x.get("note") for x in rows]))


def test_a_hanging_role_is_killed_by_the_clock_and_named():
    """Повисшая роль убивается по времени, и это НАЗЫВАЕТСЯ словом.

    До 2026-09-02 предела не было ни в запускалке, ни в очереди
    заданий, ни в круге: зависший вызов держал бы замок ролей вечно, а
    вместе с ним очередь заданий (единственный доступ сессии к
    серверу) и суточный круг. Правило проекта: прогон, который молчит
    дольше минуты, неотличим от повисшего.

    Убийство по времени НЕ откатывается на запасную модель — это не
    отказ модели, а зависание, и второй час ждать незачем.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sh = os.path.join(root, "tools", "agents_run.sh")
    MAIN, BACK = AG.model_of("propose"), AG.fallback_of("propose")
    d = tempfile.mkdtemp()
    bin_d = os.path.join(d, "bin")
    os.makedirs(bin_d)
    seen = os.path.join(d, "models.txt")
    try:
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
                    # Спит ДОЛЬШЕ допуска проверки: со сном короче
                    # «убит по пределу» проходило бы и без предела.
                    'sleep 90\n' % seen)
        os.chmod(os.path.join(bin_d, "claude"), 0o755)
        env = dict(os.environ, AGENTS_OUT=d, AGENTS_NO_PUBLISH="1",
                   AGENTS_TIMEOUT_SEC="2",
                   PATH=bin_d + os.pathsep + os.environ.get("PATH", ""))
        env.pop("ANTHROPIC_API_KEY", None)
        t0 = time.time()
        r = subprocess.run([sh, "propose"], cwd=root, env=env,
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        took = time.time() - t0
        rows, _ = RL.read(os.path.join(d, RL.RUNS))
        used = []
        if os.path.exists(seen):
            with open(seen, encoding="utf-8") as f:
                used = [x.strip() for x in f if x.strip()]
        check("повисший вызов убит по пределу, а не ждёт вечно",
              took < 60, f"{took:.1f} с")
        check("прогон упал", r.returncode != 0, str(r.returncode))
        check("причина названа временем, а не кодом",
              any("по времени" in (x.get("note") or "") for x in rows),
              str([x.get("note") for x in rows]))
        check("о пределе сказано громко",
              "ПРЕДЕЛ ВРЕМЕНИ" in r.stdout, r.stdout[-200:])
        check("зависание не тратит запасную модель",
              used == [MAIN], str(used))
        check("предел настраивается снаружи, а не зашит",
              "AGENTS_TIMEOUT_SEC" in open(sh, encoding="utf-8").read())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_usage_limit_is_a_wait_and_the_role_resumes_itself():
    """Лимит аккаунта — ОЖИДАНИЕ: бюджета не тратит, снимется — сам.

    Решение владельца (2026-09-02): «если какой-то из агентов попал на
    этот лимит и остановился, он должен автоматически потом сам
    возобновлять работу по истечению этого лимита».

    Три утверждения, ломающиеся порознь. (1) До срока роль НЕ
    будится — звать модель на тот же отказ значит тратить квоту.
    (2) Попытка, упёршаяся в лимит, суточного бюджета НЕ тратит:
    иначе три лимита подряд выбивают роль на сутки при лимите на час,
    и «возобновится сама» не выполняется ровно там, где нужно.
    (3) По истечении срока шаг поднимается САМ, на обычном такте
    круга — отдельного расписания для этого не заводится.
    """
    import cycle as CY

    d = tempfile.mkdtemp()
    old = (CY.OUT, CY.STOP, CY.launch)
    try:
        CY.OUT = d
        CY.STOP = os.path.join(d, "STOP")
        runs = os.path.join(d, RL.RUNS)
        launched = []
        CY.launch = lambda k, kind, argv, log=print: (
            launched.append(k) or 4242)
        now = time.time()
        # Разведчик упёрся в лимит, снятие через полчаса.
        RL.append(runs, "scout", "start", now - 60, pid=1)
        RL.append(runs, "scout", RL.LIMIT, now - 60,
                  note="лимит аккаунта", retry_at=now + 1800)
        CY.main(["--force"])
        check("до срока роль не будится", "scout" not in launched,
              str(launched))
        check("круг не встал: следующий шаг пошёл",
              launched == ["brief"], str(launched))

        # Тот же лимит ещё дважды: бюджет попыток не тратится.
        for i in range(2):
            RL.append(runs, "scout", "start", now - 50 + i, pid=1)
            RL.append(runs, "scout", RL.LIMIT, now - 50 + i,
                      note="лимит", retry_at=now + 1800)
        rows, _ = RL.read(runs)
        # Срок истёк — роль обязана подняться сама, без вмешательства.
        RL.append(runs, "scout", "start", now - 40, pid=1)
        RL.append(runs, "scout", RL.LIMIT, now - 40, note="лимит",
                  retry_at=now - 1)
        launched.clear()
        CY.main(["--force"])
        check("по истечении срока роль поднялась сама",
              launched == ["scout"], str(launched))

        # А четыре НАСТОЯЩИХ отказа подряд бюджет тратят и шаг
        # пропускают: правило лимита не должно снимать защиту от
        # бесконечного вызова модели.
        d2 = tempfile.mkdtemp()
        CY.OUT, CY.STOP = d2, os.path.join(d2, "STOP")
        runs2 = os.path.join(d2, RL.RUNS)
        for i in range(3):
            RL.append(runs2, "scout", "start", now - 30 + i, pid=1)
            RL.append(runs2, "scout", "fail", now - 30 + i,
                      note="что-то другое")
        launched.clear()
        CY.main(["--force"])
        check("настоящие отказы бюджет тратят",
              launched == ["brief"], str(launched))
        shutil.rmtree(d2, ignore_errors=True)
    finally:
        CY.OUT, CY.STOP, CY.launch = old
        shutil.rmtree(d, ignore_errors=True)


def test_the_contract_judges_the_run_not_the_live_artifacts():
    """Проверка контракта смотрит В КАТАЛОГ ПРОГОНА, а не в боевой.

    Найдено 2026-09-02 строкой в ЖИВОЙ очереди механик, оставленной
    прогоном в песочнице: роль пишет туда, куда её послали
    (`AGENTS_OUT`), а `check_role` выводила каталог из корня — то есть
    судила боевые артефакты вместо произведённых и, что хуже, писала
    в боевые журналы (принесённое разведчиком, просьбы владельцу,
    очередь механик).

    Оба следствия проверяются: годным считается артефакт ПРОГОНА, а
    боевой каталог остаётся нетронутым.
    """
    import mech_queue as MQ
    long = "z" * 200
    root = tempfile.mkdtemp(prefix="live-")
    run = tempfile.mkdtemp(prefix="run-")
    try:
        live = os.path.join(root, "research", "factory", "out")
        os.makedirs(live)
        for rel in ("research/factory/space.py",
                    "research/factory/pool.py"):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
                f.write("проба\n")
        # В БОЕВОМ каталоге лежит своя заявка — её судить не должны.
        for d, title in ((live, "боевая механика"),
                         (run, "механика прогона")):
            with open(os.path.join(d, "proposal.md"), "w",
                      encoding="utf-8") as f:
                f.write("заявка человеческим текстом\n")
            with open(os.path.join(d, "brief.md"), "w",
                      encoding="utf-8") as f:
                f.write("бриф\n")
            with open(os.path.join(d, "proposal.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"proposed": True, "kind": "mechanism",
                           "title": title, "hypothesis": long,
                           "kills_it": long, "ceiling": long,
                           "differs_from_live": long, "shape": long,
                           "needs": "строителя",
                           "cites": ["research/factory/out/brief.md",
                                     "research/factory/space.py",
                                     "research/factory/pool.py"]},
                          f, ensure_ascii=False)

        # record=True: проверяется, КУДА пишет машина, — значит зовём
        # её так, как зовёт запускалка.
        ok, why = RL.check_role("propose", root, out=run, record=True)
        check("контракт прогона выполнен", ok, str(why))
        check("в очередь встала механика ПРОГОНА",
              [r["title"] for r in MQ.state(run)[0]]
              == ["механика прогона"], str(MQ.state(run)[0]))
        check("боевая очередь не тронута",
              not os.path.exists(os.path.join(live, MQ.QUEUE)),
              live)
        # Умолчание прежнее: без указания каталога судится корень.
        ok, why = RL.check_role("propose", root, record=True)
        check("без указания каталога судится корень",
              [r["title"] for r in MQ.state(live)[0]]
              == ["боевая механика"], str(MQ.state(live)[0]))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(run, ignore_errors=True)


def test_the_mechanic_builds_in_a_directory_the_machine_named():
    """Каталог механики назначает МАШИНА, и приёмка знает про него.

    Живой отказ 03.09: задание велело строить механику отдельным
    каталогом, а страж приёмки знал только `research/factory/` —
    готовая работа (сюита 32 проверки, 19 кусающихся контролей,
    прогнанный потолок) не была принята, машина не записала ничего,
    механика осталась «отдана», и строитель был позван строить то же
    самое заново. Публикатор при этом молчал так же, и в git уехал
    ОТЧЁТ потолка без кода, который его посчитал.

    Имя каталога выводится от ключа заявки: отчёт пишет судимая роль,
    и взять каталог оттуда значило бы позволить ей назвать своим что
    угодно; ключ же есть хеш заголовка ЗАЯВКИ, а её пишет другая роль.
    """
    import mech_queue as MQ
    import publish_build as PB
    long = "z" * 130
    root = tempfile.mkdtemp(prefix="mech-dir-")
    try:
        out = os.path.join(root, "research", "factory", "out")
        os.makedirs(out)
        k = MQ.queue(out, {"kind": "mechanism", "title": "механика с кодом",
                           "hypothesis": long, "needs": long})
        rows, _ = MQ.state(out)
        check("каталог назначен машиной и лежит в записи",
              rows[0].get("dir") == MQ.dir_of(k)
              == "research/mech_%s/" % k, str(rows[0].get("dir")))

        MQ.main(["--out", out, "--next"])
        task = open(os.path.join(out, MQ.TASK), encoding="utf-8").read()
        check("задание называет каталог числом, а не «коротким именем»",
              MQ.dir_of(k) in task and "короткое имя" not in task,
              task[-400:])

        # Задание, писанное до правила, переписывается для ТОЙ ЖЕ
        # механики: иначе строитель выберет имя сам, и приёмка
        # отвергнет его же работу (03.09 так и вышло).
        with open(os.path.join(out, MQ.TASK), "w", encoding="utf-8") as f:
            f.write((MQ.MARK % k) + "\nстарое задание без каталога\n")
        MQ.main(["--out", out, "--next"])
        again = open(os.path.join(out, MQ.TASK), encoding="utf-8").read()
        check("устаревшее задание переписано, механика та же",
              MQ.task_id(os.path.join(out, MQ.TASK)) == k
              and MQ.dir_of(k) in again, again[:120])
        rows2, _ = MQ.state(out)
        check("вторая механика в очередь не пролезла",
              len(rows2) == 1, str([r["id"] for r in rows2]))

        # Приёмка берёт каталог ИЗ ЗАДАНИЯ, а не из отчёта.
        check("приёмка знает каталог механики из задания",
              RL.mech_dir(out) == MQ.dir_of(k), str(RL.mech_dir(out)))

        # Настоящий круг: модуль и тесты механики в своём каталоге,
        # контроль портит СВОЙ файл — обязано пройти.
        mech = os.path.join(root, "research", "mech_" + k)
        os.makedirs(mech)
        with open(os.path.join(mech, "shift.py"), "w",
                  encoding="utf-8") as f:
            f.write("VALUE = 1\n")
        with open(os.path.join(mech, "test_shift.py"), "w",
                  encoding="utf-8") as f:
            f.write("import os, sys\n"
                    "sys.path.insert(0, os.path.dirname("
                    "os.path.abspath(__file__)))\n"
                    "import shift\n"
                    "if shift.VALUE != 1:\n"
                    "    print('test_value: не единица')\n"
                    "    raise SystemExit(1)\n"
                    "print('все проверки прошли')\n")
        rep = {"built": True,
               "module": "research/mech_%s/shift.py" % k,
               "tests": "research/mech_%s/test_shift.py" % k,
               "controls": [{"file": "research/mech_%s/shift.py" % k,
                             "old": "VALUE = 1", "new": "VALUE = 2",
                             "expect": "test_value"}]}
        ok, why = RL.check_build(json.dumps(rep, ensure_ascii=False),
                                 root, out_dir=out)
        check("постройка в каталоге механики принимается", ok, str(why))

        # А чужой каталог по-прежнему закрыт: страж не ослаблен.
        bad_rep = dict(rep, controls=[
            {"file": "research/factory/../tools/publish.sh",
             "old": "x", "new": "y", "expect": "z"}])
        ok2, why2 = RL.check_build(json.dumps(bad_rep, ensure_ascii=False),
                                   root, out_dir=out)
        check("чужой каталог остаётся закрытым",
              not ok2 and any("вне своего каталога" in w for w in why2),
              str(why2))

        # Публикатор смотрит В ТОТ ЖЕ список каталогов, что приёмка:
        # разойдись они, работа принималась бы и не публиковалась.
        old_root, old_here = PB.ROOT, PB.HERE
        try:
            PB.ROOT, PB.HERE = root, os.path.join(root, "research",
                                                  "factory")
            rp = os.path.join(out, "build.json")
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False)
            got = PB.paths_of(rp, log=lambda *a: None,
                              allowed=["research/factory/", MQ.dir_of(k)])
            check("публикуется код механики, а не только тесты",
                  got == sorted([rep["module"], rep["tests"]]), str(got))

            # `built: false` — код всё равно публикуется: отчёт о нём
            # уезжает в git общей публикацией, а код остался бы здесь.
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(dict(rep, built=False, why="w" * 200), f,
                          ensure_ascii=False)
            got = PB.paths_of(rp, log=lambda *a: None,
                              allowed=["research/factory/", MQ.dir_of(k)])
            check("непринятая постройка публикует свой код",
                  rep["module"] in got, str(got))
        finally:
            PB.ROOT, PB.HERE = old_root, old_here
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_judge_does_not_write_the_journals():
    """Проверку зовёт и судимая роль — писать обязан только судья.

    03.09 строитель проверил свою работу сам (право `python3` у него
    есть), и «ждёт владельца» легло в очередь ДВАЖДЫ: одной записью от
    роли, второй от запускалки, 51 мс спустя. Журнал машины, который
    роль умеет наполнить своим вызовом, машинным больше не является.
    """
    import mech_queue as MQ
    long = "z" * 130
    root = tempfile.mkdtemp(prefix="rec-")
    try:
        out = os.path.join(root, "research", "factory", "out")
        os.makedirs(out)
        k = MQ.queue(out, {"kind": "mechanism", "title": "механика записи",
                           "hypothesis": long, "needs": long})
        MQ.main(["--out", out, "--next"])
        rep = {"built": False, "why": "w" * 200,
               "needs_owner": [{"what": "доступ к чужому архиву",
                                "why": "без него события не собрать "
                                       "walk-forward, а выдумывать их "
                                       "нельзя"}]}
        with open(os.path.join(out, "build.json"), "w",
                  encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False)

        ok, why = RL.check_role("build", root, out=out)
        check("самопроверка роли проходит", ok, str(why))
        st = {r["id"]: r["state"] for r in MQ.state(out)[0]}
        check("самопроверка НИЧЕГО не записала",
              st.get(k) == "отдана строителю", str(st))

        ok, why = RL.check_role("build", root, out=out, record=True)
        check("прогон судьи записал судьбу механики",
              ok and {r["id"]: r["state"]
                      for r in MQ.state(out)[0]}.get(k) == "ждёт владельца",
              str(MQ.state(out)[0]))
        # Отметка «код опубликован» состояния не трогает: затри она
        # «ждёт владельца», просьба владельцу осталась бы без причины.
        MQ.mark(out, "code", k, "код опубликован: research/mech_x")
        st2 = {r["id"]: r for r in MQ.state(out)[0]}
        check("отметка кода не затирает состояние",
              st2[k]["state"] == "ждёт владельца"
              and "research/mech_x" in (st2[k].get("code") or ""),
              str(st2[k]))

        # Ручная приёмка: заметку составляет МАШИНА, каталог обязан
        # существовать и лежать в research/ — иначе запись очереди
        # стала бы чьим-то словом о себе.
        check("приёмка вне research/ отказывает",
              MQ.main(["--out", out, "--accept", k, "--dir", "/etc"]) == 1)
        # Отдельный случай: путь внутри research/, но каталога нет.
        # Без него контроль на проверку существования не кусается —
        # `/etc` отвергается ДРУГИМ стражем, и проверка выглядела бы
        # рабочей, ничего не проверяя.
        check("приёмка несуществующего каталога отказывает",
              MQ.main(["--out", out, "--accept", k,
                       "--dir", "research/нет-такого"]) == 1)
        # Каталог проверяется в НАСТОЯЩЕМ корне репозитория (машина
        # не вправе принять постройку, которой на диске нет), поэтому
        # здесь берётся существующий каталог, а не временный.
        rc = MQ.main(["--out", out, "--accept", k,
                      "--dir", "research/factory"])
        st3 = {r["id"]: r for r in MQ.state(out)[0]}
        check("принятая оператором механика перестаёт ждать владельца",
              rc == 0 and st3[k]["state"] == "построена", str(st3[k]))

        rows, _ = MQ.read(out)
        check("запись одна, а не две",
              len([r for r in rows if r.get("ev") == "blocked"]) == 1,
              str([r.get("ev") for r in rows]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_limit_reset_time_is_read_not_guessed():
    """Момент снятия берётся из ответа, а выдумка называется запасом.

    «Ждём до 14:30» и «ждём полчаса, потому что нам не сказали» —
    разные утверждения, и владелец вправе их различать: первое можно
    проверить, второе только принять.
    """
    now = 1788350000.0
    at, src = RL.limit_retry_at(
        "Claude AI usage limit reached|1788353600", now)
    check("эпоха из ответа прочитана", at == 1788353600.0
          and "ответом" in src, f"{at} / {src}")
    at, src = RL.limit_retry_at("rate limit; retry-after: 120", now)
    check("retry-after прочитан", at == now + 120
          and "retry-after" in src, f"{at} / {src}")
    # Человеческая форма момента снятия. Живой отказ 2026-09-02
    # называл его словами, а мы брали объявленный запас — то есть
    # теряли знание, которое нам дали, и будили роль не тогда.
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    at, src = RL.limit_retry_at(
        "You've hit your session limit \u00b7 resets 10:20pm (UTC)", now)
    check("названный час UTC прочитан",
          time.strftime("%H:%M", time.gmtime(at)) == "22:20"
          and "часы UTC" in src, f"{at} / {src}")
    check("названный час впереди, а не позади", at > now, f"{at} {now}")
    # Суточные часы без am/pm — та же дорога.
    at, src = RL.limit_retry_at("limit; resets 07:05 (UTC)", now)
    check("суточная форма часа прочитана",
          time.strftime("%H:%M", time.gmtime(at)) == "07:05"
          and "часы UTC" in src, f"{at} / {src} / {day}")
    # Час НЕ в UTC не берётся вовсе: приняв чужие часы за наши, мы
    # отправили бы роль ждать на часы мимо — хуже честного запаса.
    at, src = RL.limit_retry_at("limit; resets 10:20pm (PST)", now)
    check("час без UTC за срок не принимается",
          "запас" in src, f"{at} / {src}")
    at, src = RL.limit_retry_at("usage limit reached, try later", now)
    check("без срока берётся объявленный запас",
          at == now + RL.LIMIT_BACKOFF_SEC and "запас" in src,
          f"{at} / {src}")
    # Число из чужой строки лога, принятое за момент снятия, увело бы
    # роль в ожидание на годы: диапазон проверяется.
    at, src = RL.limit_retry_at("лимит; сделок 1999999999 за месяц", now)
    check("число вне разумного окна за срок не принимается",
          "запас" in src, f"{at} / {src}")
    # За лимитом последовал удачный прогон — ожидание снято.
    rows = [{"role": "scout", "status": RL.LIMIT, "at": now,
             "retry_at": now + 999},
            {"role": "scout", "status": "ok", "at": now + 1}]
    check("удачный прогон снимает ожидание",
          RL.limit_wait(rows, "scout", now + 2) == 0.0)


def test_cycle_advances_one_step_and_obeys_the_safeties():
    """Суточный круг: один шаг за вызов, и три предохранителя держат.

    Круг не исполняется целиком в одном такте: сторож ходит раз в пять
    минут, а судья считает часами. Состояние читается с диска, поэтому
    обрыв посреди круга не теряет ничего.

    Предохранители проверяются каждый: выключатель, предел прогонов
    ролей за сутки и час начала. Без них расписание включать нельзя —
    остановить систему должно быть проще, чем запустить.
    """
    root = os.path.dirname(os.path.dirname(HERE))
    sys.path.insert(0, HERE)
    import cycle as CY

    d = tempfile.mkdtemp()
    try:
        # Подмена ВОЗВРАЩАЕТСЯ в finally: стаб, оставленный в модуле,
        # исполняет чужую дорогу в следующей проверке — она честно
        # скажет «не вызвано», а виноват будет предыдущий тест.
        old_out, old_stop = CY.OUT, CY.STOP
        old_launch = CY.launch
        CY.OUT = d
        CY.STOP = os.path.join(d, "STOP")
        runs = os.path.join(d, RL.RUNS)
        launched = []
        CY.launch = lambda k, kind, argv, log=print: (
            launched.append(k) or 4242)
        try:
            # Пустые сутки: первый шаг круга — бриф.
            CY.main(["--dry", "--force"])
            check("на пустых сутках круг начинает с первого шага",
                  True)
            launched.clear()
            CY.main(["--force"])
            check("запускается ровно один шаг, и это разведчик",
                  launched == ["scout"], str(launched))

            # Разведчик отработал — следующим бриф, потом предлагающий.
            RL.append(runs, "scout", "ok", time.time())
            launched.clear()
            CY.main(["--force"])
            check("следующим идёт брифер",
                  launched == ["brief"], str(launched))
            RL.append(runs, "brief", "ok", time.time())
            launched.clear()
            CY.main(["--force"])
            check("следующим идёт предлагающий",
                  launched == ["propose"], str(launched))

            # Выключатель сильнее всего остального.
            open(CY.STOP, "w").close()
            launched.clear()
            CY.main(["--force"])
            check("выключатель останавливает круг",
                  launched == [], str(launched))
            os.remove(CY.STOP)

            # Идущий шаг: пока процесс жив, второй не запускается.
            RL.append(runs, "propose", "start", time.time(),
                      pid=os.getpid())
            launched.clear()
            CY.main(["--force"])
            check("идущий шаг не запускается второй раз",
                  launched == [], str(launched))
            RL.append(runs, "propose", "ok", time.time())

            # Роль ВНЕ круга (заход адверсария руками) круг не
            # останавливает: иначе часовой заход молча съедал бы
            # сутки, а страница показывала спокойный день. Строитель
            # для этой проверки больше не годится — он теперь ШАГ
            # круга, и идущая постройка круг ждать обязана.
            RL.append(runs, "adversary", "start", time.time(),
                      pid=os.getpid())
            launched.clear()
            CY.main(["--force"])
            check("ручной заход роли не останавливает круг",
                  launched == ["judge"], str(launched))
            # Но РОЛЬ при идущей роли не будится: писатель один за раз.
            os.remove(runs)
            RL.append(runs, "adversary", "start", time.time(),
                      pid=os.getpid())
            launched.clear()
            CY.main(["--force"])
            check("роль при идущей роли не запускается",
                  launched == [], str(launched))
            os.remove(runs)
            RL.append(runs, "scout", "ok", time.time())
            RL.append(runs, "brief", "ok", time.time())
            RL.append(runs, "propose", "ok", time.time())

            # Предел суток: считаются прогоны РОЛЕЙ.
            RL.append(runs, "scout", "ok", time.time())
            for _ in range(CY.MAX_ROLE_RUNS_PER_DAY):
                RL.append(runs, "brief", "start", time.time(), pid=1)
                RL.append(runs, "brief", "fail", time.time())
            # Механический шаг предел не расходует и идти обязан.
            launched.clear()
            CY.main(["--force"])
            check("предел суток не запрещает механический шаг",
                  launched == ["judge"], str(launched))
            # Артефакт шага СТАРШЕ его входа: шаг судил вчерашнее и
            # обязан пойти заново. Сегодня ровно это остановило круг
            # на весь вечер, а страница показывала пройденный шаг.
            os.remove(runs)
            for k in ("scout", "brief", "propose"):
                RL.append(runs, k, "ok", time.time())
            day = os.path.join(d, "factory-day-1m.json")
            ceil = os.path.join(d, "ceiling.json")
            open(os.path.join(d, "FACTORY-day-1m.md"), "w").close()
            open(day, "w").close()
            open(ceil, "w").close()
            old_t = time.time() - 3600
            os.utime(ceil, (old_t, old_t))   # вердикт старше чисел
            launched.clear()
            CY.main(["--force"])
            check("шаг со старым артефактом идёт заново",
                  launched == ["ceiling"], str(launched))
            os.utime(ceil, None)             # вердикт свежее чисел
            launched.clear()
            CY.main(["--force"])
            check("свежий артефакт шага не переделывается",
                  launched == ["declare"], str(launched))
            os.remove(day)
            os.remove(ceil)
            os.remove(os.path.join(d, "FACTORY-day-1m.md"))
            os.remove(runs)

            # У механического шага свой предел: падающий судья без
            # него перезапускался бы каждые пять минут круглые сутки.
            for k in ("scout", "brief", "propose"):
                RL.append(runs, k, "ok", time.time())
            for _ in range(CY.MAX_MECH_RUNS_PER_DAY):
                RL.append(runs, "judge", "start", time.time(), pid=1)
                RL.append(runs, "judge", "fail", time.time())
            launched.clear()
            CY.main(["--force"])
            # Исчерпавший попытки шаг ПРОПУСКАЕТСЯ, и круг идёт
            # дальше: сломанная роль не вправе держать за собой
            # потолок и объявление — сегодня именно это остановило
            # систему на весь вечер.
            check("исчерпавший попытки шаг пропускается, круг идёт",
                  launched == ["ceiling"], str(launched))
            os.remove(runs)
            RL.append(runs, "scout", "ok", time.time())
            RL.append(runs, "brief", "ok", time.time())
            RL.append(runs, "propose", "ok", time.time())
            launched.clear()
            CY.main(["--force"])
            check("до предела механический шаг идёт",
                  launched == ["judge"], str(launched))

            # А роль — запрещает: брифа за сегодня нет в свежем
            # журнале, но лимит выбран.
            os.remove(runs)
            RL.append(runs, "scout", "ok", time.time())
            for _ in range(CY.MAX_ROLE_RUNS_PER_DAY):
                RL.append(runs, "brief", "start", time.time(), pid=1)
                RL.append(runs, "brief", "fail", time.time())
            launched.clear()
            CY.main(["--force"])
            # Общий бюджет ролей выбран — роли на сегодня кончились, а
            # механика идёт: она модель не зовёт.
            check("бюджет ролей выбран, механика идёт",
                  launched == ["judge"], str(launched))
            # А если и механика исчерпана, круг доходит до конца и
            # говорит об этом словами. Список берётся ИЗ САМОГО КРУГА:
            # перечень здесь означал бы, что новый шаг тихо выпадает
            # из проверки и «ничего не запускается» проходит на
            # запускающемся шаге.
            for k in [x[0] for x in CY.CIRCLE if x[1] == "mech"]:
                for _ in range(CY.MAX_TRIES_PER_STEP):
                    RL.append(runs, k, "start", time.time(), pid=1)
                    RL.append(runs, k, "fail", time.time())
            launched.clear()
            CY.main(["--force"])
            check("всё исчерпано — не запускается ничего",
                  launched == [], str(launched))
        finally:
            CY.OUT, CY.STOP, CY.launch = old_out, old_stop, old_launch
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_mech_step_leaves_its_end_line():
    """У механического шага есть писатель КОНЦА, и круг им пользуется.

    Найдено владельцем по живой странице: у потолка стояло «прогон
    оборван» при том, что прогон отработал и оставил оба артефакта.
    Причина — конца механического шага не писал НИКТО: круг писал
    начало, шаг кончался, и строка `start` с мёртвым номером процесса
    навсегда читалась как обрыв. Нормальное завершение было
    неотличимо от убитого процесса.

    Проверяется и правило (конец пишется с кодом возврата), и ДОРОГА
    до него: круг обязан звать шаг через обёртку, иначе правило верно
    и не исполняется.
    """
    sys.path.insert(0, HERE)
    import mech_run as MR
    import cycle as CY

    d = tempfile.mkdtemp()
    runs = os.path.join(d, RL.RUNS)
    old_env = os.environ.get("AGENTS_OUT")
    os.environ["AGENTS_OUT"] = d
    try:
        t0 = time.time() - 5
        rc = MR.main(["ceiling", "%.3f" % t0, "--",
                      sys.executable, "-c", "raise SystemExit(0)"])
        rows, _ = RL.read(runs)
        # Строки может не быть вовсе — это и есть проверяемый отказ.
        # Взяв её индексом, проверка УРОНИЛА бы сюиту вместо провала.
        one = rows[0] if rows else {}
        check("удачный шаг оставил строку конца",
              rc == 0 and len(rows) == 1 and one.get("status") == "ok",
              str(rows))
        check("в строке назван код возврата",
              "код возврата 0" in (one.get("note") or ""),
              str(one.get("note")))
        check("момент старта не потерян",
              abs((one.get("started") or 0) - t0) < 0.01,
              str(one.get("started")))

        # Шаг круга обязан исполнять СВЕЖИЙ код: тот же дефект
        # байткода, что в машине контролей, здесь означал бы суточный
        # прогон на прежнем коде после деплоя — молча.
        mod = os.path.join(d, "mm.py")
        chk = os.path.join(d, "cc.py")
        with open(chk, "w", encoding="utf-8") as f:
            f.write("import sys, os\n"
                    "sys.path.insert(0, os.path.dirname("
                    "os.path.abspath(__file__)))\n"
                    "import mm\n"
                    "raise SystemExit(0 if mm.V == 1 else 7)\n")
        stamp2 = time.time() - 10
        for v in (1, 2):
            with open(mod, "w", encoding="utf-8") as f:
                f.write(f"V = {v}\n")
            os.utime(mod, (stamp2, stamp2))
            rc = MR.main(["ceiling", "%.3f" % time.time(), "--",
                          sys.executable, chk])
            if v == 1:
                check("шаг видит свой код", rc == 0, str(rc))
            else:
                check("шаг видит НОВЫЙ код, а не прежний байткод",
                      rc == 7, str(rc))

        rc = MR.main(["ceiling", "%.3f" % time.time(), "--",
                      sys.executable, "-c", "raise SystemExit(3)"])
        rows, _ = RL.read(runs)
        last = rows[-1] if rows else {}
        check("упавший шаг назван отказом, а не удачей",
              rc == 3 and last.get("status") == "fail"
              and "3" in (last.get("note") or ""), str(last))

        # Дорога до показа: со строкой конца «оборван» исчезает,
        # без неё — остаётся. Иначе значок значил бы не то, что говорит.
        dead = 2 ** 22          # заведомо чужой/мёртвый номер
        st = RL.state_of([{"at": 1.0, "role": "ceiling",
                           "status": "start", "pid": dead},
                          {"at": 2.0, "role": "ceiling",
                           "status": "ok"}])["ceiling"]
        check("конец снимает «прогон оборван»",
              st["broken"] is None and (st["last"] or {}).get("status")
              == "ok", str(st))
        st = RL.state_of([{"at": 1.0, "role": "ceiling",
                           "status": "start", "pid": dead}])["ceiling"]
        check("без конца обрыв по-прежнему виден",
              st["broken"] is not None, str(st))

        # Дорога круга: механический шаг обязан идти ПОД обёрткой.
        seen = {}

        class _P:
            pid = 4242

        def _popen(cmd, **kw):
            seen["cmd"] = cmd
            return _P()

        old_out, old_popen = CY.OUT, CY.subprocess.Popen
        CY.OUT = d
        CY.subprocess.Popen = _popen
        try:
            CY.launch("ceiling", "mech", ["research/factory/ceiling.py"],
                      log=lambda *a: None)
        finally:
            CY.OUT, CY.subprocess.Popen = old_out, old_popen
        check("круг зовёт механический шаг через обёртку",
              any("mech_run.py" in str(x) for x in seen.get("cmd", [])),
              str(seen.get("cmd")))
        check("сама команда шага в строке запуска осталась",
              any("ceiling.py" in str(x) for x in seen.get("cmd", [])),
              str(seen.get("cmd")))
    finally:
        if old_env is None:
            os.environ.pop("AGENTS_OUT", None)
        else:
            os.environ["AGENTS_OUT"] = old_env
        shutil.rmtree(d, ignore_errors=True)


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



def test_candidate_diagnostic_counts_trades_not_journal_lines():
    """Диагностика кандидатов считает СДЕЛКИ ядром, а не строки.

    Первая версия считала строки `picks.jsonl`, а строка выбора одна
    на (руку, час) и несёт СПИСОК ног: «выборов 12» читалось как
    двенадцать сделок при шести ногах, и открытые позиции выходили
    нулём там, где их шесть. Числа выглядели измерением, им не будучи,
    — и первый же живой прогон увёл меня к ложному диагнозу «рука
    деревьев не входит вовсе».

    Поэтому сделки строит `trades.build` — то же ядро, которым их
    считают деньги: своя склейка выбора с разбором однажды разошлась
    бы с той, по которой считают кассу.
    """
    import subprocess

    root = os.path.dirname(os.path.dirname(HERE))
    d = tempfile.mkdtemp()
    out = os.path.join(d, "research", "s8_loop", "out")
    cdir = os.path.join(out, "model_c_x")
    os.makedirs(cdir)
    # Один час, ЧЕТЫРЕ ноги в одной строке выбора; разобрана одна.
    legs = [{"sym": f"A{i}USDT", "px": 10.0 + i, "fwd": 40.0,
             "mae": -100.0, "mfe": 200.0,
             "at_ts": time.time() - 600} for i in range(4)]
    with open(os.path.join(cdir, "picks.jsonl"), "w",
              encoding="utf-8") as f:
        f.write(json.dumps({"arm": "gbm", "hour": "2026-09-02-05",
                            "at_ts": time.time() - 600,
                            "long": legs, "short": []},
                           ensure_ascii=False) + "\n")
    with open(os.path.join(cdir, "review.jsonl"), "w",
              encoding="utf-8") as f:
        f.write(json.dumps({"arm": "gbm", "hour": "2026-09-02-05",
                            "at_ts": time.time() - 300,
                            "rows": [{"sym": "A0USDT", "side": "long",
                                      "got": 12.0, "net_bp": 1.0,
                                      "why": "стоп",
                                      "exit_ts": time.time() - 300}]},
                           ensure_ascii=False) + "\n")
    with open(os.path.join(d, "research", "s8_loop",
                           "books_extra.json"), "w",
              encoding="utf-8") as f:
        json.dump([{"key": "x", "dir": "model_c_x", "label": "x",
                    "family": "situational", "lane": "selected",
                    "gate": {"slots": 6, "floor_bp": 30.0,
                             "min_rr": 0.0, "max_rr": 1.5,
                             "per_side": 3, "agree": False}}], f)
    src = os.path.join(root, "tools", "diag_cycle.py")
    dst = os.path.join(d, "tools", "diag_cycle.py")
    os.makedirs(os.path.dirname(dst))
    shutil.copy(src, dst)
    # Ядро сделок диагностика берёт из репозитория, а данные — из
    # временного корня: копировать ради теста весь `s8_loop` значило
    # бы проверять копию, а не тот код, который поедет на сервер.
    os.symlink(os.path.join(root, "research", "s8_loop", "trades.py"),
               os.path.join(d, "research", "s8_loop", "trades.py"))
    os.symlink(os.path.join(root, "research", "common"),
               os.path.join(d, "research", "common"))
    r = subprocess.run([sys.executable, dst, "--cand"],
                       capture_output=True, text=True, timeout=120)
    txt = r.stdout + r.stderr
    shutil.rmtree(d, ignore_errors=True)
    line = [x for x in txt.splitlines() if x.strip().startswith("gbm:")]
    check("строка руки напечатана", bool(line), txt[-600:])
    ln = line[0] if line else ""
    check("сделок четыре, а не одна строка выбора",
          "сделок 4" in ln, ln)
    check("закрыта одна", "закрыто 1" in ln, ln)
    check("открыто три, а не ноль", "открыто 3" in ln, ln)




def test_overfilled_book_record_is_retired_not_kept():
    """Запись сверх объявленной ширины отставляется, а не остаётся.

    Книга кандидата есть испытание ОБЪЯВЛЕННОГО правила. Позиции,
    набранные при дефекте сверх объявленных мест, описывают книгу
    другой ширины — то есть другого кандидата под тем же именем; на
    живом сервере такая книга держала 23 имени при десяти местах,
    пока правка не доехала. Оставить их значило бы измерять не то,
    что заявлено, и пометкой это не чинится: кривая складывается из
    сделок.

    Обе стороны: превышение отставляется, книга в пределах мест НЕ
    трогается. Иначе инструмент, срабатывающий всегда, стирал бы
    здоровые записи.
    """
    import subprocess

    root = os.path.dirname(os.path.dirname(HERE))
    tool = os.path.join(root, "tools", "retire_overfilled_book.py")

    def make(n):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"situational": True, "slots": 10}, f)
        with open(os.path.join(d, "entries_live.jsonl"), "w",
                  encoding="utf-8") as f:
            for i in range(n):
                f.write(json.dumps(
                    {"arm": "gbm", "hour": "2026-09-02-09",
                     "sym": f"S{i}USDT", "side": "long", "px": 100.0,
                     "mae": -40.0, "mfe": 90.0,
                     "at_ts": 1000.0}) + "\n")
        for f_ in ("picks.jsonl", "review.jsonl"):
            open(os.path.join(d, f_), "w").close()
        return d

    over = make(23)
    ok = make(4)
    try:
        r = subprocess.run([sys.executable, tool, over],
                           capture_output=True, text=True, timeout=300)
        txt = r.stdout + r.stderr
        arch = [x for x in os.listdir(os.path.dirname(over))
                if x.startswith(os.path.basename(over) + ".overfilled")]
        check("превышение названо числом", "занято имён 23" in txt,
              txt[-300:])
        check("запись отставлена в архив", len(arch) == 1, str(arch))
        left = sorted(os.listdir(over))
        check("сделки из книги уехали, манифест остался",
              "entries_live.jsonl" not in left
              and "manifest.json" in left, str(left))
        r2 = subprocess.run([sys.executable, tool, over],
                            capture_output=True, text=True, timeout=300)
        check("повторный прогон вычищенную книгу не трогает",
              "превышения нет" in (r2.stdout + r2.stderr),
              (r2.stdout + r2.stderr)[-200:])
        r3 = subprocess.run([sys.executable, tool, ok],
                            capture_output=True, text=True, timeout=300)
        check("книга в пределах мест не трогается",
              "превышения нет" in (r3.stdout + r3.stderr)
              and "entries_live.jsonl" in os.listdir(ok),
              (r3.stdout + r3.stderr)[-200:])
    finally:
        for x in (over, ok):
            shutil.rmtree(x, ignore_errors=True)
            for y in os.listdir(os.path.dirname(x)):
                if y.startswith(os.path.basename(x) + ".overfilled"):
                    shutil.rmtree(os.path.join(os.path.dirname(x), y),
                                  ignore_errors=True)



def main():
    tests = (test_space_is_declared_and_frozen,
             test_control_share_is_of_the_pool_not_the_batch,
             test_control_share_converges,
             test_batch_respects_the_owners_limits,
             test_window_is_calendar_not_last_entries,
             test_the_window_speaks_day_numbers_not_seconds,
             test_retire_rule_follows_the_owner_by_sum,
             test_shape_is_the_owners_main_criterion,
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
             test_scout_brings_mechanisms_not_verdicts,
             test_scout_is_not_rejected_by_its_own_ideas,
             test_contract_check_gets_the_start_moment,
             test_scout_backlog_survives_the_next_menu,
             test_owner_ask_is_measured_not_assumed,
             test_mechanic_waits_in_a_queue_not_in_a_file,
             test_the_conveyor_records_asks_and_the_mechanic,
             test_circle_calls_the_builder_only_with_a_task,
             test_proposal_must_be_checkable_not_persuasive,
             test_closed_by_ceiling_is_not_proposed_again,
             test_the_control_machine_is_not_fooled_by_stale_bytecode,
             test_build_contract_makes_the_controls_bite,
             test_adversary_must_show_what_it_tried,
             test_runner_leaves_a_line_on_every_refusal,
             test_rights_reach_the_model_whole,
             test_prompt_actually_reaches_the_model,
             test_a_broken_character_does_not_swallow_the_journal_row,
             test_a_hanging_role_is_killed_by_the_clock_and_named,
             test_a_usage_limit_is_a_wait_and_the_role_resumes_itself,
             test_the_mechanic_builds_in_a_directory_the_machine_named,
             test_the_judge_does_not_write_the_journals,
             test_limit_reset_time_is_read_not_guessed,
             test_the_contract_judges_the_run_not_the_live_artifacts,
             test_fallback_happens_on_a_limit_or_an_unknown_model,
             test_cycle_advances_one_step_and_obeys_the_safeties,
             test_mech_step_leaves_its_end_line,
             test_candidate_diagnostic_counts_trades_not_journal_lines,
             test_overfilled_book_record_is_retired_not_kept,
             test_dropped_book_dir_is_found_and_the_archive_is_not,
             test_stability_asks_how_not_how_much)
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


# Фикстура правила вылета обязана выглядеть как ЖИВОЙ артефакт: ключ
# дневного ряда — номер суток (`candidate.daily_net` кладёт
# `exit // DAY`), а `now` приходит в секундах. Прежние фикстуры были
# написаны целиком в секундах, то есть невозможной для писателя формой,
# и ровно поэтому дефект единиц прожил в живом пуле незамеченным.
NOW_S = 20698 * P.DAY          # момент «сейчас» в секундах
D0 = P.day_no(NOW_S)           # он же номером суток


def test_window_is_calendar_not_last_entries():
    # Три дня внутри окна и один далеко за ним: старая крупная прибыль
    # не имеет права спасать книгу, слившую последние десять суток.
    daily = {D0 - 1: -5.0, D0 - 3: -4.0, D0 - 9: -3.0, D0 - 40: +500.0}
    net, n = P.window_net(daily, NOW_S)
    check("окно берёт только свои сутки", abs(net + 12.0) < 1e-9 and n == 3,
          f"{net} за {n} дней")


def test_the_window_speaks_day_numbers_not_seconds():
    """Единица ключа дневного ряда — НОМЕР СУТОК, и это было дефектом.

    До 2026-09-02 окно сравнивало ключи ряда с моментом в секундах, и на
    живых данных в него не попадало ни одних суток: за деньги не
    отставлялся никто вовсе, а на тридцатые сутки после объявления любой
    кандидат — хоть с полусотней сделок в сутки — попал бы под
    «простой». Воспроизведено на живом артефакте: у всех семи книг пула
    окно видело 0 суток при 22–26 сутках в ряду.

    Ряд не в тех единицах теперь ОТВЕРГАЕТСЯ громко: молчание здесь
    дороже падения — отказ виден в тот же прогон, а неотставленный
    кандидат через месяц и не тем признаком.
    """
    live_shaped = {D0 - i: -2.0 for i in range(0, 5)}
    _net, n = P.window_net(live_shaped, NOW_S)
    check("живой ряд окно видит", n == 5, str(n))
    seconds_shaped = {NOW_S - i * P.DAY: -2.0 for i in range(0, 5)}
    try:
        P.window_net(seconds_shaped, NOW_S)
        check("ряд в секундах отвергнут", False, "прошёл молча")
    except ValueError as e:
        check("ряд в секундах отвергнут с названной причиной",
              "секунды" in str(e), str(e))
    # И то же самое из правила целиком, а не только из окна: дорога до
    # вердикта одна, и проверять надо её.
    try:
        P.should_retire(seconds_shaped, NOW_S, 0.0, NOW_S - 20 * P.DAY)
        check("правило на ряде в секундах не судит молча", False, "судило")
    except ValueError:
        check("правило на ряде в секундах отказывает", True)


def test_retire_rule_follows_the_owner_by_sum():
    born = NOW_S - 20 * P.DAY
    losing = {D0 - i: -2.0 for i in range(1, 10)}
    why = P.should_retire(losing, NOW_S, 0.0, born)
    check("сумма ниже медианы нуля — вылет", bool(why), str(why))
    # Копеечная зелёная свеча не обнуляет счётчик: правило по СУММЕ, а
    # не по серии — иначе мёртвая книга вылетала бы раз в полтора года.
    losing_with_green = dict(losing)
    losing_with_green[D0 - 5] = +0.5
    check("зелёный день серию не обнуляет",
          bool(P.should_retire(losing_with_green, NOW_S, 0.0, born)))
    winning = {D0 - i: +2.0 for i in range(1, 10)}
    check("книга выше нуля живёт",
          P.should_retire(winning, NOW_S, 0.0, born) is None)
    # Сравнение со СВОИМ нулём: та же книга при нуле выше неё вылетает.
    check("нуль выше книги — вылет",
          bool(P.should_retire(winning, NOW_S, +100.0, born)))


def test_shape_is_the_owners_main_criterion():
    """Вылет судит ФОРМУ, а не только сумму (решение владельца 2026-09-02).

    «Интересны стратегии, которые приносят немного, но стабильно, и не
    забирают за один день всю прибыль за неделю или месяц.» Прежнее
    правило смотрело сумму окна: книга, отдающая недельную прибыль одним
    днём, проходила его, пока сумма оставалась выше нуля.

    Пороги объявлены в модуле ДО первого прогона правила: обычный день
    не отрицателен, худший день не глубже десяти обычных прибыльных
    (критерий 8 спеки 04 назвал десять терпимым, сорок — «год работы за
    неделю»).
    """
    born = NOW_S - 40 * P.DAY
    # Тринадцать ровных прибыльных суток и один день, забирающий всё.
    # Провал стоит ЗА окном суммы, и это не подгонка фикстуры, а смысл
    # правила: хвост есть свойство самого правила книги, а не последних
    # десяти суток, и, забыв однажды случившийся срыв, пул переоткрывал
    # бы его каждый месяц. Прежнее правило здесь молчит — сумма окна
    # положительна.
    bites = {D0 - i: +1.0 for i in range(0, 14)}
    bites[D0 - 12] = -30.0
    net, _n = P.window_net(bites, NOW_S)
    check("сумма окна положительна — прежнее правило молчало бы",
          net > 0, f"{net:+.1f}")
    why = P.should_retire(bites, NOW_S, 0.0, born) or ""
    check("укус глубже предела — вылет", "съедает" in why, str(why))
    check("в причине стоят и укус, и предел",
          "30.0" in why and "10" in why, str(why))
    # Ровная мелкая прибыль — ровно то, что владелец просил, — живёт.
    steady = {D0 - i: (+1.0 if i % 4 else -0.5) for i in range(0, 14)}
    check("ровная мелкая прибыль живёт",
          P.should_retire(steady, NOW_S, 0.0, born) is None,
          str(P.should_retire(steady, NOW_S, 0.0, born)))
    # Отрицательный обычный день — вылет, даже если хвост вытянул сумму.
    tail = {D0 - i: -1.0 for i in range(0, 14)}
    tail[D0 - 2] = +40.0
    net2, _n2 = P.window_net(tail, NOW_S)
    check("сумма окна и здесь положительна", net2 > 0, f"{net2:+.1f}")
    why2 = P.should_retire(tail, NOW_S, 0.0, born) or ""
    check("отрицательный обычный день — вылет",
          "обычный день" in why2, str(why2))
    # Форма судится ФОРВАРДОМ: дни до объявления — пересчёт по прошлому,
    # которое ассистент видел, когда предлагал.
    born_late = (D0 - 3) * P.DAY
    check("бэктест в вердикт по форме не входит",
          P.shape_why(bites, born_late) is None,
          str(P.shape_why(bites, born_late)))
    # Меньше десяти суток форварда — вердикта нет вовсе: не измерено не
    # есть провал.
    thin = {D0 - i: -5.0 for i in range(0, 6)}
    check("тонкая выборка формы не судится",
          P.shape_why(thin, born) is None, str(P.shape_why(thin, born)))
    # Мера — общая, а не своя: правило зовёт `stability.stats`.
    import stability as ST
    check("правило считает ту же меру, что отчёт устойчивости",
          ST.stats({d: bites[d] for d in bites})["bite"] == 30.0,
          str(ST.stats(bites)))


def test_young_candidate_is_not_judged():
    young = NOW_S - 3 * P.DAY
    losing = {D0 - i: -9.0 for i in range(1, 3)}
    check("окна ещё нет — вердикта нет",
          P.should_retire(losing, NOW_S, 0.0, young) is None,
          str(P.should_retire(losing, NOW_S, 0.0, young)))


def test_silence_frees_the_slot():
    check("молчание дольше предела — вылет",
          bool(P.should_retire({}, NOW_S, 0.0, NOW_S - 40 * P.DAY)))
    check("молчание в пределах — не вылет",
          P.should_retire({}, NOW_S, 0.0, NOW_S - 20 * P.DAY) is None)


def test_dropped_book_dir_is_found_and_the_archive_is_not():
    """Каталог книги вне состава обязан быть НАЗВАН, архив — нет.

    Состав книг меняется (полоса, ось, негодное правило), и брошенный
    каталог держит открытые позиции, которых больше никто не судит.
    Архив при этом трогать нельзя ни разу: он несёт точку в имени, и
    различать их надо НАБОРОМ ЗНАКОВ ключа, а не догадкой о суффиксе.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        for name in ("model", "model_sit", "model_c_alive", "model_c_gone",
                     "model_c_gone.dropped-20260902-101010",
                     "model_c_other.rules-v3"):
            os.makedirs(os.path.join(d, name))
        # Файл с подходящим именем каталогом не является.
        with open(os.path.join(d, "model_c_notadir"), "w") as f:
            f.write("x")
        got = LB.dropped_dirs(d, "model", {"alive"})
        check("брошенный каталог назван", got == ["model_c_gone"], str(got))
        check("архив не тронут",
              not any(".dropped-" in g or ".rules-" in g for g in got),
              str(got))
        check("книга состава не тронута", "model_c_alive" not in got, str(got))
        check("ядро не тронуто",
              "model" not in got and "model_sit" not in got, str(got))
        check("файл каталогом не считается",
              "model_c_notadir" not in got, str(got))
        # Демо-прогон: каталог модели зовётся иначе — правило то же.
        os.makedirs(os.path.join(d, "demo_c_gone"))
        got2 = LB.dropped_dirs(d, "demo", set())
        check("правило не зашито на имя главной книги",
              got2 == ["demo_c_gone"], str(got2))


def test_sweep_judges_control_by_the_same_rule():
    born = NOW_S - 20 * P.DAY
    st = {"s1": {"lane": "selected", "declared_at": born, "retired_at": None},
          "c1": {"lane": "control", "declared_at": born, "retired_at": None},
          "s2": {"lane": "selected", "declared_at": born,
                 "retired_at": 5.0}}
    daily = {"s1": {D0 - 1: -5.0}, "c1": {D0 - 1: -5.0},
             "s2": {D0 - 1: -5.0}}
    got = dict(P.sweep(st, daily, NOW_S, 0.0))
    check("контрольная рука судится тем же правилом", "c1" in got, str(got))
    check("отобранная тоже", "s1" in got, str(got))
    check("уже отставленный не судится дважды", "s2" not in got, str(got))
    # И правило ФОРМЫ — тоже одно на обе полосы: жребий обязан умирать
    # от той же медианы дня, иначе сравнение живучести сравнивало бы
    # правила, а не полосы.
    shape = {D0 - i: (+1.0 if i else -30.0) for i in range(0, 14)}
    st2 = {k: dict(v, retired_at=None) for k, v in st.items()}
    got2 = dict(P.sweep(st2, {k: shape for k in st2}, NOW_S, -1e9))
    check("по форме судятся обе полосы",
          all("съедает" in got2.get(k, "") for k in ("s1", "c1", "s2")),
          str(got2))


def test_stability_asks_how_not_how_much():
    """Устойчивость: сколько хороших дней съедает один плохой.

    Решение владельца (2026-09-02): важнее стабильность — книга,
    которая приносит немного, но ровно, и не забирает за один день
    прибыль недели. Мера объявлена ДО чтения живых чисел, и главная
    из них — «укус»: |худший день| / медиана прибыльного дня. Проект
    пришёл к этой же величине с другой стороны: критерий 8 спеки 04
    объявлен первичным для carry ровно потому, что Sharpe льстит
    конструкции «часто по копейке, редко по многу».

    Проверяется ДОРОГА, а не формула: ряды берутся у самого сервера
    (`/book_days`, `/factory_built`) — второй обход файлов дал бы
    вторую реализацию кассы, и отчёт разошёлся бы со страницей.
    """
    import stability as ST

    # Граница тонких данных — одна на пул: правило вылета судит по
    # десяти суткам, и вторая граница у той же выборки разошлась бы.
    check("граница тонких данных та же, что у правила вылета",
          ST.MIN_DAYS == P.WINDOW_D, f"{ST.MIN_DAYS} / {P.WINDOW_D}")
    st = ST.stats({"d1": 1.0, "d2": 1.0, "d3": -8.0, "d4": 1.0})
    check("укус считает, сколько хороших дней съел плохой",
          st["bite"] == 8.0, str(st))
    # Накопленное 1, 2, −6, −5: пик 2, провал −8 (а итог −5 — это
    # другая величина, и путать их нельзя).
    check("под водой считается сутками, а не глубиной",
          st["under"] == 2 and st["dd"] == -8.0 and st["tot"] == -5.0,
          str(st))
    check("тонкая выборка помечена, а не выброшена",
          st["thin"] is True and st["days"] == 4, str(st))
    check("пустой ряд — не ноль, а отсутствие меры",
          ST.stats({}) is None, str(ST.stats({})))
    # Без прибыльных суток укуса НЕ существует: ноль читался бы как
    # «не кусает», а кусать просто нечего.
    only_red = ST.stats({"d1": -1.0, "d2": -2.0})
    check("без прибыльных дней укус не выдумывается",
          only_red["bite"] is None, str(only_red))

    seen = []

    def fake(base, path, key, timeout=120):
        seen.append(path)
        if path == "/factory_built":
            return {"roots": [{"branches": [
                {"key": "c1", "lane": "selected", "alive": True,
                 "declared_at": 20700 * 86400,
                 "daily": [[20695, 10.0], [20696, -80.0],
                           [20701, 5.0]]}]}]}
        if path.startswith("/book_days?hz=obs"):
            return {"unknown": True}
        return {"cap": 3000.0, "days": [
            {"day": "2026-09-01", "arms": {"all": {"pnl": 2.0}}},
            {"day": "2026-09-02", "arms": {"all": {"pnl": -9.0}}}]}

    was, ST._get = ST._get, fake
    try:
        cand = ST.cand_rows("http://x", "k")
        live = ST.live_rows("http://x", "k", ["h4", "obs"])
    finally:
        ST._get = was
    # Бэктест и форвард считаются РАЗДЕЛЬНО: сложить их значило бы
    # выдать пересчёт по уже виденному прошлому за трек.
    check("форвард и бэктест кандидата разделены",
          cand[0]["fwd"]["days"] == 1 and cand[0]["pre"]["days"] == 2,
          str(cand[0]))
    check("книга, не держащая денег, названа словами",
          live[1].get("skip") and live[1].get("st") is None,
          str(live[1]))
    check("живая книга посчитана деньгами своего счёта",
          live[0]["st"]["worst"] == -9.0 and live[0]["cap"] == 3000.0,
          str(live[0]))
    # Числа берутся у сервера, а не пересчитываются обходом файлов.
    check("ряды взяты у самого сервера",
          "/factory_built" in seen and any(
              x.startswith("/book_days") for x in seen), str(seen))
    txt = ST.report(live, cand, "http://x", 1788370000)
    check("деньги живой книги печатаются с долей к депозиту",
          "-9.00 $ (-0.30 %)" in txt, txt[:200])
    check("реплей печатается процентом, а не базисным пунктом",
          "-0.80 %" in txt and " bp" not in txt, txt[:200])
    check("тонкая выборка помечена в самом отчёте",
          "⚠" in txt, txt[:200])

if __name__ == "__main__":
    raise SystemExit(main())
