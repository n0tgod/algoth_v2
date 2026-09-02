"""Реестр книг: ОДНО место, где записано, какие книги существуют.

До этого список жил восемью копиями и трижды расходился: страница
сделок молча отдавала главную книгу под именем выбранной, сводка
собирала каталог соглашением `model_<ключ>` вместо карты, лига
называла книги своими ярлыками. Каждый раз дефект выглядел исправной
страницей — тот самый отказ, неотличимый от тишины.

Модуль намеренно БЕЗ ИМПОРТОВ (как `families.py`): его читают и цикл
обучения, и веб-сервер, и будущая фабрика гипотез. Потянув сюда numpy
или математику признаков, мы привязали бы список книг к окружению,
которого у читателя может не быть.

Что реестр решает и чего НЕ решает. Он говорит, какие книги
существуют, где их каталоги, как они называются на странице, к какой
семье относятся и какие у них флаги (торгуемая, эхо, согласная,
удалённая). Он НЕ содержит правил книги — пороги, геометрия и размер
живут в манифесте самой книги, потому что запись обязана описывать тот
прогон, который её породил, а не текущие исходники.

Поля записи:
  key        — ключ в адресе страницы и в ответах сервера;
  dir        — каталог книги внутри `s8_loop/out`;
  label      — подпись на странице (порядок кнопок = порядок реестра);
  family     — чем книгу ведёт цикл: timer / sigma / basket / agree /
               situational;
  horizon_h  — срок закрытия; None у книг без таймера;
  traded     — держит ли книга деньги (наблюдательная запись — нет);
  echo       — ТЕ ЖЕ решения, что у книги-источника, под другим
               правилом — размера (`sit_r`, равный доллар риска) либо
               выхода (корзинные). Свои деньги у них настоящие, но в
               сводных суммах (лига, корень дерева, разбивка
               волатильности, дневной тормоз) они считали бы одни
               решения дважды — исключаются по этому флагу, а не по
               имени в каждом месте;
  agree      — руки тождественны по построению (пересечение выборов
               симметрично): на дереве такая книга живёт под третьим
               корнем, а показ сводится к канонической руке — иначе
               каждая её сделка стояла бы в таблице дважды. Членство
               объявлено здесь, а не выведено из манифеста: книга без
               манифеста иначе МОЛЧА вернулась бы под руки;
  in_menu    — есть ли кнопка на странице сделок;
  removed    — книга снята решением владельца: каталог на диске
               остаётся записью, но не пишется и не показывается.
"""

# Порядок записей = порядок кнопок на странице. Менять его — менять
# показ, поэтому он объявлен здесь, а не собирается сортировкой.
REGISTRY = (
    {"key": "h4", "dir": "model", "label": "4 h · per σ",
     "family": "timer", "horizon_h": 4, "traded": True,
     "echo": False, "agree": False, "in_menu": True},
    {"key": "h24", "dir": "model_h24", "label": "24 h",
     "family": "timer", "horizon_h": 24, "traded": True,
     "echo": False, "agree": False, "in_menu": True},
    {"key": "h24b", "dir": "model_h24b", "label": "24 h · basket",
     "family": "basket", "horizon_h": 24, "traded": True,
     "echo": True, "agree": False, "in_menu": True},
    {"key": "h24bf", "dir": "model_h24bf",
     "label": "24 h · basket ± floor",
     "family": "basket", "horizon_h": 24, "traded": True,
     "echo": True, "agree": False, "in_menu": True},
    {"key": "h24c", "dir": "model_h24c", "label": "24 h · basket only",
     "family": "basket", "horizon_h": 24, "traded": True,
     "echo": True, "agree": False, "in_menu": True},
    {"key": "sit", "dir": "model_sit", "label": "situational · per σ",
     "family": "situational", "horizon_h": None, "traded": True,
     "echo": False, "agree": False, "in_menu": True},
    # Книга низкого RR дизъюнктна с торгуемой по построению
    # (rr ≤ 1.5 против rr ≥ 2) — двойного счёта решений нет.
    {"key": "sit_lo", "dir": "model_sit_lo",
     "label": "situational · low RR",
     "family": "situational", "horizon_h": None, "traded": True,
     "echo": False, "agree": False, "in_menu": True},
    {"key": "sit_r", "dir": "model_sit_r",
     "label": "situational · fixed risk",
     "family": "situational", "horizon_h": None, "traded": True,
     "echo": True, "agree": False, "in_menu": True},
    # Пара «сырой порядок против порядка в σ» стоит на 24 ч. Прежде
    # она стояла на 4 ч, но решением владельца главная книга сама
    # перешла на порядок в σ — и пара стала бы её дубликатом. Каталог
    # `model_z` не удалён: его сделки остаются накопленной записью
    # торговли в σ на 4 ч, но живой книгой он больше не является.
    {"key": "z", "dir": "model_h24z", "label": "24 h · per σ",
     "family": "sigma", "horizon_h": 24, "traded": True,
     "echo": False, "agree": False, "in_menu": True},
    {"key": "h24a", "dir": "model_h24a", "label": "24 h · agreed",
     "family": "agree", "horizon_h": 24, "traded": True,
     "echo": True, "agree": True, "in_menu": True},
    {"key": "h24za", "dir": "model_h24za", "label": "24 h · σ · agreed",
     "family": "agree", "horizon_h": 24, "traded": True,
     "echo": True, "agree": True, "in_menu": True},
    # Наблюдательная запись: те же кандидаты, что у торгуемой, без
    # порога отношения. Денег не держит и кнопки не имеет, но
    # адресуема — на неё уводит фильтр владельца по RR.
    {"key": "sit_obs", "dir": "model_sit_obs",
     "label": "situational · any RR",
     "family": "situational", "horizon_h": None, "traded": False,
     "echo": False, "agree": False, "in_menu": False},
)

# Горизонты турнира темпов, снятые решением владельца. Держим ЧИСЛАМИ,
# а не ключами: цикл заводит книги обходом `FB.HORIZONS`, и снятый
# горизонт обязан отсекаться там же. Часовая книга удалена 2026-08-12
# по зонду крайности: фильтр не лечит её знаменатель — круг издержек
# 11 б.п. на час.
REMOVED_HORIZONS = (1,)

# Каноническая рука согласной книги. Её руки тождественны по
# построению, и показ сводится к одной; та же рука каноническая на
# дереве, чтобы страница и дерево не назвали разные счета.
CANON_ARM = "gbm"


def all_keys(books=None):
    return tuple(b["key"] for b in (books or REGISTRY))


def by_key(key, books=None):
    for b in (books or REGISTRY):
        if b["key"] == key:
            return b
    return None


def dirs(books=None):
    """Ключ → каталог. Карта существует затем, чтобы каталог НЕ
    выводился соглашением `model_<ключ>`: у четырёх книг из пяти
    соглашение совпадало, а пятая молча читала чужой каталог."""
    return {b["key"]: b["dir"] for b in (books or REGISTRY)}


def traded(books=None):
    """Книги, держащие деньги, в порядке реестра."""
    return tuple((b["key"], b["dir"]) for b in (books or REGISTRY)
                 if b["traded"])


def echo_keys(books=None):
    return frozenset(b["key"] for b in (books or REGISTRY) if b["echo"])


def agree_keys(books=None):
    return frozenset(b["key"] for b in (books or REGISTRY) if b["agree"])


def menu(books=None):
    """Кнопки страницы: ключ и подпись, в объявленном порядке."""
    return tuple((b["key"], b["label"]) for b in (books or REGISTRY)
                 if b["in_menu"])


def addressable(books=None):
    """Ключи, законные в адресе. Главная книга — умолчание и в адрес
    не пишется; наблюдательная запись адресуема, хотя кнопки не
    имеет."""
    return tuple(b["key"] for b in (books or REGISTRY)
                 if b["key"] != "h4")


# Каталог книги строится циклом как `MODEL_DIR + суффикс`, а не как
# «out/<каталог>»: в демо- и песочном прогоне MODEL_DIR подменяется
# целиком, и книги обязаны переехать вместе с ним. Отсюда правило —
# каталог ЛЮБОЙ книги начинается с каталога главной; у самой главной
# суффикс пуст. Оно проверяется и у ядра, и у кандидатов фабрики:
# книга вне этого правила не попала бы в подменённый каталог, а
# выглядела бы заведённой.
MAIN_DIR = "model"


def suffix(key, books=None):
    b = by_key(key, books)
    if not b:
        raise KeyError(f"книги {key!r} нет в реестре")
    d = b["dir"]
    if d != MAIN_DIR and not d.startswith(MAIN_DIR + "_"):
        raise ValueError(f"каталог {d!r} не начинается с {MAIN_DIR!r}")
    return d[len(MAIN_DIR):]


def family(name, books=None):
    return tuple(b for b in (books or REGISTRY) if b["family"] == name)


# --- Книги фабрики ---------------------------------------------------
#
# Реестр выше — ЯДРО: книги, заведённые решением владельца. Оно живёт
# кодом намеренно: питоновский литерал не может не разобраться, а рядом
# с ним стоят доводы, почему пара переехала на 24 ч и почему часовая
# удалена. Фабрика гипотез (спека 13) книг таких не заводит — её
# кандидаты приходят ФАЙЛОМ, и это единственный способ завести книгу
# без правки кода.
#
# Асимметрия защиты выведена из того, чем платит отказ, а не из вкуса.
# Страницы и запись стакана живут в ОДНОМ процессе, и негодный файл,
# роняющий чтение, остановил бы запись — единственное необратимое в
# проекте (архива книги не существует нигде). Поэтому: негодный файл
# гасит ТОЛЬКО кандидатов и поднимает флаг, который страница обязана
# напечатать; ядро от файла не зависит вовсе. Молчаливого отката к
# «списку по умолчанию» нет ни в одной ветке — он показал бы чужой
# состав книг под видом исправной страницы.
EXTRAS_FILE = "books_extra.json"

FAMILIES = ("timer", "sigma", "basket", "agree", "situational")

# Ключ уезжает в адрес страницы, каталог — в путь на диске. Файл пишет
# автомат, поэтому оба проверяются набором знаков: `..` или разделитель
# в каталоге увели бы чтение за пределы каталога модели.
_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def _safe_name(s):
    return bool(s) and set(str(s).lower()) <= _SAFE


def _extras_path(path=None):
    if path:
        return path
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        EXTRAS_FILE)


def extras(path=None):
    """Книги фабрики с диска: (список, причина отказа или None).

    Файла нет — это НОРМА (фабрика ещё не заводила книг), а не отказ:
    пустой список и None. Файл негоден — пустой список и причина
    словами; звать её обязана страница, потому что «кандидатов нет» и
    «кандидаты потеряны» снаружи неотличимы.
    """
    import json
    import os
    p = _extras_path(path)
    if not os.path.exists(p):
        return [], None
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return [], f"{EXTRAS_FILE} не читается: {e}"
    if not isinstance(raw, list):
        return [], f"{EXTRAS_FILE}: ожидался список книг"
    core = set(all_keys())
    dirs_ = {b["dir"] for b in REGISTRY}
    out, seen = [], set()
    for i, b in enumerate(raw):
        if not isinstance(b, dict):
            return [], f"{EXTRAS_FILE}: запись {i} не объект"
        key, d = b.get("key"), b.get("dir")
        for name, v in (("key", key), ("dir", d)):
            if not _safe_name(v):
                return [], (f"{EXTRAS_FILE}: запись {i}, "
                            f"негодный {name}: {v!r}")
        if d != MAIN_DIR and not str(d).startswith(MAIN_DIR + "_"):
            return [], (f"{EXTRAS_FILE}: запись {i}, каталог {d!r} не "
                        f"начинается с {MAIN_DIR!r}")
        if key in core or d in dirs_:
            return [], (f"{EXTRAS_FILE}: запись {i} занимает имя ядра: "
                        f"{key}/{d}")
        if key in seen:
            return [], f"{EXTRAS_FILE}: ключ {key} встречается дважды"
        fam = b.get("family")
        if fam not in FAMILIES:
            return [], (f"{EXTRAS_FILE}: запись {i}, "
                        f"неизвестная семья: {fam!r}")
        if not b.get("label"):
            return [], f"{EXTRAS_FILE}: запись {i} без подписи"
        seen.add(key)
        dirs_.add(d)
        out.append({"key": key, "dir": d, "label": str(b["label"]),
                    "family": fam, "horizon_h": b.get("horizon_h"),
                    "traded": bool(b.get("traded", True)),
                    "echo": bool(b.get("echo", False)),
                    "agree": bool(b.get("agree", False)),
                    # Кандидатов фабрики может быть до сотни — кнопкой
                    # на странице сделок они по умолчанию НЕ становятся
                    # (ряд из ста кнопок показом не является), но
                    # адресуемы, и своя страница у них будет.
                    "in_menu": bool(b.get("in_menu", False)),
                    "origin": "factory",
                    # ПРАВИЛО кандидата провозится насквозь, и это не
                    # нарушение «реестр не содержит правил». У книги
                    # ядра правило есть решение владельца в коде, и
                    # манифест только записывает применённое. У
                    # кандидата правило объявлено реестром испытаний и
                    # переписать его нечем: файл несёт ИНСТРУКЦИЮ,
                    # манифест книги — ЗАПИСЬ о том, чем она торговала.
                    # Расхождение между ними обязано быть видно, а для
                    # этого инструкция должна доехать до цикла.
                    "rule": b.get("rule") if isinstance(
                        b.get("rule"), dict) else None,
                    "gate": b.get("gate") if isinstance(
                        b.get("gate"), dict) else None,
                    "sizing": b.get("sizing"),
                    "lane": b.get("lane"),
                    "declared_at": b.get("declared_at"),
                    # Вылетевший кандидат книгу СОХРАНЯЕТ: его запись —
                    # накопленный форвард, и стереть её значило бы
                    # стереть наблюдение. Новых входов он не берёт.
                    "retired_at": b.get("retired_at")})
    return out, None


def load(path=None):
    """Все книги: ядро плюс кандидаты фабрики, и причина отказа.

    Возвращает (книги, причина). Читатель, которому кандидаты не
    нужны, зовёт аксессоры без аргумента и получает ядро — то есть
    сегодняшнее поведение бит в бит.
    """
    ex, why = extras(path)
    return list(REGISTRY) + ex, why
