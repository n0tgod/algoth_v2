"""Sign in with Apple: проверка identity token (JWT RS256) ключами Apple.

Ключи берутся с https://appleid.apple.com/auth/keys и держатся час;
проверяются подпись, издатель, аудитория (Bundle ID приложения) и срок.
Результат — стабильный `sub` пользователя и e-mail, если Apple его отдал.
"""
import json
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


def verify(identity_token, audience=BUNDLE_ID, keys=None):
    """→ {'sub', 'email'} или ValueError словами."""
    try:
        header = jwt.get_unverified_header(identity_token)
    except jwt.PyJWTError as e:
        raise ValueError(f"токен Apple не читается: {e}") from e
    kid = header.get("kid")
    jwks = keys if keys is not None else _keys()
    jwk = next((k for k in jwks if k.get("kid") == kid), None)
    if jwk is None:
        raise ValueError("ключ подписи Apple не найден")
    try:
        claims = jwt.decode(identity_token, PyJWK.from_dict(jwk).key, algorithms=["RS256"],
                            audience=audience, issuer=ISSUER)
    except jwt.PyJWTError as e:
        raise ValueError(f"токен Apple отвергнут: {e}") from e
    if not claims.get("sub"):
        raise ValueError("в токене Apple нет sub")
    return {"sub": claims["sub"], "email": claims.get("email")}
