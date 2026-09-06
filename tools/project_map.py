#!/usr/bin/env python3
"""
Карта кода проекта — из самих файлов, не руками.

Зачем
-----

Проект вырос: 85 тысяч строк кода в полусотне каталогов, и новая сессия
ассистента, чтобы найти нужное место, перечитывала файлы целиком —
`collect.py` на 5 300 строк ради одной функции. Это дорого в токенах и
медленно. Карта отвечает на «где что лежит и что делает» без чтения
исходников: сессия читает `docs/MAP.md` (короткий, по модулям), а
точное место ищет в `docs/MAP-symbols.md` грепом по имени.

Почему генерируется, а не пишется
---------------------------------

Рукописная карта устаревает в первый же день: новый модуль появляется,
строка в карте — нет, и карта начинает врать молча. Здесь карта —
функция от дерева репозитория; хук `tools/githooks/pre-commit` строит
её заново перед каждым коммитом и добавляет в него же. Значит карта
всегда описывает тот код, который лежит рядом с ней.

Три файла:

- `docs/MAP.md` — по каталогам: модуль · строк · назначение (первая
  строка докстринга), тесты, инструкции, отчёты в `out/`;
- `docs/MAP-symbols.md` — функции, классы, методы, константы каждого
  модуля со строкой и первой строкой докстринга — грепать по имени;
- `docs/MAP-tests.md` — проверки по файлам тестов: имена тестов в этом
  проекте описывают поведение словами и потому служат индексом того,
  что закреплено.

Только стандартная библиотека: зовётся хуком в любом клоне, включая
сервер, где numpy живёт в `.venv`.

    python3 tools/project_map.py           # переписать три файла
    python3 tools/project_map.py --check   # 0 — карта свежа, 1 — устарела
"""

import ast
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
OUT_MAP = os.path.join(DOCS, "MAP.md")
OUT_SYM = os.path.join(DOCS, "MAP-symbols.md")
OUT_TST = os.path.join(DOCS, "MAP-tests.md")

CODE_EXT = (".py", ".rs", ".sh", ".js")
DOC_LINE = 110          # предел первой строки докстринга в карте
SIG_LEN = 64            # предел сигнатуры в индексе символов
VAL_LEN = 40            # предел значения константы

# Заголовки этапов — единственное рукописное знание в генераторе.
# Этап без строки печатается без названия, и это видно.
STAGES = {
    "common": "общие модули (площадка, funding, комиссии, универсум)",
    "a0_venue_inventory": "A0 — инвентаризация площадок",
    "a1_universe": "A1 — универсум на момент времени, свечи, funding, комиссии",
    "a2_storage": "A2 — хранилище Parquet, гигиена рядов",
    "asset_groups": "A3 — группы активов, ликвидность, кандидаты пар",
    "a4_cointegration": "A4 — коинтеграция walk-forward (гипотеза 1, закрыта)",
    "r1_factor": "R1 — рыночная волна: посылка факторной гипотезы",
    "r2_residual": "R2/R3 — остаток и его нули (гипотеза 2, закрыта)",
    "r4_costs": "R4 — модель издержек книги",
    "r5_backtest": "R5 — бэктест, поправка на испытания, парный бутстрап",
    "f1_carry": "F1 — carry на funding: разложение брутто (гипотеза 3)",
    "f2_traps": "F2 — ловушки carry: бета, делистинг, концентрация",
    "f3_nulls": "F3 — нули carry, хвост (гипотеза 3 закрыта)",
    "s1_managed": "S1 — carry с управлением риском (гипотеза 4, закрыта)",
    "l0_liquidation_inventory": "L0 — какие данные о ликвидациях существуют",
    "l1_cascades": "L1 — зонд каскадов ликвидаций, задержка публикации",
    "l2_data": "L2 — сбор открытого интереса Binance/Bybit",
    "l3_events": "L3 — события каскадов и контроли (гипотеза 5, закрыта)",
    "probe_intraday": "зонд: возврат внутри дня, микроструктура",
    "probe_reversal": "зонд: краткосрочный возврат по всему универсуму",
    "probe_extreme": "зонд: крайность прогноза (RSI-порог)",
    "probe_regimes": "зонд: неоднороден ли навык модели по режимам",
    "probe_turn": "зонд: «все книги сначала растут, потом сливают»",
    "t0_orderflow_inventory": "T0 — какие данные потока заявок существуют",
    "t1_tape": "T1 — лента: поглощение по объёму",
    "t2_levels": "T2 — лента: набор на уровне, фон из хранилища",
    "t3_brackets": "T3 — бракет от ленты; страница кластеров и график",
    "t4_structure": "T4 — бракет от структурных уровней и его зеркало",
    "b1_book": "B1 — сбор стакана живьём, страницы наблюдения, веб-сервер",
    "m1_features": "M1 — матрица признаков актив-день (гипотеза 6)",
    "m2_walkforward": "M2 — walk-forward обучение, бустинг на numpy",
    "s8_loop": "S8 — часовой цикл обучения, книги, касса (ядро денег)",
    "s9_sweep": "S9 — перебор правил ситуационной книги по журналу листов",
    "s10_policy": "S10 — турнир политик исполнения, профиль по ширине",
    "s11_horizon": "S11 — зонд горизонта сигнала 4…24 ч",
    "d1_seconds": "D1 — первые секунды после падения (гипотеза 7)",
    "probe_setups": "зонд: есть ли устойчивый сетап среди семейств признаков",
    "z1_screen": "Z1 — скрин закономерностей по хранилищу A2 (цена × интерес)",
    "z2_book": "Z2 — скрин по собственной записи стакана; минутный склад",
    "z3_ladder": "Z3 — лесенка ценовых уровней: снятие, восполнение, склад",
    "w1_waves": "W1–W3 — волновой анализ: форма, грамматика, фильтр",
    "probe_calm_exec": "зонд: пассивный вход в спокойном рынке",
    "probe_monthly": "зонд: месячный горизонт кросс-секции, funding, поправки",
    "probe_listings": "зонд: отставание новых листингов",
    "probe_spike": "зонд: минутный всплеск на записи и на годах A2",
    "probe_drain": "зонд: разбор слива 08-24…27, дневной тормоз",
    "probe_dow": "зонд: дни недели",
    "probe_basket": "зонд: корзина без отдельных выходов",
    "probe_corr": "зонд: фильтр по корреляции с рынком",
    "probe_stables": "зонд: порог плоского инструмента",
    "probe_fshift": "механика фабрики: смена интервала funding как событие (закрыта)",
    "probe_agree": "зонд: согласие рук",
    "probe_liqsplit": "зонд: разделение ликвидаций",
    "probe_tailveto": "зонд: вето по хвосту",
    "probe_upcascade": "зонд: каскад вверх",
    "paper_monthly": "бумажная месячная книга (k14/h30/дециль), календарь",
    "factory": "фабрика гипотез и автономная система: агенты, потолок, судья, вылет",
    "dca_ladder": "DCA D0–D9 — лестница с забором по марже: реплеи, хеджи, тейк, выходы",
    "dca_paper": "бумажные DCA-книги: правила, журнал, хвост ленты, короткие книги",
    "dca_live": "DCA: пробы живых уровней",
    "ops": "диагностика сервера: книги по дням, живой отчёт",
}


def git_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if p]


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
        return f.read()


def one_line(text, limit=DOC_LINE):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def first_doc_line(doc):
    """Первый абзац докстринга одной строкой (обрезанной до DOC_LINE).

    Абзац, а не строка: докстринги в проекте переносятся по 72 знака, и
    первая строка обрывается на полуслове («…словами трейдера, и
    объяснение»)."""
    if not doc:
        return ""
    para = []
    for ln in doc.splitlines():
        ln = ln.strip()
        if not ln or set(ln) <= set("-=~"):
            if para:
                break
            continue
        para.append(ln)
    return one_line(" ".join(para)) if para else ""


def comment_block_above(lines, idx, marks=("#",)):
    """Блок комментариев, стоящий прямо над строкой idx (0-based), одной
    строкой. Шебанг и пустой блок не считаются."""
    j = idx - 1
    block = []
    while j >= 0:
        s = lines[j].strip()
        if not s or not any(s.startswith(m) for m in marks) or s.startswith("#!"):
            break
        block.append(s)
        j -= 1
    if not block:
        return ""
    out = []
    for s in reversed(block):
        for m in marks:
            if s.startswith(m):
                s = s[len(m):]
                break
        out.append(s.strip())
    return one_line(" ".join(out))


# ---------------------------------------------------------------- Python
def py_sig(node):
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "…"
    sig = f"{node.name}({args})"
    return sig if len(sig) <= SIG_LEN else sig[:SIG_LEN - 1] + "…"


def py_module(path):
    src = read(path)
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {"doc": f"(не разбирается: {e.msg}, строка {e.lineno})",
                "symbols": [], "lines": len(lines)}
    doc = first_doc_line(ast.get_docstring(tree))
    syms = []

    def doc_of(node):
        d = first_doc_line(ast.get_docstring(node))
        if d:
            return d
        top = min([node.lineno] + [d.lineno for d in node.decorator_list])
        return comment_block_above(lines, top - 1)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append((node.lineno, py_sig(node), doc_of(node), 0))
        elif isinstance(node, ast.ClassDef):
            syms.append((node.lineno, f"class {node.name}", doc_of(node), 0))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    syms.append((sub.lineno, f"{node.name}.{py_sig(sub)}",
                                 doc_of(sub), 1))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id.isupper():
            name = node.targets[0].id
            val = node.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str) \
                    and "\n" in val.value:
                shown = f"{name} = <текст, {val.value.count(chr(10)) + 1} строк>"
            else:
                try:
                    v = ast.unparse(val)
                except Exception:
                    v = "…"
                v = " ".join(v.split())
                if len(v) > VAL_LEN:
                    v = v[:VAL_LEN - 1] + "…"
                shown = f"{name} = {v}"
            syms.append((node.lineno, shown,
                         comment_block_above(lines, node.lineno - 1), 0))
    return {"doc": doc, "symbols": syms, "lines": len(lines)}


# ------------------------------------------------------------------ Rust
RS_FN = re.compile(r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)")
RS_TYPE = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(struct|enum|trait|type)\s+(\w+)")
# Пути вида `crate::venue::Venue` допустимы: в карте остаётся последний
# сегмент — `impl Exchange for Venue`, методы под `Venue::…`.
RS_IMPL = re.compile(r"^impl(?:<[^>]*>)?\s+(?:([\w:]+)\s+for\s+)?([\w:]+)")
RS_MOD = re.compile(r"^(?:pub\s+)?mod\s+(\w+)\s*\{")


def rs_module(path):
    lines = read(path).splitlines()
    doc = ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("//!"):
            doc = one_line(s[3:].strip())
            break
        if s and not s.startswith("//"):
            break
    syms = []
    scope = None            # имя impl-блока, внутри которого стоим
    for i, ln in enumerate(lines):
        if ln.startswith("}"):
            scope = None
        m = RS_IMPL.match(ln)
        if m:
            scope = m.group(2).rsplit("::", 1)[-1]
            trait = m.group(1).rsplit("::", 1)[-1] if m.group(1) else None
            what = f"impl {trait} for {scope}" if trait else f"impl {scope}"
            syms.append((i + 1, what, comment_block_above(lines, i, ("///",)), 0))
            continue
        m = RS_TYPE.match(ln)
        if m:
            syms.append((i + 1, f"{m.group(1)} {m.group(2)}",
                         comment_block_above(lines, i, ("///",)), 0))
            continue
        m = RS_MOD.match(ln)
        if m:
            syms.append((i + 1, f"mod {m.group(1)}",
                         comment_block_above(lines, i, ("///",)), 0))
            continue
        m = RS_FN.match(ln)
        if m:
            indent, name = m.group(1), m.group(2)
            d = comment_block_above(lines, i, ("///",))
            if not d:
                d = comment_block_above(lines, i, ("//",))
            if scope and indent:
                syms.append((i + 1, f"{scope}::{name}", d, 1))
            else:
                syms.append((i + 1, name, d, 1 if indent else 0))
    return {"doc": doc, "symbols": syms, "lines": len(lines)}


# ------------------------------------------------------------------ shell
SH_FN = re.compile(r"^(\w+)\s*\(\)\s*\{")


def sh_module(path):
    lines = read(path).splitlines()
    doc = ""
    for ln in lines[1:] if lines and lines[0].startswith("#!") else lines:
        s = ln.strip()
        if s.startswith("#") and s.strip("# ").strip():
            doc = one_line(s.lstrip("#").strip())
            break
        if s and not s.startswith("#"):
            break
    syms = []
    for i, ln in enumerate(lines):
        m = SH_FN.match(ln)
        if m:
            syms.append((i + 1, m.group(1) + "()",
                         comment_block_above(lines, i), 0))
    return {"doc": doc, "symbols": syms, "lines": len(lines)}


# --------------------------------------------------------------------- JS
JS_FN = re.compile(r"^(?:async\s+)?function\s+(\w+)\s*\(")
JS_CONST = re.compile(r"^const\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>")


def js_module(path):
    lines = read(path).splitlines()
    doc = ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("//"):
            doc = one_line(s.lstrip("/").strip())
            break
        if s and not s.startswith("/*") and not s.startswith("*"):
            break
    syms = []
    for i, ln in enumerate(lines):
        m = JS_FN.match(ln) or JS_CONST.match(ln)
        if m:
            syms.append((i + 1, m.group(1) + "()",
                         comment_block_above(lines, i, ("//",)), 0))
    return {"doc": doc, "symbols": syms, "lines": len(lines)}


def md_title(path):
    for ln in read(path).splitlines():
        if ln.startswith("# "):
            return one_line(ln[2:])
    return ""


PARSERS = {".py": py_module, ".rs": rs_module, ".sh": sh_module,
           ".js": js_module}


def is_test(path):
    base = os.path.basename(path)
    return base.startswith("test_") or "/tests/" in path or \
        base in ("headless_check.js", "test_safety.sh")


# ------------------------------------------------------------- сборка
ROOT_GROUP = "корень"
# Сами файлы карты в карту не входят: иначе первый коммит с ними менял
# бы карту на втором, и она никогда не была бы свежей.
SELF = ("docs/MAP.md", "docs/MAP-symbols.md", "docs/MAP-tests.md")


def group_of(path):
    parts = path.split("/")
    if len(parts) == 1:
        return ROOT_GROUP
    if parts[0] == "research" and len(parts) > 2:
        return "research/" + parts[1]
    if parts[0] == "bot":
        return "bot/" + parts[1] if len(parts) > 2 else "bot"
    return parts[0]


def shown_name(group, path):
    """Имя файла в карте: относительно каталога группы, чтобы
    `docs/journal/2026-08.md` не выглядел как файл в корне docs."""
    if group == ROOT_GROUP:
        return path
    prefix = group + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def build():
    files = git_files()
    groups = {}
    for p in files:
        if "/out/" in p or "__pycache__" in p or "/fixtures/" in p or p in SELF:
            continue
        if p.endswith(CODE_EXT) or p.endswith(".md") or p.endswith(".yaml") \
                or p.endswith(".toml") or p.endswith(".json"):
            groups.setdefault(group_of(p), []).append(p)
    reports = {}
    for p in files:
        if "/out/" in p and p.endswith(".md"):
            reports.setdefault(group_of(p), []).append(p)
    jobs_n = sum(1 for p in files if p.startswith("jobs/") and p.endswith(".job"))
    jobs_done = sum(1 for p in files if p.startswith("jobs/done/") and p.endswith(".log"))

    modules = {}
    for g, paths in groups.items():
        for p in paths:
            ext = os.path.splitext(p)[1]
            if ext in PARSERS and os.path.getsize(os.path.join(ROOT, p)) > 0:
                modules[p] = PARSERS[ext](p)

    def derived_title(paths):
        """Каталог вне STAGES (фабрика плодит `mech_<ключ>` сама):
        название — первая строка докстринга главного модуля, с пометкой,
        что оно выведено, а не назначено."""
        order_ = sorted(paths, key=lambda p: (
            0 if os.path.basename(p).startswith("run") else
            1 if os.path.basename(p) == "probe.py" else 2, p))
        for p in order_:
            v = modules.get(p)
            if v and v["doc"] and not is_test(p):
                return f"(по докстрингу) {v['doc']}"
        return "(этап без названия и без докстринга)"

    def title(g):
        if g.startswith("research/"):
            stage = g.split("/", 1)[1]
            t = STAGES.get(stage) or derived_title(groups[g])
            return f"{g} — {t}"
        return {ROOT_GROUP: "корень — память проекта, идеи, README",
                "bot/src": "bot/src — исполнительное ядро и живой исполнитель (Rust)",
                "bot/tests": "bot/tests — интеграционные тесты ядра",
                "bot": "bot — счетовод-тень, сверка, сборка",
                "tools": "tools — команды сервера, защита коммитов, хуки",
                "jobs": "jobs — очередь заданий серверу (файл = задание, done/ = лог)",
                "docs": "docs — спеки, роли, память, журнал"}.get(g, g)

    order = sorted(groups, key=lambda g: (
        0 if g == ROOT_GROUP else 1 if g == "docs" else
        2 if g.startswith("research/common") else
        3 if g.startswith("research/") else 4 if g.startswith("bot") else 5, g))

    # --- MAP.md ---------------------------------------------------------
    m = []
    m.append("# Карта кода\n")
    m.append("Генерируется `tools/project_map.py` из дерева репозитория; хук "
             "`tools/githooks/pre-commit` перестраивает её при каждом коммите. "
             "**Руками не править** — правка уедет при следующем коммите.\n")
    m.append("Как пользоваться: этот файл отвечает «где что лежит и что делает». "
             "Точное место — `docs/MAP-symbols.md` (функции, классы, константы "
             "со строками; искать грепом по имени), что закреплено тестами — "
             "`docs/MAP-tests.md`. История решений и уроки — `docs/memory/README.md`.\n")
    total_lines = sum(v["lines"] for v in modules.values())
    m.append(f"Модулей кода: {len(modules)}, строк: {total_lines}, "
             f"каталогов: {len(groups)}.\n")
    for g in order:
        m.append(f"\n## {title(g)}\n")
        paths = sorted(groups[g])
        code = [p for p in paths if p in modules and not is_test(p)]
        tests = [p for p in paths if p in modules and is_test(p)]
        other = [p for p in paths if p not in modules]
        for p in code:
            v = modules[p]
            m.append(f"- `{shown_name(g, p)}` · {v['lines']} строк — {v['doc'] or '—'}")
        if tests:
            m.append("- тесты: " + ", ".join(
                f"`{shown_name(g, p)}` ({modules[p]['lines']})" for p in tests))
        docs_here = [p for p in other if p.endswith(".md")]
        if g in ("docs", ROOT_GROUP):
            for p in sorted(docs_here):
                m.append(f"- `{shown_name(g, p)}` — {md_title(p) or '—'}")
        elif docs_here:
            m.append("- документы: " + ", ".join(
                f"`{shown_name(g, p)}` — {md_title(p)}" for p in docs_here))
        rest = [p for p in other if not p.endswith(".md")]
        if rest:
            m.append("- прочее: " + ", ".join(f"`{shown_name(g, p)}`" for p in rest))
        if g == "jobs":
            m.append(f"- заданий `.job`: {jobs_n}, логов `done/*.log`: {jobs_done} "
                     "(в карту не перечисляются — их читают по имени)")
        if g in reports:
            names = sorted(os.path.basename(p) for p in reports[g])
            m.append(f"- отчёты в `out/` ({len(names)}): " + ", ".join(names))
    map_md = "\n".join(m) + "\n"

    # --- MAP-symbols.md / MAP-tests.md -----------------------------------
    def sym_section(p, v):
        s = [f"\n## {p} · {v['lines']} строк\n"]
        if v["doc"]:
            s.append(v["doc"] + "\n")
        for ln, name, doc, depth in v["symbols"]:
            pad = "  " if depth else ""
            s.append(f"{pad}- L{ln} `{name}`" + (f" — {doc}" if doc else ""))
        return s

    sy = ["# Символы кода\n",
          "Генерируется `tools/project_map.py`; руками не править. Строка — "
          "`L<номер>`; ищите грепом: `grep -n 'account(' docs/MAP-symbols.md`. "
          "Методы стоят под своим классом (`Класс.метод`), у Rust — под "
          "`impl` (`Тип::метод`). Тесты — в `docs/MAP-tests.md`.\n"]
    ts = ["# Проверки\n",
          "Генерируется `tools/project_map.py`; руками не править. Имена "
          "проверок в проекте описывают поведение словами — это индекс того, "
          "что закреплено тестом. Строка — `L<номер>` в файле теста.\n"]
    for g in order:
        for p in sorted(groups[g]):
            if p not in modules:
                continue
            (ts if is_test(p) else sy).extend(sym_section(p, modules[p]))
    return map_md, "\n".join(sy) + "\n", "\n".join(ts) + "\n"


def main(argv):
    check = "--check" in argv
    map_md, sym_md, tst_md = build()
    targets = [(OUT_MAP, map_md), (OUT_SYM, sym_md), (OUT_TST, tst_md)]
    if check:
        stale = []
        for path, text in targets:
            try:
                cur = open(path, encoding="utf-8").read()
            except FileNotFoundError:
                cur = None
            if cur != text:
                stale.append(os.path.relpath(path, ROOT))
        if stale:
            print("карта устарела: " + ", ".join(stale) +
                  " — перестроить: python3 tools/project_map.py")
            return 1
        print("карта свежа")
        return 0
    os.makedirs(DOCS, exist_ok=True)
    changed = []
    for path, text in targets:
        try:
            cur = open(path, encoding="utf-8").read()
        except FileNotFoundError:
            cur = None
        if cur != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            changed.append(os.path.relpath(path, ROOT))
    print("карта: " + (", ".join(changed) if changed else "без изменений"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
