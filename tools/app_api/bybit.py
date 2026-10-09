"""Запросы к Bybit V5 от имени ключа аккаунта — только то, что нужно
проверкам спеки 15 §7a: права ключа, эквити, режим позиций.

Секрет живёт в памяти ровно на время вызова; в ошибки и журнал попадает
только префикс ключа. База URL — параметр: проверка гоняется и против
тестовой сети.
"""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

BASE = "https://api.bybit.com"
RECV = "5000"
TIMEOUT = 15
MONEY_MOVING = ("Withdraw", "AccountTransfer", "SubMemberTransfer")


class VenueError(Exception):
    pass


def _get(path, key, secret, params=None, base=BASE):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    qs = urllib.parse.urlencode(sorted(params.items()))
    ts = str(int(time.time() * 1000))
    sig = hmac.new(secret.encode(), (ts + key + RECV + qs).encode(),
                   hashlib.sha256).hexdigest()
    req = urllib.request.Request(base + path + ("?" + qs if qs else ""), headers={
        "X-BAPI-API-KEY": key, "X-BAPI-SIGN": sig, "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": RECV, "User-Agent": "algoth-app-api"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception as e:                                     # noqa: BLE001
        raise VenueError(f"биржа не ответила ({type(e).__name__})") from e
    if int(body.get("retCode", -1)) != 0:
        raise VenueError(f"биржа отказала: {body.get('retMsg') or body.get('retCode')}")
    return body.get("result") or {}


def query_api(key, secret, base=BASE):
    """Права ключа как их видит биржа: словарь прав, IP-список, только-чтение."""
    return _get("/v5/user/query-api", key, secret, base=base)


def judge_permissions(info, server_ip):
    """Из ответа `query-api` — вердикт по правилам §7a.2.

    trade_ok — есть торговля контрактами (Order и Position);
    money_moving — есть вывод или переводы (ключ отвергается);
    read_only — ключ только на чтение (торговать нельзя);
    ip_ok — IP-ограничение включает сервер; ips пустой — ограничения нет.
    """
    perms = info.get("permissions") or {}
    contract = set(perms.get("ContractTrade") or [])
    wallet = set(perms.get("Wallet") or [])
    ips = [str(x) for x in (info.get("ips") or []) if str(x) not in ("", "*")]
    read_only = int(info.get("readOnly") or 0) == 1
    return {"trade_ok": ({"Order", "Position"} <= contract) and not read_only,
            "money_moving": sorted(wallet & set(MONEY_MOVING)),
            "read_only": read_only,
            "ip_restricted": bool(ips),
            "ip_ok": (server_ip in ips) if ips else False,
            "ips": ips,
            "contract": sorted(contract),
            "expires": info.get("expiredAt")}


def wallet_equity(key, secret, base=BASE):
    """Эквити единого счёта в долларах. Нет поля — None, не ноль."""
    r = _get("/v5/account/wallet-balance", key, secret,
             {"accountType": "UNIFIED"}, base=base)
    for acc in r.get("list") or []:
        v = acc.get("totalEquity")
        if v not in (None, ""):
            return float(v)
    return None


def position_mode(key, secret, symbols=None, base=BASE):
    """Режим позиций по именам: positionIdx 0 — односторонний, 1/2 — хедж.
    Возвращает {имя: 'hedge' | 'oneway'} по позициям, которые биржа отдаёт
    (пустая позиция у Bybit тоже несёт positionIdx)."""
    out = {}
    cursor = None
    for _ in range(20):
        r = _get("/v5/position/list", key, secret,
                 {"category": "linear", "settleCoin": "USDT", "limit": 200,
                  "cursor": cursor}, base=base)
        for p in r.get("list") or []:
            sym = p.get("symbol")
            if symbols and sym not in symbols:
                continue
            idx = int(p.get("positionIdx") or 0)
            mode = "hedge" if idx in (1, 2) else "oneway"
            if out.get(sym) == "hedge" or sym not in out:
                out[sym] = mode if out.get(sym) != "hedge" else "hedge"
        cursor = r.get("nextPageCursor") or None
        if not cursor:
            break
    return out
