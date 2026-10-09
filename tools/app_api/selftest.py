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
    print(f"me: {st} {me}")
    st, s = call(base, "/api/v1/strategies", token=sess, ctx=ctx)
    cells = s.get("cells") or []
    print(f"ячеек стратегий: {len(cells)}" + (f", первая {cells[0]['book']} {cells[0]['deposit']:g} $ касса {cells[0]['cash_usd']}" if cells else " — книги не прочитаны"))
    st, stt = call(base, "/api/v1/state", token=sess, ctx=ctx)
    print(f"state: {st}, подписок {len(stt.get('subscriptions') or [])}, live_enabled {stt.get('live_enabled')}")
    call(base, "/api/v1/auth/logout", {}, token=sess, ctx=ctx)
    print("ок")


if __name__ == "__main__":
    main()
