"""Запечатанный конверт для секретов ключей биржи (спека 15 §7a.2).

Схема — «sealed box»: у сервера API есть только ПУБЛИЧНАЯ половина
X25519; на каждый секрет создаётся эфемерная пара, общий секрет идёт
через HKDF-SHA256 в ключ AES-256-GCM. Открыть конверт может лишь тот, у
кого приватная половина (`master.key`, 600) — процесс исполнителя.
Процесс API после запечатывания секрет не помнит и отдать не может.

Формат конверта: b"ASB1" + эфемерный публичный ключ (32) + nonce (12) +
шифротекст с тегом. Версия в заголовке — чтобы смена схемы не читалась
как битые данные.
"""
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"ASB1"
INFO = b"algoth-app-api sealed v1"


def keygen():
    """(приватный PEM, публичный raw 32 байта)."""
    priv = x25519.X25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)
    return pem, pub


def _kdf(shared, eph_pub, pub):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=eph_pub + pub,
                info=INFO).derive(shared)


def seal(pub, plaintext):
    eph = x25519.X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw,
                                            serialization.PublicFormat.Raw)
    shared = eph.exchange(x25519.X25519PublicKey.from_public_bytes(pub))
    key = _kdf(shared, eph_pub, pub)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, MAGIC)
    return MAGIC + eph_pub + nonce + ct


def open_box(priv_pem, blob):
    if not blob.startswith(MAGIC) or len(blob) < 4 + 32 + 12 + 16:
        raise ValueError("конверт не того формата")
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)
    eph_pub = blob[4:36]
    nonce = blob[36:48]
    ct = blob[48:]
    shared = priv.exchange(x25519.X25519PublicKey.from_public_bytes(eph_pub))
    key = _kdf(shared, eph_pub, pub)
    return AESGCM(key).decrypt(nonce, ct, MAGIC)


def write_keypair(dirpath):
    """Пара на диск: приватная — 600, публичная — рядом. Существующую не
    трогает: перезапись приватного ключа сделала бы все конверты нечитаемыми."""
    os.makedirs(dirpath, exist_ok=True)
    kp = os.path.join(dirpath, "master.key")
    pp = os.path.join(dirpath, "master.pub")
    if os.path.exists(kp):
        return False
    pem, pub = keygen()
    fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    with open(pp, "wb") as f:
        f.write(pub)
    return True


def read_pub(dirpath):
    with open(os.path.join(dirpath, "master.pub"), "rb") as f:
        pub = f.read()
    if len(pub) != 32:
        raise ValueError("публичный ключ не 32 байта")
    return pub
