"""Зонд: какие решения касса отказывает по шагу объёма и почему.

Для каждой записи кэша реплея длинных и коротких книг — цена входа,
шаг/лот справочника и стоимость минимального объёма; печатает имена, где
минимальный объём дороже $50 (такой отказ возможен и на больших
депозитах), с ценой из записи — чтобы отличить дорогое имя от цены не в
тех единицах. Ничего не пишет.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in ("dca_paper", "dca_ladder", "a1_universe"):
    sys.path.insert(0, os.path.join(ROOT, "research", d))
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_d6 as D6                                           # noqa: E402


def main():
    ins = D6._instruments()
    rows = collections.defaultdict(list)
    for name, (cache, why) in (("long", RP.read_cache()),
                               ("short", S.read_cache(log=lambda *a: None))):
        if why:
            print(name, "кэш:", why)
            continue
        for _k, r in cache.items():
            sym, px = r.get("sym"), r.get("entry_px")
            spec = ins.get(sym)
            if spec is None or not px:
                rows[(name, "нет справочника/цены")].append(sym)
                continue
            step, mq, mn = spec
            q = max(mq, step)
            cost = q * float(px)
            if cost > 50:
                rows[(name, "дорого")].append((sym, float(px), step, mq, round(cost, 1)))
    for k, v in rows.items():
        print(k, len(v))
        if k[1] == "дорого":
            agg = collections.Counter((s, st, mq) for s, _p, st, mq, _c in v)
            for (s, st, mq), n in agg.most_common(30):
                pxs = sorted(p for s2, p, *_ in v if s2 == s)
                print(f"  {s}: {n} решений, шаг {st:g}, лот {mq:g}, цена {pxs[0]:g}…{pxs[-1]:g}")
        else:
            print("  ", collections.Counter(v).most_common(15))


if __name__ == "__main__":
    main()
