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
import subprocess
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import db as DBM                                              # noqa: E402
import sealed
import push as PUSH
import tradelog as TRADES                                             # noqa: E402  (имя не `trades`: так зовётся модуль кассы S8)
import follow as FOLLOW                                                 # noqa: E402
import intents as INTENTS                                               # noqa: E402
import bybit                                                  # noqa: E402

DEFAULT_SIZING = "compound"     # формат размера по умолчанию — как у бумаги
SCHEMA = 1
OUT = os.path.join(HERE, "out")
# Журналы живого исполнителя по подпискам (спека 15 §7.6, §9): пишет
# `bot dca` (Y2), читает приём `trades.ingest`; пробные — `_test_<акк>`.
EXEC_ROOT = os.environ.get("ALGOTH_EXEC_ROOT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bot", "out", "dca")
PUSH_TICK_S = 5
# намерения исполнителя (спека 15 §10a, L1): источники читаются раз в
# минуту — выборы приходят часовым циклом, чаще читать нечего
INTENTS_TICK_S = 60
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
                 apple_verify=None, server_ip=SERVER_IP, max_accounts=MAX_ACCOUNTS,
                 out=None, exec_root=None, sender=None):
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
        self.out = out or os.path.dirname(dbpath) or "."
        self.exec_root = exec_root or EXEC_ROOT
        self.sender = sender or PUSH.Sender(self.out)
        # подмены источников и баров для проверок; None — настоящие
        self.intents_env = None
        self._intents_at = 0.0

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
        sizings = list(d.get("sizings") or [DEFAULT_SIZING])
        cells = []
        for r in rulers:
            key = r.get("key") if isinstance(r, dict) else r
            if not key:
                continue
            side = (r.get("side") if isinstance(r, dict) else None) or (
                "both" if str(key).startswith(PAIR_PREFIX) else "short" if str(key).endswith("_h") else "long")
            for dep, sizing in ((dp, z) for dp in deps for z in sizings):
                b = (d.get("books") or {}).get(self.cell_key(key, dep, sizing)) or {}
                cells.append({"book": key, "deposit": float(dep), "side": side,
                              # формат размера — ось ячейки (решение владельца
                              # 2026-10-09): сложный процент либо фиксированный
                              # билет; подпись — от правил книг, не своя
                              "sizing": sizing,
                              "sizing_title": (d.get("sizing_title") or {}).get(sizing, sizing),
                              "title": (r.get("title") if isinstance(r, dict) else None) or key,
                              # касса БУМАГИ — справка: подписка стартует с депозита (§2)
                              "paper_cash_usd": self.paper_cash(b, float(dep)),
                              "ticket_usd": self.ticket_of(b, float(dep)),
                              "final": ((b.get("all") or {}).get("final")),
                              "n": ((b.get("all") or {}).get("n"))})
        return 200, {"cells": cells, "stale": d.get("stale"), "window": d.get("window"),
                     "sizings": sizings, "sizing_title": d.get("sizing_title") or {},
                     "sizing_plain": d.get("sizing_plain") or {}}

    @staticmethod
    def cell_key(book, deposit, sizing=None):
        """Ключ книги в своде `/dca`: та же схема, что у `rules.cell_key` —
        `книга:депозит`, у фиксированного билета с хвостом `:fixed`."""
        k = f"{book}:{int(float(deposit))}"
        return k if (sizing or DEFAULT_SIZING) == DEFAULT_SIZING else f"{k}:{sizing}"

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
    def add_subscription(self, acc, key_id, book, deposit, sizing=None):
        k = self.db.key(key_id, acc["id"])
        if k is None or k["status"] != "ok":
            return 404, {"error": "ключа нет или он отозван"}
        try:
            deposit = float(deposit)
        except (TypeError, ValueError):
            return 400, {"error": "депозит — число из ряда ячеек"}
        st, cells = self.strategies()
        sizing = sizing or DEFAULT_SIZING
        if sizing not in cells["sizings"]:
            return 400, {"error": f"формат размера {sizing!r} книгам неизвестен: "
                                  + ", ".join(cells["sizings"])}
        cell = next((c for c in cells["cells"] if c["book"] == book
                     and abs(c["deposit"] - deposit) < 1e-9 and c["sizing"] == sizing), None)
        if cell is None:
            return 400, {"error": f"ячейки {book} на {deposit:g} $ нет среди книг сервера"}
        for s in self.db.subs_on_key(key_id):
            # одна книга на ключ в ЛЮБОМ формате: две подписки одной книги
            # торговали бы одни имена на одном счёте и ломали сверку
            if s["book"] == book:
                return 409, {"error": "на этом ключе уже есть подписка на эту книгу"}
        state = {"side": cell["side"], "sizing": sizing, "warnings": []}
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
        self.db.event(acc["id"], "subscription", f"подписка {book} на {deposit:g} $, {sizing} (сухой режим)",
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
                "sizing": st.get("sizing") or DEFAULT_SIZING,
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

    # ------------------------------------------------------------ живой режим
    def live_enabled(self):
        return os.path.exists(os.path.join(self.out, "LIVE_ENABLED"))

    def set_live_enabled(self, acc, on):
        """Рубильник оператора (§7a.5): без него ни одна подписка в live
        не переводится. Выключение НЕ останавливает работающих — для
        этого у подписки `disarm` и `kill`."""
        if acc["role"] != "operator":
            return 403, {"error": "рубильник — только оператору"}
        path = os.path.join(self.out, "LIVE_ENABLED")
        if on:
            with open(path, "w") as f:
                f.write(str(time.time()))
        elif os.path.exists(path):
            os.remove(path)
        self.db.event(acc["id"], "live", "рубильник живой торговли " + ("ВКЛЮЧЁН" if on else "выключен"))
        return 200, {"live_enabled": self.live_enabled()}

    def sub_dir(self, sid):
        return os.path.join(self.exec_root, sid)

    def exec_status(self, sid):
        try:
            with open(os.path.join(self.sub_dir(sid), "ladder_status.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def arm(self, acc, sid, confirm):
        """Перевод подписки в живые сделки — кнопкой владельца (§7a.4).
        Подтверждение — словом `книга:депозит`: случайное нажатие его не
        наберёт. Проверки машиной; любая не прошла — отказ словами."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "подписки нет"}
        want = f"{s['book']}:{int(float(s['deposit']))}"
        if (confirm or "").strip() != want:
            return 400, {"error": f"подтверждение не совпало: нужно «{want}»"}
        why = []
        if not self.live_enabled():
            why.append("рубильник живой торговли выключен (оператор)")
        k = self.db.key(s["key_id"])
        if k is None or k["status"] != "ok":
            why.append("ключ подписки отозван")
        others = [o for o in self.db.subs_on_key(s["key_id"], live_only=True) if o["id"] != sid]
        if others:
            why.append(f"на этом ключе уже есть живая подписка {others[0]['book']} — две делили бы одни позиции")
        st = json.loads(s["state_json"] or "{}")
        cash = self.sub_cash(s, st)
        if k is not None:
            age = (time.time() - k["equity_at"]) if k["equity_at"] else None
            if k["equity_usd"] is None or age is None or age > 24 * 3600:
                why.append("эквити счёта не измерено за сутки — нажмите «Check account»")
            elif k["equity_usd"] < cash:
                why.append(f"на счёте {k['equity_usd']:,.2f} $, касса подписки {cash:,.2f} $")
        if why:
            self.db.event(acc["id"], "live", f"перевод {s['book']} в live отвергнут: " + "; ".join(why))
            return 409, {"error": "; ".join(why), "reasons": why}
        d = self.sub_dir(sid)
        os.makedirs(d, exist_ok=True)
        for f in ("NO_ENTRIES", "STOP"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
        was = s["mode"]
        self.db.c.execute("UPDATE subscriptions SET mode='live', armed_at=?, armed_by=? WHERE id=?",
                          (time.time(), acc["id"], sid))
        self.db.event(acc["id"], "live", (f"подписка {s['book']} {float(s['deposit']):g} $ переведена в ЖИВЫЕ сделки"
                                          if was != "live" else f"подписка {s['book']}: входы снова включены"),
                      {"subscription_id": sid})
        return 200, {"ok": True, "mode": "live",
                     "note": "исполнитель поднимет сторож в течение 5 минут; первые входы — со следующих выборов"}

    def disarm(self, acc, sid):
        """Входы выключены, открытые позиции исполнитель ведёт дальше
        (цель, пол, срок, охрана рынком). Режим остаётся live."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "подписки нет"}
        if s["mode"] != "live":
            return 409, {"error": "подписка не в живом режиме"}
        d = self.sub_dir(sid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "NO_ENTRIES"), "w") as f:
            f.write(str(time.time()))
        self.db.event(acc["id"], "live", f"подписка {s['book']}: новые входы выключены, позиции ведутся")
        return 200, {"ok": True, "entries": False}

    def to_dry(self, acc, sid):
        """Обратно в сухой режим — только без открытых позиций."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "подписки нет"}
        ex = self.exec_status(sid) or {}
        if ex.get("positions"):
            return 409, {"error": f"у исполнителя открыто позиций {len(ex['positions'])}: сперва «Stop entries» и дождаться закрытия"}
        self.db.c.execute("UPDATE subscriptions SET mode='dry' WHERE id=?", (sid,))
        self.db.event(acc["id"], "live", f"подписка {s['book']} переведена в сухой режим")
        return 200, {"ok": True, "mode": "dry"}

    def kill(self, acc, sid, on):
        """KILL подписки: исполнитель не делает НИЧЕГО (ни заявок, ни отмен)."""
        if acc["role"] != "operator":
            return 403, {"error": "KILL — только оператору"}
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "подписки нет"}
        d = self.sub_dir(sid)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "KILL")
        if on:
            with open(path, "w") as f:
                f.write(str(time.time()))
        elif os.path.exists(path):
            os.remove(path)
        self.db.event(acc["id"], "live", f"подписка {s['book']}: KILL " + ("ВКЛЮЧЁН" if on else "снят"))
        return 200, {"kill": bool(on)}

    def check_account(self, acc, sid, runner=None):
        """Предполётная проверка счёта по кнопке владельца: ключ открывает
        отдельный процесс (`preflight.py`), сюда приходит только текст —
        числа и да/нет, без ключа. Эквити записывается в базу."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "подписки нет"}
        cmd = [sys.executable, os.path.join(HERE, "preflight.py"), "--db", self.db.path,
               "--sub", sid, "--update-equity"]
        try:
            r = (runner or (lambda c: subprocess.run(c, capture_output=True, text=True, timeout=60)))(cmd)
            text = (r.stdout or "") + (("\n" + r.stderr[-800:]) if r.stderr else "")
        except Exception as e:                                  # noqa: BLE001
            return 502, {"error": f"проверка не выполнилась: {type(e).__name__}"}
        self.db.event(acc["id"], "live", f"проверка счёта {s['book']}", {"subscription_id": sid})
        return 200, {"text": text.strip(), "ok": "итог: годен" in text}

    # ------------------------------------------------------------ состояние
    def state(self, acc):
        d = self.dca() or {}
        subs = []
        for s in self.db.subscriptions_of(acc["id"]):
            k = self.db.key(s["key_id"])
            st = json.loads(s["state_json"] or "{}")
            sizing = st.get("sizing") or DEFAULT_SIZING
            b = (d.get("books") or {}).get(self.cell_key(s["book"], s["deposit"], sizing)) or {}
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
            # открытые позиции ячейки — из свода книг, с уровнями строки (Y1);
            # `followed` — открыта после подписки, то есть её ведёт исполнитель
            since = float((st.get("follow") or {}).get("since") or s["created"])
            positions = []
            ex = self.exec_status(s["id"]) if s["mode"] == "live" else None
            if ex is not None:
                cash = float(s["deposit"]) + float(ex.get("realized_usd") or 0.0)
            # У живой подписки позиции — только исполнителя: бумажные под её
            # строкой читались бы позициями на счёте, которых нет.
            for q in ([] if s["mode"] == "live" else ((b.get("open") or {}).get("positions") or [])):
                lv = q.get("levels") or {}
                w = (q.get("walk") or [{}])[-1]
                positions.append({"sym": q.get("sym"), "side": q.get("side"), "at": q.get("at"),
                                  "avg": q.get("avg"), "qty": w.get("qty"), "lev": q.get("lev"),
                                  "paper_margin_usd": q.get("margin"), "depth": q.get("depth"),
                                  "mark_frac": q.get("mark_frac"), "mark_usd": q.get("mark_usd"),
                                  "take_px": lv.get("take_px") if lv else w.get("take"),
                                  "floor_px": lv.get("floor_px"), "liq_px": lv.get("liq_px"),
                                  "term_ts": q.get("sched_end"),
                                  "followed": bool(q.get("at") is not None and float(q["at"]) >= since)})
            if ex is not None:
                for q in ex.get("positions") or []:
                    positions.append({"sym": q.get("sym"), "side": q.get("side"), "at": q.get("pos_at"),
                                      "avg": q.get("avg"), "qty": q.get("qty"), "lev": q.get("lev"),
                                      "margin_usd": q.get("margin_usd"), "depth": q.get("depth"),
                                      "take_px": q.get("take_px"), "floor_px": q.get("floor_px"),
                                      "liq_px": q.get("liq_px"), "term_ts": q.get("term_ts"),
                                      "closing": q.get("closing"), "live": True, "followed": True})
            d_sub = self.sub_dir(s["id"])
            executor = None
            if s["mode"] == "live":
                executor = {"status": ({k: ex.get(k) for k in ("at_ms", "mode", "kill", "no_entries", "paused",
                                                              "realized_usd", "realized_today_usd", "entries_n",
                                                              "closed_n", "rejects_n", "last_error",
                                                              "margin_open_usd", "hedge")} if ex else None),
                            "age_s": (time.time() - float(ex["at_ms"]) / 1000.0) if ex and ex.get("at_ms") else None,
                            "kill": os.path.exists(os.path.join(d_sub, "KILL")),
                            "no_entries": os.path.exists(os.path.join(d_sub, "NO_ENTRIES")),
                            "why_none": (None if ex else "исполнитель ещё не поднят: сторож запускает его в течение 5 минут")}
            subs.append({"subscription_id": s["id"], "book": s["book"], "deposit": s["deposit"],
                         "executor": executor, "armed_at": s["armed_at"],
                         "mode": s["mode"], "side": st.get("side"), "sizing": sizing,
                         "positions": positions, "follow": {k: v for k, v in (st.get("follow") or {}).items()
                                                            if k in ("since", "at", "gaps")},
                         # намерения исполнителя за подписку (L1): счёт, живые,
                         # ждущие бар, сверка с бумагой, ошибка такта
                         "intents": INTENTS.summary(st),
                         "cash_usd": cash, "realized_usd": float(st.get("realized_usd") or 0.0),
                         "paper_cash_usd": paper, "ticket_usd": self.ticket_of(b, s["deposit"]),
                         "equity_usd": equity, "equity_age_s": eq_age,
                         "equity_ok": equity_ok,
                         "idle_usd": (None if equity is None or cash is None else max(0.0, equity - cash)),
                         "shortfall_usd": (None if equity is None or cash is None else max(0.0, cash - equity)),
                         "hedge_mode": st.get("hedge_mode", "n/a"),
                         "min_order_share": None,                 # не измерено
                         "orders": [], "reconcile": None,
                         "halt": None, "warnings": warnings})
        ev = [dict(e) for e in self.db.events_of(acc["id"], since=0, limit=10**9)][-20:]
        return 200, {"schema": SCHEMA, "at": time.time(), "live_enabled": self.live_enabled(),
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

    # ------------------------------------------------------------ устройства и пуши (§7.5)
    def add_device(self, acc, token, env="prod", build=None):
        tok = str(token or "").strip().lower()
        if not tok or not all(c in "0123456789abcdef" for c in tok) or len(tok) < 32:
            return 400, {"error": "токен устройства — hex-строка APNs"}
        env = env if env in PUSH.HOSTS else "prod"
        self.db.upsert_device(tok, acc["id"], env, (str(build) if build is not None else None))
        return 200, {"ok": True, "devices": len(self.db.devices_of(acc["id"]))}

    def list_devices(self, acc):
        return 200, {"devices": [{"token": d["token"][:8] + "…", "token_tail": d["token"][-6:], "env": d["env"],
                                  "build": d["build"], "status": d["status"], "last_error": d["last_error"],
                                  "last_seen": d["last_seen"]} for d in self.db.devices_of(acc["id"], live_only=False)],
                     "push": PUSH.public_config(self.out)}

    def delete_device(self, acc, token):
        self.db.drop_device(str(token or "").lower(), acc["id"])
        return 200, {"ok": True}

    def push_config(self, acc, team_id, key_id, p8, topic=None):
        if acc["role"] != "operator":
            return 403, {"error": "ключ APNs задаёт только оператор"}
        try:
            r = PUSH.save_config(self.out, team_id, key_id, p8, topic)
        except ValueError as e:
            return 400, {"error": str(e)}
        self.sender._jwt = (0.0, None, None)
        self.db.event(acc["id"], "push", f"ключ APNs задан: {r['key_id']}, тема {r['topic']}")
        return 200, {"ok": True, **r}

    def push_test(self, acc):
        """Пробный пуш на устройства аккаунта — без записи сделки."""
        devs = self.db.devices_of(acc["id"])
        if not devs:
            return 409, {"error": "у аккаунта нет зарегистрированных устройств: откройте приложение и разрешите уведомления"}
        if PUSH.load_config(self.out) is None:
            return 409, {"error": "ключ APNs не задан (оператор: Account → Push notifications)"}
        payload = PUSH.payload_for({"kind": "test", "mode": "test", "reason": "push channel check",
                                    "subscription_id": "test", "id": None}, book="Algoth")
        res = []
        for d in devs:
            r = self.sender.send(d["token"], d["env"], payload)
            if r["status"] != 200:
                self.db.device_failed(d["token"], r["reason"], dead=r["dead"])
            res.append({"token": d["token"][:8] + "…", "env": d["env"], **r})
        return 200, {"devices": len(devs), "sent": sum(1 for r in res if r["status"] == 200), "results": res}

    # ------------------------------------------------------------ сделки исполнителя (§7.6)
    def list_trades(self, acc, since=0, limit=200, mode="live"):
        """Записи журнала исполнителя. По умолчанию — только ЖИВЫЕ (решение
        владельца 10.10: «на вкладке Trades — реальные сделки»); сухие и
        пробные остаются в базе и отдаются по `mode=all` (или `dry`,
        `test`), а их число называется — скрытое не выдаётся за пустое."""
        try:
            since, limit = int(since or 0), max(1, min(int(limit or 200), 500))
        except (TypeError, ValueError):
            return 400, {"error": "since и limit — числа"}
        mode = (mode or "live").strip()
        modes = None if mode == "all" else [m for m in mode.split(",") if m]
        rows = [TRADES.view(r) for r in self.db.trades_of(acc["id"], since=since, limit=limit, modes=modes)]
        by_mode = {}
        for r in self.db.c.execute("SELECT mode, COUNT(*) AS n FROM trades WHERE account_id=? GROUP BY mode",
                                   (acc["id"],)).fetchall():
            by_mode[r["mode"]] = r["n"]
        live = any(s["mode"] == "live" for s in self.db.subscriptions_of(acc["id"]))
        hidden = sum(n for m, n in by_mode.items() if modes is not None and m not in modes)
        note = ("живые сделки исполнителя на бирже" if live else
                "живого исполнителя нет: подписка в сухом режиме")
        if hidden:
            note += f"; сухих и пробных записей скрыто {hidden}"
        return 200, {"trades": rows, "by_mode": by_mode, "mode": mode, "hidden": hidden,
                     "executor_running": "live" if live else "dry", "note": note}

    # Слова исхода — те же, что у строк бумажной книги: карточка позиции
    # одна на бумагу и живое, и два словаря однажды разошлись бы.
    EXIT_WORDS = {"take": "тейк", "floor": "пол", "term": "срок", "market": "рынок",
                  "cmd_close": "команда", "liq": "ликвидация", "mismatch": "вне исполнителя"}

    def live_positions(self, acc):
        """Живые позиции — в ФОРМЕ строки бумажной книги (`sym, side, at, lev,
        margin, entry_px, avg, fills, walk, exit, exit_ts, exit_px, usd,
        pnl_frac, mark_usd, mark_frac, levels`), чтобы приложение рисовало
        их той же карточкой и тем же экраном позиции. Источник — журнал
        исполнителя (§7.6, записи `live`): входы и доливы с ценами, уровни
        глубины и исход записаны им; здесь только сборка по позиции. Отметка
        открытой — из статуса исполнителя (середина последнего такта и
        нереализованное), её комиссии вычитаются: отметка — нетто на сейчас."""
        rows = sorted(self.db.trades_of(acc["id"], since=0, limit=100000, modes=["live"]),
                      key=lambda r: (r["subscription_id"], r["seq"]))
        subs = {s["id"]: s for s in self.db.subscriptions_of(acc["id"])}
        out, by = [], {}
        for r in rows:
            try:
                d = json.loads(r["data_json"] or "{}")
            except ValueError:
                d = {}
            sym, kind = r["sym"], r["kind"]
            at = d.get("pos_at")
            if not sym or at is None:
                continue
            key = (r["subscription_id"], sym, int(float(at)))
            p = by.get(key)
            if kind == "entry":
                s = subs.get(r["subscription_id"])
                margin, lev = r["margin_usd"], r["lev"]
                p = {"sym": sym, "side": r["side"], "book": d.get("book"), "subscription_id": r["subscription_id"],
                     "cell": (f"{s['book']}:{int(float(s['deposit']))}" if s else None),
                     "pos_at": float(at), "at": r["ts"], "lev": lev, "margin": margin,
                     "entry_px": r["px"], "avg": r["avg"] or r["px"], "px_ref": d.get("px_ref"),
                     "slip_bp": d.get("slip_bp"), "fills": [], "walk": [], "depth": 1, "state": "open",
                     "fees": float(d.get("fee_usd") or 0.0), "live_exec": True,
                     "sched_end": d.get("term_ts"),
                     "levels": {"take_px": d.get("take_px"), "floor_px": d.get("floor_px"),
                                "liq_px": d.get("liq_px"), "term_ts": d.get("term_ts")}}
                by[key] = p
                out.append(p)
            if p is None:
                continue
            if kind in ("entry", "rung") and r["qty"] and r["px"]:
                qty = float(r["qty"])
                cum = (p["walk"][-1]["qty"] if p["walk"] else 0.0) + qty
                notl = (float(p["margin"] or 0) * float(p["lev"] or 0)) or None
                w = (qty * float(r["px"]) / notl) if notl else None
                p["fills"].append([r["ts"], r["px"], w])
                p["walk"].append({"at": r["ts"], "px": r["px"], "w": w, "dq": qty, "qty": cum,
                                  "avg": r["avg"], "take": d.get("take_px"), "liq": d.get("liq_px"),
                                  "floor": d.get("floor_px")})
                p["avg"] = r["avg"] or p["avg"]
                p["depth"] = len(p["walk"])
                if kind == "rung":
                    p["fees"] += float(d.get("fee_usd") or 0.0)
                    p["levels"].update({k: d.get(k) for k in ("take_px", "floor_px", "liq_px") if d.get(k) is not None})
            elif kind == "take_set" and r["px"]:
                p["levels"]["take_px"] = r["px"]
                if p["walk"]:
                    p["walk"][-1]["take"] = r["px"]
            elif kind in self.EXIT_WORDS:
                p.update({"state": "closed", "exit": self.EXIT_WORDS[kind], "exit_ts": r["ts"],
                          "exit_px": r["px"], "usd": r["pnl_usd"], "pnl_bp": r["pnl_bp"],
                          "pnl_frac": ((r["pnl_usd"] / p["margin"]) if (r["pnl_usd"] is not None and p["margin"]) else None),
                          "reason": r["reason"]})
        # открытые — отметка исполнителя
        st_cache = {}
        for p in out:
            if p["state"] != "open":
                continue
            sid = p["subscription_id"]
            if sid not in st_cache:
                st_cache[sid] = self.exec_status(sid) or {}
            ex = st_cache[sid]
            q = next((x for x in ex.get("positions") or []
                      if x.get("sym") == p["sym"] and abs(float(x.get("pos_at") or 0) - p["pos_at"]) < 1.0), None)
            if q is None:
                p["mark_why"] = ("исполнитель не прислал статус" if not ex else
                                 "исполнитель этой позиции не держит — исход ждёт записи журнала")
                continue
            if q.get("upnl_usd") is not None:
                net = float(q["upnl_usd"]) + float(q.get("realized_part_usd") or 0.0) - float(q.get("fee_usd") or 0.0)
                p["mark_usd"] = net
                p["mark_frac"] = (net / p["margin"]) if p["margin"] else None
                p["mark_px"] = q.get("mark_px")
                p["last_ts"] = (q.get("mark_at_ms") or 0) / 1000.0
            p["qty"] = q.get("qty")
            p["closing"] = q.get("closing")
            p["levels"].update({"take_px": q.get("take_px") or p["levels"].get("take_px"),
                                "floor_px": q.get("floor_px"), "liq_px": q.get("liq_px")})
        out.sort(key=lambda p: (p["state"] != "open", -float(p.get("exit_ts") or p["at"] or 0)))
        return 200, {"positions": out, "open": sum(1 for p in out if p["state"] == "open"),
                     "closed": sum(1 for p in out if p["state"] == "closed"),
                     "pnl": self.live_pnl(out, subs), "at": time.time()}

    @staticmethod
    def live_pnl(rows, subs):
        """Общий результат живых сделок (владелец 10.10: «на странице trades
        общий пнл по всем сделкам»): реализованное — сумма нетто закрытых
        (исход записан исполнителем, комиссии вычтены), открытое — сумма
        отметок нетто; процент — от суммы депозитов живых подписок.
        Открытая без отметки не превращается в ноль: она считается и
        называется числом (`open_unmarked`)."""
        closed = [p for p in rows if p["state"] == "closed"]
        opened = [p for p in rows if p["state"] == "open"]
        realized = sum(float(p["usd"]) for p in closed if p.get("usd") is not None)
        marked = [p for p in opened if p.get("mark_usd") is not None]
        open_usd = sum(float(p["mark_usd"]) for p in marked)
        dep = sum(float(s["deposit"]) for s in subs.values() if s["mode"] == "live")
        total = realized + open_usd
        wins = sum(1 for p in closed if (p.get("usd") or 0) > 0)
        return {"realized_usd": round(realized, 4), "open_usd": round(open_usd, 4),
                "total_usd": round(total, 4), "deposit_usd": dep,
                "total_pct": (round(total / dep * 100.0, 3) if dep else None),
                "closed_n": len(closed), "open_n": len(opened), "wins_n": wins,
                "open_unmarked": len(opened) - len(marked),
                "fees_usd": round(sum(float(p.get("fees") or 0.0) for p in rows), 4)}

    def trade_test(self, acc, text=None):
        """Пробная строка журнала → приём → запись → пуш: весь канал одной кнопкой."""
        if acc["role"] != "operator":
            return 403, {"error": "пробное событие — только оператор"}
        sid, ev = TRADES.test_event(self.exec_root, acc["id"], text)
        n = TRADES.tick(self.db, self.exec_root, self.sender, log=log)
        row = self.db.c.execute("SELECT * FROM trades WHERE subscription_id=? AND seq=?",
                                (sid, ev["seq"])).fetchone()
        return 200, {"ingested": n, "trade": (TRADES.view(row) if row else None)}

    def intents_tick(self, force=False):
        """Намерения исполнителя по новым выборам источников (L1) — раз в
        `INTENTS_TICK_S`; падение пишется в состояние подписки самим
        модулем и в лог, такт пушей не роняет."""
        now = time.time()
        if not force and now - self._intents_at < INTENTS_TICK_S:
            return 0
        self._intents_at = now
        try:
            return INTENTS.tick(self.db, self.dca(), self.exec_root, log=log, env=self.intents_env)
        except Exception as e:                                  # noqa: BLE001
            log(f"намерения: {e}")
            return 0

    def list_intents(self, acc, sub_id=None, limit=50):
        """Намерения и отказы по подпискам аккаунта — хвост файлов."""
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 50
        out = []
        for s in self.db.subscriptions_of(acc["id"]):
            if sub_id and s["id"] != sub_id:
                continue
            st = json.loads(s["state_json"] or "{}")
            out.append({"subscription_id": s["id"], "book": s["book"], "deposit": s["deposit"],
                        "summary": INTENTS.summary(st),
                        "intents": INTENTS.read_rows(INTENTS.intents_path(self.exec_root, s["id"]), limit),
                        "skips": INTENTS.read_rows(INTENTS.skips_path(self.exec_root, s["id"]), limit)})
        return 200, {"subscriptions": out, "at": time.time()}

    def push_tick(self):
        """Такт фонового потока: намерения по новым выборам (раз в минуту),
        следователь пишет события ячеек подписок (сухой исполнитель),
        затем новые строки журналов → записи → пуши."""
        try:
            self.intents_tick()
            try:
                FOLLOW.tick(self.db, self.dca(), self.exec_root, log=log)
            except Exception as e:                              # noqa: BLE001
                log(f"следователь: {e}")
            return TRADES.tick(self.db, self.exec_root, self.sender, log=log)
        except Exception as e:                                  # noqa: BLE001
            log(f"такт приёма журнала исполнителя: {e}")
            return 0


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
            return self._send(*self.app.add_subscription(acc, body.get("key_id"), body.get("book"),
                                                         body.get("deposit"), body.get("sizing")))
        if len(rest) == 2 and rest[0] == "subscriptions" and method == "DELETE":
            return self._send(*self.app.delete_subscription(acc, rest[1]))
        if len(rest) == 3 and rest[0] == "subscriptions" and method == "POST":
            sid, act = rest[1], rest[2]
            if act == "arm":
                return self._send(*self.app.arm(acc, sid, body.get("confirm")))
            if act == "disarm":
                return self._send(*self.app.disarm(acc, sid))
            if act == "dry":
                return self._send(*self.app.to_dry(acc, sid))
            if act == "kill":
                return self._send(*self.app.kill(acc, sid, bool(body.get("on"))))
            if act == "check":
                return self._send(*self.app.check_account(acc, sid))
            if act == "cmd":
                return self._send(501, {"error": STAGE_NOT_BUILT})
        if rest == ["operator", "live"] and method == "POST":
            return self._send(*self.app.set_live_enabled(acc, bool(body.get("on"))))
        if rest == ["cmd"]:
            return self._send(501, {"error": STAGE_NOT_BUILT})
        if rest == ["state"] and method == "GET":
            return self._send(*self.app.state(acc))
        if rest == ["events"] and method == "GET":
            return self._send(*self.app.events(acc, (q.get("since") or ["0"])[0]))
        if rest == ["books"] and method == "GET":
            return self._send(*self.app.books((q.get("full") or [None])[0]))
        if rest == ["devices"] and method == "GET":
            return self._send(*self.app.list_devices(acc))
        if rest == ["devices"] and method == "POST":
            return self._send(*self.app.add_device(acc, body.get("token"), body.get("env", "prod"), body.get("build")))
        if len(rest) == 2 and rest[0] == "devices" and method == "DELETE":
            return self._send(*self.app.delete_device(acc, rest[1]))
        if rest == ["push", "config"] and method == "GET":
            return self._send(200, PUSH.public_config(self.app.out))
        if rest == ["push", "config"] and method == "POST":
            return self._send(*self.app.push_config(acc, body.get("team_id"), body.get("key_id"),
                                                    body.get("p8"), body.get("topic")))
        if rest == ["push", "test"] and method == "POST":
            return self._send(*self.app.push_test(acc))
        if rest == ["trades"] and method == "GET":
            return self._send(*self.app.list_trades(acc, (q.get("since") or ["0"])[0], (q.get("limit") or ["200"])[0],
                                                    (q.get("mode") or ["live"])[0]))
        if rest == ["intents"] and method == "GET":
            return self._send(*self.app.list_intents(acc, (q.get("sub") or [None])[0], (q.get("limit") or ["50"])[0]))
        if rest == ["positions"] and method == "GET":
            return self._send(*self.app.live_positions(acc))
        if rest == ["trades", "test"] and method == "POST":
            return self._send(*self.app.trade_test(acc, body.get("text")))
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
              apple_verify=apple.verify, out=out)
    if a.plain:
        srv = make_server(app, port=a.plain, tls_dir=None)
        log(f"API без TLS на {a.plain} (режим проверок)")
    else:
        srv = make_server(app, port=a.port, tls_dir=os.path.join(out, "tls"))
        log(f"API на {a.port} с TLS")
    with open(os.path.join(out, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"started": time.time(), "port": a.plain or a.port, "pid": os.getpid(),
                   "host": socket.gethostname(), "exec_root": app.exec_root,
                   "push": PUSH.public_config(out)}, f)

    def pusher():
        # журнал исполнителя → записи → пуши, раз в PUSH_TICK_S; падение
        # такта пишется в лог и не роняет API
        while True:
            app.push_tick()
            time.sleep(PUSH_TICK_S)
    threading.Thread(target=pusher, name="push-tick", daemon=True).start()
    log(f"приём журнала исполнителя: {app.exec_root}, пуши {'настроены' if PUSH.load_config(out) else 'без ключа APNs'}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
