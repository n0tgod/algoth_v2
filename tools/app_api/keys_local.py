"""Открытие запечатанного ключа подписки — ТОЛЬКО на сервере, только
процессами исполнителя и предполётной проверки (спека 15 §8).

Ключ и секрет не печатаются, не пишутся в журнал и не попадают в
исключения: наружу из этого модуля уходят только сами строки — в
память вызывающего — и отпечаток (`fingerprint`), по которому можно
сравнить два ключа, не показывая ни одного.
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
LIVE_ENV = os.path.expanduser("~/.bybit/live.env")


class KeyError_(Exception):
    pass


def master_pem(out=OUT):
    p = os.path.join(out, "master.key")
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError as e:
        raise KeyError_(f"приватной половины конвертов нет ({type(e).__name__})") from None


def open_sub_key(db, sub_id, out=OUT):
    """(key, secret) ключа подписки. Отказ — словами, без содержимого."""
    import sealed                                            # noqa: E402
    row = db.c.execute("""SELECT k.cipher, k.status FROM subscriptions s
                          JOIN exchange_keys k ON k.id = s.key_id
                          WHERE s.id=?""", (sub_id,)).fetchone()
    if row is None:
        raise KeyError_(f"подписки {sub_id} нет или у неё нет ключа")
    if row["status"] != "ok" or row["cipher"] is None:
        raise KeyError_(f"ключ подписки {sub_id} отозван")
    try:
        d = json.loads(sealed.open_box(master_pem(out), bytes(row["cipher"])).decode("utf-8"))
    except KeyError_:
        raise
    except Exception as e:                                   # noqa: BLE001
        raise KeyError_(f"конверт ключа не открылся ({type(e).__name__})") from None
    k, s = d.get("key") or "", d.get("secret") or ""
    if not k or not s:
        raise KeyError_("в конверте нет ключа или секрета")
    return k, s


def live_env_key(path=LIVE_ENV):
    """API-ключ X3 из `~/.bybit/live.env` (только ключ, не секрет) — для
    сравнения отпечатков. Нет файла — None."""
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                name, _, val = ln.strip().partition("=")
                if name.strip() == "BYBIT_KEY" and val.strip():
                    return val.strip()
    except OSError:
        return None
    return None


def fingerprint(key):
    return None if not key else hashlib.sha256(("algoth:" + key).encode()).hexdigest()[:10]
