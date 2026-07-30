#!/usr/bin/env python3
"""
Разбор бумажных сделок: история и сводка.

Почему сводка не считается здесь
--------------------------------

Ожидание, безубыточная доля побед и кратность риска уже посчитаны в
`t3_brackets/brackets.py` — тем самым кодом, которым сделаны отчёты T3 и
T4. Вторая реализация тех же формул однажды разойдётся с первой, и тогда
страница будет показывать одно, а отчёт утверждать другое, причём обе
стороны будут выглядеть правдоподобно. Поэтому здесь только перевод
имён полей: живая сделка называет итог `pnl_bp` и `state`, замер —
`net_bp` и `outcome`.

Что в сводку не входит
----------------------

Сделки, оборванные перезапуском процесса, результата не имеют вовсе —
цена выхода у них не наступала. Они видны в истории отдельной строкой,
но в статистику не идут: посчитать их нулём значило бы разбавить
ожидание выдумкой.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "t3_brackets"))
import brackets as BR                                     # noqa: E402

sys.path.insert(0, HERE)
from signals import COST_BP                               # noqa: E402

FINISHED = ("цель", "стоп", "время")
# Правила идут параллельно: «лента» — то же, что мерили T3 и T4, «стакан»
# — новое. Первое здесь контрольная рука, и сравнивать надо их друг с
# другом на одном периоде, а не новое правило с числами старого отчёта.
RULES = ("лента", "стакан")


def finished(trades):
    """Только сделки с наступившим выходом."""
    return [t for t in trades
            if t.get("state") in FINISHED and t.get("pnl_bp") is not None]


def as_bracket(t):
    """Живая сделка в именах замера T3/T4."""
    return {"net_bp": float(t["pnl_bp"]), "rr": float(t.get("rr") or 0.0),
            "outcome": t["state"], "stop_bp": float(t.get("stop_bp") or 0.0),
            "held": float(t.get("held") or 0.0)}


def summary(trades):
    """Сводка тем же ядром, что считало отчёты T3 и T4."""
    fin = finished(trades)
    if not fin:
        return None
    out = BR.stats([as_bracket(t) for t in fin], COST_BP)
    out["cut_by_restart"] = len(trades) - len(fin)
    return out


def by_rule(trades):
    """Сводка по каждому правилу отдельно."""
    return {r: summary([t for t in trades if t.get("rule", "лента") == r])
            for r in RULES}


def equity(trades):
    """Кривая счёта по времени закрытия: `(момент, б.п., R)`.

    Накопление в двух единицах сразу, потому что они отвечают на разные
    вопросы: базисные пункты — сколько денег при равном размере позиции,
    R — сколько при равном риске на сделку.
    """
    fin = sorted(finished(trades),
                 key=lambda t: t.get("closed_at") or t.get("t") or 0.0)
    bp = r = 0.0
    out = []
    for t in fin:
        bp += float(t["pnl_bp"])
        r += float(t["pnl_bp"]) / max(float(t.get("stop_bp") or 0.0), 1e-9)
        out.append([round(t.get("closed_at") or t.get("t") or 0.0, 1),
                    round(bp, 1), round(r, 3)])
    return out
