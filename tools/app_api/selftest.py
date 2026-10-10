#!/usr/bin/env python3
"""Самопроверка API на сервере: процесс жив, TLS отвечает, вход оператора
работает, книги читаются. Печатает словами, что прошло и что нет.

    run tools/app_api/selftest.py
"""
import json
import os
import ssl
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def call(base, path, body=None, token=None, ctx=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    port = 443
    try:
        with open(os.path.join(OUT, "status.json"), encoding="utf-8") as f:
            port = int(json.load(f).get("port") or 443)
    except (OSError, ValueError):
        print("status.json нет — процесс API не стартовал ни разу")
    base = f"https://127.0.0.1:{port}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                     # самоподписанный; снаружи — пиннинг в приложении
    try:
        st, h = call(base, "/api/v1/health", ctx=ctx)
        print(f"health: {st} {h}")
    except Exception as e:                               # noqa: BLE001
        print(f"API не отвечает на {base}: {e}")
        sys.exit(1)
    try:
        with open(os.path.join(OUT, "operator_token.txt"), encoding="utf-8") as f:
            tok = f.read().strip()
    except OSError:
        print("токена оператора нет — init.py не запускался")
        sys.exit(1)
    st, a = call(base, "/api/v1/auth/operator", {"token": tok, "device": "selftest"}, ctx=ctx)
    print(f"вход оператора: {st}, аккаунт {a.get('account_id')}, роль {a.get('role')}")
    sess = a.get("session")
    st, me = call(base, "/api/v1/me", token=sess, ctx=ctx)
    # адрес почты в лог не идёт: лог задания уезжает в git
    print(f"me: {st}, роль {me.get('role')}, Apple ID {'привязан' if me.get('apple_linked') else 'не привязан'}")
    st, s = call(base, "/api/v1/strategies", token=sess, ctx=ctx)
    cells = s.get("cells") or []
    print(f"ячеек стратегий: {len(cells)}" + (f", первая {cells[0].get('book')} {cells[0].get('deposit'):g} $, "
                                              f"касса бумаги {cells[0].get('paper_cash_usd')}" if cells else " — книги не прочитаны"))
    st, stt = call(base, "/api/v1/state", token=sess, ctx=ctx)
    print(f"state: {st}, подписок {len(stt.get('subscriptions') or [])}, live_enabled {stt.get('live_enabled')}")
    for x in stt.get("subscriptions") or []:
        it = x.get("intents") or {}
        ex = x.get("executor")
        print(f"  {x.get('book')} {x.get('deposit'):g} $ режим {x.get('mode')}: касса {x.get('cash_usd')}, "
              f"позиций {len(x.get('positions') or [])}, намерений {it.get('n')}, отказов {it.get('n_skips')}, "
              f"возраст источников {it.get('source_age_s')}"
              + (f"; исполнитель: {('нет — ' + str(ex.get('why_none'))) if not ex.get('status') else 'есть'}" if ex else ""))
    st, ps = call(base, "/api/v1/positions", token=sess, ctx=ctx)
    print(f"positions: {st}, открытых {ps.get('open')}, закрытых {ps.get('closed')}")
    for p in ps.get("positions") or []:
        lv = p.get("levels") or {}
        print(f"  {p.get('state')} {p.get('sym')} {p.get('side')} x{p.get('lev')} вход {p.get('entry_px')} "
              f"средняя {p.get('avg')} пол {lv.get('floor_px')} цель {lv.get('take_px')} "
              f"отметка {p.get('mark_usd')} ({p.get('mark_why') or 'есть'}) исход {p.get('exit')} {p.get('usd')}")
    # Отказы исполнителя полным текстом: в приложении причина обрезана
    # строкой, а код площадки стоит в её хвосте.
    st, tr = call(base, "/api/v1/trades?limit=200", token=sess, ctx=ctx)
    rej = [t for t in tr.get("trades") or [] if t.get("kind") == "reject"]
    print(f"trades: {st}, записей {len(tr.get('trades') or [])}, отказов {len(rej)}")
    for t in rej[-8:]:
        print(f"  отказ {t.get('sym')} {t.get('side')}: {t.get('reason') or (t.get('extra') or {}).get('reason')}")
    call(base, "/api/v1/auth/logout", {}, token=sess, ctx=ctx)
    print("ок")


if __name__ == "__main__":
    main()
