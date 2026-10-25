#!/usr/bin/env python3
"""Ветвь с потолком плеча (спека 18, ось `lev_cap`; владелец 25.10).

Потолок МЕНЯЕТ исход позиции (пол стоит дальше, маржа та же, нотионал
меньше), поэтому сестра не вид над записью, как охрана, а свой счёт ядром:
записи основной линейки с плечом выше потолка пересчитываются
`run_short.replay_cells` с политикой `lev_cap` (`run_d10.one_position`) и
лежат в своём кэше `cache/recs-cap<потолок>.jsonl` под подписью кэша
коротких + потолок. Записи с плечом не выше потолка — те же, что у основной
книги, бит в бит.

Пересчёт дорогой на старой записи (август из бакета, ~30 с на имя), поэтому
идёт кусками по именам и ложится на диск после каждого куска: снятый прогон
продолжает с места, часовой прогон досчитывает только новое и открытое.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "cache")
CHUNK = 12                       # имён на кусок пересчёта: кэш пишется после каждого


def cache_path(cap, base_path=None):
    """Путь кэша потолка; рядом с кэшем коротких, если тот не на своём месте (тесты)."""
    d = os.path.dirname(base_path) if base_path else CACHE_DIR
    return os.path.join(d, f"recs-cap{float(cap):g}.jsonl")


def cap_sig(cap):
    import run_short as S                                      # noqa: E402
    return dict(S.cache_sig(), lev_cap=float(cap))


def caps_in_use():
    """Потолки, у которых есть книги в реестре."""
    import rules as R                                          # noqa: E402
    return sorted({float(b["lev_cap"]) for b in R.LEV_CAP_BRANCHES.values()})


def read(cap, path=None, log=print):
    """{(линейка, имя, момент): запись с потолком} — что уже пересчитано."""
    import run_paper as RP                                     # noqa: E402
    cache, why = RP.read_cache(path or cache_path(cap), sig=cap_sig(cap))
    if why:
        log(f"кэш потолка {float(cap):g}× не используется: {why}")
    return {((pair[0] if isinstance(pair, (list, tuple)) else pair), sym, at): r
            for (pair, sym, at), r in cache.items()}


def write(cache, cap, path=None):
    import run_paper as RP                                     # noqa: E402
    path = path or cache_path(cap)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    RP.write_cache({((rk,), sym, at): r for (rk, sym, at), r in cache.items()}, path=path, sig=cap_sig(cap))


def over(cache, cap):
    """Записи основного кэша, которых потолок касается: плечо выше потолка."""
    return {k: r for k, r in cache.items() if float(r.get("lev") or 0) > float(cap)}


def ensure(cache, legs, cap, log=print, path=None, replay=None, chunk=CHUNK, src=None):
    """→ кэш потолка, досчитанный до основного: пересчитаны все записи с
    плечом выше потолка, которых нет или которые ещё открыты.

    `legs` — решения листа (нужны ядру: вход считается от решения, не от
    записи). `replay` — подмена `run_short.replay_cells` в проверках."""
    import run_short as S                                      # noqa: E402
    cap = float(cap)
    done = read(cap, path=path, log=log)
    ov = over(cache, cap)
    by_leg = {(g["sym"], round(float(g["at"]), 3)): g for g in legs}
    need = {}
    for (rk, sym, at), r in ov.items():
        d = done.get((rk, sym, at))
        if (d is None or d.get("state") != "closed") and (sym, at) in by_leg:
            need[(sym, at)] = by_leg[(sym, at)]
    log(f"потолок {cap:g}×: записей с плечом выше — {len(ov)}, пересчитано {sum(1 for k in ov if k in done)}, "
        f"к досчёту решений {len(need)}")
    if need:
        rulers = sorted({rk for (rk, _s, _a) in cache})
        fn = replay or S.replay_cells
        syms = sorted({sym for (sym, _at) in need})
        for ci in range(0, len(syms), chunk):
            part = set(syms[ci:ci + chunk])
            groups = [g for (sym, _at), g in need.items() if sym in part]
            out, _tail = fn(groups, [S.CELL], src=src, log=log, rulers=rulers,
                            adds_of=lambda g, key: {"adds": [], "lev_cap": cap})
            fresh = out.get(S.CELL[0]) or {}
            for k, r in fresh.items():
                if k in ov:
                    done[k] = dict(r)
            write(done, cap, path=path)
            if len(syms) > chunk:
                log(f"потолок {cap:g}×: имён {min(ci + chunk, len(syms))}/{len(syms)}, в кэше {len(done)}")
    return done


def apply(recs, capped, cap, rk, log=None):
    """Записи сестры на линейке `rk`: запись основной книги с плечом выше
    потолка заменяется пересчитанной; нет пересчёта — запись берётся как
    есть, и это считается, а не молчит."""
    cap = float(cap)
    out, n, miss = [], 0, 0
    for r in recs:
        if float(r.get("lev") or 0) > cap:
            c = capped.get((rk, r["sym"], round(float(r["at"]), 3)))
            if c is not None:
                out.append(c)
                n += 1
                continue
            miss += 1
        out.append(r)
    if log:
        log(f"потолок {cap:g}×: записей с потолком {n}" + (f", без пересчёта {miss} — взяты как есть" if miss else ""))
    return out, {"capped": n, "missing": miss, "cap": cap}
