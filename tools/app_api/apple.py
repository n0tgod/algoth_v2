"""Sign in with Apple: проверка identity token (JWT RS256) ключами Apple.

Ключи берутся с https://appleid.apple.com/auth/keys и держатся час;
проверяются подпись, издатель, аудитория (Bundle ID приложения) и срок.
Результат — стабильный `sub` пользователя и e-mail, если Apple его отдал.
"""
import json
import os
import time
import urllib.request

import jwt
from jwt import PyJWK

KEYS_URL = "https://appleid.apple.com/auth/keys"
ISSUER = "https://appleid.apple.com"
BUNDLE_ID = "pl.mdsauto.algoth"
_cache = {"at": 0.0, "keys": None}


def _keys():
    if _cache["keys"] is None or time.time() - _cache["at"] > 3600:
        with urllib.request.urlopen(KEYS_URL, timeout=10) as r:
            _cache["keys"] = json.loads(r.read().decode("utf-8")).get("keys") or []
            _cache["at"] = time.time()
    return _cache["keys"]


AUDIENCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "apple_audiences.txt")


def audiences(path=AUDIENCES_FILE):
    """Допустимые аудитории токена (Bundle ID приложения): умолчание плюс
    строки файла на сервере — у сборки TestFlight Bundle ID задаёт секрет
    `IOS_BUNDLE_ID`, и он может отличаться от записанного здесь."""
    out = [BUNDLE_ID]
    try:
        with open(path, encoding="utf-8") as f:
            out += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        pass
    return out


def verify(identity_token, audience=None, keys=None):
    """→ {'sub', 'email'} или ValueError словами (с аудиторией токена при
    несовпадении: она не секрет, а ключ к починке)."""
    try:
        header = jwt.get_unverified_header(identity_token)
        raw = jwt.decode(identity_token, options={"verify_signature": False})
    except jwt.PyJWTError as e:
        raise ValueError(f"токен Apple не читается: {e}") from e
    kid = header.get("kid")
    jwks = keys if keys is not None else _keys()
    jwk = next((k for k in jwks if k.get("kid") == kid), None)
    if jwk is None:
        raise ValueError("ключ подписи Apple не найден")
    auds = audiences() if audience is None else ([audience] if isinstance(audience, str) else list(audience))
    try:
        claims = jwt.decode(identity_token, PyJWK.from_dict(jwk).key, algorithms=["RS256"],
                            audience=auds, issuer=ISSUER)
    except jwt.InvalidAudienceError as e:
        raise ValueError(f"токен Apple отвергнут: аудитория {raw.get('aud')!r} не из допустимых {auds}") from e
    except jwt.PyJWTError as e:
        raise ValueError(f"токен Apple отвергнут: {e}") from e
    if not claims.get("sub"):
        raise ValueError("в токене Apple нет sub")
    return {"sub": claims["sub"], "email": claims.get("email")}
