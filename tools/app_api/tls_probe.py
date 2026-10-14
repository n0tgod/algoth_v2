#!/usr/bin/env python3
"""Разведка перед настоящим сертификатом (спека 16 L2): кто слушает 80 и
443, есть ли на машине certbot/acme.sh/openssl, какие модули Python для
ACME есть в .venv, видит ли сервер домен. Ничего не меняет.

    run tools/app_api/tls_probe.py
"""
import importlib
import shutil
import socket
import subprocess
import sys


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        return (r.stdout + r.stderr).strip() or "(пусто)"
    except Exception as e:                                      # noqa: BLE001
        return f"не выполнилось: {e}"


def main():
    print("== слушают 80 и 443 ==")
    print(sh("ss -ltnp | grep -E ':(80|443) '"))
    print("== перенаправления порта 80 (iptables nat) ==")
    print(sh("iptables -t nat -S 2>/dev/null | grep -E 'dport (80|443)' || echo нет"))
    print("== nginx / caddy / apache ==")
    print(sh("systemctl is-active nginx caddy apache2 2>/dev/null"))
    print("== инструменты ==")
    for t in ("certbot", "acme.sh", "openssl", "lego"):
        print(f"{t}: {shutil.which(t) or 'нет'}")
    print("== модули Python ==")
    for m in ("cryptography", "josepy", "acme", "jwt"):
        try:
            mod = importlib.import_module(m)
            print(f"{m}: {getattr(mod, '__version__', 'есть')}")
        except Exception as e:                                  # noqa: BLE001
            print(f"{m}: нет ({type(e).__name__})")
    print("== домен с сервера ==")
    for h in ("algoth.trade", "www.algoth.trade"):
        try:
            print(h, sorted({a[4][0] for a in socket.getaddrinfo(h, 443)}))
        except OSError as e:
            print(h, f"не разрешается: {e}")
    print("== сертификат API сейчас ==")
    print(sh("openssl x509 -in tools/app_api/out/tls/cert.pem -noout -subject -issuer -dates 2>&1"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
