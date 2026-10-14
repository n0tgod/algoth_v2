"""Документы для пользователей и их версия (спека 16 §8b, L3/L6).

Три текста — `docs/legal/{terms,risk,privacy}.md`; версия набора — файл
`docs/legal/VERSION`: «дата отпечаток», где отпечаток — sha256 трёх
текстов. Согласие пользователя записывается С ОТПЕЧАТКОМ: правка текста
без смены версии — отказ, неотличимый от исправности (человек согласился
не с тем, что ему показали), поэтому `check()` сверяет отпечаток с
текстами и проверка падает, если их разошли.
"""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "docs", "legal")
DOCS = (("terms", "Terms of Use"), ("risk", "Risk Disclosure"), ("privacy", "Privacy Policy"))


def digest(d=DIR):
    h = hashlib.sha256()
    for name, _t in DOCS:
        fn = name + ".md"
        with open(os.path.join(d, fn), "rb") as f:
            h.update(fn.encode() + b"\0" + f.read() + b"\0")
    return h.hexdigest()[:16]


def version(d=DIR):
    """(дата версии, отпечаток из файла VERSION)."""
    with open(os.path.join(d, "VERSION"), encoding="utf-8") as f:
        date, dg = f.read().split()
    return date, dg


def check(d=DIR):
    """None — тексты и VERSION сходятся; иначе слова расхождения."""
    date, dg = version(d)
    real = digest(d)
    return None if real == dg else (f"тексты docs/legal изменены без смены версии: VERSION {date} {dg}, "
                                    f"тексты {real} — поднять дату и отпечаток")


def current(d=DIR):
    """Версия, на которую берётся согласие: «дата:отпечаток»."""
    date, dg = version(d)
    return f"{date}:{dg}"


def bundle(d=DIR):
    out = []
    for name, title in DOCS:
        with open(os.path.join(d, name + ".md"), encoding="utf-8") as f:
            out.append({"id": name, "title": title, "text": f.read()})
    return {"version": current(d), "docs": out}
