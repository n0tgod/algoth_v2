#!/usr/bin/env python3
"""Сертификат Let's Encrypt для API на 443 (спека 16 L2).

Клиент ACME v2 без сторонних утилит (на машине нет certbot): ключ
аккаунта EC P-256, проверка HTTP-01 — файл в `out/acme/http/<токен>`,
его отдаёт сборщик на порту 80 (`web.py`, без ключа страниц).

Главное свойство: сертификат выпускается на ТОТ ЖЕ ключ, что уже стоит
у API (`out/tls/key.pem`). Приложение закрепляет именно ключ (SPKI), а не
сертификат, — поэтому все установленные сборки продолжают подключаться,
а браузеры видят настоящий сертификат на домен. Прежний сертификат
сохраняется рядом (`cert.pem.<время>`), новый пишется только если
выпуск прошёл целиком и ключ в нём совпал с ключом API.

    run tools/app_api/acme_cert.py                       — выпуск/продление
    run tools/app_api/acme_cert.py --staging             — проба на тестовом центре
    run tools/app_api/acme_cert.py --if-days 30          — только если осталось меньше 30 сут

После выпуска API перезапускается отдельным заданием (restart.py).
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
TLS = os.path.join(OUT, "tls")
ACME = os.path.join(OUT, "acme")
HTTP_DIR = os.path.join(ACME, "http")
DOMAINS = ["algoth.trade", "www.algoth.trade"]
DIRECTORY = {"prod": "https://acme-v02.api.letsencrypt.org/directory",
             "staging": "https://acme-staging-v02.api.letsencrypt.org/directory"}


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_or_make_account_key(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), None)
    k = ec.generate_private_key(ec.SECP256R1())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()))
    os.chmod(path, 0o600)
    return k


def jwk(key):
    n = key.public_key().public_numbers()
    return {"crv": "P-256", "kty": "EC", "x": b64(n.x.to_bytes(32, "big")), "y": b64(n.y.to_bytes(32, "big"))}


def thumbprint(key):
    j = jwk(key)
    return b64(hashlib.sha256(json.dumps(j, sort_keys=True, separators=(",", ":")).encode()).digest())


def spki_pin(pub):
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


class Acme:
    def __init__(self, directory, key):
        self.key = key
        self.dir = self._get(directory)
        self.kid = None
        self.nonce = None

    @staticmethod
    def _get(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())

    def _nonce(self):
        if self.nonce:
            n, self.nonce = self.nonce, None
            return n
        req = urllib.request.Request(self.dir["newNonce"], method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.headers["Replay-Nonce"]

    def post(self, url, payload, tries=3):
        """POST JWS; payload None — POST-as-GET. Возвращает (код, заголовки, тело)."""
        for _ in range(tries):
            prot = {"alg": "ES256", "nonce": self._nonce(), "url": url}
            if self.kid:
                prot["kid"] = self.kid
            else:
                prot["jwk"] = jwk(self.key)
            p64 = b64(json.dumps(prot).encode())
            pl64 = "" if payload is None else b64(json.dumps(payload).encode())
            der = self.key.sign(f"{p64}.{pl64}".encode(), ec.ECDSA(hashes.SHA256()))
            r_, s_ = decode_dss_signature(der)
            sig = b64(r_.to_bytes(32, "big") + s_.to_bytes(32, "big"))
            body = json.dumps({"protected": p64, "payload": pl64, "signature": sig}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/jose+json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    self.nonce = r.headers.get("Replay-Nonce")
                    return r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                self.nonce = e.headers.get("Replay-Nonce")
                raw = e.read()
                try:
                    err = json.loads(raw)
                except ValueError:
                    err = {"detail": raw[:300].decode(errors="replace")}
                if err.get("type", "").endswith("badNonce"):
                    continue
                raise SystemExit(f"ACME отказ {e.code} на {url}: {err.get('type')} — {err.get('detail')}")
        raise SystemExit("ACME: badNonce трижды подряд")

    def account(self):
        st, h, _b = self.post(self.dir["newAccount"], {"termsOfServiceAgreed": True})
        self.kid = h["Location"]
        log(f"аккаунт ACME: {'создан' if st == 201 else 'есть'}")

    def poll(self, url, done=("valid",), bad=("invalid",), what="", wait=90):
        t0 = time.time()
        while time.time() - t0 < wait:
            _st, _h, b = self.post(url, None)
            j = json.loads(b)
            if j.get("status") in done:
                return j
            if j.get("status") in bad:
                raise SystemExit(f"{what}: {j.get('status')} — {json.dumps(j.get('challenges') or j.get('error') or j)[:600]}")
            time.sleep(2)
        raise SystemExit(f"{what}: не дождались за {wait} с")


def self_check(token, body):
    """Свой файл вызова виден снаружи — до того, как звать центр."""
    for d in DOMAINS:
        url = f"http://{d}/.well-known/acme-challenge/{token}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                got = r.read().decode()
        except Exception as e:                                  # noqa: BLE001
            raise SystemExit(f"проверка до центра: {url} не отвечает ({e}) — сборщик без маршрута ACME?")
        if got != body:
            raise SystemExit(f"проверка до центра: {url} отдал не то ({got[:60]!r})")
    log("файл вызова виден по http на обоих именах")


def days_left(path):
    try:
        with open(path, "rb") as f:
            c = x509.load_pem_x509_certificate(f.read())
    except (OSError, ValueError):
        return None, None
    end = c.not_valid_after_utc
    return (end - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400, c


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", action="store_true")
    ap.add_argument("--if-days", type=float, default=None)
    a = ap.parse_args(argv)
    cert_path = os.path.join(TLS, "cert.pem")
    key_path = os.path.join(TLS, "key.pem")
    left, cur = days_left(cert_path)
    is_le = cur is not None and "Let's Encrypt" in cur.issuer.rfc4514_string()
    log(f"сертификат сейчас: {cur.issuer.rfc4514_string() if cur else 'нет'}, осталось {left and round(left)} сут")
    if a.if_days is not None and is_le and left is not None and left > a.if_days:
        log(f"продление не нужно: осталось {left:.0f} сут > {a.if_days:g}")
        return 0
    with open(key_path, "rb") as f:
        tls_key = serialization.load_pem_private_key(f.read(), None)
    pin = spki_pin(tls_key.public_key())
    log(f"ключ API (закреплён в приложении): {pin}")
    env = "staging" if a.staging else "prod"
    acct = load_or_make_account_key(os.path.join(ACME, f"account-{env}.pem"))
    c = Acme(DIRECTORY[env], acct)
    c.account()
    _st, h, b = c.post(c.dir["newOrder"], {"identifiers": [{"type": "dns", "value": d} for d in DOMAINS]})
    order_url, order = h["Location"], json.loads(b)
    os.makedirs(HTTP_DIR, exist_ok=True)
    thumb = thumbprint(acct)
    written = []
    try:
        for az_url in order["authorizations"]:
            _s, _h, ab = c.post(az_url, None)
            az = json.loads(ab)
            name = az["identifier"]["value"]
            if az.get("status") == "valid":
                log(f"{name}: уже подтверждён")
                continue
            ch = next(x for x in az["challenges"] if x["type"] == "http-01")
            body = f"{ch['token']}.{thumb}"
            fn = os.path.join(HTTP_DIR, ch["token"])
            with open(fn, "w") as f:
                f.write(body)
            written.append(fn)
            self_check(ch["token"], body)
            c.post(ch["url"], {})
            c.poll(az_url, what=f"подтверждение {name}")
            log(f"{name}: подтверждён")
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, DOMAINS[0])]))
               .add_extension(x509.SubjectAlternativeName([x509.DNSName(d) for d in DOMAINS]), critical=False)
               .sign(tls_key, hashes.SHA256()))
        c.post(order["finalize"], {"csr": b64(csr.public_bytes(serialization.Encoding.DER))})
        order = c.poll(order_url, what="выпуск")
        _s, _h, chain = c.post(order["certificate"], None)
    finally:
        for fn in written:
            try:
                os.remove(fn)
            except OSError:
                pass
    certs = x509.load_pem_x509_certificates(chain)
    leaf = certs[0]
    if spki_pin(leaf.public_key()) != pin:
        raise SystemExit("ключ в выпущенном сертификате не совпал с ключом API — не записываю")
    log(f"выпущен: {leaf.subject.rfc4514_string()}, до {leaf.not_valid_after_utc:%Y-%m-%d}, "
        f"имена {[n.value for n in leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value]}")
    if a.staging:
        log("тестовый центр: сертификат НЕ записываю (браузеры ему не верят) — проба прошла")
        return 0
    if os.path.exists(cert_path):
        shutil.copy2(cert_path, f"{cert_path}.{time.strftime('%Y%m%d-%H%M%S')}")
    tmp = cert_path + ".new"
    with open(tmp, "wb") as f:
        f.write(chain)
    os.replace(tmp, cert_path)
    log("записан cert.pem (полная цепочка); API перезапускается отдельным заданием")
    return 0


if __name__ == "__main__":
    sys.exit(main())
