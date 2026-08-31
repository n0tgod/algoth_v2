"""Проверки реестра книг.

Две разные вещи, и путать их нельзя.

СНИМОК (`test_registry_matches_the_snapshot`) — это запись того, каким
состав книг был в день, когда реестр заводили. Он остаётся годной
проверкой и ПОСЛЕ того, как читатели переведены на реестр: там сравнение
«выведенное из реестра против реестра» станет тавтологией, а снимок
ловит опечатку в каталоге и потерянную книгу.

ЧИТАТЕЛИ (`test_readers_agree_with_the_registry`) — проверка ДОРОГИ до
показа: сегодня она доказывает, что реестр списан с живых литералов, а
после перевода — что каждый читатель действительно берёт список оттуда,
а не держит свою копию. Проверять надо каждую дорогу: список книг уже
жил восемью копиями, и трижды расходился.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))

import books as BK  # noqa: E402

FAILED = []


def check(name, ok, got=""):
    print(("  ok   " if ok else "  ПРОВАЛ ") + name + ("" if ok else f" — {got}"))
    if not ok:
        FAILED.append(name)


# Снимок на день заведения реестра: ключ, каталог, подпись, семья,
# горизонт, торгуемая, эхо, согласная, кнопка.
SNAPSHOT = (
    ("h4", "model", "4 h · per σ", "timer", 4, True, False, False, True),
    ("h24", "model_h24", "24 h", "timer", 24, True, False, False, True),
    ("h24b", "model_h24b", "24 h · basket", "basket", 24,
     True, True, False, True),
    ("h24bf", "model_h24bf", "24 h · basket ± floor", "basket", 24,
     True, True, False, True),
    ("h24c", "model_h24c", "24 h · basket only", "basket", 24,
     True, True, False, True),
    ("sit", "model_sit", "situational · per σ", "situational", None,
     True, False, False, True),
    ("sit_lo", "model_sit_lo", "situational · low RR", "situational", None,
     True, False, False, True),
    ("sit_r", "model_sit_r", "situational · fixed risk", "situational", None,
     True, True, False, True),
    ("z", "model_h24z", "24 h · per σ", "sigma", 24,
     True, False, False, True),
    ("h24a", "model_h24a", "24 h · agreed", "agree", 24,
     True, True, True, True),
    ("h24za", "model_h24za", "24 h · σ · agreed", "agree", 24,
     True, True, True, True),
    ("sit_obs", "model_sit_obs", "situational · any RR", "situational", None,
     False, False, False, False),
)
FIELDS = ("key", "dir", "label", "family", "horizon_h",
          "traded", "echo", "agree", "in_menu")


def test_registry_matches_the_snapshot():
    check("книг столько же", len(BK.REGISTRY) == len(SNAPSHOT),
          f"{len(BK.REGISTRY)} против {len(SNAPSHOT)}")
    bad = []
    for want, got in zip(SNAPSHOT, BK.REGISTRY):
        row = tuple(got.get(f) for f in FIELDS)
        if row != want:
            bad.append(f"{want[0]}: {row} против {want}")
    check("каждая книга дословно как в снимке", not bad, "; ".join(bad))
    # Порядок реестра ЕСТЬ порядок кнопок — сортировкой он не
    # собирается, поэтому проверяется как порядок, а не как множество.
    check("порядок совпал со снимком",
          BK.all_keys() == tuple(s[0] for s in SNAPSHOT),
          str(BK.all_keys()))


def test_registry_is_self_consistent():
    keys = [b["key"] for b in BK.REGISTRY]
    ds = [b["dir"] for b in BK.REGISTRY]
    check("ключи уникальны", len(set(keys)) == len(keys), str(keys))
    check("каталоги уникальны", len(set(ds)) == len(ds), str(ds))
    unknown = [b["key"] for b in BK.REGISTRY
               if b["family"] not in BK.FAMILIES]
    check("семья каждой книги известна", not unknown, str(unknown))
    # Эхо повторяет решения источника — не держащая денег книга эхом
    # быть не может: в лиге её и так нет, а исключать её было бы не от
    # чего.
    check("эхо держит деньги",
          BK.echo_keys() <= {k for k, _ in BK.traded()},
          str(BK.echo_keys()))
    check("главная книга не адресуема", "h4" not in BK.addressable(), "")
    check("наблюдательная запись адресуема без кнопки",
          "sit_obs" in BK.addressable()
          and "sit_obs" not in dict(BK.menu()), "")


def _web_book_list():
    """BOOK_LIST со страницы — разбором ТОГО ЖЕ куска JS, что уезжает
    в браузер. Копию списка на стороне питона здесь заводить нельзя:
    она сошлась бы с реестром, а страница жила бы своей."""
    import re
    import web as W
    src = W.BOOKJS if hasattr(W, "BOOKJS") else W.HEADJS
    m = re.search(r"const BOOK_LIST = (\[.*?\]\];)", src, re.S)
    if not m:
        return None
    # Разбирает JSON, а не «unicode_escape»: список уже валидный
    # JSON, и `\uXXXX` он раскрывает сам, а вот живой «·», стоящий в
    # источнике буквой, повторное декодирование ПОРТИТ — первый прогон
    # этой проверки на том и упал.
    return [tuple(x) for x in json.loads(m.group(1)[:-1])]


def _web_hz_keys():
    import re
    import web as W
    m = re.search(r"const HZ_KEYS = (\[.*?\]);", W.BOOKJS, re.S)
    return json.loads(m.group(1)) if m else None


def test_readers_agree_with_the_registry():
    import collect as C
    co = C.Collector
    check("каталоги книг: сборщик", co.BOOK_DIRS == BK.dirs(),
          str(sorted(set(co.BOOK_DIRS.items()) ^ set(BK.dirs().items()))))
    check("торгуемые книги: сборщик", tuple(co.BOOKS) == BK.traded(),
          str(co.BOOKS))
    check("эхо: сборщик", set(co.ECHO_BOOKS) == set(BK.echo_keys()),
          str(co.ECHO_BOOKS))
    check("согласные: сборщик", set(co.AGREE_BOOKS) == set(BK.agree_keys()),
          str(co.AGREE_BOOKS))
    check("каноническая рука: сборщик", co.CANON_ARM == BK.CANON_ARM,
          co.CANON_ARM)
    got = _web_book_list()
    check("кнопки страницы: web", got is not None and got == list(BK.menu()),
          str(got))
    hz = _web_hz_keys()
    check("законные ключи адреса: web", hz == list(BK.addressable()),
          str(hz))
    import train as T
    check("снятые горизонты: цикл",
          set(T.REMOVED_BOOKS) == set(BK.REMOVED_HORIZONS),
          str(T.REMOVED_BOOKS))


def _extras(rows):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "books_extra.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    return p


def test_factory_books_come_from_a_file():
    # Файла нет — это норма, а не отказ.
    miss = os.path.join(tempfile.mkdtemp(), "nope.json")
    check("файла нет — пусто и без причины", BK.extras(miss) == ([], None),
          str(BK.extras(miss)))
    good = _extras([{"key": "f1", "dir": "model_f1", "label": "cand 1",
                     "family": "situational", "horizon_h": None}])
    ex, why = BK.extras(good)
    check("кандидат прочитан", why is None and len(ex) == 1, f"{why} {ex}")
    check("умолчания кандидата: торгуется, не эхо, без кнопки",
          ex and ex[0]["traded"] and not ex[0]["echo"]
          and not ex[0]["in_menu"] and ex[0]["origin"] == "factory",
          str(ex))
    books, why = BK.load(good)
    check("слияние ставит кандидата ПОСЛЕ ядра",
          why is None and BK.all_keys(books)
          == BK.all_keys() + ("f1",), str(BK.all_keys(books)))
    check("аксессор по слитому списку видит кандидата",
          BK.dirs(books).get("f1") == "model_f1"
          and ("f1", "model_f1") in BK.traded(books), "")
    check("без списка аксессор отдаёт ядро бит в бит",
          BK.dirs() == dict(zip((s[0] for s in SNAPSHOT),
                                (s[1] for s in SNAPSHOT))), "")


def test_a_bad_file_drops_candidates_and_names_the_reason():
    cases = (
        ("мусор вместо json", "{{{"),
        ("не список", json.dumps({"key": "f1"})),
    )
    for name, body in cases:
        d = tempfile.mkdtemp()
        p = os.path.join(d, "books_extra.json")
        open(p, "w", encoding="utf-8").write(body)
        ex, why = BK.extras(p)
        check(f"{name}: пусто и причина словами", ex == [] and bool(why),
              f"{ex} {why}")
    bad = (
        ("каталог с переходом наверх",
         {"key": "f1", "dir": "../model", "label": "x",
          "family": "timer", "horizon_h": 4}),
        ("ключ с разделителем",
         {"key": "a/b", "dir": "model_f1", "label": "x",
          "family": "timer", "horizon_h": 4}),
        ("занят ключ ядра",
         {"key": "sit", "dir": "model_f1", "label": "x",
          "family": "situational", "horizon_h": None}),
        ("занят каталог ядра",
         {"key": "f1", "dir": "model_sit", "label": "x",
          "family": "situational", "horizon_h": None}),
        ("неизвестная семья",
         {"key": "f1", "dir": "model_f1", "label": "x",
          "family": "quantum", "horizon_h": 4}),
        ("без подписи",
         {"key": "f1", "dir": "model_f1", "label": "",
          "family": "timer", "horizon_h": 4}),
    )
    for name, row in bad:
        ex, why = BK.extras(_extras([row]))
        check(f"{name}: отвергнут", ex == [] and bool(why), f"{ex} {why}")
    ex, why = BK.extras(_extras([
        {"key": "f1", "dir": "model_f1", "label": "a",
         "family": "timer", "horizon_h": 4},
        {"key": "f1", "dir": "model_f2", "label": "b",
         "family": "timer", "horizon_h": 4}]))
    check("дубль ключа кандидатов отвергнут", ex == [] and bool(why),
          f"{ex} {why}")
    # Ядро от негодного файла не зависит вовсе — иначе сломанный
    # кандидат уносил бы торгуемые книги.
    check("ядро цело при негодном файле", len(BK.REGISTRY) == len(SNAPSHOT))


def main():
    tests = (test_registry_matches_the_snapshot,
             test_registry_is_self_consistent,
             test_readers_agree_with_the_registry,
             test_factory_books_come_from_a_file,
             test_a_bad_file_drops_candidates_and_names_the_reason)
    for t in tests:
        print(t.__name__)
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
