#!/usr/bin/env python3
"""
Проверка генератора карты кода и хука, который её перестраивает.

Гоняется в НАСТОЯЩИХ временных репозиториях (урок test_safety.sh): тест,
который пишет в индекс рабочего дерева, однажды закоммитит это сам. На
живом репозитории — только чтение и сборка в память.

    python3 tools/test_project_map.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import project_map as PM                                    # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def git(root, *args, **kw):
    return subprocess.run(["git", "-C", root, *args], check=True,
                          capture_output=True, text=True, **kw).stdout


def temp_repo(files):
    root = tempfile.mkdtemp(prefix="map-")
    git(root, "init", "-q", ".")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        git(root, "add", "--", rel)
    git(root, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "начало")
    return root


def with_root(root, fn):
    old = PM.ROOT, PM.DOCS, PM.OUT_MAP, PM.OUT_SYM, PM.OUT_TST
    PM.ROOT = root
    PM.DOCS = os.path.join(root, "docs")
    PM.OUT_MAP = os.path.join(PM.DOCS, "MAP.md")
    PM.OUT_SYM = os.path.join(PM.DOCS, "MAP-symbols.md")
    PM.OUT_TST = os.path.join(PM.DOCS, "MAP-tests.md")
    try:
        return fn()
    finally:
        PM.ROOT, PM.DOCS, PM.OUT_MAP, PM.OUT_SYM, PM.OUT_TST = old


# ------------------------------------------------------------ живой репо
def test_real_repo():
    map_md, sym, tst = with_root(REAL_ROOT, PM.build)
    check("карта видит ядро денег", "## research/s8_loop — " in map_md)
    with open(os.path.join(REAL_ROOT, "research/s8_loop/trades.py"),
              encoding="utf-8") as f:
        real = [i + 1 for i, ln in enumerate(f) if ln.startswith("def account(")]
    check("у account один def в trades.py", len(real) == 1)
    check("строка account в индексе — настоящая",
          f"- L{real[0]} `account(" in sym, f"ждали L{real[0]}")
    check("тесты — в своём файле, не в символах",
          "## research/s8_loop/test_s8.py" in tst
          and "## research/s8_loop/test_s8.py" not in sym)
    check("карта не перечисляет саму себя",
          not any(ln.startswith("- `MAP") for ln in map_md.splitlines()))
    check("каталог без докстринга не остался",
          "(этап без названия и без докстринга)" not in map_md)
    check("очередь заданий — числом, а не перечнем",
          "заданий `.job`:" in map_md and map_md.count("`.job`") < 5)
    again = with_root(REAL_ROOT, PM.build)
    check("сборка детерминирована", again == (map_md, sym, tst))


# ---------------------------------------------------------- разборщики
PY_FIX = '''#!/usr/bin/env python3
"""
Первый абзац переносится
на вторую строку.

Второй абзац в карту не идёт.
"""

# Комментарий над константой.
LIMIT = 5
PAGE = """a
b
c"""


# Комментарий над функцией
# из двух строк.
def helper(x, y=1):
    return x


class Box:
    """Класс с докстрингом."""

    def put(self, item):
        """Положить."""
        return item
'''

RS_FIX = '''//! Модуль подставной площадки.
pub struct Venue;

/// Площадка умеет ставить заявки.
pub trait Exchange {
    fn place_limit(&self);
}

impl Exchange for crate::venue::Venue {
    /// Лимитная заявка.
    fn place_limit(&self) {}
}

/// Свободная функция.
pub fn floor_step(x: f64) -> f64 { x }
'''

RS_TEST_FIX = '''#[test]
fn тейк_внутри_такта_не_останавливает() {}
'''


def test_parsers():
    root = temp_repo({"research/x/a.py": PY_FIX, "bot/src/venue.rs": RS_FIX,
                      "bot/tests/t.rs": RS_TEST_FIX})
    map_md, sym, tst = with_root(root, PM.build)
    check("докстринг модуля — абзацем, не строкой",
          "Первый абзац переносится на вторую строку." in map_md)
    check("второй абзац не попал", "Второй абзац" not in map_md)
    fix = PY_FIX.splitlines()
    l_limit = fix.index("LIMIT = 5") + 1
    l_put = fix.index("    def put(self, item):") + 1
    check("константа со значением и комментарием",
          f"- L{l_limit} `LIMIT = 5` — Комментарий над константой." in sym)
    check("многострочный текст — числом строк", "`PAGE = <текст, 3 строк>`" in sym)
    check("комментарий над функцией — целиком",
          "`helper(x, y=1)` — Комментарий над функцией из двух строк." in sym)
    check("метод под классом",
          f"  - L{l_put} `Box.put(self, item)` — Положить." in sym)
    check("impl с путём — последний сегмент", "`impl Exchange for Venue`" in sym)
    check("метод impl — под типом", "`Venue::place_limit` — Лимитная заявка." in sym)
    check("///-документ у функции", "`floor_step` — Свободная функция." in sym)
    check("тест Rust — в файле проверок",
          "тейк_внутри_такта_не_останавливает" in tst
          and "тейк_внутри_такта_не_останавливает" not in sym)
    check("этап вне STAGES назван по докстрингу и помечен",
          "research/x — (по докстрингу) Первый абзац переносится" in map_md)
    shutil.rmtree(root)


# ------------------------------------------------------ --check и хук
def test_check_mode():
    root = temp_repo({"research/x/a.py": PY_FIX})

    def run():
        check("первая сборка пишет файлы", PM.main([]) == 0
              and os.path.exists(PM.OUT_MAP))
        check("свежая карта проходит --check", PM.main(["--check"]) == 0)
        with open(PM.OUT_MAP, "a", encoding="utf-8") as f:
            f.write("\nправка руками\n")
        check("правленная руками карта — устарела (контроль)",
              PM.main(["--check"]) == 1)
        check("перестройка возвращает свежесть",
              PM.main([]) == 0 and PM.main(["--check"]) == 0)
    with_root(root, run)
    shutil.rmtree(root)


def test_hook_end_to_end():
    """Дорога до вызова: не функция, а сам хук в настоящем коммите."""
    root = temp_repo({"research/x/a.py": PY_FIX})
    os.makedirs(os.path.join(root, "tools/githooks"))
    for rel in ("tools/project_map.py", "tools/safety_check.sh",
                "tools/githooks/pre-commit"):
        shutil.copy(os.path.join(REAL_ROOT, rel), os.path.join(root, rel))
    git(root, "config", "core.hooksPath", "tools/githooks")

    with open(os.path.join(root, "research/x/a.py"), "a", encoding="utf-8") as f:
        f.write("\n\ndef added_by_hook_test():\n    pass\n")
    git(root, "add", "--", "research/x/a.py")
    git(root, "commit", "-qm", "правка")
    names = git(root, "show", "--name-only", "--format=", "HEAD").split()
    check("хук положил карту в тот же коммит",
          {"docs/MAP.md", "docs/MAP-symbols.md", "docs/MAP-tests.md"} <= set(names),
          str(names))
    sym = git(root, "show", "HEAD:docs/MAP-symbols.md")
    check("карта в коммите видит новую функцию", "added_by_hook_test()" in sym)

    # Контроль: без хука карта не перестраивается — значит свежесть
    # держит именно хук, а не случайность.
    with open(os.path.join(root, "research/x/a.py"), "a", encoding="utf-8") as f:
        f.write("\n\ndef added_without_hook():\n    pass\n")
    git(root, "add", "--", "research/x/a.py")
    git(root, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "без хука")
    stale = with_root(root, lambda: PM.main(["--check"]))
    check("без хука карта устаревает (контроль)", stale == 1)

    # Сломанный генератор коммит не останавливает — карта класс C.
    # Отказ — ПЕРВОЙ строкой после шебанга: дописанный в конец файла он
    # не исполнился бы никогда (main() выходит через sys.exit раньше).
    gen = os.path.join(root, "tools/project_map.py")
    with open(gen, encoding="utf-8") as f:
        lines = f.read().splitlines(True)
    lines.insert(1, "raise SystemExit('подставной отказ')\n")
    with open(gen, "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(root, "research/x/a.py"), "a", encoding="utf-8") as f:
        f.write("\n\ndef third():\n    pass\n")
    git(root, "add", "--", "research/x/a.py")
    r = subprocess.run(["git", "-C", root, "commit", "-qm", "при отказе"],
                       capture_output=True, text=True)
    check("отказ генератора не блокирует коммит",
          r.returncode == 0 and "карта кода не перестроена" in r.stderr, r.stderr)
    shutil.rmtree(root)


def main():
    test_real_repo()
    test_parsers()
    test_check_mode()
    test_hook_end_to_end()
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
