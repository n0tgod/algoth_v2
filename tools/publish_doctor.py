#!/usr/bin/env python3
"""Доктор публикации: почему сервер молчит в git — и отчёт В ОБХОД канала.

Повод (17.10). С 09:45 UTC задания очереди исполнялись (перезапуски
проходили), а в git не доехал ни один их лог и ни один часовой свод:
`publish.sh` падал на каждом задании, и текст отказа ложился в локальный
лог задания — который публикуется тем же `publish.sh`. Отказ, неотличимый
от тишины, причём замкнутый сам на себя: единственный канал наружу и есть
то, что сломано. Очередь при этом работала: её проверка `merge --ff-only`
проходила, то есть непропушенных коммитов на сервере не было — публикация
ломалась ДО коммита.

Что делает. Собирает диагностику дерева (статус, замки, незавершённый
rebase, индекс, маркеры конфликта в индексе, хвосты последних локальных
логов заданий — там текст отказа публикации, хвост `jobs/poke.log` и
журнала сторожа) и отправляет её ОТДЕЛЬНЫМ коммитом в служебную ветку
`server-doctor` плумбингом git (`hash-object` → `mktree` → `commit-tree`):
без хуков, не касаясь индекса и рабочего дерева, всегда fast-forward.
Это и есть обходной канал. С `--repair` — консервативная починка ровно
тех состояний, что уже ломали публикацию: застрявший `index.lock` без
живого git, незавершённый rebase (карта кода сводится `resolve_maps.sh`),
разросшийся индекс (`git reset` — только индекс, рабочее дерево цело),
генерируемые карты кода (`git restore` ТОЛЬКО трёх файлов `docs/MAP*.md`
— их содержимое выводится из исходников, терять нечего). Артефакты,
журналы, код — не трогает. После починки запускает `publish.sh` и
дописывает его вывод в отчёт.

    run tools/publish_doctor.py            # только отчёт
    run tools/publish_doctor.py --repair   # отчёт → починка → публикация → отчёт
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRANCH = "server-doctor"
MAPS = ("docs/MAP.md", "docs/MAP-symbols.md", "docs/MAP-tests.md")
MARK = re.compile(r"^\+(<<<<<<<|=======$|>>>>>>>)")


def sh(cmd, timeout=120, check=False):
    """(код, вывод) команды в корне репозитория; таймаут — тоже ответ."""
    try:
        p = subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, (p.stdout or "").rstrip()
    except subprocess.TimeoutExpired as e:
        return 124, f"таймаут {timeout} с: {(e.stdout or b'')[-2000:]!r}"


def tail(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return [f"(не читается: {e})"]
    return lines[-n:]


def age_s(path):
    try:
        return round(time.time() - os.path.getmtime(path))
    except OSError:
        return None


def report(title):
    out = [f"# {title}", f"время {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC",
           f"узел {os.uname().nodename}", ""]

    def sec(name, body):
        out.append(f"## {name}")
        out.extend(body if isinstance(body, list) else [body])
        out.append("")

    sec("git log -3", sh("git log --oneline -3")[1])
    sec("ссылки", [f"HEAD {sh('git rev-parse HEAD')[1]}",
                   f"origin/main {sh('git rev-parse origin/main')[1]}",
                   f"впереди origin/main на {sh('git rev-list --count origin/main..HEAD')[1]}, "
                   f"позади на {sh('git rev-list --count HEAD..origin/main')[1]}"])
    locks = []
    for p in (".git/index.lock", ".git/rebase-merge", ".git/rebase-apply", ".git/MERGE_HEAD",
              ".git/CHERRY_PICK_HEAD"):
        full = os.path.join(ROOT, p)
        if os.path.exists(full):
            locks.append(f"{p}: есть, возраст {age_s(full)} с")
    sec("замки и незавершённые операции", locks or ["нет"])
    sec("процессы git", sh("pgrep -af '^git ' || echo нет")[1])
    st = sh("git status --porcelain --untracked-files=no")[1].splitlines()
    sec("git status (без неотслеживаемых)", [f"строк {len(st)}"] + st[:40])
    sec("индекс (diff --cached --stat, хвост)", sh("git diff --cached --stat | tail -20")[1] or "пусто")
    marks = sh("git diff --cached -U0 | grep -n '^+\\(<<<<<<<\\|=======$\\|>>>>>>>\\)' | head -20")[1]
    sec("маркеры конфликта в индексе", marks or "нет")
    files = sh("git diff --cached --name-only")[1].splitlines()
    bad = []
    for f in files:
        full = os.path.join(ROOT, f)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                for i, ln in enumerate(fh, 1):
                    if MARK.match("+" + ln.rstrip("\n")):
                        bad.append(f"{f}:{i}: {ln.rstrip()[:80]}")
                        if len(bad) > 20:
                            break
        except OSError:
            continue
        if len(bad) > 20:
            break
    sec("файлы индекса со строками-маркерами", bad or "нет")
    sec("CLAUDE.md, байт", sh("stat -c %s CLAUDE.md")[1])
    sec("хук", sh("git config core.hooksPath; ls -la tools/githooks 2>/dev/null | head -5")[1])
    sec("диск", sh("df -h . | tail -1")[1])
    # Хвосты последних локальных логов заданий: сюда publish.sh писал отказ
    logs = sorted(glob.glob(os.path.join(ROOT, "jobs", "done", "*.log")),
                  key=lambda p: os.path.getmtime(p), reverse=True)[:6]
    for p in logs:
        sec(f"хвост {os.path.relpath(p, ROOT)} (возраст {age_s(p)} с)", tail(p, 30))
    sec("хвост jobs/poke.log", tail(os.path.join(ROOT, "jobs", "poke.log"), 15))
    sec("хвост журнала сторожа", tail(os.path.join(ROOT, "research/b1_book/out/watchdog.log"), 25))
    return "\n".join(out) + "\n"


def push_report(text, branch=BRANCH, log=print):
    """Отчёт — коммитом в служебную ветку плумбингом: без хуков, без индекса."""
    fd, tmp = tempfile.mkstemp(prefix="doctor-", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        rc, blob = sh(["git", "hash-object", "-w", tmp])
        if rc:
            return log(f"отчёт не записан в объекты: {blob}")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        name = f"doctor-{stamp}.md"
        rc, tree = sh(f"printf '100644 blob {blob}\\t{name}\\n' | git mktree")
        if rc:
            return log(f"дерево отчёта не собрано: {tree}")
        parent = ""
        if sh(["git", "fetch", "-q", "origin", branch], timeout=60)[0] == 0:
            parent = sh("git rev-parse FETCH_HEAD")[1].strip()
        cmd = ["git", "commit-tree", tree.strip(), "-m", f"doctor: отчёт {stamp} UTC"]
        if parent:
            cmd += ["-p", parent]
        rc, commit = sh(cmd)
        if rc:
            return log(f"коммит отчёта не создан: {commit}")
        rc, out = sh(["git", "push", "-q", "origin", f"{commit.strip()}:refs/heads/{branch}"], timeout=120)
        log(f"отчёт {name} → origin/{branch}: " + ("ушёл" if rc == 0 else f"НЕ ушёл: {out}"))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def repair(log=print):
    """Консервативная починка — только состояния, уже ломавшие публикацию."""
    did = []
    lock = os.path.join(ROOT, ".git", "index.lock")
    if os.path.exists(lock):
        a = age_s(lock) or 0
        if a > 300 and sh("pgrep -x git || pgrep -f '^git '")[0] != 0:
            os.unlink(lock)
            did.append(f"снят застрявший .git/index.lock (возраст {a} с, живого git нет)")
        else:
            did.append(f"index.lock оставлен: возраст {a} с или git работает")
    if os.path.exists(os.path.join(ROOT, ".git", "rebase-merge")) or \
            os.path.exists(os.path.join(ROOT, ".git", "rebase-apply")):
        for _ in range(6):
            sh("tools/resolve_maps.sh", timeout=120)
            rc, out = sh("GIT_EDITOR=true git rebase --continue", timeout=120)
            if rc == 0:
                did.append("незавершённый rebase доведён (карты сведены пересборкой)")
                break
            if not os.path.exists(os.path.join(ROOT, ".git", "rebase-merge")):
                break
        else:
            sh("git rebase --abort")
            did.append("rebase не доведён — снят (коммит на месте)")
    # индекс — только индекс: рабочее дерево и артефакты не трогаются
    rc, out = sh("git reset -q")
    did.append("индекс расставлен (git reset)" if rc == 0 else f"git reset отказал: {out}")
    # генерируемые карты кода: содержимое выводится из исходников
    rc, out = sh(["git", "restore", "--", *MAPS])
    did.append("карты кода восстановлены из HEAD (docs/MAP*.md — генерируемые)"
               if rc == 0 else f"restore карт отказал: {out}")
    rc, out = sh("git fetch -q origin main && git merge -q --ff-only origin/main", timeout=180)
    did.append("origin/main подтянут (ff-only)" if rc == 0 else f"ff-only не прошёл: {out[-400:]}")
    for d in did:
        log("  " + d)
    rc, out = sh('tools/publish.sh "doctor: восстановление публикации"', timeout=600)
    log(f"publish.sh: код {rc}")
    return did, rc, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--no-push", action="store_true", help="только напечатать отчёт")
    ap.add_argument("--branch", default=BRANCH)
    a = ap.parse_args()
    before = report("доктор публикации — состояние ДО")
    if a.no_push:
        print(before)
        return 0
    print(before)
    push_report(before, a.branch)
    if not a.repair:
        return 0
    print("== починка ==")
    did, rc, out = repair()
    after = report("доктор публикации — состояние ПОСЛЕ починки")
    after += "## что сделано\n" + "\n".join("- " + d for d in did) + "\n\n"
    after += f"## publish.sh (код {rc}), хвост\n" + "\n".join(out.splitlines()[-60:]) + "\n"
    print(after)
    push_report(after, a.branch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
