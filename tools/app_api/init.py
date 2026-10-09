#!/usr/bin/env python3
"""Разовая подготовка API на сервере: пара конвертов, токен оператора,
самоподписанный сертификат. Существующее не перезаписывает — повторный
запуск безопасен и печатает, что уже было.

    run tools/app_api/init.py

Печатает отпечаток сертификата (SHA-256 SPKI, base64) — его приложение
закрепляет (pinning), и первые знаки токена оператора; сам токен читается
владельцем из файла `tools/app_api/out/operator_token.txt` на сервере.
"""
import base64
import datetime as dt
import hashlib
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sealed                                                 # noqa: E402

OUT = os.path.join(HERE, "out")
SERVER_IP = "116.203.146.99"


def certgen(tls_dir, ip=SERVER_IP, days=825):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress
    os.makedirs(tls_dir, exist_ok=True)
    kp, cp = os.path.join(tls_dir, "key.pem"), os.path.join(tls_dir, "cert.pem")
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return False, spki_pin(cert)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "algoth-api")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(cp, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return True, spki_pin(cert)


def spki_pin(cert):
    from cryptography.hazmat.primitives import serialization
    der = cert.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(der).digest()).decode("ascii")


def operator_token(out):
    p = os.path.join(out, "operator_token.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return False, f.read().strip()
    tok = secrets.token_urlsafe(24)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    return True, tok


def main(out=OUT, ip=SERVER_IP):
    os.makedirs(out, exist_ok=True)
    made = sealed.write_keypair(out)
    print(f"пара конвертов: {'создана' if made else 'уже была'} ({out}/master.key, 600)")
    new, tok = operator_token(out)
    print(f"токен оператора: {'создан' if new else 'уже был'}, начинается с {tok[:4]}…; файл {out}/operator_token.txt")
    newc, pin = certgen(os.path.join(out, "tls"), ip=ip)
    print(f"сертификат: {'создан' if newc else 'уже был'} на {ip}; отпечаток SPKI sha256/{pin}")
    return pin


if __name__ == "__main__":
    main()
