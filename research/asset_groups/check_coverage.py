#!/usr/bin/env python3
"""
Проверка группировки активов: покрытие, дубликаты, опечатки, размер групп.

Сверяет groups.yaml с универсумом на момент времени (этап A1).
Запускается после каждой правки groups.yaml.

Знаменатель — не «активы, торгуемые сегодня» и не когорты с длинной
историей, а всё, что может попасть хотя бы в одно окно walk-forward:
криптоактив с историей Binance, листингованный не позже чем за
MIN_HISTORY дней до конца данных. Отбор по сегодняшнему списку был бы
отбором выживших, а отбор по когорте «3+ года» описывал бы только
ранние окна.

Парсер YAML написан вручную под конкретный плоский формат файла —
внешних зависимостей нет.
"""

import json
import os
import re
from collections import Counter
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
GROUPS = os.path.join(HERE, "groups.yaml")
UNIVERSE = os.path.join(HERE, "..", "a1_universe", "out", "universe.json")

MIN_HISTORY = 365          # требование к истории, раздел 6 спеки 02
BIG_GROUP_PAIRS = 200      # выше этого группу дробит слой tiers


def parse_groups(path):
    """Читает плоский YAML вида `ключ:` + список `  - ЗНАЧЕНИЕ`."""
    sections, current, top = {}, None, None
    for raw in open(path, encoding="utf-8"):
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue
        if re.match(r"^\w[\w_]*:$", line):
            top = line[:-1]
            current = None if top == "groups" else top
            if current:
                sections.setdefault(current, [])
            continue
        m = re.match(r"^  (\w[\w_]*):$", line)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            continue
        m = re.match(r"^\s+-\s+(\S+)$", line)
        if m and current:
            sections[current].append(m.group(1))
    return sections


def eligible():
    """Активы, способные попасть хотя бы в одно окно walk-forward."""
    u = json.load(open(UNIVERSE, encoding="utf-8"))
    end = date.fromisoformat(u["archive_as_of"])
    cutoff = (end - timedelta(days=MIN_HISTORY)).isoformat()
    keep = {a for a, v in u["assets"].items()
            if v["asset_class"] == "crypto"
            and v.get("binance_symbol")
            and v["listed"] <= cutoff}
    return keep, cutoff


def main():
    sections = parse_groups(GROUPS)
    working, cutoff = eligible()

    meta = {}
    for name in ("duplicate_listings", "mechanically_linked",
                 "low_confidence", "unlabeled"):
        meta[name] = sections.pop(name, [])

    dup_pairs = [tuple(p.split("/")) for p in meta["duplicate_listings"]]
    mech_pairs = [tuple(p.split("/")) for p in meta["mechanically_linked"]]
    low = set(meta["low_confidence"])
    unlabeled = set(meta["unlabeled"])
    excluded = set(sections.get("excluded_special", []))
    tradable = {g: v for g, v in sections.items() if g != "excluded_special"}

    assigned = [a for v in sections.values() for a in v]
    dupes = {a: n for a, n in Counter(assigned).items() if n > 1}
    assigned_set = set(assigned)

    named = assigned_set | unlabeled
    ghosts = sorted(named - working)
    missing = sorted(working - named)
    pair_ghosts = sorted({a for p in dup_pairs + mech_pairs for a in p}
                         - working)

    print("=" * 62)
    print("ПОКРЫТИЕ")
    print("=" * 62)
    print(f"  подлежит группировке (листинг до {cutoff}): {len(working)}")
    print(f"  распределено по группам:                    "
          f"{len(assigned_set & working)}")
    print(f"  из них исключено как особые случаи:         "
          f"{len(excluded & working)}")
    print(f"  без метки (сектор назвать нечестно):        "
          f"{len(unlabeled & working)}")
    if working:
        cov = len(assigned_set & working) / len(working) * 100
        print(f"  покрытие:                                   {cov:.1f} %")
    print(f"  из размеченных метка ненадёжна:             {len(low)}"
          f" ({100*len(low)/max(1, len(assigned_set)):.0f} %)")

    print()
    print("=" * 62)
    print("ПРОБЛЕМЫ")
    print("=" * 62)
    both = sorted(assigned_set & unlabeled)
    stray_low = sorted(low - assigned_set)
    problems = False
    for title, items, hint in (
        ("дубликаты между группами", sorted(dupes), None),
        ("и в группе, и в unlabeled", both, "удалить из unlabeled"),
        ("нет в универсуме", ghosts,
         "опечатка либо инструмент отсутствует на одной из площадок"),
        ("в парах, но нет в универсуме", pair_ghosts, None),
        ("помечены low_confidence, но не в группах", stray_low, None),
        ("не упомянуты вовсе", missing, None),
    ):
        if items:
            problems = True
            print(f"  {title} ({len(items)}): " + ", ".join(items))
            if hint:
                print(f"    -> {hint}")
    if not problems:
        print("  не обнаружено")

    print()
    print("=" * 62)
    print("РАЗМЕР ГРУПП И ПРОСТРАНСТВО ПОИСКА")
    print("=" * 62)
    total_pairs = 0
    big = []
    for g, v in sorted(tradable.items(), key=lambda kv: -len(kv[1])):
        live = [a for a in set(v) if a in working]
        n = len(live)
        pairs = n * (n - 1) // 2
        total_pairs += pairs
        flag = ""
        if pairs > BIG_GROUP_PAIRS:
            flag = "  <-- дробит слой tiers"
            big.append(g)
        print(f"  {g:<22} {n:>3} активов  {pairs:>5} пар{flag}")

    # Пары одинаковых активов вычитаются: их спред постоянен по
    # построению, и в отбор они не идут.
    dup_in = sum(1 for a, b in dup_pairs if a in working and b in working)
    total_pairs -= dup_in

    n_all = len(working)
    print()
    print(f"  без группировки:  {n_all * (n_all - 1) // 2:>6} пар")
    print(f"  с группировкой:   {total_pairs:>6} пар"
          f"  (вычтено пар-двойников: {dup_in})")
    if n_all > 1:
        red = (1 - total_pairs / (n_all * (n_all - 1) / 2)) * 100
        print(f"  сокращение:       {red:>6.1f} %")
    if big:
        print()
        print("  Крупные группы намеренно не дроблены здесь: деление по")
        print("  обороту принадлежит моменту окна, а не сегодняшнему дню.")
        print("  Группы под дробление: " + ", ".join(big))
    print()
    print("  При контроле FDR ожидаемое число ложных срабатываний примерно")
    print("  пропорционально числу тестов, поэтому сокращение пространства")
    print("  поиска напрямую уменьшает объём мусора в отборе.")


if __name__ == "__main__":
    main()
