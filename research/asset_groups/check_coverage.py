#!/usr/bin/env python3
"""
Проверка группировки активов: покрытие, дубликаты, опечатки, размер групп.

Сверяет groups.yaml с фактическим универсумом из результатов этапа A0.
Запускается после каждой правки groups.yaml.

Парсер YAML написан вручную под конкретный плоский формат файла —
внешних зависимостей нет.
"""

import json
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
GROUPS = os.path.join(HERE, "groups.yaml")
A0_SUMMARY = os.path.join(HERE, "..", "a0_venue_inventory", "out", "summary.json")

# Границы когорт по глубине истории на площадке исполнения
COHORT_DEEP = "2023-01-01"   # 4+ года
COHORT_MID = "2024-01-01"    # 3+ года


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


def main():
    sections = parse_groups(GROUPS)
    inter = json.load(open(A0_SUMMARY, encoding="utf-8"))["intersection"]

    deep = {e["base"] for e in inter if e["bybit_first"] < COHORT_DEEP}
    mid = {e["base"] for e in inter if COHORT_DEEP <= e["bybit_first"] < COHORT_MID}
    working = deep | mid
    all_assets = {e["base"] for e in inter}

    unclassified = set(sections.pop("unclassified", []))
    excluded = set(sections.get("excluded_special", []))
    tradable = {g: v for g, v in sections.items() if g != "excluded_special"}

    assigned = [a for v in sections.values() for a in v]
    dupes = {a: n for a, n in Counter(assigned).items() if n > 1}
    assigned_set = set(assigned)

    ghosts = sorted((assigned_set | unclassified) - all_assets)
    missing = sorted(working - assigned_set - unclassified)

    print("=" * 62)
    print("ПОКРЫТИЕ")
    print("=" * 62)
    print(f"  универсум A0 (пересечение Bybit x Binance): {len(all_assets)}")
    print(f"  рабочие когорты (история 3+ года):          {len(working)}")
    print(f"  распределено по группам:                    {len(assigned_set & working)}")
    print(f"  в unclassified:                             {len(unclassified & working)}")
    print(f"  исключено как особые случаи:                {len(excluded & working)}")
    if working:
        cov = len(assigned_set & working) / len(working) * 100
        print(f"  покрытие рабочих когорт:                    {cov:.1f} %")

    print()
    print("=" * 62)
    print("ПРОБЛЕМЫ")
    print("=" * 62)
    both = sorted(assigned_set & unclassified)
    if dupes:
        print(f"  дубликаты между группами ({len(dupes)}): " + ", ".join(sorted(dupes)))
    if both:
        print(f"  и в группе, и в unclassified ({len(both)}): " + ", ".join(both))
        print("    -> удалить из unclassified")
    if ghosts:
        print(f"  нет в универсуме A0 ({len(ghosts)}): " + ", ".join(ghosts))
        print("    -> опечатка либо инструмент отсутствует на одной из площадок")
    if missing:
        print(f"  не упомянуты вовсе ({len(missing)}): " + ", ".join(missing))
    if not (dupes or ghosts or missing or both):
        print("  не обнаружено")

    print()
    print("=" * 62)
    print("РАЗМЕР ГРУПП И ПРОСТРАНСТВО ПОИСКА")
    print("=" * 62)
    total_pairs = 0
    for g, v in sorted(tradable.items(), key=lambda kv: -len(kv[1])):
        live = [a for a in set(v) if a in working]
        n = len(live)
        pairs = n * (n - 1) // 2
        total_pairs += pairs
        flag = "  <-- крупная, кандидат на дробление" if pairs > 200 else ""
        print(f"  {g:<22} {n:>3} активов  {pairs:>5} пар{flag}")

    n_all = len(working)
    print()
    print(f"  без группировки:  {n_all * (n_all - 1) // 2:>6} пар")
    print(f"  с группировкой:   {total_pairs:>6} пар")
    if n_all > 1:
        red = (1 - total_pairs / (n_all * (n_all - 1) / 2)) * 100
        print(f"  сокращение:       {red:>6.1f} %")
    print()
    print("  При контроле FDR ожидаемое число ложных срабатываний примерно")
    print("  пропорционально числу тестов, поэтому сокращение пространства")
    print("  поиска напрямую уменьшает объём мусора в отборе.")


if __name__ == "__main__":
    main()
