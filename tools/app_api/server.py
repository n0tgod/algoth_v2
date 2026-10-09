#!/usr/bin/env python3
"""HTTPS-API приложения Algoth (спека 15 §7, §7a, этап Y0).

Что здесь есть: вход (Sign in with Apple или токен оператора для
первого аккаунта), сессии, ключи биржи с проверкой прав у Bybit и
запечатыванием, подписки на ячейки стратегий в сухом режиме, состояние
подписок с проверками эквити и режима хеджирования, события, книги
(прокси свода `/dca` сборщика). Чего нет намеренно: команд исполнителю и
перевода в live — это этапы Y3–Y4, и на их адреса сервер отвечает словами
«этап не построен», а не молчит.

Процесс не видит ни приватного ключа конвертов, ни ключей биржи после
проверки: секрет живёт в памяти ровно на время проверки и запечатывается.

    .venv/bin/python tools/app_api/server.py            # 443, TLS из out/tls
    .venv/bin/python tools/app_api/server.py --plain 8443   # без TLS (тесты)
"""
import argparse
import http.server
import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import db as DBM                                              # noqa: E402
import sealed                                                 # noqa: E402
import bybit                                                  # noqa: E402

SCHEMA = 1
OUT = os.path.join(HERE, "out")
SERVER_IP = "116.203.146.99"
COLLECTOR = "http://127.0.0.1:8765"
PAGE_TOKEN = os.path.join(ROOT, "research", "b1_book", "out", "token.txt")
MAX_ACCOUNTS = 1                 # §7a.6: до юридической проверки — один аккаунт
EQUITY_TTL = 60.0
RATE = {"read": (60, 60.0), "write": (10, 60.0)}     # (запросов, окно с)
STAGE_NOT_BUILT = "этап не построен: команды и перевод в live — Y3–Y4 спеки 15"
PAIR_PREFIX = "pair_"


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), *a, flush=True)


class RateLimiter:
    def __init__(self):
        self.hits = {}
        self.lock = threading.Lock()

    def allow(self, who, kind):
        n, win = RATE[kind]
        now = time.time()
        with self.lock:
            q = [t for t in self.hits.get((who, kind), []) if now - t < win]
            if len(q) >= n:
                self.hits[(who, kind)] = q
                return False
            q.append(now)
            self.hits[(who, kind)] = q
            return True


class App:
    """Логика API без HTTP: её гоняют проверки напрямую."""

    def __init__(self, dbpath, pub, operator_token=None, venue=bybit, dca_fetch=None,
                 apple_verify=None, server_ip=SERVER_IP, max_accounts=MAX_ACCOUNTS):
        self.db = DBM.DB(dbpath)
        self.pub = pub
        self.operator_token = operator_token
        self.venue = venue
        self.dca_fetch = dca_fetch or fetch_dca
        self.apple_verify = apple_verify
        self.server_ip = server_ip
        self.max_accounts = max_accounts
        self.rate = RateLimiter()
        self._dca = {"at": 0.0, "data": None}

    # ------------------------------------------------------------ вход
    def auth_operator(self, token, device=None):
        if not self.operator_token or not token or token != self.operator_token:
            return 403, {"error": "токен оператора не подошёл"}
        op = self.db.operator()
        if op is None:
            aid = self.db.create_account("operator")
            self.db.event(aid, "account", "аккаунт оператора создан")
        else:
            aid = op["id"]
        tok = self.db.new_session(aid, device)
        self.db.event(aid, "auth", "вход оператора", {"device": device})
        return 200, {"session": tok, "account_id": aid, "role": "operator"}

    def auth_apple(self, identity_token, device=None, current=None):
        if self.apple_verify is None:
            return 503, {"error": "вход через Apple не настроен на сервере"}
        try:
            who = self.apple_verify(identity_token or "")
        except ValueError as e:
            # Причина — в журнал процесса (без токена): отказ, которого не
            # видно ни в журнале, ни на телефоне, стоил вечера 09.10.
            log("вход через Apple отвергнут:", str(e))
            return 401, {"error": str(e)}
        except Exception as e:                                 # noqa: BLE001
            log("вход через Apple: сбой проверки:", type(e).__name__, str(e)[:200])
            return 503, {"error": f"проверка токена Apple не удалась: {type(e).__name__}"}
        acc = self.db.account_by_apple(who["sub"])
        if acc is None and current is not None and not current["apple_sub"]:
            # оператор привязывает свой Apple ID к уже существующему аккаунту
            self.db.link_apple(current["id"], who["sub"], who.get("email"))
            acc = self.db.account(current["id"])
            self.db.event(acc["id"], "account", "Apple ID привязан к аккаунту")
        if acc is None:
            if self.db.accounts_count() >= self.max_accounts:
                return 403, {"error": f"регистрация закрыта: аккаунтов не больше {self.max_accounts} "
                                      "до решения владельца (спека 15 §7a.6)"}
            role = "operator" if self.db.accounts_count() == 0 else "user"
            aid = self.db.create_account(role, who["sub"], who.get("email"))
            self.db.event(aid, "account", f"аккаунт создан ({role})")
            acc = self.db.account(aid)
        if acc["status"] != "active":
            return 403, {"error": "аккаунт заморожен"}
        tok = self.db.new_session(acc["id"], device)
        self.db.event(acc["id"], "auth", "вход через Apple", {"device": device})
        return 200, {"session": tok, "account_id": acc["id"], "role": acc["role"]}

    def logout(self, token):
        self.db.drop_session(token)
        return 200, {"ok": True}

    def me(self, acc):
        return 200, {"account_id": acc["id"], "role": acc["role"], "email": acc["email"],
                     "apple_linked": bool(acc["apple_sub"]), "schema": SCHEMA}

    # ------------------------------------------------------------ ключи
    def add_key(self, acc, venue, key, secret):
        if venue != "bybit":
            return 400, {"error": "площадка не поддерживается: только bybit"}
        key = (key or "").strip()
        secret = (secret or "").strip()
        if len(key) < 8 or len(secret) < 8:
            return 400, {"error": "ключ и секрет обязательны"}
        try:
            info = self.venue.query_api(key, secret)
        except bybit.VenueError as e:
            return 400, {"error": f"ключ не прошёл проверку у биржи: {e}"}
        j = bybit.judge_permissions(info, self.server_ip)
        if j["money_moving"]:
            return 400, {"error": "ключ умеет выводить или переводить деньги "
                                  f"({', '.join(j['money_moving'])}): отзовите его и создайте без права вывода",
                         "perms": j}
        if not j["trade_ok"]:
            return 400, {"error": "у ключа нет права торговать контрактами (ContractTrade: Order, Position)"
                                  + (" — он только на чтение" if j["read_only"] else ""), "perms": j}
        warnings = []
        if not j["ip_restricted"]:
            warnings.append("у ключа нет IP-ограничения: добавьте адрес сервера "
                            f"{self.server_ip} в настройках ключа на бирже")
        elif not j["ip_ok"]:
            warnings.append(f"IP-ограничение ключа не содержит адрес сервера {self.server_ip}: "
                            "запросы исполнителя будут отвергнуты")
        equity = None
        try:
            equity = self.venue.wallet_equity(key, secret)
        except bybit.VenueError as e:
            warnings.append(f"эквити не прочитано: {e}")
        modes = {}
        try:
            modes = self.venue.position_mode(key, secret)
        except bybit.VenueError as e:
            warnings.append(f"режим позиций не прочитан: {e}")
        cipher = sealed.seal(self.pub, json.dumps({"venue": venue, "key": key, "secret": secret}).encode("utf-8"))
        del secret
        perms = dict(j, warnings=warnings, position_modes=modes)
        kid = self.db.add_key(acc["id"], venue, key[:4], cipher, perms, j["ip_ok"], equity)
        self.db.event(acc["id"], "key", f"ключ {key[:4]}… добавлен", {"key_id": kid, "warnings": warnings})
        return 200, self._key_view(self.db.key(kid))

    def _key_view(self, r):
        perms = json.loads(r["perms_json"])
        return {"key_id": r["id"], "venue": r["venue"], "prefix": r["key_prefix"], "status": r["status"],
                "trade_ok": perms.get("trade_ok"), "ip_restricted": perms.get("ip_restricted"),
                "ip_ok": bool(r["ip_ok"]), "warnings": perms.get("warnings") or [],
                "checked": r["checked"], "equity_usd": r["equity_usd"], "equity_at": r["equity_at"]}

    def list_keys(self, acc):
        return 200, {"keys": [self._key_view(r) for r in self.db.keys_of(acc["id"])]}

    def delete_key(self, acc, kid):
        r = self.db.key(kid, acc["id"])
        if r is None or r["status"] == "revoked":
            return 404, {"error": "ключа нет"}
        if self.db.subs_on_key(kid, live_only=True):
            return 409, {"error": "ключ держит живую подписку: сперва остановите её"}
        for s in self.db.subs_on_key(kid):
            self.db.close_subscription(s["id"])
        self.db.revoke_key(kid)
        self.db.event(acc["id"], "key", f"ключ {r['key_prefix']}… отозван, подписки на нём закрыты")
        return 200, {"ok": True}

    # ------------------------------------------------------------ книги и ячейки
    def dca(self):
        if self._dca["data"] is None or time.time() - self._dca["at"] > 30:
            self._dca["data"] = self.dca_fetch()
            self._dca["at"] = time.time()
        return self._dca["data"]

    def strategies(self):
        d = self.dca() or {}
        rulers = d.get("rulers") or []
        deps = d.get("deposits") or []
        cells = []
        for r in rulers:
            key = r.get("key") if isinstance(r, dict) else r
            if not key:
                continue
            side = (r.get("side") if isinstance(r, dict) else None) or (
                "both" if str(key).startswith(PAIR_PREFIX) else "short" if str(key).endswith("_h") else "long")
            for dep in deps:
                b = (d.get("books") or {}).get(f"{key}:{int(float(dep))}") or {}
                cells.append({"book": key, "deposit": float(dep), "side": side,
                              "title": (r.get("title") if isinstance(r, dict) else None) or key,
                              # касса БУМАГИ — справка: подписка стартует с депозита (§2)
                              "paper_cash_usd": self.paper_cash(b, float(dep)),
                              "ticket_usd": self.ticket_of(b, float(dep)),
                              "final": ((b.get("all") or {}).get("final")),
                              "n": ((b.get("all") or {}).get("n"))})
        return 200, {"cells": cells, "stale": d.get("stale"), "window": d.get("window")}

    @staticmethod
    def paper_cash(book, deposit):
        """Касса БУМАЖНОЙ книги сейчас: депозит плюс её накопленный нетто.

        Справочное число, не требование к счёту: подписка стартует со
        стартового депозита ячейки (решение владельца 2026-10-09, §2),
        и её касса растёт только её собственными живыми результатами."""
        usd = (book.get("all") or {}).get("usd")
        return None if usd is None else float(deposit) + float(usd)

    @staticmethod
    def ticket_of(book, deposit):
        """Билет ячейки (маржа одной позиции на стартовом депозите), $."""
        t = book.get("ticket")
        if isinstance(t, dict):
            t = t.get(str(int(deposit)))
        try:
            return None if t is None else float(t)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def sub_cash(s, st):
        """Касса ПОДПИСКИ: стартовый депозит плюс реализованный нетто её
        собственных живых позиций (`realized_usd` в состоянии; Y0 — 0).
        Размер живой позиции — доля ЭТОЙ кассы, та же доля, которой бумага
        берёт от своего счёта (билет / депозит), §2."""
        return float(s["deposit"]) + float(st.get("realized_usd") or 0.0)

    # ------------------------------------------------------------ подписки
    def add_subscription(self, acc, key_id, book, deposit):
        k = self.db.key(key_id, acc["id"])
        if k is None or k["status"] != "ok":
            return 404, {"error": "ключа нет или он отозван"}
        try:
            deposit = float(deposit)
        except (TypeError, ValueError):
            return 400, {"error": "депозит — число из ряда ячеек"}
        st, cells = self.strategies()
        cell = next((c for c in cells["cells"] if c["book"] == book and abs(c["deposit"] - deposit) < 1e-9), None)
        if cell is None:
            return 400, {"error": f"ячейки {book} на {deposit:g} $ нет среди книг сервера"}
        for s in self.db.subs_on_key(key_id):
            if s["book"] == book:
                return 409, {"error": "на этом ключе уже есть подписка на эту книгу"}
        state = {"side": cell["side"], "warnings": []}
        if cell["side"] == "both":
            try:
                modes = self.venue_modes(k)
                off = sorted(s for s, m in modes.items() if m != "hedge")
                state["hedge_mode"] = "off" if off else ("on" if modes else "n/a")
                state["hedge_off_syms"] = off[:50]
                if off:
                    state["warnings"].append(f"режим хеджирования выключен у {len(off)} имён — "
                                             "двусторонняя книга живьём работать не сможет")
            except bybit.VenueError as e:
                state["hedge_mode"] = "n/a"
                state["warnings"].append(f"режим хеджирования не прочитан: {e}")
        sid = self.db.add_subscription(acc["id"], key_id, book, deposit, state)
        self.db.event(acc["id"], "subscription", f"подписка {book} на {deposit:g} $ (сухой режим)",
                      {"subscription_id": sid, "warnings": state["warnings"]})
        return 200, self._sub_view(self.db.subscription(sid, acc["id"]))

    def venue_modes(self, k):
        """Режим позиций по ключу. Секрет открыть этот процесс НЕ может:
        режим читается ключом только при добавлении (см. add_key) — здесь
        отдаётся то, что записано, либо «не измерено»."""
        perms = json.loads(k["perms_json"])
        return perms.get("position_modes") or {}

    def _sub_view(self, s):
        st = json.loads(s["state_json"] or "{}")
        return {"subscription_id": s["id"], "key_id": s["key_id"], "book": s["book"],
                "deposit": s["deposit"], "mode": s["mode"], "side": st.get("side"),
                "hedge_mode": st.get("hedge_mode", "n/a"), "warnings": st.get("warnings") or [],
                "created": s["created"]}

    def list_subscriptions(self, acc):
        return 200, {"subscriptions": [self._sub_view(s) for s in self.db.subscriptions_of(acc["id"])]}

    def delete_subscription(self, acc, sid):
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "подписки нет"}
        if s["mode"] == "live":
            return 409, {"error": "подписка в живом режиме: сперва disarm"}
        self.db.close_subscription(sid)
        self.db.event(acc["id"], "subscription", f"подписка {s['book']} закрыта")
        return 200, {"ok": True}

    # ------------------------------------------------------------ состояние
    def state(self, acc):
        d = self.dca() or {}
        subs = []
        for s in self.db.subscriptions_of(acc["id"]):
            k = self.db.key(s["key_id"])
            st = json.loads(s["state_json"] or "{}")
            b = (d.get("books") or {}).get(f"{s['book']}:{int(s['deposit'])}") or {}
            cash = self.sub_cash(s, st)
            paper = self.paper_cash(b, s["deposit"])
            equity = k["equity_usd"] if k else None
            eq_age = (time.time() - k["equity_at"]) if (k and k["equity_at"]) else None
            warnings = list(st.get("warnings") or [])
            equity_ok = None
            if equity is not None and cash is not None:
                equity_ok = equity >= cash
                if not equity_ok:
                    warnings.append(f"на счёте {equity:,.0f} $, подписка требует {cash:,.0f} $ — входов не будет")
            else:
                warnings.append("эквити счёта не прочитано")
            subs.append({"subscription_id": s["id"], "book": s["book"], "deposit": s["deposit"],
                         "mode": s["mode"], "side": st.get("side"),
                         "cash_usd": cash, "realized_usd": float(st.get("realized_usd") or 0.0),
                         "paper_cash_usd": paper, "ticket_usd": self.ticket_of(b, s["deposit"]),
                         "equity_usd": equity, "equity_age_s": eq_age,
                         "equity_ok": equity_ok,
                         "idle_usd": (None if equity is None or cash is None else max(0.0, equity - cash)),
                         "shortfall_usd": (None if equity is None or cash is None else max(0.0, cash - equity)),
                         "hedge_mode": st.get("hedge_mode", "n/a"),
                         "min_order_share": None,                 # Y1: не измерено
                         "positions": [], "orders": [], "reconcile": None,
                         "halt": None, "warnings": warnings})
        ev = [dict(e) for e in self.db.events_of(acc["id"], since=0, limit=10**9)][-20:]
        return 200, {"schema": SCHEMA, "at": time.time(), "live_enabled": os.path.exists(os.path.join(OUT, "LIVE_ENABLED")),
                     "sheet_age_s": None if not d.get("window") else d.get("stale"),
                     "subscriptions": subs, "events_tail": ev}

    def events(self, acc, since):
        return 200, {"events": [dict(e) for e in self.db.events_of(acc["id"], since=since)]}

    def books(self, full=None):
        try:
            d = self.dca_fetch(full=full) if full else self.dca()
        except Exception as e:                                  # noqa: BLE001
            return 502, {"error": f"сервер книг не ответил: {e}"}
        return 200, d or {}


# ------------------------------------------------------------ HTTP

def fetch_dca(full=None):
    try:
        with open(PAGE_TOKEN, encoding="utf-8") as f:
            tok = f.read().strip()
    except OSError:
        tok = ""
    q = {"k": tok}
    if full:
        q["full"] = full
    with urllib.request.urlopen(COLLECTOR + "/dca?" + urllib.parse.urlencode(q), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


class Handler(http.server.BaseHTTPRequestHandler):
    app = None
    server_version = "AlgothAPI/0.1"

    def log_message(self, fmt, *a):                       # в журнал — без query и токенов
        path = str(getattr(self, "path", "") or "").split("?")[0]
        log(self.client_address[0], getattr(self, "command", "?"), path, fmt % a)

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64 * 1024:
            return None
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return None

    def _acc(self):
        auth = self.headers.get("Authorization") or ""
        tok = auth[7:].strip() if auth.startswith("Bearer ") else ""
        s = self.app.db.session(tok)
        if s is None:
            return None, tok
        return self.app.db.account(s["account_id"]), tok

    def _route(self, method):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        if len(parts) < 3 or parts[0] != "api" or parts[1] != "v1":
            return self._send(404, {"error": "нет такого адреса"})
        who = self.client_address[0]
        kind = "write" if method in ("POST", "DELETE") else "read"
        if not self.app.rate.allow(who, kind):
            return self._send(429, {"error": "слишком часто"})
        rest = parts[2:]
        body = self._body() if method in ("POST", "DELETE") else {}
        if body is None:
            return self._send(400, {"error": "тело не JSON или слишком большое"})
        # --- без сессии
        if rest == ["auth", "operator"] and method == "POST":
            return self._send(*self.app.auth_operator(body.get("token"), body.get("device")))
        if rest == ["auth", "apple"] and method == "POST":
            cur, _t = self._acc()
            return self._send(*self.app.auth_apple(body.get("identity_token"), body.get("device"), current=cur))
        if rest == ["health"] and method == "GET":
            return self._send(200, {"ok": True, "schema": SCHEMA})
        acc, tok = self._acc()
        if acc is None:
            return self._send(401, {"error": "нужен вход"})
        if rest == ["auth", "logout"] and method == "POST":
            return self._send(*self.app.logout(tok))
        if rest == ["me"] and method == "GET":
            return self._send(*self.app.me(acc))
        if rest == ["keys"] and method == "GET":
            return self._send(*self.app.list_keys(acc))
        if rest == ["keys"] and method == "POST":
            return self._send(*self.app.add_key(acc, body.get("venue", "bybit"), body.get("key"), body.get("secret")))
        if len(rest) == 2 and rest[0] == "keys" and method == "DELETE":
            return self._send(*self.app.delete_key(acc, rest[1]))
        if rest == ["strategies"] and method == "GET":
            return self._send(*self.app.strategies())
        if rest == ["subscriptions"] and method == "GET":
            return self._send(*self.app.list_subscriptions(acc))
        if rest == ["subscriptions"] and method == "POST":
            return self._send(*self.app.add_subscription(acc, body.get("key_id"), body.get("book"), body.get("deposit")))
        if len(rest) == 2 and rest[0] == "subscriptions" and method == "DELETE":
            return self._send(*self.app.delete_subscription(acc, rest[1]))
        if len(rest) == 3 and rest[0] == "subscriptions" and rest[2] in ("arm", "disarm", "cmd"):
            return self._send(501, {"error": STAGE_NOT_BUILT})
        if rest == ["cmd"]:
            return self._send(501, {"error": STAGE_NOT_BUILT})
        if rest == ["state"] and method == "GET":
            return self._send(*self.app.state(acc))
        if rest == ["events"] and method == "GET":
            return self._send(*self.app.events(acc, (q.get("since") or ["0"])[0]))
        if rest == ["books"] and method == "GET":
            return self._send(*self.app.books((q.get("full") or [None])[0]))
        return self._send(404, {"error": "нет такого адреса"})

    def do_GET(self):                                   # noqa: N802
        self._route("GET")

    def do_POST(self):                                  # noqa: N802
        self._route("POST")

    def do_DELETE(self):                                # noqa: N802
        self._route("DELETE")


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(app, host="0.0.0.0", port=443, tls_dir=None):
    Handler.app = app
    srv = Server((host, port), Handler)
    if tls_dir:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(os.path.join(tls_dir, "cert.pem"), os.path.join(tls_dir, "key.pem"))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def read_operator_token(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plain", type=int, default=None, help="порт без TLS (только проверки)")
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    out = a.out
    os.makedirs(out, exist_ok=True)
    pub = sealed.read_pub(out)
    import apple                                           # noqa: E402  (сеть — только при входе)
    app = App(os.path.join(out, "app.sqlite"), pub,
              operator_token=read_operator_token(os.path.join(out, "operator_token.txt")),
              apple_verify=apple.verify)
    if a.plain:
        srv = make_server(app, port=a.plain, tls_dir=None)
        log(f"API без TLS на {a.plain} (режим проверок)")
    else:
        srv = make_server(app, port=a.port, tls_dir=os.path.join(out, "tls"))
        log(f"API на {a.port} с TLS")
    with open(os.path.join(out, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"started": time.time(), "port": a.plain or a.port, "pid": os.getpid(),
                   "host": socket.gethostname()}, f)
    srv.serve_forever()


if __name__ == "__main__":
    main()
